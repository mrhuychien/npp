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
