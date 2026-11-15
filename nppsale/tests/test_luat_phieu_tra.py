"""Luật thuần phiếu trả (nppsale.luat.phieu_tra) — kỳ vọng đối chiếu trên Postgres tham chiếu (round numeric nửa xa số 0, to_char /
trim_scale của câu lỗi) và định nghĩa trigger đang chạy: _chot_gia_tran_dong_tra (mig 230), _ngay_tru_doanh_so (mig 192),
sync_return_credited_at (mig 188), _nguoi_cua_phieu_tra + guard_return_sales_user (mig 160 / 194), sync_return_credit_amount.

	python3 -m unittest nppsale.tests.test_luat_phieu_tra
"""
import datetime as dt
import unittest

from nppsale.cong.loi import NppLoi
from nppsale.luat.gia_don import QuyenGiam, quyen_giam
from nppsale.luat.phieu_tra import (
	dien_nguoi_mac_dinh,
	kiem_gia_tra,
	kiem_nguoi_dung_ten,
	moc_ghi_co,
	ngay_tru_doanh_so,
	nguoi_dung_ten,
	thanh_tien,
	tien_tra,
)

D = dt.date


class TestThanhTien(unittest.TestCase):
	def test_lam_tron_nhu_postgres(self):
		# SELECT round(3 * 12345.67 * 1.08), round(10.5), round(1.5), round(2 * 8333.335 * 1.1) → 40000, 11, 2, 18333
		self.assertEqual(thanh_tien(3, 12345.67, 0.08), 40000)
		self.assertEqual(thanh_tien(1, 10.5, 0), 11)  # Python round() ra 10 (làm tròn ngân hàng)
		self.assertEqual(thanh_tien(3, 0.5, None), 2)
		self.assertEqual(thanh_tien(2, 8333.335, 0.1), 18333)

	def test_tien_tra_bo_hang_doi_khong_dong_la_0(self):
		dong = [{"sl": 2, "gia": 10000, "thue": 0.08}, {"sl": 1, "gia": 5000, "thue": 0.1, "doi": True}, {"thanh_tien": 7, "doi": False}]
		self.assertEqual(tien_tra(dong), 21600 + 7)
		self.assertEqual(tien_tra([]), 0)  # sync_return_credit_amount: COALESCE(SUM, 0) — xoá hết dòng thì về 0
		self.assertEqual(tien_tra([{"sl": 1, "gia": 9, "thue": 0, "doi": True}]), 0)


class TestTranGiaTra(unittest.TestCase):
	NV = quyen_giam({"vai": "sales", "cho_sua_gia": True, "tran_tang_gia": 10})

	def test_tran_va_dung_sai_1d(self):
		kiem_gia_tra(11000, q=self.NV, gia_tham_chieu=10000)
		kiem_gia_tra(11001, q=self.NV, gia_tham_chieu=10000)  # ≤ trần + 1
		with self.assertRaises(NppLoi) as e:
			kiem_gia_tra(11002.6, q=self.NV, gia_tham_chieu=10000)
		self.assertEqual(str(e.exception), "RETURN_PRICE_OVER_CEILING: Giá trả 11.003 vượt mức tối đa 11.000 (giá tham chiếu 10.000, được nâng 10%).")

	def test_phan_tram_la_phan_tram_khong_phai_he_so(self):
		"""round(ref × (1 + pct / 100)) — 12,5 % trên 10.000 → 11.250 (SELECT round(10000 * (1 + 12.5/100)))."""
		q = quyen_giam({"vai": "manager", "tran_tang_gia": 12.5})
		kiem_gia_tra(11251, q=q, gia_tham_chieu=10000)
		with self.assertRaises(NppLoi) as e:
			kiem_gia_tra(11252, q=q, gia_tham_chieu=10000)
		self.assertIn("vượt mức tối đa 11.250 (giá tham chiếu 10.000, được nâng 12,5%)", str(e.exception))

	def test_nvbh_chua_duoc_sua_gia_la_0_phan_tram(self):
		q = quyen_giam({"vai": "sales", "cho_sua_gia": False, "tran_tang_gia": 50})
		kiem_gia_tra(10001, q=q, gia_tham_chieu=10000)
		with self.assertRaises(NppLoi):
			kiem_gia_tra(10002, q=q, gia_tham_chieu=10000)

	def test_cho_qua(self):
		for q in (quyen_giam({"vai": "owner"}), quyen_giam({"vai": "accountant"}), quyen_giam(None)):  # None = việc nền (auth.uid() NULL)
			kiem_gia_tra(10 ** 9, q=q, gia_tham_chieu=10000)
		kiem_gia_tra(10 ** 9, q=self.NV, gia_tham_chieu=10000, la_doi=True)  # hàng đổi
		kiem_gia_tra(10 ** 9, q=self.NV, gia_tham_chieu=0)  # tham chiếu 0 / không có giá
		kiem_gia_tra(10 ** 9, q=self.NV, gia_tham_chieu=None)
		kiem_gia_tra(50001, q=self.NV, gia_tham_chieu=10000, gia_cu=50000)  # sửa dòng giữ hàng + đơn vị, không nâng quá 1 đ
		with self.assertRaises(NppLoi):
			kiem_gia_tra(50002, q=self.NV, gia_tham_chieu=10000, gia_cu=50000)
		self.assertTrue(isinstance(self.NV, QuyenGiam))


class TestNgayVaMoc(unittest.TestCase):
	def test_ngay_tru_doanh_so(self):
		kw = {"ngay_hd_ghi_so": D(2026, 10, 1), "ngay_ghi_co": D(2026, 10, 5), "ngay_tra": D(2026, 10, 4), "ngay_tao": D(2026, 10, 3)}
		self.assertEqual(ngay_tru_doanh_so(tu_sinh=True, trang_thai="submitted", **kw), D(2026, 10, 1))  # trừ ngay lúc xuất, kể cả Chờ xử lý
		self.assertEqual(ngay_tru_doanh_so(tu_sinh=True, trang_thai="completed", **kw), D(2026, 10, 1))
		self.assertIsNone(ngay_tru_doanh_so(tu_sinh=True, trang_thai="completed", **{**kw, "ngay_hd_ghi_so": None}))  # HĐ huỷ
		self.assertIsNone(ngay_tru_doanh_so(tu_sinh=True, trang_thai="draft", **kw))
		self.assertEqual(ngay_tru_doanh_so(tu_sinh=False, trang_thai="completed", **kw), D(2026, 10, 5))  # tự lập: ngày ghi có
		self.assertEqual(ngay_tru_doanh_so(tu_sinh=False, trang_thai="completed", **{**kw, "ngay_ghi_co": None}), D(2026, 10, 4))
		self.assertEqual(ngay_tru_doanh_so(tu_sinh=False, trang_thai="completed", **{**kw, "ngay_ghi_co": None, "ngay_tra": None}),
			D(2026, 10, 3))
		for tt in ("draft", "submitted", "cancelled"):
			self.assertIsNone(ngay_tru_doanh_so(tu_sinh=False, trang_thai=tt, **kw))

	def test_moc_ghi_co(self):
		bay_gio, hom_nay = dt.datetime(2026, 10, 9, 15, 30), D(2026, 10, 9)
		kw = {"bay_gio": bay_gio, "hom_nay": hom_nay}
		self.assertEqual(moc_ghi_co(trang_thai="completed", ngay_tra=hom_nay, moc_cu=None, doi_ngay=False, **kw), bay_gio)
		self.assertEqual(moc_ghi_co(trang_thai="completed", ngay_tra=None, moc_cu=None, doi_ngay=False, **kw), bay_gio)
		self.assertEqual(moc_ghi_co(trang_thai="completed", ngay_tra=D(2026, 10, 2), moc_cu=None, doi_ngay=False, **kw),
			dt.datetime(2026, 10, 2, 12, 0))
		cu = dt.datetime(2026, 10, 2, 12, 0)
		self.assertEqual(moc_ghi_co(trang_thai="completed", ngay_tra=D(2026, 10, 2), moc_cu=cu, doi_ngay=False, **kw), cu)  # sửa ghi chú
		self.assertEqual(moc_ghi_co(trang_thai="completed", ngay_tra=D(2026, 10, 6), moc_cu=cu, doi_ngay=True, **kw),
			dt.datetime(2026, 10, 6, 12, 0))
		for tt in ("draft", "submitted", "cancelled"):
			self.assertIsNone(moc_ghi_co(trang_thai=tt, ngay_tra=hom_nay, moc_cu=cu, doi_ngay=False, **kw))


class TestNguoiDungTen(unittest.TestCase):
	def test_chuoi_dien(self):
		self.assertEqual(nguoi_dung_ten(nv_hd="A", hien_tai="B", nv_don="C", nv_hd_gan_nhat="D"), "A")
		self.assertEqual(nguoi_dung_ten(nv_hd=None, hien_tai="B", nv_don="C", nv_hd_gan_nhat="D"), "B")
		self.assertEqual(nguoi_dung_ten(nv_hd=None, hien_tai=None, nv_don="C", nv_hd_gan_nhat="D"), "C")
		self.assertEqual(nguoi_dung_ten(nv_hd=None, hien_tai=None, nv_don=None, nv_hd_gan_nhat="D"), "D")
		self.assertEqual(dien_nguoi_mac_dinh(nv_don="C", nguoi_goi="X", vai_nguoi_goi="sales"), "C")
		self.assertEqual(dien_nguoi_mac_dinh(nv_don=None, nguoi_goi="X", vai_nguoi_goi="manager"), "X")
		self.assertIsNone(dien_nguoi_mac_dinh(nv_don=None, nguoi_goi="X", vai_nguoi_goi="warehouse"))
		self.assertIsNone(dien_nguoi_mac_dinh(nv_don=None, nguoi_goi=None, vai_nguoi_goi=None))

	def test_kiem_gan_nguoi(self):
		kw = {"qua_rpc": False, "cung_npp": True}
		kiem_nguoi_dung_ten(nv="X", nguoi_goi="X", vai_nguoi_goi="sales", vai_nv="sales", **kw)  # chính mình
		kiem_nguoi_dung_ten(nv="Y", nguoi_goi="X", vai_nguoi_goi="sales", vai_nv="warehouse", qua_rpc=True, cung_npp=True)  # RPC miễn
		kiem_nguoi_dung_ten(nv="Y", nguoi_goi=None, vai_nguoi_goi=None, vai_nv="sales", **kw)  # việc nền
		with self.assertRaises(NppLoi) as e:
			kiem_nguoi_dung_ten(nv="Y", nguoi_goi="X", vai_nguoi_goi="sales", vai_nv="sales", **kw)
		self.assertTrue(str(e.exception).startswith("PHIEU_TRA_HO_KHONG_DUOC_PHEP:"))
		with self.assertRaises(NppLoi) as e:
			kiem_nguoi_dung_ten(nv="Y", nguoi_goi="X", vai_nguoi_goi="manager", vai_nv=None, **kw)
		self.assertTrue(str(e.exception).startswith("NHAN_VIEN_KHONG_HOP_LE:"))
		with self.assertRaises(NppLoi) as e:
			kiem_nguoi_dung_ten(nv="Y", nguoi_goi="X", vai_nguoi_goi="owner", vai_nv="warehouse", **kw)
		self.assertEqual(str(e.exception), "NHAN_VIEN_KHONG_BAN_HANG: warehouse không phải vai trò bán hàng, không đứng tên phiếu trả được.")
		kiem_nguoi_dung_ten(nv="Y", nguoi_goi="X", vai_nguoi_goi="manager", vai_nv="sales", **kw)


if __name__ == "__main__":
	unittest.main()
