"""Công nợ phải thu = bản chiếu thuần từ sổ (blueprint 02 §4.3.0, quyết định Q2).

`NPP Cong No` không có trường nào người dùng ghi: số tiền lấy từ Payment Ledger Entry của lõi, trạng thái nghiệp vụ (NV giữ nợ, dấu bàn
giao, mốc về NPP, hạn, dấu quá hạn, ghi chú) nằm ở trường `allow_on_submit` của chứng từ nguồn. Hàm chiếu tính lại được bất cứ lúc nào.

Dòng của HĐ / tờ nợ đầu kỳ: nhóm = {HĐ} ∪ {tờ ghi có độc lập gắn HĐ (`npp_hoa_don_goc`), đã ghi sổ}.
  so_tien = grand_total HĐ + Σ grand_total (âm) của tờ ghi có gắn — = total − credits của `_wf2b_recompute_receivable`
  con_no  = Σ Payment Ledger Entry.amount (delinked = 0) có against_voucher thuộc nhóm — âm = dư có
  da_thu  = so_tien − con_no;  trang_thai — một luật (`_cong_no_am_trang_thai`, mig 212)
Chứng từ nguồn không còn ghi sổ → xoá dòng.
"""
from __future__ import annotations

import frappe
from frappe.utils import flt, now_datetime

DT = "NPP Cong No"


def trang_thai(so_tien: float, da_thu: float, qua_han_tay: bool) -> str:
	"""_cong_no_am_trang_thai (mig 212): nợ âm (dư có) chỉ 'paid' khi dùng hết; trả dư là 'open' (dư có, trừ vào tổng nợ)."""
	if so_tien < 0:
		return "paid" if abs(da_thu - so_tien) < 0.01 else "open"
	if abs(da_thu - so_tien) < 0.01:
		return "paid"
	if da_thu > so_tien:
		return "open"
	if qua_han_tay:
		return "overdue"
	if da_thu > 0:
		return "partial"
	return "open"


def _con_no(nhom: list[str]) -> float:
	if not nhom:
		return 0.0
	return flt(frappe.db.sql("""SELECT COALESCE(SUM(`amount`), 0) FROM `tabPayment Ledger Entry`
		WHERE `against_voucher_type` = 'Sales Invoice' AND `against_voucher_no` IN %(n)s AND `delinked` = 0""", {"n": tuple(nhom)})[0][0])


def _ghi(khoa: str, gia_tri: dict) -> str:
	ten = frappe.db.get_value(DT, {"khoa_nguon": khoa}, "name")
	if ten:
		doc = frappe.get_doc(DT, ten)
		doc.update(gia_tri)
		doc.flags.ignore_permissions = True
		doc.save()
		return doc.name
	doc = frappe.get_doc({"doctype": DT, "khoa_nguon": khoa, **gia_tri})
	doc.insert(ignore_permissions=True)
	return doc.name


def chieu_hoa_don(ten: str) -> str | None:
	"""Chiếu dòng công nợ của một HĐ bán / tờ nợ đầu kỳ (không phải tờ ghi có). Trả tên dòng (receivable_id) hoặc None."""
	si = frappe.db.get_value("Sales Invoice", ten, ["name", "docstatus", "is_return", "customer", "grand_total", "creation", "due_date",
		"npp_don_hang", "npp_nv_giu_no", "npp_giao_tu_nv", "npp_ve_npp_luc", "npp_han_thanh_toan", "npp_qua_han_tay", "npp_ghi_chu"],
		as_dict=True)
	if not si or si.is_return:
		return None
	khoa = f"Sales Invoice:{ten}"
	if si.docstatus != 1:
		frappe.db.delete(DT, {"khoa_nguon": khoa})  # xoá thẳng — dòng phiếu thu đã huỷ có thể còn trỏ tới (blueprint §4.3)
		return None
	ghi_co = frappe.get_all("Sales Invoice", filters={"is_return": 1, "npp_hoa_don_goc": ten, "docstatus": 1},
		fields=["name", "grand_total"]) if frappe.db.has_column("Sales Invoice", "npp_hoa_don_goc") else []
	so_tien = flt(si.grand_total) + sum(flt(x.grand_total) for x in ghi_co)
	con_no = _con_no([ten, *(x.name for x in ghi_co)])
	da_thu = so_tien - con_no
	dau_ky = ten.startswith("DK-")
	return _ghi(khoa, {
		"loai": "dau_ky" if dau_ky else "hoa_don", "khach_hang": si.customer, "hoa_don": ten, "don_hang": si.npp_don_hang,
		"nhan_vien": si.npp_nv_giu_no, "giao_tu_nv": si.npp_giao_tu_nv, "ve_npp_luc": si.npp_ve_npp_luc,
		"so_tien": so_tien, "da_thu": da_thu, "con_no": con_no, "han_thanh_toan": si.npp_han_thanh_toan or si.due_date,
		"trang_thai": trang_thai(so_tien, da_thu, bool(si.npp_qua_han_tay)), "qua_han_tay": 1 if si.npp_qua_han_tay else 0,
		"ghi_chu": si.npp_ghi_chu if dau_ky else None, "tao_luc": si.creation, "tinh_luc": now_datetime(),
	})


# Trường người giữ nợ trên chứng từ nguồn của từng loại dòng (blueprint 02 §5.6): (người giữ, mốc về NPP, dấu bàn giao)
TRUONG_GIU = {"Sales Invoice": ("npp_nv_giu_no", "npp_ve_npp_luc", "npp_giao_tu_nv"),
	"NPP Phieu Thu": ("nv_giu_tien_thua", "ve_npp_luc", "giao_tu_nv")}


def dat_nguoi_giu(dong: str, nv: str | None, ve_npp_luc) -> None:
	"""Chế độ GIAO NỢ (`npp.giao_cong_no` — RPC nghỉ việc / giao nợ / bàn giao): đặt thẳng người giữ của MỘT dòng công nợ trên chứng từ
	nguồn; có người giữ thì bỏ mốc về NPP (`_cong_no_giu_ve_npp`); dấu bàn giao giữ nguyên. Rồi chiếu lại dòng."""
	khoa = frappe.db.get_value(DT, dong, "khoa_nguon")
	dt, _, ten = (khoa or "").partition(":")
	truong = TRUONG_GIU.get(dt)
	if not truong or not ten:
		frappe.throw(f"Không rõ chứng từ nguồn của dòng công nợ {dong} ({khoa})")
	frappe.db.set_value(dt, ten, {truong[0]: nv, truong[1]: None if nv else ve_npp_luc}, update_modified=False)
	if dt == "Sales Invoice":
		chieu_nguon_cua(frappe.db.get_value("Sales Invoice", ten, ["name", "is_return", "npp_hoa_don_goc"], as_dict=True))


def chieu_nguon_cua(si) -> None:
	"""Mọi dòng công nợ chịu ảnh hưởng của một Sales Invoice (HĐ: chính nó; tờ ghi có: HĐ gắn)."""
	if si.get("is_return"):
		goc = si.get("npp_hoa_don_goc")
		if goc:
			chieu_hoa_don(goc)
		return
	chieu_hoa_don(si.name)


# ------------------------------------------------------------------------------------------------ doc_events
def sau_ghi_so_hoa_don(doc, method=None):
	chieu_nguon_cua(doc)


def sau_thanh_toan(doc, method=None):
	"""Payment Entry ghi sổ / huỷ: chiếu lại mọi HĐ được phân bổ."""
	for r in doc.get("references") or []:
		if r.reference_doctype == "Sales Invoice" and r.reference_name:
			si = frappe.db.get_value("Sales Invoice", r.reference_name, ["name", "is_return", "npp_hoa_don_goc"], as_dict=True)
			if si:
				chieu_nguon_cua(si)
