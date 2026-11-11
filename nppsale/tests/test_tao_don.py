"""RPC create_order_with_lines trên Sales Order, so với CHÍNH hàm + trigger của nppsale (cần bench):

	bench --site poc.local run-tests --module nppsale.tests.test_tao_don

Dữ liệu vàng du_lieu/tao_don_mau.json do tools/vang_tao_don.py sinh trên Postgres tham chiếu (schema_full.sql của nppsale): mỗi tình huống
là một lần gọi thật dưới vai `authenticated` của đúng người (RLS + trigger), ghi lại lỗi hoặc đơn vừa ghi. Bài này dựng cùng bộ người /
khách / hàng / bảng giá trên site, gọi qua cổng RPC dưới đúng người và so từng tình huống: cùng thành / bại, cùng mã + câu lỗi, đơn ghi ra
cùng trạng thái, người đứng tên, người lập, dòng (hàng, đơn vị, SL, giá, giảm, hệ số, thuế, ghi chú), tiền (subtotal / vat / total đọc qua
cổng), giảm đơn, lịch sử trạng thái, gọi lại cùng client_request_id.

Lệch có chủ đích (blueprint 02 §3.2) — so riêng, không so như nppsale:
  - thuế dòng NULL / không hợp lệ ("theo SP"): method chụp thuế mặt hàng ngay lúc lập → vat / total theo thuế ấy;
  - đơn giá lẻ đồng: tiền làm tròn về đồng (currency_precision 0 — Q3 (a)).
"""
from __future__ import annotations

import json
import os

import frappe
from frappe.tests import IntegrationTestCase

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.truy_van import doc
from nppsale.luat.sdt import email_ky_thuat

VANG = os.path.join(os.path.dirname(__file__), "du_lieu", "tao_don_mau.json")
ADMIN = NguCanh(user="Administrator", vai=None, bo_qua_rls=True)


def _dam_bao_uom(ten):
	if not frappe.db.exists("UOM", ten):
		frappe.get_doc({"doctype": "UOM", "uom_name": ten, "must_be_whole_number": 0}).insert(ignore_permissions=True)


def dung_nen(nen: dict) -> dict:
	"""Dựng người / nhóm / khách / hàng / bảng giá của dữ liệu vàng trên site → bảng đổi khoá tượng trưng ("@C1", "@P1", "@u:x")
	sang tên bản ghi Frappe."""
	ma = {}
	for i, (k, (vai, sua, nang, giam, kieu, tran, lam)) in enumerate(nen["nguoi"].items()):
		sdt = f"0917{500 + i:06d}"
		email = email_ky_thuat(sdt)
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": k, "send_welcome_email": 0}).insert(ignore_permissions=True)
		if not frappe.db.exists("NPP Nhan Vien", email):
			frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": k, "vai": vai, "sdt": sdt, "dang_hoat_dong": 1 if lam else 0,
				"cho_sua_gia": 1 if sua else 0, "tran_tang_gia": nang, "cho_giam_gia": 1 if giam else 0, "kieu_tran_giam": kieu,
				"co_tran_giam": 0 if tran is None else 1, "tran_giam": tran or 0}).insert(ignore_permissions=True)
		ma["u:" + k] = email
	ma["u:khong_co"] = email_ky_thuat("0917999999")
	for k, ten in nen["nhom"].items():
		if not frappe.db.exists("Customer Group", ten):
			frappe.get_doc({"doctype": "Customer Group", "customer_group_name": ten, "parent_customer_group": "All Customer Groups",
				"is_group": 0}).insert(ignore_permissions=True)
		ma[k] = ten
	# khách "không nhóm" của nppsale: Customer bắt buộc có nhóm → một nhóm riêng không có giá nào (bảng giá nhóm trống → Gia chuan)
	nhom_mac_dinh = "VTD Khong Nhom"
	if not frappe.db.exists("Customer Group", nhom_mac_dinh):
		frappe.get_doc({"doctype": "Customer Group", "customer_group_name": nhom_mac_dinh, "parent_customer_group": "All Customer Groups",
			"is_group": 0}).insert(ignore_permissions=True)
	for k, (ten, nhom) in nen["khach"].items():
		ten_kh = frappe.db.get_value("Customer", {"customer_name": ten}, "name")
		if not ten_kh:
			ten_kh = frappe.get_doc({"doctype": "Customer", "customer_name": ten, "customer_type": "Company",
				"customer_group": ma[nhom] if nhom else nhom_mac_dinh}).insert(ignore_permissions=True).name
		ma[k] = ten_kh
	ma["C9"] = "KH-KHONG-CO"
	nhom_hang = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	for k, (sku, ten, dv, gia, thue, dvs) in nen["hang"].items():
		for d in [dv, *dvs]:
			_dam_bao_uom(d)
		if not frappe.db.exists("Item", sku):
			frappe.get_doc({"doctype": "Item", "item_code": sku, "item_name": ten, "item_group": nhom_hang, "stock_uom": dv, "is_stock_item": 1,
				"npp_gia_ban": gia, "npp_thue_suat": thue, "uoms": [{"uom": u, "conversion_factor": h} for u, h in dvs.items()]}).insert(
				ignore_permissions=True)
		ma[k] = sku
	ma["P9"] = "VTD-P9"
	for sp, nhom, dv, gia in nen["gia"]:
		bang = frappe.db.get_value("Customer Group", ma[nhom], "default_price_list") if nhom else "Gia chuan"
		if not frappe.db.exists("Item Price", {"item_code": ma[sp], "price_list": bang, "uom": dv}):
			frappe.get_doc({"doctype": "Item Price", "item_code": ma[sp], "price_list": bang, "uom": dv, "price_list_rate": gia}).insert(
				ignore_permissions=True)
	return ma


def doi_khoa(v, ma: dict):
	if isinstance(v, str) and v.startswith("@"):
		return ma[v[1:]]
	if isinstance(v, dict):
		return {a: doi_khoa(b, ma) for a, b in v.items()}
	if isinstance(v, list):
		return [doi_khoa(x, ma) for x in v]
	return v


def goi_rpc(nguoi: str, ten: str, tham_so: dict) -> dict:
	frappe.set_user(nguoi)
	try:
		return api.rpc(ten=ten, tham_so=tham_so)
	finally:
		frappe.set_user("Administrator")


def _so(x):
	return None if x is None else float(x)


class TestTaoDon(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)

	def setUp(self):
		frappe.db.savepoint("npp_test")
		frappe.local._npp_cai_dat_ban = None
		self.ma = dung_nen(self.vang["nen"])
		self.nguoi_cua = {v: k[2:] for k, v in self.ma.items() if k.startswith("u:")}
		self.hang_mac_dinh = {sku: thue for _k, (sku, _t, _d, _g, thue, _u) in self.vang["nen"]["hang"].items()}

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------------------------------------ so một tình huống
	def _doc_don(self, ten: str) -> dict:
		r = doc({"bang": "sales_orders", "select": "id, status, sales_user_id, created_by, payment_terms, expected_delivery, notes, "
			"subtotal, vat, total, approval_reason, submitted_at, lines:sales_order_lines(product_id, unit_name, quantity, unit_price, "
			"line_discount, conversion_factor, vat_rate, note, sort_order)", "loc": [{"op": "eq", "cot": "id", "gt": ten}]}, ADMIN)["data"][0]
		r["lines"].sort(key=lambda x: x["sort_order"])
		r["giam_don"] = frappe.db.get_value("Sales Order", ten, "npp_giam_gia_don")
		r["lich_su"] = [[a, b] for a, b in frappe.get_all("NPP Nhat Ky Don", filters={"don": ten, "loai": "trang_thai"},
			fields=["tu_trang_thai", "den_trang_thai"], order_by="luc asc, creation asc", as_list=True)] or None
		return r

	def _mot(self, t: dict):
		ma = t["ma"]
		mong = t["mong"]
		p = doi_khoa(t["p"], self.ma)
		nguoi = self.ma["u:" + t["nguoi"]]
		lan, ket = [], None
		for _ in range(2 if t["goi_lai"] else 1):
			ket = goi_rpc(nguoi, "create_order_with_lines", {"p": p})
			if "error" in ket:
				break
			r = ket["data"][0]
			lan.append(r)
		if not mong["ok"]:
			self.assertIn("error", ket, f"{ma}: nppsale báo lỗi {mong['ma_loi']} {mong['loi']!r} — bản Frappe lại ghi được")
			loi = ket["error"]
			self.assertEqual(loi["code"], mong["ma_loi"], f"{ma}: mã lỗi")
			self.assertEqual(loi["message"], mong["loi"], f"{ma}: câu lỗi")
			return
		self.assertNotIn("error", ket, f"{ma}: nppsale ghi được — bản Frappe báo {ket.get('error')}")
		ct = mong["ct"]
		self.assertEqual([x["already_existed"] for x in lan], [x["already_existed"] for x in ct["lan"]], f"{ma}: gọi lại")
		self.assertEqual(len({x["order_id"] for x in lan}), 1, f"{ma}: gọi lại phải trả cùng đơn")
		self.assertEqual(lan[0]["order_code"], lan[0]["order_id"], f"{ma}: mã đơn = id (CFD-01)")
		don = self._doc_don(lan[0]["order_id"])
		thue_sp = any(d["thue"] is None for d in ct["dong"])
		gia_le = any(float(d["gia"]) != int(float(d["gia"])) for d in ct["dong"])
		self.assertEqual(don["status"], ct["status"], f"{ma}: trạng thái")
		self.assertEqual(self.nguoi_cua.get(don["sales_user_id"]), ct["sales_user"], f"{ma}: người đứng tên")
		self.assertEqual(self.nguoi_cua.get(don["created_by"]), ct["created_by"], f"{ma}: người lập")
		self.assertEqual(don["payment_terms"], ct["payment_terms"], f"{ma}: điều khoản")
		self.assertEqual(don["expected_delivery"], ct["expected_delivery"], f"{ma}: ngày giao")
		self.assertEqual(don["notes"], ct["notes"], f"{ma}: ghi chú")
		self.assertEqual(don["approval_reason"], ct["approval_reason"], f"{ma}: cảnh báo")
		self.assertEqual(don["submitted_at"] is not None, ct["co_submitted_at"], f"{ma}: mốc gửi")
		self.assertEqual(don["lich_su"], ct["lich_su"], f"{ma}: lịch sử trạng thái")
		dong = [{"sp": x["product_id"], "dv": x["unit_name"], "sl": _so(x["quantity"]), "gia": _so(x["unit_price"]), "giam": _so(x["line_discount"]),
			"hs": _so(x["conversion_factor"]), "thue": _so(x["vat_rate"]), "ghi_chu": x["note"]} for x in don["lines"]]
		dong_mong = []
		for d in ct["dong"]:
			d = {k: (_so(v) if k in ("sl", "gia", "giam", "hs", "thue") else v) for k, v in d.items()}
			if d["thue"] is None:  # lệch có chủ đích: thuế "theo SP" chụp ngay lúc lập
				d["thue"] = _so(self.hang_mac_dinh[d["sp"]])
			if gia_le:
				d["gia"] = float(round(d["gia"]))
			dong_mong.append(d)
		self.assertEqual(dong, dong_mong, f"{ma}: dòng")
		if not gia_le:
			self.assertEqual(_so(don["subtotal"]), _so(ct["subtotal"]), f"{ma}: subtotal")
			# _giam_don_hien_tai: phần chênh lưu nguyên văn, ngưỡng sai số max(1, số dòng) quyết "có giảm đơn"
			chenh = float(don["giam_don"] or 0)
			self.assertEqual(chenh if chenh > max(1, len(dong)) else 0.0, _so(ct["giam_don"]), f"{ma}: giảm đơn")
			if not thue_sp:
				self.assertEqual(_so(don["vat"]), _so(ct["vat"]), f"{ma}: vat")
				self.assertEqual(_so(don["total"]), _so(ct["total"]), f"{ma}: total")

	def test_tung_tinh_huong_nhu_nppsale(self):
		sai = []
		for t in self.vang["tinh_huong"]:
			frappe.db.savepoint("npp_th")
			try:
				self._mot(t)
			except AssertionError as e:
				sai.append(f"{t['ma']}: " + str(e).split(" : ")[-1].splitlines()[0][:240])
			finally:
				frappe.db.rollback(save_point="npp_th")
				frappe.local._npp_ngu_canh = None
		if sai:
			self.fail(f"{len(sai)} / {len(self.vang['tinh_huong'])} tình huống lệch nppsale:\n" + "\n".join(sai))

	def test_don_ghi_ra_dung_so_sach(self):
		"""Sales Order nháp mang đủ trường lõi bán hàng cần: bảng giá nhóm, kho bán, mẫu thuế, Item Tax Template theo thuế dòng,
		giá bảng của đúng đơn vị, không tự tính lại đơn giá."""
		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == "giam_co_quyen")
		ket = goi_rpc(self.ma["u:" + t["nguoi"]], "create_order_with_lines", {"p": doi_khoa(t["p"], self.ma)})
		so = frappe.get_doc("Sales Order", ket["data"][0]["order_id"])
		self.assertEqual(so.docstatus, 0)
		self.assertEqual(so.selling_price_list, frappe.db.get_value("Customer Group", self.ma["G1"], "default_price_list"))
		self.assertEqual((so.ignore_pricing_rule, so.skip_delivery_note, so.disable_rounded_total), (1, 1, 1))
		self.assertTrue(so.set_warehouse and so.taxes_and_charges)
		r = so.items[0]
		self.assertEqual((r.item_code, r.uom, r.qty, r.rate, r.price_list_rate, r.amount), ("VTD-P1", "Lon", 2, 9000, 9500, 18000))
		self.assertEqual((r.npp_giam_dong, r.npp_thue_suat), (1000, 0.08))
		self.assertTrue(r.item_tax_template.startswith("VAT 8%"))
		self.assertEqual(so.total_taxes_and_charges, 1440)
		self.assertTrue(frappe.get_all("NPP Nhat Ky Don", filters={"don": so.name, "hanh_dong": "add_line"}))

	def test_hang_tra_kem_don_chua_ho_tro(self):
		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == "dung_gia_sales_a")
		p = doi_khoa(t["p"], self.ma)
		p["returns"] = {"reason": "damaged", "notes": None}
		p["return_lines"] = [{"product_id": self.ma["P1"], "unit_name": "Lon", "quantity": 1, "unit_price": 9500, "vat_rate": 0.08,
			"line_total": 9500, "is_exchange": False}]
		ket = goi_rpc(self.ma["u:sales_a"], "create_order_with_lines", {"p": p})
		self.assertTrue(ket["error"]["message"].startswith("RETURNS_CHUA_HO_TRO"))
		self.assertFalse(frappe.db.exists("Sales Order", {"npp_client_request_id": p["client_request_id"]}))

	def test_dong_xuat_hang(self):
		"""get_invoiceable_lines: dòng đơn để màn Xuất hàng dựng HĐ — SL đặt / đã xuất / còn lại, giá, giảm, thuế, giá bán cơ sở, tồn kho bán."""
		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == "giam_co_quyen")
		don = goi_rpc(self.ma["u:" + t["nguoi"]], "create_order_with_lines", {"p": doi_khoa(t["p"], self.ma)})["data"][0]["order_id"]
		ket = goi_rpc(self.ma["u:owner"], "get_invoiceable_lines", {"p_order_id": don})
		self.assertEqual(len(ket["data"]), 1)
		d = ket["data"][0]
		self.assertEqual((d["product_id"], d["sku"], d["product_name"], d["unit_name"], d["conversion_factor"]),
			("VTD-P1", "VTD-P1", "Nuoc ngot VTD", "Lon", 1.0))
		self.assertEqual((d["ordered_qty"], d["invoiced_qty"], d["remaining_qty"]), (2.0, 0.0, 2.0))
		self.assertEqual((d["unit_price"], d["list_price"], d["line_discount"], d["vat_rate"]), (9000.0, 10000.0, 1000.0, 0.08))
		self.assertEqual((d["available_base"], d["is_exchange"], d["return_line_id"]), (0.0, False, None))
		self.assertTrue(d["order_line_id"])
		ket = goi_rpc(self.ma["u:owner"], "get_invoiceable_lines", {"p_order_id": "DH-KHONG-CO"})
		self.assertEqual(ket["error"]["message"], "ORDER_NOT_FOUND")
