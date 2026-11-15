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

	def test_gia_von_che_theo_quyen(self):
		"""Chủ nhà 25/09/2026: NVBH "Không xem được các thông tin quan trọng của nhà phân phối" (`xemDuocGiaVon`). nppsale chỉ che ở
		giao diện; cổng che luôn products.cost_price — chọn, `*`, lọc, sắp, bảng lồng, dòng trả lại sau khi ghi — và người không được xem
		sửa mặt hàng thì không ghi đè giá vốn bằng số form gửi lại (form ẩn ô giá vốn nhưng vẫn gửi số đã nạp)."""
		from frappe.utils import flt

		a = self._sp("SPT-GV-01", self.ncc_a, cost_price=7000)
		ql = _nv("0919000953", "manager")
		cau = {"bang": "products", "select": "id, cost_price, sell_price", "loc": [{"op": "eq", "cot": "id", "gt": a}]}
		self.assertEqual(flt(doc(cau, self.chu)["data"][0]["cost_price"]), 7000)
		self.assertEqual(flt(doc(cau, ql)["data"][0]["cost_price"]), 7000)  # quản lý: mặc định được xem
		r = doc(cau, self.nv)["data"][0]
		self.assertIsNone(r["cost_price"])
		self.assertEqual(flt(r["sell_price"]), 10000)  # giá bán vẫn thấy
		self.assertIsNone(doc({"bang": "products", "select": "*", "loc": cau["loc"]}, self.nv)["data"][0]["cost_price"])
		loc_gv = cau["loc"] + [{"op": "gt", "cot": "cost_price", "gt": 6000}]
		self.assertEqual(doc({"bang": "products", "select": "id", "loc": loc_gv}, self.nv)["data"], [])  # lọc không dò ra giá vốn
		self.assertEqual(len(doc({"bang": "products", "select": "id", "loc": loc_gv}, ql)["data"]), 1)
		# bảng lồng: price_lists → product:products(cost_price)
		frappe.get_doc({"doctype": "Item Price", "item_code": a, "price_list": "Gia chuan", "uom": "Lon thử",
			"price_list_rate": 10000}).insert(ignore_permissions=True)
		cau_long = {"bang": "price_lists", "select": "id, product:products(sku, cost_price)", "loc": [{"op": "eq", "cot": "product_id", "gt": a}]}
		self.assertEqual(flt(doc(cau_long, ql)["data"][0]["product"]["cost_price"]), 7000)
		lo = doc(cau_long, self.nv)["data"][0]["product"]
		self.assertEqual((lo["sku"], lo["cost_price"]), (a, None))
		# quyền riêng tắt ô giá vốn của quản lý → che; quản lý ấy sửa mặt hàng (form gửi lại cost_price 0) → giá vốn giữ nguyên
		frappe.get_doc({"doctype": "NPP Quyen Rieng", "nhan_vien": ql.user, "khoa_quyen": "inventory.cost.read", "duoc_phep": 0}).insert(
			ignore_permissions=True)
		ql = NguCanh(user=ql.user, vai="manager")  # quyền nạp một lần mỗi request — ngữ cảnh mới
		self.assertIsNone(doc(cau, ql)["data"][0]["cost_price"])
		frappe.set_user(ql.user)
		try:
			ra = ghi({"bang": "products", "hanh_dong": "update", "gia_tri": {"sku": a, "name": "Hàng sửa tên", "cost_price": 0},
				"loc": [{"op": "eq", "cot": "id", "gt": a}], "select": "id, name, cost_price"}, ql)["data"][0]
		finally:
			frappe.set_user("Administrator")
		self.assertEqual((ra["name"], ra["cost_price"]), ("Hàng sửa tên", None))  # dòng trả lại sau khi ghi cũng che
		self.assertEqual(flt(frappe.db.get_value("Item", a, "valuation_rate")), 7000)
		# chủ NPP sửa giá vốn thì ghi
		frappe.set_user(self.chu.user)
		try:
			ghi({"bang": "products", "hanh_dong": "update", "gia_tri": {"cost_price": 8000}, "loc": [{"op": "eq", "cot": "id", "gt": a}]},
				NguCanh(user=self.chu.user, vai="owner"))
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(flt(frappe.db.get_value("Item", a, "valuation_rate")), 8000)

	def test_bang_gia_chung_va_nhap_theo_cai_dat(self):
		"""Blueprint 02 §3.11: tên bảng giá chung / nhập ở NPP Cai Dat (không viết cứng "Gia chuan" / "Gia nhap"). Đổi cài đặt → giá bảng của
		đơn, bảng cổng price_lists (nhóm NULL) / purchase_price_lists, chỗ ghi giá nhóm trống đều theo bảng mới; Selling / Buying Settings
		trỏ theo khi chạy lại thiết lập mặc định."""
		from nppsale.rpc.don_hang import _gia_bang
		from nppsale.su_kien.san_pham import bang_gia_chung, bang_gia_nhap, dam_bao_bang_gia
		from nppsale.thiet_lap.mac_dinh import dam_bao

		self.assertEqual((bang_gia_chung(), bang_gia_nhap()), ("Gia chuan", "Gia nhap"))
		self.assertEqual(frappe.db.get_single_value("NPP Cai Dat", "bang_gia_chung", cache=False), "Gia chuan")
		a = self._sp("SPT-BG-01")
		for bang, gia in (("Gia chuan", 10000), ("Gia nhap", 7000)):
			frappe.get_doc({"doctype": "Item Price", "item_code": a, "price_list": bang, "uom": "Lon thử",
				"price_list_rate": gia}).insert(ignore_permissions=True)
		dam_bao_bang_gia("Bang gia chung thu", ban=True)
		dam_bao_bang_gia("Bang gia nhap thu", ban=False)
		for bang, gia in (("Bang gia chung thu", 12000), ("Bang gia nhap thu", 6500)):
			frappe.get_doc({"doctype": "Item Price", "item_code": a, "price_list": bang, "uom": "Lon thử",
				"price_list_rate": gia}).insert(ignore_permissions=True)
		self.assertEqual(_gia_bang(a, "Lon thử", None), 10000)
		frappe.db.set_single_value("NPP Cai Dat", "bang_gia_chung", "Bang gia chung thu")
		frappe.db.set_single_value("NPP Cai Dat", "bang_gia_nhap", "Bang gia nhap thu")
		self.assertEqual(_gia_bang(a, "Lon thử", None), 12000)
		ban = {(r["price"], r["group_id"]) for r in doc({"bang": "price_lists", "select": "price, group_id",
			"loc": [{"op": "eq", "cot": "product_id", "gt": a}]}, self.chu)["data"]}
		self.assertIn((12000, None), ban)
		self.assertNotIn(6500, {p for p, _ in ban})  # bảng giá nhập không lẫn vào bảng giá bán
		nhap = [r["price"] for r in doc({"bang": "purchase_price_lists", "select": "price", "loc": [{"op": "eq", "cot": "product_id", "gt": a}]},
			self.chu)["data"]]
		self.assertEqual(nhap, [6500])
		# ghi giá bán nhóm trống qua cổng → vào bảng giá chung đang chọn
		b = self._sp("SPT-BG-02")
		frappe.set_user(self.chu.user)
		try:
			ghi({"bang": "price_lists", "hanh_dong": "insert", "gia_tri": {"product_id": b, "unit_name": "Lon thử", "price": 9900,
				"group_id": None}}, self.chu)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_all("Item Price", filters={"item_code": b}, pluck="price_list"), ["Bang gia chung thu"])
		dam_bao()
		self.assertEqual(frappe.db.get_single_value("Selling Settings", "selling_price_list", cache=False), "Bang gia chung thu")
		self.assertEqual(frappe.db.get_single_value("Buying Settings", "buying_price_list", cache=False), "Bang gia nhap thu")
