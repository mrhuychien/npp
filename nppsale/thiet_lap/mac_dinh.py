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
	for dt, mau in (("Customer", "KH-.#####"), ("Supplier", "NCC-.####")):
		for prop in ("options", "default"):
			if frappe.db.get_value("Property Setter", {"doc_type": dt, "field_name": "naming_series", "property": prop}, "value") != mau:
				make_property_setter(dt, "naming_series", prop, mau, "Text", validate_fields_for_doctype=False)
	# NCC đặt tên theo dãy (Buying Settings supp_master_name — Supplier.autoname đọc mặc định toàn cục)
	if frappe.db.get_single_value("Buying Settings", "supp_master_name") != "Naming Series" or (
		frappe.defaults.get_global_default("supp_master_name") != "Naming Series"
	):
		bs = frappe.get_single("Buying Settings")
		bs.supp_master_name = "Naming Series"
		bs.flags.ignore_mandatory = True
		bs.save(ignore_permissions=True)


def dam_bao():
	_dat_ten_chung_tu()
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
