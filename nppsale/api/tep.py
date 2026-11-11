"""Kho tệp của portal (thay Supabase Storage) — chỉ bucket `customer-photos` (ảnh điểm bán; `visit-photos` / `pod-photos` không nhận
ảnh mới — blueprint 02 §8.2).

tai_len: multipart {bucket, path, upsert, file}. Đường dẫn đúng khuôn app tải lên `<org>/<khách>/<ô>-<ms>.jpg` (org = mã đơn vị của
site), khách tồn tại và người gọi thấy được, vai owner / manager / sales; `upsert` = 0 mà đã có → lỗi như Supabase (Duplicate).
Lưu File riêng tư gắn vào Customer, `npp_duong_dan` = "<bucket>/<path>" (unique) để tra khi phục vụ / dọn.
"""
from __future__ import annotations

import re

import frappe

BUCKET_ANH = "customer-photos"
VAI_ANH = ("owner", "manager", "sales")
_DUONG = re.compile(r"^(?P<org>[0-9a-fA-F-]{36})/(?P<khach>[^/]+)/[\w-]+\.jpg$")


def tach_duong(path: str, org_id: str) -> str | None:
	"""Mã khách của một đường dẫn ảnh đúng khuôn của ĐÚNG đơn vị; sai khuôn / có `..` / đơn vị khác → None (parseOrgPhotoPath)."""
	if not path or ".." in path or path.startswith("/"):
		return None
	m = _DUONG.match(path)
	if not m or m.group("org").lower() != (org_id or "").lower():
		return None
	return m.group("khach")


def _loi(msg: str, ma: str = "400"):
	return {"error": {"message": msg, "statusCode": ma}}


@frappe.whitelist(methods=["POST"])
def tai_len(bucket=None, path=None, upsert=None):
	from nppsale.cong.bang.khach_hang import thay_khach
	from nppsale.cong.ngu_canh import hien_tai

	nc = hien_tai()
	if nc.vai not in VAI_ANH:
		return _loi("new row violates row-level security policy", "403")
	if bucket != BUCKET_ANH:
		return _loi(f"Bucket {bucket} không nhận tệp mới", "400")
	khach = tach_duong(path or "", frappe.db.get_single_value("NPP Cai Dat", "org_id"))
	if not khach or not frappe.db.exists("Customer", khach) or not thay_khach(nc, khach):
		return _loi("new row violates row-level security policy", "403")
	tep = frappe.request.files.get("file") if frappe.request and frappe.request.files else None
	if not tep:
		return _loi("Thiếu tệp", "400")
	noi_dung = tep.stream.read()
	if len(noi_dung) > 8 * 1024 * 1024:
		return _loi("Ảnh quá lớn (tối đa 8 MB)", "413")
	duong = f"{bucket}/{path}"
	cu = frappe.db.get_value("File", {"npp_duong_dan": duong}, "name")
	if cu:
		if str(upsert) not in ("1", "true", "True"):
			return _loi("The resource already exists", "409")
		frappe.delete_doc("File", cu, ignore_permissions=True, force=True)
	f = frappe.get_doc({
		"doctype": "File", "file_name": path.rsplit("/", 1)[-1], "is_private": 1, "content": noi_dung,
		"attached_to_doctype": "Customer", "attached_to_name": khach, "npp_duong_dan": duong,
	})
	f.flags.ignore_permissions = True
	f.insert(ignore_permissions=True)
	return {"data": {"id": f.name, "path": path, "fullPath": duong}}
