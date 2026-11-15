"""Nợ đầu kỳ + ghi thẳng `receivables` qua cổng (đặc tả phiếu thu §2.3; trigger `_khoa_ghi_thang_cong_no` mig 214, RLS mig 002 / 102 / 166).

Màn Nợ đầu kỳ (`/finance/opening-balances`) và nút "Đánh dấu quá hạn" / "Đặt lại trạng thái mở" ghi thẳng bảng `receivables`. Công nợ trên
Frappe là bản chiếu từ sổ, nên ghi thẳng đi qua đây:
- THÊM nợ đầu kỳ = lập + ghi sổ tờ Sales Invoice `DK-` (`is_opening = Yes`, một dòng không mã hàng, đối ứng TK tạm đầu kỳ) rồi chiếu;
- SỬA số nợ đầu kỳ chưa thu = huỷ + amend `DK-…-n` (giữ `name` dòng chiếu + ngày lập gốc); hạn / ghi chú = trường AOS của tờ; trạng thái chỉ
  còn nghĩa "đánh dấu quá hạn" (`npp_qua_han_tay`);
- XOÁ nợ đầu kỳ chưa thu = huỷ tờ.
Thứ tự kiểm như Postgres: trigger (CONG_NO_KHOA) → RLS (42501 / 0 dòng) → NOT NULL → duy nhất → khoá ngoại. Lệch có chủ ý (00_quyet_dinh Q7):
sửa SỐ nợ đầu kỳ đã thu → CONG_NO_KHOA (Q2 — nppsale cho, phần chênh thành dư có); số ≤ 0 / lẻ → BAD_AMOUNT (Q7); đổi người giữ / hạn /
ghi chú của dòng HĐ / phiếu trả → CONG_NO_KHOA (blueprint §6.1 — không màn nào gửi).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import frappe
from frappe.utils import add_days, get_datetime, getdate, now_datetime, nowdate

from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong
from nppsale.su_kien import cong_no as CN
from nppsale.thiet_lap.ban_hang import cai_dat_ban

BANG = "receivables"
COT = ("id", "org_id", "order_id", "customer_id", "sales_user_id", "amount", "paid", "due_date", "status", "created_at", "opening_balance",
	"note", "invoice_id", "return_id", "ve_npp_luc", "giao_tu_nv")
VAI_GHI = ("owner", "accountant")
KHOA_THEM = "CONG_NO_KHOA: công nợ chỉ sinh từ hóa đơn / phiếu trả — màn hình chỉ thêm được nợ đầu kỳ chưa thu"
KHOA_SUA = "CONG_NO_KHOA: số nợ / số đã thu chỉ đổi qua hóa đơn, phiếu trả, phiếu thu (RPC)"
KHOA_XOA = "CONG_NO_KHOA: chỉ xoá được nợ đầu kỳ chưa thu đồng nào"
BAD_AMOUNT = "BAD_AMOUNT: nợ đầu kỳ phải là số đồng chẵn lớn hơn 0"


def _cot_la(gt: dict) -> None:
	for k in gt:
		if k not in COT:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{BANG}' in the schema cache", http=400)


def _so(v, cot: str) -> Decimal | None:
	if v is None:
		return None
	if isinstance(v, bool):
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{str(v).lower()}"')
	try:
		d = Decimal(str(v).strip())
	except InvalidOperation:
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{v}"') from None
	if not d.is_finite():
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{v}"')
	return d


def _ngay(v):
	from nppsale.rpc.phieu_tra import _ngay_pg

	return None if v is None else _ngay_pg(v)


def _bool(v):
	from nppsale.rpc.phieu_tra import _bool_pg

	return False if v is None else _bool_pg(v)


def _org() -> str:
	return frappe.db.get_single_value("NPP Cai Dat", "org_id") or ""


def _tu_choi():
	raise LoiCong("42501", f'new row violates row-level security policy for table "{BANG}"', http=403)


def _gia_tri_hien_tai(r) -> dict:
	"""Giá trị cột cổng của một dòng chiếu (để so "gửi lại đúng giá trị cũ")."""
	return {"id": r.name, "org_id": _org(), "order_id": r.don_hang, "customer_id": r.khach_hang, "sales_user_id": r.nhan_vien,
		"amount": r.so_tien, "paid": r.da_thu, "due_date": r.han_thanh_toan, "status": r.trang_thai, "created_at": r.tao_luc,
		"opening_balance": r.loai == "dau_ky", "note": r.ghi_chu,
		"invoice_id": r.hoa_don if r.loai in ("hoa_don", "tien_thua") else None, "return_id": r.phieu_tra,
		"ve_npp_luc": r.ve_npp_luc, "giao_tu_nv": r.giao_tu_nv}


def _khac(cot: str, moi, cu) -> bool:
	"""IS DISTINCT FROM theo kiểu cột của Postgres."""
	if moi is None or cu is None:
		return (moi is None) != (cu is None)
	if cot in ("amount", "paid"):
		return _so(moi, cot) != Decimal(str(cu))
	if cot == "due_date":
		return _ngay(moi) != getdate(cu)
	if cot in ("created_at", "ve_npp_luc"):
		from nppsale.cong.bang._chung import gio_vao

		return get_datetime(gio_vao(moi)) != get_datetime(cu)
	if cot == "opening_balance":
		return bool(_bool(moi)) != bool(cu)
	return str(moi) != str(cu)


def _nv_hop_le(nv: str | None, rang_buoc: str) -> None:
	if nv is not None and not frappe.db.exists("NPP Nhan Vien", nv):
		raise LoiCong("23503", f'insert or update on table "{BANG}" violates foreign key constraint "{rang_buoc}"', http=409)


# ------------------------------------------------------------------------------------------------ THÊM
def ghi_no_dau_ky(ds: list[dict], nc) -> list[str]:
	"""INSERT nhiều dòng = một câu Postgres: hỏng một dòng là hỏng cả lệnh (cổng lui savepoint)."""
	from nppsale.luat.giu_no import khi_lap
	from nppsale.rpc.gan_nguoi import da_nghi

	cd = cai_dat_ban()
	ra = []
	for g in ds:
		g = g or {}
		_cot_la(g)
		# trigger _khoa_ghi_thang_cong_no (chạy trước RLS)
		if not _bool(g.get("opening_balance")) or g.get("invoice_id") is not None or g.get("order_id") is not None or \
				g.get("return_id") is not None or (_so(g.get("paid"), "paid") or 0) != 0:
			raise NppLoi(KHOA_THEM)
		if not nc.bo_qua_rls and (nc.vai not in VAI_GHI or g.get("org_id") not in (None, _org())):
			_tu_choi()
		for cot in ("customer_id", "amount"):
			if g.get(cot) is None:
				raise LoiCong("23502", f'null value in column "{cot}" of relation "{BANG}" violates not-null constraint', http=400)
		so = _so(g.get("amount"), "amount")
		if so <= 0 or so != so.to_integral_value():
			raise NppLoi(BAD_AMOUNT)
		kh = str(g.get("customer_id"))
		han = _ngay(g.get("due_date")) if g.get("due_date") is not None else None
		CN.khoa_khach(kh)
		if frappe.db.exists(CN.DT, {"khach_hang": kh, "loai": "dau_ky"}):
			raise LoiCong("23505", 'duplicate key value violates unique constraint "uq_receivables_opening"', http=409)
		if not frappe.db.exists("Customer", kh):
			raise LoiCong("23503", f'insert or update on table "{BANG}" violates foreign key constraint "receivables_customer_id_fkey"', http=409)
		nv = g.get("sales_user_id")
		_nv_hop_le(nv, "receivables_sales_user_id_fkey")
		giu = khi_lap(nv, da_nghi, now_datetime())
		si = _lap_dk(kh, so, han, g.get("note"), nv, giu, g.get("status") == "overdue", cd)
		_ghi_so(si)
		ra.append(CN.chieu_hoa_don(si))
	return [x for x in ra if x]


def _lap_dk(kh, so, han, ghi_chu, nv, giu, qua_han, cd, amend_tu: str | None = None, posting=None) -> str:
	"""Tờ nợ đầu kỳ `DK-` (như Opening Invoice Creation Tool của lõi): một dòng không mã hàng, đối ứng TK tạm đầu kỳ, không kho, không thuế."""
	if not cd.tk_tam_dau_ky:
		frappe.throw("Chưa có TK tạm đầu kỳ (NPP Cai Dat.tk_tam_dau_ky)")
	ngay = getdate(posting or nowdate())
	si = frappe.new_doc("Sales Invoice")
	si.update({
		"naming_series": "DK-.####", "customer": kh, "company": cd.cong_ty, "is_opening": "Yes", "is_pos": 0, "set_posting_time": 1,
		"posting_date": ngay, "due_date": max(ngay, getdate(han)) if han else ngay, "update_stock": 0, "disable_rounded_total": 1,
		"allocate_advances_automatically": 0, "taxes_and_charges": "", "payment_terms_template": None,
		"npp_han_thanh_toan": han, "npp_ghi_chu": ghi_chu, "npp_nhan_vien": nv, "npp_nv_giu_no": giu.nv, "npp_ve_npp_luc": giu.ve_npp,
		"npp_giao_tu_nv": giu.giao, "npp_qua_han_tay": 1 if qua_han else 0,
		"items": [{"item_name": "Nợ đầu kỳ", "description": "Nợ đầu kỳ", "qty": 1, "rate": float(so), "conversion_factor": 1,
			"uom": frappe.db.get_single_value("Stock Settings", "stock_uom") or "Nos", "income_account": cd.tk_tam_dau_ky,
			"cost_center": frappe.get_cached_value("Company", cd.cong_ty, "cost_center")}],
	})
	if amend_tu:
		si.amended_from = amend_tu
	si.set("taxes", [])
	si.flags.ignore_permissions = True
	si.insert()
	return si.name


def _ghi_so(ten: str) -> None:
	si = frappe.get_doc("Sales Invoice", ten)
	si.flags.ignore_permissions = True
	si.submit()
	frappe.local.message_log = []


# ------------------------------------------------------------------------------------------------ SỬA
def _co_qua_han(so_tien, da_thu) -> int:
	"""PATCH status = 'overdue': trigger chỉ giữ khi dòng chưa thu đủ, không trả dư, số không âm (mig 212)."""
	return 1 if so_tien >= 0 and da_thu <= so_tien - 0.01 else 0


def sua_cong_no(gt: dict, ids: list[str], nc) -> list[str]:
	_cot_la(gt)
	if not nc.bo_qua_rls and nc.vai not in VAI_GHI:
		return []  # RLS UPDATE "Accountant/Owner can update receivables": 0 dòng, không lỗi
	cd = cai_dat_ban()
	ra = []
	for ten in ids:
		r = frappe.db.get_value(CN.DT, ten, ["name", "loai", "khach_hang", "hoa_don", "phieu_tra", "don_hang", "nhan_vien", "giao_tu_nv",
			"ve_npp_luc", "so_tien", "da_thu", "han_thanh_toan", "trang_thai", "tao_luc", "ghi_chu", "qua_han_tay"], as_dict=True)
		if not r:
			continue
		CN.khoa_khach(r.khach_hang)
		cu = _gia_tri_hien_tai(r)
		dau_ky = r.loai == "dau_ky"
		doi = {k for k, v in gt.items() if k != "status" and _khac(k, v, cu[k])}
		cam = {"paid", "invoice_id", "order_id", "return_id", "customer_id", "org_id", "opening_balance", "id", "sales_user_id", "ve_npp_luc",
			"giao_tu_nv", "created_at"}
		if not dau_ky:
			cam |= {"amount", "due_date", "note"}
		if doi & cam:
			raise NppLoi(KHOA_SUA)
		si = r.hoa_don
		so_moi = None
		if "amount" in doi:
			if abs(r.da_thu or 0) >= 0.005:
				raise NppLoi(KHOA_SUA)  # Q2: số nợ đầu kỳ đã thu → khoá (huỷ + lập lại tờ không mang được tiền đã thu)
			so_moi = _so(gt["amount"], "amount")
			if so_moi <= 0 or so_moi != so_moi.to_integral_value():
				raise NppLoi(BAD_AMOUNT)
		# trạng thái: chỉ còn nghĩa "dấu quá hạn" trên chứng từ nguồn có dấu (HĐ / tờ nợ đầu kỳ); không gửi → giữ
		co = int(r.qua_han_tay or 0)
		if "status" in gt and r.loai in ("hoa_don", "dau_ky"):
			so_tien = float(so_moi) if so_moi is not None else (r.so_tien or 0)
			co = _co_qua_han(so_tien, r.da_thu or 0) if gt["status"] == "overdue" else 0
		han = (_ngay(gt["due_date"]) if gt["due_date"] is not None else None) if "due_date" in doi else r.han_thanh_toan
		ghi_chu = gt["note"] if "note" in doi else r.ghi_chu
		if so_moi is not None:
			si = _lam_lai_dk(r, si, so_moi, han, ghi_chu, co, cd)
		elif si and r.loai in ("hoa_don", "dau_ky"):
			moi = {"npp_qua_han_tay": co}
			if dau_ky:
				moi.update({"npp_han_thanh_toan": han, "npp_ghi_chu": ghi_chu})
			cur = frappe.db.get_value("Sales Invoice", si, list(moi), as_dict=True)
			moi = {k: v for k, v in moi.items() if (cur.get(k) if k != "npp_han_thanh_toan" else (getdate(cur.get(k)) if cur.get(k) else None)) != (
				getdate(v) if (k == "npp_han_thanh_toan" and v) else v)}
			if moi:
				frappe.db.set_value("Sales Invoice", si, moi, update_modified=False)
		CN.chieu_dong(frappe._dict(loai=r.loai, hoa_don=si, phieu_tra=r.phieu_tra, phieu_thu=frappe.db.get_value(CN.DT, ten, "phieu_thu")))
		ra.append(ten)
	return ra


def _lam_lai_dk(r, si_cu: str, so_moi, han, ghi_chu, co, cd) -> str:
	"""Số nợ đầu kỳ mới (chưa thu): amend `DK-…-n` — giữ `name` dòng chiếu (link /receivables/<id>) và ngày lập gốc; chép trường app."""
	cu = frappe.get_doc("Sales Invoice", si_cu)
	from nppsale.luat.giu_no import GiuNo

	# lõi chỉ cho amend tờ ĐÃ huỷ → đổi khoá dòng chiếu sang khoá tạm trước khi huỷ (hook huỷ không xoá dòng), lập tờ mới rồi trỏ khoá vào
	frappe.db.set_value(CN.DT, r.name, "khoa_nguon", f"Sales Invoice:{si_cu}:lam_lai", update_modified=False)
	cu.flags.ignore_permissions = True
	cu.cancel()
	frappe.local.message_log = []
	moi = _lap_dk(cu.customer, so_moi, han, ghi_chu, cu.npp_nhan_vien, GiuNo(cu.npp_nv_giu_no, cu.npp_ve_npp_luc, cu.npp_giao_tu_nv), co, cd,
		amend_tu=cu.name, posting=cu.posting_date)
	frappe.db.set_value(CN.DT, r.name, {"khoa_nguon": f"Sales Invoice:{moi}", "hoa_don": moi}, update_modified=False)
	_ghi_so(moi)
	return moi


# ------------------------------------------------------------------------------------------------ XOÁ
def xoa_no_dau_ky(ids: list[str], nc) -> list[str]:
	ra = []
	for ten in ids:
		r = frappe.db.get_value(CN.DT, ten, ["name", "loai", "khach_hang", "hoa_don", "da_thu"], as_dict=True)
		if not r or (not nc.bo_qua_rls and nc.vai not in VAI_GHI) or r.loai != "dau_ky":
			continue  # RLS DELETE "Accountant can delete opening receivables": ngoài phạm vi → 0 dòng, không lỗi
		CN.khoa_khach(r.khach_hang)
		if abs(r.da_thu or 0) >= 0.005:
			raise NppLoi(KHOA_XOA)
		if frappe.db.exists("NPP Phieu Thu Dong", {"cong_no": ten, "parenttype": "NPP Phieu Thu"}):
			raise LoiCong("23503", f'update or delete on table "{BANG}" violates foreign key constraint "cash_receipt_lines_receivable_id_fkey" '
				'on table "cash_receipt_lines"', chi_tiet='Key is still referenced from table "cash_receipt_lines".', http=409)
		if r.hoa_don and frappe.db.get_value("Sales Invoice", r.hoa_don, "docstatus") == 1:
			si = frappe.get_doc("Sales Invoice", r.hoa_don)
			si.flags.ignore_permissions = True
			si.cancel()
			frappe.local.message_log = []
		frappe.db.delete(CN.DT, {"name": ten})
		ra.append(ten)
	return ra


_ = add_days
