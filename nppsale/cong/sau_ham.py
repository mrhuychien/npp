"""Áp lọc / sắp / đếm / phân trang / chọn cột lên KẾT QUẢ của một RPC trả tập dòng.

PostgREST cho viết `rpc("ham", args).select("a, b").eq("x", 1).order("a").range(0, 999)` — các phép ấy bọc ngoài kết quả hàm
(SELECT … FROM ham(args) WHERE … ORDER BY … LIMIT …). Hàm của app trả list[dict]; ở đây áp đúng các phép ấy bằng Python, giữ
luật của SQL: so sánh với NULL là "không biết" (dòng bị loại, kể cả dưới NOT); sắp tăng thì NULL cuối, giảm thì NULL đầu.
"""
from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal

from . import chon as C
from . import loc as L
from .sql import LoiCong


def _so(v):
	return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _ep(mau, gt):
	"""Đưa giá trị bộ lọc (thường là chuỗi từ trình duyệt) về kiểu của giá trị trong dòng."""
	if gt is None or mau is None:
		return gt
	if isinstance(mau, bool):
		if isinstance(gt, str):
			return gt.strip().lower() in ("true", "t", "1")
		return bool(gt)
	if _so(mau):
		try:
			return Decimal(str(gt))
		except Exception:
			return gt
	if isinstance(mau, _dt.datetime):
		if isinstance(gt, str):
			try:
				return _dt.datetime.fromisoformat(gt.replace("Z", "+00:00"))
			except ValueError:
				return gt
		return gt
	if isinstance(mau, _dt.date):
		if isinstance(gt, str):
			try:
				return _dt.date.fromisoformat(gt[:10])
			except ValueError:
				return gt
		return gt
	return gt if isinstance(gt, str) else str(gt)


def _chuan(v):
	if _so(v):
		return Decimal(str(v))
	if isinstance(v, _dt.datetime) and v.tzinfo is None:
		return v
	return v


def _so_sanh(a, b):
	"""-1 / 0 / 1; None khi không so được (NULL)."""
	if a is None or b is None:
		return None
	a, b = _chuan(a), _chuan(_ep(a, b))
	try:
		return (a > b) - (a < b)
	except TypeError:
		sa, sb = str(a), str(b)
		return (sa > sb) - (sa < sb)


def _mau_like(mau: str, khong_phan_biet: bool):
	r = ""
	for ch in mau:
		r += ".*" if ch == "%" else "." if ch == "_" else re.escape(ch)
	return re.compile(r"\A" + r + r"\Z", re.S | (re.I if khong_phan_biet else 0))


def _dieu(d: L.Dieu, dong: dict):
	"""True / False / None (không biết)."""
	v = dong.get(d.cot)
	op, gt = d.op, d.gt
	if op == "is":
		kq = v is None if gt is None else (v is gt if isinstance(v, bool) else False if v is None else None)
	elif op == "isdistinct":
		kq = _ep(v, gt) != v if v is not None and gt is not None else (v is None) != (gt is None)
	elif op == "in":
		if v is None:
			kq = None
		else:
			ds = gt if isinstance(gt, (list, tuple)) else [gt]
			kq = any(_so_sanh(v, x) == 0 for x in ds if x is not None)
	elif op in ("like", "ilike"):
		kq = None if v is None or gt is None else bool(_mau_like(str(gt), op == "ilike").match(str(v)))
	elif op in ("cs", "cd", "ov"):
		if v is None:
			kq = None
		else:
			a = set(map(str, v if isinstance(v, (list, tuple, set)) else [v]))
			b = set(map(str, gt if isinstance(gt, (list, tuple, set)) else [gt]))
			kq = a >= b if op == "cs" else a <= b if op == "cd" else bool(a & b)
	else:
		c = _so_sanh(v, gt)
		if c is None:
			kq = None
		else:
			kq = {"eq": c == 0, "neq": c != 0, "gt": c > 0, "gte": c >= 0, "lt": c < 0, "lte": c <= 0}.get(op)
			if kq is None:
				raise LoiCong("PGRST100", f"toán tử không hỗ trợ sau lời gọi hàm: {op}")
	if d.phu_dinh and kq is not None:
		kq = not kq
	return kq


def _nut(n, dong):
	if isinstance(n, L.Dieu):
		return _dieu(n, dong)
	kqs = [_nut(c, dong) for c in n.con]
	if isinstance(n, L.Va):
		kq = False if any(k is False for k in kqs) else (None if any(k is None for k in kqs) else True)
	else:
		kq = True if any(k is True for k in kqs) else (None if any(k is None for k in kqs) else False)
	if n.phu_dinh and kq is not None:
		kq = not kq
	return kq


def _chieu(nut_chon, dong: dict) -> dict:
	if not nut_chon or any(isinstance(n, C.TatCa) for n in nut_chon):
		return dong
	ra = {}
	for n in nut_chon:
		if not isinstance(n, C.Cot):
			raise LoiCong("PGRST100", "sau lời gọi hàm chỉ chọn được cột của kết quả")
		ra[n.bi_danh or n.ten] = dong.get(n.ten)
	return ra


def ap(dong: list[dict], sau: dict | None):
	"""(data, count) — count = số dòng sau lọc, trước phân trang; None khi không xin đếm."""
	if not sau:
		return dong, None
	try:
		goc, long = L.doc_loc(sau.get("loc"))
		nut_chon = C.doc_select(sau.get("select")) if sau.get("select") else None
	except (L.LoiLoc, C.LoiChon) as e:
		raise LoiCong("PGRST100", str(e))
	if long:
		raise LoiCong("PGRST100", "sau lời gọi hàm không lọc được bảng lồng")
	ds = [d for d in dong if all(_nut(n, d) is True for n in goc)]
	for o in reversed(sau.get("thu_tu") or []):
		cot, tang = o.get("cot"), o.get("tang", True)
		null_dau = o.get("null_dau")
		if null_dau is None:
			null_dau = not tang
		co = [d for d in ds if d.get(cot) is not None]
		khong = [d for d in ds if d.get(cot) is None]
		co.sort(key=lambda d: _chuan(d.get(cot)), reverse=not tang)
		ds = khong + co if null_dau else co + khong
	dem = len(ds) if sau.get("count") else None
	if sau.get("range"):
		tu, den = sau["range"]
		ds = ds[int(tu) : int(den) + 1]
	if sau.get("limit") is not None:
		ds = ds[: int(sau["limit"])]
	if sau.get("head"):
		return None, dem
	return [_chieu(nut_chon, d) for d in ds], dem
