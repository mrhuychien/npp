# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Phiếu kiểm kê (= `stock_entries` dòng `type = 'stocktake'` + `stock_entry_lines` của nó — đặc tả kho_mua §1.1, §3.17, §3.18, §4.5; blueprint 02
§4.4 `NPP Kiem Ke`; CFD-09: KHÔNG dùng Stock Reconciliation).

Không submit — trạng thái là trường (`draft` chờ duyệt / `posted` / `cancelled`); chứng từ lõi phía dưới là hai Stock Entry `DCK-` (xuất phần hụt / nhập
phần thừa) do `post_stock_adjustment` lập và ghi sổ (nppsale.rpc.kiem_ke). Cổng `stock_entries` lập / sửa / xoá phiếu NHÁP (nppsale.rpc.kiem_ke); đổi
trạng thái chỉ qua RPC (duyệt / từ chối / huỷ phiếu kho) hoặc lệnh cổng `draft → cancelled` (trigger mig 170 cho đúng một chiều ấy). Khoá tìm `tim_kd` =
khoá của `entry_code` (`_trg_tim_kd('entry_code')`, mig 249) — `entry_code` của cổng là tên phiếu.
"""
from __future__ import annotations

from frappe.model.document import Document

from nppsale.luat.tim import khoa_tim_ds


class NPPKiemKe(Document):
	def validate(self):
		self.tim_kd = khoa_tim_ds(self.name)
