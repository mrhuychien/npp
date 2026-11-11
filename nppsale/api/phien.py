"""Phiên đăng nhập cho portal: sau đăng nhập / đăng xuất / QR, trình duyệt lấy lại CSRF token + hồ sơ ở đây
(`lamMoiCsrf` trong portal/src/lib/supabase/cong/phien.ts)."""
import frappe

from nppsale.portal.vo import ngu_canh_trang


@frappe.whitelist(allow_guest=True, methods=["GET"])
def ngu_canh():
	return ngu_canh_trang()
