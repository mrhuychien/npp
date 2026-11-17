"""RPC KHO chỉ đọc (STABLE ở nppsale — gọi GET): tồn kho bán theo mặt hàng (POS), tổng giá trị tồn, hàng đã đặt chưa xuất, báo cáo tồn kho một lượt.

Cùng một nguồn với bảng cổng `batches` (nppsale.cong.bang.kho.NGUON_LO: lô × kho từ gói lô chưa huỷ + lô ảo của hàng không lô) — một
luật tồn cho mọi nơi đọc; các hàm chỉ cần dòng tồn > 0 đọc `NGUON_LO_CON_TON` (cùng dòng, chỉ gộp gói lô của lô `batch_qty > 0` — P6 M0, đặc tả báo cáo
§2.2). Giá trị tồn (tồn × giá vốn) chỉ người được xem giá vốn (`xemDuocGiaVon`) — người khác nhận NULL, như cột
`batches.unit_cost` ở cổng (nppsale chỉ che ở giao diện).

`bao_cao_ton_kho(p_tu, p_den)` (P4 — M9, đặc tả kho_mua §5.4; mig 204 / 256): hàm nppsale SQL STABLE **SECURITY INVOKER** → đọc QUA CỔNG dưới người gọi
(`truy_van.doc` — vế RLS + che cột một chỗ với bảng cổng): `lo` = dòng cổng `batches` còn hàng, `dong` = dòng HĐ ghi sổ trong kỳ (vế đọc
`sales_invoices` của người gọi — NVBH chỉ HĐ mình).
"""
from __future__ import annotations

import frappe
from frappe.utils import flt

from nppsale.cong.bang.kho import NGUON_LO_CON_TON
from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai, xem_gia_von

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
	return {hang: flt(sl) for hang, sl in frappe.db.sql(f"""SELECT x.`hang`, SUM(x.`ton`) FROM {NGUON_LO_CON_TON} x
		WHERE x.`ton` > 0 AND x.`vung` = 'sale' GROUP BY x.`hang`""")}


@rpc("stock_value_summary", ghi=False)
def stock_value_summary():
	"""Σ tồn × giá vốn và số dòng lô còn hàng (mọi vùng)."""
	if not _la_nv():
		return [{"inventory_value": 0, "batch_count": 0}]
	gt, so = frappe.db.sql(f"""SELECT COALESCE(SUM(x.`ton` * COALESCE(x.`gia_von`, 0)), 0), COUNT(*) FROM {NGUON_LO_CON_TON} x
		WHERE COALESCE(x.`ton`, 0) > 0""")[0]
	return [{"inventory_value": flt(gt) if xem_gia_von(hien_tai()) else None, "batch_count": int(so)}]


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
	xem = xem_gia_von(hien_tai())
	sap = p_sap if p_sap in ("gia-tri", "so-luong") and (xem or p_sap != "gia-tri") else "ten"  # sắp theo giá trị cũng lộ giá vốn
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
			FROM {NGUON_LO_CON_TON} x WHERE x.`ton` > 0 GROUP BY x.`hang`
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
	return [{**r, **{k: (flt(r[k]) if xem or not k.endswith("_value") else None) for k in so}, "total_count": int(r.total_count),
		"units": dv.get(r.product_id)} for r in ds]


@rpc("bao_cao_ton_kho", ghi=False)
def bao_cao_ton_kho(p_tu=None, p_den=None):
	"""Báo cáo tổng hợp › Kho một lượt (`napTonKho` — src/lib/bao-cao/nap-kho.ts:87–92, GET qua `goiMotLuot`, `p_tu` = hôm nay − 89, `p_den` = hôm
	nay). nppsale (mig 204, `SET jit = off` mig 256): `jsonb_build_object('lo', …, 'dong', …)`, phần rỗng → `[]`:
	- `lo`: `batches` của NPP có `qty_on_hand > 0` (mọi vùng, KHÔNG trả vùng) {id, product_id, batch_code, qty_on_hand, unit_cost, expires_at,
	  created_at}, `ORDER BY id`. Bản Frappe = dòng cổng `batches` (§5.4: `id` = `<lô>::<vùng>`, lô ảo `~SKU::vùng` của hàng không lô, hạn trống →
	  2099-12-31) — `unit_cost` che theo `inventory.cost` như cổng (❓ §7.3 điểm 21 — nppsale không che ở hàm; giao diện đã che).
	- `dong`: dòng HĐ `status = 'posted'` có `invoice_date BETWEEN p_tu AND p_den` (gồm dòng hàng đổi — màn tự bỏ) {ngay, invoice_id, product_id,
	  unit_name, conversion_factor, quantity, is_exchange}; NULL ở một đầu kỳ → BETWEEN ra NULL → `[]`. Bản Frappe = HĐ cổng `sales_invoices`
	  (Sales Invoice docstatus 1, `is_return = 0`, `is_opening = No`, ngày = `posting_date`) + dòng cổng `sales_invoice_lines`.
	Ép kiểu `date` như Postgres trước khi đọc (chuỗi sai → 22007 / 22008). Phần lưu trữ trước ngày cắt (`NPP LS *` — BP §2.11) chưa có DocType
	(P8) nên chưa UNION.
	P6 M1 (soát theo đặc tả báo cáo §2.2 — khớp từng khoá): thêm khoá `tinh_lai_gia_von` (❓Q12 — số việc Repost Item Valuation còn chờ / đang chạy,
	MỌI ngày: giá vốn lô hiện tại đổi theo bất kỳ việc tính lại nào; 0 với người không phải NV) như `bao_cao_so_ban` — giao diện cũ bỏ qua khoá lạ."""
	from nppsale.luat.bao_cao import HET_GIO_BAO_CAO

	from .bao_cao import _chay, _ngay

	tu, den = _ngay(p_tu), _ngay(p_den)  # ép kiểu như PostgREST TRƯỚC thân hàm (22007 / 22008)
	return _chay(lambda: _bao_cao_ton_kho(tu, den), HET_GIO_BAO_CAO)  # P6 M0 — L11: 40 s, quá hạn → 57014


def _bao_cao_ton_kho(tu, den) -> dict:
	from nppsale.cong.truy_van import doc

	from .bao_cao import KHOA_TINH_LAI, _la_nv, tinh_lai_gia_von

	nc = hien_tai()
	lo = doc({"bang": "batches", "select": "id, product_id, batch_code, qty_on_hand, unit_cost, expires_at, created_at",
		"loc": [{"op": "gt", "cot": "qty_on_hand", "gt": 0}], "thu_tu": [{"cot": "id", "tang": True}]}, nc)["data"] or []
	dong = []
	if tu is not None and den is not None:  # kỳ ngược: hai vế lọc ngày tự ra rỗng như BETWEEN ngược
		for hd in doc({"bang": "sales_invoices", "select": "id, invoice_date, lines:sales_invoice_lines(product_id, unit_name, conversion_factor, "
				"quantity, is_exchange)", "loc": [{"op": "eq", "cot": "status", "gt": "posted"}, {"op": "gte", "cot": "invoice_date",
				"gt": tu.isoformat()}, {"op": "lte", "cot": "invoice_date", "gt": den.isoformat()}]}, nc)["data"] or []:
			for d in hd.get("lines") or []:
				dong.append({"ngay": hd["invoice_date"], "invoice_id": hd["id"], "product_id": d["product_id"], "unit_name": d["unit_name"],
					"conversion_factor": d["conversion_factor"], "quantity": d["quantity"], "is_exchange": d["is_exchange"]})
	return {"lo": lo, "dong": dong, KHOA_TINH_LAI: tinh_lai_gia_von() if _la_nv(nc) else 0}
