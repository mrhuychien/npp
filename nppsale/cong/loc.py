"""Bộ lọc của cổng: điều kiện đơn, phủ định, và biểu thức or / and kiểu PostgREST.

Lớp createClient() ở portal gửi mỗi bộ lọc thành một từ điển:
    {"op": "eq", "cot": "status", "gt": "draft"}             .eq / .neq / .gt / .gte / .lt / .lte / .like / .ilike / .is / .in
    {"op": "not", "cot": "status", "op_con": "is", "gt": None}  .not(cot, toan_tu, gia_tri)
    {"op": "or", "bieu_thuc": "status.is.null,status.eq.active", "bang_ngoai": None}
    {"op": "filter", "cot": "tags", "toan_tu": "cs", "gt": "{a,b}"}  .filter(cot, toan_tu, gia_tri) — giá trị theo cú pháp PostgREST
    {"op": "match", "gt": {"a": 1}}                            .match({...}) — tương đương nhiều eq
Cột có dấu chấm ("customers.channel") là cột của bảng lồng tên ấy.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TOAN_TU = {"eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is", "in", "cs", "cd", "ov", "match", "imatch",
	"fts", "plfts", "phfts", "wfts", "isdistinct"}
TOAN_TU_HO_TRO = {"eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is", "in", "cs", "cd", "ov", "isdistinct"}


class LoiLoc(ValueError):
	"""Bộ lọc sai cú pháp hoặc không hỗ trợ (PGRST100)."""


@dataclass
class Dieu:
	op: str
	cot: str
	gt: object = None
	phu_dinh: bool = False


@dataclass
class Va:
	con: list = field(default_factory=list)
	phu_dinh: bool = False


@dataclass
class Hoac:
	con: list = field(default_factory=list)
	phu_dinh: bool = False


def _tach(s: str) -> list[str]:
	"""Tách theo phẩy ở mức ngoặc 0, tôn trọng nháy kép (giá trị có phẩy)."""
	phan, cur, sau, nhay = [], [], 0, False
	i = 0
	while i < len(s):
		ch = s[i]
		if ch == "\\" and i + 1 < len(s):
			cur.append(s[i : i + 2])
			i += 2
			continue
		if ch == '"':
			nhay = not nhay
		elif not nhay:
			if ch == "(":
				sau += 1
			elif ch == ")":
				sau -= 1
			elif ch == "," and sau == 0:
				phan.append("".join(cur))
				cur = []
				i += 1
				continue
		cur.append(ch)
		i += 1
	if sau != 0 or nhay:
		raise LoiLoc(f"ngoặc / nháy không khép: {s!r}")
	phan.append("".join(cur))
	return [p.strip() for p in phan if p.strip()]


def _bo_nhay(v: str) -> str:
	v = v.strip()
	if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
		return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
	return v


def doc_gia_tri(op: str, tho: str):
	"""Giá trị theo cú pháp PostgREST → giá trị Python."""
	if op == "is":
		t = tho.strip().lower()
		if t in ("null", "true", "false", "unknown"):
			return {"null": None, "true": True, "false": False, "unknown": None}[t]
		raise LoiLoc(f"is chỉ nhận null / true / false: {tho!r}")
	if op == "in":
		t = tho.strip()
		if not (t.startswith("(") and t.endswith(")")):
			raise LoiLoc(f"in cần dạng (a,b,…): {tho!r}")
		return [_bo_nhay(x) for x in _tach(t[1:-1])]
	if op in ("cs", "cd", "ov"):
		t = tho.strip()
		if t.startswith("{") and t.endswith("}"):
			return [_bo_nhay(x) for x in _tach(t[1:-1])]
		if t.startswith("[") or t.startswith("{"):
			return t  # JSON thô
		return [t]
	if op in ("like", "ilike"):
		return _bo_nhay(tho).replace("*", "%")
	return _bo_nhay(tho)


def doc_bieu_thuc(bieu_thuc: str) -> Hoac:
	"""Biểu thức truyền vào .or("a.eq.1,b.is.null,and(c.gt.2,d.lt.5)") → cây Hoac."""
	return Hoac(con=[_doc_dieu(p) for p in _tach(bieu_thuc)])


def _doc_dieu(p: str):
	p = p.strip()
	phu_dinh = False
	if p.startswith("not."):
		phu_dinh, p = True, p[4:]
	for ten, lop in (("and(", Va), ("or(", Hoac)):
		if p.startswith(ten):
			if not p.endswith(")"):
				raise LoiLoc(f"thiếu ngoặc đóng: {p!r}")
			return lop(con=[_doc_dieu(x) for x in _tach(p[len(ten) : -1])], phu_dinh=phu_dinh)
	# cot.[not.]op.gia_tri — cột có thể chứa dấu chấm (bảng lồng): tìm toán tử từ trái sang
	phan = p.split(".")
	for i in range(1, len(phan)):
		ung = phan[i]
		phu = False
		j = i
		if ung == "not" and i + 1 < len(phan):
			phu, j = True, i + 1
			ung = phan[j]
		if ung in TOAN_TU:
			cot = ".".join(phan[:i])
			gia_tri = ".".join(phan[j + 1 :])
			if ung not in TOAN_TU_HO_TRO:
				raise LoiLoc(f"toán tử chưa hỗ trợ: {ung}")
			return Dieu(op=ung, cot=cot, gt=doc_gia_tri(ung, gia_tri), phu_dinh=phu_dinh ^ phu)
	raise LoiLoc(f"không đọc được điều kiện: {p!r}")


def doc_loc(ds: list[dict] | None) -> tuple[list, dict[str, list]]:
	"""Danh sách bộ lọc từ trình duyệt → (điều kiện của bảng gốc, {tên bảng lồng: điều kiện của nó})."""
	goc, long = [], {}

	def them(nut, bang_ngoai=None):
		if bang_ngoai:
			long.setdefault(bang_ngoai, []).append(nut)
			return
		# Điều kiện đơn có cột dạng "bang.cot" thuộc về bảng lồng
		if isinstance(nut, Dieu) and "." in nut.cot:
			ten, cot = nut.cot.split(".", 1)
			long.setdefault(ten, []).append(Dieu(nut.op, cot, nut.gt, nut.phu_dinh))
			return
		goc.append(nut)

	for f in ds or []:
		op = f.get("op")
		if op == "or":
			them(doc_bieu_thuc(f.get("bieu_thuc") or ""), f.get("bang_ngoai"))
		elif op == "match":
			for k, v in (f.get("gt") or {}).items():
				them(Dieu("eq", k, v))
		elif op == "not":
			op_con = f.get("op_con")
			gt = f.get("gt")
			if isinstance(gt, str) and op_con in ("in", "is", "cs", "cd", "ov"):
				gt = doc_gia_tri(op_con, gt)
			if op_con not in TOAN_TU_HO_TRO:
				raise LoiLoc(f"toán tử chưa hỗ trợ trong not: {op_con}")
			them(Dieu(op_con, f["cot"], gt, True))
		elif op == "filter":
			tt = f.get("toan_tu") or ""
			phu = tt.startswith("not.")
			tt = tt[4:] if phu else tt
			if tt not in TOAN_TU_HO_TRO:
				raise LoiLoc(f"toán tử chưa hỗ trợ: {tt}")
			gt = f.get("gt")
			if isinstance(gt, str):
				gt = doc_gia_tri(tt, gt)
			them(Dieu(tt, f["cot"], gt, phu))
		elif op in TOAN_TU_HO_TRO:
			gt = f.get("gt")
			if op in ("like", "ilike") and isinstance(gt, str):
				gt = gt.replace("*", "%")
			them(Dieu(op, f["cot"], gt, False))
		else:
			raise LoiLoc(f"bộ lọc không hỗ trợ: {op}")
	return goc, long
