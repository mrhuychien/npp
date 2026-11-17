"""RPC BÁO CÁO (P6) — KHUNG chung cho mọi hàm báo cáo (đặc tả báo cáo P6 §2.0, L5, L9–L12, ❓Q14; nấc 1 §4.2 — mốc M0).

Các hàm báo cáo (`bao_cao_so_ban`, `dashboard_*`, `finance_*`, `hang_khach_da_lay`, `my_sales_target`) dựng ở các mốc sau, giữ đúng tên + tên tham số
nppsale, và CHỈ dùng các hàm phụ ở đây (một luật một chỗ):
- `_ngay(v)`: tham số `date` của Postgres — None → None (SQL NULL); chuỗi sai → 22007; ngày không có thật → 22008 (MỘT luật với `_ngay_pg` đang dùng ở
  phiếu trả / `bao_cao_ton_kho`). ⚠ `frappe.utils.getdate('')` trả HÔM NAY — không gọi thẳng trên giá trị người gửi. Gửi bằng GET thì giá trị là chuỗi
  trong JSON `q`.
- `_ky(tu, den)`: mốc cột datetime giờ VN [tu 00:00, den+1 00:00) — `luat.bao_cao.moc_ky` (L5); `_hom_nay()` = `vn_today()` (mig 140).
- `_la_nv(nc)`: = `user_org_id() IS NOT NULL` (NV đang hoạt động) — Administrator (việc nền) cũng qua. Người khác ⇒ mỗi hàm trả "rỗng đúng dạng" (dict
  mảng rỗng / một dòng toàn 0 / list rỗng), KHÔNG lỗi (ngoại lệ `hang_khach_da_lay` tự kiểm vai — §2.9).
- `_ve(bang, nc, bd, ts)`: vế RLS của BẢNG CỔNG cho người gọi, đặt trên bí danh `bd` (`nppsale.cong.sql.vế_rls`) — hàm nppsale SECURITY INVOKER ⇒ mọi câu
  chèn vế của bảng cổng tương ứng, kể cả bảng nối / truy vấn con (L9). Không đổi sang "đọc hết rồi lọc" (mig 093 "BẢO MẬT — ĐỌC KỸ TRƯỚC KHI SỬA").
- `_so(v, kieu)`: chuẩn hoá số như PostgREST (`truy_van.chuan_gia_tri` — `Decimal` không lọt ra: portal/rest.py in `Decimal` thành CHUỖI); cộng tiếp ở
  Python bằng `luat.so.d`, ROUND nửa xa 0 bằng `luat.so.tron` (L12).
- `_chay(ham, giay)`: thân RPC dưới `max_statement_time` (`frappe.db.execution_timeout` — trả mức cũ khi ra khỏi khối, kể cả khi lỗi); MariaDB `1969`
  (quá hạn) → `LoiCong("57014", "canceling statement due to statement timeout", http=500)` như Postgres (giao diện dịch `QUA_HAN_VI`). `bao_cao_*` 40 s,
  `dashboard_*` / `finance_*` 8 s (`luat.bao_cao.HET_GIO_*`). Mọi câu đọc / RPC khác của cổng cũng đổi `1969` → `57014` ở `cong/api.py::_loi`.
- `_can_nguon(ham, *bang)`: ❓Q14 — hàm cần nguồn chưa có (BẢNG CỔNG chưa đăng ký: `expenses`, `payable_payments`, `payables`…) ném `PGRST202` như hàm
  chưa có (giao diện báo "máy chủ chưa chạy migration mới"), KHÔNG trả 0 im lặng. Kiểm theo bảng cổng đã đăng ký, không theo DocType (`NPP Phieu Chi` có
  từ P4 M6 — chỉ phiếu hao hụt kiểm kê — trước khi có đường lập phiếu chi tay P7).
- Giá vốn dòng chứng từ: hằng `NGUON_DONG_XUAT` / `NGUON_DONG_NHAP_LAI` + `nguon_dong_xuat(dk)` / `nguon_dong_nhap_lai(dk)` của `nppsale.cong.bang.kho`
  (P4 dựng theo Phụ lục A + "Chốt chéo": dòng xuất lẻ `XKL-` / chuyển kho `CKL-` giá 0 như nppsale, trả NCC giá lô từ sổ kho) — DÙNG LẠI, không chép.
  Tồn theo lô: `NGUON_LO` (đủ dòng, kể cả lô hết) / `NGUON_LO_CON_TON` (chỉ lô còn hàng — lọc `Batch.batch_qty > 0` trước khi gộp gói lô) cùng tệp.
"""
from __future__ import annotations

from decimal import Decimal

import frappe

from nppsale.cong.dang_ky import NguCanh, lay
from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import BoThamSo, LoiCong, vế_rls
from nppsale.cong.truy_van import chuan_gia_tri
from nppsale.luat import bao_cao as L


def _ngay(v):
	"""Tham số `date` của Postgres (ép kiểu của PostgREST trước thân hàm): None → None; '' / chữ → 22007; ngày không có thật → 22008."""
	if v is None:
		return None
	from .phieu_tra import _ngay_pg

	return _ngay_pg(v)


def _hom_nay():
	"""`vn_today()` (mig 140) — ngày hôm nay theo giờ site (Asia/Ho_Chi_Minh)."""
	from frappe.utils import getdate, nowdate

	return getdate(nowdate())


def _ky(tu, den):
	"""Mốc [tu 00:00, den+1 00:00) giờ VN cho cột datetime (L5) — `None` ở một đầu → None (như BETWEEN với NULL: không dòng nào)."""
	if tu is None or den is None:
		return None
	return L.moc_ky(tu, den)


def _la_nv(nc: NguCanh) -> bool:
	"""= `user_org_id() IS NOT NULL` — NV đang hoạt động của NPP (tài khoản khoá / người ngoài: vai None); Administrator / việc nền cũng qua."""
	return bool(nc.vai) or nc.bo_qua_rls


def _ve(ten_bang: str, nc: NguCanh, bd: str, ts: BoThamSo) -> str:
	"""Vế RLS của BẢNG CỔNG `ten_bang` cho người gọi trên bí danh `bd`: '1=1' / '1=0' / '(…)' — một luật với câu đọc thẳng của giao diện."""
	from nppsale.cong import bang as B

	B.nap()
	bang = lay(ten_bang)
	if bang is None:
		raise LoiCong("42P01", f'relation "public.{ten_bang}" does not exist', http=404)
	return vế_rls(bang, nc, bd, ts)


def _so(v, kieu: str = "tien"):
	"""DECIMAL / float / int → int khi chẵn, float khi lẻ; None giữ None (L12)."""
	if v is None:
		return None
	return chuan_gia_tri(kieu, v if isinstance(v, Decimal) else Decimal(str(v)))


def _chay(ham, giay: float = L.HET_GIO_BAO_CAO):
	"""Chạy thân RPC dưới `max_statement_time` = `giay`; câu quá hạn (MariaDB 1969) → 57014 + câu Postgres. Lỗi khác ném nguyên (không đổi thành 57014).
	MariaDB không huỷ cả giao dịch khi một câu quá hạn (khác Postgres) — RPC đọc không ghi nên không ảnh hưởng; mức hẹn giờ của phiên được trả lại."""
	try:
		with frappe.db.execution_timeout(giay):
			return ham()
	except (LoiCong, NppLoi):
		raise
	except Exception as e:  # noqa: BLE001 — chỉ đổi đúng lỗi quá hạn, lỗi khác ném tiếp
		if frappe.db.is_statement_timeout(e):
			raise LoiCong(L.MA_QUA_HAN, L.CAU_QUA_HAN, http=500) from None
		raise


def _can_nguon(ham: str, *bang: str) -> None:
	"""❓Q14 (đặc tả §0.4, §2.13 — soát thiếu S4): mọi bảng cổng `bang` phải đã đăng ký; thiếu → PGRST202 đúng câu "hàm chưa có" của cổng (404)."""
	from nppsale.cong import bang as B

	B.nap()
	if any(lay(b) is None for b in bang):
		raise LoiCong("PGRST202", f"Could not find the function public.{ham} in the schema cache", http=404)
