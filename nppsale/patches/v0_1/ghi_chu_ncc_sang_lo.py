"""Blueprint 02 §7.2 "Supplier.npp_ghi_chu → supplier_details": ghi chú NCC (`suppliers.notes`) đi thẳng vào trường lõi `supplier_details`
(Text) thay Custom Field riêng. Chép ghi chú cũ sang ô lõi khi ô lõi còn trống rồi xoá Custom Field `Supplier-npp_ghi_chu` —
`create_custom_fields(update=True)` (thiet_lap/truong_tuy_bien.py) không tự xoá trường nào. Cột cũ để nguyên (Frappe không tự xoá cột)."""
import frappe


def execute():
	if not frappe.db.exists("Custom Field", "Supplier-npp_ghi_chu"):
		return
	if frappe.db.has_column("Supplier", "npp_ghi_chu"):
		frappe.db.sql("""UPDATE `tabSupplier` SET `supplier_details` = `npp_ghi_chu`
			WHERE IFNULL(`supplier_details`, '') = '' AND IFNULL(`npp_ghi_chu`, '') != ''""")
	frappe.delete_doc("Custom Field", "Supplier-npp_ghi_chu", ignore_permissions=True, force=True)
	frappe.clear_cache(doctype="Supplier")
