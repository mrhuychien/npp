"""Cổng HĐĐT MISA — bốn bảng `invoices` / `company_einvoice_config` / `misa_invoice_snapshots` / `einvoice_logs` (`nppsale/cong/bang/hddt.py`) và lập
dòng HĐĐT theo HĐ bán (`nppsale.api.misa.dam_bao_dong`) — đặc tả HĐĐT §7, §4.2, §8.1 Nhóm J (KV-49, KV-50) + phần cổng của Nhóm K (KV-52, KV-56,
KV-57). Cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_cong_hddt

Gọi đúng cửa trình duyệt dùng (`nppsale.cong.api.truy_van` — savepoint, dịch lỗi, `single()` / `maybeSingle()`) dưới từng người của dữ liệu vàng
xuất hàng (`du_lieu/xuat_hang_mau.json`): chủ (owner), QL (manager), KT (accountant), NVBH (sales_a — người đứng tên đơn), kho (warehouse); câu
select / lọc / sắp chép từ màn nppsale (đường dẫn ghi ở từng bài). Lệch có chủ ý so với nppsale (bài khai): H1 (dòng lập theo đơn gắn HĐ ghi sổ,
QL lập được), H3b (che RefID tờ trống / lỗi), H6 (HĐ đã huỷ không lập dòng), H24 (sửa tờ `error` có RefID; xoá nháp có RefID báo P0001), cổng cấm ghi
`misa_*` / ba bảng còn lại, `NULLIF` chuỗi rỗng, `customer_name` rỗng → 23502, thứ tự mặc định `created_at ↑, id ↑`.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, flt, now_datetime

from nppsale.api import misa as M
from nppsale.cong import api
from nppsale.cong.bang._chung import co_cot
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.ghi import ghi
from nppsale.cong.sql import LoiCong
from nppsale.npp_hddt.doctype.npp_misa_cau_hinh import npp_misa_cau_hinh as CH
from nppsale.tests import test_xuat_hang as XH
from nppsale.tests.test_hddt_khoa import _NenHoaDon, dong_hddt
from nppsale.tests.test_tao_don import doi_khoa

# Câu select của màn nppsale (đúng chuỗi trong mã, `portal/nguon/src`)
COT_DS = ("id, invoice_number, customer_name, total, status, created_at, issued_at, misa_status, misa_invoice_id, misa_ref_id, misa_inv_no, "
	"misa_inv_series, misa_invoice_url, misa_lookup_code, misa_error")  # invoices/page.tsx:176 (15)
COT_CT = ("id, order_id, invoice_number, customer_name, customer_address, customer_tax_code, subtotal, vat, total, status, issued_at, created_at, "
	"misa_invoice_id, misa_ref_id, misa_inv_no, misa_inv_series, misa_inv_date, misa_invoice_code, misa_relation, misa_org_ref_id, misa_note, "
	"misa_no_locked, misa_last_checked_at, misa_invoice_url, misa_status, misa_error, misa_lookup_code, misa_published_at")  # [id]/page.tsx:86 (28)
COT_DON = ("id, org_id, order_id, invoice_number, customer_name, customer_address, customer_tax_code, subtotal, vat, total, status, issued_at, "
	"created_at, misa_invoice_id, misa_ref_id, misa_inv_no, misa_inv_series, misa_inv_date, misa_invoice_code, misa_relation, misa_org_ref_id, "
	"misa_note, misa_no_locked, misa_invoice_url, misa_status, misa_error, misa_sent_at, misa_signed_at, misa_lookup_code, misa_published_at")  # orders (30)
COT_IN = ("id, org_id, order_id, sales_invoice_id, invoice_number, customer_name, customer_address, customer_tax_code, subtotal, vat, total, status, "
	"issued_at, created_at")  # [id]/print/page.tsx:44–48 (14)
# \d invoices / company_einvoice_config / misa_invoice_snapshots / einvoice_logs trên Postgres tham chiếu — đúng thứ tự (select('*'))
COT_33 = ["id", "org_id", "order_id", "invoice_number", "customer_name", "customer_address", "customer_tax_code", "subtotal", "vat", "total", "status",
	"issued_at", "created_at", "misa_invoice_id", "misa_invoice_url", "misa_status", "misa_error", "misa_sent_at", "misa_signed_at", "misa_lookup_code",
	"misa_published_at", "misa_ref_id", "misa_inv_no", "misa_inv_series", "misa_inv_date", "misa_invoice_code", "misa_relation", "misa_org_ref_id",
	"misa_last_checked_at", "misa_note", "misa_no_locked", "sales_invoice_id", "tim_kd"]
COT_CAU_HINH = ["id", "org_id", "provider", "api_base", "tax_code", "seller_name", "seller_address", "misa_company_id", "misa_org_unit_id",
	"misa_template_id", "misa_user_id", "misa_inv_series", "misa_inv_template_no", "username_enc", "password_enc", "sandbox", "is_active", "created_at",
	"updated_at", "token_path", "publish_path", "misa_app_id", "sign_type", "invoice_type", "is_inherit_from_old_template", "misa_is_invoice_with_code"]
COT_SNAPSHOT = ["id", "org_id", "ref_id", "inv_series", "inv_no", "inv_date", "transaction_id", "invoice_code", "buyer_tax_code", "buyer_name",
	"total_amount", "amount_before_vat", "vat_amount", "publish_status", "einvoice_status", "relation", "is_deleted", "org_ref_id", "invoice_id",
	"match_method", "match_confidence", "match_status", "match_note", "raw", "pulled_at", "matched_at", "created_at", "inv_no_norm", "inv_series_norm"]
COT_LOG = ["id", "org_id", "invoice_id", "order_id", "attempt_at", "request_payload", "response_payload", "status", "error_message", "misa_lookup_code",
	"misa_inv_no", "created_by", "created_at"]
COT_TIM = ("invoice_number", "customer_name", "misa_inv_no", "misa_invoice_id")  # invoices/page.tsx:185

RLS = 'new row violates row-level security policy for table "invoices"'
HET_HIEU_LUC = "Hóa đơn {} không còn hiệu lực — không phát hành hoá đơn điện tử được."
CHUA_XUAT = "Đơn chưa có hóa đơn bán nào — xuất hàng trước rồi mới phát hành hoá đơn điện tử."
CAU_XOA = "Chỉ xoá được hoá đơn điện tử nháp chưa gửi MISA."
PGRST116 = "JSON object requested, multiple (or no) rows returned"


def _dk_tim(chu: str) -> str:
	"""Bản Python của `dieuKienTim("invoices", COT_TIM, chu, true)` (`src/lib/search/list-search.ts:211–221`, `ilikeDk` :72–75) cho chữ ASCII."""
	nhom = []
	for tu in chu.split():
		lien = "".join(ch for ch in tu.lower() if ch.isalnum())
		kd = [lien] + ([tu.lower()] if tu.lower() != lien else [])
		nhom.append([f'{c}.ilike."%{tu}%"' for c in COT_TIM] + [f'tim_kd.ilike."%{k}%"' for k in kd])
	if len(nhom) == 1:
		return ",".join(nhom[0])
	return "and(" + ",".join("or(" + ",".join(g) + ")" for g in nhom) + ")"


class _NenCong(_NenHoaDon):
	"""Nền `_NenHoaDon` (đơn của sales_a + HĐ ghi sổ `xuat_du_mot_lo`) + lời gọi cổng dưới đúng người."""

	def tearDown(self):
		super().tearDown()
		frappe.clear_document_cache(CH.TEN, CH.TEN)

	def _cong(self, nguoi: str, yc: dict) -> dict:
		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None
		try:
			return api.truy_van(yeu_cau=json.loads(json.dumps(yc)))
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	def _doc(self, nguoi: str, bang: str = "invoices", **yc) -> list | dict | None:
		kq = self._cong(nguoi, {"bang": bang, **yc})
		self.assertNotIn("error", kq, kq)
		return kq["data"]

	def _dem(self, nguoi: str, loc: list | None = None, bang: str = "invoices") -> int:
		kq = self._cong(nguoi, {"bang": bang, "select": "id", "count": "exact", "head": True, "loc": loc or []})
		self.assertNotIn("error", kq, kq)
		return kq["count"]

	def _ghi(self, nguoi: str, hanh_dong: str, gia_tri=None, loc=None, select=None, mot=None, bang: str = "invoices") -> dict:
		yc = {"bang": bang, "hanh_dong": hanh_dong, "gia_tri": gia_tri, "loc": loc or [], "select": select}
		if mot:
			yc["mot"] = mot
		return self._cong(nguoi, yc)

	def _loi(self, kq: dict) -> tuple:
		self.assertIn("error", kq, kq)
		return (kq["error"]["code"], kq["error"]["message"])

	def _lap(self, ma: str = "xuat_du_mot_lo", *, xuat: bool = True) -> tuple:
		"""Thêm một đơn (+ HĐ ghi sổ) theo tình huống vàng `ma` — mã yêu cầu mới (không trùng đơn của setUp)."""
		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == ma)
		tao, bx = t["buoc"][0], t["buoc"][1]
		p = doi_khoa(tao["p"], self.ma)
		p["client_request_id"] = str(uuid.uuid4())
		don = self._goi(tao["nguoi"], "create_order_with_lines", {"p": p})["data"][0]["order_id"]
		if not xuat:
			return don, None
		px = {**XH.ngay_tuong_doi(bx["p"]), "order_id": don, "lines": XH.TestXuatHang._dong_xuat(self, don, bx["dong"])}
		ket = self._goi(bx["nguoi"], "post_invoice", {"p": px})
		self.assertNotIn("error", ket, ket)
		return don, ket["data"][0]["invoice_id"]

	def _nc(self, nguoi: str) -> NguCanh:
		u = self.ma["u:" + nguoi]
		return NguCanh(user=u, vai=frappe.db.get_value("NPP Nhan Vien", u, "vai"))

	def _hddt(self, ten: str, *truong):
		return frappe.db.get_value("NPP HDDT", ten, list(truong), as_dict=True)


# ============================================================================================================================ ĐỌC
class TestCongHddtDoc(_NenCong):
	"""KV-49 · `invoices` đọc [= trừ H3b] + câu của các màn (danh sách / chi tiết / đơn / HĐ bán / POS / tờ in)."""

	def _so_kv49(self) -> dict:
		self.assertEqual(frappe.db.get_value("Sales Order", self.don, "npp_nhan_vien"), self.ma["u:sales_a"])  # đơn của NVBH A
		r_b, r_d = str(uuid.uuid4()), str(uuid.uuid4())
		s = {
			"A": dong_hddt(nguoi_mua="Khách A", don_hang=self.don),  # misa_status NULL (dòng chuyển sang — dưới)
			"A2": dong_hddt(nguoi_mua="Khách A2", don_hang=self.don),  # misa_status '' (Select trống lưu qua Document)
			"B": dong_hddt(nguoi_mua="Khách B", trang_thai="issued", misa_status="sent", misa_ref_id=r_b),
			"C": dong_hddt(nguoi_mua="Tạp hoá Cô Ba", trang_thai="issued", misa_status="signed", misa_ref_id=str(uuid.uuid4()),
				misa_inv_no="0000123", misa_inv_series="1C26TAA", hoa_don_ban=self.hd, don_hang=self.don),
			"D": dong_hddt(nguoi_mua="Khách D", misa_status="error", misa_error="Chưa cấu hình tài khoản MISA", misa_ref_id=r_d),
			"F": dong_hddt(nguoi_mua="Khách F", trang_thai="issued", misa_status="replaced", misa_ref_id=str(uuid.uuid4())),
		}
		frappe.db.sql("UPDATE `tabNPP HDDT` SET `misa_status` = NULL WHERE `name` = %s", s["A"])
		self.assertEqual(frappe.db.sql("SELECT `misa_status` FROM `tabNPP HDDT` WHERE `name` = %s", s["A2"])[0][0], "")  # thật sự lưu ''
		self.assertIsNone(frappe.db.sql("SELECT `misa_status` FROM `tabNPP HDDT` WHERE `name` = %s", s["A"])[0][0])
		s["r_b"], s["r_d"] = r_b, r_d
		return s

	def test_kv49_nam_cau_dem(self):
		"""Năm câu HEAD của `/invoices` (`invoices/page.tsx:112–116`): tổng 6, signed 1, error 1, chip "Chờ gửi" `or(is.null, eq.pending)` = 2 (A + A2
		— nhờ NULLIF), "Cần chú ý" `in(replaced, cancelled, amount_mismatch, waiting_code)` = 1."""
		cau = [None, [{"op": "eq", "cot": "misa_status", "gt": "signed"}], [{"op": "eq", "cot": "misa_status", "gt": "error"}],
			[{"op": "or", "bieu_thuc": "misa_status.is.null,misa_status.eq.pending", "bang_ngoai": None}],
			[{"op": "in", "cot": "misa_status", "gt": ["replaced", "cancelled", "amount_mismatch", "waiting_code"]}]]
		truoc = [self._dem("owner", c) for c in cau]
		self._so_kv49()
		self.assertEqual([self._dem("owner", c) - t for c, t in zip(cau, truoc, strict=True)], [6, 1, 1, 2, 1])

	def test_kv49_refid_h3b_va_tim(self):
		s = self._so_kv49()
		ds = {r["id"]: r for r in self._doc("owner", select=COT_DS)}
		self.assertIsNone(ds[s["D"]]["misa_ref_id"])  # H3b: tờ lỗi đọc như chưa có RefID → màn hiện "Đẩy lại lên MISA"
		self.assertEqual(frappe.db.get_value("NPP HDDT", s["D"], "misa_ref_id"), s["r_d"])  # sổ vẫn giữ RefID (I1)
		self.assertEqual(ds[s["B"]]["misa_ref_id"], s["r_b"])
		self.assertIsNone(ds[s["A"]]["misa_ref_id"])
		self.assertEqual((ds[s["D"]]["misa_status"], ds[s["D"]]["misa_error"]), ("error", "Chưa cấu hình tài khoản MISA"))
		self.assertIsNone(ds[s["A2"]]["misa_status"])  # NULLIF: '' đọc ra null như nppsale
		self.assertEqual((ds[s["C"]]["misa_inv_no"], ds[s["C"]]["misa_inv_series"], ds[s["C"]]["status"]), ("0000123", "1C26TAA", "issued"))
		# tìm số HĐĐT (tim_kd: '0000123' → khoá có cả '123') — một từ, rồi nhiều từ (and(or(…), or(…)))
		for chu in ("0000123", "123", "co ba 0000123"):
			thay = [r["id"] for r in self._doc("owner", select="id", loc=[{"op": "or", "bieu_thuc": _dk_tim(chu)}])]
			self.assertEqual(thay, [s["C"]], chu)
		self.assertEqual(self._doc("owner", select="id", loc=[{"op": "or", "bieu_thuc": "id.eq.00000000-0000-0000-0000-000000000000"}]), [])
		# coTimKd (list-search.ts:118–131): câu dò phải KHÔNG lỗi
		self.assertIsInstance(self._doc("owner", select="id", loc=[{"op": "or", "bieu_thuc": 'tim_kd.ilike."%0%"'}], limit=1), list)

	def test_kv49_nam_vai(self):
		"""RLS mig 084: chủ / QL / KT mọi dòng; NVBH A đúng dòng có `don_hang` của đơn mình; NVBH khác / kho / NV nghỉ việc 0 dòng (không lỗi)."""
		s = self._so_kv49()
		moi = {s[k] for k in ("A", "A2", "B", "C", "D", "F")}
		for nguoi in ("owner", "manager", "accountant"):
			self.assertEqual(moi & {r["id"] for r in self._doc(nguoi, select="id")}, moi, nguoi)
		self.assertEqual({r["id"] for r in self._doc("sales_a", select="id")}, {s["A"], s["A2"], s["C"]})
		for nguoi in ("sales_b", "warehouse", "sales_nghi"):
			self.assertEqual(self._doc(nguoi, select="id"), [], nguoi)
			self.assertEqual(self._dem(nguoi), 0, nguoi)
		# NVBH đọc dòng của mình đủ cột màn đơn (thẻ "Hoá đơn" của chi tiết đơn điện thoại — mobile-order-detail.tsx:310–319)
		r = self._doc("sales_a", select=COT_DON, loc=[{"op": "eq", "cot": "id", "gt": s["C"]}], mot="one")
		self.assertEqual((r["order_id"], r["misa_status"], r["misa_inv_no"]), (self.don, "signed", "0000123"))

	@staticmethod
	def _them_dong_hd(hd: str, **kv) -> str:
		return dong_hddt(hoa_don_ban=hd, **kv)

	def test_kv49_dong_cua_hd_ban_va_mot_dong(self):
		"""Màn HĐ bán / POS (`sales-invoices/[id]/page.tsx:139–150`, `invoice-screen.tsx:271–276`): `.eq(sales_invoice_id)` + `misa_inv_no desc nulls last,
		created_at desc` + `limit(1).maybeSingle()` → tờ có số trước, rồi mới nhất; `.maybeSingle()` trên hai dòng → PGRST116 (chi tiết đơn nuốt lỗi)."""
		cu = self._them_dong_hd(self.hd, misa_inv_no="00000456", misa_inv_series="1C26TAA", trang_thai="issued", misa_status="signed",
			misa_ref_id=str(uuid.uuid4()), don_hang=self.don)
		moi = self._them_dong_hd(self.hd, misa_status="error", misa_ref_id=str(uuid.uuid4()), don_hang=self.don)
		frappe.db.sql("UPDATE `tabNPP HDDT` SET `creation` = %s WHERE `name` = %s", (add_to_date(now_datetime(), minutes=-5), cu))
		thu_tu = [{"cot": "misa_inv_no", "tang": False, "null_dau": False}, {"cot": "created_at", "tang": False}]
		loc = [{"op": "eq", "cot": "sales_invoice_id", "gt": self.hd}]
		for nguoi, cot in (("owner", "id, misa_inv_no, misa_status"), ("accountant", "status, misa_inv_no, misa_status")):
			r = self._doc(nguoi, select=cot, loc=loc, thu_tu=thu_tu, limit=1, mot="maybe")
			self.assertEqual(r["misa_inv_no"], "00000456", nguoi)
		frappe.db.set_value("NPP HDDT", cu, "misa_inv_no", None)  # không tờ nào có số → mới nhất
		self.assertEqual(self._doc("owner", select="id", loc=loc, thu_tu=thu_tu, limit=1, mot="maybe")["id"], moi)
		kq = self._cong("owner", {"bang": "invoices", "select": COT_DON, "loc": [{"op": "eq", "cot": "order_id", "gt": self.don}], "mot": "maybe"})
		self.assertEqual(self._loi(kq), ("PGRST116", PGRST116))
		self.assertIsNone(self._doc("owner", select="id", loc=[{"op": "eq", "cot": "sales_invoice_id", "gt": "HD-KHONG-CO"}], mot="maybe"))

	def test_luu_tru_p8(self):
		"""`.eq('sales_invoice_id', <uuid LS>)` khớp dòng lưu trữ (KV-49) — chỉ thử được khi đã dựng `hoa_don_ban_ls` (P8)."""
		if not co_cot("NPP HDDT", "hoa_don_ban_ls"):
			self.skipTest("P8 chưa dựng NPP LS Hoa Don / hoa_don_ban_ls — viết bài khi dựng bảng lưu trữ")
		self.fail("đã có hoa_don_ban_ls: viết bài lọc sales_invoice_id / order_id theo dòng lưu trữ (so từng cột riêng — BP §6.1)")

	def test_cot_cua_cac_man(self):
		"""`select('*')` = đúng 33 cột `\\d invoices` (thứ tự); câu của danh sách (15) / chi tiết (28) / đơn (30) / tờ in (14) chạy được, đúng khoá."""
		s = self._so_kv49()
		r = self._doc("owner", select="*", loc=[{"op": "eq", "cot": "id", "gt": s["C"]}], mot="one")
		self.assertEqual(list(r), COT_33)
		self.assertEqual((r["sales_invoice_id"], r["order_id"], r["customer_name"], r["misa_no_locked"], r["org_id"]),
			(self.hd, self.don, "Tạp hoá Cô Ba", False, frappe.db.get_single_value("NPP Cai Dat", "org_id")))
		self.assertEqual(r["tim_kd"], frappe.db.get_value("NPP HDDT", s["C"], "tim_kd"))
		# Select trống lưu '' qua Document (misa_relation của dòng chưa kéo về) — cổng đọc null như nppsale
		self.assertEqual((frappe.db.get_value("NPP HDDT", s["C"], "misa_relation"), r["misa_relation"]), ("", None))
		for cot in (COT_DS, COT_CT, COT_DON, COT_IN):
			r = self._doc("accountant", select=cot, loc=[{"op": "eq", "cot": "id", "gt": s["C"]}], mot="one")
			self.assertEqual(list(r), [x.strip() for x in cot.split(",")])
		t = self._doc("owner", select="order_id, sales_invoice_id, invoice_number, customer_address", loc=[{"op": "eq", "cot": "id", "gt": s["B"]}],
			mot="one")
		self.assertEqual(t, {"order_id": None, "sales_invoice_id": None, "invoice_number": None, "customer_address": None})  # tờ tay: null, không ''

	def test_to_in(self):
		"""Tờ in `/invoices/[id]/print` (`print/page.tsx:44–104`): dòng HĐĐT → `sales_orders` nhúng `users!sales_orders_sales_user_id_fkey` (gợi ý khoá
		ngoại) `.single()` → dòng HĐ bán theo `sort_order` → `organizations` (`loadOrgHeader`)."""
		ten = M.dam_bao_dong(self.hd, self._nc("owner"))
		inv = self._doc("accountant", select=COT_IN, loc=[{"op": "eq", "cot": "id", "gt": ten}], mot="one")
		self.assertEqual((inv["order_id"], inv["sales_invoice_id"]), (self.don, self.hd))
		don = self._doc("accountant", "sales_orders",
			select="id, order_code, customer:customers(phone), sales_user:users!sales_orders_sales_user_id_fkey(full_name, phone)",
			loc=[{"op": "eq", "cot": "id", "gt": inv["order_id"]}], mot="one")
		self.assertEqual(don["id"], self.don)
		self.assertTrue(don["sales_user"] and don["sales_user"]["full_name"], don)
		self.assertIn("phone", don["customer"])
		dong = self._doc("accountant", "sales_invoice_lines",
			select="id, unit_name, quantity, unit_price, line_discount, line_total, product:products(*)",
			loc=[{"op": "eq", "cot": "invoice_id", "gt": inv["sales_invoice_id"]}], thu_tu=[{"cot": "sort_order", "tang": True}])
		self.assertEqual([(d["unit_name"], d["quantity"], d["line_total"]) for d in dong], [("Lon", 2, 19000), ("Chai", 1, 5000)])
		self.assertTrue(all(d["product"] for d in dong))
		org = self._doc("accountant", "organizations", select="name, settings", loc=[{"op": "eq", "cot": "id", "gt": inv["org_id"]}], mot="maybe")
		self.assertIsNotNone(org)

	def test_loc_nang_cao_sap_xep_phan_trang(self):
		"""Lọc nâng cao `LOC_HOA_DON_DIEN_TU` (`list-filter-fields.ts:154–168` → `menhDeMot`, `advanced-filter.ts:90–113`), sắp `SAP_XEP_HD_DIEN_TU`
		(customer_name / total + created_at desc + id), `range` + `count=exact` kèm dữ liệu."""
		s = self._so_kv49()
		frappe.db.set_value("NPP HDDT", s["C"], {"mst_nguoi_mua": "0301175691", "tien_thue": 20000, "tong_tien": 220000, "misa_inv_date": "2026-11-10",
			"phat_hanh_luc": "2026-11-10 09:00:00"}, update_modified=False)
		frappe.db.set_value("NPP HDDT", s["B"], {"tien_thue": 5000, "tong_tien": 55000}, update_modified=False)
		moi = {s[k] for k in ("A", "A2", "B", "C", "D", "F")}

		def loc(*bieu) -> set:
			return moi & {r["id"] for r in self._doc("owner", select="id", loc=[{"op": "or", "bieu_thuc": b} for b in bieu])}

		self.assertEqual(loc('customer_name.ilike."%Cô Ba%"'), {s["C"]})
		self.assertEqual(loc('customer_name.not.ilike."%Khách%"'), {s["C"]})
		self.assertEqual(loc("customer_tax_code.not.is.null"), {s["C"]})
		self.assertEqual(loc("misa_error.is.null"), moi - {s["D"]})
		self.assertEqual(loc("misa_inv_no.not.is.null"), {s["C"]})
		self.assertEqual(loc('status.eq."issued"'), {s["B"], s["C"], s["F"]})
		self.assertEqual(loc('status.neq."issued"'), {s["A"], s["A2"], s["D"]})
		self.assertEqual(loc('misa_status.eq."replaced"'), {s["F"]})
		self.assertEqual(loc('and(total.gte."50000",total.lte."60000")'), {s["B"]})
		self.assertEqual(loc('vat.gte."20000"'), {s["C"]})
		self.assertEqual(loc('misa_inv_date.eq."2026-11-10"'), {s["C"]})
		self.assertEqual(loc('and(issued_at.gte."2026-11-10",issued_at.lte."2026-11-10T23:59:59.999")'), {s["C"]})
		self.assertEqual(loc(f'created_at.gte."{frappe.utils.today()}"'), moi)
		# sắp theo khách (asc, null cuối) + created_at desc + id; theo tổng tiền desc
		tt = [{"cot": "customer_name", "tang": True, "null_dau": False}, {"cot": "created_at", "tang": False}, {"cot": "id", "tang": True}]
		ds = [r["customer_name"] for r in self._doc("owner", select="customer_name", thu_tu=tt) if r["customer_name"] in
			("Khách A", "Khách A2", "Khách B", "Tạp hoá Cô Ba", "Khách D", "Khách F")]
		self.assertEqual(ds, sorted(ds, key=lambda x: frappe.utils.cstr(x).lower()))
		ds = [r["id"] for r in self._doc("owner", select="id, total", thu_tu=[{"cot": "total", "tang": False}]) if r["id"] in moi]
		self.assertEqual(ds[:2], [s["C"], s["B"]])
		kq = self._cong("owner", {"bang": "invoices", "select": COT_DS, "count": "exact", "range": [0, 1],
			"thu_tu": [{"cot": "created_at", "tang": False}, {"cot": "id", "tang": True}]})
		self.assertEqual((len(kq["data"]), kq["count"] >= 6), (2, True))


# ============================================================================================================================ GHI
class TestCongHddtGhi(_NenCong):
	"""KV-50 · `invoices` ghi [= trừ H1 / H24] + KV-52 (phần cổng)."""

	def _them(self, nguoi: str, gt: dict, select: str | None = "id", mot: str | None = "one") -> dict:
		return self._ghi(nguoi, "insert", gt, select=select, mot=mot)

	def _gt_hd(self, hd: str, **kv) -> dict:
		"""Đúng gói `ensureEInvoiceRow` gửi (`publish.ts:70–86`) — người mua + tiền trình duyệt tự điền (sẽ bị bỏ)."""
		return {"org_id": frappe.db.get_single_value("NPP Cai Dat", "org_id"), "order_id": self.don, "sales_invoice_id": hd, "invoice_number": None,
			"customer_name": "Tên trình duyệt gửi", "customer_address": None, "customer_tax_code": None, "subtotal": 1, "vat": 2, "total": 3,
			"status": "draft", **kv}

	def test_ensure_einvoice_row_qua_cong(self):
		"""`ensureEInvoiceRow` (`src/lib/einvoice/publish.ts:51–93`) đi trọn qua cổng như trình duyệt — câu HĐ bán của chi tiết đơn
		(`orders/[id]/page.tsx:557–563`, nhúng khách) → tìm dòng `.eq(sales_invoice_id).maybeSingle()` → chèn `.select('id').single()` → lần hai tìm ra
		đúng dòng ấy. Kèm các câu §7.5 của bảng khác mà luồng HĐĐT chạm (chỉ kiểm cột): chi tiết HĐ bán (`sales-invoices/[id]/page.tsx:125–131`), đơn
		đã giao của `/invoices/new`, dòng đơn (tờ in nhánh cũ), công nợ theo đơn."""
		for nguoi in ("owner", "manager"):  # QL bấm Phát hành ở HĐ chưa có dòng (H1)
			frappe.db.savepoint("ensure")
			si = self._doc(nguoi, "sales_invoices", select="id, org_id, order_id, invoice_code, status, subtotal, vat, total, "
				"customer:customers(store_name, billing_name, billing_address, address, tax_code)", loc=[{"op": "eq", "cot": "id", "gt": self.hd}],
				mot="one")
			self.assertEqual((si["status"], si["order_id"], si["subtotal"], si["vat"], si["total"]), ("posted", self.don, 24000, 2020, 26020))
			self.assertEqual(set(si["customer"]), {"store_name", "billing_name", "billing_address", "address", "tax_code"})
			tim = {"select": "id", "loc": [{"op": "eq", "cot": "sales_invoice_id", "gt": si["id"]}], "mot": "maybe"}
			self.assertIsNone(self._doc(nguoi, **tim))
			c = si["customer"]
			kq = self._ghi(nguoi, "insert", {"org_id": si["org_id"], "order_id": si["order_id"], "sales_invoice_id": si["id"], "invoice_number": None,
				"customer_name": c["billing_name"] or c["store_name"] or "", "customer_address": c["billing_address"] or c["address"] or None,
				"customer_tax_code": c["tax_code"] or None, "subtotal": si["subtotal"], "vat": si["vat"], "total": si["total"], "status": "draft"},
				select="id", mot="one")
			self.assertEqual(kq["status"], 201, kq)
			self.assertEqual(self._doc(nguoi, **tim)["id"], kq["data"]["id"], nguoi)
			frappe.db.rollback(save_point="ensure")
		ct = self._doc("accountant", "sales_invoices", select="id, org_id, invoice_code, invoice_date, status, subtotal, vat, total, payment_terms, "
			"due_date, notes, cancel_reason, cancelled_at, stock_entry_id, replaced_from, replaced_by, order_id, customer_id, customer:customers("
			"store_name, billing_name, billing_address, address, tax_code, phone), sales_user:users!sales_invoices_sales_user_id_fkey(full_name), "
			"creator:users!sales_invoices_posted_by_fkey(full_name), order:sales_orders(order_code, notes)", loc=[{"op": "eq", "cot": "id",
			"gt": self.hd}], mot="maybe")
		self.assertEqual((ct["status"], ct["order_id"], bool(ct["sales_user"]), bool(ct["order"])), ("posted", self.don, True, True))
		don = self._doc("accountant", "sales_orders", select="id, order_code, subtotal, vat, total, customer:customers(store_name, address, phone)",
			loc=[{"op": "eq", "cot": "status", "gt": "completed"}], thu_tu=[{"cot": "order_date", "tang": False}])
		self.assertIn(self.don, [d["id"] for d in don])
		dong = self._doc("owner", "sales_order_lines", select="id, unit_name, quantity, unit_price, line_discount, line_total, product:products(*)",
			loc=[{"op": "eq", "cot": "order_id", "gt": self.don}])
		self.assertEqual(sorted((d["unit_name"], d["quantity"]) for d in dong), [("Chai", 1), ("Lon", 2)])
		no = self._doc("owner", "receivables", select="id, order_id, amount, invoice_id", loc=[{"op": "in", "cot": "order_id", "gt": [self.don]}])
		self.assertEqual([(r["invoice_id"], r["amount"]) for r in no], [(self.hd, 26020)])

	def test_kv50a_quan_ly_lap_dong_gan_hd(self):
		"""(a) QL insert theo HĐ bán → tạo (H1 — nppsale: RLS chỉ chủ / KT ghi ⇒ QL bấm Phát hành ở HĐ chưa có dòng là hỏng); QL tờ tay → 42501; kho /
		NVBH / NV nghỉ → 42501 (cả hai nhánh)."""
		kq = self._them("manager", self._gt_hd(self.hd))
		self.assertEqual(kq["status"], 201, kq)
		ten = kq["data"]["id"]
		self.assertEqual(self._hddt(ten, "hoa_don_ban", "don_hang", "trang_thai", "owner"),
			{"hoa_don_ban": self.hd, "don_hang": self.don, "trang_thai": "draft", "owner": self.ma["u:manager"]})
		tay = {"invoice_number": "INV-20261115-0001", "customer_name": "Cty C", "subtotal": 100000, "vat": 10000, "total": 110000, "status": "draft"}
		self.assertEqual(self._loi(self._them("manager", tay)), ("42501", RLS))
		for nguoi in ("warehouse", "sales_a", "sales_nghi"):
			self.assertEqual(self._loi(self._them(nguoi, self._gt_hd(self.hd))), ("42501", RLS), nguoi)
			self.assertEqual(self._loi(self._them(nguoi, tay)), ("42501", RLS), nguoi)
		self.assertEqual(frappe.db.count("NPP HDDT", {"hoa_don_ban": self.hd}), 1)

	def test_kv50b_insert_lan_hai_tra_dong_san_co(self):
		"""(b) Chủ insert lần hai cùng HĐ → trả dòng sẵn có (idempotent), không dòng thứ hai; `invoice_number` gửi kèm KHÔNG ghi đè số của dòng ấy;
		`/invoices/new` chèn không `.select()` (return=minimal) → 201 không thân."""
		dau = self._them("owner", self._gt_hd(self.hd))["data"]["id"]
		lai = self._them("accountant", self._gt_hd(self.hd, invoice_number="INV-20261115-9999"))["data"]["id"]
		self.assertEqual(lai, dau)
		kq = self._ghi("owner", "insert", self._gt_hd(self.hd, sales_invoice_id=None, invoice_number="INV-20261115-1234"))  # chọn đơn ở /invoices/new
		self.assertEqual((kq["status"], kq["data"]), (201, None))
		self.assertEqual(frappe.db.count("NPP HDDT", {"hoa_don_ban": self.hd}), 1)
		self.assertIsNone(self._hddt(dau, "so_hd_go_tay")["so_hd_go_tay"])
		# dòng MỚI qua /invoices/new chọn đơn: số gõ tay vào dòng
		don2, hd2 = self._lap()
		kq = self._ghi("owner", "insert", self._gt_hd(None, order_id=don2, sales_invoice_id=None, invoice_number="INV-20261115-1234"), select="id",
			mot="one")
		self.assertEqual(self._hddt(kq["data"]["id"], "hoa_don_ban", "so_hd_go_tay"), {"hoa_don_ban": hd2, "so_hd_go_tay": "INV-20261115-1234"})

	def test_kv50c_lap_theo_don_h1(self):
		"""(c) Theo đơn (danh sách đơn "Xuất hoá đơn" — `orders/page.tsx:1235–1253`): đơn chưa xuất → P0001; đơn một HĐ ghi sổ → dòng gắn HĐ, tiền + người
		mua của HĐ (bỏ tiền ĐƠN trình duyệt gửi); đơn > 1 HĐ ghi sổ (dữ liệu trước mig 217) → P0001 "Đơn có 2 hóa đơn bán…"."""
		chua, _ = self._lap(xuat=False)
		self.assertEqual(self._loi(self._them("owner", self._gt_hd(None, order_id=chua, sales_invoice_id=None))), ("P0001", CHUA_XUAT))
		self.assertEqual(frappe.db.count("NPP HDDT", {"don_hang": chua}), 0)
		ten = self._them("owner", self._gt_hd(None, sales_invoice_id=None, subtotal=999, vat=99, total=1098))["data"]["id"]
		r = self._doc("owner", select="sales_invoice_id, order_id, subtotal, vat, total, customer_name", loc=[{"op": "eq", "cot": "id", "gt": ten}],
			mot="one")
		hd = self._doc("owner", "sales_invoices", select="subtotal, vat, total", loc=[{"op": "eq", "cot": "id", "gt": self.hd}], mot="one")
		self.assertEqual((r["sales_invoice_id"], r["order_id"], r["subtotal"], r["vat"], r["total"]),
			(self.hd, self.don, hd["subtotal"], hd["vat"], hd["total"]))
		self.assertEqual((r["subtotal"], r["vat"], r["total"]), (24000, 2020, 26020))  # số vàng nppsale của HĐ (xuat_du_mot_lo)
		self.assertEqual(r["customer_name"], frappe.db.get_value("Customer", self.ma["C1"], "customer_name"))
		_, hd2 = self._lap()
		# tờ ghi có / tờ đầu kỳ cùng đơn không phải "HĐ bán ghi sổ" của đơn
		for cot, gt in (("is_return", 1), ("is_opening", "Yes")):
			frappe.db.sql(f"UPDATE `tabSales Invoice` SET `npp_don_hang` = %s, `{cot}` = %s WHERE `name` = %s", (self.don, gt, hd2))
			self.assertEqual(self._them("owner", self._gt_hd(None, sales_invoice_id=None))["data"]["id"], ten, cot)
			frappe.db.sql(f"UPDATE `tabSales Invoice` SET `{cot}` = %s WHERE `name` = %s", (0 if cot == "is_return" else "No", hd2))
		frappe.db.sql("UPDATE `tabSales Invoice` SET `npp_don_hang` = %s WHERE `name` = %s", (self.don, hd2))  # đơn hai HĐ (trước mig 217)
		self.assertEqual(self._loi(self._them("owner", self._gt_hd(None, sales_invoice_id=None))),
			("P0001", "Đơn có 2 hóa đơn bán. Mở từng hóa đơn ở mục Hóa đơn bán rồi phát hành riêng — phát hành gộp là khai sai chứng từ thuế."))

	def test_to_tay(self):
		"""Tờ tay (`/invoices/new` không chọn đơn): chủ / KT; người mua + tiền + số như gửi; `status` khác draft bị bỏ; `customer_name` rỗng → 23502."""
		gt = {"invoice_number": "INV-20261115-0042", "customer_name": "Cty C", "customer_address": "1 Lê Lợi", "customer_tax_code": "0300000009",
			"subtotal": 100000, "vat": 10000, "total": 110000, "status": "issued", "order_id": None}
		ten = self._them("accountant", gt)["data"]["id"]
		r = self._doc("accountant", select="*", loc=[{"op": "eq", "cot": "id", "gt": ten}], mot="one")
		self.assertEqual({k: r[k] for k in ("invoice_number", "customer_name", "customer_address", "customer_tax_code", "subtotal", "vat", "total",
			"status", "order_id", "sales_invoice_id", "misa_status", "issued_at")}, {"invoice_number": "INV-20261115-0042", "customer_name": "Cty C",
			"customer_address": "1 Lê Lợi", "customer_tax_code": "0300000009", "subtotal": 100000, "vat": 10000, "total": 110000, "status": "draft",
			"order_id": None, "sales_invoice_id": None, "misa_status": None, "issued_at": None})
		self.assertEqual(r["tim_kd"], "inv 20261115 0042 inv202611150042 inv2026111542 cty c ctyc")
		for ten_rong in ("", "   ", None):
			self.assertEqual(self._loi(self._them("owner", {**gt, "customer_name": ten_rong})),
				("23502", 'null value in column "customer_name" of relation "invoices" violates not-null constraint'), ten_rong)
		self.assertEqual(self._loi(self._them("owner", {**gt, "subtotal": "abc"})), ("22P02", 'invalid input syntax for type numeric: "abc"'))

	def test_cot_cam_va_cot_la(self):
		"""`misa_*` / `tim_kd` → 42501 (kèm gợi ý); cột lạ → PGRST204; `org_id` khác site → 42501; upsert → 42501; UPDATE `order_id` /
		`sales_invoice_id` / `misa_*` → 42501 (cả QL — quyền cột đứng trước RLS dòng)."""
		for cot, gt in (("misa_status", "signed"), ("misa_ref_id", "x"), ("misa_inv_no", "1"), ("tim_kd", "x")):
			kq = self._them("owner", {**self._gt_hd(self.hd), cot: gt})
			self.assertEqual(self._loi(kq), ("42501", RLS), cot)
			self.assertTrue(kq["error"]["hint"], cot)
		self.assertEqual(self._loi(self._them("owner", {**self._gt_hd(self.hd), "khong_co": 1}))[0], "PGRST204")
		self.assertEqual(self._loi(self._them("owner", self._gt_hd(self.hd, org_id=str(uuid.uuid4())))), ("42501", RLS))
		self.assertEqual(self._loi(self._ghi("owner", "upsert", self._gt_hd(self.hd)))[0], "42501")
		self.assertEqual(frappe.db.count("NPP HDDT", {"hoa_don_ban": self.hd}), 0)
		ten = dong_hddt()
		loc = [{"op": "eq", "cot": "id", "gt": ten}]
		for nguoi in ("owner", "manager"):
			for gt in ({"misa_status": "signed"}, {"misa_inv_no": "1"}, {"tim_kd": "x"}, {"order_id": self.don}, {"sales_invoice_id": self.hd}):
				kq = self._ghi(nguoi, "update", gt, loc=loc, select="*")
				self.assertEqual(self._loi(kq), ("42501", RLS), (nguoi, gt))
		r = self._hddt(ten, "misa_status", "hoa_don_ban", "don_hang")
		self.assertEqual((r.misa_status or None, r.hoa_don_ban, r.don_hang), (None, None, None))

	def test_kv50d_sua(self):
		"""(d) KT sửa: nháp chưa RefID → OK (trả dòng); nháp `pending` / `sent` có RefID → 0 dòng; nháp `error` có RefID → OK [≠ H24]; `customer_name`
		'  ' → 23502; draft → issued kèm `issued_at` → OK (giờ VN); cancelled → draft → 0 dòng; QL / NVBH / kho → 0 dòng; `status` lạ → 23514."""

		def sua(nguoi, ten, gt):
			return self._ghi(nguoi, "update", gt, loc=[{"op": "eq", "cot": "id", "gt": ten}], select="*")

		nhap = dong_hddt(nguoi_mua="Cty C", mst_nguoi_mua="0300000009", tien_hang=100000, tien_thue=10000, tong_tien=110000)
		kq = sua("accountant", nhap, {"customer_name": "Cty C mới", "customer_address": "2 Lê Lợi", "customer_tax_code": "0300000001",
			"subtotal": 200000, "vat": 20000, "total": 220000})
		self.assertEqual([(r["id"], r["customer_name"], r["customer_tax_code"], r["total"]) for r in kq["data"]],
			[(nhap, "Cty C mới", "0300000001", 220000)])
		self.assertEqual(frappe.db.get_value("NPP HDDT", nhap, "tim_kd"), "cty c moi ctycmoi")  # before_save chạy (đường Document)
		for st in ("pending", "sent"):
			ten = dong_hddt(misa_status=st, misa_ref_id=str(uuid.uuid4()))
			self.assertEqual(sua("accountant", ten, {"customer_tax_code": "0300000001"})["data"], [], st)
			self.assertIsNone(self._hddt(ten, "mst_nguoi_mua")["mst_nguoi_mua"], st)
		r_loi = str(uuid.uuid4())
		loi = dong_hddt(misa_status="error", misa_ref_id=r_loi, mst_nguoi_mua="0300000009")
		self.assertEqual(len(sua("accountant", loi, {"customer_tax_code": "0300000001"})["data"]), 1)
		self.assertEqual(self._hddt(loi, "mst_nguoi_mua", "misa_ref_id"), {"mst_nguoi_mua": "0300000001", "misa_ref_id": r_loi})  # I1
		self.assertEqual(self._loi(sua("owner", nhap, {"customer_name": "  "})),
			("23502", 'null value in column "customer_name" of relation "invoices" violates not-null constraint'))
		kq = sua("owner", nhap, {"status": "issued", "issued_at": "2026-11-15T03:00:00.000Z"})
		self.assertEqual((kq["data"][0]["status"], kq["data"][0]["issued_at"]), ("issued", "2026-11-15T10:00:00+07:00"))
		self.assertEqual(str(self._hddt(nhap, "phat_hanh_luc")["phat_hanh_luc"]), "2026-11-15 10:00:00")
		self.assertEqual(sua("owner", nhap, {"customer_name": "Đổi sau khoá"})["data"], [])  # issued → khoá sửa
		self.assertEqual(sua("owner", nhap, {"status": "draft"})["data"], [])  # issued → draft: không có đường
		self.assertEqual(len(sua("accountant", nhap, {"status": "cancelled"})["data"]), 1)  # issued → cancelled (RLS cho cả KT)
		self.assertEqual(sua("owner", nhap, {"status": "draft"})["data"], [])  # cancelled → draft
		self.assertEqual(sua("owner", nhap, {"status": "issued"})["data"], [])  # cancelled → issued: chỉ phát hành OK
		self.assertEqual(self._hddt(nhap, "trang_thai")["trang_thai"], "cancelled")
		ten = dong_hddt()
		self.assertEqual(len(sua("owner", ten, {"status": "cancelled"})["data"]), 1)  # draft → cancelled
		ten = dong_hddt()
		self.assertEqual(sua("owner", ten, {"issued_at": "2026-11-15T03:00:00.000Z"})["data"], [])  # mốc phát hành chỉ kèm draft → issued
		for nguoi in ("manager", "sales_a", "warehouse"):
			self.assertEqual(sua(nguoi, ten, {"customer_name": "x"})["data"], [], nguoi)
		self.assertEqual(self._loi(sua("owner", ten, {"status": "xyz"})),
			("23514", 'new row for relation "invoices" violates check constraint "invoices_status_check"'))
		self.assertEqual(self._hddt(ten, "nguoi_mua", "trang_thai"), {"nguoi_mua": "Tạp hoá A", "trang_thai": "draft"})

	def test_kv52_sua_to_tay_bi_misa_tu_choi(self):
		"""KV-52 (phần cổng) [≠ H24]: tờ tay bị MISA từ chối (phát hành ghi RefID TRƯỚC khi gửi — `error` có RefID) → KT sửa MST được (1 dòng, RefID giữ
		nguyên — I1); biến thể `pending` (hết giờ) / `issued` (đẩy OK) → 0 dòng; chủ xoá lúc `error` → P0001. nppsale: RefID chưa ghi khi lỗi rõ ⇒ sửa /
		xoá được [=] — đây là khoảng cách H24 lấp."""
		gt = {"customer_name": "Cty C", "customer_tax_code": "0300000009", "subtotal": 100000, "vat": 10000, "total": 110000, "invoice_number": None,
			"status": "draft"}
		t = self._them("accountant", gt)["data"]["id"]
		r = str(uuid.uuid4())
		frappe.db.set_value("NPP HDDT", t, {"misa_status": "error", "misa_ref_id": r, "misa_sent_at": now_datetime(),
			"misa_error": "MISA từ chối hoá đơn: MST người mua không hợp lệ"}, update_modified=False)  # = §4.1.1 bước 9 + 14 (MISA lỗi rõ)
		loc = [{"op": "eq", "cot": "id", "gt": t}]
		kq = self._ghi("accountant", "update", {"customer_tax_code": "0300000001"}, loc=loc, select="*")
		self.assertEqual([(x["customer_tax_code"], x["misa_ref_id"], x["misa_status"]) for x in kq["data"]], [("0300000001", None, "error")])
		self.assertEqual(self._hddt(t, "mst_nguoi_mua", "misa_ref_id", "trang_thai"), {"mst_nguoi_mua": "0300000001", "misa_ref_id": r,
			"trang_thai": "draft"})
		self.assertEqual(self._loi(self._ghi("owner", "delete", loc=loc, select="*")), ("P0001", CAU_XOA))
		self.assertTrue(frappe.db.exists("NPP HDDT", t))
		frappe.db.set_value("NPP HDDT", t, {"misa_status": "pending", "misa_error": "chưa biết MISA nhận chưa — bấm Làm mới trạng thái"},
			update_modified=False)
		self.assertEqual(self._ghi("accountant", "update", {"customer_tax_code": "0300000002"}, loc=loc, select="*")["data"], [])
		frappe.db.set_value("NPP HDDT", t, {"misa_status": "sent", "trang_thai": "issued", "misa_error": None}, update_modified=False)
		self.assertEqual(self._ghi("accountant", "update", {"customer_tax_code": "0300000002"}, loc=loc, select="*")["data"], [])
		self.assertEqual(self._hddt(t, "mst_nguoi_mua")["mst_nguoi_mua"], "0300000001")

	def test_kv50e_xoa(self):
		"""(e) Chủ xoá nháp chưa RefID → OK (`DELETE … RETURNING` trả dòng; Log / Snapshot trỏ tới → `hddt` NULL); nháp có RefID → P0001 [≠ H24];
		`issued` / `cancelled` → 0 dòng; KT xoá được (RLS), QL / NVBH → 0 dòng."""
		ten = dong_hddt(nguoi_mua="Xoá được")
		log = frappe.get_doc({"doctype": "NPP MISA Log", "hddt": ten, "nguon": "publish", "ket_qua": "failed",
			"gui_di": json.dumps([{"RefID": "x"}])}).insert(ignore_permissions=True).name
		sn = frappe.get_doc({"doctype": "NPP MISA Snapshot", "ref_id": str(uuid.uuid4()), "hddt": ten}).insert(ignore_permissions=True).name
		loc = [{"op": "eq", "cot": "id", "gt": ten}]
		for nguoi in ("manager", "sales_a", "warehouse"):
			self.assertEqual(self._ghi(nguoi, "delete", loc=loc, select="*")["data"], [], nguoi)
		kq = self._ghi("owner", "delete", loc=loc, select="*")
		self.assertEqual([(r["id"], r["customer_name"]) for r in kq["data"]], [(ten, "Xoá được")])
		self.assertFalse(frappe.db.exists("NPP HDDT", ten))
		self.assertEqual((frappe.db.get_value("NPP MISA Log", log, "hddt"), frappe.db.get_value("NPP MISA Snapshot", sn, "hddt")), (None, None))
		for kv in ({"misa_status": "error", "misa_ref_id": str(uuid.uuid4())}, {"misa_status": "pending", "misa_ref_id": str(uuid.uuid4())}):
			ten = dong_hddt(**kv)
			self.assertEqual(self._loi(self._ghi("owner", "delete", loc=[{"op": "eq", "cot": "id", "gt": ten}], select="*")), ("P0001", CAU_XOA))
			self.assertTrue(frappe.db.exists("NPP HDDT", ten))
		for kv in ({"trang_thai": "issued"}, {"trang_thai": "cancelled"}, {"trang_thai": "issued", "misa_ref_id": str(uuid.uuid4()),
				"misa_status": "signed", "misa_inv_no": "00000777"}):
			ten = dong_hddt(**kv)
			self.assertEqual(self._ghi("owner", "delete", loc=[{"op": "eq", "cot": "id", "gt": ten}], select="*")["data"], [], kv)
			self.assertTrue(frappe.db.exists("NPP HDDT", ten), kv)
		ten = dong_hddt()
		self.assertEqual(len(self._ghi("accountant", "delete", loc=[{"op": "eq", "cot": "id", "gt": ten}], select="id")["data"]), 1)


# ============================================================================================================================ LẬP DÒNG
class TestDamBaoDong(_NenCong):
	"""§4.2 `dam_bao_dong`: I9 (tiền + người mua từ HĐ bán), một HĐ tối đa một dòng mới, H6, vai, khoá HĐ bán."""

	def test_i9_tien_va_nguoi_mua_tu_hd_ban(self):
		"""Tình huống vàng `giam_gia_don` (giảm cả đơn 2.000): tiền dòng = số vàng nppsale của HĐ (22.000 / 2.020 / 24.020) = cổng `sales_invoices`;
		người mua = tên / địa chỉ xuất HĐ ∥ tên / địa chỉ khách, MST; đơn = đơn của HĐ; `tim_kd` tính."""
		don, hd = self._lap("giam_gia_don")
		mong = next(x for x in self.vang["tinh_huong"] if x["ma"] == "giam_gia_don")["mong"]["ct"]["hd"][0]
		frappe.db.set_value("Customer", self.ma["C1"], {"npp_ten_xuat_hd": "Công ty TNHH Tạp hoá VTD", "npp_dia_chi_xuat_hd": "12 Lê Lợi, Q1",
			"npp_dia_chi": "Chợ Bến Thành", "tax_id": "0301175691-044"})
		ten = M.dam_bao_dong(hd, self._nc("manager"))
		r = self._hddt(ten, "hoa_don_ban", "don_hang", "trang_thai", "nguoi_mua", "dia_chi_nguoi_mua", "mst_nguoi_mua", "tien_hang", "tien_thue",
			"tong_tien", "so_hd_go_tay", "misa_status", "misa_ref_id", "tim_kd")
		r.misa_status = r.misa_status or None  # Select trống lưu '' qua Document — cổng đọc NULLIF
		self.assertEqual((flt(r.tien_hang), flt(r.tien_thue), flt(r.tong_tien)), (mong["subtotal"], mong["vat"], mong["total"]))
		self.assertEqual((mong["subtotal"], mong["vat"], mong["total"]), (22000, 2020, 24020))
		si = frappe.db.get_value("Sales Invoice", hd, ["net_total", "discount_amount", "total_taxes_and_charges", "grand_total"], as_dict=True)
		self.assertEqual((flt(r.tien_hang), flt(r.tien_thue), flt(r.tong_tien)),
			(flt(si.net_total) - flt(si.discount_amount), flt(si.total_taxes_and_charges), flt(si.grand_total)))  # I9 nguyên văn
		self.assertEqual({k: r[k] for k in ("hoa_don_ban", "don_hang", "trang_thai", "nguoi_mua", "dia_chi_nguoi_mua", "mst_nguoi_mua",
			"so_hd_go_tay", "misa_status", "misa_ref_id")}, {"hoa_don_ban": hd, "don_hang": don, "trang_thai": "draft",
			"nguoi_mua": "Công ty TNHH Tạp hoá VTD", "dia_chi_nguoi_mua": "12 Lê Lợi, Q1", "mst_nguoi_mua": "0301175691-044", "so_hd_go_tay": None,
			"misa_status": None, "misa_ref_id": None})
		self.assertEqual(r.tim_kd, "cong ty tnhh tap hoa vtd congtytnhhtaphoavtd")
		# không có tên / địa chỉ xuất HĐ → tên / địa chỉ khách (`billing_name || store_name`, `billing_address || address`)
		frappe.db.set_value("Customer", self.ma["C1"], {"npp_ten_xuat_hd": None, "npp_dia_chi_xuat_hd": None, "tax_id": None})
		ten = M.dam_bao_dong(self.hd, self._nc("owner"), so_hd_go_tay="INV-1")
		self.assertEqual(self._hddt(ten, "nguoi_mua", "dia_chi_nguoi_mua", "mst_nguoi_mua", "so_hd_go_tay", "tong_tien"),
			{"nguoi_mua": frappe.db.get_value("Customer", self.ma["C1"], "customer_name"), "dia_chi_nguoi_mua": "Chợ Bến Thành", "mst_nguoi_mua": None,
			"so_hd_go_tay": "INV-1", "tong_tien": 26020})

	def test_mot_hd_mot_dong_va_thu_tu_du_lieu_cu(self):
		"""Gọi lại → cùng dòng, không đổi gì (kể cả số gõ tay); dữ liệu cũ ≥ 2 dòng / HĐ: tờ có số trước, rồi mới nhất (màn HĐ bán)."""
		a = M.dam_bao_dong(self.hd, self._nc("owner"))
		truoc = self._hddt(a, "modified", "so_hd_go_tay", "nguoi_mua")
		self.assertEqual(M.dam_bao_dong(self.hd, self._nc("accountant"), so_hd_go_tay="INV-9"), a)
		self.assertEqual(self._hddt(a, "modified", "so_hd_go_tay", "nguoi_mua"), truoc)
		self.assertEqual(frappe.db.count("NPP HDDT", {"hoa_don_ban": self.hd}), 1)
		b = dong_hddt(hoa_don_ban=self.hd)  # dòng thứ hai (dữ liệu chuyển sang), mới hơn
		frappe.db.sql("UPDATE `tabNPP HDDT` SET `creation` = %s WHERE `name` = %s", (add_to_date(now_datetime(), minutes=-5), a))
		self.assertEqual(M.dam_bao_dong(self.hd, self._nc("owner")), b)  # chưa tờ nào có số → mới nhất
		frappe.db.set_value("NPP HDDT", a, {"misa_inv_no": "00000123", "misa_inv_series": "1C26TAA"}, update_modified=False)
		self.assertEqual(M.dam_bao_dong(self.hd, self._nc("owner")), a)  # tờ có số trước

	def test_h6_hd_khong_con_hieu_luc(self):
		"""HĐ đã huỷ / không có / tờ ghi có / tờ đầu kỳ → P0001 "không còn hiệu lực" (câu của `ensureEInvoiceRow`) — kể cả khi HĐ đã có dòng HĐĐT."""
		dong = M.dam_bao_dong(self.hd, self._nc("owner"))
		self.assertNotIn("error", self._huy())
		with self.assertRaises(LoiCong) as e:
			M.dam_bao_dong(self.hd, self._nc("owner"))
		self.assertEqual((e.exception.ma, e.exception.thong_diep, e.exception.http), ("P0001", HET_HIEU_LUC.format(self.hd), 400))
		self.assertEqual(frappe.db.count("NPP HDDT", {"hoa_don_ban": self.hd}), 1)
		self.assertTrue(frappe.db.exists("NPP HDDT", dong))
		for hd in ("HD-KHONG-CO", "", None):
			with self.assertRaises(LoiCong) as e:
				M.dam_bao_dong(hd, self._nc("owner"))
			self.assertEqual(e.exception.thong_diep, HET_HIEU_LUC.format(hd or ""), hd)
		_, hd2 = self._lap()
		for cot, gt in (("is_return", 1), ("is_opening", "Yes")):
			frappe.db.savepoint("h6")
			frappe.db.sql(f"UPDATE `tabSales Invoice` SET `{cot}` = %s WHERE `name` = %s", (gt, hd2))
			with self.assertRaises(LoiCong) as e:
				M.dam_bao_dong(hd2, self._nc("owner"))
			self.assertEqual(e.exception.thong_diep, HET_HIEU_LUC.format(hd2), cot)
			frappe.db.rollback(save_point="h6")
		# qua cổng: câu nguyên văn, mã P0001
		kq = self._ghi("owner", "insert", {"sales_invoice_id": self.hd, "customer_name": "x"}, select="id", mot="one")
		self.assertEqual(self._loi(kq), ("P0001", HET_HIEU_LUC.format(self.hd)))

	def test_vai(self):
		"""Vai lập dòng = vai phát hành (chủ / KT / QL — H1); NVBH / kho / NV nghỉ → 42501; việc nền (Administrator, bỏ RLS) được."""
		for nguoi in ("sales_a", "warehouse", "sales_nghi"):
			nc = self._nc(nguoi) if nguoi != "sales_nghi" else NguCanh(user=self.ma["u:sales_nghi"], vai=None)
			with self.assertRaises(LoiCong) as e:
				M.dam_bao_dong(self.hd, nc)
			self.assertEqual((e.exception.ma, e.exception.thong_diep), ("42501", RLS), nguoi)
		self.assertEqual(frappe.db.count("NPP HDDT", {"hoa_don_ban": self.hd}), 0)
		ten = M.dam_bao_dong(self.hd, NguCanh(user="Administrator", bo_qua_rls=True))
		self.assertEqual(M.dam_bao_dong(self.hd, self._nc("manager")), ten)

	def test_khoa_hd_ban_truoc(self):
		"""Câu đầu tiên chạm sổ là khoá dòng HĐ bán `FOR UPDATE` (thứ tự khoá HĐ bán → dòng HĐĐT như `_huy`); không thấy dòng ở đọc thường thì đọc
		CÓ KHOÁ trước khi chèn. (Bài hai kết nối thật: TestDamBaoDongDocCoKhoa.)"""
		goc = frappe.db.sql
		cau = []

		def ghi_lai(q, *a, **k):
			cau.append(" ".join(str(q).split()))
			return goc(q, *a, **k)

		nc = self._nc("owner")
		with patch.object(frappe.db, "sql", ghi_lai):
			ten = M.dam_bao_dong(self.hd, nc)
		self.assertTrue(cau and "FROM `tabSales Invoice`" in cau[0] and cau[0].endswith("FOR UPDATE"), cau[:2])
		tim = [i for i, q in enumerate(cau) if "FROM `tabNPP HDDT`" in q and "`hoa_don_ban` = %s" in q]
		chen = [i for i, q in enumerate(cau) if q.startswith("INSERT INTO `tabNPP HDDT`")]
		self.assertTrue(tim and chen, cau)
		self.assertTrue(any(cau[i].endswith("LOCK IN SHARE MODE") for i in tim if i < chen[0]), [cau[i] for i in tim])
		self.assertTrue(frappe.db.exists("NPP HDDT", ten))


# ============================================================================================================================ KV-56
class TestKv56HaiDongMotDon(_NenCong):
	"""KV-56 [= trừ H6]: SO có E10 (`draft`, `error` — tờ HD cũ) → Sửa HĐ (vế khoá không gồm `error`) ra HD-…-1 → màn HĐ bán bấm Phát hành → E11 (`sent`).
	E10 mang tên uuid4 xếp SAU mọi uuid7 trong khoá chính (như dòng chuyển sang từ nppsale) — bỏ thứ tự mặc định thì câu không `order` trả theo khoá chính
	(E11 trước E10) và `invMap` của danh sách đơn ra E10."""

	E10 = "ffffffff-ffff-4fff-bfff-ffffffffffff"  # MariaDB so `uuid` từ nhóm cuối (node) — node ff… đứng sau uuid7 (đo trên poc.local)

	def _dung(self):
		e10 = dong_hddt(name=self.E10, hoa_don_ban=self.hd, don_hang=self.don, misa_status="error", misa_ref_id=str(uuid.uuid4()),
			misa_error="MISA từ chối hoá đơn: …")
		frappe.db.sql("UPDATE `tabNPP HDDT` SET `creation` = %s WHERE `name` = %s", (add_to_date(now_datetime(), minutes=-30), e10))
		kq = self._sua()
		self.assertNotIn("error", kq, kq)
		hd_moi = kq["data"][0]["invoice_id"]
		self.assertEqual((frappe.db.get_value("Sales Invoice", self.hd, "docstatus"), frappe.db.get_value("Sales Invoice", hd_moi, "npp_don_hang")),
			(2, self.don))
		return e10, hd_moi

	def test_kv56a_dong_moi_thang_trong_invmap(self):
		e10, hd_moi = self._dung()
		# chỉ có E10: nút "Xuất hoá đơn" ở danh sách đơn thấy E10 trong invMap; lập lại theo ĐƠN (chưa có dòng) thì gắn tờ MỚI, không vớ E10
		e11 = self._ghi("owner", "insert", {"order_id": self.don, "customer_name": "x", "status": "draft"}, select="id", mot="one")["data"]["id"]
		self.assertNotEqual(e11, e10)
		self.assertEqual(self._hddt(e11, "hoa_don_ban")["hoa_don_ban"], hd_moi)
		frappe.db.set_value("NPP HDDT", e11, {"misa_status": "sent", "misa_ref_id": str(uuid.uuid4()), "trang_thai": "issued"},
			update_modified=False)
		# (a) orders/page.tsx:821 — `in(order_id)` KHÔNG order → [E10, E11] (creation ↑) ⇒ invMap[SO] = dòng về sau = E11
		ds = self._doc("owner", select=COT_DON, loc=[{"op": "in", "cot": "order_id", "gt": [self.don]}])
		self.assertEqual([r["id"] for r in ds], [e10, e11])
		inv_map = {}
		for r in ds:
			inv_map[r["order_id"]] = r
		self.assertEqual(inv_map[self.don]["id"], e11)
		# đối chứng thứ tự khoá chính (bài này chỉ bắt được lỗi khi E11 đứng trước E10 trong khoá chính)
		self.assertEqual([x for (x,) in frappe.db.sql("SELECT `name` FROM `tabNPP HDDT` WHERE `name` IN (%s, %s) ORDER BY `name`", (e10, e11))],
			[e11, e10])

	def test_kv56c_mot_dong_theo_don_va_theo_hd(self):
		_, hd_moi = self._dung()
		e11 = M.dam_bao_dong(hd_moi, self._nc("owner"))
		# (c) chi tiết đơn `.eq(order_id).maybeSingle()` → PGRST116 (màn nuốt, hiện "Xuất hóa đơn") → bấm → ensureEInvoiceRow(HD-…-1) tìm ra E11
		kq = self._cong("owner", {"bang": "invoices", "select": COT_DON, "loc": [{"op": "eq", "cot": "order_id", "gt": self.don}], "mot": "maybe"})
		self.assertEqual(self._loi(kq), ("PGRST116", PGRST116))
		r = self._doc("owner", select="id", loc=[{"op": "eq", "cot": "sales_invoice_id", "gt": hd_moi}], mot="maybe")
		self.assertEqual(r["id"], e11)
		ins = self._ghi("owner", "insert", {"sales_invoice_id": hd_moi, "order_id": self.don, "customer_name": "x", "status": "draft"},
			select="id", mot="one")
		self.assertEqual(ins["data"]["id"], e11)
		# H6 ở cổng: tờ cũ đã huỷ không lập / không trả dòng (nppsale: phát hành E10 cho HĐ đã huỷ — route chặn 400, bài route)
		kq = self._ghi("owner", "insert", {"sales_invoice_id": self.hd, "customer_name": "x", "status": "draft"}, select="id", mot="one")
		self.assertEqual(self._loi(kq), ("P0001", HET_HIEU_LUC.format(self.hd)))
		self.assertEqual(frappe.db.count("NPP HDDT", {"don_hang": self.don}), 2)


# ============================================================================================================================ BA BẢNG CHỈ ĐỌC
class TestBaBangChiDoc(_NenCong):
	"""`company_einvoice_config` / `misa_invoice_snapshots` / `einvoice_logs` — cột, vế đọc (chủ / KT / QL), cấm ghi (KV-50 (f), (g); KV-57 phần cổng)."""

	def _xoa_cau_hinh(self):
		frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)
		frappe.db.sql("DELETE FROM `__Auth` WHERE `doctype` = %s", CH.TEN)
		frappe.clear_document_cache(CH.TEN, CH.TEN)

	def test_cau_hinh(self):
		"""Chưa lưu → 0 dòng (maybeSingle → null — màn dựng link MISA không có CompanyID); lưu rồi → một dòng 26 cột cho chủ / KT / QL; NVBH / kho 0
		dòng; `username_enc` / `password_enc` luôn null, không chuỗi nào chứa tài khoản / mật khẩu (I6); ghi → 42501."""
		self._xoa_cau_hinh()
		for nguoi in ("owner", "accountant", "manager"):
			self.assertIsNone(self._doc(nguoi, "company_einvoice_config", select="misa_company_id", mot="maybe"), nguoi)
			self.assertEqual(self._dem(nguoi, bang="company_einvoice_config"), 0, nguoi)
		ch = frappe.get_single(CH.TEN)
		ch.update({"tai_khoan": "u-thu", "mat_khau": "p-thu", "dia_chi_api": "https://misa.gia/api/v2", "mst_nguoi_ban": "0100000000",
			"misa_company_id": "156217", "misa_inv_series": "1C26TAA", "ten_nguoi_ban": "NPP Thử"})
		ch.save(ignore_permissions=True)
		self.assertTrue(CH.da_luu())
		for nguoi in ("owner", "accountant", "manager"):
			self.assertEqual(self._doc(nguoi, "company_einvoice_config", select="misa_company_id", mot="maybe"), {"misa_company_id": "156217"}, nguoi)
		r = self._doc("owner", "company_einvoice_config", select="*", mot="one")
		self.assertEqual(list(r), COT_CAU_HINH)
		self.assertEqual({k: r[k] for k in COT_CAU_HINH if k not in ("org_id", "updated_at")}, {
			"id": "NPP MISA Cau Hinh", "provider": "misa", "api_base": "https://misa.gia/api/v2", "tax_code": "0100000000", "seller_name": "NPP Thử",
			"seller_address": None, "misa_company_id": "156217", "misa_org_unit_id": None, "misa_template_id": None, "misa_user_id": None,
			"misa_inv_series": "1C26TAA", "misa_inv_template_no": "1", "username_enc": None, "password_enc": None, "sandbox": True, "is_active": True,
			"created_at": None, "token_path": "/oauth", "publish_path": "/v3sainvoice", "misa_app_id": None, "sign_type": 1, "invoice_type": 1,
			"is_inherit_from_old_template": False, "misa_is_invoice_with_code": False})
		self.assertEqual(r["org_id"], frappe.db.get_single_value("NPP Cai Dat", "org_id"))
		self.assertTrue(r["updated_at"])
		tho = json.dumps(r, ensure_ascii=False)
		self.assertNotIn("u-thu", tho)
		self.assertNotIn("p-thu", tho)
		for nguoi in ("sales_a", "warehouse"):
			self.assertIsNone(self._doc(nguoi, "company_einvoice_config", select="misa_company_id", mot="maybe"), nguoi)
		for hd, gt in (("insert", {"misa_company_id": "1"}), ("update", {"misa_company_id": "1"}), ("delete", None), ("upsert", {"misa_company_id": "1"})):
			self.assertEqual(self._loi(self._ghi("owner", hd, gt, bang="company_einvoice_config"))[0], "42501", hd)
		self.assertEqual(frappe.db.get_single_value(CH.TEN, "misa_company_id"), "156217")

	def test_snapshot(self):
		"""KV-57 phần cổng: `publish_status` / `einvoice_status` lưu chữ → số nguyên hoặc null (`'3.5'` / `'abc'` / `''` → null — CAST trần của MariaDB ra
		3 / 0); `total_amount` null khi MISA không trả; tiền trước thuế / thuế 0 → null; chuẩn hoá theo hàm khớp; 29 cột; vế đọc; cấm ghi."""
		hddt = dong_hddt()
		mau = [("3", "1", 1, 212600, "a"), ("3.5", "7", 1, -1000, "b"), ("abc", "", 0, 0, "c"), ("", None, 1, 0, "d"), ("-1", "08", 0, 5, "e")]
		ten = {}
		for ps, es, co, tong, k in mau:
			ten[k] = frappe.get_doc({"doctype": "NPP MISA Snapshot", "ref_id": str(uuid.uuid4()), "ky_hieu": "1c26 taa" if k == "a" else None,
				"so_hddt": "00000123" if k == "a" else None, "publish_status": ps, "einvoice_status": es, "co_tong_tien": co, "tong_tien": tong,
				"tien_truoc_thue": 195000 if k == "a" else 0, "tien_thue": 17600 if k == "a" else 0, "hddt": hddt if k == "a" else None,
				"ban_ghi_tho": json.dumps({"RefID": k, "PublishStatus": ps}), "keo_luc": now_datetime(),
				"ket_qua_khop": "matched" if k == "a" else "misa_only"}).insert(ignore_permissions=True).name
		ds = {r["id"]: r for r in self._doc("manager", "misa_invoice_snapshots", select="*",
			loc=[{"op": "in", "cot": "id", "gt": list(ten.values())}])}
		self.assertEqual(list(ds[ten["a"]]), COT_SNAPSHOT)
		self.assertEqual([(ds[ten[k]]["publish_status"], ds[ten[k]]["einvoice_status"], ds[ten[k]]["total_amount"]) for k in "abcde"],
			[(3, 1, 212600), (None, 7, -1000), (None, None, None), (None, None, 0), (-1, 8, None)])
		a = ds[ten["a"]]
		self.assertEqual((a["amount_before_vat"], a["vat_amount"], a["inv_no_norm"], a["inv_series_norm"], a["invoice_id"], a["raw"]["RefID"],
			a["match_status"]), (195000, 17600, "123", "1C26TAA", hddt, "a", "matched"))
		self.assertEqual((ds[ten["b"]]["amount_before_vat"], ds[ten["b"]]["vat_amount"], ds[ten["b"]]["inv_no_norm"], ds[ten["b"]]["inv_series_norm"]),
			(None, None, None, ""))  # Postgres: inv_series_norm không bao giờ NULL
		# Select trống (chưa khớp) lưu '' qua Document — cổng đọc null
		self.assertEqual(frappe.db.get_value("NPP MISA Snapshot", ten["b"], "cach_khop"), "")
		self.assertEqual((ds[ten["b"]]["match_method"], ds[ten["b"]]["match_confidence"], ds[ten["b"]]["relation"]), (None, None, None))
		# màn đối soát (reconcile/page.tsx): 14 cột, in / eq match_status, order inv_date desc nullslast, limit 500; 6 câu HEAD
		self.assertEqual(len(self._doc("owner", "misa_invoice_snapshots", select="id, ref_id, inv_series, inv_no, inv_date, buyer_name, buyer_tax_code, "
			"total_amount, relation, match_status, match_method, match_confidence, match_note, invoice_id", loc=[{"op": "in", "cot": "match_status",
			"gt": ["misa_only", "needs_review"]}], thu_tu=[{"cot": "inv_date", "tang": False, "null_dau": False}], limit=500)) >= 4, True)
		self.assertGreaterEqual(self._dem("accountant", [{"op": "eq", "cot": "match_status", "gt": "matched"}], bang="misa_invoice_snapshots"), 1)
		for nguoi in ("sales_a", "warehouse"):
			self.assertEqual(self._doc(nguoi, "misa_invoice_snapshots", select="id"), [], nguoi)
		for hd, gt in (("insert", {"ref_id": "x"}), ("update", {"match_status": "matched"}), ("delete", None)):
			self.assertEqual(self._loi(self._ghi("owner", hd, gt, loc=[{"op": "eq", "cot": "id", "gt": ten["a"]}],
				bang="misa_invoice_snapshots"))[0], "42501", hd)
		# I7-like: ghi bị chặn không đổi gì
		self.assertEqual(frappe.db.get_value("NPP MISA Snapshot", ten["a"], "ket_qua_khop"), "matched")

	def test_nhat_ky(self):
		"""(g) `request_payload` của dòng phát hành là MẢNG (gửi đi `json.dumps` chuỗi — §1.2); `created_by` = người bấm (Administrator → null); 13 cột;
		vế đọc chủ / KT / QL; ghi → 42501 (nppsale cho QL sửa / xoá nhật ký — không chép)."""
		hddt = dong_hddt(don_hang=self.don)
		frappe.set_user(self.ma["u:owner"])
		try:
			a = frappe.get_doc({"doctype": "NPP MISA Log", "hddt": hddt, "don_hang": self.don, "nguon": "publish", "ket_qua": "success",
				"gui_di": json.dumps([{"RefID": "R1", "InvSeries": "1C26TAA"}], ensure_ascii=False), "nhan_ve": json.dumps({"Success": True}),
				"misa_lookup_code": None, "misa_inv_no": None}).insert(ignore_permissions=True).name
		finally:
			frappe.set_user("Administrator")
		b = frappe.get_doc({"doctype": "NPP MISA Log", "nguon": "sync_run", "ket_qua": "failed", "loi": "Lượt 1 lỗi: …"}).insert(
			ignore_permissions=True).name
		ds = {r["id"]: r for r in self._doc("accountant", "einvoice_logs", select="*", loc=[{"op": "in", "cot": "id", "gt": [a, b]}])}
		self.assertEqual(list(ds[a]), COT_LOG)
		self.assertEqual((ds[a]["request_payload"], ds[a]["response_payload"], ds[a]["invoice_id"], ds[a]["order_id"], ds[a]["status"],
			ds[a]["created_by"]), ([{"RefID": "R1", "InvSeries": "1C26TAA"}], {"Success": True}, hddt, self.don, "success", self.ma["u:owner"]))
		self.assertIsInstance(ds[a]["request_payload"], list)
		self.assertEqual((ds[b]["created_by"], ds[b]["request_payload"], ds[b]["error_message"], ds[b]["invoice_id"]), (None, None, "Lượt 1 lỗi: …",
			None))
		r = self._doc("manager", "einvoice_logs", select="id, invoice:invoices(id, misa_status), order:sales_orders(id)",
			loc=[{"op": "eq", "cot": "id", "gt": a}], mot="one")  # nhúng theo khoá ngoại
		self.assertEqual((r["invoice"]["id"], r["order"]["id"]), (hddt, self.don))
		for nguoi in ("sales_a", "warehouse"):
			self.assertEqual(self._doc(nguoi, "einvoice_logs", select="id"), [], nguoi)
		for hd, gt in (("insert", {"status": "success"}), ("update", {"status": "failed"}), ("delete", None)):
			self.assertEqual(self._loi(self._ghi("manager", hd, gt, loc=[{"op": "eq", "cot": "id", "gt": a}], bang="einvoice_logs"))[0], "42501", hd)
		self.assertTrue(frappe.db.exists("NPP MISA Log", a))


# ============================================================================================================================ HAI KẾT NỐI
class TestDamBaoDongDocCoKhoa(_NenHoaDon):
	"""Hai lượt song song, kết nối thật thứ hai (khuôn TestKhoaHddtDocCoKhoa — `test_hddt_khoa.py`). Giao dịch REPEATABLE READ chụp ảnh ở câu đọc thường
	đầu tiên (PoC 1d): (1) `dam_bao_dong` phải thấy dòng HĐĐT một lượt bấm khác vừa commit sau ảnh chụp (đọc có khoá) — nếu không là hai dòng cho một
	HĐ; (2) cổng sửa dòng phải đọc bản đã commit mới nhất (`get_doc(for_update=True)`) — đọc theo ảnh chụp rồi `save()` là đè `misa_status` mà bước
	giành tờ của phát hành vừa ghi bằng câu SQL (không đổi `modified`, check_if_latest không bắt). Lớp riêng: không để khoá khoảng của bài khác chặn
	câu chèn của kết nối thứ hai."""

	@contextmanager
	def _ket_noi_hai(self):
		chinh = frappe.local.db
		if getattr(self, "_kn2", None) is None:
			frappe.connect(set_admin_as_user=False)
			self._kn2 = frappe.local.db
			self.addCleanup(self._kn2.close)
		frappe.local.db = self._kn2
		try:
			yield
		finally:
			frappe.local.db = chinh

	def _chen_kn2(self, ten: str, **kv):
		cot = {"name": ten, "owner": "Administrator", "modified_by": "Administrator", "docstatus": 0, "idx": 0, "nguoi_mua": "Tạp hoá A",
			"trang_thai": "draft", **kv}
		with self._ket_noi_hai():
			frappe.db.sql(f"""INSERT INTO `tabNPP HDDT` ({", ".join(f"`{k}`" for k in cot)}, `creation`, `modified`)
				VALUES ({", ".join(["%s"] * len(cot))}, NOW(6), NOW(6))""", tuple(cot.values()))
			frappe.db.commit()

	def _don_dep(self, ten: str):
		frappe.db.rollback()  # nhả khoá của câu đọc có khoá — lui về điểm lưu không nhả khoá dòng
		with self._ket_noi_hai():
			frappe.db.sql("DELETE FROM `tabNPP HDDT` WHERE `name` = %s", ten)
			frappe.db.sql("DELETE FROM `tabVersion` WHERE `ref_doctype` = 'NPP HDDT' AND `docname` = %s", ten)
			frappe.db.commit()
		frappe.db.savepoint("npp_test")  # tearDown lui về điểm này

	def test_luot_song_song_vua_commit(self):
		ten = str(uuid.uuid4())
		frappe.db.sql("SELECT COUNT(*) FROM `tabNPP HDDT`")  # ảnh chụp đã lập từ setUp; câu đọc thường cho chắc
		try:
			self._chen_kn2(ten, hoa_don_ban=self.hd, don_hang=self.don, tien_hang=24000, tien_thue=2020, tong_tien=26020)
			self.assertEqual(frappe.db.sql("SELECT COUNT(*) FROM `tabNPP HDDT` WHERE `hoa_don_ban` = %s", self.hd)[0][0], 0,
				"đọc thường đã thấy dòng của kết nối kia — bài không còn thử được ảnh chụp cũ")
			self.assertEqual(M.dam_bao_dong(self.hd, NguCanh(user=self.ma["u:owner"], vai="owner")), ten)
			self.assertEqual(frappe.db.sql("SELECT COUNT(*) FROM `tabNPP HDDT` WHERE `hoa_don_ban` = %s LOCK IN SHARE MODE", self.hd)[0][0], 1)
		finally:
			self._don_dep(ten)

	def test_cong_sua_khong_de_trang_thai_vua_ghi(self):
		ten = str(uuid.uuid4())
		try:
			self._chen_kn2(ten, misa_status="error", misa_ref_id=str(uuid.uuid4()))
			frappe.db.rollback()  # giao dịch mới: ảnh chụp lập ở câu đọc dưới — thấy dòng ở trạng thái `error`
			self.assertEqual(frappe.db.sql("SELECT `misa_status` FROM `tabNPP HDDT` WHERE `name` = %s", ten)[0][0], "error")
			with self._ket_noi_hai():  # phát hành giành tờ (§4.1.1 bước 9) ở request khác: error → pending, RefID giữ
				frappe.db.sql("UPDATE `tabNPP HDDT` SET `misa_status` = 'pending', `misa_sent_at` = NOW(6), `misa_error` = NULL WHERE `name` = %s", ten)
				frappe.db.commit()
			self.assertEqual(frappe.db.sql("SELECT `misa_status` FROM `tabNPP HDDT` WHERE `name` = %s", ten)[0][0], "error")  # ảnh chụp cũ
			kq = ghi({"bang": "invoices", "hanh_dong": "update", "gia_tri": {"status": "cancelled"}, "loc": [{"op": "eq", "cot": "id", "gt": ten}],
				"select": "id"}, NguCanh(user="Administrator", vai="owner"))
			self.assertEqual(len(kq["data"]), 1)
			self.assertEqual(frappe.db.sql("SELECT `trang_thai`, `misa_status` FROM `tabNPP HDDT` WHERE `name` = %s LOCK IN SHARE MODE", ten)[0],
				("cancelled", "pending"))
		finally:
			self._don_dep(ten)
