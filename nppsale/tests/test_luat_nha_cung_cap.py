"""Luật thuần NHÀ CUNG CẤP — đếm chứng từ, gộp, xoá (P4 — M8; đặc tả kho_mua §3.13, §3.14, §5.3): python3 -m unittest nppsale.tests.test_luat_nha_cung_cap

Câu lỗi lấy nguyên văn từ thân hàm / trigger nppsale (scratchpad kho_mua/src/gop_nha_cung_cap.sql, xoa_nha_cung_cap.sql, so_chung_tu_ncc.sql,
_ncc_dem_chung_tu.sql, _ncc_chan_xoa.sql, _ncc_xoa_qua_rpc.sql); kết quả đã chạy trên Postgres tham chiếu ở tệp vàng du_lieu/kho_mua_mau.json (V32, V72,
V73, V84); `concat_ws` / `format` / `btrim` đo trên PG16 (btrim một tham số chỉ bỏ dấu cách).
"""
import unittest
from datetime import date

from nppsale.cong.loi import NppLoi
from nppsale.luat import kho_mua as K
from nppsale.luat import nha_cung_cap as L

HOM_NAY = date(2026, 11, 17)


class TestCau(unittest.TestCase):
	def test_cau_nguyen_van(self):
		self.assertEqual(L.GOP_NCC_TRUNG, "GOP_NCC_TRUNG: chọn hai nhà cung cấp khác nhau")
		self.assertEqual(L.KHONG_TIM_THAY_TU, "KHONG_TIM_THAY_NCC: nhà cung cấp cần gộp không còn / không thuộc NPP")
		self.assertEqual(L.KHONG_TIM_THAY_VAO, "KHONG_TIM_THAY_NCC: nhà cung cấp giữ lại không còn / không thuộc NPP")
		self.assertEqual(L.KHONG_TIM_THAY_XOA, "KHONG_TIM_THAY_NCC: nhà cung cấp không còn / không thuộc NPP")
		self.assertEqual(L.NCC_XOA_QUA_RPC, "NCC_XOA_QUA_RPC: xoá nhà cung cấp ở màn chi tiết NCC (chỉ Chủ NPP).")
		# so_chung_tu_ncc: chỉ MÃ (RAISE EXCEPTION 'KHONG_DU_QUYEN' / 'KHONG_TIM_THAY_NCC')
		self.assertEqual((L.KHONG_DU_QUYEN_DEM, L.KHONG_TIM_THAY_DEM), ("KHONG_DU_QUYEN", "KHONG_TIM_THAY_NCC"))
		e = L.loi_co_chung_tu("NCC Một", "2 dòng công nợ NCC")
		self.assertIsInstance(e, NppLoi)
		self.assertEqual((e.ma, e.code), ('NCC_CO_CHUNG_TU: không xoá được nhà cung cấp "NCC Một" — đã có 2 dòng công nợ NCC. Dùng "Ngừng hợp tác" hoặc '
			'"Gộp vào NCC khác".', "P0001"))

	def test_cua_vai(self):
		"""mig 232 / 233: gộp owner / manager / accountant (P0001 — thủ kho, NVBH, tài khoản khoá bị); xoá chỉ owner; đếm chứng từ 4 vai mua hàng (câu
		chỉ mã)."""
		for vai in ("owner", "manager", "accountant"):
			self.assertIsNone(K.loi_vai("gop_nha_cung_cap", vai))
		for vai in ("warehouse", "sales", None, ""):
			e = K.loi_vai("gop_nha_cung_cap", vai)
			self.assertEqual((e.ma, e.code), ("KHONG_DU_QUYEN: chỉ Chủ NPP / Quản lý / Kế toán được gộp nhà cung cấp", "P0001"))
		self.assertIsNone(K.loi_vai("xoa_nha_cung_cap", "owner"))
		for vai in ("manager", "accountant", "warehouse", "sales", None):
			e = K.loi_vai("xoa_nha_cung_cap", vai)
			self.assertEqual((e.ma, e.code), ("KHONG_DU_QUYEN_XOA_NCC: chỉ Chủ NPP được xoá nhà cung cấp", "P0001"))
		for vai in ("owner", "manager", "accountant", "warehouse"):
			self.assertIsNone(K.loi_vai("so_chung_tu_ncc", vai))
		for vai in ("sales", None):
			self.assertEqual(K.loi_vai("so_chung_tu_ncc", vai).ma, "KHONG_DU_QUYEN")
		# không có cửa gọi nội bộ
		self.assertIsNotNone(K.loi_vai("gop_nha_cung_cap", "warehouse", noi_bo=True))


class TestDemChungTu(unittest.TestCase):
	def test_thu_tu_va_nhan(self):
		"""V32 (đã chạy): thứ tự `ORDER BY` tên bảng, tên cột; nhãn tiếng Việt, `supplier_payments` tên thô (§7.3 điểm 25); bảng 0 dòng không vào."""
		r = L.dem_chung_tu({"supplier_returns": 1, "supplier_payments": 2, "stock_entries": 3, "purchase_invoices": 2, "products": 1, "payables": 5,
			"purchase_orders": 0})
		self.assertEqual(r, {"tong": 14, "chi_tiet": [
			{"bang": "payables", "cot": "supplier_id", "so": 5, "nhan": "dòng công nợ NCC"},
			{"bang": "products", "cot": "primary_supplier_id", "so": 1, "nhan": "mặt hàng"},
			{"bang": "purchase_invoices", "cot": "supplier_id", "so": 2, "nhan": "phiếu nhập"},
			{"bang": "stock_entries", "cot": "supplier_id", "so": 3, "nhan": "phiếu kho"},
			{"bang": "supplier_payments", "cot": "supplier_id", "so": 2, "nhan": "supplier_payments"},
			{"bang": "supplier_returns", "cot": "supplier_id", "so": 1, "nhan": "phiếu trả NCC"}]})
		self.assertEqual(L.dem_chung_tu({}), {"tong": 0, "chi_tiet": []})
		r = L.dem_chung_tu({"purchase_orders": 2})
		self.assertEqual(r["chi_tiet"], [{"bang": "purchase_orders", "cot": "supplier_id", "so": 2, "nhan": "đơn đặt hàng NCC"}])

	def test_mo_ta(self):
		"""V73: xoá qua RPC bỏ mặt hàng ("2 dòng công nợ NCC"); xoá thẳng (trigger) liệt kê cả mặt hàng ("2 dòng công nợ NCC, 1 mặt hàng"); chỉ còn mặt
		hàng → không có gì để chặn ở RPC."""
		ct = L.dem_chung_tu({"payables": 2, "products": 1})["chi_tiet"]
		self.assertEqual(L.mo_ta_chung_tu(ct, bo_mat_hang=True), "2 dòng công nợ NCC")
		self.assertEqual(L.mo_ta_chung_tu(ct, bo_mat_hang=False), "2 dòng công nợ NCC, 1 mặt hàng")
		ct = L.dem_chung_tu({"products": 2})["chi_tiet"]
		self.assertIsNone(L.mo_ta_chung_tu(ct, bo_mat_hang=True))
		self.assertEqual(L.mo_ta_chung_tu(ct, bo_mat_hang=False), "2 mặt hàng")
		self.assertIsNone(L.mo_ta_chung_tu([], bo_mat_hang=False))
		ct = L.dem_chung_tu({"supplier_payments": 1, "stock_entries": 2, "payables": 1})["chi_tiet"]
		self.assertEqual(L.mo_ta_chung_tu(ct, bo_mat_hang=True), "1 dòng công nợ NCC, 2 phiếu kho, 1 supplier_payments")


class TestGop(unittest.TestCase):
	def test_ghi_chu_dau_ky(self):
		"""Bước 0 (V72): ghi chú cũ trống / toàn dấu cách → chỉ câu gộp; có chữ → nối ' · '; btrim chỉ bỏ dấu cách (tab giữ)."""
		self.assertEqual(L.ghi_chu_dau_ky_gop("  ", "NCC Hai", HOM_NAY), "Nợ đầu kỳ của NCC NCC Hai (gộp ngày 17/11/2026)")
		self.assertEqual(L.ghi_chu_dau_ky_gop(None, "NCC Hai", HOM_NAY), "Nợ đầu kỳ của NCC NCC Hai (gộp ngày 17/11/2026)")
		self.assertEqual(L.ghi_chu_dau_ky_gop(" Đầu kỳ S2 ", "NCC Hai", HOM_NAY), "Đầu kỳ S2 · Nợ đầu kỳ của NCC NCC Hai (gộp ngày 17/11/2026)")
		self.assertEqual(L.ghi_chu_dau_ky_gop("\tx ", "B", date(2026, 1, 5)), "\tx · Nợ đầu kỳ của NCC B (gộp ngày 05/01/2026)")

	def test_ho_so(self):
		"""Bước 3 (V72 — đã chạy): ô trống của NCC giữ lại (sau btrim) lấy NGUYÊN chữ của NCC bị gộp, ô còn chữ giữ bản đã trim; ngày ĐKKD / hạn mức
		COALESCE; ghi chú 'ghi chú S1\\nGộp từ NCC NCC Hai (NCC02) ngày …\\nGhi chú NCC cũ: NCC hai cũ'."""
		vao = {"name": "NCC Một", "code": "NCC01", "phone": "0901", "email": "  ", "tax_code": None, "notes": "ghi chú S1", "address": "  Hà Nội ",
			"business_license_date": None, "credit_limit": None}
		tu = {"name": "NCC Hai", "code": "NCC02", "phone": "0902", "email": "hai@ncc", "tax_code": "0101", "notes": "NCC hai cũ", "address": "HCM",
			"bank_name": " VCB ", "business_license_date": date(2020, 1, 2), "credit_limit": 5000000}
		r = L.ho_so_gop(vao, tu, HOM_NAY)
		self.assertEqual((r["phone"], r["email"], r["tax_code"], r["address"], r["bank_name"]), ("0901", "hai@ncc", "0101", "Hà Nội", " VCB "))
		self.assertEqual((r["business_license_date"], r["credit_limit"]), (date(2020, 1, 2), 5000000))
		self.assertEqual(r["notes"], "ghi chú S1\nGộp từ NCC NCC Hai (NCC02) ngày 17/11/2026.\nGhi chú NCC cũ: NCC hai cũ")
		self.assertEqual(set(r), set(L.COT_CHU) | set(L.COT_COALESCE) | {"notes"})
		# NCC giữ lại có hạn mức 0 / ngày → giữ (COALESCE, không phải "trống")
		r = L.ho_so_gop({**vao, "credit_limit": 0, "business_license_date": date(2021, 3, 4)}, tu, HOM_NAY)
		self.assertEqual((r["credit_limit"], r["business_license_date"]), (0, date(2021, 3, 4)))
		# không mã, không ghi chú cũ hai bên
		r = L.ho_so_gop({"name": "A", "notes": " "}, {"name": "NCC Ba", "code": None, "notes": "  "}, HOM_NAY)
		self.assertEqual(r["notes"], "Gộp từ NCC NCC Ba ngày 17/11/2026.")
		r = L.ho_so_gop({"name": "A", "notes": None}, {"name": "B", "code": "", "notes": " cũ "}, date(2026, 2, 3))
		self.assertEqual(r["notes"], "Gộp từ NCC B () ngày 03/02/2026.\nGhi chú NCC cũ: cũ")


class TestXoa(unittest.TestCase):
	def test_tham_so_xoa_hang(self):
		"""`p_xoa_hang boolean DEFAULT false`: không truyền → false; NULL tường minh → như true (`IF NOT NULL OR …` không vào nhánh gỡ)."""
		self.assertFalse(L.xoa_hang_cua(None, co_truyen=False))
		self.assertTrue(L.xoa_hang_cua(None, co_truyen=True))
		self.assertTrue(L.xoa_hang_cua(True, co_truyen=True))
		self.assertFalse(L.xoa_hang_cua(False, co_truyen=True))

	def test_nhanh_mat_hang(self):
		"""V73 / V84: không xoá hàng → gỡ NCC; có chứng từ → ngừng bán + gỡ; không → xoá."""
		self.assertEqual(L.nhanh_mat_hang(False, True), "go")
		self.assertEqual(L.nhanh_mat_hang(False, False), "go")
		self.assertEqual(L.nhanh_mat_hang(True, True), "ngung_ban")
		self.assertEqual(L.nhanh_mat_hang(True, False), "xoa")


if __name__ == "__main__":
	unittest.main()
