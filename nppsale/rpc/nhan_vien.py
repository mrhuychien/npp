"""RPC nhân viên NGHỈ VIỆC (mig 223) — chủ nhà 02/10/2026: chưa có chứng từ thì xoá hẳn; đã có thì "Cho nghỉ việc" (khoá, ẩn khỏi ô chọn,
giữ tên trên chứng từ cũ); "khi nghỉ bàn giao khách hàng và công nợ về npp. Npp sẽ phân phối lại sau".

- so_chung_tu_nhan_vien (chỉ đọc, chủ NPP): số chứng từ trỏ tới NV theo đúng các khoá ngoại CHẶN XOÁ của nppsale (bảng `CHAN` — ánh xạ
  bảng.cột → DocType.trường; DocType chưa dựng thì bỏ qua), kèm số khách đang phụ trách, lịch tuyến, khoản nợ chưa thu.
- cho_nhan_vien_nghi (chủ NPP): khoá NV + mốc nghỉ; khách + lịch tuyến về NPP; nợ chưa thu về NPP (giữ = trống, mốc về NPP); bỏ mã QR đăng
  nhập + khoá chứng từ của NV. Nợ đã thu xong giữ tên người cũ (lịch sử).
- giao_cong_no_npp (chủ / quản lý / kế toán): nợ NPP đang giữ (đã về NPP) của một khách → NV đang làm.
"""
from __future__ import annotations

import frappe
from frappe.utils import cint, flt, now_datetime

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai
from nppsale.su_kien.cong_no import dat_nguoi_giu

from . import rpc
from .don_hang import _chu

# Khoá ngoại CHẶN XOÁ (NO ACTION / RESTRICT) tới users của nppsale → nơi tương ứng trên Frappe. `loc`: điều kiện thêm (tờ ghi có của phiếu
# trả là chứng từ của phiếu trả, không phải "hoá đơn"). Bảng nppsale chưa port (chuyến giao, lương…) thêm dòng khi DocType ra đời.
CHAN: list[tuple[str, str, str, str, dict | None]] = [
	("sales_orders", "created_by", "Sales Order", "owner", None),
	("sales_orders", "sales_user_id", "Sales Order", "npp_nhan_vien", None),
	("sales_invoices", "posted_by", "Sales Invoice", "owner", {"is_return": 0}),
	("sales_invoices", "sales_user_id", "Sales Invoice", "npp_nhan_vien", {"is_return": 0}),
	("sales_invoices", "cancelled_by", "Sales Invoice", "npp_huy_boi", {"is_return": 0}),
	("receivables", "sales_user_id", "NPP Cong No", "nhan_vien", None),
	("order_activity_log", "actor_id", "NPP Nhat Ky Don", "nguoi", None),
	("visit_logs", "sales_user_id", "NPP Ghe Tham", "nhan_vien", None),
	("customer_photos", "uploaded_by", "NPP Anh Diem Ban", "nguoi_tai", None),
	("batches", "zone_moved_by", "Batch", "npp_chuyen_vung_boi", None),
	("returns", "sales_user_id", "NPP Phieu Tra", "nhan_vien", None),
	("returns", "requested_by", "NPP Phieu Tra", "owner", None),
	("cash_receipts", "created_by", "NPP Phieu Thu", "owner", None),
	("stock_entries", "created_by", "Stock Entry", "owner", None),
	("purchase_invoices", "created_by", "Purchase Invoice", "owner", None),
	("expenses", "created_by", "NPP Phieu Chi", "owner", None),
]


def _co_truong(dt: str, truong: str) -> bool:
	if not frappe.db.exists("DocType", dt):
		return False
	return truong == "owner" or frappe.get_meta(dt).has_field(truong)


def dem_chung_tu(nv: str) -> dict:
	"""= so_chung_tu_nhan_vien phần đếm — dùng chung cho màn xoá NV (nppsale.api.nguoi_dung.xoa)."""
	tong, ct = 0, []
	for bang, cot, dt, truong, loc in CHAN:
		if not _co_truong(dt, truong):
			continue
		n = frappe.db.count(dt, {truong: nv, **(loc or {})})
		if n:
			tong += n
			ct.append({"bang": bang, "cot": cot, "so": n})
	no = frappe.db.sql("""SELECT COUNT(*), COALESCE(SUM(`so_tien` - IFNULL(`da_thu`, 0)), 0) FROM `tabNPP Cong No`
		WHERE `nhan_vien` = %s AND `trang_thai` != 'paid'""", nv)[0]
	return {"tong": tong, "chi_tiet": ct,
		"khach": frappe.db.sql("SELECT COUNT(DISTINCT `khach`) FROM `tabNPP Phan Cong Khach` WHERE `nhan_vien` = %s", nv)[0][0],
		"lich_tuyen": frappe.db.count("NPP Lich Tuyen", {"nhan_vien": nv}), "so_khoan_no": cint(no[0]), "tien_no": flt(no[1])}


def _chu_npp(nc) -> None:
	if nc.vai != "owner":
		raise NppLoi("KHONG_DU_QUYEN: chỉ Chủ NPP")


@rpc("so_chung_tu_nhan_vien", ghi=False)
def so_chung_tu_nhan_vien(p_user_id=None):
	_chu_npp(hien_tai())
	nv = _chu(p_user_id)
	if not nv or not frappe.db.exists("NPP Nhan Vien", nv):
		raise NppLoi("KHONG_TIM_THAY_NV")
	return dem_chung_tu(nv)


@rpc("cho_nhan_vien_nghi", ghi=True)
def cho_nhan_vien_nghi(p_user_id=None):
	nc = hien_tai()
	_chu_npp(nc)
	nv = _chu(p_user_id)
	if nv and nv == nc.user:
		raise NppLoi("TU_NGHI: không tự cho mình nghỉ việc")
	if not nv or not frappe.db.sql("SELECT `name` FROM `tabNPP Nhan Vien` WHERE `name` = %s FOR UPDATE", nv):
		raise NppLoi("KHONG_TIM_THAY_NV")
	doc = frappe.get_doc("NPP Nhan Vien", nv)
	if doc.vai == "owner":
		raise NppLoi("NGHI_CHU_NPP: không cho Chủ NPP nghỉ việc")
	doc.dang_hoat_dong = 0
	doc.nghi_viec_luc = doc.nghi_viec_luc or now_datetime()
	doc.nghi_viec_boi = nc.user if frappe.db.exists("NPP Nhan Vien", nc.user) else None
	# mã QR đăng nhập (= qr_login_tokens của NV)
	for t in ("qr_token", "qr_token_bam", "qr_cap_luc"):
		if doc.meta.has_field(t):
			doc.set(t, None)
	doc.flags.ignore_permissions = True
	doc.save()
	# khách + lịch tuyến về NPP (không ai phụ trách) — NPP phân lại sau
	khach = frappe.db.sql("SELECT COUNT(DISTINCT `khach`) FROM `tabNPP Phan Cong Khach` WHERE `nhan_vien` = %s", nv)[0][0]
	for ten in frappe.get_all("NPP Phan Cong Khach", filters={"nhan_vien": nv}, pluck="name"):
		frappe.delete_doc("NPP Phan Cong Khach", ten, ignore_permissions=True, force=True)
	tuyen = 0
	for ten in frappe.get_all("NPP Lich Tuyen", filters={"nhan_vien": nv}, pluck="name"):
		frappe.delete_doc("NPP Lich Tuyen", ten, ignore_permissions=True, force=True)
		tuyen += 1
	# nợ chưa thu về NPP (chế độ giao nợ: người giữ trống + mốc về NPP); nợ đã thu xong giữ tên người cũ
	bay_gio = now_datetime()
	so_no, tien = 0, 0.0
	for r in frappe.get_all("NPP Cong No", filters={"nhan_vien": nv, "trang_thai": ("!=", "paid")}, fields=["name", "so_tien", "da_thu"]):
		dat_nguoi_giu(r.name, None, bay_gio)
		so_no += 1
		tien += flt(r.so_tien) - flt(r.da_thu)
	for ten in frappe.get_all("NPP Khoa Chung Tu", filters={"nguoi_khoa": nv}, pluck="name"):
		frappe.delete_doc("NPP Khoa Chung Tu", ten, ignore_permissions=True, force=True)
	return {"khach": cint(khach), "lich_tuyen": tuyen, "so_khoan_no": so_no, "tien_no": tien}


@rpc("giao_cong_no_npp", ghi=True)
def giao_cong_no_npp(p_customer_id=None, p_user_id=None):
	nc = hien_tai()
	if nc.vai not in ("owner", "manager", "accountant"):
		raise NppLoi("KHONG_DU_QUYEN")
	nv = _chu(p_user_id)
	x = frappe.db.get_value("NPP Nhan Vien", nv, ["dang_hoat_dong", "nghi_viec_luc"], as_dict=True) if nv else None
	if not x or not cint(x.dang_hoat_dong) or x.nghi_viec_luc:
		raise NppLoi("NV_KHONG_HOP_LE: nhân viên đã nghỉ / bị khoá")
	so_no, tien = 0, 0.0
	for r in frappe.get_all("NPP Cong No", filters={"khach_hang": _chu(p_customer_id), "ve_npp_luc": ("is", "set"),
			"trang_thai": ("!=", "paid")}, fields=["name", "so_tien", "da_thu"]):
		dat_nguoi_giu(r.name, nv, None)
		so_no += 1
		tien += flt(r.so_tien) - flt(r.da_thu)
	return {"so_khoan_no": so_no, "tien_no": tien}
