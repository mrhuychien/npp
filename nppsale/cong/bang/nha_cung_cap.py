"""Bảng `suppliers` của nppsale trên cổng (blueprint 02 phần Kho Mua §3.6, §5): Supplier lõi + trường npp_*.

Đọc: mọi NV của NPP ("Authenticated can view suppliers", mig 092). Ghi: owner / manager / warehouse thêm / sửa (mig 163); XOÁ cấm
thẳng — chỉ RPC xoa_nha_cung_cap (NCC_XOA_QUA_RPC, mig 233); gộp NCC qua RPC gop_nha_cung_cap.
"""
from __future__ import annotations

from ..dang_ky import Bang, CotDef, dang_ky
from ..loi import NppLoi
from ..sql import LoiCong
from ._chung import GhiDocType, bool_vao, c, org, rls_moi_nv

_ANH_XA = {
	"name": "supplier_name", "code": "npp_ma", "category": "npp_nhom", "tax_code": "tax_id", "payment_terms": "payment_terms",
	"contact_name": "npp_nguoi_lien_he", "phone": "npp_dien_thoai", "email": "npp_email", "address": "npp_dia_chi",
	"legal_name": "npp_ten_phap_ly", "business_type": "npp_loai_hinh", "representative": "npp_dai_dien",
	"business_license_no": "npp_so_dkkd", "business_license_date": "npp_ngay_dkkd", "registered_address": "npp_dia_chi_dkkd",
	"bank_account": "npp_so_tai_khoan", "bank_name": "npp_ngan_hang", "rating": "npp_danh_gia", "is_verified": ("npp_da_xac_minh", bool_vao),
	"notes": "npp_ghi_chu", "is_active": ("npp_ngung_hop_tac", lambda v: 0 if bool_vao(v) else 1),
}


class GhiNcc(GhiDocType):
	def _gan(self, dich, gia_tri):
		g = dict(gia_tri)
		if "credit_limit" in g:
			v = g.pop("credit_limit")
			dich["npp_co_han_muc"] = 0 if v is None else 1
			dich["npp_han_muc"] = v or 0
		super()._gan(dich, g)

	def xoa(self, ids, nc):
		raise NppLoi("NCC_XOA_QUA_RPC: Xoá nhà cung cấp đi qua nút Xoá (kiểm chứng từ trước).", code="P0001")


def _trung_ma(e):
	return LoiCong("23505", 'duplicate key value violates unique constraint "suppliers_org_id_code_key"',
		chi_tiet="Mã NCC đã có (suppliers_org_id_code).", http=409)


def _ep_them(d, g, nc):
	d.setdefault("supplier_group", None)
	if not d.get("supplier_group"):
		import frappe

		d["supplier_group"] = frappe.db.get_single_value("Buying Settings", "supplier_group") or frappe.db.get_value(
			"Supplier Group", {"is_group": 0}, "name")


dang_ky(Bang(
	ten="suppliers",
	nguon="`tabSupplier`",
	cot={
		"id": c("{t}.`name`"), "org_id": org(), "name": c("supplier_name"), "code": c("npp_ma"), "category": c("npp_nhom"),
		"tax_code": c("tax_id"), "payment_terms": c("payment_terms"), "contact_name": c("npp_nguoi_lien_he"), "phone": c("npp_dien_thoai"),
		"email": c("npp_email"), "address": c("npp_dia_chi"), "legal_name": c("npp_ten_phap_ly"), "business_type": c("npp_loai_hinh"),
		"representative": c("npp_dai_dien"), "business_license_no": c("npp_so_dkkd"), "business_license_date": c("npp_ngay_dkkd", "ngay"),
		"registered_address": c("npp_dia_chi_dkkd"), "bank_account": c("npp_so_tai_khoan"), "bank_name": c("npp_ngan_hang"),
		"credit_limit": c("CASE WHEN {t}.`npp_co_han_muc` = 1 THEN {t}.`npp_han_muc` END", "tien"), "rating": c("NULLIF({t}.`npp_danh_gia`, 0)", "so"),
		"is_verified": c("npp_da_xac_minh", "bool"), "notes": c("npp_ghi_chu"), "is_active": c("(1 - {t}.`npp_ngung_hop_tac`)", "bool"),
		"tim_kd": c("npp_tim_kd"), "created_at": c("creation", "gio"),
		"created_by": c("CASE WHEN {t}.`owner` IN ('Administrator', 'Guest') THEN NULL ELSE {t}.`owner` END"), "updated_at": c("modified", "gio"),
	},
	rls=rls_moi_nv,
	ghi=GhiNcc("suppliers", "Supplier", _ANH_XA, vai_them=("owner", "manager", "warehouse"), vai_sua=("owner", "manager", "warehouse"),
		ep_them=_ep_them, bat_trung=_trung_ma),
))

_ = CotDef
