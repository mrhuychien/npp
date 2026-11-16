# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Nhật ký gọi MISA (= `einvoice_logs`, mig 072) — blueprint 02 §4.6. Chỉ method ghi, chỉ thêm (ngoại lệ duy nhất: `hddt` = NULL khi tờ HĐĐT nháp bị
xoá — on_trash của NPP HDDT, thay ON DELETE SET NULL). `gui_di` / `nhan_ve` ghi CHUỖI `json.dumps(…, ensure_ascii=False)`: payload phát hành là mảng,
gán list vào trường JSON thì lõi ném 'Value for … cannot be a list' (`frappe/model/document.py:2585–2586`). Không bao giờ chứa token / mật khẩu (I6).
Chỉ mục `hddt`, `goi_luc`: search_index trong JSON."""
from frappe.model.document import Document


class NPPMISALog(Document):
	pass
