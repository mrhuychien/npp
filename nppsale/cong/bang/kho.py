"""Bảng KHO của nppsale trên cổng — phần ĐỌC (blueprint 02 §2.11, §5.12, sổ đăng ký cổng dòng `batches`).

batches: một dòng nppsale = một lô ở MỘT vùng → cổng dựng theo cặp (Batch × kho NPP) có phát sinh, `id` = `<lô>::sale` / `<lô>::date`:
- tồn = Σ `Serial and Batch Entry.qty` của gói lô chưa huỷ tại kho (đơn vị cơ sở) — không lọc SLE.batch_no (trống ở dòng có gói lô);
- nhập = Σ phần dương tại kho; giá vốn lô = Σ stock_value_difference / Σ qty các dòng NHẬP của lô (bình quân trong lô), lô rỗng →
  `npp_gia_von_lo_rong`;
- lô chưa phát sinh → một dòng tồn 0 ở `npp_kho_tao` (mặc định kho bán);
- hàng KHÔNG lô (câu 14 B) → "lô ảo" mỗi (mặt hàng × kho) từ Bin: `~<mã hàng>::<vùng>`, mã lô "—", hạn 2099-12-31, tồn = Bin.actual_qty
  (âm được khi cho bán vượt tồn), giá vốn = Bin.valuation_rate.
Hạn trống → 2099-12-31 (quy ước "không hạn" của giao diện, src/lib/pos/load.ts). RLS "Org members can view batches" (mig 002): mọi NV;
`unit_cost` chỉ người được xem giá vốn (`xemDuocGiaVon`) — người khác đọc ra NULL.
Ghi (lô rỗng, đổi mã / hạn / vị trí / vùng — trigger mig 170) dựng ở bước kho (P4); hiện từ chối như RLS.
"""
from __future__ import annotations

from ..dang_ky import Bang, QuanHe, dang_ky
from ..ngu_canh import xem_gia_von
from ._chung import c, co_cot, org, rls_moi_nv

KHO = ("(SELECT s.`value` AS kho, 'sale' AS vung FROM `tabSingles` s WHERE s.`doctype` = 'NPP Cai Dat' AND s.`field` = 'kho_ban' "
	"UNION ALL SELECT s.`value`, 'date' FROM `tabSingles` s WHERE s.`doctype` = 'NPP Cai Dat' AND s.`field` = 'kho_can_date')")
KHONG_HAN = "2099-12-31"

_GOI = ("JOIN `tabSerial and Batch Bundle` sb ON sb.`name` = e.`parent` AND sb.`docstatus` = 1 AND sb.`is_cancelled` = 0")
_DONG = "e.`is_cancelled` = 0 AND IFNULL(e.`batch_no`, '') != ''"

NGUON_LO = f"""(
	SELECT CONCAT(t.`lo`, '::', t.`vung`) AS `name`, t.`lo`, t.`vung`, t.`ton`, t.`nhap`, b.`item` AS `hang`, b.`name` AS `ma_lo`,
		b.`manufacturing_date`, b.`expiry_date`, b.`npp_vi_tri`, b.`disabled`, b.`npp_chuyen_vung_luc`, b.`npp_chuyen_vung_boi`,
		b.`npp_ngay_nhap`, b.`creation`, b.`npp_tim_kd`,
		COALESCE(gv.`gia`, b.`npp_gia_von_lo_rong`, 0) AS `gia_von`
	FROM (
		SELECT e.`batch_no` AS `lo`, z.`vung`, SUM(e.`qty`) AS `ton`, SUM(GREATEST(e.`qty`, 0)) AS `nhap`
		FROM `tabSerial and Batch Entry` e {_GOI} JOIN {KHO} z ON z.`kho` = e.`warehouse`
		WHERE {_DONG}
		GROUP BY e.`batch_no`, z.`vung`
		UNION ALL
		SELECT b0.`name`, z.`vung`, 0, 0
		FROM `tabBatch` b0 JOIN {KHO} z ON z.`kho` = COALESCE(NULLIF(b0.`npp_kho_tao`, ''),
			(SELECT s.`value` FROM `tabSingles` s WHERE s.`doctype` = 'NPP Cai Dat' AND s.`field` = 'kho_ban'))
		WHERE NOT EXISTS (SELECT 1 FROM `tabSerial and Batch Entry` e {_GOI} WHERE {_DONG} AND e.`batch_no` = b0.`name`)
	) t
	JOIN `tabBatch` b ON b.`name` = t.`lo`
	LEFT JOIN (
		SELECT e.`batch_no`, SUM(e.`stock_value_difference`) / NULLIF(SUM(e.`qty`), 0) AS `gia`
		FROM `tabSerial and Batch Entry` e {_GOI}
		WHERE {_DONG} AND e.`qty` > 0
		GROUP BY e.`batch_no`
	) gv ON gv.`batch_no` = t.`lo`
	UNION ALL
	SELECT CONCAT('~', bi.`item_code`, '::', z.`vung`), NULL, z.`vung`, bi.`actual_qty`, GREATEST(bi.`actual_qty`, 0), bi.`item_code`, '—',
		NULL, NULL, NULL, 0, NULL, NULL, NULL, bi.`creation`, NULL, bi.`valuation_rate`
	FROM `tabBin` bi JOIN {KHO} z ON z.`kho` = bi.`warehouse` JOIN `tabItem` it ON it.`name` = bi.`item_code` AND it.`has_batch_no` = 0
)"""


# ------------------------------------------------------------------------------------------------ giá dòng chứng từ kho (đặc tả kho_mua §10 điểm 3–5)
# MỘT luật giá vốn mỗi đơn vị CƠ SỞ cho cổng `stock_entry_lines.unit_cost`, `v_stock_movements.unit_cost` (nppsale.cong.bang.phieu_kho) và hằng báo
# cáo P6 (`nguon_dong_xuat` / `nguon_dong_nhap_lai` — đặc tả báo cáo Phụ lục A): đường lùi đọc cổng (`fetchCogsForRange`, XNT) phải ra CÙNG số với
# đường một lượt.
# - Xuất lẻ `XKL-` / chuyển kho `CKL-`: 0 — TẠM THEO nppsale (dòng phiếu giữ `unit_cost 0`, giá chỉ ở vết lấy lô → giá vốn kỳ KHÔNG tính xuất lẻ;
#   §7.3 điểm 36, §10 điểm 3 — Q9 "Giá vốn xuất lẻ / chuyển kho trên báo cáo"); sổ kho / GL vẫn giá thật.
# - Trả NCC: giá vốn LÔ từ sổ kho của dòng (|Σ stock_value_difference| / |Σ actual_qty|) — KHÔNG `PI Item.valuation_rate` (= giá trả NCC,
#   `buying_controller.py:576–660`; soát thiếu S2 / V81).
GIA_SE_XUAT_LE_0 = "('xuat_le', 'chuyen_kho', 'chuyen_date_tu_dong')"
GIA_TRA_NCC = ("IFNULL((SELECT ABS(SUM(sle.`stock_value_difference`)) / NULLIF(ABS(SUM(sle.`actual_qty`)), 0) FROM `tabStock Ledger Entry` sle "
	"WHERE sle.`voucher_type` = 'Purchase Invoice' AND sle.`voucher_no` = {p}.`name` AND sle.`voucher_detail_no` = {d}.`name` "
	"AND sle.`is_cancelled` = 0), 0)")


def gia_dong_se(se: str = "se", d: str = "d") -> str:
	return f"CASE WHEN IFNULL({se}.`npp_loai`, '') IN {GIA_SE_XUAT_LE_0} THEN 0 ELSE IFNULL({d}.`valuation_rate`, 0) END"


def gia_tra_ncc(p: str = "p", d: str = "pii") -> str:
	return GIA_TRA_NCC.format(p=p, d=d)


def nguon_dong_xuat(dk: str = "") -> str:
	"""Mỗi dòng XUẤT đã ghi sổ (đặc tả báo cáo P6 Phụ lục A-1): HĐ có kho (gồm dòng đổi), xuất kho lẻ `XKL-` (giá 0 — §10 điểm 3), xuất trả NCC
	`PTNCC-` (giá lô từ sổ kho). → (hang, sl, gia, ngay, chung_tu, loai, dong). `dk` dùng {t} cho bí danh đầu phiếu, vd
	"AND {t}.`posting_date` BETWEEN %(tu)s AND %(den)s" — chèn vào TỪNG nhánh (giữ chỉ mục `posting_date`)."""
	return f"""(
	SELECT ii.`item_code` AS hang, ABS(ii.`stock_qty`) AS sl, IFNULL(ii.`incoming_rate`, 0) AS gia, si.`posting_date` AS ngay, si.`name` AS chung_tu,
		'hoa_don' AS loai, ii.`name` AS dong
	FROM `tabSales Invoice` si
	JOIN `tabSales Invoice Item` ii ON ii.`parent` = si.`name` AND ii.`parenttype` = 'Sales Invoice'
	WHERE si.`docstatus` = 1 AND si.`is_return` = 0 AND si.`update_stock` = 1 AND IFNULL(si.`is_opening`, 'No') = 'No' {dk.replace('{t}', 'si')}
	UNION ALL
	SELECT d.`item_code`, ABS(d.`transfer_qty`), {gia_dong_se()}, se.`posting_date`, se.`name`, 'xuat_le', d.`name`
	FROM `tabStock Entry` se
	JOIN `tabStock Entry Detail` d ON d.`parent` = se.`name` AND d.`parenttype` = 'Stock Entry'
	WHERE se.`docstatus` = 1 AND se.`npp_loai` = 'xuat_le' {dk.replace('{t}', 'se')}
	UNION ALL
	SELECT pii.`item_code`, ABS(pii.`stock_qty`), {gia_tra_ncc()}, p.`posting_date`, p.`name`, 'tra_ncc', pii.`name`
	FROM `tabPurchase Invoice` p
	JOIN `tabPurchase Invoice Item` pii ON pii.`parent` = p.`name` AND pii.`parenttype` = 'Purchase Invoice'
	WHERE p.`docstatus` = 1 AND p.`is_return` = 1 AND p.`update_stock` = 1 AND p.`npp_loai` = 'tra_ncc' {dk.replace('{t}', 'p')}
)"""


def nguon_dong_nhap_lai(dk: str = "") -> str:
	"""Mỗi dòng NHẬP LẠI hàng khách trả đã ghi sổ (Phụ lục A-2), nối phiếu theo Link `npp_phieu_tra` (phiếu `NL-` và tờ ghi có có kho `HDT-`), gồm dòng
	đổi. → (pt, hang, sl, gia, ngay, chung_tu)."""
	return f"""(
	SELECT se.`npp_phieu_tra` AS pt, d.`item_code` AS hang, ABS(d.`transfer_qty`) AS sl, IFNULL(d.`valuation_rate`, 0) AS gia, se.`posting_date` AS ngay,
		se.`name` AS chung_tu
	FROM `tabStock Entry` se
	JOIN `tabStock Entry Detail` d ON d.`parent` = se.`name` AND d.`parenttype` = 'Stock Entry'
	WHERE se.`docstatus` = 1 AND se.`npp_loai` = 'nhap_lai_tra' AND IFNULL(se.`npp_phieu_tra`, '') <> '' {dk.replace('{t}', 'se')}
	UNION ALL
	SELECT si.`npp_phieu_tra`, ii.`item_code`, ABS(ii.`stock_qty`), IFNULL(ii.`incoming_rate`, 0), si.`posting_date`, si.`name`
	FROM `tabSales Invoice` si
	JOIN `tabSales Invoice Item` ii ON ii.`parent` = si.`name` AND ii.`parenttype` = 'Sales Invoice'
	WHERE si.`docstatus` = 1 AND si.`is_return` = 1 AND si.`update_stock` = 1 AND IFNULL(si.`npp_phieu_tra`, '') <> '' {dk.replace('{t}', 'si')}
)"""


# tên HẰNG của đặc tả kho_mua §10 điểm 5 / đặc tả báo cáo §2.13 (không lọc ngày) — nơi cần lọc theo ngày gọi hàm (`dk` chèn vào từng nhánh)
NGUON_DONG_XUAT = nguon_dong_xuat()
NGUON_DONG_NHAP_LAI = nguon_dong_nhap_lai()


class _ChuaGhi:
	"""Ghi lô (mig 170) dựng ở bước kho — tới lúc ấy từ chối như RLS (vai khác owner / warehouse cũng bị từ chối ở nppsale)."""

	def _tu_choi(self):
		from ..sql import LoiCong

		raise LoiCong("42501", 'new row violates row-level security policy for table "batches"', "Ghi lô dựng ở bước kho (P4).", http=403)

	def them(self, ds, nc):
		self._tu_choi()

	def sua(self, gia_tri, ids, nc):
		self._tu_choi()

	def xoa(self, ids, nc):
		self._tu_choi()


def nap():
	if not co_cot("Batch", "npp_ngay_nhap"):
		return
	dang_ky(Bang(
		ten="batches",
		nguon=NGUON_LO,
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "product_id": c("hang"), "batch_code": c("ma_lo"),
			"manufactured_at": c("manufacturing_date", "ngay"),
			"expires_at": c(f"COALESCE({{t}}.`expiry_date`, '{KHONG_HAN}')", "ngay"),
			"location": c("npp_vi_tri"), "qty_initial": c("nhap", "so"), "qty_on_hand": c("ton", "so"), "unit_cost": c("gia_von", "so"),
			# Batch tắt (huỷ phiếu nhập làm lô hết hàng — §7.3 điểm 35; đóng lô) = `status 'cancelled'` của nppsale (giá trị dùng: available / cancelled;
			# màn chọn lô lọc `eq status available`)
			"status": c("CASE WHEN IFNULL({t}.`disabled`, 0) = 1 THEN 'cancelled' ELSE 'available' END"),
			"warehouse_zone": c("vung"), "zone_moved_at": c("npp_chuyen_vung_luc", "gio"), "zone_moved_by": c("npp_chuyen_vung_boi"),
			"received_at": c("npp_ngay_nhap", "gio"), "created_at": c("creation", "gio"), "tim_kd": c("npp_tim_kd"),
		},
		quan_he=[QuanHe("products", "product_id", "id", False, ("batches_product_id_fkey", "product_id"))],
		rls=rls_moi_nv,
		ghi=_ChuaGhi(),
		an_cot={"unit_cost": xem_gia_von},
	))


try:
	nap()
except Exception:
	pass
