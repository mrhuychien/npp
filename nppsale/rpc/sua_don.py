"""Sửa / huỷ / xoá đơn trên Sales Order — đường ghi thẳng bảng của nppsale (applyOrderEdit: xoá dòng → sửa dòng → thêm dòng → lưu đầu
đơn, mỗi lệnh một giao dịch) và RPC cancel_order. Luật là trigger của sales_orders / sales_order_lines, chạy đúng thứ tự Postgres:

  dòng (INSERT / UPDATE): đơn vị rỗng = đơn vị cơ sở → khoá dòng đơn đã xuất (+ đã huỷ với INSERT / UPDATE) → không ghi tay "đã xuất"
     → giá trần + quyền giảm dòng (_chot_gia_dong_don: dòng KHÔNG đổi SL / giá / giảm / hàng / đơn vị thì bỏ qua) → RLS WITH CHECK
     → CHECK thuế 0..1 → khoá ngoại mặt hàng (cuối câu lệnh)
  dòng (DELETE): khoá dòng đơn đã xuất → chụp mốc giảm đơn → dòng HĐ còn hiệu lực trỏ vào → 23503
  đầu đơn (UPDATE): chuyển trạng thái (mig 124/217) → người đứng tên (153/155) → đếm lần sửa (130) → RLS WITH CHECK → lịch sử trạng thái
     → cuối giao dịch: quyền giảm cả đơn, chỉ khi giảm TĂNG so với giảm đơn trước lần sửa. nppsale lưu subtotal do màn hình ghi nên
     phải chụp mốc (giam_don_goc) lúc dòng đầu tiên đổi; ở đây lưu PHẦN GIẢM (npp_giam_gia_don) — giảm đơn hiện tại trước lần lưu đầu
     đơn luôn bằng mốc ấy (dòng đổi không đụng phần giảm), nên không cần trường mốc (bài vàng sua_don_mau.json khớp cả hai cách)
  đầu đơn (DELETE): RLS (chủ / quản lý: nháp hoặc đã huỷ, chưa từng xuất HĐ; NVBH: nháp của mình) → gỡ ghé thăm → HĐ trỏ vào → 23503

UPDATE / DELETE chỉ chạm dòng người gọi được ghi (RLS USING) — dòng không được ghi thì lặng lẽ bỏ qua như Postgres (0 dòng, không lỗi).
"""
from __future__ import annotations

import frappe
from frappe.utils import flt, now_datetime

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import co_quyen, hien_tai
from nppsale.cong.sql import LoiCong
from nppsale.luat import gia_don as L
from nppsale.npp_he_thong.doctype.npp_nhat_ky_don.npp_nhat_ky_don import ghi_nhat_ky_don
from nppsale.npp_he_thong.doctype.npp_thong_bao.npp_thong_bao import gui_thong_bao
from nppsale.su_kien.san_pham import GIA_CHUAN
from nppsale.thiet_lap.ban_hang import cai_dat_ban, mau_thue_dong

from . import rpc
from .don_hang import (
	TRANG_THAI,
	_bang_gia_nhom,
	_chu,
	_dam_bao_uom,
	_don_vi_rong,
	_dong_so,
	_gia_bang,
	_khoa_dong_theo_trang_thai,
	_kiem_nguoi_dung_ten,
	_quyen,
	_rls,
	_so,
)

VAI_QUAN_TRI_DON = ("owner", "manager", "warehouse")
CHUYEN = {  # check_order_status_transition (mig 124 / 217)
	"draft": ("submitted", "cancelled"),
	"submitted": ("partially_invoiced", "completed", "cancelled", "draft"),
	"partially_invoiced": ("completed", "closed", "submitted"),
	"completed": ("partially_invoiced", "submitted"),
	"closed": ("partially_invoiced", "submitted", "completed"),
}
_COT_DONG = {"product_id": "hang", "unit_name": "don_vi", "quantity": "sl", "unit_price": "gia", "line_discount": "giam",
	"conversion_factor": "he_so", "note": "ghi_chu", "vat_rate": "thue"}
_COT_DONG_BO_QUA = {"id", "line_total", "batch_id", "sort_order", "created_at", "org_id"}


def _tt(so) -> str:
	return so.get("npp_trang_thai") or "draft"


def _don(ten: str, cache: dict):
	if ten not in cache:
		cache[ten] = frappe.get_doc("Sales Order", ten) if ten and frappe.db.exists("Sales Order", ten) else None
	return cache[ten]


def _ghi_duoc_dong(nc, so) -> bool:
	"""RLS ALL của sales_order_lines (USING = WITH CHECK): owner / manager / warehouse — đơn chưa 'completed'; sales — đơn của mình
	đang draft / submitted."""
	if nc.bo_qua_rls:
		return True
	if nc.vai in VAI_QUAN_TRI_DON:
		return _tt(so) != "completed"
	return nc.vai == "sales" and so.npp_nhan_vien == nc.user and _tt(so) in ("draft", "submitted")


def _subtotal_cua(so) -> float:
	return flt(so.net_total) - flt(so.npp_giam_gia_don)


def _giam_hien_tai(so) -> int:
	return L.giam_don_hien_tai([(r.qty, r.rate) for r in so.items], _subtotal_cua(so))




def _dong_cua(r) -> dict:
	return {"hang": r.item_code, "don_vi": r.uom, "sl": flt(r.qty), "gia": flt(r.rate), "giam": flt(r.npp_giam_dong),
		"he_so": flt(r.conversion_factor), "ghi_chu": r.additional_notes or None, "thue": r.npp_thue_suat}


def _kiem_thue(d: dict):
	"""CHECK sales_order_lines_vat_rate_check — sau trigger + RLS."""
	t = d.get("thue")
	if t is None:
		return
	try:
		x = float(t)
	except (TypeError, ValueError):
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{t}"') from None
	if x < 0 or x > 1:
		raise LoiCong("23514", 'new row for relation "sales_order_lines" violates check constraint "sales_order_lines_vat_rate_check"')
	d["thue"] = x


def _kiem_hang_ton_tai(ds: list[dict]):
	for d in ds:
		if not d.get("hang") or not frappe.db.exists("Item", d["hang"]):
			raise LoiCong("23503", 'insert or update on table "sales_order_lines" violates foreign key constraint '
				'"sales_order_lines_product_id_fkey"', f'Key (product_id)=({d.get("hang")}) is not present in table "products".', http=409)


def _gan_dong(r, d: dict, gia_bang: float, kho: str, cong_ty: str):
	"""Ghi giá trị dòng nppsale vào một dòng Sales Order Item đã có."""
	moi = _dong_so(d, gia_bang, kho, cong_ty)
	if r.item_code != moi["item_code"]:  # đổi mặt hàng: để lõi điền lại tên / nhóm / đơn vị kho của hàng mới
		for k in ("item_name", "description", "stock_uom", "item_group", "brand", "image", "item_tax_rate"):
			r.set(k, None)
	for k, v in moi.items():
		r.set(k, v)


def _luu(so, rong_duoc=False):
	so.flags.ignore_permissions = True
	if rong_duoc and not so.items:
		so.flags.ignore_mandatory = True  # applyOrderEdit xoá dòng TRƯỚC rồi mới thêm — giữa chừng đơn có thể 0 dòng
	so.save()
	frappe.local.message_log = []


# ------------------------------------------------------------------------------------------------ sales_order_lines
def them_dong(ds: list[dict], nc) -> list[str]:
	q = _quyen(nc)
	cd = cai_dat_ban()
	docs: dict = {}
	moi: list[tuple] = []
	for gt in ds:
		gt = gt or {}
		so = _don(_chu(gt.get("order_id")), docs)
		khong_ro = set(gt) - set(_COT_DONG) - _COT_DONG_BO_QUA - {"order_id", "invoiced_qty"}
		if khong_ro:
			raise LoiCong("PGRST204", f"Could not find the '{sorted(khong_ro)[0]}' column of 'sales_order_lines' in the schema cache")
		d = {
			"hang": _chu(gt.get("product_id")), "don_vi": _chu(gt.get("unit_name")), "sl": _so(gt.get("quantity")),
			"gia": _so(gt.get("unit_price")), "giam": _so(gt.get("line_discount"), 0) or 0,
			"he_so": _so(gt.get("conversion_factor"), 1) if gt.get("conversion_factor") is not None else 1,
			"ghi_chu": _chu(gt.get("note")), "thue": gt.get("vat_rate"),
		}
		_don_vi_rong(d)
		if so is not None:
			_khoa_dong_theo_trang_thai(_tt(so))
		if flt(gt.get("invoiced_qty")) and nc.vai is not None:
			raise NppLoi("DON_KHOA: số đã xuất chỉ đổi khi lập / huỷ hóa đơn")
		gia_bang = _gia_bang(d["hang"], d["don_vi"], _bang_gia_nhom(so.customer) if so is not None else None) if d["hang"] else 0.0
		L.kiem_dong(d["sl"], d["gia"], d["giam"], q=q, gia_bang=gia_bang)
		if so is None or not _ghi_duoc_dong(nc, so):
			raise _rls("sales_order_lines")
		_kiem_thue(d)
		d["gia_bang"] = gia_bang
		moi.append((so, d))
	_kiem_hang_ton_tai([d for _so_, d in moi])
	ra = []
	for so, d in moi:
		_dam_bao_uom(d["don_vi"])
		r = so.append("items", _dong_so(d, d["gia_bang"], cd.kho_ban or so.set_warehouse, cd.cong_ty or so.company))
		ra.append(r)
	for so in {id(s): s for s, _d in moi}.values():
		so.npp_dong_doi = 1
		_luu(so)
	for r in ra:
		ghi_nhat_ky_don(r.parent, "dong", hanh_dong="add_line", dong_don=r.name, giai_doan="draft", thay_doi={
			"product_id": r.item_code, "unit_name": r.uom, "quantity": r.qty, "unit_price": r.rate, "line_total": r.amount})
	return [r.name for r in ra]


def sua_dong(gt: dict, ids: list[str], nc) -> list[str]:
	gt = gt or {}
	khong_ro = set(gt) - set(_COT_DONG) - _COT_DONG_BO_QUA - {"order_id", "invoiced_qty"}
	if khong_ro:
		raise LoiCong("PGRST204", f"Could not find the '{sorted(khong_ro)[0]}' column of 'sales_order_lines' in the schema cache")
	q = _quyen(nc)
	cd = cai_dat_ban()
	docs: dict = {}
	da_sua: list[tuple] = []
	for ten in ids:
		cha = frappe.db.get_value("Sales Order Item", ten, "parent")
		so = _don(cha, docs)
		if so is None or not _ghi_duoc_dong(nc, so):
			continue  # RLS USING: không được ghi → bỏ qua, không lỗi
		r = next(x for x in so.items if x.name == ten)
		cu = _dong_cua(r)
		d = dict(cu)
		for k, v in gt.items():
			if k in _COT_DONG:
				d[_COT_DONG[k]] = _so(v) if _COT_DONG[k] in ("sl", "gia", "giam", "he_so") else (v if k == "vat_rate" else _chu(v))
		if "line_discount" in gt and gt["line_discount"] is None:
			d["giam"] = 0
		if "conversion_factor" in gt and gt["conversion_factor"] is None:
			d["he_so"] = 1
		if "order_id" in gt and _chu(gt["order_id"]) != so.name:
			raise _rls("sales_order_lines")  # chuyển dòng sang đơn khác — giao diện không làm; không hỗ trợ
		_don_vi_rong(d)
		_khoa_dong_theo_trang_thai(_tt(so))
		if "invoiced_qty" in gt and flt(gt["invoiced_qty"]) != flt(r.delivered_qty) and nc.vai is not None:
			raise NppLoi("DON_KHOA: số đã xuất chỉ đổi khi lập / huỷ hóa đơn")
		doi = any(d[k] != cu[k] for k in ("sl", "gia", "giam", "hang", "don_vi"))
		gia_bang = _gia_bang(d["hang"], d["don_vi"], _bang_gia_nhom(so.customer)) if d["hang"] else 0.0
		if doi:
			cung = d["hang"] == cu["hang"] and d["don_vi"] == cu["don_vi"]
			L.kiem_dong(d["sl"], d["gia"], d["giam"], q=q, gia_bang=gia_bang,
				cu={"sl": cu["sl"], "gia": cu["gia"], "giam_dong": cu["giam"]} if cung else None)
		_kiem_thue(d)
		d["gia_bang"] = gia_bang
		da_sua.append((so, r, cu, d))
	_kiem_hang_ton_tai([d for *_x, d in da_sua])
	for so, r, _cu, d in da_sua:
		_dam_bao_uom(d["don_vi"])
		_gan_dong(r, d, d["gia_bang"], r.warehouse or cd.kho_ban, cd.cong_ty or so.company)
	for so in {id(x[0]): x[0] for x in da_sua}.values():
		if any(any(c[k] != d[k] for k in ("sl", "gia", "giam", "hang", "don_vi", "thue")) for s_, _r, c, d in da_sua if s_ is so):
			so.npp_dong_doi = 1  # tiền đơn đổi → lần lưu đầu đơn kế tiếp là một lần sửa
		_luu(so)
	for so, r, cu, d in da_sua:
		moi_tien = flt(r.amount)
		cu_tien = round(cu["sl"] * cu["gia"])
		thay = {}
		for k_cu, k_moi, ten in (("hang", "hang", "product_id"), ("don_vi", "don_vi", "unit_name"), ("sl", "sl", "quantity"),
				("gia", "gia", "unit_price"), ("giam", "giam", "line_discount")):
			if cu[k_cu] != d[k_moi]:
				thay[ten] = {"from": cu[k_cu], "to": d[k_moi]}
		if cu_tien != moi_tien:
			thay["line_total"] = {"from": cu_tien, "to": moi_tien}
		if thay:
			ghi_nhat_ky_don(so.name, "dong", hanh_dong="edit_line", dong_don=r.name, giai_doan="draft", thay_doi=thay)
	return [r.name for _so_, r, _c, _d in da_sua]


def xoa_dong(ids: list[str], nc) -> list[str]:
	docs: dict = {}
	xoa: list[tuple] = []
	for ten in ids:
		so = _don(frappe.db.get_value("Sales Order Item", ten, "parent"), docs)
		if so is None or not _ghi_duoc_dong(nc, so):
			continue
		if _tt(so) in ("partially_invoiced", "completed", "closed"):
			raise NppLoi("ORDER_LOCKED: đơn đã xuất hàng, không sửa dòng được. Huỷ hóa đơn trước, hoặc lập đơn trả.")
		xoa.append((so, next(x for x in so.items if x.name == ten)))
	for _so_xoa, r in xoa:
		if frappe.db.sql("""SELECT 1 FROM `tabSales Invoice Item` i JOIN `tabSales Invoice` s ON s.`name` = i.`parent`
				WHERE i.`so_detail` = %s AND s.`docstatus` = 1 LIMIT 1""", r.name):
			raise LoiCong("23503", 'update or delete on table "sales_order_lines" violates foreign key constraint '
				'"sales_invoice_lines_order_line_id_fkey" on table "sales_invoice_lines"',
				f'Key (id)=({r.name}) is still referenced from table "sales_invoice_lines".', http=409)
	for so, r in xoa:
		so.remove(r)
	for so in {id(x[0]): x[0] for x in xoa}.values():
		so.npp_dong_doi = 1
		_luu(so, rong_duoc=True)
	for so, r in xoa:
		ghi_nhat_ky_don(so.name, "dong", hanh_dong="remove_line", dong_don=r.name, giai_doan="draft", thay_doi={
			"product_id": r.item_code, "unit_name": r.uom, "quantity": r.qty, "unit_price": r.rate, "line_total": r.amount})
	return [r.name for _so_, r in xoa]


# ------------------------------------------------------------------------------------------------ sales_orders
_COT_DAU = {"customer_id", "payment_terms", "expected_delivery", "subtotal", "vat", "total", "notes", "status", "approval_reason",
	"sales_user_id", "cancel_reason", "cancelled_at", "cancelled_by", "order_date", "discount"}
_COT_DAU_BO_QUA = {"id", "org_id", "order_code", "order_seq", "edit_no", "created_at", "created_by", "updated_at", "tim_kd",
	"client_request_id", "approved_by", "approved_at", "current_workflow_stage", "merged_into", "submitted_at", "completed_at",
	"completed_by", "closed_at", "closed_by"}


def _ghi_duoc_dau(nc, so) -> bool:
	"""RLS UPDATE USING của sales_orders: owner / manager / warehouse mọi đơn; sales — đơn của mình đang draft / submitted."""
	if nc.bo_qua_rls:
		return True
	if nc.vai in VAI_QUAN_TRI_DON:
		return True
	return nc.vai == "sales" and so.npp_nhan_vien == nc.user and _tt(so) in ("draft", "submitted")


def _kiem_chuyen(cu: str, moi: str, qua_rpc: bool = False):
	if cu == moi:
		return
	if moi not in CHUYEN.get(cu, ()):
		raise NppLoi(f"Không thể chuyển đơn từ {cu} sang {moi}")
	if not qua_rpc and ({cu, moi} & {"partially_invoiced", "completed", "closed"}):
		raise NppLoi("USE_RPC: dùng nút Xuất hàng / Huỷ hóa đơn / Đóng đơn")


# Trường sửa được sau khi đơn đã ghi sổ (đã xuất): ghi chú (màn chi tiết đơn), ngày giao, câu cảnh báo, đếm lần sửa, huỷ
_SAU_GHI_SO = {"npp_ghi_chu", "delivery_date", "npp_ly_do_canh_bao", "npp_lan_sua", "npp_ly_do_huy", "npp_huy_luc", "npp_huy_boi"}


def sua_dau_don(gt: dict, ids: list[str], nc) -> list[str]:
	gt = gt or {}
	khong_ro = set(gt) - _COT_DAU - _COT_DAU_BO_QUA
	if khong_ro:
		raise LoiCong("PGRST204", f"Could not find the '{sorted(khong_ro)[0]}' column of 'sales_orders' in the schema cache")
	q = _quyen(nc)
	ra = []
	for ten in ids:
		so = frappe.get_doc("Sales Order", ten)
		if not _ghi_duoc_dau(nc, so):
			continue  # RLS USING: không được ghi → bỏ qua, không lỗi
		tt_cu = _tt(so)
		sub_cu = _subtotal_cua(so)
		tt = (_chu(gt["status"]) if "status" in gt else None) or tt_cu
		# ---- BEFORE UPDATE: chuyển trạng thái → người đứng tên → đếm lần sửa
		_kiem_chuyen(tt_cu, tt)
		nguoi = so.npp_nhan_vien
		if "sales_user_id" in gt and _chu(gt["sales_user_id"]) and _chu(gt["sales_user_id"]) != nguoi:
			nguoi = _chu(gt["sales_user_id"])
			_kiem_nguoi_dung_ten(nc, nguoi)
		if tt not in TRANG_THAI:
			raise LoiCong("23514", 'new row for relation "sales_orders" violates check constraint "chk_sales_orders_status_v2"')
		doi: dict = {}
		dem_sua = False  # trg_sales_orders_bump_edit: khách / điều khoản / ngày giao / tiền / ghi chú đổi
		if "customer_id" in gt and _chu(gt["customer_id"]) != so.customer:
			khach = _chu(gt["customer_id"])
			if not khach or not frappe.db.exists("Customer", khach):
				raise LoiCong("23503", 'insert or update on table "sales_orders" violates foreign key constraint "sales_orders_customer_id_fkey"',
					f'Key (customer_id)=({khach}) is not present in table "customers".', http=409)
			doi["customer"] = khach
			dem_sua = True
		if "payment_terms" in gt and (_chu(gt["payment_terms"]) or None) != (so.payment_terms_template or None):
			dk = _chu(gt["payment_terms"]) or None
			if dk and not frappe.db.exists("Payment Terms Template", dk):
				raise NppLoi(f"BAD_PAYLOAD: điều khoản thanh toán \"{dk}\" không có trong danh mục.")
			doi["payment_terms_template"] = dk
			dem_sua = True
		if "expected_delivery" in gt and (_chu(gt["expected_delivery"]) or None) != (str(so.delivery_date) if so.delivery_date else None):
			doi["delivery_date"] = _chu(gt["expected_delivery"]) or None
			dem_sua = True
		if "notes" in gt and (_chu(gt["notes"]) or None) != (so.npp_ghi_chu or None):
			doi["npp_ghi_chu"] = _chu(gt["notes"]) or None
			dem_sua = True
		if "order_date" in gt and _chu(gt["order_date"]) and _chu(gt["order_date"]) != str(so.transaction_date):
			doi["transaction_date"] = _chu(gt["order_date"])
		if "approval_reason" in gt and (_chu(gt["approval_reason"]) or None) != (so.npp_ly_do_canh_bao or None):
			doi["npp_ly_do_canh_bao"] = _chu(gt["approval_reason"]) or None
		for cot, truong in (("cancel_reason", "npp_ly_do_huy"), ("cancelled_by", "npp_huy_boi"), ("cancelled_at", "npp_huy_luc")):
			if cot in gt and (_chu(gt[cot]) or None) != (str(so.get(truong)) if so.get(truong) else None):
				doi[truong] = _chu(gt[cot]) or None
		if tt != tt_cu:
			doi["npp_trang_thai"] = tt
			if tt == "cancelled" and not so.npp_huy_luc and "npp_huy_luc" not in doi:
				doi["npp_huy_luc"] = now_datetime()
		if nguoi != so.npp_nhan_vien:
			doi["npp_nhan_vien"] = nguoi
		tien = {"subtotal", "vat", "total"} & set(gt)
		if tien:
			sub = _so(gt.get("subtotal"), 0) if "subtotal" in gt else sub_cu
			vat_c = _so(gt.get("vat"), 0) if "vat" in gt else flt(so.total_taxes_and_charges)
			if "subtotal" in gt:
				doi["npp_giam_gia_don"] = max(0, L.tong_tien([(r.qty, r.rate) for r in so.items]) - L.lam_tron(sub))
			if "total" in gt:
				doi["npp_tru_hang_tra"] = max(0, L.lam_tron(sub + vat_c - (_so(gt.get("total"), 0) or 0)))
			cu_doc = (L.lam_tron(sub_cu), L.lam_tron(so.total_taxes_and_charges))
			if so.get("npp_dong_doi") or ("subtotal" in gt and L.lam_tron(sub) != cu_doc[0]) or (
					"vat" in gt and L.lam_tron(vat_c) != cu_doc[1]) or (
					"total" in gt and doi.get("npp_tru_hang_tra", flt(so.npp_tru_hang_tra)) != flt(so.npp_tru_hang_tra)):
				dem_sua = True
			doi["npp_dong_doi"] = 0
		if dem_sua:
			doi["npp_lan_sua"] = (so.npp_lan_sua or 0) + 1
		goc = _giam_hien_tai(so) if "subtotal" in gt else None  # giảm đơn trước lần lưu này (= giam_don_goc của nppsale)
		# ---- ghi
		if so.docstatus == 1:
			cam = {k for k, v in doi.items() if k not in _SAU_GHI_SO and k != "npp_dong_doi" and v != so.get(k)}
			if cam:
				raise NppLoi("DON_DA_XUAT: đơn đã xuất hàng chỉ sửa được ghi chú / ngày giao — đổi khác thì huỷ hoá đơn trước.")
			doi.pop("npp_dong_doi", None)
		for k, v in doi.items():
			so.set(k, v)
		if "customer" in doi:  # bảng giá + giá bảng từng dòng theo nhóm của khách mới
			bang = _bang_gia_nhom(so.customer) or GIA_CHUAN
			so.selling_price_list = bang
			cd = cai_dat_ban()
			for r in so.items:
				d = _dong_cua(r)
				_gan_dong(r, d, _gia_bang(d["hang"], d["don_vi"], bang), r.warehouse, cd.cong_ty or so.company)
		if {"payment_terms_template", "transaction_date"} & set(doi) and so.docstatus == 0:
			so.set("payment_schedule", [])
		if so.docstatus == 1:
			_luu_sau_ghi_so(so)
		else:
			_luu(so, rong_duoc=True)
		if "subtotal" in gt and tt in ("draft", "submitted") and not nc.bo_qua_rls:
			L.kiem_giam_don(_giam_hien_tai(so), q=q, goc=goc, dong=[(r.qty, r.rate, r.npp_giam_dong) for r in so.items])
		if tt != tt_cu:
			ghi_nhat_ky_don(so.name, "trang_thai", tu_trang_thai=tt_cu, den_trang_thai=tt)
		ra.append(so.name)
	return ra


def _luu_sau_ghi_so(so):
	"""Đơn đã xuất (Sales Order đã ghi sổ): chỉ trường sửa được sau ghi sổ (ghi chú, ngày giao…) — lõi tự chặn phần còn lại."""
	so.flags.ignore_permissions = True
	so.save()
	frappe.local.message_log = []


def xoa_don(ids: list[str], nc) -> list[str]:
	ra = []
	for ten in ids:
		so = frappe.get_doc("Sales Order", ten)
		tt = _tt(so)
		da_xuat = frappe.db.exists("Sales Invoice", {"npp_don_hang": ten, "docstatus": ("in", (1, 2))}) if frappe.db.has_column(
			"Sales Invoice", "npp_don_hang") else False
		if not nc.bo_qua_rls:
			if nc.vai in ("owner", "manager"):
				if tt not in ("draft", "cancelled") or da_xuat:
					continue
			elif not (nc.vai == "sales" and so.npp_nhan_vien == nc.user and tt == "draft"):
				continue
		# trg_sales_orders_before_delete: phiếu trả của đơn (khi có NPP Phieu Tra), gỡ ghé thăm
		for g in frappe.get_all("NPP Ghe Tham", filters={"don_hang": ten}, pluck="name"):
			frappe.db.set_value("NPP Ghe Tham", g, "don_hang", None, update_modified=False)
		if da_xuat:
			raise LoiCong("23503", 'update or delete on table "sales_orders" violates foreign key constraint "sales_invoices_order_id_fkey" on '
				'table "sales_invoices"', f'Key (id)=({ten}) is still referenced from table "sales_invoices".', http=409)
		for k in frappe.get_all("NPP Nhat Ky Don", filters={"don": ten}, pluck="name"):  # ON DELETE CASCADE
			frappe.delete_doc("NPP Nhat Ky Don", k, ignore_permissions=True, force=True)
		frappe.delete_doc("Sales Order", ten, ignore_permissions=True, force=True)
		ra.append(ten)
	return ra


# ------------------------------------------------------------------------------------------------ RPC cancel_order
@rpc("cancel_order", ghi=True)
def cancel_order(p_order_id=None, p_reason=None):
	"""Huỷ đơn chưa xuất (mig 217): chỉ người có orders.update; NVBH chỉ đơn của mình; phiếu trả nháp kèm đơn huỷ theo; báo người đứng
	tên. Đơn đã có HĐ ghi sổ → HAS_INVOICE (huỷ HĐ là huỷ đơn — đường cancel_invoice)."""
	nc = hien_tai()
	ten = _chu(p_order_id)
	if not ten or not frappe.db.exists("Sales Order", ten):
		raise NppLoi("ORDER_NOT_FOUND")
	so = frappe.get_doc("Sales Order", ten)
	frappe.db.sql("SELECT `name` FROM `tabSales Order` WHERE `name` = %s FOR UPDATE", ten)
	tt = _tt(so)
	if tt == "cancelled":
		return None
	so_hd = frappe.db.count("Sales Invoice", {"npp_don_hang": ten, "docstatus": 1}) if frappe.db.has_column(
		"Sales Invoice", "npp_don_hang") else 0
	if so_hd > 0 or tt in ("partially_invoiced", "completed", "closed"):
		raise NppLoi(f"HAS_INVOICE: đơn {ten} đã xuất {so_hd} hóa đơn. Huỷ hết hóa đơn trước, rồi mới huỷ đơn.")
	if not co_quyen(nc, "orders.update"):
		raise NppLoi("FORBIDDEN: bạn không có quyền huỷ đơn")
	if nc.vai == "sales" and so.npp_nhan_vien != nc.user:
		raise NppLoi("FORBIDDEN_NOT_OWNER: chỉ huỷ được đơn của mình")
	_kiem_chuyen(tt, "cancelled")
	so.npp_trang_thai = "cancelled"
	so.npp_huy_luc = now_datetime()
	so.npp_huy_boi = nc.user if frappe.db.exists("User", nc.user) else None
	so.npp_ly_do_huy = _chu(p_reason)
	_luu(so, rong_duoc=True)
	ghi_nhat_ky_don(ten, "trang_thai", tu_trang_thai=tt, den_trang_thai="cancelled")
	# phiếu trả nháp kèm đơn → Đã huỷ: thêm khi có NPP Phieu Tra
	gui_thong_bao(so.npp_nhan_vien, "order_cancelled", f"Đơn {ten} đã bị huỷ", _chu(p_reason), f"/orders/{ten}")
	return None
