"""Lớp gọi MISA (nppsale.api.misa_mang) — đặc tả HĐĐT §3, §8.0 tầng 2, §8.1 Nhóm B (KV-13 header / thân / đường `code` của năm lời gọi,
KV-14 token) + ca lớp mạng của Nhóm K (KV-21 / KV-54 thử lại + H27 hỏi trước, KV-22 / KV-23 truyền tải, KV-55 che token) + bất biến I6 / I11.

Không gọi MISA thật: `_phien()` trả phiên gắn AdapterGia (`requests.adapters.BaseAdapter` — không có `responses` / `requests_mock`, không thêm
thư viện), hoặc máy chủ giả ở 127.0.0.1 (socket thô: thấy nguyên byte yêu cầu; lỗi truyền tải THẬT của requests / urllib3). Hình dạng lời gọi
[đo] bằng chính client.ts (bản chép `scratchpad/hddt/vang/lib`, fetch giả ghi phương thức / URL / header / thân); kết quả đọc phản hồi so
TỪNG ca với `du_lieu/hddt_mau.json` (sinh từ mã TS — tools/vang_hddt.mjs). Giá trị bí mật là chữ bịa (u-thu / p-thu / T1 …).

	bench --site poc.local run-tests --module nppsale.tests.test_misa_mang
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import parse_qsl

import frappe
import requests
import urllib3
from frappe.tests import IntegrationTestCase

from nppsale.api import misa_mang as M
from nppsale.luat import hddt as H
from nppsale.npp_hddt.doctype.npp_misa_cau_hinh import npp_misa_cau_hinh as CH
from nppsale.tests.test_luat_hddt import VANG

API = "https://misa.gia/api/v2"
MST = "0100000000"
MAC_DINH_REQUESTS = {"User-Agent", "Accept-Encoding", "Accept", "Connection", "Content-Length"}  # requests tự thêm — không phải header của app
TOK = {"body": {"access_token": "T1", "expires_in": 3600}}
TOK2 = {"body": {"access_token": "T2", "expires_in": 3600}}
HOA_DON = [{"RefID": "R", "AccountObjectName": "Tạp hoá A", "Quantity": 2}]
CAU_401 = {"status": 401, "body": {"message": "Token expired"}}
CAU_400_TOKEN = {"status": 400, "body": {"message": "InvalidInvoiceTemplate token mismatch"}}
DA_CO = {"InvNo": "<Chưa cấp số>", "PublishStatus": 0, "TotalAmount": 212600}  # KV-20 / KV-54: bản ghi MISA trả khi đã có tờ


class AdapterGia(requests.adapters.BaseAdapter):
	"""§8.0: ghi (phương thức, URL, header, thân) + hẹn giờ của từng lời; trả theo kịch bản — dict {status, body} hoặc ngoại lệ (ReadTimeout …)."""

	def __init__(self, kich_ban, khi_goi=None):
		super().__init__()
		self.kich_ban, self.goi, self.het_gio, self.khi_goi = list(kich_ban), [], [], khi_goi

	def send(self, request, **kw):
		self.goi.append((request.method, request.url, dict(request.headers), request.body))
		self.het_gio.append(kw.get("timeout"))
		if self.khi_goi:
			self.khi_goi(request)  # soi sổ / tua đồng hồ đúng lúc lời gọi bay đi
		b = self.kich_ban.pop(0)
		if isinstance(b, BaseException):
			raise b
		r = requests.models.Response()
		r.status_code, r.request, r.url = b.get("status", 200), request, request.url
		than = b.get("body", {})
		r._content = (than if isinstance(than, str) else json.dumps(than, ensure_ascii=False)).encode()
		return r

	def close(self):
		pass


_PHIEN_THAT = M._phien  # phiên THẬT của lớp mạng (lấy trước mọi patch) — adapter giả gắn vào chính phiên ấy, nên mọi bài đi qua cấu hình của nó


def phien_gia(a: AdapterGia) -> requests.Session:
	s = _PHIEN_THAT()
	s.mount("https://", a)
	s.mount("http://", a)
	return s


def cau_hinh(**kv) -> M.CauHinhMisa:
	return M.CauHinhMisa(**{"dia_chi_api": API, "mst": MST, "tai_khoan": "u-thu", "mat_khau": "p-thu", **kv})


def gon(a: AdapterGia) -> list:
	return [f"{m} {u[len(API):] if u.startswith(API) else u}" for m, u, _h, _b in a.goi]


def hd_app(h: dict) -> list:
	"""Header CỦA APP theo thứ tự gửi (bỏ bốn header mặc định của requests + Content-Length) — tên giữ đúng chữ hoa / thường."""
	return [(k, v) for k, v in h.items() if k not in MAC_DINH_REQUESTS]


class _NenMang(unittest.TestCase):
	"""Đồng hồ giả (`_dong_ho`), bộ nhớ token sạch, `_phien()` → phiên gắn AdapterGia."""

	def setUp(self):
		M.xoa_token_nho()
		self.addCleanup(M.xoa_token_nho)
		self.gio = 1000.0
		p = patch.object(M, "_dong_ho", lambda: self.gio)
		p.start()
		self.addCleanup(p.stop)

	def mang(self, *kich_ban, khi_goi=None) -> AdapterGia:
		a = AdapterGia(kich_ban, khi_goi)
		s = phien_gia(a)
		p = patch.object(M, "_phien", lambda: s)
		p.start()
		self.addCleanup(p.stop)
		return a

	def nap_token(self, ch, token="T1"):
		"""Token đã nằm trong RAM (route phát hành lấy ở bước 8, trước khi giành tờ)."""
		a = self.mang({"body": {"access_token": token, "expires_in": 3600}})
		self.assertEqual(M.lay_token(ch), token)
		return a


# =====================================================================================================================================
# KV-13 / KV-14 — token
# =====================================================================================================================================

class TestToken(_NenMang):
	def test_kv13_hinh_dang(self):
		"""POST {api}/oauth, header ĐÚNG hai khoá `Content-Type: text/plain` + `taxcode` (chữ thường, một lần), thân là CHUỖI form [đo client.ts]."""
		a = self.mang(TOK)
		self.assertEqual(M.lay_token(cau_hinh()), "T1")
		((pt, url, h, than),) = a.goi
		self.assertEqual((pt, url), ("POST", API + "/oauth"))
		self.assertEqual(hd_app(h), [("Content-Type", "text/plain"), ("taxcode", MST)])
		self.assertNotIn("TaxCode", h)
		self.assertNotIn("Authorization", h)
		self.assertEqual(than, b"grant_type=password&username=u-thu&password=p-thu")  # = URLSearchParams của TS [đo]
		self.assertEqual(a.het_gio, [(5, 15)])

	def test_kv13_form_ky_tu_dac_biet(self):
		"""urlencode để nguyên `~`, mã `*` — URLSearchParams ngược lại; cùng nghĩa sau giải mã (§3.2) [đo thân TS]."""
		a = self.mang(TOK)
		M.lay_token(cau_hinh(tai_khoan="u ~*'()!@&=+", mat_khau="p ~*%"))
		ts = "grant_type=password&username=u+%7E*%27%28%29%21%40%26%3D%2B&password=p+%7E*%25"
		self.assertEqual(parse_qsl(a.goi[0][3].decode()), parse_qsl(ts))
		self.assertEqual(parse_qsl(ts), [("grant_type", "password"), ("username", "u ~*'()!@&=+"), ("password", "p ~*%")])

	def test_get_password_rong_khong_gui_chu_none(self):
		"""[Soát thiếu 2] tài khoản / mật khẩu trống là '' (nppsale `decryptSecret(null)` = '') — `urlencode` của None gửi chữ "None"."""
		a = self.mang(TOK)
		M.lay_token(cau_hinh(tai_khoan="", mat_khau=""))
		self.assertEqual(a.goi[0][3], b"grant_type=password&username=&password=")

	def test_kv14_nho_ram(self):
		"""Hai lời liền cùng khoá → một /oauth; khoá = api | mst | tài khoản; `ep` bỏ qua bản nhớ; lỗi không nhớ."""
		a = self.mang(TOK, {"body": {"access_token": "T-khac"}}, {"body": {"access_token": "T-ep"}})
		self.assertEqual([M.lay_token(cau_hinh()), M.lay_token(cau_hinh())], ["T1", "T1"])
		self.assertEqual(M.lay_token(cau_hinh(tai_khoan="u-khac")), "T-khac")
		self.assertEqual(M.lay_token(cau_hinh(), ep=True), "T-ep")
		self.assertEqual(M.lay_token(cau_hinh()), "T-ep")  # bản ép thay bản nhớ (client.ts:369)
		self.assertEqual(len(a.goi), 3)
		loi = {"body": {"error": "invalid_grant", "error_description": "Sai tài khoản hoặc mật khẩu", "status": 401}}
		a = self.mang(loi, loi)
		for _ in range(2):
			with self.assertRaises(M.MisaLoi) as e:
				M.lay_token(cau_hinh(tai_khoan="u-sai"))
			self.assertEqual(str(e.exception), "MISA token lỗi 401: Sai tài khoản hoặc mật khẩu (invalid_grant)")
			self.assertFalse(e.exception.chua_biet)
		self.assertEqual(len(a.goi), 2)  # lần sau VẪN gọi lại

	def test_kv14_han_token(self):
		"""Sống min(expires_in, 30 phút) − 60 s; `expires_in` không phải số > 0 → 30 phút [đo: expires_in 120 → giữ 59 s, gọi lại ở 61 s]."""
		for het, song in ((120, 60), (None, 1740), (7200, 1740), (0, 1740), (-5, 1740), ("3600", 1740), (True, 1740), (90.5, 30.5)):
			with self.subTest(expires_in=het):
				M.xoa_token_nho()
				than = {"access_token": "A"} if het is None else {"access_token": "A", "expires_in": het}
				a = self.mang({"body": than}, {"body": {"access_token": "B"}})
				ch = cau_hinh()
				self.gio = 5000.0
				M.lay_token(ch)
				self.gio = 5000.0 + song - 0.5
				self.assertEqual(M.lay_token(ch), "A")
				self.gio = 5000.0 + song + 0.5
				self.assertEqual(M.lay_token(ch), "B")
				self.assertEqual(len(a.goi), 2)

	def test_kv14_thieu_duong_token(self):
		"""`token_path` rỗng → câu nguyên văn, KHÔNG gọi mạng — xét trước bản nhớ như TS; có khoảng trắng hai đầu thì cắt."""
		self.nap_token(cau_hinh())
		a = self.mang()
		for duong in ("", "   ", None):
			with self.subTest(duong=duong), self.assertRaises(M.MisaLoi) as e:
				M.lay_token(cau_hinh(duong_token=duong))
			self.assertEqual(str(e.exception), "Chưa cấu hình 'Endpoint lấy token' (token_path) cho MISA. Vào Cài đặt → Hoá đơn điện tử.")
		self.assertEqual(a.goi, [])
		a = self.mang(TOK)
		M.lay_token(cau_hinh(tai_khoan="u-cat", duong_token="  /oauth  "))
		self.assertEqual(a.goi[0][1], API + "/oauth")

	def test_kv14_tra_tho_mot_loi(self):
		"""Thử kết nối: token + thân /oauth từ CÙNG một lời (nppsale gọi hai lần [≠ nhỏ]); `tach_dinh_danh` ra đúng KV-14; token vẫn được nhớ."""
		than = {"access_token": "T9", "expires_in": 3600,
			"Data": '{"CompanyID":156217,"OrganizationUnitID":"ou","UserID":"us","IsInvoiceWithCode":"True"}'}
		self.nap_token(cau_hinh(), "T-cu")
		a = self.mang({"body": than})
		token, tho = M.lay_token(cau_hinh(), ep=True, tra_tho=True)
		self.assertEqual((token, tho), ("T9", than))
		self.assertEqual(len(a.goi), 1)
		self.assertEqual(H.tach_dinh_danh(tho), {"companyId": "156217", "orgUnitId": "ou", "userId": "us", "isInvoiceWithCode": True})
		self.assertEqual(M.lay_token(cau_hinh()), "T9")
		a = self.mang({"body": "<html>"})
		with self.assertRaises(M.MisaLoi):
			M.lay_token(cau_hinh(), tra_tho=True)

	def test_token_vang(self):
		"""Mọi ca `doc_phan_hoi_token` của tệp vàng đi trọn qua lớp mạng: câu lỗi / token / thân thô y như số TS (đã khai lệch H25, thân null)."""
		for ca in VANG["doc_phan_hoi_token"]:
			v, m = ca["vao"], ca["mong"]
			with self.subTest(ten=ca["ten"]):
				M.xoa_token_nho()
				self.mang({"status": v["status"], "body": v["text"]})
				if m["loi"]:
					with self.assertRaises(M.MisaLoi) as e:
						M.lay_token(cau_hinh(), ep=True)
					self.assertEqual(str(e.exception), m["loi"])
				elif "tho" in m:
					self.assertEqual(M.lay_token(cau_hinh(), tra_tho=True), (m["token"], m["tho"]))
				else:
					self.assertEqual(M.lay_token(cau_hinh(), ep=True), m["token"])

	def test_kv55_khong_lo_token(self):
		"""[ĐX H25] `/oauth` trả token dưới khoá lạ → câu lỗi che giá trị (nppsale mang nguyên TOKEN-GIA-123 vào misa_error / nhật ký)."""
		self.mang({"body": '{"Data":{"AccessToken":"TOKEN-GIA-123"},"expires_in":3600}'})
		with self.assertRaises(M.MisaLoi) as e:
			M.lay_token(cau_hinh())
		self.assertEqual(str(e.exception),
			'MISA token: không thấy access_token trong response. Raw: {"Data":{"AccessToken":"***"},"expires_in":3600}')
		self.assertNotIn("TOKEN-GIA-123", str(e.exception))

	def test_bom_dau_than(self):
		"""Thân giải mã như `res.text()` của fetch: bỏ BOM UTF-8 đầu (JSON.parse không nhận BOM)."""
		self.mang({"body": '﻿{"access_token":"T-bom"}'})
		self.assertEqual(M.lay_token(cau_hinh()), "T-bom")


# =====================================================================================================================================
# KV-13 / KV-21 / KV-54 — đẩy, thử lại một lần, H27 hỏi trước
# =====================================================================================================================================

class TestDay(_NenMang):
	def test_kv13_hinh_dang(self):
		"""Header `Content-Type: application/json`, `Authorization: Bearer T1`, `TaxCode` (PascalCase, một lần); thân = JSON.stringify MẢNG, byte
		UTF-8 (không \\u…) [đo]; hẹn giờ (5, 30)."""
		a = self.mang(TOK, {"body": {"success": True, "TransactionID": "TXABC", "InvNo": "00000123"}})
		kq = M.day_hd(cau_hinh(), HOA_DON)
		self.assertEqual(gon(a), ["POST /oauth", "POST /v3sainvoice"])
		_pt, _url, h, than = a.goi[1]
		self.assertEqual(hd_app(h), [("Content-Type", "application/json"), ("Authorization", "Bearer T1"), ("TaxCode", MST)])
		self.assertNotIn("taxcode", {k for k in h if k != "TaxCode"})
		self.assertEqual(than, '[{"RefID":"R","AccountObjectName":"Tạp hoá A","Quantity":2}]'.encode())  # = thân TS [đo]
		self.assertEqual(a.het_gio, [(5, 15), (5, 30)])
		self.assertEqual(kq, {"ok": True, "raw": {"success": True, "TransactionID": "TXABC", "InvNo": "00000123"}, "error": None,
			"lookup_code": "TXABC", "inv_no": "00000123", "ref_id": None, "chua_biet": False, "da_co": None})

	def test_netrc_khong_de_header(self):
		"""`~/.netrc` (trust_env của requests — giữ cho proxy / CA) có dòng cho máy MISA thì requests tự thêm Basic auth ĐÈ `Authorization:
		Bearer` và thêm header thứ ba cho /oauth — phiên của lớp mạng đặt xác thực rỗng để requests bỏ qua netrc."""
		with tempfile.NamedTemporaryFile("w", suffix=".netrc", delete=False) as f:
			f.write("machine misa.gia login netrc-user password netrc-pass\n")
		self.addCleanup(os.unlink, f.name)
		self.assertEqual(requests.utils.get_netrc_auth(API + "/oauth"), None)  # chưa đặt NETRC: bài không dựa vào netrc của máy
		with patch.dict(os.environ, {"NETRC": f.name}):
			self.assertEqual(requests.utils.get_netrc_auth(API + "/oauth"), ("netrc-user", "netrc-pass"))  # requests THẤY netrc …
			a = self.mang(TOK, {"body": {"success": True, "RefID": "R"}})
			self.assertTrue(M.day_hd(cau_hinh(), HOA_DON)["ok"])
		self.assertEqual(hd_app(a.goi[0][2]), [("Content-Type", "text/plain"), ("taxcode", MST)])  # … mà không dùng
		self.assertEqual(dict(a.goi[1][2])["Authorization"], "Bearer T1")

	def test_duong_day_va_mst_rong(self):
		"""Đường đẩy theo cấu hình (có mã: /v3sainvoice/Code — C HOA); `TaxCode: ""` khi thiếu MST (`cfg.taxCode || ""`)."""
		a = self.mang(TOK, {"body": {"success": True, "RefID": "R"}})
		M.day_hd(cau_hinh(duong_day="/v3sainvoice/Code", mst="", co_ma=True), HOA_DON)
		self.assertEqual(gon(a)[1], "POST /v3sainvoice/Code")
		self.assertEqual(dict(hd_app(a.goi[1][2]))["TaxCode"], "")

	def test_thieu_duong_day(self):
		a = self.mang()
		for duong in ("", "  ", None):
			with self.subTest(duong=duong):
				self.assertEqual(M.day_hd(cau_hinh(duong_day=duong), HOA_DON), {"ok": False, "raw": None, "lookup_code": None,
					"inv_no": None, "ref_id": None, "chua_biet": False, "da_co": None,
					"error": "Chưa cấu hình 'Endpoint phát hành' (publish_path) cho MISA. Vào Cài đặt → Hoá đơn điện tử."})
		self.assertEqual(a.goi, [])

	def test_vang_hieu_phan_hoi_va_thu_lai(self):
		"""Mọi ca `hieu_phan_hoi_day` của tệp vàng đi trọn qua lớp mạng: kết quả y số TS, và số lần POST = 2 đúng khi TS thử lại (`thu_lai`)."""
		for ca in VANG["hieu_phan_hoi_day"]:
			v = ca["vao"]
			with self.subTest(ten=ca["ten"]):
				M.xoa_token_nho()
				tl = {"status": v["status"], "body": v["text"]}
				a = self.mang(TOK, tl, TOK2, tl)
				kq = M.day_hd(cau_hinh(), [{"RefID": "rid-1"}])
				self.assertEqual({k: kq[k] for k in ca["mong"]}, ca["mong"])
				self.assertEqual(kq["chua_biet"], False)
				self.assertEqual(sum(1 for g in gon(a) if g == "POST /v3sainvoice"), 2 if ca["thu_lai"] else 1)

	def test_kv21_401_thu_lai_mot_lan(self):
		"""Token T1 đã nhớ; POST → 401 → /oauth ÉP → T2 → POST lại NGUYÊN thân (`Bearer T2`) → OK. Không có hỏi trước: thứ tự [=] nppsale."""
		self.nap_token(cau_hinh())
		a = self.mang(CAU_401, TOK2, {"body": {"success": True, "RefID": "R"}})
		kq = M.day_hd(cau_hinh(), HOA_DON)
		self.assertEqual(gon(a), ["POST /v3sainvoice", "POST /oauth", "POST /v3sainvoice"])
		self.assertEqual([dict(g[2])["Authorization"] for g in (a.goi[0], a.goi[2])], ["Bearer T1", "Bearer T2"])
		self.assertEqual(a.goi[0][3], a.goi[2][3])
		self.assertTrue(kq["ok"])

	def test_kv21_401_thu_lai_khong_lan_hai(self):
		"""Thử lại MỘT lần: POST lần 2 vẫn 401 → trả lỗi, không lần 3."""
		self.nap_token(cau_hinh())
		a = self.mang(CAU_401, TOK2, CAU_401, TOK2, {"body": {"success": True}})
		kq = M.day_hd(cau_hinh(), HOA_DON)
		self.assertEqual(gon(a), ["POST /v3sainvoice", "POST /oauth", "POST /v3sainvoice"])
		self.assertEqual(kq["error"], "MISA publish lỗi 401: Token expired")

	def test_kv21_h27_hoi_truoc_roi_post(self):
		"""[Soát thiếu 2 — H27] thứ tự POST, oauth, GET ?refID=R (data null), POST; `Bearer T2` cho cả GET lẫn POST."""
		ch = cau_hinh()
		self.nap_token(ch)
		a = self.mang(CAU_401, TOK2, {"body": {"success": True, "data": None}}, {"body": {"success": True, "RefID": "R"}})
		kq = M.day_hd(ch, HOA_DON, lambda: M.lay_hd(ch, "R"))
		self.assertEqual(gon(a), ["POST /v3sainvoice", "POST /oauth", "GET /v3sainvoice/?refID=R", "POST /v3sainvoice"])
		self.assertEqual([dict(g[2])["Authorization"] for g in a.goi[2:]], ["Bearer T2", "Bearer T2"])
		self.assertTrue(kq["ok"])

	def test_kv54_400_token_mismatch(self):
		"""KV-54: 400 có chữ "token" cũng là lỗi xác thực (looksLikeAuthError) — POST, oauth (ép), GET (null), POST → 502 câu lần 2."""
		ch = cau_hinh()
		a = self.mang(TOK, CAU_400_TOKEN, TOK2, {"body": {"success": True, "data": None}}, CAU_400_TOKEN)
		kq = M.day_hd(ch, [{"RefID": "R"}], lambda: M.lay_hd(ch, "R"))
		self.assertEqual(gon(a), ["POST /oauth", "POST /v3sainvoice", "POST /oauth", "GET /v3sainvoice/?refID=R", "POST /v3sainvoice"])
		self.assertEqual((kq["ok"], kq["error"], kq["da_co"]), (False, "MISA publish lỗi 400: InvalidInvoiceTemplate token mismatch", None))

	def test_kv54_misa_da_co_khong_post_lan_hai(self):
		"""H27 + I11: GET thấy RefID trên MISA → KHÔNG POST lần 2; trả kết quả lần 1 + `da_co` = bản ghi (route xử lý như đẩy lại thấy trên MISA).
		`{}` (JSON không phải object mà JS coi là có) cũng là "có"."""
		for ten, than_get, da_co in (("bản ghi", {"success": True, "data": json.dumps(DA_CO)}, DA_CO),
				("data '[1]' → {}", {"success": True, "data": "[1]"}, {})):
			with self.subTest(ten=ten):
				M.xoa_token_nho()
				ch = cau_hinh()
				a = self.mang(TOK, CAU_400_TOKEN, TOK2, {"body": than_get})
				kq = M.day_hd(ch, [{"RefID": "R"}], lambda: M.lay_hd(ch, "R"))
				self.assertEqual(gon(a), ["POST /oauth", "POST /v3sainvoice", "POST /oauth", "GET /v3sainvoice/?refID=R"])
				self.assertEqual(kq["da_co"], da_co)
				self.assertEqual((kq["ok"], kq["error"]), (False, "MISA publish lỗi 400: InvalidInvoiceTemplate token mismatch"))
				self.assertEqual(a.kich_ban, [])

	def test_kv54_hoi_truoc_hong(self):
		"""GET trước khi thử lại ném (MISA lỗi / mạng) → coi như lần 1 lỗi rõ: KHÔNG POST lần 2, câu của lần 1."""
		for ten, b in (("GET 500", {"status": 500, "body": "boom"}), ("GET hết giờ nối", requests.exceptions.ConnectTimeout("x"))):
			with self.subTest(ten=ten):
				M.xoa_token_nho()
				ch = cau_hinh()
				a = self.mang(TOK, CAU_400_TOKEN, TOK2, b)
				kq = M.day_hd(ch, [{"RefID": "R"}], lambda: M.lay_hd(ch, "R"))
				self.assertEqual(gon(a)[-1], "GET /v3sainvoice/?refID=R")
				self.assertEqual((kq["ok"], kq["error"], kq["da_co"], kq["chua_biet"]),
					(False, "MISA publish lỗi 400: InvalidInvoiceTemplate token mismatch", None, False))

	def test_loi_khong_xac_thuc_khong_thu_lai(self):
		"""500 / 400 không có token / expired / unauthorized → không thử lại (một POST)."""
		a = self.mang(TOK, {"status": 500, "body": "<html>Bad gateway</html>"})
		kq = M.day_hd(cau_hinh(), HOA_DON, lambda: self.fail("không được hỏi trước"))
		self.assertEqual(gon(a), ["POST /oauth", "POST /v3sainvoice"])
		self.assertEqual((kq["error"], kq["raw"]), ("MISA publish lỗi 500: <html>Bad gateway</html>", {"raw": "<html>Bad gateway</html>"}))

	def test_2xx_co_chu_token_khong_thu_lai(self):
		"""Thử lại CHỈ khi HTTP lỗi (`!res.ok && looksLikeAuthError` — client.ts:486): 2xx mà thân có chữ token / unauthorized (vd 200
		`{"Success":false,"ErrorCode":"InvalidToken"}`) → MỘT POST — gửi lại là đẻ nháp thứ hai cho tờ MISA đã nhận."""
		for tl, mong in (
				({"body": {"Success": False, "ErrorCode": "InvalidToken"}}, "MISA publish thất bại: InvalidToken"),
				({"body": {"success": True, "TransactionID": "TXT", "AccessToken": "x"}}, None),
				({"status": 201, "body": {"success": True, "RefID": "R", "msg": "unauthorized retry not needed"}}, None)):
			with self.subTest(tl=tl):
				M.xoa_token_nho()
				a = self.mang(TOK, tl, TOK2, {"body": {"success": True, "RefID": "R"}})
				kq = M.day_hd(cau_hinh(), HOA_DON, lambda: self.fail("không được hỏi trước"))
				self.assertEqual(gon(a), ["POST /oauth", "POST /v3sainvoice"])
				self.assertEqual(kq["error"], mong)

	def test_token_ep_hong(self):
		"""Token ép hỏng ở lần thử lại → câu token (nppsale: ném ra khỏi publishInvoice), không POST lần 2."""
		self.nap_token(cau_hinh())
		a = self.mang(CAU_401, {"body": {"error": "invalid_grant", "error_description": "Sai tài khoản hoặc mật khẩu", "status": 401}})
		kq = M.day_hd(cau_hinh(), HOA_DON)
		self.assertEqual(gon(a), ["POST /v3sainvoice", "POST /oauth"])
		self.assertEqual((kq["ok"], kq["error"], kq["chua_biet"]), (False, "MISA token lỗi 401: Sai tài khoản hoặc mật khẩu (invalid_grant)",
			False))

	def test_token_hong_truoc_khi_day(self):
		"""Token hỏng ngay đầu (RAM trống) → lỗi = câu token, không POST /v3sainvoice."""
		a = self.mang({"status": 500, "body": "x"})
		kq = M.day_hd(cau_hinh(), HOA_DON)
		self.assertEqual(gon(a), ["POST /oauth"])
		self.assertEqual((kq["ok"], kq["error"]), (False, "MISA token lỗi 500: x"))

	def test_qua_60s_khong_thu_lai(self):
		"""§3.1: đã quá 60 s kể từ lúc bắt đầu đẩy thì không thử lại (giữ tổng < 120 s của gunicorn); đúng 60 s vẫn thử. `bat_dau` của route."""
		for tre, mong in ((61, ["POST /v3sainvoice"]), (60, ["POST /v3sainvoice", "POST /oauth", "POST /v3sainvoice"])):
			with self.subTest(tre=tre):
				M.xoa_token_nho()
				self.nap_token(cau_hinh())

				def cham(req, tre=tre):
					if req.url.endswith("/v3sainvoice"):
						self.gio += tre

				a = self.mang(CAU_401, TOK2, {"body": {"success": True, "RefID": "R"}}, khi_goi=cham)
				self.gio = 2000.0
				M.day_hd(cau_hinh(), HOA_DON)
				self.assertEqual(gon(a)[:3], mong)
		M.xoa_token_nho()
		self.nap_token(cau_hinh())
		a = self.mang(CAU_401, TOK2, {"body": {"success": True}})
		M.day_hd(cau_hinh(), HOA_DON, bat_dau=self.gio - 61)
		self.assertEqual(gon(a), ["POST /v3sainvoice"])

	def test_tran_tong_cua_chuoi_day(self):
		"""[ĐX] chuỗi thử lại (token ép + GET của H27 + POST lần 2) bị cắt hẹn ĐỌC cho vừa HAN_DAY_S (110 s) kể từ `bat_dau` — đặc tả chỉ tính
		token + đẩy (55 s); thêm GET là quá 120 s. Ngoài day_hd không cắt."""
		ch = cau_hinh()
		self.gio = 3000.0
		self.nap_token(ch)

		def moi_loi_15s(_req):
			self.gio += 15

		a = self.mang(CAU_401, TOK2, {"body": {"success": True, "data": None}}, {"body": {"success": True, "RefID": "R"}}, khi_goi=moi_loi_15s)
		M.day_hd(ch, HOA_DON, lambda: M.lay_hd(ch, "R"), bat_dau=self.gio - 45)
		# bắt đầu ở 45 s: POST1 (5, 30) → 60 s (≤ 60: còn thử lại); token (5, 15) → 75 s; GET (5, min(15, 110−75−5)) → 90 s;
		# POST2 (5, min(30, 110−90−5 = 15))
		self.assertEqual(a.het_gio, [(5, 30), (5, 15), (5, 15), (5, 15)])

		def token_cham(req):
			self.gio += 40 if req.url.endswith("/oauth") else (10 if "refID" in req.url else 0)

		a = self.mang(CAU_401, TOK2, {"body": {"success": True, "data": None}}, {"body": {"success": True, "RefID": "R"}}, khi_goi=token_cham)
		M.day_hd(ch, HOA_DON, lambda: M.lay_hd(ch, "R"), bat_dau=self.gio - 60)
		# 60 s: POST1 (5, 30); token ép +40 → 100 s; GET (5, 110−100−5 = 5) +10 → 110 s; POST2 hết ngân sách → sàn (5, 1)
		self.assertEqual(a.het_gio, [(5, 30), (5, 15), (5, 5), (5, 1)])
		a = self.mang({"body": {"success": True, "data": None}})
		self.assertIsNone(M.lay_hd(ch, "R"))
		self.assertEqual(a.het_gio, [(5, 15)])

	def test_kv23_kv22_truyen_tai(self):
		"""Lời ĐẨY: không nối được / sai địa chỉ / TLS = CHƯA GỬI (route đặt error); hết giờ đọc / đứt giữa chừng = CHƯA BIẾT (`chua_biet`, route
		giữ pending). Câu nguyên văn §3.1 / Phụ lục A."""
		chua_biet = M.CAU_CHUA_BIET
		self.assertEqual(chua_biet, "Không nhận được trả lời của MISA (hết giờ / rớt mạng) — chưa biết MISA đã nhận hoá đơn chưa. ĐỪNG đẩy lại: "
			"bấm 'Làm mới trạng thái từ MISA' sau ít phút.")
		ket_noi = urllib3.exceptions.MaxRetryError(None, "/x", urllib3.exceptions.NewConnectionError(None, "refused"))
		phan_giai = urllib3.exceptions.MaxRetryError(None, "/x", urllib3.exceptions.NameResolutionError("misa.gia", None, OSError("dns")))
		for loi, cau, cb in (
				(requests.exceptions.ConnectTimeout("x"), "Không kết nối được tới MISA (ConnectTimeout) — hoá đơn chưa được gửi.", False),
				(requests.exceptions.ConnectionError(ket_noi), "Không kết nối được tới MISA (NewConnectionError) — hoá đơn chưa được gửi.", False),
				(requests.exceptions.ConnectionError(phan_giai), "Không kết nối được tới MISA (NameResolutionError) — hoá đơn chưa được gửi.",
					False),
				(requests.exceptions.SSLError(urllib3.exceptions.MaxRetryError(None, "/x", urllib3.exceptions.SSLError("cert"))),
					"Không kết nối được tới MISA (SSLError) — hoá đơn chưa được gửi.", False),
				(requests.exceptions.ProxyError("p"), "Không kết nối được tới MISA (ProxyError) — hoá đơn chưa được gửi.", False),
				(requests.exceptions.ReadTimeout("x"), chua_biet, True),
				(requests.exceptions.ConnectionError(urllib3.exceptions.ProtocolError("Connection aborted.")), chua_biet, True),
				(requests.exceptions.ChunkedEncodingError("x"), chua_biet, True),
				(requests.exceptions.TooManyRedirects("x"), chua_biet, True),
				(urllib3.exceptions.DecodeError("x"), chua_biet, True)):
			with self.subTest(loi=type(loi).__name__, cau=cau):
				M.xoa_token_nho()
				self.mang(TOK, loi)
				self.assertEqual(M.day_hd(cau_hinh(), HOA_DON), {"ok": False, "raw": None, "error": cau, "lookup_code": None, "inv_no": None,
					"ref_id": None, "chua_biet": cb, "da_co": None})

	def test_truyen_tai_post_lan_hai(self):
		"""Hết giờ ở POST lần 2 vẫn là "chưa biết"; nối hỏng ở lần 2 là chưa gửi."""
		for loi, cb in ((requests.exceptions.ReadTimeout("x"), True), (requests.exceptions.ConnectTimeout("x"), False)):
			with self.subTest(loi=type(loi).__name__):
				M.xoa_token_nho()
				self.nap_token(cau_hinh())
				a = self.mang(CAU_401, TOK2, loi)
				kq = M.day_hd(cau_hinh(), HOA_DON)
				self.assertEqual(gon(a), ["POST /v3sainvoice", "POST /oauth", "POST /v3sainvoice"])
				self.assertEqual(kq["chua_biet"], cb)

	def test_che_bi_mat_doi_lai(self):
		"""[ĐX — I6] MISA dội lại tài khoản / mật khẩu / token đang dùng → `***` ở `error` lẫn `raw` (nhật ký `nhan_ve`). (Thân không có chữ
		token / expired / unauthorized — không thì thành lỗi xác thực, thử lại.)"""
		a = self.mang({"body": {"access_token": "JWT-BIMAT-9"}},
			{"status": 500, "body": {"errorMessage": "User u-thu-BIMAT / p-thu-BIMAT bị khoá (phiên JWT-BIMAT-9)"}})
		kq = M.day_hd(cau_hinh(tai_khoan="u-thu-BIMAT", mat_khau="p-thu-BIMAT"), HOA_DON)
		self.assertEqual(gon(a), ["POST /oauth", "POST /v3sainvoice"])
		self.assertEqual(kq["error"], "MISA publish lỗi 500: User *** / *** bị khoá (phiên ***)")
		self.assertEqual(kq["raw"], {"errorMessage": "User *** / *** bị khoá (phiên ***)"})
		self.mang(CAU_401, {"body": {"access_token": "JWT-BIMAT-2"}},
			{"status": 403, "body": {"message": "Phiên JWT-BIMAT-9 / JWT-BIMAT-2 bị chặn"}})
		kq = M.day_hd(cau_hinh(tai_khoan="u-thu-BIMAT", mat_khau="p-thu-BIMAT"), HOA_DON)
		self.assertEqual(kq["error"], "MISA publish lỗi 403: Phiên *** / *** bị chặn")  # che cả token lần 1 lẫn token ép


# =====================================================================================================================================
# KV-13 — một HĐ, danh sách, mẫu
# =====================================================================================================================================

class TestDoc(_NenMang):
	def test_kv13_lay_hd(self):
		"""Có mã: GET …/v3sainvoice/code/?refID=; không mã: …/v3sainvoice/?refID= (encodeURIComponent [đo]); header Authorization, TaxCode,
		Content-Type: application/json; không thân; hẹn (5, 15)."""
		for co_ma, ref, duong in ((True, "rid-1", "/v3sainvoice/code/?refID=rid-1"),
				(False, "rid-1", "/v3sainvoice/?refID=rid-1"),
				(False, "a b/c?d&e=f~*'()!é", "/v3sainvoice/?refID=a%20b%2Fc%3Fd%26e%3Df~*'()!%C3%A9")):
			with self.subTest(co_ma=co_ma, ref=ref):
				M.xoa_token_nho()
				a = self.mang(TOK, {"body": {"success": True, "data": json.dumps({"InvNo": "00000123", "PublishStatus": 3})}})
				self.assertEqual(M.lay_hd(cau_hinh(co_ma=co_ma), ref), {"InvNo": "00000123", "PublishStatus": 3})
				self.assertEqual(gon(a), ["POST /oauth", "GET " + duong])
				_pt, _url, h, than = a.goi[1]
				self.assertEqual(hd_app(h), [("Authorization", "Bearer T1"), ("TaxCode", MST), ("Content-Type", "application/json")])
				self.assertIsNone(than)
				self.assertEqual(a.het_gio[1], (5, 15))

	def test_kv13_lay_hd_loi_va_rong(self):
		"""401 → 'Lấy HD lỗi 401: Unauthorized', KHÔNG lấy token mới [=]; Success false → 'Lấy HD thất bại: NotFound'; data null → None."""
		self.nap_token(cau_hinh())
		a = self.mang({"status": 401, "body": {"message": "Unauthorized"}}, {"body": {"Success": False, "ErrorCode": "NotFound"}},
			{"body": {"success": True, "data": None}})
		for cau in ("Lấy HD lỗi 401: Unauthorized", "Lấy HD thất bại: NotFound"):
			with self.assertRaises(M.MisaLoi) as e:
				M.lay_hd(cau_hinh(), "rid-x")
			self.assertEqual(str(e.exception), cau)
		self.assertIsNone(M.lay_hd(cau_hinh(), "rid-x"))
		self.assertEqual(gon(a), ["GET /v3sainvoice/?refID=rid-x"] * 3)

	def test_lay_hd_vang(self):
		for ca in VANG["doc_phan_hoi_lay_hd"]:
			v, m = ca["vao"], ca["mong"]
			with self.subTest(ten=ca["ten"]):
				M.xoa_token_nho()
				self.mang(TOK, {"status": v["status"], "body": v["text"]})
				if m["loi"]:
					with self.assertRaises(M.MisaLoi) as e:
						M.lay_hd(cau_hinh(), "rid-1")
					self.assertEqual(str(e.exception), m["loi"])
				else:
					self.assertEqual(M.lay_hd(cau_hinh(), "rid-1"), m["ban_ghi"])

	def test_kv13_ds_hd(self):
		"""Có mã: POST {api}/code/v3sainvoice/paging; form start, length, fromDate / toDate TRẦN (không nháy kép) [đo]; recordsTotal 0 + 2 dòng →
		2 dòng; Data không JSON + RecordsTotal 5 → 0 dòng, 5, không ném; hẹn (5, 60)."""
		a = self.mang(TOK, {"body": {"success": True, "recordsTotal": 0, "data": json.dumps([{"RefID": "a"}, {"RefID": "b"}])}},
			{"body": {"Success": True, "RecordsTotal": 5, "Data": "khong-phai-json"}})
		self.assertEqual(M.ds_hd(cau_hinh(co_ma=True), "2026-09-17", "2026-11-15", 0, 100),
			{"dong": [{"RefID": "a"}, {"RefID": "b"}], "records_total": 0})
		self.assertEqual(M.ds_hd(cau_hinh(), datetime.date(2026, 9, 17), datetime.date(2026, 11, 15), 100, 100),
			{"dong": [], "records_total": 5})
		self.assertEqual(gon(a), ["POST /oauth", "POST /code/v3sainvoice/paging", "POST /v3sainvoice/paging"])
		self.assertEqual(hd_app(a.goi[1][2]), [("Content-Type", "application/x-www-form-urlencoded"), ("Authorization", "Bearer T1"),
			("TaxCode", MST)])
		self.assertEqual(a.goi[1][3], b"start=0&length=100&fromDate=2026-09-17T00%3A00%3A00.000Z&toDate=2026-11-15T23%3A59%3A59.000Z")
		self.assertEqual(a.goi[2][3], b"start=100&length=100&fromDate=2026-09-17T00%3A00%3A00.000Z&toDate=2026-11-15T23%3A59%3A59.000Z")
		self.assertNotIn(b"%22", a.goi[1][3])
		self.assertEqual(a.het_gio[1:], [(5, 60), (5, 60)])

	def test_ds_hd_vang(self):
		for ca in VANG["doc_phan_hoi_ds"]:
			v, m = ca["vao"], ca["mong"]
			with self.subTest(ten=ca["ten"]):
				M.xoa_token_nho()
				self.mang(TOK, {"status": v["status"], "body": v["text"]})
				if m["loi"]:
					with self.assertRaises(M.MisaLoi) as e:
						M.ds_hd(cau_hinh(), "2026-09-17", "2026-11-15", 0, 100)
					self.assertEqual(str(e.exception), m["loi"])
				else:
					self.assertEqual(M.ds_hd(cau_hinh(), "2026-09-17", "2026-11-15", 0, 100),
						{"dong": m["dong"], "records_total": m["records_total"]})

	def test_kv13_lay_mau(self):
		"""Không mã: POST {api}/v3common/template; có mã: /v3common/code/template; thân JSON ĐÚNG 4 khoá TypeInvoice, TaxCode, UserName, Password
		[đo]; truyền token thì không gọi /oauth; hẹn (5, 15)."""
		mau = [{"IPTemplateID": "t1", "InvSeries": "1C26TAA"}]
		a = self.mang(TOK, {"body": {"success": True, "data": json.dumps(mau)}}, {"body": {"success": True, "data": json.dumps(mau)}})
		self.assertEqual(M.lay_mau(cau_hinh()), mau)
		self.assertEqual(M.lay_mau(cau_hinh(co_ma=True), "T9"), mau)
		self.assertEqual(gon(a), ["POST /oauth", "POST /v3common/template", "POST /v3common/code/template"])
		self.assertEqual(hd_app(a.goi[1][2]), [("Content-Type", "application/json"), ("Authorization", "Bearer T1"), ("TaxCode", MST)])
		self.assertEqual(dict(a.goi[2][2])["Authorization"], "Bearer T9")
		self.assertEqual(a.goi[1][3], b'{"TypeInvoice":0,"TaxCode":"0100000000","UserName":"u-thu","Password":"p-thu"}')
		self.assertEqual(a.het_gio[1:], [(5, 15), (5, 15)])

	def test_lay_mau_vang(self):
		for ca in VANG["doc_phan_hoi_mau"]:
			v, m = ca["vao"], ca["mong"]
			with self.subTest(ten=ca["ten"]):
				self.mang({"status": v["status"], "body": v["text"]})
				if m["loi"]:
					with self.assertRaises(M.MisaLoi) as e:
						M.lay_mau(cau_hinh(), "T1")
					self.assertEqual(str(e.exception), m["loi"])
				else:
					self.assertEqual(M.lay_mau(cau_hinh(), "T1"), m["mau"])

	def test_truyen_tai_loi_khong_phai_day(self):
		"""Token / một HĐ / danh sách / mẫu: câu trung tính (không "hoá đơn chưa được gửi"), `chua_biet` luôn False."""
		self.nap_token(cau_hinh())
		for ham, loi, cau in (
				(lambda: M.lay_token(cau_hinh(), ep=True), requests.exceptions.ConnectTimeout("x"), "Không kết nối được tới MISA (ConnectTimeout)."),
				(lambda: M.lay_hd(cau_hinh(), "R"), requests.exceptions.ReadTimeout("x"),
					"Không nhận được trả lời của MISA (ReadTimeout) — thử lại sau ít phút."),
				(lambda: M.ds_hd(cau_hinh(), "2026-09-17", "2026-11-15", 0, 100), requests.exceptions.ChunkedEncodingError("x"),
					"Không nhận được trả lời của MISA (ChunkedEncodingError) — thử lại sau ít phút."),
				(lambda: M.lay_mau(cau_hinh(), "T1"), requests.exceptions.ConnectionError(urllib3.exceptions.MaxRetryError(None, "/x",
					urllib3.exceptions.NewConnectionError(None, "refused"))), "Không kết nối được tới MISA (NewConnectionError).")):
			with self.subTest(cau=cau):
				self.mang(loi)
				with self.assertRaises(M.MisaLoi) as e:
					ham()
				self.assertEqual((str(e.exception), e.exception.chua_biet), (cau, False))

	def test_che_bi_mat_doi_lai(self):
		"""[ĐX — I6] câu lỗi của token / một HĐ / danh sách / mẫu không mang tài khoản / mật khẩu / token MISA dội lại; bí mật < 4 ký tự không che."""
		self.mang({"status": 400, "body": {"error": "invalid_grant", "error_description": "Tài khoản u-thu-BIMAT không tồn tại"}})
		with self.assertRaises(M.MisaLoi) as e:
			M.lay_token(cau_hinh(tai_khoan="u-thu-BIMAT"))
		self.assertEqual(str(e.exception), "MISA token lỗi 400: Tài khoản *** không tồn tại (invalid_grant)")
		self.mang({"body": {"access_token": "TOKEN-BIMAT-1"}}, {"status": 401, "body": "Token TOKEN-BIMAT-1 expired for p-thu-BIMAT"})
		with self.assertRaises(M.MisaLoi) as e:
			M.lay_hd(cau_hinh(mat_khau="p-thu-BIMAT"), "R")
		self.assertEqual(str(e.exception), "Lấy HD lỗi 401: Token *** expired for ***")
		self.mang({"status": 500, "body": {"message": "Sai mật khẩu p-thu-BIMAT"}})
		with self.assertRaises(M.MisaLoi) as e:
			M.lay_mau(cau_hinh(mat_khau="p-thu-BIMAT"), "T1")
		self.assertEqual(str(e.exception), "Lấy mẫu HD lỗi 500: Sai mật khẩu ***")
		self.mang({"status": 500, "body": {"message": "Sai abc"}})
		with self.assertRaises(M.MisaLoi) as e:
			M.lay_mau(cau_hinh(mat_khau="abc"), "T1")
		self.assertEqual(str(e.exception), "Lấy mẫu HD lỗi 500: Sai abc")


# =====================================================================================================================================
# Máy chủ giả 127.0.0.1 — byte thật trên dây + lỗi truyền tải THẬT của requests / urllib3
# =====================================================================================================================================

class _MayChuGia:
	"""HTTP giả ở 127.0.0.1 bằng socket thô (mỗi kết nối một luồng): ghi NGUYÊN byte yêu cầu, gọi `xu_ly(byte, conn)`."""

	def __init__(self, xu_ly):
		self.xu_ly, self.yeu_cau = xu_ly, []
		self.sock = socket.create_server(("127.0.0.1", 0))
		self.goc = f"http://127.0.0.1:{self.sock.getsockname()[1]}/api/v2"
		threading.Thread(target=self._chay, daemon=True).start()

	def _chay(self):
		while True:
			try:
				conn, _ = self.sock.accept()
			except OSError:
				return
			threading.Thread(target=self._mot, args=(conn,), daemon=True).start()

	def _mot(self, conn):
		with conn:
			try:
				b = self._doc(conn)
				self.yeu_cau.append(b)
				self.xu_ly(b, conn)
			except OSError:
				pass

	@staticmethod
	def _doc(conn) -> bytes:
		conn.settimeout(5)
		b = b""
		while b"\r\n\r\n" not in b:
			m = conn.recv(65536)
			if not m:
				return b
			b += m
		dau, _, than = b.partition(b"\r\n\r\n")
		n = next((int(d.split(b":", 1)[1]) for d in dau.split(b"\r\n")[1:] if d.split(b":", 1)[0].strip().lower() == b"content-length"), 0)
		while len(than) < n:
			m = conn.recv(65536)
			if not m:
				break
			than += m
		return dau + b"\r\n\r\n" + than

	def dong(self):
		self.sock.close()


def _tra(conn, than, ma=200):
	b = (than if isinstance(than, str) else json.dumps(than)).encode()
	conn.sendall(f"HTTP/1.1 {ma} X\r\nContent-Type: application/json\r\nContent-Length: {len(b)}\r\nConnection: close\r\n\r\n".encode() + b)


def _dong_header(b: bytes) -> list:
	return b.partition(b"\r\n\r\n")[0].decode("latin-1").split("\r\n")[1:]


class TestMayChuGia(unittest.TestCase):
	def setUp(self):
		M.xoa_token_nho()
		self.addCleanup(M.xoa_token_nho)
		s = _PHIEN_THAT()
		s.trust_env = False  # không đi proxy của môi trường
		p = patch.object(M, "_phien", lambda: s)
		p.start()
		self.addCleanup(p.stop)

	def may_chu(self, sau_token):
		def xu_ly(b, conn):
			if b.split(b" ", 2)[1].endswith(b"/oauth"):
				_tra(conn, {"access_token": "T1", "expires_in": 3600})
			else:
				sau_token(b, conn)

		mc = _MayChuGia(xu_ly)
		self.addCleanup(mc.dong)
		return mc

	def test_byte_tren_day(self):
		"""Tên header đi trên dây ĐÚNG chữ hoa / thường, mỗi tên một lần: /oauth `taxcode`, đẩy `TaxCode`; thân UTF-8 (Content-Length theo byte)."""
		mc = self.may_chu(lambda b, conn: _tra(conn, {"success": True, "TransactionID": "TXABC"}))
		kq = M.day_hd(cau_hinh(dia_chi_api=mc.goc), HOA_DON)
		self.assertTrue(kq["ok"])
		token, day = mc.yeu_cau
		h = _dong_header(token)
		self.assertIn("taxcode: 0100000000", h)
		self.assertIn("Content-Type: text/plain", h)
		self.assertEqual([d for d in h if d.lower().startswith(("taxcode:", "authorization:"))], ["taxcode: 0100000000"])
		self.assertTrue(token.endswith(b"\r\n\r\ngrant_type=password&username=u-thu&password=p-thu"))
		h = _dong_header(day)
		self.assertEqual([d for d in h if d.lower().startswith(("taxcode:", "authorization:", "content-type:"))],
			["Content-Type: application/json", "Authorization: Bearer T1", "TaxCode: 0100000000"])
		than = '[{"RefID":"R","AccountObjectName":"Tạp hoá A","Quantity":2}]'.encode()
		self.assertTrue(day.endswith(b"\r\n\r\n" + than))
		self.assertIn(f"Content-Length: {len(than)}", h)

	def test_tu_choi_noi_la_chua_gui(self):
		x = socket.socket()
		x.bind(("127.0.0.1", 0))
		cong = x.getsockname()[1]
		x.close()
		ch = cau_hinh(dia_chi_api=f"http://127.0.0.1:{cong}/api/v2")
		with self.assertRaises(M.MisaLoi) as e:
			M.lay_token(ch)
		self.assertEqual(str(e.exception), "Không kết nối được tới MISA (NewConnectionError).")
		self.assertEqual(M.day_hd(ch, HOA_DON)["error"], "Không kết nối được tới MISA (NewConnectionError).")  # token hỏng trước khi đẩy

	def test_sai_dia_chi_la_chua_gui(self):
		kq = M.day_hd(cau_hinh(dia_chi_api="misa.gia/api/v2"), HOA_DON)
		self.assertEqual((kq["error"], kq["chua_biet"]), ("Không kết nối được tới MISA (MissingSchema).", False))

	def test_dut_sau_khi_gui_la_chua_biet(self):
		"""Máy chủ ĐÃ nhận đủ thân rồi: ngủ quá hẹn đọc (ReadTimeout) / đóng không trả lời (ConnectionError — ProtocolError) / thân chunked đứt
		(ChunkedEncodingError) → CHƯA BIẾT (route giữ pending — KV-22)."""
		def ngu(b, conn):
			time.sleep(1.5)

		def dong_ngay(b, conn):
			pass

		def dut_chunk(b, conn):
			conn.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Type: application/json\r\n\r\n10\r\n{\"success\":tr")
			time.sleep(0.2)

		for ten, xu_ly in (("ReadTimeout", ngu), ("đóng không trả lời", dong_ngay), ("chunked đứt", dut_chunk)):
			with self.subTest(ten=ten), patch.object(M, "HET_GIO_DAY", (2, 0.3)):
				M.xoa_token_nho()
				mc = self.may_chu(xu_ly)
				kq = M.day_hd(cau_hinh(dia_chi_api=mc.goc), HOA_DON)
				self.assertEqual((kq["error"], kq["chua_biet"]), (M.CAU_CHUA_BIET, True))
				self.assertTrue(mc.yeu_cau[-1].endswith('"Tạp hoá A","Quantity":2}]'.encode()))  # MISA đã có đủ thân

	def test_lay_hd_het_gio_doc(self):
		mc = self.may_chu(lambda b, conn: time.sleep(1.5))
		with patch.object(M, "HET_GIO_MOT_HD", (2, 0.3)), self.assertRaises(M.MisaLoi) as e:
			M.lay_hd(cau_hinh(dia_chi_api=mc.goc), "R")
		self.assertEqual(str(e.exception), "Không nhận được trả lời của MISA (ReadTimeout) — thử lại sau ít phút.")


# =====================================================================================================================================
# Cấu hình — Single NPP MISA Cau Hinh (§1.2 "đã lưu", §1.7 Password, §3.1 CauHinhMisa)
# =====================================================================================================================================

@contextmanager
def _khoa_site(khoa: str):
	goc = frappe.local.conf.get("encryption_key")
	frappe.local.conf.encryption_key = khoa
	try:
		yield
	finally:
		frappe.local.conf.encryption_key = goc


class TestCauHinhMisa(IntegrationTestCase):
	def setUp(self):
		frappe.db.savepoint("npp_test")
		frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)
		frappe.db.sql("DELETE FROM `__Auth` WHERE `doctype` = %s", CH.TEN)
		frappe.clear_document_cache(CH.TEN, CH.TEN)
		M.xoa_token_nho()

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.clear_document_cache(CH.TEN, CH.TEN)
		M.xoa_token_nho()

	def _luu(self, **kv):
		d = frappe.get_single(CH.TEN)
		d.update(kv)
		d.save(ignore_permissions=True)

	def _mang(self, *kich_ban) -> AdapterGia:
		a = AdapterGia(kich_ban)
		s = phien_gia(a)
		p = patch.object(M, "_phien", lambda: s)
		p.start()
		self.addCleanup(p.stop)
		return a

	def test_chua_luu(self):
		"""Chưa lưu → None (get_single vẫn trả mặc định — không dùng để biết "chưa cấu hình")."""
		self.assertIsNone(M.lay_cau_hinh())
		self.assertEqual(frappe.get_single(CH.TEN).dia_chi_api, "https://testapp.meinvoice.vn/api/v2")

	def test_doc_cau_hinh(self):
		self._luu(dia_chi_api="https://misa.gia/api/v2", mst_nguoi_ban=MST, tai_khoan="u-thu", mat_khau="p-thu", misa_company_id="156217",
			misa_inv_series="1C26TAA", loai_hd=2, ke_thua_mau_cu=1, misa_org_unit_id="ou", misa_user_id="us", misa_template_id="t1",
			moi_truong_thu=0, dang_dung=0)
		with patch("frappe.utils.password.get_decrypted_password", side_effect=AssertionError("không giải mã khi đọc")):
			ch = M.lay_cau_hinh()
		self.assertEqual((ch.dia_chi_api, ch.mst, ch.duong_token, ch.duong_day, ch.co_ma, ch.dang_dung, ch.moi_truong_thu),
			("https://misa.gia/api/v2", MST, "/oauth", "/v3sainvoice", False, False, False))
		self.assertEqual((ch.tai_khoan, ch.mat_khau), (None, None))  # chưa giải mã
		self.assertEqual(ch.cau_hinh_payload, {"misa_company_id": "156217", "misa_org_unit_id": "ou", "misa_user_id": "us", "loai_hd": 2,
			"misa_inv_series": "1C26TAA", "misa_inv_template_no": "1", "misa_template_id": "t1", "ke_thua_mau_cu": 1})
		self.assertIs(ch.giai_ma(), ch)
		self.assertEqual((ch.tai_khoan, ch.mat_khau), ("u-thu", "p-thu"))
		self.assertNotIn("u-thu", repr(ch))
		self.assertNotIn("p-thu", repr(ch))
		self.assertIn("tai_khoan='***'", repr(ch))
		p = H.dung_payload({"ten": "A"}, [], "R", ch.cau_hinh_payload, luc=datetime.datetime(2026, 11, 15, 3, tzinfo=datetime.UTC))[0]
		self.assertEqual((p["CompanyID"], p["InvoiceType"], p["InvSeries"], p["IsInheritFromOldTemplate"]), ("156217", 2, "1C26TAA", True))

	def test_duong(self):
		"""Có mã → /v3sainvoice/Code (bỏ qua duong_phat_hanh); token trống → '/oauth' ∥ '' (phát hành không lùi — publish/route.ts:329)."""
		self._luu(misa_is_invoice_with_code=1, duong_phat_hanh="/khac", duong_lay_token="", tai_khoan="u-thu", mat_khau="p-thu")
		ch = M.lay_cau_hinh()
		self.assertEqual((ch.co_ma, ch.duong_day, ch.duong_token), (True, "/v3sainvoice/Code", "/oauth"))
		ch = M.lay_cau_hinh(lui_duong_token=False)
		self.assertEqual(ch.duong_token, "")
		a = self._mang()
		with self.assertRaises(M.MisaLoi) as e:
			M.lay_token(ch)
		self.assertEqual(str(e.exception), H.CAU_THIEU_DUONG_TOKEN)
		self.assertEqual(a.goi, [])
		self._luu(misa_is_invoice_with_code=0, duong_phat_hanh="")
		self.assertEqual(M.lay_cau_hinh().duong_day, "/v3sainvoice")

	def test_mst_du_phong(self):
		"""mst_nguoi_ban ∥ NPP Cai Dat.ma_so_thue ∥ '' [BP]."""
		self._luu(mst_nguoi_ban="")
		frappe.db.set_single_value("NPP Cai Dat", "ma_so_thue", "0309999999")
		self.assertEqual(M.lay_cau_hinh().mst, "0309999999")
		frappe.db.set_single_value("NPP Cai Dat", "ma_so_thue", "")
		self.assertEqual(M.lay_cau_hinh().mst, "")

	def test_thieu_mat_khau_la_chuoi_rong(self):
		"""[Soát thiếu 2] mật khẩu chưa nhập → '' — /oauth nhận `password=` chứ không chữ "None"; lời đầu tự giải mã khi chưa nạp."""
		self._luu(dia_chi_api=API, tai_khoan="u-thu")
		ch = M.lay_cau_hinh()
		a = self._mang(TOK)
		M.lay_token(ch)
		self.assertEqual((ch.tai_khoan, ch.mat_khau), ("u-thu", ""))
		self.assertEqual(a.goi[0][3], b"grant_type=password&username=u-thu&password=")

	def test_go_tay_khong_giai_ma(self):
		"""Thử kết nối: chữ vừa gõ (trim kiểu JS) thì dùng, KHÔNG giải mã trường ấy; chỉ khoảng trắng → giải mã bản đã lưu."""
		self._luu(tai_khoan="u-thu", mat_khau="p-thu")
		with patch("frappe.utils.password.get_decrypted_password", side_effect=AssertionError("không được giải mã")):
			ch = M.lay_cau_hinh().giai_ma("  u-moi﻿", "\tp-moi ")
		self.assertEqual((ch.tai_khoan, ch.mat_khau), ("u-moi", "p-moi"))
		ch = M.lay_cau_hinh().giai_ma("   ", None)
		self.assertEqual((ch.tai_khoan, ch.mat_khau), ("u-thu", "p-thu"))

	def test_giai_ma_hong(self):
		"""Khoá site đổi (InvalidToken → frappe.throw tiếng Anh) / khoá sai định dạng (ValueError của Fernet) → `LoiGiaiMa` câu tiếng Việt,
		message_log sạch; lời gọi MISA không đi; gõ đủ cả hai thì vẫn thử được (KV-47 biến thể giải mã)."""
		from cryptography.fernet import Fernet
		from frappe.utils.password import get_decrypted_password

		self._luu(dia_chi_api=API, tai_khoan="u-thu", mat_khau="p-thu")
		a = self._mang()
		with _khoa_site(Fernet.generate_key().decode()):
			# Bẫy v16 (lý do không dùng raise_exception=False): lỗi giải mã bị NUỐT thành None ("chưa nhập") + chữ Anh nằm lại message_log.
			n = len(frappe.local.message_log)
			self.assertIsNone(get_decrypted_password(CH.TEN, CH.TEN, "mat_khau", raise_exception=False))
			self.assertIn("Encryption key is invalid", str(frappe.local.message_log[n:]))
			del frappe.local.message_log[n:]
		for khoa in (Fernet.generate_key().decode(), "khong-phai-khoa-fernet"):
			with self.subTest(khoa=khoa[:6]), _khoa_site(khoa):
				n = len(frappe.local.message_log)
				with self.assertRaises(M.LoiGiaiMa) as e:
					M.lay_cau_hinh().giai_ma()
				self.assertEqual(str(e.exception), "Không giải mã được tài khoản MISA — khoá mã hoá của site (encryption_key trong "
					"site_config.json) đã đổi so với lúc lưu cấu hình?")
				self.assertEqual(e.exception.ly_do, "khoá mã hoá của site không mở được tài khoản / mật khẩu MISA đã lưu")
				self.assertEqual(len(frappe.local.message_log), n)
				with self.assertRaises(M.LoiGiaiMa):
					M.lay_token(M.lay_cau_hinh())
				kq = M.day_hd(M.lay_cau_hinh(), HOA_DON)
				self.assertEqual((kq["ok"], kq["error"]), (False, str(e.exception)))
				self.assertEqual(M.lay_cau_hinh().giai_ma("u-go", "p-go").mat_khau, "p-go")
		self.assertEqual(a.goi, [])


# =====================================================================================================================================
# I6 — không bí mật trong câu lỗi / Error Log (traceback CÓ biến cục bộ của developer_mode)
# =====================================================================================================================================

BI_MAT = ("u-thu-BIMAT", "p-thu-BIMAT", "TOKEN-BIMAT-1")
TIEU_DE_I6 = "I6 thử misa_mang"  # tabError Log là MyISAM — rollback KHÔNG gỡ được, tearDown xoá theo tiêu đề này


def _ghi_loi(ham):
	"""Gọi `ham`; ngoại lệ → frappe.log_error ngay trong khung bắt (như route / việc nền) — khung này không giữ adapter / bí mật."""
	try:
		ham()
	except Exception as e:  # bài thử: ghi mọi lỗi như khung gọi thật
		return str(e), frappe.log_error(title=TIEU_DE_I6)
	return None, None


class TestBiMatI6(IntegrationTestCase):
	"""Biến cục bộ giữ bí mật mang tên `password` / `token` / `secret` / `key` (bộ che của frappe.get_traceback chỉ nhận tên tiếng Anh) và
	`CauHinhMisa` có repr riêng — traceback_with_variables in từng thuộc tính của dataclass repr tự sinh."""

	def setUp(self):
		frappe.db.savepoint("npp_test")
		M.xoa_token_nho()
		self.dev = frappe.conf.get("developer_mode")
		frappe.conf.developer_mode = 1  # traceback kèm biến chỉ bật khi developer_mode (frappe/utils/__init__.py:325)

	def tearDown(self):
		frappe.conf.developer_mode = self.dev
		frappe.db.rollback(save_point="npp_test")
		frappe.db.delete("Error Log", {"method": TIEU_DE_I6})  # MyISAM: không theo giao dịch
		M.xoa_token_nho()

	def _mang(self, *kich_ban):
		a = AdapterGia(kich_ban)
		s = phien_gia(a)
		p = patch.object(M, "_phien", lambda: s)
		p.start()
		self.addCleanup(p.stop)

	def _sach(self, cau, el, *chu_phai_co):
		tb = el.error
		self.assertIn("Traceback with variables", tb)  # bài không rỗng: traceback CÓ in biến
		for chu in chu_phai_co:
			self.assertIn(chu, tb)
		for bm in BI_MAT:
			self.assertNotIn(bm, cau or "")
			self.assertNotIn(bm, tb)
			self.assertNotIn(bm, el.method or "")

	def test_traceback_khong_lo(self):
		ch = cau_hinh(tai_khoan=BI_MAT[0], mat_khau=BI_MAT[1])
		tok = {"body": {"access_token": BI_MAT[2], "expires_in": 3600}}
		# (tên, token đã nhớ trước?, kịch bản, lời gọi, chữ phải thấy trong traceback — biến bí mật CÓ mặt nhưng bị che)
		ca = [
			("/oauth hết giờ nối", False, [requests.exceptions.ConnectTimeout("x")], lambda: M.lay_token(ch),
				("password_form = ********", "than_secret = ********")),
			("/oauth sai mật khẩu", False, [{"body": {"error": "invalid_grant", "error_description": "Sai"}}], lambda: M.lay_token(ch, ep=True),
				("password_form = ********", "cache_key = ********", "token_text = ********")),
			("KV-55 token dưới khoá lạ", False, [{"body": {"Data": {"AccessToken": BI_MAT[2]}}}], lambda: M.lay_token(ch, ep=True),
				("token_kq = ********",)),
			("mẫu hết giờ đọc", True, [requests.exceptions.ReadTimeout("x")], lambda: M.lay_mau(ch),
				("password_body = ********", "than_secret = ********")),
			("GET 401", True, [{"status": 401, "body": "x"}], lambda: M.lay_hd(ch, "R"), ("token = ********",)),
			("lỗi lạ trong chuỗi thử lại của đẩy", True, [CAU_401, tok], lambda: M.day_hd(ch, HOA_DON, lambda: 1 / 0),
				("token_dau = ********", "token = ********")),
		]
		for ten, nap, kich_ban, ham, chu in ca:
			with self.subTest(ten=ten):
				M.xoa_token_nho()
				if nap:
					self._mang(tok)
					M.lay_token(ch)
				self._mang(*kich_ban)
				cau, el = _ghi_loi(ham)
				self.assertIsNotNone(el, ten)
				self._sach(cau, el, "CauHinhMisa(", *chu)

	def test_giai_ma_hong_khong_lo_chu_go(self):
		"""Thử kết nối gõ tài khoản, mật khẩu đã lưu giải mã hỏng → LoiGiaiMa; khung giữ chữ vừa gõ không lộ."""
		from cryptography.fernet import Fernet

		frappe.db.sql("DELETE FROM `__Auth` WHERE `doctype` = %s", CH.TEN)
		d = frappe.get_single(CH.TEN)
		d.mat_khau = "p-cu-luu"
		d.save(ignore_permissions=True)
		with _khoa_site(Fernet.generate_key().decode()):
			cau, el = _ghi_loi(lambda: M.lay_cau_hinh().giai_ma(BI_MAT[0], None))
		self.assertEqual(cau, M.CAU_GIAI_MA)
		self._sach(cau, el, "password_vao = ********")

	def test_repr_cau_hinh(self):
		"""repr / str / bộ in traceback_with_variables của CauHinhMisa không mang tài khoản / mật khẩu (dataclasses.replace giữ kiểu)."""
		from traceback_with_variables.fast_capped_str_casts import to_capped_str

		ch = dataclasses.replace(cau_hinh(tai_khoan=BI_MAT[0], mat_khau=BI_MAT[1]), co_ma=True)
		for s in (repr(ch), str(ch), to_capped_str(ch, len_cap=1000, obj_depth=1), f"{ch}"):
			for bm in BI_MAT:
				self.assertNotIn(bm, s)
		self.assertIn("co_ma=True", repr(ch))
		self.assertIn("mat_khau=''", repr(cau_hinh(mat_khau="")))
		self.assertIn("mat_khau=None", repr(cau_hinh(mat_khau=None)))
