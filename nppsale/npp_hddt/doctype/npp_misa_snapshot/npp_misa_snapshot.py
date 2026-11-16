# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Ảnh chụp danh sách hoá đơn MISA kéo về (= `misa_invoice_snapshots`, mig 100) — blueprint 02 §4.6, đặc tả HĐĐT §1.2 (H21), §5.3.

`so_hddt_chuan` / `ky_hieu_chuan` (Postgres: cột GENERATED `inv_no_norm` / `inv_series_norm`) = ĐÚNG hàm khớp tầng 3 — `chuan_so` (normalizeInvNo,
`src/lib/misa/normalize.ts:20–26`) và `ky_hieu_chat` (strictSeries, `src/lib/misa/reconcile.ts:79–81`); một chỗ khai cho mọi nơi (Gotcha #9 — "hai bản
chuẩn hoá là hai màn hình khớp khác nhau"). H21: biểu thức GENERATED của Postgres khác hàm khớp ('000' giữ '000', chỉ bỏ dấu cách U+0020) — app không đọc
hai cột này nên dùng hàm khớp. Lượt kéo ghi bằng câu SQL gộp (không qua validate) → hàm ghi gọi `chuan_hoa_snapshot` cho từng dòng.
"""
from __future__ import annotations

import re

import frappe
from frappe.model.document import Document

# TODO(HĐĐT-2): bỏ hai hàm tạm + khối try khi `nppsale/luat/hddt.py` (tác tử khác đang viết) có `chuan_so` / `ky_hieu_chat` — lúc ấy khối import dưới
# tự dùng bản của tệp luật (bài nppsale.tests.test_hddt_khoa so hai bản trên cùng mẫu). Luật theo đặc tả HĐĐT §2.1–§2.2: trim / `\s` kiểu JavaScript.
# Khoảng trắng của trim() / \s trong JS (ECMAScript WhiteSpace + LineTerminator): KHÁC str.strip() của Python — JS có U+FEFF, Python có U+001C–U+001F, U+0085.
JS_KT = "\t\n\v\f\r                  　﻿"
_KT_JS = re.compile(f"[{re.escape(JS_KT)}]+")


def _chuan_so_tam(s) -> str:
	"""normalizeInvNo: None → ''; trim; rỗng → ''; bỏ số 0 ĐẦU; còn rỗng → '0'. Không bỏ khoảng trắng giữa ('00000123' → '123', '000' → '0')."""
	if s is None:
		return ""
	t = str(s).strip(JS_KT)
	if not t:
		return ""
	return t.lstrip("0") or "0"


def _ky_hieu_chat_tam(s) -> str:
	"""strictSeries: (v ?? '').trim().toUpperCase() rồi bỏ mọi khoảng trắng — GIỮ chữ số mẫu đầu ('1c26 taa' → '1C26TAA')."""
	return _KT_JS.sub("", str(s if s is not None else "").strip(JS_KT).upper())


try:
	from nppsale.luat.hddt import chuan_so, ky_hieu_chat
except ImportError:
	chuan_so, ky_hieu_chat = _chuan_so_tam, _ky_hieu_chat_tam


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
