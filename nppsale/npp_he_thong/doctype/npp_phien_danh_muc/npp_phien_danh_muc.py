# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Số phiên danh mục bán (mig 209 / 254): máy NVBH so số này với bản lưu IndexedDB để biết có phải tải lại hàng / khách không.

Tăng bằng MỘT câu cộng dồn trong cùng giao dịch với thay đổi danh mục — khoá dòng tới commit như trigger mức câu lệnh của nppsale.
Không để trong Single (đọc-sửa-ghi hai giao dịch cùng lúc → một lần đổi bị mất)."""
import frappe
from frappe.model.document import Document

TEN = "1"


class NPPPhienDanhMuc(Document):
	pass


def _tang(cot: str, cot_luc: str):
	if not frappe.db.exists("NPP Phien Danh Muc", TEN):
		frappe.get_doc({"doctype": "NPP Phien Danh Muc", "name": TEN, "phien": 1, "phien_khach": 1}).insert(ignore_permissions=True)
	frappe.db.sql(
		f"UPDATE `tabNPP Phien Danh Muc` SET `{cot}` = `{cot}` + 1, `{cot_luc}` = NOW(6), `modified` = NOW(6) WHERE `name` = %s", (TEN,)
	)


def tang_phien_danh_muc(*_a, **_k):
	"""Hàng · giá · đơn vị đổi (doc_events Item / Item Price / Price List)."""
	_tang("phien", "luc")


def tang_phien_khach(*_a, **_k):
	"""Khách · nhóm khách · phân công · quyền đổi (tập khách NVBH thấy có thể đổi)."""
	_tang("phien_khach", "luc_khach")


def doc_phien() -> dict:
	r = frappe.db.sql("SELECT phien, luc, phien_khach, luc_khach FROM `tabNPP Phien Danh Muc` WHERE name = %s", (TEN,), as_dict=True)
	return r[0] if r else {"phien": 1, "luc": None, "phien_khach": 1, "luc_khach": None}
