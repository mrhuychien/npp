# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Dòng quyền của vai (= role_permissions). Tên bản ghi = "vai:mô-đun:hành động" nên ghi đè theo khoá ghép là ghi theo tên."""
import re

import frappe
from frappe import _
from frappe.model.document import Document

from nppsale.npp_he_thong.doctype.npp_phien_danh_muc.npp_phien_danh_muc import tang_phien_khach

MAU_MO_DUN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


class NPPQuyenVai(Document):
	def validate(self):
		if not MAU_MO_DUN.match(self.mo_dun or "") or len(self.mo_dun) > 64:
			frappe.throw(_("Mô-đun / ô quyền không hợp lệ: {0}").format(self.mo_dun))

	def on_update(self):
		tang_phien_khach()

	def on_trash(self):
		tang_phien_khach()
