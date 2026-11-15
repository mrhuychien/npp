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
		"""Đẩy tới phòng của TỪNG NV đang làm (= entity_locks thấy được với mọi NV của NPP). Không dùng `doctype=` không kèm docname:
		lõi rơi vào phòng "all" mà chỉ System User vào (realtime/handlers.js) — NV NPP là Website User, không bao giờ nhận."""
		tin = {"bang": "entity_locks", "su_kien": su_kien, "entity_type": self.loai_chung_tu, "entity_id": self.chung_tu,
			"locked_by": self.nguoi_khoa}
		for nv in frappe.get_all("NPP Nhan Vien", filters={"dang_hoat_dong": 1, "nghi_viec_luc": ("is", "not set")}, pluck="name"):
			frappe.publish_realtime("npp_cong", tin, user=nv, after_commit=True)
