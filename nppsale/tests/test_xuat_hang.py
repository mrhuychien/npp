"""Xuất hàng (post_invoice) trên Sales Order / Sales Invoice, so với CHÍNH hàm + trigger của nppsale (cần bench):

	bench --site poc.local run-tests --module nppsale.tests.test_xuat_hang

Dữ liệu vàng du_lieu/xuat_hang_mau.json (tools/vang_xuat_hang.py): tạo đơn → xuất hàng dưới đúng người trên kho có lô (ngày nhận / hạn
tương đối với hôm nay). Bài này dựng cùng kho trên site (Batch + phiếu nhập kho lùi ngày theo ngày nhận vào kho bán / kho cận date), gửi
cùng chuỗi lệnh qua cổng RPC và so: từng lệnh (thành / bại, mã + câu lỗi), số trả về (mã HĐ, short_qty, near_expiry_skipped, trạng thái
đơn), HĐ đọc qua cổng (ngày, hạn, điều khoản, tiền, ghi chú, người đứng tên, từng dòng), lô đã lấy theo từng dòng, tồn mọi lô sau khi xuất,
dòng công nợ (số nợ, đã thu, hạn, trạng thái, NV giữ nợ), trạng thái đơn.

Lệch có chủ đích (LECH): bán vượt tồn ở hàng theo lô — nppsale cho (lô về 0, ghi short_qty) khi bật allow_oversell; lõi không cho lô âm
nên luôn chặn (CFD-05, câu 14 B): mong như khi không cho bán vượt.
"""
from __future__ import annotations

import json
import os

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.truy_van import doc
from nppsale.tests.test_tao_don import doi_khoa, dung_nen
from nppsale.thiet_lap.ban_hang import cai_dat_ban

VANG = os.path.join(os.path.dirname(__file__), "du_lieu", "xuat_hang_mau.json")
ADMIN = NguCanh(user="Administrator", vai=None, bo_qua_rls=True)
LECH = {"ban_vuot_ton": "thieu_ton"}  # tình huống → lấy kết quả mong của tình huống này (lý do ở đầu tệp)


def hom_nay():
	return getdate(nowdate())


def ngay_tuong_doi(v):
	"""\"@hom_nay±n\" → ngày thật — cùng luật với tools/vang_xuat_hang.py."""
	if isinstance(v, str) and v.startswith("@hom_nay"):
		return str(add_days(hom_nay(), int(v[len("@hom_nay"):] or 0)))
	if isinstance(v, dict):
		return {a: ngay_tuong_doi(b) for a, b in v.items()}
	if isinstance(v, list):
		return [ngay_tuong_doi(x) for x in v]
	return v


def dung_kho(nen: dict, ma: dict):
	"""Lô của dữ liệu vàng: mặt hàng có lô → has_batch_no; mỗi lô một Batch (hạn, ngày nhận) + một phiếu nhập kho lùi về ngày nhận."""
	cd = cai_dat_ban()
	for sp in {x[1] for x in nen["lo"]}:
		frappe.db.set_value("Item", ma[sp], {"has_batch_no": 1, "create_new_batch": 0})
	for lo, sp, sl, nhan, han, gia, vung in nen["lo"]:
		ngay_nhan = add_days(hom_nay(), nhan)
		frappe.get_doc({"doctype": "Batch", "batch_id": lo, "item": ma[sp], "expiry_date": add_days(hom_nay(), han),
			"manufacturing_date": ngay_nhan, "npp_ngay_nhap": f"{ngay_nhan} 08:00:00"}).insert(ignore_permissions=True)
		kho = cd.kho_ban if vung == "sale" else cd.kho_can_date
		se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": cd.cong_ty, "posting_date": ngay_nhan,
			"posting_time": "08:00:00", "set_posting_time": 1, "to_warehouse": kho,
			"items": [{"item_code": ma[sp], "qty": sl, "uom": frappe.db.get_value("Item", ma[sp], "stock_uom"), "conversion_factor": 1,
				"basic_rate": gia, "t_warehouse": kho, "use_serial_batch_fields": 1, "batch_no": lo}]})
		se.insert(ignore_permissions=True)
		se.submit()


def ton_lo(ds_lo: list[str]) -> dict:
	return {lo: float(sl) for lo, sl in frappe.db.sql("""SELECT e.`batch_no`, SUM(e.`qty`) FROM `tabSerial and Batch Entry` e
		JOIN `tabSerial and Batch Bundle` b ON b.`name` = e.`parent` WHERE b.`docstatus` = 1 AND b.`is_cancelled` = 0
		AND e.`batch_no` IN %(l)s GROUP BY e.`batch_no`""", {"l": tuple(ds_lo)})}


def lo_cua_hd(hd: str) -> list:
	ds = frappe.db.sql("""SELECT i.`item_code`, e.`batch_no`, ABS(e.`qty`), IFNULL(lo.`npp_ngay_nhap`, lo.`creation`)
		FROM `tabSales Invoice Item` i JOIN `tabSerial and Batch Entry` e ON e.`parent` = i.`serial_and_batch_bundle`
		JOIN `tabBatch` lo ON lo.`name` = e.`batch_no` WHERE i.`parent` = %s""", hd)
	return [[sp, lo, float(sl)] for sp, lo, sl, _n in sorted(ds, key=lambda x: (x[0], str(x[3])))] or None


def _so(x):
	return None if x is None else float(x)


class TestXuatHang(IntegrationTestCase):
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
		dung_kho(self.vang["nen"], self.ma)
		self.nguoi_cua = {v: k[2:] for k, v in self.ma.items() if k.startswith("u:")}

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

	def _dong_xuat(self, don: str, dong_x: list) -> list:
		dd = frappe.get_all("Sales Order Item", filters={"parent": don}, fields=["name", "item_code", "uom", "conversion_factor", "qty",
			"delivered_qty", "rate", "npp_giam_dong", "npp_thue_suat", "additional_notes"], order_by="idx asc")
		ra = []
		for chi_so, de in dong_x:
			de = doi_khoa(de, self.ma)
			if chi_so is None:
				ra.append(de)
				continue
			r = dd[chi_so]
			ra.append({"order_line_id": r.name, "product_id": r.item_code, "unit_name": r.uom, "conversion_factor": r.conversion_factor,
				"quantity": r.qty - (r.delivered_qty or 0), "unit_price": r.rate, "line_discount": r.npp_giam_dong, "vat_rate": r.npp_thue_suat,
				"is_exchange": False, "note": r.additional_notes, **de})
		return ra

	def _ct(self, don: str, tra_ve: list) -> dict:
		so = doc({"bang": "sales_orders", "select": "status, completed_at", "loc": [{"op": "eq", "cot": "id", "gt": don}]}, ADMIN)["data"][0]
		hds = doc({"bang": "sales_invoices", "select": "id, invoice_code, status, invoice_date, due_date, payment_terms, subtotal, vat, total, "
			"notes, sales_user_id, lines:sales_invoice_lines(product_id, unit_name, conversion_factor, quantity, unit_price, line_discount, "
			"line_total, vat_rate, is_exchange, order_line_id, sort_order)", "loc": [{"op": "eq", "cot": "order_id", "gt": don}],
			"thu_tu": [{"cot": "id"}]}, ADMIN)["data"]

		def ngay(v):
			n = (getdate(v) - hom_nay()).days
			return "@hom_nay" if n == 0 else f"@hom_nay{n:+d}"

		hd = []
		for h in hds:
			no = doc({"bang": "receivables", "select": "amount, paid, due_date, status, sales_user_id",
				"loc": [{"op": "eq", "cot": "invoice_id", "gt": h["id"]}]}, ADMIN)["data"]
			dong = sorted(h["lines"], key=lambda x: x["sort_order"])
			hd.append({"ma": h["invoice_code"], "status": h["status"], "ngay": ngay(h["invoice_date"]), "han": ngay(h["due_date"]),
				"dieu_khoan": h["payment_terms"], "subtotal": _so(h["subtotal"]), "vat": _so(h["vat"]), "total": _so(h["total"]),
				"ghi_chu": h["notes"], "sales_user": self.nguoi_cua.get(h["sales_user_id"]),
				"dong": [{"sp": x["product_id"], "dv": x["unit_name"], "hs": _so(x["conversion_factor"]), "sl": _so(x["quantity"]),
					"gia": _so(x["unit_price"]), "giam": _so(x["line_discount"]), "tien": _so(x["line_total"]), "thue": _so(x["vat_rate"]),
					"doi": x["is_exchange"], "noi_don": x["order_line_id"] is not None} for x in dong],
				"lo": lo_cua_hd(h["id"]),
				"cong_no": [{"so_tien": _so(x["amount"]), "da_thu": _so(x["paid"]), "han": ngay(x["due_date"]), "status": x["status"],
					"nv": self.nguoi_cua.get(x["sales_user_id"])} for x in no] or None})
		return {"tra_ve": tra_ve, "don": {"status": so["status"], "co_completed_at": so["completed_at"] is not None}, "hd": hd or None,
			"ton_lo": ton_lo([x[0] for x in self.vang["nen"]["lo"]])}

	@staticmethod
	def _chuan_mong(ct: dict) -> dict:
		ct = json.loads(json.dumps(ct))
		for h in ct.get("hd") or []:
			for k in ("subtotal", "vat", "total"):
				h[k] = _so(h[k])
			for x in h.get("dong") or []:
				for k in ("hs", "sl", "gia", "giam", "tien", "thue"):
					x[k] = _so(x[k])
			for c in h.get("cong_no") or []:
				for k in ("so_tien", "da_thu"):
					c[k] = _so(c[k])
			h["lo"] = [[a, b, _so(c)] for a, b, c in h["lo"]] if h.get("lo") else None
		ct["ton_lo"] = {k: _so(v) for k, v in (ct.get("ton_lo") or {}).items()}
		for x in ct.get("tra_ve") or []:
			x["short_qty"] = _so(x["short_qty"])
		return ct

	def _mot(self, t: dict, mong: dict) -> list[str]:
		sai = []
		frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 1 if t["cho_ban_vuot_ton"] else 0)
		frappe.local._npp_cai_dat_ban = None
		don, tra_ve = None, []
		for i, (b, m) in enumerate(zip(t["buoc"], mong["buoc"], strict=False)):
			nhan = f"{t['ma']} bước {i + 1} ({b['buoc']} — {b['nguoi']})"
			if b["buoc"] == "tao":
				ket = self._goi(b["nguoi"], "create_order_with_lines", {"p": doi_khoa(b["p"], self.ma)})
			else:
				p = {**ngay_tuong_doi(b["p"]), "order_id": don, "lines": self._dong_xuat(don, b["dong"])}
				ket = self._goi(b["nguoi"], "post_invoice", {"p": p})
			if m["ok"]:
				if "error" in ket:
					return [*sai, f"{nhan}: nppsale ghi được — bản Frappe báo {ket['error']['code']} {ket['error']['message'][:200]}"]
				if b["buoc"] == "tao":
					don = ket["data"][0]["order_id"]
				else:
					r = ket["data"][0]
					tra_ve.append({**r, "invoice_id": bool(r["invoice_id"]), "entry_id": bool(r["entry_id"]),
						"receivable_id": bool(r["receivable_id"]), "short_qty": _so(r["short_qty"])})
			else:
				if "error" not in ket:
					return [*sai, f"{nhan}: nppsale báo {m['ma_loi']} {m['loi'][:150]} — bản Frappe lại ghi được"]
				if (ket["error"]["code"], ket["error"]["message"]) != (m["ma_loi"], m["loi"]):
					sai.append(f"{nhan}: lỗi {ket['error']['code']} {ket['error']['message'][:200]} ≠ nppsale {m['ma_loi']} {m['loi'][:200]}")
				break
		if don is None:
			return sai
		ct = self._ct(don, tra_ve)
		ct_mong = self._chuan_mong(mong["ct"])
		for k in ("tra_ve", "don", "hd", "ton_lo"):
			if ct[k] != ct_mong.get(k):
				sai.append(f"{t['ma']}: {k} = {json.dumps(ct[k], ensure_ascii=False)[:600]}\n      nppsale {json.dumps(ct_mong.get(k), ensure_ascii=False)[:600]}")
		return sai

	def test_tung_tinh_huong_nhu_nppsale(self):
		mong_cua = {t["ma"]: t["mong"] for t in self.vang["tinh_huong"]}
		sai = []
		for t in self.vang["tinh_huong"]:
			mong = mong_cua[LECH.get(t["ma"], t["ma"])]
			frappe.db.savepoint("npp_th")
			try:
				sai += self._mot(t, mong)
			finally:
				frappe.db.rollback(save_point="npp_th")
				frappe.local._npp_ngu_canh = None
		if sai:
			self.fail(f"{len(sai)} chỗ lệch nppsale:\n" + "\n".join(sai))
