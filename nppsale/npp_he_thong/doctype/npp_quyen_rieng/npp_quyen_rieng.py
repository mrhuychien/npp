# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Quyền riêng của một nhân viên (= user_permission_overrides) — thắng ma trận vai; chủ NPP luôn được trừ khi có dòng riêng cấm."""
import frappe
from frappe import _
from frappe.model.document import Document

from nppsale.luat.quyen import tach_khoa
from nppsale.npp_he_thong.doctype.npp_phien_danh_muc.npp_phien_danh_muc import tang_phien_khach


class NPPQuyenRieng(Document):
	def validate(self):
		if not tach_khoa(self.khoa_quyen or ""):
			frappe.throw(_("Khoá quyền phải có dạng <mô-đun / ô>.<hành động>: {0}").format(self.khoa_quyen))

	def on_update(self):
		tang_phien_khach()

	def on_trash(self):
		tang_phien_khach()
