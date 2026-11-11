"""Quản lý nhân viên (route cũ /api/admin/users của nppsale) — chỉ chủ NPP.

	POST   /api/admin/users        tạo: User (email kỹ thuật <sđt>@nppsale.local, mật khẩu) + NPP Nhan Vien + mã QR — MỘT giao dịch
	                               (hỏng giữa chừng quay lui hết, không để tài khoản mồ côi như nhánh xoá bù của bản cũ)
	DELETE /api/admin/users/<id>   xoá: không tự xoá mình; NV đã có chứng từ → 409 CO_CHUNG_TU ("dùng Cho nghỉ việc")
Dạng trả về giữ nguyên ({success, id, token, loginUrl} / {error}) để màn Cài đặt › Người dùng của nppsale chạy không sửa.
"""
from __future__ import annotations

import frappe
from frappe.utils.password import update_password

from nppsale.luat.sdt import email_ky_thuat, sdt_hop_le

from .qr import phat_ma, url_dang_nhap
from .tuyen import YeuCauCu, tuyen

VAI_HOP_LE = ("owner", "manager", "accountant", "sales", "warehouse")


def _la_chu() -> bool:
	nv = frappe.db.get_value("NPP Nhan Vien", frappe.session.user, ["vai", "dang_hoat_dong", "nghi_viec_luc"], as_dict=True)
	return bool(nv and nv.vai == "owner" and nv.dang_hoat_dong and not nv.nghi_viec_luc)


@tuyen("POST", r"^/api/admin/users$")
def tao(yc: YeuCauCu):
	b = yc.json()
	sdt, mat_khau, ho_ten, vai = b.get("phone"), b.get("password"), b.get("full_name"), b.get("role")
	if not sdt or not mat_khau or not ho_ten or not vai:
		return 400, {"error": "Thiếu thông tin bắt buộc: số điện thoại, mật khẩu, họ tên, vai trò"}
	if not sdt_hop_le(sdt):
		return 400, {"error": f'Số điện thoại không hợp lệ: "{sdt}". Ví dụ đúng: 0909123456'}
	if not _la_chu():
		return 403, {"error": "Chỉ Chủ sở hữu mới được tạo người dùng"}
	if vai not in VAI_HOP_LE:
		return 400, {"error": f"Vai không hợp lệ: {vai}"}
	email = email_ky_thuat(sdt)
	if frappe.db.exists("User", email):
		return 400, {"error": "Số điện thoại đã được dùng cho tài khoản khác."}
	tu_do = vai in ("owner", "accountant")
	try:
		tran = max(0.0, min(100.0, float(b.get("price_edit_max_increase_pct") or 0)))
	except (TypeError, ValueError):
		tran = 0.0
	frappe.db.savepoint("tao_nv")
	try:
		frappe.get_doc({"doctype": "User", "email": email, "first_name": ho_ten, "send_welcome_email": 0, "enabled": 1}).insert(
			ignore_permissions=True
		)
		update_password(email, mat_khau)
		frappe.get_doc({
			"doctype": "NPP Nhan Vien", "user": email, "ho_ten": ho_ten, "vai": vai, "sdt": str(sdt).strip(), "dang_hoat_dong": 1,
			"cho_sua_gia": 1 if tu_do else (1 if b.get("allow_price_edit") is True else 0), "tran_tang_gia": tran,
		}).insert(ignore_permissions=True)
		token = phat_ma(email)
	except frappe.ValidationError as e:
		frappe.db.rollback(save_point="tao_nv")
		msg = str(e) or "Tạo tài khoản thất bại"
		if "PHONE_TAKEN" in msg or "đã được dùng" in msg:
			msg = "Số điện thoại đã được dùng cho tài khoản khác."
		return 400, {"error": msg}
	return 200, {"success": True, "id": email, "token": token, "loginUrl": url_dang_nhap(token)}


# Bản ghi trỏ tới NV mà nppsale khai ON DELETE CASCADE → xoá theo; SET NULL → đặt rỗng (DocType nào chưa có thì bỏ qua).
_XOA_THEO = [("NPP Quyen Rieng", "nhan_vien"), ("NPP Thong Bao", "nguoi_nhan"), ("NPP Khoa Chung Tu", "nguoi_khoa"),
	("NPP Phan Cong Khach", "nhan_vien"), ("NPP Lich Tuyen", "nhan_vien")]
_DAT_RONG = [("NPP Nhat Ky Don", "nguoi"), ("NPP Do Nap", "nguoi"), ("NPP Nhan Vien", "nghi_viec_boi")]


@tuyen("DELETE", r"^/api/admin/users/(?P<id>[^/]+)$")
def xoa(yc: YeuCauCu):
	dich = yc.tham["id"]
	if dich == frappe.session.user:
		return 400, {"error": "Không thể tự xóa tài khoản của mình"}
	if not _la_chu():
		return 403, {"error": "Chỉ Chủ sở hữu mới được xóa người dùng"}
	if not frappe.db.exists("NPP Nhan Vien", dich):
		return 404, {"error": "Không tìm thấy người dùng trong tổ chức"}
	frappe.db.savepoint("xoa_nv")
	try:
		for dt, truong in _XOA_THEO:
			if frappe.db.exists("DocType", dt):
				for ten in frappe.get_all(dt, filters={truong: dich}, pluck="name"):
					frappe.delete_doc(dt, ten, ignore_permissions=True, force=True)
		for dt, truong in _DAT_RONG:
			if frappe.db.exists("DocType", dt):
				frappe.db.sql(f"UPDATE `tab{dt}` SET `{truong}` = NULL WHERE `{truong}` = %s", (dich,))
		frappe.delete_doc("NPP Nhan Vien", dich, ignore_permissions=True)
		frappe.delete_doc("User", dich, ignore_permissions=True)
	except frappe.LinkExistsError as e:
		frappe.db.rollback(save_point="xoa_nv")
		return 409, {"error": "Nhân viên đã có chứng từ — không xoá được, dùng Cho nghỉ việc.", "code": "CO_CHUNG_TU",
			"chung_tu": {"chi_tiet": str(e)[:300]}}
	return 200, {"success": True}
