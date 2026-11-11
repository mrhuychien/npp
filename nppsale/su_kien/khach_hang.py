"""Customer = customers của nppsale (blueprint 02 §4.1).

validate: SĐT lưu bản chuẩn hoá như taoKhach / sdtDeLuu; khoá tìm = khoa_tim_ds(tên, chủ, SĐT, MST, địa chỉ, phường, quận, tỉnh) —
đúng thứ tự mig 203; toạ độ trong khoảng; khoá trường duyệt ảnh (chỉ RPC ghi — DUYET_QUA_NUT) và khoá vị trí khi đã duyệt mà người
sửa thiếu quyền customers.approve (VI_TRI_DA_DUYET). Mọi thay đổi → tăng số phiên khách (máy NVBH tải lại sổ khách).
"""
from __future__ import annotations

import frappe

from nppsale.cong.loi import NppLoi
from nppsale.luat.sdt import sdt_khach_de_luu
from nppsale.luat.tim import khoa_tim_ds
from nppsale.npp_he_thong.doctype.npp_phien_danh_muc.npp_phien_danh_muc import tang_phien_khach

COT_DUYET = ("npp_duyet_anh_luc", "npp_duyet_anh_boi")


def _co_quyen_duyet() -> bool:
	if frappe.session.user == "Administrator" or getattr(frappe.flags, "npp_duyet_anh_diem_ban", False):
		return True
	from nppsale.cong.ngu_canh import co_quyen, hien_tai

	return co_quyen(hien_tai(), "customers.approve")


def validate(doc, method=None):
	if doc.get("npp_sdt"):
		doc.npp_sdt = sdt_khach_de_luu(doc.npp_sdt) or None
	for f, lo, hi in (("npp_vi_do", -90, 90), ("npp_kinh_do", -180, 180)):
		v = doc.get(f) or 0
		if not (lo <= v <= hi):
			frappe.throw(f"{doc.meta.get_label(f)} ngoài khoảng {lo}..{hi}.")
	cu = doc.get_doc_before_save()
	if cu is not None and not getattr(frappe.flags, "npp_duyet_anh_diem_ban", False):
		for f in COT_DUYET:
			if doc.get(f) != cu.get(f) and frappe.session.user != "Administrator":
				raise NppLoi("DUYET_QUA_NUT", "Mốc duyệt ảnh + vị trí chỉ đổi qua nút Duyệt.")
		if cu.get("npp_duyet_anh_luc") and (doc.npp_vi_do != cu.npp_vi_do or doc.npp_kinh_do != cu.npp_kinh_do):
			if not _co_quyen_duyet():
				raise NppLoi("VI_TRI_DA_DUYET", "Vị trí điểm bán đã được duyệt — gửi yêu cầu dời vị trí để chủ NPP duyệt.")
	doc.npp_tim_kd = khoa_tim_ds(doc.customer_name, doc.get("npp_chu_cua_hang"), doc.get("npp_sdt"), doc.get("tax_id"),
		doc.get("npp_dia_chi"), doc.get("npp_phuong"), doc.get("npp_quan"), doc.get("npp_tinh"))


def thay_doi(doc, method=None):
	tang_phien_khach()
