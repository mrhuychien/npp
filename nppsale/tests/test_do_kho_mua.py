"""Đo hành vi lõi ERPNext 16 mà P4 dựa vào (đặc tả kho_mua §8 dòng M0: "đo §7.3 điểm 19, 31 phần PI") — ghim thành bài để nâng lõi mà hành vi
đổi thì đỏ ngay. Kết quả đo 17/11/2026 (erpnext 16.53, site poc.local) ghi ở 00_quyet_dinh_trien_khai.md mục Q9:

- §7.3 điểm 19 — hệ số quy đổi dòng phiếu nhập: lõi GIỮ hệ số dòng gửi lên (thùng ×20 dù danh mục ×24) và nhận đơn vị không khai trong
  `Item.uoms` — như nppsale tin hệ số trình duyệt; không cần gán lại sau `set_missing_values`.
- §7.3 điểm 31 (phần PI): (a) PI nháp KHÔNG nhận dòng SL 0 (phiếu nhập: InvalidQtyError lúc insert; tờ trả có kho: "'0' qty Items are not
  allowed") → cổng ghi nháp phải chặn trước (§7.3 điểm 23); (b) huỷ tờ trả NCC khi lô đã `disabled` vẫn được — hàng về lại lô đang tắt
  (method mở lại lô như `cancel_supplier_return` mig 235); (c) tờ trả NCC độc lập xuất theo GIÁ LÔ (Serial and Batch Entry `incoming_rate` /
  SLE `valuation_rate`), không theo đơn giá trả — chênh vào `Company.default_expense_account` (§7.1 #4); `PI Item.valuation_rate` = giá trả NCC
  (cổng `stock_entry_lines.unit_cost` phải đọc sổ kho — soát thiếu S2).

	bench --site poc.local run-tests --module nppsale.tests.test_do_kho_mua
"""
from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, nowdate

from nppsale.rpc.goi_lo import gan_goi_lo, lap_goi_lo, lo_theo_kho
from nppsale.thiet_lap.kho_mua import cai_dat_kho


class TestDoKhoMua(IntegrationTestCase):
	def setUp(self):
		frappe.db.savepoint("npp_test")
		for p in (patch.object(frappe.db, "commit", lambda *a, **k: None), patch.object(frappe, "log_error", lambda *a, **k: None)):
			p.start()
			self.addCleanup(p.stop)
		frappe.local._npp_cai_dat_ban = None
		self.cd = cai_dat_kho()
		from nppsale.rpc.don_hang import _dam_bao_uom

		for u in ("Lon", "Thung", "Hop"):
			_dam_bao_uom(u)
		nhom = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		self.ncc = frappe.get_doc({"doctype": "Supplier", "supplier_name": "VTD Do M0",
			"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")}).insert(ignore_permissions=True).name
		self.lo = frappe.get_doc({"doctype": "Item", "item_code": "VTD-DO-M0", "item_name": "Do M0", "item_group": nhom, "stock_uom": "Lon",
			"is_stock_item": 1, "has_batch_no": 1, "create_new_batch": 0, "uoms": [{"uom": "Thung", "conversion_factor": 24}]}).insert(
			ignore_permissions=True).name
		self.x = frappe.get_doc({"doctype": "Item", "item_code": "VTD-DO-M0-X", "item_name": "Do M0 X", "item_group": nhom, "stock_uom": "Lon",
			"is_stock_item": 1, "uoms": [{"uom": "Thung", "conversion_factor": 24}]}).insert(ignore_permissions=True).name

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_cai_dat_ban = None

	def _pi(self, dong: list[dict], **them):
		pi = frappe.new_doc("Purchase Invoice")
		pi.update({"naming_series": "PN-.####", "supplier": self.ncc, "company": self.cd.cong_ty, "posting_date": nowdate(), "set_posting_time": 1,
			"disable_rounded_total": 1, "taxes_and_charges": "", "update_stock": 1, "set_warehouse": self.cd.kho_ban, **them})
		for d in dong:
			pi.append("items", {"conversion_factor": 1, "uom": "Lon", "warehouse": them.get("set_warehouse", self.cd.kho_ban), **d})
		pi.set("taxes", [])
		pi.flags.ignore_permissions = True
		return pi

	def test_he_so_dong_giu_nguyen(self):
		"""§7.3 điểm 19."""
		for uom, hs in (("Thung", 20), ("Hop", 10)):
			pi = self._pi([{"item_code": self.x, "qty": 2, "uom": uom, "conversion_factor": hs, "rate": 1000, "price_list_rate": 1000}])
			pi.insert()
			pi.submit()
			self.assertEqual((pi.items[0].conversion_factor, flt(pi.items[0].stock_qty)), (hs, 2 * hs), uom)
			self.assertEqual(flt(frappe.db.sql("""SELECT SUM(`actual_qty`) FROM `tabStock Ledger Entry` WHERE `voucher_no` = %s AND `is_cancelled` = 0""",
				pi.name)[0][0]), 2 * hs)
			self.assertTrue(pi.name.startswith("PN-"))  # dãy số PN- (mac_dinh._dat_ten_chung_tu)

	def test_nhap_khong_nhan_dong_sl_0(self):
		"""§7.3 điểm 31a — nháp đã từ chối, nên cổng ghi nháp chặn SL ≤ 0 bằng câu nppsale (§7.3 điểm 23)."""
		with self.assertRaises(frappe.ValidationError) as e:
			self._pi([{"item_code": self.x, "qty": 0, "rate": 1000}]).insert()
		self.assertIn("cannot be zero", str(e.exception))
		with self.assertRaises(frappe.ValidationError) as e:
			self._pi([{"item_code": self.x, "qty": 0, "rate": 1000}], is_return=1, naming_series="PTNCC-.####").insert()
		self.assertIn("'0' qty Items are not allowed", str(e.exception))

	def test_tra_ncc_doc_lap_gia_lo_va_huy_vao_lo_tat(self):
		"""§7.3 điểm 31b + 31c (S2)."""
		kho = self.cd.kho_can_date
		frappe.get_doc({"doctype": "Batch", "batch_id": "VTD-DO-L1", "item": self.lo}).insert(ignore_permissions=True)
		pn = self._pi([{"item_code": self.lo, "qty": 10, "rate": 8000, "price_list_rate": 8000}], set_warehouse=kho)
		gan_goi_lo(pn.items[0], lap_goi_lo("Inward", "Purchase Invoice", self.lo, kho, {"VTD-DO-L1": 10}, pn.posting_date, "08:00:00",
			self.cd.cong_ty))
		pn.insert()
		pn.submit()
		tra = self._pi([{"item_code": self.lo, "qty": -2, "rate": 9000, "price_list_rate": 9000}], set_warehouse=kho, is_return=1,
			naming_series="PTNCC-.####")
		gan_goi_lo(tra.items[0], lap_goi_lo("Outward", "Purchase Invoice", self.lo, kho, {"VTD-DO-L1": 2}, tra.posting_date, "09:00:00",
			self.cd.cong_ty))
		tra.insert()
		tra.submit()
		sle = frappe.db.get_value("Stock Ledger Entry", {"voucher_no": tra.name, "is_cancelled": 0}, ["actual_qty", "stock_value_difference",
			"valuation_rate"], as_dict=True)
		self.assertEqual((flt(sle.actual_qty), flt(sle.stock_value_difference), flt(sle.valuation_rate)), (-2, -16000, 8000))  # giá lô
		self.assertEqual(flt(frappe.db.get_value("Purchase Invoice Item", tra.items[0].name, "valuation_rate")), 9000)  # giá trả, KHÔNG phải giá vốn
		gl = {r.account: flt(r.credit) - flt(r.debit) for r in frappe.get_all("GL Entry", filters={"voucher_no": tra.name, "is_cancelled": 0},
			fields=["account", "debit", "credit"])}
		self.assertEqual(gl[frappe.get_cached_value("Company", self.cd.cong_ty, "default_expense_account")], 2000)  # chênh giá trả − giá lô
		self.assertEqual([(x.ma, x.ton) for x in lo_theo_kho(self.lo, kho)], [("VTD-DO-L1", 8)])
		frappe.db.set_value("Batch", "VTD-DO-L1", "disabled", 1)
		tra.reload()
		tra.flags.ignore_permissions = True
		tra.cancel()  # lô tắt vẫn nhận hàng về
		self.assertEqual(flt(frappe.db.sql("""SELECT SUM(e.`qty`) FROM `tabSerial and Batch Entry` e JOIN `tabSerial and Batch Bundle` b
			ON b.`name` = e.`parent` AND b.`docstatus` = 1 AND b.`is_cancelled` = 0 WHERE e.`batch_no` = 'VTD-DO-L1' AND e.`is_cancelled` = 0""")[0][0]), 10)
		self.assertEqual(lo_theo_kho(self.lo, kho), [])  # lô tắt không được chọn
