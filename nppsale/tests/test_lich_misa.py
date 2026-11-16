"""Việc nền HĐĐT MISA (`nppsale/lich/misa.py`: vòng quét hai lượt + kéo snapshot + khớp bốn tầng) và khám sổ HĐĐT (`nppsale.kham_so.hddt`) —
đặc tả HĐĐT §5, §6.3, §6.4, §8.1 Nhóm E (KV-37 … KV-40), Nhóm F (KV-41 … KV-43), ca lịch / khám sổ của Nhóm K (KV-51 phần khám, KV-53, KV-57) và
ca Nhóm I do lịch gây ra (khoá Huỷ HĐ sau khi vòng quét đổi trạng thái tờ — bảng KV-48 đủ trạng thái ở test_hddt_khoa). Cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_lich_misa

Nền: `_NenPhatHanh` của test_hddt (dữ liệu vàng xuất hàng — HĐ bán `self.hd`; cấu hình MISA lưu qua route dưới CHU: api https://misa.gia/api/v2,
MST 0100000000, tài khoản / mật khẩu chữ bịa u-thu / p-thu, không mã, 1C26TAA; giờ ghim `luc` = 15/11/2026 10:00 giờ VN; token RAM sạch; bất biến
I1–I6 / I11 cuối MỖI bài). MISA là adapter giả (không gọi mạng). Dòng HĐĐT dựng thẳng đúng trạng thái kịch bản (không qua phát hành).

Lệch có chủ ý so với nppsale (bài khai): H14 (cửa sổ GREATEST — KV-37 tờ Y), H15 (một /oauth đầu lượt; hết hạn giữa lượt một lời, hỏng thì dừng —
KV-40 a), H5 (treo quá 10 phút → error; MISA có tờ treo → xác nhận đẩy), lượt 2 quét cả `misa_status` trống (KV-37 tờ U), ngày cửa sổ snapshot +
ngày khớp của sổ theo giờ VN (KV-41, KV-43 tờ b8), khử trùng RefID trong lượt kéo (KV-57), `publish_status` chữ ('3.5' không làm hỏng lô), ghi một
snapshot hỏng không đếm, nhật ký lượt `sync_run` / `pull_snapshots`, lỗi một lượt bọc riêng (khoá tệp, RQ cắt việc không bị nuốt).
"""
from __future__ import annotations

import datetime
import json
import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, parse_qsl, urlparse

import frappe
import requests
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from nppsale import kham_so as KS
from nppsale.api import misa as M
from nppsale.api import misa_mang as MM
from nppsale.lich import misa as L
from nppsale.npp_hddt.doctype.npp_misa_cau_hinh import npp_misa_cau_hinh as CH
from nppsale.tests.test_hddt import (
	_PHIEN_THAT,
	API,
	LUC,
	MST,
	RONG,
	TOK,
	AdapterHddt,
	_NenPhatHanh,
	get_ban_ghi,
	gon,
	hd_app,
)
from nppsale.tests.test_hddt_khoa import CHO_MISA, DA_PHAT_HANH, dong_hddt
from nppsale.tests.test_misa_mang import cho_phep_misa_gia

NGAY = datetime.timedelta(days=1)
PHUT = datetime.timedelta(minutes=1)
TOK_HONG = {"body": {"error": "invalid_grant", "error_description": "Sai tài khoản hoặc mật khẩu", "status": 401}}
CAU_TOK_HONG = "MISA token lỗi 401: Sai tài khoản hoặc mật khẩu (invalid_grant)"
COT_NHANH = ("nguoi_mua", "trang_thai", "tien_hang", "tien_thue", "tong_tien", "hoa_don_ban", "misa_ref_id", "misa_inv_no", "misa_inv_series",
	"misa_status", "misa_no_locked", "misa_last_checked_at", "phat_hanh_luc", "misa_sent_at", "misa_note", "misa_error")
COT_KHOP = ("hddt", "cach_khop", "do_tin", "ket_qua_khop", "ghi_chu_khop")


def ref_cua(url: str) -> str | None:
	return (parse_qs(urlparse(url).query).get("refID") or [None])[0]


def hoi(a: AdapterHddt) -> list:
	"""RefID của các lời GET ?refID= theo thứ tự bay đi."""
	return [ref_cua(u) for m, u, _h, _b in a.goi if m == "GET"]


def misa_gia(get=None, trang=None, oauth=None):
	"""MỘT hàm trả lời mọi lời gọi (AdapterHddt nhận hàm `f(request)`): /oauth → `oauth` (mặc định TOK); GET ?refID= → `get(ref)` (kịch bản
	{"body"…} / {"status", "body"} / ngoại lệ; None → không có tờ); POST …/paging → `trang(start, form)`; lời khác → AssertionError."""

	def f(req):
		u = urlparse(req.url)
		if u.path.endswith("/oauth"):
			return oauth or TOK
		if req.method == "GET" and "/v3sainvoice/" in u.path:
			kq = get(ref_cua(req.url)) if get else None
			return RONG if kq is None else kq
		if req.method == "POST" and u.path.endswith("/paging"):
			than = req.body.decode() if isinstance(req.body, bytes) else req.body
			return trang(int(dict(parse_qsl(than))["start"]))
		raise AssertionError(f"lời gọi MISA lạ: {req.method} {req.url}")

	return f


def trang_ds(ds: list, tong=None, *, tho: str | None = None) -> dict:
	"""Một trang danh sách MISA: `data` = chuỗi JSON mảng (`tho` = chuỗi méo), + `recordsTotal` khi có."""
	than = {"success": True, "data": tho if tho is not None else json.dumps(ds, ensure_ascii=False)}
	if tong is not None:
		than["recordsTotal"] = tong
	return {"body": than}


def bg(ref, so=None, *, ky_hieu="1C26TAA", ngay="2026-11-10T00:00:00", tong=1000, bo=(), **them) -> dict:
	"""Một bản ghi danh sách MISA (`so` None → chỗ giữ chỗ `<Chưa cấp số>`; `bo` = khoá bỏ hẳn)."""
	d = {"RefID": ref, "InvSeries": ky_hieu, "InvNo": so if so is not None else "<Chưa cấp số>", "InvDate": ngay, "PublishStatus": 3,
		"EInvoiceStatus": 1, "TotalAmount": tong, "TotalAmountWithoutVAT": 0.0, "TotalVATAmount": 0.0, **them}
	return {k: v for k, v in d.items() if k not in bo}


def chen_nhanh(ds: list[dict]) -> list[str]:
	"""Chèn nhanh nhiều dòng HĐĐT thẳng bảng (KV-37: 250+ tờ) — đúng quy ước hàm ghi: khoá trống NULL, có số mà không ký hiệu → ''."""
	luc = frappe.utils.now_datetime()
	cot = ["name", "creation", "modified", "modified_by", "owner", "docstatus", "idx", *COT_NHANH]
	ten, gt = [], []
	for d in ds:
		r = {"nguoi_mua": "Tạp hoá A", "trang_thai": "draft", "tien_hang": 0, "tien_thue": 0, "tong_tien": 0, "misa_no_locked": 0, **d}
		if r.get("misa_inv_no") and r.get("misa_inv_series") is None:
			r["misa_inv_series"] = ""
		t = str(uuid.uuid4())
		ten.append(t)
		gt.append([t, luc, luc, "Administrator", "Administrator", 0, 0, *(r.get(c) for c in COT_NHANH)])
	frappe.db.bulk_insert("NPP HDDT", cot, gt)
	return ten


def anh_hddt() -> dict:
	return {r.name: dict(r) for r in frappe.db.sql("SELECT * FROM `tabNPP HDDT`", as_dict=True)}


class _NenLich(_NenPhatHanh):
	"""+ dọn Error Log khoá tệp của lõi (bảng MyISAM — không lui theo giao dịch); tiện ích MISA giả / nhật ký lượt / snapshot."""

	def tearDown(self):
		try:
			super().tearDown()
		finally:
			frappe.db.sql("DELETE FROM `tabError Log` WHERE `creation` > %s AND `method` LIKE 'Filelock:%%'", self.loi_truoc)

	def misa(self, f, n: int = 1000, khi_goi=None) -> AdapterHddt:
		return self.mang(*([f] * n), khi_goi=khi_goi)

	def luot(self, nguon: str = "sync_run") -> tuple:
		"""Dòng nhật ký lượt MỚI NHẤT của `nguon` → (dòng, nhan_ve đã giải)."""
		nk = self.nhat_ky(nguon=nguon)
		self.assertTrue(nk, f"không có nhật ký {nguon}")
		return nk[-1], json.loads(nk[-1].nhan_ve)

	def co_ma(self):
		frappe.db.set_single_value(CH.TEN, "misa_is_invoice_with_code", 1)
		frappe.clear_document_cache(CH.TEN, CH.TEN)

	def snap(self, ref: str) -> frappe._dict:
		return frappe.db.get_value("NPP MISA Snapshot", {"ref_id": ref}, ["*"], as_dict=True)

	def snapshot_san(self, ref: str, **kv) -> str:
		"""Một dòng snapshot có sẵn (lượt kéo trước / người chốt tay)."""
		return frappe.get_doc({"doctype": "NPP MISA Snapshot", "ref_id": ref, "keo_luc": LUC - NGAY, "ban_ghi_tho": json.dumps({"RefID": ref}),
			**kv}).insert(ignore_permissions=True).name


# =====================================================================================================================================
# Nhóm E — vòng quét trạng thái (§5.2)
# =====================================================================================================================================
class TestVongQuet(_NenLich):
	def test_kv37_hai_luot_thu_tu_tran_cua_so(self):
		"""KV-37 [= trừ H14 + lượt 2 quét trạng thái trống]: 250 tờ có RefID chưa số trong cửa sổ (50 chưa hỏi lần nào, 200 mốc hỏi tăng dần) → lượt
		1 hỏi ĐÚNG 200: 50 tờ chưa hỏi trước, rồi theo mốc hỏi tăng dần; X (phát hành 70 ngày trước, chưa gửi) không bị hỏi dù mốc hỏi trống (đứng đầu
		nếu lọt cửa sổ); Y (khoá HĐ 90 ngày trước, gửi MISA hôm qua) ĐƯỢC hỏi (GREATEST — COALESCE thì không); lượt 2: V (signed) và U (trạng thái
		trống) được hỏi, Z (huỷ trên MISA) / Q (bị thay thế) / W (khoá gán tay) không. MISA không có tờ nào → tờ được hỏi CHỈ đổi mốc hỏi (kể cả
		`modified` giữ); nhật ký `sync_run`. Lượt kế (hôm sau) hỏi phần còn lại trước, token RAM của lượt trước còn hạn → không /oauth."""
		tre = LUC - 5 * NGAY
		nen = {"misa_status": "sent", "trang_thai": "issued", "phat_hanh_luc": tre, "misa_sent_at": tre}
		a = [{**nen, "misa_ref_id": f"A-{i:03d}"} for i in range(50)]
		b = [{**nen, "misa_ref_id": f"B-{i:03d}", "misa_last_checked_at": LUC - 30 * NGAY + i * PHUT} for i in range(200)]
		khac = [
			{"misa_ref_id": "X", "misa_status": "sent", "trang_thai": "issued", "phat_hanh_luc": LUC - 70 * NGAY},
			{"misa_ref_id": "Y", "misa_status": "sent", "trang_thai": "issued", "phat_hanh_luc": LUC - 90 * NGAY, "misa_sent_at": LUC - NGAY,
				"misa_last_checked_at": LUC - 40 * NGAY},
			{**nen, "misa_ref_id": "Z", "misa_status": "cancelled", "misa_inv_no": "00000901", "misa_inv_series": "1C26TAA"},
			{**nen, "misa_ref_id": "Q", "misa_status": "replaced", "misa_inv_no": "00000905", "misa_inv_series": "1C26TAA"},
			{**nen, "misa_ref_id": "W", "misa_status": "signed", "misa_no_locked": 1, "misa_inv_no": "00000902", "misa_inv_series": "1C26TAA"},
			{**nen, "misa_ref_id": "V", "misa_status": "signed", "misa_inv_no": "00000903", "misa_inv_series": "1C26TAA"},
			{**nen, "misa_ref_id": "U", "misa_status": None, "misa_inv_no": "00000904", "misa_last_checked_at": LUC - 50 * NGAY},
		]
		chen_nhanh(a + b + khac)
		truoc = anh_hddt()
		a1 = self.misa(misa_gia())
		bao = L.dong_bo_trang_thai()
		h = hoi(a1)
		self.assertEqual(gon(a1)[0], "POST /oauth")
		self.assertEqual(gon(a1).count("POST /oauth"), 1)  # H15: một lời /oauth cho cả lượt
		self.assertEqual(len(h), 202)
		self.assertEqual(set(h[:50]), {f"A-{i:03d}" for i in range(50)})
		self.assertEqual(h[50], "Y")
		self.assertEqual(h[51:200], [f"B-{i:03d}" for i in range(149)])
		self.assertEqual(h[200:], ["V", "U"])
		sau = anh_hddt()
		for ten, r in sau.items():
			cu = truoc[ten]
			if r["misa_ref_id"] in h:
				self.assertEqual(r["misa_last_checked_at"], LUC, r["misa_ref_id"])
				self.assertEqual({k: v for k, v in r.items() if k != "misa_last_checked_at"},
					{k: v for k, v in cu.items() if k != "misa_last_checked_at"}, r["misa_ref_id"])
			else:
				self.assertEqual(r, cu, r["misa_ref_id"])
		nk, nv = self.luot()
		self.assertEqual((nk.ket_qua, nk.hddt, nk.loi), ("success", None, None))
		self.assertEqual({k: nv[k] for k in ("orgs", "checked", "updated", "originals_marked_replaced", "treo_thanh_loi", "luot_1", "luot_2",
			"errors")}, {"orgs": 1, "checked": 202, "updated": 0, "originals_marked_replaced": 0, "treo_thanh_loi": 0, "luot_1": 200, "luot_2": 2,
			"errors": []})
		self.assertEqual(bao["checked"], 202)
		self.assertEqual(self.nhat_ky(nguon="sync"), [])  # tờ không có chuyện đáng nói thì không nhật ký từng tờ
		# lượt kế: phần còn lại (B-149 … B-199, mốc cũ nhất) trước
		self.luc = LUC + NGAY
		a2 = self.misa(misa_gia())
		L.dong_bo_trang_thai()
		h2 = hoi(a2)
		self.assertNotIn("POST /oauth", gon(a2))
		self.assertEqual(len(h2), 202)
		self.assertEqual(h2[:51], [f"B-{i:03d}" for i in range(149, 200)])
		self.assertEqual(sorted(h2[200:]), ["U", "V"])
		self.assertEqual(frappe.db.get_value("NPP HDDT", {"misa_ref_id": "B-199"}, "misa_last_checked_at"), LUC + NGAY)

	def test_kv38_huy_sau_khi_da_cap_so(self):
		"""KV-38 [= trừ H7]: E (`signed`, 00000123, sổ 110.000) — lượt 2 hỏi, MISA báo ĐÃ HUỶ + lệch tiền → `cancelled` (lệch không đè trạng thái
		cuối), số giữ, ghi chú thêm hai dòng; nhật ký `sync` một dòng; đêm sau lượt 2 BỎ E (0 lời gọi); HĐ bán vẫn LOCKED_EINVOICE (H12)."""
		e = dong_hddt(hoa_don_ban=self.hd, don_hang=self.don, trang_thai="issued", misa_status="signed", misa_ref_id="R38",
			misa_inv_no="00000123", misa_inv_series="1C26TAA", tong_tien=110000, phat_hanh_luc=LUC - 2 * NGAY, misa_sent_at=LUC - 2 * NGAY,
			misa_note="ghi chú cũ")
		a = self.misa(misa_gia(get=lambda ref: get_ban_ghi(IsInvoiceDeleted=True, DeletedReason="Sai giá", InvNo="00000123", PublishStatus=3,
			TotalAmount=99000) if ref == "R38" else None))
		L.dong_bo_trang_thai()
		self.assertEqual(gon(a), ["POST /oauth", "GET /v3sainvoice/?refID=R38"])
		r = self.dong(e)
		hai = ["MISA báo hoá đơn ĐÃ HUỶ (IsInvoiceDeleted) — lý do: Sai giá.", "Lệch tiền với MISA — Tổng tiền: sổ 110000, MISA 99000."]
		self.assertEqual((r.misa_status, r.misa_inv_no, r.misa_note, r.misa_last_checked_at), ("cancelled", "00000123",
			"\n".join(["ghi chú cũ", *hai]), LUC))
		nk = self.nhat_ky(nguon="sync")
		self.assertEqual(len(nk), 1)
		self.assertEqual((nk[0].hddt, json.loads(nk[0].gui_di), nk[0].ket_qua, nk[0].loi, nk[0].misa_inv_no, nk[0].don_hang),
			(e, {"source": "sync", "ref_id": "R38"}, "success", "\n".join(hai), "00000123", self.don))
		self.assertEqual(json.loads(nk[0].nhan_ve)["DeletedReason"], "Sai giá")
		_l, nv = self.luot()
		self.assertEqual((nv["checked"], nv["updated"], nv["luot_2"]), (1, 1, 1))
		a2 = self.misa(misa_gia())
		L.dong_bo_trang_thai()
		self.assertEqual(a2.goi, [])  # không tờ nào để hỏi → không cả /oauth
		self.assertEqual(self._huy()["error"]["message"], DA_PHAT_HANH)

	def test_kv39_mot_to_loi_khong_keo_ca_luot(self):
		"""KV-39 [= + nhật ký lượt]: ba tờ lượt 1 — t1 MISA đã cấp số → `signed` (KHÔNG ghi misa_signed_at / misa_published_at / misa_invoice_url —
		chỉ phát hành ghi [=]); t2 GET 500 → errors, dòng không đổi gì NGOÀI mốc hỏi [≠ — phát hiện 10: MISA TRẢ LỜI lỗi vẫn ghi mốc để hàng đợi xoay
		vòng]; t3 không có → chỉ mốc hỏi. Commit sau MỖI tờ (đếm lúc từng lời GET bay đi: 0, 1, 2) — tờ hỏng không cuộn lại tờ trước."""
		t = {k: dong_hddt(misa_ref_id=k, misa_status="sent", trang_thai="issued", phat_hanh_luc=LUC - NGAY, tong_tien=50000)
			for k in ("t-1", "t-2", "t-3")}
		tra = {"t-1": get_ban_ghi(InvNo="00000777", InvSeries="1C26TAA", InvDate="2026-11-14T00:00:00", PublishStatus=3, EInvoiceStatus=1,
			TransactionID="TX7", TotalAmount=50000), "t-2": {"status": 500, "body": "boom"}}
		dem = {"commit": 0}
		luc_get = []
		p = patch.object(M, "commit_giua_chung", lambda: dem.__setitem__("commit", dem["commit"] + 1))
		p.start()
		self.addCleanup(p.stop)
		self.misa(misa_gia(get=tra.get), khi_goi=lambda req: luc_get.append(dem["commit"]) if req.method == "GET" else None)
		truoc_t2 = self.dong(t["t-2"])
		L.dong_bo_trang_thai()
		self.assertEqual(luc_get, [0, 1, 2])
		r1 = self.dong(t["t-1"])
		self.assertEqual((r1.misa_status, r1.misa_inv_no, r1.misa_inv_series, str(r1.misa_inv_date), r1.misa_lookup_code, r1.misa_relation,
			r1.misa_last_checked_at), ("signed", "00000777", "1C26TAA", "2026-11-14", "TX7", "new", LUC))
		self.assertEqual((r1.misa_signed_at, r1.misa_published_at, r1.misa_invoice_url), (None, None, None))
		r2 = self.dong(t["t-2"])
		self.assertEqual({k: v for k, v in r2.items() if k != "misa_last_checked_at"}, {k: v for k, v in truoc_t2.items() if k != "misa_last_checked_at"})
		self.assertEqual((truoc_t2.misa_last_checked_at, r2.misa_last_checked_at), (None, LUC))
		self.assertEqual(self.dong(t["t-3"]).misa_last_checked_at, LUC)
		nk, nv = self.luot()
		self.assertEqual((nk.ket_qua, nv["checked"], nv["updated"], nv["originals_marked_replaced"], nv["errors"]),
			("success", 3, 1, 0, [{"invoice_id": t["t-2"], "message": "Lấy HD lỗi 500: boom"}]))
		self.assertEqual(nk.loi, f"{t['t-2']}: Lấy HD lỗi 500: boom")

	def test_kv40a_token_hong_mot_loi(self):
		"""KV-40 (a) [≠ H15]: mật khẩu sai, 150 tờ chờ hỏi → MỘT lời /oauth, 0 GET, một lỗi, `bo_qua_vi_token` 150, nhật ký `failed`, không dòng nào
		đổi (nppsale: 150 lời /oauth, 150 lỗi — nguy cơ MISA khoá tài khoản)."""
		chen_nhanh([{"misa_ref_id": f"K-{i:03d}", "misa_status": "sent", "phat_hanh_luc": LUC - NGAY} for i in range(150)])
		truoc = anh_hddt()
		a = self.misa(misa_gia(oauth=TOK_HONG))
		L.dong_bo_trang_thai()
		self.assertEqual(gon(a), ["POST /oauth"])
		self.assertEqual(anh_hddt(), truoc)
		nk, nv = self.luot()
		self.assertEqual((nk.ket_qua, nv["errors"], nv["bo_qua_vi_token"], nv["checked"], nv["luot_1"], nk.loi),
			("failed", [{"message": CAU_TOK_HONG}], 150, 0, 150, CAU_TOK_HONG))

	def test_h15_token_het_han_giua_luot(self):
		"""[ĐX H15] token sống 60 s (expires_in 120 − 60) hết hạn sau tờ đầu: tờ kế lấy token MỘT lời — hỏng ⇒ DỪNG lượt (không /oauth cho từng tờ
		còn lại): `bo_qua_vi_token` 2, `failed`; tờ đầu đã ghi giữ nguyên."""
		chen_nhanh([{"misa_ref_id": f"H-{i}", "misa_status": "sent", "phat_hanh_luc": LUC - NGAY} for i in range(3)])
		lan = {"oauth": 0}

		def oauth_lan():
			lan["oauth"] += 1
			return {"body": {"access_token": "T1", "expires_in": 120}} if lan["oauth"] == 1 else TOK_HONG

		def f(req):
			if req.url.endswith("/oauth"):
				return oauth_lan()
			return misa_gia()(req)

		def khi_goi(req):
			if req.method == "GET":
				self.gio += 100  # đồng hồ đơn điệu giả: qua hạn token sau lời GET đầu

		a = self.misa(f, khi_goi=khi_goi)
		L.dong_bo_trang_thai()
		self.assertEqual([g.split("?")[0] for g in gon(a)], ["POST /oauth", "GET /v3sainvoice/", "POST /oauth"])
		nk, nv = self.luot()
		self.assertEqual((nk.ket_qua, nv["checked"], nv["bo_qua_vi_token"], nv["errors"]), ("failed", 1, 2, [{"message": CAU_TOK_HONG}]))
		self.assertEqual(frappe.db.get_value("NPP HDDT", {"misa_ref_id": hoi(a)[0]}, "misa_last_checked_at"), LUC)

	def test_h5_xac_nhan_day_va_khoa_huy_hd(self):
		"""§5.2 bước 4 + Nhóm I của lịch: (a) tờ `pending` gửi 11 phút trước, MISA KHÔNG có → `error` + câu H5 + mốc hỏi; Huỷ HĐ bán QUA (vế khoá
		không gồm `error`); (b) gửi 5 phút trước → giữ `pending`, chỉ mốc hỏi; Huỷ HĐ → "đang chờ MISA" (H2); (c) MISA CÓ tờ treo → xác nhận đẩy:
		`sent` + `issued` + `phat_hanh_luc` = lúc quét + `misa_error` xoá; Huỷ HĐ → "đã phát hành"."""
		ca = {
			"a": (LUC - 11 * PHUT, None, {"misa_status": "error", "misa_error": M.LOI_LM_TREO, "trang_thai": "draft", "phat_hanh_luc": None}, None),
			"b": (LUC - 5 * PHUT, None, {"misa_status": "pending", "misa_error": "chưa biết MISA nhận chưa — bấm Làm mới trạng thái",
				"trang_thai": "draft", "phat_hanh_luc": None}, CHO_MISA),
			"c": (LUC - 5 * PHUT, get_ban_ghi(InvNo="<Chưa cấp số>", PublishStatus=0, TotalAmount=0), {"misa_status": "sent", "misa_error": None,
				"trang_thai": "issued", "phat_hanh_luc": LUC}, DA_PHAT_HANH),
		}
		for nhan, (gui, tra, mong, khoa) in ca.items():
			frappe.db.savepoint("lich_ca")
			try:
				e = dong_hddt(hoa_don_ban=self.hd, misa_ref_id=f"R-{nhan}", misa_status="pending", misa_sent_at=gui,
					misa_error="chưa biết MISA nhận chưa — bấm Làm mới trạng thái")
				self.misa(misa_gia(get=lambda ref, tra=tra: tra))
				bao = L.dong_bo_trang_thai()
				r = self.dong(e)
				self.assertEqual({k: r[k] for k in mong}, mong, nhan)
				self.assertEqual(r.misa_last_checked_at, LUC, nhan)
				self.assertEqual((bao["treo_thanh_loi"], bao["updated"]), ((1, 0) if nhan == "a" else (0, 1) if nhan == "c" else (0, 0)), nhan)
				ket = self._huy()
				self.assertEqual((ket.get("error") or {}).get("message"), khoa, nhan)
			finally:
				frappe.db.rollback(save_point="lich_ca")
				frappe.local._npp_ngu_canh = None

	def test_danh_dau_goc_trung_so_nhat_ky_hong(self):
		"""§5.2 bước 4: bản THAY THẾ đánh dấu tờ gốc (`originals_marked_replaced`); tờ có số MISA đụng chỉ mục (ký hiệu, số) của tờ khác → errors câu
		409 của Làm mới, dòng không đổi, chạy tiếp; ghi nhật ký `sync` hỏng → errors "Không ghi được nhật ký hoá đơn: …" (KHÔNG best-effort) nhưng tờ
		vẫn ghi; đánh dấu tờ gốc hỏng → errors, phần ghi chính giữ."""
		goc = dong_hddt(misa_ref_id="goc-1", misa_status="signed", misa_inv_no="00000100", misa_inv_series="1C26TAA", trang_thai="issued",
			phat_hanh_luc=LUC - 3 * NGAY, misa_last_checked_at=LUC - PHUT)
		thay = dong_hddt(misa_ref_id="thay-1", misa_status="sent", trang_thai="issued", phat_hanh_luc=LUC - NGAY, tong_tien=70000)
		dong_hddt(misa_inv_no="00000555", misa_inv_series="1C26TAA", trang_thai="issued")  # tờ khác đang giữ số
		trung = dong_hddt(misa_ref_id="trung-1", misa_status="sent", trang_thai="issued", phat_hanh_luc=LUC - NGAY, tong_tien=1)
		lech = dong_hddt(misa_ref_id="lech-1", misa_status="sent", trang_thai="issued", phat_hanh_luc=LUC - NGAY, tong_tien=1000)
		tra = {"thay-1": get_ban_ghi(InvNo="00000124", InvSeries="1C26TAA", PublishStatus=3, EInvoiceStatus=3, OrgRefID="goc-1", TotalAmount=70000),
			"trung-1": get_ban_ghi(InvNo="00000555", InvSeries="1C26TAA", PublishStatus=3, EInvoiceStatus=1, TotalAmount=1),
			"lech-1": get_ban_ghi(InvNo="00000600", InvSeries="1C26TAA", PublishStatus=3, EInvoiceStatus=1, TotalAmount=5000)}
		truoc = self.dong(trung)
		self.misa(misa_gia(get=tra.get))
		goc_ghi = M.ghi_nhat_ky

		def ghi_hong(nguon, *a, **k):
			if nguon == "sync":
				raise RuntimeError("bảng nhật ký khoá")
			return goc_ghi(nguon, *a, **k)

		with patch.object(M, "ghi_nhat_ky", ghi_hong):
			L.dong_bo_trang_thai()
		self.assertEqual((self.dong(goc).misa_status, self.dong(goc).misa_relation), ("replaced", "replaced"))
		self.assertEqual((self.dong(thay).misa_relation, self.dong(thay).misa_status), ("replacement", "signed"))
		self.assertEqual(self.dong(trung), truoc)
		r = self.dong(lech)
		self.assertEqual((r.misa_status, r.misa_inv_no, r.misa_note), ("amount_mismatch", "00000600",
			"Lệch tiền với MISA — Tổng tiền: sổ 1000, MISA 5000."))
		self.assertEqual(self.nhat_ky(nguon="sync"), [])
		_nk, nv = self.luot()
		self.assertEqual((nv["originals_marked_replaced"], nv["updated"]), (1, 2))  # thay + lech (goc: MISA không có → chỉ mốc; trung hỏng)
		self.assertEqual(sorted((e["invoice_id"], e["message"]) for e in nv["errors"]), sorted([
			(trung, "Số HĐĐT 1C26TAA · 00000555 MISA trả về đã có ở một hoá đơn khác trong sổ — kiểm tra trùng trước khi làm mới lại."),
			(lech, "Không ghi được nhật ký hoá đơn: bảng nhật ký khoá")]))
		# đánh dấu tờ gốc hỏng → errors (phần ghi chính giữ); nhật ký `sync` của tờ lệch tiền lần này ghi được
		frappe.db.set_value("NPP HDDT", goc, {"misa_status": "signed", "misa_relation": None}, update_modified=False)
		frappe.db.set_value("NPP HDDT", thay, {"misa_inv_no": None, "misa_inv_series": None, "misa_status": "sent"}, update_modified=False)
		self.misa(misa_gia(get=tra.get))
		with patch.object(M, "danh_dau_goc", side_effect=RuntimeError("khoá tờ gốc")):
			L.dong_bo_trang_thai()
		_nk, nv = self.luot()
		self.assertIn({"invoice_id": thay, "message": "Không đánh dấu được tờ gốc bị thay thế: khoá tờ gốc"}, nv["errors"])
		self.assertEqual((self.dong(thay).misa_inv_no, self.dong(goc).misa_status), ("00000124", "signed"))
		self.assertEqual([(x.hddt, x.loi) for x in self.nhat_ky(nguon="sync")], [(lech, "Lệch tiền với MISA — Tổng tiền: sổ 1000, MISA 5000.")])

	def test_moc_hoi_khong_giam_va_ghi_moc_hong(self):
		"""I10: lượt chạy chậm (mốc hỏi của tờ đã muộn hơn `luc` — lượt song song) không lùi mốc. Ghi mốc hỏng → errors "Không ghi được mốc đã hỏi".
		Câu lượt hỏng → "Lượt 1 lỗi: …", lượt 2 vẫn chạy, nhật ký `failed`."""
		muon = LUC + 2 * PHUT
		e = dong_hddt(misa_ref_id="moc-1", misa_status="sent", phat_hanh_luc=LUC - NGAY, misa_last_checked_at=muon)
		e2 = dong_hddt(misa_ref_id="moc-2", misa_status="signed", misa_inv_no="00000888", misa_inv_series="1C26TAA", phat_hanh_luc=LUC - NGAY)
		self.misa(misa_gia())
		L.dong_bo_trang_thai()
		self.assertEqual(self.dong(e).misa_last_checked_at, muon)
		self.assertEqual(self.dong(e2).misa_last_checked_at, LUC)
		self.misa(misa_gia())
		with patch.object(L, "_ghi_moc_hoi", side_effect=RuntimeError("khoá chờ quá hạn")):
			L.dong_bo_trang_thai()
		_nk, nv = self.luot()
		self.assertEqual(sorted(x["message"] for x in nv["errors"]), ["Không ghi được mốc đã hỏi: khoá chờ quá hạn"] * 2)
		a = self.misa(misa_gia())
		with patch.object(L, "LUOT_1", "SELECT * FROM `tabKhong Co Bang`"):
			L.dong_bo_trang_thai()
		nk, nv = self.luot()
		self.assertEqual((nk.ket_qua, nv["luot_1"], nv["luot_2"], hoi(a)), ("failed", 0, 1, ["moc-2"]))
		self.assertTrue(nv["errors"][0]["message"].startswith("Lượt 1 lỗi: "), nv["errors"])

	def test_cau_hinh_tat_hong_va_het_gio_viec(self):
		"""KV-40 (d): chưa lưu / `dang_dung` 0 → `sync_run` bỏ qua, 0 lời gọi. Giải mã hỏng → một lỗi, `failed`, 0 lời gọi; đọc cấu hình hỏng →
		"Lỗi đọc cấu hình: …". RQ cắt việc (JobTimeoutException) KHÔNG bị nuốt trong vòng "lỗi một tờ"."""
		from rq.timeouts import JobTimeoutException

		dong_hddt(misa_ref_id="cf-1", misa_status="sent", phat_hanh_luc=LUC - NGAY)
		a = self.misa(misa_gia())
		frappe.db.set_single_value(CH.TEN, "dang_dung", 0)
		frappe.clear_document_cache(CH.TEN, CH.TEN)
		L.chay_dong_bo()
		self.assertEqual(a.goi, [])
		for nguon in ("sync_run", "pull_snapshots"):
			nk, nv = self.luot(nguon)
			self.assertEqual((nk.ket_qua, nv["bo_qua"], nk.loi), ("success", "chưa cấu hình / đang tắt", "chưa cấu hình / đang tắt"), nguon)
		frappe.db.set_single_value(CH.TEN, "dang_dung", 1)
		frappe.clear_document_cache(CH.TEN, CH.TEN)
		with patch.object(MM.CauHinhMisa, "giai_ma", side_effect=MM.LoiGiaiMa()):
			L.dong_bo_trang_thai()
			L.keo_snapshot()
		self.assertEqual(a.goi, [])
		for nguon in ("sync_run", "pull_snapshots"):
			nk, nv = self.luot(nguon)
			self.assertEqual((nk.ket_qua, nv["errors"]), ("failed", [{"message": "Giải mã cấu hình lỗi: khoá mã hoá của site không mở được tài "
				"khoản / mật khẩu MISA đã lưu"}]), nguon)
		with patch.object(MM, "lay_cau_hinh", side_effect=RuntimeError("mất kết nối CSDL")):
			L.dong_bo_trang_thai()
		self.assertEqual(self.luot()[1]["errors"], [{"message": "Lỗi đọc cấu hình: mất kết nối CSDL"}])
		with patch.object(MM, "lay_hd", side_effect=JobTimeoutException("quá 3600 s")), self.assertRaises(JobTimeoutException):
			L.dong_bo_trang_thai()
		frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)
		frappe.clear_document_cache(CH.TEN, CH.TEN)
		L.dong_bo_trang_thai()
		self.assertEqual(self.luot()[1]["bo_qua"], "chưa cấu hình / đang tắt")


# =====================================================================================================================================
# §5.1 — lịch, khoá tệp, thứ tự hai việc (KV-40 b, c)
# =====================================================================================================================================
class TestChayDongBo(_NenLich):
	def test_thu_tu_va_token_dung_chung(self):
		"""`chay_dong_bo`: đồng bộ TRƯỚC (GET …), kéo snapshot SAU (paging) — một lời /oauth cho cả hai (token RAM của lượt); hai dòng nhật ký lượt,
		`sync_run` trước `pull_snapshots`."""
		dong_hddt(misa_ref_id="cd-1", misa_status="sent", phat_hanh_luc=LUC - NGAY)
		a = self.misa(misa_gia(trang=lambda start: trang_ds([bg("ds-1", "00000301")] if start == 0 else [], tong=1)))
		kq = L.chay_dong_bo(days=7)
		self.assertEqual([g.split("?")[0] for g in gon(a)], ["POST /oauth", "GET /v3sainvoice/", "POST /v3sainvoice/paging"])
		self.assertEqual((kq["keo_snapshot"]["from"], kq["keo_snapshot"]["to"]), ("2026-11-08", "2026-11-15"))
		self.assertEqual(sorted(kq), ["dong_bo", "keo_snapshot"])
		nk = frappe.get_all("NPP MISA Log", filters={"nguon": ("in", ("sync_run", "pull_snapshots"))}, fields=["nguon", "ket_qua"],
			order_by="creation asc")
		self.assertEqual([(x.nguon, x.ket_qua) for x in nk], [("sync_run", "success"), ("pull_snapshots", "success")])
		self.assertEqual(self.luot("pull_snapshots")[1]["pulled"], 1)

	def test_kv40b_khoa_tep_dang_giu(self):
		"""KV-40 (b): khoá tệp `npp_misa_dong_bo` đang bị giữ (lượt khác) → một dòng `sync_run` "bỏ qua — lượt khác đang chạy", 0 lời gọi, không kéo."""
		from frappe.utils.synchronization import filelock

		dong_hddt(misa_ref_id="kt-1", misa_status="sent", phat_hanh_luc=LUC - NGAY)
		a = self.misa(misa_gia())
		with filelock(L.TEN_VIEC):
			kq = L.chay_dong_bo()
		self.assertEqual(kq, {"bo_qua": "bỏ qua — lượt khác đang chạy"})
		self.assertEqual(a.goi, [])
		nk, nv = self.luot()
		self.assertEqual((nk.ket_qua, nv["bo_qua"], nk.loi), ("success", "bỏ qua — lượt khác đang chạy", "bỏ qua — lượt khác đang chạy"))
		self.assertEqual(self.nhat_ky(nguon="pull_snapshots"), [])
		self.assertEqual(len(self.nhat_ky(nguon="sync_run")), 1)

	def test_kv40c_dong_bo_nem_van_keo(self):
		"""KV-40 (c): `dong_bo_trang_thai` ném → một dòng `sync_run` failed (câu lỗi) + Error Log, VẪN kéo snapshot (nhật ký `pull_snapshots`).
		Ngược lại kéo ném → `pull_snapshots` failed, đồng bộ đã xong. RQ cắt việc ở đồng bộ → nổi lên, KHÔNG kéo tiếp."""
		from rq.timeouts import JobTimeoutException

		a = self.misa(misa_gia(trang=lambda start: trang_ds([])))
		with patch.object(L, "dong_bo_trang_thai", side_effect=RuntimeError("hỏng giữa lượt")):
			L.chay_dong_bo()
		nk, nv = self.luot()
		self.assertEqual((nk.ket_qua, nv["errors"]), ("failed", [{"message": "hỏng giữa lượt"}]))
		self.assertEqual(self.luot("pull_snapshots")[0].ket_qua, "success")
		self.assertIn("POST /v3sainvoice/paging", gon(a))
		self.assertTrue(frappe.db.sql("SELECT 1 FROM `tabError Log` WHERE `creation` > %s AND `method` = 'HĐĐT MISA: vòng quét lỗi'",
			self.loi_truoc))
		with patch.object(L, "keo_snapshot", side_effect=RuntimeError("hỏng lúc kéo")):
			kq = L.chay_dong_bo()
		self.assertEqual((self.luot()[0].ket_qua, self.luot("pull_snapshots")[1]["errors"]), ("success", [{"message": "hỏng lúc kéo"}]))
		self.assertEqual(kq["keo_snapshot"]["errors"], [{"message": "hỏng lúc kéo"}])
		so_keo = len(self.nhat_ky(nguon="pull_snapshots"))
		with patch.object(L, "dong_bo_trang_thai", side_effect=JobTimeoutException("quá giờ")), self.assertRaises(JobTimeoutException):
			L.chay_dong_bo()
		self.assertEqual(len(self.nhat_ky(nguon="pull_snapshots")), so_keo)
		# [Sửa cuối — phát hiện 17] RQ cắt việc vẫn để lại MỘT dòng nhật ký lượt `failed` (bằng chứng duy nhất việc đã chạy) trước khi nổi lên
		nk, nv = self.luot()
		self.assertEqual((nk.ket_qua, nv["errors"]), ("failed", [{"message": "RQ cắt việc (quá trần thời gian của việc nền) — lượt dở dang: quá giờ"}]))
		with patch.object(L, "keo_snapshot", side_effect=JobTimeoutException("quá giờ kéo")), self.assertRaises(JobTimeoutException):
			L.chay_dong_bo()
		nk, nv = self.luot("pull_snapshots")
		self.assertEqual((nk.ket_qua, nv["errors"][0]["message"]), ("failed", "RQ cắt việc (quá trần thời gian của việc nền) — lượt dở dang: quá giờ kéo"))


# =====================================================================================================================================
# Nhóm F — kéo snapshot + khớp (§5.3, §5.4)
# =====================================================================================================================================
class TestKeoSnapshot(_NenLich):
	def test_kv41_phan_trang(self):
		"""KV-41 [≠ ngày VN]: days 60, T = 15/11/2026 → từ 2026-09-16 đến 2026-11-15; có mã → POST …/code/v3sainvoice/paging, form ngày trần không
		nháy; trang 100 / 100 / 37, recordsTotal 0 → 3 lời, pulled 237, short_pull []. Chạy 01:00 giờ VN: đến ngày VN 2026-11-15 (nppsale lấy ngày
		UTC → 2026-11-14)."""
		self.co_ma()
		ds = [bg(f"P-{i:03d}", f"{i + 1:08d}") for i in range(237)]
		a = self.misa(misa_gia(trang=lambda start: trang_ds(ds[start:start + 100], tong=0)))
		bao = L.keo_snapshot()
		self.assertEqual(gon(a), ["POST /oauth"] + ["POST /code/v3sainvoice/paging"] * 3)
		_m, _u, hd, than = a.goi[1]
		self.assertEqual(than.decode(), "start=0&length=100&fromDate=2026-09-16T00%3A00%3A00.000Z&toDate=2026-11-15T23%3A59%3A59.000Z")
		self.assertEqual(hd_app(hd), [("Content-Type", "application/x-www-form-urlencoded"), ("Authorization", "Bearer T1"), ("TaxCode", MST)])
		self.assertEqual([dict(parse_qsl(g[3].decode()))["start"] for g in a.goi[1:]], ["0", "100", "200"])
		self.assertEqual({k: bao[k] for k in ("from", "to", "orgs", "pulled", "short_pull", "hit_page_cap", "trung_ref_trong_luot", "matched",
			"misa_only", "needs_review", "skipped_unlink", "read_truncated", "errors")}, {"from": "2026-09-16", "to": "2026-11-15", "orgs": 1,
			"pulled": 237, "short_pull": [], "hit_page_cap": False, "trung_ref_trong_luot": 0, "matched": 0, "misa_only": 237, "needs_review": 0,
			"skipped_unlink": 0, "read_truncated": [], "errors": []})
		self.assertEqual(frappe.db.count("NPP MISA Snapshot"), 237)
		nk, nv = self.luot("pull_snapshots")
		self.assertEqual((nk.ket_qua, nv["pulled"], nv["from"], nv["to"], nk.hddt), ("success", 237, "2026-09-16", "2026-11-15", None))
		self.luc = datetime.datetime(2026, 11, 15, 1, 0)  # giờ chạy của lịch
		a = self.misa(misa_gia(trang=lambda start: trang_ds([])))
		self.assertEqual(L.keo_snapshot()["to"], "2026-11-15")
		self.assertIn("toDate=2026-11-15T23%3A59%3A59.000Z", a.goi[0][3].decode())  # token RAM: lời đầu là paging

	def test_kv41_trang_meo_tong_dau_tien_tran_trang(self):
		"""KV-41: trang 2 méo, recordsTotal 250 → dừng, pulled 100, short_pull [{expected 250, got 100}]; recordsTotal = số ĐẦU TIÊN gặp (trang đầu
		không trả số thì lấy ở trang sau) [Soát thiếu 2]; adapter luôn trả 100 dòng → 300 lời, hit_page_cap."""
		ds = [bg(f"M-{i:03d}", f"{i + 1:08d}") for i in range(150)]
		a = self.misa(misa_gia(trang=lambda start: trang_ds(ds[:100], tong=250) if start == 0 else trang_ds([], tong=999, tho="khong-phai-json")))
		bao = L.keo_snapshot()
		self.assertEqual((gon(a).count("POST /v3sainvoice/paging"), bao["pulled"], bao["short_pull"]), (2, 100, [{"expected": 250, "got": 100}]))
		a = self.misa(misa_gia(trang=lambda start: trang_ds(ds[start:start + 100], tong=None if start == 0 else 300)))
		bao = L.keo_snapshot()
		self.assertEqual((gon(a).count("POST /v3sainvoice/paging"), bao["pulled"], bao["short_pull"]), (2, 150, [{"expected": 300, "got": 150}]))
		a = self.misa(misa_gia(trang=lambda start: trang_ds(ds[:100])))
		bao = L.keo_snapshot()
		self.assertEqual((gon(a).count("POST /v3sainvoice/paging"), bao["hit_page_cap"], bao["pulled"], bao["trung_ref_trong_luot"]),
			(300, True, 100, 100))
		self.assertEqual(L.TRAN_TRANG * L.CO_TRANG, 30000)

	def test_kv41_so_ngay(self):
		"""`days` `Number(x) || 60` kẹp [1, 400]: '0' / 'abc' / thiếu → 60; 1000 → 400 (từ = đến − 400); -5 → 1; '2.5' → 2; 0.5 → 1."""
		self.assertEqual([L.so_ngay(x) for x in ("0", "abc", None, 1000, -5, "2.5", 0.5, " 7 ", 60)], [60, 60, 60, 400, 1, 2, 1, 7, 60])
		a = self.misa(misa_gia(trang=lambda start: trang_ds([])))
		bao = L.keo_snapshot("1000")
		self.assertEqual((bao["from"], bao["to"]), ("2025-10-11", "2026-11-15"))
		self.assertIn("fromDate=2025-10-11T00%3A00%3A00.000Z", a.goi[1][3].decode())

	def test_kv42_keo_lai_khong_nhan_ban_giu_chot_tay(self):
		"""KV-42 [=]: kéo lại cùng RefID → không nhân bản; dòng `cach_khop` manual GIỮ mọi cột khớp (I7) dù cột dữ liệu được cập nhật (tổng tiền mới,
		`keo_luc`, `modified`; `name` / `creation` / `owner` giữ); chuẩn hoá: '00007140' → '7140', ' 1c26 taa' → ký hiệu '1c26 taa' / chuẩn
		'1C26TAA'; `<Chưa cấp số>` → số NULL; bản ghi thiếu RefID bị bỏ; `TotalAmountWithoutVAT` 0.0 → cổng `amount_before_vat` null; thiếu
		`TotalAmount` → `co_tong_tien` 0, cổng `total_amount` null."""
		hd_tay = dong_hddt(trang_thai="issued", tong_tien=5000)
		ds = [bg(f"R-{i:03d}", f"{i + 1:08d}") for i in range(232)] + [
			bg("chuan-1", "00007140", ky_hieu=" 1c26 taa"), bg("cho-1", None), bg("", "00000999"), bg("tien-0", "00000998", TotalAmountWithoutVAT=0.0,
			TotalVATAmount=0.0), bg("khong-tong", "00000997", bo=("TotalAmount",)), bg("tay-1", "00000996", tong=5000)]
		ds.append({"InvNo": "00000995"})  # không có khoá RefID
		self.misa(misa_gia(trang=lambda start: trang_ds(ds[start:start + 100])))
		self.assertEqual(L.keo_snapshot()["pulled"], 237)
		self.assertEqual(frappe.db.count("NPP MISA Snapshot"), 237)
		tay = self.snap("tay-1")
		chot = {"hddt": hd_tay, "cach_khop": "manual", "do_tin": "certain", "ket_qua_khop": "matched", "ghi_chu_khop": "Người nối tay.",
			"khop_luc": LUC - 3 * NGAY}
		frappe.db.set_value("NPP MISA Snapshot", tay.name, chot, update_modified=False)
		ds[-2] = bg("tay-1", "00000996", tong=6000)  # MISA đổi tổng của tờ đã chốt tay
		self.luc = LUC + PHUT
		self.misa(misa_gia(trang=lambda start: trang_ds(ds[start:start + 100])))
		bao = L.keo_snapshot()
		self.assertEqual((bao["pulled"], frappe.db.count("NPP MISA Snapshot")), (237, 237))
		sau = self.snap("tay-1")
		self.assertEqual({k: sau[k] for k in chot}, chot)
		self.assertEqual((sau.name, sau.creation, sau.owner, flt(sau.tong_tien), sau.keo_luc, sau.modified),
			(tay.name, tay.creation, tay.owner, 6000, LUC + PHUT, LUC + PHUT))
		c = self.snap("chuan-1")
		self.assertEqual((c.so_hddt, c.so_hddt_chuan, c.ky_hieu, c.ky_hieu_chuan), ("00007140", "7140", "1c26 taa", "1C26TAA"))
		self.assertEqual((self.snap("cho-1").so_hddt, self.snap("cho-1").so_hddt_chuan), (None, None))
		self.assertEqual(frappe.db.count("NPP MISA Snapshot", {"so_hddt": ("in", ("00000999", "00000995"))}), 0)
		cong = {r["ref_id"]: r for r in self._doc("owner", "misa_invoice_snapshots", select="ref_id, total_amount, amount_before_vat, vat_amount",
			loc=[{"op": "in", "cot": "ref_id", "gt": ["tien-0", "khong-tong", "chuan-1"]}])}
		self.assertEqual((cong["tien-0"]["amount_before_vat"], cong["tien-0"]["vat_amount"], cong["tien-0"]["total_amount"]), (None, None, 1000))
		self.assertEqual((self.snap("khong-tong").co_tong_tien, cong["khong-tong"]["total_amount"]), (0, None))

	def test_kv43_khop_ghi_dung_khong_dung_so(self):
		"""KV-43 [= trừ ngày VN]: sổ = b1…b7 của KV-11 (+ b8 phát hành 03:00 giờ VN chưa có ngày MISA, b_cu ngoài cửa sổ) → kết quả khớp của từng
		snapshot đúng KV-11; ảnh `NPP HDDT` trước / sau GIỐNG HỆT (I7 — module khớp chỉ ghi snapshot); snapshot trỏ tờ ngoài cửa sổ mà không khớp →
		`skipped_unlink` 1, giữ liên kết; snapshot trỏ tờ TRONG cửa sổ mà không khớp nữa → cắt liên kết (misa_only); dòng chốt tay không đổi; snapshot
		không có ngày không bao giờ được khớp; nhật ký `pull_snapshots` đếm đúng (matched gồm amount_diff)."""
		ngay = {f"b{i}": datetime.datetime(2026, 11, d, 9, 0) for i, d in ((1, 2), (2, 3), (3, 10), (4, 11), (5, 12), (6, 12), (7, 7))}
		so = {
			"b1": dong_hddt(misa_ref_id="rid-1", misa_lookup_code="TXA", misa_inv_series="1C26TAA", misa_inv_no="00000123",
				mst_nguoi_mua="0301175691-044", misa_inv_date="2026-11-02", tong_tien=212600, trang_thai="issued", misa_status="signed",
				phat_hanh_luc=ngay["b1"]),
			"b2": dong_hddt(misa_inv_series="2C26TAA", misa_inv_no="00000500", tong_tien=1000, trang_thai="issued", phat_hanh_luc=ngay["b2"]),
			"b3": dong_hddt(mst_nguoi_mua="0301175691-044", misa_inv_date="2026-11-10", tong_tien=55000, trang_thai="issued",
				phat_hanh_luc=ngay["b3"] - NGAY),  # ngày MISA (10/11) ≠ ngày phát hành nội bộ (09/11): tầng 4 dùng ngày MISA trước
			"b4": dong_hddt(mst_nguoi_mua="0302222222-001", misa_inv_date="2026-11-11", tong_tien=66000, trang_thai="issued",
				phat_hanh_luc=ngay["b4"]),
			"b5": dong_hddt(mst_nguoi_mua="0303333333", misa_inv_date="2026-11-12", tong_tien=70000, trang_thai="issued", phat_hanh_luc=ngay["b5"]),
			"b6": dong_hddt(mst_nguoi_mua="0303333333", misa_inv_date="2026-11-12", tong_tien=70000, trang_thai="issued", phat_hanh_luc=ngay["b6"]),
			"b7": dong_hddt(misa_ref_id="rid-7", misa_inv_series="1C26TAA", misa_inv_no="00000130", tong_tien=108000, trang_thai="issued",
				misa_status="signed", phat_hanh_luc=ngay["b7"]),
			"b8": dong_hddt(mst_nguoi_mua="0304444444", tong_tien=77000, trang_thai="issued", phat_hanh_luc=datetime.datetime(2026, 11, 13, 3, 0)),
			"b_cu": dong_hddt(misa_ref_id="rid-cu", tong_tien=9000, trang_thai="issued", phat_hanh_luc=LUC - 100 * NGAY),
			# biên cửa sổ [từ 00:00:00, đến 23:59:59] giờ VN — hai đầu đều vào
			"b_dau": dong_hddt(mst_nguoi_mua="0306666666", tong_tien=99000, trang_thai="issued",
				phat_hanh_luc=datetime.datetime(2026, 9, 16, 0, 30)),
			"b_cuoi": dong_hddt(mst_nguoi_mua="0305555555", tong_tien=88000, trang_thai="issued",
				phat_hanh_luc=datetime.datetime(2026, 11, 15, 23, 30)),
		}
		cu = self.snapshot_san("r-cu", ngay_phat_hanh="2026-11-08", hddt=so["b_cu"], cach_khop="ref_id", do_tin="certain", ket_qua_khop="matched")
		self.snapshot_san("s-cat", ngay_phat_hanh="2026-11-09", hddt=so["b2"], cach_khop="inv_no", do_tin="certain", ket_qua_khop="matched")
		chot = {"hddt": so["b3"], "cach_khop": "manual", "do_tin": "certain", "ket_qua_khop": "matched", "ghi_chu_khop": "Người nối tay."}
		self.snapshot_san("s-tay", ngay_phat_hanh="2026-11-10", **chot)
		chot_cu = {**chot, "hddt": so["b_cu"]}  # chốt tay vào tờ NGOÀI cửa sổ: vòng khớp không đọc dòng manual — không cả `skipped_unlink`
		self.snapshot_san("s-tay-cu", ngay_phat_hanh="2026-11-10", **chot_cu)
		khong = {"InvSeries": "X9", "InvNo": "999"}
		ds = [
			bg("rid-1", None, ngay="2026-11-02T00:00:00", tong=212600),
			bg("s2", None, ngay="2026-11-02T00:00:00", tong=212600, TransactionID="TXA"),
			bg("s3", "123", ky_hieu=" 1c26taa", ngay="2026-11-02T00:00:00", tong=212000),
			bg("s4", "500", ky_hieu="C26TAA", ngay="2026-11-03T00:00:00", tong=1000),
			bg("s5", None, ngay="2026-11-10T00:00:00", tong=55000, AccountObjectTaxCode="0301175691-044"),
			bg("s6", None, ngay="2026-11-11T00:00:00", tong=-66000, AccountObjectTaxCode="0302222222"),
			bg("s7", None, ngay="2026-11-12T00:00:00", tong=70000, AccountObjectTaxCode="0303333333"),
			bg("s8", None, ngay="2026-11-05T00:00:00", tong=5000),
			bg("s9", None, ngay="2026-11-06T00:00:00", tong=1, IsInvoiceDeleted=True),
			bg("s10", "00000130", ngay="2026-11-07T00:00:00", tong=-5000, EInvoiceStatus=4),
			bg("s11", "130", ngay="2026-11-07T00:00:00", tong=108000, EInvoiceStatus=7),
			bg("s12", "0130", ngay="2026-11-07T00:00:00", tong=-108002),
			bg("s13", "000130", ngay="2026-11-07T00:00:00", tong=108001),
			bg("s14", None, ngay="2026-11-13T00:00:00", tong=77000, AccountObjectTaxCode="0304444444"),
			bg("r-cu", None, ngay="2026-11-08T00:00:00", tong=9000, **khong),
			bg("s-cat", None, ngay="2026-11-09T00:00:00", tong=1000, **khong),
			bg("s-tay", None, ngay="2026-11-10T00:00:00", tong=55000),
			bg("s-tay-cu", None, ngay="2026-11-10T00:00:00", tong=9000, **khong),
			bg("s-khong-ngay", "00000777", bo=("InvDate",)),
			bg("s-dau", None, ngay="2026-09-16T00:00:00", tong=99000, AccountObjectTaxCode="0306666666"),
			bg("s-cuoi", None, ngay="2026-11-15T00:00:00", tong=88000, AccountObjectTaxCode="0305555555"),
		]
		truoc = anh_hddt()
		self.misa(misa_gia(trang=lambda start: trang_ds(ds if start == 0 else [])))
		bao = L.keo_snapshot()
		self.assertEqual(anh_hddt(), truoc)  # I7
		mong = {
			"rid-1": (so["b1"], "ref_id", "certain", "matched", None),
			"s2": (so["b1"], "transaction_id", "certain", "matched", None),
			"s3": (so["b1"], "inv_no", "certain", "amount_diff", "Lệch tiền — sổ 212.600đ, MISA 212.000đ."),
			"s4": (so["b2"], "inv_no_loose", "review", "needs_review", "Khớp sau khi bỏ chữ số đầu của ký hiệu (MISA: C26TAA). Xác nhận đúng mẫu số "
				"trước khi chốt."),
			"s5": (so["b3"], "tax_date_amount", "review", "needs_review", "Suy đoán từ MST 0301175691-044 + ngày 2026-11-10 + tiền. Duy nhất một hoá "
				"đơn trùng."),
			"s6": (so["b4"], "tax_date_amount", "review", "needs_review", "Suy đoán từ MST gốc 0302222222 (đã bỏ đuôi chi nhánh) + ngày 2026-11-11 + "
				"tiền. Duy nhất một hoá đơn trùng — kiểm lại đúng chi nhánh trước khi chốt."),
			"s7": (None, None, None, "misa_only", "Không tìm được hoá đơn tương ứng trong sổ — hoá đơn phát hành ngoài app."),
			"s8": (None, None, None, "misa_only", "Không tìm được hoá đơn tương ứng trong sổ — hoá đơn phát hành ngoài app."),
			"s9": (None, None, None, "cancelled", "MISA báo hoá đơn đã huỷ."),
			"s10": (so["b7"], "inv_no", "certain", "matched", "Hoá đơn điều chỉnh mang số chênh — không so tiền với sổ."),
			"s11": (so["b7"], "inv_no", "certain", "replaced", "Đã bị thay thế trên MISA — hết hiệu lực."),
			"s12": (so["b7"], "inv_no", "certain", "amount_diff", "Lệch tiền — sổ 108.000đ, MISA -108.002đ."),
			"s13": (so["b7"], "inv_no", "certain", "matched", None),
			"s14": (so["b8"], "tax_date_amount", "review", "needs_review", "Suy đoán từ MST 0304444444 + ngày 2026-11-13 + tiền. Duy nhất một hoá đơn "
				"trùng."),
			"s-cat": (None, None, None, "misa_only", "Không tìm được hoá đơn tương ứng trong sổ — hoá đơn phát hành ngoài app."),
			"s-tay": tuple(chot[k] for k in COT_KHOP),
			"s-tay-cu": tuple(chot_cu[k] for k in COT_KHOP),
			"s-dau": (so["b_dau"], "tax_date_amount", "review", "needs_review", "Suy đoán từ MST 0306666666 + ngày 2026-09-16 + tiền. Duy nhất một "
				"hoá đơn trùng."),
			"s-cuoi": (so["b_cuoi"], "tax_date_amount", "review", "needs_review", "Suy đoán từ MST 0305555555 + ngày 2026-11-15 + tiền. Duy nhất "
				"một hoá đơn trùng."),
		}
		sai = []
		for ref, m in mong.items():
			s = self.snap(ref)
			thuc = tuple(s[k] or None for k in COT_KHOP)
			if thuc != m:
				sai.append(f"{ref}: {thuc} ≠ {m}")
		self.assertEqual(sai, [])
		r_cu = self.snap("r-cu")
		self.assertEqual((r_cu.name, r_cu.hddt, r_cu.cach_khop, r_cu.ket_qua_khop, r_cu.khop_luc), (cu, so["b_cu"], "ref_id", "matched", None))
		self.assertEqual((self.snap("s-khong-ngay").ngay_phat_hanh, self.snap("s-khong-ngay").ket_qua_khop or None), (None, None))
		self.assertEqual(self.snap("s13").khop_luc, LUC)
		self.assertEqual({k: bao[k] for k in ("pulled", "matched", "misa_only", "needs_review", "skipped_unlink", "errors")},
			{"pulled": 21, "matched": 6, "misa_only": 3, "needs_review": 6, "skipped_unlink": 1, "errors": []})
		self.assertEqual(self.luot("pull_snapshots")[1]["matched"], 6)

	def test_kv53_kv57_trang_truot_so_la_ngay_khong_that(self):
		"""KV-57 [≠ nhỏ]: trang 0 có K-050; trang 1 lại K-050 (trang trượt) + 36 dòng mới (37 < 100 ⇒ dừng, 2 lời) → 136 dòng, pulled 136,
		`trung_ref_trong_luot` 1, K-050 ghi theo lần gặp SAU; khớp vẫn chạy. PublishStatus 3.5 → lưu '3.5', cổng KHÔNG đọc thành 3 (null).
		KV-53 [≠ H26]: InvDate '2026-02-30' → `ngay_phat_hanh` NULL, các dòng khác của lô vẫn ghi (MariaDB strict từ chối CẢ câu nếu ghi thẳng)."""
		trang0 = [bg(f"K-{i:03d}", f"{i + 1:08d}") for i in range(100)]
		trang0[50] = bg("K-050", "00000051", tong=1000)
		trang0[7] = bg("K-007", "00000008", PublishStatus=3.5)
		trang0[8] = bg("K-008", "00000009", ngay="2026-02-30T00:00:00")
		trang1 = [bg("K-050", "00000051", tong=2000)] + [bg(f"K-{i:03d}", f"{i + 1:08d}") for i in range(100, 136)]
		a = self.misa(misa_gia(trang=lambda start: trang_ds(trang0 if start == 0 else trang1)))
		bao = L.keo_snapshot()
		self.assertEqual(gon(a).count("POST /v3sainvoice/paging"), 2)
		self.assertEqual((bao["pulled"], bao["trung_ref_trong_luot"], frappe.db.count("NPP MISA Snapshot"), bao["misa_only"], bao["errors"]),
			(136, 1, 136, 135, []))
		self.assertEqual(flt(self.snap("K-050").tong_tien), 2000)
		self.assertEqual((self.snap("K-007").publish_status, self.snap("K-008").ngay_phat_hanh), ("3.5", None))
		self.assertEqual(json.loads(self.snap("K-008").ban_ghi_tho)["InvDate"], "2026-02-30T00:00:00")
		cong = self._doc("owner", "misa_invoice_snapshots", select="ref_id, publish_status", loc=[{"op": "eq", "cot": "ref_id", "gt": "K-007"}])
		self.assertEqual(cong, [{"ref_id": "K-007", "publish_status": None}])
		# khoá so như chỉ mục duy nhất của MariaDB (không phân biệt hoa thường)
		ds, trung = L._khu_trung([bg("abc-1", "1"), bg("ABC-1", "2"), bg("x", "3")], LUC)
		self.assertEqual(([d["ref_id"] for d in ds], [d["so_hddt"] for d in ds], trung), (["ABC-1", "x"], ["2", "3"], 1))

	def test_noi_tay_giua_luc_doc_va_ghi(self):
		"""I7 / Gotcha #10: người nối tay một snapshot SAU khi vòng khớp đã đọc danh sách (chưa có `manual`) mà TRƯỚC khi ghi → câu ghi của vòng khớp
		không đè chốt tay (vế `cach_khop` ≠ manual ngay trong câu UPDATE), và không đếm dòng ấy."""
		e = dong_hddt(misa_ref_id="nt-1", trang_thai="issued", phat_hanh_luc=LUC - NGAY, tong_tien=1000)
		self.misa(misa_gia(trang=lambda start: trang_ds([bg("nt-snap", "00000901")] if start == 0 else [])))
		goc = L.quyet_ket_qua_khop
		chot = {"hddt": e, "cach_khop": "manual", "do_tin": "certain", "ket_qua_khop": "matched", "ghi_chu_khop": "Người nối tay."}

		def quyet_va_noi_tay(s, *a):
			if s.ref_id == "nt-snap":  # người bấm "Nối tay" đúng lúc này (đã commit ở request khác)
				frappe.db.set_value("NPP MISA Snapshot", s.name, chot, update_modified=False)
			return goc(s, *a)

		with patch.object(L, "quyet_ket_qua_khop", quyet_va_noi_tay):
			bao = L.keo_snapshot()
		s = self.snap("nt-snap")
		self.assertEqual({k: s[k] for k in chot}, chot)
		self.assertEqual((bao["misa_only"], bao["matched"], bao["errors"]), (0, 0, []))

	def test_kv53_vong_quet_ngay_khong_that(self):
		"""KV-53 (đường vòng quét) [≠ H26]: MISA trả InvDate '2026-02-30' cho E (`sent`) → E `signed`, số ghi, `misa_inv_date` NULL, mốc hỏi ghi,
		ghi chú thêm câu H26; nhật ký `sync` mang câu ấy."""
		e = dong_hddt(misa_ref_id="R53", misa_status="sent", trang_thai="issued", phat_hanh_luc=LUC - NGAY, tong_tien=212600)
		self.misa(misa_gia(get=lambda ref: get_ban_ghi(InvNo="00000123", InvSeries="1C26TAA", InvDate="2026-02-30T00:00:00", PublishStatus=3,
			EInvoiceStatus=1, TotalAmount=212600)))
		L.dong_bo_trang_thai()
		r = self.dong(e)
		cau = "MISA trả InvDate=2026-02-30T00:00:00 không phải ngày có thật — bỏ qua, cần kiểm tra tay."
		self.assertEqual((r.misa_status, r.misa_inv_no, r.misa_inv_series, r.misa_inv_date, r.misa_last_checked_at, r.misa_note),
			("signed", "00000123", "1C26TAA", None, LUC, cau))
		self.assertEqual(self.nhat_ky(nguon="sync")[0].loi, cau)

	def test_keo_va_khop_hong(self):
		"""Kéo danh sách hỏng giữa chừng → "Kéo danh sách lỗi: …", bỏ CẢ phần đã kéo + bỏ khớp (snapshot cũ không đổi), `failed`; ghi snapshot hỏng
		(một dòng quá dài) → "Ghi snapshot lỗi: …", lui hết lô, bỏ khớp; đọc sổ hỏng → "Đối soát lỗi: Đọc sổ hoá đơn: …"; ghi kết quả khớp của một
		dòng hỏng → "Ghi kết quả khớp lỗi (ref): …", KHÔNG đếm dòng ấy, các dòng khác vẫn ghi."""
		cu = self.snapshot_san("cu-1", ngay_phat_hanh="2026-11-01", ket_qua_khop="misa_only")
		ds = [bg(f"G-{i:03d}", f"{i + 1:08d}") for i in range(100)]
		self.misa(misa_gia(trang=lambda start: trang_ds(ds) if start == 0 else {"status": 500, "body": "boom"}))
		bao = L.keo_snapshot()
		nk, _nv = self.luot("pull_snapshots")
		self.assertEqual((nk.ket_qua, bao["errors"], bao["pulled"], frappe.db.count("NPP MISA Snapshot")),
			("failed", [{"message": "Kéo danh sách lỗi: Lấy danh sách HD lỗi 500: boom"}], 0, 1))
		self.assertEqual((self.snap("cu-1").ket_qua_khop, self.snap("cu-1").khop_luc), ("misa_only", None))
		dai = [bg("dai-1", "1"), bg("dai-2", "2", ky_hieu="X" * 200)]
		self.misa(misa_gia(trang=lambda start: trang_ds(dai if start == 0 else [])))
		with patch.object(L, "LO_GHI", 1):  # mỗi dòng một câu: lô 2 hỏng phải lui cả lô 1 đã ghi (như MỘT câu upsert của nppsale)
			bao = L.keo_snapshot()
		self.assertTrue(bao["errors"][0]["message"].startswith("Ghi snapshot lỗi: "), bao["errors"])
		self.assertEqual((bao["pulled"], frappe.db.count("NPP MISA Snapshot"), self.snap("cu-1").khop_luc), (0, 1, None))
		goc = frappe.local.db.sql

		def sql_doc_so_hong(q, *a, **k):
			if "`phat_hanh_luc`, `misa_sent_at`, `tong_tien`" in q and "FROM `tabNPP HDDT`" in q:
				raise RuntimeError("đọc sổ hỏng")
			return goc(q, *a, **k)

		self.misa(misa_gia(trang=lambda start: trang_ds([bg("ok-1", "00000401")] if start == 0 else [])))
		with patch.object(frappe.local.db, "sql", sql_doc_so_hong):
			bao = L.keo_snapshot()
		self.assertEqual((bao["errors"], bao["pulled"], self.luot("pull_snapshots")[0].ket_qua),
			([{"message": "Đối soát lỗi: Đọc sổ hoá đơn: đọc sổ hỏng"}], 1, "failed"))

		ten_ok = self.snap("ok-1").name

		def sql_ghi_mot_hong(q, *a, **k):
			if q.lstrip().startswith("UPDATE `tabNPP MISA Snapshot`") and a and a[0][-1] == ten_ok:
				raise RuntimeError("khoá dòng")
			return goc(q, *a, **k)

		self.misa(misa_gia(trang=lambda start: trang_ds([bg("ok-1", "00000401")] if start == 0 else [])))
		with patch.object(frappe.local.db, "sql", sql_ghi_mot_hong):
			bao = L.keo_snapshot()
		self.assertEqual((bao["errors"], bao["misa_only"], self.luot("pull_snapshots")[0].ket_qua),
			([{"message": "Ghi kết quả khớp lỗi (ok-1): khoá dòng"}], 1, "success"))  # cu-1 vẫn ghi (misa_only), ok-1 không đếm
		self.assertEqual(self.snap("cu-1").khop_luc, LUC)
		self.assertTrue(cu)


# =====================================================================================================================================
# Sửa cuối (vòng soát 3 góc) — phát hiện 1, 2, 8, 9, 10, 17 ở việc nền
# =====================================================================================================================================
class TestSuaCuoiLich(_NenLich):
	def test_xac_nhan_day_khi_ap_dung_khong_ket_luan(self):
		"""[phát hiện 1] Vòng quét gặp tờ `pending` / `error` có RefID mà MISA CÓ tờ với số thật, PublishStatus lạ (2), đơn vị KHÔNG mã (`ap_dung` không
		kết luận): xác nhận đẩy đưa về `sent` + issued (trước: kẹt pending / error mỗi đêm). Cùng hàm ghi với Làm mới."""
		bg2 = {"InvNo": "00000321", "InvSeries": "1C26TAA", "PublishStatus": 2, "EInvoiceStatus": 1, "TotalAmount": 1000}
		t = {k: dong_hddt(misa_ref_id=k, misa_status=k.split("-")[0], misa_error="x", misa_sent_at=LUC - NGAY, tong_tien=1000,
			misa_inv_series=None) for k in ("pending-1", "error-1")}
		self.misa(misa_gia(get=lambda ref: get_ban_ghi(**{**bg2, "InvNo": "0000032" + ("1" if ref == "pending-1" else "2")})))
		bao = L.dong_bo_trang_thai()
		for k, e in t.items():
			r = self.dong(e)
			self.assertEqual((r.misa_status, r.trang_thai, r.misa_error, bool(r.misa_inv_no)), ("sent", "issued", None, True), k)
		self.assertEqual((bao["updated"], bao["errors"]), (2, []))

	def test_ban_ghi_rong_la_misa_khong_co(self):
		"""[phát hiện 9] `data: '{}'` / `'[]'` cho tờ treo quá 10 phút → H5 (`error`, treo_thanh_loi) như MISA không có; tờ `error` + bản ghi rỗng → chỉ
		mốc hỏi (không "xác nhận đẩy" tờ MISA chưa nhận)."""
		treo = dong_hddt(misa_ref_id="rong-p", misa_status="pending", misa_sent_at=LUC - 11 * PHUT)
		loi = dong_hddt(misa_ref_id="rong-e", misa_status="error", misa_error="MISA từ chối", misa_sent_at=LUC - NGAY)
		self.misa(misa_gia(get=lambda ref: {"body": {"success": True, "data": "{}" if ref == "rong-p" else "[]"}}))
		bao = L.dong_bo_trang_thai()
		self.assertEqual((self.dong(treo).misa_status, self.dong(treo).misa_error, bao["treo_thanh_loi"], bao["updated"]),
			("error", M.LOI_LM_TREO, 1, 0))
		r = self.dong(loi)
		self.assertEqual((r.misa_status, r.trang_thai, r.misa_error, r.misa_last_checked_at), ("error", "draft", "MISA từ chối", LUC))

	def test_loi_misa_tra_loi_van_xoay_hang_doi(self):
		"""[phát hiện 10] MISA TRẢ LỜI lỗi cho tờ (vd 404 cho RefID nó không có — dạng "không có" chưa đo, §9.4-2): vẫn ghi mốc hỏi ⇒ đêm sau tờ CHƯA
		hỏi đứng đầu (trước: tờ chết giữ mốc trống, đứng đầu lượt 1 mãi — ≥ 200 tờ như vậy là tờ mới không bao giờ tới lượt). Lỗi đường truyền không
		ghi mốc [=]."""
		chen_nhanh([{"misa_ref_id": f"Q-{i}", "misa_status": "error", "phat_hanh_luc": LUC - NGAY} for i in range(3)])
		khong_co = {"status": 404, "body": {"message": "Not Found"}}

		def moc(ref):
			return frappe.db.get_value("NPP HDDT", {"misa_ref_id": ref}, "misa_last_checked_at")

		with patch.object(L, "TRAN_LUOT", 2):
			a = self.misa(misa_gia(get=lambda ref: khong_co))
			bao = L.dong_bo_trang_thai()
			dem1 = hoi(a)
			self.assertEqual((len(dem1), len(bao["errors"]), [moc(r) for r in dem1]), (2, 2, [LUC, LUC]))
			con = ({"Q-0", "Q-1", "Q-2"} - set(dem1)).pop()
			self.luc = LUC + NGAY
			a = self.misa(misa_gia(get=lambda ref: khong_co))
			L.dong_bo_trang_thai()
			self.assertEqual(hoi(a)[0], con)  # tờ chưa hỏi lần nào đứng đầu (trước: mốc trống mãi — hai tờ chết chiếm trọn lượt)
			truoc = {r: moc(r) for r in ("Q-0", "Q-1", "Q-2")}
			self.luc = LUC + 2 * NGAY
			a = self.misa(misa_gia(get=lambda ref: requests.exceptions.ConnectionError("đứt")))
			L.dong_bo_trang_thai()
		self.assertEqual(len(hoi(a)), 2)
		for r in hoi(a):
			self.assertEqual(moc(r), truoc[r], r)  # lỗi ĐƯỜNG TRUYỀN: mốc giữ [=] (đêm sau hỏi lại trước)

	def test_han_luot_va_ngat_khi_mang_dut(self):
		"""[phát hiện 17] (a) MISA chậm: quá HAN_DONG_BO_S thì dừng nhận tờ mới — `bo_qua_vi_het_gio`, failed — và `chay_dong_bo` VẪN kéo snapshot
		(trước: RQ cắt việc ở 3600 s, không dòng nhật ký, không kéo); (b) NGAT_LOI_MANG tờ liên tiếp lỗi đường truyền ⇒ dừng lượt (`bo_qua_vi_mang`);
		(c) kéo danh sách quá HAN_KEO_S ⇒ dừng như lỗi kéo, failed."""
		chen_nhanh([{"misa_ref_id": f"H-{i}", "misa_status": "sent", "phat_hanh_luc": LUC - NGAY} for i in range(4)])

		def cham(req):
			if req.method == "GET":
				self.gio += 1000  # mỗi lời GET 1.000 s (đồng hồ đơn điệu giả của misa_mang)

		self.misa(misa_gia(trang=lambda start: trang_ds([])), khi_goi=cham)
		kq = L.chay_dong_bo()
		nv = self.luot()[1]
		self.assertEqual((self.luot()[0].ket_qua, nv["checked"], nv["bo_qua_vi_het_gio"]), ("failed", 3, 1))
		self.assertEqual((self.luot("pull_snapshots")[0].ket_qua, kq["keo_snapshot"]["errors"]), ("success", []))
		a = self.misa(misa_gia(get=lambda ref: requests.exceptions.ConnectionError("đứt")))
		chen_nhanh([{"misa_ref_id": f"N-{i}", "misa_status": "sent", "phat_hanh_luc": LUC - NGAY} for i in range(3)])
		bao = L.dong_bo_trang_thai()
		self.assertEqual((len(hoi(a)), bao["checked"], bao["bo_qua_vi_mang"], len(bao["errors"])), (L.NGAT_LOI_MANG, L.NGAT_LOI_MANG,
			7 - L.NGAT_LOI_MANG, L.NGAT_LOI_MANG))
		self.assertEqual(self.luot()[0].ket_qua, "failed")

		def trang_cham(req):
			if req.url.endswith("/paging"):
				self.gio += 4000

		self.misa(misa_gia(trang=lambda start: trang_ds([bg(f"P-{i}", f"{i + 1:08d}") for i in range(100)])), khi_goi=trang_cham)
		bao = L.keo_snapshot()
		self.assertEqual((bao["errors"], bao["pulled"], self.luot("pull_snapshots")[0].ket_qua),
			([{"message": "Kéo danh sách dừng vì quá hạn lượt đêm (55 phút) sau 1 trang — bỏ khớp đêm nay."}], 0, "failed"))

	def test_khop_so_theo_moc_gui_h14(self):
		"""[phát hiện 2 — mở rộng H14] Phần sổ của vòng khớp = GREATEST(phát hành nội bộ, lần gửi MISA) trong cửa sổ, hoặc ngày HĐĐT trong cửa sổ:
		Y "Khoá HĐ" 90 ngày trước rồi mới đẩy hôm qua, V huỷ nội bộ rồi phát hành (phat_hanh_luc NULL — KV-26 b), U dữ liệu chuyển sang chỉ có ngày HĐĐT
		→ khớp đúng tờ của chúng (trước: "Chỉ có trên MISA — phát hành ngoài app" mỗi đêm cho chính tờ của sổ). Tầng 4 của V dùng ngày gửi MISA."""
		y = dong_hddt(misa_ref_id="R-Y", trang_thai="issued", misa_status="sent", phat_hanh_luc=LUC - 90 * NGAY, misa_sent_at=LUC - NGAY,
			tong_tien=1000)
		v = dong_hddt(misa_ref_id="R-V", trang_thai="issued", misa_status="sent", misa_sent_at=LUC - 2 * NGAY, tong_tien=2000)
		u = dong_hddt(trang_thai="issued", misa_status="signed", misa_inv_series="1C26TAA", misa_inv_no="00000777", misa_inv_date="2026-11-03",
			tong_tien=3000)
		w = dong_hddt(mst_nguoi_mua="0307777777", trang_thai="issued", misa_sent_at=datetime.datetime(2026, 11, 12, 9, 0), tong_tien=4000)
		ds = [bg("R-Y", None, ngay="2026-11-14T00:00:00", tong=1000), bg("R-V", None, ngay="2026-11-13T00:00:00", tong=2000),
			bg("s-u", "00000777", ngay="2026-11-03T00:00:00", tong=3000),
			bg("s-w", None, ngay="2026-11-12T00:00:00", tong=4000, AccountObjectTaxCode="0307777777")]
		self.misa(misa_gia(trang=lambda start: trang_ds(ds if start == 0 else [])))
		bao = L.keo_snapshot()
		mong = {"R-Y": (y, "ref_id", "matched"), "R-V": (v, "ref_id", "matched"), "s-u": (u, "inv_no", "matched"),
			"s-w": (w, "tax_date_amount", "needs_review")}
		for ref, m in mong.items():
			s = self.snap(ref)
			self.assertEqual((s.hddt, s.cach_khop, s.ket_qua_khop), m, ref)
		self.assertEqual((bao["matched"], bao["misa_only"], bao["needs_review"]), (3, 0, 1))

	def test_ban_ghi_tho_va_nhat_ky_che_bi_mat(self):
		"""[phát hiện 8] Bản ghi MISA mang tài khoản đang dùng (vd `CreatedBy`) → `ban_ghi_tho` của snapshot và `nhan_ve` của nhật ký `sync` che `***`
		(QL đọc qua cổng); trường đã bóc (người mua…) lấy từ bản NGUYÊN. (`_i6` cuối bài quét cả `ban_ghi_tho`.)"""
		e = dong_hddt(misa_ref_id="R-che", misa_status="sent", trang_thai="issued", phat_hanh_luc=LUC - NGAY, tong_tien=1000)
		self.misa(misa_gia(get=lambda ref: get_ban_ghi(InvNo="00000555", InvSeries="1C26TAA", PublishStatus=3, EInvoiceStatus=1, TotalAmount=2000,
			CreatedBy="u-thu"), trang=lambda start: trang_ds([bg("s-che", "00000556", AccountObjectName="Cty u-thu", CreatedBy="u-thu")]
			if start == 0 else [])))
		L.chay_dong_bo()
		(nk,) = self.nhat_ky(nguon="sync", hddt=e)
		self.assertEqual(json.loads(nk.nhan_ve)["CreatedBy"], "***")
		s = self.snap("s-che")
		self.assertEqual((json.loads(s.ban_ghi_tho)["CreatedBy"], json.loads(s.ban_ghi_tho)["AccountObjectName"], s.nguoi_mua),
			("***", "Cty ***", "Cty u-thu"))


# =====================================================================================================================================
# §6.3 / §4.9 — lịch khai đúng, không whitelist
# =====================================================================================================================================
class TestLichKhai(IntegrationTestCase):
	def test_mot_muc_lich_xep_hang_long_khong_whitelist(self):
		"""Một mục lịch "0 1 * * *" → `dong_bo` (không mục riêng cho kéo snapshot / vòng quét); `dong_bo` CHỈ xếp hàng `long` (trần 3600 s, job_id
		khử trùng); Scheduled Job Type có sau migrate; không hàm lịch nào whitelist (không cửa HTTP — §4.9)."""
		from nppsale import hooks as HK

		cron = HK.scheduler_events["cron"]
		self.assertEqual(cron["0 1 * * *"].count("nppsale.lich.misa.dong_bo"), 1)
		moi = [m for ds in cron.values() for m in ds] + [m for k, ds in HK.scheduler_events.items() if k != "cron" for m in ds]
		self.assertEqual([m for m in moi if m.startswith("nppsale.lich.misa")], ["nppsale.lich.misa.dong_bo"])
		self.assertIn("nppsale.lich.misa.dong_bo", frappe.get_hooks("scheduler_events")["cron"]["0 1 * * *"])
		self.assertEqual(frappe.db.get_value("Scheduled Job Type", {"method": "nppsale.lich.misa.dong_bo"}, ["frequency", "cron_format"]),
			("Cron", "0 1 * * *"))
		with patch.object(frappe, "enqueue") as xh:
			L.dong_bo()
		xh.assert_called_once_with("nppsale.lich.misa.chay_dong_bo", queue="long", timeout=3600, job_id="npp_misa_dong_bo", deduplicate=True)
		self.assertIs(frappe.get_attr("nppsale.lich.misa.chay_dong_bo"), L.chay_dong_bo)
		for f in (L.dong_bo, L.chay_dong_bo, L.dong_bo_trang_thai, L.keo_snapshot, L.khop_snapshot, L.ghi_snapshot):
			self.assertNotIn(f, frappe.whitelisted, f.__name__)
		self.assertEqual((L.TRAN_LUOT, L.CUA_SO_NGAY, L.CO_TRANG, L.TRAN_TRANG, L.NGAY_MAC_DINH), (200, 60, 100, 300, 60))


# =====================================================================================================================================
# Commit THẬT — commit sau mỗi tờ, không giữ khoá lúc chờ MISA (khuôn TestHaiKetNoi của test_hddt)
# =====================================================================================================================================
class TestLichHaiKetNoi(IntegrationTestCase):
	"""Vòng quét chạy NGOÀI giao dịch bài (`in_test` tắt, commit thật): lúc lời GET của tờ thứ k bay đi, kết nối THỨ HAI `SELECT … FOR UPDATE NOWAIT`
	tờ k−1 KHÔNG bị chặn (hàm ghi đã nhả khoá — commit sau mỗi tờ) và thấy mốc hỏi của nó ĐÃ commit; tờ hỏng ở giữa không cuộn lại tờ trước. Site đã
	có cấu hình MISA thật → bỏ qua (không đụng). Dữ liệu tối thiểu commit trước, dọn sạch ở cleanup."""

	def setUp(self):
		frappe.db.rollback()
		if frappe.db.sql("SELECT 1 FROM `tabSingles` WHERE `doctype` = %s LIMIT 1", CH.TEN) or frappe.db.sql(
				"SELECT 1 FROM `__Auth` WHERE `doctype` = %s LIMIT 1", CH.TEN):
			self.skipTest("site đã có cấu hình MISA — bài commit thật không chạy để khỏi đụng cấu hình thật")
		self.bat_dau = frappe.utils.now_datetime() - datetime.timedelta(seconds=1)  # `creation` theo giờ site (NOW() của CSDL là UTC)
		cho_phep_misa_gia(self)
		MM.xoa_token_nho()
		self.addCleanup(MM.xoa_token_nho)
		p = patch.object(M, "bay_gio", lambda: LUC)
		p.start()
		self.addCleanup(p.stop)
		self.ten = []
		self.addCleanup(self._don)
		d = frappe.get_doc(CH.TEN)
		d.update({"dia_chi_api": API, "mst_nguoi_ban": MST, "tai_khoan": "u-thu", "mat_khau": "p-thu", "misa_inv_series": "1C26TAA"})
		d.save(ignore_permissions=True)
		for k in ("hk-1", "hk-2", "hk-3"):
			self.ten.append(dong_hddt(misa_ref_id=k, misa_status="sent", trang_thai="issued", phat_hanh_luc=LUC - NGAY))
		frappe.db.commit()

	def _don(self):
		frappe.db.rollback()
		for t in self.ten:
			frappe.db.sql("DELETE FROM `tabNPP MISA Log` WHERE `hddt` = %s", t)
			frappe.db.sql("DELETE FROM `tabNPP HDDT` WHERE `name` = %s", t)
		frappe.db.sql("DELETE FROM `tabNPP MISA Log` WHERE `nguon` IN ('sync_run', 'pull_snapshots') AND `creation` >= %s", self.bat_dau)
		frappe.db.sql("DELETE FROM `tabVersion` WHERE `ref_doctype` IN ('NPP HDDT', %s) AND `creation` >= %s", (CH.TEN, self.bat_dau))
		frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)
		frappe.db.sql("DELETE FROM `__Auth` WHERE `doctype` = %s", CH.TEN)
		frappe.db.sql("DELETE FROM `tabError Log` WHERE `creation` >= %s AND `method` LIKE 'HĐĐT MISA%%'", self.bat_dau)
		frappe.db.commit()
		frappe.clear_document_cache(CH.TEN, CH.TEN)

	def test_commit_sau_moi_to_khong_giu_khoa(self):
		chinh = frappe.local.db
		frappe.connect(set_admin_as_user=False)
		kn2 = frappe.local.db
		frappe.local.db = chinh
		self.addCleanup(kn2.close)
		thay, da_hoi = [], []

		def khi_goi(req):
			if req.method != "GET":
				return
			frappe.local.db = kn2
			try:
				for ref in da_hoi:
					kn2.rollback()
					try:
						thay.append((ref, kn2.sql("SELECT `misa_last_checked_at` FROM `tabNPP HDDT` WHERE `misa_ref_id` = %s FOR UPDATE NOWAIT",
							ref)[0][0]))
					except Exception as e:  # khoá còn bị giữ → NOWAIT ném ngay
						thay.append((ref, e))
					kn2.rollback()
			finally:
				frappe.local.db = chinh
			da_hoi.append(ref_cua(req.url))

		a = AdapterHddt([misa_gia(get=lambda ref: requests.exceptions.ConnectionError("đứt") if ref == "hk-2" else None)] * 10, khi_goi)
		s = _PHIEN_THAT()
		s.mount("https://", a)
		p = patch.object(MM, "_phien", lambda: s)
		p.start()
		self.addCleanup(p.stop)
		trong_test = frappe.flags.in_test
		frappe.flags.in_test = False
		try:
			bao = L.dong_bo_trang_thai()
		finally:
			frappe.flags.in_test = trong_test
		frappe.db.rollback()
		self.assertEqual(sorted(da_hoi), ["hk-1", "hk-2", "hk-3"])
		# trước lời GET thứ k: mọi tờ đã hỏi KHÔNG bị khoá; tờ không hỏng đã có mốc hỏi ĐÃ commit
		self.assertEqual([x for x in thay if isinstance(x[1], Exception)], [])
		mong = [(r, None if r == "hk-2" else LUC) for i, _ in enumerate(da_hoi) for r in da_hoi[:i]]
		self.assertEqual(thay, mong)
		self.assertEqual((bao["checked"], len(bao["errors"])), (3, 1))
		self.assertEqual(frappe.db.count("NPP HDDT", {"name": ("in", self.ten), "misa_last_checked_at": LUC}), 2)
		self.assertEqual(frappe.db.count("NPP MISA Log", {"nguon": "sync_run", "creation": (">=", self.bat_dau)}), 1)


# =====================================================================================================================================
# §6.4 — khám sổ HĐĐT (kham_so.hddt) + KV-51 phần khám
# =====================================================================================================================================
class TestKhamSoHddt(_NenLich):
	def _kham(self, **kv) -> dict:
		return KS.quet_hddt(luc=kv.pop("luc", LUC))

	def _nhom(self, kq: dict, nhom: str) -> list:
		return [x for x in kq["can_xem"] if x["nhom"] == nhom]

	def _luot_moi(self, gio=LUC - PHUT):
		self.luc = gio
		M.ghi_nhat_ky("sync_run", "success", nhan_ve={"checked": 0})
		self.luc = LUC

	def test_so_sach(self):
		"""Sổ đúng (tờ đã phát hành có RefID + số, nháp, lỗi CHƯA có RefID, snapshot trạng thái đã biết, lượt đêm vừa chạy) → không dòng nào."""
		self._luot_moi()
		dong_hddt(hoa_don_ban=self.hd, misa_ref_id="ok-1", misa_inv_no="00000123", misa_inv_series="1C26TAA", misa_status="signed",
			trang_thai="issued", phat_hanh_luc=LUC - NGAY)
		dong_hddt(misa_status="error", misa_error="Chưa cấu hình tài khoản MISA")
		dong_hddt(misa_ref_id="ok-2", misa_status="pending", misa_sent_at=LUC - PHUT)
		self.snapshot_san("sn-1", publish_status="3", einvoice_status="1", ban_ghi_tho=json.dumps({"IsInvoiceDeleted": False}))
		kq = self._kham()
		self.assertEqual(kq["can_xem"], [])
		self.assertEqual(kq["thong_ke"]["mat_refid"]["so_hoa_don"], 0)

	def test_nhom1_mat_refid_kv51(self):
		"""Nhóm 1 / 1b / 1c (einvoice_lost_refid.sql truy vấn 1–3; KV-51): tờ có số mà mất RefID — tờ tìm lại được RefID từ nhật ký phát hành
		`success` MẢNG mới nhất lên đầu (`refid_tim_duoc`); nhật ký `failed` / `gui_di` không phải mảng không tính; quy mô ở thong_ke."""
		ma_mat = "MẤT RefID: cột misa_invoice_id cũ đã bị số hoá đơn ghi đè (mig 099). Không tra cứu lại được trên MISA — cần phát hành lại hoặc gán tay RefID."
		g = dong_hddt(misa_inv_no="00000456", misa_inv_series="1C26TAA", misa_status="signed", trang_thai="issued", misa_note=ma_mat,
			phat_hanh_luc=LUC - 3 * NGAY, tong_tien=1000)
		g2 = dong_hddt(misa_inv_no="00000457", misa_inv_series="1C26TAA", misa_status="signed", trang_thai="issued", phat_hanh_luc=LUC - 9 * NGAY,
			tong_tien=2000)
		g3 = dong_hddt(misa_inv_no="00000458", misa_status="error", tong_tien=500)
		for gio, ten, ket_qua, gui in ((LUC - 9 * NGAY, g2, "success", [{"RefID": "cu-9"}]), (LUC - 8 * NGAY, g2, "success", [{"RefID": "goc-9"}]),
				(LUC - 7 * NGAY, g2, "success", {"source": "hoi_truoc_khi_day_lai", "ref_id": "khac"}), (LUC - 7 * NGAY, g3, "failed", [{"RefID": "x"}])):
			self.luc = gio
			M.ghi_nhat_ky("publish", ket_qua, hddt=ten, gui_di=gui)
		self.luc = LUC
		self._luot_moi()
		kq = self._kham()
		n1 = self._nhom(kq, "1")
		self.assertEqual([(x["chung_tu"], x["refid_tim_duoc"]) for x in n1], [(g2, "goc-9"), (g, None), (g3, None)])
		self.assertEqual((n1[1]["so_misa"], n1[1]["ky_hieu"], n1[1]["trang_thai"], str(n1[1]["ngay_phat_hanh"])), ("00000456", "1C26TAA", "signed",
			"2026-11-12"))
		self.assertIn("goc-9", n1[0]["nen_lam"])
		self.assertEqual(kq["thong_ke"]["mat_refid"], {"so_hoa_don": 3, "tong_tien": 3500, "cu_nhat": datetime.date(2026, 11, 6),
			"moi_nhat": datetime.date(2026, 11, 12), "tim_lai_duoc": 1})
		self.assertEqual([x["nhom"] for x in kq["can_xem"]], ["1", "1", "1"])
		# gán tay RefID (đường a) → hết mất RefID; ghi chú "MẤT RefID" ở lại (H7)
		d = frappe.get_doc("NPP HDDT", g)
		d.misa_ref_id = "goc-8"
		d.save(ignore_permissions=True)
		self.assertEqual([x["chung_tu"] for x in self._nhom(self._kham(), "1")], [g2, g3])
		self.assertEqual(self.dong(g).misa_note, ma_mat)
		# nhật ký dựng tay của tờ mất RefID (dữ liệu nppsale trước mig 099 — RefID trong nhật ký, không trên tờ) trái I5 của bản Frappe: bỏ trước
		# bất biến cuối bài
		frappe.db.sql("DELETE FROM `tabNPP MISA Log` WHERE `nguon` = 'publish'")

	def test_nhom2_enum_la_va_co_huy(self):
		"""Nhóm 2 / 2c / 2a / 2b (einvoice_unknown_enums.sql truy vấn 1–4) + sức khoẻ đối soát (truy vấn 5)."""
		self._luot_moi()
		for i, (ps, es, ma_cqt, so, tho, kq_khop, tong) in enumerate((
				("3", "5", None, "00000001", {}, "misa_only", 1000), ("3", "5", None, None, {}, "misa_only", -2000), ("2", "2", "M1", "00000003", {},
				"matched", 3000), ("3.5", "1", None, None, {"IsCanceled": True}, None, 0), ("0", "", None, None, {"IsInvoiceDeleted": True},
				"cancelled", 500), ("", "1", None, None, {"IsCancelled": "true"}, None, 0))):
			self.snapshot_san(f"e-{i}", publish_status=ps, einvoice_status=es, ma_cqt=ma_cqt, so_hddt=so, ky_hieu="1C26TAA",
				ngay_phat_hanh=f"2026-11-{10 + i}", ban_ghi_tho=json.dumps(tho), ket_qua_khop=kq_khop, tong_tien=tong, co_tong_tien=1)
		la = dong_hddt(misa_ref_id="la-1", misa_status="waiting_code", misa_inv_no="00000009", misa_inv_series="1C26TAA",
			misa_note="MISA trả PublishStatus=2 (không rõ nghĩa) và chưa có mã CQT — đang chờ cấp mã.")
		kq = self._kham()
		self.assertEqual([(x["gia_tri"], x["so_hoa_don"]) for x in self._nhom(kq, "2")], [("5", 2), ("2", 1)])
		self.assertEqual(self._nhom(kq, "2")[0]["hoa_don_mau"], ["1C26TAA · ?", "1C26TAA · 00000001"])
		self.assertEqual(self._nhom(kq, "2")[0]["ref_id_mau"], ["e-1", "e-0"])
		self.assertEqual([(x["gia_tri"], x["so_hoa_don"], x["co_ma_cqt"], x["da_cap_so"]) for x in self._nhom(kq, "2c")],
			[("2", 1, 1, 1), ("3.5", 1, 0, 0)])
		self.assertEqual([x["chung_tu"] for x in self._nhom(kq, "2a")], [la])
		self.assertEqual([x["chung_tu"] for x in self._nhom(kq, "2b")], ["IsCanceled"])
		self.assertEqual(kq["thong_ke"]["co_huy_theo_ten"], {"IsInvoiceDeleted": 1, "IsInvoiceCanceled": 0, "IsCanceled": 1, "IsCancelled": 0})
		self.assertEqual(kq["thong_ke"]["doi_soat"], [{"ro": "(chưa đối soát)", "so_dong": 2, "tong_tien_tuyet_doi": 0},
			{"ro": "misa_only", "so_dong": 2, "tong_tien_tuyet_doi": 3000}, {"ro": "cancelled", "so_dong": 1, "tong_tien_tuyet_doi": 500},
			{"ro": "matched", "so_dong": 1, "tong_tien_tuyet_doi": 3000}])
		self.assertEqual([x["nhom"] for x in kq["can_xem"]], ["2", "2", "2a", "2b", "2c", "2c"])

	def test_nhom3_4_to_treo_va_luot_dem(self):
		"""Nhóm 3a (`pending` gửi quá 1 ngày), 3b (`error` có RefID), 4 (lượt đêm không chạy — chỉ khi cấu hình đã lưu + đang dùng)."""
		cu = dong_hddt(hoa_don_ban=self.hd, misa_ref_id="tr-1", misa_status="pending", misa_sent_at=LUC - 2 * NGAY)
		dong_hddt(misa_ref_id="tr-2", misa_status="pending", misa_sent_at=LUC - 3 * PHUT)
		loi = dong_hddt(misa_ref_id="tr-3", misa_status="error", misa_error="MISA từ chối hoá đơn: MST sai")
		dong_hddt(misa_status="error", misa_error="Chưa cấu hình tài khoản MISA")
		kq = self._kham()
		self.assertEqual([(x["nhom"], x["chung_tu"]) for x in kq["can_xem"]], [("3a", cu), ("3b", loi), ("4", None)])
		self.assertIn("chưa có dòng sync_run", self._nhom(kq, "4")[0]["chi_tiet"])
		self._luot_moi(LUC - 30 * 60 * PHUT)
		self.assertEqual(len(self._nhom(self._kham(), "4")), 1)
		self._luot_moi(LUC - 2 * 60 * PHUT)
		kq = self._kham()
		self.assertEqual(self._nhom(kq, "4"), [])
		self.assertEqual(kq["thong_ke"]["luot_moi_nhat"]["sync_run"]["goi_luc"], LUC - 2 * 60 * PHUT)
		frappe.db.sql("DELETE FROM `tabNPP MISA Log` WHERE `nguon` = 'sync_run'")
		frappe.db.set_single_value(CH.TEN, "dang_dung", 0)
		self.assertEqual(self._nhom(self._kham(), "4"), [])

	def test_nhom5_trung_so_hai_dong_khoa_huy(self):
		"""Nhóm 5a (trùng số đã chuẩn hoá — chỉ mục duy nhất không bắt), 5b (hai dòng một HĐ bán), 5c (dòng lẽ ra khoá Huỷ HĐ mà HĐ bán đã huỷ),
		5d (`issued` thiếu cả hai mốc — không bao giờ vào cửa sổ quét)."""
		self._luot_moi()
		a = dong_hddt(misa_inv_series="1C26TAA", misa_inv_no="00000123", misa_ref_id="t5-1", trang_thai="issued", phat_hanh_luc=LUC - NGAY)
		b = dong_hddt(misa_inv_series="", misa_inv_no="123", misa_ref_id="t5-2", trang_thai="issued", phat_hanh_luc=LUC - NGAY)
		dong_hddt(misa_inv_series="2C26TAA", misa_inv_no="0000777", misa_ref_id="t5-3", trang_thai="issued", phat_hanh_luc=LUC - NGAY)
		dong_hddt(misa_inv_series="1C26TAA", misa_inv_no="777", misa_ref_id="t5-4", trang_thai="issued", phat_hanh_luc=LUC - NGAY)
		khong_moc = dong_hddt(misa_ref_id="t5-5", trang_thai="issued", misa_status="sent")
		dong_hddt(misa_ref_id="t5-8", trang_thai="issued", misa_status="sent", misa_sent_at=LUC - NGAY)  # KV-26b: vào cửa sổ nhờ mốc gửi
		kq = self._kham()
		self.assertEqual([(x["nhom"], x["chung_tu"], x.get("hddt_khac")) for x in kq["can_xem"]], [("5a", a, b, ), ("5d", khong_moc, None)])
		self.assertEqual(self._huy().get("error"), None)  # HĐ bán chưa có dòng HĐĐT → huỷ được
		for kv in ({"trang_thai": "issued"}, {"misa_status": "pending", "misa_ref_id": "t5-6"}, {"misa_status": "error", "misa_ref_id": "t5-7"}):
			d = frappe.get_doc({"doctype": "NPP HDDT", "nguoi_mua": "Tạp hoá A", "hoa_don_ban": self.hd, "phat_hanh_luc": LUC - NGAY, **kv})
			d.flags.ignore_links = True  # HĐ bán đã huỷ (dữ liệu nhập / lọt khoá)
			d.insert(ignore_permissions=True)
		kq = self._kham()
		self.assertEqual(len(self._nhom(kq, "5b")), 1)
		self.assertEqual((self._nhom(kq, "5b")[0]["chung_tu"], self._nhom(kq, "5b")[0]["chi_tiet"].count(" (")), (self.hd, 3))
		self.assertEqual(sorted(frappe.db.get_value("NPP HDDT", x["chung_tu"], "misa_status") or "" for x in self._nhom(kq, "5c")), ["", "pending"])

	def test_chi_system_manager(self):
		"""`hddt()` whitelist chỉ cho System Manager / Administrator (`chan_cua_chung` để NV NPP tới mọi method nppsale.* có whitelist)."""
		self.assertIn("can_xem", KS.hddt())
		frappe.set_user(self.ma["u:owner"])
		try:
			with self.assertRaises(frappe.PermissionError):
				KS.hddt()
		finally:
			frappe.set_user("Administrator")
