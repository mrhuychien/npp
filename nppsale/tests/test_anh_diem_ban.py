"""Duyệt ảnh + vị trí điểm bán (cần bench): bench --site poc.local run-tests --module nppsale.tests.test_anh_diem_ban"""
import frappe
from frappe.tests import IntegrationTestCase

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.ghi import ghi
from nppsale.cong.loi import NppLoi
from nppsale.luat.sdt import email_ky_thuat


def _nv(sdt, vai):
	email = email_ky_thuat(sdt)
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": vai, "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": f"NV {vai}", "vai": vai, "sdt": sdt}).insert(ignore_permissions=True)
	return NguCanh(user=email, vai=vai)


class _La:
	def __init__(self, u):
		self.u = u

	def __enter__(self):
		frappe.set_user(self.u)
		frappe.local._npp_ngu_canh = None

	def __exit__(self, *a):
		frappe.set_user("Administrator")
		frappe.local._npp_ngu_canh = None


def _rpc(u, ten, **tham):
	with _La(u):
		kq = api.rpc(ten=ten, tham_so=tham)
	if "error" in kq:
		raise NppLoi(kq["error"]["message"], code=kq["error"]["code"])
	return kq["data"]


class TestAnhDiemBan(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")

	def setUp(self):
		# IntegrationTestCase chỉ quay lui khi hết lớp test — mỗi test tự quay lui phần của nó
		frappe.db.savepoint("npp_test")
		self.chu = _nv("0917000801", "owner")
		self.a = _nv("0917000802", "sales")
		with _La(self.a.user):
			self.kh = ghi({"bang": "customers", "hanh_dong": "insert", "gia_tri": {"store_name": "Tạp hoá Duyệt", "phone": "0989000801",
				"owner_name": "Chủ"}, "select": "id"}, self.a)["data"][0]["id"]
		self.org = frappe.db.get_single_value("NPP Cai Dat", "org_id")

	def _url(self, o, ms):
		return f"/storage/v1/object/public/customer-photos/{self.org}/{self.kh}/{o}-{ms}.jpg"

	def _them_anh(self, nc, o, ms):
		with _La(nc.user):
			return ghi({"bang": "customer_photos", "hanh_dong": "insert", "gia_tri": {"customer_id": self.kh, "slot": o,
				"photo_url": self._url(o, ms), "taken_at": "2026-11-11T08:00:00+07:00", "gps_lat": 20.8, "gps_lng": 106.7}, "select": "id"}, nc)["data"][0]["id"]

	def test_vong_duyet_day_du(self):
		anh1 = self._them_anh(self.a, 1, 100)
		tb = frappe.get_all("NPP Thong Bao", filters={"nguoi_nhan": self.chu.user, "loai": "customer_photo_review"}, pluck="tieu_de")
		self.assertIn("Ảnh điểm bán chờ duyệt: Tạp hoá Duyệt", tb)  # ảnh đầu tiên → báo người duyệt
		with self.assertRaises(NppLoi) as ng:
			_rpc(self.a.user, "duyet_anh_diem_ban", p_customer_id=self.kh)
		self.assertIn("FORBIDDEN", ng.exception.ma)
		self.assertEqual(_rpc(self.chu.user, "duyet_anh_diem_ban", p_customer_id=self.kh), {"duyet": True, "file_bo": []})
		# Đã duyệt: NVBH sửa thẳng ảnh bị chặn; xin đổi thì được
		with self.assertRaises(NppLoi) as ng:
			with _La(self.a.user):
				ghi({"bang": "customer_photos", "hanh_dong": "update", "gia_tri": {"photo_url": self._url(1, 200)},
					"loc": [{"op": "eq", "cot": "id", "gt": anh1}]}, self.a)
		self.assertEqual(ng.exception.ma, "ANH_DA_DUYET")
		yc = _rpc(self.a.user, "xin_doi_anh_diem_ban", p_customer_id=self.kh, p_photo_action="replace", p_photo_id=anh1,
			p_photo_url=self._url(1, 300), p_taken_at="2026-11-12T09:00:00+07:00", p_pin_action="set", p_pin_lat=20.81, p_pin_lng=106.71)
		self.assertEqual(len(yc["ids"]), 2)
		self.assertEqual(frappe.db.get_value("NPP Anh Diem Ban", anh1, "anh_url"), self._url(1, 100))  # chưa đổi gì tới khi duyệt
		kq = _rpc(self.chu.user, "duyet_yeu_cau_anh_diem_ban", p_request_ids=yc["ids"], p_dong_y=True)
		self.assertEqual((kq["xong"], kq["bo_qua"]), (2, 0))
		self.assertEqual(kq["file_bo"], [self._url(1, 100)])
		self.assertEqual(frappe.db.get_value("NPP Anh Diem Ban", anh1, "anh_url"), self._url(1, 300))
		self.assertAlmostEqual(frappe.db.get_value("Customer", self.kh, "npp_vi_do"), 20.81, places=5)
		self.assertIn("Đã duyệt ảnh điểm bán: Tạp hoá Duyệt",
			frappe.get_all("NPP Thong Bao", filters={"nguoi_nhan": self.a.user}, pluck="tieu_de"))
		with self.assertRaises(NppLoi) as ng:
			_rpc(self.chu.user, "duyet_yeu_cau_anh_diem_ban", p_request_ids=yc["ids"], p_dong_y=True)
		self.assertTrue(ng.exception.ma.startswith("DA_XU_LY"))

	def test_xin_lai_thay_yeu_cau_cu_rut_va_bo_duyet(self):
		self._them_anh(self.a, 1, 100)
		_rpc(self.chu.user, "duyet_anh_diem_ban", p_customer_id=self.kh)
		y1 = _rpc(self.a.user, "xin_doi_anh_diem_ban", p_customer_id=self.kh, p_photo_action="add", p_slot=2,
			p_photo_url=self._url(2, 1), p_taken_at="2026-11-12T09:00:00+07:00")["ids"][0]
		y2 = _rpc(self.a.user, "xin_doi_anh_diem_ban", p_customer_id=self.kh, p_photo_action="add", p_slot=2,
			p_photo_url=self._url(2, 2), p_taken_at="2026-11-12T09:05:00+07:00")
		self.assertEqual(y2["file_bo"], [self._url(2, 1)])
		self.assertEqual(frappe.db.get_value("NPP Yeu Cau Anh Diem Ban", y1, "trang_thai"), "cancelled")
		self.assertEqual(_rpc(self.a.user, "huy_yeu_cau_anh_diem_ban", p_request_id=y2["ids"][0]), {"file_bo": [self._url(2, 2)]})
		with self.assertRaises(NppLoi) as ng:
			_rpc(self.a.user, "xin_doi_anh_diem_ban", p_customer_id=self.kh, p_photo_action="add", p_slot=3,
				p_photo_url="/storage/v1/object/public/customer-photos/khac/x.jpg", p_taken_at="2026-11-12T09:00:00+07:00")
		self.assertTrue(ng.exception.ma.startswith("FILE_SAI"))
		y3 = _rpc(self.a.user, "xin_doi_anh_diem_ban", p_customer_id=self.kh, p_pin_action="clear")["ids"][0]
		kq = _rpc(self.chu.user, "duyet_anh_diem_ban", p_customer_id=self.kh, p_duyet=False)
		self.assertEqual(kq["duyet"], False)
		self.assertEqual(frappe.db.get_value("NPP Yeu Cau Anh Diem Ban", y3, "trang_thai"), "cancelled")
		self.assertIsNone(frappe.db.get_value("Customer", self.kh, "npp_duyet_anh_luc"))
		with self.assertRaises(NppLoi) as ng:
			_rpc(self.a.user, "xin_doi_anh_diem_ban", p_customer_id=self.kh, p_pin_action="clear")
		self.assertTrue(ng.exception.ma.startswith("CHUA_DUYET"))
