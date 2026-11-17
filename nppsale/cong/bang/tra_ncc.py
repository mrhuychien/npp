"""Bảng PHIẾU TRẢ NCC của nppsale trên cổng (P4 — mốc M2; đặc tả kho_mua §4.3; blueprint 02 §5.9, §6.1):

- supplier_returns ← Purchase Invoice `npp_loai = tra_ncc` (`is_return = 1`, mọi docstatus). `id` = `return_code` = `name` (`PTNCC-0042`, tờ amend
  `PTNCC-0042-1` — ⚠K CFD-01: nppsale sửa / khôi phục giữ số); `return_seq` = số tách từ tên (tờ gốc của chuỗi); `return_code_cu` = `npp_ma_cu` (mã `TH-…`
  trước mig 240 — chỉ dữ liệu chuyển sang); `return_date` = `bill_date` (ngày trả hiển thị — ghi sổ kho / nợ lúc bấm như nppsale, §7.3 điểm 11);
  `reason` = `npp_ly_do`; `notes` = `npp_ghi_chu`; tiền như phiếu nhập ĐỔI DẤU VỀ DƯƠNG (tờ trả mang số âm): `subtotal` = −`total`, `vat` = −Σ dòng
  thuế trừ dòng chi phí trả hàng (KHÔNG đọc `total_taxes_and_charges` — đã trừ khoản ấy), `total` = −`grand_total`, `discount` = `npp_giam_dau_phieu`,
  `vat_override` = thuế gõ tay khi có cờ (NULL ≠ 0); `status` = docstatus 0 → `draft` (nháp mang dấu huỷ → `cancelled` — §7.3 điểm 1), 1 →
  `completed`, 2 → `cancelled`; `warehouse_zone` = kho của phiếu (`npp_kho_nhap` → `set_warehouse`); `stock_entry_id` = chính tờ khi đã / thôi ghi sổ
  (⚠K §7.2 #14 — phiếu kho = PI); `payable_credit_id` = dòng `NPP Cong No NCC` (âm) của tờ (nháp / huỷ → NULL); `completed_at` / `completed_by` =
  `npp_hoan_thanh_luc` / `npp_hoan_thanh_boi`; `cancel_reason` = `npp_ly_do_huy` (nppsale không có `cancelled_at / by`); `created_by` / `created_at` của
  tờ GỐC chuỗi amend.
  RLS (mig 068): ĐỌC mọi NV của NPP (kể cả NVBH, tài xế — "View supplier returns"); ghi bốn vai mua hàng.
- supplier_return_lines ← Purchase Invoice Item của các tờ trên: `quantity` DƯƠNG (dòng PI âm), `unit_price` = `price_list_rate`, `line_discount` =
  `npp_giam_dong` (TIỀN cả dòng), `vat_rate` = `npp_thue_suat` (tỉ lệ), `line_total` = max(0, SL × giá − giảm) × (1 + thuế) (như trình duyệt ghi),
  `sort_order` = `idx`.
  Ghi (cả hai bảng): phiếu NHÁP qua `nppsale.rpc.tra_ncc` — trạng thái / tờ đã gửi / đã huỷ → `USE_RPC` (BP §6.1 siết; nppsale RLS cho ghi mọi cột,
  không trigger khoá — K25).
"""
from __future__ import annotations

from ..dang_ky import Bang, CotDef, QuanHe, dang_ky
from ._chung import c, co_cot, org, rls_moi_nv
from .kho import KHO
from .mua_hang import TK_GIAM

NGUON_PTN = "(SELECT * FROM `tabPurchase Invoice` WHERE `npp_loai` = 'tra_ncc')"
GOC = "SUBSTRING_INDEX({t}.`name`, '-', 2)"  # tờ gốc của chuỗi amend: `PTNCC-0042-1` → `PTNCC-0042`


class GhiPhieuTra:
	"""supplier_returns: phiếu nháp — nppsale.rpc.tra_ncc."""

	def them(self, ds, nc):
		from nppsale.rpc.tra_ncc import them_phieu

		return them_phieu(ds, nc)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.tra_ncc import sua_phieu

		return sua_phieu(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.tra_ncc import xoa_phieu

		return xoa_phieu(ids, nc)


class GhiDongPhieuTra:
	"""supplier_return_lines: dòng của phiếu nháp — nppsale.rpc.tra_ncc."""

	def them(self, ds, nc):
		from nppsale.rpc.tra_ncc import them_dong

		return them_dong(ds, nc)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.tra_ncc import sua_dong

		return sua_dong(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.tra_ncc import xoa_dong

		return xoa_dong(ids, nc)


def nap():
	if not co_cot("Purchase Invoice", "npp_loai"):
		return
	nguoi_lap = f"(SELECT g.`owner` FROM `tabPurchase Invoice` g WHERE g.`name` = {GOC})"
	dang_ky(Bang(
		ten="supplier_returns",
		nguon=NGUON_PTN,
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "supplier_id": c("supplier"), "return_code": c("{t}.`name`"),
			"return_seq": c(f"CAST(SUBSTRING_INDEX({GOC}, '-', -1) AS UNSIGNED)", "so"), "return_code_cu": c("npp_ma_cu"),
			"return_date": c("bill_date", "ngay"), "reason": c("npp_ly_do"), "notes": c("npp_ghi_chu"),
			"subtotal": c("-COALESCE({t}.`total`, 0)", "tien"),
			"vat": c("-(SELECT COALESCE(SUM(CASE WHEN x.`add_deduct_tax` = 'Deduct' THEN -x.`tax_amount` ELSE x.`tax_amount` END), 0) "
				"FROM `tabPurchase Taxes and Charges` x WHERE x.`parent` = {t}.`name` AND x.`parenttype` = 'Purchase Invoice' "
				f"AND x.`account_head` <> IFNULL({TK_GIAM}, ''))", "tien"),
			"total": c("-COALESCE({t}.`grand_total`, 0)", "tien"), "discount": c("npp_giam_dau_phieu", "tien"),
			"vat_override": c("CASE WHEN {t}.`npp_co_thue_go_tay` = 1 THEN {t}.`npp_thue_go_tay` END", "tien"),
			"status": c("CASE WHEN {t}.`docstatus` = 1 THEN 'completed' WHEN {t}.`docstatus` = 2 OR {t}.`npp_huy_luc` IS NOT NULL "
				"THEN 'cancelled' ELSE 'draft' END"),
			"warehouse_zone": c(f"(SELECT z.`vung` FROM {KHO} z WHERE z.`kho` = COALESCE(NULLIF({{t}}.`npp_kho_nhap`, ''), {{t}}.`set_warehouse`) "
				"LIMIT 1)"),
			"stock_entry_id": c("CASE WHEN {t}.`docstatus` IN (1, 2) THEN {t}.`name` END"),
			"payable_credit_id": c("(SELECT n.`name` FROM `tabNPP Cong No NCC` n WHERE n.`chung_tu` = {t}.`name` LIMIT 1)"),
			"completed_at": c("npp_hoan_thanh_luc", "gio"), "completed_by": c("npp_hoan_thanh_boi"),
			"created_by": c(f"CASE WHEN {nguoi_lap} IN ('Administrator', 'Guest') THEN NULL ELSE {nguoi_lap} END"),
			"created_at": c(f"(SELECT g.`creation` FROM `tabPurchase Invoice` g WHERE g.`name` = {GOC})", "gio"),
			"cancel_reason": c("npp_ly_do_huy"),
		},
		quan_he=[
			QuanHe("suppliers", "supplier_id", "id", False, ("supplier_returns_supplier_id_fkey", "supplier_id")),
			QuanHe("supplier_return_lines", "id", "return_id", True, ("supplier_return_lines_return_id_fkey",)),
			QuanHe("payables", "payable_credit_id", "id", False, ("supplier_returns_payable_credit_id_fkey", "payable_credit_id")),
			QuanHe("users", "created_by", "id", False, ("supplier_returns_created_by_fkey", "created_by")),
			QuanHe("users", "completed_by", "id", False, ("supplier_returns_completed_by_fkey", "completed_by")),
		],
		rls=rls_moi_nv,
		ghi=GhiPhieuTra(),
	))
	dang_ky(Bang(
		ten="supplier_return_lines",
		nguon=("(SELECT d.* FROM `tabPurchase Invoice Item` d WHERE d.`parenttype` = 'Purchase Invoice' AND d.`parent` IN "
			"(SELECT p.`name` FROM `tabPurchase Invoice` p WHERE p.`npp_loai` = 'tra_ncc'))"),
		cot={
			"id": c("{t}.`name`"), "return_id": c("parent"), "product_id": c("item_code"), "unit_name": c("uom"),
			"quantity": CotDef("-{t}.`qty`", "so"), "unit_price": c("price_list_rate", "tien"),
			"line_discount": c("IFNULL({t}.`npp_giam_dong`, 0)", "tien"), "vat_rate": c("IFNULL({t}.`npp_thue_suat`, 0)", "so"),
			"conversion_factor": c("conversion_factor", "so"),
			"line_total": c("(GREATEST(0, -{t}.`qty` * {t}.`price_list_rate` - IFNULL({t}.`npp_giam_dong`, 0)) "
				"* (1 + IFNULL({t}.`npp_thue_suat`, 0)))", "tien"),
			"notes": c("npp_ghi_chu"), "sort_order": c("idx", "so"), "created_at": c("creation", "gio"),
		},
		quan_he=[
			QuanHe("products", "product_id", "id", False, ("supplier_return_lines_product_id_fkey", "product_id")),
			QuanHe("supplier_returns", "return_id", "id", False, ("supplier_return_lines_return_id_fkey", "return_id")),
		],
		rls=rls_moi_nv,
		ghi=GhiDongPhieuTra(),
		thu_tu_mac_dinh=[{"cot": "return_id"}, {"cot": "sort_order"}],
	))


try:
	nap()
except Exception:  # noqa: BLE001 — nạp sổ ngoài request (không có DB) thì thôi
	pass
