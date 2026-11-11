"""Ngữ cảnh người gọi cho vế RLS: vai nppsale + quyền đã tính. Tính một lần mỗi request."""
from __future__ import annotations

import frappe

from .dang_ky import NguCanh


def hien_tai() -> NguCanh:
	nc = getattr(frappe.local, "_npp_ngu_canh", None)
	if nc is not None and nc.user == frappe.session.user:
		return nc
	user = frappe.session.user
	vai = None
	quyen = frozenset()
	them = {}
	if user and user != "Guest" and frappe.db.table_exists("NPP Nhan Vien"):
		nv = frappe.db.get_value("NPP Nhan Vien", {"user": user}, ["name", "vai"], as_dict=True)
		if nv:
			vai = nv.vai
			them["nhan_vien"] = nv.name
	try:
		from nppsale.quyen import quyen_hieu_luc  # P2: ma trận vai × ô × hành động + quyền riêng
		quyen = frozenset(quyen_hieu_luc(user, vai))
	except ImportError:
		pass
	nc = NguCanh(user=user, vai=vai, quyen=quyen, bo_qua_rls=(user == "Administrator"), them=them)
	frappe.local._npp_ngu_canh = nc
	return nc
