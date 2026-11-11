"""Ghi qua cổng (.insert / .update / .upsert / .delete). Bảng nào nppsale cấm ghi thẳng từ trình duyệt (tiền, kho, trạng thái
chứng từ — mig 214) thì không khai bộ ghi ⇒ từ chối như RLS (42501). Bộ ghi của từng bảng khai ở nppsale/cong/bang/*.py:

	class GhiX:
		def them(self, ds_gia_tri: list[dict], nc) -> list[str]          # trả id các dòng mới
		def sua(self, gia_tri: dict, ids: list[str], nc) -> list[str]
		def xoa(self, ids: list[str], nc) -> list[str]
		def them_hoac_sua(self, ds_gia_tri, on_conflict: str | None, bo_qua_trung: bool, nc) -> list[str]   (tuỳ chọn)
"""
from __future__ import annotations

import frappe

from . import dang_ky as D
from .sql import LoiCong
from .truy_van import doc


def _ids_khop(bang: D.Bang, yc: dict, nc: D.NguCanh) -> list:
	"""Các id dòng thoả bộ lọc + RLS của người gọi (update / delete chỉ chạm dòng người ấy thấy được)."""
	ket = doc({"bang": bang.ten, "select": bang.khoa, "loc": yc.get("loc")}, nc)
	return [r[bang.khoa] for r in (ket["data"] or [])]


def ghi(yc: dict, nc: D.NguCanh) -> dict:
	bang = D.lay(yc.get("bang") or "")
	if bang is None:
		raise LoiCong("42P01", f'relation "public.{yc.get("bang")}" does not exist', http=404)
	bo = bang.ghi
	hd = yc.get("hanh_dong")
	if bo is None:
		raise LoiCong("42501", f'new row violates row-level security policy for table "{bang.ten}"', http=403)
	gt = yc.get("gia_tri")
	if hd == "insert":
		ds = gt if isinstance(gt, list) else [gt]
		ids = bo.them(ds, nc)
	elif hd == "upsert":
		ds = gt if isinstance(gt, list) else [gt]
		if not hasattr(bo, "them_hoac_sua"):
			raise LoiCong("42501", f"upsert không được phép trên {bang.ten}", http=403)
		ids = bo.them_hoac_sua(ds, yc.get("on_conflict"), bool(yc.get("bo_qua_trung")), nc)
	elif hd == "update":
		ids = _ids_khop(bang, yc, nc)
		ids = bo.sua(gt or {}, ids, nc) if ids else []
	elif hd == "delete":
		ids = _ids_khop(bang, yc, nc)
		ids = bo.xoa(ids, nc) if ids else []
	else:
		raise LoiCong("PGRST100", f"hành động không hỗ trợ: {hd}")
	ket = {"data": None, "count": None}
	if yc.get("select") is not None and ids:
		ket = doc({"bang": bang.ten, "select": yc.get("select"), "loc": [{"op": "in", "cot": bang.khoa, "gt": ids}]},
			D.NguCanh(user=nc.user, vai=nc.vai, quyen=nc.quyen, bo_qua_rls=True, them=nc.them))
	elif yc.get("select") is not None:
		ket["data"] = []
	if yc.get("count"):
		ket["count"] = len(ids)
	return ket
