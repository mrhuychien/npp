"""Hai cửa công khai của cổng:

	POST|GET /api/method/nppsale.cong.api.truy_van   {"yeu_cau": {...}}   — .from(...) của createClient() ở portal
	POST|GET /api/method/nppsale.cong.api.rpc        {"ten": "...", "tham_so": {...}}  — .rpc(ten, tham_so, {get})

Trả 200 với {"data", "count"} hoặc {"error": {message, code, details, hint}, "status"} — lớp createClient() dựng lại đúng
{data, error, count, status} như supabase-js. Đọc chạy được bằng GET (Frappe không commit GET — thử lại an toàn); ghi chỉ POST.
"""
from __future__ import annotations

import json

import frappe

from . import bang as _bang
from .ghi import ghi as _ghi
from .loi import NppLoi
from .ngu_canh import hien_tai
from .sql import LoiCong
from .truy_van import ap_mot, doc


def _doc_json(x):
	if isinstance(x, str):
		return json.loads(x) if x else {}
	return x or {}


def _phuong_thuc() -> str:
	try:
		return (frappe.request.method or "POST").upper()
	except Exception:
		return "POST"


def _loi(e: Exception) -> dict:
	if isinstance(e, (LoiCong, NppLoi)):
		return {"error": e.to_dict(), "status": e.http}
	if isinstance(e, frappe.PermissionError):
		return {"error": {"message": "permission denied", "code": "42501", "details": str(e), "hint": None}, "status": 403}
	if isinstance(e, frappe.ValidationError):
		return {"error": {"message": str(e), "code": "P0001", "details": None, "hint": None}, "status": 400}
	raise e


@frappe.whitelist(methods=["GET", "POST"])
def truy_van(yeu_cau=None):
	if frappe.session.user == "Guest":
		return {"error": {"message": "JWT expired", "code": "PGRST301", "details": None, "hint": None}, "status": 401}
	_bang.nap()
	yc = _doc_json(yeu_cau)
	hd = yc.get("hanh_dong") or "select"
	try:
		nc = hien_tai()
		if hd == "select":
			ket = ap_mot(doc(yc, nc), yc.get("mot"))
		else:
			if _phuong_thuc() != "POST":
				raise LoiCong("PGRST105", "ghi phải gửi bằng POST", http=405)
			ket = ap_mot(_ghi(yc, nc), yc.get("mot"))
		ket["status"] = 200 if hd == "select" else (201 if hd in ("insert", "upsert") else 200)
		return ket
	except Exception as e:  # noqa: BLE001 — dịch sang lỗi kiểu PostgREST, lỗi lạ thì ném tiếp
		if hd != "select":
			frappe.db.rollback()
		return _loi(e)


@frappe.whitelist(methods=["GET", "POST"])
def rpc(ten=None, tham_so=None):
	if frappe.session.user == "Guest":
		return {"error": {"message": "JWT expired", "code": "PGRST301", "details": None, "hint": None}, "status": 401}
	from nppsale import rpc as R

	R.nap()
	muc = R.DANG_KY.get(ten or "")
	if muc is None:
		return {"error": {"message": f"Could not find the function public.{ten} in the schema cache", "code": "PGRST202",
			"details": None, "hint": None}, "status": 404}
	ham, la_ghi = muc
	if la_ghi and _phuong_thuc() != "POST":
		return {"error": {"message": f"{ten} ghi sổ — phải gọi bằng POST", "code": "PGRST105", "details": None, "hint": None},
			"status": 405}
	try:
		kq = ham(**_doc_json(tham_so))
		return {"data": kq, "status": 200}
	except Exception as e:  # noqa: BLE001
		frappe.db.rollback()
		return _loi(e)
