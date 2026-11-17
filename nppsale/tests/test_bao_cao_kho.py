"""Báo cáo kho + luồng cũ + RPC đọc kho với chứng từ P4 + khám sổ P4 (P4 — M9; đặc tả kho_mua §3.21, §5.4, §5.5, §6.9 V74, §8.1) — cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_bao_cao_kho

Dựng trên bộ dữ liệu F của tệp vàng (test_kho_mua_vang.dung_nen_kho) và DÙNG LẠI các bước của bài vàng (`_buoc`: lo / ban / huy_hd / nhap_kho / pn /
pn_hoan / pn_huy / ptn / ptn_gui / pk / xuat_le / chuyen / kk_duyet / nguong / ra_soat / chi…) như nppsale.tests.test_kho_tay. Phần kiểm:
- `bao_cao_ton_kho` (§5.4): tập lô còn hàng theo id cổng `<lô>::<vùng>` (lô ảo hàng không lô, hạn trống → 2099-12-31), sắp `id`, che giá vốn theo
  `inventory.cost`, dòng HĐ ghi sổ trong kỳ (gồm dòng hàng đổi; bỏ HĐ huỷ / ngoài kỳ), vế đọc HĐ của người gọi, đầu kỳ NULL / ngược / sai kiểu, người
  ngoài NPP;
- `post_stock_export` (§3.21): luôn LEGACY_FLOW_REMOVED, không đổi gì;
- RPC đọc kho đã có (§5.5 — `ton_ban_theo_hang`, `stock_value_summary`, `ton_kho_trang`) sau từng loại chứng từ P4 (PN, PTNCC, IN-, XKL-, CKL-,
  CKL- tự động, DCK-): khớp nguồn lô cổng `batches` + số tay; lô rỗng ở `npp_kho_tao`, lô hết tồn còn dòng;
- giá vốn kỳ đọc cổng (§5.7 — soát thiếu S1, §10): phiếu `export` ghi sổ trong kỳ = HĐ + trả NCC (giá lô) + xuất lẻ (0); không HĐ huỷ / chuyển kho /
  kiểm kê; giá vốn hàng trả theo ghi chú "Nhập lại từ phiếu trả <phiếu>";
- giá vốn V74 (§6.9, §7.1): giá vốn HĐ 250.000, trả NCC giảm kho 45.000 (giá lô) + chênh 5.000 vào TK chi phí mặc định, giá lô L2 KHÔNG bình quân lại
  sau thừa kiểm kê / nhập lại hàng trả;
- khám sổ P4 (§8.1 — nppsale.kham_so.quet_kho_mua): sổ do method lập thì sạch; bắt từng nhóm 27–32 trên sổ làm lệch; thống kê theo dòng nppsale; việc đêm
  nối sau khám sổ công nợ NCC (Error Log khi có dòng cần xem).
"""
from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, get_datetime

from nppsale.cong import api
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.truy_van import doc as doc_cong
from nppsale.kham_so import quet_kho_mua
from nppsale.tests import test_kho_mua_vang as V
from nppsale.tests import test_xuat_hang as XH

LEGACY = ("P0001", "LEGACY_FLOW_REMOVED: chức năng đã gỡ")


class TestBaoCaoKho(V.TestKhoMuaVang):
	test_kich_ban_vang = None  # bài so vàng chạy ở test_kho_mua_vang

	def setUp(self):
		super().setUp()
		self.st = {"ma": "bck", "nhan": {}}

	# ------------------------------------------------------------------------------------------------ gọi
	def _ok(self, **b):
		ket, tv = self._buoc(b, self.st)
		self.assertNotIn("error", ket, f"{b['buoc']} {b.get('nhan')}: {ket.get('error')}")
		return tv

	def _nh(self, nhan: str) -> str:
		return self.st["nhan"][nhan]

	def _hom_nay(self, n: int = 0) -> str:
		return str(add_days(XH.hom_nay(), n))

	def _bc(self, nguoi: str, tu=None, den=None) -> dict:
		ket = self._goi(nguoi, "bao_cao_ton_kho", {"p_tu": tu, "p_den": den})
		self.assertNotIn("error", ket, ket)
		return ket["data"]

	def _cua_bai(self, bc: dict) -> tuple[list, list]:
		"""Phần của bài trong kết quả (site có lô / HĐ dựng thử cũ): lô theo mã lô của bài + lô ảo của X; dòng của HĐ có nhãn."""
		hd = {v: k[3:] for k, v in self.st["nhan"].items() if k.startswith("hd:")}
		lo = [(r["id"], r["product_id"], r["batch_code"], flt(r["qty_on_hand"]), r["unit_cost"], r["expires_at"]) for r in bc["lo"]
			if r["id"].rpartition("::")[0] not in self.co_san["Batch"] and r["product_id"] in (self.ma["P"], self.ma["X"])]
		dong = sorted((hd[r["invoice_id"]], r["ngay"], r["product_id"], r["unit_name"], flt(r["conversion_factor"]), flt(r["quantity"]),
			r["is_exchange"]) for r in bc["dong"] if r["invoice_id"] in hd)
		return sorted(lo), dong

	def _ban_nv(self, nguoi: str, nhan: str, sl: float, sp: str = "@P", dv: str = "Lon") -> str:
		"""Đơn do `nguoi` lập (NVBH → đơn đứng tên NV) rồi CHỦ xuất hàng (NVBH không có `orders.approve`) — như bước `ban` của bài vàng."""
		import uuid

		gia = 10000
		p = {"client_request_id": str(uuid.uuid4()), "order": {"order_code": "TAM-1", "customer_id": self.ma["K1"], "payment_terms": "COD",
			"expected_delivery": None, "subtotal": sl * gia, "vat": 0, "total": sl * gia, "notes": None, "status": "submitted",
			"approval_reason": None, "sales_user_id": None}, "lines": [{"product_id": self.ma[sp[1:]], "unit_name": dv, "quantity": sl,
			"unit_price": gia, "line_discount": 0, "conversion_factor": 1, "vat_rate": 0, "line_total": sl * gia}], "returns": None, "return_lines": []}
		ket = self._goi(nguoi, "create_order_with_lines", {"p": p})
		self.assertNotIn("error", ket, ket)
		don = ket["data"][0]["order_id"]
		dd = frappe.get_all("Sales Order Item", filters={"parent": don}, fields=["name", "item_code", "uom", "conversion_factor", "qty", "rate",
			"npp_giam_dong", "npp_thue_suat"], order_by="idx asc")
		ket = self._goi("CHU", "post_invoice", {"p": {"order_id": don, "lines": [{"order_line_id": r.name, "product_id": r.item_code,
			"unit_name": r.uom, "conversion_factor": r.conversion_factor, "quantity": r.qty, "unit_price": r.rate, "line_discount": r.npp_giam_dong,
			"vat_rate": r.npp_thue_suat, "is_exchange": False} for r in dd]}})
		self.assertNotIn("error", ket, ket)
		self.st["nhan"]["hd:" + nhan] = ket["data"][0]["invoice_id"]
		return self.st["nhan"]["hd:" + nhan]

	def _ton_lo(self, ma: str, vung: str = "sale") -> float:
		ds = doc_cong({"bang": "batches", "select": "qty_on_hand", "loc": [{"op": "eq", "cot": "id", "gt": f"{ma}::{vung}"}]},
			NguCanh(user="Administrator", vai=None, bo_qua_rls=True))["data"]
		return flt(ds[0]["qty_on_hand"]) if ds else None

	# ------------------------------------------------------------------------------------------------ bao_cao_ton_kho (§5.4)
	def test_bao_cao_ton_kho(self):
		p, x = self.ma["P"], self.ma["X"]
		for b in ({"ma": "BC-A", "ton": 10, "gia": 8000, "han": 200, "nhan_ngay": -40}, {"ma": "BC-B", "ton": 5, "gia": 9000, "han": 100,
				"nhan_ngay": -10}, {"ma": "BC-C", "ton": 20, "gia": 7000, "han": 10, "nhan_ngay": -50}, {"ma": "BC-R", "ton": 0, "gia": 0, "han": 300,
				"nhan_ngay": -1}, {"ma": "BC-H", "nhap": 3, "ton": 0, "gia": 5000, "han": 150, "nhan_ngay": -20}):
			self._lo({"sp": "@P", "vung": "sale", "tao_ngay": b["nhan_ngay"], **b})
		self._ok(buoc="nhap_kho", nguoi="TK", nhan="IX", p={"entry_code": "IN-BC-1", "warehouse_zone": "sale", "lines": [{"product_id": "@X",
			"unit_name": "cai", "qty_tx": 7, "conv": 1, "base_qty": 7, "base_cost": 3000}]})
		h1 = self._ban_nv("CHU", "H1", 2)
		h2 = self._ban_nv("NV", "H2", 1)
		frappe.db.set_value("Sales Invoice Item", {"parent": h2}, "npp_hang_doi", 1, update_modified=False)  # dòng hàng đổi — màn tự bỏ
		h3 = self._ban_nv("CHU", "H3", 1)
		frappe.db.set_value("Sales Invoice", h3, "posting_date", self._hom_nay(-100), update_modified=False)  # ngoài kỳ 90 ngày
		self._ban_nv("CHU", "H4", 1)
		self._ok(buoc="huy_hd", nguoi="CHU", nhan="H4", ly_do="sai")  # HĐ huỷ — không vào `dong`
		self.assertEqual(self._ton_lo("BC-A"), 6)  # FIFO ngày nhận kho bán: BC-A (−40) trước BC-B (−10); BC-C ở kho cận date

		tu, den = self._hom_nay(-89), self._hom_nay()
		bc = self._bc("CHU", tu, den)
		from nppsale.cong.bang.kho import NGUON_LO

		self.assertEqual([r["id"] for r in bc["lo"]], [r[0] for r in frappe.db.sql(f"SELECT x.`name` FROM {NGUON_LO} x WHERE x.`ton` > 0 "
			"ORDER BY x.`name`")], "lo = mọi dòng lô còn hàng, sắp theo id (collation của sổ)")
		self.assertTrue(all(flt(r["qty_on_hand"]) > 0 for r in bc["lo"]))
		self.assertEqual(set(bc["lo"][0]), {"id", "product_id", "batch_code", "qty_on_hand", "unit_cost", "expires_at", "created_at"})
		lo, dong = self._cua_bai(bc)
		self.assertEqual(lo, sorted([("BC-A::sale", p, "BC-A", 6.0, 8000, self._hom_nay(200)), ("BC-B::sale", p, "BC-B", 5.0, 9000, self._hom_nay(100)),
			("BC-C::date", p, "BC-C", 20.0, 7000, self._hom_nay(10)), (f"~{x}::sale", x, "—", flt(self._bin_x()), 3000, "2099-12-31")]))
		self.assertEqual(get_datetime(next(r["created_at"] for r in bc["lo"] if r["id"] == "BC-A::sale")).strftime("%Y-%m-%d %H:%M"),
			f"{self._hom_nay(-40)} 08:00")
		hom_nay = self._hom_nay()
		self.assertEqual(dong, [("H1", hom_nay, p, "Lon", 1.0, 2.0, False), ("H2", hom_nay, p, "Lon", 1.0, 1.0, True)])
		self.assertEqual(set(bc["dong"][0]), {"ngay", "invoice_id", "product_id", "unit_name", "conversion_factor", "quantity", "is_exchange"})
		self.assertEqual([r[0] for r in self._cua_bai(self._bc("CHU", self._hom_nay(-120), den))[1]], ["H1", "H2", "H3"])  # kỳ dài hơn → có H3
		self.assertEqual(self._cua_bai(self._bc("CHU", den, den))[1], dong)  # đầu kỳ = cuối kỳ (BETWEEN gồm hai đầu)
		# NVBH: cùng tập lô, giá vốn che (❓ §7.3 điểm 21); dòng chỉ HĐ mình đọc được (vế đọc sales_invoices — đơn / HĐ đứng tên NV)
		lo_nv, dong_nv = self._cua_bai(self._bc("NV", tu, den))
		self.assertEqual(lo_nv, [(a, b, c, d, None, f) for a, b, c, d, _e, f in lo])
		self.assertEqual([r[0] for r in dong_nv], ["H2"])
		# thủ kho / kế toán thấy mọi HĐ (vai xem HĐ — mig 124)
		self.assertEqual([r[0] for r in self._cua_bai(self._bc("TK", tu, den))[1]], ["H1", "H2"])
		# đầu kỳ NULL / ngược → `dong` rỗng (BETWEEN NULL / BETWEEN ngược của Postgres); `lo` không phụ thuộc kỳ
		for a, b in ((None, den), (tu, None), (None, None), (den, tu)):
			kq = self._bc("CHU", a, b)
			self.assertEqual((self._cua_bai(kq)[1], len(kq["lo"])), ([], len(bc["lo"])), (a, b))
		# ép kiểu `date` như Postgres
		for v, ma, cau in (("abc", "22007", 'invalid input syntax for type date: "abc"'), ("2026-13-45", "22008",
				'date/time field value out of range: "2026-13-45"')):
			ket = self._goi("CHU", "bao_cao_ton_kho", {"p_tu": v, "p_den": den})
			self.assertEqual((ket["error"]["code"], ket["error"]["message"]), (ma, cau))
		# người ngoài NPP (không NV đang hoạt động — RLS cả hai bảng)
		email = "m9-ngoai@nppsale.local"
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": "Ngoai", "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.set_user(email)
		frappe.local._npp_ngu_canh = None
		try:
			# P6 M1 (❓Q12): khoá thêm `tinh_lai_gia_von` — 0 với người không phải NV
			self.assertEqual(api.rpc(ten="bao_cao_ton_kho", tham_so={"p_tu": tu, "p_den": den})["data"], {"lo": [], "dong": [],
				"tinh_lai_gia_von": 0})
		finally:
			self._ve_admin()
		self.assertFalse(h1 == h2)
		self._kiem_con_ton()  # sau HĐ / HĐ huỷ / lô hết / lô rỗng

	def _kiem_con_ton(self):
		"""P6 M0 (đặc tả báo cáo §2.2 — tối ưu NGUON_LO): nguồn chỉ lô còn hàng (`NGUON_LO_CON_TON` — gộp gói lô của lô `batch_qty > 0`) ra ĐÚNG các dòng
		tồn > 0 của nguồn đủ trên sổ sau mọi chứng từ của bài; cổng `batches` lọc `gt qty_on_hand 0` (tự chọn nguồn còn tồn) = cùng câu trên nguồn đủ."""
		from nppsale.cong import dang_ky as D
		from nppsale.cong.bang.kho import NGUON_LO, NGUON_LO_CON_TON

		cot = "x.`name`, x.`lo`, x.`vung`, x.`ton`, x.`nhap`, x.`hang`, x.`gia_von`, x.`expiry_date`, x.`creation`, x.`disabled`"
		du = frappe.db.sql(f"SELECT {cot} FROM {NGUON_LO} x WHERE x.`ton` > 0 ORDER BY x.`name`")
		self.assertTrue(du)
		self.assertEqual(frappe.db.sql(f"SELECT {cot} FROM {NGUON_LO_CON_TON} x WHERE x.`ton` > 0 ORDER BY x.`name`"), du)
		nc = NguCanh(user="Administrator", vai=None, bo_qua_rls=True)
		yc = {"bang": "batches", "select": "id, product_id, batch_code, qty_on_hand, qty_initial, unit_cost, expires_at, status, warehouse_zone, "
			"created_at", "loc": [{"op": "gt", "cot": "qty_on_hand", "gt": 0}], "thu_tu": [{"cot": "id", "tang": True}]}
		theo_loc = doc_cong(yc, nc)["data"]
		with patch.object(D.lay("batches"), "nguon_theo_loc", None):
			self.assertEqual(theo_loc, doc_cong(yc, nc)["data"])

	# ------------------------------------------------------------------------------------------------ luồng cũ (§3.21, V80)
	def test_post_stock_export_luong_cu(self):
		"""Mọi vai, id thật của phiếu xuất lẻ nháp / id lạ / không tham số: LEGACY_FLOW_REMOVED — phiếu không đổi; GET bị từ chối như hàm ghi."""
		self._lo({"ma": "BC-X", "sp": "@P", "vung": "sale", "ton": 5, "gia": 8000, "han": None, "nhan_ngay": -5})
		self._ok(buoc="pk", nguoi="TK", nhan="XKL", dau={"org_id": "@org", "entry_code": "XKL", "type": "export", "warehouse_zone": "sale",
			"dest_warehouse_zone": None, "issue_reason": "damaged", "notes": None, "status": "draft", "created_by": "@u:TK"},
			dong=[{"product_id": "@P", "batch_id": None, "unit_name": "Lon", "quantity": 2, "qty_in_base_uom": 2, "qty_in_transaction_uom": 2,
				"transaction_uom": "Lon", "conversion_factor_snapshot": 1, "unit_cost": 0, "notes": None}])
		ten = self._nh("pk:XKL")
		for nguoi in ("CHU", "TK", "NV"):
			for ts in ({"p_entry_id": ten}, {"p_entry_id": V.LA}, {}):
				ket = self._goi(nguoi, "post_stock_export", ts)
				self.assertEqual((ket["error"]["code"], ket["error"]["message"]), LEGACY, (nguoi, ts))
		self.assertEqual((frappe.db.get_value("Stock Entry", ten, "docstatus"), self._ton_lo("BC-X")), (0, 5))
		from unittest.mock import patch

		with patch("nppsale.cong.api._phuong_thuc", lambda: "GET"):
			self.assertEqual(self._goi("CHU", "post_stock_export", {"p_entry_id": ten})["error"]["code"], "PGRST105")
			self.assertNotIn("error", self._goi("CHU", "bao_cao_ton_kho", {"p_tu": self._hom_nay(), "p_den": self._hom_nay()}))  # hàm đọc: GET được

	# ------------------------------------------------------------------------------------------------ RPC đọc kho đã có với chứng từ P4 (§5.5)
	def _so_rpc(self, sp: str) -> dict:
		"""Số của các RPC đọc kho cho một mặt hàng (dưới CHU — được xem giá vốn) + tổng từ nguồn lô cổng `batches` (cùng luật NGUON_LO)."""
		tbh = self._goi("CHU", "ton_ban_theo_hang", {})["data"]
		ktt = [r for r in self._goi("CHU", "ton_kho_trang", {"p_tim": frappe.db.get_value("Item", sp, "item_code"), "p_con_ton": False,
			"p_limit": 500})["data"] if r["product_id"] == sp]
		lo = doc_cong({"bang": "batches", "select": "qty_on_hand, unit_cost, warehouse_zone", "loc": [{"op": "eq", "cot": "product_id", "gt": sp}]},
			NguCanh(user=self.ma["u:CHU"], vai="owner"))["data"]
		cong = {v: (sum(flt(r["qty_on_hand"]) for r in lo if r["warehouse_zone"] == v),
			sum(flt(r["qty_on_hand"]) * flt(r["unit_cost"]) for r in lo if r["warehouse_zone"] == v)) for v in ("sale", "date")}
		k = ktt[0] if ktt else {}
		return {"ban": flt(tbh.get(sp)), "trang_sale": (flt(k.get("sale_qty")), round(flt(k.get("sale_value")), 2)),
			"trang_date": (flt(k.get("date_qty")), round(flt(k.get("date_value")), 2)), "cong_sale": (cong["sale"][0], round(cong["sale"][1], 2)),
			"cong_date": (cong["date"][0], round(cong["date"][1], 2))}

	def _gia_tri_ton(self) -> tuple[float, int]:
		r = self._goi("CHU", "stock_value_summary", {})["data"][0]
		return flt(r["inventory_value"]), int(r["batch_count"])

	def _kiem(self, sp: str, sale: tuple, date: tuple, buoc: str):
		so = self._so_rpc(sp)
		mong = {"ban": sale[0], "trang_sale": sale, "trang_date": date, "cong_sale": sale, "cong_date": date}
		self.assertEqual(so, mong, buoc)

	def test_rpc_kho_sau_chung_tu_p4(self):
		a, c = self.ma["A"], self.ma["C"]
		gt0, n0 = self._gia_tri_ton()
		self._kiem(a, (0, 0), (0, 0), "đầu")
		# PN: 2 thùng × 240.000 → 48 hộp @10.000 (kho bán)
		self._ok(buoc="pn", nguoi="TK", nhan="P", dau={"org_id": "@org", "supplier_id": "@S1", "invoice_number": "HD-BC", "warehouse_zone": "sale",
			"discount": 0, "vat_override": None, "notes": None, "status": "draft", "created_by": "@u:TK", "subtotal": 480000, "vat": 0,
			"total": 480000}, dong=[{"product_id": "@A", "unit_name": "thùng", "quantity": 2, "unit_price": 240000, "line_discount": 0,
			"vat_rate": 0, "conversion_factor": 24, "line_total": 480000, "notes": None, "sort_order": 1}])
		self._ok(buoc="pn_hoan", nguoi="TK", nhan="P")
		self._kiem(a, (48, 480000), (0, 0), "PN")
		self.assertEqual(self._gia_tri_ton(), (gt0 + 480000, n0 + 1))
		# PTNCC: 3 hộp đơn giá trả 12.000 → kho giảm theo GIÁ LÔ (S2)
		self._ok(buoc="ptn", nguoi="TK", nhan="R", dau={"org_id": "@org", "supplier_id": "@S1", "warehouse_zone": "sale", "discount": 0,
			"vat_override": None, "reason": None, "notes": None, "status": "draft", "created_by": "@u:TK"}, dong=[{"product_id": "@A",
			"unit_name": "hộp", "quantity": 3, "unit_price": 12000, "line_discount": 0, "vat_rate": 0, "conversion_factor": 1, "line_total": 36000,
			"notes": None, "sort_order": 1}])
		self._ok(buoc="ptn_gui", nguoi="TK", nhan="R")
		self._kiem(a, (45, 450000), (0, 0), "PTNCC")
		# IN- (nhập kho tay không NCC): 10 hộp giá vốn 9.000 → lô LOT-IN-BC-1-1
		self._ok(buoc="nhap_kho", nguoi="TK", nhan="IN1", p={"entry_code": "IN-BC-1", "warehouse_zone": "sale", "lines": [{"product_id": "@A",
			"unit_name": "hộp", "qty_tx": 10, "conv": 1, "base_qty": 10, "base_cost": 9000}]})
		self._kiem(a, (55, 540000), (0, 0), "IN-")
		self.assertEqual(self._gia_tri_ton(), (gt0 + 540000, n0 + 2))
		# XKL: 2 hộp — hạn cũ trước, hoà hạn (A không hạn) theo lúc tạo lô → lô của PN (10.000)
		ten = self._pk_nhap("XKL", "export", "sale", [("@A", "hộp", 2)])
		self._ok(buoc="xuat_le", nguoi="TK", nhan="XKL")
		self._kiem(a, (53, 520000), (0, 0), "XKL-")
		# CKL: 4 hộp kho bán → kho cận date (giữ giá lô)
		self._pk_nhap("CKL", "transfer", "sale", [("@A", "hộp", 4)], dich="date")
		self._ok(buoc="chuyen", nguoi="TK", nhan="CKL")
		self._kiem(a, (49, 480000), (4, 40000), "CKL-")
		self.assertEqual(self._gia_tri_ton()[0], gt0 + 520000)
		# DCK (kiểm kê): lô của IN- thừa 2 (giá lô 9.000) → +2 kho bán
		lo_in = frappe.db.get_value("Batch", {"name": ("like", "LOT-IN-BC-1-%")}, "name")
		self._ok(buoc="pk", nguoi="TK", nhan="KK", dau={"org_id": "@org", "entry_code": "KK", "type": "stocktake", "dest_warehouse_zone": None,
			"issue_reason": None, "notes": None, "status": "draft", "created_by": "@u:TK"}, dong=[{"product_id": "@A", "batch_id": f"{lo_in}::sale",
			"unit_name": "hộp", "quantity": 2, "qty_in_base_uom": 2, "qty_in_transaction_uom": 2, "transaction_uom": "hộp",
			"conversion_factor_snapshot": 1, "unit_cost": 9000, "notes": None}])
		self._ok(buoc="kk_duyet", nguoi="CHU", nhan="KK")
		self._kiem(a, (51, 498000), (4, 40000), "DCK-")
		# CKL tự động (rà soát): C hạn +20 nhập khi ngưỡng 10 (kho bán) → ngưỡng 30 → rà soát chuyển hết sang kho cận date
		self._ok(buoc="nguong", nguoi="MAY_CHU", ngay=10)
		self._ok(buoc="pn", nguoi="TK", nhan="PC", dau={"org_id": "@org", "supplier_id": "@S1", "invoice_number": "HD-BC-C", "warehouse_zone": "sale",
			"discount": 0, "vat_override": None, "notes": None, "status": "draft", "created_by": "@u:TK", "subtotal": 50000, "vat": 0,
			"total": 50000}, dong=[{"product_id": "@C", "unit_name": "chai", "quantity": 5, "unit_price": 10000, "line_discount": 0, "vat_rate": 0,
			"conversion_factor": 1, "line_total": 50000, "notes": None, "sort_order": 1}])
		self._ok(buoc="pn_hoan", nguoi="TK", nhan="PC")
		self._kiem(c, (5, 50000), (0, 0), "PN C (ngưỡng 10)")
		self._ok(buoc="nguong", nguoi="MAY_CHU", ngay=30)
		self.assertGreaterEqual(self._ok(buoc="ra_soat", nguoi="TK"), 1)
		self._kiem(c, (0, 0), (5, 50000), "CKL- tự động")
		# lô hết tồn không mất khỏi cổng `batches` khi còn sổ; lô RỖNG (chưa phiếu nào) là dòng tồn 0 ở `npp_kho_tao`
		self._lo({"ma": "BC-HET", "sp": "@A", "vung": "sale", "nhap": 1, "ton": 0, "gia": 1000, "han": None, "nhan_ngay": -3})
		self.assertEqual(self._ton_lo("BC-HET"), 0)
		ket = self._cong("TK", {"bang": "batches", "hanh_dong": "insert", "gia_tri": {"org_id": self.ma["org"], "product_id": a, "batch_code": "BC-RONG",
			"qty_initial": 0, "qty_on_hand": 0, "unit_cost": 5000, "warehouse_zone": "date", "status": "available", "expires_at": "2099-12-31"},
			"select": "id"})
		self.assertNotIn("error", ket, ket)
		self.assertEqual((ket["data"][0]["id"], self._ton_lo("BC-RONG", "date")), ("BC-RONG::date", 0))
		self._kiem(a, (51, 498000), (4, 40000), "lô rỗng / hết tồn")
		self.assertNotIn(ten, [])
		self._kiem_con_ton()  # sau PN, PTNCC, IN-, XKL-, CKL-, DCK-, CKL- tự động, lô hết / lô rỗng

	def _pk_nhap(self, nhan: str, loai: str, vung: str, dong: list, **dau) -> str:
		d = [{"product_id": sp, "batch_id": None, "unit_name": dv, "quantity": sl, "qty_in_base_uom": sl, "qty_in_transaction_uom": sl,
			"transaction_uom": dv, "conversion_factor_snapshot": 1, "unit_cost": 0, "notes": None} for sp, dv, sl in dong]
		self._ok(buoc="pk", nguoi="TK", nhan=nhan, dau={"org_id": "@org", "entry_code": nhan, "type": loai, "warehouse_zone": vung,
			"dest_warehouse_zone": dau.get("dich"), "issue_reason": "damaged" if loai == "export" else None, "notes": None, "status": "draft",
			"created_by": "@u:TK"}, dong=d)
		return self._nh("pk:" + nhan)

	# ------------------------------------------------------------------------------------------------ giá vốn kỳ đọc cổng (§5.7 — soát thiếu S1, §10)
	def test_gia_von_ky_doc_cong(self):
		"""Giá vốn kỳ của mọi báo cáo đọc cổng (`fetchCogsForRange` + `locPhieuXuatBan`; `bao_cao_so_ban` / `finance_*` chưa có trên bản Frappe → giao
		diện lùi về đường này): phiếu `export` ĐÃ GHI SỔ trong kỳ = HĐ (giá xuất) + trả NCC (giá LÔ, không giá trả — S2) + xuất lẻ (dòng 0 — §10 điểm 3);
		KHÔNG HĐ huỷ (cổng `cancelled`), chuyển kho (`transfer`), kiểm kê (`stocktake`). Giá vốn hàng trả (`fetchReturnCosts`) = dòng phiếu `import` ghi
		sổ có ghi chú ĐÚNG "Nhập lại từ phiếu trả <phiếu>" (§10 điểm 1 — tờ ghi có có kho của phiếu tự lập)."""
		self._ok(buoc="pn", nguoi="TK", nhan="P", dau={"org_id": "@org", "supplier_id": "@S1", "invoice_number": "HD-GV", "warehouse_zone": "sale",
			"discount": 0, "vat_override": None, "notes": None, "status": "draft", "created_by": "@u:TK", "subtotal": 500000, "vat": 0,
			"total": 500000}, dong=[{"product_id": "@A", "unit_name": "hộp", "quantity": 50, "unit_price": 10000, "line_discount": 0, "vat_rate": 0,
			"conversion_factor": 1, "line_total": 500000, "notes": None, "sort_order": 1}])
		self._ok(buoc="pn_hoan", nguoi="TK", nhan="P")
		self._ok(buoc="ban", nguoi="CHU", nhan="H1", khach="@K1", dong=[{"product_id": "@A", "unit_name": "hộp", "quantity": 10}])
		self._ok(buoc="ban", nguoi="CHU", nhan="H2", khach="@K1", dong=[{"product_id": "@A", "unit_name": "hộp", "quantity": 5}])
		self._ok(buoc="huy_hd", nguoi="CHU", nhan="H2", ly_do="sai")
		self._pk_nhap("XKL", "export", "sale", [("@A", "hộp", 2)])
		self._ok(buoc="xuat_le", nguoi="TK", nhan="XKL")
		self._pk_nhap("CKL", "transfer", "sale", [("@A", "hộp", 4)], dich="date")
		self._ok(buoc="chuyen", nguoi="TK", nhan="CKL")
		self._ok(buoc="ptn", nguoi="TK", nhan="R", dau={"org_id": "@org", "supplier_id": "@S1", "warehouse_zone": "sale", "discount": 0,
			"vat_override": None, "reason": None, "notes": None, "status": "draft", "created_by": "@u:TK"}, dong=[{"product_id": "@A",
			"unit_name": "hộp", "quantity": 3, "unit_price": 12000, "line_discount": 0, "vat_rate": 0, "conversion_factor": 1, "line_total": 36000,
			"notes": None, "sort_order": 1}])
		self._ok(buoc="ptn_gui", nguoi="TK", nhan="R")
		lo = f"{self._ten(self.st, 'pn:P')}-001"
		self._ok(buoc="pk", nguoi="TK", nhan="KK", dau={"org_id": "@org", "entry_code": "KK", "type": "stocktake", "dest_warehouse_zone": None,
			"issue_reason": None, "notes": None, "status": "draft", "created_by": "@u:TK"}, dong=[{"product_id": "@A", "batch_id": f"{lo}::sale",
			"unit_name": "hộp", "quantity": -1, "qty_in_base_uom": -1, "qty_in_transaction_uom": -1, "transaction_uom": "hộp",
			"conversion_factor_snapshot": 1, "unit_cost": 0, "notes": None}])
		self._ok(buoc="kk_duyet", nguoi="CHU", nhan="KK")
		self._ok(buoc="tra_khach", nguoi="CHU", nhan="T1", khach="@K1", dong=[{"product_id": "@A", "unit_name": "hộp", "quantity": 1,
			"unit_price": 12000, "vat_rate": 0, "is_exchange": False}])
		hn = self._hom_nay()
		self.assertEqual(self._ok(buoc="gia_von_ky", nguoi="CHU", tu=hn, den=hn), {"cogs": 130000.0})  # 10 × 10.000 + 3 × 10.000 + 2 × 0
		self.assertEqual(self._ok(buoc="gia_von_ky", nguoi="CHU", tu=self._hom_nay(-1), den=self._hom_nay(-1)), {"cogs": 0.0})  # ngoài kỳ
		pt = self._nh("tk:T1")
		ket = self._cong("CHU", {"bang": "stock_entries", "select": "id, notes", "loc": [{"op": "eq", "cot": "type", "gt": "import"},
			{"op": "eq", "cot": "status", "gt": "posted"}, {"op": "in", "cot": "notes", "gt": [f"Nhập lại từ phiếu trả {pt}"]}]})
		self.assertEqual(len(ket["data"]), 1, ket)
		dong = self._cong("CHU", {"bang": "stock_entry_lines", "select": "qty_in_base_uom, unit_cost", "loc": [{"op": "eq", "cot": "entry_id",
			"gt": ket["data"][0]["id"]}]})["data"]
		self.assertEqual(sum(abs(flt(d["qty_in_base_uom"])) * flt(d["unit_cost"]) for d in dong), 10000)  # giá vốn hàng trả = giá lô nhận

	# ------------------------------------------------------------------------------------------------ giá vốn V74 (§6.9, §7.1)
	def test_gia_von_v74(self):
		"""V74 trên sổ: giá vốn HĐ = 20 × 8.000 + 10 × 9.000 = 250.000 (FIFO ngày nhận qua hai lô); trả NCC 5 hộp đơn giá 10.000 từ L2 → kho giảm 45.000
		(giá lô), chênh 5.000 vào TK chi phí mặc định của công ty (lõi — `purchase_invoice.py`, nppsale không ghi — §7.1 #4); thừa kiểm kê 2 (giá dòng
		8.500) + hàng khách trả 1 (12.000) vào L2 → giá lô L2 GIỮ 9.000 (thừa theo giá vốn hiện tại của lô — M6; nhập lại hàng trả theo giá lô — P3):
		⚠K "bình quân lại" của đặc tả không xảy ra."""
		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == "V74")
		st = {"ma": "V74", "nhan": {}}
		for b in t["buoc"]:
			ket, _ = self._buoc(b, st)
			self.assertNotIn("error", ket, f"{b['buoc']}: {ket.get('error')}")
		hd, r = st["nhan"]["hd:H1"], self._cuoi(st["nhan"]["ptn:R"])

		def gv(dt: str, ten: str) -> float:
			return flt(frappe.db.sql("""SELECT SUM(`stock_value_difference`) FROM `tabStock Ledger Entry` WHERE `voucher_type` = %s
				AND `voucher_no` = %s AND `is_cancelled` = 0""", (dt, ten))[0][0])

		self.assertEqual(gv("Sales Invoice", hd), -250000)
		self.assertEqual(gv("Purchase Invoice", r), -45000)
		cty = frappe.db.get_value("Purchase Invoice", r, "company")
		tk_cp = frappe.get_cached_value("Company", cty, "default_expense_account")
		chenh = flt(frappe.db.sql("""SELECT SUM(`debit` - `credit`) FROM `tabGL Entry` WHERE `voucher_type` = 'Purchase Invoice' AND `voucher_no` = %s
			AND `account` = %s AND `is_cancelled` = 0""", (r, tk_cp))[0][0])
		self.assertEqual(chenh, -5000)  # trả 50.000 cho hàng giá vốn 45.000 → Có 5.000 vào TK chi phí (giảm giá vốn)
		l2 = f"{frappe.db.get_value('Purchase Invoice', st['nhan']['pn:P2'], 'name')}-001"
		lo = doc_cong({"bang": "batches", "select": "qty_on_hand, unit_cost", "loc": [{"op": "eq", "cot": "id", "gt": f"{l2}::sale"}]},
			NguCanh(user="Administrator", vai=None, bo_qua_rls=True))["data"][0]
		self.assertEqual((flt(lo["qty_on_hand"]), round(flt(lo["unit_cost"]), 2)), (38, 9000))  # 50 − 10 bán − 5 trả NCC + 2 thừa + 1 khách trả
		self._kiem_con_ton()  # sau trả NCC, kiểm kê thừa, nhập lại hàng khách trả

	# ------------------------------------------------------------------------------------------------ khám sổ P4 (§8.1)
	def _kham(self) -> dict:
		return quet_kho_mua([v for k, v in self.ma.items() if len(k) == 1 and k.isupper()], [v for k, v in self.ma.items() if k[:1] == "S"
			and k[1:].isdigit()])

	def _nhom(self, kq: dict | None = None) -> list:
		return sorted({x["nhom"] for x in (kq or self._kham())["can_xem"]})

	def test_kham_so_kho_mua_sach_va_thong_ke(self):
		"""Sổ do method lập (PN, HĐ, trả NCC, xuất lẻ, chuyển kho, kiểm kê, phiếu chi trả trước, PN nháp huỷ) → không dòng nào; thống kê theo dòng
		nppsale (66, 70, 72, 74, 77–82)."""
		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == "V74")
		for b in t["buoc"]:
			self.assertNotIn("error", self._buoc(b, self.st)[0], b["buoc"])
		self._pk_nhap("XKL", "export", "sale", [("@A", "hộp", 1)])
		self._ok(buoc="xuat_le", nguoi="TK", nhan="XKL")
		self._pk_nhap("CKL", "transfer", "sale", [("@A", "hộp", 2)], dich="date")
		self._ok(buoc="chuyen", nguoi="TK", nhan="CKL")
		self._ok(buoc="chi", nguoi="KT", nhan="C", ncc="@S2", tien=50000, cach="cash")  # S2 không nợ → trả trước 50.000
		self._ok(buoc="chi", nguoi="KT", nhan="C3", ncc="@S3", tien=20000, cach="cash")  # S3 không nợ → trả trước 20.000
		self._ok(buoc="chi", nguoi="KT", nhan="C4", ncc="@S4", tien=10000, cach="cash")  # S4 (NCC chính của R): phiếu chi rồi HUỶ
		self._ok(buoc="huy_chi", nguoi="KT", nhan="C4", ly_do="chi nhầm")
		self._ok(buoc="pn", nguoi="TK", nhan="PH", dau={"org_id": "@org", "supplier_id": "@S1", "invoice_number": None, "warehouse_zone": "sale",
			"discount": 0, "vat_override": None, "notes": None, "status": "draft", "created_by": "@u:TK", "subtotal": 1000, "vat": 0, "total": 1000},
			dong=[{"product_id": "@A", "unit_name": "hộp", "quantity": 1, "unit_price": 1000, "line_discount": 0, "vat_rate": 0, "conversion_factor": 1,
			"line_total": 1000, "notes": None, "sort_order": 1}])
		self._ok(buoc="pn_huy", nguoi="TK", nhan="PH", ly_do="lập nhầm")  # nháp huỷ = giữ nháp + dấu huỷ (§7.3 điểm 1)
		kq = self._kham()
		self.assertEqual(kq["can_xem"], [])
		tk = kq["thong_ke"]
		self.assertEqual({k: tk[k] for k in ("phieu_kho_dao_huy_rieng", "the_kho_lech", "lo_am", "ncc_trung_ten", "gia_nhap_trung", "ncc_paid_lech",
			"dong_ncc_am_mo", "ptncc_dang_tru_no", "ncc_tra_truoc", "tra_truoc_ncc_tong", "pn_co_hang_da_xuat", "pn_da_huy", "ptncc_da_huy",
			"nhap_mang_dau_huy", "phieu_chi_ncc", "tra_truoc_con", "bin_am_khong_lo", "ncc_chi_con_mat_hang")}, {
			"phieu_kho_dao_huy_rieng": 0, "the_kho_lech": 0, "lo_am": 0, "ncc_trung_ten": 0, "gia_nhap_trung": 0, "ncc_paid_lech": 0,
			"dong_ncc_am_mo": 1, "ptncc_dang_tru_no": 1, "ncc_tra_truoc": 2, "tra_truoc_ncc_tong": 70000, "pn_co_hang_da_xuat": 2, "pn_da_huy": 0,
			"ptncc_da_huy": 0, "nhap_mang_dau_huy": 1, "phieu_chi_ncc": 2, "tra_truoc_con": 70000, "bin_am_khong_lo": 0,
			"ncc_chi_con_mat_hang": 0})  # NCC chính: S1 có phiếu nhập, S3 (B / N) phiếu chi còn hiệu lực, S4 (R) phiếu chi ĐÃ HUỶ — vẫn là chứng từ
		self.assertGreaterEqual(tk["gia_nhap"], 1)

	def test_kham_so_kho_mua_bat_lech(self):
		"""Từng nhóm 28–32 trên sổ làm lệch (bằng quyền máy chủ — như dữ liệu hỏng / ghi tay ở Desk)."""
		a = self.ma["A"]
		self._lo({"ma": "KS-1", "sp": "@A", "vung": "sale", "ton": 10, "gia": 1000, "han": None, "nhan_ngay": -5})
		kq = self._kham()
		self.assertEqual(kq["can_xem"], [])
		# dòng 72 — NCC chỉ còn là NCC chính của mặt hàng (nền: M → S1, B / N → S3, R → S4; chưa chứng từ nào) — phiếu NHÁP / phiếu chi ĐÃ HUỶ vẫn
		# là chứng từ (nppsale đếm mọi dòng purchase_invoices / supplier_payments, kể cả nháp / huỷ)
		self.assertEqual(kq["thong_ke"]["ncc_chi_con_mat_hang"], 3)
		self._ok(buoc="pn", nguoi="TK", nhan="PX", dau={"org_id": "@org", "supplier_id": "@S1", "invoice_number": None, "warehouse_zone": "sale",
			"discount": 0, "vat_override": None, "notes": None, "status": "draft", "created_by": "@u:TK", "subtotal": 1000, "vat": 0, "total": 1000},
			dong=[{"product_id": "@A", "unit_name": "hộp", "quantity": 1, "unit_price": 1000, "line_discount": 0, "vat_rate": 0, "conversion_factor": 1,
			"line_total": 1000, "notes": None, "sort_order": 1}])
		self.assertEqual(self._kham()["thong_ke"]["ncc_chi_con_mat_hang"], 2)
		self._ok(buoc="chi", nguoi="KT", nhan="CX", ncc="@S3", tien=10000, cach="cash")
		self._ok(buoc="huy_chi", nguoi="KT", nhan="CX", ly_do="chi nhầm")
		self.assertEqual(self._kham()["thong_ke"]["ncc_chi_con_mat_hang"], 1)
		kho = self.cd.kho_ban
		# 29: Bin lệch sổ kho (và 28: lệch tồn lô)
		frappe.db.sql("UPDATE `tabBin` SET `actual_qty` = `actual_qty` + 1 WHERE `item_code` = %s AND `warehouse` = %s", (a, kho))
		kq = self._kham()
		self.assertEqual(self._nhom(kq), [28, 29])
		self.assertEqual({(x["nhom"], x["chung_tu"], x["vung"]) for x in kq["can_xem"]}, {(28, a, "sale"), (29, a, "sale")})
		from nppsale.kham_so import kham_so_kho_mua

		kham_so_kho_mua()  # việc đêm: cả sổ — có dòng cần xem → Error Log (setUp ghi lại thay vì ghi bảng MyISAM)
		self.assertEqual([x for x in self.nhat_ky if str(x).startswith("Khám sổ kho / mua hàng:")], ["Khám sổ kho / mua hàng: 2 chỗ cần xem"])
		self.nhat_ky.clear()
		frappe.db.sql("UPDATE `tabBin` SET `actual_qty` = `actual_qty` - 1 WHERE `item_code` = %s AND `warehouse` = %s", (a, kho))
		self.assertEqual(self._nhom(), [])
		# 30: lô âm (dòng gói lô xuất lớn hơn tồn) — kéo theo 28 (Σ gói lô ≠ Bin)
		e = frappe.db.sql("""SELECT e.`name` FROM `tabSerial and Batch Entry` e JOIN `tabSerial and Batch Bundle` b ON b.`name` = e.`parent`
			WHERE e.`batch_no` = 'KS-1' AND b.`type_of_transaction` = 'Inward' LIMIT 1""")[0][0]
		frappe.db.set_value("Serial and Batch Entry", e, "qty", -1, update_modified=False)
		kq = self._kham()
		self.assertEqual(self._nhom(kq), [28, 30])
		self.assertEqual([(x["chung_tu"], x["hang"], x["vung"]) for x in kq["can_xem"] if x["nhom"] == 30], [("KS-1", a, "sale")])
		self.assertEqual(kq["thong_ke"]["lo_am"], 1)
		frappe.db.set_value("Serial and Batch Entry", e, "qty", 10, update_modified=False)
		self.assertEqual(self._nhom(), [])
		# 31: NCC trùng tên (khác hoa thường / khoảng trắng)
		nhom = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
		s = frappe.get_doc({"doctype": "Supplier", "supplier_name": "  ncc một ", "supplier_group": nhom}).insert(ignore_permissions=True).name
		self.ma["S9"] = s
		kq = self._kham()
		self.assertEqual(self._nhom(kq), [31])
		self.assertEqual((kq["can_xem"][0]["chung_tu"], kq["can_xem"][0]["chi_tiet"]), (", ".join(sorted([self.ma["S1"], s])), "tên “ncc một”"))
		self.assertEqual(kq["thong_ke"]["ncc_trung_ten"], 1)
		del self.ma["S9"]
		# 32: hai giá nhập cho một (mặt hàng, đơn vị)
		from nppsale.su_kien.san_pham import bang_gia_nhap

		for g in (10000, 11000):
			frappe.get_doc({"doctype": "Item Price", "item_code": a, "price_list": bang_gia_nhap(), "uom": "hộp", "price_list_rate": g}).db_insert()
		kq = self._kham()
		self.assertEqual([(x["nhom"], x["chung_tu"]) for x in kq["can_xem"]], [(32, a)])
		self.assertEqual((kq["thong_ke"]["gia_nhap"], kq["thong_ke"]["gia_nhap_trung"]), (2, 1))

	def test_kham_so_phieu_nhap_lai_huy_rieng(self):
		"""27: phiếu trả TỰ SINH (đơn kèm hàng trả khi xuất HĐ) Hoàn thành có phiếu nhập lại `NL-`; huỷ riêng phiếu ấy ở Desk (bỏ qua
		cancel_stock_entry — việc #24 chặn) → phiếu trả vẫn Hoàn thành mà không còn chứng từ nhập kho → nhóm 27."""
		import uuid

		self._lo({"ma": "KS-T", "sp": "@A", "vung": "sale", "ton": 10, "gia": 1000, "han": None, "nhan_ngay": -5})
		p = {"client_request_id": str(uuid.uuid4()), "order": {"order_code": "TAM-1", "customer_id": self.ma["K1"], "payment_terms": "COD",
			"expected_delivery": None, "subtotal": 24000, "vat": 0, "total": 12000, "notes": None, "status": "submitted", "approval_reason": None,
			"sales_user_id": None}, "lines": [{"product_id": self.ma["A"], "unit_name": "hộp", "quantity": 2, "unit_price": 12000, "line_discount": 0,
			"conversion_factor": 1, "vat_rate": 0, "line_total": 24000}], "returns": {"reason": "damaged"},
			"return_lines": [{"product_id": self.ma["A"], "unit_name": "hộp", "quantity": 1, "unit_price": 12000, "vat_rate": 0}]}
		ket = self._goi("CHU", "create_order_with_lines", {"p": p})
		self.assertNotIn("error", ket, ket)
		don = ket["data"][0]["order_id"]
		dd = frappe.get_all("Sales Order Item", filters={"parent": don}, fields=["name", "item_code", "uom", "conversion_factor", "qty", "rate",
			"npp_giam_dong", "npp_thue_suat"], order_by="idx asc")
		ket = self._goi("CHU", "post_invoice", {"p": {"order_id": don, "lines": [{"order_line_id": r.name, "product_id": r.item_code,
			"unit_name": r.uom, "conversion_factor": r.conversion_factor, "quantity": r.qty, "unit_price": r.rate, "line_discount": r.npp_giam_dong,
			"vat_rate": r.npp_thue_suat, "is_exchange": False} for r in dd]}})
		self.assertNotIn("error", ket, ket)
		pt = frappe.db.get_value("NPP Phieu Tra", {"hoa_don": ket["data"][0]["invoice_id"]}, "name")
		ket = self._goi("CHU", "complete_return", {"p_return_id": pt, "p_zone": "sale"})
		self.assertNotIn("error", ket, ket)
		nl0 = frappe.db.get_value("NPP Phieu Tra", pt, "phieu_nhap_kho")
		# huỷ nhập kho (phiếu tự sinh về Chờ xử lý — NL- cũ đã huỷ) rồi hoàn thành lại (NL- mới): phiếu Hoàn thành CÓ chứng từ nhập kho → sạch
		for ten, ts in (("cancel_return", {"p_reason": "nhập lại"}), ("complete_return", {"p_zone": "sale"})):
			ket = self._goi("CHU", ten, {"p_return_id": pt, **ts})
			self.assertNotIn("error", ket, ket)
		nl = frappe.db.get_value("NPP Phieu Tra", pt, "phieu_nhap_kho")
		self.assertTrue(nl != nl0 and frappe.db.get_value("Stock Entry", nl0, "docstatus") == 2)
		self.assertTrue(nl and frappe.db.get_value("Stock Entry", nl, "npp_loai") == "nhap_lai_tra")
		self.assertEqual(self._nhom(), [])
		se = frappe.get_doc("Stock Entry", nl)
		se.flags.ignore_permissions = True
		se.cancel()
		kq = self._kham()
		self.assertEqual([(x["nhom"], x["chung_tu"], x["phieu_kho"]) for x in kq["can_xem"]], [(27, pt, nl)])
		self.assertEqual(kq["thong_ke"]["phieu_kho_dao_huy_rieng"], 1)

	def test_kham_so_viec_dem_noi_tiep(self):
		"""Việc đêm 01:00: kham_so_cong_no → kham_so_cong_no_ncc → kham_so_kho_mua (khám sổ P4 cả sổ)."""
		from unittest.mock import patch

		from nppsale import kham_so

		goi = []
		with patch.object(kham_so, "kham_so_kho_mua", lambda: goi.append(1)):
			kham_so.kham_so_cong_no_ncc()
		self.assertEqual(goi, [1])
