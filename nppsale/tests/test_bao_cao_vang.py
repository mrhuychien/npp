"""BÁO CÁO (P6) so với CHÍNH hàm + RLS của nppsale và mã TS thật của giao diện (cần bench):

	bench --site poc.local run-tests --module nppsale.tests.test_bao_cao_vang
	NPP_VANG_CHI=VB-A0,VB-E01 bench … run-tests …        (chạy một phần — đầu mã kịch bản)

Dữ liệu vàng du_lieu/bao_cao_mau.json (tools/vang_bao_cao.py — đặc tả báo cáo P6 §5: 62 kịch bản VB-A01…VB-E16 trên ba bộ nền: Sổ BC S1 + biến thể
S2…S11, Nền N, bộ e2e một lượt E2E). Bài dựng cùng người / NCC / khách / hàng / lô trên site, phát lại cùng chuỗi bước qua cổng RPC / cổng bảng DƯỚI
ĐÚNG NGƯỜI và ĐÚNG GIỜ (đồng hồ ghim theo `gio` — hoặc `gio_frappe` — của bước), so sổ với ảnh chụp của bộ (`anh_chup` — lệch ở đây là lỗi bộ dựng,
không phải lỗi báo cáo), rồi gọi từng lời gọi của kịch bản dưới `nguoi`, đồng hồ `gio`, và so với `mong_frappe` (khác biệt có chủ đích Q1 / Q2 = 0 /
Q3 / Q9 đã tính sẵn ở bộ sinh) hoặc `mong` — chỉ phần khoá `chon` (+ bộ khoá `_khoa`).

Phạm vi theo nấc dựng (đặc tả §4.2): hàm của nấc CHƯA dựng (`NAC_HAM` ∉ `DA_DUNG`) → lời gọi "chưa dựng" (bỏ, in số); bộ nền của nấc sau (`NAC_BO`)
→ cả kịch bản "chưa dựng"; kịch bản chờ P8 (`cho`) bỏ; kịch bản chỉ có ở Frappe (`nguon` = dac_ta, không lời gọi) kiểm bằng hàm riêng ở `KIEM_DAC_TA`.
Hàm P3 / P4 đã có (`bao_cao_ton_kho`, `stock_value_summary`, `bao_cao_cong_no`, `receivables_*`, `payables_*`, cổng bảng) chạy ở mọi nấc.
Lời gọi `ts:ban_hang` chạy CHÍNH mã TS của giao diện (tools/vang_bao_cao_ts.ts — `tuMotLuot → dungDongBan → congBan`, "Hàng bán theo nhân viên",
`/reports/sales` tab Nhân viên) trên kết quả `bao_cao_so_ban` của Frappe + danh mục mặt hàng đọc qua cổng `products` — cần `portal/nguon` (mã nppsale
ghim) + `portal/node_modules/.bin/esbuild` + node: tìm ở `NPP_PORTAL`, rồi `<repo>/portal` (bản bench có hai thư mục ấy qua liên kết); thiếu thì
lời gọi TS bỏ qua và in lý do (không lặng lẽ xanh).

Chuẩn hoá trước khi so (khác có chủ đích — không phải lệch; 00_quyet_dinh_trien_khai.md Q10):
- id = name chứng từ Frappe → NHÃN của tệp vàng (mã đơn / HĐ / phiếu trả theo bước lập — `nhan` / `nhan_phu`); dòng HĐ '<HĐ>/<SKU>/<ĐV>[/doi]', dòng
  đơn '<đơn>/<SKU>/<ĐV>', công nợ 'no:<HĐ | phiếu trả>', khoản thu 'thu:<chứng từ>:<tiền>', lô '<mã lô>::<vùng>' (= id cổng `batches`); NV = email
  (`NPP Nhan Vien.name` — người dựng mang đúng email của tệp vàng); khách = SĐT (`Customer.npp_sdt`); hàng = SKU (= `item_code`).
- tên đơn vị: site dùng chung bảng UOM với collation KHÔNG phân biệt hoa thường / dấu (`utf8mb4_unicode_ci`) — 'thung' / 'thùng' của tệp vàng là UOM
  'Thung' có sẵn, 'hộp' là 'Hop' → đổi về tên vàng theo mặt hàng (khoá không dấu, chữ thường); chữ SL dạng "2 thùng 10 hộp" của TS đổi cùng luật.
- giờ → 'YYYY-MM-DDTHH:MM:SS+07:00' (bỏ phần lẻ giây); số → int khi chẵn, float khi lẻ.
- Q12 (đề xuất): kết quả `bao_cao_so_ban` có thêm khoá `tinh_lai_gia_von` (số việc Repost Item Valuation còn chờ — số nguyên ≥ 0) ngoài 6 khoá nppsale.
- `dong_hd` / `dong_tra`: nppsale ORDER BY uuid, Frappe ORDER BY name → so NHƯ TẬP (tệp vàng xếp theo khoá); kiểm riêng danh sách Frappe tăng theo id.
- giá vốn so tuyệt đối (một lô một giá mỗi mặt hàng — định giá lô của lõi = giá lô); phân bổ tiền theo dòng của mã TS (`dong`) ±1 đ (R6).
LECH: lời gọi bản Frappe khác vì CÁCH DỰNG bộ (không phải luật báo cáo) → hàm sửa phần MONG kèm lý do (bảng `LECH`).
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
import frappe.utils.data as _FUD
from frappe.tests import IntegrationTestCase

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.truy_van import doc as doc_cong
from nppsale.luat.bao_cao import CAU_QUA_HAN, MA_QUA_HAN

VANG = os.path.join(os.path.dirname(__file__), "du_lieu", "bao_cao_mau.json")
TS_GOC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tools", "vang_bao_cao_ts.ts"))
ADMIN = NguCanh(user="Administrator", vai=None, bo_qua_rls=True)
VN = ZoneInfo("Asia/Ho_Chi_Minh")

# nấc dựng (đặc tả §4.2) của từng HÀM được gọi: hàm của nấc chưa dựng → lời gọi "chưa dựng" (bỏ, đếm)
NAC_HAM = {"bao_cao_so_ban": "P6-2", "ts:ban_hang": "P6-2", "dashboard_summary": "P6-3", "dashboard_channel_revenue": "P6-3",
	"dashboard_top_customers": "P6-3", "hang_khach_da_lay": "P6-4", "my_sales_target": "P6-4", "finance_pnl": "P6-5", "finance_cash_flow": "P6-5",
	"finance_balance_sheet": "P6-5", "ts:xnt": "P6-5"}
# bộ nền dựng ở nấc sau (◇ của VB-E07 / E08 / E10 / E11; Nền N của nhóm D)
NAC_BO = {"S8": "P6-5", "S8b": "P6-5", "S9": "P6-5", "S10": "P6-3", "S11": "P6-5", "N": "P6-5"}
# hàm tổng hợp TOÀN SỔ chạy được trên Sổ BC / biến thể (dashboard_*, công nợ theo khách / tổng): kịch bản có lời gọi của chúng tách sổ của bộ khỏi dữ liệu
# khác của site trước khi gọi (`_chi_so_cua_bo`)
HAM_TOAN_SO = ("dashboard_summary", "dashboard_channel_revenue", "dashboard_top_customers", "receivables_by_customer", "receivables_summary")
# kịch bản xếp nấc riêng (đặc tả §4.2) dù có lời gọi hàm đã có: VB-A16 (tài chính / tồn / công nợ trên Sổ BC) thuộc nấc 5 — hàm TỔNG HỢP toàn sổ
# (receivables_summary, bao_cao_cong_no, stock_value_summary) cần mốc trừ phần sổ dùng chung của site, dựng cùng finance_*
NAC_KB = {"VB-A16": "P6-5"}
DA_DUNG = ("P6-2", "P6-3", "P6-4")
# khách của bộ E2E (bo.E2E.frappe: "Khách Một Lượt (0912000001), Tạp hoá Cô Ba (0912000002), Đại lý Minh (0912000003)")
TEN_KHACH_E2E = {"0912000001": "Khách Một Lượt", "0912000002": "Tạp hoá Cô Ba", "0912000003": "Đại lý Minh"}
# mã HĐ cũ của tờ H3 dựng tay (VB-E10) — không trùng dãy HD- của site
MA_HD_CU_H3 = "HD-H3-0001"
# '@la' của tệp vàng = id không thuộc NPP (nppsale: uuid lạ) — Frappe: chuỗi không phải name NV / khách nào
ID_LA = "00000000-0000-0000-0000-0000000000aa"
_RE_NHAN = re.compile(r"^(@[a-z_]+:)?[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")
_RE_LUC = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?$")


# ------------------------------------------------------------------------------------------------ đồng hồ ghim
def _gio_ghim():
	"""Thân thay cho `frappe.utils.data.now_datetime` (chạy với globals của frappe.utils.data): giờ ghim của bài, không có thì giờ thật."""
	g = getattr(frappe.local, "npp_gio_ghim", None)
	if g is not None:
		return g
	return datetime.datetime.now(ZoneInfo(get_system_timezone())).replace(tzinfo=None)  # noqa: F821 — tên của frappe.utils.data


class DongHo:
	"""Ghim đồng hồ của Frappe: thay THÂN hàm `frappe.utils.data.now_datetime` (mọi nơi đã `from frappe.utils import now_datetime` cùng giữ MỘT đối
	tượng hàm nên đều thấy) — `now`, `nowdate`, `nowtime`, `today`, `getdate()`, `get_datetime()` của Frappe đều đi qua nó. Giờ là giờ site (VN)
	không múi giờ, như Frappe lưu."""

	def __init__(self):
		self._goc = None

	def bat(self):
		self._goc = _FUD.now_datetime.__code__
		_FUD.now_datetime.__code__ = _gio_ghim.__code__

	def tat(self):
		if self._goc is not None:
			_FUD.now_datetime.__code__ = self._goc
			self._goc = None
		frappe.local.npp_gio_ghim = None

	@staticmethod
	def dat(gio: str | None):
		frappe.local.npp_gio_ghim = gio_vn(gio) if gio else None


def gio_vn(s: str) -> _dt.datetime:
	"""ISO có / không múi giờ → datetime giờ VN không múi giờ (như Frappe lưu)."""
	t = _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
	if t.tzinfo is not None:
		t = t.astimezone(VN).replace(tzinfo=None)
	return t


# ------------------------------------------------------------------------------------------------ chuẩn hoá giá trị
def so(v):
	"""Tiền / SL: int khi chẵn, float (≤ 6 chữ số lẻ) khi lẻ — như bộ sinh (`so`)."""
	if v is None or isinstance(v, bool):
		return v
	f = float(v)
	return round(f) if abs(f - round(f)) < 1e-9 else round(f, 6)


def luc(v):
	"""Mốc giờ → 'YYYY-MM-DDTHH:MM:SS+07:00' (bỏ phần lẻ giây) — như bộ sinh (`gio_vn`)."""
	if v is None:
		return None
	t = _dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
	if t.tzinfo is None:
		t = t.replace(tzinfo=VN)
	return t.astimezone(VN).replace(microsecond=0).isoformat()


def khoa_dv(s: str | None) -> str:
	"""Khoá so tên đơn vị như collation của site (không phân biệt hoa thường / dấu): 'Thung' = 'thùng' = 'thung'."""
	s = unicodedata.normalize("NFD", s or "")
	return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d").replace("Đ", "D").casefold().strip()


def _sap(ds: list) -> list:
	return sorted(ds, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False, default=str))


def _cho_lech(a, b, duong: str = "") -> list[str]:
	"""Liệt kê chỗ khác giữa hai giá trị JSON (tối đa vài chục dòng) — để đọc lỗi."""
	if isinstance(a, dict) and isinstance(b, dict):
		ra = []
		for k in sorted(set(a) | set(b), key=str):
			if k not in a:
				ra.append(f"{duong}.{k}: thiếu (mong {json.dumps(b[k], ensure_ascii=False, default=str)[:200]})")
			elif k not in b:
				ra.append(f"{duong}.{k}: thừa {json.dumps(a[k], ensure_ascii=False, default=str)[:200]}")
			else:
				ra += _cho_lech(a[k], b[k], f"{duong}.{k}")
		return ra
	if isinstance(a, list) and isinstance(b, list):
		if len(a) != len(b):
			return [f"{duong}: {len(a)} phần tử ≠ mong {len(b)} — có {json.dumps(a, ensure_ascii=False, default=str)[:900]} / mong "
				f"{json.dumps(b, ensure_ascii=False, default=str)[:900]}"]
		ra = []
		for i, (x, y) in enumerate(zip(a, b, strict=True)):
			ra += _cho_lech(x, y, f"{duong}[{i}]")
		return ra
	if a != b:
		return [f"{duong}: {json.dumps(a, ensure_ascii=False, default=str)[:300]} ≠ mong {json.dumps(b, ensure_ascii=False, default=str)[:300]}"]
	return []


def _gan_bang(a, b, dung_sai: dict | None = None, duong: str = "") -> bool:
	"""a == b, số so trong dung sai theo tên khoá (`dung_sai` = {khoá: sai số})."""
	if isinstance(a, dict) and isinstance(b, dict):
		return set(a) == set(b) and all(_gan_bang(a[k], b[k], dung_sai, k) for k in a)
	if isinstance(a, list) and isinstance(b, list):
		return len(a) == len(b) and all(_gan_bang(x, y, dung_sai, duong) for x, y in zip(a, b, strict=True))
	if dung_sai and duong in dung_sai and isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
		return abs(a - b) <= dung_sai[duong] + 1e-9
	return a == b


# ------------------------------------------------------------------------------------------------ mã TS của giao diện (node + esbuild)
_BO_TS: dict = {}


def _tim_portal() -> str | None:
	"""Thư mục portal có `nguon/src` (mã nppsale ghim) + `node_modules/.bin/esbuild`: `NPP_PORTAL`, rồi `<repo>/portal` (bản bench: hai thư mục ấy là
	liên kết tới bản làm việc — rsync bỏ qua chúng)."""
	for p in (os.environ.get("NPP_PORTAL"), os.path.join(os.path.dirname(__file__), "..", "..", "portal")):
		if p and os.path.isdir(os.path.join(p, "nguon", "src")) and os.path.exists(os.path.join(p, "node_modules", ".bin", "esbuild")):
			return os.path.abspath(p)
	return None


def _node() -> str | None:
	return shutil.which("node") or next((x for x in ("/opt/node22/bin/node", "/opt/node24/bin/node") if os.path.exists(x)), None)


def ly_do_khong_ts() -> str | None:
	if not os.path.exists(TS_GOC):
		return f"thiếu {TS_GOC}"
	if _tim_portal() is None:
		return "không thấy portal/nguon + portal/node_modules (đặt NPP_PORTAL=<đường dẫn portal>)"
	if _node() is None:
		return "không có node"
	return None


def chay_ts(cas: list[dict]) -> list[dict]:
	"""Bó tools/vang_bao_cao_ts.ts bằng esbuild (bí danh "@/*" → portal/nguon/src/* — như bộ sinh), chạy node: stdin MỘT mảng ca {ma, so_ban,
	san_pham}, stdout MỘT mảng kết quả cùng thứ tự."""
	if "bo" not in _BO_TS:
		portal = _tim_portal()
		tam = tempfile.mkdtemp(prefix="bc-vang-ts-")
		with open(os.path.join(tam, "tsconfig.json"), "w") as f:
			json.dump({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": [os.path.join(portal, "nguon", "src") + "/*"]}}}, f)
		ra = os.path.join(tam, "vang_bao_cao_ts.mjs")
		r = subprocess.run([os.path.join(portal, "node_modules", ".bin", "esbuild"), TS_GOC, "--bundle", "--platform=node", "--format=esm",
			f"--tsconfig={tam}/tsconfig.json", f"--outfile={ra}", "--log-level=warning"], capture_output=True, text=True, check=False, timeout=300)
		if r.returncode != 0:
			raise AssertionError("esbuild hỏng:\n" + r.stderr[-4000:])
		_BO_TS["bo"] = ra
	r = subprocess.run([_node(), _BO_TS["bo"]], input=json.dumps(cas, default=str), capture_output=True, text=True, check=False, timeout=300)
	if r.returncode != 0:
		raise AssertionError("node (mã TS nppsale) hỏng:\n" + r.stderr[-4000:])
	return json.loads(r.stdout)


# ------------------------------------------------------------------------------------------------ bộ nền: người / NCC / khách / hàng / lô
def _dam_bao(dt: str, ten: str, doc: dict) -> str:
	if not frappe.db.exists(dt, ten):
		frappe.get_doc({"doctype": dt, **doc}).insert(ignore_permissions=True)
	return ten


def uom_site(ten: str | None) -> str | None:
	"""Tên đơn vị (vàng) → tên bản ghi UOM của site: bảng UOM khoá theo collation không phân biệt hoa thường / dấu nên 'thung' / 'thùng' là bản ghi
	'Thung' có sẵn — dùng ĐÚNG tên bản ghi ở mọi chứng từ (như giao diện lấy đơn vị từ danh mục mặt hàng), không thì chuỗi so khớp của mã TS
	(`heSoQuyDoi`, bảng giá theo đơn vị) lệch hoa thường giữa dòng phiếu trả và danh mục."""
	if not ten:
		return ten
	return frappe.db.get_value("UOM", ten, "name") or ten


def dung_nen_bc(ten_nen: str, nen: dict, i0: int) -> dict:
	"""Danh mục của một bộ nền (`nen.S` / `nen.E2E` của tệp vàng) trên site → bảng khoá vàng → tên Frappe: "nv:<email>", "kh:<SĐT>", "sp:<SKU>",
	"ncc:<tên>", "dv:<SKU>" = {khoá đơn vị: tên vàng}. NV mang đúng email của tệp vàng (= `NPP Nhan Vien.name`); SĐT đăng nhập riêng mỗi bộ (`i0`)."""
	from nppsale.rpc.don_hang import _dam_bao_uom
	from nppsale.su_kien.san_pham import bang_gia_chung

	ma: dict = {"org": frappe.db.get_single_value("NPP Cai Dat", "org_id")}
	for i, (k, ng) in enumerate(nen["nguoi"].items()):
		email = ng["email"]
		_dam_bao("User", email, {"email": email, "first_name": ng["ten"], "send_welcome_email": 0})
		if not frappe.db.exists("NPP Nhan Vien", email):
			frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": ng["ten"], "vai": ng["vai"], "sdt": f"09196{i0 + i:05d}",
				"dang_hoat_dong": 1}).insert(ignore_permissions=True)
		ma["k:" + k] = email
		ma["nv:" + email] = email
	nhom_ncc = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
	for ten in nen.get("ncc") or []:
		ma["ncc:" + ten] = frappe.db.get_value("Supplier", {"supplier_name": ten}, "name") or frappe.get_doc({"doctype": "Supplier",
			"supplier_name": ten, "supplier_group": nhom_ncc}).insert(ignore_permissions=True).name
	for email, ds in (nen.get("cong_ty_nv") or {}).items():
		nv = frappe.get_doc("NPP Nhan Vien", email)
		for ten in ds:
			nv.append("cong_ty", {"nha_cung_cap": ma["ncc:" + ten]})
		nv.save(ignore_permissions=True)
	nhom_khach = _dam_bao("Customer Group", "VTD Khong Nhom", {"customer_group_name": "VTD Khong Nhom", "parent_customer_group": "All Customer Groups",
		"is_group": 0})
	for sdt, kh in nen["khach"].items():
		kh = kh if isinstance(kh, dict) else {"ten": TEN_KHACH_E2E.get(sdt, kh), "han_muc": 100000000}
		# mã tuyến giữ NGUYÊN như sổ nppsale ('' của khách tuyến rỗng — `hang_khach_da_lay.khach[].channel` trả thô)
		ten = frappe.get_doc({"doctype": "Customer", "customer_name": kh["ten"], "customer_type": "Company", "customer_group": nhom_khach,
			"npp_sdt": sdt, "npp_tuyen": kh.get("tuyen"), "npp_han_muc": kh.get("han_muc") or 0, "npp_chu_cua_hang": kh.get("chu"),
			"npp_dia_chi": kh.get("dia_chi")}).insert(ignore_permissions=True).name
		if kh.get("nguoi_tao"):
			frappe.db.set_value("Customer", ten, "owner", kh["nguoi_tao"], update_modified=False)
		ma["kh:" + sdt] = ten
	for pc in nen.get("phan_cong") or []:
		frappe.get_doc({"doctype": "NPP Phan Cong Khach", "khach": ma["kh:" + pc["khach"]], "nhan_vien": pc["nv"], "vai_tro": pc["vai_tro"],
			"trang_thai": pc["trang_thai"]}).insert(ignore_permissions=True)
	nhom_hang = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	cong_ty = frappe.db.get_single_value("NPP Cai Dat", "cong_ty")
	for sku, h in nen["hang"].items():
		for u in [h["dv_co_so"], *(h.get("quy_doi") or {})]:
			_dam_bao_uom(u)
		it = frappe.get_doc({"doctype": "Item", "item_code": sku, "item_name": h["ten"], "item_group": nhom_hang, "stock_uom": uom_site(h["dv_co_so"]),
			"is_stock_item": 1, "has_batch_no": 1, "create_new_batch": 0, "has_expiry_date": 1, "npp_gia_ban": h.get("gia_ban") or 0,
			"npp_thue_suat": h.get("vat") or 0, "uoms": [{"uom": uom_site(u), "conversion_factor": hs} for u, hs in (h.get("quy_doi") or {}).items()]})
		if h.get("thuong_hieu"):
			it.brand = _dam_bao("Brand", h["thuong_hieu"], {"brand": h["thuong_hieu"]})
		if h.get("ncc"):
			it.append("item_defaults", {"company": cong_ty, "default_supplier": ma["ncc:" + h["ncc"]]})
		it.insert(ignore_permissions=True)
		ma["sp:" + sku] = it.name
		# tên đơn vị vàng theo khoá collation (site có sẵn UOM 'Thung' / 'Lon' / 'Hop' — 'thùng' của tệp vàng là UOM ấy)
		ma["dv:" + sku] = {khoa_dv(u): u for u in [h["dv_co_so"], *(h.get("quy_doi") or {})]}
		for dv, gia in (h.get("bang_gia_chung") or {}).items():
			frappe.get_doc({"doctype": "Item Price", "item_code": it.name, "price_list": bang_gia_chung(), "uom": uom_site(dv),
				"price_list_rate": gia}).insert(ignore_permissions=True)
	ma["nen"] = ten_nen
	return ma


class SoDoi:
	"""Bảng đổi hai chiều của MỘT bộ nền đang dựng: nhãn vàng ↔ tên Frappe (đơn / HĐ / phiếu trả / phiếu kho) + danh mục (`dung_nen_bc`)."""

	def __init__(self, ma: dict):
		self.ma = ma
		self.nhan: dict = {}  # nhãn vàng → tên Frappe
		self.ten: dict = {}  # tên Frappe → nhãn vàng
		self.sdt = {v: k[3:] for k, v in ma.items() if k.startswith("kh:")}
		self.sku = {v: k[3:] for k, v in ma.items() if k.startswith("sp:")}
		self.ncc = {v: k[4:] for k, v in ma.items() if k.startswith("ncc:")}  # name NCC (NCC-xxxx) → tên

	def gan(self, nhan: str, ten: str | None):
		if ten:
			self.nhan[nhan] = ten
			self.ten[ten] = nhan

	def nhan_cua(self, ten):
		if ten is None:
			return None
		return self.ten.get(ten, "?" + str(ten))

	def dv(self, sku: str | None, ten: str | None):
		"""Tên UOM của site → tên đơn vị vàng của mặt hàng (khoá collation)."""
		if ten is None:
			return None
		return (self.ma.get("dv:" + str(sku)) or {}).get(khoa_dv(ten), ten)

	@staticmethod
	def dv_frappe(sku: str, ten_vang: str):
		"""Tên đơn vị vàng → tên bản ghi UOM của site (`uom_site`)."""
		return uom_site(ten_vang)


class TestBaoCaoVang(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)

	def setUp(self):
		frappe.db.savepoint("npp_test")
		# commit thật làm mất điểm lui (sự cố M0); Error Log là MyISAM; việc repost nền (ghi lùi ngày) không đẩy vào Redis — lõi chạy RIV ngay khi in_test
		self.nhat_ky = []
		for p in (patch.object(frappe.db, "commit", lambda *a, **k: None),
				patch.object(frappe, "log_error", lambda title=None, message=None, **k: self.nhat_ky.append(title)),
				patch("nppsale.rpc.phieu_nhap._xep_repost", lambda: None)):
			p.start()
			self.addCleanup(p.stop)
		self.dong_ho = DongHo()
		self.dong_ho.bat()
		self.addCleanup(self.dong_ho.tat)
		frappe.local._npp_cai_dat_ban = None
		self.bo: dict = {}  # tên bộ → SoDoi
		self.da_so: list = []  # lời gọi đã so (để in)
		self.da_dung: dict = {}  # tên bộ → danh sách lỗi dựng (rỗng = dựng sạch)

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_cai_dat_ban = None
		frappe.local._npp_ngu_canh = None

	# ------------------------------------------------------------------------------------------------ gọi dưới đúng người, đúng giờ
	def _nguoi(self, email: str | None):
		frappe.set_user(email or "Administrator")
		frappe.local._npp_ngu_canh = None
		frappe.local._npp_cai_dat_ban = None

	def _goi(self, email: str, ten: str, ts: dict, gio: str | None = None) -> dict:
		DongHo.dat(gio)
		self._nguoi(email)
		try:
			return api.rpc(ten=ten, tham_so=ts)
		finally:
			self._nguoi(None)

	def _cong(self, email: str, yc: dict, gio: str | None = None) -> dict:
		DongHo.dat(gio)
		self._nguoi(email)
		try:
			return api.truy_van(yeu_cau=yc)
		finally:
			self._nguoi(None)

	@staticmethod
	def _email(sd: SoDoi, nguoi: str) -> str:
		return sd.ma["k:" + nguoi]

	# ------------------------------------------------------------------------------------------------ chỗ giữ
	def _thay(self, v, sd: SoDoi, b: dict | None = None):
		"""Chỗ giữ của tham số (`quy_uoc` của tệp vàng) → giá trị trên site. Chỗ giữ phiếu kho chưa có (lời chèn qua cổng — id do cổng đặt, COT_BO)
		giữ nguyên."""
		if isinstance(v, dict):
			return {a: (uom_site(x) if a in ("unit_name", "transaction_uom") and isinstance(x, str) else self._thay(x, sd, b)) for a, x in v.items()}
		if isinstance(v, list):
			return [self._thay(x, sd, b) for x in v]
		if not isinstance(v, str) or not v.startswith("@"):
			return v
		if v == "@org":
			return sd.ma["org"]
		if v == "@la":
			return ID_LA
		loai, _, k = v[1:].partition(":")
		if loai == "kh":
			return sd.ma["kh:" + k]
		if loai == "sp":
			return sd.ma["sp:" + k]
		if loai == "nv":
			return sd.ma["nv:" + k]
		if loai in ("don", "hd", "pt"):
			return sd.nhan.get(k, v)
		if loai in ("pk", "ptncc", "cp"):
			return sd.nhan.get(v, v)
		if loai == "no":
			kieu, _, ma = k.partition(":")
			ten = sd.nhan.get(ma)
			dk = {"hoa_don": ten, "loai": "hoa_don"} if kieu == "hd" else {"phieu_tra": ten}
			return frappe.db.get_value("NPP Cong No", dk, "name") if ten else v
		if loai == "dong_xuat":
			return self._dong_xuat(sd, sd.nhan[k], b)
		if loai == "dong_sua":
			return self._dong_sua(sd, sd.nhan[k], (b or {}).get("doi_sl") or {})
		raise AssertionError(f"chỗ giữ lạ: {v}")

	@staticmethod
	def _chu_so(v) -> str:
		"""numeric::text của Postgres (vd '0.08', '0')."""
		x = so(v) or 0
		return str(x)

	def _dong_xuat(self, sd: SoDoi, don: str, b: dict | None) -> list:
		"""'@dong_xuat:<đơn>' = mọi dòng get_invoiceable_lines của đơn (SL còn lại, giá đơn, hàng đổi) — như kb/xuat.sql của bộ sinh / màn Xuất hàng."""
		ket = self._goi(self._email(sd, (b or {}).get("nguoi") or "CHU"), "get_invoiceable_lines", {"p_order_id": don},
			(b or {}).get("gio_frappe") or (b or {}).get("gio"))
		if "error" in ket:
			raise AssertionError(f"get_invoiceable_lines({don}): {ket['error']}")
		return [{"order_line_id": g["order_line_id"], "product_id": g["product_id"], "unit_name": g["unit_name"],
			"conversion_factor": g["conversion_factor"], "quantity": g["remaining_qty"], "unit_price": g["unit_price"],
			"line_discount": g["line_discount"], "vat_rate": self._chu_so(g["vat_rate"]), "is_exchange": g["is_exchange"], "note": g.get("note")}
			for g in ket["data"]]

	def _dong_sua(self, sd: SoDoi, hd: str, doi: dict) -> list:
		"""'@dong_sua:<HĐ>' + doi_sl {'<SKU>/<ĐV vàng>': SL | {quantity, unit_price}} = dòng hiện có của HĐ (theo thứ tự dòng), đổi SL / giá."""
		ra = []
		for r in frappe.get_all("Sales Invoice Item", filters={"parent": hd, "parenttype": "Sales Invoice"}, fields=["so_detail", "npp_dong_don",
				"item_code", "uom", "conversion_factor", "qty", "rate", "npp_giam_dong", "npp_thue_suat", "npp_hang_doi"], order_by="idx asc"):
			d = doi.get(f"{sd.sku.get(r.item_code, r.item_code)}/{sd.dv(sd.sku.get(r.item_code), r.uom)}")
			sl = d if isinstance(d, (int, float)) else (d or {}).get("quantity", r.qty)
			gia = (d or {}).get("unit_price", r.rate) if isinstance(d, dict) else r.rate
			ra.append({"order_line_id": r.so_detail or r.npp_dong_don, "product_id": r.item_code, "unit_name": r.uom,
				"conversion_factor": r.conversion_factor, "quantity": sl, "unit_price": gia, "line_discount": r.npp_giam_dong,
				"vat_rate": self._chu_so(r.npp_thue_suat), "is_exchange": bool(r.npp_hang_doi)})
		return ra

	# ------------------------------------------------------------------------------------------------ một bước của bộ nền
	def _buoc(self, b: dict, sd: SoDoi) -> dict:
		"""Phát lại một bước của `bo.<bộ>.buoc` → kết quả cổng ({data} | {error})."""
		gio = b.get("gio_frappe") or b.get("gio")
		if b["loai"] == "ghi_may_chu":
			# nppsale dời giờ ghi sổ phiếu xuất / phiếu xuất lẻ bằng quyền máy chủ — Frappe ghi sổ kho theo posting_date (Q1) và đã ghim giờ ở
			# chính bước post_stock_issue (`gio_frappe`): bước này BỎ QUA (trường `frappe` của tệp vàng)
			if not re.search(r"bỏ qua", b.get("frappe") or "", re.I):
				raise AssertionError(f"bước máy chủ chưa có cách làm bên Frappe: {b.get('mo_ta')} — {b.get('frappe')}")
			return {"data": None}
		if b["loai"] == "ghi_cong" and re.match(r"tờ HĐ cũ H3", b.get("frappe") or ""):
			return self._lap_hd_cu_h3(b, sd)
		if b["loai"] == "ghi_cong":
			yc = {"bang": b["bang"], "hanh_dong": b["hanh_dong"], "gia_tri": self._thay(b["gia_tri"], sd, b), "select": "id"}
			if b.get("loc"):
				yc["loc"] = [{"op": "eq", "cot": k, "gt": self._thay(x, sd, b)} for k, x in b["loc"].items()]
			ket = self._cong(self._email(sd, b["nguoi"]), yc, gio)
			if b.get("nhan") and "error" not in ket and ket.get("data"):
				sd.gan(b["nhan"], ket["data"][0]["id"])
			return ket
		ts = self._thay(b["tham_so"], sd, b)
		ket = self._goi(self._email(sd, b["nguoi"]), b["rpc"], ts, gio)
		if "error" in ket:
			return ket
		data = ket.get("data")
		ten = None
		if b["rpc"] == "create_order_with_lines":
			ten = data[0]["order_id"]
		elif b["rpc"] in ("post_invoice", "reissue_invoice"):
			ten = data[0]["invoice_id"]
		elif b["rpc"] == "create_return_with_lines":
			ten = data if isinstance(data, str) else (data[0].get("return_id") if isinstance(data, list) else data.get("return_id"))
		elif b["rpc"] == "post_stock_issue":
			ten = ts.get("p_entry_id")
		if b.get("nhan") and _RE_NHAN.match(b["nhan"]) and ten:
			sd.gan(b["nhan"], ten)
		if b.get("nhan_phu") and b["rpc"] == "create_order_with_lines":
			# phiếu trả tự sinh lập NGẦM cùng đơn (phần trả kèm đơn) — bên Frappe là NPP Phieu Tra của đơn ấy
			pt = frappe.get_all("NPP Phieu Tra", filters={"don_hang": ten}, pluck="name", order_by="creation asc, name asc", limit=1)
			sd.gan(b["nhan_phu"], pt[0] if pt else None)
		return ket

	def _lap_hd_cu_h3(self, b: dict, sd: SoDoi) -> dict:
		"""Tờ HĐ cũ H3 (bộ S10 #2 — VB-E10): Sales Invoice `is_opening = 'Yes'` giữ MÃ HĐ CŨ (`insert(set_name=…)` — BP §5.6 / PoC 10), một dòng không mã
		hàng như tờ nợ đầu kỳ (Opening Invoice Creation Tool), đối ứng TK tạm đầu kỳ, ngày tờ = hạn = `due_date` của bước. Công cụ nhập `NPP LS *` của P8
		chưa có (`can_frappe` của VB-E10: lập TAY trong bài). nppsale không có tờ này — bước vàng ghi một dòng nợ đầu kỳ không HĐ cùng số tiền; bản Frappe
		là nợ THEO HĐ (`loai = hoa_don`, BP §6.1 dòng `receivables`) nên ảnh chụp sổ gắn nhãn 'dk:<SĐT>:<tiền>' cho tờ để so cùng khoá."""
		from nppsale.rpc.no_dau_ky import _ghi_so
		from nppsale.su_kien import cong_no as CN
		from nppsale.thiet_lap.ban_hang import cai_dat_ban

		DongHo.dat(b.get("gio_frappe") or b.get("gio"))
		gt = self._thay(b["gia_tri"], sd, b)
		cd = cai_dat_ban()
		ngay = gt["due_date"]
		si = frappe.new_doc("Sales Invoice")
		si.update({"customer": gt["customer_id"], "company": cd.cong_ty, "is_opening": "Yes", "is_pos": 0, "set_posting_time": 1, "posting_date": ngay,
			"due_date": ngay, "update_stock": 0, "disable_rounded_total": 1, "allocate_advances_automatically": 0, "taxes_and_charges": "",
			"payment_terms_template": None, "npp_han_thanh_toan": ngay, "npp_ghi_chu": gt.get("note"),
			"items": [{"item_name": "Nợ HĐ cũ", "description": "Nợ HĐ cũ", "qty": 1, "rate": float(gt["amount"]), "conversion_factor": 1,
				"uom": frappe.db.get_single_value("Stock Settings", "stock_uom") or "Nos", "income_account": cd.tk_tam_dau_ky,
				"cost_center": frappe.get_cached_value("Company", cd.cong_ty, "cost_center")}]})
		si.set("taxes", [])
		si.flags.ignore_permissions = True
		si.insert(set_name=MA_HD_CU_H3)
		_ghi_so(si.name)
		CN.chieu_hoa_don(si.name)
		sd.gan(f"dk:{sd.sdt[gt['customer_id']]}:{so(gt['amount'])}", si.name)
		return {"data": [{"id": si.name}]}

	def _phat_lai(self, ten_bo: str, sd: SoDoi) -> list[str]:
		"""Các bước của `bo.<ten_bo>` — so thành / bại (và mã + câu lỗi của bước chờ lỗi) với tệp vàng."""
		sai = []
		for i, b in enumerate(self.vang["bo"][ten_bo]["buoc"]):
			nhan = f"{ten_bo} bước {i} ({b.get('rpc') or b.get('bang') or b['loai']} — {b['nguoi']})"
			try:
				ket = self._buoc(b, sd)
			except Exception as e:  # noqa: BLE001 — báo đúng bước rồi dừng bộ
				return [*sai, f"{nhan}: {type(e).__name__}: {str(e)[:600]}"]
			m = b["kq"]
			if m["ok"] and "error" in ket:
				return [*sai, f"{nhan}: nppsale ghi được — bản Frappe báo {ket['error'].get('code')} {str(ket['error'].get('message'))[:400]}"]
			if not m["ok"]:
				if "error" not in ket:
					return [*sai, f"{nhan}: nppsale báo {m['ma_loi']} {m['loi'][:200]} — bản Frappe lại ghi được"]
				if (ket["error"]["code"], ket["error"]["message"]) != (m["ma_loi"], m["loi"]):
					sai.append(f"{nhan}: lỗi {ket['error']['code']} {ket['error']['message'][:300]} ≠ nppsale {m['ma_loi']} {m['loi'][:300]}")
		return sai

	# ------------------------------------------------------------------------------------------------ bộ nền
	def _dung_s1(self) -> list[str]:
		"""Sổ BC: danh mục `nen.S` + lô hạt giống (post_stock_import lúc `gio_hat_giong`, ngày nhận = `nhan_luc` — Batch.creation = lo[].created_at của
		tệp vàng) + 41 bước `bo.S1.buoc`."""
		nen = self.vang["nen"]["S"]
		DongHo.dat(nen["gio_hat_giong"])
		sd = SoDoi(dung_nen_bc("S", nen, 0))
		self.bo["S1"] = sd
		chu = self._email(sd, "CHU")
		for ma_lo, lo in nen["lo"].items():
			ket = self._goi(chu, "post_stock_import", {"p": {"entry_code": f"NK-HAT-{ma_lo}", "warehouse_zone": lo["kho"], "posted_at": lo["nhan_luc"],
				"lines": [{"product_id": sd.ma["sp:" + lo["sku"]], "batch_code": ma_lo, "expires_at": lo["han"], "base_qty": lo["sl"],
					"base_cost": lo["gia_von"], "unit_name": nen["hang"][lo["sku"]]["dv_co_so"]}]}}, lo["tao_luc"])
			if "error" in ket:
				return [f"S lô hạt giống {ma_lo}: {ket['error']}"]
		return self._phat_lai("S1", sd)

	def _dung_e2e(self) -> list[str]:
		"""Bộ e2e một lượt (29/09/2026 — bo.E2E.frappe): sổ giả e2e của nppsale CHÈN THẲNG; ở đây đi đúng RPC dưới Chủ (lập hộ NV A / NV B):
		- lô ML1 (giá 15.000 / hộp) nhập 28/09 08:00;
		- HD-ML-A: 2 thùng × 470.000, giảm giá đơn 20.000, kèm dòng ĐỔI 3 hộp 0 đ gửi thẳng trong tải trọng post_invoice — sổ giả có dòng đổi trên HĐ
		  mà không có phiếu trả (đi qua phiếu tự sinh thì `tra` có thêm phiếu 0 đ mà sổ giả không có); HD-ML-B 10 hộp × 21.000; HD-ML-HUY 5 hộp rồi
		  Huỷ HĐ — lập theo thứ tự để mã HĐ giữ A < B theo mã điểm (nhanVienPhieuTra đoán NV phiếu trả cũ theo HĐ GẶP TRƯỚC);
		- TR-ML-1: phiếu tự lập Chủ lập 13:00, 2 hộp × 21.000, Hoàn thành (tờ ghi có có kho — giá vốn nhập lại = giá lô 15.000) rồi GHI THẲNG bỏ người
		  đứng tên: phiếu "không NV, không HĐ" chỉ có ở dữ liệu chuyển (phiếu tự lập Frappe luôn có người).
		Phần VB-E04 (HD-E2E-1, TR-E2E-1, khoản thu Cô Ba) chưa dựng — xem CHUA_DUNG_KB."""
		nen = self.vang["nen"]["E2E"]
		DongHo.dat("2026-09-28T08:00:00+07:00")
		sd = SoDoi(dung_nen_bc("E2E", nen, 50))
		self.bo["E2E"] = sd
		chu, nv_a, nv_b = self._email(sd, "CHU"), self._email(sd, "NV_A"), self._email(sd, "NV_B")
		sp, kh = sd.ma["sp:ML1"], sd.ma["kh:0912000001"]
		thung, hop = sd.dv_frappe("ML1", "thùng"), sd.dv_frappe("ML1", "hộp")
		sai = []

		def goi(ten, ts, gio):
			ket = self._goi(chu, ten, ts, gio)
			if "error" in ket:
				sai.append(f"E2E {ten} lúc {gio}: {ket['error']}")
				raise AssertionError
			return ket["data"]

		def dong(sl, dv, hs, gia):
			return {"product_id": sp, "unit_name": dv, "conversion_factor": hs, "quantity": sl, "unit_price": gia, "line_total": sl * gia, "vat_rate": "0"}

		def don(n, nv, dong_, giam, gio):
			# giảm giá cả đơn ghi ở đơn như sổ giả (đơn DH-ML-A total 920.000 — tiền đơn sau giảm) rồi gửi lại lúc Xuất hàng
			t = sum(x["line_total"] for x in dong_) - giam
			return goi("create_order_with_lines", {"p": {"client_request_id": f"33333333-3333-3333-3333-{n:012d}", "order": {"customer_id": kh,
				"payment_terms": "COD", "subtotal": t, "vat": 0, "total": t, "status": "submitted", "approval_reason": "", "sales_user_id": nv},
				"lines": dong_, "returns": None, "return_lines": []}}, gio)[0]["order_id"]

		try:
			goi("post_stock_import", {"p": {"entry_code": "NK-ML-1", "warehouse_zone": "sale", "posted_at": "2026-09-28T08:00:00+07:00",
				"lines": [{"product_id": sp, "batch_code": "ML-LO1", "expires_at": "2028-12-31", "base_qty": 100, "base_cost": 15000, "unit_name": hop}]}},
				"2026-09-28T08:00:00+07:00")
			for nhan, nv, dong_, giam, them in (
					("ML-A", nv_a, [dong(2, thung, 24, 470000)], 20000, [{"product_id": sp, "unit_name": hop, "conversion_factor": 1, "quantity": 3,
						"unit_price": 0, "line_discount": 0, "vat_rate": "0", "is_exchange": True}]),
					("ML-B", nv_b, [dong(10, hop, 1, 21000)], 0, []),
					("ML-HUY", nv_a, [dong(5, hop, 1, 20000)], 0, [])):
				n = len(sd.nhan) // 2 + 1
				ten_don = don(n, nv, dong_, giam, f"2026-09-29T10:00:0{n}+07:00")
				sd.gan("DH-" + nhan, ten_don)
				dx = self._dong_xuat(sd, ten_don, {"nguoi": "CHU", "gio": f"2026-09-29T10:00:0{n}+07:00"})
				hd = goi("post_invoice", {"p": {"order_id": ten_don, "invoice_date": "2026-09-29", "discount": str(giam), "lines": dx + them}},
					f"2026-09-29T10:00:0{n}+07:00")[0]["invoice_id"]
				sd.gan("HD-" + nhan, hd)
			goi("cancel_invoice", {"p_invoice_id": sd.nhan["HD-ML-HUY"], "p_reason": "e2e huy"}, "2026-09-29T10:00:30+07:00")
			pt = goi("create_return_with_lines", {"p_head": {"customer_id": kh, "reason": "damaged", "status": "draft"}, "p_lines": [{"product_id": sp,
				"unit_name": hop, "quantity": 2, "unit_price": 21000, "vat_rate": 0, "line_total": 42000, "is_exchange": False}]}, "2026-09-29T13:00:00+07:00")
			sd.gan("TR-ML-1", pt)
			goi("complete_return", {"p_return_id": pt, "p_zone": "sale"}, "2026-09-29T13:00:01+07:00")
		except AssertionError:
			return sai
		frappe.db.set_value("NPP Phieu Tra", pt, "nhan_vien", None, update_modified=False)  # phiếu "không NV" của dữ liệu chuyển
		return sai

	# ------------------------------------------------------------------------------------------------ ảnh chụp sổ (so với bo.<bộ>.anh_chup)
	def _doc_cong(self, bang: str, select: str, loc: list | None = None, nc: NguCanh = ADMIN, thu_tu: list | None = None) -> list[dict]:
		yc = {"bang": bang, "select": select, "loc": loc or []}
		if thu_tu:
			yc["thu_tu"] = thu_tu
		return doc_cong(yc, nc)["data"] or []

	def _anh_chup(self, sd: SoDoi) -> dict:
		"""Sổ của bộ theo khoá nghiệp vụ — cùng dạng `anh_chup` của tệp vàng (đọc qua cổng: một luật với giao diện)."""
		kh = list(sd.sdt)
		hd = [{"id": sd.nhan_cua(r["id"]), "nv": r["sales_user_id"], "don": sd.nhan_cua(r["order_id"]), "vat": so(r["vat"]), "ngay": r["invoice_date"],
			"khach": sd.sdt[r["customer_id"]], "total": so(r["total"]), "status": r["status"], "subtotal": so(r["subtotal"])}
			for r in self._doc_cong("sales_invoices", "id, sales_user_id, order_id, vat, invoice_date, customer_id, total, status, subtotal",
				[{"op": "in", "cot": "customer_id", "gt": kh}])]
		don = [{"id": sd.nhan_cua(r["id"]), "nv": r["sales_user_id"], "khach": sd.sdt[r["customer_id"]], "total": so(r["total"]), "status": r["status"]}
			for r in self._doc_cong("sales_orders", "id, sales_user_id, customer_id, total, status", [{"op": "in", "cot": "customer_id", "gt": kh}])]
		no = self._doc_cong("receivables", "id, sales_user_id, due_date, paid, customer_id, amount, status, invoice_id, return_id",
			[{"op": "in", "cot": "customer_id", "gt": kh}])
		khoa_no = {r["id"]: sd.nhan_cua(r["invoice_id"] or r["return_id"]) if (r["invoice_id"] or r["return_id"])
			else f"dk:{sd.sdt[r['customer_id']]}:{so(r['amount'])}" for r in no}  # nợ đầu kỳ (không HĐ / phiếu) — khoá vàng 'no:dk:<SĐT>:<tiền>'

		cong_no = [{"id": "no:" + khoa_no[r["id"]], "nv": r["sales_user_id"], "han": r["due_date"], "paid": so(r["paid"]), "khach": sd.sdt[r["customer_id"]],
			"amount": so(r["amount"]), "status": r["status"]} for r in no]
		thu = [{"id": f"thu:{khoa_no[r['receivable_id']]}:{so(r['amount'])}", "luc": luc(r["collected_at"]), "amount": so(r["amount"]),
			"method": r["method"]} for r in self._doc_cong("payments", "id, receivable_id, amount, method, collected_at",
				[{"op": "in", "cot": "receivable_id", "gt": list(khoa_no)}])] if khoa_no else []
		pt = [{"hd": sd.nhan_cua(r["invoice_id"]), "id": sd.nhan_cua(r["id"]), "nv": r["sales_user_id"], "tien": so(r["credit_note_amount"]),
			"khach": sd.sdt[r["customer_id"]], "status": r["status"], "tu_sinh": r["credit_with_invoice"], "ngay_phieu": r["return_date"],
			"credited_at": luc(r["credited_at"]), "revenue_date": r["revenue_date"]} for r in self._doc_cong("returns", "id, invoice_id, sales_user_id, "
				"credit_note_amount, customer_id, status, credit_with_invoice, return_date, credited_at, revenue_date",
				[{"op": "in", "cot": "customer_id", "gt": kh}])]
		lo = [{"id": r["id"], "gia": so(r["unit_cost"]), "ton": so(r["qty_on_hand"])} for r in self._doc_cong("batches", "id, unit_cost, qty_on_hand",
			[{"op": "in", "cot": "product_id", "gt": list(sd.sku)}]) if not r["id"].startswith("~")]
		return {"hd": _sap(hd), "don": _sap(don), "thu": _sap(thu), "cong_no": _sap(cong_no), "phieu_tra": _sap(pt), "lo": _sap(lo)}

	def _so_anh_chup(self, ten_bo: str, sd: SoDoi) -> list[str]:
		"""So sổ đã dựng với `bo.<bộ>.anh_chup` — không so `phieu_kho` (phiếu kho của HĐ / nhập lại trên Frappe là CHÍNH chứng từ; nppsale có thêm
		phiếu "Đảo phiếu trả" / "Hoàn kho do huỷ" — Frappe huỷ chứng từ: docstatus 2; số phiếu kho được kiểm qua gv / gv_tra / lo của báo cáo)."""
		mong = copy.deepcopy(self.vang["bo"][ten_bo]["anh_chup"])
		co = self._anh_chup(sd)
		muc = ("hd", "don", "thu", "cong_no", "phieu_tra", "lo")
		if ten_bo == "E2E":
			# chỉ phần một lượt 29/09 (VB-E01 / E02 / E05 / E14 / E15): phần VB-E04 chưa dựng (CHUA_DUNG_KB); lô của sổ giả e2e không có (anh_chup.lo = [])
			muc = ("hd", "don", "phieu_tra")
			bo_e04 = ("HD-E2E-1", "DH-E2E-1", "TR-E2E-1")
			for k in muc:
				mong[k] = [x for x in mong[k] if x["id"] not in bo_e04]
			for x in mong["phieu_tra"]:
				if x["id"] == "TR-ML-1":
					# sổ giả chèn thẳng ngày phiếu 30/09 + chưa có mốc ghi có mà ngày trừ doanh số 29/09 (trạng thái hàm nppsale không lập được); bản
					# Frappe Hoàn thành lúc 13:00:01 ngày 29/09 → ngày phiếu = mốc ghi có = 29/09 (ngày trừ doanh số như sổ giả)
					x.update({"ngay_phieu": "2026-09-29", "credited_at": "2026-09-29T13:00:01+07:00"})
		sai = []
		for k in muc:
			m = _sap(mong.get(k) or [])
			if co[k] != m:
				sai.append(f"{ten_bo}: ảnh chụp sổ `{k}` lệch — {'; '.join(_cho_lech(co[k], m, k))[:3000]}")
		return sai

	# ------------------------------------------------------------------------------------------------ chuẩn hoá kết quả báo cáo
	def _loc_so_ban(self, kq: dict, sd: SoDoi) -> dict:
		"""Chỉ phần của bộ (site dùng chung — có chứng từ của dữ liệu thử khác trong cùng kỳ): HĐ / phiếu trả của khách bộ + dòng của chúng, giá vốn
		của mặt hàng bộ / phiếu bộ. Giữ id Frappe (đầu vào mã TS)."""
		kh = set(sd.sdt)
		hd = [r for r in kq["hd"] if r["customer_id"] in kh]
		ids_hd = {r["id"] for r in hd}
		tra = [r for r in kq["tra"] if r["customer_id"] in kh]
		ids_tra = {r["id"] for r in tra}
		return {**kq, "hd": hd, "dong_hd": [r for r in kq["dong_hd"] if r["invoice_id"] in ids_hd], "tra": tra,
			"dong_tra": [r for r in kq["dong_tra"] if r["return_id"] in ids_tra], "gv": [r for r in kq["gv"] if r["product_id"] in sd.sku],
			"gv_tra": [r for r in kq["gv_tra"] if r["return_id"] in ids_tra]}

	@staticmethod
	def _dong_don(sd: SoDoi) -> dict:
		"""Dòng đơn (Sales Order Item) của bộ → '<đơn>/<SKU>/<ĐV>'."""
		don = [v for k, v in sd.nhan.items() if k.startswith("DH-")]
		if not don:
			return {}
		return {r.name: f"{sd.nhan_cua(r.parent)}/{sd.sku.get(r.item_code, r.item_code)}/{sd.dv(sd.sku.get(r.item_code), r.uom)}"
			for r in frappe.get_all("Sales Order Item", filters={"parent": ("in", don)}, fields=["name", "parent", "item_code", "uom"])}

	@staticmethod
	def _xep(ds: list, *cot) -> list:
		"""Như XEP của bộ sinh: mảng không thứ tự (L12) xếp theo khoá để so như tập."""
		return sorted(ds, key=lambda x: tuple("" if x.get(c) is None else str(x.get(c)) for c in cot))

	def _chuan_so_ban(self, kq: dict, sd: SoDoi) -> dict:
		n, sku = sd.nhan_cua, (lambda x: sd.sku.get(x, "?" + str(x)) if x else x)
		dd = self._dong_don(sd)
		hd = [{**r, "id": n(r["id"]), "invoice_code": n(r["invoice_code"]), "order_id": n(r["order_id"]), "customer_id": sd.sdt.get(r["customer_id"]),
			**{k: so(r[k]) for k in ("total", "subtotal", "vat")}} for r in kq["hd"]]
		dong_hd = [{**r, "id": f"{n(r['invoice_id'])}/{sku(r['product_id'])}/{sd.dv(sku(r['product_id']), r['unit_name'])}"
			+ ("/doi" if r["is_exchange"] else ""), "invoice_id": n(r["invoice_id"]), "product_id": sku(r["product_id"]),
			"unit_name": sd.dv(sku(r["product_id"]), r["unit_name"]), "order_line_id": dd.get(r["order_line_id"], "?" + str(r["order_line_id"]))
			if r["order_line_id"] else None, **{k: so(r[k]) for k in ("conversion_factor", "quantity", "unit_price", "line_total", "line_discount")}}
			for r in kq["dong_hd"]]
		tra = [{**r, "id": n(r["id"]), "ma": n(r["ma"]), "customer_id": sd.sdt.get(r["customer_id"]), "invoice_id": n(r["invoice_id"]),
			"created_at": luc(r["created_at"]), "credit_note_amount": so(r["credit_note_amount"])} for r in kq["tra"]]
		dong_tra = [{**r, "return_id": n(r["return_id"]), "product_id": sku(r["product_id"]), "unit_name": sd.dv(sku(r["product_id"]), r["unit_name"]),
			**{k: so(r[k]) for k in ("quantity", "line_total", "unit_price")}} for r in kq["dong_tra"]]
		gv = [{"product_id": sku(r["product_id"]), "sl": so(r["sl"]), "tien": so(r["tien"])} for r in kq["gv"]]
		gv_tra = [{"return_id": n(r["return_id"]), "product_id": sku(r["product_id"]), "tien": so(r["tien"])} for r in kq["gv_tra"]]
		return {"hd": self._xep(hd, "id"), "dong_hd": self._xep(dong_hd, "invoice_id", "product_id", "unit_name", "is_exchange", "quantity"),
			"tra": self._xep(tra, "id"), "dong_tra": self._xep(dong_tra, "return_id", "product_id", "unit_name", "quantity"),
			"gv": self._xep(gv, "product_id"), "gv_tra": self._xep(gv_tra, "return_id", "product_id")}

	def _chuan_ton_kho(self, kq: dict, sd: SoDoi) -> dict:
		n, sku = sd.nhan_cua, (lambda x: sd.sku.get(x, "?" + str(x)))
		lo = [{**r, "product_id": sku(r["product_id"]), "qty_on_hand": so(r["qty_on_hand"]), "unit_cost": so(r["unit_cost"]),
			"created_at": luc(r["created_at"])} for r in kq["lo"] if r["product_id"] in sd.sku and not r["id"].startswith("~")]
		ids_hd = set(sd.ten)
		dong = [{**r, "invoice_id": n(r["invoice_id"]), "product_id": sku(r["product_id"]), "unit_name": sd.dv(sku(r["product_id"]), r["unit_name"]),
			"quantity": so(r["quantity"]), "conversion_factor": so(r["conversion_factor"])} for r in kq["dong"] if r["invoice_id"] in ids_hd]
		return {"lo": self._xep(lo, "id"), "dong": self._xep(dong, "ngay", "invoice_id", "product_id", "unit_name", "is_exchange")}

	def _chuan_ts(self, r: dict, sd: SoDoi) -> dict:
		"""Kết quả mã TS (id Frappe) → cùng dạng `ts_gon` của bộ sinh (id → khoá nghiệp vụ, đơn vị → tên vàng, số int / float)."""
		n = sd.nhan_cua

		def sku(x):
			return sd.sku.get(x, x) if x else x

		def chu_sl(sp, s):
			"""'2 Thung 10 Hop' (tên UOM của site) → '2 thùng 10 hộp' (tên vàng của mặt hàng)."""
			return " ".join(sd.dv(sp, w) if not re.fullmatch(r"[\d.,]+", w) else w for w in (s or "").split(" "))

		def so_de_quy(v):
			if isinstance(v, dict):
				return {k: so_de_quy(x) for k, x in v.items()}
			if isinstance(v, list):
				return [so_de_quy(x) for x in v]
			return so(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v

		dong = sorted(({**d, "ct": n(d["ct"]), "sp": sku(d["sp"]), "kh": sd.sdt.get(d["kh"], d["kh"])} for d in r["dong"]),
			key=lambda d: (-d["loai"], d["ct"] or "", d["sp"] or "", d["sl"]))
		hb = []
		for h in sorted(r["hang_ban_nv"], key=lambda h: h["id"] or ""):
			hb.append({k: h[k] for k in ("id", "qty", "sl_hien", "don_vi", "listed", "revenue", "diff", "docDiscount", "thueLamTron", "returnQty",
				"sl_tra_hien", "returnValue", "returnListed", "diffReturn", "netRevenue", "diffNet", "tongChenh")}
				| {"products": [{"sku": sku(p["sku"]), "qty": p["qty"], "listed": p["listed"], "revenue": p["revenue"], "diff": p["diff"],
					"returnQty": p["returnQty"], "returnValue": p["returnValue"], "diffReturn": p["diffReturn"],
					"donVi": [{**{k: d[k] for k in ("heSo", "qty", "returnQty", "giaBang", "giaBan", "listed", "revenue", "diff", "returnValue",
						"diffReturn")}, "unit": sd.dv(sku(p["sku"]), d["unit"])} for d in p["donVi"]]} for p in h["products"]]})
		return so_de_quy({"tong": r["tong"], "theo_nv": dict(sorted(r["theo_nv"].items())), "gia_von_xuat": r["gia_von_xuat"],
			"nv_reports_sales": sorted(({k: h[k] for k in ("id", "orders", "revenue", "cogs", "profit")} for h in r["nv_reports_sales"]),
				key=lambda h: h["id"] or ""),
			"gia_von_co_so": dict(sorted((sku(k), v) for k, v in r["gia_von_co_so"].items())),
			"gia_von_tra": dict(sorted((n(k), {"total": v["total"], "byProduct": {sku(a): b for a, b in v["byProduct"].items()}})
				for k, v in r["gia_von_tra"].items())),
			"thu_tu_hd": [n(x) for x in r["thu_tu_hd"]], "nv_phieu_tra": dict(sorted((n(k), v) for k, v in r["nv_phieu_tra"].items())), "dong": dong,
			"sl_mat_hang": dict(sorted((sku(k), {"sl": v["sl"], "chu": chu_sl(sku(k), v["chu"])}) for k, v in r["sl_mat_hang"].items())),
			"hang_ban_nv": hb})

	def _san_pham_ts(self, sd: SoDoi, doi_gia: dict | None) -> list[dict]:
		"""Danh mục mặt hàng cho mã TS — đọc qua cổng `products` như màn (đơn vị, bảng giá, giá bán); `doi_gia` (VB-E14) thay bảng giá chung theo SKU
		(tên đơn vị vàng → tên UOM của site)."""
		sp = self._doc_cong("products", "id, sku, name, brand, primary_supplier_id, base_unit, sell_price, units:product_units(unit_name, conversion), "
			"price_lists(unit_name, price, group_id)", [{"op": "in", "cot": "id", "gt": list(sd.sku)}],
			nc=NguCanh(user=sd.ma["k:CHU"], vai="owner"))
		for p in sp:
			if doi_gia and sd.sku[p["id"]] in doi_gia:
				p["price_lists"] = [{**g, "unit_name": sd.dv_frappe(sd.sku[p["id"]], g["unit_name"])} for g in doi_gia[sd.sku[p["id"]]]]
		return sp

	# ------------------------------------------------------------------------------------------------ một lời gọi của kịch bản
	def _svs(self) -> tuple[float, int]:
		"""Mốc `stock_value_summary` (Administrator — mọi lô của site) TRƯỚC khi dựng Sổ BC: site dùng chung có lô của dữ liệu thử khác → lời gọi
		`stock_value_summary` so PHẦN TĂNG do Sổ BC (tệp vàng: sổ chỉ có ba lô của Sổ BC)."""
		from nppsale.cong.bang.kho import NGUON_LO_CON_TON

		gt, n = frappe.db.sql(f"""SELECT COALESCE(SUM(x.`ton` * COALESCE(x.`gia_von`, 0)), 0), COUNT(*) FROM {NGUON_LO_CON_TON} x
			WHERE COALESCE(x.`ton`, 0) > 0""")[0]  # = thân stock_value_summary (rpc/kho.py) — hàm trả 0 cho người không phải NV (Administrator)
		return float(gt or 0), int(n)

	def _goi_kb(self, t: dict, i: int, c: dict, sd: SoDoi, tho: dict) -> tuple[object, str | None]:
		"""Chạy lời gọi thứ i → (kết quả đã chuẩn hoá cùng dạng `mong.kq` | {"_loi": (mã, câu)}, ghi chú bỏ qua)."""
		ham, nguoi = c["ham"], c.get("nguoi")
		gio = c.get("gio") or self.vang["nen"][sd.ma["nen"]]["gio_doc"]
		if ham == "ts:ban_hang":
			ly_do = ly_do_khong_ts()
			if ly_do:
				return None, f"mã TS — {ly_do}"
			if c["tu"] not in tho:
				return None, f"mã TS — lời gọi nguồn #{c['tu']} không chạy"
			ra = chay_ts([{"ma": f"{t['ma']}#{i}", "so_ban": tho[c["tu"]], "san_pham": self._san_pham_ts(sd, c.get("doi_gia"))}])[0]
			return self._chuan_ts(ra, sd), None
		if ham.startswith("bang:"):
			return self._bang(ham[5:], c, sd, gio), None
		ket = self._goi(sd.ma["k:" + nguoi], ham, self._thay(c.get("tham_so") or {}, sd), gio)
		if "error" in ket:
			return {"_loi": (ket["error"]["code"], ket["error"]["message"])}, None
		kq = ket["data"]
		if ham == "bao_cao_so_ban":
			tho[i] = self._loc_so_ban(kq, sd)
			ra = self._chuan_so_ban(tho[i], sd)
			ra["_khoa"] = sorted(kq)
			ra["tinh_lai_gia_von"] = kq.get("tinh_lai_gia_von")
			ra["_thu_tu_id"] = [r["id"] for r in kq["dong_hd"]] == sorted(r["id"] for r in kq["dong_hd"])
			ts = c.get("tham_so") or {}
			if all(isinstance(ts.get(k), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", ts[k]) for k in ("p_tu", "p_den")):
				DongHo.dat(gio)
				ra["_hai_duong"] = self._chuan_so_ban(self._loc_so_ban(self._tung_bang(sd.ma["k:" + nguoi], ts["p_tu"], ts["p_den"]), sd), sd)
			return ra, None
		if ham == "bao_cao_ton_kho":
			return self._chuan_ton_kho(kq, sd), None
		if ham == "stock_value_summary":
			r = kq[0]
			gt = None if r["inventory_value"] is None else so(float(r["inventory_value"]) - self.svs_nen[0])
			return [{"batch_count": int(r["batch_count"]) - self.svs_nen[1], "inventory_value": gt}], None
		if ham in ("dashboard_top_customers", "receivables_by_customer"):
			return [{**r, "customer_id": sd.sdt.get(r["customer_id"], "?" + str(r["customer_id"]))} for r in kq], None
		if ham == "hang_khach_da_lay":
			return self._chuan_hang_da_lay(kq, sd), None
		return kq, None

	@staticmethod
	def _chuan_hang_da_lay(kq: dict, sd: SoDoi) -> dict:
		"""`hang_khach_da_lay` (id Frappe) → khoá vàng, GIỮ thứ tự của hàm (list có thứ tự — Q8): khách = SĐT, hàng = SKU, NCC = tên, NV = email; đơn vị cơ
		sở → tên vàng của mặt hàng (khoá collation)."""
		def kh(x):
			return sd.sdt.get(x, "?" + str(x))

		def sku(x):
			return sd.sku.get(x, "?" + str(x)) if x else x

		def ncc(x):
			return sd.ncc.get(x, "?" + str(x)) if x else x

		return {"nv": kq["nv"], "khach": [{**r, "id": kh(r["id"])} for r in kq["khach"]],
			"hang": [{**r, "k": kh(r["k"]), "p": sku(r["p"])} for r in kq["hang"]],
			"sp": [{**r, "id": sku(r["id"]), "ncc": ncc(r["ncc"]), "base_unit": sd.dv(sku(r["id"]), r["base_unit"])} for r in kq["sp"]],
			"ncc": [{**r, "id": ncc(r["id"])} for r in kq["ncc"]]}

	def _tung_bang(self, email: str, tu: str, den: str) -> dict:
		"""VB-E02 (phần máy chủ) — "hai đường đọc phải ra Y HỆT": cùng sáu khối dựng từ các BẢNG CỔNG dưới cùng người như đường lùi `docTungBang` của
		giao diện (CLAUDE.md đợt 7): HĐ ghi sổ theo ngày HĐ + mọi dòng; phiếu trả theo ngày trừ doanh số + dòng không đổi; giá vốn xuất = dòng phiếu kho
		`export` đã ghi sổ trong cửa sổ [tu 00:00, den+1 00:00) giờ VN (`fetchCogsForRange`: SL cơ sở × giá vốn); giá vốn hàng trả = dòng phiếu nhập có
		ghi chú NGUYÊN VĂN 'Nhập lại từ phiếu trả <id>' (`fetchReturnCosts`). Một luật với bao_cao_so_ban ⇒ cùng số. Phần giao diện (CHÍNH mã nạp
		`napSoBan` một lượt ↔ đường lùi khi hàm trả PGRST202, qua cổng thật): portal/tests/dau-cuoi-bao-cao.test.ts."""
		vai = frappe.db.get_value("NPP Nhan Vien", email, "vai")
		nc = NguCanh(user=email, vai=vai)
		hd = self._doc_cong("sales_invoices", ", ".join(k for k, _ in __import__("nppsale.rpc.bao_cao", fromlist=["COT_HD"]).COT_HD),
			[{"op": "eq", "cot": "status", "gt": "posted"}, {"op": "gte", "cot": "invoice_date", "gt": tu}, {"op": "lte", "cot": "invoice_date", "gt": den}],
			nc)
		ids_hd = [r["id"] for r in hd] or ["-"]
		dong_hd = self._doc_cong("sales_invoice_lines", "id, invoice_id, product_id, unit_name, conversion_factor, quantity, unit_price, line_total, "
			"is_exchange, line_discount, order_line_id", [{"op": "in", "cot": "invoice_id", "gt": ids_hd}], nc, [{"cot": "id", "tang": True}])
		tra = self._doc_cong("returns", "id, status, customer_id, invoice_id, credit_note_amount, created_at, revenue_date, sales_user_id, reason, "
			"credit_with_invoice, ma:return_code", [{"op": "gte", "cot": "revenue_date", "gt": tu}, {"op": "lte", "cot": "revenue_date", "gt": den}], nc)
		ids_tra = [r["id"] for r in tra] or ["-"]
		dong_tra = self._doc_cong("return_lines", "return_id, product_id, unit_name, quantity, line_total, unit_price",
			[{"op": "in", "cot": "return_id", "gt": ids_tra}, {"op": "eq", "cot": "is_exchange", "gt": False}], nc)
		sau = (_dt.date.fromisoformat(den) + _dt.timedelta(days=1)).isoformat()
		pk = self._doc_cong("stock_entries", "id", [{"op": "eq", "cot": "type", "gt": "export"}, {"op": "eq", "cot": "status", "gt": "posted"},
			{"op": "gte", "cot": "posted_at", "gt": f"{tu}T00:00:00+07:00"}, {"op": "lt", "cot": "posted_at", "gt": f"{sau}T00:00:00+07:00"}], nc)
		gv: dict = {}
		for l in self._doc_cong("stock_entry_lines", "entry_id, product_id, quantity, qty_in_base_uom, conversion_factor_snapshot, unit_cost",
				[{"op": "in", "cot": "entry_id", "gt": [r["id"] for r in pk] or ["-"]}], nc):
			sl = abs(float(l["qty_in_base_uom"])) if l["qty_in_base_uom"] is not None else abs(float(l["quantity"] or 0)) * (
				float(l["conversion_factor_snapshot"] or 0) or 1)
			g = gv.setdefault(l["product_id"], {"product_id": l["product_id"], "sl": 0.0, "tien": 0.0})
			g["sl"] += sl
			g["tien"] = None if l["unit_cost"] is None or g["tien"] is None else g["tien"] + sl * float(l["unit_cost"])
		ghi_chu = {f"Nhập lại từ phiếu trả {x}": x for x in ids_tra}
		pn = self._doc_cong("stock_entries", "id, notes", [{"op": "eq", "cot": "status", "gt": "posted"}, {"op": "in", "cot": "notes", "gt": list(ghi_chu)}],
			nc)
		cua = {r["id"]: ghi_chu[r["notes"]] for r in pn}
		gv_tra: dict = {}
		for l in self._doc_cong("stock_entry_lines", "entry_id, product_id, quantity, qty_in_base_uom, conversion_factor_snapshot, unit_cost",
				[{"op": "in", "cot": "entry_id", "gt": list(cua) or ["-"]}], nc):
			sl = abs(float(l["qty_in_base_uom"])) if l["qty_in_base_uom"] is not None else abs(float(l["quantity"] or 0))
			g = gv_tra.setdefault((cua[l["entry_id"]], l["product_id"]), {"return_id": cua[l["entry_id"]], "product_id": l["product_id"], "tien": 0.0})
			g["tien"] = None if l["unit_cost"] is None or g["tien"] is None else g["tien"] + sl * float(l["unit_cost"])
		return {"hd": hd, "dong_hd": dong_hd, "tra": tra, "dong_tra": dong_tra, "gv": list(gv.values()), "gv_tra": list(gv_tra.values())}

	def _bang(self, bang: str, c: dict, sd: SoDoi, gio: str) -> list[dict]:
		"""'bang:<tên>' = câu đọc cổng bảng dưới người của lời gọi (`tham_so.loc` = [(cột, toán tử, giá trị)]) — cột theo `mong` của tệp vàng, chỉ dòng
		của bộ, id → khoá nghiệp vụ; so như tập."""
		m = (c.get("mong_frappe") or c["mong"]).get("kq") or []
		cot = sorted({k for x in m for k in x}) or ["id"]
		loc = [{"op": o, "cot": k, "gt": self._thay(v, sd)} for k, o, v in (c.get("tham_so") or {}).get("loc") or []]
		kh = list(sd.sdt)
		chon = ["id", *cot]
		if bang == "receivables":
			chon += ["invoice_id", "return_id"]
		if bang == "payments":  # khoản thu của bộ = khoản thu trỏ dòng nợ của khách bộ
			cua_bo = [{"op": "in", "cot": "receivable_id", "gt": [r["id"] for r in self._doc_cong("receivables", "id",
				[{"op": "in", "cot": "customer_id", "gt": kh}])] or ["-"]}]
		else:
			chon.append("customer_id")
			cua_bo = [{"op": "in", "cot": "customer_id", "gt": kh}]
		DongHo.dat(gio)
		email = sd.ma["k:" + c["nguoi"]]
		ds = self._doc_cong(bang, ", ".join(dict.fromkeys(chon)), [*loc, *cua_bo],
			nc=NguCanh(user=email, vai=frappe.db.get_value("NPP Nhan Vien", email, "vai")))
		n = sd.nhan_cua
		ra = []
		for r in ds:
			x = {}
			for k in cot:
				v = r.get(k)
				if k == "id":
					v = ("no:" + n(r["invoice_id"] or r["return_id"])) if bang == "receivables" else n(v)
				elif k in ("invoice_id", "return_id", "order_id"):
					v = n(v)
				elif k == "customer_id":
					v = sd.sdt.get(v, v)
				elif k in ("credited_at", "collected_at", "created_at"):
					v = luc(v)
				elif isinstance(v, (int, float)) and not isinstance(v, bool):
					v = so(v)
				x[k] = v
			ra.append(x)
		return _sap(ra)

	@staticmethod
	def _mong_chon(c: dict, mong_kq):
		"""Phần `chon` của kỳ vọng (+ bộ khoá `_khoa`)."""
		if not isinstance(mong_kq, dict):
			return mong_kq
		chon = c.get("chon")
		return {k: v for k, v in mong_kq.items() if (chon is None or k in chon or k == "_khoa")}

	def _so_goi(self, t: dict, i: int, c: dict, ra, sd: SoDoi) -> list[str]:
		nhan = f"{t['ma']} #{i} {c['ham']}" + (f" ({c.get('nguoi')})" if c.get("nguoi") else "")
		mong = copy.deepcopy(c.get("mong_frappe") or c["mong"])
		for fn, _ly_do in [*LECH.get((t["ma"], i), ()), *LECH_BO.get((sd.ma["nen"], c["ham"]), ())]:
			fn(mong, sd)
		if not mong["ok"]:
			if not isinstance(ra, dict) or "_loi" not in ra:
				return [f"{nhan}: nppsale báo {mong['ma_loi']} {mong['loi']} — bản Frappe lại ra kết quả"]
			if ra["_loi"] != (mong["ma_loi"], mong["loi"]):
				return [f"{nhan}: lỗi {ra['_loi']} ≠ {(mong['ma_loi'], mong['loi'])}"]
			return []
		if isinstance(ra, dict) and "_loi" in ra:
			return [f"{nhan}: bản Frappe báo lỗi {ra['_loi']}"]
		m = self._mong_chon(c, mong["kq"])
		sai = []
		if c["ham"] == "bao_cao_so_ban":
			if "_khoa" in m and ra["_khoa"] != sorted([*m["_khoa"], "tinh_lai_gia_von"]):
				sai.append(f"{nhan}: bộ khoá {ra['_khoa']} ≠ {sorted([*m['_khoa'], 'tinh_lai_gia_von'])} (6 khoá nppsale + tinh_lai_gia_von — Q12)")
			if not isinstance(ra["tinh_lai_gia_von"], int) or isinstance(ra["tinh_lai_gia_von"], bool) or ra["tinh_lai_gia_von"] < 0:
				sai.append(f"{nhan}: tinh_lai_gia_von {ra['tinh_lai_gia_von']!r} không phải số nguyên ≥ 0")
			if not ra["_thu_tu_id"]:
				sai.append(f"{nhan}: dong_hd không xếp theo id (đường lùi `.order('id')` — dòng cuối nhận phần dư)")
			if "_hai_duong" in ra:
				for k, v in ra["_hai_duong"].items():
					if not _gan_bang(ra[k], v, {"tien": 0.01}, k):
						sai.append(f"{nhan}: hai đường (một lượt ↔ từng bảng cổng) khác ở `{k}` — {'; '.join(_cho_lech(ra[k], v, k))[:2000]}")
			for k in m:
				if k != "_khoa" and not _gan_bang(ra[k], m[k]):
					sai.append(f"{nhan}: `{k}` lệch — {'; '.join(_cho_lech(ra[k], m[k], k))[:2500]}")
			return sai
		if c["ham"] == "ts:ban_hang":
			for k in m:
				if not _gan_bang(ra.get(k), m[k], {"tien": 1, "gia_von": 1, "giam_don": 1, "niem_yet": 1, "tien_tt": 1} if k == "dong" else None, k):
					sai.append(f"{nhan}: `{k}` lệch — {'; '.join(_cho_lech(ra.get(k), m[k], k))[:2500]}")
			return sai
		if isinstance(m, dict):
			for k in m:
				if not _gan_bang(ra.get(k), m[k]):
					sai.append(f"{nhan}: `{k}` lệch — {'; '.join(_cho_lech(ra.get(k), m[k], k))[:2500]}")
			return sai
		mm = _sap(m) if c["ham"].startswith("bang:") else m
		if not _gan_bang(ra, mm):
			sai.append(f"{nhan}: lệch — {'; '.join(_cho_lech(ra, mm))[:2500]}")
		return sai

	# ------------------------------------------------------------------------------------------------ một kịch bản
	def _bo_cua(self, ten_bo: str) -> tuple[SoDoi | None, list[str]]:
		"""Bộ nền của kịch bản: S1 / E2E đã dựng ở đầu bài; S2…S7 = S1 + bước riêng (chạy trong điểm lưu của kịch bản — lui sau) rồi so ảnh chụp."""
		if ten_bo in self.bo:
			return self.bo[ten_bo], self.da_dung.get(ten_bo) or []
		goc = self.vang["bo"][ten_bo].get("goc")
		if goc != "S1" or "S1" not in self.bo:
			return None, [f"bộ {ten_bo} (gốc {goc}) chưa dựng"]
		if self.da_dung.get("S1"):
			return None, [f"bộ {ten_bo}: Sổ BC dựng hỏng"]
		g = self.bo["S1"]
		sd = SoDoi(g.ma)
		sd.nhan, sd.ten = dict(g.nhan), dict(g.ten)
		sai = self._phat_lai(ten_bo, sd)
		return sd, sai + (self._so_anh_chup(ten_bo, sd) if not sai else [])

	def _chi_so_cua_bo(self, sd: SoDoi) -> None:
		"""Hàm tổng hợp TOÀN SỔ (`HAM_TOAN_SO` — không lọc theo khách được ở bài như `bao_cao_so_ban`, và top-N / tổng không trừ mốc được) đọc mọi chứng từ
		của site DÙNG CHUNG: 95 HĐ PoC ngày 05-06/11/2026, bộ E2E dựng cùng bài (nợ HD-ML-A / B)… — sổ nppsale của bộ vàng là DB MỚI chỉ có chứng từ của
		bộ. Trong điểm lưu của kịch bản (lui sau kịch bản), đẩy chứng từ của khách NGOÀI bộ ra khỏi tập các hàm ấy đọc: HĐ → `is_opening = 'Yes'` (không
		phải doanh thu — L1), phiếu trả → không ngày trừ doanh số (L2), dòng nợ → `paid` (L8). Hàm không bị sửa; dữ liệu của bộ giữ nguyên."""
		kh = {"kh": tuple(sd.sdt)}
		frappe.db.sql("""UPDATE `tabSales Invoice` SET `is_opening` = 'Yes' WHERE `customer` NOT IN %(kh)s AND `docstatus` = 1 AND `is_return` = 0
			AND IFNULL(`is_opening`, 'No') = 'No'""", kh)
		frappe.db.sql("""UPDATE `tabNPP Phieu Tra` SET `ngay_tru_doanh_so` = NULL WHERE `khach_hang` NOT IN %(kh)s
			AND `ngay_tru_doanh_so` IS NOT NULL""", kh)
		frappe.db.sql("UPDATE `tabNPP Cong No` SET `trang_thai` = 'paid' WHERE `khach_hang` NOT IN %(kh)s AND `trang_thai` <> 'paid'", kh)

	def _bo_con(self, ten_bo: str, ten_goc: str, sd_goc: SoDoi) -> tuple[SoDoi | None, list[str]]:
		"""Lời gọi chạy trên bộ `ten_bo` KHÁC bộ của kịch bản (VB-B06 #2 / #3 → S2 / S4): được khi bộ ấy dựng tiếp từ chính bộ của kịch bản (`goc` = bộ
		đang có trên sổ) — phát lại bước riêng trên bản sao bảng đổi rồi so ảnh chụp; người gọi bọc trong điểm lưu riêng và lui sau lời gọi."""
		if self.vang["bo"][ten_bo].get("goc") != ten_goc:
			return None, []
		sd = SoDoi(sd_goc.ma)
		sd.nhan, sd.ten = dict(sd_goc.nhan), dict(sd_goc.ten)
		sai = self._phat_lai(ten_bo, sd)
		return sd, sai + (self._so_anh_chup(ten_bo, sd) if not sai else [])

	def _mot(self, t: dict) -> tuple[list[str], list[str]]:
		"""→ (sai, bỏ qua)."""
		sd, sai = self._bo_cua(t["bo"])
		if sd is None or sai:
			return sai, []
		bo_qua, tho = [], {}
		for fn in TRUOC_GOI.get(t["ma"], ()):
			sai += fn(self, sd) or []
		if any(c["ham"] in HAM_TOAN_SO and NAC_HAM.get(c["ham"], DA_DUNG[0]) in DA_DUNG and not c.get("bo") for c in t["goi"]):
			self._chi_so_cua_bo(sd)
		for i, c in enumerate(t["goi"]):
			nac = NAC_HAM.get(c["ham"])
			if c.get("chi_nppsale"):
				bo_qua.append(f"{t['ma']} #{i} {c['ham']}: chỉ nppsale")
				continue
			if nac and nac not in DA_DUNG:
				bo_qua.append(f"{t['ma']} #{i} {c['ham']}: chưa dựng ({nac})")
				continue
			if c.get("bien_the"):
				bo_qua.append(f"{t['ma']} #{i} {c['ham']}: biến thể ({c.get('bien_the')}) chưa dựng")
				continue
			if (c.get("bo") or t["bo"]) != t["bo"]:
				frappe.db.savepoint("npp_goi_bo")
				try:
					sd2, sai2 = self._bo_con(c["bo"], t["bo"], sd)
					if sd2 is None:
						bo_qua.append(f"{t['ma']} #{i} {c['ham']}: bộ {c['bo']} không dựng tiếp từ bộ {t['bo']}")
						continue
					if sai2:
						sai += sai2
						continue
					if c["ham"] in HAM_TOAN_SO:
						self._chi_so_cua_bo(sd2)
					ra, ly_do = self._goi_kb(t, i, c, sd2, tho)
					if ly_do:
						bo_qua.append(f"{t['ma']} #{i} {c['ham']}: {ly_do}")
						continue
					sai += self._so_goi(t, i, c, ra, sd2)
					self.da_so.append(f"{t['ma']}#{i}")
				finally:
					frappe.db.rollback(save_point="npp_goi_bo")
					self._nguoi(None)
				continue
			ra, ly_do = self._goi_kb(t, i, c, sd, tho)
			if ly_do:
				bo_qua.append(f"{t['ma']} #{i} {c['ham']}: {ly_do}")
				continue
			sai += self._so_goi(t, i, c, ra, sd)
			self.da_so.append(f"{t['ma']}#{i}")
		return sai, bo_qua

	def test_kich_ban_vang(self):
		chi = os.environ.get("NPP_VANG_CHI")  # chạy một phần: NPP_VANG_CHI=VB-A0,VB-E01 (đầu mã)
		ds = [t for t in self.vang["tinh_huong"] if not chi or any(t["ma"].startswith(x) for x in chi.split(","))]
		sai, bo_qua, chua = [], [], []
		chay = []
		for t in ds:
			if t.get("cho"):
				chua.append(f"{t['ma']}: chờ {t['cho']}")
			elif t["ma"] in CHUA_DUNG_KB:
				chua.append(f"{t['ma']}: {CHUA_DUNG_KB[t['ma']]}")
			elif t["ma"] in NAC_KB and NAC_KB[t["ma"]] not in DA_DUNG:
				chua.append(f"{t['ma']}: chưa dựng ({NAC_KB[t['ma']]})")
			elif t["ma"] in KIEM_DAC_TA or not t.get("goi"):
				chay.append(t)
			elif NAC_BO.get(t["bo"]) and NAC_BO[t["bo"]] not in DA_DUNG:
				chua.append(f"{t['ma']}: bộ {t['bo']} chưa dựng ({NAC_BO[t['bo']]})")
			elif all(NAC_HAM.get(c["ham"]) and NAC_HAM[c["ham"]] not in DA_DUNG for c in t["goi"]):
				chua.append(f"{t['ma']}: chưa dựng ({sorted({NAC_HAM[c['ham']] for c in t['goi']})})")
			else:
				chay.append(t)
		can = {t["bo"] for t in chay if t.get("bo")}
		if "E2E" in can:
			self.da_dung["E2E"] = self._dung_e2e()
			if not self.da_dung["E2E"]:
				self.da_dung["E2E"] = self._so_anh_chup("E2E", self.bo["E2E"])
			sai += self.da_dung["E2E"]
		self.svs_nen = self._svs()
		if any(b.startswith("S") for b in can):
			self.da_dung["S1"] = self._dung_s1()
			if not self.da_dung["S1"]:
				self.da_dung["S1"] = self._so_anh_chup("S1", self.bo["S1"])
			sai += self.da_dung["S1"]
		for t in chay:
			if t["ma"] in KIEM_DAC_TA:
				sai += KIEM_DAC_TA[t["ma"]](self, t) or []
				continue
			if not t.get("goi"):
				chua.append(f"{t['ma']}: chỉ đặc tả, chưa có bài")
				continue
			frappe.db.savepoint("npp_th")
			frappe.local._npp_cai_dat_ban = None
			try:
				s, b = self._mot(t)
				sai += s
				bo_qua += b
			finally:
				frappe.db.rollback(save_point="npp_th")
				self._nguoi(None)
				DongHo.dat(None)
		print(f"\n[bao_cao_vang] chạy {len(chay)} kịch bản ({', '.join(t['ma'] for t in chay)}); đã so {len(self.da_so)} lời gọi; chưa dựng "
			f"{len(chua)}; lời gọi bỏ qua {len(bo_qua)}")
		for x in chua + bo_qua:
			print("  -", x)
		self.assertFalse(sai, "\n".join(sai))


# ------------------------------------------------------------------------------------------------ lệch do CÁCH DỰNG bộ (không phải luật báo cáo)
def _e2e_dong_don(mong: dict, sd: SoDoi):
	"""Sổ giả e2e chèn thẳng HĐ không có dòng đơn (`order_line_id` null); bản Frappe phát lại bằng create_order_with_lines + post_invoice nên dòng HĐ
	(trừ dòng đổi gửi thẳng) móc dòng đơn '<đơn>/<SKU>/<ĐV>'."""
	kq = mong.get("kq") or {}
	don = {h["id"]: h["order_id"] for h in kq.get("hd") or []}
	for d in kq.get("dong_hd") or []:
		if not d["is_exchange"] and d.get("order_line_id") is None:
			d["order_line_id"] = f"{don.get(d['invoice_id'])}/{d['product_id']}/{d['unit_name']}"


# (kịch bản, số lời gọi) → [(hàm sửa mong, lý do)] — rỗng ở M1: mọi khác biệt có chủ đích đã nằm trong `mong_frappe` của tệp vàng
LECH: dict = {}
# (bộ, hàm) → [(hàm sửa mong, lý do)]
LECH_BO = {("E2E", "bao_cao_so_ban"): [(_e2e_dong_don, "bộ E2E: sổ giả chèn thẳng HĐ không dòng đơn — Frappe đi RPC nên dòng HĐ móc dòng đơn")]}
# kịch bản chưa dựng ở M1 dù hàm đã có (thiếu phần bộ nền) — lý do
CHUA_DUNG_KB = {"VB-E04": "phần công nợ của bộ E2E (HD-E2E-1 Cô Ba NET12, khoản thu 05/09, TR-E2E-1 dư có) chưa dựng — màn /bao-cao/cong-no kiểm ở "
	"bài e2e portal (bao_cao_cong_no đã có từ P3d)"}


def _e09_thu_gia_von(tc: TestBaoCaoVang, sd: SoDoi) -> list[str]:
	"""VB-E09: thu ô `inventory.cost` của Kế toán bằng NPP Quyen Rieng trước các lời gọi (nppsale chỉ ẩn ở giao diện — số giống Chủ)."""
	frappe.get_doc({"doctype": "NPP Quyen Rieng", "nhan_vien": sd.ma["k:KT"], "khoa_quyen": "inventory.cost.read", "duoc_phep": 0}).insert(
		ignore_permissions=True)
	return []


def _e15_bang_gia_ngoai(tc: TestBaoCaoVang, sd: SoDoi) -> list[str]:
	"""VB-E15 (C4): thêm Item Price `Standard Selling` thùng 999.000 cho "Sữa một lượt" (name nhỏ hơn dòng `Gia chuan` — ra TRƯỚC nếu cổng không lọc)
	+ một Price List bán `Gia le` không gắn nhóm khách nào (thùng 1.000.000) → cổng `products(price_lists)` KHÔNG có hai dòng ấy; mã TS ("Hàng bán theo
	nhân viên") vẫn Theo bảng giá 900.000, Chênh lệch bán 40.000 (= VB-E05) — lời gọi ts:ban_hang sau hook đọc danh mục qua cổng."""
	sp = sd.ma["sp:ML1"]
	thung = sd.dv_frappe("ML1", "thùng")
	if not frappe.db.exists("Price List", "Standard Selling"):
		frappe.get_doc({"doctype": "Price List", "price_list_name": "Standard Selling", "selling": 1, "currency": "VND", "enabled": 1}).insert(
			ignore_permissions=True)
	frappe.db.set_value("Price List", "Standard Selling", {"selling": 1, "enabled": 1})
	ip = frappe.get_doc({"doctype": "Item Price", "item_code": sp, "price_list": "Standard Selling", "uom": thung, "price_list_rate": 999000})
	ip.name = "0000-VB-E15-STD"
	ip.flags.name_set = True
	ip.insert(ignore_permissions=True, set_name="0000-VB-E15-STD")
	if not frappe.db.exists("Price List", "Gia le"):
		frappe.get_doc({"doctype": "Price List", "price_list_name": "Gia le", "selling": 1, "currency": "VND", "enabled": 1}).insert(
			ignore_permissions=True)
	frappe.get_doc({"doctype": "Item Price", "item_code": sp, "price_list": "Gia le", "uom": thung, "price_list_rate": 1000000}).insert(
		ignore_permissions=True)
	gia = sorted((sd.dv("ML1", g["unit_name"]), so(g["price"]), g["group_id"]) for p in tc._san_pham_ts(sd, None) for g in p["price_lists"])
	mong = [("hộp", 20000, None), ("thùng", 450000, None)]
	return [] if gia == mong else [f"VB-E15: cổng products(price_lists) của ML1 = {gia} ≠ {mong} (bảng giá ngoài NPP lọt vào giá chung — C4)"]


TRUOC_GOI = {"VB-E09": (_e09_thu_gia_von,), "VB-E15": (_e15_bang_gia_ngoai,)}


def _e16_qua_han(tc: TestBaoCaoVang, t: dict) -> list[str]:
	"""VB-E16 (L11): `/rest/v1/rpc/bao_cao_so_ban?q=…` (GET như `goiMotLuot`) với hẹn ép rất nhỏ → HTTP 500 + {code 57014, message "canceling statement
	due to statement timeout"} (giao diện dịch QUA_HAN_VI); sau lỗi, lời gọi tiếp theo của cùng tiến trình chạy bình thường (hẹn giờ phiên trả lại)."""
	from nppsale.portal.rest import xu_ly

	class Yc:
		method = "GET"

		def __init__(self, ts):
			self.args = {"q": json.dumps(ts)}

		def get_data(self, as_text=False):
			return ""

	ts = {"p_tu": "2026-11-01", "p_den": "2026-11-30"}
	sai = []
	han_cu = frappe.db.get_execution_timeout()
	with patch("nppsale.luat.bao_cao.HET_GIO_BAO_CAO", 0.000001):
		ma, than = xu_ly("rpc/bao_cao_so_ban", Yc(ts))
	if (ma, (than.get("error") or {}).get("code"), (than.get("error") or {}).get("message")) != (500, MA_QUA_HAN, CAU_QUA_HAN):
		sai.append(f"VB-E16: quá hạn ra {ma} {than} — mong 500 {MA_QUA_HAN} {CAU_QUA_HAN}")
	if frappe.db.get_execution_timeout() != han_cu:
		sai.append(f"VB-E16: hẹn giờ phiên sau lỗi {frappe.db.get_execution_timeout()} ≠ trước {han_cu}")
	ma, than = xu_ly("rpc/bao_cao_so_ban", Yc(ts))
	if ma != 200 or "error" in than or sorted(than.get("data") or {}) != sorted(["dong_hd", "dong_tra", "gv", "gv_tra", "hd", "tra",
			"tinh_lai_gia_von"]):
		sai.append(f"VB-E16: lời gọi sau lỗi quá hạn không chạy bình thường: {ma} {str(than)[:300]}")
	return sai


KIEM_DAC_TA = {"VB-E16": _e16_qua_han}


def dung_cho_cong_that() -> dict:
	"""Bộ E2E + Sổ BC (S1) trên site cho cổng thật (`tools/cong_that.py --nen bao_cao` — bài đầu-cuối portal `dau-cuoi-bao-cao.test.ts`, VB-E02): cùng
	cách dựng của bài vàng (RPC dưới đúng người, đồng hồ ghim theo bước), không commit (cổng thật lui khi tắt). → khoá cho bài portal: org, email từng
	người, tên khách theo SĐT, mặt hàng, nhãn chứng từ → tên Frappe."""
	tc = TestBaoCaoVang("test_kich_ban_vang")
	with open(VANG, encoding="utf-8") as f:
		tc.vang = json.load(f)
	tc.setUp()  # điểm lưu + chốt commit / Error Log / xếp repost + ghim đồng hồ (dọn khi tiến trình cổng thật tắt)
	sai = tc._dung_e2e() + tc._dung_s1()
	if sai:
		raise SystemExit("dựng bộ báo cáo hỏng:\n" + "\n".join(sai))
	DongHo.dat(None)  # lời gọi của portal chạy theo giờ thật
	ra: dict = {"org": tc.bo["S1"].ma["org"]}
	for ten, sd in tc.bo.items():
		ra[ten] = {"nguoi": {k[2:]: v for k, v in sd.ma.items() if k.startswith("k:")}, "khach": {k[3:]: v for k, v in sd.ma.items() if k.startswith("kh:")},
			"hang": {k[3:]: v for k, v in sd.ma.items() if k.startswith("sp:")}, "nhan": dict(sd.nhan)}
	return ra
