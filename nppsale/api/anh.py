"""/api/customers/photo-cleanup của nppsale: xoá file ảnh điểm bán không còn dòng ảnh / yêu cầu đang chờ nào trỏ tới. Chỉ
owner / manager / sales; chỉ file đúng khuôn của đúng đơn vị; tối đa 10 đường dẫn một lần; trả {removed, skipped}."""
from __future__ import annotations

import frappe

from .tep import BUCKET_ANH, VAI_ANH, tach_duong
from .tuyen import YeuCauCu, tuyen

TOI_DA = 10


def _duong_cua_url(url: str | None) -> str | None:
	"""photoStoragePath: URL ảnh → đường dẫn trong kho."""
	if not url:
		return None
	dau = f"/storage/v1/object/public/{BUCKET_ANH}/"
	i = url.find(dau)
	if i < 0:
		return None
	from urllib.parse import unquote

	p = unquote(url[i + len(dau):].split("?")[0].split("#")[0])
	return p if p and ".." not in p and not p.startswith("/") else None


@tuyen("POST", r"^/api/customers/photo-cleanup$")
def don_file(yc: YeuCauCu):
	from nppsale.cong.ngu_canh import hien_tai

	nc = hien_tai()
	if nc.vai not in VAI_ANH:
		return 403, {"error": "Không có quyền xoá ảnh điểm bán"}
	hoi = [p for p in (yc.json().get("paths") or []) if isinstance(p, str)][:TOI_DA]
	org = frappe.db.get_single_value("NPP Cai Dat", "org_id")
	cua_minh = [(p, tach_duong(p, org)) for p in hoi]
	cua_minh = [(p, k) for p, k in cua_minh if k]
	if not cua_minh:
		return 200, {"removed": [], "skipped": hoi}
	khach = list({k for _, k in cua_minh})
	dang_dung = set()
	for (u,) in frappe.db.sql("SELECT anh_url FROM `tabNPP Anh Diem Ban` WHERE khach IN %(k)s", {"k": tuple(khach)}):
		dang_dung.add(_duong_cua_url(u))
	for (u,) in frappe.db.sql("SELECT anh_url FROM `tabNPP Yeu Cau Anh Diem Ban` WHERE khach IN %(k)s AND trang_thai = 'pending'",
			{"k": tuple(khach)}):
		dang_dung.add(_duong_cua_url(u))
	xoa = [p for p, _ in cua_minh if p not in dang_dung]
	for p in xoa:
		ten = frappe.db.get_value("File", {"npp_duong_dan": f"{BUCKET_ANH}/{p}"}, "name")
		if ten:
			frappe.delete_doc("File", ten, ignore_permissions=True, force=True)
	return 200, {"removed": xoa, "skipped": [p for p in hoi if p not in xoa]}
