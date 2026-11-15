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
			"status": c("CASE WHEN IFNULL({t}.`disabled`, 0) = 1 THEN 'disabled' ELSE 'available' END"),
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
