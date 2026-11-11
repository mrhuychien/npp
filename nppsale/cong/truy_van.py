"""Chạy kế hoạch đọc của cổng trên sổ (frappe.db) và dựng kết quả giống PostgREST."""
from __future__ import annotations

import datetime as _dt
import decimal
import json
from zoneinfo import ZoneInfo

import frappe

from . import dang_ky as D
from .sql import KeHoach, KeHoachLong, LoiCong, cau_long, ke_hoach_doc

LO = 500  # số khoá mỗi câu lấy bảng lồng


def _mui_gio():
	tz = getattr(frappe.local, "_npp_tz", None)
	if tz is None:
		ten = frappe.db.get_single_value("System Settings", "time_zone") or "Asia/Ho_Chi_Minh"
		tz = frappe.local._npp_tz = ZoneInfo(ten)
	return tz


def chuan_gia_tri(kieu: str | None, v):
	"""Giá trị từ MariaDB → JSON như PostgREST trả cho nppsale."""
	if v is None:
		return None
	if isinstance(v, bytes):
		v = v.decode("utf-8", "replace")
	if kieu in ("tien", "so"):
		if isinstance(v, decimal.Decimal):
			return int(v) if v == v.to_integral_value() else float(v)
		if isinstance(v, float) and v.is_integer():
			return int(v)
		return v
	if kieu == "bool":
		return bool(int(v)) if not isinstance(v, bool) else v
	if kieu == "ngay":
		if isinstance(v, _dt.datetime):
			return v.date().isoformat()
		if isinstance(v, _dt.date):
			return v.isoformat()
		return str(v)
	if kieu == "gio":
		if isinstance(v, _dt.datetime):
			if v.tzinfo is None:
				v = v.replace(tzinfo=_mui_gio())
			return v.isoformat()
		if isinstance(v, _dt.date):
			return _dt.datetime(v.year, v.month, v.day, tzinfo=_mui_gio()).isoformat()
		return str(v)
	if kieu == "json":
		if isinstance(v, str):
			try:
				return json.loads(v)
			except ValueError:
				return v
		return v
	if isinstance(v, decimal.Decimal):
		return float(v)
	if isinstance(v, (_dt.datetime, _dt.date)):
		return v.isoformat()
	return v


def _dung_dong(raw: dict, cot_ra: list) -> dict:
	return {k: chuan_gia_tri(kieu, raw.get(bd)) for (k, bd, kieu) in cot_ra}


def _gan_long(raw_cha: list[dict], ra_cha: list[dict], kl: KeHoachLong, nc: D.NguCanh):
	khoa = sorted({r[kl.khoa_an] for r in raw_cha if r.get(kl.khoa_an) is not None}, key=str)
	theo_khoa: dict = {}
	raw_con_all, ra_con_all = [], []
	for i in range(0, len(khoa), LO):
		sql, tham, cot_ra = cau_long(kl, khoa[i : i + LO], nc)
		for r in frappe.db.sql(sql, tham, as_dict=True):
			ra = _dung_dong(r, cot_ra)
			raw_con_all.append(r)
			ra_con_all.append(ra)
			theo_khoa.setdefault(r["__noi"], []).append(ra)
	for con in kl.con:
		_gan_long(raw_con_all, ra_con_all, con, nc)
	ten = kl.nut.khoa_ra
	for raw, ra in zip(raw_cha, ra_cha):
		ds = theo_khoa.get(raw.get(kl.khoa_an), [])
		if kl.quan_he.nhieu:
			ra[ten] = ds
		else:
			ra[ten] = ds[0] if ds else None
	if kl.nut.inner and not kl.quan_he.nhieu:
		pass  # dòng cha không có dòng lồng đã bị loại bằng EXISTS ở câu gốc


def doc(yc: dict, nc: D.NguCanh) -> dict:
	kh, _bang = ke_hoach_doc(yc, nc)
	ket: dict = {"data": None, "count": None}
	if yc.get("count") and kh.sql_dem:
		ket["count"] = int(frappe.db.sql(kh.sql_dem, kh.tham_dem)[0][0])
	if yc.get("head"):
		return ket
	raw = frappe.db.sql(kh.sql, kh.tham, as_dict=True)
	ra = [_dung_dong(r, kh.cot_ra) for r in raw]
	for kl in kh.long:
		_gan_long(raw, ra, kl, nc)
	ket["data"] = ra
	return ket


def ap_mot(ket: dict, kieu: str | None) -> dict:
	"""single() / maybeSingle() như supabase-js: PGRST116 khi không đúng một dòng."""
	if not kieu or ket.get("data") is None:
		return ket
	ds = ket["data"]
	if len(ds) == 1:
		ket["data"] = ds[0]
		return ket
	if len(ds) == 0 and kieu == "maybe":
		ket["data"] = None
		return ket
	raise LoiCong("PGRST116", "JSON object requested, multiple (or no) rows returned",
		f"The result contains {len(ds)} rows", http=406)
