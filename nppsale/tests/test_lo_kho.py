"""Lô + kho cận date (P4 — M5) ngoài kịch bản vàng (đặc tả kho_mua §2.7, §3.20, §4.6, §7.2 #7 / #27, §7.3 điểm 6 / 8 / 20 / 22 / 37) — cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_lo_kho

Dựng trên bộ dữ liệu F của tệp vàng (test_kho_mua_vang.dung_nen_kho), dùng lại các bước của bài vàng (`_buoc`: lo / pn / pn_hoan / pn_huy / nhap_kho /
pk / xuat_le / chuyen / huy_pk / nguong / ra_soat) — lớp bài kế thừa lớp bài vàng nhưng bỏ bài so vàng. Phần kiểm:
- `refresh_warehouse_zones`: MỘT phiếu `CKL-` cho mọi lô cần chuyển (lô tồn 0 / không hạn / hạn xa / đã ở date không chuyển; lô đã tắt còn tồn vẫn
  chuyển), dấu chuyển vùng không người, gọi lại 0; NPP khác / tài khoản khoá / không NPP → ORG_MISMATCH 42501; Administrator không kiểm NPP; mọi vai
  gọi được (§7.3 điểm 22); khoá Bin là câu đầu; việc đêm đăng ký 01:00.
- Cổng `batches` ghi: tạo lô rỗng (kho tạo theo vùng + hạn, ngày SX trống, giá vốn lô rỗng), thứ tự lỗi khi tạo (trigger trước RLS, NOT NULL / CHECK /
  khoá ngoại, mặt hàng không lô, mã trùng); sửa (thứ tự trigger tồn → giá → mặt hàng → cột lõi; gửi lại đúng giá trị; giá lô rỗng; ngày SX; đổi mã =
  `rename_doc` đổi gói lô theo; hạn vào ngưỡng = CKL tự động không dấu; đổi vùng = CKL tay có dấu; HANG_GAN_HAN; lô ảo; vai khác 0 dòng); xoá (Σ tồn,
  23503 khi đã có sổ kho, lô rỗng xoá được, trả dòng trước khi xoá); khuôn ghi kho (đọc → savepoint → khoá Bin là câu đầu).
- §7.3 điểm 8: huỷ phiếu nhập / nhập kho tay mà lô đã bị rà sang kho date (huỷ trước phiếu tự động; phiếu chở lô khác → lập lại phần lô khác cùng giờ;
  lô đã động khác → vẫn chặn).
- Cổng `products` lồng ngược `batches` (§4.6 / §4.9 — màn kiểm kê).
"""
from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, get_datetime, now_datetime

from nppsale.luat import lo_kho as L
from nppsale.luat.tim import khoa_tim_ds
from nppsale.tests import test_kho_mua_vang as V
from nppsale.tests import test_xuat_hang as XH

ORG_MISMATCH = ("42501", "ORG_MISMATCH: không rà kho của đơn vị khác được.")
HANG_GAN_HAN = ("HANG_GAN_HAN: Nuoc ngot (lô {lo}, hạn {han}) chỉ còn dưới 30 ngày nên không chuyển sang kho hàng bán được — hệ thống sẽ tự đẩy về kho "
	"hàng date. Bán hàng gần hạn qua kênh hàng date.")


class TestLoKho(V.TestKhoMuaVang):
	test_kich_ban_vang = None  # bài so vàng chạy ở test_kho_mua_vang

	def setUp(self):
		super().setUp()
		self.st = {"ma": "lk", "nhan": {}}
		self.org = self.ma["org"]

	# ------------------------------------------------------------------------------------------------ gọi
	def _ok(self, **b):
		ket, tv = self._buoc(b, self.st)
		self.assertNotIn("error", ket, f"{b['buoc']} {b.get('nhan')}: {ket.get('error')}")
		return tv

	def _lo_p(self, ma: str, ton: float, han: int | None, vung="sale", sp="@P", gia=8000, nhan_ngay=-30):
		return self._lo({"ma": ma, "sp": sp, "vung": vung, "ton": ton, "gia": gia, "han": han, "nhan_ngay": nhan_ngay})

	def _ton(self, lo: str) -> dict:
		from nppsale.rpc.lo_kho import _ton

		return {k: v for k, v in _ton(lo).items() if abs(v) > 1e-9}

	def _ghi(self, nguoi: str, hanh_dong: str, gia_tri=None, select="*", **loc):
		yc = {"bang": "batches", "hanh_dong": hanh_dong, "select": select, "loc": [{"op": "eq", "cot": c, "gt": v} for c, v in loc.items()]}
		if gia_tri is not None:
			yc["gia_tri"] = gia_tri
		return self._cong(nguoi, yc)

	def _loi(self, ket: dict, ma: str, cau: str):
		self.assertIn("error", ket, f"mong lỗi {cau}")
		self.assertEqual((ket["error"]["code"], ket["error"]["message"]), (ma, cau))

	def _lo_rong(self, nguoi="TK", **g):
		return self._ghi(nguoi, "insert", {"org_id": self.org, "product_id": self.ma["P"], "batch_code": "R1", "expires_at": str(add_days(XH.hom_nay(),
			300)), "qty_initial": 0, "qty_on_hand": 0, **g})

	def _goi_ra_soat(self, nguoi="TK", org=None):
		return self._goi(nguoi, "refresh_warehouse_zones", {"p_org_id": self.org if org is None else org})

	def _lo_ban_thang(self, ma: str, ton: float, han: int, sp="@P", gia=8000):
		"""Lô ở kho bán mà hạn đã trong ngưỡng ("chưa rà soát" — vd ngưỡng vừa tăng): dựng thẳng, không qua luật kho tạo của `_lo`."""
		return V.dung_lo(self.ma, self.cd, {"ma": ma, "sp": sp, "vung": "sale", "ton": ton, "gia": gia, "han": han, "nhan_ngay": -30})

	def _dong_phieu(self, se: str) -> list:
		"""[(lô, kho, SL có dấu)] gói lô chưa huỷ của một phiếu kho — bỏ lô CÓ SẴN trên site."""
		return sorted((lo, k, flt(q)) for lo, k, q in frappe.db.sql("""SELECT e.`batch_no`, e.`warehouse`, SUM(e.`qty`)
			FROM `tabSerial and Batch Bundle` b JOIN `tabSerial and Batch Entry` e ON e.`parent` = b.`name`
			WHERE b.`voucher_type` = 'Stock Entry' AND b.`voucher_no` = %s AND b.`docstatus` = 1 AND b.`is_cancelled` = 0
			GROUP BY e.`batch_no`, e.`warehouse`""", se) if lo not in self.co_san["Batch"])

	def _cau_sau(self, diem: str, fn, commit: list | None = None):
		"""(kết quả, câu SQL ĐẦU ngay sau điểm lưu `diem` — kèm tham số, mọi câu trước điểm lưu). `commit` (list) → bật tạm `frappe.flags.in_test =
		False` với commit thay bằng hàm ghi VỊ TRÍ (số câu đã chạy) vào list ấy, kèm vị trí điểm lưu cuối list — để kiểm thứ tự đọc → commit → điểm lưu."""
		cau, moc = [], []
		goc_sql, goc_sp = frappe.db.sql, frappe.db.savepoint

		def ghi_sql(q, *a, **kw):
			cau.append(" ".join(str(q).split()) + " -- " + str(a[:1] or kw.get("values")))
			return goc_sql(q, *a, **kw)

		def ghi_sp(ten_sp, *a, **kw):
			kq = goc_sp(ten_sp, *a, **kw)
			if ten_sp == diem:
				moc.append(len(cau))
			return kq

		with patch.object(frappe.db, "sql", ghi_sql), patch.object(frappe.db, "savepoint", ghi_sp):
			if commit is None:
				ket = fn()
			else:
				with patch.dict(frappe.flags, {"in_test": False}), patch.object(frappe.db, "commit", lambda *a, **k: commit.append(len(cau))):
					ket = fn()
				commit.append(("diem", moc[0] - 1 if moc else None))
		return ket, (cau[moc[0]] if moc and len(cau) > moc[0] else ""), (cau[:moc[0]] if moc else cau)

	# ------------------------------------------------------------------------------------------------ refresh_warehouse_zones
	def test_ra_soat_mot_phieu_cho_moi_lo(self):
		"""Ngưỡng 100: lô kho bán có hạn trong ngưỡng (hai mặt hàng, kể cả lô ĐÃ TẮT còn tồn — nppsale không lọc `status`) → MỘT phiếu `CKL-`
		`chuyen_date_tu_dong` chở toàn bộ tồn kho bán của từng lô; lô tồn 0 / không hạn / hạn xa / chỉ còn ở kho date không chuyển; dấu chuyển vùng = lúc
		rà, người không ghi (giữ người cũ); NVBH gọi được (không kiểm vai — §7.3 điểm 22); gọi lại → 0, không phiếu mới."""
		self._lo_p("A1", 10, 46)
		self._lo_p("A2", 4, 99, sp="@G", gia=20000)
		self._lo_p("A3", 6, 60)
		frappe.db.set_value("Batch", "A3", "disabled", 1)  # ≈ status 'cancelled' của nppsale
		self._lo_p("A4", 1, 100)  # hạn ĐÚNG BẰNG hôm nay + ngưỡng — vẫn chuyển (`<=`)
		self._lo_p("B0", 0, 50)  # lô rỗng (chưa phát sinh)
		self._lo({"ma": "B1", "sp": "@P", "vung": "sale", "ton": 0, "nhap": 5, "gia": 8000, "han": 50, "nhan_ngay": -30})  # nhập rồi xuất hết
		self._lo_p("B2", 7, 101)  # hạn xa hơn ngưỡng
		self._lo_p("B3", 3, None)  # không hạn
		self._lo_p("B4", 2, 20, vung="date")  # đã ở date
		frappe.db.set_value("Batch", "A1", "npp_chuyen_vung_boi", self.ma["u:TK"])  # người chuyển cũ — rà soát không ghi đè
		self._ok(buoc="nguong", nguoi="MAY_CHU", ngay=100)
		dau = self._ckl_tu_dong()
		self.assertEqual(self._ok(buoc="ra_soat", nguoi="NV"), 4)
		moi = self._ckl_tu_dong() - dau
		self.assertEqual(len(moi), 1)
		se = frappe.get_doc("Stock Entry", next(iter(moi)))
		self.assertEqual((se.purpose, se.npp_loai, se.from_warehouse, se.to_warehouse, se.docstatus, se.owner), ("Material Transfer",
			"chuyen_date_tu_dong", self.cd.kho_ban, self.cd.kho_can_date, 1, self.ma["u:NV"]))
		self.assertTrue(se.name.startswith("CKL-"), se.name)
		self.assertEqual(se.npp_ghi_chu, "Rà soát kho date: lô còn hạn không quá 100 ngày tự chuyển sang kho hàng date")
		kb, kd = self.cd.kho_ban, self.cd.kho_can_date
		self.assertEqual(self._dong_phieu(se.name), sorted([("A1", kb, -10), ("A1", kd, 10), ("A2", kb, -4), ("A2", kd, 4), ("A3", kb, -6),
			("A3", kd, 6), ("A4", kb, -1), ("A4", kd, 1)]))
		for lo in ("A1", "A2", "A3", "A4"):
			x = frappe.db.get_value("Batch", lo, ["npp_chuyen_vung_luc", "npp_chuyen_vung_boi"], as_dict=True)
			self.assertLess(abs((get_datetime(x.npp_chuyen_vung_luc) - now_datetime()).total_seconds()), 300)
			self.assertEqual(x.npp_chuyen_vung_boi, self.ma["u:TK"] if lo == "A1" else None)
		self.assertEqual(frappe.db.get_value("Batch", "A3", "disabled"), 1)  # lô tắt mở tạm để chuyển rồi tắt lại
		for lo in ("B0", "B1", "B2", "B3", "B4"):
			self.assertIsNone(frappe.db.get_value("Batch", lo, "npp_chuyen_vung_luc"), lo)
		self.assertEqual(self._ton("B2"), {kb: 7})
		# giá lô giữ khi chuyển (§7.1 #13): dòng date của A2 = 20.000
		gia = {r["warehouse_zone"]: flt(r["unit_cost"]) for r in self._cong("CHU", {"bang": "batches", "select": "warehouse_zone, unit_cost",
			"loc": [{"op": "eq", "cot": "batch_code", "gt": "A2"}]})["data"]}
		self.assertEqual(gia, {"sale": 20000, "date": 20000})
		self.assertEqual(self._ok(buoc="ra_soat", nguoi="TK"), 0)
		self.assertEqual(self._ckl_tu_dong() - dau, moi)

	def test_ra_soat_npp_va_tai_khoan(self):
		"""Người đăng nhập rà NPP khác / gửi NULL → ORG_MISMATCH 42501 (kể cả chủ NPP); tài khoản bị khoá (user_org_id() NULL) → ORG_MISMATCH; mọi vai
		đang hoạt động gọi được; Administrator (việc nền — "không người" của nppsale) không kiểm NPP: NPP khác → 0, không phiếu."""
		self._lo_ban_thang("A1", 10, 20)
		dau = self._ckl_tu_dong()
		for nguoi in ("CHU", "NV"):
			self._loi(self._goi_ra_soat(nguoi, org="org-khac"), *ORG_MISMATCH)
		self._loi(self._goi("TK", "refresh_warehouse_zones", {}), *ORG_MISMATCH)
		frappe.db.set_value("NPP Nhan Vien", self.ma["u:TK"], "dang_hoat_dong", 0)
		self._loi(self._goi_ra_soat("TK"), *ORG_MISMATCH)
		frappe.db.set_value("NPP Nhan Vien", self.ma["u:TK"], "dang_hoat_dong", 1)
		self.assertEqual(self._ckl_tu_dong(), dau)
		self._ve_admin()
		from nppsale.cong import api

		self.assertEqual(api.rpc(ten="refresh_warehouse_zones", tham_so={"p_org_id": "org-khac"}), {"data": 0, "status": 200})
		self.assertEqual(self._ckl_tu_dong(), dau)
		for nguoi in ("KT", "QL"):  # mọi vai — lượt sau không còn gì
			ket = self._goi_ra_soat(nguoi)
			self.assertNotIn("error", ket, ket)
		self.assertEqual(self._ton("A1"), {self.cd.kho_can_date: 10})

	def test_ra_soat_khoa_bin_cau_dau(self):
		"""Khuôn ghi kho (CFD-05 "chuyển kho date tự động"): câu ĐẦU của thân hàm (sau điểm lưu `npp_cong_rpc`) là khoá Bin `FOR UPDATE` gồm mặt
		hàng của lô cần chuyển — đọc lô ở bước chuẩn bị (trước commit)."""
		self._lo_ban_thang("A1", 10, 20, sp="@G")
		ket, dau, _truoc = self._cau_sau("npp_cong_rpc", lambda: self._goi_ra_soat("TK"))
		self.assertEqual(ket["data"] - self._lo_cu_trong(self._ckl_tu_dong()), 1)
		self.assertIn("`tabBin`", dau)
		self.assertIn("FOR UPDATE", dau)
		self.assertIn(f"'{self.ma['G']}'", dau)  # mặt hàng của lô cần chuyển nằm trong tập khoá

	def test_viec_dem_dang_ky_va_loi(self):
		"""hooks.py: việc đêm 01:00 giờ VN (giờ hệ thống của site) gọi `nppsale.rpc.lo_kho.ra_soat_kho_date`; lỗi → Error Log, không ném (lượt sau chạy
		lại)."""
		from nppsale.rpc import lo_kho

		self.assertIn("nppsale.rpc.lo_kho.ra_soat_kho_date", frappe.get_hooks("scheduler_events")["cron"]["0 1 * * *"])
		with patch("nppsale.rpc.lo_kho.ra_soat", side_effect=frappe.ValidationError("hỏng")):
			self.assertIsNone(lo_kho.ra_soat_kho_date())
		self.assertEqual(self.nhat_ky, ["Rà soát kho date (việc đêm)"])
		self.nhat_ky.clear()

	# ------------------------------------------------------------------------------------------------ cổng batches — tạo
	def test_tao_lo_rong(self):
		"""Màn `/inventory/batches/new`: lô RỖNG → Batch mã = tên, kho tạo theo vùng + hạn (bán mà hạn trong ngưỡng → date; chọn date giữ date), ngày SX
		trống giữ trống, ngày nhận = lúc tạo, giá vốn lô rỗng = `unit_cost`, khoá tìm; trả dòng `.select().single()` có `id` `<lô>::<vùng>`."""
		ket = self._ghi("TK", "insert", {"org_id": self.org, "product_id": self.ma["P"], "batch_code": "R1", "manufactured_at": None,
			"expires_at": str(add_days(XH.hom_nay(), 300)), "location": "Ke 1", "qty_initial": 0, "qty_on_hand": 0, "unit_cost": 7500})
		self.assertNotIn("error", ket, ket)
		r = ket["data"][0]
		self.assertEqual((r["id"], r["batch_code"], r["warehouse_zone"], r["qty_on_hand"], r["qty_initial"], r["unit_cost"], r["location"],
			r["manufactured_at"], r["status"]), ("R1::sale", "R1", "sale", 0, 0, 7500, "Ke 1", None, "available"))
		b = frappe.get_doc("Batch", "R1")
		self.assertEqual((b.item, b.npp_kho_tao, flt(b.npp_gia_von_lo_rong), b.manufacturing_date, b.npp_tim_kd, str(b.expiry_date)), (
			self.ma["P"], self.cd.kho_ban, 7500, None, khoa_tim_ds("R1"), str(add_days(XH.hom_nay(), 300))))
		self.assertLess(abs((get_datetime(b.npp_ngay_nhap) - now_datetime()).total_seconds()), 300)
		# hạn trong ngưỡng (30) → kho cận date ngay lúc tạo; ngày SX gửi lên giữ
		ket = self._ghi("TK", "insert", [{"org_id": self.org, "product_id": self.ma["P"], "batch_code": "R2", "expires_at": str(add_days(XH.hom_nay(),
			30)), "manufactured_at": str(add_days(XH.hom_nay(), -3)), "qty_initial": 0, "qty_on_hand": 0}, {"org_id": self.org, "product_id":
			self.ma["P"], "batch_code": "R3", "expires_at": str(add_days(XH.hom_nay(), 300)), "warehouse_zone": "date", "qty_initial": 0,
			"qty_on_hand": 0}], select="id")
		self.assertEqual([x["id"] for x in ket["data"]], ["R2::date", "R3::date"])
		self.assertEqual((frappe.db.get_value("Batch", "R2", "npp_kho_tao"), str(frappe.db.get_value("Batch", "R2", "manufacturing_date"))),
			(self.cd.kho_can_date, str(add_days(XH.hom_nay(), -3))))
		# không phát sinh sổ kho
		self.assertEqual(self._ton("R1"), {})

	def test_tao_lo_thu_tu_loi(self):
		"""Trigger BEFORE INSERT (lô có tồn) chạy TRƯỚC RLS — NVBH gửi lô có tồn cũng nhận câu trigger; rồi vai / NPP (42501), NOT NULL, CHECK vùng,
		khoá ngoại mặt hàng; bản Frappe thêm: mặt hàng không lô, mã trùng (kể cả trong cùng lệnh), cột lõi tự giữ, cột lạ (PGRST204)."""
		self._loi(self._lo_rong("NV", qty_on_hand=5), "P0001", L.TAO_LO_CO_TON)
		self._loi(self._lo_rong("TK", qty_initial=1), "P0001", L.TAO_LO_CO_TON)
		rls = ("42501", 'new row violates row-level security policy for table "batches"')
		for nguoi in ("NV", "KT", "QL"):
			self._loi(self._lo_rong(nguoi), *rls)
		self._loi(self._lo_rong(org_id="org-khac"), *rls)
		self._loi(self._lo_rong(expires_at=None), "23502", 'null value in column "expires_at" of relation "batches" violates not-null constraint')
		self._loi(self._lo_rong(batch_code=None), "23502", 'null value in column "batch_code" of relation "batches" violates not-null constraint')
		self._loi(self._lo_rong(qty_initial=None), "23502", 'null value in column "qty_initial" of relation "batches" violates not-null constraint')
		self._loi(self._lo_rong(warehouse_zone="kho"), "23514", 'new row for relation "batches" violates check constraint '
			'"batches_warehouse_zone_check"')
		self._loi(self._lo_rong(product_id="KHONG-CO"), "23503", 'insert or update on table "batches" violates foreign key constraint '
			'"batches_product_id_fkey"')
		self._loi(self._lo_rong(product_id=self.ma["X"]), "P0001", L.KHONG_LO)
		self._loi(self._lo_rong(status="cancelled"), "P0001", L.KHONG_SUA_TRUONG)
		self._loi(self._lo_rong(abc=1), "PGRST204", "Could not find the 'abc' column of 'batches' in the schema cache")
		self._loi(self._lo_rong(expires_at="31/12/2026"), "22007", 'invalid input syntax for type date: "31/12/2026"')
		self._lo_p("L-CO", 3, 200)
		self._loi(self._lo_rong(batch_code="L-CO"), "P0001", "LO_TRUNG_MA: Mã lô L-CO đã có trong sổ — chọn mã lô khác.")
		hai = [{"org_id": self.org, "product_id": self.ma["P"], "batch_code": "D1", "expires_at": str(add_days(XH.hom_nay(), 300)), "qty_initial": 0,
			"qty_on_hand": 0}] * 2
		self._loi(self._ghi("TK", "insert", hai), "P0001", "LO_TRUNG_MA: Mã lô D1 đã có trong sổ — chọn mã lô khác.")
		self.assertFalse(frappe.db.exists("Batch", "D1"))  # lời ghi lui trọn
		self.assertFalse(frappe.db.exists("Batch", "R1"))

	# ------------------------------------------------------------------------------------------------ cổng batches — sửa
	def test_sua_thu_tu_trigger_va_vai(self):
		"""Thứ tự trigger mig 170 (tồn → giá khi lô còn tồn → mặt hàng → cột lõi giữ); gửi lại đúng giá trị đang có → được; vai ngoài owner / warehouse →
		0 dòng, không đổi gì; lỗi ép kiểu như PostgREST; hạn NULL → 23502."""
		self._lo_p("L7", 7, 200)
		dong = {"id": "L7::sale"}
		self._loi(self._ghi("TK", "update", {"qty_on_hand": 8, "unit_cost": 9000, "product_id": self.ma["A"]}, **dong), "P0001", L.SUA_TON)
		self._loi(self._ghi("TK", "update", {"unit_cost": 9000, "product_id": self.ma["A"]}, **dong), "P0001", L.SUA_GIA)
		self._loi(self._ghi("TK", "update", {"product_id": self.ma["A"]}, **dong), "P0001", L.DOI_HANG)
		self._loi(self._ghi("TK", "update", {"org_id": "org-khac"}, **dong), "P0001", L.DOI_HANG)
		self._loi(self._ghi("TK", "update", {"status": "cancelled"}, **dong), "P0001", L.KHONG_SUA_TRUONG)
		self._loi(self._ghi("TK", "update", {"zone_moved_at": "2026-11-01T08:00:00+07:00"}, **dong), "P0001", L.KHONG_SUA_TRUONG)
		self._loi(self._ghi("TK", "update", {"qty_on_hand": "abc"}, **dong), "22P02", 'invalid input syntax for type numeric: "abc"')
		self._loi(self._ghi("TK", "update", {"expires_at": None}, **dong), "23502", 'null value in column "expires_at" of relation "batches" '
			'violates not-null constraint')
		hien = self._cong("CHU", {"bang": "batches", "select": "*", "loc": [{"op": "eq", "cot": "id", "gt": "L7::sale"}]})["data"][0]
		gui_lai = {k: hien[k] for k in ("qty_on_hand", "qty_initial", "unit_cost", "product_id", "org_id", "status", "received_at", "batch_code",
			"expires_at", "location")}
		ket = self._ghi("TK", "update", gui_lai, select="id", **dong)
		self.assertEqual(ket.get("data"), [{"id": "L7::sale"}], ket)
		for nguoi in ("NV", "KT", "QL"):
			ket = self._ghi(nguoi, "update", {"location": "Ke 9", "batch_code": "L7-X"}, select="id", **dong)
			self.assertEqual(ket.get("data"), [], (nguoi, ket))
		self.assertEqual((frappe.db.get_value("Batch", "L7", "npp_vi_tri"), frappe.db.exists("Batch", "L7-X")), (None, None))

	def test_sua_gia_ngay_sx_vi_tri(self):
		"""Giá vốn: lô rỗng (Σ mọi kho = 0) → ghi `npp_gia_von_lo_rong` (cổng hiện giá mới); lô có tồn ở kho KIA → chặn (§7.3 điểm 37). Ngày SX / vị trí
		ghi cho cả Batch (cả hai dòng); ngày SX NULL giữ NULL; không có khoá `expires_at` → không chạy luật kho date (V82c)."""
		self._ok(buoc="nhap_kho", nguoi="TK", nhan="IN1", p={"entry_code": "IN-T-1", "warehouse_zone": "sale", "lines": [{"product_id": "@P",
			"unit_name": "Lon", "qty_tx": 10, "conv": 1, "base_qty": 10, "base_cost": 8000, "batch_code": "L1", "expires_at": "@hom_nay+40"}]})
		self._ok(buoc="nguong", nguoi="MAY_CHU", ngay=45)
		ket = self._ghi("TK", "update", {"manufactured_at": str(add_days(XH.hom_nay(), -5)), "location": "Ke 3"}, select="id", id="L1::sale")
		self.assertEqual(ket.get("data"), [{"id": "L1::sale"}], ket)
		self.assertEqual(self._ton("L1"), {self.cd.kho_ban: 10})  # hạn trong ngưỡng nhưng lệnh không có khoá expires_at
		self.assertEqual((str(frappe.db.get_value("Batch", "L1", "manufacturing_date")), frappe.db.get_value("Batch", "L1", "npp_vi_tri")),
			(str(add_days(XH.hom_nay(), -5)), "Ke 3"))
		self._ghi("TK", "update", {"manufactured_at": None}, id="L1::sale")
		self.assertIsNone(frappe.db.get_value("Batch", "L1", "manufacturing_date"))
		self._loi(self._ghi("TK", "update", {"unit_cost": 9000}, id="L1::sale"), "P0001", L.SUA_GIA)
		# lô rỗng: giá ghi được, cổng đọc giá mới
		self._lo_rong()
		ket = self._ghi("TK", "update", {"unit_cost": 9100.5}, select="unit_cost", id="R1::sale")
		self.assertEqual(ket.get("data"), [{"unit_cost": 9100.5}], ket)

	def test_doi_ma_lo(self):
		"""Đổi mã = `rename_doc` ép (PoC 8): gói lô / sổ kho / chứng từ trỏ mã mới (cả hai kho — một Batch), khoá tìm theo mã mới, lời ghi trả dòng mã mới;
		mã mới là lô KHÁC → LO_TRUNG_MA, không đổi gì; mã rỗng → 23502."""
		self._lo_p("L1", 6, 200)
		self._ok(buoc="pk", nguoi="TK", nhan="CK", dau={"org_id": "@org", "entry_code": "CK", "type": "transfer", "warehouse_zone": "sale",
			"dest_warehouse_zone": "date", "status": "draft"}, dong=[{"product_id": "@P", "unit_name": "Lon", "qty_in_base_uom": 2,
			"qty_in_transaction_uom": 2, "conversion_factor_snapshot": 1}])
		self._ok(buoc="chuyen", nguoi="TK", nhan="CK")
		self._lo_p("L2", 1, 200)
		self._loi(self._ghi("TK", "update", {"batch_code": "L2"}, id="L1::sale"), "P0001", "LO_TRUNG_MA: Mã lô L2 đã có trong sổ — chọn mã lô khác.")
		self._loi(self._ghi("TK", "update", {"batch_code": ""}, id="L1::sale"), "23502", 'null value in column "batch_code" of relation "batches" '
			'violates not-null constraint')
		ket = self._ghi("TK", "update", {"batch_code": "L1-MOI", "location": "Ke 5"}, select="id, batch_code, location", id="L1::date")
		self.assertEqual(ket.get("data"), [{"id": "L1-MOI::date", "batch_code": "L1-MOI", "location": "Ke 5"}], ket)
		self.assertFalse(frappe.db.exists("Batch", "L1"))
		self.assertEqual(frappe.db.get_value("Batch", "L1-MOI", "npp_tim_kd"), khoa_tim_ds("L1-MOI"))
		self.assertEqual(self._ton("L1-MOI"), {self.cd.kho_ban: 4, self.cd.kho_can_date: 2})
		self.assertEqual(frappe.db.count("Serial and Batch Entry", {"batch_no": "L1"}), 0)
		ids = sorted(r["id"] for r in self._cong("NV", {"bang": "batches", "select": "id", "loc": [{"op": "like", "cot": "batch_code",
			"gt": "L1%"}]})["data"])
		self.assertEqual(ids, ["L1-MOI::date", "L1-MOI::sale"])
		# xuất lẻ sau khi đổi mã vẫn lấy đúng lô
		self._ok(buoc="pk", nguoi="TK", nhan="XK", dau={"org_id": "@org", "entry_code": "XK", "type": "export", "warehouse_zone": "sale",
			"status": "draft"}, dong=[{"product_id": "@P", "unit_name": "Lon", "qty_in_base_uom": 1, "qty_in_transaction_uom": 1,
			"conversion_factor_snapshot": 1}])
		self._ok(buoc="xuat_le", nguoi="TK", nhan="XK")
		self.assertEqual(self._ton("L1-MOI"), {self.cd.kho_ban: 3, self.cd.kho_can_date: 2})

	def test_sua_han_vao_nguong_chuyen_tu_dong(self):
		"""Khoá `expires_at` (kể cả giá trị cũ) + hạn trong ngưỡng → TOÀN BỘ tồn kho bán sang date bằng `CKL-` `chuyen_date_tu_dong` trong cùng lượt, KHÔNG
		dấu chuyển vùng (trigger không ghi `zone_moved_at`); trả dòng date; hạn xa lại → không tự về bán; lô rỗng → chỉ đổi kho tạo."""
		self._lo_p("L5", 5, 100)
		dau = self._ckl_tu_dong()
		ket = self._ghi("TK", "update", {"expires_at": str(add_days(XH.hom_nay(), 20))}, select="id", id="L5::sale")
		self.assertEqual(ket.get("data"), [{"id": "L5::date"}], ket)
		moi = self._ckl_tu_dong() - dau
		self.assertEqual(len(moi), 1)
		se = frappe.get_doc("Stock Entry", next(iter(moi)))
		self.assertEqual(se.npp_ghi_chu, "Sửa hạn lô L5: còn hạn không quá 30 ngày — tự chuyển sang kho hàng date")
		self.assertEqual(self._dong_phieu(se.name), sorted([("L5", self.cd.kho_ban, -5), ("L5", self.cd.kho_can_date, 5)]))
		self.assertEqual(self._ton("L5"), {self.cd.kho_can_date: 5})
		self.assertIsNone(frappe.db.get_value("Batch", "L5", "npp_chuyen_vung_luc"))
		self._ghi("TK", "update", {"expires_at": str(add_days(XH.hom_nay(), 300))}, id="L5::date")
		self.assertEqual(self._ton("L5"), {self.cd.kho_can_date: 5})
		self.assertEqual(self._ckl_tu_dong() - dau, moi)
		# lô rỗng: chỉ đổi kho tạo — dòng cổng đổi id
		self._lo_rong()
		ket = self._ghi("TK", "update", {"expires_at": str(add_days(XH.hom_nay(), 10))}, select="id", id="R1::sale")
		self.assertEqual(ket.get("data"), [{"id": "R1::date"}], ket)
		self.assertEqual(frappe.db.get_value("Batch", "R1", "npp_kho_tao"), self.cd.kho_can_date)
		self.assertEqual(self._ckl_tu_dong() - dau, moi)

	def test_doi_vung_va_hang_gan_han(self):
		"""`warehouse_zone` đổi trên dòng có tồn → `CKL-` `chuyen_kho` toàn bộ tồn của DÒNG sang kho kia + dấu chuyển vùng (lúc + người); về kho bán khi
		lô gần hạn → HANG_GAN_HAN (không đổi gì); lô ảo → SO_KHO_KHOA mặt hàng không lô; CHECK vùng."""
		self._lo_p("L1", 6, 200)
		ket = self._ghi("TK", "update", {"warehouse_zone": "date"}, select="id", id="L1::sale")
		self.assertEqual(ket.get("data"), [{"id": "L1::date"}], ket)
		self.assertEqual(self._ton("L1"), {self.cd.kho_can_date: 6})
		se = frappe.get_all("Stock Entry", filters={"npp_loai": "chuyen_kho", "docstatus": 1, "npp_ghi_chu": "Đổi vùng lô L1 sang kho hàng date"},
			pluck="name")
		self.assertEqual(len(se), 1)
		x = frappe.db.get_value("Batch", "L1", ["npp_chuyen_vung_luc", "npp_chuyen_vung_boi"], as_dict=True)
		self.assertEqual(x.npp_chuyen_vung_boi, self.ma["u:TK"])
		self.assertIsNotNone(x.npp_chuyen_vung_luc)
		ket = self._ghi("TK", "update", {"warehouse_zone": "sale"}, select="id", id="L1::date")
		self.assertEqual(ket.get("data"), [{"id": "L1::sale"}], ket)
		self.assertEqual(self._ton("L1"), {self.cd.kho_ban: 6})
		self._loi(self._ghi("TK", "update", {"warehouse_zone": "kho"}, id="L1::sale"), "23514", 'new row for relation "batches" violates check '
			'constraint "batches_warehouse_zone_check"')
		self._lo_p("L2", 3, 10, vung="date")
		han = add_days(XH.hom_nay(), 10).strftime("%d/%m/%Y")
		self._loi(self._ghi("TK", "update", {"warehouse_zone": "sale"}, id="L2::date"), "P0001", HANG_GAN_HAN.format(lo="L2", han=han))
		self.assertEqual(self._ton("L2"), {self.cd.kho_can_date: 3})
		# đổi vùng kèm hạn gần: trigger lật về date — không lỗi, không phiếu
		ket = self._ghi("TK", "update", {"warehouse_zone": "sale", "expires_at": str(add_days(XH.hom_nay(), 10))}, select="id", id="L2::date")
		self.assertEqual(ket.get("data"), [{"id": "L2::date"}], ket)
		self._ok(buoc="nhap_kho", nguoi="TK", nhan="IN1", p={"entry_code": "IN-T-1", "warehouse_zone": "sale", "lines": [{"product_id": "@X",
			"unit_name": "cai", "qty_tx": 2, "conv": 1, "base_qty": 2, "base_cost": 1000}]})
		self._loi(self._ghi("TK", "update", {"location": "Ke 1"}, id=f"~{self.ma['X']}::sale"), "P0001", L.KHONG_LO)
		self._loi(self._ghi("TK", "delete", id=f"~{self.ma['X']}::sale"), "P0001", L.KHONG_LO)

	# ------------------------------------------------------------------------------------------------ cổng batches — xoá
	def test_xoa_lo(self):
		"""Xoá: Σ tồn mọi kho ≠ 0 → SO_KHO_KHOA (số `so6`); lô đã có sổ kho (kể cả phiếu nhập đã huỷ — lô "chưa phát sinh") → 23503 khoá ngoại của
		nppsale; lô rỗng chưa phát sinh → xoá Batch, lời xoá trả dòng TRƯỚC khi xoá; vai khác → 0 dòng."""
		self._lo_p("L7", 7, 200)
		self._loi(self._ghi("TK", "delete", id="L7::sale"), "P0001", "SO_KHO_KHOA: lô còn 7.000000 trong kho — không xoá được. Điều chỉnh về 0 qua "
			"phiếu kiểm kê trước.")
		self._ok(buoc="pn", nguoi="TK", nhan="P", dau={"org_id": "@org", "supplier_id": "@S1", "warehouse_zone": "sale", "status": "draft"},
			dong=[{"product_id": "@A", "unit_name": "hộp", "quantity": 2, "unit_price": 10000, "line_discount": 0, "vat_rate": 0,
				"conversion_factor": 1, "sort_order": 1}])
		self._ok(buoc="pn_hoan", nguoi="TK", nhan="P")
		self._ok(buoc="pn_huy", nguoi="TK", nhan="P", ly_do="x")
		lo = self._ten(self.st, "pn:P") + "-001"
		self._loi(self._ghi("TK", "delete", id=f"{lo}::sale"), "23503", 'update or delete on table "batches" violates foreign key constraint '
			'"stock_entry_lines_batch_id_fkey" on table "stock_entry_lines"')
		self.assertTrue(frappe.db.exists("Batch", lo))
		# cổng tự kiểm gói lô, không dựa vào kiểm liên kết của Frappe (app nào thêm bảng gói lô vào `ignore_links_on_delete` thì lô có sổ kho vẫn
		# không xoá được): lô đã có gói lô → 23503 mà KHÔNG gọi tới hàm xoá
		with patch("frappe.delete_doc") as xoa:
			self._loi(self._ghi("TK", "delete", id=f"{lo}::sale"), "23503", 'update or delete on table "batches" violates foreign key constraint '
				'"stock_entry_lines_batch_id_fkey" on table "stock_entry_lines"')
		self.assertFalse(xoa.called)
		self._lo_rong()
		self.assertEqual(self._ghi("NV", "delete", select="id", id="R1::sale").get("data"), [])
		self.assertTrue(frappe.db.exists("Batch", "R1"))
		ket = self._ghi("TK", "delete", select="id, batch_code", id="R1::sale")
		self.assertEqual(ket.get("data"), [{"id": "R1::sale", "batch_code": "R1"}], ket)
		self.assertFalse(frappe.db.exists("Batch", "R1"))

	def test_ghi_kho_khoa_bin_cau_dau(self):
		"""Khuôn ghi kho của cổng (BP §4.4.0): đọc dòng khớp bộ lọc + mặt hàng → COMMIT → điểm lưu `npp_cong_ghi` → câu ĐẦU là khoá Bin `FOR UPDATE`
		gồm mặt hàng của lô (cả lời xoá); tạo lô (không đụng kho) đi đường thường. Commit thật chỉ ngoài bài kiểm (`frappe.flags.in_test`) — bài bật
		tạm cờ ấy với commit đã thay bằng hàm ghi dấu để kiểm THỨ TỰ."""
		self._lo_p("L5", 5, 100, sp="@G")
		commit = []
		ket, dau, truoc = self._cau_sau("npp_cong_ghi", lambda: self._ghi("TK", "update", {"expires_at": str(add_days(XH.hom_nay(), 20))},
			select="id", id="L5::sale"), commit)
		self.assertNotIn("error", ket, ket)
		# đúng MỘT commit, ngay trước câu `savepoint npp_cong_ghi` (sau mọi câu đọc của bước chuẩn bị)
		self.assertEqual(len(commit), 2, commit)
		self.assertEqual(commit[0], commit[1][1], commit)
		self.assertIn("`tabBin`", dau)
		self.assertIn("FOR UPDATE", dau)
		self.assertIn(f"'{self.ma['G']}'", dau)
		self.assertTrue(any("tabSerial and Batch Entry" in q for q in truoc), "đọc dòng khớp phải ở TRƯỚC điểm lưu")
		self._lo_rong()
		ket, dau, _t = self._cau_sau("npp_cong_ghi", lambda: self._ghi("TK", "delete", select="id", id="R1::sale"))
		self.assertEqual(ket.get("data"), [{"id": "R1::sale"}], ket)
		self.assertIn("`tabBin`", dau)
		self.assertIn("FOR UPDATE", dau)
		# tạo lô: không theo khuôn ghi kho (không commit giữa chừng)
		with patch("nppsale.cong.ghi.chuan_bi_kho") as cb:
			self._lo_rong(batch_code="R9")
		self.assertFalse(cb.called)

	# ------------------------------------------------------------------------------------------------ §7.3 điểm 8
	def _pn(self, nhan: str, dong: list):
		self._ok(buoc="pn", nguoi="TK", nhan=nhan, dau={"org_id": "@org", "supplier_id": "@S1", "warehouse_zone": "sale", "status": "draft"},
			dong=[{"product_id": sp, "unit_name": dv, "quantity": sl, "unit_price": gia, "line_discount": 0, "vat_rate": 0, "conversion_factor": 1,
				"sort_order": i} for i, (sp, dv, sl, gia) in enumerate(dong, 1)])
		self._ok(buoc="pn_hoan", nguoi="TK", nhan=nhan)
		return self._ten(self.st, "pn:" + nhan)

	def test_huy_phieu_nhap_sau_ra_soat(self):
		"""Lô D của phiếu nhập (hạn +180) bị rà sang kho date (ngưỡng 200) và không động gì khác → huỷ phiếu nhập được (nppsale: lật cờ vùng nên huỷ
		được): phiếu `CKL-` tự động huỷ trước (hàng về kho bán) rồi phiếu nhập huỷ, lô tắt, không còn tồn."""
		pn = self._pn("P", [("@D", "lon", 12, 5000)])
		lo = pn + "-001"
		self._ok(buoc="nguong", nguoi="MAY_CHU", ngay=200)
		dau = self._ckl_tu_dong()
		self._ok(buoc="ra_soat", nguoi="TK")
		se = next(iter(self._ckl_tu_dong() - dau))
		self.assertEqual(self._ton(lo), {self.cd.kho_can_date: 12})
		self.assertEqual(self._ok(buoc="pn_huy", nguoi="TK", nhan="P", ly_do="nhầm"), "pn:P")
		self.assertEqual((frappe.db.get_value("Stock Entry", se, "docstatus"), frappe.db.get_value("Purchase Invoice", pn, "docstatus")), (2, 2))
		self.assertEqual(self._ton(lo), {})
		self.assertEqual(frappe.db.get_value("Batch", lo, "disabled"), 1)
		self.assertIn(1, self.repost)

	def test_huy_phieu_nhap_ra_soat_cho_lo_khac(self):
		"""Phiếu rà soát chở cả lô KHÁC (lô dựng sẵn L9) → huỷ phiếu rà soát rồi lập lại phần L9 bằng phiếu tự động mới CÙNG giờ ghi sổ (L9 vẫn ở date,
		sổ không đổi vùng hồi tố); L9 đã động sau phiếu rà soát (xuất lẻ từ kho date) → không lập lại được → huỷ phiếu nhập vẫn chặn HANG_DA_XUAT, không
		đổi gì."""
		pn = self._pn("P", [("@D", "lon", 12, 5000)])
		lo = pn + "-001"
		self._lo_p("L9", 4, 150, sp="@G", gia=20000)
		self._ok(buoc="nguong", nguoi="MAY_CHU", ngay=200)
		dau = self._ckl_tu_dong()
		self._ok(buoc="ra_soat", nguoi="TK")
		(se,) = self._ckl_tu_dong() - dau
		goc = frappe.db.get_value("Stock Entry", se, ["posting_date", "posting_time"], as_dict=True)
		# nhánh chặn trước: L9 xuất lẻ 1 từ kho date sau phiếu rà soát
		frappe.db.savepoint("lk_chan")
		self._ok(buoc="pk", nguoi="TK", nhan="XK", dau={"org_id": "@org", "entry_code": "XK", "type": "export", "warehouse_zone": "date",
			"status": "draft"}, dong=[{"product_id": "@G", "unit_name": "Kg", "qty_in_base_uom": 1, "qty_in_transaction_uom": 1,
			"conversion_factor_snapshot": 1}])
		self._ok(buoc="xuat_le", nguoi="TK", nhan="XK")
		ket, _ = self._buoc({"buoc": "pn_huy", "nguoi": "TK", "nhan": "P", "ly_do": "x"}, self.st)
		self.assertEqual(ket["error"]["message"][:13], "HANG_DA_XUAT:")
		self.assertEqual((frappe.db.get_value("Stock Entry", se, "docstatus"), frappe.db.get_value("Purchase Invoice", pn, "docstatus")), (1, 1))
		frappe.db.rollback(save_point="lk_chan")
		# L9 đứng yên → huỷ được, phần L9 lập lại cùng giờ
		self.assertEqual(self._ok(buoc="pn_huy", nguoi="TK", nhan="P", ly_do="x"), "pn:P")
		moi = self._ckl_tu_dong() - dau - {se}
		self.assertEqual(len(moi), 1)
		lai = frappe.get_doc("Stock Entry", next(iter(moi)))
		self.assertEqual((str(lai.posting_date), str(lai.posting_time), lai.npp_ghi_chu), (str(goc.posting_date), str(goc.posting_time),
			frappe.db.get_value("Stock Entry", se, "npp_ghi_chu")))
		self.assertEqual(self._dong_phieu(lai.name), sorted([("L9", self.cd.kho_ban, -4), ("L9", self.cd.kho_can_date, 4)]))
		self.assertEqual((frappe.db.get_value("Stock Entry", se, "docstatus"), self._ton("L9"), self._ton(lo)), (2, {self.cd.kho_can_date: 4}, {}))

	def test_huy_phieu_nhap_lo_da_dong_khac_van_chan(self):
		"""Lô đã rà sang date rồi còn xuất lẻ bớt từ kho date → không phải "chỉ do rà soát" → HANG_DA_XUAT như cũ (chấp nhận chặn), phiếu rà soát giữ."""
		pn = self._pn("P", [("@D", "lon", 12, 5000)])
		self._ok(buoc="nguong", nguoi="MAY_CHU", ngay=200)
		dau = self._ckl_tu_dong()
		self._ok(buoc="ra_soat", nguoi="TK")
		(se,) = self._ckl_tu_dong() - dau
		self._ok(buoc="pk", nguoi="TK", nhan="XK", dau={"org_id": "@org", "entry_code": "XK", "type": "export", "warehouse_zone": "date",
			"status": "draft"}, dong=[{"product_id": "@D", "unit_name": "lon", "qty_in_base_uom": 2, "qty_in_transaction_uom": 2,
			"conversion_factor_snapshot": 1}])
		self._ok(buoc="xuat_le", nguoi="TK", nhan="XK")
		ket, _ = self._buoc({"buoc": "pn_huy", "nguoi": "TK", "nhan": "P", "ly_do": "x"}, self.st)
		self.assertEqual(ket["error"]["message"], "HANG_DA_XUAT: Không huỷ được vì hàng của phiếu đã xuất bớt — Hàng D (nhập 12.000000, còn "
			"0.000000). Lập phiếu trả hàng NCC hoặc phiếu điều chỉnh kho — hoặc bật \"Cho phép bán vượt tồn kho\" (Cài đặt › Đơn vị) để huỷ: phần đã "
			"xuất thành tồn âm.")
		self.assertEqual((frappe.db.get_value("Stock Entry", se, "docstatus"), frappe.db.get_value("Purchase Invoice", pn, "docstatus")), (1, 1))

	def test_huy_nhap_kho_tay_sau_sua_han(self):
		"""Phiếu nhập kho tay `IN-` có lô bị sửa hạn vào ngưỡng (phiếu `CKL-` tự động của lô) → `cancel_stock_entry` huỷ trước phiếu ấy rồi huỷ phiếu
		nhập: `(true, true, 1)`, lô không còn tồn; lô sửa hạn rồi CHUYỂN TAY (`chuyen_kho`) → không hoàn → ALREADY_ISSUED."""
		self._ok(buoc="nhap_kho", nguoi="TK", nhan="IN1", p={"entry_code": "IN-T-1", "warehouse_zone": "sale", "lines": [{"product_id": "@P",
			"unit_name": "Lon", "qty_tx": 10, "conv": 1, "base_qty": 10, "base_cost": 8000, "batch_code": "L1", "expires_at": "@hom_nay+90"}]})
		self._ghi("TK", "update", {"expires_at": str(add_days(XH.hom_nay(), 10))}, id="L1::sale")
		self.assertEqual(self._ton("L1"), {self.cd.kho_can_date: 10})
		self.assertEqual(self._ok(buoc="huy_pk", nguoi="TK", nhan="IN1", ly_do="nhầm"), {"cancelled": True, "reversed": True, "lines_reversed": 1})
		self.assertEqual(self._ton("L1"), {})
		self._ok(buoc="nhap_kho", nguoi="TK", nhan="IN2", p={"entry_code": "IN-T-2", "warehouse_zone": "sale", "lines": [{"product_id": "@P",
			"unit_name": "Lon", "qty_tx": 10, "conv": 1, "base_qty": 10, "base_cost": 8000, "batch_code": "L2", "expires_at": "@hom_nay+90"}]})
		self._ghi("TK", "update", {"warehouse_zone": "date"}, id="L2::sale")
		ket, _ = self._buoc({"buoc": "huy_pk", "nguoi": "TK", "nhan": "IN2", "ly_do": "x"}, self.st)
		self.assertEqual(ket["error"]["message"][:15], "ALREADY_ISSUED:")
		self.assertEqual(self._ton("L2"), {self.cd.kho_can_date: 10})

	# ------------------------------------------------------------------------------------------------ đọc
	def test_san_pham_long_nguoc_lo(self):
		"""Cổng `products` lồng ngược `batches` (§4.6 / §4.9 — màn kiểm kê): `batches(id, batch_code, qty_on_hand)` và `batches!inner(id)` +
		`batches.qty_on_hand > 0`."""
		self._lo_p("L1", 6, 200)
		self._lo_p("L0", 0, 200)
		r = self._cong("TK", {"bang": "products", "select": "id, batches(id, batch_code, qty_on_hand)", "loc": [{"op": "eq", "cot": "id",
			"gt": self.ma["P"]}]})
		self.assertNotIn("error", r, r)
		self.assertEqual(sorted((x["batch_code"], x["qty_on_hand"]) for x in r["data"][0]["batches"]), [("L0", 0), ("L1", 6)])
		r = self._cong("TK", {"bang": "products", "select": "id, batches!inner(id)", "loc": [{"op": "gt", "cot": "batches.qty_on_hand", "gt": 0},
			{"op": "eq", "cot": "id", "gt": self.ma["P"]}]})
		self.assertNotIn("error", r, r)
		self.assertEqual([x["id"] for x in r["data"][0]["batches"]], ["L1::sale"])
