"""RPC phiếu thu tiền của khách — create_cash_receipt / void_cash_receipt (nppsale mig 120 → 191 → 212 → 215 → 227; đặc tả phiếu thu §2.1–§2.2).

Phiếu = `NPP Phieu Thu` (không submit) bọc chứng từ sổ của lõi:
- Payment Entry (Receive) CÙNG TÊN phiếu khi có tiền thật (`tien_thu > 0`): một tham chiếu mỗi HĐ = Σ dòng `payment` của HĐ ấy;
- bút toán Credit Note `CTR-` khi dùng dư có (`use_credit > 0`): vế Nợ = chứng từ ÂM của dòng nguồn (tờ ghi có / HĐ âm / PE tiền thừa), vế Có =
  HĐ được đắp. "Rút" và "đắp" vẫn là hai dòng phiếu thu như nppsale (dòng âm `credit_applied` ở nguồn, dòng dương ở khoản được đắp).
Công nợ (`NPP Cong No`) là bản chiếu từ Payment Ledger — method chiếu lại mọi nhóm bị chạm sau khi ghi (hook PE / JE cũng chiếu).

Thứ tự kiểm + câu lỗi chép nguyên văn hàm Postgres đang chạy. Lệch có chủ ý (00_quyet_dinh_trien_khai.md Q7): khoá khách + mọi dòng công nợ của
khách TRƯỚC khi tính dư có (Q5 — nppsale để hai phiếu rút cùng một dư có, phiếu sau ghi tiền mặt mà không ai đưa); `method` ngoài
cash / transfer / ewallet bị từ chối cả khi là credit_applied / return_credit (Q14); mã phiếu PTH-YYMMDD-#### chạy liên tục thay 4 số ngẫu nhiên;
nhánh cấn phiếu trả (`credits`) chỉ còn phần kiểm — sau mig 191 chỉ phiếu 0đ lọt điều kiện, không ghi gì (`applied_receipt_id` không port).
"""
from __future__ import annotations

import hashlib
import uuid as _uuid
from decimal import Decimal, InvalidOperation

import frappe
from frappe.utils import getdate, now_datetime, nowdate

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import co_quyen, hien_tai
from nppsale.cong.sql import LoiCong
from nppsale.su_kien import cong_no as CN
from nppsale.thiet_lap.ban_hang import cai_dat_ban

from . import rpc
from .phieu_tra import _json, _ngay_pg, _van_ban

DT = "NPP Phieu Thu"
HINH_THUC = ("cash", "transfer", "ewallet")
_LO = Decimal("0.01")


# ------------------------------------------------------------------------------------------------ đọc tham số như Postgres
def _so(v) -> Decimal | None:
	"""(x->>'k')::numeric — null → None; sai dạng → 22P02 nguyên văn."""
	if v is None:
		return None
	t = _van_ban(v)
	try:
		d = Decimal(t.strip())
	except InvalidOperation:
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{t}"') from None
	if not d.is_finite():
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{t}"')
	return d


def _uuid_pg(v) -> str | None:
	"""(x->>'k')::uuid — null → None; chuẩn về chữ thường có gạch; sai dạng → 22P02."""
	if v is None:
		return None
	t = _van_ban(v)
	try:
		return str(_uuid.UUID(t.strip()))
	except ValueError:
		raise LoiCong("22P02", f'invalid input syntax for type uuid: "{t}"') from None


def _mang(p: dict, khoa: str) -> list:
	"""jsonb_array_elements(COALESCE(p->'k', '[]')) — thiếu khoá → []; JSON null (p->'k' là jsonb 'null', COALESCE không thay) → lỗi vô hướng."""
	v = p.get(khoa)
	if v is None:
		if khoa in p:
			raise LoiCong("22023", "cannot extract elements from a scalar")
		return []
	if isinstance(v, list):
		return v
	raise LoiCong("22023", "cannot extract elements from an object" if isinstance(v, dict) else "cannot extract elements from a scalar")


def _in_so(x) -> str:
	"""Số trong câu lỗi: số nguyên in không phần lẻ (đặc tả §2.0.2)."""
	d = x if isinstance(x, Decimal) else Decimal(str(x))
	if d == d.to_integral_value():
		return str(int(d))
	return format(d.normalize(), "f")


def _p(p) -> dict:
	p = _json(p)
	return p if isinstance(p, dict) else {}


def _dung_du_co(p: dict) -> tuple[Decimal, str]:
	"""v_use := GREATEST(0, COALESCE((p->>'use_credit')::numeric, 0)) — kèm chữ in lại (Postgres in số theo thang gửi lên)."""
	d = _so(p.get("use_credit"))
	if d is None or d <= 0:
		return Decimal(0), "0"
	return d, format(d, "f")


def _ten_khoa(key: str) -> str:
	return "npp_pt:" + hashlib.md5(key.encode("utf-8")).hexdigest()


def _nha_khoa(ten: str) -> None:
	try:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", ten)
	except Exception:  # noqa: BLE001 — kết nối đã đóng thì khoá phiên đã tự nhả
		pass


# ------------------------------------------------------------------------------------------------ create_cash_receipt
def _chuan_bi_thu(p=None):
	"""Trước khi khoá (cổng COMMIT sau bước này): người gọi + quyền + cài đặt; ép kiểu của khối DECLARE (lỗi ép kiểu nổ trước cả FORBIDDEN);
	`client_key`: khoá phiên MariaDB (GET_LOCK — sống qua COMMIT của cổng, nhả ở after_commit / after_rollback của thân hàm) rồi tra phiếu đã
	lập cùng khoá (mig 215: bấm Lưu hai lần, mạng chập chờn → trả lại phiếu cũ, mọi trạng thái)."""
	nc = hien_tai()
	cai_dat_ban()
	kq = frappe._dict(duoc=bool(co_quyen(nc, "receivables.create")), loi_dau=None, khoa=None, cu=None, xong=True)
	frappe.local._npp_phieu_thu = kq
	p = _p(p)
	try:
		if p.get("customer_id") == "":  # (p->>'customer_id')::uuid của khối DECLARE — chuỗi rỗng nổ trước cả FORBIDDEN
			raise LoiCong("22P02", 'invalid input syntax for type uuid: ""')
		_dung_du_co(p)
	except LoiCong as e:
		kq.loi_dau = e
		return kq
	if not kq.duoc:
		return kq
	key = _van_ban(p.get("client_key"))
	if key:
		ten = _ten_khoa(key)
		if not frappe.db.sql("SELECT GET_LOCK(%s, 30)", ten)[0][0]:
			raise frappe.QueryTimeoutError(f"Đang lập phiếu thu cùng client_key ở phiên khác ({key})")
		kq.khoa = ten
		if not frappe.flags.in_test:  # bỏ ảnh chụp REPEATABLE READ cũ: phải thấy phiếu phiên trước vừa ghi rồi mới nhả khoá
			frappe.db.commit()
		kq.cu = frappe.db.get_value(DT, {"client_key": key}, "name")
	return kq


def _hen_nha(ten: str) -> None:
	frappe.db.after_commit.add(lambda: _nha_khoa(ten))
	frappe.db.after_rollback.add(lambda: _nha_khoa(ten))


def _ngay_chon(r) -> tuple:
	"""ORDER BY due_date NULLS LAST, id."""
	h = r.get("han_thanh_toan")
	return (h is None, getdate(h) if h else None, r.get("name"))


def _hd_cua_dong(r) -> str | None:
	"""`invoice_id` của dòng công nợ theo nghĩa nppsale: HĐ (dòng HĐ); nợ đầu kỳ + phiếu trả + tiền thừa chưa phân bổ: trống."""
	return r.get("hoa_don") if r.get("loai") == "hoa_don" else None


def _si_cua_dong(r) -> str | None:
	"""Chứng từ sổ của dòng đích (HĐ / tờ nợ đầu kỳ)."""
	return r.get("hoa_don") if r.get("loai") in ("hoa_don", "dau_ky") else None


@rpc("create_cash_receipt", ghi=True, chuan_bi=_chuan_bi_thu)
def create_cash_receipt(p=None):
	kq = getattr(frappe.local, "_npp_phieu_thu", None)
	frappe.local._npp_phieu_thu = None
	if kq is None:  # gọi thẳng không qua cổng
		kq = _chuan_bi_thu(p)
	if kq.khoa:
		_hen_nha(kq.khoa)
	nc = hien_tai()
	cd = cai_dat_ban()
	if kq.loi_dau:
		raise kq.loi_dau
	if not kq.duoc:
		raise NppLoi("FORBIDDEN: bạn không có quyền lập phiếu thu")
	if kq.cu:
		return kq.cu
	p = _p(p)
	kh = _van_ban(p.get("customer_id"))
	if not kh:
		raise NppLoi("CUSTOMER_REQUIRED: chưa chọn khách hàng")
	use, use_chu = _dung_du_co(p)
	if use != use.to_integral_value():
		raise NppLoi("BAD_AMOUNT: số dư có dùng phải là số đồng chẵn")

	# Q5 / Q15 — khoá khách rồi mọi dòng công nợ của khách TRƯỚC mọi câu đọc thường (số còn nợ / dư có đọc sau khoá, từ sổ)
	dong = {r.name: r for r in CN.khoa_khach(kh)}
	con: dict[str, Decimal] = {}

	def con_no(r) -> Decimal:
		if r.name not in con:
			con[r.name] = Decimal(str(round(CN.con_no_dong(r), 2)))
		return con[r.name]

	lines = _mang(p, "lines")
	# v_sum_line: gộp theo CHUỖI receivable_id (nhóm id rỗng vẫn cộng); SUM bỏ qua amount null
	nhom_chu: dict = {}
	for l in lines:
		rid = _van_ban(l.get("receivable_id")) if isinstance(l, dict) else None
		so = _so(l.get("amount")) if isinstance(l, dict) else None
		if so is not None:
			nhom_chu[rid] = nhom_chu.get(rid, Decimal(0)) + so
	sum_line = sum(nhom_chu.values(), Decimal(0))
	credits = _mang(p, "credits")
	tra_ids = list(dict.fromkeys(_van_ban(c.get("return_id")) if isinstance(c, dict) else None for c in credits))
	tra_ids = [x for x in tra_ids if x]
	sum_cred = Decimal(0)
	for t in tra_ids:
		v = frappe.db.get_value("NPP Phieu Tra", t, "tien_tra")
		if v is not None or frappe.db.exists("NPP Phieu Tra", t):
			sum_cred += Decimal(str(v or 0))
	if sum_line <= 0 and sum_cred <= 0:
		raise NppLoi("EMPTY_RECEIPT: chưa chọn khoản nào để thu")
	if sum_cred > sum_line:
		raise NppLoi("CREDIT_EXCEEDS_SELECTED: cấn trừ vượt số nợ đã chọn")
	if use > 0:
		avail = sum((max(Decimal(0), -con_no(r)) for r in dong.values()), Decimal(0))
		if use > avail + _LO:
			raise NppLoi(f"CREDIT_BALANCE_TOO_LOW: khách chỉ còn {_in_so(avail)} số dư có, không rút được {use_chu}")
		if use > sum_line - sum_cred + _LO:
			raise NppLoi("CREDIT_EXCEEDS_SELECTED: số dư có dùng vượt phần còn phải trả")

	# gộp theo khoản nợ (id ép kiểu uuid như nppsale) rồi kiểm từng khoản: cùng khách, > 0, đồng chẵn, không vượt số còn nợ
	nhom: dict = {}
	for l in lines:
		rid = _uuid_pg(l.get("receivable_id")) if isinstance(l, dict) else None
		so = _so(l.get("amount")) if isinstance(l, dict) else None
		if rid not in nhom:
			nhom[rid] = None
		if so is not None:
			nhom[rid] = (nhom[rid] or Decimal(0)) + so
	for rid, tong in nhom.items():
		r = dong.get(rid) if rid else None
		if not (r and tong is not None and tong > 0 and tong == tong.to_integral_value() and tong <= con_no(r) + _LO):
			raise NppLoi("BAD_RECEIVABLE_LINE: khoản nợ không hợp lệ hoặc thu vượt số còn nợ")

	# phiếu trả cấn trừ (nhánh cũ): phải cùng khách, hoàn thành, không theo đơn / HĐ, chưa thành dòng công nợ âm
	for t in tra_ids:
		pt = frappe.db.get_value("NPP Phieu Tra", t, ["name", "khach_hang", "trang_thai", "don_hang", "hoa_don", "tien_tra"], as_dict=True)
		if not pt or pt.khach_hang != kh or pt.trang_thai != "completed" or pt.don_hang or pt.hoa_don or frappe.db.exists(
				CN.DT, {"phieu_tra": pt.name}) or (pt.tien_tra or 0) != 0:
			raise NppLoi("BAD_CREDIT: phiếu trả không đủ điều kiện cấn trừ")

	ngay_v = p.get("receipt_date")
	ngay = _ngay_pg(_van_ban(ngay_v)) if ngay_v is not None else getdate(nowdate())
	method = _van_ban(p.get("method"))
	method = "cash" if method is None else method
	tien_thu = sum_line - sum_cred - use
	if tien_thu > 0 and method not in HINH_THUC:
		raise LoiCong("23514", 'new row for relation "payments" violates check constraint "chk_payments_method_v2"')

	# ---- kế hoạch dòng (đúng thứ tự chèn của nppsale) + vế bút toán
	alloc = []
	for rid, tong in nhom.items():
		r = dong[rid]
		alloc.append(frappe._dict(r=r, left=tong))
	alloc.sort(key=lambda a: _ngay_chon(a.r))
	ke: list[dict] = []
	no_ct: list[tuple[str, str, Decimal]] = []  # vế Nợ bút toán cấn trừ: (loại, chứng từ, tiền)
	co_hd: dict[str, Decimal] = {}  # vế Có: HĐ → tiền
	cham: dict[str, object] = {}  # dòng công nợ bị chạm
	if use > 0:
		con_rut = use
		nguon = sorted((r for r in dong.values() if con_no(r) < 0), key=_ngay_chon)
		for src in nguon:
			if con_rut <= 0:
				break
			take = min(-con_no(src), con_rut)
			if take <= 0:
				continue
			am = CN.chung_tu_am(src)
			du = take
			for loai_ct, ten_ct, x in am:
				lay = min(Decimal(str(round(x, 2))), du)
				if lay > 0:
					no_ct.append((loai_ct, ten_ct, lay))
					du -= lay
			if du > _LO:
				frappe.throw(f"Dư có của dòng công nợ {src.name} không khớp chứng từ sổ (thiếu {du}) — chạy khám sổ công nợ")
			cham[src.name] = src
			ke.append({"loai": "credit_applied", "so_tien": -take, "cong_no": src.name, "hoa_don": _hd_cua_dong(src), "don_hang": None,
				"chung_tu_loai": am[0][0] if am else None, "chung_tu": am[0][1] if am else None})
			for a in alloc:
				if take <= 0:
					break
				if a.left > 0:
					ap = min(a.left, take)
					si = _si_cua_dong(a.r)
					ke.append({"loai": "credit_applied", "so_tien": ap, "cong_no": a.r.name, "hoa_don": _hd_cua_dong(a.r),
						"don_hang": a.r.don_hang, "chung_tu_loai": "Sales Invoice", "chung_tu": si})
					co_hd[si] = co_hd.get(si, Decimal(0)) + ap
					a.left -= ap
					take -= ap
					con_rut -= ap
		if con_rut > _LO:
			frappe.throw(f"Không rút đủ dư có đã kiểm ({con_rut} còn thiếu) — chạy khám sổ công nợ")
	tham_chieu: dict[str, Decimal] = {}  # tham chiếu Payment Entry: HĐ → tiền
	for a in alloc:
		cham[a.r.name] = a.r
		if a.left > 0:
			si = _si_cua_dong(a.r)
			ke.append({"loai": "payment", "so_tien": a.left, "cong_no": a.r.name, "hoa_don": _hd_cua_dong(a.r), "don_hang": a.r.don_hang,
				"chung_tu_loai": "Sales Invoice", "chung_tu": si})
			tham_chieu[si] = tham_chieu.get(si, Decimal(0)) + a.left

	# ---- ghi
	bay_gio = now_datetime()
	nv = nc.user if frappe.db.exists("NPP Nhan Vien", nc.user) else None
	pt_doc = frappe.get_doc({
		"doctype": DT, "khach_hang": kh, "ngay_thu": ngay, "hinh_thuc": method if method in HINH_THUC else "cash", "trang_thai": "received",
		"nguon": "standalone", "tong_chon": float(sum_line), "dung_du_co": float(use), "tien_thu": float(tien_thu), "nguoi_thu": nv, "nhan_boi": nv,
		"nhan_luc": bay_gio, "ghi_chu": _van_ban(p.get("notes")), "client_key": _van_ban(p.get("client_key")) or None,
		"dong": [{**k, "so_tien": float(k["so_tien"])} for k in ke],
	})
	pt_doc.flags.ignore_permissions = True
	pt_doc.flags.ignore_mandatory = not nv  # người gọi không có hồ sơ NV (Administrator / việc nền)
	diem = "npp_phieu_thu_chen"
	frappe.db.savepoint(diem)
	try:
		pt_doc.insert()
	except frappe.DuplicateEntryError:
		# lưới cuối của client_key (khoá phiên đã giữ thứ tự — chỉ tới đây khi khoá hết giờ chờ): trả phiếu đã lập
		frappe.db.rollback(save_point=diem)
		cu = frappe.db.sql(f"SELECT `name` FROM `tab{DT}` WHERE `client_key` = %s FOR UPDATE", _van_ban(p.get("client_key")))
		if cu:
			return cu[0][0]
		raise
	ten = pt_doc.name
	je = _lap_can_tru(ten, kh, ngay, no_ct, co_hd, cd) if no_ct else None
	pe = _lap_tien(ten, kh, ngay, method, tien_thu, tham_chieu, cd) if tien_thu > 0 else None
	frappe.db.set_value(DT, ten, {"but_toan_tien": pe, "but_toan_can_tru": je}, update_modified=False)
	# dấu quá hạn mất trên mọi khoản bị chạm (nppsale ghi status CASE paid / partial / open lên đích và nguồn)
	for r in cham.values():
		si = _si_cua_dong(r)
		if si and frappe.db.get_value("Sales Invoice", si, "npp_qua_han_tay"):
			frappe.db.set_value("Sales Invoice", si, "npp_qua_han_tay", 0, update_modified=False)
	for r in cham.values():
		CN.chieu_dong(r)
	frappe.local.message_log = []
	return ten


def _tk_phai_thu(kh: str, cong_ty: str) -> str:
	from erpnext.accounts.party import get_party_account

	return get_party_account("Customer", kh, cong_ty)


def _tk_cua_chung_tu(loai: str, ten: str) -> str:
	return frappe.db.get_value("Sales Invoice", ten, "debit_to") if loai == "Sales Invoice" else frappe.db.get_value(
		"Payment Entry", ten, "paid_from")


def _lap_can_tru(phieu: str, kh: str, ngay, no_ct, co_hd, cd, amend_tu: str | None = None) -> str:
	"""Bút toán Credit Note `CTR-` của phần dùng dư có: vế Nợ trỏ chứng từ âm của nguồn, vế Có trỏ HĐ được đắp; Σ Nợ = Σ Có."""
	je = frappe.new_doc("Journal Entry")
	je.update({"voucher_type": "Credit Note", "naming_series": "CTR-.####", "company": cd.cong_ty, "posting_date": ngay,
		"npp_loai": "can_tru_khach", "npp_phieu_thu": phieu, "user_remark": f"Cấn trừ dư có — {phieu}", "is_system_generated": 0})
	if amend_tu:
		je.amended_from = amend_tu
	for loai, ten, x in no_ct:
		je.append("accounts", {"account": _tk_cua_chung_tu(loai, ten), "party_type": "Customer", "party": kh, "debit_in_account_currency": float(x),
			"reference_type": loai, "reference_name": ten})
	for si, x in co_hd.items():
		je.append("accounts", {"account": _tk_cua_chung_tu("Sales Invoice", si), "party_type": "Customer", "party": kh,
			"credit_in_account_currency": float(x), "reference_type": "Sales Invoice", "reference_name": si})
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	frappe.local.message_log = []
	return je.name


def _lap_tien(phieu: str, kh: str, ngay, method: str, tien, tham_chieu: dict, cd) -> str:
	"""Payment Entry (Receive) cùng tên phiếu: một tham chiếu mỗi HĐ (lõi cấm hai tham chiếu cùng HĐ + cùng kỳ hạn)."""
	ht = cd.hinh_thuc[method]
	tk_tien = frappe.db.get_value("Mode of Payment Account", {"parent": ht, "company": cd.cong_ty}, "default_account")
	if not tk_tien:
		frappe.throw(f"Hình thức thanh toán {ht} chưa có tài khoản cho công ty {cd.cong_ty} (NPP Cai Dat)")
	pe = frappe.new_doc("Payment Entry")
	pe.update({"naming_series": "ACC-PAY-.YYYY.-", "payment_type": "Receive", "company": cd.cong_ty, "posting_date": ngay,
		"mode_of_payment": ht, "party_type": "Customer", "party": kh, "paid_from": _tk_phai_thu(kh, cd.cong_ty), "paid_to": tk_tien,
		"paid_amount": float(tien), "received_amount": float(tien), "source_exchange_rate": 1, "target_exchange_rate": 1, "reference_no": phieu,
		"reference_date": ngay, "npp_loai": "phieu_thu", "npp_phieu_thu": phieu})
	for si, x in tham_chieu.items():
		pe.append("references", {"reference_doctype": "Sales Invoice", "reference_name": si, "allocated_amount": float(x)})
	pe.flags.ignore_permissions = True
	pe.insert(set_name=phieu)
	pe.submit()
	frappe.local.message_log = []
	return pe.name


# ------------------------------------------------------------------------------------------------ void_cash_receipt
def _chuan_bi_huy_thu(p_receipt_id=None, p_reason=None):
	"""Không kiểm quyền ở đây (nppsale báo RECEIPT_NOT_FOUND trước FORBIDDEN) — chỉ nạp người gọi + cài đặt."""
	nc = hien_tai()
	co_quyen(nc, "receivables.update")
	cai_dat_ban()


def _qua_han_sau_huy(si: str) -> None:
	"""CASE của void_cash_receipt + trigger (mig 120 / 212 / 227): khoản bị gỡ tiền về `overdue` khi còn nợ, đã thu ≤ 0, có hạn và hạn đã qua
	(giờ VN); ngược lại mất dấu."""
	r = frappe.db.get_value(CN.DT, {"khoa_nguon": f"Sales Invoice:{si}"}, ["so_tien", "da_thu", "han_thanh_toan"], as_dict=True)
	co = 0
	if r and (r.so_tien or 0) >= 0 and (r.so_tien or 0) - (r.da_thu or 0) >= 0.01 and (r.da_thu or 0) <= 0 and r.han_thanh_toan \
			and getdate(r.han_thanh_toan) < getdate(nowdate()):
		co = 1
	if int(frappe.db.get_value("Sales Invoice", si, "npp_qua_han_tay") or 0) != co:
		frappe.db.set_value("Sales Invoice", si, "npp_qua_han_tay", co, update_modified=False)


@rpc("void_cash_receipt", ghi=True, chuan_bi=_chuan_bi_huy_thu)
def void_cash_receipt(p_receipt_id=None, p_reason=None):
	nc = hien_tai()
	cai_dat_ban()
	ten = _van_ban(p_receipt_id)
	r = frappe.db.sql(f"""SELECT `name`, `trang_thai`, `khach_hang`, `but_toan_tien`, `but_toan_can_tru`
		FROM `tab{DT}` WHERE `name` = %s FOR UPDATE""", ten, as_dict=True) if ten else []
	if not r:
		raise NppLoi("RECEIPT_NOT_FOUND")
	r = r[0]
	if not co_quyen(nc, "receivables.update"):
		raise NppLoi("FORBIDDEN: bạn không có quyền huỷ phiếu thu")
	if r.trang_thai not in ("pending", "received"):
		raise NppLoi(f"RECEIPT_NOT_VOIDABLE: phiếu ở trạng thái {r.trang_thai} không huỷ được")
	ly_do = _van_ban(p_reason)
	if ly_do is None or ly_do.strip(" ") == "":  # btrim(): chỉ bỏ dấu cách
		raise NppLoi("REASON_REQUIRED: phải ghi lý do huỷ phiếu thu")
	CN.khoa_khach(r.khach_hang)
	cham = {d.cong_no for d in frappe.get_all("NPP Phieu Thu Dong", filters={"parent": ten, "parenttype": DT}, fields=["cong_no"]) if d.cong_no}

	# phần thu vượt sau Sửa HĐ đã chuyển vào HĐ (bút toán `chuyen_tien_thua` của phiếu): huỷ trước PE — nợ HĐ tăng lại; phần ấy đã bị phiếu khác
	# rút thì bút toán cấn trừ của phiếu kia (trỏ HĐ) giữ nguyên → "khách nợ lại" trên chính dòng HĐ (mig 212 §2)
	from .can_tru import huy_je

	chuyen = frappe.get_all("Journal Entry", filters={"npp_phieu_thu": ten, "npp_loai": "chuyen_tien_thua", "docstatus": 1}, pluck="name")
	for je in frappe.get_all("Journal Entry Account", filters={"parent": ("in", chuyen or [""]), "reference_type": "Sales Invoice"},
			pluck="reference_name"):
		r_hd = frappe.db.get_value(CN.DT, {"khoa_nguon": f"Sales Invoice:{je}"}, "name")
		if r_hd:
			cham.add(r_hd)
	huy_je(chuyen)
	for dt_ct, ct in (("Journal Entry", r.but_toan_can_tru), ("Payment Entry", r.but_toan_tien)):
		if ct and frappe.db.get_value(dt_ct, ct, "docstatus") == 1:
			d = frappe.get_doc(dt_ct, ct)
			d.flags.ignore_permissions = True
			d.cancel()
	frappe.local.message_log = []
	# Q18 (a): khoản thu của phiếu huỷ mất cùng `payments` ở nppsale → bỏ dấu xác nhận trên dòng (đếm chứng từ của NV khớp nppsale)
	frappe.db.sql("""UPDATE `tabNPP Phieu Thu Dong` SET `xac_nhan_boi` = NULL, `xac_nhan_luc` = NULL WHERE `parent` = %s
		AND `parenttype` = 'NPP Phieu Thu'""", ten)

	frappe.db.set_value(DT, ten, {"trang_thai": "voided", "huy_luc": now_datetime(),
		"huy_boi": nc.user if frappe.db.exists("NPP Nhan Vien", nc.user) else None, "ly_do_huy": ly_do}, update_modified=False)
	dong = frappe.get_all(CN.DT, filters={"name": ("in", list(cham) or [""])}, fields=["name", "loai", "hoa_don", "phieu_tra", "phieu_thu"])
	for d in dong:
		CN.chieu_dong(d)
	for d in dong:
		si = _si_cua_dong(d)
		if si:
			_qua_han_sau_huy(si)
			CN.chieu_hoa_don(si)
	CN.chieu_tien_thua(ten)
	frappe.local.message_log = []
	return None

