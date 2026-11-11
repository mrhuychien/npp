# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Tuyến bán hàng (= sales_routes). Khách tham chiếu tuyến bằng MÃ (Customer.npp_tuyen, chữ) — đổi mã / xoá tuyến thì màn tự sửa
khách theo mã như nppsale (route-form.tsx), cổng không thêm luật."""
from frappe.model.document import Document


class NPPTuyen(Document):
	pass
