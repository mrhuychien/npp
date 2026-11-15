"""Bảng TIỀN THU của nppsale trên cổng (đặc tả phiếu thu §4; blueprint 02 §6.1):

- cash_receipts ← NPP Phieu Thu. RLS đọc (mig 034): chủ / quản lý / kế toán mọi phiếu; NVBH / thủ kho phiếu mình thu.
- cash_receipt_lines ← NPP Phieu Thu Dong (mọi phiếu, kể cả đã huỷ); `payment_id` = tên dòng khi phiếu chưa huỷ. RLS: theo phiếu cha đọc được.
- payments ← dòng phiếu thu của phiếu CHƯA huỷ (nppsale xoá `payments` khi huỷ phiếu). RLS: vai ≠ sales và thấy được dòng công nợ (thủ kho 0
  dòng); NVBH: dòng công nợ mình giữ VÀ đơn của dòng đứng tên mình.
- cash_collections: không port (chuyến giao bỏ 24/09/2026) — đọc rỗng, ghi → LEGACY_FLOW_REMOVED.

GHI thẳng (trigger mig 214 chạy trước RLS khi THÊM; RLS lọc dòng trước trigger khi SỬA / XOÁ — "0 dòng" là 200 + mảng rỗng, không lỗi):
- phiếu: chỉ đổi {trạng thái giữ nguyên / Chờ → Đã nhận, người nhận, giờ nhận, ghi chú} (chủ / quản lý / kế toán); còn lại PHIEU_THU_KHOA;
- dòng phiếu thu: mọi ghi THU_TIEN_KHOA (sửa: chủ / QL / KT; xoá: chủ / QL; vai khác 0 dòng);
- khoản thu: chỉ xác nhận (verified_by / verified_at — chủ / kế toán); còn lại THU_TIEN_KHOA; không ai xoá được (không có chính sách xoá).
"So giá trị": gửi lại đúng giá trị cũ của cột cấm không lỗi (trigger so to_jsonb).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import frappe
from frappe.utils import get_datetime, getdate

from ..dang_ky import Bang, CotDef, NguCanh, QuanHe, dang_ky
from ..loi import NppLoi
from ..sql import LoiCong
from ._chung import VAI_VAN_PHONG, c, co_cot, gio_vao, la_nv, lay_org_id, org

KHOA_PHIEU = "PHIEU_THU_KHOA: phiếu thu chỉ lập / huỷ qua nút Lập phiếu thu, Huỷ phiếu thu"
KHOA_TIEN = "THU_TIEN_KHOA: tiền thu chỉ ghi / huỷ qua phiếu thu (lập phiếu thu, huỷ phiếu thu)"
NULL = CotDef("NULL")


# ------------------------------------------------------------------------------------------------ RLS
def ve_phieu(nc: NguCanh, bd: str = "{t}"):
	if nc.bo_qua_rls:
		return None
	if not la_nv(nc):
		return False
	if nc.vai in VAI_VAN_PHONG:
		return None
	if nc.vai in ("sales", "warehouse"):
		return (f"{bd}.`nguoi_thu` = %(u)s", {"u": nc.user})
	return False


def _ve_dong(nc: NguCanh):
	v = ve_phieu(nc, "p")
	if v is None or v is False:
		return v
	return (f"EXISTS (SELECT 1 FROM `tabNPP Phieu Thu` p WHERE p.`name` = {{t}}.`parent` AND {v[0]})", v[1])


def _ve_khoan(nc: NguCanh):
	if nc.bo_qua_rls:
		return None
	if not la_nv(nc):
		return False
	if nc.vai == "sales":
		return ("EXISTS (SELECT 1 FROM `tabNPP Cong No` r JOIN `tabSales Order` so ON so.`name` = r.`don_hang` WHERE r.`name` = {t}.`cong_no` "
			"AND r.`nhan_vien` = %(u)s AND so.`npp_nhan_vien` = %(u)s)", {"u": nc.user})
	if nc.vai in VAI_VAN_PHONG:  # vai khác sales và thấy được dòng công nợ (RLS receivables: chỉ chủ / QL / KT)
		return ("EXISTS (SELECT 1 FROM `tabNPP Cong No` r WHERE r.`name` = {t}.`cong_no`)", {})
	return False


# ------------------------------------------------------------------------------------------------ so giá trị
def _so(v):
	try:
		return Decimal(str(v).strip())
	except InvalidOperation:
		raise LoiCong("22P02", f'invalid input syntax for type numeric: "{v}"') from None


def _khac(kieu: str, moi, cu) -> bool:
	if moi is None or cu is None:
		return (moi is None) != (cu is None)
	if kieu == "tien":
		return _so(moi) != Decimal(str(cu))
	if kieu == "ngay":
		return getdate(moi) != getdate(cu)
	if kieu == "gio":
		return get_datetime(gio_vao(moi)) != get_datetime(cu)
	return str(moi) != str(cu)


def _kiem_cot(bang: Bang, gt: dict) -> None:
	for k in gt:
		if k not in bang.cot:
			raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{bang.ten}' in the schema cache", http=400)


def _hien_tai(bang: str, ten: str, cot: list[str]) -> dict:
	from ..truy_van import doc

	r = doc({"bang": bang, "select": ", ".join(cot), "loc": [{"op": "eq", "cot": "id", "gt": ten}]},
		NguCanh(user="Administrator", vai=None, bo_qua_rls=True))["data"]
	return r[0] if r else {}


def _nv(v, bang: str, rang_buoc: str):
	if v is not None and not frappe.db.exists("NPP Nhan Vien", v):
		raise LoiCong("23503", f'insert or update on table "{bang}" violates foreign key constraint "{rang_buoc}"', http=409)
	return v


# ------------------------------------------------------------------------------------------------ bộ ghi
class GhiPhieuThu:
	CHO = {"status", "received_by", "received_at", "notes"}

	def __init__(self, bang: Bang):
		self.bang = bang

	def them(self, ds, nc):
		for g in ds:
			_kiem_cot(self.bang, g or {})
		raise NppLoi(KHOA_PHIEU)

	def sua(self, gt, ids, nc):
		_kiem_cot(self.bang, gt)
		if not nc.bo_qua_rls and nc.vai not in VAI_VAN_PHONG:
			return []
		ra = []
		for ten in ids:
			cu = _hien_tai(self.bang.ten, ten, list(gt) or ["id"])
			for k, v in gt.items():
				if k not in self.CHO and _khac(self.bang.cot[k].kieu, v, cu.get(k)):
					raise NppLoi(KHOA_PHIEU)
			tt_cu = frappe.db.get_value("NPP Phieu Thu", ten, "trang_thai")
			if "status" in gt and gt["status"] != tt_cu and not (tt_cu == "pending" and gt["status"] == "received"):
				raise NppLoi(KHOA_PHIEU)
			d = frappe.get_doc("NPP Phieu Thu", ten)
			if "status" in gt:
				d.trang_thai = gt["status"]
			if "received_by" in gt:
				d.nhan_boi = _nv(gt["received_by"], "cash_receipts", "cash_receipts_received_by_fkey")
			if "received_at" in gt:
				d.nhan_luc = gio_vao(gt["received_at"])
			if "notes" in gt:
				d.ghi_chu = gt["notes"]
			d.flags.ignore_permissions = True
			d.flags.ignore_mandatory = True
			d.save()
			ra.append(ten)
		return ra

	def xoa(self, ids, nc):
		if ids and (nc.bo_qua_rls or nc.vai in ("owner", "manager")):
			raise NppLoi(KHOA_PHIEU)
		return []


class GhiDongThu:
	def __init__(self, bang: Bang):
		self.bang = bang

	def them(self, ds, nc):
		for g in ds:
			_kiem_cot(self.bang, g or {})
		raise NppLoi(KHOA_TIEN)

	def sua(self, gt, ids, nc):
		_kiem_cot(self.bang, gt)
		if ids and (nc.bo_qua_rls or nc.vai in VAI_VAN_PHONG):
			raise NppLoi(KHOA_TIEN)
		return []

	def xoa(self, ids, nc):
		if ids and (nc.bo_qua_rls or nc.vai in ("owner", "manager")):
			raise NppLoi(KHOA_TIEN)
		return []


class GhiKhoanThu:
	CHO = {"verified_by", "verified_at"}

	def __init__(self, bang: Bang):
		self.bang = bang

	def them(self, ds, nc):
		for g in ds:
			_kiem_cot(self.bang, g or {})
		raise NppLoi(KHOA_TIEN)

	def sua(self, gt, ids, nc):
		_kiem_cot(self.bang, gt)
		if not nc.bo_qua_rls and nc.vai not in ("owner", "accountant"):
			return []  # RLS UPDATE "Accountant can verify payments"
		ra = []
		for ten in ids:
			if not frappe.db.sql("""SELECT 1 FROM `tabNPP Phieu Thu Dong` d JOIN `tabNPP Cong No` r ON r.`name` = d.`cong_no`
					WHERE d.`name` = %s""", ten):
				continue
			cu = _hien_tai(self.bang.ten, ten, list(gt) or ["id"])
			for k, v in gt.items():
				if k not in self.CHO and _khac(self.bang.cot[k].kieu, v, cu.get(k)):
					raise NppLoi(KHOA_TIEN)
			moi = {}
			if "verified_by" in gt:
				moi["xac_nhan_boi"] = _nv(gt["verified_by"], "payments", "payments_verified_by_fkey")
			if "verified_at" in gt:
				moi["xac_nhan_luc"] = gio_vao(gt["verified_at"])
			if moi:
				frappe.db.set_value("NPP Phieu Thu Dong", ten, moi, update_modified=False)
			ra.append(ten)
		return ra

	def xoa(self, ids, nc):
		return []  # không có chính sách DELETE: 0 dòng với mọi vai


class GhiDaGo:
	"""Bảng của luồng đã gỡ (chuyến giao): mọi ghi → LEGACY_FLOW_REMOVED."""

	def _go(self, *a, **k):
		raise NppLoi("LEGACY_FLOW_REMOVED: chức năng đã gỡ")

	them = sua = xoa = them_hoac_sua = _go


# ------------------------------------------------------------------------------------------------ đăng ký
def nap():
	if not co_cot("NPP Phieu Thu", "tien_thu"):
		return
	nguoi_tao = "CASE WHEN {t}.`owner` IN ('Administrator', 'Guest') THEN NULL ELSE {t}.`owner` END"
	phieu = Bang(
		ten="cash_receipts",
		nguon="`tabNPP Phieu Thu`",
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "receipt_code": c("{t}.`name`"), "receipt_date": c("ngay_thu", "ngay"),
			"source_type": c("nguon"), "source_id": c("nguon_id"), "collected_by": c("nguoi_thu"),
			"submitted_amount": c("tien_thu", "tien"), "expected_amount": c("{t}.`tien_thu`", "tien"), "notes": c("ghi_chu"),
			"status": c("trang_thai"), "received_by": c("nhan_boi"), "received_at": c("nhan_luc", "gio"), "created_by": c(nguoi_tao),
			"created_at": c("creation", "gio"), "voided_at": c("huy_luc", "gio"), "voided_by": c("huy_boi"), "void_reason": c("ly_do_huy"),
			"client_key": c("client_key"), "tim_kd": c("tim_kd"),
		},
		quan_he=[
			QuanHe("cash_receipt_lines", "id", "receipt_id", True, ("cash_receipt_lines_receipt_id_fkey",)),
			QuanHe("users", "collected_by", "id", False, ("cash_receipts_collected_by_fkey",)),
			QuanHe("users", "created_by", "id", False, ("cash_receipts_created_by_fkey",)),
			QuanHe("users", "received_by", "id", False, ("cash_receipts_received_by_fkey",)),
			QuanHe("users", "voided_by", "id", False, ("cash_receipts_voided_by_fkey",)),
		],
		rls=lambda nc: ve_phieu(nc),
	)
	phieu.ghi = GhiPhieuThu(phieu)
	dang_ky(phieu)
	dong = Bang(
		ten="cash_receipt_lines",
		nguon="(SELECT d.*, p.`trang_thai` AS `_tt_phieu` FROM `tabNPP Phieu Thu Dong` d JOIN `tabNPP Phieu Thu` p ON p.`name` = d.`parent` "
		"WHERE d.`parenttype` = 'NPP Phieu Thu')",
		cot={
			"id": c("{t}.`name`"), "receipt_id": c("parent"), "order_id": c("don_hang"), "receivable_id": c("cong_no"),
			"payment_id": c("CASE WHEN {t}.`_tt_phieu` <> 'voided' THEN {t}.`name` END"), "amount": c("so_tien", "tien"),
			"notes": c("ghi_chu"), "kind": c("loai"), "return_id": c("phieu_tra"), "invoice_id": c("hoa_don"),
		},
		quan_he=[
			QuanHe("cash_receipts", "receipt_id", "id", False, ("cash_receipt_lines_receipt_id_fkey",)),
			QuanHe("receivables", "receivable_id", "id", False, ("cash_receipt_lines_receivable_id_fkey",)),
			QuanHe("payments", "payment_id", "id", False, ("cash_receipt_lines_payment_id_fkey",)),
			QuanHe("sales_orders", "order_id", "id", False, ("cash_receipt_lines_order_id_fkey",)),
			QuanHe("sales_invoices", "invoice_id", "id", False, ("cash_receipt_lines_invoice_id_fkey",)),
			QuanHe("returns", "return_id", "id", False, ("cash_receipt_lines_return_id_fkey",)),
		],
		rls=_ve_dong,
		thu_tu_mac_dinh=[{"cot": "receipt_id"}, {"cot": "id"}],
	)
	dong.ghi = GhiDongThu(dong)
	dang_ky(dong)
	khoan = Bang(
		ten="payments",
		nguon="(SELECT d.*, p.`nguoi_thu` AS `_nguoi_thu`, p.`hinh_thuc` AS `_hinh_thuc`, p.`creation` AS `_thu_luc` FROM `tabNPP Phieu Thu Dong` d "
		"JOIN `tabNPP Phieu Thu` p ON p.`name` = d.`parent` WHERE d.`parenttype` = 'NPP Phieu Thu' AND p.`trang_thai` <> 'voided')",
		cot={
			"id": c("{t}.`name`"), "receivable_id": c("cong_no"), "collected_by": c("{t}.`_nguoi_thu`"), "amount": c("so_tien", "tien"),
			"method": c("CASE WHEN {t}.`loai` = 'payment' THEN {t}.`_hinh_thuc` ELSE {t}.`loai` END"),
			"collected_at": c("{t}.`_thu_luc`", "gio"), "verified_by": c("xac_nhan_boi"), "verified_at": c("xac_nhan_luc", "gio"),
		},
		quan_he=[
			QuanHe("receivables", "receivable_id", "id", False, ("payments_receivable_id_fkey",)),
			QuanHe("users", "collected_by", "id", False, ("payments_collected_by_fkey",)),
			QuanHe("users", "verified_by", "id", False, ("payments_verified_by_fkey",)),
			QuanHe("cash_receipt_lines", "id", "payment_id", True, ("cash_receipt_lines_payment_id_fkey",)),
		],
		rls=_ve_khoan,
	)
	khoan.ghi = GhiKhoanThu(khoan)
	dang_ky(khoan)
	dang_ky(Bang(
		ten="cash_collections",
		nguon="(SELECT NULL AS `id`, NULL AS `org_id`, NULL AS `driver_id`, NULL AS `work_date`, NULL AS `total_collected`, "
		"NULL AS `total_submitted`, NULL AS `discrepancy`, NULL AS `status`, NULL AS `notes`, NULL AS `verified_by`, NULL AS `verified_at`, "
		"NULL AS `created_at` FROM DUAL WHERE 1 = 0)",
		cot={k: c("{t}.`" + k + "`", "tien" if k.startswith("total") or k == "discrepancy" else "ngay" if k == "work_date" else
			"gio" if k in ("verified_at", "created_at") else "chuoi") for k in ("id", "org_id", "driver_id", "work_date", "total_collected",
			"total_submitted", "discrepancy", "status", "notes", "verified_by", "verified_at", "created_at")},
		rls=lambda nc: None if la_nv(nc) else False,
		ghi=GhiDaGo(),
	))


_ = (NULL, lay_org_id)

try:
	nap()
except Exception:  # noqa: BLE001 — nạp sổ ngoài request (không có DB) thì thôi
	pass
