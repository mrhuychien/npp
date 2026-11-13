"""Luật người giữ nợ (nppsale/luat/giu_no.py) khớp từng dòng bảng chân trị sinh từ trigger thật `_cong_no_giu_ve_npp` của nppsale
(tools/vang_giu_no.py): 80 tổ hợp đổi người + 4 lượt lập mới. Thuần Python — chạy: python3 -m unittest nppsale.tests.test_luat_giu_no"""
from __future__ import annotations

import json
import os
import unittest

from nppsale.luat.giu_no import GiuNo, khi_doi_nguoi, khi_lap

VANG = os.path.join(os.path.dirname(__file__), "du_lieu", "giu_no_mau.json")


class TestLuatGiuNo(unittest.TestCase):
	def test_bang_chan_tri_nhu_trigger_nppsale(self):
		with open(VANG, encoding="utf-8") as f:
			dong = json.load(f)["dong"]
		self.assertEqual(len(dong), 84)

		def da_nghi(nv):
			return nv == "N"

		sai = []
		for x in dong:
			if x["loai"] == "doi":
				cu = GiuNo(x["cu"]["nv"], "luc_cu" if x["cu"]["ve"] else None, x["cu"]["giao"])
				kq = khi_doi_nguoi(cu, x["moi"], da_nghi, "bay_gio")
			else:
				kq = khi_lap(x["moi"], da_nghi, "bay_gio")
			if (kq.nv, kq.ve_npp is not None, kq.giao) != (x["nv"], x["co_ve"], x["giao"]):
				sai.append(f"{x['loai']} {x['cu']} → {x['moi']}: ra {kq} ≠ nppsale nv={x['nv']} có mốc={x['co_ve']} giao={x['giao']}")
		self.assertEqual(sai, [], "\n".join(sai))

	def test_moc_ve_npp_giu_nguyen_gia_tri(self):
		cu = GiuNo(None, "2026-11-01 08:00:00", "A")
		self.assertIs(khi_doi_nguoi(cu, "B", lambda nv: False, "bay_gio"), cu)


if __name__ == "__main__":
	unittest.main()
