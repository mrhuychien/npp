"""Bảng ĐƠN HÀNG của nppsale trên cổng: sales_orders (Sales Order + trường npp_*), sales_order_lines (Sales Order Item) —
blueprint 02 phần Bán hàng §3.2, §4. Đọc theo sales_order_select (mig 161); tạo đơn qua RPC create_order_with_lines; sửa đơn (ghi thẳng
bảng như applyOrderEdit của nppsale) và xoá đơn đi bộ ghi GhiDon / GhiDongDon → nppsale.rpc.sua_don (luật trigger).

sales_order_select: (đơn không phải nháp OR người đứng tên = tôi — NHÁP KÍN, kể cả chủ NPP) AND (vai ∈ owner / manager / accountant /
warehouse OR quyền customer.view_all OR người đứng tên = tôi OR khách thuộc phân công đang hiệu lực của tôi).
"""
from __future__ import annotations

from ..dang_ky import Bang, CotDef, NguCanh, QuanHe, dang_ky
from ..ngu_canh import co_quyen
from ..sql import LoiCong
from ._chung import c, co_cot, la_nv, org

VAI_XEM_DON = ("owner", "manager", "accountant", "warehouse")
# số đã xuất của dòng đơn (mig 179 — gồm dòng HĐ đổi đơn vị lúc xuất) — cùng luật với get_invoiceable_lines (nppsale.rpc.xuat_hang)
_DA_XUAT = ("(SELECT COALESCE(SUM(hi.`qty` * COALESCE(NULLIF(hi.`conversion_factor`, 0), 1)), 0) / "
	"COALESCE(NULLIF({t}.`conversion_factor`, 0), 1) FROM `tabSales Invoice Item` hi WHERE hi.`parenttype` = 'Sales Invoice' "
	"AND hi.`docstatus` = 1 AND (hi.`so_detail` = {t}.`name` OR hi.`npp_dong_don` = {t}.`name`))")


def ve_don(nc: NguCanh, bd: str = "{t}"):
	"""Vế "đơn người gọi thấy được" trên bí danh `bd` của tabSales Order."""
	if nc.bo_qua_rls:
		return None
	if not la_nv(nc):
		return False
	nhap = f"(IFNULL({bd}.`npp_trang_thai`, 'draft') != 'draft' OR {bd}.`npp_nhan_vien` = %(u)s)"
	if nc.vai in VAI_XEM_DON or co_quyen(nc, "customer.view_all"):
		return (nhap, {"u": nc.user})
	pham_vi = (f"({bd}.`npp_nhan_vien` = %(u)s OR {bd}.`customer` IN (SELECT pc.`khach` FROM `tabNPP Phan Cong Khach` pc "
		"WHERE pc.`nhan_vien` = %(u)s AND pc.`trang_thai` = 'active'))")
	return (f"{nhap} AND {pham_vi}", {"u": nc.user})


def _co_hd() -> bool:
	return co_cot("Sales Invoice", "npp_don_hang")


def _tong_sql() -> str:
	"""total của nppsale = khách phải trả lúc lên đơn: subtotal + vat − hàng trả kèm đơn (màn chi tiết đơn suy "Trừ hàng trả" bằng
	subtotal + vat − total, không tính lại khi phiếu trả đổi)."""
	tru = " - IFNULL({t}.`npp_tru_hang_tra`, 0)" if co_cot("Sales Order", "npp_tru_hang_tra") else ""
	return "GREATEST(0, {t}.`grand_total` - IFNULL({t}.`npp_giam_gia_don`, 0)" + tru + ")"


def _cot_don():
	_TONG = _tong_sql()
	ra = {
		"id": c("{t}.`name`"), "org_id": org(), "order_code": c("{t}.`name`"),
		"order_seq": c("CAST(SUBSTRING_INDEX({t}.`name`, '-', -1) AS UNSIGNED)", "so"),
		"customer_id": c("customer"), "sales_user_id": c("npp_nhan_vien"), "order_date": c("transaction_date", "ngay"),
		"expected_delivery": c("delivery_date", "ngay"), "status": c("IFNULL({t}.`npp_trang_thai`, 'draft')"),
		"current_workflow_stage": CotDef("NULL"), "payment_terms": c("payment_terms_template"),
		"subtotal": c("({t}.`net_total` - IFNULL({t}.`npp_giam_gia_don`, 0))", "tien"), "discount": CotDef("0", "tien"),
		"vat": c("total_taxes_and_charges", "tien"), "total": c(_TONG, "tien"),
		"merged_into": CotDef("NULL"), "notes": c("npp_ghi_chu"), "approved_by": CotDef("NULL"), "approved_at": CotDef("NULL", "gio"),
		"approval_reason": c("npp_ly_do_canh_bao"),
		# lần đầu sang submitted (check_order_status_transition / _don_moi_moc_gui chỉ đặt khi đang trống) — giữ cả khi đơn gửi về nháp
		"submitted_at": c("(SELECT MIN(nk.`luc`) FROM `tabNPP Nhat Ky Don` nk WHERE nk.`don` = {t}.`name` AND nk.`loai` = 'trang_thai' "
			"AND nk.`den_trang_thai` = 'submitted')", "gio"),
		"cancelled_at": c("npp_huy_luc", "gio"), "cancelled_by": c("npp_huy_boi"), "cancel_reason": c("npp_ly_do_huy"),
		"closed_at": CotDef("NULL", "gio"), "closed_by": CotDef("NULL"),
		"created_at": c("creation", "gio"), "created_by": c("CASE WHEN {t}.`owner` IN ('Administrator', 'Guest') THEN NULL ELSE {t}.`owner` END"),
		"updated_at": c("modified", "gio"), "edit_no": c("npp_lan_sua", "so"), "client_request_id": c("npp_client_request_id"),
		"tim_kd": c("npp_tim_kd"),
	}
	if _co_hd():
		# CHỈ khi đơn đang Hoàn thành — `_wf2b_sync_order_status` xoá completed_at / completed_by khi đơn rời 'completed' (huỷ HĐ → đơn về
		# submitted rồi Đã huỷ; Sửa HĐ → về submitted rồi hoàn thành LẠI lúc lập tờ mới). Vậy mốc = lúc lập HĐ ĐANG hiệu lực (mới nhất).
		_hd_hl = ("FROM `tabSales Invoice` hd WHERE hd.`npp_don_hang` = {t}.`name` AND hd.`docstatus` = 1 AND hd.`is_return` = 0 "
			"ORDER BY hd.`creation` DESC LIMIT 1")
		ra["completed_at"] = c("CASE WHEN {t}.`npp_trang_thai` = 'completed' THEN (SELECT hd.`creation` " + _hd_hl + ") END", "gio")
		ra["completed_by"] = c("CASE WHEN {t}.`npp_trang_thai` = 'completed' THEN (SELECT CASE WHEN hd.`owner` IN ('Administrator', "
			"'Guest') THEN NULL ELSE hd.`owner` END " + _hd_hl + ") END")
	else:
		ra["completed_at"] = CotDef("NULL", "gio")
		ra["completed_by"] = CotDef("NULL")
	return ra


def _rls_don(nc):
	return ve_don(nc)


class GhiDon:
	"""sales_orders: sửa đầu đơn / xoá đơn theo luật trigger (nppsale.rpc.sua_don); tạo đơn đi RPC create_order_with_lines."""

	def them(self, ds, nc):
		raise LoiCong("42501", 'new row violates row-level security policy for table "sales_orders"', "Tạo đơn qua create_order_with_lines.",
			http=403)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.sua_don import sua_dau_don

		return sua_dau_don(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.sua_don import xoa_don

		return xoa_don(ids, nc)


class GhiDongDon:
	"""sales_order_lines: thêm / sửa / xoá dòng của đơn chưa xuất (applyOrderEdit) theo luật trigger (nppsale.rpc.sua_don)."""

	def them(self, ds, nc):
		from nppsale.rpc.sua_don import them_dong

		return them_dong(ds, nc)

	def sua(self, gia_tri, ids, nc):
		from nppsale.rpc.sua_don import sua_dong

		return sua_dong(gia_tri, ids, nc)

	def xoa(self, ids, nc):
		from nppsale.rpc.sua_don import xoa_dong

		return xoa_dong(ids, nc)


def _rls_dong(nc):
	v = ve_don(nc, "dh")
	if v is None:
		return None
	if v is False:
		return False
	return (f"{{t}}.`parent` IN (SELECT dh.`name` FROM `tabSales Order` dh WHERE {v[0]})", v[1])


def nap():
	"""Khai bảng đơn (gọi khi nạp sổ — cột 'đã xuất' phụ thuộc cột npp_don_hang của Sales Invoice đã có chưa)."""
	if not co_cot("Sales Order", "npp_trang_thai"):
		return  # site chưa có trường của phần Bán hàng — bỏ qua, cổng báo bảng không tồn tại như trước
	dang_ky(Bang(
		ten="sales_orders",
		nguon="`tabSales Order`",
		cot=_cot_don(),
		quan_he=[
			QuanHe("customers", "customer_id", "id", False, ("sales_orders_customer_id_fkey",)),
			QuanHe("users", "sales_user_id", "id", False, ("sales_orders_sales_user_id_fkey",)),
			QuanHe("users", "created_by", "id", False, ("sales_orders_created_by_fkey",)),
			QuanHe("users", "cancelled_by", "id", False, ("sales_orders_cancelled_by_fkey",)),
			QuanHe("sales_order_lines", "id", "order_id", True, ("sales_order_lines_order_id_fkey",)),
		],
		rls=_rls_don,
		ghi=GhiDon(),
	))
	dang_ky(Bang(
		ten="sales_order_lines",
		nguon="(SELECT * FROM `tabSales Order Item` WHERE `parenttype` = 'Sales Order')",
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "order_id": c("parent"), "product_id": c("item_code"), "unit_name": c("uom"),
			"quantity": c("qty", "so"), "unit_price": c("rate", "tien"), "line_discount": c("npp_giam_dong", "tien"),
			"line_total": c("amount", "tien"), "batch_id": CotDef("NULL"), "note": c("additional_notes"),
			"conversion_factor": c("conversion_factor", "so"), "vat_rate": c("npp_thue_suat", "so"), "invoiced_qty": c(_DA_XUAT, "so"),
			"sort_order": c("idx", "so"), "created_at": c("creation", "gio"),
		},
		quan_he=[
			QuanHe("products", "product_id", "id", False, ("sales_order_lines_product_id_fkey",)),
			QuanHe("sales_orders", "order_id", "id", False, ("sales_order_lines_order_id_fkey",)),
		],
		rls=_rls_dong,
		ghi=GhiDongDon(),
	))
	if co_cot("NPP Nhat Ky Don", "loai"):
		_nap_nhat_ky()


def _rls_lich_su(nc):
	"""order_status_history "View history of visible orders": dòng của đơn người gọi thấy được (sales_order_select)."""
	v = ve_don(nc, "so")
	if v is None or v is False:
		return v
	return (f"{{t}}.`don` IN (SELECT so.`name` FROM `tabSales Order` so WHERE {v[0]})", v[1])


def _nap_nhat_ky():
	"""NPP Nhat Ky Don gộp hai bảng nhật ký của nppsale (blueprint 02): loai 'trang_thai' = order_status_history (trigger đổi trạng thái),
	loai 'dong' = order_activity_log (mig 052, RLS `org_id = user_org_id()` — mọi NV của NPP). Chỉ đọc: ghi do method."""
	from ..sql import LoiCong as _L
	from ._chung import rls_moi_nv

	class _ChiDoc:
		def __init__(self, ten):
			self.ten = ten

		def them(self, ds, nc):
			raise _L("42501", f'new row violates row-level security policy for table "{self.ten}"', http=403)

		def sua(self, gia_tri, ids, nc):
			return []

		def xoa(self, ids, nc):
			return []

	dang_ky(Bang(
		ten="order_status_history",
		nguon="(SELECT * FROM `tabNPP Nhat Ky Don` WHERE `loai` = 'trang_thai')",
		cot={"id": c("{t}.`name`"), "order_id": c("don"), "from_status": c("tu_trang_thai"), "to_status": c("den_trang_thai"),
			"changed_by": c("nguoi"), "changed_at": c("luc", "gio"), "notes": c("ghi_chu")},
		quan_he=[QuanHe("users", "changed_by", "id", False, ("order_status_history_changed_by_fkey", "changed_by")),
			QuanHe("sales_orders", "order_id", "id", False, ("order_status_history_order_id_fkey", "order_id"))],
		rls=_rls_lich_su,
		ghi=_ChiDoc("order_status_history"),
	))
	dang_ky(Bang(
		ten="order_activity_log",
		nguon="(SELECT * FROM `tabNPP Nhat Ky Don` WHERE `loai` = 'dong')",
		cot={"id": c("{t}.`name`"), "org_id": org(), "order_id": c("don"), "order_line_id": c("dong_don"), "action": c("hanh_dong"),
			"workflow_stage": c("giai_doan"), "changes": c("thay_doi", "json"), "actor_id": c("nguoi"), "created_at": c("luc", "gio")},
		quan_he=[QuanHe("users", "actor_id", "id", False, ("order_activity_log_actor_id_fkey", "actor_id")),
			QuanHe("sales_orders", "order_id", "id", False, ("order_activity_log_order_id_fkey", "order_id"))],
		rls=rls_moi_nv,
		ghi=_ChiDoc("order_activity_log"),
	))


try:
	nap()
except Exception:  # noqa: BLE001 — nạp sổ ngoài request (không có DB) thì thôi
	pass
