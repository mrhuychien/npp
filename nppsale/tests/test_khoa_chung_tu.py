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

	def test_bao_realtime_toi_phong_tung_nv(self):
		"""Giành / nhả khoá → đẩy "npp_cong" tới phòng user của TỪNG NV đang làm (NV NPP là Website User — không vào phòng "all" mà
		publish_realtime(doctype=…) không docname rơi vào); NV đã nghỉ / bị khoá không nhận."""
		from unittest.mock import patch

		nghi = _nv("0913000403", "sales", "NV nghi")
		frappe.db.set_value("NPP Nhan Vien", nghi, "nghi_viec_luc", frappe.utils.now_datetime())
		goi = []
		with patch("frappe.publish_realtime", side_effect=lambda *a, **k: goi.append((a, k))):
			_goi(self.a, "acquire_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9100")
			_goi(self.a, "release_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9100")
		goi = [(a, k) for a, k in goi if a and a[0] == "npp_cong"]  # bỏ doc_update… của lõi
		self.assertTrue(goi)
		for _a, k in goi:
			self.assertNotIn("doctype", k)
			self.assertNotIn("room", k)
			self.assertTrue(k.get("user"), k)
		nhan = {k["user"] for _a, k in goi}
		self.assertIn(self.a, nhan)
		self.assertIn(self.b, nhan)
		self.assertNotIn(nghi, nhan)
		self.assertEqual({a[1]["su_kien"] for a, _k in goi}, {"UPSERT", "DELETE"})

	def test_khoa_qua_han_bi_don(self):
		_goi(self.a, "acquire_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9002")
		frappe.db.sql("UPDATE `tabNPP Khoa Chung Tu` SET nhip_cuoi = NOW(6) - INTERVAL 11 MINUTE WHERE name = 'sales_order:DH-9002'")
		k = _goi(self.b, "acquire_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9002")
		self.assertTrue(k["data"][0]["ok"])
		self.assertEqual(k["data"][0]["holder_id"], self.b)
		frappe.db.sql("UPDATE `tabNPP Khoa Chung Tu` SET nhip_cuoi = NOW(6) - INTERVAL 11 MINUTE")
		# dọn bằng câu xoá thẳng vẫn phải báo DELETE tới từng NV (người đang chờ khoá nhận ngay, không chờ vòng hỏi)
		from unittest.mock import patch

		goi = []
		with patch("frappe.publish_realtime", side_effect=lambda *a, **k: goi.append((a, k))):
			self.assertGreaterEqual(release_stale_entity_locks(), 1)
		self.assertFalse(frappe.db.exists("NPP Khoa Chung Tu", "sales_order:DH-9002"))
		bao = [(a[1], k.get("user")) for a, k in goi if a and a[0] == "npp_cong" and a[1].get("entity_id") == "DH-9002"]
		self.assertTrue(bao)
		self.assertTrue(all(t["su_kien"] == "DELETE" and t["bang"] == "entity_locks" and t["locked_by"] == self.b for t, _u in bao))
		self.assertIn(self.a, {u for _t, u in bao})

	def test_chua_dang_nhap_hoac_khong_phai_nv(self):
		k = _goi("Guest", "acquire_entity_lock", p_entity_type="sales_order", p_entity_id="DH-9003")
		self.assertEqual(k["error"]["code"], "PGRST301")
