"""Bảng HOÁ ĐƠN ĐIỆN TỬ MISA của nppsale trên cổng (đặc tả `dac_ta_hddt.md` §7; blueprint 02 §6.1 dòng `invoices` /
`company_einvoice_config` / `einvoice_logs` / `misa_invoice_snapshots`). Cột đúng `\\d` của bốn bảng trên Postgres tham chiếu (cùng thứ tự —
`select('*')` ra đúng bộ cột nppsale); cột chuỗi / Select bọc `NULLIF(…, '')` (Frappe lưu được cả `''` lẫn NULL — thiếu là chip "Chờ gửi"
`.or('misa_status.is.null,misa_status.eq.pending')` đếm sót dòng lưu `''`). Cột Link kiểu `uuid` (`hddt` của Log / Snapshot) không bọc: cột
`uuid` không chứa được `''`, và so `uuid` với `''` sinh cảnh báo 1292 cho từng dòng.

- invoices ← NPP HDDT (HĐĐT MISA — tên cũ của mig 001, KHÔNG phải HĐ bán). Đọc (chép RLS mig 084): chủ / QL / KT mọi dòng; NVBH dòng có
  `don_hang` của đơn mình đứng tên (`Sales Order.npp_nhan_vien`); kho / người khác 0 dòng. `misa_ref_id` = NULL khi `misa_status` trống / `error`
  [ĐX H3b — RefID ghi TRƯỚC khi gửi; tờ chưa chắc tới MISA vẫn hiện "Đẩy lại lên MISA" ở `/invoices/[id]` như cũ]. Thứ tự mặc định (yêu cầu
  không `order`) `created_at ↑, id ↑` (KV-56: danh sách đơn dựng `invMap[order_id]` theo thứ tự trả về — dòng về sau thắng, dòng mới lập của tờ
  `HD-…-n` sau Sửa HĐ phải thắng dòng của tờ cũ đã huỷ). Ghi: `GhiHddt` (dưới).
- company_einvoice_config ← Single NPP MISA Cau Hinh: 0 dòng khi chưa lưu ("đã lưu" = có dòng `tabSingles` của `nha_cung_cap` — cùng luật
  `npp_misa_cau_hinh.da_luu`); `username_enc` / `password_enc` luôn NULL (nppsale để QL đọc được chữ mã — không chép; has_username /
  has_password chỉ ở route GET /api/einvoice/config). Đọc chủ / KT / QL. Ghi cấm (42501) — lưu qua route cấu hình.
- misa_invoice_snapshots ← NPP MISA Snapshot: `publish_status` / `einvoice_status` lưu Data → `CASE … REGEXP '^-?[0-9]+$'` (MariaDB
  `CAST('3.5' AS SIGNED)` = 3 — đọc thành "đã cấp mã"; KV-57); `total_amount` NULL khi MISA không trả (`co_tong_tien`). Đọc chủ / KT / QL. Ghi cấm
  (nppsale cho chủ / KT / QL ghi thẳng — siết theo blueprint: kéo + khớp là việc nền, nối / gỡ / dựng qua route đối soát).
- einvoice_logs ← NPP MISA Log: `request_payload` / `response_payload` là JSON (payload phát hành là MẢNG). Đọc chủ / KT / QL. Ghi cấm (nppsale
  cho QL sửa / xoá nhật ký — không chép lỗ ấy).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import frappe

from ..dang_ky import Bang, CotDef, NguCanh, QuanHe, dang_ky
from ..loi import NppLoi
from ..sql import LoiCong
from ._chung import VAI_VAN_PHONG, c, co_cot, gio_vao, kiem_org, la_nv, org, pivot_single, tu_choi

BANG = "invoices"
TRANG_THAI = ("draft", "issued", "cancelled")
# Chuyển trạng thái nội bộ người được làm (đặc tả §1.3.1): draft → issued ("Khoá hoá đơn"), draft → cancelled, issued → cancelled. Ngược lại
# (cancelled → draft, issued → draft, cancelled → issued) bỏ qua dòng — 0 dòng như RLS lọc; chỉ phát hành OK mới đưa cancelled → issued.
CHUYEN_DUOC = {("draft", "issued"), ("draft", "cancelled"), ("issued", "cancelled")}
# Cột người mua / tiền / số gõ tay: cột cổng → trường NPP HDDT (sửa theo luật H24 — `npp_hddt.sua_duoc_nguoi_mua_tien`)
NGUOI_MUA_TIEN = {"customer_name": "nguoi_mua", "customer_address": "dia_chi_nguoi_mua", "customer_tax_code": "mst_nguoi_mua",
	"subtotal": "tien_hang", "vat": "tien_thue", "total": "tong_tien", "invoice_number": "so_hd_go_tay"}
COT_TIEN = ("subtotal", "vat", "total")
# `id` / `created_at` / `issued_at` (khi thêm) / `status` (khi thêm): nhận rồi bỏ qua như GhiDocType (id do UUID, created_at = creation, tờ mới luôn nháp)
GOI_Y_MISA = "Cột misa_* chỉ đổi qua /api/einvoice/* (phát hành, làm mới, đối soát)."
GOI_Y_TIM = "tim_kd do máy chủ tính (khoa_tim_ds — mig 249)."
GOI_Y_GAN = "Đơn / hoá đơn bán của HĐĐT chỉ gắn lúc lập dòng (dam_bao_dong)."


def _n(truong: str) -> CotDef:
	return c("NULLIF({t}.`" + truong + "`, '')")


# ------------------------------------------------------------------------------------------------ RLS
def ve_hddt(nc: NguCanh):
	"""invoices SELECT (mig 084): "Admin roles can view all invoices" (chủ / QL / KT) + "Sales see own invoices" (NVBH: `order_id` có ∧ đơn có
	`sales_user_id` = mình — EXISTS trên sales_orders). Dòng lưu trữ (P8): `don_hang_ls` của đơn lưu trữ đứng tên mình. Kho / vai khác 0 dòng."""
	if nc.bo_qua_rls:
		return None
	if not la_nv(nc):
		return False
	if nc.vai in VAI_VAN_PHONG:
		return None
	if nc.vai == "sales":
		ve = "{t}.`don_hang` IN (SELECT so.`name` FROM `tabSales Order` so WHERE so.`npp_nhan_vien` = %(u)s)"
		if co_cot("NPP HDDT", "don_hang_ls") and frappe.db.exists("DocType", "NPP LS Don Hang"):
			ve = (f"({ve} OR {{t}}.`don_hang_ls` IN (SELECT ls.`name` FROM `tabNPP LS Don Hang` ls WHERE ls.`sales_user_id` = %(u)s))")
		return (ve, {"u": nc.user})
	return False


def ve_van_phong(nc: NguCanh):
	"""company_einvoice_config / einvoice_logs / misa_invoice_snapshots SELECT (mig 072 / 100): chủ / KT / QL; vai khác 0 dòng (không lỗi)."""
	if nc.bo_qua_rls:
		return None
	return None if nc.vai in VAI_VAN_PHONG else False


# ------------------------------------------------------------------------------------------------ ghi invoices
def _cam(cot: str, goi_y: str):
	"""Cột không ghi thẳng được: 42501 như thiếu quyền cột của Postgres (trước vế RLS dòng) — `errorMessage` của giao diện dịch theo mã."""
	raise NppLoi(f'new row violates row-level security policy for table "{BANG}"', code="42501", http=403, goi_y=goi_y)


def _so_tien(v):
	"""Số tiền trình duyệt gửi → số; chữ không phải số → 22P02 như cột numeric của Postgres (flt() của Frappe lặng lẽ đổi thành 0)."""
	if v is None:
		return None
	if isinstance(v, bool):
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{str(v).lower()}"')
	try:
		return float(Decimal(str(v).strip()))
	except (InvalidOperation, ValueError):
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{v}"') from None


class GhiHddt:
	"""Bộ ghi `invoices` (đặc tả §7.1 Ghi). Không dùng GhiDocType vì vai được thêm khác theo nhánh và mọi luật đọc trạng thái dòng CÓ KHOÁ.

	INSERT (từng giá trị; `misa_*` / `tim_kd` → 42501, cột lạ → PGRST204, `org_id` khác site → 42501):
	  (i)   có `sales_invoice_id` → vai chủ / KT / QL (H1) → `nppsale.api.misa.dam_bao_dong(HĐ, nc, so_hd_go_tay=invoice_number)`: trả dòng sẵn có
	        nếu đã có (insert idempotent — `invoice_number` gửi kèm KHÔNG ghi đè số của dòng ấy), người mua + tiền lấy từ HĐ bán (bỏ số gửi lên).
	  (ii)  không HĐ mà có `order_id` (danh sách đơn "Xuất hoá đơn", màn Tạo HĐĐT chọn đơn) — H1: HĐ ghi sổ của đơn: 0 → P0001 "Đơn chưa có hóa
	        đơn bán nào…"; > 1 → P0001 "Đơn có {n} hóa đơn bán…"; 1 → như (i).
	  (iii) không gì → tờ tay: vai chủ / KT; người mua, ba số tiền, số gõ tay như gửi; `trang_thai` luôn draft (bỏ `status` khác).
	UPDATE (vai chủ / KT; dòng không thoả luật bị BỎ QUA = 0 dòng — giao diện báo "Database từ chối…" của must-write.ts):
	  người mua / tiền / `invoice_number` chỉ khi dòng `draft` ∧ `misa_status` trống / `error` (H24); `customer_name` sau strip rỗng → 23502 (validate
	  của NPP HDDT); `status` theo CHUYEN_DUOC (giá trị ngoài ba trạng thái → 23514 `invoices_status_check`); `issued_at` chỉ đi kèm draft → issued
	  (→ `phat_hanh_luc`); `order_id` / `sales_invoice_id` / `misa_*` / `tim_kd` → 42501. Đọc dòng bằng `get_doc(for_update=True)`: bản ĐÃ COMMIT MỚI
	  NHẤT + khoá dòng — `save()` ghi lại MỌI trường, đọc theo ảnh chụp cũ là đè mất `misa_status` / `misa_ref_id` mà bước giành tờ của phát hành
	  vừa ghi bằng câu SQL (không đổi `modified` nên check_if_latest của lõi không bắt được).
	DELETE (vai chủ / KT): chỉ `draft` chưa có RefID; `draft` có RefID (tờ đã gửi / lỗi sau khi gửi) → P0001 "Chỉ xoá được hoá đơn điện tử nháp
	  chưa gửi MISA." (H24 — thay vì 0 dòng); `issued` / `cancelled` → 0 dòng. `on_trash` của NPP HDDT gỡ `hddt` ở Log / Snapshot.
	UPSERT: không khai `them_hoac_sua` → 42501 (cong/ghi.py)."""

	def __init__(self, bang: Bang):
		self.bang = bang

	def _kiem_cot(self, gt: dict, *, them: bool) -> None:
		for k in gt:
			if k not in self.bang.cot:
				raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{BANG}' in the schema cache", http=400)
		for k in gt:
			if k.startswith("misa_"):
				_cam(k, GOI_Y_MISA)
			if k == "tim_kd":
				_cam(k, GOI_Y_TIM)
			if not them and k in ("order_id", "sales_invoice_id"):
				_cam(k, GOI_Y_GAN)

	# --------------------------------------------------------------------------------------------------------------- INSERT
	def them(self, ds, nc):
		from nppsale.api.misa import (
			CAU_DON_CHUA_XUAT,
			CAU_DON_NHIEU_HD,
			VAI_GHI_TAY,
			VAI_PHAT_HANH,
			dam_bao_dong,
			hd_ban_cua_don,
		)

		ra = []
		for g in ds:
			g = g or {}
			self._kiem_cot(g, them=True)
			kiem_org(g, BANG)
			hd, don = g.get("sales_invoice_id"), g.get("order_id")
			if hd or don:  # (i) / (ii) — H1
				if not nc.bo_qua_rls and nc.vai not in VAI_PHAT_HANH:
					tu_choi(BANG)
				if not hd:
					ds_hd = hd_ban_cua_don(don)
					if not ds_hd:
						raise LoiCong("P0001", CAU_DON_CHUA_XUAT, http=400)
					if len(ds_hd) > 1:
						raise LoiCong("P0001", CAU_DON_NHIEU_HD.format(n=len(ds_hd)), http=400)
					hd = ds_hd[0]
				ra.append(dam_bao_dong(hd, nc, so_hd_go_tay=g.get("invoice_number")))
				continue
			if not nc.bo_qua_rls and nc.vai not in VAI_GHI_TAY:  # (iii) tờ tay — RLS "Owner/Accountant can manage invoices"
				tu_choi(BANG)
			d = frappe.get_doc({"doctype": "NPP HDDT", "trang_thai": "draft", "so_hd_go_tay": g.get("invoice_number"),
				"nguoi_mua": g.get("customer_name"), "dia_chi_nguoi_mua": g.get("customer_address"),
				"mst_nguoi_mua": g.get("customer_tax_code"), **{NGUOI_MUA_TIEN[k]: _so_tien(g.get(k)) for k in COT_TIEN}})
			d.insert(ignore_permissions=True)
			ra.append(d.name)
		return ra

	# --------------------------------------------------------------------------------------------------------------- UPDATE
	def sua(self, gt, ids, nc):
		from nppsale.api.misa import VAI_GHI_TAY
		from nppsale.npp_hddt.doctype.npp_hddt.npp_hddt import sua_duoc_nguoi_mua_tien

		gt = gt or {}
		self._kiem_cot(gt, them=False)
		if not nc.bo_qua_rls and nc.vai not in VAI_GHI_TAY:  # sửa: RLS "Owner/Accountant can manage invoices"
			return []
		kiem_org(gt, BANG)
		if "status" in gt and gt["status"] not in TRANG_THAI:
			raise LoiCong("23514", f'new row for relation "{BANG}" violates check constraint "invoices_status_check"')
		nd = {NGUOI_MUA_TIEN[k]: (_so_tien(v) if k in COT_TIEN else v) for k, v in gt.items() if k in NGUOI_MUA_TIEN}
		ra = []
		for ten in ids:
			d = frappe.get_doc("NPP HDDT", ten, for_update=True)
			cu = d.trang_thai or ""
			moi = gt.get("status", cu)
			if nd and not sua_duoc_nguoi_mua_tien(cu, d.misa_status):
				continue  # H24: người mua / tiền / số gõ tay chỉ sửa khi nháp chưa tới MISA
			if moi != cu and (cu, moi) not in CHUYEN_DUOC:
				continue
			if "issued_at" in gt and not (cu == "draft" and moi == "issued"):
				continue  # mốc phát hành nội bộ (cửa sổ quét — H14) chỉ đặt lúc "Khoá hoá đơn"
			for truong, v in nd.items():
				d.set(truong, v)
			d.trang_thai = moi
			if "issued_at" in gt:
				d.phat_hanh_luc = gio_vao(gt["issued_at"])
			d.save(ignore_permissions=True)
			ra.append(ten)
		return ra

	# --------------------------------------------------------------------------------------------------------------- DELETE
	def xoa(self, ids, nc):
		from nppsale.api.misa import VAI_GHI_TAY
		from nppsale.npp_hddt.doctype.npp_hddt.npp_hddt import CAU_XOA, xoa_duoc

		if not nc.bo_qua_rls and nc.vai not in VAI_GHI_TAY:  # xoá: RLS như sửa (màn chỉ mở nút cho chủ)
			return []
		ra = []
		for ten in ids:
			r = frappe.db.sql("SELECT `trang_thai`, `misa_ref_id` FROM `tabNPP HDDT` WHERE `name` = %s FOR UPDATE", ten, as_dict=True)
			if not r or r[0].trang_thai != "draft":
				continue  # issued / cancelled → 0 dòng
			if not xoa_duoc(r[0].trang_thai, r[0].misa_ref_id):
				raise LoiCong("P0001", CAU_XOA, http=400)  # nháp đã có RefID (H24): nói rõ thay vì câu chung "Database từ chối…"
			frappe.delete_doc("NPP HDDT", ten, ignore_permissions=True)
			ra.append(ten)
		return ra


# ------------------------------------------------------------------------------------------------ đăng ký
def _cot_hddt(luu_tru: bool) -> dict:
	"""33 cột `invoices` theo thứ tự `\\d invoices`. Bản lưu trữ (P8 — `don_hang_ls` / `hoa_don_ban_ls`, cột `uuid`): ép về chữ trước khi
	COALESCE với cột varchar (COALESCE giữa varchar và `uuid` ra kiểu `uuid`, mã đơn / HĐ thật thành NULL kèm cảnh báo 1292 — blueprint §6.1)."""
	don, hd = "NULLIF({t}.`don_hang`, '')", "NULLIF({t}.`hoa_don_ban`, '')"
	if luu_tru:
		don = "COALESCE(" + don + ", CAST({t}.`don_hang_ls` AS CHAR(36)) COLLATE utf8mb4_unicode_ci)"
		hd = "COALESCE(" + hd + ", CAST({t}.`hoa_don_ban_ls` AS CHAR(36)) COLLATE utf8mb4_unicode_ci)"
	gio = lambda truong: c("{t}.`" + truong + "`", "gio")  # noqa: E731
	return {
		"id": c("{t}.`name`"), "org_id": org(), "order_id": c(don), "invoice_number": _n("so_hd_go_tay"), "customer_name": _n("nguoi_mua"),
		"customer_address": _n("dia_chi_nguoi_mua"), "customer_tax_code": _n("mst_nguoi_mua"), "subtotal": c("{t}.`tien_hang`", "tien"),
		"vat": c("{t}.`tien_thue`", "tien"), "total": c("{t}.`tong_tien`", "tien"), "status": _n("trang_thai"), "issued_at": gio("phat_hanh_luc"),
		"created_at": gio("creation"), "misa_invoice_id": _n("misa_invoice_id"), "misa_invoice_url": _n("misa_invoice_url"),
		"misa_status": _n("misa_status"), "misa_error": _n("misa_error"), "misa_sent_at": gio("misa_sent_at"),
		"misa_signed_at": gio("misa_signed_at"), "misa_lookup_code": _n("misa_lookup_code"), "misa_published_at": gio("misa_published_at"),
		# H3b: RefID ghi TRƯỚC khi gửi — tờ chưa chắc tới MISA (trống / error) đọc như chưa có RefID
		"misa_ref_id": c("CASE WHEN IFNULL({t}.`misa_status`, '') IN ('', 'error') THEN NULL ELSE NULLIF({t}.`misa_ref_id`, '') END"),
		"misa_inv_no": _n("misa_inv_no"), "misa_inv_series": _n("misa_inv_series"), "misa_inv_date": c("{t}.`misa_inv_date`", "ngay"),
		"misa_invoice_code": _n("misa_invoice_code"), "misa_relation": _n("misa_relation"), "misa_org_ref_id": _n("misa_org_ref_id"),
		"misa_last_checked_at": gio("misa_last_checked_at"), "misa_note": _n("misa_note"), "misa_no_locked": c("{t}.`misa_no_locked`", "bool"),
		"sales_invoice_id": c(hd), "tim_kd": _n("tim_kd"),
	}


# Single cấu hình → một dòng ảo; "đã lưu" = có dòng `nha_cung_cap` (gộp không GROUP BY luôn ra MỘT dòng NULL — HAVING cắt về 0 dòng).
_CAU_HINH = pivot_single("NPP MISA Cau Hinh", {
	"nha_cung_cap": "chuoi", "dia_chi_api": "chuoi", "mst_nguoi_ban": "chuoi", "ten_nguoi_ban": "chuoi", "dia_chi_nguoi_ban": "chuoi",
	"misa_company_id": "chuoi", "misa_org_unit_id": "chuoi", "misa_template_id": "chuoi", "misa_user_id": "chuoi", "misa_inv_series": "chuoi",
	"misa_inv_template_no": "chuoi", "moi_truong_thu": "bool", "dang_dung": "bool", "modified": "gio", "duong_lay_token": "chuoi",
	"duong_phat_hanh": "chuoi", "misa_app_id": "chuoi", "kieu_ky": "so", "loai_hd": "so", "ke_thua_mau_cu": "bool",
	"misa_is_invoice_with_code": "bool",
})
assert _CAU_HINH.endswith(")")
_CAU_HINH = _CAU_HINH[:-1] + " HAVING SUM(s.`field` = 'nha_cung_cap') > 0)"
_SO_NGUYEN = "CASE WHEN {t}.`{f}` REGEXP '^-?[0-9]+$' THEN CAST({t}.`{f}` AS SIGNED) END"  # KV-57: '3.5' / 'abc' / '' → NULL


def nap():
	if not co_cot("NPP HDDT", "misa_ref_id"):
		return
	luu_tru = co_cot("NPP HDDT", "hoa_don_ban_ls")
	hddt = Bang(
		ten=BANG,
		nguon="`tabNPP HDDT`",
		cot=_cot_hddt(luu_tru),
		quan_he=[
			QuanHe("sales_orders", "order_id", "id", False, ("invoices_order_id_fkey",)),
			QuanHe("sales_invoices", "sales_invoice_id", "id", False, ("invoices_sales_invoice_id_fkey",)),
			QuanHe("organizations", "org_id", "id", False, ("invoices_org_id_fkey",)),
			QuanHe("einvoice_logs", "id", "invoice_id", True, ("einvoice_logs_invoice_id_fkey",)),
			QuanHe("misa_invoice_snapshots", "id", "invoice_id", True, ("misa_invoice_snapshots_invoice_id_fkey",)),
		],
		rls=ve_hddt,
		thu_tu_mac_dinh=[{"cot": "created_at", "tang": True}, {"cot": "id", "tang": True}],
	)
	hddt.ghi = GhiHddt(hddt)
	dang_ky(hddt)

	dang_ky(Bang(
		ten="company_einvoice_config",
		nguon=_CAU_HINH,
		cot={
			"id": CotDef("'NPP MISA Cau Hinh'"), "org_id": org(), "provider": _n("nha_cung_cap"), "api_base": _n("dia_chi_api"),
			"tax_code": _n("mst_nguoi_ban"), "seller_name": _n("ten_nguoi_ban"), "seller_address": _n("dia_chi_nguoi_ban"),
			"misa_company_id": _n("misa_company_id"), "misa_org_unit_id": _n("misa_org_unit_id"), "misa_template_id": _n("misa_template_id"),
			"misa_user_id": _n("misa_user_id"), "misa_inv_series": _n("misa_inv_series"), "misa_inv_template_no": _n("misa_inv_template_no"),
			"username_enc": CotDef("NULL"), "password_enc": CotDef("NULL"),  # bí mật ở __Auth — không bao giờ trả (§1.7, I6)
			"sandbox": c("{t}.`moi_truong_thu`", "bool"), "is_active": c("{t}.`dang_dung`", "bool"), "created_at": CotDef("NULL", "gio"),
			"updated_at": c("{t}.`modified`", "gio"), "token_path": _n("duong_lay_token"), "publish_path": _n("duong_phat_hanh"),
			"misa_app_id": _n("misa_app_id"), "sign_type": c("{t}.`kieu_ky`", "so"), "invoice_type": c("{t}.`loai_hd`", "so"),
			"is_inherit_from_old_template": c("{t}.`ke_thua_mau_cu`", "bool"),
			"misa_is_invoice_with_code": c("{t}.`misa_is_invoice_with_code`", "bool"),
		},
		quan_he=[QuanHe("organizations", "org_id", "id", False, ("company_einvoice_config_org_id_fkey",))],
		rls=ve_van_phong,
	))

	dang_ky(Bang(
		ten="misa_invoice_snapshots",
		nguon="`tabNPP MISA Snapshot`",
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "ref_id": _n("ref_id"), "inv_series": _n("ky_hieu"), "inv_no": _n("so_hddt"),
			"inv_date": c("{t}.`ngay_phat_hanh`", "ngay"), "transaction_id": _n("ma_tra_cuu"), "invoice_code": _n("ma_cqt"),
			"buyer_tax_code": _n("mst_nguoi_mua"), "buyer_name": _n("nguoi_mua"),
			"total_amount": c("IF({t}.`co_tong_tien` = 1, {t}.`tong_tien`, NULL)", "tien"),  # MISA không trả TotalAmount → NULL (§1.2)
			"amount_before_vat": c("NULLIF({t}.`tien_truoc_thue`, 0)", "tien"), "vat_amount": c("NULLIF({t}.`tien_thue`, 0)", "tien"),
			"publish_status": c(_SO_NGUYEN.replace("{f}", "publish_status"), "so"),
			"einvoice_status": c(_SO_NGUYEN.replace("{f}", "einvoice_status"), "so"),
			"relation": _n("quan_he"), "is_deleted": c("{t}.`da_huy`", "bool"), "org_ref_id": _n("ref_id_goc"), "invoice_id": c("{t}.`hddt`"),
			"match_method": _n("cach_khop"), "match_confidence": _n("do_tin"), "match_status": _n("ket_qua_khop"),
			"match_note": _n("ghi_chu_khop"), "raw": c("{t}.`ban_ghi_tho`", "json"), "pulled_at": c("{t}.`keo_luc`", "gio"),
			"matched_at": c("{t}.`khop_luc`", "gio"), "created_at": c("{t}.`creation`", "gio"),
			# Postgres: cột GENERATED — inv_no_norm NULL khi inv_no NULL; inv_series_norm không bao giờ NULL ('' khi thiếu ký hiệu). Giá trị theo
			# hàm khớp (H21 — app không đọc hai cột này)
			"inv_no_norm": c("CASE WHEN NULLIF({t}.`so_hddt`, '') IS NULL THEN NULL ELSE {t}.`so_hddt_chuan` END"),
			"inv_series_norm": c("IFNULL({t}.`ky_hieu_chuan`, '')"),
		},
		quan_he=[
			QuanHe("invoices", "invoice_id", "id", False, ("misa_invoice_snapshots_invoice_id_fkey",)),
			QuanHe("organizations", "org_id", "id", False, ("misa_invoice_snapshots_org_id_fkey",)),
		],
		rls=ve_van_phong,
	))

	dang_ky(Bang(
		ten="einvoice_logs",
		nguon="`tabNPP MISA Log`",
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "invoice_id": c("{t}.`hddt`"), "order_id": _n("don_hang"),
			"attempt_at": c("{t}.`goi_luc`", "gio"), "request_payload": c("{t}.`gui_di`", "json"), "response_payload": c("{t}.`nhan_ve`", "json"),
			"status": _n("ket_qua"), "error_message": _n("loi"), "misa_lookup_code": _n("misa_lookup_code"), "misa_inv_no": _n("misa_inv_no"),
			"created_by": c("CASE WHEN {t}.`owner` IN ('Administrator', 'Guest') THEN NULL ELSE {t}.`owner` END"),  # việc nền → NULL như nppsale
			"created_at": c("{t}.`creation`", "gio"),
		},
		quan_he=[
			QuanHe("invoices", "invoice_id", "id", False, ("einvoice_logs_invoice_id_fkey",)),
			QuanHe("sales_orders", "order_id", "id", False, ("einvoice_logs_order_id_fkey",)),
			QuanHe("users", "created_by", "id", False, ("einvoice_logs_created_by_fkey",)),
			QuanHe("organizations", "org_id", "id", False, ("einvoice_logs_org_id_fkey",)),
		],
		rls=ve_van_phong,
	))


try:
	nap()
except Exception:  # noqa: BLE001 — nạp sổ ngoài request (không có DB) thì thôi
	pass
