"""Chuẩn hoá SĐT (nppsale.luat.sdt) — cùng kết quả với normalizePhone (TS) và normalize_phone (SQL mig 104) của nppsale.
Bộ ca dùng chung của nppsale (portal/nguon/tests/fixtures/phone-cases.json) chạy khi có nguon/; thêm vài ca ghim tại chỗ."""
import json
import os
import unittest

from nppsale.luat.sdt import chuan_hoa_sdt, email_ky_thuat, sdt_hop_le

BO_CA = os.path.join(os.path.dirname(__file__), "..", "..", "portal", "nguon", "tests", "fixtures", "phone-cases.json")


class TestSdt(unittest.TestCase):
	def test_ca_ghim(self):
		for vao, ra in [("0909 123 456", "0909123456"), ("+84 909 123 456", "0909123456"), ("0084909123456", "0909123456"),
				("909123456", "0909123456"), ("84909123456", "0909123456"), ("", ""), (None, ""), ("abc", ""), ("0243.826.1234", "02438261234")]:
			self.assertEqual(chuan_hoa_sdt(vao), ra, vao)
		self.assertTrue(sdt_hop_le("+84 909 123 456"))
		self.assertFalse(sdt_hop_le("12345"))
		self.assertEqual(email_ky_thuat("0909.123.456"), "0909123456@nppsale.local")
		with self.assertRaises(ValueError):
			email_ky_thuat("  ")

	@unittest.skipUnless(os.path.exists(BO_CA), "chưa có portal/nguon (bộ ca dùng chung của nppsale)")
	def test_bo_ca_dung_chung_cua_nppsale(self):
		d = json.load(open(BO_CA, encoding="utf-8"))
		for ca in d["normalize"]:
			self.assertEqual(chuan_hoa_sdt(ca["in"]), ca["out"], ca)
		for ca in d["valid"]:
			self.assertEqual(sdt_hop_le(ca["in"]), ca["out"], ca)


if __name__ == "__main__":
	unittest.main()


class TestSdtKhach(unittest.TestCase):
	"""SĐT khách (chuanHoaSdt / sdtDeLuu / sdtTimChinhXac) — mẫu sinh bằng chính hàm TS (vite-node, du_lieu/sdt_khach_mau.json)."""

	def test_mau_ts(self):
		from nppsale.luat.sdt import chuan_hoa_sdt_khach, sdt_khach_de_luu, sdt_khach_tim_chinh_xac

		mau = json.load(open(os.path.join(os.path.dirname(__file__), "du_lieu", "sdt_khach_mau.json"), encoding="utf-8"))
		self.assertGreater(len(mau), 10)
		for m in mau:
			self.assertEqual(chuan_hoa_sdt_khach(m["v"]), m["chuan"], m)
			self.assertEqual(sdt_khach_de_luu(m["v"]), m["luu"], m)
			self.assertEqual(sdt_khach_tim_chinh_xac(m["v"]), m["tim"], m)
