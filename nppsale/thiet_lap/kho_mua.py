"""Cài đặt site bắt buộc cho P4 — kho + mua hàng + công nợ NCC (đặc tả kho_mua §2.11; blueprint 02 §5.16; PoC) và BỘ KIỂM cài đặt.

- `dam_bao()` (after_install / after_migrate — chạy lại an toàn): đặt đúng các Single lõi ở `CAI_DAT`, Property Setter ở `THUOC_TINH`, trỏ
  `NPP Cai Dat.tk_thue_dau_vao` vào TK thuế GTGT đầu vào của mẫu "VAT n%" (dòng thuế gõ tay của phiếu nhập — BP §4.1); lập TK giảm đầu phiếu nhập
  (`tk_giam_dau_phieu_nhap` — dòng Actual + Deduct của CFD-11; M1, quyết định tạm Q9: "Chiet khau mua hang duoc huong" dưới thu nhập khác 711, chờ
  kế toán chốt 711 hay 632 — BP §7.1 điểm 16) khi NPP Cai Dat còn trống; trỏ TK nợ NCC lập tay (`tk_no_ncc_lap_tay` — M3, quyết định tạm Q9: TK "hàng
  về chưa có hoá đơn" của công ty) khi còn trống; trỏ TK xuất lẻ (`tk_xuat_le` — M4: giá vốn hàng bán của công ty) và TK nhập kho tay không công nợ
  (`tk_nhap_kho_khong_hd` — M4: "hàng về chưa có hoá đơn") khi còn trống (quyết định tạm Q9, chờ kế toán — BP §7.1 điểm 16). Dãy số phiếu nhập / trả NCC /
  nợ NCC / sửa giá (`PN-`, `PTNCC-`, `DKN-`, `NTN-`, `SGN-`) đặt cùng các dãy khác ở `mac_dinh._dat_ten_chung_tu`; phiếu kho tay (`IN-…`, `XKL-`,
  `CKL-`) đặt dãy ngay trên tờ (nppsale.rpc.kho_tay).
- `kiem()` (chỉ đọc): mỗi chỗ lệch một dòng {doi_tuong, truong, dang_co, can, vi_sao} — Single lõi, Property Setter, dãy số, mẫu thuế "VAT n%" thiếu
  TK đầu vào (thiếu là phiếu nhập tính VAT = 0 mà không báo — PoC 05/11), `NPP Cai Dat` thiếu kho / bảng giá nhập / mẫu thuế mua / ngưỡng ngoài 0–365,
  NCC đang `disabled` (lõi chặn MỌI bút toán với NCC bị tắt — `party.py:881–889`; ngừng hợp tác = `npp_ngung_hop_tac`). Rỗng = đủ.
  after_migrate ghi Error Log khi còn lệch (`ghi_nhat_ky_lech`); System Manager gọi `nppsale.thiet_lap.kho_mua.kiem_cai_dat`.
- `cai_dat_kho()`: bộ cài đặt method P4 cần = `cai_dat_ban()` (một lần mỗi request) + ngưỡng kho date, cờ bán vượt tồn, bảng giá nhập, các TK `tk_*`.
"""
from __future__ import annotations

import frappe
from frappe.utils import cint

from nppsale.luat.kho_mua import nguong

# (Single lõi, trường, giá trị cần, vì sao) — đặc tả kho_mua §2.11
CAI_DAT: tuple = (
	("Buying Settings", "allow_multiple_items", 1, "hai dòng cùng mặt hàng = hai lô (mig 142)"),
	("Buying Settings", "supp_master_name", "Naming Series", "NCC đặt tên NCC-.####"),
	("Stock Settings", "auto_insert_price_list_rate_if_missing", 0, "lõi không tự chèn giá từ chứng từ (PoC mục 3 điểm 13)"),
	("Stock Settings", "enable_serial_and_batch_no_for_item", 1, "mặt hàng theo lô"),
	("Stock Settings", "allow_negative_stock", 0, "tồn âm chỉ theo Item.allow_negative_stock + NPP Cai Dat.cho_ban_vuot_ton (câu 14 B)"),
	("Stock Settings", "allow_negative_stock_for_batch", 0, "lô không bao giờ âm (CFD-05 B)"),
	("Stock Settings", "do_not_use_batchwise_valuation", 0, "giá vốn theo lô — Batch mới use_batchwise_valuation = 1 (BP §2.11)"),
	("Stock Settings", "role_allowed_to_create_edit_back_dated_transactions", "",
		"có vai thì người ngoài vai bị chặn ghi lùi (stock_ledger_entry.py:409–439) — tồn đầu kỳ / trả NCC lùi ngày / khôi phục giữ ngày gốc hỏng"),
	("Stock Reposting Settings", "enable_parallel_reposting", 1, "repost nền song song sau ghi lùi / huỷ / LCV (CFD-07)"),
	("Accounts Settings", "add_taxes_from_item_tax_template", 0, "method tự dựng bảng thuế (BP §5.9)"),
	("Accounts Settings", "unlink_payment_on_cancellation_of_invoice", 1,
		"huỷ PN có phiếu chi — lõi gỡ phân bổ (method kiểm DA_TRA_TIEN trước vì lõi gỡ cả tiền Ghi trả)"),
	("Accounts Settings", "check_supplier_invoice_uniqueness", 0, "nppsale cho trùng số HĐ NCC (purchase_invoice.py:1923–1945)"),
	("Document Naming Settings", "default_amend_naming", "Amend Counter", "tờ sửa / khôi phục ra -1, -2 (CFD-01)"),
)

# (DocType, trường, thuộc tính, giá trị, kiểu thuộc tính, vì sao) — blueprint 02 §5.16
THUOC_TINH: tuple = (
	("Purchase Invoice Item", "rate", "precision", "4", "Select", "giảm dòng không chia hết SL vẫn giữ tiền dòng sau làm tròn (BP §7.2 điểm 3)"),
	("Purchase Invoice Item", "net_rate", "precision", "4", "Select", "như rate"),
	("Purchase Invoice Item", "discount_amount", "precision", "4", "Select", "giảm dòng / SL (BP §5.9)"),
	("Purchase Invoice", "bill_no", "allow_on_submit", "1", "Check", "sửa số HĐ NCC ở màn công nợ NCC (payables/[id]/page.tsx:156)"),
)

# Dãy số P4 (đặt ở mac_dinh._dat_ten_chung_tu — kiểm ở đây)
DAY_SO: tuple = (
	("Purchase Invoice", "PN-.####\nPTNCC-.####\nDKN-.####\nNTN-.####", "PN-.####"),
	("Landed Cost Voucher", "SGN-.####", "SGN-.####"),
)


def _gia_tri(dt: str, truong: str):
	return frappe.db.get_single_value(dt, truong, cache=False)


def _bang(x) -> str:
	return "" if x is None else str(x)


def _khop(dang_co, can) -> bool:
	if isinstance(can, int):
		return cint(dang_co) == can
	return _bang(dang_co) == can


def _tk_thue_vao(cd_ban) -> str | None:
	abbr = cd_ban.get("abbr")
	ten = f"Thue GTGT dau vao - {abbr}" if abbr else None
	return ten if ten and frappe.db.exists("Account", ten) else None


def _tk_giam_dau_phieu_nhap(cd_ban) -> str | None:
	"""TK của dòng giảm đầu phiếu nhập (Có — vào thẳng lãi lỗ, không hạ giá trị kho: CFD-11 / PoC 3). Tạm: tài khoản lá "Chiet khau mua hang duoc
	huong" dưới nhóm thu nhập khác (Indirect Income — 711 của TT200), tạo khi chưa có."""
	cong_ty, abbr = cd_ban.get("cong_ty"), cd_ban.get("abbr")
	if not cong_ty or not abbr:
		return None
	ma = f"Chiet khau mua hang duoc huong - {abbr}"
	if frappe.db.exists("Account", ma):
		return ma
	nhom = frappe.db.get_value("Account", {"company": cong_ty, "account_name": "Indirect Income", "is_group": 1}) or frappe.db.get_value(
		"Account", {"company": cong_ty, "root_type": "Income", "is_group": 1}, order_by="lft desc")
	if not nhom:
		return None
	return frappe.get_doc({"doctype": "Account", "account_name": "Chiet khau mua hang duoc huong", "parent_account": nhom, "company": cong_ty,
		"account_type": "", "is_group": 0}).insert(ignore_permissions=True).name


def _tk_no_ncc_lap_tay(cd_ban) -> str | None:
	"""TK dòng của tờ nợ NCC lập tay `NTN-` (M3 — quyết định tạm Q9, chờ kế toán chốt cùng BP §7.1 điểm 16): TK trung gian "hàng về chưa có hoá đơn"
	của công ty (`Company.stock_received_but_not_billed` — 3388 của TT200): nợ lập tay gắn phiếu nhập kho tay `IN-` (Có TK này ở M4) tất toán đúng phần
	kho đã ghi; nợ lập tay không gắn phiếu kho để lại số dư Nợ trên TK này cho kế toán phân loại."""
	cong_ty = cd_ban.get("cong_ty")
	return frappe.get_cached_value("Company", cong_ty, "stock_received_but_not_billed") if cong_ty else None


def _tk_xuat_le(cd_ban) -> str | None:
	"""TK chênh lệch của phiếu xuất lẻ `XKL-` (M4 — quyết định tạm Q9, chờ kế toán chốt cùng BP §7.1 điểm 16 "632 như cách nppsale tính vào giá
	vốn, hay 811 / 641"): giá vốn hàng bán của công ty (`Company.default_expense_account` — 632). Không đặt thì `validate_item` của lõi lặng lẽ điền
	`stock_adjustment_account` (`stock_entry.py:3334–3337`)."""
	cong_ty = cd_ban.get("cong_ty")
	return frappe.get_cached_value("Company", cong_ty, "default_expense_account") if cong_ty else None


def _tk_nhap_kho_khong_hd(cd_ban) -> str | None:
	"""TK chênh lệch của phiếu nhập kho tay `IN-` không công nợ (M4 — quyết định tạm Q9, cùng dòng M3 "TK nợ NCC lập tay"): TK trung gian "hàng về
	chưa có hoá đơn" (`Company.stock_received_but_not_billed` — 3388): phiếu nhập kho ghi Có, nợ NCC lập tay `NTN-` gắn phiếu ấy ghi Nợ — tất toán đúng
	phần kho đã ghi. Tồn đầu kỳ (`DK-`) dùng `tk_tam_dau_ky` (lõi bắt TK tài sản / nợ cho tờ mở đầu)."""
	cong_ty = cd_ban.get("cong_ty")
	return frappe.get_cached_value("Company", cong_ty, "stock_received_but_not_billed") if cong_ty else None


def dam_bao() -> None:
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	for dt, truong, can, _vi_sao in CAI_DAT:
		if not frappe.db.exists("DocType", dt) or not frappe.get_meta(dt).has_field(truong):
			continue
		if not _khop(_gia_tri(dt, truong), can):
			# ghi thẳng Single (không qua controller): Stock Settings.validate của lõi chặn đổi cờ tồn âm / lô khi đã có giao dịch kho — cài đặt
			# đầu của site là việc của app, không phải người dùng
			frappe.db.set_single_value(dt, truong, can)
	if frappe.db.get_single_value("Stock Reposting Settings", "enable_parallel_reposting") and not cint(
			frappe.db.get_single_value("Stock Reposting Settings", "item_based_reposting")):
		frappe.db.set_single_value("Stock Reposting Settings", "item_based_reposting", 1)  # lõi tắt song song khi không repost theo mặt hàng
	for dt, truong, tt, gt, kieu, _vi_sao in THUOC_TINH:
		if not frappe.db.exists("DocType", dt):
			continue
		if frappe.db.get_value("Property Setter", {"doc_type": dt, "field_name": truong, "property": tt}, "value") != gt:
			make_property_setter(dt, truong, tt, gt, kieu, validate_fields_for_doctype=False)
	if frappe.db.exists("DocType", "NPP Cai Dat") and frappe.get_meta("NPP Cai Dat").has_field("tk_thue_dau_vao"):
		from .ban_hang import cai_dat_ban

		frappe.local._npp_cai_dat_ban = None
		tk = _tk_thue_vao(cai_dat_ban())
		if tk and not frappe.db.get_single_value("NPP Cai Dat", "tk_thue_dau_vao", cache=False):
			frappe.db.set_single_value("NPP Cai Dat", "tk_thue_dau_vao", tk)
		if frappe.get_meta("NPP Cai Dat").has_field("tk_giam_dau_phieu_nhap") and not frappe.db.get_single_value("NPP Cai Dat",
				"tk_giam_dau_phieu_nhap", cache=False):
			tk = _tk_giam_dau_phieu_nhap(cai_dat_ban())
			if tk:
				frappe.db.set_single_value("NPP Cai Dat", "tk_giam_dau_phieu_nhap", tk)
		for truong, ham in (("tk_no_ncc_lap_tay", _tk_no_ncc_lap_tay), ("tk_xuat_le", _tk_xuat_le), ("tk_nhap_kho_khong_hd", _tk_nhap_kho_khong_hd)):
			if frappe.get_meta("NPP Cai Dat").has_field(truong) and not frappe.db.get_single_value("NPP Cai Dat", truong, cache=False):
				tk = ham(cai_dat_ban())
				if tk:
					frappe.db.set_single_value("NPP Cai Dat", truong, tk)
		frappe.local._npp_cai_dat_ban = None


def kiem() -> list[dict]:
	"""Bộ kiểm cài đặt P4 (chỉ đọc). Rỗng = site đủ cài đặt cho kho / mua hàng / công nợ NCC."""
	from nppsale.thiet_lap.ban_hang import THUE_SUAT, ten_mau_thue_dong

	ra: list[dict] = []

	def lech(doi_tuong, truong, dang_co, can, vi_sao):
		ra.append({"doi_tuong": doi_tuong, "truong": truong, "dang_co": dang_co, "can": can, "vi_sao": vi_sao})

	for dt, truong, can, vi_sao in CAI_DAT:
		if not frappe.db.exists("DocType", dt) or not frappe.get_meta(dt).has_field(truong):
			lech(dt, truong, "(không có trường)", can, vi_sao)
			continue
		gt = _gia_tri(dt, truong)
		if not _khop(gt, can):
			lech(dt, truong, gt, can, vi_sao)
	for dt, truong, tt, gt, _kieu, vi_sao in THUOC_TINH:
		cu = frappe.db.get_value("Property Setter", {"doc_type": dt, "field_name": truong, "property": tt}, "value")
		if cu != gt:
			lech(f"{dt}.{truong}", tt, cu, gt, vi_sao)
	for dt, chon, mac in DAY_SO:
		for tt, gt in (("options", chon), ("default", mac)):
			cu = frappe.db.get_value("Property Setter", {"doc_type": dt, "field_name": "naming_series", "property": tt}, "value")
			if cu != gt:
				lech(f"{dt}.naming_series", tt, cu, gt, "dãy số P4 (đặc tả kho_mua §2.10, BP §5.16)")
	nhap = frappe.db.get_single_value("NPP Cai Dat", "bang_gia_nhap", cache=False) if frappe.db.exists("DocType", "NPP Cai Dat") else None
	gia = _gia_tri("Buying Settings", "buying_price_list")
	if not nhap or gia != nhap:
		lech("Buying Settings", "buying_price_list", gia, nhap or "Gia nhap", "bảng giá nhập của app (BP §5.4)")
	if nhap and not frappe.db.get_value("Price List", nhap, "buying"):
		lech("Price List", nhap, "buying = 0", "buying = 1", "bảng giá nhập phải là bảng giá mua")
	if frappe.db.exists("DocType", "NPP Cai Dat"):
		from .ban_hang import cai_dat_ban

		cd = cai_dat_ban()
		g = frappe.db.get_singles_dict("NPP Cai Dat", cast=False)
		for truong, vi_sao in (("kho_ban", "vùng sale"), ("kho_can_date", "vùng date"), ("mau_thue_mua", "dòng VAT của phiếu nhập / trả NCC"),
				("tk_thue_dau_vao", "dòng Actual thuế gõ tay của phiếu nhập; chênh VAT của bút toán DCN-"),
				("tk_giam_dau_phieu_nhap", "dòng Actual + Deduct giảm đầu phiếu nhập (CFD-11) — thiếu thì phiếu có giảm đầu phiếu không lưu được"),
				("tk_no_ncc_lap_tay", "dòng của tờ nợ NCC lập tay NTN- (màn Thêm công nợ NCC) — thiếu thì dùng TK hàng về chưa có hoá đơn của công ty"),
				("tk_xuat_le", "TK chênh lệch phiếu xuất lẻ XKL- — thiếu thì ghi sổ xuất lẻ báo CAI_DAT_THIEU"),
				("tk_nhap_kho_khong_hd", "TK chênh lệch phiếu nhập kho tay IN- không công nợ — thiếu thì nhập kho tay báo CAI_DAT_THIEU")):
			if not g.get(truong):
				lech("NPP Cai Dat", truong, None, "(có giá trị)", vi_sao)
		ng = g.get("nguong_kho_date_ngay")
		if ng not in (None, "") and not (0 <= cint(ng) <= 365):
			lech("NPP Cai Dat", "nguong_kho_date_ngay", ng, "0–365", "pricing_rules.date_warehouse_threshold_days CHECK 0–365")
		abbr = cd.get("abbr")
		vao = g.get("tk_thue_dau_vao") or _tk_thue_vao(cd)
		for r in THUE_SUAT:
			ten = ten_mau_thue_dong(r / 100, abbr) if abbr else None
			if not ten or not frappe.db.exists("Item Tax Template", ten):
				lech("Item Tax Template", ten or f"VAT {r}%", None, "(có)", "mẫu thuế dòng của phiếu nhập")
				continue
			if not vao or not frappe.db.exists("Item Tax Template Detail", {"parent": ten, "tax_type": vao}):
				lech("Item Tax Template", ten, "thiếu TK đầu vào", vao, "thiếu TK đầu vào → phiếu nhập tính VAT = 0 mà không báo (PoC 05/11)")
	for ncc in frappe.get_all("Supplier", filters={"disabled": 1}, pluck="name"):
		lech("Supplier", ncc, "disabled = 1", "disabled = 0 (ngừng hợp tác = npp_ngung_hop_tac)",
			"lõi chặn mọi bút toán với NCC bị tắt (party.py:881–889) — không huỷ / trả / chi được")
	return ra


@frappe.whitelist()
def kiem_cai_dat() -> list[dict]:
	frappe.only_for(("System Manager", "Administrator"))
	return kiem()


def ghi_nhat_ky_lech() -> None:
	"""after_migrate: còn lệch sau dam_bao → một Error Log (không làm hỏng migrate)."""
	try:
		lech = kiem()
	except Exception:  # noqa: BLE001
		frappe.log_error(title="Bộ kiểm cài đặt kho / mua hàng hỏng", message=frappe.get_traceback())
		return
	if lech:
		frappe.log_error(title=f"Cài đặt kho / mua hàng: {len(lech)} chỗ lệch", message=frappe.as_json(lech, indent=1))


def cai_dat_kho() -> frappe._dict:
	"""`cai_dat_ban()` (bộ đệm một request — test đặt `frappe.local._npp_cai_dat_ban = None` để đọc lại) mở rộng thêm khoá P4."""
	from .ban_hang import cai_dat_ban

	cd = cai_dat_ban()
	if "nguong" not in cd:
		g = frappe.db.get_singles_dict("NPP Cai Dat") if frappe.db.exists("DocType", "NPP Cai Dat") else {}
		cd.update({
			"nguong": nguong(g.get("nguong_kho_date_ngay")), "cho_ban_vuot_ton": cint(g.get("cho_ban_vuot_ton")),
			"bang_gia_nhap": g.get("bang_gia_nhap") or "Gia nhap",
			**{k: g.get(k) for k in ("tk_thue_dau_vao", "tk_giam_dau_phieu_nhap", "tk_trung_gian_sua_gia_nhap", "tk_no_ncc_lap_tay",
				"tk_xuat_le", "tk_nhap_kho_khong_hd", "tk_thua_kiem_ke", "tk_chi_phi_phai_tra", "tk_chi_phi_mac_dinh")},
		})
	return cd
