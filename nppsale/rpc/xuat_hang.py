"""RPC Xuất hàng trên Sales Order / Sales Invoice.

post_invoice (mig 125 / 174 / 183 / 186 / 217 / 227): lập + ghi sổ HĐ của một đơn trong MỘT giao dịch — khoá Bin (câu đầu) → khoá đơn →
quyền `orders.approve` → trạng thái đơn → dòng → xuất kho FIFO lô kho bán (gói lô do app lập) → ghi sổ SO → Sales Invoice update_stock
(giảm giá cả đơn sau thuế, không hạ nền thuế) → đơn Hoàn thành (giao thiếu: đóng SO) → chiếu công nợ → nhật ký + báo NV.
Hàng theo lô thiếu tồn luôn chặn (CFD-05); hàng không lô bán vượt khi mặt hàng cho phép + NPP Cai Dat.cho_ban_vuot_ton.

post_invoice nhận hàng trả kèm (return_adds / return_edits, mig 133 / 152 / 180 / 189 / 213): phiếu theo đơn thành phiếu TỰ SINH Chờ xử
lý gắn HĐ, nợ HĐ trừ ngay qua tờ ghi có không kho (nppsale.rpc.phieu_tra).

cancel_invoice (mig 125 / 131 / 135 / 162 / 213 / 217): huỷ HĐ = huỷ đơn — tờ ghi có của phiếu tự sinh huỷ trước, lõi hoàn kho đúng lô (đảo
gói lô), hook on_cancel bỏ dòng công nợ, phiếu tự sinh về Nháp / phiếu tự lập bám tờ Đã huỷ, đơn về submitted rồi Đã huỷ (lý do "Huỷ theo
hóa đơn …", phiếu Nháp / Chờ của đơn huỷ theo), báo NV; khoá khi đã thu tiền / đã phát hành HĐĐT hoặc HĐĐT đang chờ MISA (`_khoa_hddt`) /
có phiếu trả hoàn thành.

reissue_invoice (mig 128 / 152 / 182 / 210 / 213 / 215 / 216 / 227 / 247): Sửa HĐ = huỷ (đơn KHÔNG huỷ theo) + lập tờ mới amend tờ cũ
(`HD-0001-1`) trong CÙNG giao dịch; giữ hệ số tờ cũ, NV đứng tên + người giữ nợ, mặc định ngày / điều khoản / giảm giá của tờ cũ; phiếu
trả của tờ cũ đi theo tờ mới (đã nhập kho: hỏi `tra_da_nhap` lam_lai / giu).

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
from nppsale.luat.giu_no import khi_lap
from nppsale.npp_he_thong.doctype.npp_nhat_ky_don.npp_nhat_ky_don import ghi_nhat_ky_don
from nppsale.npp_he_thong.doctype.npp_thong_bao.npp_thong_bao import gui_thong_bao
from nppsale.su_kien.cong_no import chieu_hoa_don
from nppsale.thiet_lap.ban_hang import cai_dat_ban, mau_thue_dong

from . import rpc
from .don_hang import _bang_gia_nhom, _chu, _dam_bao_uom, _gia_bang, _so

# _da_xuat_cua_dong_don (mig 179): Σ SL × hệ số của dòng HĐ ghi sổ nối dòng đơn (so_detail, hoặc npp_dong_don khi đổi đơn vị lúc xuất)
# ÷ hệ số dòng đơn. Dùng chung cho get_invoiceable_lines và cổng sales_order_lines.invoiced_qty.
DA_XUAT_SQL = ("(SELECT COALESCE(SUM(hi.`qty` * COALESCE(NULLIF(hi.`conversion_factor`, 0), 1)), 0) / "
	"COALESCE(NULLIF({t}.`conversion_factor`, 0), 1) FROM `tabSales Invoice Item` hi WHERE hi.`parenttype` = 'Sales Invoice' "
	"AND hi.`docstatus` = 1 AND (hi.`so_detail` = {t}.`name` OR hi.`npp_dong_don` = {t}.`name`))")


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
		f"""
		SELECT d.`name`, d.`item_code`, i.`item_name`, d.`uom`, d.`conversion_factor`, d.`qty`, {DA_XUAT_SQL.format(t="d")} AS `delivered_qty`, d.`rate`,
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
	"""Ghi sổ HĐ: nợ theo NV đứng tên; NV ấy đã nghỉ → nợ về NPP (trống + mốc) — _cong_no_giu_ve_npp lượt INSERT (mig 223)."""
	from .gan_nguoi import da_nghi

	g = khi_lap(nv, da_nghi, now_datetime())
	return g.nv, g.ve_npp


def _khoa_bin(hang, cd) -> None:
	"""Câu ĐẦU TIÊN của giao dịch ghi kho: khoá Bin của mọi mặt hàng (kho bán + kho cận date) theo thứ tự tên (CFD-05, PoC 1d)."""
	if hang:
		frappe.db.sql("""SELECT `name` FROM `tabBin` WHERE `item_code` IN %(h)s AND `warehouse` IN %(k)s ORDER BY `name` FOR UPDATE""",
			{"h": tuple(sorted(hang)), "k": tuple(x for x in (cd.kho_ban, cd.kho_can_date) if x) or ("",)})


def _hang_cua(dong_vao) -> set:
	return {_chu(x.get("product_id")) for x in dong_vao or [] if isinstance(x, dict) and _chu(x.get("product_id"))}


@rpc("post_invoice", ghi=True, chuan_bi=_chuan_bi_xuat)
def post_invoice(p=None):
	"""Xuất hàng. `reissue_of` chỉ đi qua reissue_invoice (màn Sửa HĐ gọi RPC riêng — post_invoice gốc nhận khoá ấy từ chính
	reissue_invoice); trình duyệt gửi kèm thì từ chối thay vì lập tờ `-n` bên cạnh tờ còn hiệu lực."""
	nc = hien_tai()
	cd = cai_dat_ban()
	p = p if isinstance(p, dict) else (frappe.parse_json(p) if p else {})
	_khoa_bin(_hang_cua(p.get("lines") if isinstance(p.get("lines"), list) else []), cd)
	if p.get("reissue_of"):
		raise NppLoi("REISSUE_QUA_RPC_RIENG: sửa hóa đơn dùng reissue_invoice")
	return [_xuat(nc, cd, p)]


def _xuat(nc, cd, p: dict, *, hd_cu: str | None = None, giu: dict | None = None) -> dict:
	"""Thân post_invoice (Bin đã khoá). Sửa HĐ: `hd_cu` = tờ vừa huỷ — tờ mới amend nó (Amend Counter → `HD-0001-1`), dòng cùng mặt hàng
	+ đơn vị giữ hệ số chụp trên tờ cũ (mig 247), đơn ĐÃ ĐÓNG (dữ liệu cũ) vẫn lập lại được (mig 215); `giu` = NV đứng tên + người giữ
	nợ của tờ cũ (mig 182 / 227 / 246)."""
	dong_vao = p.get("lines") if isinstance(p.get("lines"), list) else []
	dong_vao = chuan_he_so(dong_vao, hd_cu)
	don = _chu(p.get("order_id"))
	if not don or not frappe.db.sql("SELECT `name` FROM `tabSales Order` WHERE `name` = %s FOR UPDATE", don):
		raise NppLoi("ORDER_NOT_FOUND")
	so = frappe.get_doc("Sales Order", don)
	if not co_quyen(nc, "orders.approve"):
		raise NppLoi("FORBIDDEN: bạn không có quyền xuất hàng")
	tt = so.get("npp_trang_thai") or "draft"
	if tt not in ("submitted", "partially_invoiced") and not (tt == "closed" and hd_cu):
		raise NppLoi(f"ORDER_NOT_INVOICEABLE: đơn {so.name} đang ở trạng thái {tt}, không xuất hàng được")
	co_sl = [x for x in dong_vao if isinstance(x, dict) and (_so(x.get("quantity"), 0) or 0) > 0]
	if not co_sl:
		raise NppLoi("NO_LINES: hóa đơn phải có ít nhất một dòng số lượng > 0")
	dong_don = {r.name: r for r in so.items}
	for x in dong_vao:
		oli = _chu(x.get("order_line_id")) if isinstance(x, dict) else None
		if oli and (oli not in dong_don or dong_don[oli].item_code != _chu(x.get("product_id"))):
			raise NppLoi("BAD_LINE: dòng hóa đơn không thuộc đơn này hoặc sai sản phẩm")
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
	# ---- ghi sổ đơn (Sales Order nháp → submit; Sửa HĐ: đơn đã ghi sổ)
	so.flags.ignore_permissions = True
	if so.docstatus == 0:
		so.submit()
	# ---- Sales Invoice
	bang_nhom = _bang_gia_nhom(so.customer)
	tien_hang = sum(Decimal(str(d["sl"])) * Decimal(str(d["gia"])) for d in dong)
	giam = giam_gia_don(p.get("discount"), tien_hang)
	if giu:
		nv_dung_ten, nv, ve_npp, giao = giu.get("nhan_vien"), giu.get("nv_giu_no"), giu.get("ve_npp_luc"), giu.get("giao_tu_nv")
	else:
		nv_dung_ten, giao = so.npp_nhan_vien, None
		nv, ve_npp = _nv_giu_no(so.npp_nhan_vien)
	si = frappe.new_doc("Sales Invoice")
	si.update({
		"naming_series": "HD-.####", "customer": so.customer, "company": cd.cong_ty, "posting_date": ngay, "set_posting_time": 1,
		"posting_time": nowtime(), "update_stock": 1, "set_warehouse": cd.kho_ban, "selling_price_list": so.selling_price_list,
		"ignore_pricing_rule": 1, "disable_rounded_total": 1, "taxes_and_charges": cd.mau_thue_ban, "npp_don_hang": so.name,
		"npp_nhan_vien": nv_dung_ten, "npp_nv_giu_no": nv, "npp_ve_npp_luc": ve_npp, "npp_giao_tu_nv": giao,
		"npp_han_thanh_toan": add_days(ngay, so_ngay_dieu_khoan(dk)), "npp_ghi_chu": _chu(p.get("notes")) or None,
	})
	if hd_cu:
		si.amended_from = hd_cu  # tên tờ mới: Amend Counter của lõi → HD-0001-1, HD-0001-2… (giữ số gốc — mig 128)
	if dk and frappe.db.exists("Payment Terms Template", dk):
		si.payment_terms_template = dk
	else:
		si.due_date = add_days(ngay, so_ngay_dieu_khoan(dk))
	if giam > 0:
		si.update({"apply_discount_on": "Grand Total", "is_cash_or_non_trade_discount": 1, "discount_amount": float(giam),
			"additional_discount_account": cd.tk_giam_gia_don})
	for i, d in enumerate(dong):
		r_don = dong_don.get(d["oli"]) if d["oli"] else None
		# lõi chỉ cho so_detail khi dòng HĐ cùng đơn vị + hệ số với dòng SO (validate_with_previous_doc). Khác (đổi đơn vị lúc xuất, hoặc
		# danh mục đổi hệ số sau khi lên đơn) → không nối so_detail, giữ móc ở npp_dong_don (mig 179); dòng SO giữ nguyên hệ số như nppsale
		noi = r_don is not None and r_don.uom == d["dv"] and abs(flt(r_don.conversion_factor or 1) - flt(d["hs"])) < 1e-9
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
			# đổi đơn vị lúc xuất (mig 179): lõi không cho so_detail khác đơn vị / hệ số → giữ móc dòng đơn ở trường riêng
			"npp_dong_don": r_don.name if r_don is not None and not noi else None,
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
	# ---- hàng trả kèm (mig 133 / 152 / 180 / 189 / 213): dòng thêm (Sửa HĐ đã gỡ return_adds khỏi tải trọng) → câu gắn MỌI phiếu theo
	# đơn chưa gắn HĐ (trừ phiếu tự lập Sửa HĐ giữ lại) → sửa dòng (chỉ lần xuất đầu) → tờ ghi có KHÔNG kho khớp phiếu tự sinh. Lỗi ở đây
	# nổ SAU khi đã xuất kho / lập HĐ → lùi cả giao dịch
	if frappe.db.exists("DocType", "NPP Phieu Tra"):
		from .phieu_tra import ap_sua_tra, ap_tra_them, dong_bo_to_ghi_co, gan_phieu_theo_don

		ap_tra_them(so.name, si.name, p.get("return_adds"), qua_rpc=True)
		gan_phieu_theo_don(so.name, si.name, giu=(giu or {}).get("phieu_tu_lap") or ())
		if not hd_cu:
			ap_sua_tra(si.name, p.get("return_edits"))
		dong_bo_to_ghi_co(si.name, cd)
	# ---- đơn: một đơn một HĐ — xuất (kể cả giao thiếu) là Hoàn thành (mig 217); dòng chưa giao hết → đóng SO
	so.reload()
	if any(float(r.delivered_qty or 0) < float(r.qty or 0) for r in so.items) and so.status not in ("Closed", "Completed"):
		so.update_status("Closed")
		so.reload()
	so.npp_trang_thai = "completed"
	so.flags.ignore_permissions = True
	so.save()
	if tt != "completed":
		ghi_nhat_ky_don(so.name, "trang_thai", tu_trang_thai=tt, den_trang_thai="completed")
	no = chieu_hoa_don(si.name)
	ghi_nhat_ky_don(so.name, "dong", hanh_dong="invoice_posted", giai_doan="completed",
		thay_doi={"invoice_id": si.name, "invoice_code": si.name, "entry_id": si.name})
	gui_thong_bao(so.npp_nhan_vien, "order_completed", f"Đơn {so.name} đã xuất hóa đơn {si.name}", None, f"/sales-invoices/{si.name}")
	return {"invoice_id": si.name, "invoice_code": si.name, "entry_id": si.name, "receivable_id": no, "short_qty": float(thieu),
		"near_expiry_skipped": can_han, "order_status": "completed"}


# ================================================================================================ cancel_invoice (Huỷ HĐ = huỷ đơn)
def _chuan_bi_huy(p_invoice_id=None, p_reason=None, p=None):
	nc = hien_tai()
	co_quyen(nc, "orders.approve")
	cai_dat_ban()


def _tien_da_thu(hd: str, don: str | None = None) -> bool:
	"""LOCKED_HAS_PAYMENT (mig 125, hai nhánh): (a) dòng công nợ của HĐ đã thu > 0 (mọi loại — kể cả dòng tiền thừa mang mã HĐ); (b) còn
	dòng phiếu thu CHƯA huỷ trỏ HĐ, hoặc không trỏ HĐ mà trỏ đơn của HĐ ("thà chặn rộng" — bắt cả dòng rút dư có âm, dòng cấn phiếu trả cũ)."""
	if frappe.db.sql("SELECT 1 FROM `tabNPP Cong No` WHERE `hoa_don` = %s AND `da_thu` > 0 LIMIT 1", hd):
		return True
	if not frappe.db.exists("DocType", "NPP Phieu Thu Dong"):
		return False
	return bool(frappe.db.sql("""SELECT 1 FROM `tabNPP Phieu Thu Dong` d JOIN `tabNPP Phieu Thu` p ON p.`name` = d.`parent`
		WHERE d.`parenttype` = 'NPP Phieu Thu' AND p.`trang_thai` != 'voided'
		AND (d.`hoa_don` = %(hd)s OR (IFNULL(d.`hoa_don`, '') = '' AND d.`don_hang` = %(don)s)) LIMIT 1""", {"hd": hd, "don": don or ""}))


def _khoa_hddt(hd: str) -> None:
	"""LOCKED_EINVOICE (mig 125 `cancel_invoice` — bản đang chạy dòng 66–77; `reissue_invoice` gọi lồng nên Sửa HĐ cũng khoá) — đặc tả HĐĐT §6.1:
	có dòng `NPP HDDT` gắn HĐ bán (`hoa_don_ban` — chỉ nối theo HĐ, dòng chỉ có `don_hang` không khoá) mà (a) `trang_thai` = issued ∨ có
	`misa_inv_no` ∨ `misa_status` ∈ {signed, replaced} → "đã phát hành" (MỘT dòng thoả là khoá; Postgres khoá cả `misa_inv_no = ''` — Frappe coi
	`''` là không số, công cụ nhập đổi `''` → NULL nên hai bên trùng; HĐĐT đã huỷ trên MISA mà còn số vẫn khoá — H12); (b) [H2 — blueprint
	§7.1 điểm 20, chờ chủ nhà chốt] có `misa_ref_id` ∧ `misa_status` ∈ {pending, sent, waiting_code, amount_mismatch} → "đang chờ MISA" (không
	khoá thì có thể ra HĐĐT nháp trên MISA cho một HĐ đã huỷ). [Sửa cuối — phát hiện 13] `amount_mismatch` CHƯA số = MISA đang giữ nháp lệch tiền
	(H10 — mọi HĐ có giảm giá cả đơn): chủ "Huỷ" HĐĐT nội bộ (issued → cancelled — không huỷ gì bên MISA) là lọt cả hai vế; có số thì vế (a) đã
	khoá. Đọc CÓ KHOÁ (LOCK IN SHARE MODE) sau khi đã khoá HĐ bán FOR UPDATE: REPEATABLE READ chụp ảnh ở câu
	đọc thường đầu tiên (PoC 1d) — đọc thường có thể không thấy tờ `phat_hanh` vừa commit; phát hành khoá HĐ bán ở bước giành tờ ⇒ hai đường
	xếp hàng. Giao diện cắt tiền tố mã (`src/lib/orders/post-invoice.ts:218–220`) — người dùng đọc phần sau dấu hai chấm."""
	if frappe.db.sql("""SELECT 1 FROM `tabNPP HDDT` WHERE `hoa_don_ban` = %s
			AND (`trang_thai` = 'issued' OR IFNULL(`misa_inv_no`, '') <> '' OR `misa_status` IN ('signed', 'replaced'))
			LIMIT 1 LOCK IN SHARE MODE""", hd):
		raise NppLoi("LOCKED_EINVOICE: hóa đơn đã phát hành hóa đơn điện tử")
	if frappe.db.sql("""SELECT 1 FROM `tabNPP HDDT` WHERE `hoa_don_ban` = %s AND IFNULL(`misa_ref_id`, '') <> ''
			AND `misa_status` IN ('pending', 'sent', 'waiting_code', 'amount_mismatch') LIMIT 1 LOCK IN SHARE MODE""", hd):
		raise NppLoi("LOCKED_EINVOICE: HĐĐT đang chờ MISA — bấm Làm mới trạng thái trước")


def _hang_cua_hd(hd: str | None) -> set:
	return {r[0] for r in frappe.db.sql("SELECT DISTINCT `item_code` FROM `tabSales Invoice Item` WHERE `parent` = %s", hd)} if hd else set()


@rpc("cancel_invoice", ghi=True, chuan_bi=_chuan_bi_huy)
def cancel_invoice(p_invoice_id=None, p_reason=None):
	"""Huỷ HĐ (mig 217): đơn về Đã huỷ (không về Nháp), hàng về đúng lô đã xuất (lõi đảo gói lô), dòng công nợ bỏ. Sửa HĐ dùng
	reissue_invoice (không huỷ đơn)."""
	nc = hien_tai()
	cd = cai_dat_ban()
	hd = _chu(p_invoice_id)
	_khoa_bin(_hang_cua_hd(hd), cd)
	si, _so_don, tt_don = _huy(nc, cd, hd, p_reason)
	return [{"import_entry_id": si.name, "order_status": tt_don}]


def _huy(nc, cd, hd: str | None, p_reason, *, lap_lai: bool = False):
	"""Thân cancel_invoice (Bin đã khoá). `lap_lai` (Sửa HĐ — cờ `npp.reissue_chuyen_thu` của nppsale): tiền thu không khoá (chuyển sang
	tờ mới — mig 184) và đơn KHÔNG huỷ theo (còn sống để lập tờ mới — `_huy_don_theo_hoa_don`)."""
	# tờ nợ đầu kỳ `DK-` không phải `sales_invoices` của nppsale (Q9 đặc tả phiếu thu) → INVOICE_NOT_FOUND
	if not hd or not frappe.db.sql("""SELECT `name` FROM `tabSales Invoice` WHERE `name` = %s AND `is_return` = 0
			AND IFNULL(`is_opening`, 'No') = 'No' FOR UPDATE""", hd):
		raise NppLoi("INVOICE_NOT_FOUND")
	if not co_quyen(nc, "orders.approve"):
		raise NppLoi("FORBIDDEN: bạn không có quyền huỷ hóa đơn")
	si = frappe.get_doc("Sales Invoice", hd)
	tt_hd = {1: "posted", 2: "cancelled"}.get(si.docstatus, "draft")
	if tt_hd != "posted":
		raise NppLoi(f"INVOICE_NOT_POSTED: hóa đơn {si.name} đang ở trạng thái {tt_hd}")
	from .phieu_tra import _van_ban

	ly_do = _van_ban(p_reason)  # tham số text của PostgREST: số / true / đối tượng JSON thành chữ
	if ly_do is None or ly_do.strip(" ") == "":  # btrim(): chỉ bỏ dấu cách (\n, \t vẫn là lý do)
		raise NppLoi("REASON_REQUIRED: phải ghi lý do huỷ hóa đơn")
	# nppsale ghi nguyên văn (chỉ kiểm sau khi bỏ khoảng trắng)
	don = si.get("npp_don_hang")
	if don:
		frappe.db.sql("SELECT `name` FROM `tabSales Order` WHERE `name` = %s FOR UPDATE", don)
	if not lap_lai and _tien_da_thu(hd, don):
		raise NppLoi("LOCKED_HAS_PAYMENT: hóa đơn đã có tiền thu, huỷ phiếu thu trước")
	_khoa_hddt(hd)  # sau LOCKED_HAS_PAYMENT (bỏ qua khi Sửa HĐ), trước LOCKED_RETURN_DONE — thứ tự của cancel_invoice (mig 125)
	if frappe.db.exists("DocType", "NPP Phieu Tra") and frappe.db.exists("NPP Phieu Tra", {"hoa_don": hd, "trang_thai": "completed"}):
		raise NppLoi("LOCKED_RETURN_DONE: hóa đơn đã có phiếu trả hoàn thành")
	so = frappe.get_doc("Sales Order", don) if don else None
	if so is not None and so.docstatus == 1 and so.status == "Closed":  # lõi đòi mở lại SO đã đóng trước khi huỷ HĐ (bàn bạc 6.12)
		so.update_status("Draft")
	co_pt = frappe.db.exists("DocType", "NPP Phieu Tra")
	if co_pt:
		# tờ ghi có đang ghi sổ gắn HĐ (lúc này chỉ còn tờ không kho của phiếu tự sinh Chờ xử lý): Link npp_hoa_don_goc chặn huỷ HĐ
		from .phieu_tra import huy_to_ghi_co_cua_hd

		huy_to_ghi_co_cua_hd(hd, ly_do)
	# ---- huỷ HĐ: lõi hoàn kho đúng lô qua gói lô, gỡ phân bổ, đảo sổ cái; hook on_cancel chiếu lại công nợ (xoá dòng của tờ)
	dong_no = frappe.db.get_value("NPP Cong No", {"khoa_nguon": f"Sales Invoice:{hd}"}, "name")
	si.npp_ly_do_huy = ly_do
	si.npp_huy_luc = now_datetime()
	si.npp_huy_boi = nc.user if frappe.db.exists("NPP Nhan Vien", nc.user) else None
	si.flags.ignore_permissions = True
	si.cancel()
	frappe.local.message_log = []
	if dong_no and frappe.db.exists("DocType", "NPP Phieu Thu Dong"):
		# dòng công nợ của HĐ đã xoá: dòng phiếu thu (lúc này chỉ của phiếu đã huỷ — hoặc phiếu sống khi Sửa HĐ, gắn lại sau) bỏ receivable_id,
		# giữ invoice_id (mig 125)
		frappe.db.sql("UPDATE `tabNPP Phieu Thu Dong` SET `cong_no` = NULL WHERE `cong_no` = %s", dong_no)
	if co_pt:
		# phiếu tự sinh theo đơn → gỡ HĐ, về Nháp (mig 131 / 135); phiếu còn bám tờ (độc lập / tự lập) → Đã huỷ "Hóa đơn … bị huỷ" (mig 213)
		from .phieu_tra import huy_phieu_khi_huy_hd

		huy_phieu_khi_huy_hd(hd, si.name)
	# ---- đơn: _wf2b_sync_order_status (không còn HĐ ghi sổ → submitted) rồi _huy_don_theo_hoa_don (→ Đã huỷ; Sửa HĐ thì không)
	tt_don = None
	if so is not None:
		so.reload()
		tt_cu = so.get("npp_trang_thai") or "draft"
		tt_don = tt_cu
		if tt_cu not in ("draft", "cancelled"):
			con_hd = frappe.db.count("Sales Invoice", {"npp_don_hang": so.name, "docstatus": 1, "is_return": 0})
			tt_don = "submitted" if con_hd == 0 else "completed"
			if tt_don != tt_cu:
				ghi_nhat_ky_don(so.name, "trang_thai", tu_trang_thai=tt_cu, den_trang_thai=tt_don)
		if tt_don == "submitted" and not lap_lai:
			if co_pt:  # _huy_don_theo_hoa_don (mig 217): mọi phiếu Nháp / Chờ của đơn (gồm phiếu tự sinh vừa về Nháp) huỷ theo
				from .phieu_tra import huy_phieu_theo_don

				huy_phieu_theo_don(so.name, f"Hóa đơn {si.name} bị huỷ — đơn {so.name} huỷ theo")
			so.npp_trang_thai = "cancelled"
			so.npp_huy_luc = now_datetime()
			so.npp_huy_boi = si.npp_huy_boi
			so.npp_ly_do_huy = f"Huỷ theo hóa đơn {si.name}: {ly_do}"
			so.flags.ignore_permissions = True
			if so.docstatus == 1:
				so.cancel()
			else:
				so.save()
			ghi_nhat_ky_don(so.name, "trang_thai", tu_trang_thai="submitted", den_trang_thai="cancelled")
			ghi_nhat_ky_don(so.name, "dong", hanh_dong="cancel_after_complete", giai_doan="cancelled",
				thay_doi={"reason": ly_do, "invoice_code": si.name})
			tt_don = "cancelled"
		elif tt_don != tt_cu:
			so.npp_trang_thai = tt_don
			so.flags.ignore_permissions = True
			so.save()
		ghi_nhat_ky_don(so.name, "dong", hanh_dong="invoice_cancelled", giai_doan=tt_don,
			thay_doi={"invoice_id": si.name, "invoice_code": si.name, "import_entry_id": si.name, "reason": ly_do})
	gui_thong_bao(si.npp_nhan_vien or (so.npp_nhan_vien if so else None), "invoice_cancelled", f"Hóa đơn {si.name} đã bị huỷ", ly_do,
		f"/orders/{don}" if don else None)
	frappe.local.message_log = []
	return si, so, tt_don


# ================================================================================================ reissue_invoice (Sửa HĐ)
def _mac_dinh_lap_lai(hd: str, p: dict) -> dict:
	"""_mac_dinh_lap_lai (mig 213): thiếu ngày / điều khoản → của tờ cũ; vắng khoá `discount` → giảm giá cả đơn của tờ cũ
	(= round(Σ tiền dòng − subtotal), chỉ khi > 0). Gửi `discount` (kể cả 0) là ý định của màn — giữ nguyên."""
	ra = dict(p or {})
	cu = frappe.db.get_value("Sales Invoice", hd, ["posting_date", "payment_terms_template", "net_total", "discount_amount"], as_dict=True)
	if not cu:
		return ra
	if not _chu(ra.get("invoice_date")) and cu.posting_date:
		ra["invoice_date"] = str(cu.posting_date)
	if not _chu(ra.get("payment_terms")) and cu.payment_terms_template:
		ra["payment_terms"] = cu.payment_terms_template
	if "discount" not in ra:
		giam = L.lam_tron(Decimal(str(cu.discount_amount or 0)))  # subtotal của cổng = net_total − giảm cả đơn → Σ dòng − subtotal = giảm
		if giam > 0:
			ra["discount"] = int(giam)
	return ra


@rpc("reissue_invoice", ghi=True, chuan_bi=_chuan_bi_huy)
def reissue_invoice(p_invoice_id=None, p=None):
	"""Sửa HĐ (mig 128 / 149 / 152 / 182 / 184 / 210 / 213 / 215 / 216 / 227 / 246 / 247): huỷ tờ cũ (đơn KHÔNG huỷ theo) rồi lập tờ mới
	trong CÙNG giao dịch — tờ mới amend tờ cũ (`HD-0001-1`), giữ hệ số tờ cũ, giữ NV đứng tên + người giữ nợ, mặc định ngày / điều khoản /
	giảm giá của tờ cũ. Phần phiếu trả chạy TRƯỚC mọi kiểm quyền / trạng thái HĐ (nguyên thứ tự Postgres): phiếu đã nhập kho (hỏi
	`tra_da_nhap`) → sửa / thêm dòng trả trên tờ cũ → gỡ phiếu chờ khỏi tờ cũ → huỷ tờ cũ → lập tờ mới (câu gắn bắt phiếu theo đơn) → gắn
	lại phiếu tự lập / phiếu giữ nhập kho → tờ ghi có khớp phiếu. Lỗi ở bất kỳ bước nào → cả giao dịch lùi, tờ cũ còn nguyên.
	Chưa gồm (báo rõ, không làm dở): chuyển tiền thu sang tờ mới (mig 184 — bước phiếu thu)."""
	nc = hien_tai()
	cd = cai_dat_ban()
	hd = _chu(p_invoice_id)
	p = p if isinstance(p, dict) else (frappe.parse_json(p) if p else {})
	co_pt = bool(frappe.db.exists("DocType", "NPP Phieu Tra"))
	hang = _hang_cua_hd(hd) | _hang_cua(p.get("lines") if isinstance(p.get("lines"), list) else [])
	if co_pt and hd:  # phiếu nhập lại của phiếu trả gắn tờ cũ có thể bị đảo (tra_da_nhap = lam_lai)
		hang |= set(frappe.db.sql_list("""SELECT DISTINCT d.`mat_hang` FROM `tabNPP Phieu Tra Dong` d JOIN `tabNPP Phieu Tra` r
			ON r.`name` = d.`parent` WHERE r.`hoa_don` = %s""", hd))
	_khoa_bin(hang, cd)
	if not hd or not frappe.db.exists("Sales Invoice", {"name": hd, "is_return": 0}):
		raise NppLoi("INVOICE_NOT_FOUND")
	p = _mac_dinh_lap_lai(hd, p)
	cu = frappe.db.get_value("Sales Invoice", hd, ["npp_don_hang", "npp_nhan_vien", "npp_nv_giu_no", "npp_ve_npp_luc", "npp_giao_tu_nv"],
		as_dict=True)
	giu = {"nhan_vien": cu.npp_nhan_vien, "nv_giu_no": cu.npp_nv_giu_no, "ve_npp_luc": cu.npp_ve_npp_luc, "giao_tu_nv": cu.npp_giao_tu_nv}
	# R0 (mig 184): ghi nhớ tiền thu của tờ cũ + huỷ bút toán cấn trừ trỏ tờ / tờ ghi có của tờ TRƯỚC mọi bước có thể huỷ chúng
	tien = None
	if frappe.db.get_value("Sales Invoice", hd, "docstatus") == 1 and frappe.db.exists("DocType", "NPP Phieu Thu"):
		from .can_tru import nho_tien_thu

		tien = nho_tien_thu(hd)
	nho, v_rets, sua = [], [], 0
	if co_pt:
		from .phieu_tra import ap_sua_tra, ap_tra_them, go_phieu_khoi_hd, phieu_tu_lap_cua_hd, tra_da_nhap_truoc

		giu["phieu_tu_lap"] = phieu_tu_lap_cua_hd(hd)  # _mac_dinh_lap_lai (mig 213): câu gắn của tờ mới không biến chúng thành tự sinh
		nho = tra_da_nhap_truoc(hd, p, nc, cd)  # mig 210 / 216
		sua = ap_sua_tra(hd, p.get("return_edits"))  # trần giá tham chiếu dòng tờ CŨ
		ap_tra_them(cu.npp_don_hang, hd, p.get("return_adds"), qua_rpc=False)  # trước khi bật via_rpc: guard áp khi phải dựng phiếu mới
		v_rets = go_phieu_khoi_hd(hd)  # phiếu Nháp / Chờ của tờ cũ → gỡ HĐ (tờ ghi có của chúng huỷ trước — Link chặn huỷ HĐ)
	elif any(isinstance(p.get(k), list) and p[k] for k in ("return_edits", "return_adds")) or _chu(p.get("tra_da_nhap")):
		raise NppLoi("RETURNS_CHUA_HO_TRO: hàng trả kèm khi sửa HĐ cần DocType NPP Phieu Tra.")
	_huy(nc, cd, hd, f"Lập lại hóa đơn {hd}", lap_lai=True)
	tai = {k: v for k, v in p.items() if k != "return_adds"}  # mig 152: gỡ return_adds — không thì dòng trả bị thêm hai lần
	tai["order_id"] = cu.npp_don_hang
	ket = _xuat(nc, cd, tai, hd_cu=hd, giu=giu)
	if co_pt:
		from .phieu_tra import sau_lap_lai

		sau_lap_lai(hd, ket["invoice_id"], v_rets, sua, nho, cu.npp_nhan_vien, cd)
	if tien is not None:
		from .can_tru import chuyen_tien_thu

		chuyen_tien_thu(tien, hd, ket["invoice_id"])  # tiền thu đi theo tờ mới, số phiếu thu không đổi (mig 184)
	if co_pt or tien is not None:
		ket["receivable_id"] = chieu_hoa_don(ket["invoice_id"])
	return [ket]
