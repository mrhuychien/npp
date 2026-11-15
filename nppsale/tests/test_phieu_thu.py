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

	def _hd(self) -> str:
		"""HĐ của tình huống vàng `xuat_du_mot_lo` (Xuất hàng thật qua cổng)."""
		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == "xuat_du_mot_lo")
		tao, xuat = t["buoc"][0], t["buoc"][1]
		don = self._ok(tao["nguoi"], "create_order_with_lines", {"p": doi_khoa(tao["p"], self.ma)})[0]["order_id"]
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
		# huỷ: đảo cả hai vế
		self._ok("accountant", "void_cash_receipt", {"p_receipt_id": ten, "p_reason": "x"})
		self.assertEqual((frappe.db.get_value("Journal Entry", je.name, "docstatus"), frappe.db.get_value("Payment Entry", ten, "docstatus")),
			(2, 2))
		self.assertEqual(flt(self._no(hd).da_thu), 0)
		self.assertEqual(flt(frappe.db.get_value("NPP Cong No", dong_tra.name, "con_no")), -20520)
