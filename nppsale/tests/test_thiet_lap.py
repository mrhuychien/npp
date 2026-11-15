"""Các mục "Mã cần đổi" của blueprint 02 §7.2: cột Link tới DocType UUID, /api/do-nap tách cột, Customer Group tăng số phiên danh mục.

	bench --site poc.local run-tests --module nppsale.tests.test_thiet_lap
"""
from __future__ import annotations

import json

import frappe
from frappe.tests import IntegrationTestCase


class TestThietLap(IntegrationTestCase):
	def setUp(self):
		frappe.db.savepoint("npp_test")

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")

	def test_cot_link_uuid(self):
		from nppsale.thiet_lap.cot_uuid import cot_can_doi, dam_bao

		def kieu(dt, cot):
			return frappe.db.sql("""SELECT `DATA_TYPE` FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = %s
				AND column_name = %s""", (f"tab{dt}", cot))[0][0]

		self.assertEqual(cot_can_doi(), [])
		for dt, cot in (("NPP Yeu Cau Anh Diem Ban", "anh"), ("NPP Phieu Thu Dong", "cong_no")):
			self.assertEqual(kieu(dt, cot), "uuid", (dt, cot))
		# cài mới tạo bảng trước DocType đích → cột varchar: bước thiết lập phải trả về uuid (DDL tự commit — dựng lại điểm lui cho tearDown)
		try:
			frappe.db.sql_ddl("ALTER TABLE `tabNPP Phieu Thu Dong` MODIFY `cong_no` varchar(140)")
			self.assertEqual(cot_can_doi(), [("NPP Phieu Thu Dong", "cong_no")])
			dam_bao()
			self.assertEqual((kieu("NPP Phieu Thu Dong", "cong_no"), cot_can_doi()), ("uuid", []))
		finally:
			if kieu("NPP Phieu Thu Dong", "cong_no") != "uuid":
				frappe.db.sql_ddl("ALTER TABLE `tabNPP Phieu Thu Dong` MODIFY `cong_no` uuid")
			frappe.db.savepoint("npp_test")

	def test_do_nap_tach_cot(self):
		from nppsale.api.do_nap import ghi
		from nppsale.api.tuyen import YeuCauCu

		def goi(than):
			return ghi(YeuCauCu(duong="/api/do-nap", phuong_thuc="POST", than=than))

		truoc = set(frappe.get_all("NPP Do Nap", pluck="name"))
		goi_tin = {"man": "bc-ban-hang", "ms": 1234.6, "tuMoTrang": True, "loi": None, "dong": 12, "trang": {"ttfb": 210, "dcl": 900},
			"soCau": 7, "cham": [{"p": "/rest/v1/rpc/x", "m": "GET", "ms": 800, "tt": 200}], "mang": {"loai": "4g", "rtt": 50, "mbps": 9.5},
			"user": "gia-mao@x"}
		self.assertEqual(goi(json.dumps(goi_tin)), (204, None))
		self.assertEqual(goi(json.dumps({"ms": 5})), (204, None))  # thiếu `man` vẫn ghi (như route nppsale)
		self.assertEqual(goi("[1, 2]")[0], 400)
		self.assertEqual(goi("{hỏng")[0], 400)
		moi = frappe.get_all("NPP Do Nap", filters={"name": ("not in", list(truoc) or [""])},
			fields=["man", "nhan", "ms", "tu_mo_trang", "dong", "ttfb_ms", "dcl_ms", "so_cau", "mang_loai", "mang_rtt", "mang_mbps", "noi_dung", "cham"],
			order_by="creation asc")
		self.assertEqual(len(moi), 2)
		a, b = moi
		self.assertEqual((a.man, a.nhan, a.ms, a.tu_mo_trang, a.dong, a.ttfb_ms, a.dcl_ms, a.so_cau, a.mang_loai, a.mang_rtt, a.mang_mbps),
			("bc-ban-hang", "bao-cao-nap", 1235, 1, 12, 210, 900, 7, "4g", 50, 9.5))
		self.assertEqual(json.loads(a.noi_dung)["user"], "Administrator")  # thân có khoá `user` cũng không đè người đăng nhập
		self.assertEqual(json.loads(a.cham)[0]["ms"], 800)
		self.assertEqual((b.man, b.nhan, b.ms), (None, "pos-nap", 5))

	def test_nhom_khach_doi_bang_gia_tang_phien_danh_muc(self):
		def phien():
			return frappe.db.get_value("NPP Phien Danh Muc", "1", ["phien", "phien_khach"])

		goc = frappe.db.get_value("Customer Group", {"is_group": 1}, "name")
		g = frappe.get_doc({"doctype": "Customer Group", "customer_group_name": "Nhom thu phien", "parent_customer_group": goc,
			"is_group": 0}).insert(ignore_permissions=True)
		p0 = phien()
		g.reload()
		g.flags.ignore_permissions = True
		g.save()  # lưu không đổi bảng giá: chỉ số phiên khách
		p1 = phien()
		self.assertEqual((p1[0], p1[1] > p0[1]), (p0[0], True))
		bg = frappe.get_doc({"doctype": "Price List", "price_list_name": "Bang gia thu phien", "currency": "VND", "selling": 1}).insert(
			ignore_permissions=True)
		p1 = phien()
		g.reload()
		g.default_price_list = bg.name
		g.save()
		self.assertGreater(phien()[0], p1[0])
		p2 = phien()
		frappe.rename_doc("Customer Group", g.name, "Nhom thu phien 2", force=True, show_alert=False)
		self.assertGreater(phien()[0], p2[0])
