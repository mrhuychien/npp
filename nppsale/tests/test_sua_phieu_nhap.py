"""SỬA PHIẾU NHẬP ĐÃ HOÀN THÀNH (P4 — M7; đặc tả kho_mua §3.3) ngoài kịch bản vàng — cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_sua_phieu_nhap

Thứ tự kiểm + câu lỗi (§3.3 bước 1–16, §7.3 điểm 7 / 34), nhánh B chỉ sửa giá (LCV `SGN-` một chiều, bút toán `DCN-` cân, `npp_sua_gia` + phủ ở
cổng, repost giá vốn phần đã bán, giá nhập), huỷ / khôi phục / sửa tiếp sau sửa giá, nhánh A huỷ + amend (giữ lô, lô mới theo MỌI Batch, kho theo
hạn, tiền đã trả đi theo — phân bổ lại + bút toán chuyển trả dư, bù trừ lập lại), đổi NCC, lô bị rà soát sang kho date, hàng không lô lùi về nhánh
B, thứ tự khoá. Dựng trên bộ dữ liệu F của tệp vàng (các bước chạy bằng chính bộ bước của nppsale.tests.test_kho_mua_vang).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt

from nppsale.cong import bang as B
from nppsale.tests import test_kho_mua_vang as V
from nppsale.tests import test_xuat_hang as XH
from nppsale.thiet_lap.kho_mua import cai_dat_kho

DT = "Purchase Invoice"
CHI_SUA_GIA = ("PHIEU_DA_XUAT_CHI_SUA_GIA: Lô của phiếu đã xuất ở {} — chỉ sửa được giá; muốn đổi số lượng / mặt hàng / NCC / kho thì huỷ các HĐ "
	"đã lấy lô hoặc lập phiếu trả hàng NCC / điều chỉnh kho.")


class TestSuaPhieuNhap(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(V.VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)

	def setUp(self):
		frappe.db.savepoint("npp_test")
		self.repost = []
		for p in (patch.object(frappe.db, "commit", lambda *a, **k: None), patch.object(frappe, "log_error", lambda *a, **k: None),
				patch("nppsale.rpc.phieu_nhap._xep_repost", lambda: self.repost.append(1))):
			p.start()
			self.addCleanup(p.stop)
		frappe.local._npp_cai_dat_ban = None
		self.cd = cai_dat_kho()
		self.riv0 = set(frappe.get_all("Repost Item Valuation", pluck="name"))
		h = self.h = V.TestKhoMuaVang("test_kich_ban_vang")
		h.vang, h.cd, h.nhat_ky, h.repost = self.vang, self.cd, [], self.repost
		h.co_san = {dt: set() for dt in ("Purchase Invoice", "Batch", "NPP Cong No NCC", "Sales Invoice", "Item Price", "Payment Entry")}
		self.ma = h.ma = V.dung_nen_kho(self.vang["nen"])
		h.khoa_cua = {v: "@" + k for k, v in self.ma.items()}
		h.vung = {self.cd.kho_ban: "sale", self.cd.kho_can_date: "date"}
		self.st = {"ma": "T", "nhan": {}}

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_cai_dat_ban = None
		frappe.local._npp_ngu_canh = None

	# ------------------------------------------------------------------------------------------------ bước
	def _b(self, **b):
		return self.h._buoc(b, self.st)

	def _ok(self, **b):
		ket, tv = self._b(**b)
		self.assertNotIn("error", ket, f"{b['buoc']}: {ket.get('error')}")
		return tv

	@staticmethod
	def _dong(dong):
		ra = []
		for i, x in enumerate(dong, 1):
			sp, dv, sl, gia, *con = x
			giam, thue, hs = (list(con) + [0, 0, 1][len(con):])[:3]
			ra.append({"product_id": "@" + sp, "unit_name": dv, "quantity": sl, "unit_price": gia, "line_discount": giam, "vat_rate": thue,
				"conversion_factor": hs, "notes": None, "sort_order": i})
		return ra

	def _pn(self, nhan, dong, nguoi="TK", **dau) -> str:
		g = {"org_id": "@org", "supplier_id": "@S1", "invoice_number": None, "invoice_date": "@hom_nay", "warehouse_zone": "sale", "discount": 0,
			"vat_override": None, "notes": None, "status": "draft", **dau}
		self._ok(buoc="pn", nguoi=nguoi, nhan=nhan, dau=g, dong=self._dong(dong))
		self._ok(buoc="pn_hoan", nguoi=nguoi, nhan=nhan)
		return self._ten(nhan)

	def _ten(self, nhan) -> str:
		return self.h._ten(self.st, "pn:" + nhan)

	def _sua(self, nhan, dong, nguoi="KT", dau=None):
		d = {"supplier_id": "@S1", "invoice_number": None, "invoice_date": "@hom_nay", "warehouse_zone": "sale", "discount": 0, "vat_override": None,
			"notes": None} if dau is None else dau
		return self._b(buoc="pn_sua", nguoi=nguoi, nhan=nhan, dau=d, dong=self._dong(dong))

	def _rpc(self, nguoi, ten, ts):
		return self.h._goi(nguoi, ten, ts)

	def _loi(self, ket, cau, ma="P0001"):
		if isinstance(ket, tuple):  # kết quả của _b / _sua (cổng, số trả về)
			ket = ket[0]
		self.assertIn("error", ket, ket)
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), (ma, cau))

	def _ban(self, nhan, sp, dv, sl):
		return self._ok(buoc="ban", nguoi="CHU", nhan=nhan, dong=[{"product_id": "@" + sp, "unit_name": dv, "quantity": sl}])

	def _cong(self, yc):
		return V.doc_cong(yc, V.ADMIN)["data"]

	def _lo(self, ma) -> dict:
		"""{vùng: (tồn, giá vốn, nhập, trạng thái)} của lô qua cổng `batches`."""
		return {r["warehouse_zone"]: (flt(r["qty_on_hand"]), round(flt(r["unit_cost"]), 2), flt(r["qty_initial"]), r["status"])
			for r in self._cong({"bang": "batches", "select": "*", "loc": [{"op": "eq", "cot": "batch_code", "gt": ma}]})}

	def _no(self, pi) -> dict:
		return frappe.db.get_value("NPP Cong No NCC", {"chung_tu": pi}, ["so_tien", "da_tra", "con_no", "trang_thai", "nha_cung_cap"], as_dict=True)

	def _kham(self):
		from nppsale.kham_so import quet_cong_no_ncc

		self.assertEqual(quet_cong_no_ncc([self.ma["S1"], self.ma["S2"]]), [])

	def _chay_repost(self):
		from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost

		for n in frappe.get_all("Repost Item Valuation", filters={"status": "Queued"}, pluck="name", order_by="creation asc"):
			if n not in self.riv0:
				repost(frappe.get_doc("Repost Item Valuation", n))

	def _gv_hd(self, nhan) -> float:
		hd = self.st["nhan"]["hd:" + nhan]
		return -flt(frappe.db.sql("SELECT SUM(`stock_value_difference`) FROM `tabStock Ledger Entry` WHERE `voucher_no` = %s AND `is_cancelled` = 0",
			hd)[0][0])

	# ------------------------------------------------------------------------------------------------ cửa vào + thứ tự lỗi
	def test_cua_vao_va_thu_tu_loi(self):
		self._loi(self._rpc("KT", "sua_phieu_nhap", {"p_invoice_id": "PN-9999", "p_head": {}, "p_lines": [{}]}),
			"PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu nhập này.")
		g = {"org_id": "@org", "supplier_id": "@S1", "warehouse_zone": "sale", "discount": 0, "status": "draft"}
		self._ok(buoc="pn", nguoi="TK", nhan="P", dau=g, dong=self._dong([("A", "hộp", 10, 10000)]))
		tam = self._ten("P")
		self._loi(self._sua("P", [("A", "hộp", 10, 10000)]), "PHIEU_CHUA_HOAN_THANH: Chỉ sửa tại chỗ phiếu nhập đã hoàn thành (phiếu tạm lưu như thường).")
		self._ok(buoc="pn_hoan", nguoi="TK", nhan="P")
		# vai (không cửa gọi nội bộ — nppsale không có `npp.via_rpc` ở hàm này) TRƯỚC trạng thái / tham số
		self._loi(self._sua("P", [], nguoi="NV"), "FORBIDDEN: vai trò của bạn không được sửa phiếu nhập.", "42501")
		ts = lambda dau, dong: {"p_invoice_id": tam, "p_head": dau, "p_lines": dong}  # noqa: E731
		ncc_sai = {"supplier_id": "NCC-KHONG-CO", "warehouse_zone": "x", "discount": "abc"}
		self._loi(self._rpc("KT", "sua_phieu_nhap", ts(ncc_sai, [])), "PHIEU_TRONG: Phiếu nhập phải có ít nhất một dòng hàng.")
		self._loi(self._rpc("KT", "sua_phieu_nhap", ts(ncc_sai, None)), "PHIEU_TRONG: Phiếu nhập phải có ít nhất một dòng hàng.")
		dong = [{"product_id": self.ma["A"], "unit_name": "hộp", "quantity": 10, "unit_price": 10000}]
		self._loi(self._rpc("KT", "sua_phieu_nhap", ts(ncc_sai, dong)), "NCC_KHONG_HOP_LE: Nhà cung cấp không thuộc đơn vị.")
		self._loi(self._rpc("KT", "sua_phieu_nhap", ts({"warehouse_zone": "x", "discount": "abc"}, dong)), "KHO_KHONG_HOP_LE: Kho nhập không hợp lệ.")
		self._loi(self._rpc("KT", "sua_phieu_nhap", ts({"discount": "abc"}, [{"quantity": "x"}])), "BAD_PAYLOAD: dữ liệu phiếu sai kiểu.")
		self._loi(self._rpc("KT", "sua_phieu_nhap", ts({}, [{"product_id": "KHONG-CO"}, {"quantity": "x"}])), "BAD_PAYLOAD: dữ liệu phiếu sai kiểu.")
		self._loi(self._rpc("KT", "sua_phieu_nhap", ts({}, [{**dong[0]}, {"product_id": "KHONG-CO", "unit_name": "hộp", "quantity": 1}])),
			"HANG_KHONG_HOP_LE: Dòng 2 — mặt hàng không thuộc đơn vị.")
		# ngày HĐ ép kiểu SAU CÙNG (câu UPDATE cuối của hàm gốc): lỗi dòng ra trước; dòng đúng thì BAD_PAYLOAD
		self._loi(self._rpc("KT", "sua_phieu_nhap", ts({"invoice_date": "30/02/2026"}, [{**dong[0], "unit_price": -1}])),
			"GIA_KHONG_HOP_LE: Dòng 1 có giá / giảm giá âm.")
		self._loi(self._rpc("KT", "sua_phieu_nhap", ts({"invoice_date": "2026-02-30"}, dong)), "BAD_PAYLOAD: dữ liệu phiếu sai kiểu.")
		self._loi(self._rpc("KT", "sua_phieu_nhap", ts({}, [{**dong[0], "line_discount": 100001}])),
			"GIA_KHONG_HOP_LE: Dòng 1 có giảm giá lớn hơn tiền hàng.")
		# mọi lần hỏng không đổi gì: tờ vẫn ghi sổ, không tờ amend, lô nguyên
		self.assertEqual((frappe.db.get_value(DT, tam, "docstatus"), frappe.db.count(DT, {"amended_from": tam})), (1, 0))
		self.assertEqual(self._lo(f"{tam}-001"), {"sale": (10.0, 10000.0, 10.0, "available")})
		# phiếu đã huỷ → PHIEU_CHUA_HOAN_THANH
		self._ok(buoc="pn_huy", nguoi="KT", nhan="P", ly_do="x")
		self._loi(self._sua("P", [("A", "hộp", 10, 10000)]), "PHIEU_CHUA_HOAN_THANH: Chỉ sửa tại chỗ phiếu nhập đã hoàn thành (phiếu tạm lưu như thường).")

	def test_khoa_bin_truoc_pi(self):
		"""§2.1 / CFD-05: câu ĐẦU của thân hàm (sau bước chuẩn bị) là khoá Bin, câu kế khoá PI `FOR UPDATE` — Bin gồm mặt hàng CŨ ∪ mặt hàng GỬI LÊN."""
		ten = self._pn("P", [("A", "hộp", 10, 10000)])
		cau, moc = [], []
		goc_sql, goc_sp = frappe.db.sql, frappe.db.savepoint

		def ghi_sql(q, *a, **kw):
			cau.append((str(q), a))
			return goc_sql(q, *a, **kw)

		def ghi_sp(ten_sp, *a, **kw):
			kq = goc_sp(ten_sp, *a, **kw)
			if ten_sp == "npp_cong_rpc":
				moc.append(len(cau))
			return kq

		with patch.object(frappe.db, "sql", ghi_sql), patch.object(frappe.db, "savepoint", ghi_sp):
			ket = self._sua("P", [("A", "hộp", 12, 10000), ("B", "gói", 1, 5000)])
		self.assertNotIn("error", ket, ket)
		than = [(" ".join(q.split()), a) for q, a in cau[moc[0]:]]
		self.assertIn("`tabBin`", than[0][0])
		self.assertIn("FOR UPDATE", than[0][0])
		self.assertEqual(set(than[0][1][0]["h"]), {self.ma["A"], self.ma["B"]})  # mặt hàng cũ ∪ mặt hàng gửi lên
		self.assertTrue("`tabPurchase Invoice`" in than[1][0] and "FOR UPDATE" in than[1][0], than[1][0][:200])
		self.assertEqual(ket[1]["id"], "pn:P")
		self.assertTrue(frappe.db.get_value(DT, {"amended_from": ten}, "name"))

	# ------------------------------------------------------------------------------------------------ nhánh B — chỉ sửa giá
	def _v65(self):
		"""V65: P thùng 2 × 240.000 (lô 48 @10.000), bán 30 hộp, KT Ghi trả 100.000, sửa giá 264.000 + số HĐ + ghi chú."""
		ten = self._pn("P", [("A", "thùng", 2, 240000, 0, 0, 24)], invoice_number="HD-NCC-1", invoice_date="@hom_nay-46")
		self._ban("H1", "A", "hộp", 30)
		self._ok(buoc="ghi_tra", nguoi="KT", no="@no:pn:P", tien=100000, cach="transfer")
		# lõi chạy repost NGAY trong bài (`RepostItemValuation.on_submit` khi `frappe.in_test`) — giữ việc ở hàng đợi để kiểm trước / sau repost
		frappe.flags.dont_execute_stock_reposts = True
		self.addCleanup(setattr, frappe.flags, "dont_execute_stock_reposts", False)
		ket, tv = self._sua("P", [("A", "thùng", 2, 264000, 0, 0, 24)], dau={"supplier_id": "@S1", "invoice_number": "HD-NCC-9",
			"invoice_date": "@hom_nay-46", "warehouse_zone": "sale", "discount": 0, "vat_override": None, "notes": "sửa giá"})
		self.assertNotIn("error", ket, ket)
		return ten, tv

	def test_nhanh_b_sua_gia_v65(self):
		ten, tv = self._v65()
		self.assertEqual(tv, {"id": "pn:P", "total": 528000, "paid": 100000, "so_dong": 1, "doi_gia_lo": 1})
		self.assertEqual(frappe.db.count(DT, {"amended_from": ten}), 0)  # nhánh giá: id giữ, không amend
		pi = frappe.get_doc(DT, ten)
		self.assertEqual((pi.docstatus, flt(pi.items[0].price_list_rate), flt(pi.grand_total), pi.bill_no, pi.npp_ghi_chu),
			(1, 240000, 480000, "HD-NCC-9", "sửa giá"))  # tờ lõi giữ giá gốc
		lcv = frappe.get_all("Landed Cost Voucher", filters={"npp_phieu_nhap": ten, "docstatus": 1}, fields=["name", "npp_but_toan"])
		self.assertEqual(len(lcv), 1)
		x = frappe.get_doc("Landed Cost Voucher", lcv[0].name)
		self.assertTrue(x.name.startswith("SGN-"), x.name)
		self.assertEqual((x.distribute_charges_based_on, [(i.purchase_receipt_item, flt(i.applicable_charges)) for i in x.items],
			[(t.expense_account, flt(t.amount)) for t in x.taxes]), ("Distribute Manually", [(pi.items[0].name, 48000)],
			[(self.cd.tk_trung_gian_sua_gia_nhap, 48000)]))
		je = frappe.get_doc("Journal Entry", lcv[0].npp_but_toan)
		self.assertTrue(je.name.startswith("DCN-"), je.name)
		self.assertEqual((je.voucher_type, je.npp_loai, je.npp_phieu_nhap), ("Journal Entry", "dieu_chinh_gia_nhap", ten))
		self.assertEqual(sorted((a.account, flt(a.debit_in_account_currency), flt(a.credit_in_account_currency), a.party, a.reference_name)
			for a in je.accounts), sorted([(pi.credit_to, 0, 48000, self.ma["S1"], ten), (self.cd.tk_trung_gian_sua_gia_nhap, 48000, 0, None, None)]))
		sg = json.loads(frappe.db.get_value(DT, ten, "npp_sua_gia"))
		self.assertEqual((sg["dong"]["1"], sg["dau_phieu"]), ({"don_gia": 264000, "giam_dong": 0, "thue_suat": 0, "thanh_tien": 528000, "ghi_chu": None},
			{"giam": 0, "giam_ap": 0, "thue_go_tay": None, "tien_hang": 528000, "thue": 0, "tong": 528000}))
		self.assertEqual([(y["lcv"], y["but_toan"], y["nguoi"]) for y in sg["lan_sua"]], [([x.name], je.name, self.ma["u:KT"])])
		# cổng phủ số đã sửa
		r = self._cong({"bang": "purchase_invoices", "select": "subtotal, vat, total, discount, vat_override, notes, invoice_number, status, "
			"lines:purchase_invoice_lines(unit_price, line_total, line_discount, vat_rate, quantity)", "loc": [{"op": "eq", "cot": "id", "gt": ten}]})[0]
		self.assertEqual(r, {"subtotal": 528000, "vat": 0, "total": 528000, "discount": 0, "vat_override": None, "notes": "sửa giá",
			"invoice_number": "HD-NCC-9", "status": "completed", "lines": [{"unit_price": 264000, "line_total": 528000, "line_discount": 0,
			"vat_rate": 0, "quantity": 2}]})
		# lô 11.000 ngay sau LCV; công nợ 528.000 / đã trả 100.000; giá nhập theo giá đã sửa; khám sổ sạch
		self.assertEqual(self._lo(f"{ten}-001"), {"sale": (18.0, 11000.0, 48.0, "available")})
		self.assertEqual({k: flt(v) if k != "trang_thai" and k != "nha_cung_cap" else v for k, v in self._no(ten).items()},
			{"so_tien": 528000, "da_tra": 100000, "con_no": 428000, "trang_thai": "partial", "nha_cung_cap": self.ma["S1"]})
		self.assertEqual(frappe.db.get_value("NPP Cong No NCC", {"chung_tu": ten}, "so_hd_ncc"), "HD-NCC-9")  # số HĐ mới về dòng nợ
		self.assertEqual(flt(frappe.db.get_value("Item Price", {"item_code": self.ma["A"], "price_list": self.cd.bang_gia_nhap, "uom": pi.items[0].uom},
			"price_list_rate")), 264000)
		self.assertTrue(self.repost)
		self._kham()
		# repost (CFD-07): giá vốn 30 hộp đã bán tính lại 330.000
		self.assertEqual(self._gv_hd("H1"), 300000)
		self._chay_repost()
		self.assertEqual(self._gv_hd("H1"), 330000)
		# huỷ vẫn DA_TRA_TIEN
		self._loi(self._b(buoc="pn_huy", nguoi="KT", nhan="P", ly_do="x")[0], "DA_TRA_TIEN: Phiếu này đã trả NCC 100000 — huỷ phiếu là xoá mất khoản "
			"đã trả. Gỡ phiếu chi trước, hoặc lập phiếu trả hàng NCC.")

	def test_nhanh_b_chi_sua_gia(self):
		ten, _ = self._v65()
		hd = self.st["nhan"]["hd:H1"]
		cau = CHI_SUA_GIA.format(hd)
		dau = {"supplier_id": "@S1", "invoice_number": "HD-NCC-9", "invoice_date": "@hom_nay-46", "warehouse_zone": "sale", "discount": 0,
			"vat_override": None, "notes": "sửa giá"}
		dong = [("A", "thùng", 2, 264000, 0, 0, 24)]
		for _mo_ta, ket in (
				("đổi đơn vị", self._sua("P", [("A", "hộp", 48, 11000)], dau=dau)),
				("đổi SL", self._sua("P", [("A", "thùng", 3, 264000, 0, 0, 24)], dau=dau)),
				("đổi hệ số", self._sua("P", [("A", "thùng", 2, 264000, 0, 0, 20)], dau=dau)),
				("thêm dòng", self._sua("P", [*dong, ("B", "gói", 1, 5000)], dau=dau)),
				("đổi NCC", self._sua("P", dong, dau={**dau, "supplier_id": "@S2"})),
				("đổi kho", self._sua("P", dong, dau={**dau, "warehouse_zone": "date"}))):
			self._loi(ket[0], cau)
		# đổi mặt hàng = bỏ dòng A đã xuất: DA_XUAT_NHIEU_HON (bước 15–16, chung hai nhánh) ra trước
		self._loi(self._sua("P", [("M", "thùng", 2, 264000, 0, 0, 24)], dau=dau), "DA_XUAT_NHIEU_HON: Hàng của phiếu đã xuất nhiều hơn số lượng sửa — "
			"Hàng A: đã xuất 30 — không bỏ dòng này được. Giữ số lượng tối thiểu bằng số đã xuất, hoặc lập phiếu trả hàng NCC / điều chỉnh kho.")
		self._loi(self._sua("P", [("A", "thùng", 2, 264000, 0, 0, 24), ("M", "thùng", 2, 264000, 0, 0, 24)], dau=dau), cau)  # thêm mặt hàng khác
		# SL dưới số đã xuất: DA_XUAT_NHIEU_HON trước (bước 16 — chung hai nhánh)
		self._loi(self._sua("P", [("A", "thùng", 1, 264000, 0, 0, 24)], dau=dau)[0], "DA_XUAT_NHIEU_HON: Hàng của phiếu đã xuất nhiều hơn số lượng sửa — "
			f"Hàng A: đã xuất 30 {frappe.db.get_value('Item', self.ma['A'], 'stock_uom')}, số lượng mới chỉ 24. Giữ số lượng tối thiểu bằng số đã xuất, hoặc "
			"lập phiếu trả hàng NCC / điều chỉnh kho.")
		self.assertEqual(frappe.db.count("Landed Cost Voucher", {"npp_phieu_nhap": ten, "docstatus": 1}), 1)  # không lập thêm gì
		# ngày HĐ NCC đổi được ở nhánh giá (`bill_date` ghi thẳng — §7.2 #19), giá nhập lấy ngày mới
		ket, tv = self._sua("P", dong, dau={**dau, "invoice_date": "@hom_nay-40"})
		self.assertNotIn("error", ket, ket)
		self.assertEqual((tv["total"], tv["doi_gia_lo"], str(frappe.db.get_value(DT, ten, "bill_date"))), (528000, 0, str(add_days(XH.hom_nay(), -40))))
		self.assertEqual(frappe.db.count("Landed Cost Voucher", {"npp_phieu_nhap": ten, "docstatus": 1}), 1)  # giá không đổi → không LCV / DCN
		self.assertEqual(frappe.db.count("Journal Entry", {"npp_phieu_nhap": ten, "npp_loai": "dieu_chinh_gia_nhap", "docstatus": 1}), 1)
		self.assertEqual(str(frappe.db.get_value("Item Price", {"item_code": self.ma["A"], "price_list": self.cd.bang_gia_nhap}, "valid_from")),
			str(add_days(XH.hom_nay(), -40)))

	def test_nhanh_b_hai_chieu_thue_giam(self):
		ten = self._pn("P", [("A", "thùng", 2, 240000, 0, "0.1", 24), ("B", "gói", 10, 5000, 0, "0.1")], discount=10000)
		self.assertEqual(flt(frappe.db.get_value(DT, ten, "grand_total")), 573000)
		self._ban("H1", "A", "hộp", 30)
		dau = {"supplier_id": "@S1", "warehouse_zone": "sale", "discount": 15000, "vat_override": None}
		ket, tv = self._sua("P", [("A", "thùng", 2, 264000, 0, "0.1", 24), ("B", "gói", 10, 4000, 0, "0.1")], dau=dau)
		self.assertNotIn("error", ket, ket)
		self.assertEqual(tv, {"id": "pn:P", "total": 609800, "paid": 0, "so_dong": 2, "doi_gia_lo": 2})
		pi = frappe.get_doc(DT, ten)
		dong = {d.idx: d.name for d in pi.items}
		lcv = [frappe.get_doc("Landed Cost Voucher", x) for x in frappe.get_all("Landed Cost Voucher", filters={"npp_phieu_nhap": ten, "docstatus": 1},
			pluck="name", order_by="creation asc")]
		# MỖI LCV một chiều: tăng (A +48.000) rồi giảm (B −10.000)
		self.assertEqual([sorted((i.purchase_receipt_item, flt(i.applicable_charges)) for i in x.items if flt(i.applicable_charges)) for x in lcv],
			[[(dong[1], 48000)], [(dong[2], -10000)]])
		je = frappe.get_doc("Journal Entry", lcv[0].npp_but_toan)
		self.assertEqual(lcv[1].npp_but_toan, je.name)
		ve = {a.account: flt(a.debit_in_account_currency) - flt(a.credit_in_account_currency) for a in je.accounts}
		self.assertEqual(ve, {pi.credit_to: -36800, self.cd.tk_trung_gian_sua_gia_nhap: 38000, self.cd.tk_thue_dau_vao: 3800,
			self.cd.tk_giam_dau_phieu_nhap: -5000})
		self.assertEqual(je.voucher_type, "Journal Entry")
		r = self._cong({"bang": "purchase_invoices", "select": "subtotal, vat, total, discount, vat_override", "loc": [{"op": "eq", "cot": "id", "gt": ten}]})[0]
		self.assertEqual(r, {"subtotal": 568000, "vat": 56800, "total": 609800, "discount": 15000, "vat_override": None})
		self.assertEqual((self._lo(f"{ten}-001")["sale"][1], self._lo(f"{ten}-002")["sale"][1]), (11000.0, 4000.0))
		self.assertEqual(flt(self._no(ten).so_tien), 609800)
		self._kham()
		# sửa NGƯỢC về giá cũ: số cũ đọc từ phủ `npp_sua_gia` (không từ tờ lõi) — hai LCV đảo chiều, bút toán Debit Note đảo
		ket, tv = self._sua("P", [("A", "thùng", 2, 240000, 0, "0.1", 24), ("B", "gói", 10, 5000, 0, "0.1")], dau={**dau, "discount": 10000})
		self.assertEqual(tv, {"id": "pn:P", "total": 573000, "paid": 0, "so_dong": 2, "doi_gia_lo": 2})
		je2 = frappe.get_all("Journal Entry", filters={"npp_phieu_nhap": ten, "npp_loai": "dieu_chinh_gia_nhap", "docstatus": 1}, pluck="name",
			order_by="creation desc")[0]
		je2 = frappe.get_doc("Journal Entry", je2)
		self.assertEqual((je2.voucher_type, {a.account: flt(a.debit_in_account_currency) - flt(a.credit_in_account_currency) for a in je2.accounts}),
			("Debit Note", {pi.credit_to: 36800, self.cd.tk_trung_gian_sua_gia_nhap: -38000, self.cd.tk_thue_dau_vao: -3800,
			self.cd.tk_giam_dau_phieu_nhap: 5000}))
		self.assertEqual((self._lo(f"{ten}-001")["sale"][1], self._lo(f"{ten}-002")["sale"][1]), (10000.0, 5000.0))
		self.assertEqual(frappe.db.count("Landed Cost Voucher", {"npp_phieu_nhap": ten, "docstatus": 1}), 4)
		# thuế gõ tay 60.000: chỉ chênh thuế — không LCV, bút toán thuế ↔ NCC
		ket, tv = self._sua("P", [("A", "thùng", 2, 240000, 0, "0.1", 24), ("B", "gói", 10, 5000, 0, "0.1")],
			dau={**dau, "discount": 10000, "vat_override": 60000})
		self.assertEqual(tv, {"id": "pn:P", "total": 580000, "paid": 0, "so_dong": 2, "doi_gia_lo": 0})
		self.assertEqual(frappe.db.count("Landed Cost Voucher", {"npp_phieu_nhap": ten, "docstatus": 1}), 4)
		r = self._cong({"bang": "purchase_invoices", "select": "vat, total, vat_override", "loc": [{"op": "eq", "cot": "id", "gt": ten}]})[0]
		self.assertEqual(r, {"vat": 60000, "total": 580000, "vat_override": 60000})
		self.assertEqual(flt(self._no(ten).so_tien), 580000)
		self._kham()

	def test_huy_khoi_phuc_va_sua_lai_sau_sua_gia(self):
		"""Sửa giá (LCV + DCN) → huỷ HĐ (lô về đủ) → huỷ phiếu nhập: huỷ DCN rồi LCV trước; khôi phục → tờ amend mang THẲNG giá đã sửa (nppsale khôi
		phục số đã sửa), bỏ phủ; sửa tiếp (nhánh A) trên tờ khôi phục."""
		ten = self._pn("P", [("A", "thùng", 2, 240000, 0, 0, 24)])
		self._ban("H1", "A", "hộp", 30)
		self.assertNotIn("error", self._sua("P", [("A", "thùng", 2, 264000, 0, 0, 24)])[0])
		lcv = frappe.get_all("Landed Cost Voucher", filters={"npp_phieu_nhap": ten}, pluck="name")
		je = frappe.get_all("Journal Entry", filters={"npp_phieu_nhap": ten, "npp_loai": "dieu_chinh_gia_nhap"}, pluck="name")
		self._ok(buoc="huy_hd", nguoi="CHU", nhan="H1", ly_do="x")
		self._ok(buoc="pn_huy", nguoi="KT", nhan="P", ly_do="x")
		self.assertEqual([frappe.db.get_value("Landed Cost Voucher", x, "docstatus") for x in lcv] + [frappe.db.get_value("Journal Entry", x,
			"docstatus") for x in je] + [frappe.db.get_value(DT, ten, "docstatus")], [2, 2, 2])
		self.assertIsNone(self._no(ten))
		tv = self._ok(buoc="pn_khoi_phuc", nguoi="KT", nhan="P")
		moi = self._ten("P")
		self.assertEqual((tv["trang_thai"], tv["da_khoi_phuc"], moi), ("completed", True, f"{ten}-1"))
		pi = frappe.get_doc(DT, moi)
		self.assertEqual((flt(pi.items[0].price_list_rate), flt(pi.grand_total), pi.npp_sua_gia), (264000, 528000, None))
		self.assertEqual(self._lo(f"{ten}-001"), {"sale": (48.0, 11000.0, 48.0, "available")})
		self.assertEqual(flt(self._no(moi).so_tien), 528000)
		r = self._cong({"bang": "purchase_invoices", "select": "total, lines:purchase_invoice_lines(unit_price)", "loc": [{"op": "eq", "cot": "id",
			"gt": moi}]})[0]
		self.assertEqual(r, {"total": 528000, "lines": [{"unit_price": 264000}]})
		# sửa tiếp (chưa xuất → nhánh A): gọi bằng id CŨ → làm trên tờ cuối chuỗi
		ket = self._rpc("KT", "sua_phieu_nhap", {"p_invoice_id": ten, "p_head": {"warehouse_zone": "sale"}, "p_lines": [{"product_id": self.ma["A"],
			"unit_name": "thùng", "quantity": 3, "unit_price": 250000, "conversion_factor": 24}]})
		self.assertEqual(ket.get("data"), {"id": f"{ten}-2", "total": 750000, "paid": 0, "so_dong": 1, "doi_gia_lo": 1})
		self.assertEqual(self._lo(f"{ten}-001"), {"sale": (72.0, round(750000 / 72, 2), 72.0, "available")})
		self._kham()

	def test_nhanh_a_sau_sua_gia_huy_lcv(self):
		"""Phiếu đã sửa giá rồi hàng về đủ (huỷ HĐ) → sửa SL = nhánh A: thân huỷ nội bộ huỷ DCN + LCV, tờ amend mang số mới, không còn phủ."""
		ten = self._pn("P", [("A", "thùng", 2, 240000, 0, 0, 24)])
		self._ban("H1", "A", "hộp", 30)
		self._sua("P", [("A", "thùng", 2, 264000, 0, 0, 24)])
		self._ok(buoc="huy_hd", nguoi="CHU", nhan="H1", ly_do="x")
		ket, tv = self._sua("P", [("A", "thùng", 1, 300000, 0, 0, 24)])
		self.assertNotIn("error", ket, ket)
		self.assertEqual(tv, {"id": "pn:P", "total": 300000, "paid": 0, "so_dong": 1, "doi_gia_lo": 1})
		moi = self._ten("P")
		self.assertEqual((moi, frappe.db.get_value(DT, moi, "npp_sua_gia")), (f"{ten}-1", None))
		self.assertEqual(frappe.db.count("Landed Cost Voucher", {"npp_phieu_nhap": ten, "docstatus": 1}), 0)
		self.assertEqual(frappe.db.count("Journal Entry", {"npp_phieu_nhap": ten, "npp_loai": "dieu_chinh_gia_nhap", "docstatus": 1}), 0)
		self.assertEqual(self._lo(f"{ten}-001"), {"sale": (24.0, 12500.0, 24.0, "available")})
		self._kham()

	# ------------------------------------------------------------------------------------------------ nhánh A — huỷ + amend
	def test_nhanh_a_lo_va_kho(self):
		ten = self._pn("P", [("A", "thùng", 2, 240000, 0, 0, 24)])
		_ket, tv = self._sua("P", [("A", "hộp", 30, 11000), ("B", "gói", 10, 5000)])
		self.assertEqual(tv, {"id": "pn:P", "total": 380000, "paid": 0, "so_dong": 2, "doi_gia_lo": 1})
		p1 = self._ten("P")
		self.assertEqual((p1, frappe.db.get_value(DT, ten, "docstatus"), frappe.db.get_value(DT, ten, "npp_ly_do_huy")),
			(f"{ten}-1", 2, "Sửa phiếu nhập đã hoàn thành — lập lại"))
		pi = frappe.get_doc(DT, p1)
		self.assertEqual((pi.npp_hoan_thanh_luc, str(pi.posting_date), str(pi.posting_time)), (frappe.db.get_value(DT, ten, "npp_hoan_thanh_luc"),
			str(frappe.db.get_value(DT, ten, "posting_date")), str(frappe.db.get_value(DT, ten, "posting_time"))))  # giữ mốc của tờ gốc
		self.assertEqual(self._lo(f"{ten}-001"), {"sale": (30.0, 11000.0, 30.0, "available")})  # ĐÚNG Batch cũ
		self.assertEqual(self._lo(f"{ten}-002"), {"sale": (10.0, 5000.0, 10.0, "available")})
		self.assertEqual(frappe.db.get_value("Batch", f"{ten}-002", "reference_name"), p1)
		# bỏ dòng B → lô -002 tắt (cổng `cancelled`); thêm lại B → lô MỚI -003 (hậu tố theo MỌI Batch — nppsale cấp lại -002, KB21)
		self._sua("P", [("A", "hộp", 30, 11000)])
		self.assertEqual(self._lo(f"{ten}-002"), {"sale": (0.0, 5000.0, 0.0, "cancelled")})
		_ket, tv = self._sua("P", [("A", "hộp", 30, 11000), ("B", "gói", 4, 5000)])
		self.assertEqual((tv["id"], tv["total"], tv["doi_gia_lo"]), ("pn:P", 350000, 0))
		self.assertEqual(self._lo(f"{ten}-003"), {"sale": (4.0, 5000.0, 4.0, "available")})
		self.assertEqual(self._ten("P"), f"{ten}-3")
		# đổi kho đầu phiếu sang kho cận date: hàng nhập vào kho date; về kho bán: A vào bán, C hạn 20 (trong ngưỡng) vẫn vào date (V70 ⚠K)
		q = self._pn("Q", [("A", "thùng", 1, 240000, 0, 0, 24), ("C", "chai", 10, 15000)])
		self.assertEqual(self._lo(f"{q}-002"), {"date": (10.0, 15000.0, 10.0, "available")})
		self._sua("Q", [("A", "thùng", 1, 240000, 0, 0, 24), ("C", "chai", 10, 15000)], dau={"warehouse_zone": "date"})
		self.assertEqual((self._lo(f"{q}-001"), self._lo(f"{q}-002")), ({"date": (24.0, 10000.0, 24.0, "available")},
			{"date": (10.0, 15000.0, 10.0, "available")}))
		self._sua("Q", [("A", "thùng", 1, 240000, 0, 0, 24), ("C", "chai", 10, 15000)], dau={"warehouse_zone": "sale"})
		self.assertEqual((self._lo(f"{q}-001"), self._lo(f"{q}-002")), ({"sale": (24.0, 10000.0, 24.0, "available")},
			{"date": (10.0, 15000.0, 10.0, "available")}))
		self._kham()

	def test_nhanh_a_tien_di_theo(self):
		"""V71: Ghi trả 1.000.000 + phiếu chi 200.000 trên P2 (1.200.000) → sửa còn 800.000: tiền đi theo tờ mới — phần vừa = tham chiếu giữ tên phiếu,
		phần dư = bút toán `chuyen_tra_du_ncc` vào CHÍNH tờ mới (đã trả 1.200.000, nợ 800.000 → open); dòng tiền cổng mang danh tính phiếu tiền gốc;
		huỷ phiếu nhập → DA_TRA_TIEN (Ghi trả, kể cả phần dư); huỷ phiếu chi → bút toán dư của nó huỷ trước."""
		self._pn("P2", [("A", "thùng", 5, 240000, 0, 0, 24)])
		self._ok(buoc="ghi_tra", nguoi="KT", no="@no:pn:P2", tien=1000000, cach="transfer")
		self._ok(buoc="chi", nguoi="KT", nhan="C1", ncc="@S1", tien=200000, cach="cash")
		gtn = frappe.get_all("Payment Entry", filters={"npp_loai": "ghi_tra_ncc", "party": self.ma["S1"], "docstatus": 1}, pluck="name")[0]
		pc = self.st["nhan"]["pc:C1"]
		p0 = self._pn("P0", [("B", "gói", 10, 5000)])  # khoản khác còn mở: thân huỷ nội bộ KHÔNG được dồn tiền phiếu chi vừa gỡ sang đây
		_ket, tv = self._sua("P2", [("A", "thùng", 5, 160000, 0, 0, 24)])
		self.assertEqual(flt(self._no(p0).da_tra), 0)
		self.assertEqual(tv, {"id": "pn:P2", "total": 800000, "paid": 1200000, "so_dong": 1, "doi_gia_lo": 1})
		moi = self._ten("P2")
		self.assertEqual({k: flt(v) if k not in ("trang_thai", "nha_cung_cap") else v for k, v in self._no(moi).items()},
			{"so_tien": 800000, "da_tra": 1200000, "con_no": -400000, "trang_thai": "open", "nha_cung_cap": self.ma["S1"]})
		ref = dict(frappe.db.sql("""SELECT r.`parent`, SUM(r.`allocated_amount`) FROM `tabPayment Entry Reference` r WHERE r.`reference_name` = %s
			GROUP BY r.`parent`""", moi))
		self.assertEqual({k: flt(v) for k, v in ref.items()}, {gtn: 800000})  # phiếu tiền giữ tên
		du = frappe.get_all("Journal Entry", filters={"npp_loai": "chuyen_tra_du_ncc", "docstatus": 1}, pluck="name")
		self.assertEqual(sorted((p, x) for p, x in (self._du(j) for j in du)), sorted([(gtn, 200000.0), (pc, 200000.0)]))
		dong = self._cong({"bang": "payable_payments", "select": "amount, method, supplier_payment_id, notes, paid_at", "loc": [{"op": "eq",
			"cot": "payable_id", "gt": frappe.db.get_value("NPP Cong No NCC", {"chung_tu": moi}, "name")}]})
		gop = {}
		for d in dong:
			k = (d["method"], d["supplier_payment_id"], d["notes"], d["paid_at"])
			gop[k] = gop.get(k, 0) + flt(d["amount"])
		self.assertEqual(sorted((k[0], k[1], v) for k, v in gop.items()), sorted([("transfer", None, 1000000.0), ("cash", pc, 200000.0)]))
		self.assertEqual(flt(self._cong({"bang": "supplier_payments", "select": "dong:payable_payments(amount)", "loc": [{"op": "eq", "cot": "id",
			"gt": pc}]})[0]["dong"][0]["amount"]), 200000)
		self._kham()
		self._loi(self._b(buoc="pn_huy", nguoi="KT", nhan="P2", ly_do="x")[0], "DA_TRA_TIEN: Phiếu này đã trả NCC 1000000 — huỷ phiếu là xoá mất "
			"khoản đã trả. Gỡ phiếu chi trước, hoặc lập phiếu trả hàng NCC.")
		self._ok(buoc="huy_chi", nguoi="KT", nhan="C1", ly_do="x")
		self.assertEqual([frappe.db.get_value("Journal Entry", j, "docstatus") for j in du if self._du(j)[0] == pc], [2])
		self.assertEqual(flt(self._no(moi).da_tra), 1000000)
		self._kham()
		# sửa LẦN NỮA lên 1.100.000: phần dư cũ gộp lại vào phiếu tiền, phân bổ lại hết
		_ket, tv = self._sua("P2", [("A", "thùng", 5, 220000, 0, 0, 24)])
		self.assertEqual((tv["total"], tv["paid"]), (1100000, 1000000))
		moi2 = self._ten("P2")
		self.assertEqual(flt(frappe.db.sql("SELECT SUM(`allocated_amount`) FROM `tabPayment Entry Reference` WHERE `reference_name` = %s", moi2)[0][0]),
			1000000)
		self.assertEqual(frappe.db.count("Journal Entry", {"npp_loai": "chuyen_tra_du_ncc", "docstatus": 1}), 0)
		self.assertEqual((flt(self._no(moi2).da_tra), self._no(moi2).trang_thai), (1000000, "partial"))
		self._kham()

	def _du(self, je) -> tuple[str, float]:
		from nppsale.su_kien.cong_no_ncc import tien_chuyen_tra_du

		return tien_chuyen_tra_du(je)

	def test_nhanh_a_phieu_chi_du_ve_tra_truoc_khi_huy(self):
		"""Phiếu chi 100.000 trả đủ P3 → sửa P3 còn 60.000: 40.000 chuyển dư vào P3-1; P4 lập sau không nhận dồn (phiếu chi không còn tiền theo sổ);
		huỷ P3-1 → bút toán dư huỷ trước, toàn bộ tiền phiếu chi về trả trước rồi dồn vào P4 (mig 242 `_tra_phan_bo_ve_truoc`)."""
		self._pn("P3", [("A", "hộp", 10, 10000)])
		self._ok(buoc="chi", nguoi="KT", nhan="C1", ncc="@S1", tien=100000, cach="cash")
		# sửa TĂNG (TK): phiếu chi về trọn tờ mới, không phần dư — dòng trả trước tạm (hook huỷ chiếu ra) phải mất
		_ket, tv = self._sua("P3", [("A", "hộp", 12, 10000)], nguoi="TK")
		self.assertEqual((tv["total"], tv["paid"]), (120000, 100000))
		self.assertFalse(frappe.db.exists("NPP Cong No NCC", {"phieu_chi": self.st["nhan"]["pc:C1"], "loai": "tra_truoc"}))
		self._kham()
		_ket, tv = self._sua("P3", [("A", "hộp", 6, 10000)], nguoi="TK")
		self.assertEqual((tv["total"], tv["paid"]), (60000, 100000))
		p4 = self._pn("P4", [("B", "gói", 10, 5000)])
		self.assertEqual(flt(self._no(p4).da_tra), 0)
		self._kham()
		self._ok(buoc="pn_huy", nguoi="KT", nhan="P3", ly_do="x")
		self.assertEqual(frappe.db.count("Journal Entry", {"npp_loai": "chuyen_tra_du_ncc", "docstatus": 1}), 0)
		self.assertEqual((flt(self._no(p4).da_tra), self._no(p4).trang_thai), (50000, "paid"))
		pc = self.st["nhan"]["pc:C1"]
		self.assertEqual(flt(frappe.db.get_value("NPP Cong No NCC", {"phieu_chi": pc, "loai": "tra_truoc"}, "da_tra")), 50000)
		self._kham()
		# sửa P4 TĂNG (nhánh A): tờ amend là PI dương ghi sổ → dồn trả trước còn lại vào (đặc tả §2.8)
		_ket, tv = self._sua("P4", [("B", "gói", 20, 5000)])
		self.assertEqual((tv["total"], tv["paid"]), (100000, 100000))
		self.assertFalse(frappe.db.exists("NPP Cong No NCC", {"phieu_chi": pc, "loai": "tra_truoc"}))
		self._kham()

	def test_nhanh_a_bu_tru_lap_lai(self):
		"""Bù trừ `CTN-` (vế Nợ trỏ P) huỷ trước khi huỷ P rồi lập lại trỏ tờ mới — giữ số từng vế."""
		self._pn("P0", [("B", "gói", 10, 5000)])
		self._ok(buoc="ptn", nguoi="TK", nhan="R", dau={"org_id": "@org", "supplier_id": "@S1", "warehouse_zone": "sale", "reason": "damaged",
			"discount": 0, "status": "draft"}, dong=[{"product_id": "@B", "unit_name": "gói", "quantity": 3, "unit_price": 5000, "line_discount": 0,
			"vat_rate": 0, "conversion_factor": 1, "sort_order": 1}])
		self._ok(buoc="ptn_gui", nguoi="TK", nhan="R")
		p = self._pn("P", [("A", "hộp", 10, 10000)])
		self._ok(buoc="ghi_tra", nguoi="KT", no="@no:pn:P", tien=15000, cach="offset")
		ctn = frappe.get_all("Journal Entry", filters={"npp_loai": "bu_tru_ncc", "docstatus": 1}, pluck="name")
		_ket, tv = self._sua("P", [("A", "hộp", 12, 10000)])
		self.assertEqual((tv["total"], tv["paid"]), (120000, 15000))
		moi = self._ten("P")
		self.assertEqual(frappe.db.get_value("Journal Entry", ctn[0], "docstatus"), 2)
		lai = frappe.get_all("Journal Entry", filters={"npp_loai": "bu_tru_ncc", "docstatus": 1, "amended_from": ctn[0]}, pluck="name")
		self.assertEqual(len(lai), 1)
		x = frappe.get_doc("Journal Entry", lai[0])
		self.assertEqual(sorted((a.reference_name, flt(a.debit_in_account_currency), flt(a.credit_in_account_currency)) for a in x.accounts),
			sorted([(moi, 15000, 0), (self._b_ten("ptn:R"), 0, 15000)]))
		self.assertEqual(x.npp_phieu_nhap, moi)  # khoản được trả của bút toán bù trừ = tờ còn hiệu lực
		self.assertNotEqual(moi, p)
		self.assertEqual(flt(self._no(moi).da_tra), 15000)
		self._kham()

	def _b_ten(self, k):
		return self.h._ten(self.st, k)

	def test_doi_ncc(self):
		self._pn("P", [("A", "hộp", 10, 10000)])
		self._ok(buoc="ghi_tra", nguoi="KT", no="@no:pn:P", tien=1000, cach="cash")
		self._loi(self._sua("P", [("A", "hộp", 10, 10000)], dau={"supplier_id": "@S2"})[0],
			"NCC_DA_TRA_TIEN: Phiếu đã trả NCC 1000 — không đổi nhà cung cấp được. Gỡ phiếu chi / Ghi trả trước.")
		q = self._pn("Q", [("A", "hộp", 5, 10000)])
		ket, _tv = self._sua("Q", [("A", "hộp", 5, 10000)], dau={"supplier_id": "@S2"})
		self.assertNotIn("error", ket, ket)
		moi = self._ten("Q")
		self.assertEqual((frappe.db.get_value(DT, moi, "supplier"), self._no(moi).nha_cung_cap, self._no(q)), (self.ma["S2"], self.ma["S2"], None))
		self._kham()

	def test_lo_ra_soat_khong_tinh_da_xuat(self):
		"""Lô bị RÀ SOÁT sang kho cận date (phiếu `CKL-` tự động — nppsale lật cờ vùng, không xuất) vẫn là "chưa xuất": sửa SL đi nhánh A (huỷ trước phiếu
		rà soát — §7.3 điểm 8)."""
		ten = self._pn("P", [("D", "lon", 10, 5000)])
		self.assertEqual(self._lo(f"{ten}-001"), {"sale": (10.0, 5000.0, 10.0, "available")})
		self._ok(buoc="nguong", ngay=200)
		truoc = set(frappe.get_all("Stock Entry", filters={"npp_loai": "chuyen_date_tu_dong", "docstatus": 1}, pluck="name"))
		self._b(buoc="ra_soat", nguoi="CHU")
		self.assertEqual(self._lo(f"{ten}-001")["date"][0], 10.0)
		ckl = set(frappe.get_all("Stock Entry", filters={"npp_loai": "chuyen_date_tu_dong", "docstatus": 1}, pluck="name")) - truoc
		self.assertTrue(ckl)
		ket, tv = self._sua("P", [("D", "lon", 12, 5000)])
		self.assertNotIn("error", ket, ket)
		self.assertEqual((tv["id"], tv["total"]), ("pn:P", 60000))
		self.assertEqual(self._ten("P"), f"{ten}-1")
		self.assertEqual({frappe.db.get_value("Stock Entry", x, "docstatus") for x in ckl}, {2})  # phiếu rà soát huỷ trước (hàng về kho nhận)
		self.assertEqual(self._lo(f"{ten}-001")["date"][0], 12.0)  # hạn +180 trong ngưỡng 200 → nhập thẳng kho date

	def test_hang_khong_lo_thieu_ton_lui_ve_sua_gia(self):
		"""Hàng KHÔNG lô X đã bán bớt, NPP không cho bán vượt tồn: thân huỷ của nhánh A không đảo được (Bin thiếu) → lùi về điểm lưu, chỉ sửa giá (nhánh
		B); đổi SL → PHIEU_DA_XUAT_CHI_SUA_GIA."""
		frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 0)
		frappe.local._npp_cai_dat_ban = None
		ten = self._pn("P", [("X", "cai", 10, 1000)])
		self._ban("H1", "X", "cai", 4)
		ket, tv = self._sua("P", [("X", "cai", 10, 1200)])
		self.assertNotIn("error", ket, ket)
		self.assertEqual(tv, {"id": "pn:P", "total": 12000, "paid": 0, "so_dong": 1, "doi_gia_lo": 0})
		self.assertEqual((self._ten("P"), frappe.db.get_value(DT, ten, "docstatus")), (ten, 1))
		self.assertEqual(frappe.db.count("Landed Cost Voucher", {"npp_phieu_nhap": ten, "docstatus": 1}), 1)
		self._loi(self._sua("P", [("X", "cai", 8, 1200)])[0], CHI_SUA_GIA.format("chứng từ khác"))
		self._kham()
