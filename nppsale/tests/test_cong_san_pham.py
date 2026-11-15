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

	def test_phien_danh_muc_chi_theo_gia_ban(self):
		"""Số phiên danh mục bán (mig 209) chỉ tăng theo giá BÁN: giá nhập (Gia nhap — tự cập nhật mỗi phiếu nhập) không làm mọi máy NVBH
		tải lại danh mục."""
		a = self._sp("SPT-PH-01")
		dam = frappe.db.get_value("Price List", {"buying": 1, "enabled": 1}, "name") or "Gia nhap"
		phien = doc_phien()["phien"]
		frappe.get_doc({"doctype": "Item Price", "item_code": a, "price_list": dam, "price_list_rate": 7000}).insert(ignore_permissions=True)
		self.assertEqual(doc_phien()["phien"], phien)
		frappe.get_doc({"doctype": "Item Price", "item_code": a, "price_list": "Gia chuan", "uom": "Lon thử",
			"price_list_rate": 11000}).insert(ignore_permissions=True)
		self.assertGreater(doc_phien()["phien"], phien)

	def test_ten_dai_khoa_tim_qua_140(self):
		"""Khoá tìm = SKU + tên + mã vạch, mỗi từ thêm bản viết liền — dài gấp đôi tên; Data 140 ký tự làm lõi từ chối lưu mặt hàng tên dài."""
		ten = "Nước tăng lực Red Bull Thái Lan lon 250ml thùng 24 lon chính hãng nhập khẩu"
		a = self._sp("SPT-DAI-01", name=ten, barcode="8936000000001")
		khoa = frappe.db.get_value("Item", a, "npp_tim_kd")
		self.assertGreater(len(khoa), 140)
		self.assertIn("8936000000001", khoa)

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
		# form Sửa sản phẩm luôn gửi lại `sku`: trùng giá trị → bỏ qua, các trường khác vẫn lưu
		ghi({"bang": "products", "hanh_dong": "update", "gia_tri": {"sku": "SPT-A01", "name": "Hàng A sửa tên"},
			"loc": [{"op": "eq", "cot": "id", "gt": a}]}, self.chu)
		self.assertEqual(frappe.db.get_value("Item", a, "item_name"), "Hàng A sửa tên")
		# đã có chứng từ (lô) → SKU khoá (câu 18)
		frappe.get_doc({"doctype": "Batch", "batch_id": "SPT-A01-L1", "item": a}).insert(ignore_permissions=True)
		with self.assertRaises(LoiCong) as loi:
			ghi({"bang": "products", "hanh_dong": "update", "gia_tri": {"sku": "DOI"}, "loc": [{"op": "eq", "cot": "id", "gt": a}]}, self.chu)
		self.assertIn("SKU_KHOA", str(loi.exception))
		# chưa có chứng từ → đổi SKU = đổi tên bản ghi; trùng SKU khác → 23505
		with self.assertRaises(LoiCong):
			ghi({"bang": "products", "hanh_dong": "update", "gia_tri": {"sku": "SPT-B01"}, "loc": [{"op": "eq", "cot": "id", "gt": k}]}, self.chu)
		ghi({"bang": "products", "hanh_dong": "update", "gia_tri": {"sku": "SPT-K02"}, "loc": [{"op": "eq", "cot": "id", "gt": k}]}, self.chu)
		self.assertFalse(frappe.db.exists("Item", k))
		self.assertEqual(frappe.db.get_value("Item", "SPT-K02", "item_code"), "SPT-K02")
		self.assertEqual(ghi({"bang": "products", "hanh_dong": "update", "gia_tri": {"status": "inactive"},
			"loc": [{"op": "eq", "cot": "id", "gt": a}], "select": "id"}, self.nv)["data"], [])  # NVBH không sửa hàng
		ghi({"bang": "products", "hanh_dong": "update", "gia_tri": {"status": "inactive"}, "loc": [{"op": "eq", "cot": "id", "gt": a}]}, self.chu)
		self.assertEqual(frappe.db.get_value("Item", a, "npp_ngung_ban"), 1)
