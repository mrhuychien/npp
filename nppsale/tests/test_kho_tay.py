"""Phiếu kho tay (P4 — M4) ngoài kịch bản vàng (đặc tả kho_mua §3.6, §3.15, §3.16, §3.19, §4.5, §4.7, §4.8, §10) — cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_kho_tay

Dựng trên bộ dữ liệu F của tệp vàng (test_kho_mua_vang.dung_nen_kho) và DÙNG LẠI các bước của bài vàng (`_buoc`: pn / pn_hoan / ptn / ptn_gui /
ban / huy_hd / tra_khach / nhap_kho / pk / xuat_le / chuyen / huy_pk / lo / co_am) — lớp bài kế thừa lớp bài vàng nhưng bỏ bài so vàng.
Phần kiểm: nhập kho tay (nhánh Stock Entry + nhánh phiếu nhập, tồn đầu kỳ, lùi / tiến ngày, mã lô trùng, ép kiểu trước vai, tài khoản), xuất lẻ
(khoá Bin là câu đầu, hạn cũ trước gồm lô hết hạn, vượt tồn chỉ hàng không lô + hai cờ, mặt hàng thiếu báo theo mã), chuyển kho (giữ giá lô, dấu chuyển
vùng, ranh ngưỡng cận date, không vượt tồn), huỷ phiếu kho (vai trước trạng thái, nguồn theo trường thật — việc #24, nợ NCC lập tay, rút nhập hàng
không lô, số lô / số dòng hoàn, xoá nháp giữ số đếm), cổng đọc gộp nguồn (PN / trả NCC / HĐ / tờ ghi có / NL-, ghi chú §10.1, giá dòng một luật với hằng
P6), v_stock_movements, v_stock_balance_by_zone, che giá vốn, bảng không port, ghi thẳng nháp (ràng buộc, RLS, dòng lệch hệ số, chứng từ gốc).
"""
from __future__ import annotations

import re
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, get_datetime, getdate, now_datetime, nowdate

from nppsale.cong.bang.kho import NGUON_DONG_XUAT, nguon_dong_nhap_lai
from nppsale.luat.tim import khoa_tim_ds
from nppsale.tests import test_kho_mua_vang as V
from nppsale.tests import test_xuat_hang as XH

RLS_PK = 'new row violates row-level security policy for table "stock_entries"'
RLS_DONG = 'new row violates row-level security policy for table "stock_entry_lines"'
FORBIDDEN_KHO = "FORBIDDEN: vai trò của bạn không được làm thao tác kho / mua hàng này."
FORBIDDEN_NHAP = "FORBIDDEN: chỉ chủ NPP hoặc thủ kho được lập phiếu nhập kho."


class TestKhoTay(V.TestKhoMuaVang):
	test_kich_ban_vang = None  # bài so vàng chạy ở test_kho_mua_vang

	def setUp(self):
		super().setUp()
		self.st = {"ma": "kt", "nhan": {}}

	# ------------------------------------------------------------------------------------------------ gọi
	def _ok(self, **b):
		ket, tv = self._buoc(b, self.st)
		self.assertNotIn("error", ket, f"{b['buoc']} {b.get('nhan')}: {ket.get('error')}")
		return tv

	def _loi(self, ma_loi: str, cau: str, **b):
		ket, _ = self._buoc(b, self.st)
		self.assertIn("error", ket, f"{b['buoc']} {b.get('nhan')}: mong lỗi {cau}")
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), (ma_loi, cau))

	def _nh(self, nhan: str) -> str:
		return self.st["nhan"][nhan]

	def _nhap(self, nguoi="TK", nhan="IN1", **p):
		return self._buoc({"buoc": "nhap_kho", "nguoi": nguoi, "nhan": nhan, "p": {"entry_code": "IN-T-1", "warehouse_zone": "sale",
			"lines": [{"product_id": "@A", "unit_name": "hộp", "qty_tx": 10, "conv": 1, "base_qty": 10, "base_cost": 10000}], **p}}, self.st)[0]

	def _pk(self, nhan: str, loai: str, vung: str, dong: list, nguoi="TK", **dau):
		"""Nháp phiếu kho qua cổng (như màn /inventory/stock-issue): dòng (mặt hàng, ĐV, SL giao dịch, hệ số)."""
		d = [{"product_id": sp, "batch_id": None, "unit_name": dv, "quantity": sl * hs, "qty_in_base_uom": sl * hs, "qty_in_transaction_uom": sl,
			"transaction_uom": dv, "conversion_factor_snapshot": hs, "unit_cost": 0, "notes": None} for sp, dv, sl, hs in dong]
		self._ok(buoc="pk", nguoi=nguoi, nhan=nhan, dau={"org_id": "@org", "entry_code": nhan, "type": loai, "warehouse_zone": vung,
			"dest_warehouse_zone": dau.pop("dich", None), "issue_reason": None, "notes": None, "status": "draft", "created_by": "@u:" + nguoi, **dau},
			dong=d)
		return self._nh("pk:" + nhan)

	def _lo_p(self, ma: str, ton: float, gia: float, han: int | None, vung="sale", sp="@P", nhan_ngay=-30):
		return self._lo({"ma": ma, "sp": sp, "vung": vung, "ton": ton, "gia": gia, "han": han, "nhan_ngay": nhan_ngay})

	def _rpc_tk(self, ten: str, **ts):
		return self._goi("TK", ten, ts)

	def _cong_doc(self, nguoi: str, bang: str, select="*", **loc):
		ket = self._cong(nguoi, {"bang": bang, "select": select, "loc": [{"op": "eq", "cot": c, "gt": v} for c, v in loc.items()]})
		self.assertNotIn("error", ket, ket)
		return ket["data"]

	def _ton_lo(self, lo: str, kho: str) -> float:
		return flt(frappe.db.sql("""SELECT COALESCE(SUM(e.`qty`), 0) FROM `tabSerial and Batch Entry` e JOIN `tabSerial and Batch Bundle` b
			ON b.`name` = e.`parent` AND b.`docstatus` = 1 AND b.`is_cancelled` = 0 WHERE e.`is_cancelled` = 0 AND e.`batch_no` = %s
			AND e.`warehouse` = %s""", (lo, kho))[0][0])

	def _cau_dau(self, nguoi: str, ten: str, ts: dict) -> tuple[dict, str]:
		"""(kết quả, câu SQL ĐẦU của thân hàm — ngay sau điểm lưu `npp_cong_rpc`, PoC 1d)."""
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
			ket = self._goi(nguoi, ten, ts)
		return ket, (cau[moc[0]] if moc and len(cau) > moc[0] else "")

	# ------------------------------------------------------------------------------------------------ nhập kho tay
	def test_nhap_kho_nhanh_stock_entry(self):
		"""Không NCC → Material Receipt `IN-<ngày>-NNNN` (`nhap_kho`): giá mỗi ĐV CƠ SỞ (`basic_rate` của lõi theo đơn vị kho), dòng giữ đơn vị giao
		dịch khi SL × hệ số khớp, TK `tk_nhap_kho_khong_hd`, lô `LOT-<mã>-<n>` (không đệm), hạn trong ngưỡng → kho date dù chọn kho bán, ngày nhận =
		`posted_at`, ngày SX trống, giá vốn lô rỗng ghi sẵn."""
		ket = self._nhap(p_lines=None, lines=[
			{"product_id": "@A", "unit_name": "thùng", "qty_tx": 2, "conv": 24, "base_qty": 48, "base_cost": 10000, "expires_at": "@hom_nay+20",
				"location": " Ke 2 "},
			{"product_id": "@A", "unit_name": "thùng", "qty_tx": 3, "conv": 24, "base_qty": 48, "base_cost": 0, "batch_code": " G-9 "}])
		self.assertNotIn("error", ket, ket)
		r = ket["data"][0]
		ten = r["entry_id"]
		self.assertEqual(r, {"entry_id": ten, "entry_code": ten, "payable_id": None, "lines_written": 2})
		self.assertTrue(ten.startswith("IN-" + getdate(nowdate()).strftime("%Y%m%d") + "-"), ten)
		se = frappe.get_doc("Stock Entry", ten)
		self.assertEqual((se.docstatus, se.purpose, se.npp_loai, se.is_opening, se.npp_kho_nhap), (1, "Material Receipt", "nhap_kho", "No",
			self.cd.kho_ban))
		d1, d2 = sorted(se.items, key=lambda d: d.idx)
		self.assertEqual((V._dv(d1.uom), flt(d1.qty), flt(d1.conversion_factor), flt(d1.transfer_qty), flt(d1.valuation_rate), d1.t_warehouse,
			d1.expense_account), ("thung", 2, 24, 48, 10000, self.cd.kho_can_date, self.cd.tk_nhap_kho_khong_hd))
		# dòng 2: 3 × 24 ≠ 48 → đơn vị kho, hệ số 1; giá 0 được nhận (allow_zero_valuation_rate)
		self.assertEqual((flt(d2.qty), flt(d2.conversion_factor), d2.uom, flt(d2.valuation_rate), d2.allow_zero_valuation_rate, d2.t_warehouse),
			(48, 1, frappe.db.get_value("Item", self.ma["A"], "stock_uom"), 0, 1, self.cd.kho_ban))
		lo = frappe.get_doc("Batch", f"LOT-{'IN-T-1'}-1")
		self.assertEqual((str(lo.expiry_date), lo.manufacturing_date, lo.npp_vi_tri, lo.npp_kho_tao, flt(lo.npp_gia_von_lo_rong), lo.reference_name),
			(str(add_days(XH.hom_nay(), 20)), None, "Ke 2", self.cd.kho_can_date, 10000, ten))
		self.assertLess(abs((get_datetime(lo.npp_ngay_nhap) - now_datetime()).total_seconds()), 300)
		self.assertTrue(frappe.db.exists("Batch", "G-9"))  # mã gõ được trim
		self.assertEqual(self._ton_lo(lo.name, self.cd.kho_can_date), 48)
		self.assertEqual(self.repost, [])  # ghi hôm nay — không repost

	def test_nhap_kho_dau_ky_lui_ngay(self):
		"""Mã `DK-…` → `ton_dau_ky` + `is_opening` + TK tạm đầu kỳ (§7.3 điểm 4); `posted_at` lùi 5 ngày → ghi lùi ngày + ngày nhận lô lùi + xếp
		repost; ngày tương lai → NGAY_TUONG_LAI; cùng ngày mà giờ sau lúc bấm → ghi lúc bấm."""
		lui = f"{add_days(XH.hom_nay(), -5)}T09:30:00+07:00"
		ket = self._nhap("CHU", "DK1", entry_code="DK-20261116-1001", posted_at=lui, notes="Tồn kho đầu kỳ", lines=[{"product_id": "@B",
			"unit_name": "gói", "qty_tx": 10, "conv": 1, "base_qty": 10, "base_cost": 4000, "batch_code": "LOT-DK-1", "expires_at": "2099-12-31"}])
		self.assertNotIn("error", ket, ket)
		se = frappe.get_doc("Stock Entry", ket["data"][0]["entry_id"])
		self.assertEqual((se.npp_loai, se.is_opening, se.items[0].expense_account, str(se.posting_date), se.npp_ghi_chu), ("ton_dau_ky", "Yes",
			self.cd.tk_tam_dau_ky, str(add_days(XH.hom_nay(), -5)), "Tồn kho đầu kỳ"))
		self.assertEqual(get_datetime(f"{se.posting_date} {se.posting_time}").strftime("%H:%M"), "09:30")
		lo = frappe.get_doc("Batch", "LOT-DK-1")
		self.assertEqual((lo.expiry_date, str(get_datetime(lo.npp_ngay_nhap))[:16]), (None, f"{add_days(XH.hom_nay(), -5)} 09:30"))  # B không hạn
		self.assertEqual(self.repost, [1])
		mai = f"{add_days(XH.hom_nay(), 1)}T08:00:00+07:00"
		self.assertEqual(self._nhap(nhan="IN9", posted_at=mai)["error"]["message"], "NGAY_TUONG_LAI: Ngày nhập kho không được sau hôm nay.")
		cuoi_ngay = f"{XH.hom_nay()}T23:59:59+07:00"
		ket = self._nhap(nhan="IN8", entry_code="IN-T-8", posted_at=cuoi_ngay)
		self.assertNotIn("error", ket, ket)
		se = frappe.get_doc("Stock Entry", ket["data"][0]["entry_id"])
		self.assertLessEqual(get_datetime(f"{se.posting_date} {se.posting_time}"), now_datetime())

	def test_nhap_kho_lo_trung_va_ep_kieu(self):
		"""Mã lô trùng (cả trong cùng tải trọng) → LO_TRUNG_MA, không lập gì; ép kiểu sai ra lỗi thô TRƯỚC cửa vai; NCC không có → ORG_MISMATCH 42501."""
		hai = [{"product_id": "@A", "unit_name": "hộp", "qty_tx": 1, "conv": 1, "base_qty": 1, "base_cost": 1, "batch_code": "L-X"}] * 2
		se = frappe.db.count("Stock Entry")
		self.assertEqual(self._nhap(lines=hai)["error"]["message"], "LO_TRUNG_MA: Mã lô L-X đã có trong sổ — đổi mã lô ấy rồi ghi lại phiếu nhập kho.")
		self.assertEqual((frappe.db.count("Stock Entry"), frappe.db.exists("Batch", "L-X")), (se, None))
		self.assertNotIn("error", self._nhap(lines=hai[:1]))
		self.assertEqual(self._nhap(nhan="IN2", entry_code="IN-T-2", lines=hai[:1])["error"]["message"], "LO_TRUNG_MA: Mã lô L-X đã có trong sổ — "
			"đổi mã lô ấy rồi ghi lại phiếu nhập kho.")
		ket = self._nhap("NV", "IN3", payable={"amount": "năm"})
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), ("22P02", 'invalid input syntax for type numeric: "năm"'))
		for nguoi in ("NV", "KT", "QL"):
			ket = self._nhap(nguoi, "IN4")
			self.assertEqual((ket["error"]["code"], ket["error"]["message"]), ("42501", FORBIDDEN_NHAP), nguoi)
		ket = self._nhap("CHU", "IN5", supplier_id="NCC-KHONG-CO", payable={"amount": 1})
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), ("42501", "ORG_MISMATCH: nhà cung cấp không thuộc đơn vị của bạn."))
		ket = self._nhap("CHU", "IN6", lines=[{"product_id": "@A", "base_qty": 1, "base_cost": -1}])
		self.assertEqual(ket["error"]["message"], "BAD_PAYLOAD: dòng 1 có giá vốn âm.")

	def test_nhap_kho_co_ncc_la_phieu_nhap(self):
		"""CFD-13 / §7.3 điểm 3: có NCC + nợ > 0 → PHIẾU NHẬP `PN-` ghi sổ: dòng `rate` = giá vốn × hệ số (giá vốn lô = `base_cost`), MỘT dòng thuế
		`Actual` bù phần nợ lệch (Add / Deduct, TK thuế đầu vào), nợ = `payable.amount`, ghi chú nợ "Nhập kho <mã>", số HĐ NCC; không ghi giá nhập; có
		NCC mà nợ 0 → nhánh Stock Entry giữ NCC."""
		dong = [{"product_id": "@A", "unit_name": "thùng", "qty_tx": 2, "conv": 24, "base_qty": 48, "base_cost": 10000}]
		for tien, cong in ((500000, "Add"), (400000, "Deduct")):
			ket = self._nhap("CHU", f"P{tien}", entry_code=f"IN-P-{tien}", supplier_id="@S1", payable={"amount": tien, "invoice_number": " HD-9 "},
				lines=dong)
			self.assertNotIn("error", ket, ket)
			r = ket["data"][0]
			pi = frappe.get_doc("Purchase Invoice", r["entry_id"])
			self.assertEqual((pi.docstatus, pi.npp_loai, pi.update_stock, pi.bill_no, flt(pi.grand_total), pi.npp_ghi_chu_no), (1, "phieu_nhap", 1,
				"HD-9", tien, f"Nhập kho IN-P-{tien}"))
			self.assertEqual((V._dv(pi.items[0].uom), flt(pi.items[0].rate), flt(pi.items[0].qty), flt(pi.items[0].conversion_factor)),
				("thung", 240000, 2, 24))
			bu = [t for t in pi.taxes if t.charge_type == "Actual"]
			self.assertEqual([(t.account_head, flt(t.tax_amount), t.add_deduct_tax, t.category) for t in bu],
				[(self.cd.tk_thue_dau_vao, abs(tien - 480000), cong, "Total")])
			no = frappe.get_doc("NPP Cong No NCC", r["payable_id"])
			self.assertEqual((no.chung_tu, flt(no.so_tien), no.loai), (pi.name, tien, "phieu_nhap"))
			lo = f"LOT-IN-P-{tien}-1"
			self.assertEqual(flt(frappe.db.get_value("Serial and Batch Entry", {"batch_no": lo}, "incoming_rate")), 10000)  # giá vốn lô
		self.assertFalse(frappe.db.exists("Item Price", {"item_code": self.ma["A"], "price_list": self.cd.bang_gia_nhap}))
		ket = self._nhap("CHU", "IN0", entry_code="IN-P-0", supplier_id="@S1", payable={"amount": 0}, lines=dong)
		se = frappe.get_doc("Stock Entry", ket["data"][0]["entry_id"])
		self.assertEqual((se.supplier, se.npp_loai, ket["data"][0]["payable_id"]), (self.ma["S1"], "nhap_kho", None))

	# ------------------------------------------------------------------------------------------------ xuất lẻ
	def test_xuat_le_fefo_va_tai_khoan(self):
		"""Khoá Bin là câu ĐẦU; hạn cũ trước GỒM lô hết hạn (Material Issue không bị kiểm hạn); TK `tk_xuat_le` mọi dòng; gọi lại trả tên, không
		trừ hai lần; dòng cổng `unit_cost 0`, `batch_id` NULL khi lấy nhiều lô (⚠K: một lô → `<lô>::<vùng>`)."""
		# lô đã hết hạn VẪN ở kho bán (chưa rà soát) — dựng thẳng, không qua luật đẩy vùng của `_lo`
		V.dung_lo(self.ma, self.cd, {"ma": "L-HET", "sp": "@P", "vung": "sale", "ton": 3, "gia": 7000, "han": -5, "nhan_ngay": -60})
		self._lo_p("L-B", 5, 9000, 100)
		self._lo_p("L-A", 10, 8000, 200)
		ten = self._pk("X1", "export", "sale", [("@P", "Lon", 10, 1), ("@P", "Lon", 1, 1)], issue_reason="damaged")
		for nguoi in ("NV", "QL", "KT"):  # cửa vai owner / warehouse (mig 166) — sau bước "không có phiếu"
			ket = self._goi(nguoi, "post_stock_issue", {"p_entry_id": ten})
			self.assertEqual((ket["error"]["code"], ket["error"]["message"]), ("42501", FORBIDDEN_KHO), nguoi)
		self.assertEqual(self._goi("NV", "post_stock_issue", {"p_entry_id": "XKL-KHONG"})["error"]["message"],
			"PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu xuất kho này.")
		ket, dau = self._cau_dau("TK", "post_stock_issue", {"p_entry_id": ten})
		self.assertEqual(ket.get("data"), ten, ket)
		self.assertTrue("`tabBin`" in dau and "FOR UPDATE" in dau, dau)
		self.assertEqual([self._ton_lo(x, self.cd.kho_ban) for x in ("L-HET", "L-B", "L-A")], [0, 0, 7])
		se = frappe.get_doc("Stock Entry", ten)
		self.assertEqual({d.expense_account for d in se.items}, {self.cd.tk_xuat_le})
		self.assertEqual(self._rpc_tk("post_stock_issue", p_entry_id=ten)["data"], ten)
		self.assertEqual(self._ton_lo("L-A", self.cd.kho_ban), 7)
		dong = sorted(self._cong_doc("TK", "stock_entry_lines", entry_id=ten), key=lambda d: d["qty_in_base_uom"])
		self.assertEqual([(d["batch_id"], flt(d["unit_cost"])) for d in dong], [("L-A::sale", 0), (None, 0)])
		pk = self._cong_doc("NV", "stock_entries", id=ten)[0]
		self.assertEqual((pk["type"], pk["status"], pk["issue_reason"], pk["warehouse_zone"], pk["created_by"]), ("export", "posted", "damaged",
			"sale", self.ma["u:TK"]))

	def test_xuat_le_vuot_ton_chi_hang_khong_lo(self):
		"""CFD-05 B: hàng THEO LÔ luôn chặn; hàng KHÔNG lô X âm được chỉ khi cả Item.allow_negative_stock lẫn NPP cho bán vượt tồn; chuyển kho không
		bao giờ vượt tồn; nhiều mặt hàng thiếu → báo mặt hàng đầu theo mã."""
		x = self.ma["X"]
		ten = self._pk("X1", "export", "sale", [("@X", "cai", 3, 1)])
		# đơn vị so không dấu / hoa thường (bản ghi UOM có trước — "cái"): `V._dv`
		self.assertEqual(V._dv(self._rpc_tk("post_stock_issue", p_entry_id=ten)["error"]["message"]), V._dv("KHONG_DU_TON: Hàng không lô — cần "
			"3.000000 cai, kho hàng bán chỉ còn 0. Giảm số lượng, đổi kho, hoặc nhập bù rồi ghi sổ lại."))
		self._ok(buoc="co_am", nguoi="MAY_CHU", bat=True)
		frappe.db.set_value("Item", x, "allow_negative_stock", 0)
		self.assertIn("KHONG_DU_TON", self._rpc_tk("post_stock_issue", p_entry_id=ten)["error"]["message"])
		frappe.db.set_value("Item", x, "allow_negative_stock", 1)
		self.assertEqual(self._rpc_tk("post_stock_issue", p_entry_id=ten)["data"], ten)
		self.assertEqual(self._bin_x(), -3)
		ck = self._pk("C1", "transfer", "sale", [("@X", "cai", 1, 1)], dich="date")
		self.assertEqual(V._dv(self._rpc_tk("post_stock_transfer", p_entry_id=ck)["error"]["message"]), V._dv("KHONG_DU_TON: Hàng không lô — cần "
			"1.000000 cai, kho hàng bán chỉ còn -3.000000. Giảm số lượng hoặc đổi kho nguồn."))
		hai = self._pk("X2", "export", "sale", [("@P", "Lon", 1, 1), ("@A", "hộp", 2, 1)])
		self.assertTrue(V._dv(self._rpc_tk("post_stock_issue", p_entry_id=hai)["error"]["message"]).startswith(V._dv("KHONG_DU_TON: Hàng A — cần "
			"2.000000 hộp")))  # SPA trước SPP

	# ------------------------------------------------------------------------------------------------ chuyển kho
	def test_chuyen_kho_giu_gia_lo_va_nguong(self):
		"""Lõi lập phía nhận CÙNG Batch, giữ giá lô (đo §7.1 #13); dấu chuyển vùng (lúc + NV); thẻ kho hai dòng; ranh ngưỡng: hạn = hôm nay +
		ngưỡng chặn (câu nói "dưới" nhưng `<=` — nppsale), +ngưỡng+1 qua; đích kho date không xét hạn."""
		self._lo_p("L-A", 10, 8000, 200)
		ten = self._pk("C1", "transfer", "sale", [("@P", "Lon", 4, 1)], dich="date")
		ket = self._goi("QL", "post_stock_transfer", {"p_entry_id": ten})
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), ("42501", FORBIDDEN_KHO))
		self.assertEqual(self._rpc_tk("post_stock_transfer", p_entry_id=ten)["data"], ten)
		self.assertEqual((self._ton_lo("L-A", self.cd.kho_ban), self._ton_lo("L-A", self.cd.kho_can_date)), (6, 4))
		r = self._cong_doc("TK", "stock_entries", select="type, status, warehouse_zone, dest_warehouse_zone, lines:stock_entry_lines(batch_id, "
			"unit_cost)", id=ten)[0]
		self.assertEqual((r["type"], r["status"], r["warehouse_zone"], r["dest_warehouse_zone"], [(d["batch_id"], flt(d["unit_cost"])) for d in r["lines"]]),
			("transfer", "posted", "sale", "date", [("L-A::sale", 0)]))
		lo = frappe.db.get_value("Batch", "L-A", ["npp_chuyen_vung_luc", "npp_chuyen_vung_boi"], as_dict=True)
		self.assertEqual(lo.npp_chuyen_vung_boi, frappe.db.get_value("NPP Nhan Vien", {"user": self.ma["u:TK"]}, "name"))
		self.assertIsNotNone(lo.npp_chuyen_vung_luc)
		gia = {r["warehouse_zone"]: flt(r["unit_cost"]) for r in self._cong_doc("CHU", "batches", batch_code="L-A")}
		self.assertEqual(gia, {"sale": 8000, "date": 8000})
		bd = sorted((r["warehouse_zone"], flt(r["signed_qty_in_base_uom"]), flt(r["unit_cost"]), r["entry_type"], r["transaction_uom"])
			for r in self._cong_doc("CHU", "v_stock_movements", entry_id=ten))
		self.assertEqual(bd, [("date", 4, 0, "transfer", "Lon"), ("sale", -4, 0, "transfer", "Lon")])
		self.assertEqual(self._rpc_tk("cancel_stock_entry", p_entry_id=ten, p_reason="x")["error"]["message"], f"CANNOT_REVERSE_TYPE: phiếu {ten} "
			"(transfer) đã ghi sổ nhưng chưa có đường hoàn kho cho loại phiếu này. Dùng phiếu điều chỉnh để sửa tồn.")
		ng = self.cd.nguong
		self._lo_p("L-30", 2, 7000, ng, vung="date")
		self._lo_p("L-31", 2, 7000, ng + 1, vung="date", sp="@G")
		ve = self._pk("C2", "transfer", "date", [("@P", "Lon", 1, 1)], dich="sale")
		self.assertEqual(self._rpc_tk("post_stock_transfer", p_entry_id=ve)["error"]["message"], f"HANG_GAN_HAN: Nuoc ngot (lô L-30, hạn "
			f"{add_days(XH.hom_nay(), ng).strftime('%d/%m/%Y')}) chỉ còn dưới {ng} ngày nên không chuyển sang kho hàng bán được — hệ thống sẽ tự đẩy về kho "
			"hàng date. Bán hàng gần hạn qua kênh hàng date.")
		ve2 = self._pk("C3", "transfer", "date", [("@G", "Kg", 1, 1)], dich="sale")
		self.assertEqual(self._rpc_tk("post_stock_transfer", p_entry_id=ve2)["data"], ve2)
		# lô cận hạn còn ở kho bán (chưa rà soát) đứng đầu FEFO: đích kho date không xét hạn
		V.dung_lo(self.ma, self.cd, {"ma": "L-S", "sp": "@P", "vung": "sale", "ton": 2, "gia": 7000, "han": 5, "nhan_ngay": -60})
		ve3 = self._pk("C4", "transfer", "sale", [("@P", "Lon", 1, 1)], dich="date")
		self.assertEqual(self._rpc_tk("post_stock_transfer", p_entry_id=ve3)["data"], ve3)
		self.assertEqual(self._ton_lo("L-S", self.cd.kho_can_date), 1)
		trung = self._pk("C5", "transfer", "date", [("@P", "Lon", 1, 1)], dich="date")
		self.assertEqual(self._rpc_tk("post_stock_transfer", p_entry_id=trung)["error"]["message"],
			"TRUNG_KHO: Kho nguồn và kho đích đang là một (date). Chọn hai kho khác nhau.")
		thieu = self._pk("C6", "transfer", "date", [("@P", "Lon", 1, 1)])
		self.assertEqual(self._rpc_tk("post_stock_transfer", p_entry_id=thieu)["error"]["message"], "THIEU_KHO_DICH: Phiếu chuyển kho chưa chọn kho đích.")
		self.assertEqual(self._rpc_tk("post_stock_issue", p_entry_id=thieu)["error"]["message"], "SAI_LOAI_PHIEU: Phiếu này không phải phiếu xuất kho.")
		self.assertEqual(self._rpc_tk("post_stock_transfer", p_entry_id=self._pk("X9", "export", "sale", [("@P", "Lon", 1, 1)]))["error"]["message"],
			"SAI_LOAI_PHIEU: Phiếu này không phải phiếu chuyển kho.")

	# ------------------------------------------------------------------------------------------------ huỷ phiếu kho
	def test_huy_vai_va_trang_thai(self):
		"""Không có phiếu → ENTRY_NOT_FOUND; vai kiểm TRƯỚC bước "đã huỷ"; xuất lẻ → hoàn đúng lô, `lines_reversed` = số lô, ghi chú nối "Huỷ phiếu:
		(không ghi lý do)", xếp repost; huỷ lại → [true, false, 0]; xoá nháp KHÔNG lùi dãy số (không cấp lại tên)."""
		self.assertEqual(self._rpc_tk("cancel_stock_entry", p_entry_id="XKL-KHONG")["error"]["message"], "ENTRY_NOT_FOUND: không tìm thấy phiếu kho này.")
		self._lo_p("L-B", 5, 9000, 100)
		self._lo_p("L-A", 10, 8000, 200)
		ten = self._pk("X1", "export", "sale", [("@P", "Lon", 7, 1)])
		self._rpc_tk("post_stock_issue", p_entry_id=ten)
		ket = self._goi("QL", "cancel_stock_entry", {"p_entry_id": ten})
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), ("42501", FORBIDDEN_KHO))
		self.assertEqual(self._rpc_tk("cancel_stock_entry", p_entry_id=ten, p_reason=None)["data"],
			[{"cancelled": True, "reversed": True, "lines_reversed": 2}])
		self.assertEqual((self._ton_lo("L-A", self.cd.kho_ban), self._ton_lo("L-B", self.cd.kho_ban)), (10, 5))
		self.assertEqual(frappe.db.get_value("Stock Entry", ten, ["docstatus", "npp_ghi_chu"]), (2, "Huỷ phiếu: (không ghi lý do)"))
		self.assertEqual(self.repost, [1])
		ket = self._goi("NV", "cancel_stock_entry", {"p_entry_id": ten})
		self.assertEqual(ket["error"]["code"], "42501")  # vai trước "đã huỷ"
		self.assertEqual(self._rpc_tk("cancel_stock_entry", p_entry_id=ten)["data"], [{"cancelled": True, "reversed": False, "lines_reversed": 0}])
		nhap = self._pk("N1", "export", "sale", [("@P", "Lon", 1, 1)])
		self.assertEqual(self._rpc_tk("cancel_stock_entry", p_entry_id=nhap, p_reason="")["data"],
			[{"cancelled": True, "reversed": False, "lines_reversed": 0}])
		self.assertFalse(frappe.db.exists("Stock Entry", nhap))
		self.assertNotEqual(self._pk("N2", "export", "sale", [("@P", "Lon", 1, 1)]), nhap)  # số không cấp lại

	def test_huy_nhap_kho(self):
		"""Nhập kho tay: nợ NCC lập tay gắn phiếu (`NTN-`) → ENTRY_HAS_SOURCE (công nợ NCC); lô đã xuất bớt → ALREADY_ISSUED (không nới khi cho bán
		vượt tồn — hàng theo lô); hàng KHÔNG lô đã bán bớt: chặn khi không được âm, được âm (hai cờ) thì huỷ được; `lines_reversed` = số dòng."""
		ket = self._nhap(entry_code="IN-T-1", supplier_id="@S1")
		ten = ket["data"][0]["entry_id"]
		ket = self._cong("CHU", {"bang": "payables", "hanh_dong": "insert", "select": "id", "gia_tri": {"org_id": self.ma["org"], "supplier_id": self.ma["S1"],
			"invoice_number": "HD-TAY", "paid": 0, "status": "open", "amount": 100000, "stock_entry_id": ten}})
		self.assertNotIn("error", ket, ket)
		self.assertEqual(self._rpc_tk("cancel_stock_entry", p_entry_id=ten)["error"]["message"], f"ENTRY_HAS_SOURCE: phiếu {ten} đang có công nợ NCC. "
			"Xoá công nợ NCC đó trước rồi mới huỷ phiếu kho.")
		self._ok(buoc="co_am", nguoi="MAY_CHU", bat=True)
		ket = self._nhap(nhan="IN2", entry_code="IN-T-2", lines=[{"product_id": "@G", "unit_name": "Kg", "qty_tx": 10, "conv": 1, "base_qty": 10,
			"base_cost": 20000}, {"product_id": "@X", "unit_name": "cai", "qty_tx": 4, "conv": 1, "base_qty": 4, "base_cost": 1000}])
		ten2 = ket["data"][0]["entry_id"]
		xk = self._pk("X1", "export", "sale", [("@G", "Kg", 1, 1)])
		self._rpc_tk("post_stock_issue", p_entry_id=xk)
		self.assertEqual(self._rpc_tk("cancel_stock_entry", p_entry_id=ten2)["error"]["message"], f'ALREADY_ISSUED: "Gao" của phiếu {ten2} đã xuất '
			"bớt — nhập 10.000000 nhưng lô chỉ còn 9.000000. Phiếu đã xuất thì chỉ SỬA được, không huỷ được.")
		self._rpc_tk("cancel_stock_entry", p_entry_id=xk)
		x1 = self._pk("X2", "export", "sale", [("@X", "cai", 3, 1)])
		self._rpc_tk("post_stock_issue", p_entry_id=x1)
		self._ok(buoc="co_am", nguoi="MAY_CHU", bat=False)
		self.assertEqual(self._rpc_tk("cancel_stock_entry", p_entry_id=ten2)["error"]["message"], f'ALREADY_ISSUED: "Hàng không lô" của phiếu {ten2} '
			"đã xuất bớt — nhập 4.000000 nhưng lô chỉ còn 1.000000. Phiếu đã xuất thì chỉ SỬA được, không huỷ được.")
		self._ok(buoc="co_am", nguoi="MAY_CHU", bat=True)
		self.assertEqual(self._rpc_tk("cancel_stock_entry", p_entry_id=ten2, p_reason="x")["data"],
			[{"cancelled": True, "reversed": True, "lines_reversed": 2}])
		self.assertEqual(self._bin_x(), -3)

	def test_huy_chung_tu_goc(self):
		"""Việc #24 + §3.19 bước 2 / 4: nguồn nhận diện bằng TRƯỜNG THẬT — tờ ghi có có kho của phiếu trả khách Hoàn thành → "là hàng khách trả. Huỷ
		phiếu trả hàng đó…"; phiếu trả bị huỷ (tờ thôi ghi sổ) → "Huỷ / sửa phiếu trả hàng đó…"; Stock Entry `NL-` (`nhap_lai_tra` + Link phiếu trả)
		cùng luật; PN / trả NCC / HĐ → câu của nppsale; ghi chú cổng "Nhập lại từ phiếu trả <phiếu>" (§10 điểm 1) — khớp NGUYÊN chuỗi."""
		self._lo_p("L-A", 10, 8000, 200)
		self._ok(buoc="tra_khach", nguoi="CHU", nhan="T1", khach="@K1", dong=[{"product_id": "@P", "unit_name": "Lon", "quantity": 1,
			"unit_price": 10000, "vat_rate": 0, "is_exchange": False}])
		pt = self._nh("tk:T1")
		cn = frappe.db.get_value("NPP Phieu Tra", pt, "to_ghi_co")
		self.assertEqual(frappe.db.get_value("Sales Invoice", cn, ["is_return", "update_stock", "docstatus"]), (1, 1, 1))
		self.assertEqual(self._goi("CHU", "cancel_stock_entry", {"p_entry_id": cn})["error"]["message"], f"ENTRY_HAS_SOURCE: phiếu {cn} là hàng "
			"khách trả. Huỷ phiếu trả hàng đó thay vì huỷ riêng phiếu kho.")
		r = self._cong_doc("TK", "stock_entries", id=cn)[0]
		self.assertEqual((r["type"], r["status"], r["notes"]), ("import", "posted", f"Nhập lại từ phiếu trả {pt}"))
		# Stock Entry NL- của phiếu (P3 lập khi phiếu tự sinh / chỉ hàng đổi) — dựng bằng một phiếu nhập kho gắn Link
		nl = self._nhap(nhan="NL", entry_code="NL-T", lines=[{"product_id": "@P", "unit_name": "Lon", "qty_tx": 1, "conv": 1, "base_qty": 1,
			"base_cost": 8000, "batch_code": "L-NL"}])["data"][0]["entry_id"]
		frappe.db.set_value("Stock Entry", nl, {"npp_loai": "nhap_lai_tra", "npp_phieu_tra": pt}, update_modified=False)
		self.assertEqual(self._goi("CHU", "cancel_stock_entry", {"p_entry_id": nl})["error"]["message"], f"ENTRY_HAS_SOURCE: phiếu {nl} là hàng "
			"khách trả. Huỷ phiếu trả hàng đó thay vì huỷ riêng phiếu kho.")
		self.assertEqual(self._cong_doc("TK", "stock_entries", id=nl)[0]["notes"], f"Nhập lại từ phiếu trả {pt}")
		ma = {r[0] for r in frappe.db.sql(f"SELECT x.chung_tu FROM {nguon_dong_nhap_lai()} x WHERE x.pt = %s", pt)}
		self.assertEqual(ma, {cn, nl})
		ket = self._goi("CHU", "cancel_return", {"p_return_id": pt, "p_reason": "nham"})
		self.assertNotIn("error", ket, ket)
		self.assertEqual(frappe.db.get_value("Sales Invoice", cn, "docstatus"), 2)
		self.assertEqual(self._goi("CHU", "cancel_stock_entry", {"p_entry_id": cn})["error"]["message"], f"ENTRY_HAS_SOURCE: phiếu {cn} là hàng "
			"khách trả. Huỷ / sửa phiếu trả hàng đó thay vì huỷ riêng phiếu kho.")
		self.assertEqual(self._goi("CHU", "cancel_stock_entry", {"p_entry_id": nl})["error"]["message"], f"ENTRY_HAS_SOURCE: phiếu {nl} là hàng "
			"khách trả. Huỷ / sửa phiếu trả hàng đó thay vì huỷ riêng phiếu kho.")
		# Stock Entry nhập thường (không Link) huỷ được — cùng loại nhưng KHÔNG nhận theo ghi chú
		frappe.db.set_value("Stock Entry", nl, {"npp_loai": "nhap_kho", "npp_phieu_tra": None, "npp_ghi_chu": f"Nhập lại từ phiếu trả {pt}"},
			update_modified=False)
		self.assertEqual(self._goi("CHU", "cancel_stock_entry", {"p_entry_id": nl})["data"][0]["reversed"], True)

	# ------------------------------------------------------------------------------------------------ cổng đọc
	def _pn_xong(self, nhan="P", sl=10):
		self._ok(buoc="pn", nguoi="TK", nhan=nhan, dau={"org_id": "@org", "supplier_id": "@S1", "invoice_number": None, "warehouse_zone": "sale",
			"discount": 0, "vat_override": None, "notes": "ghi chu PN", "status": "draft", "created_by": "@u:TK"}, dong=[{"product_id": "@A",
			"unit_name": "hộp", "quantity": sl, "unit_price": 10000, "line_discount": 0, "vat_rate": 0, "conversion_factor": 1, "line_total": sl * 10000,
			"notes": None, "sort_order": 1}])
		pn = self._nh("pn:" + nhan)
		self.assertEqual(self._cong_doc("TK", "stock_entries", id=pn), [])  # nháp KHÔNG có phiếu kho
		self._ok(buoc="pn_hoan", nguoi="TK", nhan=nhan)
		return pn

	def test_cong_doc_gop_nguon(self):
		"""PN (import, ghi chú của tờ, dòng giá vốn), trả NCC (export, dòng giá LÔ — không giá trả: S2), HĐ (export, `ref_order_ids` [đơn], dòng giá
		xuất), HĐ huỷ → `cancelled`; hằng P6 `nguon_dong_xuat` cùng luật giá (xuất lẻ 0)."""
		pn = self._pn_xong()
		r = self._cong_doc("NV", "stock_entries", select="*, lines:stock_entry_lines(*)", id=pn)[0]
		self.assertEqual((r["type"], r["status"], r["entry_code"], r["supplier_id"], r["notes"], r["warehouse_zone"], r["ref_order_ids"]), ("import",
			"posted", pn, self.ma["S1"], "ghi chu PN", "sale", []))
		self.assertEqual([(d["batch_id"], flt(d["qty_in_base_uom"]), d["unit_cost"]) for d in r["lines"]], [(f"{pn}-001::sale", 10, None)])  # NV: che
		self.assertEqual(flt(self._cong_doc("CHU", "stock_entry_lines", entry_id=pn)[0]["unit_cost"]), 10000)
		# lồng của /purchasing/invoices + màn phiếu kho: nợ NCC (một-nhiều qua `NPP Cong No NCC.phieu_kho`) và người lập (đúng tên khoá ngoại)
		r = self._cong_doc("CHU", "stock_entries", select="id, debt:payables!inner(status), creator:users!stock_entries_created_by_fkey(full_name)",
			id=pn)[0]
		self.assertEqual((r["debt"], bool(r["creator"])), ([{"status": "open"}], True))
		self._ok(buoc="ptn", nguoi="TK", nhan="R", dau={"org_id": "@org", "supplier_id": "@S1", "warehouse_zone": "sale", "discount": 0,
			"vat_override": None, "reason": None, "notes": None, "status": "draft", "created_by": "@u:TK"}, dong=[{"product_id": "@A", "unit_name": "hộp",
			"quantity": 3, "unit_price": 12000, "line_discount": 0, "vat_rate": 0, "conversion_factor": 1, "line_total": 36000, "notes": None,
			"sort_order": 1}])
		self._ok(buoc="ptn_gui", nguoi="TK", nhan="R")
		tra = self._nh("ptn:R")
		r = self._cong_doc("CHU", "stock_entries", select="type, status, lines:stock_entry_lines(unit_cost, qty_in_base_uom)", id=tra)[0]
		self.assertEqual((r["type"], r["status"], [(flt(d["unit_cost"]), flt(d["qty_in_base_uom"])) for d in r["lines"]]), ("export", "posted",
			[(10000, 3)]))
		self._ok(buoc="ban", nguoi="CHU", nhan="H1", khach="@K1", dong=[{"product_id": "@A", "unit_name": "hộp", "quantity": 2}])
		hd = self._nh("hd:H1")
		r = self._cong_doc("CHU", "stock_entries", select="type, status, ref_order_ids, lines:stock_entry_lines(unit_cost)", id=hd)[0]
		self.assertEqual((r["type"], r["status"], r["ref_order_ids"], [flt(d["unit_cost"]) for d in r["lines"]]), ("export", "posted",
			[self._nh("don:H1")], [10000]))
		xk = self._pk("X1", "export", "sale", [("@A", "hộp", 1, 1)])
		self._rpc_tk("post_stock_issue", p_entry_id=xk)
		dong = {x[0]: (x[1], flt(x[2]), flt(x[3])) for x in frappe.db.sql(f"""SELECT x.chung_tu, x.loai, x.sl, x.gia FROM {NGUON_DONG_XUAT} x
			WHERE x.chung_tu IN %s""", ((tra, hd, xk),))}
		self.assertEqual(dong, {tra: ("tra_ncc", 3, 10000), hd: ("hoa_don", 2, 10000), xk: ("xuat_le", 1, 0)})
		self._ok(buoc="huy_hd", nguoi="CHU", nhan="H1", ly_do="x")
		self.assertEqual(self._cong_doc("CHU", "stock_entries", select="status", id=hd)[0]["status"], "cancelled")
		self.assertEqual(self._goi("CHU", "cancel_stock_entry", {"p_entry_id": pn})["error"]["message"], f"ENTRY_HAS_SOURCE: phiếu {pn} thuộc một hoá "
			"đơn nhập mua. Huỷ hoá đơn nhập đó thay vì huỷ riêng phiếu kho.")
		self.assertEqual(self._goi("CHU", "cancel_stock_entry", {"p_entry_id": tra})["error"]["message"], f"ENTRY_HAS_SOURCE: phiếu {tra} thuộc một "
			"phiếu trả NCC. Huỷ phiếu trả NCC đó thay vì huỷ riêng phiếu kho.")

	def test_cong_doc_view_va_bang_khong_port(self):
		"""v_stock_balance_by_zone (Bin > 0, giá trị che theo giá vốn); thẻ kho của phiếu nhập kho tay: ĐV giao dịch nối qua dòng chứng từ, giá nhập;
		phiếu huỷ biến mất; bảng không port đọc rỗng cho mọi NV, ghi → LEGACY_FLOW_REMOVED."""
		ket = self._nhap(lines=[{"product_id": "@A", "unit_name": "thùng", "qty_tx": 2, "conv": 24, "base_qty": 48, "base_cost": 10000}])
		ten = ket["data"][0]["entry_id"]
		bd = self._cong_doc("CHU", "v_stock_movements", entry_id=ten)
		self.assertEqual([(V._dv(r["transaction_uom"]), flt(r["qty_in_transaction_uom"]), flt(r["conversion_factor"]), flt(r["signed_qty_in_base_uom"]),
			flt(r["unit_cost"]), r["entry_type"], r["entry_status"], r["warehouse_zone"]) for r in bd], [("thung", 2, 24, 48, 10000, "import", "posted",
			"sale")])
		self.assertIsNone(self._cong_doc("NV", "v_stock_movements", entry_id=ten)[0]["unit_cost"])
		ton = self._cong_doc("CHU", "v_stock_balance_by_zone", product_id=self.ma["A"])
		self.assertEqual([(r["warehouse_zone"], flt(r["qty_in_base_uom"]), flt(r["value"])) for r in ton], [("sale", 48, 480000)])
		self.assertIsNone(self._cong_doc("NV", "v_stock_balance_by_zone", product_id=self.ma["A"])[0]["value"])
		ket = self._goi("TK", "confirm_driver_handover", {"p_handover_id": "x"})  # §7.3 điểm 40
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), ("P0001", "LEGACY_FLOW_REMOVED: chức năng đã gỡ"))
		ket = self._cong("CHU", {"bang": "v_stock_movements", "hanh_dong": "update", "gia_tri": {"unit_cost": 1}, "loc": [{"op": "eq", "cot": "id",
			"gt": bd[0]["id"]}]})
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), ("42501", 'new row violates row-level security policy for table '
			'"v_stock_movements"'))
		self._rpc_tk("cancel_stock_entry", p_entry_id=ten)
		self.assertEqual(self._cong_doc("CHU", "v_stock_movements", entry_id=ten), [])
		self.assertEqual(self._cong_doc("CHU", "v_stock_balance_by_zone", product_id=self.ma["A"]), [])
		for bang in ("swap_stock_movements", "purchase_orders", "purchase_order_lines"):
			self.assertEqual(self._cong_doc("NV", bang), [], bang)
			ket = self._cong("CHU", {"bang": bang, "hanh_dong": "insert", "gia_tri": {"id": "x"}})
			self.assertEqual(ket["error"]["message"], "LEGACY_FLOW_REMOVED: chức năng đã gỡ", bang)

	# ------------------------------------------------------------------------------------------------ cổng ghi nháp
	def test_cong_ghi_nhap(self):
		"""Ràng buộc nppsale (CHECK / FK / NOT NULL), RLS (NVBH chèn → 42501, quản lý sửa → 0 dòng), dòng lệch SL × hệ số về đơn vị kho, khoá tìm,
		phiếu nhập nháp `IN-` (kho người chọn), phiếu kiểm kê nháp (M6), ghi chú của chứng từ gốc (HĐ / PI) không sửa ở phiếu kho."""
		ins = lambda g, nguoi="TK": self._cong(nguoi, {"bang": "stock_entries", "hanh_dong": "insert", "select": "id",  # noqa: E731
			"gia_tri": {"org_id": self.ma["org"], "status": "draft", **g}})
		self.assertEqual(ins({"type": "lạ"})["error"]["message"], 'new row for relation "stock_entries" violates check constraint '
			'"stock_entries_type_check"')
		self.assertEqual(ins({"type": "export", "warehouse_zone": "x"})["error"]["message"], 'new row for relation "stock_entries" violates check '
			'constraint "stock_entries_zone_chk"')
		self.assertEqual(ins({"type": "transfer", "dest_warehouse_zone": "x"})["error"]["code"], "23514")
		self.assertEqual(ins({"type": "export", "supplier_id": "NCC-KHONG"})["error"]["message"], 'insert or update on table "stock_entries" violates '
			'foreign key constraint "stock_entries_supplier_id_fkey"')
		self.assertEqual(ins({"type": "export", "cot_la": 1})["error"]["code"], "PGRST204")
		self.assertEqual(ins({"type": "export"}, "NV")["error"]["message"], RLS_PK)
		# trigger mig 170 chạy TRƯỚC RLS: quên cột `status` (mặc định posted) → SO_KHO_KHOA kể cả với NVBH
		khong_tt = self._cong("NV", {"bang": "stock_entries", "hanh_dong": "insert", "gia_tri": {"org_id": self.ma["org"], "type": "export"}})
		self.assertEqual(khong_tt["error"]["message"], "SO_KHO_KHOA: phiếu kho lập từ màn hình phải là phiếu NHÁP — ghi sổ đi qua nút Duyệt / Hoàn thành.")
		kk = ins({"type": "stocktake"})["data"][0]["id"]  # M6: phiếu kiểm kê nháp `NPP Kiem Ke` (chi tiết ở nppsale.tests.test_kiem_ke)
		self.assertEqual(frappe.db.get_value("NPP Kiem Ke", kk, ["trang_thai", "kho"]), ("draft", self.cd.kho_ban))
		ten = ins({"type": "import", "warehouse_zone": "date", "notes": "nhap nhap"})["data"][0]["id"]
		se = frappe.get_doc("Stock Entry", ten)
		self.assertEqual((se.docstatus, se.purpose, se.npp_kho_nhap, se.to_warehouse, se.npp_ghi_chu, se.npp_tim_kd), (0, "Material Receipt",
			self.cd.kho_can_date, self.cd.kho_can_date, "nhap nhap", khoa_tim_ds(ten)))
		them = lambda g, nguoi="TK": self._cong(nguoi, {"bang": "stock_entry_lines", "hanh_dong": "insert", "select": "id",  # noqa: E731
			"gia_tri": {"entry_id": ten, **g}})
		self.assertEqual(them({"product_id": "SP-KHONG", "unit_name": "x", "qty_in_base_uom": 1})["error"]["message"], 'insert or update on table '
			'"stock_entry_lines" violates foreign key constraint "stock_entry_lines_product_id_fkey"')
		self.assertEqual(them({"product_id": self.ma["A"], "unit_name": "hộp"})["error"]["code"], "23502")
		self.assertEqual(them({"product_id": self.ma["A"], "unit_name": "hộp", "qty_in_base_uom": 1}, "NV")["error"]["message"], RLS_DONG)
		self.assertEqual(them({"product_id": self.ma["A"], "unit_name": "hộp", "qty_in_base_uom": 0})["error"]["message"],
			"SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0.")
		ket = them({"product_id": self.ma["A"], "unit_name": "thùng", "qty_in_base_uom": 30, "qty_in_transaction_uom": 1,
			"conversion_factor_snapshot": 24})  # 1 × 24 ≠ 30 → đơn vị kho, hệ số 1
		self.assertNotIn("error", ket, ket)
		d = frappe.get_doc("Stock Entry", ten).items[0]
		self.assertEqual((d.uom, flt(d.qty), flt(d.conversion_factor), flt(d.transfer_qty)), (frappe.db.get_value("Item", self.ma["A"], "stock_uom"),
			30, 1, 30))
		sua = self._cong("QL", {"bang": "stock_entries", "hanh_dong": "update", "select": "id", "gia_tri": {"notes": "x"}, "loc": [{"op": "eq",
			"cot": "id", "gt": ten}]})
		self.assertEqual(sua.get("data"), [])
		self._nhap(nhan="INB", entry_code="IN-B-1")
		self._ok(buoc="ban", nguoi="CHU", nhan="H1", khach="@K1", dong=[{"product_id": "@A", "unit_name": "hộp", "quantity": 1}])
		hd = self._nh("hd:H1")
		ket = self._cong("TK", {"bang": "stock_entries", "hanh_dong": "update", "select": "id", "gia_tri": {"notes": "y"}, "loc": [{"op": "eq",
			"cot": "id", "gt": hd}]})
		self.assertEqual(ket["error"]["message"], "SO_KHO_KHOA: phiếu kho này là chính hoá đơn / phiếu nhập / phiếu trả NCC — sửa ghi chú ở chứng từ gốc.")
		ket = self._cong("TK", {"bang": "stock_entry_lines", "hanh_dong": "update", "gia_tri": {"notes": "z"}, "loc": [{"op": "eq", "cot": "entry_id",
			"gt": hd}]})
		self.assertEqual(ket["error"]["message"], "SO_KHO_KHOA: phiếu đã ghi sổ — không sửa dòng hàng được nữa.")

	def test_cai_dat_tai_khoan(self):
		"""Tài khoản mặc định (thiet_lap.kho_mua.dam_bao — BP §7.1 điểm 16, Q9): xuất lẻ = giá vốn hàng bán của công ty, nhập kho không HĐ = "hàng về
		chưa có hoá đơn"; thiếu `tk_xuat_le` → xuất lẻ báo CAI_DAT_THIEU (không để lõi lặng lẽ điền Stock Adjustment)."""
		cty = frappe.get_cached_doc("Company", self.cd.cong_ty)
		self.assertEqual((self.cd.tk_xuat_le, self.cd.tk_nhap_kho_khong_hd), (cty.default_expense_account, cty.stock_received_but_not_billed))
		self._lo_p("L-A", 10, 8000, 200)
		ten = self._pk("X1", "export", "sale", [("@P", "Lon", 1, 1)])
		frappe.db.set_single_value("NPP Cai Dat", "tk_xuat_le", None)
		frappe.local._npp_cai_dat_ban = None
		self.assertEqual(self._rpc_tk("post_stock_issue", p_entry_id=ten)["error"]["message"],
			"CAI_DAT_THIEU: NPP Cai Dat chưa có tài khoản xuất lẻ (tk_xuat_le).")

	# ------------------------------------------------------------------------------------------------ soát P4
	def test_tim_kd_phieu_kho_lap_bang_method(self):
		"""Soát P4 (§4.5): phiếu kho lập thẳng bằng method — nhập kho tay không NCC (`IN-…`, `_phieu_nhap_kho`) và Stock Entry lưu qua lõi như phiếu
		nhập lại hàng khách trả `NL-` của P3 — có khoá tìm `tim_kd` = khoá của mã (hook `validate` của Stock Entry): gõ mã liền / bỏ số 0 như ô tìm của
		danh sách (`tachTuTim` → `entry_code.ilike` OR `tim_kd.ilike`) ra phiếu, như `PN-` cùng danh sách."""
		ten = self._nhap(nhan="INT", entry_code="IN-T-TIM")["data"][0]["entry_id"]
		se = frappe.new_doc("Stock Entry")
		se.update({"naming_series": "NL-.####", "stock_entry_type": "Material Receipt", "purpose": "Material Receipt", "company": self.cd.cong_ty,
			"to_warehouse": self.cd.kho_ban, "npp_loai": "nhap_lai_tra"})
		se.append("items", {"item_code": self.ma["X"], "qty": 1, "t_warehouse": self.cd.kho_ban, "basic_rate": 1000, "set_basic_rate_manually": 1})
		se.flags.ignore_permissions = True
		se.insert()
		for x in (ten, se.name):
			self.assertEqual(frappe.db.get_value("Stock Entry", x, "npp_tim_kd"), khoa_tim_ds(x))
			gon = x.replace("-", "").lower()
			for tu in (gon, re.sub(r"(?<=\D)0+(?=\d)", "", gon)):
				ds = self._cong("TK", {"bang": "stock_entries", "select": "id", "loc": [{"op": "or",
					"bieu_thuc": f"entry_code.ilike.*{tu.upper()}*,tim_kd.ilike.*{tu}*"}]})
				self.assertNotIn("error", ds, ds)
				self.assertIn(x, [r["id"] for r in ds["data"]], tu)

	def test_nhap_kho_co_ncc_sua_khoi_phuc_giu_no(self):
		"""Soát P4 (§7.3 điểm 3, Q9 M4): phiếu nhập sinh từ màn Nhập kho có NCC + nợ mang dòng thuế bù phần nợ lệch giá vốn (`npp_no_lech_gia_von`) —
		sửa phiếu (nhánh A: lô chưa xuất — tờ amend; nhánh B: lô đã bán — chỉ giá) và khôi phục sau huỷ đều GIỮ đúng nợ = `payable.amount` (lệch dương
		lẫn âm; sửa giá thì nợ đổi đúng phần chênh tiền hàng); cổng `vat` không gồm phần lệch (màn sửa / POS nạp lại thuế không đếm hai lần); không ghi
		bảng giá nhập ở mọi đường (giá dòng là giá VỐN)."""
		dong = [{"product_id": "@A", "unit_name": "hộp", "qty_tx": 10, "conv": 1, "base_qty": 10, "base_cost": 10000}]
		pn = self._nhap("CHU", "PL", entry_code="IN-PL-1", supplier_id="@S1", payable={"amount": 130000}, lines=dong)["data"][0]["entry_id"]

		def no(x):
			return flt(frappe.db.get_value("NPP Cong No NCC", {"chung_tu": x}, "so_tien"))

		self.assertEqual((flt(frappe.db.get_value("Purchase Invoice", pn, "grand_total")), no(pn)), (130000, 130000))
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pn, ["npp_ma_nhap_kho", "npp_no_lech_gia_von"]), ("IN-PL-1", 30000))
		self.assertEqual(self._cong_doc("KT", "purchase_invoices", "subtotal, vat, total, vat_override", id=pn)[0],
			{"subtotal": 100000, "vat": 0, "total": 130000, "vat_override": None})
		it = frappe.get_doc("Purchase Invoice", pn).items[0]

		def sua(ten, gia=10000, ghi_chu="sửa"):
			return self._goi("KT", "sua_phieu_nhap", {"p_invoice_id": ten, "p_head": {"supplier_id": self.ma["S1"], "invoice_number": None,
				"invoice_date": str(getdate(nowdate())), "warehouse_zone": "sale", "discount": 0, "vat_override": None, "notes": ghi_chu},
				"p_lines": [{"product_id": it.item_code, "unit_name": it.uom, "quantity": flt(it.qty), "unit_price": gia, "line_discount": 0,
					"vat_rate": 0, "conversion_factor": flt(it.conversion_factor), "notes": None, "sort_order": 1}]})

		ket = sua(pn)  # nhánh A (lô chưa xuất): tờ amend giữ dòng lệch
		self.assertNotIn("error", ket, ket)
		moi = ket["data"]["id"]
		self.assertNotEqual(moi, pn)
		self.assertEqual((flt(frappe.db.get_value("Purchase Invoice", moi, "grand_total")), no(moi), ket["data"]["total"]), (130000, 130000, 130000))
		# nhánh B (lô đã bán): sửa ghi chú → không bút toán, nợ giữ; sửa giá 11.000 → nợ tăng đúng 10.000 tiền hàng, thuế (cổng) vẫn 0
		self._ok(buoc="ban", nguoi="CHU", nhan="HL", khach="@K1", dong=[{"product_id": "@A", "unit_name": "hộp", "quantity": 2}])
		ket = sua(moi, ghi_chu="sửa lần hai")
		self.assertEqual(((ket.get("data") or {}).get("id"), no(moi)), (moi, 130000), ket)
		self.assertFalse(frappe.db.exists("Journal Entry", {"npp_phieu_nhap": moi, "docstatus": 1}))
		ket = sua(moi, gia=11000)
		self.assertEqual(((ket.get("data") or {}).get("total"), no(moi)), (140000, 140000), ket)
		self.assertEqual(self._cong_doc("KT", "purchase_invoices", "vat, total", id=moi)[0], {"vat": 0, "total": 140000})
		# lệch ÂM (nợ < giá vốn): huỷ → khôi phục → sửa nhánh A — nợ giữ 80.000
		pn2 = self._nhap("CHU", "PL2", entry_code="IN-PL-2", supplier_id="@S1", payable={"amount": 80000}, lines=dong)["data"][0]["entry_id"]
		self.assertEqual((no(pn2), frappe.db.get_value("Purchase Invoice", pn2, "npp_no_lech_gia_von")), (80000, -20000))
		self.assertEqual(self._goi("KT", "cancel_purchase_invoice", {"p_invoice_id": pn2, "p_reason": "x"}).get("data"), pn2)
		moi2 = self._goi("KT", "khoi_phuc_phieu_nhap", {"p_invoice_id": pn2})["data"]["id"]
		self.assertEqual(no(moi2), 80000)
		ket = sua(moi2)
		self.assertNotIn("error", ket, ket)
		self.assertEqual(no(ket["data"]["id"]), 80000)
		self.assertFalse(frappe.db.exists("Item Price", {"item_code": self.ma["A"], "price_list": self.cd.bang_gia_nhap}))

	def test_lo_trung_ma_luot_song_song_nhap_kho(self):
		"""Soát P4: lô cùng mã vừa được lập song song SAU bước kiểm (khác mặt hàng — khoá Bin không xếp hàng; mô phỏng: bước kiểm không thấy) → khoá
		chính báo trùng → câu LO_TRUNG_MA của màn Nhập kho, không 500 "Lỗi máy chủ…"."""
		frappe.get_doc({"doctype": "Batch", "batch_id": "L-SS", "item": self.ma["A"]}).insert(ignore_permissions=True)
		goc = frappe.db.exists
		with patch.object(frappe.db, "exists", lambda dt, *a, **k: False if dt == "Batch" else goc(dt, *a, **k)):
			ket = self._nhap(nhan="INS", entry_code="IN-S-1", lines=[{"product_id": "@A", "unit_name": "hộp", "qty_tx": 1, "conv": 1, "base_qty": 1,
				"base_cost": 1000, "batch_code": "L-SS"}])
		self.assertEqual((ket.get("error") or {}).get("message"), "LO_TRUNG_MA: Mã lô L-SS đã có trong sổ — đổi mã lô ấy rồi ghi lại phiếu nhập kho.",
			ket)

	def test_khoa_bu_hang_them_giua_hai_buoc(self):
		"""Soát P4 (PoC 1d): nháp được thêm dòng hàng KHÁC giữa bước chuẩn bị và lúc khoá (sửa nháp song song) — câu đọc mặt hàng sau khoá phiếu là đọc
		CÓ KHOÁ, nên khoá Bin bù của hàng mới đứng TRƯỚC câu đọc thường đầu tiên (đọc thường ở đó lập ảnh chụp cũ: tồn lô hàng mới đọc số cũ → lô âm)."""
		from nppsale.rpc import kho_tay as KT

		self._lo_p("L-A", 10, 8000, 200)
		self._lo_p("L-G", 5, 20000, 200, sp="@G")
		ten = self._pk("X1", "export", "sale", [("@P", "Lon", 1, 1)])
		hang = KT._hang_cua(KT.nguon_phieu(ten))  # bước chuẩn bị đọc {P}
		ket = self._cong("TK", {"bang": "stock_entry_lines", "hanh_dong": "insert", "select": "id", "gia_tri": [{"entry_id": ten,
			"product_id": self.ma["G"], "unit_name": "Kg", "quantity": 1, "qty_in_base_uom": 1, "qty_in_transaction_uom": 1, "transaction_uom": "Kg",
			"conversion_factor_snapshot": 1, "unit_cost": 0, "notes": None}]})
		self.assertNotIn("error", ket, ket)
		cau = []
		goc_sql = frappe.db.sql

		def ghi_sql(q, *a, **kw):
			cau.append(" ".join(str(q).split()))
			return goc_sql(q, *a, **kw)

		frappe.set_user(self.ma["u:TK"])
		frappe.local._npp_ngu_canh = None
		try:
			KT.hien_tai()
			frappe.local._npp_pk = (ten, hang)
			with patch.object(frappe.db, "sql", ghi_sql):
				self.assertEqual(KT.post_stock_issue(p_entry_id=ten), ten)
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None
		khoa_bin = [k for k, q in enumerate(cau) if "`tabBin`" in q and "FOR UPDATE" in q]
		self.assertGreaterEqual(len(khoa_bin), 2, cau[:5])  # khoá câu đầu {P} + khoá bù {G}
		doc = [q for q in cau[khoa_bin[0]:khoa_bin[1]] if q.startswith("SELECT") and "`tab" in q]
		self.assertTrue(doc and all("FOR UPDATE" in q or "LOCK IN SHARE MODE" in q for q in doc), doc)
		self.assertEqual(self._ton_lo("L-G", self.cd.kho_ban), 4)
