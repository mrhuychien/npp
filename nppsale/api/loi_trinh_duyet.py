"""/api/client-error của nppsale → Error Log của Frappe (tra được trên Desk). Lỗi ở điện thoại người dùng vốn không để lại dấu vết
ở máy chủ (chủ nhà 26/09/2026). Chỉ người đã đăng nhập; thân cắt 8.000 ký tự; tối đa 30 lượt / phút / người để không ngập nhật ký."""
from __future__ import annotations

import json

import frappe

from .tuyen import YeuCauCu, tuyen

TOI_DA_PHUT = 30


@tuyen("POST", r"^/api/client-error$")
def ghi(yc: YeuCauCu):
	k = frappe.cache.make_key(f"npp_rl:client-error:{frappe.session.user}")
	n = frappe.cache.incr(k)
	if n == 1:
		frappe.cache.expire(k, 60)
	if n > TOI_DA_PHUT:
		return 204, None
	than = yc.than
	if isinstance(than, str):
		than = than[:8000]
	goi = {"user": frappe.session.user, **(than if isinstance(than, dict) else {"raw": than})}
	tieu_de = "[client-error] " + str((than or {}).get("message") if isinstance(than, dict) else "")[:100]
	frappe.log_error(title=tieu_de, message=json.dumps(goi, ensure_ascii=False, indent=1)[:8000])
	return 204, None
