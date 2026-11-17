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

	def test_xoa_nhap_khong_lui_day_so(self):
		"""P4 đuôi (như F2 của phiếu kho nháp): xoá qua cổng phiếu trả NHÁP và đơn NHÁP (kèm phiếu trả nháp của đơn) mang số CUỐI của dãy `PT-` / `DH-`
		KHÔNG lùi dãy — phiếu / đơn lập sau không nhận lại id vừa xoá (lõi `revert_series_if_last`; nppsale id uuid — `nppsale.day_so`)."""
		import uuid

		from nppsale.tests.test_tao_don import doi_khoa

		def so_dem(ten: str) -> int:
			return int(frappe.db.sql("SELECT `current` FROM `tabSeries` WHERE `name` = %s", ten.rsplit("-", 1)[0] + "-")[0][0])

		def xoa(nguoi: str, bang: str, ten: str) -> list:
			return self._ghi(nguoi, {"bang": bang, "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "id", "gt": ten}], "select": "id"})["data"]

		k = self.ma["C1"]

		def pt_moi() -> str:
			return self._ghi("sales_a", {"bang": "returns", "hanh_dong": "insert", "gia_tri": {"customer_id": k, "status": "draft"},
				"select": "id"})["data"][0]["id"]

		a = pt_moi()
		dem = so_dem(a)
		self.assertEqual(dem, int(a.rsplit("-", 1)[1]))  # a mang số CUỐI của dãy
		self.assertEqual(xoa("sales_a", "returns", a), [{"id": a}])
		self.assertFalse(frappe.db.exists("NPP Phieu Tra", a))
		self.assertEqual(so_dem(a), dem)
		self.assertNotEqual(pt_moi(), a)
		# đơn nháp kèm phiếu trả của đơn: xoá đơn (cổng sales_orders → sua_don.xoa_don) xoá theo phiếu trả nháp — cả hai dãy giữ số
		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == "xuat_du_mot_lo")

		def don_moi() -> tuple:
			p = doi_khoa(t["buoc"][0]["p"], self.ma)
			p["client_request_id"] = str(uuid.uuid4())
			p["order"]["status"] = "draft"
			p["returns"] = {"reason": "damaged"}
			p["return_lines"] = [{"product_id": self.ma["P1"], "unit_name": "Lon", "quantity": 1, "unit_price": 9500, "vat_rate": 0.08}]
			p["order"]["total"] = p["order"]["total"] - 10260
			ket = self._goi("sales_a", "create_order_with_lines", {"p": p})
			self.assertNotIn("error", ket, ket)
			don = ket["data"][0]["order_id"]
			return don, frappe.db.get_value("NPP Phieu Tra", {"don_hang": don}, "name")

		d1, p1 = don_moi()
		self.assertTrue(p1)
		dem_dh, dem_pt = so_dem(d1), so_dem(p1)
		self.assertEqual((dem_dh, dem_pt), (int(d1.rsplit("-", 1)[1]), int(p1.rsplit("-", 1)[1])))
		self.assertEqual(xoa("sales_a", "sales_orders", d1), [{"id": d1}])  # đơn nháp chỉ người đứng tên thấy / xoá (RLS sales_orders)
		self.assertFalse(frappe.db.exists("Sales Order", d1) or frappe.db.exists("NPP Phieu Tra", p1))
		self.assertEqual((so_dem(d1), so_dem(p1)), (dem_dh, dem_pt))
		d2, p2 = don_moi()
		self.assertNotEqual(d2, d1)
		self.assertNotEqual(p2, p1)

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

	def test_doc_loc_dem_nhu_giao_dien(self):
		"""Đặc tả §5.3 — lời đọc thật của màn Trả hàng: gom nhóm `reason, count()` (lý do NULL là một nhóm), ô tìm `tim_kd` (PT-0001 → pt1),
		trạng thái ngoài miền Select → rỗng không lỗi, `in` trạng thái, `is.null`, RLS NVBH, dòng phiếu theo thứ tự nhập."""
		k = self.ma["C1"]
		for nguoi, ly_do in (("owner", "damaged"), ("owner", None), ("sales_a", "expired")):
			ket = self._goi(nguoi, "save_pos_return", {"p": {"customer_id": k, "reason": ly_do, "lines": [
				{"product_id": self.ma["P1"], "unit_name": "Lon", "quantity": 1, "unit_price": 9500, "vat_rate": 0.08},
				{"product_id": self.ma["P2"], "unit_name": "Chai", "quantity": 1, "unit_price": 5000, "vat_rate": 0.1}]}})
			self.assertNotIn("error", ket, ket)
		chu = self._nc("owner")
		nhom = {x["reason"]: x["count"] for x in doc({"bang": "returns", "select": "reason, count()"}, chu)["data"]}
		self.assertEqual(nhom, {"damaged": 1, None: 1, "expired": 1})
		ten = sorted(frappe.get_all("NPP Phieu Tra", pluck="name"))
		dau = ten[0]
		so = str(int(dau.split("-")[1]))
		tim = doc({"bang": "returns", "select": "id", "loc": [{"op": "or", "bieu_thuc": f'return_code.ilike.*pt{so}*,tim_kd.ilike.*pt{so}*'}]},
			chu)["data"]
		self.assertIn(dau, [x["id"] for x in tim])
		self.assertEqual(doc({"bang": "returns", "select": "id", "loc": [{"op": "eq", "cot": "status", "gt": "approved"}]}, chu)["data"], [])
		self.assertEqual(len(doc({"bang": "returns", "select": "id", "loc": [{"op": "in", "cot": "status", "gt": ["submitted", "draft"]}]},
			chu)["data"]), 3)
		self.assertEqual(doc({"bang": "returns", "select": "id", "loc": [{"op": "is", "cot": "sales_user_id", "gt": None}]}, chu)["data"], [])
		# NVBH chỉ thấy phiếu mình lập / đứng tên
		self.assertEqual(len(doc({"bang": "returns", "select": "id"}, self._nc("sales_a"))["data"]), 1)
		self.assertEqual(doc({"bang": "returns", "select": "id"}, self._nc("sales_b"))["data"], [])
		# dòng không `order` → thứ tự nhập
		r = doc({"bang": "return_lines", "select": "product_id", "loc": [{"op": "eq", "cot": "return_id", "gt": dau}]}, chu)["data"]
		self.assertEqual([x["product_id"] for x in r], [self.ma["P1"], self.ma["P2"]])

	def test_ghi_nhan_lai_amend_to_ghi_co(self):
		"""Ghi nhận lại phiếu tự lập đã nhập kho (save_pos_return complete trên phiếu cũ): số PT giữ, tờ ghi có cũ huỷ, tờ mới amend nó
		(HDT-x-1 — bàn bạc 6.11); tổng tờ = đúng tiền trả kể cả đơn giá lẻ (⚠ Q2: 3 × 3.333,5 → 10.001)."""
		k = self.ma["C2"]
		dong = [{"product_id": self.ma["P2"], "unit_name": "Chai", "quantity": 3, "unit_price": 3333.5, "vat_rate": 0}]
		ket = self._goi("owner", "save_pos_return", {"p": {"customer_id": k, "complete": True, "zone": "sale", "lines": dong}})
		self.assertNotIn("error", ket, ket)
		pt = ket["data"]
		cu = frappe.db.get_value("NPP Phieu Tra", pt, "to_ghi_co")
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", cu, "grand_total")), -10001)
		ket = self._goi("owner", "save_pos_return", {"p": {"return_id": pt, "customer_id": k, "complete": True, "zone": "sale",
			"lines": [{**dong[0], "quantity": 4}]}})
		self.assertNotIn("error", ket, ket)
		self.assertEqual(ket["data"], pt)
		moi = frappe.db.get_value("NPP Phieu Tra", pt, "to_ghi_co")
		self.assertEqual((moi, frappe.db.get_value("Sales Invoice", moi, "amended_from")), (f"{cu}-1", cu))
		self.assertEqual(frappe.db.get_value("Sales Invoice", cu, "docstatus"), 2)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", moi, "grand_total")), -13334)

	def _han_no(self, pt: str):
		ds = doc({"bang": "receivables", "select": "due_date, amount", "loc": [{"op": "eq", "cot": "return_id", "gt": pt}]},
			self._nc("owner"))["data"]
		self.assertEqual(len(ds), 1, ds)
		return ds[0]["due_date"]

	def test_han_no_am_theo_ngay_phieu(self):
		"""🔧 P3-HAN-NO-AM (bộ vàng P6, soát SOAT-VBC-02): hạn dòng nợ ÂM phiếu tự lập độc lập = ngày PHIẾU lúc Hoàn thành
		(`_cong_no_phieu_tra` mig 191: COALESCE(return_date, ngày hoàn thành)), không phải ngày bấm (posting_date tờ ghi có). Đổi ngày phiếu
		sau đó không dời hạn kể cả khi dòng được chiếu lại (ĐT-PT G32 / Q10); Ghi nhận lại chụp ngày phiếu mới; ngày phiếu tương lai giữ nguyên."""
		from frappe.utils import add_days, getdate, nowdate

		from nppsale.su_kien.cong_no import chieu_phieu_tra

		hn = getdate(nowdate())
		k = self.ma["C1"]
		dong = [{"product_id": self.ma["P1"], "unit_name": "Lon", "quantity": 2, "unit_price": 9500, "vat_rate": 0.08}]
		ket = self._goi("owner", "save_pos_return", {"p": {"customer_id": k, "reason": "damaged", "zone": "sale", "complete": True,
			"return_date": str(add_days(hn, -2)), "lines": dong}})
		self.assertNotIn("error", ket, ket)
		pt = ket["data"]
		to = frappe.db.get_value("NPP Phieu Tra", pt, "to_ghi_co")
		self.assertEqual(str(frappe.db.get_value("Sales Invoice", to, "posting_date")), str(hn))  # tờ ghi sổ ngày bấm
		self.assertEqual(self._han_no(pt), str(add_days(hn, -2)))  # hạn = ngày phiếu (Frappe cũ: ngày bấm)
		# đổi ngày phiếu đã Hoàn thành (ghi thẳng — chỉ dời mốc ghi có / ngày trừ doanh số) → hạn đứng yên, kể cả khi chiếu lại dòng
		self.assertEqual(self._ghi("owner", {"bang": "returns", "hanh_dong": "update", "gia_tri": {"return_date": str(add_days(hn, -5))},
			"loc": [{"op": "eq", "cot": "id", "gt": pt}], "select": "id, return_date"})["data"], [{"id": pt, "return_date": str(add_days(hn, -5))}])
		chieu_phieu_tra(pt)
		self.assertEqual(self._han_no(pt), str(add_days(hn, -2)))
		# Ghi nhận lại (huỷ + hoàn thành lại — complete_return chạy lại `_cong_no_phieu_tra`) → chụp ngày phiếu mới
		ket = self._goi("owner", "save_pos_return", {"p": {"return_id": pt, "customer_id": k, "reason": "damaged", "zone": "sale",
			"complete": True, "return_date": str(add_days(hn, -1)), "lines": [{**dong[0], "quantity": 3}]}})
		self.assertNotIn("error", ket, ket)
		self.assertEqual(frappe.db.get_value("Sales Invoice", frappe.db.get_value("NPP Phieu Tra", pt, "to_ghi_co"), "amended_from"), to)
		self.assertEqual(self._han_no(pt), str(add_days(hn, -1)))
		# ngày phiếu sau hôm nay (Sổ BC PT-0006: ngày 02/12 bấm 16/11 → hạn 02/12)
		ket = self._goi("owner", "save_pos_return", {"p": {"customer_id": k, "zone": "sale", "complete": True,
			"return_date": str(add_days(hn, 16)), "lines": dong}})
		self.assertNotIn("error", ket, ket)
		self.assertEqual(self._han_no(ket["data"]), str(add_days(hn, 16)))

	def test_kham_so_bat_lech(self):
		"""nppsale.kham_so.quet_phieu_tra: sổ đúng → không dòng nào; huỷ tay tờ ghi có của phiếu tự sinh (sổ lệch) → báo nhóm 1 (tờ ghi có
		không khớp phiếu) và nhóm 6 (công nợ HĐ lệch công thức)."""
		import uuid

		from nppsale.kham_so import quet_phieu_tra
		from nppsale.tests.test_tao_don import doi_khoa

		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == "xuat_du_mot_lo")
		p = doi_khoa(t["buoc"][0]["p"], self.ma)
		p["client_request_id"] = str(uuid.uuid4())
		p["returns"] = {"reason": "damaged"}
		p["return_lines"] = [{"product_id": self.ma["P1"], "unit_name": "Lon", "quantity": 1, "unit_price": 9500, "vat_rate": 0.08}]
		p["order"]["total"] = p["order"]["total"] - 10260
		don = self._goi(t["buoc"][0]["nguoi"], "create_order_with_lines", {"p": p})["data"][0]["order_id"]
		dd = frappe.get_all("Sales Order Item", filters={"parent": don}, fields=["name", "item_code", "uom", "conversion_factor", "qty", "rate",
			"npp_giam_dong", "npp_thue_suat"], order_by="idx asc")
		ket = self._goi("owner", "post_invoice", {"p": {"order_id": don, "lines": [{"order_line_id": r.name, "product_id": r.item_code,
			"unit_name": r.uom, "conversion_factor": r.conversion_factor, "quantity": r.qty, "unit_price": r.rate, "line_discount": r.npp_giam_dong,
			"vat_rate": r.npp_thue_suat, "is_exchange": False} for r in dd]}})
		self.assertNotIn("error", ket, ket)
		hd = ket["data"][0]["invoice_id"]
		self.assertEqual(quet_phieu_tra(), [])
		pt = frappe.db.get_value("NPP Phieu Tra", {"hoa_don": hd}, ["name", "to_ghi_co"], as_dict=True)
		cn = frappe.get_doc("Sales Invoice", pt.to_ghi_co)
		cn.flags.ignore_permissions = True
		cn.cancel()
		nhom = sorted({(d["nhom"], d["chung_tu"]) for d in quet_phieu_tra()})
		self.assertEqual(nhom, [(1, pt.name), (6, hd)])

