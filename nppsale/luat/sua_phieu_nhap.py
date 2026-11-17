"""Luật thuần của SỬA PHIẾU NHẬP ĐÃ HOÀN THÀNH (P4 — mốc M7; đặc tả kho_mua §3.3, §7.2 #3, §7.3 điểm 7 / 34; nppsale hàm `sua_phieu_nhap`
mig 235 / 236 — thân hàm ở scratchpad kho_mua/src/sua_phieu_nhap.sql) — không import frappe; bài: nppsale.tests.test_luat_sua_phieu_nhap.

1. Đọc tham số đúng ngữ nghĩa jsonb của nppsale (bước 5–9): `p_head->>'k'` / `e.v->>'k'` (`kho_mua.chu_json`), `NULLIF(…, '')`, ép kiểu
   `::numeric` / `::date` (sai → nppsale lỗi Postgres thô 22P02 — ⚠K §7.3 điểm 7 đề xuất: `BAD_PAYLOAD: dữ liệu phiếu sai kiểu.`); thứ tự lỗi như hàm
   gốc: dòng trống → NCC (ở method — cần sổ) → kho → ép kiểu giảm / thuế gõ tay → ép kiểu dòng → bốn kiểm của TỪNG dòng → … → ngày HĐ (ép kiểu ở câu
   UPDATE cuối hàm gốc — lỗi ngày ra SAU mọi lỗi khác).
2. Bốn kiểm của một dòng (bước 10, đủ bốn rồi mới sang dòng sau): mặt hàng → đơn vị → số lượng / hệ số → giá / giảm âm.
3. Ghép dòng mới ↔ lô cũ + `DA_XUAT_NHIEU_HON` (bước 14–16): `kho_mua.ghep_dong_lo`. "Đã xuất" của lô trên Frappe (`da_xuat_lo`): nppsale lật cờ vùng
   tại chỗ khi rà soát kho date (không "xuất") — Frappe rà soát = phiếu `CKL-` `chuyen_date_tu_dong` (⚠K §7.2 #7) nên phần đã bị phiếu ấy chuyển
   sang kho date (còn nằm ở đó) KHÔNG tính là đã xuất; chuyển kho tay vẫn tính (nppsale: lô nguồn giảm).
4. Rẽ nhánh (CFD-06, BP §5.9 / §5.10): không lô nào đã xuất → nhánh A (huỷ + amend `PN-xxxx-n`, giữ lô); có lô đã xuất → nhánh B CHỈ SỬA GIÁ
   (`kiem_chi_sua_gia` — đổi mặt hàng / ĐV / SL / hệ số / số dòng / NCC / kho → `PHIEU_DA_XUAT_CHI_SUA_GIA`, mã + câu đề xuất §3.3 chờ chốt).
   Nhánh A đổi NCC khi tờ đã có tiền trả → `NCC_DA_TRA_TIEN` (§7.3 điểm 34 đề xuất — lõi không phân bổ chéo NCC).
5. Nhánh B: chênh tiền hàng từng dòng → Landed Cost Voucher `SGN-` tách hai chiều (`tach_lcv` — lõi bắt mọi `applicable_charges` cùng dấu tổng,
   tổng ≠ 0); bút toán `DCN-` (`but_toan_dcn` — Phải trả NCC ↔ TK trung gian sửa giá ↔ thuế đầu vào ↔ giảm đầu phiếu, cân Nợ / Có); `npp_sua_gia`
   (`json_sua_gia` — số hiện hành sau sửa, cổng phủ lên phiếu / dòng).
6. Số lô đổi giá (`doi_gia_lo` của kết quả): lô cũ giữ lại mà giá vốn mỗi đơn vị cơ sở đổi (`IS DISTINCT FROM` — so Decimal không làm tròn như
   numeric của nppsale); lô mới không tính.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.luat import kho_mua as K
from nppsale.luat.cong_no_ncc import btrim

# ------------------------------------------------------------------------------------------------ câu lỗi (nguyên văn hàm gốc + mã mới đề xuất)
PHIEU_KHONG_TON_TAI = "PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu nhập này."
PHIEU_CHUA_HOAN_THANH = "PHIEU_CHUA_HOAN_THANH: Chỉ sửa tại chỗ phiếu nhập đã hoàn thành (phiếu tạm lưu như thường)."
PHIEU_TRONG = "PHIEU_TRONG: Phiếu nhập phải có ít nhất một dòng hàng."
NCC_KHONG_HOP_LE = "NCC_KHONG_HOP_LE: Nhà cung cấp không thuộc đơn vị."
KHO_KHONG_HOP_LE = "KHO_KHONG_HOP_LE: Kho nhập không hợp lệ."
# §7.3 điểm 7 (đề xuất — nppsale ra lỗi Postgres thô 22P02 `invalid input syntax for type …`)
BAD_PAYLOAD = "BAD_PAYLOAD: dữ liệu phiếu sai kiểu."


def loi_hang(stt: int) -> NppLoi:
	return NppLoi(f"HANG_KHONG_HOP_LE: Dòng {stt} — mặt hàng không thuộc đơn vị.")


def loi_don_vi(stt: int) -> NppLoi:
	return NppLoi(f"DON_VI_TRONG: Dòng {stt} chưa có đơn vị tính.")


def loi_chi_sua_gia(chung_tu: Iterable[str]) -> NppLoi:
	"""§3.3 nhánh B bước 1 (đề xuất, chờ chốt mã + câu — §7.3 điểm 7): phiếu có lô đã xuất chỉ sửa được giá. `chung_tu` = các chứng từ đã lấy hàng từ
	lô của phiếu (HĐ bán, xuất lẻ, trả NCC, chuyển kho tay…) theo tên."""
	ds = ", ".join(sorted(dict.fromkeys(x for x in chung_tu if x))) or "chứng từ khác"
	return NppLoi(f"PHIEU_DA_XUAT_CHI_SUA_GIA: Lô của phiếu đã xuất ở {ds} — chỉ sửa được giá; muốn đổi số lượng / mặt hàng / NCC / kho thì huỷ các HĐ "
		"đã lấy lô hoặc lập phiếu trả hàng NCC / điều chỉnh kho.")


def loi_ncc_da_tra_tien(tien) -> NppLoi:
	"""§7.3 điểm 34 (soát thiếu S3 — đề xuất, chờ chốt): đổi NCC của phiếu đã có tiền trả (lõi không phân bổ PE / bút toán của NCC cũ vào phiếu của
	NCC khác; nppsale giữ cả tiền trên khoản nợ nay thuộc NCC mới). Số in như RAISE '%' của numeric (§2.5)."""
	return NppLoi(f"NCC_DA_TRA_TIEN: Phiếu đã trả NCC {K.so_pg(tien)} — không đổi nhà cung cấp được. Gỡ phiếu chi / Ghi trả trước.")


# ------------------------------------------------------------------------------------------------ 1. tham số
def _chu(obj, khoa: str) -> str | None:
	"""`x->>'khoa'` của jsonb: obj không phải object → NULL ở mọi khoá."""
	return K.chu_json(obj.get(khoa)) if isinstance(obj, Mapping) else None


def _nullif(obj, khoa: str) -> str | None:
	x = _chu(obj, khoa)
	return None if x in (None, "") else x


def so_jsonb(obj, khoa: str, mac_dinh=None) -> Decimal | None:
	"""`COALESCE(NULLIF(x->>'khoa', '')::numeric, mặc định)` — chữ không phải số (kể cả chỉ dấu cách) → BAD_PAYLOAD (nppsale 22P02)."""
	x = _nullif(obj, khoa)
	if x is None:
		return None if mac_dinh is None else K.so(mac_dinh)
	g = K.so_numeric(x.strip())
	if g is None:
		raise NppLoi(BAD_PAYLOAD)
	return g


_NGAY = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2})(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}(?::?\d{2})?)?)?")


def ngay_jsonb(obj, khoa: str, cu):
	"""`COALESCE(NULLIF(x->>'khoa', '')::date, cũ)` — `YYYY-MM-DD`, có thể kèm giờ hợp lệ (`date_in` của Postgres bỏ phần giờ: `T10:00:00Z`,
	` 10:00:00 +0700`, `T1:5`); sai → BAD_PAYLOAD (đo Postgres 16: `2026-11-02abc` / `2026-11-02 abc` / `2026-11-02T` / `2026-11-02 10` /
	`T25:00:00` → 22P02 / 22008). Lệch còn lại (không gặp ở giao diện): `2026-11-021` Postgres đọc thành 2026-11-21, ở đây BAD_PAYLOAD."""
	x = _nullif(obj, khoa)
	if x is None:
		return cu
	m = _NGAY.fullmatch(x.strip())
	if not m or (m.group(4) is not None and (int(m.group(4)) > 24 or int(m.group(5)) > 59 or int(m.group(6) or 0) > 60)):
		raise NppLoi(BAD_PAYLOAD)
	try:
		return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
	except ValueError:
		raise NppLoi(BAD_PAYLOAD) from None


@dataclass
class DauPhieu:
	ncc: str | None  # supplier_id (thiếu / '' → NCC cũ)
	vung: str  # warehouse_zone đã kiểm
	giam: Decimal  # discount — GREATEST(0, …)
	thue_tay: Decimal | None  # vat_override — None = tự cộng từ dòng (thiếu / null → XOÁ số gõ tay cũ)
	so_hd: str | None  # invoice_number — NULLIF(btrim), thiếu → NULL
	ghi_chu: str | None  # notes — NULLIF(btrim), thiếu → NULL
	ngay_tho: object = None  # p_head (giữ để ép kiểu ngày SAU CÙNG — `ngay_hd`)


def ncc_dau(p_head, ncc_cu: str | None) -> str | None:
	"""Bước 6: `COALESCE(NULLIF(p_head->>'supplier_id', ''), NCC cũ)` — NCC có thuộc NPP không do method kiểm (cần sổ) → `NCC_KHONG_HOP_LE`."""
	return _nullif(p_head, "supplier_id") or ncc_cu


def doc_dau(p_head, ncc: str | None, vung_cu: str | None) -> DauPhieu:
	"""Đầu phiếu SAU khi NCC đã kiểm (bước 7–8): kho (`KHO_KHONG_HOP_LE`) → ép kiểu giảm / thuế gõ tay (BAD_PAYLOAD); số / ghi chú NULLIF(btrim)."""
	h = p_head if isinstance(p_head, Mapping) else {}
	vung = _nullif(h, "warehouse_zone") or vung_cu or "sale"
	if vung not in K.VUNG:
		raise NppLoi(KHO_KHONG_HOP_LE)
	giam = max(Decimal(0), so_jsonb(h, "discount", 0))
	thue_tay = so_jsonb(h, "vat_override")
	return DauPhieu(ncc=ncc, vung=vung, giam=giam, thue_tay=thue_tay, so_hd=btrim(_chu(h, "invoice_number")),
		ghi_chu=btrim(_chu(h, "notes")), ngay_tho=h)


def ngay_hd(dau: DauPhieu, cu):
	"""`invoice_date = COALESCE(NULLIF(head.invoice_date, '')::date, cũ)` — hàm gốc ép kiểu ở câu UPDATE cuối: lỗi ngày ra sau mọi kiểm khác."""
	return ngay_jsonb(dau.ngay_tho, "invoice_date", cu)


@dataclass
class DongSua:
	stt: int  # vị trí 1-based trong p_lines (= sort_order mới)
	hang: str | None
	dv: str  # btrim — '' = chưa có đơn vị
	sl: Decimal
	gia: Decimal
	giam: Decimal  # giảm dòng (TIỀN cả dòng)
	thue: Decimal  # thuế suất (TỈ LỆ)
	hs: Decimal  # hệ số quy đổi
	ghi_chu: str | None

	@property
	def base(self) -> Decimal:
		return self.sl * self.hs

	@property
	def tien(self) -> Decimal:
		return K.tien_dong(self.sl, self.gia, self.giam)

	def gia_von(self) -> Decimal:
		return K.gia_von_lo(self.sl, self.gia, self.giam, self.hs)


def kiem_mang(p_lines) -> list:
	"""Bước 5 (TRƯỚC NCC / kho): `p_lines` NULL / không phải mảng / rỗng → PHIEU_TRONG. Chuỗi JSON (lời gọi không qua cổng) được đọc thành mảng."""
	if isinstance(p_lines, str):
		try:
			p_lines = json.loads(p_lines)
		except ValueError:
			p_lines = None
	if not isinstance(p_lines, list) or not p_lines:
		raise NppLoi(PHIEU_TRONG)
	return p_lines


def doc_dong(mang: list) -> list[DongSua]:
	"""Bước 9 (sau ép kiểu đầu phiếu): mỗi phần tử (không phải object → mọi khoá NULL): hàng NULLIF '', đơn vị btrim, SL / giá / giảm / thuế thiếu → 0,
	hệ số thiếu → 1, ghi chú '' → NULL (không btrim); ép kiểu sai ở BẤT KỲ dòng nào → BAD_PAYLOAD trước mọi kiểm dòng (INSERT … SELECT của hàm gốc ép
	kiểu cả mảng trước vòng kiểm)."""
	ra = []
	for stt, e in enumerate(mang, 1):
		ra.append(DongSua(stt=stt, hang=_nullif(e, "product_id"), dv=(_chu(e, "unit_name") or "").strip(" "), sl=so_jsonb(e, "quantity", 0),
			gia=so_jsonb(e, "unit_price", 0), giam=so_jsonb(e, "line_discount", 0), thue=so_jsonb(e, "vat_rate", 0),
			hs=so_jsonb(e, "conversion_factor", 1), ghi_chu=_nullif(e, "notes")))
	return ra


# ------------------------------------------------------------------------------------------------ 2. bốn kiểm của một dòng
def kiem_dong(dong: Iterable[DongSua], hang_hop_le) -> None:
	"""Bước 10 — theo stt, đủ bốn kiểm của một dòng rồi mới sang dòng sau, dừng ở lỗi đầu: hàng trống / không thuộc NPP → đơn vị '' → SL ≤ 0 hoặc
	hệ số ≤ 0 → giá âm hoặc giảm âm. KHÔNG kiểm giảm dòng > tiền hàng (nppsale — tiền dòng âm báo riêng ở `kiem_tien_am`)."""
	for d in sorted(dong, key=lambda x: x.stt):
		if not d.hang or d.hang not in hang_hop_le:
			raise loi_hang(d.stt)
		if d.dv == "":
			raise loi_don_vi(d.stt)
		if d.sl <= 0 or d.hs <= 0:
			raise K.loi_dong_so_luong(d.stt)
		if d.gia < 0 or d.giam < 0:
			raise K.loi_dong_gia(d.stt)


def kiem_tien_am(dong: Iterable[DongSua]) -> None:
	"""Tiền dòng âm (giảm dòng > SL × giá): nppsale nhận (lô giá vốn âm), lõi không ghi sổ dòng `rate` âm (câu tiếng Anh) — câu của cổng ghi nháp /
	Hoàn thành (M1, Q9); kiểm SAU mọi lỗi của nppsale (kể cả DA_XUAT_NHIEU_HON) để lỗi nppsale vẫn ra trước."""
	for d in sorted(dong, key=lambda x: x.stt):
		if d.tien < 0:
			raise K.loi_dong_tien_am(d.stt)


# ------------------------------------------------------------------------------------------------ 3. đã xuất của lô
def da_xuat_lo(nhap, ton_kho_dong, tu_dong_ra, ton_kho_khac) -> Decimal:
	"""Đã xuất của một lô của phiếu (nppsale `qty_initial − qty_on_hand` của dòng lô): SL nhập − tồn tại kho của dòng − phần phiếu `CKL-` rà soát tự
	động đã chuyển khỏi kho dòng mà còn nằm ở kho kia (nppsale lật cờ vùng tại chỗ — không phải xuất). Chuyển kho tay, bán, xuất lẻ, trả NCC… vẫn
	là đã xuất. Số âm (lô nhận thêm — hàng khách trả nhập lại vào lô cũ, thừa kiểm kê) giữ nguyên như nppsale."""
	return K.so(nhap) - K.so(ton_kho_dong) - min(max(K.so(tu_dong_ra), Decimal(0)), max(K.so(ton_kho_khac), Decimal(0)))


# ------------------------------------------------------------------------------------------------ 4. nhánh B — chỉ sửa giá
@dataclass
class DongCu:
	"""Dòng hiện hành của phiếu (đã phủ `npp_sua_gia` nếu có)."""
	idx: int
	hang: str
	dv: str
	sl: Decimal
	hs: Decimal
	gia: Decimal = Decimal(0)
	giam: Decimal = Decimal(0)
	thue: Decimal = Decimal(0)
	ghi_chu: str | None = None
	tien: Decimal = Decimal(0)  # tiền dòng hiện hành (đã làm tròn đồng — `amount` của lõi / `thanh_tien` đã phủ)

	def gia_von(self) -> Decimal:
		return K.gia_von_lo(self.sl, self.gia, self.giam, self.hs)


def kiem_chi_sua_gia(dong_moi: list[DongSua], dong_cu: list[DongCu], dv_moi: Mapping[int, str], ncc_moi, ncc_cu, vung_moi, vung_cu) -> list[str]:
	"""Nhánh B (CFD-06): mọi thứ ngoài giá phải giữ nguyên. `dv_moi` = {stt: tên UOM của sổ} (đơn vị gõ "thùng" và bản ghi "Thung" là MỘT đơn vị —
	method tra sổ). Trả danh sách chỗ đổi (rỗng = chỉ đổi giá)."""
	doi = []
	if ncc_moi != ncc_cu:
		doi.append("ncc")
	if vung_moi != vung_cu:
		doi.append("kho")
	if len(dong_moi) != len(dong_cu):
		doi.append("so_dong")
		return doi
	cu = sorted(dong_cu, key=lambda x: x.idx)
	for m, c in zip(sorted(dong_moi, key=lambda x: x.stt), cu, strict=True):
		if m.hang != c.hang:
			doi.append(f"dong{m.stt}:hang")
		if dv_moi.get(m.stt) != c.dv:
			doi.append(f"dong{m.stt}:dv")
		if K.so(m.sl) != K.so(c.sl):
			doi.append(f"dong{m.stt}:sl")
		if K.so(m.hs) != K.so(c.hs):
			doi.append(f"dong{m.stt}:hs")
	return doi


def chenh_dong(tien_cu: Mapping[int, object], tien_moi: Mapping[int, object]) -> dict[int, Decimal]:
	"""Chênh tiền hàng chưa thuế từng dòng (mới − cũ) theo idx; dòng không đổi bỏ."""
	ra = {}
	for i in sorted(set(tien_cu) | set(tien_moi)):
		x = K.so(tien_moi.get(i, 0)) - K.so(tien_cu.get(i, 0))
		if x != 0:
			ra[i] = x
	return ra


def tach_lcv(chenh: Mapping[int, Decimal]) -> list[dict[int, Decimal]]:
	"""Landed Cost Voucher MỘT chiều (BP §5.10 — lõi v16 bắt `applicable_charges` mọi dòng cùng dấu với tổng và tổng ≠ 0 lúc `on_submit`,
	`landed_cost_voucher.py:354–368, 404–417`): dòng tăng một LCV (tổng dương), dòng giảm một LCV (tổng âm); không chênh → không LCV. Thứ tự: tăng
	trước."""
	duong = {i: x for i, x in chenh.items() if x > 0}
	am = {i: x for i, x in chenh.items() if x < 0}
	return [x for x in (duong, am) if x]


@dataclass
class SoPhieu:
	"""Số tiền hiện hành của phiếu (tờ lõi hoặc phủ `npp_sua_gia`), đã làm tròn đồng như sổ."""
	tien_hang: Decimal  # Σ tiền dòng (subtotal)
	thue: Decimal  # Σ dòng VAT / thuế gõ tay
	giam_ap: Decimal  # giảm đầu phiếu đã áp (dòng Deduct — min(giảm, tiền + thuế))
	tong: Decimal  # grand_total (+ Σ chênh DCN đã lập)


@dataclass
class ButToan:
	"""Bút toán `DCN-` (BP §5.9 / §5.10): số dương = NỢ tài khoản, âm = CÓ."""
	ncc: Decimal  # Phải trả NCC (tham chiếu phiếu nhập): −Δtổng (tổng tăng → Có)
	trung_gian: Decimal  # TK trung gian sửa giá nhập (đối ứng LCV): +Δtiền hàng
	thue: Decimal  # thuế GTGT đầu vào: +Δthuế
	giam: Decimal  # giảm đầu phiếu nhập (thu nhập): −Δgiảm đã áp
	loai: str = field(default="Journal Entry")  # "Debit Note" khi GIẢM nợ (lõi bỏ kiểm số còn nợ — nợ âm được như nppsale)

	def rong(self) -> bool:
		return not any((self.ncc, self.trung_gian, self.thue, self.giam))


def but_toan_dcn(cu: SoPhieu, moi: SoPhieu) -> ButToan:
	"""Δ = mới − cũ; cân: Δtiền + Δthuế = Δtổng + Δgiảm (tổng = tiền + thuế − giảm đã áp). Lệch → ValueError (số dựng sai)."""
	dt, dth, dg, dtong = moi.tien_hang - cu.tien_hang, moi.thue - cu.thue, moi.giam_ap - cu.giam_ap, moi.tong - cu.tong
	if dt + dth - dg != dtong:
		raise ValueError(f"bút toán sửa giá không cân: Δtiền {dt} + Δthuế {dth} − Δgiảm {dg} ≠ Δtổng {dtong}")
	return ButToan(ncc=-dtong, trung_gian=dt, thue=dth, giam=-dg, loai="Debit Note" if dtong < 0 else "Journal Entry")


def so_lo_doi_gia(cap: Iterable[tuple[object, object]]) -> int:
	"""Số lô đổi giá vốn: cặp (giá cũ, giá mới) mỗi đơn vị cơ sở của lô cũ giữ lại — so Decimal không làm tròn (`IS DISTINCT FROM` của numeric)."""
	return sum(1 for cu, moi in cap if K.so(cu) != K.so(moi))


def _so_json(x):
	d = K.so(x)
	return int(d) if d == d.to_integral_value() else float(d)


def json_sua_gia(cu: Mapping | None, dong: Iterable[tuple[int, DongSua, object]], dau: DauPhieu, so: SoPhieu, lan: Mapping) -> dict:
	"""`Purchase Invoice.npp_sua_gia` (BP §5.9): số HIỆN HÀNH sau lần sửa — {dong: {"<idx>": {don_gia, giam_dong, thue_suat, thanh_tien, ghi_chu}},
	dau_phieu: {giam, giam_ap, thue_go_tay, tien_hang, thue, tong}, lan_sua: [… + lan]}; `dong` = [(idx, dòng mới, tiền dòng đã làm tròn)]."""
	ra = {"dong": {}, "dau_phieu": {}, "lan_sua": list((cu or {}).get("lan_sua") or [])}
	for idx, d, tien in dong:
		ra["dong"][str(idx)] = {"don_gia": _so_json(d.gia), "giam_dong": _so_json(d.giam), "thue_suat": _so_json(d.thue),
			"thanh_tien": _so_json(tien), "ghi_chu": d.ghi_chu}
	ra["dau_phieu"] = {"giam": _so_json(dau.giam), "giam_ap": _so_json(so.giam_ap), "thue_go_tay": None if dau.thue_tay is None
		else _so_json(dau.thue_tay), "tien_hang": _so_json(so.tien_hang), "thue": _so_json(so.thue), "tong": _so_json(so.tong)}
	ra["lan_sua"].append(dict(lan))
	return ra
