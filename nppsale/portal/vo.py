"""Vỏ trang portal: đọc manifest của Vite để chèn thẻ script / css, và dựng `window.NPP_CONTEXT` (phiên + hồ sơ).

Portal build bằng Vite ra nppsale/public/portal/app (Frappe phục vụ ở /assets/nppsale/portal/app/). Vỏ HTML không do Vite dựng
(cách "tích hợp máy chủ" của Vite): đọc `.vite/manifest.json`, lấy mục vào `src/khung/main.tsx` → tệp JS, các tệp CSS và các
khối nạp sẵn (modulepreload).
"""
import json
import os

import frappe

THU_MUC_BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "portal", "app")
TIEN_TO = "/assets/nppsale/portal/app/"
MUC_VAO = "src/khung/main.tsx"
_nho = {"mtime": None, "ket_qua": None}


def tai_san_vite():
	"""{"js": url, "css": [url], "nap_san": [url]} của mục vào; None khi chưa build (vỏ báo "chưa build portal")."""
	duong = os.path.join(THU_MUC_BUILD, ".vite", "manifest.json")
	try:
		mtime = os.path.getmtime(duong)
	except OSError:
		return None
	if _nho["mtime"] == mtime:
		return _nho["ket_qua"]
	with open(duong, encoding="utf-8") as f:
		mf = json.load(f)
	vao = mf.get(MUC_VAO)
	if not vao:
		return None
	css, nap_san, da = [], [], set()

	def gom(khoa):
		if khoa in da:
			return
		da.add(khoa)
		muc = mf.get(khoa) or {}
		for c in muc.get("css") or []:
			if c not in css:
				css.append(c)
		for con in muc.get("imports") or []:
			tep = (mf.get(con) or {}).get("file")
			if tep and tep not in nap_san:
				nap_san.append(tep)
			gom(con)

	gom(MUC_VAO)
	kq = {"js": TIEN_TO + vao["file"], "css": [TIEN_TO + c for c in css], "nap_san": [TIEN_TO + t for t in nap_san]}
	_nho.update(mtime=mtime, ket_qua=kq)
	return kq


def ho_so_nguoi_dung(user):
	"""Hồ sơ như `users` của nppsale (bộ cột COT_HO_SO + giảm giá) — đọc qua chính cổng tương thích, đúng luật quyền.
	Sổ chưa có bảng `users` (chưa cài DocType) hoặc đọc hỏng → None: trình duyệt tự đọc lại như nppsale."""
	if not user or user == "Guest":
		return None
	try:
		from nppsale.cong import truy_van
		from nppsale.cong.bang import nap
		from nppsale.cong.dang_ky import lay
		from nppsale.cong.ngu_canh import hien_tai

		nap()
		if not lay("users"):
			return None
		kq = truy_van.ap_mot(
			truy_van.doc(
				{
					"bang": "users",
					"select": "id, org_id, full_name, role, phone, is_active, created_at, allow_price_edit, "
					"price_edit_max_increase_pct, allow_discount, discount_max_type, discount_max_value",
					"loc": [{"op": "eq", "cot": "id", "gt": user}],
				},
				hien_tai(),
			),
			"maybe",
		)
		return kq.get("data")
	except Exception:
		frappe.log_error(title="nppsale: đọc hồ sơ cho vỏ trang hỏng")
		return None


def ngu_canh_trang():
	user = frappe.session.user
	return {
		"user": None if user == "Guest" else user,
		"csrf_token": frappe.sessions.get_csrf_token() if user != "Guest" else "",
		"ho_so": ho_so_nguoi_dung(user),
		"phien_ban": frappe.utils.get_build_version(),
	}
