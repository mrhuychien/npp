"""Việc định kỳ nhắc khách (cần bench): bench --site poc.local run-tests --module nppsale.tests.test_nhac_khach"""
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime

from nppsale.lich.nhac_khach import nhac_anh_diem_ban, nhac_khach_chua_tuyen
from nppsale.luat.sdt import email_ky_thuat


def _nv(sdt, vai):
	email = email_ky_thuat(sdt)
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": vai, "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": f"NV {vai} {sdt[-2:]}", "vai": vai, "sdt": sdt}).insert(
			ignore_permissions=True)
	return email


class TestNhacKhach(IntegrationTestCase):
	def setUp(self):
		frappe.db.savepoint("npp_test")
		# chỉ khách của bài này đang bán — khách sẵn có trên site tạm ngừng để đếm cho gọn
		frappe.db.sql("UPDATE `tabCustomer` SET `npp_trang_thai` = 'inactive' WHERE `npp_trang_thai` = 'active'")
		frappe.db.sql("UPDATE `tabNPP Nhan Vien` SET `dang_hoat_dong` = 0 WHERE `vai` IN ('owner', 'manager')")
		self.nv = _nv("0916000801", "sales")
		self.chu = _nv("0916000802", "owner")
		frappe.db.set_value("NPP Nhan Vien", self.chu, "dang_hoat_dong", 1)
		nhom = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		self.k = {}
		for ma, vi_tri, tuyen in (("du", True, "T2"), ("thieu_anh", True, None), ("khong_vi_tri", False, "T3"), ("khong_ai", False, None)):
			self.k[ma] = frappe.get_doc({"doctype": "Customer", "customer_name": f"Nhắc {ma}", "customer_group": nhom, "customer_type": "Company",
				"npp_trang_thai": "active", "npp_vi_do": 21.0 if vi_tri else 0, "npp_kinh_do": 105.8 if vi_tri else 0,
				"npp_tuyen": tuyen}).insert(ignore_permissions=True).name
		for ma in ("du", "thieu_anh", "khong_vi_tri"):
			frappe.get_doc({"doctype": "NPP Phan Cong Khach", "khach": self.k[ma], "nhan_vien": self.nv, "vai_tro": "primary",
				"trang_thai": "active"}).insert(ignore_permissions=True)
		frappe.flags.npp_duyet_anh_diem_ban = True
		for ma in ("du", "khong_vi_tri"):
			frappe.get_doc({"doctype": "NPP Anh Diem Ban", "khach": self.k[ma], "o_anh": 1, "anh_url": f"x/{ma}.jpg",
				"chup_luc": now_datetime()}).insert(ignore_permissions=True)
		frappe.flags.npp_duyet_anh_diem_ban = False

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")

	def _bao(self, loai, nguoi):
		return frappe.get_all("NPP Thong Bao", filters={"loai": loai, "nguoi_nhan": nguoi}, fields=["tieu_de", "noi_dung", "duong_dan", "du_lieu"])

	def test_nhac_anh_diem_ban(self):
		bao = nhac_anh_diem_ban(commit=False)
		self.assertEqual((bao["notified_reps"], bao["customers_flagged"], bao["unassigned"]), (1, 2, 1))
		tb = self._bao("customer_photo_missing", self.nv)
		self.assertEqual(len(tb), 1)
		self.assertEqual((tb[0].tieu_de, tb[0].duong_dan), ("2 điểm bán chưa có ảnh / vị trí", "/customers/missing-photos"))
		self.assertEqual(sorted(frappe.parse_json(tb[0].du_lieu)["customer_ids"]), sorted([self.k["thieu_anh"], self.k["khong_vi_tri"]]))
		self.assertTrue(frappe.db.get_value("Customer", self.k["thieu_anh"], "npp_nhac_anh_luc"))
		self.assertFalse(frappe.db.get_value("Customer", self.k["du"], "npp_nhac_anh_luc"))
		self.assertFalse(frappe.db.get_value("Customer", self.k["khong_ai"], "npp_nhac_anh_luc"))  # không ai nhận → không đóng dấu
		bao = nhac_anh_diem_ban(commit=False)  # ngay sau: hạ nhiệt
		self.assertEqual((bao["notified_reps"], bao["cooled_down"]), (0, 2))
		frappe.db.set_value("Customer", self.k["thieu_anh"], "npp_nhac_anh_luc", add_days(now_datetime(), -8))
		self.assertEqual(nhac_anh_diem_ban(commit=False)["customers_flagged"], 1)

	def test_nhac_khach_chua_tuyen(self):
		bao = nhac_khach_chua_tuyen(commit=False)
		self.assertEqual((bao["notified"], bao["customers_flagged"]), (2, 2))
		self.assertEqual([t.tieu_de for t in self._bao("customer_route_missing", self.nv)], ["1 khách hàng chưa gán tuyến"])
		tb = self._bao("customer_route_missing", self.chu)  # khách không ai phụ trách → chủ / quản lý đang làm
		self.assertEqual(frappe.parse_json(tb[0].du_lieu)["customer_ids"], [self.k["khong_ai"]])
		self.assertEqual(tb[0].duong_dan, "/customers?tuyen=chua")
		self.assertEqual(nhac_khach_chua_tuyen(commit=False)["cooled_down"], 2)
