# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Cấu hình kết nối MISA meInvoice (= `company_einvoice_config` của nppsale, mig 072 / 075–079 — một dòng / NPP = một Single / site) — blueprint 02
§4.6, đặc tả HĐĐT §1.2 / §1.7.

"Đã lưu" = có dòng `tabSingles` của `nha_cung_cap` (`da_luu`): `frappe.get_single` của Single chưa lưu vẫn trả mặc định (`dang_dung` = 1, địa chỉ
API thử) nên không dùng để biết "chưa cấu hình" (cổng `company_einvoice_config` ra 0 dòng, GET /api/einvoice/config trả `{config: null}`). Vì thế
KHÔNG bước cài đặt / migrate nào được lưu Single này: `init_singles()` của lõi (`frappe/installer.py:595–610`, chạy trong `post_install` ở MỖI lần
cài một app lên site) lưu mọi Single chưa có dòng (bỏ validate + bắt buộc) → `save` / `insert` bỏ qua khi `frappe.flags.in_install`.

Hai trường Password (`tai_khoan` / `mat_khau`) nằm ở `__Auth`, mã bằng `encryption_key` của site; bảng `tabSingles` chỉ giữ dấu `*`. `co_bi_mat`
trả has_username / has_password mà KHÔNG giải mã (GET cấu hình không được hỏng vì khoá site sai). Bẫy của lõi cho nơi ghi (đặc tả §1.7): gán
'' / None rồi save() là XOÁ bản mã (`Document._save_passwords`, `frappe/model/document.py:3399–3400`) ⇒ chỉ gán khi người gõ giá trị khác rỗng;
`db_set` / `set_single_value` bỏ qua mã hoá (lưu chữ thường) ⇒ cấm cho hai trường này; `get_password(..., raise_exception=False)`.
"""
from __future__ import annotations

import frappe
from frappe.model.document import Document

TEN = "NPP MISA Cau Hinh"
TRUONG_BI_MAT = ("tai_khoan", "mat_khau")


class NPPMISACauHinh(Document):
	def save(self, *args, **kwargs):
		if frappe.flags.in_install:  # init_singles() của lõi — lưu là đánh dấu "đã cấu hình" một kết nối chưa ai nhập
			return self
		return super().save(*args, **kwargs)

	def insert(self, *args, **kwargs):
		if frappe.flags.in_install:
			return self
		return super().insert(*args, **kwargs)


def da_luu() -> bool:
	"""Chủ / KT đã lưu cấu hình lần nào chưa (route cấu hình, phát hành "chưa cấu hình", cổng `company_einvoice_config` 0 dòng)."""
	return bool(frappe.db.sql("SELECT 1 FROM `tabSingles` WHERE `doctype` = %s AND `field` = 'nha_cung_cap' LIMIT 1", TEN))


def co_bi_mat(truong: str) -> bool:
	"""has_username (`tai_khoan`) / has_password (`mat_khau`): có bản mã ở `__Auth` — không giải mã."""
	if truong not in TRUONG_BI_MAT:
		raise ValueError(truong)
	return bool(frappe.db.sql("""SELECT 1 FROM `__Auth` WHERE `doctype` = %s AND `name` = %s AND `fieldname` = %s AND `encrypted` = 1
		AND IFNULL(`password`, '') != '' LIMIT 1""", (TEN, TEN, truong)))
