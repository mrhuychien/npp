"""Kiểm kê (P4 — M6) ngoài kịch bản vàng (đặc tả kho_mua §3.17, §3.18, §3.19 phần phiếu kiểm kê, §4.5 nguồn (2), §7.1 #1 / #11, §7.3 điểm 15 / 17;
blueprint 02 §4.4 `NPP Kiem Ke`, §4.5 `NPP Phieu Chi` / `NPP Danh Muc Chi Phi`) — cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_kiem_ke

Dựng trên bộ dữ liệu F của tệp vàng (test_kho_mua_vang.dung_nen_kho) và DÙNG LẠI các bước của bài vàng (`_buoc`: lo / pk / kk_duyet / kk_tu_choi /
huy_pk / ghi / nhap_kho) — lớp bài kế thừa lớp bài vàng nhưng bỏ bài so vàng. Phần kiểm: chứng từ lõi của lượt duyệt (hai phiếu `DCK-`: dòng, lô, kho, giá,
tài khoản, gói lô; phiếu chi hao hụt không JE; số trên phiếu; lô / kho điền vào dòng), khoá Bin là câu đầu, thứ tự kiểm (tài khoản khoá → không thấy →
đã duyệt → khác nháp → quyền), giá phần thừa = giá lô hiện tại (§7.1 #1), giá trị hao hụt luật nppsale ↔ sổ kho đúng từng lô (§7.1 #11), Batch tắt, hàng
không lô, danh mục / tài khoản, từ chối (thứ tự, ghi chú, BAD_TYPE), huỷ phiếu kho trên phiếu kiểm kê, cổng ghi / đọc phiếu + dòng kiểm kê, khoá phiếu
chi hao hụt.
"""
from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import flt, get_datetime, now_datetime, nowdate

from nppsale.luat import kiem_ke as KK
from nppsale.luat.tim import khoa_tim_ds
from nppsale.tests import test_kho_mua_vang as V
from nppsale.tests import test_xuat_hang as XH

FORBIDDEN_KHO = "FORBIDDEN: vai trò của bạn không được làm thao tác kho / mua hàng này."
RLS_PK = 'new row violates row-level security policy for table "stock_entries"'
RLS_DONG = 'new row violates row-level security policy for table "stock_entry_lines"'


def _dk(sp, sl, *, lo=None, gia=0, dv=None, ghi_chu=None) -> dict:
	"""Một dòng kiểm kê như màn /inventory/stocktake-adjust gửi (`quantity` = `qty_in_base_uom` = `qty_in_transaction_uom` = chênh có dấu)."""
	dv = dv or {"@P": "Lon", "@Q": "Chai", "@A": "hộp", "@X": "cai", "@G": "Kg"}[sp]
	return {"product_id": sp, "batch_id": lo, "unit_name": dv, "quantity": sl, "qty_in_base_uom": sl, "qty_in_transaction_uom": sl,
		"transaction_uom": dv, "conversion_factor_snapshot": 1, "unit_cost": gia, "notes": ghi_chu}


class TestKiemKe(V.TestKhoMuaVang):
	test_kich_ban_vang = None  # bài so vàng chạy ở test_kho_mua_vang

	def setUp(self):
		super().setUp()
		self.st = {"ma": "kk", "nhan": {}}

	# ------------------------------------------------------------------------------------------------ gọi
	def _ok(self, **b):
		ket, tv = self._buoc(b, self.st)
		self.assertNotIn("error", ket, f"{b['buoc']} {b.get('nhan')}: {ket.get('error')}")
		return tv

	def _loi(self, ket: dict, ma_loi: str, cau: str):
		self.assertIn("error", ket, f"mong lỗi {cau}")
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), (ma_loi, cau))

	def _nh(self, nhan: str) -> str:
		return self.st["nhan"][nhan]

	def _lo_p(self, ma: str, ton: float, gia: float, han: int | None, vung="sale", sp="@P", nhan_ngay=-30) -> str:
		return self._lo({"ma": ma, "sp": sp, "vung": vung, "ton": ton, "gia": gia, "han": han, "nhan_ngay": nhan_ngay})

	def _lo_v60(self):
		"""Lô của V60: L-A bán +200 giá 8.000 (10), L-B bán +100 giá 9.000 (5), L-C hạn +10 → kho date giá 7.000 (20), L-RONG bán +300 rỗng giá 0."""
		self._lo_p("L-A", 10, 8000, 200, nhan_ngay=-40)
		self._lo_p("L-B", 5, 9000, 100, nhan_ngay=-10)
		self._lo_p("L-C", 20, 7000, 10, nhan_ngay=-50)
		self._lo_p("L-RONG", 0, 0, 300, nhan_ngay=-1)

	def _kk(self, nhan: str, dong: list, nguoi="TK", **dau) -> str:
		self._ok(buoc="pk", nguoi=nguoi, nhan=nhan, dau={"org_id": "@org", "entry_code": nhan, "type": "stocktake", "status": "draft",
			"created_by": "@u:" + nguoi, "notes": None, **dau}, dong=dong)
		return self._nh("pk:" + nhan)

	def _duyet(self, nguoi: str, ten: str) -> dict:
		return self._goi(nguoi, "post_stock_adjustment", {"p_entry_id": ten})

	def _tu_choi(self, nguoi: str, ten: str, ly_do=None) -> dict:
		return self._goi(nguoi, "reject_stock_adjustment", {"p_entry_id": ten, "p_reason": ly_do})

	def _ton_lo(self, lo: str, kho: str) -> float:
		return flt(frappe.db.sql("""SELECT COALESCE(SUM(e.`qty`), 0) FROM `tabSerial and Batch Entry` e JOIN `tabSerial and Batch Bundle` b
			ON b.`name` = e.`parent` AND b.`docstatus` = 1 AND b.`is_cancelled` = 0 WHERE e.`is_cancelled` = 0 AND e.`batch_no` = %s
			AND e.`warehouse` = %s""", (lo, kho))[0][0])

	def _dong_se(self, se: str) -> list[tuple]:
		"""Dòng của phiếu `DCK-`: (mặt hàng, lô theo gói lô, kho, SL cơ sở, giá định giá, TK chênh lệch) theo idx."""
		ra = []
		for d in frappe.get_doc("Stock Entry", se).items:
			lo = frappe.db.get_value("Serial and Batch Entry", {"parent": d.serial_and_batch_bundle}, "batch_no") if d.serial_and_batch_bundle else None
			ra.append((d.item_code, lo, d.s_warehouse or d.t_warehouse, flt(d.transfer_qty), flt(d.valuation_rate), d.expense_account))
		return ra

	def _cong_doc(self, nguoi: str, bang: str, select="*", **loc):
		ket = self._cong(nguoi, {"bang": bang, "select": select, "loc": [{"op": "eq", "cot": c, "gt": v} for c, v in loc.items()]})
		self.assertNotIn("error", ket, ket)
		return ket["data"]

	def _quyen(self, nguoi: str, khoa: str, duoc: bool):
		frappe.get_doc({"doctype": "NPP Quyen Rieng", "nhan_vien": self.ma["u:" + nguoi], "khoa_quyen": khoa, "duoc_phep": 1 if duoc else 0}).insert(
			ignore_permissions=True)
		frappe.local._npp_ngu_canh = None

	# ------------------------------------------------------------------------------------------------ duyệt — chứng từ lõi
	def test_duyet_chung_tu_loi(self):
		"""V60 qua chứng từ: Material Issue `DCK-` (L-A 3 kho bán, L-C 6,5 kho date — TK danh mục COGS_ADJ), Material Receipt `DCK-` (L-RONG 2, giá 0 →
		allow_zero_valuation_rate, TK `tk_thua_kiem_ke`) — cả hai `dieu_chinh_kiem_ke` + `npp_kiem_ke`; NPP Phieu Chi 69.500 (ngày VN, chưa trả, danh mục
		COGS_ADJ, người lập = người duyệt, phiếu xuất), KHÔNG JE; phiếu `posted` + số + lô / kho điền vào dòng; sổ kho phần hụt đúng 69.500; cổng đọc phiếu
		(DCK- không hiện riêng) và thẻ kho (DCK- mang mã phiếu kiểm kê)."""
		self._lo_v60()
		kk = self._kk("KK60", [_dk("@P", -3, lo="@lo:L-A", gia=8000), _dk("@P", -6.5), _dk("@P", 2), _dk("@P", 0)])
		frappe.db.set_value("NPP Kiem Ke", kk, "creation", f"{frappe.utils.add_days(nowdate(), -2)} 08:00:00", update_modified=False)  # lập hai ngày trước
		ket = self._duyet("QL", kk)
		self.assertNotIn("error", ket, ket)
		pc = ket["data"][0]["expense_id"]
		self.assertEqual(ket["data"], [{"batches_touched": 3, "shrink_qty": 6.5 + 3, "shrink_value": 69500.0, "surplus_qty": 2.0, "surplus_value": 0.0,
			"expense_id": pc}])
		doc = frappe.get_doc("NPP Kiem Ke", kk)
		self.assertEqual((doc.trang_thai, doc.so_lo_cham, flt(doc.sl_hao_hut), flt(doc.gia_tri_hao_hut), flt(doc.sl_thua), flt(doc.gia_tri_thua),
			doc.phieu_chi_hao_hut), ("posted", 3, 9.5, 69500, 2, 0, pc))
		self.assertLess(abs((get_datetime(doc.duyet_luc) - now_datetime()).total_seconds()), 300)
		self.assertEqual([(d.lo, d.kho) for d in sorted(doc.dong, key=lambda d: d.idx)], [("L-A", self.cd.kho_ban), ("L-C", self.cd.kho_can_date),
			("L-RONG", self.cd.kho_ban), (None, None)])
		dm = frappe.db.get_value("NPP Danh Muc Chi Phi", {"ma": "COGS_ADJ"}, ["name", "tai_khoan"], as_dict=True)
		px, pn = doc.phieu_xuat_dc, doc.phieu_nhap_dc
		for se, muc in ((px, "Material Issue"), (pn, "Material Receipt")):
			r = frappe.db.get_value("Stock Entry", se, ["docstatus", "purpose", "npp_loai", "npp_kiem_ke", "naming_series"], as_dict=True)
			self.assertEqual((r.docstatus, r.purpose, r.npp_loai, r.npp_kiem_ke, r.naming_series), (1, muc, "dieu_chinh_kiem_ke", kk, "DCK-.####"))
		p = self.ma["P"]
		self.assertEqual(self._dong_se(px), [(p, "L-A", self.cd.kho_ban, 3, 8000, dm.tai_khoan), (p, "L-C", self.cd.kho_can_date, 6.5, 7000, dm.tai_khoan)])
		self.assertEqual(self._dong_se(pn), [(p, "L-RONG", self.cd.kho_ban, 2, 0, self.cd.tk_thua_kiem_ke)])
		self.assertEqual(frappe.db.get_value("Stock Entry Detail", {"parent": pn}, "allow_zero_valuation_rate"), 1)
		self.assertEqual(flt(frappe.db.sql("""SELECT SUM(`stock_value_difference`) FROM `tabStock Ledger Entry` WHERE `voucher_no` = %s
			AND `is_cancelled` = 0""", px)[0][0]), -69500)
		phieu = frappe.get_doc("NPP Phieu Chi", pc)
		self.assertEqual((flt(phieu.so_tien), str(phieu.ngay_chi), phieu.danh_muc, phieu.dien_giai, phieu.so_tham_chieu, phieu.nguon_loai, phieu.kiem_ke,
			phieu.da_tra, phieu.chung_tu_kho, phieu.owner), (69500, nowdate(), dm.name, f"Hao hụt từ phiếu kiểm kê {kk}", kk, "stocktake", kk, 0, px,
			self.ma["u:QL"]))
		self.assertFalse(frappe.db.exists("Journal Entry", {"npp_phieu_chi": pc}))  # chi phí đã nằm trong bút toán của phiếu xuất DCK-
		self.assertEqual((self._ton_lo("L-A", self.cd.kho_ban), self._ton_lo("L-C", self.cd.kho_can_date), self._ton_lo("L-RONG", self.cd.kho_ban)),
			(7, 13.5, 2))
		# cổng: phiếu kiểm kê (nguồn 2) — DCK- không hiện riêng; dòng mang lô đã điền; thẻ kho mang mã phiếu kiểm kê
		r = self._cong_doc("CHU", "stock_entries", select="id, entry_code, type, status, posted_at, warehouse_zone, notes, tim_kd, created_by", id=kk)[0]
		self.assertEqual((r["entry_code"], r["type"], r["status"], r["warehouse_zone"], r["tim_kd"], r["created_by"]), (kk, "stocktake", "posted", "sale",
			khoa_tim_ds(kk), self.ma["u:TK"]))
		self.assertLess(abs((V._gio(r["posted_at"]) - get_datetime(doc.duyet_luc)).total_seconds()), 1)  # `posted_at` = lúc DUYỆT (không phải lúc lập)
		self.assertEqual(self._cong_doc("CHU", "stock_entries", id=px), [])
		dong = self._cong_doc("CHU", "stock_entry_lines", select="batch_id, quantity, qty_in_base_uom, unit_cost, unit_name", entry_id=kk)
		self.assertEqual([(d["batch_id"], flt(d["quantity"]), flt(d["qty_in_base_uom"]), flt(d["unit_cost"])) for d in dong], [("L-A::sale", -3, -3,
			8000), ("L-C::date", -6.5, -6.5, 0), ("L-RONG::sale", 2, 2, 0), (None, 0, 0, 0)])
		bd = self._cong_doc("CHU", "v_stock_movements", select="entry_code, entry_type, signed_qty_in_base_uom, warehouse_zone", entry_id=kk)
		self.assertEqual(sorted((r["entry_code"], r["entry_type"], flt(r["signed_qty_in_base_uom"]), r["warehouse_zone"]) for r in bd), sorted([
			(kk, "stocktake", -3, "sale"), (kk, "stocktake", -6.5, "date"), (kk, "stocktake", 2, "sale")]))

	def test_khoa_bin_la_cau_dau(self):
		"""CFD-05 / PoC 1d: câu ĐẦU của thân hàm (sau điểm lưu của cổng) là khoá Bin `FOR UPDATE`, câu kế khoá phiếu kiểm kê `FOR UPDATE` — lượt duyệt
		thứ hai xếp hàng ở khoá rồi thấy `posted` (ALREADY_POSTED — không cộng / trừ kho hai lần)."""
		self._lo_p("L-A", 10, 8000, 200)
		kk = self._kk("K1", [_dk("@P", -1, lo="@lo:L-A")])
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
			ket = self._duyet("CHU", kk)
		self.assertNotIn("error", ket, ket)
		than = cau[moc[0]:]
		self.assertTrue("`tabBin`" in than[0] and "FOR UPDATE" in than[0], than[:1])
		self.assertTrue("`tabNPP Kiem Ke`" in than[1] and "FOR UPDATE" in than[1], than[1:2])
		lan2 = self._duyet("CHU", kk)
		self.assertTrue(lan2["error"]["message"].startswith(f"ALREADY_POSTED: phiếu {kk} đã được duyệt lúc "), lan2)
		self.assertEqual(self._ton_lo("L-A", self.cd.kho_ban), 9)

	def test_thu_tu_kiem(self):
		"""Thứ tự nppsale: tài khoản khoá (TRƯỚC khi đọc phiếu — id lạ cũng FORBIDDEN) → không thấy (chỉ nhận NPP Kiem Ke: phiếu xuất nháp → không thấy)
		→ đã duyệt (thủ kho không quyền vẫn nhận ALREADY_POSTED, giờ VN) → khác nháp (BAD_STATUS) → CUỐI CÙNG quyền `inventory.approve` (P0001): kế toán /
		thủ kho không có; quản lý bị thu quyền riêng → FORBIDDEN; kế toán được cấp quyền riêng → duyệt được."""
		self._lo_p("L-A", 10, 8000, 200)
		frappe.db.set_value("NPP Nhan Vien", self.ma["u:TK"], "dang_hoat_dong", 0)
		self._loi(self._duyet("TK", V.LA), "P0001", KK.FORBIDDEN_KHOA)
		frappe.db.set_value("NPP Nhan Vien", self.ma["u:TK"], "dang_hoat_dong", 1)
		self._loi(self._duyet("CHU", V.LA), "P0001", KK.KHONG_THAY)
		xk = self._ok(buoc="pk", nguoi="TK", nhan="X1", dau={"org_id": "@org", "entry_code": "X1", "type": "export", "warehouse_zone": "sale",
			"status": "draft"}, dong=[{**_dk("@P", 1), "quantity": 1}]) or self._nh("pk:X1")
		self._loi(self._duyet("CHU", xk), "P0001", KK.KHONG_THAY)  # ⚠K đóng lỗ V13
		kk = self._kk("K1", [_dk("@P", -1, lo="@lo:L-A")])
		self._loi(self._duyet("KT", kk), "P0001", KK.FORBIDDEN_DUYET)
		self._loi(self._duyet("TK", kk), "P0001", KK.FORBIDDEN_DUYET)
		self._quyen("QL", "inventory.approve", False)
		self._loi(self._duyet("QL", kk), "P0001", KK.FORBIDDEN_DUYET)
		self._quyen("KT", "inventory.approve", True)
		self.assertNotIn("error", self._duyet("KT", kk))
		ket = self._duyet("TK", kk)  # đã duyệt: báo trạng thái TRƯỚC quyền
		gio = get_datetime(frappe.db.get_value("NPP Kiem Ke", kk, "duyet_luc"))
		self._loi(ket, "P0001", f"ALREADY_POSTED: phiếu {kk} đã được duyệt lúc {gio:%H:%M %d/%m/%Y}")
		k2 = self._kk("K2", [_dk("@P", -1, lo="@lo:L-A")])
		self.assertEqual(self._tu_choi("CHU", k2, "x")["data"], True)
		self._loi(self._duyet("TK", k2), "P0001", f"BAD_STATUS: phiếu {k2} đang ở trạng thái cancelled, không duyệt được")

	def test_gia_phan_thua_va_gia_tri(self):
		"""§7.1 #1 / §7.3 điểm 15 (đề xuất): phần thừa vào lô có sẵn nhập theo giá vốn HIỆN TẠI của lô (8.000 — lô giữ giá như nppsale, không bình quân
		lại theo giá dòng 9.999) còn `surplus_value` theo luật nppsale (giá dòng ≠ 0 → 9.999); hụt FEFO chạm hai lô khác giá với giá dòng 0: `shrink_value`
		= SL × giá lô ĐẦU TIÊN (luật nppsale — tiền phiếu chi) còn sổ kho đúng từng lô (§7.1 #11)."""
		self._lo_p("L-A", 10, 8000, 200, nhan_ngay=-40)
		self._lo_p("L-B", 5, 9000, 100, nhan_ngay=-10)
		kk = self._kk("K1", [_dk("@P", 2, lo="@lo:L-A", gia=9999), _dk("@P", -12)])
		ket = self._duyet("CHU", kk)["data"][0]
		# hụt −12: L-B (hạn +100) 5 trước, L-A (hạn +200) 7 → giá dòng 0 → giá lô ĐẦU TIÊN 9.000
		self.assertEqual((ket["surplus_qty"], ket["surplus_value"], ket["shrink_qty"], ket["shrink_value"], ket["batches_touched"]), (2, 19998, 12,
			108000, 3))
		doc = frappe.get_doc("NPP Kiem Ke", kk)
		self.assertEqual(self._dong_se(doc.phieu_nhap_dc)[0][4], 8000)
		self.assertEqual(flt(frappe.db.sql("""SELECT SUM(`stock_value_difference`) FROM `tabStock Ledger Entry` WHERE `voucher_no` = %s
			AND `is_cancelled` = 0""", doc.phieu_xuat_dc)[0][0]), -(5 * 9000 + 7 * 8000))
		self.assertEqual(flt(frappe.db.get_value("NPP Phieu Chi", ket["expense_id"], "so_tien")), 108000)
		gia = {r["id"]: flt(r["unit_cost"]) for r in self._cong_doc("CHU", "batches", select="id, unit_cost", product_id=self.ma["P"])}
		self.assertEqual((gia["L-A::sale"], gia["L-B::sale"]), (8000, 9000))

	def test_nhap_truoc_xuat(self):
		"""nppsale cập nhật tồn ngay trong vòng dòng: dòng thừa cộng vào lô rỗng, dòng sau trừ chính lô ấy (tồn trước lượt 0) → bản Frappe ghi sổ phiếu
		nhập `DCK-` TRƯỚC phiếu xuất (ngược lại lô âm — lõi chặn)."""
		self._lo_p("L-R", 0, 0, 300, nhan_ngay=-1)
		kk = self._kk("K1", [_dk("@P", 3), _dk("@P", -2, lo="@lo:L-R")])
		ket = self._duyet("CHU", kk)
		self.assertNotIn("error", ket, ket)
		doc = frappe.get_doc("NPP Kiem Ke", kk)
		self.assertLess(get_datetime(frappe.db.get_value("Stock Entry", doc.phieu_nhap_dc, "creation")),
			get_datetime(frappe.db.get_value("Stock Entry", doc.phieu_xuat_dc, "creation")))
		self.assertEqual(self._ton_lo("L-R", self.cd.kho_ban), 1)
		# hụt 2 mà giá 0 (giá dòng 0, lô giá 0) → `shrink_value` 0 → KHÔNG phiếu chi hao hụt (nppsale `IF v_shrink_v > 0`)
		self.assertEqual((ket["data"][0]["shrink_qty"], ket["data"][0]["shrink_value"], ket["data"][0]["expense_id"]), (2, 0, None))
		self.assertFalse(frappe.db.exists("NPP Phieu Chi", {"kiem_ke": kk}))

	def test_lo_tat_va_lo_hai_kho(self):
		"""FEFO hụt lấy cả Batch TẮT (mọi trạng thái — mig 123), mở tạm trong lượt rồi tắt lại; thừa không lô vào lô hạn xa nhất có ở HAI kho → kho có tồn
		lớn nhất (đề xuất §7.3 điểm 15 — không phải kho bán mặc định)."""
		self._lo_p("L-T", 3, 5000, 20, nhan_ngay=-20)  # hạn +20 → kho date (ngưỡng 30)
		frappe.db.set_value("Batch", "L-T", "disabled", 1)
		self._lo_p("L-Y", 3, 8000, 400, nhan_ngay=-4)
		self._ok(buoc="pk", nguoi="TK", nhan="C1", dau={"org_id": "@org", "entry_code": "C1", "type": "transfer", "warehouse_zone": "sale",
			"dest_warehouse_zone": "date", "status": "draft"}, dong=[{**_dk("@P", 2), "quantity": 2}])
		self._ok(buoc="chuyen", nguoi="TK", nhan="C1")  # L-Y: kho bán 1, kho date 2
		kk = self._kk("K1", [_dk("@P", -2), _dk("@P", 4)])
		ket = self._duyet("CHU", kk)
		self.assertNotIn("error", ket, ket)
		doc = frappe.get_doc("NPP Kiem Ke", kk)
		p = self.ma["P"]
		self.assertEqual([x[:4] for x in self._dong_se(doc.phieu_xuat_dc)], [(p, "L-T", self.cd.kho_can_date, 2)])
		self.assertEqual(frappe.db.get_value("Batch", "L-T", "disabled"), 1)  # tắt lại sau lượt
		self.assertEqual([x[:4] for x in self._dong_se(doc.phieu_nhap_dc)], [(p, "L-Y", self.cd.kho_can_date, 4)])
		self.assertEqual([(d.lo, d.kho) for d in sorted(doc.dong, key=lambda d: d.idx)], [("L-T", self.cd.kho_can_date), ("L-Y", self.cd.kho_can_date)])
		self.assertEqual((self._ton_lo("L-T", self.cd.kho_can_date), self._ton_lo("L-Y", self.cd.kho_can_date), self._ton_lo("L-Y", self.cd.kho_ban)),
			(1, 6, 1))

	def test_hang_khong_lo(self):
		"""Hàng KHÔNG lô (câu 14 B — lô ảo `~<mã>::<vùng>` = Bin): dòng lô ảo trừ thẳng kho của dòng (không gói lô), không âm (kiểm kê không áp vượt tồn
		— STOCK_MOVED dù NPP cho bán vượt tồn); thừa không kho → kho bán; cổng đọc dòng ra lô ảo."""
		self._ok(buoc="nhap_kho", nguoi="TK", nhan="IN1", p={"entry_code": "IN-X-1", "warehouse_zone": "sale", "lines": [{"product_id": "@X",
			"unit_name": "cai", "qty_tx": 5, "conv": 1, "base_qty": 5, "base_cost": 1000}]})
		frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 1)
		frappe.local._npp_cai_dat_ban = None
		x = self.ma["X"]
		k1 = self._kk("K1", [_dk("@X", -6, lo=f"~{x}::sale")])
		self._loi(self._duyet("CHU", k1), "P0001", 'STOCK_MOVED: "Hàng không lô" tồn hiện 5.000000, phiếu trừ 6 — tồn đã đổi từ lúc kiểm đếm. Kiểm đếm '
			"lại rồi lập phiếu mới.")
		k2 = self._kk("K2", [_dk("@X", -2, lo=f"~{x}::sale"), _dk("@X", 3)])
		self.assertEqual([d["batch_id"] for d in self._cong_doc("CHU", "stock_entry_lines", select="batch_id", entry_id=k2)], [f"~{x}::sale", None])
		ket = self._duyet("CHU", k2)["data"][0]
		self.assertEqual((ket["batches_touched"], ket["shrink_qty"], ket["shrink_value"], ket["surplus_qty"], ket["surplus_value"]), (2, 2, 2000, 3, 3000))
		doc = frappe.get_doc("NPP Kiem Ke", k2)
		self.assertEqual([x2[:4] for x2 in self._dong_se(doc.phieu_xuat_dc)], [(x, None, self.cd.kho_ban, 2)])
		self.assertEqual([x2[:4] for x2 in self._dong_se(doc.phieu_nhap_dc)], [(x, None, self.cd.kho_ban, 3)])
		self.assertEqual(flt(frappe.db.get_value("Bin", {"item_code": x, "warehouse": self.cd.kho_ban}, "actual_qty")), 6)
		self.assertEqual([d["batch_id"] for d in self._cong_doc("CHU", "stock_entry_lines", select="batch_id", entry_id=k2)], [f"~{x}::sale",
			f"~{x}::sale"])

	def test_danh_muc_va_tai_khoan(self):
		"""Danh mục hao hụt: COGS_ADJ → (không có) danh mục đầu theo mã — TK của danh mục, trống → `tk_chi_phi_mac_dinh`; thiếu cả hai → CAI_DAT_THIEU;
		thừa mà thiếu `tk_thua_kiem_ke` → CAI_DAT_THIEU (phiếu giữ nháp, kho không đổi)."""
		self._lo_p("L-A", 10, 8000, 200)
		frappe.db.set_value("NPP Danh Muc Chi Phi", frappe.db.get_value("NPP Danh Muc Chi Phi", {"ma": "COGS_ADJ"}), "ma", "ZZ_COGS")
		for ma in ("AAA", "AAB"):
			if not frappe.db.exists("NPP Danh Muc Chi Phi", {"ma": ma}):
				frappe.get_doc({"doctype": "NPP Danh Muc Chi Phi", "ma": ma, "ten": ma, "nhom": "other"}).insert(ignore_permissions=True)
		dau = frappe.get_all("NPP Danh Muc Chi Phi", fields=["name", "tai_khoan"], order_by="ma asc", limit=1)[0]
		frappe.db.set_value("NPP Danh Muc Chi Phi", dau.name, "tai_khoan", None)
		k1 = self._kk("K1", [_dk("@P", -1, lo="@lo:L-A")])
		ket = self._duyet("CHU", k1)["data"][0]
		doc = frappe.get_doc("NPP Kiem Ke", k1)
		self.assertEqual(frappe.db.get_value("NPP Phieu Chi", ket["expense_id"], "danh_muc"), dau.name)
		self.assertEqual(self._dong_se(doc.phieu_xuat_dc)[0][5], self.cd.tk_chi_phi_mac_dinh)
		frappe.db.set_single_value("NPP Cai Dat", {"tk_chi_phi_mac_dinh": None, "tk_thua_kiem_ke": None})
		frappe.local._npp_cai_dat_ban = None
		k2 = self._kk("K2", [_dk("@P", -1, lo="@lo:L-A")])
		self.assertTrue(self._duyet("CHU", k2)["error"]["message"].startswith("CAI_DAT_THIEU: danh mục chi phí COGS_ADJ chưa gắn tài khoản"))
		k3 = self._kk("K3", [_dk("@P", 1, lo="@lo:L-A")])
		self._loi(self._duyet("CHU", k3), "P0001", "CAI_DAT_THIEU: NPP Cai Dat chưa có tài khoản thừa kiểm kê (tk_thua_kiem_ke).")
		self.assertEqual((frappe.db.get_value("NPP Kiem Ke", k3, "trang_thai"), self._ton_lo("L-A", self.cd.kho_ban)), ("draft", 9))

	# ------------------------------------------------------------------------------------------------ từ chối / huỷ
	def test_tu_choi(self):
		"""reject_stock_adjustment: không đâu có → `ENTRY_NOT_FOUND.`; tài khoản khoá → `ORG_MISMATCH.` 42501; thủ kho (không `inventory.approve`) →
		FORBIDDEN 42501; phiếu kho khác loại → BAD_TYPE SAU kiểm quyền; ghi chú nối sau ghi chú cũ; đã huỷ → false (ghi chú giữ); đã duyệt →
		ALREADY_POSTED."""
		self._lo_p("L-A", 10, 8000, 200)
		self._loi(self._tu_choi("QL", V.LA), "P0001", KK.KHONG_THAY_TU_CHOI)
		kk = self._kk("K1", [_dk("@P", -1, lo="@lo:L-A")], notes="dem tay")
		frappe.db.set_value("NPP Nhan Vien", self.ma["u:QL"], "dang_hoat_dong", 0)
		self._loi(self._tu_choi("QL", kk), "42501", KK.KHAC_NPP_TU_CHOI)
		frappe.db.set_value("NPP Nhan Vien", self.ma["u:QL"], "dang_hoat_dong", 1)
		self._loi(self._tu_choi("TK", kk), "42501", KK.FORBIDDEN_TU_CHOI)
		self._ok(buoc="pk", nguoi="TK", nhan="X1", dau={"org_id": "@org", "entry_code": "X1", "type": "export", "warehouse_zone": "sale",
			"status": "draft"}, dong=[{**_dk("@P", 1), "quantity": 1}])
		self._loi(self._tu_choi("TK", self._nh("pk:X1")), "42501", KK.FORBIDDEN_TU_CHOI)  # quyền trước loại
		self._loi(self._tu_choi("QL", self._nh("pk:X1")), "P0001", KK.SAI_LOAI)
		self.assertEqual(self._tu_choi("QL", kk, "")["data"], True)
		self.assertEqual(frappe.db.get_value("NPP Kiem Ke", kk, ["trang_thai", "ghi_chu"]), ("cancelled", "dem tay\nTừ chối: (không ghi lý do)"))
		r = self._cong_doc("CHU", "stock_entries", select="status, posted_at, notes", id=kk)[0]
		self.assertEqual((r["status"], r["posted_at"], r["notes"]), ("cancelled", None, "dem tay\nTừ chối: (không ghi lý do)"))
		self.assertEqual(self._tu_choi("QL", kk, "lan 2")["data"], False)
		self.assertEqual(frappe.db.get_value("NPP Kiem Ke", kk, "ghi_chu"), "dem tay\nTừ chối: (không ghi lý do)")
		k2 = self._kk("K2", [_dk("@P", -1, lo="@lo:L-A")])
		self.assertNotIn("error", self._duyet("CHU", k2))
		self._loi(self._tu_choi("CHU", k2, "x"), "P0001", KK.DA_DUYET_TU_CHOI)

	def test_huy_phieu_kho_kiem_ke(self):
		"""cancel_stock_entry trên phiếu kiểm kê: vai owner / warehouse (quản lý → FORBIDDEN, trước trạng thái); nháp → `cancelled` + "Huỷ phiếu: <lý do>"
		(giữ phiếu — khác Stock Entry nháp: xoá) `[true, false, 0]`; lần hai `[true, false, 0]`; đã duyệt → CANNOT_REVERSE_TYPE (stocktake)."""
		self._lo_p("L-A", 10, 8000, 200)
		kk = self._kk("K1", [_dk("@P", -1, lo="@lo:L-A")], notes="dem tay")
		self._loi(self._goi("QL", "cancel_stock_entry", {"p_entry_id": kk, "p_reason": "x"}), "42501", FORBIDDEN_KHO)
		huy = lambda ten, ly_do: self._goi("TK", "cancel_stock_entry", {"p_entry_id": ten, "p_reason": ly_do})  # noqa: E731
		self.assertEqual(huy(kk, "nham")["data"], [{"cancelled": True, "reversed": False, "lines_reversed": 0}])
		self.assertEqual(frappe.db.get_value("NPP Kiem Ke", kk, ["trang_thai", "ghi_chu"]), ("cancelled", "dem tay\nHuỷ phiếu: nham"))
		self.assertEqual(huy(kk, "lan 2")["data"], [{"cancelled": True, "reversed": False, "lines_reversed": 0}])
		self.assertEqual(frappe.db.get_value("NPP Kiem Ke", kk, "ghi_chu"), "dem tay\nHuỷ phiếu: nham")
		self.assertEqual(self._ton_lo("L-A", self.cd.kho_ban), 10)  # nháp — kho không đổi
		k2 = self._kk("K2", [_dk("@P", -1, lo="@lo:L-A")])
		self.assertNotIn("error", self._duyet("CHU", k2))
		self._loi(huy(k2, "x"), "P0001", f"CANNOT_REVERSE_TYPE: phiếu {k2} (stocktake) đã ghi sổ nhưng chưa có đường hoàn kho cho loại phiếu này. Dùng "
			"phiếu điều chỉnh để sửa tồn.")
		self._loi(self._goi("TK", "post_stock_issue", {"p_entry_id": k2}), "P0001", "SAI_LOAI_PHIEU: Phiếu này không phải phiếu xuất kho.")

	# ------------------------------------------------------------------------------------------------ cổng ghi / đọc
	def test_cong_ghi_phieu_kiem_ke(self):
		"""Ghi thẳng phiếu kiểm kê nháp (trigger mig 170 + RLS owner / warehouse): lập (kho theo vùng, mã trình duyệt bị thay, khoá tìm), dòng (chênh có dấu,
		dòng 0 được, lô thật / lô ảo / lô không có → 23503, thiếu cột NOT NULL → 23502, cột lạ → PGRST204, NVBH → 42501), sửa / xoá dòng nháp, sửa đầu
		nháp, đổi trạng thái (chỉ draft → cancelled: giữ phiếu, ghi chú không đổi), phiếu đã duyệt chỉ sửa ghi chú, xoá chỉ nháp (không lùi dãy số)."""
		self._lo_p("L-A", 10, 8000, 200)
		ins = lambda g, nguoi="TK": self._cong(nguoi, {"bang": "stock_entries", "hanh_dong": "insert", "select": "id",  # noqa: E731
			"gia_tri": {"org_id": self.ma["org"], "type": "stocktake", "status": "draft", **g}})
		self.assertEqual(ins({}, "NV")["error"]["message"], RLS_PK)
		self.assertEqual(ins({"status": "posted"})["error"]["message"], "SO_KHO_KHOA: phiếu kho lập từ màn hình phải là phiếu NHÁP — ghi sổ đi qua nút "
			"Duyệt / Hoàn thành.")
		self.assertEqual(ins({"warehouse_zone": "x"})["error"]["code"], "23514")
		self.assertEqual(ins({"cot_la": 1})["error"]["code"], "PGRST204")
		kk = ins({"entry_code": "KK2611179999", "warehouse_zone": "date", "notes": "dem cuoi ngay", "posted_at": None})["data"][0]["id"]
		self.assertTrue(kk.startswith("KK-"), kk)
		self.assertEqual(frappe.db.get_value("NPP Kiem Ke", kk, ["trang_thai", "kho", "ghi_chu", "tim_kd"]), ("draft", self.cd.kho_can_date,
			"dem cuoi ngay", khoa_tim_ds(kk)))
		self.assertEqual(self._cong_doc("TK", "stock_entries", select="warehouse_zone, status", id=kk), [{"warehouse_zone": "date", "status": "draft"}])
		them = lambda ds, nguoi="TK": self._cong(nguoi, {"bang": "stock_entry_lines", "hanh_dong": "insert", "select": "id",  # noqa: E731
			"gia_tri": [{"entry_id": kk, **self._thay(g, self.st)} for g in ds]})
		self.assertEqual(them([_dk("@P", -1)], "NV")["error"]["message"], RLS_DONG)
		self.assertEqual(them([_dk("@P", -1, lo="L-KHONG::sale")])["error"]["message"], 'insert or update on table "stock_entry_lines" violates foreign '
			'key constraint "stock_entry_lines_batch_id_fkey"')
		self.assertEqual(them([_dk("@P", -1, lo=f"~{self.ma['P']}::sale")])["error"]["code"], "23503")  # P theo lô → không có lô ảo
		self.assertEqual(them([{k: v for k, v in _dk("@P", -1).items() if k != "quantity"}])["error"]["message"], 'null value in column "quantity" of '
			'relation "stock_entry_lines" violates not-null constraint')
		self.assertEqual(them([{**_dk("@P", -1), "unit_cost": None}])["error"]["code"], "23502")
		self.assertEqual(them([{**_dk("@P", -1), "la": 1}])["error"]["code"], "PGRST204")
		ket = them([_dk("@P", -2, lo="@lo:L-A", gia=8000), _dk("@P", 0), _dk("@P", 1.5, ghi_chu="thua")])
		self.assertEqual(len(ket["data"]), 3)
		dong = frappe.get_doc("NPP Kiem Ke", kk).dong
		self.assertEqual([(d.mat_hang, d.lo, d.kho, flt(d.chenh_lech), flt(d.gia_von), d.ghi_chu) for d in dong], [(self.ma["P"], "L-A",
			self.cd.kho_ban, -2, 8000, None), (self.ma["P"], None, None, 0, 0, None), (self.ma["P"], None, None, 1.5, 0, "thua")])
		ids = [r["id"] for r in ket["data"]]
		ket = self._cong("TK", {"bang": "stock_entry_lines", "hanh_dong": "update", "select": "id", "gia_tri": {"quantity": -3, "qty_in_base_uom": -3},
			"loc": [{"op": "eq", "cot": "id", "gt": ids[0]}]})
		self.assertEqual(len(ket["data"]), 1)
		ket = self._cong("TK", {"bang": "stock_entry_lines", "hanh_dong": "delete", "select": "id", "loc": [{"op": "eq", "cot": "id", "gt": ids[1]}]})
		self.assertEqual(len(ket["data"]), 1)
		self.assertEqual([flt(d.chenh_lech) for d in frappe.get_doc("NPP Kiem Ke", kk).dong], [-3, 1.5])
		sua = lambda g, nguoi="TK", ten=kk: self._cong(nguoi, {"bang": "stock_entries", "hanh_dong": "update", "select": "id",  # noqa: E731
			"gia_tri": g, "loc": [{"op": "eq", "cot": "id", "gt": ten}]})
		self.assertEqual(sua({"warehouse_zone": "sale"})["data"], [{"id": kk}])
		self.assertEqual(frappe.db.get_value("NPP Kiem Ke", kk, "kho"), self.cd.kho_ban)
		self.assertEqual(sua({"notes": "x"}, "QL")["data"], [])  # RLS: quản lý → 0 dòng
		self.assertEqual(sua({"status": "posted"})["error"]["message"], "SO_KHO_KHOA: không đổi thẳng trạng thái phiếu kho (draft → posted) — ghi sổ / "
			"huỷ đi qua nút Duyệt / Huỷ phiếu để kho đổi theo.")
		self.assertEqual(sua({"type": "export"})["error"]["message"], "SO_KHO_KHOA: phiếu đã ghi sổ chỉ sửa được ghi chú.")
		# đã duyệt: chỉ ghi chú; dòng khoá; xoá khoá
		self.assertNotIn("error", self._duyet("CHU", kk))
		self.assertEqual(sua({"notes": "sua sau duyet"})["data"], [{"id": kk}])
		self.assertEqual(frappe.db.get_value("NPP Kiem Ke", kk, "ghi_chu"), "sua sau duyet")
		self.assertEqual(sua({"warehouse_zone": "date"})["error"]["message"], "SO_KHO_KHOA: phiếu đã ghi sổ chỉ sửa được ghi chú.")
		self.assertEqual(sua({"notes": "sua lan 2", "warehouse_zone": "sale", "type": "stocktake"})["data"], [{"id": kk}])  # giá trị không đổi → được
		self.assertEqual(frappe.db.get_value("NPP Kiem Ke", kk, "ghi_chu"), "sua lan 2")
		self.assertEqual(them([_dk("@P", 1)])["error"]["message"], "SO_KHO_KHOA: phiếu đã ghi sổ — không sửa dòng hàng được nữa.")
		ket = self._cong("TK", {"bang": "stock_entries", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "id", "gt": kk}]})
		self.assertEqual(ket["error"]["message"], f"SO_KHO_KHOA: chỉ xoá được phiếu NHÁP. Phiếu {kk} đã ghi sổ, dùng Huỷ phiếu để hàng về lại kho.")
		# nháp → cancelled qua cổng: giữ phiếu, ghi chú không đổi; xoá nháp (màn dọn khi chèn dòng hỏng) không lùi dãy số
		k2 = ins({"notes": "n"})["data"][0]["id"]
		self.assertEqual(sua({"status": "cancelled", "type": "export"}, ten=k2)["error"]["message"], "SO_KHO_KHOA: phiếu đã ghi sổ chỉ sửa được ghi "
			"chú.")  # trigger: đổi loại bị chặn cả khi cùng lệnh huỷ nháp
		self.assertEqual(frappe.db.get_value("NPP Kiem Ke", k2, "trang_thai"), "draft")
		self.assertEqual(sua({"status": "cancelled"}, ten=k2)["data"], [{"id": k2}])
		self.assertEqual(frappe.db.get_value("NPP Kiem Ke", k2, ["trang_thai", "ghi_chu"]), ("cancelled", "n"))
		k3 = ins({})["data"][0]["id"]
		ket = self._cong("TK", {"bang": "stock_entries", "hanh_dong": "delete", "select": "*", "loc": [{"op": "eq", "cot": "id", "gt": k3},
			{"op": "eq", "cot": "status", "gt": "draft"}]})
		self.assertEqual([r["id"] for r in ket["data"]], [k3])
		self.assertFalse(frappe.db.exists("NPP Kiem Ke", k3))
		self.assertNotEqual(ins({})["data"][0]["id"], k3)

	def test_cong_doc_man_duyet(self):
		"""Câu của màn /inventory/adjustments: phiếu `stocktake` `draft` kèm người lập + dòng + sản phẩm + lô (`batch:batches(batch_code, qty_on_hand)`);
		mọi NV đọc được (RLS mig 002) nhưng giá vốn dòng che với người thiếu `inventory.cost` (NVBH)."""
		self._lo_p("L-A", 10, 8000, 200)
		kk = self._kk("K1", [_dk("@P", -1, lo="@lo:L-A", gia=8000), _dk("@P", 2)])
		chon = ("id, entry_code, status, notes, posted_at, created_at, creator:users!stock_entries_created_by_fkey(full_name), "
			"lines:stock_entry_lines(*, product:products(name, sku, base_unit), batch:batches(batch_code, qty_on_hand))")
		r = next(x for x in self._cong_doc("CHU", "stock_entries", select=chon, type="stocktake", status="draft") if x["id"] == kk)
		self.assertEqual((r["entry_code"], r["status"], r["posted_at"], r["creator"]["full_name"]), (kk, "draft", None, "TK"))
		self.assertEqual([(d["product"]["name"], (d["batch"] or {}).get("batch_code"), flt((d["batch"] or {}).get("qty_on_hand")), flt(d["quantity"]),
			flt(d["unit_cost"])) for d in r["lines"]], [("Nuoc ngot", "L-A", 10, -1, 8000), ("Nuoc ngot", None, 0, 2, 0)])
		nv = next(x for x in self._cong_doc("NV", "stock_entries", select="id, lines:stock_entry_lines(unit_cost)", type="stocktake") if x["id"] == kk)
		self.assertEqual([d["unit_cost"] for d in nv["lines"]], [None, None])

	def test_phieu_chi_hao_hut_khoa(self):
		"""BP §7.1 điểm 18 (đề xuất — Q9): phiếu chi nguồn kiểm kê chỉ sửa diễn giải / số tham chiếu; đổi tiền / danh mục / ngày → PHIEU_CHI_KIEM_KE_KHOA;
		không xoá được."""
		self._lo_p("L-A", 10, 8000, 200)
		kk = self._kk("K1", [_dk("@P", -1, lo="@lo:L-A")])
		pc = self._duyet("CHU", kk)["data"][0]["expense_id"]
		doc = frappe.get_doc("NPP Phieu Chi", pc)
		doc.dien_giai = "Hao hụt do vỡ"
		doc.save(ignore_permissions=True)
		for truong, gt in (("so_tien", 1), ("ngay_chi", "2026-01-01"), ("kiem_ke", None)):
			doc = frappe.get_doc("NPP Phieu Chi", pc)
			doc.set(truong, gt)
			with self.assertRaises(frappe.ValidationError) as e:
				doc.save(ignore_permissions=True)
			self.assertEqual(str(e.exception), KK.loi_phieu_chi_khoa(kk), truong)
		with self.assertRaises(frappe.ValidationError) as e:
			frappe.delete_doc("NPP Phieu Chi", pc, ignore_permissions=True)
		self.assertEqual(str(e.exception), KK.loi_phieu_chi_khong_xoa(kk))
		self.assertEqual(frappe.db.get_value("NPP Phieu Chi", pc, ["dien_giai", "so_tien"]), ("Hao hụt do vỡ", 8000))

	def test_cai_dat(self):
		"""Cài đặt site (thiet_lap.kho_mua.dam_bao — Q9): `tk_thua_kiem_ke` = "Thua kiem ke" dưới thu nhập khác; `tk_chi_phi_mac_dinh` = chi phí khác;
		tám danh mục mig 016 có đủ, COGS_ADJ gắn TK giá vốn hàng bán; bộ kiểm cài đặt không báo lệch kiểm kê."""
		from nppsale.thiet_lap.kho_mua import DANH_MUC_CHI_PHI, kiem

		cty = frappe.get_cached_doc("Company", self.cd.cong_ty)
		self.assertEqual((self.cd.tk_thua_kiem_ke, frappe.db.get_value("Account", self.cd.tk_thua_kiem_ke, "root_type")), (f"Thua kiem ke - {cty.abbr}",
			"Income"))
		self.assertEqual(self.cd.tk_chi_phi_mac_dinh, f"Miscellaneous Expenses - {cty.abbr}")
		self.assertEqual({ma for ma, *_ in DANH_MUC_CHI_PHI} - set(frappe.get_all("NPP Danh Muc Chi Phi", pluck="ma")), set())
		self.assertEqual(frappe.db.get_value("NPP Danh Muc Chi Phi", {"ma": "COGS_ADJ"}, ["nhom", "tai_khoan"]), ("cogs", cty.default_expense_account))
		self.assertEqual([x for x in kiem() if "kiem" in str(x).lower() or x["doi_tuong"] == "NPP Danh Muc Chi Phi"], [])
		# gieo MỘT lần (bảng rỗng): đủ tám mã, COGS_ADJ gắn TK giá vốn; bảng đã có dòng → không gieo lại (danh mục người dùng xoá không tự hiện lại)
		from nppsale.thiet_lap.ban_hang import cai_dat_ban
		from nppsale.thiet_lap.kho_mua import _gieo_danh_muc_chi_phi

		frappe.db.delete("NPP Danh Muc Chi Phi")
		_gieo_danh_muc_chi_phi(cai_dat_ban())
		self.assertEqual(sorted(frappe.get_all("NPP Danh Muc Chi Phi", pluck="ma")), sorted(ma for ma, *_ in DANH_MUC_CHI_PHI))
		self.assertEqual(frappe.db.get_value("NPP Danh Muc Chi Phi", {"ma": "COGS_ADJ"}, ["nhom", "tai_khoan"]), ("cogs", cty.default_expense_account))
		self.assertEqual(frappe.db.get_value("NPP Danh Muc Chi Phi", {"ma": "RENT"}, ["ten", "nhom", "tai_khoan"]), ("Tiền thuê mặt bằng", "operating",
			None))
		frappe.db.delete("NPP Danh Muc Chi Phi", {"ma": "RENT"})
		_gieo_danh_muc_chi_phi(cai_dat_ban())
		self.assertEqual(frappe.db.count("NPP Danh Muc Chi Phi"), len(DANH_MUC_CHI_PHI) - 1)
		self.assertLess(abs((XH.hom_nay() - frappe.utils.getdate(nowdate())).days), 1)
