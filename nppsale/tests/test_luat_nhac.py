"""Luật nhắc định kỳ (thuần) — chép tests/customer-photos.test.ts + tests/tao-khach-moi.test.ts của nppsale:
python3 -m unittest nppsale.tests.test_luat_nhac"""
import unittest

from nppsale.luat.nhac import (
	NGAY,
	NHAC_ANH_HOA_NHIET_NGAY,
	KhachNhacAnh,
	KhachNhacTuyen,
	lap_nhac_anh,
	lap_nhac_tuyen,
	noi_dung_nhac_anh,
	noi_dung_nhac_tuyen,
)

BAY_GIO = 1_790_000_000.0


def anh(id_, so_anh=0, co_vi_tri=False, nhac_luc=None, nv="r1", ten=None):
	return KhachNhacAnh(id_, ten or f"Quán {id_}", so_anh, co_vi_tri, nhac_luc, nv)


def tuyen(id_, tuyen_=None, nv=None, nhac_luc=None):
	return KhachNhacTuyen(id_, f"Khách {id_}", tuyen_, nhac_luc, nv)


class TestNhacAnh(unittest.TestCase):
	def test_du_anh_va_vi_tri_thi_thoi(self):
		self.assertEqual(lap_nhac_anh([anh("a", 3, True)], BAY_GIO)["theo_nv"], [])
		self.assertEqual(lap_nhac_anh([anh("a", 1, True)], BAY_GIO)["theo_nv"], [])  # một tấm kèm vị trí là đủ

	def test_thieu_mot_trong_hai_deu_nhac(self):
		k = lap_nhac_anh([anh("khong-anh", 0, True), anh("khong-gps", 2, False)], BAY_GIO)
		self.assertEqual(sorted(x.id for x in k["theo_nv"][0][1]), ["khong-anh", "khong-gps"])

	def test_gop_theo_nv(self):
		k = lap_nhac_anh([anh("a", nv="r1"), anh("b", nv="r1"), anh("c", nv="r2")], BAY_GIO)
		self.assertEqual([(nv, [x.id for x in ds]) for nv, ds in k["theo_nv"]], [("r1", ["a", "b"]), ("r2", ["c"])])

	def test_chua_ai_phu_trach_tach_rieng(self):
		k = lap_nhac_anh([anh("a", nv=None)], BAY_GIO)
		self.assertEqual((k["theo_nv"], [x.id for x in k["khong_ai"]]), ([], ["a"]))

	def test_ha_nhiet_7_ngay(self):
		k = lap_nhac_anh([anh("a", nhac_luc=BAY_GIO - 2 * NGAY)], BAY_GIO)
		self.assertEqual((k["theo_nv"], k["hoa_nhiet"]), ([], 1))
		k = lap_nhac_anh([anh("a", nhac_luc=BAY_GIO - (NHAC_ANH_HOA_NHIET_NGAY + 1) * NGAY)], BAY_GIO)
		self.assertEqual(len(k["theo_nv"][0][1]), 1)

	def test_noi_dung(self):
		tieu_de, noi_dung = noi_dung_nhac_anh([anh(str(i)) for i in range(1, 6)])
		self.assertIn("5 điểm bán", tieu_de)
		self.assertIn("Quán 1, Quán 2, Quán 3", noi_dung)
		self.assertIn("và 2 điểm nữa", noi_dung)
		self.assertNotIn("điểm nữa", noi_dung_nhac_anh([anh("1")])[1])


class TestNhacTuyen(unittest.TestCase):
	def test_nguoi_nhan(self):
		k = lap_nhac_tuyen([tuyen("a", nv="nv1"), tuyen("b", "T2", nv="nv1"), tuyen("c"), tuyen("d", "  ", nv="nv2")], ["chu"], BAY_GIO)
		self.assertEqual({nv: [x.id for x in ds] for nv, ds in k["theo_nguoi"]}, {"nv1": ["a"], "chu": ["c"], "nv2": ["d"]})

	def test_khong_ai_phu_trach_va_khong_quan_ly(self):
		k = lap_nhac_tuyen([tuyen("a")], [], BAY_GIO)
		self.assertEqual((k["theo_nguoi"], k["khong_nguoi_nhan"]), ([], 1))
		k = lap_nhac_tuyen([tuyen("a")], ["chu", "ql"], BAY_GIO)
		self.assertEqual([nv for nv, _ds in k["theo_nguoi"]], ["chu", "ql"])  # mọi chủ / quản lý cùng nhận

	def test_ha_nhiet_3_ngay(self):
		k = lap_nhac_tuyen([tuyen("a", nv="nv", nhac_luc=BAY_GIO - 1 * NGAY), tuyen("b", nv="nv", nhac_luc=BAY_GIO - 11 * NGAY)], [], BAY_GIO)
		self.assertEqual(k["hoa_nhiet"], 1)
		self.assertEqual([x.id for x in k["theo_nguoi"][0][1]], ["b"])

	def test_noi_dung(self):
		tieu_de, noi_dung = noi_dung_nhac_tuyen([tuyen(str(i)) for i in range(1, 5)])
		self.assertEqual(tieu_de, "4 khách hàng chưa gán tuyến")
		self.assertIn("và 1 khách nữa", noi_dung)


if __name__ == "__main__":
	unittest.main()
