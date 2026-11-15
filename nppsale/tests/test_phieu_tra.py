"""Phiếu trả (P3c): bảng cổng returns / return_lines (đọc + ghi thẳng theo RLS + khoá trình duyệt), controller NPP Phieu Tra.
Bài vàng so Postgres thật của nppsale: test_phieu_tra_vang (dữ liệu tools/vang_phieu_tra.py).

	bench --site poc.local run-tests --module nppsale.tests.test_phieu_tra
"""
from __future__ import annotations

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.ghi import ghi
from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong
from nppsale.cong.truy_van import doc
from nppsale.tests import test_xuat_hang as XH
from nppsale.tests.test_tao_don import dung_nen


class TestPhieuTraCong(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(XH.VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)

	def setUp(self):
		frappe.db.savepoint("npp_test")
		frappe.local._npp_cai_dat_ban = None
		self.ma = dung_nen(self.vang["nen"])
		XH.dung_kho(self.vang["nen"], self.ma)

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_ngu_canh = None

	def _nc(self, nguoi: str) -> NguCanh:
		u = self.ma["u:" + nguoi]
		return NguCanh(user=u, vai=frappe.db.get_value("NPP Nhan Vien", u, "vai"))

	def _ghi(self, nguoi: str, yc: dict) -> dict:
		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None
		try:
			return ghi(yc, self._nc(nguoi))
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	def test_ghi_thang_phieu_nhap(self):
		k = self.ma["C1"]
		pt = self._ghi("sales_a", {"bang": "returns", "hanh_dong": "insert", "gia_tri": {"customer_id": k, "status": "draft",
			"reason": "damaged", "notes": "n1"}, "select": "id, status, sales_user_id, requested_by, credit_note_amount"})["data"][0]
		self.assertTrue(pt["id"].startswith("PT-"))
		self.assertEqual((pt["status"], pt["sales_user_id"], pt["requested_by"]), ("draft", self.ma["u:sales_a"], self.ma["u:sales_a"]))
		dong = self._ghi("sales_a", {"bang": "return_lines", "hanh_dong": "insert", "gia_tri": [
			{"return_id": pt["id"], "product_id": self.ma["P1"], "unit_name": "Lon", "quantity": 2, "unit_price": 9500, "vat_rate": 0.08,
				"line_total": 1},
			{"return_id": pt["id"], "product_id": self.ma["P2"], "unit_name": "", "quantity": 1, "unit_price": 5000, "vat_rate": 0.1,
				"is_exchange": True, "note": "doi"}], "select": "id, line_total, unit_name"})["data"]
		self.assertEqual([(x["line_total"], x["unit_name"]) for x in dong], [(20520, "Lon"), (5500, "Chai")])  # thành tiền máy tính
		r = doc({"bang": "returns", "select": "id, credit_note_amount, lines:return_lines(product_id, is_exchange, line_total)",
			"loc": [{"op": "eq", "cot": "id", "gt": pt["id"]}]}, self._nc("sales_a"))["data"][0]
		self.assertEqual(flt(r["credit_note_amount"]), 20520)  # hàng đổi không ghi có
		self.assertEqual([x["is_exchange"] for x in r["lines"]], [False, True])  # thứ tự chèn (idx)
		# NVBH khác không thấy, không sửa được (0 dòng, không lỗi)
		self.assertEqual(doc({"bang": "returns", "select": "id", "loc": [{"op": "eq", "cot": "id", "gt": pt["id"]}]}, self._nc("sales_b"))["data"], [])
		self.assertEqual(self._ghi("sales_b", {"bang": "returns", "hanh_dong": "update", "gia_tri": {"notes": "x"},
			"loc": [{"op": "eq", "cot": "id", "gt": pt["id"]}], "select": "id"})["data"], [])
		# đổi trạng thái thẳng bị khoá
		with self.assertRaises(NppLoi) as e:
			self._ghi("owner", {"bang": "returns", "hanh_dong": "update", "gia_tri": {"status": "completed"},
				"loc": [{"op": "eq", "cot": "id", "gt": pt["id"]}]})
		self.assertEqual(str(e.exception), "PHIEU_TRA_KHOA: trạng thái phiếu trả chỉ đổi qua Hoàn thành / Huỷ (draft → completed)")
		# thủ kho không lập phiếu (RLS WITH CHECK)
		with self.assertRaises(LoiCong) as e:
			self._ghi("warehouse", {"bang": "returns", "hanh_dong": "insert", "gia_tri": {"customer_id": k, "status": "draft"}})
		self.assertEqual(e.exception.ma, "42501")
		# lập thẳng không gửi status (mặc định 'pending') → khoá
		with self.assertRaises(NppLoi):
			self._ghi("sales_a", {"bang": "returns", "hanh_dong": "insert", "gia_tri": {"customer_id": k}})
		# sửa ghi chú phiếu nháp của mình; xoá trả đúng dòng đã xoá
		self.assertEqual(self._ghi("sales_a", {"bang": "returns", "hanh_dong": "update", "gia_tri": {"notes": "n2"},
			"loc": [{"op": "eq", "cot": "id", "gt": pt["id"]}], "select": "id, notes"})["data"], [{"id": pt["id"], "notes": "n2"}])
		xoa = self._ghi("sales_a", {"bang": "returns", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "id", "gt": pt["id"]}],
			"select": "id"})
		self.assertEqual(xoa["data"], [{"id": pt["id"]}])
		self.assertFalse(frappe.db.exists("NPP Phieu Tra", pt["id"]))
