"""/api/do-nap của nppsale → NPP Do Nap. Màn POS / báo cáo gửi bản tóm tắt thời gian nạp (baoNapPos — chỉ đường dẫn + cách gọi +
ms + kết quả, không tham số / dữ liệu). Chỉ người đã đăng nhập; thân cắt ở 4.000 ký tự; trả 204 như route cũ."""
from __future__ import annotations

import json

import frappe

from .tuyen import YeuCauCu, tuyen


@tuyen("POST", r"^/api/do-nap$")
def ghi(yc: YeuCauCu):
	than = yc.than
	if isinstance(than, str):
		try:
			than = json.loads(than[:4000])
		except ValueError:
			return 400, None
	if not isinstance(than, dict):
		return 400, None
	man = str(than.get("man") or "")[:140]
	if not man:
		return 400, None
	noi_dung = json.dumps({**than, "user": frappe.session.user}, ensure_ascii=False)[:4000]
	nguoi = frappe.session.user if frappe.db.exists("NPP Nhan Vien", frappe.session.user) else None
	frappe.get_doc({
		"doctype": "NPP Do Nap", "man": man, "nhan": "bao-cao-nap" if man.startswith(("bc-", "pt-")) else "pos-nap",
		"ms": int(than.get("ms") or 0) if str(than.get("ms") or "0").lstrip("-").isdigit() else 0, "noi_dung": noi_dung, "nguoi": nguoi,
	}).insert(ignore_permissions=True)
	return 204, None
