"""Bảng MUA HÀNG + CÔNG NỢ NCC của nppsale trên cổng (P4 — đặc tả kho_mua §4.2, §4.4; blueprint 02 §5.9, §6.1):

- purchase_invoices ← Purchase Invoice `npp_loai = phieu_nhap` (mọi docstatus). `id` = `receipt_code` = `name` (`PN-0042`, tờ amend `PN-0042-1`; ⚠K câu 18:
  phiếu tạm cũng có số); `warehouse_zone` = kho người chọn `npp_kho_nhap` (trường mới M1 — lõi xoá `set_warehouse` khi các dòng khác kho);
  `status` = docstatus 0 → `draft` (nháp mang dấu huỷ `npp_huy_luc` → `cancelled` — §7.3 điểm 1), 1 → `completed`, 2 → `cancelled`;
  `subtotal` = `total` (Σ tiền dòng sau giảm dòng); `vat` = Σ dòng thuế TRỪ dòng giảm đầu phiếu (KHÔNG đọc `total_taxes_and_charges` — đã trừ khoản giảm,
  PoC 3); `total` = `grand_total`; `vat_override` = thuế gõ tay khi có cờ (NULL ≠ 0); `warehouse_zone` từ `set_warehouse`; `stock_entry_id` = chính tờ khi
  đã / thôi ghi sổ (⚠K §7.2 #14 — phiếu kho = PI); `payable_id` = dòng `NPP Cong No NCC` của tờ (huỷ → không còn dòng → NULL); `created_by` /
  `created_at` của tờ GỐC chuỗi amend (nppsale: khôi phục / sửa giữ người lập + lúc lập); `po_id` luôn NULL (đơn mua không port).
  RLS (mig 034 / 163 `FOR ALL`): đọc bốn vai mua hàng (owner / manager / accountant / warehouse), NVBH 0 dòng.
- purchase_invoice_lines ← Purchase Invoice Item của các tờ trên: `unit_price` = `price_list_rate` (giá trước giảm dòng), `line_discount` = `npp_giam_dong`
  (TIỀN cả dòng), `vat_rate` = `npp_thue_suat` (tỉ lệ), `line_total` = max(0, SL × giá − giảm) × (1 + thuế) (như trình duyệt ghi — `lineTotalOf`),
  `sort_order` = `idx`.
  Ghi (cả hai bảng): phiếu TẠM qua `nppsale.rpc.phieu_nhap` (them_phieu / sua_phieu / xoa_phieu, them_dong / sua_dong / xoa_dong) — trạng thái / tờ đã ghi
  sổ → `USE_RPC` (BP §6.1 siết; nppsale RLS cho ghi mọi cột).
- payables ← `NPP Cong No NCC` (bản chiếu từ sổ — `nppsale.su_kien.cong_no_ncc`, §2.8): `amount` = `so_tien`, `paid` = `da_tra`, `created_at` = `tao_luc`
  (ngày ghi nợ), `opening_balance` = (`loai = dau_ky`), `stock_entry_id` = `phieu_kho`. RLS (mig 034): owner / manager / accountant; thủ kho / NVBH 0 dòng.
  M1 chỉ ĐỌC — ghi (nợ đầu kỳ `DKN-` / lập tay `NTN-`, sửa hạn / ghi chú / quá hạn, xoá) dựng ở M3; tới lúc ấy ghi bị từ chối như RLS.
"""
from __future__ import annotations

from ..dang_ky import Bang, CotDef, NguCanh, QuanHe, dang_ky
from ._chung import c, co_cot, org
from .kho import KHO

VAI_MUA = ("owner", "manager", "accountant", "warehouse")
VAI_NO = ("owner", "manager", "accountant")
NGUON_PN = "(SELECT * FROM `tabPurchase Invoice` WHERE `npp_loai` = 'phieu_nhap')"
TK_GIAM = "(SELECT s.`value` FROM `tabSingles` s WHERE s.`doctype` = 'NPP Cai Dat' AND s.`field` = 'tk_giam_dau_phieu_nhap')"
# tờ GỐC của chuỗi amend: `PN-0042-1` → `PN-0042` (dãy `PN-.####` không có gạch nối khác)
GOC = "SUBSTRING_INDEX({t}.`name`, '-', 2)"


def _rls_mua(nc: NguCanh):
	if nc.bo_qua_rls or nc.vai in VAI_MUA:
		return None
	return False


def _rls_no(nc: NguCanh):
	if nc.bo_qua_rls or nc.vai in VAI_NO:
		return None
	return False


class GhiPhieuNhap:
	"""purchase_invoices: phiếu tạm — nppsale.rpc.phieu_nhap."""

	def them(self, ds, nc):
		from nppsale.rpc.phieu_nhap import them_phieu

		return them_phieu(ds, nc)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.phieu_nhap import sua_phieu

		return sua_phieu(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.phieu_nhap import xoa_phieu

		return xoa_phieu(ids, nc)


class GhiDongPhieuNhap:
	"""purchase_invoice_lines: dòng của phiếu tạm — nppsale.rpc.phieu_nhap."""

	def them(self, ds, nc):
		from nppsale.rpc.phieu_nhap import them_dong

		return them_dong(ds, nc)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.phieu_nhap import sua_dong

		return sua_dong(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.phieu_nhap import xoa_dong

		return xoa_dong(ids, nc)


def nap():
	if not co_cot("Purchase Invoice", "npp_loai"):
		return
	nguoi_lap = f"(SELECT g.`owner` FROM `tabPurchase Invoice` g WHERE g.`name` = {GOC})"
	dang_ky(Bang(
		ten="purchase_invoices",
		nguon=NGUON_PN,
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "po_id": CotDef("NULL"), "supplier_id": c("supplier"), "invoice_number": c("bill_no"),
			"invoice_date": c("bill_date", "ngay"), "subtotal": c("COALESCE({t}.`total`, 0)", "tien"),
			"vat": c("(SELECT COALESCE(SUM(CASE WHEN x.`add_deduct_tax` = 'Deduct' THEN -x.`tax_amount` ELSE x.`tax_amount` END), 0) "
				"FROM `tabPurchase Taxes and Charges` x WHERE x.`parent` = {t}.`name` AND x.`parenttype` = 'Purchase Invoice' "
				f"AND x.`account_head` <> IFNULL({TK_GIAM}, ''))", "tien"),
			"total": c("COALESCE({t}.`grand_total`, 0)", "tien"),
			"status": c("CASE WHEN {t}.`docstatus` = 1 THEN 'completed' WHEN {t}.`docstatus` = 2 OR {t}.`npp_huy_luc` IS NOT NULL "
				"THEN 'cancelled' ELSE 'draft' END"),
			"payable_id": c("(SELECT n.`name` FROM `tabNPP Cong No NCC` n WHERE n.`chung_tu` = {t}.`name` LIMIT 1)"),
			"notes": c("npp_ghi_chu"),
			"created_at": c(f"(SELECT g.`creation` FROM `tabPurchase Invoice` g WHERE g.`name` = {GOC})", "gio"),
			"created_by": c(f"CASE WHEN {nguoi_lap} IN ('Administrator', 'Guest') THEN NULL ELSE {nguoi_lap} END"),
			"completed_at": c("npp_hoan_thanh_luc", "gio"),
			"stock_entry_id": c("CASE WHEN {t}.`docstatus` IN (1, 2) THEN {t}.`name` END"),
			"receipt_code": c("{t}.`name`"), "discount": c("npp_giam_dau_phieu", "tien"),
			# kho người chọn: `npp_kho_nhap` (lõi xoá `set_warehouse` khi các dòng khác kho — dòng hạn ngắn vào kho cận date)
			"warehouse_zone": c(f"(SELECT z.`vung` FROM {KHO} z WHERE z.`kho` = COALESCE(NULLIF({{t}}.`npp_kho_nhap`, ''), {{t}}.`set_warehouse`) "
				"LIMIT 1)"),
			"cancelled_at": c("npp_huy_luc", "gio"), "cancelled_by": c("npp_huy_boi"), "cancel_reason": c("npp_ly_do_huy"),
			"vat_override": c("CASE WHEN {t}.`npp_co_thue_go_tay` = 1 THEN {t}.`npp_thue_go_tay` END", "tien"),
		},
		quan_he=[
			QuanHe("suppliers", "supplier_id", "id", False, ("purchase_invoices_supplier_id_fkey", "supplier_id")),
			QuanHe("purchase_invoice_lines", "id", "invoice_id", True, ("purchase_invoice_lines_invoice_id_fkey",)),
			QuanHe("payables", "payable_id", "id", False, ("purchase_invoices_payable_id_fkey", "payable_id")),
			QuanHe("users", "created_by", "id", False, ("purchase_invoices_created_by_fkey", "created_by")),
			QuanHe("users", "cancelled_by", "id", False, ("purchase_invoices_cancelled_by_fkey", "cancelled_by")),
		],
		rls=_rls_mua,
		ghi=GhiPhieuNhap(),
	))
	dang_ky(Bang(
		ten="purchase_invoice_lines",
		nguon=("(SELECT d.* FROM `tabPurchase Invoice Item` d WHERE d.`parenttype` = 'Purchase Invoice' AND d.`parent` IN "
			"(SELECT p.`name` FROM `tabPurchase Invoice` p WHERE p.`npp_loai` = 'phieu_nhap'))"),
		cot={
			"id": c("{t}.`name`"), "invoice_id": c("parent"), "product_id": c("item_code"), "unit_name": c("uom"), "quantity": c("qty", "so"),
			"unit_price": c("price_list_rate", "tien"), "line_discount": c("IFNULL({t}.`npp_giam_dong`, 0)", "tien"),
			"vat_rate": c("IFNULL({t}.`npp_thue_suat`, 0)", "so"), "conversion_factor": c("conversion_factor", "so"),
			"line_total": c("(GREATEST(0, {t}.`qty` * {t}.`price_list_rate` - IFNULL({t}.`npp_giam_dong`, 0)) * (1 + IFNULL({t}.`npp_thue_suat`, 0)))",
				"tien"),
			"notes": c("npp_ghi_chu"), "sort_order": c("idx", "so"), "created_at": c("creation", "gio"),
		},
		quan_he=[
			QuanHe("products", "product_id", "id", False, ("purchase_invoice_lines_product_id_fkey", "product_id")),
			QuanHe("purchase_invoices", "invoice_id", "id", False, ("purchase_invoice_lines_invoice_id_fkey", "invoice_id")),
		],
		rls=_rls_mua,
		ghi=GhiDongPhieuNhap(),
		thu_tu_mac_dinh=[{"cot": "invoice_id"}, {"cot": "sort_order"}],
	))
	if co_cot("NPP Cong No NCC", "khoa_nguon"):
		dang_ky(Bang(
			ten="payables",
			nguon="`tabNPP Cong No NCC`",
			cot={
				"id": c("{t}.`name`"), "org_id": org(), "supplier_id": c("nha_cung_cap"), "stock_entry_id": c("phieu_kho"),
				"invoice_number": c("so_hd_ncc"), "amount": c("so_tien", "tien"), "paid": c("da_tra", "tien"), "due_date": c("han_thanh_toan", "ngay"),
				"status": c("trang_thai"), "notes": c("ghi_chu"), "created_at": c("tao_luc", "gio"),
				"opening_balance": c("({t}.`loai` = 'dau_ky')", "bool"), "tim_kd": c("tim_kd"),
			},
			quan_he=[QuanHe("suppliers", "supplier_id", "id", False, ("payables_supplier_id_fkey", "supplier_id"))],
			rls=_rls_no,
		))


try:
	nap()
except Exception:  # noqa: BLE001 — nạp sổ ngoài request (không có DB) thì thôi
	pass
