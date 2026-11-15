# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Lượt đo thời gian nạp màn (route /api/do-nap — nppsale.api.do_nap). Chỉ thêm; Log Settings của lõi dọn dòng cũ hơn 30 ngày
(`default_log_clearing_doctypes` trong hooks.py gọi `clear_old_logs`)."""

import frappe
from frappe.model.document import Document


class NPPDoNap(Document):
	@staticmethod
	def clear_old_logs(days=30):
		from frappe.query_builder import Interval
		from frappe.query_builder.functions import Now

		t = frappe.qb.DocType("NPP Do Nap")
		frappe.db.delete(t, filters=(t.creation < (Now() - Interval(days=days))))
