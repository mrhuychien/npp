"""PoC P0 — mười điểm đo. Mỗi hàm chạy độc lập, in kết quả dạng JSON một dòng cuối cùng.

bench --site poc.local execute nppsale.poc.do.<ham> [--kwargs '{...}']
"""
import json, time, random
from decimal import Decimal, ROUND_HALF_UP
import frappe
from frappe.utils import flt, nowdate, add_days, now_datetime, getdate, get_datetime
from erpnext.stock.doctype.batch.batch import get_batch_qty

CTY = "NPP Thu"; ABBR = "NPP"
KHO_BAN = f"Kho ban - {ABBR}"; KHO_DATE = f"Kho can date - {ABBR}"
VAT_TPL = f"VAT theo mat hang - {ABBR}"
VAT_MUA_TPL = f"VAT mua theo mat hang - {ABBR}"
ITEM_TPL = lambda r: f"VAT {r}% - {ABBR}"


def _out(d):
	print("KQ " + json.dumps(d, ensure_ascii=False, default=str))
	return d


def _items(theo_lo=True):
	return frappe.get_all("Item", filters={"item_group": "Hang NPP", "has_batch_no": 1 if theo_lo else 0, "disabled": 0}, pluck="name", order_by="name")


def _khach(i=1):
	return frappe.get_all("Customer", filters={"customer_name": f"Tap hoa so {i}"}, pluck="name")[0]


def _ncc(i=1):
	return frappe.get_all("Supplier", filters={"supplier_name": f"NCC {i}"}, pluck="name")[0]


def _gia(item, uom="Lon", bang="Gia chuan"):
	return flt(frappe.db.get_value("Item Price", {"item_code": item, "price_list": bang, "uom": uom}, "price_list_rate"))


# ─────────────────────────────── tồn ban đầu ───────────────────────────────

def nhap_ton(so_lo=3, sl_moi_lo=240, ngay_lui=30, commit=True, lo_bat_dau=1):
	"""Mỗi mặt hàng theo lô: so_lo lô (PI riêng, ngày nhập lùi dần) vào Kho bán; hàng không lô: Material Receipt."""
	kq = {"pi": [], "se": None}
	for k in range(so_lo):
		ngay = add_days(nowdate(), -ngay_lui + k * 7)
		pi = frappe.new_doc("Purchase Invoice")
		pi.update({"supplier": _ncc(1), "company": CTY, "posting_date": ngay, "set_posting_time": 1, "update_stock": 1,
			"set_warehouse": KHO_BAN, "bill_no": f"NCC-{k+int(lo_bat_dau)}", "bill_date": ngay, "taxes_and_charges": VAT_MUA_TPL})
		for it in _items(True):
			ma_lo = f"{it}-L{k+int(lo_bat_dau)}"
			if not frappe.db.exists("Batch", ma_lo):
				hsd = add_days(ngay, 365) if frappe.db.get_value("Item", it, "has_expiry_date") else None
				b = frappe.get_doc({"doctype": "Batch", "batch_id": ma_lo, "item": it, "manufacturing_date": ngay})
				if hsd: b.expiry_date = hsd
				b.insert()
			pi.append("items", {"item_code": it, "qty": sl_moi_lo, "uom": "Lon", "conversion_factor": 1, "rate": _gia(it, "Lon", "Gia nhap") + k * 10,
				"warehouse": KHO_BAN, "use_serial_batch_fields": 1, "batch_no": ma_lo, "item_tax_template": ITEM_TPL(8)})
		_set_taxes(pi, "Purchase Taxes and Charges Template", VAT_MUA_TPL)
		pi.insert(); pi.submit()
		kq["pi"].append(pi.name)
	se = frappe.new_doc("Stock Entry")
	se.update({"stock_entry_type": "Material Receipt", "company": CTY, "to_warehouse": KHO_BAN})
	for it in _items(False):
		se.append("items", {"item_code": it, "qty": sl_moi_lo * so_lo, "uom": "Lon", "conversion_factor": 1, "t_warehouse": KHO_BAN, "basic_rate": _gia(it, "Lon", "Gia nhap")})
	se.insert(); se.submit(); kq["se"] = se.name
	if commit: frappe.db.commit()
	return _out(kq)


def _set_taxes(doc, dt, tpl):
	from erpnext.controllers.accounts_controller import get_taxes_and_charges
	doc.set("taxes", [])
	for t in get_taxes_and_charges(dt, tpl):
		doc.append("taxes", t)


# ─────────────────────────── (1) Xuất hàng + đồng thời ───────────────────────────

def chon_lo_fifo(item, kho, can):
	"""FIFO theo thứ tự tạo lô trong kho — app tự chọn (không dùng auto-pick của lõi)."""
	ra = []
	for b in get_batch_qty(item_code=item, warehouse=kho) or []:
		if can <= 0: break
		lay = min(flt(b.get("qty")), can)
		if lay <= 0: continue
		ra.append((b.get("batch_no"), lay)); can -= lay
	return ra, can


def xuat_hang_mot(so_dong=15, khach=1, in_kq=True, dong_thoi_tag="", cach="bundle", dong_co_dinh=None, khoa=False):
	"""Một lượt Xuất hàng: SO (nháp) → submit → SI update_stock từ Kho bán, app gán lô, submit. Trả thời gian từng bước (ms)."""
	t = {}; t0 = time.perf_counter()
	items_lo = _items(True); items_kl = _items(False)
	chon = random.sample(items_lo, max(0, min(so_dong - 2, len(items_lo)))) + random.sample(items_kl, min(2, max(0, so_dong)))
	if dong_co_dinh:
		chon = [d[0] for d in dong_co_dinh]
	so = frappe.new_doc("Sales Order")
	so.update({"customer": _khach(khach), "company": CTY, "transaction_date": nowdate(), "delivery_date": nowdate(),
		"set_warehouse": KHO_BAN, "taxes_and_charges": VAT_TPL, "ignore_pricing_rule": 1})
	for k, it in enumerate(chon):
		uom = random.choice(["Lon", "Loc", "Thung"]); cf = {"Lon": 1, "Loc": 6, "Thung": 24}[uom]
		sl = random.randint(1, 3)
		if dong_co_dinh:
			uom, sl = dong_co_dinh[k][1], dong_co_dinh[k][2]; cf = {"Lon": 1, "Loc": 6, "Thung": 24}[uom]
		so.append("items", {"item_code": it, "qty": sl, "uom": uom, "conversion_factor": cf,
			"rate": _gia(it, uom), "price_list_rate": _gia(it, uom), "item_tax_template": ITEM_TPL(random.choice([0, 8, 10])), "warehouse": KHO_BAN})
	_set_taxes(so, "Sales Taxes and Charges Template", VAT_TPL)
	so.insert(); t["so_insert"] = _ms(t0); t1 = time.perf_counter()
	so.submit(); t["so_submit"] = _ms(t1); t2 = time.perf_counter()
	if khoa:
		# Thực tế: đơn đã chốt ở lượt trước; lượt Xuất hàng là giao dịch MỚI mà câu đầu tiên là khoá Bin (FOR UPDATE)
		# → ảnh chụp dữ liệu (REPEATABLE READ) chỉ được lập ở câu đọc thường kế tiếp, tức SAU khi giành được khoá.
		mat_hang_lo = sorted({d.item_code for d in so.items if frappe.db.get_value("Item", d.item_code, "has_batch_no")})
		frappe.db.commit()
		tk = time.perf_counter(); _khoa_bin(mat_hang_lo); t["khoa_ms"] = _ms(tk)
	from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
	si = make_sales_invoice(so.name)
	si.update({"update_stock": 1, "set_warehouse": KHO_BAN, "posting_date": nowdate(), "set_posting_time": 1,
		"taxes_and_charges": VAT_TPL, "ignore_pricing_rule": 1})
	gan_lo_cho_tung_dong(si, cach)
	_set_taxes(si, "Sales Taxes and Charges Template", VAT_TPL)
	t["dong"] = [(d.item_code, d.uom, d.qty, d.conversion_factor, d.batch_no) for d in si.items]
	try:
		si.insert(); t["si_insert"] = _ms(t2); t3 = time.perf_counter()
		t["dong_sau_insert"] = [(d.item_code, d.uom, d.qty, d.stock_qty, d.batch_no, d.serial_and_batch_bundle) for d in si.items]
		si.submit(); t["si_submit"] = _ms(t3)
	except Exception as e:
		t["LOI"] = type(e).__name__ + ": " + str(e)[:200]
		frappe.db.rollback()
		return _out(t) if in_kq else t
	t["tong"] = _ms(t0); t["so"] = so.name; t["si"] = si.name; t["so_dong"] = len(si.items); t["tag"] = dong_thoi_tag
	frappe.db.commit()
	return _out(t) if in_kq else t



def _khoa_bin(items, kho=KHO_BAN):
	"""Khoá hàng Bin của từng mặt hàng theo thứ tự tên (không bế tắc) tới khi giao dịch kết thúc — câu ĐẦU của giao dịch."""
	for it in items:
		frappe.db.sql("select name from `tabBin` where item_code=%s and warehouse=%s for update", (it, kho))


def gan_lo_cho_tung_dong(si, cach="bundle"):
	"""App tự gán lô FIFO cho mọi dòng hàng theo lô. cach="bundle": một dòng + một Serial and Batch Bundle nhiều lô
	(không tách dòng, không bị lõi chọn lại); cach="tach_dong": tách dòng, ghi batch_no (cách cũ, để so)."""
	from erpnext.stock.serial_batch_bundle import SerialBatchCreation
	for d in list(si.items):
		d.warehouse = KHO_BAN
		if not frappe.db.get_value("Item", d.item_code, "has_batch_no"):
			continue
		can = flt(d.qty) * flt(d.conversion_factor)
		phan, thieu = chon_lo_fifo(d.item_code, KHO_BAN, can)
		if thieu > 0:
			frappe.throw(f"THIEU_TON {d.item_code} thiếu {thieu} lon")
		if cach == "bundle":
			sbc = SerialBatchCreation({"item_code": d.item_code, "warehouse": KHO_BAN, "posting_date": si.posting_date, "posting_time": si.posting_time,
				"voucher_type": "Sales Invoice", "qty": can, "type_of_transaction": "Outward", "company": si.company,
				"batches": frappe._dict({lo: sl for lo, sl in phan}), "do_not_submit": True})
			b = sbc.make_serial_and_batch_bundle()
			d.serial_and_batch_bundle = b.name; d.use_serial_batch_fields = 0; d.batch_no = None
		else:
			for i, (lo, sl) in enumerate(phan):
				r = d if i == 0 else si.append("items", d.as_dict(no_default_fields=True))
				r.use_serial_batch_fields = 1; r.batch_no = lo
				r.qty = sl / flt(d.conversion_factor)
				if i > 0: r.so_detail = None; r.sales_order = None; r.name = None


def xuat_hang_tach_lo(item="SP016", uom="Thung", qty=2, cach="bundle"):
	"""Dòng cần nhiều hơn lô đầu còn lại → phải lấy từ hai lô. So hai cách gán lô."""
	return xuat_hang_mot(so_dong=1, khach=5, cach=cach, dong_co_dinh=[(item, uom, qty)])


def _ms(t0):
	return round((time.perf_counter() - t0) * 1000)


def xuat_hang_nhieu(lan=10, so_dong=15):
	tat = [xuat_hang_mot(so_dong=so_dong, khach=1 + i % 10, in_kq=False) for i in range(int(lan))]
	kq = [x for x in tat if "tong" in x]; loi = [x.get("LOI") for x in tat if "LOI" in x]
	if not kq:
		return _out({"lan": len(tat), "loi": loi})
	tong = sorted(x["tong"] for x in kq)
	return _out({"lan": len(kq), "loi": loi, "tong_ms_min": tong[0], "tong_ms_tb": round(sum(tong) / len(tong)), "tong_ms_max": tong[-1],
		"buoc_tb": {k: round(sum(x[k] for x in kq) / len(kq)) for k in ("so_insert", "so_submit", "si_insert", "si_submit")}})


# ─────────────────────────── (2) thuế + làm tròn ───────────────────────────

def _tron(x):
	"""Làm tròn nửa XA 0 về đồng — như round(numeric) của Postgres trong post_invoice và Math.round (số dương) ở POS nppsale.
	(Bản đo 05/11 dùng round() của Python — làm tròn nửa về số CHẴN — nên mọi ca ",5" bị đếm nhầm là lệch.)"""
	return Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def dat_precision(p="0"):
	"""Đổi System Settings.currency_precision (dùng cho bài so precision 0 / 2), xoá cache."""
	ss = frappe.get_doc("System Settings")
	ss.currency_precision = str(p)
	ss.flags.ignore_mandatory = True
	ss.save()
	frappe.db.commit()
	frappe.clear_cache()
	return _out({"currency_precision": frappe.db.get_single_value("System Settings", "currency_precision")})


def thue_lam_tron(n=50, dong_min=10, dong_max=20, giam_don_pct=0, ty_le_giam_dong=0.3, cach_giam_dong="app", seed=1, ty_le_sl_le=0, luat_dong="pos"):
	"""So tiền hàng / VAT / tổng của lõi với công thức nppsale (post_invoice sau mig 183), ĐÚNG từng đồng (không ngưỡng):
	  g            = round(SL × giá bảng)                    (lineGross, src/lib/pos/discount.ts)
	  tiền giảm    = min(g, round(g × % / 100))              (discountAmount — % tính trên TIỀN DÒNG)
	  đơn giá dòng = round((g − tiền giảm) / SL)             (đơn giá ghi sổ). luat_dong="pos": quy cho MỌI dòng như POS lúc lập đơn
	                 (posLinesToCart); luat_dong="hoa_don": chỉ quy ở dòng có giảm, dòng không giảm giữ giá như /sell (netPriceOf)
	                 và màn hoá đơn (toDraftCoGiam / toDraft). SL nguyên thì hai luật như nhau.
	  tiền dòng    = SL × đơn giá                            (post_invoice: line_total numeric, KHÔNG làm tròn từng dòng)
	  VAT          = round(Σ tiền dòng × thuế suất dòng)
	  tổng         = round(Σ tiền dòng − giảm đơn + Σ tiền dòng × thuế suất)
	round = làm tròn nửa xa 0. Mỗi HĐ dong_min..dong_max dòng chọn trong 40 mặt hàng, đơn vị Lon / Loc / Thung, SL 1–20,
	thuế 0 / 5 / 8 / 10 %, ty_le_giam_dong số dòng có giảm %; ty_le_sl_le > 0: chừng ấy dòng mang SL lẻ 0,5 / 1,5 / 2,5 / 3,5
	(mặc định 0 — khi 0 không gọi thêm số ngẫu nhiên nào nên chuỗi HĐ y hệt lượt đo 06/11). cach_giam_dong:
	  "app" — app gửi sẵn đơn giá sau giảm (rate) kèm price_list_rate + discount_percentage;
	  "loi" — chỉ gửi price_list_rate + discount_percentage, để lõi tự tính rate.
	HĐ lập rồi rollback, không để lại sổ."""
	rnd = random.Random(int(seed))
	items = _items(True) + _items(False)
	don_vi = (("Lon", 1), ("Loc", 6), ("Thung", 24))
	tk_giam = frappe.db.get_value("Account", {"company": CTY, "account_name": "Miscellaneous Expenses", "is_group": 0})
	dem = {"hd": 0, "dong": 0, "dong_giam": 0, "dong_sl_le": 0, "hd_co_sl_le": 0, "lech_don_gia": 0, "mat_pct": 0, "lech_tien_hang": 0,
		"lech_vat": 0, "vat_co_le": 0, "lech_grand": 0, "lech_rounded": 0, "lech_tong_max": 0}
	mau = []
	for i in range(int(n)):
		si = frappe.new_doc("Sales Invoice")
		si.update({"customer": _khach(1 + i % 10), "company": CTY, "update_stock": 0, "taxes_and_charges": VAT_TPL,
			"ignore_pricing_rule": 1, "is_cash_or_non_trade_discount": 1 if giam_don_pct else 0})
		dong_npp = []
		for it in rnd.sample(items, min(rnd.randint(int(dong_min), int(dong_max)), len(items))):
			uom, cf = rnd.choice(don_vi)
			plr = Decimal(str(_gia(it, uom)))
			qty = rnd.randint(1, 20)
			if float(ty_le_sl_le) > 0 and rnd.random() < float(ty_le_sl_le):
				qty = rnd.choice([0.5, 1.5, 2.5, 3.5])
			r = rnd.choice([0, 5, 8, 10])
			pct = Decimal(str(rnd.choice([2, 2.5, 3, 5, 7.5, 10, 12.5, 15]))) if rnd.random() < float(ty_le_giam_dong) else Decimal(0)
			# Luật thật của nppsale (đo lại 10/11/2026; bản 06/11 dùng bản rút gọn round(giá × (1 − %)) — sai):
			sl = Decimal(str(qty))
			g = _tron(sl * plr)
			tien_giam = min(g, _tron(g * pct / Decimal(100))) if pct else Decimal(0)
			don_gia = _tron((g - tien_giam) / sl) if (pct or luat_dong == "pos") else plr
			row = {"item_code": it, "qty": qty, "uom": uom, "conversion_factor": cf, "price_list_rate": float(plr), "item_tax_template": ITEM_TPL(r)}
			if pct:
				row["discount_percentage"] = float(pct)
			if cach_giam_dong == "app":
				# app gửi đơn giá theo luật nppsale cho MỌI dòng: SL lẻ thì kể cả dòng không giảm, đơn giá cũng có thể khác giá bảng
				# (0,5 × 15.343 = 7.671,5 → 7.672 → đơn giá 15.344) — bản trước gửi giá bảng ở dòng không giảm (lỗi mã đo, sửa 10/11)
				row["rate"] = float(don_gia)
			elif not pct:
				row["rate"] = float(plr)
			si.append("items", row)
			dong_npp.append((it, sl, don_gia, Decimal(r), pct))
		_set_taxes(si, "Sales Taxes and Charges Template", VAT_TPL)
		tien_hang = sum(Decimal(q) * g for _, q, g, _, _ in dong_npp)
		if giam_don_pct:
			si.apply_discount_on = "Grand Total"; si.additional_discount_account = tk_giam
			si.discount_amount = float(_tron(tien_hang * Decimal(str(giam_don_pct)) / 100))
		si.insert()
		dem["hd"] += 1
		vat_tho = sum(Decimal(q) * g * r / 100 for _, q, g, r, _ in dong_npp)
		giam = Decimal(str(flt(si.discount_amount)))
		vat_npp = _tron(vat_tho)
		tong_npp = max(Decimal(0), _tron(tien_hang - giam + vat_tho))
		co_le = False
		for d, (it, q, g, r, pct) in zip(si.items, dong_npp):
			dem["dong"] += 1
			if q != q.to_integral_value():
				dem["dong_sl_le"] += 1; co_le = True
			if pct:
				dem["dong_giam"] += 1
				if not flt(d.discount_percentage):
					dem["mat_pct"] += 1
			if Decimal(str(flt(d.rate))) != g:
				dem["lech_don_gia"] += 1
				if len(mau) < 8:
					mau.append({"loai": "don_gia", "item": it, "uom": d.uom, "gia_bang": flt(d.price_list_rate), "pct": float(pct),
						"rate_loi": flt(d.rate), "giam_loi": flt(d.discount_amount), "don_gia_npp": float(g)})
		if co_le: dem["hd_co_sl_le"] += 1
		th = Decimal(str(flt(si.net_total))); vat = Decimal(str(flt(si.total_taxes_and_charges)))
		grand = Decimal(str(flt(si.grand_total))); rounded = Decimal(str(flt(si.rounded_total)))
		dem["lech_tong_max"] = max(dem["lech_tong_max"], float(abs(rounded - tong_npp)))
		# nppsale không làm tròn từng dòng (SL lẻ → tiền dòng có thể lẻ ,5) nên so tiền hàng với Σ đã làm tròn một lần
		if th != _tron(tien_hang): dem["lech_tien_hang"] += 1
		if vat != vat_npp: dem["lech_vat"] += 1
		if vat != vat.to_integral_value(): dem["vat_co_le"] += 1
		if grand != tong_npp: dem["lech_grand"] += 1
		if rounded != tong_npp: dem["lech_rounded"] += 1
		if (th != tien_hang or vat != vat_npp or rounded != tong_npp or grand != tong_npp) and len(mau) < 14:
			mau.append({"loai": "hd", "si": si.name, "so_dong": len(si.items), "co_sl_le": co_le, "tien_hang_loi": float(th), "tien_hang_npp": float(tien_hang),
				"vat_loi": float(vat), "vat_tho": float(vat_tho), "vat_npp": float(vat_npp), "grand_loi": float(grand), "rounded_loi": float(rounded),
				"tong_npp": float(tong_npp), "giam_don": float(giam)})
	frappe.db.rollback()
	return _out({"tham_so": {"n": int(n), "dong": [int(dong_min), int(dong_max)], "giam_don_pct": giam_don_pct, "ty_le_giam_dong": ty_le_giam_dong,
			"cach_giam_dong": cach_giam_dong, "seed": int(seed), "ty_le_sl_le": float(ty_le_sl_le), "luat_dong": luat_dong, "luat_don_gia": "nppsale that (10/11)"},
		"precision": frappe.db.get_single_value("System Settings", "currency_precision"),
		"rounding": frappe.db.get_single_value("System Settings", "rounding_method"),
		"round_row_wise_tax": frappe.db.get_single_value("Accounts Settings", "round_row_wise_tax"),
		**dem, "mau": mau})


# ─────────────────────────── (3) giảm đầu phiếu nhập ───────────────────────────

def giam_dau_phieu_nhap(giam=50_000):
	"""PI 3 dòng + khoản giảm đầu phiếu dạng dòng thuế Deduct (Actual) — xem net dòng, VAT, giá vốn lô có bị hạ không; so với apply_discount_on."""
	kq = {}
	for cach in ("deduct_row", "apply_discount_on"):
		pi = frappe.new_doc("Purchase Invoice")
		ngay = nowdate()
		pi.update({"supplier": _ncc(2), "company": CTY, "update_stock": 1, "set_warehouse": KHO_BAN, "bill_no": f"GD-{cach}", "bill_date": ngay, "taxes_and_charges": VAT_MUA_TPL})
		items = _items(True)[:3]
		for i, it in enumerate(items):
			lo = f"{it}-GD-{cach}"
			if not frappe.db.exists("Batch", lo):
				frappe.get_doc({"doctype": "Batch", "batch_id": lo, "item": it, "expiry_date": add_days(ngay, 300) if frappe.db.get_value("Item", it, "has_expiry_date") else None}).insert()
			pi.append("items", {"item_code": it, "qty": 10, "uom": "Lon", "conversion_factor": 1, "rate": 20_000 + i * 1000, "warehouse": KHO_BAN,
				"use_serial_batch_fields": 1, "batch_no": lo, "item_tax_template": ITEM_TPL(8)})
		_set_taxes(pi, "Purchase Taxes and Charges Template", VAT_MUA_TPL)
		if cach == "deduct_row":
			tk = frappe.db.get_value("Account", {"company": CTY, "account_name": "Miscellaneous Expenses", "is_group": 0})
			pi.append("taxes", {"charge_type": "Actual", "add_deduct_tax": "Deduct", "category": "Total", "account_head": tk, "description": "Giam dau phieu", "tax_amount": giam})
		else:
			pi.apply_discount_on = "Grand Total"; pi.discount_amount = giam
		try:
			pi.insert(); pi.submit()
			sle = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": pi.name, "is_cancelled": 0}, fields=["item_code", "incoming_rate", "valuation_rate", "actual_qty"])
			kq[cach] = {"pi": pi.name, "net_total": pi.net_total, "vat": pi.total_taxes_and_charges, "grand_total": pi.grand_total, "rounded_total": pi.rounded_total,
				"net_dong": [d.net_amount for d in pi.items], "gia_von_lo": [(s.item_code, s.incoming_rate) for s in sle]}
		except Exception as e:
			frappe.db.rollback(); kq[cach] = {"LOI": str(e)[:300]}
	frappe.db.commit()
	return _out(kq)


# ─────────────────────────── (4) LCV trên lô đã bán ───────────────────────────

def lcv_sua_gia(pi_name=None, so_tien=-30_000):
	"""Landed Cost Voucher âm / dương lên PI đã có lô bán ra → giá vốn đổi, số PN giữ."""
	if not pi_name:
		pi_name = frappe.get_all("Purchase Invoice", filters={"docstatus": 1, "update_stock": 1, "company": CTY}, order_by="creation asc", pluck="name")[0]
	pi = frappe.get_doc("Purchase Invoice", pi_name)
	lcv = frappe.new_doc("Landed Cost Voucher")
	lcv.company = CTY
	lcv.append("purchase_receipts", {"receipt_document_type": "Purchase Invoice", "receipt_document": pi.name, "supplier": pi.supplier, "grand_total": pi.grand_total})
	lcv.get_items_from_purchase_receipts()
	tk = frappe.db.get_value("Account", {"company": CTY, "account_name": "Miscellaneous Expenses", "is_group": 0})
	lcv.append("taxes", {"expense_account": tk, "description": "Sua gia nhap", "amount": so_tien})
	lcv.distribute_charges_based_on = "Amount"
	try:
		moc = now_datetime()
		lcv.insert(); lcv.submit()
		# Việc tính lại sinh theo MẶT HÀNG + KHO (voucher_no trống) — đếm theo giờ tạo, không theo số chứng từ
		riv = frappe.get_all("Repost Item Valuation", filters={"creation": [">=", moc]}, fields=["status", "count(name) as n"], group_by="status")
		frappe.db.commit()
		return _out({"lcv": lcv.name, "pi_van_la": pi.name, "viec_tinh_lai": riv})
	except Exception as e:
		frappe.db.rollback(); return _out({"LOI": str(e)[:400]})


# ─────────────────────── (5) tờ ghi có độc lập có kho: lô + giá vốn ───────────────────────

def ghi_co_doc_lap(kho=KHO_DATE, dat_incoming_rate=True, ban_het=False):
	"""Credit note độc lập (không return_against) update_stock=1 nhập vào `kho`; kiểm incoming_rate ghi trên SLE."""
	it = _items(True)[0]
	lo = get_batch_qty(item_code=it, warehouse=KHO_BAN)[0]["batch_no"]
	gia_von_goc = flt(frappe.db.get_value("Stock Ledger Entry", {"batch_no": lo, "actual_qty": [">", 0], "is_cancelled": 0}, "incoming_rate"))
	if ban_het:
		# bán sạch lô ấy khỏi kho bán để test ca "lô đã hết"
		con = flt(get_batch_qty(batch_no=lo, warehouse=KHO_BAN))
		if con > 0:
			si0 = frappe.new_doc("Sales Invoice")
			si0.update({"customer": _khach(2), "company": CTY, "update_stock": 1, "set_warehouse": KHO_BAN, "taxes_and_charges": VAT_TPL, "ignore_pricing_rule": 1})
			si0.append("items", {"item_code": it, "qty": con, "uom": "Lon", "conversion_factor": 1, "rate": _gia(it), "warehouse": KHO_BAN, "use_serial_batch_fields": 1, "batch_no": lo, "item_tax_template": ITEM_TPL(0)})
			_set_taxes(si0, "Sales Taxes and Charges Template", VAT_TPL); si0.insert(); si0.submit()
	cn = frappe.new_doc("Sales Invoice")
	cn.update({"customer": _khach(2), "company": CTY, "is_return": 1, "update_stock": 1, "set_warehouse": kho, "taxes_and_charges": VAT_TPL, "ignore_pricing_rule": 1})
	row = {"item_code": it, "qty": -5, "uom": "Lon", "conversion_factor": 1, "rate": _gia(it) * 1.1, "warehouse": kho, "use_serial_batch_fields": 1, "batch_no": lo, "item_tax_template": ITEM_TPL(0)}
	if dat_incoming_rate: row["incoming_rate"] = gia_von_goc
	cn.append("items", row)
	_set_taxes(cn, "Sales Taxes and Charges Template", VAT_TPL)
	try:
		cn.insert(); cn.submit()
		sle = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": cn.name, "is_cancelled": 0}, fields=["warehouse", "batch_no", "actual_qty", "incoming_rate", "valuation_rate", "stock_value_difference"])
		frappe.db.commit()
		return _out({"cn": cn.name, "outstanding": cn.outstanding_amount, "gia_von_goc": gia_von_goc, "gia_ban_dong": row["rate"], "dat_incoming_rate": dat_incoming_rate, "ban_het": ban_het, "sle": sle})
	except Exception as e:
		frappe.db.rollback(); return _out({"LOI": str(e)[:400], "ban_het": ban_het, "dat_incoming_rate": dat_incoming_rate})


# ─────────────────────── (6) repost khi huỷ / sửa ───────────────────────

def repost_khi_huy(si_name=None):
	"""Huỷ một HĐ cũ (có chứng từ sau) → Repost Item Valuation sinh ra; chạy ngay và đo thời gian."""
	from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost_entries
	if not si_name:
		si_name = frappe.get_all("Sales Invoice", filters={"docstatus": 1, "update_stock": 1, "is_return": 0, "company": CTY}, order_by="creation asc", pluck="name")[0]
	moc = now_datetime()
	t0 = time.perf_counter()
	si = frappe.get_doc("Sales Invoice", si_name); si.cancel()
	t_cancel = _ms(t0)
	# Việc tính lại sinh theo MẶT HÀNG + KHO, voucher_no TRỐNG (lọc theo số HĐ sẽ ra rỗng) — đếm theo giờ tạo
	loc = {"creation": [">=", moc]}
	# repost_entries() chạy MỌI việc đang chờ của cả site (repost_item_valuation.py:840–843) và thoát ngay khi bật tính lại song song
	# (:834–835): còn việc cũ đang chờ (sổ PoC đang giữ 40 việc Queued từ 06/11) hay đang bật song song thì giờ đo không còn là của
	# riêng lần huỷ này — dừng, trả sổ như cũ. lcv_kiem_lai cần cùng chốt (nó còn đếm mọi việc của site, không lọc giờ tạo).
	viec_cu = frappe.db.count("Repost Item Valuation", {"status": ["in", ["Queued", "In Progress"]], "creation": ["<", moc]})
	if viec_cu or frappe.db.get_single_value("Stock Reposting Settings", "enable_parallel_reposting"):
		frappe.db.rollback()
		return _out({"si": si_name, "LOI": f"còn {viec_cu} việc tính lại cũ đang chờ hoặc đang bật tính lại song song — xử lý xong rồi mới đo"})
	riv = frappe.get_all("Repost Item Valuation", filters=loc, fields=["based_on", "status", "count(name) as n"], group_by="based_on, status")
	frappe.db.commit()
	t1 = time.perf_counter()
	repost_entries()
	t_repost = _ms(t1)
	riv2 = frappe.get_all("Repost Item Valuation", filters=loc, fields=["status", "count(name) as n"], group_by="status")
	frappe.db.commit()
	return _out({"si": si_name, "cancel_ms": t_cancel, "viec_sau_huy": riv, "repost_ms": t_repost, "viec_sau_repost": riv2})


# ─────────────────────── (8) hai dòng cùng mặt hàng cùng lô; đổi mã lô ───────────────────────

def hai_dong_cung_lo():
	it = _items(True)[1]
	lo = get_batch_qty(item_code=it, warehouse=KHO_BAN)[0]["batch_no"]
	kq = {}
	for bat in (1, 0):
		frappe.db.set_single_value("Selling Settings", "allow_multiple_items", bat)
		si = frappe.new_doc("Sales Invoice")
		si.update({"customer": _khach(3), "company": CTY, "update_stock": 1, "set_warehouse": KHO_BAN, "taxes_and_charges": VAT_TPL, "ignore_pricing_rule": 1})
		si.append("items", {"item_code": it, "qty": 1, "uom": "Thung", "conversion_factor": 24, "rate": _gia(it, "Thung"), "warehouse": KHO_BAN, "use_serial_batch_fields": 1, "batch_no": lo, "item_tax_template": ITEM_TPL(8)})
		si.append("items", {"item_code": it, "qty": 3, "uom": "Lon", "conversion_factor": 1, "rate": _gia(it, "Lon"), "warehouse": KHO_BAN, "use_serial_batch_fields": 1, "batch_no": lo, "item_tax_template": ITEM_TPL(8)})
		_set_taxes(si, "Sales Taxes and Charges Template", VAT_TPL)
		try:
			si.insert(); si.submit(); kq[f"allow_multiple_items={bat}"] = {"ok": si.name}; frappe.db.commit()
		except Exception as e:
			frappe.db.rollback(); kq[f"allow_multiple_items={bat}"] = {"LOI": str(e)[:200]}
	frappe.db.set_single_value("Selling Settings", "allow_multiple_items", 1); frappe.db.commit()
	return _out(kq)


def doi_ma_lo():
	it = _items(True)[2]
	lo = get_batch_qty(item_code=it, warehouse=KHO_BAN)[0]["batch_no"]
	try:
		moi = frappe.rename_doc("Batch", lo, lo + "-DOI")
		frappe.db.commit()
		sle = frappe.db.count("Stock Ledger Entry", {"batch_no": moi, "is_cancelled": 0})
		return _out({"doi_duoc": True, "moi": moi, "sle_theo_ma_moi": sle})
	except Exception as e:
		frappe.db.rollback(); return _out({"doi_duoc": False, "LOI": str(e)[:300]})


# ─────────────────────── (9) nhập lại lô đã hết hạn ───────────────────────

def nhap_lai_lo_het_han():
	it = [i for i in _items(True) if frappe.db.get_value("Item", i, "has_expiry_date")][0]
	lo = f"{it}-HETHAN"
	if not frappe.db.exists("Batch", lo):
		frappe.get_doc({"doctype": "Batch", "batch_id": lo, "item": it, "manufacturing_date": add_days(nowdate(), -400), "expiry_date": add_days(nowdate(), -10)}).insert()
	kq = {}
	# cách 1: dòng ghi batch_no
	se = frappe.new_doc("Stock Entry"); se.update({"stock_entry_type": "Material Receipt", "company": CTY, "to_warehouse": KHO_DATE})
	se.append("items", {"item_code": it, "qty": 5, "uom": "Lon", "conversion_factor": 1, "t_warehouse": KHO_DATE, "basic_rate": 10_000, "use_serial_batch_fields": 1, "batch_no": lo})
	try:
		se.insert(); se.submit(); kq["dong_co_batch_no"] = {"ok": se.name}; frappe.db.commit()
	except Exception as e:
		frappe.db.rollback(); kq["dong_co_batch_no"] = {"LOI": type(e).__name__ + ": " + str(e)[:200]}
	# cách 2: bundle Inward do app tạo, dòng không ghi batch_no
	try:
		from erpnext.stock.serial_batch_bundle import SerialBatchCreation
		se2 = frappe.new_doc("Stock Entry"); se2.update({"stock_entry_type": "Material Receipt", "company": CTY, "to_warehouse": KHO_DATE})
		se2.append("items", {"item_code": it, "qty": 5, "uom": "Lon", "conversion_factor": 1, "t_warehouse": KHO_DATE, "basic_rate": 10_000})
		se2.insert()
		sbc = SerialBatchCreation({"item_code": it, "warehouse": KHO_DATE, "posting_date": se2.posting_date, "posting_time": se2.posting_time, "voucher_type": "Stock Entry",
			"voucher_no": se2.name, "voucher_detail_no": se2.items[0].name, "qty": 5, "type_of_transaction": "Inward", "company": CTY, "batches": frappe._dict({lo: 5}), "do_not_submit": True})
		bundle = sbc.make_serial_and_batch_bundle()
		se2.items[0].serial_and_batch_bundle = bundle.name; se2.items[0].use_serial_batch_fields = 0
		se2.save(); se2.submit()
		kq["bundle_inward"] = {"ok": se2.name, "bundle": bundle.name}; frappe.db.commit()
	except Exception as e:
		frappe.db.rollback(); kq["bundle_inward"] = {"LOI": type(e).__name__ + ": " + str(e)[:300]}
	return _out(kq)


# ─────────────────────── (10) tờ đầu kỳ giữ mã cũ ───────────────────────

def dau_ky_giu_ma(ma="HD-0042", ngay="2026-06-15", tien=1_250_000):
	tk_tam = frappe.db.get_value("Account", {"company": CTY, "account_type": "Temporary", "is_group": 0})
	si = frappe.new_doc("Sales Invoice")
	si.update({"customer": _khach(4), "company": CTY, "is_opening": "Yes", "posting_date": ngay, "set_posting_time": 1, "due_date": add_days(ngay, 30),
		"disable_rounded_total": 1, "ignore_pricing_rule": 1})
	si.append("items", {"item_name": "Opening Invoice Item", "qty": 1, "rate": tien, "income_account": tk_tam, "uom": "Nos"})
	try:
		si.insert(set_name=ma); si.submit(); frappe.db.commit()
		return _out({"ten": si.name, "outstanding": si.outstanding_amount, "is_opening": si.is_opening})
	except Exception as e:
		frappe.db.rollback(); return _out({"LOI": str(e)[:400]})


def ton_lo(item="SP016", kho=KHO_BAN):
	"""Chẩn đoán: get_batch_qty so với cộng SLE theo lô."""
	gb = get_batch_qty(item_code=item, warehouse=kho)
	sle = frappe.db.sql("""select batch_no, sum(actual_qty) qty from `tabStock Ledger Entry`
		where item_code=%s and warehouse=%s and is_cancelled=0 group by batch_no""", (item, kho), as_dict=True)
	sbe = frappe.db.sql("""select sbe.batch_no, sum(sbe.qty) qty from `tabSerial and Batch Entry` sbe
		join `tabSerial and Batch Bundle` b on b.name=sbe.parent
		where b.item_code=%s and sbe.warehouse=%s and b.docstatus=1 and b.is_cancelled=0 group by sbe.batch_no""", (item, kho), as_dict=True)
	return _out({"get_batch_qty": gb, "sle": sle, "bundle_entries": sbe,
		"si_moi": frappe.get_all("Sales Invoice", filters={"docstatus": 1, "update_stock": 1}, fields=["name"], order_by="creation desc", limit=3)})


def va_thue_mua():
	"""Item Tax Template cần chứa cả tài khoản thuế ĐẦU VÀO để dòng thuế của phiếu mua khớp (bài học PoC)."""
	tk_vao = frappe.db.get_value("Account", {"company": CTY, "account_name": "Thue GTGT dau vao"})
	for r in (0, 5, 8, 10):
		t = frappe.get_doc("Item Tax Template", ITEM_TPL(r))
		if not any(x.tax_type == tk_vao for x in t.taxes):
			t.append("taxes", {"tax_type": tk_vao, "tax_rate": r}); t.save()
	frappe.db.commit()
	return _out({"ok": True})


def gia_von_lo(lo, kho=None):
	"""Giá vốn của lô theo sổ: SLE có bundle thì batch_no nằm ở Serial and Batch Entry."""
	cond = "and sbe.warehouse=%(kho)s" if kho else ""
	r = frappe.db.sql(f"""select sbe.incoming_rate, sbe.qty from `tabSerial and Batch Entry` sbe join `tabSerial and Batch Bundle` b on b.name=sbe.parent
		where sbe.batch_no=%(lo)s and b.docstatus=1 and b.is_cancelled=0 and sbe.qty>0 {cond} order by b.creation asc limit 1""", {"lo": lo, "kho": kho}, as_dict=True)
	return flt(r[0].incoming_rate) if r else 0.0


def ghi_co_doc_lap2(kho=KHO_DATE, dat_incoming_rate=True, ban_het=False):
	it = _items(True)[0]
	lo = get_batch_qty(item_code=it, warehouse=KHO_BAN)[0]["batch_no"]
	gia_von_goc = gia_von_lo(lo)
	try:
		if ban_het:
			con = flt((get_batch_qty(batch_no=lo, warehouse=KHO_BAN) or 0))
			if con > 0:
				si0 = frappe.new_doc("Sales Invoice")
				si0.update({"customer": _khach(2), "company": CTY, "update_stock": 1, "set_warehouse": KHO_BAN, "taxes_and_charges": VAT_TPL, "ignore_pricing_rule": 1})
				si0.append("items", {"item_code": it, "qty": con, "uom": "Lon", "conversion_factor": 1, "rate": _gia(it), "warehouse": KHO_BAN, "use_serial_batch_fields": 1, "batch_no": lo, "item_tax_template": ITEM_TPL(0)})
				_set_taxes(si0, "Sales Taxes and Charges Template", VAT_TPL); si0.insert(); si0.submit()
		cn = frappe.new_doc("Sales Invoice")
		cn.update({"customer": _khach(2), "company": CTY, "is_return": 1, "update_stock": 1, "set_warehouse": kho, "taxes_and_charges": VAT_TPL, "ignore_pricing_rule": 1})
		row = {"item_code": it, "qty": -5, "uom": "Lon", "conversion_factor": 1, "rate": _gia(it) * 1.1, "warehouse": kho, "use_serial_batch_fields": 1, "batch_no": lo, "item_tax_template": ITEM_TPL(0)}
		if dat_incoming_rate: row["incoming_rate"] = gia_von_goc
		cn.append("items", row)
		_set_taxes(cn, "Sales Taxes and Charges Template", VAT_TPL)
		cn.insert(); cn.submit()
		sle = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": cn.name, "is_cancelled": 0}, fields=["warehouse", "actual_qty", "incoming_rate", "valuation_rate", "stock_value_difference"])
		sbe = frappe.db.sql("""select sbe.batch_no, sbe.qty, sbe.incoming_rate from `tabSerial and Batch Entry` sbe join `tabSerial and Batch Bundle` b on b.name=sbe.parent where b.voucher_no=%s""", cn.name, as_dict=True)
		frappe.db.commit()
		return _out({"cn": cn.name, "outstanding": cn.outstanding_amount, "lo": lo, "gia_von_goc": gia_von_goc, "gia_ban_dong": row["rate"], "dat_incoming_rate": dat_incoming_rate, "ban_het": ban_het, "sle": sle, "sbe": sbe})
	except Exception as e:
		frappe.db.rollback(); return _out({"LOI": type(e).__name__ + ": " + str(e)[:300], "ban_het": ban_het, "dat_incoming_rate": dat_incoming_rate})


def nhap_lai_lo_het_han2():
	it = [i for i in _items(True) if frappe.db.get_value("Item", i, "has_expiry_date")][0]
	lo = f"{it}-HETHAN"
	if not frappe.db.exists("Batch", lo):
		frappe.get_doc({"doctype": "Batch", "batch_id": lo, "item": it, "manufacturing_date": add_days(nowdate(), -400), "expiry_date": add_days(nowdate(), -10)}).insert()
		frappe.db.commit()
	kq = {}
	try:
		from erpnext.stock.serial_batch_bundle import SerialBatchCreation
		se2 = frappe.new_doc("Stock Entry"); se2.update({"stock_entry_type": "Material Receipt", "company": CTY, "to_warehouse": KHO_DATE})
		se2.append("items", {"item_code": it, "qty": 5, "uom": "Lon", "conversion_factor": 1, "t_warehouse": KHO_DATE, "basic_rate": 10_000})
		sbc = SerialBatchCreation({"item_code": it, "warehouse": KHO_DATE, "posting_date": nowdate(), "voucher_type": "Stock Entry",
			"qty": 5, "type_of_transaction": "Inward", "company": CTY, "batches": frappe._dict({lo: 5}), "do_not_submit": True})
		bundle = sbc.make_serial_and_batch_bundle()
		se2.items[0].serial_and_batch_bundle = bundle.name; se2.items[0].use_serial_batch_fields = 0
		se2.insert(); se2.submit()
		kq["bundle_inward"] = {"ok": se2.name, "bundle": bundle.name}; frappe.db.commit()
	except Exception as e:
		frappe.db.rollback(); kq["bundle_inward"] = {"LOI": type(e).__name__ + ": " + str(e)[:300]}
	# cách 3: credit note có kho (tờ trả) với lô hết hạn
	try:
		cn = frappe.new_doc("Sales Invoice")
		cn.update({"customer": _khach(6), "company": CTY, "is_return": 1, "update_stock": 1, "set_warehouse": KHO_DATE, "taxes_and_charges": VAT_TPL, "ignore_pricing_rule": 1})
		cn.append("items", {"item_code": it, "qty": -2, "uom": "Lon", "conversion_factor": 1, "rate": _gia(it), "warehouse": KHO_DATE, "use_serial_batch_fields": 1, "batch_no": lo, "incoming_rate": 9_000, "item_tax_template": ITEM_TPL(0)})
		_set_taxes(cn, "Sales Taxes and Charges Template", VAT_TPL); cn.insert(); cn.submit()
		kq["credit_note_co_kho"] = {"ok": cn.name}; frappe.db.commit()
	except Exception as e:
		frappe.db.rollback(); kq["credit_note_co_kho"] = {"LOI": type(e).__name__ + ": " + str(e)[:300]}
	return _out(kq)


def lcv_kiem_lai(pi_name="ACC-PINV-2026-00001"):
	from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost_entries
	# Đếm ĐỦ (bản 05/11 in `limit=5` nên báo cáo ghi nhầm 5 việc — sổ có 30)
	riv = frappe.get_all("Repost Item Valuation", fields=["status", "count(name) as n"], group_by="status")
	t0 = time.perf_counter(); repost_entries(); ms = _ms(t0)
	riv2 = frappe.get_all("Repost Item Valuation", fields=["status", "count(name) as n"], group_by="status")
	lo = f"{_items(True)[0]}-L1"
	sle = frappe.db.sql("""select sle.voucher_type, sle.voucher_no, sle.actual_qty, sle.incoming_rate, sle.valuation_rate, sle.stock_value_difference from `tabStock Ledger Entry` sle
		join `tabSerial and Batch Bundle` b on b.name=sle.serial_and_batch_bundle join `tabSerial and Batch Entry` e on e.parent=b.name
		where e.batch_no=%s and sle.is_cancelled=0 order by sle.posting_datetime asc limit 6""", lo, as_dict=True)
	frappe.db.commit()
	return _out({"riv_truoc": riv, "repost_ms": ms, "riv_sau": riv2, "lo": lo, "sle_cua_lo": sle})


# ─────────────────────── (1b) đồng thời: nhiều tiến trình cùng Xuất hàng một lúc ───────────────────────

def xuat_hang_dong_thoi(cho_den=0, khach=1, so_dong=15, tag="", khoa=False, lam_nong=True):
	"""Chờ tới mốc epoch `cho_den` (để các tiến trình song song bắt đầu cùng lúc) rồi Xuất hàng một lượt.
	lam_nong: chạy một lượt trước mốc để tiến trình đã nạp mã / cache như gunicorn worker nóng (không tính)."""
	cho_den = float(cho_den or 0)
	nong = None
	if lam_nong:
		n0 = xuat_hang_mot(so_dong=int(so_dong), khach=int(khach), in_kq=False, khoa=khoa)
		nong = n0.get("tong") or n0.get("LOI")
	while time.time() < cho_den:
		time.sleep(0.01)
	bd = time.time()
	kq = xuat_hang_mot(so_dong=int(so_dong), khach=int(khach), in_kq=False, dong_thoi_tag=tag, khoa=khoa)
	kq["nong"] = nong; kq["khoa"] = khoa
	# (bản 05/11 ghi giờ KẾT THÚC vào khoá "bat_dau")
	kq["bat_dau"] = round(bd, 3); kq["ket_thuc"] = round(time.time(), 3)
	kq.pop("dong", None); kq.pop("dong_sau_insert", None)
	return _out(kq)


# ─────────────────────── (1c) dòng cần HAI lô thật — bundle so với tách dòng (đo lại 06/11/2026) ───────────────────────

def _lo_con(item, kho=KHO_BAN):
	return [b for b in (get_batch_qty(item_code=item, warehouse=kho) or []) if flt(b.get("qty")) > 0]


def _chuan_bi_lo_le(item, con_lai=20, kho=KHO_BAN):
	"""Bán bớt lô FIFO đầu của `item` (tờ bán riêng, đã commit, không tính giờ) cho tới khi lô ấy còn `con_lai` lon."""
	lo = _lo_con(item, kho)
	if not lo:
		return None
	dau = lo[0]; ban = flt(dau["qty"]) - con_lai
	if ban > 0:
		si0 = frappe.new_doc("Sales Invoice")
		si0.update({"customer": _khach(9), "company": CTY, "update_stock": 1, "set_warehouse": kho, "taxes_and_charges": VAT_TPL, "ignore_pricing_rule": 1})
		si0.append("items", {"item_code": item, "qty": ban, "uom": "Lon", "conversion_factor": 1, "rate": _gia(item), "warehouse": kho,
			"use_serial_batch_fields": 1, "batch_no": dau["batch_no"], "item_tax_template": ITEM_TPL(0)})
		_set_taxes(si0, "Sales Taxes and Charges Template", VAT_TPL); si0.insert(); si0.submit(); frappe.db.commit()
	return dau["batch_no"]


def hai_lo_do(lan=5):
	"""Dòng 2 thùng (48 lon) khi lô FIFO đầu chỉ còn ≤ 20 lon → phải lấy từ hai lô. `lan` lượt mỗi cách, xen kẽ, mỗi lượt
	một mặt hàng riêng đã bán bớt trước. Kiểm sổ số lô thật sự trên tờ (bundle) và số dòng (tách dòng)."""
	ket = {"bundle": [], "tach_dong": []}
	hang = _items(True); k = 0
	for _ in range(int(lan)):
		for cach in ("bundle", "tach_dong"):
			it = None
			while k < len(hang):
				x = hang[k]; k += 1
				lo = _lo_con(x)
				if len(lo) >= 2 and sum(flt(b["qty"]) for b in lo[1:]) >= 48:
					it = x; break
			if not it:
				ket["LOI"] = "hết mặt hàng đủ hai lô"; return _out(ket)
			_chuan_bi_lo_le(it, 20)
			r = xuat_hang_mot(so_dong=1, khach=5, in_kq=False, cach=cach, dong_co_dinh=[(it, "Thung", 2)])
			if "LOI" in r:
				ket[cach].append({"item": it, "LOI": r["LOI"]}); continue
			lo_sbe = frappe.db.sql("""select e.batch_no, e.qty from `tabSerial and Batch Entry` e join `tabSerial and Batch Bundle` b on b.name=e.parent
				where b.voucher_no=%s and b.is_cancelled=0 order by e.idx""", r["si"], as_dict=True)
			dong = frappe.db.sql("""select qty, uom, stock_qty, batch_no from `tabSales Invoice Item` where parent=%s order by idx""", r["si"], as_dict=True)
			ket[cach].append({"item": it, "si": r["si"], "tong": r["tong"], "si_insert": r["si_insert"], "si_submit": r["si_submit"],
				"lo": [[x.batch_no, flt(x.qty)] for x in lo_sbe], "dong": [[flt(x.qty), x.uom, flt(x.stock_qty), x.batch_no] for x in dong]})
	for c in ("bundle", "tach_dong"):
		ok = [x["tong"] for x in ket[c] if "tong" in x]
		ket[c + "_tb_ms"] = round(sum(ok) / len(ok)) if ok else None
		ket[c + "_min_max"] = [min(ok), max(ok)] if ok else None
	return _out(ket)


# ─────────────────────── (1d) đồng thời, chỉ đo phần XUẤT HĐ của đơn đã chốt (đo lại 06/11/2026) ───────────────────────

def _nhom_hang(k, chung=False):
	"""Nhóm k (1..5): 6 mặt hàng theo lô + 2 không lô, năm nhóm RỜI nhau; chung=True: mọi tiến trình dùng nhóm 1."""
	lo = _items(True); kl = _items(False)
	k = 1 if chung else int(k)
	return lo[6 * (k - 1): 6 * k] + kl[2 * (k - 1): 2 * k]


def _tao_don(items, khach):
	so = frappe.new_doc("Sales Order")
	so.update({"customer": _khach(khach), "company": CTY, "transaction_date": nowdate(), "delivery_date": nowdate(),
		"set_warehouse": KHO_BAN, "taxes_and_charges": VAT_TPL, "ignore_pricing_rule": 1})
	for it in items:
		so.append("items", {"item_code": it, "qty": 2, "uom": "Lon", "conversion_factor": 1, "rate": _gia(it), "price_list_rate": _gia(it),
			"item_tax_template": ITEM_TPL(8), "warehouse": KHO_BAN})
	_set_taxes(so, "Sales Taxes and Charges Template", VAT_TPL)
	so.insert(); so.submit(); frappe.db.commit()
	return so.name


def _xuat_hd(so_name, hang_lo, khoa=False):
	"""Phần Xuất hàng của một đơn đã chốt: commit → (khoá Bin, câu ĐẦU của giao dịch) → SI từ SO → app gán lô → insert → submit → commit.
	hang_lo do nơi gọi truyền vào để không phải đọc sổ trước khi khoá (câu đọc thường đầu tiên lập ảnh chụp REPEATABLE READ)."""
	from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
	t = {}
	frappe.db.commit()
	t0 = time.perf_counter()
	if khoa:
		_khoa_bin(sorted(hang_lo)); t["khoa_ms"] = _ms(t0)
	si = make_sales_invoice(so_name)
	si.update({"update_stock": 1, "set_warehouse": KHO_BAN, "posting_date": nowdate(), "set_posting_time": 1, "taxes_and_charges": VAT_TPL, "ignore_pricing_rule": 1})
	gan_lo_cho_tung_dong(si, "bundle")
	_set_taxes(si, "Sales Taxes and Charges Template", VAT_TPL)
	try:
		t1 = time.perf_counter(); si.insert(); t["si_insert"] = _ms(t1)
		t2 = time.perf_counter(); si.submit(); t["si_submit"] = _ms(t2)
		frappe.db.commit()
	except Exception as e:
		frappe.db.rollback()
		t["LOI"] = type(e).__name__ + ": " + str(e)[:160]
		return t
	t["tong"] = _ms(t0); t["si"] = si.name
	return t


def xuat_hd_dong_thoi(cho_den=0, k=1, chung=False, khoa=False, tag=""):
	"""Một tiến trình của bài đồng thời: làm nóng (đơn + xuất, không tính) → chốt đơn cho lượt đo TRƯỚC mốc → chờ mốc →
	đo riêng phần Xuất HĐ. Ghi giờ bắt đầu (sau mốc) và giờ kết thúc để thấy nối đuôi hay song song."""
	hang = _nhom_hang(k, chung)
	hang_lo = [i for i in hang if frappe.db.get_value("Item", i, "has_batch_no")]
	n0 = _xuat_hd(_tao_don(hang, int(k)), hang_lo, khoa)
	so1 = _tao_don(hang, int(k))
	while time.time() < float(cho_den):
		time.sleep(0.005)
	bd = time.time()
	kq = _xuat_hd(so1, hang_lo, khoa)
	kq.update({"bat_dau": round(bd, 3), "ket_thuc": round(time.time(), 3), "nong": n0.get("tong") or n0.get("LOI"),
		"k": int(k), "chung": bool(chung), "khoa": bool(khoa), "tag": tag, "so": so1, "hang": hang})
	return _out(kq)



# ─────────────────────── (11) CFD-01: Sửa HĐ đã ghi sổ = huỷ + amend → tên "-1", "-2" (đo 06/11/2026) ───────────────────────

def sua_hd_amend(si_name=None, lan=2):
	"""Huỷ HĐ ghi sổ rồi amend (copy_doc + amended_from) `lan` lần liền; ghi tên từng tờ, docstatus tờ cũ, thời gian.
	Dòng tờ mới không mang bundle cũ (huỷ đã xoá serial_and_batch_bundle + batch_no trên dòng tờ cũ — copy_doc vẫn chép trường no_copy) → lõi tự lập bundle lúc ghi sổ (auto_create_serial_and_batch_bundle_for_outward)."""
	if not si_name:
		si_name = frappe.get_all("Sales Invoice", filters={"docstatus": 1, "update_stock": 1, "is_return": 0, "company": CTY,
			"amended_from": ["is", "not set"]}, order_by="creation desc", pluck="name")[0]
	ket = {"goc": si_name, "lan": []}
	ten = si_name
	for _ in range(int(lan)):
		t0 = time.perf_counter()
		cu = frappe.get_doc("Sales Invoice", ten)
		try:
			cu.cancel()
			moi = frappe.copy_doc(cu)
			moi.amended_from = cu.name
			moi.insert(); moi.submit()
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			ket["lan"].append({"tu": ten, "LOI": type(e).__name__ + ": " + str(e)[:200]}); break
		ket["lan"].append({"tu": ten, "ra": moi.name, "ms": _ms(t0), "cu_docstatus": frappe.db.get_value("Sales Invoice", ten, "docstatus"),
			"bundle_moi": frappe.get_all("Sales Invoice Item", filters={"parent": moi.name, "serial_and_batch_bundle": ["is", "set"]},
				pluck="serial_and_batch_bundle")[:2],
			# lõi gắn gói lô tự lập bằng frappe.db.set_value (erpnext/stock/serial_batch_bundle.py:325) nên `moi.items` trong bộ nhớ
			# không thấy — phải đọc sổ; kèm lô của tờ cũ và tờ mới để biết lõi có chọn khác lô app đã gán hay không
			"lo_cu_moi": frappe.db.sql("""select b.voucher_no, b.item_code, e.batch_no, e.qty from `tabSerial and Batch Bundle` b
				join `tabSerial and Batch Entry` e on e.parent = b.name where b.voucher_no in (%s, %s)
				order by b.item_code, b.voucher_no""", (ten, moi.name), as_dict=True)})
		ten = moi.name
	return _out(ket)


def doi_ma_lo_ep(force=True):
	"""Bản 06/11: `rename_doc` chỉ chặn khi KHÔNG force / ignore_permissions (frappe/model/rename_doc.py:385).
	Thử ép đổi tên một lô đã có sổ rồi ROLLBACK (không để lại gì): đếm chỗ còn trỏ mã cũ / mã mới."""
	it = _items(True)[2]
	lo = _lo_con(it)[0]["batch_no"]
	moi = lo + "-DOI"
	def dem(ma):
		return {"sbe": frappe.db.count("Serial and Batch Entry", {"batch_no": ma}),
			"sii": frappe.db.count("Sales Invoice Item", {"batch_no": ma}),
			"pii": frappe.db.count("Purchase Invoice Item", {"batch_no": ma}),
			"batch": frappe.db.count("Batch", {"name": ma})}
	truoc = dem(lo)
	try:
		t0 = time.perf_counter()
		ra = frappe.rename_doc("Batch", lo, moi, force=bool(force))
		ms = _ms(t0)
		kq = {"doi_duoc": True, "lo": lo, "ra": ra, "ms": ms, "truoc_ma_cu": truoc, "sau_ma_cu": dem(lo), "sau_ma_moi": dem(moi),
			"batch_id_moi": frappe.db.get_value("Batch", moi, "batch_id")}
	except Exception as e:
		kq = {"doi_duoc": False, "lo": lo, "LOI": type(e).__name__ + ": " + str(e)[:300]}
	frappe.db.rollback()
	kq["sau_rollback_con_ma_cu"] = frappe.db.exists("Batch", lo) is not None
	return _out(kq)


def doi_ma_lo_ep_do_sot(force=True):
	"""Ép đổi tên lô rồi dò MỌI cột chữ của mọi bảng xem còn chỗ nào giữ mã cũ (khớp đúng, hoặc nằm trong chuỗi JSON / văn bản);
	ROLLBACK cuối hàm."""
	it = _items(True)[2]
	lo = _lo_con(it)[0]["batch_no"]
	moi = lo + "-DOI"
	frappe.rename_doc("Batch", lo, moi, force=bool(force))
	cot = frappe.db.sql("""select table_name, column_name, data_type from information_schema.columns
		where table_schema = database() and data_type in ('varchar','text','mediumtext','longtext','json')""", as_dict=True)
	con = []
	for c in cot:
		t, k = c.table_name, c.column_name
		n_dung = frappe.db.sql(f"select count(*) from `{t}` where `{k}` = %s", lo)[0][0]
		n_trong = frappe.db.sql(f"select count(*) from `{t}` where `{k}` like %s and `{k}` <> %s and `{k}` not like %s",
			(f"%{lo}%", lo, f"%{moi}%"))[0][0]
		if n_dung or n_trong:
			mau = frappe.db.sql(f"select left(`{k}`, 160) from `{t}` where `{k}` like %s and `{k}` not like %s limit 2", (f"%{lo}%", f"%{moi}%"))
			con.append({"bang": t, "cot": k, "khop_dung": n_dung, "nam_trong_chuoi": n_trong, "mau": [m[0] for m in mau]})
	frappe.db.rollback()
	return _out({"lo": lo, "so_cot_da_do": len(cot), "con_giu_ma_cu": con})


# ─────────────────────── (2b) dòng 0 đ và dòng bán trên giá bảng — lõi làm gì với rate app gửi (đo 10/11/2026) ───────────────────────

def dong_dac_biet():
	"""Một HĐ (không trừ kho), mỗi dòng một ca; insert rồi đọc lại rate / discount / margin lõi để lại; ROLLBACK cuối hàm.
	  a1  hàng đổi 0 đ: rate 0 + price_list_rate          a2  rate 0 + price_list_rate + discount_percentage 100
	  a3  rate 0, không price_list_rate                    b   bán TRÊN giá bảng: rate = giá bảng + 1.000
	  c   bán dưới giá bảng, rate app tự tính (lệch luật % của lõi)
	  a4  rate 0 + price_list_rate 0 gửi tường minh          a5  rate 0 + price_list_rate + discount_amount = giá bảng"""
	it = _items(True)[0]
	plr = _gia(it)
	ca = [
		("a1", {"rate": 0, "price_list_rate": plr}),
		("a2", {"rate": 0, "price_list_rate": plr, "discount_percentage": 100}),
		("a3", {"rate": 0}),
		("b", {"rate": plr + 1000, "price_list_rate": plr}),
		("c", {"rate": plr - 777, "price_list_rate": plr, "discount_percentage": 5}),
		("a4", {"rate": 0, "price_list_rate": 0}),
		("a5", {"rate": 0, "price_list_rate": plr, "discount_amount": plr}),
	]
	si = frappe.new_doc("Sales Invoice")
	si.update({"customer": _khach(3), "company": CTY, "update_stock": 0, "taxes_and_charges": VAT_TPL, "ignore_pricing_rule": 1})
	for _, row in ca:
		si.append("items", {"item_code": it, "qty": 2, "uom": "Lon", "conversion_factor": 1, "item_tax_template": ITEM_TPL(8), **row})
	_set_taxes(si, "Sales Taxes and Charges Template", VAT_TPL)
	kq = {"item": it, "gia_bang": plr}
	try:
		si.insert()
		for (ten, gui), d in zip(ca, si.items):
			kq[ten] = {"gui": gui, "rate": flt(d.rate), "price_list_rate": flt(d.price_list_rate), "discount_percentage": flt(d.discount_percentage),
				"discount_amount": flt(d.discount_amount), "margin_type": d.margin_type or "", "margin_rate_or_amount": flt(d.margin_rate_or_amount),
				"amount": flt(d.amount)}
	except Exception as e:
		kq["LOI"] = type(e).__name__ + ": " + str(e)[:300]
	frappe.db.rollback()
	return _out(kq)

