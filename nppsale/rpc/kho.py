"""RPC KHO chỉ đọc (STABLE ở nppsale — gọi GET): tồn kho bán theo mặt hàng (POS), tổng giá trị tồn, hàng đã đặt chưa xuất.

Cùng một nguồn với bảng cổng `batches` (nppsale.cong.bang.kho.NGUON_LO: lô × kho từ gói lô chưa huỷ + lô ảo của hàng không lô) — một
luật tồn cho mọi nơi đọc.
"""
from __future__ import annotations

import frappe
from frappe.utils import flt

from nppsale.cong.bang.kho import NGUON_LO
from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai

from . import rpc
from .don_hang import _chu


def _la_nv() -> bool:
	"""= user_org_id() IS NOT NULL (NV đang hoạt động của NPP)."""
	return bool(hien_tai().vai)


@rpc("ton_ban_theo_hang", ghi=False)
def ton_ban_theo_hang():
	"""mig 257: {mặt hàng: Σ tồn > 0 của các dòng lô vùng bán} — POS / bán hàng đọc MỘT câu thay vì tải từng lô."""
	if not _la_nv():
		return {}
	return {hang: flt(sl) for hang, sl in frappe.db.sql(f"""SELECT x.`hang`, SUM(x.`ton`) FROM {NGUON_LO} x
		WHERE x.`ton` > 0 AND x.`vung` = 'sale' GROUP BY x.`hang`""")}


@rpc("stock_value_summary", ghi=False)
def stock_value_summary():
	"""Σ tồn × giá vốn và số dòng lô còn hàng (mọi vùng)."""
	if not _la_nv():
		return [{"inventory_value": 0, "batch_count": 0}]
	gt, so = frappe.db.sql(f"""SELECT COALESCE(SUM(x.`ton` * COALESCE(x.`gia_von`, 0)), 0), COUNT(*) FROM {NGUON_LO} x
		WHERE COALESCE(x.`ton`, 0) > 0""")[0]
	return [{"inventory_value": flt(gt), "batch_count": int(so)}]


@rpc("committed_stock_by_product", ghi=False)
def committed_stock_by_product(p_exclude_order=None):
	"""mig 136 / 137: hàng ĐÃ ĐẶT chưa xuất (đơn submitted / partially_invoiced, trừ đơn đang sửa) theo đơn vị cơ sở — dòng đơn còn lại ×
	hệ số + dòng HÀNG ĐỔI của phiếu trả nháp / chờ kèm đơn chưa bám HĐ (khi có NPP Phieu Tra)."""
	if not _la_nv():
		raise NppLoi("NO_ORG: Tài khoản chưa được gắn đơn vị nên không đọc được số hàng đã đặt.")
	bo = _chu(p_exclude_order) or ""
	ds = frappe.db.sql("""SELECT i.`item_code`, SUM(GREATEST(0, i.`qty` - IFNULL(i.`delivered_qty`, 0)) * IFNULL(i.`conversion_factor`, 1))
		FROM `tabSales Order Item` i JOIN `tabSales Order` so ON so.`name` = i.`parent`
		WHERE so.`npp_trang_thai` IN ('submitted', 'partially_invoiced') AND so.`docstatus` < 2 AND so.`name` != %s
		GROUP BY i.`item_code`""", bo)
	tong: dict = {}
	for hang, sl in ds:
		tong[hang] = tong.get(hang, 0.0) + flt(sl)
	if frappe.db.exists("DocType", "NPP Phieu Tra"):
		from nppsale.rpc.phieu_tra import hang_doi_da_dat

		for hang, sl in hang_doi_da_dat(bo):
			tong[hang] = tong.get(hang, 0.0) + flt(sl)
	return [{"product_id": h, "committed_base": sl} for h, sl in sorted(tong.items()) if sl > 0]
