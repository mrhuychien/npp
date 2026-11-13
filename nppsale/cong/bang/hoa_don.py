"""Bảng HOÁ ĐƠN BÁN + CÔNG NỢ của nppsale trên cổng (blueprint 02 §5.6, §6.1):

- sales_invoices / v_hoa_don_con_lai ← Sales Invoice (`is_return = 0`, `is_opening = 'No'`, docstatus 1 / 2 — không có HĐ nháp); `status` từ
  docstatus; `subtotal` = net_total − discount_amount (giảm cả đơn sau thuế); `stock_entry_id` = chính HĐ (chứng từ kho). Chỉ đọc — ghi qua
  RPC (post_invoice, reissue_invoice, cancel_invoice…). RLS `sales_invoices_select` (mig 124): vai owner / manager / accountant /
  warehouse, hoặc người đứng tên HĐ = tôi, hoặc người đứng tên ĐƠN của HĐ = tôi.
- sales_invoice_lines ← Sales Invoice Item của HĐ trên; theo dòng cha.
- receivables ← NPP Cong No (bản chiếu từ sổ — nppsale.su_kien.cong_no). RLS: owner / manager / accountant mọi dòng; sales dòng mình giữ nợ;
  thủ kho không dòng nào (không có chính sách). Ghi (nợ đầu kỳ) dựng ở bước nợ đầu kỳ.
"""
from __future__ import annotations

from ..dang_ky import Bang, CotDef, NguCanh, QuanHe, dang_ky
from ._chung import c, co_cot, la_nv, org

VAI_XEM_HD = ("owner", "manager", "accountant", "warehouse")
VAI_XEM_NO = ("owner", "manager", "accountant")
NGUON_HD = ("(SELECT * FROM `tabSales Invoice` WHERE `is_return` = 0 AND IFNULL(`is_opening`, 'No') = 'No' AND `docstatus` IN (1, 2))")


def ve_hoa_don(nc: NguCanh, bd: str = "{t}"):
	if nc.bo_qua_rls:
		return None
	if not la_nv(nc):
		return False
	if nc.vai in VAI_XEM_HD:
		return ("1 = 1", {})
	return (f"({bd}.`npp_nhan_vien` = %(u)s OR {bd}.`npp_don_hang` IN (SELECT so.`name` FROM `tabSales Order` so "
		"WHERE so.`npp_nhan_vien` = %(u)s))", {"u": nc.user})


def _rls_dong(nc):
	v = ve_hoa_don(nc, "hd")
	if v is None or v is False:
		return v
	return (f"{{t}}.`parent` IN (SELECT hd.`name` FROM `tabSales Invoice` hd WHERE {v[0]})", v[1])


def _cot_hd() -> dict:
	return {
		"id": c("{t}.`name`"), "org_id": org(), "invoice_code": c("{t}.`name`"),
		"invoice_seq": c("CAST(SUBSTRING_INDEX(SUBSTRING_INDEX({t}.`name`, '-', 2), '-', -1) AS UNSIGNED)", "so"),
		"reissue_no": c("CASE WHEN {t}.`name` REGEXP '^[A-Z]+-[0-9]+-[0-9]+$' THEN CAST(SUBSTRING_INDEX({t}.`name`, '-', -1) AS UNSIGNED) "
			"ELSE 0 END", "so"),
		"order_id": c("npp_don_hang"), "customer_id": c("customer"), "sales_user_id": c("npp_nhan_vien"),
		"invoice_date": c("posting_date", "ngay"),
		"status": c("CASE {t}.`docstatus` WHEN 1 THEN 'posted' WHEN 2 THEN 'cancelled' ELSE 'draft' END"),
		"subtotal": c("({t}.`net_total` - IFNULL({t}.`discount_amount`, 0))", "tien"), "vat": c("total_taxes_and_charges", "tien"),
		"total": c("grand_total", "tien"), "payment_terms": c("payment_terms_template"),
		"due_date": c("IFNULL({t}.`npp_han_thanh_toan`, {t}.`due_date`)", "ngay"), "stock_entry_id": c("{t}.`name`"),
		"notes": c("npp_ghi_chu"), "replaced_from": c("amended_from"),
		"replaced_by": c("(SELECT x.`name` FROM `tabSales Invoice` x WHERE x.`amended_from` = {t}.`name` ORDER BY x.`creation` DESC LIMIT 1)"),
		"posted_at": c("creation", "gio"),
		"posted_by": c("CASE WHEN {t}.`owner` IN ('Administrator', 'Guest') THEN NULL ELSE {t}.`owner` END"),
		"cancelled_at": c("npp_huy_luc", "gio"), "cancelled_by": c("npp_huy_boi"), "cancel_reason": c("npp_ly_do_huy"),
		"created_at": c("creation", "gio"), "updated_at": c("modified", "gio"), "soan_luc": c("npp_soan_luc", "gio"),
		"soan_boi": c("npp_soan_boi"), "tim_kd": c("npp_tim_kd"),
	}


_QH_HD = [
	QuanHe("customers", "customer_id", "id", False, ("sales_invoices_customer_id_fkey",)),
	QuanHe("users", "sales_user_id", "id", False, ("sales_invoices_sales_user_id_fkey",)),
	QuanHe("users", "posted_by", "id", False, ("sales_invoices_posted_by_fkey",)),
	QuanHe("users", "cancelled_by", "id", False, ("sales_invoices_cancelled_by_fkey",)),
	QuanHe("sales_orders", "order_id", "id", False, ("sales_invoices_order_id_fkey",)),
	QuanHe("sales_invoice_lines", "id", "invoice_id", True, ("sales_invoice_lines_invoice_id_fkey",)),
]


def nap():
	if not co_cot("Sales Invoice", "npp_don_hang"):
		return
	cot = _cot_hd()
	dang_ky(Bang(ten="sales_invoices", nguon=NGUON_HD, cot=cot, quan_he=_QH_HD, rls=ve_hoa_don))
	# v_hoa_don_con_lai (mig 257): tiền CÒN LẠI sau hàng trả đã trừ vào HĐ (luật creditCounted) — phiếu trả nối vào khi có NPP Phieu Tra
	con_lai = c("{t}.`grand_total`", "tien")
	if co_cot("NPP Phieu Tra", "tien_tra"):
		con_lai = c("({t}.`grand_total` - IFNULL((SELECT SUM(GREATEST(0, pt.`tien_tra`)) FROM `tabNPP Phieu Tra` pt WHERE pt.`hoa_don` = {t}.`name` "
			"AND ((pt.`tu_sinh` = 1 AND pt.`trang_thai` IN ('submitted', 'completed')) OR (pt.`tu_sinh` = 0 AND pt.`trang_thai` = 'completed'))), 0))",
			"tien")
	dang_ky(Bang(ten="v_hoa_don_con_lai", nguon=NGUON_HD, cot={**cot, "con_lai": con_lai}, quan_he=_QH_HD, rls=ve_hoa_don))
	dang_ky(Bang(
		ten="sales_invoice_lines",
		nguon="(SELECT * FROM `tabSales Invoice Item` WHERE `parenttype` = 'Sales Invoice')",
		cot={
			# Tờ đã huỷ nhả móc nối về dòng đơn (mig 162): dòng HĐ giữ bản chụp, order_line_id = NULL — không chặn bỏ dòng khỏi đơn
			"id": c("{t}.`name`"), "invoice_id": c("parent"),
			"order_line_id": c("CASE WHEN {t}.`docstatus` = 2 THEN NULL ELSE {t}.`so_detail` END"), "product_id": c("item_code"),
			"unit_name": c("uom"), "conversion_factor": c("conversion_factor", "so"), "quantity": c("qty", "so"), "unit_price": c("rate", "tien"),
			"line_discount": c("npp_giam_dong", "tien"), "line_total": c("amount", "tien"), "vat_rate": c("npp_thue_suat", "so"),
			"is_exchange": c("npp_hang_doi", "bool"), "sort_order": c("idx", "so"), "note": c("npp_ghi_chu"),
		},
		quan_he=[
			QuanHe("products", "product_id", "id", False, ("sales_invoice_lines_product_id_fkey",)),
			QuanHe("sales_invoices", "invoice_id", "id", False, ("sales_invoice_lines_invoice_id_fkey",)),
			QuanHe("sales_order_lines", "order_line_id", "id", False, ("sales_invoice_lines_order_line_id_fkey",)),
		],
		rls=_rls_dong,
	))
	if co_cot("NPP Cong No", "khoa_nguon"):
		dang_ky(Bang(
			ten="receivables",
			nguon="`tabNPP Cong No`",
			cot={
				"id": c("{t}.`name`"), "org_id": org(), "order_id": c("don_hang"), "customer_id": c("khach_hang"),
				"sales_user_id": c("nhan_vien"), "amount": c("so_tien", "tien"), "paid": c("da_thu", "tien"),
				"due_date": c("han_thanh_toan", "ngay"), "status": c("trang_thai"), "created_at": c("tao_luc", "gio"),
				"opening_balance": c("({t}.`loai` = 'dau_ky')", "bool"), "note": c("ghi_chu"),
				"invoice_id": c("CASE WHEN {t}.`loai` = 'hoa_don' THEN {t}.`hoa_don` END"), "return_id": c("phieu_tra"),
				"ve_npp_luc": c("ve_npp_luc", "gio"), "giao_tu_nv": c("giao_tu_nv"),
			},
			quan_he=[
				QuanHe("customers", "customer_id", "id", False, ("receivables_customer_id_fkey",)),
				QuanHe("users", "sales_user_id", "id", False, ("receivables_sales_user_id_fkey",)),
				QuanHe("sales_orders", "order_id", "id", False, ("receivables_order_id_fkey",)),
				QuanHe("sales_invoices", "invoice_id", "id", False, ("receivables_invoice_id_fkey",)),
			],
			rls=_rls_no,
		))


def _rls_no(nc: NguCanh):
	if nc.bo_qua_rls:
		return None
	if nc.vai in VAI_XEM_NO:
		return ("1 = 1", {})
	if nc.vai == "sales":
		return ("{t}.`nhan_vien` = %(u)s", {"u": nc.user})
	return False


try:
	nap()
except Exception:  # noqa: BLE001 — nạp sổ ngoài request (không có DB) thì thôi
	pass
