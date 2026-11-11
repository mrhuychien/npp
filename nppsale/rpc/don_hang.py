"""RPC đơn hàng trên Sales Order.

create_order_with_lines (mig 169): một giao dịch ghi đầu đơn + dòng (+ phiếu trả nháp kèm đơn), idempotent theo client_request_id.
Hàm gốc là SECURITY INVOKER nên mọi trigger trên sales_orders / sales_order_lines là luật phải chép, theo đúng thứ tự Postgres chạy:

  đầu đơn  — guard_order_sales_user (mig 153/155: chỉ chủ / quản lý lập đơn đứng tên người khác, người ấy phải là vai bán hàng)
             → RLS insert (owner / manager / sales) + RLS đọc lại dòng vừa ghi (RETURNING: đơn NHÁP đứng tên người khác thì người lập
             không thấy → 42501, kể cả chủ NPP) → CHECK trạng thái (23514) → trùng client_request_id (23505) → khoá ngoại khách (23503)
  từng dòng — đơn vị rỗng = đơn vị cơ sở (UNIT_MISSING) → khoá dòng của đơn đã xuất / đã huỷ → giá trần + quyền giảm giá dòng
             (_chot_gia_dong_don, mig 226/230) → khoá ngoại mặt hàng (cuối câu lệnh)
  cuối      — quyền giảm giá cả đơn (_chot_giam_don, constraint trigger hoãn tới cuối giao dịch)

Đơn ghi thành Sales Order nháp (docstatus 0): `npp_trang_thai` draft / submitted, bảng giá của nhóm khách (hoặc Gia chuan),
ignore_pricing_rule, kho bán, mẫu thuế "VAT theo mặt hàng" + Item Tax Template theo thuế suất từng dòng, skip_delivery_note (không bắt
ngày giao), disable_rounded_total. Dòng mang đơn giá SAU giảm + giá bảng của đúng đơn vị (lõi không tự tính lại từ %, PoC 2).
Giảm giá cả đơn = Σ SL × giá − subtotal gửi lên (như `_giam_don_hien_tai`) → `npp_giam_gia_don`; hàng trả kèm đơn đã trừ vào số
khách phải trả = subtotal + vat − total gửi lên → `npp_tru_hang_tra`.
"""
from __future__ import annotations

import json
import uuid

import frappe
from frappe.utils import nowdate

from nppsale.cong.bang.don_hang import VAI_XEM_DON
from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import co_quyen, hien_tai
from nppsale.cong.sql import LoiCong
from nppsale.luat import gia_don as L
from nppsale.npp_he_thong.doctype.npp_nhat_ky_don.npp_nhat_ky_don import ghi_nhat_ky_don
from nppsale.su_kien.san_pham import GIA_CHUAN
from nppsale.thiet_lap.ban_hang import cai_dat_ban, mau_thue_dong

from . import rpc

TRANG_THAI = ("draft", "submitted", "partially_invoiced", "completed", "closed", "cancelled")
VAI_LAP_DON = ("owner", "manager", "sales")
VAI_DUNG_TEN = ("sales", "manager", "owner")


def _rls(bang: str) -> LoiCong:
	return LoiCong("42501", f'new row violates row-level security policy for table "{bang}"', http=403)


def _uuid(v) -> str | None:
	"""NULLIF(x, '')::uuid — rỗng → None; sai dạng → 22P02 như Postgres."""
	if v is None or v == "":
		return None
	s = v if isinstance(v, str) else json.dumps(v)
	try:
		return str(uuid.UUID(s))
	except (ValueError, AttributeError, TypeError):
		raise LoiCong("22P02", f'invalid input syntax for type uuid: "{s}"') from None


def _so(v, mac_dinh=None):
	"""(x)::numeric — None giữ None (rồi COALESCE ở nơi gọi); chữ không phải số → 22P02."""
	if v is None:
		return mac_dinh
	if isinstance(v, bool):
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{json.dumps(v)}"')
	if isinstance(v, (int, float)):
		return v
	try:
		return float(str(v).strip())
	except ValueError:
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{v}"') from None


def _chu(v) -> str | None:
	"""p->>'x' của Postgres: chuỗi giữ nguyên, số / bool thành chữ, null → None."""
	if v is None:
		return None
	if isinstance(v, str):
		return v
	return json.dumps(v)


def _nv(ten: str | None) -> dict | None:
	if not ten:
		return None
	return frappe.db.get_value("NPP Nhan Vien", ten, ["name", "vai", "dang_hoat_dong", "nghi_viec_luc", "cho_sua_gia", "tran_tang_gia",
		"cho_giam_gia", "kieu_tran_giam", "co_tran_giam", "tran_giam"], as_dict=True)


def _quyen(nc) -> L.QuyenGiam:
	"""_quyen_giam_cua(auth.uid()): theo dòng users của người gọi (không lọc đang làm — như hàm gốc)."""
	if nc.bo_qua_rls:
		return L.QuyenGiam(toan_quyen=True)
	nv = _nv(nc.user)
	if not nv:
		return L.QuyenGiam(toan_quyen=True)  # COALESCE(role IN (...), true): người gọi không có dòng users
	return L.quyen_giam(nv)


# ------------------------------------------------------------------------------------------------ giá bảng của đúng đơn vị
def _gia_bang(hang: str, don_vi: str, bang_nhom: str | None) -> float:
	"""_gia_bang_don_vi(sp, đơn vị, nhóm khách) — 4 bậc: (1) bảng giá của nhóm khách, đúng đơn vị; (2) Gia chuan, đúng đơn vị; (3) đơn
	vị cơ sở → giá bán của mặt hàng; (4) đơn vị khác có hệ số → giá đơn vị cơ sở (lại qua 3 bậc trên) × hệ số. Trùng → giá thấp nhất;
	0 = chưa có giá."""
	def min_gia(bang):
		v = frappe.db.sql("SELECT MIN(`price_list_rate`) FROM `tabItem Price` WHERE `item_code` = %s AND `uom` = %s AND `price_list` = %s",
			(hang, don_vi, bang))[0][0]
		return float(v) if v is not None else None

	if bang_nhom:
		v = min_gia(bang_nhom)
		if v is not None:
			return v
	v = min_gia(GIA_CHUAN)
	if v is not None:
		return v
	sp = frappe.db.get_value("Item", hang, ["stock_uom", "npp_gia_ban"], as_dict=True)
	if not sp:
		return 0.0
	if don_vi == sp.stock_uom:
		return float(sp.npp_gia_ban or 0)
	he_so = frappe.db.get_value("UOM Conversion Detail", {"parent": hang, "parenttype": "Item", "uom": don_vi}, "conversion_factor")
	if he_so is not None:
		v = _gia_bang(hang, sp.stock_uom, bang_nhom)
		if v > 0:
			return v * float(he_so)
	return 0.0


def _bang_gia_nhom(khach: str) -> str | None:
	nhom = frappe.db.get_value("Customer", khach, "customer_group")
	return frappe.db.get_value("Customer Group", nhom, "default_price_list") if nhom else None


# ------------------------------------------------------------------------------------------------ đơn người gọi thấy được
def _thay_don(nc, ten: str) -> bool:
	from nppsale.cong.bang.don_hang import ve_don

	v = ve_don(nc, "so")
	if v is None:
		return True
	if v is False:
		return False
	sql, tham = v
	return bool(frappe.db.sql(f"SELECT 1 FROM `tabSales Order` so WHERE so.`name` = %(ten)s AND {sql}", dict(tham, ten=ten)))


def _thay_don_moi(nc, nguoi_dung_ten: str, khach: str, trang_thai: str) -> bool:
	"""sales_order_select trên dòng sắp ghi (RETURNING của INSERT phải đọc lại được dòng ấy)."""
	if nc.bo_qua_rls:
		return True
	if trang_thai == "draft" and nguoi_dung_ten != nc.user:
		return False
	if nc.vai in VAI_XEM_DON or co_quyen(nc, "customer.view_all") or nguoi_dung_ten == nc.user:
		return True
	return bool(frappe.db.exists("NPP Phan Cong Khach", {"khach": khach, "nhan_vien": nc.user, "trang_thai": "active"}))


def _tim_theo_crid(nc, crid: str) -> str | None:
	ten = frappe.db.get_value("Sales Order", {"npp_client_request_id": crid}, "name")
	return ten if ten and _thay_don(nc, ten) else None


def _kiem_nguoi_dung_ten(nc, ten: str):
	"""guard_order_sales_user (BEFORE INSERT) — npp.via_rpc không bật ở đường này."""
	if nc.bo_qua_rls or ten == nc.user:
		return
	if nc.vai is not None and nc.vai not in ("owner", "manager"):  # user_role() NULL (bị khoá) → điều kiện NULL, không ném
		raise NppLoi("DON_HO_KHONG_DUOC_PHEP: chỉ chủ nhà phân phối hoặc quản lý mới lập đơn đứng tên nhân viên khác.")
	nv = _nv(ten)
	if not nv:
		raise NppLoi("NHAN_VIEN_KHONG_HOP_LE: nhân viên được chọn không thuộc đơn vị này.")
	if nv.vai not in VAI_DUNG_TEN:
		raise NppLoi(f"NHAN_VIEN_KHONG_BAN_HANG: {nv.vai} không phải vai trò bán hàng, không đứng tên đơn được.")


# ------------------------------------------------------------------------------------------------ dòng hàng
def _doc_dong(l: dict) -> dict:
	if not isinstance(l, dict):
		l = {}
	return {
		"hang": _chu(l.get("product_id")),
		"don_vi": _chu(l.get("unit_name")),
		"sl": _so(l.get("quantity")),
		"gia": _so(l.get("unit_price"), 0),
		"giam": _so(l.get("line_discount"), 0),
		"he_so": _so(l.get("conversion_factor"), 1),
		"ghi_chu": _chu(l.get("note")) or None,
		"thue": L.thue_hop_le(_chu(l.get("vat_rate"))),
	}


def _don_vi_rong(d: dict):
	"""_trg_don_vi_rong_la_co_so (mig 167): đơn vị rỗng → đơn vị cơ sở của mặt hàng, trừ khi hệ số ≠ 1."""
	if (d["don_vi"] or "").strip():
		d["don_vi"] = d["don_vi"].strip()
		return
	he_so = 1 if d["he_so"] is None else d["he_so"]
	if he_so != 1:
		raise NppLoi(f"UNIT_MISSING: dòng hàng thiếu đơn vị tính mà hệ số quy đổi là {float(he_so):.6f} — chọn lại đơn vị rồi lưu.")
	co_so = frappe.db.get_value("Item", d["hang"], "stock_uom") if d["hang"] else None
	if not (co_so or "").strip():
		raise NppLoi("UNIT_MISSING: mặt hàng chưa có đơn vị cơ sở — điền đơn vị trong danh mục hàng rồi lưu lại.")
	d["don_vi"] = co_so


def _khoa_dong_theo_trang_thai(trang_thai: str):
	"""guard_order_lines_locked."""
	if trang_thai in ("partially_invoiced", "completed", "closed"):
		raise NppLoi("ORDER_LOCKED: đơn đã xuất hàng, không sửa dòng được. Huỷ hóa đơn trước, hoặc lập đơn trả.")
	if trang_thai == "cancelled":
		raise NppLoi("ORDER_CANCELLED: đơn này đã bị huỷ — không sửa dòng hàng được nữa. Tải lại đơn để xem trạng thái mới.")


def _dam_bao_uom(ten: str):
	if ten and not frappe.db.exists("UOM", ten):
		frappe.get_doc({"doctype": "UOM", "uom_name": ten, "must_be_whole_number": 0}).insert(ignore_permissions=True)


def _dong_so(d: dict, gia_bang: float, kho: str, cong_ty: str) -> dict:
	"""Dòng Sales Order Item: đơn giá SAU giảm + giá bảng của đúng đơn vị; giảm so giá bảng để lõi khỏi tính lại (calculate_item_rate)."""
	thue = d["thue"]
	if thue is None:  # "theo SP" (vat_rate NULL / không hợp lệ) — nppsale để hoá đơn lấy thuế mặt hàng; ở đây chụp ngay lúc lập
		thue = float(frappe.db.get_value("Item", d["hang"], "npp_thue_suat") or 0)
	gia = float(d["gia"])
	ra = {"item_code": d["hang"], "qty": d["sl"], "uom": d["don_vi"], "conversion_factor": d["he_so"], "rate": gia,
		"price_list_rate": float(gia_bang or 0), "discount_percentage": 0, "discount_amount": 0, "margin_type": "",
		"margin_rate_or_amount": 0, "warehouse": kho, "item_tax_template": mau_thue_dong(thue, cong_ty), "npp_thue_suat": thue,
		"npp_giam_dong": float(d["giam"] or 0), "additional_notes": d["ghi_chu"]}
	if gia_bang and gia < gia_bang:
		ra["discount_amount"] = float(gia_bang) - gia
	return ra


# ------------------------------------------------------------------------------------------------ RPC
@rpc("create_order_with_lines", ghi=True)
def create_order_with_lines(p=None):
	nc = hien_tai()
	p = p if isinstance(p, dict) else (json.loads(p) if isinstance(p, str) and p else {})
	crid = _uuid(_chu(p.get("client_request_id")))
	if crid is None:
		raise NppLoi("BAD_PAYLOAD: thiếu client_request_id.")
	dong_vao = p.get("lines")
	if not isinstance(dong_vao, list) or not dong_vao:
		raise NppLoi("BAD_PAYLOAD: đơn cần ít nhất một dòng hàng.")
	o = p.get("order") if isinstance(p.get("order"), dict) else {}

	da_co = _tim_theo_crid(nc, crid)
	if da_co:
		return [{"order_id": da_co, "order_code": da_co, "already_existed": True}]

	# ---- đầu đơn: thứ tự kiểm như INSERT của Postgres
	nguoi_dung_ten = _chu(o.get("sales_user_id")) or nc.user
	trang_thai = _chu(o.get("status")) or "draft"
	khach = _chu(o.get("customer_id"))
	dieu_khoan = _chu(o.get("payment_terms")) or "COD"
	_kiem_nguoi_dung_ten(nc, nguoi_dung_ten)
	if not nc.bo_qua_rls and nc.vai not in VAI_LAP_DON:
		raise _rls("sales_orders")
	if not _thay_don_moi(nc, nguoi_dung_ten, khach, trang_thai):
		raise _rls("sales_orders")
	if trang_thai not in TRANG_THAI:
		raise LoiCong("23514", 'new row for relation "sales_orders" violates check constraint "chk_sales_orders_status_v2"')
	if frappe.db.exists("Sales Order", {"npp_client_request_id": crid}):
		raise LoiCong("23505", 'duplicate key value violates unique constraint "idx_sales_orders_client_request_id"',
			f"Key (client_request_id)=({crid}) already exists.", http=409)
	if not khach or not frappe.db.exists("Customer", khach):
		raise LoiCong("23503", 'insert or update on table "sales_orders" violates foreign key constraint "sales_orders_customer_id_fkey"',
			f'Key (customer_id)=({khach}) is not present in table "customers".', http=409)
	if not frappe.db.exists("Payment Terms Template", dieu_khoan):
		raise NppLoi(f"BAD_PAYLOAD: điều khoản thanh toán \"{dieu_khoan}\" không có trong danh mục.")

	# ---- dòng hàng: trigger BEFORE từng dòng, khoá ngoại mặt hàng cuối câu lệnh
	q = _quyen(nc)
	bang_nhom = _bang_gia_nhom(khach)
	dong = []
	for l in dong_vao:
		d = _doc_dong(l)
		_don_vi_rong(d)
		_khoa_dong_theo_trang_thai(trang_thai)
		gia_bang = _gia_bang(d["hang"], d["don_vi"], bang_nhom) if d["hang"] else 0.0
		L.kiem_dong(d["sl"], d["gia"], d["giam"], q=q, gia_bang=gia_bang)
		d["gia_bang"] = gia_bang
		dong.append(d)
	for d in dong:
		if not d["hang"] or not frappe.db.exists("Item", d["hang"]):
			raise LoiCong("23503", 'insert or update on table "sales_order_lines" violates foreign key constraint '
				'"sales_order_lines_product_id_fkey"', f'Key (product_id)=({d["hang"]}) is not present in table "products".', http=409)

	# ---- giảm giá cả đơn (constraint trigger cuối giao dịch; đơn mới: gốc = 0)
	sub_c = _so(o.get("subtotal"), 0) or 0
	vat_c = _so(o.get("vat"), 0) or 0
	tong_c = _so(o.get("total"), 0) or 0
	giam_don = L.giam_don_hien_tai([(d["sl"], d["gia"]) for d in dong], sub_c)
	if trang_thai in ("draft", "submitted"):
		L.kiem_giam_don(giam_don, q=q, goc=0, dong=[(d["sl"], d["gia"], d["giam"]) for d in dong])
	# Lưu đúng phần chênh màn hình gửi (kể cả 1–2 đ dưới ngưỡng sai số) để subtotal đọc ra = subtotal nppsale lưu nguyên văn;
	# ngưỡng chỉ dùng để quyết "có giảm đơn không" khi kiểm quyền (như _giam_don_hien_tai).
	chenh_don = max(0, L.tong_tien([(d["sl"], d["gia"]) for d in dong]) - L.lam_tron(sub_c))

	if isinstance(p.get("returns"), dict) and isinstance(p.get("return_lines"), list) and p["return_lines"]:
		# Phiếu trả nháp kèm đơn (returns / return_lines) đi vào NPP Phieu Tra — dựng ở bước phiếu trả của P3.
		raise NppLoi("RETURNS_CHUA_HO_TRO: đơn có hàng trả kèm chưa ghi được trên bản ERPNext — bỏ hàng trả, gửi đơn trước rồi lập phiếu trả.")

	# ---- ghi Sales Order
	cd = cai_dat_ban()
	for d in dong:
		_dam_bao_uom(d["don_vi"])
	so = frappe.new_doc("Sales Order")
	so.update({
		"customer": khach, "company": cd.cong_ty, "order_type": "Sales", "transaction_date": nowdate(),
		"delivery_date": _chu(o.get("expected_delivery")) or None, "skip_delivery_note": 1,
		"selling_price_list": bang_nhom or GIA_CHUAN, "ignore_pricing_rule": 1, "set_warehouse": cd.kho_ban,
		"payment_terms_template": dieu_khoan, "disable_rounded_total": 1, "taxes_and_charges": cd.mau_thue_ban,
		"npp_trang_thai": trang_thai, "npp_nhan_vien": nguoi_dung_ten, "npp_client_request_id": crid, "npp_lan_sua": 0,
		"npp_ly_do_canh_bao": _chu(o.get("approval_reason")) or None, "npp_ghi_chu": _chu(o.get("notes")) or None,
		"npp_giam_gia_don": chenh_don, "npp_tru_hang_tra": max(0, L.lam_tron(sub_c + vat_c - tong_c)),
	})
	for d in dong:
		so.append("items", _dong_so(d, d["gia_bang"], cd.kho_ban, cd.cong_ty))
	if cd.mau_thue_ban:
		# bản không kiểm quyền của get_taxes_and_charges (NVBH không có quyền "select" mẫu thuế — method đã kiểm vai ở trên)
		from erpnext.controllers.accounts_controller import _get_taxes_and_charges

		for t in _get_taxes_and_charges("Sales Taxes and Charges Template", cd.mau_thue_ban) or []:
			so.append("taxes", t)
	so.flags.ignore_permissions = True
	try:
		so.insert()
	except frappe.UniqueValidationError:
		# client_request_id vừa được ghi bởi lượt gửi song song (unique_violation trong hàm gốc → đọc lại theo RLS)
		ten = _tim_theo_crid(nc, crid)
		if not ten:
			raise
		return [{"order_id": ten, "order_code": ten, "already_existed": True}]
	frappe.local.message_log = []

	# ---- lịch sử (order_status_history khi tạo thẳng ở trạng thái khác nháp; order_activity_log từng dòng thêm)
	if trang_thai != "draft":
		ghi_nhat_ky_don(so.name, "trang_thai", tu_trang_thai="draft", den_trang_thai=trang_thai)
	for r in so.items:
		ghi_nhat_ky_don(so.name, "dong", hanh_dong="add_line", dong_don=r.name, giai_doan="draft", thay_doi={
			"product_id": r.item_code, "unit_name": r.uom, "quantity": r.qty, "unit_price": r.rate, "line_total": r.amount})
	return [{"order_id": so.name, "order_code": so.name, "already_existed": False}]
