"""Chặn các cửa đọc / ghi chung của lõi với người chỉ mang vai NPP (bản bàn bạc chốt, mục 3.5).

Vai NPP có quyền ĐỌC danh mục ở lớp Frappe (DocPerm sàn — `nppsale.thiet_lap.quyen_san`) chỉ để method của app lập được chứng từ lõi
dưới chính người dùng. Nếu để ngỏ `/api/resource/Item`, `frappe.client.get_list`, `frappe.desk.reportview.get`… thì NVBH đọc được hàng
của công ty khác, khách / HĐ của NV khác — vượt RLS của nppsale. Nên với người dùng mà MỌI vai đều là vai NPP (không vai Desk nào khác):
chỉ cho `/api/method/nppsale.*` (cổng, RPC, method của app) + đăng nhập / đăng xuất / realtime; mọi cửa `/api/…` khác và lối `?cmd=` cũ
→ 403. Người có vai lõi (System Manager, kế toán Desk…) không bị ảnh hưởng.
"""
from __future__ import annotations

from nppsale.thiet_lap.vai import VAI_ROLE

VAI_NPP = frozenset(VAI_ROLE.values())
VAI_TU_DONG = frozenset(("All", "Guest", "Desk User"))  # Frappe tự gắn — không phải vai Desk thật
CHO_DUNG = frozenset(("login", "logout", "frappe.auth.get_logged_user"))
CHO_DAU = ("nppsale.", "frappe.realtime.")


def chi_vai_npp(vai: set[str] | frozenset[str]) -> bool:
	"""True khi người dùng có ít nhất một vai NPP và không vai nào khác ngoài vai Frappe tự gắn."""
	vai = set(vai) - VAI_TU_DONG
	return bool(vai) and vai <= VAI_NPP


def lenh_duoc_phep(cmd: str) -> bool:
	return cmd in CHO_DUNG or cmd.startswith(CHO_DAU)


def bi_chan(duong: str, cmd: str | None) -> bool:
	"""Quyết định thuần (không đọc sổ) cho người chỉ mang vai NPP."""
	if cmd:
		return not lenh_duoc_phep(cmd)
	if duong.startswith("/api/method/"):
		return not lenh_duoc_phep(duong[len("/api/method/"):].strip("/"))
	return duong.startswith("/api/")


def chan_cua_chung():
	"""Hook before_request."""
	import frappe

	u = frappe.session.user
	if not u or u in ("Guest", "Administrator"):
		return
	try:
		duong = frappe.request.path or ""
	except RuntimeError:
		return
	cmd = frappe.form_dict.get("cmd") if not duong.startswith("/api/") else None
	if not cmd and not duong.startswith("/api/"):
		return
	if not chi_vai_npp(frappe.get_roles(u)):
		return
	if bi_chan(duong, cmd):
		frappe.throw("Không được phép", frappe.PermissionError)
