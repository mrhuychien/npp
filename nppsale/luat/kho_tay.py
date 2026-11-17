"""Luật thuần của PHIẾU KHO TAY (P4 — mốc M4; đặc tả kho_mua §3.6, §3.15, §3.16, §3.19, §4.5, §7.3 điểm 3 / 4 / 5 / 23) — không import frappe;
bài: nppsale.tests.test_luat_kho_tay. Chọn lô hạn cũ trước, kho nhận theo hạn, định dạng số ở nppsale/luat/kho_mua.py — tệp này chỉ thêm phần riêng:

1. Câu lỗi NGUYÊN VĂN của bốn hàm nppsale (thân đang chạy — scratchpad kho_mua/src/<tên>.sql): `post_stock_issue` (mig 144 / 166 / 222 / 228),
   `post_stock_transfer` (mig 148 / 166 / 222 / 228), `cancel_stock_entry` (mig 139 / 166 / 227 / 228), `post_stock_import` (mig 168 / 219) — so TỪNG
   KÝ TỰ ở bài vàng (§2.5): số cần / còn của câu thiếu tồn là numeric(18,6) (`so6`); "còn" khi không có dòng lô nào là `0` (COALESCE(SUM, 0)); nhãn
   đơn vị = `MIN(unit_name)` các dòng của mặt hàng (đơn vị giao dịch dù số là đơn vị cơ sở — §7.3 điểm 29, chép y nguyên).
2. Gom lượt một của xuất lẻ / chuyển kho (`GROUP BY product_id HAVING SUM > 0`) — mặt hàng thiếu báo trước: theo mã hàng (nppsale: thứ tự GROUP BY
   không xác định — §3.15 Frappe bước 3).
3. Tải trọng `post_stock_import(p jsonb)`: ép kiểu như khối DECLARE của hàm (22007 / 22P02 thô — trước cả FORBIDDEN), mã lô tự đặt
   `LOT-<mã>-<n>` (không đệm số), nhận diện tồn đầu kỳ theo tiền tố `DK-` (§7.3 điểm 4 — đề xuất), hạn `2099-12-31` = không hạn (CFD-10).
4. Ghi chú khi huỷ (`COALESCE(notes || E'\\n', '') || 'Huỷ phiếu: ' || COALESCE(p_reason, '(không ghi lý do)')` — lý do '' giữ rỗng).
5. Câu khoá ghi thẳng phiếu kho / dòng (trigger `_trg_khoa_ghi_thang_phieu_kho` / `_dong_kho`, mig 170).
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong
from nppsale.luat.kho_mua import VUNG, so, so6, so_numeric

HAN_KHONG = "2099-12-31"  # quy ước "không hạn" của nppsale (cổng `batches` trả lại cho hạn trống — CFD-10)
DV_CO_SO_TRONG = "đv cơ sở"
LOAI_SE = {"Material Receipt": "import", "Material Issue": "export", "Material Transfer": "transfer"}  # purpose → `stock_entries.type`
SE_XUAT_LE, SE_CHUYEN, SE_CHUYEN_DATE, SE_NHAP, SE_DAU_KY, SE_NHAP_LAI = (
	"xuat_le", "chuyen_kho", "chuyen_date_tu_dong", "nhap_kho", "ton_dau_ky", "nhap_lai_tra")

# ------------------------------------------------------------------------------------------------ 1. post_stock_issue / post_stock_transfer
KHONG_TON_TAI_XUAT = "PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu xuất kho này."
KHONG_TON_TAI_CHUYEN = "PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu chuyển kho này."
SAI_LOAI_XUAT = "SAI_LOAI_PHIEU: Phiếu này không phải phiếu xuất kho."
SAI_LOAI_CHUYEN = "SAI_LOAI_PHIEU: Phiếu này không phải phiếu chuyển kho."
KHONG_CO_HANG = "PHIEU_KHONG_CO_HANG: Phiếu chưa có dòng hàng nào."
THIEU_KHO_DICH = "THIEU_KHO_DICH: Phiếu chuyển kho chưa chọn kho đích."


def ten_vung(vung: str | None) -> str:
	"""`CASE WHEN v_zone = 'date' THEN 'hàng date' ELSE 'hàng bán' END`."""
	return "hàng date" if vung == "date" else "hàng bán"


def loi_khong_con_tam(trang_thai: str) -> NppLoi:
	"""Bước 6 của `post_stock_issue` / `post_stock_transfer` (thực tế chỉ `cancelled`)."""
	return NppLoi(f'PHIEU_KHONG_CON_TAM: Phiếu đang ở trạng thái "{trang_thai}" — chỉ phiếu tạm mới ghi sổ được.')


def loi_trung_kho(vung: str) -> NppLoi:
	"""`post_stock_transfer`: kho đích = kho nguồn — % là MÃ vùng thô (`sale` / `date`)."""
	return NppLoi(f"TRUNG_KHO: Kho nguồn và kho đích đang là một ({vung}). Chọn hai kho khác nhau.")


def con_in(co_dong: bool, ton) -> str:
	""""chỉ còn %" = `COALESCE(SUM(qty_on_hand), 0)` các lô `available` của mặt hàng ở vùng: có dòng lô (kể cả lô đã về 0) → numeric(18,6); không
	dòng nào → `0`. Frappe: "có dòng" = có dòng ở cổng `batches` tại kho (lô không tắt); hàng không lô: có Bin."""
	return so6(ton) if co_dong else "0"


def loi_khong_du_ton(ten: str, can, dv: str | None, vung: str, con: tuple, chuyen: bool = False) -> NppLoi:
	"""Lượt một (kiểm đủ trước khi trừ, gom theo mặt hàng): `KHONG_DU_TON: % — cần % %, kho % chỉ còn %.` + đuôi theo hàm — xuất lẻ "Giảm số lượng,
	đổi kho, hoặc nhập bù rồi ghi sổ lại.", chuyển kho "Giảm số lượng hoặc đổi kho nguồn.". `can` = Σ SL CƠ SỞ (`so6`), `dv` = MIN(unit_name) (trống →
	`đv cơ sở`), `con` = (có dòng, tồn)."""
	duoi = "Giảm số lượng hoặc đổi kho nguồn." if chuyen else "Giảm số lượng, đổi kho, hoặc nhập bù rồi ghi sổ lại."
	return NppLoi(f"KHONG_DU_TON: {ten} — cần {so6(can)} {dv or DV_CO_SO_TRONG}, kho {ten_vung(vung)} chỉ còn {con_in(*con)}. {duoi}")


def loi_lay_mat(ten: str, thieu) -> NppLoi:
	"""Lượt hai (hết lô vẫn còn thiếu — giao dịch khác chen giữa hai lượt; Frappe sau khoá Bin không xảy ra): `v_need` là numeric(18,6)."""
	return NppLoi(f"KHONG_DU_TON: {ten} — hàng vừa bị lấy mất trong lúc ghi sổ, còn thiếu {so6(thieu)}. Thử lại.")


def loi_hang_gan_han(ten: str, ma_lo: str, han, nguong_ngay: int) -> NppLoi:
	"""`post_stock_transfer` lượt hai: lô được ghé mà kho đích là kho bán và hạn ≤ hôm nay + ngưỡng (hạn ĐÚNG BẰNG ngưỡng cũng chặn dù câu nói
	"dưới"). Hạn in `DD/MM/YYYY`."""
	from nppsale.luat.kho_mua import ngay_dmy

	return NppLoi(f"HANG_GAN_HAN: {ten} (lô {ma_lo}, hạn {ngay_dmy(han)}) chỉ còn dưới {nguong_ngay} ngày nên không chuyển sang kho hàng bán được — hệ "
		"thống sẽ tự đẩy về kho hàng date. Bán hàng gần hạn qua kênh hàng date.")


@dataclass
class CanHang:
	hang: str
	can: Decimal  # Σ SL cơ sở các dòng
	dv: str | None  # MIN(unit_name) các dòng


def gom_can(dong: Iterable[tuple]) -> list[CanHang]:
	"""Lượt một: `SELECT product_id, MIN(unit_name), SUM(qty_in_base_uom) … GROUP BY product_id HAVING SUM(...) > 0` — dòng âm / 0 vẫn tính vào
	tổng (chỉ lượt hai mới bỏ). `dong`: (mặt hàng, đơn vị, SL cơ sở). Thứ tự ra: theo mã hàng (nppsale không xác định)."""
	gop: dict[str, list] = {}
	for hang, dv, sl in dong:
		x = gop.setdefault(hang, [Decimal(0), []])
		x[0] += so(sl)
		if dv is not None:
			x[1].append(dv)
	return [CanHang(hang, tong, min(dvs) if dvs else None) for hang, (tong, dvs) in sorted(gop.items()) if tong > 0]


# ------------------------------------------------------------------------------------------------ 2. cancel_stock_entry
KHONG_THAY_PHIEU = "ENTRY_NOT_FOUND: không tìm thấy phiếu kho này."


def loi_nguon_phieu_nhap(ma: str) -> NppLoi:
	return NppLoi(f"ENTRY_HAS_SOURCE: phiếu {ma} thuộc một hoá đơn nhập mua. Huỷ hoá đơn nhập đó thay vì huỷ riêng phiếu kho.")


def loi_nguon_tra_ncc(ma: str) -> NppLoi:
	return NppLoi(f"ENTRY_HAS_SOURCE: phiếu {ma} thuộc một phiếu trả NCC. Huỷ phiếu trả NCC đó thay vì huỷ riêng phiếu kho.")


def loi_nguon_tra_khach(ma: str) -> NppLoi:
	"""Phiếu nhập lại của phiếu trả khách ĐANG Hoàn thành (nppsale nhận diện bằng ghi chú đúng bằng `'Nhập lại từ phiếu trả ' || returns.id`;
	Frappe bằng Link `npp_phieu_tra` của phiếu `NL-` / tờ ghi có có kho `HDT-` — việc #24)."""
	return NppLoi(f"ENTRY_HAS_SOURCE: phiếu {ma} là hàng khách trả. Huỷ phiếu trả hàng đó thay vì huỷ riêng phiếu kho.")


def loi_nguon_tra_khach_sua(ma: str) -> NppLoi:
	"""Phiếu nhập lại của phiếu trả khách KHÔNG còn Hoàn thành (về Chờ xử lý / Đã huỷ / sửa HĐ) — mig 227."""
	return NppLoi(f"ENTRY_HAS_SOURCE: phiếu {ma} là hàng khách trả. Huỷ / sửa phiếu trả hàng đó thay vì huỷ riêng phiếu kho.")


def loi_nguon_no_ncc(ma: str) -> NppLoi:
	return NppLoi(f"ENTRY_HAS_SOURCE: phiếu {ma} đang có công nợ NCC. Xoá công nợ NCC đó trước rồi mới huỷ phiếu kho.")


def loi_hd_da_huy(ma: str, hd: str) -> NppLoi:
	"""mig 227: phiếu xuất của HĐ đã huỷ / đã sửa (Frappe: tờ HĐ docstatus 2 — phiếu kho = chính HĐ)."""
	return NppLoi(f"ENTRY_HAS_INVOICE: phiếu {ma} thuộc hóa đơn {hd} đã huỷ / đã sửa — hàng đã hoàn kho lúc huỷ / sửa hóa đơn, không huỷ riêng phiếu "
		"kho được.")


def loi_hd_dang_ghi(ma: str, hd: str) -> NppLoi:
	return NppLoi(f"ENTRY_HAS_INVOICE: phiếu {ma} thuộc hóa đơn {hd}. Huỷ hóa đơn đó thay vì huỷ riêng phiếu kho — huỷ riêng thì hàng về kho mà sổ "
		"nợ vẫn ghi khách còn nợ.")


def loi_khong_hoan_duoc(ma: str, loai: str) -> NppLoi:
	"""Phiếu đã ghi sổ loại `transfer` / `stocktake` (mã, loại thô)."""
	return NppLoi(f"CANNOT_REVERSE_TYPE: phiếu {ma} ({loai}) đã ghi sổ nhưng chưa có đường hoàn kho cho loại phiếu này. Dùng phiếu điều chỉnh để sửa "
		"tồn.")


def loi_da_xuat_bot(ten: str, ma: str, nhap, con) -> NppLoi:
	"""Huỷ phiếu nhập kho tay mà lô đã xuất bớt (chủ nhà: "ĐÃ XUẤT THÌ CHỈ CHO SỬA") — nhập / còn là numeric(18,6); KHÔNG nới khi cho bán vượt
	tồn (khác mig 238)."""
	return NppLoi(f'ALREADY_ISSUED: "{ten}" của phiếu {ma} đã xuất bớt — nhập {so6(nhap)} nhưng lô chỉ còn {so6(con)}. Phiếu đã xuất thì chỉ SỬA '
		"được, không huỷ được.")


def ghi_chu_huy(cu: str | None, ly_do: str | None) -> str:
	"""`notes = COALESCE(notes || E'\\n', '') || 'Huỷ phiếu: ' || COALESCE(p_reason, '(không ghi lý do)')` — ghi chú NULL thì không xuống dòng (ghi
	chú '' vẫn xuống dòng như Postgres); lý do '' giữ rỗng ("Huỷ phiếu: "), NULL → "(không ghi lý do)"."""
	return ("" if cu is None else cu + "\n") + "Huỷ phiếu: " + ("(không ghi lý do)" if ly_do is None else ly_do)


def ket_qua_huy(da_huy: bool, hoan: bool, so_lo: int) -> list[dict]:
	"""`RETURNS TABLE(cancelled, reversed, lines_reversed)` — mảng MỘT dòng (giao diện đọc `data[0]`)."""
	return [{"cancelled": da_huy, "reversed": hoan, "lines_reversed": so_lo}]


# ------------------------------------------------------------------------------------------------ 3. post_stock_import
FORBIDDEN_CHUA_GAN = "FORBIDDEN: tài khoản chưa gắn đơn vị."
THIEU_MA = "BAD_PAYLOAD: thiếu mã phiếu."
THIEU_DONG = "BAD_PAYLOAD: phiếu nhập cần ít nhất một dòng hàng."
NCC_KHAC = "ORG_MISMATCH: nhà cung cấp không thuộc đơn vị của bạn."
SAI_VUNG = "BAD_PAYLOAD: kho nhận chỉ là kho bán (sale) hoặc kho date (date)."
NO_AM = "BAD_PAYLOAD: số tiền công nợ NCC không được âm."
# CFD-12 (lõi 16.53 không chặn ngày tương lai ở Stock Entry / Purchase Invoice) — mã chưa có ở nppsale (nhập kho tay lùi / tiến ngày đều được): câu
# đề xuất của §3.6 Frappe bước 2, quyết định tạm Q9
NGAY_TUONG_LAI = "NGAY_TUONG_LAI: Ngày nhập kho không được sau hôm nay."


def loi_hang_khac(ma) -> NppLoi:
	"""`ORG_MISMATCH: sản phẩm % …` — % là `l->>'product_id'` thô (thiếu → `<NULL>` như RAISE in NULL). Frappe: mặt hàng không có (một site một
	NPP)."""
	return NppLoi(f"ORG_MISMATCH: sản phẩm {'<NULL>' if ma is None else ma} không thuộc đơn vị của bạn.", code="42501", http=403)


def loi_dong_sl(n: int) -> NppLoi:
	return NppLoi(f"BAD_PAYLOAD: dòng {n} có số lượng không hợp lệ.")


def loi_dong_gia_am(n: int) -> NppLoi:
	return NppLoi(f"BAD_PAYLOAD: dòng {n} có giá vốn âm.")


def loi_lo_trung(ma: str) -> NppLoi:
	"""Mã lô (gõ tay hoặc tự đặt `LOT-<mã>-<n>`) đã có — Batch của Frappe khoá `name` (nppsale cho trùng: lô thứ hai cùng mã — BP §7.1 điểm 14, §7.3
	điểm 6 đề xuất chặn). Cùng mã + câu với hoàn thành phiếu nhập (M1), đuôi theo màn Nhập kho — quyết định tạm Q9."""
	return NppLoi(f"LO_TRUNG_MA: Mã lô {ma} đã có trong sổ — đổi mã lô ấy rồi ghi lại phiếu nhập kho.")


def _chu_json(v) -> str | None:
	"""`p->>'k'`: thiếu / null → None; chuỗi → nguyên văn; số / bool → chữ như jsonb in."""
	from nppsale.luat.kho_mua import chu_json

	return chu_json(v)


def ep_so(v, mac=None):
	"""`(x->>'k')::numeric`: thiếu / null → `mac`; không phải số (kể cả chuỗi rỗng, `true`) → 22P02 thô như Postgres."""
	chu = _chu_json(v)
	if chu is None:
		return mac
	x = so_numeric(chu.strip())
	if x is None:
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{chu}"', http=400)
	return x


_RE_NGAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def ep_ngay(v):
	"""`NULLIF(x->>'k', '')::date`: thiếu / null / '' → None; sai → 22007 thô."""
	chu = _chu_json(v)
	if chu is None or chu == "":
		return None
	s = chu.strip()
	try:
		if _RE_NGAY.match(s):
			return date.fromisoformat(s[:10])
	except ValueError:
		pass
	raise LoiCong("22007", f'invalid input syntax for type date: "{chu}"', http=400)


def ep_gio(v):
	"""`(p->>'posted_at')::timestamptz`: thiếu / null → None (nơi gọi lấy now()); chuỗi sai (kể cả '') → 22007 thô. Có múi giờ → giữ (nơi gọi đổi
	về giờ site); không múi giờ → hiểu là giờ site (⚠K nhẹ: nppsale hiểu theo TimeZone phiên = UTC — giao diện luôn gửi kèm múi giờ)."""
	chu = _chu_json(v)
	if chu is None:
		return None
	try:
		return datetime.fromisoformat(chu.strip())
	except ValueError:
		raise LoiCong("22007", f'invalid input syntax for type timestamp with time zone: "{chu}"', http=400) from None


@dataclass
class DongNhap:
	n: int  # vị trí 1-based trong mảng `lines`
	hang: str | None
	ma_lo: str | None  # trim(batch_code) — trống → None (nơi gọi đặt LOT-<mã>-<n>)
	nsx: date | None
	han: date | None  # trống = None; `2099-12-31` giữ nguyên — nơi gọi bỏ khi mặt hàng không quản lý hạn (`han_lo`)
	vi_tri: str | None
	dv: str  # COALESCE(unit_name, '')
	sl_gd: Decimal | None  # qty_tx
	he_so: Decimal  # COALESCE(conv, 1)
	sl_cs: Decimal  # base_qty
	gia_von: Decimal  # COALESCE(base_cost, 0) — mỗi đơn vị CƠ SỞ


@dataclass
class TaiNhap:
	ma: str | None  # NULLIF(trim(entry_code), '')
	luc: datetime | None  # posted_at (None → now())
	ncc: str | None  # NULLIF(supplier_id, '')
	no: Decimal  # COALESCE(payable.amount, 0)
	so_hd: str | None  # NULLIF(trim(payable.invoice_number), '')
	vung: str  # COALESCE(NULLIF(trim(warehouse_zone), ''), 'sale')
	ghi_chu: str | None  # NULLIF(notes, '')
	dong: list = field(default_factory=list)  # mảng `lines` thô (kiểm từng dòng ở `doc_dong_nhap`)
	co_mang: bool = False  # `jsonb_typeof(p->'lines') = 'array'`


def doc_tai_nhap(p) -> TaiNhap:
	"""Khối DECLARE của `post_stock_import`: ép kiểu `posted_at` / `payable.amount` (sai → 22007 / 22P02 TRƯỚC cả FORBIDDEN — nơi gọi gọi hàm này
	trước khi kiểm vai). `p` không phải object → mọi khoá NULL. `supplier_id` của Frappe không phải uuid (tên NCC-…): không ép."""
	p = p if isinstance(p, dict) else {}
	tra = p.get("payable") if isinstance(p.get("payable"), dict) else {}
	ma = _chu_json(p.get("entry_code"))
	ma = ma.strip() if ma is not None else None
	vung = _chu_json(p.get("warehouse_zone"))
	vung = vung.strip() if vung is not None else ""
	ncc = _chu_json(p.get("supplier_id"))
	so_hd = _chu_json(tra.get("invoice_number"))
	so_hd = so_hd.strip() if so_hd is not None else None
	ghi = _chu_json(p.get("notes"))
	luc = ep_gio(p.get("posted_at"))
	no = ep_so(tra.get("amount"), Decimal(0))
	dong = p.get("lines")
	return TaiNhap(ma=ma or None, luc=luc, ncc=ncc or None, no=no, so_hd=so_hd or None, vung=vung or "sale", ghi_chu=ghi or None,
		dong=dong if isinstance(dong, list) else [], co_mang=isinstance(dong, list))


def kiem_dau_nhap(t: TaiNhap) -> None:
	"""Bước 3–4 (sau cửa vai): thiếu mã → thiếu dòng. Bước 5 (NCC có trong sổ) do nơi gọi kiểm, rồi `kiem_vung_no`."""
	if t.ma is None:
		raise NppLoi(THIEU_MA)
	if not t.co_mang or not t.dong:
		raise NppLoi(THIEU_DONG)


def kiem_vung_no(t: TaiNhap) -> None:
	"""Bước 6–7: vùng ngoài {sale, date}; tiền công nợ âm."""
	if t.vung not in VUNG:
		raise NppLoi(SAI_VUNG)
	if t.no < 0:
		raise NppLoi(NO_AM)


def doc_dong_nhap(n: int, l, co_hang) -> DongNhap:
	"""Một dòng theo thứ tự mảng (bước 9 rồi phần ép kiểu của lệnh INSERT): mặt hàng không có → ORG_MISMATCH (42501); `base_qty` thiếu / ≤ 0 →
	BAD_PAYLOAD; `base_cost` < 0 → BAD_PAYLOAD; ngày SX / hạn / `qty_tx` / `conv` sai kiểu → 22007 / 22P02. `co_hang(mã)` → bool."""
	l = l if isinstance(l, dict) else {}
	hang = _chu_json(l.get("product_id"))
	if hang is None or not co_hang(hang):
		raise loi_hang_khac(hang)
	sl = ep_so(l.get("base_qty"), Decimal(0))
	if sl <= 0:
		raise loi_dong_sl(n)
	gia = ep_so(l.get("base_cost"), Decimal(0))
	if gia < 0:
		raise loi_dong_gia_am(n)
	ma_lo = _chu_json(l.get("batch_code"))
	ma_lo = (ma_lo.strip() or None) if ma_lo is not None else None
	nsx = ep_ngay(l.get("manufactured_at"))
	han = ep_ngay(l.get("expires_at"))
	vi_tri = _chu_json(l.get("location"))
	vi_tri = (vi_tri.strip() or None) if vi_tri is not None else None
	sl_gd = ep_so(l.get("qty_tx"))
	he_so = ep_so(l.get("conv"), Decimal(1))
	return DongNhap(n=n, hang=hang, ma_lo=ma_lo, nsx=nsx, han=han, vi_tri=vi_tri, dv=_chu_json(l.get("unit_name")) or "", sl_gd=sl_gd,
		he_so=he_so, sl_cs=sl, gia_von=gia)


def han_lo(han: date | None, co_han: bool) -> date | None:
	"""Hạn ghi vào Batch: `2099-12-31` (quy ước "không hạn" của nppsale — màn Excel / bước dựng gửi thẳng) với mặt hàng KHÔNG quản lý hạn → trống
	(CFD-10 bỏ hạn giả; cổng `batches` trả lại `2099-12-31`); mặt hàng có hạn giữ số gửi lên (để trống thì lõi tự tính ngày SX + hạn dùng —
	`batch.py` `set_expiry_date`, §7.3 điểm 5 — đã đo M4)."""
	if han is not None and not co_han and str(han) == HAN_KHONG:
		return None
	return han


def ma_lo_tu_dat(ma_phieu: str, n: int) -> str:
	"""`'LOT-' || v_code || '-' || (v_n + 1)` — KHÔNG đệm số (khác lô phiếu nhập `<PN>-NNN`)."""
	return f"LOT-{ma_phieu}-{n}"


def la_ton_dau_ky(ma_phieu: str | None) -> bool:
	"""§7.3 điểm 4 (đề xuất): tải trọng không có cờ — hộp nhập Excel sản phẩm đặt mã `DK-YYYYMMDD-NNNN` (`opening-stock-plan.ts::openingEntryCode`)."""
	return bool(ma_phieu) and ma_phieu.startswith("DK-")


def sl_dong_se(d: DongNhap) -> tuple[Decimal, Decimal]:
	"""(SL, hệ số) của dòng Stock Entry Detail sao cho SL × hệ số = SL CƠ SỞ (`base_qty` — số vào lô): `qty_tx` × `conv` khớp → giữ đơn vị giao dịch;
	lệch / thiếu → SL cơ sở với hệ số 1 (nơi gọi dùng đơn vị cơ sở của mặt hàng). nppsale lưu hai cột rời (`qty_in_transaction_uom`,
	`qty_in_base_uom`) nên chịu được tải trọng lệch."""
	if d.sl_gd is not None and d.he_so > 0 and d.sl_gd * d.he_so == d.sl_cs:
		return d.sl_gd, d.he_so
	return d.sl_cs, Decimal(1)


# ------------------------------------------------------------------------------------------------ 4. ghi thẳng phiếu kho / dòng (mig 170)
NHAP_PHAI_NHAP = "SO_KHO_KHOA: phiếu kho lập từ màn hình phải là phiếu NHÁP — ghi sổ đi qua nút Duyệt / Hoàn thành."
CHI_SUA_GHI_CHU = "SO_KHO_KHOA: phiếu đã ghi sổ chỉ sửa được ghi chú."
# đặc tả §4.5 ("dòng nguồn HĐ / PI → cấm, đổi ở chứng từ gốc" — câu MỚI, Q9): phiếu kho của HĐ / tờ ghi có / phiếu nhập / trả NCC là CHÍNH chứng từ
# (⚠K §7.2 #14) — ghi chú phiếu kho nppsale là cột riêng, ở Frappe là ghi chú của chứng từ (sửa ở đây là đổi ghi chú hoá đơn / phiếu nhập)
SUA_O_CHUNG_TU_GOC = "SO_KHO_KHOA: phiếu kho này là chính hoá đơn / phiếu nhập / phiếu trả NCC — sửa ghi chú ở chứng từ gốc."


def loi_doi_trang_thai(cu: str, moi) -> NppLoi:
	return NppLoi(f"SO_KHO_KHOA: không đổi thẳng trạng thái phiếu kho ({cu} → {'<NULL>' if moi is None else moi}) — ghi sổ / huỷ đi qua nút Duyệt / "
		"Huỷ phiếu để kho đổi theo.")


def _chu_tt(tt: str) -> str:
	return "ghi sổ" if tt == "posted" else "huỷ"


def loi_xoa_khong_nhap(ma: str, tt: str) -> NppLoi:
	return NppLoi(f"SO_KHO_KHOA: chỉ xoá được phiếu NHÁP. Phiếu {ma} đã {_chu_tt(tt)}, dùng Huỷ phiếu để hàng về lại kho.")


def loi_dong_khoa(tt: str) -> NppLoi:
	return NppLoi(f"SO_KHO_KHOA: phiếu đã {_chu_tt(tt)} — không sửa dòng hàng được nữa.")


def kiem_dong_phieu_kho(dong: Iterable) -> None:
	"""Cổng ghi nháp phiếu xuất lẻ / chuyển kho / nhập kho (§7.3 điểm 23 — đề xuất; nppsale nhận dòng SL ≤ 0: lượt một tính, lượt hai bỏ — V44b):
	từng dòng theo thứ tự trên phiếu, SL CƠ SỞ ≤ 0 → câu của `sua_phieu_nhap` (Stock Entry Detail không biểu diễn được dòng 0 / âm)."""
	from nppsale.luat.kho_mua import loi_dong_so_luong

	for stt, sl in enumerate(dong, 1):
		if so(sl) <= 0:
			raise loi_dong_so_luong(stt)
