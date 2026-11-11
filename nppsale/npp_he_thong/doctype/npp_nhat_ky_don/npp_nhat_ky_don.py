# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Nhật ký đơn hàng (= order_status_history + order_activity_log). Chỉ chèn — method của phần Bán hàng gọi `ghi_nhat_ky_don` đúng chỗ
trigger của nppsale từng ghi."""
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class NPPNhatKyDon(Document):
	pass


def ghi_nhat_ky_don(don: str, loai: str, *, tu_trang_thai=None, den_trang_thai=None, ghi_chu=None, hanh_dong=None, dong_don=None,
		thay_doi=None, nguoi=None, giai_doan=None):
	nv = nguoi if nguoi is not None else frappe.session.user
	if nv and not frappe.db.exists("NPP Nhan Vien", nv):
		nv = None  # Administrator / việc nền = "Hệ thống"
	frappe.get_doc({
		"doctype": "NPP Nhat Ky Don", "don": don, "loai": loai, "tu_trang_thai": tu_trang_thai, "den_trang_thai": den_trang_thai,
		"ghi_chu": ghi_chu, "hanh_dong": hanh_dong or "", "dong_don": dong_don, "thay_doi": frappe.as_json(thay_doi) if thay_doi else None,
		"nguoi": nv, "luc": now_datetime(), "giai_doan": giai_doan,
	}).insert(ignore_permissions=True)


def on_doctype_update():
	frappe.db.add_index("NPP Nhat Ky Don", ["don", "luc"], "idx_nhat_ky_don_luc")
