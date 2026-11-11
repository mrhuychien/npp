"""Sales Order = sales_orders của nppsale: khoá tìm = khoa_tim_ds(mã đơn) như mig 249 (tên đã đặt trước validate)."""
from __future__ import annotations

from nppsale.luat.tim import khoa_tim_ds


def validate(doc, method=None):
	if doc.meta.has_field("npp_tim_kd"):
		doc.npp_tim_kd = khoa_tim_ds(doc.name)
