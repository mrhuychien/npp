"""Luật thuần phiếu trả NCC (P4 — M2; đặc tả kho_mua §3.7–§3.9, §7.3 điểm 23 / 26): python3 -m unittest nppsale.tests.test_luat_tra_ncc

Câu lỗi lấy nguyên văn từ kết quả ĐÃ CHẠY trên Postgres tham chiếu (tệp vàng du_lieu/kho_mua_mau.json — V18, V22, V24; đặc tả §6.2 K02 / K06 / K09).
"""
import unittest
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.luat import kho_mua as K
from nppsale.luat import tra_ncc as T


class TestCauLoi(unittest.TestCase):
	def test_thieu_ton_nguyen_van(self):
		# V18 lần 1: M 20 hộp kho date (lô 10 + 5 — đã trừ 15 trong lượt) — "còn" vùng phiếu SAU khi trừ; vùng kia 100
		e = T.loi_thieu_ton("Sữa hộp", "hộp", 20, 1, "date", (True, T.con_sau_lay(15, 15)), "sale", (True, Decimal("100")), ma_hang="SPM")
		self.assertEqual((e.ma, e.code), ("INSUFFICIENT_STOCK | Sữa hộp (hộp): cần 20, kho hàng date còn 0.000000, kho hàng bán còn 100.000000",
			"P0001"))
		# V18 lần 2: N 1,5 thùng ×10, không lô nào ở cả hai kho → "còn 0" (COALESCE của tập rỗng), "cần" theo scale tích
		e = T.loi_thieu_ton("Kẹo", "túi", "1.5", 10, "date", (False, Decimal(0)), "sale", (False, Decimal(0)))
		self.assertEqual(e.ma, "INSUFFICIENT_STOCK | Kẹo (túi): cần 15.0, kho hàng date còn 0, kho hàng bán còn 0")
		# V22: phiếu kho bán — thứ tự vùng theo vùng phiếu
		e = T.loi_thieu_ton("Sữa hộp", "hộp", 10, 1.0, "sale", (True, T.con_sau_lay(7, 7)), "date", (True, Decimal(15)))
		self.assertEqual(e.ma, "INSUFFICIENT_STOCK | Sữa hộp (hộp): cần 10, kho hàng bán còn 0.000000, kho hàng date còn 15.000000")
		# tên / đơn vị thiếu → mã hàng / "đv cơ sở"; hệ số float nguyên của Frappe in như numeric không scale; tích 0,5 × 24 = 12.0
		e = T.loi_thieu_ton(None, None, 0.5, 24.0, "date", (True, Decimal("2.5")), "sale", (False, 0), ma_hang="SPM")
		self.assertEqual(e.ma, "INSUFFICIENT_STOCK | SPM (đv cơ sở): cần 12.0, kho hàng date còn 2.500000, kho hàng bán còn 0")
		self.assertEqual(e.ma.split("|")[0], "INSUFFICIENT_STOCK ")  # giao diện tách theo dấu `|` (friendlyReturnError)

	def test_cau_trang_thai_va_khac(self):
		self.assertEqual(T.loi_khong_con_nhap("cancelled").ma,
			'PHIEU_KHONG_CON_NHAP: Phiếu đang ở trạng thái "cancelled" — chỉ phiếu nháp mới gửi được.')
		self.assertEqual(T.KHONG_TON_TAI, "PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu trả NCC này.")
		self.assertEqual(T.KHONG_CO_HANG, "PHIEU_KHONG_CO_HANG: Phiếu chưa có dòng hàng nào.")
		# DA_CAN_TRU: % = payables.paid thô (numeric) — đặc tả §3.8 bước 6 "(-30000)"
		self.assertEqual(T.loi_da_can_tru(-30000.0).ma,
			"DA_CAN_TRU: Khoản giảm công nợ của phiếu này đã được cấn trừ (-30000). Gỡ phần cấn trừ trước rồi mới huỷ phiếu.")
		self.assertEqual(T.loi_da_can_tru(Decimal("-1234.50")).ma.split("(")[1].split(")")[0], "-1234.50")
		# vai — cùng bảng cửa vai của P4 (RPC mới `sua_phieu_tra_ncc` dùng câu kho / mua hàng, không cửa gọi nội bộ)
		self.assertEqual(K.loi_vai("sua_phieu_tra_ncc", "sales").ma, "FORBIDDEN: vai trò của bạn không được làm thao tác kho / mua hàng này.")
		self.assertEqual(K.loi_vai("sua_phieu_tra_ncc", "sales", noi_bo=True).code, "42501")
		self.assertIsNone(K.loi_vai("sua_phieu_tra_ncc", "warehouse"))
		self.assertIsNone(K.loi_vai("complete_supplier_return", "sales", noi_bo=True))  # cửa npp.via_rpc của hàm nppsale

	def test_vung(self):
		self.assertEqual((T.vung_kia("sale"), T.vung_kia("date"), T.vung_kia(None)), ("date", "sale", "sale"))
		self.assertEqual((T.ten_vung("date"), T.ten_vung("sale"), T.ten_vung(None)), ("hàng date", "hàng bán", "hàng bán"))
		self.assertEqual((T.con_in(True, 0), T.con_in(False, 0), T.con_in(True, Decimal("15"))), ("0.000000", "0", "15.000000"))

	def test_ket_qua_khoi_phuc(self):
		self.assertEqual(T.ket_qua_khoi_phuc("PTNCC-0001-1", "completed", True), {"id": "PTNCC-0001-1", "trang_thai": "completed",
			"da_khoi_phuc": True})
		self.assertEqual(T.ket_qua_khoi_phuc("PTNCC-0001", "draft", False), {"id": "PTNCC-0001", "trang_thai": "draft", "da_khoi_phuc": False})
		kq = T.ket_qua_khoi_phuc("X", "draft", True, "INSUFFICIENT_STOCK | …")
		self.assertEqual(set(kq), {"id", "trang_thai", "da_khoi_phuc", "ly_do"})  # không có so_lo (khác phiếu nhập)


class TestDongCong(unittest.TestCase):
	def _loi(self, dong) -> str | None:
		try:
			T.kiem_dong_tra(dong)
		except NppLoi as e:
			return e.ma
		return None

	def test_thu_tu_kiem_tung_dong(self):
		self.assertIsNone(self._loi([(1, 1, 1000, 0), ("0.5", 24, 240000, 10000), (2, None, 5000, 0)]))
		self.assertEqual(self._loi([(2, 1, 1000, 0), (0, 1, 1000, 0)]), "SO_LUONG_KHONG_HOP_LE: Dòng 2 có số lượng không lớn hơn 0.")
		self.assertEqual(self._loi([(-1, 1, 1000, 0)]), "SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0.")
		self.assertEqual(self._loi([(1, 0, 1000, 0)]), "SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0.")  # hệ số 0
		self.assertEqual(self._loi([(1, 1, -1, 0)]), "GIA_KHONG_HOP_LE: Dòng 1 có giá / giảm giá âm.")
		self.assertEqual(self._loi([(1, 1, 1000, -5)]), "GIA_KHONG_HOP_LE: Dòng 1 có giá / giảm giá âm.")
		self.assertEqual(self._loi([(1, 1, 10000, 25000)]), "GIA_KHONG_HOP_LE: Dòng 1 có giảm giá lớn hơn tiền hàng.")
		tien0 = "GIA_KHONG_HOP_LE: Dòng {} có tiền hàng bằng 0 — phiếu trả NCC phải có tiền trả lớn hơn 0."
		self.assertEqual(self._loi([(1, 1, 0, 0)]), tien0.format(1))
		self.assertEqual(self._loi([(1, 1, 1000, 0), (2, 1, 1000, 2000)]), tien0.format(2))
		# một dòng nhiều lỗi: SL trước giá trước tiền (thứ tự kiểm của sua_phieu_nhap bước 10)
		self.assertEqual(self._loi([(0, 1, -1, 5)]), "SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0.")
		self.assertEqual(self._loi([(1, 1, -1, 5)]), "GIA_KHONG_HOP_LE: Dòng 1 có giá / giảm giá âm.")

	def test_tien_phieu_tra_dao_dau(self):
		"""Bảng thuế tờ trả NCC (§2.4): thuế gõ tay −max(0, x); chi phí trả hàng Add +min(giảm, |tiền + thuế|) → grand_total = −max(0, …) = nợ nppsale."""
		self.assertEqual(K.thue_go_tay_pi(-500, la_tra=True), Decimal(0))
		self.assertEqual(K.thue_go_tay_pi(1000, la_tra=True), Decimal(-1000))
		self.assertEqual(K.giam_dau_phieu_pi(-120000, -11800, 1000, la_tra=True), ("Add", Decimal(1000)))
		self.assertEqual(K.giam_dau_phieu_pi(-10000, -1000, 999999, la_tra=True), ("Add", Decimal(11000)))  # V26 R3: tổng kẹp 0
		self.assertEqual(K.tong_pi(-120000, -11800, 1000, la_tra=True), Decimal(-130800))  # V17
		tp = K.tien_phieu([(Decimal("0.5"), 240000, 10000, Decimal("0.1")), (2, 5000, 0, Decimal("0.08"))], giam=1000)
		self.assertEqual((tp.tien_hang, tp.thue, tp.tong, K.no_ncc(tp, la_tra=True)), (Decimal(120000), Decimal("11800.0"), Decimal("130800.0"),
			Decimal("-130800.0")))


if __name__ == "__main__":
	unittest.main()
