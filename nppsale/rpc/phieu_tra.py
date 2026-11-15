"""PHIẾU TRẢ HÀNG (nppsale `returns` / `return_lines` → NPP Phieu Tra) — phần GHI THẲNG qua cổng + hàm dùng chung.

Ghi thẳng từ trình duyệt (supabase.from('returns' | 'return_lines')) đi qua bộ ghi cổng (nppsale.cong.bang.phieu_tra) vào đây. Luật:
- RLS ghi đang chạy: INSERT returns — chủ NPP / quản lý / NVBH (khác → 42501); UPDATE — chủ / quản lý mọi phiếu, NVBH phiếu NHÁP mình
  đứng tên (USING + WITH CHECK); DELETE — chủ / quản lý phiếu Nháp, NVBH phiếu Nháp mình đứng tên. Dòng không qua USING → bỏ lặng
  lẽ (200, 0 dòng — giao diện tự báo câu tiếng Việt). return_lines: chủ / quản lý / NVBH, phiếu cha thấy được.
- Khoá trình duyệt (`_khoa_ghi_thang_phieu_tra` / `_khoa_ghi_thang_dong_tra`, mig 214 / 227; chỉ khi người ghi là trình duyệt):
  lập phiếu chỉ ở Nháp; xoá chỉ Nháp; trạng thái chỉ đổi qua Hoàn thành / Huỷ; phiếu đã qua Nháp chỉ sửa ghi chú / lý do / ngày /
  người đứng tên; completed_at / credited_at / credit_with_invoice / applied_receipt_id chỉ qua RPC; dòng chỉ sửa khi phiếu còn
  Nháp, không chuyển dòng sang phiếu khác.
- Phiếu tự sinh (`_khoa_phieu_tra_tu_sinh`, mig 191): cấm xoá, cấm đổi trạng thái / khách / HĐ / đơn / cờ tự sinh / tiền, cấm
  mọi ghi dòng (RETURN_FOLLOWS_INVOICE).
Thứ tự lỗi như Postgres: trigger BEFORE (theo tên) rồi WITH CHECK của RLS; dòng: UNIT_MISSING → RETURN_PRICE_OVER_CEILING →
RETURN_FOLLOWS_INVOICE → PHIEU_TRA_KHOA.
"""
from __future__ import annotations

import frappe
from frappe.utils import flt, nowdate

from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong

from . import rpc  # noqa: F401 — RPC phiếu trả khai ở phần sau của P3c

DT = "NPP Phieu Tra"
VAI_LAP = ("owner", "manager", "sales")
VAI_DUYET = ("owner", "manager")

# cột nppsale → trường NPP Phieu Tra (ghi thẳng); cột bỏ qua khi gửi lên (máy tự lo hoặc không port)
COT_PHIEU = {"customer_id": "khach_hang", "invoice_id": "hoa_don", "order_id": "don_hang", "reason": "ly_do", "notes": "ghi_chu",
	"status": "trang_thai", "return_date": "ngay_tra", "sales_user_id": "nhan_vien", "credit_note_amount": "tien_tra",
	"revenue_date": "ngay_tru_doanh_so", "credit_with_invoice": "tu_sinh", "completed_at": "hoan_thanh_luc", "credited_at": "ghi_co_luc",
	"cancel_reason": "ly_do_huy", "cancelled_at": "huy_luc", "completed_by": "hoan_thanh_boi"}
COT_PHIEU_BO = {"id", "org_id", "requested_by", "created_at", "updated_at", "return_code", "return_seq", "tim_kd", "approved_by",
	"photo_url", "destination_zone", "applied_receipt_id"}
# phiếu đã qua Nháp: chỉ các cột này (v_cho của mig 227)
CHO_SUA_SAU_NHAP = {"ghi_chu", "ly_do", "ngay_tra", "nhan_vien", "ngay_tru_doanh_so"}
CHI_QUA_RPC = {"hoan_thanh_luc", "ghi_co_luc", "tu_sinh"}
KHOA_TU_SINH = ("trang_thai", "khach_hang", "hoa_don", "don_hang", "tu_sinh", "tien_tra")

COT_DONG = {"product_id": "mat_hang", "unit_name": "don_vi", "quantity": "so_luong", "unit_price": "don_gia", "vat_rate": "thue_suat",
	"line_total": "thanh_tien", "is_exchange": "hang_doi", "note": "ghi_chu", "reason": "ly_do"}
COT_DONG_BO = {"id", "return_id", "sort_order", "created_at"}


def _khoa(cau: str):
	raise NppLoi(f"PHIEU_TRA_KHOA: {cau}")


def _rls_ghi(bang: str):
	raise LoiCong("42501", f'new row violates row-level security policy for table "{bang}"', http=403)


_FK = {"khach_hang", "hoa_don", "don_hang", "nhan_vien", "mat_hang"}


def _gia_tri(v, truong: str, bang: str, nullif: set):
	"""Giá trị JSON → trường Frappe. Chuỗi rỗng: lối vào có NULLIF (RPC) → NULL; ghi thẳng như Postgres — khoá ngoại uuid rỗng → 22P02,
	lý do rỗng → vi phạm CHECK (23514). bool → 0 / 1."""
	if truong in ("tu_sinh", "hang_doi"):
		return 1 if (v is True or str(v).lower() in ("true", "t", "1")) else 0
	if v == "":
		if truong in nullif:
			return None
		if truong in _FK:
			raise LoiCong("22P02", 'invalid input syntax for type uuid: ""', http=400)
		if truong == "ly_do":
			raise LoiCong("23514", f'new row for relation "{bang}" violates check constraint "{bang}_reason_check"', http=400)
	return v


def _ap(doc, gia_tri: dict, anh_xa: dict, bo: set, bang: str, nullif: set = frozenset()) -> set:
	cham = set()
	for k, v in gia_tri.items():
		if k in bo:
			continue
		f = anh_xa.get(k)
		if f is None:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{bang}' in the schema cache", http=400)
		doc.set(f, _gia_tri(v, f, bang, nullif))
		cham.add(f)
	return cham


# ------------------------------------------------------------------------------------------------ returns
def them_phieu(ds: list[dict], nc, nullif: set = frozenset()) -> list[str]:
	ra = []
	for g in ds:
		g = dict(g or {})
		doc = frappe.new_doc(DT)
		doc.trang_thai = "pending"  # mặc định cột status của nppsale — lập phiếu thẳng không gửi status là bị khoá
		doc.ngay_tra = nowdate()
		cham = _ap(doc, g, COT_PHIEU, COT_PHIEU_BO, "returns", nullif)
		if doc.trang_thai != "draft":  # trigger BEFORE chạy trước ràng buộc NOT NULL / CHECK
			_khoa("phiếu trả lập ra ở Nháp — hoàn thành đi qua nút Hoàn thành")
		if g.get("applied_receipt_id") is not None:
			_khoa("cột này chỉ đổi qua RPC")
		if not doc.khach_hang:
			raise LoiCong("23502", 'null value in column "customer_id" of relation "returns" violates not-null constraint', http=400)
		doc.flags.cot_ghi = cham
		doc.flags.ignore_permissions = True
		frappe.db.savepoint("npp_them_pt")
		doc.insert()
		if nc.vai not in VAI_LAP and not nc.bo_qua_rls:  # WITH CHECK của RLS chạy sau trigger BEFORE
			frappe.db.rollback(save_point="npp_them_pt")
			_rls_ghi("returns")
		ra.append(doc.name)
	return ra


def _duoc_sua(doc, nc) -> bool:
	"""USING của UPDATE: chủ / quản lý mọi phiếu; NVBH phiếu Nháp mình đứng tên."""
	if nc.bo_qua_rls or nc.vai in VAI_DUYET:
		return True
	return nc.vai == "sales" and doc.nhan_vien == nc.user and doc.trang_thai == "draft"


def sua_phieu(gia_tri: dict, ids: list[str], nc) -> list[str]:
	ra = []
	for ten in ids:
		doc = frappe.get_doc(DT, ten)
		if not _duoc_sua(doc, nc):
			continue
		cu = {f: doc.get(f) for f in (*COT_PHIEU.values(), "tien_tra")}
		cham = _ap(doc, dict(gia_tri or {}), COT_PHIEU, COT_PHIEU_BO, "returns")
		doi = {f for f in cham if doc.get(f) != cu.get(f) and str(doc.get(f) or "") != str(cu.get(f) or "")}
		if not nc.bo_qua_rls:
			# _khoa_ghi_thang_phieu_tra (trình duyệt)
			if "trang_thai" in doi:
				_khoa(f"trạng thái phiếu trả chỉ đổi qua Hoàn thành / Huỷ ({cu['trang_thai']} → {doc.trang_thai})")
			if cu["trang_thai"] != "draft" and doi - CHO_SUA_SAU_NHAP:
				_khoa("phiếu trả đã qua Nháp chỉ sửa được ghi chú / lý do / ngày / người đứng tên — sửa hàng, tiền đi qua màn sửa phiếu")
			if doi & CHI_QUA_RPC or (gia_tri or {}).get("applied_receipt_id") is not None:
				_khoa("cột này chỉ đổi qua RPC")
			# _khoa_phieu_tra_tu_sinh
			if cu["tu_sinh"] and doi & set(KHOA_TU_SINH):
				raise NppLoi("RETURN_FOLLOWS_INVOICE: phiếu trả tự sinh theo hóa đơn — muốn sửa thì sửa hóa đơn")
		doc.flags.cot_ghi = cham
		doc.flags.ignore_permissions = True
		frappe.db.savepoint("npp_sua_pt")
		doc.save()
		if not nc.bo_qua_rls and nc.vai == "sales" and not (doc.nhan_vien == nc.user and doc.trang_thai == "draft"):
			frappe.db.rollback(save_point="npp_sua_pt")  # WITH CHECK của "Sales can update own draft returns"
			_rls_ghi("returns")
		ra.append(ten)
	return ra


def xoa_phieu(ids: list[str], nc) -> list[str]:
	ra = []
	for ten in ids:
		r = frappe.db.get_value(DT, ten, ["trang_thai", "nhan_vien", "tu_sinh"], as_dict=True)
		if not r:
			continue
		if not nc.bo_qua_rls:
			if nc.vai in VAI_DUYET:
				if r.trang_thai != "draft":
					continue
			elif not (nc.vai == "sales" and r.nhan_vien == nc.user and r.trang_thai == "draft"):
				continue
			if r.tu_sinh:
				raise NppLoi("RETURN_FOLLOWS_INVOICE: phiếu trả tự sinh theo hóa đơn — muốn sửa thì sửa hóa đơn")
		frappe.delete_doc(DT, ten, ignore_permissions=True, force=True)
		ra.append(ten)
	return ra


# ------------------------------------------------------------------------------------------------ return_lines
def _phieu_cua_dong(ten_dong: str) -> str | None:
	return frappe.db.get_value("NPP Phieu Tra Dong", ten_dong, "parent")


def _duoc_ghi_dong(nc) -> bool:
	"""RLS "Authorized roles can manage return lines": chủ / quản lý / NVBH (phiếu cha thấy được — đã lọc ở bước chọn dòng)."""
	return nc.bo_qua_rls or nc.vai in VAI_LAP


def _khoa_dong(doc, nc):
	"""Thứ tự trigger dòng sau trần giá (trần chạy trong validate): tự sinh → khoá Nháp."""
	if nc.bo_qua_rls:
		return
	if doc.tu_sinh:
		raise NppLoi("RETURN_FOLLOWS_INVOICE: phiếu trả tự sinh theo hóa đơn — muốn sửa thì sửa hóa đơn")
	if doc.trang_thai != "draft":
		_khoa(f"dòng hàng chỉ sửa được khi phiếu trả còn Nháp (đang {doc.trang_thai or '?'})")


def them_dong(ds: list[dict], nc, nullif: set = frozenset()) -> list[str]:
	if not _duoc_ghi_dong(nc):
		_rls_ghi("return_lines")
	ra = []
	theo_phieu: dict = {}
	for g in ds:
		g = dict(g or {})
		pt = g.get("return_id")
		if not pt or not frappe.db.exists(DT, pt):
			_rls_ghi("return_lines")  # phiếu cha không thấy được / không có — WITH CHECK
		theo_phieu.setdefault(pt, []).append(g)
	for pt, dong in theo_phieu.items():
		doc = frappe.get_doc(DT, pt)
		moi = []
		for g in dong:
			d = doc.append("dong", {"hang_doi": 0})
			_ap(d, g, COT_DONG, COT_DONG_BO, "return_lines", nullif)
			if not d.mat_hang:
				raise LoiCong("23502", 'null value in column "product_id" of relation "return_lines" violates not-null constraint', http=400)
			if d.so_luong is None:
				raise LoiCong("23502", 'null value in column "quantity" of relation "return_lines" violates not-null constraint', http=400)
			moi.append(d)
		_luu_dong(doc, nc)
		ra += [d.name for d in moi]
	return ra


def _luu_dong(doc, nc):
	"""Lưu phiếu sau khi đổi dòng: validate chạy đơn vị / thành tiền / trần giá trước, rồi khoá tự sinh / Nháp như thứ tự trigger."""
	doc.flags.ignore_permissions = True
	doc.flags.cot_ghi = set()
	doc.flags.kiem_dong_sau = (lambda: _khoa_dong(doc, nc))
	doc.save()


def sua_dong(gia_tri: dict, ids: list[str], nc) -> list[str]:
	if not _duoc_ghi_dong(nc):
		return []
	ra = []
	for ten in ids:
		pt = _phieu_cua_dong(ten)
		if not pt:
			continue
		doc = frappe.get_doc(DT, pt)
		d = next(x for x in doc.dong if x.name == ten)
		g = dict(gia_tri or {})
		if g.get("return_id") not in (None, pt) and not nc.bo_qua_rls:
			_khoa("không chuyển dòng sang phiếu khác")
		g.pop("return_id", None)
		_ap(d, g, COT_DONG, COT_DONG_BO, "return_lines")
		_luu_dong(doc, nc)
		ra.append(ten)
	return ra


def xoa_dong(ids: list[str], nc) -> list[str]:
	if not _duoc_ghi_dong(nc):
		return []
	ra = []
	theo_phieu: dict = {}
	for ten in ids:
		pt = _phieu_cua_dong(ten)
		if pt:
			theo_phieu.setdefault(pt, []).append(ten)
	for pt, ds in theo_phieu.items():
		doc = frappe.get_doc(DT, pt)
		doc.set("dong", [x for x in doc.dong if x.name not in ds])
		_luu_dong(doc, nc)
		ra += ds
	return ra


# ------------------------------------------------------------------------------------------------ hàm dùng chung
def dong_hang_doi_cua_don(don: str) -> list[dict]:
	"""get_invoiceable_lines — phần UNION: hàng ĐỔI của phiếu trả kèm đơn (Nháp / Chờ xử lý, chưa bám HĐ — mig 212) cũng rời kho chuyến
	này: return_line_id = dòng phiếu, order_line_id rỗng, đơn giá 0, giá bán của mặt hàng làm list_price, ghi chú '[Exchange]'."""
	from nppsale.rpc.xuat_hang import _ton_kho_ban
	from nppsale.thiet_lap.ban_hang import cai_dat_ban

	ds = frappe.db.sql("""SELECT d.`name`, d.`mat_hang`, i.`item_name`, d.`don_vi`, d.`so_luong`, i.`npp_gia_ban`, i.`npp_thue_suat`,
			(SELECT u.`conversion_factor` FROM `tabUOM Conversion Detail` u WHERE u.`parent` = d.`mat_hang` AND u.`parenttype` = 'Item'
				AND u.`uom` = d.`don_vi` LIMIT 1) AS `hs`
		FROM `tabNPP Phieu Tra Dong` d JOIN `tabNPP Phieu Tra` r ON r.`name` = d.`parent`
		LEFT JOIN `tabItem` i ON i.`name` = d.`mat_hang`
		WHERE r.`don_hang` = %s AND r.`trang_thai` IN ('draft', 'submitted') AND IFNULL(r.`hoa_don`, '') = '' AND d.`hang_doi` = 1
		ORDER BY r.`creation`, r.`name`, d.`idx`""", (don,), as_dict=True)
	if not ds:
		return []
	ton = _ton_kho_ban(sorted({d.mat_hang for d in ds}), cai_dat_ban().kho_ban)
	return [{"order_line_id": None, "return_line_id": d.name, "product_id": d.mat_hang, "product_name": d.item_name, "sku": d.mat_hang,
		"unit_name": d.don_vi, "conversion_factor": flt(d.hs) or 1, "ordered_qty": flt(d.so_luong), "invoiced_qty": 0.0,
		"remaining_qty": flt(d.so_luong), "unit_price": 0.0, "list_price": flt(d.npp_gia_ban), "line_discount": 0.0,
		"vat_rate": flt(d.npp_thue_suat), "available_base": ton.get(d.mat_hang, 0.0), "is_exchange": True, "note": "[Exchange]"} for d in ds]


def hang_doi_da_dat(bo_don: str) -> list[tuple]:
	"""committed_stock_by_product (mig 137) — phần hàng ĐỔI: dòng đổi của phiếu Nháp / Chờ xử lý chưa bám HĐ, thuộc đơn còn sống
	(submitted / partially_invoiced, trừ đơn đang sửa) → [(mặt hàng, SL cơ sở)]."""
	return frappe.db.sql("""SELECT d.`mat_hang`, SUM(d.`so_luong` * COALESCE((SELECT u.`conversion_factor` FROM `tabUOM Conversion Detail` u
			WHERE u.`parent` = d.`mat_hang` AND u.`parenttype` = 'Item' AND u.`uom` = d.`don_vi` LIMIT 1), 1))
		FROM `tabNPP Phieu Tra Dong` d JOIN `tabNPP Phieu Tra` r ON r.`name` = d.`parent`
		JOIN `tabSales Order` so ON so.`name` = r.`don_hang`
		WHERE d.`hang_doi` = 1 AND IFNULL(r.`hoa_don`, '') = '' AND r.`trang_thai` IN ('draft', 'submitted')
			AND so.`npp_trang_thai` IN ('submitted', 'partially_invoiced') AND so.`docstatus` < 2 AND so.`name` != %s
		GROUP BY d.`mat_hang`""", (bo_don or "",))


def doi_nguoi_phieu_tra(pt: str, nv: str):
	"""assign_doc_seller('return', …) (mig 194): phiếu gắn HĐ đi theo người đứng tên HĐ; phiếu không gắn HĐ → đổi người đứng tên (qua
	RPC — guard mig 160 không kiểm quyền gán), công nợ âm của phiếu đi theo (_phieu_tra_doi_nguoi_cong_no)."""
	doc = frappe.get_doc(DT, pt)
	if doc.hoa_don:
		raise NppLoi("RETURN_SELLER_FOLLOWS_INVOICE: phiếu trả gắn hóa đơn đi theo người đứng tên hóa đơn — gán lại ở hóa đơn")
	doc.nhan_vien = nv
	doc.flags.qua_rpc = True
	doc.flags.cot_ghi = {"nhan_vien"}
	doc.flags.ignore_permissions = True
	doc.save()
	cong_no_doi_nguoi(doc)


def cong_no_doi_nguoi(doc):
	"""_phieu_tra_doi_nguoi_cong_no: dòng công nợ âm của phiếu (tờ ghi có độc lập) mang người đứng tên mới — dựng cùng phần tờ ghi có."""
	return None


# ------------------------------------------------------------------------------------------------ RPC
@rpc("create_return_with_lines")
def create_return_with_lines(p_head=None, p_lines=None):
	"""mig 171 — SECURITY INVOKER (cố ý): ghi dưới quyền người gọi, qua RLS + khoá trình duyệt như ghi thẳng. Phiếu lập ở Nháp (status
	trống → 'submitted' → PHIEU_TRA_KHOA); dòng: thành tiền / tiền trả do máy tính."""
	from nppsale.cong.ngu_canh import hien_tai

	nc = hien_tai()
	head = _json(p_head) or {}
	lines = _json(p_lines)
	if not isinstance(lines, list) or not lines:
		raise NppLoi("BAD_PAYLOAD: phiếu trả cần ít nhất một dòng hàng.")
	g = {"customer_id": head.get("customer_id"), "invoice_id": head.get("invoice_id"), "order_id": head.get("order_id"),
		"reason": head.get("reason"), "notes": head.get("notes"), "status": head.get("status") or "submitted",
		"credit_note_amount": head.get("credit_note_amount") or 0, "sales_user_id": head.get("sales_user_id")}
	ten = them_phieu([g], nc, nullif={"hoa_don", "don_hang", "ghi_chu", "nhan_vien"})[0]
	dong = [{"return_id": ten, "product_id": x.get("product_id"), "unit_name": x.get("unit_name"), "quantity": x.get("quantity"),
		"unit_price": x.get("unit_price") or 0, "vat_rate": x.get("vat_rate") or 0, "is_exchange": bool(x.get("is_exchange")),
		"note": x.get("note"), "reason": x.get("reason")} for x in lines]
	them_dong(dong, nc, nullif={"ghi_chu", "ly_do"})
	return ten


def _json(v):
	import json

	if isinstance(v, str):
		try:
			return json.loads(v) if v else None
		except ValueError:
			return None
	return v


# ================================================================================================ save_pos_return (POS)
_BOOL_DUNG = {"t", "tr", "tru", "true", "y", "ye", "yes", "on", "1"}
_BOOL_SAI = {"f", "fa", "fal", "fals", "false", "n", "no", "of", "off", "0"}


def _bool_pg(v) -> bool:
	"""(p->>'x')::boolean của Postgres: true / false / t / f / yes / no / on / off / 1 / 0 (không phân biệt hoa thường); null → false."""
	if v is None:
		return False
	if isinstance(v, bool):
		return v
	s = str(v).strip().lower()
	if s in _BOOL_DUNG:
		return True
	if s in _BOOL_SAI:
		return False
	raise LoiCong("22P02", f'invalid input syntax for type boolean: "{v}"', http=400)


def _ngay_pg(v):
	"""NULLIF(p->>'x', '')::date — ISO YYYY-MM-DD; dạng d/m/y lệch tháng → 22008, chữ → 22007."""
	import datetime as _dt
	import re

	s = str(v).strip()
	try:
		return _dt.date.fromisoformat(s[:10]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T].*)?", s) else _dt.datetime.strptime(s, "%m/%d/%Y").date()
	except ValueError:
		if re.search(r"\d", s):
			raise LoiCong("22008", f'date/time field value out of range: "{v}"', http=400) from None
		raise LoiCong("22007", f'invalid input syntax for type date: "{v}"', http=400) from None


def _chu(v) -> str | None:
	if v is None:
		return None
	s = v if isinstance(v, str) else str(v)
	return s or None


def _chuan_bi_tra(p=None):
	"""Đọc trước khi khoá (cổng commit sau bước này): người gọi + quyền, cài đặt bán hàng."""
	from nppsale.cong.ngu_canh import co_quyen, hien_tai
	from nppsale.thiet_lap.ban_hang import cai_dat_ban

	co_quyen(hien_tai(), "returns.approve")
	cai_dat_ban()


@rpc("save_pos_return", ghi=True, chuan_bi=_chuan_bi_tra)
def save_pos_return(p=None):
	"""mig 190 / 191 / 227 — POS lập / sửa / ghi nhận phiếu TỰ LẬP trong MỘT giao dịch (SECURITY DEFINER: không RLS, không khoá trình duyệt;
	guard người đứng tên vẫn kiểm khi LẬP). Sửa = ghi đè cả đầu phiếu + thay toàn bộ dòng; phiếu đã nhập kho chỉ sửa khi Ghi nhận lại
	(huỷ rồi hoàn thành lại, giữ số PT)."""
	from nppsale.cong.ngu_canh import hien_tai
	from nppsale.rpc.xuat_hang import _khoa_bin
	from nppsale.thiet_lap.ban_hang import cai_dat_ban

	nc = hien_tai()
	cd = cai_dat_ban()
	p = _json(p) or {}
	rid = _chu(p.get("return_id"))
	kh = _chu(p.get("customer_id"))
	hd = _chu(p.get("invoice_id"))
	lines = p.get("lines")
	complete = _bool_pg(p.get("complete"))
	zone = _chu(p.get("zone")) or "sale"
	ngay = _ngay_pg(p.get("return_date")) if _chu(p.get("return_date")) else frappe.utils.getdate(nowdate())
	# khoá Bin trước mọi câu đọc khi có ghi kho (CFD-05): hàng gửi lên ∪ hàng đang có trên phiếu
	if complete or (rid and frappe.db.get_value(DT, rid, "trang_thai") == "completed"):
		hang = {_chu(x.get("product_id")) for x in (lines if isinstance(lines, list) else []) if isinstance(x, dict) and _chu(x.get("product_id"))}
		if rid:
			hang |= set(frappe.get_all("NPP Phieu Tra Dong", filters={"parent": rid, "parenttype": DT}, pluck="mat_hang"))
		_khoa_bin(hang, cd)
	if not nc.vai:
		raise NppLoi("FORBIDDEN: chưa đăng nhập")
	if nc.vai not in VAI_LAP:
		raise NppLoi("FORBIDDEN: vai trò của bạn không lập được phiếu trả")
	if not isinstance(lines, list) or not lines:
		raise NppLoi("BAD_PAYLOAD: phiếu trả cần ít nhất một dòng hàng.")
	if not kh or not frappe.db.exists("Customer", kh):
		raise NppLoi("CUSTOMER_NOT_FOUND: không tìm thấy khách hàng")
	if hd and not frappe.db.exists("Sales Invoice", {"name": hd, "is_return": 0}):
		raise NppLoi("INVOICE_NOT_FOUND: không tìm thấy hóa đơn gốc")
	for x in lines:
		if not isinstance(x, dict):
			continue
		if _so(x.get("quantity")) > 0 and (_so(x.get("unit_price")) < 0 or not (0 <= _so(x.get("vat_rate")) <= 1)):
			raise NppLoi("BAD_PAYLOAD: đơn giá hàng trả không được âm, thuế phải trong khoảng 0 – 1 (0 – 100 phần trăm)")
	dau = {"khach_hang": kh, "hoa_don": hd, "ly_do": _chu(p.get("reason")), "ghi_chu": _chu(p.get("notes")), "ngay_tra": ngay}
	if not rid:
		doc = frappe.new_doc(DT)
		doc.update({**dau, "trang_thai": "draft"})
		doc.flags.cot_ghi = set(dau) | {"trang_thai"}
	else:
		r = frappe.db.sql(f"SELECT `name` FROM `tab{DT}` WHERE `name` = %s FOR UPDATE", (rid,))
		if not r:
			raise NppLoi("RETURN_NOT_FOUND")
		doc = frappe.get_doc(DT, rid)
		if doc.trang_thai == "cancelled":
			raise NppLoi("RETURN_LOCKED: phiếu trả đã huỷ — không sửa được")
		if doc.tu_sinh:
			raise NppLoi("RETURN_FOLLOWS_INVOICE: phiếu trả tự sinh theo hóa đơn — muốn sửa thì sửa hóa đơn")
		if nc.vai == "sales" and (doc.trang_thai != "draft" or doc.nhan_vien != nc.user):
			raise NppLoi("FORBIDDEN: nhân viên bán hàng chỉ sửa được phiếu nháp của mình")
		if doc.trang_thai == "completed":
			if not complete:
				raise NppLoi("RETURN_COMPLETED: phiếu đã nhập kho — sửa xong phải bấm Ghi nhận để kho và công nợ đổi theo")
			_huy(doc, "Sửa phiếu trả trên POS — ghi nhận lại", nc, cd)
			doc.reload()
			doc.update({"trang_thai": "draft", "huy_luc": None, "ly_do_huy": None})
		doc.update(dau)
		doc.flags.cot_ghi = set(dau)  # không có sales_user_id trong SET → guard không chạy; người đứng tên theo HĐ mới (mig 194)
		doc.set("dong", [])
	n = 0
	for x in lines:
		if not isinstance(x, dict) or not _chu(x.get("product_id")) or not _so(x.get("quantity")) > 0:
			continue
		doi = _bool_pg(x.get("is_exchange")) if x.get("is_exchange") is not None else False
		doc.append("dong", {"mat_hang": _chu(x.get("product_id")), "don_vi": x.get("unit_name") or "", "so_luong": _so(x.get("quantity")),
			"don_gia": _so(x.get("unit_price")), "thue_suat": _so(x.get("vat_rate")), "hang_doi": 1 if doi else 0,
			"ghi_chu": _chu(x.get("note")), "ly_do": None if doi else _chu(x.get("reason"))})
		n += 1
	if not n:
		raise NppLoi("BAD_PAYLOAD: phiếu trả cần ít nhất một dòng hàng.")
	doc.flags.ignore_permissions = True
	if doc.is_new():
		doc.insert()
	else:
		doc.save()
	if complete:
		if doc.trang_thai == "draft":
			doc.trang_thai = "submitted"
			doc.flags.qua_rpc = True
			doc.flags.cot_ghi = {"trang_thai"}
			doc.save()
		_hoan_thanh(doc.name, zone, None, nc, cd)
	return doc.name


def _so(v) -> float:
	"""COALESCE((x)::numeric, 0) — chữ không phải số → 22P02 như Postgres."""
	if v is None or v == "":
		return 0.0
	try:
		return float(v)
	except (TypeError, ValueError):
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{v}"', http=400) from None


# ================================================================================================ complete_return / cancel_return
VUNG_KHO = ("sale", "date")


def _kho_cua(zone: str, cd) -> str:
	return cd.kho_ban if zone == "sale" else cd.kho_can_date


def _he_so(hang: str, don_vi: str) -> float:
	"""Hệ số quy đổi hiện tại của đơn vị (Item.uoms; đơn vị cơ sở / không có → 1) — chụp vào he_so_quy_doi lúc lập chứng từ (⚠ Q13)."""
	if don_vi == frappe.db.get_value("Item", hang, "stock_uom"):
		return 1.0
	v = frappe.db.get_value("UOM Conversion Detail", {"parent": hang, "parenttype": "Item", "uom": don_vi}, "conversion_factor")
	return flt(v) if v and flt(v) > 0 else 1.0


def _gia_von_xuat(hang: str, hds: list[str]) -> float | None:
	"""Giá vốn mỗi đơn vị kho của mặt hàng đã xuất trên các HĐ (bậc a / b của mig 127): gói lô Outward của HĐ — HĐ mới nhất trước, trong
	một HĐ lấy dòng chèn trước (Postgres: cùng now() của giao dịch → dòng vật lý đầu); hàng không lô: |Δ giá trị / Δ SL| của sổ kho."""
	if not hds:
		return None
	v = frappe.db.sql("""SELECT e.`incoming_rate` FROM `tabSerial and Batch Bundle` b
		JOIN `tabSerial and Batch Entry` e ON e.`parent` = b.`name`
		JOIN `tabSales Invoice` si ON si.`name` = b.`voucher_no`
		LEFT JOIN `tabSales Invoice Item` i ON i.`name` = b.`voucher_detail_no`
		WHERE b.`voucher_type` = 'Sales Invoice' AND b.`type_of_transaction` = 'Outward' AND b.`item_code` = %(h)s
			AND si.`name` IN %(hd)s AND si.`is_return` = 0
		ORDER BY si.`creation` DESC, i.`idx` ASC, e.`idx` ASC LIMIT 1""", {"h": hang, "hd": tuple(hds)})
	if v and v[0][0] is not None:
		return flt(v[0][0])
	v = frappe.db.sql("""SELECT ABS(sle.`stock_value_difference` / NULLIF(sle.`actual_qty`, 0)) FROM `tabStock Ledger Entry` sle
		JOIN `tabSales Invoice` si ON si.`name` = sle.`voucher_no`
		WHERE sle.`voucher_type` = 'Sales Invoice' AND sle.`voucher_no` IN %(hd)s AND sle.`item_code` = %(h)s AND sle.`actual_qty` < 0
		ORDER BY si.`creation` DESC, sle.`creation` ASC LIMIT 1""", {"h": hang, "hd": tuple(hds)})
	return flt(v[0][0]) if v and v[0][0] is not None else None


def _gia_von_nhap_lai(doc, hang: str) -> float:
	"""mig 127 / 158: (a) HĐ gắn → (b) các HĐ của đơn (cả HĐ đã huỷ) → (c) lô mới nhất cùng mặt hàng có giá > 0 → (d) ⚠ Q3: giá vốn mặc
	định của mặt hàng → giá nhập (đơn vị cơ sở) → chặn (gửi 0 cho lõi là rơi về giá bán — PoC 5)."""
	from nppsale.cong.bang.kho import NGUON_LO
	from nppsale.su_kien.san_pham import bang_gia_nhap

	if doc.hoa_don:
		g = _gia_von_xuat(hang, [doc.hoa_don])
		if g:
			return g
	if doc.don_hang:
		g = _gia_von_xuat(hang, frappe.get_all("Sales Invoice", filters={"npp_don_hang": doc.don_hang, "is_return": 0}, pluck="name"))
		if g:
			return g
	v = frappe.db.sql(f"""SELECT x.`gia_von` FROM {NGUON_LO} x WHERE x.`hang` = %s AND x.`gia_von` > 0
		ORDER BY x.`npp_ngay_nhap` IS NULL, x.`npp_ngay_nhap` DESC, x.`creation` DESC LIMIT 1""", (hang,))
	if v and flt(v[0][0]) > 0:
		return flt(v[0][0])
	it = frappe.db.get_value("Item", hang, ["valuation_rate", "stock_uom", "item_name"], as_dict=True) or frappe._dict()
	if flt(it.valuation_rate) > 0:
		return flt(it.valuation_rate)
	gn = frappe.db.get_value("Item Price", {"item_code": hang, "price_list": bang_gia_nhap(), "uom": it.stock_uom}, "price_list_rate")
	if flt(gn) > 0:
		return flt(gn)
	raise NppLoi(f"RETURN_NO_COST: mặt hàng {it.item_name or hang} chưa có giá vốn — nhập giá vốn mặc định của mặt hàng rồi hoàn thành lại")


def _lo_nhan(doc, hang: str, zone: str, kho: str) -> str | None:
	"""Lô nhận (mig 127): lô còn dùng mới nhất của mặt hàng ở ĐÚNG kho chọn (không xét hạn / tồn); không có → lô mới RESTOCK-<PT>-<hàng>
	(hạn = hạn xa nhất của mặt hàng → hôm nay + hạn dùng → hôm nay + 365 ngày). Hàng không lô → None."""
	from frappe.utils import add_days, now_datetime

	from nppsale.cong.bang.kho import NGUON_LO

	if not frappe.db.get_value("Item", hang, "has_batch_no"):
		return None
	v = frappe.db.sql(f"""SELECT x.`lo` FROM {NGUON_LO} x WHERE x.`hang` = %s AND x.`vung` = %s AND x.`lo` IS NOT NULL
		AND IFNULL(x.`disabled`, 0) = 0 ORDER BY x.`npp_ngay_nhap` IS NULL, x.`npp_ngay_nhap` DESC, x.`creation` DESC LIMIT 1""", (hang, zone))
	if v:
		return v[0][0]
	ten = f"RESTOCK-{doc.name}-{hang}"[:140]
	if frappe.db.exists("Batch", ten):
		return ten
	han = frappe.db.sql("SELECT MAX(`expiry_date`) FROM `tabBatch` WHERE `item` = %s", (hang,))[0][0]
	if not han:
		hsd = frappe.db.get_value("Item", hang, "shelf_life_in_days") or 0
		han = add_days(nowdate(), hsd if hsd > 0 else 365)
	frappe.get_doc({"doctype": "Batch", "batch_id": ten, "item": hang, "expiry_date": han, "npp_ngay_nhap": now_datetime(),
		"npp_kho_tao": kho}).insert(ignore_permissions=True)
	return ten


def _lap_phieu_nhap(doc, kho: str, zone: str, luc, cd) -> str:
	"""Stock Entry Material Receipt `NL-` (phiếu tự sinh; phiếu tự lập chỉ hàng đổi): mọi dòng SL > 0 kể cả hàng đổi, giá vốn mỗi đơn vị
	kho, gói lô Inward do app lập (lô hết hạn vẫn nhận — PoC 9)."""
	from erpnext.stock.serial_batch_bundle import SerialBatchCreation

	se = frappe.new_doc("Stock Entry")
	se.update({"naming_series": "NL-.####", "stock_entry_type": "Material Receipt", "company": cd.cong_ty, "to_warehouse": kho,
		"set_posting_time": 1, "posting_date": luc.date(), "posting_time": luc.strftime("%H:%M:%S"), "npp_loai": "nhap_lai_tra",
		"npp_phieu_tra": doc.name, "remarks": f"Nhập lại từ phiếu trả {doc.name}"})
	for d in doc.dong:
		if flt(d.so_luong) <= 0:
			continue
		hs = _he_so(d.mat_hang, d.don_vi)
		d.he_so_quy_doi = hs
		r = se.append("items", {"item_code": d.mat_hang, "qty": flt(d.so_luong), "uom": d.don_vi, "conversion_factor": hs, "t_warehouse": kho,
			"basic_rate": _gia_von_nhap_lai(doc, d.mat_hang), "set_basic_rate_manually": 1, "allow_zero_valuation_rate": 0})
		lo = _lo_nhan(doc, d.mat_hang, zone, kho)
		if lo:
			b = SerialBatchCreation({"item_code": d.mat_hang, "warehouse": kho, "posting_date": se.posting_date, "posting_time": se.posting_time,
				"voucher_type": "Stock Entry", "qty": flt(d.so_luong) * hs, "type_of_transaction": "Inward", "company": cd.cong_ty,
				"batches": frappe._dict({lo: flt(d.so_luong) * hs}), "do_not_submit": True}).make_serial_and_batch_bundle()
			r.serial_and_batch_bundle = b.name
			r.use_serial_batch_fields = 0
	se.flags.ignore_permissions = True
	se.insert()
	se.submit()
	frappe.local.message_log = []
	return se.name


def _lap_to_ghi_co_co_kho(doc, kho: str, zone: str, luc, cd) -> str:
	"""Tờ ghi có CÓ KHO `HDT-` của phiếu tự lập: mọi dòng SL > 0 (SL âm), dòng đổi theo luật dòng 0 đ, giá vốn nhập lại tự đặt theo đơn vị
	kho rồi ghi sổ ngay (lưu lại tờ nháp đổi dòng là lõi xoá giá — PoC 5). Gắn HĐ thì npp_hoa_don_goc (nợ trừ vào HĐ), không thì dòng âm."""
	from frappe.utils import now_datetime

	from nppsale.luat.giu_no import khi_lap
	from nppsale.rpc.don_hang import _bang_gia_nhom, _gia_bang
	from nppsale.rpc.gan_nguoi import da_nghi
	from nppsale.thiet_lap.ban_hang import mau_thue_dong
	from nppsale.su_kien.san_pham import bang_gia_chung

	g = khi_lap(doc.nhan_vien, da_nghi, now_datetime())
	bang = _bang_gia_nhom(doc.khach_hang) or bang_gia_chung()
	cn = frappe.new_doc("Sales Invoice")
	cn.update({"naming_series": "HDT-.####", "customer": doc.khach_hang, "company": cd.cong_ty, "is_return": 1, "update_stock": 1,
		"set_warehouse": kho, "set_posting_time": 1, "posting_date": luc.date(), "posting_time": luc.strftime("%H:%M:%S"),
		"selling_price_list": bang, "ignore_pricing_rule": 1, "disable_rounded_total": 1, "taxes_and_charges": cd.mau_thue_ban,
		"npp_hoa_don_goc": doc.hoa_don or None, "npp_phieu_tra": doc.name, "npp_nhan_vien": doc.nhan_vien, "npp_nv_giu_no": g.nv,
		"npp_ve_npp_luc": g.ve_npp, "update_outstanding_for_self": 1, "due_date": luc.date()})
	for d in doc.dong:
		if flt(d.so_luong) <= 0:
			continue
		hs = _he_so(d.mat_hang, d.don_vi)
		d.he_so_quy_doi = hs
		gia = 0.0 if d.hang_doi else flt(d.don_gia)
		plr = (_gia_bang(d.mat_hang, d.don_vi, bang) or 0.0) if d.hang_doi else gia
		lo = _lo_nhan(doc, d.mat_hang, zone, kho)
		cn.append("items", {"item_code": d.mat_hang, "qty": -flt(d.so_luong), "uom": d.don_vi, "conversion_factor": hs, "rate": gia,
			"price_list_rate": plr, "discount_percentage": 0, "discount_amount": max(0.0, plr - gia), "margin_type": "",
			"margin_rate_or_amount": 0, "warehouse": kho, "item_tax_template": mau_thue_dong(flt(d.thue_suat), cd.cong_ty),
			"npp_thue_suat": flt(d.thue_suat), "npp_hang_doi": 1 if d.hang_doi else 0, "npp_ghi_chu": d.ghi_chu,
			"incoming_rate": _gia_von_nhap_lai(doc, d.mat_hang), "use_serial_batch_fields": 1 if lo else 0, "batch_no": lo})
	from erpnext.controllers.accounts_controller import _get_taxes_and_charges

	for t in _get_taxes_and_charges("Sales Taxes and Charges Template", cd.mau_thue_ban) or []:
		cn.append("taxes", t)
	cn.flags.ignore_permissions = True
	cn.insert()
	cn.submit()
	frappe.local.message_log = []
	return cn.name


def _khoa_phieu(pt) -> object:
	r = frappe.db.sql(f"SELECT `name` FROM `tab{DT}` WHERE `name` = %s FOR UPDATE", (str(pt or ""),))
	if not r:
		raise NppLoi("RETURN_NOT_FOUND")
	return frappe.get_doc(DT, pt)


def _hoan_thanh(pt: str, zone, ngay, nc, cd):
	"""Thân complete_return (2 tham số; `ngay` = mốc ngày chọn của bản 3 tham số, None = lúc bấm) → tên chứng từ nhập (hoặc None)."""
	import datetime as _dt

	from frappe.utils import now_datetime

	from nppsale.cong.ngu_canh import co_quyen
	from nppsale.su_kien.cong_no import chieu_hoa_don, chieu_phieu_tra

	doc = _khoa_phieu(pt)
	if not co_quyen(nc, "returns.approve"):
		raise NppLoi("FORBIDDEN: bạn không có quyền hoàn thành đơn trả")
	tt = doc.trang_thai
	if tt == "draft" and not doc.tu_sinh and not (doc.don_hang and not doc.hoa_don):
		tt = "submitted"  # mig 191: phiếu tự lập đi Nháp → Hoàn thành
	if tt != "submitted":
		raise NppLoi("RETURN_NOT_SUBMITTED: phiếu trả không ở Phiếu tạm")
	if zone not in VUNG_KHO:
		raise NppLoi("BAD_ZONE: kho nhận phải là sale hoặc date")
	if doc.hoa_don:
		if frappe.db.get_value("Sales Invoice", doc.hoa_don, "docstatus") != 1:
			raise NppLoi("INVOICE_NOT_POSTED: hóa đơn gốc đã bị huỷ — hàng của nó đã hoàn về kho rồi, không nhập trả lần nữa")
	elif doc.don_hang:
		if frappe.db.get_value("Sales Order", doc.don_hang, "npp_trang_thai") not in ("partially_invoiced", "completed", "closed"):
			raise NppLoi("ORDER_NOT_COMPLETED: đơn gốc chưa xuất hàng, không nhập trả được")
		# mig 200: gắn HĐ ghi sổ duy nhất của đơn TRƯỚC khi lập chứng từ (tờ ghi có mang đúng HĐ gốc)
		ds = frappe.get_all("Sales Invoice", filters={"npp_don_hang": doc.don_hang, "docstatus": 1, "is_return": 0}, pluck="name",
			order_by="name asc")
		if not ds:
			raise NppLoi("RETURN_NEEDS_INVOICE: đơn gốc chưa có hóa đơn đã xuất — phiếu trả hoàn thành phải gắn với một hóa đơn đã xuất")
		if len(ds) > 1:
			raise NppLoi(f"RETURN_NEEDS_INVOICE: đơn có {len(ds)} hóa đơn đã xuất — chọn hóa đơn cho phiếu trả trước khi hoàn thành")
		doc.hoa_don = ds[0]
		doc.nhan_vien = frappe.db.get_value("Sales Invoice", ds[0], "npp_nhan_vien") or doc.nhan_vien
	kho = _kho_cua(zone, cd)
	bay_gio = now_datetime()
	luc = bay_gio if ngay is None or ngay == bay_gio.date() else _dt.datetime.combine(ngay, _dt.time(12, 0))
	co_dong = any(flt(d.so_luong) > 0 for d in doc.dong)
	chung_tu = None
	if co_dong:
		if doc.tu_sinh or not flt(doc.tien_tra):
			chung_tu = _lap_phieu_nhap(doc, kho, zone, luc, cd)
			doc.phieu_nhap_kho = chung_tu
		else:
			chung_tu = _lap_to_ghi_co_co_kho(doc, kho, zone, luc, cd)
			doc.to_ghi_co = chung_tu
	doc.update({"trang_thai": "completed", "hoan_thanh_luc": luc, "hoan_thanh_boi": nc.user if nc.vai else None, "kho_nhan": kho})
	doc.flags.qua_rpc = True
	doc.flags.cot_ghi = {"trang_thai", "hoa_don", "nhan_vien"}
	doc.flags.ignore_permissions = True
	doc.save()
	if doc.hoa_don:
		chieu_hoa_don(doc.hoa_don)
	elif not doc.don_hang:
		chieu_phieu_tra(doc.name)
	from nppsale.npp_he_thong.doctype.npp_thong_bao.npp_thong_bao import gui_thong_bao

	gui_thong_bao(doc.owner, "return_completed", "Phiếu trả đã hoàn thành", None, f"/returns/{doc.name}")
	return chung_tu


def _huy_chung_tu(dt: str, ten: str | None):
	"""Huỷ chứng từ lõi nhập lại (lõi đảo kho theo gói lô). Hàng nhập lại đã bán tiếp → lõi chặn lô âm (CFD-05; nppsale cho lô âm — ⚠ Q5)."""
	if not ten:
		return False
	d = frappe.get_doc(dt, ten)
	if d.docstatus != 1:
		return False
	d.flags.ignore_permissions = True
	try:
		d.cancel()
	except (frappe.ValidationError,) as e:
		if "NegativeStock" in type(e).__name__ or "negative" in str(e).lower() or "âm" in str(e):
			raise NppLoi("RETURN_STOCK_USED: hàng nhập lại của phiếu trả đã xuất đi tiếp — tồn lô không đủ để đảo nhập kho") from e
		raise
	frappe.local.message_log = []
	return True


def _huy(doc, ly_do, nc, cd):
	"""Thân cancel_return (mig 120 / 127 / 190 / 191 / 213): nháp rỗng → huỷ; nháp / chờ → huỷ (tự sinh, theo đơn bị chặn); hoàn thành →
	đảo chứng từ nhập (tự sinh về Chờ xử lý, tờ ghi có không kho giữ — nợ giữ nguyên; tự lập → Đã huỷ, nợ tăng lại)."""
	from frappe.utils import now_datetime

	from nppsale.cong.ngu_canh import co_quyen
	from nppsale.su_kien.cong_no import chieu_hoa_don, chieu_phieu_tra

	if not co_quyen(nc, "returns.approve"):
		raise NppLoi("FORBIDDEN: bạn không có quyền huỷ đơn trả")
	hd, don = doc.hoa_don, doc.don_hang
	if doc.trang_thai == "draft" and not doc.dong:
		doc.update({"trang_thai": "cancelled", "huy_luc": now_datetime(), "ly_do_huy": ly_do})
		_luu_rpc(doc, {"trang_thai"})
		return
	if doc.trang_thai in ("draft", "submitted"):
		if doc.tu_sinh:
			raise NppLoi("RETURN_FOLLOWS_INVOICE: phiếu trả tự sinh theo hóa đơn — muốn bỏ hàng trả thì sửa hóa đơn")
		if doc.trang_thai == "draft" and doc.don_hang and not doc.hoa_don:
			raise NppLoi("RETURN_FOLLOWS_ORDER: hàng trả đi theo đơn hàng — muốn bỏ thì sửa đơn")
		doc.update({"trang_thai": "cancelled", "huy_luc": now_datetime(), "ly_do_huy": ly_do})
		_luu_rpc(doc, {"trang_thai"})
		if hd:
			chieu_hoa_don(hd)
		return
	if doc.trang_thai != "completed":
		raise NppLoi(f"RETURN_NOT_CANCELLABLE: phiếu ở trạng thái {doc.trang_thai} không huỷ được")
	if doc.tu_sinh:
		if not _huy_chung_tu("Stock Entry", doc.phieu_nhap_kho):
			raise NppLoi("NO_IMPORT_TO_REVERSE: không tìm được phiếu nhập của phiếu trả này, phải đảo kho bằng tay")
		doc.update({"trang_thai": "submitted", "hoan_thanh_luc": None, "hoan_thanh_boi": None, "phieu_nhap_kho": None})
		_luu_rpc(doc, {"trang_thai"})
	else:
		da = _huy_chung_tu("Sales Invoice", doc.to_ghi_co) if doc.to_ghi_co else _huy_chung_tu("Stock Entry", doc.phieu_nhap_kho)
		if not da:
			raise NppLoi("NO_IMPORT_TO_REVERSE: không tìm được phiếu nhập của phiếu trả này, phải đảo kho bằng tay")
		doc.update({"trang_thai": "cancelled", "huy_luc": now_datetime(), "ly_do_huy": ly_do, "to_ghi_co": None, "phieu_nhap_kho": None})
		_luu_rpc(doc, {"trang_thai"})
	if hd:
		chieu_hoa_don(hd)
	elif don:
		for x in frappe.get_all("Sales Invoice", filters={"npp_don_hang": don, "docstatus": 1, "is_return": 0}, pluck="name"):
			chieu_hoa_don(x)
	else:
		chieu_phieu_tra(doc.name)


def _luu_rpc(doc, cot: set):
	doc.flags.qua_rpc = True
	doc.flags.cot_ghi = set(cot)
	doc.flags.ignore_permissions = True
	doc.save()


def _chuan_bi_kho_phieu(p_return_id=None, p_zone=None, p_ngay=None, p_reason=None):
	"""Đọc trước khi khoá: người gọi + quyền, cài đặt bán hàng (cổng commit sau bước này rồi hàm khoá Bin)."""
	_chuan_bi_tra()


def _khoa_bin_phieu(pt, cd):
	from nppsale.rpc.xuat_hang import _khoa_bin

	_khoa_bin(set(frappe.get_all("NPP Phieu Tra Dong", filters={"parent": str(pt or ""), "parenttype": DT}, pluck="mat_hang")), cd)


@rpc("complete_return", ghi=True, chuan_bi=_chuan_bi_kho_phieu)
def complete_return(p_return_id=None, p_zone=None, p_ngay=None):
	"""Hoàn thành phiếu trả: nhập kho (tự sinh — nợ đã trừ lúc xuất HĐ) / nhập kho + trừ nợ cùng lúc (tự lập). Bản 3 tham số (p_ngay —
	mig 211: chỉ phiếu tự sinh, ngày ∈ [ngày HĐ, hôm nay]) kiểm ngày TRƯỚC mọi bước của bản 2 tham số."""
	from frappe.utils import getdate

	from nppsale.cong.ngu_canh import hien_tai
	from nppsale.thiet_lap.ban_hang import cai_dat_ban

	nc = hien_tai()
	cd = cai_dat_ban()
	pt = _chu(p_return_id)
	_khoa_bin_phieu(pt, cd)
	ngay = None
	if _chu(p_ngay):
		ngay = _ngay_pg(p_ngay)
		r = frappe.db.get_value(DT, pt, ["name", "tu_sinh", "hoa_don"], as_dict=True) if pt else None
		if not r:
			raise NppLoi("RETURN_NOT_FOUND")
		if not r.tu_sinh:
			raise NppLoi("NGAY_NHAP_CHI_TU_SINH: chỉ phiếu trả tự sinh theo hóa đơn mới chọn ngày nhập kho — phiếu tự lập dùng ngày chứng từ")
		if ngay > getdate(nowdate()):
			raise NppLoi(f"NGAY_NHAP_TUONG_LAI: ngày nhập kho {ngay.strftime('%d/%m/%Y')} sau hôm nay")
		ngay_hd = frappe.db.get_value("Sales Invoice", r.hoa_don, "posting_date") if r.hoa_don else None
		if ngay_hd and ngay < getdate(ngay_hd):
			raise NppLoi(f"NGAY_NHAP_TRUOC_HOA_DON: ngày nhập kho {ngay.strftime('%d/%m/%Y')} trước ngày hóa đơn "
				f"{getdate(ngay_hd).strftime('%d/%m/%Y')}")
	return [{"entry_id": _hoan_thanh(pt, _chu(p_zone), ngay, nc, cd)}]


@rpc("cancel_return", ghi=True, chuan_bi=_chuan_bi_kho_phieu)
def cancel_return(p_return_id=None, p_reason=None):
	"""Huỷ phiếu trả / Huỷ nhập kho (phiếu tự sinh đã nhập kho về Chờ xử lý). Không bắt lý do (như nppsale — ⚠ Q9)."""
	from nppsale.cong.ngu_canh import hien_tai
	from nppsale.thiet_lap.ban_hang import cai_dat_ban

	nc = hien_tai()
	cd = cai_dat_ban()
	pt = _chu(p_return_id)
	_khoa_bin_phieu(pt, cd)
	_huy(_khoa_phieu(pt), p_reason, nc, cd)
	return None
