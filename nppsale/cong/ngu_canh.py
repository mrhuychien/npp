"""Ngữ cảnh người gọi cho vế RLS: vai nppsale + kiểm quyền (user_has_permission). Tính một lần mỗi request.

NV bị khoá (`dang_hoat_dong = 0`) hoặc đã nghỉ việc thì không có vai → mọi vế lọc từ chối — như `user_org_id()` của nppsale trả
NULL khi `is_active = false` (mọi chính sách chặn)."""
from __future__ import annotations

import frappe

from nppsale.luat.quyen import co_quyen as _co_quyen

from .dang_ky import NguCanh


def hien_tai() -> NguCanh:
	nc = getattr(frappe.local, "_npp_ngu_canh", None)
	if nc is not None and nc.user == frappe.session.user:
		return nc
	user = frappe.session.user
	vai = None
	them = {}
	if user and user != "Guest" and frappe.db.table_exists("NPP Nhan Vien"):
		nv = frappe.db.get_value("NPP Nhan Vien", user, ["name", "vai", "dang_hoat_dong", "nghi_viec_luc"], as_dict=True)
		if nv and nv.dang_hoat_dong and not nv.nghi_viec_luc:
			vai = nv.vai
			them["nhan_vien"] = nv.name
	nc = NguCanh(user=user, vai=vai, bo_qua_rls=(user == "Administrator"), them=them)
	frappe.local._npp_ngu_canh = nc
	return nc


def co_quyen(nc: NguCanh, khoa: str) -> bool:
	"""= public.user_has_permission(auth.uid(), khoa) (mig 166) — quyền riêng của người gọi + dòng quyền của vai, nạp một lần."""
	if nc.bo_qua_rls:
		return True
	if not nc.vai:
		return False
	bo = nc.them.get("_quyen")
	if bo is None:
		rieng = {r.khoa_quyen: bool(r.duoc_phep) for r in frappe.get_all("NPP Quyen Rieng", filters={"nhan_vien": nc.user},
			fields=["khoa_quyen", "duoc_phep"])}
		vai = {(nc.vai, r.mo_dun, r.hanh_dong): bool(r.duoc_phep) for r in frappe.get_all("NPP Quyen Vai", filters={"vai": nc.vai},
			fields=["mo_dun", "hanh_dong", "duoc_phep"])}
		bo = nc.them["_quyen"] = (rieng, vai)
	return _co_quyen(nc.vai, khoa, bo[0], bo[1])
