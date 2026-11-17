"""KIỂM KÊ (P4 — mốc M6; đặc tả kho_mua §3.17, §3.18, §3.19 (phiếu kiểm kê), §4.5 nguồn (2), §7.1 #1 / #11, §7.3 điểm 15 / 17; blueprint 02 §4.4
`NPP Kiem Ke`, §4.5 `NPP Phieu Chi`; CFD-09 — KHÔNG dùng Stock Reconciliation: khoá lịch sử của lô).

RPC (giữ tên nppsale — thân Postgres ở scratchpad kho_mua/src/<tên>.sql; câu lỗi nguyên văn ở nppsale/luat/kiem_ke.py):
- `post_stock_adjustment(p_entry_id)` (mig 123 / 228): khoá Bin của mặt hàng trên phiếu (câu ĐẦU — CFD-05) → tài khoản khoá → khoá phiếu `FOR UPDATE` (chỉ nhận
  `NPP Kiem Ke` — ⚠K đóng lỗ V13 / V63: nppsale duyệt cả phiếu xuất nháp) → đã duyệt `ALREADY_POSTED` (giờ VN) → khác nháp `BAD_STATUS` → CUỐI CÙNG quyền
  `inventory.approve` (`FORBIDDEN` P0001) → áp chênh lệch từng dòng (`nppsale.luat.kiem_ke.duyet`) → MỘT Material Receipt `DCK-` (phần thừa: gói lô Inward,
  giá = giá vốn HIỆN TẠI của lô nhận — §7.1 #1 / §7.3 điểm 15 đề xuất, lô giữ giá như nppsale; TK `tk_thua_kiem_ke`) ghi sổ TRƯỚC rồi MỘT Material Issue
  `DCK-` (phần hụt: gói lô Outward; TK của danh mục `COGS_ADJ` → danh mục đầu theo mã → `tk_chi_phi_mac_dinh`) — nhập trước để phần hụt lấy được hàng
  phần thừa dòng trước vừa cộng (nppsale cập nhật tồn ngay trong vòng dòng); Batch tắt được đụng → mở tạm trong lượt (lõi chặn gói lô có lô tắt) →
  `shrink_value > 0` → `NPP Phieu Chi` hao hụt (danh mục `COGS_ADJ`…, ngày VN, chưa trả, KHÔNG JE — chi phí đã ở bút toán phiếu xuất `DCK-`) → phiếu
  `posted` + số + lô / kho điền vào dòng. Trả `[{batches_touched, shrink_qty, shrink_value, surplus_qty, surplus_value, expense_id}]`.
- `reject_stock_adjustment(p_entry_id, p_reason)` (mig 170): không có ở `NPP Kiem Ke` mà có ở nguồn khác của cổng `stock_entries` → (sau kiểm quyền)
  `BAD_TYPE`; không đâu có → `ENTRY_NOT_FOUND.`; tài khoản khoá → `ORG_MISMATCH.` (42501); thiếu `inventory.approve` → `FORBIDDEN` (42501); đã huỷ → `false`;
  đã duyệt → `ALREADY_POSTED`; còn lại `cancelled` + nối "Từ chối: <lý do>" → `true`.
Ghi thẳng phiếu kiểm kê NHÁP qua cổng (`stock_entries` / `stock_entry_lines` — nppsale.rpc.kho_tay chuyển sang đây khi nguồn là `NPP Kiem Ke`; trigger
mig 170 + RLS owner / warehouse): lập nháp (`kho` = vùng, mặc định kho bán; mã trình duyệt gửi bị thay bằng `KK-YYMMDD-NNNN`), dòng `{batch_id, quantity =
chênh có dấu, unit_cost}` → `NPP Kiem Ke Dong` (`lo` + `kho` tách từ `batch_id`; lô ảo → chỉ `kho`; dòng 0 / âm được — khác phiếu xuất lẻ), sửa nháp, nháp
→ `cancelled` (giữ phiếu — khác Stock Entry nháp: xoá), phiếu không nháp chỉ sửa ghi chú, xoá chỉ nháp (KHÔNG lùi dãy số — như phiếu kho tay).
"""
from __future__ import annotations

import json
from decimal import Decimal

import frappe
from frappe.utils import cint, flt, now_datetime, nowdate

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import co_quyen, hien_tai
from nppsale.cong.sql import LoiCong
from nppsale.luat import kho_mua as K
from nppsale.luat import kho_tay as T
from nppsale.luat import kiem_ke as KK
from nppsale.thiet_lap.kho_mua import cai_dat_kho

from . import rpc

DT = KK.DT
DT_DONG = "NPP Kiem Ke Dong"
DT_SE = "Stock Entry"
DT_PC = "NPP Phieu Chi"
DAY_DCK = "DCK-.####"
BANG = "stock_entries"
BANG_DONG = "stock_entry_lines"
COT_BO = ("id", "org_id", "entry_code", "created_by", "created_at", "posted_at", "ref_order_ids", "tim_kd", "status", "type")
_GOI = "JOIN `tabSerial and Batch Bundle` sb ON sb.`name` = e.`parent` AND sb.`docstatus` = 1 AND sb.`is_cancelled` = 0"


def _chu(v) -> str | None:
	if v is None:
		return None
	return v if isinstance(v, str) else json.dumps(v)


def _vung_kho(vung: str | None, cd) -> str:
	return cd.kho_can_date if vung == "date" else cd.kho_ban


def _so(v):
	"""`(x)::numeric` khi trình duyệt gửi chữ — sai → 22P02 như Postgres."""
	if v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)):
		return v
	try:
		return float(str(v).strip())
	except ValueError:
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{v}"', http=400) from None


# ================================================================================================ đọc phiếu
def phieu(ten: str | None, khoa: bool = False) -> frappe._dict | None:
	"""Phiếu kiểm kê `ten` (`khoa` → `FOR UPDATE`) — dạng nguồn của cổng `stock_entries` (nppsale.rpc.kho_tay.nguon_phieu)."""
	if not ten or not isinstance(ten, str):
		return None
	r = frappe.db.sql(f"""SELECT `name`, `trang_thai`, `kho`, `duyet_luc`, `ghi_chu` FROM `tab{DT}` WHERE `name` = %s{' FOR UPDATE' if khoa else ''}""",
		ten, as_dict=True)
	if not r:
		return None
	x = r[0]
	return frappe._dict(dt=DT, name=x.name, docstatus={"posted": 1, "cancelled": 2}.get(x.trang_thai, 0), trang_thai=x.trang_thai or "draft",
		loai="stocktake", purpose=None, npp_loai=None, phieu_tra=None, kho=x.kho, kho_dich=None, is_return=0, duyet_luc=x.duyet_luc,
		ghi_chu=x.ghi_chu)


def hang_cua(ten: str | None, khoa: bool = False) -> set:
	"""Mặt hàng cần khoá Bin: mặt hàng các dòng ∪ mặt hàng của lô dòng trỏ (dòng có thể trỏ lô của mặt hàng khác — nppsale không kiểm). `khoa` → đọc
	CÓ KHOÁ (`LOCK IN SHARE MODE` — không lập ảnh chụp): khoá Bin bù của hàng mới đứng trước câu đọc thường đầu tiên (soát P4, PoC 1d)."""
	if not ten:
		return set()
	ra = set()
	for hang, hang_lo in frappe.db.sql(f"""SELECT d.`mat_hang`, b.`item` FROM `tab{DT_DONG}` d LEFT JOIN `tabBatch` b ON b.`name` = d.`lo`
			WHERE d.`parent` = %s AND d.`parenttype` = %s{' LOCK IN SHARE MODE' if khoa else ''}""", (ten, DT)):
		ra |= {x for x in (hang, hang_lo) if x}
	return ra


def _chuan_bi(p_entry_id=None, p_reason=None):
	"""Đọc trước khi khoá (cổng commit sau bước này): người gọi, cài đặt, mặt hàng của phiếu → frappe.local — câu ĐẦU của thân hàm là khoá Bin."""
	hien_tai()
	cai_dat_kho()
	ten = _chu(p_entry_id)
	frappe.local._npp_kk = (ten, hang_cua(ten))


def _da_chuan_bi(p_entry_id) -> tuple[str | None, set]:
	x = getattr(frappe.local, "_npp_kk", None)
	frappe.local._npp_kk = None  # dùng MỘT lần
	ten = _chu(p_entry_id)
	if x and x[0] == ten:
		return ten, x[1]
	return ten, hang_cua(ten)  # gọi nội bộ không qua cổng


# ================================================================================================ post_stock_adjustment
@rpc("post_stock_adjustment", ghi=True, chuan_bi=_chuan_bi)
def post_stock_adjustment(p_entry_id=None):
	from nppsale.rpc.xuat_hang import _khoa_bin

	nc = hien_tai()
	cd = cai_dat_kho()
	ten, hang = _da_chuan_bi(p_entry_id)
	_khoa_bin(hang, cd)  # câu ĐẦU (CFD-05, PoC 1d)
	if not nc.vai and not nc.bo_qua_rls:
		raise NppLoi(KK.FORBIDDEN_KHOA)  # `user_org_id()` NULL (tài khoản khoá / chưa gắn đơn vị) — TRƯỚC khi đọc phiếu
	x = phieu(ten, khoa=True)
	if x is None:
		raise NppLoi(KK.KHONG_THAY)
	moi = hang_cua(x.name, khoa=True) - set(hang)
	if moi:
		_khoa_bin(moi, cd)  # dòng đổi giữa bước chuẩn bị và khoá (sửa nháp đồng thời) — đọc mặt hàng có khoá: khoá bù vẫn trước ảnh chụp (soát P4)
	if x.trang_thai == "posted":
		raise KK.loi_da_duyet(x.name, x.duyet_luc)  # chốt idempotent (mig 123): bấm hai lần không cộng / trừ kho hai lần
	if x.trang_thai != "draft":
		raise KK.loi_sai_trang_thai(x.name, x.trang_thai)
	if not co_quyen(nc, "inventory.approve"):  # SAU các kiểm trạng thái (như nppsale)
		raise NppLoi(KK.FORBIDDEN_DUYET)
	doc = frappe.get_doc(DT, x.name)
	dong = _dong(doc)
	kho = _kho(dong, cd)
	kq = KK.duyet(dong, kho)
	tk_hut = tk_thua = dm = None
	if any(not b.nhap for b in kq.buoc):
		dm, tk_hut = _danh_muc_hao_hut(cd)
		if not tk_hut:
			raise NppLoi("CAI_DAT_THIEU: danh mục chi phí COGS_ADJ chưa gắn tài khoản và NPP Cai Dat chưa có tài khoản chi phí mặc định "
				"(tk_chi_phi_mac_dinh).")
	if any(b.nhap for b in kq.buoc):
		tk_thua = cd.get("tk_thua_kiem_ke")
		if not tk_thua:
			raise NppLoi("CAI_DAT_THIEU: NPP Cai Dat chưa có tài khoản thừa kiểm kê (tk_thua_kiem_ke).")
	luc = now_datetime()  # SAU khoá, đủ micro giây
	ngay, gio = luc.date(), luc.strftime("%H:%M:%S.%f")
	tat = sorted({b.lo for b in kq.buoc if b.lo and cint(frappe.db.get_value("Batch", b.lo, "disabled"))})
	for ma in tat:  # Batch tắt ("mọi trạng thái" của mig 123) — lõi chặn gói lô có lô tắt: mở tạm trong lượt, tắt lại sau khi ghi sổ
		frappe.db.set_value("Batch", ma, "disabled", 0, update_modified=False)
	pn = _lap_dck("Material Receipt", [b for b in kq.buoc if b.nhap], x.name, tk_thua, ngay, gio, kho, cd)
	px = _lap_dck("Material Issue", [b for b in kq.buoc if not b.nhap], x.name, tk_hut, ngay, gio, kho, cd)
	for ma in tat:
		frappe.db.set_value("Batch", ma, "disabled", 1, update_modified=False)
	pc = _lap_phieu_chi(x.name, kq.hut_gt, dm, px) if kq.hut_gt > 0 else None
	for d in doc.dong:
		if d.name in kq.dien:
			lo, k = kq.dien[d.name]
			d.lo = lo or d.lo
			d.kho = k or d.kho
	doc.update({"trang_thai": "posted", "duyet_luc": luc, "phieu_nhap_dc": pn, "phieu_xuat_dc": px, "phieu_chi_hao_hut": pc, "so_lo_cham": kq.cham,
		"sl_hao_hut": float(kq.hut_sl), "gia_tri_hao_hut": float(kq.hut_gt), "sl_thua": float(kq.thua_sl), "gia_tri_thua": float(kq.thua_gt)})
	doc.flags.ignore_permissions = True
	doc.save()
	return KK.ket_qua(kq, pc)


def _dong(doc) -> list[KK.DongKK]:
	tt = {h: frappe.db.get_value("Item", h, ["item_name", "has_batch_no"], as_dict=True) for h in {d.mat_hang for d in doc.dong if d.mat_hang}}
	ra = []
	for d in sorted(doc.dong, key=lambda r: r.idx):
		it = tt.get(d.mat_hang) or frappe._dict()
		ra.append(KK.DongKK(stt=d.idx, ten_dong=d.name, hang=d.mat_hang, ten=it.get("item_name") or d.mat_hang, co_lo=bool(cint(it.get("has_batch_no"))),
			lo=d.lo or None, kho=d.kho or None, chenh=K.so(flt(d.chenh_lech)), gia=K.so(flt(d.gia_von))))
	return ra


def _kho(dong: list[KK.DongKK], cd) -> KK.KhoKK:
	"""Tồn ĐỌC SAU khoá Bin (ảnh chụp mới — PoC 1d) ở hai kho NPP: lô thật = Σ gói lô chưa huỷ theo (lô, kho) — MỌI Batch của mặt hàng theo lô trên phiếu
	(kể cả Batch tắt / lô rỗng / lô chưa phát sinh) + lô dòng trỏ thẳng; giá vốn lô = bình quân phần nhập (cổng `batches`), lô rỗng →
	`npp_gia_von_lo_rong`; hàng không lô = Bin (tồn + giá định giá)."""
	kho2 = tuple(x for x in (cd.kho_ban, cd.kho_can_date) if x) or ("",)
	hang_lo = tuple(sorted({d.hang for d in dong if d.co_lo})) or ("",)
	lo_ro = tuple(sorted({d.lo for d in dong if d.lo})) or ("",)
	lo = {}
	for ma, hang, han, gia, rong, tao in frappe.db.sql(f"""SELECT b.`name`, b.`item`, b.`expiry_date`,
			(SELECT SUM(e.`stock_value_difference`) / NULLIF(SUM(e.`qty`), 0) FROM `tabSerial and Batch Entry` e {_GOI}
				WHERE e.`is_cancelled` = 0 AND e.`batch_no` = b.`name` AND e.`qty` > 0),
			b.`npp_gia_von_lo_rong`, b.`npp_kho_tao`
		FROM `tabBatch` b WHERE b.`item` IN %(h)s OR b.`name` IN %(l)s""", {"h": hang_lo, "l": lo_ro}):
		lo[ma] = KK.LoTT(ma=ma, hang=hang, han=han, gia=K.so(flt(gia if gia is not None else (rong or 0))), kho_tao=tao or None)
	ton_lo = {}
	if lo:
		for ma, k, t in frappe.db.sql(f"""SELECT e.`batch_no`, e.`warehouse`, SUM(e.`qty`) FROM `tabSerial and Batch Entry` e {_GOI}
				WHERE e.`is_cancelled` = 0 AND e.`batch_no` IN %(l)s AND e.`warehouse` IN %(k)s GROUP BY e.`batch_no`, e.`warehouse`""",
				{"l": tuple(lo), "k": kho2}):
			ton_lo[(ma, k)] = Decimal(str(round(flt(t), 6)))
	ton_ao, gia_ao = {}, {}
	hang_ao = tuple(sorted({d.hang for d in dong if not d.co_lo})) or ("",)
	for hang, k, t, g in frappe.db.sql("""SELECT `item_code`, `warehouse`, `actual_qty`, `valuation_rate` FROM `tabBin`
			WHERE `item_code` IN %(h)s AND `warehouse` IN %(k)s""", {"h": hang_ao, "k": kho2}):
		ton_ao[(hang, k)] = Decimal(str(round(flt(t), 6)))
		gia_ao[(hang, k)] = K.so(flt(g))
	return KK.KhoKK(lo, ton_lo, ton_ao, gia_ao, cd.kho_ban, cd.kho_can_date)


def _danh_muc_hao_hut(cd) -> tuple[str | None, str | None]:
	"""(danh mục, TK chênh lệch phiếu xuất hao hụt): danh mục `COGS_ADJ` → danh mục đầu theo mã → không có (nppsale `category_id` NULL); TK = TK của danh
	mục → `NPP Cai Dat.tk_chi_phi_mac_dinh` (BP §4.5 / §7.2 dòng 11)."""
	ds = frappe.get_all("NPP Danh Muc Chi Phi", fields=["name", "ma", "tai_khoan"])
	ten = KK.chon_danh_muc((r.name, r.ma) for r in ds)
	tk = next((r.tai_khoan for r in ds if r.name == ten), None) if ten else None
	return ten, tk or cd.get("tk_chi_phi_mac_dinh")


def _lap_dck(muc: str, buoc: list[KK.BuocKho], ten_kk: str, tk: str | None, ngay, gio, kho: KK.KhoKK, cd) -> str | None:
	"""MỘT phiếu `DCK-` (`dieu_chinh_kiem_ke`, `npp_kiem_ke` = phiếu) ghi sổ ngay: mỗi lượt cộng / trừ một dòng đơn vị kho, gói lô do app lập (hàng
	không lô: không gói). Phần thừa: giá = giá vốn hiện tại của lô nhận (lô ảo: giá định giá của Bin) — `set_basic_rate_manually`, giá 0 →
	`allow_zero_valuation_rate` (lô rỗng chưa có giá); phần hụt: lõi định giá theo lô (bình quân giá trị nhập của chính lô)."""
	from nppsale.rpc.goi_lo import gan_goi_lo, lap_goi_lo
	from nppsale.rpc.kho_tay import _dat_tim

	if not buoc:
		return None
	nhap = muc == "Material Receipt"
	se = frappe.new_doc(DT_SE)
	se.update({"naming_series": DAY_DCK, "stock_entry_type": muc, "purpose": muc, "company": cd.cong_ty, "posting_date": ngay, "posting_time": gio,
		"set_posting_time": 1, "npp_loai": KK.SE_LOAI, "npp_kiem_ke": ten_kk, "npp_ghi_chu": f"Điều chỉnh kiểm kê {ten_kk}"})
	for b in buoc:
		dv = frappe.db.get_value("Item", b.hang, "stock_uom")
		gia = kho.lo[b.lo].gia if b.lo else kho.gia_ao.get((b.hang, b.kho), Decimal(0))
		r = se.append("items", {"item_code": b.hang, "qty": float(b.sl), "uom": dv, "stock_uom": dv, "conversion_factor": 1, "transfer_qty": float(b.sl),
			"expense_account": tk, "allow_zero_valuation_rate": 1 if gia == 0 else 0, ("t_warehouse" if nhap else "s_warehouse"): b.kho})
		if nhap:
			r.update({"basic_rate": float(gia), "set_basic_rate_manually": 1})
		if b.lo:
			gan_goi_lo(r, lap_goi_lo("Inward" if nhap else "Outward", DT_SE, b.hang, b.kho, {b.lo: float(b.sl)}, ngay, gio, cd.cong_ty))
	se.flags.ignore_permissions = True
	se.insert()
	se.submit()
	frappe.local.message_log = []
	_dat_tim(se.name)
	return se.name


def _lap_phieu_chi(ten_kk: str, tien: Decimal, dm: str | None, px: str | None) -> str:
	"""`INSERT expenses (category, expense_date, amount, description, reference_code, source_type 'stocktake', source_id, created_by)` — người lập =
	người duyệt (owner của phiếu chi); ngày = hôm nay giờ VN (⚠K nhẹ: nppsale `CURRENT_DATE` UTC — §2.5); chưa trả; KHÔNG JE (chi phí đã ở phiếu xuất
	`DCK-`); số tiền khoá (controller `NPP Phieu Chi`)."""
	pc = frappe.get_doc({"doctype": DT_PC, "ngay_chi": nowdate(), "so_tien": float(tien), "danh_muc": dm, "dien_giai": KK.dien_giai_hao_hut(ten_kk),
		"so_tham_chieu": ten_kk, "nguon_loai": KK.NGUON_KIEM_KE, "kiem_ke": ten_kk, "da_tra": 0, "chung_tu_kho": px})
	pc.insert(ignore_permissions=True)
	return pc.name


# ================================================================================================ reject_stock_adjustment
@rpc("reject_stock_adjustment", ghi=True)
def reject_stock_adjustment(p_entry_id=None, p_reason=None):
	from nppsale.rpc.kho_tay import nguon_phieu

	nc = hien_tai()
	ten = _chu(p_entry_id)
	x = phieu(ten, khoa=True)
	khac = None if x is not None else nguon_phieu(ten, khoa=True)  # phiếu kho khác loại (Stock Entry / HĐ / PI) — nppsale `type <> 'stocktake'`
	if x is None and khac is None:
		raise NppLoi(KK.KHONG_THAY_TU_CHOI)
	if not nc.vai and not nc.bo_qua_rls:
		raise NppLoi(KK.KHAC_NPP_TU_CHOI, code="42501", http=403)  # `org_id IS DISTINCT FROM user_org_id()` — NULL khi tài khoản khoá
	if not co_quyen(nc, "inventory.approve"):
		raise NppLoi(KK.FORBIDDEN_TU_CHOI, code="42501", http=403)
	if x is None:
		raise NppLoi(KK.SAI_LOAI)
	if x.trang_thai == "cancelled":
		return False
	if x.trang_thai != "draft":
		raise NppLoi(KK.DA_DUYET_TU_CHOI)
	frappe.db.set_value(DT, x.name, {"trang_thai": "cancelled", "ghi_chu": KK.ghi_chu_tu_choi(x.ghi_chu, _chu(p_reason))})
	return True


# ================================================================================================ huỷ phiếu kiểm kê (cancel_stock_entry — §3.19)
def huy_nhap(x, ly_do: str | None) -> list[dict]:
	"""`cancel_stock_entry` trên phiếu kiểm kê NHÁP (nppsale bước 5 — không kiểm nguồn / loại): `cancelled` + nối "Huỷ phiếu: <lý do>" (lý do '' giữ
	rỗng) — KHÁC Stock Entry nháp (xoá): phiếu kiểm kê không submit, giữ được dòng "Đã huỷ" + ghi chú như nppsale."""
	frappe.db.set_value(DT, x.name, {"trang_thai": "cancelled", "ghi_chu": T.ghi_chu_huy(x.ghi_chu, ly_do)})
	return T.ket_qua_huy(True, False, 0)


# ================================================================================================ ghi thẳng phiếu kiểm kê nháp qua cổng (§4.5)
def _vung_vao(v, cot: str, null_duoc: bool) -> str | None:
	if v is None:
		if null_duoc:
			return None
		raise LoiCong("23502", f'null value in column "{cot}" of relation "{BANG}" violates not-null constraint', http=400)
	if v not in K.VUNG:
		rang = "stock_entries_dest_warehouse_zone_check" if null_duoc else "stock_entries_zone_chk"
		raise LoiCong("23514", f'new row for relation "{BANG}" violates check constraint "{rang}"', http=400)
	return v


def _ap_dau(doc, g: dict, cd) -> None:
	"""Cột nppsale của đầu phiếu kiểm kê → trường: `warehouse_zone` → `kho`, `notes` → `ghi_chu`; `dest_warehouse_zone` / `issue_reason` /
	`supplier_id` kiểm ràng buộc như nppsale rồi bỏ (phiếu kiểm kê không có — BP: cổng trả rỗng). Cột lạ → PGRST204."""
	from nppsale.rpc.kho_tay import _ncc_vao

	for k, v in g.items():
		if k in COT_BO:
			continue
		if k == "warehouse_zone":
			doc.kho = _vung_kho(_vung_vao(v, k, False), cd)
		elif k == "dest_warehouse_zone":
			_vung_vao(v, k, True)
		elif k == "issue_reason":
			pass
		elif k == "notes":
			doc.ghi_chu = _chu(v)
		elif k == "supplier_id":
			_ncc_vao(v)
		else:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{BANG}' in the schema cache", http=400)


def them_phieu(g: dict, cd) -> str:
	"""INSERT stock_entries `type stocktake` (đã qua trigger mig 170 + RLS ở nppsale.rpc.kho_tay.them_phieu): phiếu kiểm kê nháp."""
	doc = frappe.new_doc(DT)
	doc.trang_thai = "draft"
	doc.kho = cd.kho_ban  # `warehouse_zone` mặc định `sale` (mig 144)
	_ap_dau(doc, g, cd)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def gia_tri_cot(x, k: str, cd):
	"""Giá trị hiện tại của cột nppsale `k` trên phiếu kiểm kê (so `IS DISTINCT FROM` như trigger)."""
	from nppsale.cong.bang._chung import lay_org_id
	from nppsale.rpc.goi_lo import vung_cua_kho

	if k == "type":
		return "stocktake"
	if k == "org_id":
		return lay_org_id()
	if k == "entry_code":
		return x.name
	if k == "warehouse_zone":
		return vung_cua_kho(x.kho, cd)
	if k == "ref_order_ids":
		return []
	if k == "posted_at":
		return x.duyet_luc
	if k == "created_by":
		ow = frappe.db.get_value(DT, x.name, "owner")
		return None if ow in ("Administrator", "Guest") else ow
	return None


def sua_nhap(x, g: dict, cd) -> None:
	"""UPDATE nháp (sau kiểm trạng thái / loại ở nppsale.rpc.kho_tay.sua_phieu): cột đầu phiếu như lúc lập."""
	doc = frappe.get_doc(DT, x.name)
	_ap_dau(doc, g, cd)
	doc.flags.ignore_permissions = True
	doc.save()


def doi_trang_thai_huy(x, g: dict, cd) -> None:
	"""Lệnh cổng `draft → cancelled` (trigger mig 170 cho đúng chiều ấy): các cột khác của CÙNG lệnh ghi như sửa nháp rồi đổi trạng thái — không nối
	"Từ chối / Huỷ phiếu" vào ghi chú (khác RPC từ chối / huỷ phiếu kho)."""
	sua_nhap(x, {k: v for k, v in g.items() if k != "status"}, cd)
	frappe.db.set_value(DT, x.name, "trang_thai", "cancelled")


def sua_ghi_chu(x, v) -> None:
	frappe.db.set_value(DT, x.name, "ghi_chu", _chu(v))


def xoa(x) -> None:
	"""Xoá phiếu kiểm kê NHÁP (màn kiểm kê dọn phiếu khi chèn dòng hỏng — `delete().eq('status', 'draft')`): giữ số đếm dãy (như phiếu kho tay)."""
	from nppsale.rpc.kho_tay import xoa_nhap

	xoa_nhap(x.name, DT)


def _ap_dong(r, g: dict, moi: bool, cd) -> None:
	"""Cột nppsale của một dòng kiểm kê → `NPP Kiem Ke Dong`: `product_id` → `mat_hang`, `batch_id` (`<lô>::<vùng>` / `~<mã>::<vùng>`) → `lo` + `kho`,
	`unit_name` → `don_vi`, `quantity` → `chenh_lech` (cột `post_stock_adjustment` đọc), `unit_cost` → `gia_von`, `notes` → `ghi_chu`;
	`qty_in_base_uom` / `qty_in_transaction_uom` / `transaction_uom` / `conversion_factor_snapshot` kiểm kiểu rồi bỏ (cổng trả bằng chênh lệch /
	đơn vị / 1). Ràng buộc nppsale: NOT NULL `product_id` / `unit_name` / `quantity` / `qty_in_base_uom` / `unit_cost` → 23502; khoá ngoại sản phẩm / lô →
	23503."""
	from nppsale.rpc.don_hang import _dam_bao_uom

	def null(cot):
		raise LoiCong("23502", f'null value in column "{cot}" of relation "{BANG_DONG}" violates not-null constraint', http=400)

	def fk(ten):
		raise LoiCong("23503", f'insert or update on table "{BANG_DONG}" violates foreign key constraint "{ten}"', http=409)

	for k, v in g.items():
		if k in ("id", "entry_id"):
			continue
		if k == "product_id":
			if v is None:
				null(k)
			if not frappe.db.exists("Item", v):
				fk("stock_entry_lines_product_id_fkey")
			r.mat_hang = v
		elif k == "batch_id":
			ma, vung, ao = KK.tach_id_lo(_chu(v))
			if ma is None:
				r.lo = r.kho = None
				continue
			if vung is not None and vung not in K.VUNG:
				fk("stock_entry_lines_batch_id_fkey")
			if ao:
				if not frappe.db.get_value("Item", ma, "name") or cint(frappe.db.get_value("Item", ma, "has_batch_no")):
					fk("stock_entry_lines_batch_id_fkey")
				r.lo, r.kho = None, _vung_kho(vung or "sale", cd)
			else:
				if not frappe.db.exists("Batch", ma):
					fk("stock_entry_lines_batch_id_fkey")
				r.lo, r.kho = ma, (_vung_kho(vung, cd) if vung else None)
		elif k == "unit_name":
			if v is None:
				null(k)
			if v:
				_dam_bao_uom(v)
			r.don_vi = v or None
		elif k == "quantity":
			if v is None:
				null(k)
			r.chenh_lech = _so(v)
		elif k in ("qty_in_base_uom", "unit_cost"):
			if v is None:
				null(k)
			v = _so(v)
			if k == "unit_cost":
				r.gia_von = v
		elif k in ("qty_in_transaction_uom", "conversion_factor_snapshot"):
			_so(v)
		elif k == "transaction_uom":
			pass
		elif k == "notes":
			r.ghi_chu = _chu(v)
		else:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{BANG_DONG}' in the schema cache", http=400)
	if moi:
		for cot in ("product_id", "unit_name", "quantity", "qty_in_base_uom"):
			if cot not in g:
				null(cot)


def _luu(doc) -> None:
	doc.flags.ignore_permissions = True
	doc.save()


def them_dong(doc, ds: list[dict]) -> list:
	"""INSERT stock_entry_lines của phiếu kiểm kê nháp (màn kiểm kê chèn cả bộ dòng MỘT lệnh) → các dòng mới (tên có sau khi lưu)."""
	cd = cai_dat_kho()
	moi = []
	for g in ds:
		r = doc.append("dong", {})
		_ap_dong(r, g, True, cd)
		moi.append(r)
	_luu(doc)
	return moi


def sua_dong(doc, ten_dong: list[str], g: dict) -> None:
	cd = cai_dat_kho()
	for ten in ten_dong:
		_ap_dong(next(x for x in doc.dong if x.name == ten), g, False, cd)
	_luu(doc)


def xoa_dong(doc, ten_dong: list[str]) -> None:
	doc.set("dong", [x for x in doc.dong if x.name not in ten_dong])
	for i, r in enumerate(doc.dong, 1):
		r.idx = i
	_luu(doc)
