"""Soát P4 (đặc tả kho_mua §4.5): phiếu kho do method lập thẳng (nhập kho tay `IN-` / `DK-` không NCC + nợ, nhập lại hàng khách trả `NL-`) từng thiếu
khoá tìm `npp_tim_kd` (nay hook `validate` của Stock Entry đặt — nppsale.su_kien.phieu_kho): điền lại khoá cho mọi Stock Entry đang trống."""
import frappe

from nppsale.luat.tim import khoa_tim_ds


def execute():
	if not frappe.db.has_column("Stock Entry", "npp_tim_kd"):
		return
	for ten in frappe.db.sql_list("SELECT `name` FROM `tabStock Entry` WHERE IFNULL(`npp_tim_kd`, '') = ''"):
		frappe.db.set_value("Stock Entry", ten, "npp_tim_kd", khoa_tim_ds(ten), update_modified=False)
