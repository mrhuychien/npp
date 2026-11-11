"""Áp lọc / sắp / đếm / phân trang lên kết quả RPC (nppsale.cong.sau_ham) — thuần Python, không cần site.
Chạy: python3 -m unittest nppsale.tests.test_sau_ham (từ gốc repo)."""
import datetime as dt
import unittest
from decimal import Decimal

from nppsale.cong.sau_ham import ap
from nppsale.cong.sql import LoiCong

DONG = [
	{"product_id": "p3", "committed_base": Decimal("5"), "ngay": dt.date(2026, 11, 3), "ten": "Bia"},
	{"product_id": "p1", "committed_base": Decimal("0"), "ngay": None, "ten": "bánh"},
	{"product_id": "p2", "committed_base": None, "ngay": dt.date(2026, 11, 1), "ten": "Bột"},
]


class TestSauHam(unittest.TestCase):
	def test_khong_sau_tra_nguyen(self):
		self.assertEqual(ap(DONG, None), (DONG, None))

	def test_sap_dem_phan_trang_chon_cot(self):
		data, dem = ap(DONG, {"select": "product_id, committed_base", "thu_tu": [{"cot": "product_id"}], "range": [0, 1], "count": "exact"})
		self.assertEqual(dem, 3)
		self.assertEqual(data, [{"product_id": "p1", "committed_base": Decimal("0")}, {"product_id": "p2", "committed_base": None}])

	def test_null_trong_so_sanh_bi_loai_ke_ca_khi_phu_dinh(self):
		data, _ = ap(DONG, {"loc": [{"op": "gt", "cot": "committed_base", "gt": "0"}]})
		self.assertEqual([d["product_id"] for d in data], ["p3"])
		data, _ = ap(DONG, {"loc": [{"op": "not", "cot": "committed_base", "op_con": "eq", "gt": "0"}]})
		self.assertEqual([d["product_id"] for d in data], ["p3"])  # NULL không qua NOT

	def test_is_null_va_or(self):
		data, _ = ap(DONG, {"loc": [{"op": "or", "bieu_thuc": "ngay.is.null,ten.ilike.bi*"}]})
		self.assertEqual(sorted(d["product_id"] for d in data), ["p1", "p3"])

	def test_ngay_so_voi_chuoi_va_in(self):
		data, _ = ap(DONG, {"loc": [{"op": "gte", "cot": "ngay", "gt": "2026-11-02"}]})
		self.assertEqual([d["product_id"] for d in data], ["p3"])
		data, _ = ap(DONG, {"loc": [{"op": "in", "cot": "product_id", "gt": ["p1", "p2"]}]})
		self.assertEqual(sorted(d["product_id"] for d in data), ["p1", "p2"])

	def test_sap_giam_null_dau(self):
		data, _ = ap(DONG, {"thu_tu": [{"cot": "committed_base", "tang": False}]})
		self.assertEqual([d["product_id"] for d in data], ["p2", "p3", "p1"])

	def test_head_chi_dem(self):
		self.assertEqual(ap(DONG, {"count": "exact", "head": True}), (None, 3))

	def test_loc_bang_long_bi_tu_choi(self):
		with self.assertRaises(LoiCong):
			ap(DONG, {"loc": [{"op": "eq", "cot": "customers.channel", "gt": "MT"}]})


if __name__ == "__main__":
	unittest.main()
