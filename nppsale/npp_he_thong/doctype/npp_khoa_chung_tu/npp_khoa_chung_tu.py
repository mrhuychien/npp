# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Khoá sửa đồng thời một chứng từ (= entity_locks). Tên = "loại:chứng từ" — giành khoá là chèn, trùng tên = người khác đang giữ."""
import frappe
from frappe.model.document import Document


class NPPKhoaChungTu(Document):
	def on_change(self):
		self._bao("UPSERT")

	def on_trash(self):
		self._bao("DELETE")

	def _bao(self, su_kien: str):
		frappe.publish_realtime(
			"npp_cong",
			{"bang": "entity_locks", "su_kien": su_kien, "entity_type": self.loai_chung_tu, "entity_id": self.chung_tu,
				"locked_by": self.nguoi_khoa},
			doctype="NPP Khoa Chung Tu",
			after_commit=True,
		)
