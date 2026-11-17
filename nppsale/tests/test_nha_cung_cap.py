"""Nhà cung cấp (P4 — M8) ngoài kịch bản vàng: đếm chứng từ (`so_chung_tu_ncc`), gộp (`gop_nha_cung_cap`), xoá (`xoa_nha_cung_cap`), cổng `suppliers`
xoá thẳng (trigger `_ncc_chan_xoa` / `_ncc_xoa_qua_rpc`) — cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_nha_cung_cap

Dựng trên bộ dữ liệu F của tệp vàng (test_kho_mua_vang.dung_nen_kho — NCC chính: B / N → S3, M → S1, R → S4); mọi lời gọi đi qua cổng (`api.rpc` /
`api.truy_van`) DƯỚI ĐÚNG NGƯỜI. Câu lỗi nguyên văn của nppsale (thân hàm / trigger — đặc tả kho_mua §3.13, §3.14, §5.3).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, cint, flt, getdate, nowdate

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.kham_so import quet_cong_no_ncc
from nppsale.npp_he_thong.doctype.npp_phien_danh_muc.npp_phien_danh_muc import doc_phien
from nppsale.su_kien import cong_no_ncc as N
from nppsale.tests import test_kho_mua_vang as V
from nppsale.thiet_lap.kho_mua import cai_dat_kho

GOP_VAI = "KHONG_DU_QUYEN: chỉ Chủ NPP / Quản lý / Kế toán được gộp nhà cung cấp"
XOA_VAI = "KHONG_DU_QUYEN_XOA_NCC: chỉ Chủ NPP được xoá nhà cung cấp"
TRUNG = "GOP_NCC_TRUNG: chọn hai nhà cung cấp khác nhau"
KHONG_TU = "KHONG_TIM_THAY_NCC: nhà cung cấp cần gộp không còn / không thuộc NPP"
KHONG_VAO = "KHONG_TIM_THAY_NCC: nhà cung cấp giữ lại không còn / không thuộc NPP"
KHONG_XOA = "KHONG_TIM_THAY_NCC: nhà cung cấp không còn / không thuộc NPP"
QUA_RPC = "NCC_XOA_QUA_RPC: xoá nhà cung cấp ở màn chi tiết NCC (chỉ Chủ NPP)."


def co_chung_tu(ten: str, mo_ta: str) -> str:
	return f'NCC_CO_CHUNG_TU: không xoá được nhà cung cấp "{ten}" — đã có {mo_ta}. Dùng "Ngừng hợp tác" hoặc "Gộp vào NCC khác".'


class TestNhaCungCap(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(V.VANG, encoding="utf-8") as f:
			cls.nen = json.load(f)["nen"]

	def setUp(self):
		frappe.db.savepoint("npp_test")
		for p in (patch.object(frappe.db, "commit", lambda *a, **k: None), patch.object(frappe, "log_error", lambda *a, **k: None),
				patch("nppsale.rpc.phieu_nhap._xep_repost", lambda: None)):
			p.start()
			self.addCleanup(p.stop)
		frappe.local._npp_cai_dat_ban = None
		self.ma = V.dung_nen_kho(self.nen)
		self.cd = cai_dat_kho()
		self.ngay = getdate(nowdate()).strftime("%d/%m/%Y")

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_cai_dat_ban = None
		frappe.local._npp_ngu_canh = None
		frappe.local.dynamic_link_map = None

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

	def _ok(self, ket):
		self.assertNotIn("error", ket, ket)
		return ket["data"]

	def _loi(self, ket, ma, cau):
		self.assertIn("error", ket, ket)
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), (ma, cau))

	# ------------------------------------------------------------------------------------------------ dựng
	def _pn(self, tien: int, ncc="S1", hoan=True) -> str:
		"""Phiếu nhập A `hộp` × 10 (TK) — hoàn thành hoặc để nháp."""
		ten = self._ok(self._cong("TK", {"bang": "purchase_invoices", "hanh_dong": "insert", "select": "id", "gia_tri": {"org_id": self.ma["org"],
			"supplier_id": self.ma[ncc], "warehouse_zone": "sale", "discount": 0, "status": "draft"}}))[0]["id"]
		self._ok(self._cong("TK", {"bang": "purchase_invoice_lines", "hanh_dong": "insert", "select": "id", "gia_tri": [{"invoice_id": ten,
			"product_id": self.ma["A"], "unit_name": "hộp", "quantity": 10, "unit_price": tien // 10, "line_discount": 0, "vat_rate": 0,
			"conversion_factor": 1, "sort_order": 1}]}))
		if hoan:
			self.assertEqual(self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})["data"], ten)
		return ten

	def _ptn(self, tien: int, ncc="S1") -> str:
		ten = self._ok(self._cong("TK", {"bang": "supplier_returns", "hanh_dong": "insert", "select": "id", "gia_tri": {"org_id": self.ma["org"],
			"supplier_id": self.ma[ncc], "warehouse_zone": "sale", "discount": 0, "status": "draft"}}))[0]["id"]
		self._ok(self._cong("TK", {"bang": "supplier_return_lines", "hanh_dong": "insert", "select": "id", "gia_tri": [{"return_id": ten,
			"product_id": self.ma["A"], "unit_name": "hộp", "quantity": 1, "unit_price": tien, "line_discount": 0, "vat_rate": 0,
			"conversion_factor": 1, "sort_order": 1}]}))
		self.assertEqual(self._rpc("TK", "complete_supplier_return", {"p_return_id": ten})["data"], ten)
		return ten

	def _them_no(self, ncc="S1", **g) -> str:
		return self._ok(self._cong("KT", {"bang": "payables", "hanh_dong": "insert", "select": "id", "gia_tri": {"org_id": self.ma["org"],
			"supplier_id": self.ma.get(ncc, ncc), "paid": 0, "status": "open", **g}}))[0]["id"]

	def _phan_cong(self, *cap):
		self._ok(self._cong("CHU", {"bang": "user_suppliers", "hanh_dong": "insert", "select": "id", "gia_tri": [{"user_id": self.ma["u:" + nv],
			"supplier_id": self.ma[ncc], "org_id": self.ma["org"]} for nv, ncc in cap]}))

	def _nhap_kho(self, ncc: str, ma: str) -> str:
		"""Nhập kho tay `IN-` có NCC, không nợ (Stock Entry mang `supplier` — `stock_entries.supplier_id`)."""
		return self._ok(self._rpc("CHU", "post_stock_import", {"p": {"entry_code": ma, "supplier_id": self.ma[ncc], "warehouse_zone": "sale",
			"payable": None, "lines": [{"product_id": self.ma["A"], "unit_name": "hộp", "qty_tx": 2, "conv": 1, "base_qty": 2, "base_cost": 1000}]}}))[0][
			"entry_id"]

	def _ncc_chinh(self, hang: str) -> str | None:
		return frappe.db.get_value("Item Default", {"parent": self.ma[hang], "parenttype": "Item"}, "default_supplier")

	def _dat_ncc_chinh(self, hang: str, ncc: str):
		it = frappe.get_doc("Item", self.ma[hang])
		dong = next((d for d in it.item_defaults if d.company == self.cd.cong_ty), None) or it.append("item_defaults", {"company": self.cd.cong_ty})
		dong.default_supplier = self.ma[ncc]
		it.save(ignore_permissions=True)

	def _phien(self) -> int:
		return cint(doc_phien()["phien"])

	# ------------------------------------------------------------------------------------------------ so_chung_tu_ncc
	def test_so_chung_tu_vai_va_khong_thay(self):
		"""mig 232: 4 vai mua hàng (thủ kho thấy cả `con_no` — definer, §7.3 điểm 25); NVBH → `KHONG_DU_QUYEN` (chỉ mã); NCC không có →
		`KHONG_TIM_THAY_NCC` (chỉ mã); NCC trống → tong 0."""
		self._loi(self._rpc("NV", "so_chung_tu_ncc", {"p_supplier_id": self.ma["S1"]}), "P0001", "KHONG_DU_QUYEN")
		for nguoi in ("CHU", "QL", "KT", "TK"):
			self.assertEqual(self._ok(self._rpc(nguoi, "so_chung_tu_ncc", {"p_supplier_id": self.ma["S0"]})),
				{"tong": 0, "chi_tiet": [], "nhan_vien": 0, "so_khoan_no": 0, "con_no": 0}, nguoi)
		self._loi(self._rpc("KT", "so_chung_tu_ncc", {"p_supplier_id": "NCC-KHONG-CO"}), "P0001", "KHONG_TIM_THAY_NCC")
		self._loi(self._rpc("KT", "so_chung_tu_ncc", {}), "P0001", "KHONG_TIM_THAY_NCC")

	def test_so_chung_tu_dem(self):
		"""§5.3: `payables` = dòng công nợ (mọi loại) + tờ nợ đầu kỳ / lập tay đã xoá (tờ huỷ không có tờ sửa thay — ⚠K); tờ `DKN-` sửa số (amend)
		không đếm hai lần; `purchase_invoices` mọi docstatus (nháp cũng đếm), `stock_entries` = phiếu nhập / trả NCC đã ghi sổ + Stock Entry có NCC;
		`supplier_payments` tên thô (chỉ phiếu chi — Ghi trả `GTN-` không phải `supplier_payments`); `nhan_vien` = phân công; `so_khoan_no` / `con_no`
		chỉ dòng chưa `paid`, không kẹp dòng âm (mig 231)."""
		p1 = self._pn(100000)
		self._pn(50000, hoan=False)  # phiếu tạm: phiếu nhập, chưa phiếu kho
		self._ptn(30000)
		dk = self._them_no(amount=50000, opening_balance=True)
		self._ok(self._cong("KT", {"bang": "payables", "hanh_dong": "update", "select": "id", "gia_tri": {"amount": 60000},
			"loc": [{"op": "eq", "cot": "id", "gt": dk}]}))  # amend DKN-…-1: tờ cũ huỷ CÓ tờ sửa thay
		n1 = self._them_no(amount=7000, invoice_number="N1")
		self._ok(self._cong("KT", {"bang": "payables", "hanh_dong": "delete", "select": "id", "loc": [{"op": "eq", "cot": "id", "gt": n1}]}))
		self._nhap_kho("S1", "IN-20261117-1001")
		self._ok(self._rpc("KT", "chi_tra_ncc", {"p_supplier_id": self.ma["S1"], "p_amount": 60000, "p_method": "cash"}))  # trả đủ nợ đầu kỳ (trước)
		self._ok(self._rpc("KT", "record_payable_payment", {"p_payable_id": frappe.db.get_value(N.DT, {"chung_tu": p1}, "name"), "p_amount": 1000,
			"p_method": "cash"}))  # Ghi trả GTN-
		self._phan_cong(("NV", "S1"))
		r = self._ok(self._rpc("TK", "so_chung_tu_ncc", {"p_supplier_id": self.ma["S1"]}))
		self.assertEqual(r, {"tong": 12, "chi_tiet": [
			{"bang": "payables", "cot": "supplier_id", "so": 4, "nhan": "dòng công nợ NCC"},
			{"bang": "products", "cot": "primary_supplier_id", "so": 1, "nhan": "mặt hàng"},
			{"bang": "purchase_invoices", "cot": "supplier_id", "so": 2, "nhan": "phiếu nhập"},
			{"bang": "stock_entries", "cot": "supplier_id", "so": 3, "nhan": "phiếu kho"},
			{"bang": "supplier_payments", "cot": "supplier_id", "so": 1, "nhan": "supplier_payments"},
			{"bang": "supplier_returns", "cot": "supplier_id", "so": 1, "nhan": "phiếu trả NCC"}],
			"nhan_vien": 1, "so_khoan_no": 2, "con_no": 69000})

	# ------------------------------------------------------------------------------------------------ gop_nha_cung_cap
	def test_gop_vai_trung_khong_thay(self):
		"""mig 232 thứ tự: vai (thủ kho / NVBH) → hai NCC khác nhau (NULL / trùng — kể cả khác hoa thường) → NCC bị gộp không có → NCC giữ lại không có."""
		for nguoi in ("TK", "NV"):
			self._loi(self._rpc(nguoi, "gop_nha_cung_cap", {"p_tu": self.ma["S2"], "p_vao": self.ma["S1"]}), "P0001", GOP_VAI)
		self._loi(self._rpc("TK", "gop_nha_cung_cap", {"p_tu": None, "p_vao": None}), "P0001", GOP_VAI)  # vai trước tham số
		for ts in ({"p_tu": self.ma["S2"], "p_vao": self.ma["S2"]}, {"p_tu": None, "p_vao": self.ma["S1"]}, {"p_tu": self.ma["S2"]},
				{"p_tu": self.ma["S2"], "p_vao": self.ma["S2"].lower()}, {"p_tu": "", "p_vao": self.ma["S1"]}):
			self._loi(self._rpc("KT", "gop_nha_cung_cap", ts), "P0001", TRUNG)
		self._loi(self._rpc("KT", "gop_nha_cung_cap", {"p_tu": "NCC-KHONG-CO", "p_vao": "NCC-CUNG-KHONG"}), "P0001", KHONG_TU)
		self._loi(self._rpc("KT", "gop_nha_cung_cap", {"p_tu": "NCC-KHONG-CO", "p_vao": self.ma["S1"]}), "P0001", KHONG_TU)
		self._loi(self._rpc("KT", "gop_nha_cung_cap", {"p_tu": self.ma["S2"], "p_vao": "NCC-KHONG-CO"}), "P0001", KHONG_VAO)
		self.assertTrue(frappe.db.exists("Supplier", self.ma["S2"]))

	def test_gop_chuyen_chung_tu(self):
		"""§3.13 Frappe: mọi chứng từ / sổ cái / Payment Ledger / phiếu kho / NCC chính / phân công sang NCC giữ lại; tờ nợ đầu kỳ của NCC bị gộp thành
		nợ lập tay khi NCC giữ lại đã có nợ đầu kỳ; hồ sơ trống điền từ NCC bị gộp; dòng công nợ chiếu lại (tên NCC); trả trước KHÔNG tự dồn; phiên
		danh mục tăng; NCC bị gộp mất; khám sổ sạch."""
		s1, s2 = self.ma["S1"], self.ma["S2"]
		frappe.db.set_value("Supplier", s1, {"npp_co_han_muc": 0, "npp_han_muc": 0, "npp_ngay_dkkd": None})
		frappe.db.set_value("Supplier", s2, {"npp_co_han_muc": 1, "npp_han_muc": 3000000, "npp_ngay_dkkd": "2020-01-02", "npp_ngan_hang": "VCB",
			"npp_dien_thoai": "0902"})
		p1 = self._pn(100000, "S1")  # nợ của NCC giữ lại — chưa trả
		dk1 = self._them_no("S1", amount=30000, opening_balance=True, notes="Đầu kỳ S1")
		dk2 = self._them_no("S2", amount=40000, opening_balance=True, notes=" Đầu kỳ S2 ")
		p2 = self._pn(50000, "S2")
		pc = self._ok(self._rpc("KT", "chi_tra_ncc", {"p_supplier_id": s2, "p_amount": 120000, "p_method": "cash"}))  # 90.000 vào nợ, 30.000 trả trước
		self.assertEqual((pc["da_tru_no"], pc["tra_truoc"]), (90000, 30000))
		r2 = self._ptn(20000, "S2")
		se = self._nhap_kho("S2", "IN-20261117-2001")
		self._dat_ncc_chinh("K", "S2")
		self._phan_cong(("NV", "S1"), ("NV", "S2"), ("TK", "S2"))
		phien = self._phien()
		r = self._ok(self._rpc("QL", "gop_nha_cung_cap", {"p_tu": s2, "p_vao": s1}))
		self.assertEqual(r, {"vao": s1, "tu_ten": "NCC Hai", "tu_ma": "NCC02", "nhan_vien": 1, "da_xoa": True, "da_chuyen": [
			{"bang": "payables", "cot": "supplier_id", "so": 4}, {"bang": "products", "cot": "primary_supplier_id", "so": 1},
			{"bang": "purchase_invoices", "cot": "supplier_id", "so": 1}, {"bang": "stock_entries", "cot": "supplier_id", "so": 3},
			{"bang": "supplier_payments", "cot": "supplier_id", "so": 1}, {"bang": "supplier_returns", "cot": "supplier_id", "so": 1}]})
		self.assertFalse(frappe.db.exists("Supplier", s2))
		# chứng từ + sổ sang NCC giữ lại
		self.assertEqual({x: frappe.db.get_value("Purchase Invoice", x, "supplier") for x in (p2, r2)}, {p2: s1, r2: s1})
		self.assertEqual((frappe.db.get_value("Payment Entry", pc["id"], "party"), frappe.db.get_value("Stock Entry", se, "supplier")), (s1, s1))
		for dt in ("Payment Ledger Entry", "GL Entry"):
			self.assertFalse(frappe.db.exists(dt, {"party_type": "Supplier", "party": s2}), dt)
		self.assertEqual(self._ncc_chinh("K"), s1)
		self.assertEqual(sorted(tuple(x) for x in frappe.get_all("NPP Nhan Vien Cong Ty", filters={"nha_cung_cap": ("in", (s1, s2))},
			fields=["parent", "nha_cung_cap"], as_list=True)), sorted([(self.ma["u:NV"], s1), (self.ma["u:TK"], s1)]))
		# dòng công nợ: mọi dòng của NCC giữ lại, tên NCC mới; đầu kỳ của S2 → nợ lập tay + ghi chú; đầu kỳ của S1 giữ
		dong = {x.name: x for x in frappe.get_all(N.DT, filters={"nha_cung_cap": ("in", (s1, s2))}, fields=["name", "nha_cung_cap", "ten_ncc", "loai",
			"khoa_cho", "ghi_chu", "da_tra", "so_tien", "chung_tu"])}
		self.assertEqual({(x.nha_cung_cap, x.ten_ncc) for x in dong.values()}, {(s1, "NCC Một")})
		self.assertEqual((dong[dk1].loai, dong[dk1].khoa_cho, dong[dk1].ghi_chu), ("dau_ky", f"dau_ky:{s1}", "Đầu kỳ S1"))
		self.assertEqual((dong[dk2].loai, dong[dk2].khoa_cho, dong[dk2].ghi_chu), ("lap_tay", None,
			f"Đầu kỳ S2 · Nợ đầu kỳ của NCC NCC Hai (gộp ngày {self.ngay})"))
		self.assertEqual(frappe.db.get_value("Purchase Invoice", dong[dk2].chung_tu, "npp_loai"), "lap_tay")
		self.assertEqual(self._ok(self._cong("KT", {"bang": "payables", "select": "opening_balance", "loc": [{"op": "eq", "cot": "id", "gt": dk2}]})),
			[{"opening_balance": False}])
		# trả trước của NCC bị gộp KHÔNG dồn vào nợ của NCC giữ lại (tới sự kiện kế tiếp — như nppsale)
		self.assertEqual(flt(dong[self._dong_pn(p1)].da_tra), 0)
		tt = frappe.get_all(N.DT, filters={"nha_cung_cap": s1, "loai": "tra_truoc"}, fields=["phieu_chi", "da_tra"])
		self.assertEqual([(x.phieu_chi, flt(x.da_tra)) for x in tt], [(pc["id"], 30000)])
		# hồ sơ: ô trống lấy của S2, ô có giữ; hạn mức / ngày ĐKKD COALESCE; ghi chú gộp; khoá tìm theo MST mới
		s = frappe.db.get_value("Supplier", s1, ["npp_dien_thoai", "npp_email", "tax_id", "npp_ngan_hang", "npp_co_han_muc", "npp_han_muc",
			"npp_ngay_dkkd", "supplier_details", "npp_tim_kd"], as_dict=True)
		self.assertEqual((s.npp_dien_thoai, s.npp_email, s.tax_id, s.npp_ngan_hang, s.npp_co_han_muc, flt(s.npp_han_muc), str(s.npp_ngay_dkkd)),
			("0901", "hai@ncc", "0101", "VCB", 1, 3000000, "2020-01-02"))
		self.assertEqual(s.supplier_details, f"ghi chú S1\nGộp từ NCC NCC Hai (NCC02) ngày {self.ngay}.\nGhi chú NCC cũ: NCC hai cũ")
		self.assertIn("0101", s.npp_tim_kd)
		self.assertGreater(self._phien(), phien)
		self.assertEqual(quet_cong_no_ncc([s1, s2]), [])
		# sự kiện kế tiếp (khoản dương mới ghi sổ) dồn trả trước vào khoản của NCC giữ lại — nợ đầu kỳ trước (`opening_balance DESC`)
		self._them_no("S1", amount=1, invoice_number="MOI")
		self.assertEqual((flt(frappe.db.get_value(N.DT, dk1, "da_tra")), flt(frappe.db.get_value(N.DT, self._dong_pn(p1), "da_tra"))), (30000, 0))

	def test_gop_dynamic_link_bo_dem_cu(self):
		"""Bản đồ Dynamic Link của lõi lấy tập DISTINCT loại liên kết nhớ đệm 12 giờ (`fetch_distinct_link_doctypes`) — bộ đệm chưa có 'Supplier' (dòng
		lập không qua kiểm liên kết không làm mới) thì `rename_doc` bỏ sót `party` của phiếu chi / sổ cái / Payment Ledger: gộp tự quét mọi trường
		Dynamic Link, không sót dòng nào trỏ NCC đã xoá."""
		s1, s2 = self.ma["S1"], self.ma["S2"]
		pc = self._ok(self._rpc("KT", "chi_tra_ncc", {"p_supplier_id": s2, "p_amount": 10000, "p_method": "cash"}))
		for dt in ("Payment Entry", "GL Entry", "Payment Ledger Entry"):
			khoa = f"dynamic_link_map::{dt}::party_type"
			self.addCleanup(frappe.cache.delete_value, khoa)  # bộ đệm của site (không lui theo savepoint) — xoá để lõi dựng lại từ sổ
			frappe.cache.set_value(khoa, ["Customer"])  # bộ đệm cũ: chưa thấy 'Supplier'
		frappe.local.dynamic_link_map = None
		self._ok(self._rpc("KT", "gop_nha_cung_cap", {"p_tu": s2, "p_vao": s1}))
		self.assertEqual(frappe.db.get_value("Payment Entry", pc["id"], "party"), s1)
		for dt in ("Payment Ledger Entry", "GL Entry"):
			self.assertFalse(frappe.db.exists(dt, {"party_type": "Supplier", "party": s2}), dt)
			self.assertTrue(frappe.db.exists(dt, {"party_type": "Supplier", "party": s1}), dt)

	def test_doi_dynamic_link_bo_single_ao(self):
		"""Trường Dynamic Link ở DocType Single / ảo (không có bảng riêng — Custom Field đặt ở đó được) bỏ qua như lõi, không làm hỏng lượt gộp."""
		from frappe.model.dynamic_links import get_dynamic_links

		from nppsale.rpc import nha_cung_cap as R

		s1, s2 = self.ma["S1"], self.ma["S2"]
		pc = self._ok(self._rpc("KT", "chi_tra_ncc", {"p_supplier_id": s2, "p_amount": 10000, "p_method": "cash"}))
		gia = [frappe._dict(parent=dt, fieldname="npp_x", options="npp_x_loai") for dt in ("Buying Settings", "Recorder Event")]
		with patch.object(R, "get_dynamic_links", lambda: gia + [d for d in get_dynamic_links() if d.parent == "Payment Entry"]):
			R._doi_dynamic_link(s2, s1)
		self.assertEqual(frappe.db.get_value("Payment Entry", pc["id"], "party"), s1)

	def _dong_pn(self, pi: str) -> str:
		return frappe.db.get_value(N.DT, {"khoa_nguon": f"Purchase Invoice:{pi}"}, "name")

	def test_gop_dau_ky_mot_ben(self):
		"""Chỉ NCC bị gộp có nợ đầu kỳ → giữ nguyên là nợ đầu kỳ của NCC giữ lại (khoá chờ theo NCC mới, ghi chú không đổi); thêm nợ đầu kỳ nữa cho NCC
		giữ lại → trùng `uq_payables_opening`."""
		s1, s2 = self.ma["S1"], self.ma["S2"]
		dk = self._them_no("S2", amount=40000, opening_balance=True, notes="Đầu kỳ S2")
		self._ok(self._rpc("KT", "gop_nha_cung_cap", {"p_tu": s2, "p_vao": s1}))
		r = frappe.db.get_value(N.DT, dk, ["nha_cung_cap", "loai", "khoa_cho", "ghi_chu", "ten_ncc"], as_dict=True)
		self.assertEqual((r.nha_cung_cap, r.loai, r.khoa_cho, r.ghi_chu, r.ten_ncc), (s1, "dau_ky", f"dau_ky:{s1}", "Đầu kỳ S2", "NCC Một"))
		ket = self._cong("KT", {"bang": "payables", "hanh_dong": "insert", "select": "id", "gia_tri": {"org_id": self.ma["org"], "supplier_id": s1,
			"paid": 0, "status": "open", "amount": 5, "opening_balance": True}})
		self.assertEqual(ket["error"]["message"], 'duplicate key value violates unique constraint "uq_payables_opening"')

	def test_gop_khoa_hai_ncc_theo_ten(self):
		"""Khoá hai NCC theo tên trong MỘT câu `FOR UPDATE` (nppsale `ORDER BY id`) — câu ghi đầu tiên đến sau; gộp ngược hai NCC (S3 vào S0). Mã NCC
		rỗng = không mã (`tu_ma` null, ghi chú không kèm "()")."""
		frappe.db.set_value("Supplier", self.ma["S3"], "npp_ma", "")
		cau, goc = [], frappe.db.sql

		def ghi(q, *a, **k):
			cau.append(" ".join(str(q).split()))
			return goc(q, *a, **k)

		with patch.object(frappe.db, "sql", ghi):
			r = self._ok(self._rpc("KT", "gop_nha_cung_cap", {"p_tu": self.ma["S3"], "p_vao": self.ma["S0"]}))
		self.assertEqual((r["tu_ten"], r["tu_ma"], r["da_chuyen"]), ("NCC Ba", None, [{"bang": "products", "cot": "primary_supplier_id", "so": 2}]))
		self.assertEqual(frappe.db.get_value("Supplier", self.ma["S0"], "supplier_details"), f"Gộp từ NCC NCC Ba ngày {self.ngay}.")
		khoa = next(i for i, q in enumerate(cau) if "FROM `tabSupplier`" in q and "FOR UPDATE" in q)
		self.assertIn("WHERE `name` IN (", cau[khoa])
		self.assertIn("ORDER BY `name` FOR UPDATE", cau[khoa])
		ghi_dau = next(i for i, q in enumerate(cau) if q.upper().startswith(("UPDATE", "DELETE", "INSERT")))
		self.assertLess(khoa, ghi_dau)
		self.assertEqual(self._ncc_chinh("B"), self.ma["S0"])
		self.assertEqual(self._ncc_chinh("N"), self.ma["S0"])

	# ------------------------------------------------------------------------------------------------ xoa_nha_cung_cap
	def test_xoa_vai_khong_thay_ep_kieu(self):
		"""mig 233: ép kiểu `p_xoa_hang` (PostgREST, trước thân hàm) → chỉ Chủ NPP → NCC không có."""
		self._loi(self._rpc("NV", "xoa_nha_cung_cap", {"p_id": self.ma["S0"], "p_xoa_hang": "khong"}), "22P02",
			'invalid input syntax for type boolean: "khong"')
		for nguoi in ("QL", "KT", "TK", "NV"):
			self._loi(self._rpc(nguoi, "xoa_nha_cung_cap", {"p_id": self.ma["S0"]}), "P0001", XOA_VAI)
		self._loi(self._rpc("CHU", "xoa_nha_cung_cap", {"p_id": "NCC-KHONG-CO", "p_xoa_hang": True}), "P0001", KHONG_XOA)
		self._loi(self._rpc("CHU", "xoa_nha_cung_cap", {}), "P0001", KHONG_XOA)
		self.assertTrue(frappe.db.exists("Supplier", self.ma["S0"]))

	def test_xoa_co_chung_tu(self):
		"""Còn chứng từ (bỏ mặt hàng) → `NCC_CO_CHUNG_TU`, không đổi gì; khoản nợ đã xoá (tờ `NTN-` huỷ) vẫn chặn (⚠K); chứng từ ngoài bảng nppsale
		(Batch Desk trỏ NCC) → cùng mã, lời chung."""
		self._them_no("S1", amount=1000, invoice_number="N1")
		self._them_no("S1", amount=2000, invoice_number="N2")
		self._loi(self._rpc("CHU", "xoa_nha_cung_cap", {"p_id": self.ma["S1"], "p_xoa_hang": True}), "P0001", co_chung_tu("NCC Một",
			"2 dòng công nợ NCC"))
		self.assertEqual(self._ncc_chinh("M"), self.ma["S1"])  # mặt hàng giữ nguyên (lỗi trước bước mặt hàng)
		n = self._them_no("S0", amount=500, invoice_number="X")
		self._ok(self._cong("KT", {"bang": "payables", "hanh_dong": "delete", "select": "id", "loc": [{"op": "eq", "cot": "id", "gt": n}]}))
		self._loi(self._rpc("CHU", "xoa_nha_cung_cap", {"p_id": self.ma["S0"]}), "P0001", co_chung_tu("NCC trống", "1 dòng công nợ NCC"))
		frappe.get_doc({"doctype": "Batch", "batch_id": "VTD-LO-NCC4", "item": self.ma["A"], "supplier": self.ma["S4"]}).insert(ignore_permissions=True)
		self._loi(self._rpc("CHU", "xoa_nha_cung_cap", {"p_id": self.ma["S4"], "p_xoa_hang": False}), "P0001", co_chung_tu("NCC Bốn",
			"chứng từ khác trỏ tới nhà cung cấp"))
		self.assertEqual(self._ncc_chinh("R"), self.ma["S4"])  # lui cả lượt — mặt hàng R vẫn mang NCC chính
		self.assertTrue(frappe.db.exists("Supplier", self.ma["S4"]))

	def test_xoa_mat_hang(self):
		"""§3.14 + S12: xoá hàng — mặt hàng có chứng từ (B: lô có tồn) ngừng bán + gỡ NCC; không chứng từ (N) xoá; R chỉ có lô RỖNG + giá bán / giá nhập
		→ xoá cả lô và giá; phân công NV của NCC mất theo; phiên danh mục tăng."""
		V.dung_lo(self.ma, self.cd, {"ma": "L-B9", "sp": "@B", "vung": "sale", "ton": 3, "gia": 500, "han": 200, "nhan_ngay": -10})
		self._phan_cong(("NV", "S3"))
		phien = self._phien()
		r = self._ok(self._rpc("CHU", "xoa_nha_cung_cap", {"p_id": self.ma["S3"], "p_xoa_hang": True}))
		self.assertEqual(r, {"ten": "NCC Ba", "ma": None, "mat_hang_da_xoa": 1, "mat_hang_ngung_ban": 1, "mat_hang_go": 0})
		self.assertFalse(frappe.db.exists("Supplier", self.ma["S3"]))
		self.assertFalse(frappe.db.exists("Item", self.ma["N"]))
		self.assertEqual((cint(frappe.db.get_value("Item", self.ma["B"], "npp_ngung_ban")), self._ncc_chinh("B")), (1, None))
		self.assertFalse(frappe.db.exists("NPP Nhan Vien Cong Ty", {"nha_cung_cap": self.ma["S3"]}))
		self.assertGreater(self._phien(), phien)
		# R (NCC Bốn): lô rỗng tạo ở màn Lô hàng + giá nhập + giá bán nền
		self._ok(self._cong("TK", {"bang": "batches", "hanh_dong": "insert", "select": "id", "gia_tri": {"org_id": self.ma["org"], "product_id": self.ma["R"],
			"batch_code": "R-9", "expires_at": str(add_days(nowdate(), 365)), "qty_initial": 0, "qty_on_hand": 0, "unit_cost": 0, "warehouse_zone": "sale"}}))
		self._ok(self._rpc("KT", "luu_gia_nhap", {"p_dong": [{"product_id": self.ma["R"], "unit_name": "cái", "price": 5000}]}))
		self.assertEqual(frappe.db.count("Item Price", {"item_code": self.ma["R"]}), 2)
		r = self._ok(self._rpc("CHU", "xoa_nha_cung_cap", {"p_id": self.ma["S4"], "p_xoa_hang": None}))  # NULL tường minh = xoá hàng (luật ba trị)
		self.assertEqual(r, {"ten": "NCC Bốn", "ma": None, "mat_hang_da_xoa": 1, "mat_hang_ngung_ban": 0, "mat_hang_go": 0})
		self.assertFalse(frappe.db.exists("Item", self.ma["R"]))
		self.assertFalse(frappe.db.exists("Batch", "R-9"))
		self.assertEqual(frappe.db.count("Item Price", {"item_code": self.ma["R"]}), 0)

	def test_xoa_giu_mat_hang(self):
		"""Không truyền `p_xoa_hang` (mặc định false) / false → mặt hàng giữ, chỉ bỏ trống NCC chính (không ngừng bán, lô + giá còn)."""
		self._ok(self._cong("TK", {"bang": "batches", "hanh_dong": "insert", "select": "id", "gia_tri": {"org_id": self.ma["org"], "product_id": self.ma["R"],
			"batch_code": "R-8", "expires_at": str(add_days(nowdate(), 365)), "qty_initial": 0, "qty_on_hand": 0, "unit_cost": 0, "warehouse_zone": "sale"}}))
		phien = self._phien()
		r = self._ok(self._rpc("CHU", "xoa_nha_cung_cap", {"p_id": self.ma["S4"]}))
		self.assertEqual(r, {"ten": "NCC Bốn", "ma": None, "mat_hang_da_xoa": 0, "mat_hang_ngung_ban": 0, "mat_hang_go": 1})
		self.assertGreater(self._phien(), phien)  # gỡ NCC chính ghi thẳng (không qua Item.on_update) — phiên tăng MỘT lần cuối RPC
		self.assertEqual((self._ncc_chinh("R"), cint(frappe.db.get_value("Item", self.ma["R"], "npp_ngung_ban"))), (None, 0))
		self.assertTrue(frappe.db.exists("Batch", "R-8"))
		frappe.db.set_value("Supplier", self.ma["S3"], "npp_ma", "")  # mã rỗng = không mã
		r = self._ok(self._rpc("CHU", "xoa_nha_cung_cap", {"p_id": self.ma["S3"], "p_xoa_hang": "false"}))
		self.assertEqual(r, {"ten": "NCC Ba", "ma": None, "mat_hang_da_xoa": 0, "mat_hang_ngung_ban": 0, "mat_hang_go": 2})
		self.assertTrue(frappe.db.exists("Item", self.ma["N"]))

	def test_xoa_hang_vuong_lien_ket(self):
		"""Mặt hàng tưởng không chứng từ mà xoá vướng liên kết (nppsale `EXCEPTION WHEN foreign_key_violation`) → lui ĐÚNG phần xoá (lô rỗng đã xoá
		hiện lại) rồi ngừng bán + gỡ NCC."""
		V.dung_lo(self.ma, self.cd, {"ma": "L-B8", "sp": "@B", "vung": "sale", "ton": 3, "gia": 500, "han": 200, "nhan_ngay": -10})
		frappe.get_doc({"doctype": "Batch", "batch_id": "B-RONG", "item": self.ma["B"]}).insert(ignore_permissions=True)
		with patch("nppsale.rpc.nha_cung_cap.mat_hang_co_chung_tu", lambda hang: False):
			r = self._ok(self._rpc("CHU", "xoa_nha_cung_cap", {"p_id": self.ma["S3"], "p_xoa_hang": True}))
		self.assertEqual(r, {"ten": "NCC Ba", "ma": None, "mat_hang_da_xoa": 1, "mat_hang_ngung_ban": 1, "mat_hang_go": 0})
		self.assertTrue(frappe.db.exists("Batch", "B-RONG"))
		self.assertEqual((cint(frappe.db.get_value("Item", self.ma["B"], "npp_ngung_ban")), self._ncc_chinh("B")), (1, None))
		self.assertFalse(frappe.db.exists("Item", self.ma["N"]))

	def test_mat_hang_co_chung_tu(self):
		"""`_mat_hang_co_chung_tu`: dòng phiếu (nháp cũng tính), lô có gói lô (kể cả tồn 0), dòng kiểm kê; lô rỗng / giá KHÔNG tính."""
		from nppsale.rpc.nha_cung_cap import mat_hang_co_chung_tu

		self.assertFalse(mat_hang_co_chung_tu(self.ma["R"]))  # giá bán nền + không lô
		frappe.get_doc({"doctype": "Batch", "batch_id": "R-7", "item": self.ma["R"]}).insert(ignore_permissions=True)
		self.assertFalse(mat_hang_co_chung_tu(self.ma["R"]))
		self._pn(10000, "S1", hoan=False)  # dòng phiếu nhập nháp (A)
		self.assertTrue(mat_hang_co_chung_tu(self.ma["A"]))
		V.dung_lo(self.ma, self.cd, {"ma": "L-N1", "sp": "@N", "vung": "sale", "ton": 0, "nhap": 2, "gia": 500, "han": 200, "nhan_ngay": -10})
		self.assertTrue(mat_hang_co_chung_tu(self.ma["N"]))  # lô hết tồn vẫn có sổ / gói lô
		self.assertFalse(mat_hang_co_chung_tu(self.ma["G"]))
		frappe.get_doc({"doctype": "NPP Kiem Ke", "trang_thai": "draft", "kho": self.cd.kho_ban, "dong": [{"mat_hang": self.ma["G"],
			"kho": self.cd.kho_ban, "chenh_lech": 1}]}).insert(ignore_permissions=True)  # phiếu kiểm kê NHÁP (`stock_entry_lines`)
		self.assertTrue(mat_hang_co_chung_tu(self.ma["G"]))

	# ------------------------------------------------------------------------------------------------ cổng suppliers xoá thẳng
	def test_cong_xoa_thang(self):
		"""Trigger mig 232 / 233 qua cổng: vai ngoài owner / manager / warehouse → 0 dòng, không lỗi (RLS); NCC còn chứng từ → `NCC_CO_CHUNG_TU`
		liệt kê CẢ mặt hàng (trigger chặn chạy trước); NCC trống → `NCC_XOA_QUA_RPC` đúng câu."""
		self._them_no("S1", amount=1000, invoice_number="N1")
		xoa = lambda nguoi, ncc: self._cong(nguoi, {"bang": "suppliers", "hanh_dong": "delete", "select": "id",  # noqa: E731
			"loc": [{"op": "eq", "cot": "id", "gt": self.ma[ncc]}]})
		for nguoi in ("KT", "NV"):
			self.assertEqual(self._ok(xoa(nguoi, "S0")), [])
		for nguoi in ("CHU", "QL", "TK"):
			self._loi(xoa(nguoi, "S0"), "P0001", QUA_RPC)
		self._loi(xoa("CHU", "S1"), "P0001", co_chung_tu("NCC Một", "1 dòng công nợ NCC, 1 mặt hàng"))
		self._loi(xoa("TK", "S3"), "P0001", co_chung_tu("NCC Ba", "2 mặt hàng"))
		self.assertTrue(all(frappe.db.exists("Supplier", self.ma[x]) for x in ("S0", "S1", "S3")))
		# người lập = người gọi (bỏ `created_by` gửi lên), sửa không đổi được (trigger `_ncc_nguoi_tao`)
		ten = self._ok(self._cong("CHU", {"bang": "suppliers", "hanh_dong": "insert", "select": "id, created_by", "gia_tri": {"org_id": self.ma["org"],
			"name": "NCC Năm", "created_by": self.ma["u:NV"]}}))[0]
		self.assertEqual(ten["created_by"], self.ma["u:CHU"])
		r = self._ok(self._cong("QL", {"bang": "suppliers", "hanh_dong": "update", "select": "created_by", "gia_tri": {"created_by": self.ma["u:NV"]},
			"loc": [{"op": "eq", "cot": "id", "gt": ten["id"]}]}))
		self.assertEqual(r, [{"created_by": self.ma["u:CHU"]}])
