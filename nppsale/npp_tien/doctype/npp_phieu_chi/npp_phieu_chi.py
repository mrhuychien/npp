# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Phiếu chi chi phí (= `expenses` của nppsale — blueprint 02 §4.5 `NPP Phieu Chi`). Không submit.

P4 (mốc M6) dựng DocType + phần HAO HỤT KIỂM KÊ: `post_stock_adjustment` lập phiếu nguồn `stocktake` (`nguon_loai`, `kiem_ke`, `chung_tu_kho` = phiếu
xuất `DCK-`) — chi phí đã nằm trong bút toán của phiếu xuất điều chỉnh nên KHÔNG có JE. Phiếu nguồn kiểm kê khoá số tiền (blueprint 02 §7.1 điểm 18,
đặc tả kho_mua §7.3 điểm 15 — đề xuất, quyết định tạm Q9): chỉ sửa được diễn giải / số tham chiếu (+ phần trả tiền — chưa có đường lập, P7), không
đổi tiền / danh mục / ngày / nguồn, không xoá — nppsale cho sửa tay như mọi phiếu chi (RLS mig 016) làm lãi lỗ lệch phần kho đã trừ.
Đường lập / sửa / xoá phiếu chi TAY (`luu_phieu_chi` / `xoa_phieu_chi` + cổng `expenses`) thuộc đặc tả chi phí P7 (đặc tả kho_mua §0.1).
"""
from __future__ import annotations

from frappe.model.document import Document

from nppsale.cong.loi import NppLoi
from nppsale.luat import kiem_ke as KK


class NPPPhieuChi(Document):
	def validate(self):
		if self.is_new():
			return
		cu = self.get_doc_before_save()
		if cu is None or cu.get("nguon_loai") != KK.NGUON_KIEM_KE or self.flags.get("npp_sua_phieu_kiem_ke"):
			return
		for f in KK.TRUONG_KHOA_PHIEU_CHI:
			if self.has_value_changed(f):
				raise NppLoi(KK.loi_phieu_chi_khoa(cu.get("kiem_ke")))

	def on_trash(self):
		if self.nguon_loai == KK.NGUON_KIEM_KE and not self.flags.get("npp_sua_phieu_kiem_ke"):
			raise NppLoi(KK.loi_phieu_chi_khong_xoa(self.kiem_ke))
