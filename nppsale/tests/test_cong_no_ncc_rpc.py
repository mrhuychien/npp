"""Công nợ + tiền NCC (P4 — M3) ngoài kịch bản vàng: Ghi trả một khoản (`record_payable_payment` — GTN- / bù trừ CTN-), phiếu chi một cục
(`chi_tra_ncc`), huỷ phiếu chi (`huy_phieu_chi_ncc`), RPC đọc `payables_summary` / `payables_by_supplier`, cổng ghi `payables` (nợ đầu kỳ DKN- / lập
tay NTN-), `payable_payments` (chỉ xác nhận), `supplier_payments` (không ghi), nhánh `DA_TRA_TIEN` của Huỷ phiếu nhập, khám sổ dòng tiền NCC (nhóm
23–26) — cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_cong_no_ncc_rpc

Dựng trên bộ dữ liệu F của tệp vàng (test_kho_mua_vang.dung_nen_kho); mọi lời gọi đi qua cổng (`api.rpc` / `api.truy_van`) DƯỚI ĐÚNG NGƯỜI. Câu lỗi
nguyên văn của nppsale (thân hàm / trigger — đặc tả kho_mua §3.10–§3.12, §4.4).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, get_datetime, getdate, now_datetime, nowdate

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.luat import cong_no_ncc as L
from nppsale.su_kien import cong_no_ncc as N
from nppsale.tests import test_kho_mua_vang as V
from nppsale.thiet_lap.kho_mua import cai_dat_kho

FORBIDDEN_TRA = "FORBIDDEN: chỉ chủ NPP hoặc kế toán được ghi trả tiền NCC."
FORBIDDEN_CHI = "FORBIDDEN: chỉ chủ NPP hoặc kế toán được lập phiếu chi trả NCC."
FORBIDDEN_HUY = "FORBIDDEN: chỉ chủ NPP hoặc kế toán được huỷ phiếu chi trả NCC."
RLS_NO = 'new row violates row-level security policy for table "payables"'


class TestCongNoNccRpc(IntegrationTestCase):
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

	def _ok(self, ket):
		self.assertNotIn("error", ket, ket)
		return ket["data"]

	def _loi(self, ket, ma, cau):
		self.assertIn("error", ket, ket)
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), (ma, cau))

	# ------------------------------------------------------------------------------------------------ dựng
	def _pn(self, tien: int, ncc="S1", vung="sale") -> str:
		"""Phiếu nhập hoàn thành: A `hộp` × 10 dòng giá tien/10 (TK)."""
		ket = self._cong("TK", {"bang": "purchase_invoices", "hanh_dong": "insert", "select": "id", "gia_tri": {"org_id": self.ma["org"],
			"supplier_id": self.ma[ncc], "warehouse_zone": vung, "discount": 0, "status": "draft"}})
		ten = self._ok(ket)[0]["id"]
		self._ok(self._cong("TK", {"bang": "purchase_invoice_lines", "hanh_dong": "insert", "select": "id", "gia_tri": [{"invoice_id": ten,
			"product_id": self.ma["A"], "unit_name": "hộp", "quantity": 10, "unit_price": tien // 10, "line_discount": 0, "vat_rate": 0,
			"conversion_factor": 1, "sort_order": 1}]}))
		self.assertEqual(self._rpc("TK", "complete_purchase_invoice", {"p_invoice_id": ten})["data"], ten)
		return ten

	def _ptn(self, tien: int, ncc="S1", vung="sale") -> str:
		"""Phiếu trả NCC đã gửi: A `hộp` × 1 giá tien (TK) — lấy lô ở kho của vùng (cần phiếu nhập trước)."""
		ten = self._ok(self._cong("TK", {"bang": "supplier_returns", "hanh_dong": "insert", "select": "id", "gia_tri": {"org_id": self.ma["org"],
			"supplier_id": self.ma[ncc], "warehouse_zone": vung, "discount": 0, "status": "draft"}}))[0]["id"]
		self._ok(self._cong("TK", {"bang": "supplier_return_lines", "hanh_dong": "insert", "select": "id", "gia_tri": [{"return_id": ten,
			"product_id": self.ma["A"], "unit_name": "hộp", "quantity": 1, "unit_price": tien, "line_discount": 0, "vat_rate": 0,
			"conversion_factor": 1, "sort_order": 1}]}))
		self.assertEqual(self._rpc("TK", "complete_supplier_return", {"p_return_id": ten})["data"], ten)
		return ten

	def _dong(self, pi: str) -> str:
		return frappe.db.get_value(N.DT, {"khoa_nguon": f"Purchase Invoice:{pi}"}, "name")

	def _no(self, ten: str) -> dict:
		ds = self._ok(self._cong("KT", {"bang": "payables", "select": "*", "loc": [{"op": "eq", "cot": "id", "gt": ten}]}))
		return ds[0] if ds else None

	def _tra(self, payable: str) -> list:
		return sorted(self._ok(self._cong("KT", {"bang": "payable_payments", "select": "*", "loc": [{"op": "eq", "cot": "payable_id",
			"gt": payable}]})), key=lambda r: (str(r["paid_at"]), r["id"]))

	def _them_no(self, nguoi, **g):
		return self._cong(nguoi, {"bang": "payables", "hanh_dong": "insert", "select": "id, amount, paid, status, opening_balance",
			"gia_tri": {"org_id": self.ma["org"], "supplier_id": self.ma["S1"], "paid": 0, "status": "open", **g}})

	def _sua_no(self, nguoi, ten, g):
		return self._cong(nguoi, {"bang": "payables", "hanh_dong": "update", "select": "id", "gia_tri": g,
			"loc": [{"op": "eq", "cot": "id", "gt": ten}]})

	def _chi(self, nguoi, tien, ncc="S1", **ts):
		return self._rpc(nguoi, "chi_tra_ncc", {"p_supplier_id": self.ma.get(ncc, ncc), "p_amount": tien, "p_method": "cash", **ts})

	def _ghi_tra(self, nguoi, payable, tien, method="cash", notes=None):
		return self._rpc(nguoi, "record_payable_payment", {"p_payable_id": payable, "p_amount": tien, "p_method": method, "p_notes": notes})

	def _pe_moi(self) -> set:
		return set(frappe.get_all("Payment Entry", pluck="name")) | set(frappe.get_all("Journal Entry", pluck="name"))

	# ------------------------------------------------------------------------------------------------ record_payable_payment
	def test_ghi_tra_duoi_ke_toan(self):
		"""Ghi trả lập Payment Entry `GTN-` DƯỚI CHÍNH kế toán (`paid_by` = người lập — cần DocPerm sàn đọc NCC: lõi kiểm quyền đọc NCC khi kiểm số
		phân bổ); '' → tiền mặt; chuyển khoản → TK ngân hàng; payment_id = id dòng cổng `payable_payments`."""
		p = self._pn(100000)
		no = self._dong(p)
		r = self._ok(self._ghi_tra("KT", no, 30000, "", "  đợt 1 "))
		self.assertEqual(len(r), 1)
		self.assertEqual((r[0]["new_paid"], r[0]["new_status"]), (30000, "partial"))
		dong = self._tra(no)
		self.assertEqual([(d["id"], d["amount"], d["method"], d["paid_by"], d["notes"], d["supplier_payment_id"]) for d in dong],
			[(r[0]["payment_id"], 30000, "cash", self.ma["u:KT"], "  đợt 1 ", None)])  # NULLIF(p_notes, '') — không trim
		pe = frappe.db.get_value("Payment Entry Reference", r[0]["payment_id"], "parent")
		self.assertTrue(pe.startswith("GTN-"), pe)
		self.assertEqual(frappe.db.get_value("Payment Entry", pe, ["owner", "npp_loai", "mode_of_payment", "posting_date"], as_dict=True),
			{"owner": self.ma["u:KT"], "npp_loai": "ghi_tra_ncc", "mode_of_payment": self.cd.hinh_thuc["cash"], "posting_date": getdate(nowdate())})
		r = self._ok(self._ghi_tra("CHU", no, 70000, "transfer"))
		self.assertEqual((r[0]["new_paid"], r[0]["new_status"]), (100000, "paid"))
		self.assertEqual(self._tra(no)[-1]["method"], "transfer")
		self.assertEqual((self._no(no)["paid"], self._no(no)["status"]), (100000, "paid"))

	def test_ghi_tra_thu_tu_kiem(self):
		"""Thứ tự nppsale (mig 167): ép kiểu tham số → vai (kể cả số 0) → số → khoá + tìm khoản → OVERPAY (số còn thô; dòng âm / trả trước luôn
		vượt) → CHECK hình thức (23514 — SAU OVERPAY). Lỗi không để lại chứng từ nào."""
		p = self._pn(100000)
		r = self._ptn(30000)
		no, no_r = self._dong(p), self._dong(r)
		truoc = self._pe_moi()
		self._loi(self._ghi_tra("KT", "khong-phai-uuid", 1), "22P02", 'invalid input syntax for type uuid: "khong-phai-uuid"')
		for nguoi in ("QL", "TK", "NV"):
			self._loi(self._ghi_tra(nguoi, no, 0), "42501", FORBIDDEN_TRA)
		for tien in (0, -5, None):
			self._loi(self._ghi_tra("KT", no, tien), "P0001", L.BAD_AMOUNT_TRA)
		self._loi(self._ghi_tra("KT", V.LA, 1), "P0001", L.PAYABLE_NOT_FOUND)
		self._loi(self._ghi_tra("KT", no, 100001, "chuyen"), "P0001", "OVERPAY: số tiền vượt quá công nợ còn lại (còn 100000).")
		self._loi(self._ghi_tra("KT", no, 1, "chuyen"), "23514", L.CHECK_METHOD)
		self._loi(self._ghi_tra("KT", no_r, 1), "P0001", "OVERPAY: số tiền vượt quá công nợ còn lại (còn -30000).")
		self.assertEqual(self._pe_moi(), truoc)
		self.assertEqual(self._tra(no), [])
		# dòng trả trước (amount 0, paid = tiền còn) → còn −tiền
		c = self._ok(self._chi("KT", 50000, "S2"))
		tt = frappe.db.get_value(N.DT, {"phieu_chi": c["id"], "loai": "tra_truoc"}, "name")
		self._loi(self._ghi_tra("KT", tt, 1), "P0001", "OVERPAY: số tiền vượt quá công nợ còn lại (còn -50000).")

	def test_bu_tru_trong_khoan_giam(self):
		"""§7.3 điểm 10 (quyết định tạm Q9): Bù trừ = bút toán `CTN-` (Debit Note) Nợ khoản được trả / Có khoản giảm CÒN MỞ của phiếu trả NCC — cũ
		nhất trước; vượt tổng khoản giảm → BU_TRU_KHONG_CON (không ghi gì). Tiền bù trừ chặn Huỷ phiếu nhập (DA_TRA_TIEN) và Huỷ phiếu trả
		(DA_CAN_TRU)."""
		p = self._pn(200000)
		r1 = self._ptn(10000)
		r2 = self._ptn(30000)
		self._pn(100000, "S2")
		self._ptn(50000, "S2")  # khoản giảm của NCC KHÁC không được dùng
		no = self._dong(p)
		truoc = self._pe_moi()
		self._loi(self._ghi_tra("KT", no, 40001, "offset"), "P0001", L.BU_TRU_KHONG_CON)
		self.assertEqual(self._pe_moi(), truoc)
		k = self._ok(self._ghi_tra("KT", no, 25000, "offset", ""))
		self.assertEqual((k[0]["new_paid"], k[0]["new_status"]), (25000, "partial"))
		je = frappe.db.get_value("Journal Entry Account", k[0]["payment_id"], "parent")
		self.assertEqual(frappe.db.get_value("Journal Entry", je, ["voucher_type", "npp_loai", "npp_phieu_nhap", "owner", "user_remark"],
			as_dict=True), {"voucher_type": "Debit Note", "npp_loai": "bu_tru_ncc", "npp_phieu_nhap": p, "owner": self.ma["u:KT"],
			"user_remark": None})
		self.assertTrue(je.startswith("CTN-"), je)
		# R1 (cũ hơn) hết khoản giảm trước, R2 còn 15.000
		self.assertEqual([(d["amount"], d["method"]) for d in self._tra(no)], [(25000, "offset")])
		self.assertEqual([(d["amount"], d["method"]) for d in self._tra(self._dong(r1))], [(-10000, "offset")])
		self.assertEqual([(d["amount"], d["method"]) for d in self._tra(self._dong(r2))], [(-15000, "offset")])
		self.assertEqual((self._no(self._dong(r1))["paid"], self._no(self._dong(r1))["status"]), (-10000, "paid"))
		self.assertEqual((self._no(self._dong(r2))["paid"], self._no(self._dong(r2))["status"]), (-15000, "open"))
		self._loi(self._ghi_tra("KT", no, 15001, "offset"), "P0001", L.BU_TRU_KHONG_CON)
		self._ok(self._ghi_tra("KT", no, 15000, "offset"))
		self._loi(self._ghi_tra("KT", no, 1, "offset"), "P0001", L.BU_TRU_KHONG_CON)
		self._loi(self._rpc("TK", "cancel_purchase_invoice", {"p_invoice_id": p, "p_reason": "x"}), "P0001", L.loi_da_tra_tien(40000).ma)
		self._loi(self._rpc("TK", "cancel_supplier_return", {"p_return_id": r2, "p_reason": "x"}), "P0001",
			"DA_CAN_TRU: Khoản giảm công nợ của phiếu này đã được cấn trừ (-30000). Gỡ phần cấn trừ trước rồi mới huỷ phiếu.")

	def test_qua_han_tay_giu_sau_ghi_tra(self):
		"""§7.3 điểm 13: Ghi trả trả `new_status` theo luật hàm gốc (`partial`) nhưng KHÔNG xoá dấu quá hạn tay — bản chiếu vẫn `overdue` tới khi đủ."""
		no = self._dong(self._pn(100000))
		self.assertEqual(self._ok(self._sua_no("KT", no, {"status": "overdue"})), [{"id": no}])
		k = self._ok(self._ghi_tra("KT", no, 10000))
		self.assertEqual(k[0]["new_status"], "partial")
		self.assertEqual(self._no(no)["status"], "overdue")
		self._ok(self._ghi_tra("KT", no, 90000))
		self.assertEqual(self._no(no)["status"], "paid")

	# ------------------------------------------------------------------------------------------------ chi_tra_ncc
	def test_chi_thu_tu_kiem(self):
		"""mig 242: ép kiểu ngày → vai → số (chữ S hoa) → hình thức (NULL tường minh / offset) → NCC → ngày tương lai (giờ VN); không ghi gì."""
		truoc = self._pe_moi()
		self._loi(self._chi("KT", 1, p_paid_date="31/12/2026"), "22008", 'date/time field value out of range: "31/12/2026"')
		self._loi(self._chi("QL", 0, p_method=None), "42501", FORBIDDEN_CHI)
		self._loi(self._chi("KT", 0, p_method="offset"), "P0001", L.BAD_AMOUNT_CHI)
		self._loi(self._chi("KT", 1, "NCC-KHONG-CO", p_method=None), "P0001", L.BAD_METHOD)
		self._loi(self._chi("KT", 1, "NCC-KHONG-CO", p_method="offset"), "P0001", L.BAD_METHOD)
		self._loi(self._chi("KT", 1, "NCC-KHONG-CO", p_paid_date=add_days(nowdate(), 1)), "P0001", L.NCC_KHONG_HOP_LE)
		self._loi(self._chi("KT", 1, p_paid_date=add_days(nowdate(), 1)), "P0001", L.NGAY_TUONG_LAI_CHI)
		self.assertEqual(self._pe_moi(), truoc)
		# p_method mặc định 'cash' khi không gửi (DEFAULT của hàm)
		c = self._ok(self._rpc("CHU", "chi_tra_ncc", {"p_supplier_id": self.ma["S1"], "p_amount": 5}))
		self.assertEqual(frappe.db.get_value("Payment Entry", c["id"], "mode_of_payment"), self.cd.hinh_thuc["cash"])

	def test_chi_phan_bo_va_luc_chi(self):
		"""Nợ đầu kỳ (lập SAU) trừ trước, rồi khoản cũ nhất; không đụng dòng âm; phần dư = trả trước. Lúc chi: chi hôm nay = giờ lập; ghi lùi = 12:00
		ngày chi — mọi phần của phiếu (cả dòng trả trước) cùng lúc ấy; ghi chú / tham chiếu btrim; TK ngân hàng tự điền số tham chiếu (cổng ẩn)."""
		pa = self._pn(200000)
		self._pn(300000)  # PB
		self._ptn(50000)
		dk = self._ok(self._them_no("KT", amount=100000, opening_balance=True))[0]["id"]
		c1 = self._ok(self._chi("KT", 250000, p_notes="  trả đợt 1 ", p_reference=" REF1 "))
		self.assertEqual({k: c1[k] for k in ("so_tien", "da_tru_no", "tra_truoc", "so_khoan")},
			{"so_tien": 250000, "da_tru_no": 250000, "tra_truoc": 0, "so_khoan": 2})
		self.assertEqual((c1["id"], c1["code"][:6]), (c1["code"], "PCNCC-"))
		self.assertEqual((self._no(dk)["paid"], self._no(dk)["status"]), (100000, "paid"))
		self.assertEqual((self._no(self._dong(pa))["paid"], self._no(self._dong(pa))["status"]), (150000, "partial"))
		sp = self._ok(self._cong("KT", {"bang": "supplier_payments", "select": "*", "loc": [{"op": "eq", "cot": "id", "gt": c1["id"]}]}))[0]
		self.assertEqual({k: sp[k] for k in ("seq", "supplier_id", "amount", "method", "reference_code", "notes", "status", "prepay_payable_id",
			"created_by")}, {"seq": int(c1["id"].split("-")[-1]), "supplier_id": self.ma["S1"], "amount": 250000, "method": "cash",
			"reference_code": "REF1", "notes": "trả đợt 1", "status": "posted", "prepay_payable_id": None, "created_by": self.ma["u:KT"]})
		self.assertEqual(str(sp["paid_date"])[:10], nowdate())
		dong = self._ok(self._cong("KT", {"bang": "payable_payments", "select": "*", "loc": [{"op": "eq", "cot": "supplier_payment_id",
			"gt": c1["id"]}]}))
		self.assertEqual(sorted((d["payable_id"], d["amount"], d["notes"]) for d in dong), sorted([(dk, 100000, f"Phiếu chi {c1['id']} — trả đợt 1"),
			(self._dong(pa), 150000, f"Phiếu chi {c1['id']} — trả đợt 1")]))
		tao = get_datetime(frappe.db.get_value("Payment Entry", c1["id"], "creation"))
		self.assertTrue(all(abs((V._gio(d["paid_at"]) - tao).total_seconds()) < 1 for d in dong), dong)
		# ghi lùi 6 ngày, chuyển khoản: dư 250.000 về trả trước; lúc chi 12:00 ngày chi cho MỌI dòng
		ngay = add_days(nowdate(), -6)
		c2 = self._ok(self._chi("KT", 600000, p_paid_date=ngay, p_method="transfer"))
		self.assertEqual({k: c2[k] for k in ("da_tru_no", "tra_truoc", "so_khoan")}, {"da_tru_no": 350000, "tra_truoc": 250000, "so_khoan": 2})
		tt = frappe.db.get_value(N.DT, {"phieu_chi": c2["id"], "loai": "tra_truoc"}, "name")
		r = self._no(tt)
		self.assertEqual({k: r[k] for k in ("invoice_number", "amount", "paid", "status", "notes", "opening_balance", "stock_entry_id")},
			{"invoice_number": c2["id"], "amount": 0, "paid": 250000, "status": "open", "notes": f"Trả trước NCC — phiếu chi {c2['id']}",
			"opening_balance": False, "stock_entry_id": None})
		luc = get_datetime(f"{ngay} 12:00:00")
		self.assertEqual(V._gio(r["created_at"]), luc)
		dong = self._ok(self._cong("KT", {"bang": "payable_payments", "select": "id, amount, paid_at, method", "loc": [{"op": "eq",
			"cot": "supplier_payment_id", "gt": c2["id"]}]}))
		self.assertEqual({V._gio(d["paid_at"]) for d in dong}, {luc})
		self.assertEqual(sum(flt(d["amount"]) for d in dong), 600000)
		self.assertEqual({d["method"] for d in dong}, {"transfer"})
		sp = self._ok(self._cong("KT", {"bang": "supplier_payments", "select": "reference_code, prepay_payable_id, method",
			"loc": [{"op": "eq", "cot": "id", "gt": c2["id"]}]}))[0]
		self.assertEqual(sp, {"reference_code": None, "prepay_payable_id": tt, "method": "transfer"})
		self.assertEqual(frappe.db.get_value("Payment Entry", c2["id"], "reference_no"), c2["id"])  # lõi bắt số tham chiếu cho TK ngân hàng

	def _no_tren_so(self, ncc: str, tien: int) -> str:
		"""Khoản nợ lập THẲNG trên sổ (tờ NTN- của lõi, không qua method) — hook chỉ chiếu, không dồn trả trước."""
		pi = frappe.new_doc("Purchase Invoice")
		pi.update({"naming_series": "NTN-.####", "supplier": self.ma[ncc], "company": self.cd.cong_ty, "update_stock": 0, "npp_loai": "lap_tay",
			"disable_rounded_total": 1, "taxes_and_charges": ""})
		pi.append("items", {"item_name": "x", "description": "x", "qty": 1, "rate": tien, "conversion_factor": 1,
			"uom": frappe.db.get_single_value("Stock Settings", "stock_uom") or "Nos", "expense_account": self.cd.tk_no_ncc_lap_tay or
			frappe.get_cached_value("Company", self.cd.cong_ty, "stock_received_but_not_billed"),
			"cost_center": frappe.get_cached_value("Company", self.cd.cong_ty, "cost_center")})
		pi.set("taxes", [])
		pi.flags.ignore_permissions = True
		pi.insert()
		pi.submit()
		self.assertEqual(self._no(self._dong(pi.name))["paid"], 0)
		return self._dong(pi.name)

	def test_chi_don_phieu_chi_cu_truoc(self):
		"""Phiếu chi còn tiền dồn THEO LÚC CHI cùng phiếu đang lập — `_don_tra_truoc_ncc` chạy cuối `chi_tra_ncc` (mig 242): (1) phiếu cũ chi sớm hơn
		ăn khoản nợ lập thẳng trên sổ trước, phiếu mới chỉ trừ phần còn lại; (2) phiếu mới GHI LÙI (lúc chi 12:00 ngày chi — sớm hơn phiếu cũ chi
		hôm nay) dồn trước phiếu cũ."""
		c0 = self._ok(self._chi("KT", 30000, "S2", p_paid_date=add_days(nowdate(), -3)))
		self.assertEqual(c0["tra_truoc"], 30000)
		no = self._no_tren_so("S2", 40000)
		c1 = self._ok(self._chi("KT", 20000, "S2"))
		self.assertEqual({k: c1[k] for k in ("da_tru_no", "tra_truoc", "so_khoan")}, {"da_tru_no": 10000, "tra_truoc": 10000, "so_khoan": 1})
		self.assertEqual(sorted((d["supplier_payment_id"], d["amount"]) for d in self._tra(no)), sorted([(c0["id"], 30000), (c1["id"], 10000)]))
		self.assertIsNone(frappe.db.get_value(N.DT, {"phieu_chi": c0["id"], "loai": "tra_truoc"}, "name"))  # phiếu cũ hết tiền → mất dòng
		self.assertEqual(flt(frappe.db.get_value(N.DT, {"phieu_chi": c1["id"], "loai": "tra_truoc"}, "da_tra")), 10000)
		# (2) S3: phiếu cũ chi hôm nay 30.000; phiếu mới ghi lùi 2 ngày 20.000 → phiếu mới trừ trước, phiếu cũ trừ phần còn lại
		d0 = self._ok(self._chi("KT", 30000, "S3"))
		no = self._no_tren_so("S3", 40000)
		d1 = self._ok(self._chi("KT", 20000, "S3", p_paid_date=add_days(nowdate(), -2)))
		self.assertEqual({k: d1[k] for k in ("da_tru_no", "tra_truoc", "so_khoan")}, {"da_tru_no": 20000, "tra_truoc": 0, "so_khoan": 1})
		self.assertEqual(sorted((d["supplier_payment_id"], d["amount"]) for d in self._tra(no)), sorted([(d1["id"], 20000), (d0["id"], 20000)]))
		self.assertEqual(flt(frappe.db.get_value(N.DT, {"phieu_chi": d0["id"], "loai": "tra_truoc"}, "da_tra")), 10000)

	def test_khoa_truoc_moi_cau_doc(self):
		"""CFD-05 / PoC 1d: câu ĐẦU của thân RPC (sau bước chuẩn bị + điểm lưu) là khoá NCC, rồi mọi dòng nợ của NCC — trước mọi câu đọc thường (đọc
		thường trước khoá lập ảnh chụp cũ: lượt song song đọc số đã trả cũ). Ghi trả khoá thêm dòng được trả + PI nguồn (đặc tả §3.10 bước 1)."""
		no = self._dong(self._pn(100000))
		c = self._ok(self._chi("KT", 5000, "S3"))

		def than(nguoi, ten, ts) -> list[str]:
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
				self._ok(self._rpc(nguoi, ten, ts))
			return cau[moc[0]:]

		def la_khoa(q, bang):
			return f"`{bang}`" in q and "FOR UPDATE" in q

		q = than("KT", "record_payable_payment", {"p_payable_id": no, "p_amount": 1000, "p_method": "cash"})
		self.assertTrue(la_khoa(q[0], "tabSupplier") and la_khoa(q[1], "tabNPP Cong No NCC") and la_khoa(q[2], "tabNPP Cong No NCC")
			and la_khoa(q[3], "tabPurchase Invoice"), q[:4])
		q = than("KT", "chi_tra_ncc", {"p_supplier_id": self.ma["S1"], "p_amount": 1000, "p_method": "cash"})
		self.assertTrue(la_khoa(q[0], "tabSupplier") and la_khoa(q[1], "tabSupplier") and la_khoa(q[2], "tabNPP Cong No NCC"), q[:3])
		q = than("KT", "huy_phieu_chi_ncc", {"p_id": c["id"]})
		self.assertTrue(la_khoa(q[0], "tabSupplier") and la_khoa(q[1], "tabNPP Cong No NCC") and la_khoa(q[2], "tabPayment Entry"), q[:3])

	# ------------------------------------------------------------------------------------------------ huy_phieu_chi_ncc
	def test_huy_phieu_chi(self):
		"""mig 242: tìm phiếu → (NPP) → vai (SAU tìm) → đã huỷ = idempotent; huỷ gỡ mọi phân bổ, khoản mở lại ăn tiền trả trước của phiếu chi KHÁC
		(chi sớm trước); lý do btrim → NULL khi rỗng; phiếu Ghi trả (GTN-) không phải phiếu chi."""
		self._loi(self._rpc("QL", "huy_phieu_chi_ncc", {"p_id": "PCNCC-9999"}), "P0001", L.PHIEU_CHI_KHONG_TON_TAI)
		c21 = self._ok(self._chi("KT", 30000, "S2", p_paid_date=add_days(nowdate(), -4)))
		c22 = self._ok(self._chi("KT", 20000, "S2", p_paid_date=add_days(nowdate(), -5), p_method="transfer"))
		n1 = self._ok(self._them_no("KT", supplier_id=self.ma["S2"], invoice_number="N1", amount=25000))[0]["id"]
		self.assertEqual(sorted((d["supplier_payment_id"], d["amount"]) for d in self._tra(n1)), sorted([(c22["id"], 20000), (c21["id"], 5000)]))
		self._loi(self._rpc("QL", "huy_phieu_chi_ncc", {"p_id": c22["id"]}), "42501", FORBIDDEN_HUY)
		k = self._ok(self._rpc("KT", "huy_phieu_chi_ncc", {"p_id": c22["id"], "p_reason": "   "}))
		self.assertEqual(k, {"id": c22["id"], "code": c22["id"], "da_huy": True, "so_tien_go": 20000})
		self.assertEqual(sorted((d["supplier_payment_id"], d["amount"]) for d in self._tra(n1)), sorted([(c21["id"], 5000), (c21["id"], 20000)]))
		self.assertEqual((self._no(n1)["paid"], self._no(n1)["status"]), (25000, "paid"))
		self.assertEqual(flt(frappe.db.get_value(N.DT, {"phieu_chi": c21["id"], "loai": "tra_truoc"}, "da_tra")), 5000)
		sp = self._ok(self._cong("KT", {"bang": "supplier_payments", "select": "status, cancel_reason, cancelled_by, prepay_payable_id",
			"loc": [{"op": "eq", "cot": "id", "gt": c22["id"]}]}))[0]
		self.assertEqual(sp, {"status": "cancelled", "cancel_reason": None, "cancelled_by": self.ma["u:KT"], "prepay_payable_id": None})
		self.assertEqual(self._ok(self._rpc("KT", "huy_phieu_chi_ncc", {"p_id": c22["id"], "p_reason": "lần 2"})),
			{"id": c22["id"], "code": c22["id"], "da_huy": False, "so_tien_go": 0})
		self.assertIsNone(frappe.db.get_value("Payment Entry", c22["id"], "npp_ly_do_huy"))
		# phiếu Ghi trả không huỷ qua đường phiếu chi
		no = self._dong(self._pn(10000, "S2"))
		g = self._ok(self._ghi_tra("KT", no, 1000))[0]["payment_id"]
		self._loi(self._rpc("KT", "huy_phieu_chi_ncc", {"p_id": frappe.db.get_value("Payment Entry Reference", g, "parent")}), "P0001",
			L.PHIEU_CHI_KHONG_TON_TAI)
		k = self._ok(self._rpc("CHU", "huy_phieu_chi_ncc", {"p_id": c21["id"], "p_reason": "  nhầm  "}))
		self.assertEqual(k["so_tien_go"], 30000)
		self.assertEqual(frappe.db.get_value("Payment Entry", c21["id"], "npp_ly_do_huy"), "nhầm")
		self.assertEqual((self._no(n1)["paid"], self._no(n1)["status"]), (0, "open"))

	# ------------------------------------------------------------------------------------------------ cổng payables
	def test_cong_them_no(self):
		"""Trigger `_khoa_ghi_thang_no_ncc` (TRƯỚC RLS) → RLS owner / accountant → NOT NULL → số ≤ 0 (⚠K) → khoá ngoại → trùng nợ đầu kỳ (23505);
		sai kiểu báo trước hết. Nợ đầu kỳ = tờ DKN- (is_opening), lập tay = NTN- (gắn phiếu kho → npp_phieu_kho theo nguồn id); khoản mới ăn tiền
		trả trước."""
		self._loi(self._them_no("KT", amount="abc", paid=5), "22P02", 'invalid input syntax for type numeric: "abc"')
		self._loi(self._them_no("QL", amount=1000, paid=5), "P0001", L.KHOA_THEM)
		self._loi(self._them_no("QL", amount=1000), "42501", RLS_NO)
		self._loi(self._them_no("KT", amount=1000, status="partial"), "P0001", L.KHOA_THEM)
		self._loi(self._them_no("KT", amount=None), "23502", 'null value in column "amount" of relation "payables" violates not-null constraint')
		self._loi(self._them_no("KT", amount=0), "P0001", L.KHOA_THEM)
		self._loi(self._them_no("KT", amount=1000, supplier_id="NCC-KHONG-CO"), "23503",
			'insert or update on table "payables" violates foreign key constraint "payables_supplier_id_fkey"')
		self._loi(self._them_no("KT", amount=1000, stock_entry_id="IN-KHONG-CO"), "23503",
			'insert or update on table "payables" violates foreign key constraint "payables_stock_entry_id_fkey"')
		c = self._ok(self._chi("KT", 700, "S1"))
		dk = self._ok(self._them_no("KT", amount=1000, status="overdue", opening_balance=True, invoice_number="DK-1", notes="Nợ cũ",
			due_date=add_days(nowdate(), -3)))
		self.assertEqual(dk, [{"id": dk[0]["id"], "amount": 1000, "paid": 700, "status": "overdue", "opening_balance": True}])
		pi = frappe.db.get_value(N.DT, dk[0]["id"], "chung_tu")
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi, ["is_opening", "npp_loai", "bill_no", "npp_ghi_chu_no", "npp_qua_han_tay",
			"owner", "docstatus"], as_dict=True), {"is_opening": "Yes", "npp_loai": "dau_ky", "bill_no": "DK-1", "npp_ghi_chu_no": "Nợ cũ",
			"npp_qua_han_tay": 1, "owner": self.ma["u:KT"], "docstatus": 1})
		self.assertTrue(pi.startswith("DKN-"), pi)
		self.assertEqual(self._tra(dk[0]["id"])[0]["supplier_payment_id"], c["id"])  # trigger mig 242: khoản mới ăn trả trước
		ket = self._them_no("CHU", amount=5, opening_balance=True)
		self._loi(ket, "23505", 'duplicate key value violates unique constraint "uq_payables_opening"')
		self.assertEqual(ket["error"]["details"], f"Key (org_id, supplier_id)=({self.ma['org']}, {self.ma['S1']}) already exists.")
		# nhiều dòng một lệnh: hỏng một dòng → không dòng nào ghi (cổng lui điểm lưu)
		dem = frappe.db.count("Purchase Invoice", {"npp_loai": "lap_tay"})
		self._loi(self._cong("KT", {"bang": "payables", "hanh_dong": "insert", "gia_tri": [{"supplier_id": self.ma["S2"], "amount": 10},
			{"supplier_id": self.ma["S2"], "amount": 10, "paid": 1}]}), "P0001", L.KHOA_THEM)
		self.assertEqual(frappe.db.count("Purchase Invoice", {"npp_loai": "lap_tay"}), dem)
		# lập tay gắn phiếu nhập → phiếu kho của dòng = tờ ấy (nguồn PI)
		p = self._pn(10000, "S2")
		t = self._ok(self._them_no("CHU", supplier_id=self.ma["S2"], amount=5000, stock_entry_id=p, invoice_number="TAY"))[0]["id"]
		pi = frappe.db.get_value(N.DT, t, "chung_tu")
		self.assertTrue(pi.startswith("NTN-"), pi)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi, ["npp_phieu_kho_loai", "npp_phieu_kho", "is_opening"], as_dict=True),
			{"npp_phieu_kho_loai": "Purchase Invoice", "npp_phieu_kho": p, "is_opening": "No"})
		self.assertEqual((self._no(t)["stock_entry_id"], self._no(t)["opening_balance"]), (p, False))

	def test_cong_sua_no(self):
		"""Sửa: ép kiểu → RLS (vai khác 0 dòng) → trigger: số / đã trả / NCC… → NO_NCC_KHOA; trạng thái phải khớp (chỉ khi ĐỔI); số HĐ / hạn / ghi chú
		→ trường AOS của tờ; số nợ đầu kỳ chưa trả → huỷ + amend DKN-…-n GIỮ id dòng + ngày ghi nợ (dồn trả trước); đã trả → NO_NCC_KHOA (⚠K);
		dòng trả trước không sửa được (⚠K)."""
		p = self._pn(100000)
		no = self._dong(p)
		self._loi(self._sua_no("QL", no, {"amount": "x"}), "22P02", 'invalid input syntax for type numeric: "x"')
		self.assertEqual(self._ok(self._sua_no("QL", no, {"notes": "x"})), [])
		han = add_days(nowdate(), 30)
		self.assertEqual(self._ok(self._sua_no("KT", no, {"invoice_number": "HD-MOI", "due_date": han, "notes": "ghi chu moi"})), [{"id": no}])
		self.assertEqual(frappe.db.get_value("Purchase Invoice", p, ["bill_no", "npp_han_thanh_toan", "npp_ghi_chu_no"], as_dict=True),
			{"bill_no": "HD-MOI", "npp_han_thanh_toan": getdate(han), "npp_ghi_chu_no": "ghi chu moi"})
		self.assertEqual({k: self._no(no)[k] for k in ("invoice_number", "notes")}, {"invoice_number": "HD-MOI", "notes": "ghi chu moi"})
		self.assertEqual(self._ok(self._sua_no("KT", no, {"notes": None})), [{"id": no}])
		self.assertEqual(self._no(no)["notes"], "")  # ⚠K Q9 §7.3 điểm 14: xoá ghi chú = rỗng (NULL = chữ hệ thống)
		for g in ({"amount": 99}, {"paid": 1}, {"supplier_id": self.ma["S2"]}, {"stock_entry_id": None}, {"opening_balance": True},
				{"created_at": "2026-01-01T00:00:00+07:00"}):
			self._loi(self._sua_no("KT", no, g), "P0001", L.KHOA_SUA)
		# gửi lại đúng giá trị cũ (màn Sửa thông tin gửi đủ ba ô) — không đổi gì, không lỗi
		self.assertEqual(self._ok(self._sua_no("KT", no, {"amount": 100000, "paid": 0, "status": "open"})), [{"id": no}])
		self._ok(self._sua_no("KT", no, {"status": "overdue"}))
		self.assertEqual((frappe.db.get_value("Purchase Invoice", p, "npp_qua_han_tay"), self._no(no)["status"]), (1, "overdue"))
		self._ok(self._ghi_tra("KT", no, 1000))
		self._loi(self._sua_no("KT", no, {"status": "open"}), "P0001", "NO_NCC_KHOA: trạng thái open không khớp số đã trả 1000 / 100000")
		self._ok(self._sua_no("KT", no, {"status": "partial"}))
		self.assertEqual((frappe.db.get_value("Purchase Invoice", p, "npp_qua_han_tay"), self._no(no)["status"]), (0, "partial"))
		# nợ đầu kỳ chưa trả: đổi số = amend, giữ id dòng + ngày ghi nợ + ngày ghi sổ
		dk = self._ok(self._them_no("KT", supplier_id=self.ma["S2"], amount=3000, opening_balance=True))[0]["id"]
		cu = frappe.db.get_value(N.DT, dk, "chung_tu")
		luc = frappe.db.get_value(N.DT, dk, "tao_luc")
		self._loi(self._sua_no("KT", dk, {"status": "paid"}), "P0001", "NO_NCC_KHOA: trạng thái paid không khớp số đã trả 0 / 3000")
		self.assertEqual(self._ok(self._sua_no("KT", dk, {"amount": 5000, "status": "open"})), [{"id": dk}])
		moi = frappe.db.get_value(N.DT, dk, "chung_tu")
		self.assertEqual(moi, f"{cu}-1")
		self.assertEqual(frappe.db.get_value("Purchase Invoice", cu, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", moi, ["docstatus", "amended_from", "grand_total", "is_opening", "posting_date"],
			as_dict=True), {"docstatus": 1, "amended_from": cu, "grand_total": 5000, "is_opening": "Yes",
			"posting_date": frappe.db.get_value("Purchase Invoice", cu, "posting_date")})
		self.assertEqual((self._no(dk)["amount"], frappe.db.get_value(N.DT, dk, "tao_luc")), (5000, luc))
		self._loi(self._sua_no("KT", dk, {"amount": 0}), "P0001", L.KHOA_SUA)
		c = self._ok(self._chi("KT", 1000, "S2"))
		self.assertEqual(self._no(dk)["paid"], 1000)
		self._loi(self._sua_no("KT", dk, {"amount": 6000}), "P0001", L.KHOA_SUA)  # ⚠K: đã trả → không amend
		# nợ lập tay KHÔNG gắn phiếu kho: số nợ chỉ đổi được ở khoản ĐẦU KỲ (luật mig 227) — lập tay → NO_NCC_KHOA, tờ giữ nguyên
		t = self._ok(self._them_no("KT", supplier_id=self.ma["S2"], amount=4000, invoice_number="TAY"))[0]["id"]
		pi_t = frappe.db.get_value(N.DT, t, "chung_tu")
		self._loi(self._sua_no("KT", t, {"amount": 4500}), "P0001", L.KHOA_SUA)
		self.assertEqual((frappe.db.get_value(N.DT, t, "chung_tu"), frappe.db.get_value("Purchase Invoice", pi_t, "docstatus"), self._no(t)["amount"]),
			(pi_t, 1, 4000))
		# dòng trả trước: mọi đổi → NO_NCC_KHOA
		c = self._ok(self._chi("KT", 500, "S3"))
		tt = frappe.db.get_value(N.DT, {"phieu_chi": c["id"], "loai": "tra_truoc"}, "name")
		self._loi(self._sua_no("KT", tt, {"notes": "x"}), "P0001", L.KHOA_SUA)

	def test_quyen_san_doc_ncc(self):
		"""DocPerm sàn ĐỌC Supplier (`thiet_lap.quyen_san.SAN`): Payment Entry.validate kiểm quyền đọc NCC khi kiểm số phân bổ (payment_entry.py:499 /
		:2489) — phiếu chi / Ghi trả lập dưới chính kế toán, thiếu quyền → 42501 (lỗi lượt đầu của M3). Gỡ quyền đọc NCC của các vai NPP rồi chạy
		lại `dam_bao()` (như lúc migrate) → lập lại được."""
		from nppsale.thiet_lap import quyen_san
		from nppsale.thiet_lap.vai import VAI_ROLE

		# lõi chỉ kiểm quyền đọc NCC khi phiếu có tham chiếu để phân bổ (phiếu chỉ toàn trả trước không qua đường ấy) → NCC phải có khoản nợ
		self._ok(self._them_no("KT", supplier_id=self.ma["S3"], amount=1000, opening_balance=True))
		self.addCleanup(frappe.clear_cache, doctype="Supplier")
		frappe.db.sql("UPDATE `tabCustom DocPerm` SET `read` = 0, `select` = 0 WHERE `parent` = 'Supplier' AND `role` IN %(vai)s",
			{"vai": tuple(VAI_ROLE.values())})
		frappe.clear_cache(doctype="Supplier")
		ket = self._chi("KT", 500, "S3")
		self.assertEqual(ket.get("error", {}).get("code"), "42501", ket)
		quyen_san.dam_bao()
		self.assertEqual(self._ok(self._chi("KT", 500, "S3"))["so_khoan"], 1)

	def test_sua_so_dau_ky_goi_don(self):
		"""§7.3 điểm 27: sửa số nợ đầu kỳ chưa trả = tờ `DKN-` amend ghi sổ mới → GỌI dồn trả trước (nppsale không dồn ở đây; nợ ròng không đổi). Trạng
		thái "NCC còn tiền trả trước + khoản đầu kỳ chưa trả" (như sau gộp NCC — M8, nppsale không dồn khi gộp) dựng bằng cách tắt dồn lúc thêm khoản."""
		c = self._ok(self._chi("KT", 2000, "S2"))  # NCC chưa có khoản nào → cả 2.000 là trả trước
		tt = frappe.db.get_value(N.DT, {"phieu_chi": c["id"], "loai": "tra_truoc"}, "name")
		with patch.object(N, "don_tra_truoc_ncc", lambda *a, **k: 0.0):
			dk = self._ok(self._them_no("KT", supplier_id=self.ma["S2"], amount=3000, opening_balance=True))[0]["id"]
		self.assertEqual((self._no(dk)["paid"], self._no(tt)["amount"], self._no(tt)["paid"]), (0, 0, 2000))
		self.assertEqual(self._ok(self._sua_no("KT", dk, {"amount": 5000})), [{"id": dk}])
		self.assertEqual({k: self._no(dk)[k] for k in ("amount", "paid", "status")}, {"amount": 5000, "paid": 2000, "status": "partial"})
		self.assertEqual([(x["supplier_payment_id"], x["amount"]) for x in self._tra(dk)], [(c["id"], 2000)])
		self.assertIsNone(frappe.db.exists(N.DT, tt))  # trả trước dồn hết → dòng trả trước xoá

	def test_cong_xoa_no(self):
		"""Xoá: RLS (vai khác 0 dòng) → trigger (đã trả / có dòng tiền) → khoá ngoại 23503 của phiếu nhập / phiếu trả NCC (§7.3 điểm 38) → tờ DKN- /
		NTN- chưa trả: huỷ tờ."""
		p = self._pn(100000)
		r = self._ptn(30000)
		t = self._ok(self._them_no("KT", amount=2000, invoice_number="TAY"))[0]["id"]
		self.assertEqual(self._ok(self._cong("QL", {"bang": "payables", "hanh_dong": "delete", "select": "id", "loc": [{"op": "eq", "cot": "id",
			"gt": t}]})), [])
		self._loi(self._cong("KT", {"bang": "payables", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "id", "gt": self._dong(p)}]}),
			"23503", L.loi_fk_xoa("phieu_nhap", "x").thong_diep)
		self._loi(self._cong("KT", {"bang": "payables", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "id", "gt": self._dong(r)}]}),
			"23503", L.loi_fk_xoa("tra_ncc", "x").thong_diep)
		pi = frappe.db.get_value(N.DT, t, "chung_tu")
		self.assertEqual(self._ok(self._cong("KT", {"bang": "payables", "hanh_dong": "delete", "select": "id", "loc": [{"op": "eq", "cot": "id",
			"gt": t}]})), [{"id": t}])
		self.assertEqual((frappe.db.get_value("Purchase Invoice", pi, "docstatus"), frappe.db.exists(N.DT, t)), (2, None))
		dk = self._ok(self._them_no("KT", amount=2000, opening_balance=True))[0]["id"]
		self._ok(self._ghi_tra("KT", dk, 1))
		self._loi(self._cong("KT", {"bang": "payables", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "id", "gt": dk}]}), "P0001", L.KHOA_XOA)
		c = self._ok(self._chi("KT", 500, "S3"))
		tt = frappe.db.get_value(N.DT, {"phieu_chi": c["id"], "loai": "tra_truoc"}, "name")
		self._loi(self._cong("KT", {"bang": "payables", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "id", "gt": tt}]}), "P0001", L.KHOA_XOA)

	# ------------------------------------------------------------------------------------------------ cổng payable_payments / supplier_payments
	def test_cong_dong_tien_chi_xac_nhan(self):
		"""payable_payments: thêm → CHI_NCC_KHOA mọi vai (trigger trước RLS); sửa CHỈ `verified_by / verified_at` (chủ / kế toán) → dấu xác nhận của dòng
		tham chiếu / dòng bút toán / phiếu chi (dòng trả trước); đổi cột khác → CHI_NCC_KHOA; vai khác 0 dòng. supplier_payments: thêm → 42501, sửa /
		xoá → 0 dòng. Thủ kho / NVBH không đọc được ba bảng."""
		p = self._pn(100000)
		self._ptn(30000)
		no = self._dong(p)
		g = self._ok(self._ghi_tra("KT", no, 1000))[0]["payment_id"]
		b = self._ok(self._ghi_tra("KT", no, 2000, "offset"))[0]["payment_id"]
		c = self._ok(self._chi("KT", 500, "S3"))
		for nguoi in ("QL", "NV", "KT"):
			self._loi(self._cong(nguoi, {"bang": "payable_payments", "hanh_dong": "insert", "gia_tri": {"payable_id": no, "amount": 1}}),
				"P0001", L.CHI_NCC_KHOA)
		luc = f"{nowdate()}T10:00:00+07:00"
		for ten, dt, ten_dt in ((g, "Payment Entry Reference", g), (b, "Journal Entry Account", b), (f"{c['id']}::tra_truoc", "Payment Entry",
				c["id"])):
			loc = [{"op": "eq", "cot": "id", "gt": ten}]
			self.assertEqual(self._ok(self._cong("QL", {"bang": "payable_payments", "hanh_dong": "update", "select": "id",
				"gia_tri": {"verified_by": self.ma["u:QL"]}, "loc": loc})), [])
			self._loi(self._cong("KT", {"bang": "payable_payments", "hanh_dong": "update", "gia_tri": {"verified_by": self.ma["u:KT"], "notes": "x"},
				"loc": loc}), "P0001", L.CHI_NCC_KHOA)
			self.assertEqual(self._ok(self._cong("KT", {"bang": "payable_payments", "hanh_dong": "update", "select": "id, verified_by",
				"gia_tri": {"verified_by": self.ma["u:KT"], "verified_at": luc}, "loc": loc})), [{"id": ten, "verified_by": self.ma["u:KT"]}])
			self.assertEqual(frappe.db.get_value(dt, ten_dt, "npp_xac_nhan_boi"), self.ma["u:KT"])
		self._loi(self._cong("KT", {"bang": "payable_payments", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "id", "gt": g}]}),
			"P0001", L.CHI_NCC_KHOA)
		self.assertEqual(self._ok(self._cong("QL", {"bang": "payable_payments", "hanh_dong": "delete", "select": "id",
			"loc": [{"op": "eq", "cot": "id", "gt": g}]})), [])
		self._loi(self._cong("KT", {"bang": "supplier_payments", "hanh_dong": "insert", "gia_tri": {"supplier_id": self.ma["S1"], "amount": 1,
			"method": "cash"}}), "42501", 'new row violates row-level security policy for table "supplier_payments"')
		for hd in ("update", "delete"):
			self.assertEqual(self._ok(self._cong("KT", {"bang": "supplier_payments", "hanh_dong": hd, "select": "id", "gia_tri": {"notes": "x"},
				"loc": [{"op": "eq", "cot": "id", "gt": c["id"]}]})), [])
		self.assertEqual(frappe.db.get_value("Payment Entry", c["id"], ["docstatus", "npp_ghi_chu"], as_dict=True), {"docstatus": 1, "npp_ghi_chu": None})
		for nguoi in ("TK", "NV"):
			for bang in ("payables", "payable_payments", "supplier_payments"):
				self.assertEqual(self._ok(self._cong(nguoi, {"bang": bang, "select": "id"})), [], (nguoi, bang))
		self.assertTrue(self._ok(self._cong("QL", {"bang": "payable_payments", "select": "id", "loc": [{"op": "eq", "cot": "id", "gt": g}]})))
		# câu đọc của màn (chi tiết công nợ / chi tiết phiếu chi / Chi phí): bảng lồng theo đúng tên khoá ngoại nppsale
		d = self._ok(self._cong("KT", {"bang": "payable_payments", "select": "id, payer:users!payable_payments_paid_by_fkey(full_name, role), "
			"verifier:users!payable_payments_verified_by_fkey(full_name, role), payable:payables(id, invoice_number, opening_balance, created_at)",
			"loc": [{"op": "eq", "cot": "id", "gt": g}]}))[0]
		self.assertEqual((d["payer"]["role"], d["verifier"]["role"], d["payable"]["id"], d["payable"]["opening_balance"]),
			("accountant", "accountant", no, False))
		d = self._ok(self._cong("KT", {"bang": "payables", "select": "id, supplier:suppliers(name, code, phone, address, payment_terms)",
			"loc": [{"op": "eq", "cot": "id", "gt": no}]}))[0]
		self.assertEqual(d["supplier"]["code"], "NCC01")
		d = self._ok(self._cong("KT", {"bang": "supplier_payments", "select": "id, code, supplier:suppliers(name, code), "
			"dong:payable_payments(amount, payable:payables(invoice_number))", "loc": [{"op": "eq", "cot": "id", "gt": c["id"]}]}))[0]
		self.assertEqual((d["code"], d["supplier"], [(x["amount"], x["payable"]["invoice_number"]) for x in d["dong"]]),
			(c["id"], {"name": "NCC Ba", "code": None}, [(500, c["id"])]))

	# ------------------------------------------------------------------------------------------------ RPC đọc
	def _tong(self, nguoi, p_since):
		return self._ok(self._rpc(nguoi, "payables_summary", {"p_since": p_since}))[0]

	def test_doc_tong_hop(self):
		"""payables_summary (mig 231): còn nợ = Σ(amount − paid) dòng chưa `paid` — KHÔNG kẹp dòng âm / dòng trả trước; phát sinh = Σ amount dòng gắn
		phiếu kho có ngày ghi nợ ≥ p_since (chuỗi không múi giờ = giờ VN — §7.3 điểm 24; gồm dòng âm của phiếu trả, bỏ nợ đầu kỳ / lập tay không phiếu
		kho / trả trước). payables_by_supplier (mig 239): nhóm theo NCC, hàng trả lại = Σ(−amount) dòng phiếu trả, xếp còn lại giảm dần, mã thiếu → '-'.
		Vai không đọc được `payables` → [{0, 0}] / []."""
		hom_nay = f"{nowdate()}T00:00:00"
		goc, goc_mai = self._tong("KT", hom_nay), self._tong("KT", f"{add_days(nowdate(), 1)}T00:00:00")
		self.assertEqual(self._tong("TK", hom_nay), {"open_payables": 0, "month_total": 0})
		self.assertEqual(self._ok(self._rpc("TK", "payables_by_supplier", {})), [])
		p = self._pn(200000)
		self._ptn(50000)
		self._ok(self._them_no("KT", amount=100000, opening_balance=True))
		self._ok(self._chi("KT", 600000, p_paid_date=add_days(nowdate(), -6)))  # trả hết 300.000 nợ dương, dư 300.000 (dòng âm không ăn)
		self._ok(self._them_no("KT", supplier_id=self.ma["S3"], amount=7000, stock_entry_id=p))
		t = self._tong("KT", hom_nay)
		# còn nợ: dòng âm −50.000 + trả trước (0 − 300.000) + lập tay S3 7.000; phát sinh: PN 200.000 + dòng âm −50.000 + lập tay gắn PN 7.000
		self.assertEqual((t["open_payables"] - goc["open_payables"], t["month_total"] - goc["month_total"]), (-343000, 157000))
		t = self._tong("KT", f"{add_days(nowdate(), 1)}T00:00:00")
		self.assertEqual(t["month_total"] - goc_mai["month_total"], 0)
		ds = [r for r in self._ok(self._rpc("QL", "payables_by_supplier", {})) if r["supplier_id"] in (self.ma["S1"], self.ma["S3"])]
		self.assertEqual(ds, [
			{"supplier_id": self.ma["S3"], "supplier_name": "NCC Ba", "supplier_code": "-", "invoice_count": 1, "total_debt": 7000, "total_paid": 0,
				"remaining": 7000, "overdue_count": 0, "total_returned": 0},
			{"supplier_id": self.ma["S1"], "supplier_name": "NCC Một", "supplier_code": "NCC01", "invoice_count": 2, "total_debt": -50000,
				"total_paid": 300000, "remaining": -350000, "overdue_count": 0, "total_returned": 50000}])

	# ------------------------------------------------------------------------------------------------ Huỷ phiếu nhập — DA_TRA_TIEN
	def test_huy_phieu_nhap_da_tra_tien(self):
		"""mig 242 bước 6: tiền Ghi trả (GTN-) / bù trừ (CTN-) thẳng vào phiếu chặn huỷ — số in thô; phần phiếu chi (PCNCC-) KHÔNG chặn: lõi gỡ phân
		bổ, tiền về trả trước rồi dồn sang khoản khác."""
		p1 = self._pn(100000, "S2")
		p2 = self._pn(50000, "S2")
		c = self._ok(self._chi("CHU", 120000, "S2"))
		self.assertEqual(c["so_khoan"], 2)
		self.assertEqual(self._ok(self._rpc("CHU", "cancel_purchase_invoice", {"p_invoice_id": p1, "p_reason": "nhập nhầm"})), p1)
		self.assertIsNone(self._dong(p1))
		self.assertEqual((self._no(self._dong(p2))["paid"], self._no(self._dong(p2))["status"]), (50000, "paid"))
		self.assertEqual(flt(frappe.db.get_value(N.DT, {"phieu_chi": c["id"], "loai": "tra_truoc"}, "da_tra")), 70000)
		p3 = self._pn(80000, "S2")  # khoản mới ăn 70.000 trả trước
		self.assertEqual(self._no(self._dong(p3))["paid"], 70000)
		self._ok(self._ghi_tra("KT", self._dong(p3), 2500))
		self._loi(self._rpc("TK", "cancel_purchase_invoice", {"p_invoice_id": p3, "p_reason": "x"}), "P0001", L.loi_da_tra_tien(2500).ma)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", p3, "docstatus"), 1)

	# ------------------------------------------------------------------------------------------------ khám sổ dòng tiền NCC (dòng 66)
	def test_kham_so_dong_tien(self):
		"""nppsale.kham_so.quet_dong_chi_ncc: sổ do method lập thì sạch; dòng chiếu lệch số đã trả (23), một phiếu chi hai lúc chi (25), dòng tiền
		của phiếu chi trỏ dòng âm (26) bị bắt."""
		from nppsale.cong.bang import cong_no_ncc as CN
		from nppsale.kham_so import quet_dong_chi_ncc

		p = self._pn(100000)
		r = self._ptn(30000)
		self._ok(self._chi("KT", 150000))  # 100.000 trừ nợ P + 50.000 trả trước — hai dòng của cùng phiếu chi
		ncc = [self.ma["S1"]]
		self.assertEqual(quet_dong_chi_ncc(ncc), [])
		# 25: nguồn thật lấy lúc chi từ chính phiếu (mọi dòng một lúc) — giả lập nguồn lệch lúc chi ở dòng trả trước để ghim bộ dò
		dau = ("SELECT CONCAT(p.`name`, '::tra_truoc'), n.`name`, n.`da_tra`, " + CN.HINH_THUC + ", " + CN.NGUOI.format(o="p.`owner`") + ", "
			+ CN.LUC_CHI)
		self.assertEqual(CN.NGUON_TRA_NO.count(dau), 1)
		with patch.object(CN, "NGUON_TRA_NO", CN.NGUON_TRA_NO.replace(dau, dau[: -len(CN.LUC_CHI)] + f"DATE_ADD({CN.LUC_CHI}, INTERVAL 1 HOUR)")):
			self.assertEqual([d["nhom"] for d in quet_dong_chi_ncc(ncc)], [25])
		frappe.db.set_value(N.DT, self._dong(p), "da_tra", 1, update_modified=False)
		self.assertEqual([d["nhom"] for d in quet_dong_chi_ncc(ncc)], [23])
		N.chieu_phieu_nhap(p)
		ref = frappe.db.get_value("Payment Entry Reference", {"reference_name": p, "parenttype": "Payment Entry"}, "name")
		frappe.db.set_value("Payment Entry Reference", ref, "reference_name", r, update_modified=False)
		self.assertIn(26, [d["nhom"] for d in quet_dong_chi_ncc(ncc)])
