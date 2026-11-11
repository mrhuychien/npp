"""DocPerm sàn cho năm vai NPP (bản bàn bạc chốt, mục 3.5 dòng "Lớp Frappe (DocPerm) = sàn an toàn").

Method của app lập chứng từ lõi (Sales Order, Sales Invoice…) dưới chính người dùng để chủ chứng từ / người sửa đúng người; lõi tự kiểm
quyền ĐỌC danh mục trong lúc ấy (vd. `get_item_details` gọi `item.check_permission()`; cờ bỏ qua quyền của tờ không lan sang). Vì
vậy vai NPP được ĐỌC danh mục ở lớp Frappe — chỉ đọc, không ghi; ghi chứng từ tiền / kho không cấp cho ai (chỉ method).

Đọc ở lớp Frappe KHÔNG phải lối đọc của người dùng: các cửa đọc chung của lõi (`/api/resource`, `frappe.client.*`,
`frappe.desk.*`…) bị chặn với người chỉ mang vai NPP (`nppsale.portal.chan`) — mọi đọc đi qua cổng / method của app đã lọc theo vai
(hàng của công ty khác, HĐ của NV khác không lộ). Không dùng User Permission theo Item / Brand (chặn chính HĐ có hàng ngoài công ty).
"""
from __future__ import annotations

import frappe

from .vai import VAI_ROLE

# DocType lõi → quyền (permlevel 0) cấp cho mọi vai NPP. Thêm DocType vào đây khi một luồng của lõi kiểm quyền đọc nó — kèm bài kiểm
# chạy luồng ấy dưới vai NPP (tests/test_tao_don.py …).
SAN: dict[str, tuple[str, ...]] = {
	"Item": ("read", "select"),
	"Item Group": ("read", "select"),
	"Brand": ("read", "select"),
	"UOM": ("read", "select"),
	"Price List": ("read", "select"),
	"Item Price": ("read", "select"),
	"Item Tax Template": ("read", "select"),
	"Customer": ("read", "select"),
	"Customer Group": ("read", "select"),
	"Warehouse": ("read", "select"),
	"Sales Taxes and Charges Template": ("read", "select"),
	"Payment Terms Template": ("read", "select"),
	"Account": ("read", "select"),  # get_party_account → account_perm_check (Sales Order.validate)
}


def dam_bao():
	for dt, quyen in SAN.items():
		if not frappe.db.exists("DocType", dt):
			continue
		for role in VAI_ROLE.values():
			if not frappe.db.exists("Role", role):
				continue
			ten = frappe.db.get_value("Custom DocPerm", {"parent": dt, "role": role, "permlevel": 0, "if_owner": 0})
			if not ten:
				from frappe.permissions import setup_custom_perms

				setup_custom_perms(dt)  # chép DocPerm chuẩn sang Custom DocPerm lần đầu — không mất quyền vai lõi
				ten = frappe.get_doc({"doctype": "Custom DocPerm", "parent": dt, "parenttype": "DocType", "parentfield": "permissions",
					"role": role, "permlevel": 0, "read": 0}).insert(ignore_permissions=True).name
			cu = frappe.db.get_value("Custom DocPerm", ten, list(quyen), as_dict=True)
			thieu = {p: 1 for p in quyen if not cu.get(p)}
			if thieu:
				frappe.db.set_value("Custom DocPerm", ten, thieu, update_modified=False)
				frappe.clear_cache(doctype=dt)
