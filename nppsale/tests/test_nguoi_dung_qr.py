"""Quản lý NV + mã QR (cần bench): bench --site poc.local run-tests --module nppsale.tests.test_nguoi_dung_qr"""
import frappe
from frappe.tests import IntegrationTestCase

from nppsale.api import nguoi_dung, qr
from nppsale.api.tuyen import YeuCauCu
from nppsale.luat.sdt import email_ky_thuat


def _nv(sdt, vai):
	email = email_ky_thuat(sdt)
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": vai, "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": vai, "vai": vai, "sdt": sdt}).insert(ignore_permissions=True)
	return email


def _yc(pt, duong, than=None, **tham):
	return YeuCauCu(duong=duong, phuong_thuc=pt, tham=tham, than=than)


class TestNguoiDungQR(IntegrationTestCase):
	def setUp(self):
		self.chu = _nv("0915000601", "owner")
		self.nvbh = _nv("0915000602", "sales")
		frappe.set_user(self.chu)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_tao_phat_thu_hoi_xoa(self):
		ma, kq = nguoi_dung.tao(_yc("POST", "/api/admin/users", {"phone": "+84 915 000 609", "password": "MatKhau#609",
			"full_name": "NV Mới", "role": "accountant"}))
		self.assertEqual(ma, 200, kq)
		email = kq["id"]
		self.assertEqual(email, "0915000609@nppsale.local")
		nv = frappe.get_doc("NPP Nhan Vien", email)
		self.assertEqual(nv.cho_sua_gia, 1)  # kế toán / chủ: "free"
		self.assertEqual(nv.qr_token_bam, qr.bam(kq["token"]))
		self.assertTrue(kq["loginUrl"].endswith(f"/nppsale/qr-login?t={kq['token']}"))
		ma, lay = qr.lay(_yc("GET", "", id=email))
		self.assertEqual(lay["token"], kq["token"])
		ma, moi = qr.phat(_yc("POST", "", id=email))
		self.assertNotEqual(moi["token"], kq["token"])
		self.assertEqual(frappe.db.get_value("NPP Nhan Vien", email, "qr_token_bam"), qr.bam(moi["token"]))
		qr.thu_hoi(_yc("DELETE", "", id=email))
		self.assertEqual(qr.ds_link(_yc("GET", ""))[1]["links"].get(email), None)
		ma, kq = nguoi_dung.xoa(_yc("DELETE", "", id=email))
		self.assertEqual(ma, 200)
		self.assertFalse(frappe.db.exists("User", email))

	def test_tao_trung_so_va_quyen(self):
		ma, kq = nguoi_dung.tao(_yc("POST", "", {"phone": "0915.000.602", "password": "x", "full_name": "Trùng", "role": "sales"}))
		self.assertEqual((ma, kq["error"]), (400, "Số điện thoại đã được dùng cho tài khoản khác."))
		frappe.set_user(self.nvbh)
		ma, kq = nguoi_dung.tao(_yc("POST", "", {"phone": "0915000610", "password": "x", "full_name": "Y", "role": "sales"}))
		self.assertEqual(ma, 403)
		ma, _ = qr.lay(_yc("GET", "", id=self.chu))
		self.assertEqual(ma, 403)

	def test_khong_tu_xoa(self):
		self.assertEqual(nguoi_dung.xoa(_yc("DELETE", "", id=self.chu))[0], 400)
