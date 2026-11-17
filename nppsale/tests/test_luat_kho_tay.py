"""Luật thuần phiếu kho tay (P4 — M4; đặc tả kho_mua §3.6, §3.15, §3.16, §3.19, §4.5, §7.3 điểm 4 / 5 / 23 / 29):
python3 -m unittest nppsale.tests.test_luat_kho_tay

Câu lỗi lấy nguyên văn từ kết quả ĐÃ CHẠY trên Postgres tham chiếu (tệp vàng du_lieu/kho_mua_mau.json — V41–V55) và thân hàm nppsale (scratchpad
kho_mua/src/post_stock_issue.sql, post_stock_transfer.sql, cancel_stock_entry.sql, post_stock_import.sql, _trg_khoa_ghi_thang_phieu_kho.sql).
"""
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong
from nppsale.luat import kho_tay as T


class TestCauXuatChuyen(unittest.TestCase):
	def test_khong_du_ton_luot_mot(self):
		# V43a: SL CƠ SỞ (24) với nhãn đơn vị giao dịch MIN(unit_name) "Thung" — §7.3 điểm 29 chép y nguyên
		e = T.loi_khong_du_ton("Nuoc ngot", 24, "Thung", "sale", (True, Decimal(10)))
		self.assertEqual((e.ma, e.code), ("KHONG_DU_TON: Nuoc ngot — cần 24.000000 Thung, kho hàng bán chỉ còn 10.000000. Giảm số lượng, đổi kho, hoặc "
			"nhập bù rồi ghi sổ lại.", "P0001"))
		# V45: kho date; V49: chuyển kho — đuôi khác
		self.assertEqual(T.loi_khong_du_ton("Nuoc ngot", 25, "Lon", "date", (True, 20)).ma, "KHONG_DU_TON: Nuoc ngot — cần 25.000000 Lon, kho hàng "
			"date chỉ còn 20.000000. Giảm số lượng, đổi kho, hoặc nhập bù rồi ghi sổ lại.")
		self.assertEqual(T.loi_khong_du_ton("Nuoc ngot", 30, "Lon", "date", (True, 27), chuyen=True).ma, "KHONG_DU_TON: Nuoc ngot — cần 30.000000 Lon, "
			"kho hàng date chỉ còn 27.000000. Giảm số lượng hoặc đổi kho nguồn.")
		# không dòng lô nào → "còn 0" (COALESCE của tập rỗng — không scale); đơn vị trống → "đv cơ sở"
		self.assertEqual(T.loi_khong_du_ton("Dau an", 3, None, "sale", (False, 0)).ma, "KHONG_DU_TON: Dau an — cần 3.000000 đv cơ sở, kho hàng bán "
			"chỉ còn 0. Giảm số lượng, đổi kho, hoặc nhập bù rồi ghi sổ lại.")
		# có dòng lô đã về 0 → numeric(18,6)
		self.assertEqual(T.con_in(True, 0), "0.000000")
		self.assertEqual(T.con_in(False, 5), "0")

	def test_cau_khac(self):
		self.assertEqual(T.loi_lay_mat("Nuoc ngot", 2).ma, "KHONG_DU_TON: Nuoc ngot — hàng vừa bị lấy mất trong lúc ghi sổ, còn thiếu 2.000000. Thử lại.")
		self.assertEqual(T.loi_khong_con_tam("cancelled").ma,
			'PHIEU_KHONG_CON_TAM: Phiếu đang ở trạng thái "cancelled" — chỉ phiếu tạm mới ghi sổ được.')
		self.assertEqual(T.loi_trung_kho("date").ma, "TRUNG_KHO: Kho nguồn và kho đích đang là một (date). Chọn hai kho khác nhau.")
		self.assertEqual((T.KHONG_TON_TAI_XUAT, T.KHONG_TON_TAI_CHUYEN), ("PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu xuất kho này.",
			"PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu chuyển kho này."))
		self.assertEqual((T.SAI_LOAI_XUAT, T.SAI_LOAI_CHUYEN), ("SAI_LOAI_PHIEU: Phiếu này không phải phiếu xuất kho.",
			"SAI_LOAI_PHIEU: Phiếu này không phải phiếu chuyển kho."))
		self.assertEqual(T.KHONG_CO_HANG, "PHIEU_KHONG_CO_HANG: Phiếu chưa có dòng hàng nào.")
		self.assertEqual(T.THIEU_KHO_DICH, "THIEU_KHO_DICH: Phiếu chuyển kho chưa chọn kho đích.")
		# V48: hạn DD/MM/YYYY, ngưỡng thô
		self.assertEqual(T.loi_hang_gan_han("Nuoc ngot", "L-C", date(2026, 11, 27), 30).ma, "HANG_GAN_HAN: Nuoc ngot (lô L-C, hạn 27/11/2026) chỉ còn "
			"dưới 30 ngày nên không chuyển sang kho hàng bán được — hệ thống sẽ tự đẩy về kho hàng date. Bán hàng gần hạn qua kênh hàng date.")
		self.assertEqual((T.ten_vung("date"), T.ten_vung("sale"), T.ten_vung(None)), ("hàng date", "hàng bán", "hàng bán"))

	def test_gom_can(self):
		# dòng âm / 0 vẫn tính vào tổng (HAVING SUM > 0); đơn vị MIN theo thứ tự chữ; ra theo mã hàng
		ra = T.gom_can([("SPP", "Lon", 5), ("SPP", "Lon", -3), ("SPA", "thùng", 24), ("SPA", "hộp", 2), ("SPQ", "Chai", -2), ("SPG", None, 0)])
		self.assertEqual([(x.hang, x.can, x.dv) for x in ra], [("SPA", Decimal(26), "hộp"), ("SPP", Decimal(2), "Lon")])
		self.assertEqual([x.hang for x in T.gom_can([("B", "x", 1), ("A", "x", 1)])], ["A", "B"])
		self.assertIsNone(T.gom_can([("A", None, 1)])[0].dv)


class TestCauHuy(unittest.TestCase):
	def test_cau_nguon(self):
		self.assertEqual(T.KHONG_THAY_PHIEU, "ENTRY_NOT_FOUND: không tìm thấy phiếu kho này.")
		self.assertEqual(T.loi_nguon_phieu_nhap("PN-0001").ma, "ENTRY_HAS_SOURCE: phiếu PN-0001 thuộc một hoá đơn nhập mua. Huỷ hoá đơn nhập đó thay vì "
			"huỷ riêng phiếu kho.")
		self.assertEqual(T.loi_nguon_tra_ncc("PTNCC-0001").ma, "ENTRY_HAS_SOURCE: phiếu PTNCC-0001 thuộc một phiếu trả NCC. Huỷ phiếu trả NCC đó thay vì "
			"huỷ riêng phiếu kho.")
		self.assertEqual(T.loi_nguon_tra_khach("NL-0001").ma, "ENTRY_HAS_SOURCE: phiếu NL-0001 là hàng khách trả. Huỷ phiếu trả hàng đó thay vì huỷ riêng "
			"phiếu kho.")
		self.assertEqual(T.loi_nguon_tra_khach_sua("HDT-0001").ma, "ENTRY_HAS_SOURCE: phiếu HDT-0001 là hàng khách trả. Huỷ / sửa phiếu trả hàng đó thay vì "
			"huỷ riêng phiếu kho.")
		self.assertEqual(T.loi_nguon_no_ncc("IN-1").ma, "ENTRY_HAS_SOURCE: phiếu IN-1 đang có công nợ NCC. Xoá công nợ NCC đó trước rồi mới huỷ phiếu kho.")
		self.assertEqual(T.loi_hd_da_huy("HD-0001", "HD-0001").ma, "ENTRY_HAS_INVOICE: phiếu HD-0001 thuộc hóa đơn HD-0001 đã huỷ / đã sửa — hàng đã hoàn "
			"kho lúc huỷ / sửa hóa đơn, không huỷ riêng phiếu kho được.")
		self.assertEqual(T.loi_hd_dang_ghi("XK-1", "HD-0001").ma, "ENTRY_HAS_INVOICE: phiếu XK-1 thuộc hóa đơn HD-0001. Huỷ hóa đơn đó thay vì huỷ riêng "
			"phiếu kho — huỷ riêng thì hàng về kho mà sổ nợ vẫn ghi khách còn nợ.")
		self.assertEqual(T.loi_khong_hoan_duoc("CKL-1", "transfer").ma, "CANNOT_REVERSE_TYPE: phiếu CKL-1 (transfer) đã ghi sổ nhưng chưa có đường hoàn "
			"kho cho loại phiếu này. Dùng phiếu điều chỉnh để sửa tồn.")
		# V51 / V52: nhập / còn numeric(18,6)
		self.assertEqual(T.loi_da_xuat_bot("Gao", "IN-B", 10, Decimal("7.5")).ma, 'ALREADY_ISSUED: "Gao" của phiếu IN-B đã xuất bớt — nhập 10.000000 '
			"nhưng lô chỉ còn 7.500000. Phiếu đã xuất thì chỉ SỬA được, không huỷ được.")

	def test_ghi_chu_huy(self):
		# V50: lý do '' giữ rỗng; NULL → "(không ghi lý do)"; ghi chú NULL không xuống dòng, '' vẫn xuống dòng (COALESCE('' || E'\n'))
		self.assertEqual(T.ghi_chu_huy(None, "nham"), "Huỷ phiếu: nham")
		self.assertEqual(T.ghi_chu_huy(None, ""), "Huỷ phiếu: ")
		self.assertEqual(T.ghi_chu_huy(None, None), "Huỷ phiếu: (không ghi lý do)")
		self.assertEqual(T.ghi_chu_huy("binh thuong", "x"), "binh thuong\nHuỷ phiếu: x")
		self.assertEqual(T.ghi_chu_huy("", "x"), "\nHuỷ phiếu: x")

	def test_ket_qua(self):
		self.assertEqual(T.ket_qua_huy(True, True, 2), [{"cancelled": True, "reversed": True, "lines_reversed": 2}])
		self.assertEqual(T.ket_qua_huy(True, False, 0), [{"cancelled": True, "reversed": False, "lines_reversed": 0}])


class TestTaiNhap(unittest.TestCase):
	def _dong(self, **k):
		return {"product_id": "SPA", "unit_name": "thùng", "qty_tx": 2, "conv": 24, "base_qty": 48, "base_cost": 10000, **k}

	def test_doc_tai(self):
		t = T.doc_tai_nhap({"entry_code": "  IN-1 ", "posted_at": "2026-10-01T12:00:00+07:00", "supplier_id": "", "warehouse_zone": " ",
			"notes": "", "payable": {"amount": "480000", "invoice_number": "  "}, "lines": [self._dong()]})
		self.assertEqual((t.ma, t.ncc, t.vung, t.ghi_chu, t.no, t.so_hd, t.co_mang, len(t.dong)), ("IN-1", None, "sale", None, Decimal(480000), None,
			True, 1))
		self.assertEqual(t.luc, datetime(2026, 10, 1, 12, tzinfo=timezone(timedelta(hours=7))))
		t = T.doc_tai_nhap("không phải object")
		self.assertEqual((t.ma, t.luc, t.no, t.vung, t.co_mang), (None, None, Decimal(0), "sale", False))
		self.assertFalse(T.doc_tai_nhap({"lines": {"a": 1}}).co_mang)

	def test_ep_kieu_truoc_vai(self):
		# khối DECLARE: sai kiểu ra lỗi THÔ của Postgres (22007 / 22P02) — nơi gọi gọi trước cửa vai
		with self.assertRaises(LoiCong) as e:
			T.doc_tai_nhap({"posted_at": "hôm qua"})
		self.assertEqual((e.exception.ma, e.exception.thong_diep), ("22007", 'invalid input syntax for type timestamp with time zone: "hôm qua"'))
		with self.assertRaises(LoiCong) as e:
			T.doc_tai_nhap({"posted_at": ""})
		self.assertEqual(e.exception.ma, "22007")
		with self.assertRaises(LoiCong) as e:
			T.doc_tai_nhap({"payable": {"amount": "năm trăm"}})
		self.assertEqual((e.exception.ma, e.exception.thong_diep), ("22P02", 'invalid input syntax for type numeric: "năm trăm"'))
		self.assertEqual(T.ep_so(None, 7), 7)
		self.assertEqual(T.ep_so(" 1.5 "), Decimal("1.5"))
		self.assertIsNone(T.ep_ngay(""))
		self.assertEqual(T.ep_ngay("2027-06-30T00:00:00"), date(2027, 6, 30))
		with self.assertRaises(LoiCong) as e:
			T.ep_ngay("30/06/2027")
		self.assertEqual((e.exception.ma, e.exception.thong_diep), ("22007", 'invalid input syntax for type date: "30/06/2027"'))
		with self.assertRaises(LoiCong):
			T.ep_ngay("2027-02-30")

	def test_kiem_dau(self):
		with self.assertRaises(NppLoi) as e:
			T.kiem_dau_nhap(T.doc_tai_nhap({"entry_code": " ", "lines": [self._dong()]}))
		self.assertEqual(e.exception.ma, "BAD_PAYLOAD: thiếu mã phiếu.")
		for dong in (None, [], {"x": 1}):
			with self.assertRaises(NppLoi) as e:
				T.kiem_dau_nhap(T.doc_tai_nhap({"entry_code": "IN-1", "lines": dong}))
			self.assertEqual(e.exception.ma, "BAD_PAYLOAD: phiếu nhập cần ít nhất một dòng hàng.")
		with self.assertRaises(NppLoi) as e:
			T.kiem_vung_no(T.doc_tai_nhap({"warehouse_zone": "kho-lung"}))
		self.assertEqual(e.exception.ma, "BAD_PAYLOAD: kho nhận chỉ là kho bán (sale) hoặc kho date (date).")
		with self.assertRaises(NppLoi) as e:
			T.kiem_vung_no(T.doc_tai_nhap({"warehouse_zone": "date", "payable": {"amount": -1}}))
		self.assertEqual(e.exception.ma, "BAD_PAYLOAD: số tiền công nợ NCC không được âm.")
		T.kiem_vung_no(T.doc_tai_nhap({"warehouse_zone": "date", "payable": {"amount": 0}}))
		self.assertEqual(T.NGAY_TUONG_LAI, "NGAY_TUONG_LAI: Ngày nhập kho không được sau hôm nay.")
		self.assertEqual(T.NCC_KHAC, "ORG_MISMATCH: nhà cung cấp không thuộc đơn vị của bạn.")

	def test_doc_dong(self):
		co = {"SPA"}.__contains__
		d = T.doc_dong_nhap(1, self._dong(batch_code="  ", location=" Ke 1 ", expires_at="2027-06-30"), co)
		self.assertEqual((d.hang, d.ma_lo, d.vi_tri, d.han, d.nsx, d.dv, d.sl_gd, d.he_so, d.sl_cs, d.gia_von), ("SPA", None, "Ke 1",
			date(2027, 6, 30), None, "thùng", Decimal(2), Decimal(24), Decimal(48), Decimal(10000)))
		# thứ tự kiểm: mặt hàng → SL → giá vốn → ép kiểu
		with self.assertRaises(NppLoi) as e:
			T.doc_dong_nhap(1, self._dong(product_id="LA", base_qty=0), co)
		self.assertEqual((e.exception.ma, e.exception.code), ("ORG_MISMATCH: sản phẩm LA không thuộc đơn vị của bạn.", "42501"))
		with self.assertRaises(NppLoi) as e:
			T.doc_dong_nhap(1, {"base_qty": 1}, co)
		self.assertEqual(e.exception.ma, "ORG_MISMATCH: sản phẩm <NULL> không thuộc đơn vị của bạn.")
		for sl in (0, -1, None):
			with self.assertRaises(NppLoi) as e:
				T.doc_dong_nhap(3, self._dong(base_qty=sl, base_cost=-1), co)
			self.assertEqual(e.exception.ma, "BAD_PAYLOAD: dòng 3 có số lượng không hợp lệ.")
		with self.assertRaises(NppLoi) as e:
			T.doc_dong_nhap(2, self._dong(base_cost=-1, expires_at="sai"), co)
		self.assertEqual(e.exception.ma, "BAD_PAYLOAD: dòng 2 có giá vốn âm.")
		with self.assertRaises(LoiCong):
			T.doc_dong_nhap(2, self._dong(expires_at="sai"), co)
		d = T.doc_dong_nhap(1, {"product_id": "SPA", "base_qty": 5}, co)
		self.assertEqual((d.gia_von, d.he_so, d.sl_gd, d.dv), (Decimal(0), Decimal(1), None, ""))

	def test_lo_va_dau_ky(self):
		self.assertEqual(T.ma_lo_tu_dat("IN-20261001-1234", 1), "LOT-IN-20261001-1234-1")  # không đệm số
		self.assertEqual(T.ma_lo_tu_dat("DK-1", 12), "LOT-DK-1-12")
		self.assertTrue(T.la_ton_dau_ky("DK-20261116-1001"))
		for ma in ("IN-1", "dk-1", None, ""):
			self.assertFalse(T.la_ton_dau_ky(ma), ma)
		# §7.3 điểm 5: 2099-12-31 = không hạn — chỉ bỏ với mặt hàng KHÔNG quản lý hạn
		self.assertIsNone(T.han_lo(date(2099, 12, 31), False))
		self.assertEqual(T.han_lo(date(2099, 12, 31), True), date(2099, 12, 31))
		self.assertEqual(T.han_lo(date(2027, 6, 30), False), date(2027, 6, 30))
		self.assertIsNone(T.han_lo(None, True))
		self.assertEqual(T.loi_lo_trung("LOT-IN-1-1").ma, "LO_TRUNG_MA: Mã lô LOT-IN-1-1 đã có trong sổ — đổi mã lô ấy rồi ghi lại phiếu nhập kho.")

	def test_sl_dong(self):
		d = T.doc_dong_nhap(1, self._dong(), lambda h: True)
		self.assertEqual(T.sl_dong_se(d), (Decimal(2), Decimal(24)))
		d = T.doc_dong_nhap(1, self._dong(qty_tx=3), lambda h: True)  # 3 × 24 ≠ 48 → đơn vị cơ sở
		self.assertEqual(T.sl_dong_se(d), (Decimal(48), Decimal(1)))
		d = T.doc_dong_nhap(1, self._dong(qty_tx=None), lambda h: True)
		self.assertEqual(T.sl_dong_se(d), (Decimal(48), Decimal(1)))


class TestGhiThang(unittest.TestCase):
	def test_cau_khoa(self):
		self.assertEqual(T.NHAP_PHAI_NHAP, "SO_KHO_KHOA: phiếu kho lập từ màn hình phải là phiếu NHÁP — ghi sổ đi qua nút Duyệt / Hoàn thành.")
		self.assertEqual(T.CHI_SUA_GHI_CHU, "SO_KHO_KHOA: phiếu đã ghi sổ chỉ sửa được ghi chú.")
		self.assertEqual(T.loi_doi_trang_thai("draft", "posted").ma, "SO_KHO_KHOA: không đổi thẳng trạng thái phiếu kho (draft → posted) — ghi sổ / huỷ "
			"đi qua nút Duyệt / Huỷ phiếu để kho đổi theo.")
		self.assertIn("(cancelled → <NULL>)", T.loi_doi_trang_thai("cancelled", None).ma)
		self.assertEqual(T.loi_xoa_khong_nhap("XKL-TEST1", "posted").ma, "SO_KHO_KHOA: chỉ xoá được phiếu NHÁP. Phiếu XKL-TEST1 đã ghi sổ, dùng Huỷ phiếu "
			"để hàng về lại kho.")
		self.assertEqual(T.loi_xoa_khong_nhap("E1", "cancelled").ma, "SO_KHO_KHOA: chỉ xoá được phiếu NHÁP. Phiếu E1 đã huỷ, dùng Huỷ phiếu để hàng về "
			"lại kho.")
		self.assertEqual(T.loi_dong_khoa("posted").ma, "SO_KHO_KHOA: phiếu đã ghi sổ — không sửa dòng hàng được nữa.")
		self.assertEqual(T.loi_dong_khoa("cancelled").ma, "SO_KHO_KHOA: phiếu đã huỷ — không sửa dòng hàng được nữa.")

	def test_dong_sl_khong_duong(self):
		T.kiem_dong_phieu_kho([1, Decimal("0.5")])
		with self.assertRaises(NppLoi) as e:
			T.kiem_dong_phieu_kho([5, -3])
		self.assertEqual(e.exception.ma, "SO_LUONG_KHONG_HOP_LE: Dòng 2 có số lượng không lớn hơn 0.")
		with self.assertRaises(NppLoi) as e:
			T.kiem_dong_phieu_kho([0])
		self.assertEqual(e.exception.ma, "SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0.")


if __name__ == "__main__":
	unittest.main()
