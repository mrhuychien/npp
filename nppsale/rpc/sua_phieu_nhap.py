"""SỬA PHIẾU NHẬP ĐÃ HOÀN THÀNH (P4 — mốc M7; đặc tả kho_mua §3.3, §7.1 #2, §7.2 #3 / #19, §7.3 điểm 7 / 34; CFD-06, câu 15; BP §5.9 `npp_sua_gia`,
§5.10 Landed Cost Voucher `SGN-`, §6.4) — RPC `sua_phieu_nhap` (nppsale mig 235 / 236; chủ nhà 06/10/2026: "những phiếu nhập hàng từ NCC đã bán hàng ra
không sửa được, tao muốn sửa được"). Luật thuần: nppsale.luat.sua_phieu_nhap.

Khuôn ghi kho (CFD-05): `chuan_bi` đọc người gọi, cài đặt, tờ cuối chuỗi amend + mặt hàng cũ ∪ mặt hàng gửi lên → cổng COMMIT → câu ĐẦU là khoá Bin →
khoá PI `FOR UPDATE` (theo chuỗi amend — trang cũ của `PN-0001` sửa được `PN-0001-1` như nppsale một id) → vai (không cửa gọi nội bộ) → trạng thái →
kiểm tham số đúng thứ tự hàm gốc (`luat.sua_phieu_nhap`) → ghép dòng ↔ lô + `DA_XUAT_NHIEU_HON` → rẽ nhánh:

- NHÁNH A — không lô nào đã xuất (và mọi hàng không lô — câu 15): huỷ + amend `PN-xxxx-n` (CFD-01). Ghi nhớ tiền đã trả (tham chiếu phiếu chi `PCNCC-` /
  Ghi trả `GTN-`, bút toán chuyển trả dư của lần sửa trước — huỷ, bù trừ `CTN-` — huỷ để lập lại) → thân huỷ nội bộ (`phieu_nhap.huy(sua=True)`: bỏ
  kiểm DA_TRA_TIEN, không dồn trả trước; huỷ cả LCV / DCN của lần sửa giá trước) → tờ amend: đầu phiếu / dòng theo tham số, ngày / giờ ghi sổ + mốc hoàn
  thành của tờ gốc (ghi lùi → repost), dòng ghép lô cũ nhập vào ĐÚNG Batch cũ, dòng mới lô mới `<PN gốc>-<NNN>` (NNN = hậu tố lớn nhất của MỌI Batch
  tiền tố ấy + 1 — nppsale chỉ xét lô còn dòng nên thêm lại hàng đã bỏ ra trùng mã, KB21), kho dòng theo vùng mới + hạn lô (`kho_nhan_lo`) → giá nhập
  → phân bổ lại tiền (`reconcile_against_document`, giữ tên phiếu tiền) tới mức còn nợ của tờ mới, phần dư chuyển vào CHÍNH tờ mới (bút toán
  `chuyen_tra_du_ncc` — nppsale giữ cả `paid` trên dòng nợ; khuôn `chuyen_tien_thu` của Sửa HĐ, Q7) → lập lại bù trừ `CTN-` trỏ tờ mới → dồn trả
  trước (đặc tả §2.8: PI dương ghi sổ — kể cả amend của sửa). Lô không đưa về được kho nhận (phiếu rà soát chở cả lô khác đã động) / hàng không lô
  thiếu tồn để huỷ → lùi về điểm lưu, đi nhánh B.
- NHÁNH B — có lô đã xuất: CHỈ SỬA GIÁ (CFD-06; ⚠K §7.2 #3 — hẹp hơn nppsale: đổi mặt hàng / ĐV / SL / hệ số / số dòng / NCC / kho →
  `PHIEU_DA_XUAT_CHI_SUA_GIA`). Số mới tính bằng một bản sao TRONG BỘ NHỚ của tờ mang giá mới (cùng luật thuế / làm tròn của lõi); chênh tiền hàng
  từng dòng → LCV `SGN-` một chiều (tăng / giảm tách hai tờ — BP §5.10), dòng chi phí vào `tk_trung_gian_sua_gia_nhap`; bút toán `DCN-` (Phải trả
  NCC tham chiếu phiếu ↔ TK trung gian ↔ thuế đầu vào ↔ giảm đầu phiếu; `Debit Note` khi giảm nợ — nợ âm được như nppsale); `npp_sua_gia` = số hiện
  hành (cổng phủ lên phiếu / dòng); số / ngày HĐ NCC, ghi chú phiếu ghi thẳng (`bill_no`, `npp_ghi_chu` AOS; `bill_date` — §7.2 #19, ghi `db_set`:
  trường hiển thị + ngày hiệu lực giá nhập, không đụng sổ); repost (CFD-07 — giá vốn phần đã bán / trả NCC / xuất lẻ / chuyển kho theo giá lô mới,
  ⚠K §7.1 #2 lan cả lô đích chuyển kho); giá nhập theo giá đã sửa; KHÔNG dồn trả trước (như nppsale).

Trả `{id, total, paid, so_dong, doi_gia_lo}` như nppsale: `id` = tờ còn hiệu lực (nhánh A tờ amend — giao diện điều hướng theo id trả về, §7.3 điểm 2);
`doi_gia_lo` = số lô cũ giữ lại mà giá vốn đổi (cả nhánh A — nppsale đếm lô đổi giá dù nhánh nào).
"""
from __future__ import annotations

import json
import re

import frappe
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai
from nppsale.luat import kho_mua as K
from nppsale.luat import sua_phieu_nhap as S
from nppsale.luat.tim import khoa_tim_ds
from nppsale.thiet_lap.kho_mua import cai_dat_kho

from . import phieu_nhap as P
from . import rpc

DT = P.DT
LY_DO_HUY = "Sửa phiếu nhập đã hoàn thành — lập lại"


# ================================================================================================ chuẩn bị + khoá
def _hang_tham_so(p_lines) -> set:
	ds = p_lines
	if isinstance(ds, str):
		try:
			ds = json.loads(ds)
		except ValueError:
			ds = None
	if not isinstance(ds, list):
		return set()
	return {K.chu_json(x.get("product_id")) for x in ds if isinstance(x, dict) and x.get("product_id") not in (None, "")}


def _chuan_bi_sua(p_invoice_id=None, p_head=None, p_lines=None):
	"""Đọc trước khi khoá (cổng commit sau bước này): người gọi, cài đặt, tờ cuối chuỗi amend, mặt hàng cũ ∪ mặt hàng gửi lên (khoá Bin cả hai — §2.1)."""
	hien_tai()
	cai_dat_kho()
	ten = P._hieu_luc(P._chu(p_invoice_id))
	frappe.local._npp_sua_pn = (P._chu(p_invoice_id), ten, P._hang_cua(ten) | _hang_tham_so(p_lines))


# ================================================================================================ đọc lô / số hiện hành
def _tu_dong_ra(lo: str, kho: str, cd) -> float:
	"""SL lô đã bị phiếu `CKL-` rà soát tự động (`chuyen_date_tu_dong`) chuyển khỏi `kho` (dương)."""
	from nppsale.rpc.lo_kho import _phat_sinh, _tu_dong

	return -sum(flt(q) for vt, vn, k, q, _l in _phat_sinh(lo) if k == kho and flt(q) < 0 and vt == "Stock Entry" and _tu_dong(vn, cd))


def _lo_cu(doc, cd) -> tuple[list[K.LoCu], dict, set]:
	"""Lô của tờ: ([LoCu], {mã lô: (dòng, kho, SL nhập)}, chứng từ đã lấy hàng từ các lô — HĐ, xuất lẻ, trả NCC, chuyển kho tay… — cho câu lỗi nhánh B)."""
	from nppsale.rpc.lo_kho import _phat_sinh, _tu_dong

	lo_dong = P._lo_cua_dong(doc.name)
	ra, chi_tiet, chung_tu = [], {}, set()
	for d in sorted(doc.items, key=lambda x: x.idx):
		lo = lo_dong.get(d.name)
		if not lo:
			continue
		nhap = flt(d.stock_qty) or flt(d.qty) * flt(d.conversion_factor or 1)
		ps = _phat_sinh(lo)
		ton_dong = sum(flt(q) for _vt, _vn, k, q, _l in ps if k == d.warehouse)
		ton_khac = sum(flt(q) for _vt, _vn, k, q, _l in ps if k != d.warehouse)
		tu_dong = _tu_dong_ra(lo, d.warehouse, cd)
		da_xuat = S.da_xuat_lo(round(nhap, 6), round(ton_dong, 6), round(tu_dong, 6), round(ton_khac, 6))
		ra.append(K.LoCu(ma=lo, hang=d.item_code, da_xuat=da_xuat))
		chi_tiet[lo] = (d, d.warehouse, nhap)
		for vt, vn, _k, q, _l in ps:
			if flt(q) < 0 and vn != doc.name and not (vt == "Stock Entry" and _tu_dong(vn, cd)):
				chung_tu.add(vn)
	return ra, chi_tiet, chung_tu


def _tk_giam(cd) -> str:
	return cd.get("tk_giam_dau_phieu_nhap") or ""


def _so_cua(doc, cd) -> S.SoPhieu:
	"""Số tiền của một tờ lõi (đã làm tròn đồng): tiền hàng = `total`; thuế = Σ dòng thuế khác dòng giảm đầu phiếu; giảm đã áp = Σ dòng giảm (Deduct +)."""
	thue = giam = 0.0
	for t in doc.get("taxes") or []:
		x = flt(t.tax_amount) * (-1 if t.add_deduct_tax == "Deduct" else 1)
		if t.account_head == _tk_giam(cd):
			giam -= x
		else:
			thue += x
	return S.SoPhieu(tien_hang=K.so(round(flt(doc.total), 2)), thue=K.so(round(thue, 2)), giam_ap=K.so(round(giam, 2)),
		tong=K.so(round(flt(doc.grand_total), 2)))


def _hien_hanh(doc, cd) -> tuple[list[S.DongCu], S.SoPhieu]:
	"""Dòng + số HIỆN HÀNH của tờ: tờ lõi, phủ `npp_sua_gia` khi đã sửa giá (nhánh B lần trước)."""
	phu = P.sua_gia_cua(doc) or {}
	pd = phu.get("dong") or {}
	dong = []
	for d in sorted(doc.items, key=lambda x: x.idx):
		x = pd.get(str(d.idx)) or {}
		dong.append(S.DongCu(idx=d.idx, hang=d.item_code, dv=d.uom, sl=K.so(d.qty), hs=K.so(d.conversion_factor if d.conversion_factor is not None else 1),
			gia=K.so(x.get("don_gia", d.price_list_rate)), giam=K.so(x.get("giam_dong", flt(d.get("npp_giam_dong")))),
			thue=K.so(x.get("thue_suat", flt(d.get("npp_thue_suat")))), ghi_chu=x.get("ghi_chu", d.get("npp_ghi_chu")),
			tien=K.so(x.get("thanh_tien", round(flt(d.amount), 2)))))
	dp = phu.get("dau_phieu")
	if dp:
		so = S.SoPhieu(tien_hang=K.so(dp["tien_hang"]), thue=K.so(dp["thue"]), giam_ap=K.so(dp.get("giam_ap", 0)), tong=K.so(dp["tong"]))
	else:
		so = _so_cua(doc, cd)
	return dong, so


def _gia_tri_dong_pi(dong: S.DongSua) -> dict:
	return {"product_id": dong.hang, "unit_name": dong.dv, "quantity": float(dong.sl), "unit_price": float(dong.gia),
		"line_discount": float(dong.giam), "vat_rate": float(dong.thue), "conversion_factor": float(dong.hs), "notes": dong.ghi_chu}


# ================================================================================================ sua_phieu_nhap
@rpc("sua_phieu_nhap", ghi=True, chuan_bi=_chuan_bi_sua)
def sua_phieu_nhap(p_invoice_id=None, p_head=None, p_lines=None):
	nc = hien_tai()
	cd = cai_dat_kho()
	x = getattr(frappe.local, "_npp_sua_pn", None)
	frappe.local._npp_sua_pn = None  # dùng MỘT lần
	if x and x[0] == P._chu(p_invoice_id):
		ten, hang = x[1], x[2]
	else:  # gọi nội bộ không qua cổng
		ten = P._hieu_luc(P._chu(p_invoice_id))
		hang = P._hang_cua(ten) | _hang_tham_so(p_lines)
	r = P._khoa(ten, hang, cd)
	if r is None:
		raise NppLoi(S.PHIEU_KHONG_TON_TAI)
	P._kiem_vai("sua_phieu_nhap", nc)
	if K.trang_thai_pi(r.docstatus, r.npp_huy_luc) != "completed":
		raise NppLoi(S.PHIEU_CHUA_HOAN_THANH)
	mang = S.kiem_mang(p_lines)
	doc = frappe.get_doc(DT, r.name)
	from nppsale.rpc.goi_lo import vung_cua_kho

	ncc = S.ncc_dau(p_head, doc.supplier)
	if not frappe.db.exists("Supplier", ncc):
		raise NppLoi(S.NCC_KHONG_HOP_LE)
	vung_cu = vung_cua_kho(P.kho_phieu(doc), cd) or "sale"
	dau = S.doc_dau(p_head, ncc, vung_cu)
	dong = S.doc_dong(mang)
	co = set(frappe.get_all("Item", filters={"name": ("in", [d.hang for d in dong if d.hang] or [""])}, pluck="name"))
	S.kiem_dong(dong, co)
	moi_hang = {d.hang for d in dong} - set(hang)
	if moi_hang:  # mặt hàng gửi lên ngoài bước chuẩn bị (gọi nội bộ) — khoá Bin thêm trước mọi ghi
		from nppsale.rpc.xuat_hang import _khoa_bin

		_khoa_bin(moi_hang, cd)
	lo_cu, chi_tiet, chung_tu = _lo_cu(doc, cd)
	ten_hang = dict(frappe.get_all("Item", filters={"name": ("in", list({d.hang for d in dong} | {o.hang for o in lo_cu}))},
		fields=["name", "item_name"], as_list=True))
	dv_cs = dict(frappe.get_all("Item", filters={"name": ("in", list({o.hang for o in lo_cu}) or [""])}, fields=["name", "stock_uom"], as_list=True))
	ghep = K.ghep_dong_lo([K.DongGhep(stt=d.stt, hang=d.hang, base=d.base) for d in dong], lo_cu, ten_hang, dv_cs)
	if ghep.muc_loi:
		raise K.loi_da_xuat_nhieu_hon(ghep.muc_loi)
	S.kiem_tien_am(dong)
	ngay = S.ngay_hd(dau, doc.bill_date)
	if any(o.da_xuat != 0 for o in lo_cu):
		return _nhanh_b(doc, dau, dong, ngay, chung_tu, cd, nc)
	if dau.ncc != doc.supplier:
		from nppsale.su_kien.cong_no_ncc import gia_tri_pi

		da_tra = flt((gia_tri_pi(doc.name) or {}).get("da_tra"))
		if abs(da_tra) >= 0.005:
			raise S.loi_ncc_da_tra_tien(K.so(round(da_tra, 2)))
	frappe.db.savepoint("npp_sua_pn_a")
	try:
		return _nhanh_a(doc, dau, dong, ngay, ghep, lo_cu, cd, nc)
	except NppLoi as e:
		if not e.ma.startswith("HANG_DA_XUAT"):
			raise
		# lô không đưa về được kho nhận (phiếu rà soát chở cả lô khác đã động) / hàng không lô thiếu tồn để huỷ: như lô đã xuất — chỉ sửa giá
		frappe.db.rollback(save_point="npp_sua_pn_a")
		frappe.local.message_log = []
		return _nhanh_b(frappe.get_doc(DT, r.name), dau, dong, ngay, chung_tu, cd, nc)


# ================================================================================================ nhánh A — huỷ + amend
def _nho_tien(pi: str) -> frappe._dict:
	"""Ghi nhớ tiền đã trả vào tờ cũ TRƯỚC khi huỷ (lõi gỡ tham chiếu lặng lẽ): {phiếu tiền: số} của tham chiếu Payment Entry (`PCNCC-` / `GTN-`) +
	phần trả dư đã chuyển vào tờ ở lần sửa trước (bút toán `chuyen_tra_du_ncc` — huỷ ngay, gộp về phiếu tiền); bút toán bù trừ `CTN-` trỏ tờ (huỷ —
	lập lại theo tờ mới)."""
	from nppsale.rpc.can_tru import huy_je
	from nppsale.su_kien.cong_no_ncc import huy_chuyen_tra_du, je_chuyen_tra_du, tien_chuyen_tra_du

	pe: dict[str, float] = {}
	for ten, so in frappe.db.sql("""SELECT r.`parent`, SUM(r.`allocated_amount`) FROM `tabPayment Entry Reference` r
			JOIN `tabPayment Entry` p ON p.`name` = r.`parent` AND r.`parenttype` = 'Payment Entry'
			WHERE p.`docstatus` = 1 AND p.`party_type` = 'Supplier' AND r.`reference_doctype` = 'Purchase Invoice' AND r.`reference_name` = %s
			GROUP BY r.`parent`""", pi):
		pe[ten] = pe.get(ten, 0.0) + flt(so)
	du = je_chuyen_tra_du(pi=pi)
	for je in du:
		x, so = tien_chuyen_tra_du(je)
		if x:
			pe[x] = pe.get(x, 0.0) + so
	huy_chuyen_tra_du(du)
	ctn = []
	if frappe.get_meta("Journal Entry").has_field("npp_loai"):
		ds = [r[0] for r in frappe.db.sql("""SELECT DISTINCT j.`name`, j.`creation` FROM `tabJournal Entry` j
			JOIN `tabJournal Entry Account` a ON a.`parent` = j.`name` AND a.`parenttype` = 'Journal Entry'
			WHERE j.`docstatus` = 1 AND j.`npp_loai` = 'bu_tru_ncc' AND a.`reference_type` = 'Purchase Invoice' AND a.`reference_name` = %s
			ORDER BY j.`creation`, j.`name`""", pi)]
		ctn = huy_je(ds)
	return frappe._dict(pe=pe, ctn=ctn)


def _so_lo_moi(goc: str) -> int:
	"""Hậu tố lớn nhất của MỌI Batch `<PN gốc>-NNN` (kể cả lô đã tắt / mồ côi — Batch duy nhất toàn site)."""
	mau = re.compile(rf"{re.escape(goc)}-(\d+)")
	so = 0
	for (ten,) in frappe.db.sql("SELECT `name` FROM `tabBatch` WHERE `name` LIKE %s", (goc.replace("%", "\\%").replace("_", "\\_") + "-%",)):
		m = mau.fullmatch(ten)
		if m:
			so = max(so, int(m.group(1)))
	return so


def _lap_amend(cu, dau: S.DauPhieu, dong: list[S.DongSua], ngay, ghep: K.KetQuaGhep, cd, nc):
	"""Tờ amend của tờ đã huỷ theo tham số sửa — chưa ghi sổ."""
	from erpnext.accounts.party import get_party_account

	from nppsale.rpc.goi_lo import gan_goi_lo, kho_cua_vung, kho_nhan_lo, lap_goi_lo

	moi = frappe.copy_doc(cu, ignore_no_copy=False)
	moi.docstatus = 0  # copy_doc giữ docstatus khi chạy bài (`frappe.in_test`)
	for d in moi.get_all_children():
		d.docstatus = 0
	moi.amended_from = cu.name
	kho = kho_cua_vung(dau.vung, cd)
	moi.update({"naming_series": cu.naming_series, "is_return": 0, "npp_huy_luc": None, "npp_huy_boi": None, "npp_ly_do_huy": None,
		"npp_hoan_thanh_luc": cu.get("npp_hoan_thanh_luc"), "posting_date": cu.posting_date, "posting_time": str(cu.posting_time),
		"set_posting_time": 1, "npp_sua_gia": None, "update_stock": 1, "disable_rounded_total": 1, "ignore_pricing_rule": 1,
		"buying_price_list": cd.bang_gia_nhap, "bill_no": dau.so_hd, "bill_date": ngay, "npp_giam_dau_phieu": float(dau.giam),
		"npp_co_thue_go_tay": 0 if dau.thue_tay is None else 1, "npp_thue_go_tay": 0 if dau.thue_tay is None else float(dau.thue_tay),
		"npp_ghi_chu": dau.ghi_chu, "set_warehouse": kho, "npp_kho_nhap": kho})
	if dau.ncc != cu.supplier:
		moi.update({"supplier": dau.ncc, "supplier_name": frappe.db.get_value("Supplier", dau.ncc, "supplier_name"),
			"credit_to": get_party_account("Supplier", dau.ncc, cd.cong_ty), "supplier_address": None, "address_display": None,
			"contact_person": None, "contact_display": None})
	P.han_lai(moi)
	moi.set("items", [])
	luc = now_datetime()
	hom_nay = luc.date()
	gio = str(cu.posting_time)
	goc = "-".join(cu.name.split("-")[:2])
	so_cuoi = _so_lo_moi(goc)
	lo_moi = []
	for d in sorted(dong, key=lambda x: x.stt):
		r = moi.append("items", {})
		P._ap_dong(moi, r, _gia_tri_dong_pi(d), cd)
		r.idx = d.stt
		r.allow_zero_valuation_rate = 1 if not flt(r.rate) else 0
		it = frappe.db.get_value("Item", d.hang, ["has_batch_no", "shelf_life_in_days"], as_dict=True)
		if not it or not it.has_batch_no:
			r.warehouse = kho  # hàng không lô (câu 14 B): kho người chọn
			continue
		lo = ghep.ghep.get(d.stt)
		if lo:  # dòng ghép lô cũ → nhập vào ĐÚNG Batch cũ (lô đã tắt lúc huỷ thì mở lại — nppsale `status 'available'`)
			han = frappe.db.get_value("Batch", lo, "expiry_date")
			frappe.db.set_value("Batch", lo, {"disabled": 0, "npp_gia_von_lo_rong": float(d.gia_von())})
		else:  # dòng mới → lô mới (ngày SX / hạn tính từ NGÀY SỬA như nppsale bước 19)
			so_cuoi += 1
			lo = K.ma_lo_phieu_nhap(goc, so_cuoi)
			han = add_days(hom_nay, cint(it.shelf_life_in_days)) if cint(it.shelf_life_in_days) > 0 else None
			lo_moi.append(lo)
		r.warehouse = kho_nhan_lo(dau.vung, han, cd, hom_nay)
		if lo in lo_moi:
			frappe.get_doc({"doctype": "Batch", "batch_id": lo, "item": d.hang, "manufacturing_date": hom_nay, "expiry_date": han, "npp_ngay_nhap": luc,
				"reference_doctype": DT, "reference_name": cu.name, "npp_kho_tao": r.warehouse, "npp_tim_kd": khoa_tim_ds(lo),
				"npp_gia_von_lo_rong": float(d.gia_von())}).insert(ignore_permissions=True)
		gan_goi_lo(r, lap_goi_lo("Inward", DT, d.hang, r.warehouse, {lo: float(d.base)}, moi.posting_date, gio, cd.cong_ty))
	moi.flags.ignore_permissions = True
	P.dung_thue(moi, cd)
	return moi, lo_moi


def _tra_lai_tien(nho: frappe._dict, moi) -> None:
	"""Tiền đã trả của tờ cũ về tờ mới: phiếu tiền theo lúc lập — phân bổ = min(đã trả tờ cũ, còn nợ tờ mới, phần chưa phân bổ thật theo sổ) qua
	`reconcile_against_document` (giữ tên phiếu); phần dư → bút toán `chuyen_tra_du_ncc` vào chính tờ mới (NCC nợ lại mình như nppsale giữ `paid`)."""
	from nppsale.su_kien import cong_no_ncc as N
	from nppsale.su_kien.cong_no import _con_no

	for pe in sorted(nho.pe, key=lambda x: (frappe.db.get_value("Payment Entry", x, "creation"), x)):
		cu = round(flt(nho.pe[pe]), 2)
		if cu <= 0.005:
			continue
		con_pi = round(_con_no([moi.name], "Purchase Invoice"), 2)
		that = round(-_con_no([pe], "Payment Entry"), 2)
		phan = max(0.0, min(cu, con_pi, that))
		if phan > 0.005:
			N.ap_phan_bo(pe, moi.name, phan, moi.supplier)
		du = round(min(cu - phan, -_con_no([pe], "Payment Entry")), 2)
		if du > 0.005:
			N.lap_chuyen_tra_du(pe, moi.name, du)
		N.chieu_tra_truoc(pe)


def _lap_lai_ctn(je, cu: str, moi) -> str:
	"""Amend bút toán bù trừ `CTN-` đã huỷ: vế tham chiếu tờ cũ → tờ mới (giữ số từng vế — `Debit Note` không kiểm số còn nợ)."""
	x = frappe.copy_doc(je)
	x.amended_from = je.name
	x.docstatus = 0
	for a in x.accounts:
		a.docstatus = 0
		if a.reference_type == DT and a.reference_name == cu:
			a.reference_name = moi.name
			a.account = moi.credit_to or a.account
	if x.get("npp_phieu_nhap") == cu:
		x.npp_phieu_nhap = moi.name
	x.flags.ignore_permissions = True
	x.insert()
	x.submit()
	frappe.local.message_log = []
	return x.name


def _nhanh_a(doc, dau: S.DauPhieu, dong: list[S.DongSua], ngay, ghep: K.KetQuaGhep, lo_cu: list[K.LoCu], cd, nc) -> dict:
	from nppsale.su_kien import cong_no_ncc as N

	# giá vốn hiện hành của các lô cũ (đếm `doi_gia_lo` như nppsale: lô giữ lại mà giá đổi)
	hien = {x.idx: x for x in _hien_hanh(doc, cd)[0]}
	lo_dong = P._lo_cua_dong(doc.name)
	gia_cu = {lo_dong[d.name]: hien[d.idx].gia_von() for d in doc.items if lo_dong.get(d.name) and d.idx in hien}
	nho = _nho_tien(doc.name)
	P.huy(doc.name, LY_DO_HUY, nc, cd, sua=True)
	cu = frappe.get_doc(DT, doc.name)
	moi, lo_moi = _lap_amend(cu, dau, dong, ngay, ghep, cd, nc)
	moi.insert()
	moi.submit()  # hook on_submit: chiếu dòng công nợ NCC của tờ mới
	frappe.local.message_log = []
	for lo in lo_moi:
		frappe.db.set_value("Batch", lo, "reference_name", moi.name, update_modified=False)
	P.ghi_gia_nhap_tu_phieu(moi)
	P._xep_repost()
	_tra_lai_tien(nho, moi)
	for je in nho.ctn:
		_lap_lai_ctn(je, doc.name, moi)
	N.chieu_phieu_nhap(moi.name)
	if flt(moi.grand_total) > 0:
		N.don_tra_truoc_ncc(moi.supplier)  # đặc tả §2.8: PI dương ghi sổ (kể cả amend của sửa) — SAU khi tiền cũ đã về tờ mới
	gt = N.gia_tri_pi(moi.name) or {}
	cap = [(gia_cu[ghep.ghep[d.stt]], d.gia_von()) for d in dong if ghep.ghep.get(d.stt) in gia_cu]
	return {"id": moi.name, "total": _ra(moi.grand_total), "paid": _ra(gt.get("da_tra")), "so_dong": len(dong),
		"doi_gia_lo": S.so_lo_doi_gia(cap)}


def _ra(x):
	from nppsale.rpc.cong_no_ncc import _ra as ra

	return ra(flt(x))


# ================================================================================================ nhánh B — chỉ sửa giá
def _so_moi(doc, dong: list[S.DongSua], dau: S.DauPhieu, cd) -> tuple[S.SoPhieu, dict[int, float]]:
	"""Số mới của tờ nếu mang giá mới — tính trên một bản sao TRONG BỘ NHỚ (cùng luật thuế / làm tròn của lõi, không ghi sổ)."""
	sao = frappe.copy_doc(doc)
	moi = {d.stt: d for d in dong}
	for r in sao.items:
		d = moi[r.idx]
		kho = r.warehouse
		P._ap_dong(sao, r, {"unit_price": float(d.gia), "line_discount": float(d.giam), "vat_rate": float(d.thue), "notes": d.ghi_chu}, cd)
		r.warehouse = kho
	sao.update({"npp_giam_dau_phieu": float(dau.giam), "npp_co_thue_go_tay": 0 if dau.thue_tay is None else 1,
		"npp_thue_go_tay": 0 if dau.thue_tay is None else float(dau.thue_tay)})
	sao.flags.ignore_permissions = True
	P.dung_thue(sao, cd)
	sao.calculate_taxes_and_totals()
	return _so_cua(sao, cd), {r.idx: round(flt(r.amount), 2) for r in sao.items}


def _tk_trung_gian(cd) -> str:
	tk = cd.get("tk_trung_gian_sua_gia_nhap")
	if not tk:
		raise NppLoi("CAI_DAT_THIEU: NPP Cai Dat chưa có tài khoản trung gian sửa giá nhập (tk_trung_gian_sua_gia_nhap).")
	return tk


def _lap_lcv(doc, phan: dict[int, object], cd) -> str:
	"""Landed Cost Voucher `SGN-` MỘT chiều trên phiếu: `applicable_charges` từng dòng = chênh tiền hàng (Distribute Manually), dòng chi phí vào TK
	trung gian sửa giá nhập (BP §5.10 — PoC 4)."""
	ten_dong = {d.name: d.idx for d in doc.items}
	x = frappe.new_doc("Landed Cost Voucher")
	x.update({"naming_series": "SGN-.####", "company": cd.cong_ty, "posting_date": getdate(nowdate()),
		"distribute_charges_based_on": "Distribute Manually", "npp_phieu_nhap": doc.name})
	x.append("purchase_receipts", {"receipt_document_type": DT, "receipt_document": doc.name, "supplier": doc.supplier,
		"grand_total": doc.grand_total})
	x.get_items_from_purchase_receipts()
	for it in x.items:
		it.applicable_charges = float(phan.get(ten_dong.get(it.purchase_receipt_item), 0))
	x.append("taxes", {"expense_account": _tk_trung_gian(cd), "description": f"Sửa giá phiếu nhập {doc.name}",
		"amount": float(sum(K.so(v) for v in phan.values()))})
	x.flags.ignore_permissions = True
	x.insert()
	x.submit()  # lõi ghi lại sổ kho / sổ cái của phiếu với giá lô mới + xếp repost chứng từ sau (phần đã bán)
	frappe.local.message_log = []
	return x.name


def _lap_dcn(doc, bt: S.ButToan, cd) -> str:
	"""Bút toán `DCN-` (BP §5.10 / §3.3 nhánh B bước 3): Phải trả NCC (tham chiếu phiếu) ↔ TK trung gian ↔ thuế đầu vào ↔ giảm đầu phiếu nhập."""
	cc = frappe.get_cached_value("Company", cd.cong_ty, "cost_center")
	je = frappe.new_doc("Journal Entry")
	je.update({"voucher_type": bt.loai, "naming_series": "DCN-.####", "company": cd.cong_ty, "posting_date": getdate(nowdate()),
		"npp_loai": "dieu_chinh_gia_nhap", "npp_phieu_nhap": doc.name, "user_remark": f"Sửa giá phiếu nhập {doc.name}"})

	def ve(tk, so, **them):
		so = K.so(so)
		if so:
			je.append("accounts", {"account": tk, "debit_in_account_currency": float(so) if so > 0 else 0,
				"credit_in_account_currency": float(-so) if so < 0 else 0, "cost_center": cc, **them})

	ve(doc.credit_to, bt.ncc, party_type="Supplier", party=doc.supplier, reference_type=DT, reference_name=doc.name)
	ve(_tk_trung_gian(cd), bt.trung_gian)
	if bt.thue:
		if not cd.get("tk_thue_dau_vao"):
			raise NppLoi("CAI_DAT_THIEU: NPP Cai Dat chưa có tài khoản thuế GTGT đầu vào (tk_thue_dau_vao).")
		ve(cd.tk_thue_dau_vao, bt.thue)
	if bt.giam:
		if not cd.get("tk_giam_dau_phieu_nhap"):
			raise NppLoi("CAI_DAT_THIEU: NPP Cai Dat chưa có tài khoản giảm đầu phiếu nhập (tk_giam_dau_phieu_nhap).")
		ve(cd.tk_giam_dau_phieu_nhap, bt.giam)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()  # hook sau_but_toan: chiếu dòng công nợ (so_tien = grand_total + Σ chênh DCN)
	frappe.local.message_log = []
	return je.name


def _nhanh_b(doc, dau: S.DauPhieu, dong: list[S.DongSua], ngay, chung_tu: set, cd, nc) -> dict:
	from nppsale.rpc.goi_lo import vung_cua_kho
	from nppsale.su_kien import cong_no_ncc as N

	cu_dong, so_cu = _hien_hanh(doc, cd)
	dv_moi = {d.stt: frappe.db.get_value("UOM", d.dv, "name") for d in dong}
	doi = S.kiem_chi_sua_gia(dong, cu_dong, dv_moi, dau.ncc, doc.supplier, dau.vung, vung_cua_kho(P.kho_phieu(doc), cd) or "sale")
	if doi:
		raise S.loi_chi_sua_gia(chung_tu)
	so_moi, tien_moi = _so_moi(doc, dong, dau, cd)
	chenh = S.chenh_dong({x.idx: x.tien for x in cu_dong}, tien_moi)
	lcv = [_lap_lcv(doc, phan, cd) for phan in S.tach_lcv(chenh)]
	bt = S.but_toan_dcn(so_cu, so_moi)
	je = None if bt.rong() else _lap_dcn(doc, bt, cd)
	for x in lcv:
		if je:
			frappe.db.set_value("Landed Cost Voucher", x, "npp_but_toan", je, update_modified=False)
	moi_idx = {d.stt: d for d in dong}
	phu = S.json_sua_gia(P.sua_gia_cua(doc), [(i, moi_idx[i], tien_moi[i]) for i in sorted(tien_moi)], dau, so_moi,
		{"luc": str(now_datetime()), "nguoi": nc.user if nc else None, "lcv": lcv, "but_toan": je})
	frappe.db.set_value(DT, doc.name, {"npp_sua_gia": json.dumps(phu, ensure_ascii=False), "bill_no": dau.so_hd, "bill_date": ngay,
		"npp_ghi_chu": dau.ghi_chu})
	if lcv:
		P._xep_repost()  # CFD-07: giá vốn phần đã bán / trả NCC / xuất lẻ / chuyển kho tính lại theo giá lô mới (lõi đã xếp việc khi ghi LCV)
	moi = frappe.get_doc(DT, doc.name)
	P.ghi_gia_nhap_tu_phieu(moi)
	N.chieu_phieu_nhap(moi.name)
	gt = N.gia_tri_pi(moi.name) or {}
	lo_dong = P._lo_cua_dong(doc.name)
	doi_gia = S.so_lo_doi_gia((c.gia_von(), moi_idx[c.idx].gia_von()) for c in cu_dong for d in doc.items
		if d.idx == c.idx and lo_dong.get(d.name))
	return {"id": doc.name, "total": _ra(so_moi.tong), "paid": _ra(gt.get("da_tra")), "so_dong": len(dong), "doi_gia_lo": doi_gia}
