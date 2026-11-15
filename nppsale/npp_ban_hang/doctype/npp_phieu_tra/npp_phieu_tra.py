"""Phiếu trả hàng của khách (nppsale `returns` + `return_lines`) — blueprint 02 §NPP Phieu Tra.

`validate` chép các trigger BEFORE đang chạy của nppsale (theo thứ tự tên như Postgres) + CHECK của hai bảng — chạy ở MỌI lần lưu, cả
RPC lẫn ghi thẳng qua cổng:
  dòng: đơn vị rỗng → đơn vị cơ sở (_trg_don_vi_rong_la_co_so), thành tiền = round(SL × giá × (1 + VAT)), trần giá trả (mig 230),
        CHECK đơn giá ≥ 0 / VAT ∈ [0, 1] / lý do; tiền trả = Σ dòng không đổi (sync_return_credit_amount);
  phiếu: CHECK lý do → INVOICE_CUSTOMER_MISMATCH (_phieu_tra_dung_khach_hoa_don) → hoàn thành tự gắn HĐ duy nhất của đơn
        (_phieu_tra_hoan_thanh_gan_hd, mig 200) → người đứng tên theo HĐ (_phieu_tra_theo_nguoi_hoa_don, mig 194) → mốc ghi có
        (sync_return_credited_at, mig 188) → chốt người đứng tên (guard_return_sales_user, mig 160) → ngày trừ doanh số (mig 192)
        → giờ sửa cuối (mig 220) → khoá tìm (mig 249).
Trigger "UPDATE OF cột" chỉ chạy khi cột ấy nằm trong lệnh ghi: nơi lưu khai `flags.cot_ghi` (tên trường) — cộng với trường đổi giá trị.
`flags.qua_rpc` = lưu từ RPC (SECURITY DEFINER / `npp.via_rpc`): bỏ phần kiểm quyền gán người của guard. Khoá ghi thẳng của trình
duyệt (mig 191 / 214 / 227) nằm ở bộ ghi cổng (nppsale.cong.bang.phieu_tra), không ở đây.
"""
from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt, get_datetime, getdate, now_datetime, nowdate

from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong
from nppsale.luat import phieu_tra as LT
from nppsale.luat.tim import khoa_tim_ds

TRUONG_SUA_LUC = ("khach_hang", "don_hang", "hoa_don", "ly_do", "ghi_chu", "ngay_tra")
TRUONG_DONG = ("mat_hang", "don_vi", "so_luong", "don_gia", "thue_suat", "hang_doi", "ly_do", "ghi_chu")


def _check(bang: str, rang_buoc: str):
	raise LoiCong("23514", f'new row for relation "{bang}" violates check constraint "{rang_buoc}"', http=400)


class NPPPhieuTra(Document):
	def validate(self):
		cu = self.get_doc_before_save()
		moi = cu is None or self.is_new()
		cot_ghi = set(self.flags.get("cot_ghi") or ())

		def cham(f: str) -> bool:
			return moi or f in cot_ghi or (cu.get(f) != self.get(f))

		# "UPDATE OF …" xét theo lệnh ghi lúc vào — các bước dưới đổi giá trị không làm trigger sau chạy thêm
		da_cham = {f: cham(f) for f in ("trang_thai", "hoa_don", "khach_hang", "don_hang", "nhan_vien", "ngay_tra")}
		# ĐẦU phiếu trước (Postgres chèn / sửa dòng returns rồi mới tới return_lines): khách–HĐ, gắn HĐ, người, mốc, guard
		if self.ly_do and self.ly_do not in LT.LY_DO:
			_check("returns", "returns_reason_check")
		self._dung_khach_hoa_don(da_cham)
		self._hoan_thanh_gan_hd(cu, da_cham)
		if any(da_cham[f] for f in ("nhan_vien", "hoa_don", "don_hang", "khach_hang")):
			self.nhan_vien = LT.nguoi_dung_ten(nv_hd=self._nv_hd(self.hoa_don), hien_tai=self.nhan_vien or None,
				nv_don=self._nv_don(), nv_hd_gan_nhat=self._nv_hd_gan_nhat())
		if da_cham["trang_thai"] or da_cham["ngay_tra"]:
			self.ghi_co_luc = LT.moc_ghi_co(trang_thai=self.trang_thai, ngay_tra=getdate(self.ngay_tra) if self.ngay_tra else None,
				moc_cu=get_datetime(self.ghi_co_luc) if self.ghi_co_luc else None,
				doi_ngay=bool(cu) and str(cu.get("ngay_tra") or "") != str(self.ngay_tra or ""), bay_gio=now_datetime(), hom_nay=getdate(nowdate()))
		if da_cham["nhan_vien"]:
			self._chot_nguoi()
		# DÒNG sau (đơn vị → trần giá theo HĐ vừa gắn → khoá ghi thẳng; tiền trả)
		self._chuan_dong(cu)
		self.ngay_tru_doanh_so = LT.ngay_tru_doanh_so(tu_sinh=bool(self.tu_sinh), trang_thai=self.trang_thai,
			ngay_hd_ghi_so=self._ngay_hd_ghi_so(), ngay_ghi_co=getdate(self.ghi_co_luc) if self.ghi_co_luc else None,
			ngay_tra=getdate(self.ngay_tra) if self.ngay_tra else None, ngay_tao=getdate(self.creation) if self.creation else getdate(nowdate()))
		if moi or any(cu.get(f) != self.get(f) for f in TRUONG_SUA_LUC) or self._dong_doi(cu):
			self.sua_luc = now_datetime()
		self.tim_kd = khoa_tim_ds(self.name)

	# ------------------------------------------------------------------------------------------------ dòng
	def _chuan_dong(self, cu):
		from nppsale.rpc.don_hang import _bang_gia_nhom, _gia_bang, _quyen

		cu_dong = {d.name: d for d in (cu.get("dong") if cu else [])}
		q = None
		for d in self.dong:
			if not (d.don_vi or "").strip():
				co_so = frappe.db.get_value("Item", d.mat_hang, "stock_uom")
				if not (co_so or "").strip():
					raise NppLoi("UNIT_MISSING: mặt hàng chưa có đơn vị cơ sở — điền đơn vị trong danh mục hàng rồi lưu lại.")
				d.don_vi = co_so
			if flt(d.don_gia) < 0:
				_check("return_lines", "return_lines_unit_price_khong_am")
			if d.thue_suat is not None and (flt(d.thue_suat) < 0 or flt(d.thue_suat) > 1):
				_check("return_lines", "return_lines_vat_rate_0_1")
			if d.ly_do and d.ly_do not in LT.LY_DO:
				_check("return_lines", "return_lines_reason_check")
			d.thanh_tien = LT.thanh_tien(d.so_luong, d.don_gia, d.thue_suat)
			# trần giá trả (mig 230): mọi lần chèn / sửa dòng có người gọi, kể cả qua RPC
			c = cu_dong.get(d.name)
			if c is not None and all(c.get(f) == d.get(f) for f in TRUONG_DONG):
				continue
			if q is None:
				from nppsale.cong.ngu_canh import hien_tai

				q = _quyen(hien_tai())
			gia_cu = c.don_gia if c is not None and c.mat_hang == d.mat_hang and c.don_vi == d.don_vi else None
			ref = self._gia_da_ban(d.mat_hang, d.don_vi)
			if ref is None:
				ref = _gia_bang(d.mat_hang, d.don_vi, _bang_gia_nhom(self.khach_hang) if self.khach_hang else None)
			LT.kiem_gia_tra(d.don_gia, q=q, gia_tham_chieu=ref, la_doi=bool(d.hang_doi), gia_cu=gia_cu)
			if self.flags.get("kiem_dong_sau"):  # ghi thẳng: khoá phiếu tự sinh / khoá Nháp chạy sau trần giá của TỪNG dòng
				self.flags.kiem_dong_sau()
		if self.flags.get("kiem_dong_sau") and set(cu_dong) - {d.name for d in self.dong}:
			self.flags.kiem_dong_sau()  # xoá dòng: BEFORE DELETE của return_lines
		# credit_note_amount chỉ tính lại khi dòng đổi (trigger trên return_lines) — ghi thẳng tiền của phiếu nháp thì giữ
		if cu is None or self._dong_doi(cu):
			self.tien_tra = LT.tien_tra([{"thanh_tien": d.thanh_tien, "doi": d.hang_doi} for d in self.dong])

	def _gia_da_ban(self, hang: str, don_vi: str):
		"""max(đơn giá + giảm dòng / SL) của dòng HĐ gắn cùng mặt hàng + đơn vị — giá TRƯỚC giảm dòng (mig 230)."""
		if not self.hoa_don:
			return None
		v = frappe.db.sql("""SELECT MAX(`rate` + IFNULL(`npp_giam_dong`, 0) / NULLIF(`qty`, 0)) FROM `tabSales Invoice Item`
			WHERE `parent` = %s AND `parenttype` = 'Sales Invoice' AND `item_code` = %s AND `uom` = %s""", (self.hoa_don, hang, don_vi))[0][0]
		return flt(v) if v is not None else None

	def _dong_doi(self, cu) -> bool:
		if cu is None:
			return True
		a = [tuple(d.get(f) for f in ("name", *TRUONG_DONG)) for d in cu.get("dong") or []]
		b = [tuple(d.get(f) for f in ("name", *TRUONG_DONG)) for d in self.dong]
		return a != b

	# ------------------------------------------------------------------------------------------------ phiếu
	def _dung_khach_hoa_don(self, da_cham):
		if not (da_cham["hoa_don"] or da_cham["khach_hang"]) or not self.hoa_don or self.trang_thai == "cancelled":
			return
		kh = frappe.db.get_value("Sales Invoice", self.hoa_don, "customer")
		if kh and kh != self.khach_hang:
			raise NppLoi("INVOICE_CUSTOMER_MISMATCH: hóa đơn gốc là của khách khác — phiếu trả phải cùng khách với hóa đơn")

	def _hoan_thanh_gan_hd(self, cu, da_cham):
		"""mig 200: hoàn thành phiếu gắn đơn mà chưa gắn HĐ → tự gắn HĐ ghi sổ duy nhất của đơn (người đứng tên theo HĐ)."""
		if not da_cham["trang_thai"] or self.trang_thai != "completed" or self.hoa_don or not self.don_hang:
			return
		if cu is not None and cu.get("trang_thai") == "completed":
			return
		ds = frappe.get_all("Sales Invoice", filters={"npp_don_hang": self.don_hang, "docstatus": 1, "is_return": 0}, pluck="name",
			order_by="name asc")
		if not ds:
			raise NppLoi("RETURN_NEEDS_INVOICE: đơn gốc chưa có hóa đơn đã xuất — phiếu trả hoàn thành phải gắn với một hóa đơn đã xuất")
		if len(ds) > 1:
			raise NppLoi(f"RETURN_NEEDS_INVOICE: đơn có {len(ds)} hóa đơn đã xuất — chọn hóa đơn cho phiếu trả trước khi hoàn thành")
		self.hoa_don = ds[0]
		self.nhan_vien = self._nv_hd(ds[0]) or self.nhan_vien

	def _chot_nguoi(self):
		"""guard_return_sales_user (mig 160): trống → người đứng tên đơn, rồi người ghi nếu vai bán hàng; có → kiểm quyền gán (ghi thẳng)."""
		from nppsale.cong.ngu_canh import hien_tai

		nc = hien_tai()
		goi = nc.user if nc.vai else None
		if not self.nhan_vien:
			self.nhan_vien = LT.dien_nguoi_mac_dinh(nv_don=self._nv_don(), nguoi_goi=goi, vai_nguoi_goi=nc.vai)
			return
		vai_nv = frappe.db.get_value("NPP Nhan Vien", self.nhan_vien, "vai")
		LT.kiem_nguoi_dung_ten(nv=self.nhan_vien, nguoi_goi=goi, vai_nguoi_goi=nc.vai, qua_rpc=bool(self.flags.get("qua_rpc")),
			vai_nv=vai_nv, cung_npp=vai_nv is not None)

	def _nv_hd(self, hd: str | None) -> str | None:
		return frappe.db.get_value("Sales Invoice", hd, "npp_nhan_vien") if hd else None

	def _nv_don(self) -> str | None:
		return frappe.db.get_value("Sales Order", self.don_hang, "npp_nhan_vien") if self.don_hang else None

	def _nv_hd_gan_nhat(self) -> str | None:
		"""Người đứng tên HĐ ghi sổ gần nhất của khách (ngày HĐ, rồi giờ tạo, giảm dần)."""
		if not self.khach_hang:
			return None
		r = frappe.db.sql("""SELECT `npp_nhan_vien` FROM `tabSales Invoice` WHERE `customer` = %s AND `docstatus` = 1 AND `is_return` = 0
			AND IFNULL(`npp_nhan_vien`, '') != '' ORDER BY `posting_date` DESC, `creation` DESC LIMIT 1""", (self.khach_hang,))
		return r[0][0] if r else None

	def _ngay_hd_ghi_so(self):
		if not self.hoa_don:
			return None
		r = frappe.db.get_value("Sales Invoice", self.hoa_don, ["posting_date", "docstatus"], as_dict=True)
		return getdate(r.posting_date) if r and r.docstatus == 1 else None
