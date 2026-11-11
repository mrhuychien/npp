# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Lịch đi tuyến (= pjp_routes): thứ 0 = Thứ Hai … 6 = Chủ nhật (quy ước màn PJP)."""
import frappe
from frappe.model.document import Document


class NPPLichTuyen(Document):
	def validate(self):
		if self.thu is None or not (0 <= int(self.thu) <= 6):
			frappe.throw("Thứ phải trong khoảng 0 (Thứ Hai) … 6 (Chủ nhật).")


def on_doctype_update():
	frappe.db.add_unique("NPP Lich Tuyen", ["nhan_vien", "thu", "khach"], "uq_lich_tuyen")
	frappe.db.add_index("NPP Lich Tuyen", ["nhan_vien", "thu"], "idx_lich_tuyen_nv_thu")
