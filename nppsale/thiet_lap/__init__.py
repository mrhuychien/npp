"""Thiết lập của app khi cài / sau mỗi lần migrate — chạy lại nhiều lần vẫn an toàn (mọi bước "đảm bảo có", không tạo trùng).

Thứ tự: vai (Role) → trường tuỳ biến trên DocType lõi → bản ghi mặc định của app (NPP Cai Dat, NPP Phien Danh Muc, dòng quyền vai
gieo sẵn). Bước nào cần DocType chưa có trên site (đang dựng dần theo giai đoạn) thì bỏ qua, không làm hỏng migrate.
"""
import frappe


def sau_khi_cai():
	_chay_het()


def sau_khi_migrate():
	_chay_het()


def _chay_het():
	from . import mac_dinh, truong_tuy_bien, vai

	vai.dam_bao()
	truong_tuy_bien.ap()
	mac_dinh.dam_bao()
	frappe.db.commit()
