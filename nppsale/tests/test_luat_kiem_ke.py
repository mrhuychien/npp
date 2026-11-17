"""Luật thuần kiểm kê (P4 — M6; đặc tả kho_mua §3.17, §3.18, §2.2, §2.5, §7.1 #1 / #11, §7.3 điểm 15):
python3 -m unittest nppsale.tests.test_luat_kiem_ke

Câu lỗi lấy nguyên văn từ kết quả ĐÃ CHẠY trên Postgres tham chiếu (tệp vàng du_lieu/kho_mua_mau.json — V60–V64) và thân hàm nppsale (scratchpad
kho_mua/src/post_stock_adjustment.sql, reject_stock_adjustment.sql). Bộ dữ liệu của bài áp chênh lệch dựng đúng lô của V60 / V61 (L-A bán +200 giá 8.000,
L-B bán +100 giá 9.000, L-C date +10 giá 7.000, L-RONG bán +300 rỗng giá 0).
"""
import unittest
from datetime import date, datetime
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.luat import kiem_ke as KK

BAN, DATE = "Kho ban", "Kho can date"
HOM_NAY = date(2026, 11, 17)


def _ngay(n: int) -> date:
	from datetime import timedelta

	return HOM_NAY + timedelta(days=n)


def _kho(lo=(), ton=None, ao=None, gia_ao=None):
	return KK.KhoKK({x.ma: x for x in lo}, ton or {}, ao or {}, gia_ao or {}, BAN, DATE)


def _lo_p():
	"""Lô của V60: L-A / L-B / L-C / L-RONG (mặt hàng P) — tồn theo (lô, kho)."""
	lo = [KK.LoTT("L-A", "P", _ngay(200), Decimal(8000), BAN), KK.LoTT("L-B", "P", _ngay(100), Decimal(9000), BAN),
		KK.LoTT("L-C", "P", _ngay(10), Decimal(7000), DATE), KK.LoTT("L-RONG", "P", _ngay(300), Decimal(0), BAN)]
	ton = {("L-A", BAN): Decimal(10), ("L-B", BAN): Decimal(5), ("L-C", DATE): Decimal(20)}
	return lo, ton


def _d(stt, chenh, *, hang="P", ten="Nuoc ngot", lo=None, kho=None, gia=0, co_lo=True):
	return KK.DongKK(stt=stt, ten_dong=f"d{stt}", hang=hang, ten=ten, co_lo=co_lo, lo=lo, kho=kho, chenh=Decimal(str(chenh)), gia=Decimal(str(gia)))


class TestCau(unittest.TestCase):
	def test_cau_duyet(self):
		"""Hai hàm KHÁC chữ cho cùng mã: post (không dấu chấm, FORBIDDEN P0001) ↔ reject (dấu chấm, ORG_MISMATCH / FORBIDDEN 42501 ở nơi gọi)."""
		self.assertEqual(KK.FORBIDDEN_KHOA, "FORBIDDEN: tài khoản chưa gắn đơn vị, hoặc đã bị khoá")
		self.assertEqual(KK.KHONG_THAY, "ENTRY_NOT_FOUND: không tìm thấy phiếu kiểm kê")
		self.assertEqual(KK.KHONG_THAY_TU_CHOI, "ENTRY_NOT_FOUND: không tìm thấy phiếu kiểm kê.")
		self.assertEqual(KK.KHAC_NPP, "ORG_MISMATCH: phiếu không thuộc đơn vị của bạn")
		self.assertEqual(KK.KHAC_NPP_TU_CHOI, "ORG_MISMATCH: phiếu không thuộc đơn vị của bạn.")
		self.assertEqual(KK.FORBIDDEN_DUYET, "FORBIDDEN: bạn không có quyền duyệt điều chỉnh kho")
		self.assertEqual(KK.FORBIDDEN_TU_CHOI, "FORBIDDEN: bạn không có quyền duyệt / từ chối điều chỉnh kho.")
		self.assertEqual(KK.SAI_LOAI, "BAD_TYPE: đây không phải phiếu kiểm kê.")
		self.assertEqual(KK.DA_DUYET_TU_CHOI, "ALREADY_POSTED: phiếu đã duyệt — không từ chối được nữa.")
		e = KK.loi_da_duyet("KK60", datetime(2026, 11, 17, 9, 5, 33, 120))
		self.assertEqual((e.ma, e.code), ("ALREADY_POSTED: phiếu KK60 đã được duyệt lúc 09:05 17/11/2026", "P0001"))
		self.assertEqual(KK.loi_sai_trang_thai("KK-2", "cancelled").ma, "BAD_STATUS: phiếu KK-2 đang ở trạng thái cancelled, không duyệt được")
		self.assertEqual(KK.loi_lo_mat("Nuoc ngot").ma, 'BATCH_GONE: lô của dòng "Nuoc ngot" không còn tồn tại')
		self.assertEqual(KK.loi_chua_co_lo("Dau an").ma, 'NO_BATCH: "Dau an" chưa có lô nào để ghi phần thừa. Tạo lô cho sản phẩm này trước.')

	def test_so_trong_cau(self):
		"""§2.5: tồn lô numeric(18,6); phiếu trừ đúng số đã lưu; "chỉ còn" scale 6 khi đã trừ lô, 0 theo scale SL khi không lô nào."""
		self.assertEqual(KK.loi_ton_doi("Nuoc ngot", Decimal(10), Decimal(-12)).ma, 'STOCK_MOVED: "Nuoc ngot" tồn hiện 10.000000, phiếu trừ 12 — tồn đã '
			"đổi từ lúc kiểm đếm. Kiểm đếm lại rồi lập phiếu mới.")
		self.assertEqual(KK.loi_ton_doi("X", Decimal("2.5"), Decimal("-6.5")).ma, 'STOCK_MOVED: "X" tồn hiện 2.500000, phiếu trừ 6.5 — tồn đã đổi từ '
			"lúc kiểm đếm. Kiểm đếm lại rồi lập phiếu mới.")
		self.assertEqual(KK.loi_thieu("Nuoc ngot", Decimal(-16), Decimal(15), True).ma, 'NOT_ENOUGH_STOCK: "Nuoc ngot" chỉ còn 15.000000 để trừ, phiếu '
			"trừ 16 — kiểm đếm lại.")
		self.assertEqual(KK.loi_thieu("Dau an", Decimal(-4), Decimal(0), False).ma, 'NOT_ENOUGH_STOCK: "Dau an" chỉ còn 0 để trừ, phiếu trừ 4 — kiểm '
			"đếm lại.")
		self.assertEqual(KK.chi_con(Decimal("-6.5"), Decimal(0), False), "0.0")
		self.assertEqual(KK.chi_con(Decimal("-6.50"), Decimal(0), False), "0.00")
		self.assertEqual(KK.chi_con(Decimal(-4), Decimal(0), False), "0")

	def test_ghi_chu_tu_choi(self):
		"""`COALESCE(notes || E'\\n', '') || 'Từ chối: ' || COALESCE(NULLIF(p_reason, ''), '(không ghi lý do)')`."""
		self.assertEqual(KK.ghi_chu_tu_choi(None, ""), "Từ chối: (không ghi lý do)")
		self.assertEqual(KK.ghi_chu_tu_choi(None, None), "Từ chối: (không ghi lý do)")
		self.assertEqual(KK.ghi_chu_tu_choi(None, "Dem lai"), "Từ chối: Dem lai")
		self.assertEqual(KK.ghi_chu_tu_choi("cu", "x"), "cu\nTừ chối: x")
		self.assertEqual(KK.ghi_chu_tu_choi("", "x"), "\nTừ chối: x")

	def test_phieu_chi(self):
		self.assertEqual(KK.chon_danh_muc([("u2", "AAA"), ("u1", "COGS_ADJ")]), "u1")  # COGS_ADJ thắng dù có mã nhỏ hơn
		self.assertEqual(KK.chon_danh_muc([("u2", "RENT"), ("u3", "OTHER"), ("u1", "FUEL")]), "u1")  # không COGS_ADJ → đầu theo mã
		self.assertIsNone(KK.chon_danh_muc([]))
		self.assertEqual(KK.dien_giai_hao_hut("KK-261117-0001"), "Hao hụt từ phiếu kiểm kê KK-261117-0001")
		self.assertIn("PHIEU_CHI_KIEM_KE_KHOA", KK.loi_phieu_chi_khoa("KK-1"))
		self.assertEqual(KK.TRUONG_KHOA_PHIEU_CHI, ("so_tien", "danh_muc", "ngay_chi", "nguon_loai", "kiem_ke", "chung_tu_kho"))

	def test_tach_id_lo(self):
		self.assertEqual(KK.tach_id_lo("L-A::sale"), ("L-A", "sale", False))
		self.assertEqual(KK.tach_id_lo("PN-0001-001::date"), ("PN-0001-001", "date", False))
		self.assertEqual(KK.tach_id_lo("~SPX::date"), ("SPX", "date", True))
		self.assertEqual(KK.tach_id_lo("L-A"), ("L-A", None, False))
		self.assertEqual(KK.tach_id_lo(None), (None, None, False))
		self.assertEqual(KK.tach_id_lo(""), (None, None, False))


class TestDuyet(unittest.TestCase):
	def test_v60(self):
		"""V60: (1) lô L-A −3 giá 8.000; (2) hụt không lô −6,5 → FEFO cả hai kho → L-C (date, hạn gần nhất) giá lô 7.000; (3) thừa không lô +2 → lô hạn
		XA nhất L-RONG (kể cả lô rỗng) giá 0; (4) dòng 0 bỏ → (3 lô, 9,5, 69.500, 2, 0)."""
		lo, ton = _lo_p()
		kho = _kho(lo, ton)
		kq = KK.duyet([_d(1, -3, lo="L-A", kho=BAN, gia=8000), _d(2, -6.5), _d(3, 2), _d(4, 0)], kho)
		self.assertEqual((kq.cham, kq.hut_sl, kq.hut_gt, kq.thua_sl, kq.thua_gt), (3, Decimal("9.5"), Decimal("69500.0"), 2, 0))
		self.assertEqual([(b.ten_dong, b.lo, b.kho, b.sl, b.nhap) for b in kq.buoc], [("d1", "L-A", BAN, 3, False), ("d2", "L-C", DATE, Decimal("6.5"),
			False), ("d3", "L-RONG", BAN, 2, True)])
		self.assertEqual(kq.dien, {"d2": ("L-C", DATE), "d3": ("L-RONG", BAN)})  # dòng 1 đã có lô; dòng 0 không điền
		self.assertEqual((kho.ton_lo[("L-A", BAN)], kho.ton_lo[("L-C", DATE)], kho.ton_lo[("L-RONG", BAN)]), (7, Decimal("13.5"), 2))
		self.assertEqual(KK.ket_qua(kq, "PC-0001"), [{"batches_touched": 3, "shrink_qty": 9.5, "shrink_value": 69500.0, "surplus_qty": 2.0,
			"surplus_value": 0.0, "expense_id": "PC-0001"}])

	def test_v61_loi(self):
		"""V61: lô L-A −12 (tồn L-A 10 dù tổng hai lô 15) → STOCK_MOVED; không lô −16 → NOT_ENOUGH_STOCK chỉ còn 15.000000; Q chưa lô +4 → NO_BATCH; Q −4 →
		NOT_ENOUGH_STOCK chỉ còn 0."""
		lo, ton = _lo_p()
		lo, ton = lo[:2], {k: v for k, v in ton.items() if k[0] in ("L-A", "L-B")}
		for dong, cau in (
				([_d(1, -12, lo="L-A", kho=BAN, gia=8000)], 'STOCK_MOVED: "Nuoc ngot" tồn hiện 10.000000, phiếu trừ 12 — tồn đã đổi từ lúc kiểm đếm. Kiểm '
					"đếm lại rồi lập phiếu mới."),
				([_d(1, -16)], 'NOT_ENOUGH_STOCK: "Nuoc ngot" chỉ còn 15.000000 để trừ, phiếu trừ 16 — kiểm đếm lại.'),
				([_d(1, 4, hang="Q", ten="Dau an")], 'NO_BATCH: "Dau an" chưa có lô nào để ghi phần thừa. Tạo lô cho sản phẩm này trước.'),
				([_d(1, -4, hang="Q", ten="Dau an")], 'NOT_ENOUGH_STOCK: "Dau an" chỉ còn 0 để trừ, phiếu trừ 4 — kiểm đếm lại.')):
			with self.assertRaises(NppLoi) as e:
				KK.duyet(dong, _kho(lo, ton))
			self.assertEqual(e.exception.ma, cau)

	def test_hut_fefo_nhieu_lo_mot_gia(self):
		"""FEFO chạm nhiều lô: hạn gần trước (cả hai kho), mỗi lô chạm +1; MỘT giá cho cả dòng = giá lô ĐẦU TIÊN có giá ≠ 0 (§7.1 #11 — lô đầu giá 0
		thì lấy lô kế); hạn trống xếp cuối; Batch tắt cũng lấy (nơi gọi đưa đủ mọi trạng thái)."""
		lo = [KK.LoTT("X0", "P", _ngay(5), Decimal(0), BAN), KK.LoTT("X1", "P", _ngay(9), Decimal(7000), DATE), KK.LoTT("X2", "P", None, Decimal(9000), BAN),
			KK.LoTT("X9", "P", _ngay(1), Decimal(1), BAN)]  # X9 hạn gần nhất nhưng đã hết hàng (tồn 0) — không được đụng, không tính lô chạm
		kho = _kho(lo, {("X0", BAN): Decimal(1), ("X1", DATE): Decimal(2), ("X2", BAN): Decimal(10), ("X9", BAN): Decimal(0)})
		kq = KK.duyet([_d(1, -5)], kho)
		self.assertEqual([(b.lo, b.sl) for b in kq.buoc], [("X0", 1), ("X1", 2), ("X2", 2)])
		self.assertEqual((kq.cham, kq.hut_gt, kq.dien["d1"]), (3, Decimal(35000), ("X0", BAN)))

	def test_hut_hoa_han_theo_ma_roi_kho(self):
		"""Hoà hạn → mã lô, rồi kho bán trước (một Batch có ở hai kho)."""
		lo = [KK.LoTT("B", "P", _ngay(9), Decimal(1)), KK.LoTT("A", "P", _ngay(9), Decimal(2))]
		kho = _kho(lo, {("B", BAN): Decimal(1), ("A", DATE): Decimal(1), ("A", BAN): Decimal(1)})
		kq = KK.duyet([_d(1, -3)], kho)
		self.assertEqual([(b.lo, b.kho) for b in kq.buoc], [("A", BAN), ("A", DATE), ("B", BAN)])

	def test_dong_sau_thay_dong_truoc(self):
		"""nppsale cập nhật tồn ngay trong vòng dòng: dòng thừa cộng vào lô rỗng thì dòng hụt sau lấy được (lô ấy thành có tồn); dòng có lô sau thấy phần
		dòng trước đã trừ (STOCK_MOVED theo tồn MỚI)."""
		lo, ton = _lo_p()
		kq = KK.duyet([_d(1, 2), _d(2, -22.5)], _kho(lo, ton))  # +2 vào L-RONG; −22,5: L-C 20 (hạn +10), L-B 2,5 (hạn +100)
		self.assertEqual([(b.lo, b.sl, b.nhap) for b in kq.buoc], [("L-RONG", 2, True), ("L-C", 20, False), ("L-B", Decimal("2.5"), False)])
		lo, ton = _lo_p()
		with self.assertRaises(NppLoi) as e:
			KK.duyet([_d(1, -8, lo="L-A", kho=BAN), _d(2, -3, lo="L-A", kho=BAN)], _kho(lo, ton))
		self.assertIn("tồn hiện 2.000000, phiếu trừ 3", e.exception.ma)

	def test_thua_lo_han_xa_nhat_va_kho(self):
		"""Thừa không lô: lô hạn XA nhất bất kể tồn (hạn trống xếp cuối); kho = nơi lô có tồn lớn nhất, không đâu có → kho tạo (`npp_kho_tao`), trống →
		kho bán; giá = giá dòng ≠ 0, không thì giá lô."""
		lo = [KK.LoTT("H", "P", _ngay(50), Decimal(5000), BAN), KK.LoTT("N", "P", None, Decimal(1), BAN), KK.LoTT("G", "P", _ngay(40), Decimal(1), BAN)]
		kq = KK.duyet([_d(1, 3)], _kho(lo, {("H", BAN): Decimal(1), ("H", DATE): Decimal(4)}))
		self.assertEqual(([(b.lo, b.kho) for b in kq.buoc], kq.thua_gt), ([("H", DATE)], Decimal(15000)))
		kq = KK.duyet([_d(1, 3, gia=100)], _kho([KK.LoTT("Z", "P", _ngay(9), Decimal(5000), DATE)]))
		self.assertEqual(([(b.lo, b.kho) for b in kq.buoc], kq.thua_gt), ([("Z", DATE)], Decimal(300)))
		kq = KK.duyet([_d(1, 1)], _kho([KK.LoTT("Z", "P", None, Decimal(0), None)]))
		self.assertEqual([(b.lo, b.kho) for b in kq.buoc], [("Z", BAN)])

	def test_dong_co_lo_gia(self):
		"""Dòng có lô: giá dòng ≠ 0 thắng giá lô; = 0 → giá lô; lô có mà dòng thiếu kho → kho tồn lớn nhất + điền kho."""
		lo, ton = _lo_p()
		kq = KK.duyet([_d(1, -1, lo="L-B", kho=BAN, gia=0), _d(2, 1, lo="L-A", gia=123)], _kho(lo, ton))
		self.assertEqual((kq.hut_gt, kq.thua_gt, kq.dien), (Decimal(9000), Decimal(123), {"d2": ("L-A", BAN)}))
		# lô có ở hai kho: dòng mang kho → đúng kho của dòng (không phải kho tồn lớn nhất)
		kq = KK.duyet([_d(1, -1, lo="L-A", kho=DATE)], _kho(lo, {("L-A", BAN): Decimal(5), ("L-A", DATE): Decimal(2)}))
		self.assertEqual([(b.lo, b.kho) for b in kq.buoc], [("L-A", DATE)])
		with self.assertRaises(NppLoi) as e:
			KK.duyet([_d(1, -1, lo="L-MAT", kho=BAN)], _kho(lo, ton))
		self.assertEqual(e.exception.ma, 'BATCH_GONE: lô của dòng "Nuoc ngot" không còn tồn tại')

	def test_hang_khong_lo(self):
		"""Hàng không lô (lô ảo = Bin): dòng có kho → STOCK_MOVED theo Bin (không âm — kiểm kê không áp vượt tồn); hụt không kho → kho bán rồi kho date;
		thừa không kho → kho tồn lớn nhất, không đâu có → kho bán; giá = giá định giá Bin khi giá dòng 0; KHÔNG NO_BATCH."""
		ao = {("X", BAN): Decimal(2), ("X", DATE): Decimal(5)}
		gia = {("X", BAN): Decimal(100), ("X", DATE): Decimal(200)}
		kq = KK.duyet([_d(1, -4, hang="X", co_lo=False)], _kho(ao=dict(ao), gia_ao=gia))
		self.assertEqual(([(b.lo, b.kho, b.sl) for b in kq.buoc], kq.hut_gt, kq.dien), ([(None, BAN, 2), (None, DATE, 2)], Decimal(400),
			{"d1": (None, BAN)}))
		kq = KK.duyet([_d(1, 1, hang="X", co_lo=False)], _kho(ao=dict(ao), gia_ao=gia))
		self.assertEqual(([(b.kho, b.nhap) for b in kq.buoc], kq.thua_gt), ([(DATE, True)], Decimal(200)))
		kq = KK.duyet([_d(1, 1, hang="Y", co_lo=False)], _kho())
		self.assertEqual([(b.kho, b.lo) for b in kq.buoc], [(BAN, None)])
		with self.assertRaises(NppLoi) as e:
			KK.duyet([_d(1, -3, hang="X", ten="Hàng X", co_lo=False, kho=BAN)], _kho(ao=dict(ao)))
		self.assertEqual(e.exception.ma, 'STOCK_MOVED: "Hàng X" tồn hiện 2.000000, phiếu trừ 3 — tồn đã đổi từ lúc kiểm đếm. Kiểm đếm lại rồi lập phiếu mới.')
		with self.assertRaises(NppLoi) as e:
			KK.duyet([_d(1, -8, hang="X", ten="Hàng X", co_lo=False)], _kho(ao=dict(ao)))
		self.assertEqual(e.exception.ma, 'NOT_ENOUGH_STOCK: "Hàng X" chỉ còn 7.000000 để trừ, phiếu trừ 8 — kiểm đếm lại.')

	def test_thu_tu_dong(self):
		"""Dòng áp theo `stt` (idx) dù đưa vào lộn xộn — lỗi ở dòng hỏng ĐẦU TIÊN."""
		lo, ton = _lo_p()
		with self.assertRaises(NppLoi) as e:
			KK.duyet([_d(2, 4, hang="Q", ten="Dau an"), _d(1, -12, lo="L-A", kho=BAN)], _kho(lo, ton))
		self.assertTrue(e.exception.ma.startswith("STOCK_MOVED"), e.exception.ma)


if __name__ == "__main__":
	unittest.main()
