"""Cổng cho các route `/api/<đường>` cũ của nppsale (Next.js route handler) — trình duyệt gửi qua `caiApiCu`
(portal/src/khung/api-cu.ts) kèm đường dẫn + phương thức gốc trong header; ở đây tra bảng và gọi hàm xử lý Python.

Hàm xử lý nhận `YeuCauCu` và trả `(ma_http, than_json)` — đúng dạng route cũ trả, để mã React đọc `res.ok` / `res.status` /
`res.json()` như trước. Route chưa chuyển trả 501 kèm câu tiếng Việt (không im lặng).
"""
import json
import re
from dataclasses import dataclass, field

import frappe
from werkzeug.wrappers import Response

BANG = []  # [(phuong_thuc, regex, ham)]


@dataclass
class YeuCauCu:
	duong: str
	phuong_thuc: str
	tham: dict = field(default_factory=dict)  # tham số trong đường dẫn (nhóm có tên của regex)
	query: dict = field(default_factory=dict)
	than: object = None  # JSON đã giải, hoặc None

	def json(self):
		return self.than if isinstance(self.than, dict) else {}


def tuyen(phuong_thuc, mau):
	"""@tuyen("POST", r"^/api/admin/users/(?P<id>[^/]+)/password$")"""

	def boc(ham):
		BANG.append((phuong_thuc.upper(), re.compile(mau), ham))
		return ham

	return boc


_DA_NAP = False


def _nap():
	# Các mô-đun khai route bằng @tuyen — nhập ở đây để đăng ký (thêm dần theo giai đoạn).
	global _DA_NAP
	if _DA_NAP:
		return
	_DA_NAP = True
	import importlib

	for ten in ("nppsale.api.do_nap", "nppsale.api.loi_trinh_duyet", "nppsale.api.nguoi_dung", "nppsale.api.qr",
			"nppsale.api.anh"):
		try:
			importlib.import_module(ten)
		except ModuleNotFoundError:
			pass


def _tra(ma, than):
	if ma == 204 or than is None:
		return Response(status=ma)
	return Response(json.dumps(than, ensure_ascii=False, default=str), status=ma, mimetype="application/json")


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def goi():
	req = frappe.local.request
	duong_day_du = req.headers.get("X-Npp-Duong") or ""
	phuong_thuc = (req.headers.get("X-Npp-Phuong-Thuc") or req.method or "GET").upper()
	duong, _, chuoi_query = duong_day_du.partition("?")
	if not duong.startswith("/api/"):
		return _tra(400, {"error": "Thiếu đường dẫn API."})
	_nap()
	for pt, mau, ham in BANG:
		if pt != phuong_thuc:
			continue
		m = mau.match(duong)
		if not m:
			continue
		if frappe.session.user == "Guest" and not getattr(ham, "cho_khach", False):
			return _tra(401, {"error": "Chưa đăng nhập."})
		than = None
		if phuong_thuc not in ("GET", "HEAD"):
			du_lieu = req.get_data(as_text=True)
			if du_lieu:
				try:
					than = json.loads(du_lieu)
				except ValueError:
					than = du_lieu  # chữ thô (route cũ nhận cả chữ không phải JSON)
		from urllib.parse import parse_qs

		query = {k: v[-1] for k, v in parse_qs(chuoi_query).items()}
		ma, kq = ham(YeuCauCu(duong=duong, phuong_thuc=phuong_thuc, tham=m.groupdict(), query=query, than=than))
		return _tra(ma, kq)
	return _tra(501, {"error": f"Chức năng {phuong_thuc} {duong} chưa chuyển sang bản Frappe."})
