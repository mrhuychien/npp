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


@rpc("ton_kho_trang", ghi=False)
def ton_kho_trang(p_tim=None, p_con_ton=True, p_sap="ten", p_offset=0, p_limit=20):
	"""mig 255 — màn Tồn kho hiện tại: gộp kho bán / kho cận date theo mặt hàng (dòng lô còn hàng), lọc "còn tồn", tìm theo khoá tìm
	(mọi từ, không dấu), sắp tên (tiếng Việt) / giá trị / số lượng, chia trang; mỗi dòng kèm total_count + sum_* của CẢ tập đã lọc.
	Mặt hàng ngừng bán chỉ hiện khi còn tồn. Hàm gốc SECURITY INVOKER — người ngoài NPP không thấy dòng nào."""
	from nppsale.luat.tim import tu_tim

	if not _la_nv():
		return []
	tu = tu_tim(p_tim or "")
	con_ton = True if p_con_ton is None else bool(p_con_ton)
	sap = p_sap if p_sap in ("gia-tri", "so-luong") else "ten"
	tu_dong = max(int(p_offset or 0), 0)
	so_dong = min(max(int(p_limit or 20), 1), 500)
	ts: dict = {"tu_dong": tu_dong, "so_dong": so_dong}
	loc_tu = []
	for i, w in enumerate(tu):
		ts[f"w{i}"] = f"%{w}%"
		loc_tu.append(f"COALESCE(NULLIF(i.`npp_tim_kd`, ''), LOWER(CONCAT_WS(' ', i.`item_code`, i.`item_name`))) LIKE %(w{i})s")
	# sắp tên: không có khoá đầu (MariaDB đọc `ORDER BY 0` là số thứ tự cột)
	sap_sql = {"gia-tri": "s.`sale_value` + s.`date_value` DESC, ", "so-luong": "s.`sale_qty` + s.`date_qty` DESC, "}.get(sap, "")
	ds = frappe.db.sql(f"""
		WITH ton AS (
			SELECT x.`hang`,
				COALESCE(SUM(CASE WHEN x.`vung` = 'date' THEN x.`ton` END), 0) AS `date_qty`,
				COALESCE(SUM(CASE WHEN x.`vung` = 'date' THEN x.`ton` * COALESCE(x.`gia_von`, 0) END), 0) AS `date_value`,
				COALESCE(SUM(CASE WHEN x.`vung` != 'date' THEN x.`ton` END), 0) AS `sale_qty`,
				COALESCE(SUM(CASE WHEN x.`vung` != 'date' THEN x.`ton` * COALESCE(x.`gia_von`, 0) END), 0) AS `sale_value`
			FROM {NGUON_LO} x WHERE x.`ton` > 0 GROUP BY x.`hang`
		), s AS (
			SELECT i.`name` AS `product_id`, i.`item_code` AS `sku`, i.`item_name` AS `name`, i.`stock_uom` AS `base_unit`,
				CASE WHEN IFNULL(i.`npp_ngung_ban`, 0) = 1 THEN 'inactive' ELSE 'active' END AS `status`,
				COALESCE(t.`sale_qty`, 0) AS `sale_qty`, COALESCE(t.`sale_value`, 0) AS `sale_value`,
				COALESCE(t.`date_qty`, 0) AS `date_qty`, COALESCE(t.`date_value`, 0) AS `date_value`
			FROM `tabItem` i LEFT JOIN ton t ON t.`hang` = i.`name`
			WHERE (IFNULL(i.`npp_ngung_ban`, 0) = 0 OR COALESCE(t.`sale_qty`, 0) <> 0 OR COALESCE(t.`date_qty`, 0) <> 0)
				AND ({'COALESCE(t.`sale_qty`, 0) + COALESCE(t.`date_qty`, 0) > 0' if con_ton else '1 = 1'})
				{''.join(' AND ' + x for x in loc_tu)}
		)
		SELECT s.*, s.`sale_qty` + s.`date_qty` AS `total_qty`, s.`sale_value` + s.`date_value` AS `total_value`,
			COUNT(*) OVER () AS `total_count`, SUM(s.`sale_qty`) OVER () AS `sum_sale_qty`, SUM(s.`sale_value`) OVER () AS `sum_sale_value`,
			SUM(s.`date_qty`) OVER () AS `sum_date_qty`, SUM(s.`date_value`) OVER () AS `sum_date_value`,
			SUM(s.`sale_qty` + s.`date_qty`) OVER () AS `sum_total_qty`, SUM(s.`sale_value` + s.`date_value`) OVER () AS `sum_total_value`
		FROM s
		ORDER BY {sap_sql}s.`name` COLLATE utf8mb4_vietnamese_ci, s.`product_id`
		LIMIT %(so_dong)s OFFSET %(tu_dong)s""", ts, as_dict=True)
	if not ds:
		return []
	dv: dict = {}
	for r in frappe.db.sql("""SELECT u.`parent`, u.`uom`, u.`conversion_factor` FROM `tabUOM Conversion Detail` u
			JOIN `tabItem` i ON i.`name` = u.`parent` WHERE u.`parenttype` = 'Item' AND u.`parent` IN %s AND u.`uom` != i.`stock_uom`
			ORDER BY u.`conversion_factor` DESC""", (tuple(r.product_id for r in ds),), as_dict=True):
		dv.setdefault(r.parent, []).append({"unit_name": r.uom, "conversion": flt(r.conversion_factor)})
	so = ("sale_qty", "sale_value", "date_qty", "date_value", "total_qty", "total_value", "sum_sale_qty", "sum_sale_value", "sum_date_qty",
		"sum_date_value", "sum_total_qty", "sum_total_value")
	return [{**r, **{k: flt(r[k]) for k in so}, "total_count": int(r.total_count), "units": dv.get(r.product_id)} for r in ds]
