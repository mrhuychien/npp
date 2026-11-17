"""PHIẾU KHO TAY (P4 — mốc M4; đặc tả kho_mua §3.6, §3.15, §3.16, §3.19, §4.5, §7.3 điểm 1 / 3 / 4 / 5 / 23; blueprint 02 §5.11, §6.1, §6.4).

RPC (giữ tên nppsale — hàm Postgres nguồn ở scratchpad kho_mua/src/<tên>.sql; câu lỗi nguyên văn ở nppsale/luat/kho_tay.py):
- `post_stock_import(p)` (mig 168 / 219): ép kiểu tải trọng → vai owner / warehouse → mã / dòng / NCC / vùng / tiền nợ → từng dòng (mặt hàng, SL, giá
  vốn) → ngày tương lai (CFD-12 — mới) → mã lô trùng (`LO_TRUNG_MA` — BP §7.1 điểm 14, mới) → có NCC + tiền nợ > 0: PHIẾU NHẬP `PN-` ghi sổ ngay (CFD-13,
  câu 17; §7.3 điểm 3 — dòng `rate` = giá vốn × hệ số, MỘT dòng thuế `Actual` bù phần nợ lệch giá vốn, không ghi giá nhập, lô theo mã trình duyệt);
  còn lại Material Receipt `IN-.YYYY.MM.DD.-.####` (`nhap_kho`; mã `DK-…` → `ton_dau_ky` + `is_opening` — §7.3 điểm 4). Lô mỗi dòng mặt hàng theo lô:
  mã gõ hoặc `LOT-<mã>-<n>`, kho dòng theo hạn (`batches_auto_zone`), ngày nhận = `posted_at` (lùi ngày được — tồn đầu kỳ → xếp repost).
- `post_stock_issue(p_entry_id)` (mig 144 / 166 / 222 / 228): khoá Bin → khoá phiếu → vai → loại → idempotent → trạng thái → có dòng → lượt một gom
  theo mặt hàng (thiếu → `KHONG_DU_TON`; hàng THEO LÔ luôn chặn — CFD-05 B; hàng không lô được âm khi mặt hàng + NPP cho) → lượt hai từng dòng hạn
  cũ trước (gồm lô hết hạn — Material Issue không bị lõi kiểm hạn) → gói lô Outward, TK `tk_xuat_le`, ghi sổ lúc bấm.
- `post_stock_transfer(p_entry_id)` (mig 148 / 166 / 222 / 228): như xuất lẻ, thêm kho đích (`THIEU_KHO_DICH`, `TRUNG_KHO`), KHÔNG vượt tồn (mig 222
  cố ý), lô được ghé mà đích là kho bán và hạn ≤ hôm nay + ngưỡng → `HANG_GAN_HAN`; lõi tự lập phía nhận cùng Batch, giữ giá lô (đo M4 — §7.1 #13);
  `Batch.npp_chuyen_vung_luc / _boi`.
- `cancel_stock_entry(p_entry_id, p_reason)` (mig 139 / 166 / 227 / 228; việc #24): tìm id theo nguồn cổng `stock_entries` (Stock Entry → Sales
  Invoice có kho → Purchase Invoice phiếu nhập / trả NCC) → vai (trước mọi bước trạng thái) → đã huỷ (`[true, false, 0]` — trừ HĐ đã huỷ / phiếu nhập
  lại hàng khách trả: câu của nppsale) → nháp: XOÁ nháp (§7.3 điểm 1) → đã ghi sổ: nguồn nhận diện bằng TRƯỜNG THẬT (⚠K đóng lỗ ghi chú V54): phiếu
  nhập / trả NCC / phiếu nhập lại hàng khách trả (`NL-` hoặc tờ ghi có có kho `HDT-` — việc #24) / nợ NCC lập tay gắn phiếu / chuyển kho / HĐ → câu
  nppsale; xuất lẻ → huỷ (lõi trả đúng lô theo gói lô, `lines_reversed` = số lô); nhập kho tay → lô đã bị rà sang kho cận date (phiếu `CKL-`
  `chuyen_date_tu_dong`, không động gì khác) → huỷ trước phiếu ấy (§7.3 điểm 8 — M5, `nppsale.rpc.lo_kho.hoan_chuyen_date`) → `ALREADY_ISSUED` khi lô /
  Bin đã xuất bớt (không nới khi cho bán vượt tồn), rồi huỷ (`lines_reversed` = số dòng) → xếp repost. Nháp xoá KHÔNG lùi dãy số (`xoa_nhap`).
- `confirm_driver_handover` (chuyến giao — luồng cũ, §4.8 soát thiếu S14 / §7.3 điểm 40), `post_stock_export` (phiếu xuất kiểu cũ — M9, §3.21):
  `LEGACY_FLOW_REMOVED`.
Phiếu KIỂM KÊ (`NPP Kiem Ke` — M6, nguồn (2) của cổng `stock_entries`): `nguon_phieu` nhận cả nó; huỷ nháp = `cancelled` + ghi chú (giữ phiếu), đã duyệt
→ `CANNOT_REVERSE_TYPE (stocktake)`; ghi thẳng nháp / dòng chuyển sang nppsale.rpc.kiem_ke (dòng có dấu, dòng 0 được).
Ghi thẳng phiếu kho NHÁP qua cổng (`stock_entries` / `stock_entry_lines` — nppsale.cong.bang.phieu_kho; trigger mig 170 + RLS owner / warehouse): lập
nháp (`status` khác `draft` hoặc quên cột → `SO_KHO_KHOA`), sửa nháp (đổi `type` → câu "chỉ sửa được ghi chú"; `draft → cancelled` = XOÁ nháp), phiếu
đã ghi sổ / đã huỷ chỉ sửa `notes` (⚠K: nppsale cho sửa cả `entry_code`, `issue_reason`, `supplier_id`, `ref_order_ids`), xoá chỉ nháp; dòng chỉ khi
phiếu cha là nháp; dòng SL ≤ 0 bị chặn ngay lúc lưu (§7.3 điểm 23). Nháp Stock Entry lưu KHÔNG chạy `validate` của lõi (nháp chuyển kho thiếu / trùng
kho đích phải lưu được như nppsale — V49); ghi sổ mới chạy đủ.
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import frappe
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from nppsale.cong.bang._chung import gio_vao, kiem_org, lay_org_id, tu_choi
from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai
from nppsale.cong.sql import LoiCong
from nppsale.luat import kho_mua as K
from nppsale.luat import kho_tay as T
from nppsale.luat.tim import khoa_tim_ds
from nppsale.thiet_lap.kho_mua import cai_dat_kho

from . import phieu_nhap as PN
from . import rpc

DT = "Stock Entry"
KK_DT = "NPP Kiem Ke"  # phiếu kiểm kê (M6 — nppsale.rpc.kiem_ke)
BANG = "stock_entries"
BANG_DONG = "stock_entry_lines"
# `stock_entries.type` của nháp lập qua cổng → (Stock Entry Type / purpose, `npp_loai`, dãy số)
LOAI_NHAP = {"import": ("Material Receipt", T.SE_NHAP, "IN-.YYYY.MM.DD.-.####"), "export": ("Material Issue", T.SE_XUAT_LE, "XKL-.####"),
	"transfer": ("Material Transfer", T.SE_CHUYEN, "CKL-.####")}
# cột nppsale của đầu phiếu mà cổng bỏ qua khi ghi nháp (mã do dãy số Frappe cấp — giao diện điều hướng theo `id`; người lập = người gọi)
COT_BO = ("id", "org_id", "entry_code", "created_by", "created_at", "posted_at", "ref_order_ids", "tim_kd")
COT_DONG_BO = ("id", "entry_id", "quantity", "transaction_uom", "unit_cost", "batch_id")


def _chu(v) -> str | None:
	if v is None:
		return None
	return v if isinstance(v, str) else json.dumps(v)


def _vung_kho(vung, cd) -> str:
	return cd.kho_can_date if vung == "date" else cd.kho_ban


def _ten_hang(hang: str) -> str:
	return frappe.db.get_value("Item", hang, "item_name") or hang


def _thong_tin(hang: str) -> frappe._dict:
	return frappe.db.get_value("Item", hang, ["item_name", "stock_uom", "has_batch_no", "has_expiry_date", "allow_negative_stock"],
		as_dict=True) or frappe._dict(item_name=hang)


def _dat_tim(ten: str) -> None:
	"""Khoá tìm `tim_kd` của phiếu kho = khoá của TÊN chứng từ (`_trg_tim_kd('entry_code')`, mig 249) — nháp lưu không chạy validate của lõi nên đặt
	thẳng sau khi có tên."""
	frappe.db.set_value(DT, ten, "npp_tim_kd", khoa_tim_ds(ten), update_modified=False)


def _xep_repost():
	PN._xep_repost()  # đọc tại chỗ — bài kiểm thay `nppsale.rpc.phieu_nhap._xep_repost`


def xoa_nhap(ten: str, dt: str = DT) -> None:
	"""Xoá phiếu kho NHÁP (huỷ nháp = xoá — §7.3 điểm 1) mà KHÔNG lùi dãy số: lõi lùi `tabSeries` khi xoá tờ số cuối (`frappe/model/delete_doc.py:195`
	→ `revert_series_if_last`) nên phiếu lập sau nhận lại ĐÚNG tên ấy — màn còn giữ id cũ (danh sách, chi tiết, dọn nháp hỏng của màn xuất lẻ) sẽ chạm
	nhầm phiếu mới (nppsale id uuid không bao giờ dùng lại; mã `XKL-<base36>` cũng không). Giữ số đếm của mọi dãy là tiền tố của tên."""
	tien_to = tuple(ten[:i] for i in range(1, len(ten)))
	truoc = frappe.db.sql("SELECT `name`, `current` FROM `tabSeries` WHERE `name` IN %s", (tien_to,)) if tien_to else ()
	frappe.delete_doc(dt, ten, ignore_permissions=True, force=True)
	for day, hien in truoc:
		frappe.db.sql("UPDATE `tabSeries` SET `current` = %s WHERE `name` = %s AND `current` < %s", (hien, day, hien))


# ================================================================================================ nguồn của cổng `stock_entries` (§4.5)
def nguon_phieu(ten: str | None, khoa: bool = False) -> frappe._dict | None:
	"""Phiếu kho `ten` theo đúng các nguồn của cổng `stock_entries`: Stock Entry (trừ `dieu_chinh_kiem_ke` — đi theo phiếu kiểm kê) → phiếu kiểm kê
	`NPP Kiem Ke` (M6 — `stocktake`) → Sales Invoice có kho đã / thôi ghi sổ (HĐ → `export`, tờ ghi có → `import`) → Purchase Invoice phiếu nhập / trả
	NCC đã / thôi ghi sổ (nháp không có phiếu kho). `khoa` → `FOR UPDATE` dòng nguồn. → {dt, name, trang_thai, loai, npp_loai, purpose, phieu_tra,
	is_return} hoặc None."""
	if not ten or not isinstance(ten, str):
		return None
	sau = " FOR UPDATE" if khoa else ""
	r = frappe.db.sql(f"""SELECT `name`, `docstatus`, `purpose`, `npp_loai`, `npp_phieu_tra`, `from_warehouse`, `to_warehouse`
		FROM `tabStock Entry` WHERE `name` = %s AND IFNULL(`npp_loai`, '') <> 'dieu_chinh_kiem_ke'{sau}""", ten, as_dict=True)
	if r:
		x = r[0]
		return frappe._dict(dt=DT, name=x.name, docstatus=cint(x.docstatus), trang_thai=K.trang_thai_phieu_kho(x.docstatus),
			loai=T.LOAI_SE.get(x.purpose, "import"), purpose=x.purpose, npp_loai=x.npp_loai, phieu_tra=x.npp_phieu_tra or None,
			kho=x.from_warehouse, kho_dich=x.to_warehouse, is_return=0)
	if _co_kiem_ke():
		from nppsale.rpc.kiem_ke import phieu

		x = phieu(ten, khoa=khoa)
		if x is not None:
			return x
	r = frappe.db.sql(f"""SELECT `name`, `docstatus`, `is_return`, `npp_phieu_tra` FROM `tabSales Invoice`
		WHERE `name` = %s AND `update_stock` = 1 AND `docstatus` IN (1, 2){sau}""", ten, as_dict=True)
	if r:
		x = r[0]
		return frappe._dict(dt="Sales Invoice", name=x.name, docstatus=cint(x.docstatus), trang_thai=K.trang_thai_phieu_kho(x.docstatus),
			loai="import" if cint(x.is_return) else "export", is_return=cint(x.is_return), phieu_tra=x.npp_phieu_tra or None)
	r = frappe.db.sql(f"""SELECT `name`, `docstatus`, `npp_loai` FROM `tabPurchase Invoice` WHERE `name` = %s AND `update_stock` = 1
		AND `docstatus` IN (1, 2) AND `npp_loai` IN ('phieu_nhap', 'tra_ncc'){sau}""", ten, as_dict=True)
	if r:
		x = r[0]
		return frappe._dict(dt="Purchase Invoice", name=x.name, docstatus=cint(x.docstatus), trang_thai=K.trang_thai_phieu_kho(x.docstatus),
			loai="export" if x.npp_loai == "tra_ncc" else "import", npp_loai=x.npp_loai, is_return=int(x.npp_loai == "tra_ncc"))
	return None


def _co_kiem_ke() -> bool:
	from nppsale.cong.bang._chung import co_cot

	return co_cot(KK_DT, "trang_thai")


def _hang_cua(x) -> set:
	if not x:
		return set()
	if x.dt == KK_DT:
		from nppsale.rpc.kiem_ke import hang_cua

		return hang_cua(x.name)
	bang = {DT: "Stock Entry Detail", "Sales Invoice": "Sales Invoice Item", "Purchase Invoice": "Purchase Invoice Item"}[x.dt]
	return {r[0] for r in frappe.db.sql(f"SELECT DISTINCT `item_code` FROM `tab{bang}` WHERE `parent` = %s AND `parenttype` = %s", (x.name, x.dt))}


def _chuan_bi(p_entry_id=None, p_reason=None):
	"""Đọc trước khi khoá (cổng commit sau bước này): người gọi, cài đặt, phiếu + mặt hàng của nó → frappe.local — câu ĐẦU của thân hàm là khoá
	Bin (PoC 1d)."""
	hien_tai()
	cai_dat_kho()
	ten = _chu(p_entry_id)
	frappe.local._npp_pk = (ten, _hang_cua(nguon_phieu(ten)))


def _da_chuan_bi(p_entry_id) -> tuple[str | None, set]:
	x = getattr(frappe.local, "_npp_pk", None)
	frappe.local._npp_pk = None  # dùng MỘT lần
	ten = _chu(p_entry_id)
	if x and x[0] == ten:
		return ten, x[1]
	return ten, _hang_cua(nguon_phieu(ten))  # gọi nội bộ không qua cổng


def _khoa(ten, hang: set, cd) -> frappe._dict | None:
	"""Khoá Bin (mặt hàng đọc ở bước chuẩn bị) → khoá dòng nguồn `FOR UPDATE`; mặt hàng đổi giữa hai bước (sửa nháp đồng thời) → khoá thêm."""
	from nppsale.rpc.xuat_hang import _khoa_bin

	_khoa_bin(hang, cd)
	x = nguon_phieu(ten, khoa=True)
	moi = _hang_cua(x) - set(hang)
	if moi:
		_khoa_bin(moi, cd)
	return x


# ================================================================================================ post_stock_issue / post_stock_transfer
def _mo(ten_rpc: str, p_entry_id, khong_ton_tai: str):
	nc = hien_tai()
	cd = cai_dat_kho()
	ten, hang = _da_chuan_bi(p_entry_id)
	x = _khoa(ten, hang, cd)
	if x is None or x.dt not in (DT, KK_DT):  # chỉ Stock Entry ghi sổ được ở đây (§3.15 Frappe bước 2); phiếu kiểm kê → sai loại như nppsale
		raise NppLoi(khong_ton_tai)
	PN._kiem_vai(ten_rpc, nc)
	return nc, cd, x


@rpc("post_stock_issue", ghi=True, chuan_bi=_chuan_bi)
def post_stock_issue(p_entry_id=None):
	_nc, cd, x = _mo("post_stock_issue", p_entry_id, T.KHONG_TON_TAI_XUAT)
	if x.purpose != "Material Issue" or x.npp_loai != T.SE_XUAT_LE:
		raise NppLoi(T.SAI_LOAI_XUAT)
	if x.docstatus == 1:
		return x.name  # IDEMPOTENT — bấm hai lần không trừ kho hai lần
	if x.docstatus == 2:
		raise T.loi_khong_con_tam("cancelled")
	doc = frappe.get_doc(DT, x.name)
	dong = sorted(doc.items, key=lambda d: d.idx)
	if not dong:
		raise NppLoi(T.KHONG_CO_HANG)
	kho = doc.from_warehouse
	lay = _lay_lo(dong, kho, cd, chuyen=False)
	_ghi_so(doc, dong, lay, kho, None, cd)
	return doc.name


@rpc("post_stock_transfer", ghi=True, chuan_bi=_chuan_bi)
def post_stock_transfer(p_entry_id=None):
	from nppsale.rpc.goi_lo import vung_cua_kho

	nc, cd, x = _mo("post_stock_transfer", p_entry_id, T.KHONG_TON_TAI_CHUYEN)
	if x.purpose != "Material Transfer" or x.npp_loai not in (T.SE_CHUYEN, T.SE_CHUYEN_DATE):
		raise NppLoi(T.SAI_LOAI_CHUYEN)
	if x.docstatus == 1:
		return x.name
	if x.docstatus == 2:
		raise T.loi_khong_con_tam("cancelled")
	doc = frappe.get_doc(DT, x.name)
	kho, dich = doc.from_warehouse, doc.to_warehouse
	if not dich:
		raise NppLoi(T.THIEU_KHO_DICH)
	if dich == kho:
		raise T.loi_trung_kho(vung_cua_kho(kho, cd) or kho)
	dong = sorted(doc.items, key=lambda d: d.idx)
	if not dong:
		raise NppLoi(T.KHONG_CO_HANG)
	lay = _lay_lo(dong, kho, cd, chuyen=True, kho_dich=dich)
	_ghi_so(doc, dong, lay, kho, dich, cd)
	luc = now_datetime()
	for ma in {m for ds in lay if ds for m, _sl in ds}:
		frappe.db.set_value("Batch", ma, {"npp_chuyen_vung_luc": luc, "npp_chuyen_vung_boi": PN._nv(nc)}, update_modified=False)
	return doc.name


def _lay_lo(dong, kho: str, cd, *, chuyen: bool, kho_dich: str | None = None) -> list:
	"""Lượt một (gom theo mặt hàng, kiểm đủ trước khi trừ) rồi lượt hai (từng dòng theo `idx`, hạn cũ trước, dòng sau thấy phần dòng trước lấy) →
	[(mã lô, SL cơ sở)] mỗi dòng (None: hàng không lô / dòng SL ≤ 0)."""
	from nppsale.rpc.goi_lo import lo_theo_kho, vung_cua_kho
	from nppsale.rpc.tra_ncc import ton_kho_hang

	vung = vung_cua_kho(kho, cd) or "sale"
	cho = bool(cd.get("cho_ban_vuot_ton")) and not chuyen  # chuyển kho KHÔNG vượt tồn (mig 222 cố ý: đẻ tồn ở kho nhận)
	tt = {d.item_code: _thong_tin(d.item_code) for d in dong}
	for c in T.gom_can((d.item_code, d.uom, d.transfer_qty) for d in dong):
		it = tt[c.hang]
		co, ton = ton_kho_hang(c.hang, kho, bool(it.has_batch_no), cd)
		if ton < c.can and not (cho and not it.has_batch_no and cint(it.allow_negative_stock)):
			raise T.loi_khong_du_ton(it.item_name or c.hang, c.can, c.dv, vung, (co, ton), chuyen=chuyen)
	nguong = cd.get("nguong") if cd.get("nguong") is not None else K.NGUONG_MAC_DINH
	han_chot = add_days(getdate(nowdate()), nguong)
	lo_kho: dict = {}
	ra = []
	for d in dong:
		it = tt[d.item_code]
		can = K.so(d.transfer_qty)
		if can <= 0 or not it.has_batch_no:
			ra.append(None)
			continue
		kq = K.chon_lo_fefo(lo_kho.setdefault(d.item_code, lo_theo_kho(d.item_code, kho)), can)
		if chuyen and kho_dich == cd.kho_ban:
			for ma, _sl in kq.lay:  # mỗi lô được ghé (đủ thì dừng — lô sau không xét)
				han = frappe.db.get_value("Batch", ma, "expiry_date")
				if han and getdate(han) <= han_chot:
					raise T.loi_hang_gan_han(it.item_name or d.item_code, ma, han, nguong)
		if kq.thieu > 0:
			raise T.loi_lay_mat(it.item_name or d.item_code, kq.thieu)
		ra.append(kq.lay)
	return ra


def _ghi_so(doc, dong, lay, kho: str, dich: str | None, cd) -> None:
	"""Gói lô Outward mỗi dòng ở kho nguồn (lõi tự lập phía nhận ở kho đích cùng Batch), TK chênh lệch theo loại (xuất lẻ `tk_xuat_le` — không để lõi
	lặng lẽ điền `stock_adjustment_account`; chuyển kho để lõi điền), ghi sổ lúc bấm (giờ lấy SAU khoá, đủ micro giây — M2)."""
	from nppsale.rpc.goi_lo import gan_goi_lo, lap_goi_lo

	if dich is None and not cd.get("tk_xuat_le"):
		raise NppLoi("CAI_DAT_THIEU: NPP Cai Dat chưa có tài khoản xuất lẻ (tk_xuat_le).")
	luc = now_datetime()
	ngay, gio = luc.date(), luc.strftime("%H:%M:%S.%f")
	for d, l in zip(dong, lay, strict=True):
		d.s_warehouse = kho
		d.t_warehouse = dich
		if dich is None:
			d.expense_account = cd.tk_xuat_le
			if not l:  # hàng KHÔNG lô (chỉ nó được xuất âm — CFD-05 B): tồn 0 chưa từng có giá thì lõi đòi giá ("Valuation Rate … is required")
				d.allow_zero_valuation_rate = 1  # — nppsale không định giá phần âm; có giá bình quân thì lõi vẫn dùng giá ấy (V44c)
		if l:
			gan_goi_lo(d, lap_goi_lo("Outward", DT, d.item_code, kho, l, ngay, gio, cd.cong_ty))
	doc.update({"posting_date": ngay, "posting_time": gio, "set_posting_time": 1})
	doc.flags.ignore_permissions = True
	doc.save()
	doc.submit()
	frappe.local.message_log = []


# ================================================================================================ post_stock_import
def _chuan_bi_nhap(p=None):
	hien_tai()
	cai_dat_kho()
	p = _p(p)
	dong = p.get("lines") if isinstance(p, dict) and isinstance(p.get("lines"), list) else []
	frappe.local._npp_nk = {str(x.get("product_id")) for x in dong if isinstance(x, dict) and x.get("product_id")}


def _p(p):
	if isinstance(p, str):
		try:
			return json.loads(p) if p else {}
		except ValueError:
			return {}
	return p


@rpc("post_stock_import", ghi=True, chuan_bi=_chuan_bi_nhap)
def post_stock_import(p=None):
	from nppsale.rpc.xuat_hang import _khoa_bin

	nc = hien_tai()
	cd = cai_dat_kho()
	p = _p(p)
	hang = getattr(frappe.local, "_npp_nk", None)
	frappe.local._npp_nk = None
	if hang is None:  # gọi nội bộ không qua cổng
		dong = p.get("lines") if isinstance(p, dict) and isinstance(p.get("lines"), list) else []
		hang = {str(x.get("product_id")) for x in dong if isinstance(x, dict) and x.get("product_id")}
	_khoa_bin(hang, cd)  # câu ĐẦU (mã lạ không khớp Bin nào — không đọc gì trước khoá: ảnh chụp REPEATABLE READ lập sau)
	t = T.doc_tai_nhap(p)  # khối DECLARE: ép kiểu sai → 22007 / 22P02 trước cả vai
	PN._kiem_vai("post_stock_import", nc)
	T.kiem_dau_nhap(t)
	if t.ncc is not None and not frappe.db.exists("Supplier", t.ncc):
		raise NppLoi(T.NCC_KHAC, code="42501", http=403)
	T.kiem_vung_no(t)
	dong = [T.doc_dong_nhap(n, l, lambda h: bool(frappe.db.exists("Item", h))) for n, l in enumerate(t.dong, 1)]
	bay_gio = now_datetime()
	luc = gio_vao(t.luc.isoformat()) if t.luc is not None else bay_gio
	if luc.date() > bay_gio.date():
		raise NppLoi(T.NGAY_TUONG_LAI)
	luc = min(luc, bay_gio)  # cùng ngày mà giờ sau lúc bấm → lúc bấm (sổ kho không ghi giờ tương lai)
	kho_chon = _vung_kho(t.vung, cd)
	lo = _lap_lo(t, dong, luc, kho_chon, cd)
	if t.ncc is not None and t.no > 0:
		ten = _phieu_nhap_ncc(t, dong, lo, luc, kho_chon, cd)
		no = frappe.db.get_value("NPP Cong No NCC", {"chung_tu": ten}, "name")
	else:
		ten = _phieu_nhap_kho(t, dong, lo, luc, kho_chon, cd)
		no = None
	for ma in {x[0] for x in lo.values()}:
		frappe.db.set_value("Batch", ma, {"reference_doctype": "Purchase Invoice" if no else DT, "reference_name": ten}, update_modified=False)
	if luc.date() < bay_gio.date():
		_xep_repost()  # ghi lùi ngày (tồn đầu kỳ) — tính lại giá vốn các chứng từ sau (CFD-07)
	return [{"entry_id": ten, "entry_code": ten, "payable_id": no, "lines_written": len(dong)}]


def _lap_lo(t, dong, luc, kho_chon: str, cd) -> dict:
	"""Batch mỗi dòng mặt hàng theo lô → {n: (mã lô, kho dòng)}. Mã = mã gõ (trim) hoặc `LOT-<mã phiếu>-<n>`; đã có (kể cả dòng trước của cùng phiếu)
	→ `LO_TRUNG_MA`; ngày SX trống giữ trống (lõi tự điền hôm nay — đặt lại); hạn `2099-12-31` của hàng không hạn → trống; kho dòng = kho người chọn,
	kho bán mà hạn trong ngưỡng → kho cận date (ngày VN lúc bấm — `batches_auto_zone`)."""
	from nppsale.rpc.goi_lo import kho_nhan_lo

	ra: dict = {}
	hom_nay = getdate(nowdate())
	for d in dong:
		it = _thong_tin(d.hang)
		if not it.has_batch_no:
			continue
		ma = d.ma_lo or T.ma_lo_tu_dat(t.ma, d.n)
		# trùng trong CÙNG tải trọng cũng bắt ở đây: dòng trước đã lập Batch trong giao dịch này (khoá `name` không phân biệt hoa thường —
		# collation utf8mb4_unicode_ci)
		if frappe.db.exists("Batch", ma):
			raise T.loi_lo_trung(ma)
		han = T.han_lo(d.han, bool(it.has_expiry_date))
		kho = kho_nhan_lo(t.vung, han, cd, hom_nay)
		b = frappe.get_doc({"doctype": "Batch", "batch_id": ma, "item": d.hang, "manufacturing_date": d.nsx, "expiry_date": han,
			"npp_vi_tri": d.vi_tri, "npp_ngay_nhap": luc, "npp_kho_tao": kho, "npp_gia_von_lo_rong": float(d.gia_von),
			"npp_tim_kd": khoa_tim_ds(ma)}).insert(ignore_permissions=True)
		if not d.nsx:
			frappe.db.set_value("Batch", b.name, "manufacturing_date", None, update_modified=False)
		ra[d.n] = (b.name, kho)
	return ra


def _phieu_nhap_kho(t, dong, lo: dict, luc, kho_chon: str, cd) -> str:
	"""Nhánh B — Material Receipt `IN-…` (không NCC, hoặc có NCC mà không tiền nợ): giá mỗi đơn vị CƠ SỞ (`basic_rate` của lõi tính theo đơn vị kho
	— đo M4), giá 0 → `allow_zero_valuation_rate`; TK chênh lệch `tk_nhap_kho_khong_hd` (tạm: TK "hàng về chưa có hoá đơn" — nợ lập tay gắn phiếu
	tất toán), tồn đầu kỳ → `tk_tam_dau_ky` (lõi bắt TK tài sản / nợ cho tờ mở đầu)."""
	from nppsale.rpc.don_hang import _dam_bao_uom
	from nppsale.rpc.goi_lo import gan_goi_lo, kho_nhan_lo, lap_goi_lo

	dau_ky = T.la_ton_dau_ky(t.ma)
	tk = cd.get("tk_tam_dau_ky") if dau_ky else cd.get("tk_nhap_kho_khong_hd")
	if not tk:
		raise NppLoi("CAI_DAT_THIEU: NPP Cai Dat chưa có tài khoản " + ("tạm đầu kỳ (tk_tam_dau_ky)." if dau_ky else
			"nhập kho không công nợ (tk_nhap_kho_khong_hd)."))
	ngay, gio = luc.date(), luc.strftime("%H:%M:%S.%f")
	se = frappe.new_doc(DT)
	se.update({"naming_series": LOAI_NHAP["import"][2], "stock_entry_type": "Material Receipt", "purpose": "Material Receipt", "company": cd.cong_ty,
		"posting_date": ngay, "posting_time": gio, "set_posting_time": 1, "npp_loai": T.SE_DAU_KY if dau_ky else T.SE_NHAP,
		"is_opening": "Yes" if dau_ky else "No", "supplier": t.ncc, "npp_ghi_chu": t.ghi_chu, "to_warehouse": kho_chon, "npp_kho_nhap": kho_chon})
	for d in dong:
		it = _thong_tin(d.hang)
		sl, hs = T.sl_dong_se(d)
		dv = d.dv if hs == d.he_so and d.dv else it.stock_uom
		if dv:
			_dam_bao_uom(dv)
		x = lo.get(d.n)
		kho = x[1] if x else kho_nhan_lo(t.vung, None, cd)
		r = se.append("items", {"item_code": d.hang, "qty": float(sl), "uom": dv, "conversion_factor": float(hs), "t_warehouse": kho,
			"basic_rate": float(d.gia_von), "set_basic_rate_manually": 1, "allow_zero_valuation_rate": 1 if d.gia_von == 0 else 0,
			"expense_account": tk})
		if x:
			gan_goi_lo(r, lap_goi_lo("Inward", DT, d.hang, kho, {x[0]: d.sl_cs}, ngay, gio, cd.cong_ty))
	se.flags.ignore_permissions = True
	se.insert()
	se.submit()
	frappe.local.message_log = []
	return se.name


def _phieu_nhap_ncc(t, dong, lo: dict, luc, kho_chon: str, cd) -> str:
	"""Nhánh A — có NCC + tiền nợ > 0 → PHIẾU NHẬP `PN-` ghi sổ (CFD-13, câu 17; §7.3 điểm 3 — đề xuất): dòng `rate` = giá vốn × hệ số (giá vốn lô =
	`base_cost` như nppsale), MỘT dòng thuế `Actual` / `Total` bù phần nợ (`payable.amount` — màn tính từ đơn giá + VAT) lệch tổng giá vốn (TK tạm =
	TK thuế GTGT đầu vào — chờ kế toán chốt, BP §7.1 điểm 16); ngày ghi sổ = `posted_at`; ngày ghi nợ = lúc bấm; ghi chú nợ = "Nhập kho <mã>" như
	nppsale; KHÔNG ghi bảng giá nhập (nppsale không ghi giá nhập từ màn Nhập kho); dồn trả trước NCC (trigger `_trg_tra_truoc_vao_no_moi`)."""
	from nppsale.rpc.don_hang import _dam_bao_uom
	from nppsale.rpc.goi_lo import gan_goi_lo, kho_nhan_lo, lap_goi_lo
	from nppsale.thiet_lap.ban_hang import mau_thue_dong

	ngay, gio = luc.date(), luc.strftime("%H:%M:%S.%f")
	pi = frappe.new_doc("Purchase Invoice")
	pi.update({"naming_series": PN.DAY_SO, "npp_loai": PN.LOAI, "company": cd.cong_ty, "supplier": t.ncc, "posting_date": ngay, "posting_time": gio,
		"set_posting_time": 1, "update_stock": 1, "disable_rounded_total": 1, "ignore_pricing_rule": 1, "buying_price_list": cd.bang_gia_nhap,
		"set_warehouse": kho_chon, "npp_kho_nhap": kho_chon, "bill_no": t.so_hd, "bill_date": ngay, "npp_giam_dau_phieu": 0, "npp_ghi_chu": t.ghi_chu,
		"npp_ghi_chu_no": f"Nhập kho {t.ma}", "npp_hoan_thanh_luc": now_datetime(), "taxes_and_charges": ""})
	for d in dong:
		it = _thong_tin(d.hang)
		sl, hs = T.sl_dong_se(d)
		dv = d.dv if hs == d.he_so and d.dv else it.stock_uom
		if dv:
			_dam_bao_uom(dv)
		gia = d.gia_von * hs
		x = lo.get(d.n)
		kho = x[1] if x else kho_nhan_lo(t.vung, None, cd)
		r = pi.append("items", {"item_code": d.hang, "qty": float(sl), "uom": dv, "conversion_factor": float(hs), "price_list_rate": float(gia),
			"rate": float(gia), "discount_amount": 0, "discount_percentage": 0, "margin_type": "", "margin_rate_or_amount": 0, "npp_giam_dong": 0,
			"npp_thue_suat": 0, "item_tax_template": mau_thue_dong(0, cd.cong_ty), "warehouse": kho,
			"allow_zero_valuation_rate": 1 if gia == 0 else 0})
		if x:
			gan_goi_lo(r, lap_goi_lo("Inward", "Purchase Invoice", d.hang, kho, {x[0]: d.sl_cs}, ngay, gio, cd.cong_ty))
	pi.flags.ignore_permissions = True
	PN.dung_thue(pi, cd)  # bảng thuế như phiếu nhập M1 (dòng VAT của mẫu thuế mua — dòng hàng thuế suất 0 nên 0 đ)
	pi.run_method("set_missing_values")
	pi.calculate_taxes_and_totals()
	chenh = flt(t.no) - flt(pi.grand_total)
	if abs(chenh) >= 0.5:
		if not cd.get("tk_thue_dau_vao"):
			raise NppLoi("CAI_DAT_THIEU: NPP Cai Dat chưa có tài khoản thuế GTGT đầu vào (tk_thue_dau_vao).")
		pi.append("taxes", {"charge_type": "Actual", "account_head": cd.tk_thue_dau_vao, "description": "Phần nợ NCC lệch giá vốn (nhập kho)",
			"tax_amount": abs(chenh), "category": "Total", "add_deduct_tax": "Add" if chenh > 0 else "Deduct"})
	pi.insert()
	pi.submit()  # hook on_submit: chiếu dòng công nợ NCC (tao_luc = npp_hoan_thanh_luc)
	frappe.local.message_log = []
	from nppsale.su_kien.cong_no_ncc import don_tra_truoc_ncc

	don_tra_truoc_ncc(pi.supplier)
	return pi.name


# ================================================================================================ cancel_stock_entry
def _la_tra_khach(x) -> bool:
	"""Phiếu nhập lại hàng khách trả: Stock Entry `NL-` (`nhap_lai_tra`) hoặc tờ ghi có có kho `HDT-` — nhận diện bằng Link `npp_phieu_tra` (việc #24,
	§2.12 ⚠K: nppsale nhận theo ghi chú, sửa ghi chú là lách được — V18 / V54)."""
	return bool(x.phieu_tra) and ((x.dt == DT and x.npp_loai == T.SE_NHAP_LAI) or (x.dt == "Sales Invoice" and x.is_return))


@rpc("cancel_stock_entry", ghi=True, chuan_bi=_chuan_bi)
def cancel_stock_entry(p_entry_id=None, p_reason=None):
	nc = hien_tai()
	cd = cai_dat_kho()
	ten, hang = _da_chuan_bi(p_entry_id)
	x = _khoa(ten, hang, cd)
	if x is None:
		raise NppLoi(T.KHONG_THAY_PHIEU)
	PN._kiem_vai("cancel_stock_entry", nc)  # TRƯỚC bước "đã huỷ" như nppsale
	ly_do = _chu(p_reason)
	if x.trang_thai == "cancelled":
		# nppsale giữ phiếu kho gốc của các chứng từ này ở `posted` (HĐ huỷ / sửa lập phiếu hoàn kho riêng, huỷ phiếu trả lập phiếu "Đảo phiếu trả")
		# nên huỷ riêng nó báo câu của mig 227 — Frappe chứng từ gốc đã docstatus 2: giữ câu
		if x.dt == "Sales Invoice" and not x.is_return:
			raise T.loi_hd_da_huy(x.name, x.name)
		if _la_tra_khach(x):
			_loi_tra_khach(x)
		return T.ket_qua_huy(True, False, 0)
	if x.trang_thai == "draft":
		if x.dt == KK_DT:  # phiếu kiểm kê không submit — giữ phiếu `cancelled` + ghi chú như nppsale (bước 5)
			from nppsale.rpc.kiem_ke import huy_nhap

			return huy_nhap(x, ly_do)
		xoa_nhap(x.name)  # Stock Entry nháp — XOÁ nháp (§7.3 điểm 1: Frappe không cho nháp sang docstatus 2)
		return T.ket_qua_huy(True, False, 0)
	if x.dt == KK_DT:  # phiếu kiểm kê đã duyệt: nppsale bước 6f (`type` ∉ {import, export})
		raise T.loi_khong_hoan_duoc(x.name, "stocktake")
	if x.dt == "Purchase Invoice":
		raise (T.loi_nguon_phieu_nhap if x.npp_loai == PN.LOAI else T.loi_nguon_tra_ncc)(x.name)
	if _la_tra_khach(x):
		_loi_tra_khach(x)
	if x.dt == DT and frappe.db.exists("NPP Cong No NCC", {"phieu_kho": x.name}):
		raise T.loi_nguon_no_ncc(x.name)
	if x.dt == "Sales Invoice":
		raise T.loi_hd_dang_ghi(x.name, x.name)
	if x.purpose == "Material Transfer":
		raise T.loi_khong_hoan_duoc(x.name, "transfer")
	doc = frappe.get_doc(DT, x.name)
	so = _so_lo_xuat(doc) if x.purpose == "Material Issue" else _kiem_rut_nhap(doc, cd)
	doc.npp_ghi_chu = T.ghi_chu_huy(doc.get("npp_ghi_chu"), ly_do)
	doc.flags.ignore_permissions = True
	doc.cancel()  # lõi đảo gói lô — hàng về / rút khỏi ĐÚNG lô đã ghi
	frappe.local.message_log = []
	_xep_repost()
	return T.ket_qua_huy(True, True, so)


def _loi_tra_khach(x):
	tt = frappe.db.get_value("NPP Phieu Tra", x.phieu_tra, "trang_thai")
	raise (T.loi_nguon_tra_khach if tt == "completed" else T.loi_nguon_tra_khach_sua)(x.name)


def _so_lo_xuat(doc) -> int:
	"""`lines_reversed` của phiếu xuất = số LÔ khác nhau được hoàn (nppsale gom vết lấy lô theo lô) — hàng không lô tính mỗi (mặt hàng, kho) một "lô
	ảo" như cổng `batches`."""
	lo = {r[0] for r in frappe.db.sql("""SELECT DISTINCT e.`batch_no` FROM `tabSerial and Batch Bundle` b
		JOIN `tabSerial and Batch Entry` e ON e.`parent` = b.`name`
		WHERE b.`voucher_type` = %s AND b.`voucher_no` = %s AND b.`docstatus` = 1 AND b.`is_cancelled` = 0 AND IFNULL(e.`batch_no`, '') != ''""",
		(DT, doc.name))}
	ao = {(d.item_code, d.s_warehouse) for d in doc.items if not d.serial_and_batch_bundle and flt(d.transfer_qty) > 0}
	return len(lo) + len(ao)


def _kiem_rut_nhap(doc, cd) -> int:
	"""Huỷ phiếu nhập kho tay: từng dòng SL > 0 theo `idx` — tồn của lô TẠI KHO NHẬN (Σ gói lô) < SL nhập → `ALREADY_ISSUED` (nppsale so tồn lô với
	SL dòng; KHÔNG nới khi cho bán vượt tồn — hàng theo lô không bao giờ âm, CFD-05 B); hàng không lô: Bin của kho < Σ SL nhập của mặt hàng ở kho ấy
	và không được âm (đặc tả §3.19 Frappe bước 6 — được âm khi mặt hàng `allow_negative_stock` + NPP `cho_ban_vuot_ton`: lõi rút thành tồn âm).
	→ số dòng sẽ rút."""
	from nppsale.rpc.phieu_nhap import _ton_lo

	lo_dong = {d: lo for d, lo in frappe.db.sql("""SELECT b.`voucher_detail_no`, e.`batch_no` FROM `tabSerial and Batch Bundle` b
		JOIN `tabSerial and Batch Entry` e ON e.`parent` = b.`name`
		WHERE b.`voucher_type` = %s AND b.`voucher_no` = %s AND b.`docstatus` = 1 AND b.`is_cancelled` = 0 AND IFNULL(e.`batch_no`, '') != ''""",
		(DT, doc.name))}
	# §7.3 điểm 8 (M5 — đề xuất): lô đã bị rà sang kho cận date (phiếu `CKL-` `chuyen_date_tu_dong`) mà không động gì khác → huỷ trước phiếu ấy
	from nppsale.rpc.lo_kho import hoan_chuyen_date

	hoan_chuyen_date((DT, doc.name), {lo_dong[d.name]: (d.t_warehouse, flt(d.transfer_qty)) for d in doc.items if lo_dong.get(d.name)}, cd)
	khong_lo: dict = {}
	n = 0
	for d in sorted(doc.items, key=lambda r: r.idx):
		nhap = flt(d.transfer_qty)
		if nhap <= 0:
			continue
		n += 1
		lo = lo_dong.get(d.name)
		if lo:
			con = _ton_lo(lo, d.t_warehouse)
		else:
			k = (d.item_code, d.t_warehouse)
			khong_lo[k] = khong_lo.get(k, 0.0) + nhap
			nhap = khong_lo[k]
			if cd.get("cho_ban_vuot_ton") and cint(_thong_tin(d.item_code).allow_negative_stock):
				continue  # được âm (CFD-05 B)
			con = flt(frappe.db.get_value("Bin", {"item_code": d.item_code, "warehouse": d.t_warehouse}, "actual_qty"))
		if con < nhap - 1e-9:
			raise T.loi_da_xuat_bot(_ten_hang(d.item_code), doc.name, nhap, Decimal(str(round(con, 6))))
	return n


# ================================================================================================ RPC luồng cũ (§4.8 — soát thiếu S14)
@rpc("confirm_driver_handover")
def confirm_driver_handover(p_handover_id=None):
	"""Chuyến giao đã bỏ (CLAUDE.md "Chuyến giao" — 24/09/2026): màn `/deliveries/[id]/handover` bị chặn (`LEGACY_V2_HREFS`) nhưng tên vẫn có ở nppsale
	— đăng ký giữ tên để lời gọi lạc nhận câu nghiệp vụ thay PGRST202 (§7.3 điểm 40 — một luật với bảng không port `swap_stock_movements`)."""
	raise NppLoi("LEGACY_FLOW_REMOVED: chức năng đã gỡ")


@rpc("post_stock_export")
def post_stock_export(p_entry_id=None):
	"""Ghi sổ phiếu xuất kho kiểu cũ (P4 — M9, đặc tả kho_mua §3.21, V80): ở nppsale chỉ còn `_wf2_export_order` gọi (Xuất / Sửa HĐ — P3 đã dựng
	bằng Sales Invoice `update_stock`, luật FIFO ngày nhận / kho bán / `INSUFFICIENT_STOCK` nằm ở `post_invoice` — nppsale.luat.xuat_kho); màn
	`/inventory/stock-out` chặn từ 22/09/2026 (`LEGACY_V2_HREFS`), nút "TỰ GIAO HÀNG & THU TIỀN" khoá (`LEGACY_FLOW_WRITES_LOCKED`) → giữ tên, luôn
	ném câu luồng cũ (ba câu lỗi riêng của hàm cố ý không chép — §9.4)."""
	raise NppLoi("LEGACY_FLOW_REMOVED: chức năng đã gỡ")


# ================================================================================================ ghi thẳng phiếu kho nháp qua cổng (§4.5)
def _loai_cua(v) -> str:
	if v is None:
		raise LoiCong("23502", f'null value in column "type" of relation "{BANG}" violates not-null constraint', http=400)
	if v not in ("import", "export", "transfer", "stocktake"):
		raise LoiCong("23514", f'new row for relation "{BANG}" violates check constraint "stock_entries_type_check"', http=400)
	return v


def _vung_vao(v, cot: str, null_duoc: bool) -> str | None:
	if v is None:
		if null_duoc:
			return None
		raise LoiCong("23502", f'null value in column "{cot}" of relation "{BANG}" violates not-null constraint', http=400)
	if v not in K.VUNG:
		rang = "stock_entries_dest_warehouse_zone_check" if null_duoc else "stock_entries_zone_chk"
		raise LoiCong("23514", f'new row for relation "{BANG}" violates check constraint "{rang}"', http=400)
	return v


def _ncc_vao(v) -> str | None:
	if v in (None, ""):
		return None
	if not frappe.db.exists("Supplier", v):
		raise LoiCong("23503", f'insert or update on table "{BANG}" violates foreign key constraint "stock_entries_supplier_id_fkey"', http=409)
	return v


def _ap_dau(doc, loai: str, g: dict, cd) -> None:
	"""Cột nppsale của đầu phiếu nháp → trường Stock Entry: `warehouse_zone` (kho nguồn của xuất / chuyển, kho nhận của nhập), `dest_warehouse_zone`
	(kho đích — chỉ chuyển kho; trống / trùng nguồn vẫn lưu được, ghi sổ mới báo), `issue_reason` → `npp_ly_do_xuat`, `notes` → `npp_ghi_chu`,
	`supplier_id` → `supplier`. Cột lạ → PGRST204."""
	for k, v in g.items():
		if k in COT_BO or k in ("status", "type"):
			continue
		if k == "warehouse_zone":
			kho = _vung_kho(_vung_vao(v, k, False), cd)
			if loai == "import":
				doc.to_warehouse = doc.npp_kho_nhap = kho
			else:
				doc.from_warehouse = kho
		elif k == "dest_warehouse_zone":
			v = _vung_vao(v, k, True)
			if loai == "transfer":
				doc.to_warehouse = _vung_kho(v, cd) if v else None
		elif k == "issue_reason":
			doc.npp_ly_do_xuat = _chu(v)
		elif k == "notes":
			doc.npp_ghi_chu = _chu(v)
		elif k == "supplier_id":
			doc.supplier = _ncc_vao(v)
		else:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{BANG}' in the schema cache", http=400)


def _luu_nhap(doc) -> None:
	"""Lưu nháp KHÔNG qua `validate` của lõi (nháp chuyển kho thiếu / trùng kho đích phải lưu được — V49): tự điền đơn vị kho, SL cơ sở, kho dòng theo
	đầu phiếu; chặn dòng SL ≤ 0 (§7.3 điểm 23); khoá tìm theo tên."""
	dong = sorted(doc.items, key=lambda d: d.idx)
	T.kiem_dong_phieu_kho(d.transfer_qty for d in dong)
	nhap = doc.purpose == "Material Receipt"
	for d in dong:
		it = _thong_tin(d.item_code)
		d.stock_uom = it.stock_uom
		d.item_name = it.item_name
		d.s_warehouse = None if nhap else doc.from_warehouse
		d.t_warehouse = doc.to_warehouse if (nhap or doc.purpose == "Material Transfer") else None
	doc.flags.ignore_validate = True
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_permissions = True
	doc.save()
	_dat_tim(doc.name)


def them_phieu(ds: list[dict], nc) -> list[str]:
	"""INSERT stock_entries: phiếu NHÁP (trigger mig 170 chạy TRƯỚC RLS: `status` khác `draft` — kể cả quên cột, mặc định `posted` — →
	`SO_KHO_KHOA`), rồi vai owner / warehouse (RLS → 42501). `export` → Material Issue `XKL-`, `transfer` → Material Transfer `CKL-`, `import` →
	Material Receipt `IN-` nháp (không có đường ghi sổ — như nppsale), `stocktake` → phiếu kiểm kê nháp `NPP Kiem Ke` (M6)."""
	cd = cai_dat_kho()
	ra = []
	for g in ds:
		g = dict(g or {})
		if g.get("status", "posted") != "draft":
			raise NppLoi(T.NHAP_PHAI_NHAP)
		if nc.vai not in K.VAI_KHO_TAY and not nc.bo_qua_rls:
			tu_choi(BANG)
		kiem_org(g, BANG)
		loai = _loai_cua(g.get("type"))
		if loai == "stocktake":
			from nppsale.rpc.kiem_ke import them_phieu as them_kk

			ra.append(them_kk(g, cd))
			continue
		muc, npp_loai, day = LOAI_NHAP[loai]
		doc = frappe.new_doc(DT)
		luc = now_datetime()
		kho = _vung_kho("sale", cd)
		doc.update({"naming_series": day, "stock_entry_type": muc, "purpose": muc, "company": cd.cong_ty, "npp_loai": npp_loai,
			"posting_date": luc.date(), "posting_time": luc.strftime("%H:%M:%S"), "set_posting_time": 1})
		if loai == "import":
			doc.to_warehouse = doc.npp_kho_nhap = kho
		else:
			doc.from_warehouse = kho
		_ap_dau(doc, loai, g, cd)
		doc.flags.ignore_validate = True
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_permissions = True
		doc.insert()
		_dat_tim(doc.name)
		ra.append(doc.name)
	return ra


def _gia_tri_cot(x, k: str, cd):
	"""Giá trị hiện tại của cột nppsale `k` trên phiếu (để so `IS DISTINCT FROM` như trigger)."""
	from nppsale.rpc.goi_lo import vung_cua_kho

	if k == "type":
		return x.loai
	if k == "org_id":
		return lay_org_id()
	if k == "entry_code":
		return x.name
	if x.dt == KK_DT:
		from nppsale.rpc.kiem_ke import gia_tri_cot

		return gia_tri_cot(x, k, cd)
	if x.dt != DT:
		return None
	r = frappe.db.get_value(DT, x.name, ["npp_ly_do_xuat", "supplier", "posting_date", "posting_time", "owner", "npp_kho_nhap", "from_warehouse",
		"to_warehouse", "purpose"], as_dict=True)
	if k == "issue_reason":
		return r.npp_ly_do_xuat
	if k == "supplier_id":
		return r.supplier
	if k == "warehouse_zone":
		return vung_cua_kho(r.npp_kho_nhap or r.to_warehouse if r.purpose == "Material Receipt" else r.from_warehouse, cd)
	if k == "dest_warehouse_zone":
		return vung_cua_kho(r.to_warehouse, cd) if r.purpose == "Material Transfer" else None
	if k == "ref_order_ids":
		return []
	if k == "created_by":
		return None if r.owner in ("Administrator", "Guest") else r.owner
	if k == "posted_at":
		return None if x.trang_thai == "draft" else datetime.combine(getdate(r.posting_date), (datetime.min + r.posting_time).time())
	return None


def _khac(x, k: str, v, cd) -> bool:
	cu = _gia_tri_cot(x, k, cd)
	if k == "posted_at":
		return (gio_vao(v) if v else None) != cu
	if k == "ref_order_ids":
		return (v if v is not None else []) != cu
	return v != cu


def sua_phieu(gia_tri: dict, ids: list[str], nc) -> list[str]:
	"""UPDATE stock_entries: vai ngoài owner / warehouse → 0 dòng (RLS lọc trước trigger). Trigger mig 170: đổi `status` chỉ `draft → cancelled`
	(Frappe: XOÁ nháp); đổi `type` / `org_id` → "chỉ sửa được ghi chú"; phiếu không nháp: đổi `posted_at` / vùng → cùng câu, ⚠K mọi cột khác `notes`
	cũng vậy (tên chứng từ Frappe không đổi được; nppsale cho sửa `entry_code`, `issue_reason`, `supplier_id`, `ref_order_ids` — lách nhận diện
	nguồn, V54); `notes` ghi vào `npp_ghi_chu` (AOS) của Stock Entry — phiếu kho là HĐ / tờ ghi có / PI (chính chứng từ) → `SUA_O_CHUNG_TU_GOC`
	(§4.5 "dòng nguồn HĐ / PI → cấm")."""
	if nc.vai not in K.VAI_KHO_TAY and not nc.bo_qua_rls:
		return []
	cd = cai_dat_kho()
	g = dict(gia_tri or {})
	ra = []
	for ten in ids:
		x = nguon_phieu(ten)
		if x is None:
			continue
		if "status" in g and g["status"] != x.trang_thai:
			if x.trang_thai == "draft" and g["status"] == "cancelled" and x.dt == DT:
				xoa_nhap(x.name)  # huỷ nháp = xoá (§7.3 điểm 1)
				continue
			if x.trang_thai == "draft" and g["status"] == "cancelled" and x.dt == KK_DT:
				from nppsale.rpc.kiem_ke import doi_trang_thai_huy

				for k in ("type", "org_id"):
					if k in g and _khac(x, k, g[k], cd):
						raise NppLoi(T.CHI_SUA_GHI_CHU)
				doi_trang_thai_huy(x, g, cd)  # phiếu kiểm kê giữ phiếu (không submit) — như nppsale: cột của lệnh + trạng thái, ghi chú giữ
				ra.append(x.name)
				continue
			raise T.loi_doi_trang_thai(x.trang_thai, g["status"])
		for k in ("type", "org_id"):
			if k in g and _khac(x, k, g[k], cd):
				raise NppLoi(T.CHI_SUA_GHI_CHU)
		if x.trang_thai != "draft":
			for k, v in g.items():
				if k in ("status", "type", "org_id", "notes", "id", "created_at", "tim_kd"):
					continue
				if _khac(x, k, v, cd):
					raise NppLoi(T.CHI_SUA_GHI_CHU)
			if "notes" in g:
				if x.dt == KK_DT:
					from nppsale.rpc.kiem_ke import sua_ghi_chu

					sua_ghi_chu(x, g["notes"])
				elif x.dt != DT:
					raise NppLoi(T.SUA_O_CHUNG_TU_GOC)
				else:
					frappe.db.set_value(DT, x.name, "npp_ghi_chu", _chu(g["notes"]))
			ra.append(x.name)
			continue
		if x.dt == KK_DT:
			from nppsale.rpc.kiem_ke import sua_nhap

			sua_nhap(x, {k: v for k, v in g.items() if k != "status"}, cd)
			ra.append(x.name)
			continue
		doc = frappe.get_doc(DT, x.name)
		_ap_dau(doc, x.loai, {k: v for k, v in g.items() if k not in ("status",)}, cd)
		_luu_nhap(doc)
		ra.append(x.name)
	return ra


def xoa_phieu(ids: list[str], nc) -> list[str]:
	"""DELETE stock_entries: vai ngoài owner / warehouse → 0 dòng; phiếu đã ghi sổ / đã huỷ → `SO_KHO_KHOA: chỉ xoá được phiếu NHÁP…` (mã = tên
	chứng từ); nháp → xoá (cả dòng)."""
	if nc.vai not in K.VAI_KHO_TAY and not nc.bo_qua_rls:
		return []
	ra = []
	for ten in ids:
		x = nguon_phieu(ten)
		if x is None:
			continue
		if x.trang_thai != "draft":
			raise T.loi_xoa_khong_nhap(x.name, x.trang_thai)
		xoa_nhap(x.name, x.dt)
		ra.append(x.name)
	return ra


def _phieu_cha(ten, nc, ghi_moi: bool):
	"""Phiếu cha của lời ghi dòng (trigger mig 170 rồi RLS): không có → chèn: RLS 42501 (chính sách `EXISTS (phiếu của NPP)`) / sửa, xoá: bỏ qua; đã
	ghi sổ / đã huỷ → `SO_KHO_KHOA: phiếu đã % — …`; vai ngoài owner / warehouse → chèn 42501, sửa / xoá bỏ qua."""
	x = nguon_phieu(ten)
	if x is None:
		if ghi_moi:
			tu_choi(BANG_DONG)
		return None
	if x.trang_thai != "draft":
		raise T.loi_dong_khoa(x.trang_thai)
	if nc.vai not in K.VAI_KHO_TAY and not nc.bo_qua_rls:
		if ghi_moi:
			tu_choi(BANG_DONG)
		return None
	return frappe.get_doc(x.dt, x.name)


def _ap_dong(r, g: dict) -> None:
	"""Cột nppsale của một dòng → Stock Entry Detail: `product_id` → `item_code`, `unit_name` → `uom`, `qty_in_transaction_uom` → `qty`,
	`conversion_factor_snapshot` → `conversion_factor`, `qty_in_base_uom` → `transfer_qty` (SL cơ sở — nguồn sự thật của số vào / ra kho: SL × hệ số
	lệch thì dòng về đơn vị kho, hệ số 1), `notes` → `npp_ghi_chu`. `quantity` (ROUND SL cơ sở), `transaction_uom`, `unit_cost` (0), `batch_id`: bỏ."""
	from nppsale.rpc.don_hang import _dam_bao_uom

	for k, v in g.items():
		if k in COT_DONG_BO:
			continue
		if k == "product_id":
			if v is None:
				raise LoiCong("23502", f'null value in column "product_id" of relation "{BANG_DONG}" violates not-null constraint', http=400)
			if not frappe.db.exists("Item", v):
				raise LoiCong("23503", f'insert or update on table "{BANG_DONG}" violates foreign key constraint "stock_entry_lines_product_id_fkey"',
					http=409)
			r.item_code = v
		elif k == "unit_name":
			if v is None:
				raise LoiCong("23502", f'null value in column "unit_name" of relation "{BANG_DONG}" violates not-null constraint', http=400)
			if v:
				_dam_bao_uom(v)
			r.uom = v
		elif k == "qty_in_base_uom":
			if v is None:
				raise LoiCong("23502", f'null value in column "qty_in_base_uom" of relation "{BANG_DONG}" violates not-null constraint', http=400)
			r.transfer_qty = PN._so(v)
		elif k == "qty_in_transaction_uom":
			r.qty = PN._so(v)
		elif k == "conversion_factor_snapshot":
			r.conversion_factor = PN._so(v)
		elif k == "notes":
			r.npp_ghi_chu = _chu(v)
		else:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{BANG_DONG}' in the schema cache", http=400)
	sl, hs, cs = flt(r.get("qty")), flt(r.get("conversion_factor")) if r.get("conversion_factor") is not None else 1.0, flt(r.get("transfer_qty"))
	if r.get("qty") is None or abs(sl * hs - cs) > 1e-9:
		r.qty, r.conversion_factor = cs, 1  # SL × hệ số lệch / thiếu SL giao dịch → đơn vị kho (đặt ở `_luu_nhap`)
		r.flags._npp_dv_kho = True
	else:
		r.conversion_factor = hs


def _dong_moi(doc, g: dict):
	r = doc.append("items", {})
	_ap_dong(r, g)
	if not r.item_code:
		raise LoiCong("23502", f'null value in column "product_id" of relation "{BANG_DONG}" violates not-null constraint', http=400)
	if r.get("transfer_qty") is None:
		raise LoiCong("23502", f'null value in column "qty_in_base_uom" of relation "{BANG_DONG}" violates not-null constraint', http=400)
	if not r.uom and not r.flags.get("_npp_dv_kho"):
		raise LoiCong("23502", f'null value in column "unit_name" of relation "{BANG_DONG}" violates not-null constraint', http=400)
	if r.flags.get("_npp_dv_kho") or not r.uom:
		r.uom = frappe.db.get_value("Item", r.item_code, "stock_uom")
	return r


def them_dong(ds: list[dict], nc) -> list[str]:
	"""INSERT stock_entry_lines (màn xuất lẻ / chuyển kho chèn cả bộ dòng một lệnh) — trả tên từng dòng mới theo thứ tự gửi."""
	theo_phieu: dict = {}
	for g in ds:
		g = dict(g or {})
		theo_phieu.setdefault(_chu(g.get("entry_id")), []).append(g)
	ra = []
	for ten, dong in theo_phieu.items():
		doc = _phieu_cha(ten, nc, True)
		if doc.doctype == KK_DT:  # dòng kiểm kê: chênh có dấu, dòng 0 được (nppsale.rpc.kiem_ke)
			from nppsale.rpc.kiem_ke import them_dong as them_kk

			ra += [r.name for r in them_kk(doc, dong)]
			continue
		moi = [_dong_moi(doc, g) for g in dong]
		_luu_nhap(doc)
		ra += [r.name for r in moi]
	return ra


def sua_dong(gia_tri: dict, ids: list[str], nc) -> list[str]:
	g = dict(gia_tri or {})
	if g.get("entry_id") is not None:
		raise NppLoi(T.CHI_SUA_GHI_CHU)  # chuyển dòng sang phiếu khác
	theo_phieu: dict = {}
	for ten in ids:
		theo_phieu.setdefault(_phieu_cua_dong(ten), []).append(ten)
	ra = []
	for pk, ds in theo_phieu.items():
		doc = _phieu_cha(pk, nc, False)
		if doc is None:
			continue
		if doc.doctype == KK_DT:
			from nppsale.rpc.kiem_ke import sua_dong as sua_kk

			sua_kk(doc, ds, g)
			ra += ds
			continue
		for ten in ds:
			r = next(x for x in doc.items if x.name == ten)
			if any(k in g for k in ("qty_in_base_uom", "qty_in_transaction_uom", "conversion_factor_snapshot")):
				r.flags._npp_dv_kho = False
			_ap_dong(r, g)
			if r.flags.get("_npp_dv_kho"):
				r.uom = frappe.db.get_value("Item", r.item_code, "stock_uom")
		_luu_nhap(doc)
		ra += ds
	return ra


def xoa_dong(ids: list[str], nc) -> list[str]:
	theo_phieu: dict = {}
	for ten in ids:
		theo_phieu.setdefault(_phieu_cua_dong(ten), []).append(ten)
	ra = []
	for pk, ds in theo_phieu.items():
		doc = _phieu_cha(pk, nc, False)
		if doc is None:
			continue
		if doc.doctype == KK_DT:
			from nppsale.rpc.kiem_ke import xoa_dong as xoa_kk

			xoa_kk(doc, ds)
			ra += ds
			continue
		doc.set("items", [x for x in doc.items if x.name not in ds])
		for i, r in enumerate(doc.items, 1):
			r.idx = i
		_luu_nhap(doc)
		ra += ds
	return ra


def _phieu_cua_dong(ten: str) -> str | None:
	"""Phiếu cha của một dòng cổng: Stock Entry Detail → NPP Kiem Ke Dong → Sales Invoice Item → Purchase Invoice Item (dòng nguồn HĐ / PI chỉ để
	báo khoá)."""
	for bang in ("Stock Entry Detail", "NPP Kiem Ke Dong", "Sales Invoice Item", "Purchase Invoice Item"):
		if bang == "NPP Kiem Ke Dong" and not _co_kiem_ke():
			continue
		x = frappe.db.get_value(bang, ten, "parent")
		if x:
			return x
	return None
