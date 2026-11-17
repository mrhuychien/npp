"""LÔ + KHO CẬN DATE (P4 — mốc M5; đặc tả kho_mua §2.7, §3.20, §4.6, §7.2 #7 / #27, §7.3 điểm 6 / 8 / 20 / 22 / 37; blueprint 02 §4.4.0, §6.1 dòng
`batches`). Câu lỗi nguyên văn ở nppsale/luat/lo_kho.py (hàm Postgres nguồn ở scratchpad kho_mua/src/<tên>.sql).

- `refresh_warehouse_zones(p_org_id)` (mig 028 / 166 / 140): khoá Bin của mặt hàng có lô cần chuyển (câu ĐẦU — CFD-05 "chuyển kho date tự động") →
  người đăng nhập rà NPP khác / tài khoản khoá (`user_org_id()` NULL) → `ORG_MISMATCH` 42501 (KHÔNG kiểm vai — §7.3 điểm 22: NVBH gọi được như nppsale)
  → lô CÓ TỒN ở kho bán, có hạn, hạn ≤ hôm nay VN + ngưỡng (lô đã tắt cũng chuyển — nppsale không lọc `status`) → MỘT phiếu `CKL-`
  `chuyen_date_tu_dong` chuyển TOÀN BỘ tồn kho bán của các lô ấy sang kho cận date, `Batch.npp_chuyen_vung_luc` = lúc rà (không ghi người — như
  nppsale; ⚠K §7.2 #7: nppsale lật cờ vùng tại chỗ, không phiếu, thẻ kho đổi vùng hồi tố) → trả số lô. Không lô nào → không phiếu, 0.
  Administrator (việc nền — "không người đăng nhập" của nppsale) không kiểm NPP: rà NPP khác ra 0 (một site một NPP).
- `ra_soat_kho_date()` — việc đêm 01:00 giờ VN (hooks.py; mới — bàn bạc dòng 209, nppsale không có lịch tự chạy): cùng RPC qua khuôn ghi kho
  `_goi_co_khoa` (chuẩn bị → COMMIT → khoá Bin → thân hàm, thử lại khi deadlock).
- Ghi thẳng bảng cổng `batches` (§4.6 — trigger mig 170 `_trg_khoa_ghi_thang_lo` + mig 028 `batches_auto_zone`, RLS "Owner/Warehouse can manage batches"):
  · INSERT: chỉ lô RỖNG (có tồn → SO_KHO_KHOA — trước RLS như trigger BEFORE) → vai owner / warehouse (42501) → NOT NULL / CHECK vùng / khoá ngoại mặt
    hàng → mặt hàng không lô → mã trùng (`LO_TRUNG_MA`) → Batch: mã = `name`, kho tạo (`npp_kho_tao`) = kho của vùng, vùng bán mà hạn trong ngưỡng → kho
    cận date (trigger INSERT), ngày nhận = lúc tạo, giá vốn lô rỗng = `unit_cost`, ngày SX trống giữ trống.
  · UPDATE (vai ngoài owner / warehouse → 0 dòng, RLS USING): thứ tự trigger (tồn → giá khi Σ tồn mọi kho ≠ 0 — §7.3 điểm 37 → mặt hàng) → `batch_code`
    đổi → `doi_ma_lo` (`rename_doc` ép — PoC 8; đổi cả hai kho) → ngày SX / hạn / vị trí / giá vốn lô rỗng → kho date: lệnh có khoá `expires_at` (kể cả
    hạn gửi lại không đổi — §4.6 S7, V82a) mà hạn trong ngưỡng → TOÀN BỘ tồn kho bán của lô sang kho date bằng `CKL-` `chuyen_date_tu_dong` trong cùng
    lượt (⚠K: một Batch cho hai kho — sửa hạn ở dòng `::date` cũng kéo tồn kho bán, V82b), không ghi dấu chuyển vùng (trigger không ghi
    `zone_moved_at`); lô chưa phát sinh chỉ đổi kho tạo; `warehouse_zone` đổi → `CKL-` `chuyen_kho` toàn bộ tồn của DÒNG sang kho kia (+ dấu chuyển vùng
    lúc / người — ⚠K nppsale lật cột thẳng, màn đã gỡ nút), vào kho bán mà lô gần hạn → `HANG_GAN_HAN`. Trả id dòng SAU khi ghi (`<mã mới>::<vùng mới>`)
    để cổng đọc lại đúng dòng.
  · DELETE (vai khác → 0 dòng): Σ tồn mọi kho ≠ 0 → SO_KHO_KHOA (câu nppsale, số `so6`); đã có gói lô (kể cả đã huỷ) → 23503 khoá ngoại của nppsale
    (§7.3 điểm 20); còn lại xoá Batch.
  · Ghi lên lô ảo (`~<mã hàng>::<vùng>` của hàng không lô) → `SO_KHO_KHOA: mặt hàng này không quản lý theo lô.`
  · Sửa / xoá theo khuôn ghi kho (BP §4.4.0): cổng đọc dòng khớp bộ lọc + mặt hàng (`chuan_bi_ghi`) → COMMIT → khoá Bin là câu đầu của bộ ghi
    (`nppsale.cong.api._ghi_kho`).
- `hoan_chuyen_date` — §7.3 điểm 8 (đề xuất): huỷ phiếu nhập / phiếu nhập kho tay mà lô đã bị rà sang kho date (phần thiếu ở kho nhận CHỈ do phiếu
  `CKL-` `chuyen_date_tu_dong`, lô không động gì khác) → huỷ trước các phiếu ấy (hàng về kho nhận) rồi chứng từ mới huỷ được — nppsale lật cờ vùng
  nên huỷ được. Phiếu tự động chở cả lô KHÁC (rà soát gộp nhiều lô một phiếu) → huỷ phiếu rồi lập lại phần lô khác CÙNG giờ ghi sổ, chỉ khi các lô ấy
  không phát sinh gì từ phiếu ấy về sau; không thì lô vẫn chặn (`HANG_DA_XUAT` / `ALREADY_ISSUED`).
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import frappe
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, nowdate

from nppsale.cong.bang._chung import gio_vao, lay_org_id
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai
from nppsale.luat import kho_mua as K
from nppsale.luat import kho_tay as T
from nppsale.luat import lo_kho as L
from nppsale.luat.tim import khoa_tim_ds
from nppsale.thiet_lap.kho_mua import cai_dat_kho

from . import rpc

DT = "Stock Entry"
EPS = 1e-6


def _chu(v) -> str | None:
	if v is None:
		return None
	return v if isinstance(v, str) else json.dumps(v)


def _khoa_bin(hang, cd) -> None:
	from nppsale.rpc.xuat_hang import _khoa_bin as khoa

	khoa(hang, cd)


def _ton(lo: str) -> dict[str, float]:
	"""{kho: tồn} của lô theo gói lô chưa huỷ (mọi kho)."""
	return {k: flt(t) for k, t in frappe.db.sql("""SELECT e.`warehouse`, SUM(e.`qty`) FROM `tabSerial and Batch Entry` e
		JOIN `tabSerial and Batch Bundle` sb ON sb.`name` = e.`parent` AND sb.`docstatus` = 1 AND sb.`is_cancelled` = 0
		WHERE e.`is_cancelled` = 0 AND e.`batch_no` = %s GROUP BY e.`warehouse`""", lo)}


def _co_goi_lo(lo: str) -> bool:
	"""Lô đã có dòng gói lô (mọi trạng thái — gói đã huỷ vẫn giữ dòng như phiếu kho đã huỷ của nppsale giữ `stock_entry_lines`)."""
	return bool(frappe.db.sql("SELECT 1 FROM `tabSerial and Batch Entry` WHERE `batch_no` = %s LIMIT 1", lo))


def lap_ckl(dong: list[tuple[str, str, float]], tu: str, den: str, cd, *, loai: str, ghi_chu: str | None, luc=None) -> str:
	"""Phiếu chuyển kho `CKL-.####` ghi sổ ngay (Material Transfer): mỗi lô MỘT dòng (đơn vị kho, hệ số 1), gói lô Outward ở kho nguồn — lõi tự lập
	phía nhận cùng Batch, GIỮ giá lô (đo M4 — §7.1 #13); không TK chênh lệch (chuyển kho — lõi điền); giờ ghi sổ = lúc gọi (đủ micro giây, lấy SAU
	khoá) hoặc `luc` = (ngày, giờ) khi lập lại phiếu cũ. `dong`: [(mã lô, mặt hàng, SL cơ sở)]."""
	from nppsale.rpc.goi_lo import gan_goi_lo, lap_goi_lo
	from nppsale.rpc.kho_tay import _dat_tim

	if luc is None:
		x = now_datetime()
		ngay, gio = x.date(), x.strftime("%H:%M:%S.%f")
	else:
		ngay, gio = luc
	# lô đã tắt (≈ `status 'cancelled'`) còn tồn: nppsale lật vùng không xét trạng thái — lõi chặn gói lô xuất có lô tắt
	# (`stock_controller.validate_outward_bundle_batches`) → mở tạm trong lượt, tắt lại sau khi ghi sổ
	tat = [ma for ma, _h, _sl in dong if cint(frappe.db.get_value("Batch", ma, "disabled"))]
	for ma in tat:
		frappe.db.set_value("Batch", ma, "disabled", 0, update_modified=False)
	se = frappe.new_doc(DT)
	se.update({"naming_series": "CKL-.####", "stock_entry_type": "Material Transfer", "purpose": "Material Transfer", "company": cd.cong_ty,
		"posting_date": ngay, "posting_time": gio, "set_posting_time": 1, "npp_loai": loai, "from_warehouse": tu, "to_warehouse": den,
		"npp_ghi_chu": ghi_chu})
	for ma, hang, sl in dong:
		dv = frappe.db.get_value("Item", hang, "stock_uom")
		r = se.append("items", {"item_code": hang, "qty": float(sl), "uom": dv, "stock_uom": dv, "conversion_factor": 1, "transfer_qty": float(sl),
			"s_warehouse": tu, "t_warehouse": den})
		gan_goi_lo(r, lap_goi_lo("Outward", DT, hang, tu, {ma: float(sl)}, ngay, gio, cd.cong_ty))
	se.flags.ignore_permissions = True
	se.insert()
	se.submit()
	frappe.local.message_log = []
	for ma in tat:
		frappe.db.set_value("Batch", ma, "disabled", 1, update_modified=False)
	_dat_tim(se.name)
	return se.name


# ================================================================================================ refresh_warehouse_zones (§3.20)
def _lo_ban(cd, hom_nay=None) -> list[L.LoBan]:
	"""Lô cần rà: tồn > 0 ở KHO BÁN (gói lô chưa huỷ), có hạn, hạn ≤ hôm nay VN + ngưỡng — thứ tự mặt hàng, mã lô."""
	hn = hom_nay or getdate(nowdate())
	chot = frappe.utils.add_days(hn, K.nguong(cd.get("nguong")))
	ds = [L.LoBan(ma=ma, hang=hang, ton=Decimal(str(round(flt(ton), 6))), han=han) for ma, hang, ton, han in frappe.db.sql("""
		SELECT e.`batch_no`, b.`item`, SUM(e.`qty`), b.`expiry_date`
		FROM `tabSerial and Batch Entry` e
		JOIN `tabSerial and Batch Bundle` sb ON sb.`name` = e.`parent` AND sb.`docstatus` = 1 AND sb.`is_cancelled` = 0
		JOIN `tabBatch` b ON b.`name` = e.`batch_no`
		WHERE e.`is_cancelled` = 0 AND e.`warehouse` = %(kho)s AND b.`expiry_date` IS NOT NULL AND b.`expiry_date` <= %(chot)s
		GROUP BY e.`batch_no`, b.`item`, b.`expiry_date`
		HAVING SUM(e.`qty`) > 0.0000005""", {"kho": cd.kho_ban, "chot": chot})]
	return L.can_ra_soat(ds, hn, cd.get("nguong"))


def _chuan_bi_ra_soat(p_org_id=None):
	"""Đọc trước khi khoá (cổng commit sau bước này): người gọi, cài đặt, mặt hàng của các lô cần rà."""
	hien_tai()
	cd = cai_dat_kho()
	frappe.local._npp_rs = {x.hang for x in _lo_ban(cd)}


@rpc("refresh_warehouse_zones", ghi=True, chuan_bi=_chuan_bi_ra_soat)
def refresh_warehouse_zones(p_org_id=None):
	nc = hien_tai()
	cd = cai_dat_kho()
	hang = getattr(frappe.local, "_npp_rs", None)
	frappe.local._npp_rs = None  # dùng MỘT lần
	if hang is None:  # gọi nội bộ không qua cổng
		hang = {x.hang for x in _lo_ban(cd)}
	_khoa_bin(hang, cd)  # câu ĐẦU
	org = _chu(p_org_id)
	if not nc.bo_qua_rls and (not nc.vai or org != lay_org_id()):
		# `auth.uid() IS NOT NULL AND p_org_id IS DISTINCT FROM user_org_id()` — tài khoản khoá: user_org_id() NULL ⇒ cũng ORG_MISMATCH
		raise NppLoi(L.ORG_MISMATCH_RA_SOAT, code="42501", http=403)
	if org != lay_org_id():
		return 0  # không người đăng nhập rà NPP khác: một site một NPP — `UPDATE batches … WHERE org_id = p_org_id` ra 0 dòng
	return ra_soat(cd, hang)


def ra_soat(cd, da_khoa: set) -> int:
	"""Thân rà soát (Bin của `da_khoa` đã khoá): đọc lại lô SAU khoá; mặt hàng mới lọt vào giữa hai bước → khoá thêm."""
	lo = _lo_ban(cd)
	moi = {x.hang for x in lo} - set(da_khoa)
	if moi:
		_khoa_bin(moi, cd)
	if not lo:
		return 0
	lap_ckl([(x.ma, x.hang, x.ton) for x in lo], cd.kho_ban, cd.kho_can_date, cd, loai=T.SE_CHUYEN_DATE, ghi_chu=L.ghi_chu_ra_soat(cd.get("nguong")))
	luc = now_datetime()
	for x in lo:
		frappe.db.set_value("Batch", x.ma, "npp_chuyen_vung_luc", luc, update_modified=False)  # `zone_moved_at = now()`, người không ghi
	return len(lo)


def ra_soat_kho_date():
	"""Việc đêm 01:00 giờ VN (hooks.py `scheduler_events`): `refresh_warehouse_zones` cho NPP của site dưới Administrator — cùng khuôn ghi kho của
	cổng RPC (`_goi_co_khoa`: chuẩn bị → COMMIT → khoá Bin → thân hàm; deadlock → thử lại). Lỗi → Error Log (lượt đêm sau chạy lại)."""
	from nppsale import rpc as R
	from nppsale.cong.api import _goi_co_khoa

	R.nap()
	kq = _goi_co_khoa("refresh_warehouse_zones", R.DANG_KY["refresh_warehouse_zones"], {"p_org_id": lay_org_id()}, None, "npp_cong_rpc")
	if "error" in kq:
		frappe.log_error(title="Rà soát kho date (việc đêm)", message=json.dumps(kq["error"], ensure_ascii=False, default=str))
		return None
	return kq.get("data")


# ================================================================================================ cổng `batches` — ghi (§4.6)
def _tach(ten: str) -> tuple[str, str]:
	"""`<lô>::<vùng>` → (lô, vùng); lô ảo `~<mã hàng>::<vùng>` giữ dấu `~`."""
	lo, _, vung = ten.rpartition("::")
	return lo, vung


def _hang_cua_ids(ids) -> set:
	hang = set()
	for ten in ids or []:
		lo, _ = _tach(ten)
		if lo.startswith("~"):
			hang.add(lo[1:])
		elif lo:
			x = frappe.db.get_value("Batch", lo, "item")
			if x:
				hang.add(x)
	return hang


def chuan_bi_ghi(hanh_dong: str, gia_tri, ids: list, nc) -> None:
	"""Bước đọc của khuôn ghi kho (cổng gọi TRƯỚC khi commit): cài đặt + mặt hàng của các lô bị sửa / xoá → frappe.local (dùng một lần)."""
	cai_dat_kho()
	frappe.local._npp_lo_ghi = (tuple(ids or ()), _hang_cua_ids(ids))


def _khoa_lo(ids, cd) -> None:
	x = getattr(frappe.local, "_npp_lo_ghi", None)
	frappe.local._npp_lo_ghi = None
	hang = x[1] if x and x[0] == tuple(ids) else _hang_cua_ids(ids)  # gọi nội bộ không qua cổng: đọc trước khoá
	_khoa_bin(hang, cd)


def _dong_hien(ids, nc) -> dict[str, dict]:
	"""Dòng cổng HIỆN TẠI của các id (giá trị so `IS DISTINCT FROM` — cùng số màn đang thấy; giá vốn đọc không che)."""
	from nppsale.cong.truy_van import doc

	if not ids:
		return {}
	ra = doc({"bang": "batches", "select": "*", "loc": [{"op": "in", "cot": "id", "gt": list(ids)}]},
		NguCanh(user="Administrator", vai=None, bo_qua_rls=True))["data"] or []
	return {r["id"]: r for r in ra}


def _doi_kieu(g: dict) -> dict:
	"""Tải trọng → giá trị so / ghi (ép kiểu như PostgREST: số sai → 22P02, ngày sai → 22007). Cột lạ → PGRST204."""
	moi = {}
	for k, v in g.items():
		if k not in L.COT_LO:
			raise L.loi_cot_la(k)
		if k in ("qty_initial", "qty_on_hand", "unit_cost"):
			moi[k] = T.ep_so(v)
		elif k in ("manufactured_at", "expires_at"):
			moi[k] = T.ep_ngay(v)  # NULL / '' → NULL (NOT NULL của `expires_at` kiểm sau), sai → 22007
		elif k in ("received_at", "zone_moved_at", "created_at"):
			moi[k] = _gio(v)
		else:
			moi[k] = v
	return moi


def _gio(v):
	"""`::timestamptz`: NULL → None, chữ sai (kể cả '') → 22007; có múi giờ → giờ site (không múi giờ — như Frappe lưu)."""
	x = T.ep_gio(v)
	return gio_vao(x) if x is not None else None


def _cu(r: dict) -> dict:
	"""Dòng cổng → giá trị cùng kiểu với `_doi_kieu` (để so)."""
	return {**r, "manufactured_at": getdate(r["manufactured_at"]) if r.get("manufactured_at") else None,
		"expires_at": getdate(r["expires_at"]) if r.get("expires_at") else None,
		**{k: _gio(r.get(k)) for k in ("received_at", "zone_moved_at", "created_at")}}


def them_lo(ds: list[dict], nc) -> list[str]:
	"""INSERT batches (màn `/inventory/batches/new` — lô RỖNG): trigger (lô có tồn) → RLS (vai / NPP) → NOT NULL / CHECK → khoá ngoại mặt hàng → mặt
	hàng không lô → mã trùng → Batch. Trả id `<lô>::<vùng của kho tạo>` theo thứ tự gửi."""
	from nppsale.cong.bang._chung import kiem_org
	from nppsale.rpc.goi_lo import kho_nhan_lo, vung_cua_kho

	cd = cai_dat_kho()
	ra = []
	for g in ds:
		g = _doi_kieu(dict(g or {}))
		L.kiem_them(g)  # trigger BEFORE INSERT — trước RLS
		if nc.vai not in K.VAI_KHO_TAY and not nc.bo_qua_rls:
			raise L.loi_rls()
		kiem_org(g, L.BANG)  # NPP khác: WITH CHECK của RLS (42501)
		for cot in L.KHONG_NULL:
			if cot == "warehouse_zone":
				continue
			if g.get(cot) is None or (cot == "batch_code" and g.get(cot) == ""):
				raise L.loi_khong_null(cot)
		vung = L.vung_hop_le(g["warehouse_zone"]) if "warehouse_zone" in g else "sale"
		for cot in L.COT_LOI_GIU:
			if cot == "received_at":
				continue
			v = g.get(cot)
			if v is not None and not (cot == "status" and v == "available"):
				raise NppLoi(L.KHONG_SUA_TRUONG)
		hang = g["product_id"]
		it = frappe.db.get_value("Item", hang, ["has_batch_no", "has_expiry_date"], as_dict=True)
		if not it:
			raise L.loi_hang()
		if not cint(it.has_batch_no):
			raise NppLoi(L.KHONG_LO)
		ma = str(g["batch_code"])
		if frappe.db.exists("Batch", ma):
			raise L.loi_lo_trung(ma)
		han = T.han_lo(g["expires_at"], bool(cint(it.has_expiry_date)))
		kho = kho_nhan_lo(vung, han, cd)  # trigger `batches_auto_zone` lúc chèn (ngày VN)
		nsx = g.get("manufactured_at")
		b = frappe.get_doc({"doctype": "Batch", "batch_id": ma, "item": hang, "manufacturing_date": nsx, "expiry_date": han,
			"npp_vi_tri": g.get("location"), "npp_ngay_nhap": g.get("received_at") or now_datetime(), "npp_kho_tao": kho,
			"npp_gia_von_lo_rong": float(g.get("unit_cost") or 0), "npp_tim_kd": khoa_tim_ds(ma)})
		try:
			b.insert(ignore_permissions=True)
		except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
			raise L.loi_lo_trung(ma) from None
		if not nsx:  # lõi tự điền ngày SX hôm nay (`set_manufacturing_date`) — nppsale giữ NULL
			frappe.db.set_value("Batch", b.name, "manufacturing_date", None, update_modified=False)
		ra.append(f"{b.name}::{vung_cua_kho(kho, cd)}")
	return ra


def doi_ma_lo(cu: str, moi: str, nc) -> str:
	"""Đổi mã lô (BP §4.4.0, PoC 8): kiểm vai (owner / warehouse) → mã mới đã là lô KHÁC → `LO_TRUNG_MA` (§7.3 điểm 6) → `rename_doc` ép
	(`force` bỏ chặn `allow_rename`, `ignore_permissions` vì vai NPP không có quyền ghi Batch — §2.10) — đổi mọi Link trỏ lô (gói lô, sổ…) ở cả hai
	kho; khoá tìm theo mã mới. Lõi xoá cache toàn site mỗi lần đổi (`rename_doc.py:211–212`); không dựng lại tìm kiếm toàn cục."""
	if nc.vai not in K.VAI_KHO_TAY and not nc.bo_qua_rls:
		raise L.loi_rls()
	if moi == cu:
		return cu
	co = frappe.db.exists("Batch", moi)  # collation không phân biệt hoa thường — đổi hoa / thường của chính lô này vẫn được
	if co and co != cu:
		raise L.loi_lo_trung(moi)
	from frappe.model.rename_doc import rename_doc  # `frappe.rename_doc` không nhận `ignore_permissions`

	ten = rename_doc(doctype="Batch", old=cu, new=moi, force=True, ignore_permissions=True, rebuild_search=False, show_alert=False)
	frappe.db.set_value("Batch", ten, "npp_tim_kd", khoa_tim_ds(ten), update_modified=False)
	return ten


def sua_lo(gia_tri: dict, ids: list[str], nc) -> list[str]:
	"""UPDATE batches — xem đầu tệp. Trả id dòng sau khi ghi (mã mới, vùng mới) để cổng đọc lại."""
	from nppsale.rpc.goi_lo import kho_cua_vung, vung_cua_kho
	from nppsale.rpc.phieu_nhap import _nv

	moi = _doi_kieu(dict(gia_tri or {}))
	if nc.vai not in K.VAI_KHO_TAY and not nc.bo_qua_rls:
		return []  # RLS USING: dòng không thuộc quyền ghi bị lọc — 0 dòng, không lỗi
	cd = cai_dat_kho()
	_khoa_lo(ids, cd)  # câu ĐẦU (khuôn ghi kho)
	hien = _dong_hien(ids, nc)
	theo_lo: dict[str, list] = {}
	for ten in ids:
		if ten not in hien:
			continue  # dòng đã đổi giữa bước đọc và khoá (đổi mã / chuyển hết)
		lo, _ = _tach(ten)
		if lo.startswith("~"):
			raise NppLoi(L.KHONG_LO)
		theo_lo.setdefault(lo, []).append(hien[ten])
	hn = getdate(nowdate())
	ng = cd.get("nguong")
	ra = []
	for lo, dong in theo_lo.items():
		ton = _ton(lo)
		tong = sum(ton.values())
		for r in dong:
			L.kiem_sua(_cu(r), moi, Decimal(str(round(tong, 6))))
		if "batch_code" in moi and moi["batch_code"] in (None, ""):
			raise L.loi_khong_null("batch_code")
		if "expires_at" in moi and moi["expires_at"] is None:
			raise L.loi_khong_null("expires_at")
		if "warehouse_zone" in moi:
			L.vung_hop_le(moi["warehouse_zone"])
		b = frappe.db.get_value("Batch", lo, ["name", "item", "expiry_date", "npp_kho_tao"], as_dict=True)
		it = frappe.db.get_value("Item", b.item, ["item_name", "has_expiry_date"], as_dict=True) or frappe._dict()
		# ---- mã lô
		ten = doi_ma_lo(lo, str(moi["batch_code"]), nc) if "batch_code" in moi and moi["batch_code"] != lo else lo
		# ---- trường của Batch (một Batch cho cả hai kho — ⚠K §7.2 #27)
		dat = {}
		if "manufactured_at" in moi:
			dat["manufacturing_date"] = moi["manufactured_at"]
		if "expires_at" in moi:
			dat["expiry_date"] = T.han_lo(moi["expires_at"], bool(cint(it.has_expiry_date)))
		if "location" in moi:
			dat["npp_vi_tri"] = moi["location"]
		if "unit_cost" in moi:
			dat["npp_gia_von_lo_rong"] = float(moi["unit_cost"] or 0)  # giá cổng đọc từ gói lô khi lô đã nhập — số hiện ra không đổi (§7.3 điểm 37)
		if dat:
			frappe.db.set_value("Batch", ten, dat)
		han = dat.get("expiry_date", b.expiry_date) if "expires_at" in moi else b.expiry_date
		# ---- vùng: từng dòng được sửa, rồi luật kho date của cả lô. Lô "chưa phát sinh" (không dòng gói lô nào CÒN hiệu lực — cổng dựng một dòng ở
		# `npp_kho_tao`): chỉ đổi kho tạo
		rong = not ton
		vao_ban = False
		tay, tu_dong = [], []  # chuyển tay (đổi `warehouse_zone`) / tự động (trigger hạn)
		dich_dong = {}
		da_ra_ban = 0.0
		for r in dong:
			vung = r["warehouse_zone"]
			dich = L.vung_sau_sua(vung, moi, han, hn, ng)
			dich_dong[r["id"]] = dich
			if dich == vung:
				continue
			if dich == "sale":
				vao_ban = True
			if rong:
				frappe.db.set_value("Batch", ten, "npp_kho_tao", kho_cua_vung(dich, cd), update_modified=False)
				continue
			sl = flt(ton.get(kho_cua_vung(vung, cd)))
			if sl <= EPS:
				continue
			tu_tay = "warehouse_zone" in moi and moi["warehouse_zone"] != vung
			(tay if tu_tay else tu_dong).append((vung, dich, sl))
			if vung == "sale":
				da_ra_ban += sl
		if vao_ban and L.can_date(han, hn, ng):
			raise T.loi_hang_gan_han(it.item_name or b.item, ten, han, K.nguong(ng))
		if "expires_at" in moi and L.can_date(han, hn, ng) and not rong:
			con_ban = flt(ton.get(cd.kho_ban)) - da_ra_ban
			if con_ban > EPS:
				tu_dong.append(("sale", "date", con_ban))
		for vung, dich, sl in tay:
			lap_ckl([(ten, b.item, sl)], kho_cua_vung(vung, cd), kho_cua_vung(dich, cd), cd, loai=T.SE_CHUYEN,
				ghi_chu=L.ghi_chu_doi_vung(ten, dich))
			frappe.db.set_value("Batch", ten, {"npp_chuyen_vung_luc": now_datetime(), "npp_chuyen_vung_boi": _nv(nc)}, update_modified=False)
		gop = sum(sl for _v, _d, sl in tu_dong)
		if gop > EPS:  # trigger `UPDATE OF expires_at`: lật cả dòng lô, không ghi `zone_moved_at` → phiếu tự động, không dấu chuyển vùng
			lap_ckl([(ten, b.item, gop)], cd.kho_ban, cd.kho_can_date, cd, loai=T.SE_CHUYEN_DATE, ghi_chu=L.ghi_chu_doi_han(ten, ng))
		# ---- id sau khi ghi: dòng ở vùng đích nếu có (tồn đã sang / lô rỗng đổi kho tạo), không thì dòng cũ (mã mới)
		con = _ton(ten)
		kho_tao = frappe.db.get_value("Batch", ten, "npp_kho_tao") or cd.kho_ban
		for r in dong:
			dich = dich_dong[r["id"]]
			co_dich = (vung_cua_kho(kho_tao, cd) == dich) if rong else kho_cua_vung(dich, cd) in con
			ra.append(f"{ten}::{dich if co_dich else r['warehouse_zone']}")
	return list(dict.fromkeys(ra))


def xoa_lo(ids: list[str], nc) -> list[str]:
	"""DELETE batches — Σ tồn mọi kho ≠ 0 → SO_KHO_KHOA; đã có gói lô → 23503; lô ảo → SO_KHO_KHOA. Trả các id đã xoá."""
	if nc.vai not in K.VAI_KHO_TAY and not nc.bo_qua_rls:
		return []
	cd = cai_dat_kho()
	_khoa_lo(ids, cd)  # câu ĐẦU (khuôn ghi kho)
	ra, da = [], set()
	for ten in ids:
		lo, _ = _tach(ten)
		if lo.startswith("~"):
			raise NppLoi(L.KHONG_LO)
		if lo in da:
			ra.append(ten)
			continue
		if not frappe.db.exists("Batch", lo):
			continue
		tong = sum(_ton(lo).values())
		if abs(tong) > EPS:
			raise L.loi_xoa_con_ton(Decimal(str(round(tong, 6))))
		if _co_goi_lo(lo):
			raise L.loi_xoa_co_so_kho()
		try:
			frappe.delete_doc("Batch", lo, ignore_permissions=True)
		except frappe.LinkExistsError:
			raise L.loi_xoa_co_so_kho() from None
		da.add(lo)
		ra.append(ten)
	return ra


# ================================================================================================ §7.3 điểm 8 — lô đã rà sang kho date
def _phat_sinh(lo: str) -> list[tuple]:
	"""Mọi dòng gói lô CHƯA huỷ của lô, gộp theo (chứng từ, kho): [(voucher_type, voucher_no, kho, SL có dấu, lúc ghi sổ)]."""
	return frappe.db.sql("""SELECT e.`voucher_type`, e.`voucher_no`, e.`warehouse`, SUM(e.`qty`), MIN(e.`posting_datetime`)
		FROM `tabSerial and Batch Entry` e
		JOIN `tabSerial and Batch Bundle` sb ON sb.`name` = e.`parent` AND sb.`docstatus` = 1 AND sb.`is_cancelled` = 0
		WHERE e.`is_cancelled` = 0 AND e.`batch_no` = %s GROUP BY e.`voucher_type`, e.`voucher_no`, e.`warehouse`""", lo)


def _tu_dong(se: str, cd) -> frappe._dict | None:
	"""Phiếu `CKL-` `chuyen_date_tu_dong` đang ghi sổ, kho bán → kho cận date (rà soát / sửa hạn) — kèm `moc` = lúc ghi sổ."""
	r = frappe.db.get_value(DT, se, ["name", "docstatus", "npp_loai", "from_warehouse", "to_warehouse", "posting_date", "posting_time",
		"npp_ghi_chu"], as_dict=True)
	if r and cint(r.docstatus) == 1 and r.npp_loai == T.SE_CHUYEN_DATE and r.from_warehouse == cd.kho_ban and r.to_warehouse == cd.kho_can_date:
		r.moc = datetime.combine(getdate(r.posting_date), (datetime.min + r.posting_time).time())
		return r
	return None


def _dong_ra(se: str) -> list[tuple[str, str, float]]:
	"""[(lô, mặt hàng, SL)] mà phiếu chuyển lấy ra khỏi kho nguồn (gói Outward chưa huỷ)."""
	return [(lo, hang, -flt(sl)) for lo, hang, sl in frappe.db.sql("""SELECT e.`batch_no`, b.`item_code`, SUM(e.`qty`)
		FROM `tabSerial and Batch Bundle` b JOIN `tabSerial and Batch Entry` e ON e.`parent` = b.`name`
		WHERE b.`voucher_type` = %s AND b.`voucher_no` = %s AND b.`type_of_transaction` = 'Outward' AND b.`docstatus` = 1 AND b.`is_cancelled` = 0
		GROUP BY e.`batch_no`, b.`item_code`""", (DT, se))]


def _yen_tu(lo: str, se: str, moc) -> bool:
	"""Lô không phát sinh gì (ngoài chính phiếu `se`) từ lúc ghi sổ của phiếu ấy về sau."""
	return not any(vn != se and get_datetime(luc) >= get_datetime(moc) for _vt, vn, _k, _q, luc in _phat_sinh(lo))


def hoan_chuyen_date(nguon: tuple[str, str], lo_kho: dict[str, tuple[str, float]], cd) -> set[str]:
	"""§7.3 điểm 8 (đề xuất). `nguon` = (DocType, tên) chứng từ NHẬP sắp huỷ (Bin của nó đã khoá); `lo_kho` = {lô: (kho nhận, SL nhập cơ sở)}. Lô mà
	phần thiếu ở kho nhận (kho bán) CHỈ do phiếu `CKL-` `chuyen_date_tu_dong` (mọi dòng gói lô chưa huỷ của lô thuộc chứng từ nguồn hoặc các phiếu ấy)
	→ huỷ các phiếu ấy (mới trước) để hàng về kho nhận; phiếu chở cả lô KHÁC → lập lại phần lô khác bằng phiếu mới CÙNG giờ ghi sổ (lô khác phải
	đứng yên từ phiếu ấy về sau, không thì cả nhóm vẫn chặn). → tập lô đã đưa về."""
	ung: dict[str, set] = {}
	for lo, (kho, nhap) in lo_kho.items():
		if kho != cd.kho_ban:
			continue  # rà soát chỉ chuyển từ kho bán
		ps = _phat_sinh(lo)
		con = sum(flt(q) for _vt, _vn, k, q, _l in ps if k == kho)
		if con >= flt(nhap) - EPS:
			continue
		phieu, ra_khoi, ok = set(), 0.0, True
		for vt, vn, k, q, _l in ps:
			if (vt, vn) == tuple(nguon):
				continue
			if vt == DT and _tu_dong(vn, cd):
				phieu.add(vn)
				if k == kho:
					ra_khoi -= flt(q)
				continue
			ok = False
			break
		if ok and phieu and abs(con + ra_khoi - flt(nhap)) <= EPS:
			ung[lo] = phieu
	while True:  # bỏ lô dùng chung phiếu với lô khác không lập lại được — tới khi ổn định
		bo = set()
		for lo, phieu in ung.items():
			for se in phieu:
				r = _tu_dong(se, cd)
				khac = [x for x in _dong_ra(se) if x[0] not in ung]
				if r is None or any(not _yen_tu(x[0], se, r.moc) for x in khac):
					bo.add(lo)
		if not bo:
			break
		for lo in bo:
			ung.pop(lo, None)
	if not ung:
		return set()
	phieu = sorted((_tu_dong(se, cd) for se in {se for ds in ung.values() for se in ds}), key=lambda r: (r.moc, r.name), reverse=True)
	for r in phieu:  # phiếu MỚI huỷ trước (không để tồn lô âm giữa chừng)
		se = r.name
		khac = [x for x in _dong_ra(se) if x[0] not in ung]
		if khac:
			_khoa_bin({x[1] for x in khac}, cd)
		doc = frappe.get_doc(DT, se)
		doc.flags.ignore_permissions = True
		doc.cancel()
		frappe.local.message_log = []
		if khac:
			lap_ckl(khac, cd.kho_ban, cd.kho_can_date, cd, loai=T.SE_CHUYEN_DATE, ghi_chu=r.npp_ghi_chu, luc=(r.moc.date(),
				r.moc.strftime("%H:%M:%S.%f")))
	return set(ung)
