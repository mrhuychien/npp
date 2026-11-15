# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Phiếu thu tiền của khách (= `cash_receipts` + `cash_receipt_lines` + `payments` của nppsale; đặc tả phiếu thu §1.2).

Không submit: tiền nằm ở Payment Entry cùng tên (`but_toan_tien`, khi `tien_thu > 0`) và bút toán cấn trừ dư có `CTR-` (`but_toan_can_tru`).
Chỉ method `create_cash_receipt` / `void_cash_receipt` lập / huỷ; cổng chỉ cho ghi ghi chú + xác nhận (mig 214). Khoá tìm `tim_kd` =
`_trg_tim_kd('receipt_code', 'notes')`.
"""
from __future__ import annotations

import frappe
from frappe.model.document import Document

from nppsale.luat.tim import khoa_tim_ds


class NPPPhieuThu(Document):
	def validate(self):
		if self.khach_hang and (not self.ten_khach or self.has_value_changed("khach_hang")):
			self.ten_khach = frappe.db.get_value("Customer", self.khach_hang, "customer_name")
		self.tim_kd = khoa_tim_ds(self.name, self.ghi_chu)
