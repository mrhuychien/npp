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
"""
from __future__ import annotations

import frappe
from frappe.utils import flt

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
