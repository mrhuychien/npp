"""Giữ chứng từ tiền khớp sổ khi chứng từ nó trỏ tới bị huỷ / lập lại (đặc tả phiếu thu §2.5.2, §3.2; nppsale mig 184 / 191 / 212).

Lõi ERPNext, khi huỷ một Sales Invoice (`unlink_payment_on_cancellation_of_invoice = 1`), LẶNG LẼ gỡ tham chiếu của mọi bút toán / Payment Entry
trỏ nó (`accounts/utils.py: remove_ref_doc_link_from_jv / _pe`) — không báo lỗi, bút toán treo, số dư khách vẫn đúng nhưng mỗi dòng công nợ sai. Vì
vậy trước khi huỷ một tờ (HĐ cũ khi Sửa HĐ, tờ ghi có của phiếu trả khi sửa / huỷ phiếu) app huỷ trước các bút toán cấn trừ dư có `CTR-` đang trỏ
tờ ấy, làm thao tác chính, rồi LẬP LẠI từng bút toán (amend `CTR-…-n`) GIỮ NGUYÊN số tiền từng vế, chỉ thay tham chiếu sang chứng từ còn hiệu lực
cùng "dòng nppsale" (Q3 tạm quyết — nppsale không bao giờ đổi payments khi nguồn dư có đổi; nợ "tự tăng lại" nằm trên CHÍNH dòng nguồn):
- HĐ cũ → HĐ mới (Sửa HĐ);
- tờ ghi có cũ của một phiếu trả → tờ ghi có đang hiệu lực của CÙNG phiếu; không còn → HĐ phiếu gắn (cùng nhóm công nợ); phiếu độc lập đã huỷ
  → giữ tờ đã huỷ làm tham chiếu (Payment Ledger vẫn cộng vào nhóm của phiếu → dòng phiếu trả còn nợ đúng số đã rút, như `_cong_no_phieu_tra`).
Payment Entry của phiếu thu thì KHÔNG huỷ: lõi tự gỡ phân bổ khỏi HĐ cũ, app phân bổ lại sang HĐ mới (`reconcile_against_document`, giữ số phiếu
thu = tên PE); phần không vừa tờ mới (thu vượt sau Sửa HĐ giảm — mig 184) được chuyển vào CHÍNH HĐ mới bằng bút toán `chuyen_tien_thua` (Nợ PE /
Có HĐ): HĐ còn nợ âm = dư có ngay trên dòng HĐ, đúng từng dòng như nppsale (phương án B của Q1 — 00_quyet_dinh_trien_khai.md Q7).
"""
from __future__ import annotations

import frappe
from frappe.utils import flt

from nppsale.cong.loi import NppLoi
from nppsale.su_kien import cong_no as CN

PT = "NPP Phieu Thu"


# ------------------------------------------------------------------------------------------------ bút toán cấn trừ
def je_tham_chieu(ds_ct, loai: str = "can_tru_khach") -> list[str]:
	"""Bút toán của app (`npp_loai` = loai) đang ghi sổ có vế trỏ một trong các Sales Invoice `ds_ct` (theo ngày lập)."""
	ds = [x for x in dict.fromkeys(ds_ct) if x]
	if not ds or not frappe.get_meta("Journal Entry").has_field("npp_loai"):
		return []
	return [r[0] for r in frappe.db.sql("""SELECT DISTINCT j.`name` FROM `tabJournal Entry` j JOIN `tabJournal Entry Account` a ON a.`parent` = j.`name`
		WHERE j.`docstatus` = 1 AND j.`npp_loai` = %(l)s AND a.`reference_type` = 'Sales Invoice' AND a.`reference_name` IN %(d)s
		ORDER BY j.`creation`, j.`name`""", {"d": tuple(ds), "l": loai})]


def lap_chuyen_tien_thua(pe: str, hd: str, so, ngay=None) -> str:
	"""Bút toán `chuyen_tien_thua` (Credit Note — lõi không kiểm số còn nợ của HĐ được ghi Có): Nợ phần chưa phân bổ của PE / Có HĐ → HĐ còn nợ âm
	(dư có trên dòng HĐ — mig 184 "paid += paid cũ toàn bộ"). Số phiếu thu sở hữu = `npp_phieu_thu` của PE."""
	x = frappe.db.get_value("Payment Entry", pe, ["company", "party", "paid_from", "posting_date", "npp_phieu_thu"], as_dict=True)
	si = frappe.db.get_value("Sales Invoice", hd, ["debit_to", "posting_date"], as_dict=True)
	je = frappe.new_doc("Journal Entry")
	je.update({"voucher_type": "Credit Note", "naming_series": "CTR-.####", "company": x.company,
		"posting_date": ngay or max(x.posting_date, si.posting_date), "npp_loai": "chuyen_tien_thua", "npp_phieu_thu": x.npp_phieu_thu,
		"user_remark": f"Chuyển tiền thu vượt — {x.npp_phieu_thu or pe} → {hd}", "is_system_generated": 0})
	je.append("accounts", {"account": x.paid_from, "party_type": "Customer", "party": x.party, "debit_in_account_currency": flt(so),
		"reference_type": "Payment Entry", "reference_name": pe})
	je.append("accounts", {"account": si.debit_to, "party_type": "Customer", "party": x.party, "credit_in_account_currency": flt(so),
		"reference_type": "Sales Invoice", "reference_name": hd})
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	frappe.local.message_log = []
	return je.name


def huy_je(ten_ds) -> list:
	"""Huỷ các bút toán (trước khi huỷ chứng từ chúng trỏ) — trả bản đã huỷ để lập lại."""
	ra = []
	for ten in ten_ds:
		je = frappe.get_doc("Journal Entry", ten)
		if je.docstatus != 1:
			continue
		je.flags.ignore_permissions = True
		je.cancel()
		ra.append(je)
	frappe.local.message_log = []
	return ra


def lap_lai_je(je, doi: dict) -> str:
	"""Amend bút toán đã huỷ với tham chiếu đổi theo `doi` {tờ cũ: tờ mới}; giữ số từng vế. Cập nhật phiếu thu sở hữu (but_toan_can_tru) và
	chứng từ trên dòng phiếu thu của nó. Trả tên bút toán mới."""
	moi = frappe.copy_doc(je)
	moi.amended_from = je.name
	moi.docstatus = 0
	for a in moi.accounts:
		if a.reference_type == "Sales Invoice" and a.reference_name in doi:
			a.reference_name = doi[a.reference_name]
			a.account = frappe.db.get_value("Sales Invoice", a.reference_name, "debit_to") or a.account
	moi.flags.ignore_permissions = True
	# phiếu trả độc lập đã huỷ: vế Nợ giữ tờ ghi có ĐÃ HUỶ của phiếu (nhóm công nợ của phiếu không còn tờ hiệu lực — Q3); Frappe chặn
	# Link tới chứng từ đã huỷ ở bước kiểm liên kết, lõi Credit Note thì không kiểm docstatus tờ tham chiếu (journal_entry.py validate_invoices)
	if any(a.reference_type == "Sales Invoice" and frappe.db.get_value("Sales Invoice", a.reference_name, "docstatus") == 2
			for a in moi.accounts if a.reference_name):
		moi.flags.ignore_links = True
	moi.insert()
	moi.submit()
	frappe.local.message_log = []
	ph = je.get("npp_phieu_thu")
	if ph and frappe.db.exists(PT, ph):
		if frappe.db.get_value(PT, ph, "but_toan_can_tru") == je.name:
			frappe.db.set_value(PT, ph, "but_toan_can_tru", moi.name, update_modified=False)
		for d in frappe.get_all("NPP Phieu Thu Dong", filters={"parent": ph, "parenttype": PT, "chung_tu_loai": "Sales Invoice",
				"chung_tu": ("in", list(doi))}, fields=["name", "chung_tu"]):
			frappe.db.set_value("NPP Phieu Thu Dong", d.name, "chung_tu", doi[d.chung_tu], update_modified=False)
	return moi.name


# ------------------------------------------------------------------------------------------------ phiếu trả (P3c) — tờ ghi có bị huỷ / lập lại
def _cho() -> list:
	if getattr(frappe.local, "_npp_je_cho", None) is None:
		frappe.local._npp_je_cho = []
	return frappe.local._npp_je_cho


def truoc_huy_to_ghi_co(to: str) -> None:
	"""Gọi NGAY TRƯỚC khi huỷ một tờ ghi có: huỷ các bút toán cấn trừ trỏ nó, ghi vào hàng chờ lập lại (sau_thao_tac_phieu_tra)."""
	for je in huy_je(je_tham_chieu([to])):
		_cho().append(je)


def sau_thao_tac_phieu_tra() -> list[str]:
	"""Cuối mỗi thao tác phiếu trả: lập lại các bút toán trong hàng chờ — tờ ghi có cũ → tờ đang hiệu lực của cùng phiếu; không còn → HĐ phiếu
	gắn; phiếu độc lập không còn tờ hiệu lực → giữ tờ đã huỷ (Payment Ledger vẫn cộng vào nhóm của phiếu)."""
	cho, frappe.local._npp_je_cho = _cho(), []
	ra = []
	cham = set()
	for je in cho:
		doi = {}
		for a in je.accounts:
			if a.reference_type != "Sales Invoice" or not a.reference_name or a.reference_name in doi:
				continue
			t = frappe.db.get_value("Sales Invoice", a.reference_name, ["docstatus", "is_return", "npp_phieu_tra", "npp_hoa_don_goc"], as_dict=True)
			if not t or t.docstatus == 1 or not t.is_return:
				continue
			moi = None
			if t.npp_phieu_tra:
				moi = frappe.db.get_value("Sales Invoice", {"npp_phieu_tra": t.npp_phieu_tra, "is_return": 1, "docstatus": 1}, "name",
					order_by="creation desc")
			if not moi:
				hd = t.npp_hoa_don_goc or (frappe.db.get_value("NPP Phieu Tra", t.npp_phieu_tra, "hoa_don") if t.npp_phieu_tra else None)
				moi = hd if hd and frappe.db.get_value("Sales Invoice", hd, "docstatus") == 1 else None
			if moi:
				doi[a.reference_name] = moi
			if t.npp_phieu_tra:
				cham.add(t.npp_phieu_tra)
		ra.append(lap_lai_je(je, doi))
	for pt in cham:
		CN.chieu_phieu_tra(pt)
	return ra


def kiem_doi_khach_phieu_tra(pt: str, khach_moi: str | None) -> None:
	"""`_cong_no_phieu_tra` (mig 191): dòng dư có của phiếu trả độc lập đã bị rút (đã thu ≠ 0) thì không đổi khách được."""
	r = frappe.db.get_value(CN.DT, {"khoa_nguon": f"NPP Phieu Tra:{pt}"}, ["khach_hang", "da_thu"], as_dict=True)
	if r and khach_moi and r.khach_hang != khach_moi and abs(flt(r.da_thu)) >= 0.005:
		raise NppLoi("RETURN_CREDIT_USED: dư có của phiếu trả đã dùng ở phiếu thu của khách cũ — không đổi khách được")


# ------------------------------------------------------------------------------------------------ Sửa HĐ (mig 184)
def nho_tien_thu(hd: str) -> frappe._dict:
	"""R0 — ghi nhớ tiền thu của tờ cũ TRƯỚC mọi bước phiếu trả / huỷ tờ (các bước ấy huỷ tờ ghi có / tờ cũ → lõi gỡ tham chiếu lặng lẽ):
	PE phân bổ vào tờ (+ phần thu vượt đã chuyển vào tờ — bút toán `chuyen_tien_thua`), bút toán cấn trừ trỏ tờ / tờ ghi có gắn tờ (huỷ
	ngay), dòng phiếu thu trỏ dòng công nợ / trỏ tờ."""
	dong = frappe.db.get_value(CN.DT, {"khoa_nguon": f"Sales Invoice:{hd}"}, ["name", "da_thu"], as_dict=True)
	cn = CN.ghi_co_gan(hd)
	pe_cu: dict[str, float] = {}
	for ten, so in frappe.db.sql("""SELECT r.`parent`, SUM(r.`allocated_amount`) FROM `tabPayment Entry Reference` r
			JOIN `tabPayment Entry` pe ON pe.`name` = r.`parent` WHERE pe.`docstatus` = 1 AND r.`reference_doctype` = 'Sales Invoice'
			AND r.`reference_name` = %s GROUP BY r.`parent`""", hd):
		pe_cu[ten] = flt(so)
	# tiền thu vượt đã chuyển vào tờ cũ (lần Sửa trước): gộp lại vào phần của PE rồi huỷ bút toán — lập lại theo tờ mới ở chuyen_tien_thu
	for ten in je_tham_chieu([hd], "chuyen_tien_thua"):
		for a in frappe.get_all("Journal Entry Account", filters={"parent": ten, "reference_type": "Payment Entry"},
				fields=["reference_name", "debit_in_account_currency"]):
			pe_cu[a.reference_name] = pe_cu.get(a.reference_name, 0.0) + flt(a.debit_in_account_currency)
	huy_je(je_tham_chieu([hd], "chuyen_tien_thua"))
	je = huy_je(je_tham_chieu([hd, *cn]))
	dong_cu = frappe.db.sql("""SELECT d.`name`, d.`parent`, d.`cong_no`, d.`hoa_don`, d.`chung_tu_loai`, d.`chung_tu`, p.`trang_thai`
		FROM `tabNPP Phieu Thu Dong` d JOIN `tabNPP Phieu Thu` p ON p.`name` = d.`parent` WHERE d.`parenttype` = 'NPP Phieu Thu'
		AND (d.`cong_no` = %(dong)s OR d.`hoa_don` = %(hd)s)""", {"dong": dong.name if dong else "", "hd": hd}, as_dict=True) \
		if frappe.db.exists("DocType", PT) else []
	return frappe._dict(dong=dong, cn=cn, pe_cu=pe_cu, je=je, dong_cu=dong_cu)


def chuyen_tien_thu(nho: frappe._dict, hd_cu: str, hd_moi: str) -> None:
	"""Sau khi tờ mới ghi sổ (+ tờ ghi có mới của phiếu trả): phân bổ lại PE sang tờ mới (PE trước); phần của tờ cũ không vừa tờ mới chuyển vào
	chính tờ mới (`chuyen_tien_thua` — dư có trên dòng HĐ như nppsale); lập lại bút toán cấn trừ (tờ cũ → tờ mới, tờ ghi có cũ → tờ ghi có mới của
	cùng phiếu trả, không còn → tờ mới); trỏ lại dòng phiếu thu; tờ mới bỏ dấu quá hạn."""
	from erpnext.accounts.utils import reconcile_against_document

	si = frappe.db.get_value("Sales Invoice", hd_moi, ["name", "customer", "debit_to", "grand_total", "npp_nv_giu_no", "npp_giao_tu_nv",
		"npp_ve_npp_luc"], as_dict=True)
	dong_moi = frappe.db.get_value(CN.DT, {"khoa_nguon": f"Sales Invoice:{hd_moi}"}, "name")
	if not dong_moi and nho.dong and flt(nho.dong.da_thu) > 0:
		raise NppLoi(f"REISSUE_NO_RECEIVABLE: tờ mới không có công nợ để gắn {flt(nho.dong.da_thu):g} đã thu")
	# 1) PE: theo thứ tự lập — phần = min(đã phân bổ tờ cũ + tiền thừa tờ cũ, còn nợ của tờ mới, phần chưa phân bổ thật theo sổ)
	for pe in sorted(nho.pe_cu, key=lambda x: (frappe.db.get_value("Payment Entry", x, "creation"), x)):
		cu = flt(nho.pe_cu[pe])
		con_hd = CN._con_no([hd_moi])
		that = -CN._con_no([pe], "Payment Entry")
		phan = min(cu, con_hd, that)
		if phan > 0.005:
			chua = flt(frappe.db.get_value("Payment Entry", pe, "unallocated_amount"))
			reconcile_against_document([frappe._dict({
				"voucher_type": "Payment Entry", "voucher_no": pe, "voucher_detail_no": None, "against_voucher_type": "Sales Invoice",
				"against_voucher": hd_moi, "account": si.debit_to, "party_type": "Customer", "party": si.customer,
				"dr_or_cr": "credit_in_account_currency", "unreconciled_amount": chua, "unadjusted_amount": chua, "allocated_amount": phan,
				"grand_total": si.grand_total, "outstanding_amount": flt(frappe.db.get_value("Sales Invoice", hd_moi, "outstanding_amount")),
				"exchange_rate": 1, "difference_amount": 0, "difference_posting_date": None, "precision": 0})])
			frappe.local.message_log = []
		du = min(cu - max(phan, 0.0), -CN._con_no([pe], "Payment Entry"))  # phần của tờ cũ không vừa tờ mới (≤ chưa phân bổ thật)
		if du > 0.005:
			lap_chuyen_tien_thua(pe, hd_moi, du)
		ph = frappe.db.get_value("Payment Entry", pe, "npp_phieu_thu")
		if ph and frappe.db.exists(PT, ph):
			CN.chieu_tien_thua(ph)
	# 2) bút toán cấn trừ: tờ cũ → tờ mới; tờ ghi có cũ → tờ ghi có mới của cùng phiếu trả, không còn → tờ mới
	doi = {hd_cu: hd_moi}
	for to in nho.cn:
		pt = frappe.db.get_value("Sales Invoice", to, "npp_phieu_tra")
		moi = frappe.db.get_value("Sales Invoice", {"npp_phieu_tra": pt, "is_return": 1, "docstatus": 1}, "name", order_by="creation desc") \
			if pt else None
		doi[to] = moi or hd_moi
	for je in nho.je:
		lap_lai_je(je, doi)
	# 3) dòng phiếu thu: phiếu chưa huỷ → dòng công nợ tờ mới + HĐ mới + chứng từ mới; phiếu đã huỷ → chỉ HĐ mới
	cu_dong = nho.dong.name if nho.dong else None
	for d in nho.dong_cu:
		moi = {}
		if d.hoa_don == hd_cu:
			moi["hoa_don"] = hd_moi
		if d.trang_thai != "voided":
			if cu_dong and d.cong_no == cu_dong and dong_moi:
				moi["cong_no"] = dong_moi
			if d.chung_tu_loai == "Sales Invoice" and d.chung_tu in doi:
				moi["chung_tu"] = doi[d.chung_tu]
		if moi:
			frappe.db.set_value("NPP Phieu Thu Dong", d.name, moi, update_modified=False)
	if frappe.db.get_value("Sales Invoice", hd_moi, "npp_qua_han_tay"):
		frappe.db.set_value("Sales Invoice", hd_moi, "npp_qua_han_tay", 0, update_modified=False)
	CN.chieu_hoa_don(hd_moi)
	for ph in {frappe.db.get_value("Payment Entry", pe, "npp_phieu_thu") for pe in nho.pe_cu} - {None}:
		CN.chieu_tien_thua(ph)
