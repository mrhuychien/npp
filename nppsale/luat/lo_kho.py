"""Luật thuần của LÔ + KHO CẬN DATE (P4 — mốc M5; đặc tả kho_mua §2.7, §3.20, §4.6, §7.2 #7 / #27, §7.3 điểm 6 / 8 / 20 / 22 / 37) — không import
frappe; bài: nppsale.tests.test_luat_lo_kho.

1. Câu lỗi NGUYÊN VĂN của trigger `_trg_khoa_ghi_thang_lo` (mig 170 — scratchpad kho_mua/src/_trg_khoa_ghi_thang_lo.sql), của
   `refresh_warehouse_zones` (mig 166 — …/src/refresh_warehouse_zones.sql) và của ràng buộc bảng `batches` trên bản tham chiếu (RLS "Owner/Warehouse can
   manage batches", NOT NULL, CHECK `batches_warehouse_zone_check`, khoá ngoại `batches_product_id_fkey` / `stock_entry_lines_batch_id_fkey`); câu MỚI
   của bản Frappe (quyết định tạm Q9): cột lõi tự giữ, mặt hàng không lô / lô ảo, mã lô trùng (§7.3 điểm 6).
2. Thứ tự kiểm của trigger trên MỘT lệnh UPDATE (§4.6 soát thiếu S7): tồn đổi → câu "không sửa thẳng số tồn…" TRƯỚC; giá vốn đổi khi lô còn tồn (bản
   Frappe: Σ tồn MỌI kho của Batch — §7.3 điểm 37, ⚠K: nppsale xét tồn của DÒNG được sửa) → "không sửa giá vốn…"; đổi mặt hàng / đơn vị → "không đổi
   sản phẩm…"; rồi cột lõi tự giữ (ngày nhận, trạng thái, dấu chuyển vùng, lúc tạo — nppsale cho sửa, lỗ) → câu mới. So kiểu `IS DISTINCT FROM`: gửi lại
   đúng giá trị đang có thì không lỗi (màn sửa lô luôn gửi lại mã / hạn / vị trí).
3. Kho date (trigger `batches_auto_zone`, mig 028 / 138): dòng lô vùng `sale` có hạn ≤ hôm nay + ngưỡng → `date` lúc TẠO và ở MỌI lệnh UPDATE có khoá
   `expires_at` — kể cả hạn gửi lại không đổi (`BEFORE UPDATE OF expires_at` chạy khi cột có trong danh sách SET — §4.6 S7, V82a); không bao giờ tự
   `date → sale`; rà soát (`refresh_warehouse_zones`): lô CÓ TỒN ở kho bán, có hạn, hạn ≤ hôm nay + ngưỡng (lô tồn 0 không chuyển — V57). Ngày VN của
   site (⚠K nhẹ §2.5: nppsale so `CURRENT_DATE` UTC).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong
from nppsale.luat.kho_mua import NGUONG_MAC_DINH, VUNG, nguong, so, so6

BANG = "batches"

# ------------------------------------------------------------------------------------------------ 1. câu lỗi
# trigger `_trg_khoa_ghi_thang_lo` (mig 170) — P0001
TAO_LO_CO_TON = ("SO_KHO_KHOA: lô có tồn phải vào kho qua phiếu Nhập kho hoặc phiếu kiểm kê — tạo lô ở đây chỉ được tạo lô rỗng (số lượng 0).")
SUA_TON = ("SO_KHO_KHOA: không sửa thẳng số tồn của lô — lập phiếu kiểm kê để điều chỉnh (có duyệt, có thẻ kho, có ghi hao hụt).")
SUA_GIA = "SO_KHO_KHOA: không sửa giá vốn của lô đang có tồn — giá vốn đã đi vào các phiếu xuất trước đó."
DOI_HANG = "SO_KHO_KHOA: không đổi sản phẩm / đơn vị của một lô."
# câu MỚI của bản Frappe (đặc tả §4.6 — ❓ đề xuất; quyết định tạm Q9)
KHONG_SUA_TRUONG = "SO_KHO_KHOA: không sửa được trường này của lô."  # received_at / status / zone_moved_* / created_at (nppsale cho sửa — lỗ)
KHONG_LO = "SO_KHO_KHOA: mặt hàng này không quản lý theo lô."  # lõi `batch.py:158–160` "The selected item cannot have Batch"; ghi lên lô ảo
# `refresh_warehouse_zones` (mig 166) — 42501
ORG_MISMATCH_RA_SOAT = "ORG_MISMATCH: không rà kho của đơn vị khác được."
# cột bảng `batches` của nppsale (information_schema bản tham chiếu)
COT_LO = ("id", "org_id", "product_id", "batch_code", "manufactured_at", "expires_at", "location", "qty_initial", "qty_on_hand", "status",
	"created_at", "unit_cost", "warehouse_zone", "zone_moved_at", "zone_moved_by", "received_at", "tim_kd")
COT_LOI_GIU = ("received_at", "status", "zone_moved_at", "zone_moved_by", "created_at")  # lõi / app tự giữ — sửa thẳng → KHONG_SUA_TRUONG
COT_BO_QUA = ("id", "tim_kd")  # nppsale: `id` khoá chính (không đổi được ở bản Frappe — tên Batch), `tim_kd` trigger `trg_zzzz_tim_kd` tự ghi đè
KHONG_NULL = ("product_id", "batch_code", "expires_at", "qty_initial", "qty_on_hand", "warehouse_zone")  # cột NOT NULL (insert)


def loi_xoa_con_ton(ton) -> NppLoi:
	"""DELETE lô còn tồn — `%` = `OLD.qty_on_hand` numeric(18,6) (`so6`). Bản Frappe: Σ tồn MỌI kho của Batch (xoá Batch là xoá cả hai dòng
	`<lô>::sale` / `<lô>::date` — một Batch cho hai kho, ⚠K §7.2 #27)."""
	return NppLoi(f"SO_KHO_KHOA: lô còn {so6(ton)} trong kho — không xoá được. Điều chỉnh về 0 qua phiếu kiểm kê trước.")


def loi_xoa_co_so_kho() -> LoiCong:
	"""Lô đã có dòng phiếu kho trỏ tới (khoá ngoại NO ACTION `stock_entry_lines_batch_id_fkey`) — câu 23503 thô của nppsale (§7.3 điểm 20). Bản
	Frappe: Batch đã có Serial and Batch Entry (kể cả gói đã huỷ — phiếu nhập đã huỷ vẫn giữ dòng phiếu kho ở nppsale); luôn in tên khoá
	`stock_entry_lines_batch_id_fkey` (một nguồn — nppsale có thể in `stock_line_consumptions_batch_id_fkey` khi lô chỉ có vết lấy, §4.6 S7)."""
	return LoiCong("23503", 'update or delete on table "batches" violates foreign key constraint "stock_entry_lines_batch_id_fkey" on table '
		'"stock_entry_lines"', http=409)


def loi_lo_trung(ma: str) -> NppLoi:
	"""Tạo lô rỗng / đổi mã lô sang mã đã có (§7.3 điểm 6 — BP §7.1 điểm 14: Batch khoá `name`; nppsale cho trùng mã). Cùng mã với phiếu nhập (M1)
	và nhập kho tay (M4), đuôi theo màn Lô hàng — quyết định tạm Q9."""
	return NppLoi(f"LO_TRUNG_MA: Mã lô {ma} đã có trong sổ — chọn mã lô khác.")


def loi_rls() -> LoiCong:
	"""INSERT của vai ngoài owner / warehouse (RLS WITH CHECK — chạy SAU trigger BEFORE: lô có tồn báo câu trigger trước)."""
	return LoiCong("42501", f'new row violates row-level security policy for table "{BANG}"', http=403)


def loi_khong_null(cot: str) -> LoiCong:
	return LoiCong("23502", f'null value in column "{cot}" of relation "{BANG}" violates not-null constraint', http=400)


def loi_vung() -> LoiCong:
	return LoiCong("23514", f'new row for relation "{BANG}" violates check constraint "batches_warehouse_zone_check"', http=400)


def loi_hang() -> LoiCong:
	return LoiCong("23503", f'insert or update on table "{BANG}" violates foreign key constraint "batches_product_id_fkey"', http=409)


def loi_cot_la(cot: str) -> LoiCong:
	return LoiCong("PGRST204", f"Could not find the '{cot}' column of '{BANG}' in the schema cache", http=400)


# ------------------------------------------------------------------------------------------------ 2. thứ tự kiểm (trigger mig 170)
def _so_hay_none(v):
	if v is None or isinstance(v, bool):
		return v
	try:
		return so(v)
	except Exception:  # chữ không phải số: so như chữ
		return v


def khac(moi: Mapping, cu: Mapping, cot: str) -> bool:
	"""`NEW.<cot> IS DISTINCT FROM OLD.<cot>` cho cột CÓ trong tải trọng (cột vắng = giữ nguyên). Số so theo giá trị (`7` = `7.000000`; sai lệch
	≤ 5e-7 — numeric(18,6) của nppsale), NULL chỉ bằng NULL."""
	if cot not in moi:
		return False
	a, b = _so_hay_none(moi[cot]), _so_hay_none(cu.get(cot))
	if a is None or b is None:
		return (a is None) != (b is None)
	if isinstance(a, Decimal) and isinstance(b, Decimal):
		return abs(a - b) > Decimal("0.0000005")
	return a != b


def kiem_them(g: Mapping) -> None:
	"""INSERT (trigger, TRƯỚC RLS): `COALESCE(qty_on_hand, 0) <> 0 OR COALESCE(qty_initial, 0) <> 0` → TAO_LO_CO_TON."""
	for cot in ("qty_on_hand", "qty_initial"):
		v = _so_hay_none(g.get(cot))
		if v is not None and v != 0:
			raise NppLoi(TAO_LO_CO_TON)


def kiem_sua(cu: Mapping, moi: Mapping, ton_ca_lo) -> None:
	"""UPDATE một dòng lô (sau RLS — vai ngoài owner / warehouse đã bị lọc 0 dòng): `cu` = giá trị cổng hiện tại của dòng (qty_on_hand, qty_initial,
	unit_cost, product_id, org_id, cột lõi giữ…), `moi` = tải trọng đã đổi kiểu, `ton_ca_lo` = Σ tồn mọi kho của Batch (§7.3 điểm 37). Ném lỗi ĐẦU
	theo thứ tự của trigger; không lỗi → None."""
	if khac(moi, cu, "qty_on_hand") or khac(moi, cu, "qty_initial"):
		raise NppLoi(SUA_TON)
	if khac(moi, cu, "unit_cost") and so(ton_ca_lo) != 0:
		raise NppLoi(SUA_GIA)
	if khac(moi, cu, "product_id") or khac(moi, cu, "org_id"):
		raise NppLoi(DOI_HANG)
	for cot in COT_LOI_GIU:
		if khac(moi, cu, cot):
			raise NppLoi(KHONG_SUA_TRUONG)


# ------------------------------------------------------------------------------------------------ 3. kho date
def _ngay(x) -> date:
	if isinstance(x, datetime):
		return x.date()
	return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def can_date(han, hom_nay, nguong_ngay=NGUONG_MAC_DINH) -> bool:
	"""Hạn trong ngưỡng kho date: `expires_at <= CURRENT_DATE + ngưỡng` (hạn ĐÚNG BẰNG ngưỡng cũng vào — V56 +45 với ngưỡng 45). Không hạn → không."""
	if han in (None, ""):
		return False
	return _ngay(han) <= _ngay(hom_nay) + timedelta(days=nguong(nguong_ngay))


def vung_sau_sua(vung_dong: str, moi: Mapping, han_sau, hom_nay, nguong_ngay=NGUONG_MAC_DINH) -> str:
	"""Vùng của MỘT dòng lô sau lệnh UPDATE: `warehouse_zone` gửi lên (hoặc vùng hiện tại), rồi trigger `UPDATE OF expires_at` — chỉ khi tải trọng
	CÓ khoá `expires_at` (kể cả giá trị cũ): `sale` + hạn trong ngưỡng → `date`. Không bao giờ tự về `sale`."""
	v = moi.get("warehouse_zone", vung_dong) if "warehouse_zone" in moi else vung_dong
	if "expires_at" in moi and v == "sale" and can_date(han_sau, hom_nay, nguong_ngay):
		return "date"
	return v


@dataclass
class LoBan:
	ma: str  # Batch.name
	hang: str
	ton: Decimal  # tồn TẠI KHO BÁN (Σ gói lô — đơn vị cơ sở)
	han: date | str | None


def can_ra_soat(lo: Iterable[LoBan], hom_nay, nguong_ngay=NGUONG_MAC_DINH) -> list[LoBan]:
	"""`refresh_warehouse_zones`: `warehouse_zone = 'sale' AND expires_at IS NOT NULL AND expires_at <= CURRENT_DATE + ngưỡng AND qty_on_hand > 0`
	(không lọc trạng thái — lô đã đóng còn tồn cũng chuyển) → theo mã hàng rồi mã lô (thứ tự dòng của phiếu `CKL-`)."""
	ra = [x for x in lo if so(x.ton) > 0 and can_date(x.han, hom_nay, nguong_ngay)]
	return sorted(ra, key=lambda x: (x.hang, x.ma))


def vung_hop_le(v) -> str:
	"""`warehouse_zone` của tải trọng: NULL → NOT NULL 23502; ngoài {sale, date} → CHECK 23514."""
	if v is None:
		raise loi_khong_null("warehouse_zone")
	if v not in VUNG:
		raise loi_vung()
	return v


def ghi_chu_ra_soat(nguong_ngay) -> str:
	"""Ghi chú phiếu `CKL-` `chuyen_date_tu_dong` của rà soát (nppsale lật cờ tại chỗ — không có phiếu nên không có chữ để khớp)."""
	return f"Rà soát kho date: lô còn hạn không quá {nguong(nguong_ngay)} ngày tự chuyển sang kho hàng date"


def ghi_chu_doi_han(ma_lo: str, nguong_ngay) -> str:
	"""Ghi chú phiếu `CKL-` `chuyen_date_tu_dong` khi sửa hạn lô (trigger `UPDATE OF expires_at`)."""
	return f"Sửa hạn lô {ma_lo}: còn hạn không quá {nguong(nguong_ngay)} ngày — tự chuyển sang kho hàng date"


def ghi_chu_doi_vung(ma_lo: str, vung: str) -> str:
	"""Ghi chú phiếu `CKL-` `chuyen_kho` khi đổi vùng một dòng lô qua cổng (nppsale lật cột `warehouse_zone` thẳng — màn đã gỡ nút 23/09/2026)."""
	return f"Đổi vùng lô {ma_lo} sang kho {'hàng date' if vung == 'date' else 'hàng bán'}"
