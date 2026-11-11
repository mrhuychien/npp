"""Số điện thoại Việt Nam — định danh đăng nhập và khoá lọc trùng khách.

Bản gốc: nppsale `src/lib/users/phone.ts` (`normalizePhone`, `isValidPhone`, `syntheticEmail`) và `public.normalize_phone()`
(mig 104). Ba bản phải cho cùng kết quả — bộ ca dùng chung `tests/fixtures/phone-cases.json` của nppsale.
Luật: chuẩn hoá KHI SO SÁNH, giữ nguyên KHI LƯU (sđt hiển thị đúng như người nhập).
"""
from __future__ import annotations

import re

MIEN_EMAIL_KY_THUAT = "nppsale.local"


def chuan_hoa_sdt(tho: str | None) -> str:
	"""Chỉ chữ số, bắt đầu bằng 0; "" nếu không có chữ số nào. 0084… / 84… (≥ 11 số) → 0…; thiếu số 0 đầu (9 số) → thêm."""
	d = re.sub(r"\D", "", tho or "")
	if not d:
		return ""
	if d.startswith("00"):
		d = d[2:]
	if d.startswith("84") and len(d) >= 11:
		return "0" + d[2:]
	if d.startswith("0"):
		return d
	if len(d) == 9:
		return "0" + d
	return d


def sdt_hop_le(tho: str | None) -> bool:
	"""Dễ tính có chủ ý: 9–11 chữ số sau chuẩn hoá, bắt đầu bằng 0 (di động 10 số, cố định 10–11)."""
	return re.fullmatch(r"0\d{8,10}", chuan_hoa_sdt(tho)) is not None


def email_ky_thuat(tho: str | None) -> str:
	"""Email kỹ thuật của tài khoản nhân viên: <sđt chuẩn hoá>@nppsale.local — tên User của Frappe (không bao giờ đổi)."""
	p = chuan_hoa_sdt(tho)
	if not p:
		raise ValueError("Không sinh được email từ số điện thoại rỗng")
	return f"{p}@{MIEN_EMAIL_KY_THUAT}"


# --- SĐT của KHÁCH (luật riêng — nppsale `src/lib/customers/tao-khach.ts`, `kiem-trung-hang-loat.ts`) -----------------------
_KY_TU_SO = re.compile(r"^[\d\s.+()-]+$")


def chuan_hoa_sdt_khach(tho: str | None) -> str:
	"""chuanHoaSdt: chỉ chữ số; đúng 84 + 9 số → 0 + 9 số; còn lại giữ nguyên dãy số (không xử lý 00 / thiếu 0 đầu như SĐT NV)."""
	d = re.sub(r"\D", "", str(tho or ""))
	if re.fullmatch(r"84\d{9}", d):
		return "0" + d[2:]
	return d


def sdt_khach_de_luu(tho: str | None) -> str:
	"""sdtDeLuu: chuỗi chỉ gồm số / dấu cách . + ( ) - và chuẩn hoá ra 0 + 8..10 số → lưu bản chuẩn hoá; còn lại giữ nguyên
	(đã cắt khoảng trắng hai đầu) — UNIQUE(org_id, phone) so nguyên văn nên "0911.111.111" lưu thô là khách thứ hai cùng số."""
	t = str(tho or "").strip()
	d = chuan_hoa_sdt_khach(t)
	return d if _KY_TU_SO.match(t or "x") and re.fullmatch(r"0\d{8,10}", d) else t


def sdt_khach_tim_chinh_xac(q: str | None) -> str:
	"""sdtTimChinhXac: chỉ tìm khi gõ đúng một số điện thoại (0 + 9..10 số sau chuẩn hoá); không thì "" (không tìm từng phần)."""
	t = str(q or "").strip()
	if not t or not _KY_TU_SO.match(t):
		return ""
	d = chuan_hoa_sdt_khach(t)
	return d if re.fullmatch(r"0\d{9,10}", d) else ""
