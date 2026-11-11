"""Sổ đăng ký bảng của cổng tương thích.

Mỗi bảng nppsale mà giao diện gọi `.from("<bang>")` được khai một lần (ở nppsale/cong/bang/*.py):
- nguon: biểu thức FROM (bảng DocType `tabX` hoặc câu con) — bí danh do bộ dựng đặt;
- cot: tên cột nppsale → CotDef(biểu thức SQL dùng "{t}" thay bí danh bảng, kiểu dữ liệu, trường DocType để ghi);
- quan_he: để select lồng (customer:customers(...), lines:sales_order_lines(...));
- rls(ngu_canh): vế lọc theo người — chép đúng chính sách RLS đang chạy của nppsale; None = không lọc, False = cấm hết;
- ghi: bộ xử lý ghi (None = chỉ qua RPC — ghi thẳng bị từ chối như mig 214).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

KIEU = {"chuoi", "so", "tien", "ngay", "gio", "bool", "json"}


@dataclass
class CotDef:
	sql: str
	kieu: str = "chuoi"
	truong: str | None = None  # trường DocType để ghi thẳng (None = không ghi thẳng được)

	def __post_init__(self):
		if self.kieu not in KIEU:
			raise ValueError(f"kiểu cột không hợp lệ: {self.kieu}")


@dataclass
class QuanHe:
	bang: str  # bảng nppsale đích
	cot_nay: str  # cột (tên nppsale) ở bảng này
	cot_kia: str  # cột (tên nppsale) ở bảng đích
	nhieu: bool  # True: một-nhiều → mảng; False: nhiều-một → object / null
	ten_fk: tuple = ()  # tên khoá ngoại kiểu PostgREST để chọn đúng quan hệ ("sales_orders_sales_user_id_fkey")


@dataclass
class NguCanh:
	"""Người đang gọi — đủ cho vế RLS."""
	user: str
	vai: str | None = None  # vai nppsale: owner / manager / accountant / sales / warehouse …
	quyen: frozenset = frozenset()  # khoá quyền đã tính (mô-đun.hành_động, ô riêng)
	bo_qua_rls: bool = False  # Administrator / System Manager chạy việc nền
	them: dict = field(default_factory=dict)


@dataclass
class Bang:
	ten: str
	nguon: str
	cot: dict
	khoa: str = "id"
	quan_he: list = field(default_factory=list)
	rls: Callable[[NguCanh], Any] | None = None
	ghi: Any = None
	mo_ta: str = ""

	def cot_def(self, ten: str) -> CotDef | None:
		return self.cot.get(ten)


SO_DANG_KY: dict[str, Bang] = {}


def dang_ky(bang: Bang) -> Bang:
	if bang.khoa not in bang.cot:
		raise ValueError(f"{bang.ten}: khoá {bang.khoa} chưa khai trong cột")
	SO_DANG_KY[bang.ten] = bang
	return bang


def lay(ten: str) -> Bang | None:
	return SO_DANG_KY.get(ten)


def tim_quan_he(bang: Bang, ten: str, goi_y: list[str]) -> QuanHe | None:
	"""Chọn quan hệ cho nút lồng `ten!goi_y(...)`: theo tên bảng đích (hoặc tên cột nối), rồi theo gợi ý tên khoá ngoại / cột."""
	ung = [q for q in bang.quan_he if q.bang == ten]
	if not ung:
		ung = [q for q in bang.quan_he if q.cot_nay == ten]
	if goi_y:
		loc = [q for q in ung if any(g in q.ten_fk or g == q.cot_nay or g == q.cot_kia for g in goi_y)]
		if loc:
			ung = loc
	if len(ung) == 1:
		return ung[0]
	if len(ung) > 1:
		# PostgREST báo PGRST201 (nhiều quan hệ) — nppsale luôn ghi rõ !fkey ở những chỗ ấy
		return None
	return None
