"""Vỏ (shell) của SPA portal: mọi đường dẫn /nppsale/... đều trả về trang này (website_route_rules),
router của SPA đọc phần còn lại. no_cache=1 để Frappe không cache HTML (CSRF token theo phiên)."""
import frappe

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.duong_dan_app = frappe.form_dict.get("app_path") or ""
	context.csrf_token = frappe.sessions.get_csrf_token() if frappe.session.user != "Guest" else ""
	context.nguoi_dung = frappe.session.user
	context.phien_ban = frappe.utils.get_build_version()
