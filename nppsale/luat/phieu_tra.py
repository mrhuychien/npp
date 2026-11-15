"""Luật THUẦN của phiếu trả hàng (nppsale `returns` / `return_lines`) — chép các trigger / hàm đang chạy của nppsale, không import frappe:

- `thanh_tien` / `tien_tra`: line_total = round(SL × giá × (1 + VAT)) do máy chủ tính (mig 152 / 183 / 190 — bỏ số trình duyệt gửi);
  credit_note_amount = Σ line_total của dòng KHÔNG phải hàng đổi (trigger `sync_return_credit_amount`, mig 055: 0 dòng → 0).
- `kiem_gia_tra`: trần đơn giá trả theo vai (`_chot_gia_tran_dong_tra`, mig 230 — chặn "mua 100k, trả lại 150k").
- `ngay_tru_doanh_so`: `_ngay_tru_doanh_so` (mig 192 — một luật khớp công nợ: phiếu tự sinh trừ vào ngày HĐ, tự lập vào ngày hoàn thành).
- `moc_ghi_co`: `sync_return_credited_at` (mig 188 — hôm nay → giờ hiện tại; ngày khác → 12:00 giờ VN của ngày phiếu).
- `nguoi_dung_ten` / `kiem_nguoi_dung_ten`: `_nguoi_cua_phieu_tra` + `guard_return_sales_user` (mig 160 / 194).
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from nppsale.cong.loi import NppLoi

from .gia_don import QuyenGiam, lam_tron, phan_tram_vn, so_vn

LY_DO = ("damaged", "wrong_item", "near_expiry", "expired", "refused")
VAI_DUNG_TEN = ("sales", "manager", "owner")


def _d(x) -> Decimal:
	return Decimal(str(x if x is not None else 0))


def thanh_tien(sl, gia, thue) -> int:
	"""round(SL × giá × (1 + COALESCE(VAT, 0))) — numeric của Postgres, nửa xa số 0."""
	return lam_tron(_d(sl) * _d(gia) * (1 + _d(thue)))


def tien_tra(dong) -> int:
	"""Σ thành tiền các dòng không phải hàng đổi. dong: [{"sl", "gia", "thue", "doi"}] hoặc [{"thanh_tien", "doi"}]."""
	t = 0
	for d in dong or []:
		if d.get("doi"):
			continue
		t += int(d["thanh_tien"]) if d.get("thanh_tien") is not None else thanh_tien(d.get("sl"), d.get("gia"), d.get("thue"))
	return t


def kiem_gia_tra(gia, *, q: QuyenGiam, gia_tham_chieu, la_doi: bool = False, gia_cu=None):
	"""BEFORE INSERT / UPDATE trên return_lines (mig 230). gia_cu: đơn giá cũ khi SỬA dòng mà giữ nguyên mặt hàng + đơn vị (None khi dòng
	mới hoặc đổi hàng / đơn vị) — sửa dòng không nâng giá quá 1 đ thì cho qua. gia_tham_chieu: giá đã bán TRƯỚC giảm dòng trên HĐ gắn cùng
	mặt hàng + đơn vị (lấy số lớn nhất), không có thì giá bảng đúng đơn vị + nhóm giá của khách (bộ tra 4 bậc). Hàng đổi, chủ NPP /
	kế toán / người gọi không phải NV (việc nền) không kiểm; tham chiếu ≤ 0 không kiểm. Trần = round(tham chiếu × (1 + %nâng / 100)),
	dung sai 1 đ."""
	if la_doi or q.toan_quyen:
		return
	if gia_cu is not None and _d(gia) <= _d(gia_cu) + 1:
		return
	ref = _d(gia_tham_chieu)
	if ref <= 0:
		return
	tran = lam_tron(ref * (1 + _d(q.nang_gia_pct) / 100))
	if _d(gia) > tran + 1:
		raise NppLoi("RETURN_PRICE_OVER_CEILING: Giá trả {} vượt mức tối đa {} (giá tham chiếu {}, được nâng {}%).".format(
			so_vn(gia), so_vn(tran), so_vn(ref), phan_tram_vn(q.nang_gia_pct or 0)))


def ngay_tru_doanh_so(*, tu_sinh: bool, trang_thai: str, ngay_hd_ghi_so: _dt.date | None, ngay_ghi_co: _dt.date | None,
		ngay_tra: _dt.date | None, ngay_tao: _dt.date | None) -> _dt.date | None:
	"""revenue_date (mig 192). Phiếu tự sinh ở Chờ xử lý / Hoàn thành gắn HĐ → ngày HĐ nếu HĐ còn ghi sổ (huỷ → trống). Phiếu đã hoàn
	thành (tự lập) → ngày (giờ VN) của mốc ghi có, rồi ngày phiếu, rồi ngày tạo. Còn lại (nháp, huỷ…) → trống.
	ngay_hd_ghi_so: ngày HĐ gắn khi HĐ còn ghi sổ, None khi không gắn / HĐ đã huỷ."""
	if tu_sinh and trang_thai in ("submitted", "completed"):
		return ngay_hd_ghi_so
	if trang_thai in ("approved", "completed"):
		return ngay_ghi_co or ngay_tra or ngay_tao
	return None


def moc_ghi_co(*, trang_thai: str, ngay_tra: _dt.date | None, moc_cu: _dt.datetime | None, doi_ngay: bool, bay_gio: _dt.datetime,
		hom_nay: _dt.date) -> _dt.datetime | None:
	"""credited_at (mig 188), giờ địa phương VN (naive — múi giờ site). Vào Hoàn thành: ngày phiếu = hôm nay (hoặc trống) → bay_gio;
	ngày khác → 12:00 ngày ấy. Đang Hoàn thành mà đổi ngày phiếu → mốc đi theo; sửa thứ khác giữ mốc. Rời Hoàn thành → trống."""
	if trang_thai != "completed":
		return None
	moc = bay_gio if (ngay_tra is None or ngay_tra == hom_nay) else _dt.datetime.combine(ngay_tra, _dt.time(12, 0))
	if moc_cu is None or doi_ngay:
		return moc
	return moc_cu


def nguoi_dung_ten(*, nv_hd: str | None, hien_tai: str | None, nv_don: str | None, nv_hd_gan_nhat: str | None) -> str | None:
	"""_nguoi_cua_phieu_tra (mig 194): người đứng tên HĐ gắn → giá trị đang có → người đứng tên đơn → người đứng tên HĐ ghi sổ gần nhất của
	khách (ngày HĐ, rồi giờ tạo, giảm dần)."""
	return nv_hd or hien_tai or nv_don or nv_hd_gan_nhat


def dien_nguoi_mac_dinh(*, nv_don: str | None, nguoi_goi: str | None, vai_nguoi_goi: str | None) -> str | None:
	"""guard_return_sales_user, nhánh người đứng tên còn trống (sau chuỗi trên): người đứng tên đơn, rồi người ghi nếu vai bán hàng."""
	if nv_don:
		return nv_don
	if nguoi_goi and vai_nguoi_goi in VAI_DUNG_TEN:
		return nguoi_goi
	return None


def kiem_nguoi_dung_ten(*, nv: str, nguoi_goi: str | None, vai_nguoi_goi: str | None, qua_rpc: bool, vai_nv: str | None,
		cung_npp: bool):
	"""guard_return_sales_user, nhánh đã có người đứng tên (ghi thẳng — RPC tự chịu trách nhiệm, `npp.via_rpc`): đứng tên chính mình
	luôn được; người khác chỉ chủ NPP / quản lý gán, người được gán phải là NV cùng NPP vai bán hàng."""
	if qua_rpc or not nguoi_goi or nv == nguoi_goi:
		return
	if vai_nguoi_goi not in ("owner", "manager"):
		raise NppLoi("PHIEU_TRA_HO_KHONG_DUOC_PHEP: chỉ chủ nhà phân phối hoặc quản lý mới lập phiếu trả đứng tên nhân viên khác.")
	if not cung_npp or vai_nv is None:
		raise NppLoi("NHAN_VIEN_KHONG_HOP_LE: nhân viên được chọn không thuộc đơn vị này.")
	if vai_nv not in VAI_DUNG_TEN:
		raise NppLoi(f"NHAN_VIEN_KHONG_BAN_HANG: {vai_nv} không phải vai trò bán hàng, không đứng tên phiếu trả được.")
