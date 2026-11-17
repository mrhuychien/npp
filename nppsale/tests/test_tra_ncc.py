"""Phiếu trả NCC (P4 — M2) ngoài kịch bản vàng: luật ghi thẳng phiếu NHÁP qua cổng (BP §6.1 siết — USE_RPC, câu dòng của §7.3 điểm 23, vai / RLS
đọc mọi NV), cột cổng đọc, câu `INSUFFICIENT_STOCK |` nhiều dòng (phần dòng trước lấy, lô tắt), khoá Bin là câu đầu, `DA_CAN_TRU`, khôi phục ném lỗi
không nghiệp vụ, RPC mới `sua_phieu_tra_ncc` (một giao dịch, lùi hết khi gửi hỏng, chỉ lưu nháp, sửa nháp tại chỗ, phiếu đã huỷ, vai) — cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_tra_ncc

Dựng trên bộ dữ liệu F của tệp vàng (test_kho_mua_vang.dung_nen_kho) + bốn lô của vùng ② (L-B1…L-B4 — đặc tả §6.2).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.cong.loi import NppLoi
from nppsale.tests import test_kho_mua_vang as V
from nppsale.thiet_lap.kho_mua import cai_dat_kho

USE_RPC = "USE_RPC: dùng nút Gửi phiếu / Huỷ phiếu / Khôi phục"
FORBIDDEN = "FORBIDDEN: vai trò của bạn không được làm thao tác kho / mua hàng này."
LO = [  # §6.2: M — kho date L-B1 hạn +15 tồn 10 giá 1.000, L-B2 hạn +4 tồn 5 giá 1.200; kho bán L-B3 tồn 100 giá 900; B — kho date L-B4 tồn 3 giá 500
	{"ma": "L-B1", "sp": "@M", "vung": "date", "ton": 10, "gia": 1000, "han": 15, "nhan_ngay": -46},
	{"ma": "L-B2", "sp": "@M", "vung": "date", "ton": 5, "gia": 1200, "han": 4, "nhan_ngay": -42},
	{"ma": "L-B3", "sp": "@M", "vung": "sale", "ton": 100, "gia": 900, "han": 197, "nhan_ngay": -76},
	{"ma": "L-B4", "sp": "@B", "vung": "date", "ton": 3, "gia": 500, "han": 197, "nhan_ngay": -76},
]


class TestTraNcc(IntegrationTestCase):
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
		for b in LO:
			V.dung_lo(self.ma, self.cd, b)

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

	def _dong(self, dong):
		return [{"product_id": self.ma[sp], "unit_name": dv, "quantity": sl, "unit_price": gia, "line_discount": giam, "vat_rate": 0,
			"conversion_factor": 1, "sort_order": i} for i, (sp, dv, sl, gia, giam) in enumerate(dong, 1)]

	def _phieu(self, nguoi="TK", dong=None, **dau) -> str:
		g = {"org_id": self.ma["org"], "supplier_id": self.ma["S1"], "warehouse_zone": "date", "discount": 0, "status": "draft", **dau}
		ket = self._cong(nguoi, {"bang": "supplier_returns", "hanh_dong": "insert", "gia_tri": g, "select": "id"})
		self.assertNotIn("error", ket, ket)
		ten = ket["data"][0]["id"]
		if dong:
			self.assertNotIn("error", self._ghi_dong(nguoi, ten, dong))
		return ten

	def _ghi_dong(self, nguoi, ten, dong):
		return self._cong(nguoi, {"bang": "supplier_return_lines", "hanh_dong": "insert", "select": "id",
			"gia_tri": [{"return_id": ten, **d} for d in self._dong(dong)]})

	def _loi(self, ket, ma, cau):
		self.assertIn("error", ket, ket)
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), (ma, cau))

	def _ton(self, lo: str) -> float:
		return flt(frappe.db.sql("""SELECT COALESCE(SUM(e.`qty`), 0) FROM `tabSerial and Batch Entry` e JOIN `tabSerial and Batch Bundle` b
			ON b.`name` = e.`parent` AND b.`docstatus` = 1 AND b.`is_cancelled` = 0 WHERE e.`is_cancelled` = 0 AND e.`batch_no` = %s""", lo)[0][0])

	def _so_no(self, ten) -> float | None:
		x = frappe.db.get_value("NPP Cong No NCC", {"chung_tu": ten}, "so_tien")
		return None if x is None else flt(x)

	# ------------------------------------------------------------------------------------------------ cổng ghi phiếu nháp
	def test_cong_ghi_nhap(self):
		ins = lambda nguoi, g: self._cong(nguoi, {"bang": "supplier_returns", "hanh_dong": "insert", "select": "id",  # noqa: E731
			"gia_tri": {"org_id": self.ma["org"], "supplier_id": self.ma["S1"], **g}})
		self._loi(ins("TK", {"status": "completed"}), "P0001", USE_RPC)
		self._loi(ins("NV", {"status": "draft"}), "42501", 'new row violates row-level security policy for table "supplier_returns"')
		self._loi(ins("TK", {"stock_entry_id": "X"}), "P0001", USE_RPC)  # cột của RPC
		self._loi(ins("TK", {"warehouse_zone": "kho"}), "23514",
			'new row for relation "supplier_returns" violates check constraint "supplier_returns_warehouse_zone_check"')
		self._loi(ins("TK", {"supplier_id": None}), "23502",
			'null value in column "supplier_id" of relation "supplier_returns" violates not-null constraint')
		self._loi(ins("TK", {"supplier_id": "NCC-KHONG-CO"}), "23503",
			'insert or update on table "supplier_returns" violates foreign key constraint "supplier_returns_supplier_id_fkey"')
		# mã gõ tay / return_seq bị bỏ (trigger mig 240 đè); mặc định kho cận date + ngày trả hôm nay; tiền xem của trình duyệt bỏ (lõi tính)
		ten = ins("TK", {"return_code": "TU-GO", "return_seq": 99, "total": 999999})["data"][0]["id"]
		self.assertTrue(ten.startswith("PTNCC-") and "TU-GO" not in ten, ten)
		r = self._cong("TK", {"bang": "supplier_returns", "select": "warehouse_zone, return_date, total, status, return_code",
			"loc": [{"op": "eq", "cot": "id", "gt": ten}]})["data"][0]
		self.assertEqual(r, {"warehouse_zone": "date", "return_date": str(V.XH.hom_nay()), "total": 0, "status": "draft", "return_code": ten})
		# dòng: SL ≤ 0, giá / giảm âm, tiền âm, tiền 0 → câu dòng ngay lúc lưu (§7.3 điểm 23) — lô không ghi dòng nào
		for dong, cau in (([("M", "hộp", 2, 1000, 0), ("M", "hộp", 0, 1000, 0)], "SO_LUONG_KHONG_HOP_LE: Dòng 2 có số lượng không lớn hơn 0."),
				([("M", "hộp", 1, -1, 0)], "GIA_KHONG_HOP_LE: Dòng 1 có giá / giảm giá âm."),
				([("M", "hộp", 1, 1000, 1500)], "GIA_KHONG_HOP_LE: Dòng 1 có giảm giá lớn hơn tiền hàng."),
				([("M", "hộp", 1, 0, 0)], "GIA_KHONG_HOP_LE: Dòng 1 có tiền hàng bằng 0 — phiếu trả NCC phải có tiền trả lớn hơn 0."),
				([("M", "hộp", 2, 1000, 2000)], "GIA_KHONG_HOP_LE: Dòng 1 có tiền hàng bằng 0 — phiếu trả NCC phải có tiền trả lớn hơn 0.")):
			self._loi(self._ghi_dong("TK", ten, dong), "P0001", cau)
		self.assertEqual(frappe.db.count("Purchase Invoice Item", {"parent": ten}), 0)
		self.assertNotIn("error", self._ghi_dong("TK", ten, [("M", "hộp", 2, 1000, 0)]))
		loc = [{"op": "eq", "cot": "id", "gt": ten}]
		# NVBH: ĐỌC được (mig 068 "View supplier returns") — sửa / xoá 0 dòng như RLS; ghi dòng → 42501
		self.assertEqual([r["id"] for r in self._cong("NV", {"bang": "supplier_returns", "select": "id", "loc": loc})["data"]], [ten])
		self.assertEqual(len(self._cong("NV", {"bang": "supplier_return_lines", "select": "id", "loc": [{"op": "eq", "cot": "return_id",
			"gt": ten}]})["data"]), 1)
		self.assertEqual(self._cong("NV", {"bang": "supplier_returns", "hanh_dong": "update", "select": "id", "gia_tri": {"notes": "x"},
			"loc": loc})["data"], [])
		self.assertEqual(self._cong("NV", {"bang": "supplier_returns", "hanh_dong": "delete", "select": "id", "loc": loc})["data"], [])
		self._loi(self._ghi_dong("NV", ten, [("M", "hộp", 1, 1000, 0)]), "42501",
			'new row violates row-level security policy for table "supplier_return_lines"')
		# đổi trạng thái thẳng → USE_RPC; sửa đầu phiếu nháp được (status giữ nguyên + cancel_reason null như màn sửa gửi)
		self._loi(self._cong("TK", {"bang": "supplier_returns", "hanh_dong": "update", "gia_tri": {"status": "completed"}, "loc": loc}), "P0001",
			USE_RPC)
		hom_qua = str(add_days(V.XH.hom_nay(), -1))
		ket = self._cong("TK", {"bang": "supplier_returns", "hanh_dong": "update", "select": "id, discount, vat_override, total, notes, return_date",
			"gia_tri": {"discount": 500, "vat_override": 300, "notes": "n", "status": "draft", "cancel_reason": None, "return_date": hom_qua},
			"loc": loc})
		self.assertEqual(ket["data"][0], {"id": ten, "discount": 500, "vat_override": 300, "total": 1800, "notes": "n", "return_date": hom_qua})
		# đã gửi: chỉ ghi chú; đổi cột khác / dòng / xoá → USE_RPC
		self.assertEqual(self._rpc("TK", "complete_supplier_return", {"p_return_id": ten})["data"], ten)
		self.assertEqual(self._cong("TK", {"bang": "supplier_returns", "hanh_dong": "update", "select": "notes", "gia_tri": {"notes": "ghi chú sau"},
			"loc": loc})["data"], [{"notes": "ghi chú sau"}])
		self._loi(self._cong("TK", {"bang": "supplier_returns", "hanh_dong": "update", "gia_tri": {"discount": 0}, "loc": loc}), "P0001", USE_RPC)
		self._loi(self._cong("TK", {"bang": "supplier_returns", "hanh_dong": "update", "gia_tri": {"status": "draft", "cancel_reason": None},
			"loc": loc}), "P0001", USE_RPC)
		self._loi(self._cong("TK", {"bang": "supplier_returns", "hanh_dong": "delete", "loc": loc}), "P0001", USE_RPC)
		self._loi(self._cong("TK", {"bang": "supplier_return_lines", "hanh_dong": "update", "gia_tri": {"quantity": 99},
			"loc": [{"op": "eq", "cot": "return_id", "gt": ten}]}), "P0001", USE_RPC)
		self._loi(self._ghi_dong("TK", ten, [("M", "hộp", 1, 1000, 0)]), "P0001", USE_RPC)
		# nháp huỷ (dấu huỷ) vẫn xoá được — số cấp lại khi là số cuối (lõi lùi dãy, như mig 240)
		nhap = self._phieu()
		self.assertEqual(self._rpc("TK", "cancel_supplier_return", {"p_return_id": nhap, "p_reason": "x"})["data"], nhap)
		self.assertEqual(self._cong("TK", {"bang": "supplier_returns", "hanh_dong": "delete", "select": "id",
			"loc": [{"op": "eq", "cot": "id", "gt": nhap}]})["data"], [{"id": nhap}])
		self.assertEqual(self._phieu(), nhap)

	def test_doc_cong_sau_gui(self):
		ten = self._phieu(dong=[("M", "hộp", 6, 1000, 600)], discount=400, vat_override=540, reason="damaged", notes="ghi")
		self.assertEqual(self._rpc("TK", "complete_supplier_return", {"p_return_id": ten})["data"], ten)
		r = self._cong("NV", {"bang": "supplier_returns", "select": "*, lines:supplier_return_lines(quantity, unit_price, line_discount, line_total)",
			"loc": [{"op": "eq", "cot": "id", "gt": ten}]})["data"][0]
		no = frappe.db.get_value("NPP Cong No NCC", {"chung_tu": ten}, ["name", "so_tien", "ghi_chu", "so_hd_ncc", "trang_thai"], as_dict=True)
		# tiền đổi dấu về dương: (6 × 1.000 − 600) + thuế gõ tay 540 − chi phí trả hàng 400 = 5.540; nợ −5.540
		self.assertEqual({k: r[k] for k in ("status", "subtotal", "vat", "total", "discount", "vat_override", "warehouse_zone", "reason", "notes",
			"stock_entry_id", "payable_credit_id", "return_seq", "completed_by", "created_by")},
			{"status": "completed", "subtotal": 5400, "vat": 540, "total": 5540, "discount": 400, "vat_override": 540, "warehouse_zone": "date",
			"reason": "damaged", "notes": "ghi", "stock_entry_id": ten, "payable_credit_id": no.name, "return_seq": int(ten.split("-")[1]),
			"completed_by": self.ma["u:TK"], "created_by": self.ma["u:TK"]})
		self.assertEqual(r["lines"], [{"quantity": 6, "unit_price": 1000, "line_discount": 600, "line_total": 5400}])
		self.assertEqual((flt(no.so_tien), no.ghi_chu, no.so_hd_ncc, no.trang_thai), (-5540, f"Hoàn trả NCC — phiếu {ten}", ten, "open"))
		self.assertEqual((self._ton("L-B2"), self._ton("L-B1")), (0, 9))  # hạn cũ trước: L-B2 5 rồi L-B1 1

	def _dv(self, sp: str) -> str:
		"""Đơn vị cơ sở in trong câu thiếu tồn = `Item.stock_uom` (bản ghi UOM của site — "hộp" có thể là "Hop")."""
		return frappe.db.get_value("Item", self.ma[sp], "stock_uom")

	def test_gui_thieu_ton_nhieu_dong(self):
		"""Dòng 2 thấy phần dòng 1 đã lấy; câu báo DÒNG ĐẦU thiếu với "cần" cả dòng, "còn" vùng phiếu SAU khi đã trừ; không ghi gì."""
		ten = self._phieu("KT", dong=[("M", "hộp", 12, 1000, 0), ("M", "hộp", 5, 1000, 0)])
		self._loi(self._rpc("KT", "complete_supplier_return", {"p_return_id": ten}), "P0001",
			f"INSUFFICIENT_STOCK | Sữa hộp ({self._dv('M')}): cần 5, kho hàng date còn 0.000000, kho hàng bán còn 100.000000")
		self.assertEqual((frappe.db.get_value("Purchase Invoice", ten, "docstatus"), self._ton("L-B1"), self._ton("L-B2")), (0, 10, 5))
		# lô TẮT (đóng) không được chọn, không tính vào "còn"
		frappe.db.set_value("Batch", "L-B2", "disabled", 1)
		ten2 = self._phieu("KT", dong=[("M", "hộp", 11, 1000, 0)])
		self._loi(self._rpc("KT", "complete_supplier_return", {"p_return_id": ten2}), "P0001",
			f"INSUFFICIENT_STOCK | Sữa hộp ({self._dv('M')}): cần 11, kho hàng date còn 0.000000, kho hàng bán còn 100.000000")
		ten3 = self._phieu("KT", dong=[("M", "hộp", 6, 1000, 0)], warehouse_zone="sale")
		self.assertEqual(self._rpc("KT", "complete_supplier_return", {"p_return_id": ten3})["data"], ten3)
		self.assertEqual((self._ton("L-B3"), self._ton("L-B2")), (94, 5))
		# mặt hàng không có dòng lô nào ở hai kho → "còn 0" (không phải 0.000000)
		ten4 = self._phieu("KT", dong=[("N", "túi", 2, 1000, 0)])
		self._loi(self._rpc("KT", "complete_supplier_return", {"p_return_id": ten4}), "P0001",
			f"INSUFFICIENT_STOCK | Kẹo ({self._dv('N')}): cần 2, kho hàng date còn 0, kho hàng bán còn 0")

	def test_gui_khoa_bin_cau_dau(self):
		"""Câu ĐẦU của thân hàm (sau bước chuẩn bị) là khoá Bin, câu kế là khoá PI `FOR UPDATE` — lượt song song xếp hàng ở khoá rồi thấy
		docstatus 1 (idempotent, không xuất kho hai lần)."""
		ten = self._phieu(dong=[("M", "hộp", 2, 1000, 0)])
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
			self.assertEqual(self._rpc("TK", "complete_supplier_return", {"p_return_id": ten})["data"], ten)
		than = cau[moc[0]:]
		self.assertIn("`tabBin`", than[0])
		self.assertIn("FOR UPDATE", than[0])
		self.assertIn("`tabPurchase Invoice`", than[1])
		self.assertIn("FOR UPDATE", than[1])
		self.assertEqual(self._rpc("TK", "complete_supplier_return", {"p_return_id": ten})["data"], ten)
		self.assertEqual((self._ton("L-B2"), frappe.db.count("NPP Cong No NCC", {"chung_tu": ten})), (3, 1))

	def test_huy_da_can_tru_va_mo_lai_lo(self):
		ten = self._phieu(dong=[("M", "hộp", 6, 1000, 0)])
		self._rpc("TK", "complete_supplier_return", {"p_return_id": ten})
		from nppsale.su_kien import cong_no_ncc as N

		goc = N.gia_tri_pi
		with patch.object(N, "gia_tri_pi", lambda t: {**goc(t), "da_tra": -3000.0}):
			self._loi(self._rpc("TK", "cancel_supplier_return", {"p_return_id": ten, "p_reason": "x"}), "P0001",
				"DA_CAN_TRU: Khoản giảm công nợ của phiếu này đã được cấn trừ (-3000). Gỡ phần cấn trừ trước rồi mới huỷ phiếu.")
		self.assertEqual((frappe.db.get_value("Purchase Invoice", ten, "docstatus"), self._ton("L-B2"), self.repost), (1, 0, []))
		frappe.db.set_value("Batch", "L-B2", "disabled", 1)  # lô đã đóng → huỷ MỞ LẠI (mig 235)
		self.assertEqual(self._rpc("TK", "cancel_supplier_return", {"p_return_id": ten, "p_reason": "gửi nhầm"})["data"], ten)
		self.assertEqual((frappe.db.get_value("Purchase Invoice", ten, ["docstatus", "npp_ly_do_huy"]), self._ton("L-B2"), self._ton("L-B1"),
			frappe.db.get_value("Batch", "L-B2", "disabled"), self._so_no(ten), self.repost), ((2, "gửi nhầm"), 5, 10, 0, None, [1]))

	def test_khoi_phuc_loi_khong_nghiep_vu_nem_ra(self):
		"""Gửi lại hỏng vì lỗi KHÔNG phải P0001 (vai, hệ thống) → ném ra, lùi cả lượt (không để lại tờ amend nháp); P0001 → tờ amend ở Nháp + lý do."""
		ten = self._phieu(dong=[("M", "hộp", 2, 1000, 0)])
		self._rpc("TK", "complete_supplier_return", {"p_return_id": ten})
		self._rpc("TK", "cancel_supplier_return", {"p_return_id": ten, "p_reason": "x"})
		with patch("nppsale.rpc.tra_ncc.gui", side_effect=NppLoi("LOI_KHAC: hỏng", code="42501", http=403)):
			self._loi(self._rpc("TK", "khoi_phuc_phieu_tra_ncc", {"p_return_id": ten}), "42501", "LOI_KHAC: hỏng")
		self.assertFalse(frappe.db.exists("Purchase Invoice", {"amended_from": ten}))
		with patch("nppsale.rpc.tra_ncc.gui", side_effect=NppLoi("THIEU: thiếu")):
			kq = self._rpc("TK", "khoi_phuc_phieu_tra_ncc", {"p_return_id": ten})["data"]
		moi = frappe.db.get_value("Purchase Invoice", {"amended_from": ten}, "name")
		self.assertEqual(kq, {"id": moi, "trang_thai": "draft", "da_khoi_phuc": True, "ly_do": "THIEU: thiếu"})
		self.assertEqual(frappe.db.get_value("Purchase Invoice", moi, ["docstatus", "npp_huy_luc", "is_return", "npp_loai"]), (0, None, 1, "tra_ncc"))
		# id ổn định: gọi lại bằng tên CŨ → làm trên tờ cuối (amend nháp) → gửi được
		self.assertEqual(self._rpc("TK", "complete_supplier_return", {"p_return_id": ten})["data"], moi)
		self.assertEqual(self._rpc("TK", "khoi_phuc_phieu_tra_ncc", {"p_return_id": ten})["data"],
			{"id": moi, "trang_thai": "completed", "da_khoi_phuc": False})

	# ------------------------------------------------------------------------------------------------ sua_phieu_tra_ncc (§3.8)
	def _sua(self, nguoi, ten, dong, **them):
		head = {"supplier_id": self.ma["S1"], "return_date": str(V.XH.hom_nay()), "warehouse_zone": "date", "reason": None, "notes": None,
			"discount": 0, "vat_override": None}
		return self._rpc(nguoi, "sua_phieu_tra_ncc", {"p_return_id": ten, "p_head": {**head, **them.pop("head", {})}, "p_lines": self._dong(dong),
			**them})

	def test_sua_phieu_da_gui(self):
		ten = self._phieu(dong=[("M", "hộp", 6, 1000, 0)])
		self._rpc("TK", "complete_supplier_return", {"p_return_id": ten})
		kq = self._sua("TK", ten, [("M", "hộp", 8, 1000, 0)], p_reason="Sửa phiếu từ POS — lập lại")["data"]
		moi = kq["id"]
		self.assertEqual((kq, frappe.db.get_value("Purchase Invoice", moi, "amended_from")), ({"id": moi, "trang_thai": "completed"}, ten))
		self.assertEqual(frappe.db.get_value("Purchase Invoice", ten, ["docstatus", "npp_ly_do_huy"]), (2, "Sửa phiếu từ POS — lập lại"))
		self.assertEqual((self._ton("L-B2"), self._ton("L-B1"), self._so_no(ten), self._so_no(moi)), (0, 7, None, -8000))
		# lý do mặc định của màn sửa
		kq = self._sua("TK", ten, [("M", "hộp", 1, 1000, 0)])["data"]
		self.assertEqual(frappe.db.get_value("Purchase Invoice", moi, "npp_ly_do_huy"), "Sửa phiếu — lập lại")
		self.assertEqual((self._ton("L-B2"), self._ton("L-B1"), self._so_no(kq["id"])), (4, 10, -1000))

	def test_sua_phieu_gui_hong_lui_het(self):
		"""Một giao dịch: gửi lại hỏng → KHÔNG còn trạng thái nửa chừng (nppsale K11: phiếu nằm Nháp, hàng đã về kho, nợ đã xoá)."""
		ten = self._phieu(dong=[("M", "hộp", 6, 1000, 0)])
		self._rpc("TK", "complete_supplier_return", {"p_return_id": ten})
		self._loi(self._sua("TK", ten, [("M", "hộp", 100, 1000, 0)]), "P0001",
			f"INSUFFICIENT_STOCK | Sữa hộp ({self._dv('M')}): cần 100, kho hàng date còn 0.000000, kho hàng bán còn 100.000000")
		self.assertEqual((frappe.db.get_value("Purchase Invoice", ten, "docstatus"), frappe.db.exists("Purchase Invoice", {"amended_from": ten}),
			self._ton("L-B2"), self._ton("L-B1"), self._so_no(ten)), (1, None, 0, 9, -6000))
		self._loi(self._sua("TK", ten, [("M", "hộp", 0, 1000, 0)]), "P0001", "SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0.")
		self.assertEqual(frappe.db.get_value("Purchase Invoice", ten, "docstatus"), 1)

	def test_sua_phieu_chi_luu_nhap_va_nhap(self):
		ten = self._phieu(dong=[("M", "hộp", 6, 1000, 0)])
		self._rpc("TK", "complete_supplier_return", {"p_return_id": ten})
		kq = self._sua("TK", ten, [("M", "hộp", 3, 1000, 0)], p_chi_luu_nhap=True)["data"]
		moi = kq["id"]
		self.assertEqual((kq["trang_thai"], frappe.db.get_value("Purchase Invoice", moi, "docstatus"), self._ton("L-B2"), self._ton("L-B1"),
			self._so_no(ten), self._so_no(moi)), ("draft", 0, 5, 10, None, None))
		self.assertEqual([flt(x) for x in frappe.get_all("Purchase Invoice Item", filters={"parent": moi}, pluck="qty")], [-3])
		# phiếu NHÁP → sửa tại chỗ (không amend) rồi gửi; đổi kho theo đầu phiếu mới
		kq = self._sua("TK", moi, [("M", "hộp", 4, 1000, 0)], head={"warehouse_zone": "sale", "notes": "kho bán"})["data"]
		self.assertEqual((kq, self._ton("L-B3"), self._so_no(moi), frappe.db.get_value("Purchase Invoice", moi, "npp_ghi_chu")),
			({"id": moi, "trang_thai": "completed"}, 96, -4000, "kho bán"))

	def test_sua_phieu_da_huy_vai_khong_co(self):
		ten = self._phieu(dong=[("M", "hộp", 1, 1000, 0)])
		self._loi(self._sua("NV", ten, [("M", "hộp", 1, 1000, 0)]), "42501", FORBIDDEN)
		self._rpc("TK", "cancel_supplier_return", {"p_return_id": ten, "p_reason": "x"})
		self._loi(self._sua("TK", ten, [("M", "hộp", 1, 1000, 0)]), "P0001",
			"PHIEU_DA_HUY: Phiếu trả NCC này đã huỷ — không sửa được. Khôi phục phiếu ở màn chi tiết trước, hoặc lập phiếu mới.")
		self._loi(self._sua("TK", "PTNCC-KHONG-CO", []), "P0001", "PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu trả NCC này.")
