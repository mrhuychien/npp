"""Dựng câu SQL (MariaDB) cho một yêu cầu đọc của cổng. Thuần — không import frappe; tham số kiểu %(p0)s cho frappe.db.sql."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import chon as C
from . import dang_ky as D
from . import loc as L


class LoiCong(Exception):
	"""Lỗi trả về trình duyệt theo dạng PostgREST: {message, code, details, hint}."""

	def __init__(self, ma: str, thong_diep: str, chi_tiet: str | None = None, http: int = 400):
		super().__init__(thong_diep)
		self.ma, self.thong_diep, self.chi_tiet, self.http = ma, thong_diep, chi_tiet, http

	def to_dict(self):
		return {"message": self.thong_diep, "code": self.ma, "details": self.chi_tiet, "hint": None}


class BoThamSo:
	def __init__(self):
		self.gia_tri: dict = {}
		self._n = 0

	def them(self, v) -> str:
		ten = f"p{self._n}"
		self._n += 1
		self.gia_tri[ten] = v
		return f"%({ten})s"


def _bieu(bang: D.Bang, ten_cot: str, bd: str) -> tuple[str, D.CotDef]:
	cd = bang.cot_def(ten_cot)
	if cd is None:
		raise LoiCong("42703", f'column {bang.ten}.{ten_cot} does not exist')
	return cd.sql.replace("{t}", bd), cd


def _ep(cd: D.CotDef, v):
	"""Giá trị bộ lọc → giá trị so sánh theo kiểu cột."""
	if v is None:
		return None
	if cd.kieu == "bool":
		if isinstance(v, str):
			return 1 if v.strip().lower() in ("true", "t", "1", "yes") else 0
		return 1 if v else 0
	return v


def dieu_kien(bang: D.Bang, nut, bd: str, ts: BoThamSo) -> str:
	if isinstance(nut, (L.Va, L.Hoac)):
		noi = " AND " if isinstance(nut, L.Va) else " OR "
		phan = [dieu_kien(bang, c, bd, ts) for c in nut.con] or ["1=1"]
		s = "(" + noi.join(phan) + ")"
		return f"NOT {s}" if nut.phu_dinh else s
	if not isinstance(nut, L.Dieu):
		raise LoiCong("PGRST100", f"bộ lọc không hợp lệ: {nut!r}")
	e, cd = _bieu(bang, nut.cot, bd)
	op, v = nut.op, nut.gt
	if op == "eq":
		s = f"{e} IS NULL" if v is None else f"{e} = {ts.them(_ep(cd, v))}"
	elif op == "neq":
		s = f"{e} IS NOT NULL" if v is None else f"{e} <> {ts.them(_ep(cd, v))}"
	elif op in ("gt", "gte", "lt", "lte"):
		s = f"{e} {dict(gt='>', gte='>=', lt='<', lte='<=')[op]} {ts.them(_ep(cd, v))}"
	elif op == "like":
		s = f"{e} LIKE {ts.them(v)}"
	elif op == "ilike":
		s = f"LOWER({e}) LIKE LOWER({ts.them(v)})"
	elif op == "is":
		s = f"{e} IS NULL" if v is None else (f"{e} IS TRUE" if v else f"{e} IS FALSE")
	elif op == "in":
		ds = list(v) if isinstance(v, (list, tuple, set)) else [v]
		s = "1=0" if not ds else f"{e} IN (" + ", ".join(ts.them(_ep(cd, x)) for x in ds) + ")"
	elif op in ("cs", "cd", "ov"):
		import json as _json
		val = v if isinstance(v, str) else _json.dumps(v, ensure_ascii=False)
		if op == "cs":
			s = f"JSON_CONTAINS({e}, {ts.them(val)})"
		elif op == "cd":
			s = f"JSON_CONTAINS({ts.them(val)}, {e})"
		else:
			s = f"JSON_OVERLAPS({e}, {ts.them(val)})"
	elif op == "isdistinct":
		s = f"NOT ({e} <=> {ts.them(_ep(cd, v))})"
	else:
		raise LoiCong("PGRST100", f"toán tử chưa hỗ trợ: {op}")
	return f"NOT ({s})" if nut.phu_dinh else s


def vế_rls(bang: D.Bang, nc: D.NguCanh, bd: str, ts: BoThamSo) -> str:
	if nc.bo_qua_rls or bang.rls is None:
		return "1=1"
	kq = bang.rls(nc)
	if kq is None or kq is True:
		return "1=1"
	if kq is False:
		return "1=0"
	sql, tham = kq if isinstance(kq, tuple) else (kq, {})
	# Đổi tên tham số của RLS sang dãy chung để không đụng nhau giữa bảng gốc / bảng lồng
	for k, v in (tham or {}).items():
		sql = sql.replace(f"%({k})s", ts.them(v))
	return "(" + sql.replace("{t}", bd) + ")"


@dataclass
class KeHoachLong:
	nut: C.Long
	quan_he: D.QuanHe
	bang: D.Bang
	khoa_an: str  # bí danh cột ẩn chứa giá trị nối ở bảng cha
	dieu: list = field(default_factory=list)
	thu_tu: list = field(default_factory=list)
	con: list = field(default_factory=list)  # KeHoachLong lồng tiếp


@dataclass
class KeHoach:
	sql: str
	tham: dict
	sql_dem: str | None
	tham_dem: dict | None
	cot_ra: list  # [(khoa_ra, bi_danh_sql, kieu)] theo đúng thứ tự select
	long: list  # [KeHoachLong]
	co_gop: bool = False


def _cot_chon(bang: D.Bang, nut_chon: list, bd: str, ts_unused=None):
	"""→ (danh sách (biểu thức, bí danh SQL, khoá ra, kiểu), các nút lồng, các nút gộp)."""
	cot, long, gop = [], [], []
	for nut in nut_chon:
		if isinstance(nut, C.TatCa):
			for ten, cd in bang.cot.items():
				cot.append((cd.sql.replace("{t}", bd), f"c__{ten}", ten, cd.kieu))
		elif isinstance(nut, C.Cot):
			e, cd = _bieu(bang, nut.ten, bd)
			cot.append((e, f"c__{nut.khoa_ra}", nut.khoa_ra, cd.kieu))
		elif isinstance(nut, C.Long):
			long.append(nut)
		elif isinstance(nut, C.Gop):
			gop.append(nut)
	return cot, long, gop


def _sap_xep(bang: D.Bang, thu_tu: list[dict], bd: str) -> str:
	phan = []
	for o in thu_tu or []:
		e, _ = _bieu(bang, o["cot"], bd)
		tang = o.get("tang", True)
		null_dau = o.get("null_dau")
		if null_dau is None:
			null_dau = not tang  # mặc định PostgREST: asc → NULL cuối; desc → NULL đầu
		phan.append(f"({e} IS NULL) {'DESC' if null_dau else 'ASC'}")
		phan.append(f"{e} {'ASC' if tang else 'DESC'}")
	return (" ORDER BY " + ", ".join(phan)) if phan else ""


def ke_hoach_doc(yc: dict, nc: D.NguCanh) -> tuple[KeHoach, D.Bang]:
	"""yc: {"bang", "select", "loc", "thu_tu", "range": [tu, den], "limit", "count", "head"}."""
	bang = D.lay(yc.get("bang") or "")
	if bang is None:
		raise LoiCong("42P01", f'relation "public.{yc.get("bang")}" does not exist', http=404)
	try:
		nut_chon = C.doc_select(yc.get("select"))
		dieu_goc, dieu_long = L.doc_loc(yc.get("loc"))
	except (C.LoiChon, L.LoiLoc) as e:
		raise LoiCong("PGRST100", str(e))
	ts = BoThamSo()
	bd = "b"
	cot, nut_long, nut_gop = _cot_chon(bang, nut_chon, bd)
	where = [vế_rls(bang, nc, bd, ts)] + [dieu_kien(bang, d, bd, ts) for d in dieu_goc]

	# Thứ tự: phần của bảng gốc và phần của bảng lồng
	thu_tu_goc = [o for o in (yc.get("thu_tu") or []) if not o.get("bang_ngoai")]
	thu_tu_long: dict[str, list] = {}
	for o in yc.get("thu_tu") or []:
		if o.get("bang_ngoai"):
			thu_tu_long.setdefault(o["bang_ngoai"], []).append(o)

	ke_long = []
	for i, nl in enumerate(nut_long):
		kl = _ke_hoach_long(bang, nl, f"k{i}", dieu_long, thu_tu_long, nc)
		ke_long.append(kl)
		e_nay, cd_nay = _bieu(bang, kl.quan_he.cot_nay, bd)
		cot.append((e_nay, kl.khoa_an, None, cd_nay.kieu))
		if nl.inner:
			where.append(_exists_long(kl, e_nay, nc, ts, f"e{i}"))

	if nut_gop:
		if nut_long:
			raise LoiCong("PGRST100", "gộp nhóm kèm bảng lồng chưa hỗ trợ ở cổng — dùng đường lùi")
		nhom = [c for c in cot]
		chon = [f"{c[0]} AS `{c[1]}`" for c in nhom]
		cot_ra = [(c[2], c[1], c[3]) for c in nhom]
		for j, g in enumerate(nut_gop):
			if g.ham == "count" and g.cot is None:
				ex = "COUNT(*)"
				kieu = "so"
			else:
				e, cd = _bieu(bang, g.cot, bd)
				ex = f"{g.ham.upper()}({e})"
				kieu = "so" if g.ham == "count" else ("tien" if cd.kieu in ("tien", "so") else cd.kieu)
			chon.append(f"{ex} AS `g__{j}`")
			cot_ra.append((g.khoa_ra, f"g__{j}", kieu))
		sql = f"SELECT {', '.join(chon)} FROM {bang.nguon} {bd} WHERE {' AND '.join(where)}"
		if nhom:
			sql += " GROUP BY " + ", ".join(c[0] for c in nhom)
		sql += _sap_xep(bang, thu_tu_goc, bd) if thu_tu_goc and all(bang.cot_def(o['cot']) for o in thu_tu_goc) else ""
		return KeHoach(sql, ts.gia_tri, None, None, cot_ra, [], co_gop=True), bang

	if not cot:
		cot.append((bang.cot[bang.khoa].sql.replace("{t}", bd), "c__" + bang.khoa, None, bang.cot[bang.khoa].kieu))
	chon = [f"{c[0]} AS `{c[1]}`" for c in cot]
	cot_ra = [(c[2], c[1], c[3]) for c in cot if c[2] is not None]
	from_where = f" FROM {bang.nguon} {bd} WHERE {' AND '.join(where)}"
	sql = "SELECT " + ", ".join(chon) + from_where + _sap_xep(bang, thu_tu_goc, bd)
	tu, den = None, None
	if yc.get("range"):
		tu, den = int(yc["range"][0]), int(yc["range"][1])
	gioi_han = yc.get("limit")
	if tu is not None:
		so = max(0, den - tu + 1)
		if gioi_han is not None:
			so = min(so, int(gioi_han))
		sql += f" LIMIT {so} OFFSET {tu}"
	elif gioi_han is not None:
		sql += f" LIMIT {int(gioi_han)}"
	sql_dem = tham_dem = None
	if yc.get("count") in ("exact", "planned", "estimated"):
		sql_dem = "SELECT COUNT(*) AS n" + from_where
		tham_dem = dict(ts.gia_tri)
	return KeHoach(sql, ts.gia_tri, sql_dem, tham_dem, cot_ra, ke_long), bang


def _ke_hoach_long(bang_cha: D.Bang, nl: C.Long, khoa_an: str, dieu_long: dict, thu_tu_long: dict, nc) -> KeHoachLong:
	qh = D.tim_quan_he(bang_cha, nl.ten, nl.goi_y)
	if qh is None:
		raise LoiCong("PGRST200", f"Could not find a relationship between '{bang_cha.ten}' and '{nl.ten}' in the schema cache")
	bang_dich = D.lay(qh.bang)
	if bang_dich is None:
		raise LoiCong("42P01", f'relation "public.{qh.bang}" does not exist', http=404)
	dk = dieu_long.get(nl.khoa_ra, []) + (dieu_long.get(nl.ten, []) if nl.khoa_ra != nl.ten else [])
	tt = thu_tu_long.get(nl.khoa_ra, []) + (thu_tu_long.get(nl.ten, []) if nl.khoa_ra != nl.ten else [])
	kl = KeHoachLong(nut=nl, quan_he=qh, bang=bang_dich, khoa_an=f"__{khoa_an}", dieu=dk, thu_tu=tt)
	# lồng tiếp: điều kiện / thứ tự của bảng lồng cấp 2 viết dạng "a.b.cot" chưa hỗ trợ — chỉ cấp 1
	kl.con = [_ke_hoach_long(bang_dich, c, f"{khoa_an}_{j}", {}, {}, nc) for j, c in
		enumerate([x for x in nl.con if isinstance(x, C.Long)])]
	return kl


def _exists_long(kl: KeHoachLong, e_cha: str, nc, ts: BoThamSo, bd: str) -> str:
	e_kia, _ = _bieu(kl.bang, kl.quan_he.cot_kia, bd)
	phan = [f"{e_kia} = {e_cha}", vế_rls(kl.bang, nc, bd, ts)] + [dieu_kien(kl.bang, d, bd, ts) for d in kl.dieu]
	return f"EXISTS (SELECT 1 FROM {kl.bang.nguon} {bd} WHERE {' AND '.join(phan)})"


def cau_long(kl: KeHoachLong, khoa: list, nc) -> tuple[str, dict, list]:
	"""Câu lấy dòng bảng lồng cho một lô khoá của bảng cha → (sql, tham số, cột ra)."""
	ts = BoThamSo()
	bd = "l"
	nut_chon = [x for x in kl.nut.con if not isinstance(x, C.Long)] or ([C.TatCa()] if not kl.con else [])
	cot, _, gop = _cot_chon(kl.bang, nut_chon, bd)
	if gop:
		raise LoiCong("PGRST100", "gộp nhóm trong bảng lồng chưa hỗ trợ ở cổng")
	e_kia, cd_kia = _bieu(kl.bang, kl.quan_he.cot_kia, bd)
	cot.append((e_kia, "__noi", None, cd_kia.kieu))
	for c in kl.con:
		e_nay, cd_nay = _bieu(kl.bang, c.quan_he.cot_nay, bd)
		cot.append((e_nay, c.khoa_an, None, cd_nay.kieu))
	where = [vế_rls(kl.bang, nc, bd, ts), f"{e_kia} IN (" + ", ".join(ts.them(k) for k in khoa) + ")"]
	where += [dieu_kien(kl.bang, d, bd, ts) for d in kl.dieu]
	sql = ("SELECT " + ", ".join(f"{c[0]} AS `{c[1]}`" for c in cot) + f" FROM {kl.bang.nguon} {bd} WHERE "
		+ " AND ".join(where) + _sap_xep(kl.bang, kl.thu_tu, bd))
	cot_ra = [(c[2], c[1], c[3]) for c in cot if c[2] is not None]
	return sql, ts.gia_tri, cot_ra
