"""Vỏ (shell) của portal: mọi đường dẫn /nppsale/... đều trả về trang này (website_route_rules), React Router đọc phần còn lại.
no_cache=1 để Frappe không cache HTML (CSRF token + hồ sơ theo phiên)."""
import json

from nppsale.portal.vo import ngu_canh_trang, tai_san_vite

no_cache = 1


def get_context(context):
	context.no_cache = 1
	nc = ngu_canh_trang()
	# Chặn "</script>" trong dữ liệu (tên người dùng…) phá thẻ script.
	context.npp_context_json = json.dumps(nc, ensure_ascii=False, default=str).replace("</", "<\\/")
	context.csrf_token = nc["csrf_token"]
	context.tai_san = tai_san_vite()
