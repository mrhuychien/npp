"""Sổ sách bán hàng của một NPP (blueprint 02 §3.5–3.6, bản bàn bạc 3.11, PoC 2): kho bán + kho cận date, tài khoản VAT đầu ra /
đầu vào, Item Tax Template "VAT n%" (mỗi mẫu mang CẢ hai tài khoản — thiếu đầu vào thì phiếu nhập NCC tính VAT = 0 mà không báo gì,
PoC 05/11), mẫu thuế "VAT theo mat hang" (một dòng On Net Total 0% — thuế thật theo mẫu của từng dòng), điều khoản thanh toán
COD / NETn (tên mẫu = mã nppsale), và trỏ NPP Cai Dat vào chúng.

Chỉ chạy khi site đã có công ty (qua bước cài đặt ERPNext). Chạy lại nhiều lần vẫn an toàn.
"""
from __future__ import annotations

import frappe

THUE_SUAT = (0, 5, 8, 10)
DIEU_KHOAN = (("COD", 0), ("NET7", 7), ("NET15", 15), ("NET30", 30), ("NET45", 45), ("NET60", 60))


def _cong_ty() -> str | None:
	ten = None
	if frappe.db.exists("DocType", "NPP Cai Dat"):
		ten = frappe.db.get_single_value("NPP Cai Dat", "cong_ty")
	ten = ten or frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	return ten if ten and frappe.db.exists("Company", ten) else None


def _kho(cong_ty: str, abbr: str, ten: str) -> str:
	ma = f"{ten} - {abbr}"
	if not frappe.db.exists("Warehouse", ma):
		goc = frappe.db.get_value("Warehouse", {"company": cong_ty, "is_group": 1, "parent_warehouse": ("in", ("", None))})
		frappe.get_doc({"doctype": "Warehouse", "warehouse_name": ten, "company": cong_ty, "parent_warehouse": goc}).insert(
			ignore_permissions=True)
	return ma


def _tai_khoan_thue(cong_ty: str, abbr: str, ten: str) -> str:
	ma = f"{ten} - {abbr}"
	if frappe.db.exists("Account", ma):
		return ma
	nhom = frappe.db.get_value("Account", {"company": cong_ty, "account_name": "Duties and Taxes", "is_group": 1}) or frappe.db.get_value(
		"Account", {"company": cong_ty, "root_type": "Liability", "is_group": 1}, order_by="lft desc")
	return frappe.get_doc({"doctype": "Account", "account_name": ten, "parent_account": nhom, "company": cong_ty, "account_type": "Tax",
		"is_group": 0}).insert(ignore_permissions=True).name


def ten_mau_thue_dong(ty_le: float, abbr: str) -> str:
	"""Tỉ lệ 0..1 → tên Item Tax Template: 0.08 → "VAT 8% - <abbr>", 0.035 → "VAT 3.5% - <abbr>"."""
	pt = round(float(ty_le or 0) * 100, 4)
	nhan = f"{pt:g}"
	return f"VAT {nhan}% - {abbr}"


def mau_thue_dong(ty_le: float, cong_ty: str | None = None) -> str:
	"""Item Tax Template cho một thuế suất (tạo khi chưa có — nppsale cho mọi tỉ lệ 0..1)."""
	cong_ty = cong_ty or _cong_ty()
	abbr = frappe.get_cached_value("Company", cong_ty, "abbr")
	ten = ten_mau_thue_dong(ty_le, abbr)
	if frappe.db.exists("Item Tax Template", ten):
		return ten
	ra = _tai_khoan_thue(cong_ty, abbr, "Thue GTGT dau ra")
	vao = _tai_khoan_thue(cong_ty, abbr, "Thue GTGT dau vao")
	pt = round(float(ty_le or 0) * 100, 4)
	return frappe.get_doc({"doctype": "Item Tax Template", "title": f"VAT {pt:g}%", "company": cong_ty,
		"taxes": [{"tax_type": ra, "tax_rate": pt}, {"tax_type": vao, "tax_rate": pt}]}).insert(ignore_permissions=True).name


def _mau_thue(cong_ty: str, abbr: str) -> tuple[str, str]:
	ra = _tai_khoan_thue(cong_ty, abbr, "Thue GTGT dau ra")
	vao = _tai_khoan_thue(cong_ty, abbr, "Thue GTGT dau vao")
	for r in THUE_SUAT:
		ten = mau_thue_dong(r / 100, cong_ty)
		t = frappe.get_doc("Item Tax Template", ten)
		if not any(x.tax_type == vao for x in t.taxes):
			t.append("taxes", {"tax_type": vao, "tax_rate": r})
			t.save(ignore_permissions=True)
	ban = f"VAT theo mat hang - {abbr}"
	if not frappe.db.exists("Sales Taxes and Charges Template", ban):
		frappe.get_doc({"doctype": "Sales Taxes and Charges Template", "title": "VAT theo mat hang", "company": cong_ty, "is_default": 1,
			"taxes": [{"charge_type": "On Net Total", "account_head": ra, "description": "VAT", "rate": 0}]}).insert(ignore_permissions=True)
	mua = f"VAT mua theo mat hang - {abbr}"
	if not frappe.db.exists("Purchase Taxes and Charges Template", mua):
		frappe.get_doc({"doctype": "Purchase Taxes and Charges Template", "title": "VAT mua theo mat hang", "company": cong_ty,
			"is_default": 1, "taxes": [{"charge_type": "On Net Total", "account_head": vao, "description": "VAT", "rate": 0,
				"category": "Total", "add_deduct_tax": "Add"}]}).insert(ignore_permissions=True)
	return ban, mua


def _dieu_khoan():
	for ma, ngay in DIEU_KHOAN:
		if not frappe.db.exists("Payment Term", ma):
			frappe.get_doc({"doctype": "Payment Term", "payment_term_name": ma, "invoice_portion": 100,
				"due_date_based_on": "Day(s) after invoice date", "credit_days": ngay}).insert(ignore_permissions=True)
		if not frappe.db.exists("Payment Terms Template", ma):
			frappe.get_doc({"doctype": "Payment Terms Template", "template_name": ma, "terms": [{"payment_term": ma, "invoice_portion": 100,
				"due_date_based_on": "Day(s) after invoice date", "credit_days": ngay}]}).insert(ignore_permissions=True)


def _tk_giam_gia_don(cong_ty: str, abbr: str) -> str:
	"""Tài khoản của giảm giá cả đơn (additional_discount_account của HĐ — giảm sau thuế, không hạ nền thuế, mig 183)."""
	ma = f"Chiet khau thuong mai - {abbr}"
	if frappe.db.exists("Account", ma):
		return ma
	nhom = frappe.db.get_value("Account", {"company": cong_ty, "account_name": "Indirect Expenses", "is_group": 1}) or frappe.db.get_value(
		"Account", {"company": cong_ty, "root_type": "Expense", "is_group": 1}, order_by="lft")
	return frappe.get_doc({"doctype": "Account", "account_name": "Chiet khau thuong mai", "parent_account": nhom, "company": cong_ty,
		"account_type": "", "is_group": 0}).insert(ignore_permissions=True).name


def dam_bao():
	cong_ty = _cong_ty()
	if not cong_ty:
		return
	abbr = frappe.get_cached_value("Company", cong_ty, "abbr")
	kho_ban = _kho(cong_ty, abbr, "Kho ban")
	kho_date = _kho(cong_ty, abbr, "Kho can date")
	ban, mua = _mau_thue(cong_ty, abbr)
	_dieu_khoan()
	# Mẫu thuế dòng mang cả TK đầu vào → lõi KHÔNG được tự thêm dòng thuế từ mẫu dòng (thêm là chứng từ bán có thêm dòng
	# "Thue GTGT dau vao" — VAT nhân đôi). Blueprint 02 §3.5.
	if frappe.db.get_single_value("Accounts Settings", "add_taxes_from_item_tax_template"):
		frappe.db.set_single_value("Accounts Settings", "add_taxes_from_item_tax_template", 0)
	if not frappe.db.exists("DocType", "NPP Cai Dat"):
		return
	cd = frappe.get_single("NPP Cai Dat")
	doi = False
	tk_giam = _tk_giam_gia_don(cong_ty, abbr)
	for k, v in (("kho_ban", kho_ban), ("kho_can_date", kho_date), ("mau_thue_ban", ban), ("mau_thue_mua", mua), ("tk_giam_gia_don", tk_giam)):
		if cd.meta.has_field(k) and not cd.get(k):
			cd.set(k, v)
			doi = True
	if doi:
		cd.flags.ignore_mandatory = True
		cd.save(ignore_permissions=True)


def cai_dat_ban() -> frappe._dict:
	"""Bộ cài đặt method bán hàng cần — đọc một lần mỗi request."""
	cd = getattr(frappe.local, "_npp_cai_dat_ban", None)
	if cd is None:
		cong_ty = _cong_ty()
		abbr = frappe.get_cached_value("Company", cong_ty, "abbr") if cong_ty else None
		g = frappe.db.get_singles_dict("NPP Cai Dat") if frappe.db.exists("DocType", "NPP Cai Dat") else {}
		cd = frappe._dict(
			cong_ty=cong_ty, abbr=abbr,
			kho_ban=g.get("kho_ban") or (f"Kho ban - {abbr}" if abbr else None),
			kho_can_date=g.get("kho_can_date") or (f"Kho can date - {abbr}" if abbr else None),
			mau_thue_ban=g.get("mau_thue_ban") or (f"VAT theo mat hang - {abbr}" if abbr else None),
			mau_thue_mua=g.get("mau_thue_mua") or (f"VAT mua theo mat hang - {abbr}" if abbr else None),
			tk_giam_gia_don=g.get("tk_giam_gia_don") or (f"Chiet khau thuong mai - {abbr}" if abbr else None),
		)
		frappe.local._npp_cai_dat_ban = cd
	return cd
