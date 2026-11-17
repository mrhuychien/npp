"""Luật thuần của CÔNG NỢ + TIỀN NCC (P4 — mốc M3; đặc tả kho_mua §2.8, §3.10–§3.12, §4.4, §5.1–§5.2) — không import frappe; bài:
nppsale.tests.test_luat_cong_no_ncc.

1. Câu lỗi nguyên văn của hàm / trigger nppsale (thân hàm ở scratchpad kho_mua/src/<tên>.sql): `record_payable_payment` (mig 167), `chi_tra_ncc` /
   `huy_phieu_chi_ncc` (mig 242), trigger `_khoa_ghi_thang_no_ncc` / `_khoa_ghi_thang_chi_ncc` (mig 227), `cancel_purchase_invoice` nhánh `DA_TRA_TIEN`
   (mig 242) — số in như RAISE '%' của numeric (`so_pg`, §2.5).
2. Trạng thái tay của dòng công nợ NCC phải khớp số đã trả (`_khoa_ghi_thang_no_ncc`: chỉ kiểm KHI `status` đổi — soát thiếu S5).
3. Dồn tiền trả trước (`_don_tra_truoc_ncc` mig 242) trong bộ nhớ: phiếu chi theo LÚC CHI (sớm dồn trước; hoà lúc chi theo số phiếu, phiếu đang lập
   sau cùng — Q9 M0), khoản nợ theo "nợ đầu kỳ trước, rồi ngày ghi nợ, rồi tên"; không đụng dòng âm / dòng trả trước (đã lọc ở nơi gọi).
4. Bù trừ (`offset` — §7.3 điểm 10, BP §7.1 điểm 15, quyết định tạm Q9): chỉ trong phạm vi khoản giảm còn mở của các phiếu trả NCC của chính NCC,
   cũ nhất trước; vượt → `BU_TRU_KHONG_CON`.
5. Chữ tham số: `btrim` của Postgres chỉ bỏ DẤU CÁCH hai đầu (không bỏ tab / xuống dòng), `NULLIF(btrim(COALESCE(x, '')), '')`; lúc chi (`luc_chi`)
   ở nppsale.luat.kho_mua.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong
from nppsale.luat.kho_mua import so, so_pg

# ------------------------------------------------------------------------------------------------ 1. câu lỗi
BANG_NO = "payables"
KHOA_THEM = "NO_NCC_KHOA: màn hình chỉ thêm được khoản nợ NCC chưa trả — trả tiền đi qua nút Ghi trả NCC"
KHOA_SUA = "NO_NCC_KHOA: số nợ / số đã trả NCC chỉ đổi qua phiếu nhập, phiếu trả NCC, Ghi trả NCC (RPC)"
KHOA_XOA = "NO_NCC_KHOA: chỉ xoá được khoản nợ NCC chưa trả đồng nào (không có phiếu chi)"
CHI_NCC_KHOA = "CHI_NCC_KHOA: tiền trả NCC chỉ ghi qua nút Ghi trả NCC (RPC record_payable_payment)"
BAD_AMOUNT_TRA = "BAD_AMOUNT: số tiền phải lớn hơn 0."  # record_payable_payment (chữ thường)
BAD_AMOUNT_CHI = "BAD_AMOUNT: Số tiền chi phải lớn hơn 0."  # chi_tra_ncc (chữ S hoa — khác record_payable_payment)
BAD_METHOD = "BAD_METHOD: Hình thức chi chỉ là tiền mặt hoặc chuyển khoản."
NCC_KHONG_HOP_LE = "NCC_KHONG_HOP_LE: Nhà cung cấp không thuộc đơn vị của bạn."
NGAY_TUONG_LAI_CHI = "NGAY_TUONG_LAI: Ngày chi không được sau hôm nay."
PAYABLE_NOT_FOUND = "PAYABLE_NOT_FOUND: không tìm thấy khoản công nợ NCC này."
PHIEU_CHI_KHONG_TON_TAI = "PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu chi này."
# §7.3 điểm 10 / BP §7.1 điểm 15 (đề xuất — mã + câu MỚI, nppsale không có): bù trừ vượt khoản giảm còn mở của các phiếu trả NCC
BU_TRU_KHONG_CON = "BU_TRU_KHONG_CON: NCC không còn khoản giảm để bù trừ."
# CHECK `payable_payments_method_check` (method IN ('cash', 'transfer', 'offset') — NULL qua được)
CHECK_METHOD = 'new row for relation "payable_payments" violates check constraint "payable_payments_method_check"'
HINH_THUC_GHI_TRA = ("cash", "transfer", "offset")
HINH_THUC_CHI = ("cash", "transfer")
TRANG_THAI = ("open", "partial", "paid", "overdue")
# khoá ngoại NO ACTION trỏ `payables` (đặc tả §4.4 soát thiếu S8 — §7.3 điểm 38: trả đúng câu 23503 của nppsale)
FK_XOA = {"phieu_nhap": ("purchase_invoices_payable_id_fkey", "purchase_invoices"),
	"tra_ncc": ("supplier_returns_payable_credit_id_fkey", "supplier_returns")}


def loi_overpay(con) -> NppLoi:
	"""`record_payable_payment`: số trả > `amount − paid` (số thô: `200000`, `0`, `-30000` — dòng âm / dòng trả trước luôn rơi vào đây)."""
	return NppLoi(f"OVERPAY: số tiền vượt quá công nợ còn lại (còn {so_pg(con)}).")


def loi_check_method() -> LoiCong:
	return LoiCong("23514", CHECK_METHOD)


def loi_da_tra_tien(tien) -> NppLoi:
	"""`cancel_purchase_invoice` bước 6 (mig 242): khoản nợ của phiếu còn tiền Ghi trả / bù trừ (`paid` sau khi trả phần phiếu chi về trả trước)."""
	return NppLoi(f"DA_TRA_TIEN: Phiếu này đã trả NCC {so_pg(tien)} — huỷ phiếu là xoá mất khoản đã trả. Gỡ phiếu chi trước, hoặc lập phiếu trả "
		"hàng NCC.")


def loi_fk_xoa(loai: str, khoa: str) -> LoiCong | None:
	"""Xoá dòng nợ của phiếu nhập / phiếu trả NCC: khoá ngoại NO ACTION của nppsale (`purchase_invoices.payable_id`,
	`supplier_returns.payable_credit_id`) chặn — 23503 nguyên văn (đặc tả §7.3 điểm 38)."""
	x = FK_XOA.get(loai)
	if not x:
		return None
	return LoiCong("23503", f'update or delete on table "{BANG_NO}" violates foreign key constraint "{x[0]}" on table "{x[1]}"',
		chi_tiet=f'Key (id)=({khoa}) is still referenced from table "{x[1]}".', http=409)


# ------------------------------------------------------------------------------------------------ 2. trạng thái tay
def trang_thai_khop(status, paid, amount) -> bool:
	"""Trạng thái ghi thẳng phải khớp số đã trả (`_khoa_ghi_thang_no_ncc` mig 227): paid ⇔ đã trả ≥ số nợ − 0,01; partial ⇔ 0 < đã trả < số nợ;
	open ⇔ đã trả = 0 và số nợ > 0; overdue ⇔ đã trả < số nợ."""
	p, a = so(paid), so(amount)
	return ((status == "paid" and p >= a - Decimal("0.01")) or (status == "partial" and Decimal(0) < p < a)
		or (status == "open" and p == 0 and a > 0) or (status == "overdue" and p < a))


def loi_trang_thai(status, paid, amount) -> NppLoi:
	"""`NO_NCC_KHOA: trạng thái % không khớp số đã trả % / %` — RAISE in tham số NULL là `<NULL>`."""
	return NppLoi(f"NO_NCC_KHOA: trạng thái {status if status is not None else '<NULL>'} không khớp số đã trả {so_pg(paid)} / {so_pg(amount)}")


# ------------------------------------------------------------------------------------------------ 3. dồn trả trước
@dataclass
class PhieuChiCon:
	"""Phiếu chi NCC còn tiền chưa phân bổ: `ten` None = phiếu ĐANG LẬP (chưa có số — xếp sau cùng khi hoà lúc chi: số của nó lớn nhất)."""
	ten: str | None
	luc: datetime
	con: Decimal


@dataclass
class KhoanNo:
	"""Khoản nợ còn phải trả (> 0) của NCC — PI ghi sổ không phải phiếu trả / dòng âm; dòng trả trước không phải khoản nợ."""
	ten: str
	con: Decimal
	dau_ky: bool
	tao: datetime


def phan_bo_tra_truoc(phieu: Iterable[PhieuChiCon], khoan: Iterable[KhoanNo]) -> list[tuple[str | None, str, Decimal]]:
	"""`_don_tra_truoc_ncc` (mig 242) trong bộ nhớ → [(phiếu chi, khoản nợ, tiền)] theo đúng thứ tự dồn: phiếu chi theo lúc chi rồi số phiếu (nppsale
	`ORDER BY pp.paid_at, pp.id`), mỗi phiếu dồn vào khoản cũ nhất còn nợ (`ORDER BY opening_balance DESC, created_at, id`), lấy = min(còn của phiếu,
	còn nợ của khoản); không lấy được đồng nào thì dừng (`EXIT WHEN v_lay <= 0`)."""
	ds_pc = sorted(phieu, key=lambda p: (p.luc, p.ten is None, p.ten or ""))
	ds_kn = sorted(khoan, key=lambda k: (not k.dau_ky, k.tao, k.ten))
	con_no = {k.ten: so(k.con) for k in ds_kn}
	ra: list[tuple[str | None, str, Decimal]] = []
	for p in ds_pc:
		con = so(p.con)
		for k in ds_kn:
			if con <= 0:
				break
			lay = min(con, con_no[k.ten])
			if lay <= 0:
				continue
			ra.append((p.ten, k.ten, lay))
			con_no[k.ten] -= lay
			con -= lay
	return ra


# ------------------------------------------------------------------------------------------------ 4. bù trừ
def phan_bo_bu_tru(tien, khoan_giam: Iterable[tuple[str, object]]) -> list[tuple[str, Decimal]]:
	"""Bù trừ `tien` vào các khoản giảm còn mở [(phiếu trả NCC, số còn giảm > 0)] ĐÃ XẾP cũ nhất trước → [(phiếu trả, phần)]; tổng khoản giảm không đủ →
	`BU_TRU_KHONG_CON` (nppsale ghi `offset` như khoản trả không tiền, không gắn khoản nào — dòng âm vẫn `open`)."""
	can = so(tien)
	ds = [(t, so(x)) for t, x in khoan_giam if so(x) > 0]
	if sum((x for _t, x in ds), Decimal(0)) < can:
		raise NppLoi(BU_TRU_KHONG_CON)
	ra = []
	for t, x in ds:
		if can <= 0:
			break
		lay = min(can, x)
		ra.append((t, lay))
		can -= lay
	return ra


# ------------------------------------------------------------------------------------------------ 5. chữ tham số / hình thức / ngày
def btrim(x) -> str | None:
	"""`NULLIF(btrim(COALESCE(x, '')), '')` — btrim một tham số của Postgres chỉ bỏ dấu cách."""
	if x is None:
		return None
	t = str(x).strip(" ")
	return t or None


def nullif_rong(x) -> str | None:
	"""`NULLIF(x, '')` (record_payable_payment: không trim)."""
	if x is None:
		return None
	t = str(x)
	return t if t != "" else None


def hinh_thuc_ghi_tra(method) -> str:
	"""`record_payable_payment`: `method = NULLIF(p_method, '')` qua CHECK cash / transfer / offset (NULL qua được). Bản Frappe: NULL / '' → tiền mặt
	(Payment Entry cần TK tiền — §7.3 điểm 10, cổng trả `cash`); ngoài ba giá trị → 23514 nguyên văn (kiểm SAU `OVERPAY` như nppsale)."""
	m = nullif_rong(method)
	if m is None:
		return "cash"
	if m not in HINH_THUC_GHI_TRA:
		raise loi_check_method()
	return m


def kiem_hinh_thuc_chi(method) -> str:
	"""`chi_tra_ncc`: `COALESCE(p_method, '') NOT IN ('cash', 'transfer')` → BAD_METHOD (NULL tường minh cũng lỗi; `offset` không được)."""
	if (method or "") not in HINH_THUC_CHI:
		raise NppLoi(BAD_METHOD)
	return method


def ngay_chi(p_paid_date, hom_nay: date) -> date:
	"""`v_ngay = COALESCE(p_paid_date, vn_today())`; sau hôm nay (giờ VN) → NGAY_TUONG_LAI."""
	ngay = hom_nay if p_paid_date is None else (p_paid_date if isinstance(p_paid_date, date) else date.fromisoformat(str(p_paid_date)[:10]))
	if isinstance(ngay, datetime):
		ngay = ngay.date()
	if ngay > hom_nay:
		raise NppLoi(NGAY_TUONG_LAI_CHI)
	return ngay


def ghi_chu_dong_chi(ma: str, ghi_chu: str | None) -> str:
	"""`payable_payments.notes` của mọi phần một phiếu chi: 'Phiếu chi <mã>' || COALESCE(' — ' || ghi chú đã trim, '')."""
	return f"Phiếu chi {ma}" + (f" — {ghi_chu}" if ghi_chu else "")
