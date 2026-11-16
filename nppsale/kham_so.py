"""KHÁM SỔ — chỉ đọc, không sửa gì. Mỗi dòng ra là một chứng từ cần xem; không ra dòng nào là sổ sạch.

phieu_tra(): bản ERPNext của `scripts/sql/kiem-phieu-tra.sql` (nppsale — chủ nhà 25/09/2026: "quét lại hết phiếu trả hàng xem có phiếu nào
ở trạng thái chờ xử lý mà chưa trừ công nợ ko ?") + bất biến riêng của bản ERPNext (tờ ghi có ↔ phiếu, phiếu nhập kho ↔ phiếu):
  1. Phiếu TỰ SINH Chờ xử lý / Hoàn thành có tiền mà không đúng MỘT tờ ghi có không kho đang ghi sổ = −tiền trả (cùng HĐ).
  2. Phiếu TỰ LẬP đang Chờ xử lý (luật mig 191: không được có).
  3. Hàng trả theo đơn KẸT NHÁP dù đơn đã xuất HĐ (lỗi trước mig 189).
  4. Phiếu tự lập độc lập Hoàn thành có tiền mà không có dòng công nợ âm / tờ ghi có lệch tiền.
  5. Phiếu tự lập Hoàn thành gắn HĐ có tiền mà tờ ghi có có kho không gắn đúng HĐ / lệch tiền.
  6. Công nợ HĐ lệch công thức: tiền HĐ − Σ tiền phiếu đã trừ (phiếu tự sinh Chờ xử lý / Hoàn thành, phiếu tự lập Hoàn thành).
  7. Phiếu Hoàn thành theo ĐƠN mà chưa gắn HĐ (mig 200).
  8. Phiếu tự sinh Hoàn thành có dòng mà không có phiếu nhập kho đang ghi sổ (hoặc phiếu chưa hoàn thành vẫn giữ phiếu nhập).
Nhóm 5 / 8 của nppsale (cấn phiếu trả ở phiếu thu kiểu cũ — applied_receipt_id) không port: bản ERPNext không có lối ấy.

	bench --site <site> execute nppsale.kham_so.phieu_tra

cong_no(): bản ERPNext của `scripts/sql/quet/phieu-thu-cong-no.sql` (mig 164) + bất biến bản chiếu công nợ (đặc tả phiếu thu §1.7).

hddt(): hoá đơn điện tử MISA — bản Frappe của `supabase/diagnostics/einvoice_lost_refid.sql` + `einvoice_unknown_enums.sql` (đặc tả HĐĐT §6.4,
+ [Soát thiếu 2]) và các bất biến riêng của bản Frappe (tờ treo, nhật ký lượt đêm, trùng số đã chuẩn hoá, khoá Huỷ HĐ). Trả {can_xem, thong_ke}.

	bench --site <site> execute nppsale.kham_so.hddt
"""
from __future__ import annotations

import json

import frappe
from frappe.utils import cint, flt

DT = "NPP Phieu Tra"


def _dong(nhom: int, loai: str, chung_tu: str, khach: str | None, tien, chi_tiet: str, nen_lam: str) -> dict:
	return {"nhom": nhom, "loai": loai, "chung_tu": chung_tu, "khach": khach, "tien_tra": flt(tien), "chi_tiet": chi_tiet, "nen_lam": nen_lam}


def _tru_cua_hd() -> dict:
	"""Khoản trừ của từng HĐ — luật creditCounted (= `_wf2b_recompute_receivable` mig 133 / 186)."""
	return {r[0]: flt(r[1]) for r in frappe.db.sql(f"""SELECT `hoa_don`, SUM(IFNULL(`tien_tra`, 0)) FROM `tab{DT}`
		WHERE IFNULL(`hoa_don`, '') != '' AND ((`tu_sinh` = 1 AND `trang_thai` IN ('submitted', 'completed'))
			OR (`tu_sinh` = 0 AND `trang_thai` = 'completed')) GROUP BY `hoa_don`""")}


@frappe.whitelist()
def phieu_tra() -> list[dict]:
	frappe.only_for(("System Manager", "Administrator"))
	return quet_phieu_tra()


def quet_phieu_tra() -> list[dict]:
	ra: list[dict] = []
	if not frappe.db.exists("DocType", DT):
		return ra
	ten_khach = dict(frappe.db.sql("SELECT `name`, `customer_name` FROM `tabCustomer`"))
	pts = frappe.get_all(DT, fields=["name", "trang_thai", "tu_sinh", "tien_tra", "khach_hang", "hoa_don", "don_hang", "to_ghi_co",
		"phieu_nhap_kho", "creation"], order_by="name asc")
	# tờ ghi có đang ghi sổ theo phiếu
	to = {}
	for t in frappe.get_all("Sales Invoice", filters={"is_return": 1, "docstatus": 1, "npp_phieu_tra": ("is", "set")},
			fields=["name", "npp_phieu_tra", "npp_hoa_don_goc", "update_stock", "grand_total"]):
		to.setdefault(t.npp_phieu_tra, []).append(t)
	nhap = {r[0]: r[1] for r in frappe.db.sql("""SELECT `npp_phieu_tra`, COUNT(*) FROM `tabStock Entry`
		WHERE `docstatus` = 1 AND IFNULL(`npp_phieu_tra`, '') != '' GROUP BY `npp_phieu_tra`""")}
	co_dong = {r[0] for r in frappe.db.sql("""SELECT DISTINCT `parent` FROM `tabNPP Phieu Tra Dong` WHERE `parenttype` = %s AND `so_luong` > 0""",
		(DT,))}
	for p in pts:
		kh = ten_khach.get(p.khach_hang) or p.khach_hang
		tien = flt(p.tien_tra)
		dang = to.get(p.name, [])
		khong_kho = [t for t in dang if not t.update_stock]
		co_kho = [t for t in dang if t.update_stock]
		if p.tu_sinh and p.trang_thai in ("submitted", "completed") and p.hoa_don:
			can = 1 if tien != 0 else 0
			dung = len(khong_kho) == can and (not can or (khong_kho[0].npp_hoa_don_goc == p.hoa_don
				and abs(flt(khong_kho[0].grand_total) + tien) < 0.5 and p.to_ghi_co == khong_kho[0].name))
			if not dung:
				ra.append(_dong(1, "Phiếu tự sinh — tờ ghi có không khớp phiếu", p.name, kh, tien,
					f"{len(khong_kho)} tờ đang ghi sổ ({', '.join(f'{t.name} {flt(t.grand_total):g}' for t in khong_kho) or 'không có'}) — "
					f"phải là {can} tờ = {-tien:g} gắn {p.hoa_don}",
					"Chạy lại dong_bo_to_ghi_co(HĐ); vẫn còn thì báo lại"))
		elif khong_kho:
			ra.append(_dong(1, "Tờ ghi có không kho còn ghi sổ của phiếu không còn trừ vào HĐ", p.name, kh, tien,
				", ".join(t.name for t in khong_kho), "Huỷ tờ ghi có thừa"))
		if not p.tu_sinh and p.trang_thai == "submitted":
			ra.append(_dong(2, "Phiếu tự lập đang Chờ xử lý (chưa trừ nợ, chưa nhập kho)", p.name, kh, tien,
				f"Lập {frappe.utils.formatdate(p.creation, 'dd/MM/yyyy')}", "Về Nháp; bấm Hoàn thành thì mới nhập kho + trừ nợ"))
		if p.trang_thai == "draft" and not p.hoa_don and p.don_hang and tien > 0:
			hd = frappe.db.sql("""SELECT COUNT(*) FROM `tabSales Invoice` WHERE `npp_don_hang` = %s AND `docstatus` = 1 AND `is_return` = 0
				AND `creation` >= %s""", (p.don_hang, p.creation))[0][0]
			if hd:
				ra.append(_dong(3, "Hàng trả theo đơn kẹt Nháp — đơn đã xuất HĐ, công nợ không trừ", p.don_hang, kh, tien,
					f"Đơn có {hd} hóa đơn đã ghi sổ", "Gắn phiếu vào HĐ của đơn (câu gắn của post_invoice) rồi tính lại công nợ"))
		if not p.tu_sinh and p.trang_thai == "completed" and not p.hoa_don and not p.don_hang and tien != 0:
			no = frappe.db.get_value("NPP Cong No", {"khoa_nguon": f"{DT}:{p.name}"}, "so_tien")
			if no is None or abs(flt(no) + tien) >= 0.5 or len(co_kho) != 1 or abs(flt(co_kho[0].grand_total) + tien) >= 0.5:
				ra.append(_dong(4, "Phiếu tự lập độc lập đã hoàn thành — công nợ âm / tờ ghi có lệch", p.name, kh, tien,
					f"Công nợ {no if no is not None else 'KHÔNG CÓ DÒNG'}; tờ có kho: "
					f"{', '.join(f'{t.name} {flt(t.grand_total):g}' for t in co_kho) or 'không có'}",
					"Chiếu lại công nợ (chieu_phieu_tra); tờ lệch thì ghi nhận lại phiếu"))
		if not p.tu_sinh and p.trang_thai == "completed" and p.hoa_don and tien != 0:
			if len(co_kho) != 1 or co_kho[0].npp_hoa_don_goc != p.hoa_don or abs(flt(co_kho[0].grand_total) + tien) >= 0.5:
				ra.append(_dong(5, "Phiếu tự lập gắn HĐ đã hoàn thành — tờ ghi có không gắn đúng HĐ / lệch tiền", p.name, kh, tien,
					", ".join(f"{t.name} {flt(t.grand_total):g} → {t.npp_hoa_don_goc or '—'}" for t in co_kho) or "không có tờ có kho",
					"Đặt npp_hoa_don_goc của tờ = HĐ của phiếu rồi chiếu lại công nợ HĐ"))
		if p.trang_thai == "completed" and not p.hoa_don and p.don_hang:
			ra.append(_dong(7, "Phiếu hoàn thành theo ĐƠN, chưa gắn HĐ", p.name, kh, tien, f"Đơn {p.don_hang}",
				"Đơn 1 HĐ: gắn HĐ ấy; 0 hoặc nhiều HĐ: gắn tay vào đúng HĐ (hoặc huỷ phiếu)"))
		if p.tu_sinh:
			n = nhap.get(p.name, 0)
			if p.trang_thai == "completed" and p.name in co_dong and (n != 1 or not p.phieu_nhap_kho):
				ra.append(_dong(8, "Phiếu tự sinh đã nhập kho — phiếu nhập kho không khớp", p.name, kh, tien,
					f"{n} phiếu nhập đang ghi sổ, phieu_nhap_kho = {p.phieu_nhap_kho or 'trống'}", "Báo lại — không tự sửa kho"))
			elif p.trang_thai != "completed" and n:
				ra.append(_dong(8, "Phiếu tự sinh chưa hoàn thành mà còn phiếu nhập kho đang ghi sổ", p.name, kh, tien,
					f"{n} phiếu nhập đang ghi sổ", "Huỷ phiếu nhập thừa (huỷ nhập kho của phiếu)"))
	# 6. công nợ HĐ lệch công thức
	tru = _tru_cua_hd()
	for h in frappe.get_all("Sales Invoice", filters={"is_return": 0, "docstatus": 1, "name": ("in", list(tru) or [""])},
			fields=["name", "customer", "grand_total"]):
		no = frappe.db.get_value("NPP Cong No", {"khoa_nguon": f"Sales Invoice:{h.name}"}, "so_tien")
		dung = flt(h.grand_total) - tru[h.name]
		if no is None or abs(flt(no) - dung) >= 0.5:
			ra.append(_dong(6, "Công nợ HĐ lệch với tiền hàng trả", h.name, ten_khach.get(h.customer) or h.customer, tru[h.name],
				f"Công nợ {no if no is not None else 'KHÔNG CÓ DÒNG'} — đúng phải là {dung:g}", "Chiếu lại công nợ HĐ (chieu_hoa_don)"))
	ra.sort(key=lambda x: (x["nhom"], x["chung_tu"]))
	return ra


# ================================================================================================ công nợ ↔ phiếu thu (P3d)
@frappe.whitelist()
def cong_no() -> list[dict]:
	frappe.only_for(("System Manager", "Administrator"))
	return quet_cong_no()


def quet_cong_no(khach: list[str] | None = None) -> list[dict]:
	"""Bản ERPNext của `scripts/sql/quet/phieu-thu-cong-no.sql` (mig 164, INV1–INV5) + bất biến của bản chiếu (đặc tả phiếu thu §1.7):
	  10. Σ còn nợ các dòng công nợ của khách ≠ Σ Payment Ledger (delinked = 0) của khách (dòng chiếu thiếu / thừa / cũ).
	  11. Dòng công nợ: còn nợ / trạng thái lệch với sổ (chiếu cũ) — INV2.
	  12. Phiếu thu: tiền thu ≠ Σ dòng `payment` (INV4); Payment Entry cùng tên lệch tiền / sai trạng thái so với phiếu.
	  13. Bút toán cấn trừ CTR- / bút toán chuyển tiền thu vượt (`chuyen_tien_thua`) không cân, hoặc còn ghi sổ khi phiếu sở hữu đã huỷ; phiếu thu
	      sống mà Payment Entry còn tiền chưa phân bổ (dòng `tien_thua` — lưới an toàn, RPC không bao giờ để lại).
	  14. Dòng phiếu thu SỐNG trỏ HĐ đã huỷ / mất dòng công nợ (INV5)."""
	from nppsale.su_kien import cong_no as CN

	ra: list[dict] = []
	if not frappe.db.exists("DocType", "NPP Cong No"):
		return ra
	ten_khach = dict(frappe.db.sql("SELECT `name`, `customer_name` FROM `tabCustomer`"))
	loc_kh = {"khach_hang": ("in", khach)} if khach else {}
	so_cai = dict(frappe.db.sql("""SELECT `party`, SUM(`amount`) FROM `tabPayment Ledger Entry` WHERE `party_type` = 'Customer' AND `delinked` = 0
		AND `account_type` = 'Receivable' GROUP BY `party`"""))
	chieu: dict[str, float] = {}
	for r in frappe.get_all("NPP Cong No", filters=loc_kh, fields=["name", "loai", "khach_hang", "hoa_don", "phieu_tra", "phieu_thu", "so_tien",
			"da_thu", "con_no", "trang_thai", "qua_han_tay"]):
		chieu[r.khach_hang] = chieu.get(r.khach_hang, 0.0) + flt(r.con_no)
		that = CN.con_no_dong(r)
		tt = CN.trang_thai(flt(r.so_tien), flt(r.so_tien) - that, bool(r.qua_han_tay))
		if abs(that - flt(r.con_no)) >= 0.5 or tt != r.trang_thai:
			ra.append(_dong(11, "Dòng công nợ lệch sổ (chiếu cũ)", r.name, ten_khach.get(r.khach_hang), r.con_no,
				f"{r.loai}: còn nợ {flt(r.con_no):g} / sổ {that:g}; trạng thái {r.trang_thai} / đúng {tt}", "Chiếu lại dòng (chieu_dong)"))
	for kh in sorted(set(chieu) | ({k for k in so_cai if not khach or k in khach})):
		if abs(chieu.get(kh, 0.0) - flt(so_cai.get(kh))) >= 0.5:
			ra.append(_dong(10, "Công nợ khách lệch sổ cái", kh, ten_khach.get(kh), chieu.get(kh, 0.0),
				f"Σ dòng công nợ {chieu.get(kh, 0.0):g} — Σ sổ cái {flt(so_cai.get(kh)):g}",
				"Chạy kham_so_cong_no; còn lệch thì tìm chứng từ không thuộc nhóm nào (bút toán lõi bị gỡ tham chiếu)"))
	if frappe.db.exists("DocType", "NPP Phieu Thu"):
		co_loai = frappe.get_meta("Journal Entry").has_field("npp_loai")
		for p in frappe.get_all("NPP Phieu Thu", filters=loc_kh, fields=["name", "khach_hang", "trang_thai", "tien_thu", "but_toan_tien",
				"but_toan_can_tru"]):
			kh = ten_khach.get(p.khach_hang)
			if p.trang_thai != "voided":
				tong = flt(frappe.db.sql("""SELECT SUM(`so_tien`) FROM `tabNPP Phieu Thu Dong` WHERE `parent` = %s AND `parenttype` = 'NPP Phieu Thu'
					AND `loai` = 'payment'""", p.name)[0][0])
				if abs(tong - flt(p.tien_thu)) >= 0.5:
					ra.append(_dong(12, "Phiếu thu: tiền thu ≠ Σ dòng tiền (INV4)", p.name, kh, p.tien_thu, f"Σ dòng payment {tong:g}", "Báo lại"))
			pe = frappe.db.get_value("Payment Entry", p.but_toan_tien, ["docstatus", "paid_amount"], as_dict=True) if p.but_toan_tien else None
			can_pe = p.trang_thai != "voided" and flt(p.tien_thu) > 0
			if (can_pe and (not pe or pe.docstatus != 1 or abs(flt(pe.paid_amount) - flt(p.tien_thu)) >= 0.5)) or (
					not can_pe and pe and pe.docstatus == 1):
				ra.append(_dong(12, "Phiếu thu ↔ Payment Entry lệch", p.name, kh, p.tien_thu,
					f"PE {p.but_toan_tien or '—'}: {pe.docstatus if pe else 'không có'} / {flt(pe.paid_amount) if pe else 0:g}", "Báo lại — không tự sửa"))
			je = frappe.db.get_value("Journal Entry", p.but_toan_can_tru, ["docstatus", "total_debit", "total_credit"], as_dict=True) \
				if p.but_toan_can_tru else None
			if je and ((p.trang_thai == "voided" and je.docstatus == 1) or (je.docstatus == 1 and abs(flt(je.total_debit) - flt(je.total_credit)) >= 0.5)):
				ra.append(_dong(13, "Bút toán cấn trừ sai trạng thái / không cân", p.name, kh, je.total_debit,
					f"{p.but_toan_can_tru}: docstatus {je.docstatus}, Nợ {flt(je.total_debit):g} / Có {flt(je.total_credit):g}", "Báo lại"))
			# Sửa HĐ giảm tiền: phần thu vượt chuyển vào HĐ mới (bút toán `chuyen_tien_thua`, phương án B của Q1) — RPC luôn phân bổ hết tiền phiếu
			if co_loai:
				for cj in frappe.get_all("Journal Entry", filters={"npp_phieu_thu": p.name, "npp_loai": "chuyen_tien_thua", "docstatus": 1},
						fields=["name", "total_debit", "total_credit"]):
					if p.trang_thai == "voided" or abs(flt(cj.total_debit) - flt(cj.total_credit)) >= 0.5:
						ra.append(_dong(13, "Bút toán chuyển tiền thu vượt sai trạng thái / không cân", p.name, kh, cj.total_debit,
							f"{cj.name}: phiếu {p.trang_thai}, Nợ {flt(cj.total_debit):g} / Có {flt(cj.total_credit):g}", "Báo lại"))
			# theo Payment Ledger (trường unallocated_amount của PE không trừ bút toán trỏ PE — bút toán chuyển của Sửa HĐ)
			treo = -CN._con_no([p.but_toan_tien], "Payment Entry") if can_pe and pe and pe.docstatus == 1 else 0.0
			if treo >= 0.5:
				ra.append(_dong(13, "Phiếu thu còn tiền chưa phân bổ (Payment Entry treo tiền ngoài app)", p.name, kh, treo,
					f"{p.but_toan_tien}: chưa phân bổ {treo:g} — dòng công nợ `tien_thua` đang giữ số này", "Báo lại — không tự sửa"))
		for d in frappe.db.sql("""SELECT d.`parent`, d.`name`, d.`hoa_don`, d.`cong_no`, p.`khach_hang` FROM `tabNPP Phieu Thu Dong` d
				JOIN `tabNPP Phieu Thu` p ON p.`name` = d.`parent` WHERE d.`parenttype` = 'NPP Phieu Thu' AND p.`trang_thai` != 'voided'""", as_dict=True):
			if khach and d.khach_hang not in khach:
				continue
			huy = d.hoa_don and frappe.db.get_value("Sales Invoice", d.hoa_don, "docstatus") == 2
			mat = not d.cong_no or not frappe.db.exists("NPP Cong No", d.cong_no)
			if huy or mat:
				ra.append(_dong(14, "Dòng phiếu thu sống trỏ HĐ đã huỷ / mất dòng công nợ (INV5)", d.parent, ten_khach.get(d.khach_hang), 0,
					f"dòng {d.name}: HĐ {d.hoa_don or '—'}{' (đã huỷ)' if huy else ''}, công nợ {d.cong_no or 'trống'}", "Báo lại"))
	ra.sort(key=lambda x: (x["nhom"], x["chung_tu"]))
	return ra


def kham_so_cong_no() -> None:
	"""Việc đêm 01:00 (đặc tả phiếu thu §2.5.3): khách có Payment Ledger đổi trong ngày → chiếu lại mọi dòng + mọi HĐ / phiếu trả / phiếu thu của
	khách, rồi khám; còn lệch → Error Log (không tự sửa chứng từ)."""
	from frappe.utils import add_days, now_datetime

	from nppsale.su_kien import cong_no as CN

	khach = frappe.db.sql_list("""SELECT DISTINCT `party` FROM `tabPayment Ledger Entry` WHERE `party_type` = 'Customer'
		AND `modified` >= %s""", add_days(now_datetime(), -1))
	for kh in khach:
		for si in frappe.get_all("Sales Invoice", filters={"customer": kh, "docstatus": ("in", (1, 2))},
				fields=["name", "is_return", "npp_hoa_don_goc", "npp_phieu_tra"]):
			CN.chieu_nguon_cua(si)
		for r in frappe.get_all("NPP Cong No", filters={"khach_hang": kh}, fields=["name", "loai", "hoa_don", "phieu_tra", "phieu_thu"]):
			CN.chieu_dong(r)
		if frappe.db.exists("DocType", "NPP Phieu Thu"):
			for ph in frappe.get_all("NPP Phieu Thu", filters={"khach_hang": kh}, pluck="name"):
				CN.chieu_tien_thua(ph)
	lech = quet_cong_no(khach) if khach else []
	frappe.db.commit()
	if lech:
		frappe.log_error(title=f"Khám sổ công nợ: {len(lech)} chỗ lệch", message=frappe.as_json(lech[:200], indent=1))


# ================================================================================================ hoá đơn điện tử MISA (HĐĐT)
NHOM_HDDT = ("1", "2", "2a", "2b", "2c", "3a", "3b", "4", "5a", "5b", "5c", "5d")  # thứ tự in
TRAN_DONG_HDDT = 500  # mỗi nhóm in tối đa (như LIMIT 500 của einvoice_lost_refid.sql); quy mô đủ ở `thong_ke`
QUAN_HE_DA_BIET = ("1", "3", "4", "7", "8")  # EInvoiceStatus đã đo (status.ts:40–52) — lưu bằng so_js nên so chữ
PHAT_HANH_DA_BIET = ("0", "3")  # PublishStatus đã đo: 0 nháp, 3 đã cấp mã
GIO_LUOT_DEM = 26  # dòng sync_run mới nhất cũ hơn 26 giờ ⇒ lịch 01:00 không chạy (scheduler tắt / hàng long không có worker)
NGAY_TREO = 1  # `pending` gửi quá 1 ngày ⇒ vòng quét đêm không gỡ được


def _dong_hddt(nhom: str, loai: str, chung_tu, chi_tiet: str, nen_lam: str, **them) -> dict:
	return {"nhom": nhom, "loai": loai, "chung_tu": chung_tu, "chi_tiet": chi_tiet, "nen_lam": nen_lam, **them}


def _ngay_vn_hddt(gio):
	"""Giờ site → ngày VN (như `nppsale.lich.misa._ngay_vn`) — None giữ None."""
	if not gio:
		return None
	from nppsale.lich.misa import _ngay_vn

	return _ngay_vn(gio)


def _ky_so(ky_hieu, so) -> str:
	return f"{ky_hieu or '?'} · {so or '?'}"


@frappe.whitelist()
def hddt() -> dict:
	frappe.only_for(("System Manager", "Administrator"))
	return quet_hddt()


def quet_hddt(luc=None) -> dict:
	"""Khám sổ HĐĐT (chỉ đọc) → {can_xem: [dòng {nhom, loai, chung_tu, chi_tiet, nen_lam, …}] — rỗng là sổ sạch; thong_ke: quy mô / đếm}.

	1. Tờ MẤT RefID (`misa_inv_no` có ∧ `misa_ref_id` trống — mig 099 bước 4b: cột `misa_invoice_id` kiêm hai vai, Làm mới ghi số ĐÈ RefID): không
	   còn đường hỏi MISA (huỷ / thay thế sau này không ai biết; vòng quét bỏ qua — quét bằng khoá sai còn tệ hơn không quét). [1b] RefID TÌM LẠI ĐƯỢC
	   từ nhật ký (truy vấn 3 của einvoice_lost_refid.sql): NPP MISA Log `publish` / `success` mới nhất có `gui_di` là MẢNG mang `[0].RefID` → cột
	   `refid_tim_duoc` (xác nhận bằng GET ?refID= trước khi gán). [1c] quy mô (truy vấn 1) ở `thong_ke.mat_refid`.
	   Đường xử lý (thay `UPDATE invoices SET misa_ref_id = …, misa_note = NULL` chạy tay của nppsale): (a) System Manager điền `misa_ref_id` trên
	   Desk (validate cho điền khi đang trống — I1) rồi bấm Làm mới; KHÔNG xoá `misa_note` (dòng "MẤT RefID" ở lại làm vết — H7); (b) chắc tờ CHƯA
	   phát hành trên MISA: xoá `misa_inv_no` / `misa_inv_series` / `misa_inv_date` / `misa_lookup_code` / `misa_invoice_code` / `misa_status` trên
	   Desk rồi bấm Phát hành (thiếu bước xoá thì H23 trả kết quả cũ, không đẩy).
	2. Enum MISA lạ (einvoice_unknown_enums.sql): [2] snapshot `einvoice_status` ∉ {1,3,4,7,8} (số tờ, ngày sớm / muộn nhất, 5 tờ mẫu, 3 RefID mẫu);
	   [2c] `publish_status` ∉ {0,3} (số tờ, số tờ có mã CQT — manh mối mạnh nhất "đã phát hành", số tờ có số, 5 tờ mẫu); [2a] dòng sổ mang ghi chú
	   "không rõ nghĩa" (đứng im ở trạng thái có thể đã cũ); [2b] cờ huỷ ĐÃ KÍCH HOẠT theo tên trường (`ban_ghi_tho.{IsInvoiceDeleted | IsInvoiceCanceled
	   | IsCanceled | IsCancelled}` đúng `true` kiểu bool) — ra tên khác `IsInvoiceDeleted` là phải sửa thứ tự `_CO_HUY` (nppsale/luat/hddt.py). Đọc
	   được nghĩa rồi thì khai vào nppsale/luat/hddt.py — chỗ DUY NHẤT (Làm mới + vòng quét cùng đi qua) — mở đúng tờ trên MISA, đừng đoán.
	3. Tờ treo: [3a] `pending` gửi quá 1 ngày (vòng quét đêm không gỡ được: ngoài cửa sổ / MISA lỗi / lịch không chạy); [3b] `error` có RefID (MISA
	   từ chối / lỗi kết nối — chờ người sửa rồi Phát hành lại cùng RefID).
	4. Dòng `sync_run` mới nhất cũ hơn 26 giờ (hoặc chưa có) khi cấu hình MISA đã lưu + đang dùng — lịch 01:00 không chạy.
	5. [5a] Trùng số đã chuẩn hoá giữa hai tờ (`trung_so`: cùng `chuan_so` ∧ cùng ký hiệu chặt ∨ một bên trống — chỉ mục duy nhất so nguyên văn
	   không bắt); [5b] hai dòng cùng HĐ bán (nppsale đẻ được khi đua; Frappe khoá HĐ bán trong `dam_bao_dong`); [5c] dòng LẼ RA khoá Huỷ HĐ (đủ vế
	   `LOCKED_EINVOICE` — §6.1) mà HĐ bán đã huỷ; [5d] `issued` thiếu cả `phat_hanh_luc` lẫn `misa_sent_at` — không bao giờ vào cửa sổ vòng quét (H14).
	6. Sức khoẻ đối soát (truy vấn 5): số dòng + Σ |tổng tiền| theo `ket_qua_khop` (kể cả "(chưa đối soát)") ở `thong_ke.doi_soat`."""
	from frappe.utils import add_to_date, now_datetime

	from nppsale.luat.hddt import _CO_HUY, chuan_so, trung_so
	from nppsale.npp_hddt.doctype.npp_misa_cau_hinh.npp_misa_cau_hinh import da_luu

	ra: list[dict] = []
	tk: dict = {}
	if not frappe.db.exists("DocType", "NPP HDDT"):
		return {"can_xem": ra, "thong_ke": tk}
	luc = luc or now_datetime()

	# 1 / 1b / 1c — mất RefID
	mat = frappe.db.sql("""SELECT `name`, `so_hd_go_tay`, `misa_inv_series`, `misa_inv_no`, `misa_status`, `nguoi_mua`, `tong_tien`, `phat_hanh_luc`,
			`misa_lookup_code` FROM `tabNPP HDDT` WHERE IFNULL(`misa_inv_no`, '') <> '' AND IFNULL(`misa_ref_id`, '') = ''
		ORDER BY `phat_hanh_luc` IS NULL, `phat_hanh_luc` DESC, `name`""", as_dict=True)
	tim = {}
	if mat:
		for nk in frappe.db.sql("""SELECT `hddt`, `gui_di`, `goi_luc` FROM `tabNPP MISA Log` WHERE `hddt` IN %(ds)s AND `nguon` = 'publish'
				AND `ket_qua` = 'success' ORDER BY `goi_luc` DESC, `creation` DESC""", {"ds": tuple(m.name for m in mat)}, as_dict=True):
			if nk.hddt in tim:
				continue
			try:
				gui = json.loads(nk.gui_di) if nk.gui_di else None
			except ValueError:
				continue
			ref = gui[0].get("RefID") if isinstance(gui, list) and gui and isinstance(gui[0], dict) else None
			if ref not in (None, ""):
				tim[nk.hddt] = (str(ref), nk.goi_luc)
	ngay = [_ngay_vn_hddt(m.phat_hanh_luc) for m in mat if m.phat_hanh_luc]
	tk["mat_refid"] = {"so_hoa_don": len(mat), "tong_tien": sum(flt(m.tong_tien) for m in mat), "cu_nhat": min(ngay) if ngay else None,
		"moi_nhat": max(ngay) if ngay else None, "tim_lai_duoc": len(tim)}
	for m in sorted(mat, key=lambda x: x.name not in tim)[:TRAN_DONG_HDDT]:  # tờ tìm lại được RefID lên trước (ổn định theo ngày phát hành)
		ref = tim.get(m.name)
		ra.append(_dong_hddt("1", "Hoá đơn điện tử MẤT RefID — không tra cứu lại được trên MISA", m.name,
			f"{_ky_so(m.misa_inv_series, m.misa_inv_no)} · {m.misa_status or 'trống'} · {m.nguoi_mua} · {flt(m.tong_tien):g}",
			(f"RefID tìm lại từ nhật ký phát hành ({ref[1]}): {ref[0]} — xác nhận bằng GET ?refID= rồi System Manager điền misa_ref_id trên Desk, bấm "
				"Làm mới" if ref else "(a) Mở MISA tìm theo ký hiệu + số, chép RefID, System Manager điền misa_ref_id trên Desk rồi bấm Làm mới; (b) chắc "
				"chưa phát hành trên MISA: xoá misa_inv_no / misa_inv_series / misa_inv_date / misa_lookup_code / misa_invoice_code / misa_status rồi "
				"Phát hành") + " — không xoá misa_note",
			so_noi_bo=m.so_hd_go_tay, ky_hieu=m.misa_inv_series, so_misa=m.misa_inv_no, trang_thai=m.misa_status, khach_hang=m.nguoi_mua,
			tong_tien=flt(m.tong_tien), ngay_phat_hanh=_ngay_vn_hddt(m.phat_hanh_luc), ma_tra_cuu=m.misa_lookup_code,
			refid_tim_duoc=ref[0] if ref else None))

	# 2 / 2c — enum lạ trên snapshot
	if frappe.db.exists("DocType", "NPP MISA Snapshot"):
		def mau(cot: str, v: str, n: int, *truong) -> list:
			return frappe.db.sql(f"""SELECT {', '.join(f'`{t}`' for t in truong)} FROM `tabNPP MISA Snapshot` WHERE `{cot}` = %s
				ORDER BY `ngay_phat_hanh` IS NULL, `ngay_phat_hanh` DESC, `name` LIMIT {int(n)}""", v, as_dict=True)

		for r in frappe.db.sql("""SELECT `einvoice_status` AS v, COUNT(*) AS n, MIN(`ngay_phat_hanh`) AS som, MAX(`ngay_phat_hanh`) AS muon
				FROM `tabNPP MISA Snapshot` WHERE IFNULL(`einvoice_status`, '') <> '' AND `einvoice_status` NOT IN %(biet)s
				GROUP BY `einvoice_status` ORDER BY n DESC, v""", {"biet": QUAN_HE_DA_BIET}, as_dict=True):
			m5 = mau("einvoice_status", r.v, 5, "ky_hieu", "so_hddt", "ref_id")
			ra.append(_dong_hddt("2", "EInvoiceStatus MISA chưa biết nghĩa (trục quan hệ)", f"EInvoiceStatus={r.v}",
				f"{r.n} tờ, {r.som or '?'} → {r.muon or '?'}; mẫu: {', '.join(_ky_so(x.ky_hieu, x.so_hddt) for x in m5)}",
				"Mở các tờ mẫu trên MISA, đọc ô 'Trạng thái hoá đơn' rồi khai nghĩa vào _QUAN_HE (nppsale/luat/hddt.py) — đừng đoán từ tên / số lượng",
				gia_tri=r.v, so_hoa_don=r.n, som_nhat=r.som, muon_nhat=r.muon, hoa_don_mau=[_ky_so(x.ky_hieu, x.so_hddt) for x in m5],
				ref_id_mau=[x.ref_id for x in m5[:3]]))
		for r in frappe.db.sql("""SELECT `publish_status` AS v, COUNT(*) AS n, SUM(IFNULL(`ma_cqt`, '') <> '') AS co_ma,
					SUM(IFNULL(`so_hddt`, '') <> '') AS co_so
				FROM `tabNPP MISA Snapshot` WHERE IFNULL(`publish_status`, '') <> '' AND `publish_status` NOT IN %(biet)s
				GROUP BY `publish_status` ORDER BY n DESC, v""", {"biet": PHAT_HANH_DA_BIET}, as_dict=True):
			m5 = mau("publish_status", r.v, 5, "ky_hieu", "so_hddt")
			ra.append(_dong_hddt("2c", "PublishStatus MISA chưa biết nghĩa (trục phát hành)", f"PublishStatus={r.v}",
				f"{r.n} tờ, {int(r.co_ma or 0)} có mã CQT, {int(r.co_so or 0)} đã cấp số; mẫu: {', '.join(_ky_so(x.ky_hieu, x.so_hddt) for x in m5)}",
				"Giá trị LUÔN đi kèm mã CQT gần như chắc là một dạng 'đã phát hành' — mở tờ mẫu trên MISA, đọc chữ trên màn rồi khai vào suy_trang_thai "
				"(nppsale/luat/hddt.py); chưa khai thì tờ giữ nguyên trạng thái + ghi chú",
				gia_tri=r.v, so_hoa_don=r.n, co_ma_cqt=int(r.co_ma or 0), da_cap_so=int(r.co_so or 0),
				hoa_don_mau=[_ky_so(x.ky_hieu, x.so_hddt) for x in m5]))
		# 2b — cờ huỷ theo tên trường: chỉ `true` kiểu bool (chuỗi "true" không tính — như doc_ban_ghi; MariaDB so JSON_EXTRACT với 'true' khớp cả
		# chuỗi "true" nên phải xét JSON_TYPE)
		dem = frappe.db.sql("SELECT " + ", ".join(
			f"SUM(IFNULL(JSON_TYPE(JSON_EXTRACT(`ban_ghi_tho`, '$.{k}')) = 'BOOLEAN' AND JSON_EXTRACT(`ban_ghi_tho`, '$.{k}') = 'true', 0)) AS `{k}`"
			for k in _CO_HUY) + " FROM `tabNPP MISA Snapshot`", as_dict=True)[0]
		tk["co_huy_theo_ten"] = {k: int(dem[k] or 0) for k in _CO_HUY}
		for k in _CO_HUY[1:]:
			if tk["co_huy_theo_ten"][k]:
				ra.append(_dong_hddt("2b", "Cờ huỷ của MISA mang tên khác IsInvoiceDeleted", k, f"{tk['co_huy_theo_ten'][k]} snapshot có {k} = true",
					"Tài khoản MISA này dùng tên khác — sửa thứ tự _CO_HUY (nppsale/luat/hddt.py) cho đúng, rồi Làm mới các tờ liên quan"))
		tk["doi_soat"] = [{"ro": r.ro, "so_dong": int(r.so_dong), "tong_tien_tuyet_doi": flt(r.tien)} for r in frappe.db.sql("""SELECT
				IFNULL(NULLIF(`ket_qua_khop`, ''), '(chưa đối soát)') AS ro, COUNT(*) AS so_dong, SUM(ABS(IF(`co_tong_tien`, `tong_tien`, 0))) AS tien
			FROM `tabNPP MISA Snapshot` GROUP BY ro ORDER BY so_dong DESC, ro""", as_dict=True)]
	for r in frappe.db.sql(f"""SELECT `name`, `misa_inv_series`, `misa_inv_no`, `misa_status`, `tong_tien`, `misa_last_checked_at`, `misa_note`
			FROM `tabNPP HDDT` WHERE `misa_note` LIKE %s ORDER BY `phat_hanh_luc` IS NULL, `phat_hanh_luc` DESC, `name` LIMIT {TRAN_DONG_HDDT}""",
			"%không rõ nghĩa%", as_dict=True):
		ra.append(_dong_hddt("2a", "Hoá đơn trong sổ mang ghi chú 'không rõ nghĩa' — đứng im ở trạng thái có thể đã cũ", r.name,
			f"{_ky_so(r.misa_inv_series, r.misa_inv_no)} · {r.misa_status or 'trống'} · quét lần cuối {r.misa_last_checked_at or 'chưa'}",
			"Xem nhóm 2 / 2c: khai nghĩa giá trị lạ rồi Làm mới", trang_thai_dang_ghi=r.misa_status, tong_tien=flt(r.tong_tien),
			lan_quet_cuoi=r.misa_last_checked_at, misa_note=r.misa_note))

	# 3a / 3b — tờ treo
	for r in frappe.db.sql(f"""SELECT `name`, `hoa_don_ban`, `misa_ref_id`, `misa_sent_at`, `misa_error` FROM `tabNPP HDDT`
			WHERE `misa_status` = 'pending' AND IFNULL(`misa_sent_at`, TIMESTAMP('1900-01-01')) < %s ORDER BY `misa_sent_at`, `name`
			LIMIT {TRAN_DONG_HDDT}""", add_to_date(luc, days=-NGAY_TREO), as_dict=True):
		ra.append(_dong_hddt("3a", "Đang chờ MISA quá 1 ngày (vòng quét đêm không gỡ được)", r.name,
			f"HĐ bán {r.hoa_don_ban or '—'} · RefID {r.misa_ref_id or '—'} · gửi lúc {r.misa_sent_at or '—'} · {r.misa_error or ''}".rstrip(" ·"),
			"Bấm 'Làm mới trạng thái' (MISA có ⇒ xác nhận đẩy; không có ⇒ Lỗi rồi Phát hành lại cùng RefID); vẫn kẹt thì xem nhật ký sync_run "
			"(lịch / cửa sổ 60 ngày / lỗi MISA)", hoa_don_ban=r.hoa_don_ban, misa_ref_id=r.misa_ref_id, misa_sent_at=r.misa_sent_at))
	for r in frappe.db.sql(f"""SELECT `name`, `hoa_don_ban`, `misa_ref_id`, `misa_sent_at`, `misa_error` FROM `tabNPP HDDT`
			WHERE `misa_status` = 'error' AND IFNULL(`misa_ref_id`, '') <> '' ORDER BY `misa_sent_at` IS NULL, `misa_sent_at`, `name`
			LIMIT {TRAN_DONG_HDDT}""", as_dict=True):
		ra.append(_dong_hddt("3b", "Đẩy MISA lỗi (đã có RefID) — chờ người xử lý", r.name,
			f"HĐ bán {r.hoa_don_ban or '—'} · {r.misa_error or 'không có câu lỗi'}",
			"Đọc lỗi, sửa nguyên nhân (cấu hình / người mua — sửa được khi còn nháp, H24) rồi bấm Phát hành: hỏi MISA trước, dùng lại RefID (H3)",
			hoa_don_ban=r.hoa_don_ban, misa_ref_id=r.misa_ref_id, misa_error=r.misa_error))

	# 4 — lịch đêm có chạy không
	luot = {}
	for nguon in ("sync_run", "pull_snapshots"):
		x = frappe.db.sql("""SELECT `name`, `goi_luc`, `ket_qua`, `loi` FROM `tabNPP MISA Log` WHERE `nguon` = %s ORDER BY `goi_luc` DESC,
			`creation` DESC LIMIT 1""", nguon, as_dict=True)
		luot[nguon] = x[0] if x else None
	tk["luot_moi_nhat"] = luot
	if da_luu() and cint(frappe.db.get_single_value("NPP MISA Cau Hinh", "dang_dung")):
		moi = luot["sync_run"]
		if moi is None or moi.goi_luc < add_to_date(luc, hours=-GIO_LUOT_DEM):
			ra.append(_dong_hddt("4", "Vòng quét đêm HĐĐT không chạy (dòng sync_run mới nhất cũ hơn 26 giờ)", moi.name if moi else None,
				f"sync_run mới nhất: {moi.goi_luc} ({moi.ket_qua})" if moi else "chưa có dòng sync_run nào",
				"Kiểm scheduler của site (bench enable-scheduler), worker nghe hàng long (Procfile: bench worker), Scheduled Job Type "
				"nppsale.lich.misa.dong_bo (cron 0 1 * * *); chạy tay: bench --site <site> execute nppsale.lich.misa.chay_dong_bo"))

	# 5a — trùng số đã chuẩn hoá
	theo_so: dict = {}
	for r in frappe.db.sql("""SELECT `name`, `misa_inv_series`, `misa_inv_no` FROM `tabNPP HDDT` WHERE IFNULL(`misa_inv_no`, '') <> ''
			ORDER BY `creation`, `name`""", as_dict=True):
		theo_so.setdefault(chuan_so(r.misa_inv_no), []).append(r)
	for nhom in theo_so.values():
		for i, a in enumerate(nhom):
			for b in nhom[i + 1:]:
				if trung_so(a.misa_inv_series, a.misa_inv_no, b.misa_inv_series, b.misa_inv_no):
					ra.append(_dong_hddt("5a", "Hai hoá đơn điện tử trùng số sau chuẩn hoá", a.name,
						f"{_ky_so(a.misa_inv_series, a.misa_inv_no)} ↔ {b.name}: {_ky_so(b.misa_inv_series, b.misa_inv_no)}",
						"Mở hai tờ trên MISA theo RefID (số của một RefID là bất biến) — tờ mang số sai thì tìm nguồn ghi (nhập tay / công cụ nhập)",
						hddt_khac=b.name))
	# 5b — hai dòng cùng HĐ bán
	from nppsale.cong.bang._chung import co_cot

	for cot in ("hoa_don_ban", "hoa_don_ban_ls"):
		if cot != "hoa_don_ban" and not co_cot("NPP HDDT", cot):
			continue
		for r in frappe.db.sql(f"""SELECT `{cot}` AS hd, COUNT(*) AS n, GROUP_CONCAT(CONCAT(`name`, ' (', `trang_thai`, '/', IFNULL(`misa_status`, ''),
				IF(IFNULL(`misa_inv_no`, '') <> '', CONCAT(' số ', `misa_inv_no`), ''), ')') ORDER BY `creation`, `name` SEPARATOR ', ') AS ds
				FROM `tabNPP HDDT` WHERE IFNULL(`{cot}`, '') <> '' GROUP BY `{cot}` HAVING COUNT(*) > 1 ORDER BY `{cot}`""", as_dict=True):
			ra.append(_dong_hddt("5b", "Một HĐ bán có nhiều dòng hoá đơn điện tử", r.hd, f"{r.n} dòng: {r.ds}",
				"Giữ tờ có số / mới nhất (thứ tự màn HĐ bán), ghi chú các tờ còn lại — nppsale đẻ được hai dòng khi bấm song song (§9.5)"))
	# 5c — dòng lẽ ra khoá Huỷ HĐ (đủ vế LOCKED_EINVOICE — nppsale.rpc.xuat_hang._khoa_hddt) mà HĐ bán đã huỷ
	for r in frappe.db.sql("""SELECT h.`name`, h.`hoa_don_ban`, h.`trang_thai`, h.`misa_status`, h.`misa_inv_no` FROM `tabNPP HDDT` h
			JOIN `tabSales Invoice` si ON si.`name` = h.`hoa_don_ban`
			WHERE si.`docstatus` = 2 AND (h.`trang_thai` = 'issued' OR IFNULL(h.`misa_inv_no`, '') <> '' OR h.`misa_status` IN ('signed', 'replaced')
				OR (IFNULL(h.`misa_ref_id`, '') <> '' AND h.`misa_status` IN ('pending', 'sent', 'waiting_code', 'amount_mismatch')))
			ORDER BY h.`hoa_don_ban`, h.`name`""", as_dict=True):
		ra.append(_dong_hddt("5c", "Hoá đơn điện tử còn hiệu lực / đang chờ MISA cho HĐ bán ĐÃ HUỶ", r.name,
			f"HĐ bán {r.hoa_don_ban} (đã huỷ) · {r.trang_thai}/{r.misa_status or 'trống'}{' · số ' + r.misa_inv_no if r.misa_inv_no else ''}",
			"Kế toán xử lý trên MISA (huỷ / thay thế / điều chỉnh theo quy định thuế) rồi Làm mới; tìm vì sao Huỷ HĐ lọt khoá LOCKED_EINVOICE",
			hoa_don_ban=r.hoa_don_ban))
	# 5d — issued thiếu cả hai mốc ⇒ không bao giờ vào cửa sổ vòng quét
	for r in frappe.db.sql(f"""SELECT `name`, `misa_ref_id`, `misa_status`, `misa_inv_no` FROM `tabNPP HDDT` WHERE `trang_thai` = 'issued'
			AND `phat_hanh_luc` IS NULL AND `misa_sent_at` IS NULL ORDER BY `name` LIMIT {TRAN_DONG_HDDT}""", as_dict=True):
		ra.append(_dong_hddt("5d", "Đã phát hành nội bộ mà thiếu cả ngày phát hành lẫn lần gửi MISA — vòng quét không bao giờ hỏi (H14)", r.name,
			f"RefID {r.misa_ref_id or '—'} · {r.misa_status or 'trống'}{' · số ' + r.misa_inv_no if r.misa_inv_no else ''}",
			"Có RefID: bấm Làm mới tay khi cần; không bịa ngày phát hành (Gotcha #11.5)"))
	thu_tu = {n: i for i, n in enumerate(NHOM_HDDT)}
	ra.sort(key=lambda x: thu_tu[x["nhom"]])
	return {"can_xem": ra, "thong_ke": tk}
