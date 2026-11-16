# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Ảnh chụp danh sách hoá đơn MISA kéo về (= `misa_invoice_snapshots`, mig 100) — blueprint 02 §4.6, đặc tả HĐĐT §1.2 (H21), §5.3.

`so_hddt_chuan` / `ky_hieu_chuan` (Postgres: cột GENERATED `inv_no_norm` / `inv_series_norm`) = ĐÚNG hàm khớp tầng 3 của `nppsale/luat/hddt.py` —
`chuan_so` (normalizeInvNo, `src/lib/misa/normalize.ts:20–26`) và `ky_hieu_chat` (strictSeries, `src/lib/misa/reconcile.ts:79–81`); một chỗ khai cho mọi
nơi (Gotcha #9 — "hai bản chuẩn hoá là hai màn hình khớp khác nhau"). H21: biểu thức GENERATED của Postgres khác hàm khớp ('000' giữ '000', chỉ bỏ dấu
cách U+0020) — app không đọc hai cột này nên dùng hàm khớp. Lượt kéo ghi bằng câu SQL gộp (không qua validate) → hàm ghi gọi `chuan_hoa_snapshot`.
"""
from __future__ import annotations

import frappe
from frappe.model.document import Document

from nppsale.luat.hddt import chuan_so, ky_hieu_chat


def chuan_hoa_snapshot(ky_hieu, so_hddt) -> tuple[str, str]:
	"""(ky_hieu_chuan, so_hddt_chuan) của một bản ghi — validate và hàm ghi lượt kéo (câu ghi gộp) dùng chung."""
	return ky_hieu_chat(ky_hieu), chuan_so(so_hddt)


class NPPMISASnapshot(Document):
	def validate(self):
		self.ky_hieu_chuan, self.so_hddt_chuan = chuan_hoa_snapshot(self.ky_hieu, self.so_hddt)


def on_doctype_update():
	# idx_misa_snapshot_no (org_id, inv_series_norm, inv_no_norm) và idx_misa_snapshot_status (org_id, match_status, inv_date DESC) của mig 100;
	# một cột (ma_tra_cuu — tầng khớp 2, hddt) khai search_index trong JSON; ref_id duy nhất (uq_misa_snapshot_ref) là cờ unique của trường
	frappe.db.add_index("NPP MISA Snapshot", ["ky_hieu_chuan", "so_hddt_chuan"], "idx_snapshot_ky_hieu_so")
	frappe.db.add_index("NPP MISA Snapshot", ["ket_qua_khop", "ngay_phat_hanh"], "idx_snapshot_ket_qua_ngay")
