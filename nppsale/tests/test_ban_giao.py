"""Bàn giao khách (ban_giao_khach, mig 246) khớp nppsale: cùng nền + cùng chuỗi lệnh với tools/vang_ban_giao.py (hàm thật của nppsale ở
Postgres tham chiếu); so kết quả từng lệnh (xem trước: danh sách khách + tổng; làm thật: kết quả) và trạng thái cuối (phân công, lịch
tuyến, người giữ nợ + dấu bàn giao, nhật ký, thông báo).

	bench --site poc.local run-tests --module nppsale.tests.test_ban_giao
"""
from __future__ import annotations

import json
import os

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, now_datetime, nowdate

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.tests.test_tao_don import doi_khoa, dung_nen
from nppsale.tests.test_xuat_hang import VANG as VANG_XH
from nppsale.tests.test_xuat_hang import dung_kho, ngay_tuong_doi
from nppsale.thiet_lap.ban_hang import cai_dat_ban

VANG = os.path.join(os.path.dirname(__file__), "du_lieu", "ban_giao_mau.json")


def _so(x):
	"""Số → float (nppsale trả numeric / int, Frappe trả float); đi sâu vào dict / list."""
	if isinstance(x, bool) or x is None:
		return x
	if isinstance(x, int | float):
		return float(x)
	if isinstance(x, dict):
		return {k: _so(v) for k, v in x.items()}
	if isinstance(x, list):
		return [_so(v) for v in x]
	return x


class TestBanGiao(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)
		with open(VANG_XH, encoding="utf-8") as f:
			cls.nen = json.load(f)["nen"]

	def setUp(self):
		frappe.db.savepoint("npp_test")
		frappe.local._npp_cai_dat_ban = None
		frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 0)
		self.ma = dung_nen(self.nen)
		dung_kho(self.nen, self.ma)

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

	# ------------------------------------------------------------------------------------------------ nền
	def _dung_nen_ban_giao(self):
		nen = self.vang["nen"]
		cong_ty = cai_dat_ban().cong_ty
		nhom_ncc = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
		for k, (ten, sp) in nen["ncc"].items():
			self.ma[k] = frappe.get_doc({"doctype": "Supplier", "supplier_name": ten, "supplier_group": nhom_ncc}).insert(
				ignore_permissions=True).name
			it = frappe.get_doc("Item", self.ma[sp])
			dong = next((d for d in it.get("item_defaults") or [] if d.company == cong_ty), None) or it.append("item_defaults",
				{"company": cong_ty})
			dong.default_supplier = self.ma[k]
			it.save(ignore_permissions=True)
		for k, ten in nen["khach_them"].items():
			self.ma[k] = frappe.get_doc({"doctype": "Customer", "customer_name": ten, "customer_type": "Company",
				"customer_group": "VTD Khong Nhom"}).insert(ignore_permissions=True).name
		# như nền của bộ sinh (vang_tao_don.sql_nen + khách thêm): chủ "Chu", SĐT, địa chỉ, tuyến
		for i, k in enumerate(("C1", "C2", "C3")):
			frappe.db.set_value("Customer", self.ma[k], {"npp_chu_cua_hang": "Chu", "npp_sdt": "0900000099" if k == "C3" else f"09000000{i + 1:02d}",
				"npp_dia_chi": "Dia chi", "npp_tuyen": nen["tuyen"][k], "npp_trang_thai": "active"})
		for k, nv, vai, tt in nen["phan_cong"]:
			frappe.get_doc({"doctype": "NPP Phan Cong Khach", "khach": self.ma[k], "nhan_vien": self.ma["u:" + nv], "vai_tro": vai,
				"trang_thai": tt, "ngay_phan_cong": "2026-01-05"}).insert(ignore_permissions=True)
		for nv, thu, k, thu_tu in nen["lich_tuyen"]:
			frappe.get_doc({"doctype": "NPP Lich Tuyen", "nhan_vien": self.ma["u:" + nv], "thu": thu, "khach": self.ma[k],
				"thu_tu_ghe": thu_tu}).insert(ignore_permissions=True)
		for d in nen["don"]:
			ket = self._goi(d["nguoi"], "create_order_with_lines", {"p": doi_khoa(d["p"], self.ma)})
			self.assertNotIn("error", ket, ket)
			don = ket["data"][0]["order_id"]
			dong = [{"order_line_id": r.name, "product_id": r.item_code, "unit_name": r.uom, "conversion_factor": r.conversion_factor,
				"quantity": r.qty, "unit_price": r.rate, "line_discount": r.npp_giam_dong, "vat_rate": r.npp_thue_suat}
				for r in frappe.get_all("Sales Order Item", filters={"parent": don}, fields=["name", "item_code", "uom", "conversion_factor",
					"qty", "rate", "npp_giam_dong", "npp_thue_suat"], order_by="idx asc")]
			ket = self._goi("owner", "post_invoice", {"p": {"order_id": don, "lines": dong}})
			self.assertNotIn("error", ket, ket)
		# Sổ tham chiếu chỉ có C1–C3; site thử còn khách của PoC → bỏ khỏi bảng trong giao dịch của bài (lùi lại cuối bài)
		frappe.db.sql("DELETE FROM `tabCustomer` WHERE `name` NOT IN %s", (tuple(self.ma[k] for k in ("C1", "C2", "C3")),))
		self.ma["KHONG_CO"] = self.vang["khong_co"]
		self.ten_cua = {v: k[2:] for k, v in self.ma.items() if k.startswith("u:")}
		self.ten_cua.update({self.ma[k]: k for k in ("C1", "C2", "C3", *nen["ncc"])})
		self.ten_cua[self.vang["khong_co"]] = "KHONG_CO"

	# ------------------------------------------------------------------------------------------------ chạy + chụp
	def _ts(self, ts: dict) -> dict:
		ra = {}
		for k, v in ngay_tuong_doi(ts).items():
			if isinstance(v, list):
				ra[k] = [self.ma[x[1:]] if isinstance(x, str) and x.startswith("@") else (self.ma["KHONG_CO"] if x == self.vang["khong_co"] else x)
					for x in v]
			elif isinstance(v, str) and v.startswith("@"):
				ra[k] = self.ma[v[1:]]
			else:
				ra[k] = v
		return ra

	def _ten(self, x):
		"""Tên Frappe (khách / NCC / NV) → khoá; đi sâu vào dict / list."""
		if isinstance(x, dict):
			return {k: (bool(v) if k == "log_id" else self._ten(v)) for k, v in x.items()}
		if isinstance(x, list):
			return [self._ten(v) for v in x]
		if isinstance(x, str) and x in self.ten_cua:
			return self.ten_cua[x]
		return x

	def _chup(self) -> dict:
		t, hom_nay = self.ten_cua, getdate(nowdate())
		khach = [self.ma[k] for k in ("C1", "C2", "C3")]
		pc = sorted([t[r.khach], t[r.nhan_vien], r.vai_tro, r.trang_thai, getdate(r.ngay_phan_cong) == hom_nay]
			for r in frappe.get_all("NPP Phan Cong Khach", filters={"khach": ("in", khach)},
				fields=["khach", "nhan_vien", "vai_tro", "trang_thai", "ngay_phan_cong"]))
		lt = sorted([t[r.nhan_vien], r.thu, t[r.khach], r.thu_tu_ghe, bool(r.dang_dung)]
			for r in frappe.get_all("NPP Lich Tuyen", filters={"khach": ("in", khach)}, fields=["nhan_vien", "thu", "khach", "thu_tu_ghe",
				"dang_dung"]))
		no = sorted(({"hd": r.hoa_don, "nv": t.get(r.nhan_vien), "giao": t.get(r.giao_tu_nv), "co_ve": r.ve_npp_luc is not None}
			for r in frappe.get_all("NPP Cong No", filters={"khach_hang": ("in", khach)}, fields=["hoa_don", "nhan_vien", "giao_tu_nv",
				"ve_npp_luc"])), key=lambda x: x["hd"])
		nk = sorted(({"nguon": r.nguon, "tu": t.get(r.tu_nv), "den": t.get(r.den_nv), "kieu": r.kieu,
			"bo_loc": self._ten(json.loads(r.bo_loc)), "khach": self._ten(json.loads(r.khach)), "ket_qua": json.loads(r.ket_qua),
			"tao_boi": t.get(r.tao_boi)} for r in frappe.get_all("NPP Ban Giao Khach", fields=["nguon", "tu_nv", "den_nv", "kieu", "bo_loc",
				"khach", "ket_qua", "tao_boi"])), key=lambda x: (x["tu"] or "", x["den"] or ""))
		tb = sorted(({"nguoi": t.get(r.nguoi_nhan), "loai": r.loai, "tieu_de": r.tieu_de, "noi_dung": r.noi_dung,
			"duong_dan": r.duong_dan} for r in frappe.get_all("NPP Thong Bao", filters={"loai": "info"}, fields=["nguoi_nhan", "loai",
				"tieu_de", "noi_dung", "duong_dan"])), key=lambda x: (x["nguoi"] or "", x["tieu_de"]))
		return {"phan_cong": pc or None, "lich_tuyen": lt or None, "cong_no": no or None, "nhat_ky": nk or None, "thong_bao": tb or None}

	def _mot(self, th: dict) -> list[str]:
		sai = []
		for i, (b, m) in enumerate(zip(th["buoc"], th["mong"]["buoc"], strict=True)):
			if b["ham"] == "_nghi_thang":  # mốc nghỉ đặt thẳng (dữ liệu cũ — phân công còn đó)
				frappe.db.set_value("NPP Nhan Vien", self._ts(b["tham_so"])["p_user_id"], "nghi_viec_luc", now_datetime())
				continue
			ket = self._goi(b["nguoi"], b["ham"], self._ts(b["tham_so"]))
			nhan = f"{th['ma']} lệnh {i + 1} ({b['nguoi']} {b['ham']})"
			if m["ok"]:
				if "error" in ket:
					sai.append(f"{nhan}: nppsale ghi được — Frappe báo {ket['error']['code']} {ket['error']['message'][:200]}")
				elif _so(self._ten(ket["data"])) != _so(m["tra"]):
					sai.append(f"{nhan}: {json.dumps(_so(self._ten(ket['data'])), ensure_ascii=False)[:900]}\n      ≠ nppsale "
						f"{json.dumps(_so(m['tra']), ensure_ascii=False)[:900]}")
			elif "error" not in ket:
				sai.append(f"{nhan}: nppsale báo {m['loi']} — Frappe lại ghi được")
			elif (ket["error"]["code"], ket["error"]["message"]) != (m["ma_loi"], m["loi"]):
				sai.append(f"{nhan}: lỗi {ket['error']['code']} {ket['error']['message']} ≠ nppsale {m['ma_loi']} {m['loi']}")
		cuoi, mong = _so(self._chup()), _so(json.loads(json.dumps(th["mong"]["ct"])))
		for k in ("phan_cong", "lich_tuyen", "cong_no", "nhat_ky", "thong_bao"):
			if cuoi[k] != mong.get(k):
				sai.append(f"{th['ma']} cuối {k}: {json.dumps(cuoi[k], ensure_ascii=False)[:900]}\n      ≠ nppsale "
					f"{json.dumps(mong.get(k), ensure_ascii=False)[:900]}")
		return sai

	def test_tung_tinh_huong_nhu_nppsale(self):
		self._dung_nen_ban_giao()
		sai = []
		for th in self.vang["tinh_huong"]:
			frappe.db.savepoint("npp_bg")
			try:
				sai += self._mot(th)
			finally:
				frappe.db.rollback(save_point="npp_bg")
				frappe.local._npp_ngu_canh = None
		self.assertEqual(sai, [], "\n".join(sai))
