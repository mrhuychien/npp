"""/api/do-nap của nppsale → NPP Do Nap (blueprint 02 §4.1). Màn POS / báo cáo gửi bản tóm tắt thời gian nạp (`baoNapSauKhiVe` — chỉ đường
dẫn + cách gọi + ms + kết quả, không tham số / dữ liệu; chủ nhà 03/11/2026: "…load đơn vào pos vẫn có hiện tượng chậm hoặc báo lỗi quá 10s").

Như route nppsale (`src/app/api/do-nap/route.ts`): chỉ người đã đăng nhập (dispatcher trả 401); thân cắt 4.000 ký tự RỒI mới giải JSON (cắt giữa
chừng → 400); JSON hỏng / không phải object → 400; gói thiếu `man` vẫn ghi (nhãn pos-nap); `user` lấy từ phiên — thân có khoá `user` cũng không
đè; trả 204. Thêm của bản Frappe: tách cột (`tu_mo_trang`, `loi`, `dong`, `ttfb_ms`, `dcl_ms`, `so_cau`, `cham`, `mang_*`, `user_agent`) để tra
trên Desk thay nhật ký Vercel; 60 lượt / phút / người (vượt → 429, không ghi); dọn sau 30 ngày (`default_log_clearing_doctypes`).
"""
from __future__ import annotations

import json
import re

import frappe

from .tuyen import YeuCauCu, tuyen

GIOI_HAN_PHUT = 60


def _so_nguyen(v) -> int | None:
	if isinstance(v, bool) or v is None:
		return None
	try:
		return int(round(float(v)))
	except (TypeError, ValueError):
		return None


def _so_thuc(v) -> float | None:
	if isinstance(v, bool) or v is None:
		return None
	try:
		return float(v)
	except (TypeError, ValueError):
		return None


def _con_luot(nguoi: str) -> bool:
	k = frappe.cache.make_key(f"npp_rl:do-nap:{nguoi}")
	n = frappe.cache.incr(k)
	if n == 1:
		frappe.cache.expire(k, 60)
	return n <= GIOI_HAN_PHUT


@tuyen("POST", r"^/api/do-nap$")
def ghi(yc: YeuCauCu):
	user = frappe.session.user
	req = getattr(frappe.local, "request", None)
	tho = req.get_data(as_text=True) if req is not None else None
	if tho is None:  # gọi thẳng (bài kiểm) — thân đã giải
		tho = yc.than if isinstance(yc.than, str) else json.dumps(yc.than, ensure_ascii=False) if yc.than is not None else ""
	try:
		than = json.loads(tho[:4000])
	except ValueError:
		return 400, None
	if not isinstance(than, dict):
		return 400, None
	if not _con_luot(user):
		return 429, None
	man = than.get("man") if isinstance(than.get("man"), str) else ""
	trang = than.get("trang") if isinstance(than.get("trang"), dict) else {}
	mang = than.get("mang") if isinstance(than.get("mang"), dict) else {}
	cham = than.get("cham") if isinstance(than.get("cham"), list) else None
	nv = user if frappe.db.exists("NPP Nhan Vien", user) else None
	ua = (req.headers.get("User-Agent") if req is not None else None) or ""
	d = frappe.get_doc({
		"doctype": "NPP Do Nap", "man": man[:140] or None, "nhan": "bao-cao-nap" if re.match(r"^(bc|pt)-", man) else "pos-nap",
		"ms": _so_nguyen(than.get("ms")) or 0, "tu_mo_trang": 1 if than.get("tuMoTrang") is True else 0,
		"loi": str(than.get("loi"))[:300] if than.get("loi") else None, "dong": _so_nguyen(than.get("dong")),
		"ttfb_ms": _so_nguyen(trang.get("ttfb")), "dcl_ms": _so_nguyen(trang.get("dcl")), "so_cau": _so_nguyen(than.get("soCau")),
		"cham": json.dumps(cham[:6], ensure_ascii=False) if cham is not None else None,
		"mang_loai": str(mang.get("loai"))[:140] if mang.get("loai") else None, "mang_rtt": _so_nguyen(mang.get("rtt")),
		"mang_mbps": _so_thuc(mang.get("mbps")), "nguoi": nv, "user_agent": ua[:300] or None,
		"noi_dung": json.dumps({**than, "user": user}, ensure_ascii=False),
	})
	d.flags.ignore_mandatory = nv is None  # Administrator / việc nền: không có hồ sơ NV
	d.insert(ignore_permissions=True)
	return 204, None
