"""Hoá đơn điện tử MISA meInvoice — phía máy chủ của `/api/einvoice/*` (đặc tả `dac_ta_hddt.md` §4; blueprint 02 §4.6.9).

Tệp chia ba phần (giữ thứ tự để đọc từ trên xuống):
  1. PHẦN DÙNG CHUNG — vai theo route nppsale, câu lỗi nguyên văn, giờ / commit, đọc HĐ bán. Route, cổng `invoices`
     (`nppsale/cong/bang/hddt.py`) và việc nền (`nppsale/lich/misa.py`) cùng dùng — đừng chép lại ở chỗ khác.
  2. LẬP DÒNG — `dam_bao_dong` (§4.2): thay phần `ensureEInvoiceRow` (`src/lib/einvoice/publish.ts:51–93`) phía máy chủ. Trình duyệt vẫn gọi
     `ensureEInvoiceRow` nguyên văn → cổng `invoices` INSERT → bộ ghi gọi hàm này (không phủ giao diện — §9.3-9).
  3. GHI KÉO VỀ — `ghi_ket_qua_keo_ve` (§4.8) + `danh_dau_goc` (§4.7): một hàm ghi cho Làm mới, vòng quét (`nppsale/lich/misa.py`) và đẩy-lại-
     thấy-trên-MISA của phát hành; nhật ký `ghi_nhat_ky` (NPP MISA Log).
  4. ROUTE `@tuyen(...)` giữ nguyên đường `/api/einvoice/*`, mã HTTP, dạng JSON và câu lỗi nguyên văn (Phụ lục A): `phat_hanh` (§4.1),
     `lam_moi` (§4.3), `cau_hinh_doc` / `cau_hinh_luu` (§4.4), `thu_ket_noi` (§4.5), `doi_soat` (§4.6). Mô-đun nằm trong `_nap()` của
     `nppsale/api/tuyen.py` (§6.2 — thiếu là 501). `sync` / `pull-snapshots` / `cron/daily` KHÔNG port (lịch — §4.9) ⇒ 501.

Giao dịch (§0.2 điểm 3–4, §4.0): phát hành COMMIT giữa chừng (`commit_giua_chung` — sau giành tờ, sau nhật ký, sau ghi kết quả): RefID nằm trong sổ
TRƯỚC khi byte nào tới MISA, và không giữ khoá dòng / giao dịch nào trong lúc chờ HTTP (token lấy TRƯỚC giành tờ; hỏi / đẩy SAU commit). Route
khác chỉ ghi SAU khi MISA trả lời (khoá dòng `FOR UPDATE` ở hàm ghi, không trước lời gọi) — tuyen.goi commit cuối request.

Không whitelist hàm nào ở đây: route đi qua `nppsale.api.tuyen.goi`; `chan_cua_chung` (`portal/chan.py`) để NV NPP tới được mọi method
`nppsale.*` có whitelist — whitelist thêm thì phải kiểm vai TRONG hàm (§4.0).
"""
from __future__ import annotations

import datetime as _dt
import json
import uuid
from contextlib import contextmanager
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import cint, flt, get_datetime, get_system_timezone, now_datetime

from nppsale.api import misa_mang as MM
from nppsale.api.tuyen import YeuCauCu, tuyen
from nppsale.cong.bang._chung import co_cot, tu_choi
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.ngu_canh import hien_tai
from nppsale.cong.sql import LoiCong
from nppsale.luat.hddt import (
	ap_dung,
	bo_ngay_khong_that,
	canh_bao_noi_tay,
	co_ban_ghi_that,
	cung_so,
	doc_ban_ghi,
	dong_hang,
	dong_tong_hop,
	dung_payload,
	ghi_chu_bi_thay_the,
	ghi_chu_trung_so,
	gop_ghi_chu,
	js_dung,
	js_trim,
	la_so_cho,
	ngay_iso,
	ngay_that,
	so_js,
	suy_trang_thai,
	tach_dinh_danh,
	thue_phan_tram,
	trung_so,
	url_tra_cuu,
)

# ============================================================================================================================
# 1. PHẦN DÙNG CHUNG
# ============================================================================================================================
BANG_CONG = "invoices"  # tên bảng nppsale của HĐĐT (câu RLS 42501 mang tên này)

# Vai theo route nppsale (vai cứng, KHÔNG qua ma trận quyền — §4.0):
VAI_PHAT_HANH = ("owner", "accountant", "manager")  # publish / refresh-status / reconcile-action; cũng là vai LẬP DÒNG gắn HĐ bán (H1 —
# blueprint §7.1 điểm 19: quản lý bấm Phát hành ở HĐ chưa có dòng HĐĐT thì phải lập được dòng; nppsale hỏng ở RLS chỉ cho chủ / KT ghi)
VAI_CAU_HINH = ("owner", "accountant")  # config / test-connection
VAI_GHI_TAY = ("owner", "accountant")  # "Owner/Accountant can manage invoices" (mig 002): tờ tay, sửa nháp, đổi trạng thái nội bộ, xoá

# Câu nguyên văn (Phụ lục A). "hóa đơn" (dấu ở ó) đúng chính tả nppsale của từng câu — đừng "sửa" cho đồng nhất.
CAU_HET_HIEU_LUC = "Hóa đơn {ma} không còn hiệu lực — không phát hành hoá đơn điện tử được."  # publish.ts:56–59 (H6)
CAU_DON_CHUA_XUAT = "Đơn chưa có hóa đơn bán nào — xuất hàng trước rồi mới phát hành hoá đơn điện tử."  # orders/[id]/page.tsx:547–565 (H1)
CAU_DON_NHIEU_HD = ("Đơn có {n} hóa đơn bán. Mở từng hóa đơn ở mục Hóa đơn bán rồi phát hành riêng — phát hành gộp là khai sai chứng từ "
	"thuế.")


def bay_gio():
	"""Giờ site (không múi giờ) — một chỗ để bài thử ghim `luc` (đặc tả §8.0: patch `bay_gio()` của mô-đun)."""
	return now_datetime()


def commit_giua_chung() -> None:
	"""Commit giữa request (phát hành: sau giành tờ, sau nhật ký — §4.0). Bài thử chạy trong một giao dịch lui cuối bài nên bỏ qua (mẫu
	`cong/api.py::_goi_co_khoa`). Không gọi trong doc_events / controller (lõi bỏ qua commit ở đó — `frappe/database/database.py:1190–1194`)."""
	if not frappe.flags.in_test:
		frappe.db.commit()


# [Sửa cuối — phát hiện 16] Mọi lần MÁY ghi trường nghiệp vụ của NPP HDDT (giành tờ, lỗi trước gửi, kết quả phát hành, kéo về, H5, đánh dấu tờ gốc)
# đổi `modified` (+ `modified_by`): System Manager mở tờ trên Desk (đường §6.4 / `misa_no_locked`) TRƯỚC một lần máy ghi rồi bấm Lưu sau đó là
# `db_update` ghi lại MỌI cột của bản form cũ — số HĐĐT, mã tra cứu, trạng thái về bản cũ; `check_if_latest` của lõi chỉ so `modified` nên phải đổi
# nó thì lõi mới chặn (TimestampMismatchError). Đặc tả §4.0 / §8.0 (3) giữ `modified` cho luồng kéo về — lệch có chủ ý. Ghi CHỈ mốc hỏi
# (`misa_last_checked_at` — vòng quét mỗi đêm) không đổi `modified`: bản form cũ ghi đè mốc hỏi chỉ làm tờ được hỏi lại sớm.
SQL_DOI_MODIFIED = "`modified` = %(_luc_sua)s, `modified_by` = %(_nguoi_sua)s"


def tham_so_modified() -> dict:
	"""Tham số cho `SQL_DOI_MODIFIED` (giờ thật như `set_value(update_modified=True)` — không theo `bay_gio()` bài thử ghim)."""
	return {"_luc_sua": frappe.utils.now(), "_nguoi_sua": frappe.session.user or "Administrator"}


def ban_ghi_cua_to(raw, misa_status, ref):
	"""[Sửa cuối — phát hiện 9] Bản ghi `GET ?refID=` cho tờ đang `pending` / `error` mà KHÔNG nói gì (`{}` — `data: '{}'` / `'[]'`; xem
	`co_ban_ghi_that`) → coi như MISA KHÔNG có (None): phát hành POST tiếp (H3 / H27), Làm mới / vòng quét đi nhánh H5 thay vì "xác nhận đẩy" một tờ
	MISA chưa từng nhận. Tờ khác (`sent`, `signed`…) giữ nguyên bản ghi [=] — một luật cho phát hành, Làm mới, vòng quét."""
	if raw is not None and (misa_status or "") in ("pending", "error") and not co_ban_ghi_that(raw, ref):
		return None
	return raw


def _co_luu_tru() -> bool:
	"""Đã dựng bảng lưu trữ HĐ bán trước ngày cắt (P8: `NPP LS Hoa Don` + `NPP HDDT.hoa_don_ban_ls`) chưa — chưa thì mọi nhánh LS im lặng bỏ qua."""
	return co_cot("NPP HDDT", "hoa_don_ban_ls") and bool(frappe.db.exists("DocType", "NPP LS Hoa Don"))  # co_cot nhớ theo tiến trình — hỏi trước


def doc_hd_ban(hd, *, khoa: bool = False) -> dict | None:
	"""HĐ bán theo tên (= `sales_invoices.id` ở trình duyệt) → dict, hoặc None khi không có.

	Sales Invoice: chỉ tờ bán (`is_return = 0`) không phải tờ nợ đầu kỳ (`is_opening = 'No'`) — đúng tập dòng cổng `sales_invoices` cho trình
	duyệt thấy (`cong/bang/hoa_don.py::NGUON_HD`); tờ ghi có không bao giờ có HĐĐT (§4.2), tờ đầu kỳ `DK-` không phải `sales_invoices` của nppsale
	(như `rpc/xuat_hang.py::_huy` coi là INVOICE_NOT_FOUND). `khoa=True`: `SELECT … FOR UPDATE` — đọc bản ĐÃ COMMIT MỚI NHẤT (không theo ảnh chụp
	REPEATABLE READ) và giữ khoá dòng tới hết giao dịch; thứ tự khoá HĐ bán → dòng HĐĐT, cùng thứ tự với `_huy` (§4.1.1 bước 9).
	Không thấy ở Sales Invoice mà có `NPP LS Hoa Don` cùng tên (HĐ trước ngày cắt — P8) → bản lưu trữ (chỉ đọc, không khoá).
	Tiền như cổng `sales_invoices` (`hoa_don.py:49–50`): `tien_hang` = net_total − discount_amount (giảm cả đơn sau thuế), `tien_thue` =
	total_taxes_and_charges, `tong_tien` = grand_total — I9."""
	if not hd or not isinstance(hd, str):
		return None
	r = frappe.db.sql(
		"""SELECT `name`, `docstatus`, `customer`, `npp_don_hang`, `net_total`, `discount_amount`, `total_taxes_and_charges`, `grand_total`
		FROM `tabSales Invoice` WHERE `name` = %s AND `is_return` = 0 AND IFNULL(`is_opening`, 'No') = 'No'""" + (" FOR UPDATE" if khoa else ""),
		hd, as_dict=True)
	if r:
		r = r[0]
		return {"nguon": "si", "ten": r.name, "ma": r.name, "con_hieu_luc": r.docstatus == 1, "khach": r.customer,
			"don": r.npp_don_hang or None, "don_ls": None, "tien_hang": flt(r.net_total) - flt(r.discount_amount),
			"tien_thue": flt(r.total_taxes_and_charges), "tong_tien": flt(r.grand_total)}
	if _co_luu_tru():
		ls = frappe.db.sql("""SELECT `name`, `invoice_code`, `status`, `customer_id`, `order_id`, `subtotal`, `vat`, `total`
			FROM `tabNPP LS Hoa Don` WHERE `name` = %s""", hd, as_dict=True)
		if ls:
			ls = ls[0]
			return {"nguon": "ls", "ten": ls.name, "ma": ls.invoice_code or ls.name, "con_hieu_luc": ls.status == "posted",
				"khach": ls.customer_id, "don": None, "don_ls": ls.order_id or None, "tien_hang": flt(ls.subtotal), "tien_thue": flt(ls.vat),
				"tong_tien": flt(ls.total)}
	return None


def hd_ban_cua_don(don) -> list[str]:
	"""HĐ bán ĐANG GHI SỔ của một đơn (H1 — blueprint §7.1 điểm 19): Sales Invoice `npp_don_hang` = đơn, docstatus 1, không phải tờ ghi có / đầu
	kỳ; hoặc bản lưu trữ (P8) `order_id` = đơn ∧ `status = 'posted'`. Thứ tự theo tên (ổn định cho câu "Đơn có {n} hóa đơn bán")."""
	if not don or not isinstance(don, str):
		return []
	ra = [x for (x,) in frappe.db.sql("""SELECT `name` FROM `tabSales Invoice` WHERE `npp_don_hang` = %s AND `docstatus` = 1 AND `is_return` = 0
		AND IFNULL(`is_opening`, 'No') = 'No' ORDER BY `name`""", don)]
	if _co_luu_tru():
		ra += [x for (x,) in frappe.db.sql("SELECT `name` FROM `tabNPP LS Hoa Don` WHERE `order_id` = %s AND `status` = 'posted' ORDER BY `name`",
			don)]
	return ra


# ============================================================================================================================
# 2. LẬP DÒNG HĐĐT THEO HĐ BÁN (§4.2)
# ============================================================================================================================
def dam_bao_dong(hd, nc: NguCanh, so_hd_go_tay=None) -> str:
	"""Tìm hoặc lập dòng `NPP HDDT` của HĐ bán `hd` → tên dòng (mỗi HĐ bán TỐI ĐA MỘT dòng mới — nppsale đẻ được hai khi đua, chú thích
	`sales-invoices/[id]/page.tsx:143–147`).

	1. Vai ∈ VAI_PHAT_HANH (H1 — quản lý lập được; vai khác 42501 như RLS). Khoá dòng HĐ bán `FOR UPDATE` (`doc_hd_ban(khoa=True)`): không có /
	   đã huỷ (docstatus ≠ 1) / bản lưu trữ `status ≠ 'posted'` → P0001 `CAU_HET_HIEU_LUC` (H6; câu của `ensureEInvoiceRow`) — kể cả khi HĐ đã
	   có dòng HĐĐT (nppsale kiểm trạng thái HĐ trước khi tìm dòng).
	2. Dòng đã có (theo `hoa_don_ban`, hoặc `hoa_don_ban_ls` với bản lưu trữ) → trả dòng ấy, KHÔNG đổi gì (kể cả `so_hd_go_tay` gửi kèm — §7.1
	   [Soát thiếu 2]). Thứ tự khi dữ liệu cũ có ≥ 2 dòng: tờ có số trước, rồi mới nhất (như màn HĐ bán — `ORDER BY misa_inv_no DESC NULLS LAST,
	   created_at DESC`). Đọc thường trước (đường nhanh); không thấy thì đọc CÓ KHOÁ (`LOCK IN SHARE MODE`): ảnh chụp REPEATABLE READ của
	   giao dịch lập từ câu đọc thường ĐẦU TIÊN của request (`hien_tai()` đọc NPP Nhan Vien — PoC 1d) nên đọc thường có thể không thấy dòng
	   một lượt bấm song song vừa commit trong lúc mình chờ khoá HĐ bán → lập dòng thứ hai. Đọc có khoá thấy bản đã commit mới nhất.
	   ⚠ Đọc có khoá trên chỉ mục không duy nhất đặt khoá khoảng: hai lượt lập dòng cho HAI HĐ bán khác nhau cùng rơi vào một khoảng trống
	   trong cùng vài mili giây có thể deadlock (InnoDB lui một lượt — người bấm lại là được); thà vậy còn hơn đẻ hai dòng cho một HĐ.
	3. Chưa có → `NPP HDDT.insert`: `trang_thai = draft`; `hoa_don_ban` (bản lưu trữ: `hoa_don_ban_ls`); `don_hang` = đơn của HĐ (`npp_don_hang`;
	   bản lưu trữ: `don_hang_ls`); `so_hd_go_tay` = tham số; người mua từ khách HIỆN HÀNH của HĐ (như `si.customer` nppsale nhúng):
	   `nguoi_mua` = tên xuất HĐ ∥ tên khách (`billing_name || store_name` — trường reqd: rỗng → 23502 ở validate), `dia_chi_nguoi_mua` = địa chỉ
	   xuất HĐ ∥ địa chỉ, `mst_nguoi_mua` = MST; ba số tiền từ HĐ bán (I9) — bỏ mọi số trình duyệt gửi (H1)."""
	if not nc.bo_qua_rls and nc.vai not in VAI_PHAT_HANH:
		tu_choi(BANG_CONG)
	h = doc_hd_ban(hd, khoa=True)
	if h is None or not h["con_hieu_luc"]:
		raise LoiCong("P0001", CAU_HET_HIEU_LUC.format(ma=h["ma"] if h else (hd if isinstance(hd, str) else "")), http=400)
	cot = "hoa_don_ban" if h["nguon"] == "si" else "hoa_don_ban_ls"
	tim = (f"SELECT `name` FROM `tabNPP HDDT` WHERE `{cot}` = %s ORDER BY (IFNULL(`misa_inv_no`, '') = ''), `creation` DESC, `name` DESC "
		"LIMIT 1")
	co = frappe.db.sql(tim, h["ten"]) or frappe.db.sql(tim + " LOCK IN SHARE MODE", h["ten"])
	if co:
		return co[0][0]
	kh = (frappe.db.get_value("Customer", h["khach"], ["customer_name", "tax_id", "npp_ten_xuat_hd", "npp_dia_chi_xuat_hd", "npp_dia_chi"],
		as_dict=True) if h["khach"] else None) or frappe._dict()
	d = frappe.get_doc({
		"doctype": "NPP HDDT", "trang_thai": "draft", "so_hd_go_tay": so_hd_go_tay or None,
		"nguoi_mua": kh.npp_ten_xuat_hd or kh.customer_name or "", "dia_chi_nguoi_mua": kh.npp_dia_chi_xuat_hd or kh.npp_dia_chi or None,
		"mst_nguoi_mua": kh.tax_id or None, "tien_hang": h["tien_hang"], "tien_thue": h["tien_thue"], "tong_tien": h["tong_tien"],
	})
	if h["nguon"] == "si":
		d.hoa_don_ban, d.don_hang = h["ten"], h["don"]
	else:
		d.hoa_don_ban_ls, d.don_hang_ls = h["ten"], h["don_ls"]
	d.insert(ignore_permissions=True)
	return d.name


# ============================================================================================================================
# 3. GHI KÉO VỀ (§4.8) + ĐÁNH DẤU TỜ GỐC (§4.7) + NHẬT KÝ — dùng chung: Làm mới, vòng quét (nppsale/lich/misa.py), đẩy lại của phát hành
# ============================================================================================================================
TEN_CAU_HINH = "NPP MISA Cau Hinh"
CAU_DA_CO_TREN_MISA = "MISA đã có hoá đơn với RefID này — không đẩy lại."  # §4.1.1 bước 10 / 12 (H3, H27)
CAU_TRUNG_SO_KEO_VE = ("Số HĐĐT {ky_hieu} · {so} MISA trả về đã có ở một hoá đơn khác trong sổ — kiểm tra trùng trước khi làm mới lại.")
CAU_DOI_SO = "Số HĐĐT đổi từ {cu} sang {moi} theo MISA — cần kiểm tra."  # [ĐX H22]
_COT_DONG = ("name", "hoa_don_ban", "don_hang", "so_hd_go_tay", "nguoi_mua", "dia_chi_nguoi_mua", "mst_nguoi_mua", "tien_hang", "tien_thue",
	"tong_tien", "trang_thai", "phat_hanh_luc", "misa_ref_id", "misa_inv_no", "misa_inv_series", "misa_lookup_code", "misa_invoice_url",
	"misa_status", "misa_no_locked", "misa_sent_at", "misa_note", "misa_last_checked_at", "misa_invoice_id", "misa_error")


class LoiTrungSoHddt(Exception):
	"""Ghi số HĐĐT MISA trả về đụng chỉ mục duy nhất (ký hiệu, số) của tờ khác — `str(e)` = câu 409 của Làm mới (§4.3 bước 7, H13); vòng
	quét đẩy câu này vào `errors` (§5.2). Dòng KHÔNG đổi gì (đã lui điểm lưu)."""

	def __init__(self, ky_hieu, so):
		self.ky_hieu, self.so = ky_hieu, so
		super().__init__(CAU_TRUNG_SO_KEO_VE.format(ky_hieu=ky_hieu or "", so=so))


def _cot_ls() -> list[str]:
	return [c for c in ("hoa_don_ban_ls", "don_hang_ls") if co_cot("NPP HDDT", c)]


def doc_dong_hddt(ten, *, khoa: bool = False) -> frappe._dict | None:
	"""Một dòng NPP HDDT (cột route cần) — `khoa=True`: `FOR UPDATE` (bản đã commit MỚI NHẤT + khoá tới hết giao dịch)."""
	if not ten or not isinstance(ten, str):
		return None
	cot = list(_COT_DONG) + _cot_ls()
	r = frappe.db.sql(f"SELECT {', '.join(f'`{c}`' for c in cot)} FROM `tabNPP HDDT` WHERE `name` = %s" + (" FOR UPDATE" if khoa else ""), ten,
		as_dict=True)
	return r[0] if r else None


def _json_chuoi(v):
	"""Trường JSON của NPP MISA Log nhận CHUỖI (gán list là lõi ném 'Value for … cannot be a list' — document.py:2585)."""
	return None if v is None else json.dumps(v, ensure_ascii=False, default=str)


def _ghi_loi(tieu_de: str) -> None:
	"""Error Log KHÔNG kèm biến cục bộ (I6): traceback thường. Thân yêu cầu của Cấu hình / Thử kết nối (tài khoản + mật khẩu vừa gõ) nằm trong
	khung route (`YeuCauCu.than`); bộ che của lõi (`frappe/utils/__init__.py:340–385`, chỉ khi developer_mode) che theo TÊN biến / khoá dict, KHÔNG
	che thuộc tính của một dataclass ⇒ traceback có biến sẽ in nguyên mật khẩu, và "username" không nằm trong danh sách che."""
	frappe.log_error(title=tieu_de, message=frappe.get_traceback(with_context=False) or tieu_de)


def ghi_nhat_ky(nguon: str, ket_qua: str, *, hddt=None, don_hang=None, gui_di=None, nhan_ve=None, loi=None, misa_lookup_code=None,
		misa_inv_no=None) -> str:
	"""Một dòng NPP MISA Log (= einvoice_logs; chỉ thêm) — `owner` = người bấm (Administrator ở việc nền). KHÔNG BAO GIỜ đưa token / tài khoản /
	mật khẩu / thân `/oauth` / thân lấy mẫu vào (I6): người gọi chỉ đưa payload hoá đơn, bản ghi MISA (lớp mạng đã che bí mật dội lại) và câu lỗi."""
	d = frappe.get_doc({
		"doctype": "NPP MISA Log", "nguon": nguon, "ket_qua": ket_qua, "hddt": hddt or None, "don_hang": don_hang or None, "goi_luc": bay_gio(),
		"gui_di": _json_chuoi(gui_di), "nhan_ve": _json_chuoi(nhan_ve), "loi": loi or None, "misa_lookup_code": misa_lookup_code or None,
		"misa_inv_no": misa_inv_no or None,
	})
	d.insert(ignore_permissions=True)
	return d.name


def _ghi_nhat_ky_an_toan(nguon: str, ket_qua: str, **kw) -> str | None:
	"""Nhật ký best-effort: hỏng thì lui điểm lưu + Error Log, KHÔNG làm hỏng kết quả của người bấm (§4.1.1 bước 13)."""
	frappe.db.savepoint("npp_misa_nhat_ky")
	try:
		return ghi_nhat_ky(nguon, ket_qua, **kw)
	except Exception:  # nhật ký không được làm hỏng kết quả (đã ghi vào Error Log)
		frappe.db.rollback(save_point="npp_misa_nhat_ky")
		_ghi_loi("HĐĐT MISA: không ghi được nhật ký")
		return None


def _la_trung_khoa(e: Exception) -> bool:
	try:
		return bool(frappe.db.is_unique_key_violation(e) or frappe.db.is_duplicate_entry(e))
	except Exception:
		return False


def _trung_sau_chuan_hoa(ten: str, ky_hieu, so) -> list[str]:
	"""[ĐX §1.6] Tờ KHÁC mang cùng số sau chuẩn hoá ∧ (cùng ký hiệu chặt ∨ một bên trống) — chỉ mục duy nhất so NGUYÊN VĂN nên không bắt
	'00000123' vs '123' hay ('', '123') vs ('1C26TAA', '123'). Lọc thô bằng LIKE theo số đã chuẩn hoá rồi xét đúng luật `trung_so`."""
	from nppsale.luat.hddt import chuan_so

	c = chuan_so(so)
	if not c:
		return []
	mau = "%" + c.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
	ra = []
	for r in frappe.db.sql("""SELECT `name`, `misa_inv_series`, `misa_inv_no` FROM `tabNPP HDDT` WHERE `name` <> %s AND `misa_inv_no` LIKE %s
			ORDER BY `creation`, `name`""", (ten, mau), as_dict=True):
		if trung_so(ky_hieu, so, r.misa_inv_series, r.misa_inv_no):
			ra.append(r.name)
	return ra


def danh_dau_goc(org_ref_id, ten_thay_the) -> str | None:
	"""markOriginalReplaced (`src/lib/misa/mark-replaced.ts:22–61`, §4.7): bản THAY THẾ mang `OrgRefID` → tờ gốc trong sổ (`misa_ref_id` =
	OrgRefID — duy nhất ⇒ ≤ 1 dòng; nppsale `.maybeSingle()` gặp 2 dòng thì im lặng không đánh dấu) thành `replaced` / `replaced` + THÊM dòng ghi
	chú (H7 — nppsale thay cả ô). Không có tờ gốc (phát hành thẳng trên MISA / mất RefID) → None, không tạo dòng; đã `replaced` → None (không
	ghi lại mỗi lượt). Không xét `misa_no_locked`, không nhật ký riêng [=]. Không đánh dấu thì hai HĐĐT cùng "đã phát hành" cho MỘT lần bán ⇒
	doanh thu / thuế đầu ra khai GẤP ĐÔI. Lỗi CSDL để nổi lên (người gọi bọc điểm lưu)."""
	if not js_dung(org_ref_id) or not isinstance(org_ref_id, str):
		return None
	r = frappe.db.sql("SELECT `name`, `misa_status`, `misa_note` FROM `tabNPP HDDT` WHERE `misa_ref_id` = %s FOR UPDATE", org_ref_id,
		as_dict=True)
	if not r or r[0].misa_status == "replaced":
		return None
	r = r[0]
	frappe.db.set_value("NPP HDDT", r.name, {"misa_status": "replaced", "misa_relation": "replaced",
		"misa_note": gop_ghi_chu(r.misa_note, [ghi_chu_bi_thay_the(ten_thay_the)])})  # đổi `modified` (phát hiện 16)
	return r.name


def ghi_ket_qua_keo_ve(ten: str, raw, *, xac_nhan_day: bool = False, luc=None, co_ma=None) -> dict:
	"""§4.8 — áp bản ghi MISA `raw` (đã lấy XONG, ngoài khoá) vào dòng `ten`; một hàm cho Làm mới, vòng quét và đẩy-lại-thấy-trên-MISA của phát
	hành (hai đường không được kết luận khác nhau về một tờ).

	1. Đọc lại dòng `FOR UPDATE` (sau khi đã có `raw` — không giữ khoá lúc gọi MISA; Làm mới và vòng quét có thể chạm cùng tờ).
	2. `ap_dung(raw, sổ, co_ma, luc)` (luật thuần — H8, H17, khoá gán tay, so tiền; chỉ khoá có giá trị — không ghi null đè).
	3. [ĐX H5] Xác nhận đẩy: `xac_nhan_day` ∧ dòng (đọc có khoá) đang `pending` / `error` — MISA CÓ tờ ⇒ `trang_thai = issued` (+ `phat_hanh_luc =
	   luc` nếu đang draft), `misa_error = NULL`, và [Sửa cuối — phát hiện 1] `misa_status` ít nhất `sent` khi `ap_dung` không kết luận được (None —
	   vd PublishStatus lạ ở đơn vị KHÔNG mã mà đã có số): "giữ nguyên" với tờ treo / lỗi là kẹt `pending` / `error` vĩnh viễn trong khi MISA đã giữ
	   tờ (Làm mới / quét lặp lại y hệt). `sent` = đúng thứ phát hành OK không mã tra cứu sẽ ghi — rồi luật kéo về áp trên đó như nppsale.
	   (Người gọi tính `xac_nhan_day` từ bản đọc trước; xét lại trên bản đọc có khoá để lượt chạy song song không "xác nhận" tờ đã thôi treo.)
	4. Có `misa_inv_no`: ký hiệu cuối cùng (mới ∥ cũ) trống ⇒ `''` (MariaDB coi NULL là khác nhau — chỉ mục duy nhất phải bắt); số đổi so với sổ
	   (theo `cung_so`, tờ không khoá) ⇒ ghi chú [ĐX H22]; tờ khác trùng sau chuẩn hoá ⇒ ghi chú §1.6 (vẫn ghi số MISA, không đổi trạng thái).
	4b. [ĐX H26] `misa_inv_date` không phải ngày có thật ('2026-02-30') ⇒ bỏ khoá ấy + ghi chú (MariaDB strict từ chối CẢ câu ghi).
	5. `misa_note` = `gop_ghi_chu(cũ, ghi chú)` (H7 — chỉ thêm dòng chưa có); `tim_kd` tính lại khi `misa_inv_no` đổi (db_set không chạy before_save).
	   `misa_last_checked_at` không giảm (I10 — lượt chạy chậm hơn không lùi mốc).
	6. `set_value` trong điểm lưu (không validate, không Version; vết ở NPP MISA Log) — đổi `modified` khi có trường nghiệp vụ đổi (phát hiện 16;
	   chỉ mốc hỏi thì không); trùng chỉ mục (ký hiệu, số) → `LoiTrungSoHddt` (dòng không đổi). Lỗi khác → nổi lên (dòng không đổi).
	7. Ghi xong mới đánh dấu tờ gốc (`danh_dau_goc` — chỉ bản THAY THẾ; ghi hỏng thì KHÔNG đánh dấu — [Soát thiếu 2], nppsale Làm mới vẫn đánh).
	   Đánh dấu hỏng: lui điểm lưu riêng, Error Log, trả `loi_danh_dau` (vòng quét đẩy vào `errors`) — phần ghi chính vẫn giữ.

	→ {tom_tat (ap_dung), ghi_chu (của ap_dung + của hàm ghi — §4.3 bước 9), cap_nhat, so_that (số thật MISA trả ∥ None), goc (tên tờ gốc vừa
	đánh dấu ∥ None), loi_danh_dau}."""
	luc = luc or bay_gio()
	if co_ma is None:
		co_ma = bool(frappe.db.get_single_value(TEN_CAU_HINH, "misa_is_invoice_with_code"))
	diem = "npp_misa_keo_ve"
	r, cap = None, {}
	frappe.db.savepoint(diem)
	try:
		r = doc_dong_hddt(ten, khoa=True)
		if r is None:
			raise frappe.DoesNotExistError(f"Không tìm thấy HD {ten}")
		kq = ap_dung(raw, {"misa_inv_no": r.misa_inv_no, "misa_status": r.misa_status, "misa_no_locked": r.misa_no_locked,
			"tien_hang": r.tien_hang, "tien_thue": r.tien_thue, "tong_tien": r.tong_tien, "so_hd_go_tay": r.so_hd_go_tay}, co_ma, luc)
		cap = dict(kq["cap_nhat"])
		them = []
		if xac_nhan_day and (r.misa_status or "") in ("pending", "error"):  # [ĐX H5]
			cap["trang_thai"] = "issued"
			if (r.trang_thai or "") == "draft":
				cap["phat_hanh_luc"] = luc
			cap["misa_error"] = None
			cap.setdefault("misa_status", "sent")  # [Sửa cuối — phát hiện 1] MISA đã giữ tờ: không để kẹt pending / error
		so_moi = cap.get("misa_inv_no")
		if so_moi:
			if not (cap.get("misa_inv_series") or r.misa_inv_series):
				cap["misa_inv_series"] = ""
			if js_dung(r.misa_inv_no) and not cung_so(r.misa_inv_no, so_moi):  # [ĐX H22] số đã cấp của một RefID là bất biến bên MISA
				them.append(CAU_DOI_SO.format(cu=r.misa_inv_no, moi=so_moi))
			ky_hieu = cap.get("misa_inv_series") if "misa_inv_series" in cap else r.misa_inv_series
			for khac in _trung_sau_chuan_hoa(ten, ky_hieu, so_moi):
				them.append(ghi_chu_trung_so(so_moi, khac))
		them += bo_ngay_khong_that(cap, raw)  # 4b (H26) — sửa `cap` tại chỗ
		cu_luc = r.misa_last_checked_at
		if cu_luc and get_datetime(cu_luc) > get_datetime(cap["misa_last_checked_at"]):
			cap.pop("misa_last_checked_at")  # I10
		ghi_chu = list(kq["ghi_chu"]) + them
		note = gop_ghi_chu(r.misa_note, ghi_chu)
		if note != r.misa_note:
			cap["misa_note"] = note
		if so_moi and so_moi != r.misa_inv_no:
			from nppsale.npp_hddt.doctype.npp_hddt.npp_hddt import khoa_tim_hddt

			cap["tim_kd"] = khoa_tim_hddt({**r, "misa_inv_no": so_moi})
		if cap:  # I10 bỏ mốc hỏi mà MISA không cho gì mới → không có gì để ghi (set_value với {} là câu SQL rỗng — MariaDB 1065)
			# phát hiện 16: đổi `modified` khi có trường nghiệp vụ đổi — bản form Desk cũ lưu sau đó bị lõi chặn (không ghi đè số / trạng thái)
			frappe.db.set_value("NPP HDDT", ten, cap, update_modified=bool(set(cap) - {"misa_last_checked_at"}))
	except Exception as e:
		frappe.db.rollback(save_point=diem)
		if _la_trung_khoa(e) and r is not None:
			ky = cap.get("misa_inv_series") if "misa_inv_series" in cap else r.misa_inv_series
			raise LoiTrungSoHddt(ky, cap.get("misa_inv_no") or r.misa_inv_no) from e
		raise
	goc, loi_danh_dau = None, None
	if kq["danh_dau_goc"]:
		frappe.db.savepoint("npp_misa_danh_dau_goc")
		try:
			goc = danh_dau_goc(kq["danh_dau_goc"], ten)
		except Exception as e:  # nppsale chỉ console.error; ở đây Error Log + trả lỗi cho vòng quét
			frappe.db.rollback(save_point="npp_misa_danh_dau_goc")
			_ghi_loi("HĐĐT MISA: không đánh dấu được tờ gốc bị thay thế")
			loi_danh_dau = str(e) or type(e).__name__
	return {"tom_tat": kq["tom_tat"], "ghi_chu": ghi_chu, "cap_nhat": cap, "so_that": kq["tom_tat"]["InvNo"], "goc": goc,
		"loi_danh_dau": loi_danh_dau}


# ============================================================================================================================
# 4. ROUTE /api/einvoice/* (§4.0–§4.6) — `(mã HTTP, JSON)` đúng dạng route nppsale; câu nguyên văn ở Phụ lục A
# ============================================================================================================================
CAU_BODY = "Body không hợp lệ"
CAU_THIEU_ID = "Thiếu invoiceId"
CAU_KHONG_QUYEN = "Không có quyền"
CAU_PH_QUYEN = "Chỉ Chủ NPP, Kế toán hoặc Quản lý mới được phát hành hoá đơn"
CAU_PH_KHONG_CO = "Không tìm thấy hoá đơn"
CAU_PH_DANG_XU_LY = "Hoá đơn đang được xử lý hoặc đã phát hành. Thử lại sau giây lát."
CAU_PH_CHUA_CAU_HINH = "Chưa cấu hình tài khoản hoá đơn điện tử MISA. Vào Cài đặt → Hoá đơn điện tử."
LOI_PH_CHUA_CAU_HINH = "Chưa cấu hình tài khoản MISA"  # misa_error
CAU_PH_THIEU_TK = "Chưa nhập username/password MISA. Vào Cài đặt → Hoá đơn điện tử."
LOI_PH_THIEU_TK = "Thiếu username/password MISA"  # misa_error
CAU_PH_GIAI_MA = ("Không giải mã được credentials MISA (kiểm tra encryption_key trong site_config.json có thay đổi so với lúc lưu cấu hình "
	"không): {ly_do}")  # nppsale nhắc EINVOICE_ENC_KEY (publish/route.ts:313–322)
CAU_DOC_CAU_HINH = "Không đọc được cấu hình MISA: {msg}"
CAU_PH_DOC_HD = "Không đọc được hóa đơn bán để lập hoá đơn điện tử. CHƯA phát hành, vui lòng thử lại: {msg}"
CAU_PH_DOC_DON = "Không đọc được thông tin đơn hàng để lập hoá đơn. CHƯA phát hành, vui lòng thử lại: {msg}"
CAU_PH_HOI_TRUOC = "Không hỏi được MISA trước khi đẩy lại: {cau}"  # [ĐX H3]
LOI_PH_CHUA_BIET = "chưa biết MISA nhận chưa — bấm Làm mới trạng thái"  # misa_error khi hết giờ / rớt mạng sau khi gửi [BP]
CAU_PH_DA_PHAT_HANH = ("Hoá đơn ĐÃ được phát hành trên MISA nhưng hệ thống chưa cập nhật được trạng thái. KHÔNG phát hành lại — hãy bấm "
	"'Làm mới trạng thái' để đồng bộ.")
CAU_PH_MISA_LOI = "MISA trả lỗi"
CAU_PH_KHONG_XAC_DINH = "Lỗi không xác định khi gọi MISA"
CAU_PH_SERVER = "Lỗi server không xác định khi gọi MISA"
CAU_LM_KHONG_CO = "Không tìm thấy HD"
CAU_LM_LOI_DOC = "Lỗi truy vấn hoá đơn"
CAU_LM_MAT_REFID = ("Hoá đơn này đã MẤT RefID (dữ liệu cũ trước bản vá tách khoá) nên không tra cứu lại được trên MISA. Cần gán tay RefID hoặc "
	"phát hành lại — xem khám sổ HĐĐT (bench --site <site> execute nppsale.kham_so.hddt).")
CAU_LM_CHUA_DAY = "HD chưa đẩy lên MISA — không có RefID để tra cứu."
CAU_LM_LOI_CAU_HINH = "Lỗi truy vấn cấu hình MISA"
CAU_CHUA_CAU_HINH = "Chưa cấu hình MISA"
CAU_LM_MISA_RONG = "MISA không trả về dữ liệu HD."
LOI_LM_TREO = ("MISA không có hoá đơn với RefID này — lượt đẩy trước chưa tới MISA. Bấm Phát hành để đẩy lại (dùng lại RefID cũ).")  # [ĐX H5]
CAU_LM_GHI_HONG = "Không ghi được kết quả làm mới: {msg}"  # [ĐX H13]
PHUT_TREO = 10  # [ĐX H5] tờ `pending` mà MISA không có: chỉ coi là "chưa tới MISA" khi đã gửi quá 10 phút (MISA có thể chưa ghi xong)
CAU_CH_QUYEN = "Chỉ Chủ NPP hoặc Kế toán mới được cấu hình hoá đơn điện tử"
CAU_CH_MA_HOA = ("Không mã hoá được tài khoản MISA — khoá mã hoá của site (encryption_key trong site_config.json) sai định dạng.")  # [ĐX]
CAU_TK_QUYEN = "Chỉ Chủ NPP hoặc Kế toán mới được test kết nối"
CAU_TK_CHUA_LUU = "Chưa có cấu hình. Lưu cấu hình MISA trước (api_base + MST + username/password)."
CAU_TK_THIEU = "Thiếu username/password. Nhập rồi bấm test lại."
CAU_TK_CHUA_LUU_DUOC = "Đã kết nối MISA nhưng chưa lưu được thông tin vào cấu hình: {msg}"  # [ĐX H13]
CAU_TK_KHONG_XAC_DINH = "Lỗi không xác định"
CAU_DS_THIEU_SNAP = "Thiếu snapshotId"
CAU_DS_KHONG_CO_SNAP = "Không tìm thấy dòng đối soát"
CAU_DS_ACTION = "action không hợp lệ"
CAU_DS_KHONG_CO_HD = "Không tìm thấy hoá đơn đó trong sổ của đơn vị này."
CAU_DS_BI_CHIEM = ("Hoá đơn này đã được nối với một hoá đơn MISA khác ({ky_hieu} · {so}). Gỡ nối bên đó trước — một lần bán không thể có hai "
	"hoá đơn hợp lệ.")
CAU_DS_DA_NOI = "Dòng này đã nối với một hoá đơn trong sổ rồi."
CAU_DS_KHONG_REFID = "Dòng này không có RefID."
CAU_DS_GIAI_MA = "Giải mã cấu hình lỗi: {msg}"
CAU_DS_GOI_MISA = "Gọi MISA lỗi: {msg}"
CAU_DS_MISA_RONG = ("MISA không trả chi tiết hoá đơn này nên không lấy được tiền hàng và thuế. KHÔNG dựng hoá đơn với số liệu thiếu — thử lại "
	"sau, hoặc lập tay.")
CAU_DS_THIEU_TONG = "MISA không trả tổng tiền — không dựng hoá đơn thiếu số liệu."
CAU_DS_TRUNG_SO = 'Sổ đã có một hoá đơn mang ký hiệu {ky_hieu} số {so}. Dùng "Nối tay" với hoá đơn đó thay vì dựng tờ mới.'
CAU_DS_TRUNG_REFID = 'Sổ đã có một hoá đơn mang RefID này. Dùng "Nối tay" với hoá đơn đó thay vì dựng tờ mới.'  # [ĐX]
GHI_CHU_DUNG = ("Hoá đơn dựng từ đối soát MISA (phát hành thẳng trên MISA, chưa gắn đơn hàng). Kỳ ghi nhận lấy theo ngày phát hành trên MISA.")
GHI_CHU_KHOP_DUNG = "Đã dựng hoá đơn trong sổ từ dòng này."
MISA_DA_TOI = ("sent", "waiting_code", "signed", "replaced", "cancelled", "amount_mismatch")  # §4.1.1 bước 4b: đã tới MISA → kết quả cũ


def _loi(ma: int, cau: str) -> tuple:
	return ma, {"error": cau}


def _ma(v) -> str:
	"""`invoiceId` / `snapshotId` của thân → tên chứng từ ('' = thiếu). Chuỗi bỏ khoảng trắng hai đầu; số / kiểu khác → chữ (tra không ra → 404
	như câu tra hỏng của nppsale)."""
	if isinstance(v, str):
		return js_trim(v)
	if not js_dung(v):
		return ""
	return so_js(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def _than(yc: YeuCauCu) -> dict:
	"""`req.json().catch(() => ({}))` — thân không phải đối tượng JSON coi như {} (refresh, reconcile-action, test-connection)."""
	return yc.than if isinstance(yc.than, dict) else {}


def _rong_null(v):
	return None if v is None or v == "" else v


def _co_mui(luc):
	"""Giờ site (không múi) → datetime có múi giờ của site (dựng InvDate giờ VN — `gio_vn` đòi thời điểm tuyệt đối)."""
	return luc if luc.tzinfo is not None else luc.replace(tzinfo=ZoneInfo(get_system_timezone()))


def xu_ly_misa_khong_co(ten: str, luc=None) -> bool:
	"""[ĐX H5] MISA KHÔNG có tờ mang RefID của dòng `ten` (GET ?refID= ra None): dòng `pending` đã gửi quá `PHUT_TREO` phút (hoặc không có mốc gửi)
	→ `error` + câu "lượt đẩy trước chưa tới MISA…" + mốc hỏi — bấm Phát hành là đẩy lại CÙNG RefID (H3 hỏi trước). Còn trong 10 phút (MISA có thể
	chưa ghi xong) hoặc dòng không `pending` → không ghi gì. Một luật cho Làm mới (§4.3 bước 6) và vòng quét (§5.2 bước 4). → đã đổi dòng?"""
	luc = luc or bay_gio()
	# mốc hỏi không lùi (I10): lượt quét song song có thể đã ghi mốc muộn hơn
	frappe.db.sql(f"""UPDATE `tabNPP HDDT` SET `misa_status` = 'error', `misa_error` = %(loi)s,
			`misa_last_checked_at` = GREATEST(IFNULL(`misa_last_checked_at`, %(luc)s), %(luc)s), {SQL_DOI_MODIFIED}
		WHERE `name` = %(ten)s AND `misa_status` = 'pending' AND (`misa_sent_at` IS NULL OR `misa_sent_at` < %(moc)s)""",
		{"loi": LOI_LM_TREO, "luc": luc, "ten": ten, "moc": luc - _dt.timedelta(minutes=PHUT_TREO), **tham_so_modified()})
	return bool(frappe.db._cursor.rowcount)


def _bao_loi_route(ten_route: str, e: Exception, mac_dinh: str) -> tuple:
	"""Ngoại lệ không lường của một route → 500 {error} (nppsale: `errorMessage(err, …)` qua catch ngoài cùng) + Error Log. Câu trả về là
	`str(e)` — không có bí mật (lớp mạng không đưa tài khoản / token vào câu lỗi)."""
	_ghi_loi(f"HĐĐT MISA: {ten_route} lỗi")
	return _loi(500, str(e) or mac_dinh)


# ------------------------------------------------------------------------------------------------ §4.1 phát hành
def _ket_qua_cu(r) -> tuple:
	"""200 cached (`publish/route.ts:93–104`): không `sandbox`; chuỗi rỗng → null."""
	return 200, {"success": True, "cached": True, "lookup_code": _rong_null(r.misa_lookup_code), "ref_id": _rong_null(r.misa_ref_id),
		"inv_no": _rong_null(r.misa_inv_no), "invoice_url": _rong_null(r.misa_invoice_url)}


def ghi_loi_truoc_gui(ten: str, loi: str) -> None:
	"""Lỗi TRƯỚC khi gửi (cấu hình / giải mã / token — §4.1.1 bước 6, 8): `misa_status = error` + câu, CHỈ khi dòng vẫn "chưa tới MISA" (trống /
	error) ∧ chưa mã tra cứu ∧ chưa số ([Soát thiếu 2] cùng chốt H23 — không dán `error` lên tờ đã có số khi đua). Không đổi `misa_sent_at`,
	không RefID. Commit ngay (route trả lỗi sau đó)."""
	frappe.db.sql(f"""UPDATE `tabNPP HDDT` SET `misa_status` = 'error', `misa_error` = %(loi)s, {SQL_DOI_MODIFIED} WHERE `name` = %(ten)s
		AND IFNULL(`misa_status`, '') IN ('', 'error') AND IFNULL(`misa_lookup_code`, '') = '' AND IFNULL(`misa_inv_no`, '') = ''""",
		{"loi": loi, "ten": ten, **tham_so_modified()})
	commit_giua_chung()


class _LoiDocHang(Exception):
	"""Đọc người mua / dòng hàng hỏng — `str(e)` = câu 500 nguyên văn của nhánh (HĐ bán / đơn)."""


_COT_KHACH = ["customer_name", "tax_id", "npp_ten_xuat_hd", "npp_dia_chi_xuat_hd", "npp_dia_chi", "npp_email_xuat_hd", "npp_tuyen",
	"npp_hinh_thuc_tt"]


def _khach(ten_kh) -> dict:
	if not ten_kh:
		return {}
	return frappe.db.get_value("Customer", ten_kh, _COT_KHACH, as_dict=True) or {}


def _nguoi_mua(kh: dict, r) -> dict:
	"""Người mua từ khách HIỆN HÀNH (`si.customer` nppsale nhúng — `publish/route.ts:194–203`): tên / MST / địa chỉ xuất HĐ ∥ của khách ∥ của dòng
	HĐĐT; email / kênh / hình thức TT của khách (TT dự phòng 'Chuyển khoản'). Không ghi ngược vào dòng HĐĐT."""
	return {
		"ten": kh.get("npp_ten_xuat_hd") or kh.get("customer_name") or r.nguoi_mua or "",
		"mst": kh.get("tax_id") or r.mst_nguoi_mua or "",
		"dia_chi": kh.get("npp_dia_chi_xuat_hd") or kh.get("npp_dia_chi") or r.dia_chi_nguoi_mua or "",
		"email": kh.get("npp_email_xuat_hd") or None,
		"kenh": kh.get("npp_tuyen") or None,
		"hinh_thuc_tt": kh.get("npp_hinh_thuc_tt") or "Chuyển khoản",
	}


def _dong_chung_tu(sql: str, khoa, khi_trong_thue: int) -> list:
	"""Dòng chứng từ → dòng `dung_payload` (§4.1.2, cùng công thức mọi nhánh): đơn giá ĐÃ giảm + giảm dòng (trường ghi nhớ `npp_giam_dong` /
	`line_discount` — KHÔNG đọc `discount_amount` / `price_list_rate` của lõi: dòng hàng đổi mang giá bảng ở đó) cộng ngược thành giá gộp;
	thuế chụp trên dòng (nhánh đơn: thuế mặt hàng HIỆN HÀNH, trống → 10); tên hàng `Item.item_name` HIỆN HÀNH (H18); thứ tự `idx` /
	`sort_order` (H19); không lọc hàng đổi (H11)."""
	ra = []
	for x in frappe.db.sql(sql, khoa, as_dict=True):
		ra.append(dong_hang(x.ten or "", x.sku or None, x.dvt, x.dvt_co_so, x.sl, x.gia, x.giam, x.he_so if js_dung(x.he_so) else 1,
			thue_phan_tram(x.thue, khi_trong=khi_trong_thue)))
	return ra


def _nguoi_mua_va_dong(r) -> tuple[dict, list]:
	"""§4.1.2 — nguồn đầu có: (a) HĐ bán lưu trữ (P8) → (b) Sales Invoice → (c) đơn lưu trữ (P8) → (d) Sales Order (nhánh cũ, nppsale giữ cho dữ
	liệu trước v2b) → (e) không ra dòng: MỘT dòng tổng hợp từ tiền của dòng HĐĐT (tờ tay / không gắn chứng từ). Người mua lấy từ khách khi đọc
	được chứng từ, ngược lại từ dòng HĐĐT. Ngoại lệ CSDL → `_LoiDocHang` (câu 500 của nhánh) — dòng HĐĐT KHÔNG đổi."""
	nguoi_mua = {"ten": r.nguoi_mua or "", "mst": r.mst_nguoi_mua or "", "dia_chi": r.dia_chi_nguoi_mua or "", "email": "", "kenh": "",
		"hinh_thuc_tt": "Chuyển khoản"}
	dong = []
	if r.get("hoa_don_ban_ls") and _co_luu_tru():  # (a) — chưa dựng bảng lưu trữ (P8): nhánh viết theo blueprint, bỏ qua khi thiếu bảng
		try:
			hd = frappe.db.get_value("NPP LS Hoa Don", r.hoa_don_ban_ls, ["name", "customer_id"], as_dict=True)
			if hd:
				nguoi_mua = _nguoi_mua(_khach(hd.customer_id), r)
				dong = _dong_chung_tu("""SELECT d.`unit_name` AS dvt, d.`quantity` AS sl, d.`unit_price` AS gia, d.`line_discount` AS giam,
					d.`conversion_factor` AS he_so, d.`vat_rate` AS thue, d.`product_id` AS sku, i.`item_name` AS ten, i.`stock_uom` AS dvt_co_so
					FROM `tabNPP LS Hoa Don Dong` d LEFT JOIN `tabItem` i ON i.`name` = d.`product_id` WHERE d.`invoice_id` = %s
					ORDER BY d.`sort_order`, d.`name`""", r.hoa_don_ban_ls, 0)
		except Exception as e:
			raise _LoiDocHang(CAU_PH_DOC_HD.format(msg=str(e))) from e
	elif r.hoa_don_ban:  # (b)
		try:
			kh = frappe.db.get_value("Sales Invoice", r.hoa_don_ban, "customer")
			if kh is not None or frappe.db.exists("Sales Invoice", r.hoa_don_ban):
				nguoi_mua = _nguoi_mua(_khach(kh), r)
				dong = _dong_chung_tu("""SELECT d.`uom` AS dvt, d.`qty` AS sl, d.`rate` AS gia, d.`npp_giam_dong` AS giam, d.`conversion_factor` AS he_so,
					d.`npp_thue_suat` AS thue, d.`item_code` AS sku, i.`item_name` AS ten, i.`stock_uom` AS dvt_co_so
					FROM `tabSales Invoice Item` d LEFT JOIN `tabItem` i ON i.`name` = d.`item_code`
					WHERE d.`parent` = %s AND d.`parenttype` = 'Sales Invoice' ORDER BY d.`idx`, d.`name`""", r.hoa_don_ban, 0)
		except Exception as e:
			raise _LoiDocHang(CAU_PH_DOC_HD.format(msg=str(e))) from e
	elif r.get("don_hang_ls") and frappe.db.exists("DocType", "NPP LS Don Hang"):  # (c)
		try:
			don = frappe.db.get_value("NPP LS Don Hang", r.don_hang_ls, ["name", "customer_id"], as_dict=True)
			if don:
				nguoi_mua = _nguoi_mua(_khach(don.customer_id), r)
				dong = _dong_chung_tu("""SELECT d.`unit_name` AS dvt, d.`quantity` AS sl, d.`unit_price` AS gia, d.`line_discount` AS giam,
					d.`conversion_factor` AS he_so, i.`npp_thue_suat` AS thue, d.`product_id` AS sku, i.`item_name` AS ten, i.`stock_uom` AS dvt_co_so
					FROM `tabNPP LS Don Hang Dong` d LEFT JOIN `tabItem` i ON i.`name` = d.`product_id` WHERE d.`order_id` = %s
					ORDER BY d.`creation`, d.`name`""", r.don_hang_ls, 10)
		except Exception as e:
			raise _LoiDocHang(CAU_PH_DOC_DON.format(msg=str(e))) from e
	elif r.don_hang:  # (d)
		try:
			kh = frappe.db.get_value("Sales Order", r.don_hang, "customer")
			if kh is not None or frappe.db.exists("Sales Order", r.don_hang):
				nguoi_mua = _nguoi_mua(_khach(kh), r)
				dong = _dong_chung_tu("""SELECT d.`uom` AS dvt, d.`qty` AS sl, d.`rate` AS gia, d.`npp_giam_dong` AS giam, d.`conversion_factor` AS he_so,
					i.`npp_thue_suat` AS thue, d.`item_code` AS sku, i.`item_name` AS ten, i.`stock_uom` AS dvt_co_so
					FROM `tabSales Order Item` d LEFT JOIN `tabItem` i ON i.`name` = d.`item_code`
					WHERE d.`parent` = %s AND d.`parenttype` = 'Sales Order' ORDER BY d.`idx`, d.`name`""", r.don_hang, 10)
		except Exception as e:
			raise _LoiDocHang(CAU_PH_DOC_DON.format(msg=str(e))) from e
	if not dong:  # (e)
		dong = [dong_tong_hop(r.tien_hang, r.tien_thue, r.tong_tien)]
	return nguoi_mua, dong


def _hd_ban_hieu_luc(r, *, khoa: bool = False) -> tuple[bool, str]:
	"""[ĐX H6] HĐ bán của dòng còn hiệu lực → (đúng?, mã HĐ cho câu lỗi) — đúng chữ §4.1.1 bước 5 / 9: có `hoa_don_ban` → `docstatus` của Sales
	Invoice phải 1 (theo TÊN, không lọc tờ ghi có / tờ đầu kỳ: dòng chuyển sang ở P8 có thể kèm `hoa_don_ban` là tờ đầu kỳ cùng mã — §4.1.2 (a),
	§9.5; `doc_hd_ban` của lập dòng lọc hai loại ấy nên không dùng ở đây); CHỈ có `hoa_don_ban_ls` → `NPP LS Hoa Don.status = 'posted'` (mã =
	`invoice_code`). Dòng chỉ có đơn / không gắn gì: không kiểm [=]. Tờ HUỶ NỘI BỘ (`trang_thai = cancelled`) vẫn đẩy được [=].
	`khoa=True` (bước 9): `SELECT … FOR UPDATE` dòng Sales Invoice — đọc bản đã commit MỚI NHẤT và giữ khoá tới hết giao dịch giành tờ (thứ tự HĐ
	bán → dòng HĐĐT, cùng `_huy`: Huỷ HĐ song song xếp hàng sau, rồi thấy `pending` + RefID ⇒ LOCKED_EINVOICE — H2). Bản lưu trữ chỉ đọc."""
	if r.hoa_don_ban:
		x = frappe.db.sql("SELECT `docstatus` FROM `tabSales Invoice` WHERE `name` = %s" + (" FOR UPDATE" if khoa else ""), r.hoa_don_ban)
		return (bool(x) and cint(x[0][0]) == 1, r.hoa_don_ban)
	ls = r.get("hoa_don_ban_ls")
	if ls and _co_luu_tru():
		x = frappe.db.sql("SELECT `status`, `invoice_code` FROM `tabNPP LS Hoa Don` WHERE `name` = %s", ls)
		return (bool(x) and x[0][0] == "posted", (x[0][1] if x and x[0][1] else ls))
	return True, ""


def _con_hieu_luc(r) -> tuple[bool, str]:
	"""Bước 5 (đọc thường, trước khi gọi /oauth) — xem `_hd_ban_hieu_luc`; bước 9 đọc lại CÓ KHOÁ (HĐ có thể bị huỷ trong lúc lấy token)."""
	return _hd_ban_hieu_luc(r)


def _ghi_ket_qua_phat_hanh(ten: str, kq: dict) -> dict:
	"""§4.1.1 bước 14 (MISA nhận): dòng → `issued` (`phat_hanh_luc` = bây giờ nếu ĐANG draft, giữ nếu khác — có thể NULL), mã tra cứu / link / ký
	chỉ khi MISA trả mã (H20: dạng phản hồi tài liệu mô tả thì không bao giờ có ⇒ thực tế `sent`), `misa_error` NULL. KHÔNG ghi `misa_ref_id`
	(đã ghi ở giành tờ — nguồn sự thật là thứ đã gửi), KHÔNG ghi số / ký hiệu / ngày / quan hệ (I2 — chỉ luồng kéo về). → {lookup_code,
	invoice_url}. Đọc lại dòng CÓ KHOÁ (bản mới nhất).

	[Sửa cuối — phát hiện 15] RefID đã commit trước POST ⇒ cổng trả RefID cho tờ `pending` ⇒ màn hiện "Làm mới": người khác / vòng quét có thể kéo
	bản ghi MISA về TRONG LÚC POST còn chờ (≤ 110 s). Dòng không còn `pending` (kéo về đã áp bản ghi MISA — `sent` / `amount_mismatch` / `signed`…)
	⇒ KHÔNG ghi `misa_status` (bản ghi MISA là sự thật, mới hơn phản hồi POST); mã tra cứu / link / mốc ký CHỈ ghi khi phản hồi có mã — không bao
	giờ ghi NULL đè giá trị đang đúng (§0.2-7; trước giành tờ các cột ấy luôn trống nên lần đẩy thường không đổi gì)."""
	luc = bay_gio()
	ma = kq.get("lookup_code") or None
	url = url_tra_cuu(ma)
	r = doc_dong_hddt(ten, khoa=True)
	cap = {"trang_thai": "issued", "misa_error": None}
	if ma:
		cap.update({"misa_lookup_code": ma, "misa_invoice_url": url, "misa_signed_at": luc, "misa_published_at": luc})
	if r is None or (r.misa_status or "") == "pending":
		cap["misa_status"] = "signed" if ma else "sent"
	if r is not None and (r.trang_thai or "") == "draft":
		cap["phat_hanh_luc"] = luc
	frappe.db.set_value("NPP HDDT", ten, cap)  # đổi `modified` (phát hiện 16)
	return {"lookup_code": ma, "invoice_url": url}


def _ket_qua_loi_day(ten: str, misa_status: str, misa_error: str) -> None:
	"""MISA lỗi rõ / chưa gửi được (→ error) hoặc chưa biết (→ giữ pending): chỉ ghi khi dòng còn `pending` (lượt Làm mới song song đã thấy tờ trên
	MISA thì không dán lại lỗi). RefID giữ."""
	frappe.db.sql(f"""UPDATE `tabNPP HDDT` SET `misa_status` = %(st)s, `misa_error` = %(loi)s, {SQL_DOI_MODIFIED}
		WHERE `name` = %(ten)s AND `misa_status` = 'pending'""", {"st": misa_status, "loi": misa_error, "ten": ten, **tham_so_modified()})


@tuyen("POST", r"^/api/einvoice/publish$")
def phat_hanh(yc: YeuCauCu):
	"""POST /api/einvoice/publish `{invoiceId, mode?, poNote?}` (`publish/route.ts`, đặc tả §4.1). Bọc toàn thân: ngoại lệ lọt → 500
	`{error: câu ∥ "Lỗi server không xác định khi gọi MISA"}` (`publish/route.ts:20–30`)."""
	try:
		return _phat_hanh(yc)
	except Exception as e:  # route trả JSON {error}, không để lỗi Frappe (màn đọc khoá `error`)
		return _bao_loi_route("phát hành", e, CAU_PH_SERVER)


def _phat_hanh(yc: YeuCauCu) -> tuple:
	# 1. thân / mã dòng
	if not isinstance(yc.than, dict):
		return _loi(400, CAU_BODY)
	than = yc.than
	ten = _ma(than.get("invoiceId"))
	if not ten:
		return _loi(400, CAU_THIEU_ID)
	che_do = "box" if than.get("mode") == "box" else "as_sold"
	po = than.get("poNote")
	# 2. vai cứng (không qua ma trận quyền)
	if hien_tai().vai not in VAI_PHAT_HANH:
		return _loi(403, CAU_PH_QUYEN)
	# 3. dòng (không khoá)
	r = doc_dong_hddt(ten)
	if r is None:
		return _loi(404, CAU_PH_KHONG_CO)
	# 4. kết quả cũ / đang xử lý — không gọi MISA, không ghi
	if r.misa_lookup_code or r.misa_inv_no:  # a / a' [ĐX H23 — tờ MẤT RefID hay `error` đã có số không bị đẩy nháp thứ hai]
		return _ket_qua_cu(r)
	if (r.misa_status or "") in MISA_DA_TOI:  # b
		return _ket_qua_cu(r)
	if r.misa_status == "pending":  # c [ĐX H4 — 409 đúng câu nppsale, không cached]
		return _loi(409, CAU_PH_DANG_XU_LY)
	# 5. [ĐX H6] HĐ bán còn hiệu lực
	ok, ma_hd = _con_hieu_luc(r)
	if not ok:
		return _loi(400, CAU_HET_HIEU_LUC.format(ma=ma_hd))
	# 6. cấu hình (phát hành: token_path KHÔNG lùi về /oauth — publish/route.ts:329 [=])
	try:
		ch = MM.lay_cau_hinh(lui_duong_token=False)
	except MM.LoiCauHinh as e:  # [Sửa cuối — phát hiện 6] địa chỉ / đường MISA không hợp lệ (sửa tay trên Desk): không giải mã, không gọi
		ghi_loi_truoc_gui(ten, str(e))
		return _loi(400, str(e))
	except Exception as e:
		cau = CAU_DOC_CAU_HINH.format(msg=str(e))
		try:
			ghi_loi_truoc_gui(ten, cau)
		except Exception:  # CSDL đang hỏng: báo lỗi đọc là đủ
			_ghi_loi("HĐĐT MISA: phát hành — không ghi được lỗi cấu hình")
		return _loi(500, cau)
	if ch is None or not ch.dang_dung:
		ghi_loi_truoc_gui(ten, LOI_PH_CHUA_CAU_HINH)
		return _loi(400, CAU_PH_CHUA_CAU_HINH)
	from nppsale.npp_hddt.doctype.npp_misa_cau_hinh.npp_misa_cau_hinh import co_bi_mat

	if not (co_bi_mat("tai_khoan") and co_bi_mat("mat_khau")):  # nppsale xét có bản mã TRƯỚC khi giải mã (`!username_enc || !password_enc`)
		ghi_loi_truoc_gui(ten, LOI_PH_THIEU_TK)
		return _loi(400, CAU_PH_THIEU_TK)
	try:
		ch.giai_ma()
	except MM.LoiGiaiMa as e:
		cau = CAU_PH_GIAI_MA.format(ly_do=e.ly_do)
		ghi_loi_truoc_gui(ten, cau)
		return _loi(500, cau)
	if not ch.tai_khoan or not ch.mat_khau:
		ghi_loi_truoc_gui(ten, LOI_PH_THIEU_TK)
		return _loi(400, CAU_PH_THIEU_TK)
	# 7. người mua + dòng hàng (đọc, chưa khoá) — hỏng: dòng không đổi (nppsale kẹt `pending` vì đã khoá trước)
	try:
		nguoi_mua, dong = _nguoi_mua_va_dong(r)
	except _LoiDocHang as e:
		return _loi(500, str(e))
	# 8. token TRƯỚC giành tờ — không giữ khoá dòng trong lúc chờ /oauth
	bat_dau = MM._dong_ho()
	try:
		MM.lay_token(ch)
	except MM.MisaLoi as e:
		cau = str(e)
		ghi_loi_truoc_gui(ten, cau)
		_ghi_nhat_ky_an_toan("publish", "failed", hddt=ten, don_hang=r.don_hang or r.get("don_hang_ls"), loi=cau)
		commit_giua_chung()
		return _loi(500, cau)
	# 9. giành tờ: khoá HĐ bán → dòng HĐĐT (cùng thứ tự `_huy`), RefID (giữ cũ ∥ mới) + pending + mốc gửi, COMMIT trước khi gọi MISA
	ok, ma_hd = _hd_ban_hieu_luc(r, khoa=True)
	if not ok:
		return _loi(400, CAU_HET_HIEU_LUC.format(ma=ma_hd))
	x = doc_dong_hddt(ten, khoa=True)
	if x is None:
		return _loi(404, CAU_PH_KHONG_CO)
	if (x.misa_status or "") not in ("", "error") or x.misa_lookup_code or x.misa_inv_no:
		return _loi(409, CAU_PH_DANG_XU_LY)
	if _doi_truong_payload(r, x):
		# [Sửa cuối — phát hiện 14] người mua / tiền vừa được sửa (H24 — cổng cho sửa dòng `error`) giữa bước 3 và bước 9: dựng lại từ bản ĐÃ KHOÁ —
		# gửi bản cũ là MISA nhận dữ liệu cũ cùng RefID trong khi sổ ghi dữ liệu mới (nppsale dựng payload SAU khi giành tờ nên không có cửa sổ này)
		try:
			nguoi_mua, dong = _nguoi_mua_va_dong(x)
		except _LoiDocHang as e:  # chưa ghi gì: dòng không đổi
			return _loi(500, str(e))
	ref_cu = (x.misa_ref_id or "").strip() or None
	ref = ref_cu or str(uuid.uuid4())
	frappe.db.sql(f"""UPDATE `tabNPP HDDT` SET `misa_status` = 'pending', `misa_ref_id` = %(ref)s, `misa_sent_at` = %(luc)s, `misa_error` = NULL,
		{SQL_DOI_MODIFIED} WHERE `name` = %(ten)s""", {"ref": ref, "luc": bay_gio(), "ten": ten, **tham_so_modified()})
	commit_giua_chung()
	return _sau_gianh_to(ten, x, ref, ref_cu, ch, nguoi_mua, dong, che_do, po, bat_dau)


# Trường của dòng HĐĐT mà payload đọc (§4.1.2: người mua + dòng tổng hợp của tờ tay; nguồn chứng từ)
_COT_PAYLOAD = ("nguoi_mua", "dia_chi_nguoi_mua", "mst_nguoi_mua", "tien_hang", "tien_thue", "tong_tien", "hoa_don_ban", "don_hang",
	"hoa_don_ban_ls", "don_hang_ls")


def _doi_truong_payload(r, x) -> bool:
	"""Bản đọc thường (bước 3) và bản đọc CÓ KHOÁ (bước 9) khác nhau ở một trường payload dùng (tiền so theo số — Decimal / float)."""
	for k in _COT_PAYLOAD:
		a, b = r.get(k), x.get(k)
		if k in ("tien_hang", "tien_thue", "tong_tien"):
			if flt(a) != flt(b):
				return True
		elif (a or "") != (b or ""):
			return True
	return False


def _da_co_tren_misa(ten: str, raw, ch, *, gui_di, don_hang) -> tuple:
	"""MISA ĐÃ có tờ mang RefID này (hỏi trước khi đẩy lại — H3; hỏi trước khi thử lại POST — H27): KHÔNG POST; áp kết quả như Làm mới + xác nhận
	đẩy (H5), một nhật ký `success`, commit → 200 cached (đọc lại dòng)."""
	kq = ghi_ket_qua_keo_ve(ten, raw, xac_nhan_day=True, luc=bay_gio(), co_ma=ch.co_ma)
	ghi_nhat_ky("publish", "success", hddt=ten, don_hang=don_hang, gui_di=gui_di, nhan_ve=MM.che_ban_ghi(raw, ch), loi=CAU_DA_CO_TREN_MISA,
		misa_lookup_code=kq["cap_nhat"].get("misa_lookup_code"), misa_inv_no=kq["so_that"])
	commit_giua_chung()
	return _ket_qua_cu(doc_dong_hddt(ten))


def _sau_gianh_to(ten, x, ref, ref_cu, ch, nguoi_mua, dong, che_do, po, bat_dau) -> tuple:
	"""§4.1.1 bước 10–15 — dòng đã `pending` + RefID trong sổ (đã commit). Ngoại lệ lọt (bước 15): chưa gửi → `error` + câu; đã gửi → giữ `pending`;
	nhật ký `failed` best-effort (nếu lượt này chưa có nhật ký) → 500.

	"Đã gửi" gồm cả khi MISA ĐÃ XÁC NHẬN có tờ mang RefID này (bước 10 hỏi trước / H27 hỏi trước lần POST 2) mà ghi kết quả hỏng: tờ nằm trên MISA
	⇒ GIỮ `pending` (Làm mới / vòng quét gỡ theo RefID). Đặt `error` là mở khoá Huỷ / Sửa HĐ bán (vế H2 chỉ khoá pending / sent / waiting_code — §6.1)
	cho một HĐ đã có nháp trên MISA, và cổng che RefID (H3b) cho một tờ đã tới MISA [ĐX — §4.1.1 bước 15 chỉ phân "tới bước 12 chưa"]."""
	don_hang = x.don_hang or x.get("don_hang_ls")
	diem = "npp_misa_sau_gianh"
	frappe.db.savepoint(diem)
	da_gui, da_ghi_nhat_ky, payload, ban_ghi_misa = False, False, None, None
	try:
		# 10. [ĐX H3] đẩy lại (đã có RefID): hỏi MISA trước — có ⇒ không POST
		if ref_cu:
			try:
				raw = ban_ghi_cua_to(MM.lay_hd(ch, ref), "pending", ref)  # bản ghi rỗng `{}` = MISA không có (phát hiện 9)
			except MM.MisaLoi as e:
				cau = CAU_PH_HOI_TRUOC.format(cau=str(e))
				_ket_qua_loi_day(ten, "error", cau)
				commit_giua_chung()
				return _loi(502, cau)
			if raw is not None:
				ban_ghi_misa = raw
				return _da_co_tren_misa(ten, raw, ch, gui_di={"source": "hoi_truoc_khi_day_lai", "ref_id": ref}, don_hang=don_hang)
		# 11. payload (RefID truyền từ ngoài vào — đã commit)
		payload = dung_payload(nguoi_mua, dong, ref, ch.cau_hinh_payload, che_do, po if isinstance(po, str) else None, _co_mui(bay_gio()))
		# 12. POST + 1 lần thử lại khi lỗi xác thực; [ĐX H27] trước lần thử lại hỏi MISA
		da_gui = True
		kq = MM.day_hd(ch, payload, truoc_khi_thu_lai=lambda: ban_ghi_cua_to(MM.lay_hd(ch, ref), "pending", ref), bat_dau=bat_dau)
		if kq.get("da_co") is not None:  # hỏng giữa chừng → bước 15 ghi MỘT nhật ký failed cho lần POST này (I5)
			ban_ghi_misa = kq["da_co"]
			return _da_co_tren_misa(ten, kq["da_co"], ch, gui_di=payload, don_hang=don_hang)
		# 13. nhật ký (best-effort) — commit: sống kể cả khi bước 14 hỏng
		ket_qua = "success" if kq["ok"] else ("pending" if kq.get("chua_biet") else "failed")
		so_tra = kq.get("inv_no")
		_ghi_nhat_ky_an_toan("publish", ket_qua, hddt=ten, don_hang=don_hang, gui_di=payload, nhan_ve=kq.get("raw"),
			loi=None if kq["ok"] else kq.get("error"), misa_lookup_code=kq.get("lookup_code"),
			misa_inv_no=None if la_so_cho(so_tra) else so_tra)
		da_ghi_nhat_ky = True
		commit_giua_chung()
		frappe.db.savepoint(diem)  # lui ở bước 15 chỉ bỏ phần CHƯA commit (bài thử không commit — cùng ngữ nghĩa)
		# 14. ghi kết quả
		if kq["ok"]:
			frappe.db.savepoint("npp_misa_ket_qua")
			try:
				ma = _ghi_ket_qua_phat_hanh(ten, kq)
				commit_giua_chung()
			except Exception:  # MISA ĐÃ nhận: không để người dùng bấm lại (dòng còn pending + RefID ⇒ Làm mới gỡ được)
				frappe.db.rollback(save_point="npp_misa_ket_qua")
				_ghi_loi("HĐĐT MISA: MISA đã nhận nhưng chưa ghi được kết quả")
				lookup = kq.get("lookup_code") or None
				return 500, {"success": False, "error": CAU_PH_DA_PHAT_HANH, "misa": {"lookup_code": lookup, "invoice_url": url_tra_cuu(lookup)}}
			return 200, {"success": True, "lookup_code": ma["lookup_code"], "inv_no": kq.get("inv_no"), "invoice_url": ma["invoice_url"],
				"sandbox": bool(ch.moi_truong_thu)}
		if kq.get("chua_biet"):  # đứt sau khi gửi: giữ pending — Làm mới / vòng quét gỡ theo RefID
			_ket_qua_loi_day(ten, "pending", LOI_PH_CHUA_BIET)
			commit_giua_chung()
			return _loi(502, kq.get("error") or MM.CAU_CHUA_BIET)
		cau = kq.get("error") or CAU_PH_MISA_LOI  # MISA lỗi rõ / chưa gửi được: error, RefID giữ
		_ket_qua_loi_day(ten, "error", cau)
		commit_giua_chung()
		return _loi(502, cau)
	except LoiTrungSoHddt as e:
		# MISA CÓ tờ (bước 10 / H27) mà số MISA cấp đụng chỉ mục (ký hiệu, số) của tờ khác trong sổ (H13 — như Làm mới): dòng không đổi gì ngoài
		# câu lỗi, GIỮ `pending` (xem docstring), nhật ký `failed` — lần POST của lượt này (H27) phải có đúng một nhật ký (I5).
		_lui(diem)
		cau = str(e)
		_ket_qua_loi_day(ten, "pending", cau)
		_ghi_nhat_ky_an_toan("publish", "failed", hddt=ten, don_hang=don_hang, gui_di=payload if payload is not None else
			{"source": "hoi_truoc_khi_day_lai", "ref_id": ref}, nhan_ve=MM.che_ban_ghi(ban_ghi_misa, ch), loi=cau)
		commit_giua_chung()
		return _loi(409, cau)
	except Exception as e:  # bước 15
		_ghi_loi("HĐĐT MISA: phát hành lỗi sau khi giành tờ")
		cau = str(e) or CAU_PH_KHONG_XAC_DINH
		_lui(diem)
		try:
			if not da_gui and ban_ghi_misa is None:  # chưa gửi ∧ MISA chưa xác nhận có tờ
				_ket_qua_loi_day(ten, "error", cau)
			if not da_ghi_nhat_ky:
				_ghi_nhat_ky_an_toan("publish", "failed", hddt=ten, don_hang=don_hang, gui_di=payload, loi=cau)
			commit_giua_chung()
		except Exception:  # CSDL hỏng: lỗi gốc đã vào Error Log
			pass
		return _loi(500, cau)


def _lui(diem: str) -> None:
	try:
		frappe.db.rollback(save_point=diem)
	except Exception:  # điểm lưu mất (kết nối hỏng): không còn gì để lui
		pass


# ------------------------------------------------------------------------------------------------ §4.3 làm mới
@tuyen("POST", r"^/api/einvoice/refresh-status$")
def lam_moi(yc: YeuCauCu):
	"""POST /api/einvoice/refresh-status `{invoiceId}` (`refresh-status/route.ts:28–173`, đặc tả §4.3)."""
	try:
		return _lam_moi(yc)
	except Exception as e:
		return _bao_loi_route("làm mới", e, CAU_TK_KHONG_XAC_DINH)


def _lam_moi(yc: YeuCauCu) -> tuple:
	ten = _ma(_than(yc).get("invoiceId"))
	if not ten:
		return _loi(400, CAU_THIEU_ID)
	if hien_tai().vai not in VAI_PHAT_HANH:
		return _loi(403, CAU_KHONG_QUYEN)
	try:
		r = doc_dong_hddt(ten)
	except Exception:
		_ghi_loi("HĐĐT MISA: làm mới — đọc hoá đơn lỗi")
		return _loi(500, CAU_LM_LOI_DOC)
	if r is None:
		return _loi(404, CAU_LM_KHONG_CO)
	ref = (r.misa_ref_id or "").strip()
	if not ref:  # KHÔNG lùi về misa_lookup_code (TransactionID là mã khác — hỏi bằng nó là đoán)
		return _loi(409, CAU_LM_MAT_REFID) if r.misa_inv_no else _loi(400, CAU_LM_CHUA_DAY)
	try:
		ch = MM.lay_cau_hinh()
	except MM.LoiCauHinh as e:  # [Sửa cuối — phát hiện 6] địa chỉ / đường MISA không hợp lệ: không giải mã, không gọi
		return _loi(400, str(e))
	except Exception:
		_ghi_loi("HĐĐT MISA: làm mới — đọc cấu hình lỗi")
		return _loi(500, CAU_LM_LOI_CAU_HINH)
	if ch is None:  # không xét `dang_dung` [=]
		return _loi(400, CAU_CHUA_CAU_HINH)
	try:
		ch.giai_ma()
	except MM.LoiGiaiMa as e:
		return _loi(500, str(e))
	try:
		raw = ban_ghi_cua_to(MM.lay_hd(ch, ref), r.misa_status, ref)  # tờ treo / lỗi + bản ghi rỗng `{}` = MISA không có (phát hiện 9)
	except MM.MisaLoi as e:
		return _loi(502, str(e))
	if raw is None:
		xu_ly_misa_khong_co(ten)  # [ĐX H5]; dòng khác `pending` / còn trong 10 phút: không ghi gì [=]
		return _loi(404, CAU_LM_MISA_RONG)
	try:
		kq = ghi_ket_qua_keo_ve(ten, raw, xac_nhan_day=(r.misa_status in ("pending", "error")), luc=bay_gio(), co_ma=ch.co_ma)
	except LoiTrungSoHddt as e:
		return _loi(409, str(e))
	except Exception as e:  # [ĐX H13] nppsale console.error rồi vẫn 200
		_ghi_loi("HĐĐT MISA: làm mới — ghi kết quả lỗi")
		return _loi(500, CAU_LM_GHI_HONG.format(msg=str(e)))
	if kq["ghi_chu"]:  # [BP] nhật ký khi có ghi chú (nppsale không ghi log cho lượt bấm tay)
		_ghi_nhat_ky_an_toan("refresh", "success", hddt=ten, don_hang=r.don_hang or r.get("don_hang_ls"),
			gui_di={"source": "refresh", "ref_id": ref}, nhan_ve=MM.che_ban_ghi(raw, ch), loi="\n".join(kq["ghi_chu"]), misa_inv_no=kq["so_that"])
	tho = raw if isinstance(raw, dict) else {}
	tt = kq["tom_tat"]
	return 200, {"success": True, "misa": {
		"InvNo": tt["InvNo"], "TransactionID": kq["cap_nhat"].get("misa_lookup_code"), "PublishStatus": tho.get("PublishStatus"),
		# trạng thái ĐÃ GHI (= `ap_dung`, trừ xác nhận đẩy mặc định `sent` — phát hiện 1); null = giữ
		"EInvoiceStatus": tho.get("EInvoiceStatus"), "relation": tt["relation"], "status": kq["cap_nhat"].get("misa_status"), "notes": kq["ghi_chu"],
		"original_marked_replaced": kq["goc"]}}


# ------------------------------------------------------------------------------------------------ §4.4 cấu hình
def _vai_cau_hinh() -> bool:
	return hien_tai().vai in VAI_CAU_HINH


def _gio_iso(v):
	"""Mốc giờ (Single lưu chữ) → ISO có múi như cột timestamptz PostgREST trả."""
	if not v:
		return None
	from nppsale.cong.truy_van import chuan_gia_tri

	return chuan_gia_tri("gio", get_datetime(v))


@tuyen("GET", r"^/api/einvoice/config$")
def cau_hinh_doc(yc: YeuCauCu):
	try:
		return _cau_hinh_doc(yc)
	except Exception as e:
		return _bao_loi_route("đọc cấu hình", e, CAU_TK_KHONG_XAC_DINH)


def _cau_hinh_doc(yc: YeuCauCu):
	"""GET /api/einvoice/config (`config/route.ts:31–60`): chưa lưu → `{config: null}`; có → mọi trường trừ tài khoản / mật khẩu (kể cả `*****`) +
	`has_username` / `has_password` (đọc `__Auth`, KHÔNG giải mã — GET không được hỏng vì khoá site sai)."""
	if not _vai_cau_hinh():
		return _loi(403, CAU_CH_QUYEN)
	try:
		from nppsale.npp_hddt.doctype.npp_misa_cau_hinh.npp_misa_cau_hinh import co_bi_mat, da_luu

		if not da_luu():
			return 200, {"config": None}
		d = frappe.db.get_singles_dict(TEN_CAU_HINH)
		s = lambda k: _rong_null(d.get(k))  # noqa: E731
		b = lambda k: bool(int(d.get(k) or 0))  # noqa: E731
		i = lambda k: int(flt(d.get(k))) if d.get(k) not in (None, "") else None  # noqa: E731
		return 200, {"config": {
			"id": TEN_CAU_HINH, "org_id": _rong_null(frappe.db.get_single_value("NPP Cai Dat", "org_id")), "provider": s("nha_cung_cap"),
			"api_base": s("dia_chi_api"), "tax_code": s("mst_nguoi_ban"), "seller_name": s("ten_nguoi_ban"), "seller_address": s("dia_chi_nguoi_ban"),
			"misa_company_id": s("misa_company_id"), "misa_org_unit_id": s("misa_org_unit_id"), "misa_template_id": s("misa_template_id"),
			"misa_user_id": s("misa_user_id"), "misa_inv_series": s("misa_inv_series"), "misa_inv_template_no": s("misa_inv_template_no"),
			"sandbox": b("moi_truong_thu"), "is_active": b("dang_dung"), "token_path": s("duong_lay_token"), "publish_path": s("duong_phat_hanh"),
			"misa_app_id": s("misa_app_id"), "sign_type": i("kieu_ky"), "invoice_type": i("loai_hd"),
			"is_inherit_from_old_template": b("ke_thua_mau_cu"), "misa_is_invoice_with_code": b("misa_is_invoice_with_code"),
			"created_at": None, "updated_at": _gio_iso(d.get("modified")),
			"has_username": co_bi_mat("tai_khoan"), "has_password": co_bi_mat("mat_khau"),
		}}
	except Exception as e:
		_ghi_loi("HĐĐT MISA: đọc cấu hình lỗi")
		return _loi(500, CAU_DOC_CAU_HINH.format(msg=str(e)))


def _js_parse_int(v):
	"""`parseInt(chuỗi, 10)` của JS: bỏ khoảng trắng đầu, dấu, chữ số đầu; không có chữ số → None (NaN)."""
	import re

	m = re.match(r"[+-]?[0-9]+", js_trim(v))
	return int(m.group(0)) if m else None


def _loai_hd(v) -> int:
	"""invoice_type của thân (`config/route.ts:83–90`): số (không bool) giữ, chuỗi khác rỗng → parseInt, còn lại 1; không hữu hạn / < 1 → 1."""
	import math

	if isinstance(v, (int, float)) and not isinstance(v, bool):
		x = v
	elif isinstance(v, str) and js_trim(v):
		x = _js_parse_int(v)
	else:
		x = 1
	if x is None or (isinstance(x, float) and not math.isfinite(x)) or x < 1:
		return 1
	return int(x)


@contextmanager
def _sach_message_log():
	"""Bước bọc hỏng → bỏ thông điệp tiếng Anh lõi đã đẩy vào message_log (frappe.throw / msgprint — "Encryption key is in invalid format!",
	"… must be unique") để không về trình duyệt qua `_server_messages`; route tự trả câu tiếng Việt."""
	nk = getattr(frappe.local, "message_log", None)
	n = len(nk) if nk is not None else 0
	try:
		yield
	except Exception:
		if nk is not None:
			del nk[n:]
		raise


def _khoa_ma_hoa_dung() -> bool:
	"""Khoá site mã hoá được không (Fernet hợp lệ) — `encrypt` của lõi gặp khoá sai định dạng là frappe.throw tiếng Anh."""
	from cryptography.fernet import Fernet
	from frappe.utils import encode
	from frappe.utils.password import get_encryption_key

	try:
		Fernet(encode(get_encryption_key()))
	except Exception:
		return False
	return True


@tuyen("POST", r"^/api/einvoice/config$")
def cau_hinh_luu(yeu_cau_secret: YeuCauCu):
	try:
		return _cau_hinh_luu(yeu_cau_secret)
	except Exception as e:
		return _bao_loi_route("lưu cấu hình", e, CAU_TK_KHONG_XAC_DINH)


def _cau_hinh_luu(yeu_cau_secret: YeuCauCu):
	"""POST /api/einvoice/config (`config/route.ts:62–131`): màn gửi CẢ đối tượng form (kể cả `has_*`, `id`, `org_id`…) — chỉ đọc khoá dưới, bỏ
	khoá lạ. Chuỗi trim kiểu JS, rỗng → mặc định / trống; `ke_thua_mau_cu` vắng → 0, `moi_truong_thu` / `dang_dung` vắng → 1, có thì truthy kiểu JS
	(chuỗi "false" là ĐÚNG). KHÔNG ghi `misa_is_invoice_with_code`, `misa_app_id`, `kieu_ky`. Tài khoản / mật khẩu (trim — nppsale cắt khoảng trắng
	hai đầu mật khẩu) chỉ gán khi người gõ chữ khác rỗng: gán ''/None rồi save() là XOÁ bản mã (`_save_passwords`); không db_set /
	set_single_value cho hai trường Password (bỏ qua mã hoá — lưu chữ thường). Lưu qua `doc.save()` (mã hoá vào `__Auth`, `tabSingles` chỉ còn `*`)."""
	if not _vai_cau_hinh():
		return _loi(403, CAU_CH_QUYEN)
	if not isinstance(yeu_cau_secret.than, dict):
		return _loi(400, CAU_BODY)
	than_secret = yeu_cau_secret.than  # tên có `secret`: bộ che traceback của lõi che theo tên biến

	def s(k):
		v = than_secret.get(k)
		return (js_trim(v) or None) if isinstance(v, str) else None

	tai_khoan_secret, password_moi = s("username"), s("password")
	dia_chi = s("api_base") or "https://testapp.meinvoice.vn/api/v2"
	duong_token, duong_day = s("token_path") or "/oauth", s("publish_path") or "/v3sainvoice"
	loi = MM.kiem_cau_hinh(dia_chi, duong_token, duong_day)  # [Sửa cuối — phát hiện 6 (+3)] trước khi lưu: 400 câu tiếng Việt
	if loi:
		return _loi(400, loi)
	if (tai_khoan_secret or password_moi) and not _khoa_ma_hoa_dung():
		return _loi(500, CAU_CH_MA_HOA)
	from nppsale.npp_hddt.doctype.npp_misa_cau_hinh.npp_misa_cau_hinh import da_luu

	# [Sửa cuối — phát hiện 6 (2)] ĐỔI MÁY MISA mà không gõ lại tài khoản / mật khẩu ⇒ XOÁ bản đã lưu (gán trống rồi save — `_save_passwords`):
	# tài khoản của máy cũ không bao giờ tự đi sang máy mới (thử ↔ thật là hai tài khoản khác nhau). Không từ chối: màn "Test kết nối" lưu trước mà
	# không xem kết quả lưu — từ chối là lượt thử chạy bằng cấu hình CŨ; xoá thì lượt thử báo "Thiếu username/password" rõ ràng.
	doi_may = da_luu() and MM.may_cua(frappe.db.get_single_value(TEN_CAU_HINH, "dia_chi_api") or "") != MM.may_cua(dia_chi)
	try:
		with _sach_message_log():
			d = frappe.get_single(TEN_CAU_HINH)
			d.nha_cung_cap = "misa"
			d.dia_chi_api = dia_chi
			d.duong_lay_token = duong_token
			d.duong_phat_hanh = duong_day
			for k, truong in (("tax_code", "mst_nguoi_ban"), ("seller_name", "ten_nguoi_ban"), ("seller_address", "dia_chi_nguoi_ban"),
					("misa_company_id", "misa_company_id"), ("misa_org_unit_id", "misa_org_unit_id"), ("misa_template_id", "misa_template_id"),
					("misa_user_id", "misa_user_id"), ("misa_inv_series", "misa_inv_series")):
				d.set(truong, s(k))
			d.misa_inv_template_no = s("misa_inv_template_no") or "1"
			d.loai_hd = _loai_hd(than_secret.get("invoice_type"))
			d.ke_thua_mau_cu = 1 if "is_inherit_from_old_template" in than_secret and js_dung(than_secret["is_inherit_from_old_template"]) else 0
			d.moi_truong_thu = 1 if "sandbox" not in than_secret or js_dung(than_secret["sandbox"]) else 0
			d.dang_dung = 1 if "is_active" not in than_secret or js_dung(than_secret["is_active"]) else 0
			if tai_khoan_secret:
				d.tai_khoan = tai_khoan_secret
			elif doi_may:
				d.tai_khoan = None
			if password_moi:
				d.mat_khau = password_moi
			elif doi_may:
				d.mat_khau = None
			d.save(ignore_permissions=True)
	except Exception as e:
		_ghi_loi("HĐĐT MISA: lưu cấu hình lỗi")
		return _loi(500, str(e) or CAU_TK_KHONG_XAC_DINH)
	return 200, {"success": True}


# ------------------------------------------------------------------------------------------------ §4.5 thử kết nối
def _chu(v):
	"""Giá trị mẫu MISA → chữ cho trường Data (số → `so_js`; None giữ None)."""
	if v is None or isinstance(v, str):
		return v
	return so_js(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


@tuyen("POST", r"^/api/einvoice/test-connection$")
def thu_ket_noi(yeu_cau_secret: YeuCauCu):
	"""POST /api/einvoice/test-connection `{username?, password?}` (`test-connection/route.ts:35–159`, đặc tả §4.5)."""
	try:
		return _thu_ket_noi(yeu_cau_secret)
	except Exception as e:
		return _bao_loi_route("thử kết nối", e, CAU_TK_KHONG_XAC_DINH)


def _thu_ket_noi(yeu_cau_secret: YeuCauCu) -> tuple:
	than_secret = _than(yeu_cau_secret)  # tên có `secret` / `password` / `token`: bộ che traceback của lõi che theo tên
	if not _vai_cau_hinh():
		return _loi(403, CAU_TK_QUYEN)
	try:
		ch = MM.lay_cau_hinh()  # token_path ∥ "/oauth"; không xét `dang_dung`
	except MM.LoiCauHinh as e:  # [Sửa cuối — phát hiện 6] địa chỉ / đường MISA không hợp lệ: không giải mã, không gọi
		return _loi(400, str(e))
	except Exception:
		_ghi_loi("HĐĐT MISA: thử kết nối — đọc cấu hình lỗi")
		return _loi(500, CAU_LM_LOI_CAU_HINH)
	if ch is None:
		return _loi(400, CAU_TK_CHUA_LUU)
	tai_khoan_secret = than_secret.get("username") if isinstance(than_secret.get("username"), str) else None
	password_go = than_secret.get("password") if isinstance(than_secret.get("password"), str) else None
	try:
		ch.giai_ma(tai_khoan_secret, password_go)  # [Soát thiếu 2] chỉ giải mã trường thân KHÔNG có chữ (`||` ngắn mạch — route.ts:80–81)
	except MM.LoiGiaiMa as e:
		return _loi(500, str(e))
	if not ch.tai_khoan or not ch.mat_khau:
		return _loi(400, CAU_TK_THIEU)
	try:
		token, tho_token = MM.lay_token(ch, ep=True, tra_tho=True)  # MỘT lời /oauth (nppsale gọi hai lần — client.ts:259–283 [≠ nhỏ])
	except MM.MisaLoi as e:
		return _loi(502, str(e))
	ids = tach_dinh_danh(tho_token)
	ch.co_ma = bool(ids["isInvoiceWithCode"])
	mau, loi_mau = [], None
	try:
		mau = MM.lay_mau(ch, token, 0)  # TypeInvoice = 0 theo ví dụ LAYMAU
	except MM.MisaLoi as e:
		loi_mau = str(e)  # không chặn
	con_dung = [t for t in mau if isinstance(t, dict) and not js_dung(t.get("Inactive"))]
	chon = next((t for t in con_dung if t.get("IsPublished") is not False), con_dung[0] if con_dung else None)
	try:
		with _sach_message_log():
			d = frappe.get_single(TEN_CAU_HINH)
			for k, truong in (("companyId", "misa_company_id"), ("orgUnitId", "misa_org_unit_id"), ("userId", "misa_user_id")):
				if ids[k]:
					d.set(truong, ids[k])
			if ids["isInvoiceWithCode"] is not None:
				d.misa_is_invoice_with_code = 1 if ids["isInvoiceWithCode"] else 0
				d.duong_phat_hanh = "/v3sainvoice/Code" if ch.co_ma else "/v3sainvoice"
			if chon:
				# khoá VẮNG (undefined — JSON.stringify bỏ) ⇒ giữ giá trị cũ; khoá có mà null ⇒ ghi trống [Soát thiếu 2]
				if "IPTemplateID" in chon:
					d.misa_template_id = _chu(chon["IPTemplateID"])
				if "InvSeries" in chon:
					d.misa_inv_series = _chu(chon["InvSeries"])
				d.misa_inv_template_no = _chu(chon.get("InvTemplateNo")) if js_dung(chon.get("InvTemplateNo")) else "1"
				d.loai_hd = cint(chon.get("InvoiceType")) if js_dung(chon.get("InvoiceType")) else 1
				d.ke_thua_mau_cu = 1 if js_dung(chon.get("IsInheritFromOldTemplate")) else 0
			if tai_khoan_secret and js_trim(tai_khoan_secret):
				d.tai_khoan = js_trim(tai_khoan_secret)
			if password_go and js_trim(password_go):
				d.mat_khau = js_trim(password_go)
			d.save(ignore_permissions=True)  # `modified` luôn đổi (nppsale `updated_at`)
	except Exception as e:  # [ĐX H13] nppsale console.error rồi vẫn 200
		_ghi_loi("HĐĐT MISA: thử kết nối — lưu cấu hình lỗi")
		return _loi(500, CAU_TK_CHUA_LUU_DUOC.format(msg=str(e)))
	tom_tat = {k: chon[k] for k in ("IPTemplateID", "TemplateName", "InvSeries", "InvTemplateNo", "InvoiceType") if k in chon} if chon else None
	ket_qua = {"success": True, "tenant": ids, "template": tom_tat, "template_count": len(con_dung), "template_error": loi_mau}
	# nhật ký: KHÔNG thân /oauth (có token), KHÔNG thân lấy mẫu (có mật khẩu) — chỉ tóm tắt
	_ghi_nhat_ky_an_toan("test_connection", "success", nhan_ve={"tenant": ids, "template": tom_tat, "template_count": len(con_dung),
		"template_error": loi_mau})
	return 200, ket_qua


# ------------------------------------------------------------------------------------------------ §4.6 đối soát tay
@tuyen("POST", r"^/api/einvoice/reconcile-action$")
def doi_soat(yc: YeuCauCu):
	"""POST /api/einvoice/reconcile-action `{action: link | unlink | create, snapshotId, invoiceId?}` (`reconcile-action/route.ts:42–351`, §4.6).
	Mọi thao tác đặt `cach_khop = manual` (vòng khớp tự động bỏ qua — người chốt rồi máy không sửa lại); mỗi thao tác một nhật ký `reconcile`."""
	try:
		return _doi_soat(yc)
	except Exception as e:
		return _bao_loi_route("đối soát", e, CAU_TK_KHONG_XAC_DINH)


def _doi_soat(yc: YeuCauCu) -> tuple:
	b = _than(yc)
	snap_id = _ma(b.get("snapshotId"))
	if not snap_id:
		return _loi(400, CAU_DS_THIEU_SNAP)
	if hien_tai().vai not in VAI_PHAT_HANH:
		return _loi(403, CAU_KHONG_QUYEN)
	sn = frappe.db.get_value("NPP MISA Snapshot", snap_id, ["name", "ref_id", "ky_hieu", "so_hddt", "ngay_phat_hanh", "nguoi_mua",
		"mst_nguoi_mua", "hddt"], as_dict=True)  # id không phải uuid → không có → 404 (nppsale 500 "invalid input syntax for type uuid" [≠])
	if not sn:
		return _loi(404, CAU_DS_KHONG_CO_SNAP)
	hanh_dong = b.get("action")
	if hanh_dong == "unlink":
		ma, kq, lien_quan = _go_noi(sn)
	elif hanh_dong == "link":
		ma, kq, lien_quan = _noi_tay(sn, _ma(b.get("invoiceId")))
	elif hanh_dong == "create":
		ma, kq, lien_quan = _dung_tu_snapshot(sn)
	else:
		return _loi(400, CAU_DS_ACTION)
	if lien_quan and not frappe.db.exists("NPP HDDT", lien_quan):
		lien_quan = None
	_ghi_nhat_ky_an_toan("reconcile", "success" if ma == 200 else "failed", hddt=lien_quan,
		gui_di={"action": hanh_dong, "snapshotId": b.get("snapshotId"), "invoiceId": b.get("invoiceId")}, nhan_ve=kq,
		loi=kq.get("error") if isinstance(kq, dict) else None)
	return ma, kq


def _go_noi(sn) -> tuple:
	"""unlink: trả dòng về cho vòng khớp tự động (lượt kéo sau khớp lại)."""
	frappe.db.set_value("NPP MISA Snapshot", sn.name, {"hddt": None, "cach_khop": None, "do_tin": None, "ket_qua_khop": None,
		"ghi_chu_khop": None, "khop_luc": None})
	return 200, {"success": True, "action": "unlink"}, sn.hddt


def _noi_tay(sn, ten_hd: str) -> tuple:
	"""link: tờ phải có trong sổ; tờ đã bị snapshot KHÁC chiếm → 409 (hai HĐĐT MISA cho một lần bán là kê hai lần; ≥ 2 dòng chiếm vẫn 409 —
	nppsale `.maybeSingle()` lỗi → 500 [≠ nhỏ]); số / ký hiệu sổ khác MISA → cảnh báo, không chặn. Không xét `da_huy` / `quan_he` (nối tay đè được
	cancelled / replaced) [=]; KHÔNG ghi NPP HDDT. Khoá dòng HĐĐT rồi đọc CÓ KHOÁ snapshot chiếm (hai lượt nối song song vào một tờ xếp hàng; đọc
	thường theo ảnh chụp REPEATABLE READ có thể không thấy lượt kia vừa commit)."""
	if not ten_hd:
		return 400, {"error": CAU_THIEU_ID}, None
	h = frappe.db.sql("SELECT `name`, `misa_inv_no`, `misa_inv_series` FROM `tabNPP HDDT` WHERE `name` = %s FOR UPDATE", ten_hd, as_dict=True)
	if not h:
		return 404, {"error": CAU_DS_KHONG_CO_HD}, None
	h = h[0]
	chiem = frappe.db.sql("""SELECT `name`, `ky_hieu`, `so_hddt` FROM `tabNPP MISA Snapshot` WHERE `hddt` = %s AND `name` <> %s
		ORDER BY `creation`, `name` LIMIT 1 LOCK IN SHARE MODE""", (h.name, sn.name), as_dict=True)
	if chiem:
		return 409, {"error": CAU_DS_BI_CHIEM.format(ky_hieu=chiem[0].ky_hieu or "?", so=chiem[0].so_hddt or "?")}, h.name
	canh_bao, ket_qua, ghi_chu = canh_bao_noi_tay(h.misa_inv_no, h.misa_inv_series, sn.so_hddt, sn.ky_hieu)
	frappe.db.set_value("NPP MISA Snapshot", sn.name, {"hddt": h.name, "cach_khop": "manual", "do_tin": "certain", "ket_qua_khop": ket_qua,
		"ghi_chu_khop": ghi_chu, "khop_luc": bay_gio()})
	return 200, {"success": True, "action": "link", "warnings": canh_bao}, h.name


def _dung_tu_snapshot(sn) -> tuple:
	"""create: dựng dòng NPP HDDT từ snapshot "chỉ có trên MISA" — số tiền lấy từ endpoint CHI TIẾT (danh sách không tách thuế; thiếu thì DỪNG);
	không gắn đơn / HĐ bán (máy không biết tờ phát hành thẳng trên MISA thuộc đơn nào); kỳ ghi nhận = ngày phát hành trên MISA. MỘT giao dịch (dòng
	mới + snapshot) — không còn ca "Đã dựng hoá đơn nhưng chưa cập nhật được dòng đối soát" của nppsale. Gọi MISA KHÔNG giữ khoá; khoá snapshot
	`FOR UPDATE` + đọc lại sau đó (hai lượt bấm song song: lượt sau 409). [ĐX H9] chi tiết còn `<Chưa cấp số>` ⇒ số NULL (trạng thái suy ra `sent`).
	[ĐX H26] ngày không có thật ⇒ không ghi ngày (kỳ = hôm nay) + ghi chú. Không gọi `danh_dau_goc` [=]."""
	if sn.hddt:
		return 409, {"error": CAU_DS_DA_NOI}, sn.hddt
	ref = js_trim(sn.ref_id or "")
	if not ref:
		return 400, {"error": CAU_DS_KHONG_REFID}, None
	try:
		ch = MM.lay_cau_hinh()  # không xét `dang_dung`
	except MM.LoiCauHinh as e:  # [Sửa cuối — phát hiện 6] địa chỉ / đường MISA không hợp lệ: không giải mã, không gọi
		return 400, {"error": str(e)}, None
	except Exception as e:
		return 500, {"error": CAU_DOC_CAU_HINH.format(msg=str(e))}, None
	if ch is None:
		return 400, {"error": CAU_CHUA_CAU_HINH}, None
	try:
		ch.giai_ma()
	except MM.LoiGiaiMa as e:
		return 500, {"error": CAU_DS_GIAI_MA.format(msg=e.ly_do)}, None
	try:
		raw = MM.lay_hd(ch, ref)
	except MM.MisaLoi as e:
		return 502, {"error": CAU_DS_GOI_MISA.format(msg=str(e))}, None
	if raw is None:
		return 502, {"error": CAU_DS_MISA_RONG}, None
	bg = doc_ban_ghi(raw)
	if bg["total_amount"] is None:
		return 502, {"error": CAU_DS_THIEU_TONG}, None
	st, rel, note = suy_trang_thai(bg, ch.co_ma, None)
	ghi_chu = [GHI_CHU_DUNG + (f" {note}" if note else "")]
	if bg["inv_date"]:  # MISA có InvDate: chuỗi lạ ⇒ không lùi về ngày của snapshot [=]
		ngay = ngay_iso(bg["inv_date"])
		if ngay and not ngay_that(ngay):  # [ĐX H26]
			from nppsale.luat.hddt import ghi_chu_ngay_khong_that

			ghi_chu.append(ghi_chu_ngay_khong_that(bg["inv_date"]))
			ngay = None
	else:
		ngay = sn.ngay_phat_hanh.isoformat() if sn.ngay_phat_hanh else None
	so = None if la_so_cho(bg["inv_no"]) else bg["inv_no"]
	tho = raw if isinstance(raw, dict) else {}

	def chu(k):
		v = tho.get(k)
		return v if isinstance(v, str) and v else None

	luc = bay_gio()
	diem = "npp_misa_dung"
	frappe.db.savepoint(diem)
	try:
		lai = frappe.db.sql("SELECT `hddt` FROM `tabNPP MISA Snapshot` WHERE `name` = %s FOR UPDATE", sn.name)
		if not lai:
			return 404, {"error": CAU_DS_KHONG_CO_SNAP}, None
		if lai[0][0]:
			return 409, {"error": CAU_DS_DA_NOI}, lai[0][0]
		if frappe.db.sql("SELECT 1 FROM `tabNPP HDDT` WHERE `misa_ref_id` = %s LIMIT 1 LOCK IN SHARE MODE", ref):
			return 409, {"error": CAU_DS_TRUNG_REFID}, None
		ky_hieu = bg["inv_series"] or ("" if so else None)
		if so and frappe.db.sql("""SELECT 1 FROM `tabNPP HDDT` WHERE `misa_inv_series` = %s AND `misa_inv_no` = %s LIMIT 1
				LOCK IN SHARE MODE""", (ky_hieu, so)):
			return 409, {"error": CAU_DS_TRUNG_SO.format(ky_hieu=so_js(sn.ky_hieu), so=so_js(sn.so_hddt))}, None
		d = frappe.get_doc({
			"doctype": "NPP HDDT", "trang_thai": "issued",
			"so_hd_go_tay": so or (None if la_so_cho(sn.so_hddt) else sn.so_hddt),
			"nguoi_mua": chu("AccountObjectName") or sn.nguoi_mua or "Khách lẻ", "dia_chi_nguoi_mua": chu("AccountObjectAddress"),
			"mst_nguoi_mua": chu("AccountObjectTaxCode") or sn.mst_nguoi_mua or None,
			"tien_hang": bg["total_without_vat"] if bg["total_without_vat"] is not None else 0,
			"tien_thue": bg["total_vat"] if bg["total_vat"] is not None else 0, "tong_tien": bg["total_amount"],
			"phat_hanh_luc": f"{ngay} 00:00:00" if ngay else luc, "misa_ref_id": ref, "misa_inv_no": so, "misa_inv_series": ky_hieu,
			"misa_inv_date": ngay, "misa_invoice_code": bg["invoice_code"], "misa_lookup_code": bg["transaction_id"], "misa_relation": rel or "",
			"misa_org_ref_id": bg["org_ref_id"], "misa_status": st or "signed", "misa_last_checked_at": luc, "misa_note": "\n".join(ghi_chu),
		})
		with _sach_message_log():
			d.insert(ignore_permissions=True)
		frappe.db.set_value("NPP MISA Snapshot", sn.name, {"hddt": d.name, "cach_khop": "manual", "do_tin": "certain", "ket_qua_khop": "matched",
			"ghi_chu_khop": GHI_CHU_KHOP_DUNG, "khop_luc": luc})
	except Exception as e:
		_lui(diem)
		goc = e.__cause__ or e.__context__ or e
		if _la_trung_khoa(e) or _la_trung_khoa(goc) or isinstance(e, frappe.UniqueValidationError):
			if "misa_ref_id" in f"{e} {goc}":
				return 409, {"error": CAU_DS_TRUNG_REFID}, None
			return 409, {"error": CAU_DS_TRUNG_SO.format(ky_hieu=so_js(sn.ky_hieu), so=so_js(sn.so_hddt))}, None
		raise
	return 200, {"success": True, "action": "create", "invoice_id": d.name}, d.name
