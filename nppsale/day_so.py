"""Dãy số đặt tên (`tabSeries`) — xoá bản ghi mà KHÔNG lùi dãy (một luật cho mọi chỗ xoá bản ghi đặt tên theo dãy).

Lõi lùi `tabSeries` khi xoá bản ghi mang số CUỐI của dãy: `frappe.delete_doc` → `update_naming_series` (`frappe/model/delete_doc.py:250-256`) →
`naming.revert_series_if_last` (`frappe/model/naming.py:426-478`) — với `naming_series:` (NCC-, KH-, DH-, IN-/XKL-/CKL-, PN-/PTNCC-…) lẫn autoname
kiểu `PT-.####` / `KK-.YY.MM.DD.-.####`; `rename_doc(merge=True)` cũng xoá tên cũ bằng `delete_doc` (`frappe/model/rename_doc.py:208-209`). Bản ghi lập
sau nhận lại ĐÚNG tên ấy — mà tên Frappe là id của cổng: màn còn giữ id cũ (danh sách, chi tiết, tab khác, link thông báo, bản nháp hỏng màn đang dọn)
chạm nhầm bản ghi mới của người khác. nppsale: id uuid (`gen_random_uuid()`) không bao giờ dùng lại; mã chứng từ / mã danh mục lấy từ bộ đếm không lùi.

Dùng ở: phiếu kho / phiếu nhập / trả NCC / kiểm kê nháp (`rpc.kho_tay.xoa_nhap` — soát P4 F2), xoá NCC + gộp NCC (`rpc.nha_cung_cap` — P4 đuôi),
phiếu trả nháp (`rpc.phieu_tra.xoa_phieu`), đơn nháp + phiếu trả của đơn (`rpc.sua_don.xoa_don`), bộ ghi chung của cổng (`cong.bang._chung.GhiDocType.xoa`
— khách `KH-`; bảng UUID không đổi gì). Bản ghi đặt tên theo trường / hash / UUID / `format:` không có dãy để lùi (lõi bỏ qua hoặc không khớp dòng nào).
"""
from __future__ import annotations

from contextlib import contextmanager

import frappe


def _tien_to(ten) -> tuple:
	return tuple(sorted({t[:i] for t in ten if isinstance(t, str) and t for i in range(1, len(t))}))


@contextmanager
def giu_day_so(*ten: str):
	"""Trong khối: dãy nào là TIỀN TỐ của một tên trong `ten` (vd `NCC-` của `NCC-0012`) giữ số đếm — lõi lùi thì đặt lại đúng số trước khối. Chỉ NÂNG
	về số cũ, không bao giờ hạ (bản ghi khác lập song song đã đẩy số lên thì giữ; lõi khoá dòng `tabSeries` FOR UPDATE khi lùi)."""
	tt = _tien_to(ten)
	truoc = frappe.db.sql("SELECT `name`, `current` FROM `tabSeries` WHERE `name` IN %s", (tt,)) if tt else ()
	try:
		yield
	finally:
		for day, hien in truoc:
			frappe.db.sql("UPDATE `tabSeries` SET `current` = %s WHERE `name` = %s AND `current` < %s", (hien, day, hien))


def xoa_giu_day_so(dt: str, ten: str, **kw) -> None:
	"""`frappe.delete_doc(dt, ten, ignore_permissions=True, **kw)` mà KHÔNG lùi dãy số (lỗi liên kết… của lõi ném nguyên như cũ)."""
	with giu_day_so(ten):
		frappe.delete_doc(dt, ten, ignore_permissions=True, **kw)
