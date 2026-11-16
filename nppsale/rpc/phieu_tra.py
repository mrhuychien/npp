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
RETURN_FOLLOWS_INVOICE → PHIEU_TRA_KHOA → 42501 → CHECK → khoá ngoại (móc `kiem_rls` / `kiem_dong_sau` gọi từ controller).

RPC phiếu trả (save_pos_return, create_return_with_lines, complete_return, cancel_return) và phần nối vào bán hàng (đặc tả §3.5, §4):
Xuất hàng (`ap_tra_them` / `phieu_cho_cua_don` → câu gắn `gan_phieu_theo_don` → `ap_sua_tra` → `dong_bo_to_ghi_co`), Huỷ HĐ (huỷ tờ
ghi có trước → `huy_phieu_khi_huy_hd` → `huy_phieu_theo_don`), Sửa HĐ (`tra_da_nhap_truoc` → `go_phieu_khoi_hd` → `sau_lap_lai`), đổi
người HĐ (`doi_nguoi_theo_hd`), công nợ theo người đứng tên (`cong_no_doi_nguoi`). Tờ ghi có KHÔNG kho `HDT-` của phiếu tự sinh luôn khớp
dòng + tiền của phiếu (huỷ / lập lại amend); tổng tờ = đúng tiền trả nppsale (`_khop_tong`, ⚠ Q2). Quyết định tạm Q1–Q14:
docs/chuyen-doi/blueprint/00_quyet_dinh_trien_khai.md mục Q6.
"""
from __future__ import annotations

import frappe
from frappe.utils import flt, nowdate

from nppsale.cong.loi import NppLoi
from nppsale.cong.sql import LoiCong

from . import rpc

DT = "NPP Phieu Tra"
VAI_LAP = ("owner", "manager", "sales")
VAI_DUYET = ("owner", "manager")

# cột nppsale → trường NPP Phieu Tra (ghi thẳng); cột bỏ qua khi gửi lên (máy tự lo hoặc không port)
COT_PHIEU = {"customer_id": "khach_hang", "invoice_id": "hoa_don", "order_id": "don_hang", "reason": "ly_do", "notes": "ghi_chu",
	"status": "trang_thai", "return_date": "ngay_tra", "sales_user_id": "nhan_vien", "credit_note_amount": "tien_tra",
	"revenue_date": "ngay_tru_doanh_so", "credit_with_invoice": "tu_sinh", "completed_at": "hoan_thanh_luc", "credited_at": "ghi_co_luc",
	"cancel_reason": "ly_do_huy", "cancelled_at": "huy_luc", "completed_by": "hoan_thanh_boi", "destination_zone": "kho_nhan"}
COT_PHIEU_BO = {"id", "org_id", "requested_by", "created_at", "updated_at", "return_code", "return_seq", "tim_kd", "approved_by",
	"photo_url", "applied_receipt_id"}
ZONE_SAI = "__zone_sai__"  # destination_zone ngoài {sale, date}: controller báo CHECK chk_returns_destination_zone đúng chỗ (sau trigger)
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
	if truong in ("hoan_thanh_luc", "huy_luc", "ghi_co_luc"):  # timestamptz của nppsale (ISO có múi giờ) → giờ site không múi giờ
		from nppsale.cong.bang._chung import gio_vao

		return gio_vao(v)
	if truong == "ngay_tra" and isinstance(v, str) and v:
		return _ngay_pg(v)
	if truong == "kho_nhan":  # destination_zone: vùng kho nppsale → kho của NPP Cai Dat
		if v is None:
			return None
		from nppsale.thiet_lap.ban_hang import cai_dat_ban

		return _kho_cua(v, cai_dat_ban()) if v in VUNG_KHO else ZONE_SAI
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
		doc.flags.cot_ghi = cham
		doc.flags.ignore_permissions = True
		# WITH CHECK của "Sales can create returns" chạy sau trigger BEFORE, trước NOT NULL / CHECK / khoá ngoại
		doc.flags.kiem_rls = (lambda: _rls_ghi("returns")) if nc.vai not in VAI_LAP and not nc.bo_qua_rls else None
		doc.insert()
		ra.append(doc.name)
	return ra


def thay_phieu(ten: str, nc) -> bool:
	"""Người gọi đọc được phiếu theo RLS (cổng `_ve_phieu`) — trigger INVOKER của nppsale đọc phiếu cha dưới quyền người gọi."""
	if nc.bo_qua_rls or nc.vai in ("owner", "manager", "accountant", "warehouse"):
		return bool(frappe.db.exists(DT, ten))
	if nc.vai != "sales":
		return False
	r = frappe.db.get_value(DT, ten, ["owner", "nhan_vien", "hoa_don", "don_hang"], as_dict=True)
	if not r:
		return False
	return nc.user in (r.owner, r.nhan_vien) or (bool(r.hoa_don) and frappe.db.get_value("Sales Invoice", r.hoa_don, "npp_nhan_vien") == nc.user) \
		or (bool(r.don_hang) and frappe.db.get_value("Sales Order", r.don_hang, "npp_nhan_vien") == nc.user)


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
		# WITH CHECK của "Sales can update own draft returns": sau trigger BEFORE (người đứng tên có thể đã đổi theo HĐ vừa gắn)
		doc.flags.kiem_rls = (lambda d=doc: _rls_ghi("returns") if not (d.nhan_vien == nc.user and d.trang_thai == "draft") else None) \
			if not nc.bo_qua_rls and nc.vai == "sales" else None
		doc.save()
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


def _khoa_dong(doc, nc, chen: bool = False):
	"""Thứ tự trigger dòng sau trần giá (trần chạy trong validate): tự sinh → khoá Nháp — hai trigger INVOKER đọc phiếu cha dưới RLS của
	người gọi (không thấy → không phải tự sinh, trạng thái '?'); rồi WITH CHECK của RLS dòng (lúc chèn: vai owner / manager / sales)."""
	if nc.bo_qua_rls:
		return
	thay = thay_phieu(doc.name, nc)
	cu = frappe.db.get_value(DT, doc.name, ["tu_sinh", "trang_thai"], as_dict=True) if thay else None
	if cu and cu.tu_sinh:
		raise NppLoi("RETURN_FOLLOWS_INVOICE: phiếu trả tự sinh theo hóa đơn — muốn sửa thì sửa hóa đơn")
	tt = cu.trang_thai if cu else None
	if tt != "draft":
		_khoa(f"dòng hàng chỉ sửa được khi phiếu trả còn Nháp (đang {tt or '?'})")
	if chen and not _duoc_ghi_dong(nc):
		_rls_ghi("return_lines")


def them_dong(ds: list[dict], nc, nullif: set = frozenset()) -> list[str]:
	ra = []
	theo_phieu: dict = {}
	for g in ds:
		g = dict(g or {})
		pt = g.get("return_id")
		if not pt or not frappe.db.exists(DT, pt):
			# phiếu cha không có: khoá Nháp (INVOKER) không đọc được trạng thái → '?' — ra trước WITH CHECK và khoá ngoại
			if not nc.bo_qua_rls:
				_khoa("dòng hàng chỉ sửa được khi phiếu trả còn Nháp (đang ?)")
			_rls_ghi("return_lines")
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
		_luu_dong(doc, nc, chen=True)
		ra += [d.name for d in moi]
	return ra


def _luu_dong(doc, nc, chen: bool = False):
	"""Lưu phiếu sau khi đổi dòng: validate chạy đơn vị / thành tiền / trần giá trước, rồi khoá tự sinh / Nháp / RLS như thứ tự trigger."""
	doc.flags.ignore_permissions = True
	doc.flags.cot_ghi = set()
	doc.flags.kiem_dong_sau = (lambda: _khoa_dong(doc, nc, chen))
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
	doc.save()  # on_update của phiếu: tờ ghi có + dòng nợ âm theo người mới (_phieu_tra_doi_nguoi_cong_no)


def cong_no_doi_nguoi(doc):
	"""_phieu_tra_doi_nguoi_cong_no (mig 194): tờ ghi có đang hiệu lực của phiếu mang người đứng tên mới; dòng nợ âm của phiếu độc lập (người
	giữ ở ba trường của tờ) đổi theo luật giữ nợ (`_cong_no_giu_ve_npp` — nợ đã về NPP đứng yên, người mới đã nghỉ thì giữ người cũ)."""
	from frappe.utils import now_datetime

	from nppsale.luat.giu_no import GiuNo, khi_doi_nguoi
	from nppsale.rpc.gan_nguoi import da_nghi
	from nppsale.su_kien.cong_no import chieu_phieu_tra

	to = frappe.db.get_value("Sales Invoice", doc.to_ghi_co, ["docstatus", "npp_nhan_vien", "npp_nv_giu_no", "npp_ve_npp_luc",
		"npp_giao_tu_nv", "npp_hoa_don_goc"], as_dict=True) if doc.to_ghi_co else None
	if not to or to.docstatus != 1:
		return
	gt = {}
	if to.npp_nhan_vien != doc.nhan_vien:
		gt["npp_nhan_vien"] = doc.nhan_vien
	if not to.npp_hoa_don_goc and to.npp_nv_giu_no != doc.nhan_vien:
		moi = khi_doi_nguoi(GiuNo(to.npp_nv_giu_no, to.npp_ve_npp_luc, to.npp_giao_tu_nv), doc.nhan_vien, da_nghi, now_datetime())
		gt.update({"npp_nv_giu_no": moi.nv, "npp_ve_npp_luc": moi.ve_npp, "npp_giao_tu_nv": moi.giao})
	if gt:
		frappe.db.set_value("Sales Invoice", doc.to_ghi_co, gt, update_modified=False)
	chieu_phieu_tra(doc.name)


def doi_nguoi_theo_hd(hd: str, nv: str) -> None:
	"""_hoa_don_doi_nguoi (mig 194): đổi người đứng tên HĐ → phiếu trả gắn HĐ (mọi trạng thái, IS DISTINCT FROM) đổi theo; tờ ghi có
	đang hiệu lực của phiếu mang người mới (dòng nợ của chúng là dòng của HĐ — người giữ do HĐ quyết)."""
	for ten in frappe.get_all(DT, filters={"hoa_don": hd}, pluck="name", order_by="creation asc, name asc"):
		doc = frappe.get_doc(DT, ten)
		if doc.nhan_vien != nv:
			doc.nhan_vien = nv
			_luu_rpc(doc, {"nhan_vien"})
	for t in frappe.get_all("Sales Invoice", filters={"is_return": 1, "npp_hoa_don_goc": hd, "docstatus": 1},
			fields=["name", "npp_nhan_vien"]):
		if t.npp_nhan_vien != nv:
			frappe.db.set_value("Sales Invoice", t.name, "npp_nhan_vien", nv, update_modified=False)


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
		to_cu = doc.to_ghi_co
		if doc.trang_thai == "completed":
			if not complete:
				raise NppLoi("RETURN_COMPLETED: phiếu đã nhập kho — sửa xong phải bấm Ghi nhận để kho và công nợ đổi theo")
			if kh != doc.khach_hang:  # _cong_no_phieu_tra (mig 191): dư có đã bị rút ở phiếu thu → không đổi khách (kiểm trước khi huỷ chứng từ)
				from .can_tru import kiem_doi_khach_phieu_tra

				kiem_doi_khach_phieu_tra(doc.name, kh)
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
		_hoan_thanh(doc.name, zone, None, nc, cd, to_cu=to_cu if rid else None)
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
	kho, gói lô Inward do app lập (lô hết hạn vẫn nhận — PoC 9) — hàm dùng chung `nppsale.rpc.goi_lo`."""
	from .goi_lo import gan_goi_lo, lap_goi_lo

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
			gan_goi_lo(r, lap_goi_lo("Inward", "Stock Entry", d.mat_hang, kho, {lo: flt(d.so_luong) * hs}, se.posting_date, se.posting_time,
				cd.cong_ty))
	se.flags.ignore_permissions = True
	se.insert()
	se.submit()
	frappe.local.message_log = []
	return se.name


def _lap_to_ghi_co_co_kho(doc, kho: str, zone: str, luc, cd, to_cu: str | None = None) -> str:
	"""Tờ ghi có CÓ KHO `HDT-` của phiếu tự lập: mọi dòng SL > 0 (SL âm), dòng đổi theo luật dòng 0 đ, giá vốn nhập lại tự đặt theo đơn vị
	kho rồi ghi sổ ngay (lưu lại tờ nháp đổi dòng là lõi xoá giá — PoC 5). Gắn HĐ thì npp_hoa_don_goc (nợ trừ vào HĐ), không thì dòng âm."""
	from frappe.utils import now_datetime

	from nppsale.luat.giu_no import khi_lap
	from nppsale.rpc.don_hang import _bang_gia_nhom, _gia_bang
	from nppsale.rpc.gan_nguoi import da_nghi
	from nppsale.thiet_lap.ban_hang import mau_thue_dong
	from nppsale.su_kien.san_pham import bang_gia_chung

	g = khi_lap(doc.nhan_vien, da_nghi, now_datetime())
	cu_giu = frappe.db.get_value("Sales Invoice", to_cu, ["npp_nv_giu_no", "npp_ve_npp_luc", "npp_giao_tu_nv"], as_dict=True) \
		if to_cu else None
	if cu_giu:  # ghi nhận lại: `_cong_no_phieu_tra` UPDATE dòng nợ → `_cong_no_giu_ve_npp` giữ người đang giữ (nợ về NPP đứng yên, dấu bàn giao)
		from nppsale.luat.giu_no import GiuNo, khi_doi_nguoi

		g = khi_doi_nguoi(GiuNo(cu_giu.npp_nv_giu_no, cu_giu.npp_ve_npp_luc, cu_giu.npp_giao_tu_nv), doc.nhan_vien, da_nghi, now_datetime())
	bang = _bang_gia_nhom(doc.khach_hang) or bang_gia_chung()
	cn = frappe.new_doc("Sales Invoice")
	cn.update({"naming_series": "HDT-.####", "customer": doc.khach_hang, "company": cd.cong_ty, "is_return": 1, "update_stock": 1,
		"set_warehouse": kho, "set_posting_time": 1, "posting_date": luc.date(), "posting_time": luc.strftime("%H:%M:%S"),
		"selling_price_list": bang, "ignore_pricing_rule": 1, "disable_rounded_total": 1, "taxes_and_charges": cd.mau_thue_ban,
		"npp_hoa_don_goc": doc.hoa_don or None, "npp_phieu_tra": doc.name, "npp_nhan_vien": doc.nhan_vien, "npp_nv_giu_no": g.nv,
		"npp_ve_npp_luc": g.ve_npp, "npp_giao_tu_nv": g.giao, "update_outstanding_for_self": 1, "due_date": luc.date()})
	if to_cu and frappe.db.get_value("Sales Invoice", to_cu, "docstatus") == 2:
		cn.amended_from = to_cu  # ghi nhận lại phiếu tự lập: amend tờ cũ (HDT-x-n), số PT giữ (bàn bạc 6.11)
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
	_khop_tong(cn, -flt(doc.tien_tra), cd)
	cn.flags.ignore_permissions = True
	cn.insert()
	cn.submit()
	frappe.local.message_log = []
	return cn.name


def _khop_tong(cn, muc_tieu: float, cd) -> None:
	"""⚠ Q2 (đặc tả §7.1): tiền trả nppsale = Σ round(SL × giá × (1 + thuế)) TỪNG DÒNG, đơn giá trả được 2 số lẻ (mig 181); lõi làm tròn đơn
	giá / tiền dòng / thuế theo độ chính xác tiền (VND 0 số lẻ) → tổng tờ lệch vài đồng (vd 3 × 3.333,5 = 10.001 ở nppsale, 10.002 ở lõi).
	Công nợ là nguồn sự thật → bù đúng phần lệch bằng giảm giá SAU thuế (is_cash_or_non_trade_discount — cùng cách giảm giá cả đơn của HĐ,
	không đổi nền thuế) để grand_total = −tiền trả. Tính trước khi lưu (lưu lại tờ nháp có kho làm lõi xoá giá vốn tự đặt — PoC 5)."""
	cn.run_method("set_missing_values")
	cn.calculate_taxes_and_totals()
	lech = flt(cn.grand_total) - flt(muc_tieu)
	if abs(lech) >= 0.5:
		cn.update({"apply_discount_on": "Grand Total", "is_cash_or_non_trade_discount": 1, "discount_amount": lech,
			"additional_discount_account": cd.tk_giam_gia_don})


def _khoa_phieu(pt) -> object:
	r = frappe.db.sql(f"SELECT `name` FROM `tab{DT}` WHERE `name` = %s FOR UPDATE", (str(pt or ""),))
	if not r:
		raise NppLoi("RETURN_NOT_FOUND")
	return frappe.get_doc(DT, pt)


def _hoan_thanh(pt: str, zone, ngay, nc, cd, to_cu: str | None = None):
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
		# ⚠ Q15: PG gắn HĐ trong lệnh UPDATE chỉ có status / completed_* nên trigger khách–HĐ (mig 212) không chạy — phiếu khách khác
		# gắn được HĐ và trừ vào nợ khách HĐ. Chủ nhà chốt "khách phiếu = khách HĐ" (mig 212) → chặn ở đây, trước khi lập chứng từ.
		if frappe.db.get_value("Sales Invoice", ds[0], "customer") != doc.khach_hang:
			raise NppLoi("INVOICE_CUSTOMER_MISMATCH: hóa đơn gốc là của khách khác — phiếu trả phải cùng khách với hóa đơn")
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
			chung_tu = _lap_to_ghi_co_co_kho(doc, kho, zone, luc, cd, to_cu)
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
	if frappe.db.get_value(dt, ten, "docstatus") != 1:
		return False
	if dt == "Sales Invoice":  # tờ ghi có có kho đang là nguồn dư có của bút toán cấn trừ → huỷ bút toán trước (đọc tờ SAU — huỷ bút toán
		from .can_tru import truoc_huy_to_ghi_co  # chạm `modified` của tờ), lập lại cuối lời gọi

		truoc_huy_to_ghi_co(ten)
	d = frappe.get_doc(dt, ten)
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


# ================================================================================================ nối vào Xuất / Huỷ / Sửa HĐ (đặc tả §3.5, §4)
def _he_so_dm(hang: str, don_vi: str | None):
	"""Hệ số của đơn vị trong danh mục: đơn vị cơ sở → 1; có trong Item.uoms → hệ số; không có → None (product_units của nppsale)."""
	if not don_vi:
		return None
	if don_vi == frappe.db.get_value("Item", hang, "stock_uom"):
		return 1.0
	v = frappe.db.get_value("UOM Conversion Detail", {"parent": hang, "parenttype": "Item", "uom": don_vi}, "conversion_factor")
	return flt(v) if v is not None else None


def phieu_cho_cua_don(don: str, hd: str | None, *, qua_rpc: bool):
	"""_pending_return_for (mig 152 / 189): phiếu CŨ NHẤT của đơn ở Nháp / Chờ xử lý chưa gắn HĐ (hoặc gắn đúng HĐ) → dùng lại; không có →
	lập phiếu nháp theo đơn (khách = khách đơn, lý do 'damaged', KHÔNG gắn HĐ — câu gắn sẽ bắt)."""
	if not don:
		raise NppLoi("ORDER_NOT_FOUND")
	for r in frappe.get_all(DT, filters={"don_hang": don, "trang_thai": ["in", ["draft", "submitted"]]}, fields=["name", "hoa_don"],
			order_by="creation asc, name asc"):
		if not r.hoa_don or r.hoa_don == hd:
			return frappe.get_doc(DT, r.name)
	kh = frappe.db.get_value("Sales Order", don, "customer")
	if not kh:
		raise NppLoi("ORDER_NOT_FOUND")
	doc = frappe.new_doc(DT)
	doc.update({"don_hang": don, "khach_hang": kh, "trang_thai": "draft", "ly_do": "damaged", "ngay_tra": frappe.utils.getdate(nowdate())})
	doc.flags.qua_rpc = qua_rpc
	doc.flags.cot_ghi = {"don_hang", "khach_hang", "trang_thai", "ly_do", "ngay_tra"}
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def ap_tra_them(don: str, hd: str | None, adds, *, qua_rpc: bool) -> int:
	"""_apply_return_adds (mig 152 / 183 / 227): dòng trả / đổi thêm lúc Xuất / Sửa HĐ vào phiếu chờ của đơn (dựng nếu chưa có — kể cả khi
	mọi phần tử SL ≤ 0). Trần giá theo vai người gọi, tham chiếu theo HĐ phiếu đang gắn lúc chèn."""
	if not isinstance(adds, list) or not adds:
		return 0
	for x in adds:
		if isinstance(x, dict) and _so(x.get("quantity")) > 0 and (_so(x.get("unit_price")) < 0 or not (0 <= _so(x.get("vat_rate")) <= 1)):
			raise NppLoi("BAD_PAYLOAD: đơn giá hàng trả không được âm, thuế phải trong khoảng 0 – 1 (0 – 100 phần trăm)")
	doc = phieu_cho_cua_don(don, hd, qua_rpc=qua_rpc)
	n = 0
	for x in adds:
		if not isinstance(x, dict) or _so(x.get("quantity")) <= 0:
			continue
		doc.append("dong", {"mat_hang": _chu(x.get("product_id")), "don_vi": x.get("unit_name") or "", "so_luong": _so(x.get("quantity")),
			"don_gia": _so(x.get("unit_price")), "thue_suat": _so(x.get("vat_rate")),
			"hang_doi": 1 if _bool_pg(x.get("is_exchange")) else 0, "ghi_chu": _chu(x.get("note")), "ly_do": _chu(x.get("reason"))})
		n += 1
	if n:
		_luu_rpc(doc, set())  # chèn dòng: guard người đứng tên không chạy (UPDATE OF sales_user_id); trần giá theo vai người gọi
	return n


def gan_phieu_theo_don(don: str, hd: str, giu=()) -> None:
	"""Câu gắn của post_invoice (mig 131 / 133 / 189 / 213): MỌI phiếu theo đơn chưa gắn HĐ, Nháp / Chờ xử lý (trừ phiếu tự lập Sửa HĐ giữ
	lại) → Chờ xử lý, gắn HĐ, tự sinh — nợ HĐ trừ ngay, doanh số trừ theo ngày HĐ."""
	for ten in frappe.get_all(DT, filters={"don_hang": don, "trang_thai": ["in", ["draft", "submitted"]], "hoa_don": ["is", "not set"]},
			pluck="name", order_by="creation asc, name asc"):
		if ten in (giu or ()):
			continue
		doc = frappe.get_doc(DT, ten)
		doc.update({"trang_thai": "submitted", "hoa_don": hd, "tu_sinh": 1})
		_luu_rpc(doc, {"trang_thai", "hoa_don", "tu_sinh"})


def ap_sua_tra(hd: str, edits) -> int:
	"""_apply_return_edits (mig 149 / 181 / 183): sửa / xoá dòng của phiếu Nháp / Chờ xử lý gắn HĐ — SL ≤ 0 xoá; đổi quy cách quy giá theo hệ
	số (2 số lẻ); dòng lạ / phiếu khác HĐ / phiếu đã xong bỏ qua im lặng. → số phần tử đã áp."""
	from decimal import ROUND_HALF_UP, Decimal

	if not isinstance(edits, list):
		return 0
	n = 0
	for e in edits:
		if not isinstance(e, dict):
			continue
		lid = _chu(e.get("line_id"))
		r = frappe.db.sql(f"""SELECT d.`parent` FROM `tabNPP Phieu Tra Dong` d JOIN `tab{DT}` p ON p.`name` = d.`parent`
			WHERE d.`name` = %s AND p.`hoa_don` = %s AND p.`trang_thai` IN ('draft', 'submitted')""", (lid, hd)) if lid else None
		if not r:
			continue
		doc = frappe.get_doc(DT, r[0][0])
		d = next(x for x in doc.dong if x.name == lid)
		sl = _so(e.get("quantity"))
		if sl <= 0:
			doc.set("dong", [x for x in doc.dong if x.name != lid])
		else:
			dv_moi = (_chu(e.get("unit_name")) or "").strip() or None
			if dv_moi and dv_moi != d.don_vi:
				hs_moi = _he_so_dm(d.mat_hang, dv_moi)
				if not hs_moi or hs_moi <= 0:
					raise NppLoi(f'RETURN_UNIT_UNKNOWN: đơn vị "{dv_moi}" không có trong danh mục của mặt hàng')
				hs_cu = _he_so_dm(d.mat_hang, d.don_vi)
				if not hs_cu or hs_cu <= 0:
					raise NppLoi(f'RETURN_UNIT_UNKNOWN: đơn vị cũ "{d.don_vi}" không còn trong danh mục — không quy được giá')
				d.don_gia = float((Decimal(str(flt(d.don_gia))) * Decimal(str(hs_moi)) / Decimal(str(hs_cu))).quantize(Decimal("0.01"),
					rounding=ROUND_HALF_UP))
				d.don_vi = dv_moi
			d.so_luong = sl
			if "note" in e:
				d.ghi_chu = _chu(e.get("note"))
			if "reason" in e:
				d.ly_do = _chu(e.get("reason"))
		_luu_rpc(doc, set())
		n += 1
	return n


def _huy_to_ghi_co(ten: str, ly_do: str | None = None):
	from frappe.utils import now_datetime

	from nppsale.cong.ngu_canh import hien_tai

	if frappe.db.get_value("Sales Invoice", ten, "docstatus") != 1:
		return
	from .can_tru import truoc_huy_to_ghi_co

	truoc_huy_to_ghi_co(ten)  # bút toán cấn trừ đang trỏ tờ: huỷ trước (lõi gỡ tham chiếu lặng lẽ), lập lại cuối lời gọi RPC
	cn = frappe.get_doc("Sales Invoice", ten)  # đọc SAU khi huỷ bút toán (lõi chạm `modified` của tờ)
	nc = hien_tai()
	cn.npp_ly_do_huy = ly_do
	cn.npp_huy_luc = now_datetime()
	cn.npp_huy_boi = nc.user if frappe.db.exists("NPP Nhan Vien", nc.user) else None
	cn.flags.ignore_permissions = True
	cn.cancel()
	frappe.local.message_log = []


def _lap_to_ghi_co_khong_kho(doc, hd: str, cu: str | None, cd) -> str:
	"""Tờ ghi có KHÔNG kho `HDT-` của phiếu tự sinh (blueprint §3.5.6): chỉ dòng tiền (không hàng đổi), SL âm, ngày = ngày HĐ, giờ = giờ HĐ
	+ vài giây; trừ vào nợ HĐ qua npp_hoa_don_goc. Lập lại sau sửa → amend tờ cũ (HDT-x-n — ⚠ Q14)."""
	import datetime as _dt

	from frappe.utils import get_time, now_datetime

	from nppsale.luat.giu_no import khi_lap
	from nppsale.rpc.don_hang import _bang_gia_nhom
	from nppsale.rpc.gan_nguoi import da_nghi
	from nppsale.su_kien.san_pham import bang_gia_chung
	from nppsale.thiet_lap.ban_hang import mau_thue_dong

	h = frappe.db.get_value("Sales Invoice", hd, ["customer", "posting_date", "posting_time"], as_dict=True)
	gio = (_dt.datetime.combine(_dt.date(2000, 1, 1), get_time(h.posting_time)) + _dt.timedelta(seconds=5)).time()
	if gio < get_time(h.posting_time):  # vượt nửa đêm → kẹp 23:59:59
		gio = _dt.time(23, 59, 59)
	g = khi_lap(doc.nhan_vien, da_nghi, now_datetime())
	cn = frappe.new_doc("Sales Invoice")
	cn.update({"naming_series": "HDT-.####", "customer": h.customer, "company": cd.cong_ty, "is_return": 1, "update_stock": 0,
		"set_posting_time": 1, "posting_date": h.posting_date, "posting_time": gio.strftime("%H:%M:%S"),
		"selling_price_list": _bang_gia_nhom(h.customer) or bang_gia_chung(), "ignore_pricing_rule": 1, "disable_rounded_total": 1,
		"taxes_and_charges": cd.mau_thue_ban, "npp_hoa_don_goc": hd, "npp_phieu_tra": doc.name, "npp_nhan_vien": doc.nhan_vien,
		"npp_nv_giu_no": g.nv, "npp_ve_npp_luc": g.ve_npp, "update_outstanding_for_self": 1, "due_date": h.posting_date})
	if cu:
		cn.amended_from = cu
	for d in doc.dong:
		if d.hang_doi or flt(d.so_luong) == 0:
			continue
		hs = _he_so(d.mat_hang, d.don_vi)
		if flt(d.he_so_quy_doi) != hs:
			frappe.db.set_value("NPP Phieu Tra Dong", d.name, "he_so_quy_doi", hs, update_modified=False)
			d.he_so_quy_doi = hs
		cn.append("items", {"item_code": d.mat_hang, "qty": -flt(d.so_luong), "uom": d.don_vi, "conversion_factor": hs,
			"rate": flt(d.don_gia), "price_list_rate": flt(d.don_gia), "discount_percentage": 0, "discount_amount": 0, "margin_type": "",
			"margin_rate_or_amount": 0, "item_tax_template": mau_thue_dong(flt(d.thue_suat), cd.cong_ty), "npp_thue_suat": flt(d.thue_suat),
			"npp_ghi_chu": d.ghi_chu})
	from erpnext.controllers.accounts_controller import _get_taxes_and_charges

	for t in _get_taxes_and_charges("Sales Taxes and Charges Template", cd.mau_thue_ban) or []:
		cn.append("taxes", t)
	_khop_tong(cn, -flt(doc.tien_tra), cd)
	cn.flags.ignore_permissions = True
	cn.insert()
	cn.submit()
	frappe.local.message_log = []
	return cn.name


def _chu_ky_to(ten: str) -> tuple:
	return tuple(sorted((r.item_code, r.uom, round(-flt(r.qty), 6), round(flt(r.rate), 4), round(flt(r.npp_thue_suat), 4))
		for r in frappe.get_all("Sales Invoice Item", filters={"parent": ten, "parenttype": "Sales Invoice"},
			fields=["item_code", "uom", "qty", "rate", "npp_thue_suat"])))


def dong_bo_to_ghi_co(hd: str, cd=None) -> None:
	"""Giữ tờ ghi có KHÔNG kho khớp phiếu tự sinh của HĐ (thay cho việc nppsale tính sống credit_note_amount — mig 133): phiếu tự sinh Chờ xử
	lý / Hoàn thành có tiền → đúng một tờ đang ghi sổ cùng dòng; lệch → huỷ tờ cũ, lập lại (amend); không tiền / rời HĐ → không còn tờ."""
	from nppsale.thiet_lap.ban_hang import cai_dat_ban

	cd = cd or cai_dat_ban()
	can = {}
	for r in frappe.get_all(DT, filters={"hoa_don": hd, "tu_sinh": 1, "trang_thai": ["in", ["submitted", "completed"]]}, pluck="name"):
		doc = frappe.get_doc(DT, r)
		can[doc.name] = doc
	# tờ không kho đang ghi sổ của HĐ (cả của phiếu đã rời HĐ)
	dang = frappe.get_all("Sales Invoice", filters={"is_return": 1, "update_stock": 0, "npp_hoa_don_goc": hd, "docstatus": 1},
		fields=["name", "npp_phieu_tra", "grand_total"], order_by="creation asc")
	theo_pt: dict = {}
	for t in dang:
		theo_pt.setdefault(t.npp_phieu_tra, []).append(t)
	for pt, ds in theo_pt.items():
		if pt not in can:
			for t in ds:
				_huy_to_ghi_co(t.name)
	for pt, doc in can.items():
		ds = theo_pt.get(pt, [])
		# SL không kiểm dấu ở nppsale (dòng SL âm làm tiền trả âm — nợ HĐ tăng lại): mọi dòng tiền SL ≠ 0 lên tờ
		can_to = any(not d.hang_doi and flt(d.so_luong) != 0 for d in doc.dong) and flt(doc.tien_tra) != 0
		ky = tuple(sorted((d.mat_hang, d.don_vi, round(flt(d.so_luong), 6), round(flt(d.don_gia), 4), round(flt(d.thue_suat), 4))
			for d in doc.dong if not d.hang_doi and flt(d.so_luong) != 0))
		if can_to and len(ds) == 1 and _chu_ky_to(ds[0].name) == ky:
			if doc.to_ghi_co != ds[0].name:
				doc.db_set("to_ghi_co", ds[0].name, update_modified=False)
			continue
		for t in ds:
			_huy_to_ghi_co(t.name)
		if not can_to:
			continue  # to_ghi_co giữ tên tờ đã huỷ: lần lập sau amend tiếp (HDT-x-n — ⚠ Q14)
		goc = ds[-1].name if ds else doc.to_ghi_co
		if goc and frappe.db.get_value("Sales Invoice", goc, "docstatus") != 2:
			goc = None
		doc.db_set("to_ghi_co", _lap_to_ghi_co_khong_kho(doc, hd, goc, cd), update_modified=False)


def huy_phieu_khi_huy_hd(hd: str, ma_hd: str) -> None:
	"""cancel_invoice sau khi huỷ HĐ (mig 131 / 135): phiếu tự sinh theo đơn → gỡ HĐ, về Nháp, bỏ cờ tự sinh (huỷ đơn sẽ huỷ tiếp); phiếu còn
	gắn tờ (độc lập / tự lập) Nháp / Chờ → Đã huỷ 'Hóa đơn <mã> bị huỷ', giữ HĐ."""
	from frappe.utils import now_datetime

	for r in frappe.get_all(DT, filters={"hoa_don": hd, "trang_thai": ["in", ["draft", "submitted"]]},
			fields=["name", "don_hang", "tu_sinh"], order_by="creation asc"):
		doc = frappe.get_doc(DT, r.name)
		if r.don_hang and r.tu_sinh:
			doc.update({"hoa_don": None, "trang_thai": "draft", "tu_sinh": 0, "to_ghi_co": None})
			_luu_rpc(doc, {"hoa_don", "trang_thai", "tu_sinh"})
	for r in frappe.get_all(DT, filters={"hoa_don": hd, "trang_thai": ["in", ["draft", "submitted"]]}, pluck="name", order_by="creation asc"):
		doc = frappe.get_doc(DT, r)
		doc.update({"trang_thai": "cancelled", "huy_luc": now_datetime(), "ly_do_huy": f"Hóa đơn {ma_hd} bị huỷ"})
		_luu_rpc(doc, {"trang_thai"})


def huy_to_ghi_co_cua_hd(hd: str, ly_do: str | None) -> None:
	"""Trước khi huỷ HĐ: huỷ mọi tờ ghi có đang ghi sổ gắn HĐ (Link npp_hoa_don_goc làm lõi chặn huỷ HĐ)."""
	for t in frappe.get_all("Sales Invoice", filters={"is_return": 1, "npp_hoa_don_goc": hd, "docstatus": 1}, pluck="name",
			order_by="creation desc"):
		_huy_to_ghi_co(t, ly_do)


def huy_phieu_theo_don(don: str, ly_do: str, chi_nhap: bool = False) -> None:
	"""_huy_don_theo_hoa_don (mig 217) / cancel_order: phiếu của đơn Nháp / Chờ (cancel_order: chỉ Nháp) → Đã huỷ với lý do."""
	from frappe.utils import now_datetime

	tt = ["draft"] if chi_nhap else ["draft", "submitted"]
	for r in frappe.get_all(DT, filters={"don_hang": don, "trang_thai": ["in", tt]}, pluck="name", order_by="creation asc"):
		doc = frappe.get_doc(DT, r)
		doc.update({"trang_thai": "cancelled", "huy_luc": now_datetime(), "ly_do_huy": ly_do})
		_luu_rpc(doc, {"trang_thai"})


# ------------------------------------------------------------------------------------------------ Sửa HĐ (reissue_invoice — đặc tả §4.4)
def _van_ban(v) -> str | None:
	"""p->>'x' của Postgres: chuỗi giữ nguyên, true/false, số theo JSON, null → None."""
	import json

	if v is None:
		return None
	if isinstance(v, bool):
		return "true" if v else "false"
	if isinstance(v, str):
		return v
	return json.dumps(v, ensure_ascii=False, separators=(", ", ": ")) if isinstance(v, (dict, list)) else str(v)


def phieu_tu_lap_cua_hd(hd: str) -> tuple:
	"""_mac_dinh_lap_lai (mig 213): phiếu TỰ LẬP Nháp / Chờ đang gắn tờ cũ — câu gắn của tờ mới không được biến chúng thành tự sinh."""
	return tuple(frappe.get_all(DT, filters={"hoa_don": hd, "trang_thai": ["in", ["draft", "submitted"]], "tu_sinh": 0}, pluck="name"))


def _go_to_khoi_hd(doc) -> None:
	"""Phiếu rời HĐ giữa chừng Sửa HĐ: tờ ghi có KHÔNG kho (tự sinh) huỷ — lập lại theo tờ mới ở bước cuối; tờ ghi có CÓ kho (tự lập Hoàn
	thành) gỡ móc npp_hoa_don_goc (AOS, không chạy hook chiếu giữa chừng)."""
	if not doc.to_ghi_co or frappe.db.get_value("Sales Invoice", doc.to_ghi_co, "docstatus") != 1:
		return
	if frappe.db.get_value("Sales Invoice", doc.to_ghi_co, "update_stock"):
		frappe.db.set_value("Sales Invoice", doc.to_ghi_co, "npp_hoa_don_goc", None, update_modified=False)
	else:
		_huy_to_ghi_co(doc.to_ghi_co)


def tra_da_nhap_truoc(hd: str, p: dict, nc, cd) -> list[tuple[str, str]]:
	"""_tra_da_nhap_truoc_lap_lai (mig 210 / 216 — chủ nhà 28/09/2026 "Cần huỷ phiếu nhập trước?"): phiếu Hoàn thành của tờ cũ → `lam_lai`
	(chỉ phiếu tự sinh: huỷ phiếu nhập, phiếu về Chờ xử lý, đi theo tờ mới như phiếu chờ — KHÔNG nhập kho lại) hoặc gỡ khỏi tờ để gắn lại
	vào tờ mới (`giu`, và phiếu tự lập ở cả hai chế độ). Vắng lựa chọn mà có phiếu tự sinh đã nhập kho → REISSUE_RETURN_STOCKED."""
	che_do = (_van_ban(p.get("tra_da_nhap")) or "").strip() or None
	xong = frappe.get_all(DT, filters={"hoa_don": hd, "trang_thai": "completed"}, fields=["name", "tu_sinh"], order_by="creation asc, name asc")
	if not xong:
		return []
	if che_do is not None and che_do not in ("lam_lai", "giu"):
		raise NppLoi(f"BAD_TRA_DA_NHAP: {che_do} — chỉ nhận lam_lai hoặc giu")
	if che_do is None:
		ma = [r.name for r in xong if r.tu_sinh]
		if ma:
			raise NppLoi(f"REISSUE_RETURN_STOCKED: phiếu trả {', '.join(ma)} đã nhập kho — chọn huỷ phiếu nhập hay giữ nguyên")
	nho = []
	for r in xong:
		doc = _khoa_phieu(r.name)
		if che_do == "lam_lai" and r.tu_sinh:
			_huy(doc, "Sửa hóa đơn — nhập kho lại theo số mới", nc, cd)  # cần returns.approve → FORBIDDEN: bạn không có quyền huỷ đơn trả
			nho.append((r.name, "nhap_lai"))
		else:
			_go_to_khoi_hd(doc)
			doc.hoa_don = None
			_luu_rpc(doc, {"hoa_don"})
			nho.append((r.name, "gan_lai"))
	return nho


def go_phieu_khoi_hd(hd: str) -> list[str]:
	"""v_rets của reissue_invoice: phiếu Nháp / Chờ gắn tờ cũ → gỡ HĐ (gắn lại sau khi lập tờ mới)."""
	ds = frappe.get_all(DT, filters={"hoa_don": hd, "trang_thai": ["in", ["draft", "submitted"]]}, pluck="name",
		order_by="creation asc, name asc")
	for ten in ds:
		doc = frappe.get_doc(DT, ten)
		_go_to_khoi_hd(doc)
		doc.hoa_don = None
		_luu_rpc(doc, {"hoa_don"})
	return ds


def sau_lap_lai(hd_cu: str, hd_moi: str, v_rets: list[str], sua: int, nho: list[tuple[str, str]], nv_cu: str | None, cd) -> None:
	"""Phần cuối reissue_invoice sau post_invoice của tờ mới: gắn lại v_rets (tự lập giữ trạng thái + cờ), phiếu bị chính lượt sửa làm rỗng
	→ Nháp rời HĐ (cờ tự sinh giữ — mig 152 / 158), NV đứng tên theo tờ cũ (mig 182), gắn lại phiếu đã nhập kho (`gan_lai` — mig 210), rồi
	tờ ghi có khớp phiếu."""
	for ten in v_rets:
		doc = frappe.get_doc(DT, ten)
		if doc.hoa_don != hd_moi:
			doc.hoa_don = hd_moi
			_luu_rpc(doc, {"hoa_don"})
	if sua > 0:
		for ten in v_rets:
			doc = frappe.get_doc(DT, ten)
			if doc.trang_thai in ("draft", "submitted") and not doc.dong:
				doc.update({"trang_thai": "draft", "hoa_don": None})
				_luu_rpc(doc, {"trang_thai", "hoa_don"})
	for ten in frappe.get_all(DT, filters={"hoa_don": hd_moi, "trang_thai": ["!=", "cancelled"]}, pluck="name"):
		doc = frappe.get_doc(DT, ten)
		if nv_cu and doc.nhan_vien != nv_cu:
			doc.nhan_vien = nv_cu
			_luu_rpc(doc, {"nhan_vien"})
	for ten, lam in nho:
		if lam != "gan_lai":
			continue
		doc = frappe.get_doc(DT, ten)
		doc.hoa_don = hd_moi
		_luu_rpc(doc, {"hoa_don"})
		to = frappe.db.get_value("Sales Invoice", doc.to_ghi_co, ["docstatus", "update_stock"], as_dict=True) if doc.to_ghi_co else None
		if to and to.docstatus == 1 and to.update_stock:
			frappe.db.set_value("Sales Invoice", doc.to_ghi_co, {"npp_hoa_don_goc": hd_moi, "npp_nhan_vien": doc.nhan_vien},
				update_modified=False)
	dong_bo_to_ghi_co(hd_moi, cd)
