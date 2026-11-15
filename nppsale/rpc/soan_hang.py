"""Soạn hàng (nppsale mig 224 `danh_dau_soan_hang`, mig 225 lượt soạn) — đánh dấu HĐ đã soạn và lượt soạn nhiều HĐ một lần (rổ A–Z),
tiến độ nhặt / chia lưu trên máy chủ (chủ nhà 02/10/2026 "Lưu trên máy chủ": hai máy cùng soạn một lượt thấy nhau). Không trừ kho —
kho đã trừ lúc ghi sổ HĐ; dấu soạn ở `Sales Invoice.npp_soan_luc / npp_soan_boi` (Custom Field allow_on_submit, không đổi `modified`
— như trigger `_sua_luc_hoa_don` của nppsale chỉ đổi updated_at khi nội dung HĐ đổi).

Mã lượt `SH-dd/mm-NN`, NN = số lượt tạo trong ngày (giờ VN) + 1 — blueprint 02 §7.1 điểm 9 (name UUID + trường `ma`).
"""
from __future__ import annotations

import json

import frappe
from frappe.utils import getdate, now_datetime, nowdate

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai

from . import rpc

VAI_SOAN = ("owner", "manager", "warehouse", "accountant")
TOI_DA_RO = 26


def _quyen(viec: str = "soạn hàng"):
	"""_luot_soan_quyen: NV đang hoạt động, vai chủ NPP / quản lý / thủ kho / kế toán."""
	nc = hien_tai()
	if not nc.vai or nc.vai not in VAI_SOAN:
		raise NppLoi(f"KHONG_DU_QUYEN: chỉ chủ NPP, quản lý, thủ kho, kế toán {viec}")
	return nc


def _ro(i: int) -> str:
	return chr(ord("A") + i)


def _hoa_don(ids) -> list:
	"""_luot_soan_hoa_don: bỏ trùng giữ thứ tự (= thứ tự rổ); ≤ 26; chỉ HĐ đã ghi sổ của NPP."""
	ds: list = []
	for x in ids or []:
		if x not in ds:
			ds.append(x)
	if len(ds) > TOI_DA_RO:
		raise NppLoi("QUA_NHIEU_RO: một lượt soạn tối đa 26 hoá đơn (rổ A–Z)")
	if ds:
		hop_le = set(frappe.get_all("Sales Invoice", filters={"name": ["in", [str(x) for x in ds if x]], "docstatus": 1, "is_return": 0,
			"is_opening": "No"}, pluck="name"))
		if any(not isinstance(x, str) or x not in hop_le for x in ds):
			raise NppLoi("HOA_DON_KHONG_HOP_LE: chỉ soạn hoá đơn đã ghi sổ của NPP")
	return ds


def _lpad2(n: int) -> str:
	"""lpad(n::text, 2, '0') của Postgres — dài hơn 2 thì CẮT (lượt thứ 100 trong ngày ra '10', như nppsale)."""
	s = str(n)
	return s[:2] if len(s) > 2 else s.rjust(2, "0")


def _bo_null(v):
	"""jsonb_strip_nulls: bỏ mọi trường có giá trị null của object, đệ quy (phần tử null của mảng giữ nguyên)."""
	if isinstance(v, dict):
		return {k: _bo_null(x) for k, x in v.items() if x is not None}
	if isinstance(v, list):
		return [_bo_null(x) for x in v]
	return v


def _json(v) -> dict:
	if isinstance(v, str):
		try:
			v = json.loads(v)
		except ValueError:
			v = None
	return v if isinstance(v, dict) else {}


def _hang(ten: str) -> dict:
	"""Dòng `luot_soan` như cổng trả (cùng định dạng giờ / mảng HĐ) — RPC nppsale RETURNS luot_soan."""
	from nppsale.cong import bang as B
	from nppsale.cong.truy_van import doc

	B.nap()
	ds = doc({"bang": "luot_soan", "select": "*", "loc": [{"op": "eq", "cot": "id", "gt": ten}]}, hien_tai())["data"]
	return ds[0] if ds else None


def _khoa_luot(p_id) -> dict:
	r = frappe.db.sql("SELECT `name`, `trang_thai` FROM `tabNPP Luot Soan` WHERE `name` = %s FOR UPDATE", (str(p_id or ""),), as_dict=True)
	if not r:
		raise NppLoi("KHONG_TIM_THAY_LUOT")
	if r[0].trang_thai != "dang_soan":
		raise NppLoi("LUOT_DA_DONG: lượt soạn đã hoàn tất / huỷ")
	return r[0]


def _danh_dau(ids: list, da: bool, user: str, luc) -> int:
	"""Đặt / gỡ dấu đã soạn trên HĐ đã ghi sổ; chỉ chạm HĐ đang ở trạng thái ngược lại (đếm = số HĐ đổi)."""
	ids = [str(x) for x in ids if x]
	if not ids:
		return 0
	ten = [r[0] for r in frappe.db.sql(f"""SELECT `name` FROM `tabSales Invoice` WHERE `name` IN %(i)s AND `docstatus` = 1 AND `is_return` = 0
		AND `is_opening` = 'No' AND `npp_soan_luc` IS {'NULL' if da else 'NOT NULL'} FOR UPDATE""", {"i": tuple(ids)})]
	if not ten:
		return 0
	if da:
		frappe.db.sql("""UPDATE `tabSales Invoice` SET `npp_soan_luc` = COALESCE(`npp_soan_luc`, %(l)s), `npp_soan_boi` = COALESCE(`npp_soan_boi`, %(u)s)
			WHERE `name` IN %(i)s""", {"l": luc, "u": user, "i": tuple(ten)})
	else:
		frappe.db.sql("UPDATE `tabSales Invoice` SET `npp_soan_luc` = NULL, `npp_soan_boi` = NULL WHERE `name` IN %(i)s", {"i": tuple(ten)})
	return len(ten)


@rpc("tao_luot_soan")
def tao_luot_soan(p_invoice_ids=None):
	"""Lập lượt soạn cho các HĐ đã ghi sổ (thứ tự = rổ A–Z) → id lượt."""
	_quyen()
	ds = _hoa_don(p_invoice_ids)
	if not ds:
		raise NppLoi("CHUA_CHON_HOA_DON")
	# hai lượt lập cùng lúc đếm số lượt trong ngày lần lượt (pg_advisory_xact_lock('luot_soan:' || org)) — khoá một dòng cài đặt
	frappe.db.sql("SELECT `value` FROM `tabSingles` WHERE `doctype` = 'NPP Cai Dat' AND `field` = 'org_id' FOR UPDATE")
	hom_nay = nowdate()  # múi giờ site = Asia/Ho_Chi_Minh
	n = int(frappe.db.sql("SELECT COUNT(*) FROM `tabNPP Luot Soan` WHERE DATE(`creation`) = %s", (hom_nay,))[0][0]) + 1
	doc = frappe.get_doc({
		"doctype": "NPP Luot Soan", "ma": f"SH-{getdate(hom_nay).strftime('%d/%m')}-{_lpad2(n)}", "trang_thai": "dang_soan",
		"tien_do": json.dumps({"chia": {}, "nhat": {}}), "hoa_don": [{"hoa_don": x, "ro": _ro(i)} for i, x in enumerate(ds)],
	})
	doc.insert(ignore_permissions=True)
	return doc.name


@rpc("cap_nhat_luot_soan")
def cap_nhat_luot_soan(p_id=None, p_invoice_ids=None, p_nhat=None, p_chia=None):
	"""Đổi danh sách HĐ của lượt và / hoặc gộp tiến độ nhặt / chia (từng khoá; giá trị null = xoá khoá) → dòng lượt sau khi ghi."""
	_quyen()
	_khoa_luot(p_id)
	doc = frappe.get_doc("NPP Luot Soan", p_id)
	if p_invoice_ids is not None:
		doc.set("hoa_don", [{"hoa_don": x, "ro": _ro(i)} for i, x in enumerate(_hoa_don(p_invoice_ids))])
	td = _json(doc.tien_do)
	for khoa, moi in (("nhat", p_nhat), ("chia", p_chia)):
		if isinstance(moi, dict):
			cu = td.get(khoa)
			td[khoa] = _bo_null({**(cu if isinstance(cu, dict) else {}), **moi})
	doc.tien_do = json.dumps(td, ensure_ascii=False)
	doc.save(ignore_permissions=True)
	return _hang(doc.name)


@rpc("hoan_tat_luot_soan")
def hoan_tat_luot_soan(p_id=None):
	"""Đóng lượt (xong) + đánh dấu đã soạn các HĐ của lượt chưa có dấu → số HĐ được đánh dấu. Không trừ kho."""
	nc = _quyen()
	_khoa_luot(p_id)
	luc = now_datetime()
	frappe.db.set_value("NPP Luot Soan", p_id, {"trang_thai": "xong", "xong_luc": luc, "xong_boi": nc.user})
	ids = frappe.get_all("NPP Luot Soan Hoa Don", filters={"parent": p_id, "parenttype": "NPP Luot Soan"}, pluck="hoa_don", order_by="idx")
	return _danh_dau(ids, True, nc.user, luc)


@rpc("huy_luot_soan")
def huy_luot_soan(p_id=None):
	"""Huỷ lượt đang soạn (dấu soạn đã có trên HĐ giữ nguyên)."""
	_quyen()
	if not frappe.db.sql("SELECT `name` FROM `tabNPP Luot Soan` WHERE `name` = %s AND `trang_thai` = 'dang_soan' FOR UPDATE", (str(p_id or ""),)):
		raise NppLoi("KHONG_TIM_THAY_LUOT: không có lượt đang soạn này")
	frappe.db.set_value("NPP Luot Soan", p_id, "trang_thai", "huy")


@rpc("danh_dau_soan_hang")
def danh_dau_soan_hang(p_ids=None, p_da=True):
	"""mig 224: đánh dấu (p_da) / gỡ dấu đã soạn hàng cho các HĐ đã ghi sổ → số HĐ đổi."""
	nc = _quyen("đánh dấu soạn hàng")
	if p_da is None:  # (soan_luc IS NULL) = NULL → không dòng nào
		return 0
	return _danh_dau(list(p_ids or []), bool(p_da), nc.user, now_datetime())
