# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Cài đặt của NPP (Single) — thay `organizations`, `pricing_rules`, `approval_rules` của nppsale. Một site một NPP: `org_id` là
hằng cổng trả cho mọi cột `org_id`."""
import frappe
from frappe import _
from frappe.model.document import Document


class NPPCaiDat(Document):
	def validate(self):
		if self.nguong_kho_date_ngay is not None and not (0 <= int(self.nguong_kho_date_ngay) <= 365):
			frappe.throw(_("Số ngày tự chuyển kho date phải trong khoảng 0–365."))
		for t in ("tu_duyet_toi_da", "quan_ly_duyet_toi_da", "no_khach_toi_da", "no_qua_han_toi_da", "no_danh_muc_nv_toi_da"):
			if (self.get(t) or 0) < 0:
				frappe.throw(_("{0} không được âm.").format(self.meta.get_label(t)))
		cu = self.get_doc_before_save()
		if cu and cu.org_id and self.org_id != cu.org_id:
			frappe.throw(_("Không đổi được mã đơn vị của site."))

	def on_update(self):
		if self.cong_ty and self.ma_so_thue is not None:
			if frappe.db.get_value("Company", self.cong_ty, "tax_id") != self.ma_so_thue:
				frappe.db.set_value("Company", self.cong_ty, "tax_id", self.ma_so_thue)
		frappe.clear_document_cache("NPP Cai Dat", "NPP Cai Dat")


def org_id() -> str:
	"""Mã đơn vị (UUID) cổng trả cho mọi cột org_id — đọc từ bộ nhớ đệm của tài liệu Single."""
	return frappe.get_cached_value("NPP Cai Dat", "NPP Cai Dat", "org_id") or ""
