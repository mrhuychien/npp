# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Ảnh điểm bán (= customer_photos), tối đa 3 ô / khách (UNIQUE khách + ô). Khách đã duyệt ảnh + vị trí → thêm / thay / xoá chỉ
người có quyền customers.approve, người khác phải gửi yêu cầu (ANH_DA_DUYET, mig 244). Xoá ảnh → yêu cầu đang trỏ tới mất ảnh gốc."""
import frappe
from frappe.model.document import Document

from nppsale.cong.loi import NppLoi


def _khoa(khach: str):
	if getattr(frappe.flags, "npp_duyet_anh_diem_ban", False) or frappe.session.user == "Administrator":
		return
	if not frappe.db.get_value("Customer", khach, "npp_duyet_anh_luc"):
		return
	from nppsale.cong.ngu_canh import co_quyen, hien_tai

	if not co_quyen(hien_tai(), "customers.approve"):
		raise NppLoi("ANH_DA_DUYET", "Ảnh điểm bán đã được duyệt — gửi yêu cầu đổi ảnh để chủ NPP duyệt.")


class NPPAnhDiemBan(Document):
	def validate(self):
		if not (1 <= int(self.o_anh or 0) <= 3):
			frappe.throw("Ô ảnh phải là 1, 2 hoặc 3.")
		_khoa(self.khach)

	def after_insert(self):
		from nppsale.rpc.anh_diem_ban import bao_anh_dau_cho_duyet

		bao_anh_dau_cho_duyet(self)

	def on_trash(self):
		_khoa(self.khach)
		if frappe.db.exists("DocType", "NPP Yeu Cau Anh Diem Ban"):
			frappe.db.sql("UPDATE `tabNPP Yeu Cau Anh Diem Ban` SET `anh` = NULL WHERE `anh` = %s", (self.name,))


def on_doctype_update():
	frappe.db.add_unique("NPP Anh Diem Ban", ["khach", "o_anh"], "uq_anh_diem_ban_o")
