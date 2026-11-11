"""Bảng HỆ THỐNG của nppsale trên cổng: organizations, pricing_rules, approval_rules (Single NPP Cai Dat), users, user_suppliers,
role_permissions, user_permission_overrides, danh_muc_ban_phien, notifications, entity_locks, workflow_sessions (không port).

Vế lọc chép chính sách RLS đang chạy (blueprint 02 §8.1): mọi NV thấy mọi NV / quyền / số phiên; thông báo chỉ của mình; ghi theo vai.
"""
from __future__ import annotations

import json

import frappe

from ..dang_ky import Bang, CotDef, NguCanh, QuanHe, dang_ky
from ..sql import LoiCong
from ._chung import ORG_SQL, c, kiem_org, la_nv, org, pivot_single, rls_moi_nv, tu_choi

# ----------------------------------------------------------------------------------------------------------------------------
# NPP Cai Dat → organizations / pricing_rules / approval_rules (một dòng ảo)
# ----------------------------------------------------------------------------------------------------------------------------
_CAI_DAT = pivot_single(
	"NPP Cai Dat",
	{
		"org_id": "chuoi", "ten_npp": "chuoi", "ma_npp": "chuoi", "dia_chi": "chuoi", "so_dien_thoai": "chuoi", "ma_so_thue": "chuoi",
		"email": "chuoi", "setup_xong_luc": "gio", "cai_dat_khac": "chuoi", "cho_ban_vuot_ton": "bool", "nguong_kho_date_ngay": "so",
		"tu_duyet_toi_da": "so", "quan_ly_duyet_toi_da": "so", "no_khach_toi_da": "so", "no_qua_han_toi_da": "so",
		"no_danh_muc_nv_toi_da": "so", "kiem_han_muc": "bool", "bat_canh_bao": "bool", "ghi_chu_canh_bao": "chuoi",
	},
)
_SUA_CAI_DAT = "(SELECT MAX(`modified`) FROM `tabSingles` WHERE 0)"  # Single không lưu modified theo dòng → null

# settings của organizations: khoá nppsale đọc (orgHeaderFrom, /setup) từ trường riêng, khoá lạ giữ trong cai_dat_khac
_SETTINGS = (
	"JSON_MERGE_PATCH(IFNULL(NULLIF({t}.`cai_dat_khac`, ''), '{}'), JSON_OBJECT("
	"'address', {t}.`dia_chi`, 'phone', {t}.`so_dien_thoai`, 'tax_code', {t}.`ma_so_thue`, 'email', {t}.`email`, "
	"'setup_completed_at', DATE_FORMAT({t}.`setup_xong_luc`, '%%Y-%%m-%%dT%%H:%%i:%%s+07:00')))"
)
_KHOA_SETTINGS = {"address": "dia_chi", "phone": "so_dien_thoai", "tax_code": "ma_so_thue", "email": "email",
	"setup_completed_at": "setup_xong_luc"}


class GhiCaiDat:
	"""UPDATE / UPSERT các bảng ảo trên NPP Cai Dat. INSERT của approval_rules (màn chưa thấy dòng) = UPDATE."""

	def __init__(self, bang: str, anh_xa: dict[str, str], vai: tuple[str, ...]):
		self.bang, self.anh_xa, self.vai = bang, anh_xa, vai

	def _ap(self, gia_tri: dict, nc: NguCanh) -> list[str]:
		if nc.vai not in self.vai:
			return []
		kiem_org(gia_tri, self.bang)
		cd = frappe.get_single("NPP Cai Dat")
		for k, v in gia_tri.items():
			if k in ("org_id", "id", "created_at", "updated_at", "updated_by"):
				continue
			if self.bang == "organizations" and k == "settings":
				_ghi_settings(cd, v or {})
				continue
			truong = self.anh_xa.get(k)
			if truong is None:
				raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{self.bang}' in the schema cache", http=400)
			cd.set(truong, v)
		cd.save(ignore_permissions=True)
		return [cd.org_id]

	def sua(self, gia_tri, ids, nc):
		return self._ap(gia_tri, nc)

	def them(self, ds, nc):
		if nc.vai not in self.vai:
			tu_choi(self.bang)
		ra = []
		for g in ds:
			ra += self._ap(g, nc)
		return ra

	def them_hoac_sua(self, ds, on_conflict, bo_qua_trung, nc):
		return self.them(ds, nc)

	def xoa(self, ids, nc):
		return []


def _ghi_settings(cd, s: dict):
	khac = {}
	try:
		khac = json.loads(cd.cai_dat_khac or "{}")
	except ValueError:
		khac = {}
	for k, v in (s or {}).items():
		if k in _KHOA_SETTINGS:
			truong = _KHOA_SETTINGS[k]
			if truong == "setup_xong_luc" and v:
				v = frappe.utils.get_datetime(v).replace(tzinfo=None)
			cd.set(truong, v)
		else:
			khac[k] = v
	cd.cai_dat_khac = json.dumps(khac, ensure_ascii=False) if khac else None


dang_ky(Bang(
	ten="organizations",
	nguon=_CAI_DAT,
	cot={
		"id": c("{t}.`org_id`"), "name": c("{t}.`ten_npp`"), "slug": c("{t}.`ma_npp`"), "settings": c(_SETTINGS, "json"),
		"allow_oversell": c("{t}.`cho_ban_vuot_ton`", "bool"), "created_at": CotDef("NULL", "gio"), "completed_edit_days": CotDef("1", "so"),
	},
	rls=rls_moi_nv,
	ghi=GhiCaiDat("organizations", {"name": "ten_npp", "slug": "ma_npp", "allow_oversell": "cho_ban_vuot_ton"}, ("owner",)),
))

dang_ky(Bang(
	ten="pricing_rules",
	nguon=_CAI_DAT,
	khoa="org_id",
	cot={
		"id": c("{t}.`org_id`"), "org_id": c("{t}.`org_id`"), "date_warehouse_threshold_days": c("{t}.`nguong_kho_date_ngay`", "so"),
		"updated_at": CotDef("NULL", "gio"), "updated_by": CotDef("NULL"),
	},
	rls=rls_moi_nv,
	ghi=GhiCaiDat("pricing_rules", {"date_warehouse_threshold_days": "nguong_kho_date_ngay"}, ("owner", "manager")),
))

dang_ky(Bang(
	ten="approval_rules",
	nguon=_CAI_DAT,
	cot={
		"id": c("{t}.`org_id`"), "org_id": c("{t}.`org_id`"), "auto_approve_max": c("{t}.`tu_duyet_toi_da`", "tien"),
		"manager_approve_max": c("{t}.`quan_ly_duyet_toi_da`", "tien"), "customer_debt_max": c("NULLIF({t}.`no_khach_toi_da`, 0)", "tien"),
		"customer_overdue_max": c("NULLIF({t}.`no_qua_han_toi_da`, 0)", "tien"),
		"rep_portfolio_debt_max": c("NULLIF({t}.`no_danh_muc_nv_toi_da`, 0)", "tien"),
		"enforce_credit_limit": c("{t}.`kiem_han_muc`", "bool"), "is_active": c("{t}.`bat_canh_bao`", "bool"),
		"notes": c("{t}.`ghi_chu_canh_bao`"), "created_at": CotDef("NULL", "gio"), "updated_at": CotDef("NULL", "gio"),
		"updated_by": CotDef("NULL"),
	},
	# approval_rules_select: chỉ owner / manager / accountant — NVBH, thủ kho đọc ra rỗng (evaluateApproval dùng ngưỡng mặc định)
	rls=lambda nc: None if nc.vai in ("owner", "manager", "accountant") else False,
	ghi=GhiCaiDat("approval_rules", {
		"auto_approve_max": "tu_duyet_toi_da", "manager_approve_max": "quan_ly_duyet_toi_da", "customer_debt_max": "no_khach_toi_da",
		"customer_overdue_max": "no_qua_han_toi_da", "rep_portfolio_debt_max": "no_danh_muc_nv_toi_da",
		"enforce_credit_limit": "kiem_han_muc", "is_active": "bat_canh_bao", "notes": "ghi_chu_canh_bao",
	}, ("owner", "manager")),
))

# ----------------------------------------------------------------------------------------------------------------------------
# NPP Nhan Vien → users, user_suppliers
# ----------------------------------------------------------------------------------------------------------------------------
_COT_USERS = {
	"full_name": "ho_ten", "role": "vai", "phone": "sdt", "is_active": "dang_hoat_dong", "allow_price_edit": "cho_sua_gia",
	"price_edit_max_increase_pct": "tran_tang_gia", "allow_discount": "cho_giam_gia", "discount_max_type": "kieu_tran_giam",
	"left_at": "nghi_viec_luc", "left_by": "nghi_viec_boi",
}


class GhiUsers:
	"""UPDATE: chỉ chủ NPP (users "Owner update users"); tạo / xoá NV đi qua method (nppsale.api.nguoi_dung)."""

	def sua(self, gia_tri, ids, nc):
		if nc.vai != "owner":
			return []
		kiem_org(gia_tri, "users")
		ra = []
		for ten in ids:
			nv = frappe.get_doc("NPP Nhan Vien", ten)
			for k, v in gia_tri.items():
				if k in ("id", "org_id", "created_at", "tim_kd"):
					continue
				if k == "discount_max_value":
					nv.co_tran_giam = 0 if v is None else 1
					nv.tran_giam = v or 0
					continue
				truong = _COT_USERS.get(k)
				if truong is None:
					raise LoiCong("PGRST204", f"Could not find the '{k}' column of 'users' in the schema cache", http=400)
				if k == "left_at" and v:
					raise LoiCong("42501", "Nghỉ việc đi qua nút Cho nghỉ việc (cho_nhan_vien_nghi).", http=403)
				nv.set(truong, v)
			nv.save(ignore_permissions=True)
			ra.append(ten)
		return ra

	def them(self, ds, nc):
		tu_choi("users")

	def xoa(self, ids, nc):
		return []


dang_ky(Bang(
	ten="users",
	nguon="`tabNPP Nhan Vien`",
	cot={
		"id": c("{t}.`name`"), "org_id": org(), "full_name": c("ho_ten"), "role": c("vai"), "phone": c("sdt"),
		"is_active": c("dang_hoat_dong", "bool"), "created_at": c("creation", "gio"), "allow_price_edit": c("cho_sua_gia", "bool"),
		"price_edit_max_increase_pct": c("tran_tang_gia", "so"), "allow_discount": c("cho_giam_gia", "bool"),
		"discount_max_type": c("kieu_tran_giam"),
		"discount_max_value": c("CASE WHEN {t}.`co_tran_giam` = 1 THEN {t}.`tran_giam` END", "so"),
		"left_at": c("nghi_viec_luc", "gio"), "left_by": c("nghi_viec_boi"), "tim_kd": c("khoa_tim"),
	},
	quan_he=[QuanHe("user_suppliers", "id", "user_id", True, ("user_suppliers_user_id_fkey",))],
	rls=rls_moi_nv,
	ghi=GhiUsers(),
))


class GhiUserSuppliers:
	"""INSERT / DELETE: chủ NPP, quản lý — sửa dòng con rồi lưu NPP Nhan Vien (validate + đồng bộ chạy như sửa tay)."""

	def them(self, ds, nc):
		if nc.vai not in ("owner", "manager"):
			tu_choi("user_suppliers")
		ra = []
		for g in ds:
			kiem_org(g, "user_suppliers")
			nv = frappe.get_doc("NPP Nhan Vien", g.get("user_id"))
			if not any(d.nha_cung_cap == g.get("supplier_id") for d in nv.cong_ty):
				nv.append("cong_ty", {"nha_cung_cap": g.get("supplier_id")})
				nv.save(ignore_permissions=True)
			ra += [d.name for d in nv.cong_ty if d.nha_cung_cap == g.get("supplier_id")]
		return ra

	def xoa(self, ids, nc):
		if nc.vai not in ("owner", "manager"):
			return []
		cha = {}
		for ten, parent in frappe.db.sql("SELECT name, parent FROM `tabNPP Nhan Vien Cong Ty` WHERE name IN %(i)s", {"i": tuple(ids)}):
			cha.setdefault(parent, set()).add(ten)
		for parent, bo in cha.items():
			nv = frappe.get_doc("NPP Nhan Vien", parent)
			nv.set("cong_ty", [d for d in nv.cong_ty if d.name not in bo])
			nv.save(ignore_permissions=True)
		return list(ids)

	def sua(self, gia_tri, ids, nc):
		return []


dang_ky(Bang(
	ten="user_suppliers",
	nguon="`tabNPP Nhan Vien Cong Ty`",
	cot={
		"id": c("{t}.`name`"), "user_id": c("parent"), "supplier_id": c("nha_cung_cap"), "created_at": c("creation", "gio"), "org_id": org(),
	},
	quan_he=[QuanHe("users", "user_id", "id", False, ("user_suppliers_user_id_fkey",))],
	rls=rls_moi_nv,
	ghi=GhiUserSuppliers(),
))

# ----------------------------------------------------------------------------------------------------------------------------
# NPP Quyen Vai → role_permissions; NPP Quyen Rieng → user_permission_overrides
# ----------------------------------------------------------------------------------------------------------------------------


class GhiQuyenVai:
	"""UPSERT theo (org_id, role, module, action) — chủ NPP (role_permissions_owner_write)."""

	def them_hoac_sua(self, ds, on_conflict, bo_qua_trung, nc):
		if nc.vai != "owner":
			tu_choi("role_permissions")
		ra = []
		for g in ds:
			kiem_org(g, "role_permissions")
			ten = f"{g.get('role')}:{g.get('module')}:{g.get('action')}"
			if frappe.db.exists("NPP Quyen Vai", ten):
				if bo_qua_trung:
					continue
				d = frappe.get_doc("NPP Quyen Vai", ten)
				d.duoc_phep = 1 if g.get("allowed") else 0
				d.save(ignore_permissions=True)
			else:
				frappe.get_doc({"doctype": "NPP Quyen Vai", "vai": g.get("role"), "mo_dun": g.get("module"), "hanh_dong": g.get("action"),
					"duoc_phep": 1 if g.get("allowed") else 0}).insert(ignore_permissions=True)
			ra.append(ten)
		return ra

	def them(self, ds, nc):
		return self.them_hoac_sua(ds, None, False, nc)

	def sua(self, gia_tri, ids, nc):
		if nc.vai != "owner":
			return []
		for ten in ids:
			d = frappe.get_doc("NPP Quyen Vai", ten)
			if "allowed" in gia_tri:
				d.duoc_phep = 1 if gia_tri["allowed"] else 0
			d.save(ignore_permissions=True)
		return list(ids)

	def xoa(self, ids, nc):
		if nc.vai != "owner":
			return []
		for ten in ids:
			frappe.delete_doc("NPP Quyen Vai", ten, ignore_permissions=True)
		return list(ids)


dang_ky(Bang(
	ten="role_permissions",
	nguon="`tabNPP Quyen Vai`",
	cot={
		"id": c("{t}.`name`"), "org_id": org(), "role": c("vai"), "module": c("mo_dun"), "action": c("hanh_dong"),
		"allowed": c("duoc_phep", "bool"), "updated_at": c("modified", "gio"), "updated_by": c("modified_by"),
	},
	rls=rls_moi_nv,
	ghi=GhiQuyenVai(),
))


def _vai_cua(nhan_vien: str) -> str | None:
	return frappe.db.get_value("NPP Nhan Vien", nhan_vien, "vai")


class GhiQuyenRieng:
	"""UPSERT theo (user_id, permission_key), DELETE: chủ NPP, quản lý — quản lý không đụng dòng của chủ NPP (org_iso_upo_write)."""

	def _duoc(self, nc, nhan_vien) -> bool:
		if nc.vai == "owner":
			return bool(frappe.db.exists("NPP Nhan Vien", nhan_vien))
		if nc.vai == "manager":
			v = _vai_cua(nhan_vien)
			return v is not None and v != "owner"
		return False

	def them_hoac_sua(self, ds, on_conflict, bo_qua_trung, nc):
		ra = []
		for g in ds:
			kiem_org(g, "user_permission_overrides")
			if not self._duoc(nc, g.get("user_id")):
				tu_choi("user_permission_overrides")
			ten = f"{g.get('user_id')}:{g.get('permission_key')}"
			if frappe.db.exists("NPP Quyen Rieng", ten):
				if bo_qua_trung:
					continue
				d = frappe.get_doc("NPP Quyen Rieng", ten)
				d.duoc_phep = 1 if g.get("granted") else 0
				d.save(ignore_permissions=True)
			else:
				frappe.get_doc({"doctype": "NPP Quyen Rieng", "nhan_vien": g.get("user_id"), "khoa_quyen": g.get("permission_key"),
					"duoc_phep": 1 if g.get("granted") else 0}).insert(ignore_permissions=True)
			ra.append(ten)
		return ra

	def them(self, ds, nc):
		return self.them_hoac_sua(ds, None, False, nc)

	def sua(self, gia_tri, ids, nc):
		ra = []
		for ten in ids:
			d = frappe.get_doc("NPP Quyen Rieng", ten)
			if not self._duoc(nc, d.nhan_vien):
				continue
			if "granted" in gia_tri:
				d.duoc_phep = 1 if gia_tri["granted"] else 0
			d.save(ignore_permissions=True)
			ra.append(ten)
		return ra

	def xoa(self, ids, nc):
		ra = []
		for ten in ids:
			nv = frappe.db.get_value("NPP Quyen Rieng", ten, "nhan_vien")
			if nv and self._duoc(nc, nv):
				frappe.delete_doc("NPP Quyen Rieng", ten, ignore_permissions=True)
				ra.append(ten)
		return ra


dang_ky(Bang(
	ten="user_permission_overrides",
	nguon="`tabNPP Quyen Rieng`",
	cot={
		"id": c("{t}.`name`"), "org_id": org(), "user_id": c("nhan_vien"), "permission_key": c("khoa_quyen"),
		"granted": c("duoc_phep", "bool"), "created_at": c("creation", "gio"), "updated_at": c("modified", "gio"),
	},
	quan_he=[QuanHe("users", "user_id", "id", False, ("user_permission_overrides_user_id_fkey",))],
	rls=rls_moi_nv,
	ghi=GhiQuyenRieng(),
))

# ----------------------------------------------------------------------------------------------------------------------------
# Số phiên danh mục, thông báo, khoá chứng từ, workflow_sessions
# ----------------------------------------------------------------------------------------------------------------------------
dang_ky(Bang(
	ten="danh_muc_ban_phien",
	nguon="`tabNPP Phien Danh Muc`",
	cot={
		"id": c("CAST({t}.`name` AS UNSIGNED)", "so"), "phien": c("phien", "so"), "luc": c("luc", "gio"),
		"phien_khach": c("phien_khach", "so"), "luc_khach": c("luc_khach", "gio"),
	},
	rls=rls_moi_nv,
))


class GhiThongBao:
	"""INSERT: mọi NV, người nhận phải là NV của NPP. UPDATE (is_read, read_at) / DELETE: chỉ dòng của mình."""

	def them(self, ds, nc):
		if not la_nv(nc):
			tu_choi("notifications")
		ra = []
		for g in ds:
			kiem_org(g, "notifications")
			if not frappe.db.exists("NPP Nhan Vien", g.get("user_id")):
				tu_choi("notifications")
			d = frappe.get_doc({
				"doctype": "NPP Thong Bao", "nguoi_nhan": g.get("user_id"), "loai": g.get("type") or "info", "tieu_de": g.get("title"),
				"noi_dung": g.get("body"), "duong_dan": g.get("link_url"), "da_doc": 1 if g.get("is_read") else 0,
				"du_lieu": json.dumps(g.get("metadata"), ensure_ascii=False) if g.get("metadata") is not None else None,
			})
			if g.get("id"):
				d.name = g["id"]
			d.insert(ignore_permissions=True)
			ra.append(d.name)
		return ra

	def sua(self, gia_tri, ids, nc):
		ra = []
		for ten in ids:
			d = frappe.get_doc("NPP Thong Bao", ten)
			if d.nguoi_nhan != nc.user:
				continue
			for k, v in gia_tri.items():
				if k == "is_read":
					d.da_doc = 1 if v else 0
				elif k == "read_at":
					d.doc_luc = frappe.utils.get_datetime(v).replace(tzinfo=None) if v else None
			d.save(ignore_permissions=True)
			ra.append(ten)
		return ra

	def xoa(self, ids, nc):
		ra = []
		for ten in ids:
			if frappe.db.get_value("NPP Thong Bao", ten, "nguoi_nhan") == nc.user:
				frappe.delete_doc("NPP Thong Bao", ten, ignore_permissions=True)
				ra.append(ten)
		return ra


dang_ky(Bang(
	ten="notifications",
	nguon="`tabNPP Thong Bao`",
	cot={
		"id": c("{t}.`name`"), "org_id": org(), "user_id": c("nguoi_nhan"), "type": c("loai"), "title": c("tieu_de"), "body": c("noi_dung"),
		"link_url": c("duong_dan"), "is_read": c("da_doc", "bool"), "read_at": c("doc_luc", "gio"), "metadata": c("du_lieu", "json"),
		"created_at": c("creation", "gio"),
	},
	rls=lambda nc: ("{t}.`nguoi_nhan` = %(u)s", {"u": nc.user}) if la_nv(nc) else False,
	ghi=GhiThongBao(),
))

dang_ky(Bang(
	ten="entity_locks",
	nguon="`tabNPP Khoa Chung Tu`",
	cot={
		"id": c("{t}.`name`"), "org_id": org(), "entity_type": c("loai_chung_tu"), "entity_id": c("chung_tu"),
		"locked_by": c("nguoi_khoa"), "locked_at": c("khoa_luc", "gio"), "last_heartbeat_at": c("nhip_cuoi", "gio"),
	},
	quan_he=[QuanHe("users", "locked_by", "id", False, ("entity_locks_locked_by_fkey",))],
	rls=rls_moi_nv,
))


class GhiBoQua:
	"""workflow_sessions không port (bản bàn bạc 4.2 / 6.15): ghi trả thành công, không lưu gì — để mã cũ không vỡ."""

	def them(self, ds, nc):
		return []

	def them_hoac_sua(self, ds, on_conflict, bo_qua_trung, nc):
		return []

	def sua(self, gia_tri, ids, nc):
		return []

	def xoa(self, ids, nc):
		return []


dang_ky(Bang(
	ten="workflow_sessions",
	nguon="(SELECT NULL AS `id`, NULL AS `user_id`, NULL AS `entity_type`, NULL AS `entity_id`, NULL AS `stage`, NULL AS `state`, "
	"NULL AS `updated_at` FROM DUAL WHERE 1 = 0)",
	cot={k: c("{t}.`" + k + "`", "json" if k == "state" else "gio" if k == "updated_at" else "chuoi") for k in
		("id", "user_id", "entity_type", "entity_id", "stage", "state", "updated_at")},
	rls=rls_moi_nv,
	ghi=GhiBoQua(),
))

_ = ORG_SQL  # dùng ở _chung; giữ tên để tìm
