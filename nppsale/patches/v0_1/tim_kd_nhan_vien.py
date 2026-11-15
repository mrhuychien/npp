"""Blueprint 02 §7.2 mục 2 — một tên cho khoá tìm trên DocType riêng: `tim_kd` (bàn bạc 6.7). NPP Nhan Vien đổi `khoa_tim` → `tim_kd`:
tính lại khoá cho mọi NV (cột cũ để nguyên — Frappe không tự xoá cột; không còn ai đọc)."""
import frappe

from nppsale.luat.tim import khoa_tim_ds


def execute():
	if not frappe.db.has_column("NPP Nhan Vien", "tim_kd"):
		return
	for nv in frappe.get_all("NPP Nhan Vien", fields=["name", "ho_ten", "sdt"]):
		frappe.db.set_value("NPP Nhan Vien", nv.name, "tim_kd", khoa_tim_ds(nv.ho_ten, nv.sdt), update_modified=False)
