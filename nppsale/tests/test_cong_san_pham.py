"""Bảng sản phẩm trên cổng (cần bench): bench --site poc.local run-tests --module nppsale.tests.test_cong_san_pham"""
import frappe
from frappe.tests import IntegrationTestCase

from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.ghi import ghi
from nppsale.cong.sql import LoiCong
from nppsale.cong.truy_van import doc
from nppsale.luat.sdt import email_ky_thuat
from nppsale.npp_he_thong.doctype.npp_phien_danh_muc.npp_phien_danh_muc import doc_phien


def _nv(sdt, vai, cong_ty=()):
	email = email_ky_thuat(sdt)
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": vai, "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": f"NV {vai}", "vai": vai, "sdt": sdt,
			"cong_ty": [{"nha_cung_cap": x} for x in cong_ty]}).insert(ignore_permissions=True)
	return NguCanh(user=email, vai=vai)


def _ncc(ten):
	return frappe.get_doc({"doctype": "Supplier", "supplier_name": ten, "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")}).insert(
		ignore_permissions=True).name


class TestCongSanPham(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()

	def setUp(self):
		frappe.db.savepoint("npp_test")
		self.ncc_a = _ncc("NCC Thử A")
		self.ncc_b = _ncc("NCC Thử B")
		self.chu = _nv("0919000951", "owner")
		self.nv = _nv("0919000952", "sales", cong_ty=[self.ncc_a])

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")

	def _sp(self, sku, ncc=None, **them):
		frappe.set_user(self.chu.user)
		try:
			return ghi({"bang": "products", "hanh_dong": "insert", "gia_tri": {"sku": sku, "name": f"Hàng {sku}", "base_unit": "Lon thử",
				"vat_rate": 0.08, "sell_price": 10000, "primary_supplier_id": ncc, **them}, "select": "id"}, self.chu)["data"][0]["id"]
		finally:
			frappe.set_user("Administrator")

	def test_tao_doc_don_vi_gia_va_pham_vi_nvbh(self):
		phien = doc_phien()["phien"]
		a = self._sp("SPT-A01", self.ncc_a, barcode="8939999000017")
		b = self._sp("SPT-B01", self.ncc_b)
		k = self._sp("SPT-K01")
		self.assertGreater(doc_phien()["phien"], phien)  # đổi hàng → tăng số phiên danh mục
		r = doc({"bang": "products", "select": "id, sku, name, barcode, base_unit, vat_rate, sell_price, status, primary_supplier_id, tim_kd, images",
			"loc": [{"op": "eq", "cot": "id", "gt": a}]}, self.chu)["data"][0]
		self.assertEqual((r["sku"], r["barcode"], r["base_unit"], r["vat_rate"], r["sell_price"], r["status"], r["primary_supplier_id"], r["images"]),
			("SPT-A01", "8939999000017", "Lon thử", 0.08, 10000, "active", self.ncc_a, []))
		self.assertIn("8939999000017", r["tim_kd"])
		thay = {x["id"] for x in doc({"bang": "products", "select": "id", "loc": [{"op": "in", "cot": "id", "gt": [a, b, k]}]}, self.nv)["data"]}
		self.assertEqual(thay, {a, k})  # NVBH: hàng công ty mình + hàng chưa gán NCC
		ghi({"bang": "product_units", "hanh_dong": "insert", "gia_tri": {"product_id": a, "unit_name": "Thùng thử", "conversion": 24}}, self.chu)
		ghi({"bang": "price_lists", "hanh_dong": "insert", "gia_tri": {"product_id": a, "unit_name": "Thùng thử", "price": 230000, "group_id": None}}, self.chu)
		sp = doc({"bang": "products", "select": "id, units:product_units(unit_name, conversion), price_lists(unit_name, price, group_id)",
			"loc": [{"op": "eq", "cot": "id", "gt": a}]}, self.nv)["data"][0]
		self.assertEqual(sp["units"], [{"unit_name": "Thùng thử", "conversion": 24}])
		self.assertEqual(sp["price_lists"], [{"unit_name": "Thùng thử", "price": 230000, "group_id": None}])
		with self.assertRaises(LoiCong):
			ghi({"bang": "products", "hanh_dong": "update", "gia_tri": {"sku": "DOI"}, "loc": [{"op": "eq", "cot": "id", "gt": a}]}, self.chu)
		self.assertEqual(ghi({"bang": "products", "hanh_dong": "update", "gia_tri": {"status": "inactive"},
			"loc": [{"op": "eq", "cot": "id", "gt": a}], "select": "id"}, self.nv)["data"], [])  # NVBH không sửa hàng
		ghi({"bang": "products", "hanh_dong": "update", "gia_tri": {"status": "inactive"}, "loc": [{"op": "eq", "cot": "id", "gt": a}]}, self.chu)
		self.assertEqual(frappe.db.get_value("Item", a, "npp_ngung_ban"), 1)
