"""RPC Xuất hàng trên Sales Order / Sales Invoice.

post_invoice (mig 125 / 174 / 183 / 186 / 217 / 227): lập + ghi sổ HĐ của một đơn trong MỘT giao dịch — khoá Bin (câu đầu) → khoá đơn →
quyền `orders.approve` → trạng thái đơn → dòng → xuất kho FIFO lô kho bán (gói lô do app lập) → ghi sổ SO → Sales Invoice update_stock
(giảm giá cả đơn sau thuế, không hạ nền thuế) → đơn Hoàn thành (giao thiếu: đóng SO) → chiếu công nợ → nhật ký + báo NV.
Hàng theo lô thiếu tồn luôn chặn (CFD-05); hàng không lô bán vượt khi mặt hàng cho phép + NPP Cai Dat.cho_ban_vuot_ton.

get_invoiceable_lines (mig 124 / 212): dòng của đơn để màn Xuất hàng (POS / điện thoại) dựng hoá đơn — SL đặt, đã xuất, còn lại, giá, giảm,
thuế, tồn kho bán (theo đơn vị kho), cộng dòng HÀNG ĐỔI của phiếu trả nháp / chờ kèm đơn chưa bám HĐ nào. Hàm gốc SECURITY DEFINER, chỉ
kiểm cùng đơn vị — không lọc theo người (POS của chủ / thủ kho mở đơn của mọi NV). Chỉ đọc (GET — POS gọi `{ get: true }`).
"""
from __future__ import annotations

import re
from decimal import Decimal

import frappe
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate, nowtime

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import co_quyen, hien_tai
from nppsale.luat import gia_don as L
from nppsale.luat import xuat_kho as XK
from nppsale.npp_he_thong.doctype.npp_nhat_ky_don.npp_nhat_ky_don import ghi_nhat_ky_don
from nppsale.npp_he_thong.doctype.npp_thong_bao.npp_thong_bao import gui_thong_bao
from nppsale.su_kien.cong_no import chieu_hoa_don
from nppsale.thiet_lap.ban_hang import cai_dat_ban, mau_thue_dong

from . import rpc
from .don_hang import _bang_gia_nhom, _chu, _dam_bao_uom, _gia_bang, _so


def _ton_kho_ban(hang: list[str], kho: str | None) -> dict:
	"""Σ tồn của mặt hàng trong kho bán (đơn vị kho) — = Σ batches.qty_on_hand vùng 'sale' của nppsale."""
	if not hang or not kho:
		return {}
	return {r.item_code: flt(r.actual_qty) for r in frappe.get_all("Bin", filters={"item_code": ("in", hang), "warehouse": kho},
		fields=["item_code", "actual_qty"])}


@rpc("get_invoiceable_lines", ghi=False)
def get_invoiceable_lines(p_order_id=None):
	nc = hien_tai()
	ten = p_order_id if isinstance(p_order_id, str) else None
	if not ten or not frappe.db.exists("Sales Order", ten):
		raise NppLoi("ORDER_NOT_FOUND")
	if not nc.bo_qua_rls and not nc.vai:
		raise NppLoi("ORG_MISMATCH")
	dong = frappe.db.sql(
		"""
		SELECT d.`name`, d.`item_code`, i.`item_name`, d.`uom`, d.`conversion_factor`, d.`qty`, d.`delivered_qty`, d.`rate`,
			i.`npp_gia_ban`, d.`npp_giam_dong`, d.`npp_thue_suat`, i.`npp_thue_suat` AS `thue_sp`, d.`additional_notes`
		FROM `tabSales Order Item` d
		LEFT JOIN `tabItem` i ON i.`name` = d.`item_code`
		WHERE d.`parent` = %s AND d.`parenttype` = 'Sales Order'
		ORDER BY d.`idx`
		""",
		ten,
		as_dict=True,
	)
	ton = _ton_kho_ban(sorted({d.item_code for d in dong}), cai_dat_ban().kho_ban)
	ra = []
	for d in dong:
		da = flt(d.delivered_qty)
		ra.append({
			"order_line_id": d.name, "return_line_id": None, "product_id": d.item_code, "product_name": d.item_name, "sku": d.item_code,
			"unit_name": d.uom, "conversion_factor": flt(d.conversion_factor) or 1, "ordered_qty": flt(d.qty), "invoiced_qty": da,
			"remaining_qty": max(0.0, flt(d.qty) - da), "unit_price": flt(d.rate), "list_price": flt(d.npp_gia_ban),
			"line_discount": flt(d.npp_giam_dong),
			"vat_rate": flt(d.npp_thue_suat if d.npp_thue_suat is not None else (d.thue_sp or 0)),
			"available_base": ton.get(d.item_code, 0.0), "is_exchange": False, "note": d.additional_notes,
		})
	ra.extend(_dong_hang_doi(ten))
	return ra


def _dong_hang_doi(don: str) -> list[dict]:
	"""Dòng hàng đổi của phiếu trả nháp / chờ kèm đơn, chưa bám HĐ (mig 212) — có khi DocType phiếu trả đã dựng."""
	if not frappe.db.exists("DocType", "NPP Phieu Tra"):
		return []
	from nppsale.rpc.phieu_tra import dong_hang_doi_cua_don

	return dong_hang_doi_cua_don(don)


# ================================================================================================ post_invoice (Xuất hàng)
def so_ngay_dieu_khoan(dk: str | None) -> int:
	"""_wf2b_payment_terms_days: số sau "NET" (COD / rỗng / lạ → 0)."""
	m = re.search(r"NET([0-9]+)", (dk or "").upper())
	return int(m.group(1)) if m else 0


def giam_gia_don(gt, tien_hang) -> Decimal:
	"""_giam_gia_don(p, tiền hàng): số tuyệt đối gửi lên (chữ / âm → 0), kẹp trong [0, tiền hàng]."""
	s = "" if gt is None else str(gt)
	d = Decimal(s.strip()) if re.fullmatch(r"\s*[0-9]+(\.[0-9]+)?\s*", s) else Decimal(0)
	return min(max(d, Decimal(0)), max(Decimal(str(tien_hang or 0)), Decimal(0)))


def chuan_he_so(dong: list, hd_cu: str | None = None) -> list:
	"""_chuan_he_so_dong_hoa_don (mig 174 / 247): đơn vị cơ sở → 1; Sửa HĐ: cùng mặt hàng + đơn vị với tờ cũ → hệ số chụp trên tờ cũ;
	đơn vị có trong danh mục → hệ số danh mục; còn lại → hệ số gửi lên (hoặc 1). Không tin hệ số trình duyệt gửi."""
	ra = []
	for x in dong or []:
		if not isinstance(x, dict) or not _chu(x.get("product_id")):
			ra.append(x)
			continue
		hang, dv = _chu(x.get("product_id")), _chu(x.get("unit_name"))
		co_so = frappe.db.get_value("Item", hang, "stock_uom")
		qd = cu = None
		if co_so is not None:
			qd = frappe.db.get_value("UOM Conversion Detail", {"parent": hang, "parenttype": "Item", "uom": dv}, "conversion_factor")
			if hd_cu:
				cu = frappe.db.sql("""SELECT MAX(`conversion_factor`) FROM `tabSales Invoice Item` WHERE `parent` = %s AND `item_code` = %s
					AND `uom` = %s AND `conversion_factor` > 0""", (hd_cu, hang, dv))[0][0]
		if co_so is not None and dv == co_so:
			hs = 1
		elif cu is not None:
			hs = cu
		elif qd is not None:
			hs = qd
		else:
			hs = _so(x.get("conversion_factor"), 1) if x.get("conversion_factor") is not None else 1
		ra.append({**x, "conversion_factor": float(hs)})
	return ra


def _chuan_bi_xuat(p=None):
	"""Đọc trước khi khoá (cổng commit sau bước này): người gọi + quyền, cài đặt bán hàng."""
	nc = hien_tai()
	co_quyen(nc, "orders.approve")
	cai_dat_ban()


def _lo_kho_ban(hang: str, kho: str) -> list[XK.Lo]:
	"""Lô còn hàng của mặt hàng trong kho bán, khoá FIFO = (npp_ngay_nhap, creation, name) — lô hết hạn lõi không cho xuất, đã loại."""
	from erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import get_auto_batch_nos

	ton: dict = {}
	for b in get_auto_batch_nos(frappe._dict(item_code=hang, warehouse=kho, based_on="FIFO", ignore_reserved_stock=True)) or []:
		if b.get("batch_no"):
			ton[b["batch_no"]] = ton.get(b["batch_no"], Decimal(0)) + Decimal(str(b.get("qty") or 0))
	if not ton:
		return []
	tt = {r.name: r for r in frappe.get_all("Batch", filters={"name": ("in", list(ton))},
		fields=["name", "expiry_date", "creation", "npp_ngay_nhap"])}
	ra = []
	for ma, sl in ton.items():
		r = tt.get(ma)
		if not r or sl <= 0:
			continue
		nhan = r.npp_ngay_nhap or r.creation
		ra.append(XK.Lo(ma=ma, ton=sl, han=str(r.expiry_date) if r.expiry_date else XK.HAN_KHONG, khoa_fifo=(str(nhan), str(r.creation), ma)))
	return ra


def _ton_bin(hang: str, kho: str | None) -> Decimal:
	if not kho:
		return Decimal(0)
	return Decimal(str(frappe.db.get_value("Bin", {"item_code": hang, "warehouse": kho}, "actual_qty") or 0))


def _phan_bo_kho(dong: list[dict], cd) -> tuple[dict, Decimal, int]:
	"""post_stock_export trên kho bán: lần lượt từng dòng, FIFO lô; trả {chỉ số dòng: [(lô, SL cơ sở)]}, short_qty, near_expiry_skipped."""
	lo_cua: dict = {}
	da_lay_khong_lo: dict = {}
	phan, thieu_tong, can_han = {}, Decimal(0), 0
	for i, d in enumerate(dong):
		can = Decimal(str(d["sl"])) * Decimal(str(d["hs"]))
		if can <= 0:
			continue
		it = frappe.db.get_value("Item", d["hang"], ["item_name", "has_batch_no", "allow_negative_stock"], as_dict=True)
		if it and it.has_batch_no:
			if d["hang"] not in lo_cua:
				lo_cua[d["hang"]] = _lo_kho_ban(d["hang"], cd.kho_ban)
			kq = XK.chon_lo(lo_cua[d["hang"]], can)
			phan[i] = kq.lay
			can_han += kq.can_han
			thieu = kq.thieu
			duoc_vuot = False  # hàng theo lô: lõi không cho lô âm — luôn chặn (CFD-05, câu 14 B)
		else:
			con = _ton_bin(d["hang"], cd.kho_ban) - da_lay_khong_lo.get(d["hang"], Decimal(0))
			lay = min(max(con, Decimal(0)), can)
			da_lay_khong_lo[d["hang"]] = da_lay_khong_lo.get(d["hang"], Decimal(0)) + can
			thieu = can - lay
			duoc_vuot = bool(it and it.allow_negative_stock and frappe.db.get_single_value("NPP Cai Dat", "cho_ban_vuot_ton"))
		if thieu > 0:
			if not duoc_vuot:
				raise XK.loi_thieu_ton(thieu, (it.item_name if it else None) or d["hang"], _ton_bin(d["hang"], cd.kho_can_date))
			thieu_tong += thieu
	return phan, thieu_tong, can_han


def _goi_lo(si, r, lay: list, cd):
	"""Gói lô Outward do app lập cho một dòng (một dòng một gói — PoC 1c)."""
	from erpnext.stock.serial_batch_bundle import SerialBatchCreation

	b = SerialBatchCreation({"item_code": r.item_code, "warehouse": cd.kho_ban, "posting_date": si.posting_date,
		"posting_time": si.posting_time, "voucher_type": "Sales Invoice", "qty": float(sum(sl for _m, sl in lay)),
		"type_of_transaction": "Outward", "company": si.company, "do_not_submit": True,
		"batches": frappe._dict({m: float(sl) for m, sl in lay})}).make_serial_and_batch_bundle()
	r.serial_and_batch_bundle = b.name
	r.use_serial_batch_fields = 0
	r.batch_no = None


def _nv_giu_no(nv: str | None) -> tuple[str | None, object]:
	"""Ghi sổ HĐ: nợ theo NV đứng tên; NV ấy đã nghỉ → nợ về NPP (trống + mốc) — _cong_no_giu_ve_npp (mig 223)."""
	if nv and frappe.db.get_value("NPP Nhan Vien", nv, "nghi_viec_luc"):
		return None, now_datetime()
	return nv, None


@rpc("post_invoice", ghi=True, chuan_bi=_chuan_bi_xuat)
def post_invoice(p=None):
	nc = hien_tai()
	cd = cai_dat_ban()
	p = p if isinstance(p, dict) else (frappe.parse_json(p) if p else {})
	dong_vao = p.get("lines") if isinstance(p.get("lines"), list) else []
	# Câu ĐẦU TIÊN của giao dịch: khoá Bin của mọi mặt hàng trên HĐ (CFD-05, PoC 1d)
	hang = sorted({_chu(x.get("product_id")) for x in dong_vao if isinstance(x, dict) and _chu(x.get("product_id"))})
	if hang:
		frappe.db.sql("""SELECT `name` FROM `tabBin` WHERE `item_code` IN %(h)s AND `warehouse` IN %(k)s ORDER BY `name` FOR UPDATE""",
			{"h": tuple(hang), "k": tuple(x for x in (cd.kho_ban, cd.kho_can_date) if x) or ("",)})
	if p.get("reissue_of"):
		raise NppLoi("REISSUE_CHUA_HO_TRO: Sửa HĐ dựng ở bước reissue_invoice.")
	dong_vao = chuan_he_so(dong_vao, None)
	don = _chu(p.get("order_id"))
	if not don or not frappe.db.sql("SELECT `name` FROM `tabSales Order` WHERE `name` = %s FOR UPDATE", don):
		raise NppLoi("ORDER_NOT_FOUND")
	so = frappe.get_doc("Sales Order", don)
	if not co_quyen(nc, "orders.approve"):
		raise NppLoi("FORBIDDEN: bạn không có quyền xuất hàng")
	tt = so.get("npp_trang_thai") or "draft"
	if tt not in ("submitted", "partially_invoiced"):
		raise NppLoi(f"ORDER_NOT_INVOICEABLE: đơn {so.name} đang ở trạng thái {tt}, không xuất hàng được")
	co_sl = [x for x in dong_vao if isinstance(x, dict) and (_so(x.get("quantity"), 0) or 0) > 0]
	if not co_sl:
		raise NppLoi("NO_LINES: hóa đơn phải có ít nhất một dòng số lượng > 0")
	dong_don = {r.name: r for r in so.items}
	for x in dong_vao:
		oli = _chu(x.get("order_line_id")) if isinstance(x, dict) else None
		if oli and (oli not in dong_don or dong_don[oli].item_code != _chu(x.get("product_id"))):
			raise NppLoi("BAD_LINE: dòng hóa đơn không thuộc đơn này hoặc sai sản phẩm")
	if (isinstance(p.get("return_adds"), list) and p["return_adds"]) or (isinstance(p.get("return_edits"), list) and p["return_edits"]):
		raise NppLoi("RETURNS_CHUA_HO_TRO: hàng trả kèm HĐ dựng ở bước phiếu trả của P3.")
	ngay = str(getdate(_chu(p.get("invoice_date")) or nowdate()))
	dk = _chu(p.get("payment_terms")) or so.payment_terms_template
	# ---- dòng HĐ (theo thứ tự gửi lên, SL > 0)
	dong = []
	for x in co_sl:
		hang_x = _chu(x.get("product_id"))
		thue = L.thue_hop_le(_chu(x.get("vat_rate")))
		if thue is None:
			thue = float(frappe.db.get_value("Item", hang_x, "npp_thue_suat") or 0)
		dong.append({"hang": hang_x, "dv": _chu(x.get("unit_name")), "hs": _so(x.get("conversion_factor"), 1) or 1,
			"sl": _so(x.get("quantity")), "gia": _so(x.get("unit_price"), 0) or 0, "giam": _so(x.get("line_discount"), 0) or 0,
			"thue": thue, "doi": str(x.get("is_exchange")).lower() == "true", "ghi_chu": _chu(x.get("note")) or None,
			"oli": _chu(x.get("order_line_id"))})
	# ---- xuất kho (FIFO lô kho bán; thiếu → INSUFFICIENT_STOCK)
	phan, thieu, can_han = _phan_bo_kho(dong, cd)
	# ---- ghi sổ đơn (Sales Order nháp → submit; hệ số dòng đơn theo danh mục trước khi ghi sổ — mig 174)
	for d in dong:
		r = dong_don.get(d["oli"]) if d["oli"] else None
		if r is not None and r.uom == d["dv"] and abs(float(r.conversion_factor or 1) - float(d["hs"])) > 1e-9:
			r.conversion_factor = d["hs"]
	so.flags.ignore_permissions = True
	if so.docstatus == 0:
		so.submit()
	# ---- Sales Invoice
	bang_nhom = _bang_gia_nhom(so.customer)
	tien_hang = sum(Decimal(str(d["sl"])) * Decimal(str(d["gia"])) for d in dong)
	giam = giam_gia_don(p.get("discount"), tien_hang)
	nv, ve_npp = _nv_giu_no(so.npp_nhan_vien)
	si = frappe.new_doc("Sales Invoice")
	si.update({
		"naming_series": "HD-.####", "customer": so.customer, "company": cd.cong_ty, "posting_date": ngay, "set_posting_time": 1,
		"posting_time": nowtime(), "update_stock": 1, "set_warehouse": cd.kho_ban, "selling_price_list": so.selling_price_list,
		"ignore_pricing_rule": 1, "disable_rounded_total": 1, "taxes_and_charges": cd.mau_thue_ban, "npp_don_hang": so.name,
		"npp_nhan_vien": so.npp_nhan_vien, "npp_nv_giu_no": nv, "npp_ve_npp_luc": ve_npp,
		"npp_han_thanh_toan": add_days(ngay, so_ngay_dieu_khoan(dk)), "npp_ghi_chu": _chu(p.get("notes")) or None,
	})
	if dk and frappe.db.exists("Payment Terms Template", dk):
		si.payment_terms_template = dk
	else:
		si.due_date = add_days(ngay, so_ngay_dieu_khoan(dk))
	if giam > 0:
		si.update({"apply_discount_on": "Grand Total", "is_cash_or_non_trade_discount": 1, "discount_amount": float(giam),
			"additional_discount_account": cd.tk_giam_gia_don})
	for i, d in enumerate(dong):
		r_don = dong_don.get(d["oli"]) if d["oli"] else None
		noi = r_don is not None and r_don.uom == d["dv"]
		_dam_bao_uom(d["dv"])
		if noi:
			plr = float(r_don.price_list_rate or 0)
		else:
			plr = _gia_bang(d["hang"], d["dv"], bang_nhom) if d["hang"] else 0.0
		gia = float(d["gia"])
		r = si.append("items", {
			"item_code": d["hang"], "qty": d["sl"], "uom": d["dv"], "conversion_factor": d["hs"], "rate": gia, "price_list_rate": plr,
			"discount_percentage": 0, "discount_amount": max(0.0, plr - gia) if plr else 0.0, "margin_type": "", "margin_rate_or_amount": 0,
			"warehouse": cd.kho_ban, "item_tax_template": mau_thue_dong(d["thue"], cd.cong_ty), "npp_thue_suat": d["thue"],
			"npp_giam_dong": float(d["giam"]), "npp_hang_doi": 1 if d["doi"] else 0, "npp_ghi_chu": d["ghi_chu"],
			"sales_order": so.name if noi else None, "so_detail": r_don.name if noi else None,
		})
		if phan.get(i):
			_goi_lo(si, r, phan[i], cd)
	from erpnext.controllers.accounts_controller import _get_taxes_and_charges

	for t in _get_taxes_and_charges("Sales Taxes and Charges Template", cd.mau_thue_ban) or []:
		si.append("taxes", t)
	si.flags.ignore_permissions = True
	si.insert()
	si.submit()
	frappe.local.message_log = []
	# ---- đơn: một đơn một HĐ — xuất (kể cả giao thiếu) là Hoàn thành (mig 217); dòng chưa giao hết → đóng SO
	so.reload()
	if any(float(r.delivered_qty or 0) < float(r.qty or 0) for r in so.items) and so.status not in ("Closed", "Completed"):
		so.update_status("Closed")
		so.reload()
	so.npp_trang_thai = "completed"
	so.flags.ignore_permissions = True
	so.save()
	ghi_nhat_ky_don(so.name, "trang_thai", tu_trang_thai=tt, den_trang_thai="completed")
	no = chieu_hoa_don(si.name)
	ghi_nhat_ky_don(so.name, "dong", hanh_dong="invoice_posted", giai_doan="completed",
		thay_doi={"invoice_id": si.name, "invoice_code": si.name, "entry_id": si.name})
	gui_thong_bao(so.npp_nhan_vien, "order_completed", f"Đơn {so.name} đã xuất hóa đơn {si.name}", None, f"/sales-invoices/{si.name}")
	return [{"invoice_id": si.name, "invoice_code": si.name, "entry_id": si.name, "receivable_id": no, "short_qty": float(thieu),
		"near_expiry_skipped": can_han, "order_status": "completed"}]
