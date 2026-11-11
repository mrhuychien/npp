"""Supplier = suppliers của nppsale (blueprint 02 phần Kho Mua §3.6): khoá tìm = khoa_tim_ds(tên, mã, SĐT, MST) như mig 205; mã NCC
không trùng (rỗng → NULL để unique nhận nhiều dòng trống); có hạn mức thì hạn mức ≥ 0 (CHECK mig 232)."""
from __future__ import annotations

import frappe

from nppsale.luat.tim import khoa_tim_ds


def validate(doc, method=None):
	doc.npp_ma = (doc.get("npp_ma") or "").strip() or None
	if doc.get("npp_co_han_muc") and (doc.get("npp_han_muc") or 0) < 0:
		frappe.throw("Hạn mức nợ NCC không được âm.")
	doc.npp_tim_kd = khoa_tim_ds(doc.supplier_name, doc.get("npp_ma"), doc.get("npp_dien_thoai"), doc.get("tax_id"))
