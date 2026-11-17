"""Luật thuần LÔ + KHO CẬN DATE (P4 — M5; đặc tả kho_mua §2.7, §3.20, §4.6, §7.3 điểm 6 / 20 / 37): python3 -m unittest nppsale.tests.test_luat_lo_kho

Câu lỗi lấy nguyên văn từ thân trigger / hàm nppsale (scratchpad kho_mua/src/_trg_khoa_ghi_thang_lo.sql, batches_auto_zone.sql,
refresh_warehouse_zones.sql), kết quả đã chạy trên Postgres tham chiếu (tệp vàng du_lieu/kho_mua_mau.json — V56, V57, V59) và ràng buộc bảng `batches`
(`pg_constraint` / `pg_policy` của bản tham chiếu).
"""
import unittest
from datetime import date, datetime
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong
from nppsale.luat import lo_kho as L

HOM_NAY = date(2026, 11, 17)


class TestCau(unittest.TestCase):
	def test_cau_trigger_mig_170(self):
		self.assertEqual(L.TAO_LO_CO_TON, "SO_KHO_KHOA: lô có tồn phải vào kho qua phiếu Nhập kho hoặc phiếu kiểm kê — tạo lô ở đây chỉ được tạo lô "
			"rỗng (số lượng 0).")
		self.assertEqual(L.SUA_TON, "SO_KHO_KHOA: không sửa thẳng số tồn của lô — lập phiếu kiểm kê để điều chỉnh (có duyệt, có thẻ kho, có ghi hao hụt).")
		self.assertEqual(L.SUA_GIA, "SO_KHO_KHOA: không sửa giá vốn của lô đang có tồn — giá vốn đã đi vào các phiếu xuất trước đó.")
		self.assertEqual(L.DOI_HANG, "SO_KHO_KHOA: không đổi sản phẩm / đơn vị của một lô.")
		# DELETE: `OLD.qty_on_hand` numeric(18,6) — V59 "lô còn 7.000000"
		e = L.loi_xoa_con_ton(7)
		self.assertEqual((e.ma, e.code), ("SO_KHO_KHOA: lô còn 7.000000 trong kho — không xoá được. Điều chỉnh về 0 qua phiếu kiểm kê trước.", "P0001"))
		self.assertEqual(L.loi_xoa_con_ton(Decimal("2.5")).ma[:31], "SO_KHO_KHOA: lô còn 2.500000 tr")

	def test_cau_rang_buoc_bang(self):
		e = L.loi_xoa_co_so_kho()
		self.assertEqual((e.ma, e.thong_diep), ("23503", 'update or delete on table "batches" violates foreign key constraint '
			'"stock_entry_lines_batch_id_fkey" on table "stock_entry_lines"'))
		e = L.loi_rls()
		self.assertEqual((e.ma, e.thong_diep, e.http), ("42501", 'new row violates row-level security policy for table "batches"', 403))
		self.assertEqual((L.loi_khong_null("expires_at").ma, L.loi_khong_null("expires_at").thong_diep), ("23502",
			'null value in column "expires_at" of relation "batches" violates not-null constraint'))
		self.assertEqual((L.loi_vung().ma, L.loi_vung().thong_diep), ("23514",
			'new row for relation "batches" violates check constraint "batches_warehouse_zone_check"'))
		self.assertEqual((L.loi_hang().ma, L.loi_hang().thong_diep), ("23503",
			'insert or update on table "batches" violates foreign key constraint "batches_product_id_fkey"'))
		self.assertEqual(L.loi_cot_la("abc").thong_diep, "Could not find the 'abc' column of 'batches' in the schema cache")
		self.assertEqual(L.ORG_MISMATCH_RA_SOAT, "ORG_MISMATCH: không rà kho của đơn vị khác được.")

	def test_cau_moi_cua_ban_frappe(self):
		self.assertEqual(L.loi_lo_trung("R0").ma, "LO_TRUNG_MA: Mã lô R0 đã có trong sổ — chọn mã lô khác.")
		self.assertEqual(L.KHONG_SUA_TRUONG, "SO_KHO_KHOA: không sửa được trường này của lô.")
		self.assertEqual(L.KHONG_LO, "SO_KHO_KHOA: mặt hàng này không quản lý theo lô.")


class TestThuTuKiem(unittest.TestCase):
	CU = {"qty_on_hand": 7, "qty_initial": 7, "unit_cost": 8000, "product_id": "SPP", "org_id": "o1", "status": "available",  # noqa: RUF012
		"received_at": datetime(2026, 11, 12, 8, 0), "zone_moved_at": None, "zone_moved_by": None, "created_at": datetime(2026, 11, 12, 8, 0)}

	def _loi(self, moi, ton=7):
		with self.assertRaises(NppLoi) as c:
			L.kiem_sua(self.CU, moi, ton)
		return c.exception.ma

	def test_ton_truoc_gia_truoc_hang(self):
		# một lệnh vừa đổi tồn vừa đổi giá / mặt hàng → câu TỒN (trigger kiểm tồn đầu tiên — §4.6 S7)
		self.assertEqual(self._loi({"qty_on_hand": 8, "unit_cost": 9000, "product_id": "X"}), L.SUA_TON)
		self.assertEqual(self._loi({"qty_initial": 0}), L.SUA_TON)
		self.assertEqual(self._loi({"unit_cost": 9000, "product_id": "X"}), L.SUA_GIA)
		self.assertEqual(self._loi({"product_id": "X"}), L.DOI_HANG)
		self.assertEqual(self._loi({"org_id": "o2"}), L.DOI_HANG)
		self.assertEqual(self._loi({"product_id": "X", "status": "cancelled"}), L.DOI_HANG)

	def test_gia_chi_chan_khi_lo_con_ton(self):
		# lô rỗng (Σ mọi kho = 0) → đổi giá được; còn tồn ở kho KIA (dòng này 0 — V82d) → vẫn chặn (§7.3 điểm 37)
		self.assertIsNone(L.kiem_sua(self.CU, {"unit_cost": 9000}, 0))
		self.assertEqual(self._loi({"unit_cost": 12000}, Decimal(4)), L.SUA_GIA)

	def test_is_distinct_from(self):
		# gửi lại đúng giá trị đang có (màn luôn gửi lại) → không lỗi; số so theo giá trị (7 = 7.000000), NULL chỉ bằng NULL
		self.assertIsNone(L.kiem_sua(self.CU, {"qty_on_hand": Decimal("7.000000"), "qty_initial": 7.0, "unit_cost": "8000", "product_id": "SPP",
			"org_id": "o1", "status": "available", "zone_moved_at": None, "received_at": datetime(2026, 11, 12, 8, 0)}, 7))
		self.assertEqual(self._loi({"qty_on_hand": None}), L.SUA_TON)
		self.assertEqual(self._loi({"unit_cost": Decimal("8000.000001")}), L.SUA_GIA)  # lệch > 5e-7
		self.assertIsNone(L.kiem_sua(self.CU, {"unit_cost": Decimal("8000.0000004")}, 7))
		self.assertTrue(L.khac({"a": None}, {"a": 0}, "a"))
		self.assertFalse(L.khac({}, {"a": 1}, "a"))  # cột vắng = giữ nguyên

	def test_cot_loi_giu(self):
		for cot, v in (("status", "cancelled"), ("received_at", datetime(2026, 11, 13)), ("zone_moved_at", datetime(2026, 11, 13)),
				("zone_moved_by", "u1"), ("created_at", datetime(2026, 11, 13))):
			self.assertEqual(self._loi({cot: v}), L.KHONG_SUA_TRUONG, cot)

	def test_them_chi_lo_rong(self):
		L.kiem_them({"qty_initial": 0, "qty_on_hand": 0})
		L.kiem_them({"qty_initial": None})  # COALESCE(NULL, 0) — NOT NULL kiểm sau
		for g in ({"qty_on_hand": 5}, {"qty_initial": 5, "qty_on_hand": 0}, {"qty_on_hand": Decimal("0.5")}, {"qty_on_hand": -1}):
			with self.assertRaises(NppLoi) as c:
				L.kiem_them(g)
			self.assertEqual(c.exception.ma, L.TAO_LO_CO_TON)


class TestKhoDate(unittest.TestCase):
	def test_nguong_dung_bang_van_vao(self):
		# V56 (ngưỡng 45): +44, +45 vào date; +46 ở bán; ngưỡng trống → 30
		self.assertTrue(L.can_date(date(2026, 12, 31), HOM_NAY, 45))  # +44
		self.assertTrue(L.can_date(date(2027, 1, 1), HOM_NAY, 45))  # +45
		self.assertFalse(L.can_date(date(2027, 1, 2), HOM_NAY, 45))  # +46
		self.assertTrue(L.can_date("2026-12-17", HOM_NAY, None))  # +30
		self.assertFalse(L.can_date("2026-12-18", HOM_NAY, None))
		self.assertFalse(L.can_date(None, HOM_NAY, 365))  # không hạn

	def test_vung_sau_sua(self):
		han_gan, han_xa = date(2026, 12, 1), date(2027, 6, 1)
		# khoá expires_at có mặt (kể cả không đổi — V82a) → sale vào date; vắng → không chạy trigger (V82c)
		self.assertEqual(L.vung_sau_sua("sale", {"expires_at": han_gan, "location": "Ke 2"}, han_gan, HOM_NAY, 45), "date")
		self.assertEqual(L.vung_sau_sua("sale", {"location": "Ke 2"}, han_gan, HOM_NAY, 45), "sale")
		# không bao giờ tự về sale (V56: +44 → +300 vẫn date)
		self.assertEqual(L.vung_sau_sua("date", {"expires_at": han_xa}, han_xa, HOM_NAY, 45), "date")
		# đổi vùng gửi lên: sale → date được; date → sale khi hạn xa được; date → sale kèm hạn gần → trigger lật về date
		self.assertEqual(L.vung_sau_sua("sale", {"warehouse_zone": "date"}, han_xa, HOM_NAY, 45), "date")
		self.assertEqual(L.vung_sau_sua("date", {"warehouse_zone": "sale"}, han_xa, HOM_NAY, 45), "sale")
		self.assertEqual(L.vung_sau_sua("date", {"warehouse_zone": "sale", "expires_at": han_gan}, han_gan, HOM_NAY, 45), "date")
		# đổi vùng sang sale KHÔNG kèm hạn: trigger không chạy (nơi gọi chặn HANG_GAN_HAN)
		self.assertEqual(L.vung_sau_sua("date", {"warehouse_zone": "sale"}, han_gan, HOM_NAY, 45), "sale")

	def test_can_ra_soat(self):
		lo = [L.LoBan("L46", "P", Decimal(10), date(2027, 1, 2)), L.LoBan("L91", "P", Decimal(0), date(2027, 2, 16)),
			L.LoBan("L0", "A", Decimal("0.0"), date(2026, 12, 1)), L.LoBan("K", "B", Decimal(3), None), L.LoBan("A2", "A", Decimal(2), date(2026, 12, 1)),
			L.LoBan("Z", "A", Decimal(1), date(2027, 6, 1)), L.LoBan("Z1", "A", Decimal(1), date(2027, 1, 2))]
		# V57: ngưỡng 100 → L46 (tồn 10) chuyển, L91 (tồn 0) không, không hạn không, hạn xa không; thứ tự MẶT HÀNG rồi mã lô (Z1 của A trước L46 của P)
		self.assertEqual([x.ma for x in L.can_ra_soat(lo, HOM_NAY, 100)], ["A2", "Z1", "L46"])
		self.assertEqual([x.ma for x in L.can_ra_soat(lo, HOM_NAY, 45)], ["A2"])

	def test_vung_hop_le(self):
		self.assertEqual(L.vung_hop_le("date"), "date")
		for v, ma in ((None, "23502"), ("kho", "23514"), ("", "23514")):
			with self.assertRaises(LoiCong) as c:
				L.vung_hop_le(v)
			self.assertEqual(c.exception.ma, ma)

	def test_ghi_chu(self):
		self.assertEqual(L.ghi_chu_ra_soat(None), "Rà soát kho date: lô còn hạn không quá 30 ngày tự chuyển sang kho hàng date")
		self.assertEqual(L.ghi_chu_doi_han("L5", 45), "Sửa hạn lô L5: còn hạn không quá 45 ngày — tự chuyển sang kho hàng date")
		self.assertEqual(L.ghi_chu_doi_vung("L5", "sale"), "Đổi vùng lô L5 sang kho hàng bán")


if __name__ == "__main__":
	unittest.main()
