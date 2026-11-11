"""Vỏ trang portal (cần bench): hồ sơ gửi kèm là MỘT object như users của nppsale (NapHoSo / hoSoGuiKemDung so `id`)."""
import frappe
from frappe.tests import IntegrationTestCase

from nppsale.luat.sdt import email_ky_thuat
from nppsale.portal.vo import ho_so_nguoi_dung, ngu_canh_trang


class TestVoTrang(IntegrationTestCase):
	def test_ho_so_la_mot_object(self):
		email = email_ky_thuat("0914000501")
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": "Vỏ", "send_welcome_email": 0}).insert(ignore_permissions=True)
			frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": "Vỏ Trang", "vai": "accountant", "sdt": "0914000501"}).insert(
				ignore_permissions=True
			)
		frappe.set_user(email)
		frappe.local._npp_ngu_canh = None
		try:
			hs = ho_so_nguoi_dung(email)
			nc = ngu_canh_trang()
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None
		self.assertIsInstance(hs, dict)
		self.assertEqual(hs["id"], email)
		self.assertEqual(hs["role"], "accountant")
		self.assertEqual(nc["user"], email)
		self.assertTrue(nc["csrf_token"])

	def test_khach_khong_co_ho_so(self):
		self.assertIsNone(ho_so_nguoi_dung("Guest"))
