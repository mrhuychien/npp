"""Khai bảng cho cổng — mỗi tệp một nhóm bảng nppsale; nạp tất cả một lần mỗi tiến trình."""
from __future__ import annotations

import importlib
import pkgutil

_DA_NAP = False


def nap():
	global _DA_NAP
	if _DA_NAP:
		return
	for m in pkgutil.iter_modules(__path__):
		if not m.name.startswith("_"):
			importlib.import_module(f"{__name__}.{m.name}")
	_DA_NAP = True
