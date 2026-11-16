"""Công nợ NCC (P4 — M0): bản chiếu `NPP Cong No NCC` theo sổ (đặc tả kho_mua §2.8), dồn trả trước NCC (`_don_tra_truoc_ncc` mig 242), khám sổ
phía NCC, cài đặt site §2.11 + bộ kiểm cài đặt, hàm kho dùng chung (gói lô Inward / Outward, lô theo kho, kho nhận theo hạn) — cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_cong_no_ncc

Chứng từ dựng thẳng bằng lõi (Purchase Invoice / Payment Entry / Journal Entry) — RPC phiếu nhập / trả NCC / phiếu chi (M1–M3) sau này đi qua cùng
hook + hàm chiếu này. Số mong theo nppsale: nợ PN dương, trả NCC âm `open`, dòng trả trước `amount 0` / `paid` = phần chưa dồn, dồn "nợ đầu kỳ
trước, rồi cũ nhất trước", không đụng dòng âm.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, get_datetime, getdate, now_datetime, nowdate

from nppsale.luat.tim import khoa_tim_ds
from nppsale.su_kien import cong_no_ncc as N
from nppsale.tests import test_xuat_hang as XH
from nppsale.tests.test_tao_don import dung_nen
from nppsale.thiet_lap.kho_mua import cai_dat_kho

SERIES = {"phieu_nhap": "PN-.####", "tra_ncc": "PTNCC-.####", "dau_ky": "DKN-.####", "lap_tay": "NTN-.####"}


class TestCongNoNcc(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		with open(XH.VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)

	def setUp(self):
		frappe.db.savepoint("npp_test")
		# việc đêm / hàm nền có commit: trong bài chặn commit — commit thật làm mất điểm lui, dữ liệu bài nằm lại sổ (và tiêu số PN- / PCNCC-…);
		# Error Log là bảng MyISAM (không theo giao dịch) — ghi thật là nằm lại sổ dù lùi điểm lui: bắt vào danh sách
		self.nhat_ky = []
		for p in (patch.object(frappe.db, "commit", lambda *a, **k: None),
				patch.object(frappe, "log_error", lambda title=None, message=None, **k: self.nhat_ky.append(title))):
			p.start()
			self.addCleanup(p.stop)
		frappe.local._npp_cai_dat_ban = None
		self.ma = dung_nen(self.vang["nen"])
		self.cd = cai_dat_kho()
		self.tk_no = frappe.get_cached_value("Company", self.cd.cong_ty, "default_payable_account")
		self.tk_tien = frappe.get_cached_value("Company", self.cd.cong_ty, "default_cash_account")
		self.tk_cp = frappe.get_cached_value("Company", self.cd.cong_ty, "default_expense_account")
		self.cc = frappe.get_cached_value("Company", self.cd.cong_ty, "cost_center")
		self.uom = frappe.db.get_single_value("Stock Settings", "stock_uom") or "Nos"
		self.ncc = self._ncc("VTD NCC Cong No A")
		self.ncc_b = self._ncc("VTD NCC Cong No B")

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_cai_dat_ban = None
		frappe.local._npp_ngu_canh = None

	# ------------------------------------------------------------------------------------------------ dựng chứng từ
	def _ncc(self, ten: str) -> str:
		return frappe.get_doc({"doctype": "Supplier", "supplier_name": ten,
			"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")}).insert(ignore_permissions=True).name

	def _pi(self, ncc: str, tien: float, loai: str = "phieu_nhap", *, ngay=None, bill_no=None, luc=None, submit=True, **them):
		"""Tờ nợ một dòng không mã hàng (như tờ `DK-` của nợ đầu kỳ khách) — chỉ để chiếu công nợ; tờ có kho ở bài gói lô."""
		la_tra = loai == "tra_ncc"
		pi = frappe.new_doc("Purchase Invoice")
		pi.update({"naming_series": SERIES[loai], "supplier": ncc, "company": self.cd.cong_ty, "posting_date": ngay or nowdate(),
			"set_posting_time": 1, "bill_no": bill_no, "is_return": 1 if la_tra else 0, "update_stock": 0, "disable_rounded_total": 1,
			"npp_loai": loai, "is_opening": "Yes" if loai == "dau_ky" else "No", "npp_hoan_thanh_luc": luc, "taxes_and_charges": "", **them})
		pi.append("items", {"item_name": loai, "description": loai, "qty": -1 if la_tra else 1, "rate": tien, "conversion_factor": 1, "uom": self.uom,
			"expense_account": self.cd.tk_tam_dau_ky if loai == "dau_ky" else self.tk_cp, "cost_center": self.cc})
		pi.set("taxes", [])
		pi.flags.ignore_permissions = True
		pi.insert()
		if submit:
			pi.submit()
		return pi

	def _pe(self, ncc: str, tien: float, loai: str = "phieu_chi_ncc", *, ngay=None, ref: dict | None = None, xac_nhan: str | None = None):
		pe = frappe.new_doc("Payment Entry")
		pe.update({"naming_series": "PCNCC-.####" if loai == "phieu_chi_ncc" else "GTN-.####", "payment_type": "Pay",
			"company": self.cd.cong_ty, "posting_date": ngay or nowdate(), "mode_of_payment": self.cd.hinh_thuc["cash"], "party_type": "Supplier",
			"party": ncc, "paid_from": self.tk_tien, "paid_to": self.tk_no, "paid_amount": tien, "received_amount": tien,
			"source_exchange_rate": 1, "target_exchange_rate": 1, "npp_loai": loai})
		for pi, x in (ref or {}).items():
			pe.append("references", {"reference_doctype": "Purchase Invoice", "reference_name": pi, "allocated_amount": x})
		if xac_nhan:
			pe.update({"npp_xac_nhan_boi": xac_nhan, "npp_xac_nhan_luc": now_datetime()})
		pe.flags.ignore_permissions = True
		pe.insert()
		pe.submit()
		return pe

	def _je(self, ve: list[tuple], loai: str | None, voucher_type: str = "Journal Entry", phieu_nhap: str | None = None):
		"""ve: [(tài khoản, nợ, có, NCC | None, tham chiếu | None)] — tham chiếu: tên PI hoặc (loại, tên)."""
		je = frappe.new_doc("Journal Entry")
		je.update({"voucher_type": voucher_type, "company": self.cd.cong_ty, "posting_date": nowdate(), "npp_loai": loai,
			"npp_phieu_nhap": phieu_nhap})
		for tk, no, co, ncc, ref in ve:
			loai_ref, ten_ref = ref if isinstance(ref, tuple) else ("Purchase Invoice" if ref else None, ref)
			je.append("accounts", {"account": tk, "debit_in_account_currency": no, "credit_in_account_currency": co,
				"party_type": "Supplier" if ncc else None, "party": ncc, "reference_type": loai_ref, "reference_name": ten_ref,
				"cost_center": self.cc})
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		return je

	def _dong(self, khoa: str):
		return frappe.db.get_value(N.DT, {"khoa_nguon": khoa}, ["name", "loai", "nha_cung_cap", "ten_ncc", "chung_tu", "phieu_chi", "khoa_cho",
			"so_hd_ncc", "tim_kd", "phieu_kho", "so_tien", "da_tra", "con_no", "han_thanh_toan", "trang_thai", "qua_han_tay", "ghi_chu", "tao_luc",
			"tinh_luc"], as_dict=True)

	def _so(self, khoa: str) -> tuple:
		r = self._dong(khoa)
		return (flt(r.so_tien), flt(r.da_tra), flt(r.con_no), r.trang_thai) if r else None

	# ------------------------------------------------------------------------------------------------ bản chiếu
	def test_phieu_nhap_ghi_so_huy(self):
		luc = get_datetime("2026-11-10 09:30:00")
		pn = self._pi(self.ncc, 100000, bill_no="HD-NCC/0012", luc=luc)
		r = self._dong(f"Purchase Invoice:{pn.name}")
		self.assertTrue(pn.name.startswith("PN-"), pn.name)
		self.assertEqual((r.loai, r.nha_cung_cap, r.ten_ncc, r.chung_tu, r.phieu_chi, r.khoa_cho, r.phieu_kho),
			("phieu_nhap", self.ncc, "VTD NCC Cong No A", pn.name, None, None, pn.name))
		self.assertEqual((flt(r.so_tien), flt(r.da_tra), flt(r.con_no), r.trang_thai, r.qua_han_tay), (100000, 0, 100000, "open", 0))
		self.assertEqual((r.so_hd_ncc, r.tim_kd), ("HD-NCC/0012", khoa_tim_ds("HD-NCC/0012")))
		self.assertEqual(r.ghi_chu, f"Phiếu nhập hàng {pn.name}")  # chữ hệ thống của complete_purchase_invoice (§7.3 điểm 14)
		self.assertEqual(get_datetime(r.tao_luc), luc)  # ngày ghi nợ = lúc hoàn thành (không lấy creation của dòng chiếu)
		# huỷ phiếu → xoá dòng (payables không có trạng thái cancelled)
		pn.reload()
		pn.flags.ignore_permissions = True
		pn.cancel()
		self.assertIsNone(self._dong(f"Purchase Invoice:{pn.name}"))

	def test_tra_ncc_dong_am_va_truong_aos(self):
		tra = self._pi(self.ncc, 30000, "tra_ncc")
		khoa = f"Purchase Invoice:{tra.name}"
		r = self._dong(khoa)
		self.assertTrue(tra.name.startswith("PTNCC-"), tra.name)
		self.assertEqual((r.loai, flt(r.so_tien), flt(r.da_tra), flt(r.con_no), r.trang_thai), ("tra_ncc", -30000, 0, -30000, "open"))
		self.assertEqual((r.so_hd_ncc, r.phieu_kho, r.ghi_chu), (tra.name, tra.name, f"Hoàn trả NCC — phiếu {tra.name}"))
		self.assertEqual(get_datetime(r.tao_luc), get_datetime(tra.creation))  # chưa có npp_hoan_thanh_luc → creation
		# sửa ở màn công nợ (trường AOS): số HĐ NCC, hạn, ghi chú công nợ riêng — chiếu lại ngay
		tra.reload()
		tra.update({"bill_no": "TL-77", "npp_han_thanh_toan": add_days(nowdate(), 5), "npp_ghi_chu_no": "Đã gọi NCC"})
		tra.flags.ignore_permissions = True
		tra.save()
		r = self._dong(khoa)
		self.assertEqual((r.so_hd_ncc, r.tim_kd, str(r.han_thanh_toan), r.ghi_chu), ("TL-77", khoa_tim_ds("TL-77"), add_days(nowdate(), 5),
			"Đã gọi NCC"))
		tra.reload()
		tra.npp_ghi_chu_no = ""  # người dùng xoá ghi chú: rỗng, không quay về chữ hệ thống
		tra.flags.ignore_permissions = True
		tra.save()
		self.assertEqual(self._dong(khoa).ghi_chu, "")

	def test_qua_han_tay_giu_toi_khi_du_va_tra_du_la_open(self):
		pn = self._pi(self.ncc, 100000, ngay=add_days(nowdate(), -40))
		khoa = f"Purchase Invoice:{pn.name}"
		pn.reload()
		pn.npp_qua_han_tay = 1
		pn.flags.ignore_permissions = True
		pn.save()
		self.assertEqual(self._so(khoa), (100000, 0, 100000, "overdue"))
		self._pe(self.ncc, 40000, "ghi_tra_ncc", ref={pn.name: 40000})
		self.assertEqual(self._so(khoa), (100000, 40000, 60000, "overdue"))  # BP §4.3.0: dấu tay giữ (nppsale: RPC ghi đè — §7.3 điểm 13)
		self._pe(self.ncc, 60000, "ghi_tra_ncc", ref={pn.name: 60000})
		self.assertEqual(self._so(khoa), (100000, 100000, 0, "paid"))
		# bút toán làm giảm nợ dưới số đã trả (sửa giá giảm — DCN- Debit Note): trả dư là `open` (dư có, trừ vào tổng NCC)
		self._je([(self.tk_no, 10000, 0, self.ncc, pn.name), (self.tk_cp, 0, 10000, None, None)], "dieu_chinh_gia_nhap", "Debit Note", pn.name)
		self.assertEqual(self._so(khoa), (90000, 100000, -10000, "open"))

	def test_ghi_tra_mot_phan_va_huy_phieu(self):
		pn = self._pi(self.ncc, 100000)
		khoa = f"Purchase Invoice:{pn.name}"
		pe = self._pe(self.ncc, 40000, "ghi_tra_ncc", ref={pn.name: 40000})
		self.assertTrue(pe.name.startswith("GTN-"), pe.name)
		self.assertEqual(self._so(khoa), (100000, 40000, 60000, "partial"))
		self.assertIsNone(self._dong(f"Payment Entry:{pe.name}"))  # Ghi trả không có dòng trả trước
		pe.reload()
		pe.flags.ignore_permissions = True
		pe.cancel()
		self.assertEqual(self._so(khoa), (100000, 0, 100000, "open"))

	def test_dau_ky_mot_dong_moi_ncc(self):
		dk = self._pi(self.ncc, 50000, "dau_ky", ngay=add_days(nowdate(), -60))
		r = self._dong(f"Purchase Invoice:{dk.name}")
		self.assertTrue(dk.name.startswith("DKN-"), dk.name)
		self.assertEqual((r.loai, r.khoa_cho, r.phieu_kho, r.ghi_chu, flt(r.so_tien)), ("dau_ky", f"dau_ky:{self.ncc}", None, None, 50000))
		# lưới an toàn của uq_payables_opening: tờ đầu kỳ thứ hai của cùng NCC không ghi sổ được (method kiểm trước — §6.1 `payables`)
		self.assertTrue(self._pi(self.ncc_b, 1000, "dau_ky").name)
		hai = self._pi(self.ncc, 7000, "dau_ky", submit=False)
		hai.flags.ignore_permissions = True
		with self.assertRaises(frappe.UniqueValidationError):
			hai.submit()

	def test_lap_tay_phieu_kho_va_desk(self):
		ntn = self._pi(self.ncc, 25000, "lap_tay", npp_phieu_kho_loai="Purchase Invoice", npp_phieu_kho=self._pi(self.ncc, 1, submit=False).name)
		r = self._dong(f"Purchase Invoice:{ntn.name}")
		self.assertEqual((r.loai, r.phieu_kho, r.ghi_chu), ("lap_tay", ntn.npp_phieu_kho, None))
		# tờ lập trên Desk không có npp_loai: loại theo tiền tố / is_return (Σ dòng NCC vẫn bằng sổ)
		self.assertEqual(N.loai_cua_pi(None, "ACC-PINV-2026-00001", 1, "No"), "tra_ncc")
		self.assertEqual(N.loai_cua_pi(None, "ACC-PINV-2026-00002", 0, "Yes"), "dau_ky")
		self.assertEqual(N.loai_cua_pi("", "PTNCC-0009", 0, "No"), "tra_ncc")
		self.assertEqual(N.loai_cua_pi(None, "X-1", 0, "No"), "phieu_nhap")
		self.assertEqual(N.loai_cua_pi("lap_tay", "PN-0042", 0, "No"), "lap_tay")  # npp_loai của app thắng tiền tố tên

	# ------------------------------------------------------------------------------------------------ trả trước + dồn
	def test_phieu_chi_tra_truoc_va_don_no_dau_ky_truoc(self):
		nv = frappe.db.get_value("NPP Nhan Vien", {"user": self.ma["u:accountant"]}, "name")
		pn1 = self._pi(self.ncc, 100000, luc=get_datetime("2026-11-01 08:00:00"))
		tra = self._pi(self.ncc, 30000, "tra_ncc", luc=get_datetime("2026-10-01 08:00:00"))
		dk = self._pi(self.ncc, 50000, "dau_ky", luc=get_datetime("2026-11-05 08:00:00"), ngay=add_days(nowdate(), -30))
		pn2 = self._pi(self.ncc, 30000, luc=get_datetime("2026-11-03 08:00:00"))
		pe = self._pe(self.ncc, 120000, xac_nhan=nv)
		r = self._dong(f"Payment Entry:{pe.name}")
		self.assertEqual((r.loai, r.phieu_chi, r.chung_tu, r.so_hd_ncc, flt(r.so_tien), flt(r.da_tra), flt(r.con_no), r.trang_thai),
			("tra_truoc", pe.name, None, pe.name, 0, 120000, -120000, "open"))
		self.assertEqual(r.ghi_chu, f"Trả trước NCC — phiếu chi {pe.name}")
		self.assertEqual(get_datetime(r.tao_luc), get_datetime(pe.creation))  # chi hôm nay → lúc lập
		self.assertEqual(N.don_tra_truoc_ncc(self.ncc), 120000)
		# nợ đầu kỳ trước (dù ghi nợ sau), rồi cũ nhất trước; dòng âm (trả NCC) không đụng; hết tiền → xoá dòng trả trước
		self.assertEqual(self._so(f"Purchase Invoice:{dk.name}"), (50000, 50000, 0, "paid"))
		self.assertEqual(self._so(f"Purchase Invoice:{pn1.name}"), (100000, 70000, 30000, "partial"))
		self.assertEqual(self._so(f"Purchase Invoice:{pn2.name}"), (30000, 0, 30000, "open"))
		self.assertEqual(self._so(f"Purchase Invoice:{tra.name}"), (-30000, 0, -30000, "open"))
		self.assertIsNone(self._dong(f"Payment Entry:{pe.name}"))
		# tham chiếu mới chép dấu xác nhận cấp phiếu (mig 242); Σ phân bổ = tiền phiếu (BP §7.2 điểm 8)
		ref = frappe.get_all("Payment Entry Reference", filters={"parent": pe.name}, fields=["reference_name", "allocated_amount",
			"npp_xac_nhan_boi"], order_by="idx")
		self.assertEqual([(x.reference_name, flt(x.allocated_amount), x.npp_xac_nhan_boi) for x in ref], [(dk.name, 50000, nv), (pn1.name, 70000, nv)])
		self.assertEqual(flt(frappe.db.get_value("Payment Entry", pe.name, "unallocated_amount")), 0)
		self.assertEqual(N.don_tra_truoc_ncc(self.ncc), 0)  # không còn phiếu chi còn tiền → không làm gì
		self.assertEqual(N.don_tra_truoc_ncc(self.ncc_b), 0)

	def test_don_theo_luc_chi_ghi_lui_va_con_du(self):
		pn = self._pi(self.ncc, 50000)
		a = self._pe(self.ncc, 30000)  # chi hôm nay
		b = self._pe(self.ncc, 40000, ngay=add_days(nowdate(), -3))  # lập sau nhưng ghi lùi → lúc chi 12:00 ngày ấy → dồn TRƯỚC
		self.assertEqual(get_datetime(self._dong(f"Payment Entry:{b.name}").tao_luc),
			get_datetime(f"{add_days(nowdate(), -3)} 12:00:00"))
		self.assertEqual(N.don_tra_truoc_ncc(self.ncc), 50000)
		self.assertEqual(self._so(f"Purchase Invoice:{pn.name}"), (50000, 50000, 0, "paid"))
		self.assertIsNone(self._dong(f"Payment Entry:{b.name}"))  # b dồn hết 40.000 trước
		self.assertEqual(self._so(f"Payment Entry:{a.name}"), (0, 20000, -20000, "open"))  # a còn 20.000 trả trước
		# nợ mới của NCC → method gọi dồn (thay trigger AFTER INSERT payables) — lấy nốt phần còn của a
		pn2 = self._pi(self.ncc, 15000)
		self.assertEqual(self._so(f"Payment Entry:{a.name}"), (0, 20000, -20000, "open"))  # hook KHÔNG tự dồn (method quyết thứ tự)
		self.assertEqual(N.don_tra_truoc_ncc(self.ncc), 15000)
		self.assertEqual((self._so(f"Purchase Invoice:{pn2.name}"), self._so(f"Payment Entry:{a.name}")),
			((15000, 15000, 0, "paid"), (0, 5000, -5000, "open")))

	def test_huy_phieu_nhap_tien_ve_tra_truoc_roi_don_tiep(self):
		pn1 = self._pi(self.ncc, 60000, luc=get_datetime("2026-11-01 08:00:00"))
		pn2 = self._pi(self.ncc, 60000, luc=get_datetime("2026-11-02 08:00:00"))
		pe = self._pe(self.ncc, 60000)
		N.don_tra_truoc_ncc(self.ncc)
		self.assertEqual(self._so(f"Purchase Invoice:{pn1.name}"), (60000, 60000, 0, "paid"))
		self.assertIsNone(self._dong(f"Payment Entry:{pe.name}"))
		pn1.reload()
		pn1.flags.ignore_permissions = True
		pn1.cancel()  # lõi gỡ phân bổ (unlink_payment_on_cancellation_of_invoice) — hook chiếu lại dòng trả trước của NCC
		self.assertIsNone(self._dong(f"Purchase Invoice:{pn1.name}"))
		self.assertEqual(self._so(f"Payment Entry:{pe.name}"), (0, 60000, -60000, "open"))
		self.assertEqual(N.don_tra_truoc_ncc(self.ncc), 60000)  # cancel_purchase_invoice gọi dồn sau huỷ (mig 242)
		self.assertEqual(self._so(f"Purchase Invoice:{pn2.name}"), (60000, 60000, 0, "paid"))
		self.assertIsNone(self._dong(f"Payment Entry:{pe.name}"))
		pe.reload()
		pe.flags.ignore_permissions = True
		pe.cancel()  # huỷ phiếu chi: nợ quay lại
		self.assertEqual(self._so(f"Purchase Invoice:{pn2.name}"), (60000, 0, 60000, "open"))

	def test_don_duoi_vai_ke_toan(self):
		"""Dồn chạy trong method của kế toán / chủ (chi_tra_ncc, huỷ PN…) — dưới chính người gọi, không phải Administrator."""
		pn = self._pi(self.ncc, 20000)
		pe = self._pe(self.ncc, 20000)
		frappe.set_user(self.ma["u:accountant"])
		try:
			self.assertEqual(N.don_tra_truoc_ncc(self.ncc), 20000)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(self._so(f"Purchase Invoice:{pn.name}"), (20000, 20000, 0, "paid"))
		self.assertIsNone(self._dong(f"Payment Entry:{pe.name}"))

	def test_but_toan_bu_tru_va_sua_gia(self):
		pn = self._pi(self.ncc, 100000)
		tra = self._pi(self.ncc, 30000, "tra_ncc")
		# bù trừ (CTN- Debit Note, npp_loai bu_tru_ncc): Nợ phải trả (PN) / Có phải trả (PTNCC) — hai dòng chiếu lại
		je = self._je([(self.tk_no, 30000, 0, self.ncc, pn.name), (self.tk_no, 0, 30000, self.ncc, tra.name)], "bu_tru_ncc", "Debit Note")
		self.assertEqual(self._so(f"Purchase Invoice:{pn.name}"), (100000, 30000, 70000, "partial"))
		self.assertEqual(self._so(f"Purchase Invoice:{tra.name}"), (-30000, -30000, 0, "paid"))  # dòng âm dùng hết → paid
		# sửa giá tăng (DCN-, npp_loai dieu_chinh_gia_nhap): số nợ = grand_total + chênh, đã trả không đổi
		dcn = self._je([(self.tk_cp, 5000, 0, None, None), (self.tk_no, 0, 5000, self.ncc, pn.name)], "dieu_chinh_gia_nhap", phieu_nhap=pn.name)
		self.assertEqual(self._so(f"Purchase Invoice:{pn.name}"), (105000, 30000, 75000, "partial"))
		for x in (dcn, je):
			x.reload()
			x.flags.ignore_permissions = True
			x.cancel()
		self.assertEqual((self._so(f"Purchase Invoice:{pn.name}"), self._so(f"Purchase Invoice:{tra.name}")),
			((100000, 0, 100000, "open"), (-30000, 0, -30000, "open")))

	def test_but_toan_tro_phieu_chi_tra_truoc(self):
		"""Bút toán vế NCC trỏ phiếu chi (vd. NCC hoàn lại một phần tiền trả trước — làm tay trên Desk): dòng trả trước của phiếu chiếu lại."""
		pe = self._pe(self.ncc, 120000)
		khoa = f"Payment Entry:{pe.name}"
		je = self._je([(self.tk_tien, 20000, 0, None, None), (self.tk_no, 0, 20000, self.ncc, ("Payment Entry", pe.name))], None)
		self.assertEqual(self._so(khoa), (0, 100000, -100000, "open"))
		je.reload()
		je.flags.ignore_permissions = True
		je.cancel()
		self.assertEqual(self._so(khoa), (0, 120000, -120000, "open"))

	def test_khoa_ncc_giu_khoa_dong_ncc_va_dong_no(self):
		"""`khoa_ncc` khoá dòng Supplier + mọi dòng công nợ của NCC: kết nối THỨ HAI `FOR UPDATE NOWAIT` bị chặn — hai lượt chi / dồn / huỷ cùng NCC
		xếp hàng (nppsale `_don_tra_truoc_ncc`: khoá cả sổ nợ của NCC). NCC phải là dòng đã commit sẵn trên site (dòng chèn trong bài tự mang khoá
		ngầm — không phân biệt được)."""
		ncc = frappe.db.sql(f"""SELECT s.`name` FROM `tabSupplier` s WHERE s.`name` NOT IN %(bo)s AND EXISTS (SELECT 1 FROM `tab{N.DT}` c
			WHERE c.`nha_cung_cap` = s.`name`) ORDER BY s.`name` LIMIT 1""", {"bo": (self.ncc, self.ncc_b)})
		if not ncc:
			self.skipTest("site chưa có NCC đã commit kèm dòng công nợ NCC")
		ncc = ncc[0][0]
		chinh = frappe.local.db
		frappe.connect(set_admin_as_user=False)
		kn2 = frappe.local.db
		frappe.local.db = chinh
		self.addCleanup(kn2.close)

		def thu(cau):
			frappe.local.db = kn2
			try:
				kn2.sql(cau, ncc)
				return "được"
			except Exception:  # NOWAIT gặp khoá → ném ngay
				return "bị chặn"
			finally:
				kn2.rollback()
				frappe.local.db = chinh

		ncc_kh = "SELECT `name` FROM `tabSupplier` WHERE `name` = %s FOR UPDATE NOWAIT"
		no_kh = f"SELECT `name` FROM `tab{N.DT}` WHERE `nha_cung_cap` = %s FOR UPDATE NOWAIT"
		try:
			self.assertEqual((thu(ncc_kh), thu(no_kh)), ("được", "được"))
			self.assertTrue(N.khoa_ncc(ncc))
			self.assertEqual((thu(ncc_kh), thu(no_kh)), ("bị chặn", "bị chặn"))
		finally:
			frappe.db.rollback()  # nhả khoá (lui về điểm lưu KHÔNG nhả khoá dòng); dựng lại điểm lưu cho tearDown
			frappe.db.savepoint("npp_test")

	# ------------------------------------------------------------------------------------------------ khám sổ
	def test_kham_so_ncc(self):
		from nppsale.kham_so import kham_so_cong_no_ncc, quet_cong_no_ncc

		pn = self._pi(self.ncc, 100000)
		tra = self._pi(self.ncc, 30000, "tra_ncc")
		pe = self._pe(self.ncc, 50000)
		N.don_tra_truoc_ncc(self.ncc)
		self._pe(self.ncc_b, 9000)  # NCC B chỉ có trả trước
		self.assertEqual(quet_cong_no_ncc([self.ncc, self.ncc_b]), [])
		# chiếu cũ (21) / chứng từ ghi sổ mất dòng — PI lẫn phiếu chi (22) / dòng mồ côi (22) / chứng từ ngoài nhóm (20)
		frappe.db.set_value(N.DT, {"khoa_nguon": f"Purchase Invoice:{pn.name}"}, {"con_no": 1, "trang_thai": "paid"}, update_modified=False)
		frappe.db.delete(N.DT, {"khoa_nguon": f"Purchase Invoice:{tra.name}"})
		pe_b = self._pe(self.ncc_b, 1000).name
		frappe.db.delete(N.DT, {"khoa_nguon": f"Payment Entry:{pe_b}"})
		mo_coi = frappe.get_doc({"doctype": N.DT, "khoa_nguon": "Purchase Invoice:KHONG-CO", "loai": "phieu_nhap", "nha_cung_cap": self.ncc_b,
			"trang_thai": "open"}).insert(ignore_permissions=True).name
		gtn = self._pe(self.ncc, 7000, "ghi_tra_ncc")  # Ghi trả không phân bổ: tiền không thuộc dòng nào → lệch tổng NCC
		nhom = sorted({(x["nhom"], x["chung_tu"]) for x in quet_cong_no_ncc([self.ncc, self.ncc_b])})
		dong_pn = frappe.db.get_value(N.DT, {"khoa_nguon": f"Purchase Invoice:{pn.name}"}, "name")
		self.assertEqual(nhom, sorted([(20, self.ncc), (20, self.ncc_b), (21, dong_pn), (22, tra.name), (22, pe_b), (22, mo_coi)]))
		self.assertIn(pe.name, frappe.get_all("Payment Entry", filters={"party": self.ncc, "npp_loai": "phieu_chi_ncc"}, pluck="name"))
		# việc đêm: chiếu lại NCC có Payment Ledger đổi → còn đúng lệch "tiền ngoài nhóm" (không tự sửa chứng từ; commit bị chặn ở setUp)
		kham_so_cong_no_ncc()
		con = sorted({(x["nhom"], x["chung_tu"]) for x in quet_cong_no_ncc([self.ncc, self.ncc_b])})
		self.assertEqual(con, [(20, self.ncc)])
		self.assertEqual(self.nhat_ky, ["Khám sổ công nợ NCC: 1 chỗ lệch"])
		gtn.reload()
		gtn.flags.ignore_permissions = True
		gtn.cancel()
		self.assertEqual(quet_cong_no_ncc([self.ncc, self.ncc_b]), [])

	def test_chieu_cong_no_ncc_ten_chung(self):
		"""Method gọi thẳng sau thao tác lõi không qua doc_events (vd. reconcile) — chiếu lại theo chứng từ nguồn."""
		pn = self._pi(self.ncc, 50000)
		pe = self._pe(self.ncc, 20000, "ghi_tra_ncc", ref={pn.name: 20000})
		khoa = f"Purchase Invoice:{pn.name}"
		for dt, ten in (("Payment Entry", pe.name), ("Purchase Invoice", pn.name)):
			frappe.db.set_value(N.DT, {"khoa_nguon": khoa}, {"con_no": 1, "da_tra": 0, "trang_thai": "open"}, update_modified=False)
			N.chieu_cong_no_ncc(dt, ten)
			self.assertEqual(self._so(khoa), (50000, 20000, 30000, "partial"), dt)
		with self.assertRaises(ValueError):
			N.chieu_cong_no_ncc("Sales Invoice", "HD-0001")

	def test_chieu_ncc_bat_dong_mo_coi(self):
		pn = self._pi(self.ncc, 1000)
		frappe.db.set_value("Purchase Invoice", pn.name, "docstatus", 2, update_modified=False)  # nguồn thôi ghi sổ mà hook không chạy
		frappe.get_doc({"doctype": N.DT, "khoa_nguon": "Purchase Invoice:KHONG-CO", "loai": "phieu_nhap", "nha_cung_cap": self.ncc,
			"trang_thai": "open", "so_tien": 5}).insert(ignore_permissions=True)
		N.chieu_ncc(self.ncc)
		self.assertEqual(frappe.get_all(N.DT, filters={"nha_cung_cap": self.ncc}, pluck="khoa_nguon"), [])

	# ------------------------------------------------------------------------------------------------ cài đặt + nền kho
	def test_cai_dat_va_bo_kiem(self):
		from nppsale.thiet_lap import kho_mua as KM

		self.assertEqual(KM.kiem(), [])
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock_for_batch", 1)
		frappe.db.set_single_value("Accounts Settings", "check_supplier_invoice_uniqueness", 1)
		frappe.db.set_single_value("Stock Settings", "role_allowed_to_create_edit_back_dated_transactions", "System Manager")
		frappe.db.set_value("Property Setter", {"doc_type": "Purchase Invoice Item", "field_name": "rate", "property": "precision"}, "value", "2")
		frappe.db.set_value("Supplier", self.ncc_b, "disabled", 1)
		lech = {(x["doi_tuong"], x["truong"]) for x in KM.kiem()}
		self.assertEqual(lech, {("Stock Settings", "allow_negative_stock_for_batch"), ("Accounts Settings", "check_supplier_invoice_uniqueness"),
			("Stock Settings", "role_allowed_to_create_edit_back_dated_transactions"), ("Purchase Invoice Item.rate", "precision"),
			("Supplier", self.ncc_b)})
		KM.dam_bao()
		self.assertEqual({(x["doi_tuong"], x["truong"]) for x in KM.kiem()}, {("Supplier", self.ncc_b)})  # dữ liệu NCC không tự sửa
		cd = cai_dat_kho()
		self.assertEqual((cd.nguong, cd.bang_gia_nhap, cd.tk_thue_dau_vao), (30, "Gia nhap", f"Thue GTGT dau vao - {cd.abbr}"))
		hooks = frappe.get_hooks("doc_events")
		self.assertIn("nppsale.su_kien.cong_no_ncc.sau_ghi_so_phieu_nhap", hooks["Purchase Invoice"]["on_submit"])
		self.assertIn("nppsale.su_kien.cong_no_ncc.sau_thanh_toan", hooks["Payment Entry"]["on_cancel"])
		self.assertIn("nppsale.su_kien.cong_no_ncc.sau_but_toan", hooks["Journal Entry"]["on_submit"])

	def test_goi_lo_nhap_tra_va_lo_theo_kho(self):
		"""Hàm kho dùng chung: phiếu nhập có kho → lô hạn trong ngưỡng vào THẲNG kho cận date (kho của dòng), gói lô Inward do app lập; tờ trả NCC
		lấy lô hạn cũ trước đọc từ Serial and Batch Entry của đúng kho, gói Outward; Batch tắt không được chọn."""
		from nppsale.luat.kho_mua import chon_lo_fefo
		from nppsale.rpc.goi_lo import gan_goi_lo, kho_nhan_lo, lap_goi_lo, lo_theo_kho

		hang = self.ma["P1"]
		frappe.db.set_value("Item", hang, {"has_batch_no": 1, "create_new_batch": 0, "has_expiry_date": 0})
		hn = getdate(nowdate())
		lo = {}
		for ma, han in (("VTD-M0-GAN", add_days(hn, 10)), ("VTD-M0-XA", add_days(hn, 200)), ("VTD-M0-GAN2", add_days(hn, 20))):
			frappe.get_doc({"doctype": "Batch", "batch_id": ma, "item": hang, "expiry_date": han}).insert(ignore_permissions=True)
			lo[ma] = han
		self.assertEqual((kho_nhan_lo("sale", lo["VTD-M0-GAN"], self.cd), kho_nhan_lo("sale", lo["VTD-M0-XA"], self.cd),
			kho_nhan_lo("date", lo["VTD-M0-XA"], self.cd), kho_nhan_lo("sale", None, self.cd)),
			(self.cd.kho_can_date, self.cd.kho_ban, self.cd.kho_can_date, self.cd.kho_ban))
		pn = frappe.new_doc("Purchase Invoice")
		pn.update({"naming_series": "PN-.####", "supplier": self.ncc, "company": self.cd.cong_ty, "posting_date": nowdate(), "set_posting_time": 1,
			"update_stock": 1, "set_warehouse": self.cd.kho_ban, "disable_rounded_total": 1, "npp_loai": "phieu_nhap", "taxes_and_charges": ""})
		for ma, sl in (("VTD-M0-GAN", 10), ("VTD-M0-XA", 5), ("VTD-M0-GAN2", 4)):
			kho = kho_nhan_lo("sale", lo[ma], self.cd)
			r = pn.append("items", {"item_code": hang, "qty": sl, "uom": "Lon", "conversion_factor": 1, "rate": 8000, "price_list_rate": 8000,
				"warehouse": kho})
			gan_goi_lo(r, lap_goi_lo("Inward", "Purchase Invoice", hang, kho, {ma: sl}, pn.posting_date, "08:00:00", self.cd.cong_ty))
		pn.set("taxes", [])
		pn.flags.ignore_permissions = True
		pn.insert()
		pn.submit()
		# dòng mang gói lô do app lập: use_serial_batch_fields = 0, không batch_no (PoC 1c / 9) — lõi giữ nguyên sau ghi sổ
		self.assertEqual({(x.use_serial_batch_fields, x.batch_no) for x in frappe.get_all("Purchase Invoice Item", filters={"parent": pn.name},
			fields=["use_serial_batch_fields", "batch_no"])}, {(0, None)})
		self.assertEqual({(x.batch_no, x.warehouse, flt(x.qty)) for x in frappe.get_all("Serial and Batch Entry", filters={"parent": ("in",
			[r.serial_and_batch_bundle for r in pn.items])}, fields=["batch_no", "warehouse", "qty"])},
			{("VTD-M0-GAN", self.cd.kho_can_date, 10), ("VTD-M0-XA", self.cd.kho_ban, 5), ("VTD-M0-GAN2", self.cd.kho_can_date, 4)})
		self.assertEqual(self._so(f"Purchase Invoice:{pn.name}"), (152000, 0, 152000, "open"))
		self.assertEqual(self._dong(f"Purchase Invoice:{pn.name}").phieu_kho, pn.name)
		self.assertEqual([(x.ma, x.ton) for x in lo_theo_kho(hang, self.cd.kho_can_date)], [("VTD-M0-GAN", 10), ("VTD-M0-GAN2", 4)])
		# trả NCC 12 từ kho cận date: hạn cũ trước → GAN 10 + GAN2 2; Batch tắt không được chọn
		kq = chon_lo_fefo(lo_theo_kho(hang, self.cd.kho_can_date), 12)
		self.assertEqual((kq.lay, kq.thieu), ([("VTD-M0-GAN", 10), ("VTD-M0-GAN2", 2)], 0))
		tra = frappe.new_doc("Purchase Invoice")
		tra.update({"naming_series": "PTNCC-.####", "supplier": self.ncc, "company": self.cd.cong_ty, "posting_date": nowdate(),
			"set_posting_time": 1, "is_return": 1, "update_stock": 1, "set_warehouse": self.cd.kho_can_date, "disable_rounded_total": 1,
			"npp_loai": "tra_ncc", "taxes_and_charges": ""})
		r = tra.append("items", {"item_code": hang, "qty": -12, "uom": "Lon", "conversion_factor": 1, "rate": 8000, "price_list_rate": 8000,
			"warehouse": self.cd.kho_can_date})
		gan_goi_lo(r, lap_goi_lo("Outward", "Purchase Invoice", hang, self.cd.kho_can_date, kq.lay, tra.posting_date, "09:00:00",
			self.cd.cong_ty))
		tra.set("taxes", [])
		tra.flags.ignore_permissions = True
		tra.insert()
		tra.submit()
		self.assertEqual([(x.ma, x.ton) for x in lo_theo_kho(hang, self.cd.kho_can_date)], [("VTD-M0-GAN2", 2)])
		self.assertEqual(self._so(f"Purchase Invoice:{tra.name}"), (-96000, 0, -96000, "open"))
		frappe.db.set_value("Batch", "VTD-M0-GAN2", "disabled", 1)
		self.assertEqual(lo_theo_kho(hang, self.cd.kho_can_date), [])
		self.assertEqual([x.ma for x in lo_theo_kho(hang, self.cd.kho_ban)], ["VTD-M0-XA"])
