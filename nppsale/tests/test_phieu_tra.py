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

	def _goi(self, nguoi: str, ten: str, ts: dict) -> dict:
		from nppsale.cong import api

		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None
		try:
			return api.rpc(ten=ten, tham_so=ts)
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	def _ton(self, lo: str) -> float:
		ds = doc({"bang": "batches", "select": "batch_code, warehouse_zone, qty_on_hand", "loc": [{"op": "eq", "cot": "batch_code", "gt": lo}]},
			self._nc("owner"))["data"]
		return sum(flt(x["qty_on_hand"]) for x in ds if x["warehouse_zone"] == "sale")

	def test_tu_lap_doc_lap_hoan_thanh_va_huy(self):
		k = self.ma["C1"]
		ton_l2 = self._ton("L2-MOI-HAN-SOM")
		ket = self._goi("owner", "save_pos_return", {"p": {"customer_id": k, "reason": "damaged", "zone": "sale", "lines": [
			{"product_id": self.ma["P1"], "unit_name": "Lon", "quantity": 2, "unit_price": 9500, "vat_rate": 0.08},
			{"product_id": self.ma["P2"], "unit_name": "Chai", "quantity": 1, "unit_price": 0, "vat_rate": 0, "is_exchange": True}]}})
		self.assertNotIn("error", ket, ket)
		pt = ket["data"]
		r = frappe.get_doc("NPP Phieu Tra", pt)
		self.assertEqual((r.trang_thai, flt(r.tien_tra), r.nhan_vien), ("draft", 20520, self.ma["u:owner"]))
		ket = self._goi("owner", "complete_return", {"p_return_id": pt, "p_zone": "sale"})
		self.assertNotIn("error", ket, ket)
		r.reload()
		self.assertEqual(r.trang_thai, "completed")
		self.assertTrue(r.to_ghi_co and r.to_ghi_co.startswith("HDT-"), r.to_ghi_co)
		self.assertEqual(ket["data"], [{"entry_id": r.to_ghi_co}])
		cn = frappe.get_doc("Sales Invoice", r.to_ghi_co)
		self.assertEqual((cn.is_return, cn.update_stock, cn.docstatus), (1, 1, 1))
		self.assertEqual(flt(cn.grand_total), -20520)
		self.assertEqual(self._ton("L2-MOI-HAN-SOM"), ton_l2 + 2)  # lô mới nhất của P1 ở kho bán
		no = doc({"bang": "receivables", "select": "amount, paid, status, return_id, invoice_id",
			"loc": [{"op": "eq", "cot": "return_id", "gt": pt}]}, self._nc("owner"))["data"]
		self.assertEqual(no, [{"amount": -20520, "paid": 0, "status": "open", "return_id": pt, "invoice_id": None}])
		self.assertIsNotNone(r.ghi_co_luc)
		self.assertEqual(str(r.ngay_tru_doanh_so), str(frappe.utils.getdate(r.ghi_co_luc)))
		# huỷ: đảo kho, bỏ dòng nợ âm, phiếu Đã huỷ
		ket = self._goi("owner", "cancel_return", {"p_return_id": pt, "p_reason": "Nhap nham"})
		self.assertNotIn("error", ket, ket)
		r.reload()
		self.assertEqual((r.trang_thai, r.ly_do_huy, r.to_ghi_co, r.ghi_co_luc, r.ngay_tru_doanh_so), ("cancelled", "Nhap nham", None, None, None))
		self.assertEqual(frappe.db.get_value("Sales Invoice", cn.name, "docstatus"), 2)
		self.assertEqual(self._ton("L2-MOI-HAN-SOM"), ton_l2)
		self.assertEqual(doc({"bang": "receivables", "select": "id", "loc": [{"op": "eq", "cot": "return_id", "gt": pt}]},
			self._nc("owner"))["data"], [])
		ket = self._goi("owner", "cancel_return", {"p_return_id": pt, "p_reason": "x"})
		self.assertEqual(ket["error"]["message"], "RETURN_NOT_CANCELLABLE: phiếu ở trạng thái cancelled không huỷ được")
