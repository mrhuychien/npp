# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Nhân viên của NPP (= users + user_suppliers + qr_login_tokens). Tên bản ghi = User.name = email kỹ thuật <sđt>@nppsale.local —
cổng trả làm `users.id`. Mỗi lần lưu đồng bộ sang User: họ tên, SĐT chuẩn hoá (đăng nhập), bật / tắt, Role theo vai."""
import frappe
from frappe import _
from frappe.model.document import Document

from nppsale.luat.sdt import chuan_hoa_sdt, sdt_hop_le
from nppsale.luat.tim import khoa_tim_ds
from nppsale.thiet_lap.vai import ROLE_VAI, VAI_ROLE


class NPPNhanVien(Document):
	def validate(self):
		cu = self.get_doc_before_save()
		if self.vai == "driver" and (self.is_new() or (cu and cu.vai != "driver")):
			frappe.throw(_("Vai Tài xế đã ngưng — không gán mới được."), title="ROLE_RETIRED")
		self._kiem_sdt()
		if not (0 <= (self.tran_tang_gia or 0) <= 100):
			frappe.throw(_("Trần tăng giá phải trong khoảng 0–100%."))
		if self.co_tran_giam:
			if (self.tran_giam or 0) < 0:
				frappe.throw(_("Trần giảm không được âm."))
			if self.kieu_tran_giam == "pct" and self.tran_giam > 100:
				frappe.throw(_("Trần giảm theo % không quá 100."))
			if self.kieu_tran_giam == "vnd":
				self.tran_giam = round(self.tran_giam or 0)
		else:
			self.tran_giam = 0
		thay = set()
		for d in self.cong_ty or []:
			if d.nha_cung_cap in thay:
				frappe.throw(_("Công ty {0} bị chọn hai lần.").format(d.nha_cung_cap))
			thay.add(d.nha_cung_cap)
		self.khoa_tim = khoa_tim_ds(self.ho_ten, self.sdt)

	def _kiem_sdt(self):
		if not self.sdt:
			return
		if not sdt_hop_le(self.sdt):
			frappe.throw(_("Số điện thoại không hợp lệ: {0}").format(self.sdt))
		chuan = chuan_hoa_sdt(self.sdt)
		for ten, sdt in frappe.db.sql("SELECT name, sdt FROM `tabNPP Nhan Vien` WHERE name != %s AND IFNULL(sdt, '') != ''", (self.name or "",)):
			if chuan_hoa_sdt(sdt) == chuan:
				frappe.throw(_("Số điện thoại đã được dùng cho tài khoản khác."), title="PHONE_TAKEN")

	def on_update(self):
		dong_bo_user(self)


def dong_bo_user(nv):
	"""User ← NPP Nhan Vien: first_name, mobile_no (chuẩn hoá, unique ở lõi), enabled, Role của vai. Tắt → xoá mọi phiên đang mở
	(lõi không tự xoá phiên khi tắt User)."""
	u = frappe.get_doc("User", nv.user)
	bat_truoc = bool(u.enabled)
	u.first_name = nv.ho_ten
	u.mobile_no = chuan_hoa_sdt(nv.sdt) or None
	u.enabled = 1 if nv.dang_hoat_dong else 0
	role_dung = VAI_ROLE.get(nv.vai)
	giu = [r for r in u.roles if r.role not in ROLE_VAI]
	if [r.role for r in u.roles] != [r.role for r in giu] + ([role_dung] if role_dung else []):
		u.set("roles", [])
		for r in giu:
			u.append("roles", {"role": r.role})
		if role_dung:
			u.append("roles", {"role": role_dung})
	u.flags.ignore_permissions = True
	u.save()
	if bat_truoc and not u.enabled:
		frappe.sessions.clear_sessions(nv.user, force=True)


def nhan_vien_cua(user: str | None = None) -> dict | None:
	"""Hồ sơ NV của người đang gọi (vai, hoạt động) — None nếu không phải NV của NPP (Administrator, Guest…)."""
	user = user or frappe.session.user
	r = frappe.db.get_value("NPP Nhan Vien", user, ["name", "vai", "dang_hoat_dong", "nghi_viec_luc"], as_dict=True)
	return r
