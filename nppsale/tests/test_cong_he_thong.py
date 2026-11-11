"""Bảng hệ thống trên cổng (cần bench): bench --site poc.local run-tests --module nppsale.tests.test_cong_he_thong
Kiểm vế lọc + luật ghi chép từ chính sách RLS của nppsale (blueprint 02 §8.1)."""
import frappe
from frappe.tests import IntegrationTestCase

from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.ghi import ghi
from nppsale.cong.sql import LoiCong
from nppsale.cong.truy_van import ap_mot, doc
from nppsale.luat.sdt import email_ky_thuat


def _nv(sdt, vai, ten=None):
	email = email_ky_thuat(sdt)
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": ten or vai, "send_welcome_email": 0}).insert(ignore_permissions=True)
	if not frappe.db.exists("NPP Nhan Vien", email):
		frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": ten or vai, "vai": vai, "sdt": sdt}).insert(ignore_permissions=True)
	return NguCanh(user=email, vai=vai, them={"nhan_vien": email})


class TestCongHeThong(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()

	def setUp(self):
		self.chu = _nv("0912000301", "owner", "Chủ")
		self.ql = _nv("0912000302", "manager", "Quản lý")
		self.nv = _nv("0912000303", "sales", "NVBH")

	def test_users_moi_nv_thay_het_va_chi_chu_sua(self):
		ds = doc({"bang": "users", "select": "id, full_name, role, discount_max_value, org_id"}, self.nv)["data"]
		self.assertIn(self.chu.user, [r["id"] for r in ds])
		org = frappe.db.get_single_value("NPP Cai Dat", "org_id")
		self.assertTrue(all(r["org_id"] == org for r in ds))
		# NVBH sửa → 0 dòng (USING owner), không lỗi
		k = ghi({"bang": "users", "hanh_dong": "update", "gia_tri": {"full_name": "Đổi bậy"}, "loc": [{"op": "eq", "cot": "id", "gt": self.chu.user}],
			"select": "id"}, self.nv)
		self.assertEqual(k["data"], [])
		self.assertEqual(frappe.db.get_value("NPP Nhan Vien", self.chu.user, "ho_ten"), "Chủ")
		# Chủ đặt trần giảm 10% → discount_max_value đọc lại 10; bỏ trần → null
		ghi({"bang": "users", "hanh_dong": "update", "gia_tri": {"allow_discount": True, "discount_max_type": "pct", "discount_max_value": 10},
			"loc": [{"op": "eq", "cot": "id", "gt": self.nv.user}]}, self.chu)
		r = ap_mot(doc({"bang": "users", "select": "allow_discount, discount_max_value", "loc": [{"op": "eq", "cot": "id", "gt": self.nv.user}],
			"mot": "one"}, self.chu), "one")["data"]
		self.assertEqual(r, {"allow_discount": True, "discount_max_value": 10})
		ghi({"bang": "users", "hanh_dong": "update", "gia_tri": {"discount_max_value": None}, "loc": [{"op": "eq", "cot": "id", "gt": self.nv.user}]},
			self.chu)
		self.assertIsNone(doc({"bang": "users", "select": "discount_max_value", "loc": [{"op": "eq", "cot": "id", "gt": self.nv.user}]},
			self.chu)["data"][0]["discount_max_value"])

	def test_nv_bi_khoa_khong_doc_duoc_gi(self):
		khoa = NguCanh(user=self.nv.user, vai=None)
		self.assertEqual(doc({"bang": "users", "select": "id"}, khoa)["data"], [])

	def test_quyen_vai_upsert_chi_chu(self):
		gt = {"role": "sales", "module": "customers.handover", "action": "read", "allowed": True}
		with self.assertRaises(LoiCong):
			ghi({"bang": "role_permissions", "hanh_dong": "upsert", "gia_tri": [gt], "on_conflict": "org_id,role,module,action"}, self.ql)
		ghi({"bang": "role_permissions", "hanh_dong": "upsert", "gia_tri": [gt], "on_conflict": "org_id,role,module,action"}, self.chu)
		self.assertEqual(frappe.db.get_value("NPP Quyen Vai", "sales:customers.handover:read", "duoc_phep"), 1)
		gt["allowed"] = False
		ghi({"bang": "role_permissions", "hanh_dong": "upsert", "gia_tri": [gt], "on_conflict": "org_id,role,module,action"}, self.chu)
		self.assertEqual(frappe.db.get_value("NPP Quyen Vai", "sales:customers.handover:read", "duoc_phep"), 0)

	def test_quyen_rieng_quan_ly_khong_dung_chu(self):
		with self.assertRaises(LoiCong):
			ghi({"bang": "user_permission_overrides", "hanh_dong": "upsert", "gia_tri": [{"user_id": self.chu.user,
				"permission_key": "orders.delete", "granted": False}]}, self.ql)
		ghi({"bang": "user_permission_overrides", "hanh_dong": "upsert", "gia_tri": [{"user_id": self.nv.user,
			"permission_key": "customer.view_all", "granted": True}]}, self.ql)
		self.assertEqual(frappe.db.get_value("NPP Quyen Rieng", f"{self.nv.user}:customer.view_all", "duoc_phep"), 1)
		from nppsale.cong.ngu_canh import co_quyen

		self.assertTrue(co_quyen(NguCanh(user=self.nv.user, vai="sales"), "customer.view_all"))
		self.assertFalse(co_quyen(NguCanh(user=self.nv.user, vai="sales"), "orders.approve"))

	def test_thong_bao_chi_cua_minh(self):
		ghi({"bang": "notifications", "hanh_dong": "insert", "gia_tri": {"user_id": self.chu.user, "type": "visit_logged", "title": "NV ghé thăm",
			"metadata": {"customer_id": "KH-1"}}}, self.nv)
		self.assertEqual(doc({"bang": "notifications", "select": "id"}, self.nv)["data"], [])
		ds = doc({"bang": "notifications", "select": "id, title, is_read, metadata"}, self.chu)["data"]
		self.assertEqual(ds[0]["title"], "NV ghé thăm")
		self.assertEqual(ds[0]["metadata"], {"customer_id": "KH-1"})
		# NVBH đánh dấu đọc thông báo của người khác → 0 dòng
		k = ghi({"bang": "notifications", "hanh_dong": "update", "gia_tri": {"is_read": True}, "loc": [{"op": "eq", "cot": "id", "gt": ds[0]["id"]}],
			"select": "id"}, self.nv)
		self.assertEqual(k["data"], [])
		ghi({"bang": "notifications", "hanh_dong": "update", "gia_tri": {"is_read": True}, "loc": [{"op": "eq", "cot": "id", "gt": ds[0]["id"]}]},
			self.chu)
		self.assertTrue(doc({"bang": "notifications", "select": "is_read"}, self.chu)["data"][0]["is_read"])

	def test_organizations_settings_va_quyen_sua(self):
		org = doc({"bang": "organizations", "select": "id, name, settings, allow_oversell, completed_edit_days"}, self.nv)["data"][0]
		self.assertEqual(org["completed_edit_days"], 1)
		self.assertIsInstance(org["settings"], dict)
		ghi({"bang": "organizations", "hanh_dong": "update", "gia_tri": {"name": "NPP Đổi Bậy"}, "loc": [{"op": "eq", "cot": "id", "gt": org["id"]}]},
			self.nv)
		self.assertNotEqual(frappe.db.get_single_value("NPP Cai Dat", "ten_npp"), "NPP Đổi Bậy")
		ghi({"bang": "organizations", "hanh_dong": "update", "gia_tri": {"settings": {**org["settings"], "address": "12 Lê Lợi", "logo_url": "x.png"}},
			"loc": [{"op": "eq", "cot": "id", "gt": org["id"]}]}, self.chu)
		moi = doc({"bang": "organizations", "select": "settings"}, self.chu)["data"][0]["settings"]
		self.assertEqual(moi["address"], "12 Lê Lợi")
		self.assertEqual(moi["logo_url"], "x.png")
		# approval_rules: NVBH đọc ra rỗng (evaluateApproval dùng mặc định)
		self.assertEqual(doc({"bang": "approval_rules", "select": "id"}, self.nv)["data"], [])
		self.assertEqual(len(doc({"bang": "approval_rules", "select": "auto_approve_max"}, self.ql)["data"]), 1)
