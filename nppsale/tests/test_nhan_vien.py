"""NPP Nhan Vien ↔ User (cần bench): bench --site poc.local run-tests --module nppsale.tests.test_nhan_vien"""
import frappe
from frappe.tests import IntegrationTestCase

from nppsale.luat.sdt import email_ky_thuat


def _tao(sdt, ten="NV thử", vai="sales", **them):
	email = email_ky_thuat(sdt)
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": ten, "send_welcome_email": 0}).insert(ignore_permissions=True)
	return frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": ten, "vai": vai, "sdt": sdt, **them}).insert(
		ignore_permissions=True
	)


class TestNhanVien(IntegrationTestCase):
	def test_dong_bo_user_va_vai(self):
		nv = _tao("0911 000 101", ten="Nguyễn Văn Thử", vai="sales")
		self.assertEqual(nv.name, "0911000101@nppsale.local")
		u = frappe.get_doc("User", nv.user)
		self.assertEqual(u.first_name, "Nguyễn Văn Thử")
		self.assertEqual(u.mobile_no, "0911000101")
		self.assertIn("NPP NVBH", [r.role for r in u.roles])
		self.assertEqual(u.user_type, "Website User")
		# = viSearchKey(ho_ten, sdt) của nppsale: bản viết liền bỏ số 0 đầu từng từ ("0911 000 101" → "9110101")
		self.assertEqual(nv.khoa_tim, "nguyen van thu nguyenvanthu 0911 000 101 0911000101 9110101")
		nv.vai = "warehouse"
		nv.save(ignore_permissions=True)
		roles = [r.role for r in frappe.get_doc("User", nv.user).roles]
		self.assertIn("NPP Thu Kho", roles)
		self.assertNotIn("NPP NVBH", roles)
		nv.dang_hoat_dong = 0
		nv.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("User", nv.user, "enabled"), 0)

	def test_sdt_trung_sau_chuan_hoa_bi_chan(self):
		_tao("0911000102")
		# Người khác (email kỹ thuật khác — ví dụ đã đổi SĐT) nhập cùng số theo kiểu khác → chặn như idx_users_phone_unique
		email = "khac-0911000102@nppsale.local"
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": "Khác", "send_welcome_email": 0}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": "Khác", "vai": "sales", "sdt": "+84 911 000 102"}).insert(
				ignore_permissions=True
			)

	def test_khong_gan_vai_tai_xe(self):
		with self.assertRaises(frappe.ValidationError):
			_tao("0911000103", vai="driver")

	def test_tran_giam(self):
		with self.assertRaises(frappe.ValidationError):
			_tao("0911000104", co_tran_giam=1, kieu_tran_giam="pct", tran_giam=150)
		nv = _tao("0911000105", co_tran_giam=1, kieu_tran_giam="vnd", tran_giam=1500.6)
		self.assertEqual(nv.tran_giam, 1501)
