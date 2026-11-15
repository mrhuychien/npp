"""RPC ĐỌC công nợ phải thu / tiền thu (đặc tả phiếu thu §5): receivables_by_customer, receivables_by_rep, receivables_summary, bao_cao_cong_no,
cash_received_total — cùng tên, cùng cột, cùng luật hàm Postgres của nppsale (mig 093 / 121 / 140 / 186 / 194 / 195 / 199 / 204).

Hàm nppsale là SECURITY INVOKER: RLS của NGƯỜI GỌI áp lên mọi bảng (kể cả bảng nối — khách / người dùng / HĐ không thấy được ra '-' / null). Ở đây
mọi câu đọc đi qua chính cổng (`truy_van.doc` với ngữ cảnh người gọi) nên vế RLS là một chỗ với bảng cổng: NVBH chỉ thấy dòng mình giữ, thủ kho không
thấy dòng công nợ nào. Nợ = Σ(amount − paid) KHÔNG kẹp 0 (dư có trừ vào nợ). "Quá hạn" của receivables_by_customer / by_rep là theo DẤU (status
'overdue'), của receivables_summary là theo HẠN (giờ VN) — đừng trộn. ROUND của Postgres là nửa xa số 0 (Decimal ROUND_HALF_UP, không round()).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe.utils import getdate, nowdate

from nppsale.cong.ngu_canh import hien_tai
from nppsale.cong.truy_van import doc

from . import rpc


def _d(v) -> Decimal:
	return Decimal(str(v)) if v is not None else Decimal(0)


def _ra(x: Decimal):
	"""numeric của Postgres ra JSON: số nguyên không phần lẻ."""
	return int(x) if x == x.to_integral_value() else float(x)


def _tron(x: Decimal) -> int:
	return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _doc(nc, bang: str, select: str, loc: list | None = None) -> list[dict]:
	return doc({"bang": bang, "select": select, "loc": loc or []}, nc)["data"] or []


def _ten_nv(nc, ids) -> dict:
	ids = sorted({x for x in ids if x})
	if not ids:
		return {}
	return {r["id"]: r.get("full_name") for r in _doc(nc, "users", "id, full_name", [{"op": "in", "cot": "id", "gt": ids}])}


@rpc("receivables_by_customer", ghi=False)
def receivables_by_customer():
	nc = hien_tai()
	gom: dict = {}
	for r in _doc(nc, "receivables", "customer_id, amount, paid, status, sales_user_id", [{"op": "neq", "cot": "status", "gt": "paid"}]):
		g = gom.setdefault(r["customer_id"], {"debt": Decimal(0), "paid": Decimal(0), "con": Decimal(0), "qh": None, "nv": []})
		a, p = _d(r["amount"]), _d(r["paid"])
		g["debt"] += a
		g["paid"] += p
		g["con"] += a - p
		if r["status"] == "overdue":
			g["qh"] = (g["qh"] or Decimal(0)) + a - p
		if r.get("sales_user_id"):
			g["nv"].append(r["sales_user_id"])
	if not gom:
		return []
	kh = {r["id"]: r for r in _doc(nc, "customers", "id, store_name, phone, credit_limit", [{"op": "in", "cot": "id", "gt": list(gom)}])}
	pc: dict = {}
	for r in _doc(nc, "customer_assignments", "customer_id, user_id", [{"op": "in", "cot": "customer_id", "gt": list(gom)},
			{"op": "eq", "cot": "role", "gt": "primary"}]):
		pc.setdefault(r["customer_id"], r["user_id"])  # LIMIT 1 không ORDER BY
	ten = _ten_nv(nc, list(pc.values()) + [min(g["nv"]) for g in gom.values() if g["nv"]])
	ra = []
	for k, g in gom.items():
		c = kh.get(k) or {}
		rep = ten.get(pc.get(k)) if pc.get(k) in ten else None
		if rep is None and g["nv"]:
			rep = ten.get(min(g["nv"]))
		ra.append({"customer_id": k, "store_name": c.get("store_name") if c.get("store_name") is not None else "-",
			"phone": c.get("phone") if c.get("phone") is not None else "-", "rep_name": rep if rep is not None else "-",
			"total_debt": _ra(g["debt"]), "total_paid": _ra(g["paid"]), "remaining": _ra(g["con"]),
			"overdue_amount": _ra(max(Decimal(0), g["qh"] or Decimal(0))),
			"credit_limit": _ra(_d(c.get("credit_limit")))})
	ra.sort(key=lambda x: -Decimal(str(x["remaining"])))
	return ra


@rpc("receivables_by_rep", ghi=False)
def receivables_by_rep():
	nc = hien_tai()
	hom_nay = getdate(nowdate())
	gom: dict = {}
	for r in _doc(nc, "receivables", "customer_id, amount, paid, status, sales_user_id, due_date"):
		g = gom.setdefault(r.get("sales_user_id"), {"kh": set(), "kh_no": set(), "con": Decimal(0), "paid": Decimal(0), "amount": Decimal(0),
			"qh": Decimal(0), "tuoi": []})
		a, p = _d(r["amount"]), _d(r["paid"])
		con = a - p if r["status"] != "paid" else Decimal(0)
		co_no = r["status"] != "paid" and a - p > 0
		g["kh"].add(r["customer_id"])
		g["con"] += con
		g["paid"] += p
		g["amount"] += a
		if r["status"] == "overdue":
			g["qh"] += con
		if co_no:
			g["kh_no"].add(r["customer_id"])
			han = getdate(r["due_date"]) if r.get("due_date") else hom_nay
			g["tuoi"].append(max(0, (hom_nay - han).days))
	ten = _ten_nv(nc, list(gom))
	ra = []
	for nv, g in gom.items():
		ty_le = 0
		if g["amount"] > 0:
			ty_le = max(0, min(100, _tron(g["paid"] / g["amount"] * 100)))
		dso = _tron(Decimal(sum(g["tuoi"])) / Decimal(len(g["tuoi"]))) if g["tuoi"] else 0
		ra.append({"user_id": nv, "full_name": "(Chưa gán nhân viên)" if nv is None else (ten.get(nv) if ten.get(nv) is not None else "-"),
			"customer_count": len(g["kh"]), "customers_with_debt": len(g["kh_no"]), "total_debt": _ra(g["con"]), "total_paid": _ra(g["paid"]),
			"total_amount": _ra(g["amount"]), "overdue_amount": _ra(g["qh"]), "collection_rate": ty_le, "dso": dso})
	ra.sort(key=lambda x: -Decimal(str(x["total_debt"])))
	return ra


@rpc("receivables_summary", ghi=False)
def receivables_summary():
	nc = hien_tai()
	hom_nay = getdate(nowdate())
	tong = {"current": [Decimal(0), 0], "warning": [Decimal(0), 0], "overdue": [Decimal(0), 0], "critical": [Decimal(0), 0]}
	tat_ca = Decimal(0)
	for r in _doc(nc, "receivables", "amount, paid, due_date", [{"op": "neq", "cot": "status", "gt": "paid"}]):
		con = _d(r["amount"]) - _d(r["paid"])
		tat_ca += con
		if not r.get("due_date"):
			nhom = "current"
		else:
			n = (hom_nay - getdate(r["due_date"])).days
			nhom = "current" if n <= 0 else "warning" if n <= 30 else "overdue" if n <= 60 else "critical"
		tong[nhom][0] += con
		tong[nhom][1] += 1
	return [{"total_outstanding": _ra(tat_ca),
		**{f"{k}_amount": _ra(v[0]) for k, v in tong.items()}, **{f"{k}_count": v[1] for k, v in tong.items()}}]


@rpc("bao_cao_cong_no", ghi=False)
def bao_cao_cong_no(p_tu_thu=None, p_tu_90=None):
	nc = hien_tai()
	phieu = _doc(nc, "receivables", "id, customer_id, sales_user_id, invoice_id, return_id, amount, paid, due_date, status, created_at, "
		"invoice:sales_invoices(invoice_code, invoice_date)")
	theo_id = {p["id"]: p for p in phieu}
	mo = [p for p in phieu if p["status"] != "paid"]
	gan90 = []
	if p_tu_90:
		moc = f"{getdate(p_tu_90).isoformat()}T00:00:00+07:00"
		gan90 = _doc(nc, "receivables", "id", [{"op": "gte", "cot": "created_at", "gt": moc}])
		gan90 = [theo_id[x["id"]] for x in gan90 if x["id"] in theo_id]
	thu = []
	if p_tu_thu:
		moc = f"{getdate(p_tu_thu).isoformat()}T00:00:00+07:00"
		for t in _doc(nc, "payments", "id, amount, method, collected_at, receivable_id", [{"op": "gte", "cot": "collected_at", "gt": moc}]):
			thu.append({**t, "receivable": theo_id.get(t["receivable_id"])})
	return {"mo": mo, "gan90": gan90, "thu": thu}


@rpc("cash_received_total", ghi=False)
def cash_received_total(p_from=None, p_to=None):
	if not p_from or not p_to:
		return 0
	nc = hien_tai()
	ds = _doc(nc, "cash_receipts", "submitted_amount", [{"op": "eq", "cot": "status", "gt": "received"},
		{"op": "gte", "cot": "receipt_date", "gt": str(getdate(p_from))}, {"op": "lte", "cot": "receipt_date", "gt": str(getdate(p_to))}])
	return _ra(sum((_d(x["submitted_amount"]) for x in ds), Decimal(0)))


_ = frappe
