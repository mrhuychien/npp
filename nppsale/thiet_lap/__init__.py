"""Thiết lập của app khi cài / sau mỗi lần migrate — chạy lại nhiều lần vẫn an toàn (mọi bước "đảm bảo có", không tạo trùng).

Thứ tự: vai (Role) → DocPerm sàn (vai NPP đọc danh mục lõi) → trường tuỳ biến trên DocType lõi → bản ghi mặc định của app (NPP Cai Dat, NPP Phien Danh Muc, dòng quyền vai
gieo sẵn) → sổ sách bán hàng (kho, tài khoản VAT, mẫu thuế, điều khoản thanh toán — khi site đã có công ty) → cài đặt kho / mua hàng P4 (Single lõi,
Property Setter, TK thuế đầu vào — `kho_mua`, kèm bộ kiểm cài đặt). Bước nào cần DocType chưa có trên site (đang dựng dần theo giai đoạn) thì bỏ qua, không làm hỏng migrate.
"""


def sau_khi_cai():
	_chay_het()


def sau_khi_migrate():
	_chay_het()


def _chay_het():
	import frappe

	from . import ban_hang, cot_uuid, kho_mua, mac_dinh, quyen_san, truong_tuy_bien, vai

	vai.dam_bao()
	quyen_san.dam_bao()
	truong_tuy_bien.ap()
	cot_uuid.dam_bao()
	mac_dinh.dam_bao()
	ban_hang.dam_bao()
	kho_mua.dam_bao()
	frappe.db.commit()
	kho_mua.ghi_nhat_ky_lech()  # bộ kiểm cài đặt P4: còn lệch → Error Log
	frappe.db.commit()
