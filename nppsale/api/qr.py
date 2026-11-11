"""Mã QR đăng nhập (route cũ /api/admin/users/<id>/qr, /api/admin/users/qr-links, /qr-login của nppsale).

Mã = 32 byte ngẫu nhiên base64url (như randomBytes(32).toString("base64url")). Lưu MÃ HOÁ ở trường Password `qr_token` của
NPP Nhan Vien (chủ NPP hiện lại được QR như nppsale) + băm sha256 ở `qr_token_bam` (unique) để tra lúc đăng nhập. Phát mới là mã
cũ hết hiệu lực ngay; thu hồi là xoá cả ba trường.
"""
from __future__ import annotations

import hashlib
import secrets
from urllib.parse import quote

import frappe
from frappe.utils import get_url, now_datetime

from .tuyen import YeuCauCu, tuyen


def bam(token: str) -> str:
	return hashlib.sha256(token.encode("utf-8")).hexdigest()


def url_dang_nhap(token: str) -> str:
	return f"{get_url()}/nppsale/qr-login?t={quote(token)}"


def phat_ma(nhan_vien: str) -> str:
	token = secrets.token_urlsafe(32)
	nv = frappe.get_doc("NPP Nhan Vien", nhan_vien)
	nv.qr_token = token
	nv.qr_token_bam = bam(token)
	nv.qr_cap_luc = now_datetime()
	nv.save(ignore_permissions=True)
	return token


def _ma_hien_tai(nhan_vien: str) -> str | None:
	if not frappe.db.get_value("NPP Nhan Vien", nhan_vien, "qr_token_bam"):
		return None
	from frappe.utils.password import get_decrypted_password

	return get_decrypted_password("NPP Nhan Vien", nhan_vien, "qr_token", raise_exception=False)


def _chu_va_dich(dich: str):
	nv = frappe.db.get_value("NPP Nhan Vien", frappe.session.user, ["vai", "dang_hoat_dong"], as_dict=True)
	if not nv or nv.vai != "owner" or not nv.dang_hoat_dong:
		return 403, {"error": "Chỉ Chủ sở hữu mới được quản lý mã QR đăng nhập"}
	if not frappe.db.exists("NPP Nhan Vien", dich):
		return 404, {"error": "Không tìm thấy người dùng trong tổ chức"}
	return None


@tuyen("GET", r"^/api/admin/users/(?P<id>[^/]+)/qr$")
def lay(yc: YeuCauCu):
	dich = yc.tham["id"]
	if (loi := _chu_va_dich(dich)):
		return loi
	token = _ma_hien_tai(dich)
	nv = frappe.db.get_value("NPP Nhan Vien", dich, ["qr_cap_luc", "dang_hoat_dong"], as_dict=True)
	return 200, {"token": token, "loginUrl": url_dang_nhap(token) if token else None,
		"issuedAt": nv.qr_cap_luc.isoformat() if (token and nv.qr_cap_luc) else None, "isActive": bool(nv.dang_hoat_dong)}


@tuyen("POST", r"^/api/admin/users/(?P<id>[^/]+)/qr$")
def phat(yc: YeuCauCu):
	dich = yc.tham["id"]
	if (loi := _chu_va_dich(dich)):
		return loi
	token = phat_ma(dich)
	return 200, {"token": token, "loginUrl": url_dang_nhap(token),
		"issuedAt": frappe.db.get_value("NPP Nhan Vien", dich, "qr_cap_luc").isoformat()}


@tuyen("DELETE", r"^/api/admin/users/(?P<id>[^/]+)/qr$")
def thu_hoi(yc: YeuCauCu):
	dich = yc.tham["id"]
	if (loi := _chu_va_dich(dich)):
		return loi
	nv = frappe.get_doc("NPP Nhan Vien", dich)
	nv.qr_token = None
	nv.qr_token_bam = None
	nv.qr_cap_luc = None
	nv.save(ignore_permissions=True)
	frappe.db.delete("__Auth", {"doctype": "NPP Nhan Vien", "name": dich, "fieldname": "qr_token"})
	return 200, {"success": True}


@tuyen("GET", r"^/api/admin/users/qr-links$")
def ds_link(yc: YeuCauCu):
	nv = frappe.db.get_value("NPP Nhan Vien", frappe.session.user, ["vai", "dang_hoat_dong"], as_dict=True)
	if not nv or nv.vai != "owner" or not nv.dang_hoat_dong:
		return 403, {"error": "Chỉ Chủ sở hữu mới được quản lý mã QR đăng nhập"}
	links = {}
	for ten in frappe.get_all("NPP Nhan Vien", filters={"qr_token_bam": ["is", "set"]}, pluck="name"):
		token = _ma_hien_tai(ten)
		if token:
			links[ten] = url_dang_nhap(token)
	return 200, {"links": links}
