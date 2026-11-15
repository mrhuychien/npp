"""Cột Link trỏ tới DocType đặt tên `UUID` phải cùng kiểu `uuid` với khoá đích (blueprint 02 §2.3, §4.8.0, §7.2).

Frappe dựng cột Link kiểu `uuid` chỉ khi DocType đích đã có lúc tạo bảng; cài mới thì tuỳ thứ tự `os.listdir` — bảng tạo trước đích ra `varchar(140)`
và migrate sau không sửa (DocType không đổi thì không đồng bộ lại). Hệ quả: so / nối hai kiểu khác nhau (UNION với `NPP LS *`, COALESCE) ra NULL
lặng lẽ. Bước này chạy ở after_install + after_migrate: mọi Link (DocField + Custom Field) tới DocType `autoname = UUID` mà cột còn khác `uuid` →
đổi `''` thành NULL rồi `ALTER TABLE … MODIFY … uuid`. Lỗi (giá trị không phải UUID) thì ghi Error Log, không làm hỏng migrate.
"""
from __future__ import annotations

import frappe


def cot_can_doi() -> list[tuple[str, str]]:
	dich = frappe.get_all("DocType", filters={"autoname": "UUID"}, pluck="name")
	if not dich:
		return []
	ra = []
	for dt, cot in frappe.db.sql("""SELECT `parent`, `fieldname` FROM `tabDocField` WHERE `fieldtype` = 'Link' AND `options` IN %(d)s
			UNION SELECT `dt`, `fieldname` FROM `tabCustom Field` WHERE `fieldtype` = 'Link' AND `options` IN %(d)s""", {"d": tuple(dich)}):
		if not frappe.db.exists("DocType", dt) or frappe.get_meta(dt).issingle:
			continue
		k = frappe.db.sql("""SELECT `DATA_TYPE` FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = %s
			AND column_name = %s""", (f"tab{dt}", cot))
		if k and k[0][0] != "uuid":
			ra.append((dt, cot))
	return ra


def dam_bao() -> None:
	for dt, cot in cot_can_doi():
		bang = f"tab{dt}"
		try:
			frappe.db.sql(f"UPDATE `{bang}` SET `{cot}` = NULL WHERE `{cot}` = ''")
			frappe.db.sql_ddl(f"ALTER TABLE `{bang}` MODIFY `{cot}` uuid")
		except Exception:  # noqa: BLE001
			frappe.log_error(title=f"Không đổi được {dt}.{cot} sang uuid", message=frappe.get_traceback())
