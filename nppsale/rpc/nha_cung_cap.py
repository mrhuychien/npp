"""NHÀ CUNG CẤP: đếm chứng từ, gộp, xoá (P4 — mốc M8; đặc tả kho_mua §3.13, §3.14, §5.3, §7.2 #22 / #23, §7.3 điểm 18 / 25, §9 S11 / S12; blueprint 02
§6.1 dòng `suppliers`, §4.1 `NPP Nhan Vien Cong Ty`; bàn bạc 4.1) — giữ tên nppsale (thân Postgres ở scratchpad kho_mua/src/<tên>.sql; câu lỗi nguyên
văn ở nppsale/luat/nha_cung_cap.py, cửa vai ở nppsale/luat/kho_mua.CUA_VAI).

Đếm chứng từ theo TÊN BẢNG nppsale (`dem_theo_bang` — dùng chung RPC đọc, gộp, xoá và cổng `suppliers` xoá thẳng):
- `payables` = dòng `NPP Cong No NCC` của NCC (mọi loại) + tờ nợ đầu kỳ / lập tay (`DKN-` / `NTN-`) KHÔNG ghi sổ mà không có tờ sửa thay (khoản nợ đã xoá
  ở màn công nợ: nppsale xoá dòng `payables`, bản Frappe huỷ tờ — tờ huỷ vẫn trỏ NCC, lõi chặn xoá NCC như khoá ngoại; ⚠K đặc tả §5.3 "số payables khác
  khi có tờ DKN / NTN … đã xoá");
- `products` = Item có `Item Default.default_supplier` = NCC; `purchase_invoices` / `supplier_returns` = Purchase Invoice phiếu nhập / trả NCC MỌI
  docstatus (theo `npp_loai` — tờ lập ngoài app theo tiền tố tên như bản chiếu công nợ); `stock_entries` = Stock Entry có `supplier` + phiếu nhập / trả
  NCC đã / thôi ghi sổ (phiếu kho của chúng là chính tờ — ⚠K §7.2 #14); `supplier_payments` = Payment Entry `phieu_chi_ncc` mọi docstatus;
  `purchase_orders` không port (0).

RPC (gộp / xoá theo khuôn CFD-05: `chuan_bi` đọc người gọi → cổng COMMIT → câu ĐẦU của thân hàm là khoá NCC `FOR UPDATE`):
- `so_chung_tu_ncc(p_supplier_id)` (mig 232 — SECURITY DEFINER, đọc): 4 vai mua hàng (thủ kho thấy cả `con_no` — §7.3 điểm 25 giữ y) → `KHONG_DU_QUYEN`
  (chỉ mã) → NCC không có → `KHONG_TIM_THAY_NCC` (chỉ mã) → `{tong, chi_tiet, nhan_vien, so_khoan_no, con_no}` (không kẹp dòng âm — mig 231).
- `gop_nha_cung_cap(p_tu, p_vao)` (mig 232): vai owner / manager / accountant → hai NCC khác nhau → khoá hai Supplier theo tên `FOR UPDATE` (+ mọi dòng
  công nợ của chúng — xếp hàng với Ghi trả / phiếu chi) → NCC giữ lại đã có nợ đầu kỳ thì tờ `DKN-` của NCC bị gộp thành nợ lập tay (`npp_loai` →
  `lap_tay`, ghi chú nối — kẻo `khoa_cho 'dau_ky:<NCC>'` trùng sau đổi tên; §7.3 điểm 18) → đếm `da_chuyen` TRƯỚC khi đổi tên → bỏ dòng phân công trùng
  (NV phụ trách cả hai — `ON CONFLICT DO NOTHING`) → điền hồ sơ trống của NCC giữ lại → đổi MỌI trường Dynamic Link trỏ NCC bị gộp (`party` của phiếu
  chi, sổ cái, Payment Ledger… — quét đủ trường, không dựa bộ đệm của lõi: `_doi_dynamic_link`) → `rename_doc(merge)` (đổi mọi Link: phiếu, phiếu kho,
  `Item Default`, phân công NV, dòng công nợ…; lõi xoá NCC cũ và xoá cache toàn site) → chiếu lại các dòng công nợ đã sang NCC giữ lại → tăng phiên
  danh mục (S11: đổi `Item Default` bằng SQL không qua `Item.on_update`). KHÔNG dồn trả trước (như nppsale — K23).
- `xoa_nha_cung_cap(p_id, p_xoa_hang)` (mig 233): ép kiểu `p_xoa_hang` (PostgREST — trước thân hàm) → chỉ Chủ NPP → khoá Supplier → còn chứng từ (bỏ mặt
  hàng) → `NCC_CO_CHUNG_TU` → mặt hàng lấy NCC làm NCC chính (khoá theo tên): gỡ NCC / ngừng bán + gỡ (có chứng từ) / xoá (Batch rỗng chưa có Serial and
  Batch Entry xoá trước — S12; vướng liên kết → ngừng bán như nhánh EXCEPTION) → xoá phân công NV (CASCADE) → xoá Supplier → tăng phiên danh mục.
"""
from __future__ import annotations

from decimal import Decimal

import frappe
from frappe.model.dynamic_links import get_dynamic_links
from frappe.model.rename_doc import rename_doc
from frappe.utils import cint, flt, getdate, nowdate

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai
from nppsale.day_so import giu_day_so, xoa_giu_day_so
from nppsale.luat import kho_mua as K
from nppsale.luat import nha_cung_cap as L
from nppsale.luat.tim import khoa_tim_ds
from nppsale.npp_he_thong.doctype.npp_phien_danh_muc.npp_phien_danh_muc import tang_phien_danh_muc
from nppsale.su_kien import cong_no_ncc as N

from . import rpc
from .phieu_tra import _bool_pg, _van_ban

DT_PC = "NPP Nhan Vien Cong Ty"
# cột hồ sơ nppsale ↔ trường Supplier (cổng `suppliers` — nppsale/cong/bang/nha_cung_cap.py `_ANH_XA`); hạn mức = `npp_co_han_muc` + `npp_han_muc`
TRUONG = {"category": "npp_nhom", "contact_name": "npp_nguoi_lien_he", "phone": "npp_dien_thoai", "email": "npp_email", "address": "npp_dia_chi",
	"tax_code": "tax_id", "bank_account": "npp_so_tai_khoan", "bank_name": "npp_ngan_hang", "legal_name": "npp_ten_phap_ly",
	"business_type": "npp_loai_hinh", "representative": "npp_dai_dien", "business_license_no": "npp_so_dkkd",
	"business_license_date": "npp_ngay_dkkd", "registered_address": "npp_dia_chi_dkkd", "notes": "supplier_details"}
# chứng từ chạm mặt hàng = khoá ngoại KHÔNG CASCADE trỏ `products` của nppsale (`_mat_hang_co_chung_tu`: dòng đơn, HĐ, phiếu nhập, đơn mua, phiếu kho,
# phiếu trả khách, phiếu trả NCC — PI trả NCC là Purchase Invoice Item; kiểm kê — `NPP Kiem Ke Dong`) + sổ kho / gói lô của bản Frappe
CHUNG_TU_HANG = (("Sales Order Item", "item_code"), ("Sales Invoice Item", "item_code"), ("Purchase Invoice Item", "item_code"),
	("Purchase Order Item", "item_code"), ("Stock Entry Detail", "item_code"), ("Stock Ledger Entry", "item_code"),
	("Serial and Batch Bundle", "item_code"), ("NPP Phieu Tra Dong", "mat_hang"), ("NPP Kiem Ke Dong", "mat_hang"))
_KHONG_TRUYEN = object()


# ================================================================================================ đếm chứng từ
def dem_theo_bang(ncc: str) -> dict[str, int]:
	"""Số dòng mỗi bảng nppsale trỏ NCC (xem đầu tệp) — `nppsale.luat.nha_cung_cap.dem_chung_tu` dựng `{tong, chi_tiet}` theo đúng thứ tự khoá ngoại."""
	so = dict.fromkeys(("payables", "products", "purchase_invoices", "stock_entries", "supplier_payments", "supplier_returns"), 0)
	so["payables"] = frappe.db.count(N.DT, {"nha_cung_cap": ncc})
	so["products"] = cint(frappe.db.sql("""SELECT COUNT(DISTINCT `parent`) FROM `tabItem Default` WHERE `parenttype` = 'Item'
		AND `default_supplier` = %s""", ncc)[0][0])
	pi = frappe.db.sql("""SELECT `name`, `docstatus`, `npp_loai`, `is_return`, `is_opening` FROM `tabPurchase Invoice` WHERE `supplier` = %s""", ncc,
		as_dict=True)
	sua = set(frappe.db.sql_list("""SELECT `amended_from` FROM `tabPurchase Invoice` WHERE `amended_from` IN %s""",
		(tuple(r.name for r in pi) or ("",),)))
	for r in pi:
		loai = N.loai_cua_pi(r.npp_loai, r.name, r.is_return, r.is_opening)
		if loai == "phieu_nhap":
			so["purchase_invoices"] += 1
		elif loai == "tra_ncc":
			so["supplier_returns"] += 1
		elif r.docstatus != 1 and r.name not in sua:
			so["payables"] += 1  # khoản nợ đầu kỳ / lập tay đã xoá: tờ huỷ không có tờ sửa thay
		if loai in ("phieu_nhap", "tra_ncc") and r.docstatus in (1, 2):
			so["stock_entries"] += 1
	so["stock_entries"] += frappe.db.count("Stock Entry", {"supplier": ncc})
	if frappe.get_meta("Payment Entry").has_field("npp_loai"):
		so["supplier_payments"] = frappe.db.count("Payment Entry", {"party_type": "Supplier", "party": ncc, "npp_loai": "phieu_chi_ncc"})
	return so


def _ra(x: Decimal):
	return int(x) if x == x.to_integral_value() else float(x)


@rpc("so_chung_tu_ncc", ghi=False)
def so_chung_tu_ncc(p_supplier_id=None):
	nc = hien_tai()
	loi = K.loi_vai("so_chung_tu_ncc", nc.vai)
	if loi is not None:
		raise loi
	ncc = _van_ban(p_supplier_id)
	if not ncc or not frappe.db.exists("Supplier", ncc):
		raise NppLoi(L.KHONG_TIM_THAY_DEM)
	ra = L.dem_chung_tu(dem_theo_bang(ncc))
	ra["nhan_vien"] = frappe.db.count(DT_PC, {"nha_cung_cap": ncc})
	mo = frappe.get_all(N.DT, filters={"nha_cung_cap": ncc, "trang_thai": ("!=", "paid")}, fields=["so_tien", "da_tra"])
	ra["so_khoan_no"] = len(mo)
	ra["con_no"] = _ra(sum((Decimal(str(round(flt(r.so_tien) - flt(r.da_tra), 2))) for r in mo), Decimal(0)))  # không kẹp (mig 231)
	return ra


# ================================================================================================ gộp
def _ho_so(ten: str) -> dict:
	"""Hồ sơ Supplier theo cột nppsale `suppliers` (cùng ánh xạ cổng)."""
	s = frappe.db.get_value("Supplier", ten, ["supplier_name", "npp_ma", "npp_co_han_muc", "npp_han_muc", *TRUONG.values()], as_dict=True)
	ra = {c: s.get(f) for c, f in TRUONG.items()}
	ra.update({"name": s.supplier_name, "code": s.npp_ma or None, "credit_limit": s.npp_han_muc if cint(s.npp_co_han_muc) else None})
	return ra


def _khoa_hai(tu: str, vao: str) -> tuple[str, str]:
	"""Khoá hai Supplier theo tên (`ORDER BY id FOR UPDATE` của nppsale — hai lượt gộp chéo nhau không khoá chết) → tên đúng chữ của sổ (collation không
	phân biệt hoa thường; nppsale so uuid)."""
	ten = {r[0].casefold(): r[0] for r in frappe.db.sql("""SELECT `name` FROM `tabSupplier` WHERE `name` IN (%s, %s) ORDER BY `name` FOR UPDATE""",
		(tu, vao))}
	if tu.casefold() not in ten:
		raise NppLoi(L.KHONG_TIM_THAY_TU)
	if vao.casefold() not in ten:
		raise NppLoi(L.KHONG_TIM_THAY_VAO)
	return ten[tu.casefold()], ten[vao.casefold()]


def _doi_dynamic_link(cu: str, moi: str) -> None:
	"""Đổi MỌI trường Dynamic Link trỏ Supplier `cu` sang `moi` (nppsale: UPDATE khoá ngoại từng bảng). `rename_doc` của lõi chỉ đổi bảng có trong bản đồ
	Dynamic Link (`get_dynamic_link_map`), mà bản đồ lấy tập DISTINCT loại liên kết NHỚ ĐỆM 12 giờ (`fetch_distinct_link_doctypes`) — dòng lập không qua
	bước kiểm liên kết (`ignore_links`: sổ cái khi bật sổ bất biến, bút toán lập lại…) không làm mới bộ đệm: bộ đệm chưa có 'Supplier' thì lõi bỏ sót,
	xoá NCC cũ xong phiếu chi / sổ cái / Payment Ledger còn trỏ NCC không còn. Quét đủ trường TRƯỚC khi đổi tên (lõi còn gì thì không còn dòng nào)."""
	for df in get_dynamic_links():
		meta = frappe.get_meta(df.parent)
		if not (meta.issingle or meta.is_virtual):  # Single / ảo không có bảng riêng (Custom Field đặt ở đó) — bỏ như lõi
			frappe.db.sql(f"""UPDATE `tab{df.parent}` SET `{df.fieldname}` = %s WHERE `{df.options}` = 'Supplier' AND `{df.fieldname}` = %s""",
				(moi, cu))


def _chuan_bi(**_ts):
	"""Trước khi khoá (khuôn CFD-05 — cổng COMMIT sau bước này rồi đặt savepoint): chỉ đọc người gọi; thân hàm mở đầu bằng câu khoá NCC `FOR UPDATE`
	nên ảnh chụp REPEATABLE READ lập SAU khoá (PoC 1d) — đếm chứng từ / dòng công nợ đọc số mới nhất."""
	hien_tai()


@rpc("gop_nha_cung_cap", ghi=True, chuan_bi=_chuan_bi)
def gop_nha_cung_cap(p_tu=None, p_vao=None):
	nc = hien_tai()
	loi = K.loi_vai("gop_nha_cung_cap", nc.vai)
	if loi is not None:
		raise loi
	tu, vao = _van_ban(p_tu) or None, _van_ban(p_vao) or None
	if tu is None or vao is None or tu.casefold() == vao.casefold():
		raise NppLoi(L.GOP_NCC_TRUNG)
	tu, vao = _khoa_hai(tu, vao)
	for x in sorted((tu, vao)):
		N.khoa_ncc(x)
	hom_nay = getdate(nowdate())  # giờ VN của site (nppsale `now() AT TIME ZONE 'Asia/Ho_Chi_Minh'`)
	ho_tu, ho_vao = _ho_so(tu), _ho_so(vao)
	# 0. mỗi NCC một dòng nợ đầu kỳ (`uq_payables_opening` ↔ `khoa_cho`): NCC giữ lại đã có → tờ đầu kỳ của NCC bị gộp thành nợ lập tay, số / đã trả
	#    giữ (TK của tờ giữ nguyên — chỉ đổi phân loại); trường `npp_loai` chỉ đọc sau ghi sổ → ghi thẳng TRƯỚC khi đổi tên — dòng chiếu lại ở bước 5
	#    ra `lap_tay`, khoá chờ trống (đổi tên trước thì chiếu lại ra `dau_ky:<NCC giữ lại>` trùng)
	if frappe.db.exists(N.DT, {"nha_cung_cap": vao, "loai": "dau_ky"}):
		for r in frappe.get_all(N.DT, filters={"nha_cung_cap": tu, "loai": "dau_ky"}, fields=["chung_tu"], order_by="name"):
			cu = frappe.db.get_value("Purchase Invoice", r.chung_tu, "npp_ghi_chu_no")
			frappe.db.set_value("Purchase Invoice", r.chung_tu, {"npp_loai": "lap_tay",
				"npp_ghi_chu_no": L.ghi_chu_dau_ky_gop(cu, ho_tu["name"], hom_nay)}, update_modified=False)
	# 1. bảng nppsale được chuyển (đếm TRƯỚC khi đổi tên — số dòng mỗi lệnh UPDATE của vòng khoá ngoại)
	da_chuyen = [{k: x[k] for k in ("bang", "cot", "so")} for x in L.dem_chung_tu(dem_theo_bang(tu))["chi_tiet"]]
	dong_no = frappe.get_all(N.DT, filters={"nha_cung_cap": tu}, fields=["name", "loai", "chung_tu", "phieu_chi"], order_by="name")
	# 2. phân công NV: NV phụ trách cả hai → bỏ dòng của NCC bị gộp (lõi đổi Link bằng SQL, không bỏ trùng — blueprint 02 `NPP Nhan Vien Cong Ty`)
	co_vao = set(frappe.get_all(DT_PC, filters={"nha_cung_cap": vao}, pluck="parent"))
	dong_tu = frappe.get_all(DT_PC, filters={"nha_cung_cap": tu}, fields=["name", "parent"])
	trung = [r.name for r in dong_tu if r.parent in co_vao]
	if trung:
		frappe.db.delete(DT_PC, {"name": ("in", trung)})
	nhan_vien = len({r.parent for r in dong_tu if r.parent not in co_vao})
	# 3. hồ sơ: ô trống của NCC giữ lại lấy của NCC bị gộp; ghi chú việc gộp (ghi thẳng như UPDATE của nppsale — Email / SĐT là chữ đã lưu của hai NCC)
	moi = L.ho_so_gop(ho_vao, ho_tu, hom_nay)
	gt = {f: moi[c] for c, f in TRUONG.items()}
	gt.update({"npp_co_han_muc": 0 if moi["credit_limit"] is None else 1, "npp_han_muc": moi["credit_limit"] or 0,
		"npp_tim_kd": khoa_tim_ds(ho_vao["name"], ho_vao["code"], moi["phone"], moi["tax_code"])})  # trigger `trg_tim_kd`
	frappe.db.set_value("Supplier", vao, gt)
	# 4. đổi mọi Dynamic Link rồi mọi Link sang NCC giữ lại, xoá NCC bị gộp (merge của lõi luôn xoá — ⚠K: không có nhánh "xoá không được → ngừng hợp
	#    tác"); `frappe.model.rename_doc` vì `frappe.rename_doc` không nhận ignore_permissions (vai NPP không có quyền ghi Supplier ở lớp Frappe)
	_doi_dynamic_link(tu, vao)
	with giu_day_so(tu):  # merge xoá NCC bị gộp bằng delete_doc → lõi lùi dãy `NCC-` nếu là số cuối (P4 đuôi — `nppsale.day_so`)
		rename_doc(doctype="Supplier", old=tu, new=vao, merge=True, force=True, ignore_permissions=True, show_alert=False, rebuild_search=False)
	frappe.local.message_log = []
	# 5. chiếu lại các dòng công nợ vừa sang NCC giữ lại (khoá chờ đầu kỳ, tên NCC); KHÔNG dồn trả trước (như nppsale — tới sự kiện kế tiếp)
	for r in dong_no:
		N.chieu_dong(r)
	tang_phien_danh_muc()  # S11: `Item Default.default_supplier` đổi bằng SQL — máy POS tải lại sổ hàng
	return {"vao": vao, "tu_ten": ho_tu["name"], "tu_ma": ho_tu["code"], "da_chuyen": da_chuyen, "nhan_vien": nhan_vien, "da_xoa": True}


# ================================================================================================ xoá
def mat_hang_co_chung_tu(hang: str) -> bool:
	"""`_mat_hang_co_chung_tu` (mig 233): dòng chứng từ bất kỳ (`CHUNG_TU_HANG` — nháp / đã huỷ cũng tính, như khoá ngoại). "Lô tồn ≠ 0" của nppsale nằm
	trong sổ kho (Bin tính từ Stock Ledger Entry); "lô đã có dòng phiếu kho" (kể cả tồn 0) nằm trong gói lô (`Serial and Batch Bundle.item_code`)."""
	return any(frappe.db.exists(dt, {truong: hang}) for dt, truong in CHUNG_TU_HANG)


def _go_ncc(hang: str, ncc: str, ngung_ban: bool) -> None:
	"""Gỡ NCC chính (dòng `Item Default` của NCC) — kèm ngừng bán. Ghi thẳng (nppsale UPDATE products); phiên danh mục tăng MỘT lần cuối method."""
	frappe.db.sql("""UPDATE `tabItem Default` SET `default_supplier` = NULL WHERE `parent` = %s AND `parenttype` = 'Item'
		AND `default_supplier` = %s""", (hang, ncc))
	if ngung_ban:
		frappe.db.set_value("Item", hang, "npp_ngung_ban", 1)
	frappe.clear_document_cache("Item", hang)


def _thu_xoa_hang(hang: str) -> bool:
	"""Xoá mặt hàng không chứng từ: Batch rỗng chưa có Serial and Batch Entry xoá trước (nppsale `batches` CASCADE theo mặt hàng — S12), rồi Item (lõi
	xoá Bin + Item Price bán / nhập ở `Item.on_trash`). Vướng liên kết → lui đúng phần này, False (nppsale `EXCEPTION WHEN foreign_key_violation`)."""
	frappe.db.savepoint("npp_xoa_hang")
	try:
		for lo in frappe.get_all("Batch", filters={"item": hang}, pluck="name", order_by="name"):
			if not frappe.db.exists("Serial and Batch Entry", {"batch_no": lo}):
				frappe.delete_doc("Batch", lo, ignore_permissions=True)
		frappe.delete_doc("Item", hang, ignore_permissions=True)
		return True
	except frappe.LinkExistsError:
		frappe.db.rollback(save_point="npp_xoa_hang")
		frappe.local.message_log = []
		return False


@rpc("xoa_nha_cung_cap", ghi=True, chuan_bi=_chuan_bi)
def xoa_nha_cung_cap(p_id=None, p_xoa_hang=_KHONG_TRUYEN):
	co_truyen = p_xoa_hang is not _KHONG_TRUYEN
	# PostgREST ép kiểu tham số TRƯỚC thân hàm (sai → 22P02); NULL gửi tường minh giữ NULL (luật ba trị của `IF NOT p_xoa_hang` — luat.xoa_hang_cua)
	gia_tri = _bool_pg(p_xoa_hang) if co_truyen and p_xoa_hang is not None else None
	xoa_hang = L.xoa_hang_cua(gia_tri, co_truyen)
	nc = hien_tai()
	loi = K.loi_vai("xoa_nha_cung_cap", nc.vai)
	if loi is not None:
		raise loi
	r = frappe.db.sql("SELECT `name`, `supplier_name`, `npp_ma` FROM `tabSupplier` WHERE `name` = %s FOR UPDATE", _van_ban(p_id) or "", as_dict=True)
	if not r:
		raise NppLoi(L.KHONG_TIM_THAY_XOA)
	ncc, ten, ma = r[0].name, r[0].supplier_name, r[0].npp_ma or None
	# 1. còn chứng từ (ngoài mặt hàng) → không xoá; mời ngừng hợp tác / gộp
	mo_ta = L.mo_ta_chung_tu(L.dem_chung_tu(dem_theo_bang(ncc))["chi_tiet"], bo_mat_hang=True)
	if mo_ta:
		raise L.loi_co_chung_tu(ten, mo_ta)
	# 2. mặt hàng lấy NCC làm NCC chính (khoá theo tên — nppsale `ORDER BY id FOR UPDATE`)
	da_xoa = ngung = go = 0
	for hang in frappe.db.sql_list("""SELECT i.`name` FROM `tabItem` i WHERE EXISTS (SELECT 1 FROM `tabItem Default` d WHERE d.`parent` = i.`name`
			AND d.`parenttype` = 'Item' AND d.`default_supplier` = %s) ORDER BY i.`name` FOR UPDATE""", ncc):
		nhanh = L.nhanh_mat_hang(xoa_hang, xoa_hang and mat_hang_co_chung_tu(hang))
		if nhanh == "go":
			_go_ncc(hang, ncc, ngung_ban=False)
			go += 1
		elif nhanh == "xoa" and _thu_xoa_hang(hang):
			da_xoa += 1
		else:
			_go_ncc(hang, ncc, ngung_ban=True)
			ngung += 1
	# 3. phân công NV (`user_suppliers` CASCADE) rồi NCC
	frappe.db.delete(DT_PC, {"nha_cung_cap": ncc})
	try:
		xoa_giu_day_so("Supplier", ncc)  # P4 đuôi: không lùi dãy `NCC-` — NCC lập sau không nhận lại id vừa xoá (nppsale uuid)
	except frappe.LinkExistsError:
		# chứng từ ngoài các bảng nppsale (lập ở Desk…) còn trỏ NCC — nppsale không có; giữ mã + lời mời của câu
		frappe.local.message_log = []
		raise L.loi_co_chung_tu(ten, "chứng từ khác trỏ tới nhà cung cấp") from None
	tang_phien_danh_muc()  # nppsale: UPDATE / DELETE products + hành động ON DELETE SET NULL đều kích trigger mức câu lệnh (kể cả 0 dòng — V84)
	return {"ten": ten, "ma": ma, "mat_hang_da_xoa": da_xoa, "mat_hang_ngung_ban": ngung, "mat_hang_go": go}
