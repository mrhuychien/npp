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
from frappe.utils import nowdate

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


def _gia_tri(v, truong: str):
	"""Giá trị JSON từ trình duyệt → giá trị trường Frappe ('' của khoá ngoại / lý do → None như NULLIF ở RPC; bool → 0 / 1)."""
	if truong in ("tu_sinh", "hang_doi"):
		return 1 if (v is True or str(v).lower() in ("true", "t", "1")) else 0
	if v == "" and truong in ("hoa_don", "don_hang", "nhan_vien", "ly_do"):
		return None
	return v


def _ap(doc, gia_tri: dict, anh_xa: dict, bo: set, bang: str) -> set:
	cham = set()
	for k, v in gia_tri.items():
		if k in bo:
			continue
		f = anh_xa.get(k)
		if f is None:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{bang}' in the schema cache", http=400)
		doc.set(f, _gia_tri(v, f))
		cham.add(f)
	return cham


# ------------------------------------------------------------------------------------------------ returns
def them_phieu(ds: list[dict], nc) -> list[str]:
	ra = []
	for g in ds:
		g = dict(g or {})
		doc = frappe.new_doc(DT)
		doc.trang_thai = "pending"  # mặc định cột status của nppsale — lập phiếu thẳng không gửi status là bị khoá
		doc.ngay_tra = nowdate()
		cham = _ap(doc, g, COT_PHIEU, COT_PHIEU_BO, "returns")
		if doc.trang_thai != "draft":
			_khoa("phiếu trả lập ra ở Nháp — hoàn thành đi qua nút Hoàn thành")
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
			if doi & CHI_QUA_RPC:
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


def them_dong(ds: list[dict], nc) -> list[str]:
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
			_ap(d, g, COT_DONG, COT_DONG_BO, "return_lines")
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
