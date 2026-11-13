"""RPC assign_doc_seller (mig 160 / 194 / 223 / 246): chủ NPP / quản lý đổi NGƯỜI ĐỨNG TÊN hoá đơn (hoặc phiếu trả tự lập không gắn HĐ).

Đổi người trên HĐ (mọi trạng thái — cả tờ đã huỷ) → dòng công nợ của HĐ đi theo (trigger `_hoa_don_doi_nguoi`) nhưng NGƯỜI GIỮ NỢ theo luật
`_cong_no_giu_ve_npp` (nppsale.luat.giu_no): nợ đã về NPP đứng yên, dấu bàn giao giữ NV nhận, người mới đã nghỉ việc thì giữ người cũ.
Phiếu trả gắn HĐ đi theo người của HĐ (thêm khi có NPP Phieu Tra). Người được gán: NV bán hàng / quản lý / chủ đang hoạt động.
"""
from __future__ import annotations

import frappe
from frappe.utils import cint, now_datetime

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai
from nppsale.luat.giu_no import GiuNo, khi_doi_nguoi
from nppsale.su_kien.cong_no import chieu_hoa_don

from . import rpc
from .don_hang import _chu


def da_nghi(nv: str | None) -> bool:
	return bool(nv) and bool(frappe.db.get_value("NPP Nhan Vien", nv, "nghi_viec_luc"))


def doi_nguoi_hoa_don(hd: str, nv_moi: str) -> None:
	"""UPDATE sales_invoices SET sales_user_id + trigger `_hoa_don_doi_nguoi`: dòng nợ của HĐ (chỉ khi người giữ khác người mới — `IS
	DISTINCT FROM`) đổi theo luật giữ nợ; chiếu lại công nợ."""
	si = frappe.db.get_value("Sales Invoice", hd, ["docstatus", "npp_nv_giu_no", "npp_ve_npp_luc", "npp_giao_tu_nv"], as_dict=True)
	gt = {"npp_nhan_vien": nv_moi}
	if si.docstatus == 1 and si.npp_nv_giu_no != nv_moi:  # HĐ ghi sổ mới có dòng nợ (tờ huỷ: dòng đã bỏ)
		moi = khi_doi_nguoi(GiuNo(si.npp_nv_giu_no, si.npp_ve_npp_luc, si.npp_giao_tu_nv), nv_moi, da_nghi, now_datetime())
		gt.update({"npp_nv_giu_no": moi.nv, "npp_ve_npp_luc": moi.ve_npp, "npp_giao_tu_nv": moi.giao})
	frappe.db.set_value("Sales Invoice", hd, gt)
	if si.docstatus == 1:
		chieu_hoa_don(hd)


@rpc("assign_doc_seller", ghi=True)
def assign_doc_seller(p_kind=None, p_id=None, p_user=None):
	nc = hien_tai()
	if nc.vai not in ("owner", "manager"):
		raise NppLoi("ASSIGN_FORBIDDEN: chỉ NPP (chủ / quản lý) được gán người phụ trách")
	u = _chu(p_user)
	nv = frappe.db.get_value("NPP Nhan Vien", u, ["vai", "dang_hoat_dong"], as_dict=True) if u else None
	if not nv or nv.vai not in ("sales", "manager", "owner") or not cint(nv.dang_hoat_dong):
		raise NppLoi("ASSIGN_BAD_USER: người được gán phải là nhân viên bán hàng / quản lý / chủ đang hoạt động của đơn vị")
	if p_kind == "invoice":
		hd = _chu(p_id)
		if not hd or not frappe.db.exists("Sales Invoice", {"name": hd, "is_return": 0}):
			raise NppLoi("DOC_NOT_FOUND: không tìm thấy hóa đơn")
		doi_nguoi_hoa_don(hd, u)
	elif p_kind == "return":
		pt = _chu(p_id)
		if not pt or not frappe.db.exists("DocType", "NPP Phieu Tra") or not frappe.db.exists("NPP Phieu Tra", pt):
			raise NppLoi("DOC_NOT_FOUND: không tìm thấy phiếu trả")
		from nppsale.rpc.phieu_tra import doi_nguoi_phieu_tra

		doi_nguoi_phieu_tra(pt, u)
	else:
		raise NppLoi(f"ASSIGN_BAD_KIND: {p_kind}")
	return None
