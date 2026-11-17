"""PHIẾU NHẬP NCC (P4 — mốc M1; đặc tả kho_mua §3.1, §3.2, §3.4, §3.5, §2.4, §2.9, §4.2) — Purchase Invoice `npp_loai = phieu_nhap`, dãy `PN-.####`
(số cấp LÚC LẬP NHÁP — câu 18, ⚠K: nppsale cấp lúc hoàn thành), `update_stock = 1`, mỗi dòng một lô `<PN>-NNN`; phiếu kho = chính PI (⚠K §7.2 #14).

RPC (giữ tên nppsale — hàm Postgres nguồn ở scratchpad kho_mua/src/<tên>.sql):
- `complete_purchase_invoice` (mig 142 / 145 / 166): khoá Bin (câu đầu) → khoá PI `FOR UPDATE` (⚠K có lợi: nppsale đọc không khoá) → vai → idempotent →
  `PHIEU_KHONG_CON_TAM` → `PHIEU_KHONG_CO_HANG` → `SO_LUONG_KHONG_HOP_LE` (dòng thứ n) → lô + gói lô Inward từng dòng (kho dòng theo hạn — kho cận date
  khi hạn trong ngưỡng, `batches_auto_zone`) → bảng thuế (§2.4) → ghi sổ (hook chiếu công nợ NCC) → giá nhập (`_ghi_gia_nhap_tu_phieu`) → dồn trả trước.
- `cancel_purchase_invoice` (mig 142 / 166 / 238 / 242): phiếu tạm → chỉ dấu huỷ (`npp_huy_*` — §7.3 điểm 1: giữ nháp mang dấu huỷ, khôi phục về nháp
  được như mig 241); đã ghi sổ → `HANG_DA_XUAT` (hàng theo lô luôn chặn — CFD-05 B; câu riêng khi cờ bán vượt tồn bật — §7.3 điểm 12; hàng không lô
  được âm khi mặt hàng cho + NPP cho) → huỷ PI (lõi đảo gói lô, gỡ phân bổ phiếu chi) → lô hết hàng thì tắt (`disabled` ≈ `status 'cancelled'` —
  §7.3 điểm 35) → xếp repost (CFD-07) → dồn trả trước sang khoản khác. `DA_TRA_TIEN` (M3) kiểm TRƯỚC `HANG_DA_XUAT`: tiền Ghi trả `GTN-` + vế Nợ bù
  trừ `CTN-` trỏ phiếu (phần phiếu chi `PCNCC-` lõi tự gỡ rồi dồn sang khoản khác).
- `khoi_phuc_phieu_nhap` (mig 241): huỷ lúc nháp → bỏ dấu huỷ (về nháp); huỷ lúc đã ghi sổ → amend `PN-xxxx-n` (CFD-01) giữ ngày / giờ ghi sổ gốc (ghi lùi
  → repost), dòng giữ nguyên, nhập vào ĐÚNG các lô cũ (không lô mới), mốc hoàn thành gốc (ngày ghi nợ); không ghi đè giá nhập mới hơn.
- `luu_gia_nhap` (mig 234): sửa tay bảng giá nhập — MỘT Item Price mỗi (mặt hàng, đơn vị) trên `NPP Cai Dat.bang_gia_nhap`, sửa tại chỗ.
Id ổn định như nppsale: ba RPC trên nhận tên BẤT KỲ tờ nào của chuỗi amend (`PN-0001`, `PN-0001-1`…) và làm trên tờ CUỐI của chuỗi — trang cũ của
`PN-0001` bấm Huỷ là huỷ `PN-0001-1` như nppsale (một id cho mọi lần khôi phục). `khoi_phuc` trả `id` = tờ còn hiệu lực (giao diện điều hướng theo id
trả về — §7.3 điểm 2).

Ghi thẳng phiếu TẠM qua cổng (`purchase_invoices` / `purchase_invoice_lines` — `nppsale.cong.bang.mua_hang`; nppsale: RLS `FOR ALL` bốn vai, mọi cột kể cả
`status`, không trigger — ⚠K siết theo BP §6.1): thêm / sửa / xoá đầu phiếu nháp, thêm / sửa / xoá dòng của phiếu nháp; đổi `status`, ghi cột của RPC,
đụng phiếu đã hoàn thành (trừ `notes`) / đã huỷ → `USE_RPC`; dòng SL ≤ 0 / giá âm → câu lỗi của `sua_phieu_nhap` ngay lúc lưu (§7.3 điểm 23 — lõi không
nhận PI nháp dòng SL 0, đo M0); tiền dòng âm (giảm dòng > SL × giá — lõi không ghi sổ được dòng giá âm) → `GIA_KHONG_HOP_LE` câu riêng, ở cổng lẫn lúc
Hoàn thành (Q9). Mỗi lần lưu nháp dựng lại bảng thuế, nên tiền phiếu tạm là số lõi tính (nppsale: số trình duyệt gửi, chỉ để xem).
"""
from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from nppsale.cong.bang._chung import kiem_org, tu_choi
from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai
from nppsale.cong.sql import LoiCong
from nppsale.luat import kho_mua as K
from nppsale.luat.tim import khoa_tim_ds
from nppsale.thiet_lap.kho_mua import cai_dat_kho

from . import rpc

DT = "Purchase Invoice"
LOAI = "phieu_nhap"
DAY_SO = "PN-.####"
BANG = "purchase_invoices"
BANG_DONG = "purchase_invoice_lines"
USE_RPC = "USE_RPC: dùng nút Hoàn thành / Huỷ phiếu / Khôi phục / Lưu sửa"
# cột đầu phiếu chỉ RPC đặt (nppsale RLS cho ghi — siết: gửi giá trị → USE_RPC; gửi null như giá trị mặc định thì bỏ qua)
COT_RPC = ("receipt_code", "completed_at", "stock_entry_id", "payable_id", "cancelled_at", "cancelled_by", "cancel_reason", "po_id")
# cột máy tự lo / không port: bỏ qua khi trình duyệt gửi (subtotal / vat / total của phiếu tạm chỉ để xem — lõi tính lại)
COT_BO = ("id", "org_id", "created_by", "created_at", "subtotal", "vat", "total")
COT_DONG_BO = ("id", "org_id", "created_at", "line_total")


# ================================================================================================ hàm nhỏ
def _chu(v) -> str | None:
	if v is None:
		return None
	return v if isinstance(v, str) else json.dumps(v)


def _so(v):
	"""`(x)::numeric` khi trình duyệt gửi chữ — sai → 22P02 như Postgres."""
	if v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)):
		return v
	try:
		return float(str(v).strip())
	except ValueError:
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{v}"', http=400) from None


def _khong_null(v, cot: str, bang: str):
	if v is None:
		raise LoiCong("23502", f'null value in column "{cot}" of relation "{bang}" violates not-null constraint', http=400)
	return v


def _nv(nc) -> str | None:
	"""Người thao tác cho trường Link `NPP Nhan Vien` (`cancelled_by`…): NV đang gọi; Administrator / việc nền → trống."""
	return nc.them.get("nhan_vien") if nc and nc.them else None


def _xep_repost():
	"""CFD-07: sau huỷ / ghi lùi — xếp việc tính lại giá vốn chạy nền song song (Stock Reposting Settings `enable_parallel_reposting`). Tách
	hàm để bài kiểm thay (không đẩy việc thật vào hàng đợi Redis)."""
	from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import enqueue_parallel_reposting

	enqueue_parallel_reposting()


def hom_nay():
	return getdate(nowdate())


# ================================================================================================ bảng thuế (§2.4, CFD-11, PoC 3)
def dung_thue(doc, cd) -> None:
	"""Bảng thuế phiếu nhập do method dựng (`add_taxes_from_item_tax_template = 0`; mọi dòng `category = Total` — giá vốn lô không gồm VAT):
	thuế gõ tay (`npp_co_thue_go_tay`) → MỘT dòng `Actual` vào `tk_thue_dau_vao` = max(0, số gõ) thay các dòng VAT; không thì dòng VAT của mẫu
	`mau_thue_mua` (On Net Total 0% — thuế thật theo Item Tax Template từng dòng); giảm đầu phiếu > 0 → MỘT dòng `Actual` + `Deduct` vào
	`tk_giam_dau_phieu_nhap` = min(giảm, tiền hàng + thuế) (lõi từ chối grand_total < 0 — kẹp = `GREATEST(0, …)` của nppsale). `discount_amount` /
	`apply_discount_on` đầu phiếu để trống (lõi chia giảm vào dòng → hạ thuế + giá vốn — CFD-11)."""
	from erpnext.controllers.accounts_controller import _get_taxes_and_charges

	doc.taxes_and_charges = ""
	doc.set("taxes", [])
	thue_tay = None
	if cint(doc.get("npp_co_thue_go_tay")):
		thue_tay = K.thue_go_tay_pi(doc.get("npp_thue_go_tay"), la_tra=False)
		doc.append("taxes", {"charge_type": "Actual", "account_head": cd.tk_thue_dau_vao, "description": "Thuế GTGT (gõ tay)",
			"tax_amount": float(thue_tay), "category": "Total", "add_deduct_tax": "Add"})
	else:
		for t in _get_taxes_and_charges("Purchase Taxes and Charges Template", cd.mau_thue_mua) or []:
			doc.append("taxes", t)
	giam = flt(doc.get("npp_giam_dau_phieu"))
	if not giam:
		return
	tien = thue = 0.0
	if doc.get("items"):
		doc.run_method("set_missing_values")
		doc.calculate_taxes_and_totals()
		tien, thue = flt(doc.total), flt(doc.total_taxes_and_charges)
	elif thue_tay is not None:
		thue = float(thue_tay)
	g = K.giam_dau_phieu_pi(tien, thue, giam, la_tra=False)
	if g:
		if not cd.get("tk_giam_dau_phieu_nhap"):
			raise NppLoi("CAI_DAT_THIEU: NPP Cai Dat chưa có tài khoản giảm đầu phiếu nhập (tk_giam_dau_phieu_nhap).")
		doc.append("taxes", {"charge_type": "Actual", "account_head": cd.tk_giam_dau_phieu_nhap, "description": "Giảm đầu phiếu",
			"tax_amount": float(g[1]), "category": "Total", "add_deduct_tax": g[0]})


# ================================================================================================ phiếu tạm qua cổng (§4.2)
def _vung_kho(vung, cd) -> str:
	if vung not in K.VUNG:
		raise LoiCong("23514", f'new row for relation "{BANG}" violates check constraint "purchase_invoices_warehouse_zone_check"', http=400)
	return cd.kho_can_date if vung == "date" else cd.kho_ban


def _ap_dau(doc, g: dict, cd) -> None:
	"""Cột nppsale của đầu phiếu → trường PI. Thứ tự / nghĩa theo bảng `purchase_invoices` (§1.2): NOT NULL gửi null → 23502; khoá ngoại sai →
	23503; vùng ngoài {sale, date} → 23514; `vat_override` null ≠ 0 (cờ `npp_co_thue_go_tay`)."""
	for k, v in g.items():
		if k in COT_BO or k == "status":
			continue
		if k in COT_RPC:
			if v is not None:
				raise NppLoi(USE_RPC)
			continue
		if k == "supplier_id":
			_khong_null(v, k, BANG)
			if not frappe.db.exists("Supplier", v):
				raise LoiCong("23503", f'insert or update on table "{BANG}" violates foreign key constraint "purchase_invoices_supplier_id_fkey"',
					http=409)
			doc.supplier = v
		elif k == "invoice_number":
			doc.bill_no = _chu(v)
		elif k == "invoice_date":
			doc.bill_date = getdate(v) if v not in (None, "") else None
		elif k == "warehouse_zone":  # `npp_kho_nhap` giữ lựa chọn — lõi xoá `set_warehouse` khi các dòng khác kho (purchase_invoice.py:311)
			doc.set_warehouse = doc.npp_kho_nhap = _vung_kho(_khong_null(v, k, BANG), cd)
		elif k == "discount":
			doc.npp_giam_dau_phieu = _so(_khong_null(v, k, BANG))
		elif k == "vat_override":
			doc.npp_co_thue_go_tay = 0 if v is None else 1
			doc.npp_thue_go_tay = 0 if v is None else _so(v)
		elif k == "notes":
			doc.npp_ghi_chu = _chu(v)
		else:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{BANG}' in the schema cache", http=400)


def kho_phieu(doc) -> str | None:
	"""Kho người chọn ở đầu phiếu (`warehouse_zone`): `npp_kho_nhap` (lõi xoá `set_warehouse` khi các dòng khác kho) → `set_warehouse`."""
	return doc.get("npp_kho_nhap") or doc.get("set_warehouse")


def _tt(doc) -> str:
	return K.trang_thai_pi(doc.docstatus, doc.get("npp_huy_luc"))


def han_lai(doc) -> None:
	"""Hạn thanh toán của LÕI (`due_date` + lịch thanh toán) tính lại mỗi lần lưu: lõi chỉ tính khi trống, rồi giữ theo lịch đã lập — sửa ngày HĐ
	NCC của phiếu tạm sang sau hạn cũ là lõi từ chối "Due Date cannot be before Supplier Invoice Date" (`party.py:753`, `accounts_controller.py:1165`).
	nppsale không có hạn cho nợ phiếu nhập (`payables.due_date` NULL — hạn của app là `npp_han_thanh_toan`), nên để lõi tính lại theo ngày HĐ /
	ngày ghi sổ hiện tại (§3.1 bước 7)."""
	doc.due_date = None
	doc.set("payment_schedule", [])


def _luu_nhap(doc, cd) -> None:
	"""Lưu phiếu tạm: kiểm dòng (§7.3 điểm 23) → dựng lại bảng thuế → lưu (PI nháp không dòng: bỏ kiểm bắt buộc của bảng items)."""
	K.kiem_dong_phieu((d.qty, d.conversion_factor, d.price_list_rate, d.get("npp_giam_dong")) for d in sorted(doc.items, key=lambda x: x.idx))
	doc.flags.ignore_permissions = True  # trước dung_thue: set_missing_values của lõi đọc Supplier theo quyền người gọi nếu không có cờ
	han_lai(doc)
	dung_thue(doc, cd)
	doc.flags.ignore_mandatory = not doc.items
	doc.save()


def them_phieu(ds: list[dict], nc) -> list[str]:
	"""INSERT purchase_invoices: phiếu tạm (`status` 'draft' — khác → USE_RPC), số `PN-` cấp ngay (câu 18), người lập = người gọi (bỏ
	`created_by` gửi lên); ngày HĐ thiếu → hôm nay giờ VN (nppsale `CURRENT_DATE` — ngày UTC); vùng thiếu → kho bán."""
	if nc.vai not in K.VAI_MUA_HANG and not nc.bo_qua_rls:
		tu_choi(BANG)
	cd = cai_dat_kho()
	ra = []
	for g in ds:
		g = dict(g or {})
		kiem_org(g, BANG)
		if (g.get("status") or "draft") != "draft":
			raise NppLoi(USE_RPC)
		doc = frappe.new_doc(DT)
		doc.update({"naming_series": DAY_SO, "npp_loai": LOAI, "company": cd.cong_ty, "posting_date": hom_nay(), "set_posting_time": 1,
			"update_stock": 1, "disable_rounded_total": 1, "ignore_pricing_rule": 1, "buying_price_list": cd.bang_gia_nhap,
			"set_warehouse": cd.kho_ban, "npp_kho_nhap": cd.kho_ban, "bill_date": hom_nay(), "npp_giam_dau_phieu": 0})
		_ap_dau(doc, g, cd)
		if not doc.supplier:
			_khong_null(None, "supplier_id", BANG)
		_luu_nhap(doc, cd)
		ra.append(doc.name)
	return ra


def sua_phieu(gia_tri: dict, ids: list[str], nc) -> list[str]:
	"""UPDATE purchase_invoices: vai ngoài bốn vai mua hàng → 0 dòng (như RLS); đổi `status` → USE_RPC; phiếu tạm → lưu nháp + dựng lại thuế;
	phiếu đã hoàn thành → chỉ `notes` (`npp_ghi_chu` AOS), cột khác → USE_RPC (sửa đi qua `sua_phieu_nhap`); phiếu đã huỷ → USE_RPC."""
	if nc.vai not in K.VAI_MUA_HANG and not nc.bo_qua_rls:
		return []
	cd = cai_dat_kho()
	g = dict(gia_tri or {})
	kiem_org(g, BANG)
	ra = []
	for ten in ids:
		doc = frappe.get_doc(DT, ten)
		tt = _tt(doc)
		if "status" in g and g["status"] != tt:
			raise NppLoi(USE_RPC)
		if tt == "draft":
			_ap_dau(doc, g, cd)
			_luu_nhap(doc, cd)
		elif tt == "completed" and not (set(g) - set(COT_BO) - {"status", "notes"}):
			if "notes" in g:
				doc.db_set("npp_ghi_chu", _chu(g["notes"]))
		else:
			raise NppLoi(USE_RPC)
		ra.append(ten)
	return ra


def xoa_phieu(ids: list[str], nc) -> list[str]:
	"""DELETE purchase_invoices: chỉ phiếu chưa ghi sổ (nháp, kể cả nháp mang dấu huỷ) — số PN bỏ trống (câu 18); đã ghi sổ → USE_RPC."""
	if nc.vai not in K.VAI_MUA_HANG and not nc.bo_qua_rls:
		return []
	ra = []
	for ten in ids:
		if cint(frappe.db.get_value(DT, ten, "docstatus")) != 0:
			raise NppLoi(USE_RPC)
		frappe.delete_doc(DT, ten, ignore_permissions=True, force=True)
		ra.append(ten)
	return ra


def _ap_dong(doc, r, g: dict, cd) -> None:
	"""Cột nppsale của một dòng → Purchase Invoice Item (BP §5.9): đơn giá → `price_list_rate`; giảm dòng (TIỀN cả dòng) → `npp_giam_dong`;
	`rate` / `discount_amount` = tiền dòng / SL, giảm / SL (precision 4 — `luat.kho_mua.dong_pi`); thuế suất (tỉ lệ) → `npp_thue_suat` + Item Tax
	Template "VAT n%"; kho dòng = kho đầu phiếu (hoàn thành mới đặt kho theo hạn)."""
	from nppsale.rpc.don_hang import _dam_bao_uom
	from nppsale.thiet_lap.ban_hang import mau_thue_dong

	for k, v in g.items():
		if k in COT_DONG_BO or k in ("invoice_id", "sort_order"):
			continue
		if k == "product_id":
			_khong_null(v, k, BANG_DONG)
			if not frappe.db.exists("Item", v):
				raise LoiCong("23503", f'insert or update on table "{BANG_DONG}" violates foreign key constraint '
					'"purchase_invoice_lines_product_id_fkey"', http=409)
			r.item_code = v
		elif k == "unit_name":
			_dam_bao_uom(_khong_null(v, k, BANG_DONG))
			r.uom = v
		elif k == "quantity":
			r.qty = _so(_khong_null(v, k, BANG_DONG))
		elif k == "unit_price":
			r.price_list_rate = _so(_khong_null(v, k, BANG_DONG))
		elif k == "line_discount":
			r.npp_giam_dong = _so(_khong_null(v, k, BANG_DONG))
		elif k == "vat_rate":
			r.npp_thue_suat = _so(_khong_null(v, k, BANG_DONG))
		elif k == "conversion_factor":
			r.conversion_factor = _so(_khong_null(v, k, BANG_DONG))
		elif k == "notes":
			r.npp_ghi_chu = _chu(v)
		else:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{BANG_DONG}' in the schema cache", http=400)
	r.price_list_rate = flt(r.price_list_rate)
	r.npp_giam_dong = flt(r.get("npp_giam_dong"))
	r.npp_thue_suat = flt(r.get("npp_thue_suat"))
	r.conversion_factor = r.conversion_factor if r.conversion_factor is not None else 1
	r.item_tax_template = mau_thue_dong(r.npp_thue_suat, cd.cong_ty)
	r.warehouse = kho_phieu(doc)
	r.margin_type, r.margin_rate_or_amount, r.discount_percentage = "", 0, 0
	if flt(r.qty) > 0:
		x = K.dong_pi(r.qty, r.price_list_rate, r.npp_giam_dong)
		r.rate, r.discount_amount = float(x["rate"]), float(x["discount_amount"])
		if not r.rate and r.price_list_rate:
			r.discount_percentage = 100  # tiền dòng 0 mà có đơn giá: lõi thấy rate 0 thì tính lại theo giá bảng — 100 % giữ 0
	else:
		r.rate, r.discount_amount = r.price_list_rate, 0


def _dong_moi(doc, g: dict, cd, thu: int):
	r = doc.append("items", {})
	r.flags._npp_thu = (flt(g.get("sort_order")) if g.get("sort_order") is not None else 10 ** 9, thu)
	_ap_dong(doc, r, g, cd)
	if not r.item_code:
		_khong_null(None, "product_id", BANG_DONG)
	if not r.uom:
		_khong_null(None, "unit_name", BANG_DONG)
	return r


def _xep_dong(doc) -> None:
	"""Thứ tự dòng = `sort_order` trình duyệt gửi (STT 1-based người dùng thấy), hoà → thứ tự gửi; dòng cũ giữ vị trí. `idx` = `sort_order` cổng."""
	ds = sorted(doc.items, key=lambda r: getattr(r.flags, "_npp_thu", None) or (flt(r.idx), -1))
	for i, r in enumerate(ds, 1):
		r.idx = i
	doc.items = ds


def _phieu_nhap_tam(ten: str | None):
	"""Phiếu cha của lời ghi dòng: không có → khoá ngoại 23503; không còn là phiếu tạm → USE_RPC (cha đã ghi sổ / đã huỷ)."""
	if not ten or not frappe.db.exists(DT, {"name": ten, "npp_loai": LOAI}):
		raise LoiCong("23503", f'insert or update on table "{BANG_DONG}" violates foreign key constraint "purchase_invoice_lines_invoice_id_fkey"',
			http=409)
	doc = frappe.get_doc(DT, ten)
	if _tt(doc) != "draft":
		raise NppLoi(USE_RPC)
	return doc


def them_dong(ds: list[dict], nc) -> list[str]:
	"""INSERT purchase_invoice_lines (saveReceiptLines: xoá hết rồi chèn lại theo `sort_order`) — trả tên từng dòng mới theo thứ tự gửi."""
	if nc.vai not in K.VAI_MUA_HANG and not nc.bo_qua_rls:
		tu_choi(BANG_DONG)
	cd = cai_dat_kho()
	theo_phieu: dict = {}
	for g in ds:
		g = dict(g or {})
		theo_phieu.setdefault(_chu(g.get("invoice_id")), []).append(g)
	ra = []
	for pn, dong in theo_phieu.items():
		doc = _phieu_nhap_tam(pn)
		moi = [_dong_moi(doc, g, cd, i) for i, g in enumerate(dong)]
		_xep_dong(doc)
		_luu_nhap(doc, cd)
		ra += [r.name for r in moi]
	return ra


def sua_dong(gia_tri: dict, ids: list[str], nc) -> list[str]:
	if nc.vai not in K.VAI_MUA_HANG and not nc.bo_qua_rls:
		return []
	cd = cai_dat_kho()
	g = dict(gia_tri or {})
	if g.get("invoice_id") is not None:
		raise NppLoi(USE_RPC)  # chuyển dòng sang phiếu khác
	ra = []
	for ten in ids:
		doc = _phieu_nhap_tam(frappe.db.get_value("Purchase Invoice Item", ten, "parent"))
		r = next(x for x in doc.items if x.name == ten)
		if "sort_order" in g:
			r.flags._npp_thu = (flt(g["sort_order"]), 0)
		_ap_dong(doc, r, g, cd)
		_xep_dong(doc)
		_luu_nhap(doc, cd)
		ra.append(ten)
	return ra


def xoa_dong(ids: list[str], nc) -> list[str]:
	if nc.vai not in K.VAI_MUA_HANG and not nc.bo_qua_rls:
		return []
	cd = cai_dat_kho()
	theo_phieu: dict = {}
	for ten in ids:
		theo_phieu.setdefault(frappe.db.get_value("Purchase Invoice Item", ten, "parent"), []).append(ten)
	ra = []
	for pn, ds in theo_phieu.items():
		doc = _phieu_nhap_tam(pn)
		doc.set("items", [x for x in doc.items if x.name not in ds])
		_xep_dong(doc)
		_luu_nhap(doc, cd)
		ra += ds
	return ra


# ================================================================================================ khoá + chuỗi amend
def _hieu_luc(ten: str | None) -> str | None:
	"""Tờ CUỐI của chuỗi amend chứa `ten` (đọc thường — chỉ dùng ở bước chuẩn bị, trước khi khoá)."""
	if not ten:
		return None
	for _ in range(100):
		x = frappe.db.sql(f"SELECT `name` FROM `tab{DT}` WHERE `amended_from` = %s ORDER BY `creation` DESC LIMIT 1", ten)
		if not x:
			return ten
		ten = x[0][0]
	return ten


def _hang_cua(ten: str | None) -> set:
	return {r[0] for r in frappe.db.sql("SELECT DISTINCT `item_code` FROM `tabPurchase Invoice Item` WHERE `parent` = %s", ten)} if ten else set()


def _chuan_bi_pn(p_invoice_id=None, p_reason=None):
	"""Đọc trước khi khoá (cổng commit sau bước này): người gọi, cài đặt, tờ cuối của chuỗi + mặt hàng của nó → frappe.local — câu ĐẦU của hàm là
	khoá Bin (ảnh chụp REPEATABLE READ lập ở câu đọc thường đầu tiên SAU khoá — PoC 1d)."""
	hien_tai()
	cai_dat_kho()
	ten = _hieu_luc(_chu(p_invoice_id))
	frappe.local._npp_pn = (_chu(p_invoice_id), ten, _hang_cua(ten))


def _da_chuan_bi(p_invoice_id) -> tuple[str | None, set]:
	x = getattr(frappe.local, "_npp_pn", None)
	frappe.local._npp_pn = None  # dùng MỘT lần — lời gọi nội bộ sau đó (cùng tiến trình) đọc lại, không lấy ảnh cũ của lượt trước
	if x and x[0] == _chu(p_invoice_id):
		return x[1], x[2]
	ten = _hieu_luc(_chu(p_invoice_id))  # gọi nội bộ không qua cổng
	return ten, _hang_cua(ten)


def _khoa(ten: str | None, hang: set, cd):
	"""Khoá Bin (mặt hàng của tờ, đọc ở bước chuẩn bị) → khoá PI `FOR UPDATE`, theo chuỗi amend tới tờ cuối (đọc có khoá — tờ amend lập đúng lúc
	này thì đi tiếp sang nó). Mặt hàng của tờ đổi giữa hai bước (sửa nháp đồng thời) → khoá thêm Bin của hàng mới. None = không có phiếu nhập."""
	from nppsale.rpc.xuat_hang import _khoa_bin

	_khoa_bin(hang, cd)
	for _ in range(100):
		r = frappe.db.sql(f"""SELECT `name`, `docstatus`, `npp_huy_luc`, `supplier` FROM `tab{DT}` WHERE `name` = %s AND `npp_loai` = %s
			FOR UPDATE""", (ten or "", LOAI), as_dict=True)
		if not r:
			return None
		x = frappe.db.sql(f"SELECT `name` FROM `tab{DT}` WHERE `amended_from` = %s ORDER BY `creation` DESC LIMIT 1 FOR UPDATE", r[0].name)
		if not x:
			break
		ten = x[0][0]
	moi = _hang_cua(r[0].name) - set(hang)
	if moi:
		_khoa_bin(moi, cd)
	return r[0]


def _kiem_vai(ham: str, nc, noi_bo: bool = False) -> None:
	loi = K.loi_vai(ham, nc.vai, noi_bo)
	if loi is not None:
		raise loi


# ================================================================================================ complete_purchase_invoice
@rpc("complete_purchase_invoice", ghi=True, chuan_bi=_chuan_bi_pn)
def complete_purchase_invoice(p_invoice_id=None):
	nc = hien_tai()
	cd = cai_dat_kho()
	ten, hang = _da_chuan_bi(p_invoice_id)
	r = _khoa(ten, hang, cd)
	if r is None:
		raise NppLoi("PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu nhập này.")
	_kiem_vai("complete_purchase_invoice", nc)
	return hoan_thanh(r, nc, cd)


def hoan_thanh(r, nc, cd) -> str:
	"""Thân complete_purchase_invoice (PI đã khoá, vai đã kiểm). Trả tên PI."""
	tt = K.trang_thai_pi(r.docstatus, r.npp_huy_luc)
	if tt == "completed":
		return r.name  # IDEMPOTENT — bấm hai lần / mạng rớt bấm lại không nhập kho hai lần
	if tt != "draft":
		raise NppLoi(f'PHIEU_KHONG_CON_TAM: Phiếu đang ở trạng thái "{tt}" — chỉ phiếu tạm mới hoàn thành được.')
	doc = frappe.get_doc(DT, r.name)
	dong = sorted(doc.items, key=lambda x: x.idx)
	if not dong:
		raise NppLoi("PHIEU_KHONG_CO_HANG: Phiếu chưa có dòng hàng nào.")
	for stt, d in enumerate(dong, 1):
		if flt(d.qty) * flt(d.conversion_factor if d.conversion_factor is not None else 1) <= 0:
			raise K.loi_dong_so_luong(stt)
	for stt, d in enumerate(dong, 1):
		# tiền dòng âm (nháp lọt ngoài cổng — Desk / dữ liệu chuyển sang): nppsale nhận (lô giá vốn âm), lõi từ chối dòng `rate` âm lúc ghi sổ bằng câu
		# tiếng Anh → câu của cổng ghi nháp; lượt riêng SAU kiểm SL để lỗi SL của mọi dòng vẫn ra trước như nppsale (nppsale không có lỗi này)
		if K.tien_dong(d.qty, d.price_list_rate, d.get("npp_giam_dong")) < 0:
			raise K.loi_dong_tien_am(stt)
	from nppsale.rpc.goi_lo import gan_goi_lo, kho_nhan_lo, lap_goi_lo, vung_cua_kho

	luc = now_datetime()
	ngay = luc.date()
	gio = luc.strftime("%H:%M:%S")
	kho = kho_phieu(doc)
	vung = vung_cua_kho(kho, cd) or "sale"
	goc = "-".join(doc.name.split("-")[:2])  # lô theo số GỐC của chuỗi amend (`PN-0042-1` → lô `PN-0042-NNN`)
	for stt, d in enumerate(dong, 1):
		it = frappe.db.get_value("Item", d.item_code, ["has_batch_no", "shelf_life_in_days"], as_dict=True)
		base = flt(d.qty) * flt(d.conversion_factor or 1)
		d.allow_zero_valuation_rate = 1 if not flt(d.rate) else 0
		if not it or not it.has_batch_no:
			d.warehouse = kho  # hàng không lô (câu 14 B): kho người chọn, không lô
			continue
		han = add_days(ngay, cint(it.shelf_life_in_days)) if cint(it.shelf_life_in_days) > 0 else None  # không hạn: trống (CFD-10)
		kho_lo = kho_nhan_lo(vung, han, cd, ngay)
		ma = K.ma_lo_phieu_nhap(goc, stt)
		if frappe.db.exists("Batch", ma):
			raise NppLoi(f"LO_TRUNG_MA: Mã lô {ma} đã có trong sổ — đổi mã lô ấy rồi hoàn thành lại phiếu.")
		frappe.get_doc({"doctype": "Batch", "batch_id": ma, "item": d.item_code, "manufacturing_date": ngay, "expiry_date": han,
			"npp_ngay_nhap": luc, "reference_doctype": DT, "reference_name": doc.name, "npp_kho_tao": kho_lo, "npp_tim_kd": khoa_tim_ds(ma),
			"npp_gia_von_lo_rong": float(K.gia_von_lo(d.qty, d.price_list_rate, d.get("npp_giam_dong"), d.conversion_factor or 1)),
		}).insert(ignore_permissions=True)
		d.warehouse = kho_lo
		gan_goi_lo(d, lap_goi_lo("Inward", DT, d.item_code, kho_lo, {ma: base}, ngay, gio, cd.cong_ty))
	doc.update({"posting_date": ngay, "posting_time": gio, "set_posting_time": 1, "update_stock": 1, "disable_rounded_total": 1,
		"ignore_pricing_rule": 1, "buying_price_list": cd.bang_gia_nhap, "npp_hoan_thanh_luc": luc, "npp_han_thanh_toan": None})
	han_lai(doc)  # ngày ghi sổ đổi sang hôm nay — hạn của lõi tính lại
	doc.flags.ignore_permissions = True
	dung_thue(doc, cd)
	doc.save()
	doc.submit()  # hook on_submit: chiếu dòng công nợ NCC (tao_luc = npp_hoan_thanh_luc)
	frappe.local.message_log = []
	ghi_gia_nhap_tu_phieu(doc)
	if flt(doc.grand_total) > 0:
		from nppsale.su_kien.cong_no_ncc import don_tra_truoc_ncc

		don_tra_truoc_ncc(doc.supplier)
	return doc.name


# ================================================================================================ cancel_purchase_invoice
def _lo_cua_dong(ten_pi: str) -> dict:
	"""{tên dòng PI: mã lô} theo gói lô của tờ — đọc cả gói đã huỷ (lõi xoá `serial_and_batch_bundle` trên dòng khi huỷ tờ, gói vẫn mang
	`voucher_detail_no`)."""
	return {d: lo for d, lo in frappe.db.sql("""SELECT b.`voucher_detail_no`, e.`batch_no` FROM `tabSerial and Batch Bundle` b
		JOIN `tabSerial and Batch Entry` e ON e.`parent` = b.`name`
		WHERE b.`voucher_type` = %s AND b.`voucher_no` = %s AND IFNULL(e.`batch_no`, '') != ''
		ORDER BY b.`creation`""", (DT, ten_pi))}


def _ton_lo(lo: str, kho: str | None = None) -> float:
	"""Tồn của lô theo gói lô chưa huỷ (một kho, hoặc mọi kho)."""
	dk = " AND e.`warehouse` = %(k)s" if kho else ""
	return flt(frappe.db.sql(f"""SELECT COALESCE(SUM(e.`qty`), 0) FROM `tabSerial and Batch Entry` e
		JOIN `tabSerial and Batch Bundle` sb ON sb.`name` = e.`parent` AND sb.`docstatus` = 1 AND sb.`is_cancelled` = 0
		WHERE e.`is_cancelled` = 0 AND e.`batch_no` = %(l)s{dk}""", {"l": lo, "k": kho})[0][0])


@rpc("cancel_purchase_invoice", ghi=True, chuan_bi=_chuan_bi_pn)
def cancel_purchase_invoice(p_invoice_id=None, p_reason=None):
	nc = hien_tai()
	cd = cai_dat_kho()
	ten, hang = _da_chuan_bi(p_invoice_id)
	r = _khoa(ten, hang, cd)
	if r is None:
		raise NppLoi("PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu nhập này.")
	_kiem_vai("cancel_purchase_invoice", nc)
	tt = K.trang_thai_pi(r.docstatus, r.npp_huy_luc)
	if tt == "cancelled":
		return r.name
	ly_do = _chu(p_reason)
	if tt == "draft":  # phiếu tạm: chỉ dấu huỷ — chưa đụng kho / công nợ / giá, không cấp gì (§7.3 điểm 1: giữ nháp để khôi phục được)
		frappe.db.set_value(DT, r.name, {"npp_huy_luc": now_datetime(), "npp_huy_boi": _nv(nc), "npp_ly_do_huy": ly_do})
		return r.name
	huy(r.name, ly_do, nc, cd)
	return r.name


def huy(ten: str, ly_do: str | None, nc, cd) -> None:
	"""Thân huỷ phiếu đã ghi sổ (PI đã khoá). Thứ tự nppsale: DA_TRA_TIEN → HANG_DA_XUAT → đảo kho → bỏ nợ → dồn trả trước."""
	from nppsale.luat.cong_no_ncc import loi_da_tra_tien
	from nppsale.su_kien.cong_no_ncc import tien_tra_thang

	doc = frappe.get_doc(DT, ten)
	# mig 242 bước 6: tiền Ghi trả / bù trừ thẳng vào phiếu chặn huỷ — kể cả khi cho tồn âm, TRƯỚC HANG_DA_XUAT (đặc tả §3.2 Frappe bước 3). Phần phiếu
	# chi `PCNCC-` không chặn: lõi gỡ phân bổ khi huỷ (`unlink_payment_on_cancellation_of_invoice` — gỡ cả Ghi trả nên phải kiểm trước), dồn ở cuối.
	tra = tien_tra_thang(ten)
	if tra > 0.005:
		raise loi_da_tra_tien(round(tra, 2))
	lo_dong = _lo_cua_dong(ten)
	cho = bool(cd.get("cho_ban_vuot_ton"))
	chan = []
	khong_lo: dict = {}  # (mặt hàng, kho) → [tên hàng, Σ SL nhập, mặt hàng cho âm]
	for d in sorted(doc.items, key=lambda x: x.idx):
		it = frappe.db.get_value("Item", d.item_code, ["item_name", "has_batch_no", "allow_negative_stock"], as_dict=True) or frappe._dict()
		nhap = flt(d.stock_qty) or flt(d.qty) * flt(d.conversion_factor or 1)
		ten_hang = it.item_name or d.item_code
		lo = lo_dong.get(d.name)
		if lo:  # hàng theo lô: lõi cấm lô âm (CFD-05 B) — đã xuất bớt / đã nhận thêm là chặn, kể cả khi cho bán vượt tồn (⚠K)
			con = _ton_lo(lo, d.warehouse)
			if abs(con - nhap) > 1e-6:
				chan.append((ten_hang, K.muc_hang_da_xuat(ten_hang, nhap, con)))
		else:  # hàng không lô: gộp mọi dòng cùng (mặt hàng, kho) — Bin là MỘT số cho cả kho
			x = khong_lo.setdefault((d.item_code, d.warehouse), [ten_hang, 0.0, bool(it.allow_negative_stock)])
			x[1] += nhap
	for (hang, kho), (ten_hang, nhap, cho_am) in khong_lo.items():
		# Bin của kho thiếu số nhập → chặn, trừ khi mặt hàng cho âm + NPP cho bán vượt tồn (câu 14 B, mig 238); không gộp thì hai dòng cùng
		# mặt hàng mỗi dòng "đủ" một mình mà cả phiếu thiếu — huỷ đẩy Bin âm, lõi báo NegativeStockError thay câu của app
		con = flt(frappe.db.get_value("Bin", {"item_code": hang, "warehouse": kho}, "actual_qty"))
		if con < nhap - 1e-6 and not (cho_am and cho):
			chan.append((ten_hang, K.muc_hang_da_xuat(ten_hang, nhap, con)))
	if chan:
		raise K.loi_hang_da_xuat(chan, cho)
	doc.update({"npp_ly_do_huy": ly_do, "npp_huy_luc": now_datetime(), "npp_huy_boi": _nv(nc)})
	doc.flags.ignore_permissions = True
	doc.cancel()  # lõi đảo gói lô (hàng về đúng lô), đảo GL, gỡ phân bổ phiếu chi (unlink_payment_on_cancellation_of_invoice); hook xoá dòng nợ
	frappe.local.message_log = []
	for lo in dict.fromkeys(lo_dong.values()):
		if _ton_lo(lo) <= 1e-6:
			frappe.db.set_value("Batch", lo, "disabled", 1)  # ≈ `status 'cancelled'` của nppsale (lô ≤ 0 sau huỷ — §7.3 điểm 35)
	_xep_repost()
	from nppsale.su_kien.cong_no_ncc import don_tra_truoc_ncc

	don_tra_truoc_ncc(doc.supplier)  # tiền phiếu chi lõi vừa gỡ khỏi phiếu → dồn sang khoản nợ khác còn mở (mig 242)


# ================================================================================================ khoi_phuc_phieu_nhap
@rpc("khoi_phuc_phieu_nhap", ghi=True, chuan_bi=_chuan_bi_pn)
def khoi_phuc_phieu_nhap(p_invoice_id=None):
	nc = hien_tai()
	cd = cai_dat_kho()
	ten, hang = _da_chuan_bi(p_invoice_id)
	r = _khoa(ten, hang, cd)
	if r is None:
		raise NppLoi("PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu nhập này.")
	_kiem_vai("khoi_phuc_phieu_nhap", nc)
	tt = K.trang_thai_pi(r.docstatus, r.npp_huy_luc)
	if tt != "cancelled":  # IDEMPOTENT (gồm tờ đã có tờ amend sống — `_khoa` đã đi tới tờ ấy)
		return {"id": r.name, "trang_thai": tt, "da_khoi_phuc": False, "so_lo": 0}
	if not r.docstatus:  # huỷ lúc còn phiếu tạm → về phiếu tạm, không đụng kho / công nợ
		frappe.db.set_value(DT, r.name, {"npp_huy_luc": None, "npp_huy_boi": None, "npp_ly_do_huy": None})
		return {"id": r.name, "trang_thai": "draft", "da_khoi_phuc": True, "so_lo": 0}
	moi, so_lo = lap_lai(r.name, cd)
	return {"id": moi, "trang_thai": "completed", "da_khoi_phuc": True, "so_lo": so_lo}


def lap_lai(ten_cu: str, cd) -> tuple[str, int]:
	"""Amend tờ đã huỷ (CFD-01): chép đầu phiếu + dòng (bảng thuế giữ nguyên), bỏ dấu huỷ, ngày / giờ ghi sổ = tờ gốc (ghi lùi → repost; nppsale
	giữ ngày nhập gốc của phiếu kho), mốc hoàn thành gốc (`npp_hoan_thanh_luc` — ngày ghi nợ = completed_at gốc), gói lô Inward vào ĐÚNG lô cũ của
	từng dòng (lô đã tắt lúc huỷ thì mở lại — nppsale `status 'available'`). Trả (tên tờ mới, số lô đã nhập lại)."""
	from nppsale.rpc.goi_lo import gan_goi_lo, lap_goi_lo

	cu = frappe.get_doc(DT, ten_cu)
	lo_idx = {}
	theo_dong = _lo_cua_dong(cu.name)
	for d in cu.items:
		if theo_dong.get(d.name):
			lo_idx[d.idx] = theo_dong[d.name]
	moi = frappe.copy_doc(cu, ignore_no_copy=False)  # như Amend của Desk: trường no_copy của lõi (tiền còn nợ, trạng thái…) không chép
	moi.docstatus = 0  # copy_doc giữ docstatus khi chạy bài (`frappe.in_test`)
	for d in moi.get_all_children():
		d.docstatus = 0
	moi.amended_from = cu.name
	# trường no_copy của lõi mà phiếu cần giữ: dãy số, chiều tờ, ngày HĐ NCC (ngày hiệu lực giá nhập), ghi chú phiếu, giờ ghi sổ
	moi.update({"naming_series": cu.naming_series, "is_return": cu.is_return, "bill_date": cu.bill_date, "npp_ghi_chu": cu.get("npp_ghi_chu"),
		"npp_huy_luc": None, "npp_huy_boi": None, "npp_ly_do_huy": None, "npp_hoan_thanh_luc": cu.get("npp_hoan_thanh_luc"),
		"posting_date": cu.posting_date, "posting_time": str(cu.posting_time), "set_posting_time": 1})
	gio = str(cu.posting_time)
	cu_idx = {d.idx: d for d in cu.items}
	for d in moi.items:
		d.allow_zero_valuation_rate = cu_idx[d.idx].allow_zero_valuation_rate if d.idx in cu_idx else 0  # dòng 0 đ (hàng tặng)
		lo = lo_idx.get(d.idx)
		if not lo:
			continue
		if cint(frappe.db.get_value("Batch", lo, "disabled")):
			frappe.db.set_value("Batch", lo, "disabled", 0)
		gan_goi_lo(d, lap_goi_lo("Inward", DT, d.item_code, d.warehouse, {lo: flt(d.stock_qty) or flt(d.qty) * flt(d.conversion_factor or 1)},
			moi.posting_date, gio, cd.cong_ty))
	moi.flags.ignore_permissions = True
	moi.insert()
	moi.submit()
	frappe.local.message_log = []
	ghi_gia_nhap_tu_phieu(moi)
	_xep_repost()
	if flt(moi.grand_total) > 0:
		from nppsale.su_kien.cong_no_ncc import don_tra_truoc_ncc

		don_tra_truoc_ncc(moi.supplier)
	return moi.name, len(set(lo_idx.values()))


# ================================================================================================ bảng giá nhập (§2.9, §3.5)
def _gia_nhap(sp: str, dv: str, bang: str):
	r = frappe.get_all("Item Price", filters={"price_list": bang, "item_code": sp, "uom": dv}, fields=["name", "valid_from"],
		order_by="creation asc", limit=1)
	return r[0] if r else None


def _ghi_gia(cu, sp: str, dv: str, bang: str, gia, ngay, nguon: str | None) -> None:
	"""MỘT Item Price mỗi (mặt hàng, đơn vị) trên bảng giá nhập — sửa tại chỗ (lõi `check_duplicates` theo `valid_from`: chèn bản mới mỗi ngày là
	ra nhiều giá); người sửa = người gọi (`modified_by` ↔ `updated_by`). Nguồn (`source_invoice_id` = phiếu nhập) ghi vào `reference` SAU khi lưu:
	`ItemPrice.before_save` của lõi đè `reference = customer or supplier` (item_price.py:135–136) — lưu lại tay trên Desk là mất nguồn (chỉ để xem)."""
	from nppsale.rpc.don_hang import _dam_bao_uom

	if cu:
		doc = frappe.get_doc("Item Price", cu.name)
		doc.update({"price_list_rate": float(gia), "valid_from": ngay})
		doc.flags.ignore_permissions = True
		doc.save()
	else:
		_dam_bao_uom(dv)
		doc = frappe.get_doc({"doctype": "Item Price", "price_list": bang, "item_code": sp, "uom": dv, "price_list_rate": float(gia),
			"valid_from": ngay}).insert(ignore_permissions=True)
	doc.db_set("reference", nguon, update_modified=False)


def ghi_gia_nhap_tu_phieu(doc) -> int:
	"""`_ghi_gia_nhap_tu_phieu` (mig 234; trigger khi phiếu sang `completed` + gọi thẳng cuối `sua_phieu_nhap`): phiếu chưa ghi sổ → 0; ngày = ngày HĐ
	NCC (trống → hôm nay VN); mỗi (mặt hàng, đơn vị) dòng dưới cùng có đơn giá > 0; chỉ đè giá có ngày hiệu lực ≤ ngày phiếu; nguồn = tên tờ.
	Huỷ phiếu KHÔNG hoàn giá. Trả số giá đã ghi."""
	from nppsale.su_kien.san_pham import bang_gia_nhap

	if cint(doc.docstatus) != 1:
		return 0
	ngay = getdate(doc.bill_date) if doc.get("bill_date") else hom_nay()
	bang = bang_gia_nhap()
	moi = K.dong_ghi_gia({"product_id": d.item_code, "unit_name": d.uom, "unit_price": d.price_list_rate}
		for d in sorted(doc.items, key=lambda x: x.idx))
	so = 0
	for (sp, dv), gia in moi.items():
		cu = _gia_nhap(sp, dv, bang)
		if cu and not K.duoc_de_gia(cu.valid_from, ngay):
			continue
		_ghi_gia(cu, sp, dv, bang, gia, ngay, doc.name)
		so += 1
	return so


@rpc("luu_gia_nhap", ghi=True)
def luu_gia_nhap(p_dong=None):
	"""Sửa tay bảng giá nhập (mig 234): vai → mảng → từng phần tử (thiếu mặt hàng / đơn vị → mặt hàng + đơn vị trong danh mục → giá trống / null =
	xoá → không phải số → âm) → ghi `round(giá)`, ngày hiệu lực = max(cũ, hôm nay VN), nguồn trống. Lỗi ở phần tử k → lui cả lượt (RPC một giao dịch).
	Không tăng phiên danh mục (bảng giá nhập không phải nguồn tăng — BP)."""
	from nppsale.su_kien.san_pham import bang_gia_nhap

	nc = hien_tai()
	_kiem_vai("luu_gia_nhap", nc)
	ds = p_dong
	if isinstance(ds, str):
		try:
			ds = json.loads(ds)
		except ValueError:
			ds = None
	if not isinstance(ds, list):
		raise NppLoi("GIA_NHAP_SAI: cần danh sách dòng giá")
	bang = bang_gia_nhap()
	luu = bo = 0
	for d in ds:
		sp, dv, chu = K.dong_gia_nhap(d)
		# so trong SQL: UOM là bản ghi (collation của sổ) — đơn vị gõ "hộp" khớp UOM "Hop" như dòng phiếu nhập đã lưu
		if not (frappe.db.exists("Item", {"name": sp, "stock_uom": dv})
				or frappe.db.exists("UOM Conversion Detail", {"parent": sp, "parenttype": "Item", "uom": dv})):
			raise NppLoi(f'GIA_NHAP_SAI: mặt hàng / đơn vị "{dv}" không có trong danh mục')
		gia = K.gia_nhap_so(chu)
		cu = _gia_nhap(sp, dv, bang)
		if gia is None:
			for x in frappe.get_all("Item Price", filters={"price_list": bang, "item_code": sp, "uom": dv}, pluck="name"):
				frappe.delete_doc("Item Price", x, ignore_permissions=True)
			bo += 1
			continue
		_ghi_gia(cu, sp, dv, bang, gia, K.ngay_gia_tay(cu.valid_from if cu else None, hom_nay()), None)
		luu += 1
	return {"luu": luu, "bo": bo}

