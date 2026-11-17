"""Stock Entry (phiếu kho tay `IN-` / `DK-` / `XKL-` / `CKL-` / `DCK-`, phiếu nhập lại hàng khách trả `NL-` của P3 — đặc tả kho_mua §4.5): khoá tìm
`npp_tim_kd` = khoá của MÃ phiếu (`name`; nppsale `tim_kd = khoa_tim_ds(entry_code)` — trigger `trg_zzzz_tim_kd`, mig 249) ở MỌI lần lưu đi qua
`validate`. Soát P4: phiếu do method lập thẳng (nhập kho tay nhánh Stock Entry `_phieu_nhap_kho`, nhập lại hàng trả `phieu_tra._lap_phieu_nhap`) từng
không có khoá → cổng `stock_entries` lùi về `LOWER(name)`, gõ mã liền / bỏ số 0 ("NL0012", "nl12") không ra trong khi `PN-` cùng danh sách thì ra.
Nháp lưu qua cổng bỏ `validate` của lõi (`flags.ignore_validate` — nppsale.rpc.kho_tay._luu_nhap) → đặt thẳng ở `kho_tay._dat_tim`."""
from __future__ import annotations

from nppsale.luat.tim import khoa_tim_ds


def validate(doc, method=None):
	if doc.meta.has_field("npp_tim_kd"):
		doc.npp_tim_kd = khoa_tim_ds(doc.name)
