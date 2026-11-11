"""Đọc chuỗi select kiểu PostgREST.

    select := muc ("," muc)*
    muc    := "*" | [bi_danh ":"] cot ["::" kieu]
                  | [bi_danh ":"] gop
                  | [bi_danh ":"] ten_long ("!" goi_y)* "(" select ")"
    gop    := "count()" | cot "." ham "()"      ham ∈ sum / avg / min / max / count

Ví dụ thật ở nppsale: "id, order_code, customer:customers(store_name, phone), sales_user:users!sales_orders_sales_user_id_fkey(full_name)",
"product_id, quantity, returns!inner(order_id, status)", "status, count()", "total.sum(), customer:customers!inner(channel)".
"""
from __future__ import annotations

from dataclasses import dataclass, field

HAM_GOP = {"sum", "avg", "min", "max", "count"}


class LoiChon(ValueError):
	"""Chuỗi select sai cú pháp (mã PGRST100 của PostgREST)."""


@dataclass
class Cot:
	ten: str
	bi_danh: str | None = None
	kieu_ep: str | None = None

	@property
	def khoa_ra(self) -> str:
		return self.bi_danh or self.ten


@dataclass
class TatCa:
	pass


@dataclass
class Gop:
	ham: str  # count / sum / avg / min / max
	cot: str | None  # None với count()
	bi_danh: str | None = None

	@property
	def khoa_ra(self) -> str:
		# PostgREST đặt tên cột kết quả: "count" cho count(), tên hàm cho col.sum() ("sum")
		return self.bi_danh or self.ham


@dataclass
class Long:
	ten: str  # tên quan hệ / bảng đích như viết trong select
	con: list = field(default_factory=list)
	bi_danh: str | None = None
	goi_y: list[str] = field(default_factory=list)  # các phần sau "!" trừ inner / left

	inner: bool = False

	@property
	def khoa_ra(self) -> str:
		return self.bi_danh or self.ten


def _tach_cap_cao(s: str) -> list[str]:
	"""Tách theo dấu phẩy ở mức ngoặc 0, bỏ qua phẩy trong ngoặc kép."""
	phan, sau, sau_ngoac, trong_nhay = [], [], 0, False
	for ch in s:
		if ch == '"':
			trong_nhay = not trong_nhay
		if not trong_nhay:
			if ch == "(":
				sau_ngoac += 1
			elif ch == ")":
				sau_ngoac -= 1
				if sau_ngoac < 0:
					raise LoiChon(f"thừa ngoặc đóng trong select: {s!r}")
			elif ch == "," and sau_ngoac == 0:
				phan.append("".join(sau))
				sau = []
				continue
		sau.append(ch)
	if sau_ngoac != 0 or trong_nhay:
		raise LoiChon(f"ngoặc / nháy không khép trong select: {s!r}")
	phan.append("".join(sau))
	return [p.strip() for p in phan if p.strip()]


def _hop_le(ten: str) -> bool:
	return bool(ten) and all(c.isalnum() or c == "_" for c in ten)


def doc_select(s: str | None) -> list:
	"""Trả danh sách nút (Cot / TatCa / Gop / Long). Rỗng hoặc None = "*"."""
	if s is None or not str(s).strip():
		return [TatCa()]
	ket = []
	for muc in _tach_cap_cao(str(s)):
		ket.append(_doc_muc(muc))
	return ket


def _doc_muc(muc: str):
	muc = " ".join(muc.split())  # gộp xuống dòng / nhiều dấu cách (chuỗi select của nppsale hay xuống dòng)
	if muc == "*":
		return TatCa()
	# Bí danh: phần trước dấu ":" đầu tiên ở mức ngoặc 0, nhưng không phải "::" (ép kiểu)
	bi_danh = None
	i_ngoac = muc.find("(")
	dau_phan = muc if i_ngoac < 0 else muc[:i_ngoac]
	i_hai_cham = dau_phan.find(":")
	if i_hai_cham > 0 and dau_phan[i_hai_cham : i_hai_cham + 2] != "::":
		bi_danh = dau_phan[:i_hai_cham].strip()
		muc = muc[i_hai_cham + 1 :].strip()
		if not _hop_le(bi_danh):
			raise LoiChon(f"bí danh không hợp lệ: {bi_danh!r}")
	# Gộp nhóm
	if muc.replace(" ", "") == "count()":
		return Gop("count", None, bi_danh)
	if muc.endswith("()") and "." in muc and "(" not in muc[:-2]:
		cot, ham = muc[:-2].rsplit(".", 1)
		ham, cot = ham.strip(), cot.strip()
		if ham not in HAM_GOP or not _hop_le(cot):
			raise LoiChon(f"hàm gộp không hỗ trợ: {muc!r}")
		return Gop(ham, cot, bi_danh)
	# Bảng lồng
	if "(" in muc:
		if not muc.endswith(")"):
			raise LoiChon(f"bảng lồng thiếu ngoặc đóng: {muc!r}")
		dau, than = muc.split("(", 1)
		than = than[:-1]
		phan = [p.strip() for p in dau.split("!")]
		ten, goi_y = phan[0], [p for p in phan[1:] if p]
		if not _hop_le(ten):
			raise LoiChon(f"tên bảng lồng không hợp lệ: {ten!r}")
		inner = "inner" in goi_y
		goi_y = [g for g in goi_y if g not in ("inner", "left")]
		return Long(ten=ten, con=doc_select(than) if than.strip() else [TatCa()], bi_danh=bi_danh, goi_y=goi_y, inner=inner)
	# Cột thường (có thể kèm ép kiểu)
	kieu = None
	if "::" in muc:
		muc, kieu = [x.strip() for x in muc.split("::", 1)]
	if not _hop_le(muc):
		raise LoiChon(f"cột không hợp lệ: {muc!r}")
	return Cot(ten=muc, bi_danh=bi_danh, kieu_ep=kieu)
