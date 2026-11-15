"""Phiếu thu (P3d): create_cash_receipt / void_cash_receipt — chứng từ sổ (Payment Entry cùng tên, bút toán cấn trừ CTR-), bản chiếu công nợ,
thứ tự kiểm + câu lỗi nguyên văn hàm Postgres của nppsale. Bài vàng so Postgres thật: test_phieu_thu_vang (tools/vang_phieu_thu.py).

	bench --site poc.local run-tests --module nppsale.tests.test_phieu_thu
"""
from __future__ import annotations

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.tests import test_xuat_hang as XH
from nppsale.tests.test_tao_don import doi_khoa, dung_nen


def _kham(kh: str) -> list:
	from nppsale.kham_so import quet_cong_no

	return quet_cong_no([kh])


class TestPhieuThu(IntegrationTestCase):
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
		frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 0)
		frappe.local._npp_cai_dat_ban = None

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_ngu_canh = None
		frappe.local._npp_phieu_thu = None

	def _goi(self, nguoi: str, ten: str, ts: dict) -> dict:
		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None
		try:
			return api.rpc(ten=ten, tham_so=ts)
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	def _ok(self, nguoi: str, ten: str, ts: dict):
		kq = self._goi(nguoi, ten, ts)
		self.assertNotIn("error", kq, kq)
		return kq["data"]

	def _loi(self, nguoi: str, ten: str, ts: dict) -> dict:
		kq = self._goi(nguoi, ten, ts)
		self.assertIn("error", kq, kq)
		return kq["error"]

	def _hd(self, khoa_don: str | None = None) -> str:
		"""HĐ của tình huống vàng `xuat_du_mot_lo` (Xuất hàng thật qua cổng). `khoa_don`: client_request_id khác → đơn thứ hai."""
		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == "xuat_du_mot_lo")
		tao, xuat = t["buoc"][0], t["buoc"][1]
		p_tao = doi_khoa(tao["p"], self.ma)
		if khoa_don:
			p_tao = {**p_tao, "client_request_id": khoa_don}
		don = self._ok(tao["nguoi"], "create_order_with_lines", {"p": p_tao})[0]["order_id"]
		tc = XH.TestXuatHang._dong_xuat(self, don, xuat["dong"])
		p = {**XH.ngay_tuong_doi(xuat["p"]), "order_id": don, "lines": tc}
		return self._ok(xuat["nguoi"], "post_invoice", {"p": p})[0]["invoice_id"]

	def _no(self, hd: str) -> frappe._dict:
		return frappe.db.get_value("NPP Cong No", {"khoa_nguon": f"Sales Invoice:{hd}"}, ["name", "khach_hang", "so_tien", "da_thu", "con_no",
			"trang_thai"], as_dict=True)

	def test_lap_huy_va_cua_chan(self):
		hd = self._hd()
		no = self._no(hd)
		self.assertTrue(no and no.so_tien > 0, no)
		kh = no.khach_hang
		thu = 100000.0 if no.so_tien > 100000 else no.so_tien - 1
		# cửa chặn theo đúng thứ tự nppsale
		self.assertEqual(self._loi("sales_a", "create_cash_receipt", {"p": {"customer_id": kh, "lines": []}})["message"],
			"FORBIDDEN: bạn không có quyền lập phiếu thu")
		self.assertEqual(self._loi("owner", "create_cash_receipt", {"p": {"lines": [{"receivable_id": no.name, "amount": 1}]}})["message"],
			"CUSTOMER_REQUIRED: chưa chọn khách hàng")
		self.assertEqual(self._loi("owner", "create_cash_receipt", {"p": {"customer_id": kh, "use_credit": 1.5, "lines": []}})["message"],
			"BAD_AMOUNT: số dư có dùng phải là số đồng chẵn")
		e = self._loi("owner", "create_cash_receipt", {"p": {"customer_id": kh, "use_credit": "x", "lines": []}})
		self.assertEqual((e["code"], e["message"]), ("22P02", 'invalid input syntax for type numeric: "x"'))
		self.assertEqual(self._loi("owner", "create_cash_receipt", {"p": {"customer_id": kh, "lines": []}})["message"],
			"EMPTY_RECEIPT: chưa chọn khoản nào để thu")
		self.assertEqual(self._loi("owner", "create_cash_receipt", {"p": {"customer_id": kh, "lines": [{"receivable_id": no.name,
			"amount": no.so_tien + 1}]}})["message"], "BAD_RECEIVABLE_LINE: khoản nợ không hợp lệ hoặc thu vượt số còn nợ")
		self.assertEqual(self._loi("owner", "create_cash_receipt", {"p": {"customer_id": kh, "lines": [{"receivable_id": no.name,
			"amount": 10.5}]}})["message"], "BAD_RECEIVABLE_LINE: khoản nợ không hợp lệ hoặc thu vượt số còn nợ")
		self.assertEqual(self._loi("owner", "create_cash_receipt", {"p": {"customer_id": kh, "use_credit": 5000, "lines": [
			{"receivable_id": no.name, "amount": 1000}]}})["message"],
			"CREDIT_BALANCE_TOO_LOW: khách chỉ còn 0 số dư có, không rút được 5000")
		e = self._loi("owner", "create_cash_receipt", {"p": {"customer_id": kh, "method": "credit_applied", "lines": [
			{"receivable_id": no.name, "amount": 1000}]}})
		self.assertEqual((e["code"], e["message"]), ("23514", 'new row for relation "payments" violates check constraint "chk_payments_method_v2"'))
		e = self._loi("owner", "create_cash_receipt", {"p": {"customer_id": kh, "receipt_date": "", "lines": [
			{"receivable_id": no.name, "amount": 1000}]}})
		self.assertEqual((e["code"], e["message"]), ("22007", 'invalid input syntax for type date: ""'))
		self.assertFalse(frappe.db.exists("NPP Phieu Thu", {"khach_hang": kh}))  # mọi lỗi trên không ghi gì

		# lập: kế toán, chuyển khoản, có client_key, hai dòng cùng khoản (gộp)
		ngay = add_days(nowdate(), -1)
		p = {"customer_id": kh, "method": "transfer", "receipt_date": ngay, "notes": "", "client_key": "ck-1",
			"lines": [{"receivable_id": no.name, "amount": thu - 1000}, {"receivable_id": no.name, "amount": 1000}]}
		ten = self._ok("accountant", "create_cash_receipt", {"p": p})
		self.assertTrue(isinstance(ten, str) and ten.startswith("PTH-"), ten)
		self.assertEqual(self._ok("accountant", "create_cash_receipt", {"p": {**p, "lines": []}}), ten)  # gửi lại cùng khoá → phiếu cũ
		pt = frappe.get_doc("NPP Phieu Thu", ten)
		self.assertEqual((pt.trang_thai, pt.hinh_thuc, str(pt.ngay_thu), flt(pt.tien_thu), flt(pt.tong_chon), pt.client_key, pt.ghi_chu),
			("received", "transfer", str(ngay), thu, thu, "ck-1", ""))
		self.assertEqual([(d.loai, flt(d.so_tien), d.cong_no, d.hoa_don, d.chung_tu) for d in pt.dong], [("payment", thu, no.name, hd, hd)])
		pe = frappe.get_doc("Payment Entry", ten)
		self.assertEqual((pe.docstatus, flt(pe.paid_amount), pe.party, pe.mode_of_payment, pe.npp_loai, pe.npp_phieu_thu, str(pe.posting_date)),
			(1, thu, kh, "Chuyen khoan", "phieu_thu", ten, str(ngay)))
		self.assertEqual([(r.reference_name, flt(r.allocated_amount)) for r in pe.references], [(hd, thu)])
		self.assertEqual(pt.but_toan_tien, ten)
		sau = self._no(hd)
		self.assertEqual((flt(sau.da_thu), flt(sau.con_no), sau.trang_thai, sau.name), (thu, flt(no.so_tien) - thu, "partial", no.name))

		# huỷ
		self.assertEqual(self._loi("owner", "void_cash_receipt", {"p_receipt_id": "PTH-khong-co", "p_reason": "x"})["message"],
			"RECEIPT_NOT_FOUND")
		self.assertEqual(self._loi("sales_a", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "x"})["message"],
			"FORBIDDEN: bạn không có quyền huỷ phiếu thu")
		self.assertEqual(self._loi("owner", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "   "})["message"],
			"REASON_REQUIRED: phải ghi lý do huỷ phiếu thu")
		self.assertIsNone(self._ok("accountant", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": " Thu nhầm\n"}))
		pt.reload()
		self.assertEqual((pt.trang_thai, pt.ly_do_huy, pt.huy_boi), ("voided", " Thu nhầm\n", self.ma["u:accountant"]))
		self.assertEqual(len(pt.dong), 1)  # dòng giữ nguyên
		self.assertEqual(frappe.db.get_value("Payment Entry", ten, "docstatus"), 2)
		sau = self._no(hd)
		self.assertEqual((flt(sau.da_thu), flt(sau.con_no), sau.trang_thai), (0, flt(no.so_tien), "open"))
		self.assertEqual(self._loi("owner", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "x"})["message"],
			"RECEIPT_NOT_VOIDABLE: phiếu ở trạng thái voided không huỷ được")

	def test_qua_han_khi_huy(self):
		"""Huỷ phiếu: khoản bị gỡ hết tiền mà hạn đã qua → quá hạn (mig 120 / 227); lập phiếu thu chạm khoản → mất dấu."""
		hd = self._hd()
		no = self._no(hd)
		frappe.db.set_value("Sales Invoice", hd, "npp_han_thanh_toan", add_days(nowdate(), -3), update_modified=False)
		frappe.db.set_value("Sales Invoice", hd, "npp_qua_han_tay", 1, update_modified=False)
		from nppsale.su_kien.cong_no import chieu_hoa_don

		chieu_hoa_don(hd)
		self.assertEqual(self._no(hd).trang_thai, "overdue")
		ten = self._ok("owner", "create_cash_receipt", {"p": {"customer_id": no.khach_hang, "lines": [{"receivable_id": no.name, "amount": 1000}]}})
		self.assertEqual((frappe.db.get_value("Sales Invoice", hd, "npp_qua_han_tay"), self._no(hd).trang_thai), (0, "partial"))
		self._ok("owner", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "x"})
		self.assertEqual((frappe.db.get_value("Sales Invoice", hd, "npp_qua_han_tay"), self._no(hd).trang_thai), (1, "overdue"))

	def test_soat_bien(self):
		"""Soát P3d: ép kiểu của khối DECLARE / jsonb_array_elements nổ đúng chỗ như Postgres; biên quá hạn khi huỷ phiếu (CASE của
		void_cash_receipt + trigger mig 212) và khi PATCH status (no_dau_ky._co_qua_han); lý do huỷ HĐ chỉ bỏ dấu cách (btrim); đếm chứng từ
		của NV gồm phiếu thu (khoá ngoại người thu / người nhận / người huỷ, payments của phiếu chưa huỷ)."""
		from nppsale.rpc.nhan_vien import dem_chung_tu
		from nppsale.rpc.no_dau_ky import _co_qua_han
		from nppsale.rpc.phieu_thu import _qua_han_sau_huy

		hd = self._hd()
		no = self._no(hd)
		kh = no.khach_hang
		# (p->>'customer_id')::uuid ở DECLARE: chuỗi rỗng nổ trước cả FORBIDDEN
		e = self._loi("sales_a", "create_cash_receipt", {"p": {"customer_id": "", "lines": []}})
		self.assertEqual((e["code"], e["message"]), ("22P02", 'invalid input syntax for type uuid: ""'))
		# p->'lines' / p->'credits' là JSON null → jsonb_array_elements('null') nổ — sau BAD_AMOUNT
		for k in ("lines", "credits"):
			e = self._loi("owner", "create_cash_receipt", {"p": {"customer_id": kh, "lines": [{"receivable_id": no.name, "amount": 1000}], k: None}})
			self.assertEqual((e["code"], e["message"]), ("22023", "cannot extract elements from a scalar"), k)
		self.assertEqual(self._loi("owner", "create_cash_receipt", {"p": {"customer_id": kh, "use_credit": 1.5, "lines": None}})["message"],
			"BAD_AMOUNT: số dư có dùng phải là số đồng chẵn")
		self.assertFalse(frappe.db.exists("NPP Phieu Thu", {"khach_hang": kh}))

		# quá hạn sau huỷ phiếu: còn nợ ≥ 0,01, đã thu ≤ 0, số không âm, hạn đã qua
		frappe.db.set_value("NPP Cong No", no.name, "han_thanh_toan", add_days(nowdate(), -3), update_modified=False)
		for so_tien, da_thu, mong in ((100, 0, 1), (100, -50, 1), (100, 0.003, 0), (0.008, 0, 0), (-5, -10, 0), (100, 100, 0)):
			frappe.db.set_value("NPP Cong No", no.name, {"so_tien": so_tien, "da_thu": da_thu}, update_modified=False)
			_qua_han_sau_huy(hd)
			self.assertEqual(frappe.db.get_value("Sales Invoice", hd, "npp_qua_han_tay"), mong, (so_tien, da_thu))
		# PATCH status = 'overdue': trigger giữ khi chưa thu đủ (|còn| ≥ 0,01), không trả dư, số không âm
		self.assertEqual([_co_qua_han(100, x) for x in (99.99, 99.995, 0, 100, 101)], [1, 0, 1, 0, 0])
		self.assertEqual(_co_qua_han(-5, -10), 0)
		from nppsale.su_kien.cong_no import chieu_hoa_don

		frappe.db.set_value("Sales Invoice", hd, "npp_qua_han_tay", 0, update_modified=False)
		chieu_hoa_don(hd)

		# đếm chứng từ của NV: phiếu thu của kế toán (người lập + người thu + người nhận + payments), huỷ bởi chủ
		ke_toan, chu = self.ma["u:accountant"], self.ma["u:owner"]
		ten = self._ok("accountant", "create_cash_receipt", {"p": {"customer_id": kh, "lines": [{"receivable_id": no.name, "amount": 1000}]}})
		x = frappe.db.get_value("NPP Phieu Thu", ten, ["owner", "nguoi_thu", "nhan_boi"], as_dict=True)
		self.assertEqual((x.owner, x.nguoi_thu, x.nhan_boi), (ke_toan, ke_toan, ke_toan))
		ct = {(r["bang"], r["cot"]): r["so"] for r in dem_chung_tu(ke_toan)["chi_tiet"]}
		self.assertEqual({k: v for k, v in ct.items() if k[0] in ("cash_receipts", "payments")}, {("cash_receipts", "collected_by"): 1,
			("cash_receipts", "created_by"): 1, ("cash_receipts", "received_by"): 1, ("payments", "collected_by"): 1})
		ds = dem_chung_tu(ke_toan)["chi_tiet"]
		self.assertEqual(ds, sorted(ds, key=lambda r: (r["bang"], r["cot"])))
		self._ok("owner", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "x"})
		ct = {(r["bang"], r["cot"]): r["so"] for r in dem_chung_tu(ke_toan)["chi_tiet"]}
		self.assertNotIn(("payments", "collected_by"), ct)  # nppsale xoá payments khi huỷ phiếu
		self.assertEqual(ct[("cash_receipts", "collected_by")], 1)
		self.assertEqual({(r["bang"], r["cot"]): r["so"] for r in dem_chung_tu(chu)["chi_tiet"]}.get(("cash_receipts", "voided_by")), 1)

		# lý do huỷ HĐ: btrim() chỉ bỏ dấu cách — "\n" vẫn là lý do; số JSON thành chữ như tham số text của PostgREST
		self.assertEqual(self._loi("owner", "cancel_invoice", {"p_invoice_id": hd, "p_reason": "   "})["message"],
			"REASON_REQUIRED: phải ghi lý do huỷ hóa đơn")
		self._ok("owner", "cancel_invoice", {"p_invoice_id": hd, "p_reason": "\n"})
		self.assertEqual(frappe.db.get_value("Sales Invoice", hd, ["docstatus", "npp_ly_do_huy"]), (2, "\n"))
		hd2 = self._hd("00000000-0000-4000-8000-000000000002")
		self._ok("owner", "cancel_invoice", {"p_invoice_id": hd2, "p_reason": 5})
		self.assertEqual(frappe.db.get_value("Sales Invoice", hd2, "npp_ly_do_huy"), "5")

	def test_dung_du_co_phieu_tra(self):
		"""Dư có từ phiếu trả tự lập độc lập rút vào HĐ: bút toán CTR- hai vế, PE phần còn lại; huỷ trả lại cả hai vế."""
		hd = self._hd()
		no = self._no(hd)
		kh = no.khach_hang
		pt = self._ok("owner", "save_pos_return", {"p": {"customer_id": kh, "reason": "damaged", "zone": "sale", "lines": [
			{"product_id": self.ma["P1"], "unit_name": "Lon", "quantity": 2, "unit_price": 9500, "vat_rate": 0.08}]}})
		self._ok("owner", "complete_return", {"p_return_id": pt, "p_zone": "sale"})
		dong_tra = frappe.db.get_value("NPP Cong No", {"khoa_nguon": f"NPP Phieu Tra:{pt}"}, ["name", "so_tien", "con_no"], as_dict=True)
		self.assertEqual((flt(dong_tra.so_tien), flt(dong_tra.con_no)), (-20520, -20520))
		self.assertEqual(flt(no.so_tien), 26020)  # HĐ của tình huống vàng xuat_du_mot_lo
		self.assertEqual(self._loi("owner", "create_cash_receipt", {"p": {"customer_id": kh, "use_credit": 30000, "lines": [
			{"receivable_id": no.name, "amount": 26020}]}})["message"],
			"CREDIT_BALANCE_TOO_LOW: khách chỉ còn 20520 số dư có, không rút được 30000")
		self.assertEqual(self._loi("owner", "create_cash_receipt", {"p": {"customer_id": kh, "use_credit": 20000, "lines": [
			{"receivable_id": no.name, "amount": 10000}]}})["message"], "CREDIT_EXCEEDS_SELECTED: số dư có dùng vượt phần còn phải trả")
		ten = self._ok("accountant", "create_cash_receipt", {"p": {"customer_id": kh, "use_credit": 20520, "method": "cash", "lines": [
			{"receivable_id": no.name, "amount": 26020}]}})
		phieu = frappe.get_doc("NPP Phieu Thu", ten)
		self.assertEqual([(d.loai, flt(d.so_tien), d.cong_no) for d in phieu.dong], [("credit_applied", -20520, dong_tra.name),
			("credit_applied", 20520, no.name), ("payment", 5500, no.name)])
		self.assertEqual((flt(phieu.dung_du_co), flt(phieu.tien_thu)), (20520, 5500))
		je = frappe.get_doc("Journal Entry", phieu.but_toan_can_tru)
		self.assertTrue(je.name.startswith("CTR-"), je.name)
		to_ghi_co = frappe.db.get_value("NPP Phieu Tra", pt, "to_ghi_co")
		self.assertEqual(sorted((a.reference_name, flt(a.debit), flt(a.credit)) for a in je.accounts),
			sorted([(to_ghi_co, 20520, 0), (hd, 0, 20520)]))
		self.assertEqual(flt(frappe.db.get_value("Payment Entry", ten, "paid_amount")), 5500)
		self.assertEqual((flt(self._no(hd).da_thu), self._no(hd).trang_thai), (26020, "paid"))
		tra = frappe.db.get_value("NPP Cong No", dong_tra.name, ["so_tien", "da_thu", "con_no", "trang_thai"], as_dict=True)
		self.assertEqual((flt(tra.so_tien), flt(tra.da_thu), flt(tra.con_no), tra.trang_thai), (-20520, -20520, 0, "paid"))
		self.assertEqual(_kham(kh), [])
		# huỷ: đảo cả hai vế
		self._ok("accountant", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "x"})
		self.assertEqual((frappe.db.get_value("Journal Entry", je.name, "docstatus"), frappe.db.get_value("Payment Entry", ten, "docstatus")),
			(2, 2))
		self.assertEqual(flt(self._no(hd).da_thu), 0)
		self.assertEqual(flt(frappe.db.get_value("NPP Cong No", dong_tra.name, "con_no")), -20520)


class TestPhieuThuCong(TestPhieuThu):
	"""Cổng: cash_receipts / cash_receipt_lines / payments / cash_collections / receivables (ma trận ghi thẳng — đặc tả phiếu thu §4.0)."""

	def _nc(self, nguoi: str):
		from nppsale.cong.dang_ky import NguCanh

		u = self.ma["u:" + nguoi]
		return NguCanh(user=u, vai=frappe.db.get_value("NPP Nhan Vien", u, "vai"))

	def _doc(self, nguoi: str, yc: dict) -> list:
		from nppsale.cong.truy_van import doc

		return doc(yc, self._nc(nguoi))["data"]

	def _ghi(self, nguoi: str, yc: dict):
		from nppsale.cong.ghi import ghi

		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None
		try:
			return ghi(yc, self._nc(nguoi))
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	def _loi_ghi(self, nguoi: str, yc: dict) -> tuple[str, str]:
		from nppsale.cong.loi import NppLoi
		from nppsale.cong.sql import LoiCong

		try:
			self._ghi(nguoi, yc)
		except NppLoi as e:
			return (e.code, e.ma)
		except LoiCong as e:
			return (e.ma, e.thong_diep)
		self.fail(f"không lỗi: {yc}")

	def test_cong_phieu_thu(self):
		hd = self._hd()
		no = self._no(hd)
		ten = self._ok("accountant", "create_cash_receipt", {"p": {"customer_id": no.khach_hang, "method": "transfer", "lines": [
			{"receivable_id": no.name, "amount": 6020}], "notes": "ghi chu"}})
		loc = [{"op": "eq", "cot": "id", "gt": ten}]
		r = self._doc("accountant", {"bang": "cash_receipts", "select": "*", "loc": loc})
		self.assertEqual(len(r), 1)
		self.assertEqual(len(r[0]), 20)  # đúng 20 cột của nppsale
		self.assertEqual({k: r[0][k] for k in ("id", "receipt_code", "source_type", "status", "submitted_amount", "expected_amount",
			"collected_by", "received_by", "notes")}, {"id": ten, "receipt_code": ten, "source_type": "standalone", "status": "received",
			"submitted_amount": 6020, "expected_amount": 6020, "collected_by": self.ma["u:accountant"], "received_by": self.ma["u:accountant"],
			"notes": "ghi chu"})
		self.assertEqual(self._doc("sales_a", {"bang": "cash_receipts", "select": "id", "loc": loc}), [])  # NVBH: chỉ phiếu mình thu
		dong = self._doc("accountant", {"bang": "cash_receipt_lines", "select": "id, payment_id, receivable_id, invoice_id, kind, amount",
			"loc": [{"op": "eq", "cot": "receipt_id", "gt": ten}]})
		self.assertEqual([(d["payment_id"] == d["id"], d["receivable_id"], d["invoice_id"], d["kind"], d["amount"]) for d in dong],
			[(True, no.name, hd, "payment", 6020)])
		k = self._doc("accountant", {"bang": "payments", "select": "id, receivable_id, amount, method, collected_by",
			"loc": [{"op": "eq", "cot": "receivable_id", "gt": no.name}]})
		self.assertEqual([(x["id"], x["amount"], x["method"], x["collected_by"]) for x in k], [(dong[0]["id"], 6020, "transfer",
			self.ma["u:accountant"])])
		self.assertEqual(self._doc("warehouse", {"bang": "payments", "select": "id", "loc": [{"op": "eq", "cot": "receivable_id",
			"gt": no.name}]}), [])
		# ghi thẳng phiếu
		self.assertEqual(self._loi_ghi("owner", {"bang": "cash_receipts", "hanh_dong": "insert", "gia_tri": {"notes": "x"}}),
			("P0001", "PHIEU_THU_KHOA: phiếu thu chỉ lập / huỷ qua nút Lập phiếu thu, Huỷ phiếu thu"))
		self.assertEqual(self._ghi("accountant", {"bang": "cash_receipts", "hanh_dong": "update", "gia_tri": {"notes": "moi",
			"submitted_amount": 6020}, "loc": loc, "select": "id, notes, tim_kd"})["data"][0]["notes"], "moi")
		self.assertIn("moi", frappe.db.get_value("NPP Phieu Thu", ten, "tim_kd"))
		self.assertEqual(self._loi_ghi("accountant", {"bang": "cash_receipts", "hanh_dong": "update", "gia_tri": {"submitted_amount": 1},
			"loc": loc})[1], "PHIEU_THU_KHOA: phiếu thu chỉ lập / huỷ qua nút Lập phiếu thu, Huỷ phiếu thu")
		self.assertEqual(self._loi_ghi("accountant", {"bang": "cash_receipts", "hanh_dong": "update", "gia_tri": {"status": "voided"},
			"loc": loc})[1], "PHIEU_THU_KHOA: phiếu thu chỉ lập / huỷ qua nút Lập phiếu thu, Huỷ phiếu thu")
		self.assertEqual(self._ghi("accountant", {"bang": "cash_receipts", "hanh_dong": "delete", "loc": loc, "select": "id"})["data"], [])
		self.assertEqual(self._loi_ghi("owner", {"bang": "cash_receipts", "hanh_dong": "delete", "loc": loc})[1],
			"PHIEU_THU_KHOA: phiếu thu chỉ lập / huỷ qua nút Lập phiếu thu, Huỷ phiếu thu")
		self.assertEqual(self._loi_ghi("owner", {"bang": "cash_receipts", "hanh_dong": "update", "gia_tri": {"khong_co": 1}, "loc": loc})[0],
			"PGRST204")
		# dòng phiếu thu: cấm mọi ghi
		khoa_tien = "THU_TIEN_KHOA: tiền thu chỉ ghi / huỷ qua phiếu thu (lập phiếu thu, huỷ phiếu thu)"
		dloc = [{"op": "eq", "cot": "id", "gt": dong[0]["id"]}]
		self.assertEqual(self._loi_ghi("accountant", {"bang": "cash_receipt_lines", "hanh_dong": "update", "gia_tri": {"notes": "x"},
			"loc": dloc})[1], khoa_tien)
		self.assertEqual(self._ghi("accountant", {"bang": "cash_receipt_lines", "hanh_dong": "delete", "loc": dloc, "select": "id"})["data"], [])
		self.assertEqual(self._loi_ghi("sales_a", {"bang": "cash_receipt_lines", "hanh_dong": "insert", "gia_tri": {"amount": 1}})[1],
			khoa_tien)
		# khoản thu: chỉ xác nhận (chủ / kế toán); quản lý 0 dòng
		x = self._ghi("accountant", {"bang": "payments", "hanh_dong": "update", "gia_tri": {"verified_by": self.ma["u:accountant"],
			"verified_at": "2026-11-15T10:00:00+07:00", "amount": 6020}, "loc": dloc, "select": "id, verified_by, verified_at"})["data"]
		self.assertEqual((x[0]["verified_by"], str(x[0]["verified_at"])[:19]), (self.ma["u:accountant"], "2026-11-15T10:00:00"))
		self.assertEqual(self._ghi("manager", {"bang": "payments", "hanh_dong": "update", "gia_tri": {"verified_by": None}, "loc": dloc,
			"select": "id"})["data"], [])
		self.assertEqual(self._loi_ghi("owner", {"bang": "payments", "hanh_dong": "update", "gia_tri": {"amount": 1}, "loc": dloc})[1], khoa_tien)
		self.assertEqual(self._ghi("owner", {"bang": "payments", "hanh_dong": "delete", "loc": dloc, "select": "id"})["data"], [])
		# huỷ phiếu: khoản thu biến mất, dòng giữ, payment_id = NULL
		self._ok("accountant", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "x"})
		self.assertEqual(self._doc("accountant", {"bang": "payments", "select": "id", "loc": dloc}), [])
		self.assertEqual(self._doc("accountant", {"bang": "cash_receipt_lines", "select": "payment_id, amount", "loc": dloc}),
			[{"payment_id": None, "amount": 6020}])
		# chuyến giao cũ
		self.assertEqual(self._doc("owner", {"bang": "cash_collections", "select": "*"}), [])
		self.assertEqual(self._loi_ghi("owner", {"bang": "cash_collections", "hanh_dong": "insert", "gia_tri": {"notes": "x"}})[1],
			"LEGACY_FLOW_REMOVED: chức năng đã gỡ")

	def test_no_dau_ky(self):
		kh = self.ma["C2"]
		them = {"customer_id": kh, "amount": 500000, "paid": 0, "due_date": add_days(nowdate(), -2), "status": "open", "opening_balance": True,
			"note": "no cu"}
		chon = "id, amount, paid, status, opening_balance, note, due_date, invoice_id, customer_id"
		self.assertEqual(self._loi_ghi("manager", {"bang": "receivables", "hanh_dong": "insert", "gia_tri": them})[0], "42501")
		self.assertEqual(self._loi_ghi("accountant", {"bang": "receivables", "hanh_dong": "insert", "gia_tri": {**them,
			"opening_balance": False}})[1], "CONG_NO_KHOA: công nợ chỉ sinh từ hóa đơn / phiếu trả — màn hình chỉ thêm được nợ đầu kỳ chưa thu")
		self.assertEqual(self._loi_ghi("accountant", {"bang": "receivables", "hanh_dong": "insert", "gia_tri": {**them, "paid": 5}})[1],
			"CONG_NO_KHOA: công nợ chỉ sinh từ hóa đơn / phiếu trả — màn hình chỉ thêm được nợ đầu kỳ chưa thu")
		self.assertEqual(self._loi_ghi("accountant", {"bang": "receivables", "hanh_dong": "insert", "gia_tri": {**them, "amount": None}}),
			("23502", 'null value in column "amount" of relation "receivables" violates not-null constraint'))
		self.assertEqual(self._loi_ghi("accountant", {"bang": "receivables", "hanh_dong": "insert", "gia_tri": {**them, "amount": 0}})[1],
			"BAD_AMOUNT: nợ đầu kỳ phải là số đồng chẵn lớn hơn 0")
		r = self._ghi("accountant", {"bang": "receivables", "hanh_dong": "insert", "gia_tri": them, "select": chon})["data"][0]
		self.assertEqual({k: r[k] for k in ("amount", "paid", "status", "opening_balance", "note", "invoice_id", "customer_id")},
			{"amount": 500000, "paid": 0, "status": "open", "opening_balance": True, "note": "no cu", "invoice_id": None, "customer_id": kh})
		si = frappe.db.get_value("NPP Cong No", r["id"], "hoa_don")
		self.assertTrue(si.startswith("DK-"), si)
		self.assertEqual(frappe.db.get_value("Sales Invoice", si, ["is_opening", "docstatus", "grand_total"]), ("Yes", 1, 500000))
		self.assertEqual(self._loi_ghi("owner", {"bang": "receivables", "hanh_dong": "insert", "gia_tri": them}),
			("23505", 'duplicate key value violates unique constraint "uq_receivables_opening"'))
		loc = [{"op": "eq", "cot": "id", "gt": r["id"]}]
		# sửa số (chưa thu): amend DK-…-1, giữ id; đánh dấu quá hạn
		s = self._ghi("accountant", {"bang": "receivables", "hanh_dong": "update", "gia_tri": {"amount": 600000, "due_date": them["due_date"],
			"note": "no cu 2"}, "loc": loc, "select": chon})["data"]
		self.assertEqual([(x["id"], x["amount"], x["note"]) for x in s], [(r["id"], 600000, "no cu 2")])
		si2 = frappe.db.get_value("NPP Cong No", r["id"], "hoa_don")
		self.assertEqual((si2, frappe.db.get_value("Sales Invoice", si, "docstatus")), (f"{si}-1", 2))
		s = self._ghi("owner", {"bang": "receivables", "hanh_dong": "update", "gia_tri": {"status": "overdue"}, "loc": loc, "select": "status"})
		self.assertEqual(s["data"], [{"status": "overdue"}])
		self.assertEqual(self._ghi("manager", {"bang": "receivables", "hanh_dong": "update", "gia_tri": {"status": "open"}, "loc": loc,
			"select": "id"})["data"], [])
		self.assertEqual(self._loi_ghi("accountant", {"bang": "receivables", "hanh_dong": "update", "gia_tri": {"paid": 1}, "loc": loc})[1],
			"CONG_NO_KHOA: số nợ / số đã thu chỉ đổi qua hóa đơn, phiếu trả, phiếu thu (RPC)")
		# thu một phần → không xoá được; huỷ phiếu → còn dòng phiếu thu (đã huỷ) trỏ tới → 23503
		ten = self._ok("owner", "create_cash_receipt", {"p": {"customer_id": kh, "lines": [{"receivable_id": r["id"], "amount": 100000}]}})
		self.assertEqual(self._loi_ghi("accountant", {"bang": "receivables", "hanh_dong": "delete", "loc": loc})[1],
			"CONG_NO_KHOA: chỉ xoá được nợ đầu kỳ chưa thu đồng nào")
		self.assertEqual(self._loi_ghi("accountant", {"bang": "receivables", "hanh_dong": "update", "gia_tri": {"amount": 700000},
			"loc": loc})[1], "CONG_NO_KHOA: số nợ / số đã thu chỉ đổi qua hóa đơn, phiếu trả, phiếu thu (RPC)")
		self._ok("owner", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "x"})
		self.assertEqual(self._loi_ghi("accountant", {"bang": "receivables", "hanh_dong": "delete", "loc": loc})[0], "23503")
		# khách khác: thêm rồi xoá (trả dòng đọc TRƯỚC khi xoá); NVBH xoá 0 dòng
		r2 = self._ghi("owner", {"bang": "receivables", "hanh_dong": "insert", "gia_tri": {**them, "customer_id": self.ma["C1"]},
			"select": "id"})["data"][0]
		loc2 = [{"op": "eq", "cot": "id", "gt": r2["id"]}]
		self.assertEqual(self._ghi("owner", {"bang": "receivables", "hanh_dong": "delete", "loc": loc2, "select": "id, amount"})["data"],
			[{"id": r2["id"], "amount": 500000}])
		self.assertFalse(frappe.db.exists("NPP Cong No", r2["id"]))

	def test_rpc_doc_cong_no(self):
		"""receivables_by_customer / by_rep / summary, cash_received_total, bao_cao_cong_no — RLS người gọi, không kẹp 0, quá hạn theo dấu / theo hạn."""
		hd = self._hd()
		no = self._no(hd)
		dk = self._ghi("accountant", {"bang": "receivables", "hanh_dong": "insert", "gia_tri": {"customer_id": self.ma["C2"], "amount": 500000,
			"paid": 0, "due_date": add_days(nowdate(), -40), "status": "overdue", "opening_balance": True}, "select": "id, status"})["data"][0]
		self.assertEqual(dk["status"], "overdue")
		ten = self._ok("accountant", "create_cash_receipt", {"p": {"customer_id": no.khach_hang, "lines": [
			{"receivable_id": no.name, "amount": 6020}]}})
		kq = self._ok("owner", "receivables_by_customer", {})
		theo = {r["customer_id"]: r for r in kq}
		self.assertEqual({k: theo[self.ma["C2"]][k] for k in ("total_debt", "total_paid", "remaining", "overdue_amount", "rep_name")},
			{"total_debt": 500000, "total_paid": 0, "remaining": 500000, "overdue_amount": 500000, "rep_name": "-"})
		c1 = theo[no.khach_hang]
		self.assertEqual((c1["total_debt"], c1["total_paid"], c1["remaining"], c1["overdue_amount"]), (26020, 6020, 20000, 0))
		self.assertEqual([r["remaining"] for r in kq], sorted((r["remaining"] for r in kq), reverse=True))
		self.assertEqual(self._ok("warehouse", "receivables_by_customer", {}), [])
		rep = {r["full_name"]: r for r in self._ok("owner", "receivables_by_rep", {})}
		chua = rep["(Chưa gán nhân viên)"]
		self.assertEqual((chua["user_id"], chua["total_debt"], chua["overdue_amount"], chua["dso"], chua["collection_rate"]), (None, 500000, 500000, 40, 0))
		tom = self._ok("owner", "receivables_summary", {})
		self.assertEqual(len(tom), 1)
		self.assertEqual((tom[0]["total_outstanding"], tom[0]["overdue_amount"], tom[0]["overdue_count"]), (520000, 500000, 1))
		self.assertEqual(self._ok("warehouse", "receivables_summary", {})[0]["total_outstanding"], 0)
		self.assertEqual(self._ok("accountant", "cash_received_total", {"p_from": nowdate(), "p_to": nowdate()}), 6020)
		self.assertEqual(self._ok("sales_a", "cash_received_total", {"p_from": nowdate(), "p_to": nowdate()}), 0)  # phiếu người khác thu
		self.assertEqual(self._ok("owner", "cash_received_total", {"p_from": None, "p_to": nowdate()}), 0)
		bc = self._ok("owner", "bao_cao_cong_no", {"p_tu_thu": add_days(nowdate(), -180), "p_tu_90": add_days(nowdate(), -91)})
		self.assertEqual(sorted(p["id"] for p in bc["mo"]), sorted([no.name, dk["id"]]))
		self.assertEqual(sorted(p["id"] for p in bc["gan90"]), sorted([no.name, dk["id"]]))
		self.assertEqual([(t["amount"], t["method"], t["receivable"]["id"], t["receivable"]["invoice"]["invoice_code"]) for t in bc["thu"]],
			[(6020, "cash", no.name, hd)])
		self._ok("accountant", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "x"})
		self.assertEqual(self._ok("accountant", "cash_received_total", {"p_from": nowdate(), "p_to": nowdate()}), 0)

	def test_huy_hd_khoa_tien_thu(self):
		"""cancel_invoice (mig 125): (a) đã thu > 0; (b) còn dòng phiếu thu sống trỏ HĐ (kể cả rút dư có — đã thu ≤ 0); huỷ phiếu rồi mới huỷ được
		HĐ, dòng phiếu thu (đã huỷ) bỏ receivable_id, giữ invoice_id; tờ nợ đầu kỳ DK- không phải HĐ bán → INVOICE_NOT_FOUND."""
		hd = self._hd()
		no = self._no(hd)
		kh = no.khach_hang
		ten = self._ok("owner", "create_cash_receipt", {"p": {"customer_id": kh, "lines": [{"receivable_id": no.name, "amount": 1000}]}})
		khoa = "LOCKED_HAS_PAYMENT: hóa đơn đã có tiền thu, huỷ phiếu thu trước"
		self.assertEqual(self._loi("owner", "cancel_invoice", {"p_invoice_id": hd, "p_reason": "x"})["message"], khoa)
		self._ok("owner", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "x"})
		# (b): phiếu trả tự lập gắn HĐ vượt tiền HĐ → dòng HĐ dư có; phiếu thu khác rút dư có ấy → đã thu ≤ 0 mà vẫn khoá
		pt = self._ok("owner", "save_pos_return", {"p": {"customer_id": kh, "invoice_id": hd, "reason": "damaged", "zone": "sale", "lines": [
			{"product_id": self.ma["P1"], "unit_name": "Lon", "quantity": 3, "unit_price": 9500, "vat_rate": 0.08}]}})
		self._ok("owner", "complete_return", {"p_return_id": pt, "p_zone": "sale"})
		sau = self._no(hd)
		self.assertLess(flt(sau.con_no), 0, sau)
		dk = self._ghi("accountant", {"bang": "receivables", "hanh_dong": "insert", "gia_tri": {"customer_id": kh, "amount": 100000, "paid": 0,
			"opening_balance": True}, "select": "id"})["data"][0]
		rut = int(-flt(sau.con_no))
		ten2 = self._ok("owner", "create_cash_receipt", {"p": {"customer_id": kh, "use_credit": rut, "lines": [{"receivable_id": dk["id"],
			"amount": rut}]}})
		self.assertLessEqual(flt(self._no(hd).da_thu), 0)
		self.assertEqual(self._loi("owner", "cancel_invoice", {"p_invoice_id": hd, "p_reason": "x"})["message"], khoa)
		self._ok("owner", "void_cash_receipt", {"p_receipt_id": ten2, "p_reason": "x"})
		# tờ DK- không huỷ qua Huỷ HĐ
		dk_si = frappe.db.get_value("NPP Cong No", dk["id"], "hoa_don")
		self.assertEqual(self._loi("owner", "cancel_invoice", {"p_invoice_id": dk_si, "p_reason": "x"})["message"], "INVOICE_NOT_FOUND")
		_ = no

	def test_huy_hd_sau_khi_huy_phieu(self):
		hd = self._hd()
		no = self._no(hd)
		ten = self._ok("owner", "create_cash_receipt", {"p": {"customer_id": no.khach_hang, "lines": [{"receivable_id": no.name, "amount": 1000}]}})
		self._ok("owner", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "x"})
		self._ok("owner", "cancel_invoice", {"p_invoice_id": hd, "p_reason": "Khach tra lai hang"})
		self.assertFalse(frappe.db.exists("NPP Cong No", no.name))
		d = frappe.get_all("NPP Phieu Thu Dong", filters={"parent": ten}, fields=["cong_no", "hoa_don"])
		self.assertEqual([(x.cong_no, x.hoa_don) for x in d], [(None, hd)])  # bỏ receivable_id, giữ invoice_id (mig 125)

	def test_sua_hd_chuyen_tien_thu(self):
		"""reissue_invoice (mig 184): tiền thu đi theo tờ mới, số phiếu thu không đổi. Tờ mới nhỏ hơn số đã thu → phần vượt chuyển vào CHÍNH HĐ mới
		(bút toán `chuyen_tien_thua`, phương án B của Q1): dòng HĐ đã thu > phải thu = dư có như nppsale; sửa tăng lại → bút toán chuyển huỷ, tiền
		phân bổ lại đủ; huỷ phiếu → sạch."""
		hd = self._hd()
		no = self._no(hd)
		kh = no.khach_hang
		ten = self._ok("accountant", "create_cash_receipt", {"p": {"customer_id": kh, "lines": [{"receivable_id": no.name, "amount": 20000}]}})
		# giảm: P1 còn 1 lon → 10.260 + 5.500 = 15.760 < 20.000 đã thu
		hd2 = self._ok("owner", "reissue_invoice", {"p_invoice_id": hd, "p": {"lines": XH.TestXuatHang._dong_sua(self, hd,
			[[0, {"quantity": 1}], [1, {}]])}})[0]["invoice_id"]
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", hd2, "grand_total")), 15760)
		pe = frappe.get_doc("Payment Entry", ten)
		self.assertEqual((pe.docstatus, flt(pe.paid_amount), flt(pe.unallocated_amount)), (1, 20000, 4240))
		self.assertEqual([(r.reference_name, flt(r.allocated_amount)) for r in pe.references if flt(r.allocated_amount)], [(hd2, 15760)])
		chuyen = frappe.get_all("Journal Entry", filters={"npp_loai": "chuyen_tien_thua", "npp_phieu_thu": ten, "docstatus": 1}, pluck="name")
		self.assertEqual(len(chuyen), 1)
		self.assertEqual(sorted((a.reference_type, a.reference_name, flt(a.debit), flt(a.credit))
			for a in frappe.get_doc("Journal Entry", chuyen[0]).accounts),
			sorted([("Payment Entry", ten, 4240, 0), ("Sales Invoice", hd2, 0, 4240)]))
		moi = self._no(hd2)
		# dòng HĐ: đã thu 20.000 > phải thu 15.760 → còn nợ −4.240, 'open' (dư có — mig 212), như receivables của nppsale
		self.assertEqual((flt(moi.so_tien), flt(moi.da_thu), flt(moi.con_no), moi.trang_thai), (15760, 20000, -4240, "open"))
		self.assertFalse(frappe.db.exists("NPP Cong No", {"khoa_nguon": f"NPP Phieu Thu:{ten}"}))
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", hd2, "outstanding_amount")), -4240)
		d = frappe.get_all("NPP Phieu Thu Dong", filters={"parent": ten}, fields=["cong_no", "hoa_don", "chung_tu", "so_tien"])
		self.assertEqual([(x.cong_no, x.hoa_don, x.chung_tu, flt(x.so_tien)) for x in d], [(moi.name, hd2, hd2, 20000)])
		# Σ còn nợ của khách = −4.240 (đã thu đủ + 4.240 dư có)
		self.assertEqual(sum(flt(r.con_no) for r in frappe.get_all("NPP Cong No", filters={"khach_hang": kh}, fields=["con_no"])), -4240)
		self.assertEqual(_kham(kh), [])
		# lưới an toàn: bút toán chuyển bị huỷ NGOÀI app → tiền treo ở PE → dòng `tien_thua` giữ Σ nợ khớp sổ, khám sổ nhóm 13 báo
		frappe.db.savepoint("ngoai_app")
		je = frappe.get_doc("Journal Entry", chuyen[0])
		je.flags.ignore_permissions = True
		je.cancel()
		tt = frappe.db.get_value("NPP Cong No", {"khoa_nguon": f"NPP Phieu Thu:{ten}"}, ["loai", "con_no"], as_dict=True)
		self.assertEqual((tt.loai, flt(tt.con_no)), ("tien_thua", -4240))
		self.assertEqual(sum(flt(r.con_no) for r in frappe.get_all("NPP Cong No", filters={"khach_hang": kh}, fields=["con_no"])), -4240)
		self.assertEqual([(d["nhom"], d["loai"]) for d in _kham(kh)],
			[(13, "Phiếu thu còn tiền chưa phân bổ (Payment Entry treo tiền ngoài app)")])
		frappe.db.rollback(save_point="ngoai_app")
		self.assertEqual(frappe.db.get_value("Journal Entry", chuyen[0], "docstatus"), 1)
		# sửa tăng lại 2 lon → 26.020: bút toán chuyển huỷ, PE phân bổ lại đủ 20.000 vào tờ mới
		hd3 = self._ok("owner", "reissue_invoice", {"p_invoice_id": hd2, "p": {"lines": XH.TestXuatHang._dong_sua(self, hd2,
			[[0, {"quantity": 2}], [1, {}]])}})[0]["invoice_id"]
		ba = self._no(hd3)
		self.assertEqual((flt(ba.so_tien), flt(ba.da_thu), ba.trang_thai), (26020, 20000, "partial"))
		self.assertEqual(frappe.db.get_value("Journal Entry", chuyen[0], "docstatus"), 2)
		self.assertFalse(frappe.get_all("Journal Entry", filters={"npp_loai": "chuyen_tien_thua", "npp_phieu_thu": ten, "docstatus": 1}))
		self.assertFalse(frappe.db.exists("NPP Cong No", {"khoa_nguon": f"NPP Phieu Thu:{ten}"}))
		self.assertEqual(frappe.get_all("Payment Entry Reference", filters={"parent": ten, "allocated_amount": (">", 0)},
			fields=["reference_name", "allocated_amount"]), [{"reference_name": hd3, "allocated_amount": 20000}])
		self.assertEqual(flt(frappe.db.get_value("Payment Entry", ten, "unallocated_amount")), 0)
		# giảm lần nữa rồi huỷ phiếu: bút toán chuyển huỷ cùng phiếu — sạch
		hd4 = self._ok("owner", "reissue_invoice", {"p_invoice_id": hd3, "p": {"lines": XH.TestXuatHang._dong_sua(self, hd3,
			[[0, {"quantity": 1}], [1, {}]])}})[0]["invoice_id"]
		self.assertEqual(flt(self._no(hd4).con_no), -4240)
		self._ok("accountant", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "x"})
		self.assertFalse(frappe.get_all("Journal Entry", filters={"npp_loai": "chuyen_tien_thua", "npp_phieu_thu": ten, "docstatus": 1}))
		bon = self._no(hd4)
		self.assertEqual((flt(bon.da_thu), flt(bon.con_no), bon.trang_thai), (0, 15760, "open"))
		self.assertEqual(_kham(kh), [])

	def test_lap_lai_can_tru(self):
		"""Bút toán cấn trừ dư có giữ số từng vế khi chứng từ nó trỏ bị lập lại / huỷ (đặc tả phiếu thu §2.5.2, Q3): ghi nhận lại phiếu trả nguồn →
		trỏ tờ ghi có mới của cùng phiếu; đổi khách khi dư có đã dùng → RETURN_CREDIT_USED; Sửa HĐ được đắp → trỏ HĐ mới; huỷ phiếu trả nguồn →
		nợ "tự tăng lại" trên chính dòng phiếu trả (như _cong_no_phieu_tra mig 191 / 212)."""
		hd = self._hd()
		no = self._no(hd)
		kh = no.khach_hang
		dong = [{"product_id": self.ma["P1"], "unit_name": "Lon", "quantity": 2, "unit_price": 9500, "vat_rate": 0.08}]
		pt = self._ok("owner", "save_pos_return", {"p": {"customer_id": kh, "reason": "damaged", "zone": "sale", "lines": dong, "complete": True}})
		self.assertEqual(frappe.db.get_value("NPP Phieu Tra", pt, "trang_thai"), "completed")
		ten = self._ok("accountant", "create_cash_receipt", {"p": {"customer_id": kh, "use_credit": 20520, "lines": [
			{"receivable_id": no.name, "amount": 26020}]}})
		je1 = frappe.db.get_value("NPP Phieu Thu", ten, "but_toan_can_tru")
		dong_tra = frappe.db.get_value("NPP Cong No", {"khoa_nguon": f"NPP Phieu Tra:{pt}"}, "name")
		# đổi khách khi dư có đã dùng
		self.assertEqual(self._loi("owner", "save_pos_return", {"p": {"return_id": pt, "customer_id": self.ma["C2"], "reason": "damaged",
			"zone": "sale", "lines": dong, "complete": True}})["message"],
			"RETURN_CREDIT_USED: dư có của phiếu trả đã dùng ở phiếu thu của khách cũ — không đổi khách được")
		# ghi nhận lại với 1 lon: bút toán lập lại trỏ tờ ghi có mới, số từng vế giữ → dòng phiếu trả còn nợ 10.260
		self._ok("owner", "save_pos_return", {"p": {"return_id": pt, "customer_id": kh, "reason": "damaged", "zone": "sale",
			"lines": [{**dong[0], "quantity": 1}], "complete": True}})
		to_moi = frappe.db.get_value("NPP Phieu Tra", pt, "to_ghi_co")
		je2 = frappe.db.get_value("NPP Phieu Thu", ten, "but_toan_can_tru")
		self.assertNotEqual(je2, je1)
		self.assertEqual(frappe.db.get_value("Journal Entry", je2, "amended_from"), je1)
		vế = sorted((a.reference_name, flt(a.debit), flt(a.credit)) for a in frappe.get_doc("Journal Entry", je2).accounts)
		self.assertEqual(vế, sorted([(to_moi, 20520, 0), (hd, 0, 20520)]))
		r = frappe.db.get_value("NPP Cong No", dong_tra, ["so_tien", "da_thu", "con_no"], as_dict=True)
		self.assertEqual((flt(r.so_tien), flt(r.da_thu), flt(r.con_no)), (-10260, -20520, 10260))
		self.assertEqual(flt(self._no(hd).da_thu), 26020)
		# Sửa HĐ được đắp: bút toán trỏ HĐ mới
		hd2 = self._ok("owner", "reissue_invoice", {"p_invoice_id": hd, "p": {"lines": XH.TestXuatHang._dong_sua(self, hd, [[0, {}], [1, {}]])}})[0][
			"invoice_id"]
		je3 = frappe.db.get_value("NPP Phieu Thu", ten, "but_toan_can_tru")
		self.assertEqual(sorted((a.reference_name, flt(a.debit), flt(a.credit)) for a in frappe.get_doc("Journal Entry", je3).accounts),
			sorted([(to_moi, 20520, 0), (hd2, 0, 20520)]))
		self.assertEqual((flt(self._no(hd2).da_thu), self._no(hd2).trang_thai), (26020, "paid"))
		# huỷ phiếu trả nguồn: nợ tự tăng lại trên chính dòng phiếu trả (giữ dòng — phiếu thu còn trỏ tới)
		self._ok("owner", "cancel_return", {"p_return_id": pt, "p_reason": "x"})
		r = frappe.db.get_value("NPP Cong No", dong_tra, ["so_tien", "da_thu", "con_no"], as_dict=True)
		self.assertEqual((flt(r.so_tien), flt(r.con_no)), (0, 20520))
		self.assertEqual(sum(flt(x.con_no) for x in frappe.get_all("NPP Cong No", filters={"khach_hang": kh}, fields=["con_no"])), 20520)
		self.assertEqual(_kham(kh), [])
