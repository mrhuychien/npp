# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Yêu cầu đổi ảnh / vị trí điểm bán đã duyệt (= customer_photo_requests, mig 244). Một ô ảnh / một vị trí chỉ một yêu cầu chờ:
`khoa_cho` (unique) = "<khách>:o<ô>" hoặc "<khách>:vitri" khi đang chờ, rỗng khi rời trạng thái chờ — thay chỉ mục duy nhất có
điều kiện của Postgres. Chỉ RPC ghi."""
import frappe
from frappe.model.document import Document


class NPPYeuCauAnhDiemBan(Document):
	def validate(self):
		loai = self.loai or ""
		if loai.startswith("photo_"):
			if not (1 <= int(self.o_anh or 0) <= 3):
				frappe.throw("Yêu cầu ảnh phải có ô 1..3.")
			if loai in ("photo_add", "photo_replace") and not (self.anh_url and self.chup_luc):
				frappe.throw("Yêu cầu ảnh mới phải có ảnh và giờ chụp.")
		if loai == "pin_set":
			if not (-90 <= (self.vi_do_ghim or 0) <= 90 and -180 <= (self.kinh_do_ghim or 0) <= 180) or not (self.vi_do_ghim or self.kinh_do_ghim):
				frappe.throw("Yêu cầu dời vị trí phải có toạ độ hợp lệ.")
		if self.trang_thai == "pending":
			self.khoa_cho = f"{self.khach}:o{int(self.o_anh)}" if loai.startswith("photo_") else f"{self.khach}:vitri"
		else:
			self.khoa_cho = None


def on_doctype_update():
	frappe.db.add_index("NPP Yeu Cau Anh Diem Ban", ["khach", "trang_thai"], "idx_yc_anh_khach_tt")
