"""NV nghỉ việc (mig 223) khớp nppsale: so_chung_tu_nhan_vien / cho_nhan_vien_nghi / giao_cong_no_npp chạy cùng chuỗi lệnh với
tools/vang_nhan_vien.py (hàm thật của nppsale ở Postgres tham chiếu) và so kết quả từng lệnh + trạng thái cuối.

	bench --site poc.local run-tests --module nppsale.tests.test_nhan_vien_nghi
"""
from __future__ import annotations

import json
import os

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.tests.test_tao_don import doi_khoa, dung_nen
from nppsale.tests.test_xuat_hang import VANG as VANG_XH
from nppsale.tests.test_xuat_hang import dung_kho

VANG = os.path.join(os.path.dirname(__file__), "du_lieu", "nhan_vien_nghi_mau.json")


class TestNhanVienNghi(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)
		with open(VANG_XH, encoding="utf-8") as f:
			cls.nen = json.load(f)["nen"]  # cùng bộ nền (người, khách, hàng, giá, lô) với bộ sinh

	def setUp(self):
		frappe.db.savepoint("npp_test")
		frappe.local._npp_cai_dat_ban = None
		frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 0)
		self.ma = dung_nen(self.nen)
		dung_kho(self.nen, self.ma)
		self.ten_cua = {v: k[2:] for k, v in self.ma.items() if k.startswith("u:")}
		self.ten_cua.update({self.ma[k]: k for k in ("C1", "C2")})

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")

	def _goi(self, nguoi: str, ten: str, ts: dict) -> dict:
		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None
		try:
			return api.rpc(ten=ten, tham_so=ts)
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	def _dung_nen_kich_ban(self):
		nen = self.vang["nen"]
		for k, nv, vai in nen["phan_cong"]:
			frappe.get_doc({"doctype": "NPP Phan Cong Khach", "khach": self.ma[k], "nhan_vien": self.ma["u:" + nv], "vai_tro": vai,
				"trang_thai": "active"}).insert(ignore_permissions=True)
		for nv, thu, k in nen["lich_tuyen"]:
			frappe.get_doc({"doctype": "NPP Lich Tuyen", "nhan_vien": self.ma["u:" + nv], "thu": thu, "khach": self.ma[k],
				"thu_tu_ghe": 1}).insert(ignore_permissions=True)
		for i, d in enumerate(nen["don"]):
			ket = self._goi(d["nguoi"], "create_order_with_lines", {"p": doi_khoa(d["p"], self.ma)})
			self.assertNotIn("error", ket, ket)
			don = ket["data"][0]["order_id"]
			dong = [{"order_line_id": r.name, "product_id": r.item_code, "unit_name": r.uom, "conversion_factor": r.conversion_factor,
				"quantity": r.qty, "unit_price": r.rate, "line_discount": r.npp_giam_dong, "vat_rate": r.npp_thue_suat}
				for r in frappe.get_all("Sales Order Item", filters={"parent": don}, fields=["name", "item_code", "uom", "conversion_factor",
					"qty", "rate", "npp_giam_dong", "npp_thue_suat"], order_by="idx asc")]
			ket = self._goi("owner", "post_invoice", {"p": {"order_id": don, "lines": dong}})
			self.assertNotIn("error", ket, ket)
			if i in nen["da_thu_du"]:  # đã thu đủ (phiếu thu chưa dựng — đặt thẳng trên dòng chiếu như nppsale đặt paid = amount)
				hd = ket["data"][0]["invoice_id"]
				so_tien = frappe.db.get_value("NPP Cong No", {"hoa_don": hd}, "so_tien")
				frappe.db.set_value("NPP Cong No", {"hoa_don": hd}, {"da_thu": so_tien, "con_no": 0, "trang_thai": "paid"})

	def _ts(self, ts: dict) -> dict:
		return {k: (self.ma[v[1:]] if isinstance(v, str) and v.startswith("@") else v) for k, v in ts.items()}

	@staticmethod
	def _chuan(tra):
		if isinstance(tra, dict) and "tong" in tra:
			tra = {"co_chung_tu": tra["tong"] > 0, "khach": tra["khach"], "lich_tuyen": tra["lich_tuyen"], "so_khoan_no": tra["so_khoan_no"],
				"tien_no": tra["tien_no"]}
		return {k: flt(v) if isinstance(v, int | float) and not isinstance(v, bool) else v for k, v in (tra or {}).items()}

	def _trang_thai_cuoi(self) -> dict:
		t = self.ten_cua
		nv = {}
		for k in ("sales_a", "sales_b"):
			x = frappe.db.get_value("NPP Nhan Vien", self.ma["u:" + k], ["dang_hoat_dong", "nghi_viec_luc", "nghi_viec_boi"], as_dict=True)
			nv[k] = {"dang_lam": bool(x.dang_hoat_dong), "da_nghi": x.nghi_viec_luc is not None, "nghi_boi": t.get(x.nghi_viec_boi)}
		khach = {self.ma["C1"], self.ma["C2"]}
		pc = sorted([t[r.khach], t[r.nhan_vien], r.vai_tro] for r in frappe.get_all("NPP Phan Cong Khach",
			filters={"khach": ("in", list(khach))}, fields=["khach", "nhan_vien", "vai_tro"]))
		lt = sorted([t[r.nhan_vien], r.thu, t[r.khach]] for r in frappe.get_all("NPP Lich Tuyen", filters={"khach": ("in", list(khach))},
			fields=["nhan_vien", "thu", "khach"]))
		no = sorted(({"hd": r.hoa_don, "nv": t.get(r.nhan_vien), "co_ve": r.ve_npp_luc is not None, "status": r.trang_thai,
			"con": flt(r.so_tien) - flt(r.da_thu)} for r in frappe.get_all("NPP Cong No", filters={"khach_hang": ("in", list(khach))},
			fields=["hoa_don", "nhan_vien", "ve_npp_luc", "trang_thai", "so_tien", "da_thu"])), key=lambda x: x["hd"])
		return {"nhan_vien": nv, "phan_cong": pc or None, "lich_tuyen": lt or None, "cong_no": no or None}

	def test_tung_lenh_nhu_nppsale(self):
		self._dung_nen_kich_ban()
		sai = []
		for i, (b, m) in enumerate(zip(self.vang["buoc"], self.vang["mong"]["buoc"], strict=True)):
			ket = self._goi(b["nguoi"], b["ham"], self._ts(b["tham_so"]))
			nhan = f"lệnh {i + 1} {b['nguoi']} {b['ham']}"
			if m["ok"]:
				if "error" in ket:
					sai.append(f"{nhan}: nppsale ghi được — Frappe báo {ket['error']}")
				elif self._chuan(ket["data"]) != self._chuan(m["tra"]):
					sai.append(f"{nhan}: {self._chuan(ket['data'])} ≠ nppsale {self._chuan(m['tra'])}")
			elif "error" not in ket:
				sai.append(f"{nhan}: nppsale báo {m['loi']} — Frappe lại ghi được ({ket.get('data')})")
			elif (ket["error"]["code"], ket["error"]["message"]) != (m["ma_loi"], m["loi"]):
				sai.append(f"{nhan}: lỗi {ket['error']['code']} {ket['error']['message']} ≠ nppsale {m['ma_loi']} {m['loi']}")
		cuoi = self._trang_thai_cuoi()
		mong = json.loads(json.dumps(self.vang["mong"]["ct"]))
		for x in mong.get("cong_no") or []:
			x["con"] = flt(x["con"])
		mong["lich_tuyen"] = [list(x) for x in mong.get("lich_tuyen") or []] or None
		for k in ("nhan_vien", "phan_cong", "lich_tuyen", "cong_no"):
			if cuoi[k] != mong.get(k):
				sai.append(f"trạng thái cuối {k}: {cuoi[k]} ≠ nppsale {mong.get(k)}")
		self.assertEqual(sai, [], "\n".join(sai))

	def test_khong_cho_chu_npp_nghi(self):
		"""NGHI_CHU_NPP (bộ vàng chỉ có một chủ NPP — chủ tự cho mình nghỉ là TU_NGHI): một NV khác mang vai chủ → không cho nghỉ."""
		nv = self.ma["u:manager_nang10"]
		frappe.db.set_value("NPP Nhan Vien", nv, "vai", "owner")
		ket = self._goi("owner", "cho_nhan_vien_nghi", {"p_user_id": nv})
		self.assertEqual(ket["error"]["message"], "NGHI_CHU_NPP: không cho Chủ NPP nghỉ việc")
		self.assertIsNone(frappe.db.get_value("NPP Nhan Vien", nv, "nghi_viec_luc"))

	def test_xoa_nv_co_chung_tu_bi_chan(self):
		"""Màn xoá NV hỏi cùng bộ đếm: đã có chứng từ → 409 CO_CHUNG_TU (không xoá), như route xoá của nppsale (mig 223)."""
		from nppsale.api.nguoi_dung import xoa

		self._dung_nen_kich_ban()
		frappe.set_user(self.ma["u:owner"])
		try:
			ma, kq = xoa(frappe._dict(tham={"id": self.ma["u:sales_a"]}))
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(ma, 409)
		self.assertEqual(kq["code"], "CO_CHUNG_TU")
		self.assertTrue(kq["chung_tu"]["tong"] > 0)
		self.assertTrue(frappe.db.exists("NPP Nhan Vien", self.ma["u:sales_a"]))
