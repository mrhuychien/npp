"""Bảng PHIẾU KHO của nppsale trên cổng (P4 — mốc M4; đặc tả kho_mua §4.5, §4.7, §4.8, §10; blueprint 02 §5.11, §6.1):

- stock_entries ← UNION ALL các nguồn có sổ kho (BP dòng `stock_entries`): (1) Stock Entry (trừ `dieu_chinh_kiem_ke` — đi theo phiếu kiểm kê) mọi
  docstatus: Material Receipt → `import` (`IN-` nhập kho tay, `DK-…` tồn đầu kỳ, `NL-` nhập lại hàng khách trả), Material Issue → `export` (`XKL-`),
  Material Transfer → `transfer` (`CKL-`); (2) phiếu kiểm kê `NPP Kiem Ke` → `stocktake` (M6: `status` = `trang_thai`, `posted_at` = `duyet_luc`, `notes` =
  `ghi_chu`, `warehouse_zone` = `kho`; hai phiếu `DCK-` của nó không hiện riêng); (3) Sales Invoice có kho đã / thôi ghi sổ (HĐ → `export`, tờ ghi có
  `HDT-` → `import`);
  (4) Purchase Invoice phiếu nhập / trả NCC đã / thôi ghi sổ (nháp KHÔNG có phiếu kho — thiếu điều kiện này thì phiếu nhập nháp hiện thành phiếu kho
  nháp). `id` = `entry_code` = tên chứng từ (⚠K §7.2 #14 — phiếu kho của PN / PTNCC / HĐ = chính chứng từ); `status` = docstatus (0 `draft`, 1 `posted`,
  2 `cancelled`); `posted_at` = ngày + giờ ghi sổ (nháp NULL như nppsale); `notes` (§10 điểm 1 — ƯU TIÊN hơn §2.12 / §4.5): phiếu `NL-` / tờ ghi có có
  kho mang Link `npp_phieu_tra` → "Nhập lại từ phiếu trả <phiếu trả>" (giao diện nối `.in('notes', …)` khớp NGUYÊN chuỗi — `fetchReturnCosts`; XNT xếp
  "Trả về" theo tiền tố), còn lại `npp_ghi_chu` của chứng từ; `ref_order_ids` kiểu json (§10 điểm 2): [đơn của HĐ] / []; `warehouse_zone` = kho nguồn
  (xuất / chuyển) hoặc kho NGƯỜI CHỌN của phiếu nhập (`npp_kho_nhap` — dòng hạn ngắn vào kho cận date); `dest_warehouse_zone` = kho đích của chuyển kho;
  `issue_reason` = `npp_ly_do_xuat`; `tim_kd` = khoá của tên chứng từ. RLS đọc (mig 002): mọi NV của NPP; GHI (owner / warehouse — mig 002, trigger
  mig 170): nppsale.rpc.kho_tay (them_phieu / sua_phieu / xoa_phieu).
- stock_entry_lines ← dòng của các nguồn trên: `quantity` = `qty_in_transaction_uom` = SL giao dịch (dương; ⚠K §4.5: nppsale PN ghi ROUND(SL cơ sở),
  `IN-` SL cơ sở thô — màn đọc `qty_in_base_uom`), `qty_in_base_uom` = SL cơ sở, `batch_id` = `<lô>::<vùng>` khi gói lô của dòng có ĐÚNG một lô (cả
  gói đã huỷ — lõi bỏ `serial_and_batch_bundle` trên dòng khi huỷ tờ), hàng không lô ghi sổ → lô ảo `~<mã>::<vùng>` (như cổng `batches`), không thì NULL
  (⚠K: nppsale dòng xuất lẻ / chuyển kho luôn NULL, vết lấy lô ở `stock_line_consumptions`); `unit_cost` = giá vốn mỗi đơn vị cơ sở theo MỘT luật với hằng
  P6 (`nppsale.cong.bang.kho.gia_dong_se` / `gia_tra_ncc`: xuất lẻ / chuyển kho 0 — §10 điểm 3; trả NCC giá lô từ sổ kho — S2; HĐ / tờ ghi có
  `incoming_rate`; PN / nhập kho `valuation_rate`), che theo `inventory.cost` như `batches.unit_cost` (§7.3 điểm 21). Không có `created_at` (§7.3 điểm
  28 — giữ hành vi nppsale). Dòng kiểm kê (`NPP Kiem Ke Dong`): `quantity` = `qty_in_base_uom` = `qty_in_transaction_uom` = chênh CÓ DẤU, ĐV = `don_vi`,
  hệ số 1, `unit_cost` = `gia_von` (giá màn gửi — duyệt KHÔNG ghi lại, như nppsale), `batch_id` = `<lo>::<vùng của kho>` (hàng không lô có kho → lô ảo;
  dòng chưa duyệt không lô → NULL). Ghi: dòng của phiếu kho tay / kiểm kê NHÁP — nppsale.rpc.kho_tay (them_dong / sua_dong / xoa_dong) → kiểm kê:
  nppsale.rpc.kiem_ke.
- v_stock_movements ← sổ kho lõi (Stock Ledger Entry chưa huỷ — §4.7): chuyển kho tự ra hai dòng (nguồn −, đích +); đơn vị / SL giao dịch / hệ số NỐI
  dòng chứng từ qua `voucher_detail_no` (§7.3 điểm 39 — màn "+2 thùng (= +48)"); `unit_cost` cùng luật dòng phiếu kho (xuất lẻ / chuyển kho 0 như
  `sel.unit_cost` của view nppsale); `signed_qty_in_base_uom` = `actual_qty`. ⚠K (sạch hơn nppsale): không phiếu nháp, không đổi vùng hồi tố, chứng từ
  huỷ biến mất, rà soát kho date hiện thành phiếu `CKL-`.
- v_stock_balance_by_zone ← Bin hai kho (`actual_qty > 0`) — chỉ là đường lùi của bảng tồn (`ton_kho_trang` lỗi). `value` che như giá vốn.
- swap_stock_movements, purchase_orders, purchase_order_lines: KHÔNG port (§4.8 — chuyến giao bỏ, đơn mua không dùng): đọc rỗng (không 404), ghi →
  LEGACY_FLOW_REMOVED.
"""
from __future__ import annotations

from ..dang_ky import Bang, CotDef, QuanHe, dang_ky
from ..ngu_canh import xem_gia_von
from ._chung import c, co_cot, la_nv, org, rls_moi_nv
from .kho import KHO, gia_dong_se, gia_tra_ncc
from .tien import GhiDaGo

NGUOI = "CASE WHEN {o} IN ('Administrator', 'Guest') THEN NULL ELSE {o} END"
GHI_CHU_NHAP_LAI = "CONCAT('Nhập lại từ phiếu trả ', {x}.`npp_phieu_tra`)"


def _vung(kho: str) -> str:
	return f"(SELECT z.`vung` FROM {KHO} z WHERE z.`kho` = {kho} LIMIT 1)"


_NGUON_PHIEU_KHO = f"""(
	SELECT se.`name`, se.`docstatus` AS `_ds`, se.`owner`, se.`creation`, se.`posting_date`, se.`posting_time`,
		CASE se.`purpose` WHEN 'Material Issue' THEN 'export' WHEN 'Material Transfer' THEN 'transfer' ELSE 'import' END AS `loai`,
		CASE WHEN se.`npp_loai` = 'nhap_lai_tra' AND IFNULL(se.`npp_phieu_tra`, '') <> '' THEN {GHI_CHU_NHAP_LAI.format(x='se')}
			ELSE se.`npp_ghi_chu` END AS `ghi_chu`,
		se.`supplier` AS `ncc`, '[]' AS `don`, se.`npp_ly_do_xuat` AS `ly_do`,
		CASE WHEN se.`purpose` = 'Material Receipt' THEN COALESCE(NULLIF(se.`npp_kho_nhap`, ''), se.`to_warehouse`) ELSE se.`from_warehouse` END AS `kho`,
		CASE WHEN se.`purpose` = 'Material Transfer' THEN se.`to_warehouse` END AS `kho_dich`,
		COALESCE(NULLIF(se.`npp_tim_kd`, ''), LOWER(se.`name`)) AS `tim`
	FROM `tabStock Entry` se WHERE IFNULL(se.`npp_loai`, '') <> 'dieu_chinh_kiem_ke'
	UNION ALL
	SELECT si.`name`, si.`docstatus`, si.`owner`, si.`creation`, si.`posting_date`, si.`posting_time`,
		CASE WHEN si.`is_return` = 1 THEN 'import' ELSE 'export' END,
		CASE WHEN si.`is_return` = 1 AND IFNULL(si.`npp_phieu_tra`, '') <> '' THEN {GHI_CHU_NHAP_LAI.format(x='si')} ELSE si.`npp_ghi_chu` END,
		NULL, CASE WHEN IFNULL(si.`npp_don_hang`, '') <> '' THEN JSON_ARRAY(si.`npp_don_hang`) ELSE '[]' END, NULL,
		COALESCE(NULLIF(si.`set_warehouse`, ''), (SELECT ii.`warehouse` FROM `tabSales Invoice Item` ii WHERE ii.`parent` = si.`name`
			AND ii.`parenttype` = 'Sales Invoice' ORDER BY ii.`idx` LIMIT 1)), NULL, COALESCE(NULLIF(si.`npp_tim_kd`, ''), LOWER(si.`name`))
	FROM `tabSales Invoice` si WHERE si.`update_stock` = 1 AND si.`docstatus` IN (1, 2)
	UNION ALL
	SELECT p.`name`, p.`docstatus`, p.`owner`, p.`creation`, p.`posting_date`, p.`posting_time`,
		CASE WHEN p.`is_return` = 1 THEN 'export' ELSE 'import' END, p.`npp_ghi_chu`, p.`supplier`, '[]', NULL,
		COALESCE(NULLIF(p.`npp_kho_nhap`, ''), p.`set_warehouse`), NULL, COALESCE(NULLIF(p.`npp_tim_kd`, ''), LOWER(p.`name`))
	FROM `tabPurchase Invoice` p WHERE p.`update_stock` = 1 AND p.`docstatus` IN (1, 2) AND p.`npp_loai` IN ('phieu_nhap', 'tra_ncc')
	{{kiem_ke}}
)"""

KHO_BAN = "(SELECT s.`value` FROM `tabSingles` s WHERE s.`doctype` = 'NPP Cai Dat' AND s.`field` = 'kho_ban')"
# (2) phiếu kiểm kê (M6): trạng thái là trường; `posted_at` = `duyet_luc` (từ chối / huỷ: NULL như nppsale — chưa từng ghi sổ)
_PHIEU_KIEM_KE = f"""UNION ALL
	SELECT kk.`name`, CASE kk.`trang_thai` WHEN 'posted' THEN 1 WHEN 'cancelled' THEN 2 ELSE 0 END, kk.`owner`, kk.`creation`,
		DATE(kk.`duyet_luc`), TIME(kk.`duyet_luc`), 'stocktake', kk.`ghi_chu`, NULL, '[]', NULL, COALESCE(NULLIF(kk.`kho`, ''), {KHO_BAN}), NULL,
		COALESCE(NULLIF(kk.`tim_kd`, ''), LOWER(kk.`name`))
	FROM `tabNPP Kiem Ke` kk"""


def _co_kiem_ke() -> bool:
	return co_cot("NPP Kiem Ke", "trang_thai")


def nguon_phieu_kho() -> str:
	"""Nguồn `stock_entries` — nhánh phiếu kiểm kê chỉ khi `NPP Kiem Ke` đã có trên site (DocType M6)."""
	return _NGUON_PHIEU_KHO.replace("{kiem_ke}", _PHIEU_KIEM_KE if _co_kiem_ke() else "")


_NGUON_DONG_KHO = f"""(
	SELECT d.`name`, d.`parent` AS `phieu`, se.`docstatus` AS `_ds`, d.`item_code` AS `hang`, d.`uom` AS `dv`, d.`qty` AS `sl_gd`,
		d.`transfer_qty` AS `sl_cs`, d.`conversion_factor` AS `hs`, {gia_dong_se('se', 'd')} AS `gia`, d.`npp_ghi_chu` AS `ghi_chu`, d.`idx`,
		CASE WHEN se.`purpose` = 'Material Receipt' THEN d.`t_warehouse` ELSE d.`s_warehouse` END AS `kho`, NULL AS `lo_kk`, 0 AS `la_kk`
	FROM `tabStock Entry Detail` d JOIN `tabStock Entry` se ON se.`name` = d.`parent` AND d.`parenttype` = 'Stock Entry'
	WHERE IFNULL(se.`npp_loai`, '') <> 'dieu_chinh_kiem_ke'
	UNION ALL
	SELECT ii.`name`, ii.`parent`, si.`docstatus`, ii.`item_code`, ii.`uom`, ABS(ii.`qty`), ABS(ii.`stock_qty`), ii.`conversion_factor`,
		IFNULL(ii.`incoming_rate`, 0), ii.`npp_ghi_chu`, ii.`idx`, ii.`warehouse`, NULL, 0
	FROM `tabSales Invoice Item` ii JOIN `tabSales Invoice` si ON si.`name` = ii.`parent` AND ii.`parenttype` = 'Sales Invoice'
	WHERE si.`update_stock` = 1 AND si.`docstatus` IN (1, 2)
	UNION ALL
	SELECT pii.`name`, pii.`parent`, p.`docstatus`, pii.`item_code`, pii.`uom`, ABS(pii.`qty`), ABS(pii.`stock_qty`), pii.`conversion_factor`,
		CASE WHEN p.`is_return` = 1 THEN {gia_tra_ncc('p', 'pii')} ELSE IFNULL(pii.`valuation_rate`, 0) END, pii.`npp_ghi_chu`, pii.`idx`, pii.`warehouse`,
		NULL, 0
	FROM `tabPurchase Invoice Item` pii JOIN `tabPurchase Invoice` p ON p.`name` = pii.`parent` AND pii.`parenttype` = 'Purchase Invoice'
	WHERE p.`update_stock` = 1 AND p.`docstatus` IN (1, 2) AND p.`npp_loai` IN ('phieu_nhap', 'tra_ncc')
	{{kiem_ke}}
)"""
# dòng kiểm kê (M6): chênh CÓ DẤU (không ABS), hệ số 1, giá = `gia_von` màn gửi
_DONG_KIEM_KE = """UNION ALL
	SELECT kd.`name`, kd.`parent`, CASE kk.`trang_thai` WHEN 'posted' THEN 1 WHEN 'cancelled' THEN 2 ELSE 0 END, kd.`mat_hang`, kd.`don_vi`,
		kd.`chenh_lech`, kd.`chenh_lech`, 1, IFNULL(kd.`gia_von`, 0), kd.`ghi_chu`, kd.`idx`, kd.`kho`, kd.`lo`, 1
	FROM `tabNPP Kiem Ke Dong` kd JOIN `tabNPP Kiem Ke` kk ON kk.`name` = kd.`parent` AND kd.`parenttype` = 'NPP Kiem Ke'"""


def nguon_dong_kho() -> str:
	return _NGUON_DONG_KHO.replace("{kiem_ke}", _DONG_KIEM_KE if _co_kiem_ke() else "")


# lô của dòng: gói lô gắn dòng (mọi docstatus của gói — huỷ tờ thì lõi bỏ liên kết trên dòng, gói giữ `voucher_detail_no`)
LO_DONG = ("(SELECT CASE WHEN COUNT(DISTINCT e.`batch_no`) = 1 THEN MIN(e.`batch_no`) END FROM `tabSerial and Batch Bundle` b "
	"JOIN `tabSerial and Batch Entry` e ON e.`parent` = b.`name` WHERE b.`voucher_detail_no` = {t}.`name` AND IFNULL(e.`batch_no`, '') <> '')")
LO_AO = ("CASE WHEN {t}.`_ds` <> 0 AND (SELECT it.`has_batch_no` FROM `tabItem` it WHERE it.`name` = {t}.`hang`) = 0 "
	"THEN CONCAT('~', {t}.`hang`, '::', " + _vung("{t}.`kho`") + ") END")
# dòng kiểm kê: lô đã đếm / đã điền khi duyệt (`lo` + `kho`); hàng không lô có kho → lô ảo (cả nháp — dòng mang sẵn kho); chưa duyệt không lô → NULL
LO_KK = ("CASE WHEN IFNULL({t}.`lo_kk`, '') <> '' THEN CONCAT({t}.`lo_kk`, '::', " + _vung("{t}.`kho`") + ") "
	"WHEN IFNULL({t}.`kho`, '') <> '' AND (SELECT it.`has_batch_no` FROM `tabItem` it WHERE it.`name` = {t}.`hang`) = 0 "
	"THEN CONCAT('~', {t}.`hang`, '::', " + _vung("{t}.`kho`") + ") END")

NGUON_BIEN_DONG = """(
	SELECT sle.`name`, sle.`item_code` AS `hang`, sle.`warehouse` AS `kho`, sle.`posting_date`, sle.`posting_time`, sle.`creation`,
		CASE WHEN se.`npp_loai` = 'dieu_chinh_kiem_ke' THEN 'stocktake' WHEN se.`purpose` = 'Material Issue' THEN 'export'
			WHEN se.`purpose` = 'Material Transfer' THEN 'transfer' ELSE 'import' END AS `loai`,
		{ma_se} AS `ma`,
		COALESCE(d.`uom`, sle.`stock_uom`) AS `dv`, COALESCE(d.`qty`, ABS(sle.`actual_qty`)) AS `sl_gd`, COALESCE(d.`conversion_factor`, 1) AS `hs`,
		ABS(sle.`actual_qty`) AS `sl_cs`, sle.`actual_qty` AS `sl_dau`,
		CASE WHEN IFNULL(se.`npp_loai`, '') IN ('xuat_le', 'chuyen_kho', 'chuyen_date_tu_dong') THEN 0
			WHEN sle.`actual_qty` > 0 THEN IFNULL(sle.`incoming_rate`, 0)
			ELSE IFNULL(ABS(sle.`stock_value_difference` / NULLIF(sle.`actual_qty`, 0)), 0) END AS `gia`,
		'[]' AS `don`
	FROM `tabStock Ledger Entry` sle JOIN `tabStock Entry` se ON se.`name` = sle.`voucher_no`
	LEFT JOIN `tabStock Entry Detail` d ON d.`name` = sle.`voucher_detail_no`
	WHERE sle.`voucher_type` = 'Stock Entry' AND sle.`is_cancelled` = 0
	UNION ALL
	SELECT sle.`name`, sle.`item_code`, sle.`warehouse`, sle.`posting_date`, sle.`posting_time`, sle.`creation`,
		CASE WHEN sle.`actual_qty` < 0 THEN 'export' ELSE 'import' END, sle.`voucher_no`,
		COALESCE(ii.`uom`, sle.`stock_uom`), COALESCE(ABS(ii.`qty`), ABS(sle.`actual_qty`)), COALESCE(ii.`conversion_factor`, 1),
		ABS(sle.`actual_qty`), sle.`actual_qty`,
		CASE WHEN sle.`actual_qty` > 0 THEN IFNULL(sle.`incoming_rate`, 0)
			ELSE IFNULL(ABS(sle.`stock_value_difference` / NULLIF(sle.`actual_qty`, 0)), 0) END,
		CASE WHEN IFNULL(si.`npp_don_hang`, '') <> '' THEN JSON_ARRAY(si.`npp_don_hang`) ELSE '[]' END
	FROM `tabStock Ledger Entry` sle JOIN `tabSales Invoice` si ON si.`name` = sle.`voucher_no`
	LEFT JOIN `tabSales Invoice Item` ii ON ii.`name` = sle.`voucher_detail_no`
	WHERE sle.`voucher_type` = 'Sales Invoice' AND sle.`is_cancelled` = 0
	UNION ALL
	SELECT sle.`name`, sle.`item_code`, sle.`warehouse`, sle.`posting_date`, sle.`posting_time`, sle.`creation`,
		CASE WHEN sle.`actual_qty` < 0 THEN 'export' ELSE 'import' END, sle.`voucher_no`,
		COALESCE(pii.`uom`, sle.`stock_uom`), COALESCE(ABS(pii.`qty`), ABS(sle.`actual_qty`)), COALESCE(pii.`conversion_factor`, 1),
		ABS(sle.`actual_qty`), sle.`actual_qty`,
		CASE WHEN sle.`actual_qty` > 0 THEN IFNULL(sle.`incoming_rate`, 0)
			ELSE IFNULL(ABS(sle.`stock_value_difference` / NULLIF(sle.`actual_qty`, 0)), 0) END,
		'[]'
	FROM `tabStock Ledger Entry` sle LEFT JOIN `tabPurchase Invoice Item` pii ON pii.`name` = sle.`voucher_detail_no`
	WHERE sle.`voucher_type` = 'Purchase Invoice' AND sle.`is_cancelled` = 0
)"""

MA_SE_KIEM_KE = "CASE WHEN se.`npp_loai` = 'dieu_chinh_kiem_ke' THEN COALESCE(NULLIF(se.`npp_kiem_ke`, ''), se.`name`) ELSE se.`name` END"


def nguon_bien_dong() -> str:
	"""Nguồn `v_stock_movements`. Thẻ kho hiện mã phiếu kiểm kê thay mã `DCK-` (BP 02 §5.11 `npp_kiem_ke`) — trường ấy chỉ có khi `NPP Kiem Ke`
	đã dựng (M6: `thiet_lap.truong_tuy_bien.ap` bỏ Link tới DocType chưa có), trước đó mã là tên Stock Entry."""
	return NGUON_BIEN_DONG.replace("{ma_se}", MA_SE_KIEM_KE if co_cot("Stock Entry", "npp_kiem_ke") else "se.`name`")


NGUON_TON_VUNG = f"""(
	SELECT CONCAT(bi.`item_code`, '::', z.`vung`) AS `name`, bi.`item_code` AS `hang`, z.`vung`, bi.`actual_qty`, bi.`stock_value`
	FROM `tabBin` bi JOIN {KHO} z ON z.`kho` = bi.`warehouse` WHERE bi.`actual_qty` > 0
)"""


class GhiPhieuKho:
	"""stock_entries: phiếu kho NHÁP — nppsale.rpc.kho_tay."""

	def them(self, ds, nc):
		from nppsale.rpc.kho_tay import them_phieu

		return them_phieu(ds, nc)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.kho_tay import sua_phieu

		return sua_phieu(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.kho_tay import xoa_phieu

		return xoa_phieu(ids, nc)


class GhiDongKho:
	"""stock_entry_lines: dòng của phiếu kho NHÁP — nppsale.rpc.kho_tay."""

	def them(self, ds, nc):
		from nppsale.rpc.kho_tay import them_dong

		return them_dong(ds, nc)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.kho_tay import sua_dong

		return sua_dong(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.kho_tay import xoa_dong

		return xoa_dong(ids, nc)


class GhiChiDoc:
	"""View (`v_stock_*`): PostgREST trả lỗi ghi vào view không cập nhật được — cổng từ chối như RLS."""

	def _tu_choi(self, *a, **k):
		from ._chung import tu_choi

		tu_choi(self.ten)

	def __init__(self, ten):
		self.ten = ten

	them = sua = xoa = _tu_choi


def _rong(cot: dict) -> str:
	return "(SELECT " + ", ".join(f"NULL AS `{k}`" for k in cot) + " FROM DUAL WHERE 1 = 0)"


def nap():
	if not co_cot("Stock Entry", "npp_loai"):
		return
	dang_ky(Bang(
		ten="stock_entries",
		nguon=nguon_phieu_kho(),
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "entry_code": c("{t}.`name`"), "type": c("loai"),
			"created_by": c(NGUOI.format(o="{t}.`owner`")), "notes": c("ghi_chu"), "created_at": c("creation", "gio"), "supplier_id": c("ncc"),
			"status": c("CASE {t}.`_ds` WHEN 1 THEN 'posted' WHEN 2 THEN 'cancelled' ELSE 'draft' END"),
			"posted_at": c("CASE WHEN {t}.`_ds` = 0 THEN NULL ELSE TIMESTAMP({t}.`posting_date`, {t}.`posting_time`) END", "gio"),
			"ref_order_ids": c("don", "json"), "issue_reason": c("ly_do"), "warehouse_zone": c(_vung("{t}.`kho`")),
			"dest_warehouse_zone": c(_vung("{t}.`kho_dich`")), "tim_kd": c("tim"),
		},
		quan_he=[
			QuanHe("users", "created_by", "id", False, ("stock_entries_created_by_fkey", "created_by")),
			QuanHe("suppliers", "supplier_id", "id", False, ("stock_entries_supplier_id_fkey", "supplier_id")),
			QuanHe("stock_entry_lines", "id", "entry_id", True, ("stock_entry_lines_entry_id_fkey",)),
			QuanHe("payables", "id", "stock_entry_id", True, ("payables_stock_entry_id_fkey",)),
		],
		rls=rls_moi_nv,
		ghi=GhiPhieuKho(),
	))
	dang_ky(Bang(
		ten="stock_entry_lines",
		nguon=nguon_dong_kho(),
		cot={
			"id": c("{t}.`name`"), "entry_id": c("phieu"), "product_id": c("hang"),
			"batch_id": c(f"CASE WHEN {{t}}.`la_kk` = 1 THEN {LO_KK} ELSE COALESCE(CONCAT({LO_DONG}, '::', {_vung('{t}.`kho`')}), {LO_AO}) END"),
			"unit_name": c("dv"), "transaction_uom": c("dv"), "quantity": c("sl_gd", "so"), "qty_in_transaction_uom": c("sl_gd", "so"),
			"qty_in_base_uom": c("sl_cs", "so"), "conversion_factor_snapshot": c("hs", "so"), "unit_cost": c("gia", "so"), "notes": c("ghi_chu"),
		},
		quan_he=[
			QuanHe("stock_entries", "entry_id", "id", False, ("stock_entry_lines_entry_id_fkey", "entry_id")),
			QuanHe("products", "product_id", "id", False, ("stock_entry_lines_product_id_fkey", "product_id")),
			QuanHe("batches", "batch_id", "id", False, ("stock_entry_lines_batch_id_fkey", "batch_id")),
		],
		rls=rls_moi_nv,
		ghi=GhiDongKho(),
		an_cot={"unit_cost": xem_gia_von},
		thu_tu_mac_dinh=[{"cot": "entry_id"}, {"sql": "{t}.`idx`"}],  # như Postgres trả dòng theo thứ tự chèn
	))
	dang_ky(Bang(
		ten="v_stock_movements",
		nguon=nguon_bien_dong(),
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "product_id": c("hang"), "warehouse_zone": c(_vung("{t}.`kho`")),
			"posted_at": c("TIMESTAMP({t}.`posting_date`, {t}.`posting_time`)", "gio"), "created_at": c("creation", "gio"), "entry_type": c("loai"),
			"entry_status": CotDef("'posted'"), "entry_code": c("ma"), "entry_id": c("ma"), "transaction_uom": c("dv"),
			"qty_in_transaction_uom": c("sl_gd", "so"), "qty_in_base_uom": c("sl_cs", "so"), "conversion_factor": c("hs", "so"),
			"unit_cost": c("gia", "so"), "signed_qty_in_base_uom": c("sl_dau", "so"), "ref_order_ids": c("don", "json"),
		},
		quan_he=[QuanHe("products", "product_id", "id", False, ("product_id",))],
		rls=rls_moi_nv,
		ghi=GhiChiDoc("v_stock_movements"),
		an_cot={"unit_cost": xem_gia_von},
	))
	dang_ky(Bang(
		ten="v_stock_balance_by_zone",
		nguon=NGUON_TON_VUNG,
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "product_id": c("hang"), "warehouse_zone": c("vung"), "qty_in_base_uom": c("actual_qty", "so"),
			"value": c("stock_value", "so"),
		},
		quan_he=[QuanHe("products", "product_id", "id", False, ("product_id",))],
		rls=rls_moi_nv,
		ghi=GhiChiDoc("v_stock_balance_by_zone"),
		an_cot={"value": xem_gia_von},
	))
	# --------------------------------------------------------------------------------------------- không port (§4.8)
	swap = {"id": "chuoi", "org_id": "chuoi", "stock_entry_id": "chuoi", "product_id": "chuoi", "qty": "so", "unit_name": "chuoi",
		"qty_in_base_uom": "so", "reason": "chuoi", "created_at": "gio"}
	dang_ky(Bang(
		ten="swap_stock_movements", nguon=_rong(swap), cot={k: c("{t}.`" + k + "`", v) for k, v in swap.items()},
		quan_he=[QuanHe("products", "product_id", "id", False, ("swap_stock_movements_product_id_fkey", "product_id"))],
		rls=lambda nc: None if la_nv(nc) else False, ghi=GhiDaGo(),
	))
	don_mua = {"id": "chuoi", "org_id": "chuoi", "po_number": "chuoi", "supplier_id": "chuoi", "order_date": "ngay", "expected_date": "ngay",
		"status": "chuoi", "subtotal": "tien", "vat": "tien", "total": "tien", "notes": "chuoi", "created_by": "chuoi", "created_at": "gio"}
	dang_ky(Bang(
		ten="purchase_orders", nguon=_rong(don_mua), cot={k: c("{t}.`" + k + "`", v) for k, v in don_mua.items()},
		quan_he=[QuanHe("purchase_order_lines", "id", "po_id", True, ("purchase_order_lines_po_id_fkey",)),
			QuanHe("suppliers", "supplier_id", "id", False, ("purchase_orders_supplier_id_fkey", "supplier_id"))],
		rls=lambda nc: None if la_nv(nc) else False, ghi=GhiDaGo(),
	))
	dong_mua = {"id": "chuoi", "po_id": "chuoi", "product_id": "chuoi", "unit_name": "chuoi", "quantity": "so", "unit_price": "tien",
		"vat_rate": "so", "line_total": "tien", "received_qty": "so", "created_at": "gio"}
	dang_ky(Bang(
		ten="purchase_order_lines", nguon=_rong(dong_mua), cot={k: c("{t}.`" + k + "`", v) for k, v in dong_mua.items()},
		quan_he=[QuanHe("purchase_orders", "po_id", "id", False, ("purchase_order_lines_po_id_fkey", "po_id")),
			QuanHe("products", "product_id", "id", False, ("purchase_order_lines_product_id_fkey", "product_id"))],
		rls=lambda nc: None if la_nv(nc) else False, ghi=GhiDaGo(),
	))


try:
	nap()
except Exception:  # noqa: BLE001 — nạp sổ ngoài request (không có DB) thì thôi
	pass
