# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Ghé thăm điểm bán (= visit_logs). Đi tuyến chỉ check-in (vị trí + kết quả + ghi chú), không chụp ảnh (chủ nhà 12/10/2026)."""
import frappe
from frappe.model.document import Document


class NPPGheTham(Document):
	pass


def on_doctype_update():
	frappe.db.add_index("NPP Ghe Tham", ["khach", "ngay_ghe"], "idx_ghe_tham_khach_ngay")
	frappe.db.add_index("NPP Ghe Tham", ["nhan_vien", "ngay_ghe"], "idx_ghe_tham_nv_ngay")
