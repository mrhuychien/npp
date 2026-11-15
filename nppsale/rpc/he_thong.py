"""RPC hệ thống / đăng nhập."""
from __future__ import annotations

import frappe

from nppsale.luat.sdt import chuan_hoa_sdt

from . import rpc


@rpc("lookup_email_by_identifier", ghi=False, cho_khach=True, gioi_han_phut=20)
def lookup_email_by_identifier(p_id: str | None = None):
	"""SĐT → email kỹ thuật để đăng nhập (mig 106). Không phải số / không có ai → None (màn hiện một câu chung "Sai tài khoản hoặc
	mật khẩu" — người ngoài không dò được số nào có trong hệ thống)."""
	so = chuan_hoa_sdt(p_id)
	if not so:
		return None
	for ten, sdt in frappe.db.sql("SELECT name, sdt FROM `tabNPP Nhan Vien` WHERE IFNULL(sdt, '') != ''"):
		if chuan_hoa_sdt(sdt) == so:
			return ten
	return None


def _nv_dang_hoat_dong():
	"""Dòng users của người gọi khi `COALESCE(is_active, true)` — như user_org_id() / user_role() của nppsale (không xét mốc nghỉ)."""
	nv = frappe.db.get_value("NPP Nhan Vien", frappe.session.user, ["vai", "dang_hoat_dong"], as_dict=True)
	return nv if nv and (nv.dang_hoat_dong is None or nv.dang_hoat_dong) else None


@rpc("user_org_id", ghi=False)
def user_org_id():
	"""Mã đơn vị của người gọi (NPP Cai Dat.org_id — một site một NPP); không phải NV đang hoạt động → None."""
	return frappe.db.get_single_value("NPP Cai Dat", "org_id") if _nv_dang_hoat_dong() else None


@rpc("user_role", ghi=False)
def user_role():
	nv = _nv_dang_hoat_dong()
	return nv.vai if nv else None
