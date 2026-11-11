"""Tiện ích chung cho các tệp khai bảng của cổng."""
from __future__ import annotations

import re

import frappe

from ..dang_ky import CotDef, NguCanh
from ..sql import LoiCong

# Hằng org_id của site (một site một NPP) — câu con không tương quan, MariaDB tính một lần mỗi câu.
ORG_SQL = "(SELECT `value` FROM `tabSingles` WHERE `doctype` = 'NPP Cai Dat' AND `field` = 'org_id')"

VAI_VAN_PHONG = ("owner", "manager", "accountant")


def c(bieu: str, kieu: str = "chuoi", truong: str | None = None) -> CotDef:
	"""c("ho_ten") = cột `ho_ten` của bảng nguồn; c("CASE …{t}…", "so") = biểu thức SQL tự viết."""
	if re.fullmatch(r"[a-z_][a-z0-9_]*", bieu):
		return CotDef(f"{{t}}.`{bieu}`", kieu, truong if truong is not None else bieu)
	return CotDef(bieu, kieu, truong)


def org() -> CotDef:
	return CotDef(ORG_SQL, "chuoi")


def la_nv(nc: NguCanh) -> bool:
	"""Người gọi là NV đang hoạt động của NPP (cổng chỉ phục vụ NV — `user_org_id()` của nppsale trả NULL khi bị khoá)."""
	return bool(nc.vai)


def rls_moi_nv(nc: NguCanh):
	"""SELECT cho mọi NV của NPP (chính sách kiểu `org_id = user_org_id()`)."""
	return None if la_nv(nc) else False


def tu_choi(bang: str):
	raise LoiCong("42501", f'new row violates row-level security policy for table "{bang}"', http=403)


def lay_org_id() -> str:
	return frappe.db.get_single_value("NPP Cai Dat", "org_id") or ""


def kiem_org(gia_tri: dict, bang: str):
	"""Ghi kèm `org_id` khác hằng của site → từ chối như WITH CHECK của RLS."""
	if "org_id" in gia_tri and gia_tri["org_id"] not in (None, lay_org_id()):
		tu_choi(bang)


def pivot_single(doctype: str, truong: dict[str, str]) -> str:
	"""Câu con dựng MỘT dòng từ `tabSingles` của DocType Single: {tên cột ra: kiểu} — kiểu: chuoi / so / bool / gio / json."""
	phan = []
	for ten, kieu in truong.items():
		e = f"MAX(CASE WHEN s.`field` = '{ten}' THEN s.`value` END)"
		if kieu == "so":
			e = f"CAST({e} AS DECIMAL(21,6))"
		elif kieu == "bool":
			e = f"CAST(IFNULL({e}, 0) AS UNSIGNED)"
		elif kieu == "gio":
			e = f"CAST({e} AS DATETIME(6))"
		phan.append(f"{e} AS `{ten}`")
	return f"(SELECT {', '.join(phan)} FROM `tabSingles` s WHERE s.`doctype` = '{doctype}')"


# ----------------------------------------------------------------------------------------------------------------------------
# Bộ ghi dùng chung cho bảng một-DocType: khai ánh xạ cột nppsale → trường, vai được thêm / sửa / xoá, luật riêng theo dòng.
# ----------------------------------------------------------------------------------------------------------------------------
from frappe.utils import get_datetime as _gd  # noqa: E402


def gio_vao(v):
	"""ISO có múi giờ (trình duyệt gửi) → datetime không múi giờ theo giờ site (Frappe lưu giờ địa phương)."""
	if not v:
		return None
	d = _gd(v)
	if d.tzinfo is not None:
		from frappe.utils import convert_utc_to_system_timezone

		d = convert_utc_to_system_timezone(d.astimezone(__import__("datetime").timezone.utc)).replace(tzinfo=None)
	return d


def bool_vao(v):
	return 1 if v in (True, 1, "1", "true", "t") else 0


def so_0(v):
	"""Toạ độ: null ⇔ 0 (đất liền VN không bao giờ ở 0)."""
	return 0 if v is None else v


CHI_DOC = ("id", "org_id", "created_at", "updated_at", "created_by", "updated_by", "tim_kd")


class GhiDocType:
	def __init__(self, bang: str, doctype: str, anh_xa: dict, *, vai_them=(), vai_sua=(), vai_xoa=(), ep_them=None, duoc_sua=None,
			duoc_xoa=None, giu_id=False, truoc_xoa=None, bat_trung=None):
		"""anh_xa: {cột nppsale: "truong" | ("truong", hàm đổi giá trị)}. ep_them(dict_doc, gia_tri, nc): ép giá trị khi thêm.
		duoc_sua / duoc_xoa(nc, ten) → bool: luật theo dòng (sai = bỏ qua dòng, như USING của RLS). giu_id: nhận `id` trình duyệt
		gửi làm tên (DocType đặt tên UUID). bat_trung(e) → LoiCong: dịch lỗi trùng khoá."""
		self.bang, self.doctype, self.anh_xa = bang, doctype, anh_xa
		self.vai_them, self.vai_sua, self.vai_xoa = vai_them, vai_sua, vai_xoa
		self.ep_them, self.duoc_sua, self.duoc_xoa, self.giu_id = ep_them, duoc_sua, duoc_xoa, giu_id
		self.truoc_xoa, self.bat_trung = truoc_xoa, bat_trung

	def _gan(self, dich: dict, gia_tri: dict):
		for k, v in gia_tri.items():
			if k in CHI_DOC:
				continue
			m = self.anh_xa.get(k)
			if m is None:
				raise LoiCong("PGRST204", f"Could not find the '{k}' column of '{self.bang}' in the schema cache", http=400)
			if isinstance(m, tuple):
				dich[m[0]] = m[1](v)
			else:
				dich[m] = v

	def them(self, ds, nc):
		if nc.vai not in self.vai_them and not nc.bo_qua_rls:
			tu_choi(self.bang)
		ra = []
		for g in ds:
			kiem_org(g, self.bang)
			d = {"doctype": self.doctype}
			self._gan(d, g)
			if self.ep_them:
				self.ep_them(d, g, nc)
			doc = frappe.get_doc(d)
			if self.giu_id and g.get("id"):
				doc.name = g["id"]
			try:
				doc.insert(ignore_permissions=True)
			except (frappe.DuplicateEntryError, frappe.UniqueValidationError) as e:
				if self.bat_trung:
					raise self.bat_trung(e) from e
				raise LoiCong("23505", f'duplicate key value violates unique constraint "{self.bang}_pkey"', http=409) from e
			ra.append(doc.name)
		return ra

	def sua(self, gia_tri, ids, nc):
		if nc.vai not in self.vai_sua and not nc.bo_qua_rls:
			return []
		kiem_org(gia_tri, self.bang)
		ra = []
		for ten in ids:
			if self.duoc_sua and not nc.bo_qua_rls and not self.duoc_sua(nc, ten):
				continue
			doc = frappe.get_doc(self.doctype, ten)
			moi = {}
			self._gan(moi, gia_tri)
			for f, v in moi.items():
				doc.set(f, v)
			try:
				doc.save(ignore_permissions=True)
			except (frappe.DuplicateEntryError, frappe.UniqueValidationError) as e:
				if self.bat_trung:
					raise self.bat_trung(e) from e
				raise
			ra.append(ten)
		return ra

	def xoa(self, ids, nc):
		if nc.vai not in self.vai_xoa and not nc.bo_qua_rls:
			return []
		ra = []
		for ten in ids:
			if self.duoc_xoa and not nc.bo_qua_rls and not self.duoc_xoa(nc, ten):
				continue
			if self.truoc_xoa:
				self.truoc_xoa(ten)
			frappe.delete_doc(self.doctype, ten, ignore_permissions=True)
			ra.append(ten)
		return ra


_COT_CO = {}


def co_cot(doctype: str, cot: str) -> bool:
	"""Bảng có cột chưa (vế lọc tham chiếu bảng của giai đoạn sau — ví dụ đơn hàng — chỉ bật khi đã có)."""
	k = (doctype, cot)
	if k not in _COT_CO:
		try:
			_COT_CO[k] = bool(frappe.db.has_column(doctype, cot))
		except Exception:
			_COT_CO[k] = False
	return _COT_CO[k]
