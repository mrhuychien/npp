"""Purchase Invoice (phiếu nhập / trả NCC / nợ NCC — đặc tả kho_mua, blueprint 02 §5.9): khoá tìm `npp_tim_kd` = khoá của MÃ phiếu (`name`) — nguồn gộp
`stock_entries` của cổng đưa phiếu nhập / trả NCC vào danh sách phiếu kho mà ô tìm hỏi `tim_kd` (mig 249 — `entry_code`)."""
from __future__ import annotations

from nppsale.luat.tim import khoa_tim_ds


def validate(doc, method=None):
	if doc.meta.has_field("npp_tim_kd"):
		doc.npp_tim_kd = khoa_tim_ds(doc.name)
