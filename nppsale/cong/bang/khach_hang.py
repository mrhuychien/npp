"""Bảng KHÁCH HÀNG của nppsale trên cổng: customers, customer_groups, customer_assignments, sales_routes, pjp_routes, visit_logs,
customer_photos, customer_photo_requests, ban_giao_khach_log (blueprint 02 §8.1).

customer_select (mig 154 + vá 260): văn phòng (owner / manager / accountant) hoặc quyền `customer.view_all` thấy mọi khách; người khác
thấy khách được phân công (đang active), khách mình tạo, khách có đơn đứng tên mình (`khach_toi_da_ban`).
"""
from __future__ import annotations

import frappe

from ..dang_ky import Bang, CotDef, NguCanh, QuanHe, dang_ky
from ..ngu_canh import co_quyen
from ..sql import LoiCong
from ._chung import GhiDocType, bool_vao, c, co_cot, gio_vao, la_nv, org, rls_moi_nv, so_0, tu_choi

VAN_PHONG = ("owner", "manager", "accountant")


def _thay_moi_khach(nc: NguCanh) -> bool:
	return nc.bo_qua_rls or nc.vai in VAN_PHONG or co_quyen(nc, "customer.view_all")


def ve_khach(nc: NguCanh, cot_khach: str = "{t}.`name`"):
	"""Vế lọc "khách người gọi thấy được" trên một cột chứa mã khách — dùng cho customers và các bảng con của khách."""
	if not la_nv(nc) and not nc.bo_qua_rls:
		return False
	if _thay_moi_khach(nc):
		return None
	phan = [
		f"{cot_khach} IN (SELECT pc.`khach` FROM `tabNPP Phan Cong Khach` pc WHERE pc.`nhan_vien` = %(u)s AND pc.`trang_thai` = 'active')",
		f"{cot_khach} IN (SELECT kh.`name` FROM `tabCustomer` kh WHERE kh.`owner` = %(u)s)",
	]
	if co_cot("Sales Order", "npp_nhan_vien"):
		phan.append(f"{cot_khach} IN (SELECT so.`customer` FROM `tabSales Order` so WHERE so.`npp_nhan_vien` = %(u)s)")
	return ("(" + " OR ".join(phan) + ")", {"u": nc.user})


def thay_khach(nc: NguCanh, khach: str) -> bool:
	"""Một khách cụ thể có nằm trong tập người gọi thấy được không (luật theo dòng của bảng con)."""
	v = ve_khach(nc, "%(k)s")
	if v is None:
		return True
	if v is False:
		return False
	sql, tham = v
	return bool(frappe.db.sql(f"SELECT 1 FROM DUAL WHERE {sql}", {**tham, "k": khach}))


# ----------------------------------------------------------------------------------------------------------------------------
# customers
# ----------------------------------------------------------------------------------------------------------------------------
def _trung_sdt(e):
	return LoiCong("23505", 'duplicate key value violates unique constraint "customers_org_id_phone_key"',
		chi_tiet="Số điện thoại đã có khách khác (customers_org_id_phone).", http=409)


def _xoa_kem_khach(ten: str):
	"""Như ON DELETE CASCADE của nppsale: phân công, lịch tuyến, ảnh (+ file), yêu cầu ảnh đi theo khách. Đơn / HĐ / phiếu trả /
	công nợ / ghé thăm còn trỏ tới thì lõi chặn xoá (LinkExistsError) — đúng FK NO ACTION."""
	for dt in ("NPP Yeu Cau Anh Diem Ban", "NPP Anh Diem Ban", "NPP Lich Tuyen", "NPP Phan Cong Khach"):
		for x in frappe.get_all(dt, filters={"khach": ten}, pluck="name"):
			frappe.flags.npp_duyet_anh_diem_ban = True
			try:
				frappe.delete_doc(dt, x, ignore_permissions=True, force=True)
			finally:
				frappe.flags.npp_duyet_anh_diem_ban = False


def _ep_them_khach(d, g, nc):
	d.setdefault("customer_type", "Company")
	if not d.get("customer_group"):
		d["customer_group"] = frappe.db.get_single_value("Selling Settings", "customer_group") or frappe.db.get_value(
			"Customer Group", {"is_group": 0}, "name")


_ANH_XA_KHACH = {
	"store_name": "customer_name", "owner_name": "npp_chu_cua_hang", "phone": "npp_sdt", "address": "npp_dia_chi", "ward": "npp_phuong",
	"district": "npp_quan", "province": "npp_tinh", "channel": "npp_tuyen", "status": "npp_trang_thai", "credit_limit": "npp_han_muc",
	"gps_lat": ("npp_vi_do", so_0), "gps_lng": ("npp_kinh_do", so_0), "tax_code": "tax_id", "group_id": "customer_group",
	"payment_terms": "payment_terms", "billing_name": "npp_ten_xuat_hd", "billing_address": "npp_dia_chi_xuat_hd",
	"billing_email": "npp_email_xuat_hd", "payment_method_label": "npp_hinh_thuc_tt",
	# Chỉ RPC / việc đêm ghi — gửi kèm thì validate của Customer chặn (DUYET_QUA_NUT) hoặc bỏ qua
	"photo_approved_at": ("npp_duyet_anh_luc", gio_vao), "photo_approved_by": "npp_duyet_anh_boi",
}


class GhiKhach(GhiDocType):
	def them(self, ds, nc):
		ds = [{k: v for k, v in g.items() if k not in ("photo_reminder_sent_at", "route_reminder_sent_at")} for g in ds]
		return super().them(ds, nc)

	def sua(self, gia_tri, ids, nc):
		gia_tri = {k: v for k, v in gia_tri.items() if k not in ("photo_reminder_sent_at", "route_reminder_sent_at")}
		return super().sua(gia_tri, ids, nc)


dang_ky(Bang(
	ten="customers",
	nguon="`tabCustomer`",
	cot={
		"id": c("{t}.`name`"), "org_id": org(), "store_name": c("customer_name"), "owner_name": c("npp_chu_cua_hang"),
		"phone": c("npp_sdt"), "address": c("npp_dia_chi"), "ward": c("npp_phuong"), "district": c("npp_quan"), "province": c("npp_tinh"),
		"channel": c("npp_tuyen"), "status": c("npp_trang_thai"), "credit_limit": c("npp_han_muc", "tien"),
		"gps_lat": c("NULLIF({t}.`npp_vi_do`, 0)", "so"), "gps_lng": c("NULLIF({t}.`npp_kinh_do`, 0)", "so"),
		"tax_code": c("tax_id"), "group_id": c("customer_group"), "payment_terms": c("payment_terms"),
		"created_at": c("creation", "gio"), "created_by": c("CASE WHEN {t}.`owner` IN ('Administrator', 'Guest') THEN NULL ELSE {t}.`owner` END"),
		"photo_approved_at": c("npp_duyet_anh_luc", "gio"), "photo_approved_by": c("npp_duyet_anh_boi"),
		"photo_reminder_sent_at": c("npp_nhac_anh_luc", "gio"), "route_reminder_sent_at": c("npp_nhac_tuyen_luc", "gio"),
		"billing_name": c("npp_ten_xuat_hd"), "billing_address": c("npp_dia_chi_xuat_hd"), "billing_email": c("npp_email_xuat_hd"),
		"payment_method_label": c("npp_hinh_thuc_tt"), "tim_kd": c("npp_tim_kd"), "updated_at": c("modified", "gio"),
	},
	quan_he=[
		QuanHe("customer_groups", "group_id", "id", False, ("customers_group_id_fkey",)),
		QuanHe("customer_assignments", "id", "customer_id", True, ("customer_assignments_customer_id_fkey",)),
		QuanHe("customer_photos", "id", "customer_id", True, ("customer_photos_customer_id_fkey",)),
		QuanHe("users", "photo_approved_by", "id", False, ("customers_photo_approved_by_fkey",)),
		QuanHe("users", "created_by", "id", False, ("customers_created_by_fkey",)),
	],
	rls=lambda nc: ve_khach(nc),
	ghi=GhiKhach("customers", "Customer", _ANH_XA_KHACH, vai_them=("owner", "manager", "sales"), vai_sua=("owner", "manager", "sales"),
		vai_xoa=("owner",), ep_them=_ep_them_khach, truoc_xoa=_xoa_kem_khach, bat_trung=_trung_sdt),
))

dang_ky(Bang(
	ten="customer_groups",
	nguon="(SELECT * FROM `tabCustomer Group` WHERE `is_group` = 0)",
	cot={"id": c("{t}.`name`"), "org_id": org(), "name": c("customer_group_name"), "description": CotDef("NULL"),
		"created_at": c("creation", "gio")},
	rls=rls_moi_nv,
))

# ----------------------------------------------------------------------------------------------------------------------------
# customer_assignments, sales_routes, pjp_routes
# ----------------------------------------------------------------------------------------------------------------------------
dang_ky(Bang(
	ten="customer_assignments",
	nguon="`tabNPP Phan Cong Khach`",
	cot={"id": c("{t}.`name`"), "org_id": org(), "customer_id": c("khach"), "user_id": c("nhan_vien"), "role": c("vai_tro"),
		"assigned_at": c("ngay_phan_cong", "ngay"), "status": c("trang_thai"), "created_at": c("creation", "gio")},
	quan_he=[QuanHe("users", "user_id", "id", False, ("customer_assignments_user_id_fkey",)),
		QuanHe("customers", "customer_id", "id", False, ("customer_assignments_customer_id_fkey",))],
	rls=rls_moi_nv,
	ghi=GhiDocType("customer_assignments", "NPP Phan Cong Khach", {"customer_id": "khach", "user_id": "nhan_vien", "role": "vai_tro",
		"assigned_at": "ngay_phan_cong", "status": "trang_thai"}, vai_them=("owner", "manager"), vai_sua=("owner", "manager"),
		vai_xoa=("owner", "manager"), giu_id=True),
))

dang_ky(Bang(
	ten="sales_routes",
	nguon="`tabNPP Tuyen`",
	cot={"id": c("{t}.`name`"), "org_id": org(), "code": c("ma_tuyen"), "name": c("ten_tuyen"), "description": c("mo_ta"),
		"is_active": c("dang_dung", "bool"), "sort_order": c("thu_tu", "so"), "created_at": c("creation", "gio"),
		"updated_at": c("modified", "gio")},
	rls=rls_moi_nv,
	ghi=GhiDocType("sales_routes", "NPP Tuyen", {"code": "ma_tuyen", "name": "ten_tuyen", "description": "mo_ta",
		"is_active": ("dang_dung", bool_vao), "sort_order": "thu_tu"}, vai_them=("owner", "manager"), vai_sua=("owner", "manager"),
		vai_xoa=("owner", "manager"), giu_id=True,
		bat_trung=lambda e: LoiCong("23505", 'duplicate key value violates unique constraint "sales_routes_org_id_code_key"', http=409)),
))


def _cua_minh_hoac_quan_ly(nc: NguCanh):
	if not la_nv(nc):
		return False
	if nc.vai in ("owner", "manager"):
		return None
	return ("{t}.`nhan_vien` = %(u)s", {"u": nc.user})


dang_ky(Bang(
	ten="pjp_routes",
	nguon="`tabNPP Lich Tuyen`",
	cot={"id": c("{t}.`name`"), "org_id": org(), "sales_user_id": c("nhan_vien"), "day_of_week": c("thu", "so"),
		"customer_id": c("khach"), "visit_order": c("thu_tu_ghe", "so"), "is_active": c("dang_dung", "bool"),
		"created_at": c("creation", "gio")},
	quan_he=[QuanHe("customers", "customer_id", "id", False, ("pjp_routes_customer_id_fkey",)),
		QuanHe("users", "sales_user_id", "id", False, ("pjp_routes_sales_user_id_fkey",))],
	rls=_cua_minh_hoac_quan_ly,
	ghi=GhiDocType("pjp_routes", "NPP Lich Tuyen", {"sales_user_id": "nhan_vien", "day_of_week": "thu", "customer_id": "khach",
		"visit_order": "thu_tu_ghe", "is_active": ("dang_dung", bool_vao)}, vai_them=("owner", "manager"), vai_sua=("owner", "manager"),
		vai_xoa=("owner", "manager"), giu_id=True),
))

# ----------------------------------------------------------------------------------------------------------------------------
# visit_logs — mọi NV ghi lượt ghé của chính mình; văn phòng (owner / manager) xem tất cả
# ----------------------------------------------------------------------------------------------------------------------------


def _ep_nv_la_minh(d, g, nc):
	d["nhan_vien"] = nc.user
	if not d.get("ngay_ghe"):
		d["ngay_ghe"] = frappe.utils.today()


dang_ky(Bang(
	ten="visit_logs",
	nguon="`tabNPP Ghe Tham`",
	cot={"id": c("{t}.`name`"), "org_id": org(), "sales_user_id": c("nhan_vien"), "customer_id": c("khach"),
		"visit_date": c("ngay_ghe", "ngay"), "check_in_at": c("vao_luc", "gio"), "check_out_at": c("ra_luc", "gio"),
		"check_in_lat": c("NULLIF({t}.`vi_do`, 0)", "so"), "check_in_lng": c("NULLIF({t}.`kinh_do`, 0)", "so"),
		"check_in_address": c("dia_chi_vao"), "result": c("NULLIF({t}.`ket_qua`, '')"), "order_id": c("don_hang"), "notes": c("ghi_chu"),
		"photo_url": c("anh_cu"), "created_at": c("creation", "gio")},
	quan_he=[QuanHe("users", "sales_user_id", "id", False, ("visit_logs_sales_user_id_fkey",)),
		QuanHe("customers", "customer_id", "id", False, ("visit_logs_customer_id_fkey",))],
	rls=_cua_minh_hoac_quan_ly,
	ghi=GhiDocType("visit_logs", "NPP Ghe Tham", {"sales_user_id": "nhan_vien", "customer_id": "khach", "visit_date": "ngay_ghe",
		"check_in_at": ("vao_luc", gio_vao), "check_out_at": ("ra_luc", gio_vao), "check_in_lat": ("vi_do", so_0),
		"check_in_lng": ("kinh_do", so_0), "check_in_address": "dia_chi_vao", "result": ("ket_qua", lambda v: v or ""),
		"order_id": "don_hang", "notes": "ghi_chu", "photo_url": "anh_cu"},
		vai_them=("owner", "manager", "accountant", "sales", "warehouse"), vai_sua=("owner", "manager", "accountant", "sales", "warehouse"),
		ep_them=_ep_nv_la_minh, duoc_sua=lambda nc, ten: frappe.db.get_value("NPP Ghe Tham", ten, "nhan_vien") == nc.user, giu_id=True),
))

# ----------------------------------------------------------------------------------------------------------------------------
# customer_photos, customer_photo_requests, ban_giao_khach_log
# ----------------------------------------------------------------------------------------------------------------------------


def _ep_nguoi_chup(d, g, nc):
	d["nguoi_tai"] = nc.user
	if not thay_khach(nc, d.get("khach") or ""):
		tu_choi("customer_photos")


def _anh_cua_khach_thay(nc, ten):
	return thay_khach(nc, frappe.db.get_value("NPP Anh Diem Ban", ten, "khach") or "")


dang_ky(Bang(
	ten="customer_photos",
	nguon="`tabNPP Anh Diem Ban`",
	cot={"id": c("{t}.`name`"), "org_id": org(), "customer_id": c("khach"), "slot": c("o_anh", "so"), "photo_url": c("anh_url"),
		"taken_at": c("chup_luc", "gio"), "gps_lat": c("NULLIF({t}.`vi_do`, 0)", "so"), "gps_lng": c("NULLIF({t}.`kinh_do`, 0)", "so"),
		"gps_accuracy": c("NULLIF({t}.`sai_so`, 0)", "so"), "uploaded_by": c("nguoi_tai"), "created_at": c("creation", "gio")},
	quan_he=[QuanHe("customers", "customer_id", "id", False, ("customer_photos_customer_id_fkey",)),
		QuanHe("users", "uploaded_by", "id", False, ("customer_photos_uploaded_by_fkey",))],
	rls=lambda nc: ve_khach(nc, "{t}.`khach`"),
	ghi=GhiDocType("customer_photos", "NPP Anh Diem Ban", {"customer_id": "khach", "slot": "o_anh", "photo_url": "anh_url",
		"taken_at": ("chup_luc", gio_vao), "gps_lat": ("vi_do", so_0), "gps_lng": ("kinh_do", so_0), "gps_accuracy": ("sai_so", so_0),
		"uploaded_by": "nguoi_tai"}, vai_them=("owner", "manager", "sales"), vai_sua=("owner", "manager", "sales"),
		vai_xoa=("owner", "manager", "sales"), ep_them=_ep_nguoi_chup, duoc_sua=_anh_cua_khach_thay, duoc_xoa=_anh_cua_khach_thay,
		giu_id=True, bat_trung=lambda e: LoiCong("23505", 'duplicate key value violates unique constraint "customer_photos_customer_id_slot_key"',
			http=409)),
))

dang_ky(Bang(
	ten="customer_photo_requests",
	nguon="`tabNPP Yeu Cau Anh Diem Ban`",
	cot={"id": c("{t}.`name`"), "org_id": org(), "customer_id": c("khach"), "kind": c("loai"), "photo_id": c("anh"), "slot": c("o_anh", "so"),
		"photo_url": c("anh_url"), "taken_at": c("chup_luc", "gio"), "gps_lat": c("NULLIF({t}.`vi_do`, 0)", "so"),
		"gps_lng": c("NULLIF({t}.`kinh_do`, 0)", "so"), "gps_accuracy": c("NULLIF({t}.`sai_so`, 0)", "so"),
		"pin_lat": c("NULLIF({t}.`vi_do_ghim`, 0)", "so"), "pin_lng": c("NULLIF({t}.`kinh_do_ghim`, 0)", "so"), "status": c("trang_thai"),
		"requested_by": c("nguoi_xin"), "requested_at": c("xin_luc", "gio"), "decided_by": c("nguoi_duyet"), "decided_at": c("duyet_luc", "gio"),
		"decision_note": c("ghi_chu_duyet"), "created_at": c("creation", "gio")},
	quan_he=[QuanHe("users", "requested_by", "id", False, ("customer_photo_requests_requested_by_fkey",)),
		QuanHe("users", "decided_by", "id", False, ("customer_photo_requests_decided_by_fkey",)),
		QuanHe("customers", "customer_id", "id", False, ("customer_photo_requests_customer_id_fkey",))],
	rls=lambda nc: ve_khach(nc, "{t}.`khach`"),
))

dang_ky(Bang(
	ten="ban_giao_khach_log",
	nguon="`tabNPP Ban Giao Khach`",
	cot={"id": c("{t}.`name`"), "org_id": org(), "nguon": c("nguon"), "tu_nv": c("tu_nv"), "den_nv": c("den_nv"), "kieu": c("kieu"),
		"bo_loc": c("bo_loc", "json"), "khach": c("khach", "json"), "ket_qua": c("ket_qua", "json"), "tao_boi": c("tao_boi"),
		"tao_luc": c("tao_luc", "gio")},
	rls=lambda nc: None if nc.vai in ("owner", "manager") or nc.bo_qua_rls else False,
))
