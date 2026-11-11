"""RPC khoá chứng từ (cần bench): bench --site poc.local run-tests --module nppsale.tests.test_khoa_chung_tu"""
import frappe
from frappe.tests import IntegrationTestCase

from nppsale.cong import api
from nppsale.luat.sdt import email_ky_thuat
from nppsale.rpc.khoa_chung_tu import release_stale_entity_locks


def _nv(sdt, vai, ten):
	email = email_ky_thuat(sdt)
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": ten, "send_welcome_email": 0}).insert(ignore_permissions=True)
	if not frappe.db.exists("NPP Nhan Vien", email):
		frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": ten, "vai": vai, "sdt": sdt}).insert(ignore_permissions=True)
	return email


def _goi(user, ten, **tham):
	frappe.set_user(user)
	frappe.local._npp_ngu_canh = None
	frappe.local.request = None
	try:
		return api.rpc(ten=ten, tham_so=tham)
	finally:
		frappe.set_user("Administrator")


class TestKhoaChungTu(IntegrationTestCase):
	def setUp(self):
		self.a = _nv("0913000401", "sales", "NV A")
		self.b = _nv("0913000402", "manager", "QL B")

	def test_gianh_giu_nha(self):
		k = _goi(self.a, "acquire_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9001")
		self.assertTrue(k["data"][0]["ok"])
		self.assertEqual(k["data"][0]["holder_name"], "NV A")
		k2 = _goi(self.b, "acquire_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9001")
		self.assertFalse(k2["data"][0]["ok"])
		self.assertEqual(k2["data"][0]["holder_id"], self.a)
		self.assertFalse(_goi(self.b, "heartbeat_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9001")["data"])
		self.assertTrue(_goi(self.a, "heartbeat_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9001")["data"])
		self.assertFalse(_goi(self.b, "release_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9001")["data"])
		self.assertTrue(_goi(self.a, "release_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9001")["data"])
		self.assertTrue(_goi(self.b, "acquire_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9001")["data"][0]["ok"])

	def test_khoa_qua_han_bi_don(self):
		_goi(self.a, "acquire_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9002")
		frappe.db.sql("UPDATE `tabNPP Khoa Chung Tu` SET nhip_cuoi = NOW(6) - INTERVAL 11 MINUTE WHERE name = 'sales_order:DH-9002'")
		k = _goi(self.b, "acquire_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9002")
		self.assertTrue(k["data"][0]["ok"])
		self.assertEqual(k["data"][0]["holder_id"], self.b)
		frappe.db.sql("UPDATE `tabNPP Khoa Chung Tu` SET nhip_cuoi = NOW(6) - INTERVAL 11 MINUTE")
		release_stale_entity_locks()
		self.assertFalse(frappe.db.exists("NPP Khoa Chung Tu", "sales_order:DH-9002"))

	def test_chua_dang_nhap_hoac_khong_phai_nv(self):
		k = _goi("Guest", "acquire_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9003")
		self.assertEqual(k["error"]["code"], "PGRST301")
