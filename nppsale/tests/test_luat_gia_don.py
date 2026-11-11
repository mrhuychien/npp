"""Luật giá / giảm giá đơn (thuần, không cần site): python3 -m unittest nppsale.tests.test_luat_gia_don

Toàn bộ luật đã so với hàm + trigger thật của nppsale ở tests/test_tao_don.py (96 tình huống); ở đây giữ các mép số học dễ vỡ khi sửa:
làm tròn nửa xa số 0 như numeric của Postgres, định dạng số / phần trăm trong câu lỗi, thuế dòng hợp lệ, ngưỡng sai số giảm đơn."""
import unittest

from nppsale.cong.loi import NppLoi
from nppsale.luat import gia_don as L


class TestSoHoc(unittest.TestCase):
	def test_lam_tron_nua_xa_so_0(self):
		self.assertEqual([L.lam_tron(x) for x in (2.5, 3.5, -2.5, 0.49999, 10455.5)], [3, 4, -3, 0, 10456])

	def test_dinh_dang_cau_loi(self):
		self.assertEqual(L.so_vn(1234567.5), "1.234.568")
		self.assertEqual(L.so_vn(-9500), "-9.500")
		self.assertEqual((L.phan_tram_vn(12.5), L.phan_tram_vn(10.0), L.phan_tram_vn(0)), ("12,5", "10", "0"))
		self.assertEqual(L.nhan_tran_giam("vnd", 20000), "tối đa 20.000đ")
		self.assertEqual(L.nhan_tran_giam("pct", 5), "tối đa 5%")

	def test_thue_hop_le(self):
		self.assertEqual([L.thue_hop_le(x) for x in ("0.08", 0.1, "1", 0, "0.12345")], [0.08, 0.1, 1.0, 0.0, 0.1235])
		self.assertEqual([L.thue_hop_le(x) for x in (8, "-0.1", "abc", "", None, True, " 0.1 x")], [None] * 7)


class TestQuyenGiam(unittest.TestCase):
	def test_vai(self):
		self.assertTrue(L.quyen_giam({"vai": "owner"}).toan_quyen)
		self.assertTrue(L.quyen_giam({"vai": "accountant"}).toan_quyen)
		self.assertTrue(L.quyen_giam(None).toan_quyen)  # không phải NV (việc nền) — như auth.uid() NULL
		q = L.quyen_giam({"vai": "sales", "tran_tang_gia": 15})
		self.assertEqual((q.toan_quyen, q.nang_gia_pct), (False, 0.0))  # NVBH không cờ sửa giá: trần nâng = 0
		self.assertEqual(L.quyen_giam({"vai": "manager", "tran_tang_gia": 10}).nang_gia_pct, 10.0)
		q = L.quyen_giam({"vai": "sales", "cho_giam_gia": 1, "kieu_tran_giam": "vnd", "co_tran_giam": 1, "tran_giam": 20000})
		self.assertEqual((q.duoc_giam, q.loai_tran, q.tran), (True, "vnd", 20000.0))


class TestDong(unittest.TestCase):
	nv = L.QuyenGiam(toan_quyen=False)

	def test_sai_so_lam_tron(self):
		L.kiem_dong(1, 9499, 0, q=self.nv, gia_bang=9500)  # giảm 1 ≤ 1,5
		L.kiem_dong(2, 9499, 0, q=self.nv, gia_bang=9500)  # giảm 2 ≤ 2
		with self.assertRaisesRegex(NppLoi, "^DISCOUNT_NOT_ALLOWED"):
			L.kiem_dong(1, 9498, 0, q=self.nv, gia_bang=9500)

	def test_tran_gia_sau_khi_cong_giam_dong(self):
		with self.assertRaisesRegex(NppLoi, r"^PRICE_OVER_CEILING: Đơn giá 10\.100 vượt mức tối đa 9\.500"):
			L.kiem_dong(1, 9500, 600, q=self.nv, gia_bang=9500)

	def test_sua_dong_giu_gia_cu_khong_bi_chan(self):
		L.kiem_dong(1, 9600, 0, q=self.nv, gia_bang=9500, cu={"sl": 1, "gia": 9600, "giam_dong": 0})

	def test_chua_co_gia_bang_khong_kiem(self):
		L.kiem_dong(3, 1, 0, q=self.nv, gia_bang=0)

	def test_du_lieu_hong(self):
		for sl, gia, giam in ((0, 1, 0), (-1, 1, 0), (1, -1, 0), (1, 1, -1)):
			with self.assertRaisesRegex(NppLoi, "^BAD_PAYLOAD"):
				L.kiem_dong(sl, gia, giam, q=L.QuyenGiam(toan_quyen=True), gia_bang=0)


class TestGiamDon(unittest.TestCase):
	def test_nguong_sai_so(self):
		self.assertEqual(L.giam_don_hien_tai([(2, 9500), (1, 5000)], 23998), 0)  # 2 ≤ max(1, 2 dòng)
		self.assertEqual(L.giam_don_hien_tai([(2, 9500), (1, 5000)], 23997), 3)
		self.assertEqual(L.giam_don_hien_tai([(0, 9500), (1, 5000)], 4000), 1000)  # dòng SL 0 không tính

	def test_tran_tinh_tren_tien_truoc_giam_dong(self):
		q = L.QuyenGiam(toan_quyen=False, duoc_giam=True, loai_tran="pct", tran=5)
		L.kiem_giam_don(4752, q=q, goc=0, dong=[(10, 9400, 1000)])  # nền 95.000 → 4.750 + 1 dòng + 1
		with self.assertRaisesRegex(NppLoi, r"^DISCOUNT_OVER_LIMIT: Giảm giá đơn vượt mức cho phép \(tối đa 5%\)\."):
			L.kiem_giam_don(4753, q=q, goc=0, dong=[(10, 9400, 1000)])

	def test_chi_kiem_khi_tang(self):
		L.kiem_giam_don(5000, q=L.QuyenGiam(toan_quyen=False), goc=5000, dong=[(1, 10000, 0)])


if __name__ == "__main__":
	unittest.main()
