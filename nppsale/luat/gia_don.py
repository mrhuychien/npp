"""Luật giá / giảm giá của dòng đơn và cả đơn — chép trigger `_chot_gia_dong_don` (BEFORE trên sales_order_lines) và
`_chot_giam_don` (constraint trigger hoãn tới cuối giao dịch trên sales_orders) của nppsale (mig 226 / 230 / 185), cùng
`_gia_bang_don_vi`, `_giam_don_hien_tai`, `_nhan_tran_giam`, `_thue_hop_le`. Không import frappe — method của phần Bán hàng
đọc sổ rồi gọi các hàm này.

Câu báo lỗi giữ nguyên mã đầu câu (PRICE_OVER_CEILING / DISCOUNT_NOT_ALLOWED / DISCOUNT_OVER_LIMIT / BAD_PAYLOAD) vì màn POS và
`errorMessage` của nppsale dịch theo mã ấy.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from nppsale.cong.loi import NppLoi


def lam_tron(x) -> int:
	"""round(numeric) của Postgres: nửa xa số 0 (Python round() là làm tròn kiểu ngân hàng — sai ở x,5)."""
	return int(Decimal(str(x or 0)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def so_vn(x) -> str:
	"""replace(to_char(round(x), 'FM999,999,999,999'), ',', '.') — 1234567 → "1.234.567"."""
	n = lam_tron(x)
	return ("-" if n < 0 else "") + f"{abs(n):,}".replace(",", ".")


def phan_tram_vn(x) -> str:
	"""replace(trim_scale(x)::text, '.', ',') — 12.50 → "12,5", 10.0 → "10"."""
	d = Decimal(str(x or 0)).normalize()
	s = format(d, "f")
	return s.replace(".", ",")


def nhan_tran_giam(loai: str | None, tran) -> str:
	if loai == "vnd":
		return "tối đa " + so_vn(tran) + "đ"
	return "tối đa " + phan_tram_vn(tran) + "%"


def thue_hop_le(v) -> float | None:
	"""_thue_hop_le (mig 183): chuỗi số 0..1 → làm tròn 4 chữ số; còn lại (rỗng, âm, 8 thay vì 0,08, chữ) → None = "theo SP"."""
	if v is None or isinstance(v, bool):
		return None
	s = str(v)
	if not re.fullmatch(r"\s*[0-9]+(\.[0-9]+)?\s*", s):
		return None
	try:
		d = Decimal(s.strip())
	except InvalidOperation:
		return None
	if d < 0 or d > 1:
		return None
	return float(d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


@dataclass
class QuyenGiam:
	"""_quyen_giam_cua(uid): chủ / kế toán (hoặc người gọi không phải NV — việc nền) toàn quyền; NV khác theo cờ + trần (mig 185)."""
	toan_quyen: bool
	duoc_giam: bool = False
	loai_tran: str = "pct"
	tran: float | None = None
	nang_gia_pct: float = 0.0  # trần nâng giá so với giá bảng (%), đã quy theo vai — xem quyen_giam()


def quyen_giam(nv: dict | None) -> QuyenGiam:
	"""nv: dòng NPP Nhan Vien của người gọi (vai, cho_giam_gia, kieu_tran_giam, co_tran_giam, tran_giam, cho_sua_gia, tran_tang_gia)
	hoặc None (không phải nhân viên — Administrator / việc nền: như auth.uid() IS NULL → toàn quyền)."""
	if not nv:
		return QuyenGiam(toan_quyen=True)
	vai = nv.get("vai")
	nang = 0.0
	if nv.get("cho_sua_gia") or vai != "sales":
		nang = max(0.0, float(nv.get("tran_tang_gia") or 0))
	return QuyenGiam(
		toan_quyen=vai in ("owner", "accountant"),
		duoc_giam=bool(nv.get("cho_giam_gia")),
		loai_tran=nv.get("kieu_tran_giam") or "pct",
		tran=float(nv["tran_giam"]) if nv.get("co_tran_giam") and nv.get("tran_giam") is not None else None,
		nang_gia_pct=nang,
	)


def _d(x) -> Decimal:
	return Decimal(str(x if x is not None else 0))


def kiem_dong(sl, gia, giam_dong, *, q: QuyenGiam, gia_bang, cu: dict | None = None):
	"""BEFORE INSERT / UPDATE của dòng đơn. cu: dòng cũ CÙNG mặt hàng + đơn vị (sửa dòng) = {sl, gia, giam_dong}; khác hàng / đơn vị
	hay dòng mới → None. Ném NppLoi như trigger. Tính bằng Decimal như numeric của Postgres (mép x,5 của round không lệch)."""
	if sl is None or sl <= 0:
		raise NppLoi("BAD_PAYLOAD: số lượng của dòng hàng phải lớn hơn 0 (bỏ dòng thay vì để 0).")
	if gia is None or gia < 0:
		raise NppLoi("BAD_PAYLOAD: đơn giá của dòng hàng không được âm.")
	if (giam_dong or 0) < 0:
		raise NppLoi("BAD_PAYLOAD: giảm giá dòng không được âm.")
	if q.toan_quyen:
		return
	sl, gia, gd, bang = _d(sl), _d(gia), _d(giam_dong), _d(gia_bang)
	if bang > 0:
		truoc = gia + gd / sl
		tran_gia = lam_tron(bang * (1 + _d(q.nang_gia_pct) / 100))
		giu_nguyen = bool(cu) and _d(cu.get("sl")) > 0 and truoc <= _d(cu["gia"]) + _d(cu.get("giam_dong")) / _d(cu["sl"]) + 1
		if truoc > tran_gia + 1 and not giu_nguyen:
			raise NppLoi("PRICE_OVER_CEILING: Đơn giá {} vượt mức tối đa {} (giá bảng {}, được nâng {}%).".format(
				so_vn(truoc), so_vn(tran_gia), so_vn(bang), phan_tram_vn(q.nang_gia_pct or 0)))
	giam = max(gd, sl * (bang - gia) if bang > 0 else Decimal(0), Decimal(0))
	goc = Decimal(0)
	if cu:
		goc = max(_d(cu.get("giam_dong")), _d(cu["sl"]) * (bang - _d(cu["gia"])) if bang > 0 else Decimal(0), Decimal(0))
	sai = sl * Decimal("0.5") + 1
	if giam <= goc + sai:
		return
	if not q.duoc_giam:
		raise NppLoi("DISCOUNT_NOT_ALLOWED: Bạn không có quyền giảm giá dòng (kể cả bán dưới giá bảng) — bỏ giảm giá ở các dòng rồi gửi lại.")
	if q.tran is not None:
		tien = sl * gia + giam
		tran = _d(q.tran) if q.loai_tran == "vnd" else Decimal(math.floor(tien * min(Decimal(100), _d(q.tran)) / 100))
		if giam > tran + sai:
			raise NppLoi(f"DISCOUNT_OVER_LIMIT: Giảm giá dòng vượt mức cho phép ({nhan_tran_giam(q.loai_tran, q.tran)}).")


def giam_don_hien_tai(dong: list[tuple], subtotal) -> int:
	"""_giam_don_hien_tai: dong = [(SL, đơn giá)]; chỉ tính dòng SL > 0. Giảm giá cả đơn suy ra = round(Σ SL × giá) − round(subtotal)
	khi vượt max(1, số dòng) (sai số làm tròn), không thì 0."""
	n = sum(1 for sl, _g in dong if (sl or 0) > 0)
	hieu = tong_tien(dong) - lam_tron(subtotal or 0)
	return hieu if hieu > max(1, n) else 0


def tong_tien(dong: list[tuple]) -> int:
	"""round(Σ SL × đơn giá) trên các dòng SL > 0 — làm tròn MỘT lần như nppsale."""
	return lam_tron(sum((_d(sl) * _d(g) for sl, g in dong if (sl or 0) > 0), Decimal(0)))


def kiem_giam_don(giam, *, q: QuyenGiam, goc, dong: list[tuple]):
	"""_chot_giam_don (cuối giao dịch, đơn draft / submitted): giam = giảm đơn hiện tại; goc = giảm đơn trước lần sửa (đơn mới: 0);
	dong = [(SL, đơn giá, giảm dòng)]; chỉ tính dòng SL > 0. Chỉ kiểm khi giảm TĂNG so với gốc."""
	if q.toan_quyen:
		return
	if _d(giam) <= max(_d(goc), Decimal(0)):
		return
	if not q.duoc_giam:
		raise NppLoi("DISCOUNT_NOT_ALLOWED: Bạn không có quyền giảm giá đơn.")
	if q.tran is not None:
		dong = [d for d in dong if (d[0] or 0) > 0]
		tien = sum((_d(sl) * _d(g) + _d(gd) for sl, g, gd in dong), Decimal(0))
		n = len(dong)
		tran = _d(q.tran) if q.loai_tran == "vnd" else Decimal(math.floor(tien * min(Decimal(100), _d(q.tran)) / 100))
		if _d(giam) > tran + n + 1:
			raise NppLoi(f"DISCOUNT_OVER_LIMIT: Giảm giá đơn vượt mức cho phép ({nhan_tran_giam(q.loai_tran, q.tran)}).")
