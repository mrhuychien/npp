"""Luật thuần của KHO + MUA HÀNG + CÔNG NỢ NCC (P4 — đặc tả kho_mua §2) — không import frappe; bài: nppsale.tests.test_luat_kho_mua.

1. Tiền phiếu nhập / phiếu trả NCC (§2.4 — mig 142 khối "QUY ƯỚC TIỀN", 145, 146; hàm `complete_purchase_invoice` dòng 87–141,
   `complete_supplier_return` dòng 103–201, `sua_phieu_nhap` bước 21–22): tiền dòng = SL × đơn giá − giảm dòng (giảm dòng là TIỀN của cả dòng, trừ
   thật, KHÔNG kẹp ≥ 0); thuế = thuế gõ tay kẹp ≥ 0 nếu có (`vat_override` — NULL ≠ 0), không thì Σ tiền dòng × thuế suất (tỉ lệ); tổng =
   max(0, tiền hàng + thuế − giảm đầu phiếu) — giảm đầu phiếu trừ SAU thuế; chỉ kẹp tổng; KHÔNG làm tròn ở đâu. Phiếu trả NCC cùng công thức,
   nợ NCC = −tổng (dòng âm). Phía Frappe (BP §5.9, CFD-11, PoC 3): dòng thuế `Actual` gõ tay và dòng giảm đầu phiếu `Actual` mang dấu theo
   chiều tờ — tờ trả NCC (tiền âm) phải ĐẢO dấu, chép nguyên cách của phiếu nhập là đảo chiều khoản giảm (`taxes_and_totals.py:734–745`).
2. Định dạng số trong câu lỗi (§2.5) — để bài so vàng khớp từng ký tự với RAISE của Postgres: `so_pg` (numeric không scale), `so_tich`
   (tích hai numeric — scale = tổng scale), `to_char_fm` (`to_char(x, 'FM999999990.###')` — đo PG16), ngày `DD/MM/YYYY`, giờ `HH24:MI DD/MM/YYYY`;
   `so6` (numeric(18,6)) ở nppsale/luat/xuat_kho.py.
3. Chọn lô hạn cũ trước (FEFO — §2.2): xuất lẻ `XKL`, chuyển kho `CKL`, trả NCC — `expires_at NULLS LAST, created_at, id` (mig 144 / 148 / 222 /
   228); kiểm kê hụt không lô — `expires_at NULLS LAST, id`; kiểm kê thừa không lô — `expires_at DESC NULLS LAST, id` LIMIT 1 (mig 123). Phía
   Frappe đọc lô của MỘT kho từ Serial and Batch Entry (nppsale/rpc/goi_lo.py::lo_theo_kho) — không dùng `get_auto_batch_nos` (loại lô hết hạn).
4. Kho nhận theo hạn (§2.7 — trigger `batches_auto_zone`, mig 028 / 138): vùng `sale` mà hạn ≤ hôm nay + ngưỡng → `date`; không bao giờ `date → sale`;
   không hạn → vùng người chọn. Ngưỡng `NPP Cai Dat.nguong_kho_date_ngay` (trống → 30).
5. Ghép dòng mới ↔ lô cũ khi sửa phiếu nhập (§3.3 bước 14–16 — `sua_phieu_nhap` dòng 128–153): từng dòng theo thứ tự lấy lô cũ CHƯA dùng cùng
   mặt hàng theo mã lô; danh sách mục lỗi `DA_XUAT_NHIEU_HON` đúng câu nppsale.
6. Lúc chi của phiếu chi NCC (luật `v_luc` của `chi_tra_ncc`, mig 242): chi hôm nay → lúc lập; ghi lùi → 12:00 của ngày chi.
7. Vai + trạng thái (§1.3, §1.4): cửa vai của từng RPC P4 với ĐÚNG câu `FORBIDDEN` / `KHONG_DU_QUYEN…` và SQLSTATE của hàm nppsale (§7.2 #21 — bốn câu
   `FORBIDDEN` khác nhau; cửa `npp.via_rpc` chỉ ở các hàm có nó); trạng thái nppsale của Purchase Invoice / Stock Entry (§7.3 điểm 1).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext

from nppsale.cong.loi import NppLoi
from nppsale.luat.xuat_kho import so6  # numeric(18,6) của câu lỗi kho — dùng lại, không chép

VUNG = ("sale", "date")
NGUONG_MAC_DINH = 30  # pricing_rules.date_warehouse_threshold_days: NOT NULL DEFAULT 30, CHECK 0–365


# ================================================================================================ số
def so(x) -> Decimal:
	"""Giá trị → Decimal GIỮ scale như numeric của Postgres: Decimal giữ nguyên; int → scale 0; float NGUYÊN → scale 0 (Frappe trả Float /
	Currency là float — `12.0` là số 12 người gõ, không phải `12.0`); float lẻ → chữ số ngắn nhất (`6.5`); chuỗi → đúng chữ số. None → 0."""
	if x is None:
		return Decimal(0)
	if isinstance(x, Decimal):
		return x
	if isinstance(x, bool):
		return Decimal(int(x))
	if isinstance(x, int):
		return Decimal(x)
	if isinstance(x, float):
		if x != x or x in (float("inf"), float("-inf")):
			raise ValueError(f"không phải số hữu hạn: {x!r}")
		return Decimal(int(x)) if x.is_integer() else Decimal(repr(x))
	return Decimal(str(x).strip())


def _khong_am_0(d: Decimal) -> Decimal:
	"""numeric của Postgres không có −0: `-0.00` in ra `0.00`."""
	return d.copy_abs() if d == 0 else d


def so_pg(x) -> str:
	"""numeric không scale in qua RAISE '%': đúng chữ số đã lưu (`12`, `6.5`, `100000`, `-30000`, `13332.60`); NULL → `<NULL>` (cách RAISE in
	tham số NULL). Dùng ở `DA_TRA_TIEN`, `OVERPAY`, `DA_CAN_TRU`, `STOCK_MOVED` / `NOT_ENOUGH_STOCK` (phiếu trừ), `NO_NCC_KHOA` (§2.5)."""
	if x is None:
		return "<NULL>"
	return format(_khong_am_0(so(x)), "f")


def so_tich(a, b) -> str:
	"""Tích `quantity × conversion_factor` của Postgres: scale = tổng scale hai thừa số (`2 × 24 = 48`, `1.5 × 10 = 15.0`, `0.5 × 24 = 12.0`,
	`2.50 × 1.0 = 2.500`) — `INSUFFICIENT_STOCK |` (cần) của trả NCC."""
	with localcontext() as c:
		c.prec = 60
		return format(_khong_am_0(so(a) * so(b)), "f")


TRAN_FM = Decimal(10) ** 9  # 'FM999999990.###' có 9 ô số nguyên


def to_char_fm(x) -> str:
	"""`trim(to_char(x, 'FM999999990.###'))` — đo trên PG16 (bản tham chiếu): `#` sau dấu chấm KHÔNG phải ô số nên ra SỐ NGUYÊN làm tròn nửa
	ra xa 0 (2,5 → `3`, −2,5 → `-3`, 48,75 → `49`, −0,4 → `0`); phần nguyên làm tròn ≥ 10 chữ số → `#########.###` (âm: `-#########.###`).
	Dùng ở `DA_XUAT_NHIEU_HON` (sửa phiếu nhập)."""
	d = so(x)
	tron = d.quantize(Decimal(1), rounding=ROUND_HALF_UP)
	if abs(tron) >= TRAN_FM:
		return ("-" if d < 0 else "") + "#########.###"
	return str(int(tron))


def ngay_dmy(x) -> str:
	"""`to_char(expires_at, 'DD/MM/YYYY')` — `HANG_GAN_HAN`."""
	d = x if isinstance(x, date) else date.fromisoformat(str(x)[:10])
	return f"{d.day:02d}/{d.month:02d}/{d.year:04d}"


def gio_dmy(x) -> str:
	"""`to_char(posted_at, 'HH24:MI DD/MM/YYYY')` — `ALREADY_POSTED` (Frappe in giờ VN của site — ❓ §7.3 điểm 15, đề xuất)."""
	t = x if isinstance(x, datetime) else datetime.fromisoformat(str(x))
	return f"{t.hour:02d}:{t.minute:02d} {ngay_dmy(t.date())}"


# ================================================================================================ 1. tiền phiếu nhập / trả NCC
def tien_dong(sl, gia, giam=0) -> Decimal:
	"""Tiền một dòng = SL × đơn giá − giảm dòng (TIỀN của cả dòng — trừ thật, khác dòng bán). Máy chủ nppsale không kẹp ≥ 0."""
	return so(sl) * so(gia) - so(giam)


def line_total(sl, gia, giam=0, thue_suat=0) -> Decimal:
	"""`purchase_invoice_lines.line_total` = max(0, tiền dòng) × (1 + thuế suất) — như `sua_phieu_nhap` bước 21 và `lineTotalOf` của trình
	duyệt (`src/lib/purchasing/receipt-form.ts:178–181`); cột chỉ để xem."""
	return max(tien_dong(sl, gia, giam), Decimal(0)) * (1 + so(thue_suat))


def gia_von_lo(sl, gia, giam, he_so) -> Decimal:
	"""Giá vốn mỗi đơn vị CƠ SỞ của lô nhập = (SL × giá − giảm dòng) / (SL × hệ số) — không VAT, không giảm đầu phiếu, không làm tròn (mig 142 /
	145; `complete_purchase_invoice` dòng 87–96). SL cơ sở ≤ 0 → lỗi chia (nppsale chặn trước bằng SO_LUONG_KHONG_HOP_LE)."""
	with localcontext() as c:
		c.prec = 40
		return tien_dong(sl, gia, giam) / (so(sl) * so(he_so))


@dataclass(frozen=True)
class TienPhieu:
	tien_hang: Decimal  # subtotal = Σ tiền dòng (sau giảm dòng, chưa thuế)
	thue: Decimal  # vat — số gõ tay (kẹp ≥ 0) thắng số tự cộng
	giam: Decimal  # discount — giảm đầu phiếu (phí trả hàng của phiếu trả NCC), trừ SAU thuế
	tong: Decimal  # total = max(0, tiền hàng + thuế − giảm)


def tien_phieu(dong: Iterable, giam=0, thue_go_tay=None) -> TienPhieu:
	"""Tiền cả phiếu nhập / phiếu trả NCC như máy chủ nppsale tính lại lúc hoàn thành / gửi / sửa. `dong`: (SL, đơn giá, giảm dòng, thuế suất) —
	tuple hoặc dict khoá nppsale (`quantity`, `unit_price`, `line_discount`, `vat_rate`; thiếu → 0). `thue_go_tay` None = tự cộng từ thuế suất dòng
	(`vat_override` NULL); có số → số ấy kẹp ≥ 0 (0 = hoá đơn không thuế). Giảm đầu phiếu lấy như truyền vào (`complete_purchase_invoice`:
	`COALESCE(discount, 0)`; `sua_phieu_nhap` kẹp ≥ 0 TRƯỚC khi gọi)."""
	tien = thue = Decimal(0)
	for d in dong:
		if isinstance(d, Mapping):
			sl, gia, gd, ts = d.get("quantity"), d.get("unit_price"), d.get("line_discount"), d.get("vat_rate")
		else:
			sl, gia, gd, ts = [*d, 0, 0, 0, 0][:4]
		t = tien_dong(sl, gia, gd)
		tien += t
		thue += t * so(ts)
	if thue_go_tay is not None:
		thue = max(Decimal(0), so(thue_go_tay))
	g = so(giam)
	return TienPhieu(tien_hang=tien, thue=thue, giam=g, tong=max(Decimal(0), tien + thue - g))


def no_ncc(tp: TienPhieu, la_tra: bool) -> Decimal:
	"""`payables.amount` của phiếu: phiếu nhập = tổng; phiếu trả NCC = −tổng (dòng âm — NCC nợ lại mình, mig 231 / 239)."""
	return -tp.tong if la_tra else tp.tong


def thue_go_tay_pi(thue_go_tay, la_tra: bool) -> Decimal:
	"""`tax_amount` của MỘT dòng thuế `Actual` thay các dòng VAT khi có thuế gõ tay (BP §5.9): phiếu nhập max(0, x); tờ trả NCC −max(0, x)
	(dòng Actual chia theo tỉ lệ `net_amount` — dấu theo `tax_amount`)."""
	x = max(Decimal(0), so(thue_go_tay))
	return -x if la_tra else x


def giam_dau_phieu_pi(tien_hang, thue, giam, la_tra: bool) -> tuple[str, Decimal] | None:
	"""Dòng thuế `Actual` (category `Total`) của giảm đầu phiếu trên Purchase Invoice: (`add_deduct_tax`, `tax_amount`) sao cho
	`grand_total` = ±max(0, |tiền hàng| + |thuế| − giảm) = nợ NCC của nppsale; None khi không cần dòng. `tien_hang` / `thue`: số TUYỆT ĐỐI của tờ
	Frappe (đã làm tròn đồng). Phiếu nhập giảm > 0 → `Deduct` min(giảm, tiền + thuế) (lõi từ chối grand_total < 0 ở tờ không phải trả hàng —
	`accounts_controller.py:351–354`); tờ trả NCC (tiền âm) → `Add` +min(giảm, |tiền + thuế|) — chép nguyên cách của phiếu nhập là đảo chiều
	khoản giảm. Giảm âm (ghi thẳng phiếu tạm của nppsale nhận được) → dòng ngược chiều."""
	co_so = abs(so(tien_hang)) + abs(so(thue))
	x = max(Decimal(0), co_so - so(giam)) - co_so  # phần tổng phải đổi (≤ 0 khi giảm ≥ 0)
	if x == 0:
		return None
	if la_tra:
		x = -x
	return ("Add", x) if x > 0 else ("Deduct", -x)


def tong_pi(tien_hang, thue, giam, la_tra: bool) -> Decimal:
	"""`grand_total` mong đợi của tờ: phiếu nhập max(0, tiền + thuế − giảm); tờ trả NCC −max(0, |tiền| + |thuế| − giảm)."""
	t = max(Decimal(0), abs(so(tien_hang)) + abs(so(thue)) - so(giam))
	return -t if la_tra else t


def dong_pi(sl, gia, giam=0, chu_so: int = 4) -> dict:
	"""Giá trên dòng Purchase Invoice Item (BP §5.9, §5.16): `price_list_rate` = đơn giá; `rate` = tiền dòng / SL; `discount_amount` = giảm dòng /
	SL — làm tròn `chu_so` chữ số lẻ (Property Setter precision 4 của `rate` / `net_rate` / `discount_amount`: giảm dòng không chia hết SL vẫn
	giữ `amount` = tiền dòng sau làm tròn đồng — BP §7.2 điểm 3). SL ≤ 0 → không chia (nppsale chặn trước)."""
	q = so(sl)
	mau = Decimal(1).scaleb(-chu_so)
	with localcontext() as c:
		c.prec = 40
		rate = (tien_dong(sl, gia, giam) / q).quantize(mau, rounding=ROUND_HALF_UP)
		ck = (so(giam) / q).quantize(mau, rounding=ROUND_HALF_UP)
	return {"price_list_rate": so(gia), "rate": rate, "discount_amount": ck, "npp_giam_dong": so(giam)}


def tien_cong_pi(*, tong_dong, thue_vat, giam, co_thue_go_tay, thue_go_tay, grand_total, la_tra: bool) -> dict:
	"""Cột tiền cổng trả cho `purchase_invoices` / `supplier_returns` (§2.4 "Cổng đọc"): `subtotal` = `PI.total`; `vat` = Σ các dòng VAT / dòng
	thuế gõ tay (KHÔNG đọc `total_taxes_and_charges` — đã trừ dòng giảm); `discount` = `npp_giam_dau_phieu`; `vat_override` = thuế gõ tay khi
	có cờ (không thì NULL); `total` = `grand_total`. Tờ trả NCC: đổi dấu về dương như nppsale."""
	k = -1 if la_tra else 1
	return {"subtotal": k * so(tong_dong), "vat": k * so(thue_vat), "discount": so(giam),
		"vat_override": so(thue_go_tay) if co_thue_go_tay else None, "total": k * so(grand_total)}


# ================================================================================================ 3. chọn lô hạn cũ trước (FEFO)
@dataclass
class LoKho:
	ma: str  # Batch.name = mã lô (`id` của nppsale ở khoá phụ)
	ton: Decimal  # tồn TẠI KHO (đơn vị cơ sở)
	han: date | str | None = None  # None = không hạn (xếp cuối như NULLS LAST)
	tao: datetime | str | None = None  # Batch.creation (≈ `created_at` của dòng lô — ⚠K §2.2: nppsale lấy created_at của dòng lô ở VÙNG)


@dataclass
class LayLo:
	lay: list[tuple[str, Decimal]] = field(default_factory=list)  # [(mã lô, SL cơ sở)]
	thieu: Decimal = Decimal(0)


def _han(x) -> str:
	return "" if x is None else str(x)[:10]


def thu_tu_fefo(lo: LoKho) -> tuple:
	"""`ORDER BY expires_at NULLS LAST, created_at, id` — xuất lẻ, chuyển kho, trả NCC (§2.2)."""
	return (lo.han is None, _han(lo.han), str(lo.tao or ""), lo.ma)


def thu_tu_hut(lo: LoKho) -> tuple:
	"""Kiểm kê hụt không chọn lô: `ORDER BY expires_at NULLS LAST, id` (hoà hạn → id; mig 123)."""
	return (lo.han is None, _han(lo.han), lo.ma)


def chon_lo_fefo(lo: list[LoKho], can, thu_tu=thu_tu_fefo) -> LayLo:
	"""Một dòng cần `can` đơn vị CƠ SỞ: lấy lần lượt các lô còn tồn (> 0) theo `thu_tu`; trừ `ton` của lô TẠI CHỖ để dòng sau thấy phần dòng
	trước đã lấy (nppsale trừ `qty_on_hand` ngay trong vòng dòng). Thiếu → `thieu` > 0 (nơi gọi ra mã lỗi của chứng từ)."""
	con = so(can)
	kq = LayLo()
	for x in sorted((y for y in lo if y.ton > 0), key=thu_tu):
		if con <= 0:
			break
		lay = min(x.ton, con)
		x.ton -= lay
		con -= lay
		kq.lay.append((x.ma, lay))
	kq.thieu = max(con, Decimal(0))
	return kq


def lo_nhan_thua(lo: list[LoKho]) -> str | None:
	"""Kiểm kê thừa không chọn lô: MỌI lô của mặt hàng (kể cả lô rỗng / đã đóng) — `ORDER BY expires_at DESC NULLS LAST, id LIMIT 1`."""
	co_han = sorted((x for x in lo if x.han is not None), key=lambda x: x.ma)
	co_han.sort(key=lambda x: _han(x.han), reverse=True)  # sort ổn định: hạn giảm dần, hoà hạn giữ id tăng dần
	ds = co_han + sorted((x for x in lo if x.han is None), key=lambda x: x.ma)
	return ds[0].ma if ds else None


# ================================================================================================ 4. kho nhận theo hạn
def nguong(x) -> int:
	"""`NPP Cai Dat.nguong_kho_date_ngay` — trống → 30 (= `pricing_rules.date_warehouse_threshold_days` mặc định / `batches_auto_zone`)."""
	if x is None or (isinstance(x, str) and not x.strip()):
		return NGUONG_MAC_DINH
	return int(x)


def _ngay(x) -> date:
	if isinstance(x, datetime):
		return x.date()
	return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def vung_nhan(vung_chon: str, han, hom_nay, nguong_ngay=NGUONG_MAC_DINH) -> str:
	"""`batches_auto_zone` (BEFORE INSERT / UPDATE OF expires_at): vùng `sale` mà `expires_at ≤ CURRENT_DATE + ngưỡng` → `date`; chỉ một chiều
	(không bao giờ `date → sale`); hạn trống (hàng không lô / lô không hạn — CFD-10) → giữ vùng người chọn. ⚠K nhẹ: nppsale so ngày UTC
	(`CURRENT_DATE`), Frappe truyền ngày VN của site (§2.5)."""
	if vung_chon != "sale" or han in (None, ""):
		return vung_chon
	return "date" if _ngay(han) <= _ngay(hom_nay) + timedelta(days=nguong(nguong_ngay)) else "sale"


# ================================================================================================ 5. ghép dòng ↔ lô (sửa phiếu nhập)
@dataclass
class DongGhep:
	stt: int  # vị trí 1-based của dòng trong `p_lines`
	hang: str
	base: Decimal  # SL × hệ số (đơn vị cơ sở)


@dataclass
class LoCu:
	ma: str  # Batch.name (nppsale `ORDER BY batch_code, batch_id`)
	hang: str
	da_xuat: Decimal  # SL nhập của dòng − tồn hiện tại của lô tại kho dòng


@dataclass
class KetQuaGhep:
	ghep: dict[int, str] = field(default_factory=dict)  # stt → mã lô cũ
	bo: list[str] = field(default_factory=list)  # lô cũ không ghép dòng nào (theo mã)
	muc_loi: list[str] = field(default_factory=list)


def ghep_dong_lo(dong: Iterable[DongGhep], lo_cu: Iterable[LoCu], ten_hang: Mapping[str, str] | None = None,
		dv_co_so: Mapping[str, str] | None = None) -> KetQuaGhep:
	"""`sua_phieu_nhap` bước 14–15: từng dòng mới theo `stt` lấy lô cũ CHƯA dùng cùng mặt hàng (mã nhỏ nhất); ghép được mà SL cơ sở mới < đã xuất →
	mục `'<tên>: đã xuất <x> <đơn vị cơ sở>, số lượng mới chỉ <y>'`; lô cũ không ghép mà đã xuất ≠ 0 → mục `'<tên>: đã xuất <x> — không bỏ dòng
	này được'` (nppsale vòng này không ORDER BY — thứ tự không xác định; ở đây theo mã lô). Số in `to_char_fm`. Tên / đơn vị trống in rỗng như
	`format('%s', NULL)`."""
	ten_hang = ten_hang or {}
	dv_co_so = dv_co_so or {}
	cu = sorted(lo_cu, key=lambda x: x.ma)
	dung: set[str] = set()
	kq = KetQuaGhep()
	for d in sorted(dong, key=lambda x: x.stt):
		o = next((x for x in cu if x.hang == d.hang and x.ma not in dung), None)
		if o is None:
			continue
		dung.add(o.ma)
		kq.ghep[d.stt] = o.ma
		if so(d.base) < so(o.da_xuat):
			kq.muc_loi.append(f"{ten_hang.get(d.hang) or ''}: đã xuất {to_char_fm(o.da_xuat)} {dv_co_so.get(d.hang) or ''}, "
				f"số lượng mới chỉ {to_char_fm(d.base)}")
	for o in cu:
		if o.ma in dung:
			continue
		kq.bo.append(o.ma)
		if so(o.da_xuat) != 0:
			kq.muc_loi.append(f"{ten_hang.get(o.hang) or ''}: đã xuất {to_char_fm(o.da_xuat)} — không bỏ dòng này được")
	return kq


def loi_da_xuat_nhieu_hon(muc_loi: list[str]) -> NppLoi:
	"""`sua_phieu_nhap` bước 16 (mục nối ` · `)."""
	return NppLoi("DA_XUAT_NHIEU_HON: Hàng của phiếu đã xuất nhiều hơn số lượng sửa — " + " · ".join(muc_loi)
		+ ". Giữ số lượng tối thiểu bằng số đã xuất, hoặc lập phiếu trả hàng NCC / điều chỉnh kho.")


# ================================================================================================ 6. lúc chi của phiếu chi NCC
def luc_chi(ngay_chi, luc_lap) -> datetime:
	"""Luật `v_luc` của `chi_tra_ncc` (mig 242): ngày chi = ngày lập (giờ VN — giờ hệ thống của site) → lúc lập; ghi lùi ngày → 12:00 giờ VN của
	ngày chi. Mọi phần của một phiếu chi (kể cả phần dồn sang nợ mới về sau) mang cùng lúc chi ấy — `paid_at` của cổng `payable_payments`,
	`tao_luc` của dòng trả trước, thứ tự dồn (§2.8)."""
	lap = luc_lap if isinstance(luc_lap, datetime) else datetime.fromisoformat(str(luc_lap))
	ngay = _ngay(ngay_chi)
	return lap if lap.date() == ngay else datetime.combine(ngay, time(12, 0))


# ================================================================================================ 7. vai + trạng thái (§1.3, §1.4)
VAI_MUA_HANG = ("owner", "manager", "accountant", "warehouse")  # phiếu nhập / trả NCC: nháp, hoàn thành, huỷ, sửa, khôi phục; giá nhập
VAI_TIEN_NCC = ("owner", "accountant")  # ghi `payables` (cổng), xác nhận `payable_payments`, Ghi trả, phiếu chi NCC (mig 163 / 167 / 242)
VAI_DOC_NO_NCC = ("owner", "manager", "accountant")  # đọc `payables`, `payable_payments`, `supplier_payments` (RLS mig 034 / 242)
VAI_KHO_TAY = ("owner", "warehouse")  # nhập kho tay, phiếu kho nháp / lô, xuất lẻ, chuyển kho, huỷ phiếu kho (RLS mig 002, cổng vai mig 166 / 228)
VAI_GHI_NCC = ("owner", "manager", "warehouse")  # ghi `suppliers` qua cổng (kế toán KHÔNG ghi được dù ô quyền có — RLS)

_KHO_MUA = "FORBIDDEN: vai trò của bạn không được làm thao tác kho / mua hàng này."
# tên RPC → (vai được, câu lỗi, SQLSTATE, có cửa gọi nội bộ `npp.via_rpc`) — đúng thân hàm đang chạy (§3)
CUA_VAI: dict[str, tuple] = {
	"complete_purchase_invoice": (VAI_MUA_HANG, _KHO_MUA, "42501", True),
	"cancel_purchase_invoice": (VAI_MUA_HANG, _KHO_MUA, "42501", True),
	"sua_phieu_nhap": (VAI_MUA_HANG, "FORBIDDEN: vai trò của bạn không được sửa phiếu nhập.", "42501", False),
	"khoi_phuc_phieu_nhap": (VAI_MUA_HANG, "FORBIDDEN: vai trò của bạn không được khôi phục phiếu nhập.", "42501", False),
	"luu_gia_nhap": (VAI_MUA_HANG, "KHONG_DU_QUYEN_GIA_NHAP: vai này không sửa được bảng giá nhập", "P0001", False),
	"complete_supplier_return": (VAI_MUA_HANG, _KHO_MUA, "42501", True),
	"cancel_supplier_return": (VAI_MUA_HANG, _KHO_MUA, "42501", True),
	"khoi_phuc_phieu_tra_ncc": (VAI_MUA_HANG, "FORBIDDEN: vai trò của bạn không được khôi phục phiếu trả NCC.", "42501", False),
	"so_chung_tu_ncc": (VAI_MUA_HANG, "KHONG_DU_QUYEN", "P0001", False),
	"record_payable_payment": (VAI_TIEN_NCC, "FORBIDDEN: chỉ chủ NPP hoặc kế toán được ghi trả tiền NCC.", "42501", False),
	"chi_tra_ncc": (VAI_TIEN_NCC, "FORBIDDEN: chỉ chủ NPP hoặc kế toán được lập phiếu chi trả NCC.", "42501", False),
	"huy_phieu_chi_ncc": (VAI_TIEN_NCC, "FORBIDDEN: chỉ chủ NPP hoặc kế toán được huỷ phiếu chi trả NCC.", "42501", False),
	"gop_nha_cung_cap": (VAI_DOC_NO_NCC, "KHONG_DU_QUYEN: chỉ Chủ NPP / Quản lý / Kế toán được gộp nhà cung cấp", "P0001", False),
	"xoa_nha_cung_cap": (("owner",), "KHONG_DU_QUYEN_XOA_NCC: chỉ Chủ NPP được xoá nhà cung cấp", "P0001", False),
	"post_stock_import": (VAI_KHO_TAY, "FORBIDDEN: chỉ chủ NPP hoặc thủ kho được lập phiếu nhập kho.", "42501", False),
	"post_stock_issue": (VAI_KHO_TAY, _KHO_MUA, "42501", True),
	"post_stock_transfer": (VAI_KHO_TAY, _KHO_MUA, "42501", True),
	"cancel_stock_entry": (VAI_KHO_TAY, _KHO_MUA, "42501", True),
}


def loi_vai(ham: str, vai: str | None, noi_bo: bool = False) -> NppLoi | None:
	"""Cửa vai của RPC `ham` (máy chủ nppsale chỉ đọc `users.role` — §1.4): None = được; không thì NppLoi đúng câu + SQLSTATE để ném. `noi_bo`
	(method gọi method — tương đương `npp.via_rpc = 'on'`, §2.1) chỉ mở được hàm có cửa ấy; trình duyệt không truyền được. Vai trống (tài khoản
	khoá — `user_role()` NULL) rơi vào lỗi vai như nppsale. Duyệt / từ chối kiểm kê theo ô `inventory.approve`, rà soát kho date không kiểm vai
	(§7.3 điểm 22) — không qua bảng này."""
	duoc, cau, ma, co_cua = CUA_VAI[ham]
	if (noi_bo and co_cua) or (vai or "") in duoc:
		return None
	return NppLoi(cau, code=ma, http=403 if ma == "42501" else 400)


def trang_thai_pi(docstatus, huy_luc=None) -> str:
	"""`purchase_invoices.status` / `supplier_returns.status` của một Purchase Invoice (§1.3; §7.3 điểm 1 — đề xuất: huỷ phiếu NHÁP giữ nháp + dấu
	`npp_huy_luc`, cổng trả `cancelled`, mọi method coi như đã huỷ): docstatus 2 hoặc nháp mang dấu huỷ → `cancelled`; 1 → `completed`; còn lại `draft`."""
	ds = int(docstatus or 0)
	if ds == 2 or (ds == 0 and huy_luc):
		return "cancelled"
	return "completed" if ds == 1 else "draft"


def trang_thai_phieu_kho(docstatus) -> str:
	"""`stock_entries.status` của Stock Entry (xuất lẻ `XKL-`, chuyển kho `CKL-`, nhập kho tay `IN-`…): 0 `draft` · 1 `posted` · 2 `cancelled`
	(nháp huỷ = xoá như BP — §7.3 điểm 1)."""
	return {1: "posted", 2: "cancelled"}.get(int(docstatus or 0), "draft")
