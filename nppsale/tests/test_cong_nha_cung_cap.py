"""Bảng suppliers trên cổng (cần bench): bench --site poc.local run-tests --module nppsale.tests.test_cong_nha_cung_cap"""
import frappe
from frappe.tests import IntegrationTestCase

from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.ghi import ghi
from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong
from nppsale.cong.truy_van import doc
from nppsale.luat.sdt import email_ky_thuat


def _nv(sdt, vai):
	email = email_ky_thuat(sdt)
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": vai, "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": f"NV {vai}", "vai": vai, "sdt": sdt}).insert(ignore_permissions=True)
	return NguCanh(user=email, vai=vai)


class TestCongNhaCungCap(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()

	def setUp(self):
		frappe.db.savepoint("npp_test")
		self.kho = _nv("0918000901", "warehouse")
		self.nv = _nv("0918000902", "sales")

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")

	def test_them_doc_sua_xoa(self):
		frappe.set_user(self.kho.user)
		k = ghi({"bang": "suppliers", "hanh_dong": "insert", "gia_tri": {"name": "Công ty Sữa Thử", "code": "SUA01", "phone": "0243 111 222",
			"credit_limit": 50000000, "is_active": True}, "select": "id, name, code, credit_limit, is_active, tim_kd"}, self.kho)["data"][0]
		self.assertTrue(k["id"].startswith("NCC-"))
		self.assertEqual((k["code"], k["credit_limit"], k["is_active"]), ("SUA01", 50000000, True))
		self.assertIn("sua01", k["tim_kd"])
		# NVBH đọc được, không sửa được (0 dòng)
		self.assertIn(k["id"], [r["id"] for r in doc({"bang": "suppliers", "select": "id"}, self.nv)["data"]])
		self.assertEqual(ghi({"bang": "suppliers", "hanh_dong": "update", "gia_tri": {"name": "Đổi"}, "loc": [{"op": "eq", "cot": "id", "gt": k["id"]}],
			"select": "id"}, self.nv)["data"], [])
		# Ngừng hợp tác + bỏ hạn mức
		ghi({"bang": "suppliers", "hanh_dong": "update", "gia_tri": {"is_active": False, "credit_limit": None},
			"loc": [{"op": "eq", "cot": "id", "gt": k["id"]}]}, self.kho)
		r = doc({"bang": "suppliers", "select": "is_active, credit_limit", "loc": [{"op": "eq", "cot": "id", "gt": k["id"]}]}, self.kho)["data"][0]
		self.assertEqual(r, {"is_active": False, "credit_limit": None})
		with self.assertRaises(LoiCong):
			ghi({"bang": "suppliers", "hanh_dong": "insert", "gia_tri": {"name": "Trùng mã", "code": "SUA01"}}, self.kho)
		with self.assertRaises(NppLoi):
			ghi({"bang": "suppliers", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "id", "gt": k["id"]}]}, self.kho)
