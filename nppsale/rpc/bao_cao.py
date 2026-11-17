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
"""
from __future__ import annotations

from decimal import Decimal

import frappe

from nppsale.cong.dang_ky import NguCanh, lay
from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai, xem_gia_von
from nppsale.cong.sql import BoThamSo, LoiCong, vế_rls
from nppsale.cong.truy_van import chuan_gia_tri
from nppsale.luat import bao_cao as L

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
DK_HD = ("si.`docstatus` = 1 AND si.`is_return` = 0 AND IFNULL(si.`is_opening`, 'No') = 'No' AND si.`posting_date` BETWEEN %(tu)s AND %(den)s")


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
