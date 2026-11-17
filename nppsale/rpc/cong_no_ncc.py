"""CÔNG NỢ + TIỀN NCC (P4 — mốc M3; đặc tả kho_mua §2.8, §3.10–§3.12, §4.4, §5.1–§5.2; blueprint 02 §4.4, §5.7–§5.9, §6.1) — giữ tên nppsale (hàm
Postgres nguồn ở scratchpad kho_mua/src/<tên>.sql). Công nợ NCC là bản chiếu từ sổ (`nppsale.su_kien.cong_no_ncc`); method ở đây chỉ lập / huỷ chứng
từ lõi rồi chiếu lại.

RPC ghi (khuôn CFD-05: `chuan_bi` đọc người gọi + cài đặt → cổng COMMIT → thân hàm mà câu ĐẦU là khoá NCC rồi mọi dòng công nợ của NCC `FOR UPDATE`
— `cong_no_ncc.khoa_ncc`, thay khoá advisory / `FOR UPDATE payables` của nppsale; số còn nợ đọc từ Payment Ledger SAU khoá):
- `record_payable_payment` (mig 167): Ghi trả MỘT khoản — tiền mặt / chuyển khoản → Payment Entry Pay `GTN-` một tham chiếu; bù trừ (`offset`) → bút
  toán Debit Note `CTN-` (Nợ khoản được trả / Có các phiếu trả NCC còn khoản giảm, cũ nhất trước — §7.3 điểm 10, BP §7.1 điểm 15: vượt khoản giảm →
  `BU_TRU_KHONG_CON`); NULL / '' → tiền mặt (cổng trả `cash` — ⚠K: nppsale lưu `method NULL`). Không dồn trả trước (như nppsale). Trả `[{payment_id,
  new_paid, new_status}]` (`new_status` theo luật hàm gốc: đã trả ≥ số nợ → `paid`, không thì `partial`; dấu quá hạn tay KHÔNG xoá — §7.3 điểm 13).
- `chi_tra_ncc` (mig 242): phiếu chi một cục Payment Entry Pay `PCNCC-` — tham chiếu = phần dồn vào các khoản nợ cũ nhất (kế hoạch `ke_hoach_don` CHUNG
  với `don_tra_truoc_ncc`: phiếu chi khác còn tiền mà chi SỚM hơn dồn trước, như `_don_tra_truoc_ncc` gọi ở cuối hàm nppsale), phần dư = tiền trả trước
  (`unallocated_amount` — dòng `tra_truoc` của bản chiếu); ngày chi ≤ hôm nay giờ VN; lúc chi = giờ lập (chi hôm nay) / 12:00 ngày chi (ghi lùi).
- `huy_phieu_chi_ncc` (mig 242): idempotent; huỷ Payment Entry (lõi gỡ mọi phân bổ) → chiếu lại → tiền trả trước của phiếu chi KHÁC dồn vào khoản vừa mở.

RPC đọc: `payables_summary(p_since)`, `payables_by_supplier()` — qua cổng `payables` với RLS người gọi (hàm nppsale SECURITY INVOKER), không kẹp dòng âm
(mig 231).

Ghi thẳng qua cổng (`payables` / `payable_payments` / `supplier_payments` — nppsale.cong.bang.cong_no_ncc; trigger mig 227 + RLS mig 163):
- `payables` THÊM: trigger (đã trả ≠ 0 / trạng thái ngoài open–overdue → `NO_NCC_KHOA`) → RLS (owner / accountant) → NOT NULL → số ≤ 0 (⚠K §4.4 đề xuất:
  PI không âm) → trùng nợ đầu kỳ (`uq_payables_opening` 23505) → khoá ngoại; nợ đầu kỳ = tờ `DKN-` (`is_opening`, TK tạm đầu kỳ), còn lại = tờ `NTN-`
  (TK `tk_no_ncc_lap_tay`; gắn phiếu kho → `npp_phieu_kho`) → dồn trả trước (trigger mig 242 AFTER INSERT WHEN amount > 0).
  SỬA: RLS (owner / accountant, vai khác 0 dòng) → trigger: đổi đã trả / NCC / phiếu kho / cờ đầu kỳ / ngày ghi nợ, đổi số nợ ngoài khoản đầu kỳ không
  gắn phiếu kho → `NO_NCC_KHOA`; đổi trạng thái phải khớp số đã trả (chỉ kiểm khi trạng thái ĐỔI — soát thiếu S5); số nợ đầu kỳ đã trả → `NO_NCC_KHOA`
  (⚠K: nppsale cho); số nợ đầu kỳ chưa trả = huỷ + amend `DKN-…-n` (giữ tên dòng chiếu + ngày ghi nợ, gọi dồn — §7.3 điểm 27); số HĐ / hạn / ghi chú →
  trường AOS của tờ (`bill_no` / `npp_han_thanh_toan` / `npp_ghi_chu_no`); `overdue` ↔ dấu quá hạn tay. Dòng trả trước: mọi đổi → `NO_NCC_KHOA` (⚠K).
  XOÁ: đã trả / có dòng tiền → `NO_NCC_KHOA`; nợ của phiếu nhập / trả NCC → 23503 khoá ngoại nguyên văn (§7.3 điểm 38); `DKN-` / `NTN-` → huỷ tờ.
- `payable_payments`: chỉ xác nhận (`verified_by` / `verified_at` → `npp_xac_nhan_*` của dòng tham chiếu / dòng bút toán / phiếu chi); còn lại `CHI_NCC_KHOA`.
"""
from __future__ import annotations

from decimal import Decimal

import frappe
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, nowdate

from nppsale.cong.bang._chung import gio_vao, tu_choi
from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai
from nppsale.cong.sql import LoiCong
from nppsale.luat import cong_no_ncc as L
from nppsale.luat import kho_mua as K
from nppsale.su_kien import cong_no_ncc as N
from nppsale.thiet_lap.kho_mua import cai_dat_kho

from . import rpc
from .phieu_thu import _so, _uuid_pg
from .phieu_tra import _bool_pg, _ngay_pg, _van_ban

BANG = "payables"
COT_NO = ("id", "org_id", "supplier_id", "stock_entry_id", "invoice_number", "amount", "paid", "due_date", "status", "notes", "created_at",
	"opening_balance", "tim_kd")
COT_TRA = ("id", "payable_id", "amount", "method", "paid_by", "paid_at", "verified_by", "verified_at", "notes", "supplier_payment_id")
DAY_SO = {"dau_ky": "DKN-.####", "lap_tay": "NTN-.####"}
TEN_DONG = {"dau_ky": "Nợ đầu kỳ NCC", "lap_tay": "Nợ NCC lập tay"}


# ================================================================================================ hàm nhỏ
def _ra(x):
	"""numeric của Postgres ra JSON: số nguyên không phần lẻ."""
	d = x if isinstance(x, Decimal) else Decimal(str(round(flt(x), 6)))
	return int(d) if d == d.to_integral_value() else float(d)


def _tien(x) -> Decimal:
	"""Tiền đọc từ sổ (float của Frappe — số nguyên đồng) → Decimal như numeric của Postgres: `200000.0` → `200000` (in qua RAISE '%' không
	thêm `.0` — đặc tả §2.5 "tiền Frappe là số nguyên đồng → in str(int)"), số lẻ giữ chữ số ngắn nhất."""
	return K.so(round(flt(x), 2))


def _nv(nc) -> str | None:
	return nc.user if nc.user and frappe.db.exists("NPP Nhan Vien", nc.user) else None


def _org() -> str:
	return frappe.db.get_single_value("NPP Cai Dat", "org_id") or ""


def tk_no_lap_tay(cd) -> str | None:
	"""TK dòng của tờ nợ NCC lập tay `NTN-` (`NPP Cai Dat.tk_no_ncc_lap_tay`; trống → `Company.stock_received_but_not_billed` — quyết định tạm Q9: TK
	trung gian "hàng về chưa có hoá đơn", nợ lập tay gắn phiếu nhập kho tay `IN-` tất toán đúng phần kho đã ghi — §7.3 điểm 17)."""
	return cd.get("tk_no_ncc_lap_tay") or frappe.get_cached_value("Company", cd.cong_ty, "stock_received_but_not_billed")


def _gia_tri_dong(r) -> dict | None:
	"""Giá trị sổ của một dòng chiếu (đọc lại SAU khoá — không tin số đang lưu)."""
	if r.loai == "tra_truoc":
		return N.gia_tri_tra_truoc(r.phieu_chi)
	return N.gia_tri_pi(r.chung_tu) if r.chung_tu else None


def _khoa_dong(ten: str, ncc_doan: str | None):
	"""Khoá NCC (đoán ở bước chuẩn bị) + mọi dòng của NCC, rồi đọc dòng `ten` (có khoá). NCC của dòng khác NCC đoán (đổi giữa hai bước) → khoá thêm."""
	if ncc_doan:
		N.khoa_ncc(ncc_doan)
	r = frappe.db.sql(f"""SELECT `name`, `loai`, `nha_cung_cap`, `chung_tu`, `phieu_chi`, `so_tien`, `da_tra`, `trang_thai`, `han_thanh_toan`,
		`ghi_chu`, `so_hd_ncc`, `phieu_kho`, `tao_luc`, `qua_han_tay`, `tim_kd` FROM `tab{N.DT}` WHERE `name` = %s FOR UPDATE""", ten, as_dict=True)
	if r and r[0].nha_cung_cap != ncc_doan:
		N.khoa_ncc(r[0].nha_cung_cap)
	return r[0] if r else None


def _ve_ngay(v):
	return getdate(v) if v else None


# ================================================================================================ chứng từ lõi
def _tk_tien(method: str, cd) -> str:
	ht = cd.hinh_thuc[method]
	tk = frappe.db.get_value("Mode of Payment Account", {"parent": ht, "company": cd.cong_ty}, "default_account")
	if not tk:
		frappe.throw(f"Hình thức thanh toán {ht} chưa có tài khoản cho công ty {cd.cong_ty} (NPP Cai Dat)")
	return tk


def lap_pe(loai: str, ncc: str, tien, ngay, method: str, tham_chieu_pi: list[tuple[str, object]], ghi_chu: str | None, so_tham_chieu: str | None,
		cd, tk_no: str | None = None) -> str:
	"""Payment Entry Pay của NCC (`phieu_chi_ncc` → `PCNCC-`, `ghi_tra_ncc` → `GTN-`): tham chiếu PI = phần trừ nợ, phần dư = tiền trả trước
	(`unallocated_amount`). TK ngân hàng bắt số tham chiếu (`payment_entry.py:1412–1418`) → người không gõ thì tự điền tên phiếu (cổng không trả lên)."""
	from erpnext.accounts.party import get_party_account
	from frappe.model.naming import make_autoname

	tk_tien = _tk_tien(method, cd)
	ten = make_autoname("PCNCC-.####" if loai == "phieu_chi_ncc" else "GTN-.####", "Payment Entry")
	ngan_hang = frappe.get_cached_value("Account", tk_tien, "account_type") == "Bank"
	pe = frappe.new_doc("Payment Entry")
	pe.update({"naming_series": "PCNCC-.####" if loai == "phieu_chi_ncc" else "GTN-.####", "payment_type": "Pay", "company": cd.cong_ty,
		"posting_date": ngay, "mode_of_payment": cd.hinh_thuc[method], "party_type": "Supplier", "party": ncc, "paid_from": tk_tien,
		"paid_to": tk_no or get_party_account("Supplier", ncc, cd.cong_ty), "paid_amount": flt(tien), "received_amount": flt(tien),
		"source_exchange_rate": 1, "target_exchange_rate": 1, "reference_no": so_tham_chieu or (ten if ngan_hang else None),
		"reference_date": ngay, "npp_loai": loai, "npp_ghi_chu": ghi_chu})
	for pi, x in tham_chieu_pi:
		pe.append("references", {"reference_doctype": "Purchase Invoice", "reference_name": pi, "allocated_amount": flt(x)})
	pe.flags.ignore_permissions = True
	pe.insert(set_name=ten)
	pe.submit()  # hook sau_thanh_toan: chiếu các PI được trừ + dòng trả trước của chính phiếu
	frappe.local.message_log = []
	return pe.name


def _lap_bu_tru(r, tien: Decimal, ghi_chu: str | None, cd) -> str:
	"""Bù trừ (`offset`) = bút toán Debit Note `CTN-` (§7.3 điểm 10): Nợ phải trả tham chiếu khoản được trả / Có phải trả tham chiếu các phiếu trả NCC
	của chính NCC còn khoản giảm (cũ nhất trước). Trả tên dòng Nợ (= `payment_id`)."""
	giam = []
	for x in frappe.get_all(N.DT, filters={"nha_cung_cap": r.nha_cung_cap, "loai": "tra_ncc"}, fields=["name", "chung_tu", "tao_luc"]):
		gt = N.gia_tri_pi(x.chung_tu) if x.chung_tu else None
		if gt and flt(gt["con_no"]) < -0.005:
			giam.append((get_datetime(gt["tao_luc"]), x.chung_tu, _tien(-flt(gt["con_no"]))))
	giam.sort()
	phan = L.phan_bo_bu_tru(tien, [(t, x) for _l, t, x in giam])
	tk = frappe.db.get_value("Purchase Invoice", r.chung_tu, "credit_to")
	cc = frappe.get_cached_value("Company", cd.cong_ty, "cost_center")
	je = frappe.new_doc("Journal Entry")
	je.update({"voucher_type": "Debit Note", "naming_series": "CTN-.####", "company": cd.cong_ty, "posting_date": getdate(nowdate()),
		"npp_loai": "bu_tru_ncc", "npp_phieu_nhap": r.chung_tu, "user_remark": ghi_chu})
	je.append("accounts", {"account": tk, "party_type": "Supplier", "party": r.nha_cung_cap, "debit_in_account_currency": flt(tien),
		"reference_type": "Purchase Invoice", "reference_name": r.chung_tu, "cost_center": cc})
	for t, x in phan:
		je.append("accounts", {"account": frappe.db.get_value("Purchase Invoice", t, "credit_to"), "party_type": "Supplier",
			"party": r.nha_cung_cap, "credit_in_account_currency": flt(x), "reference_type": "Purchase Invoice", "reference_name": t,
			"cost_center": cc})
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()  # hook sau_but_toan: chiếu khoản được trả + các phiếu trả NCC
	frappe.local.message_log = []
	return je.accounts[0].name


# ================================================================================================ record_payable_payment
def _chuan_bi_tra(p_payable_id=None, p_amount=None, p_method=None, p_notes=None):
	"""Trước khi khoá (cổng commit sau bước này): người gọi, cài đặt, NCC của dòng (đọc thường) — KHÔNG ném lỗi (lỗi ép kiểu báo ở thân hàm)."""
	hien_tai()
	cai_dat_kho()
	ten = _van_ban(p_payable_id)
	frappe.local._npp_tra_ncc = (ten, frappe.db.get_value(N.DT, ten, "nha_cung_cap") if ten else None)


@rpc("record_payable_payment", ghi=True, chuan_bi=_chuan_bi_tra)
def record_payable_payment(p_payable_id=None, p_amount=None, p_method=None, p_notes=None):
	nc = hien_tai()
	cd = cai_dat_kho()
	x = getattr(frappe.local, "_npp_tra_ncc", None)
	frappe.local._npp_tra_ncc = None
	ten = _uuid_pg(p_payable_id)  # PostgREST ép kiểu tham số trước thân hàm (22P02)
	tien = _so(p_amount)
	loi = K.loi_vai("record_payable_payment", nc.vai)
	if loi is not None:
		raise loi
	if tien is None or tien <= 0:
		raise NppLoi(L.BAD_AMOUNT_TRA)
	ncc = x[1] if x and x[0] == _van_ban(p_payable_id) else (frappe.db.get_value(N.DT, ten, "nha_cung_cap") if ten else None)
	r = _khoa_dong(ten, ncc) if ten else None
	if not r:
		raise NppLoi(L.PAYABLE_NOT_FOUND)
	if r.chung_tu:  # khoá cả PI nguồn (đặc tả §3.10 Frappe bước 1) — xếp hàng với Huỷ phiếu nhập (khoá PI rồi kiểm DA_TRA_TIEN)
		frappe.db.sql("SELECT `name` FROM `tabPurchase Invoice` WHERE `name` = %s FOR UPDATE", r.chung_tu)
	gt = _gia_tri_dong(r)
	con = _tien(gt["con_no"]) if gt else Decimal(0)
	if tien > con:
		raise L.loi_overpay(con)
	method = L.hinh_thuc_ghi_tra(p_method)  # CHECK của payable_payments — kiểm SAU OVERPAY như nppsale (lúc INSERT)
	ghi_chu = L.nullif_rong(p_notes)
	if method == "offset":
		ma = _lap_bu_tru(r, tien, ghi_chu, cd)
	else:
		pe = lap_pe("ghi_tra_ncc", r.nha_cung_cap, tien, getdate(nowdate()), method, [(r.chung_tu, tien)], ghi_chu, None, cd,
			tk_no=frappe.db.get_value("Purchase Invoice", r.chung_tu, "credit_to"))
		ma = frappe.db.get_value("Payment Entry Reference", {"parent": pe, "parenttype": "Payment Entry"}, "name")
	N.chieu_phieu_nhap(r.chung_tu)
	moi = N.gia_tri_pi(r.chung_tu) or {}
	da_tra, so_tien = _tien(moi.get("da_tra")), _tien(moi.get("so_tien"))
	return [{"payment_id": ma, "new_paid": _ra(da_tra), "new_status": "paid" if da_tra >= so_tien else "partial"}]


# ================================================================================================ chi_tra_ncc
def _chuan_bi_chi(p_supplier_id=None, p_amount=None, p_paid_date=None, p_method="cash", p_notes=None, p_reference=None):
	hien_tai()
	cai_dat_kho()


@rpc("chi_tra_ncc", ghi=True, chuan_bi=_chuan_bi_chi)
def chi_tra_ncc(p_supplier_id=None, p_amount=None, p_paid_date=None, p_method="cash", p_notes=None, p_reference=None):
	nc = hien_tai()
	cd = cai_dat_kho()
	tien = _so(p_amount)
	ngay_gui = _ngay_pg(_van_ban(p_paid_date)) if p_paid_date is not None else None
	loi = K.loi_vai("chi_tra_ncc", nc.vai)
	if loi is not None:
		raise loi
	if tien is None or tien <= 0:
		raise NppLoi(L.BAD_AMOUNT_CHI)
	method = L.kiem_hinh_thuc_chi(p_method)
	ncc = _van_ban(p_supplier_id) or ""
	if not frappe.db.sql("SELECT `name` FROM `tabSupplier` WHERE `name` = %s FOR UPDATE", ncc):  # khoá đầu tiên của thân hàm
		raise NppLoi(L.NCC_KHONG_HOP_LE)
	ngay = L.ngay_chi(ngay_gui, getdate(nowdate()))
	N.khoa_ncc(ncc)
	luc = K.luc_chi(ngay, now_datetime())
	ke = N.ke_hoach_don(ncc, L.PhieuChiCon(None, luc, tien))
	tham_chieu: dict[str, Decimal] = {}
	for pe_cu, pi, lay in ke:
		if pe_cu is None:
			tham_chieu[pi] = tham_chieu.get(pi, Decimal(0)) + lay
	ghi_chu = L.btrim(p_notes)
	pe = lap_pe("phieu_chi_ncc", ncc, tien, ngay, method, list(tham_chieu.items()), ghi_chu, L.btrim(p_reference), cd)
	cu = []
	for pe_cu, pi, lay in ke:  # phiếu chi khác còn tiền mà chi SỚM hơn: dồn trước (kế hoạch chung — `_don_tra_truoc_ncc` cuối hàm nppsale)
		if pe_cu is not None:
			N.ap_phan_bo(pe_cu, pi, lay, ncc)
			cu.append(pe_cu)
	for p in dict.fromkeys(cu):
		N.chieu_tra_truoc(p)
	da_tru = sum(tham_chieu.values(), Decimal(0))
	return {"id": pe, "code": pe, "so_tien": _ra(tien), "da_tru_no": _ra(da_tru), "tra_truoc": _ra(tien - da_tru), "so_khoan": len(tham_chieu)}


# ================================================================================================ huy_phieu_chi_ncc
def _chuan_bi_huy_chi(p_id=None, p_reason=None):
	hien_tai()
	cai_dat_kho()
	ten = _van_ban(p_id)
	frappe.local._npp_huy_chi = (ten, frappe.db.get_value("Payment Entry", ten, "party") if ten else None)


@rpc("huy_phieu_chi_ncc", ghi=True, chuan_bi=_chuan_bi_huy_chi)
def huy_phieu_chi_ncc(p_id=None, p_reason=None):
	nc = hien_tai()
	cai_dat_kho()
	ten = _van_ban(p_id)
	x = getattr(frappe.local, "_npp_huy_chi", None)
	frappe.local._npp_huy_chi = None
	ncc = x[1] if x and x[0] == ten else (frappe.db.get_value("Payment Entry", ten, "party") if ten else None)
	if ncc:
		N.khoa_ncc(ncc)  # câu ĐẦU của thân hàm là câu khoá — đọc thường trước khoá lập ảnh chụp cũ (PoC 1d)
	r = frappe.db.sql("""SELECT `name`, `docstatus`, `party_type`, `party`, `payment_type`, `npp_loai`, `paid_amount` FROM `tabPayment Entry`
		WHERE `name` = %s FOR UPDATE""", ten or "", as_dict=True)
	if not r or r[0].npp_loai != "phieu_chi_ncc" or r[0].party_type != "Supplier" or r[0].payment_type != "Pay" or r[0].docstatus == 0:
		raise NppLoi(L.PHIEU_CHI_KHONG_TON_TAI)
	r = r[0]
	loi = K.loi_vai("huy_phieu_chi_ncc", nc.vai)  # nppsale kiểm SAU tồn tại + NPP
	if loi is not None:
		raise loi
	if r.docstatus == 2:
		return {"id": r.name, "code": r.name, "da_huy": False, "so_tien_go": 0}  # IDEMPOTENT — bấm hai lần không gỡ tiền hai lần
	if r.party != ncc:
		N.khoa_ncc(r.party)
	# tiền phiếu chi đã chuyển dư vào phiếu nhập sau một lần sửa (bút toán `chuyen_tra_du_ncc` — M7): huỷ trước (bút toán trỏ phiếu chi chặn huỷ PE),
	# khoản ấy tăng nợ lại như mọi dòng tiền của phiếu chi bị gỡ (nppsale xoá dòng `payable_payments` của phiếu chi)
	du = N.je_chuyen_tra_du(pe=r.name)
	pi_du = [a.reference_name for je in du for a in frappe.get_doc("Journal Entry", je).accounts if a.reference_type == "Purchase Invoice"]
	N.huy_chuyen_tra_du(du)
	pe = frappe.get_doc("Payment Entry", r.name)
	pi = [d.reference_name for d in pe.references if d.reference_doctype == "Purchase Invoice"] + pi_du
	pe.update({"npp_ly_do_huy": L.btrim(p_reason), "npp_huy_luc": now_datetime(), "npp_huy_boi": _nv(nc)})
	pe.flags.ignore_permissions = True
	pe.cancel()  # lõi gỡ mọi phân bổ (Payment Ledger delinked); hook chiếu lại các khoản + xoá dòng trả trước
	frappe.local.message_log = []
	for x in dict.fromkeys(pi):
		N.chieu_phieu_nhap(x)
	N.chieu_tra_truoc(r.name)
	N.don_tra_truoc_ncc(r.party)  # khoản vừa mở lại: tiền trả trước của các phiếu chi KHÁC dồn vào
	return {"id": r.name, "code": r.name, "da_huy": True, "so_tien_go": _ra(r.paid_amount)}


# ================================================================================================ RPC đọc
def _doc(nc, bang: str, select: str, loc: list | None = None) -> list[dict]:
	from nppsale.cong.truy_van import doc

	return doc({"bang": bang, "select": select, "loc": loc or []}, nc)["data"] or []


def _d(v) -> Decimal:
	return Decimal(str(v)) if v is not None else Decimal(0)


@rpc("payables_summary", ghi=False)
def payables_summary(p_since=None):
	"""mig 093 → 231 (SQL STABLE, INVOKER): `open_payables` = Σ(amount − paid) dòng chưa `paid` — KHÔNG kẹp (dòng âm, dòng trả trước trừ vào);
	`month_total` = Σ amount dòng gắn phiếu kho có ngày ghi nợ ≥ `p_since` (chuỗi không múi giờ hiểu theo giờ VN của site — §7.3 điểm 24). RLS: vai
	ngoài chủ / quản lý / kế toán → [{0, 0}]."""
	nc = hien_tai()
	tu = get_datetime(gio_vao(_van_ban(p_since))) if p_since not in (None, "") else None
	mo, thang = Decimal(0), Decimal(0)
	for r in _doc(nc, "payables", "amount, paid, status, stock_entry_id, created_at"):
		if r["status"] != "paid":
			mo += _d(r["amount"]) - _d(r["paid"])
		if r["stock_entry_id"] and tu is not None and r["created_at"] and get_datetime(gio_vao(r["created_at"])) >= tu:
			thang += _d(r["amount"])
	return [{"open_payables": _ra(mo), "month_total": _ra(thang)}]


@rpc("payables_by_supplier", ghi=False)
def payables_by_supplier():
	"""mig 093 → 239 (SQL STABLE, INVOKER): dòng chưa `paid` gom theo NCC — số dòng (cả dòng âm, dòng trả trước), Σ số nợ, Σ đã trả, còn lại (không
	kẹp), số dòng quá hạn (dấu `overdue`), hàng trả lại = Σ(−số nợ) các dòng của phiếu trả NCC; xếp còn lại giảm dần."""
	nc = hien_tai()
	ds = _doc(nc, "payables", "id, supplier_id, amount, paid, status", [{"op": "neq", "cot": "status", "gt": "paid"}])
	if not ds:
		return []
	tra = set(frappe.get_all(N.DT, filters={"name": ("in", [r["id"] for r in ds]), "loai": "tra_ncc"}, pluck="name"))
	gom: dict = {}
	for r in ds:
		g = gom.setdefault(r["supplier_id"], {"n": 0, "no": Decimal(0), "tra": Decimal(0), "qh": 0, "lai": Decimal(0)})
		a, p = _d(r["amount"]), _d(r["paid"])
		g["n"] += 1
		g["no"] += a
		g["tra"] += p
		g["qh"] += 1 if r["status"] == "overdue" else 0
		if r["id"] in tra:
			g["lai"] -= a
	ncc = {r["id"]: r for r in _doc(nc, "suppliers", "id, name, code", [{"op": "in", "cot": "id", "gt": list(gom)}])}
	ra = []
	for k, g in gom.items():
		s = ncc.get(k) or {}
		ra.append({"supplier_id": k, "supplier_name": s.get("name") if s.get("name") is not None else "-",
			"supplier_code": s.get("code") if s.get("code") is not None else "-", "invoice_count": g["n"], "total_debt": _ra(g["no"]),
			"total_paid": _ra(g["tra"]), "remaining": _ra(g["no"] - g["tra"]), "overdue_count": g["qh"], "total_returned": _ra(g["lai"])})
	ra.sort(key=lambda x: -Decimal(str(x["remaining"])))
	return ra


# ================================================================================================ cổng payables — THÊM
def _cot_la(gt: dict, cot=COT_NO, bang: str = BANG) -> None:
	for k in gt:
		if k not in cot:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{bang}' in the schema cache", http=400)


def _so_cot(v, cot: str) -> Decimal | None:
	if v is None:
		return None
	if isinstance(v, bool):
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{str(v).lower()}"')
	return _so(v)


def _loai_phieu_kho(ten: str | None) -> str | None:
	"""Nguồn id của cổng `stock_entries` (M4): Stock Entry (`IN-`…) hay PI (phiếu kho của phiếu nhập / trả NCC = chính tờ — ⚠K §7.2 #14)."""
	if not ten:
		return None
	if frappe.db.exists("Stock Entry", ten):
		return "Stock Entry"
	if frappe.db.exists("Purchase Invoice", ten):
		return "Purchase Invoice"
	raise LoiCong("23503", f'insert or update on table "{BANG}" violates foreign key constraint "payables_stock_entry_id_fkey"',
		chi_tiet=f'Key (stock_entry_id)=({ten}) is not present in table "stock_entries".', http=409)


def lap_no(loai: str, ncc: str, so, so_hd, han, ghi_chu, qua_han: bool, phieu_kho, cd, *, amend_tu: str | None = None, posting=None,
		luc=None) -> str:
	"""Tờ nợ NCC không kho (như tờ `DK-` của nợ đầu kỳ khách): một dòng không mã hàng — nợ đầu kỳ `DKN-` (`is_opening`, TK tạm đầu kỳ), nợ lập tay
	`NTN-` (TK `tk_no_ncc_lap_tay`). Lúc ghi nợ (`npp_hoan_thanh_luc` — `payables.created_at`, khoá thứ tự dồn) = bây giờ (amend: giữ của tờ gốc)."""
	tk = cd.tk_tam_dau_ky if loai == "dau_ky" else tk_no_lap_tay(cd)
	if not tk:
		frappe.throw("Chưa có TK cho nợ NCC (NPP Cai Dat.tk_tam_dau_ky / tk_no_ncc_lap_tay)")
	ngay = getdate(posting or nowdate())
	han = _ve_ngay(han)
	pi = frappe.new_doc("Purchase Invoice")
	pi.update({
		"naming_series": DAY_SO[loai], "supplier": ncc, "company": cd.cong_ty, "is_opening": "Yes" if loai == "dau_ky" else "No",
		"posting_date": ngay, "set_posting_time": 1, "due_date": max(ngay, han) if han else ngay, "bill_no": so_hd, "update_stock": 0,
		"is_return": 0, "disable_rounded_total": 1, "allocate_advances_automatically": 0, "taxes_and_charges": "", "npp_loai": loai,
		"npp_han_thanh_toan": han, "npp_ghi_chu_no": ghi_chu, "npp_qua_han_tay": 1 if qua_han else 0, "npp_hoan_thanh_luc": luc or now_datetime(),
		"npp_phieu_kho_loai": _loai_phieu_kho(phieu_kho), "npp_phieu_kho": phieu_kho or None,
		"items": [{"item_name": TEN_DONG[loai], "description": TEN_DONG[loai], "qty": 1, "rate": flt(so), "conversion_factor": 1,
			"uom": frappe.db.get_single_value("Stock Settings", "stock_uom") or "Nos", "expense_account": tk,
			"cost_center": frappe.get_cached_value("Company", cd.cong_ty, "cost_center")}],
	})
	if amend_tu:
		pi.amended_from = amend_tu
	pi.set("taxes", [])
	pi.flags.ignore_permissions = True
	pi.insert()
	return pi.name


def _ghi_so(ten: str) -> None:
	pi = frappe.get_doc("Purchase Invoice", ten)
	pi.flags.ignore_permissions = True
	pi.submit()  # hook: chiếu dòng công nợ NCC
	frappe.local.message_log = []


def them_no(ds: list[dict], nc) -> list[str]:
	"""INSERT nhiều dòng = một câu Postgres: hỏng một dòng là hỏng cả lệnh (cổng lui savepoint)."""
	cd = cai_dat_kho()
	ra = []
	for g in ds:
		g = g or {}
		_cot_la(g)
		# PostgREST dựng dòng từ JSON (json_populate_recordset) TRƯỚC mọi trigger / RLS: sai kiểu → 22P02 / 22007 / 22008
		paid, so = _so_cot(g.get("paid"), "paid"), _so_cot(g.get("amount"), "amount")
		dau_ky = _bool_pg(g.get("opening_balance"))
		han = _ngay_pg(_van_ban(g["due_date"])) if g.get("due_date") not in (None, "") else None
		# trigger `_khoa_ghi_thang_no_ncc` (BEFORE INSERT — trước RLS)
		if (paid or 0) != 0 or (g.get("status") or "open") not in ("open", "overdue"):
			raise NppLoi(L.KHOA_THEM)
		if not nc.bo_qua_rls and (nc.vai not in K.VAI_TIEN_NCC or g.get("org_id") not in (None, _org())):
			tu_choi(BANG)
		for cot in ("supplier_id", "amount"):
			if g.get(cot) is None:
				raise LoiCong("23502", f'null value in column "{cot}" of relation "{BANG}" violates not-null constraint', http=400)
		if so <= 0:  # ⚠K §4.4 (đề xuất): tờ nợ không âm / không 0 — nppsale trigger không chặn
			raise NppLoi(L.KHOA_THEM)
		ncc = str(g.get("supplier_id"))
		if not frappe.db.exists("Supplier", ncc):
			raise LoiCong("23503", f'insert or update on table "{BANG}" violates foreign key constraint "payables_supplier_id_fkey"',
				chi_tiet=f'Key (supplier_id)=({ncc}) is not present in table "suppliers".', http=409)
		N.khoa_ncc(ncc)
		if dau_ky and frappe.db.sql(f"SELECT `name` FROM `tab{N.DT}` WHERE `nha_cung_cap` = %s AND `loai` = 'dau_ky' FOR UPDATE", ncc):
			raise LoiCong("23505", 'duplicate key value violates unique constraint "uq_payables_opening"',
				chi_tiet=f"Key (org_id, supplier_id)=({_org()}, {ncc}) already exists.", http=409)
		pi = lap_no("dau_ky" if dau_ky else "lap_tay", ncc, so, _van_ban(g.get("invoice_number")) or None, han, _van_ban(g.get("notes")),
			g.get("status") == "overdue", _van_ban(g.get("stock_entry_id")) or None, cd)
		_ghi_so(pi)
		N.don_tra_truoc_ncc(ncc)  # trigger `trg_tra_truoc_vao_no_moi` (mig 242): khoản dương mới ăn tiền trả trước còn
		ten = frappe.db.get_value(N.DT, {"khoa_nguon": f"Purchase Invoice:{pi}"}, "name")
		if ten:
			ra.append(ten)
	return ra


# ================================================================================================ cổng payables — SỬA
def _hien_tai(r) -> dict:
	return {"id": r.name, "org_id": _org(), "supplier_id": r.nha_cung_cap, "stock_entry_id": r.phieu_kho, "invoice_number": r.so_hd_ncc,
		"amount": r.so_tien, "paid": r.da_tra, "due_date": r.han_thanh_toan, "status": r.trang_thai, "notes": r.ghi_chu, "created_at": r.tao_luc,
		"opening_balance": r.loai == "dau_ky", "tim_kd": r.tim_kd}


def _khac(cot: str, moi, cu) -> bool:
	"""IS DISTINCT FROM theo kiểu cột của Postgres."""
	if moi is None or cu is None:
		return (moi is None) != (cu is None)
	if cot in ("amount", "paid"):
		return _so_cot(moi, cot) != _tien(cu)
	if cot == "due_date":
		return _ngay_pg(_van_ban(moi)) != getdate(cu)
	if cot == "created_at":
		return get_datetime(gio_vao(moi)) != get_datetime(cu)
	if cot == "opening_balance":
		return bool(_bool_pg(moi)) != bool(cu)
	return str(moi) != str(cu)


def _ep_kieu(gt: dict) -> None:
	"""Giá trị SET của PATCH được ép kiểu một lần (json_populate_record) trước khi lọc dòng — sai kiểu báo lỗi kể cả khi không dòng nào khớp."""
	for k, v in gt.items():
		if v is None:
			continue
		if k in ("amount", "paid"):
			_so_cot(v, k)
		elif k == "due_date":
			_ngay_pg(_van_ban(v))
		elif k == "opening_balance":
			_bool_pg(v)


def sua_no(gt: dict, ids: list[str], nc) -> list[str]:
	_cot_la(gt)
	_ep_kieu(gt)
	if not nc.bo_qua_rls and nc.vai not in K.VAI_TIEN_NCC:
		return []  # RLS UPDATE: 0 dòng, không lỗi
	cd = cai_dat_kho()
	ra = []
	for ten in ids:
		ncc = frappe.db.get_value(N.DT, ten, "nha_cung_cap")
		r = _khoa_dong(ten, ncc) if ncc else None
		if not r:
			continue
		cu = _hien_tai(r)
		doi = {k for k, v in gt.items() if k != "status" and _khac(k, v, cu[k])}
		# trigger `_khoa_ghi_thang_no_ncc` (BEFORE UPDATE)
		if doi & {"paid", "supplier_id", "org_id", "stock_entry_id", "opening_balance", "created_at", "id"} or (
				"amount" in doi and (r.loai != "dau_ky" or r.phieu_kho)):
			raise NppLoi(L.KHOA_SUA)
		amount_moi = _so_cot(gt["amount"], "amount") if "amount" in doi else _tien(r.so_tien)
		doi_tt = "status" in gt and gt["status"] != r.trang_thai
		if doi_tt and not L.trang_thai_khop(gt["status"], r.da_tra, amount_moi):
			raise L.loi_trang_thai(gt["status"], r.da_tra, gt["amount"] if "amount" in doi else r.so_tien)
		if r.loai == "tra_truoc" and (doi or doi_tt):
			raise NppLoi(L.KHOA_SUA)  # ⚠K: dòng trả trước là dòng hệ thống của phiếu chi — không có chứng từ để giữ số HĐ / hạn / ghi chú / trạng thái
		if "amount" in doi and (abs(flt(r.da_tra)) >= 0.005 or amount_moi <= 0):
			raise NppLoi(L.KHOA_SUA)  # ⚠K: nppsale cho sửa số đầu kỳ đã trả (`trangThaiSauSuaSoTien`) — tờ amend không mang được tiền đã trả
		qua_han = (1 if gt["status"] == "overdue" else 0) if doi_tt else cint(r.qua_han_tay)
		goc = frappe.db.get_value("Purchase Invoice", r.chung_tu, ["bill_no", "npp_han_thanh_toan", "npp_ghi_chu_no"], as_dict=True) if (
			r.chung_tu) else frappe._dict()
		so_hd = _van_ban(gt["invoice_number"]) if "invoice_number" in doi else goc.get("bill_no")
		han = (_ngay_pg(_van_ban(gt["due_date"])) if gt["due_date"] is not None else None) if "due_date" in doi else goc.get("npp_han_thanh_toan")
		# ghi chú xoá = chuỗi rỗng (NULL = chữ hệ thống của bản chiếu — Q9 §7.3 điểm 14)
		ghi_chu = (gt["notes"] if gt["notes"] is not None else "") if "notes" in doi else goc.get("npp_ghi_chu_no")
		if "amount" in doi:
			_lam_lai_dkn(r, amount_moi, so_hd, han, ghi_chu, qua_han, cd)
		elif r.chung_tu:
			moi = {}
			if "invoice_number" in doi:
				moi["bill_no"] = so_hd
			if "due_date" in doi:
				moi["npp_han_thanh_toan"] = han
			if "notes" in doi:
				moi["npp_ghi_chu_no"] = ghi_chu
			if doi_tt:
				moi["npp_qua_han_tay"] = qua_han
			if moi:
				frappe.db.set_value("Purchase Invoice", r.chung_tu, moi, update_modified=False)
			N.chieu_phieu_nhap(r.chung_tu)
		ra.append(ten)
	return ra


def _lam_lai_dkn(r, so_moi: Decimal, so_hd, han, ghi_chu, qua_han: int, cd) -> str:
	"""Số nợ đầu kỳ mới (chưa trả): huỷ + amend `DKN-…-n` — giữ TÊN dòng chiếu (link /payables/<id>), ngày ghi sổ + lúc ghi nợ gốc, rồi gọi dồn trả
	trước (§7.3 điểm 27: tờ amend là tờ mới ghi sổ; nợ ròng không đổi — chỉ khác phân bổ)."""
	cu = frappe.get_doc("Purchase Invoice", r.chung_tu)
	# lõi chỉ cho amend tờ ĐÃ huỷ → đổi khoá dòng chiếu sang khoá tạm trước khi huỷ (hook huỷ không xoá dòng), lập tờ mới rồi trỏ khoá vào
	frappe.db.set_value(N.DT, r.name, "khoa_nguon", f"Purchase Invoice:{cu.name}:lam_lai", update_modified=False)
	cu.flags.ignore_permissions = True
	cu.cancel()
	frappe.local.message_log = []
	moi = lap_no("dau_ky", cu.supplier, so_moi, so_hd, han, ghi_chu, bool(qua_han), None, cd, amend_tu=cu.name, posting=cu.posting_date,
		luc=cu.npp_hoan_thanh_luc)
	frappe.db.set_value(N.DT, r.name, {"khoa_nguon": f"Purchase Invoice:{moi}", "chung_tu": moi}, update_modified=False)
	_ghi_so(moi)
	N.don_tra_truoc_ncc(cu.supplier)
	return moi


# ================================================================================================ cổng payables — XOÁ
def _co_dong_tien(ten: str) -> bool:
	from nppsale.cong.bang.cong_no_ncc import NGUON_TRA_NO

	return bool(frappe.db.sql(f"SELECT 1 FROM {NGUON_TRA_NO} x WHERE x.`payable_id` = %s LIMIT 1", ten))


def xoa_no(ids: list[str], nc) -> list[str]:
	if not nc.bo_qua_rls and nc.vai not in K.VAI_TIEN_NCC:
		return []  # RLS DELETE: 0 dòng, không lỗi
	ra = []
	for ten in ids:
		ncc = frappe.db.get_value(N.DT, ten, "nha_cung_cap")
		r = _khoa_dong(ten, ncc) if ncc else None
		if not r:
			continue
		# trigger BEFORE DELETE (`paid ≠ 0 OR EXISTS payable_payments`); đã trả của bản chiếu tính từ sổ nên khoản có dòng tiền đã có đã trả ≠ 0 —
		# vế thứ hai chỉ giữ cho khớp trigger (thử phá: bỏ vế này không bài nào đỏ — tương đương)
		if abs(flt(r.da_tra)) >= 0.005 or _co_dong_tien(ten):
			raise NppLoi(L.KHOA_XOA)
		loi = L.loi_fk_xoa(r.loai, r.name)  # khoá ngoại NO ACTION của phiếu nhập / phiếu trả NCC (§7.3 điểm 38)
		if loi is not None:
			raise loi
		if r.chung_tu and frappe.db.get_value("Purchase Invoice", r.chung_tu, "docstatus") == 1:
			pi = frappe.get_doc("Purchase Invoice", r.chung_tu)
			pi.flags.ignore_permissions = True
			pi.cancel()  # hook xoá dòng chiếu
			frappe.local.message_log = []
		frappe.db.delete(N.DT, {"name": ten})
		ra.append(ten)
	return ra


# ================================================================================================ cổng payable_payments
def them_tra(ds: list[dict], nc) -> list[str]:
	for g in ds:
		_cot_la(g or {}, COT_TRA, "payable_payments")
	raise NppLoi(L.CHI_NCC_KHOA)  # trigger BEFORE INSERT chạy trước RLS — mọi vai


def xoa_tra(ids: list[str], nc) -> list[str]:
	if ids and (nc.bo_qua_rls or nc.vai in K.VAI_TIEN_NCC):
		raise NppLoi(L.CHI_NCC_KHOA)
	return []


def _dong_tra(ten: str) -> tuple[str, str] | None:
	"""Chứng từ giữ dấu xác nhận của một dòng `payable_payments`: dòng tham chiếu Payment Entry / dòng bút toán / phiếu chi (dòng `::tra_truoc` —
	dấu cấp phiếu, dồn về sau chép sang tham chiếu mới như mig 242)."""
	if ten.endswith("::tra_truoc"):
		return ("Payment Entry", ten[: -len("::tra_truoc")])
	if frappe.db.exists("Payment Entry Reference", ten):
		return ("Payment Entry Reference", ten)
	if frappe.db.exists("Journal Entry Account", ten):
		return ("Journal Entry Account", ten)
	return None


def xac_nhan_tra(gt: dict, ids: list[str], nc) -> list[str]:
	"""Chỉ đổi `verified_by` / `verified_at` (trigger `_khoa_ghi_thang_chi_ncc` so mọi cột còn lại — gửi lại đúng giá trị cũ không lỗi)."""
	from nppsale.cong.dang_ky import NguCanh
	from nppsale.cong.truy_van import doc

	_cot_la(gt, COT_TRA, "payable_payments")
	if not nc.bo_qua_rls and nc.vai not in K.VAI_TIEN_NCC:
		return []
	ra = []
	cot = [k for k in gt if k not in ("verified_by", "verified_at")]
	for ten in ids:
		cu = doc({"bang": "payable_payments", "select": ", ".join(["id", *cot]), "loc": [{"op": "eq", "cot": "id", "gt": ten}]},
			NguCanh(user="Administrator", vai=None, bo_qua_rls=True))["data"]
		cu = cu[0] if cu else {}
		for k in cot:
			moi, cu_k = gt[k], cu.get(k)
			khac = (moi is None) != (cu_k is None) if moi is None or cu_k is None else (
				_so_cot(moi, k) != Decimal(str(cu_k)) if k == "amount" else
				get_datetime(gio_vao(moi)) != get_datetime(gio_vao(cu_k)) if k == "paid_at" else str(moi) != str(cu_k))
			if khac:
				raise NppLoi(L.CHI_NCC_KHOA)
		dich = _dong_tra(ten)
		if not dich:
			continue
		moi = {}
		if "verified_by" in gt:
			if gt["verified_by"] is not None and not frappe.db.exists("NPP Nhan Vien", gt["verified_by"]):
				raise LoiCong("23503", 'insert or update on table "payable_payments" violates foreign key constraint '
					'"payable_payments_verified_by_fkey"', http=409)
			moi["npp_xac_nhan_boi"] = gt["verified_by"]
		if "verified_at" in gt:
			moi["npp_xac_nhan_luc"] = gio_vao(gt["verified_at"])
		if moi:
			frappe.db.set_value(dich[0], dich[1], moi, update_modified=False)
		ra.append(ten)
	return ra
