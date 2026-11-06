"""PoC P0 — dựng site thử theo mục 3.11 của bản bàn bạc và dữ liệu mẫu để đo.

Chạy:  bench --site poc.local execute nppsale.poc.setup.run
Idempotent: chạy lại không tạo trùng.
"""
import frappe
from frappe.utils import nowdate, add_days, getdate

CTY = "NPP Thu"
ABBR = "NPP"
KHO_BAN = f"Kho ban - {ABBR}"
KHO_DATE = f"Kho can date - {ABBR}"


def run(currency_precision="0"):
	_thiet_lap_cong_ty()
	_cai_dat_he_thong(currency_precision)
	_tai_khoan_lam_tron()
	_kho()
	_don_vi()
	_thue()
	_dieu_khoan_tt()
	_hinh_thuc_tt()
	_bang_gia()
	_hang_hoa()
	_khach_ncc()
	frappe.db.commit()
	print("SETUP XONG")


def _thiet_lap_cong_ty():
	if frappe.db.exists("Company", CTY):
		return
	from erpnext.setup.setup_wizard.setup_wizard import setup_complete
	nam = getdate(nowdate()).year
	setup_complete(frappe._dict({
		"company_name": CTY, "company_abbr": ABBR, "currency": "VND", "country": "Vietnam",
		"chart_of_accounts": "Standard", "domain": "Distribution",
		"fy_start_date": f"{nam}-01-01", "fy_end_date": f"{nam}-12-31",
		"bank_account": "Ngan hang", "full_name": "Administrator", "email": "admin@example.com",
		"language": "english", "timezone": "Asia/Ho_Chi_Minh",
	}))
	# năm tài chính trước cho dữ liệu lùi ngày / đầu kỳ
	for y in (nam - 1,):
		if not frappe.db.exists("Fiscal Year", str(y)):
			frappe.get_doc({"doctype": "Fiscal Year", "year": str(y), "year_start_date": f"{y}-01-01", "year_end_date": f"{y}-12-31"}).insert()
	frappe.db.set_single_value("System Settings", "setup_complete", 1)


def _cai_dat_he_thong(currency_precision):
	ss = frappe.get_doc("System Settings")
	ss.time_zone = "Asia/Ho_Chi_Minh"
	ss.rounding_method = "Commercial Rounding"
	ss.currency_precision = currency_precision
	ss.number_format = "#.###"
	ss.float_precision = "3"
	ss.allow_login_using_mobile_number = 1
	ss.session_expiry = "720:00"
	ss.flags.ignore_mandatory = True
	ss.save()
	frappe.db.set_value("Currency", "VND", {"enabled": 1, "smallest_currency_fraction_value": 0, "number_format": "#.###"})

	st = frappe.get_doc("Stock Settings")
	st.enable_serial_and_batch_no_for_item = 1
	st.use_serial_batch_fields = 1
	st.pick_serial_and_batch_based_on = "FIFO"
	st.auto_create_serial_and_batch_bundle_for_outward = 1
	st.allow_negative_stock = 0
	st.valuation_method = "FIFO"
	st.stock_uom = "Lon" if frappe.db.exists("UOM", "Lon") else st.stock_uom
	st.role_allowed_to_over_deliver_receive = "System Manager"
	st.over_delivery_receipt_allowance = 100
	st.save()

	sel = frappe.get_doc("Selling Settings")
	sel.allow_multiple_items = 1
	sel.maintain_same_sales_rate = 0
	sel.save()
	buy = frappe.get_doc("Buying Settings")
	buy.allow_multiple_items = 1
	buy.save()

	acc = frappe.get_doc("Accounts Settings")
	acc.unlink_payment_on_cancellation_of_invoice = 1
	acc.over_billing_allowance = 100
	acc.role_allowed_to_over_bill = "System Manager"
	acc.add_taxes_from_item_tax_template = 1
	acc.enable_immutable_ledger = 0
	acc.save()


def _tai_khoan_lam_tron():
	cty = frappe.get_doc("Company", CTY)
	tk = frappe.db.get_value("Account", {"company": CTY, "account_name": "Round Off", "is_group": 0}) or \
		frappe.db.get_value("Account", {"company": CTY, "account_name": "Miscellaneous Expenses", "is_group": 0})
	cc = frappe.db.get_value("Cost Center", {"company": CTY, "is_group": 0})
	cty.round_off_account = tk
	cty.round_off_cost_center = cc
	cty.save()


def _kho():
	parent = frappe.db.get_value("Warehouse", {"company": CTY, "is_group": 1, "parent_warehouse": ""})
	for ten in ("Kho ban", "Kho can date"):
		if not frappe.db.exists("Warehouse", f"{ten} - {ABBR}"):
			frappe.get_doc({"doctype": "Warehouse", "warehouse_name": ten, "company": CTY, "parent_warehouse": parent}).insert()


def _don_vi():
	for u in ("Lon", "Chai", "Hop", "Loc", "Thung"):
		if not frappe.db.exists("UOM", u):
			frappe.get_doc({"doctype": "UOM", "uom_name": u, "must_be_whole_number": 0}).insert()


def _tai_khoan_vat():
	ten = f"Thue GTGT dau ra - {ABBR}"
	if not frappe.db.exists("Account", ten):
		nhom = frappe.db.get_value("Account", {"company": CTY, "account_name": "Duties and Taxes", "is_group": 1})
		frappe.get_doc({"doctype": "Account", "account_name": "Thue GTGT dau ra", "parent_account": nhom, "company": CTY, "account_type": "Tax", "is_group": 0}).insert()
	return ten


def _thue():
	tk = _tai_khoan_vat()
	for r in (0, 5, 8, 10):
		ten = f"VAT {r}% - {ABBR}"
		if not frappe.db.exists("Item Tax Template", ten):
			frappe.get_doc({"doctype": "Item Tax Template", "title": f"VAT {r}%", "company": CTY,
				"taxes": [{"tax_type": tk, "tax_rate": r}]}).insert()
	ten = f"VAT theo mat hang - {ABBR}"
	if not frappe.db.exists("Sales Taxes and Charges Template", ten):
		frappe.get_doc({"doctype": "Sales Taxes and Charges Template", "title": "VAT theo mat hang", "company": CTY, "is_default": 1,
			"taxes": [{"charge_type": "On Net Total", "account_head": tk, "description": "VAT", "rate": 0}]}).insert()
	ten = f"VAT mua theo mat hang - {ABBR}"
	if not frappe.db.exists("Purchase Taxes and Charges Template", ten):
		tkv = frappe.db.get_value("Account", {"company": CTY, "account_name": "Thue GTGT dau vao"}) or _tai_khoan_vat_vao()
		frappe.get_doc({"doctype": "Purchase Taxes and Charges Template", "title": "VAT mua theo mat hang", "company": CTY, "is_default": 1,
			"taxes": [{"charge_type": "On Net Total", "account_head": tkv, "description": "VAT", "rate": 0, "category": "Total", "add_deduct_tax": "Add"}]}).insert()


def _tai_khoan_vat_vao():
	nhom = frappe.db.get_value("Account", {"company": CTY, "account_name": "Duties and Taxes", "is_group": 1})
	d = frappe.get_doc({"doctype": "Account", "account_name": "Thue GTGT dau vao", "parent_account": nhom, "company": CTY, "account_type": "Tax", "is_group": 0}).insert()
	return d.name


def _dieu_khoan_tt():
	for ma, ngay in (("COD", 0), ("NET7", 7), ("NET15", 15), ("NET30", 30), ("NET45", 45), ("NET60", 60)):
		if not frappe.db.exists("Payment Term", ma):
			frappe.get_doc({"doctype": "Payment Term", "payment_term_name": ma, "invoice_portion": 100,
				"due_date_based_on": "Day(s) after invoice date", "credit_days": ngay}).insert()
		if not frappe.db.exists("Payment Terms Template", ma):
			frappe.get_doc({"doctype": "Payment Terms Template", "template_name": ma,
				"terms": [{"payment_term": ma, "invoice_portion": 100, "due_date_based_on": "Day(s) after invoice date", "credit_days": ngay}]}).insert()


def _hinh_thuc_tt():
	cash = frappe.db.get_value("Account", {"company": CTY, "account_type": "Cash", "is_group": 0})
	bank = frappe.db.get_value("Account", {"company": CTY, "account_type": "Bank", "is_group": 0})
	for ten, loai, tk in (("Tien mat", "Cash", cash), ("Chuyen khoan", "Bank", bank), ("Vi dien tu", "General", bank)):
		if not frappe.db.exists("Mode of Payment", ten):
			frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": ten, "type": loai, "enabled": 1,
				"accounts": [{"company": CTY, "default_account": tk}]}).insert()


def _bang_gia():
	for ten, selling in (("Gia chuan", 1), ("Gia nhom VIP", 1), ("Gia nhap", 0)):
		if not frappe.db.exists("Price List", ten):
			frappe.get_doc({"doctype": "Price List", "price_list_name": ten, "currency": "VND", "enabled": 1,
				"selling": selling, "buying": 0 if selling else 1}).insert()
	for g in ("Thuong", "VIP"):
		if not frappe.db.exists("Customer Group", g):
			frappe.get_doc({"doctype": "Customer Group", "customer_group_name": g, "parent_customer_group": "All Customer Groups",
				"default_price_list": "Gia nhom VIP" if g == "VIP" else "Gia chuan"}).insert()


def _hang_hoa():
	if not frappe.db.exists("Item Group", "Hang NPP"):
		frappe.get_doc({"doctype": "Item Group", "item_group_name": "Hang NPP", "parent_item_group": "All Item Groups"}).insert()
	vat_tpl = lambda r: f"VAT {r}% - {ABBR}"
	for i in range(1, 41):
		ma = f"SP{i:03d}"
		if frappe.db.exists("Item", ma):
			continue
		theo_lo = i <= 30  # 30 mặt hàng theo lô, 10 không lô (được bán âm) — CFD-05 B
		d = frappe.get_doc({
			"doctype": "Item", "item_code": ma, "item_name": f"Mat hang {i}", "item_group": "Hang NPP",
			"stock_uom": "Lon", "is_stock_item": 1,
			"has_batch_no": 1 if theo_lo else 0, "create_new_batch": 0,
			"has_expiry_date": 1 if (theo_lo and i % 3 != 0) else 0,
			"shelf_life_in_days": 365 if (theo_lo and i % 3 != 0) else 0,
			"allow_negative_stock": 0 if theo_lo else 1,
			"valuation_method": "FIFO",
			"uoms": [{"uom": "Lon", "conversion_factor": 1}, {"uom": "Loc", "conversion_factor": 6}, {"uom": "Thung", "conversion_factor": 24}],
			"item_defaults": [{"company": CTY, "default_warehouse": KHO_BAN}],
			"barcodes": [{"barcode": f"893{i:010d}"}],
		})
		d.insert()
		gia_lon = 10_000 + i * 137  # giá lẻ để thử làm tròn
		for uom, cf in (("Lon", 1), ("Loc", 6), ("Thung", 24)):
			frappe.get_doc({"doctype": "Item Price", "item_code": ma, "price_list": "Gia chuan", "uom": uom, "price_list_rate": gia_lon * cf - (cf > 1 and 500 or 0)}).insert()
			frappe.get_doc({"doctype": "Item Price", "item_code": ma, "price_list": "Gia nhap", "uom": uom, "price_list_rate": int(gia_lon * cf * 0.8)}).insert()


def _khach_ncc():
	for i in range(1, 11):
		ten = f"Tap hoa so {i}"
		if not frappe.db.exists("Customer", {"customer_name": ten}):
			frappe.get_doc({"doctype": "Customer", "customer_name": ten, "customer_group": "VIP" if i % 4 == 0 else "Thuong",
				"territory": "All Territories", "customer_type": "Individual", "mobile_no": f"09{i:08d}",
				"payment_terms": "NET30" if i % 2 else "COD"}).insert()
	for i in range(1, 4):
		ten = f"NCC {i}"
		if not frappe.db.exists("Supplier", {"supplier_name": ten}):
			frappe.get_doc({"doctype": "Supplier", "supplier_name": ten, "supplier_group": "All Supplier Groups", "supplier_type": "Company"}).insert()
