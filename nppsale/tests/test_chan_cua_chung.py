"""Chặn cửa đọc / ghi chung của lõi với người chỉ mang vai NPP (thuần): python3 -m unittest nppsale.tests.test_chan_cua_chung"""
import unittest

from nppsale.portal.chan import bi_chan, chi_vai_npp


class TestChanCuaChung(unittest.TestCase):
	def test_ai_bi_ap(self):
		self.assertTrue(chi_vai_npp({"NPP NVBH", "All", "Guest"}))
		self.assertTrue(chi_vai_npp({"NPP Chu", "NPP Ke Toan", "Desk User", "All"}))
		self.assertFalse(chi_vai_npp({"NPP Chu", "System Manager", "All"}))  # có vai lõi → không áp
		self.assertFalse(chi_vai_npp({"All", "Guest"}))  # không phải người của app

	def test_cua_bi_chan(self):
		for duong, cmd in (("/api/resource/Item", None), ("/api/resource/Sales Invoice/HD-0001", None),
				("/api/v2/document/Customer", None), ("/api/method/frappe.client.get_list", None),
				("/api/method/frappe.desk.reportview.get", None), ("/api/method/frappe.desk.search.search_link", None),
				("/api/method/run_doc_method", None), ("/api/method/upload_file", None),
				("/api/method/erpnext.stock.get_item_details.get_item_details", None), ("/", "frappe.client.get_list")):
			self.assertTrue(bi_chan(duong, cmd), duong + (cmd or ""))

	def test_cua_duoc_mo(self):
		for duong in ("/api/method/nppsale.cong.api.truy_van", "/api/method/nppsale.cong.api.rpc", "/api/method/nppsale.api.phien.ngu_canh",
				"/api/method/nppsale.api.tuyen.goi", "/api/method/login", "/api/method/logout", "/api/method/frappe.auth.get_logged_user",
				"/api/method/frappe.realtime.get_user_info", "/nppsale/orders", "/rest/v1/customers", "/assets/nppsale/x.js"):
			self.assertFalse(bi_chan(duong, None), duong)


if __name__ == "__main__":
	unittest.main()
