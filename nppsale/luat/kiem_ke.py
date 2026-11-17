"""Luật thuần của KIỂM KÊ (P4 — mốc M6; đặc tả kho_mua §3.17, §3.18, §2.2, §2.5, §7.1 #1 / #11, §7.3 điểm 15; blueprint 02 §4.4 `NPP Kiem Ke`,
§4.5 `NPP Phieu Chi`) — không import frappe; bài: nppsale.tests.test_luat_kiem_ke.

1. Câu lỗi NGUYÊN VĂN của hai hàm nppsale (thân đang chạy — scratchpad kho_mua/src/post_stock_adjustment.sql, reject_stock_adjustment.sql): hai hàm
   KHÁC chữ cho cùng mã — `post_stock_adjustment` (mig 123 / 228): `ENTRY_NOT_FOUND` / `ORG_MISMATCH` KHÔNG dấu chấm, `FORBIDDEN` P0001;
   `reject_stock_adjustment` (mig 170): có dấu chấm, `ORG_MISMATCH` / `FORBIDDEN` 42501. Số trong câu theo §2.5: tồn lô numeric(18,6) (`so6`), số phiếu
   trừ = `-quantity` như đã lưu (`so_pg`); "chỉ còn" của NOT_ENOUGH_STOCK = `-quantity - v_left` (đã trừ ít nhất một lô → scale 6; không lô nào → 0
   theo scale của SL: `0`, `0.0`); giờ `ALREADY_POSTED` `HH24:MI DD/MM/YYYY` — giờ VN của site (❓ §7.3 điểm 15 — đề xuất; nppsale giờ phiên UTC).
2. Áp chênh lệch (`duyet` — §3.17 bước 7 + Frappe bước 3): từng dòng theo thứ tự trên phiếu (`idx`; nppsale `ORDER BY sel.id` — uuid), bỏ dòng 0; dòng
   sau thấy phần dòng trước đã cộng / trừ (nppsale cập nhật `qty_on_hand` ngay trong vòng):
   - dòng CÓ lô (`lo` + `kho`): lô không còn → BATCH_GONE; tồn lô tại kho + chênh < 0 → STOCK_MOVED (không kẹp — mig 123 "KHÔNG KẸP ÂM TRONG IM LẶNG");
     giá = giá dòng, = 0 thì giá vốn lô; chạm +1;
   - HỤT không lô: lô có tồn > 0 của mặt hàng ở CẢ HAI kho, MỌI trạng thái (Batch tắt cũng lấy), hạn gần trước (trống xếp cuối), hoà hạn → mã lô
     (⚠K nhẹ: nppsale hoà hạn → uuid dòng lô; lô có ở hai kho → kho bán trước); điền lô / kho đầu tiên đã đụng vào dòng; giá = giá dòng, = 0 thì giá
     lô ĐẦU TIÊN có giá ≠ 0 đã đụng (MỘT giá cho cả dòng — §7.1 #11); mỗi lô chạm +1; còn thiếu → NOT_ENOUGH_STOCK;
   - THỪA không lô: lô hạn XA nhất của mặt hàng bất kể tồn (trống xếp cuối — `lo_nhan_thua`), không có Batch nào → NO_BATCH; kho nhận = kho lô đang có
     tồn lớn nhất, không đâu có → kho tạo lô (`npp_kho_tao`, trống → kho bán) (❓ §7.3 điểm 15 — đề xuất); chạm +1;
   - hàng KHÔNG lô (câu 14 B — nppsale không có): lô ảo `~<mã>::<vùng>` = Bin của kho; dòng có kho → như dòng có lô (STOCK_MOVED); không kho → hụt lấy
     kho bán rồi kho date, thừa vào kho có tồn lớn nhất (không đâu có → kho bán); KHÔNG bao giờ âm (kiểm kê không áp vượt tồn — §2.6).
   Cộng dồn: hụt `shrink_qty += −q`, `shrink_value += −q × giá`; thừa `surplus_qty += q`, `surplus_value += q × giá` (luật nppsale — số trả về và tiền
   phiếu chi hao hụt; sổ kho / GL của phiếu `DCK-` đúng từng lô — §7.3 điểm 15 đề xuất).
3. Phiếu chi hao hụt (§3.17 bước 8 + Frappe bước 6) + khoá phiếu nguồn kiểm kê (BP §7.1 điểm 18 — đề xuất, câu MỚI: quyết định tạm Q9); ghi chú từ
   chối (`COALESCE(notes || E'\\n', '') || 'Từ chối: ' || COALESCE(NULLIF(p_reason, ''), '(không ghi lý do)')`).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.luat.kho_mua import LoKho, gio_dmy, lo_nhan_thua, so, so6, so_pg

DT = "NPP Kiem Ke"
NGUON_KIEM_KE = "stocktake"  # `expenses.source_type` của phiếu chi hao hụt
MA_DANH_MUC_HAO_HUT = "COGS_ADJ"
SE_LOAI = "dieu_chinh_kiem_ke"  # Stock Entry.npp_loai của hai phiếu `DCK-`
TRANG_THAI = ("draft", "posted", "cancelled")

# ------------------------------------------------------------------------------------------------ 1. câu lỗi — post_stock_adjustment (mig 123 / 228)
FORBIDDEN_KHOA = "FORBIDDEN: tài khoản chưa gắn đơn vị, hoặc đã bị khoá"
KHONG_THAY = "ENTRY_NOT_FOUND: không tìm thấy phiếu kiểm kê"
KHAC_NPP = "ORG_MISMATCH: phiếu không thuộc đơn vị của bạn"
FORBIDDEN_DUYET = "FORBIDDEN: bạn không có quyền duyệt điều chỉnh kho"


def loi_da_duyet(ma: str, luc) -> NppLoi:
	"""`ALREADY_POSTED: phiếu % đã được duyệt lúc %` — `to_char(posted_at, 'HH24:MI DD/MM/YYYY')`; giờ VN của site (❓ §7.3 điểm 15 — đề xuất)."""
	return NppLoi(f"ALREADY_POSTED: phiếu {ma} đã được duyệt lúc {gio_dmy(luc) if luc else '<NULL>'}")


def loi_sai_trang_thai(ma: str, tt: str) -> NppLoi:
	return NppLoi(f"BAD_STATUS: phiếu {ma} đang ở trạng thái {tt}, không duyệt được")


def loi_lo_mat(ten: str) -> NppLoi:
	"""BATCH_GONE (thực tế không xảy ra — khoá ngoại / liên kết chặn xoá lô có dòng trỏ)."""
	return NppLoi(f'BATCH_GONE: lô của dòng "{ten}" không còn tồn tại')


def loi_ton_doi(ten: str, ton, chenh) -> NppLoi:
	"""STOCK_MOVED: tồn lô `qty_on_hand` numeric(18,6); phiếu trừ `-l.quantity` (đúng số đã lưu)."""
	return NppLoi(f'STOCK_MOVED: "{ten}" tồn hiện {so6(ton)}, phiếu trừ {so_pg(-so(chenh))} — tồn đã đổi từ lúc kiểm đếm. Kiểm đếm lại rồi lập '
		"phiếu mới.")


def chi_con(chenh, da_tru, co_lo: bool) -> str:
	""""chỉ còn" = `-l.quantity - v_left`: đã trừ ít nhất một lô (mỗi lần trừ trọn tồn numeric(18,6) của lô) → scale 6; không lô nào → 0 với scale của
	SL (`0`, `0.0`)."""
	if co_lo:
		return so6(da_tru)
	e = so(chenh).as_tuple().exponent
	return so_pg(Decimal(0).scaleb(e) if isinstance(e, int) and e < 0 else Decimal(0))


def loi_thieu(ten: str, chenh, da_tru, co_lo: bool) -> NppLoi:
	return NppLoi(f'NOT_ENOUGH_STOCK: "{ten}" chỉ còn {chi_con(chenh, da_tru, co_lo)} để trừ, phiếu trừ {so_pg(-so(chenh))} — kiểm đếm lại.')


def loi_chua_co_lo(ten: str) -> NppLoi:
	return NppLoi(f'NO_BATCH: "{ten}" chưa có lô nào để ghi phần thừa. Tạo lô cho sản phẩm này trước.')


# ------------------------------------------------------------------------------------------------ câu lỗi — reject_stock_adjustment (mig 170)
KHONG_THAY_TU_CHOI = "ENTRY_NOT_FOUND: không tìm thấy phiếu kiểm kê."
KHAC_NPP_TU_CHOI = "ORG_MISMATCH: phiếu không thuộc đơn vị của bạn."  # 42501 (`IS DISTINCT FROM user_org_id()` — tài khoản khoá cũng vào đây)
FORBIDDEN_TU_CHOI = "FORBIDDEN: bạn không có quyền duyệt / từ chối điều chỉnh kho."  # 42501
SAI_LOAI = "BAD_TYPE: đây không phải phiếu kiểm kê."
DA_DUYET_TU_CHOI = "ALREADY_POSTED: phiếu đã duyệt — không từ chối được nữa."


def ghi_chu_tu_choi(cu: str | None, ly_do: str | None) -> str:
	"""`COALESCE(notes || E'\\n', '') || 'Từ chối: ' || COALESCE(NULLIF(p_reason, ''), '(không ghi lý do)')` — ghi chú NULL không xuống dòng (ghi chú
	'' vẫn xuống dòng như Postgres); lý do NULL / '' → "(không ghi lý do)" (khác `cancel_stock_entry`: lý do '' giữ rỗng)."""
	return ("" if cu is None else cu + "\n") + "Từ chối: " + (ly_do if ly_do not in (None, "") else "(không ghi lý do)")


# ------------------------------------------------------------------------------------------------ 2. áp chênh lệch
@dataclass
class LoTT:
	"""Một Batch của mặt hàng trên phiếu (MỌI trạng thái — Batch tắt cũng lấy, như "mọi trạng thái" của mig 123)."""
	ma: str
	hang: str
	han: date | str | None = None  # None = không hạn (xếp cuối)
	gia: Decimal = Decimal(0)  # giá vốn mỗi ĐV cơ sở của lô (cổng `batches.unit_cost`: bình quân phần nhập; lô rỗng → `npp_gia_von_lo_rong`)
	kho_tao: str | None = None  # `npp_kho_tao` — kho của dòng "lô chưa phát sinh" ở cổng `batches`


@dataclass
class DongKK:
	stt: int  # idx
	ten_dong: str  # name của NPP Kiem Ke Dong
	hang: str
	ten: str  # tên hàng in trong câu lỗi (`COALESCE(p.name, product_id)`)
	co_lo: bool  # Item.has_batch_no
	lo: str | None
	kho: str | None
	chenh: Decimal
	gia: Decimal = Decimal(0)  # `gia_von` của dòng (`COALESCE(unit_cost, 0)`)


@dataclass
class BuocKho:
	"""Một lượt cộng / trừ kho của phiếu `DCK-`: hụt → Material Issue, thừa → Material Receipt."""
	ten_dong: str
	hang: str
	lo: str | None  # None = hàng không lô
	kho: str
	sl: Decimal  # dương, đơn vị cơ sở
	nhap: bool


@dataclass
class KetQuaKK:
	buoc: list = field(default_factory=list)
	dien: dict = field(default_factory=dict)  # tên dòng → (lô, kho) điền vào dòng chưa có
	cham: int = 0  # batches_touched
	hut_sl: Decimal = Decimal(0)
	hut_gt: Decimal = Decimal(0)
	thua_sl: Decimal = Decimal(0)
	thua_gt: Decimal = Decimal(0)


def _han(x) -> str:
	return "" if x is None else str(x)[:10]


class KhoKK:
	"""Tồn trong lượt duyệt (cập nhật ngay khi áp từng dòng — dòng sau thấy dòng trước): lô thật theo (mã lô, kho), hàng không lô theo (mặt hàng,
	kho) — Bin. `kho_ban` / `kho_date`: thứ tự kho khi hoà (kho bán trước) và kho mặc định."""

	def __init__(self, lo: Mapping[str, LoTT], ton_lo: Mapping[tuple, Decimal], ton_ao: Mapping[tuple, Decimal], gia_ao: Mapping[tuple, Decimal],
			kho_ban: str, kho_date: str | None):
		self.lo = dict(lo)
		self.ton_lo = {k: so(v) for k, v in ton_lo.items()}
		self.ton_ao = {k: so(v) for k, v in ton_ao.items()}
		self.gia_ao = {k: so(v) for k, v in gia_ao.items()}
		self.kho_ban, self.kho_date = kho_ban, kho_date

	def thu_kho(self, kho: str) -> int:
		return 0 if kho == self.kho_ban else 1 if kho == self.kho_date else 2

	def kho_nhieu_nhat(self, ton: Mapping[str, Decimal], mac: str | None) -> str:
		"""Kho có tồn lớn nhất (> 0; hoà → kho bán trước), không đâu có → `mac` (trống → kho bán)."""
		co = sorted(((t, k) for k, t in ton.items() if t > 0), key=lambda x: (-x[0], self.thu_kho(x[1]), x[1]))
		return co[0][1] if co else (mac or self.kho_ban)

	def ton_cua_lo(self, ma: str) -> dict[str, Decimal]:
		return {k: t for (m, k), t in self.ton_lo.items() if m == ma}

	def ton_cua_hang_ao(self, hang: str) -> dict[str, Decimal]:
		return {k: t for (h, k), t in self.ton_ao.items() if h == hang}


def _gia(v_gia: Decimal, gia_lo) -> Decimal:
	"""`IF v_cost = 0 THEN v_cost := b.unit_cost` — chỉ lấy giá lô khi giá đang có = 0."""
	return so(gia_lo) if v_gia == 0 else v_gia


def duyet(dong: Iterable[DongKK], kho: KhoKK) -> KetQuaKK:
	"""Áp chênh lệch các dòng (đã xếp theo `stt`) lên `kho` (cập nhật tại chỗ) → lượt cộng / trừ kho + lô / kho điền vào dòng + số trả về. Ném NppLoi
	đúng câu nppsale ở dòng hỏng đầu tiên (nơi gọi lui cả lượt)."""
	kq = KetQuaKK()
	for d in sorted(dong, key=lambda x: x.stt):
		q = so(d.chenh)
		if q == 0:
			continue  # `CONTINUE WHEN COALESCE(l.quantity, 0) = 0` — không tính lô chạm
		v_gia = so(d.gia)
		if d.lo:
			v_gia = _dong_co_lo(d, q, v_gia, kho, kq)
		elif not d.co_lo:
			v_gia = _dong_khong_lo(d, q, v_gia, kho, kq)
		elif q < 0:
			v_gia = _hut_khong_lo(d, q, v_gia, kho, kq)
		else:
			v_gia = _thua_khong_lo(d, q, v_gia, kho, kq)
		if q < 0:
			kq.hut_sl += -q
			kq.hut_gt += -q * v_gia
		else:
			kq.thua_sl += q
			kq.thua_gt += q * v_gia
	return kq


def _dong_co_lo(d: DongKK, q: Decimal, v_gia: Decimal, kho: KhoKK, kq: KetQuaKK) -> Decimal:
	lo = kho.lo.get(d.lo)
	if lo is None:
		raise loi_lo_mat(d.ten)
	k = d.kho or kho.kho_nhieu_nhat(kho.ton_cua_lo(lo.ma), lo.kho_tao)
	ton = kho.ton_lo.get((lo.ma, k), Decimal(0))
	if ton + q < 0:
		raise loi_ton_doi(d.ten, ton, q)
	kho.ton_lo[(lo.ma, k)] = ton + q
	kq.cham += 1
	kq.buoc.append(BuocKho(d.ten_dong, lo.hang, lo.ma, k, abs(q), q > 0))
	if not d.kho:
		kq.dien[d.ten_dong] = (lo.ma, k)
	return _gia(v_gia, lo.gia)


def _dong_khong_lo(d: DongKK, q: Decimal, v_gia: Decimal, kho: KhoKK, kq: KetQuaKK) -> Decimal:
	"""Hàng không lô — lô ảo mỗi kho = Bin (không bao giờ âm)."""
	ton = kho.ton_cua_hang_ao(d.hang)
	if d.kho:
		t = ton.get(d.kho, Decimal(0))
		if t + q < 0:
			raise loi_ton_doi(d.ten, t, q)
		kho.ton_ao[(d.hang, d.kho)] = t + q
		kq.cham += 1
		kq.buoc.append(BuocKho(d.ten_dong, d.hang, None, d.kho, abs(q), q > 0))
		return _gia(v_gia, kho.gia_ao.get((d.hang, d.kho), 0))
	if q > 0:
		k = kho.kho_nhieu_nhat(ton, None)
		kho.ton_ao[(d.hang, k)] = ton.get(k, Decimal(0)) + q
		kq.cham += 1
		kq.buoc.append(BuocKho(d.ten_dong, d.hang, None, k, q, True))
		kq.dien[d.ten_dong] = (None, k)
		return _gia(v_gia, kho.gia_ao.get((d.hang, k), 0))
	con, da_tru, dau = -q, Decimal(0), None
	for k in sorted((k for k, t in ton.items() if t > 0), key=lambda x: (kho.thu_kho(x), x)):
		if con <= 0:
			break
		lay = min(ton[k], con)
		kho.ton_ao[(d.hang, k)] = ton[k] - lay
		con -= lay
		da_tru += lay
		kq.cham += 1
		kq.buoc.append(BuocKho(d.ten_dong, d.hang, None, k, lay, False))
		v_gia = _gia(v_gia, kho.gia_ao.get((d.hang, k), 0))
		dau = dau or k
	if con > 0:
		raise loi_thieu(d.ten, q, da_tru, dau is not None)
	kq.dien[d.ten_dong] = (None, dau)
	return v_gia


def thu_tu_hut(lo: LoTT, kho: str, thu_kho: int) -> tuple:
	"""Kiểm kê hụt không lô: `ORDER BY expires_at NULLS LAST, id` — hoà hạn → mã lô, rồi kho bán trước (một Batch ở hai kho)."""
	return (lo.han is None, _han(lo.han), lo.ma, thu_kho, kho)


def _hut_khong_lo(d: DongKK, q: Decimal, v_gia: Decimal, kho: KhoKK, kq: KetQuaKK) -> Decimal:
	ung = [(kho.lo[m], k) for (m, k), t in kho.ton_lo.items() if t > 0 and m in kho.lo and kho.lo[m].hang == d.hang]
	con, da_tru, dau = -q, Decimal(0), None
	for lo, k in sorted(ung, key=lambda x: thu_tu_hut(x[0], x[1], kho.thu_kho(x[1]))):
		if con <= 0:
			break
		t = kho.ton_lo[(lo.ma, k)]
		lay = min(t, con)
		kho.ton_lo[(lo.ma, k)] = t - lay
		con -= lay
		da_tru += lay
		kq.cham += 1
		kq.buoc.append(BuocKho(d.ten_dong, lo.hang, lo.ma, k, lay, False))
		v_gia = _gia(v_gia, lo.gia)
		dau = dau or (lo.ma, k)
	if con > 0:
		raise loi_thieu(d.ten, q, da_tru, dau is not None)
	kq.dien[d.ten_dong] = dau
	return v_gia


def _thua_khong_lo(d: DongKK, q: Decimal, v_gia: Decimal, kho: KhoKK, kq: KetQuaKK) -> Decimal:
	ds = [x for x in kho.lo.values() if x.hang == d.hang]
	ma = lo_nhan_thua([LoKho(ma=x.ma, ton=Decimal(0), han=x.han) for x in ds])
	if ma is None:
		raise loi_chua_co_lo(d.ten)
	lo = kho.lo[ma]
	k = kho.kho_nhieu_nhat(kho.ton_cua_lo(ma), lo.kho_tao)
	kho.ton_lo[(ma, k)] = kho.ton_lo.get((ma, k), Decimal(0)) + q
	kq.cham += 1
	kq.buoc.append(BuocKho(d.ten_dong, lo.hang, ma, k, q, True))
	kq.dien[d.ten_dong] = (ma, k)
	return _gia(v_gia, lo.gia)


def ket_qua(kq: KetQuaKK, phieu_chi: str | None) -> list[dict]:
	"""`RETURNS TABLE(batches_touched, shrink_qty, shrink_value, surplus_qty, surplus_value, expense_id)` — mảng MỘT dòng (giao diện đọc `data[0]`)."""
	return [{"batches_touched": kq.cham, "shrink_qty": float(kq.hut_sl), "shrink_value": float(kq.hut_gt), "surplus_qty": float(kq.thua_sl),
		"surplus_value": float(kq.thua_gt), "expense_id": phieu_chi}]


# ------------------------------------------------------------------------------------------------ 3. phiếu chi hao hụt
def chon_danh_muc(ds: Iterable[tuple[str, str]]) -> str | None:
	"""Danh mục của phiếu chi hao hụt: mã `COGS_ADJ`; không có thì danh mục ĐẦU theo mã; không có nữa → None. `ds`: (tên, mã)."""
	ds = list(ds)
	for ten, ma in ds:
		if ma == MA_DANH_MUC_HAO_HUT:
			return ten
	ds.sort(key=lambda x: (x[1] or "", x[0]))
	return ds[0][0] if ds else None


def dien_giai_hao_hut(ma_phieu: str) -> str:
	return f"Hao hụt từ phiếu kiểm kê {ma_phieu}"


# Phiếu chi nguồn kiểm kê chỉ sửa được diễn giải / số tham chiếu (BP §7.1 điểm 18 — đề xuất): mọi trường dưới khoá; không xoá
TRUONG_KHOA_PHIEU_CHI = ("so_tien", "danh_muc", "ngay_chi", "nguon_loai", "kiem_ke", "chung_tu_kho")


def loi_phieu_chi_khoa(kiem_ke: str | None) -> str:
	return (f"PHIEU_CHI_KIEM_KE_KHOA: phiếu chi hao hụt của phiếu kiểm kê {kiem_ke or '<NULL>'} chỉ sửa được diễn giải / số tham chiếu — sai thì kiểm "
		"kê lại.")


def loi_phieu_chi_khong_xoa(kiem_ke: str | None) -> str:
	return (f"PHIEU_CHI_KIEM_KE_KHOA: không xoá được phiếu chi hao hụt của phiếu kiểm kê {kiem_ke or '<NULL>'} — phiếu kiểm kê đã duyệt không đảo "
		"được.")


# ------------------------------------------------------------------------------------------------ cổng: `batch_id` của dòng kiểm kê
def tach_id_lo(batch_id: str | None) -> tuple[str | None, str | None, bool]:
	"""Id cổng `batches` → (mã lô | mã hàng của lô ảo, vùng, là lô ảo): `<lô>::<vùng>`, `~<mã hàng>::<vùng>`; id không có `::` → (id, None, False)."""
	if batch_id in (None, ""):
		return None, None, False
	ao = batch_id.startswith("~")
	ma, sep, vung = (batch_id[1:] if ao else batch_id).rpartition("::")
	if not sep:
		return (batch_id[1:] if ao else batch_id), None, ao
	return ma, vung, ao
