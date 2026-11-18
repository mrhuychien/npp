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

Hàm báo cáo đã dựng (mốc M1 — §4.2 nấc 2): `bao_cao_so_ban` (§2.1). `bao_cao_ton_kho` (§2.2) dựng ở P4 M9 — `nppsale.rpc.kho` (dùng khung ở đây).
Mốc M2 (§4.2 nấc 3 + 4): `dashboard_summary` / `dashboard_channel_revenue` / `dashboard_top_customers` (§2.3-2.5 — INVOKER: vế RLS bảng cổng của
người gọi, kể cả LEFT JOIN khách), `hang_khach_da_lay` (§2.9 — DEFINER: đọc thẳng sổ, tự kiểm vai, CHỈ số lượng theo đơn vị cơ sở), `my_sales_target`
(§2.11 — trả 0 tới khi P7 có `NPP Cau Hinh Luong`; chỗ nối: `DT_CAU_HINH_LUONG` / `muc_tieu_doanh_so`).
"""
from __future__ import annotations

import re
from decimal import Decimal

import frappe

from nppsale.cong.dang_ky import NguCanh, lay
from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai, xem_gia_von
from nppsale.cong.sql import BoThamSo, LoiCong, vế_rls
from nppsale.cong.truy_van import chuan_gia_tri
from nppsale.luat import bao_cao as L
from nppsale.luat.so import d
from nppsale.luat.so import ra as ra_so

from . import rpc


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


# ================================================================================================ bao_cao_so_ban (§2.1)
# Bộ cột ĐÚNG của hàm nppsale (mig 256 — `to_jsonb(h)` / `jsonb_build_object`): (khoá ra, cột của BẢNG CỔNG cùng nghĩa). Biểu thức + kiểu lấy từ CHÍNH
# `CotDef` của bảng cổng (`lay(bảng).cot_def(cột)`) — đổi ánh xạ một nơi là đường một lượt và đường lùi đọc từng bảng (`docTungBang`) cùng đổi (đặc tả
# §2.1 "một chỗ", CLAUDE.md đợt 7: hai đường phải ra y hệt).
COT_HD = tuple((k, k) for k in ("id", "invoice_code", "invoice_date", "order_id", "status", "total", "subtotal", "vat", "customer_id", "sales_user_id",
	"posted_by", "payment_terms"))
COT_DONG_HD = tuple((k, k) for k in ("id", "invoice_id", "product_id", "unit_name", "conversion_factor", "quantity", "unit_price", "line_total",
	"is_exchange", "line_discount", "order_line_id"))
COT_TRA = (*((k, k) for k in ("id", "status", "customer_id", "invoice_id", "credit_note_amount", "created_at", "revenue_date", "sales_user_id",
	"reason", "credit_with_invoice")), ("ma", "return_code"))  # `ma` = to_jsonb(r)->>'return_code' (PT-0001)
COT_DONG_TRA = tuple((k, k) for k in ("return_id", "product_id", "unit_name", "quantity", "line_total", "unit_price"))
KHOI_SO_BAN = ("hd", "dong_hd", "tra", "dong_tra", "gv", "gv_tra")
# ❓Q12 (đề xuất — CFD-07, BP §2.11): số việc Repost Item Valuation còn chờ / đang chạy → khoá THÊM `tinh_lai_gia_von` (⚠K so với đúng bộ khoá mig 256;
# giao diện cũ bỏ qua khoá lạ — `tuMotLuot` chỉ đọc khoá biết; lớp phủ hiện dải "đang tính lại giá vốn (N việc)"). Việc ghi lùi về ngày ≤ cuối kỳ mới
# đổi giá vốn các chứng từ trong kỳ (lõi tính lại từ `posting_date` của việc trở đi).
KHOA_TINH_LAI = "tinh_lai_gia_von"
SQL_TINH_LAI = ("SELECT COUNT(*) FROM `tabRepost Item Valuation` WHERE `docstatus` = 1 AND `status` IN ('Queued', 'In Progress')"
	" AND (%(den)s IS NULL OR `posting_date` <= %(den)s)")
# HĐ doanh thu (L1): Sales Invoice ghi sổ, không phải tờ ghi có, không phải tờ đầu kỳ / HĐ cũ H3 — một luật với cổng `sales_invoices` (`status = 'posted'`)
HD_DOANH_THU = "si.`docstatus` = 1 AND si.`is_return` = 0 AND IFNULL(si.`is_opening`, 'No') = 'No'"
DK_HD = HD_DOANH_THU + " AND si.`posting_date` BETWEEN %(tu)s AND %(den)s"


def _bieu_cot(bang: str, cot: tuple, bd: str) -> list[tuple[str, str, str]]:
	"""[(khoá ra, biểu thức SQL trên bí danh `bd`, kiểu)] từ `CotDef` của bảng cổng."""
	b = lay(bang)
	ra = []
	for khoa, ten in cot:
		cd = b.cot_def(ten)
		ra.append((khoa, cd.sql.replace("{t}", bd), cd.kieu))
	return ra


def _dong(ds, bieu: list[tuple[str, str, str]]) -> list[dict]:
	"""Dòng thô (tuple) → dict đã chuẩn hoá như PostgREST (L12): số int / float, ngày 'YYYY-MM-DD', giờ ISO +07:00, bool thật, chuỗi rỗng → null
	(Frappe lưu '' cho Link / Data trống — Postgres là NULL; `tuMotLuot` tự đổi `sales_user_id` null → '')."""
	ra = []
	for r in ds:
		x = {}
		for (khoa, _bt, kieu), v in zip(bieu, r, strict=True):
			v = chuan_gia_tri(kieu, v)
			x[khoa] = None if v == "" else v
		ra.append(x)
	return ra


def _sql_chon(bieu: list[tuple[str, str, str]]) -> str:
	return ", ".join(f"{b} AS `{k}`" for k, b, _ in bieu)


def tinh_lai_gia_von(den=None) -> int:
	"""❓Q12: số việc Repost Item Valuation (đã gửi) còn `Queued` / `In Progress` có ngày bắt đầu tính lại ≤ `den` (None = mọi việc) — 0 khi chạy hết."""
	return int(frappe.db.sql(SQL_TINH_LAI, {"den": den})[0][0] or 0)


@rpc("bao_cao_so_ban", ghi=False)
def bao_cao_so_ban(p_tu=None, p_den=None):
	"""Số bán MỘT LƯỢT (đặc tả §2.1; mig 204 → 218 → 228 → 256): dòng thô cho Báo cáo tổng hợp / Nhân viên / báo cáo cũ / phân tích
	(`docSoBanMotLuot` / `docSoBanKy` ← `goiMotLuot`, GET 45 s một lượt). Máy chủ KHÔNG tính doanh thu / chênh lệch / phân bổ — chỉ dòng thô + giá vốn
	gộp sẵn theo mặt hàng (`gv`) và theo (phiếu trả, mặt hàng) (`gv_tra`). → dict đúng 6 khoá `{hd, dong_hd, tra, dong_tra, gv, gv_tra}` (mỗi khoá một
	list — `goiMotLuot` coi giá trị không phải object là "chưa có hàm") + `tinh_lai_gia_von` (❓Q12).

	nppsale SECURITY INVOKER ⇒ vế RLS của BẢNG CỔNG cho người gọi ở mọi câu (L9): `hd` / `dong_hd` theo `sales_invoices` (NVBH: HĐ mình đứng tên hoặc của
	đơn mình đứng tên), `tra` / `dong_tra` / `gv_tra` theo `returns`, `gv` không lọc (phiếu kho: mọi NV). Người không phải NV đang hoạt động / kỳ thiếu
	một đầu / kỳ ngược → 6 mảng rỗng (BETWEEN NULL không ra dòng), không lỗi. Tham số sai dạng → 22007 / 22008 TRƯỚC thân hàm (ép kiểu `date` của
	PostgREST); thân chạy dưới hẹn 40 s (quá hạn → 57014).

	Khác nppsale có chủ ý (⚠K — 00_quyet_dinh Q10): id = mã chứng từ, NV = email; `gv` theo `posting_date` của chứng từ (❓Q1 — HĐ ghi lùi ngày: giá vốn
	cùng kỳ với doanh thu); dòng xuất kho lẻ / chuyển kho giá 0 như nppsale (❓Q2 — "Chốt chéo" với P4); HĐ huỷ (docstatus 2) rơi với MỌI vai (❓Q9 — không
	tái hiện quirk RLS `NOT EXISTS`); `gv[].tien` / `gv_tra[].tien` = null với người thiếu ô `inventory.cost` (❓Q3 — nppsale chỉ che ở giao diện);
	không có phiếu "Đảo phiếu trả" (huỷ = cancel chứng từ lõi — nppsale loại phiếu ấy nên cùng số)."""
	tu, den = _ngay(p_tu), _ngay(p_den)  # ép kiểu như PostgREST TRƯỚC thân hàm (22007 / 22008)
	return _chay(lambda: _so_ban(tu, den), L.HET_GIO_BAO_CAO)


def _so_ban(tu, den) -> dict:
	from nppsale.cong.bang.kho import nguon_dong_nhap_lai, nguon_dong_xuat

	nc = hien_tai()
	ra: dict = {k: [] for k in KHOI_SO_BAN}
	ra[KHOA_TINH_LAI] = 0
	if not _la_nv(nc) or tu is None or den is None or tu > den:
		return ra
	ts = BoThamSo()
	ve_hd = _ve("sales_invoices", nc, "si", ts)
	ve_pt = _ve("returns", nc, "r", ts)
	tham = {**ts.gia_tri, "tu": tu, "den": den}
	hd = _bieu_cot("sales_invoices", COT_HD, "si")
	ra["hd"] = _dong(frappe.db.sql(f"""SELECT {_sql_chon(hd)} FROM `tabSales Invoice` si WHERE {DK_HD} AND {ve_hd}
		ORDER BY si.`name`""", tham), hd)
	# MỌI dòng của HĐ thấy được, KỂ CẢ dòng hàng đổi (giao diện tự bỏ — L3); ORDER BY id = khoá `.order('id')` của đường lùi (dòng CUỐI mỗi HĐ nhận phần
	# dư khi chia tiền — L12)
	dong_hd = _bieu_cot("sales_invoice_lines", COT_DONG_HD, "ii")
	ra["dong_hd"] = _dong(frappe.db.sql(f"""SELECT {_sql_chon(dong_hd)} FROM `tabSales Invoice Item` ii
		JOIN `tabSales Invoice` si ON si.`name` = ii.`parent`
		WHERE ii.`parenttype` = 'Sales Invoice' AND {DK_HD} AND {ve_hd} ORDER BY ii.`name`""", tham), dong_hd)
	# phiếu trả có ngày trừ doanh số trong kỳ — KHÔNG lọc trạng thái: luật nằm sẵn trong `ngay_tru_doanh_so` (= revenue_date, mig 192 — L2)
	dk_pt = f"r.`ngay_tru_doanh_so` BETWEEN %(tu)s AND %(den)s AND {ve_pt}"
	tra = _bieu_cot("returns", COT_TRA, "r")
	ra["tra"] = _dong(frappe.db.sql(f"SELECT {_sql_chon(tra)} FROM `tabNPP Phieu Tra` r WHERE {dk_pt} ORDER BY r.`name`", tham), tra)
	# dòng KHÔNG đổi của các phiếu ấy (lọc ở máy chủ — L3); không có cột hệ số (L6: giao diện tra danh mục hiện tại)
	dong_tra = _bieu_cot("return_lines", COT_DONG_TRA, "d")
	ra["dong_tra"] = _dong(frappe.db.sql(f"""SELECT {_sql_chon(dong_tra)} FROM `tabNPP Phieu Tra Dong` d
		JOIN `tabNPP Phieu Tra` r ON r.`name` = d.`parent`
		WHERE d.`parenttype` = 'NPP Phieu Tra' AND IFNULL(d.`hang_doi`, 0) = 0 AND {dk_pt} ORDER BY d.`name`""", tham), dong_tra)
	xem = xem_gia_von(nc)
	# giá vốn XUẤT của kỳ theo mặt hàng (L4-b): dòng chứng từ xuất đã ghi sổ có `posting_date` trong kỳ — điều kiện ngày chèn vào TỪNG nhánh (giữ chỉ mục)
	nguon_xuat = nguon_dong_xuat("AND {t}.`posting_date` BETWEEN %(tu)s AND %(den)s")
	gv = frappe.db.sql(f"""SELECT x.`hang`, SUM(x.`sl`), SUM(x.`sl` * x.`gia`) FROM {nguon_xuat} x
		GROUP BY x.`hang` ORDER BY x.`hang`""", tham)
	ra["gv"] = [{"product_id": h, "sl": _so(sl, "so"), "tien": _so(tien) if xem else None} for h, sl, tien in gv]
	# giá vốn hàng trả ĐÃ nhập lại kho theo (phiếu trả ∈ `tra`, mặt hàng) (L4-d): nối Link `npp_phieu_tra` của NL- / tờ ghi có có kho, gồm dòng đổi, không
	# lọc ngày chứng từ nhập, không lọc trạng thái phiếu — vế "phiếu trong kỳ" chèn vào từng nhánh (chỉ mục `npp_phieu_tra`)
	nguon_nhap = nguon_dong_nhap_lai("AND {t}.`npp_phieu_tra` IN (SELECT r.`name` FROM `tabNPP Phieu Tra` r WHERE " + dk_pt + ")")
	gv_tra = frappe.db.sql(f"""SELECT x.`pt`, x.`hang`, SUM(x.`sl` * x.`gia`) FROM {nguon_nhap} x
		GROUP BY x.`pt`, x.`hang` ORDER BY x.`pt`, x.`hang`""", tham)
	ra["gv_tra"] = [{"return_id": pt, "product_id": h, "tien": _so(tien) if xem else None} for pt, h, tien in gv_tra]
	ra[KHOA_TINH_LAI] = tinh_lai_gia_von(den)
	return ra


# ================================================================================================ dashboard_* (§2.3-2.5 — /dashboard)
# Ba hàm nppsale `RETURNS TABLE`, SECURITY INVOKER (mig 093 → 126 → 192 thuần → 256): mọi câu chèn vế RLS BẢNG CỔNG của người gọi — HĐ theo
# `sales_invoices`, phiếu trả theo `returns`, dòng nợ theo `receivables` (thủ kho: không dòng nào — ❓Q10 chép y), khách theo `customers` đặt TRONG điều
# kiện LEFT JOIN (khách không thấy được → kênh 'Khác' / tên 'N/A', tiền vẫn cộng — đúng hành vi LEFT JOIN dưới RLS). Doanh thu THUẦN = HĐ doanh thu
# (L1) có ngày HĐ ≥ p - tiền trả (`tien_tra` = credit_note_amount) của phiếu có ngày trừ doanh số ≥ p (L2 — không lọc trạng thái, luật nằm sẵn trong
# `ngay_tru_doanh_so`); KHÔNG cận trên (❓Q11 chép y — phiếu đề ngày tương lai vẫn trừ vào "kỳ này"), âm được. p NULL → so với NULL sai: không HĐ / phiếu
# nào (hai số công nợ của `dashboard_summary` vẫn đủ). Người không phải NV đang hoạt động → rỗng đúng dạng (một dòng 0 / list rỗng), không lỗi. Thân dưới
# hẹn 8 s (statement_timeout của vai `authenticated`; quá hạn → 57014). Gọi GET (`rpc(…, {get: true})` — dashboard/page.tsx:121-123); lỗi → màn NÉM
# "Không thể tải dữ liệu" (không đường lùi, không hiện 0 thay lỗi).
KENH_KHAC = "Khác"
TOP_MAC_DINH = 5  # `p_limit integer DEFAULT 5` — thiếu tham số
TOP_TRAN = 100  # LIMIT GREATEST(1, LEAST(p_limit, 100)) — p_limit NULL → 100 (LEAST của Postgres bỏ qua NULL)
_THIEU = object()  # tham số KHÔNG gửi (khác gửi null)
_RE_SO_NGUYEN = re.compile(r"\s*[+-]?\d+\s*")


def _so_nguyen(v) -> int:
	"""Tham số `integer` của Postgres (PostgREST ép trước thân hàm — json_to_record / chữ của GET): số nguyên JSON hoặc chuỗi số (bỏ khoảng trắng hai
	đầu, có dấu +/-) → int; số thực (kể cả 5.0), bool, chữ khác → 22P02 `invalid input syntax for type integer: "<giá trị>"`; ngoài int4 → 22003 (đo trên
	bản tham chiếu: `json_to_record('{"a": 5.0}') AS x(a integer)` → 22P02 "5.0")."""
	if isinstance(v, bool):
		raise LoiCong("22P02", f'invalid input syntax for type integer: "{str(v).lower()}"')
	if isinstance(v, int):
		n = v
	elif isinstance(v, str) and _RE_SO_NGUYEN.fullmatch(v):
		n = int(v.strip())
	else:
		raise LoiCong("22P02", f'invalid input syntax for type integer: "{v}"')
	if not -2147483648 <= n <= 2147483647:
		raise LoiCong("22003", f'value "{v.strip() if isinstance(v, str) else v}" is out of range for type integer')
	return n


def gioi_han_top(p_limit=_THIEU) -> int:
	"""`LIMIT GREATEST(1, LEAST(p_limit, 100))` của nppsale tính ở PYTHON (đặc tả §2.5): thiếu tham số → 5 (DEFAULT); null → 100 (LEAST bỏ qua NULL);
	còn lại kẹp [1, 100]. KHÔNG chép nguyên biểu thức vào SQL: GREATEST / LEAST của MariaDB trả NULL khi có đối số NULL."""
	if p_limit is _THIEU:
		return TOP_MAC_DINH
	if p_limit is None:
		return TOP_TRAN
	return max(1, min(_so_nguyen(p_limit), TOP_TRAN))


def _ve_tong_quan(nc: NguCanh, ts: BoThamSo, khach: bool = False) -> dict:
	"""Vế RLS của các bảng cổng dashboard đọc, trên bí danh cố định: HĐ `si`, phiếu trả `r`, khách `c` (nếu cần)."""
	ve = {"hd": _ve("sales_invoices", nc, "si", ts), "pt": _ve("returns", nc, "r", ts)}
	if khach:
		ve["kh"] = _ve("customers", nc, "c", ts)
	return ve


@rpc("dashboard_summary", ghi=False)
def dashboard_summary(p_period_start=None):
	"""Bốn thẻ `/dashboard` (đặc tả §2.3; mig 093 → 126 → 192 → 256): đúng MỘT dòng `[{period_revenue, period_orders, open_receivables, overdue_count}]`
	(`motDong` / `.maybeSingle()` của portal gỡ list một phần tử).
	- `period_revenue` = Σ tiền HĐ doanh thu ngày HĐ ≥ p - Σ tiền trả phiếu có ngày trừ doanh số ≥ p (thuần, không kẹp 0, không cận trên — ❓Q11);
	- `period_orders` = số ĐƠN khác nhau của các HĐ ấy (`COUNT(DISTINCT order_id)` — HĐ không đơn không đếm: '' của Frappe → NULL; không trừ hàng trả);
	- `open_receivables` = Σ(số tiền - đã thu) MỌI dòng nợ chưa `paid` thấy được — KHÔNG theo kỳ, KHÔNG kẹp từng dòng (dư có trừ vào; CLAUDE.md "Công nợ
	  ÂM", mig 186) — cùng tập dòng với `receivables_summary.total_outstanding` (VB-D07); gồm tờ đầu kỳ `DK-` / HĐ cũ H3 (VB-E10);
	- `overdue_count` = số dòng mang DẤU `overdue` (bấm tay — không phải theo hạn).
	Thủ kho: hai số đầu đủ (thấy mọi HĐ), hai số công nợ 0 (không chính sách đọc `receivables` — ❓Q10 chép y)."""
	p = _ngay(p_period_start)  # ép kiểu `date` như PostgREST TRƯỚC thân hàm (22007 / 22008)
	return _chay(lambda: _tong_quan(p), L.HET_GIO_NHANH)


def _tong_quan(p) -> list[dict]:
	nc = hien_tai()
	ra = {"period_revenue": 0, "period_orders": 0, "open_receivables": 0, "overdue_count": 0}
	if not _la_nv(nc):
		return [ra]
	ts = BoThamSo()
	ve = _ve_tong_quan(nc, ts)
	ve_no = _ve("receivables", nc, "cn", ts)
	hd = f"FROM `tabSales Invoice` si WHERE {HD_DOANH_THU} AND si.`posting_date` >= %(p)s AND {ve['hd']}"
	dt, don, no, qh = frappe.db.sql(f"""SELECT
		(SELECT COALESCE(SUM(IFNULL(si.`grand_total`, 0)), 0) {hd})
		- (SELECT COALESCE(SUM(IFNULL(r.`tien_tra`, 0)), 0) FROM `tabNPP Phieu Tra` r WHERE r.`ngay_tru_doanh_so` >= %(p)s AND {ve['pt']}),
		(SELECT COUNT(DISTINCT NULLIF(si.`npp_don_hang`, '')) {hd}),
		(SELECT COALESCE(SUM(IFNULL(cn.`so_tien`, 0) - IFNULL(cn.`da_thu`, 0)), 0) FROM `tabNPP Cong No` cn WHERE cn.`trang_thai` <> 'paid' AND {ve_no}),
		(SELECT COUNT(*) FROM `tabNPP Cong No` cn WHERE cn.`trang_thai` = 'overdue' AND {ve_no})""", {**ts.gia_tri, "p": p})[0]
	return [{"period_revenue": _so(dt), "period_orders": int(don or 0), "open_receivables": _so(no), "overdue_count": int(qh or 0)}]


@rpc("dashboard_channel_revenue", ghi=False)
def dashboard_channel_revenue(p_period_start=None):
	"""Doanh thu thuần theo KÊNH (đặc tả §2.4): `[{channel, total}]` xếp `total` giảm. Kênh = mã tuyến THÔ của khách (`Customer.npp_tuyen` — không trim,
	không dịch sang tên: `/dashboard` hiện nguyên chuỗi); rỗng / khách không thấy được → 'Khác'. Hàng trả trừ vào kênh của KHÁCH TRẢ. Nhóm theo chuỗi
	ĐÚNG như Postgres (gộp ở Python — `GROUP BY` của MariaDB `utf8mb4_unicode_ci` gộp 'GT' / 'gt ' / 'gT', R8); khoá phụ `channel` theo điểm mã chỉ để
	thứ tự tất định khi bằng tiền (nppsale không định). p NULL / người không phải NV → []."""
	p = _ngay(p_period_start)
	return _chay(lambda: _theo_kenh(p), L.HET_GIO_NHANH)


def _theo_kenh(p) -> list[dict]:
	nc = hien_tai()
	if not _la_nv(nc) or p is None:
		return []
	ts = BoThamSo()
	ve = _ve_tong_quan(nc, ts, khach=True)
	ds = frappe.db.sql(f"""SELECT c.`npp_tuyen`, SUM(x.`tien`) FROM (
			SELECT si.`customer` AS kh, IFNULL(si.`grand_total`, 0) AS tien FROM `tabSales Invoice` si
			WHERE {HD_DOANH_THU} AND si.`posting_date` >= %(p)s AND {ve['hd']}
			UNION ALL
			SELECT r.`khach_hang`, -IFNULL(r.`tien_tra`, 0) FROM `tabNPP Phieu Tra` r WHERE r.`ngay_tru_doanh_so` >= %(p)s AND {ve['pt']}) x
		LEFT JOIN `tabCustomer` c ON c.`name` = x.`kh` AND {ve['kh']}
		GROUP BY x.`kh`, c.`npp_tuyen`""", {**ts.gia_tri, "p": p})
	gom: dict = {}
	for tuyen, tien in ds:
		kenh = KENH_KHAC if tuyen is None or tuyen == "" else tuyen  # COALESCE(NULLIF(c.channel, ''), 'Khác')
		gom[kenh] = gom.get(kenh, Decimal(0)) + d(tien)
	return [{"channel": k, "total": ra_so(v)} for k, v in sorted(gom.items(), key=lambda x: (-x[1], x[0]))]


@rpc("dashboard_top_customers", ghi=False)
def dashboard_top_customers(p_period_start=None, p_limit=_THIEU):
	"""Top khách theo doanh thu THUẦN (đặc tả §2.5): `[{customer_id, store_name, total, order_count}]` xếp `total` giảm, tối đa `gioi_han_top(p_limit)`
	dòng. Chỉ khách CÓ HĐ doanh thu từ p (khách chỉ có hàng trả không hiện); `total` = tiền HĐ - tiền trả của khách (âm được); `order_count` = số đơn
	khác nhau của các HĐ; `store_name` khách không thấy được → 'N/A' (thủ kho — ❓Q10). Khoá phụ `customer_id` chỉ để tất định khi bằng tiền. `p_limit`
	không phải số nguyên → 22P02 (ép kiểu `integer` của PostgREST)."""
	p = _ngay(p_period_start)
	lim = gioi_han_top(p_limit)
	return _chay(lambda: _top_khach(p, lim), L.HET_GIO_NHANH)


def _top_khach(p, lim: int) -> list[dict]:
	nc = hien_tai()
	if not _la_nv(nc) or p is None:
		return []
	ts = BoThamSo()
	ve = _ve_tong_quan(nc, ts, khach=True)
	ds = frappe.db.sql(f"""SELECT b.`kh`, c.`customer_name`, b.`tien` - IFNULL(t.`tien`, 0) AS `con`, b.`n`
		FROM (SELECT si.`customer` AS kh, SUM(IFNULL(si.`grand_total`, 0)) AS tien, COUNT(DISTINCT NULLIF(si.`npp_don_hang`, '')) AS n
			FROM `tabSales Invoice` si
			WHERE {HD_DOANH_THU} AND si.`posting_date` >= %(p)s AND IFNULL(si.`customer`, '') <> '' AND {ve['hd']}
			GROUP BY si.`customer`) b
		LEFT JOIN (SELECT r.`khach_hang` AS kh, SUM(IFNULL(r.`tien_tra`, 0)) AS tien FROM `tabNPP Phieu Tra` r
			WHERE r.`ngay_tru_doanh_so` >= %(p)s AND {ve['pt']} GROUP BY r.`khach_hang`) t ON t.`kh` = b.`kh`
		LEFT JOIN `tabCustomer` c ON c.`name` = b.`kh` AND {ve['kh']}
		ORDER BY `con` DESC, b.`kh`
		LIMIT {int(lim)}""", {**ts.gia_tri, "p": p})
	return [{"customer_id": kh, "store_name": ten if ten is not None else "N/A", "total": _so(con), "order_count": int(n or 0)}
		for kh, ten, con, n in ds]


# ================================================================================================ hang_khach_da_lay (§2.9 — mig 246)
# Hàm nppsale `plpgsql STABLE SECURITY DEFINER` (chủ nhà 15/10/2026: "dskh tuyến đó, đã lấy hàng gì, số lượng, hàng cty nào mà nv đó làm … thể hiện
# luôn trên máy của nv"): KHÔNG áp RLS bảng — đọc thẳng sổ, tự kiểm vai, luật lọc riêng của hàm (NV thấy hàng NV KHÁC bán cho khách mình phụ trách —
# VB-C04). CHỈ số lượng (không tiền), quy về ĐƠN VỊ CƠ SỞ (CLAUDE.md "Quy đổi đơn vị"): dòng HĐ theo hệ số CHỤP trên dòng (> 0) rồi danh mục; dòng trả
# theo danh mục HIỆN TẠI (❓Q7 — dòng trả không chụp hệ số ở nppsale; khớp `soLuongCoSoDongTra` của giao diện). Hàng trả = phiếu có ngày trừ doanh số
# (đã trừ — mig 192; không lọc trạng thái: phiếu tự sinh Chờ xử lý có tính), bỏ hàng đổi. Gọi POST (`napHangDaLay` — ban-giao.ts:316; ghi=False nhận
# cả GET); PGRST202 → giao diện coi là "chưa chạy mig 246".
VAI_XEM_HANG_DA_LAY = ("owner", "manager", "accountant")
KHONG_DU_QUYEN = "KHONG_DU_QUYEN"
KHONG_DU_QUYEN_VAI = "KHONG_DU_QUYEN: vai này không xem hàng khách đã lấy"
KHONG_TIM_THAY_NV = "KHONG_TIM_THAY_NV"
CHUA_CO_TUYEN = "__chua_co_tuyen"  # nhóm "chưa có tuyến" (CHUA_CO_TUYEN của giao diện — src/lib/customers/ban-giao.ts)
# hệ số về đơn vị cơ sở — dòng HĐ: chụp trên dòng (> 0) trước, rồi danh mục (cùng luật `heSoQuyDoi`); dòng trả: danh mục hiện tại (❓Q7)
HE_SO_DONG_HD = ("CASE WHEN ii.`conversion_factor` > 0 THEN ii.`conversion_factor` WHEN IFNULL(ii.`uom`, '') = '' OR ii.`uom` = it.`stock_uom` THEN 1 "
	"ELSE COALESCE(NULLIF(u.`conversion_factor`, 0), 1) END")
HE_SO_DONG_TRA = ("CASE WHEN IFNULL(d.`don_vi`, '') = '' OR d.`don_vi` = it.`stock_uom` THEN 1 ELSE COALESCE(NULLIF(u.`conversion_factor`, 0), 1) END")


def _mang(v, ten: str) -> list | None:
	"""Tham số mảng (`uuid[]` / `text[]`) gửi qua JSON: None → None (SQL NULL); list → các phần tử CHUỖI (phần tử khác bỏ — như không khớp, đặc tả §2.9);
	giá trị không phải mảng → 22P02 `malformed array literal` (PostgREST ép kiểu mảng)."""
	if v is None:
		return None
	if not isinstance(v, (list, tuple)):
		raise LoiCong("22P02", f'malformed array literal: "{v}"', chi_tiet=f'Array value must start with "{{" or dimension information. ({ten})')
	return [x for x in v if isinstance(x, str)]


def _diem_ma(s) -> str:
	"""Khoá xếp chữ theo ĐIỂM MÃ (collation C.UTF-8 của bản tham chiếu: hoa trước thường, không so dấu — ❓Q8); None xếp như chuỗi rỗng."""
	return "" if s is None else str(s)


@rpc("hang_khach_da_lay", ghi=False)
def hang_khach_da_lay(p_nv=None, p_khach=None, p_tu=None, p_tuyen=None):
	"""Hàng khách đã lấy (đặc tả §2.9; mig 246): → `{nv, khach, hang, sp, ncc}`.
	1. Người gọi không phải NV đang hoạt động → P0001 KHONG_DU_QUYEN. NVBH → NV = CHÍNH MÌNH (bỏ qua `p_nv`); chủ / QL / KT → NV = `p_nv` (có mà không phải
	   NV của NPP — mọi trạng thái → KHONG_TIM_THAY_NV); vai khác (thủ kho, tài xế) → "KHONG_DU_QUYEN: vai này không xem hàng khách đã lấy".
	2. Không NV và không danh sách khách → trả ngay rỗng (không đọc cả sổ). `p_khach = []` → không khách nào (khác NULL).
	3. Khách K: (`p_khach` NULL hoặc trong `p_khach`) ∧ (không NV hoặc NV được phân công ĐANG làm — chính HOẶC phụ) ∧ (`p_tuyen` rỗng / NULL hoặc mã tuyến
	   đã trim — rỗng thì '__chua_co_tuyen' — nằm trong `p_tuyen`, so ĐÚNG chuỗi như Postgres). Không lọc trạng thái khách.
	4. Hàng S: không NV, hoặc NCC chính rỗng (hàng chưa gán công ty — ai cũng thấy), hoặc NCC chính ∈ công ty NV làm (như RLS sản phẩm mig 081; NCC chính =
	   cột `products.primary_supplier_id` của cổng — một biểu thức).
	5. `hang` theo (khách, hàng): đi = HĐ ghi sổ (không cận trên, KHÔNG lọc NV đứng tên HĐ), trả = phiếu có ngày trừ doanh số; `p_tu` lọc cả hai từ ngày
	   ấy; ROUND 3 số lẻ TRƯỚC khi trừ (`sl` = round(đi) - round(trả), âm được); `lan` = số HĐ; `cuoi` = ngày HĐ cuối (null nếu chỉ có trả).
	Thứ tự (❓Q8 — xếp ở Python theo điểm mã như C.UTF-8): `khach` (tên, id), `hang` (khách, sl giảm, hàng), `sp` (tên, id), `ncc` (tên, id).
	Thân dưới hẹn 8 s (statement_timeout của vai `authenticated`); tham số sai dạng → 22007 / 22008 / 22P02 trước thân hàm."""
	tu = _ngay(p_tu)
	khach, tuyen = _mang(p_khach, "p_khach"), _mang(p_tuyen, "p_tuyen")
	tuyen_loc = bool(p_tuyen)  # cardinality(p_tuyen) > 0 — kể cả khi mọi phần tử bị bỏ (không khớp gì)
	nv_goi = None if p_nv is None else str(p_nv)
	return _chay(lambda: _hang_da_lay(nv_goi, khach, tu, tuyen, tuyen_loc), L.HET_GIO_NHANH)


def _hang_da_lay(p_nv, khach, tu, tuyen, tuyen_loc) -> dict:
	nc = hien_tai()
	if not nc.vai:
		raise NppLoi(KHONG_DU_QUYEN)
	if nc.vai == "sales":
		nv = nc.user  # NVBH: chỉ khách + công ty của chính mình (bỏ qua p_nv)
	elif nc.vai in VAI_XEM_HANG_DA_LAY:
		nv = p_nv
		if nv is not None and not frappe.db.exists("NPP Nhan Vien", nv):
			raise NppLoi(KHONG_TIM_THAY_NV)
	else:
		raise NppLoi(KHONG_DU_QUYEN_VAI)
	ra = {"nv": nv, "khach": [], "hang": [], "sp": [], "ncc": []}
	if nv is None and khach is None:
		return ra
	cong_ty = frappe.get_all("NPP Nhan Vien Cong Ty", filters={"parent": nv, "parenttype": "NPP Nhan Vien"}, pluck="nha_cung_cap") if nv else []
	K = _khach_cua(nv, khach, tuyen, tuyen_loc)
	hang = _hang_theo_khach(K, nv, tu) if K else []
	ra["hang"] = hang
	ra["khach"] = _thong_tin_khach(K) if K else []
	P = sorted({h["p"] for h in hang})
	sp = _thong_tin_hang(P) if P else []
	ra["sp"] = sp
	ncc = {x["ncc"] for x in sp if x["ncc"]} | set(cong_ty)
	ra["ncc"] = [{"id": ten, "name": ten_ncc} for ten, ten_ncc in sorted(frappe.db.sql("""SELECT s.`name`, s.`supplier_name` FROM `tabSupplier` s
		WHERE s.`name` IN %(ncc)s""", {"ncc": tuple(ncc)}), key=lambda x: (_diem_ma(x[1]), x[0]))] if ncc else []
	return ra


def _khach_cua(nv, khach, tuyen, tuyen_loc) -> list[str]:
	"""Tập khách K (bước 3): lọc người / danh sách ở SQL, lọc tuyến ở Python — so ĐÚNG chuỗi như `= ANY(text[])` của Postgres (collation của MariaDB không
	phân biệt hoa thường / dấu); trim như `btrim` (khoảng trắng)."""
	if khach is not None and not khach:
		return []
	dk, tham = ["1 = 1"], {}
	if khach is not None:
		dk.append("c.`name` IN %(khach)s")
		tham["khach"] = tuple(khach)
	if nv is not None:
		dk.append("EXISTS (SELECT 1 FROM `tabNPP Phan Cong Khach` pc WHERE pc.`khach` = c.`name` AND pc.`nhan_vien` = %(nv)s "
			"AND pc.`trang_thai` = 'active')")
		tham["nv"] = nv
	ds = frappe.db.sql(f"SELECT c.`name`, c.`npp_tuyen` FROM `tabCustomer` c WHERE {' AND '.join(dk)}", tham)
	if not tuyen_loc:
		return [k for k, _ in ds]
	chon = set(tuyen or ())
	return [k for k, t in ds if ((t or "").strip(" ") or CHUA_CO_TUYEN) in chon]


def _ncc_chinh(bd: str) -> str:
	"""NCC chính của mặt hàng trên bí danh `bd` — CHÍNH biểu thức cột `products.primary_supplier_id` của cổng (Item Default dòng đầu theo idx có NCC)."""
	from nppsale.cong import bang as B

	B.nap()
	return lay("products").cot_def("primary_supplier_id").sql.replace("{t}", bd)


def _hang_theo_khach(K: list[str], nv, tu) -> list[dict]:
	"""`hang` (bước 5): đi ⊕ trả theo (khách, hàng) — MariaDB không có FULL JOIN → hai câu, ghép ở Python. ROUND 3 số lẻ ở SQL (DECIMAL, nửa xa 0 như
	`round(numeric, 3)`) rồi trừ bằng Decimal."""
	ncc = _ncc_chinh("it")
	ve_sp = f"(%(nv)s IS NULL OR {ncc} IS NULL OR {ncc} IN (SELECT ct.`nha_cung_cap` FROM `tabNPP Nhan Vien Cong Ty` ct WHERE ct.`parent` = %(nv)s " \
		"AND ct.`parenttype` = 'NPP Nhan Vien'))"
	tham = {"K": tuple(K), "nv": nv, "tu": tu}
	di = frappe.db.sql(f"""SELECT si.`customer`, ii.`item_code`, ROUND(SUM(IFNULL(ii.`qty`, 0) * {HE_SO_DONG_HD}), 3), COUNT(DISTINCT si.`name`),
			MAX(si.`posting_date`)
		FROM `tabSales Invoice` si
		JOIN `tabSales Invoice Item` ii ON ii.`parent` = si.`name` AND ii.`parenttype` = 'Sales Invoice'
		JOIN `tabItem` it ON it.`name` = ii.`item_code`
		LEFT JOIN `tabUOM Conversion Detail` u ON u.`parent` = ii.`item_code` AND u.`parenttype` = 'Item' AND u.`uom` = ii.`uom`
		WHERE {HD_DOANH_THU} AND IFNULL(ii.`npp_hang_doi`, 0) = 0 AND si.`customer` IN %(K)s AND {ve_sp}
			AND (%(tu)s IS NULL OR si.`posting_date` >= %(tu)s)
		GROUP BY si.`customer`, ii.`item_code`""", tham)
	tra = frappe.db.sql(f"""SELECT r.`khach_hang`, d.`mat_hang`, ROUND(SUM(IFNULL(d.`so_luong`, 0) * {HE_SO_DONG_TRA}), 3)
		FROM `tabNPP Phieu Tra` r
		JOIN `tabNPP Phieu Tra Dong` d ON d.`parent` = r.`name` AND d.`parenttype` = 'NPP Phieu Tra'
		JOIN `tabItem` it ON it.`name` = d.`mat_hang`
		LEFT JOIN `tabUOM Conversion Detail` u ON u.`parent` = d.`mat_hang` AND u.`parenttype` = 'Item' AND u.`uom` = d.`don_vi`
		WHERE r.`ngay_tru_doanh_so` IS NOT NULL AND (%(tu)s IS NULL OR r.`ngay_tru_doanh_so` >= %(tu)s) AND IFNULL(d.`hang_doi`, 0) = 0
			AND r.`khach_hang` IN %(K)s AND {ve_sp}
		GROUP BY r.`khach_hang`, d.`mat_hang`""", tham)
	gom: dict = {}
	for k, p, sl, lan, cuoi in di:
		gom[(k, p)] = {"k": k, "p": p, "di": d(sl), "tra": Decimal(0), "lan": int(lan or 0), "cuoi": cuoi}
	for k, p, sl in tra:
		g = gom.setdefault((k, p), {"k": k, "p": p, "di": Decimal(0), "tra": Decimal(0), "lan": 0, "cuoi": None})
		g["tra"] = d(sl)
	ra = []
	for g in gom.values():
		con = g["di"] - g["tra"]
		ra.append({"k": g["k"], "p": g["p"], "di": _so(g["di"], "so"), "tra": _so(g["tra"], "so"), "sl": _so(con, "so"), "lan": g["lan"],
			"cuoi": None if g["cuoi"] is None else str(g["cuoi"]), "_sl": con})
	ra.sort(key=lambda h: (_diem_ma(h["k"]), -h["_sl"], _diem_ma(h["p"])))
	for h in ra:
		del h["_sl"]
	return ra


def _thong_tin_khach(K: list[str]) -> list[dict]:
	"""`khach` = MỌI khách của K (kể cả chưa lấy gì) — cột như `customers` của nppsale (kênh THÔ, không trim); `nv_chinh` = tên các NV CHÍNH đang phụ
	trách nối ', ' theo tên (string_agg … ORDER BY full_name — xếp ở Python theo điểm mã), null nếu không có."""
	ds = frappe.db.sql("""SELECT c.`name`, c.`customer_name`, c.`npp_chu_cua_hang`, c.`npp_sdt`, c.`npp_dia_chi`, c.`npp_phuong`, c.`npp_tuyen`,
		c.`npp_trang_thai` FROM `tabCustomer` c WHERE c.`name` IN %(K)s""", {"K": tuple(K)})
	chinh: dict = {}
	for k, ten in frappe.db.sql("""SELECT pc.`khach`, nv.`ho_ten` FROM `tabNPP Phan Cong Khach` pc JOIN `tabNPP Nhan Vien` nv ON nv.`name` = pc.`nhan_vien`
			WHERE pc.`khach` IN %(K)s AND pc.`trang_thai` = 'active' AND pc.`vai_tro` = 'primary'""", {"K": tuple(K)}):
		chinh.setdefault(k, []).append(ten)
	ra = [{"id": k, "store_name": ten, "owner_name": chu, "phone": sdt, "address": dc, "ward": phuong, "channel": tuyen, "status": tt,
		"nv_chinh": ", ".join(sorted((x or "" for x in chinh[k]), key=_diem_ma)) if chinh.get(k) else None}
		for k, ten, chu, sdt, dc, phuong, tuyen, tt in ds]
	ra.sort(key=lambda x: (_diem_ma(x["store_name"]), x["id"]))
	return ra


def _thong_tin_hang(P: list[str]) -> list[dict]:
	"""`sp` = mặt hàng có trong `hang` (đã thuộc S): `{id, sku, name, base_unit, ncc}` — ncc = NCC chính (null khi chưa gán công ty)."""
	ds = frappe.db.sql(f"""SELECT it.`name`, it.`item_code`, it.`item_name`, it.`stock_uom`, {_ncc_chinh('it')} FROM `tabItem` it
		WHERE it.`name` IN %(P)s""", {"P": tuple(P)})
	ra = [{"id": ten, "sku": ma, "name": ten_hang, "base_unit": dv, "ncc": ncc or None} for ten, ma, ten_hang, dv, ncc in ds]
	ra.sort(key=lambda x: (_diem_ma(x["name"]), x["id"]))
	return ra


# ================================================================================================ my_sales_target (§2.11 — mig 196)
# Mức doanh số A / tháng của NVBH (trang chủ NVBH: mục tiêu tháng / quý x3 …; `/bao-cao/ban-hang` cột Chỉ tiêu / % đạt). nppsale: `COALESCE(max(
# hr_salary_config.kpi_target_revenue), 0)` của NPP người gọi — SECURITY DEFINER (NVBH đọc được dù bảng cấu hình khoá với NVBH — mig 197), KHÔNG lọc
# `is_active`. Frappe: Single `NPP Cau Hinh Luong.muc_doanh_so_a` (BP §4.7) — DocType do P7 dựng (đặc tả nhân sự §3.4: đăng ký MỘT chỗ ở đây, P7 không
# khai lại — `rpc/__init__.py` ghi đè `DANG_KY[ten]` lặng lẽ). Tới khi có DocType → 0 (giao diện vốn nuốt mọi lỗi thành 0: ẩn cột Chỉ tiêu / mục tiêu).
# P8: `hr_salary_config` nppsale nhiều dòng / NPP — chuyển `muc_doanh_so_a` = MAX MỌI dòng (kể cả không dùng) thì số không đổi.
DT_CAU_HINH_LUONG = "NPP Cau Hinh Luong"
TRUONG_MUC_A = "muc_doanh_so_a"


def muc_tieu_doanh_so() -> Decimal:
	"""Chỗ nối P7: mức A đang lưu (Single chưa lưu / chưa có DocType → 0); KHÔNG xét `dang_dung` (như mig 196 MAX mọi dòng)."""
	if not frappe.db.exists("DocType", DT_CAU_HINH_LUONG):
		return Decimal(0)
	return d(frappe.db.get_single_value(DT_CAU_HINH_LUONG, TRUONG_MUC_A, cache=False))


@rpc("my_sales_target", ghi=False)
def my_sales_target():
	"""→ SỐ TRƠN (numeric của Postgres — `int` khi chẵn): người không phải NV đang hoạt động (tài khoản khoá, người ngoài) → 0; còn lại mức A của NPP (mọi
	vai — DEFINER). Không UNION lưu trữ (không đọc chứng từ — BP §4.8.0). Gọi POST (sales-home.tsx:188, man-ban-hang.tsx:126-133)."""
	nc = hien_tai()
	if not _la_nv(nc):
		return 0
	return ra_so(muc_tieu_doanh_so())
