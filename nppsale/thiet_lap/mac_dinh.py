"""Bản ghi mặc định của app: NPP Cai Dat (org_id cố định của site, công ty sổ sách), NPP Phien Danh Muc "1", dòng quyền vai gieo
sẵn (= _gieo_quyen_mac_dinh mig 166). Chỉ chạy phần có DocType trên site."""
import uuid

import frappe

from nppsale.luat.quyen import DONG_VAI_GIEO_SAN


def _co(dt: str) -> bool:
	return bool(frappe.db.exists("DocType", dt))


def dam_bao():
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
