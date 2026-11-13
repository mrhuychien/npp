"""Bản ghi mặc định của app: NPP Cai Dat (org_id cố định của site, công ty sổ sách), NPP Phien Danh Muc "1", dòng quyền vai gieo
sẵn (= _gieo_quyen_mac_dinh mig 166). Chỉ chạy phần có DocType trên site."""
import uuid

import frappe

from nppsale.luat.quyen import DONG_VAI_GIEO_SAN


def _co(dt: str) -> bool:
	return bool(frappe.db.exists("DocType", dt))


def _dat_ten_chung_tu():
	"""Khách KH-.#####, NCC NCC-.#### (Selling / Buying Settings = Naming Series; bản bàn bạc 3.11)."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	# Customer.autoname đọc mặc định toàn cục cust_master_name (Selling Settings.on_update ghi) — lưu qua controller, không set thẳng
	if frappe.db.get_single_value("Selling Settings", "cust_master_name") != "Naming Series" or (
		frappe.defaults.get_global_default("cust_master_name") != "Naming Series"
	):
		ss = frappe.get_single("Selling Settings")
		ss.cust_master_name = "Naming Series"
		ss.flags.ignore_mandatory = True
		ss.save(ignore_permissions=True)
	# (DocType, lựa chọn naming_series, mặc định) — HĐ bán HD-, tờ ghi có của phiếu trả HDT-, tờ nợ đầu kỳ DK- (blueprint 02 §2.4 / §5.6)
	for dt, chon, mac in (("Customer", "KH-.#####", "KH-.#####"), ("Supplier", "NCC-.####", "NCC-.####"),
			("Sales Order", "DH-.####", "DH-.####"), ("Sales Invoice", "HD-.####\nHDT-.####\nDK-.####", "HD-.####")):
		for prop, gt in (("options", chon), ("default", mac)):
			if frappe.db.get_value("Property Setter", {"doc_type": dt, "field_name": "naming_series", "property": prop}, "value") != gt:
				make_property_setter(dt, "naming_series", prop, gt, "Text", validate_fields_for_doctype=False)
	# NCC đặt tên theo dãy (Buying Settings supp_master_name — Supplier.autoname đọc mặc định toàn cục)
	if frappe.db.get_single_value("Buying Settings", "supp_master_name") != "Naming Series" or (
		frappe.defaults.get_global_default("supp_master_name") != "Naming Series"
	):
		bs = frappe.get_single("Buying Settings")
		bs.supp_master_name = "Naming Series"
		bs.flags.ignore_mandatory = True
		bs.save(ignore_permissions=True)


def _bang_gia():
	"""Bảng giá (blueprint 02 §3.1 / 3.5): Gia chuan (bán, nhóm NULL), Gia nhom <tên> mỗi nhóm khách lá, Gia nhap (mua).
	Selling Settings dùng Gia chuan; tắt tự chèn giá khi thiếu (lõi tự lập Item Price từ đơn giá dòng — PoC 2)."""
	from nppsale.su_kien.san_pham import GIA_CHUAN, GIA_NHAP, bang_gia_nhom, dam_bao_bang_gia

	dam_bao_bang_gia(GIA_CHUAN, ban=True)
	dam_bao_bang_gia(GIA_NHAP, ban=False)
	for g in frappe.get_all("Customer Group", filters={"is_group": 0}, fields=["name", "default_price_list"]):
		if not g.default_price_list:
			ten = bang_gia_nhom(g.name)
			dam_bao_bang_gia(ten, ban=True)
			frappe.db.set_value("Customer Group", g.name, "default_price_list", ten)
	if frappe.db.get_single_value("Selling Settings", "selling_price_list") != GIA_CHUAN:
		frappe.db.set_single_value("Selling Settings", "selling_price_list", GIA_CHUAN)
	if frappe.db.get_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing"):
		frappe.db.set_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing", 0)


def dam_bao():
	_dat_ten_chung_tu()
	_bang_gia()
	if _co("NPP Cai Dat"):
		cd = frappe.get_single("NPP Cai Dat")
		doi = False
		if not cd.get("org_id"):
			cd.org_id = str(uuid.uuid4())
			doi = True
		if not cd.get("cong_ty"):
			cong_ty = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
			if cong_ty:
				cd.cong_ty = cong_ty
				doi = True
		if not cd.get("ten_npp") and cd.get("cong_ty"):
			cd.ten_npp = cd.cong_ty
			doi = True
		if doi:
			cd.flags.ignore_mandatory = True
			cd.save(ignore_permissions=True)
	if _co("NPP Phien Danh Muc") and not frappe.db.exists("NPP Phien Danh Muc", "1"):
		frappe.get_doc({"doctype": "NPP Phien Danh Muc", "name": "1", "phien": 1, "phien_khach": 1}).insert(ignore_permissions=True)
	if _co("NPP Quyen Vai"):
		for vai, mo_dun, hanh_dong in DONG_VAI_GIEO_SAN:
			ten = f"{vai}:{mo_dun}:{hanh_dong}"
			if not frappe.db.exists("NPP Quyen Vai", ten):
				frappe.get_doc({"doctype": "NPP Quyen Vai", "vai": vai, "mo_dun": mo_dun, "hanh_dong": hanh_dong, "duoc_phep": 1}).insert(
					ignore_permissions=True
				)
