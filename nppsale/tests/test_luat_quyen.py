"""Kiểm quyền máy chủ (nppsale.luat.quyen) — cùng thứ tự với public.user_has_permission (mig 166)."""
import unittest

from nppsale.luat.quyen import DONG_VAI_GIEO_SAN, co_quyen, tach_khoa, xem_duoc_gia_von

VAI = {k: True for k in DONG_VAI_GIEO_SAN}


class TestQuyen(unittest.TestCase):
	def test_tach_khoa_o_dau_cham_cuoi(self):
		self.assertEqual(tach_khoa("customers.analytics.read"), ("customers.analytics", "read"))
		self.assertEqual(tach_khoa("orders.update"), ("orders", "update"))
		for sai in ("orders", ".read", "orders.", ""):
			self.assertIsNone(tach_khoa(sai))

	def test_quyen_rieng_thang_ca_chu_npp(self):
		self.assertFalse(co_quyen("owner", "orders.delete", {"orders.delete": False}, VAI))
		self.assertTrue(co_quyen("sales", "inventory.approve", {"inventory.approve": True}, VAI))

	def test_chu_npp_luon_duoc_khi_khong_co_quyen_rieng(self):
		self.assertTrue(co_quyen("owner", "bat.ky.khoa.nao", None, {}))

	def test_dong_vai_va_mac_dinh_khong(self):
		self.assertTrue(co_quyen("manager", "orders.approve", None, VAI))
		self.assertFalse(co_quyen("sales", "orders.approve", None, VAI))
		self.assertFalse(co_quyen("sales", "orders.update", None, {("sales", "orders", "update"): False}))
		self.assertFalse(co_quyen("manager", "orders", None, VAI))  # khoá không có hành động

	def test_bo_gieo_san_dung_mig_202(self):
		"""= _gieo_quyen_mac_dinh đang chạy (mig 202): NVBH không còn receivables.create (không lập phiếu thu)."""
		self.assertEqual(sorted(DONG_VAI_GIEO_SAN), sorted([
			("manager", "orders", "approve"), ("manager", "orders", "update"), ("manager", "returns", "approve"),
			("manager", "inventory", "approve"), ("sales", "orders", "update"), ("accountant", "receivables", "create"),
			("accountant", "receivables", "update")]))
		self.assertFalse(co_quyen("sales", "receivables.create", None, VAI))

	def test_khong_ho_so_khong_duoc(self):
		self.assertFalse(co_quyen(None, "orders.read", {"orders.read": True}, VAI))


	def test_xem_gia_von_nhu_giao_dien(self):
		"""= `xemDuocGiaVon` (src/lib/permissions.ts): chủ luôn được; quyền riêng inventory.cost.read thắng; mặc định QL / KT / thủ kho
		được, NVBH / lái xe không; dòng quyền vai của ô inventory.cost thêm / bớt hành động — ô còn hành động là được."""
		for vai in ("owner", "manager", "accountant", "warehouse"):
			self.assertTrue(xem_duoc_gia_von(vai, None, {}), vai)
		for vai in ("sales", "driver", None, ""):
			self.assertFalse(xem_duoc_gia_von(vai, None, {}), vai)
		self.assertFalse(xem_duoc_gia_von("manager", {"inventory.cost.read": False}, {}))
		self.assertTrue(xem_duoc_gia_von("sales", {"inventory.cost.read": True}, {}))
		self.assertTrue(xem_duoc_gia_von("owner", {"inventory.cost.read": False}, {}))  # chủ: giao diện trả true trước quyền riêng
		self.assertFalse(xem_duoc_gia_von("sales", {"inventory.read": True}, {("sales", "inventory", "read"): True}))  # mô-đun cha không mở
		self.assertTrue(xem_duoc_gia_von("sales", None, {("sales", "inventory.cost", "read"): True}))
		self.assertFalse(xem_duoc_gia_von("accountant", None, {("accountant", "inventory.cost", "read"): False}))
		# thủ kho mặc định có 4 hành động: bỏ một vẫn còn ô; bỏ hết mới mất
		self.assertTrue(xem_duoc_gia_von("warehouse", None, {("warehouse", "inventory.cost", "read"): False}))
		self.assertFalse(xem_duoc_gia_von("warehouse", None, {("warehouse", "inventory.cost", a): False
			for a in ("read", "create", "update", "export")}))
		# dòng của vai khác không đụng
		self.assertFalse(xem_duoc_gia_von("sales", None, {("manager", "inventory.cost", "read"): True}))


if __name__ == "__main__":
	unittest.main()
