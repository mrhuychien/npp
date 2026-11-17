# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Danh mục chi phí (= `expense_categories` của nppsale — blueprint 02 §4.5 `NPP Danh Muc Chi Phi`): `ma` duy nhất (UNIQUE org + code), `nhom` = nhóm
của báo cáo lãi lỗ kiểu nppsale, `tai_khoan` = TK Nợ của phiếu chi / TK chênh lệch của phiếu xuất hao hụt kiểm kê (trống → `NPP Cai Dat.tk_chi_phi_mac_dinh`).
Tám danh mục mẫu mig 016 gieo một lần khi cài site (nppsale.thiet_lap.kho_mua — `COGS_ADJ` là mã `post_stock_adjustment` tra để ghi hao hụt)."""
from __future__ import annotations

from frappe.model.document import Document


class NPPDanhMucChiPhi(Document):
	pass
