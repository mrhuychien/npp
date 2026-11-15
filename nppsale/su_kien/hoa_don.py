"""Sales Invoice = sales_invoices (và tờ ghi có) của nppsale: khoá tìm = khoa_tim_ds(mã HĐ) như trigger `trg_zzzz_tim_kd` (mig 249) —
cột thật ghi lúc lưu (§2.8); tên đã đặt trước validate (cả tờ amend `HD-0001-1`). Thiếu là ô tìm số HĐ ở danh sách không ra tờ nào."""
from __future__ import annotations

from nppsale.luat.tim import khoa_tim_ds


def validate(doc, method=None):
	if doc.meta.has_field("npp_tim_kd"):
		doc.npp_tim_kd = khoa_tim_ds(doc.name)
