"""Nhắc định kỳ về khách — thay /api/customers/photo-reminders (thứ Hai giờ VN) và /api/customers/route-reminders (hằng ngày) trong
cron hằng ngày của nppsale (vercel.json: 18:00 UTC = 01:00 VN). Luật chọn / gộp / câu chữ ở nppsale.luat.nhac.

Khách "đang bán" = npp_trang_thai = active. NV phụ trách chính = NPP Phan Cong Khach vai_tro primary đang hiệu lực. Mỗi NV một thông báo
gộp; khách đã nhắc trong thời gian hạ nhiệt thì bỏ qua; đóng dấu thời điểm nhắc lên khách SAU khi ghi được thông báo.
"""
from __future__ import annotations

import frappe
from frappe.utils import get_datetime, now_datetime

from nppsale.luat.nhac import (
	KhachNhacAnh,
	KhachNhacTuyen,
	lap_nhac_anh,
	lap_nhac_tuyen,
	noi_dung_nhac_anh,
	noi_dung_nhac_tuyen,
)
from nppsale.npp_he_thong.doctype.npp_thong_bao.npp_thong_bao import gui_thong_bao


def _epoch(v) -> float | None:
	return get_datetime(v).timestamp() if v else None


def _nv_chinh() -> dict:
	ra = {}
	for khach, nv in frappe.db.sql("""SELECT `khach`, `nhan_vien` FROM `tabNPP Phan Cong Khach`
			WHERE `vai_tro` = 'primary' AND `trang_thai` = 'active' ORDER BY `name`"""):
		ra.setdefault(khach, nv)
	return ra


def _dong_dau(khach: list[str], truong: str, luc):
	for i in range(0, len(khach), 200):
		frappe.db.sql(f"UPDATE `tabCustomer` SET `{truong}` = %(luc)s WHERE `name` IN %(ds)s", {"luc": luc, "ds": tuple(khach[i:i + 200])})


def nhac_anh_diem_ban(commit: bool = True) -> dict:
	"""Thứ Hai 01:00 giờ VN: điểm bán đang bán thiếu ảnh hoặc vị trí → nhắc NV phụ trách chính (mỗi người một thông báo, hạ nhiệt 7
	ngày)."""
	luc = now_datetime()
	so_anh = dict(frappe.db.sql("SELECT `khach`, COUNT(*) FROM `tabNPP Anh Diem Ban` GROUP BY `khach`"))
	nv = _nv_chinh()
	ds = [KhachNhacAnh(r.name, r.customer_name, int(so_anh.get(r.name, 0)), bool(r.npp_vi_do) and bool(r.npp_kinh_do),
		_epoch(r.npp_nhac_anh_luc), nv.get(r.name))
		for r in frappe.db.sql("""SELECT `name`, `customer_name`, `npp_vi_do`, `npp_kinh_do`, `npp_nhac_anh_luc` FROM `tabCustomer`
			WHERE `npp_trang_thai` = 'active' ORDER BY `customer_name`, `name`""", as_dict=True)]
	ke = lap_nhac_anh(ds, luc.timestamp())
	bao = {"notified_reps": 0, "customers_flagged": 0, "unassigned": len(ke["khong_ai"]), "cooled_down": ke["hoa_nhiet"]}
	for nguoi, khach in ke["theo_nv"]:
		tieu_de, noi_dung = noi_dung_nhac_anh(khach)
		gui_thong_bao(nguoi, "customer_photo_missing", tieu_de, noi_dung, "/customers/missing-photos",
			{"customer_ids": [k.id for k in khach]})
		_dong_dau([k.id for k in khach], "npp_nhac_anh_luc", luc)
		bao["notified_reps"] += 1
		bao["customers_flagged"] += len(khach)
	if commit:
		frappe.db.commit()
	return bao


def nhac_khach_chua_tuyen(commit: bool = True) -> dict:
	"""Hằng ngày 01:00 giờ VN (mig 221): khách đang bán chưa có tuyến → NV phụ trách chính, không ai phụ trách thì mọi chủ / quản lý
	đang làm; hạ nhiệt 3 ngày."""
	luc = now_datetime()
	nv = _nv_chinh()
	ds = [KhachNhacTuyen(r.name, r.customer_name, r.npp_tuyen, _epoch(r.npp_nhac_tuyen_luc), nv.get(r.name))
		for r in frappe.db.sql("""SELECT `name`, `customer_name`, `npp_tuyen`, `npp_nhac_tuyen_luc` FROM `tabCustomer`
			WHERE `npp_trang_thai` = 'active' ORDER BY `customer_name`, `name`""", as_dict=True)]
	quan_ly = frappe.get_all("NPP Nhan Vien", filters={"vai": ("in", ("owner", "manager")), "dang_hoat_dong": 1,
		"nghi_viec_luc": ("is", "not set")}, pluck="name", order_by="name")
	ke = lap_nhac_tuyen(ds, quan_ly, luc.timestamp())
	da_nhac: dict = {}
	bao = {"notified": 0, "customers_flagged": 0, "cooled_down": ke["hoa_nhiet"], "no_recipient": ke["khong_nguoi_nhan"]}
	for nguoi, khach in ke["theo_nguoi"]:
		tieu_de, noi_dung = noi_dung_nhac_tuyen(khach)
		gui_thong_bao(nguoi, "customer_route_missing", tieu_de, noi_dung, "/customers?tuyen=chua", {"customer_ids": [k.id for k in khach]})
		bao["notified"] += 1
		for k in khach:
			da_nhac[k.id] = True
	if da_nhac:
		_dong_dau(list(da_nhac), "npp_nhac_tuyen_luc", luc)
		bao["customers_flagged"] = len(da_nhac)
	if commit:
		frappe.db.commit()
	return bao
