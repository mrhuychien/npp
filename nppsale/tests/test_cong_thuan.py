"""Unit test thuần cho cổng tương thích (không cần bench): python -m unittest nppsale.tests.test_cong_thuan"""
import unittest

from nppsale.cong import chon as C
from nppsale.cong import dang_ky as D
from nppsale.cong import loc as L
from nppsale.cong import sql as S


def _dk_mau():
	D.SO_DANG_KY.clear()
	D.dang_ky(D.Bang(
		ten="users", nguon="`tabUser`", khoa="id",
		cot={"id": D.CotDef("{t}.`name`"), "full_name": D.CotDef("{t}.`full_name`"), "enabled": D.CotDef("{t}.`enabled`", "bool")},
	))
	D.dang_ky(D.Bang(
		ten="customers", nguon="`tabCustomer`", khoa="id",
		cot={"id": D.CotDef("{t}.`name`"), "store_name": D.CotDef("{t}.`customer_name`"), "channel": D.CotDef("{t}.`npp_kenh`"),
			"phone": D.CotDef("{t}.`npp_sdt`")},
		rls=lambda nc: None if nc.vai != "sales" else ("{t}.`name` IN (SELECT customer FROM `tabNPP Phan Cong Khach` WHERE user = %(u)s)", {"u": nc.user}),
	))
	D.dang_ky(D.Bang(
		ten="sales_orders", nguon="`tabSales Order`", khoa="id",
		cot={"id": D.CotDef("{t}.`name`"), "order_code": D.CotDef("{t}.`name`"), "customer_id": D.CotDef("{t}.`customer`"),
			"status": D.CotDef("{t}.`npp_trang_thai`"), "total": D.CotDef("{t}.`grand_total`", "tien"),
			"sales_user_id": D.CotDef("{t}.`npp_nv`"), "created_by": D.CotDef("{t}.`owner`"), "created_at": D.CotDef("{t}.`creation`", "gio")},
		quan_he=[
			D.QuanHe("customers", "customer_id", "id", False, ("sales_orders_customer_id_fkey",)),
			D.QuanHe("users", "sales_user_id", "id", False, ("sales_orders_sales_user_id_fkey",)),
			D.QuanHe("users", "created_by", "id", False, ("sales_orders_created_by_fkey",)),
			D.QuanHe("sales_order_lines", "id", "order_id", True, ("sales_order_lines_order_id_fkey",)),
		],
		rls=lambda nc: None if nc.vai != "sales" else ("{t}.`npp_nv` = %(u)s", {"u": nc.user}),
	))
	D.dang_ky(D.Bang(
		ten="sales_order_lines", nguon="`tabSales Order Item`", khoa="id",
		cot={"id": D.CotDef("{t}.`name`"), "order_id": D.CotDef("{t}.`parent`"), "quantity": D.CotDef("{t}.`qty`", "so"),
			"unit_price": D.CotDef("{t}.`rate`", "tien")},
	))


class TestChon(unittest.TestCase):
	def test_co_ban(self):
		n = C.doc_select("id, order_code, customer:customers(store_name, phone), sales_user:users!sales_orders_sales_user_id_fkey(full_name)")
		self.assertEqual([type(x).__name__ for x in n], ["Cot", "Cot", "Long", "Long"])
		self.assertEqual(n[2].bi_danh, "customer")
		self.assertEqual(n[2].ten, "customers")
		self.assertEqual(n[3].goi_y, ["sales_orders_sales_user_id_fkey"])

	def test_inner_va_xuong_dong(self):
		n = C.doc_select("product_id,\n  quantity,\n  returns!inner(order_id, status)")
		self.assertTrue(n[2].inner)
		self.assertEqual([c.ten for c in n[2].con], ["order_id", "status"])

	def test_gop(self):
		n = C.doc_select("status, count()")
		self.assertIsInstance(n[1], C.Gop)
		self.assertEqual(n[1].khoa_ra, "count")
		n = C.doc_select("total.sum()")
		self.assertEqual((n[0].ham, n[0].cot, n[0].khoa_ra), ("sum", "total", "sum"))

	def test_sao_va_ep_kieu(self):
		self.assertIsInstance(C.doc_select("*")[0], C.TatCa)
		self.assertIsInstance(C.doc_select(None)[0], C.TatCa)
		self.assertEqual(C.doc_select("id::text")[0].kieu_ep, "text")

	def test_loi(self):
		with self.assertRaises(C.LoiChon):
			C.doc_select("customers(store_name")


class TestLoc(unittest.TestCase):
	def test_or_that_cua_nppsale(self):
		h = L.doc_bieu_thuc("status.is.null,status.eq.active")
		self.assertEqual(len(h.con), 2)
		self.assertEqual((h.con[0].op, h.con[0].cot, h.con[0].gt), ("is", "status", None))
		h = L.doc_bieu_thuc("group_id.eq.abc,group_id.is.null")
		self.assertEqual(h.con[0].gt, "abc")

	def test_or_long_and_in_nhay(self):
		h = L.doc_bieu_thuc('and(a.gt.2,b.lt.5),c.in.(x,"y,z"),d.not.is.null,name.ilike.*tra*')
		self.assertIsInstance(h.con[0], L.Va)
		self.assertEqual(h.con[1].gt, ["x", "y,z"])
		self.assertTrue(h.con[2].phu_dinh)
		self.assertEqual(h.con[3].gt, "%tra%")

	def test_doc_loc_bang_long(self):
		goc, long = L.doc_loc([
			{"op": "eq", "cot": "status", "gt": "draft"},
			{"op": "eq", "cot": "customers.channel", "gt": "MT"},
			{"op": "not", "cot": "status", "op_con": "is", "gt": None},
			{"op": "or", "bieu_thuc": "channel.is.null,channel.eq.GT", "bang_ngoai": "customers"},
		])
		self.assertEqual(len(goc), 2)
		self.assertEqual(len(long["customers"]), 2)


class TestSql(unittest.TestCase):
	def setUp(self):
		_dk_mau()

	def test_select_loc_thu_tu_phan_trang_dem(self):
		nc = D.NguCanh(user="nv@x", vai="sales")
		kh, bang = S.ke_hoach_doc({"bang": "sales_orders", "select": "id, order_code, total",
			"loc": [{"op": "eq", "cot": "status", "gt": "draft"}, {"op": "in", "cot": "customer_id", "gt": ["KH-1", "KH-2"]}],
			"thu_tu": [{"cot": "created_at", "tang": False}], "range": [0, 49], "count": "exact"}, nc)
		self.assertIn("FROM `tabSales Order` q_b WHERE (q_b.`npp_nv` = %(p0)s) AND q_b.`npp_trang_thai` = %(p1)s AND q_b.`customer` IN (%(p2)s, %(p3)s)", kh.sql)
		self.assertIn("ORDER BY (q_b.`creation` IS NULL) DESC, q_b.`creation` DESC LIMIT 50 OFFSET 0", kh.sql)
		self.assertEqual(kh.tham, {"p0": "nv@x", "p1": "draft", "p2": "KH-1", "p3": "KH-2"})
		self.assertTrue(kh.sql_dem.startswith("SELECT COUNT(*) AS n FROM `tabSales Order` q_b WHERE"))
		self.assertEqual([c[0] for c in kh.cot_ra], ["id", "order_code", "total"])

	def test_khong_rls_cho_chu(self):
		kh, _ = S.ke_hoach_doc({"bang": "sales_orders", "select": "id"}, D.NguCanh(user="chu@x", vai="owner"))
		self.assertIn("WHERE 1=1", kh.sql)

	def test_long_va_inner(self):
		nc = D.NguCanh(user="nv@x", vai="sales")
		kh, _ = S.ke_hoach_doc({"bang": "sales_orders",
			"select": "id, customer:customers!inner(store_name), sales_user:users!sales_orders_sales_user_id_fkey(full_name), lines:sales_order_lines(quantity, unit_price)",
			"loc": [{"op": "eq", "cot": "customer.channel", "gt": "MT"}]}, nc)
		self.assertEqual(len(kh.long), 3)
		self.assertEqual(kh.long[1].quan_he.cot_nay, "sales_user_id")
		self.assertIn("EXISTS (SELECT 1 FROM `tabCustomer` e0 WHERE e0.`name` = q_b.`customer`", kh.sql)
		self.assertIn("e0.`npp_kenh` = ", kh.sql)
		sql, tham, cot = S.cau_long(kh.long[2], ["SO-1", "SO-2"], nc)
		self.assertIn("FROM `tabSales Order Item` q_l WHERE 1=1 AND q_l.`parent` IN (", sql)
		self.assertEqual([c[0] for c in cot], ["quantity", "unit_price"])

	def test_quan_he_nhap_nhang_bao_loi(self):
		with self.assertRaises(S.LoiCong):
			S.ke_hoach_doc({"bang": "sales_orders", "select": "id, users(full_name)"}, D.NguCanh(user="a", vai="owner"))

	def test_gop_nhom(self):
		kh, _ = S.ke_hoach_doc({"bang": "sales_orders", "select": "status, count()"}, D.NguCanh(user="a", vai="owner"))
		self.assertIn("COUNT(*) AS `g__0`", kh.sql)
		self.assertIn("GROUP BY q_b.`npp_trang_thai`", kh.sql)
		kh, _ = S.ke_hoach_doc({"bang": "sales_orders", "select": "total.sum()"}, D.NguCanh(user="a", vai="owner"))
		self.assertIn("SUM(q_b.`grand_total`) AS `g__0`", kh.sql)
		self.assertNotIn("GROUP BY", kh.sql)

	def test_cot_la_va_bang_la(self):
		with self.assertRaises(S.LoiCong) as e:
			S.ke_hoach_doc({"bang": "sales_orders", "select": "khong_co"}, D.NguCanh(user="a"))
		self.assertEqual(e.exception.ma, "42703")
		with self.assertRaises(S.LoiCong) as e:
			S.ke_hoach_doc({"bang": "khong_co_bang"}, D.NguCanh(user="a"))
		self.assertEqual(e.exception.ma, "42P01")

	def test_or_va_null_va_bool(self):
		kh, _ = S.ke_hoach_doc({"bang": "users", "select": "id",
			"loc": [{"op": "or", "bieu_thuc": "full_name.is.null,full_name.ilike.*an*"}, {"op": "eq", "cot": "enabled", "gt": True}]},
			D.NguCanh(user="a", vai="owner"))
		self.assertIn("(q_b.`full_name` IS NULL OR LOWER(q_b.`full_name`) LIKE LOWER(%(p0)s))", kh.sql)
		self.assertEqual(kh.tham["p0"], "%an%")
		self.assertEqual(kh.tham["p1"], 1)


if __name__ == "__main__":
	unittest.main()
