"""Luật thuần HOÁ ĐƠN ĐIỆN TỬ MISA (nppsale.luat.hddt) — so TỪNG ca với số vàng chạy từ chính mã TS của nppsale (đặc tả dac_ta_hddt.md
§8.0 tầng 1, §8.1 Nhóm A KV-01 … KV-12 + ca thuần của nhóm khác: KV-13 / KV-14 phần đọc phản hồi, KV-53 / KV-55 / KV-57 phần luật).

Mẫu `du_lieu/hddt_mau.json` sinh bằng `tools/vang_hddt.mjs` (bản chép src/lib/misa/*.ts chỉ khác dòng import, UUID + giờ ghim, fetch giả).
Ca có `lech` là chỗ bản Python CHỦ Ý khác TS (H8, H17, H25, H26, lệch nhỏ thân `null`) — `mong` đã gồm luật lệch, `lech.ts` là số TS.
Khi có portal/nguon và node, bài chạy lại bộ sinh và so với tệp đã ghi để bắt lúc nppsale đổi luật. Thêm bài chỉ-Python cho luật [ĐX] không
có bản TS (H7 gộp ghi chú, H25 che token, H26 ngày có thật, giờ VN).

	cd /home/user/npp && /home/frappe/frappe-bench/env/bin/python -m unittest nppsale.tests.test_luat_hddt
"""
import datetime
import json
import os
import shutil
import subprocess
import unittest

from nppsale.luat import hddt as H

DIR = os.path.dirname(__file__)
MAU = os.path.join(DIR, "du_lieu", "hddt_mau.json")
GOC = os.path.abspath(os.path.join(DIR, "..", ".."))
BO_SINH = os.path.join(GOC, "tools", "vang_hddt.mjs")
NGUON = os.path.join(GOC, "portal", "nguon", "src", "lib", "misa")


def _so_nguyen_js(t):
	"""Đọc tệp vàng theo nghĩa JS: JSON.stringify in số thực ≥ 2^53 không có dấu chấm (12345678901234567000) — đó là số thực."""
	n = int(t)
	return float(t) if abs(n) > 2 ** 53 else n


def _doc_vang(chuoi):
	return json.loads(chuoi, parse_int=_so_nguyen_js)


VANG = _doc_vang(open(MAU, encoding="utf-8").read())
MA_LECH = {"H8", "H17", "H8 + H17", "H25", "H26", "≠ nhỏ"}


def _giai(v):
	"""{"$so": "-0.4"} → float, {"$nguyen": "…"} → int (số JSON không chở được: -0, NaN, 215000.0 kiểu float, int > 2^53)."""
	if isinstance(v, list):
		return [_giai(x) for x in v]
	if isinstance(v, dict):
		if len(v) == 1 and "$so" in v:
			return float(v["$so"])
		if len(v) == 1 and "$nguyen" in v:
			return int(v["$nguyen"])
		return {k: _giai(x) for k, x in v.items()}
	return v


def _giong_het(tc, a, b, duong="$"):
	"""So chặt (thân gửi MISA): cùng kiểu (int ≠ float ≠ bool), cùng thứ tự khoá, cùng giá trị."""
	if isinstance(b, bool) or isinstance(a, bool):
		tc.assertIs(type(a), type(b), duong)
		tc.assertEqual(a, b, duong)
	elif isinstance(b, dict):
		tc.assertIsInstance(a, dict, duong)
		tc.assertEqual(list(a), list(b), duong)
		for k in b:
			_giong_het(tc, a[k], b[k], f"{duong}.{k}")
	elif isinstance(b, list):
		tc.assertIsInstance(a, list, duong)
		tc.assertEqual(len(a), len(b), duong)
		for i, (x, y) in enumerate(zip(a, b, strict=True)):
			_giong_het(tc, x, y, f"{duong}[{i}]")
	else:
		tc.assertIs(type(a), type(b), f"{duong}: {a!r} vs {b!r}")
		tc.assertEqual(a, b, duong)


def _dong_payload(vao):
	if "dong_ct" in vao:
		return [H.dong_hang(c["ten"], c["sku"], c["dvt"], c["dvt_co_so"], c["sl"], c["gia_ban"], c["giam"], c["he_so"],
			H.thue_phan_tram(c["thue"], 0 if c["nhanh"] == "hd" else 10)) for c in _giai(vao["dong_ct"])]
	if "tong_hop" in vao:
		t = vao["tong_hop"]
		return [H.dong_tong_hop(t["tien_hang"], t["tien_thue"], t["tong_tien"])]
	return _giai(vao["dong"])


def _payload(vao):
	u = vao["uuid"]
	return H.dung_payload(vao["nguoi_mua"], _dong_payload(vao), u[0], vao["cau_hinh"], vao["che_do"], vao["po_note"],
		datetime.datetime.fromisoformat(vao["luc"]), iter(u[1:]).__next__)


class TestKieuJs(unittest.TestCase):
	"""§2.1 — tron / so_js / tien_vn / chuoi / so / js_khoa / js_cat / JSON."""

	def test_tron(self):
		for ca in VANG["tron"]:
			with self.subTest(ca=ca):
				r = H.tron(_giai(ca["vao"]))
				self.assertEqual(r, ca["mong"])
				self.assertIsInstance(r, int)

	def test_so_js(self):
		for ca in VANG["so_js"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.so_js(_giai(ca["vao"])), ca["mong"])

	def test_tien_vn(self):
		for ca in VANG["tien_vn"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.tien_vn(_giai(ca["vao"])), ca["mong"])

	def test_chuoi_so(self):
		for ca in VANG["chuoi"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.chuoi(ca["vao"]), ca["mong"])
		for ca in VANG["so"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.so(_giai(ca["vao"])), ca["mong"])
		for ca in VANG["quan_he"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.quan_he(_giai(ca["vao"])), ca["mong"])

	def test_khoa_cat_json(self):
		for ca in VANG["js_khoa"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.js_khoa(H.js_doc_json(ca["vao"])), ca["mong"])
		for ca in VANG["js_cat"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.js_cat(*ca["vao"]), ca["mong"])
		for ca in VANG["js_json"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.js_json(H.js_doc_json(ca["vao"])), ca["mong"])

	def test_json_chat_nhu_js(self):
		for t in ("NaN", '{"a":Infinity}', "[-Infinity]", "", "{'a':1}", "﻿{}"):
			with self.subTest(t=t), self.assertRaises(ValueError):
				H.js_doc_json(t)


class TestChuanHoa(unittest.TestCase):
	"""§2.2 (KV-12) — chuẩn hoá khi SO, giữ nguyên khi LƯU."""

	def test_vang(self):
		for ca in VANG["chuan_hoa"]:
			with self.subTest(ca=ca):
				self.assertEqual(getattr(H, ca["ham"])(*ca["vao"]), ca["mong"])

	def test_kv12_ghim(self):
		self.assertEqual((H.chuan_so("000"), H.chuan_so(" 12 3 "), H.chuan_so(None)), ("0", "12 3", ""))
		self.assertEqual(H.ky_hieu_long(" 1c25 mhg"), "C25 MHG")
		self.assertEqual((H.cung_ky_hieu("1C25MHG", "C25MHG"), H.cung_ky_hieu("", "")), (True, False))
		self.assertEqual((H.tien_vn(212600), H.tien_vn(-108002), H.tien_vn(-0.4)), ("212.600đ", "-108.002đ", "-0đ"))
		self.assertEqual((H.so_js(215000.0), H.so_js(None), H.so_js(1e21), H.so_js(1e-7)), ("215000", "null", "1e+21", "1e-7"))
		self.assertIsNone(H.ngay_iso("2026-13-01"))

	def test_ngay_that_h26(self):
		"""[ĐX H26] ngay_iso giữ đúng TS ('2026-02-30' lọt); ngay_that kiểm lịch thật cho hàm ghi."""
		self.assertEqual(H.ngay_iso("2026-02-30T00:00:00"), "2026-02-30")
		self.assertEqual([H.ngay_that(x) for x in ("2026-02-30", "2026-04-31", "2026-02-29", "0000-01-01", "abc", None, "20261115")],
			[None] * 7)
		self.assertEqual([H.ngay_that(x) for x in ("2028-02-29", "2026-11-15", "2026-12-31")], ["2028-02-29", "2026-11-15", "2026-12-31"])


class TestTrangThai(unittest.TestCase):
	"""§2.3–§2.6 (KV-06 … KV-09) — đọc bản ghi, suy trạng thái, so tiền, áp kết quả."""

	def test_doc_ban_ghi(self):
		for ca in VANG["doc_ban_ghi"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.doc_ban_ghi(ca["vao"]), ca["mong"])

	def test_suy_trang_thai(self):
		for ca in VANG["suy_trang_thai"]:
			v = ca["vao"]
			with self.subTest(ten=ca["ten"]):
				self.assertEqual(list(H.suy_trang_thai(H.doc_ban_ghi(v["raw"]), v["co_ma"], v["dang"])), ca["mong"])

	def test_so_tien(self):
		for ca in VANG["so_tien"]:
			v = ca["vao"]
			with self.subTest(ten=ca["ten"]):
				self.assertEqual(list(H.so_tien(H.doc_ban_ghi(v["raw"]), v["relation"], v["so"])), ca["mong"])

	def test_ap_dung(self):
		for ca in VANG["ap_dung"]:
			v = ca["vao"]
			with self.subTest(ten=ca["ten"]):
				self.assertEqual(H.ap_dung(v["raw"], v["so"], v["co_ma"], v["luc"]), ca["mong"])

	def test_lech_khai_du(self):
		"""Mọi ca lệch có mã H# đã biết, lý do và số TS để đối chiếu; ca KHÔNG lệch thì ghi chú Python = ghi chú TS (đã kiểm ở bộ sinh)."""
		n = 0
		for ds in VANG.values():
			if not isinstance(ds, list):
				continue
			for ca in ds:
				if isinstance(ca, dict) and "lech" in ca:
					n += 1
					self.assertIn(ca["lech"]["ma"], MA_LECH, ca.get("ten"))
					self.assertTrue(ca["lech"]["ly_do"] and "ts" in ca["lech"], ca.get("ten"))
		self.assertGreaterEqual(n, 12)
		ma = {c["lech"]["ma"] for c in VANG["ap_dung"] if "lech" in c}
		self.assertEqual(ma, {"H8", "H17"})

	def test_h8_khong_ha_trang_thai(self):
		ca = next(c for c in VANG["ap_dung"] if c["ten"] == "KV-08 B1 [H8] MISA trả {}")
		self.assertEqual(ca["lech"]["ts"]["updates"]["misa_status"], "sent")  # nppsale hạ signed → sent [đo B1]
		kq = H.ap_dung({}, {"misa_status": "signed", "misa_inv_no": "00000123", "tong_tien": 110000}, False, "L")
		self.assertNotIn("misa_status", kq["cap_nhat"])
		self.assertEqual(kq["ghi_chu"], ["MISA trả bản ghi chưa có số trong khi sổ đã ghi số 00000123 — giữ nguyên trạng thái, cần kiểm tra tay."])

	def test_gop_ghi_chu_h7(self):
		"""[BP H7] chỉ thêm dòng chưa có nguyên văn; không có dòng mới → ô giữ nguyên (nppsale thay cả ô)."""
		cu = "MẤT RefID: cột misa_invoice_id cũ đã bị số hoá đơn ghi đè (mig 099)."
		moi = ["Lệch tiền với MISA — Tổng tiền: sổ 110000, MISA 110002."]
		o = H.gop_ghi_chu(cu, moi)
		self.assertEqual(o, cu + "\n" + moi[0])
		self.assertEqual(H.gop_ghi_chu(o, moi), o)
		self.assertEqual(H.gop_ghi_chu(o, [moi[0], "B", "B", ""]), o + "\nB")
		self.assertIsNone(H.gop_ghi_chu(None, []))
		self.assertEqual(H.gop_ghi_chu("", ["A"]), "A")
		self.assertEqual(H.gop_ghi_chu("A\nB", ["B", "A"]), "A\nB")

	def test_bo_ngay_khong_that_h26(self):
		"""[ĐX H26 — KV-53] hàm ghi bỏ khoá ngày không có thật + ghi chú; khoá khác giữ."""
		raw = {"InvNo": "00000123", "InvSeries": "1C26TAA", "InvDate": " 2026-02-30T00:00:00 ", "PublishStatus": 3, "EInvoiceStatus": 1,
			"TotalAmount": 212600}
		kq = H.ap_dung(raw, {"misa_status": "sent", "tong_tien": 212600}, False, "L")
		self.assertEqual(kq["cap_nhat"]["misa_inv_date"], "2026-02-30")
		cap = dict(kq["cap_nhat"])
		self.assertEqual(H.bo_ngay_khong_that(cap, raw),
			["MISA trả InvDate=2026-02-30T00:00:00 không phải ngày có thật — bỏ qua, cần kiểm tra tay."])
		self.assertNotIn("misa_inv_date", cap)
		self.assertEqual((cap["misa_inv_no"], cap["misa_status"], cap["misa_last_checked_at"]), ("00000123", "signed", "L"))
		cap2 = {"misa_inv_date": "2026-11-15", "misa_status": "signed"}
		self.assertEqual(H.bo_ngay_khong_that(cap2, {"InvDate": "2026-11-15"}), [])
		self.assertEqual(cap2["misa_inv_date"], "2026-11-15")
		self.assertEqual(H.bo_ngay_khong_that({"misa_status": "sent"}, {}), [])


class TestPayload(unittest.TestCase):
	"""§2.7 (KV-01 … KV-05, KV-09, KV-28) — dòng hàng từ chứng từ + thân gửi /v3sainvoice, so TRỌN với payload TS."""

	def test_dong_hang(self):
		for ca in VANG["dong_hang"]:
			c = ca["vao"]
			with self.subTest(ca=c):
				self.assertEqual(H.dong_hang(c["ten"], c["sku"], c["dvt"], c["dvt_co_so"], c["sl"], c["gia_ban"], c["giam"], c["he_so"],
					H.thue_phan_tram(c["thue"], 0 if c["nhanh"] == "hd" else 10)), ca["mong"])
		for ca in VANG["dong_tong_hop"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.dong_tong_hop(**ca["vao"]), ca["mong"])

	def test_payload_tron_ven(self):
		for ca in VANG["dung_payload"]:
			with self.subTest(ten=ca["ten"]):
				p = _payload(ca["vao"])
				self.assertEqual(p, ca["mong"])
				_giong_het(self, p, ca["mong"])
				# Byte gửi đi: json.dumps của Python phải ra ĐÚNG chuỗi JSON.stringify của TS (2 chứ không 2.0, thứ tự khoá).
				self.assertEqual(json.dumps(p, ensure_ascii=False, separators=(",", ":")), H.js_json(ca["mong"]))

	def test_kv_ghim(self):
		"""Số của đặc tả (KV-01, 02, 03, 04, 05, 28) đọc thẳng từ kết quả Python — giữ được cả khi tệp vàng bị sinh lại sai."""
		ten = {c["ten"]: c for c in VANG["dung_payload"]}
		h = _payload(ten["KV-01 hai mức thuế, giảm dòng, PO"]["vao"])[0]
		self.assertEqual([[d["UnitPrice"], d["Quantity"], d["AmountOC"], d["DiscountAmountOC"], d["VATRate"], d["VATAmountOC"]]
			for d in h["InvoiceDetails"]], [[10000, 10, 100000, 0, 10, 10000], [20000, 5, 100000, 5000, 8, 7600]])
		self.assertEqual([h[k] for k in ("TotalSaleAmountOC", "TotalDiscountAmountOC", "TotalAmountWithoutVATOC", "TotalVATAmountOC",
			"TotalAmountOC", "IsMoreVATRate", "VATRate", "IsTaxReduction43", "TypeDiscount", "InvNo", "ContactName", "PaymentMethod")],
			[200000, 5000, 195000, 17600, 212600, True, 0, True, 1, "<Chưa cấp số>", "Tạp hoá A, PO-7", "Chuyển khoản"])
		self.assertEqual({h["InvDate"], h["CreatedDate"], h["ModifiedDate"]}, {"2026-11-15T10:00:00+07:00"})
		self.assertEqual({d["RefID"] for d in h["InvoiceDetails"]}, {h["RefID"]})
		h = _payload(ten["KV-02 chiết khấu không chia hết"]["vao"])[0]
		d = h["InvoiceDetails"][0]
		self.assertEqual((d["UnitPrice"], d["AmountOC"], d["DiscountAmountOC"], d["VATAmountOC"], h["TotalAmountOC"]),
			(33666, 100999, 1000, 10000, 109999))
		h = _payload(ten["KV-03 quy đổi hộp + đầu vào lạ"]["vao"])[0]
		self.assertEqual([(d["UnitName"], d["Quantity"], d["UnitPrice"], d["AmountOC"], d["VATRate"], d["VATAmountOC"])
			for d in h["InvoiceDetails"]], [("Lon", 48, 4167, 200000, 10, 20000), ("Hộp", 2, 1000, 2000, 10, 200), ("Hộp", 2, 1000, 2000, 0, 0)])
		self.assertEqual(h["PaymentMethod"], "TM/CK")
		h = _payload(ten["KV-04 làm tròn nửa đồng"]["vao"])[0]
		self.assertEqual((h["InvoiceDetails"][0]["VATAmountOC"], h["TotalAmountOC"]), (1235, 13580))
		h = _payload(ten["KV-05 không dòng"]["vao"])[0]
		self.assertEqual((h["VATRate"], h["IsMoreVATRate"], h["TotalAmountOC"]), (10, False, 0))
		h = _payload(ten["KV-05 dòng tổng hợp"]["vao"])[0]
		self.assertEqual((h["InvoiceDetails"][0]["VATRate"], h["TotalVATAmountOC"], h["TotalAmountOC"]), (9, 17550, 212550))
		h = _payload(ten["KV-28 HD-0002 as_sold"]["vao"])[0]
		self.assertEqual([[d["InventoryItemCode"], d["UnitName"], d["Quantity"], d["UnitPrice"], d["AmountOC"], d["DiscountAmountOC"],
			d["VATRate"], d["VATAmountOC"]] for d in h["InvoiceDetails"]], [["SP01", "Thùng", 2, 240000, 480000, 0, 10, 48000],
			["SP02", "Hộp", 1, 0, 0, 0, 10, 0], ["SP03", "Hộp", 3, 33666, 100999, 1000, 8, 8000]])
		self.assertEqual([h[k] for k in ("TotalSaleAmountOC", "TotalDiscountAmountOC", "TotalAmountWithoutVATOC", "TotalVATAmountOC",
			"TotalAmountOC")], [580999, 1000, 579999, 56000, 635999])
		h = _payload(ten["KV-28 HD-0002 box"]["vao"])[0]
		d = h["InvoiceDetails"][0]
		self.assertEqual([d["UnitName"], d["Quantity"], d["UnitPrice"], d["AmountOC"]], ["Lon", 48, 10000, 480000])
		self.assertEqual(h["TotalAmountOC"], 635999)

	def test_gio_vn(self):
		vn = datetime.timezone(datetime.timedelta(hours=7))
		self.assertEqual(H.gio_vn(datetime.datetime(2026, 11, 15, 10, 0, 0, 999999, tzinfo=vn)), "2026-11-15T10:00:00+07:00")
		self.assertEqual(H.gio_vn(datetime.datetime(2026, 11, 15, 17, 30, tzinfo=datetime.UTC)), "2026-11-16T00:30:00+07:00")
		with self.assertRaises(ValueError):
			H.gio_vn(datetime.datetime(2026, 11, 15, 10, 0))  # giờ trần: không biết là giờ nào
		p = H.dung_payload({"ten": "A"}, [{"ten": "X", "dvt": "Cái", "sl": 1, "don_gia": 1000, "vat": 10}], "R", {})
		self.assertEqual(len(p[0]["InvoiceDetails"][0]["RefDetailID"]), 36)
		self.assertRegex(p[0]["InvDate"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+07:00$")

	def test_url_ghi_chu(self):
		for ca in VANG["url_tra_cuu"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.url_tra_cuu(ca["vao"]), ca["mong"])
		for ca in VANG["ghi_chu_bi_thay_the"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.ghi_chu_bi_thay_the(ca["vao"]), ca["mong"])


class TestPhanHoi(unittest.TestCase):
	"""§2.8 (KV-10, KV-13, KV-14, KV-55) — đọc trả lời của năm lời gọi MISA (bộ sinh chạy client.ts với fetch giả)."""

	def test_loi_misa_xac_thuc(self):
		for ca in VANG["loi_misa"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.loi_misa(*ca["vao"]), ca["mong"])
		for ca in VANG["la_loi_xac_thuc"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.la_loi_xac_thuc(*ca["vao"]), ca["mong"])

	def test_hieu_phan_hoi_day(self):
		for ca in VANG["hieu_phan_hoi_day"]:
			v = ca["vao"]
			with self.subTest(ten=ca["ten"]):
				self.assertEqual(H.hieu_phan_hoi_day(v["status"], v["text"]), ca["mong"])
				# publishInvoice gửi lại đúng một lần khi HTTP lỗi + la_loi_xac_thuc (kể cả 400 / 500 có chữ token — H27).
				self.assertEqual(not 200 <= v["status"] <= 299 and H.la_loi_xac_thuc(v["status"], v["text"]), ca["thu_lai"])

	def test_token(self):
		for ca in VANG["doc_phan_hoi_token"]:
			v, m = ca["vao"], ca["mong"]
			with self.subTest(ten=ca["ten"]):
				r = H.doc_phan_hoi_token(v["status"], v["text"])
				self.assertEqual((r["token"], r["loi"]), (m["token"], m["loi"]))
				if "tho" in m:
					self.assertEqual(r["tho"], m["tho"])
		self.assertEqual(H.doc_phan_hoi_token(200, '{"access_token":"T1","expires_in":3600}')["expires_in"], 3600)
		self.assertEqual(H.doc_phan_hoi_token(200, "<html>")["tho"], {"_raw": "<html>"})

	def test_token_khong_lo_h25(self):
		"""[ĐX H25 — KV-55] câu lỗi `/oauth` không mang token, kể cả khi MISA đổi tên khoá; thân không có khoá *token* thì giữ y nppsale."""
		r = H.doc_phan_hoi_token(200, '{"Data":{"AccessToken":"TOKEN-GIA-123"},"expires_in":3600}')
		self.assertEqual(r["loi"], 'MISA token: không thấy access_token trong response. Raw: {"Data":{"AccessToken":"***"},"expires_in":3600}')
		self.assertNotIn("TOKEN-GIA-123", json.dumps(r, ensure_ascii=False).replace(json.dumps(r["tho"], ensure_ascii=False), ""))
		ca = next(c for c in VANG["doc_phan_hoi_token"] if c["ten"] == "KV-55 token dưới khoá lạ")
		self.assertIn("TOKEN-GIA-123", ca["lech"]["ts"]["loi"])  # nppsale lộ token [đo soat2 ca 1]
		self.assertEqual(H.che_token('{"Data":"{\\"AccessToken\\":\\"x-y\\",\\"a\\":1}"}'), '{"Data":"{\\"AccessToken\\":\\"***\\",\\"a\\":1}"}')
		self.assertEqual(H.che_token("access_token=abc123&token_type=bearer"), "access_token=***&token_type=***")
		for t in ('{"foo":1}', '{"expires_in": 3600, "a": "b c"}', "", '{"access_token":""}'):
			self.assertEqual(H.che_token(t), t)

	def test_token_khong_lo_h25_mo_rong(self):
		"""[Sửa cuối — phát hiện 7] token KHÔNG nằm dưới khoá chữ "token" vẫn bị che: JWT ở bất kỳ đâu (vỏ {success, data} của MISA), giá trị dạng token
		của `Data` / `jwt` / `*key`, phần tử mảng (`"tokens":["…"]`), và nhánh HTTP lỗi của /oauth (trước: in thẳng 500 ký tự thân). Câu không có gì
		giống token giữ y nppsale; che lại lần hai không đổi gì."""
		jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1LXRodSJ9.SIGNATURE-BI-MAT"
		ca = [
			('{"success":true,"errorCode":null,"data":"' + jwt + '"}', '{"success":true,"errorCode":null,"data":"***"}'),
			('{"Data":{"jwt":"' + jwt + '"}}', '{"Data":{"jwt":"***"}}'),
			('{"tokens":["RAW-TOKEN-IN-ARRAY"]}', '{"tokens":["***"]}'),
			('{"Success":true,"Data":"abcdefghijklmnopqrstuvwxyz0123","ErrorCode":null}', '{"Success":true,"Data":"***","ErrorCode":null}'),
			('{"api_key":"ABCDEFGHIJKLMNOPQRSTUVWX"}', '{"api_key":"***"}'),
			('Bearer ' + jwt + ' het han', "Bearer *** het han"),
		]
		for vao, ra in ca:
			with self.subTest(vao=vao):
				self.assertEqual(H.che_token(vao), ra)
				self.assertEqual(H.che_token(ra), ra)
		for giu in ('{"Success":true,"Data":"ngan"}', '{"metadata":"Mot cau co khoang trang dai hon hai muoi"}', "<html>x</html>",
				'{"data":{"access_token":""}}'):
			self.assertEqual(H.che_token(giu), giu)
		r = H.doc_phan_hoi_token(200, '{"success":true,"errorCode":null,"data":"' + jwt + '"}')
		self.assertEqual(r["loi"], 'MISA token: không thấy access_token trong response. Raw: {"success":true,"errorCode":null,"data":"***"}')
		self.assertEqual(H.doc_phan_hoi_token(500, '{"Data":{"AccessToken":"TOKEN-IN-500"}}')["loi"],
			'MISA token lỗi 500: {"Data":{"AccessToken":"***"}}')
		self.assertEqual(H.doc_phan_hoi_token(401, '{"error":"invalid_token","error_description":"Token ' + jwt + ' expired"}')["loi"],
			"MISA token lỗi 401: Token *** expired (invalid_token)")
		# JWT vắt qua mốc cắt 500 của `loi_misa` (mốc rơi giữa phần thân JWT — nửa còn lại không còn "dạng JWT" để bắt) vẫn che trọn: che TRƯỚC khi cắt
		dai = '{"x":"' + "a" * 450 + '","sess":"' + jwt + '"}'
		loi = H.doc_phan_hoi_token(500, dai)["loi"]
		self.assertEqual(len(loi), len("MISA token lỗi 500: ") + 500)
		self.assertNotIn("eyJhbGci", loi)
		self.assertNotIn("eyJhbGci", H.doc_phan_hoi_token(200, dai)["loi"])  # nhánh "không thấy access_token" (cắt 300) cũng vậy

	def test_co_ban_ghi_that(self):
		"""[Sửa cuối — phát hiện 9] bản ghi `GET ?refID=` RỖNG (`{}` — `data: '{}'` / `'[]'`) không nói "MISA có tờ"; RefID trùng (hoa thường) hoặc một
		trường nhận diện / trạng thái / cờ huỷ thì có. `doc_phan_hoi_lay_hd` vẫn parity JS (trả `{}` cho mảng)."""
		self.assertEqual(H.doc_phan_hoi_lay_hd(200, '{"success":true,"data":"[]"}')["ban_ghi"], {})
		self.assertEqual(H.doc_phan_hoi_lay_hd(200, '{"success":true,"data":"{}"}')["ban_ghi"], {})
		for raw, ref, mong in (
			({}, "R", False), (None, "R", False), ([], "R", False), ({"foo": 1}, "R", False), ({"RefID": "X"}, "R", False),
			({"RefID": "  r  "}, "R", True), ({"RefID": "R"}, None, False), ({"InvNo": "<Chưa cấp số>"}, "R", True), ({"InvNo": "  "}, "R", False),
			({"PublishStatus": 0}, "R", True), ({"TotalAmount": 0}, "R", True), ({"EInvoiceStatus": "1"}, "R", True),
			({"InvSeries": "1C26TAA"}, "R", True), ({"TransactionID": "TX1"}, "R", True), ({"InvoiceCode": "M1"}, "R", True),
			({"IsInvoiceDeleted": True}, "R", True), ({"IsInvoiceDeleted": "true"}, "R", False),
		):
			with self.subTest(raw=raw, ref=ref):
				self.assertIs(H.co_ban_ghi_that(raw, ref), mong)

	def test_lay_hd_ds_mau_dinh_danh(self):
		for muc, ham in (("doc_phan_hoi_lay_hd", H.doc_phan_hoi_lay_hd), ("doc_phan_hoi_ds", H.doc_phan_hoi_ds),
				("doc_phan_hoi_mau", H.doc_phan_hoi_mau)):
			for ca in VANG[muc]:
				with self.subTest(muc=muc, ten=ca["ten"]):
					self.assertEqual(ham(ca["vao"]["status"], ca["vao"]["text"]), ca["mong"])
		for ca in VANG["tach_dinh_danh"]:
			with self.subTest(ca=ca):
				self.assertEqual(H.tach_dinh_danh(ca["vao"]), ca["mong"])
		for ca in VANG["hang_so"]:
			with self.subTest(ten=ca["ten"]):
				self.assertEqual(getattr(H, ca["ten"]), ca["mong"])


class TestSnapshotKhop(unittest.TestCase):
	"""§5.3 bước 4 (KV-57 phần luật) + §2.9 khớp bốn tầng (KV-11)."""

	def test_dong_snapshot(self):
		for ca in VANG["dong_snapshot"]:
			with self.subTest(ca=ca["vao"]):
				self.assertEqual(H.dong_snapshot(ca["vao"]), ca["mong"])

	def test_chi_muc(self):
		cm = H.lap_chi_muc(VANG["khop_so"])
		for k, cap in VANG["khop_chi_muc"].items():
			with self.subTest(chi_muc=k):
				self.assertEqual([[a, b] for a, b in cm[k].items()], cap)

	def test_khop(self):
		so = VANG["khop_so"]
		cm = H.lap_chi_muc(so)
		theo_id = {r["id"]: r for r in so}
		for ca in VANG["khop"]:
			with self.subTest(ten=ca["ten"]):
				hit = H.khop_mot(ca["vao"], cm)
				self.assertEqual(list(hit) if hit else None, ca["mong"]["hit"])
				self.assertEqual(list(H.quyet_ket_qua_khop(ca["vao"], hit, theo_id)), ca["mong"]["ket_qua"])

	def test_canh_bao_noi_tay(self):
		"""KV-44 phần luật — cảnh báo khi nối tay (không chặn), so qua chuẩn hoá."""
		for ca in VANG["canh_bao_noi_tay"]:
			with self.subTest(ca=ca["vao"]):
				self.assertEqual(list(H.canh_bao_noi_tay(*ca["vao"])), ca["mong"])

	def test_trung_so(self):
		"""[ĐX §1.6 — KV-36] trùng sau chuẩn hoá: cùng số chuẩn hoá ∧ (cùng ký hiệu chặt ∨ một bên trống)."""
		self.assertTrue(H.trung_so("", "123", "1C26TAA", "00000123"))
		self.assertTrue(H.trung_so("1C26TAA", "00000123", "1C26TAA", "00000123"))
		self.assertTrue(H.trung_so(" 1c26 taa", "123", "1C26TAA", "0123"))
		self.assertTrue(H.trung_so(None, "7", None, "07"))
		self.assertFalse(H.trung_so("2C26TAA", "123", "1C26TAA", "00000123"))
		self.assertFalse(H.trung_so("1C26TAA", "124", "1C26TAA", "00000123"))
		self.assertFalse(H.trung_so("", "", "", ""))
		self.assertEqual(H.ghi_chu_trung_so("00000123", "E7"), "Số HĐĐT 00000123 trùng (sau chuẩn hoá) với hoá đơn E7 — cần kiểm tra.")

	def test_ngay_date_cua_frappe(self):
		"""Cột Date của Frappe trả `datetime.date` — khớp tầng 4 như chuỗi 'YYYY-MM-DD'."""
		so = [{"id": "a", "mst": "0301175691", "ngay": datetime.date(2026, 11, 10), "tong_tien": 55000.0}]
		snap = {"ref_id": "z", "mst_nguoi_mua": "0301175691", "ngay_phat_hanh": datetime.date(2026, 11, 10), "tong_tien": 55000}
		self.assertEqual(H.khop_mot(snap, H.lap_chi_muc(so))[:3], ("a", "tax_date_amount", "review"))
		# co_tong_tien = 0: tong_tien 0 của Frappe là "MISA không trả tổng" — không vào tầng 4, không so tiền (§5.4).
		so = [{"id": "a", "mst": "0301175691", "ngay": "2026-11-10", "tong_tien": 0, "misa_ref_id": "R"}]
		cm, theo_id = H.lap_chi_muc(so), {"a": so[0]}
		khong_tong = {"ref_id": "z", "mst_nguoi_mua": "0301175691", "ngay_phat_hanh": "2026-11-10", "tong_tien": 0, "co_tong_tien": 0}
		self.assertIsNone(H.khop_mot(khong_tong, cm))
		self.assertEqual(H.khop_mot({**khong_tong, "co_tong_tien": 1}, cm)[:2], ("a", "tax_date_amount"))
		so[0]["tong_tien"] = 5000
		self.assertEqual(H.quyet_ket_qua_khop({"ref_id": "R", "tong_tien": 0, "co_tong_tien": 0}, ("a", "ref_id", "certain", None), theo_id),
			("matched", None))
		self.assertEqual(H.quyet_ket_qua_khop({"ref_id": "R", "tong_tien": 0, "co_tong_tien": 1}, ("a", "ref_id", "certain", None), theo_id),
			("amount_diff", "Lệch tiền — sổ 5.000đ, MISA 0đ."))


@unittest.skipUnless(os.path.isdir(NGUON) and (shutil.which("node") or os.path.exists("/opt/node22/bin/node")),
	"không có portal/nguon hoặc node")
class TestVangKhopBanTs(unittest.TestCase):
	"""Chạy lại bộ sinh trên mã TS hiện có ở portal/nguon — tệp vàng phải trùng (nppsale đổi luật / ai sửa tay tệp vàng là đỏ)."""

	def test_sinh_lai_trung(self):
		node = shutil.which("node") or "/opt/node22/bin/node"
		ra = subprocess.run([node, "--experimental-strip-types", "--no-warnings", BO_SINH, "--in"], capture_output=True, text=True,
			timeout=120, cwd=GOC)
		self.assertEqual(ra.returncode, 0, ra.stderr)
		self.assertEqual(_doc_vang(ra.stdout), VANG)


if __name__ == "__main__":
	unittest.main()
