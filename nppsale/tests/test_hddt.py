"""Route HĐĐT MISA `/api/einvoice/*` (nppsale.api.misa) — đặc tả HĐĐT §4 (trừ §4.2), §8.1 Nhóm C (phát hành), D (làm mới / đánh dấu tờ gốc /
ghi kéo về), G (đối soát tay), H (cấu hình + thử kết nối) và ca route của Nhóm K (KV-51 … KV-56). Cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_hddt

Gọi thẳng hàm `@tuyen` với `YeuCauCu` dưới từng người của dữ liệu vàng xuất hàng (chủ / QL / KT / NVBH / kho — `du_lieu/xuat_hang_mau.json`);
JSON trả về đi một vòng `json.dumps` như `tuyen._tra`. MISA là adapter giả (`requests.adapters.BaseAdapter` — không `responses` / `requests_mock`,
không gọi mạng thật); giá trị bí mật là chữ bịa (u-thu / p-thu / T1). Bộ so chuẩn §8.0: (1) mã HTTP + JSON nguyên văn, (2) lời gọi MISA (thứ tự,
phương thức, URL, header, thân), (3) dòng NPP HDDT, (4) NPP MISA Log mới, (5) bất biến I1–I11 (`_bat_bien`, chạy cuối MỖI bài).

Dữ liệu: HĐ bán của tình huống vàng `xuat_du_mot_lo` (P1 "Nuoc ngot VTD" 2 Lon × 9.500 @ 8 %, P2 "Dau an VTD" 1 Chai × 5.000 @ 10 % → 24.000 /
2.020 / 26.020; khách C1 thêm MST 0301175691-044 + địa chỉ "12 Lê Lợi" như K1 của §8.0) thay HD-0001 của §8.0 (số khác, cùng luật). Giờ ghim
`luc` = 15/11/2026 10:00 giờ VN (`misa.bay_gio`).

Lệch có chủ ý so với nppsale (bài khai): H3 (đẩy lại hỏi MISA trước), H4 (pending → 409), H5 (xác nhận đẩy; treo > 10 phút → error), H6 (HĐ
đã huỷ), H8, H13 (ghi hỏng báo lỗi), H17, H22, H23 (tờ đã có số → cached), H24, H25, H26, H27 (hỏi trước khi POST lần 2); RefID ghi TRƯỚC khi gửi
(commit trước HTTP); token lấy trước giành tờ; câu truyền tải tiếng Việt; một lời /oauth ở Thử kết nối; nối tay ≥ 2 snapshot chiếm → 409; id
không phải uuid → 404; Dựng từ snapshot một giao dịch; [ĐX] MISA đã xác nhận có tờ (bước 10 / H27) mà ghi kết quả hỏng → GIỮ `pending` (không
`error` — khỏi mở khoá Huỷ HĐ cho HĐ đã có nháp trên MISA); kết quả lỗi của lần đẩy không đè lượt Làm mới song song.

Soi chung mọi bài (không chỉ bài tự hỏi): I2 ở `phat_hanh()` (số HĐĐT chỉ đổi qua nhánh "MISA đã có tờ"), I11 ở `AdapterHddt` (lúc lời đẩy bay đi
dòng chưa có số / mã), I1 / I3–I6 ở `_bat_bien` (cuối mỗi bài).
"""
from __future__ import annotations

import datetime
import json
import re
import threading
import uuid
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import parse_qsl

import frappe
import requests
from frappe.tests import IntegrationTestCase

from nppsale.api import misa as M
from nppsale.api import misa_mang as MM
from nppsale.api.tuyen import YeuCauCu
from nppsale.cong.dang_ky import NguCanh
from nppsale.luat import hddt as H
from nppsale.npp_hddt.doctype.npp_misa_cau_hinh import npp_misa_cau_hinh as CH
from nppsale.tests.test_cong_hddt import _NenCong
from nppsale.tests.test_hddt_khoa import dong_hddt

API = "https://misa.gia/api/v2"
MST = "0100000000"
LUC = datetime.datetime(2026, 11, 15, 10, 0, 0)  # giờ site (VN)
LUC_VN = "2026-11-15T10:00:00+07:00"
TOK = {"body": {"access_token": "T1", "expires_in": 3600}}
TOK2 = {"body": {"access_token": "T2", "expires_in": 3600}}
RONG = {"body": {"success": True, "data": None}}  # GET ?refID= không có tờ
CAU_HINH_CHUAN = {"api_base": API, "tax_code": MST, "username": "u-thu", "password": "p-thu", "misa_inv_series": "1C26TAA",
	"misa_company_id": "156217", "sandbox": True, "is_active": True}
BI_MAT = ("u-thu", "p-thu")
MAC_DINH_REQUESTS = {"User-Agent", "Accept-Encoding", "Accept", "Connection", "Content-Length"}
DA_CO = {"InvNo": "<Chưa cấp số>", "PublishStatus": 0}  # bản ghi MISA của tờ nháp (+ TotalAmount theo sổ)
CAU_CHUA_BIET = ("Không nhận được trả lời của MISA (hết giờ / rớt mạng) — chưa biết MISA đã nhận hoá đơn chưa. ĐỪNG đẩy lại: bấm 'Làm mới "
	"trạng thái từ MISA' sau ít phút.")


def tra_map(ref="R", **them) -> dict:
	"""Phản hồi POST /v3sainvoice dạng map RefID → {Data: chuỗi OBJECT} (KV-15) — bộ đọc chép nguyên văn không đọc được mã (H20) ⇒ `sent`."""
	inner = {"RefID": ref, "InvNo": "<Chưa cấp số>", **them}
	return {"body": {"success": True, "data": json.dumps({ref: {"Data": json.dumps(inner, ensure_ascii=False), "ErrorMessage": None,
		"ErrorCode": [], "Success": True, "EntityState": 0}}, ensure_ascii=False)}}


def tra_mang(**them) -> dict:
	"""`Data` là chuỗi MẢNG (KV-16) → đọc được TransactionID / InvNo."""
	return {"body": {"success": True, "data": json.dumps({"R": {"Data": json.dumps([{"RefID": "R", **them}], ensure_ascii=False),
		"Success": True}}, ensure_ascii=False)}}


def get_ban_ghi(**bg) -> dict:
	"""GET ?refID= → {success, data: chuỗi JSON bản ghi}."""
	return {"body": {"success": True, "data": json.dumps(bg, ensure_ascii=False)}}


def kiem_i11(than) -> str | None:
	"""I11 (§1.8): lúc một `POST /v3sainvoice` bay đi, dòng mang RefID của payload KHÔNG được đã có `misa_inv_no` / `misa_lookup_code` (H23 — tờ đã có
	số / mã thì không đẩy nháp thứ hai). → câu vi phạm | None. Đọc bằng kết nối của chính luồng gửi (bài hai luồng: kết nối của luồng ấy)."""
	try:
		ref = json.loads(than)[0]["RefID"]
	except Exception:  # thân không phải payload phát hành — bài khác tự kiểm
		return None
	r = frappe.db.sql("SELECT `name`, `misa_inv_no`, `misa_lookup_code` FROM `tabNPP HDDT` WHERE `misa_ref_id` = %s", ref, as_dict=True)
	if r and (r[0].misa_inv_no or r[0].misa_lookup_code):
		return f"I11: POST /v3sainvoice cho dòng {r[0].name} đã có số {r[0].misa_inv_no!r} / mã {r[0].misa_lookup_code!r}"
	return None


class AdapterHddt(requests.adapters.BaseAdapter):
	"""AdapterGia của §8.0 (+ kịch bản là hàm `f(request) → dict`, khoá luồng cho bài hai tiến trình): ghi (phương thức, URL, header, thân) và
	soi I11 ở mỗi lời đẩy (`vi_pham` — `_bat_bien` đòi rỗng)."""

	def __init__(self, kich_ban, khi_goi=None):
		super().__init__()
		self.kich_ban, self.goi, self.khi_goi, self._khoa = list(kich_ban), [], khi_goi, threading.Lock()
		self.vi_pham = []

	def send(self, request, **kw):
		with self._khoa:
			self.goi.append((request.method, request.url, dict(request.headers), request.body))
			b = self.kich_ban.pop(0) if self.kich_ban else AssertionError(f"lời gọi MISA thừa: {request.method} {request.url}")
		if request.method == "POST" and "/v3sainvoice" in request.url and "paging" not in request.url:
			loi = kiem_i11(request.body)
			if loi:
				self.vi_pham.append(loi)
		if self.khi_goi:
			self.khi_goi(request)
		if callable(b) and not isinstance(b, BaseException):
			b = b(request)
		if isinstance(b, BaseException):
			raise b
		r = requests.models.Response()
		r.status_code, r.request, r.url = b.get("status", 200), request, request.url
		than = b.get("body", {})
		r._content = (than if isinstance(than, str) else json.dumps(than, ensure_ascii=False)).encode()
		return r

	def close(self):
		pass


_PHIEN_THAT = MM._phien


def gon(a: AdapterHddt) -> list:
	return [f"{m} {u[len(API):] if u.startswith(API) else u}" for m, u, _h, _b in a.goi]


def hd_app(h: dict) -> list:
	return [(k, v) for k, v in h.items() if k not in MAC_DINH_REQUESTS]


def bo_ref_detail(p: list) -> list:
	"""Payload bỏ `RefDetailID` (uuid mới mỗi dòng) để so trọn phần còn lại."""
	p = json.loads(json.dumps(p))
	for d in p[0]["InvoiceDetails"]:
		d.pop("RefDetailID")
	return p


class _NenHddt(_NenCong):
	"""Nền `_NenCong` (HĐ ghi sổ `self.hd` của đơn `self.don` + cổng dưới đúng người) + cấu hình MISA sạch, giờ ghim, token RAM sạch, MISA giả."""

	def setUp(self):
		super().setUp()
		frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)
		frappe.db.sql("DELETE FROM `__Auth` WHERE `doctype` = %s", CH.TEN)
		frappe.clear_document_cache(CH.TEN, CH.TEN)
		MM.xoa_token_nho()
		self.addCleanup(MM.xoa_token_nho)
		self.luc = LUC
		p = patch.object(M, "bay_gio", lambda: self.luc)
		p.start()
		self.addCleanup(p.stop)
		self.gio = 1000.0
		p = patch.object(MM, "_dong_ho", lambda: self.gio)
		p.start()
		self.addCleanup(p.stop)
		self.kh = frappe.db.get_value("Sales Invoice", self.hd, "customer")
		frappe.db.set_value("Customer", self.kh, {"tax_id": "0301175691-044", "npp_dia_chi": "12 Lê Lợi", "npp_hinh_thuc_tt": "Chuyển khoản"})
		self.loi_truoc = frappe.db.sql("SELECT IFNULL(MAX(`creation`), '2000-01-01') FROM `tabError Log`")[0][0]
		self.a = None
		self.cac_adapter = []

	def tearDown(self):
		try:
			self._bat_bien()  # I1–I6 trên trạng thái cuối của MỖI bài
		finally:
			frappe.db.sql("DELETE FROM `tabError Log` WHERE `creation` > %s AND `method` LIKE 'HĐĐT MISA%%'", self.loi_truoc)  # MyISAM
			super().tearDown()

	# ------------------------------------------------------------------------------------------------ gọi route
	def goi(self, nguoi: str | None, ham, than=None, pt: str = "POST") -> tuple:
		"""Gọi hàm `@tuyen` dưới người `nguoi` (khoá của `self.ma`, hoặc None = Administrator) → (mã, JSON đã đi một vòng json như tuyen._tra)."""
		frappe.set_user(self.ma["u:" + nguoi] if nguoi else "Administrator")
		frappe.local._npp_ngu_canh = None
		try:
			ma, kq = ham(YeuCauCu(duong="/api/einvoice/x", phuong_thuc=pt, than=than))
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None
		return ma, json.loads(json.dumps(kq, ensure_ascii=False, default=str))

	def mang(self, *kich_ban, khi_goi=None) -> AdapterHddt:
		a = AdapterHddt(kich_ban, khi_goi)
		s = _PHIEN_THAT()
		s.mount("https://", a)
		s.mount("http://", a)
		p = patch.object(MM, "_phien", lambda: s)
		p.start()
		self.addCleanup(p.stop)
		self.a = a
		self.cac_adapter.append(a)
		return a

	def cau_hinh(self, **kv) -> None:
		ma, kq = self.goi("owner", M.cau_hinh_luu, {**CAU_HINH_CHUAN, **kv})
		self.assertEqual((ma, kq), (200, {"success": True}))

	def phat_hanh(self, ten: str, nguoi: str = "owner", *, kiem_i2: bool = True, **than) -> tuple:
		"""Gọi Phát hành + soi I2: `misa_inv_no` chỉ đổi qua luồng KÉO VỀ — ở phát hành là nhánh "MISA đã có tờ" (bước 10 / H27), có nhật ký
		`publish` mang câu `CAU_DA_CO_TREN_MISA`; mọi nhánh khác không được đụng số. `kiem_i2=False`: bài tự giả một lượt kéo về SONG SONG ghi số
		giữa chừng (số đổi không do phát hành)."""
		co_dong = kiem_i2 and isinstance(ten, str) and frappe.db.exists("NPP HDDT", ten)
		so_truoc = frappe.db.get_value("NPP HDDT", ten, "misa_inv_no") if co_dong else None
		kq = self.goi(nguoi, M.phat_hanh, {"invoiceId": ten, **than})
		if co_dong and frappe.db.get_value("NPP HDDT", ten, "misa_inv_no") != so_truoc:
			nk = self.nhat_ky(hddt=ten, nguon="publish")
			self.assertTrue(nk and nk[-1].loi == M.CAU_DA_CO_TREN_MISA, f"I2: phát hành đổi misa_inv_no của {ten} ngoài luồng kéo về")
		return kq

	def lam_moi(self, ten: str, nguoi: str = "accountant") -> tuple:
		return self.goi(nguoi, M.lam_moi, {"invoiceId": ten})

	def lap(self, hd: str | None = None) -> str:
		"""Dòng HĐĐT của HĐ bán (dam_bao_dong — đường cổng INSERT dùng)."""
		return M.dam_bao_dong(hd or self.hd, self._nc("owner"))

	def dong(self, ten: str) -> dict:
		return frappe.db.get_value("NPP HDDT", ten, ["*"], as_dict=True)

	def nhat_ky(self, **loc) -> list:
		return frappe.get_all("NPP MISA Log", filters=loc, fields=["*"], order_by="creation asc, name asc")

	def payload(self, a: AdapterHddt | None = None) -> list:
		goi = [g for g in (a or self.a).goi if g[0] == "POST" and "/v3sainvoice" in g[1] and "paging" not in g[1]]
		return json.loads(goi[-1][3])

	# ------------------------------------------------------------------------------------------------ bất biến (§1.8)
	def _bat_bien(self):
		dong = frappe.db.sql("SELECT * FROM `tabNPP HDDT`", as_dict=True)
		ref = [d.misa_ref_id for d in dong if d.misa_ref_id]
		self.assertEqual(len(ref), len(set(ref)), "I1: hai dòng cùng RefID")
		cap = [((d.misa_inv_series or "").upper(), d.misa_inv_no) for d in dong if d.misa_inv_no]
		self.assertEqual(len(cap), len(set(cap)), "I3")
		for d in dong:
			self.assertIn(d.misa_status or "", ("", "pending", "sent", "waiting_code", "signed", "replaced", "cancelled", "amount_mismatch",
				"error"), "I4")
			self.assertIn(d.misa_relation or "", ("", "new", "replacement", "adjustment", "replaced", "adjusted", "unknown"), "I4")
			self.assertIn(d.trang_thai, ("draft", "issued", "cancelled"), "I4")
			if d.misa_status == "pending":
				self.assertTrue(d.misa_ref_id, "I4: pending phải có RefID")
		for nk in self.nhat_ky(nguon="publish"):  # I5
			gui = json.loads(nk.gui_di) if nk.gui_di else None
			if isinstance(gui, list):
				self.assertEqual(gui[0]["RefID"], frappe.db.get_value("NPP HDDT", nk.hddt, "misa_ref_id"), "I5")
		self.assertEqual([v for a in self.cac_adapter for v in a.vi_pham], [], "I11")  # soi lúc từng lời đẩy bay đi (AdapterHddt)
		self._i6()

	def _i6(self, *them):
		"""I6: không chuỗi nào trong nhật ký / misa_error / misa_note / Error Log chứa tài khoản / mật khẩu / token của bài."""
		chu = []
		for nk in frappe.db.sql("SELECT `gui_di`, `nhan_ve`, `loi` FROM `tabNPP MISA Log`"):
			chu += [x or "" for x in nk]
		for d in frappe.db.sql("SELECT `misa_error`, `misa_note` FROM `tabNPP HDDT`"):
			chu += [x or "" for x in d]
		for el in frappe.db.sql("SELECT `method`, `error` FROM `tabError Log` WHERE `creation` > %s", self.loi_truoc):
			chu += [x or "" for x in el]
		toan = "\n".join(chu)
		for bm in (*BI_MAT, *them):
			self.assertNotIn(bm, toan, f"I6: lộ {bm}")
		self.assertIsNone(re.search(r"(?<![0-9A-Za-z])T[12](?![0-9A-Za-z])", toan), "I6: lộ token T1 / T2")



class _NenPhatHanh(_NenHddt):
	"""+ cấu hình chuẩn đã lưu qua route dưới CHU (§8.0: api https://misa.gia/api/v2, MST 0100000000, u-thu / p-thu, không mã, 1C26TAA, 156217)."""

	def setUp(self):
		super().setUp()
		self.cau_hinh()


def _hong(cau: str):
	"""Hàm thay thế ném lỗi — hàm thường (không MagicMock: khung của mock giữ `args` dưới tên KHÔNG nhạy cảm, traceback có biến sẽ in token thật
	truyền vào — giả lỗi của bài, không phải của mã)."""

	def ham(*_a_token, **_k_token):
		raise RuntimeError(cau)

	return ham


def _vn(gio: datetime.datetime) -> datetime.datetime:
	from zoneinfo import ZoneInfo

	return gio.replace(tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))


# =====================================================================================================================================
# Nhóm C — phát hành (§4.1)
# =====================================================================================================================================
class TestPhatHanh(_NenPhatHanh):
	def _cau_hinh_payload(self) -> dict:
		return MM.lay_cau_hinh().cau_hinh_payload

	def _payload_hd(self, ref: str, nguoi_mua: dict | None = None, che_do: str = "as_sold") -> list:
		"""Payload mong cho `self.hd` dựng từ đầu vào VIẾT TAY (dòng / người mua của HĐ + cấu hình) — mapper đã so vàng với TS ở test_luat_hddt;
		bài này canh phần route đưa vào mapper (đọc dòng / người mua / cấu hình / RefID / giờ)."""
		nm = nguoi_mua or {"ten": "Tap hoa VTD 1", "mst": "0301175691-044", "dia_chi": "12 Lê Lợi", "email": None, "kenh": None,
			"hinh_thuc_tt": "Chuyển khoản"}
		dong = [H.dong_hang("Nuoc ngot VTD", "VTD-P1", "Lon", "Lon", 2, 9500, 0, 1, 8),
			H.dong_hang("Dau an VTD", "VTD-P2", "Chai", "Chai", 1, 5000, 0, 1, 10)]
		return H.dung_payload(nm, dong, ref, self._cau_hinh_payload(), che_do, None, _vn(LUC))

	def test_kv15_lan_dau_misa_nhan_nhap(self):
		"""KV-15 [= trừ thời điểm ghi RefID]: ensureEInvoiceRow qua cổng (chủ) rồi Phát hành → 2 lời gọi; dòng `issued` / `sent`, RefID = RefID đã gửi,
		mốc gửi = phát hành = `luc`; trả 200 không mã; một nhật ký success của CHU."""
		org = frappe.db.get_single_value("NPP Cai Dat", "org_id")
		tim = {"select": "id", "loc": [{"op": "eq", "cot": "sales_invoice_id", "gt": self.hd}], "mot": "maybe"}
		self.assertIsNone(self._doc("owner", **tim))
		kq = self._ghi("owner", "insert", {"org_id": org, "order_id": self.don, "sales_invoice_id": self.hd, "invoice_number": None,
			"customer_name": "Tap hoa VTD 1", "customer_address": "12 Lê Lợi", "customer_tax_code": "0301175691-044", "subtotal": 24000,
			"vat": 2020, "total": 26020, "status": "draft"}, select="id", mot="one")
		e = kq["data"]["id"]
		a = self.mang(TOK, tra_map())
		ma, kq = self.phat_hanh(e, mode="as_sold")
		self.assertEqual((ma, kq), (200, {"success": True, "lookup_code": None, "inv_no": None, "invoice_url": None, "sandbox": True}))
		self.assertEqual(gon(a), ["POST /oauth", "POST /v3sainvoice"])
		(_m, _u, h_tok, than_tok), (_m2, _u2, h_day, _than) = a.goi
		self.assertEqual(hd_app(h_tok), [("Content-Type", "text/plain"), ("taxcode", MST)])
		self.assertEqual(than_tok, b"grant_type=password&username=u-thu&password=p-thu")
		self.assertEqual(hd_app(h_day), [("Content-Type", "application/json"), ("Authorization", "Bearer T1"), ("TaxCode", MST)])
		r = self.dong(e)
		p = self.payload(a)
		self.assertEqual(p[0]["RefID"], r.misa_ref_id)
		self.assertEqual(str(uuid.UUID(r.misa_ref_id)), r.misa_ref_id)
		self.assertEqual(bo_ref_detail(p), bo_ref_detail(self._payload_hd(r.misa_ref_id)))
		h = p[0]
		self.assertEqual([(d["InventoryItemCode"], d["UnitName"], d["Quantity"], d["UnitPrice"], d["AmountOC"], d["DiscountAmountOC"],
			d["VATRate"], d["VATAmountOC"]) for d in h["InvoiceDetails"]], [("VTD-P1", "Lon", 2, 9500, 19000, 0, 8, 1520),
			("VTD-P2", "Chai", 1, 5000, 5000, 0, 10, 500)])
		self.assertEqual((h["TotalSaleAmountOC"], h["TotalDiscountAmountOC"], h["TotalAmountWithoutVATOC"], h["TotalVATAmountOC"],
			h["TotalAmountOC"]), (24000, 0, 24000, 2020, 26020))  # = sổ
		self.assertEqual((h["IsMoreVATRate"], h["VATRate"], h["IsTaxReduction43"], h["TypeDiscount"], h["InvNo"], h["InvDate"], h["CompanyID"],
			h["InvSeries"], h["AccountObjectName"], h["AccountObjectTaxCode"], h["AccountObjectAddress"], h["ContactName"], h["PaymentMethod"]),
			(True, 0, True, 0, "<Chưa cấp số>", LUC_VN, "156217", "1C26TAA", "Tap hoa VTD 1", "0301175691-044", "12 Lê Lợi", "Tap hoa VTD 1",
			"Chuyển khoản"))
		self.assertEqual(len({d["RefDetailID"] for d in h["InvoiceDetails"]}), 2)
		self.assertEqual({d["RefID"] for d in h["InvoiceDetails"]}, {r.misa_ref_id})
		self.assertEqual((r.trang_thai, r.phat_hanh_luc, r.misa_status, r.misa_sent_at, r.hoa_don_ban, r.don_hang), ("issued", LUC, "sent", LUC,
			self.hd, self.don))
		for k in ("misa_lookup_code", "misa_invoice_url", "misa_error", "misa_signed_at", "misa_published_at", "misa_inv_no"):
			self.assertFalse(r.get(k), k)
		self.assertEqual((r.tien_hang, r.tien_thue, r.tong_tien), (24000, 2020, 26020))
		(nk,) = self.nhat_ky()
		self.assertEqual((nk.nguon, nk.ket_qua, nk.hddt, nk.don_hang, nk.owner, nk.loi, nk.misa_lookup_code, nk.misa_inv_no),
			("publish", "success", e, self.don, self.ma["u:owner"], None, None, None))
		self.assertEqual(json.loads(nk.gui_di), p)
		self.assertEqual(json.loads(nk.nhan_ve), tra_map()["body"])  # thân MISA đã parse (dict)
		# cổng: tờ đã tới MISA đọc ra RefID (H3b chỉ che trống / error)
		self.assertEqual(self._doc("owner", select="misa_ref_id, misa_status", loc=[{"op": "eq", "cot": "id", "gt": e}], mot="one"),
			{"misa_ref_id": r.misa_ref_id, "misa_status": "sent"})

	def test_kv16_misa_tra_ma_tra_cuu_ngay(self):
		"""KV-16 [= — H20]: Data là chuỗi MẢNG → signed + mã tra cứu + link + ký / phát hành = luc; `misa_inv_no` VẪN NULL (I2 — số chỉ từ kéo về);
		trả inv_no MISA báo; nhật ký mang mã + số."""
		e = self.lap()
		a = self.mang(TOK, tra_mang(InvNo="00000123", TransactionID="TXABC"))
		ma, kq = self.phat_hanh(e)
		url = "https://www.meinvoice.vn/tra-cuu?code=TXABC"
		self.assertEqual((ma, kq), (200, {"success": True, "lookup_code": "TXABC", "inv_no": "00000123", "invoice_url": url, "sandbox": True}))
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.misa_lookup_code, r.misa_invoice_url, r.misa_signed_at, r.misa_published_at, r.misa_inv_no),
			("signed", "TXABC", url, LUC, LUC, None))
		(nk,) = self.nhat_ky()
		self.assertEqual((nk.ket_qua, nk.misa_lookup_code, nk.misa_inv_no), ("success", "TXABC", "00000123"))
		self.assertEqual(len(a.goi), 2)

	def test_kv17_bam_lai_khi_da_gui(self):
		"""KV-17 [=]: tờ đã tới MISA → 200 cached; 0 lời gọi, 0 nhật ký, dòng không đổi (kể cả `modified`); bấm từ màn HĐ bán: tìm ra dòng cũ."""
		e = self.lap()
		self.mang(TOK, tra_map())
		self.assertEqual(self.phat_hanh(e)[0], 200)
		truoc, n = self.dong(e), len(self.nhat_ky())
		a = self.mang()
		for _ in range(2):
			ma, kq = self.phat_hanh(e)
			self.assertEqual((ma, kq), (200, {"success": True, "cached": True, "lookup_code": None, "ref_id": truoc.misa_ref_id, "inv_no": None,
				"invoice_url": None}))
		self.assertEqual((a.goi, len(self.nhat_ky())), ([], n))
		self.assertEqual(self.dong(e), truoc)
		self.assertEqual(self.lap(), e)

	def test_kv18a_dang_xu_ly_409(self):
		"""KV-18 (a) [≠ H4]: dòng `pending` + RefID → 409 câu nppsale; 0 lời gọi; dòng không đổi."""
		e = self.lap()
		frappe.db.sql("UPDATE `tabNPP HDDT` SET `misa_status` = 'pending', `misa_ref_id` = %s, `misa_sent_at` = %s WHERE `name` = %s",
			(str(uuid.uuid4()), LUC, e))
		truoc = self.dong(e)
		a = self.mang()
		self.assertEqual(self.phat_hanh(e), (409, {"error": "Hoá đơn đang được xử lý hoặc đã phát hành. Thử lại sau giây lát."}))
		self.assertEqual((a.goi, self.dong(e), self.nhat_ky()), ([], truoc, []))

	def test_buoc4_cac_trang_thai(self):
		"""Bước 4: có mã tra cứu / có số (H23) / đã tới MISA → cached; pending → 409; trống / error → đi tiếp (không ghi gì nếu chưa qua bước 6)."""
		for kv, mong in (({"misa_lookup_code": "TX9", "misa_status": "error"}, 200), ({"misa_inv_no": "0000777", "misa_inv_series": "1C26TAA"}, 200),
				({"misa_status": "waiting_code", "misa_ref_id": "@"}, 200), ({"misa_status": "amount_mismatch", "misa_ref_id": "@"}, 200),
				({"misa_status": "replaced", "misa_ref_id": "@"}, 200), ({"misa_status": "cancelled", "misa_ref_id": "@"}, 200)):
			with self.subTest(kv=kv):
				if kv.get("misa_ref_id") == "@":
					kv = {**kv, "misa_ref_id": str(uuid.uuid4())}
				e = dong_hddt(**kv)
				truoc = self.dong(e)
				a = self.mang()
				ma, kq = self.phat_hanh(e)
				self.assertEqual((ma, kq.get("cached")), (mong, True))
				self.assertEqual((a.goi, self.dong(e)), ([], truoc))

	def test_dau_vao_va_quyen(self):
		"""Bước 1–3: thân không phải object → 400 "Body không hợp lệ"; thiếu / trống invoiceId → 400; vai ngoài chủ / KT / QL (NVBH, kho, NV nghỉ,
		Administrator) → 403 câu nppsale; mã không có → 404. Không gọi MISA, không ghi."""
		a = self.mang()
		for than in (None, "abc", [1], 5):
			self.assertEqual(self.goi("owner", M.phat_hanh, than), (400, {"error": "Body không hợp lệ"}), than)
		for than in ({}, {"invoiceId": ""}, {"invoiceId": "   "}, {"invoiceId": None}, {"invoiceId": 0}):
			self.assertEqual(self.goi("owner", M.phat_hanh, than), (400, {"error": "Thiếu invoiceId"}), than)
		e = self.lap()
		for nguoi in ("sales_a", "warehouse", "sales_nghi", None):
			self.assertEqual(self.phat_hanh(e, nguoi), (403, {"error": "Chỉ Chủ NPP, Kế toán hoặc Quản lý mới được phát hành hoá đơn"}), nguoi)
		self.assertEqual(self.phat_hanh("khong-co"), (404, {"error": "Không tìm thấy hoá đơn"}))
		self.assertEqual(self.phat_hanh(12345), (404, {"error": "Không tìm thấy hoá đơn"}))
		self.assertEqual(a.goi, [])
		self.assertFalse(self.dong(e).misa_status)

	def test_quan_ly_va_ke_toan_phat_hanh_duoc(self):
		for nguoi in ("manager", "accountant"):
			with self.subTest(nguoi=nguoi):
				frappe.db.savepoint("vai")
				e = self.lap()
				self.mang(TOK, tra_map())
				self.assertEqual(self.phat_hanh(e, nguoi)[0], 200)
				self.assertEqual(self.nhat_ky()[-1].owner, self.ma["u:" + nguoi])
				frappe.db.rollback(save_point="vai")
				MM.xoa_token_nho()

	def test_kv19_misa_tu_choi_roi_day_lai(self):
		"""KV-19 [≠ H3]: MISA từ chối rõ → 502 câu trong; dòng `error`, RefID GIỮ, vẫn draft, mốc gửi = luc; nhật ký failed; Huỷ HĐ bán ĐƯỢC (vế
		khoá không gồm error). Đẩy lại: hỏi `GET ?refID=R1` trước → không có → POST với CÙNG RefID (token từ RAM — không /oauth) → sent."""
		e = self.lap()
		tu_choi = {"body": {"success": True, "data": json.dumps({"R1": {"Data": None, "ErrorMessage": "Mã số thuế người mua không hợp lệ",
			"ErrorCode": ["InvalidBuyerTaxCode"], "Success": False}}, ensure_ascii=False)}}
		self.mang(TOK, tu_choi)
		cau = 'MISA từ chối hoá đơn: Mã số thuế người mua không hợp lệ · ["InvalidBuyerTaxCode"]'
		self.assertEqual(self.phat_hanh(e), (502, {"error": cau}))
		r = self.dong(e)
		r1 = r.misa_ref_id
		self.assertEqual((r.misa_status, r.misa_error, r.trang_thai, r.misa_sent_at, bool(r1)), ("error", cau, "draft", LUC, True))
		(nk,) = self.nhat_ky()
		self.assertEqual((nk.ket_qua, nk.loi, json.loads(nk.gui_di)[0]["RefID"]), ("failed", cau, r1))
		frappe.db.savepoint("huy")
		kq = self._huy()
		self.assertNotIn("error", kq, kq)
		frappe.db.rollback(save_point="huy")
		self.luc = LUC + datetime.timedelta(minutes=3)
		a = self.mang(RONG, tra_map())
		self.assertEqual(self.phat_hanh(e)[0], 200)
		self.assertEqual(gon(a), [f"GET /v3sainvoice/?refID={r1}", "POST /v3sainvoice"])
		self.assertEqual(self.payload(a)[0]["RefID"], r1)
		r = self.dong(e)
		self.assertEqual((r.misa_ref_id, r.misa_status, r.misa_error, r.trang_thai, r.misa_sent_at, r.phat_hanh_luc),
			(r1, "sent", None, "issued", self.luc, self.luc))
		self.assertEqual([x.ket_qua for x in self.nhat_ky()], ["failed", "success"])

	def test_kv20_day_lai_khi_misa_that_ra_da_co(self):
		"""KV-20 [≠ H3, H5]: POST 500 → 502, KHÔNG thử lại, nhật ký `{"raw": …}`. Đẩy lại: GET thấy tờ → KHÔNG POST; áp như Làm mới + xác nhận đẩy
		(sent, issued, phat_hanh_luc, misa_error NULL, mốc hỏi) → 200 cached; nhật ký success "MISA đã có…"."""
		e = self.lap()
		a = self.mang(TOK, {"status": 500, "body": "<html>Bad gateway</html>"})
		self.assertEqual(self.phat_hanh(e), (502, {"error": "MISA publish lỗi 500: <html>Bad gateway</html>"}))
		self.assertEqual(gon(a), ["POST /oauth", "POST /v3sainvoice"])
		(nk,) = self.nhat_ky()
		self.assertEqual((nk.ket_qua, json.loads(nk.nhan_ve)), ("failed", {"raw": "<html>Bad gateway</html>"}))
		ref = self.dong(e).misa_ref_id
		self.luc = LUC + datetime.timedelta(minutes=2)
		a = self.mang(get_ban_ghi(RefID=ref, InvNo="<Chưa cấp số>", PublishStatus=0, TotalAmount=26020))
		ma, kq = self.phat_hanh(e)
		self.assertEqual((ma, kq), (200, {"success": True, "cached": True, "lookup_code": None, "ref_id": ref, "inv_no": None,
			"invoice_url": None}))
		self.assertEqual(gon(a), [f"GET /v3sainvoice/?refID={ref}"])
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.trang_thai, r.phat_hanh_luc, r.misa_error, r.misa_last_checked_at, r.misa_ref_id),
			("sent", "issued", self.luc, None, self.luc, ref))
		nk = self.nhat_ky()[-1]
		self.assertEqual((nk.nguon, nk.ket_qua, json.loads(nk.gui_di), nk.loi),
			("publish", "success", {"source": "hoi_truoc_khi_day_lai", "ref_id": ref}, "MISA đã có hoá đơn với RefID này — không đẩy lại."))
		self.assertEqual(json.loads(nk.nhan_ve)["TotalAmount"], 26020)

	def test_day_lai_thay_to_da_ky_tren_misa(self):
		"""H3: tờ `error` có RefID mà MISA thật ra đã có — và kế toán đã KÝ trên web MISA — đẩy lại: GET thấy bản ghi có số → KHÔNG POST; ghi như Làm mới
		(số / ký hiệu / mã tra cứu / mã CQT / signed) + xác nhận đẩy (issued, misa_error NULL); 200 cached mang số + mã đọc lại từ dòng; nhật ký success
		"MISA đã có…" (I2: số đổi qua luồng kéo về). Huỷ HĐ → LOCKED_EINVOICE "đã phát hành"."""
		e = self.lap()
		r1 = str(uuid.uuid4())
		frappe.db.set_value("NPP HDDT", e, {"misa_status": "error", "misa_ref_id": r1, "misa_error": "MISA publish lỗi 500: x"},
			update_modified=False)
		a = self.mang(TOK, get_ban_ghi(**ban_ghi_ky()))
		self.assertEqual(self.phat_hanh(e), (200, {"success": True, "cached": True, "lookup_code": "TX1", "ref_id": r1, "inv_no": "00000123",
			"invoice_url": None}))
		self.assertEqual(gon(a), ["POST /oauth", f"GET /v3sainvoice/?refID={r1}"])
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.misa_inv_no, r.misa_inv_series, r.misa_lookup_code, r.misa_invoice_code, r.trang_thai, r.phat_hanh_luc,
			r.misa_error, r.misa_ref_id, r.misa_invoice_url, r.misa_signed_at), ("signed", "00000123", "1C26TAA", "TX1", "M1-26-XYZ", "issued", LUC,
			None, r1, None, None))
		(nk,) = self.nhat_ky(hddt=e)
		self.assertEqual((nk.ket_qua, nk.loi, nk.misa_inv_no, nk.misa_lookup_code), ("success", "MISA đã có hoá đơn với RefID này — không đẩy lại.",
			"00000123", "TX1"))
		self.assertEqual(self._huy()["error"]["message"], "LOCKED_EINVOICE: hóa đơn đã phát hành hóa đơn điện tử")

	def test_kv20_hoi_truoc_hong(self):
		"""H3: hỏi MISA trước khi đẩy lại hỏng → 502 "Không hỏi được MISA trước khi đẩy lại: …", dòng `error` (RefID giữ), không POST."""
		e = dong_hddt(misa_status="error", misa_ref_id="R-cu", misa_error="x")
		a = self.mang(TOK, {"status": 401, "body": {"message": "Unauthorized"}})
		cau = "Không hỏi được MISA trước khi đẩy lại: Lấy HD lỗi 401: Unauthorized"
		self.assertEqual(self.phat_hanh(e), (502, {"error": cau}))
		self.assertEqual(gon(a), ["POST /oauth", "GET /v3sainvoice/?refID=R-cu"])
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.misa_error, r.misa_ref_id), ("error", cau, "R-cu"))

	def test_kv21_token_thu_hoi_giua_chung(self):
		"""KV-21 [= trừ H27]: T1 đã nhớ; POST 401 → /oauth ép (T2) → GET ?refID=R (H27, Bearer T2) không có → POST (Bearer T2) → OK; một nhật ký."""
		e = self.lap()
		self.mang(TOK)
		MM.lay_token(MM.lay_cau_hinh(lui_duong_token=False).giai_ma())
		a = self.mang({"status": 401, "body": {"message": "Token expired"}}, TOK2, RONG, tra_map())
		self.assertEqual(self.phat_hanh(e)[0], 200)
		ref = self.dong(e).misa_ref_id
		self.assertEqual(gon(a), ["POST /v3sainvoice", "POST /oauth", f"GET /v3sainvoice/?refID={ref}", "POST /v3sainvoice"])
		self.assertEqual([g[2].get("Authorization") for g in a.goi], ["Bearer T1", None, "Bearer T2", "Bearer T2"])
		self.assertEqual([x.ket_qua for x in self.nhat_ky()], ["success"])

	def test_kv22_het_gio_sau_khi_gui(self):
		"""KV-22 [≠ BP + H2, H5]: POST hết giờ đọc → 502 câu "chưa biết"; dòng giữ `pending` + RefID, misa_error "chưa biết…", vẫn draft; nhật ký
		pending. Bấm lại → 409; Huỷ HĐ → LOCKED_EINVOICE "đang chờ MISA" (H2). KT Làm mới thấy tờ nháp → sent + issued (xác nhận đẩy — H5)."""
		e = self.lap()
		self.mang(TOK, requests.exceptions.ReadTimeout("x"))
		self.assertEqual(self.phat_hanh(e), (502, {"error": CAU_CHUA_BIET}))
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.misa_error, r.trang_thai, bool(r.misa_ref_id)),
			("pending", "chưa biết MISA nhận chưa — bấm Làm mới trạng thái", "draft", True))
		self.assertEqual([x.ket_qua for x in self.nhat_ky()], ["pending"])
		self.assertEqual(self.phat_hanh(e)[0], 409)
		kq = self._huy()
		self.assertEqual(kq["error"]["message"], "LOCKED_EINVOICE: HĐĐT đang chờ MISA — bấm Làm mới trạng thái trước")
		a = self.mang(get_ban_ghi(**DA_CO, TotalAmount=26020))
		ma, kq = self.lam_moi(e)
		self.assertEqual((ma, kq), (200, {"success": True, "misa": {"InvNo": None, "TransactionID": None, "PublishStatus": 0,
			"EInvoiceStatus": None, "relation": None, "status": "sent", "notes": [], "original_marked_replaced": None}}))
		self.assertEqual(gon(a), [f"GET /v3sainvoice/?refID={r.misa_ref_id}"])
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.trang_thai, r.phat_hanh_luc, r.misa_error), ("sent", "issued", LUC, None))

	def test_kv23_khong_ket_noi_duoc(self):
		"""KV-23 [≠ — nppsale `fetch failed`]: hết giờ NỐI → chưa gửi → 502 câu tiếng Việt; `error`, RefID giữ; nhật ký failed."""
		e = self.lap()
		self.mang(TOK, requests.exceptions.ConnectTimeout("x"))
		cau = "Không kết nối được tới MISA (ConnectTimeout) — hoá đơn chưa được gửi."
		self.assertEqual(self.phat_hanh(e), (502, {"error": cau}))
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.misa_error, bool(r.misa_ref_id)), ("error", cau, True))
		self.assertEqual([(x.ket_qua, x.loi) for x in self.nhat_ky()], [("failed", cau)])

	def test_kv24_sai_mat_khau(self):
		"""KV-24 [≠ nhỏ]: /oauth sai mật khẩu → 500 câu token; dòng `error`, RefID NULL (token lấy TRƯỚC giành tờ), mốc gửi không đổi; 0 POST; nhật ký
		failed không payload; cổng đọc RefID null ⇒ màn hiện "Đẩy lại lên MISA"."""
		e = self.lap()
		a = self.mang({"body": {"error": "invalid_grant", "error_description": "Sai tài khoản hoặc mật khẩu", "status": 401}})
		cau = "MISA token lỗi 401: Sai tài khoản hoặc mật khẩu (invalid_grant)"
		self.assertEqual(self.phat_hanh(e), (500, {"error": cau}))
		self.assertEqual(gon(a), ["POST /oauth"])
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.misa_error, r.misa_ref_id, r.misa_sent_at, r.trang_thai), ("error", cau, None, None, "draft"))
		(nk,) = self.nhat_ky()
		self.assertEqual((nk.nguon, nk.ket_qua, nk.gui_di, nk.loi, nk.hddt), ("publish", "failed", None, cau, e))
		self.assertIsNone(self._doc("owner", select="misa_ref_id", loc=[{"op": "eq", "cot": "id", "gt": e}], mot="one")["misa_ref_id"])

	def test_token_path_khong_lui_ve_oauth(self):
		"""[Soát thiếu 2, =] phát hành dùng `token_path` thẳng (publish/route.ts:329): System Manager xoá trên Desk → 500 "Chưa cấu hình 'Endpoint lấy
		token'…", `error`, không gọi mạng (Làm mới / Thử kết nối thì lùi về /oauth)."""
		frappe.db.set_single_value(CH.TEN, "duong_lay_token", "")
		e = self.lap()
		a = self.mang()
		cau = "Chưa cấu hình 'Endpoint lấy token' (token_path) cho MISA. Vào Cài đặt → Hoá đơn điện tử."
		self.assertEqual(self.phat_hanh(e), (500, {"error": cau}))
		self.assertEqual((a.goi, self.dong(e).misa_status), ([], "error"))

	def test_kv25_cau_hinh_thieu_tat_hong(self):
		"""KV-25 [= (a)–(c)]: chưa lưu / tắt → 400 + misa_error "Chưa cấu hình tài khoản MISA"; thiếu mật khẩu → 400 + "Thiếu username/password
		MISA"; 0 lời gọi, 0 nhật ký, mốc gửi không đổi. (d) khoá site đổi → 500 câu "Không giải mã được credentials MISA (kiểm tra encryption_key…"
		— không chữ tiếng Anh nào trong JSON / misa_error / message_log."""
		from cryptography.fernet import Fernet

		from nppsale.tests.test_misa_mang import _khoa_site

		e = self.lap()
		a = self.mang()
		ca = [("chưa lưu", lambda: frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN), 400,
				"Chưa cấu hình tài khoản hoá đơn điện tử MISA. Vào Cài đặt → Hoá đơn điện tử.", "Chưa cấu hình tài khoản MISA"),
			("tắt", lambda: self.cau_hinh(is_active=False), 400, "Chưa cấu hình tài khoản hoá đơn điện tử MISA. Vào Cài đặt → Hoá đơn điện tử.",
				"Chưa cấu hình tài khoản MISA"),
			("không mật khẩu", lambda: frappe.db.sql("DELETE FROM `__Auth` WHERE `doctype` = %s AND `fieldname` = 'mat_khau'", CH.TEN), 400,
				"Chưa nhập username/password MISA. Vào Cài đặt → Hoá đơn điện tử.", "Thiếu username/password MISA")]
		for ten, lam, ma_mong, cau, loi in ca:
			with self.subTest(ten=ten):
				frappe.db.savepoint("ca")
				lam()
				self.assertEqual(self.phat_hanh(e), (ma_mong, {"error": cau}))
				r = self.dong(e)
				self.assertEqual((r.misa_status, r.misa_error, r.misa_sent_at, r.misa_ref_id), ("error", loi, None, None))
				self.assertEqual((a.goi, self.nhat_ky()), ([], []))
				frappe.db.rollback(save_point="ca")
		n = len(frappe.local.message_log)
		with _khoa_site(Fernet.generate_key().decode()):
			ma, kq = self.phat_hanh(e)
		self.assertEqual(ma, 500)
		self.assertTrue(kq["error"].startswith("Không giải mã được credentials MISA (kiểm tra encryption_key trong site_config.json có thay đổi"),
			kq)
		self.assertEqual(self.dong(e).misa_error, kq["error"])
		self.assertNotIn("Encryption key", kq["error"] + str(frappe.local.message_log[n:]))
		self.assertEqual(len(frappe.local.message_log), n)
		self.assertEqual(a.goi, [])

	def test_kv26a_hd_ban_da_huy(self):
		"""KV-26 (a) [≠ H6]: dòng nháp của HĐ đã huỷ (dòng error / nháp không khoá Huỷ HĐ) → 400 câu của ensureEInvoiceRow; 0 lời gọi; dòng không đổi.
		KV-56 (b): nút "Xuất hoá đơn" của danh sách đơn đẩy dòng của tờ đã huỷ → cùng câu (nppsale phát hành thật)."""
		e = self.lap()
		kq = self._huy()
		self.assertNotIn("error", kq, kq)
		truoc = self.dong(e)
		a = self.mang()
		self.assertEqual(self.phat_hanh(e), (400, {"error": f"Hóa đơn {self.hd} không còn hiệu lực — không phát hành hoá đơn điện tử được."}))
		self.assertEqual((a.goi, self.dong(e), self.nhat_ky()), ([], truoc, []))

	def test_h6_hd_huy_giua_buoc_5_va_9(self):
		"""H6 ở bước giành tờ (khoá HĐ bán `FOR UPDATE`): HĐ bị huỷ sau khi qua bước 5 (đua) → 400, KHÔNG POST, dòng không pending."""
		e = self.lap()
		self.assertNotIn("error", self._huy())
		a = self.mang(TOK)
		with patch.object(M, "_con_hieu_luc", lambda r: (True, "")):
			self.assertEqual(self.phat_hanh(e), (400, {"error": f"Hóa đơn {self.hd} không còn hiệu lực — không phát hành hoá đơn điện tử được."}))
		self.assertEqual(gon(a), ["POST /oauth"])
		self.assertFalse(self.dong(e).misa_status)

	def test_h6_theo_ten_hd_ban(self):
		"""Bước 5 / 9 đúng chữ §4.1.1: `hoa_don_ban` → `docstatus` của Sales Invoice THEO TÊN — không lọc tờ đầu kỳ / ghi có như lập dòng (`doc_hd_ban`):
		dòng chuyển sang ở P8 có thể trỏ tờ đầu kỳ cùng mã (§4.1.2 (a), §9.5); HĐ không còn → không hiệu lực; dòng không gắn HĐ → không kiểm [=]."""
		frappe.db.sql("UPDATE `tabSales Invoice` SET `is_opening` = 'Yes' WHERE `name` = %s", self.hd)
		self.assertIsNone(M.doc_hd_ban(self.hd))
		self.assertEqual(M._hd_ban_hieu_luc(frappe._dict(hoa_don_ban=self.hd)), (True, self.hd))
		self.assertEqual(M._hd_ban_hieu_luc(frappe._dict(hoa_don_ban=self.hd), khoa=True), (True, self.hd))
		self.assertEqual(M._hd_ban_hieu_luc(frappe._dict(hoa_don_ban="khong-co")), (False, "khong-co"))
		self.assertEqual(M._hd_ban_hieu_luc(frappe._dict(hoa_don_ban=None, don_hang=self.don)), (True, ""))
		for docstatus in (0, 2):  # nháp / đã huỷ: không hiệu lực
			frappe.db.sql("UPDATE `tabSales Invoice` SET `docstatus` = %s WHERE `name` = %s", (docstatus, self.hd))
			self.assertEqual(M._hd_ban_hieu_luc(frappe._dict(hoa_don_ban=self.hd)), (False, self.hd), docstatus)

	def test_gianh_to_khoa_hd_ban_roi_dong(self):
		"""Bước 9: khoá dòng HĐ bán `FOR UPDATE` TRƯỚC khoá dòng HĐĐT `FOR UPDATE` rồi mới UPDATE giành tờ (thứ tự khoá như `_huy` — Huỷ HĐ song song
		xếp hàng ở HĐ bán rồi thấy `pending` + RefID ⇒ LOCKED_EINVOICE, không deadlock ngược chiều). (Bài hai kết nối thật: TestHaiKetNoi.)"""
		e = self.lap()
		self.mang(TOK, tra_map())
		goc = frappe.db.sql
		cau = []

		def ghi_lai(q, *a, **k):
			cau.append(" ".join(str(q).split()))
			return goc(q, *a, **k)

		with patch.object(frappe.db, "sql", ghi_lai):
			self.assertEqual(self.phat_hanh(e)[0], 200)
		khoa_hd = [i for i, q in enumerate(cau) if "FROM `tabSales Invoice`" in q and q.endswith("FOR UPDATE")]
		khoa_dong = [i for i, q in enumerate(cau) if "FROM `tabNPP HDDT`" in q and q.endswith("FOR UPDATE")]
		gianh = [i for i, q in enumerate(cau) if q.startswith("UPDATE `tabNPP HDDT` SET `misa_status` = 'pending'")]
		self.assertTrue(khoa_hd and khoa_dong and gianh, cau)
		self.assertLess(khoa_hd[0], khoa_dong[0])
		self.assertLess(khoa_dong[0], gianh[0])

	def test_ket_qua_loi_khong_de_luot_lam_moi_song_song(self):
		"""Kết quả lỗi của lần đẩy (MISA lỗi rõ → error; hết giờ → giữ pending) chỉ ghi khi dòng CÒN `pending`: lượt Làm mới song song đã thấy tờ trên MISA
		(xác nhận đẩy: sent + issued) trong lúc POST đang chờ thì không dán lại lỗi / không hạ trạng thái."""
		for ten_ca, tra in (("MISA lỗi rõ", {"status": 500, "body": "<html>x</html>"}), ("hết giờ", requests.exceptions.ReadTimeout("x"))):
			with self.subTest(ca=ten_ca):
				frappe.db.savepoint("ca")
				e = self.lap()

				def khi_goi(req, e=e):
					if "/v3sainvoice" in req.url:  # lượt Làm mới khác vừa ghi xong (MISA có tờ)
						frappe.db.sql("UPDATE `tabNPP HDDT` SET `misa_status` = 'sent', `trang_thai` = 'issued', `misa_error` = NULL WHERE `name` = %s", e)

				self.mang(TOK, tra, khi_goi=khi_goi)
				self.assertEqual(self.phat_hanh(e)[0], 502)
				r = self.dong(e)
				self.assertEqual((r.misa_status, r.trang_thai, r.misa_error), ("sent", "issued", None))
				frappe.db.rollback(save_point="ca")
				MM.xoa_token_nho()

	def test_loi_truoc_gui_khong_dan_len_to_da_co_so(self):
		"""`ghi_loi_truoc_gui` (cấu hình / giải mã / token hỏng) chỉ dán `error` lên dòng VẪN chưa tới MISA — trống / error, chưa mã tra cứu, chưa số
		([Soát thiếu 2] cùng chốt H23): lượt kéo về song song vừa ghi số giữa bước 4 và bước 6 thì giữ nguyên trạng thái, không câu lỗi."""
		e = self.lap()
		goc = MM.lay_cau_hinh

		def doc_cau_hinh(**kw):
			frappe.db.sql("UPDATE `tabNPP HDDT` SET `misa_status` = 'signed', `misa_inv_no` = '00000999', `misa_inv_series` = '', "
				"`misa_ref_id` = 'r-song-song' WHERE `name` = %s", e)
			frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)  # → "chưa cấu hình"
			return goc(**kw)

		with patch.object(MM, "lay_cau_hinh", doc_cau_hinh):
			self.assertEqual(self.phat_hanh(e, kiem_i2=False), (400, {"error": "Chưa cấu hình tài khoản hoá đơn điện tử MISA. Vào Cài đặt → Hoá đơn điện tử."}))
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.misa_error, r.misa_inv_no), ("signed", None, "00000999"))

	def test_h3_h27_thay_tren_misa_ma_so_dung_to_khac(self):
		"""Bước 10 (H3) / H27 thấy tờ trên MISA mà số MISA cấp đụng (ký hiệu, số) của tờ khác (H13 — như Làm mới) → 409 câu trùng số; dòng GIỮ `pending`
		+ RefID (MISA CÓ tờ ⇒ Huỷ HĐ vẫn khoá — H2; `error` là mở khoá + cổng che RefID — H3b) + câu vào misa_error, không cột MISA nào khác đổi; một
		nhật ký `failed` (H27: lần POST của lượt có đúng một nhật ký — I5). Làm mới báo lại đúng câu 409."""
		dong_hddt(nguoi_mua="F", misa_inv_no="00000123", misa_inv_series="1C26TAA", misa_status="signed", misa_ref_id="ref-f", trang_thai="issued")
		e = self.lap()
		r1 = str(uuid.uuid4())
		frappe.db.set_value("NPP HDDT", e, {"misa_status": "error", "misa_ref_id": r1, "misa_error": "MISA publish lỗi 500: x"},
			update_modified=False)
		cau = "Số HĐĐT 1C26TAA · 00000123 MISA trả về đã có ở một hoá đơn khác trong sổ — kiểm tra trùng trước khi làm mới lại."
		bg = ban_ghi_ky()  # 1C26TAA · 00000123
		a = self.mang(TOK, get_ban_ghi(**bg))
		self.assertEqual(self.phat_hanh(e), (409, {"error": cau}))
		self.assertEqual(gon(a), ["POST /oauth", f"GET /v3sainvoice/?refID={r1}"])
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.misa_error, r.misa_ref_id, r.trang_thai, r.misa_inv_no, r.misa_inv_series, r.misa_last_checked_at,
			r.misa_lookup_code), ("pending", cau, r1, "draft", None, None, None, None))
		(nk,) = self.nhat_ky(hddt=e)
		self.assertEqual((nk.nguon, nk.ket_qua, json.loads(nk.gui_di), nk.loi, json.loads(nk.nhan_ve)["InvNo"]),
			("publish", "failed", {"source": "hoi_truoc_khi_day_lai", "ref_id": r1}, cau, "00000123"))
		self.assertEqual(self._huy()["error"]["message"], "LOCKED_EINVOICE: HĐĐT đang chờ MISA — bấm Làm mới trạng thái trước")
		self.mang(get_ban_ghi(**bg))
		self.assertEqual(self.lam_moi(e), (409, {"error": cau}))
		# H27: POST 401 → /oauth ép → GET thấy tờ (số đụng F) → KHÔNG POST lần 2; một nhật ký failed mang payload lần 1
		e2 = dong_hddt(nguoi_mua="Tờ 2", tien_hang=1000, tien_thue=100, tong_tien=1100)
		a = self.mang({"status": 401, "body": {"message": "Token expired"}}, TOK2, get_ban_ghi(**bg))
		self.assertEqual(self.phat_hanh(e2), (409, {"error": cau}))
		self.assertEqual(gon(a)[:2], ["POST /v3sainvoice", "POST /oauth"])
		self.assertEqual(len(a.goi), 3)
		r = self.dong(e2)
		(nk,) = self.nhat_ky(hddt=e2)
		self.assertEqual((r.misa_status, r.misa_error, r.misa_inv_no, nk.ket_qua, nk.loi, json.loads(nk.gui_di)[0]["RefID"]),
			("pending", cau, None, "failed", cau, r.misa_ref_id))

	def test_h3_thay_tren_misa_ghi_hong_giu_pending(self):
		"""Bước 10 thấy tờ trên MISA mà ghi kết quả hỏng (lỗi khác) → 500; dòng GIỮ `pending` + RefID (MISA có tờ — không dán `error`, không mở khoá Huỷ HĐ);
		Làm mới gỡ được."""
		e = self.lap()
		r1 = str(uuid.uuid4())
		frappe.db.set_value("NPP HDDT", e, {"misa_status": "error", "misa_ref_id": r1, "misa_error": "x"}, update_modified=False)
		self.mang(TOK, get_ban_ghi(**DA_CO, TotalAmount=26020))
		with patch.object(M, "ghi_ket_qua_keo_ve", side_effect=frappe.QueryDeadlockError("deadlock")):
			self.assertEqual(self.phat_hanh(e), (500, {"error": "deadlock"}))
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.misa_ref_id, r.trang_thai), ("pending", r1, "draft"))
		self.assertEqual(self._huy()["error"]["message"], "LOCKED_EINVOICE: HĐĐT đang chờ MISA — bấm Làm mới trạng thái trước")
		self.mang(get_ban_ghi(**DA_CO, TotalAmount=26020))
		self.assertEqual(self.lam_moi(e)[0], 200)
		self.assertEqual((self.dong(e).misa_status, self.dong(e).trang_thai, self.dong(e).misa_error), ("sent", "issued", None))

	def test_kv26b_to_huy_noi_bo_van_day_duoc(self):
		"""KV-26 (b) [=]: tờ `cancelled` (huỷ nội bộ) của HĐ còn hiệu lực → phát hành OK → `issued`, `phat_hanh_luc` GIỮ NULL; có mốc gửi."""
		e = self.lap()
		frappe.db.set_value("NPP HDDT", e, "trang_thai", "cancelled")
		self.mang(TOK, tra_map())
		self.assertEqual(self.phat_hanh(e)[0], 200)
		r = self.dong(e)
		self.assertEqual((r.trang_thai, r.phat_hanh_luc, r.misa_sent_at, r.misa_status), ("issued", None, LUC, "sent"))

	def test_kv27_ghi_ket_qua_hong(self):
		"""KV-27 [≠ — nppsale ngõ cụt]: MISA nhận nhưng ghi kết quả hỏng → 500 success:false + câu "ĐÃ được phát hành… KHÔNG phát hành lại"; dòng còn
		`pending` + RefID (đã commit ở giành tờ), nhật ký success (đã commit). Làm mới → MISA có → sent + issued."""
		e = self.lap()
		self.mang(TOK, tra_map())
		with patch.object(M, "_ghi_ket_qua_phat_hanh", side_effect=frappe.QueryTimeoutError("Lock wait timeout")):
			ma, kq = self.phat_hanh(e)
		self.assertEqual((ma, kq), (500, {"success": False, "error": "Hoá đơn ĐÃ được phát hành trên MISA nhưng hệ thống chưa cập nhật được trạng thái. "
			"KHÔNG phát hành lại — hãy bấm 'Làm mới trạng thái' để đồng bộ.", "misa": {"lookup_code": None, "invoice_url": None}}))
		r = self.dong(e)
		self.assertEqual((r.misa_status, bool(r.misa_ref_id), r.trang_thai), ("pending", True, "draft"))
		self.assertEqual([x.ket_qua for x in self.nhat_ky()], ["success"])
		self.assertEqual(self.phat_hanh(e)[0], 409)
		self.mang(get_ban_ghi(**DA_CO, TotalAmount=26020))
		self.assertEqual(self.lam_moi(e)[0], 200)
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.trang_thai, r.phat_hanh_luc), ("sent", "issued", LUC))

	def _sua_dong_hd(self, vi_tri: int, **kv):
		"""Đổi trường dòng HĐ bán thứ `vi_tri` (bài đọc dòng — canh CỘT nào được đọc, kể cả cột của lõi phải bị bỏ qua)."""
		frappe.db.sql(f"UPDATE `tabSales Invoice Item` SET {', '.join(f'`{k}` = %s' for k in kv)} WHERE `parent` = %s AND `idx` = %s",
			(*kv.values(), self.hd, vi_tri))

	def test_kv28_dong_hang_tu_hd_ban(self):
		"""KV-28 [đo kiem_dong, =]: dòng 1 = 2 Thùng (hệ số 24) × 240.000 @ 10 %; dòng 2 = 3 × 33.333 giảm dòng 1.000 @ 8 % (đơn giá đã giảm + giảm
		dòng ÷ SL → 33.666, AmountOC 100.999, VAT 8.000). Cột lõi `price_list_rate` / `discount_amount` mang số rác — không được đọc. `box` → dòng 1
		quy về Lon (48 × 10.000), tổng không đổi. Hàng đổi (đơn giá 0, giá bảng ở cột lõi) → 0 đ (không lọc — H11)."""
		self._sua_dong_hd(1, uom="Thung", conversion_factor=24, qty=2, rate=240000, npp_giam_dong=0, npp_thue_suat=0.1, price_list_rate=777,
			discount_amount=55)
		self._sua_dong_hd(2, qty=3, rate=33333, npp_giam_dong=1000, npp_thue_suat=0.08, price_list_rate=99999, discount_amount=1000)
		for che_do, dong1 in (("as_sold", ["VTD-P1", "Thung", 2, 240000, 480000, 0, 10, 48000]),
				("box", ["VTD-P1", "Lon", 48, 10000, 480000, 0, 10, 48000])):
			with self.subTest(che_do=che_do):
				frappe.db.savepoint("ca")
				e = self.lap()
				a = self.mang(TOK, tra_map())
				self.assertEqual(self.phat_hanh(e, mode=che_do)[0], 200)
				h = self.payload(a)[0]
				self.assertEqual([[d["InventoryItemCode"], d["UnitName"], d["Quantity"], d["UnitPrice"], d["AmountOC"], d["DiscountAmountOC"],
					d["VATRate"], d["VATAmountOC"]] for d in h["InvoiceDetails"]], [dong1, ["VTD-P2", "Chai", 3, 33666, 100999, 1000, 8, 8000]])
				self.assertEqual((h["TotalSaleAmountOC"], h["TotalDiscountAmountOC"], h["TotalAmountWithoutVATOC"], h["TotalVATAmountOC"],
					h["TotalAmountOC"], h["IsMoreVATRate"], h["IsTaxReduction43"], h["TypeDiscount"]), (580999, 1000, 579999, 56000, 635999, True,
					True, 1))
				frappe.db.rollback(save_point="ca")
				MM.xoa_token_nho()
		self._sua_dong_hd(2, qty=1, rate=0, npp_giam_dong=0, npp_hang_doi=1, npp_thue_suat=0.1, price_list_rate=5000, discount_amount=5000)
		e = self.lap()
		a = self.mang(TOK, tra_map())
		self.assertEqual(self.phat_hanh(e)[0], 200)
		d2 = self.payload(a)[0]["InvoiceDetails"][1]
		self.assertEqual([d2["InventoryItemCode"], d2["Quantity"], d2["UnitPrice"], d2["AmountOC"], d2["DiscountAmountOC"], d2["VATRate"],
			d2["VATAmountOC"]], ["VTD-P2", 1, 0, 0, 0, 10, 0])

	def test_kv28_ten_hang_hien_hanh_va_thu_tu(self):
		"""H18: tên hàng = `Item.item_name` HIỆN HÀNH lúc đẩy; H19: thứ tự theo `idx`; thuế chụp trên DÒNG (đổi thuế mặt hàng không đổi HĐĐT)."""
		frappe.db.set_value("Item", "VTD-P1", {"item_name": "Nuoc ngot VTD (moi)", "npp_thue_suat": 0.1})
		self._sua_dong_hd(1, idx=9)
		e = self.lap()
		a = self.mang(TOK, tra_map())
		self.assertEqual(self.phat_hanh(e)[0], 200)
		self.assertEqual([(d["Description"], d["VATRate"], d["SortOrder"]) for d in self.payload(a)[0]["InvoiceDetails"]],
			[("Dau an VTD", 10, 1), ("Nuoc ngot VTD (moi)", 8, 2)])

	def test_kv29b_to_tay_dong_tong_hop(self):
		"""KV-29 (b) [= đo M4]: tờ tay (không HĐ / đơn) 195.000 + 17.600 → MỘT dòng "Hàng hoá, dịch vụ" / "Lần", VAT 9 % → tổng 212.550 (≠ sổ, như
		nppsale); người mua lấy từ chính dòng HĐĐT."""
		e = dong_hddt(nguoi_mua="Cty C", mst_nguoi_mua="0300000009", dia_chi_nguoi_mua="1 Hai Bà Trưng", tien_hang=195000, tien_thue=17600,
			tong_tien=212600)
		a = self.mang(TOK, tra_map())
		self.assertEqual(self.phat_hanh(e)[0], 200)
		h = self.payload(a)[0]
		(d,) = h["InvoiceDetails"]
		self.assertEqual((d["Description"], d["UnitName"], d["Quantity"], d["UnitPrice"], d["VATRate"], d["VATAmountOC"]),
			("Hàng hoá, dịch vụ", "Lần", 1, 195000, 9, 17550))
		self.assertEqual((h["TotalAmountOC"], h["AccountObjectName"], h["AccountObjectTaxCode"], h["AccountObjectAddress"], h["PaymentMethod"],
			h["ReceiverEmail"]), (212550, "Cty C", "0300000009", "1 Hai Bà Trưng", "Chuyển khoản", ""))

	def test_kv29c_chi_co_don_hang(self):
		"""KV-29 (c) [=]: dòng chỉ có `don_hang` (dữ liệu trước v2b) → dòng Sales Order Item, thuế `Item.npp_thue_suat` HIỆN HÀNH, người mua từ khách
		của đơn (tên / địa chỉ / email xuất HĐ ưu tiên)."""
		frappe.db.set_value("Item", "VTD-P2", "npp_thue_suat", 0.05)
		frappe.db.set_value("Customer", self.kh, {"npp_ten_xuat_hd": "Cty Tap hoa VTD", "npp_dia_chi_xuat_hd": "99 Nguyễn Huệ",
			"npp_email_xuat_hd": "hd@vtd.vn", "npp_hinh_thuc_tt": ""})
		e = dong_hddt(nguoi_mua="khác", don_hang=self.don)
		a = self.mang(TOK, tra_map())
		self.assertEqual(self.phat_hanh(e, poNote="PO-7")[0], 200)
		h = self.payload(a)[0]
		self.assertEqual([(d["InventoryItemCode"], d["UnitName"], d["Quantity"], d["UnitPrice"], d["VATRate"]) for d in h["InvoiceDetails"]],
			[("VTD-P1", "Lon", 2, 9500, 8), ("VTD-P2", "Chai", 1, 5000, 5)])
		self.assertEqual((h["AccountObjectName"], h["AccountObjectAddress"], h["ReceiverEmail"], h["ContactName"], h["PaymentMethod"]),
			("Cty Tap hoa VTD", "99 Nguyễn Huệ", "hd@vtd.vn", "Cty Tap hoa VTD, PO-7", "Chuyển khoản"))

	def test_doc_dong_hang_hong(self):
		"""Bước 7: đọc dòng hàng hỏng → 500 câu "CHƯA phát hành" của nhánh; dòng KHÔNG đổi (nppsale kẹt `pending`); không gọi MISA."""
		e = self.lap()
		a = self.mang()
		goc = M._dong_chung_tu
		with patch.object(M, "_dong_chung_tu", side_effect=frappe.QueryTimeoutError("Lock wait timeout exceeded")):
			ma, kq = self.phat_hanh(e)
		self.assertEqual((ma, kq), (500, {"error": "Không đọc được hóa đơn bán để lập hoá đơn điện tử. CHƯA phát hành, vui lòng thử lại: "
			"Lock wait timeout exceeded"}))
		e2 = dong_hddt(nguoi_mua="Đơn cũ", don_hang=self.don)
		with patch.object(M, "_dong_chung_tu", side_effect=frappe.QueryTimeoutError("x")):
			self.assertEqual(self.phat_hanh(e2), (500, {"error": "Không đọc được thông tin đơn hàng để lập hoá đơn. CHƯA phát hành, vui lòng thử lại: x"}))
		self.assertEqual((a.goi, self.dong(e).misa_status, self.dong(e2).misa_status), ([], "", ""))
		self.assertIs(M._dong_chung_tu, goc)

	def test_kv30_commit_truoc_khi_goi_misa(self):
		"""KV-30 (a) [≠ BP §7.3-10]: chuỗi sự kiện `POST /oauth` → commit (giành tờ) → `POST /v3sainvoice` (lúc ấy dòng ĐÃ pending + RefID) → commit
		(nhật ký) → commit (kết quả). Không khoá dòng nào bị giữ trong lúc chờ HTTP: lúc POST bay đi, giao dịch vừa commit không còn khoá."""
		e = self.lap()
		su_kien = []

		def khi_goi(req):
			su_kien.append(f"{req.method} {req.url[len(API):].split('?')[0]}")
			if "/v3sainvoice" in req.url:
				r = frappe.db.sql("SELECT `misa_status`, `misa_ref_id` FROM `tabNPP HDDT` WHERE `name` = %s", e, as_dict=True)[0]
				su_kien.append(f"dòng {r.misa_status} {bool(r.misa_ref_id)}")

		self.mang(TOK, tra_map(), khi_goi=khi_goi)
		trong_test = frappe.flags.in_test
		frappe.flags.in_test = False
		try:
			with patch.object(frappe.local.db, "commit", side_effect=lambda *a, **k: su_kien.append("commit")):
				self.assertEqual(self.phat_hanh(e)[0], 200)
		finally:
			frappe.flags.in_test = trong_test
		self.assertEqual(su_kien, ["POST /oauth", "commit", "POST /v3sainvoice", "dòng pending True", "commit", "commit"])

	def test_i11_to_da_co_so_khong_bao_gio_post(self):
		"""I11: không POST /v3sainvoice nào cho dòng TRƯỚC lời gọi đã có `misa_inv_no` hoặc `misa_lookup_code` (H23) — cả khi `misa_status` trống /
		error / signed."""
		for kv in ({"misa_inv_no": "00000456", "misa_inv_series": "1C26TAA"}, {"misa_inv_no": "00000457", "misa_status": "error",
				"misa_ref_id": "r-457"}, {"misa_lookup_code": "TX7"}, {"misa_lookup_code": "TX8", "misa_status": "error", "misa_ref_id": "r-8"}):
			with self.subTest(kv=kv):
				e = dong_hddt(**kv)
				a = self.mang()
				ma, kq = self.phat_hanh(e)
				self.assertEqual((ma, kq["cached"], kq["inv_no"], kq["lookup_code"]), (200, True, kv.get("misa_inv_no"), kv.get("misa_lookup_code")))
				self.assertEqual(a.goi, [])

	def test_gianh_to_dua_voi_lam_moi(self):
		"""Bước 9 đọc dòng CÓ KHOÁ: bản đọc thường ở bước 3 cũ (một lượt khác vừa đưa tờ tới MISA) → 409, không POST, không đè trạng thái."""
		e = self.lap()
		goc = M.doc_dong_hddt

		def doc(ten, *, khoa=False):
			r = goc(ten, khoa=khoa)
			if khoa:  # lượt khác đã ghi xong giữa bước 3 và 9
				frappe.db.sql("UPDATE `tabNPP HDDT` SET `misa_status` = 'sent', `misa_ref_id` = 'R-khac' WHERE `name` = %s", ten)
				r = goc(ten, khoa=True)
			return r

		a = self.mang(TOK)
		with patch.object(M, "doc_dong_hddt", doc):
			self.assertEqual(self.phat_hanh(e), (409, {"error": "Hoá đơn đang được xử lý hoặc đã phát hành. Thử lại sau giây lát."}))
		self.assertEqual(gon(a), ["POST /oauth"])
		self.assertEqual((self.dong(e).misa_status, self.dong(e).misa_ref_id), ("sent", "R-khac"))
		e2 = dong_hddt(nguoi_mua="Tờ có số giữa chừng", tien_hang=1000, tien_thue=100, tong_tien=1100)

		def doc_so(ten, *, khoa=False):  # H23 ở chốt giành tờ: số vừa được ghi (trạng thái vẫn trống) → không giành
			if khoa:
				frappe.db.sql("UPDATE `tabNPP HDDT` SET `misa_inv_no` = '00000888', `misa_inv_series` = '' WHERE `name` = %s", ten)
			return goc(ten, khoa=khoa)

		a = self.mang()
		with patch.object(M, "doc_dong_hddt", doc_so):
			self.assertEqual(self.phat_hanh(e2, kiem_i2=False)[0], 409)
		self.assertEqual((a.goi, self.dong(e2).misa_status, self.dong(e2).misa_ref_id), ([], "", None))

	def test_loi_khong_luong_sau_gianh_to(self):
		"""Bước 15: ngoại lệ lọt sau khi giành tờ — chưa gửi → `error` + câu, nhật ký failed; đã gửi → giữ `pending`; 500 câu."""
		e = self.lap()
		a = self.mang(TOK)
		with patch.object(M, "dung_payload", side_effect=ValueError("payload hỏng")):
			self.assertEqual(self.phat_hanh(e), (500, {"error": "payload hỏng"}))
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.misa_error, bool(r.misa_ref_id)), ("error", "payload hỏng", True))
		self.assertEqual([(x.ket_qua, x.loi) for x in self.nhat_ky()], [("failed", "payload hỏng")])
		self.assertEqual(gon(a), ["POST /oauth"])
		e2 = dong_hddt(nguoi_mua="Tờ 2", tien_hang=1000, tien_thue=100, tong_tien=1100)
		self.mang(tra_map())
		with patch.object(MM, "day_hd", side_effect=RuntimeError("đứt giữa chừng")):
			self.assertEqual(self.phat_hanh(e2), (500, {"error": "đứt giữa chừng"}))
		self.assertEqual(self.dong(e2).misa_status, "pending")
		self.assertTrue(frappe.db.exists("Error Log", {"method": "HĐĐT MISA: phát hành lỗi sau khi giành tờ"}))
		# H27 thấy tờ trên MISA nhưng ghi kéo về hỏng (lỗi khác trùng số) → 500; lần POST ấy có ĐÚNG MỘT nhật ký failed mang payload (I5)
		e3 = dong_hddt(nguoi_mua="Tờ 3", tien_hang=1000, tien_thue=100, tong_tien=1100)
		a = self.mang({"status": 401, "body": {"message": "Token expired"}}, TOK2, get_ban_ghi(**DA_CO, TotalAmount=1100))
		with patch.object(M, "ghi_ket_qua_keo_ve", side_effect=RuntimeError("ghi hỏng")):
			self.assertEqual(self.phat_hanh(e3), (500, {"error": "ghi hỏng"}))
		self.assertEqual([g for g in gon(a) if g == "POST /v3sainvoice"], ["POST /v3sainvoice"])
		(nk,) = self.nhat_ky(hddt=e3)
		self.assertEqual((nk.ket_qua, nk.loi, json.loads(nk.gui_di)[0]["RefID"]), ("failed", "ghi hỏng", self.dong(e3).misa_ref_id))
		self.assertEqual(self.dong(e3).misa_status, "pending")  # đã gửi → giữ pending (Làm mới gỡ)


class TestPhatHanhNhomK(_NenPhatHanh):
	"""Ca phát hành của Nhóm K: KV-51 (mất RefID — H23), KV-52 (tờ tay bị từ chối — H24), KV-54 (H27), KV-55 (H25)."""

	def test_kv51_to_mat_refid_khong_bi_day_nhap_thu_hai(self):
		"""KV-51 [≠ H23]: dòng nhập mất RefID (có số, RefID NULL, signed) → 200 cached, 0 lời gọi, 0 nhật ký, không đổi (kể cả modified); biến thể
		`error` → cached (vế a' đứng trước d). Làm mới → 409 MẤT RefID. System Manager gán tay RefID trên Desk (validate cho — đang trống) → Làm mới
		hỏi `GET ?refID=goc-9`."""
		g2 = dong_hddt(trang_thai="issued", misa_inv_no="00000456", misa_inv_series="1C26TAA", misa_status="signed",
			misa_note="MẤT RefID: cột misa_invoice_id cũ đã bị số hoá đơn ghi đè (mig 099).")
		g3 = dong_hddt(misa_inv_no="00000457", misa_inv_series="1C26TAA", misa_status="error")
		a = self.mang()
		for ten, so in ((g2, "00000456"), (g3, "00000457")):
			truoc = self.dong(ten)
			self.assertEqual(self.phat_hanh(ten), (200, {"success": True, "cached": True, "lookup_code": None, "ref_id": None, "inv_no": so,
				"invoice_url": None}))
			self.assertEqual(self.dong(ten), truoc)
		self.assertEqual((a.goi, self.nhat_ky()), ([], []))
		ma, kq = self.lam_moi(g2)
		self.assertEqual((ma, kq), (409, {"error": "Hoá đơn này đã MẤT RefID (dữ liệu cũ trước bản vá tách khoá) nên không tra cứu lại được trên "
			"MISA. Cần gán tay RefID hoặc phát hành lại — xem khám sổ HĐĐT (bench --site <site> execute nppsale.kham_so.hddt)."}))
		d = frappe.get_doc("NPP HDDT", g2)
		d.misa_ref_id = "goc-9"
		d.save(ignore_permissions=True)
		a = self.mang(TOK, get_ban_ghi(InvNo="00000456", InvSeries="1C26TAA", PublishStatus=3, EInvoiceStatus=1, TotalAmount=0))
		self.assertEqual(self.lam_moi(g2)[0], 200)
		self.assertEqual(gon(a), ["POST /oauth", "GET /v3sainvoice/?refID=goc-9"])
		self.assertTrue(self.dong(g2).misa_note.startswith("MẤT RefID"))  # H7: dòng cũ ở lại làm vết

	def test_kv52_sua_to_tay_bi_misa_tu_choi(self):
		"""KV-52 [≠ H24]: tờ tay bị MISA từ chối (error, RefID R) → KT sửa MST qua cổng (1 dòng, RefID giữ) → đẩy lại: GET không có → POST CÙNG RefID
		với MST mới → sent. Biến thể: `pending` → sửa 0 dòng; `issued` → 0 dòng; CHU xoá lúc `error` → P0001."""
		t = dong_hddt(nguoi_mua="Cty C", mst_nguoi_mua="0300000009", tien_hang=100000, tien_thue=10000, tong_tien=110000)
		tu_choi = {"body": {"success": True, "data": json.dumps({"R": {"Data": None, "ErrorMessage": "Mã số thuế người mua không hợp lệ",
			"ErrorCode": ["InvalidBuyerTaxCode"], "Success": False}}, ensure_ascii=False)}}
		self.mang(TOK, tu_choi)
		self.assertEqual(self.phat_hanh(t)[0], 502)
		r = self.dong(t)
		self.assertEqual((r.misa_status, r.trang_thai, bool(r.misa_ref_id)), ("error", "draft", True))
		ref = r.misa_ref_id
		frappe.db.savepoint("xoa")
		self.assertEqual(self._loi(self._ghi("owner", "delete", loc=[{"op": "eq", "cot": "id", "gt": t}], select="id")),
			("P0001", "Chỉ xoá được hoá đơn điện tử nháp chưa gửi MISA."))
		frappe.db.rollback(save_point="xoa")
		kq = self._ghi("accountant", "update", {"customer_tax_code": "0300000001"}, loc=[{"op": "eq", "cot": "id", "gt": t}], select="id")
		self.assertEqual(len(kq["data"]), 1, kq)
		self.assertEqual((self.dong(t).mst_nguoi_mua, self.dong(t).misa_ref_id), ("0300000001", ref))
		a = self.mang(RONG, tra_map())
		self.assertEqual(self.phat_hanh(t)[0], 200)
		self.assertEqual(gon(a), [f"GET /v3sainvoice/?refID={ref}", "POST /v3sainvoice"])
		h = self.payload(a)[0]
		self.assertEqual((h["RefID"], h["AccountObjectTaxCode"]), (ref, "0300000001"))
		self.assertEqual(self.dong(t).misa_status, "sent")
		kq = self._ghi("accountant", "update", {"customer_tax_code": "0300000002"}, loc=[{"op": "eq", "cot": "id", "gt": t}], select="id")
		self.assertEqual(kq["data"], [])  # issued
		frappe.db.set_value("NPP HDDT", t, {"trang_thai": "draft", "misa_status": "pending"})
		kq = self._ghi("accountant", "update", {"customer_tax_code": "0300000002"}, loc=[{"op": "eq", "cot": "id", "gt": t}], select="id")
		self.assertEqual(kq["data"], [])  # pending

	def test_kv54_thu_lai_post_hoi_misa_truoc(self):
		"""KV-54 [≠ H27]: POST 400 "…token mismatch" (lỗi xác thực theo thân) → /oauth ép → GET ?refID=R không có → POST lại → 400 ⇒ 502, `error`.
		Biến thể: GET thấy tờ → KHÔNG POST lần 2; sent + issued, misa_error NULL; 200 cached; nhật ký success với payload lần 1 + bản ghi GET."""
		loi = {"status": 400, "body": {"message": "InvalidInvoiceTemplate token mismatch"}}
		e = self.lap()
		a = self.mang(TOK, loi, TOK2, RONG, loi)
		self.assertEqual(self.phat_hanh(e), (502, {"error": "MISA publish lỗi 400: InvalidInvoiceTemplate token mismatch"}))
		ref = self.dong(e).misa_ref_id
		self.assertEqual(gon(a), ["POST /oauth", "POST /v3sainvoice", "POST /oauth", f"GET /v3sainvoice/?refID={ref}", "POST /v3sainvoice"])
		self.assertEqual(self.dong(e).misa_status, "error")
		self.assertEqual([x.ket_qua for x in self.nhat_ky()], ["failed"])
		e2 = dong_hddt(nguoi_mua="Tờ 2", tien_hang=200000, tien_thue=12600, tong_tien=212600)
		MM.xoa_token_nho()
		a = self.mang(TOK, loi, TOK2, lambda req: get_ban_ghi(RefID=req.url.split("refID=")[1], **DA_CO, TotalAmount=212600))
		ma, kq = self.phat_hanh(e2)
		r = self.dong(e2)
		self.assertEqual((ma, kq), (200, {"success": True, "cached": True, "lookup_code": None, "ref_id": r.misa_ref_id, "inv_no": None,
			"invoice_url": None}))
		self.assertEqual(gon(a), ["POST /oauth", "POST /v3sainvoice", "POST /oauth", f"GET /v3sainvoice/?refID={r.misa_ref_id}"])
		self.assertEqual((r.misa_status, r.trang_thai, r.misa_error, r.phat_hanh_luc), ("sent", "issued", None, LUC))
		nk = self.nhat_ky(hddt=e2)
		self.assertEqual([(x.ket_qua, x.loi) for x in nk], [("success", "MISA đã có hoá đơn với RefID này — không đẩy lại.")])
		self.assertEqual(json.loads(nk[0].gui_di), json.loads(a.goi[1][3]))
		self.assertEqual(json.loads(nk[0].nhan_ve)["TotalAmount"], 212600)

	def test_kv56_hai_dong_mot_don_sau_sua_hd(self):
		"""KV-56 [= trừ H6] — phần route (phần cổng: test_cong_hddt.TestKv56HaiDongMotDon). SO có E10 (`draft`, `error` + RefID — tờ cũ) → Sửa HĐ (được —
		vế khoá không gồm `error`) ra HĐ mới. (b) Chỉ có E10: nút "Xuất hoá đơn" của danh sách đơn đẩy E10 → 400 H6, 0 lời gọi (nppsale phát hành E10 cho
		HĐ đã huỷ). Màn HĐ bán mới bấm Phát hành → ensureEInvoiceRow lập E11 → sent. (a) danh sách đơn (`in(order_id)` không order → invMap = dòng về sau
		= E11) bấm lại → 200 cached; (c) chi tiết đơn → ensureEInvoiceRow(HĐ mới) tìm ra E11 → cached. 0 lời gọi ở các lượt cached; E10 không đổi."""
		r10 = str(uuid.uuid4())
		e10 = dong_hddt(hoa_don_ban=self.hd, don_hang=self.don, misa_status="error", misa_ref_id=r10, misa_error="MISA từ chối hoá đơn: …")
		kq = self._sua()
		self.assertNotIn("error", kq, kq)
		hd_moi = kq["data"][0]["invoice_id"]
		truoc10 = self.dong(e10)
		a = self.mang()
		self.assertEqual(self.phat_hanh(e10), (400, {"error": f"Hóa đơn {self.hd} không còn hiệu lực — không phát hành hoá đơn điện tử được."}))
		self.assertEqual(a.goi, [])
		e11 = self._ghi("owner", "insert", {"sales_invoice_id": hd_moi, "order_id": self.don, "customer_name": "x", "status": "draft"}, select="id",
			mot="one")["data"]["id"]
		self.mang(TOK, tra_map())
		self.assertEqual(self.phat_hanh(e11)[0], 200)
		r11 = self.dong(e11)
		self.assertEqual((r11.hoa_don_ban, r11.don_hang, r11.misa_status, r11.trang_thai), (hd_moi, self.don, "sent", "issued"))
		cached = (200, {"success": True, "cached": True, "lookup_code": None, "ref_id": r11.misa_ref_id, "inv_no": None, "invoice_url": None})
		a = self.mang()
		inv_map = {}
		for x in self._doc("owner", select="id, order_id, misa_status", loc=[{"op": "in", "cot": "order_id", "gt": [self.don]}]):
			inv_map[x["order_id"]] = x
		self.assertEqual(inv_map[self.don]["id"], e11)
		self.assertEqual(self.phat_hanh(inv_map[self.don]["id"]), cached)
		tim = self._doc("owner", select="id", loc=[{"op": "eq", "cot": "sales_invoice_id", "gt": hd_moi}], mot="maybe")
		self.assertEqual(self.phat_hanh(tim["id"]), cached)
		self.assertEqual((a.goi, self.dong(e10)), ([], truoc10))

	def test_kv55_khong_lo_token_qua_cau_loi_oauth(self):
		"""KV-55 [≠ H25]: /oauth trả token dưới khoá lạ → 500 câu "không thấy access_token… Raw:" đã CHE; misa_error cùng câu; quét I6 với chuỗi token."""
		e = self.lap()
		self.mang({"body": '{"Data":{"AccessToken":"TOKEN-GIA-123"},"expires_in":3600}'})  # thân nguyên văn (JSON gọn như MISA trả)
		cau = 'MISA token: không thấy access_token trong response. Raw: {"Data":{"AccessToken":"***"},"expires_in":3600}'
		self.assertEqual(self.phat_hanh(e), (500, {"error": cau}))
		self.assertEqual(self.dong(e).misa_error, cau)
		self._i6("TOKEN-GIA-123")


# =====================================================================================================================================
# Nhóm D — làm mới (§4.3) + đánh dấu tờ gốc (§4.7) + ghi kéo về (§4.8)
# =====================================================================================================================================
def ban_ghi_ky(**them) -> dict:
	"""Bản ghi MISA sau khi kế toán ký (KV-31) — tiền = sổ của `self.hd` (26.020)."""
	return {"InvNo": "00000123", "InvSeries": "1C26TAA", "InvDate": "2026-11-15T00:00:00", "PublishStatus": 3, "EInvoiceStatus": 1,
		"TransactionID": "TX1", "InvoiceCode": "M1-26-XYZ", "TotalAmount": 26020, "TotalAmountWithoutVAT": 0, "TotalVATAmount": 0, **them}


class TestLamMoi(_NenPhatHanh):
	def _da_gui(self, e: str | None = None, **kv) -> tuple[str, str]:
		"""Dòng của HĐ bán đã đẩy (issued / sent + RefID) — như sau KV-15."""
		e = e or self.lap()
		ref = kv.pop("misa_ref_id", None) or str(uuid.uuid4())
		frappe.db.set_value("NPP HDDT", e, {"trang_thai": "issued", "phat_hanh_luc": LUC, "misa_status": "sent", "misa_ref_id": ref,
			"misa_sent_at": LUC, **kv}, update_modified=False)
		return e, ref

	def test_kv31_sau_khi_ke_toan_ky(self):
		"""KV-31 [=]: số / ký hiệu / mã tra cứu / mã CQT / quan hệ / ngày / signed / mốc hỏi; `misa_note` không đổi; link / ký / phát hành VẪN NULL (kéo
		về không bao giờ điền); `tim_kd` có số; `modified` không đổi; 0 nhật ký (không ghi chú); Huỷ HĐ → LOCKED_EINVOICE "đã phát hành". Đơn vị
		có mã: `…/v3sainvoice/code/?refID=`."""
		e, ref = self._da_gui()
		truoc = self.dong(e)
		self.luc = LUC + datetime.timedelta(hours=1)
		a = self.mang(TOK, get_ban_ghi(**ban_ghi_ky()))
		ma, kq = self.lam_moi(e)
		self.assertEqual((ma, kq), (200, {"success": True, "misa": {"InvNo": "00000123", "TransactionID": "TX1", "PublishStatus": 3,
			"EInvoiceStatus": 1, "relation": "new", "status": "signed", "notes": [], "original_marked_replaced": None}}))
		self.assertEqual(gon(a), ["POST /oauth", f"GET /v3sainvoice/?refID={ref}"])
		self.assertEqual(hd_app(a.goi[1][2]), [("Authorization", "Bearer T1"), ("TaxCode", MST), ("Content-Type", "application/json")])
		r = self.dong(e)
		self.assertEqual((r.misa_inv_no, r.misa_inv_series, r.misa_lookup_code, r.misa_invoice_code, r.misa_relation, r.misa_inv_date,
			r.misa_status, r.misa_last_checked_at, r.misa_ref_id), ("00000123", "1C26TAA", "TX1", "M1-26-XYZ", "new", datetime.date(2026, 11, 15),
			"signed", self.luc, ref))
		self.assertEqual((r.misa_note, r.misa_signed_at, r.misa_published_at, r.misa_invoice_url, r.modified),
			(truoc.misa_note, None, None, None, truoc.modified))
		self.assertIn("00000123 123", r.tim_kd)
		self.assertEqual(self.nhat_ky(), [])
		self.assertEqual(self._huy()["error"]["message"], "LOCKED_EINVOICE: hóa đơn đã phát hành hóa đơn điện tử")
		frappe.db.set_single_value(CH.TEN, "misa_is_invoice_with_code", 1)
		a = self.mang(get_ban_ghi(**ban_ghi_ky()))
		self.assertEqual(self.lam_moi(e)[0], 200)
		self.assertEqual(gon(a), [f"GET /v3sainvoice/code/?refID={ref}"])

	def test_kv32_lam_moi_ba_lan(self):
		"""KV-32 [=] — chốt Gotcha #1: ba lần đều hỏi bằng RefID (không bao giờ bằng số / mã tra cứu); chỉ mốc hỏi đổi."""
		e, ref = self._da_gui()
		a = self.mang(TOK, *[get_ban_ghi(**ban_ghi_ky())] * 3)
		ket = []
		for i in range(3):
			self.luc = LUC + datetime.timedelta(minutes=i + 1)
			ket.append(self.lam_moi(e))
			r = self.dong(e)
			self.assertEqual((r.misa_ref_id, r.misa_last_checked_at), (ref, self.luc))
		self.assertEqual(gon(a), ["POST /oauth"] + [f"GET /v3sainvoice/?refID={ref}"] * 3)
		self.assertEqual(ket[0], ket[1])
		self.assertEqual(ket[1], ket[2])

	def test_kv33_khong_tra_duoc(self):
		"""KV-33 (a) [≠ đuôi câu] mất RefID → 409; (b) [=] nháp chưa đẩy → 400; (c) [=] MISA không có (tờ sent) → 404, dòng không đổi; (d) [=] GET 401 →
		502, không lấy token mới; (e) [=] NVBH / kho → 403 "Không có quyền"; thiếu invoiceId → 400; không có → 404. 0 lời gọi ở (a)(b)(e)."""
		a = self.mang()
		mat = dong_hddt(misa_inv_no="00000456", misa_inv_series="1C26TAA", misa_status="signed", trang_thai="issued", misa_lookup_code="TX-cu")
		self.assertEqual(self.lam_moi(mat)[0], 409)
		nhap = self.lap()
		self.assertEqual(self.lam_moi(nhap), (400, {"error": "HD chưa đẩy lên MISA — không có RefID để tra cứu."}))
		for nguoi in ("sales_a", "warehouse", None):
			self.assertEqual(self.lam_moi(nhap, nguoi), (403, {"error": "Không có quyền"}))
		self.assertEqual(self.goi("accountant", M.lam_moi, {}), (400, {"error": "Thiếu invoiceId"}))
		self.assertEqual(self.goi("accountant", M.lam_moi, "abc"), (400, {"error": "Thiếu invoiceId"}))
		self.assertEqual(self.lam_moi("khong-co"), (404, {"error": "Không tìm thấy HD"}))
		self.assertEqual(a.goi, [])
		e, ref = self._da_gui(misa_sent_at=LUC - datetime.timedelta(days=1))  # gửi đã lâu: H5 chỉ áp cho tờ `pending`, tờ `sent` không bị hạ
		truoc = self.dong(e)
		self.mang(TOK, RONG)
		self.assertEqual(self.lam_moi(e), (404, {"error": "MISA không trả về dữ liệu HD."}))
		self.assertEqual(self.dong(e), truoc)
		a = self.mang({"status": 401, "body": {"message": "Unauthorized"}})
		self.assertEqual(self.lam_moi(e), (502, {"error": "Lấy HD lỗi 401: Unauthorized"}))
		self.assertEqual(gon(a), [f"GET /v3sainvoice/?refID={ref}"])  # token từ RAM, không /oauth lại
		self.assertEqual(self.dong(e), truoc)

	def test_cau_hinh_lam_moi(self):
		"""Chưa lưu → 400 "Chưa cấu hình MISA"; `dang_dung = 0` KHÔNG chặn [=]; khoá site đổi → 500 câu tiếng Việt [ĐX]."""
		from cryptography.fernet import Fernet

		from nppsale.tests.test_misa_mang import _khoa_site

		e, _ref = self._da_gui()
		self.cau_hinh(is_active=False)
		self.mang(TOK, get_ban_ghi(**ban_ghi_ky()))
		self.assertEqual(self.lam_moi(e)[0], 200)
		with _khoa_site(Fernet.generate_key().decode()):
			self.assertEqual(self.lam_moi(e), (500, {"error": "Không giải mã được tài khoản MISA — khoá mã hoá của site (encryption_key trong "
				"site_config.json) đã đổi so với lúc lưu cấu hình?"}))
		frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)
		self.assertEqual(self.lam_moi(e), (400, {"error": "Chưa cấu hình MISA"}))

	def test_kv34_ban_thay_the_danh_dau_to_goc(self):
		"""KV-34 [= trừ H7]: làm mới bản THAY THẾ T (OrgRefID goc-1) → T `replacement` + `signed`; tờ gốc G `replaced` / `replaced` + THÊM dòng ghi
		chú (giữ dòng "MẤT RefID"); trả `original_marked_replaced = G`. Lần hai → G không đổi. Bản ĐIỀU CHỈNH (EInvoiceStatus 4) → tờ gốc không đổi."""
		g = dong_hddt(misa_ref_id="goc-1", misa_status="signed", misa_inv_no="00000100", misa_inv_series="1C26TAA", trang_thai="issued",
			misa_note="MẤT RefID: …")
		t, _ref = self._da_gui()
		bg = {"InvNo": "00000124", "InvSeries": "1C26TAA", "PublishStatus": 3, "EInvoiceStatus": 3, "OrgRefID": "goc-1", "TotalAmount": 26020}
		self.mang(TOK, get_ban_ghi(**bg), get_ban_ghi(**bg))
		ma, kq = self.lam_moi(t)
		self.assertEqual((ma, kq["misa"]["relation"], kq["misa"]["status"], kq["misa"]["original_marked_replaced"]),
			(200, "replacement", "signed", g))
		r = self.dong(t)
		self.assertEqual((r.misa_relation, r.misa_org_ref_id, r.misa_status), ("replacement", "goc-1", "signed"))
		rg = self.dong(g)
		self.assertEqual((rg.misa_status, rg.misa_relation, rg.misa_note), ("replaced", "replaced", "MẤT RefID: …\nĐã bị thay thế bởi một hoá đơn "
			f"khác trên MISA (phát hiện qua OrgRefID của tờ thay thế, id nội bộ {t}). Hết hiệu lực — KHÔNG kê khai tờ này."))
		self.assertEqual(self.lam_moi(t)[1]["misa"]["original_marked_replaced"], None)
		self.assertEqual(self.dong(g), rg)
		g2 = dong_hddt(misa_ref_id="goc-2", misa_status="signed", misa_inv_no="00000101", misa_inv_series="1C26TAA", trang_thai="issued")
		t2, _ref2 = self._da_gui(dong_hddt(nguoi_mua="Điều chỉnh", tong_tien=-5000))
		truoc = self.dong(g2)
		self.mang(get_ban_ghi(InvNo="00000125", InvSeries="1C26TAA", PublishStatus=3, EInvoiceStatus=4, OrgRefID="goc-2", TotalAmount=-5000))
		ma, kq = self.lam_moi(t2)
		self.assertEqual((ma, kq["misa"]["relation"], kq["misa"]["original_marked_replaced"]), (200, "adjustment", None))
		self.assertEqual(kq["misa"]["notes"], ["Hoá đơn ĐIỀU CHỈNH mang số chênh, không phải tổng tiền — không so với sổ."])
		self.assertEqual(self.dong(g2), truoc)
		nk = self.nhat_ky(nguon="refresh")  # có ghi chú → một nhật ký refresh [BP]
		self.assertEqual([(json.loads(x.gui_di), x.loi, x.misa_inv_no, x.hddt) for x in nk], [({"source": "refresh", "ref_id": _ref2},
			"Hoá đơn ĐIỀU CHỈNH mang số chênh, không phải tổng tiền — không so với sổ.", "00000125", t2)])

	def test_kv35_to_treo_ma_misa_khong_co(self):
		"""KV-35 [≠ H5]: `pending` gửi 5 phút trước, MISA không có → 404, giữ pending (MISA có thể chưa ghi xong); 11 phút → 404 + `error` + câu "lượt
		đẩy trước chưa tới MISA" + mốc hỏi; cổng che RefID (H3b) ⇒ màn hiện "Đẩy lại lên MISA"."""
		e, ref = self._da_gui(trang_thai="draft", misa_status="pending", misa_sent_at=LUC - datetime.timedelta(minutes=5))
		self.mang(TOK, RONG, RONG)
		self.assertEqual(self.lam_moi(e), (404, {"error": "MISA không trả về dữ liệu HD."}))
		self.assertEqual((self.dong(e).misa_status, self.dong(e).misa_last_checked_at), ("pending", None))
		self.assertFalse(M.xu_ly_misa_khong_co(e, LUC))  # hàm dùng chung với vòng quét: chưa quá 10 phút → không đổi
		frappe.db.set_value("NPP HDDT", e, "misa_sent_at", LUC - datetime.timedelta(minutes=11), update_modified=False)
		self.assertEqual(self.lam_moi(e), (404, {"error": "MISA không trả về dữ liệu HD."}))
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.misa_error, r.misa_last_checked_at, r.misa_ref_id), ("error", "MISA không có hoá đơn với RefID này — "
			"lượt đẩy trước chưa tới MISA. Bấm Phát hành để đẩy lại (dùng lại RefID cũ).", LUC, ref))
		self.assertIsNone(self._doc("owner", select="misa_ref_id", loc=[{"op": "eq", "cot": "id", "gt": e}], mot="one")["misa_ref_id"])

	def test_kv36_trung_so_khi_keo_ve(self):
		"""KV-36 [≠ H13, §1.6]: tờ F đã giữ (1C26TAA, 00000123); làm mới E, MISA trả đúng cặp ấy → 409 câu trùng số, E KHÔNG đổi gì (nppsale 200, sổ
		không đổi); F giữ ('', '123') → E vẫn ghi số MISA + ghi chú trùng sau chuẩn hoá (không đổi trạng thái vì trùng)."""
		e, _ref = self._da_gui()
		f = dong_hddt(nguoi_mua="F", misa_inv_no="00000123", misa_inv_series="1C26TAA", misa_status="signed", misa_ref_id="ref-f",
			trang_thai="issued")
		truoc = self.dong(e)
		self.mang(TOK, get_ban_ghi(**ban_ghi_ky()), get_ban_ghi(**ban_ghi_ky()))
		self.assertEqual(self.lam_moi(e), (409, {"error": "Số HĐĐT 1C26TAA · 00000123 MISA trả về đã có ở một hoá đơn khác trong sổ — kiểm tra trùng "
			"trước khi làm mới lại."}))
		self.assertEqual(self.dong(e), truoc)
		frappe.db.set_value("NPP HDDT", f, {"misa_inv_no": "123", "misa_inv_series": ""}, update_modified=False)
		ma, kq = self.lam_moi(e)
		ghi_chu = f"Số HĐĐT 00000123 trùng (sau chuẩn hoá) với hoá đơn {f} — cần kiểm tra."
		self.assertEqual((ma, kq["misa"]["status"], kq["misa"]["notes"]), (200, "signed", [ghi_chu]))
		r = self.dong(e)
		self.assertEqual((r.misa_inv_no, r.misa_inv_series, r.misa_note, r.misa_status), ("00000123", "1C26TAA", ghi_chu, "signed"))

	def test_kv53_ngay_khong_co_that(self):
		"""KV-53 [≠ H26]: InvDate 2026-02-30 → 200; signed + số + ký hiệu ghi, `misa_inv_date` NULL, mốc hỏi ghi, THÊM ghi chú; `notes` của phản hồi có
		câu ấy SAU ghi chú của ap_dung (nppsale: Postgres từ chối cả câu, vẫn 200 — sổ không đổi gì)."""
		e, _ref = self._da_gui()
		self.mang(TOK, get_ban_ghi(**ban_ghi_ky(InvDate="2026-02-30T00:00:00", TotalAmount=26030)))
		ma, kq = self.lam_moi(e)
		ngay = "MISA trả InvDate=2026-02-30T00:00:00 không phải ngày có thật — bỏ qua, cần kiểm tra tay."
		lech = "Lệch tiền với MISA — Tổng tiền: sổ 26020, MISA 26030."
		self.assertEqual((ma, kq["misa"]["status"], kq["misa"]["notes"]), (200, "amount_mismatch", [lech, ngay]))
		r = self.dong(e)
		self.assertEqual((r.misa_inv_no, r.misa_inv_series, r.misa_inv_date, r.misa_last_checked_at, r.misa_note),
			("00000123", "1C26TAA", None, LUC, f"{lech}\n{ngay}"))

	def test_h22_h8_h17_va_h7(self):
		"""Ghi chú của luật kéo về qua route: [ĐX H22] số đổi theo MISA (tờ không khoá) → ghi số MISA + ghi chú; [ĐX H8] MISA trả bản ghi chưa có số cho
		tờ đã có số → GIỮ signed + ghi chú; [BP H17] số gõ tay khác số MISA → ghi chú; H7: ghi chú cũ giữ, ghi chú trùng không thêm lần hai."""
		e, _ref = self._da_gui(misa_status="signed", misa_inv_no="00000123", misa_inv_series="1C26TAA", so_hd_go_tay="INV-20261115-1234",
			misa_note="Ghi chú người.")
		self.mang(TOK, get_ban_ghi(**ban_ghi_ky(InvNo="00000999")), get_ban_ghi(**ban_ghi_ky(InvNo="00000999")), get_ban_ghi())
		ma, kq = self.lam_moi(e)
		doi = "Số HĐĐT đổi từ 00000123 sang 00000999 theo MISA — cần kiểm tra."
		go_tay = "Sổ ghi số INV-20261115-1234, MISA cấp số 00000999."
		self.assertEqual((ma, kq["misa"]["notes"], kq["misa"]["status"]), (200, [go_tay, doi], "signed"))
		r = self.dong(e)
		self.assertEqual((r.misa_inv_no, r.misa_note), ("00000999", f"Ghi chú người.\n{go_tay}\n{doi}"))
		self.assertIn("00000999 999", r.tim_kd)
		self.assertNotIn("00000123", r.tim_kd)
		ma, kq = self.lam_moi(e)  # cùng bản ghi: số không đổi nữa → chỉ H17, ô không phình
		self.assertEqual((kq["misa"]["notes"], self.dong(e).misa_note), ([go_tay], f"Ghi chú người.\n{go_tay}\n{doi}"))
		ma, kq = self.lam_moi(e)  # {} — chưa có số (H8)
		h8 = "MISA trả bản ghi chưa có số trong khi sổ đã ghi số 00000999 — giữ nguyên trạng thái, cần kiểm tra tay."
		self.assertEqual((ma, kq["misa"]["status"], kq["misa"]["notes"]), (200, None, [h8]))
		r = self.dong(e)
		self.assertEqual((r.misa_status, r.misa_inv_no, r.misa_inv_series, r.misa_lookup_code, r.misa_invoice_code, r.misa_relation,
			r.misa_inv_date, r.misa_last_checked_at), ("signed", "00000999", "1C26TAA", "TX1", "M1-26-XYZ", "new", datetime.date(2026, 11, 15),
			LUC))  # Gotcha #7: MISA không trả gì → không ghi null đè; mốc hỏi vẫn ghi
		self.assertTrue(r.misa_note.endswith(h8))

	def test_xac_nhan_day_chi_khi_treo_hoac_loi(self):
		"""[ĐX H5] Xác nhận đẩy (issued + phat_hanh_luc + xoá misa_error) chỉ khi dòng ĐANG pending / error: tờ `error` có RefID mà MISA có → issued; tờ
		`sent` còn draft (dữ liệu chuyển sang) → giữ draft."""
		e, _ref = self._da_gui(trang_thai="draft", misa_status="error", misa_error="MISA publish lỗi 500: x", phat_hanh_luc=None)
		self.mang(TOK, get_ban_ghi(**DA_CO, TotalAmount=26020))
		self.assertEqual(self.lam_moi(e)[0], 200)
		r = self.dong(e)
		self.assertEqual((r.trang_thai, r.phat_hanh_luc, r.misa_error, r.misa_status), ("issued", LUC, None, "sent"))
		e2, _ref2 = self._da_gui(dong_hddt(nguoi_mua="Cũ"), trang_thai="draft", phat_hanh_luc=None)
		self.mang(get_ban_ghi(**DA_CO))
		self.assertEqual(self.lam_moi(e2)[0], 200)
		self.assertEqual((self.dong(e2).trang_thai, self.dong(e2).phat_hanh_luc), ("draft", None))
		# hàm ghi xét lại trên bản đọc CÓ KHOÁ: người gọi đưa xac_nhan_day=True (đọc trước lúc còn treo) mà dòng đã thôi treo → không xác nhận
		kq = M.ghi_ket_qua_keo_ve(e2, DA_CO, xac_nhan_day=True, luc=LUC)
		self.assertNotIn("trang_thai", kq["cap_nhat"])
		self.assertEqual((self.dong(e2).trang_thai, self.dong(e2).phat_hanh_luc), ("draft", None))

	def test_so_khong_ky_hieu_luu_rong_de_chi_muc_bat(self):
		"""§4.8 bước 4: MISA trả số mà KHÔNG ký hiệu → `misa_inv_series = ''` (MariaDB coi NULL là khác nhau — chỉ mục duy nhất (ký hiệu, số) phải bắt);
		tờ thứ hai nhận đúng số ấy → 409 trùng số, dòng không đổi."""
		bg = {"InvNo": "00000777", "PublishStatus": 3, "EInvoiceStatus": 1, "TotalAmount": 26020}
		e1, _r1 = self._da_gui()
		e2, _r2 = self._da_gui(dong_hddt(nguoi_mua="Tờ 2", tien_hang=24000, tien_thue=2020, tong_tien=26020))
		self.mang(TOK, get_ban_ghi(**bg), get_ban_ghi(**bg))
		self.assertEqual(self.lam_moi(e1)[0], 200)
		self.assertEqual(frappe.db.sql("SELECT `misa_inv_series`, `misa_inv_no` FROM `tabNPP HDDT` WHERE `name` = %s", e1)[0], ("", "00000777"))
		truoc = self.dong(e2)
		self.assertEqual(self.lam_moi(e2), (409, {"error": "Số HĐĐT  · 00000777 MISA trả về đã có ở một hoá đơn khác trong sổ — kiểm tra trùng trước "
			"khi làm mới lại."}))
		self.assertEqual(self.dong(e2), truoc)

	def test_i10_moc_hoi_khong_giam(self):
		"""I10: mốc hỏi không lùi khi lượt chạy chậm hơn ghi sau (lượt quét song song đã ghi mốc muộn hơn) — cả nhánh MISA có tờ lẫn nhánh H5 (treo
		quá 10 phút mà MISA không có → `error`)."""
		e, _ref = self._da_gui(misa_last_checked_at=LUC + datetime.timedelta(days=1))
		self.mang(TOK, get_ban_ghi(**ban_ghi_ky()), get_ban_ghi(**DA_CO, TotalAmount=26020), RONG)
		self.assertEqual(self.lam_moi(e)[0], 200)
		r = self.dong(e)
		self.assertEqual((r.misa_last_checked_at, r.misa_status), (LUC + datetime.timedelta(days=1), "signed"))
		# MISA không cho gì mới (tờ `sent`, bản ghi nháp khớp tiền) + mốc hỏi đã muộn hơn → không có gì để ghi: 200, dòng y nguyên (không câu SQL rỗng)
		e3, _ref3 = self._da_gui(dong_hddt(nguoi_mua="Nháp", tien_hang=24000, tien_thue=2020, tong_tien=26020),
			misa_last_checked_at=LUC + datetime.timedelta(days=1))
		truoc = self.dong(e3)
		self.assertEqual(self.lam_moi(e3), (200, {"success": True, "misa": {"InvNo": None, "TransactionID": None, "PublishStatus": 0,
			"EInvoiceStatus": None, "relation": None, "status": None, "notes": [], "original_marked_replaced": None}}))
		self.assertEqual(self.dong(e3), truoc)
		e2, _ref2 = self._da_gui(dong_hddt(nguoi_mua="Treo"), trang_thai="draft", misa_status="pending",
			misa_sent_at=LUC - datetime.timedelta(minutes=11), misa_last_checked_at=LUC + datetime.timedelta(days=1))
		self.assertEqual(self.lam_moi(e2)[0], 404)
		r = self.dong(e2)
		self.assertEqual((r.misa_status, r.misa_last_checked_at), ("error", LUC + datetime.timedelta(days=1)))

	def test_ghi_hong_khong_danh_dau_goc(self):
		"""[Soát thiếu 2] Ghi kết quả hỏng → KHÔNG đánh dấu tờ gốc (nppsale vẫn đánh): bản thay thế mang số đụng tờ khác → 409, tờ gốc giữ nguyên;
		ghi hỏng vì lỗi khác → 500 "Không ghi được kết quả làm mới: …" [ĐX H13]."""
		g = dong_hddt(misa_ref_id="goc-3", misa_status="signed", misa_inv_no="00000300", misa_inv_series="1C26TAA", trang_thai="issued")
		dong_hddt(nguoi_mua="F", misa_inv_no="00000301", misa_inv_series="1C26TAA", misa_ref_id="ref-f3", misa_status="signed")
		t, _ref = self._da_gui()
		truoc = self.dong(g)
		self.mang(TOK, get_ban_ghi(InvNo="00000301", InvSeries="1C26TAA", PublishStatus=3, EInvoiceStatus=3, OrgRefID="goc-3", TotalAmount=26020),
			get_ban_ghi(**ban_ghi_ky()))
		self.assertEqual(self.lam_moi(t)[0], 409)
		self.assertEqual(self.dong(g), truoc)
		with patch.object(M, "ap_dung", side_effect=ValueError("hỏng giữa chừng")):
			self.assertEqual(self.lam_moi(t), (500, {"error": "Không ghi được kết quả làm mới: hỏng giữa chừng"}))

	def test_danh_dau_goc_hong_van_giu_phan_ghi(self):
		"""Đánh dấu tờ gốc hỏng: phần ghi của tờ thay thế giữ; `loi_danh_dau` trả cho vòng quét; Error Log; phản hồi `original_marked_replaced` null."""
		g = dong_hddt(misa_ref_id="goc-4", misa_status="signed", misa_inv_no="00000400", misa_inv_series="1C26TAA", trang_thai="issued")
		t, _ref = self._da_gui()
		bg = {"InvNo": "00000401", "InvSeries": "1C26TAA", "PublishStatus": 3, "EInvoiceStatus": 3, "OrgRefID": "goc-4", "TotalAmount": 26020}
		self.mang(TOK, get_ban_ghi(**bg))
		with patch.object(M, "danh_dau_goc", side_effect=frappe.QueryDeadlockError("deadlock")):
			ma, kq = self.lam_moi(t)
		self.assertEqual((ma, kq["misa"]["original_marked_replaced"], kq["misa"]["relation"]), (200, None, "replacement"))
		self.assertEqual((self.dong(t).misa_inv_no, self.dong(g).misa_status), ("00000401", "signed"))
		self.assertTrue(frappe.db.exists("Error Log", {"method": "HĐĐT MISA: không đánh dấu được tờ gốc bị thay thế"}))
		with patch.object(M, "danh_dau_goc", side_effect=frappe.QueryDeadlockError("deadlock")):
			kq = M.ghi_ket_qua_keo_ve(t, bg, luc=LUC)
		self.assertEqual((kq["goc"], kq["loi_danh_dau"]), (None, "deadlock"))
		kq = M.ghi_ket_qua_keo_ve(t, bg, luc=LUC)
		self.assertEqual((kq["goc"], kq["loi_danh_dau"], self.dong(g).misa_status), (g, None, "replaced"))

	def test_danh_dau_goc_truc_tiep(self):
		"""§4.7: không có tờ gốc → None (không tạo dòng); đã replaced → None; KHÔNG xét misa_no_locked [=]; thêm dòng ghi chú (H7)."""
		self.assertIsNone(M.danh_dau_goc("khong-co", "x"))
		self.assertIsNone(M.danh_dau_goc(None, "x"))
		g = dong_hddt(misa_ref_id="goc-5", misa_status="amount_mismatch", misa_no_locked=1, misa_note="a")
		self.assertEqual(M.danh_dau_goc("goc-5", "T5"), g)
		r = self.dong(g)
		self.assertEqual((r.misa_status, r.misa_relation, r.misa_note.split("\n")[0]), ("replaced", "replaced", "a"))
		self.assertIsNone(M.danh_dau_goc("goc-5", "T6"))
		self.assertEqual(self.dong(g).misa_note, r.misa_note)


# =====================================================================================================================================
# Nhóm G — đối soát tay (§4.6)
# =====================================================================================================================================
class TestDoiSoat(_NenPhatHanh):
	def snap(self, **kv) -> str:
		d = frappe.get_doc({"doctype": "NPP MISA Snapshot", "ref_id": kv.pop("ref_id", None) or str(uuid.uuid4()), "keo_luc": LUC, **kv})
		d.insert(ignore_permissions=True)
		return d.name

	def doi_soat(self, than, nguoi: str = "owner") -> tuple:
		return self.goi(nguoi, M.doi_soat, than)

	def s(self, ten: str) -> dict:
		return frappe.db.get_value("NPP MISA Snapshot", ten, ["*"], as_dict=True)

	def test_kv44_noi_tay_bi_chiem_go(self):
		"""KV-44 [= trừ (b) khi ≥ 2]: (a) nối tay có cảnh báo số → needs_review, ghi chú "Người nối tay. …", sổ KHÔNG đổi; (b) tờ đã bị snapshot khác
		chiếm → 409; (c) gỡ → 6 cột NULL; (d) lỗi đầu vào / quyền."""
		h = dong_hddt(nguoi_mua="H", misa_inv_no="0000300", misa_inv_series="1C26TAA", misa_status="signed", misa_ref_id="r-h")
		s1 = self.snap(ky_hieu="1C26TAA", so_hddt="00000201")
		truoc = self.dong(h)
		ma, kq = self.doi_soat({"action": "link", "snapshotId": s1, "invoiceId": h})
		self.assertEqual((ma, kq), (200, {"success": True, "action": "link", "warnings": ["Sổ đang ghi số 0000300, MISA là 00000201."]}))
		x = self.s(s1)
		self.assertEqual((x.hddt, x.cach_khop, x.do_tin, x.ket_qua_khop, x.ghi_chu_khop, x.khop_luc), (h, "manual", "certain", "needs_review",
			"Người nối tay. Sổ đang ghi số 0000300, MISA là 00000201.", LUC))
		self.assertEqual(self.dong(h), truoc)
		h2 = dong_hddt(nguoi_mua="H2")
		self.snap(ky_hieu="1C26TAA", so_hddt="00000199", hddt=h2, cach_khop="manual")
		self.snap(ky_hieu="2C26TAA", so_hddt="00000198", hddt=h2, cach_khop="manual")  # ≥ 2 dòng chiếm vẫn 409 (nppsale 500)
		s3 = self.snap(ky_hieu="1C26TAA", so_hddt="00000202")
		ma, kq = self.doi_soat({"action": "link", "snapshotId": s3, "invoiceId": h2})
		self.assertEqual(ma, 409)
		self.assertRegex(kq["error"], r"^Hoá đơn này đã được nối với một hoá đơn MISA khác \((1C26TAA · 00000199|2C26TAA · 00000198)\)\. Gỡ nối "
			r"bên đó trước — một lần bán không thể có hai hoá đơn hợp lệ\.$")
		self.assertIsNone(self.s(s3).hddt)
		h3 = dong_hddt(nguoi_mua="H3")
		ma, kq = self.doi_soat({"action": "link", "snapshotId": s3, "invoiceId": h3})  # sổ chưa có số → không cảnh báo → matched
		self.assertEqual((ma, kq["warnings"], self.s(s3).ket_qua_khop, self.s(s3).ghi_chu_khop), (200, [], "matched", "Người nối tay."))
		ma, kq = self.doi_soat({"action": "unlink", "snapshotId": s1}, "manager")
		self.assertEqual((ma, kq), (200, {"success": True, "action": "unlink"}))
		x = self.s(s1)
		self.assertEqual([x.hddt, x.cach_khop, x.do_tin, x.ket_qua_khop, x.ghi_chu_khop, x.khop_luc], [None] * 6)  # cổng NULLIF đọc ra null
		for than, nguoi, mong in (({"action": "link", "snapshotId": s1}, "owner", (400, "Thiếu invoiceId")),
				({"action": "link", "snapshotId": s1, "invoiceId": "khong-co"}, "owner", (404, "Không tìm thấy hoá đơn đó trong sổ của đơn vị này.")),
				({"action": "link", "snapshotId": s1, "invoiceId": h}, "sales_a", (403, "Không có quyền")),
				({"action": "link", "snapshotId": s1, "invoiceId": h}, "warehouse", (403, "Không có quyền")),
				({"action": "link", "snapshotId": "khong-phai-uuid", "invoiceId": h}, "owner", (404, "Không tìm thấy dòng đối soát")),
				({"action": "xoa", "snapshotId": s1}, "owner", (400, "action không hợp lệ")),
				({"action": "link"}, "owner", (400, "Thiếu snapshotId")), ("abc", "owner", (400, "Thiếu snapshotId"))):
			self.assertEqual(self.doi_soat(than, nguoi), (mong[0], {"error": mong[1]}), (than, nguoi))
		nk = self.nhat_ky(nguon="reconcile")
		self.assertEqual([(json.loads(x.gui_di)["action"], x.ket_qua, x.hddt) for x in nk][:4], [("link", "success", h), ("link", "failed", h2),
			("link", "success", h3), ("unlink", "success", h)])

	def test_kv45_dung_hoa_don_tu_snapshot(self):
		"""KV-45 (a) [=]: dựng NPP HDDT từ snapshot `misa_only` với tiền của endpoint CHI TIẾT, issued, không HĐ / đơn, kỳ = ngày MISA, RefID của MISA,
		signed, ghi chú dựng; snapshot nối `manual` / matched; NVBH không thấy dòng qua cổng. (b) lần hai → 409; (c) snapshot khác cùng (ký hiệu, số) →
		409, không thêm dòng."""
		s9 = self.snap(ref_id="misa-9", ky_hieu="1C26TAA", so_hddt="00000200", ngay_phat_hanh="2026-11-05", ket_qua_khop="misa_only")
		a = self.mang(TOK, get_ban_ghi(InvNo="00000200", InvSeries="1C26TAA", InvDate="2026-11-05T00:00:00", PublishStatus=3, EInvoiceStatus=1,
			TransactionID="TX9", AccountObjectName="Cty B", AccountObjectTaxCode="0300000001", TotalAmount=77000, TotalAmountWithoutVAT=70000,
			TotalVATAmount=7000))
		ma, kq = self.doi_soat({"action": "create", "snapshotId": s9}, "manager")
		self.assertEqual((ma, kq["success"], kq["action"]), (200, True, "create"), kq)
		self.assertEqual(gon(a), ["POST /oauth", "GET /v3sainvoice/?refID=misa-9"])
		r = self.dong(kq["invoice_id"])
		self.assertEqual((r.trang_thai, r.hoa_don_ban, r.don_hang, r.so_hd_go_tay, r.nguoi_mua, r.mst_nguoi_mua, r.dia_chi_nguoi_mua, r.tien_hang,
			r.tien_thue, r.tong_tien, r.phat_hanh_luc, r.misa_ref_id, r.misa_inv_no, r.misa_inv_series, r.misa_inv_date, r.misa_lookup_code,
			r.misa_relation, r.misa_status, r.misa_last_checked_at), ("issued", None, None, "00000200", "Cty B", "0300000001", None, 70000, 7000, 77000,
			datetime.datetime(2026, 11, 5), "misa-9", "00000200", "1C26TAA", datetime.date(2026, 11, 5), "TX9", "new", "signed", LUC))
		self.assertEqual(r.misa_note, "Hoá đơn dựng từ đối soát MISA (phát hành thẳng trên MISA, chưa gắn đơn hàng). Kỳ ghi nhận lấy theo ngày "
			"phát hành trên MISA.")
		self.assertIn("00000200 200", r.tim_kd)
		x = self.s(s9)
		self.assertEqual((x.hddt, x.cach_khop, x.do_tin, x.ket_qua_khop, x.ghi_chu_khop, x.khop_luc), (r.name, "manual", "certain", "matched",
			"Đã dựng hoá đơn trong sổ từ dòng này.", LUC))
		self.assertNotIn(r.name, [d["id"] for d in self._doc("sales_a", select="id")])
		self.assertEqual(self.doi_soat({"action": "create", "snapshotId": s9}), (409, {"error": "Dòng này đã nối với một hoá đơn trong sổ rồi."}))
		s10 = self.snap(ref_id="misa-10", ky_hieu="1C26TAA", so_hddt="00000200")
		self.mang(get_ban_ghi(InvNo="00000200", InvSeries="1C26TAA", PublishStatus=3, TotalAmount=77000))
		n = frappe.db.count("NPP HDDT")
		self.assertEqual(self.doi_soat({"action": "create", "snapshotId": s10}), (409, {"error": 'Sổ đã có một hoá đơn mang ký hiệu 1C26TAA số '
			'00000200. Dùng "Nối tay" với hoá đơn đó thay vì dựng tờ mới.'}))
		self.assertEqual((frappe.db.count("NPP HDDT"), self.s(s10).hddt), (n, None))
		nk = self.nhat_ky(nguon="reconcile")
		self.assertEqual([(x.ket_qua, x.hddt, x.owner) for x in nk], [("success", r.name, self.ma["u:manager"]), ("failed", r.name,
			self.ma["u:owner"]), ("failed", None, self.ma["u:owner"])])

	def test_kv45_cac_loi(self):
		"""KV-45 (d) MISA không trả chi tiết → 502; (e) thiếu TotalAmount → 502; (f) GET 500 → 502 "Gọi MISA lỗi: …"; chưa cấu hình → 400; khoá site
		đổi → 500 "Giải mã cấu hình lỗi: …"; RefID đã có trong sổ → 409 [ĐX]. Không dòng nào được tạo."""
		from cryptography.fernet import Fernet

		from nppsale.tests.test_misa_mang import _khoa_site

		s = self.snap(ref_id="misa-11", ky_hieu="1C26TAA", so_hddt="00000211")
		n = frappe.db.count("NPP HDDT")
		self.mang(TOK, RONG, get_ban_ghi(InvNo="00000211"), {"status": 500, "body": "<html>x</html>"})
		for mong in ((502, "MISA không trả chi tiết hoá đơn này nên không lấy được tiền hàng và thuế. KHÔNG dựng hoá đơn với số liệu thiếu — thử "
				"lại sau, hoặc lập tay."), (502, "MISA không trả tổng tiền — không dựng hoá đơn thiếu số liệu."),
				(502, "Gọi MISA lỗi: Lấy HD lỗi 500: <html>x</html>")):
			self.assertEqual(self.doi_soat({"action": "create", "snapshotId": s}), (mong[0], {"error": mong[1]}))
		with _khoa_site(Fernet.generate_key().decode()):
			self.assertEqual(self.doi_soat({"action": "create", "snapshotId": s}), (500, {"error": "Giải mã cấu hình lỗi: khoá mã hoá của site không "
				"mở được tài khoản / mật khẩu MISA đã lưu"}))
		dong_hddt(nguoi_mua="Có RefID", misa_ref_id="misa-11", misa_status="sent")
		self.mang(get_ban_ghi(InvNo="<Chưa cấp số>", PublishStatus=0, TotalAmount=1000))
		self.assertEqual(self.doi_soat({"action": "create", "snapshotId": s}), (409, {"error": 'Sổ đã có một hoá đơn mang RefID này. Dùng "Nối tay" '
			'với hoá đơn đó thay vì dựng tờ mới.'}))
		frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)
		self.assertEqual(self.doi_soat({"action": "create", "snapshotId": s}), (400, {"error": "Chưa cấu hình MISA"}))
		self.assertEqual(frappe.db.count("NPP HDDT"), n + 1)

	def test_kv45_dua_hai_luot_dung(self):
		"""Dựng gọi MISA KHÔNG giữ khoá; lượt khác nối / dựng xong trong lúc chờ HTTP → đọc lại snapshot CÓ KHOÁ → 409 "đã nối", không thêm dòng."""
		s = self.snap(ref_id="misa-14", ky_hieu="1C26TAA", so_hddt="00000214")
		khac = dong_hddt(nguoi_mua="Lượt khác")

		def khi_goi(req):
			if "refID=" in req.url:
				frappe.db.sql("UPDATE `tabNPP MISA Snapshot` SET `hddt` = %s, `cach_khop` = 'manual' WHERE `name` = %s", (khac, s))

		self.mang(TOK, get_ban_ghi(InvNo="00000214", InvSeries="1C26TAA", PublishStatus=3, TotalAmount=900), khi_goi=khi_goi)
		n = frappe.db.count("NPP HDDT")
		self.assertEqual(self.doi_soat({"action": "create", "snapshotId": s}), (409, {"error": "Dòng này đã nối với một hoá đơn trong sổ rồi."}))
		self.assertEqual((frappe.db.count("NPP HDDT"), self.s(s).hddt), (n, khac))

	def test_kv45g_h_cho_cap_so_va_tien_0(self):
		"""(g) [≠ H9] chi tiết còn `<Chưa cấp số>` + PublishStatus 0 → số NULL (cả số gõ tay), `sent`; (h) [=] TotalAmountWithoutVAT 0.0 → tiền hàng 0;
		[ĐX H26] ngày không có thật → không ghi ngày, kỳ = hôm nay + ghi chú; người mua trống → "Khách lẻ"."""
		s = self.snap(ref_id="misa-12", ngay_phat_hanh="2026-11-01")
		self.mang(TOK, get_ban_ghi(InvNo="<Chưa cấp số>", PublishStatus=0, InvDate="2026-02-30", TotalAmount=1100.0, TotalAmountWithoutVAT=0.0))
		ma, kq = self.doi_soat({"action": "create", "snapshotId": s})
		self.assertEqual(ma, 200, kq)
		r = self.dong(kq["invoice_id"])
		self.assertEqual((r.so_hd_go_tay, r.misa_inv_no, r.misa_status, r.tien_hang, r.tien_thue, r.tong_tien, r.nguoi_mua, r.misa_inv_date,
			r.phat_hanh_luc), (None, None, "sent", 0, 0, 1100, "Khách lẻ", None, LUC))
		self.assertTrue(r.misa_note.endswith("MISA trả InvDate=2026-02-30 không phải ngày có thật — bỏ qua, cần kiểm tra tay."))
		s2 = self.snap(ref_id="misa-13", ngay_phat_hanh="2026-11-02", nguoi_mua="Tên snapshot", mst_nguoi_mua="0311111111")
		self.mang(get_ban_ghi(InvNo="00000213", InvSeries="1C26TAA", PublishStatus=3, TotalAmount=500))
		ma, kq = self.doi_soat({"action": "create", "snapshotId": s2})
		r = self.dong(kq["invoice_id"])
		self.assertEqual((r.phat_hanh_luc, r.misa_inv_date, r.nguoi_mua, r.mst_nguoi_mua), (datetime.datetime(2026, 11, 2), datetime.date(2026, 11, 2),
			"Tên snapshot", "0311111111"))


# =====================================================================================================================================
# Nhóm H — cấu hình (§4.4) + thử kết nối (§4.5)
# =====================================================================================================================================
class TestCauHinh(_NenHddt):
	def test_kv46_luu_cau_hinh_bao_ve_mat_khau(self):
		"""KV-46 (a) lưu: trim, mặc định đường, `loai_hd` từ chữ, sandbox false, mật khẩu cắt hai đầu, `tabSingles` chỉ có dấu `*`; (b) lưu lần hai không
		tài khoản / mật khẩu → bản mã cũ còn; (c) GET không mang chữ mật khẩu, has_* đúng; (d) cổng select('*') `*_enc` null, KHO 0 dòng, QL 1 dòng; (e) QL
		GET / POST → 403; (f) thân "abc" → 400; (g) chưa lưu → GET {config: null}, cổng 0 dòng."""
		self.assertEqual(self.goi("owner", M.cau_hinh_doc, pt="GET"), (200, {"config": None}))
		self.assertEqual(self._doc("owner", "company_einvoice_config", select="*"), [])
		ma, kq = self.goi("owner", M.cau_hinh_luu, {"api_base": " https://misa.gia/api/v2 ", "token_path": "", "publish_path": "", "tax_code":
			"0100000000", "username": "u-thu", "password": "  p-thu  ", "sandbox": False, "is_active": True, "invoice_type": "2",
			"has_username": False, "id": "x", "org_id": "khac"})
		self.assertEqual((ma, kq), (200, {"success": True}))
		d = frappe.get_doc(CH.TEN)
		self.assertEqual((d.dia_chi_api, d.duong_lay_token, d.duong_phat_hanh, d.loai_hd, d.moi_truong_thu, d.dang_dung, d.nha_cung_cap,
			d.mst_nguoi_ban, d.misa_inv_template_no, d.ke_thua_mau_cu), ("https://misa.gia/api/v2", "/oauth", "/v3sainvoice", 2, 0, 1, "misa",
			"0100000000", "1", 0))
		self.assertEqual((d.get_password("tai_khoan"), d.get_password("mat_khau")), ("u-thu", "p-thu"))
		for truong in ("tai_khoan", "mat_khau"):
			v = frappe.db.sql("SELECT `value` FROM `tabSingles` WHERE `doctype` = %s AND `field` = %s", (CH.TEN, truong))[0][0]
			self.assertTrue(v and set(v) == {"*"}, v)
		ma, kq = self.goi("accountant", M.cau_hinh_luu, {"api_base": "https://misa.gia/api/v2", "tax_code": "0100000000", "username": "",
			"password": "   ", "sandbox": "false", "misa_inv_series": "1C26TAA", "has_password": True})
		self.assertEqual(ma, 200)
		d = frappe.get_doc(CH.TEN)
		self.assertEqual((d.get_password("tai_khoan"), d.get_password("mat_khau"), d.moi_truong_thu, d.misa_inv_series), ("u-thu", "p-thu", 1,
			"1C26TAA"))  # "false" là chuỗi khác rỗng → đúng kiểu JS
		ma, kq = self.goi("accountant", M.cau_hinh_doc, pt="GET")
		self.assertEqual(ma, 200)
		ch = kq["config"]
		self.assertEqual(list(ch), ["id", "org_id", "provider", "api_base", "tax_code", "seller_name", "seller_address", "misa_company_id",
			"misa_org_unit_id", "misa_template_id", "misa_user_id", "misa_inv_series", "misa_inv_template_no", "sandbox", "is_active", "token_path",
			"publish_path", "misa_app_id", "sign_type", "invoice_type", "is_inherit_from_old_template", "misa_is_invoice_with_code", "created_at",
			"updated_at", "has_username", "has_password"])
		self.assertEqual((ch["id"], ch["provider"], ch["api_base"], ch["tax_code"], ch["seller_name"], ch["sandbox"], ch["is_active"],
			ch["invoice_type"], ch["sign_type"], ch["has_username"], ch["has_password"], ch["created_at"]), ("NPP MISA Cau Hinh", "misa",
			"https://misa.gia/api/v2", "0100000000", None, True, True, 1, 1, True, True, None))
		self.assertEqual(ch["org_id"], frappe.db.get_single_value("NPP Cai Dat", "org_id"))
		self.assertRegex(ch["updated_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+07:00$")
		toan = json.dumps(kq, ensure_ascii=False)
		for bm in ("u-thu", "p-thu", "***"):
			self.assertNotIn(bm, toan)
		self.assertEqual(self._doc("owner", "company_einvoice_config", select="username_enc, password_enc"), [{"username_enc": None,
			"password_enc": None}])
		# has_* đọc `__Auth` (bản mã thật), không đọc dấu `*` của `tabSingles`: mất bản mã mật khẩu → has_password false dù `tabSingles` còn dấu
		frappe.db.savepoint("auth")
		frappe.db.sql("DELETE FROM `__Auth` WHERE `doctype` = %s AND `fieldname` = 'mat_khau'", CH.TEN)
		kq = self.goi("owner", M.cau_hinh_doc, pt="GET")[1]["config"]
		self.assertEqual((kq["has_username"], kq["has_password"]), (True, False))
		frappe.db.rollback(save_point="auth")
		self.assertEqual(len(self._doc("manager", "company_einvoice_config", select="*")), 1)
		self.assertEqual(self._doc("warehouse", "company_einvoice_config", select="*"), [])
		for nguoi in ("manager", "sales_a", "warehouse", None):
			self.assertEqual(self.goi(nguoi, M.cau_hinh_doc, pt="GET"), (403, {"error": "Chỉ Chủ NPP hoặc Kế toán mới được cấu hình hoá đơn điện tử"}))
			self.assertEqual(self.goi(nguoi, M.cau_hinh_luu, {"api_base": "x"}), (403, {"error": "Chỉ Chủ NPP hoặc Kế toán mới được cấu hình hoá "
				"đơn điện tử"}))
		for than in ("abc", None, [1]):
			self.assertEqual(self.goi("owner", M.cau_hinh_luu, than), (400, {"error": "Body không hợp lệ"}))
		self.assertEqual(frappe.get_doc(CH.TEN).dia_chi_api, "https://misa.gia/api/v2")
		self._i6()

	def test_luu_khong_ghi_truong_cua_thu_ket_noi(self):
		"""POST không ghi `misa_is_invoice_with_code`, `misa_app_id`, `kieu_ky`; khoá lạ bỏ; chuỗi khác kiểu (số) → trống như `str()` của nppsale;
		invoice_type: số giữ, chữ → parseInt, < 1 / rác → 1; ke_thua_mau_cu vắng → 0."""
		frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)
		d = frappe.get_doc(CH.TEN)
		d.update({"dia_chi_api": API, "misa_is_invoice_with_code": 1, "misa_app_id": "app", "kieu_ky": 2, "ke_thua_mau_cu": 1})
		d.save(ignore_permissions=True)
		for loai, mong in ((3, 3), ("7 mẫu", 7), ("abc", 1), (0, 1), (-2, 1), (None, 1), (True, 1)):
			self.assertEqual(self.goi("owner", M.cau_hinh_luu, {"api_base": API, "invoice_type": loai, "misa_company_id": 156217,
				"misa_is_invoice_with_code": False, "misa_app_id": "khac", "sign_type": 9})[0], 200)
			d = frappe.get_doc(CH.TEN)
			self.assertEqual((d.loai_hd, d.misa_company_id, d.misa_is_invoice_with_code, d.misa_app_id, d.kieu_ky, d.ke_thua_mau_cu),
				(mong, None, 1, "app", 2, 0), loai)
		# ba cờ: khoá VẮNG → mặc định (sandbox / is_active 1, kế thừa 0); khoá CÓ → truthy kiểu JS (null / 0 / "" sai; "false" / "0" đúng)
		for gt, mong in ((None, 0), (0, 0), ("", 0), (False, 0), ("false", 1), ("0", 1), (1, 1), ([], 1)):
			self.assertEqual(self.goi("owner", M.cau_hinh_luu, {"api_base": API, "sandbox": gt, "is_active": gt,
				"is_inherit_from_old_template": gt})[0], 200)
			d = frappe.get_doc(CH.TEN)
			self.assertEqual((d.moi_truong_thu, d.dang_dung, d.ke_thua_mau_cu), (mong, mong, mong), gt)

	def test_luu_khoa_site_sai_dinh_dang(self):
		"""Khoá site sai định dạng khi mã hoá → 500 câu tiếng Việt [ĐX], không chữ Anh trong message_log; ô trống thì vẫn lưu được (không mã hoá)."""
		from nppsale.tests.test_misa_mang import _khoa_site

		n = len(frappe.local.message_log)
		with _khoa_site("khong-phai-khoa-fernet"):
			self.assertEqual(self.goi("owner", M.cau_hinh_luu, {"api_base": API, "password": "p-thu"}), (500, {"error": "Không mã hoá được tài khoản "
				"MISA — khoá mã hoá của site (encryption_key trong site_config.json) sai định dạng."}))
			self.assertEqual(self.goi("owner", M.cau_hinh_luu, {"api_base": API})[0], 200)
		self.assertEqual(len(frappe.local.message_log), n)

	def _tra_tk(self, **them):
		return {"body": {"access_token": "T9", "expires_in": 3600,
			"Data": '{"CompanyID":156217,"OrganizationUnitID":"ou","UserID":"us","IsInvoiceWithCode":"True"}', **them}}

	def _mau(self, ds) -> dict:
		return {"body": {"success": True, "data": json.dumps(ds, ensure_ascii=False)}}

	def test_kv47_thu_ket_noi(self):
		"""KV-47 [≠ nhỏ: 1 lời /oauth]: định danh + mẫu đầu còn dùng → lưu vào cấu hình (đường đẩy `Code` vì đơn vị có mã); đúng 1 /oauth (`taxcode`) + 1
		lời mẫu (`TaxCode`, thân 4 khoá); nhật ký test_connection không chứa mật khẩu / token / thân /oauth."""
		self.goi("owner", M.cau_hinh_luu, {**CAU_HINH_CHUAN, "misa_inv_series": "", "misa_company_id": ""})
		a = self.mang(self._tra_tk(), self._mau([{"IPTemplateID": "t0", "Inactive": True}, {"IPTemplateID": "t1", "TemplateName": "Mẫu 1",
			"InvSeries": "1C26TAA", "InvTemplateNo": "1", "InvoiceType": 1, "IsInheritFromOldTemplate": False, "IsPublished": True}]))
		truoc = frappe.db.get_single_value(CH.TEN, "modified")
		ma, kq = self.goi("accountant", M.thu_ket_noi, {})
		self.assertEqual((ma, kq), (200, {"success": True, "tenant": {"companyId": "156217", "orgUnitId": "ou", "userId": "us",
			"isInvoiceWithCode": True}, "template": {"IPTemplateID": "t1", "TemplateName": "Mẫu 1", "InvSeries": "1C26TAA", "InvTemplateNo": "1",
			"InvoiceType": 1}, "template_count": 1, "template_error": None}))
		self.assertEqual(gon(a), ["POST /oauth", "POST /v3common/code/template"])
		self.assertEqual(hd_app(a.goi[0][2]), [("Content-Type", "text/plain"), ("taxcode", MST)])
		self.assertEqual(hd_app(a.goi[1][2]), [("Content-Type", "application/json"), ("Authorization", "Bearer T9"), ("TaxCode", MST)])
		self.assertEqual(sorted(json.loads(a.goi[1][3])), ["Password", "TaxCode", "TypeInvoice", "UserName"])
		d = frappe.get_doc(CH.TEN)
		self.assertEqual((d.misa_company_id, d.misa_org_unit_id, d.misa_user_id, d.misa_is_invoice_with_code, d.duong_phat_hanh, d.misa_template_id,
			d.misa_inv_series, d.misa_inv_template_no, d.loai_hd, d.ke_thua_mau_cu), ("156217", "ou", "us", 1, "/v3sainvoice/Code", "t1", "1C26TAA",
			"1", 1, 0))
		self.assertNotEqual(d.modified, truoc)
		(nk,) = self.nhat_ky(nguon="test_connection")
		self.assertEqual((nk.ket_qua, nk.owner, json.loads(nk.nhan_ve)), ("success", self.ma["u:accountant"], {"tenant": kq["tenant"],
			"template": kq["template"], "template_count": 1, "template_error": None}))
		self._i6("T9")

	def test_kv47_bien_the(self):
		"""Mẫu 500 → 200, template null, count 0, template_error; /oauth lỗi → 502 (không lưu gì); thiếu tài khoản → 400; chưa lưu → 400; QL / NVBH → 403;
		mẫu `InvSeries: null` → ký hiệu thành trống; mẫu KHÔNG có khoá `InvSeries` / `IPTemplateID` → giữ giá trị cũ; chỉ có mẫu ngừng dùng → null."""
		self.assertEqual(self.goi("owner", M.thu_ket_noi, {}), (400, {"error": "Chưa có cấu hình. Lưu cấu hình MISA trước (api_base + MST + "
			"username/password)."}))
		self.goi("owner", M.cau_hinh_luu, {**CAU_HINH_CHUAN, "misa_template_id": "t-cu"})
		for nguoi in ("manager", "sales_a", None):
			self.assertEqual(self.goi(nguoi, M.thu_ket_noi, {}), (403, {"error": "Chỉ Chủ NPP hoặc Kế toán mới được test kết nối"}))
		self.mang(self._tra_tk(), {"status": 500, "body": "<html>loi</html>"})
		ma, kq = self.goi("owner", M.thu_ket_noi, {})
		self.assertEqual((ma, kq["template"], kq["template_count"], kq["template_error"]), (200, None, 0, "Lấy mẫu HD lỗi 500: <html>loi</html>"))
		self.assertEqual(frappe.db.get_single_value(CH.TEN, "misa_template_id"), "t-cu")
		MM.xoa_token_nho()
		self.mang({"body": {"error": "invalid_grant", "error_description": "Sai", "status": 401}})
		self.assertEqual(self.goi("owner", M.thu_ket_noi, {}), (502, {"error": "MISA token lỗi 401: Sai (invalid_grant)"}))
		self.mang(self._tra_tk(Data='{"CompanyID":"c2"}'), self._mau([{"IPTemplateID": "t2", "InvSeries": None, "IsPublished": False}]))
		self.assertEqual(self.goi("owner", M.thu_ket_noi, {})[0], 200)
		d = frappe.get_doc(CH.TEN)
		self.assertEqual((d.misa_template_id, d.misa_inv_series or None, d.misa_company_id, d.misa_is_invoice_with_code, d.duong_phat_hanh),
			("t2", None, "c2", 1, "/v3sainvoice/Code"))  # không có cờ có mã → giữ cờ + đường cũ
		frappe.db.set_single_value(CH.TEN, "misa_inv_series", "1C26TAA")
		self.mang(self._tra_tk(), self._mau([{"TemplateName": "Không id", "InvTemplateNo": None, "InvoiceType": 0}]))
		ma, kq = self.goi("owner", M.thu_ket_noi, {})
		self.assertEqual((ma, kq["template"]), (200, {"TemplateName": "Không id", "InvTemplateNo": None, "InvoiceType": 0}))
		d = frappe.get_doc(CH.TEN)
		self.assertEqual((d.misa_template_id, d.misa_inv_series, d.misa_inv_template_no, d.loai_hd), ("t2", "1C26TAA", "1", 1))
		self.mang(self._tra_tk(), self._mau([{"IPTemplateID": "t3", "Inactive": 1}]))
		ma, kq = self.goi("owner", M.thu_ket_noi, {})
		self.assertEqual((ma, kq["template"], kq["template_count"]), (200, None, 0))
		frappe.db.sql("DELETE FROM `__Auth` WHERE `doctype` = %s AND `fieldname` = 'mat_khau'", CH.TEN)
		self.assertEqual(self.goi("owner", M.thu_ket_noi, {}), (400, {"error": "Thiếu username/password. Nhập rồi bấm test lại."}))

	def test_loi_khong_luong_khong_lo_bi_mat(self):
		"""I6: lỗi không lường ở Cấu hình / Thử kết nối khi bật developer_mode (traceback CÓ biến) → 500 câu lỗi; Error Log KHÔNG mang tài khoản /
		mật khẩu vừa gõ (thân nằm trong `YeuCauCu` — bộ che của lõi không che thuộc tính dataclass, không che "username") hay token."""
		self.goi("owner", M.cau_hinh_luu, CAU_HINH_CHUAN)
		dev = frappe.conf.get("developer_mode")
		frappe.conf.developer_mode = 1
		try:
			with patch.object(M, "_loai_hd", _hong("hỏng")):
				self.assertEqual(self.goi("owner", M.cau_hinh_luu, {**CAU_HINH_CHUAN, "username": "u-BIMAT-9", "password": "p-BIMAT-9"}),
					(500, {"error": "hỏng"}))
			self.mang(self._tra_tk())
			with patch.object(MM, "lay_mau", _hong("hỏng 2")):
				self.assertEqual(self.goi("owner", M.thu_ket_noi, {"username": "u-BIMAT-9", "password": "p-BIMAT-9"}), (500, {"error": "hỏng 2"}))
		finally:
			frappe.conf.developer_mode = dev
		el = frappe.db.sql("SELECT `method`, `error` FROM `tabError Log` WHERE `creation` > %s", self.loi_truoc)
		self.assertEqual(sorted(x[0] for x in el), ["HĐĐT MISA: lưu cấu hình lỗi", "HĐĐT MISA: thử kết nối lỗi"])
		self.assertTrue(all("Traceback" in x[1] for x in el))
		self._i6("u-BIMAT-9", "p-BIMAT-9", "T9")

	def test_hai_lop_che_bi_mat_trong_error_log(self):
		"""Hai lớp, thử TỪNG lớp (mỗi lớp một mình phải đủ): (1) `_ghi_loi` không kèm biến cục bộ — biến bí mật mang tên KHÔNG nhạy cảm ở khung gọi
		vẫn không vào Error Log; (2) tên biến giữ bí mật của route Cấu hình / Thử kết nối có `secret` / `password` / `token` — kể cả khi Error Log kèm biến
		(developer_mode) thì bộ che của lõi vẫn che."""
		dev = frappe.conf.get("developer_mode")
		frappe.conf.developer_mode = 1
		try:
			try:
				mat_khau_go = "p-BIMAT-LOP1"  # tên tiếng Việt: bộ che của lõi KHÔNG nhận
				raise RuntimeError(f"x{len(mat_khau_go)}")
			except RuntimeError:
				M._ghi_loi("HĐĐT MISA: thử lớp 1")
			self.goi("owner", M.cau_hinh_luu, CAU_HINH_CHUAN)
			self.mang(self._tra_tk())
			with patch.object(M, "_ghi_loi", lambda t: frappe.log_error(title=t)), patch.object(MM, "lay_mau", _hong("hỏng 3")):
				self.assertEqual(self.goi("owner", M.thu_ket_noi, {"username": "u-BIMAT-LOP2", "password": "p-BIMAT-LOP2"}), (500, {"error": "hỏng 3"}))
			with patch.object(M, "_ghi_loi", lambda t: frappe.log_error(title=t)), patch.object(M, "_loai_hd", _hong("hỏng 4")):
				self.assertEqual(self.goi("owner", M.cau_hinh_luu, {**CAU_HINH_CHUAN, "username": "u-BIMAT-LOP2", "password": "p-BIMAT-LOP2"}),
					(500, {"error": "hỏng 4"}))
		finally:
			frappe.conf.developer_mode = dev
		el = frappe.db.sql("SELECT `method`, `error` FROM `tabError Log` WHERE `creation` > %s", self.loi_truoc)
		self.assertEqual(len(el), 3)
		self.assertTrue(any("Traceback with variables" in x[1] for x in el))  # lớp 2 thật sự chạy với traceback CÓ biến
		self._i6("p-BIMAT-LOP1", "u-BIMAT-LOP2", "p-BIMAT-LOP2", "T9")

	def test_kv47_giai_ma_va_chu_vua_go(self):
		"""[Soát thiếu 2] Khoá site đổi: thân có CẢ tài khoản lẫn mật khẩu → không giải mã, thử bình thường (200) và LƯU hai chữ vừa gõ (sau khi /oauth
		OK); thân trống → 500 câu tiếng Việt, 0 lời gọi. /oauth lỗi thì không lưu chữ vừa gõ."""
		from cryptography.fernet import Fernet

		from nppsale.tests.test_misa_mang import _khoa_site

		self.goi("owner", M.cau_hinh_luu, CAU_HINH_CHUAN)
		khoa = Fernet.generate_key().decode()
		a = self.mang()
		with _khoa_site(khoa):
			self.assertEqual(self.goi("owner", M.thu_ket_noi, {}), (500, {"error": "Không giải mã được tài khoản MISA — khoá mã hoá của site "
				"(encryption_key trong site_config.json) đã đổi so với lúc lưu cấu hình?"}))
			self.assertEqual(a.goi, [])
			a = self.mang({"body": {"error": "invalid_grant"}})
			self.assertEqual(self.goi("owner", M.thu_ket_noi, {"username": " u-moi ", "password": "  p-moi  "})[0], 502)
			a = self.mang(self._tra_tk(), self._mau([]))
			self.assertEqual(self.goi("owner", M.thu_ket_noi, {"username": " u-moi ", "password": "  p-moi  "})[0], 200)
			self.assertEqual(a.goi[0][3], b"grant_type=password&username=u-moi&password=p-moi")
			d = frappe.get_doc(CH.TEN)
			self.assertEqual((d.get_password("tai_khoan"), d.get_password("mat_khau")), ("u-moi", "p-moi"))
		self._i6("u-moi", "p-moi")


# =====================================================================================================================================
# Đọc sổ hỏng (lỗi CSDL) ở từng route — câu nguyên văn Phụ lục A; không gọi MISA; không câu tiếng Anh / bí mật
# =====================================================================================================================================
class TestDocHong(_NenPhatHanh):
	def test_doc_dong_va_cau_hinh_hong(self):
		"""Làm mới: đọc dòng hỏng → 500 "Lỗi truy vấn hoá đơn"; đọc cấu hình hỏng → 500 "Lỗi truy vấn cấu hình MISA" (Thử kết nối cùng câu). Phát hành:
		đọc cấu hình hỏng → 500 "Không đọc được cấu hình MISA: {msg}" + dòng `error` mang câu ấy (nppsale đi qua catch); ngoại lệ không lời →
		"Lỗi server không xác định khi gọi MISA". GET cấu hình hỏng → 500 "Không đọc được cấu hình MISA: {msg}". Dựng từ snapshot: đọc cấu hình hỏng →
		500 cùng câu; snapshot RefID trắng → 400 "Dòng này không có RefID.". 0 lời gọi MISA."""
		e = self.lap()
		e2 = dong_hddt(nguoi_mua="Đã gửi", misa_status="sent", misa_ref_id=str(uuid.uuid4()), trang_thai="issued")
		a = self.mang()
		hong = frappe.QueryTimeoutError("Lock wait timeout exceeded")
		with patch.object(M, "doc_dong_hddt", side_effect=hong):
			self.assertEqual(self.lam_moi(e2), (500, {"error": "Lỗi truy vấn hoá đơn"}))
		with patch.object(MM, "lay_cau_hinh", side_effect=hong):
			self.assertEqual(self.lam_moi(e2), (500, {"error": "Lỗi truy vấn cấu hình MISA"}))
			self.assertEqual(self.goi("owner", M.thu_ket_noi, {}), (500, {"error": "Lỗi truy vấn cấu hình MISA"}))
			cau = "Không đọc được cấu hình MISA: Lock wait timeout exceeded"
			self.assertEqual(self.phat_hanh(e), (500, {"error": cau}))
			self.assertEqual((self.dong(e).misa_status, self.dong(e).misa_error, self.dong(e).misa_ref_id), ("error", cau, None))
			s = frappe.get_doc({"doctype": "NPP MISA Snapshot", "ref_id": "misa-dh", "keo_luc": LUC}).insert(ignore_permissions=True).name
			self.assertEqual(self.goi("owner", M.doi_soat, {"action": "create", "snapshotId": s}), (500, {"error": cau}))
		with patch.object(M, "_gio_iso", side_effect=hong):  # hỏng giữa lúc dựng `config` (sau khi đã đọc Single)
			self.assertEqual(self.goi("owner", M.cau_hinh_doc, pt="GET"), (500, {"error": "Không đọc được cấu hình MISA: Lock wait timeout exceeded"}))
		with patch.object(M, "doc_dong_hddt", side_effect=RuntimeError()):
			self.assertEqual(self.phat_hanh(e, kiem_i2=False), (500, {"error": "Lỗi server không xác định khi gọi MISA"}))
		frappe.db.sql("UPDATE `tabNPP MISA Snapshot` SET `ref_id` = '   ' WHERE `name` = %s", s)
		self.assertEqual(self.goi("owner", M.doi_soat, {"action": "create", "snapshotId": s}), (400, {"error": "Dòng này không có RefID."}))
		self.assertEqual(a.goi, [])

	def test_thu_ket_noi_luu_hong(self):
		"""[ĐX H13] Thử kết nối: MISA trả định danh / mẫu nhưng lưu cấu hình hỏng → 500 "Đã kết nối MISA nhưng chưa lưu được thông tin vào cấu hình: {msg}"
		(nppsale: console rồi vẫn 200); cấu hình không đổi; không nhật ký test_connection; message_log không thêm chữ Anh."""
		self.mang({"body": {"access_token": "T9", "expires_in": 3600, "Data": '{"CompanyID":"c9"}'}},
			{"body": {"success": True, "data": json.dumps([{"IPTemplateID": "t9", "InvSeries": "9C26TAA"}])}})
		n = len(frappe.local.message_log)
		with patch.object(M, "_chu", side_effect=frappe.ValidationError("hỏng lưu")):
			self.assertEqual(self.goi("owner", M.thu_ket_noi, {}), (500, {"error": "Đã kết nối MISA nhưng chưa lưu được thông tin vào cấu hình: hỏng lưu"}))
		d = frappe.get_doc(CH.TEN)
		self.assertEqual((d.misa_company_id, d.misa_template_id, d.misa_inv_series), ("156217", None, "1C26TAA"))
		self.assertEqual((self.nhat_ky(nguon="test_connection"), len(frappe.local.message_log)), ([], n))
		self._i6("T9")


# =====================================================================================================================================
# Đường dẫn: `_nap()` có mô-đun MISA (§6.2); khách 401; route không port → 501; JSON trả đi qua tuyen._tra
# =====================================================================================================================================
class TestTuyen(_NenHddt):
	@contextmanager
	def _yeu_cau(self, pt: str, duong: str, than=None):
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		cu = getattr(frappe.local, "request", None)
		env = EnvironBuilder(method="POST", headers={"X-Npp-Duong": duong, "X-Npp-Phuong-Thuc": pt},
			data=None if than is None else json.dumps(than), content_type="application/json").get_environ()
		frappe.local.request = Request(env)
		try:
			yield
		finally:
			frappe.local.request = cu

	def _http(self, nguoi, pt, duong, than=None):
		from nppsale.api import tuyen as T

		with self._yeu_cau(pt, duong, than):
			frappe.set_user(nguoi)
			frappe.local._npp_ngu_canh = None
			try:
				r = T.goi()
			finally:
				frappe.set_user("Administrator")
				frappe.local._npp_ngu_canh = None
		return r.status_code, json.loads(r.get_data(as_text=True))

	def test_dang_ky_va_duong_khong_port(self):
		from nppsale.api import tuyen as T

		T._nap()
		for pt, duong, ham in (("POST", "/api/einvoice/publish", M.phat_hanh), ("POST", "/api/einvoice/refresh-status", M.lam_moi),
				("GET", "/api/einvoice/config", M.cau_hinh_doc), ("POST", "/api/einvoice/config", M.cau_hinh_luu),
				("POST", "/api/einvoice/test-connection", M.thu_ket_noi), ("POST", "/api/einvoice/reconcile-action", M.doi_soat)):
			self.assertEqual([h for p, m, h in T.BANG if p == pt and m.match(duong)], [ham], duong)
		self.assertEqual(self._http("Guest", "POST", "/api/einvoice/publish", {"invoiceId": "x"}), (401, {"error": "Chưa đăng nhập."}))
		for pt, duong in (("POST", "/api/einvoice/sync"), ("GET", "/api/einvoice/pull-snapshots"), ("GET", "/api/cron/daily")):
			self.assertEqual(self._http(self.ma["u:owner"], pt, duong), (501, {"error": f"Chức năng {pt} {duong} chưa chuyển sang bản Frappe."}))
		self.goi("owner", M.cau_hinh_luu, CAU_HINH_CHUAN)
		ma, kq = self._http(self.ma["u:owner"], "GET", "/api/einvoice/config")
		self.assertEqual((ma, kq["config"]["api_base"], kq["config"]["has_password"]), (200, API, True))
		self.assertEqual(self._http(self.ma["u:manager"], "POST", "/api/einvoice/refresh-status", {}), (400, {"error": "Thiếu invoiceId"}))


# =====================================================================================================================================
# KV-18 (b), KV-30 (b) — kết nối / luồng THẬT, commit THẬT
# =====================================================================================================================================
class TestHaiKetNoi(IntegrationTestCase):
	"""KV-18 (b) [=] + KV-30 (b) [≠ BP §7.3-10] (khuôn PoC 1d / TestDamBaoDongDocCoKhoa của test_cong_hddt): dữ liệu TỐI THIỂU (cấu hình MISA + một
	tờ tay) commit trước, dọn sạch trong cleanup (dòng, nhật ký, Version, cấu hình, Error Log của bài). Site đã có cấu hình MISA thật → bỏ qua (không
	đụng). Vai: `misa.hien_tai` → chủ (bài không dựng người)."""

	def setUp(self):
		frappe.db.rollback()
		if frappe.db.sql("SELECT 1 FROM `tabSingles` WHERE `doctype` = %s LIMIT 1", CH.TEN) or frappe.db.sql(
				"SELECT 1 FROM `__Auth` WHERE `doctype` = %s LIMIT 1", CH.TEN):
			self.skipTest("site đã có cấu hình MISA — bài commit thật không chạy để khỏi đụng cấu hình thật")
		self.bat_dau = frappe.db.sql("SELECT NOW(6)")[0][0]
		MM.xoa_token_nho()
		self.addCleanup(MM.xoa_token_nho)
		p = patch.object(M, "hien_tai", lambda: NguCanh(user=frappe.session.user, vai="owner"))
		p.start()
		self.addCleanup(p.stop)
		self.addCleanup(self._don)
		d = frappe.get_doc(CH.TEN)
		d.update({"dia_chi_api": API, "mst_nguoi_ban": MST, "tai_khoan": "u-thu", "mat_khau": "p-thu", "misa_inv_series": "1C26TAA"})
		d.save(ignore_permissions=True)
		self.e = dong_hddt(nguoi_mua="Tờ hai kết nối", tien_hang=1000, tien_thue=100, tong_tien=1100)
		frappe.db.commit()

	def _don(self):
		frappe.db.rollback()
		e = getattr(self, "e", None)
		if e:
			frappe.db.sql("DELETE FROM `tabNPP MISA Log` WHERE `hddt` = %s", e)
			frappe.db.sql("DELETE FROM `tabNPP HDDT` WHERE `name` = %s", e)
		frappe.db.sql("DELETE FROM `tabVersion` WHERE `ref_doctype` IN ('NPP HDDT', %s) AND `creation` >= %s", (CH.TEN, self.bat_dau))
		frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)
		frappe.db.sql("DELETE FROM `__Auth` WHERE `doctype` = %s", CH.TEN)
		frappe.db.sql("DELETE FROM `tabError Log` WHERE `creation` >= %s AND `method` LIKE 'HĐĐT MISA%%'", self.bat_dau)
		frappe.db.commit()
		frappe.clear_document_cache(CH.TEN, CH.TEN)

	def _mang(self, *kich_ban, khi_goi=None) -> AdapterHddt:
		a = AdapterHddt(kich_ban, khi_goi)
		s = _PHIEN_THAT()
		s.mount("https://", a)
		p = patch.object(MM, "_phien", lambda: s)
		p.start()
		self.addCleanup(p.stop)
		return a

	def test_kv30b_ket_noi_khac_thay_pending_khong_bi_chan(self):
		"""Lúc POST /v3sainvoice bay đi, kết nối THỨ HAI `SELECT … FOR UPDATE NOWAIT` không bị chặn (không khoá nào bị giữ trong lúc chờ HTTP) và thấy
		dòng ĐÃ `pending` + RefID (đã commit TRƯỚC khi byte nào tới MISA). Thử phá: bỏ commit giành tờ → kết nối kia bị chặn / không thấy → đỏ."""
		chinh = frappe.local.db
		frappe.connect(set_admin_as_user=False)
		kn2 = frappe.local.db
		frappe.local.db = chinh
		self.addCleanup(kn2.close)
		thay = []

		def khi_goi(req):
			if "/v3sainvoice" not in req.url:
				return
			frappe.local.db = kn2
			try:
				kn2.rollback()
				thay.append(kn2.sql("SELECT `misa_status`, `misa_ref_id` FROM `tabNPP HDDT` WHERE `name` = %s FOR UPDATE NOWAIT", self.e))
				kn2.rollback()
			except Exception as e:  # khoá còn bị giữ → NOWAIT ném ngay
				thay.append(e)
				kn2.rollback()
			finally:
				frappe.local.db = chinh

		self._mang(TOK, tra_map(), khi_goi=khi_goi)
		trong_test = frappe.flags.in_test
		frappe.flags.in_test = False
		try:
			ma, kq = M.phat_hanh(YeuCauCu(duong="/api/einvoice/publish", phuong_thuc="POST", than={"invoiceId": self.e}))
			frappe.db.commit()  # cuối request (tuyen.goi)
		finally:
			frappe.flags.in_test = trong_test
		self.assertEqual(ma, 200, kq)
		ref = frappe.db.get_value("NPP HDDT", self.e, "misa_ref_id")
		self.assertEqual(thay, [(("pending", ref),)])

	def test_kv18b_hai_luong_cung_phat_hanh(self):
		"""Hai luồng (hai kết nối, commit thật) cùng bấm Phát hành một tờ — cả hai qua bước 4 (rào ở lời /oauth), xếp hàng ở khoá dòng bước 9: một 200,
		một 409; MISA nhận ĐÚNG MỘT POST /v3sainvoice (adapter giữ POST 2 s); một nhật ký publish."""
		import time

		site, sites_path = frappe.local.site, frappe.local.sites_path
		rao = threading.Barrier(2, timeout=30)

		def tra(req):
			if req.url.endswith("/oauth"):
				return TOK
			if req.method == "POST":
				time.sleep(2)
				return tra_map()
			return RONG

		def khi_goi(req):
			if req.url.endswith("/oauth"):
				rao.wait()  # cả hai luồng đã qua bước 3–4 (đọc thường) trước khi bên nào giành tờ

		a = self._mang(*[tra] * 8, khi_goi=khi_goi)
		ket = {}

		def chay(ten):
			try:
				frappe.init(site=site, sites_path=sites_path)
				frappe.connect()
				# `frappe.init` chép cờ `frappe.in_test` (toàn cục, bật khi chạy bài) vào `flags` của luồng → `commit_giua_chung` thành không làm gì,
				# lượt đầu giữ khoá dòng tới hết request và lượt sau chỉ thấy `sent` ⇒ bài xanh cả khi chốt giành tờ hỏng. Tắt để commit THẬT như
				# production: lượt sau thấy `pending` đã commit trong lúc lượt đầu đang chờ POST.
				frappe.flags.in_test = False
				frappe.set_user("Administrator")
				ket[ten] = M.phat_hanh(YeuCauCu(duong="/api/einvoice/publish", phuong_thuc="POST", than={"invoiceId": self.e}))
				frappe.db.commit()
			except BaseException as e:  # báo về luồng chính
				ket[ten] = e
			finally:
				frappe.destroy()

		luong = [threading.Thread(target=chay, args=(t,)) for t in ("a", "b")]
		for t in luong:
			t.start()
		for t in luong:
			t.join(60)
		self.assertEqual(sorted(k[0] if isinstance(k, tuple) else repr(k) for k in ket.values()), [200, 409], ket)
		self.assertEqual([k[1] for k in ket.values() if k[0] == 409], [{"error": "Hoá đơn đang được xử lý hoặc đã phát hành. Thử lại sau giây lát."}])
		self.assertEqual(sorted(gon(a)), ["POST /oauth", "POST /oauth", "POST /v3sainvoice"])
		self.assertEqual(a.vi_pham, [])  # I11
		frappe.db.rollback()
		r = frappe.db.get_value("NPP HDDT", self.e, ["misa_status", "misa_ref_id", "trang_thai"], as_dict=True)
		self.assertEqual((r.misa_status, r.trang_thai, bool(r.misa_ref_id)), ("sent", "issued", True))
		self.assertEqual(frappe.db.count("NPP MISA Log", {"hddt": self.e, "nguon": "publish"}), 1)
