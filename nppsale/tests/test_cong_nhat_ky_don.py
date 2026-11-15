"""Cổng: order_status_history / order_activity_log (NPP Nhat Ky Don) — đúng câu màn chi tiết đơn của nppsale gửi
(orders/[id]/page.tsx), lồng người đổi / người làm, RLS: lịch sử theo đơn thấy được, nhật ký dòng cho mọi NV của NPP.

	bench --site poc.local run-tests --module nppsale.tests.test_cong_nhat_ky_don
"""
from __future__ import annotations

import json

import frappe
from frappe.tests import IntegrationTestCase

from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.truy_van import doc
from nppsale.tests import (
	test_xuat_hang as XH,  # nhập module, không nhập lớp — bộ tìm bài sẽ chạy lại cả lớp nếu nó nằm ở đây
)
from nppsale.tests.test_tao_don import dung_nen


class TestCongNhatKyDon(IntegrationTestCase):
	# dùng lại cách dựng đơn + HĐ của bài Xuất hàng (hàm thường — gắn vào lớp này, không kế thừa các bài của lớp ấy)
	_goi = XH.TestXuatHang._goi
	_dong_xuat = XH.TestXuatHang._dong_xuat
	_don_da_xuat = XH.TestXuatHang._don_da_xuat

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

	def _nc(self, nguoi: str) -> NguCanh:
		u = self.ma["u:" + nguoi]
		return NguCanh(user=u, vai=frappe.db.get_value("NPP Nhan Vien", u, "vai"))

	def test_lich_su_va_nhat_ky_cua_don(self):
		don, hd = self._don_da_xuat()  # đơn của sales_a + HĐ do chủ xuất
		huy = self._goi("owner", "cancel_invoice", {"p_invoice_id": hd, "p_reason": "Khach doi y"})
		self.assertNotIn("error", huy, huy)
		cau_ls = {"bang": "order_status_history", "select": "id, order_id, from_status, to_status, changed_by, changed_at, notes, "
			"changer:users!order_status_history_changed_by_fkey(full_name)", "loc": [{"op": "eq", "cot": "order_id", "gt": don}],
			"thu_tu": [{"cot": "changed_at", "tang": False}]}
		ls = doc(cau_ls, self._nc("owner"))["data"]
		self.assertEqual(sorted([x["from_status"], x["to_status"]] for x in ls),
			sorted([["draft", "submitted"], ["submitted", "completed"], ["completed", "submitted"], ["submitted", "cancelled"]]))
		self.assertEqual({x["order_id"] for x in ls}, {don})
		nguoi_doi = {(x["to_status"], (x["changer"] or {}).get("full_name")) for x in ls}
		self.assertIn(("cancelled", "owner"), nguoi_doi)  # huỷ do chủ NPP bấm
		# RLS: NV đứng tên đơn thấy; NV khác không phụ trách khách thì không (sales_order_select)
		self.assertEqual(len(doc(cau_ls, self._nc("sales_a"))["data"]), 4)
		self.assertEqual(doc(cau_ls, self._nc("sales_b"))["data"], [])
		cau_nk = {"bang": "order_activity_log", "select": "id, order_line_id, action, workflow_stage, changes, created_at, actor_id, "
			"actor:users!actor_id(full_name)", "loc": [{"op": "eq", "cot": "order_id", "gt": don}],
			"thu_tu": [{"cot": "created_at", "tang": False}], "limit": 100}
		nk = doc(cau_nk, self._nc("sales_b"))["data"]  # mọi NV của NPP (org_id = user_org_id())
		hanh_dong = [x["action"] for x in nk]
		self.assertTrue({"invoice_posted", "invoice_cancelled", "cancel_after_complete"} <= set(hanh_dong), hanh_dong)
		self.assertTrue(all(hanh_dong), hanh_dong)  # chỉ dòng nhật ký hành động — dòng đổi trạng thái thuộc order_status_history
		dang = next(x for x in nk if x["action"] == "invoice_cancelled")
		self.assertEqual(dang["changes"]["invoice_code"], hd)
		self.assertEqual((dang["actor"] or {}).get("full_name"), "owner")
		# chỉ đọc: chèn thẳng bị từ chối như RLS của nppsale
		from nppsale.cong.ghi import ghi
		from nppsale.cong.sql import LoiCong

		with self.assertRaises(LoiCong):
			ghi({"bang": "order_activity_log", "hanh_dong": "insert", "gia_tri": [{"order_id": don, "action": "add_line"}]}, self._nc("owner"))
