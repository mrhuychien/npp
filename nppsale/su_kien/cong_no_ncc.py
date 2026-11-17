"""Công nợ NCC = bản chiếu thuần từ sổ + dồn trả trước NCC (đặc tả kho_mua §2.8; blueprint 02 §4.3.0 / §4.4 `NPP Cong No NCC`; quyết định Q2;
nppsale mig 102 / 227 / 231 / 239 / 242). Khuôn: bản chiếu công nợ KHÁCH `nppsale.su_kien.cong_no`.

`NPP Cong No NCC` = bảng `payables` của nppsale; KHÔNG ai ghi ngoài hàm chiếu. Mỗi dòng một "nhóm chứng từ sổ":
- Purchase Invoice docstatus 1 (mọi `npp_loai`: phiếu nhập `PN-`, trả NCC `PTNCC-`, nợ đầu kỳ `DKN-`, nợ lập tay `NTN-`) — khoá `Purchase Invoice:<tên>`;
  PI huỷ → xoá dòng (nppsale xoá `payables` khi huỷ phiếu — không có trạng thái `cancelled`).
- Payment Entry (Pay) `npp_loai = phieu_chi_ncc` docstatus 1 còn tiền chưa phân bổ — dòng TRẢ TRƯỚC (`chi_tra_ncc` mig 242: dòng `amount 0`, `paid` = phần
  chưa dồn) — khoá `Payment Entry:<tên>`; hết tiền → xoá dòng (nppsale xoá dòng trả trước rỗng → `supplier_payments.prepay_payable_id` NULL).
  so_tien = PI: `grand_total` (trả NCC âm) + Σ chênh bút toán sửa giá `DCN-` (`npp_loai = dieu_chinh_gia_nhap`) của phiếu; trả trước: 0
  con_no  = Σ Payment Ledger Entry.amount (`delinked = 0`) trỏ chứng từ (phải trả = Có − Nợ; âm = NCC nợ lại mình / tiền trả trước còn)
  da_tra  = so_tien − con_no;  trang_thai — MỘT luật với phải thu (`_cong_no_am_trang_thai` mig 212 — `cong_no.trang_thai`; ⚠K §7.3 điểm 13:
  nppsale ghi `partial` cho trả dư sau sửa phiếu và các RPC thanh toán ghi đè `overdue`; ở đây trả dư là `open`, dấu quá hạn tay giữ tới khi đủ)
Ghi chú dòng (§7.3 điểm 14 — quyết định tạm Q9): `npp_ghi_chu_no` của PI (màn công nợ NCC sửa riêng); trống (NULL) → chữ hệ thống như nppsale
("Phiếu nhập hàng <PN>" — `complete_purchase_invoice`; "Hoàn trả NCC — phiếu <PTNCC>" — `complete_supplier_return`); dòng trả trước: "Trả trước
NCC — phiếu chi <PE>" (`chi_tra_ncc`). Ngày ghi nợ `tao_luc`: PI `npp_hoan_thanh_luc` (method đặt lúc ghi sổ / chép của tờ gốc khi khôi phục /
sửa) → trống thì `creation`; trả trước: lúc chi (luật `v_luc` — `nppsale.luat.kho_mua.luc_chi`).

Ai gọi: doc_events Purchase Invoice (`on_submit`, `on_cancel`, `on_update_after_submit`), Payment Entry / Journal Entry (vế Supplier — cùng chỗ với
nhánh khách ở `cong_no.sau_thanh_toan` / `sau_but_toan`), `don_tra_truoc_ncc` sau mỗi lần `reconcile_against_document` (lõi đổi tham chiếu PE không
qua `on_submit`), việc đêm `nppsale.kham_so.kham_so_cong_no_ncc`.

`don_tra_truoc_ncc(ncc)` thay trigger `_trg_tra_truoc_vao_no_moi` + `_don_tra_truoc_ncc` (mig 242): METHOD gọi tường minh ở đúng chỗ nppsale dồn — sau
mọi PI dương ghi sổ (PN — kể cả từ `post_stock_import`, khôi phục, amend của sửa SAU khi đã phân bổ lại tiền cũ; DKN; NTN), sau huỷ PN
(`cancel_purchase_invoice`), huỷ phiếu chi (`huy_phieu_chi_ncc`), `chi_tra_ncc`. KHÔNG gọi từ doc_events: thứ tự với phân bổ lại tiền của sửa / huỷ
PN do method quyết (hook dồn ngay lúc huỷ tờ cũ là đẩy tiền phiếu chi sang khoản khác trước khi tờ amend nhận lại). Không gọi (như nppsale): gộp NCC,
`sua_phieu_nhap` tăng nợ tại chỗ (nhánh giá), Ghi trả.
"""
from __future__ import annotations

from decimal import Decimal

import frappe
from frappe.utils import flt, get_datetime, now_datetime

from nppsale.luat.cong_no_ncc import KhoanNo, PhieuChiCon, phan_bo_tra_truoc
from nppsale.luat.kho_mua import luc_chi
from nppsale.luat.tim import khoa_tim_ds
from nppsale.su_kien.cong_no import _con_no, trang_thai

DT = "NPP Cong No NCC"
LOAI_PI = ("phieu_nhap", "tra_ncc", "dau_ky", "lap_tay")
TIEN_TO = (("PTNCC-", "tra_ncc"), ("DKN-", "dau_ky"), ("NTN-", "lap_tay"), ("PN-", "phieu_nhap"))
GHI_CHU_HE_THONG = {"phieu_nhap": "Phiếu nhập hàng {ten}", "tra_ncc": "Hoàn trả NCC — phiếu {ten}",
	"tra_truoc": "Trả trước NCC — phiếu chi {ten}"}
_TRUONG_PI = ("name", "docstatus", "is_return", "is_opening", "supplier", "supplier_name", "grand_total", "bill_no", "creation", "npp_loai",
	"npp_han_thanh_toan", "npp_qua_han_tay", "npp_ghi_chu_no", "npp_hoan_thanh_luc", "npp_phieu_kho")


def loai_cua_pi(npp_loai: str | None, ten: str, is_return=0, is_opening=None) -> str:
	"""Loại khoản của một PI: `npp_loai` của app; tờ lập ngoài app (Desk) → theo tiền tố tên, rồi `is_return` / `is_opening` — để Σ dòng chiếu của
	NCC vẫn bằng sổ (khám sổ nhóm 20)."""
	if npp_loai in LOAI_PI:
		return npp_loai
	for tien_to, loai in TIEN_TO:
		if (ten or "").startswith(tien_to):
			return loai
	if is_return:
		return "tra_ncc"
	return "dau_ky" if is_opening == "Yes" else "phieu_nhap"


def ghi_chu_he_thong(loai: str, ten: str) -> str | None:
	m = GHI_CHU_HE_THONG.get(loai)
	return m.format(ten=ten) if m else None


def _truong_pi() -> list[str]:
	meta = frappe.get_meta("Purchase Invoice")
	return [f for f in _TRUONG_PI if f in ("name", "docstatus", "creation") or meta.has_field(f)]


def _chenh_dcn(pi: str) -> float:
	"""Σ chênh nợ của bút toán sửa giá phiếu đã bán `DCN-` (§3.3 nhánh B — `sua_phieu_nhap` nppsale sửa thẳng `payables.amount`): Có − Nợ của vế
	Supplier tham chiếu phiếu."""
	if not frappe.get_meta("Journal Entry").has_field("npp_loai"):
		return 0.0
	return flt(frappe.db.sql("""SELECT COALESCE(SUM(a.`credit_in_account_currency` - a.`debit_in_account_currency`), 0)
		FROM `tabJournal Entry` j JOIN `tabJournal Entry Account` a ON a.`parent` = j.`name` AND a.`parenttype` = 'Journal Entry'
		WHERE j.`docstatus` = 1 AND j.`npp_loai` = 'dieu_chinh_gia_nhap' AND a.`party_type` = 'Supplier'
			AND a.`reference_type` = 'Purchase Invoice' AND a.`reference_name` = %s""", pi)[0][0])


def gia_tri_pi(ten: str) -> dict | None:
	"""Giá trị dòng chiếu của một Purchase Invoice (đọc thẳng sổ, không ghi); None = không được có dòng (không có / chưa / thôi ghi sổ)."""
	pi = frappe.db.get_value("Purchase Invoice", ten, _truong_pi(), as_dict=True)
	if not pi or pi.docstatus != 1:
		return None
	loai = loai_cua_pi(pi.get("npp_loai"), pi.name, pi.is_return, pi.get("is_opening"))
	so_tien = flt(pi.grand_total) + _chenh_dcn(pi.name)
	con_no = _con_no([pi.name], "Purchase Invoice")
	da_tra = so_tien - con_no
	qua_han = bool(pi.get("npp_qua_han_tay"))
	# PTNCC chưa sửa số HĐ ở màn công nợ → mã phiếu (nppsale ghi return_code vào invoice_number — mig 228 / 240)
	so_hd = pi.bill_no or (pi.name if loai == "tra_ncc" else None)
	ghi_chu = pi.get("npp_ghi_chu_no")
	return {
		"loai": loai, "nha_cung_cap": pi.supplier, "ten_ncc": pi.supplier_name, "chung_tu": pi.name, "phieu_chi": None,
		"khoa_cho": f"dau_ky:{pi.supplier}" if pi.get("npp_loai") == "dau_ky" else None,
		"so_hd_ncc": so_hd, "tim_kd": khoa_tim_ds(so_hd or ""),
		"phieu_kho": pi.name if loai in ("phieu_nhap", "tra_ncc") else (pi.get("npp_phieu_kho") or None),
		"so_tien": so_tien, "da_tra": da_tra, "con_no": con_no, "han_thanh_toan": pi.get("npp_han_thanh_toan"),
		"trang_thai": trang_thai(so_tien, da_tra, qua_han), "qua_han_tay": 1 if qua_han else 0,
		"ghi_chu": ghi_chu if ghi_chu is not None else ghi_chu_he_thong(loai, pi.name),
		"tao_luc": pi.get("npp_hoan_thanh_luc") or pi.creation,
	}


def gia_tri_tra_truoc(pe: str | None) -> dict | None:
	"""Giá trị dòng TRẢ TRƯỚC của một phiếu chi NCC; None = không có dòng (không phải phiếu chi NCC đang ghi sổ, hoặc đã dồn hết tiền)."""
	if not pe:
		return None
	x = frappe.db.get_value("Payment Entry", pe, ["name", "docstatus", "party_type", "party", "party_name", "posting_date", "creation",
		"npp_loai"], as_dict=True) if frappe.get_meta("Payment Entry").has_field("npp_loai") else None
	if not x or x.docstatus != 1 or x.party_type != "Supplier" or x.npp_loai != "phieu_chi_ncc":
		return None
	con_no = _con_no([pe], "Payment Entry")  # âm = tiền còn chưa phân bổ
	if abs(con_no) < 0.005:
		return None
	return {
		"loai": "tra_truoc", "nha_cung_cap": x.party, "ten_ncc": x.party_name, "chung_tu": None, "phieu_chi": pe, "khoa_cho": None,
		"so_hd_ncc": pe, "tim_kd": khoa_tim_ds(pe), "phieu_kho": None, "so_tien": 0.0, "da_tra": -con_no, "con_no": con_no,
		"han_thanh_toan": None, "trang_thai": trang_thai(0.0, -con_no, False), "qua_han_tay": 0,
		"ghi_chu": ghi_chu_he_thong("tra_truoc", pe), "tao_luc": luc_chi(x.posting_date, get_datetime(x.creation)),
	}


def _ghi(khoa: str, gia_tri: dict) -> str:
	ten = frappe.db.get_value(DT, {"khoa_nguon": khoa}, "name")
	gia_tri = {**gia_tri, "tinh_luc": now_datetime()}
	if ten:
		doc = frappe.get_doc(DT, ten)
		doc.update(gia_tri)
		doc.flags.ignore_permissions = True
		doc.save()
		return doc.name
	doc = frappe.get_doc({"doctype": DT, "khoa_nguon": khoa, **gia_tri})
	doc.insert(ignore_permissions=True)
	return doc.name


def chieu_phieu_nhap(ten: str | None) -> str | None:
	"""Chiếu dòng công nợ NCC của một Purchase Invoice (PN / PTNCC / DKN / NTN). Trả tên dòng (`payable_id` / `payable_credit_id`) hoặc None."""
	if not ten:
		return None
	khoa = f"Purchase Invoice:{ten}"
	gt = gia_tri_pi(ten)
	if gt is None:
		frappe.db.delete(DT, {"khoa_nguon": khoa})  # xoá thẳng như bản chiếu khách (blueprint §4.3)
		return None
	return _ghi(khoa, gt)


def chieu_tra_truoc(pe: str | None) -> str | None:
	"""Chiếu dòng trả trước của một phiếu chi NCC (Payment Entry `PCNCC-`)."""
	if not pe:
		return None
	khoa = f"Payment Entry:{pe}"
	gt = gia_tri_tra_truoc(pe)
	if gt is None:
		frappe.db.delete(DT, {"khoa_nguon": khoa})
		return None
	return _ghi(khoa, gt)


def chieu_tra_truoc_ncc(ncc: str | None) -> None:
	"""Mọi dòng trả trước của một NCC (phiếu chi đang ghi sổ + dòng đang có) — sau khi lõi gỡ phân bổ PE khỏi PI bị huỷ
	(`unlink_payment_on_cancellation_of_invoice`): lúc hook chạy tham chiếu đã mất, không biết PE nào vừa được trả tiền về."""
	if not ncc or not frappe.get_meta("Payment Entry").has_field("npp_loai"):
		return
	ds = set(frappe.get_all("Payment Entry", filters={"party_type": "Supplier", "party": ncc, "docstatus": 1, "npp_loai": "phieu_chi_ncc"},
		pluck="name"))
	ds |= set(frappe.get_all(DT, filters={"nha_cung_cap": ncc, "loai": "tra_truoc"}, pluck="phieu_chi"))
	for pe in sorted(x for x in ds if x):
		chieu_tra_truoc(pe)


def chieu_cong_no_ncc(dt: str, ten: str | None) -> None:
	"""Tên chung của luật chiếu (`chieu_cong_no_ncc(nguon)` của đặc tả §2.8 / BP §4.3.0) — method gọi thẳng sau thao tác lõi không qua doc_events
	(`reconcile_against_document`, gỡ phân bổ…): Purchase Invoice → dòng của tờ; Payment Entry / Journal Entry → mọi tờ chúng trỏ + dòng trả trước."""
	if not ten:
		return
	if dt == "Purchase Invoice":
		chieu_phieu_nhap(ten)
	elif dt == "Payment Entry":
		sau_thanh_toan(frappe.get_doc(dt, ten))
	elif dt == "Journal Entry":
		sau_but_toan(frappe.get_doc(dt, ten))
	else:
		raise ValueError(f"không phải chứng từ nguồn công nợ NCC: {dt}")


def chieu_dong(r) -> None:
	"""Chiếu lại một dòng theo loại (dòng đọc từ get_all / khoa_ncc)."""
	if r.get("loai") == "tra_truoc":
		chieu_tra_truoc(r.get("phieu_chi"))
	elif r.get("chung_tu"):
		chieu_phieu_nhap(r.get("chung_tu"))
	else:
		frappe.db.delete(DT, {"name": r.get("name")})  # dòng mồ côi không còn chứng từ nguồn


def chieu_ncc(ncc: str) -> None:
	"""Chiếu lại MỌI nguồn công nợ của một NCC (việc đêm / sau gộp NCC): mọi PI đã / thôi ghi sổ, phiếu chi, rồi dòng đang có (bắt dòng mồ côi)."""
	for pi in frappe.get_all("Purchase Invoice", filters={"supplier": ncc, "docstatus": ("in", (1, 2))}, pluck="name", order_by="name"):
		chieu_phieu_nhap(pi)
	chieu_tra_truoc_ncc(ncc)
	for r in frappe.get_all(DT, filters={"nha_cung_cap": ncc}, fields=["name", "loai", "chung_tu", "phieu_chi"]):
		chieu_dong(r)


def khoa_ncc(ncc: str) -> list:
	"""Khoá chung của mọi method đổi nợ một NCC (như `cong_no.khoa_khach` — Q15 của đặc tả phiếu thu): dòng Supplier rồi mọi dòng `NPP Cong No NCC`
	của NCC theo `name` (nppsale `_don_tra_truoc_ncc`: `PERFORM 1 FROM payables … ORDER BY id FOR UPDATE`). Method gọi TRƯỚC mọi câu đọc thường."""
	frappe.db.sql("SELECT `name` FROM `tabSupplier` WHERE `name` = %s FOR UPDATE", ncc)
	return frappe.db.sql(f"""SELECT `name`, `loai`, `chung_tu`, `phieu_chi`, `so_tien`, `da_tra`, `con_no`, `trang_thai`, `tao_luc`
		FROM `tab{DT}` WHERE `nha_cung_cap` = %s ORDER BY `name` FOR UPDATE""", ncc, as_dict=True)


# ------------------------------------------------------------------------------------------------ dồn trả trước
def phieu_chi_con_tien(ncc: str) -> list:
	"""Phiếu chi NCC đang ghi sổ của NCC còn tiền chưa phân bổ THEO SỔ (−Σ Payment Ledger trỏ chính phiếu > 0), theo lúc chi rồi tên (nppsale `ORDER BY
	pp.paid_at, pp.id` — phiếu chi SỚM hơn dồn trước; hoà lúc chi nppsale xếp theo uuid dòng tiền, ở đây theo số phiếu)."""
	if not frappe.get_meta("Payment Entry").has_field("npp_loai"):
		return []
	ds = frappe.db.sql("""SELECT p.`name`, p.`posting_date`, p.`creation`, -SUM(l.`amount`) AS `con`
		FROM `tabPayment Entry` p
		JOIN `tabPayment Ledger Entry` l ON l.`against_voucher_type` = 'Payment Entry' AND l.`against_voucher_no` = p.`name` AND l.`delinked` = 0
		WHERE p.`docstatus` = 1 AND p.`party_type` = 'Supplier' AND p.`party` = %s AND p.`npp_loai` = 'phieu_chi_ncc'
		GROUP BY p.`name`, p.`posting_date`, p.`creation` HAVING SUM(l.`amount`) < -0.005""", ncc, as_dict=True)
	for r in ds:
		r.luc = luc_chi(r.posting_date, get_datetime(r.creation))
	return sorted(ds, key=lambda r: (r.luc, r.name))


def khoan_no_mo(ncc: str) -> list:
	"""MỌI khoản nợ còn phải trả của NCC theo thứ tự dồn của `_don_tra_truoc_ncc`: PI đang ghi sổ, không phải tờ trả NCC / dòng âm, còn nợ theo sổ
	> 0; nợ đầu kỳ trước (`opening_balance DESC`), rồi ngày ghi nợ, rồi tên. Dòng trả trước không phải khoản nợ."""
	ds = frappe.db.sql("""SELECT pi.`name`, pi.`npp_loai`, pi.`is_return`, pi.`is_opening`, pi.`grand_total`, pi.`credit_to`,
			pi.`outstanding_amount`, COALESCE(pi.`npp_hoan_thanh_luc`, pi.`creation`) AS `tao`, x.`con`
		FROM (SELECT `against_voucher_no` AS `ct`, SUM(`amount`) AS `con` FROM `tabPayment Ledger Entry`
			WHERE `party_type` = 'Supplier' AND `party` = %(n)s AND `against_voucher_type` = 'Purchase Invoice' AND `delinked` = 0
			GROUP BY `against_voucher_no` HAVING SUM(`amount`) > 0.005) x
		JOIN `tabPurchase Invoice` pi ON pi.`name` = x.`ct`
		WHERE pi.`docstatus` = 1 AND pi.`is_return` = 0 AND pi.`grand_total` >= 0""", {"n": ncc}, as_dict=True)
	for r in ds:
		r.dau_ky = loai_cua_pi(r.npp_loai, r.name, r.is_return, r.is_opening) == "dau_ky"
		r.tao = get_datetime(r.tao)
	ds.sort(key=lambda r: (not r.dau_ky, r.tao, r.name))
	return ds


def khoan_no_cu_nhat(ncc: str):
	"""Khoản nợ còn phải trả cũ nhất của NCC (đầu `khoan_no_mo`)."""
	ds = khoan_no_mo(ncc)
	return ds[0] if ds else None


def _tien(x) -> Decimal:
	return Decimal(str(round(flt(x), 2)))


def ke_hoach_don(ncc: str, moi: PhieuChiCon | None = None) -> list[tuple[str | None, str, Decimal]]:
	"""Kế hoạch dồn trả trước của NCC (`nppsale.luat.cong_no_ncc.phan_bo_tra_truoc`) trên số sổ hiện tại: mọi phiếu chi còn tiền + `moi` (phiếu chi
	đang lập — `chi_tra_ncc`), mọi khoản nợ còn mở. Nơi gọi đã khoá NCC (`khoa_ncc`)."""
	pc = [PhieuChiCon(p.name, p.luc, _tien(p.con)) for p in phieu_chi_con_tien(ncc)]
	if moi is not None:
		pc.append(moi)
	kn = [KhoanNo(k.name, _tien(k.con), bool(k.dau_ky), k.tao) for k in khoan_no_mo(ncc)]
	return phan_bo_tra_truoc(pc, kn)


def ap_phan_bo(pe: str, pi: str, lay, ncc: str) -> None:
	"""Gắn `lay` đồng của phiếu chi `pe` vào khoản nợ `pi` (đọc lại số còn chưa phân bổ của phiếu + công nợ của PI ngay lúc gắn) rồi chiếu lại
	khoản."""
	khoan = frappe.db.get_value("Purchase Invoice", pi, ["name", "credit_to", "grand_total", "outstanding_amount"], as_dict=True)
	chua = flt(frappe.db.get_value("Payment Entry", pe, "unallocated_amount"))
	_phan_bo(pe, khoan, flt(lay), chua, ncc)
	chieu_phieu_nhap(pi)


def tien_tra_thang(pi: str) -> float:
	"""Tiền trả THẲNG vào một phiếu (đặc tả §3.2 bước 3 — `DA_TRA_TIEN`): Ghi trả (Payment Entry `ghi_tra_ncc`) + vế Nợ của bút toán bù trừ
	(`bu_tru_ncc`) đang ghi sổ trỏ phiếu. Phần phiếu chi `PCNCC-` KHÔNG tính: lõi gỡ phân bổ khi huỷ phiếu, method dồn sang khoản khác (mig 242
	`_tra_phan_bo_ve_truoc`)."""
	if not frappe.get_meta("Payment Entry").has_field("npp_loai"):
		return 0.0
	pe = flt(frappe.db.sql("""SELECT COALESCE(SUM(r.`allocated_amount`), 0) FROM `tabPayment Entry Reference` r
		JOIN `tabPayment Entry` p ON p.`name` = r.`parent` AND r.`parenttype` = 'Payment Entry'
		WHERE p.`docstatus` = 1 AND p.`npp_loai` = 'ghi_tra_ncc' AND r.`reference_doctype` = 'Purchase Invoice'
			AND r.`reference_name` = %s""", pi)[0][0])
	if not frappe.get_meta("Journal Entry").has_field("npp_loai"):
		return pe
	je = flt(frappe.db.sql("""SELECT COALESCE(SUM(a.`debit_in_account_currency` - a.`credit_in_account_currency`), 0)
		FROM `tabJournal Entry Account` a JOIN `tabJournal Entry` j ON j.`name` = a.`parent` AND a.`parenttype` = 'Journal Entry'
		WHERE j.`docstatus` = 1 AND j.`npp_loai` = 'bu_tru_ncc' AND a.`party_type` = 'Supplier' AND a.`reference_type` = 'Purchase Invoice'
			AND a.`reference_name` = %s""", pi)[0][0])
	return pe + je


def _phan_bo(pe: str, khoan, lay: float, chua: float, ncc: str) -> None:
	"""Gắn `lay` đồng của phiếu chi vào khoản nợ bằng đường lõi `reconcile_against_document` (PE giữ tên); tham chiếu MỚI chép dấu xác nhận cấp PE
	(`npp_xac_nhan_*` — mig 242 chép `verified_by / verified_at` của dòng trả trước sang dòng mới)."""
	from erpnext.accounts.utils import reconcile_against_document

	truoc = set(frappe.get_all("Payment Entry Reference", filters={"parent": pe, "parenttype": "Payment Entry"}, pluck="name"))
	reconcile_against_document([frappe._dict({
		"voucher_type": "Payment Entry", "voucher_no": pe, "voucher_detail_no": None, "against_voucher_type": "Purchase Invoice",
		"against_voucher": khoan.name, "account": khoan.credit_to, "party_type": "Supplier", "party": ncc,
		"dr_or_cr": "debit_in_account_currency", "unreconciled_amount": chua, "unadjusted_amount": chua, "allocated_amount": lay,
		"grand_total": flt(khoan.grand_total), "outstanding_amount": flt(khoan.outstanding_amount), "exchange_rate": 1, "difference_amount": 0,
		"difference_posting_date": None, "precision": 0})])
	frappe.local.message_log = []
	if not frappe.get_meta("Payment Entry Reference").has_field("npp_xac_nhan_boi"):
		return
	xn = frappe.db.get_value("Payment Entry", pe, ["npp_xac_nhan_boi", "npp_xac_nhan_luc"], as_dict=True)
	if xn and (xn.npp_xac_nhan_boi or xn.npp_xac_nhan_luc):
		for ten in frappe.get_all("Payment Entry Reference", filters={"parent": pe, "parenttype": "Payment Entry"}, pluck="name"):
			if ten not in truoc:
				frappe.db.set_value("Payment Entry Reference", ten, {"npp_xac_nhan_boi": xn.npp_xac_nhan_boi,
					"npp_xac_nhan_luc": xn.npp_xac_nhan_luc}, update_modified=False)


def don_tra_truoc_ncc(ncc: str | None) -> float:
	"""Dồn tiền trả trước của NCC vào các khoản nợ cũ nhất (`_don_tra_truoc_ncc` mig 242; đặc tả §2.8): chỉ chạy khi NCC có phiếu chi còn tiền (= EXISTS
	của trigger) → khoá NCC + mọi dòng → kế hoạch dồn (`ke_hoach_don` — phiếu chi theo lúc chi, khoản cũ nhất trước, lấy = min(còn, còn nợ)) → phân bổ
	từng phần → chiếu lại khoản; cuối cùng chiếu dòng trả trước (hết tiền → xoá). Không đụng tờ trả NCC / dòng âm (mig 242: "cấn trừ chúng sẽ khoá huỷ
	/ sửa phiếu trả"). Trả tổng đã dồn. `chi_tra_ncc` dùng CÙNG kế hoạch cho phiếu đang lập (tham chiếu lập sẵn khi ghi sổ)."""
	if not ncc or not phieu_chi_con_tien(ncc):
		return 0.0
	khoa_ncc(ncc)
	co_tien = [p.name for p in phieu_chi_con_tien(ncc)]
	tong = 0.0
	for pe, pi, lay in ke_hoach_don(ncc):
		ap_phan_bo(pe, pi, lay, ncc)
		tong += flt(lay)
	for pe in co_tien:
		chieu_tra_truoc(pe)
	return tong


# ------------------------------------------------------------------------------------------------ doc_events
def sau_ghi_so_phieu_nhap(doc, method=None):
	"""Purchase Invoice ghi sổ / huỷ / đổi trường AOS (số HĐ NCC, hạn, dấu quá hạn, ghi chú công nợ, giá đã sửa) → chiếu lại dòng của tờ. Ghi sổ / huỷ
	còn chiếu lại các dòng trả trước của NCC: huỷ tờ thì lõi đã gỡ phân bổ phiếu chi (tiền về phần chưa phân bổ — tham chiếu không còn để dò)."""
	chieu_phieu_nhap(doc.name)
	if method in ("on_submit", "on_cancel"):
		chieu_tra_truoc_ncc(doc.get("supplier"))


def sau_thanh_toan(doc, method=None):
	"""Payment Entry ghi sổ / huỷ — nhánh Supplier (nhánh khách: `cong_no.sau_thanh_toan`): mọi PI được phân bổ + dòng trả trước của chính phiếu."""
	if doc.get("party_type") != "Supplier":
		return
	for pi in dict.fromkeys(r.reference_name for r in doc.get("references") or [] if r.reference_doctype == "Purchase Invoice"
			and r.reference_name):
		chieu_phieu_nhap(pi)
	chieu_tra_truoc(doc.name)


def sau_but_toan(doc, method=None):
	"""Journal Entry ghi sổ / huỷ — vế Supplier (bù trừ `CTN-`, điều chỉnh giá nhập `DCN-`, cấn trừ tay trên Desk): mọi PI / phiếu chi mà vế tham chiếu,
	cộng phiếu nhập của bút toán sửa giá (`npp_phieu_nhap`)."""
	tk = [a for a in doc.get("accounts") or [] if a.party_type == "Supplier"]
	pis = [a.reference_name for a in tk if a.reference_type == "Purchase Invoice"]
	if doc.get("npp_phieu_nhap"):
		pis.append(doc.get("npp_phieu_nhap"))
	for pi in dict.fromkeys(x for x in pis if x):
		chieu_phieu_nhap(pi)
	for pe in dict.fromkeys(a.reference_name for a in tk if a.reference_type == "Payment Entry" and a.reference_name):
		chieu_tra_truoc(pe)
