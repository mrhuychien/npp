"""Phiếu trả (P3c) so với CHÍNH hàm + trigger của nppsale (cần bench):

	bench --site poc.local run-tests --module nppsale.tests.test_phieu_tra_vang

Dữ liệu vàng du_lieu/phieu_tra_mau.json (tools/vang_phieu_tra.py — đặc tả §6, Sổ C): mỗi tình huống là một chuỗi bước dưới đúng người
(tạo đơn kèm trả, xuất hàng có return_adds / return_edits, lập phiếu web / POS, hoàn thành / huỷ phiếu, huỷ / sửa HĐ có tra_da_nhap, huỷ /
xoá đơn, gán người, ghi thẳng bảng qua cổng). Bài này dựng cùng sổ trên site, phát lại cùng chuỗi qua cổng RPC / cổng bảng và so: từng
bước (thành / bại, mã + câu lỗi), số trả về, phiếu trả (trạng thái, tự sinh, tiền, ngày, mốc, kho nhận, HĐ, người, dòng), công nợ, HĐ,
đơn, tồn các lô nền, lô RESTOCK mới, dòng nhập kho đang hiệu lực của phiếu trả.

Lệch có chủ đích (chuẩn hoá trước khi so — lý do ở đặc tả §7):
- Q6: huỷ phiếu tự lập độc lập → nppsale để lại dòng công nợ amount 0; bản chiếu thuần xoá dòng → bỏ dòng `phieu_tra` số tiền 0 của nppsale.
- Phiếu CHƯA TỪNG có dòng: nppsale credit_note_amount NULL, Frappe 0 → so như 0.
- Giá vốn của lô nền sau khi nhập lại vào lô: lõi định giá theo lô trộn giá (nppsale giữ giá lô) → so SỐ LƯỢNG tồn lô nền, không so giá.
- Đảo nhập kho: nppsale lập phiếu XK "Đảo phiếu trả" + ghi chú "(đã đảo)"; Frappe huỷ chứng từ (docstatus 2) → so dòng nhập ĐANG HIỆU LỰC.
LECH_PT: tình huống Frappe khác hẳn (chờ anh chốt) → mong kết quả riêng ghi ở bảng dưới.
"""
from __future__ import annotations

import datetime
import json
import os

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, get_datetime, getdate, nowdate

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.rpc.xuat_hang import DA_XUAT_SQL
from nppsale.tests import test_xuat_hang as XH
from nppsale.tests.test_tao_don import doi_khoa, dung_nen
from nppsale.thiet_lap.ban_hang import cai_dat_ban

VANG = os.path.join(os.path.dirname(__file__), "du_lieu", "phieu_tra_mau.json")

# tình huống → (bước lệch (1-based), mã lỗi Frappe, đầu câu lỗi, lý do) — Frappe báo lỗi ở bước ấy thay vì làm như nppsale
_SL_AM = ("23514", 'new row for relation "return_lines" violates check constraint "return_lines_quantity_khong_am"',
	"Q8a: SL trả âm bị chặn như CHECK đơn giá / thuế (nppsale nhận, nợ tăng; tờ ghi có của lõi không nhận dòng SL dương)")
LECH_PT: dict[str, tuple[int, str, str, str]] = {
	"g10g_sl_am": (1, *_SL_AM),
	"g15c_don_kem_tra_sl_am": (1, *_SL_AM),
	"g16f_sl_am_no_tang": (1, *_SL_AM),
	"g25b_hang_chua_co_lo": (3, "P0001", "RETURN_NO_COST: mặt hàng Hang chua gia VTD chưa có giá vốn",
		"Q3: nppsale nhập lại giá vốn 0 (lõi sẽ lấy giá bán làm giá vốn) — chặn, báo nhập giá vốn mặc định"),
	"g28_huy_khi_hang_da_ban": (5, "P0001", "RETURN_STOCK_USED: hàng nhập lại của phiếu trả đã xuất đi tiếp",
		"Q5: nppsale cho lô âm khi đảo nhập kho; lõi chặn lô âm vô điều kiện (CFD-05)"),
}
# tình huống → (hàm sửa ảnh chụp mong của nppsale, lý do) — lệch không phải lỗi
SUA_MONG = {
	"g54a_xuat_lam_rong": (lambda ct: ct["tra_ve"].__setitem__(1, {"entry_id": False}),
		"Q11: phiếu rỗng hoàn thành không lập chứng từ kho rỗng (nppsale lập phiếu NL không dòng)"),
}


def hom_nay():
	return getdate(nowdate())


def ngay_tuong_doi(v):
	if v in (None, ""):
		return None
	n = (getdate(v) - hom_nay()).days
	return "@hom_nay" if n == 0 else f"@hom_nay{n:+d}"


def _so(x):
	return None if x is None else float(x)


def _chu(x):
	return x if x not in ("", None) else None


class TestPhieuTraVang(IntegrationTestCase):
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
		XH.dung_kho(self.vang["nen"], self.ma)
		self.nguoi_cua = {v: k[2:] for k, v in self.ma.items() if k.startswith("u:")}
		self.lo_nen = {x[0]: x[6] for x in self.vang["nen"]["lo"]}
		cd = cai_dat_ban()
		self.vung = {cd.kho_ban: "sale", cd.kho_can_date: "date"}
		# chứng từ có sẵn trên site (dữ liệu dựng thử cũ) không thuộc tình huống
		self.co_san = {dt: set(frappe.get_all(dt, pluck="name")) for dt in ("Sales Invoice", "Sales Order", "NPP Phieu Tra", "NPP Cong No",
			"Stock Entry", "Batch")}

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_ngu_canh = None

	def _moi(self, dt: str) -> dict:
		"""Lọc bỏ chứng từ có sẵn trên site (danh sách rỗng thì không lọc — `not in ()` của Frappe ra tập rỗng)."""
		return {"name": ("not in", list(self.co_san[dt]))} if self.co_san[dt] else {}

	# ------------------------------------------------------------------------------------------------ gọi dưới đúng người
	def _nguoi(self, nguoi: str):
		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None

	def _goi(self, nguoi: str, ten: str, ts: dict) -> dict:
		self._nguoi(nguoi)
		try:
			return api.rpc(ten=ten, tham_so=ts)
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	def _ghi(self, nguoi: str, yc: dict) -> dict:
		self._nguoi(nguoi)
		try:
			return api.truy_van(yeu_cau={**yc, "select": "id"})
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	# ------------------------------------------------------------------------------------------------ chỗ giữ
	def _dong_cua(self, pt: str | None, sku: str, dv: str, doi: bool) -> str | None:
		if not pt:
			return None
		r = frappe.get_all("NPP Phieu Tra Dong", filters={"parent": pt, "parenttype": "NPP Phieu Tra", "mat_hang": sku, "don_vi": dv,
			"hang_doi": 1 if doi else 0}, pluck="name", order_by="idx asc", limit=1)
		return r[0] if r else None

	def _thay(self, v, st: dict):
		if isinstance(v, str):
			if v in ("@pt", "@hd", "@don"):
				return st[v[1:]]
			if v.startswith(("@dong:", "@doi:")):
				loai, sku, dv = v[1:].split(":", 2)
				return self._dong_cua(st["pt"], sku, dv, loai == "doi") or v
			if v.startswith("@hom_nay"):
				return XH.ngay_tuong_doi(v)
			if v.startswith("@"):
				return doi_khoa(v, self.ma)
			return v
		if isinstance(v, dict):
			return {a: self._thay(b, st) for a, b in v.items()}
		if isinstance(v, list):
			return [self._thay(x, st) for x in v]
		return v

	def _dong_xuat(self, don: str, dong_x: list, st: dict) -> list:
		dd = frappe.get_all("Sales Order Item", filters={"parent": don}, fields=["name", "item_code", "uom", "conversion_factor", "qty",
			"delivered_qty", "rate", "npp_giam_dong", "npp_thue_suat", "additional_notes"], order_by="idx asc")
		ra = []
		for chi_so, de in dong_x:
			de = self._thay(de, st)
			if chi_so is None:
				ra.append(de)
				continue
			r = dd[chi_so]
			ra.append({"order_line_id": r.name, "product_id": r.item_code, "unit_name": r.uom, "conversion_factor": r.conversion_factor,
				"quantity": r.qty - (r.delivered_qty or 0), "unit_price": r.rate, "line_discount": r.npp_giam_dong, "vat_rate": r.npp_thue_suat,
				"is_exchange": False, "note": r.additional_notes, **de})
		return ra

	def _dong_sua(self, hd: str, dong_x: list, st: dict) -> list:
		dd = frappe.get_all("Sales Invoice Item", filters={"parent": hd, "parenttype": "Sales Invoice"}, fields=["so_detail", "npp_dong_don",
			"item_code", "uom", "conversion_factor", "qty", "rate", "npp_giam_dong", "npp_thue_suat", "npp_hang_doi", "npp_ghi_chu"],
			order_by="idx asc")
		ra = []
		for chi_so, de in dong_x:
			de = self._thay(de, st)
			if chi_so is None:
				ra.append(de)
				continue
			r = dd[chi_so]
			ra.append({"order_line_id": r.so_detail or r.npp_dong_don, "product_id": r.item_code, "unit_name": r.uom,
				"conversion_factor": r.conversion_factor, "quantity": r.qty, "unit_price": r.rate, "line_discount": r.npp_giam_dong,
				"vat_rate": r.npp_thue_suat, "is_exchange": bool(r.npp_hang_doi), "note": r.npp_ghi_chu, **de})
		return ra

	# ------------------------------------------------------------------------------------------------ một bước
	def _buoc(self, b: dict, st: dict) -> tuple[dict, dict | None]:
		"""→ (kết quả cổng, phần ghi vào tra_ve hoặc None)."""
		k = b["buoc"]
		if k == "tao":
			ket = self._goi(b["nguoi"], "create_order_with_lines", {"p": self._thay(b["p"], st)})
			if "error" not in ket:
				st["don"] = ket["data"][0]["order_id"]
				r = frappe.get_all("NPP Phieu Tra", filters={"don_hang": st["don"]}, pluck="name", order_by="creation asc, name asc", limit=1)
				st["pt"] = r[0] if r else None
			return ket, None
		if k == "xuat":
			p = {**self._thay(b["p"], st), "order_id": st["don"], "lines": self._dong_xuat(st["don"], b["dong"], st)}
			ket = self._goi(b["nguoi"], "post_invoice", {"p": p})
			if "error" in ket:
				return ket, None
			st["hd"] = ket["data"][0]["invoice_id"]
			r = frappe.get_all("NPP Phieu Tra", filters={"hoa_don": st["hd"]}, pluck="name", order_by="creation asc, name asc", limit=1)
			st["pt"] = r[0] if r else st["pt"]
			return ket, self._tra_ve_hd(ket["data"][0])
		if k == "sua":
			p = {**self._thay(b["p"], st), "lines": self._dong_sua(st["hd"], b["dong"], st)}
			ket = self._goi(b["nguoi"], "reissue_invoice", {"p_invoice_id": st["hd"], "p": p})
			if "error" in ket:
				return ket, None
			st["hd"] = ket["data"][0]["invoice_id"]
			return ket, self._tra_ve_hd(ket["data"][0])
		if k == "lap":
			ket = self._goi(b["nguoi"], "create_return_with_lines", {"p_head": self._thay(b["head"], st), "p_lines": self._thay(b["lines"], st)})
			if "error" not in ket:
				st["pt"] = ket["data"]
			return ket, None
		if k == "pos":
			ket = self._goi(b["nguoi"], "save_pos_return", {"p": self._thay(b["p"], st)})
			if "error" not in ket:
				st["pt"] = ket["data"]
			return ket, None
		if k == "hoan":
			ts = {"p_return_id": st["pt"], "p_zone": b["zone"]}
			if b.get("ngay"):
				ts["p_ngay"] = XH.ngay_tuong_doi(b["ngay"])
			ket = self._goi(b["nguoi"], "complete_return", ts)
			return ket, None if "error" in ket else {"entry_id": bool(ket["data"][0]["entry_id"])}
		if k == "huy_pt":
			return self._goi(b["nguoi"], "cancel_return", {"p_return_id": st["pt"], "p_reason": b["ly_do"]}), None
		if k == "huy":
			ket = self._goi(b["nguoi"], "cancel_invoice", {"p_invoice_id": st["hd"], "p_reason": b["ly_do"]})
			return ket, None if "error" in ket else {"import_entry_id": bool(ket["data"][0]["import_entry_id"]),
				"order_status": ket["data"][0]["order_status"]}
		if k == "huy_don":
			return self._goi(b["nguoi"], "cancel_order", {"p_order_id": st["don"], "p_reason": b["ly_do"]}), None
		if k == "gan":
			return self._goi(b["nguoi"], "assign_doc_seller", {"p_kind": "return", "p_id": st["pt"], "p_user": self.ma["u:" + b["nv"]]}), None
		if k == "gan_hd":
			return self._goi(b["nguoi"], "assign_doc_seller", {"p_kind": "invoice", "p_id": st["hd"], "p_user": self.ma["u:" + b["nv"]]}), None
		if k == "dong_hd":
			ket = self._goi(b["nguoi"], "get_invoiceable_lines", {"p_order_id": st["don"]})
			if "error" in ket:
				return ket, None
			return ket, {"dong_hd": [{a: (bool(v) if a.endswith("_id") else _so(v) if isinstance(v, (int, float)) and not isinstance(v, bool)
				else v) for a, v in x.items()} for x in ket["data"]]}
		if k == "chon":
			dk = {"don": {"don_hang": st["don"]}, "hd": {"hoa_don": st["hd"]}, "moi_nhat": {}}[b["cach"]]
			thu_tu = "creation desc, name desc" if b["cach"] == "moi_nhat" else "creation asc, name asc"
			r = frappe.get_all("NPP Phieu Tra", filters=dk, pluck="name", order_by=thu_tu, limit=1) if all(dk.values()) else []
			st["pt"] = r[0] if r else None
			return {"data": None}, None
		if k == "quyen":
			ten = frappe.db.get_value("NPP Quyen Rieng", {"nhan_vien": self.ma["u:" + b["nv"]], "khoa_quyen": b["khoa"]}, "name")
			if ten:
				frappe.db.set_value("NPP Quyen Rieng", ten, "duoc_phep", 1 if b["duoc"] else 0)
			else:
				frappe.get_doc({"doctype": "NPP Quyen Rieng", "nhan_vien": self.ma["u:" + b["nv"]], "khoa_quyen": b["khoa"],
					"duoc_phep": 1 if b["duoc"] else 0}).insert(ignore_permissions=True)
			return {"data": None}, None
		if k == "doi_khach_don":
			frappe.db.set_value("Sales Order", st["don"], "customer", doi_khoa(b["khach"], self.ma))
			return {"data": None}, None
		if k == "doi_nv_don":
			frappe.db.set_value("Sales Order", st["don"], "npp_nhan_vien", self.ma["u:" + b["nv"]])
			return {"data": None}, None
		if k == "ghi":
			ket = self._ghi(b["nguoi"], self._thay(b["cong"], st))
			return ket, None if "error" in ket else {"so_dong": len(ket.get("data") or [])}
		raise ValueError(f"bước lạ: {k}")

	@staticmethod
	def _tra_ve_hd(r: dict) -> dict:
		return {**r, "invoice_id": bool(r.get("invoice_id")), "entry_id": bool(r.get("entry_id")), "receivable_id": bool(r.get("receivable_id")),
			"short_qty": _so(r.get("short_qty"))}

	# ------------------------------------------------------------------------------------------------ ảnh chụp (cùng dạng _vang_anh_chup)
	def _ct(self, tra_ve: list) -> dict:
		ng = self.nguoi_cua.get
		pt = []
		for r in frappe.get_all("NPP Phieu Tra", filters=self._moi("NPP Phieu Tra"), fields=["name", "trang_thai", "tu_sinh", "tien_tra", "ngay_tra", "ngay_tru_doanh_so",
				"ghi_co_luc", "hoan_thanh_luc", "kho_nhan", "ly_do", "ghi_chu", "ly_do_huy", "huy_luc", "hoa_don", "don_hang", "nhan_vien",
				"owner", "hoan_thanh_boi"], order_by="name asc"):
			dong = frappe.get_all("NPP Phieu Tra Dong", filters={"parent": r.name, "parenttype": "NPP Phieu Tra"}, fields=["mat_hang", "don_vi",
				"so_luong", "don_gia", "thue_suat", "thanh_tien", "hang_doi", "ly_do", "ghi_chu"])
			ds = sorted(({"sp": d.mat_hang, "dv": d.don_vi, "sl": _so(d.so_luong), "gia": _so(d.don_gia), "thue": _so(d.thue_suat),
				"tien": _so(d.thanh_tien), "doi": bool(d.hang_doi), "ly_do": _chu(d.ly_do), "ghi_chu": _chu(d.ghi_chu)} for d in dong),
				key=lambda x: (x["doi"], x["sp"], x["dv"], x["gia"], x["sl"]))
			ghi_co = get_datetime(r.ghi_co_luc) if r.ghi_co_luc else None
			pt.append({"ma": r.name, "status": r.trang_thai, "tu_sinh": bool(r.tu_sinh), "tien": _so(r.tien_tra) or 0.0,
				"ngay_tra": ngay_tuong_doi(r.ngay_tra), "ngay_tru": ngay_tuong_doi(r.ngay_tru_doanh_so), "co_ghi_co": ghi_co is not None,
				"ghi_co_12h": ghi_co is not None and ghi_co.time() == datetime.time(12, 0), "co_hoan_thanh": r.hoan_thanh_luc is not None,
				"zone": self.vung.get(r.kho_nhan), "ly_do": _chu(r.ly_do), "ghi_chu": _chu(r.ghi_chu), "ly_do_huy": _chu(r.ly_do_huy),
				"co_huy_luc": r.huy_luc is not None, "hd": r.hoa_don or None, "co_don": bool(r.don_hang), "nv": ng(r.nhan_vien),
				"nguoi_lap": ng(r.owner), "hoan_thanh_boi": ng(r.hoan_thanh_boi), "dong": ds or None})
		no = [{"hd": c.hoa_don if c.loai in ("hoa_don", "dau_ky") else None, "pt": c.phieu_tra or None, "dau_ky": c.loai == "dau_ky",
			"so_tien": _so(c.so_tien), "da_thu": _so(c.da_thu), "status": c.trang_thai, "nv": ng(c.nhan_vien)}
			for c in frappe.get_all("NPP Cong No", filters=self._moi("NPP Cong No"), fields=["loai", "hoa_don",
				"phieu_tra", "so_tien", "da_thu", "trang_thai", "nhan_vien"])]
		no.sort(key=lambda x: (x["hd"] is None, x["hd"] or "", x["pt"] is None, x["pt"] or "", x["so_tien"]))
		hd = []
		for h in sorted(frappe.get_all("Sales Invoice", filters={"is_return": 0, "docstatus": ("in", (1, 2)),
				**self._moi("Sales Invoice")}, fields=["name", "docstatus",
				"posting_date", "due_date", "npp_han_thanh_toan", "net_total", "discount_amount", "total_taxes_and_charges", "grand_total",
				"npp_ly_do_huy", "npp_nhan_vien"]), key=lambda x: (int(x.name.split("-")[1]), int(x.name.split("-")[2]) if x.name.count("-") > 1
				else 0)):
			dong = frappe.get_all("Sales Invoice Item", filters={"parent": h.name, "parenttype": "Sales Invoice"}, fields=["item_code", "uom",
				"conversion_factor", "qty", "rate", "npp_giam_dong", "amount", "npp_thue_suat", "npp_hang_doi", "so_detail", "npp_dong_don"],
				order_by="idx asc")
			hd.append({"ma": h.name, "status": {1: "posted", 2: "cancelled"}[h.docstatus], "ngay": ngay_tuong_doi(h.posting_date),
				"han": ngay_tuong_doi(h.npp_han_thanh_toan or h.due_date), "subtotal": _so(flt(h.net_total) - flt(h.discount_amount)),
				"vat": _so(h.total_taxes_and_charges), "total": _so(h.grand_total), "huy_ly_do": _chu(h.npp_ly_do_huy),
				"sales_user": ng(h.npp_nhan_vien), "dong": [{"sp": x.item_code, "dv": x.uom, "hs": _so(x.conversion_factor), "sl": _so(x.qty),
					"gia": _so(x.rate), "giam": _so(x.npp_giam_dong), "tien": _so(x.amount), "thue": _so(x.npp_thue_suat), "doi": bool(x.npp_hang_doi),
					"noi_don": h.docstatus == 1 and bool(x.so_detail or x.npp_dong_don)} for x in dong] or None})
		don = []
		for so in frappe.get_all("Sales Order", filters=self._moi("Sales Order"), fields=["name", "npp_trang_thai"],
				order_by="creation asc, name asc"):
			dd = frappe.db.sql(f"""SELECT r.`item_code`, r.`uom`, r.`qty`, {DA_XUAT_SQL.format(t="r")} FROM `tabSales Order Item` r
				WHERE r.`parent` = %s""", so.name)
			don.append({"status": so.npp_trang_thai, "dong_don": sorted([a, b, _so(c), _so(d)] for a, b, c, d in dd) or None})
		ton = XH.ton_lo(list(self.lo_nen))
		ton_lo = {f"{lo}@{vung}": ton.get(lo, 0.0) for lo, vung in self.lo_nen.items()}
		lo_moi = []
		for b in frappe.get_all("Batch", filters={"name": ("like", "RESTOCK-%"), **self._moi("Batch")},
				fields=["name", "item", "expiry_date"], order_by="creation asc"):
			r = frappe.db.sql("""SELECT b.`warehouse`, SUM(e.`qty`), MIN(e.`incoming_rate`) FROM `tabSerial and Batch Entry` e
				JOIN `tabSerial and Batch Bundle` b ON b.`name` = e.`parent` WHERE e.`batch_no` = %s AND b.`docstatus` = 1 AND b.`is_cancelled` = 0
				GROUP BY b.`warehouse`""", b.name)
			for kho, sl, gia in r or [(None, 0, None)]:
				lo_moi.append({"sp": b.item, "ma_dau": "RESTOCK", "zone": self.vung.get(kho), "ton": _so(sl), "gia_von": _so(gia),
					"han": ngay_tuong_doi(b.expiry_date)})
		nhap = [[a, b_, _so(c), _so(d)] for a, b_, c, d in frappe.db.sql("""
			SELECT se.`npp_phieu_tra`, d.`item_code`, d.`transfer_qty`, d.`basic_rate` FROM `tabStock Entry Detail` d
				JOIN `tabStock Entry` se ON se.`name` = d.`parent` WHERE se.`docstatus` = 1 AND IFNULL(se.`npp_phieu_tra`, '') != ''
			UNION ALL
			SELECT si.`npp_phieu_tra`, d.`item_code`, ABS(d.`stock_qty`), d.`incoming_rate` FROM `tabSales Invoice Item` d
				JOIN `tabSales Invoice` si ON si.`name` = d.`parent` WHERE si.`docstatus` = 1 AND si.`is_return` = 1 AND si.`update_stock` = 1
				AND IFNULL(si.`npp_phieu_tra`, '') != ''""")]
		nhap.sort(key=lambda x: (x[0], x[1], x[2]))
		return {"tra_ve": tra_ve, "pt": pt or None, "cong_no": no or None, "hd": hd or None, "don": don or None, "ton_lo": ton_lo,
			"lo_moi": lo_moi or None, "nhap": nhap or None}

	@staticmethod
	def _chuan_mong(ct: dict, lo_nen: dict) -> dict:
		ct = json.loads(json.dumps(ct or {}))
		for p in ct.get("pt") or []:
			p["tien"] = _so(p.get("tien")) or 0.0
			for k in ("ly_do", "ghi_chu", "ly_do_huy"):
				p[k] = _chu(p.get(k))
			for d in p.get("dong") or []:
				for k in ("sl", "gia", "thue", "tien"):
					d[k] = _so(d[k])
				for k in ("ly_do", "ghi_chu"):
					d[k] = _chu(d.get(k))
		ct["cong_no"] = [dict(c, so_tien=_so(c["so_tien"]), da_thu=_so(c["da_thu"])) for c in ct.get("cong_no") or []
			if not (c.get("pt") and not c.get("hd") and abs(float(c["so_tien"])) < 0.005)] or None  # Q6: dòng amount 0 của nppsale
		for h in ct.get("hd") or []:
			for k in ("subtotal", "vat", "total"):
				h[k] = _so(h[k])
			h["huy_ly_do"] = _chu(h.get("huy_ly_do"))
			for x in h.get("dong") or []:
				for k in ("hs", "sl", "gia", "giam", "tien", "thue"):
					x[k] = _so(x[k])
		for d in ct.get("don") or []:
			d["dong_don"] = [[a, b, _so(c), _so(e)] for a, b, c, e in d["dong_don"]] if d.get("dong_don") else None
		ct["ton_lo"] = {k: _so(v[0]) for k, v in (ct.get("ton_lo") or {}).items() if k.split("@")[0] in lo_nen}
		for x in ct.get("lo_moi") or []:
			x["ton"], x["gia_von"] = _so(x["ton"]), _so(x["gia_von"])
		ct["nhap"] = [[a, b, _so(c), _so(d)] for a, b, c, d in ct.get("nhap") or []] or None
		for x in ct.get("tra_ve") or []:
			if isinstance(x, dict) and "short_qty" in x:
				x["short_qty"] = _so(x["short_qty"])
			if isinstance(x, dict) and "dong_hd" in x:
				x["dong_hd"] = [{a: (bool(v) if a.endswith("_id") else _so(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
					for a, v in r.items()} for r in x["dong_hd"] or []]
		ct.pop("phieu_kho", None)
		return ct

	# ------------------------------------------------------------------------------------------------ một tình huống
	def _mot(self, t: dict) -> list[str]:
		mong = t["mong"]
		sai = []
		st = {"don": None, "hd": None, "pt": None}
		tra_ve = []
		lech = LECH_PT.get(t["ma"])
		for i, (b, m) in enumerate(zip(t["buoc"], mong["buoc"], strict=False)):
			nhan = f"{t['ma']} bước {i + 1} ({b['buoc']} — {b['nguoi']})"
			ket, tv = self._buoc(b, st)
			if lech and lech[0] == i + 1:
				if "error" not in ket or (ket["error"]["code"], ket["error"]["message"][:len(lech[2])]) != (lech[1], lech[2]):
					sai.append(f"{nhan}: lệch có chủ đích ({lech[3]}) mong {lech[1]} {lech[2]} — bản Frappe ra {ket.get('error') or 'thành công'}")
				return sai
			if m["ok"]:
				if "error" in ket:
					return [*sai, f"{nhan}: nppsale ghi được — bản Frappe báo {ket['error']['code']} {ket['error']['message'][:300]}"]
				if tv is not None:
					tra_ve.append(tv)
			else:
				if "error" not in ket:
					return [*sai, f"{nhan}: nppsale báo {m['ma_loi']} {m['loi'][:200]} — bản Frappe lại ghi được"]
				if (ket["error"]["code"], ket["error"]["message"]) != (m["ma_loi"], m["loi"]):
					sai.append(f"{nhan}: lỗi {ket['error']['code']} {ket['error']['message'][:300]} ≠ nppsale {m['ma_loi']} {m['loi'][:300]}")
				break
		ct = self._ct(tra_ve)
		ct_mong = self._chuan_mong(mong["ct"], self.lo_nen)
		if t["ma"] in SUA_MONG:
			SUA_MONG[t["ma"]][0](ct_mong)
		for k in ("tra_ve", "pt", "cong_no", "hd", "don", "ton_lo", "lo_moi", "nhap"):
			if ct[k] != ct_mong.get(k):
				sai.append(f"{t['ma']}: {k} lệch ở {'; '.join(XH._cho_lech(ct[k], ct_mong.get(k)))[:2500]}")
		# bất biến sổ của bản ERPNext (tờ ghi có ↔ phiếu ↔ công nợ ↔ phiếu nhập kho) — khám sổ phải sạch ở MỌI trạng thái cuối
		from nppsale.kham_so import quet_phieu_tra

		for d in quet_phieu_tra():
			sai.append(f"{t['ma']}: khám sổ nhóm {d['nhom']} {d['loai']} — {d['chung_tu']}: {d['chi_tiet']}")
		return sai

	def test_tung_tinh_huong_nhu_nppsale(self):
		chi = os.environ.get("NPP_VANG_CHI")  # chạy một phần: NPP_VANG_CHI=g36,g37 (đầu mã)
		sai = []
		for t in self.vang["tinh_huong"]:
			if chi and not any(t["ma"].startswith(x) for x in chi.split(",")):
				continue
			frappe.db.savepoint("npp_th")
			frappe.local._npp_cai_dat_ban = None
			try:
				sai += self._mot(t)
			finally:
				frappe.db.rollback(save_point="npp_th")
				frappe.set_user("Administrator")
				frappe.local._npp_ngu_canh = None
		self.assertFalse(sai, "\n".join(sai))

