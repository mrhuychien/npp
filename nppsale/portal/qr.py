"""/nppsale/qr-login?t=<mã> — đăng nhập bằng mã QR (route /qr-login của nppsale).

Tra băm sha256 của mã ở NPP Nhan Vien.qr_token_bam; NV bị khoá / đã nghỉ / User tắt → về màn đăng nhập kèm ?qr=inactive (lõi
`login_as` không tự kiểm). Giới hạn 10 lượt / phút / IP như route cũ. Thành công → phiên mới → /nppsale/orders.
Renderer nhìn đường dẫn gốc của request vì website_route_rules đã viết lại /nppsale/<…> thành "nppsale" trước khi tới renderer.
"""
import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer

from nppsale.api.qr import bam

GIOI_HAN_PHUT = 10


def _duong():
	try:
		return (frappe.local.request.path or "").rstrip("/")
	except Exception:
		return ""


class DangNhapQR(BaseRenderer):
	def can_render(self):
		return _duong() == "/nppsale/qr-login"

	def _ve(self, dich: str):
		return self.build_response("", 302, {"Location": dich, "Cache-Control": "no-store"})

	def render(self):
		ip = getattr(frappe.local, "request_ip", None) or "?"
		k = frappe.cache.make_key(f"npp_rl:qr-login:{ip}")
		n = frappe.cache.incr(k)
		if n == 1:
			frappe.cache.expire(k, 60)
		if n > GIOI_HAN_PHUT:
			return self._ve("/nppsale/login?qr=invalid")
		t = (frappe.local.request.args.get("t") or "").strip()
		if len(t) < 16:
			return self._ve("/nppsale/login?qr=invalid")
		try:
			nv = frappe.db.get_value("NPP Nhan Vien", {"qr_token_bam": bam(t)}, ["name", "dang_hoat_dong", "nghi_viec_luc"], as_dict=True)
			if not nv:
				return self._ve("/nppsale/login?qr=invalid")
			if not nv.dang_hoat_dong or nv.nghi_viec_luc or not frappe.db.get_value("User", nv.name, "enabled"):
				return self._ve("/nppsale/login?qr=inactive")
			frappe.local.login_manager.login_as(nv.name)
			frappe.db.commit()
		except Exception:
			frappe.log_error(title="nppsale: đăng nhập QR lỗi")
			return self._ve("/nppsale/login?qr=server")
		return self._ve("/nppsale/orders")
