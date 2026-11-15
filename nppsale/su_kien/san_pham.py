"""Item = products của nppsale (blueprint 02 phần Bán hàng §3.1).

validate: khoá tìm = khoa_tim_ds(SKU, tên, mã vạch đầu) như mig 205. Mọi thay đổi Item / Item Price / Price List → tăng số phiên danh
mục hàng (máy POS / NVBH tải lại sổ hàng — mig 209). Nhóm khách mới → bảng giá nhóm "Gia nhom <tên>" gắn làm bảng giá mặc định.
"""
from __future__ import annotations

import frappe

from nppsale.luat.tim import khoa_tim_ds
from nppsale.npp_he_thong.doctype.npp_phien_danh_muc.npp_phien_danh_muc import tang_phien_danh_muc

GIA_CHUAN = "Gia chuan"  # tên mặc định lúc lập — tên đang dùng ở NPP Cai Dat.bang_gia_chung
GIA_NHAP = "Gia nhap"  # — NPP Cai Dat.bang_gia_nhap

# Tên bảng giá trong câu SQL (đọc cài đặt lúc chạy câu — đổi cài đặt không cần nạp lại sổ đăng ký cổng)
BANG_GIA_CHUNG_SQL = ("COALESCE((SELECT s.`value` FROM `tabSingles` s WHERE s.`doctype` = 'NPP Cai Dat' AND s.`field` = 'bang_gia_chung'), "
	f"'{GIA_CHUAN}')")
BANG_GIA_NHAP_SQL = ("COALESCE((SELECT s.`value` FROM `tabSingles` s WHERE s.`doctype` = 'NPP Cai Dat' AND s.`field` = 'bang_gia_nhap'), "
	f"'{GIA_NHAP}')")


def bang_gia_chung() -> str:
	"""Bảng giá bán chung (nppsale: price_lists có group_id NULL) — NPP Cai Dat.bang_gia_chung, trống thì "Gia chuan"."""
	return frappe.db.get_single_value("NPP Cai Dat", "bang_gia_chung", cache=False) or GIA_CHUAN


def bang_gia_nhap() -> str:
	"""Bảng giá nhập (nppsale: purchase_price_lists) — NPP Cai Dat.bang_gia_nhap, trống thì "Gia nhap"."""
	return frappe.db.get_single_value("NPP Cai Dat", "bang_gia_nhap", cache=False) or GIA_NHAP


def validate_item(doc, method=None):
	ma_vach = doc.barcodes[0].barcode if doc.get("barcodes") else None
	doc.npp_tim_kd = khoa_tim_ds(doc.item_code, doc.item_name, ma_vach)


def thay_doi_hang(doc, method=None, *a, **k):
	tang_phien_danh_muc()


def thay_doi_gia_ban(doc, method=None, *a, **k):
	"""Item Price / Price List: chỉ dòng BÁN tăng số phiên danh mục (trg_phien_danh_muc_ban — mig 209: products, price_lists,
	product_units; KHÔNG purchase_price_lists). Giá nhập tự cập nhật mỗi lần phiếu nhập hoàn thành — tăng ở đó là mọi máy NVBH tải lại."""
	if doc.get("selling"):
		tang_phien_danh_muc()


def bang_gia_nhom(ten_nhom: str) -> str:
	return f"Gia nhom {ten_nhom}"[:140]


def dam_bao_bang_gia(ten: str, ban: bool = True):
	if frappe.db.exists("Price List", ten):
		return
	frappe.get_doc({"doctype": "Price List", "price_list_name": ten, "currency": "VND", "selling": 1 if ban else 0,
		"buying": 0 if ban else 1, "enabled": 1}).insert(ignore_permissions=True)


def nhom_khach_moi(doc, method=None):
	"""Nhóm khách (lá) mới → bảng giá nhóm riêng (nhóm khách = nhóm giá — nppsale customer_groups ↔ price_lists.group_id)."""
	if doc.is_group or doc.default_price_list:
		return
	ten = bang_gia_nhom(doc.name)
	dam_bao_bang_gia(ten, ban=True)
	frappe.db.set_value("Customer Group", doc.name, "default_price_list", ten)
