# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Thông báo trong app (= notifications). Chèn / đổi trạng thái đọc → đẩy realtime tới đúng người nhận (thay postgres_changes của chuông)."""
import frappe
from frappe.model.document import Document


class NPPThongBao(Document):
	def after_insert(self):
		self._bao("INSERT")

	def on_update(self):
		if not self.is_new() and self.has_value_changed("da_doc"):
			self._bao("UPDATE")

	def _bao(self, su_kien: str):
		frappe.publish_realtime(
			"npp_cong",
			{"bang": "notifications", "su_kien": su_kien, "id": self.name},
			user=self.nguoi_nhan,
			after_commit=True,
		)


def on_doctype_update():
	frappe.db.add_index("NPP Thong Bao", ["nguoi_nhan", "da_doc", "creation"], "idx_thong_bao_chua_doc")
	frappe.db.add_index("NPP Thong Bao", ["nguoi_nhan", "creation"], "idx_thong_bao_gan_day")
