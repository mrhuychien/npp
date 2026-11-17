"""Luật thuần của PHIẾU TRẢ NCC (P4 — mốc M2; đặc tả kho_mua §3.7–§3.9, §4.3, §7.3 điểm 2 / 11 / 23 / 26) — không import frappe;
bài: nppsale.tests.test_luat_tra_ncc. Tiền (công thức chung với phiếu nhập, đảo dấu ở tờ Frappe), chọn lô hạn cũ trước, định dạng số ở
nppsale/luat/kho_mua.py — tệp này chỉ thêm phần riêng của phiếu trả NCC:

1. Câu lỗi nguyên văn của ba hàm nppsale (`complete_supplier_return` bản mig 228 trên thân 222 ← 146 ← 071, `cancel_supplier_return` mig 235,
   `khoi_phuc_phieu_tra_ncc` mig 241) — so TỪNG KÝ TỰ ở bài vàng (§2.5). `INSUFFICIENT_STOCK |` giữ cả dấu `|`: giao diện tách theo nó
   (`friendlyReturnError`, TS src/lib/purchasing/return-form.ts:223–232).
2. Cổng ghi nháp chặn dòng mà Purchase Invoice trả độc lập không biểu diễn được (§7.3 điểm 23 — đề xuất): SL ≤ 0 (lõi từ chối "'0' qty Items are
   not allowed", đo M0), giá / giảm âm, tiền dòng âm (giảm > tiền hàng) và tiền dòng BẰNG 0 — lõi ghi đè `rate ≤ 0` của tờ trả độc lập bằng giá vốn
   (`buying_controller.py:224–242` `set_rate_for_standalone_debit_note`, chạy cả lúc lưu nháp — đo M2: dòng giá 0 thành 1.066,6667 đ/hộp).
   nppsale máy chủ nhận cả bốn loại dòng (K12 — dòng SL ≤ 0 bỏ phần kho, vẫn cộng tiền).
3. Kết quả `khoi_phuc_phieu_tra_ncc` (jsonb {id, trang_thai, da_khoi_phuc[, ly_do]} — KHÔNG có `so_lo` như phiếu nhập).
"""
from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from nppsale.cong.loi import NppLoi
from nppsale.luat.kho_mua import (
	loi_dong_gia,
	loi_dong_so_luong,
	loi_dong_tien_am,
	so,
	so6,
	so_pg,
	so_tich,
	tien_dong,
)

LOAI = "tra_ncc"  # Purchase Invoice.npp_loai
KHONG_TON_TAI = "PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu trả NCC này."
KHONG_CO_HANG = "PHIEU_KHONG_CO_HANG: Phiếu chưa có dòng hàng nào."
# cổng đổi trạng thái / đụng phiếu đã gửi / đã huỷ (§4.3 — đề xuất; nppsale không có lỗi này: RLS cho ghi thẳng mọi cột, K25)
USE_RPC = "USE_RPC: dùng nút Gửi phiếu / Huỷ phiếu / Khôi phục"
# `sua_phieu_tra_ncc` trên phiếu đã huỷ: chính câu POS / màn sửa của nppsale tự báo trước khi ghi (TS src/lib/pos/save.ts:582–584) — máy chủ
# nppsale không có (mã mới, quyết định tạm Q9)
DA_HUY_KHONG_SUA = ("PHIEU_DA_HUY: Phiếu trả NCC này đã huỷ — không sửa được. Khôi phục phiếu ở màn chi tiết trước, hoặc lập phiếu mới.")
LY_DO_SUA = "Sửa phiếu — lập lại"  # p_reason của màn sửa `/purchase-returns/[id]/edit` (POS gửi 'Sửa phiếu từ POS — lập lại')
GHI_CHU_VUOT_TON = "Xuất vượt tồn (đơn vị cho bán vượt tồn kho)"  # dòng phiếu kho không lô của nppsale (mig 222) — chỉ để dẫn chiếu
DV_CO_SO_TRONG = "đv cơ sở"


def loi_khong_con_nhap(trang_thai: str) -> NppLoi:
	"""`complete_supplier_return` bước 5 (thực tế chỉ `cancelled`)."""
	return NppLoi(f'PHIEU_KHONG_CON_NHAP: Phiếu đang ở trạng thái "{trang_thai}" — chỉ phiếu nháp mới gửi được.')


def vung_kia(vung: str) -> str:
	"""`CASE WHEN v_zone = 'sale' THEN 'date' ELSE 'sale' END` — vùng NULL / lạ cũng ra `sale` như nppsale."""
	return "date" if vung == "sale" else "sale"


def ten_vung(vung: str) -> str:
	"""Tên vùng trong câu thiếu tồn: `CASE WHEN … = 'date' THEN 'hàng date' ELSE 'hàng bán' END`."""
	return "hàng date" if vung == "date" else "hàng bán"


def con_in(co_dong: bool, ton) -> str:
	""""còn %" của câu thiếu tồn = `COALESCE(SUM(qty_on_hand), 0)` các lô `available` của mặt hàng ở vùng: có dòng lô → numeric(18,6) (`0.000000`,
	`100.000000`); không dòng nào → `0` (đã chạy K02). Frappe: "có dòng" = mặt hàng có dòng ở cổng `batches` tại kho ấy (lô không tắt — kể cả lô đã
	hết hàng); hàng không lô: có Bin (§3.7 Frappe bước 6)."""
	return so6(ton) if co_dong else "0"


def loi_thieu_ton(ten: str | None, dv: str | None, sl, he_so, vung: str, con_vung: tuple, vung_khac: str, con_khac: tuple,
		ma_hang: str | None = None) -> NppLoi:
	"""`complete_supplier_return` bước 13: `INSUFFICIENT_STOCK | % (%): cần %, kho % còn %, kho % còn %` — tên (thiếu → mã hàng), đơn vị CƠ SỞ
	(thiếu → `đv cơ sở`), cần = SL × hệ số CẢ DÒNG (in theo scale tích — `20`, `15.0`, `12.0`), còn = sau khi đã trừ phần các dòng trước + dòng này
	lấy trong lượt (§7.3 điểm 26 — chép y nguyên: vùng phiếu gần như luôn `0.000000`). `con_*` = (có dòng, tồn)."""
	return NppLoi(f"INSUFFICIENT_STOCK | {ten or ma_hang} ({dv or DV_CO_SO_TRONG}): cần {so_tich(sl, he_so)}, kho {ten_vung(vung)} còn "
		f"{con_in(*con_vung)}, kho {ten_vung(vung_khac)} còn {con_in(*con_khac)}")


def loi_da_can_tru(da_tra) -> NppLoi:
	"""`cancel_supplier_return` bước 6: khoản giảm công nợ đã được cấn trừ (`payables.paid` ≠ 0 — số thô của numeric, vd `-30000`)."""
	return NppLoi(f"DA_CAN_TRU: Khoản giảm công nợ của phiếu này đã được cấn trừ ({so_pg(da_tra)}). Gỡ phần cấn trừ trước rồi mới huỷ phiếu.")


def loi_dong_tien_0(stt: int) -> NppLoi:
	"""Dòng tiền BẰNG 0 (giá 0 / giảm đúng bằng tiền hàng) — Purchase Invoice trả độc lập không giữ được `rate` 0 (lõi ghi đè bằng giá vốn). Mã
	của `sua_phieu_nhap`, câu mới — quyết định tạm Q9 (§7.3 điểm 23)."""
	return NppLoi(f"GIA_KHONG_HOP_LE: Dòng {stt} có tiền hàng bằng 0 — phiếu trả NCC phải có tiền trả lớn hơn 0.")


def kiem_dong_tra(dong: Iterable) -> None:
	"""Cổng ghi nháp phiếu trả NCC (§7.3 điểm 23): từng dòng theo thứ tự trên phiếu — SL ≤ 0 / hệ số ≤ 0 → `SO_LUONG_KHONG_HOP_LE`; giá / giảm
	âm → `GIA_KHONG_HOP_LE` (giá / giảm âm); tiền dòng âm → `GIA_KHONG_HOP_LE` (giảm lớn hơn tiền hàng); tiền dòng 0 → `GIA_KHONG_HOP_LE` (tiền 0);
	dừng ở lỗi đầu. `dong`: (SL dương như cổng, hệ số, đơn giá, giảm dòng)."""
	for stt, (sl, hs, gia, giam) in enumerate(dong, 1):
		if so(sl) <= 0 or so(hs if hs is not None else 1) <= 0:
			raise loi_dong_so_luong(stt)
		if so(gia) < 0 or so(giam) < 0:
			raise loi_dong_gia(stt)
		t = tien_dong(sl, gia, giam)
		if t < 0:
			raise loi_dong_tien_am(stt)
		if t == 0:
			raise loi_dong_tien_0(stt)


def ket_qua_khoi_phuc(ten: str, trang_thai: str, da_khoi_phuc: bool, ly_do: str | None = None) -> dict:
	"""Trả về của `khoi_phuc_phieu_tra_ncc` (jsonb_build_object — `ly_do` chỉ có khi gửi lại hỏng; KHÔNG có `so_lo`)."""
	kq = {"id": ten, "trang_thai": trang_thai, "da_khoi_phuc": da_khoi_phuc}
	if ly_do is not None:
		kq["ly_do"] = ly_do
	return kq


def con_sau_lay(ton, da_lay) -> Decimal:
	"""Tồn còn lại của mặt hàng ở kho xuất sau phần đã lấy trong lượt (nppsale đọc `SUM(qty_on_hand)` SAU các lệnh trừ lô của chính giao dịch)."""
	return so(ton) - so(da_lay)
