"""Đọc kho trên cổng: bảng `batches` (lô × kho từ gói lô, lô ảo hàng không lô) + RPC ton_ban_theo_hang / stock_value_summary /
committed_stock_by_product — trên bộ lô của bài Xuất hàng (cùng nền với bộ vàng nppsale: mã lô, SL, vùng, giá vốn, ngày nhận, hạn).

	bench --site poc.local run-tests --module nppsale.tests.test_kho_doc
"""
from __future__ import annotations

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.truy_van import doc
from nppsale.tests import test_xuat_hang as XH
from nppsale.tests.test_tao_don import doi_khoa, dung_nen


class TestKhoDoc(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(XH.VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)

	def setUp(self):
		frappe.db.savepoint("npp_test")
		frappe.local._npp_cai_dat_ban = None
		frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 0)
		self.ma = dung_nen(self.vang["nen"])
		XH.dung_kho(self.vang["nen"], self.ma)

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")

	def _nc(self, nguoi: str) -> NguCanh:
		u = self.ma["u:" + nguoi]
		return NguCanh(user=u, vai=frappe.db.get_value("NPP Nhan Vien", u, "vai"))

	def _goi(self, nguoi: str, ten: str, ts: dict | None = None) -> dict:
		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None
		try:
			return api.rpc(ten=ten, tham_so=ts or {})
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	def _lo(self, nguoi="sales_a") -> dict:
		hang = [self.ma[k] for k in ("P1", "P2")]
		ds = doc({"bang": "batches", "select": "id, product_id, batch_code, expires_at, qty_initial, qty_on_hand, unit_cost, status, "
			"warehouse_zone, received_at, product:products(sku)", "loc": [{"op": "in", "cot": "product_id", "gt": hang}]}, self._nc(nguoi))["data"]
		return {x["batch_code"]: x for x in ds}

	def test_lo_theo_kho_nhu_nen_nppsale(self):
		lo = self._lo()
		hom_nay = getdate(XH.hom_nay())
		for ma, sp, sl, nhan, han, gia, vung in self.vang["nen"]["lo"]:
			x = lo[ma]
			self.assertEqual(x["id"], f"{ma}::{vung}")
			self.assertEqual(x["product_id"], self.ma[sp])
			self.assertEqual(x["warehouse_zone"], vung)
			self.assertEqual(flt(x["qty_on_hand"]), sl)
			self.assertEqual(flt(x["qty_initial"]), sl)
			self.assertAlmostEqual(flt(x["unit_cost"]), gia, places=4)
			self.assertEqual(getdate(x["expires_at"]), add_days(hom_nay, han))
			self.assertEqual(getdate(x["received_at"]), add_days(hom_nay, nhan))
			self.assertEqual(x["status"], "available")
			self.assertEqual(x["product"]["sku"], self.ma[sp])
		# lọc như màn kho: còn hàng + vùng bán, sắp theo hạn
		ban = doc({"bang": "batches", "select": "batch_code", "loc": [{"op": "gt", "cot": "qty_on_hand", "gt": 0},
			{"op": "eq", "cot": "warehouse_zone", "gt": "sale"}, {"op": "in", "cot": "product_id", "gt": [self.ma["P1"], self.ma["P2"]]}],
			"thu_tu": [{"cot": "expires_at"}]}, self._nc("warehouse"))["data"]
		self.assertEqual([x["batch_code"] for x in ban], ["L2-MOI-HAN-SOM", "L1-CU", "L4-DAU"])

	def test_ton_ban_gia_tri_va_xuat_tru_ton(self):
		ton = self._goi("sales_a", "ton_ban_theo_hang")["data"]
		self.assertEqual(flt(ton[self.ma["P1"]]), 80)  # L1 30 + L2 50 (L3 ở kho cận date)
		self.assertEqual(flt(ton[self.ma["P2"]]), 10)
		gt = self._goi("owner", "stock_value_summary")["data"][0]
		lo_tat_ca = doc({"bang": "batches", "select": "qty_on_hand, unit_cost", "loc": [{"op": "gt", "cot": "qty_on_hand", "gt": 0}]},
			self._nc("owner"))["data"]
		self.assertEqual(gt["batch_count"], len(lo_tat_ca))
		self.assertAlmostEqual(flt(gt["inventory_value"]), sum(flt(x["qty_on_hand"]) * flt(x["unit_cost"]) for x in lo_tat_ca), places=2)
		# xuất HĐ 2 lon P1 + 1 chai P2 (FIFO: L1-CU, L4-DAU) → tồn lô giảm, tồn bán giảm
		don, hd = XH.TestXuatHang._don_da_xuat(self)
		self.assertTrue(don)
		lo = self._lo()
		self.assertEqual(flt(lo["L1-CU"]["qty_on_hand"]), 28)
		self.assertEqual(flt(lo["L1-CU"]["qty_initial"]), 30)
		self.assertEqual(flt(lo["L4-DAU"]["qty_on_hand"]), 9)
		ton = self._goi("sales_a", "ton_ban_theo_hang")["data"]
		self.assertEqual((flt(ton[self.ma["P1"]]), flt(ton[self.ma["P2"]])), (78, 9))
		# huỷ HĐ → gói lô xuất bị huỷ, không còn tính → tồn về như cũ
		self.assertNotIn("error", self._goi("owner", "cancel_invoice", {"p_invoice_id": hd, "p_reason": "Khach doi y"}))
		lo = self._lo()
		self.assertEqual((flt(lo["L1-CU"]["qty_on_hand"]), flt(lo["L4-DAU"]["qty_on_hand"])), (30, 10))
		ton = self._goi("sales_a", "ton_ban_theo_hang")["data"]
		self.assertEqual((flt(ton[self.ma["P1"]]), flt(ton[self.ma["P2"]])), (80, 10))

	def test_hang_da_dat_chua_xuat(self):
		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == "xuat_thung_quy_doi")  # đơn 2 thùng × 24
		don = self._goi(t["buoc"][0]["nguoi"], "create_order_with_lines", {"p": doi_khoa(t["buoc"][0]["p"], self.ma)})["data"][0]["order_id"]
		dat = {x["product_id"]: flt(x["committed_base"]) for x in self._goi("sales_a", "committed_stock_by_product")["data"]}
		self.assertEqual(dat.get(self.ma["P1"]), 48)
		dat = {x["product_id"]: flt(x["committed_base"]) for x in self._goi("sales_a", "committed_stock_by_product",
			{"p_exclude_order": don})["data"]}
		self.assertNotIn(self.ma["P1"], dat)
		# xuất xong → đơn Hoàn thành, không còn là hàng đã đặt
		dong = self._dong_xuat(don, [[0, {}]])
		self.assertNotIn("error", self._goi("owner", "post_invoice", {"p": {"order_id": don, "lines": dong}}))
		dat = {x["product_id"]: flt(x["committed_base"]) for x in self._goi("sales_a", "committed_stock_by_product")["data"]}
		self.assertNotIn(self.ma["P1"], dat)

	_dong_xuat = XH.TestXuatHang._dong_xuat
	_don_da_xuat = XH.TestXuatHang._don_da_xuat

	def test_khong_phai_nv(self):
		"""Không phải NV của NPP (user_org_id() NULL): tồn bán rỗng, giá trị 0, hàng đã đặt báo NO_ORG."""
		frappe.local._npp_ngu_canh = None
		self.assertEqual(api.rpc(ten="ton_ban_theo_hang", tham_so={})["data"], {})
		self.assertEqual(api.rpc(ten="stock_value_summary", tham_so={})["data"], [{"inventory_value": 0, "batch_count": 0}])
		ket = api.rpc(ten="committed_stock_by_product", tham_so={})
		self.assertTrue(ket["error"]["message"].startswith("NO_ORG"), ket)
