"""RPC Xuất hàng trên Sales Order / Sales Invoice.

get_invoiceable_lines (mig 124 / 212): dòng của đơn để màn Xuất hàng (POS / điện thoại) dựng hoá đơn — SL đặt, đã xuất, còn lại, giá, giảm,
thuế, tồn kho bán (theo đơn vị kho), cộng dòng HÀNG ĐỔI của phiếu trả nháp / chờ kèm đơn chưa bám HĐ nào. Hàm gốc SECURITY DEFINER, chỉ
kiểm cùng đơn vị — không lọc theo người (POS của chủ / thủ kho mở đơn của mọi NV). Chỉ đọc (GET — POS gọi `{ get: true }`).
"""
from __future__ import annotations

import frappe
from frappe.utils import flt

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai
from nppsale.thiet_lap.ban_hang import cai_dat_ban

from . import rpc


def _ton_kho_ban(hang: list[str], kho: str | None) -> dict:
	"""Σ tồn của mặt hàng trong kho bán (đơn vị kho) — = Σ batches.qty_on_hand vùng 'sale' của nppsale."""
	if not hang or not kho:
		return {}
	return {r.item_code: flt(r.actual_qty) for r in frappe.get_all("Bin", filters={"item_code": ("in", hang), "warehouse": kho},
		fields=["item_code", "actual_qty"])}


@rpc("get_invoiceable_lines", ghi=False)
def get_invoiceable_lines(p_order_id=None):
	nc = hien_tai()
	ten = p_order_id if isinstance(p_order_id, str) else None
	if not ten or not frappe.db.exists("Sales Order", ten):
		raise NppLoi("ORDER_NOT_FOUND")
	if not nc.bo_qua_rls and not nc.vai:
		raise NppLoi("ORG_MISMATCH")
	dong = frappe.db.sql(
		"""
		SELECT d.`name`, d.`item_code`, i.`item_name`, d.`uom`, d.`conversion_factor`, d.`qty`, d.`delivered_qty`, d.`rate`,
			i.`npp_gia_ban`, d.`npp_giam_dong`, d.`npp_thue_suat`, i.`npp_thue_suat` AS `thue_sp`, d.`additional_notes`
		FROM `tabSales Order Item` d
		LEFT JOIN `tabItem` i ON i.`name` = d.`item_code`
		WHERE d.`parent` = %s AND d.`parenttype` = 'Sales Order'
		ORDER BY d.`idx`
		""",
		ten,
		as_dict=True,
	)
	ton = _ton_kho_ban(sorted({d.item_code for d in dong}), cai_dat_ban().kho_ban)
	ra = []
	for d in dong:
		da = flt(d.delivered_qty)
		ra.append({
			"order_line_id": d.name, "return_line_id": None, "product_id": d.item_code, "product_name": d.item_name, "sku": d.item_code,
			"unit_name": d.uom, "conversion_factor": flt(d.conversion_factor) or 1, "ordered_qty": flt(d.qty), "invoiced_qty": da,
			"remaining_qty": max(0.0, flt(d.qty) - da), "unit_price": flt(d.rate), "list_price": flt(d.npp_gia_ban),
			"line_discount": flt(d.npp_giam_dong),
			"vat_rate": flt(d.npp_thue_suat if d.npp_thue_suat is not None else (d.thue_sp or 0)),
			"available_base": ton.get(d.item_code, 0.0), "is_exchange": False, "note": d.additional_notes,
		})
	ra.extend(_dong_hang_doi(ten))
	return ra


def _dong_hang_doi(don: str) -> list[dict]:
	"""Dòng hàng đổi của phiếu trả nháp / chờ kèm đơn, chưa bám HĐ (mig 212) — có khi DocType phiếu trả đã dựng."""
	if not frappe.db.exists("DocType", "NPP Phieu Tra"):
		return []
	from nppsale.rpc.phieu_tra import dong_hang_doi_cua_don

	return dong_hang_doi_cua_don(don)
