# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Phân công khách cho nhân viên (= customer_assignments). Một cặp (khách, NV) một dòng. Đổi → tăng phiên khách (tập khách NVBH
thấy đổi)."""
import frappe
from frappe.model.document import Document

from nppsale.npp_he_thong.doctype.npp_phien_danh_muc.npp_phien_danh_muc import tang_phien_khach


class NPPPhanCongKhach(Document):
	def on_update(self):
		tang_phien_khach()

	def on_trash(self):
		tang_phien_khach()


def on_doctype_update():
	frappe.db.add_unique("NPP Phan Cong Khach", ["khach", "nhan_vien"], "uq_phan_cong_khach_nv")
