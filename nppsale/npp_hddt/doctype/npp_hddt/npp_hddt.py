# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt
"""Hoá đơn điện tử MISA (= bảng `invoices` của nppsale — tên cũ "Invoices (M10)" của mig 001, KHÔNG phải HĐ bán; mig 124 COMMENT) — blueprint 02
§4.6, đặc tả HĐĐT §1.2 / §1.6.

Mọi trường MISA ở DocType riêng này: Sales Invoice không có trường MISA nào (Sửa HĐ = huỷ + amend, amend chép mọi trường — Gotcha #2). Ai ghi
cột nào: đặc tả §1.5 — giành tờ / luồng kéo về / Dựng ghi bằng `db_set` / câu SQL nên KHÔNG qua controller; controller giữ luật của đường
Document (Desk, cổng `invoices`, lập dòng / Dựng nếu lưu qua Document):
  validate    — `misa_ref_id` đã có thì không đổi (I1 — khoá nối bất biến, Gotcha #1); người mua / tiền / số gõ tay chỉ đổi khi dòng ĐANG
                `draft` ∧ `misa_status` trống / `error` (H24); `nguoi_mua` sau strip rỗng → 23502 như cột NOT NULL `customer_name`; khoá trống → NULL
                (`misa_ref_id`, `misa_inv_no` — cặp duy nhất với `''` ở hai tờ cũng đụng nhau), có số mà ký hiệu NULL → `''` (để chỉ mục duy nhất bắt).
  before_save — `tim_kd` = khoa_tim_ds(so_hd_go_tay, nguoi_mua, misa_inv_no, misa_invoice_id) — thứ tự cột của trigger `trg_zzzz_tim_kd` (mig 249).
  on_trash    — chỉ xoá dòng nháp chưa có RefID; gỡ `hddt` ở NPP MISA Log / NPP MISA Snapshot trước khi lõi kiểm Link (thay ON DELETE SET NULL
                của mig 072 / 100 — `frappe/model/delete_doc.py:177, 184`).
Không submit là có chủ ý: lõi chỉ chặn huỷ Sales Invoice / Sales Order bởi chứng từ liên kết ĐÃ submit (`delete_doc.py:379–382`) — khoá nghiệp vụ
duy nhất là `LOCKED_EINVOICE` (nppsale.rpc.xuat_hang._huy).
"""
from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from nppsale.cong.loi import NppLoi
from nppsale.luat.tim import khoa_tim_ds

TRUONG_TIEN = ("tien_hang", "tien_thue", "tong_tien")
# H24: người mua / tiền / số gõ tay (cổng: customer_name / _address / _tax_code, subtotal / vat / total, invoice_number)
TRUONG_SUA_NHAP = ("nguoi_mua", "dia_chi_nguoi_mua", "mst_nguoi_mua", *TRUONG_TIEN, "so_hd_go_tay")
CAU_XOA = "Chỉ xoá được hoá đơn điện tử nháp chưa gửi MISA."


def sua_duoc_nguoi_mua_tien(trang_thai, misa_status) -> bool:
	"""H24 (đặc tả HĐĐT §0.3, §1.2, §7.1): người mua / tiền / số gõ tay chỉ sửa khi `trang_thai = draft` ∧ `IFNULL(misa_status,'') IN ('','error')`
	— cùng vế "chưa chắc tới MISA" của H3b. Bản trước ("chưa có `misa_ref_id`") viết khi RefID còn ghi SAU khi MISA nhận; RefID nay ghi TRƯỚC khi
	gửi nên tờ tay bị MISA từ chối (MST người mua sai — `error` có RefID) phải sửa được để đẩy lại cùng RefID. Dùng chung validate + bộ ghi cổng."""
	return (trang_thai or "") == "draft" and (misa_status or "") in ("", "error")


def xoa_duoc(trang_thai, misa_ref_id) -> bool:
	"""Xoá: chỉ dòng nháp chưa có RefID (BP §4.6 — đã gửi MISA thì giữ khoá nối, Gotcha #1)."""
	return (trang_thai or "") == "draft" and not (misa_ref_id or "").strip()


def khoa_tim_hddt(d) -> str:
	"""`tim_kd` của một dòng (Document / dict) — before_save và hàm ghi kéo về (db_set số HĐĐT không chạy before_save) dùng chung.
	Thứ tự cột như trigger nppsale: _trg_tim_kd('invoice_number','customer_name','misa_inv_no','misa_invoice_id')."""
	return khoa_tim_ds(d.get("so_hd_go_tay"), d.get("nguoi_mua"), d.get("misa_inv_no"), d.get("misa_invoice_id"))


def _doi(cu, moi, truong: str) -> bool:
	if truong in TRUONG_TIEN:
		return flt(cu.get(truong)) != flt(moi.get(truong))
	return (cu.get(truong) or "") != (moi.get(truong) or "")


class NPPHDDT(Document):
	def validate(self):
		# khoá trống → NULL: lõi chỉ đổi '' → NULL cho trường `unique` (misa_ref_id) khi đi đường Document (document.py:2602–2605); misa_inv_no
		# không unique một cột mà nằm trong cặp duy nhất (misa_inv_series, misa_inv_no) — hai tờ ('', '') cũng đụng nhau
		for truong in ("misa_ref_id", "misa_inv_no"):
			if not (self.get(truong) or "").strip():
				self.set(truong, None)
		if self.misa_inv_no and self.misa_inv_series is None:
			self.misa_inv_series = ""  # MariaDB coi NULL là khác nhau — có số mà không ký hiệu thì chỉ mục duy nhất phải bắt được
		cu = None if self.is_new() else self.get_doc_before_save()
		if cu is not None:
			ref_cu = (cu.get("misa_ref_id") or "").strip()
			if ref_cu and (self.misa_ref_id or "") != cu.get("misa_ref_id"):
				raise NppLoi("HDDT_REFID_BAT_BIEN: RefID (khoá nối MISA) đã có thì không đổi được — mất khoá nối là mất đường hỏi MISA tờ này.")
			if any(_doi(cu, self, f) for f in TRUONG_SUA_NHAP) and not sua_duoc_nguoi_mua_tien(cu.get("trang_thai"), cu.get("misa_status")):
				raise NppLoi("HDDT_KHOA_SUA: chỉ sửa người mua / tiền / số HĐ gõ tay khi hoá đơn điện tử còn nháp và chưa tới MISA "
					"(trạng thái MISA trống hoặc Lỗi).")
		if not (self.nguoi_mua or "").strip():
			# nppsale: `customer_name text NOT NULL` (nhận '') — Frappe `nguoi_mua` reqd; cổng nhận đúng mã + câu Postgres (đặc tả §7.1)
			raise NppLoi('null value in column "customer_name" of relation "invoices" violates not-null constraint', code="23502")

	def before_save(self):
		self.tim_kd = khoa_tim_hddt(self)

	def on_trash(self):
		if not xoa_duoc(self.trang_thai, self.misa_ref_id):
			raise NppLoi(CAU_XOA)
		# ON DELETE SET NULL của nppsale (einvoice_logs.invoice_id — mig 072; misa_invoice_snapshots.invoice_id — mig 100)
		frappe.db.sql("UPDATE `tabNPP MISA Log` SET `hddt` = NULL WHERE `hddt` = %s", self.name)
		frappe.db.sql("UPDATE `tabNPP MISA Snapshot` SET `hddt` = NULL WHERE `hddt` = %s", self.name)


def on_doctype_update():
	# uq_invoices_misa_inv_no của nppsale: UNIQUE (org_id, COALESCE(misa_inv_series,''), misa_inv_no) WHERE misa_inv_no IS NOT NULL — MariaDB không
	# có chỉ mục một phần / biểu thức: NULL của misa_inv_no không vướng; ký hiệu trống lưu '' (validate / hàm ghi). Chỉ mục một cột (hoa_don_ban,
	# don_hang, trang_thai, phat_hanh_luc, misa_org_ref_id, misa_last_checked_at) khai search_index trong JSON — lõi xoá rồi tạo lại chỉ mục một
	# cột không khai ở mỗi lần đồng bộ lược đồ (frappe/database/schema.py:310–312).
	frappe.db.add_unique("NPP HDDT", ["misa_inv_series", "misa_inv_no"], "uq_hddt_ky_hieu_so")
