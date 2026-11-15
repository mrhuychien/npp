"""Soạn hàng (mig 224 danh_dau_soan_hang, mig 225 lượt soạn): RPC + bảng cổng luot_soan — luật chép từ hàm Postgres đang chạy của
nppsale (_luot_soan_quyen, _luot_soan_hoa_don, tao / cap_nhat / hoan_tat / huy_luot_soan); ngữ nghĩa jsonb_strip_nulls, bỏ trùng giữ
thứ tự, lpad đã đối chiếu trên Postgres tham chiếu.

	bench --site poc.local run-tests --module nppsale.tests.test_soan_hang
"""
from __future__ import annotations

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, nowdate

from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.truy_van import doc
from nppsale.tests import test_xuat_hang as XH
from nppsale.tests.test_tao_don import dung_nen


class TestSoanHang(IntegrationTestCase):
	_goi = XH.TestXuatHang._goi
	_dong_xuat = XH.TestXuatHang._dong_xuat

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
		frappe.db.sql("DELETE FROM `tabNPP Luot Soan`")  # đếm số lượt trong ngày từ 0 (trong giao dịch bài thử — lui khi xong)
		frappe.db.sql("DELETE FROM `tabNPP Luot Soan Hoa Don`")

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")

	def _hd(self) -> str:
		"""Một HĐ đã ghi sổ mới (tình huống vàng `xuat_du_mot_lo`, mỗi lần một client_request_id — tạo đơn lặp-an-toàn theo mã ấy)."""
		import uuid

		from nppsale.tests.test_tao_don import doi_khoa

		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == "xuat_du_mot_lo")
		tao, xuat = t["buoc"][0], t["buoc"][1]
		p = {**doi_khoa(tao["p"], self.ma), "client_request_id": str(uuid.uuid4())}
		don = self._goi(tao["nguoi"], "create_order_with_lines", {"p": p})["data"][0]["order_id"]
		px = {**XH.ngay_tuong_doi(xuat["p"]), "order_id": don, "lines": self._dong_xuat(don, xuat["dong"])}
		return self._goi(xuat["nguoi"], "post_invoice", {"p": px})["data"][0]["invoice_id"]

	def _nc(self, nguoi: str) -> NguCanh:
		u = self.ma["u:" + nguoi]
		return NguCanh(user=u, vai=frappe.db.get_value("NPP Nhan Vien", u, "vai"))

	def _loi(self, ket: dict) -> str:
		self.assertIn("error", ket, ket)
		return ket["error"]["message"]

	def _luot(self, nguoi: str, id_: str) -> dict | None:
		ds = doc({"bang": "luot_soan", "select": "id, ma, invoice_ids, trang_thai, tien_do, created_at, created_by, updated_at, xong_luc, xong_boi",
			"loc": [{"op": "eq", "cot": "id", "gt": id_}]}, self._nc(nguoi))["data"]
		return ds[0] if ds else None

	def test_luot_soan_tu_lap_toi_hoan_tat(self):
		hd1, hd2 = self._hd(), self._hd()
		# quyền: NVBH không soạn; NV đã nghỉ (user_org_id() NULL) cũng không
		for nguoi in ("sales_a", "sales_nghi"):
			self.assertEqual(self._loi(self._goi(nguoi, "tao_luot_soan", {"p_invoice_ids": [hd1]})),
				"KHONG_DU_QUYEN: chỉ chủ NPP, quản lý, thủ kho, kế toán soạn hàng")
		# chưa chọn HĐ; HĐ không hợp lệ; quá 26 rổ (kiểm trước HĐ hợp lệ)
		self.assertEqual(self._loi(self._goi("warehouse", "tao_luot_soan", {"p_invoice_ids": []})), "CHUA_CHON_HOA_DON")
		self.assertEqual(self._loi(self._goi("warehouse", "tao_luot_soan", {})), "CHUA_CHON_HOA_DON")
		self.assertEqual(self._loi(self._goi("warehouse", "tao_luot_soan", {"p_invoice_ids": [hd1, "HD-KHONG-CO"]})),
			"HOA_DON_KHONG_HOP_LE: chỉ soạn hoá đơn đã ghi sổ của NPP")
		self.assertEqual(self._loi(self._goi("warehouse", "tao_luot_soan", {"p_invoice_ids": [f"X{i}" for i in range(27)]})),
			"QUA_NHIEU_RO: một lượt soạn tối đa 26 hoá đơn (rổ A–Z)")
		# lập: bỏ trùng giữ thứ tự (rổ A = hd2), mã SH-dd/mm-01 rồi -02
		id1 = self._goi("warehouse", "tao_luot_soan", {"p_invoice_ids": [hd2, hd1, hd2]})["data"]
		hom_nay = getdate(nowdate()).strftime("%d/%m")
		l1 = self._luot("owner", id1)
		self.assertEqual((l1["ma"], l1["invoice_ids"], l1["trang_thai"], l1["tien_do"], l1["created_by"]),
			(f"SH-{hom_nay}-01", [hd2, hd1], "dang_soan", {"chia": {}, "nhat": {}}, self.ma["u:warehouse"]))
		self.assertEqual([r.ro for r in frappe.get_doc("NPP Luot Soan", id1).hoa_don], ["A", "B"])
		id2 = self._goi("accountant", "tao_luot_soan", {"p_invoice_ids": [hd1]})["data"]
		self.assertEqual(self._luot("owner", id2)["ma"], f"SH-{hom_nay}-02")
		# RLS đọc: NVBH không thấy lượt nào
		self.assertIsNone(self._luot("sales_a", id1))
		# gộp tiến độ từng khoá (null = xoá khoá), hai máy bấm hai mặt hàng không đè nhau
		p1, p2 = self.ma["P1"], self.ma["P2"]
		r = self._goi("warehouse", "cap_nhat_luot_soan", {"p_id": id1, "p_nhat": {p1: 2}})["data"]
		self.assertEqual(r["tien_do"], {"chia": {}, "nhat": {p1: 2}})
		self.assertEqual((r["id"], r["ma"], r["invoice_ids"]), (id1, f"SH-{hom_nay}-01", [hd2, hd1]))  # trả cả dòng lượt
		r = self._goi("owner", "cap_nhat_luot_soan", {"p_id": id1, "p_nhat": {p2: 1}, "p_chia": {f"{p1}|{hd1}": True, f"{p1}|{hd2}": True}})["data"]
		self.assertEqual(r["tien_do"], {"nhat": {p1: 2, p2: 1}, "chia": {f"{p1}|{hd1}": True, f"{p1}|{hd2}": True}})
		r = self._goi("warehouse", "cap_nhat_luot_soan", {"p_id": id1, "p_nhat": {p1: None, p2: {"a": None, "b": 3}},
			"p_chia": {f"{p1}|{hd2}": None}})["data"]
		self.assertEqual(r["tien_do"], {"nhat": {p2: {"b": 3}}, "chia": {f"{p1}|{hd1}": True}})  # jsonb_strip_nulls đệ quy
		r = self._goi("warehouse", "cap_nhat_luot_soan", {"p_id": id1, "p_nhat": [1, 2]})["data"]  # không phải object → bỏ qua
		self.assertEqual(r["tien_do"]["nhat"], {p2: {"b": 3}})
		# đổi danh sách HĐ (rỗng được — cập nhật không đòi có HĐ)
		r = self._goi("warehouse", "cap_nhat_luot_soan", {"p_id": id1, "p_invoice_ids": [hd1, hd2]})["data"]
		self.assertEqual(r["invoice_ids"], [hd1, hd2])
		self.assertEqual(self._goi("warehouse", "cap_nhat_luot_soan", {"p_id": id2, "p_invoice_ids": []})["data"]["invoice_ids"], [])
		self.assertEqual(self._loi(self._goi("warehouse", "cap_nhat_luot_soan", {"p_id": "khong-co"})), "KHONG_TIM_THAY_LUOT")
		# HĐ đã đánh dấu tay trước → hoàn tất chỉ đếm HĐ chưa có dấu, giữ người / giờ cũ
		self.assertEqual(self._goi("owner", "danh_dau_soan_hang", {"p_ids": [hd2]})["data"], 1)
		dau_cu = frappe.db.get_value("Sales Invoice", hd2, ["npp_soan_luc", "npp_soan_boi"])
		sua_cu = frappe.db.get_value("Sales Invoice", hd1, "modified")
		self.assertEqual(self._goi("warehouse", "hoan_tat_luot_soan", {"p_id": id1})["data"], 1)
		self.assertEqual(frappe.db.get_value("Sales Invoice", hd2, ["npp_soan_luc", "npp_soan_boi"]), dau_cu)
		self.assertEqual(frappe.db.get_value("Sales Invoice", hd1, "npp_soan_boi"), self.ma["u:warehouse"])
		self.assertIsNotNone(frappe.db.get_value("Sales Invoice", hd1, "npp_soan_luc"))
		self.assertEqual(frappe.db.get_value("Sales Invoice", hd1, "modified"), sua_cu)  # dấu soạn không đổi "sửa lúc" của HĐ
		l1 = self._luot("owner", id1)
		self.assertEqual((l1["trang_thai"], l1["xong_boi"]), ("xong", self.ma["u:warehouse"]))
		self.assertIsNotNone(l1["xong_luc"])
		hd = doc({"bang": "sales_invoices", "select": "id, soan_luc, soan_boi", "loc": [{"op": "eq", "cot": "id", "gt": hd1}]},
			self._nc("owner"))["data"][0]
		self.assertEqual(hd["soan_boi"], self.ma["u:warehouse"])
		# lượt đã đóng: không cập nhật / hoàn tất / huỷ nữa
		for ten, ts in (("cap_nhat_luot_soan", {"p_id": id1, "p_nhat": {p1: 1}}), ("hoan_tat_luot_soan", {"p_id": id1})):
			self.assertEqual(self._loi(self._goi("warehouse", ten, ts)), "LUOT_DA_DONG: lượt soạn đã hoàn tất / huỷ")
		self.assertEqual(self._loi(self._goi("warehouse", "huy_luot_soan", {"p_id": id1})), "KHONG_TIM_THAY_LUOT: không có lượt đang soạn này")
		# huỷ lượt đang soạn
		self.assertNotIn("error", self._goi("manager", "huy_luot_soan", {"p_id": id2}))
		self.assertEqual(self._luot("owner", id2)["trang_thai"], "huy")
		self.assertEqual(self._loi(self._goi("sales_a", "huy_luot_soan", {"p_id": id2})),
			"KHONG_DU_QUYEN: chỉ chủ NPP, quản lý, thủ kho, kế toán soạn hàng")
		# lượt huỷ vẫn được đếm vào số trong ngày
		id3 = self._goi("warehouse", "tao_luot_soan", {"p_invoice_ids": [hd1]})["data"]
		self.assertEqual(self._luot("owner", id3)["ma"], f"SH-{hom_nay}-03")

	def test_danh_dau_soan_hang(self):
		hd1, hd2 = self._hd(), self._hd()
		self.assertEqual(self._loi(self._goi("sales_a", "danh_dau_soan_hang", {"p_ids": [hd1]})),
			"KHONG_DU_QUYEN: chỉ chủ NPP, quản lý, thủ kho, kế toán đánh dấu soạn hàng")
		self.assertEqual(self._goi("accountant", "danh_dau_soan_hang", {"p_ids": [hd1, hd1, "HD-KHONG-CO"]})["data"], 1)
		self.assertEqual(self._goi("owner", "danh_dau_soan_hang", {"p_ids": [hd1, hd2], "p_da": True})["data"], 1)  # hd1 đã có dấu
		self.assertEqual(frappe.db.get_value("Sales Invoice", hd1, "npp_soan_boi"), self.ma["u:accountant"])
		self.assertEqual(self._goi("owner", "danh_dau_soan_hang", {"p_ids": [hd1], "p_da": None})["data"], 0)
		self.assertEqual(self._goi("owner", "danh_dau_soan_hang", {"p_ids": [hd1, hd2], "p_da": False})["data"], 2)
		self.assertEqual(frappe.db.get_value("Sales Invoice", hd1, ["npp_soan_luc", "npp_soan_boi"]), (None, None))
		self.assertEqual(self._goi("owner", "danh_dau_soan_hang", {"p_ids": [hd1], "p_da": False})["data"], 0)
		self.assertEqual(self._goi("owner", "danh_dau_soan_hang", {})["data"], 0)
		# HĐ đã huỷ không đánh dấu được (chỉ HĐ đã ghi sổ)
		self.assertNotIn("error", self._goi("owner", "cancel_invoice", {"p_invoice_id": hd2, "p_reason": "Khach doi y"}))
		self.assertEqual(self._goi("owner", "danh_dau_soan_hang", {"p_ids": [hd2]})["data"], 0)
		self.assertEqual(self._loi(self._goi("warehouse", "tao_luot_soan", {"p_invoice_ids": [hd2]})),
			"HOA_DON_KHONG_HOP_LE: chỉ soạn hoá đơn đã ghi sổ của NPP")

	def test_bang_luot_soan_chi_doc(self):
		from nppsale.cong.ghi import ghi
		from nppsale.cong.sql import LoiCong

		hd = self._hd()
		id1 = self._goi("warehouse", "tao_luot_soan", {"p_invoice_ids": [hd]})["data"]
		# đúng câu màn soạn hàng đọc (use-luot-soan.ts): lượt đang soạn, mới nhất, 30 dòng
		ds = doc({"bang": "luot_soan", "select": "id, ma, invoice_ids, trang_thai, tien_do, created_at, created_by, updated_at",
			"loc": [{"op": "eq", "cot": "trang_thai", "gt": "dang_soan"}], "thu_tu": [{"cot": "created_at", "tang": False}], "limit": 30},
			self._nc("manager"))["data"]
		self.assertEqual([x["id"] for x in ds], [id1])
		for hd_ in ("insert", "update", "delete"):
			with self.assertRaises(LoiCong):
				ghi({"bang": "luot_soan", "hanh_dong": hd_, "gia_tri": {"trang_thai": "xong"}, "loc": [{"op": "eq", "cot": "id", "gt": id1}]},
					self._nc("owner"))
