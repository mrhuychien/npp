"""Người giữ nợ của một dòng công nợ khi chứng từ nguồn đổi người — trigger `_cong_no_giu_ve_npp` (mig 223 / 246) của nppsale, nhánh
NGOÀI chế độ giao nợ (`npp.giao_cong_no` — RPC bàn giao / nghỉ việc tự đặt người giữ). Thuần Python, không đụng sổ.

Ba trường của người giữ nợ (trên HĐ: `npp_nv_giu_no`, `npp_ve_npp_luc`, `npp_giao_tu_nv` — blueprint 02 §5.6):
- `nv`: NV đang giữ (trống = NPP giữ);
- `ve_npp`: mốc nợ về NPP (NV cũ nghỉ việc) — có mốc thì nợ ĐỨNG YÊN, chứng từ đổi người cũng không kéo về;
- `giao`: dấu bàn giao (mig 246) — NV đã giao khoản nợ này đi. Chứng từ (vẫn ghi NV giao) tính lại → giữ NV nhận; chứng từ đổi sang người
  KHÁC → theo chứng từ, bỏ dấu.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple


class GiuNo(NamedTuple):
	nv: str | None
	ve_npp: object | None
	giao: str | None


def khi_doi_nguoi(cu: GiuNo, moi: str | None, da_nghi: Callable[[str], bool], bay_gio) -> GiuNo:
	"""UPDATE … SET sales_user_id = `moi` (chứng từ đổi người đứng tên / tính lại theo chứng từ) → người giữ nợ mới."""
	if cu.ve_npp is not None:  # nợ đã về NPP: đứng yên
		return cu
	giao = cu.giao
	if cu.giao is not None:
		if moi == cu.giao:  # chứng từ vẫn ghi NV đã giao → giữ NV đang giữ
			return cu
		if moi != cu.nv:  # sang người khác → theo chứng từ, bỏ dấu
			giao = None
	nv, ve = moi, None
	if moi is not None and da_nghi(moi):  # người mới đã nghỉ: giữ người đang giữ; chưa ai → NPP
		nv = cu.nv
		if nv is None:
			ve = bay_gio
	return GiuNo(nv, ve, giao)


def khi_lap(nv: str | None, da_nghi: Callable[[str], bool], bay_gio) -> GiuNo:
	"""INSERT (ghi sổ chứng từ mới): nợ theo NV đứng tên; NV ấy đã nghỉ → NPP giữ (trống + mốc); không mang dấu bàn giao."""
	if nv is not None and da_nghi(nv):
		return GiuNo(None, bay_gio, None)
	return GiuNo(nv, None, None)
