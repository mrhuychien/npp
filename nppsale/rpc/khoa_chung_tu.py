"""Khoá sửa đồng thời một chứng từ (mig 046 / 053): acquire / heartbeat / release_entity_lock, dọn khoá quá 10 phút không nhịp.
Bảng: NPP Khoa Chung Tu, tên = "loại:chứng từ" — giành khoá là chèn, trùng tên = người khác vừa giành trước."""
from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai

from . import rpc

QUA_HAN_PHUT = 10


def release_stale_entity_locks() -> int:
	"""Xoá khoá quá 10 phút không nhịp (nppsale: pg_cron mỗi phút + dọn lười trong acquire / heartbeat)."""
	frappe.db.sql(f"DELETE FROM `tabNPP Khoa Chung Tu` WHERE `nhip_cuoi` < NOW(6) - INTERVAL {QUA_HAN_PHUT} MINUTE")
	return frappe.db._cursor.rowcount if getattr(frappe.db, "_cursor", None) else 0


def _ten(loai: str, id_: str) -> str:
	return f"{loai}:{id_}"


def _nguoi_goi() -> str:
	nc = hien_tai()
	if not nc.vai:
		raise NppLoi("NOT_AUTHENTICATED")
	return nc.user


@rpc("acquire_entity_lock", ghi=True)
def acquire_entity_lock(p_entity_type: str, p_entity_id: str):
	uid = _nguoi_goi()
	release_stale_entity_locks()
	ten = _ten(p_entity_type, p_entity_id)
	for _ in range(2):
		cu = frappe.db.get_value("NPP Khoa Chung Tu", ten, ["nguoi_khoa", "khoa_luc"], as_dict=True)
		if cu:
			ten_nv = frappe.db.get_value("NPP Nhan Vien", cu.nguoi_khoa, "ho_ten")
			if cu.nguoi_khoa == uid:
				frappe.db.set_value("NPP Khoa Chung Tu", ten, "nhip_cuoi", now_datetime(), update_modified=False)
				return [{"ok": True, "holder_id": uid, "holder_name": ten_nv, "locked_at": cu.khoa_luc}]
			return [{"ok": False, "holder_id": cu.nguoi_khoa, "holder_name": ten_nv, "locked_at": cu.khoa_luc}]
		bay_gio = now_datetime()
		try:
			frappe.get_doc({"doctype": "NPP Khoa Chung Tu", "loai_chung_tu": p_entity_type, "chung_tu": p_entity_id, "nguoi_khoa": uid,
				"khoa_luc": bay_gio, "nhip_cuoi": bay_gio}).insert(ignore_permissions=True)
			return [{"ok": True, "holder_id": uid, "holder_name": frappe.db.get_value("NPP Nhan Vien", uid, "ho_ten"), "locked_at": bay_gio}]
		except frappe.DuplicateEntryError:
			continue  # người khác vừa giành trước — đọc lại để trả người giữ
	return [{"ok": False, "holder_id": None, "holder_name": None, "locked_at": None}]


@rpc("heartbeat_entity_lock", ghi=True)
def heartbeat_entity_lock(p_entity_type: str, p_entity_id: str):
	nc = hien_tai()
	if not nc.vai:
		return False
	release_stale_entity_locks()
	ten = _ten(p_entity_type, p_entity_id)
	if frappe.db.get_value("NPP Khoa Chung Tu", ten, "nguoi_khoa") != nc.user:
		return False
	frappe.db.set_value("NPP Khoa Chung Tu", ten, "nhip_cuoi", now_datetime(), update_modified=False)
	return True


@rpc("release_entity_lock", ghi=True)
def release_entity_lock(p_entity_type: str, p_entity_id: str):
	nc = hien_tai()
	if not nc.vai:
		return False
	ten = _ten(p_entity_type, p_entity_id)
	if frappe.db.get_value("NPP Khoa Chung Tu", ten, "nguoi_khoa") != nc.user:
		return False
	frappe.delete_doc("NPP Khoa Chung Tu", ten, ignore_permissions=True)
	return True
