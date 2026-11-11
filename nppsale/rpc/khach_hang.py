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


def _ve_khach_sql(nc) -> tuple[str, dict]:
	"""Vế customer_select (SECURITY INVOKER của mig 253 = RLS lọc theo người gọi) dạng câu SQL trên bí danh c."""
	from nppsale.cong.bang.khach_hang import ve_khach

	v = ve_khach(nc, "c.`name`")
	if v is None:
		return "1=1", {}
	if v is False:
		return "1=0", {}
	return v[0], v[1]


def _gioi_han(p_offset, p_limit) -> tuple[int, int]:
	return max(int(p_offset or 0), 0), min(max(int(p_limit or 50), 1), 200)


@rpc("khach_thieu_anh", ghi=False)
def khach_thieu_anh(p_tab: str = "all", p_offset: int = 0, p_limit: int = 50):
	"""Điểm bán đang hoạt động còn thiếu ảnh / vị trí (mig 253): lọc + đếm ảnh + phân trang trên máy chủ, mỗi dòng kèm total_count."""
	nc = hien_tai()
	ve, tham = _ve_khach_sql(nc)
	tab = p_tab or "all"
	dieu = {"no_photo": "kh.photo_count = 0", "no_gps": "kh.gps_lat IS NULL OR kh.gps_lng IS NULL"}.get(
		tab, "kh.photo_count = 0 OR kh.gps_lat IS NULL OR kh.gps_lng IS NULL")
	bo, lay = _gioi_han(p_offset, p_limit)
	ds = frappe.db.sql(f"""
		SELECT kh.*, COUNT(*) OVER () AS total_count FROM (
			SELECT c.`name` AS id, c.`customer_name` AS store_name, c.`npp_dia_chi` AS address, c.`npp_sdt` AS phone,
				NULLIF(c.`npp_vi_do`, 0) AS gps_lat, NULLIF(c.`npp_kinh_do`, 0) AS gps_lng,
				(SELECT COUNT(*) FROM `tabNPP Anh Diem Ban` p WHERE p.`khach` = c.`name`) AS photo_count
			FROM `tabCustomer` c
			WHERE IFNULL(c.`npp_trang_thai`, 'active') = 'active' AND ({ve})
		) kh
		WHERE {dieu}
		ORDER BY kh.store_name, kh.id
		LIMIT {lay} OFFSET {bo}
	""", tham, as_dict=True)
	return [{**r, "gps_lat": float(r.gps_lat) if r.gps_lat is not None else None, "gps_lng": float(r.gps_lng) if r.gps_lng is not None else None,
		"photo_count": int(r.photo_count), "total_count": int(r.total_count)} for r in ds]


@rpc("khach_cho_duyet_anh", ghi=False)
def khach_cho_duyet_anh(p_offset: int = 0, p_limit: int = 50):
	"""Điểm bán chờ duyệt ảnh + vị trí (mig 244 / 253): có yêu cầu đổi đang chờ, hoặc chưa duyệt mà đã có ảnh / vị trí."""
	nc = hien_tai()
	ve, tham = _ve_khach_sql(nc)
	bo, lay = _gioi_han(p_offset, p_limit)
	ds = frappe.db.sql(f"""
		SELECT kh.*, COUNT(*) OVER () AS total_count FROM (
			SELECT c.`name` AS id, c.`customer_name` AS store_name, c.`npp_dia_chi` AS address, c.`npp_sdt` AS phone,
				NULLIF(c.`npp_vi_do`, 0) AS gps_lat, NULLIF(c.`npp_kinh_do`, 0) AS gps_lng,
				(SELECT COUNT(*) FROM `tabNPP Anh Diem Ban` p WHERE p.`khach` = c.`name`) AS photo_count,
				(c.`npp_duyet_anh_luc` IS NOT NULL) AS da_duyet,
				(SELECT COUNT(*) FROM `tabNPP Yeu Cau Anh Diem Ban` r WHERE r.`khach` = c.`name` AND r.`trang_thai` = 'pending') AS so_yeu_cau
			FROM `tabCustomer` c
			WHERE IFNULL(c.`npp_trang_thai`, 'active') = 'active' AND ({ve})
		) kh
		WHERE kh.so_yeu_cau > 0 OR (NOT kh.da_duyet AND (kh.photo_count > 0 OR (kh.gps_lat IS NOT NULL AND kh.gps_lng IS NOT NULL)))
		ORDER BY kh.store_name, kh.id
		LIMIT {lay} OFFSET {bo}
	""", tham, as_dict=True)
	return [{**r, "gps_lat": float(r.gps_lat) if r.gps_lat is not None else None, "gps_lng": float(r.gps_lng) if r.gps_lng is not None else None,
		"photo_count": int(r.photo_count), "da_duyet": bool(r.da_duyet), "so_yeu_cau": int(r.so_yeu_cau), "total_count": int(r.total_count)}
		for r in ds]
