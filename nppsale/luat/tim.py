"""Khoá tìm không dấu `tim_kd` — phải trùng TỪNG KÝ TỰ với `viValueKey` / `viSearchKey` của nppsale (`src/lib/search.ts`) và
`public.khoa_tim` / `khoa_tim_ds` (mig 205, 258): portal tìm trên chuỗi này (`ilike`) theo từ đã chuẩn hoá bằng bản TS.

	"DH-0123"       → "dh 0123 dh0123 dh123"
	"0912 345 678"  → "0912 345 678 0912345678 912345678"
	"Sữa hộp"       → "sua hop suahop"
"""
from __future__ import annotations

import re
import unicodedata

_DAU = re.compile("[̀-ͯ]")
_NGAT_TU = re.compile(r"[^a-z0-9]+")
_SO_0_DAU = re.compile(r"(^|[a-z])0+(?=[0-9])")


def _chuoi_js(v) -> str:
	"""String(value) của JavaScript: 12.0 → "12", True → "true", None → ""."""
	if v is None:
		return ""
	if isinstance(v, bool):
		return "true" if v else "false"
	if isinstance(v, float):
		if v != v:
			return "NaN"
		if v.is_integer():
			return str(int(v))
		return repr(v)
	return str(v)


def vi_chuan_hoa(v) -> str:
	"""viNormalize: NFD bỏ dấu thanh (U+0300–U+036F), đ/Đ → d/D, chữ thường, gộp khoảng trắng."""
	s = unicodedata.normalize("NFD", _chuoi_js(v))
	s = _DAU.sub("", s).replace("đ", "d").replace("Đ", "D").lower()
	return re.sub(r"\s+", " ", s).strip()


def _tach_tu(chuan: str) -> list[str]:
	return [t for t in _NGAT_TU.split(chuan) if t]


def bo_so_0_dau(tu: str) -> str:
	"""boSo0Dau: "0123" → "123", "sp0012" → "sp12", "000" → "0"."""
	return _SO_0_DAU.sub(r"\1", tu)


def khoa_tim(v) -> str:
	"""viValueKey / public.khoa_tim: các từ, bản viết liền (nếu ≥ 2 từ), bản viết liền bỏ số 0 đầu (nếu khác)."""
	tu = _tach_tu(vi_chuan_hoa(v))
	if not tu:
		return ""
	lien = "".join(tu)
	ra = [" ".join(tu)]
	if len(tu) > 1:
		ra.append(lien)
	lien0 = "".join(bo_so_0_dau(t) for t in tu)
	if lien0 != lien:
		ra.append(lien0)
	return " ".join(ra)


def khoa_tim_ds(*gia_tri) -> str:
	"""viSearchKey / public.khoa_tim_ds: ghép khoá khác rỗng của từng giá trị bằng một dấu cách."""
	return " ".join(k for k in (khoa_tim(v) for v in gia_tri) if k)


def tu_tim(chuoi: str) -> list[str]:
	"""viQueryWords: mỗi từ gõ viết liền ("HD-0123" → "hd0123"), bỏ trùng, giữ thứ tự."""
	ra: list[str] = []
	for w in vi_chuan_hoa(chuoi).split(" "):
		t = "".join(_tach_tu(w))
		if t and t not in ra:
			ra.append(t)
	return ra
