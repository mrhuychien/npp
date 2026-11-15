"""Bảng PHIẾU TRẢ của nppsale trên cổng: returns (NPP Phieu Tra), return_lines (NPP Phieu Tra Dong) — blueprint 02 phần Bán hàng.

ĐỌC (RLS đang chạy của nppsale):
- returns "Admin roles can view all returns": chủ NPP / quản lý / kế toán / thủ kho thấy mọi phiếu; "Sales see own returns" (mig 198):
  NVBH thấy phiếu mình lập, mình đứng tên, gắn HĐ mình đứng tên, hoặc thuộc đơn mình đứng tên.
- return_lines "Users can view return lines": theo phiếu cha nhìn thấy được.
Cột không port (luôn NULL, không lỗi): approved_by, photo_url, applied_receipt_id (cấn phiếu trả ở phiếu thu đã bỏ từ mig 191).
`updated_at` = giờ sửa cuối (`sua_luc`, mig 220) — không phải `modified` (đổi ở mọi lần method lưu phiếu).

GHI thẳng: RLS ghi + khoá trình duyệt mig 191 / 214 / 227 (nppsale.rpc.phieu_tra); hoàn thành / huỷ / POS đi RPC.
"""
from __future__ import annotations

from ..dang_ky import Bang, CotDef, NguCanh, QuanHe, dang_ky
from ._chung import c, co_cot, la_nv, org
from .kho import KHO

VAI_XEM_HET = ("owner", "manager", "accountant", "warehouse")
NULL_CHUOI = CotDef("NULL")


def _ve_phieu(nc: NguCanh, bd: str = "{t}"):
	"""Vế "phiếu trả người gọi thấy được" trên bí danh phiếu `bd`."""
	if nc.bo_qua_rls:
		return None
	if not la_nv(nc):
		return False
	if nc.vai in VAI_XEM_HET:
		return None
	if nc.vai != "sales":
		return False
	return (f"({bd}.`owner` = %(u)s OR {bd}.`nhan_vien` = %(u)s"
		f" OR EXISTS (SELECT 1 FROM `tabSales Invoice` si WHERE si.`name` = {bd}.`hoa_don` AND si.`npp_nhan_vien` = %(u)s)"
		f" OR EXISTS (SELECT 1 FROM `tabSales Order` so WHERE so.`name` = {bd}.`don_hang` AND so.`npp_nhan_vien` = %(u)s))", {"u": nc.user})


def _ve_dong(nc: NguCanh):
	v = _ve_phieu(nc, "r")
	if v is None or v is False:
		return v
	sql, ts = v
	return (f"EXISTS (SELECT 1 FROM `tabNPP Phieu Tra` r WHERE r.`name` = {{t}}.`parent` AND {sql})", ts)


class GhiPhieu:
	"""returns: ghi thẳng theo RLS + khoá trình duyệt (nppsale.rpc.phieu_tra)."""

	def them(self, ds, nc):
		from nppsale.rpc.phieu_tra import them_phieu

		return them_phieu(ds, nc)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.phieu_tra import sua_phieu

		return sua_phieu(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.phieu_tra import xoa_phieu

		return xoa_phieu(ids, nc)


class GhiDongTra:
	"""return_lines: ghi thẳng dòng của phiếu Nháp (nppsale.rpc.phieu_tra)."""

	def them(self, ds, nc):
		from nppsale.rpc.phieu_tra import them_dong

		return them_dong(ds, nc)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.phieu_tra import sua_dong

		return sua_dong(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.phieu_tra import xoa_dong

		return xoa_dong(ids, nc)


def nap():
	if not co_cot("NPP Phieu Tra", "tien_tra"):
		return
	vung = f"(SELECT z.`vung` FROM {KHO} z WHERE z.`kho` = {{t}}.`kho_nhan` LIMIT 1)"
	dang_ky(Bang(
		ten="returns",
		nguon="`tabNPP Phieu Tra`",
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "return_code": c("{t}.`name`"),
			"return_seq": c("CAST(SUBSTRING_INDEX({t}.`name`, '-', -1) AS UNSIGNED)", "so"),
			"order_id": c("don_hang"), "invoice_id": c("hoa_don"), "customer_id": c("khach_hang"), "requested_by": c("owner"),
			"sales_user_id": c("nhan_vien"), "reason": c("NULLIF({t}.`ly_do`, '')"), "status": c("trang_thai"),
			"credit_note_amount": c("tien_tra", "tien"), "credit_with_invoice": c("tu_sinh", "bool"), "notes": c("ghi_chu"),
			"return_date": c("ngay_tra", "ngay"), "revenue_date": c("ngay_tru_doanh_so", "ngay"), "credited_at": c("ghi_co_luc", "gio"),
			"destination_zone": c(vung), "completed_at": c("hoan_thanh_luc", "gio"), "completed_by": c("hoan_thanh_boi"),
			"cancelled_at": c("huy_luc", "gio"), "cancel_reason": c("ly_do_huy"), "created_at": c("creation", "gio"),
			"updated_at": c("COALESCE({t}.`sua_luc`, {t}.`creation`)", "gio"), "tim_kd": c("tim_kd"),
			"approved_by": NULL_CHUOI, "photo_url": NULL_CHUOI, "applied_receipt_id": NULL_CHUOI,
		},
		quan_he=[
			QuanHe("return_lines", "id", "return_id", True, ("return_lines_return_id_fkey",)),
			QuanHe("customers", "customer_id", "id", False, ("returns_customer_id_fkey", "customer_id")),
			QuanHe("users", "requested_by", "id", False, ("returns_requested_by_fkey", "requested_by")),
			QuanHe("users", "sales_user_id", "id", False, ("returns_sales_user_id_fkey", "sales_user_id")),
			QuanHe("users", "approved_by", "id", False, ("returns_approved_by_fkey", "approved_by")),
			QuanHe("users", "completed_by", "id", False, ("returns_completed_by_fkey", "completed_by")),
			QuanHe("sales_orders", "order_id", "id", False, ("returns_order_id_fkey", "order_id")),
			QuanHe("sales_invoices", "invoice_id", "id", False, ("returns_invoice_id_fkey", "invoice_id")),
		],
		rls=lambda nc: _ve_phieu(nc),
		ghi=GhiPhieu(),
	))
	dang_ky(Bang(
		ten="return_lines",
		nguon="`tabNPP Phieu Tra Dong`",
		cot={
			"id": c("{t}.`name`"), "return_id": c("parent"), "product_id": c("mat_hang"), "unit_name": c("don_vi"),
			"quantity": c("so_luong", "so"), "unit_price": c("don_gia", "tien"), "vat_rate": c("thue_suat", "so"),
			"line_total": c("thanh_tien", "tien"), "is_exchange": c("hang_doi", "bool"), "note": c("ghi_chu"),
			"reason": c("NULLIF({t}.`ly_do`, '')"), "sort_order": c("idx", "so"),
		},
		quan_he=[
			QuanHe("returns", "return_id", "id", False, ("return_lines_return_id_fkey", "return_id")),
			QuanHe("products", "product_id", "id", False, ("return_lines_product_id_fkey", "product_id")),
		],
		rls=_ve_dong,
		ghi=GhiDongTra(),
		thu_tu_mac_dinh=[{"cot": "return_id"}, {"cot": "sort_order"}],
	))


try:
	nap()
except Exception:
	pass
