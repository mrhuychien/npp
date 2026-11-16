"""Kho + mua hàng + công nợ NCC (P4) so với CHÍNH hàm + trigger + RLS của nppsale (cần bench):

	bench --site poc.local run-tests --module nppsale.tests.test_kho_mua_vang
	NPP_VANG_CHI=V01,V13 bench … run-tests …        (chạy một phần — đầu mã kịch bản)

Dữ liệu vàng du_lieu/kho_mua_mau.json (tools/vang_kho_mua.py — đặc tả kho_mua §6: kịch bản V01–V87 trên bộ dữ liệu F §6.0). Bài dựng cùng người / NCC /
mặt hàng / khách / bảng giá bán trên site, phát lại cùng chuỗi bước qua cổng RPC / cổng bảng DƯỚI ĐÚNG NGƯỜI và so: từng bước (thành / bại, mã + câu lỗi
TỪNG KÝ TỰ — §2.5), số trả về, ảnh chụp cuối theo KHOÁ NGHIỆP VỤ (phiếu nhập + dòng, lô, công nợ NCC, bảng giá nhập, phiếu kho của phiếu nhập, HĐ bán nền,
nhãn) — cùng luật đọc với bộ sinh (`quy_uoc` của tệp vàng). Sau mỗi kịch bản: khám sổ công nợ NCC của các NCC nền phải sạch.

Phạm vi theo mốc (đặc tả §8): kịch bản của mốc CHƯA DỰNG (`DA_DUNG`) bỏ qua và in số; `chi_nppsale` (kịch bản / bước — NPP thứ hai, dữ liệu cũ đặt bằng
quyền máy chủ) bỏ; `nguon: dac_ta` (chỉ có ở Frappe — mong là chữ của đặc tả) kiểm bằng hàm riêng ở `KIEM_DAC_TA`.

Chuẩn hoá trước khi so (khác có chủ đích — không phải lệch; quyết định tạm Q9):
- câu 18: Frappe cấp số `PN-` lúc LẬP NHÁP → mã phiếu so theo NHÃN của bước (P, Q…): mã nppsale / tên Frappe → "<nhãn>", lô "<nhãn>-NNN"; phiếu tạm nppsale
  chưa mã cũng mang "<nhãn>" (bên Frappe nó đã có số).
- CFD-01: khôi phục = amend `PN-0001-1` → cả chuỗi amend là MỘT nhãn, ảnh chụp lấy tờ CUỐI của chuỗi (nppsale giữ id).
- §7.2 #14: phiếu kho của phiếu nhập = chính PI → ghi chú phiếu kho = ghi chú phiếu (nppsale "Nhập kho từ phiếu nhập hàng <mã>"); dòng kho không so
  `quantity` (⚠K §4.5: Frappe SL giao dịch, nppsale ROUND(SL cơ sở)); phiếu kho của HĐ bán / hoàn kho (`XK-` / `NK-`) và `phieu_kho` / `entry_id` của HĐ
  chưa so (cổng `stock_entries` — M4; phiếu kho của HĐ = chính HĐ).
- §7.2 #26: lô mà mọi gói lô đã huỷ (huỷ phiếu nhập) → cổng `batches` ra dòng "lô chưa phát sinh" `qty_initial 0` (nppsale giữ số nhập cũ, `status
  cancelled`); trạng thái tắt = `cancelled` như nppsale (Batch `disabled` — §7.3 điểm 35).
- tiền: Frappe làm tròn đồng (BP §7.2 điểm 3); giá vốn lô so 2 chữ số lẻ (§7.1 #5).
LECH: kịch bản bản Frappe khác hẳn (⚠K / ❓) → hàm sửa phần MONG (bước + ảnh chụp) thành kết quả Frappe, kèm lý do — 00_quyet_dinh_trien_khai.md Q9.
"""
from __future__ import annotations

import copy
import json
import os
import re
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, get_datetime, getdate, now_datetime, nowdate

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.truy_van import doc as doc_cong
from nppsale.luat.sdt import email_ky_thuat
from nppsale.tests import test_xuat_hang as XH
from nppsale.thiet_lap.kho_mua import cai_dat_kho

VANG = os.path.join(os.path.dirname(__file__), "du_lieu", "kho_mua_mau.json")
ADMIN = NguCanh(user="Administrator", vai=None, bo_qua_rls=True)
NS = uuid.UUID("6f1c2a77-1d0e-4b8f-9a3c-2b4d5e6f7081")

# mốc dựng → số kịch bản (đặc tả §8; V81–V87 gắn mốc theo §9.3)
MOC = {"M1": range(1, 17), "M2": (*range(17, 29), 87), "M3": (*range(29, 41), 86), "M4": (*range(41, 56), 81, 85), "M5": (*range(56, 60), 82),
	"M6": range(60, 65), "M7": (*range(65, 72), 83), "M8": (72, 73, 84), "M9": range(74, 81)}
DA_DUNG = ("M1",)
# mục ảnh chụp đã so theo mốc (mục của mốc sau — tra_no, phieu_chi, chi_phi, ptn… — thêm khi dựng)
MUC_SO = ("pn", "lo", "no", "gia_nhap", "phieu_kho", "hd", "nhan")


def moc_cua(ma: str) -> str | None:
	n = int(re.match(r"V(\d+)", ma).group(1))
	return next((m for m, ds in MOC.items() if n in ds), None)


# ------------------------------------------------------------------------------------------------ lệch có chủ đích (⚠K / ❓ — Q9)
def _v05d(t, mong):
	mong["ct"]["no"][0]["status"] = "paid"


def _v08b(t, mong):
	b = mong["buoc"]
	b[0] = {"ok": False, "ma_loi": "P0001", "loi": "SO_LUONG_KHONG_HOP_LE: Dòng 2 có số lượng không lớn hơn 0."}
	b[1] = {"ok": False, "ma_loi": "P0001", "loi": "PHIEU_KHONG_CO_HANG: Phiếu chưa có dòng hàng nào."}
	t["buoc"][0]["tiep"] = True
	p = next(x for x in mong["ct"]["pn"] if x["nhan"] == "P")
	p.pop("dong", None)
	p.update({"subtotal": 0, "total": 0})


def _v12(t, mong):
	"""Hàng THEO LÔ không bao giờ âm (CFD-05 B): huỷ bị chặn dù cờ bán vượt tồn đã bật — câu riêng §7.3 điểm 12; dừng ở bước huỷ → sổ như V11."""
	mong["buoc"][4] = {"ok": False, "ma_loi": "P0001", "loi": "HANG_DA_XUAT: Không huỷ được vì hàng của phiếu đã xuất bớt — Hàng A (nhập 48.000000, còn "
		"18.000000). Lập phiếu trả hàng NCC hoặc phiếu điều chỉnh kho."}
	ct = mong["ct"]
	p = ct["pn"][0]
	for k in ("huy_boi", "luc_huy", "ly_do_huy"):
		p.pop(k, None)
	p.update({"status": "completed", "no": "PN:PN-0001"})
	ct["lo"][0].update({"ton": 18.0, "status": "available"})
	ct["no"] = [{"luc": "@luc_goi", "ncc": "@S1", "khoa": "PN:PN-0001", "so_hd": "HD-NCC-1", "da_tra": 0, "dau_ky": False, "status": "open",
		"ghi_chu": "Phiếu nhập hàng PN-0001", "so_tien": 480000, "phieu_kho": "PN-0001", "luc_bang_hoan_thanh": True}]
	ct["hd"][0]["status"] = "posted"
	ct["phieu_kho"][0]["status"] = "posted"


# kịch bản [Frappe] (`nguon: dac_ta` — mong là chữ của đặc tả) → hàm kiểm riêng của lớp bài
KIEM_DAC_TA = {"V02c": "_v02c", "V12b": "_v12b"}

LECH: dict[str, tuple] = {
	"V05d": (_v05d, "BP §4.3.0: khoản nợ 0 đ (giảm đầu phiếu nuốt hết tiền) là ĐÃ TRẢ ĐỦ — một luật với phải thu; nppsale chèn dòng `open` amount 0"),
	"V08b": (_v08b, "§7.3 điểm 23: lõi không nhận PI nháp dòng SL 0 (đo M0) → cổng chặn ngay lúc lưu dòng bằng câu của sua_phieu_nhap (nppsale báo lúc "
		"hoàn thành); phiếu P ở lại không dòng → Hoàn thành báo PHIEU_KHONG_CO_HANG"),
	"V12": (_v12, "CFD-05 B / §7.3 điểm 12: hàng theo lô đã xuất không huỷ được phiếu nhập kể cả khi cho bán vượt tồn"),
}


# ------------------------------------------------------------------------------------------------ chuẩn hoá giá trị
def _so(v):
	if isinstance(v, bool) or v is None:
		return v
	if isinstance(v, (int, float)):
		return float(v)
	if isinstance(v, dict):
		return {a: _so(b) for a, b in v.items()}
	if isinstance(v, list):
		return [_so(x) for x in v]
	return v


def _bo_null(d: dict) -> dict:
	"""jsonb_strip_nulls của bộ sinh: khoá mang null bị bỏ."""
	return {k: v for k, v in d.items() if v is not None}


def _gio(v):
	"""Mốc giờ (cổng trả ISO kèm múi giờ site) → datetime không múi giờ theo giờ site."""
	from zoneinfo import ZoneInfo

	from frappe.utils import get_system_timezone

	d = get_datetime(v)
	return d.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None) if d.tzinfo else d


def _dv(v):
	"""Đơn vị tính so KHÔNG phân biệt dấu / hoa thường: UOM của Frappe là bản ghi (khoá `name`, collation utf8mb4_unicode_ci) — "thùng" và "Thung"
	là MỘT đơn vị, tên lưu theo bản ghi có trước (nppsale lưu chữ tự do của từng dòng)."""
	import unicodedata

	if not isinstance(v, str):
		return v
	return "".join(c for c in unicodedata.normalize("NFD", v.replace("đ", "d").replace("Đ", "D")) if unicodedata.category(c) != "Mn").lower()


def _gap_dv(v):
	"""Gập mọi khoá đơn vị (`dv`, `dv_gd`, `unit_name`) của một giá trị lồng — áp cho cả hai phía trước khi so."""
	if isinstance(v, dict):
		return {k: (_dv(x) if k in ("dv", "dv_gd", "unit_name") else _gap_dv(x)) for k, x in v.items()}
	if isinstance(v, list):
		return _xep([_gap_dv(x) for x in v]) if v and isinstance(v[0], dict) and "stt" not in v[0] else [_gap_dv(x) for x in v]
	return v


def _xep(ds: list) -> list:
	return sorted(ds, key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False))


# ------------------------------------------------------------------------------------------------ bộ dữ liệu F (§6.0)
def dung_nen_kho(nen: dict) -> dict:
	"""Người (NPP A), NCC, mặt hàng (theo lô trừ X — câu 14 B), khách, giá bán; cờ bán vượt tồn / ngưỡng kho date như nền."""
	from nppsale.rpc.don_hang import _dam_bao_uom
	from nppsale.su_kien.san_pham import bang_gia_chung

	ma = {}
	for i, (k, (vai, npp)) in enumerate(nen["nguoi"].items()):
		if npp != "A":
			continue
		sdt = f"0918{700000 + i:06d}"
		email = email_ky_thuat(sdt)
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": k, "send_welcome_email": 0}).insert(ignore_permissions=True)
		if not frappe.db.exists("NPP Nhan Vien", email):
			frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": k, "vai": vai, "sdt": sdt, "dang_hoat_dong": 1}).insert(
				ignore_permissions=True)
		ma["u:" + k] = email
	nhom_ncc = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
	for k, (ten, ma_ncc, npp, them) in nen["ncc"].items():
		if npp != "A":
			continue
		ma[k] = frappe.get_doc({"doctype": "Supplier", "supplier_name": ten, "supplier_group": nhom_ncc, "npp_ma": ma_ncc,
			"npp_dien_thoai": them.get("phone"), "tax_id": them.get("tax_code"), "supplier_details": them.get("notes")}).insert(
			ignore_permissions=True).name
		if them.get("email"):  # "hai@ncc" của nền: trường Email của Frappe kiểm dạng — nppsale lưu chữ tự do
			frappe.db.set_value("Supplier", ma[k], "npp_email", them["email"], update_modified=False)
	nhom_hang = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	hang = {k: (*v, {}) for k, v in nen["hang"].items()} | nen.get("hang_frappe", {})
	for k, (sku, ten, dv, han, dvs, _ncc, them) in hang.items():
		for u in [dv, *dvs]:
			_dam_bao_uom(u)
		co_lo = them.get("has_batch_no", 1)
		if not frappe.db.exists("Item", sku):
			frappe.get_doc({"doctype": "Item", "item_code": sku, "item_name": ten, "item_group": nhom_hang, "stock_uom": dv, "is_stock_item": 1,
				"has_batch_no": co_lo, "create_new_batch": 0, "has_expiry_date": 1 if (co_lo and han) else 0, "shelf_life_in_days": han or 0,
				"allow_negative_stock": them.get("allow_negative_stock", 0), "npp_thue_suat": 0,
				"uoms": [{"uom": u, "conversion_factor": h} for u, h in dvs.items()]}).insert(ignore_permissions=True)
		ma[k] = sku
	nhom_khach = "VTD Khong Nhom"
	if not frappe.db.exists("Customer Group", nhom_khach):
		frappe.get_doc({"doctype": "Customer Group", "customer_group_name": nhom_khach, "parent_customer_group": "All Customer Groups",
			"is_group": 0}).insert(ignore_permissions=True)
	for i, (k, ten) in enumerate(nen["khach"].items()):
		ma[k] = frappe.db.get_value("Customer", {"customer_name": ten}, "name") or frappe.get_doc({"doctype": "Customer", "customer_name": ten,
			"customer_type": "Company", "customer_group": nhom_khach, "npp_sdt": f"09187900{i + 1:02d}"}).insert(ignore_permissions=True).name
	for sp, dv, gia in nen["gia_ban"]:
		if not frappe.db.exists("Item Price", {"item_code": ma[sp], "price_list": bang_gia_chung(), "uom": dv}):
			frappe.get_doc({"doctype": "Item Price", "item_code": ma[sp], "price_list": bang_gia_chung(), "uom": dv, "price_list_rate": gia}).insert(
				ignore_permissions=True)
	frappe.db.set_single_value("NPP Cai Dat", {"cho_ban_vuot_ton": 1 if nen["cho_ban_vuot_ton"] else 0,
		"nguong_kho_date_ngay": nen["nguong_kho_date_ngay"]})
	frappe.local._npp_cai_dat_ban = None
	ma["org"] = frappe.db.get_single_value("NPP Cai Dat", "org_id")
	return ma


class TestKhoMuaVang(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)

	def setUp(self):
		frappe.db.savepoint("npp_test")
		# commit thật làm mất điểm lui (dữ liệu bài nằm lại sổ — sự cố M0); Error Log là MyISAM; việc repost nền không đẩy vào Redis
		self.nhat_ky, self.repost = [], []
		for p in (patch.object(frappe.db, "commit", lambda *a, **k: None),
				patch.object(frappe, "log_error", lambda title=None, message=None, **k: self.nhat_ky.append(title)),
				patch("nppsale.rpc.phieu_nhap._xep_repost", lambda: self.repost.append(1))):
			p.start()
			self.addCleanup(p.stop)
		frappe.local._npp_cai_dat_ban = None
		self.cd = cai_dat_kho()
		self.co_san = {dt: set(frappe.get_all(dt, pluck="name")) for dt in ("Purchase Invoice", "Batch", "NPP Cong No NCC", "Sales Invoice",
			"Item Price")}
		self.ma = dung_nen_kho(self.vang["nen"])
		self.khoa_cua = {v: "@" + k for k, v in self.ma.items()}  # tên Frappe → khoá nền (@A, @S1, @u:TK)
		self.vung = {self.cd.kho_ban: "sale", self.cd.kho_can_date: "date"}

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_cai_dat_ban = None
		frappe.local._npp_ngu_canh = None

	# ------------------------------------------------------------------------------------------------ gọi dưới đúng người
	def _nguoi(self, nguoi: str):
		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None

	def _ve_admin(self):
		frappe.set_user("Administrator")
		frappe.local._npp_ngu_canh = None
		frappe.local._npp_cai_dat_ban = None

	def _goi(self, nguoi: str, ten: str, ts: dict) -> dict:
		self._nguoi(nguoi)
		try:
			return api.rpc(ten=ten, tham_so=ts)
		finally:
			self._ve_admin()

	def _cong(self, nguoi: str, yc: dict) -> dict:
		self._nguoi(nguoi)
		try:
			return api.truy_van(yeu_cau=yc)
		finally:
			self._ve_admin()

	# ------------------------------------------------------------------------------------------------ chỗ giữ + nhãn
	def _thay(self, v, st: dict):
		"""Chỗ giữ của tải trọng → giá trị trên site: "@org", "@A", "@S1", "@u:TK", "@pn:<nhãn>", "@hom_nay±n"."""
		if isinstance(v, str):
			if v == "@org":
				return self.ma["org"]
			if v.startswith("@hom_nay"):
				return XH.ngay_tuong_doi(v)
			if v.startswith("@pn:"):
				return self._ten(st, "pn:" + v[4:])
			if v.startswith("@"):
				return self.ma.get(v[1:], v)
			return v
		if isinstance(v, dict):
			return {a: self._thay(b, st) for a, b in v.items()}
		if isinstance(v, list):
			return [self._thay(x, st) for x in v]
		return v

	@staticmethod
	def _cuoi(ten: str | None) -> str | None:
		"""Tờ cuối của chuỗi amend (CFD-01)."""
		for _ in range(50):
			x = frappe.db.get_value("Purchase Invoice", {"amended_from": ten}, "name", order_by="creation desc") if ten else None
			if not x:
				return ten
			ten = x
		return ten

	@staticmethod
	def _goc(ten: str | None) -> str | None:
		for _ in range(50):
			x = frappe.db.get_value("Purchase Invoice", ten, "amended_from") if ten else None
			if not x:
				return ten
			ten = x
		return ten

	def _ten(self, st: dict, nhan: str) -> str | None:
		"""Nhãn → tên Frappe của tờ CÒN HIỆU LỰC (tờ cuối chuỗi amend)."""
		goc = st["nhan"].get(nhan)
		return self._cuoi(goc) if nhan.startswith("pn:") else goc

	def _nhan_pn(self, st: dict, ten: str | None) -> str | None:
		goc = self._goc(ten)
		return next((k[3:] for k, v in st["nhan"].items() if k.startswith("pn:") and v == goc), None)

	def _ma_pn(self, st: dict, ten: str | None):
		"""Tên một tờ của chuỗi → "<nhãn>" (tờ ngoài kịch bản giữ tên)."""
		n = self._nhan_pn(st, ten)
		return f"<{n}>" if n else ten

	def _ma_lo(self, st: dict, ma: str | None):
		m = re.fullmatch(r"(.+)-(\d{3})", ma or "")
		if m and self._nhan_pn(st, m.group(1)):
			return f"<{self._nhan_pn(st, m.group(1))}>-{m.group(2)}"
		return ma

	def _chu_ma(self, st: dict, chu: str | None):
		"""Mã phiếu trong câu chữ (ghi chú công nợ…) → "<nhãn>" — tên dài (tờ amend) thay trước."""
		if not chu:
			return chu
		ten = sorted({x for v in st["nhan"].values() if v for x in frappe.get_all("Purchase Invoice",
			filters={"name": ("like", f"{v}%")}, pluck="name")}, key=len, reverse=True)
		for x in ten:
			n = self._nhan_pn(st, x)
			if n:
				chu = re.sub(rf"(?<![\w-]){re.escape(x)}(?![\w-])", f"<{n}>", chu)
		return chu

	def _luc(self, v):
		if not v:
			return None
		d = _gio(v)
		if abs((now_datetime() - d).total_seconds()) < 3 * 3600:
			return "@luc_goi"
		n = (d.date() - XH.hom_nay()).days
		return f"@hom_nay{n:+d}T{d:%H:%M}" if n else f"@hom_nayT{d:%H:%M}"

	@staticmethod
	def _ngay(v):
		if not v:
			return None
		d = getdate(v)
		n = (d - XH.hom_nay()).days
		if abs(n) > 400:
			return str(d)
		return "@hom_nay" if n == 0 else f"@hom_nay{n:+d}"

	# ------------------------------------------------------------------------------------------------ một bước
	def _buoc(self, b: dict, st: dict) -> tuple[dict, object]:
		"""→ (kết quả cổng {data} | {error}, số trả về đã chuẩn hoá để so `tra` — None khi bước không trả gì)."""
		k = b["buoc"]
		if k == "pn":
			ket = self._cong(b["nguoi"], {"bang": "purchase_invoices", "hanh_dong": "insert", "gia_tri": self._thay(b["dau"], st), "select": "id"})
			if "error" in ket:
				return ket, None
			st["nhan"]["pn:" + b["nhan"]] = ket["data"][0]["id"]
			return self._ghi_dong(b, st), None
		if k == "pn_dong":
			ten = self._ten(st, "pn:" + b["nhan"])
			ket = self._cong(b["nguoi"], {"bang": "purchase_invoice_lines", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "invoice_id",
				"gt": ten}]})
			return (ket if "error" in ket else self._ghi_dong(b, st)), None
		if k in ("pn_hoan", "pn_huy", "pn_khoi_phuc"):
			ten = {"pn_hoan": "complete_purchase_invoice", "pn_huy": "cancel_purchase_invoice", "pn_khoi_phuc": "khoi_phuc_phieu_nhap"}[k]
			ts = {"p_invoice_id": self._ten(st, "pn:" + b["nhan"])}
			if k == "pn_huy":
				ts["p_reason"] = b.get("ly_do")
			ket = self._goi(b["nguoi"], ten, ts)
			if "error" in ket:
				return ket, None
			r = ket["data"]
			if isinstance(r, dict):
				return ket, {**r, "id": "pn:" + (self._nhan_pn(st, r.get("id")) or "?")}
			return ket, "pn:" + (self._nhan_pn(st, r) or "?")
		if k == "gia":
			ket = self._goi(b["nguoi"], "luu_gia_nhap", {"p_dong": self._thay(b.get("p_dong"), st)})
			return ket, None if "error" in ket else ket["data"]
		if k == "doc_bang":
			cot = b.get("cot")
			yc = {"bang": b["bang"], "select": ", ".join([*cot, "__id:id"]) if cot else "*",
				"loc": [{"op": "eq", "cot": c, "gt": self._thay(v, st)} for c, v in (b.get("loc") or {}).items()]}
			ket = self._cong(b["nguoi"], yc)
			if "error" in ket:
				return ket, None
			cu = set().union(*self.co_san.values())  # dòng có sẵn trên site (dữ liệu dựng thử cũ) không thuộc kịch bản
			ds = [r for r in ket["data"] if (r.get("__id") or r.get("id")) not in cu]
			return ket, _xep([self._chuan_dong({c: v for c, v in r.items() if c != "__id"}, st) for r in ds])
		if k == "dem":
			ket = self._cong(b["nguoi"], {"bang": b["bang"], "select": "id", "count": "exact", "head": True,
				"loc": [{"op": "eq", "cot": c, "gt": self._thay(v, st)} for c, v in (b.get("loc") or {}).items()]})
			return ket, None if "error" in ket else {"so": ket["count"]}
		if k == "ghi":
			yc = {"bang": b["bang"], "hanh_dong": b["hanh_dong"], "select": "id",
				"loc": [{"op": "eq", "cot": c, "gt": self._thay(v, st)} for c, v in (b.get("loc") or {}).items()]}
			if b["hanh_dong"] != "delete":
				yc["gia_tri"] = self._thay(b.get("gia_tri"), st)
			ket = self._cong(b["nguoi"], yc)
			return ket, None if "error" in ket else {"so_dong": len(ket.get("data") or [])}
		if k == "co_am":
			frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 1 if b.get("bat", True) else 0)
			frappe.local._npp_cai_dat_ban = None
			return {"data": None}, None
		if k == "nguong":
			frappe.db.set_single_value("NPP Cai Dat", "nguong_kho_date_ngay", b["ngay"])
			frappe.local._npp_cai_dat_ban = None
			return {"data": None}, None
		if k == "ban":
			return self._ban(b, st)
		if k == "huy_hd":
			ket = self._goi(b["nguoi"], "cancel_invoice", {"p_invoice_id": st["nhan"].get("hd:" + b["nhan"]), "p_reason": b.get("ly_do")})
			if "error" in ket:
				return ket, None
			r = ket["data"][0]
			return ket, {"order_status": r.get("order_status"), "import_entry_id": bool(r.get("import_entry_id"))}
		raise ValueError(f"bước chưa dựng ở bài so: {k}")

	def _ghi_dong(self, b: dict, st: dict) -> dict:
		ten = self._ten(st, "pn:" + b["nhan"])
		dong = [{**self._thay(d, st), "invoice_id": ten} for d in b.get("dong") or []]
		if not dong:
			return {"data": []}
		return self._cong(b["nguoi"], {"bang": "purchase_invoice_lines", "hanh_dong": "insert", "gia_tri": dong, "select": "id"})

	def _ban(self, b: dict, st: dict) -> tuple[dict, object]:
		"""Bán làm nền (P3): create_order_with_lines (đơn submitted, giá bảng giá bán nền) + post_invoice đủ dòng — như `_ban_sql` của bộ sinh."""
		gia = {(sp, dv): g for sp, dv, g in self.vang["nen"]["gia_ban"]}
		gia_cua = lambda x: gia.get((x["product_id"][1:], x["unit_name"]), 10000)  # noqa: E731 — X (chỉ Frappe) không có giá bán nền
		dong = [{"product_id": self.ma[x["product_id"][1:]], "unit_name": x["unit_name"], "quantity": x["quantity"], "unit_price": gia_cua(x),
			"line_discount": 0, "conversion_factor": 1, "vat_rate": 0, "line_total": x["quantity"] * gia_cua(x)} for x in b["dong"]]
		tong = sum(x["line_total"] for x in dong)
		p = {"client_request_id": str(uuid.uuid5(NS, f"{st['ma']}:don:{b['nhan']}")), "order": {"order_code": "TAM-1",
			"customer_id": self.ma[b.get("khach", "@K1")[1:]], "payment_terms": "COD", "expected_delivery": None, "subtotal": tong, "vat": 0,
			"total": tong, "notes": None, "status": "submitted", "approval_reason": None, "sales_user_id": None}, "lines": dong, "returns": None,
			"return_lines": []}
		ket = self._goi(b["nguoi"], "create_order_with_lines", {"p": p})
		if "error" in ket:
			return ket, None
		don = ket["data"][0]["order_id"]
		dd = frappe.get_all("Sales Order Item", filters={"parent": don}, fields=["name", "item_code", "uom", "conversion_factor", "qty", "rate",
			"npp_giam_dong", "npp_thue_suat", "additional_notes"], order_by="idx asc")
		lines = [{"order_line_id": r.name, "product_id": r.item_code, "unit_name": r.uom, "conversion_factor": r.conversion_factor, "quantity": r.qty,
			"unit_price": r.rate, "line_discount": r.npp_giam_dong, "vat_rate": r.npp_thue_suat, "is_exchange": False, "note": r.additional_notes}
			for r in dd]
		ket = self._goi(b["nguoi"], "post_invoice", {"p": {"order_id": don, "lines": lines}})
		if "error" in ket:
			return ket, None
		r = ket["data"][0]
		st["nhan"]["hd:" + b["nhan"]] = r["invoice_id"]
		st["nhan"]["don:" + b["nhan"]] = don
		return ket, {"short_qty": flt(r.get("short_qty")), "invoice_id": "hd:" + b["nhan"], "invoice_code": r.get("invoice_code"),
			"order_status": r.get("order_status"), "receivable_id": "@id" if r.get("receivable_id") else None,
			"near_expiry_skipped": flt(r.get("near_expiry_skipped"))}

	def _chuan_dong(self, r: dict, st: dict) -> dict:
		"""Dòng đọc qua cổng → khoá nghiệp vụ (cùng luật `chuan_gt` của bộ sinh): mặt hàng / NCC / người → khoá nền; phiếu nhập → "pn:<nhãn>";
		ngày → "@hom_nay±n"; số → float."""
		ra = {}
		for k, v in r.items():
			if k == "source_invoice_id" or (k.endswith("invoice_id") and v):
				v = ("pn:" + (self._nhan_pn(st, v) or "?")) if v else None
			elif isinstance(v, str) and v in self.khoa_cua:
				v = self.khoa_cua[v]
			elif k.endswith(("_date", "_at")) and v:
				v = self._ngay(v) if k.endswith("_date") else self._luc(v)
			ra[k] = _so(v)
		return ra

	# ------------------------------------------------------------------------------------------------ ảnh chụp cuối (cùng dạng _vp4_anh)
	def _ct(self, st: dict) -> dict:
		k = self.khoa_cua.get
		chuoi = {nhan[3:]: self._cuoi(goc) for nhan, goc in st["nhan"].items() if nhan.startswith("pn:") and goc}
		pn, phieu_kho = [], []
		for nhan, ten in chuoi.items():
			r = doc_cong({"bang": "purchase_invoices", "select": "*, lines:purchase_invoice_lines(*)", "loc": [{"op": "eq", "cot": "id", "gt": ten}]},
				ADMIN)["data"][0]
			dong = [_bo_null({"sp": k(d["product_id"]), "dv": d["unit_name"], "sl": d["quantity"], "gia": d["unit_price"], "giam": d["line_discount"],
				"thue": d["vat_rate"], "hs": d["conversion_factor"], "tien": d["line_total"], "ghi_chu": d["notes"], "stt": d["sort_order"]})
				for d in sorted(r["lines"], key=lambda x: x["sort_order"])]
			pn.append(_bo_null({"nhan": nhan, "ma": f"<{nhan}>", "status": r["status"], "ncc": k(r["supplier_id"]), "so_hd": r["invoice_number"],
				"ngay": self._ngay(r["invoice_date"]), "vung": r["warehouse_zone"], "subtotal": r["subtotal"], "vat": r["vat"], "total": r["total"],
				"giam": r["discount"], "thue_tay": r["vat_override"], "ghi_chu": r["notes"], "lap_boi": k(r["created_by"]),
				"luc_hoan_thanh": self._luc(r["completed_at"]), "luc_huy": self._luc(r["cancelled_at"]), "huy_boi": k(r["cancelled_by"]),
				"ly_do_huy": r["cancel_reason"], "phieu_kho": f"<{nhan}>" if r["stock_entry_id"] else None, "co_phieu_kho": bool(r["stock_entry_id"]),
				"no": f"PN:<{nhan}>" if r["payable_id"] else None, "dong": dong or None}))
			if r["stock_entry_id"]:
				phieu_kho.append(self._phieu_kho_pn(nhan, ten, r, st))
		lo = []
		for r in doc_cong({"bang": "batches", "select": "*"}, ADMIN)["data"]:
			ma_lo = r["batch_code"]
			if ma_lo in self.co_san["Batch"] or r["id"].startswith("~"):
				continue
			lo.append(_bo_null({"sp": k(r["product_id"]), "ma": self._ma_lo(st, ma_lo), "vung": r["warehouse_zone"], "nhap": r["qty_initial"],
				"ton": r["qty_on_hand"], "gia": round(flt(r["unit_cost"]), 2), "status": r["status"], "han": self._ngay(r["expires_at"]),
				"nsx": self._ngay(r["manufactured_at"]), "vi_tri": r["location"], "luc_nhan": self._luc(r["received_at"]),
				"luc_chuyen_vung": self._luc(r["zone_moved_at"]), "chuyen_boi": k(r["zone_moved_by"])}))
		no = []
		ncc = [v for kk, v in self.ma.items() if re.fullmatch(r"S\d", kk)]
		for r in doc_cong({"bang": "payables", "select": "*", "loc": [{"op": "in", "cot": "supplier_id", "gt": ncc}]}, ADMIN)["data"]:
			if r["id"] in self.co_san["NPP Cong No NCC"]:
				continue
			nguon = frappe.db.get_value("NPP Cong No NCC", r["id"], ["loai", "chung_tu"], as_dict=True)
			khoa = {"phieu_nhap": "PN:", "tra_ncc": "PTNCC:"}.get(nguon.loai, nguon.loai + ":") + str(self._ma_pn(st, nguon.chung_tu))
			pi_luc = frappe.db.get_value("Purchase Invoice", nguon.chung_tu, "npp_hoan_thanh_luc") if nguon.chung_tu else None
			tao = frappe.db.get_value("NPP Cong No NCC", r["id"], "tao_luc")
			no.append(_bo_null({"khoa": khoa, "ncc": k(r["supplier_id"]), "so_hd": r["invoice_number"], "so_tien": r["amount"], "da_tra": r["paid"],
				"status": r["status"], "han": self._ngay(r["due_date"]), "ghi_chu": self._chu_ma(st, r["notes"]), "dau_ky": bool(r["opening_balance"]),
				"luc": self._luc(r["created_at"]), "phieu_kho": self._ma_pn(st, r["stock_entry_id"]),
				"luc_bang_hoan_thanh": (get_datetime(pi_luc) == get_datetime(tao)) if pi_luc and tao else None}))
		gia_nhap = []
		hang = [v for kk, v in self.ma.items() if re.fullmatch(r"[A-Z]", kk)]
		for r in doc_cong({"bang": "purchase_price_lists", "select": "*", "loc": [{"op": "in", "cot": "product_id", "gt": hang}]}, ADMIN)["data"]:
			gia_nhap.append(_bo_null({"sp": k(r["product_id"]), "dv": r["unit_name"], "gia": r["price"], "ngay": self._ngay(r["effective_date"]),
				"nguon": self._ma_pn(st, r["source_invoice_id"]), "sua_boi": k(r["updated_by"])}))
		hd = []
		for nhan, ten in st["nhan"].items():
			if nhan.startswith("hd:") and ten:
				r = frappe.db.get_value("Sales Invoice", ten, ["name", "docstatus", "grand_total"], as_dict=True)
				hd.append({"nhan": nhan[3:], "ma": r.name, "status": {1: "posted", 2: "cancelled"}.get(r.docstatus, "draft"), "total": r.grand_total})
		return {"pn": _xep(_so(pn)) or None, "lo": _xep(_so(lo)) or None, "no": _xep(_so(no)) or None, "gia_nhap": _xep(_so(gia_nhap)) or None,
			"phieu_kho": _xep(_so(phieu_kho)) or None, "hd": _xep(_so(hd)) or None, "nhan": sorted(st["nhan"])}

	def _phieu_kho_pn(self, nhan: str, ten: str, r: dict, st: dict) -> dict:
		"""Phiếu kho của phiếu nhập = chính PI (⚠K §7.2 #14): dòng = dòng PI, lô theo gói lô (cả gói đã huỷ), giá = giá vốn mỗi đơn vị cơ sở."""
		from nppsale.rpc.phieu_nhap import _lo_cua_dong

		lo_dong = _lo_cua_dong(ten)
		dong = []
		for d in frappe.get_all("Purchase Invoice Item", filters={"parent": ten, "parenttype": "Purchase Invoice"}, fields=["name", "item_code", "uom",
				"qty", "stock_qty", "conversion_factor", "warehouse", "valuation_rate"], order_by="idx asc"):
			lo = lo_dong.get(d.name)
			gia = frappe.db.sql("""SELECT e.`incoming_rate` FROM `tabSerial and Batch Entry` e JOIN `tabSerial and Batch Bundle` b ON b.`name` = e.`parent`
				WHERE b.`voucher_type` = 'Purchase Invoice' AND b.`voucher_no` = %s AND b.`voucher_detail_no` = %s LIMIT 1""", (ten, d.name))
			dong.append({"sp": self.khoa_cua.get(d.item_code), "lo": f"{self._ma_lo(st, lo)}@{self.vung.get(d.warehouse)}" if lo else None,
				"dv": d.uom, "sl_cs": d.stock_qty, "sl_gd": d.qty, "dv_gd": d.uom, "hs": d.conversion_factor,
				"gia": round(flt(gia[0][0] if gia else d.valuation_rate), 2)})
		return _bo_null({"ma": f"<{nhan}>", "loai": "import", "status": "posted" if r["status"] == "completed" else "cancelled",
			"vung": r["warehouse_zone"], "ncc": self.khoa_cua.get(r["supplier_id"]), "ghi_chu": r["notes"], "luc_ghi_so": "@luc_goi",
			"lap_boi": self.khoa_cua.get(r["created_by"]), "so_don": 0, "dong": _xep([_bo_null(x) for x in dong])})

	def _chuan_mong(self, ct: dict) -> dict:
		"""Ảnh chụp nppsale → cùng dạng bên Frappe theo các luật chuẩn hoá ở đầu tệp."""
		ct = copy.deepcopy(ct or {})
		ma_nhan = {p["ma"]: p["nhan"] for p in ct.get("pn") or [] if p.get("ma")}

		def nhan(ma):
			return f"<{ma_nhan[ma]}>" if ma in ma_nhan else ma

		def lo(ma):
			m = re.fullmatch(r"(.+)-(\d{3})(@\w+)?", ma or "")
			return f"{nhan(m.group(1))}-{m.group(2)}{m.group(3) or ''}" if m and m.group(1) in ma_nhan else ma

		def chu(s):
			for ma in sorted(ma_nhan, key=len, reverse=True):
				s = re.sub(rf"(?<![\w-]){re.escape(ma)}(?![\w-])", nhan(ma), s) if s else s
			return s

		ghi_chu_pn = {}
		for p in ct.get("pn") or []:
			p["ma"] = f"<{p['nhan']}>"  # câu 18: phiếu tạm cũng có số
			if p.get("phieu_kho"):
				p["phieu_kho"] = nhan(p["phieu_kho"])
			if p.get("no"):
				p["no"] = "PN:" + nhan(p["no"].split(":", 1)[1])
			ghi_chu_pn[p["ma"]] = p.get("ghi_chu")
		for x in ct.get("lo") or []:
			x["ma"] = lo(x["ma"])
			x["gia"] = round(flt(x.get("gia")), 2)
			if x.get("status") == "cancelled":
				x["nhap"] = 0.0  # §7.2 #26: lô chưa phát sinh của cổng batches
		for x in ct.get("no") or []:
			loai, ma = x["khoa"].split(":", 1)
			x["khoa"] = f"{loai}:{nhan(ma)}"
			if x.get("phieu_kho"):
				x["phieu_kho"] = nhan(x["phieu_kho"])
			if x.get("ghi_chu"):
				x["ghi_chu"] = chu(x["ghi_chu"])
		for x in ct.get("gia_nhap") or []:
			if x.get("nguon"):
				x["nguon"] = nhan(x["nguon"])
		pk = []
		for x in ct.get("phieu_kho") or []:
			if x.get("ma") not in ma_nhan:
				continue  # phiếu kho của HĐ / hoàn kho — cổng stock_entries (M4)
			x["ma"] = nhan(x["ma"])
			x.pop("ghi_chu", None)
			if ghi_chu_pn.get(x["ma"]):
				x["ghi_chu"] = ghi_chu_pn[x["ma"]]
			for d in x.get("dong") or []:
				d.pop("sl", None)
				d.pop("vet", None)
				d["lo"] = lo(d.get("lo"))
				d["gia"] = round(flt(d.get("gia")), 2)
			x["dong"] = _xep(_so(x.get("dong") or []))
			pk.append(x)
		ct["phieu_kho"] = pk or None
		for x in ct.get("hd") or []:
			x.pop("phieu_kho", None)
		return {m: (_xep(_so(ct.get(m))) if isinstance(ct.get(m), list) and m != "nhan" else ct.get(m)) or None for m in MUC_SO} | {
			"nhan": sorted(ct.get("nhan") or [])}

	def _chuan_tra(self, tra):
		"""`tra` của bước bên nppsale → cùng dạng: HĐ bán bỏ `entry_id` (phiếu kho = chính HĐ — M4), id phiếu kho hoàn → có / không; số → float."""
		if isinstance(tra, dict):
			tra = dict(tra)
			tra.pop("entry_id", None)
			if "import_entry_id" in tra:
				tra["import_entry_id"] = bool(tra["import_entry_id"])
		if isinstance(tra, list):
			return _xep(_so(tra))
		return _so(tra)

	# ------------------------------------------------------------------------------------------------ một kịch bản
	def _mot(self, t: dict) -> list[str]:
		t = copy.deepcopy(t)
		mong = t["mong"]
		lech = LECH.get(t["ma"])
		if lech:
			lech[0](t, mong)
		sai = []
		st = {"ma": t["ma"], "nhan": {}}
		for i, (b, m) in enumerate(zip(t["buoc"], mong["buoc"], strict=False)):
			if b.get("chi_nppsale"):
				continue
			nhan = f"{t['ma']} bước {i + 1} ({b['buoc']} — {b['nguoi']})"
			ket, tv = self._buoc(b, st)
			if m["ok"]:
				if "error" in ket:
					return [*sai, f"{nhan}: nppsale ghi được — bản Frappe báo {ket['error']['code']} {ket['error']['message'][:400]} "
						f"{(ket['error'].get('details') or '')[:300]}"]
				if m.get("tra") is not None and _gap_dv(self._chuan_tra(m["tra"])) != _gap_dv(_so(tv)):
					sai.append(f"{nhan}: trả về {json.dumps(tv, ensure_ascii=False)[:600]} ≠ nppsale "
						f"{json.dumps(self._chuan_tra(m['tra']), ensure_ascii=False)[:600]}")
				continue
			if "error" not in ket:
				return [*sai, f"{nhan}: nppsale báo {m['ma_loi']} {m['loi'][:300]} — bản Frappe lại ghi được"]
			if (ket["error"]["code"], ket["error"]["message"]) != (m["ma_loi"], m["loi"]):
				sai.append(f"{nhan}: lỗi {ket['error']['code']} {ket['error']['message'][:400]} ≠ nppsale {m['ma_loi']} {m['loi'][:400]}")
			if not b.get("tiep"):
				break
		ct = _gap_dv(self._ct(st))
		ct_mong = _gap_dv(self._chuan_mong(mong.get("ct")))
		for k in MUC_SO:
			if ct.get(k) != ct_mong.get(k):
				sai.append(f"{t['ma']}: {k} lệch ở {'; '.join(XH._cho_lech(ct.get(k), ct_mong.get(k)))[:3000]}")
		from nppsale.kham_so import quet_cong_no_ncc

		for d in quet_cong_no_ncc([v for kk, v in self.ma.items() if re.fullmatch(r"S\d", kk)]):
			sai.append(f"{t['ma']}: khám sổ NCC nhóm {d.get('nhom')} {d.get('loai')} — {d.get('chung_tu')}: {d.get('chi_tiet')}")
		return sai

	# ------------------------------------------------------------------------------------------------ kịch bản [Frappe] (`nguon: dac_ta`)
	def _v02c(self, t: dict) -> list[str]:
		"""Hai tiến trình cùng Hoàn thành một phiếu nháp: không chạy hai tiến trình thật được trong một giao dịch bài (nháp chưa commit, tiến trình kia
		không thấy) — kiểm điều kiện đủ của luật: (a) câu ĐẦU của thân hàm (sau bước chuẩn bị) là khoá Bin, câu kế là khoá PI `FOR UPDATE`, mọi câu
		đọc PI / dòng sau đó — lượt thứ hai xếp hàng ở khoá PI rồi thấy docstatus 1; (b) gọi lần hai trả đúng tên, không nhập kho / lô / nợ lần hai."""
		sai = []
		st = {"ma": t["ma"], "nhan": {}}
		ket, _ = self._buoc(t["buoc"][0], st)
		if "error" in ket:
			return [f"V02c: lập phiếu nháp hỏng {ket['error']}"]
		ten = self._ten(st, "pn:P")
		cau, moc = [], []
		goc_sql, goc_sp = frappe.db.sql, frappe.db.savepoint

		def ghi_sql(q, *a, **kw):
			cau.append(str(q))
			return goc_sql(q, *a, **kw)

		def ghi_sp(ten_sp, *a, **kw):
			kq = goc_sp(ten_sp, *a, **kw)
			if ten_sp == "npp_cong_rpc":
				moc.append(len(cau))  # sau câu SAVEPOINT: câu kế là câu đầu của thân hàm
			return kq

		with patch.object(frappe.db, "sql", ghi_sql), patch.object(frappe.db, "savepoint", ghi_sp):
			k1 = self._goi("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		k2 = self._goi("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		if "error" in k1 or "error" in k2 or k1["data"] != ten or k2["data"] != ten:
			sai.append(f"V02c: hai lượt trả {k1} / {k2}, mong {ten} cả hai")
		than = [" ".join(q.split()) for q in cau[moc[0]:]] if moc else []
		if len(than) < 2 or not ("`tabBin`" in than[0] and "FOR UPDATE" in than[0]):
			sai.append(f"V02c: câu đầu thân hàm phải là khoá Bin — {than[:1]}")
		elif not ("`tabPurchase Invoice`" in than[1] and "FOR UPDATE" in than[1]):
			sai.append(f"V02c: câu thứ hai phải là khoá PI FOR UPDATE — {than[1][:200]}")
		so = (frappe.db.count("Batch", {"reference_name": ten}), frappe.db.count("NPP Cong No NCC", {"chung_tu": ten}),
			frappe.db.count("Stock Ledger Entry", {"voucher_no": ten, "is_cancelled": 0}))
		if so != (1, 1, 1):
			sai.append(f"V02c: lô / dòng nợ / dòng sổ kho = {so}, mong (1, 1, 1) — nhập kho đúng một lần")
		return sai

	def _v12b(self, t: dict) -> list[str]:
		"""Hàng KHÔNG lô X (allow_negative_stock) + NPP cho bán vượt tồn: PN 48 → bán 30 → huỷ PN được, Bin kho bán −30, dòng nợ PN bỏ; huỷ HĐ →
		Bin 0 (câu 15, mig 238)."""
		sai = []
		st = {"ma": t["ma"], "nhan": {}}
		bin_x = lambda: flt(frappe.db.get_value("Bin", {"item_code": self.ma["X"], "warehouse": self.cd.kho_ban}, "actual_qty"))  # noqa: E731
		for i, b in enumerate(t["buoc"]):
			ket, _ = self._buoc(b, st)
			if "error" in ket:
				return [f"V12b bước {i + 1} ({b['buoc']}): {ket['error']['code']} {ket['error']['message'][:300]}"]
			if b["buoc"] == "pn_huy":
				ten = self._ten(st, "pn:P")
				if (bin_x(), frappe.db.get_value("Purchase Invoice", ten, "docstatus"), frappe.db.count("NPP Cong No NCC", {"chung_tu": ten})) != (
						-30, 2, 0):
					sai.append(f"V12b: sau huỷ PN mong Bin −30, PI huỷ, không dòng nợ — có Bin {bin_x()}")
		if bin_x() != 0:
			sai.append(f"V12b: sau huỷ HĐ mong Bin 0 — có {bin_x()}")
		return sai

	# ------------------------------------------------------------------------------------------------ chạy
	def test_kich_ban_vang(self):
		chi = os.environ.get("NPP_VANG_CHI")
		sai, bo = [], {"chưa dựng": [], "chỉ nppsale": [], "đặc tả chưa kiểm": []}
		da_chay = 0
		for t in self.vang["tinh_huong"]:
			if chi and not any(t["ma"].startswith(x) for x in chi.split(",")):
				continue
			if moc_cua(t["ma"]) not in DA_DUNG:
				bo["chưa dựng"].append(t["ma"])
				continue
			if t.get("chi_nppsale"):
				bo["chỉ nppsale"].append(t["ma"])
				continue
			if t.get("nguon") == "dac_ta" and t["ma"] not in KIEM_DAC_TA:
				bo["đặc tả chưa kiểm"].append(t["ma"])
				continue
			frappe.db.savepoint("npp_th")
			frappe.local._npp_cai_dat_ban = None
			try:
				sai += getattr(self, KIEM_DAC_TA[t["ma"]])(t) if t.get("nguon") == "dac_ta" else self._mot(t)
				da_chay += 1
			finally:
				frappe.db.rollback(save_point="npp_th")
				self._ve_admin()
		print(f"\nkho_mua_vang: chạy {da_chay} kịch bản; " + "; ".join(f"{k} {len(v)}" for k, v in bo.items()))
		self.assertFalse(sai, "\n".join(sai))
		self.assertFalse(self.nhat_ky, f"Error Log ghi trong bài: {self.nhat_ky}")
