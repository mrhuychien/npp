"""Kiểm quyền máy chủ (nppsale.luat.quyen) — cùng thứ tự với public.user_has_permission (mig 166)."""
import unittest

from nppsale.luat.quyen import DONG_VAI_GIEO_SAN, co_quyen, tach_khoa

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

	def test_khong_ho_so_khong_duoc(self):
		self.assertFalse(co_quyen(None, "orders.read", {"orders.read": True}, VAI))


if __name__ == "__main__":
	unittest.main()
