"""Luật thuần nền báo cáo P6 (mốc M0) — không cần bench:

	python -m unittest nppsale.tests.test_bao_cao_thuan

- `nppsale.luat.so` (L12: numeric ra JSON, ROUND nửa xa 0 — dời từ rpc/cong_no_doc.py), `nppsale.luat.bao_cao.moc_ky` (L5);
- 🔧 C1 (§3.3): giá trị lọc cột `gio` có múi giờ → giờ site (`cong.sql.gio_loc` / `_ep`) — 'Z' không còn lệch 7 giờ;
- nguồn theo bộ lọc của cổng (`Bang.nguon_theo_loc`) + luật chọn nguồn lô còn hàng của `batches` (`cong.bang.kho.nguon_theo_loc` — §2.2 "🔧 Hiệu năng
  NGUON_LO"): chỉ khi lọc mức gốc `qty_on_hand > x` (x ≥ 0) / `>= x` (x > 0), không phủ định.
"""
from __future__ import annotations

import datetime as dt
import unittest
from decimal import Decimal
from zoneinfo import ZoneInfo

from nppsale.cong import dang_ky as D
from nppsale.cong import loc as Lc
from nppsale.cong import sql as S
from nppsale.luat import bao_cao as LB
from nppsale.luat import so


class TestSo(unittest.TestCase):
	def test_d_ra_tron(self):
		self.assertEqual(so.d(None), Decimal(0))
		self.assertEqual(so.d(0.1) + so.d(0.2), Decimal("0.3"))  # Decimal(str()) — không cộng float
		self.assertIs(type(so.ra(Decimal("1200.000"))), int)
		self.assertEqual(so.ra(Decimal("12.5")), 12.5)
		# ROUND của Postgres / MariaDB DECIMAL: nửa XA số 0 (round() của Python là nửa về số chẵn: round(2.5) = 2)
		self.assertEqual([so.tron(Decimal(x)) for x in ("2.5", "-2.5", "0.5", "1.49", "3.5")], [3, -3, 1, 1, 4])
		self.assertEqual(so.tron(Decimal("12.345"), 2), Decimal("12.35"))
		self.assertEqual(so.tron(Decimal("-12.345"), 2), Decimal("-12.35"))


class TestMocKy(unittest.TestCase):
	def test_moc_ky_gio_vn(self):
		"""[tu 00:00, den+1 00:00) — chứng từ ghi sổ 23:59 ngày cuối kỳ vẫn trong kỳ, 00:00 ngày sau thì không (L5)."""
		tu, toi = LB.moc_ky(dt.date(2026, 11, 1), dt.date(2026, 11, 30))
		self.assertEqual((tu, toi), (dt.datetime(2026, 11, 1), dt.datetime(2026, 12, 1)))
		self.assertTrue(tu <= dt.datetime(2026, 11, 30, 23, 59, 59) < toi)
		self.assertFalse(dt.datetime(2026, 12, 1) < toi)
		self.assertEqual(LB.moc_ky(dt.date(2026, 12, 31), dt.date(2026, 12, 31))[1], dt.datetime(2027, 1, 1))
		self.assertEqual((LB.MA_QUA_HAN, LB.CAU_QUA_HAN), ("57014", "canceling statement due to statement timeout"))
		self.assertEqual((LB.HET_GIO_BAO_CAO, LB.HET_GIO_NHANH), (40, 8))


class TestC1GioLoc(unittest.TestCase):
	def test_gio_loc(self):
		"""Chuỗi / datetime CÓ múi giờ → giờ site (VN) không múi giờ; KHÔNG múi giờ / chỉ ngày / chữ lạ → giữ nguyên."""
		g = S.gio_loc
		self.assertEqual(g("2026-11-30T17:00:00.000Z"), "2026-12-01 00:00:00.000000")  # toISOString() của 00:00 VN
		self.assertEqual(g("2026-12-01T00:00:00+07:00"), "2026-12-01 00:00:00.000000")
		self.assertEqual(g("2026-11-30T12:00:00-05:00"), "2026-12-01 00:00:00.000000")
		self.assertEqual(g("2026-11-30 17:00:00+00"), "2026-12-01 00:00:00.000000")
		self.assertEqual(g("2026-11-30T16:59:59.999Z"), "2026-11-30 23:59:59.999000")
		for v in ("2026-12-01T00:00:00", "2026-12-01", "abc", "", 5):
			self.assertEqual(g(v), v)
		self.assertEqual(g(dt.datetime(2026, 11, 30, 17, tzinfo=dt.UTC)), "2026-12-01 00:00:00.000000")
		naive = dt.datetime(2026, 11, 30, 17)
		self.assertIs(g(naive), naive)

	def test_mui_gio_site_theo_ham_gan(self):
		"""Phía Frappe gắn hàm đọc System Settings.time_zone (`dat_mui_gio`) — giờ site khác VN thì đổi theo đúng giờ ấy."""
		cu = S._MUI_GIO["ham"]
		try:
			S.dat_mui_gio(lambda: ZoneInfo("Asia/Bangkok"))  # +07:00 — cùng lệch
			self.assertEqual(S.gio_loc("2026-11-30T17:00:00Z"), "2026-12-01 00:00:00.000000")
			S.dat_mui_gio(lambda: ZoneInfo("UTC"))
			self.assertEqual(S.gio_loc("2026-12-01T00:00:00+07:00"), "2026-11-30 17:00:00.000000")
		finally:
			S.dat_mui_gio(cu)

	def test_ep_theo_kieu_cot(self):
		gio, ngay, chu, bo = D.CotDef("x", "gio"), D.CotDef("x", "ngay"), D.CotDef("x"), D.CotDef("x", "bool")
		self.assertEqual(S._ep(gio, "2026-11-30T17:00:00.000Z"), "2026-12-01 00:00:00.000000")
		self.assertEqual(S._ep(ngay, "2026-11-30T17:00:00.000Z"), "2026-11-30T17:00:00.000Z")  # cột DATE: chuỗi giữ nguyên
		self.assertEqual(S._ep(chu, "2026-11-30T17:00:00Z"), "2026-11-30T17:00:00Z")
		self.assertEqual((S._ep(bo, "true"), S._ep(bo, False), S._ep(gio, None)), (1, 0, None))

	def test_ke_hoach_doc_doi_gia_tri_loc(self):
		"""Câu cổng: mọi toán tử so sánh / in trên cột `gio` nhận giá trị đã đổi (bộ lọc của bảng lồng cũng qua `_ep`)."""
		D.SO_DANG_KY.clear()
		D.dang_ky(D.Bang(ten="khach", nguon="`tabCustomer`", cot={"id": D.CotDef("{t}.`name`"), "created_at": D.CotDef("{t}.`creation`", "gio")}))
		nc = D.NguCanh(user="a", vai="owner")
		kh, _ = S.ke_hoach_doc({"bang": "khach", "select": "id", "loc": [{"op": "gte", "cot": "created_at", "gt": "2026-11-30T17:00:00.000Z"},
			{"op": "lt", "cot": "created_at", "gt": "2026-12-31T17:00:00+00:00"},
			{"op": "in", "cot": "created_at", "gt": ["2026-12-01T00:00:00+07:00", "2026-12-02"]}]}, nc)
		self.assertEqual(kh.tham, {"p0": "2026-12-01 00:00:00.000000", "p1": "2027-01-01 00:00:00.000000", "p2": "2026-12-01 00:00:00.000000",
			"p3": "2026-12-02"})


class TestHangPhuLucA(unittest.TestCase):
	def test_hang_dung_lai_cua_p4(self):
		"""Phụ lục A (đặc tả báo cáo) ↔ hằng P4 đã dựng (`cong/bang/kho.py` — DÙNG LẠI, không chép): A-1 ba nhánh xuất (HĐ có kho gồm dòng đổi, không
		đầu kỳ; xuất lẻ `XKL-` GIÁ 0 theo "Chốt chéo" / Q2; trả NCC giá lô từ sổ kho — S2), A-2 hai nhánh nhập lại nối theo Link `npp_phieu_tra`;
		điều kiện ngày chèn vào TỪNG nhánh."""
		from nppsale.cong.bang import kho as K

		x = " ".join(K.nguon_dong_xuat("AND {t}.`posting_date` BETWEEN %(tu)s AND %(den)s").split())
		self.assertIn("si.`docstatus` = 1 AND si.`is_return` = 0 AND si.`update_stock` = 1 AND IFNULL(si.`is_opening`, 'No') = 'No' "
			"AND si.`posting_date` BETWEEN %(tu)s AND %(den)s", x)
		self.assertIn("se.`docstatus` = 1 AND se.`npp_loai` = 'xuat_le' AND se.`posting_date` BETWEEN %(tu)s AND %(den)s", x)
		self.assertIn("p.`docstatus` = 1 AND p.`is_return` = 1 AND p.`update_stock` = 1 AND p.`npp_loai` = 'tra_ncc' AND p.`posting_date` BETWEEN", x)
		self.assertIn("CASE WHEN IFNULL(se.`npp_loai`, '') IN ('xuat_le', 'chuyen_kho', 'chuyen_date_tu_dong') THEN 0", x)  # Q2 = 0 (chốt chéo)
		self.assertIn("ABS(SUM(sle.`stock_value_difference`)) / NULLIF(ABS(SUM(sle.`actual_qty`)), 0)", x)  # GIA_TRA_NCC (S2 / V81)
		self.assertIn("sle.`voucher_detail_no` = pii.`name` AND sle.`is_cancelled` = 0", x)
		self.assertIn("IFNULL(ii.`incoming_rate`, 0) AS gia", x)
		self.assertEqual(x.count("UNION ALL"), 2)
		n = " ".join(K.nguon_dong_nhap_lai("AND {t}.`posting_date` >= %(tu)s").split())
		self.assertIn("se.`npp_loai` = 'nhap_lai_tra' AND IFNULL(se.`npp_phieu_tra`, '') <> '' AND se.`posting_date` >= %(tu)s", n)
		self.assertIn("si.`is_return` = 1 AND si.`update_stock` = 1 AND IFNULL(si.`npp_phieu_tra`, '') <> '' AND si.`posting_date` >= %(tu)s", n)
		self.assertEqual(n.count("UNION ALL"), 1)
		self.assertEqual(K.NGUON_DONG_XUAT, K.nguon_dong_xuat())
		self.assertEqual(K.NGUON_DONG_NHAP_LAI, K.nguon_dong_nhap_lai())


class TestNguonTheoLoc(unittest.TestCase):
	def test_luat_chon_nguon_lo_con_ton(self):
		from nppsale.cong.bang import kho as K

		con = K.NGUON_LO_CON_TON
		d = Lc.Dieu
		self.assertEqual(K.nguon_theo_loc([d("gt", "qty_on_hand", 0)]), con)
		self.assertEqual(K.nguon_theo_loc([d("eq", "warehouse_zone", "sale"), d("gt", "qty_on_hand", "0"), d("lt", "qty_on_hand", 10)]), con)
		self.assertEqual(K.nguon_theo_loc([d("gte", "qty_on_hand", 1)]), con)
		self.assertEqual(K.nguon_theo_loc([d("gt", "qty_on_hand", 5.5)]), con)
		for loc in ([], [d("gte", "qty_on_hand", 0)], [d("gt", "qty_on_hand", -1)], [d("lt", "qty_on_hand", 10)], [d("eq", "qty_on_hand", 0)],
				[d("gt", "qty_on_hand", 0, phu_dinh=True)], [Lc.Hoac([d("gt", "qty_on_hand", 0), d("eq", "status", "x")])],
				[d("gt", "qty_initial", 0)], [d("gt", "qty_on_hand", None)], [d("gt", "qty_on_hand", "abc")], [d("gt", "qty_on_hand", True)]):
			self.assertIsNone(K.nguon_theo_loc(loc), loc)
		# nguồn đủ giữ nhánh lô chưa phát sinh + gộp toàn bộ gói lô; nguồn còn tồn đi từ Batch `batch_qty > 0`
		self.assertIn("NOT EXISTS", K.NGUON_LO)
		self.assertNotIn("batch_qty", K.NGUON_LO)
		self.assertNotIn("NOT EXISTS", con)
		self.assertEqual(con.count("STRAIGHT_JOIN `tabSerial and Batch Entry` e ON e.`batch_no` = b1.`name`"), 2)
		self.assertEqual(con.count("b1.`batch_qty` > 0"), 2)
		self.assertIn("FROM `tabBin` bi", con)  # lô ảo hàng không lô vẫn có

	def test_ke_hoach_doc_dung_nguon_theo_loc(self):
		D.SO_DANG_KY.clear()
		D.dang_ky(D.Bang(ten="lo", nguon="(NGUON_DU)", cot={"id": D.CotDef("{t}.`name`"), "ton": D.CotDef("{t}.`ton`", "so")},
			nguon_theo_loc=lambda dk: "(NGUON_CON)" if any(getattr(x, "cot", None) == "ton" for x in dk) else None))
		nc = D.NguCanh(user="a", vai="owner")
		kh, _ = S.ke_hoach_doc({"bang": "lo", "select": "id", "loc": [{"op": "gt", "cot": "ton", "gt": 0}], "count": "exact"}, nc)
		self.assertIn("FROM (NGUON_CON) q_b", kh.sql)
		self.assertIn("FROM (NGUON_CON) q_b", kh.sql_dem)
		kh, _ = S.ke_hoach_doc({"bang": "lo", "select": "id"}, nc)
		self.assertIn("FROM (NGUON_DU) q_b", kh.sql)
		self.assertIs(D.lay("lo").nguon, "(NGUON_DU)")  # sổ đăng ký không bị đổi


if __name__ == "__main__":
	unittest.main()
