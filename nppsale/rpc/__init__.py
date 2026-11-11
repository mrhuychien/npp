"""RPC cùng tên với hàm Postgres của nppsale (74 hàm). Khai bằng @rpc("ten", ghi=True|False).

ghi=False: hàm chỉ đọc (STABLE ở nppsale) — gọi được bằng GET (an toàn để thử lại); ghi=True: chỉ POST."""
from __future__ import annotations

import importlib
import pkgutil

DANG_KY: dict = {}


def rpc(ten: str, ghi: bool = True):
	def boc(ham):
		DANG_KY[ten] = (ham, ghi)
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
