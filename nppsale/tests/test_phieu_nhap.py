"""Phiếu nhập NCC (P4 — M1) ngoài kịch bản vàng: luật ghi thẳng phiếu tạm qua cổng (BP §6.1 siết — USE_RPC, câu dòng của §7.3 điểm 23, vai), quan hệ
`purchase_price_lists → purchase_invoices` (🔧 §2.9), đọc `payables` theo vai, mã lô trùng, hàng không lô khi huỷ, gọi xếp repost, giá nhập không tăng phiên
danh mục — cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_phieu_nhap

Dựng trên bộ dữ liệu F của tệp vàng (test_kho_mua_vang.dung_nen_kho).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.tests import test_kho_mua_vang as V
from nppsale.thiet_lap.kho_mua import cai_dat_kho

USE_RPC = "USE_RPC: dùng nút Hoàn thành / Huỷ phiếu / Khôi phục / Lưu sửa"


class TestPhieuNhap(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(V.VANG, encoding="utf-8") as f:
			cls.nen = json.load(f)["nen"]

	def setUp(self):
		frappe.db.savepoint("npp_test")
		self.repost = []
		for p in (patch.object(frappe.db, "commit", lambda *a, **k: None), patch.object(frappe, "log_error", lambda *a, **k: None),
				patch("nppsale.rpc.phieu_nhap._xep_repost", lambda: self.repost.append(1))):
			p.start()
			self.addCleanup(p.stop)
		frappe.local._npp_cai_dat_ban = None
		self.ma = V.dung_nen_kho(self.nen)
		self.cd = cai_dat_kho()

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_cai_dat_ban = None
		frappe.local._npp_ngu_canh = None

	# ------------------------------------------------------------------------------------------------ gọi
	def _vao(self, nguoi):
		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None

	def _ra(self):
		frappe.set_user("Administrator")
		frappe.local._npp_ngu_canh = None
		frappe.local._npp_cai_dat_ban = None

	def _cong(self, nguoi, yc):
		self._vao(nguoi)
		try:
			return api.truy_van(yeu_cau=yc)
		finally:
			self._ra()

	def _rpc(self, nguoi, ten, ts):
		self._vao(nguoi)
		try:
			return api.rpc(ten=ten, tham_so=ts)
		finally:
			self._ra()

	def _phieu(self, nguoi="TK", dong=None, **dau) -> str:
		g = {"org_id": self.ma["org"], "supplier_id": self.ma["S1"], "warehouse_zone": "sale", "discount": 0, "status": "draft", **dau}
		ket = self._cong(nguoi, {"bang": "purchase_invoices", "hanh_dong": "insert", "gia_tri": g, "select": "id"})
		self.assertNotIn("error", ket, ket)
		ten = ket["data"][0]["id"]
		if dong:
			ket = self._dong(nguoi, ten, dong)
			self.assertNotIn("error", ket, ket)
		return ten

	def _dong(self, nguoi, ten, dong):
		return self._cong(nguoi, {"bang": "purchase_invoice_lines", "hanh_dong": "insert", "select": "id",
			"gia_tri": [{"invoice_id": ten, "product_id": self.ma[sp], "unit_name": dv, "quantity": sl, "unit_price": gia, "line_discount": giam,
				"vat_rate": 0, "conversion_factor": hs, "sort_order": i} for i, (sp, dv, sl, gia, giam, hs) in enumerate(dong, 1)]})

	def _loi(self, ket, ma, cau):
		self.assertIn("error", ket, ket)
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), (ma, cau))

	# ------------------------------------------------------------------------------------------------ cổng ghi phiếu tạm
	def test_ghi_thang_chi_phieu_tam(self):
		# lập thẳng phiếu khác nháp → USE_RPC; vai ngoài bốn vai mua hàng → như RLS (42501)
		self._loi(self._cong("TK", {"bang": "purchase_invoices", "hanh_dong": "insert", "gia_tri": {"org_id": self.ma["org"],
			"supplier_id": self.ma["S1"], "status": "completed"}}), "P0001", USE_RPC)
		self._loi(self._cong("NV", {"bang": "purchase_invoices", "hanh_dong": "insert", "gia_tri": {"org_id": self.ma["org"],
			"supplier_id": self.ma["S1"], "status": "draft"}}), "42501", 'new row violates row-level security policy for table "purchase_invoices"')
		self._loi(self._cong("TK", {"bang": "purchase_invoices", "hanh_dong": "insert", "gia_tri": {"org_id": self.ma["org"],
			"supplier_id": self.ma["S1"], "receipt_code": "PN-0999"}}), "P0001", USE_RPC)  # cột của RPC
		ten = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1)])
		self.assertTrue(ten.startswith("PN-"), ten)  # số cấp lúc lập nháp (câu 18)
		loc = [{"op": "eq", "cot": "id", "gt": ten}]
		# đổi trạng thái thẳng → USE_RPC; sửa đầu phiếu tạm được, tiền / thuế dựng lại
		self._loi(self._cong("TK", {"bang": "purchase_invoices", "hanh_dong": "update", "gia_tri": {"status": "completed"}, "loc": loc}),
			"P0001", USE_RPC)
		ket = self._cong("TK", {"bang": "purchase_invoices", "hanh_dong": "update", "select": "id, discount, total, vat, vat_override",
			"gia_tri": {"discount": 5000, "vat_override": 7000, "notes": "ghi chú"}, "loc": loc})
		self.assertEqual({k: ket["data"][0][k] for k in ("discount", "total", "vat", "vat_override")},
			{"discount": 5000, "total": 102000, "vat": 7000, "vat_override": 7000})
		# NVBH: sửa / xoá → 0 dòng (như RLS), đọc → 0 dòng
		self.assertEqual(self._cong("NV", {"bang": "purchase_invoices", "hanh_dong": "update", "select": "id", "gia_tri": {"notes": "x"},
			"loc": loc})["data"], [])
		self.assertEqual(self._cong("NV", {"bang": "purchase_invoices", "select": "id", "loc": loc})["data"], [])
		self.assertEqual(self._cong("NV", {"bang": "purchase_invoice_lines", "select": "id", "loc": [{"op": "eq", "cot": "invoice_id",
			"gt": ten}]})["data"], [])
		# hoàn thành → chỉ còn sửa ghi chú; dòng / đầu phiếu khác / xoá → USE_RPC
		self.assertEqual(self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})["data"], ten)
		self._loi(self._cong("TK", {"bang": "purchase_invoices", "hanh_dong": "update", "gia_tri": {"supplier_id": self.ma["S2"]},
			"loc": loc}), "P0001", USE_RPC)
		self._cong("TK", {"bang": "purchase_invoices", "hanh_dong": "update", "gia_tri": {"notes": "đã kiểm"}, "loc": loc})
		self.assertEqual(frappe.db.get_value("Purchase Invoice", ten, "npp_ghi_chu"), "đã kiểm")
		self._loi(self._dong("TK", ten, [("A", "hộp", 1, 1, 0, 1)]), "P0001", USE_RPC)
		self._loi(self._cong("TK", {"bang": "purchase_invoice_lines", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "invoice_id",
			"gt": ten}]}), "P0001", USE_RPC)
		self._loi(self._cong("TK", {"bang": "purchase_invoices", "hanh_dong": "delete", "loc": loc}), "P0001", USE_RPC)
		# phiếu tạm xoá được (số PN bỏ trống — câu 18)
		q = self._phieu()
		ket = self._cong("TK", {"bang": "purchase_invoices", "hanh_dong": "delete", "select": "id", "loc": [{"op": "eq", "cot": "id", "gt": q}]})
		self.assertEqual(ket["data"], [{"id": q}])
		self.assertFalse(frappe.db.exists("Purchase Invoice", q))
		# soát P4: xoá nháp mang số CUỐI không lùi dãy `PN-` — phiếu lập sau KHÔNG nhận lại đúng tên (id) ấy (màn còn giữ id cũ sẽ chạm phiếu của người
		# khác; nppsale id uuid không dùng lại)
		self.assertNotEqual(self._phieu(), q)

	def test_sua_ngay_hd_phieu_tam(self):
		"""Hạn thanh toán của lõi tính lại mỗi lần lưu: lõi giữ hạn theo lịch thanh toán lập lúc tạo nháp, nên sửa ngày HĐ NCC của phiếu tạm sang SAU
		hạn ấy từng hỏng "Due Date cannot be before Supplier Invoice Date" (nppsale không có hạn cho nợ phiếu nhập); phiếu tạm lập hôm trước,
		hoàn thành hôm nay vẫn được."""
		ten = self._phieu(dong=[("A", "hộp", 5, 1000, 0, 1)], invoice_date=add_days(nowdate(), -5))
		loc = [{"op": "eq", "cot": "id", "gt": ten}]
		ket = self._cong("TK", {"bang": "purchase_invoices", "hanh_dong": "update", "select": "id, invoice_date",
			"gia_tri": {"invoice_date": add_days(nowdate(), 3)}, "loc": loc})
		self.assertEqual(ket.get("data"), [{"id": ten, "invoice_date": add_days(nowdate(), 3)}], ket)
		frappe.db.set_value("Purchase Invoice", ten, "posting_date", add_days(nowdate(), -2))  # nháp lập từ hôm trước
		self.assertEqual(self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten}).get("data"), ten)
		self.assertEqual([str(x) for x in frappe.db.get_value("Purchase Invoice", ten, ["posting_date", "bill_date", "due_date"])],
			[nowdate(), add_days(nowdate(), 3), add_days(nowdate(), 3)])
		# nháp lưu lần cuối hai ngày trước (hạn lõi = max(ngày HĐ, ngày lập) = hôm kia): Hoàn thành tính lại hạn theo ngày ghi sổ mới
		hai = self._phieu(dong=[("B", "gói", 1, 5000, 0, 1)], invoice_date=add_days(nowdate(), -5))
		frappe.db.set_value("Purchase Invoice", hai, {"posting_date": add_days(nowdate(), -2), "due_date": add_days(nowdate(), -2)})
		frappe.db.set_value("Payment Schedule", {"parent": hai}, "due_date", add_days(nowdate(), -2))
		self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": hai})
		self.assertEqual([str(x) for x in frappe.db.get_value("Purchase Invoice", hai, ["docstatus", "posting_date", "due_date"])],
			["1", nowdate(), nowdate()])

	def test_dong_sai_chan_luc_luu(self):
		"""§7.3 điểm 23: lõi không nhận PI nháp dòng SL 0 → cổng chặn bằng câu của sua_phieu_nhap; giá / giảm âm cũng chặn (nppsale không)."""
		ten = self._phieu()
		self._loi(self._dong("TK", ten, [("A", "hộp", 10, 10000, 0, 1), ("B", "gói", 0, 5000, 0, 1)]), "P0001",
			"SO_LUONG_KHONG_HOP_LE: Dòng 2 có số lượng không lớn hơn 0.")
		self._loi(self._dong("TK", ten, [("A", "hộp", 10, -1, 0, 1)]), "P0001", "GIA_KHONG_HOP_LE: Dòng 1 có giá / giảm giá âm.")
		self._loi(self._dong("TK", ten, [("A", "thùng", 1, 1, 0, 0)]), "P0001", "SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0.")
		self._loi(self._dong("TK", ten, [("A", "hộp", 1, 10, -2, 1)]), "P0001", "GIA_KHONG_HOP_LE: Dòng 1 có giá / giảm giá âm.")
		# giảm dòng (tiền) lớn hơn tiền hàng — màn máy tính gửi nguyên số giảm gõ (chỉ kẹp số hiện); lõi không ghi sổ được dòng giá âm (Q9)
		self._loi(self._dong("TK", ten, [("A", "hộp", 10, 10000, 0, 1), ("B", "gói", 1, 10, 20, 1)]), "P0001",
			"GIA_KHONG_HOP_LE: Dòng 2 có giảm giá lớn hơn tiền hàng.")
		self.assertEqual(frappe.db.count("Purchase Invoice Item", {"parent": ten}), 0)  # lời ghi hỏng lui cả lượt
		# dòng giữ thứ tự sort_order; tiền dòng = SL × giá − giảm (giảm là TIỀN cả dòng)
		self._dong("TK", ten, [("D", "thùng", 2, 216000, 12000, 24), ("K", "kg", 2.5, 30000, 0, 1)])
		r = frappe.get_all("Purchase Invoice Item", filters={"parent": ten}, fields=["idx", "item_code", "amount", "rate", "discount_amount",
			"npp_giam_dong", "price_list_rate"], order_by="idx")
		self.assertEqual([(x.idx, x.item_code, flt(x.amount), flt(x.rate), flt(x.discount_amount), flt(x.npp_giam_dong), flt(x.price_list_rate))
			for x in r], [(1, self.ma["D"], 420000, 210000, 6000, 12000, 216000), (2, self.ma["K"], 75000, 30000, 0, 0, 30000)])

	# ------------------------------------------------------------------------------------------------ đọc
	def test_bang_gia_nhap_long_phieu_nhap(self):
		"""🔧 §2.9: `purchase_price_lists → invoice:purchase_invoices(receipt_code)` (thiếu → PGRST200, POS mất giá gợi ý)."""
		ten = self._phieu(dong=[("A", "hộp", 10, 11000, 0, 1)])
		self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		ket = self._cong("TK", {"bang": "purchase_price_lists", "select": "product_id, unit_name, price, invoice:purchase_invoices(receipt_code)",
			"loc": [{"op": "eq", "cot": "product_id", "gt": self.ma["A"]}]})
		self.assertNotIn("error", ket, ket)
		self.assertEqual([(r["price"], r["invoice"]) for r in ket["data"]], [(11000, {"receipt_code": ten})])
		# sửa tay: nguồn bỏ trống; NVBH đọc 0 dòng
		self.assertEqual(self._rpc("KT", "luu_gia_nhap", {"p_dong": [{"product_id": self.ma["A"], "unit_name": "hộp", "price": 12000}]})["data"],
			{"luu": 1, "bo": 0})
		ket = self._cong("KT", {"bang": "purchase_price_lists", "select": "price, source_invoice_id, invoice:purchase_invoices(receipt_code)",
			"loc": [{"op": "eq", "cot": "product_id", "gt": self.ma["A"]}]})
		self.assertEqual(ket["data"], [{"price": 12000, "source_invoice_id": None, "invoice": None}])
		self.assertEqual(self._cong("NV", {"bang": "purchase_price_lists", "select": "id", "loc": [{"op": "eq", "cot": "product_id",
			"gt": self.ma["A"]}]})["data"], [])

	def test_cau_doc_giao_dien(self):
		"""Đúng các câu đọc giao diện nppsale gửi (chuỗi select / lọc / sắp chép từ src/ — đặc tả §4.2, §4.4): không câu nào được hỏng ở cổng
		(PGRST200 / 42703 là màn trắng), số trả về đúng phiếu."""
		p1 = self._phieu(dong=[("A", "thùng", 2, 240000, 0, 24)], invoice_number="HD-1", invoice_date="2026-10-01")
		p2 = self._phieu(supplier_id=self.ma["S2"], dong=[("B", "gói", 10, 5000, 0, 1)])
		for x in (p1, p2):
			self.assertEqual(self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": x})["data"], x)
		p3 = self._phieu(dong=[("B", "gói", 1, 5000, 0, 1)])  # phiếu tạm
		eq = lambda cot, gt: {"op": "eq", "cot": cot, "gt": gt}  # noqa: E731
		# POS nạp phiếu (components/pos/purchase-screen.tsx:313–317)
		r = self._cong("TK", {"bang": "purchase_invoices", "mot": "maybe", "loc": [eq("id", p1)], "select": "id, receipt_code, supplier_id, "
			"invoice_number, invoice_date, warehouse_zone, discount, vat, vat_override, notes, status, supplier:suppliers(name, code), "
			"lines:purchase_invoice_lines(id, product_id, unit_name, quantity, unit_price, line_discount, conversion_factor, notes, "
			"product:products(name, sku))"})
		self.assertNotIn("error", r, r)
		self.assertEqual((r["data"]["receipt_code"], r["data"]["supplier"]["name"], r["data"]["status"], r["data"]["warehouse_zone"]),
			(p1, "NCC Một", "completed", "sale"))
		self.assertEqual([(x["quantity"], x["unit_price"], x["conversion_factor"], x["product"]["name"]) for x in r["data"]["lines"]],
			[(2, 240000, 24, "Hàng A")])
		# chi tiết (purchasing/receipts/[id]/page.tsx:85–90)
		r = self._cong("KT", {"bang": "purchase_invoices", "mot": "maybe", "loc": [eq("id", p1)], "select": "id, receipt_code, invoice_number, "
			"invoice_date, status, warehouse_zone, subtotal, vat, discount, total, notes, cancel_reason, completed_at, stock_entry_id, payable_id, "
			"supplier:suppliers(name, code)"})
		self.assertEqual((r["data"]["invoice_date"], r["data"]["total"], r["data"]["stock_entry_id"], bool(r["data"]["payable_id"])),
			("2026-10-01", 480000, p1, True))
		r = self._cong("KT", {"bang": "purchase_invoice_lines", "loc": [eq("invoice_id", p1)], "thu_tu": [{"cot": "sort_order"}],
			"select": "id, sort_order, unit_name, quantity, unit_price, line_discount, vat_rate, conversion_factor, line_total, notes, "
			"product:products(name, sku, base_unit)"})
		self.assertEqual([(x["sort_order"], x["line_total"], x["product"]["base_unit"]) for x in r["data"]],
			[(1, 480000, frappe.db.get_value("Item", self.ma["A"], "stock_uom"))])
		# danh sách (purchasing/receipts/page.tsx:126–135): org, created_at giảm dần rồi id, đếm đủ
		r = self._cong("QL", {"bang": "purchase_invoices", "count": "exact", "range": [0, 999], "loc": [eq("org_id", self.ma["org"])],
			"thu_tu": [{"cot": "created_at", "tang": False}, {"cot": "id"}], "select": "id, receipt_code, invoice_number, invoice_date, status, "
			"total, warehouse_zone, subtotal, vat, vat_override, discount, notes, created_by, created_at, completed_at, supplier:suppliers(name, code)"})
		cua_bai = [x for x in r["data"] if x["id"] in (p1, p2, p3)]
		self.assertEqual([(x["id"], x["status"], x["created_by"]) for x in cua_bai],
			[(p3, "draft", self.ma["u:TK"]), (p2, "completed", self.ma["u:TK"]), (p1, "completed", self.ma["u:TK"])])
		# báo cáo NCC (reports/suppliers/page.tsx:151–163) — chỉ phiếu hoàn thành trong kỳ, po_id luôn null
		r = self._cong("KT", {"bang": "purchase_invoices", "count": "exact", "range": [0, 999], "thu_tu": [{"cot": "id"}],
			"loc": [eq("org_id", self.ma["org"]), {"op": "gte", "cot": "invoice_date", "gt": "2026-09-01"},
				{"op": "lte", "cot": "invoice_date", "gt": "2026-10-31"}, eq("status", "completed")],
			"select": "id, supplier_id, invoice_number, invoice_date, total, status, po_id"})
		self.assertEqual([(x["id"], x["po_id"]) for x in r["data"] if x["id"] in (p1, p2, p3)], [(p1, None)])
		# phiếu gốc khi trả NCC (lib/pos/load.ts:254–275)
		r = self._cong("TK", {"bang": "purchase_invoices", "limit": 50, "loc": [eq("supplier_id", self.ma["S1"]), eq("status", "completed")],
			"thu_tu": [{"cot": "invoice_date", "tang": False}], "select": "id, receipt_code, invoice_date"})
		self.assertIn({"id": p1, "receipt_code": p1, "invoice_date": "2026-10-01"}, r["data"])
		self.assertNotIn(p3, [x["id"] for x in r["data"]])
		# sổ nợ NCC tra ngược phiếu theo khoản nợ (lib/payables/so-no-ncc.ts:171)
		no1 = frappe.db.get_value("NPP Cong No NCC", {"chung_tu": p1}, "name")
		r = self._cong("KT", {"bang": "purchase_invoices", "count": "exact", "range": [0, 999], "thu_tu": [{"cot": "id"}],
			"loc": [{"op": "in", "cot": "payable_id", "gt": [no1]}], "select": "id, payable_id, receipt_code"})
		self.assertEqual(r["data"], [{"id": p1, "payable_id": no1, "receipt_code": p1}])
		# ô tìm /payables tra mã phiếu nhập → khoản nợ (lib/search/list-search.ts:259–266)
		r = self._cong("KT", {"bang": "purchase_invoices", "limit": 201, "thu_tu": [{"cot": "payable_id"}], "select": "payable_id",
			"loc": [{"op": "or", "bieu_thuc": f"receipt_code.ilike.*{p1}*"}, eq("org_id", self.ma["org"])]})
		self.assertEqual(r["data"], [{"payable_id": no1}])

	def test_cong_no_ncc_sap_theo_ten_ncc(self):
		"""§4.1: `/payables` sắp theo cột bảng lồng nhiều-một `.order('supplier(name)')` (SAP_XEP_CONG_NO_NCC) — thiếu thì bấm cột "Nhà cung cấp"
		là màn báo 42703. Bảng lồng không có trong select → PGRST108 như PostgREST."""
		p1 = self._phieu(dong=[("A", "hộp", 1, 10000, 0, 1)])
		p2 = self._phieu(supplier_id=self.ma["S2"], dong=[("B", "gói", 1, 5000, 0, 1)])
		for x in (p1, p2):
			self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": x})
		ncc = [self.ma["S1"], self.ma["S2"]]
		chon = "id, invoice_number, amount, paid, due_date, status, opening_balance, supplier:suppliers(name, code)"
		for tang, mong in ((True, ["NCC Hai", "NCC Một"]), (False, ["NCC Một", "NCC Hai"])):
			r = self._cong("CHU", {"bang": "payables", "select": chon, "count": "exact", "range": [0, 49],
				"loc": [{"op": "in", "cot": "supplier_id", "gt": ncc}],
				"thu_tu": [{"cot": "supplier(name)", "tang": tang, "null_dau": False}, {"cot": "due_date"}, {"cot": "id"}]})
			self.assertNotIn("error", r, r)
			self.assertEqual(([x["supplier"]["name"] for x in r["data"]], r["count"]), (mong, 2), tang)
		r = self._cong("CHU", {"bang": "payables", "select": "id, amount", "thu_tu": [{"cot": "supplier(name)"}]})
		self.assertEqual((r["error"]["code"], r["error"]["message"]), ("PGRST108", "'supplier' is not an embedded resource in this request"))
		# bốn ô tổng (payables/page.tsx:104–110): khoản chưa trả, không kẹp
		r = self._cong("KT", {"bang": "payables", "count": "exact", "range": [0, 999], "thu_tu": [{"cot": "id"}],
			"loc": [{"op": "neq", "cot": "status", "gt": "paid"}, {"op": "in", "cot": "supplier_id", "gt": ncc}],
			"select": "amount, paid, due_date, supplier_id, status"})
		self.assertEqual(sorted(x["amount"] for x in r["data"]), [5000, 10000])

	def test_cong_no_ncc_doc_theo_vai(self):
		ten = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1)], invoice_number="HD-9")
		self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		chon = {"bang": "payables", "select": "amount, paid, status, invoice_number, opening_balance, supplier:suppliers(name)",
			"loc": [{"op": "eq", "cot": "supplier_id", "gt": self.ma["S1"]}]}
		mong = [{"amount": 100000, "paid": 0, "status": "open", "invoice_number": "HD-9", "opening_balance": False,
			"supplier": {"name": "NCC Một"}}]
		for nguoi in ("CHU", "QL", "KT"):
			self.assertEqual(self._cong(nguoi, chon)["data"], mong, nguoi)
		for nguoi in ("TK", "NV"):  # RLS mig 034: thủ kho / NVBH 0 dòng
			self.assertEqual(self._cong(nguoi, chon)["data"], [], nguoi)
		pn = self._cong("QL", {"bang": "purchase_invoices", "select": "payable_id, payable:payables(amount)", "loc": [{"op": "eq", "cot": "id",
			"gt": ten}]})["data"][0]
		self.assertEqual(pn["payable"], {"amount": 100000})

	# ------------------------------------------------------------------------------------------------ RPC
	def test_ma_lo_trung_khong_nhap(self):
		ten = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1)])
		frappe.get_doc({"doctype": "Batch", "batch_id": f"{ten}-001", "item": self.ma["A"]}).insert(ignore_permissions=True)
		self._loi(self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten}), "P0001",
			f"LO_TRUNG_MA: Mã lô {ten}-001 đã có trong sổ — đổi mã lô ấy rồi hoàn thành lại phiếu.")
		self.assertEqual(frappe.db.get_value("Purchase Invoice", ten, "docstatus"), 0)

	def test_huy_hang_khong_lo(self):
		"""Hàng KHÔNG lô X: bán bớt rồi huỷ PN — cờ bán vượt tồn tắt → HANG_DA_XUAT (câu nppsale); mặt hàng không cho âm mà cờ bật → vẫn chặn (câu
		§7.3 điểm 12); cho âm + cờ bật → huỷ được, Bin âm (V12b)."""
		ten = self._phieu(dong=[("X", "cai", 48, 10000, 0, 1)])
		self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		self.assertFalse(frappe.db.exists("Batch", {"reference_name": ten}))  # hàng không lô: không lô
		frappe.db.set_value("Bin", {"item_code": self.ma["X"], "warehouse": self.cd.kho_ban}, "actual_qty", 18)  # như đã bán 30
		self._loi(self._rpc("TK", "cancel_purchase_invoice", {"p_invoice_id": ten, "p_reason": "x"}), "P0001",
			"HANG_DA_XUAT: Không huỷ được vì hàng của phiếu đã xuất bớt — Hàng không lô (nhập 48.000000, còn 18.000000). Lập phiếu trả hàng NCC "
			"hoặc phiếu điều chỉnh kho — hoặc bật \"Cho phép bán vượt tồn kho\" (Cài đặt › Đơn vị) để huỷ: phần đã xuất thành tồn âm.")
		frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 1)
		frappe.db.set_value("Item", self.ma["X"], "allow_negative_stock", 0)
		self._loi(self._rpc("TK", "cancel_purchase_invoice", {"p_invoice_id": ten, "p_reason": "x"}), "P0001",
			"HANG_DA_XUAT: Không huỷ được vì hàng của phiếu đã xuất bớt — Hàng không lô (nhập 48.000000, còn 18.000000). Lập phiếu trả hàng NCC "
			"hoặc phiếu điều chỉnh kho.")
		self.assertEqual(self.repost, [])

	def test_huy_hang_khong_lo_gop_dong_cung_hang(self):
		"""Hai dòng cùng mặt hàng không lô trong một phiếu: Bin là MỘT số cho cả kho → so với TỔNG nhập (20), không từng dòng (10 — mỗi dòng
		"đủ" một mình mà cả phiếu thiếu)."""
		ten = self._phieu(dong=[("X", "cai", 10, 10000, 0, 1), ("X", "cai", 10, 12000, 0, 1)])
		self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		frappe.db.set_value("Bin", {"item_code": self.ma["X"], "warehouse": self.cd.kho_ban}, "actual_qty", 15)  # như đã bán 5
		self._loi(self._rpc("TK", "cancel_purchase_invoice", {"p_invoice_id": ten, "p_reason": "x"}), "P0001",
			"HANG_DA_XUAT: Không huỷ được vì hàng của phiếu đã xuất bớt — Hàng không lô (nhập 20.000000, còn 15.000000). Lập phiếu trả hàng NCC "
			"hoặc phiếu điều chỉnh kho — hoặc bật \"Cho phép bán vượt tồn kho\" (Cài đặt › Đơn vị) để huỷ: phần đã xuất thành tồn âm.")
		self.assertEqual(frappe.db.get_value("Purchase Invoice", ten, "docstatus"), 1)

	def test_huy_tat_lo_xep_repost_khoi_phuc_mo_lai(self):
		ten = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1), ("C", "chai", 2, 15000, 0, 1)], notes="ghi chú phiếu", invoice_number="HD-77",
			invoice_date=add_days(nowdate(), -3), discount=5000, vat_override=8000)
		self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		cot = ("supplier_id, invoice_number, invoice_date, warehouse_zone, subtotal, vat, vat_override, discount, total, notes, created_by, "
			"created_at, completed_at, lines:purchase_invoice_lines(sort_order, product_id, unit_name, quantity, unit_price, line_discount, vat_rate, "
			"conversion_factor, line_total)")
		doc_dau = lambda x: self._cong("KT", {"bang": "purchase_invoices", "mot": "maybe", "select": cot,  # noqa: E731
			"loc": [{"op": "eq", "cot": "id", "gt": x}]})["data"]
		truoc = doc_dau(ten)
		self.assertEqual((truoc["notes"], truoc["total"], len(truoc["lines"])), ("ghi chú phiếu", 133000, 2))
		lo = [f"{ten}-001", f"{ten}-002"]
		self.assertEqual([frappe.db.get_value("Batch", x, ["npp_kho_tao", "npp_gia_von_lo_rong"]) for x in lo],
			[(self.cd.kho_ban, 10000), (self.cd.kho_can_date, 15000)])  # lô hạn ngắn vào kho cận date; giá vốn lô rỗng (§7.3 điểm 35)
		self.assertEqual(self._rpc("TK", "cancel_purchase_invoice", {"p_invoice_id": ten, "p_reason": "x"})["data"], ten)
		self.assertEqual([frappe.db.get_value("Batch", x, "disabled") for x in lo], [1, 1])
		self.assertEqual(len(self.repost), 1)  # CFD-07
		r = self._rpc("TK", "khoi_phuc_phieu_nhap", {"p_invoice_id": ten})["data"]
		self.assertEqual(r, {"id": f"{ten}-1", "trang_thai": "completed", "da_khoi_phuc": True, "so_lo": 2})
		self.assertEqual([frappe.db.get_value("Batch", x, "disabled") for x in lo], [0, 0])
		self.assertEqual(len(self.repost), 2)  # ghi lùi về giờ gốc
		# trang cũ của tờ gốc bấm lại: id ổn định — làm trên tờ cuối của chuỗi
		self.assertEqual(self._rpc("TK", "khoi_phuc_phieu_nhap", {"p_invoice_id": ten})["data"],
			{"id": f"{ten}-1", "trang_thai": "completed", "da_khoi_phuc": False, "so_lo": 0})
		self.assertEqual(self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})["data"], f"{ten}-1")
		self.assertEqual(frappe.db.get_value("Purchase Invoice", f"{ten}-1", ["npp_kho_nhap", "set_warehouse"]), (self.cd.kho_ban, None))
		# tờ khôi phục ghi sổ đúng NGÀY + GIỜ gốc (thẻ kho giữ chỗ cũ — nppsale đặt lại phiếu kho `posted` giữ `posted_at`), mốc hoàn thành gốc
		goc, moi = (frappe.db.get_value("Purchase Invoice", x, ["posting_date", "posting_time", "npp_hoan_thanh_luc"]) for x in (ten, f"{ten}-1"))
		self.assertEqual([str(x) for x in moi], [str(x) for x in goc])
		# đầu phiếu + dòng giữ nguyên như nppsale (khôi phục không tính lại tiền) — kể cả ghi chú phiếu (`npp_ghi_chu` no_copy) và ngày HĐ NCC
		sau = doc_dau(f"{ten}-1")
		sau["lines"].sort(key=lambda x: x["sort_order"])
		truoc["lines"].sort(key=lambda x: x["sort_order"])
		self.assertEqual(sau, truoc)

	def test_khoa_theo_chuoi_amend(self):
		"""Tên BẤT KỲ tờ nào của chuỗi amend → làm trên tờ CUỐI: bước chuẩn bị (đọc thường — khoá Bin đúng mặt hàng của tờ cuối) VÀ lúc khoá (đi
		tiếp theo `amended_from` dưới khoá — tờ amend lập đúng lúc giữa hai bước)."""
		from nppsale.rpc import phieu_nhap as P

		ten = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1)])
		self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		self._rpc("TK", "cancel_purchase_invoice", {"p_invoice_id": ten, "p_reason": "x"})
		self._rpc("TK", "khoi_phuc_phieu_nhap", {"p_invoice_id": ten})
		P._chuan_bi_pn(ten)
		self.assertEqual(frappe.local._npp_pn, (ten, f"{ten}-1", {self.ma["A"]}, {self.ma["S1"]}))  # + NCC: khoá ngay sau Bin (soát P4)
		self.assertEqual(P._da_chuan_bi(ten), (f"{ten}-1", {self.ma["A"]}, {self.ma["S1"]}))
		self.assertIsNone(frappe.local._npp_pn)  # dùng một lần
		r = P._khoa(ten, set(), self.cd)  # tên cũ đưa thẳng vào bước khoá (như tờ amend vừa lập sau bước chuẩn bị)
		self.assertEqual((r.name, r.docstatus), (f"{ten}-1", 1))
		self.assertIsNone(P._khoa("PN-KHONG-CO", set(), self.cd))

	def test_huy_vai(self):
		"""Cửa vai của cancel_purchase_invoice (mig 166): ngoài bốn vai mua hàng → FORBIDDEN 42501, KỂ CẢ phiếu tạm; quản lý / kế toán huỷ được."""
		cau = "FORBIDDEN: vai trò của bạn không được làm thao tác kho / mua hàng này."
		tam = self._phieu(dong=[("A", "hộp", 1, 10000, 0, 1)])
		xong = self._phieu(dong=[("B", "gói", 1, 5000, 0, 1)])
		self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": xong})
		for x in (tam, xong):
			self._loi(self._rpc("NV", "cancel_purchase_invoice", {"p_invoice_id": x, "p_reason": "x"}), "42501", cau)
		self.assertEqual([frappe.db.get_value("Purchase Invoice", x, ["docstatus", "npp_huy_luc"]) for x in (tam, xong)], [(0, None), (1, None)])
		self.assertEqual(self._rpc("QL", "cancel_purchase_invoice", {"p_invoice_id": tam, "p_reason": None})["data"], tam)
		self.assertEqual(self._rpc("KT", "cancel_purchase_invoice", {"p_invoice_id": xong, "p_reason": "y"})["data"], xong)
		self._loi(self._rpc("NV", "cancel_purchase_invoice", {"p_invoice_id": "PN-KHONG-CO"}), "P0001",
			"PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu nhập này.")  # không thấy phiếu báo trước cửa vai (thứ tự nppsale)

	def test_gia_nhap_khong_tang_phien(self):
		"""Bảng giá nhập không phải nguồn tăng phiên danh mục bán (BP — `thay_doi_gia_ban` chỉ dòng bán)."""
		from nppsale.su_kien.san_pham import tang_phien_danh_muc

		with patch("nppsale.su_kien.san_pham.tang_phien_danh_muc", wraps=tang_phien_danh_muc) as tang:
			ten = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1)])
			self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
			self._rpc("KT", "luu_gia_nhap", {"p_dong": [{"product_id": self.ma["A"], "unit_name": "thùng", "price": 240000},
				{"product_id": self.ma["A"], "unit_name": "hộp", "price": None}]})
		self.assertEqual(tang.call_count, 0)

	def test_luu_gia_nhap_mot_luot(self):
		"""Lỗi ở phần tử sau → lui cả lượt (giá phần tử trước không ghi)."""
		ket = self._rpc("KT", "luu_gia_nhap", {"p_dong": [{"product_id": self.ma["A"], "unit_name": "thùng", "price": 240000},
			{"product_id": self.ma["A"], "unit_name": "lốc", "price": 1}]})
		self._loi(ket, "P0001", 'GIA_NHAP_SAI: mặt hàng / đơn vị "lốc" không có trong danh mục')
		self.assertFalse(frappe.db.exists("Item Price", {"item_code": self.ma["A"], "price_list": self.cd.bang_gia_nhap}))
		self._loi(self._rpc("KT", "luu_gia_nhap", {"p_dong": [{"product_id": "KHONG-CO", "unit_name": "hộp", "price": 1}]}), "P0001",
			'GIA_NHAP_SAI: mặt hàng / đơn vị "hộp" không có trong danh mục')
		self._loi(self._rpc("KT", "luu_gia_nhap", {"p_dong": {"product_id": self.ma["A"]}}), "P0001", "GIA_NHAP_SAI: cần danh sách dòng giá")

	def test_hoan_thanh_dong_sl_0_ghi_thang_so(self):
		"""Dòng SL 0 lọt vào nháp bằng đường ngoài cổng (dữ liệu chuyển sang / Desk) → Hoàn thành báo đúng câu nppsale với THỨ TỰ dòng (1-based), không
		lô / nợ / sổ kho; tiền dòng âm lọt như thế → câu của cổng (Q9), sau mọi lỗi SL."""
		ten = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1), ("B", "gói", 5, 5000, 0, 1)])
		frappe.db.set_value("Purchase Invoice Item", {"parent": ten, "idx": 2}, "qty", 0)
		# dòng 1 tiền âm (giảm > tiền hàng) cũng lọt: lỗi SL của dòng 2 vẫn ra TRƯỚC (nppsale chỉ có lỗi SL)
		frappe.db.set_value("Purchase Invoice Item", {"parent": ten, "idx": 1}, "npp_giam_dong", 100001)
		self._loi(self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten}), "P0001",
			"SO_LUONG_KHONG_HOP_LE: Dòng 2 có số lượng không lớn hơn 0.")
		self.assertEqual((frappe.db.count("Batch", {"reference_name": ten}), frappe.db.count("NPP Cong No NCC", {"chung_tu": ten})), (0, 0))
		# hết lỗi SL → tiền dòng âm báo câu của cổng (lõi sẽ từ chối dòng `rate` âm bằng câu tiếng Anh lúc ghi sổ)
		frappe.db.set_value("Purchase Invoice Item", {"parent": ten, "idx": 2}, "qty", 5)
		self._loi(self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten}), "P0001",
			"GIA_KHONG_HOP_LE: Dòng 1 có giảm giá lớn hơn tiền hàng.")
		self.assertEqual(frappe.db.get_value("Purchase Invoice", ten, "docstatus"), 0)

	def _phieu_chi(self, tien) -> str:
		"""Phiếu chi trả NCC `PCNCC-` (S1, tiền mặt) lập thẳng — `chi_tra_ncc` dựng ở M3."""
		pe = frappe.new_doc("Payment Entry")
		pe.update({"naming_series": "PCNCC-.####", "payment_type": "Pay", "company": self.cd.cong_ty, "mode_of_payment": self.cd.hinh_thuc["cash"],
			"party_type": "Supplier", "party": self.ma["S1"], "npp_loai": "phieu_chi_ncc", "paid_amount": tien, "received_amount": tien,
			"paid_from": frappe.get_cached_value("Company", self.cd.cong_ty, "default_cash_account"),
			"paid_to": frappe.get_cached_value("Company", self.cd.cong_ty, "default_payable_account"), "source_exchange_rate": 1,
			"target_exchange_rate": 1})
		pe.flags.ignore_permissions = True
		pe.insert()
		pe.submit()
		return pe.name

	@staticmethod
	def _no(pi):
		r = frappe.db.get_value("NPP Cong No NCC", {"chung_tu": pi}, ["so_tien", "da_tra", "trang_thai"], as_dict=True)
		return (flt(r.so_tien), flt(r.da_tra), r.trang_thai) if r else None

	def test_hoan_thanh_va_khoi_phuc_don_tra_truoc(self):
		"""§2.8 / mig 242 (`trg_tra_truoc_vao_no_moi`): tiền phiếu chi NCC trả trước (chưa có khoản nợ) dồn vào khoản nợ MỚI lúc Hoàn thành phiếu
		nhập; huỷ phiếu trả tiền về trả trước; khôi phục (tờ amend ghi sổ) dồn lại."""
		pe = self._phieu_chi(60000)
		self.assertEqual(frappe.db.get_value("NPP Cong No NCC", {"phieu_chi": pe}, "da_tra"), 60000)  # dòng trả trước
		pn = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1)])
		self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": pn})
		self.assertEqual(self._no(pn), (100000, 60000, "partial"))
		self.assertFalse(frappe.db.exists("NPP Cong No NCC", {"phieu_chi": pe}))  # dồn hết
		self._rpc("TK", "cancel_purchase_invoice", {"p_invoice_id": pn, "p_reason": "x"})
		self.assertEqual((self._no(pn), frappe.db.get_value("NPP Cong No NCC", {"phieu_chi": pe}, "da_tra")), (None, 60000))
		moi = self._rpc("TK", "khoi_phuc_phieu_nhap", {"p_invoice_id": pn})["data"]["id"]
		self.assertEqual((moi, self._no(moi)), (f"{pn}-1", (100000, 60000, "partial")))
		self.assertFalse(frappe.db.exists("NPP Cong No NCC", {"phieu_chi": pe}))

	def test_huy_tien_phieu_chi_don_sang_no_khac(self):
		"""mig 242: phần phiếu chi NCC đã trừ vào phiếu → lõi gỡ khi huỷ, method dồn sang khoản nợ khác còn mở của NCC (cũ nhất trước)."""
		from nppsale.su_kien import cong_no_ncc as N

		pn1 = self._phieu(dong=[("A", "hộp", 6, 10000, 0, 1)])
		pn2 = self._phieu(dong=[("B", "gói", 12, 5000, 0, 1)])
		for x in (pn1, pn2):
			self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": x})
		pe = self._phieu_chi(60000)
		N.don_tra_truoc_ncc(self.ma["S1"])
		so = self._no
		self.assertEqual((so(pn1), so(pn2)), ((60000, 60000, "paid"), (60000, 0, "open")))
		self.assertEqual(self._rpc("TK", "cancel_purchase_invoice", {"p_invoice_id": pn1, "p_reason": "x"})["data"], pn1)
		self.assertEqual((so(pn1), so(pn2)), (None, (60000, 60000, "paid")))
		self.assertFalse(frappe.db.exists("NPP Cong No NCC", {"phieu_chi": pe}))  # dồn hết — không còn dòng trả trước

	# ------------------------------------------------------------------------------------------------ soát P4
	def test_khoi_phuc_lap_dong_no_moi(self):
		"""Soát P4: khôi phục phiếu nhập đã huỷ lập dòng công nợ MỚI như nppsale (`khoi_phuc_phieu_nhap.sql:71–74` — `open`, hạn NULL, chữ hệ thống
		"Phiếu nhập hàng …"): dấu quá hạn tay / hạn / ghi chú nợ mà màn công nợ NCC đặt cho tờ CŨ không đi theo tờ amend; `payables_by_supplier` không
		đếm quá hạn. Số HĐ NCC giữ (nppsale chép `invoice_number` của phiếu)."""
		ten = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1)], invoice_number="HD-K1")
		self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		no = frappe.db.get_value("NPP Cong No NCC", {"chung_tu": ten}, "name")
		ket = self._cong("KT", {"bang": "payables", "hanh_dong": "update", "select": "id", "loc": [{"op": "eq", "cot": "id", "gt": no}],
			"gia_tri": {"status": "overdue", "due_date": str(add_days(nowdate(), 10)), "notes": "hẹn trả"}})
		self.assertNotIn("error", ket, ket)
		self.assertEqual(frappe.db.get_value("NPP Cong No NCC", no, ["trang_thai", "ghi_chu"]), ("overdue", "hẹn trả"))
		self._rpc("TK", "cancel_purchase_invoice", {"p_invoice_id": ten, "p_reason": "x"})
		moi = self._rpc("TK", "khoi_phuc_phieu_nhap", {"p_invoice_id": ten})["data"]["id"]
		r = frappe.db.get_value("NPP Cong No NCC", {"chung_tu": moi}, ["trang_thai", "han_thanh_toan", "ghi_chu", "qua_han_tay", "so_hd_ncc"],
			as_dict=True)
		self.assertEqual((r.trang_thai, r.han_thanh_toan, r.ghi_chu, r.qua_han_tay, r.so_hd_ncc), ("open", None, f"Phiếu nhập hàng {moi}", 0, "HD-K1"))
		ds = self._rpc("KT", "payables_by_supplier", {})["data"]
		self.assertEqual(next(x for x in ds if x["supplier_id"] == self.ma["S1"])["overdue_count"], 0)

	def test_gio_ghi_so_du_micro_giay(self):
		"""Soát P4: Hoàn thành ghi giờ ghi sổ đủ micro giây như mọi RPC kho (trả NCC, phiếu kho tay, kiểm kê, rà soát; HĐ P3 `nowtime()`) — cắt về giây
		là phiếu đứng TRƯỚC chứng từ đã ghi trong cùng giây → lõi coi là ghi lùi, xếp repost, giá vốn chứng từ đã chốt đổi; khôi phục giữ đúng giờ ấy."""
		from nppsale.rpc import phieu_nhap as P

		ten = self._phieu(dong=[("A", "hộp", 1, 10000, 0, 1)])
		luc = now_datetime().replace(microsecond=654321)
		with patch.object(P, "now_datetime", lambda: luc):
			self.assertEqual(self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})["data"], ten)
		self.assertEqual(str(frappe.db.get_value("Purchase Invoice", ten, "posting_time")), luc.strftime("%-H:%M:%S.654321"))
		self._rpc("TK", "cancel_purchase_invoice", {"p_invoice_id": ten, "p_reason": "x"})
		moi = self._rpc("TK", "khoi_phuc_phieu_nhap", {"p_invoice_id": ten})["data"]["id"]
		self.assertEqual(str(frappe.db.get_value("Purchase Invoice", moi, "posting_time")), luc.strftime("%-H:%M:%S.654321"))

	def _cau_than(self, ham, ts, nguoi="TK") -> tuple[dict, list[str]]:
		"""(kết quả RPC, mọi câu SQL của thân hàm — sau điểm lưu `npp_cong_rpc` của lượt cuối)."""
		cau, moc = [], []
		goc_sql, goc_sp = frappe.db.sql, frappe.db.savepoint

		def ghi_sql(q, *a, **kw):
			cau.append(" ".join(str(q).split()))
			return goc_sql(q, *a, **kw)

		def ghi_sp(ten_sp, *a, **kw):
			kq = goc_sp(ten_sp, *a, **kw)
			if ten_sp == "npp_cong_rpc":
				moc.append(len(cau))
			return kq

		with patch.object(frappe.db, "sql", ghi_sql), patch.object(frappe.db, "savepoint", ghi_sp):
			ket = self._rpc(nguoi, ham, ts)
		return ket, cau[moc[-1]:] if moc else []

	def test_khoa_bin_ncc_pi_truoc_doc_thuong(self):
		"""Soát P4 (CFD-05, PoC 1d): thân Hoàn thành / Huỷ / Khôi phục phiếu nhập khoá Bin → khoá NCC → khoá PI (cùng thứ tự NCC trước PI với Ghi trả /
		phiếu chi / cổng `payables` — không khoá chết ngược chiều; hook chiếu công nợ NCC không chạy trên ảnh chụp cũ), câu đọc mặt hàng sau khoá PI là
		đọc CÓ KHOÁ (khoá Bin bù của hàng mới trước ảnh chụp) — không câu đọc thường nào trước đó."""
		ten = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1)])
		for ham, ts in (("complete_purchase_invoice", {"p_invoice_id": ten}), ("cancel_purchase_invoice", {"p_invoice_id": ten, "p_reason": "x"}),
				("khoi_phuc_phieu_nhap", {"p_invoice_id": ten})):
			ket, than = self._cau_than(ham, ts)
			self.assertNotIn("error", ket, ket)
			self.assertTrue("`tabBin`" in than[0] and "FOR UPDATE" in than[0], (ham, than[:1]))
			self.assertTrue("`tabSupplier`" in than[1] and "FOR UPDATE" in than[1], (ham, than[1]))
			self.assertTrue("`tabPurchase Invoice`" in than[2] and "FOR UPDATE" in than[2], (ham, than[2]))
			i = next(k for k, q in enumerate(than) if "`tabPurchase Invoice Item`" in q)
			self.assertIn("LOCK IN SHARE MODE", than[i], ham)
			self.assertTrue(all("FOR UPDATE" in q or "LOCK IN SHARE MODE" in q for q in than[:i + 1]), (ham, than[:i + 1]))

	def test_ncc_doi_giua_chuan_bi_va_khoa_thu_lai(self):
		"""Soát P4: NCC của tờ đổi giữa bước chuẩn bị và lúc khoá (gộp NCC / sửa nháp song song) → lui `QueryDeadlockError`, cổng thử lại từ bước chuẩn
		bị (đọc lại NCC — khoá đúng NCC, đúng thứ tự) rồi làm xong."""
		from nppsale.rpc import phieu_nhap as P

		ten = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1)])
		with self.assertRaises(frappe.QueryDeadlockError):
			P._khoa(ten, {self.ma["A"]}, self.cd, {self.ma["S2"]})
		goc_ncc, goc_lui, lan = P._ncc_cua, frappe.db.rollback, []

		def ncc_cu(t):
			lan.append(t)
			return {self.ma["S2"]} if len(lan) == 1 else goc_ncc(t)

		def lui(*, save_point=None, chain=False):  # "lui hẳn" của cổng — trong bài: về điểm lưu của lượt (giữ dữ liệu bài)
			return goc_lui(save_point=save_point or "npp_cong_rpc")

		with patch.object(P, "_ncc_cua", ncc_cu), patch.object(frappe.db, "rollback", lui), patch("time.sleep"):
			ket = self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		self.assertEqual((ket.get("data"), len(lan)), (ten, 2), ket)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", ten, "docstatus"), 1)

	def test_cong_khoa_chet_thu_lai(self):
		"""Soát P4: khoá chết trong lời ghi thường của cổng / RPC không qua khuôn ghi kho — InnoDB lui CẢ giao dịch (điểm lưu mất: lui về nó hỏng 1305
		ngay trong nhánh bắt lỗi → 500 "Lỗi máy chủ…"): cổng lui hẳn rồi thử lại có giãn cách như khuôn ghi kho; hết lượt → 503 `40P01`."""
		from nppsale.cong import api as A
		from nppsale.rpc import phieu_nhap as P

		goc_ghi, goc_lui, goc_khoa = A._ghi, frappe.db.rollback, P._khoa_hang_gia
		lan, lui = [], []

		def ghi_hong(yc, nc, *a):
			lan.append(1)
			if len(lan) == 1:
				raise frappe.QueryDeadlockError("khoá chết giả")
			return goc_ghi(yc, nc, *a)

		def lui_ve(diem):
			def f(*, save_point=None, chain=False):
				lui.append(save_point)
				return goc_lui(save_point=save_point or diem)
			return f

		with patch.object(A, "_ghi", ghi_hong), patch.object(frappe.db, "rollback", lui_ve("npp_cong_ghi")), patch("time.sleep"):
			ten = self._phieu()
		self.assertEqual((len(lan), lui, frappe.db.get_value("Purchase Invoice", ten, "npp_loai")), (2, [None], "phieu_nhap"))

		def luon_hong(*a):
			raise frappe.QueryDeadlockError("khoá chết giả")

		with patch.object(A, "_ghi", luon_hong), patch.object(frappe.db, "rollback", lui_ve("npp_cong_ghi")), patch("time.sleep"):
			ket = self._cong("TK", {"bang": "purchase_invoices", "hanh_dong": "insert", "select": "id", "gia_tri": {"org_id": self.ma["org"],
				"supplier_id": self.ma["S1"], "status": "draft"}})
		self.assertEqual((ket.get("status"), ket.get("error", {}).get("code")), (503, "40P01"), ket)
		# RPC thường (không khuôn ghi kho): `luu_gia_nhap`
		lan.clear()

		def khoa_hong(ds):
			lan.append(1)
			if len(lan) == 1:
				raise frappe.QueryDeadlockError("khoá chết giả")
			return goc_khoa(ds)

		with patch.object(P, "_khoa_hang_gia", khoa_hong), patch.object(frappe.db, "rollback", lui_ve("npp_cong_rpc")), patch("time.sleep"):
			ket = self._rpc("KT", "luu_gia_nhap", {"p_dong": [{"product_id": self.ma["A"], "unit_name": "thùng", "price": 240000}]})
		self.assertEqual((ket.get("data"), len(lan)), ({"luu": 1, "bo": 0}, 2), ket)

	def test_ghi_gia_nhap_khoa_hang(self):
		"""Soát P4 (§2.9 MỘT Item Price mỗi (mặt hàng, đơn vị)): `luu_gia_nhap` và bước ghi giá khi Hoàn thành phiếu khoá dòng Item của các mặt hàng
		(thứ tự tên) TRƯỚC khi đọc giá, đọc giá CÓ KHOÁ — hai lượt cùng (mặt hàng, đơn vị) chưa có giá xếp hàng và lượt sau thấy giá lượt trước vừa chèn
		(sửa tại chỗ), thay vì cùng thấy "chưa có" rồi cùng chèn."""
		ten = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1)])
		for nguoi, ham, ts in (("TK", "complete_purchase_invoice", {"p_invoice_id": ten}),
				("KT", "luu_gia_nhap", {"p_dong": [{"product_id": self.ma["A"], "unit_name": "hộp", "price": 11000}]})):
			ket, than = self._cau_than(ham, ts, nguoi)
			self.assertNotIn("error", ket, ket)
			khoa = next(k for k, q in enumerate(than) if "`tabItem`" in q and "FOR UPDATE" in q)
			doc = [k for k, q in enumerate(than) if q.startswith("SELECT `name`, `valid_from` FROM `tabItem Price`")]
			self.assertTrue(doc and khoa < doc[0], ham)
			self.assertTrue(all("FOR UPDATE" in than[k] for k in doc), ham)
		self.assertEqual(frappe.get_all("Item Price", filters={"price_list": self.cd.bang_gia_nhap, "item_code": self.ma["A"]},
			fields=["uom", "price_list_rate"]), [{"uom": frappe.db.get_value("Purchase Invoice Item", {"parent": ten}, "uom"), "price_list_rate": 11000}])

	def test_lo_trung_ma_luot_song_song(self):
		"""Soát P4: lô cùng mã vừa được lập song song SAU bước kiểm `exists` (khác mặt hàng — khoá Bin không xếp hàng; mô phỏng: bước kiểm không thấy) →
		khoá chính báo trùng → đúng câu LO_TRUNG_MA, không 500 "Lỗi máy chủ…"."""
		ten = self._phieu(dong=[("A", "hộp", 10, 10000, 0, 1)])
		frappe.get_doc({"doctype": "Batch", "batch_id": f"{ten}-001", "item": self.ma["A"]}).insert(ignore_permissions=True)
		goc = frappe.db.exists
		with patch.object(frappe.db, "exists", lambda dt, *a, **k: False if dt == "Batch" else goc(dt, *a, **k)):
			ket = self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		self._loi(ket, "P0001", f"LO_TRUNG_MA: Mã lô {ten}-001 đã có trong sổ — đổi mã lô ấy rồi hoàn thành lại phiếu.")
		self.assertEqual(frappe.db.get_value("Purchase Invoice", ten, "docstatus"), 0)
