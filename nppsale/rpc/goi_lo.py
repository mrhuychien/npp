"""Hàm KHO dùng chung cho mọi method ghi kho — Bán hàng (P3) và Kho / Mua hàng (P4) (đặc tả kho_mua §2.1–§2.2, §2.7; blueprint 02 §4.4.0;
PoC 1c / 9). Không khai @rpc nào.

- `lap_goi_lo` / `gan_goi_lo`: gói lô (Serial and Batch Bundle) do APP lập cho MỘT dòng chứng từ — một dòng một gói, không tách dòng (PoC 1c);
  `Inward` (phiếu nhập, phiếu nhập lại `NL-`, nhập kho tay, lô đích chuyển kho…) / `Outward` (HĐ bán, xuất lẻ `XKL-`, chuyển kho `CKL-`, trả NCC).
  Dòng mang gói: `use_serial_batch_fields = 0` và KHÔNG ghi `batch_no` (nhập lô đã hết hạn qua `batch_no` → BatchExpiredError — PoC 9). Gói lập
  `do_not_submit` — lõi ghi sổ / huỷ gói theo chứng từ.
- `lo_theo_kho`: lô của MỘT mặt hàng tại MỘT kho đọc từ Serial and Batch Entry của gói lô chưa huỷ (khuôn `NGUON_LO` của cổng `batches`): tồn > 0,
  Batch không `disabled`, hạn trống = không hạn — đầu vào của `nppsale.luat.kho_mua.chon_lo_fefo` (xuất lẻ, chuyển kho, trả NCC: hạn cũ trước).
  KHÔNG dùng `get_auto_batch_nos` / `get_available_batches` của lõi: chúng loại lô hết hạn (`serial_and_batch_bundle.py:3469, 3478`) mà nppsale
  thanh lý / trả NCC được hàng quá hạn, và xếp theo `creation` chứ không theo hạn.
- `kho_cua_vung` / `vung_cua_kho` / `kho_nhan_lo`: vùng nppsale (`sale` / `date`) ↔ kho NPP (`NPP Cai Dat.kho_ban` / `kho_can_date`); kho của DÒNG
  nhập theo hạn lô và ngưỡng kho date (`batches_auto_zone` — `nppsale.luat.kho_mua.vung_nhan`).
Khoá Bin (câu đầu của giao dịch ghi kho — CFD-05): `nppsale.rpc.xuat_hang._khoa_bin`.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal

import frappe
from frappe.utils import flt, getdate, nowdate

from nppsale.luat.kho_mua import LoKho, nguong, vung_nhan


def lap_goi_lo(loai: str, voucher_type: str, hang: str, kho: str, lo: Mapping | Iterable, ngay, gio, cong_ty: str) -> str:
	"""Lập gói lô `loai` (`Inward` / `Outward`) cho MỘT dòng của `voucher_type`: `lo` = {mã lô: SL đơn vị CƠ SỞ} (hoặc [(mã lô, SL)]), SL dương
	ở cả hai chiều (lõi tự đổi dấu theo chiều). Trả tên gói (chưa ghi sổ)."""
	from erpnext.stock.serial_batch_bundle import SerialBatchCreation

	lo = dict(lo)
	if loai not in ("Inward", "Outward"):
		raise ValueError(f"loại gói lô lạ: {loai!r}")
	return SerialBatchCreation({"item_code": hang, "warehouse": kho, "posting_date": ngay, "posting_time": gio, "voucher_type": voucher_type,
		"qty": float(sum(lo.values())), "type_of_transaction": loai, "company": cong_ty, "do_not_submit": True,
		"batches": frappe._dict({m: float(sl) for m, sl in lo.items()})}).make_serial_and_batch_bundle().name


def gan_goi_lo(dong, ten_goi: str) -> None:
	"""Gắn gói lô do app lập vào dòng: lõi đọc lô từ gói, không từ `batch_no` (PoC 1c / 9)."""
	dong.serial_and_batch_bundle = ten_goi
	dong.use_serial_batch_fields = 0
	dong.batch_no = None


def lo_theo_kho(hang: str, kho: str) -> list[LoKho]:
	"""Lô còn tồn (> 0) của mặt hàng TẠI một kho, theo gói lô chưa huỷ; Batch `disabled` bị loại (≈ `status` khác `available` của nppsale —
	§7.3 điểm 35). Tồn làm tròn 6 chữ số lẻ như `numeric(18,6)` của `batches.qty_on_hand`."""
	ra = []
	for ma, ton, han, tao in frappe.db.sql("""SELECT e.`batch_no`, SUM(e.`qty`), b.`expiry_date`, b.`creation`
			FROM `tabSerial and Batch Entry` e
			JOIN `tabSerial and Batch Bundle` sb ON sb.`name` = e.`parent` AND sb.`docstatus` = 1 AND sb.`is_cancelled` = 0
			JOIN `tabBatch` b ON b.`name` = e.`batch_no`
			WHERE e.`is_cancelled` = 0 AND IFNULL(e.`batch_no`, '') != '' AND e.`warehouse` = %(kho)s AND b.`item` = %(hang)s
				AND IFNULL(b.`disabled`, 0) = 0
			GROUP BY e.`batch_no`, b.`expiry_date`, b.`creation`
			HAVING SUM(e.`qty`) > 0.0000005""", {"hang": hang, "kho": kho}):
		ra.append(LoKho(ma=ma, ton=Decimal(str(round(flt(ton), 6))), han=han, tao=tao))
	return ra


def kho_cua_vung(vung: str, cd) -> str:
	"""`sale` → kho bán, `date` → kho cận date (cổng đổi Warehouse ↔ `*_zone` — BP §4.4)."""
	return cd.kho_can_date if vung == "date" else cd.kho_ban


def vung_cua_kho(kho: str | None, cd) -> str | None:
	if not kho:
		return None
	return "date" if kho == cd.kho_can_date else "sale" if kho == cd.kho_ban else None


def kho_nhan_lo(vung_chon: str, han, cd, hom_nay=None) -> str:
	"""Kho của DÒNG nhập: vùng người chọn, lô có hạn trong ngưỡng kho date (`NPP Cai Dat.nguong_kho_date_ngay`, trống → 30) mà người chọn kho bán
	→ kho cận date ngay lúc nhập (`batches_auto_zone`, mig 028); hàng không lô / lô không hạn → kho người chọn. Ngày VN của site (⚠K nhẹ: nppsale
	so `CURRENT_DATE` UTC — §2.5)."""
	ng = cd.get("nguong") if cd.get("nguong") is not None else nguong(frappe.db.get_single_value("NPP Cai Dat", "nguong_kho_date_ngay"))
	return kho_cua_vung(vung_nhan(vung_chon, han, hom_nay or getdate(nowdate()), ng), cd)
