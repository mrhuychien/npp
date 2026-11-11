"""Năm vai của NPP (bản bàn bạc 3.5): Role Frappe không vào Desk (desk_access = 0 → người dùng là Website User), trang đầu /nppsale.
Mã vai nppsale ↔ Role: owner → NPP Chu, manager → NPP Quan Ly, accountant → NPP Ke Toan, sales → NPP NVBH, warehouse → NPP Thu Kho.
(`driver` đã ngưng — mig 122 — không có Role.)"""

VAI_ROLE = {
	"owner": "NPP Chu",
	"manager": "NPP Quan Ly",
	"accountant": "NPP Ke Toan",
	"sales": "NPP NVBH",
	"warehouse": "NPP Thu Kho",
}
ROLE_VAI = {r: v for v, r in VAI_ROLE.items()}


def dam_bao():
	import frappe

	for ten in VAI_ROLE.values():
		if frappe.db.exists("Role", ten):
			r = frappe.get_doc("Role", ten)
			doi = False
			for k, v in (("desk_access", 0), ("home_page", "/nppsale"), ("disabled", 0)):
				if r.get(k) != v:
					r.set(k, v)
					doi = True
			if doi:
				r.save(ignore_permissions=True)
			continue
		frappe.get_doc({"doctype": "Role", "role_name": ten, "desk_access": 0, "home_page": "/nppsale"}).insert(ignore_permissions=True)
