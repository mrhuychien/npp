"""Bảng SẢN PHẨM của nppsale trên cổng: products (Item + mã vạch + NCC chính), product_units (Item.uoms trừ đơn vị cơ sở),
price_lists (Item Price của Gia chuan / Gia nhom *), purchase_price_lists (Item Price của Gia nhap) — blueprint 02 phần Bán hàng §3.1, §4.

products (mig 081 "View products (sales scoped by supplier)"): vai khác sales thấy hết; sales thấy hàng chưa gán NCC chính hoặc NCC chính
thuộc công ty được làm của mình. Ghi: owner / manager (form, nhập Excel, bật / tắt bán).
"""
from __future__ import annotations

import frappe

from ..dang_ky import Bang, CotDef, NguCanh, QuanHe, dang_ky
from ..sql import LoiCong
from ._chung import CHI_DOC, GhiDocType, bool_vao, c, la_nv, org, tu_choi

VAI_SUA_HANG = ("owner", "manager")
_NHOM_MAC_DINH = "('All Item Groups', 'Tất cả nhóm hàng', 'Products', 'Sản phẩm')"


def _cong_ty() -> str:
	return frappe.db.get_single_value("NPP Cai Dat", "cong_ty") or frappe.defaults.get_global_default("company") or ""


def ve_san_pham(nc: NguCanh, cot_sp: str = "{t}.`name`"):
	"""Vế "mặt hàng người gọi thấy được" trên một cột chứa mã hàng (dùng cho products và bảng con / giá)."""
	if not la_nv(nc) and not nc.bo_qua_rls:
		return False
	if nc.bo_qua_rls or nc.vai != "sales":
		return None
	return (
		f"NOT EXISTS (SELECT 1 FROM `tabItem Default` d WHERE d.`parent` = {cot_sp} AND d.`parenttype` = 'Item' "
		"AND IFNULL(d.`default_supplier`, '') != '' AND d.`default_supplier` NOT IN "
		"(SELECT ct.`nha_cung_cap` FROM `tabNPP Nhan Vien Cong Ty` ct WHERE ct.`parent` = %(u)s))",
		{"u": nc.user},
	)


def _dam_bao_uom(ten: str):
	if ten and not frappe.db.exists("UOM", ten):
		frappe.get_doc({"doctype": "UOM", "uom_name": ten, "must_be_whole_number": 0}).insert(ignore_permissions=True)


_ANH_XA_SP = {
	"sku": "item_code", "name": "item_name", "brand": "brand", "description": "description", "warranty_info": "warranty_period",
	"cost_price": "valuation_rate", "sell_price": "npp_gia_ban", "track_serial": ("npp_theo_doi_serial", bool_vao), "min_stock": "safety_stock",
	"max_stock": ("npp_ton_toi_da", lambda v: v or 0), "shelf_location": "npp_vi_tri_ke", "weight": ("weight_per_unit", lambda v: v or 0),
	"weight_unit": "weight_uom", "direct_sale": ("npp_ban_truc_tiep", bool_vao), "vat_rate": ("npp_thue_suat", lambda v: v or 0),
	"shelf_life_days": ("shelf_life_in_days", lambda v: v or 0), "base_unit": "stock_uom",
	"status": ("npp_ngung_ban", lambda v: 1 if v == "inactive" else 0),
}
_BO_QUA = set(CHI_DOC) | {"allow_price_edit", "price_edit_max_type", "price_edit_max", "category"}


class GhiSanPham:
	"""Thêm / sửa / xoá Item theo cột nppsale. Mã vạch = dòng đầu Item Barcode; NCC chính = Item Default của công ty; ảnh = `image`."""

	def _gan(self, doc, g: dict):
		for k, v in g.items():
			if k in _BO_QUA or k in ("barcode", "primary_supplier_id", "images", "units", "price_lists"):
				continue
			m = _ANH_XA_SP.get(k)
			if m is None:
				raise LoiCong("PGRST204", f"Could not find the '{k}' column of 'products' in the schema cache", http=400)
			f, ham = (m, None) if isinstance(m, str) else m
			if f == "stock_uom":
				_dam_bao_uom(v)
				if not doc.is_new() and doc.stock_uom != v and frappe.db.exists("Stock Ledger Entry", {"item_code": doc.name}):
					raise LoiCong("P0001", "Không đổi được đơn vị cơ sở của mặt hàng đã có giao dịch kho.")
			if f == "weight_uom":
				_dam_bao_uom(v)
			if f == "brand" and v and not frappe.db.exists("Brand", v):
				frappe.get_doc({"doctype": "Brand", "brand": v}).insert(ignore_permissions=True)
			doc.set(f, ham(v) if ham else v)
		if "barcode" in g:
			ma = (g.get("barcode") or "").strip()
			doc.set("barcodes", [])
			if ma:
				doc.append("barcodes", {"barcode": ma})
		if "primary_supplier_id" in g:
			ct = _cong_ty()
			dong = next((d for d in doc.get("item_defaults") or [] if d.company == ct), None)
			if dong is None and ct:
				dong = doc.append("item_defaults", {"company": ct})
			if dong is not None:
				dong.default_supplier = g.get("primary_supplier_id") or None
		if "images" in g:
			ds = g.get("images") or []
			doc.image = ds[0] if ds else None
		doc.has_expiry_date = 1 if (doc.shelf_life_in_days or 0) > 0 else 0

	def them(self, ds, nc):
		if nc.vai not in VAI_SUA_HANG and not nc.bo_qua_rls:
			tu_choi("products")
		ra = []
		for g in ds:
			if not g.get("sku"):
				raise LoiCong("23502", 'null value in column "sku" of relation "products" violates not-null constraint')
			if frappe.db.exists("Item", g["sku"]):
				raise LoiCong("23505", 'duplicate key value violates unique constraint "products_org_id_sku_key"', http=409)
			doc = frappe.new_doc("Item")
			doc.item_group = frappe.db.get_single_value("Stock Settings", "item_group") or frappe.db.get_value("Item Group", {"is_group": 0}, "name")
			doc.is_stock_item = 1
			doc.has_batch_no = 1 if g.get("has_batch_no", True) else 0
			doc.create_new_batch = 0
			self._gan(doc, {k: v for k, v in g.items() if k != "has_batch_no"})
			if not doc.stock_uom:
				raise LoiCong("23502", 'null value in column "base_unit" of relation "products" violates not-null constraint')
			doc.insert(ignore_permissions=True)
			ra.append(doc.name)
		return ra

	def sua(self, gia_tri, ids, nc):
		if nc.vai not in VAI_SUA_HANG and not nc.bo_qua_rls:
			return []
		if "sku" in gia_tri:
			raise LoiCong("P0001", "SKU không đổi được (mã mặt hàng là khoá chứng từ).")
		ra = []
		for ten in ids:
			doc = frappe.get_doc("Item", ten)
			self._gan(doc, gia_tri)
			doc.save(ignore_permissions=True)
			ra.append(ten)
		return ra

	def xoa(self, ids, nc):
		if nc.vai not in VAI_SUA_HANG and not nc.bo_qua_rls:
			return []
		for ten in ids:
			try:
				frappe.delete_doc("Item", ten, ignore_permissions=True)
			except frappe.LinkExistsError as e:
				raise LoiCong("23503", f'update or delete on table "products" violates foreign key constraint — mặt hàng {ten} đã có chứng từ',
					http=409) from e
		return list(ids)


dang_ky(Bang(
	ten="products",
	nguon="`tabItem`",
	cot={
		"id": c("{t}.`name`"), "org_id": org(), "sku": c("item_code"), "name": c("item_name"),
		"category": c(f"CASE WHEN {{t}}.`item_group` IN {_NHOM_MAC_DINH} THEN NULL ELSE {{t}}.`item_group` END"),
		"brand": c("brand"),
		"barcode": c("(SELECT b.`barcode` FROM `tabItem Barcode` b WHERE b.`parent` = {t}.`name` AND b.`parenttype` = 'Item' ORDER BY b.`idx` LIMIT 1)"),
		"base_unit": c("stock_uom"), "vat_rate": c("npp_thue_suat", "so"), "shelf_life_days": c("NULLIF({t}.`shelf_life_in_days`, 0)", "so"),
		"status": c("CASE WHEN {t}.`npp_ngung_ban` = 1 THEN 'inactive' ELSE 'active' END"), "created_at": c("creation", "gio"),
		"description": c("description"), "warranty_info": c("warranty_period"), "cost_price": c("valuation_rate", "tien"),
		"sell_price": c("npp_gia_ban", "tien"), "track_serial": c("npp_theo_doi_serial", "bool"), "min_stock": c("safety_stock", "so"),
		"max_stock": c("NULLIF({t}.`npp_ton_toi_da`, 0)", "so"), "shelf_location": c("npp_vi_tri_ke"),
		"weight": c("NULLIF({t}.`weight_per_unit`, 0)", "so"), "weight_unit": c("weight_uom"), "direct_sale": c("npp_ban_truc_tiep", "bool"),
		"images": c("CASE WHEN IFNULL({t}.`image`, '') = '' THEN JSON_ARRAY() ELSE JSON_ARRAY({t}.`image`) END", "json"),
		"primary_supplier_id": c("(SELECT d.`default_supplier` FROM `tabItem Default` d WHERE d.`parent` = {t}.`name` AND d.`parenttype` = 'Item' "
			"AND IFNULL(d.`default_supplier`, '') != '' ORDER BY d.`idx` LIMIT 1)"),
		"allow_price_edit": CotDef("0", "bool"), "price_edit_max_type": CotDef("'percent'"), "price_edit_max": CotDef("0", "so"),
		"has_batch_no": c("has_batch_no", "bool"), "tim_kd": c("npp_tim_kd"), "updated_at": c("modified", "gio"),
	},
	quan_he=[
		QuanHe("product_units", "id", "product_id", True, ("product_units_product_id_fkey",)),
		QuanHe("price_lists", "id", "product_id", True, ("price_lists_product_id_fkey",)),
		QuanHe("suppliers", "primary_supplier_id", "id", False, ("products_primary_supplier_id_fkey",)),
	],
	rls=lambda nc: ve_san_pham(nc),
	ghi=GhiSanPham(),
))

# ----------------------------------------------------------------------------------------------------------------------------
# product_units — Item.uoms trừ dòng đơn vị cơ sở (lõi tự thêm, hệ số 1)
# ----------------------------------------------------------------------------------------------------------------------------


class GhiDonVi:
	def them(self, ds, nc):
		if nc.vai not in VAI_SUA_HANG and not nc.bo_qua_rls:
			tu_choi("product_units")
		ra = []
		for g in ds:
			doc = frappe.get_doc("Item", g.get("product_id"))
			uom = (g.get("unit_name") or "").strip()
			if not uom or uom == doc.stock_uom:
				raise LoiCong("23514", "Đơn vị quy đổi phải khác đơn vị cơ sở.")
			if any(d.uom == uom for d in doc.uoms):
				raise LoiCong("23505", 'duplicate key value violates unique constraint "product_units_product_id_unit_name_key"', http=409)
			_dam_bao_uom(uom)
			d = doc.append("uoms", {"uom": uom, "conversion_factor": g.get("conversion") or 1})
			doc.save(ignore_permissions=True)
			ra.append(d.name)
		return ra

	def sua(self, gia_tri, ids, nc):
		if nc.vai not in VAI_SUA_HANG and not nc.bo_qua_rls:
			return []
		ra = []
		for ten in ids:
			cha = frappe.db.get_value("UOM Conversion Detail", ten, "parent")
			doc = frappe.get_doc("Item", cha)
			d = next(x for x in doc.uoms if x.name == ten)
			if "unit_name" in gia_tri:
				_dam_bao_uom(gia_tri["unit_name"])
				d.uom = gia_tri["unit_name"]
			if "conversion" in gia_tri:
				d.conversion_factor = gia_tri["conversion"]
			doc.save(ignore_permissions=True)
			ra.append(ten)
		return ra

	def xoa(self, ids, nc):
		if nc.vai not in VAI_SUA_HANG and not nc.bo_qua_rls:
			return []
		cha = {}
		for ten, p in frappe.db.sql("SELECT name, parent FROM `tabUOM Conversion Detail` WHERE name IN %(i)s", {"i": tuple(ids)}):
			cha.setdefault(p, set()).add(ten)
		for p, bo in cha.items():
			doc = frappe.get_doc("Item", p)
			doc.set("uoms", [d for d in doc.uoms if d.name not in bo])
			doc.save(ignore_permissions=True)
		return list(ids)


dang_ky(Bang(
	ten="product_units",
	nguon="(SELECT u.* FROM `tabUOM Conversion Detail` u JOIN `tabItem` i ON i.`name` = u.`parent` "
	"WHERE u.`parenttype` = 'Item' AND u.`uom` != i.`stock_uom`)",
	cot={"id": c("{t}.`name`"), "org_id": org(), "product_id": c("parent"), "unit_name": c("uom"), "conversion": c("conversion_factor", "so"),
		"created_at": c("creation", "gio")},
	quan_he=[QuanHe("products", "product_id", "id", False, ("product_units_product_id_fkey",))],
	rls=lambda nc: ve_san_pham(nc, "{t}.`parent`"),
	ghi=GhiDonVi(),
))

# ----------------------------------------------------------------------------------------------------------------------------
# price_lists — Item Price của bảng giá bán (Gia chuan = nhóm NULL; Gia nhom * = nhóm có default_price_list trỏ tới)
# ----------------------------------------------------------------------------------------------------------------------------
_NHOM_CUA_BANG = "(SELECT cg.`name` FROM `tabCustomer Group` cg WHERE cg.`default_price_list` = {t}.`price_list` LIMIT 1)"


def _bang_cua_nhom(nhom):
	from nppsale.su_kien.san_pham import GIA_CHUAN

	if not nhom:
		return GIA_CHUAN
	bg = frappe.db.get_value("Customer Group", nhom, "default_price_list")
	if not bg:
		raise LoiCong("23503", f"Nhóm khách {nhom} chưa có bảng giá.")
	return bg


class GhiGiaBan(GhiDocType):
	def _gan(self, dich, gia_tri):
		g = dict(gia_tri)
		if "group_id" in g:
			dich["price_list"] = _bang_cua_nhom(g.pop("group_id"))
		if "unit_name" in g:
			_dam_bao_uom(g.get("unit_name"))
		super()._gan(dich, g)


dang_ky(Bang(
	ten="price_lists",
	nguon="(SELECT ip.* FROM `tabItem Price` ip JOIN `tabPrice List` pl ON pl.`name` = ip.`price_list` "
	"WHERE pl.`selling` = 1 AND ip.`price_list` != 'Gia nhap')",
	cot={"id": c("{t}.`name`"), "org_id": org(), "product_id": c("item_code"),
		"group_id": c("CASE WHEN {t}.`price_list` = 'Gia chuan' THEN NULL ELSE " + _NHOM_CUA_BANG + " END"),
		"unit_name": c("uom"), "price": c("price_list_rate", "tien"), "effective_from": c("valid_from", "ngay"),
		"effective_to": c("valid_upto", "ngay"), "created_at": c("creation", "gio")},
	quan_he=[QuanHe("products", "product_id", "id", False, ("price_lists_product_id_fkey",)),
		QuanHe("customer_groups", "group_id", "id", False, ("price_lists_group_id_fkey",))],
	rls=lambda nc: ve_san_pham(nc, "{t}.`item_code`"),
	ghi=GhiGiaBan("price_lists", "Item Price", {"product_id": "item_code", "unit_name": "uom", "price": "price_list_rate",
		"effective_from": "valid_from", "effective_to": "valid_upto"}, vai_them=VAI_SUA_HANG, vai_sua=VAI_SUA_HANG, vai_xoa=VAI_SUA_HANG),
))

dang_ky(Bang(
	ten="purchase_price_lists",
	nguon="(SELECT * FROM `tabItem Price` WHERE `price_list` = 'Gia nhap')",
	cot={"id": c("{t}.`name`"), "org_id": org(), "product_id": c("item_code"), "unit_name": c("uom"), "price": c("price_list_rate", "tien"),
		"effective_date": c("valid_from", "ngay"), "source_invoice_id": c("reference"), "updated_by": c("modified_by"),
		"updated_at": c("modified", "gio")},
	quan_he=[QuanHe("products", "product_id", "id", False, ("purchase_price_lists_product_id_fkey",))],
	rls=lambda nc: None if nc.vai in ("owner", "manager", "accountant", "warehouse") or nc.bo_qua_rls else False,
))
