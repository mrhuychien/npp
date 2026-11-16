"""Hoá đơn điện tử MISA meInvoice — phía máy chủ của `/api/einvoice/*` (đặc tả `dac_ta_hddt.md` §4; blueprint 02 §4.6.9).

Tệp chia ba phần (route thêm ở bước sau vào CÙNG tệp — giữ thứ tự để đọc từ trên xuống):
  1. PHẦN DÙNG CHUNG — vai theo route nppsale, câu lỗi nguyên văn, giờ / commit, đọc HĐ bán. Route, cổng `invoices`
     (`nppsale/cong/bang/hddt.py`) và việc nền (`nppsale/lich/misa.py`) cùng dùng — đừng chép lại ở chỗ khác.
  2. LẬP DÒNG — `dam_bao_dong` (§4.2): thay phần `ensureEInvoiceRow` (`src/lib/einvoice/publish.ts:51–93`) phía máy chủ. Trình duyệt vẫn gọi
     `ensureEInvoiceRow` nguyên văn → cổng `invoices` INSERT → bộ ghi gọi hàm này (không phủ giao diện — §9.3-9).
  3. ROUTE `@tuyen(...)` (bước sau): `phat_hanh` (§4.1), `lam_moi` (§4.3), `cau_hinh_doc` / `cau_hinh_luu` (§4.4), `thu_ket_noi` (§4.5),
     `doi_soat` (§4.6) — nhớ thêm `"nppsale.api.misa"` vào `_nap()` của `nppsale/api/tuyen.py` (§6.2; thiếu là 501).

Không whitelist hàm nào ở đây: route đi qua `nppsale.api.tuyen.goi`; `chan_cua_chung` (`portal/chan.py`) để NV NPP tới được mọi method
`nppsale.*` có whitelist — whitelist thêm thì phải kiểm vai TRONG hàm (§4.0).
"""
from __future__ import annotations

import frappe
from frappe.utils import flt, now_datetime

from nppsale.cong.bang._chung import co_cot, tu_choi
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.sql import LoiCong

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
# 3. ROUTE /api/einvoice/* — thêm ở bước sau (§4.1–§4.6), mỗi route một hàm `@tuyen("POST", r"^/api/einvoice/<…>$")`.
# ============================================================================================================================
