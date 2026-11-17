"""Ghi qua cổng (.insert / .update / .upsert / .delete). Bảng nào nppsale cấm ghi thẳng từ trình duyệt (tiền, kho, trạng thái
chứng từ — mig 214) thì không khai bộ ghi ⇒ từ chối như RLS (42501). Bộ ghi của từng bảng khai ở nppsale/cong/bang/*.py:

	class GhiX:
		def them(self, ds_gia_tri: list[dict], nc) -> list[str]          # trả id các dòng mới
		def sua(self, gia_tri: dict, ids: list[str], nc) -> list[str]
		def xoa(self, ids: list[str], nc) -> list[str]
		def them_hoac_sua(self, ds_gia_tri, on_conflict: str | None, bo_qua_trung: bool, nc) -> list[str]   (tuỳ chọn)
		def chuan_bi(self, hanh_dong, gia_tri, ids, nc) -> None                    (tuỳ chọn — bảng ghi KHO, xem `chuan_bi_kho`)
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


_KHOA_XOA = "__khoa_xoa"


def _doc_truoc_khi_xoa(bang: D.Bang, yc: dict, ids: list, nc: D.NguCanh) -> list:
	"""Dòng (theo select của yêu cầu) của các id sắp xoá + khoá ẩn `__khoa_xoa` — bỏ vế RLS dòng như đọc lại sau khi ghi (cột vẫn che)."""
	chon = f"{yc.get('select') or '*'}, {_KHOA_XOA}:{bang.khoa}"
	ket = doc({"bang": bang.ten, "select": chon, "loc": [{"op": "in", "cot": bang.khoa, "gt": ids}]},
		D.NguCanh(user=nc.user, vai=nc.vai, quyen=nc.quyen, bo_qua_rls=True, them=nc.them))
	return ket["data"] or []


def la_ghi_kho(yc: dict) -> bool:
	"""Lời sửa / xoá trên bảng mà bộ ghi khai `chuan_bi` (ghi kho — lô: sửa hạn / vùng lập phiếu `CKL-`, xoá kiểm tồn): cổng chạy theo khuôn ghi kho
	(CFD-05, đặc tả kho_mua §2.1, BP §4.4.0) — nppsale.cong.api._ghi_kho."""
	bang = D.lay(yc.get("bang") or "")
	return bool(bang and bang.ghi is not None and hasattr(bang.ghi, "chuan_bi") and yc.get("hanh_dong") in ("update", "delete"))


def chuan_bi_kho(yc: dict, nc: D.NguCanh) -> dict:
	"""Bước ĐỌC của khuôn ghi kho — chạy TRƯỚC khi cổng commit: id dòng khớp bộ lọc + RLS, dòng trả về của DELETE … RETURNING, rồi bộ ghi ghi nhớ
	mặt hàng cần khoá. Sau commit, bộ ghi khoá Bin làm câu ĐẦU (ảnh chụp REPEATABLE READ lập ở câu đọc thường SAU khoá — PoC 1d); `ghi(…, truoc=…)`
	dùng lại kết quả này, không đọc lại trước khoá."""
	bang = D.lay(yc.get("bang") or "")
	hd = yc.get("hanh_dong")
	ids = _ids_khop(bang, yc, nc)
	dong = _doc_truoc_khi_xoa(bang, yc, ids, nc) if hd == "delete" and yc.get("select") is not None and ids else []
	bang.ghi.chuan_bi(hd, yc.get("gia_tri"), ids, nc)
	return {"ids": ids, "dong": dong}


def ghi(yc: dict, nc: D.NguCanh, truoc: dict | None = None) -> dict:
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
		ids = truoc["ids"] if truoc is not None else _ids_khop(bang, yc, nc)
		ids = bo.sua(gt or {}, ids, nc) if ids else []
	elif hd == "delete":
		ids = truoc["ids"] if truoc is not None else _ids_khop(bang, yc, nc)
		# DELETE … RETURNING: đọc dòng TRƯỚC khi xoá (kèm khoá ẩn để lọc đúng dòng bộ ghi đã xoá) — đọc lại sau khi xoá ra [] và
		# giao diện báo "không xoá được" dù đã xoá (vd. xoá phiếu trả nháp, sửa đơn bỏ phiếu trả cũ).
		if truoc is not None:
			dong_truoc = truoc["dong"]
		else:
			dong_truoc = _doc_truoc_khi_xoa(bang, yc, ids, nc) if yc.get("select") is not None and ids else []
		ids = bo.xoa(ids, nc) if ids else []
		da_xoa = set(ids)
		ket = {"data": [{k: v for k, v in r.items() if k != _KHOA_XOA} for r in dong_truoc if r.get(_KHOA_XOA) in da_xoa]
			if yc.get("select") is not None else None, "count": len(ids) if yc.get("count") else None}
		return ket
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
