"""Bảng khách hàng trên cổng + RPC khách (cần bench): bench --site poc.local run-tests --module nppsale.tests.test_cong_khach_hang"""
import frappe
from frappe.tests import IntegrationTestCase

from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.ghi import ghi
from nppsale.cong.sql import LoiCong
from nppsale.cong.truy_van import doc
from nppsale.luat.sdt import email_ky_thuat
from nppsale.rpc.khach_hang import claim_customer_for_me, search_customer_dupes


def _nv(sdt, vai):
	email = email_ky_thuat(sdt)
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": vai, "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": f"NV {vai}", "vai": vai, "sdt": sdt}).insert(ignore_permissions=True)
	return NguCanh(user=email, vai=vai)


class _La:
	"""Chạy trong phiên của chính người gọi (như request thật: owner / modified_by = người ấy)."""

	def __init__(self, nc):
		self.nc = nc

	def __enter__(self):
		frappe.set_user(self.nc.user)
		frappe.local._npp_ngu_canh = None

	def __exit__(self, *a):
		frappe.set_user("Administrator")
		frappe.local._npp_ngu_canh = None


def _ghi(yc, nc):
	with _La(nc):
		return ghi(yc, nc)


def _them_khach(nc, ten, sdt, **them):
	k = _ghi({"bang": "customers", "hanh_dong": "insert", "gia_tri": {"store_name": ten, "phone": sdt, "owner_name": "Chủ", **them},
		"select": "id"}, nc)
	return k["data"][0]["id"]


class TestCongKhachHang(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()

	def setUp(self):
		self.chu = _nv("0916000701", "owner")
		self.a = _nv("0916000702", "sales")
		self.b = _nv("0916000703", "sales")

	def test_nvbh_chi_thay_khach_minh(self):
		k_a = _them_khach(self.a, "Tạp hoá A", "0987 000 001")  # A tạo → A thấy (created_by)
		k_chu = _them_khach(self.chu, "Tạp hoá Chủ", "0987000002")
		thay_a = [r["id"] for r in doc({"bang": "customers", "select": "id"}, self.a)["data"]]
		self.assertIn(k_a, thay_a)
		self.assertNotIn(k_chu, thay_a)
		self.assertNotIn(k_a, [r["id"] for r in doc({"bang": "customers", "select": "id"}, self.b)["data"]])
		self.assertIn(k_a, [r["id"] for r in doc({"bang": "customers", "select": "id"}, self.chu)["data"]])
		# B nhận khách của chủ → thấy (phân công active)
		frappe.set_user(self.b.user)
		frappe.local._npp_ngu_canh = None
		try:
			self.assertEqual(claim_customer_for_me(k_chu), {"status": "claimed", "role": "primary"})
			self.assertEqual(claim_customer_for_me(k_chu), {"status": "already_assigned"})
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None
		self.assertIn(k_chu, [r["id"] for r in doc({"bang": "customers", "select": "id"}, self.b)["data"]])

	def test_sdt_chuan_hoa_va_trung(self):
		k = _them_khach(self.chu, "Tạp hoá Số", "+84 987 000 003")
		r = doc({"bang": "customers", "select": "phone, created_by, gps_lat", "loc": [{"op": "eq", "cot": "id", "gt": k}]}, self.chu)["data"][0]
		self.assertEqual(r["phone"], "0987000003")
		self.assertEqual(r["created_by"], self.chu.user)
		self.assertIsNone(r["gps_lat"])
		with self.assertRaises(LoiCong) as ng:
			_them_khach(self.a, "Trùng", "0987.000.003")
		self.assertEqual(ng.exception.ma, "23505")
		self.assertIn("customers_org_id_phone", ng.exception.thong_diep)

	def test_tim_trung_chi_dung_so(self):
		k = _them_khach(self.chu, "Tạp hoá Tìm", "0987000004")
		frappe.set_user(self.a.user)
		frappe.local._npp_ngu_canh = None
		try:
			ds = search_customer_dupes("+84 987 000 004")
			self.assertEqual([x["id"] for x in ds], [k])
			self.assertFalse(ds[0]["has_my_assignment"])
			self.assertEqual(search_customer_dupes("0987000"), [])  # số dở không tìm
			self.assertEqual(search_customer_dupes("Tạp hoá"), [])  # tên không tìm
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	def test_nvbh_khong_sua_khach_khong_thay(self):
		k_chu = _them_khach(self.chu, "Tạp hoá Khoá", "0987000005")
		kq = _ghi({"bang": "customers", "hanh_dong": "update", "gia_tri": {"store_name": "Đổi"}, "loc": [{"op": "eq", "cot": "id", "gt": k_chu}],
			"select": "id"}, self.a)
		self.assertEqual(kq["data"], [])
		self.assertEqual(frappe.db.get_value("Customer", k_chu, "customer_name"), "Tạp hoá Khoá")

	def test_ghe_tham_ep_nguoi_ghe(self):
		k = _them_khach(self.a, "Tạp hoá Ghé", "0987000006")
		v = _ghi({"bang": "visit_logs", "hanh_dong": "insert", "gia_tri": {"customer_id": k, "sales_user_id": self.b.user, "visit_date": "2026-11-11",
			"check_in_at": "2026-11-11T01:00:00.000Z", "check_in_lat": 20.85, "check_in_lng": 106.68}, "select": "id, sales_user_id, check_in_at"}, self.a)
		r = v["data"][0]
		self.assertEqual(r["sales_user_id"], self.a.user)  # ép = người gọi
		self.assertTrue(r["check_in_at"].startswith("2026-11-11T08:00:00"))  # 01:00 UTC = 08:00 giờ VN
		self.assertEqual(doc({"bang": "visit_logs", "select": "id"}, self.b)["data"], [])


class TestKhachThieuAnh(IntegrationTestCase):
	def setUp(self):
		frappe.db.savepoint("npp_test")
		self.chu = _nv("0916000751", "owner")
		self.a = _nv("0916000752", "sales")

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")

	def test_loc_dem_phan_trang_theo_nguoi_goi(self):
		from nppsale.rpc.khach_hang import khach_cho_duyet_anh, khach_thieu_anh

		k1 = _them_khach(self.a, "AA Thiếu cả hai", "0987000101")
		k2 = _them_khach(self.a, "AB Có vị trí", "0987000102", gps_lat=20.8, gps_lng=106.7)
		k3 = _them_khach(self.chu, "AC Của chủ", "0987000103")
		with _La(self.a):
			ds = khach_thieu_anh("all", 0, 50)
			ids = [r["id"] for r in ds]
			self.assertIn(k1, ids)
			self.assertIn(k2, ids)  # có vị trí nhưng chưa có ảnh
			self.assertNotIn(k3, ids)  # NVBH không thấy khách của chủ
			self.assertEqual(ds[0]["total_count"], len(ds))
			self.assertEqual([r["id"] for r in khach_thieu_anh("no_gps", 0, 50) if r["id"] in (k1, k2)], [k1])
			trang = khach_thieu_anh("all", 0, 1)
			self.assertEqual(len(trang), 1)
			self.assertGreaterEqual(trang[0]["total_count"], 2)
			cho = [r["id"] for r in khach_cho_duyet_anh(0, 50)]
			self.assertIn(k2, cho)  # chưa duyệt mà đã có vị trí → chờ duyệt
			self.assertNotIn(k1, cho)
