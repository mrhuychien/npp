"""Trường `npp_*` trên DocType lõi — danh sách sinh từ blueprint 02 bằng tools/dung_truong_tuy_bien.py (truong_tuy_bien.json).
`create_custom_fields(update=True)`: thêm trường mới, cập nhật thuộc tính trường đã có; không xoá trường nào (xoá phải qua patch)."""
import json
import os

import frappe

TEP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "truong_tuy_bien.json")


def danh_sach() -> dict:
	if not os.path.exists(TEP):
		return {}
	with open(TEP, encoding="utf-8") as f:
		return json.load(f)


def ap():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	ds = danh_sach()
	# Bỏ trường trỏ tới DocType của app chưa có trên site (dựng dần theo giai đoạn) — lần migrate sau sẽ thêm.
	loc = {}
	for dt, truong in ds.items():
		if not frappe.db.exists("DocType", dt):
			continue
		con = []
		for f in truong:
			if f.get("fieldtype") in ("Link", "Table", "Table MultiSelect") and f.get("options") and not frappe.db.exists("DocType", f["options"]):
				continue
			con.append(f)
		if con:
			loc[dt] = con
	if loc:
		create_custom_fields(loc, ignore_validate=False, update=True)
