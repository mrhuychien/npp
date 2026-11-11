"""Module cũ "NPP Sale" (bản PoC) được tách thành 8 module theo quyết định Q4 — xoá Module Def mồ côi nếu không còn DocType nào."""
import frappe


def execute():
	if frappe.db.exists("Module Def", "NPP Sale") and not frappe.db.count("DocType", {"module": "NPP Sale"}):
		frappe.delete_doc("Module Def", "NPP Sale", ignore_permissions=True, force=True)
