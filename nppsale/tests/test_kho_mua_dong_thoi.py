"""Hai lượt SONG SONG thật (kết nối thứ hai — khuôn TestDamBaoDongDocCoKhoa của test_cong_hddt; PoC 1d: giao dịch REPEATABLE READ chụp ảnh ở câu đọc
thường đầu tiên) cho các luật khoá của P4 sau đợt soát (soát P4):

- xoá phiếu NHÁP qua cổng (phiếu nhập, phiếu trả NCC, phiếu kho; đổi nháp phiếu kho → `cancelled` = xoá) đọc trạng thái CÓ KHOÁ: lượt kia vừa ghi
  sổ / gửi tờ ấy SAU ảnh chụp của lượt xoá → lời xoá báo USE_RPC / SO_KHO_KHOA, tờ còn nguyên. Trước đây đọc thường theo ảnh chụp + `delete_doc` của
  lõi đọc lại bằng đọc thường sau khoá NOWAIT (`delete_doc.py:159–174`) → XOÁ mất tờ đã ghi sổ (sổ kho / sổ cái / công nợ trỏ tờ không còn);
- lời ghi trỏ NCC (nợ NCC lập tay / đầu kỳ ở cổng `payables`, nháp phiếu nhập / trả NCC / phiếu kho) kiểm NCC bằng câu KHOÁ (như KEY SHARE của khoá
  ngoại Postgres): NCC vừa bị gộp / xoá ở lượt kia sau ảnh chụp → 23503, không lập chứng từ trỏ NCC đã mất.

Dữ liệu TỐI THIỂU chèn thẳng bằng kết nối thứ hai rồi commit, dọn sạch cuối mỗi bài — cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_kho_mua_dong_thoi
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager

import frappe
from frappe.tests import IntegrationTestCase

from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong

USE_RPC_PN = "USE_RPC: dùng nút Hoàn thành / Huỷ phiếu / Khôi phục / Lưu sửa"
NC = NguCanh(user="Administrator", vai="owner", bo_qua_rls=True)


class TestDongThoiKhoMua(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()

	def setUp(self):
		frappe.db.rollback()
		self.dong: list[tuple[str, str]] = []  # (bảng, tên) chèn bằng kết nối 2 — dọn cuối bài

	@contextmanager
	def _ket_noi_hai(self):
		chinh = frappe.local.db
		if getattr(self, "_kn2", None) is None:
			frappe.connect(set_admin_as_user=False)
			self._kn2 = frappe.local.db
			self.addCleanup(self._kn2.close)
		frappe.local.db = self._kn2
		try:
			yield
		finally:
			frappe.local.db = chinh

	def _chen(self, bang: str, ten: str, **cot) -> str:
		"""Chèn MỘT dòng tối thiểu bằng kết nối 2 rồi commit (trước ảnh chụp của lượt chính)."""
		cot = {"name": ten, "owner": "Administrator", "modified_by": "Administrator", "idx": 0, **cot}
		with self._ket_noi_hai():
			frappe.db.sql(f"""INSERT INTO `{bang}` ({", ".join(f"`{k}`" for k in cot)}, `creation`, `modified`)
				VALUES ({", ".join(["%s"] * len(cot))}, NOW(6), NOW(6))""", tuple(cot.values()))
			frappe.db.commit()
		self.dong.append((bang, ten))
		return ten

	def _luot_kia(self, cau: str, ts: tuple) -> None:
		"""Lượt kia: một câu ghi + commit (SAU ảnh chụp của lượt chính)."""
		with self._ket_noi_hai():
			frappe.db.sql(cau, ts)
			frappe.db.commit()

	def _don(self):
		frappe.db.rollback()  # nhả khoá của lượt chính trước khi kết nối 2 xoá dòng
		if self.dong:
			with self._ket_noi_hai():
				for bang, ten in reversed(self.dong):
					frappe.db.sql(f"DELETE FROM `{bang}` WHERE `name` = %s", ten)
				frappe.db.commit()
			self.dong = []

	@staticmethod
	def _docstatus(bang: str, ten: str, khoa: bool = False):
		r = frappe.db.sql(f"SELECT `docstatus` FROM `{bang}` WHERE `name` = %s" + (" LOCK IN SHARE MODE" if khoa else ""), ten)
		return r[0][0] if r else None

	def _ghi_so_sau_anh_chup(self, bang: str, ten: str) -> None:
		"""Ảnh chụp của lượt chính thấy NHÁP; lượt kia ghi sổ (docstatus 1) rồi commit; đọc thường của lượt chính vẫn thấy nháp — bài thử đúng ảnh cũ."""
		self.assertEqual(self._docstatus(bang, ten), 0)
		self._luot_kia(f"UPDATE `{bang}` SET `docstatus` = 1 WHERE `name` = %s", (ten,))
		self.assertEqual(self._docstatus(bang, ten), 0, "đọc thường đã thấy bản của kết nối kia — bài không còn thử được ảnh chụp cũ")

	# ------------------------------------------------------------------------------------------------ xoá nháp ↔ ghi sổ song song
	def test_xoa_nhap_phieu_nhap_vua_hoan_thanh(self):
		from nppsale.rpc import phieu_nhap as P

		ten = self._chen("tabPurchase Invoice", f"PN-KN2-{uuid.uuid4().hex[:8]}", docstatus=0, npp_loai="phieu_nhap")
		try:
			self._ghi_so_sau_anh_chup("tabPurchase Invoice", ten)
			with self.assertRaises(NppLoi) as e:
				P.xoa_phieu([ten], NC)
			self.assertEqual(e.exception.ma, USE_RPC_PN)
			self.assertEqual(self._docstatus("tabPurchase Invoice", ten, khoa=True), 1)  # tờ đã ghi sổ còn nguyên
		finally:
			self._don()

	def test_xoa_nhap_phieu_tra_ncc_vua_gui(self):
		from nppsale.luat import tra_ncc as T
		from nppsale.rpc import tra_ncc as R

		ten = self._chen("tabPurchase Invoice", f"PTNCC-KN2-{uuid.uuid4().hex[:8]}", docstatus=0, npp_loai="tra_ncc", is_return=1)
		try:
			self._ghi_so_sau_anh_chup("tabPurchase Invoice", ten)
			with self.assertRaises(NppLoi) as e:
				R.xoa_phieu([ten], NC)
			self.assertEqual(e.exception.ma, T.USE_RPC)
			self.assertEqual(self._docstatus("tabPurchase Invoice", ten, khoa=True), 1)
		finally:
			self._don()

	def test_xoa_nhap_phieu_kho_vua_ghi_so(self):
		"""Xoá nháp và đổi nháp → `cancelled` (= xoá — §7.3 điểm 1) của phiếu xuất lẻ mà lượt kia vừa ghi sổ (`post_stock_issue`)."""
		from nppsale.luat import kho_tay as T
		from nppsale.rpc import kho_tay as KT

		ten = self._chen("tabStock Entry", f"XKL-KN2-{uuid.uuid4().hex[:8]}", docstatus=0, purpose="Material Issue",
			stock_entry_type="Material Issue", npp_loai="xuat_le")
		try:
			self._ghi_so_sau_anh_chup("tabStock Entry", ten)
			with self.assertRaises(NppLoi) as e:
				KT.xoa_phieu([ten], NC)
			self.assertEqual(e.exception.ma, T.loi_xoa_khong_nhap(ten, "posted").ma)
			with self.assertRaises(NppLoi) as e:
				KT.sua_phieu({"status": "cancelled"}, [ten], NC)
			self.assertEqual(e.exception.ma, T.loi_doi_trang_thai("posted", "cancelled").ma)
			self.assertEqual(self._docstatus("tabStock Entry", ten, khoa=True), 1)
		finally:
			self._don()

	# ------------------------------------------------------------------------------------------------ ghi trỏ NCC ↔ gộp / xoá NCC song song
	def test_ghi_tro_ncc_vua_bi_xoa(self):
		from nppsale.rpc import cong_no_ncc as CN
		from nppsale.rpc import kho_tay as KT
		from nppsale.rpc import phieu_nhap as P
		from nppsale.rpc import tra_ncc as R

		ncc = self._chen("tabSupplier", f"NCC-KN2-{uuid.uuid4().hex[:8]}", supplier_name="NCC hai kết nối", docstatus=0)
		try:
			self.assertEqual(frappe.db.sql("SELECT COUNT(*) FROM `tabSupplier` WHERE `name` = %s", ncc)[0][0], 1)  # ảnh chụp có NCC
			self._luot_kia("DELETE FROM `tabSupplier` WHERE `name` = %s", (ncc,))  # gộp / xoá NCC ở lượt kia commit
			self.assertEqual(frappe.db.sql("SELECT COUNT(*) FROM `tabSupplier` WHERE `name` = %s", ncc)[0][0], 1)  # đọc thường: ảnh cũ
			for ten, ham, g in (
					("payables", CN.them_no, {"supplier_id": ncc, "amount": 1000, "paid": 0, "status": "open", "opening_balance": False}),
					("purchase_invoices", P.them_phieu, {"supplier_id": ncc, "status": "draft"}),
					("supplier_returns", R.them_phieu, {"supplier_id": ncc, "status": "draft"}),
					("stock_entries", KT.them_phieu, {"supplier_id": ncc, "status": "draft", "type": "import", "warehouse_zone": "sale"})):
				with self.assertRaises(LoiCong, msg=ten) as e:
					ham([g], NC)
				self.assertEqual((e.exception.ma, f"{ten}_supplier_id_fkey" in e.exception.thong_diep), ("23503", True), ten)
		finally:
			self._don()
