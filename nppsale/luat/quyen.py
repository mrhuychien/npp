"""Kiểm quyền phía máy chủ — bản Python của `public.user_has_permission(uid, khoá)` (mig 166), dùng trong các RPC.

Thứ tự: quyền riêng của người (`user_permission_overrides` → NPP Quyen Rieng) thắng → Chủ NPP luôn được → dòng quyền của vai
(`role_permissions` → NPP Quyen Vai; khoá tách ở dấu chấm CUỐI: "customers.analytics.read" → mô-đun "customers.analytics",
hành động "read") → không có dòng thì KHÔNG được. Máy chủ không tự áp bảng mặc định của giao diện (`DEFAULT_PERMISSION_MAP`,
`defaultRoles`): các ô mặc định được gieo thành dòng quyền vai lúc cài (như `_gieo_quyen_mac_dinh`).
"""
from __future__ import annotations


def tach_khoa(khoa: str) -> tuple[str, str] | None:
	"""("mô-đun", "hành động") theo dấu chấm cuối; None nếu khoá không có dạng ấy."""
	i = khoa.rfind(".")
	if i <= 0 or i >= len(khoa) - 1:
		return None
	return khoa[:i], khoa[i + 1 :]


def co_quyen(vai: str | None, khoa: str, quyen_rieng: dict[str, bool] | None, dong_vai: dict[tuple[str, str, str], bool] | None) -> bool:
	"""vai: vai của người (None = không có hồ sơ → không được). quyen_rieng: {khoá: được?} của chính người ấy.
	dong_vai: {(vai, mô-đun, hành động): được?} của NPP."""
	if not vai:
		return False
	if quyen_rieng and khoa in quyen_rieng:
		return bool(quyen_rieng[khoa])
	if vai == "owner":
		return True
	t = tach_khoa(khoa)
	if t is None:
		return False
	return bool((dong_vai or {}).get((vai, t[0], t[1]), False))


# Bộ dòng quyền vai gieo sẵn cho NPP (mig 166 `_gieo_quyen_mac_dinh`) — các ô RPC kiểm mà giao diện mặc định cho vai ấy.
DONG_VAI_GIEO_SAN: list[tuple[str, str, str]] = [
	("manager", "orders", "approve"),
	("manager", "orders", "update"),
	("manager", "returns", "approve"),
	("manager", "inventory", "approve"),
	("sales", "orders", "update"),
	("sales", "receivables", "create"),
	("accountant", "receivables", "create"),
	("accountant", "receivables", "update"),
]
