"""RPC cùng tên với hàm Postgres của nppsale. Khai bằng @rpc("ten", ghi=True|False, cho_khach=False).

ghi=False: hàm chỉ đọc (STABLE ở nppsale) — gọi được bằng GET (an toàn để thử lại); ghi=True: chỉ POST.
cho_khach=True: gọi được khi chưa đăng nhập (nppsale GRANT … TO anon) — luôn kèm giới hạn tần suất theo IP."""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass

DANG_KY: dict = {}


@dataclass
class MucRpc:
	ham: Callable
	ghi: bool = True
	cho_khach: bool = False
	gioi_han_phut: int = 20  # lượt / phút / IP khi người gọi là khách
	# Method ghi kho (CFD-05): chạy `chuan_bi(**tham_so)` (đọc người gọi, cài đặt — mọi thứ cần trước khi khoá) → cổng COMMIT → đặt
	# savepoint → gọi hàm, mà câu ĐẦU TIÊN là khoá Bin `FOR UPDATE`: ảnh chụp dữ liệu (REPEATABLE READ) chỉ lập ở câu đọc thường sau
	# khoá, nên hàm đọc tồn mới nhất (PoC 1d). Deadlock / quá hạn khoá → lui cả lượt, thử lại có giãn cách.
	chuan_bi: Callable | None = None


def rpc(ten: str, ghi: bool = True, cho_khach: bool = False, gioi_han_phut: int = 20, chuan_bi: Callable | None = None):
	def boc(ham):
		DANG_KY[ten] = MucRpc(ham, ghi, cho_khach, gioi_han_phut, chuan_bi)
		return ham
	return boc


_DA_NAP = False


def nap():
	global _DA_NAP
	if _DA_NAP:
		return
	for m in pkgutil.iter_modules(__path__):
		if not m.name.startswith("_"):
			importlib.import_module(f"{__name__}.{m.name}")
	_DA_NAP = True
