"""Test tích hợp của cổng trên site thử (cần bench): bench --site poc.local run-tests --module nppsale.tests.test_cong_tich_hop

Khai tạm vài bảng nppsale trỏ vào DocType lõi đang có dữ liệu PoC (Sales Order, Sales Order Item, Customer, User) — sổ đăng ký
thật nằm ở nppsale/cong/bang/ và làm theo blueprint 02."""
import frappe
from frappe.tests import IntegrationTestCase

from nppsale.cong import api
from nppsale.cong import dang_ky as D
from nppsale.cong.sql import LoiCong
from nppsale.cong.truy_van import ap_mot, doc


def _khai_tam():
	D.dang_ky(D.Bang(ten="t_users", nguon="`tabUser`", cot={"id": D.CotDef("{t}.`name`"), "full_name": D.CotDef("{t}.`full_name`"),
		"enabled": D.CotDef("{t}.`enabled`", "bool")}))
	D.dang_ky(D.Bang(ten="t_customers", nguon="`tabCustomer`", cot={"id": D.CotDef("{t}.`name`"),
		"store_name": D.CotDef("{t}.`customer_name`"), "group": D.CotDef("{t}.`customer_group`")}))
	D.dang_ky(D.Bang(ten="t_sales_orders", nguon="`tabSales Order`", cot={
		"id": D.CotDef("{t}.`name`"), "customer_id": D.CotDef("{t}.`customer`"), "status": D.CotDef("{t}.`status`"),
		"total": D.CotDef("{t}.`grand_total`", "tien"), "order_date": D.CotDef("{t}.`transaction_date`", "ngay"),
		"created_at": D.CotDef("{t}.`creation`", "gio"), "created_by": D.CotDef("{t}.`owner`"), "docstatus": D.CotDef("{t}.`docstatus`", "so")},
		quan_he=[D.QuanHe("t_customers", "customer_id", "id", False, ("so_customer_fkey",)),
			D.QuanHe("t_users", "created_by", "id", False, ("so_created_by_fkey",)),
			D.QuanHe("t_sales_order_lines", "id", "order_id", True)],
		rls=lambda nc: None if nc.vai != "sales" else ("{t}.`owner` = %(u)s", {"u": nc.user})))
	D.dang_ky(D.Bang(ten="t_sales_order_lines", nguon="`tabSales Order Item`", cot={
		"id": D.CotDef("{t}.`name`"), "order_id": D.CotDef("{t}.`parent`"), "product_id": D.CotDef("{t}.`item_code`"),
		"quantity": D.CotDef("{t}.`qty`", "so"), "unit_price": D.CotDef("{t}.`rate`", "tien"), "unit_name": D.CotDef("{t}.`uom`"),
		"idx": D.CotDef("{t}.`idx`", "so")}))


NC_CHU = D.NguCanh(user="Administrator", vai="owner")


class TestCongTichHop(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_khai_tam()

	def test_dem_phan_trang_thu_tu(self):
		tong = frappe.db.count("Sales Order")
		self.assertGreater(tong, 5)
		ket = doc({"bang": "t_sales_orders", "select": "id, total, created_at", "thu_tu": [{"cot": "created_at", "tang": False}],
			"range": [0, 4], "count": "exact"}, NC_CHU)
		self.assertEqual(ket["count"], tong)
		self.assertEqual(len(ket["data"]), 5)
		mong = frappe.get_all("Sales Order", fields=["name"], order_by="creation desc", limit=5, pluck="name")
		self.assertEqual([r["id"] for r in ket["data"]], mong)
		self.assertIsInstance(ket["data"][0]["total"], (int, float))
		self.assertIn("+07:00", ket["data"][0]["created_at"])

	def test_long_nhieu_mot_va_mot_nhieu(self):
		ten = frappe.get_all("Sales Order", pluck="name", order_by="creation asc", limit=1)[0]
		so = frappe.get_doc("Sales Order", ten)
		ket = doc({"bang": "t_sales_orders", "select": "id, customer:t_customers(store_name), lines:t_sales_order_lines(product_id, quantity, idx)",
			"loc": [{"op": "eq", "cot": "id", "gt": ten}], "thu_tu": [{"cot": "idx", "bang_ngoai": "lines"}]}, NC_CHU)
		r = ket["data"][0]
		self.assertEqual(r["customer"]["store_name"], frappe.db.get_value("Customer", so.customer, "customer_name"))
		self.assertEqual([x["product_id"] for x in r["lines"]], [d.item_code for d in so.items])
		self.assertEqual(sum(x["quantity"] for x in r["lines"]), sum(d.qty for d in so.items))

	def test_inner_loc_bang_long(self):
		kh = frappe.get_all("Sales Order", pluck="customer", limit=1)[0]
		ten_kh = frappe.db.get_value("Customer", kh, "customer_name")
		ket = doc({"bang": "t_sales_orders", "select": "id, customer:t_customers!inner(store_name)",
			"loc": [{"op": "eq", "cot": "customer.store_name", "gt": ten_kh}], "count": "exact"}, NC_CHU)
		self.assertEqual(ket["count"], frappe.db.count("Sales Order", {"customer": kh}))
		self.assertTrue(all(r["customer"]["store_name"] == ten_kh for r in ket["data"]))

	def test_or_va_gop_nhom(self):
		ket = doc({"bang": "t_sales_orders", "select": "status, count()"}, NC_CHU)
		dem = {r["status"]: r["count"] for r in ket["data"]}
		self.assertEqual(sum(dem.values()), frappe.db.count("Sales Order"))
		ket = doc({"bang": "t_sales_orders", "select": "id", "loc": [{"op": "or", "bieu_thuc": "docstatus.eq.2,status.eq.Draft"}],
			"count": "exact", "head": True}, NC_CHU)
		mong = frappe.db.sql("select count(*) from `tabSales Order` where docstatus=2 or status='Draft'")[0][0]
		self.assertEqual(ket["count"], mong)
		self.assertIsNone(ket["data"])

	def test_rls_theo_vai(self):
		nc = D.NguCanh(user="khong-ai@x.vn", vai="sales")
		ket = doc({"bang": "t_sales_orders", "select": "id", "count": "exact"}, nc)
		self.assertEqual(ket["count"], 0)
		nc = D.NguCanh(user="Administrator", vai="sales")
		ket = doc({"bang": "t_sales_orders", "select": "id", "count": "exact"}, nc)
		self.assertEqual(ket["count"], frappe.db.count("Sales Order", {"owner": "Administrator"}))

	def test_mot_dong(self):
		ten = frappe.get_all("Sales Order", pluck="name", limit=1)[0]
		ket = ap_mot(doc({"bang": "t_sales_orders", "select": "id", "loc": [{"op": "eq", "cot": "id", "gt": ten}]}, NC_CHU), "one")
		self.assertEqual(ket["data"]["id"], ten)
		ket = ap_mot(doc({"bang": "t_sales_orders", "select": "id", "loc": [{"op": "eq", "cot": "id", "gt": "khong-co"}]}, NC_CHU), "maybe")
		self.assertIsNone(ket["data"])
		with self.assertRaises(LoiCong):
			ap_mot(doc({"bang": "t_sales_orders", "select": "id"}, NC_CHU), "one")

	def test_cua_api_tra_loi_kieu_postgrest(self):
		frappe.set_user("Administrator")
		ket = api.truy_van({"bang": "khong_co", "select": "id"})
		self.assertEqual(ket["error"]["code"], "42P01")
		ket = api.truy_van({"bang": "t_sales_orders", "hanh_dong": "insert", "gia_tri": {"id": "x"}})
		self.assertEqual(ket["error"]["code"], "42501")
		ket = api.truy_van({"bang": "t_sales_orders", "select": "id", "limit": 2})
		self.assertEqual(len(ket["data"]), 2)
		self.assertEqual(ket["status"], 200)
