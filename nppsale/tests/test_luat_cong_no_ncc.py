"""Luật thuần CÔNG NỢ + TIỀN NCC (P4 — M3; đặc tả kho_mua §2.8, §3.10–§3.12, §4.4, §7.3 điểm 10 / 13 / 38): python3 -m unittest
nppsale.tests.test_luat_cong_no_ncc

Câu lỗi lấy nguyên văn từ thân hàm / trigger nppsale (scratchpad kho_mua/src: record_payable_payment.sql, chi_tra_ncc.sql, huy_phieu_chi_ncc.sql,
cancel_purchase_invoice.sql, _khoa_ghi_thang_no_ncc.sql, _khoa_ghi_thang_chi_ncc.sql) và kết quả ĐÃ CHẠY của tệp vàng (V29–V38).
"""
import unittest
from datetime import date, datetime
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong
from nppsale.luat import cong_no_ncc as L


class TestCauLoi(unittest.TestCase):
	def test_cau_nguyen_van(self):
		self.assertEqual(L.KHOA_THEM, "NO_NCC_KHOA: màn hình chỉ thêm được khoản nợ NCC chưa trả — trả tiền đi qua nút Ghi trả NCC")
		self.assertEqual(L.KHOA_SUA, "NO_NCC_KHOA: số nợ / số đã trả NCC chỉ đổi qua phiếu nhập, phiếu trả NCC, Ghi trả NCC (RPC)")
		self.assertEqual(L.KHOA_XOA, "NO_NCC_KHOA: chỉ xoá được khoản nợ NCC chưa trả đồng nào (không có phiếu chi)")
		self.assertEqual(L.CHI_NCC_KHOA, "CHI_NCC_KHOA: tiền trả NCC chỉ ghi qua nút Ghi trả NCC (RPC record_payable_payment)")
		# hai câu BAD_AMOUNT khác nhau một chữ hoa (record_payable_payment / chi_tra_ncc)
		self.assertEqual(L.BAD_AMOUNT_TRA, "BAD_AMOUNT: số tiền phải lớn hơn 0.")
		self.assertEqual(L.BAD_AMOUNT_CHI, "BAD_AMOUNT: Số tiền chi phải lớn hơn 0.")
		self.assertEqual(L.BAD_METHOD, "BAD_METHOD: Hình thức chi chỉ là tiền mặt hoặc chuyển khoản.")
		self.assertEqual(L.NCC_KHONG_HOP_LE, "NCC_KHONG_HOP_LE: Nhà cung cấp không thuộc đơn vị của bạn.")
		self.assertEqual(L.NGAY_TUONG_LAI_CHI, "NGAY_TUONG_LAI: Ngày chi không được sau hôm nay.")
		self.assertEqual(L.PAYABLE_NOT_FOUND, "PAYABLE_NOT_FOUND: không tìm thấy khoản công nợ NCC này.")
		self.assertEqual(L.PHIEU_CHI_KHONG_TON_TAI, "PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu chi này.")
		self.assertEqual(L.BU_TRU_KHONG_CON, "BU_TRU_KHONG_CON: NCC không còn khoản giảm để bù trừ.")

	def test_overpay_in_so_tho(self):
		# V36: còn = amount − paid in như numeric thô — số nguyên đồng của Frappe (float) không thêm `.0`; dòng âm / dòng trả trước luôn rơi vào đây
		for con, chu in ((Decimal(200000), "200000"), (200000.0, "200000"), (0.0, "0"), (Decimal(-30000), "-30000"), (-250000.0, "-250000"),
				(Decimal("13332.60"), "13332.60")):
			e = L.loi_overpay(con)
			self.assertEqual((e.ma, e.code), (f"OVERPAY: số tiền vượt quá công nợ còn lại (còn {chu}).", "P0001"))

	def test_da_tra_tien(self):
		self.assertEqual(L.loi_da_tra_tien(100000.0).ma, "DA_TRA_TIEN: Phiếu này đã trả NCC 100000 — huỷ phiếu là xoá mất khoản đã trả. Gỡ phiếu chi "
			"trước, hoặc lập phiếu trả hàng NCC.")

	def test_check_method_23514(self):
		e = L.loi_check_method()
		self.assertIsInstance(e, LoiCong)
		self.assertEqual((e.ma, e.thong_diep), ("23514", 'new row for relation "payable_payments" violates check constraint '
			'"payable_payments_method_check"'))

	def test_khoa_ngoai_khi_xoa(self):
		# §7.3 điểm 38: nợ của phiếu nhập / phiếu trả NCC → đúng câu 23503 của nppsale; nợ đầu kỳ / lập tay / trả trước → không chặn bằng khoá ngoại
		e = L.loi_fk_xoa("phieu_nhap", "u1")
		self.assertEqual((e.ma, e.thong_diep), ("23503", 'update or delete on table "payables" violates foreign key constraint '
			'"purchase_invoices_payable_id_fkey" on table "purchase_invoices"'))
		self.assertEqual(e.to_dict()["details"], 'Key (id)=(u1) is still referenced from table "purchase_invoices".')
		e = L.loi_fk_xoa("tra_ncc", "u2")
		self.assertEqual(e.thong_diep, 'update or delete on table "payables" violates foreign key constraint "supplier_returns_payable_credit_id_fkey" '
			'on table "supplier_returns"')
		for loai in ("dau_ky", "lap_tay", "tra_truoc", None):
			self.assertIsNone(L.loi_fk_xoa(loai, "x"))


class TestTrangThaiTay(unittest.TestCase):
	def test_bang_khop(self):
		# `_khoa_ghi_thang_no_ncc` (mig 227): paid ⇔ đã trả ≥ số nợ − 0,01; partial ⇔ 0 < đã trả < số nợ; open ⇔ đã trả = 0 và số nợ > 0;
		# overdue ⇔ đã trả < số nợ
		dung = [("paid", 3000, 3000), ("paid", "2999.995", 3000), ("partial", 1, 3000), ("open", 0, 3000), ("overdue", 0, 3000),
			("overdue", 2999, 3000), ("paid", 0, 0), ("paid", -30000, -30000)]
		sai = [("paid", 0, 3000), ("paid", "2999.98", 3000), ("partial", 0, 3000), ("partial", 3000, 3000), ("open", 1, 3000), ("open", 0, 0),
			("open", 0, -30000), ("overdue", 3000, 3000), ("cancelled", 0, 3000), (None, 0, 3000)]
		for st, p, a in dung:
			self.assertTrue(L.trang_thai_khop(st, p, a), (st, p, a))
		for st, p, a in sai:
			self.assertFalse(L.trang_thai_khop(st, p, a), (st, p, a))

	def test_cau_trang_thai(self):
		# V38: số in như numeric thô (float nguyên của Frappe → không `.0`); tham số NULL in `<NULL>` như RAISE
		self.assertEqual(L.loi_trang_thai("paid", 0.0, 3000.0).ma, "NO_NCC_KHOA: trạng thái paid không khớp số đã trả 0 / 3000")
		self.assertEqual(L.loi_trang_thai(None, 0, Decimal("12.50")).ma, "NO_NCC_KHOA: trạng thái <NULL> không khớp số đã trả 0 / 12.50")


class TestDonTraTruoc(unittest.TestCase):
	def _pc(self, ten, luc, con):
		return L.PhieuChiCon(ten, datetime.fromisoformat(luc), Decimal(con))

	def _kn(self, ten, con, dau_ky=False, tao="2026-11-01 08:00"):
		return L.KhoanNo(ten, Decimal(con), dau_ky, datetime.fromisoformat(tao))

	def test_no_dau_ky_truoc_roi_cu_nhat(self):
		# V29: nợ đầu kỳ (lập SAU) vẫn được trừ trước; PN-A rồi PN-B theo ngày ghi nợ; hoà ngày ghi nợ theo tên
		kh = [self._kn("PN-B", 300000, tao="2026-11-05 08:00"), self._kn("DK", 100000, True, "2026-11-16 09:00"), self._kn("PN-A", 200000)]
		self.assertEqual(L.phan_bo_tra_truoc([self._pc(None, "2026-11-16 09:30", 250000)], kh),
			[(None, "DK", Decimal(100000)), (None, "PN-A", Decimal(150000))])
		kh = [self._kn("Z", 10), self._kn("A", 10)]
		self.assertEqual([k for _p, k, _x in L.phan_bo_tra_truoc([self._pc("P1", "2026-11-16 09:30", 15)], kh)], ["A", "Z"])

	def test_phieu_chi_som_don_truoc(self):
		# V33: phiếu chi ghi lùi (lúc chi sớm hơn) dồn trước dù lập sau; hoà lúc chi theo số phiếu, phiếu ĐANG LẬP (chưa số) sau cùng
		pc = [self._pc("PCNCC-0001", "2026-11-12 12:00", 30000), self._pc("PCNCC-0002", "2026-11-11 12:00", 20000)]
		self.assertEqual(L.phan_bo_tra_truoc(pc, [self._kn("N1", 25000)]),
			[("PCNCC-0002", "N1", Decimal(20000)), ("PCNCC-0001", "N1", Decimal(5000))])
		pc = [self._pc(None, "2026-11-12 12:00", 5), self._pc("PCNCC-0009", "2026-11-12 12:00", 5), self._pc("PCNCC-0003", "2026-11-12 12:00", 5)]
		self.assertEqual([p for p, _k, _x in L.phan_bo_tra_truoc(pc, [self._kn("N1", 15)])], ["PCNCC-0003", "PCNCC-0009", None])

	def test_lay_toi_da_va_dung(self):
		# lấy = min(còn của phiếu, còn nợ của khoản); khoản hết nợ bỏ qua; phiếu hết tiền thì sang phiếu sau; hết khoản thì dừng
		pc = [self._pc("P1", "2026-11-01 12:00", 70), self._pc("P2", "2026-11-02 12:00", 100)]
		kh = [self._kn("K1", 50), self._kn("K2", 40, tao="2026-11-02 08:00"), self._kn("K0", 0, tao="2026-10-01 08:00")]
		self.assertEqual(L.phan_bo_tra_truoc(pc, kh), [("P1", "K1", Decimal(50)), ("P1", "K2", Decimal(20)), ("P2", "K2", Decimal(20))])
		self.assertEqual(L.phan_bo_tra_truoc(pc, []), [])
		self.assertEqual(L.phan_bo_tra_truoc([], kh), [])


class TestBuTru(unittest.TestCase):
	def test_trong_pham_vi_khoan_giam(self):
		# §7.3 điểm 10: khoản giảm còn mở của các phiếu trả NCC (đã xếp cũ nhất trước) — lấy dần; thiếu → BU_TRU_KHONG_CON
		self.assertEqual(L.phan_bo_bu_tru(30000, [("PTNCC-1", 30000)]), [("PTNCC-1", Decimal(30000))])
		self.assertEqual(L.phan_bo_bu_tru(25, [("T1", 10), ("T0", 0), ("T2", 30)]), [("T1", Decimal(10)), ("T2", Decimal(15))])
		for tien, giam in ((50000, [("PTNCC-1", 30000)]), (1, []), (1, [("T", 0)])):
			with self.assertRaises(NppLoi) as e:
				L.phan_bo_bu_tru(tien, giam)
			self.assertEqual(e.exception.ma, L.BU_TRU_KHONG_CON)


class TestThamSo(unittest.TestCase):
	def test_btrim_chi_bo_dau_cach(self):
		# btrim một tham số của Postgres chỉ bỏ dấu cách — tab / xuống dòng giữ; rỗng sau trim → NULL
		self.assertEqual(L.btrim("  trả đợt 1 "), "trả đợt 1")
		self.assertEqual(L.btrim("\tREF\n"), "\tREF\n")
		self.assertIsNone(L.btrim("   "))
		self.assertIsNone(L.btrim(None))
		self.assertEqual(L.nullif_rong(" "), " ")
		self.assertIsNone(L.nullif_rong(""))
		self.assertIsNone(L.nullif_rong(None))

	def test_hinh_thuc(self):
		# Ghi trả: NULL / '' → tiền mặt (⚠K §7.3 điểm 10 — nppsale lưu NULL); ngoài ba giá trị → 23514
		self.assertEqual([L.hinh_thuc_ghi_tra(x) for x in (None, "", "cash", "transfer", "offset")], ["cash", "cash", "cash", "transfer", "offset"])
		for x in ("chuyen", "CASH", " cash"):
			with self.assertRaises(LoiCong):
				L.hinh_thuc_ghi_tra(x)
		# phiếu chi: chỉ cash / transfer — NULL tường minh cũng lỗi, `offset` không được
		self.assertEqual([L.kiem_hinh_thuc_chi(x) for x in ("cash", "transfer")], ["cash", "transfer"])
		for x in (None, "", "offset", "chuyen"):
			with self.assertRaises(NppLoi) as e:
				L.kiem_hinh_thuc_chi(x)
			self.assertEqual(e.exception.ma, L.BAD_METHOD)

	def test_ngay_chi(self):
		hn = date(2026, 11, 16)
		self.assertEqual(L.ngay_chi(None, hn), hn)
		self.assertEqual(L.ngay_chi("2026-11-10", hn), date(2026, 11, 10))
		self.assertEqual(L.ngay_chi(datetime(2026, 11, 16, 23, 0), hn), hn)
		with self.assertRaises(NppLoi) as e:
			L.ngay_chi(date(2026, 11, 17), hn)
		self.assertEqual(e.exception.ma, L.NGAY_TUONG_LAI_CHI)

	def test_ghi_chu_dong_chi(self):
		self.assertEqual(L.ghi_chu_dong_chi("PCNCC-0001", "trả đợt 1"), "Phiếu chi PCNCC-0001 — trả đợt 1")
		self.assertEqual(L.ghi_chu_dong_chi("PCNCC-0002", None), "Phiếu chi PCNCC-0002")


if __name__ == "__main__":
	unittest.main()
