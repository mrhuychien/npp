"""Phục vụ các tệp "tĩnh nhưng không được cache" của portal: sw.js (service worker) và manifest.

Vì sao không để trong /assets: Frappe/nginx gắn Cache-Control dài hạn cho /assets, còn service worker
phải được trình duyệt kiểm lại mỗi lần (và phải nằm dưới /nppsale/ để scope đúng). Tệp nguồn nằm ở
nppsale/public/portal/ (sau build Vite sẽ ghi đè bằng bản build).
"""
import os

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer

TEP = {
	"nppsale/sw.js": ("sw.js", "application/javascript; charset=utf-8"),
	"nppsale/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
}
THU_MUC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "portal")


class TepTinhPortal(BaseRenderer):
	"""Lưu ý: website_route_rules `/nppsale/<path:app_path>` đã viết lại endpoint thành `nppsale` TRƯỚC khi
	tới các renderer (PoC 05/11/2026: self.path == "nppsale" với mọi đường dẫn con) → phải nhìn đường dẫn
	gốc của request, không nhìn self.path."""

	@staticmethod
	def _duong_goc():
		try:
			return (frappe.local.request.path or "").strip("/ ")
		except Exception:
			return ""

	def can_render(self):
		return self._duong_goc() in TEP

	def render(self):
		ten, kieu = TEP[self._duong_goc()]
		duong = os.path.join(THU_MUC, ten)
		if not os.path.exists(duong):
			return self.build_response("", 404)
		with open(duong, "rb") as f:
			noi_dung = f.read()
		headers = {
			"Content-Type": kieu,
			"Cache-Control": "no-cache, must-revalidate",
			"X-Content-Type-Options": "nosniff",
		}
		if ten == "sw.js":
			headers["Service-Worker-Allowed"] = "/nppsale/"
		return self.build_response(noi_dung, 200, headers)
