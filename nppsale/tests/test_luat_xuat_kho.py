"""Chọn lô khi Xuất hàng (thuần): python3 -m unittest nppsale.tests.test_luat_xuat_kho"""
import unittest
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.luat.xuat_kho import Lo, chon_lo, loi_thieu_ton, so6


def lo(ma, ton, han, nhan):
	return Lo(ma=ma, ton=Decimal(ton), han=han, khoa_fifo=(nhan, nhan, ma))


class TestChonLo(unittest.TestCase):
	def kho(self):
		return [lo("CU", 30, "2027-03-01", "2026-10-01"), lo("MOI-HAN-SOM", 50, "2027-01-15", "2026-10-05")]

	def test_fifo_theo_ngay_nhan_va_dem_lo_can_han_bi_bo_qua(self):
		k = chon_lo(self.kho(), 40)
		self.assertEqual(k.lay, [("CU", Decimal(30)), ("MOI-HAN-SOM", Decimal(10))])
		self.assertEqual((k.thieu, k.can_han), (Decimal(0), 1))  # lấy lô CU dù MOI-HAN-SOM hết hạn sớm hơn

	def test_dong_sau_thay_ton_da_bi_dong_truoc_lay(self):
		k = self.kho()
		chon_lo(k, 30)
		k2 = chon_lo(k, 5)
		self.assertEqual((k2.lay, k2.can_han), ([("MOI-HAN-SOM", Decimal(5))], 0))  # hạn sớm nhất tính lại trên lô còn hàng

	def test_thieu(self):
		k = chon_lo(self.kho(), 90)
		self.assertEqual(k.thieu, Decimal(10))

	def test_cau_loi(self):
		self.assertEqual(so6(10), "10.000000")
		with self.assertRaises(NppLoi) as e:
			raise loi_thieu_ton(Decimal(10), "Nuoc ngot", 20)
		self.assertIn("thiếu 10.000000 đơn vị của \"Nuoc ngot\" ở kho bán — còn 20.000000", str(e.exception))
		self.assertTrue(str(loi_thieu_ton(1, "X", 0)).endswith("ghi sổ phiếu xuất sẽ làm tồn kho âm"))


if __name__ == "__main__":
	unittest.main()
