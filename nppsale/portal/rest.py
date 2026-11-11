"""Cổng dữ liệu của portal ở đường dẫn kiểu PostgREST: `/rest/v1/<bảng>` và `/rest/v1/rpc/<hàm>` (cùng gốc với trang).

Vì sao không dùng /api/method/…: lớp mạng của nppsale (`fetchCoHetGio`, `do-mang`, `thu-lai-giao-dich-hong`) nhận diện câu theo
ĐƯỜNG DẪN của Supabase — hàm báo cáo một lượt `/rest/v1/rpc/bao_cao_*` chờ 45 giây, nhật ký đo nạp ghi `/rest/v1/rpc/<hàm>`.
Giữ đúng đường dẫn thì giữ được các luật ấy mà không phải sửa mã nppsale.

	GET  /rest/v1/<bảng>?q=<yêu cầu JSON>        đọc (Frappe không commit GET — gửi lại an toàn)
	POST /rest/v1/<bảng>   thân = yêu cầu JSON    ghi; hoặc đọc dài (header X-Npp-Doc: 1)
	GET  /rest/v1/rpc/<hàm>?q=<tham số JSON>      hàm chỉ đọc (rpc(…, { get: true }))
	POST /rest/v1/rpc/<hàm> thân = tham số JSON   hàm có ghi

Trả JSON {data, count} hoặc {error: {message, code, details, hint}} với mã HTTP như PostgREST. Mọi lỗi đều trả JSON — không để
Frappe vẽ trang lỗi HTML cho câu dữ liệu.
"""
import json

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer

TIEN_TO = "/rest/v1/"


def _duong():
	try:
		return frappe.local.request.path or ""
	except Exception:
		return ""


class CongRest(BaseRenderer):
	def can_render(self):
		return _duong().startswith(TIEN_TO)

	def render(self):
		try:
			ma, than = xu_ly(_duong()[len(TIEN_TO):], frappe.local.request)
		except Exception:  # noqa: BLE001 — lỗi lạ: ghi nhật ký, trả JSON 500 (không lộ traceback)
			frappe.db.rollback()
			frappe.log_error(title="nppsale: cổng /rest/v1 lỗi")
			ma, than = 500, {"error": {"message": "Lỗi máy chủ khi xử lý dữ liệu.", "code": "XX000", "details": None, "hint": None}}
		return self.build_response(
			json.dumps(than, ensure_ascii=False, default=str),
			ma,
			{"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
		)


def _tham(req):
	if req.method == "GET":
		q = req.args.get("q")
		return json.loads(q) if q else {}
	du = req.get_data(as_text=True)
	return json.loads(du) if du else {}


def xu_ly(con, req):
	"""(mã HTTP, thân JSON) cho phần đường dẫn sau /rest/v1/."""
	from nppsale.cong import api

	try:
		tham = _tham(req)
	except ValueError:
		return 400, {"error": {"message": "Yêu cầu không phải JSON hợp lệ.", "code": "PGRST100", "details": None, "hint": None}}
	if con.startswith("rpc/"):
		ten = con[4:]
		try:
			sau = json.loads(req.args.get("sau") or "null")
		except ValueError:
			return 400, {"error": {"message": "Tham số sau không phải JSON.", "code": "PGRST100", "details": None, "hint": None}}
		kq = api.rpc(ten=ten, tham_so=tham if isinstance(tham, dict) else {}, sau=sau)
	else:
		yc = tham if isinstance(tham, dict) else {}
		if yc.get("bang") and yc["bang"] != con:
			return 400, {"error": {"message": "Bảng trên đường dẫn khác bảng trong yêu cầu.", "code": "PGRST100", "details": None, "hint": None}}
		yc["bang"] = con
		kq = api.truy_van(yeu_cau=yc)
	ma = int(kq.pop("status", 200) or 200)
	return ma, kq
