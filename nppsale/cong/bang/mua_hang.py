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
- payables (đọc từ M1, ghi từ M3) đăng ký ở nppsale.cong.bang.cong_no_ncc — cùng `payable_payments`, `supplier_payments`.
"""
from __future__ import annotations

from ..dang_ky import Bang, CotDef, NguCanh, QuanHe, dang_ky
from ._chung import c, co_cot, org
from .kho import KHO

VAI_MUA = ("owner", "manager", "accountant", "warehouse")
NGUON_PN = "(SELECT * FROM `tabPurchase Invoice` WHERE `npp_loai` = 'phieu_nhap')"
TK_GIAM = "(SELECT s.`value` FROM `tabSingles` s WHERE s.`doctype` = 'NPP Cai Dat' AND s.`field` = 'tk_giam_dau_phieu_nhap')"
# dòng thuế bù nợ lệch giá vốn của phiếu nhập sinh từ màn Nhập kho (nppsale.rpc.phieu_nhap.MO_TA_LECH — một chữ, không import mã RPC vào sổ cổng)
MO_TA_LECH_SQL = "'Phần nợ NCC lệch giá vốn (nhập kho)'"
# tờ GỐC của chuỗi amend: `PN-0042-1` → `PN-0042` (dãy `PN-.####` không có gạch nối khác)
GOC = "SUBSTRING_INDEX({t}.`name`, '-', 2)"


def _rls_mua(nc: NguCanh):
	if nc.bo_qua_rls or nc.vai in VAI_MUA:
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


# Phiếu đã SỬA GIÁ (M7 nhánh B — đặc tả §3.3, BP §5.9 `npp_sua_gia`): tờ lõi giữ giá gốc, chênh nằm ở LCV `SGN-` + bút toán `DCN-` → cổng phủ số HIỆN HÀNH
# của `npp_sua_gia` lên đầu phiếu (`dau_phieu`) và dòng (`dong."<idx>"`). JSON null (thuế gõ tay đã bỏ) → NULL.
DA_SUA = "JSON_EXISTS({t}.`npp_sua_gia`, '$.dau_phieu')"


def _so_json(cot: str, duong: str) -> str:
	return f"CAST(JSON_VALUE({cot}.`npp_sua_gia`, '{duong}') AS DECIMAL(21,6))"


def phu(khoa: str, goc: str) -> str:
	"""Cột tiền của đầu phiếu: số đã sửa khi có, không thì biểu thức gốc."""
	return f"CASE WHEN {DA_SUA} THEN {_so_json('{t}', '$.dau_phieu.' + khoa)} ELSE {goc} END"


def dong_json(khoa: str) -> str:
	return f"CONCAT('$.dong.\"', {{t}}.`idx`, '\"{khoa}')"


def _dong(khoa: str, goc: str) -> str:
	return (f"CASE WHEN JSON_EXISTS({{t}}.`_sua`, {dong_json('')}) THEN CAST(JSON_VALUE({{t}}.`_sua`, {dong_json('.' + khoa)}) AS DECIMAL(21,6)) "
		f"ELSE {goc} END")


gia_dong = _dong("don_gia", "{t}.`price_list_rate`")
giam_dong = _dong("giam_dong", "IFNULL({t}.`npp_giam_dong`, 0)")
thue_dong = _dong("thue_suat", "IFNULL({t}.`npp_thue_suat`, 0)")


def nap():
	if not co_cot("Purchase Invoice", "npp_loai"):
		return
	nguoi_lap = f"(SELECT g.`owner` FROM `tabPurchase Invoice` g WHERE g.`name` = {GOC})"
	dang_ky(Bang(
		ten="purchase_invoices",
		nguon=NGUON_PN,
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "po_id": CotDef("NULL"), "supplier_id": c("supplier"), "invoice_number": c("bill_no"),
			"invoice_date": c("bill_date", "ngay"), "subtotal": c(phu("tien_hang", "COALESCE({t}.`total`, 0)"), "tien"),
			# `vat` không gồm dòng nợ lệch giá vốn của phiếu sinh từ màn Nhập kho (`phieu_nhap.dong_lech` — gắn lại mỗi lần dựng bảng thuế): màn sửa / POS
			# nạp `vat` làm thuế gõ tay là đếm hai lần (soát P4); `total` vẫn gồm
			"vat": c(phu("thue", "(SELECT COALESCE(SUM(CASE WHEN x.`add_deduct_tax` = 'Deduct' THEN -x.`tax_amount` ELSE x.`tax_amount` END), 0) "
				"FROM `tabPurchase Taxes and Charges` x WHERE x.`parent` = {t}.`name` AND x.`parenttype` = 'Purchase Invoice' "
				f"AND x.`account_head` <> IFNULL({TK_GIAM}, '') AND NOT (x.`charge_type` = 'Actual' AND x.`description` <=> {MO_TA_LECH_SQL}))"), "tien"),
			"total": c(phu("tong", "COALESCE({t}.`grand_total`, 0)"), "tien"),
			"status": c("CASE WHEN {t}.`docstatus` = 1 THEN 'completed' WHEN {t}.`docstatus` = 2 OR {t}.`npp_huy_luc` IS NOT NULL "
				"THEN 'cancelled' ELSE 'draft' END"),
			"payable_id": c("(SELECT n.`name` FROM `tabNPP Cong No NCC` n WHERE n.`chung_tu` = {t}.`name` LIMIT 1)"),
			"notes": c("npp_ghi_chu"),
			"created_at": c(f"(SELECT g.`creation` FROM `tabPurchase Invoice` g WHERE g.`name` = {GOC})", "gio"),
			"created_by": c(f"CASE WHEN {nguoi_lap} IN ('Administrator', 'Guest') THEN NULL ELSE {nguoi_lap} END"),
			"completed_at": c("npp_hoan_thanh_luc", "gio"),
			"stock_entry_id": c("CASE WHEN {t}.`docstatus` IN (1, 2) THEN {t}.`name` END"),
			"receipt_code": c("{t}.`name`"), "discount": c(phu("giam", "{t}.`npp_giam_dau_phieu`"), "tien"),
			# kho người chọn: `npp_kho_nhap` (lõi xoá `set_warehouse` khi các dòng khác kho — dòng hạn ngắn vào kho cận date)
			"warehouse_zone": c(f"(SELECT z.`vung` FROM {KHO} z WHERE z.`kho` = COALESCE(NULLIF({{t}}.`npp_kho_nhap`, ''), {{t}}.`set_warehouse`) "
				"LIMIT 1)"),
			"cancelled_at": c("npp_huy_luc", "gio"), "cancelled_by": c("npp_huy_boi"), "cancel_reason": c("npp_ly_do_huy"),
			"vat_override": c(f"CASE WHEN {DA_SUA} THEN {_so_json('{t}', '$.dau_phieu.thue_go_tay')} "
				"WHEN {t}.`npp_co_thue_go_tay` = 1 THEN {t}.`npp_thue_go_tay` END", "tien"),
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
		# `_sua` = `npp_sua_gia` của phiếu cha (M7 nhánh B — giá đã sửa ở phiếu đã bán phủ lên dòng)
		nguon=("(SELECT d.*, p.`npp_sua_gia` AS `_sua` FROM `tabPurchase Invoice Item` d JOIN `tabPurchase Invoice` p ON p.`name` = d.`parent` "
			"WHERE d.`parenttype` = 'Purchase Invoice' AND p.`npp_loai` = 'phieu_nhap')"),
		cot={
			"id": c("{t}.`name`"), "invoice_id": c("parent"), "product_id": c("item_code"), "unit_name": c("uom"), "quantity": c("qty", "so"),
			"unit_price": c(gia_dong, "tien"), "line_discount": c(giam_dong, "tien"), "vat_rate": c(thue_dong, "so"),
			"conversion_factor": c("conversion_factor", "so"),
			"line_total": c(f"(GREATEST(0, {{t}}.`qty` * {gia_dong} - {giam_dong}) * (1 + {thue_dong}))", "tien"),
			"notes": c(f"CASE WHEN JSON_EXISTS({{t}}.`_sua`, {dong_json('')}) THEN JSON_VALUE({{t}}.`_sua`, {dong_json('.ghi_chu')}) "
				"ELSE {t}.`npp_ghi_chu` END"),
			"sort_order": c("idx", "so"), "created_at": c("creation", "gio"),
		},
		quan_he=[
			QuanHe("products", "product_id", "id", False, ("purchase_invoice_lines_product_id_fkey", "product_id")),
			QuanHe("purchase_invoices", "invoice_id", "id", False, ("purchase_invoice_lines_invoice_id_fkey", "invoice_id")),
		],
		rls=_rls_mua,
		ghi=GhiDongPhieuNhap(),
		thu_tu_mac_dinh=[{"cot": "invoice_id"}, {"cot": "sort_order"}],
	))


try:
	nap()
except Exception:  # noqa: BLE001 — nạp sổ ngoài request (không có DB) thì thôi
	pass
