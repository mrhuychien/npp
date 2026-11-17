"""Luật thuần kho + mua hàng + công nợ NCC (đặc tả kho_mua §2): python3 -m unittest nppsale.tests.test_luat_kho_mua

Số in câu lỗi đo trên Postgres 16 của bản tham chiếu (`to_char(x, 'FM999999990.###')`, tích numeric — /tmp/pg-npp, 16/11/2026); tiền theo V26
(K12 — `[đã chạy]` ở đặc tả §6.2): phiếu trả NCC 1 × 12.345 VAT 0,08 → VAT 987.60, tổng 13332.60, nợ −13332.60.
"""
import unittest
from datetime import date, datetime
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.luat import kho_mua as K


class TestDinhDangSo(unittest.TestCase):
	def test_to_char_fm_do_pg16(self):
		# (giá trị, kết quả PG16) — trim(to_char(x, 'FM999999990.###')) chạy trên bản tham chiếu
		do = [("2.5", "3"), ("2.4", "2"), ("48.75", "49"), ("30", "30"), ("0", "0"), ("-2.5", "-3"), ("-2.4", "-2"), ("0.5", "1"),
			("-0.5", "-1"), ("0.4", "0"), ("999999999.5", "#########.###"), ("999999999.4", "999999999"), ("1000000000", "#########.###"),
			("12345678901", "#########.###"), ("-1000000000", "-#########.###"), ("-999999999.5", "-#########.###"), ("1.4999", "1"),
			("3.5000", "4"), ("48.000000", "48"), ("7.500000", "8"), ("-0.4", "0"), ("-0.49999", "0"), ("999999999.49", "999999999"),
			("-999999999.4", "-999999999"), ("0.0000005", "0"), ("123.456789", "123")]
		for x, mong in do:
			self.assertEqual(K.to_char_fm(Decimal(x)), mong, x)
		self.assertEqual((K.to_char_fm(48.75), K.to_char_fm(30.0), K.to_char_fm(7)), ("49", "30", "7"))  # float / int của Frappe

	def test_so_tich_giu_scale_nhu_numeric(self):
		self.assertEqual(K.so_tich(2, 24), "48")
		self.assertEqual(K.so_tich("1.5", 10), "15.0")
		self.assertEqual(K.so_tich("0.5", 24), "12.0")
		self.assertEqual(K.so_tich("2.50", "1.0"), "2.500")  # PG16: 2.50 × 1.0 = 2.500
		# float của Frappe: số nguyên là số người gõ (scale 0), số lẻ lấy chữ số ngắn nhất
		self.assertEqual((K.so_tich(2.0, 24.0), K.so_tich(1.5, 10.0), K.so_tich(0.1, 3)), ("48", "15.0", "0.3"))

	def test_so_pg(self):
		self.assertEqual([K.so_pg(x) for x in (12, "6.5", 100000.0, -30000, Decimal("13332.60"), Decimal("-0.00"), 6.5)],
			["12", "6.5", "100000", "-30000", "13332.60", "0.00", "6.5"])
		self.assertEqual(K.so_pg(None), "<NULL>")  # RAISE in tham số NULL
		self.assertEqual(K.so_pg(Decimal("1E+2")), "100")  # không in dạng mũ

	def test_ngay_gio(self):
		self.assertEqual(K.ngay_dmy("2026-12-14"), "14/12/2026")
		self.assertEqual(K.ngay_dmy(date(2027, 1, 5)), "05/01/2027")
		self.assertEqual(K.gio_dmy(datetime(2026, 11, 16, 13, 37, 59)), "13:37 16/11/2026")
		self.assertEqual(K.gio_dmy("2026-11-16 08:05:00.123"), "08:05 16/11/2026")

	def test_so_dau_vao(self):
		self.assertEqual(K.so(None), Decimal(0))
		self.assertEqual(str(K.so(12.0)), "12")
		self.assertEqual(str(K.so(" 1.50 ")), "1.50")
		with self.assertRaises(ValueError):
			K.so(float("nan"))


class TestTienPhieu(unittest.TestCase):
	def test_v26_khong_lam_tron_thue_tong_kep(self):
		# (1) 1 × 12.345 VAT 0,08 — không làm tròn ở đâu
		t = K.tien_phieu([(1, 12345, 0, "0.08")])
		self.assertEqual((t.tien_hang, t.thue, t.tong), (Decimal(12345), Decimal("987.60"), Decimal("13332.60")))
		self.assertEqual(K.no_ncc(t, la_tra=True), Decimal("-13332.60"))
		self.assertEqual(K.no_ncc(t, la_tra=False), Decimal("13332.60"))
		# (2) thuế gõ tay âm kẹp về 0 (NULL ≠ 0)
		t = K.tien_phieu([(1, 10000, 0, "0.1")], thue_go_tay=-500)
		self.assertEqual((t.thue, t.tong), (Decimal(0), Decimal(10000)))
		# (3) thuế gõ tay thắng số tự cộng; giảm đầu phiếu vượt → tổng kẹp 0 (nợ vẫn có dòng amount 0)
		t = K.tien_phieu([(1, 10000, 0, 0)], giam=999999, thue_go_tay=1000)
		self.assertEqual((t.thue, t.tong), (Decimal(1000), Decimal(0)))
		# (4) máy chủ KHÔNG kẹp tiền dòng: dòng SL âm / giảm vượt tiền dòng vẫn cộng
		t = K.tien_phieu([(2, 10000, 0, 0), (-1, 10000, 0, 0), (0, 10000, 0, 0), (1, 10000, 25000, 0)])
		self.assertEqual((t.tien_hang, t.tong), (Decimal(-5000), Decimal(0)))
		# … và thuế tự cộng cũng trên tiền dòng âm (Σ tiền dòng × thuế suất — không kẹp từng dòng)
		t = K.tien_phieu([(2, 10000, 0, "0.1"), (1, 10000, 25000, "0.1")])
		self.assertEqual((t.tien_hang, t.thue, t.tong), (Decimal(5000), Decimal("500.0"), Decimal("5500.0")))

	def test_thue_go_tay_0_khac_null(self):
		self.assertEqual(K.tien_phieu([(1, 10000, 0, "0.1")], thue_go_tay=0).thue, Decimal(0))
		self.assertEqual(K.tien_phieu([(1, 10000, 0, "0.1")], thue_go_tay=None).thue, Decimal("1000.0"))

	def test_dong_dict_khoa_nppsale_va_giam_dong_la_tien(self):
		t = K.tien_phieu([{"quantity": 3, "unit_price": 10000, "line_discount": 1000, "vat_rate": "0.1"}, {"quantity": 2, "unit_price": 500}],
			giam=500)
		self.assertEqual((t.tien_hang, t.thue, t.tong), (Decimal(30000), Decimal("2900.0"), Decimal("32400.0")))
		self.assertEqual(K.tien_dong(3, 10000, 1000), Decimal(29000))  # giảm dòng là TIỀN của cả dòng
		self.assertEqual(K.line_total(3, 10000, 1000, "0.1"), Decimal("31900.0"))
		self.assertEqual(K.line_total(1, 1000, 5000, "0.1"), Decimal(0))  # line_total kẹp phần tiền dòng âm

	def test_gia_von_lo_theo_don_vi_co_so(self):
		self.assertEqual(K.gia_von_lo(2, 240000, 0, 24), Decimal(10000))  # V01: 2 thùng × 240.000, ×24 → 10.000 / hộp
		self.assertEqual(K.gia_von_lo(3, 10000, 1000, 1).quantize(Decimal("0.0001")), Decimal("9666.6667"))

	def test_dong_thue_va_giam_pi_dao_dau_to_tra(self):
		# phiếu nhập: giảm → Deduct, kẹp ở tiền + thuế
		self.assertEqual(K.giam_dau_phieu_pi(100000, 10000, 5000, False), ("Deduct", Decimal(5000)))
		self.assertEqual(K.giam_dau_phieu_pi(100000, 10000, 200000, False), ("Deduct", Decimal(110000)))
		self.assertIsNone(K.giam_dau_phieu_pi(100000, 10000, 0, False))
		# tờ trả NCC (tiền âm): khoản giảm thành Add dương — chép cách của phiếu nhập là đảo chiều
		self.assertEqual(K.giam_dau_phieu_pi(-100000, -10000, 5000, True), ("Add", Decimal(5000)))
		self.assertEqual(K.giam_dau_phieu_pi(100000, 10000, 200000, True), ("Add", Decimal(110000)))
		# giảm âm (phiếu tạm ghi thẳng của nppsale nhận được) → dòng ngược chiều
		self.assertEqual(K.giam_dau_phieu_pi(100000, 10000, -1000, False), ("Add", Decimal(1000)))
		self.assertEqual(K.giam_dau_phieu_pi(100000, 10000, -1000, True), ("Deduct", Decimal(1000)))
		self.assertEqual((K.thue_go_tay_pi(-5, False), K.thue_go_tay_pi(988, False), K.thue_go_tay_pi(988, True)),
			(Decimal(0), Decimal(988), Decimal(-988)))

	def test_tong_frappe_bang_no_nppsale(self):
		"""Dựng như lõi cộng tờ: grand_total = dấu × (tiền + thuế) ± dòng giảm — phải bằng nợ NCC của nppsale (= no_ncc)."""
		for tien, thue, giam in ((100000, 10000, 0), (100000, 10000, 5000), (100000, 10000, 110000), (100000, 10000, 999999),
				(12345, 988, 1), (0, 0, 0), (5, 0, -7)):
			for la_tra in (False, True):
				s = Decimal(-1 if la_tra else 1)
				dong = K.giam_dau_phieu_pi(s * tien, s * thue, giam, la_tra)
				hieu = Decimal(0) if dong is None else (dong[1] if dong[0] == "Add" else -dong[1])
				tong = s * (tien + thue) + hieu
				tp = K.TienPhieu(Decimal(tien), Decimal(thue), Decimal(giam), max(Decimal(0), Decimal(tien + thue - giam)))
				self.assertEqual(tong, K.no_ncc(tp, la_tra), (tien, thue, giam, la_tra))
				self.assertEqual(tong, K.tong_pi(tien, thue, giam, la_tra))

	def test_dong_pi_va_cot_cong(self):
		d = K.dong_pi(3, 10000, 1000)
		self.assertEqual((d["price_list_rate"], d["rate"], d["discount_amount"], d["npp_giam_dong"]),
			(Decimal(10000), Decimal("9666.6667"), Decimal("333.3333"), Decimal(1000)))
		self.assertEqual(round(d["rate"] * 3), 29000)  # precision 4 giữ tiền dòng sau làm tròn đồng
		c = K.tien_cong_pi(tong_dong=-12345, thue_vat=-988, giam=0, co_thue_go_tay=False, thue_go_tay=0, grand_total=-13333, la_tra=True)
		self.assertEqual((c["subtotal"], c["vat"], c["total"], c["vat_override"]), (Decimal(12345), Decimal(988), Decimal(13333), None))
		c = K.tien_cong_pi(tong_dong=10000, thue_vat=0, giam=500, co_thue_go_tay=True, thue_go_tay=0, grand_total=9500, la_tra=False)
		self.assertEqual((c["subtotal"], c["discount"], c["vat_override"], c["total"]), (Decimal(10000), Decimal(500), Decimal(0), Decimal(9500)))


class TestChonLo(unittest.TestCase):
	def kho(self):
		return [K.LoKho("A", Decimal(5), "2027-01-10", "2026-10-01 08:00:00"), K.LoKho("B", Decimal(3), date(2026, 12, 1), "2026-10-05 08:00:00"),
			K.LoKho("C", Decimal(10), None, "2026-09-01 08:00:00"), K.LoKho("D", Decimal(2), "2026-12-01", "2026-10-02 08:00:00"),
			K.LoKho("E", Decimal(0), "2026-11-20", "2026-09-01 08:00:00")]

	def test_han_cu_truoc_hoa_han_theo_ngay_tao_khong_han_cuoi(self):
		k = self.kho()
		r = K.chon_lo_fefo(k, 12)
		self.assertEqual(r.lay, [("D", 2), ("B", 3), ("A", 5), ("C", 2)])
		self.assertEqual(r.thieu, 0)
		r2 = K.chon_lo_fefo(k, 10)  # dòng sau thấy phần dòng trước đã lấy
		self.assertEqual((r2.lay, r2.thieu), ([("C", 8)], Decimal(2)))

	def test_kiem_ke_hut_hoa_han_theo_ma_khong_theo_ngay_tao(self):
		k = [K.LoKho("Z", Decimal(1), "2026-12-01", "2026-01-01"), K.LoKho("Y", Decimal(1), "2026-12-01", "2026-06-01")]
		self.assertEqual(K.chon_lo_fefo(k, 1, K.thu_tu_hut).lay, [("Y", 1)])
		k = [K.LoKho("Z", Decimal(1), "2026-12-01", "2026-01-01"), K.LoKho("Y", Decimal(1), "2026-12-01", "2026-06-01")]
		self.assertEqual(K.chon_lo_fefo(k, 1).lay, [("Z", 1)])  # FEFO thường: hoà hạn → ngày tạo

	def test_kiem_ke_thua_han_xa_nhat_ke_ca_lo_rong(self):
		k = [K.LoKho("W", Decimal(0), "2026-01-01"), K.LoKho("Y", Decimal(0), "2027-05-01"), K.LoKho("X", Decimal(4), "2027-05-01"),
			K.LoKho("Z", Decimal(9), None)]
		self.assertEqual(K.lo_nhan_thua(k), "X")
		self.assertEqual(K.lo_nhan_thua([K.LoKho("Q", Decimal(0), None), K.LoKho("P", Decimal(1), None)]), "P")
		self.assertIsNone(K.lo_nhan_thua([]))


class TestKhoNhan(unittest.TestCase):
	def test_vung_theo_han_mot_chieu(self):
		hn = date(2026, 11, 17)
		self.assertEqual(K.vung_nhan("sale", "2026-12-17", hn, 30), "date")  # = hôm nay + 30 → date (≤)
		self.assertEqual(K.vung_nhan("sale", "2026-12-18", hn, 30), "sale")
		self.assertEqual(K.vung_nhan("sale", None, hn, 30), "sale")  # không hạn
		self.assertEqual(K.vung_nhan("date", "2099-12-31", hn, 30), "date")  # không bao giờ date → sale
		self.assertEqual(K.vung_nhan("sale", "2026-11-10", hn, 0), "date")  # đã hết hạn
		self.assertEqual(K.vung_nhan("sale", "2026-11-18", hn, 0), "sale")
		self.assertEqual(K.vung_nhan("sale", date(2026, 12, 17), datetime(2026, 11, 17, 23, 0), None), "date")  # ngưỡng trống → 30
		self.assertEqual((K.nguong(None), K.nguong(""), K.nguong("7"), K.nguong(0)), (30, 30, 7, 0))


TEN = {"A": "Hàng A", "B": "Hàng B", "C": "Hàng C"}
DV = {"A": "hộp", "B": "gói", "C": "chai"}


class TestGhepDongLo(unittest.TestCase):

	def test_ghep_theo_thu_tu_dong_va_ma_lo(self):
		kq = K.ghep_dong_lo([K.DongGhep(2, "A", Decimal(5)), K.DongGhep(1, "A", Decimal(10)), K.DongGhep(3, "B", Decimal(1))],
			[K.LoCu("PN-0001-002", "A", Decimal(0)), K.LoCu("PN-0001-001", "A", Decimal(7)), K.LoCu("PN-0001-003", "B", Decimal(0)),
			K.LoCu("PN-0001-004", "C", Decimal(3))], TEN, DV)
		self.assertEqual(kq.ghep, {1: "PN-0001-001", 2: "PN-0001-002", 3: "PN-0001-003"})
		self.assertEqual(kq.bo, ["PN-0001-004"])
		self.assertEqual(kq.muc_loi, ["Hàng C: đã xuất 3 — không bỏ dòng này được"])

	def test_sl_moi_duoi_da_xuat_va_cau_loi(self):
		kq = K.ghep_dong_lo([K.DongGhep(1, "A", Decimal("4.5"))], [K.LoCu("L1", "A", Decimal("7.5")), K.LoCu("L2", "B", Decimal(0))],
			TEN, DV)
		self.assertEqual(kq.muc_loi, ["Hàng A: đã xuất 8 hộp, số lượng mới chỉ 5"])  # to_char làm tròn nửa ra xa 0
		self.assertEqual(kq.bo, ["L2"])  # lô chưa xuất bỏ được — không thành mục lỗi
		e = K.loi_da_xuat_nhieu_hon(kq.muc_loi + ["Hàng C: đã xuất 3 — không bỏ dòng này được"])
		self.assertIsInstance(e, NppLoi)
		self.assertEqual(e.ma, "DA_XUAT_NHIEU_HON: Hàng của phiếu đã xuất nhiều hơn số lượng sửa — Hàng A: đã xuất 8 hộp, số lượng mới chỉ 5 · "
			"Hàng C: đã xuất 3 — không bỏ dòng này được. Giữ số lượng tối thiểu bằng số đã xuất, hoặc lập phiếu trả hàng NCC / điều chỉnh kho.")

	def test_du_dong_khong_loi_va_ten_trong(self):
		kq = K.ghep_dong_lo([K.DongGhep(1, "A", Decimal(7))], [K.LoCu("L1", "A", Decimal(7))])
		self.assertEqual((kq.ghep, kq.muc_loi), ({1: "L1"}, []))  # bằng đúng số đã xuất: được
		kq = K.ghep_dong_lo([K.DongGhep(1, "A", Decimal(1))], [K.LoCu("L1", "A", Decimal(2))])
		self.assertEqual(kq.muc_loi, [": đã xuất 2 , số lượng mới chỉ 1"])  # format('%s', NULL) in rỗng


class TestLucChi(unittest.TestCase):
	def test_v_luc(self):
		lap = datetime(2026, 11, 16, 9, 15, 3)
		self.assertEqual(K.luc_chi("2026-11-16", lap), lap)
		self.assertEqual(K.luc_chi(date(2026, 11, 10), lap), datetime(2026, 11, 10, 12, 0))
		self.assertEqual(K.luc_chi("2026-11-10", "2026-11-16 09:15:03.5"), datetime(2026, 11, 10, 12, 0))


class TestVaiTrangThai(unittest.TestCase):
	def test_cua_vai_dung_cau_tung_ham(self):
		self.assertIsNone(K.loi_vai("complete_purchase_invoice", "warehouse"))
		e = K.loi_vai("complete_purchase_invoice", "sales")
		self.assertEqual((e.ma, e.code), ("FORBIDDEN: vai trò của bạn không được làm thao tác kho / mua hàng này.", "42501"))
		self.assertIsNone(K.loi_vai("complete_purchase_invoice", "sales", noi_bo=True))  # cửa npp.via_rpc
		self.assertEqual(K.loi_vai("sua_phieu_nhap", "sales", noi_bo=True).ma, "FORBIDDEN: vai trò của bạn không được sửa phiếu nhập.")  # không cửa
		self.assertEqual(K.loi_vai("khoi_phuc_phieu_tra_ncc", None).ma, "FORBIDDEN: vai trò của bạn không được khôi phục phiếu trả NCC.")
		self.assertEqual(K.loi_vai("record_payable_payment", "manager").ma, "FORBIDDEN: chỉ chủ NPP hoặc kế toán được ghi trả tiền NCC.")
		self.assertIsNone(K.loi_vai("chi_tra_ncc", "accountant"))
		self.assertEqual(K.loi_vai("huy_phieu_chi_ncc", "warehouse").ma, "FORBIDDEN: chỉ chủ NPP hoặc kế toán được huỷ phiếu chi trả NCC.")
		self.assertEqual(K.loi_vai("post_stock_import", "manager").ma, "FORBIDDEN: chỉ chủ NPP hoặc thủ kho được lập phiếu nhập kho.")
		self.assertIsNone(K.loi_vai("post_stock_issue", "warehouse"))
		self.assertEqual(K.loi_vai("cancel_stock_entry", "accountant").ma, "FORBIDDEN: vai trò của bạn không được làm thao tác kho / mua hàng này.")
		e = K.loi_vai("luu_gia_nhap", "sales")
		self.assertEqual((e.ma, e.code), ("KHONG_DU_QUYEN_GIA_NHAP: vai này không sửa được bảng giá nhập", "P0001"))  # P0001 — §7.2 #21
		self.assertEqual(K.loi_vai("gop_nha_cung_cap", "warehouse").ma, "KHONG_DU_QUYEN: chỉ Chủ NPP / Quản lý / Kế toán được gộp nhà cung cấp")
		self.assertEqual(K.loi_vai("xoa_nha_cung_cap", "manager").ma, "KHONG_DU_QUYEN_XOA_NCC: chỉ Chủ NPP được xoá nhà cung cấp")
		self.assertIsNone(K.loi_vai("so_chung_tu_ncc", "warehouse"))  # thủ kho thấy cả con_no (§7.3 điểm 25)
		self.assertEqual(K.loi_vai("so_chung_tu_ncc", "sales").ma, "KHONG_DU_QUYEN")

	def test_trang_thai(self):
		self.assertEqual([K.trang_thai_pi(0), K.trang_thai_pi(0, "2026-11-16 08:00:00"), K.trang_thai_pi(1), K.trang_thai_pi(2),
			K.trang_thai_pi(1, "x")], ["draft", "cancelled", "completed", "cancelled", "completed"])
		self.assertEqual([K.trang_thai_phieu_kho(x) for x in (0, 1, 2, None)], ["draft", "posted", "cancelled", "draft"])


class TestPhieuNhap(unittest.TestCase):
	"""M1 — câu lỗi dòng / HANG_DA_XUAT, mã lô, bảng giá nhập (mig 234; V11, V15, V16 của tệp vàng)."""

	def test_cau_loi_dong(self):
		self.assertEqual(K.loi_dong_so_luong(2).ma, "SO_LUONG_KHONG_HOP_LE: Dòng 2 có số lượng không lớn hơn 0.")
		self.assertEqual(K.loi_dong_gia(1).ma, "GIA_KHONG_HOP_LE: Dòng 1 có giá / giảm giá âm.")
		self.assertEqual(K.loi_dong_tien_am(3).ma, "GIA_KHONG_HOP_LE: Dòng 3 có giảm giá lớn hơn tiền hàng.")

	def test_tien_dong_am(self):
		"""Giảm dòng (TIỀN cả dòng) lớn hơn SL × đơn giá → tiền dòng âm: lõi không ghi sổ được dòng `rate` âm (câu tiếng Anh) → câu riêng; giảm
		BẰNG tiền hàng (dòng 0 đ) vẫn được; kiểm SAU SL và giá / giảm âm của cùng dòng."""
		K.kiem_dong_phieu([(2, 1, 10, 20), (1, 24, 240000, 240000)])  # tiền dòng 0 — được
		for dong, mong in (
				([(1, 1, 10, 20)], "GIA_KHONG_HOP_LE: Dòng 1 có giảm giá lớn hơn tiền hàng."),
				([(2.5, 1, 10, "25.01")], "GIA_KHONG_HOP_LE: Dòng 1 có giảm giá lớn hơn tiền hàng."),
				([(1, 1, 10, 0), (3, 6, 1000, 3001)], "GIA_KHONG_HOP_LE: Dòng 2 có giảm giá lớn hơn tiền hàng."),
				([(0, 1, 10, 20)], "SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0."),
				([(1, 1, -10, 0)], "GIA_KHONG_HOP_LE: Dòng 1 có giá / giảm giá âm.")):
			with self.assertRaises(NppLoi) as e:
				K.kiem_dong_phieu(dong)
			self.assertEqual(e.exception.ma, mong, dong)

	def test_kiem_dong_tung_dong_du_bon_kiem(self):
		"""Thứ tự `sua_phieu_nhap` bước 10: đủ kiểm của MỘT dòng rồi mới sang dòng sau; SL ≤ 0 / hệ số ≤ 0 trước giá âm."""
		K.kiem_dong_phieu([(1, 1, 0, 0), (2.5, 1, 30000, 0), (2, 24, 240000, 12000)])  # giá 0 (hàng tặng) được
		for dong, mong in (
				([(10, 1, 10000, 0), (0, 1, 5000, 0)], "SO_LUONG_KHONG_HOP_LE: Dòng 2"),
				([(1, 1, -1, 0), (0, 1, 5000, 0)], "GIA_KHONG_HOP_LE: Dòng 1"),
				([(1, 0, 100, 0)], "SO_LUONG_KHONG_HOP_LE: Dòng 1"),
				([(-1, 1, -100, 0)], "SO_LUONG_KHONG_HOP_LE: Dòng 1"),
				([(1, 1, 100, -5)], "GIA_KHONG_HOP_LE: Dòng 1"),
				([(1, None, 100, 0), (1, 1, 100, -1)], "GIA_KHONG_HOP_LE: Dòng 2")):
			with self.assertRaises(NppLoi) as e:
				K.kiem_dong_phieu(dong)
			self.assertTrue(e.exception.ma.startswith(mong), (dong, e.exception.ma))

	def test_ma_lo(self):
		self.assertEqual([K.ma_lo_phieu_nhap("PN-0001", 1), K.ma_lo_phieu_nhap("PN-10000", 12), K.ma_lo_phieu_nhap("PN-0042", 1000)],
			["PN-0001-001", "PN-10000-012", "PN-0042-1000"])

	def test_hang_da_xuat_dung_cau(self):
		muc = [("Hàng A", K.muc_hang_da_xuat("Hàng A", 48, 18.0))]
		self.assertEqual(K.loi_hang_da_xuat(muc, False).ma, "HANG_DA_XUAT: Không huỷ được vì hàng của phiếu đã xuất bớt — Hàng A (nhập "
			"48.000000, còn 18.000000). Lập phiếu trả hàng NCC hoặc phiếu điều chỉnh kho — hoặc bật \"Cho phép bán vượt tồn kho\" (Cài đặt › Đơn vị) "
			"để huỷ: phần đã xuất thành tồn âm.")  # V11 (nppsale nguyên văn)
		self.assertEqual(K.loi_hang_da_xuat(muc, True).ma, "HANG_DA_XUAT: Không huỷ được vì hàng của phiếu đã xuất bớt — Hàng A (nhập "
			"48.000000, còn 18.000000). Lập phiếu trả hàng NCC hoặc phiếu điều chỉnh kho.")  # §7.3 điểm 12
		hai = [("Hàng D", K.muc_hang_da_xuat("Hàng D", 6, 0)), ("Hàng C", K.muc_hang_da_xuat("Hàng C", "2.5", "1.25"))]
		self.assertIn("— Hàng C (nhập 2.500000, còn 1.250000) · Hàng D (nhập 6.000000, còn 0.000000).", K.loi_hang_da_xuat(hai, False).ma)

	def test_chu_json_nhu_jsonb(self):
		self.assertEqual([K.chu_json(x) for x in (None, "abc", " 12 ", True, False, 240000, 12345.6, 1e-7, -5, Decimal("1.50"), [1, "a"])],
			[None, "abc", " 12 ", "true", "false", "240000", "12345.6", "0.0000001", "-5", "1.50", '[1, "a"]'])

	def test_so_numeric_va_lam_tron(self):
		self.assertEqual([K.so_numeric(x) for x in ("12", "-5", "1e3", ".5", "5.", "1.50")],
			[Decimal(12), Decimal(-5), Decimal("1E+3"), Decimal("0.5"), Decimal(5), Decimal("1.50")])
		self.assertEqual([K.so_numeric(x) for x in ("abc", "", "1,5", "NaN", "Infinity", "--1", "1e", " 1")], [None] * 8)
		self.assertEqual([K.tron_dong(x) for x in ("12345.6", "2.5", "2.4", "-2.5", 0)], [12346, 3, 2, -3, 0])

	def test_dong_gia_nhap(self):
		self.assertEqual(K.dong_gia_nhap({"product_id": "SPA", "unit_name": " thùng ", "price": 240000}), ("SPA", "thùng", "240000"))
		self.assertEqual(K.dong_gia_nhap({"product_id": "SPA", "unit_name": "hộp", "price": None}), ("SPA", "hộp", None))
		self.assertEqual(K.dong_gia_nhap({"product_id": "SPA", "unit_name": "hộp"}), ("SPA", "hộp", None))
		self.assertEqual(K.dong_gia_nhap({"product_id": "SPA", "unit_name": "hộp", "price": "  "}), ("SPA", "hộp", ""))
		for d in ({"product_id": "", "unit_name": "hộp"}, {"product_id": "SPA", "unit_name": "  "}, {"unit_name": "hộp"}, "SPA", None):
			with self.assertRaises(NppLoi) as e:
				K.dong_gia_nhap(d)
			self.assertEqual(e.exception.ma, "GIA_NHAP_SAI: thiếu mặt hàng / đơn vị")

	def test_gia_nhap_so(self):
		self.assertEqual([K.gia_nhap_so(x) for x in (None, "", "0", "12345.6", "240000")], [None, None, 0, 12346, 240000])
		for chu, mong in (("abc", 'GIA_NHAP_SAI: giá "abc" không phải số'), ("-5", "GIA_NHAP_AM: giá nhập không được âm"),
				("true", 'GIA_NHAP_SAI: giá "true" không phải số'), ("-0.4", "GIA_NHAP_AM: giá nhập không được âm")):
			with self.assertRaises(NppLoi) as e:
				K.gia_nhap_so(chu)
			self.assertEqual(e.exception.ma, mong)

	def test_ngay_gia_tay_va_de_gia(self):
		self.assertEqual(K.ngay_gia_tay(None, "2026-11-16"), date(2026, 11, 16))
		self.assertEqual(K.ngay_gia_tay("2026-10-01", "2026-11-16"), date(2026, 11, 16))
		self.assertEqual(K.ngay_gia_tay("2026-12-01", "2026-11-16"), date(2026, 12, 1))  # GREATEST(cũ, hôm nay)
		self.assertTrue(K.duoc_de_gia(None, "2026-10-01"))
		self.assertTrue(K.duoc_de_gia("2026-10-01", "2026-10-01"))  # ≤
		self.assertTrue(K.duoc_de_gia("2026-09-20", "2026-10-05"))
		self.assertFalse(K.duoc_de_gia("2026-10-05", "2026-09-20"))  # V15: P0 cũ hơn không đè

	def test_dong_ghi_gia_duoi_cung(self):
		"""V15: (A, hộp) dòng 0 đ (tặng) bỏ, (B, gói) lấy dòng sort lớn nhất (4.800 — không phải 5.000)."""
		dong = [{"product_id": "SPA", "unit_name": "hộp", "unit_price": 10000}, {"product_id": "SPA", "unit_name": "thùng", "unit_price": 230000},
			{"product_id": "SPA", "unit_name": "hộp", "unit_price": 0}, {"product_id": "SPB", "unit_name": "gói", "unit_price": 5000},
			{"product_id": "SPB", "unit_name": "gói", "unit_price": "4800"}, {"product_id": "SPB", "unit_name": " ", "unit_price": 9},
			{"product_id": None, "unit_name": "gói", "unit_price": 9}]
		self.assertEqual(K.dong_ghi_gia(dong), {("SPA", "hộp"): 10000, ("SPA", "thùng"): 230000, ("SPB", "gói"): 4800})


if __name__ == "__main__":
	unittest.main()
