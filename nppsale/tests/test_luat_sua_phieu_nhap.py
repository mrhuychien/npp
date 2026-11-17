"""Luật thuần SỬA PHIẾU NHẬP ĐÃ HOÀN THÀNH (P4 — M7; đặc tả kho_mua §3.3, §7.3 điểm 7 / 34): python3 -m unittest nppsale.tests.test_luat_sua_phieu_nhap

Ép kiểu đo trên Postgres 16 của bản tham chiếu (/tmp/pg-npp, 17/11/2026): `' 12 '::numeric` = 12, `'1e3'::numeric` = 1000, `'  '::numeric` / `'true'::numeric`
/ `'2026-02-30'::date` → 22P02, `'2026-10-01T10:00:00'::date` / `' 2026-10-01 '::date` = 2026-10-01, `'[1,2]'::jsonb->>'a'` / `'"x"'::jsonb->>'a'` = NULL.
"""
import json
import unittest
from datetime import date
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.luat import kho_mua as K
from nppsale.luat import sua_phieu_nhap as S


def _ma(e) -> str:
	return e.exception.ma


class TestThamSo(unittest.TestCase):
	def test_mang_dong(self):
		for x in (None, [], {}, "x", 5, '{"a": 1}', "[]"):
			with self.assertRaises(NppLoi) as e:
				S.kiem_mang(x)
			self.assertEqual(_ma(e), "PHIEU_TRONG: Phiếu nhập phải có ít nhất một dòng hàng.")
		self.assertEqual(S.kiem_mang('[{"product_id": "A"}]'), [{"product_id": "A"}])  # chuỗi JSON (lời gọi không qua cổng)

	def test_dau_phieu_mac_dinh_va_ep_kieu(self):
		self.assertEqual(S.ncc_dau({"supplier_id": ""}, "S1"), "S1")
		self.assertEqual(S.ncc_dau(None, "S1"), "S1")
		self.assertEqual(S.ncc_dau({"supplier_id": "S2"}, "S1"), "S2")
		d = S.doc_dau({"warehouse_zone": "", "discount": "-5", "invoice_number": "  HD 1 ", "notes": " ", "vat_override": ""}, "S1", "date")
		# vùng trống → vùng cũ; giảm âm kẹp 0; số HĐ btrim; ghi chú chỉ dấu cách → NULL; thuế gõ tay '' → NULL (XOÁ số gõ tay cũ)
		self.assertEqual((d.vung, d.giam, d.so_hd, d.ghi_chu, d.thue_tay), ("date", Decimal(0), "HD 1", None, None))
		d = S.doc_dau({"discount": 1500, "vat_override": 0}, "S1", None)
		self.assertEqual((d.vung, d.giam, d.thue_tay), ("sale", Decimal(1500), Decimal(0)))  # 0 = hoá đơn không thuế (khác NULL)
		self.assertEqual(S.doc_dau({"discount": " 12 "}, "S1", "sale").giam, Decimal(12))
		self.assertEqual(S.doc_dau({"vat_override": "1e3"}, "S1", "sale").thue_tay, Decimal(1000))
		with self.assertRaises(NppLoi) as e:
			S.doc_dau({"warehouse_zone": "kho"}, "S1", "sale")
		self.assertEqual(_ma(e), "KHO_KHONG_HOP_LE: Kho nhập không hợp lệ.")
		# vùng kiểm TRƯỚC ép kiểu giảm (bước 7 trước bước 8)
		with self.assertRaises(NppLoi) as e:
			S.doc_dau({"warehouse_zone": "x", "discount": "abc"}, "S1", "sale")
		self.assertEqual(_ma(e), "KHO_KHONG_HOP_LE: Kho nhập không hợp lệ.")
		for h in ({"discount": "abc"}, {"discount": "  "}, {"vat_override": "true"}, {"vat_override": True}, {"discount": [1]}):
			with self.assertRaises(NppLoi) as e:
				S.doc_dau(h, "S1", "sale")
			self.assertEqual(_ma(e), "BAD_PAYLOAD: dữ liệu phiếu sai kiểu.", h)
		d = S.doc_dau([1, 2], "S1", "sale")  # p_head không phải object → mọi khoá NULL
		self.assertEqual((d.vung, d.giam, d.thue_tay, d.so_hd), ("sale", Decimal(0), None, None))

	def test_ngay_hd_ep_kieu_sau_cung(self):
		cu = date(2026, 10, 1)
		self.assertEqual(S.ngay_hd(S.doc_dau({}, "S1", "sale"), cu), cu)
		self.assertEqual(S.ngay_hd(S.doc_dau({"invoice_date": ""}, "S1", "sale"), cu), cu)
		self.assertEqual(S.ngay_hd(S.doc_dau({"invoice_date": "2026-11-02T10:00:00"}, "S1", "sale"), cu), date(2026, 11, 2))
		self.assertEqual(S.ngay_hd(S.doc_dau({"invoice_date": " 2026-11-02 "}, "S1", "sale"), cu), date(2026, 11, 2))
		d = S.doc_dau({"invoice_date": "2026-02-30"}, "S1", "sale")  # doc_dau KHÔNG ép kiểu ngày (hàm gốc ép ở câu UPDATE cuối)
		# phần giờ hợp lệ Postgres bỏ (đo Postgres 16, 17/11/2026)
		for x in ("2026-11-02T10:00:00Z", "2026-11-02T10:00:00.123Z", "2026-11-02 10:00:00 +0700", "2026-11-02T10:00:00+07:00", "2026-11-02T1:5"):
			self.assertEqual(S.ngay_hd(S.doc_dau({"invoice_date": x}, "S1", "sale"), cu), date(2026, 11, 2), x)
		for x in ("2026-02-30", "02/11/2026", "abc", "2026-11-02abc", "2026-11-02 abc", "2026-11-02T", "2026-11-02 10", "2026-11-02T25:00:00",
				"2026-11-02T10:61"):
			with self.assertRaises(NppLoi) as e:
				S.ngay_hd(S.doc_dau({"invoice_date": x}, "S1", "sale"), cu)
			self.assertEqual(_ma(e), S.BAD_PAYLOAD, x)
		self.assertIsNotNone(d)

	def test_dong_mac_dinh_va_ep_kieu(self):
		ds = S.doc_dong([{"product_id": "A", "unit_name": " thùng ", "quantity": "2", "unit_price": 240000, "conversion_factor": 24, "notes": ""},
			{"product_id": "", "notes": " x "}, "khong-phai-object"])
		a, b, c = ds
		self.assertEqual((a.stt, a.hang, a.dv, a.sl, a.gia, a.giam, a.thue, a.hs, a.ghi_chu, a.base),
			(1, "A", "thùng", Decimal(2), Decimal(240000), Decimal(0), Decimal(0), Decimal(24), None, Decimal(48)))
		self.assertEqual((b.hang, b.dv, b.sl, b.hs, b.ghi_chu), (None, "", Decimal(0), Decimal(1), " x "))  # ghi chú dòng KHÔNG btrim
		self.assertEqual((c.stt, c.hang, c.hs), (3, None, Decimal(1)))
		# ép kiểu sai ở dòng 3 → BAD_PAYLOAD dù dòng 1 đã sai mặt hàng (ép kiểu cả mảng trước vòng kiểm)
		with self.assertRaises(NppLoi) as e:
			S.doc_dong([{"product_id": None}, {}, {"quantity": "hai"}])
		self.assertEqual(_ma(e), S.BAD_PAYLOAD)
		self.assertEqual(S.doc_dong([{"unit_name": "\tthùng\n"}])[0].dv, "\tthùng\n")  # btrim chỉ bỏ dấu cách


class TestBonKiemDong(unittest.TestCase):
	def _d(self, **k):
		g = {"product_id": "A", "unit_name": "hộp", "quantity": 1, "unit_price": 10, "line_discount": 0, "conversion_factor": 1} | k
		return g

	def _loi(self, dong, co=("A", "B")) -> str:
		with self.assertRaises(NppLoi) as e:
			S.kiem_dong(S.doc_dong(dong), set(co))
		return _ma(e)

	def test_cau_va_thu_tu(self):
		self.assertEqual(self._loi([self._d(product_id=None)]), "HANG_KHONG_HOP_LE: Dòng 1 — mặt hàng không thuộc đơn vị.")
		self.assertEqual(self._loi([self._d(), self._d(product_id="Z")]), "HANG_KHONG_HOP_LE: Dòng 2 — mặt hàng không thuộc đơn vị.")
		self.assertEqual(self._loi([self._d(unit_name="  ")]), "DON_VI_TRONG: Dòng 1 chưa có đơn vị tính.")
		self.assertEqual(self._loi([self._d(quantity=0)]), "SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0.")
		self.assertEqual(self._loi([self._d(conversion_factor=0)]), "SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0.")
		self.assertEqual(self._loi([self._d(conversion_factor=-1)]), "SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0.")
		self.assertEqual(self._loi([self._d(unit_price=-1)]), "GIA_KHONG_HOP_LE: Dòng 1 có giá / giảm giá âm.")
		self.assertEqual(self._loi([self._d(line_discount=-1)]), "GIA_KHONG_HOP_LE: Dòng 1 có giá / giảm giá âm.")
		# đủ bốn kiểm của dòng 1 rồi mới sang dòng 2: dòng 1 giá âm thắng dòng 2 sai mặt hàng; dòng 1 đúng thì lỗi dòng 2
		self.assertEqual(self._loi([self._d(unit_price=-1), self._d(product_id=None)]), "GIA_KHONG_HOP_LE: Dòng 1 có giá / giảm giá âm.")
		self.assertEqual(self._loi([self._d(), self._d(quantity=-2, product_id="B")]), "SO_LUONG_KHONG_HOP_LE: Dòng 2 có số lượng không lớn hơn 0.")
		# trong MỘT dòng: hàng → đơn vị → SL → giá
		self.assertEqual(self._loi([self._d(product_id="Z", unit_name="", quantity=0, unit_price=-1)]),
			"HANG_KHONG_HOP_LE: Dòng 1 — mặt hàng không thuộc đơn vị.")
		self.assertEqual(self._loi([self._d(unit_name="", quantity=0, unit_price=-1)]), "DON_VI_TRONG: Dòng 1 chưa có đơn vị tính.")
		self.assertEqual(self._loi([self._d(quantity=0, unit_price=-1)]), "SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0.")
		S.kiem_dong(S.doc_dong([self._d(line_discount=100)]), {"A"})  # giảm > tiền hàng: nppsale KHÔNG kiểm ở đây

	def test_tien_am_rieng(self):
		S.kiem_tien_am(S.doc_dong([self._d(line_discount=10)]))  # tiền 0 được
		with self.assertRaises(NppLoi) as e:
			S.kiem_tien_am(S.doc_dong([self._d(), self._d(line_discount=11)]))
		self.assertEqual(_ma(e), "GIA_KHONG_HOP_LE: Dòng 2 có giảm giá lớn hơn tiền hàng.")


class TestDaXuatVaNhanh(unittest.TestCase):
	def test_da_xuat_lo(self):
		self.assertEqual(S.da_xuat_lo(48, 48, 0, 0), 0)
		self.assertEqual(S.da_xuat_lo(48, 18, 0, 0), 30)  # bán 30
		self.assertEqual(S.da_xuat_lo(48, 0, 48, 48), 0)  # rà soát chuyển hết sang kho date — nppsale lật cờ vùng, không xuất
		self.assertEqual(S.da_xuat_lo(48, 0, 18, 18), 30)  # bán 30 rồi rà soát 18
		self.assertEqual(S.da_xuat_lo(48, 0, 18, 13), 35)  # … rồi xuất lẻ 5 ở kho date
		self.assertEqual(S.da_xuat_lo(48, 40, 0, 8), 8)  # chuyển kho TAY 8 sang date: vẫn là đã xuất (nppsale lô nguồn giảm)
		self.assertEqual(S.da_xuat_lo(10, 12, 0, 0), -2)  # lô nhận thêm (hàng khách trả nhập lại) — âm giữ nguyên
		# phần rà soát chỉ trừ khi CẢ HAI vế dương (chuyển tự động vào lại kho dòng / tồn âm ở kho kia không cộng thêm "đã xuất")
		self.assertEqual(S.da_xuat_lo(10, 4, -3, 5), 6)
		self.assertEqual(S.da_xuat_lo(10, 4, 3, -2), 6)

	def test_chi_sua_gia(self):
		moi = S.doc_dong([{"product_id": "A", "unit_name": "thùng", "quantity": 2, "unit_price": 264000, "conversion_factor": 24}])
		cu = [S.DongCu(idx=1, hang="A", dv="Thung", sl=Decimal(2), hs=Decimal(24))]
		self.assertEqual(S.kiem_chi_sua_gia(moi, cu, {1: "Thung"}, "S1", "S1", "sale", "sale"), [])
		self.assertEqual(S.kiem_chi_sua_gia(moi, cu, {1: "Hop"}, "S2", "S1", "date", "sale"), ["ncc", "kho", "dong1:dv"])
		moi2 = S.doc_dong([{"product_id": "B", "unit_name": "thùng", "quantity": 3, "conversion_factor": 12}])
		self.assertEqual(S.kiem_chi_sua_gia(moi2, cu, {1: "Thung"}, "S1", "S1", "sale", "sale"), ["dong1:hang", "dong1:sl", "dong1:hs"])
		self.assertEqual(S.kiem_chi_sua_gia(moi + moi2, cu, {1: "Thung", 2: "Thung"}, "S1", "S1", "sale", "sale"), ["so_dong"])
		self.assertEqual(S.kiem_chi_sua_gia(moi, cu, {1: None}, "S1", "S1", "sale", "sale"), ["dong1:dv"])  # đơn vị chưa có trong sổ

	def test_cau_loi_moi(self):
		self.assertEqual(S.loi_chi_sua_gia(["HD-0002", "HD-0001", "HD-0001", None]).ma,
			"PHIEU_DA_XUAT_CHI_SUA_GIA: Lô của phiếu đã xuất ở HD-0001, HD-0002 — chỉ sửa được giá; muốn đổi số lượng / mặt hàng / NCC / kho thì huỷ "
			"các HĐ đã lấy lô hoặc lập phiếu trả hàng NCC / điều chỉnh kho.")
		self.assertIn("ở chứng từ khác —", S.loi_chi_sua_gia([]).ma)
		self.assertEqual(S.loi_ncc_da_tra_tien(Decimal(100000)).ma,
			"NCC_DA_TRA_TIEN: Phiếu đã trả NCC 100000 — không đổi nhà cung cấp được. Gỡ phiếu chi / Ghi trả trước.")
		self.assertEqual(S.loi_ncc_da_tra_tien(K.so(round(100000.0, 2))).ma.split(" — ")[0], "NCC_DA_TRA_TIEN: Phiếu đã trả NCC 100000")
		# số in như RAISE '%' của numeric kể cả khi nhận float của Frappe (`100000.0` → `100000`, `6.5` giữ)
		self.assertEqual(S.loi_ncc_da_tra_tien(100000.0).ma.split(" — ")[0], "NCC_DA_TRA_TIEN: Phiếu đã trả NCC 100000")
		self.assertEqual(S.loi_ncc_da_tra_tien(6.5).ma.split(" — ")[0], "NCC_DA_TRA_TIEN: Phiếu đã trả NCC 6.5")


class TestSuaGia(unittest.TestCase):
	def test_chenh_va_tach_lcv(self):
		ch = S.chenh_dong({1: 480000, 2: 50000, 3: 10}, {1: 528000, 2: 40000, 3: 10})
		self.assertEqual(ch, {1: Decimal(48000), 2: Decimal(-10000)})
		self.assertEqual(S.tach_lcv(ch), [{1: Decimal(48000)}, {2: Decimal(-10000)}])  # tăng trước, giảm sau — mỗi LCV một chiều
		self.assertEqual(S.tach_lcv(S.chenh_dong({1: 5}, {1: 5})), [])
		self.assertEqual(S.tach_lcv({1: Decimal(-400000)}), [{1: Decimal(-400000)}])
		# chênh ròng 0 vẫn hai tờ (lõi bắt tổng ≠ 0)
		self.assertEqual(len(S.tach_lcv(S.chenh_dong({1: 100, 2: 100}, {1: 150, 2: 50}))), 2)

	def test_but_toan_can(self):
		cu = S.SoPhieu(tien_hang=Decimal(480000), thue=Decimal(0), giam_ap=Decimal(0), tong=Decimal(480000))
		bt = S.but_toan_dcn(cu, S.SoPhieu(Decimal(528000), Decimal(0), Decimal(0), Decimal(528000)))
		self.assertEqual((bt.ncc, bt.trung_gian, bt.thue, bt.giam, bt.loai), (Decimal(-48000), Decimal(48000), 0, 0, "Journal Entry"))
		bt = S.but_toan_dcn(S.SoPhieu(Decimal(528000), Decimal(0), Decimal(0), Decimal(528000)), S.SoPhieu(Decimal(80000), 0, 0, Decimal(80000)))
		self.assertEqual((bt.ncc, bt.trung_gian, bt.loai), (Decimal(448000), Decimal(-448000), "Debit Note"))  # giảm nợ → Debit Note
		# giá tăng + VAT tăng + giảm đầu phiếu tăng: Nợ trung gian 20.000 + thuế 2.000 = Có NCC 17.000 + Có giảm 5.000
		bt = S.but_toan_dcn(S.SoPhieu(Decimal(100000), Decimal(10000), Decimal(0), Decimal(110000)),
			S.SoPhieu(Decimal(120000), Decimal(12000), Decimal(5000), Decimal(127000)))
		self.assertEqual((bt.ncc, bt.trung_gian, bt.thue, bt.giam), (Decimal(-17000), Decimal(20000), Decimal(2000), Decimal(-5000)))
		self.assertEqual(bt.ncc + bt.trung_gian + bt.thue + bt.giam, 0)  # cân Nợ / Có
		self.assertTrue(S.but_toan_dcn(cu, cu).rong())
		with self.assertRaises(ValueError):
			S.but_toan_dcn(cu, S.SoPhieu(Decimal(500000), Decimal(0), Decimal(0), Decimal(480000)))

	def test_so_lo_doi_gia(self):
		self.assertEqual(S.so_lo_doi_gia([(Decimal(10000), Decimal(11000)), (Decimal(5000), Decimal(5000))]), 1)
		# so KHÔNG làm tròn (IS DISTINCT FROM của numeric): 6666.66… ≠ 6666.67
		self.assertEqual(S.so_lo_doi_gia([(K.gia_von_lo(5, 160000, 0, 24), Decimal("6666.67"))]), 1)
		self.assertEqual(S.so_lo_doi_gia([(K.gia_von_lo(2, 240000, 0, 24), K.gia_von_lo(60, 10000, 0, 1))]), 0)

	def test_json_sua_gia(self):
		d = S.doc_dong([{"product_id": "A", "unit_name": "thùng", "quantity": 2, "unit_price": 264000, "conversion_factor": 24, "vat_rate": "0.1",
			"notes": "n"}])[0]
		dau = S.doc_dau({"discount": 5000, "notes": "sửa giá"}, "S1", "sale")
		so = S.SoPhieu(Decimal(528000), Decimal(52800), Decimal(5000), Decimal(575800))
		cu = {"lan_sua": [{"luc": "x", "but_toan": "DCN-0001"}], "dong": {"1": {"don_gia": 1}}, "dau_phieu": {"tong": 1}}
		x = S.json_sua_gia(cu, [(1, d, 528000.0)], dau, so, {"luc": "y", "nguoi": "kt", "lcv": ["SGN-0002"], "but_toan": "DCN-0002"})
		self.assertEqual(x["dong"], {"1": {"don_gia": 264000, "giam_dong": 0, "thue_suat": 0.1, "thanh_tien": 528000, "ghi_chu": "n"}})
		self.assertEqual(x["dau_phieu"], {"giam": 5000, "giam_ap": 5000, "thue_go_tay": None, "tien_hang": 528000, "thue": 52800, "tong": 575800})
		self.assertEqual([y["but_toan"] for y in x["lan_sua"]], ["DCN-0001", "DCN-0002"])  # lần sửa nối tiếp
		# chữ JSON lưu ở sổ: số nguyên không mang `.0` (đọc trên Desk / cổng CAST như nhau)
		self.assertIn('"don_gia": 264000, "giam_dong": 0, "thue_suat": 0.1, "thanh_tien": 528000', json.dumps(x["dong"]))
		self.assertEqual(S.json_sua_gia(None, [], S.doc_dau({"vat_override": 0}, "S1", "sale"), so, {})["dau_phieu"]["thue_go_tay"], 0)


if __name__ == "__main__":
	unittest.main()
