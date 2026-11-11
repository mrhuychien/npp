"""RPC khách hàng: search_customer_dupes (mig 245), claim_customer_for_me (mig 083)."""
from __future__ import annotations

import re

import frappe
from frappe.utils import today

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai
from nppsale.cong.sql import LoiCong

from . import rpc


@rpc("search_customer_dupes", ghi=False)
def search_customer_dupes(p_q: str | None = None):
	"""Tìm khách trùng SĐT trước khi tạo — CHỈ khớp đúng số (chủ nhà 15/10/2026): bỏ ký tự không số, 84 + 9 số → 0…, phải là 0 + 9..10
	số. Thấy cả khách của NV khác (như SECURITY DEFINER cũ) nhưng chỉ trả vài cột + tên NV chính + "đã của tôi chưa"; ≤ 20 dòng."""
	nc = hien_tai()
	if not nc.vai:
		return []
	so = re.sub(r"[^0-9]", "", p_q or "")
	if re.fullmatch(r"84\d{9}", so):
		so = "0" + so[2:]
	if not re.fullmatch(r"0\d{9,10}", so):
		return []
	ds = frappe.db.sql(
		"""
		SELECT c.`name` AS id, c.`customer_name` AS store_name, c.`npp_chu_cua_hang` AS owner_name, c.`npp_sdt` AS phone,
			c.`npp_dia_chi` AS address, c.`npp_phuong` AS ward, nv.`ho_ten` AS primary_user_name,
			EXISTS (SELECT 1 FROM `tabNPP Phan Cong Khach` m WHERE m.`khach` = c.`name` AND m.`nhan_vien` = %(u)s
				AND m.`trang_thai` = 'active') AS has_my_assignment
		FROM `tabCustomer` c
		LEFT JOIN `tabNPP Phan Cong Khach` pc ON pc.`khach` = c.`name` AND pc.`vai_tro` = 'primary' AND pc.`trang_thai` = 'active'
		LEFT JOIN `tabNPP Nhan Vien` nv ON nv.`name` = pc.`nhan_vien`
		WHERE (CASE WHEN REGEXP_REPLACE(IFNULL(c.`npp_sdt`, ''), '[^0-9]', '') REGEXP '^84[0-9]{9}$'
				THEN CONCAT('0', SUBSTRING(REGEXP_REPLACE(IFNULL(c.`npp_sdt`, ''), '[^0-9]', ''), 3))
				ELSE REGEXP_REPLACE(IFNULL(c.`npp_sdt`, ''), '[^0-9]', '') END) = %(so)s
		ORDER BY c.`customer_name`
		LIMIT 20
		""",
		{"u": nc.user, "so": so},
		as_dict=True,
	)
	return [dict(r, has_my_assignment=bool(r["has_my_assignment"])) for r in ds]


@rpc("claim_customer_for_me", ghi=True)
def claim_customer_for_me(p_customer_id: str):
	"""NVBH tự thêm một khách đã có vào danh sách của mình: đã có dòng active → already_assigned; khách đã có NV chính → phụ."""
	nc = hien_tai()
	if nc.vai != "sales":
		raise NppLoi("Chỉ vai trò sales mới được tự thêm khách hàng vào danh sách của mình")
	if not frappe.db.exists("Customer", p_customer_id):
		raise NppLoi("Khách hàng không tồn tại trong tổ chức")
	if frappe.db.exists("NPP Phan Cong Khach", {"khach": p_customer_id, "nhan_vien": nc.user, "trang_thai": "active"}):
		return {"status": "already_assigned"}
	co_chinh = frappe.db.exists("NPP Phan Cong Khach", {"khach": p_customer_id, "vai_tro": "primary", "trang_thai": "active"})
	vai = "secondary" if co_chinh else "primary"
	try:
		frappe.get_doc({"doctype": "NPP Phan Cong Khach", "khach": p_customer_id, "nhan_vien": nc.user, "vai_tro": vai,
			"trang_thai": "active", "ngay_phan_cong": today()}).insert(ignore_permissions=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError) as e:
		raise LoiCong("23505", 'duplicate key value violates unique constraint "customer_assignments_customer_id_user_id_key"', http=409) from e
	return {"status": "claimed", "role": vai}
