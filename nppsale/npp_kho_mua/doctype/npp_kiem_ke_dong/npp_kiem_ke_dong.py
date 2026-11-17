# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Dòng chênh lệch của phiếu kiểm kê (= `stock_entry_lines` của phiếu `stocktake` — blueprint 02 §4.4 `NPP Kiem Ke Dong`): `chenh_lech` có dấu theo
đơn vị cơ sở (`quantity` — cột `post_stock_adjustment` đọc), `lo` + `kho` = lô đã đếm (cổng tách từ `batch_id` `<lô>::<vùng>`; hàng không lô chỉ có
`kho` — lô ảo `~<mã>::<vùng>`); dòng không lô được duyệt điền lô / kho đầu tiên đã đụng (mig 123)."""
from __future__ import annotations

from frappe.model.document import Document


class NPPKiemKeDong(Document):
	pass
