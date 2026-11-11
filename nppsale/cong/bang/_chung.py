"""Tiện ích chung cho các tệp khai bảng của cổng."""
from __future__ import annotations

import re

import frappe

from ..dang_ky import CotDef, NguCanh
from ..sql import LoiCong

# Hằng org_id của site (một site một NPP) — câu con không tương quan, MariaDB tính một lần mỗi câu.
ORG_SQL = "(SELECT `value` FROM `tabSingles` WHERE `doctype` = 'NPP Cai Dat' AND `field` = 'org_id')"

VAI_VAN_PHONG = ("owner", "manager", "accountant")


def c(bieu: str, kieu: str = "chuoi", truong: str | None = None) -> CotDef:
	"""c("ho_ten") = cột `ho_ten` của bảng nguồn; c("CASE …{t}…", "so") = biểu thức SQL tự viết."""
	if re.fullmatch(r"[a-z_][a-z0-9_]*", bieu):
		return CotDef(f"{{t}}.`{bieu}`", kieu, truong if truong is not None else bieu)
	return CotDef(bieu, kieu, truong)


def org() -> CotDef:
	return CotDef(ORG_SQL, "chuoi")


def la_nv(nc: NguCanh) -> bool:
	"""Người gọi là NV đang hoạt động của NPP (cổng chỉ phục vụ NV — `user_org_id()` của nppsale trả NULL khi bị khoá)."""
	return bool(nc.vai)


def rls_moi_nv(nc: NguCanh):
	"""SELECT cho mọi NV của NPP (chính sách kiểu `org_id = user_org_id()`)."""
	return None if la_nv(nc) else False


def tu_choi(bang: str):
	raise LoiCong("42501", f'new row violates row-level security policy for table "{bang}"', http=403)


def lay_org_id() -> str:
	return frappe.db.get_single_value("NPP Cai Dat", "org_id") or ""


def kiem_org(gia_tri: dict, bang: str):
	"""Ghi kèm `org_id` khác hằng của site → từ chối như WITH CHECK của RLS."""
	if "org_id" in gia_tri and gia_tri["org_id"] not in (None, lay_org_id()):
		tu_choi(bang)


def pivot_single(doctype: str, truong: dict[str, str]) -> str:
	"""Câu con dựng MỘT dòng từ `tabSingles` của DocType Single: {tên cột ra: kiểu} — kiểu: chuoi / so / bool / gio / json."""
	phan = []
	for ten, kieu in truong.items():
		e = f"MAX(CASE WHEN s.`field` = '{ten}' THEN s.`value` END)"
		if kieu == "so":
			e = f"CAST({e} AS DECIMAL(21,6))"
		elif kieu == "bool":
			e = f"CAST(IFNULL({e}, 0) AS UNSIGNED)"
		elif kieu == "gio":
			e = f"CAST({e} AS DATETIME(6))"
		phan.append(f"{e} AS `{ten}`")
	return f"(SELECT {', '.join(phan)} FROM `tabSingles` s WHERE s.`doctype` = '{doctype}')"
