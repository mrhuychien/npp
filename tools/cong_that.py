"""Cổng THẬT cho bài đầu-cuối của portal (P4 — M9, đặc tả kho_mua §6.9 V76–V79): chạy CHÍNH bộ xử lý `/rest/v1` của app
(`nppsale.portal.rest.xu_ly` → cổng bảng `nppsale.cong.api.truy_van` + RPC `nppsale.cong.api.rpc`) trên site thật, trong MỘT giao dịch KHÔNG BAO GIỜ
commit (lui khi tắt / khi gọi `POST /__lui`) — bài vitest `portal/tests/dau-cuoi-kho-mua.test.ts` gọi qua HTTP bằng client cổng của portal
(`@/lib/supabase/cong`) + mã màn của nppsale (lưu phiếu POS, bảng giá nhập, thẻ kho, lịch sử tồn, danh sách hoá đơn mua).

	cd /home/frappe/frappe-bench/sites && ../env/bin/python /home/frappe/frappe-bench/apps/nppsale/tools/cong_that.py --site poc.local --cong 8765
	cd portal && NPP_CONG_THAT=http://127.0.0.1:8765 npx vitest run tests/dau-cuoi-kho-mua.test.ts

Vì sao không phải trình duyệt thật + `bench serve`: không có Playwright / trình duyệt trong bộ công cụ (không thêm thư viện), và mọi lời ghi qua máy
chủ web thật bị COMMIT vào sổ dùng chung (dãy số PN / HĐ trôi — bài vàng so mã theo dãy, sự cố M0). Ở đây giao dịch giữ nguyên tới lúc lui, cùng các
chốt của bài site (commit / Error Log / xếp repost thành không làm gì).

Người gọi theo header `X-Npp-Nguoi` (CHU / QL / KT / TK / NV — người của bộ dữ liệu F: `nppsale.tests.test_kho_mua_vang.dung_nen_kho`, thiếu header
= CHU). `GET /__nen` → khoá nền {CHU: email, A: mã hàng, S1: tên NCC, org…}; `POST /__lui` → lui về nền sạch (mỗi bài một nền). Một luồng (frappe.local
theo luồng, một kết nối sổ).

`--nen bao_cao` (P6 M1 — đặc tả báo cáo VB-E02): bộ E2E + Sổ BC của bài vàng báo cáo (`nppsale.tests.test_bao_cao_vang.dung_cho_cong_that` — dựng qua
RPC dưới đúng người, đồng hồ ghim theo bước) thay bộ F; header là EMAIL người gọi (chu@e2e.vn, nv.an@sobc.vn… — hai bộ có hai Chủ), `GET /__nen` →
{org, E2E / S1: {nguoi, khach, hang, nhan}}; bài `portal/tests/dau-cuoi-bao-cao.test.ts`:

	cd /home/frappe/frappe-bench/sites && ../env/bin/python /home/frappe/frappe-bench/apps/nppsale/tools/cong_that.py --site poc.local --cong 8766 --nen bao_cao
	cd portal && NPP_CONG_THAT=http://127.0.0.1:8766 npx vitest run tests/dau-cuoi-bao-cao.test.ts
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

DIEM = "npp_dau_cuoi"


class _Args(dict):
	def get(self, k, d=None):
		v = super().get(k)
		return v[0] if isinstance(v, list) and v else d


class _Req:
	"""Đủ mặt `werkzeug.Request` mà `nppsale.portal.rest.xu_ly` + `nppsale.cong.api._phuong_thuc` đọc."""

	def __init__(self, method: str, path: str, query: str, body: bytes, headers):
		self.method = method
		self.path = path
		self.args = _Args(parse_qs(query))
		self._body = body
		self.headers = headers
		# mặt còn lại của werkzeug.Request mà lõi đọc lúc ghi chứng từ (get_url(), địa chỉ người gọi…)
		self.host = "127.0.0.1"
		self.scheme = "http"
		self.host_url = self.root_url = self.base_url = "http://127.0.0.1/"
		self.url = f"http://127.0.0.1{path}"
		self.full_path = path
		self.remote_addr = "127.0.0.1"
		self.environ = {}
		self.cookies = {}
		self.form = {}
		self.files = {}

	def get_data(self, as_text: bool = False):
		return self._body.decode("utf-8") if as_text else self._body


def chay(site: str, cong: int, nen_ten: str = "kho_mua") -> None:
	import frappe

	frappe.init(site=site, sites_path=".")
	frappe.connect()
	frappe.set_user("Administrator")
	# như môi trường của run-tests (bài vàng / bài site): cờ in_test (việc nền chạy ngay trong giao dịch, không đẩy hàng đợi Redis cho worker lạ), không
	# bao giờ commit — lui khi tắt
	frappe.flags.in_test = True
	frappe.db.commit = lambda *a, **k: None
	frappe.log_error = lambda title=None, message=None, **k: print("Error Log (không ghi):", title, file=sys.stderr)
	import nppsale.rpc.phieu_nhap as PN

	PN._xep_repost = lambda: None
	from nppsale.cong import bang as B
	from nppsale.portal.rest import xu_ly
	B.nap()
	if nen_ten == "bao_cao":
		# P6 M1 — bộ E2E + Sổ BC của bài vàng báo cáo: người theo header = EMAIL (hai bộ có hai Chủ)
		from nppsale.tests.test_bao_cao_vang import dung_cho_cong_that

		ma = dung_cho_cong_that()
		nguoi = {}
	else:
		from nppsale.tests.test_kho_mua_vang import VANG, dung_nen_kho

		with open(VANG, encoding="utf-8") as f:
			nen = json.load(f)["nen"]
		ma = dung_nen_kho(nen)
		nguoi = {k[2:]: v for k, v in ma.items() if k.startswith("u:")}
	frappe.db.savepoint(DIEM)

	class XuLy(BaseHTTPRequestHandler):
		def _tra(self, ma_http: int, than) -> None:
			du = json.dumps(than, ensure_ascii=False, default=str).encode("utf-8")
			self.send_response(ma_http)
			self.send_header("Content-Type", "application/json; charset=utf-8")
			self.send_header("Content-Length", str(len(du)))
			self.end_headers()
			self.wfile.write(du)

		def _mot(self, method: str) -> None:
			u = urlparse(self.path)
			body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if method == "POST" else b""
			if u.path == "/__nen":
				return self._tra(200, ma)
			if u.path == "/__lui":
				frappe.db.rollback(save_point=DIEM)
				frappe.db.savepoint(DIEM)
				return self._tra(200, {"ok": True})
			if not u.path.startswith("/rest/v1/"):
				return self._tra(404, {"error": {"message": "không có đường này", "code": "PGRST000"}})
			ai = self.headers.get("X-Npp-Nguoi") or "CHU"
			frappe.set_user(nguoi.get(ai, ai))
			frappe.local._npp_ngu_canh = None
			frappe.local._npp_cai_dat_ban = None
			frappe.local.request = _Req(method, u.path, u.query, body, self.headers)
			try:
				ma_http, than = xu_ly(u.path[len("/rest/v1/"):], frappe.local.request)
			except Exception as e:  # noqa: BLE001 — lỗi lạ: trả JSON 500 như portal/rest.py (sổ vẫn lui khi tắt)
				ma_http, than = 500, {"error": {"message": f"{type(e).__name__}: {e}", "code": "XX000", "details": None, "hint": None}}
			finally:
				frappe.set_user("Administrator")
				frappe.local._npp_ngu_canh = None
			return self._tra(ma_http, than)

		def do_GET(self):
			self._mot("GET")

		def do_POST(self):
			self._mot("POST")

		def log_message(self, *a):
			pass

	may = HTTPServer(("127.0.0.1", cong), XuLy)
	print(f"cổng thật nghe ở http://127.0.0.1:{cong} — site {site} (giao dịch không commit)", flush=True)
	try:
		may.serve_forever()
	except KeyboardInterrupt:
		pass
	finally:
		frappe.db.rollback()
		frappe.destroy()


if __name__ == "__main__":
	ap = argparse.ArgumentParser()
	ap.add_argument("--site", default="poc.local")
	ap.add_argument("--cong", type=int, default=8765)
	ap.add_argument("--nen", choices=("kho_mua", "bao_cao"), default="kho_mua",
		help="bộ dữ liệu: kho_mua (P4 — bộ F, mặc định) | bao_cao (P6 — bộ E2E + Sổ BC của bài vàng báo cáo)")
	a = ap.parse_args()
	os.chdir(os.environ.get("NPP_SITES", "/home/frappe/frappe-bench/sites"))
	chay(a.site, a.cong, a.nen)
