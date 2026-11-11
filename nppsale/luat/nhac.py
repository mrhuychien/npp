"""Luật nhắc định kỳ (thuần): nhắc điểm bán thiếu ảnh / vị trí (planReminders, reminderText — src/lib/customers/photos.ts) và nhắc khách
chưa gán tuyến (lapNhacTuyen, noiDungNhacTuyen — src/lib/customers/nhac-tuyen.ts, mig 221) của nppsale.

Mốc thời gian truyền vào bằng giây epoch (không gọi đồng hồ bên trong) — một lượt chạy dùng chung một mốc, test cố định được giờ.
"""
from __future__ import annotations

from dataclasses import dataclass

NGAY = 86_400
NHAC_ANH_HOA_NHIET_NGAY = 7  # REMINDER_COOLDOWN_DAYS
NHAC_TUYEN_SAU_NGAY = 3  # NHAC_TUYEN_SAU_NGAY


@dataclass
class KhachNhacAnh:
	id: str
	ten: str
	so_anh: int
	co_vi_tri: bool
	nhac_luc: float | None  # epoch giây, None = chưa nhắc bao giờ
	nv: str | None  # NV phụ trách chính


@dataclass
class KhachNhacTuyen:
	id: str
	ten: str
	tuyen: str | None
	nhac_luc: float | None
	nv: str | None


def _gom(ds) -> list[tuple[str, list]]:
	m: dict = {}
	for k, v in ds:
		m.setdefault(k, []).append(v)
	return list(m.items())


def lap_nhac_anh(ds: list[KhachNhacAnh], bay_gio: float, hoa_nhiet_ngay: int = NHAC_ANH_HOA_NHIET_NGAY) -> dict:
	"""planReminders: điểm bán THIẾU ảnh hoặc vị trí (đủ cả hai thì thôi), chưa nhắc trong `hoa_nhiet_ngay` ngày; gộp theo NV phụ trách
	chính (mỗi người MỘT thông báo); không ai phụ trách → danh sách riêng (không nhắc ai)."""
	moc = bay_gio - hoa_nhiet_ngay * NGAY
	theo_nv, khong_ai, hoa_nhiet = [], [], 0
	for k in ds:
		if k.so_anh > 0 and k.co_vi_tri:
			continue
		if k.nhac_luc is not None and k.nhac_luc > moc:
			hoa_nhiet += 1
			continue
		if not k.nv:
			khong_ai.append(k)
			continue
		theo_nv.append((k.nv, k))
	return {"theo_nv": _gom(theo_nv), "khong_ai": khong_ai, "hoa_nhiet": hoa_nhiet}


def noi_dung_nhac_anh(ds: list[KhachNhacAnh]) -> tuple[str, str]:
	n = len(ds)
	ten = ", ".join(k.ten for k in ds[:3])
	them = f" và {n - 3} điểm nữa" if n > 3 else ""
	return f"{n} điểm bán chưa có ảnh / vị trí", f"{ten}{them}. Mở app khi tới nơi để chụp — vị trí lấy tự động."


def chua_co_tuyen(tuyen: str | None) -> bool:
	return not str(tuyen or "").strip()


def lap_nhac_tuyen(ds: list[KhachNhacTuyen], quan_ly: list[str], bay_gio: float, sau_ngay: int = NHAC_TUYEN_SAU_NGAY) -> dict:
	"""lapNhacTuyen: khách chưa có tuyến, chưa nhắc trong `sau_ngay` ngày → NV phụ trách chính; không ai phụ trách → mọi chủ / quản lý
	đang làm; không có cả quản lý → đếm "không người nhận"."""
	moc = bay_gio - sau_ngay * NGAY
	cap, hoa_nhiet, khong_nguoi = [], 0, 0
	for k in ds:
		if not chua_co_tuyen(k.tuyen):
			continue
		if k.nhac_luc is not None and k.nhac_luc > moc:
			hoa_nhiet += 1
			continue
		if k.nv:
			cap.append((k.nv, k))
		elif quan_ly:
			cap.extend((q, k) for q in quan_ly)
		else:
			khong_nguoi += 1
	return {"theo_nguoi": _gom(cap), "hoa_nhiet": hoa_nhiet, "khong_nguoi_nhan": khong_nguoi}


def noi_dung_nhac_tuyen(ds: list[KhachNhacTuyen]) -> tuple[str, str]:
	n = len(ds)
	ten = ", ".join(k.ten for k in ds[:3])
	them = f" và {n - 3} khách nữa" if n > 3 else ""
	return f"{n} khách hàng chưa gán tuyến", f"{ten}{them}. Mở khách hàng để cập nhật tuyến bán hàng."
