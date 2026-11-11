"""Phục vụ ảnh điểm bán ở đúng khuôn URL Supabase: /storage/v1/object/public/customer-photos/<org>/<khách>/<ô>-<ms>.jpg.
Phải là NV đang hoạt động và thấy được khách (vế customer_select) — bucket cũ là public, nay riêng tư (blueprint 02 §10 điểm 5)."""
from urllib.parse import unquote

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer

TIEN_TO = "/storage/v1/object/public/"


def _duong():
	try:
		return frappe.local.request.path or ""
	except Exception:
		return ""


class KhoAnh(BaseRenderer):
	def can_render(self):
		return _duong().startswith(TIEN_TO)

	def render(self):
		from nppsale.api.tep import BUCKET_ANH, tach_duong
		from nppsale.cong.bang.khach_hang import thay_khach
		from nppsale.cong.ngu_canh import hien_tai

		con = unquote(_duong()[len(TIEN_TO):])
		bucket, _, path = con.partition("/")
		nc = hien_tai()
		khach = tach_duong(path, frappe.db.get_single_value("NPP Cai Dat", "org_id")) if bucket == BUCKET_ANH else None
		if not nc.vai and not nc.bo_qua_rls:
			return self.build_response("", 401, {"Cache-Control": "no-store"})
		if not khach or not thay_khach(nc, khach):
			return self.build_response("", 404, {"Cache-Control": "no-store"})
		ten = frappe.db.get_value("File", {"npp_duong_dan": f"{bucket}/{path}"}, "name")
		if not ten:
			return self.build_response("", 404, {"Cache-Control": "no-store"})
		noi_dung = frappe.get_doc("File", ten).get_content()
		return self.build_response(noi_dung, 200, {
			"Content-Type": "image/jpeg",
			# Mỗi lần chụp một tên tệp mới (<ô>-<ms>.jpg) → giữ lâu được, nhưng chỉ trong trình duyệt của người xem
			"Cache-Control": "private, max-age=2592000, immutable",
			"X-Content-Type-Options": "nosniff",
		})
