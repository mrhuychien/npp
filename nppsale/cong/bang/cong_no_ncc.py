"""Bảng CÔNG NỢ + TIỀN NCC của nppsale trên cổng (P4 — mốc M3; đặc tả kho_mua §4.4; blueprint 02 §6.1 dòng `payables` / `payable_payments` /
`supplier_payments`):

- payables ← `NPP Cong No NCC` (bản chiếu từ sổ — `nppsale.su_kien.cong_no_ncc`, §2.8): `amount` = `so_tien`, `paid` = `da_tra`, `created_at` = `tao_luc`
  (ngày ghi nợ), `opening_balance` = (`loai = dau_ky`), `stock_entry_id` = `phieu_kho`. RLS đọc (mig 034): owner / manager / accountant — thủ kho / NVBH
  0 dòng. GHI (owner / accountant — mig 163; trigger `_khoa_ghi_thang_no_ncc` mig 227 chạy TRƯỚC RLS khi thêm): nppsale.rpc.cong_no_ncc
  (`them_no` — nợ đầu kỳ = tờ `DKN-`, nợ lập tay = tờ `NTN-`; `sua_no` — số HĐ / hạn / ghi chú / trạng thái tay, số nợ đầu kỳ chưa trả = amend `DKN-…-n`;
  `xoa_no` — huỷ tờ `DKN-` / `NTN-` chưa trả; nợ của phiếu nhập / trả NCC → 23503 khoá ngoại như nppsale).
- payable_payments ← SQL dựng (`NGUON_TRA_NO`): tham chiếu Payment Entry (`phieu_chi_ncc` / `ghi_tra_ncc`) + vế phải trả của bút toán bù trừ `CTN-`
  (`bu_tru_ncc` — số có dấu: vế Nợ khoản được trả +, vế Có phiếu trả NCC − để `paid` = Σ dòng ở cả dòng âm) + phần chưa phân bổ của phiếu chi
  (`<PE>::tra_truoc` — dòng trả trước). `paid_at` = lúc chi (luật `v_luc` của `chi_tra_ncc`: phiếu chi ngày tạo → giờ tạo, ghi lùi → 12:00 của ngày chi;
  MỌI phần của một phiếu chi mang cùng lúc chi); Ghi trả / bù trừ → giờ lập. RLS đọc owner / manager / accountant; GHI chỉ xác nhận
  (`verified_by` / `verified_at` — owner / accountant), mọi ghi khác → `CHI_NCC_KHOA` (trigger `_khoa_ghi_thang_chi_ncc` mig 227).
- supplier_payments ← Payment Entry `npp_loai = phieu_chi_ncc` (`PCNCC-`): `seq` tách từ tên, `reference_code` = số người gõ (số tự điền cho TK ngân
  hàng = tên phiếu → NULL), `prepay_payable_id` = dòng trả trước còn tiền. RLS đọc owner / manager / accountant; KHÔNG chính sách ghi (mig 242): thêm →
  42501 như RLS, sửa / xoá → 0 dòng.
"""
from __future__ import annotations

from ..dang_ky import Bang, CotDef, NguCanh, QuanHe, dang_ky
from ._chung import c, co_cot, org, tu_choi

VAI_NO = ("owner", "manager", "accountant")
DT = "`tabNPP Cong No NCC`"
# hình thức (method nppsale) ← Mode of Payment: TK chuyển khoản của NPP Cai Dat (trống → mặc định "Chuyen khoan" — cai_dat_ban)
HT_CK = "COALESCE((SELECT s.`value` FROM `tabSingles` s WHERE s.`doctype` = 'NPP Cai Dat' AND s.`field` = 'ht_chuyen_khoan'), 'Chuyen khoan')"
NGUOI = "CASE WHEN {o} IN ('Administrator', 'Guest') THEN NULL ELSE {o} END"
# lúc chi của phiếu chi NCC (đặc tả §2.8 — luật `v_luc`): ngày chi = ngày tạo (giờ VN của site) → giờ tạo; ghi lùi → 12:00 của ngày chi
LUC_CHI = "CASE WHEN p.`npp_loai` = 'phieu_chi_ncc' AND p.`posting_date` <> DATE(p.`creation`) THEN TIMESTAMP(p.`posting_date`, '12:00:00') ELSE p.`creation` END"
HINH_THUC = f"CASE WHEN p.`mode_of_payment` = {HT_CK} THEN 'transfer' ELSE 'cash' END"
GHI_CHU_CHI = ("CASE WHEN p.`npp_loai` = 'phieu_chi_ncc' THEN CONCAT('Phiếu chi ', p.`name`, CASE WHEN IFNULL(p.`npp_ghi_chu`, '') = '' THEN '' "
	"ELSE CONCAT(' — ', p.`npp_ghi_chu`) END) ELSE p.`npp_ghi_chu` END")
COT_TRA = "`id`, `payable_id`, `amount`, `method`, `paid_by`, `paid_at`, `verified_by`, `verified_at`, `notes`, `supplier_payment_id`"
# dòng tiền trả NCC (bảng `payable_payments` của nppsale) — dùng chung cổng + khám sổ (nppsale.kham_so.quet_dong_chi_ncc)
NGUON_TRA_NO = (
	"(SELECT r.`name` AS `id`, n.`name` AS `payable_id`, r.`allocated_amount` AS `amount`, " + HINH_THUC + " AS `method`, "
	+ NGUOI.format(o="p.`owner`") + " AS `paid_by`, " + LUC_CHI + " AS `paid_at`, r.`npp_xac_nhan_boi` AS `verified_by`, "
	"r.`npp_xac_nhan_luc` AS `verified_at`, " + GHI_CHU_CHI + " AS `notes`, "
	"CASE WHEN p.`npp_loai` = 'phieu_chi_ncc' THEN p.`name` END AS `supplier_payment_id` "
	"FROM `tabPayment Entry Reference` r JOIN `tabPayment Entry` p ON p.`name` = r.`parent` AND r.`parenttype` = 'Payment Entry' "
	f"LEFT JOIN {DT} n ON n.`khoa_nguon` = CONCAT('Purchase Invoice:', r.`reference_name`) "
	"WHERE p.`docstatus` = 1 AND p.`payment_type` = 'Pay' AND p.`party_type` = 'Supplier' AND p.`npp_loai` IN ('phieu_chi_ncc', 'ghi_tra_ncc') "
	"AND r.`reference_doctype` = 'Purchase Invoice' "
	"UNION ALL "
	"SELECT a.`name`, n.`name`, a.`debit_in_account_currency` - a.`credit_in_account_currency`, 'offset', " + NGUOI.format(o="j.`owner`")
	+ ", j.`creation`, a.`npp_xac_nhan_boi`, a.`npp_xac_nhan_luc`, j.`user_remark`, NULL "
	"FROM `tabJournal Entry Account` a JOIN `tabJournal Entry` j ON j.`name` = a.`parent` AND a.`parenttype` = 'Journal Entry' "
	f"LEFT JOIN {DT} n ON n.`khoa_nguon` = CONCAT('Purchase Invoice:', a.`reference_name`) "
	"WHERE j.`docstatus` = 1 AND j.`npp_loai` = 'bu_tru_ncc' AND a.`party_type` = 'Supplier' AND a.`reference_type` = 'Purchase Invoice' "
	"UNION ALL "
	"SELECT CONCAT(p.`name`, '::tra_truoc'), n.`name`, n.`da_tra`, " + HINH_THUC + ", " + NGUOI.format(o="p.`owner`") + ", " + LUC_CHI
	+ ", p.`npp_xac_nhan_boi`, p.`npp_xac_nhan_luc`, " + GHI_CHU_CHI + ", p.`name` "
	f"FROM `tabPayment Entry` p JOIN {DT} n ON n.`khoa_nguon` = CONCAT('Payment Entry:', p.`name`) "
	"WHERE p.`docstatus` = 1 AND p.`npp_loai` = 'phieu_chi_ncc')"
)
NGUON_PHIEU_CHI = (f"(SELECT p.*, n.`name` AS `_tra_truoc`, {HINH_THUC} AS `_hinh_thuc` FROM `tabPayment Entry` p "
	f"LEFT JOIN {DT} n ON n.`khoa_nguon` = CONCAT('Payment Entry:', p.`name`) "
	"WHERE p.`npp_loai` = 'phieu_chi_ncc' AND p.`payment_type` = 'Pay' AND p.`docstatus` IN (1, 2))")


def _rls_no(nc: NguCanh):
	if nc.bo_qua_rls or nc.vai in VAI_NO:
		return None
	return False


class GhiCongNoNcc:
	"""payables: nợ đầu kỳ / nợ lập tay / sửa / xoá — nppsale.rpc.cong_no_ncc."""

	def them(self, ds, nc):
		from nppsale.rpc.cong_no_ncc import them_no

		return them_no(ds, nc)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.cong_no_ncc import sua_no

		return sua_no(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.cong_no_ncc import xoa_no

		return xoa_no(ids, nc)


class GhiTraNo:
	"""payable_payments: chỉ xác nhận — nppsale.rpc.cong_no_ncc."""

	def them(self, ds, nc):
		from nppsale.rpc.cong_no_ncc import them_tra

		return them_tra(ds, nc)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.cong_no_ncc import xac_nhan_tra

		return xac_nhan_tra(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.cong_no_ncc import xoa_tra

		return xoa_tra(ids, nc)


class GhiPhieuChi:
	"""supplier_payments: không chính sách ghi (mig 242 — `phieu_chi_ncc_doc` chỉ đọc): thêm → 42501 như RLS; sửa / xoá → 0 dòng, không lỗi
	(đã chạy K22). Lập / huỷ đi qua RPC chi_tra_ncc / huy_phieu_chi_ncc."""

	def them(self, ds, nc):
		tu_choi("supplier_payments")

	def sua(self, gia_tri, ids, nc):
		return []

	def xoa(self, ids, nc):
		return []


def nap():
	if not co_cot("NPP Cong No NCC", "khoa_nguon"):
		return
	dang_ky(Bang(
		ten="payables",
		nguon=DT,
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "supplier_id": c("nha_cung_cap"), "stock_entry_id": c("phieu_kho"),
			"invoice_number": c("so_hd_ncc"), "amount": c("so_tien", "tien"), "paid": c("da_tra", "tien"), "due_date": c("han_thanh_toan", "ngay"),
			"status": c("trang_thai"), "notes": c("ghi_chu"), "created_at": c("tao_luc", "gio"),
			"opening_balance": c("({t}.`loai` = 'dau_ky')", "bool"), "tim_kd": c("tim_kd"),
		},
		quan_he=[
			QuanHe("suppliers", "supplier_id", "id", False, ("payables_supplier_id_fkey", "supplier_id")),
			QuanHe("payable_payments", "id", "payable_id", True, ("payable_payments_payable_id_fkey",)),
			QuanHe("supplier_payments", "id", "prepay_payable_id", True, ("supplier_payments_prepay_payable_id_fkey",)),
		],
		rls=_rls_no,
		ghi=GhiCongNoNcc(),
	))
	if not co_cot("Payment Entry", "npp_loai"):
		return
	dang_ky(Bang(
		ten="payable_payments",
		nguon=NGUON_TRA_NO,
		cot={
			"id": c("{t}.`id`"), "payable_id": c("{t}.`payable_id`"), "amount": c("{t}.`amount`", "tien"), "method": c("{t}.`method`"),
			"paid_by": c("{t}.`paid_by`"), "paid_at": c("{t}.`paid_at`", "gio"), "verified_by": c("{t}.`verified_by`"),
			"verified_at": c("{t}.`verified_at`", "gio"), "notes": c("{t}.`notes`"), "supplier_payment_id": c("{t}.`supplier_payment_id`"),
		},
		quan_he=[
			QuanHe("payables", "payable_id", "id", False, ("payable_payments_payable_id_fkey", "payable_id")),
			QuanHe("users", "paid_by", "id", False, ("payable_payments_paid_by_fkey", "paid_by")),
			QuanHe("users", "verified_by", "id", False, ("payable_payments_verified_by_fkey", "verified_by")),
			QuanHe("supplier_payments", "supplier_payment_id", "id", False, ("payable_payments_supplier_payment_id_fkey", "supplier_payment_id")),
		],
		rls=_rls_no,
		ghi=GhiTraNo(),
	))
	nguoi_lap = NGUOI.format(o="{t}.`owner`")
	dang_ky(Bang(
		ten="supplier_payments",
		nguon=NGUON_PHIEU_CHI,
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "seq": c("CAST(SUBSTRING_INDEX({t}.`name`, '-', -1) AS UNSIGNED)", "so"),
			"code": c("{t}.`name`"), "supplier_id": c("party"), "paid_date": c("posting_date", "ngay"), "amount": c("paid_amount", "tien"),
			"method": c("{t}.`_hinh_thuc`"),
			"reference_code": c("CASE WHEN {t}.`reference_no` = {t}.`name` OR {t}.`reference_no` = '' THEN NULL ELSE {t}.`reference_no` END"),
			"notes": c("npp_ghi_chu"), "status": c("CASE WHEN {t}.`docstatus` = 2 THEN 'cancelled' ELSE 'posted' END"),
			"prepay_payable_id": c("{t}.`_tra_truoc`"), "created_by": c(nguoi_lap), "created_at": c("creation", "gio"),
			"cancelled_at": c("npp_huy_luc", "gio"), "cancelled_by": c("npp_huy_boi"), "cancel_reason": c("npp_ly_do_huy"),
		},
		quan_he=[
			QuanHe("suppliers", "supplier_id", "id", False, ("supplier_payments_supplier_id_fkey", "supplier_id")),
			QuanHe("payables", "prepay_payable_id", "id", False, ("supplier_payments_prepay_payable_id_fkey", "prepay_payable_id")),
			QuanHe("payable_payments", "id", "supplier_payment_id", True, ("payable_payments_supplier_payment_id_fkey",)),
			QuanHe("users", "created_by", "id", False, ("supplier_payments_created_by_fkey", "created_by")),
			QuanHe("users", "cancelled_by", "id", False, ("supplier_payments_cancelled_by_fkey", "cancelled_by")),
		],
		rls=_rls_no,
		ghi=GhiPhieuChi(),
	))


_ = CotDef

try:
	nap()
except Exception:  # noqa: BLE001 — nạp sổ ngoài request (không có DB) thì thôi
	pass
