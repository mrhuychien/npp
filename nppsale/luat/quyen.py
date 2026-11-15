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


# Bộ dòng quyền vai gieo sẵn cho NPP — `_gieo_quyen_mac_dinh` bản mig 202 (chủ nhà 26/09/2026: "NV bán hàng chỉ cần Module bán hàng …
# Còn lại bỏ hết" — bỏ ("sales", "receivables", "create") của mig 166: NVBH không lập phiếu thu). Gieo MỘT lần khi lập đơn vị.
# + Quản lý lập / huỷ phiếu thu (Q4 tạm quyết của đặc tả phiếu thu — 00_quyet_dinh_trien_khai.md mục Q7): mig 215 cấp hai dòng này cho
# các NPP có sẵn lúc chạy (chủ nhà 28/09/2026) và ghi rõ hàm gieo thiếu là "KHÔNG cố ý"; nppsale chưa vá hàm gieo → NPP mới thiếu.
DONG_VAI_GIEO_SAN: list[tuple[str, str, str]] = [
	("manager", "orders", "approve"),
	("manager", "orders", "update"),
	("manager", "returns", "approve"),
	("manager", "inventory", "approve"),
	("manager", "receivables", "create"),
	("manager", "receivables", "update"),
	("sales", "orders", "update"),
	("accountant", "receivables", "create"),
	("accountant", "receivables", "update"),
]


# Ô riêng "Giá vốn, giá trị tồn, lãi gộp" (`inventory.cost`, src/lib/permissions-features.ts) — mặc định của giao diện cho các vai
# BACK_OFFICE_AND_WAREHOUSE = hành động mặc định của vai ở mô-đun cha "inventory" (`macDinhTinhNang`): ô không rỗng là được xem.
GIA_VON_MAC_DINH: dict[str, frozenset] = {
	"manager": frozenset({"read", "export"}),
	"accountant": frozenset({"read"}),
	"warehouse": frozenset({"read", "create", "update", "export"}),
}


def xem_duoc_gia_von(vai: str | None, quyen_rieng: dict[str, bool] | None, dong_vai: dict[tuple[str, str, str], bool] | None) -> bool:
	"""= `xemDuocGiaVon` của giao diện (chủ nhà 25/09/2026: NVBH "Không xem được các thông tin quan trọng của nhà phân phối").

	Chủ NPP luôn được → quyền riêng `inventory.cost.read` của chính người ấy thắng → ô `inventory.cost` của vai: mặc định
	(GIA_VON_MAC_DINH) rồi áp các dòng quyền vai của ô ấy (được → thêm hành động, không → bỏ) — ô còn hành động nào là được xem.
	Quyền mô-đun cha "inventory" KHÔNG mở được ô này (luật ô riêng `laORieng`, chủ nhà 20/10/2026)."""
	if not vai:
		return False
	if vai == "owner":
		return True
	if quyen_rieng and "inventory.cost.read" in quyen_rieng:
		return bool(quyen_rieng["inventory.cost.read"])
	o = set(GIA_VON_MAC_DINH.get(vai, ()))
	for (v, mo_dun, hanh_dong), duoc in (dong_vai or {}).items():
		if v == vai and mo_dun == "inventory.cost":
			if duoc:
				o.add(hanh_dong)
			else:
				o.discard(hanh_dong)
	return bool(o)
