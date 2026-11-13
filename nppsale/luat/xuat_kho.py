"""Chọn lô khi Xuất hàng (thuần) — chép `post_stock_export` của nppsale (mig 107 / 138 / 145, gọi từ `post_invoice` qua `_wf2_export_order`).

Mỗi dòng (theo thứ tự) cần `can` đơn vị CƠ SỞ: lấy lần lượt các lô còn hàng ở KHO BÁN theo ngày nhận (`received_at` = `npp_ngay_nhap`), rồi
ngày tạo, rồi mã; dòng sau thấy tồn đã bị dòng trước lấy. `near_expiry_skipped` đếm số lần lấy một lô có hạn MUỘN hơn hạn sớm nhất trong
các lô còn hàng lúc bắt đầu dòng ấy (lấy theo ngày nhận chứ không theo hạn). Thiếu hàng: báo INSUFFICIENT_STOCK — nói rõ khi phần
thiếu đang nằm ở KHO CẬN DATE; được bán vượt thì ghi nhận `short_qty`.

Số trong câu lỗi in như `numeric(18,6)` của Postgres ("10.000000").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from nppsale.cong.loi import NppLoi

HAN_KHONG = "2099-12-31"  # lô không hạn — quy ước "không hạn" của nppsale


@dataclass
class Lo:
	ma: str
	ton: Decimal
	han: str  # yyyy-mm-dd ("2099-12-31" khi không hạn)
	khoa_fifo: tuple  # (ngày nhận, ngày tạo, mã)


@dataclass
class KetQuaDong:
	lay: list[tuple[str, Decimal]] = field(default_factory=list)  # [(mã lô, SL cơ sở)]
	thieu: Decimal = Decimal(0)
	can_han: int = 0


def so6(x) -> str:
	return f"{Decimal(str(x)):.6f}"


def chon_lo(lo: list[Lo], can) -> KetQuaDong:
	"""Một dòng: lấy theo FIFO ngày nhận trên `lo` (ĐÃ trừ phần các dòng trước lấy) — sửa `ton` của các lô tại chỗ."""
	can = Decimal(str(can))
	kq = KetQuaDong()
	con = [x for x in lo if x.ton > 0]
	han_som = min((x.han or HAN_KHONG for x in con), default=None)
	for x in sorted(con, key=lambda y: y.khoa_fifo):
		if can <= 0:
			break
		lay = min(x.ton, can)
		x.ton -= lay
		can -= lay
		kq.lay.append((x.ma, lay))
		if han_som is not None and (x.han or HAN_KHONG) > han_som:
			kq.can_han += 1
	kq.thieu = max(can, Decimal(0))
	return kq


def loi_thieu_ton(thieu, ten_hang: str, ton_kho_date) -> NppLoi:
	ton_kho_date = Decimal(str(ton_kho_date or 0))
	if ton_kho_date > 0:
		return NppLoi(f'INSUFFICIENT_STOCK: thiếu {so6(thieu)} đơn vị của "{ten_hang}" ở kho bán — còn {so6(ton_kho_date)} đơn vị nhưng '
			"đang nằm ở KHO CẬN DATE, không bán được. Chuyển vùng lô hàng nếu muốn bán.")
	return NppLoi(f'INSUFFICIENT_STOCK: thiếu {so6(thieu)} đơn vị của "{ten_hang}" — ghi sổ phiếu xuất sẽ làm tồn kho âm')
