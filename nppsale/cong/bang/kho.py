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
Ghi (P4 — M5; đặc tả kho_mua §4.6, trigger mig 170 + mig 028, RLS "Owner/Warehouse can manage batches"): tạo lô RỖNG, đổi mã (`doi_ma_lo`), hạn (luật
kho date → phiếu `CKL-`), vị trí, ngày SX, vùng (`CKL-`), giá vốn lô rỗng, xoá lô rỗng chưa có sổ kho — nppsale.rpc.lo_kho; sửa / xoá theo khuôn ghi
kho (bộ ghi có `chuan_bi`: cổng đọc dòng khớp + mặt hàng → COMMIT → khoá Bin là câu đầu — nppsale.cong.api).
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

def nguon_lo(con_ton: bool = False) -> str:
	"""Nguồn (lô × vùng) của cổng `batches` và mọi chỗ đọc tồn theo lô. `con_ton=True` (P6 M0 — đặc tả báo cáo §2.2 "🔧 Hiệu năng NGUON_LO"): chỉ lô CÒN
	HÀNG — gộp gói lô của lô `Batch.batch_qty > 0` thay vì TOÀN BỘ `Serial and Batch Entry` (lõi tự giữ `batch_qty` = Σ gói lô ở mọi kho —
	`serial_batch_bundle.update_batch_qty`, gọi khi ghi sổ / huỷ chứng từ kho; lô âm bị chặn — CFD-05 — nên lô tổng 0 không dương ở kho nào), bỏ nhánh lô
	chưa phát sinh (tồn 0). Dòng có tồn > 0 GIỐNG HỆT bản đủ — chỉ dùng khi người đọc lọc `ton > 0` (`NGUON_LO_CON_TON`; cổng `batches` tự chọn khi yêu cầu
	lọc `qty_on_hand > 0` — `nguon_theo_loc`)."""
	# còn tồn: đi TỪ `tabBatch` (lô `batch_qty > 0`) sang dòng gói lô qua chỉ mục `batch_no` (`STRAIGHT_JOIN` — để `batch_no IN (…)` thì MariaDB vẫn quét
	# gần hết gói lô: chỉ nhanh ~20 %). Đo P6 M0 trên poc.local + gói lô giả (2.000 / 20.000 lô, 15 dòng / lô, 20 % còn hàng — giao dịch lui cuối):
	# stock_value_summary 183 → 62 ms (30.000 dòng gói lô), 1.655 → 616 ms (300.000); cổng `batches` lọc `gt qty_on_hand 0` 163 → 62 ms / 1.760 → 651 ms;
	# đếm lô sắp hết `/dashboard` 117 → 74 ms / 1.254 → 411 ms — cùng dòng / cùng số
	tu = ("FROM `tabBatch` b1 STRAIGHT_JOIN `tabSerial and Batch Entry` e ON e.`batch_no` = b1.`name`" if con_ton
		else "FROM `tabSerial and Batch Entry` e")
	loc_lo = " AND b1.`batch_qty` > 0" if con_ton else ""
	lo_rong = "" if con_ton else f"""
		UNION ALL
		SELECT b0.`name`, z.`vung`, 0, 0
		FROM `tabBatch` b0 JOIN {KHO} z ON z.`kho` = COALESCE(NULLIF(b0.`npp_kho_tao`, ''),
			(SELECT s.`value` FROM `tabSingles` s WHERE s.`doctype` = 'NPP Cai Dat' AND s.`field` = 'kho_ban'))
		WHERE NOT EXISTS (SELECT 1 FROM `tabSerial and Batch Entry` e {_GOI} WHERE {_DONG} AND e.`batch_no` = b0.`name`)"""
	return f"""(
	SELECT CONCAT(t.`lo`, '::', t.`vung`) AS `name`, t.`lo`, t.`vung`, t.`ton`, t.`nhap`, b.`item` AS `hang`, b.`name` AS `ma_lo`,
		b.`manufacturing_date`, b.`expiry_date`, b.`npp_vi_tri`, b.`disabled`, b.`npp_chuyen_vung_luc`, b.`npp_chuyen_vung_boi`,
		b.`npp_ngay_nhap`, b.`creation`, b.`npp_tim_kd`,
		COALESCE(gv.`gia`, b.`npp_gia_von_lo_rong`, 0) AS `gia_von`
	FROM (
		SELECT e.`batch_no` AS `lo`, z.`vung`, SUM(e.`qty`) AS `ton`, SUM(GREATEST(e.`qty`, 0)) AS `nhap`
		{tu} {_GOI} JOIN {KHO} z ON z.`kho` = e.`warehouse`
		WHERE {_DONG}{loc_lo}
		GROUP BY e.`batch_no`, z.`vung`{lo_rong}
	) t
	JOIN `tabBatch` b ON b.`name` = t.`lo`
	LEFT JOIN (
		SELECT e.`batch_no`, SUM(e.`stock_value_difference`) / NULLIF(SUM(e.`qty`), 0) AS `gia`
		{tu} {_GOI}
		WHERE {_DONG} AND e.`qty` > 0{loc_lo}
		GROUP BY e.`batch_no`
	) gv ON gv.`batch_no` = t.`lo`
	UNION ALL
	SELECT CONCAT('~', bi.`item_code`, '::', z.`vung`), NULL, z.`vung`, bi.`actual_qty`, GREATEST(bi.`actual_qty`, 0), bi.`item_code`, '—',
		NULL, NULL, NULL, 0, NULL, NULL, NULL, bi.`creation`, NULL, bi.`valuation_rate`
	FROM `tabBin` bi JOIN {KHO} z ON z.`kho` = bi.`warehouse` JOIN `tabItem` it ON it.`name` = bi.`item_code` AND it.`has_batch_no` = 0
)"""


NGUON_LO = nguon_lo()
NGUON_LO_CON_TON = nguon_lo(con_ton=True)


def nguon_theo_loc(dieu_goc: list) -> str | None:
	"""Cổng `batches`: yêu cầu lọc ở mức gốc (AND) `qty_on_hand > x` (x ≥ 0) hoặc `qty_on_hand >= x` (x > 0), không phủ định → `NGUON_LO_CON_TON` (cùng dòng
	kết quả, chỉ gộp gói lô của lô còn hàng): `bao_cao_ton_kho.lo`, màn chọn lô / tồn (`gt qty_on_hand 0`), `/dashboard` (`gt 0` + `lt 10`). Bộ lọc khác
	(kể cả trong `or(...)`) → nguồn đủ."""
	from ..loc import Dieu

	for d in dieu_goc:
		if not isinstance(d, Dieu) or d.cot != "qty_on_hand" or d.phu_dinh or d.op not in ("gt", "gte") or isinstance(d.gt, bool):
			continue
		try:
			x = float(d.gt)
		except (TypeError, ValueError):
			continue
		if (d.op == "gt" and x >= 0) or (d.op == "gte" and x > 0):
			return NGUON_LO_CON_TON
	return None


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


class GhiLo:
	"""batches: lô rỗng / sửa / xoá theo trigger mig 170 + mig 028 — nppsale.rpc.lo_kho. Có `chuan_bi` ⇒ cổng ghi theo khuôn ghi kho (đọc dòng khớp +
	mặt hàng → COMMIT → bộ ghi khoá Bin làm câu đầu — sửa hạn / vùng lập phiếu `CKL-`, xoá kiểm tồn)."""

	def chuan_bi(self, hanh_dong, gia_tri, ids, nc):
		from nppsale.rpc.lo_kho import chuan_bi_ghi

		chuan_bi_ghi(hanh_dong, gia_tri, ids, nc)

	def them(self, ds, nc):
		from nppsale.rpc.lo_kho import them_lo

		return them_lo(ds, nc)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.lo_kho import sua_lo

		return sua_lo(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.lo_kho import xoa_lo

		return xoa_lo(ids, nc)


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
		ghi=GhiLo(),
		an_cot={"unit_cost": xem_gia_von},
		nguon_theo_loc=nguon_theo_loc,
	))


try:
	nap()
except Exception:
	pass
