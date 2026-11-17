"""PHIẾU TRẢ NCC (P4 — mốc M2; đặc tả kho_mua §3.7–§3.9, §4.3, §2.2, §2.4, §2.6, §7.3 điểm 1 / 2 / 11 / 23 / 26) — Purchase Invoice
`npp_loai = tra_ncc`, `is_return = 1`, KHÔNG `return_against` (tờ trả độc lập — nppsale không lưu phiếu nhập gốc), dãy `PTNCC-.####` (số cấp lúc LẬP
NHÁP như trigger `_danh_so_tra_ncc` mig 240; mã gõ tay / `return_seq` bị bỏ qua — ⚠K: không lấy lại số đã xoá, không đổi tên), `update_stock = 1`,
dòng SL ÂM (cổng trả dương), phiếu kho = chính PI (⚠K §7.2 #14 — nppsale lập `stock_entries` `XK-<giờ>` riêng, một dòng mỗi lô lấy). Ngày trả
(`return_date`) = `bill_date` — trường hiển thị; ghi sổ (kho + công nợ) LÚC BẤM như nppsale (§7.3 điểm 11 — đề xuất).

RPC (giữ tên nppsale — hàm Postgres nguồn ở scratchpad kho_mua/src/<tên>.sql):
- `complete_supplier_return` (mig 228 / 222 / 146 / 071; 141 thuế tỉ lệ): khoá Bin (câu đầu) → khoá PI `FOR UPDATE` → vai (trừ gọi nội bộ) →
  idempotent → `PHIEU_KHONG_CON_NHAP` → `PHIEU_KHONG_CO_HANG` → từng dòng theo thứ tự: lấy lô của mặt hàng TẠI KHO PHIẾU (mặc định kho cận date)
  hạn cũ trước — kể cả lô đã hết hạn (tờ trả không bị lõi kiểm hạn), dòng sau thấy phần dòng trước lấy; thiếu → `INSUFFICIENT_STOCK |` của DÒNG ĐẦU
  thiếu (hàng theo lô LUÔN chặn, kể cả NPP cho bán vượt tồn — ⚠K CFD-05 B; hàng không lô được âm khi mặt hàng cho + NPP cho) → gói lô Outward mỗi
  dòng → bảng thuế ĐẢO DẤU (§2.4) → ghi sổ hôm nay, giờ lấy SAU khoá (hook chiếu dòng công nợ NCC âm — KHÔNG dồn trả trước: mig 242 không đụng
  dòng âm).
- `cancel_supplier_return` (mig 235 / 228 / 222 / 147 / 143): nháp → dấu huỷ (`npp_huy_*` — §7.3 điểm 1: giữ nháp để khôi phục được); đã gửi →
  `DA_CAN_TRU` (khoản giảm đã được cấn trừ — theo Payment Ledger của tờ) → MỞ LẠI lô đã tắt trong gói lô (mig 235 bỏ `LO_DA_DONG`) → huỷ PI (lõi
  cộng trả ĐÚNG lô đã lấy, đảo GL, hook xoá dòng công nợ) → xếp repost (CFD-07).
- `khoi_phuc_phieu_tra_ncc` (mig 241): huỷ lúc nháp → bỏ dấu huỷ (về Nháp); huỷ lúc đã gửi → amend NHÁP `PTNCC-xxxx-n` (CFD-01, ⚠K nppsale giữ
  số) → điểm lưu → thân gửi; lỗi nghiệp vụ (P0001) → lùi về điểm lưu, tờ amend ở Nháp kèm `ly_do` = nguyên câu lỗi; lỗi khác ném ra (lùi cả lượt).
  `PHIEU_KHO_LECH` / đối chiếu `v_khop` của nppsale chỉ còn cho dữ liệu chuyển sang (P8) — tờ Frappe nháp không bao giờ trỏ phiếu kho cũ.
- `sua_phieu_tra_ncc` (MỚI — §3.8 / §7.3 điểm 2, đề xuất): sửa phiếu trả ĐÃ XUẤT trong MỘT giao dịch = thân huỷ + amend nháp theo `p_head` /
  `p_lines` + thân gửi (`p_chi_luu_nhap` = POS "lưu nháp" phiếu đã xuất: dừng ở amend nháp); phiếu nháp → sửa tại chỗ (+ gửi). nppsale làm ba lời
  gọi rời (huỷ → `update status 'draft'` ghi thẳng → dòng → gửi — đã chạy K11: hỏng ở bước gửi là phiếu nằm Nháp, hàng đã về kho, nợ đã xoá); bản
  này lỗi bất kỳ → lùi hết. Trả `{id: tờ còn hiệu lực, trang_thai}` — lớp phủ giao diện điều hướng theo `id` (portal/src/thay/lib/pos/save.ts,
  app/(dashboard)/purchase-returns/[id]/edit/page.tsx).
Id ổn định như nppsale: các RPC nhận tên BẤT KỲ tờ nào của chuỗi amend và làm trên tờ CUỐI (như phiếu nhập M1).

Ghi thẳng phiếu NHÁP qua cổng (`supplier_returns` / `supplier_return_lines` — nppsale.cong.bang.tra_ncc; nppsale: RLS bốn vai, mọi cột kể cả `status`,
KHÔNG trigger khoá — đã chạy K25: về nháp / sửa dòng / xoá phiếu ĐÃ XUẤT được → ⚠K siết theo BP §6.1): thêm / sửa / xoá đầu phiếu nháp, dòng của
phiếu nháp; đổi `status`, ghi cột của RPC, đụng phiếu đã gửi (trừ `notes`) / đã huỷ → `USE_RPC`; dòng SL ≤ 0, giá / giảm âm, tiền dòng ≤ 0 → câu lỗi
dòng ngay lúc lưu (§7.3 điểm 23). Mỗi lần lưu nháp dựng lại bảng thuế: tiền phiếu nháp là số lõi tính (nppsale: số trình duyệt gửi, chỉ để xem).
"""
from __future__ import annotations

import json
from decimal import Decimal

import frappe
from frappe.utils import cint, flt, getdate, now_datetime

from nppsale.cong.bang._chung import kiem_org, tu_choi
from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai
from nppsale.cong.sql import LoiCong
from nppsale.luat import kho_mua as K
from nppsale.luat import tra_ncc as T
from nppsale.thiet_lap.kho_mua import cai_dat_kho

from . import phieu_nhap as PN
from . import rpc

DT = "Purchase Invoice"
LOAI = T.LOAI
DAY_SO = "PTNCC-.####"
BANG = "supplier_returns"
BANG_DONG = "supplier_return_lines"
# cột chỉ RPC đặt (gửi giá trị → USE_RPC; gửi null như mặc định thì bỏ qua)
COT_RPC = ("stock_entry_id", "payable_credit_id", "completed_at", "completed_by", "cancel_reason")
# cột máy tự lo / không port: bỏ qua. `return_code` gõ tay bị đè như trigger mig 240; `return_seq` / `return_code_cu` không đổi tên tờ (⚠K V27)
COT_BO = ("id", "org_id", "created_by", "created_at", "subtotal", "vat", "total", "return_code", "return_seq", "return_code_cu")
COT_DONG_BO = ("id", "org_id", "created_at", "line_total")
# p_head của `sua_phieu_tra_ncc` (cùng bộ cột màn sửa / POS gửi lên đầu phiếu)
DAU_SUA = ("supplier_id", "return_date", "warehouse_zone", "reason", "notes", "discount", "vat_override")
DONG_SUA = ("product_id", "unit_name", "quantity", "unit_price", "line_discount", "vat_rate", "conversion_factor", "notes", "sort_order")


def _tt(doc) -> str:
	return K.trang_thai_pi(doc.docstatus, doc.get("npp_huy_luc"))


def _json(v, rong):
	"""Tham số jsonb của RPC: object / mảng hoặc chuỗi JSON (gọi GET / thử bằng tay)."""
	if v is None:
		return rong
	if isinstance(v, str):
		try:
			v = json.loads(v)
		except ValueError:
			raise NppLoi("BAD_PAYLOAD: dữ liệu phiếu sai kiểu.") from None
	if not isinstance(v, type(rong)):
		raise NppLoi("BAD_PAYLOAD: dữ liệu phiếu sai kiểu.")
	return v


# ================================================================================================ bảng thuế (§2.4 — tờ trả: ĐẢO DẤU)
def dung_thue_tra(doc, cd) -> None:
	"""Bảng thuế của tờ trả NCC (net âm — dòng `Actual` chia theo tỉ lệ `net_amount` nên DẤU theo `tax_amount`, `taxes_and_totals.py:734–745`):
	thuế gõ tay → MỘT dòng `Actual` vào `tk_thue_dau_vao` = −max(0, số gõ) thay các dòng VAT; không thì dòng VAT của mẫu `mau_thue_mua` (thuế thật
	theo Item Tax Template từng dòng — ra số âm theo tiền dòng âm); chi phí trả hàng (`discount`, trừ SAU thuế) → MỘT dòng `Actual` `Add` +min(giảm,
	|tiền + thuế|) → `grand_total = −max(0, tiền + thuế − giảm)` = `payables.amount` của nppsale. Chép nguyên cách của phiếu nhập là ĐẢO CHIỀU khoản
	giảm (`luat.kho_mua.giam_dau_phieu_pi`). TK của chi phí trả hàng = TK giảm đầu phiếu nhập (quyết định tạm Q9 — chờ kế toán chốt)."""
	from erpnext.controllers.accounts_controller import _get_taxes_and_charges

	doc.taxes_and_charges = ""
	doc.set("taxes", [])
	thue_tay = None
	if cint(doc.get("npp_co_thue_go_tay")):
		thue_tay = K.thue_go_tay_pi(doc.get("npp_thue_go_tay"), la_tra=True)
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
	g = K.giam_dau_phieu_pi(tien, thue, giam, la_tra=True)
	if g:
		if not cd.get("tk_giam_dau_phieu_nhap"):
			raise NppLoi("CAI_DAT_THIEU: NPP Cai Dat chưa có tài khoản giảm đầu phiếu nhập (tk_giam_dau_phieu_nhap).")
		doc.append("taxes", {"charge_type": "Actual", "account_head": cd.tk_giam_dau_phieu_nhap, "description": "Chi phí trả hàng",
			"tax_amount": float(g[1]), "category": "Total", "add_deduct_tax": g[0]})


# ================================================================================================ phiếu nháp qua cổng (§4.3)
def _vung_kho(vung, cd) -> str:
	if vung not in K.VUNG:
		raise LoiCong("23514", f'new row for relation "{BANG}" violates check constraint "supplier_returns_warehouse_zone_check"', http=400)
	return cd.kho_can_date if vung == "date" else cd.kho_ban


def _ap_dau(doc, g: dict, cd) -> None:
	"""Cột nppsale của đầu phiếu trả → trường PI (§4.3): NOT NULL gửi null → 23502; NCC sai → 23503; vùng ngoài {sale, date} → 23514;
	`vat_override` null ≠ 0 (cờ `npp_co_thue_go_tay`); `return_date` → `bill_date` (ngày hiển thị — §7.3 điểm 11)."""
	for k, v in g.items():
		if k in COT_BO or k == "status":
			continue
		if k in COT_RPC:
			if v is not None:
				raise NppLoi(T.USE_RPC)
			continue
		if k == "supplier_id":
			PN._khong_null(v, k, BANG)
			if not frappe.db.exists("Supplier", v):
				raise LoiCong("23503", f'insert or update on table "{BANG}" violates foreign key constraint "supplier_returns_supplier_id_fkey"',
					http=409)
			doc.supplier = v
		elif k == "return_date":
			doc.bill_date = getdate(PN._khong_null(v, k, BANG))
		elif k == "warehouse_zone":
			doc.set_warehouse = doc.npp_kho_nhap = _vung_kho(PN._khong_null(v, k, BANG), cd)
		elif k == "reason":
			doc.npp_ly_do = PN._chu(v)
		elif k == "notes":
			doc.npp_ghi_chu = PN._chu(v)
		elif k == "discount":
			doc.npp_giam_dau_phieu = PN._so(PN._khong_null(v, k, BANG))
		elif k == "vat_override":
			doc.npp_co_thue_go_tay = 0 if v is None else 1
			doc.npp_thue_go_tay = 0 if v is None else PN._so(v)
		else:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{BANG}' in the schema cache", http=400)


def _luu_nhap(doc, cd) -> None:
	"""Lưu phiếu nháp: kiểm dòng (§7.3 điểm 23) → mọi dòng về kho của phiếu → dựng lại bảng thuế → lưu (PI nháp không dòng: bỏ kiểm bắt buộc của
	bảng items)."""
	dong = sorted(doc.items, key=lambda x: x.idx)
	T.kiem_dong_tra((-flt(d.qty), d.conversion_factor, d.price_list_rate, d.get("npp_giam_dong")) for d in dong)
	kho = PN.kho_phieu(doc)
	for d in dong:
		d.warehouse = kho
	doc.flags.ignore_permissions = True  # trước dung_thue_tra: set_missing_values của lõi đọc Supplier theo quyền người gọi nếu không có cờ
	PN.han_lai(doc)
	dung_thue_tra(doc, cd)
	doc.flags.ignore_mandatory = not doc.items
	doc.save()


def _dau_moi(cd):
	doc = frappe.new_doc(DT)
	doc.update({"naming_series": DAY_SO, "npp_loai": LOAI, "is_return": 1, "company": cd.cong_ty, "posting_date": PN.hom_nay(),
		"set_posting_time": 1, "update_stock": 1, "disable_rounded_total": 1, "ignore_pricing_rule": 1, "buying_price_list": cd.bang_gia_nhap,
		# supplier_returns.warehouse_zone DEFAULT 'date'; return_date DEFAULT CURRENT_DATE (⚠K nhẹ: ngày VN — nppsale ngày UTC)
		"set_warehouse": cd.kho_can_date, "npp_kho_nhap": cd.kho_can_date, "bill_date": PN.hom_nay(), "npp_giam_dau_phieu": 0})
	return doc


def them_phieu(ds: list[dict], nc) -> list[str]:
	"""INSERT supplier_returns: phiếu NHÁP (`status` 'draft' — khác → USE_RPC), số `PTNCC-` cấp ngay (mã gõ tay bị bỏ), người lập = người gọi."""
	if nc.vai not in K.VAI_MUA_HANG and not nc.bo_qua_rls:
		tu_choi(BANG)
	cd = cai_dat_kho()
	ra = []
	for g in ds:
		g = dict(g or {})
		kiem_org(g, BANG)
		if (g.get("status") or "draft") != "draft":
			raise NppLoi(T.USE_RPC)
		doc = _dau_moi(cd)
		_ap_dau(doc, g, cd)
		if not doc.supplier:
			PN._khong_null(None, "supplier_id", BANG)
		_luu_nhap(doc, cd)
		ra.append(doc.name)
	return ra


def sua_phieu(gia_tri: dict, ids: list[str], nc) -> list[str]:
	"""UPDATE supplier_returns: vai ngoài bốn vai mua hàng → 0 dòng (như RLS); đổi `status` → USE_RPC (luồng "sửa phiếu đã xuất" của nppsale ghi
	thẳng `status 'draft'` lên tờ vừa huỷ — bản Frappe đi RPC `sua_phieu_tra_ncc`); nháp → lưu + dựng lại thuế; đã gửi → chỉ `notes`; đã huỷ → USE_RPC."""
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
			raise NppLoi(T.USE_RPC)
		if tt == "draft":
			_ap_dau(doc, g, cd)
			_luu_nhap(doc, cd)
		elif tt == "completed" and not (set(g) - set(COT_BO) - {"status", "notes"}):
			if "notes" in g:
				doc.db_set("npp_ghi_chu", PN._chu(g["notes"]))
		else:
			raise NppLoi(T.USE_RPC)
		ra.append(ten)
	return ra


def xoa_phieu(ids: list[str], nc) -> list[str]:
	"""DELETE supplier_returns: chỉ phiếu chưa ghi sổ (nháp, kể cả nháp mang dấu huỷ); đã gửi / đã huỷ sau khi gửi → USE_RPC (nppsale xoá được
	phiếu đã xuất — K25: nợ âm + phiếu kho mồ côi)."""
	if nc.vai not in K.VAI_MUA_HANG and not nc.bo_qua_rls:
		return []
	ra = []
	for ten in ids:
		if cint(frappe.db.get_value(DT, ten, "docstatus")) != 0:
			raise NppLoi(T.USE_RPC)
		frappe.delete_doc(DT, ten, ignore_permissions=True, force=True)
		ra.append(ten)
	return ra


def _ap_dong(doc, r, g: dict, cd) -> None:
	"""Cột nppsale của một dòng trả → Purchase Invoice Item: SL ÂM trên tờ (`qty = −quantity`); đơn giá → `price_list_rate`; giảm dòng (TIỀN cả
	dòng) → `npp_giam_dong`; `rate` / `discount_amount` = tiền dòng / SL, giảm / SL theo SL DƯƠNG (precision 4 — `luat.kho_mua.dong_pi`); thuế suất
	(tỉ lệ) → `npp_thue_suat` + Item Tax Template "VAT n%"; kho dòng = kho của phiếu."""
	from nppsale.rpc.don_hang import _dam_bao_uom
	from nppsale.thiet_lap.ban_hang import mau_thue_dong

	for k, v in g.items():
		if k in COT_DONG_BO or k in ("return_id", "sort_order"):
			continue
		if k == "product_id":
			PN._khong_null(v, k, BANG_DONG)
			if not frappe.db.exists("Item", v):
				raise LoiCong("23503", f'insert or update on table "{BANG_DONG}" violates foreign key constraint '
					'"supplier_return_lines_product_id_fkey"', http=409)
			r.item_code = v
		elif k == "unit_name":
			_dam_bao_uom(PN._khong_null(v, k, BANG_DONG))
			r.uom = v
		elif k == "quantity":
			sl = PN._so(PN._khong_null(v, k, BANG_DONG))
			r.qty = -flt(sl)
		elif k == "unit_price":
			r.price_list_rate = PN._so(PN._khong_null(v, k, BANG_DONG))
		elif k == "line_discount":
			r.npp_giam_dong = PN._so(PN._khong_null(v, k, BANG_DONG))
		elif k == "vat_rate":
			r.npp_thue_suat = PN._so(PN._khong_null(v, k, BANG_DONG))
		elif k == "conversion_factor":
			r.conversion_factor = PN._so(PN._khong_null(v, k, BANG_DONG))
		elif k == "notes":
			r.npp_ghi_chu = PN._chu(v)
		else:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{BANG_DONG}' in the schema cache", http=400)
	r.price_list_rate = flt(r.price_list_rate)
	r.npp_giam_dong = flt(r.get("npp_giam_dong"))
	r.npp_thue_suat = flt(r.get("npp_thue_suat"))
	r.conversion_factor = r.conversion_factor if r.conversion_factor is not None else 1
	r.item_tax_template = mau_thue_dong(r.npp_thue_suat, cd.cong_ty)
	r.warehouse = PN.kho_phieu(doc)
	r.margin_type, r.margin_rate_or_amount, r.discount_percentage = "", 0, 0
	sl = -flt(r.qty)
	if sl > 0 and K.tien_dong(sl, r.price_list_rate, r.npp_giam_dong) > 0:
		x = K.dong_pi(sl, r.price_list_rate, r.npp_giam_dong)
		r.rate, r.discount_amount = float(x["rate"]), float(x["discount_amount"])
	else:  # dòng sai — `_luu_nhap` báo lỗi dòng trước khi lưu
		r.rate, r.discount_amount = r.price_list_rate, 0


def _dong_moi(doc, g: dict, cd, thu: int):
	r = doc.append("items", {})
	r.flags._npp_thu = (flt(g.get("sort_order")) if g.get("sort_order") is not None else 10 ** 9, thu)
	_ap_dong(doc, r, g, cd)
	if not r.item_code:
		PN._khong_null(None, "product_id", BANG_DONG)
	if not r.uom:
		PN._khong_null(None, "unit_name", BANG_DONG)
	return r


def _phieu_tra_nhap(ten: str | None):
	"""Phiếu cha của lời ghi dòng: không có → khoá ngoại 23503; không còn là phiếu nháp → USE_RPC (cha đã gửi / đã huỷ)."""
	if not ten or not frappe.db.exists(DT, {"name": ten, "npp_loai": LOAI}):
		raise LoiCong("23503", f'insert or update on table "{BANG_DONG}" violates foreign key constraint "supplier_return_lines_return_id_fkey"',
			http=409)
	doc = frappe.get_doc(DT, ten)
	if _tt(doc) != "draft":
		raise NppLoi(T.USE_RPC)
	return doc


def them_dong(ds: list[dict], nc) -> list[str]:
	"""INSERT supplier_return_lines (saveReturnLines: xoá hết rồi chèn lại theo `sort_order`) — trả tên từng dòng mới theo thứ tự gửi."""
	if nc.vai not in K.VAI_MUA_HANG and not nc.bo_qua_rls:
		tu_choi(BANG_DONG)
	cd = cai_dat_kho()
	theo_phieu: dict = {}
	for g in ds:
		g = dict(g or {})
		theo_phieu.setdefault(PN._chu(g.get("return_id")), []).append(g)
	ra = []
	for ten, dong in theo_phieu.items():
		doc = _phieu_tra_nhap(ten)
		moi = [_dong_moi(doc, g, cd, i) for i, g in enumerate(dong)]
		PN._xep_dong(doc)
		_luu_nhap(doc, cd)
		ra += [r.name for r in moi]
	return ra


def sua_dong(gia_tri: dict, ids: list[str], nc) -> list[str]:
	if nc.vai not in K.VAI_MUA_HANG and not nc.bo_qua_rls:
		return []
	cd = cai_dat_kho()
	g = dict(gia_tri or {})
	if g.get("return_id") is not None:
		raise NppLoi(T.USE_RPC)  # chuyển dòng sang phiếu khác
	ra = []
	for ten in ids:
		doc = _phieu_tra_nhap(frappe.db.get_value("Purchase Invoice Item", ten, "parent"))
		r = next(x for x in doc.items if x.name == ten)
		if "sort_order" in g:
			r.flags._npp_thu = (flt(g["sort_order"]), 0)
		_ap_dong(doc, r, g, cd)
		PN._xep_dong(doc)
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
	for pt, ds in theo_phieu.items():
		doc = _phieu_tra_nhap(pt)
		doc.set("items", [x for x in doc.items if x.name not in ds])
		PN._xep_dong(doc)
		_luu_nhap(doc, cd)
		ra += ds
	return ra


# ================================================================================================ khoá + chuỗi amend
def _hang_moi(p_lines) -> set:
	try:
		ds = _json(p_lines, [])
	except NppLoi:
		return set()
	return {str(d.get("product_id")) for d in ds if isinstance(d, dict) and d.get("product_id")}


def _chuan_bi_tra(p_return_id=None, p_reason=None, p_head=None, p_lines=None, p_chi_luu_nhap=None):
	"""Đọc trước khi khoá (cổng commit sau bước này): người gọi, cài đặt, tờ cuối của chuỗi + mặt hàng của nó (∪ mặt hàng của `p_lines` khi
	sửa) → frappe.local — câu ĐẦU của hàm là khoá Bin (PoC 1d)."""
	hien_tai()
	cai_dat_kho()
	ten = PN._hieu_luc(PN._chu(p_return_id))
	frappe.local._npp_ptn = (PN._chu(p_return_id), ten, PN._hang_cua(ten) | _hang_moi(p_lines))


def _da_chuan_bi(p_return_id, p_lines=None) -> tuple[str | None, set]:
	x = getattr(frappe.local, "_npp_ptn", None)
	frappe.local._npp_ptn = None  # dùng MỘT lần
	if x and x[0] == PN._chu(p_return_id):
		return x[1], x[2]
	ten = PN._hieu_luc(PN._chu(p_return_id))  # gọi nội bộ không qua cổng
	return ten, PN._hang_cua(ten) | _hang_moi(p_lines)


def _khoa(ten: str | None, hang: set, cd):
	"""Khoá Bin (mặt hàng đọc ở bước chuẩn bị) → khoá PI `FOR UPDATE` theo chuỗi amend tới tờ cuối; mặt hàng của tờ đổi giữa hai bước (sửa nháp
	đồng thời) → khoá thêm Bin của hàng mới. None = không có phiếu trả NCC."""
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
	moi = PN._hang_cua(r[0].name) - set(hang)
	if moi:
		_khoa_bin(moi, cd)
	return r[0]


def _mo(ten_rpc: str, p_return_id, p_lines=None):
	"""Phần đầu chung của bốn RPC: người gọi, cài đặt, khoá, `PHIEU_KHONG_TON_TAI`, vai."""
	nc = hien_tai()
	cd = cai_dat_kho()
	ten, hang = _da_chuan_bi(p_return_id, p_lines)
	r = _khoa(ten, hang, cd)
	if r is None:
		raise NppLoi(T.KHONG_TON_TAI)
	PN._kiem_vai(ten_rpc, nc)
	return nc, cd, r


# ================================================================================================ tồn để chọn lô / in câu thiếu tồn
def ton_kho_hang(hang: str, kho: str, co_lo: bool, cd) -> tuple[bool, Decimal]:
	"""(có dòng, Σ tồn) của mặt hàng tại MỘT kho — đúng nguồn của cổng `batches` (`NGUON_LO`): lô KHÔNG tắt có gói lô chưa huỷ ở kho (kể cả lô đã
	về 0) + lô chưa phát sinh có `npp_kho_tao` = kho; hàng không lô → Bin. nppsale: `COALESCE(SUM(qty_on_hand), 0)` các lô `available` của vùng."""
	if not co_lo:
		x = frappe.db.get_value("Bin", {"item_code": hang, "warehouse": kho}, "actual_qty")
		return (x is not None), Decimal(str(round(flt(x), 6)))
	r = frappe.db.sql("""SELECT COUNT(*), COALESCE(SUM(t.`ton`), 0) FROM (
			SELECT e.`batch_no`, SUM(e.`qty`) AS `ton`
			FROM `tabSerial and Batch Entry` e
			JOIN `tabSerial and Batch Bundle` sb ON sb.`name` = e.`parent` AND sb.`docstatus` = 1 AND sb.`is_cancelled` = 0
			JOIN `tabBatch` b ON b.`name` = e.`batch_no`
			WHERE e.`is_cancelled` = 0 AND IFNULL(e.`batch_no`, '') != '' AND e.`warehouse` = %(kho)s AND b.`item` = %(hang)s
				AND IFNULL(b.`disabled`, 0) = 0
			GROUP BY e.`batch_no`
			UNION ALL
			SELECT b0.`name`, 0 FROM `tabBatch` b0
			WHERE b0.`item` = %(hang)s AND IFNULL(b0.`disabled`, 0) = 0 AND COALESCE(NULLIF(b0.`npp_kho_tao`, ''), %(kho_ban)s) = %(kho)s
				AND NOT EXISTS (SELECT 1 FROM `tabSerial and Batch Entry` e
					JOIN `tabSerial and Batch Bundle` sb ON sb.`name` = e.`parent` AND sb.`docstatus` = 1 AND sb.`is_cancelled` = 0
					WHERE e.`is_cancelled` = 0 AND e.`batch_no` = b0.`name`)
		) t""", {"hang": hang, "kho": kho, "kho_ban": cd.kho_ban})[0]
	return bool(r[0]), Decimal(str(round(flt(r[1]), 6)))


# ================================================================================================ complete_supplier_return
@rpc("complete_supplier_return", ghi=True, chuan_bi=_chuan_bi_tra)
def complete_supplier_return(p_return_id=None):
	nc, cd, r = _mo("complete_supplier_return", p_return_id)
	return gui(r, nc, cd)


def gui(r, nc, cd) -> str:
	"""Thân complete_supplier_return (PI đã khoá, vai đã kiểm). Trả tên PI."""
	from nppsale.rpc.goi_lo import gan_goi_lo, kho_cua_vung, lap_goi_lo, lo_theo_kho, vung_cua_kho

	tt = K.trang_thai_pi(r.docstatus, r.npp_huy_luc)
	if tt == "completed":
		return r.name  # IDEMPOTENT — bấm hai lần không xuất kho hai lần
	if tt != "draft":
		raise T.loi_khong_con_nhap(tt)
	doc = frappe.get_doc(DT, r.name)
	dong = sorted(doc.items, key=lambda x: x.idx)
	if not dong:
		raise NppLoi(T.KHONG_CO_HANG)
	# nháp lọt ngoài cổng (Desk / dữ liệu chuyển sang): cùng luật cổng — PI trả không biểu diễn được dòng SL ≤ 0 / tiền ≤ 0
	T.kiem_dong_tra((-flt(d.qty), d.conversion_factor, d.price_list_rate, d.get("npp_giam_dong")) for d in dong)
	kho = PN.kho_phieu(doc)
	vung = vung_cua_kho(kho, cd) or "date"
	kia = T.vung_kia(vung)
	kho_kia = kho_cua_vung(kia, cd)
	cho = bool(cd.get("cho_ban_vuot_ton"))
	lo_kho: dict = {}  # mặt hàng → [LoKho] tại kho xuất (dòng sau thấy phần dòng trước lấy)
	da_lay: dict = {}  # mặt hàng → Σ đã lấy trong lượt (đơn vị cơ sở)
	lay_dong = []
	for d in dong:
		it = frappe.db.get_value("Item", d.item_code, ["item_name", "stock_uom", "has_batch_no", "allow_negative_stock"], as_dict=True) or frappe._dict()
		sl, hs = -flt(d.qty), flt(d.conversion_factor if d.conversion_factor is not None else 1)
		can = K.so(sl) * K.so(hs)
		if it.has_batch_no:
			ds = lo_kho.setdefault(d.item_code, lo_theo_kho(d.item_code, kho))
			kq = K.chon_lo_fefo(ds, can)
			da_lay[d.item_code] = da_lay.get(d.item_code, Decimal(0)) + sum((x for _m, x in kq.lay), Decimal(0))
			thieu = kq.thieu > 0  # hàng THEO LÔ không bao giờ âm (CFD-05 B) — kể cả NPP cho bán vượt tồn (⚠K: nppsale ghi dòng không lô)
			lay_dong.append(kq.lay)
		else:  # hàng không lô (câu 14 B): Bin kho xuất; thiếu mà mặt hàng cho âm + NPP cho bán vượt tồn → xuất âm (giá phần âm do lõi định — §2.6)
			_co, ton = ton_kho_hang(d.item_code, kho, False, cd)
			con = ton - da_lay.get(d.item_code, Decimal(0))
			lay = min(can, max(con, Decimal(0)))
			thieu = can > lay and not (cint(it.allow_negative_stock) and cho)
			da_lay[d.item_code] = da_lay.get(d.item_code, Decimal(0)) + (can if not thieu else lay)
			lay_dong.append(None)
		if thieu:
			co, ton = ton_kho_hang(d.item_code, kho, bool(it.has_batch_no), cd)
			co2, ton2 = ton_kho_hang(d.item_code, kho_kia, bool(it.has_batch_no), cd)
			raise T.loi_thieu_ton(it.item_name, it.stock_uom, sl, hs, vung, (co, T.con_sau_lay(ton, da_lay[d.item_code])), kia, (co2, ton2),
				ma_hang=d.item_code)
	luc = now_datetime()
	# giờ ghi sổ đủ micro giây (như `nowtime()` của lõi): cắt về giây là tờ có thể đứng TRƯỚC phiếu nhập kho cùng giây → lõi coi là ghi lùi, không
	# tìm thấy giá vốn của hàng không lô ("Valuation Rate … is required" — đo M2)
	ngay, gio = luc.date(), luc.strftime("%H:%M:%S.%f")
	for d, lay in zip(dong, lay_dong, strict=True):
		d.warehouse = kho
		if lay:
			gan_goi_lo(d, lap_goi_lo("Outward", DT, d.item_code, kho, lay, ngay, gio, cd.cong_ty))
	doc.update({"posting_date": ngay, "posting_time": gio, "set_posting_time": 1, "update_stock": 1, "disable_rounded_total": 1,
		"ignore_pricing_rule": 1, "buying_price_list": cd.bang_gia_nhap, "npp_hoan_thanh_luc": luc, "npp_hoan_thanh_boi": PN._nv(nc),
		"npp_han_thanh_toan": None})
	PN.han_lai(doc)  # ngày ghi sổ đổi sang hôm nay — hạn của lõi tính lại
	doc.flags.ignore_permissions = True
	dung_thue_tra(doc, cd)
	doc.save()
	doc.submit()  # hook on_submit: chiếu dòng công nợ NCC ÂM (`tra_ncc` — không dồn trả trước)
	frappe.local.message_log = []
	return doc.name


# ================================================================================================ cancel_supplier_return
@rpc("cancel_supplier_return", ghi=True, chuan_bi=_chuan_bi_tra)
def cancel_supplier_return(p_return_id=None, p_reason=None):
	nc, cd, r = _mo("cancel_supplier_return", p_return_id)
	tt = K.trang_thai_pi(r.docstatus, r.npp_huy_luc)
	if tt == "cancelled":
		return r.name  # IDEMPOTENT — giữ lý do huỷ cũ
	ly_do = PN._chu(p_reason)
	if tt == "draft":  # nháp: chỉ dấu huỷ — chưa đụng kho / công nợ (§7.3 điểm 1: giữ nháp để khôi phục được)
		frappe.db.set_value(DT, r.name, {"npp_huy_luc": now_datetime(), "npp_huy_boi": PN._nv(nc), "npp_ly_do_huy": ly_do})
		return r.name
	huy(r.name, ly_do, nc, cd)
	return r.name


def _lo_cua_to(ten: str) -> list[str]:
	"""Mã lô trong gói lô CHƯA huỷ của tờ (lô hàng sẽ được cộng trả về khi huỷ)."""
	return [x[0] for x in frappe.db.sql("""SELECT DISTINCT e.`batch_no` FROM `tabSerial and Batch Bundle` b
		JOIN `tabSerial and Batch Entry` e ON e.`parent` = b.`name`
		WHERE b.`voucher_type` = %s AND b.`voucher_no` = %s AND b.`docstatus` = 1 AND b.`is_cancelled` = 0 AND IFNULL(e.`batch_no`, '') != ''
		ORDER BY e.`batch_no`""", (DT, ten))]


def huy(ten: str, ly_do: str | None, nc, cd) -> None:
	"""Thân huỷ phiếu trả đã gửi (PI đã khoá). Thứ tự nppsale: DA_CAN_TRU → cộng trả đúng lô (mở lại lô đã đóng) → bỏ dòng nợ âm."""
	from nppsale.su_kien.cong_no_ncc import gia_tri_pi

	gt = gia_tri_pi(ten)
	if gt and abs(flt(gt["da_tra"])) >= 0.005:  # khoản giảm đã được cấn trừ (bù trừ / phân bổ tay) — lõi sẽ gỡ phân bổ khi huỷ: chặn trước
		raise T.loi_da_can_tru(round(flt(gt["da_tra"]), 2))
	for lo in _lo_cua_to(ten):  # mig 235: lô đã đóng thì MỞ LẠI — hàng thật sự quay về kho (lõi vẫn cộng được vào lô tắt — đo M0)
		if cint(frappe.db.get_value("Batch", lo, "disabled")):
			frappe.db.set_value("Batch", lo, "disabled", 0)
	doc = frappe.get_doc(DT, ten)
	doc.update({"npp_ly_do_huy": ly_do, "npp_huy_luc": now_datetime(), "npp_huy_boi": PN._nv(nc)})
	doc.flags.ignore_permissions = True
	doc.cancel()  # lõi đảo gói lô (hàng về đúng lô), đảo GL; hook xoá dòng công nợ NCC âm
	frappe.local.message_log = []
	PN._xep_repost()


# ================================================================================================ khoi_phuc_phieu_tra_ncc + amend
def lap_amend(ten_cu: str, cd) -> str:
	"""Amend NHÁP của tờ đã huỷ (CFD-01): chép đầu phiếu + dòng, bỏ dấu huỷ / gói lô; giữ ngày trả, ghi chú, lý do trả, mốc + người gửi lần trước
	(nppsale: phiếu về Nháp vẫn giữ `completed_at / completed_by` cũ); bỏ số HĐ NCC / ghi chú / hạn của dòng công nợ cũ (nppsale lập dòng nợ MỚI khi
	gửi lại). Lưu như nháp (kiểm dòng + dựng lại thuế). Trả tên tờ mới."""
	cu = frappe.get_doc(DT, ten_cu)
	moi = frappe.copy_doc(cu, ignore_no_copy=False)  # như Amend của Desk: trường no_copy của lõi không chép
	moi.docstatus = 0
	for d in moi.get_all_children():
		d.docstatus = 0
	moi.amended_from = cu.name
	kho = PN.kho_phieu(cu)
	moi.update({"naming_series": cu.naming_series, "npp_loai": LOAI, "is_return": 1, "bill_date": cu.bill_date, "bill_no": None,
		"npp_ghi_chu": cu.get("npp_ghi_chu"), "npp_ly_do": cu.get("npp_ly_do"), "npp_huy_luc": None, "npp_huy_boi": None,
		"npp_ly_do_huy": None, "npp_hoan_thanh_luc": cu.get("npp_hoan_thanh_luc"), "npp_hoan_thanh_boi": cu.get("npp_hoan_thanh_boi"),
		"npp_ghi_chu_no": None, "npp_han_thanh_toan": None, "npp_qua_han_tay": 0, "posting_date": PN.hom_nay(), "set_posting_time": 1,
		"set_warehouse": kho, "npp_kho_nhap": kho})
	for d in moi.items:
		d.serial_and_batch_bundle = None
		d.batch_no = None
		d.use_serial_batch_fields = 0
	_luu_nhap(moi, cd)
	return moi.name


@rpc("khoi_phuc_phieu_tra_ncc", ghi=True, chuan_bi=_chuan_bi_tra)
def khoi_phuc_phieu_tra_ncc(p_return_id=None):
	nc, cd, r = _mo("khoi_phuc_phieu_tra_ncc", p_return_id)
	tt = K.trang_thai_pi(r.docstatus, r.npp_huy_luc)
	if tt != "cancelled":  # IDEMPOTENT (gồm tờ đã có tờ amend sống — `_khoa` đã đi tới tờ ấy)
		return T.ket_qua_khoi_phuc(r.name, tt, False)
	if not r.docstatus:  # huỷ lúc còn nháp → về nháp, không đụng kho / công nợ
		frappe.db.set_value(DT, r.name, {"npp_huy_luc": None, "npp_huy_boi": None, "npp_ly_do_huy": None})
		return T.ket_qua_khoi_phuc(r.name, "draft", True)
	moi = lap_amend(r.name, cd)
	# gửi lại: lỗi nghiệp vụ (P0001 — kho không đủ…) chỉ lùi phần gửi lại, tờ amend ở Nháp kèm lý do; lỗi khác (vai, hệ thống) ném ra — lùi cả lượt
	frappe.db.savepoint("npp_khoi_phuc_tra")
	try:
		gui(frappe._dict({"name": moi, "docstatus": 0, "npp_huy_luc": None}), nc, cd)
	except NppLoi as e:
		if e.code != "P0001":
			raise
		frappe.db.rollback(save_point="npp_khoi_phuc_tra")
		frappe.local.message_log = []
		return T.ket_qua_khoi_phuc(moi, "draft", True, e.ma)
	return T.ket_qua_khoi_phuc(moi, "completed", True)


# ================================================================================================ sua_phieu_tra_ncc (mới — §3.8)
def _ap_sua(doc, head: dict, lines: list, cd) -> None:
	"""Đầu phiếu + dòng mới của lời sửa (bộ cột của màn sửa / POS; khoá khác bỏ qua như `p_head->>'k'` của jsonb) → tờ nháp, lưu."""
	_ap_dau(doc, {k: v for k, v in head.items() if k in DAU_SUA}, cd)
	doc.set("items", [])
	for i, g in enumerate(lines):
		_dong_moi(doc, {k: v for k, v in (g if isinstance(g, dict) else {}).items() if k in DONG_SUA}, cd, i)
	PN._xep_dong(doc)
	_luu_nhap(doc, cd)


@rpc("sua_phieu_tra_ncc", ghi=True, chuan_bi=_chuan_bi_tra)
def sua_phieu_tra_ncc(p_return_id=None, p_reason=None, p_head=None, p_lines=None, p_chi_luu_nhap=None):
	"""Sửa phiếu trả NCC trong MỘT giao dịch: nháp → sửa tại chỗ; đã gửi → thân huỷ (lý do `p_reason`, mặc định "Sửa phiếu — lập lại") + amend
	nháp theo số mới; rồi (trừ `p_chi_luu_nhap`) thân gửi. Đã huỷ → `PHIEU_DA_HUY` (khôi phục trước). Trả {id: tờ còn hiệu lực, trang_thai}."""
	nc, cd, r = _mo("sua_phieu_tra_ncc", p_return_id, p_lines)
	head, lines = _json(p_head, {}), _json(p_lines, [])
	tt = K.trang_thai_pi(r.docstatus, r.npp_huy_luc)
	if tt == "cancelled":
		raise NppLoi(T.DA_HUY_KHONG_SUA)
	if tt == "completed":
		huy(r.name, PN._chu(p_reason) or T.LY_DO_SUA, nc, cd)
		doc = frappe.get_doc(DT, lap_amend(r.name, cd))
	else:
		doc = frappe.get_doc(DT, r.name)
	_ap_sua(doc, head, lines, cd)
	if p_chi_luu_nhap in (True, 1, "1", "true", "t"):
		return {"id": doc.name, "trang_thai": "draft"}
	gui(frappe._dict({"name": doc.name, "docstatus": 0, "npp_huy_luc": None}), nc, cd)
	return {"id": doc.name, "trang_thai": "completed"}
