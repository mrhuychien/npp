"""Hoá đơn điện tử MISA — phần DocType + khoá Huỷ / Sửa HĐ (đặc tả HĐĐT §1.2, §1.6, §1.7, §6.1; KV-48; phần DocType của KV-50 / KV-52). Cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_hddt_khoa

KV-48 (gốc nppsale: `scripts/sql/doi-test/hoa-don-xuat-sua-huy.sql:582–589` ca E6, `hoa-don-soan-hang-tra-da-nhap.sql:259–267` ca J1): HĐ có MỘT dòng
HĐĐT ở từng trạng thái → cancel_invoice và reissue_invoice khoá / qua đúng câu; thứ tự: tiền thu trước, phiếu trả hoàn thành sau; đọc CÓ KHOÁ thấy dòng
vừa commit ở kết nối khác (REPEATABLE READ — PoC 1d). Lệch có chủ ý: vế "đang chờ MISA" (H2 — nppsale không khoá; chờ chủ nhà chốt, Q8).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.cong.loi import NppLoi
from nppsale.npp_hddt.doctype.npp_hddt import npp_hddt as H
from nppsale.npp_hddt.doctype.npp_misa_cau_hinh import npp_misa_cau_hinh as CH
from nppsale.npp_hddt.doctype.npp_misa_snapshot import npp_misa_snapshot as SN
from nppsale.tests import test_xuat_hang as XH
from nppsale.tests.test_tao_don import doi_khoa, dung_nen

DA_PHAT_HANH = "LOCKED_EINVOICE: hóa đơn đã phát hành hóa đơn điện tử"
CHO_MISA = "LOCKED_EINVOICE: HĐĐT đang chờ MISA — bấm Làm mới trạng thái trước"
# (nhãn, trường dòng HĐĐT gắn HĐ bán, câu mong — None = Huỷ / Sửa qua). "@ref" = một RefID mới; "@chi_don" = dòng chỉ có don_hang.
CA_KV48 = [
	("issued, chưa số, sent", {"trang_thai": "issued", "misa_status": "sent", "misa_ref_id": "@ref"}, DA_PHAT_HANH),  # vế (a) đứng trước (b)
	("draft, có số", {"misa_inv_no": "0000123"}, DA_PHAT_HANH),
	("draft, signed", {"misa_status": "signed", "misa_ref_id": "@ref"}, DA_PHAT_HANH),
	("draft, replaced", {"misa_status": "replaced", "misa_ref_id": "@ref"}, DA_PHAT_HANH),
	("draft, huỷ trên MISA, có số (H12)", {"misa_status": "cancelled", "misa_ref_id": "@ref", "misa_inv_no": "00000456",
		"misa_inv_series": "1C26TAA"}, DA_PHAT_HANH),
	("draft, pending + RefID (H2)", {"misa_status": "pending", "misa_ref_id": "@ref"}, CHO_MISA),
	("draft, sent + RefID — dữ liệu chuyển sang (H2)", {"misa_status": "sent", "misa_ref_id": "@ref"}, CHO_MISA),
	("draft, waiting_code + RefID (H2)", {"misa_status": "waiting_code", "misa_ref_id": "@ref"}, CHO_MISA),
	# [Sửa cuối — phát hiện 13] nháp lệch tiền chưa số (H10 — mọi HĐ có giảm giá cả đơn): MISA đang giữ nháp; chủ "Huỷ" HĐĐT nội bộ không huỷ gì bên MISA
	("draft, amount_mismatch + RefID, chưa số (H2)", {"misa_status": "amount_mismatch", "misa_ref_id": "@ref"}, CHO_MISA),
	("huỷ nội bộ, amount_mismatch + RefID, chưa số (H2)", {"trang_thai": "cancelled", "misa_status": "amount_mismatch", "misa_ref_id": "@ref"},
		CHO_MISA),
	("huỷ nội bộ, amount_mismatch, có số", {"trang_thai": "cancelled", "misa_status": "amount_mismatch", "misa_ref_id": "@ref",
		"misa_inv_no": "00000789", "misa_inv_series": "1C26TAA"}, DA_PHAT_HANH),
	("draft, error + RefID", {"misa_status": "error", "misa_ref_id": "@ref"}, None),
	("draft trống", {}, None),
	("huỷ nội bộ, không số", {"trang_thai": "cancelled"}, None),
	("draft, pending không RefID (vế H2 đòi RefID)", {"misa_status": "pending"}, None),
	("draft, huỷ trên MISA, không số", {"misa_status": "cancelled", "misa_ref_id": "@ref"}, None),
	("chỉ don_hang, không hoa_don_ban (issued + số)", {"@chi_don": True, "trang_thai": "issued", "misa_status": "signed", "misa_ref_id": "@ref",
		"misa_inv_no": "0000999"}, None),
]


def dong_hddt(**kv) -> str:
	d = frappe.get_doc({"doctype": "NPP HDDT", "nguoi_mua": "Tạp hoá A", **kv})
	d.insert(ignore_permissions=True)
	return d.name


class _NenHoaDon(IntegrationTestCase):
	"""Nền chung: đơn + HĐ ghi sổ của tình huống vàng `xuat_du_mot_lo` (2 dòng, khách C1) dưới đúng người (như test_xuat_hang)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(XH.VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)

	def setUp(self):
		frappe.db.savepoint("npp_test")
		frappe.local._npp_cai_dat_ban = None
		self.ma = dung_nen(self.vang["nen"])
		XH.dung_kho(self.vang["nen"], self.ma)
		t = next(x for x in self.vang["tinh_huong"] if x["ma"] == "xuat_du_mot_lo")
		frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 0)
		frappe.local._npp_cai_dat_ban = None
		tao, xuat = t["buoc"][0], t["buoc"][1]
		self.don = self._goi(tao["nguoi"], "create_order_with_lines", {"p": doi_khoa(tao["p"], self.ma)})["data"][0]["order_id"]
		p = {**XH.ngay_tuong_doi(xuat["p"]), "order_id": self.don, "lines": XH.TestXuatHang._dong_xuat(self, self.don, xuat["dong"])}
		ket = self._goi(xuat["nguoi"], "post_invoice", {"p": p})
		self.assertNotIn("error", ket, ket)
		self.hd = ket["data"][0]["invoice_id"]

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_ngu_canh = None

	def _goi(self, nguoi: str, ten: str, ts: dict) -> dict:
		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None
		try:
			return api.rpc(ten=ten, tham_so=ts)
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	def _huy(self) -> dict:
		return self._goi("owner", "cancel_invoice", {"p_invoice_id": self.hd, "p_reason": "x"})

	def _sua(self) -> dict:
		dong = XH.TestXuatHang._dong_sua(self, self.hd, [[0, {}], [1, {}]])
		return self._goi("owner", "reissue_invoice", {"p_invoice_id": self.hd, "p": {"lines": dong}})

	def _dong(self, kv: dict) -> str:
		kv = dict(kv)
		if kv.pop("@chi_don", False):
			kv["don_hang"] = self.don
		else:
			kv["hoa_don_ban"] = self.hd
		if kv.get("misa_ref_id") == "@ref":
			kv["misa_ref_id"] = str(uuid.uuid4())
		return dong_hddt(**kv)


class TestKhoaHddt(_NenHoaDon):
	"""KV-48 · LOCKED_EINVOICE (`nppsale.rpc.xuat_hang._khoa_hddt`)."""

	def test_kv48_tung_trang_thai_huy_va_sua(self):
		sai = []
		for rpc in ("cancel_invoice", "reissue_invoice"):
			for nhan, kv, mong in CA_KV48:
				frappe.db.savepoint("hddt_ca")
				try:
					ten = self._dong(kv)
					truoc = frappe.db.get_value("NPP HDDT", ten, ["hoa_don_ban", "trang_thai", "misa_status", "misa_ref_id", "modified"], as_dict=True)
					ket = self._huy() if rpc == "cancel_invoice" else self._sua()
					loi = (ket.get("error") or {}).get("message")
					if mong is None:
						if loi is not None:
							sai.append(f"{rpc} · {nhan}: phải qua — báo {loi[:200]}")
							continue
						if frappe.db.get_value("Sales Invoice", self.hd, "docstatus") != 2:
							sai.append(f"{rpc} · {nhan}: qua mà HĐ cũ chưa huỷ")
						# §1.4: Sửa HĐ không chép HĐĐT sang tờ mới — dòng ở lại tờ cũ, không đổi
						sau = frappe.db.get_value("NPP HDDT", ten, ["hoa_don_ban", "trang_thai", "misa_status", "misa_ref_id", "modified"], as_dict=True)
						if sau != truoc:
							sai.append(f"{rpc} · {nhan}: dòng HĐĐT đổi {truoc} → {sau}")
						if rpc == "reissue_invoice":
							moi = ket["data"][0]["invoice_id"]
							if frappe.db.count("NPP HDDT", {"hoa_don_ban": moi}):
								sai.append(f"{rpc} · {nhan}: tờ mới {moi} có dòng HĐĐT")
					else:
						if (loi, (ket.get("error") or {}).get("code")) != (mong, "P0001"):
							sai.append(f"{rpc} · {nhan}: mong {mong!r} — nhận {ket.get('error') or 'qua'}")
							continue
						if frappe.db.get_value("Sales Invoice", self.hd, "docstatus") != 1:  # tờ cũ vẫn ghi sổ (J1)
							sai.append(f"{rpc} · {nhan}: khoá mà HĐ cũ không còn ghi sổ")
						if frappe.db.get_value("Sales Order", self.don, "npp_trang_thai") != "completed":
							sai.append(f"{rpc} · {nhan}: khoá mà đơn đổi trạng thái")
				finally:
					frappe.db.rollback(save_point="hddt_ca")
					frappe.local._npp_ngu_canh = None
		if sai:
			self.fail(f"{len(sai)} chỗ sai:\n" + "\n".join(sai))

	def test_kv48_mot_dong_khoa_la_du(self):
		"""Một dòng thoả là khoá, kể cả khi dòng khác của cùng HĐ chưa khoá (nppsale EXISTS)."""
		self._dong({"misa_status": "error", "misa_ref_id": "@ref"})
		self._dong({"trang_thai": "issued"})
		self.assertEqual(self._huy()["error"]["message"], DA_PHAT_HANH)

	def test_kv48_thu_tu_tien_thu_truoc(self):
		"""HĐ có tiền thu + HĐĐT khoá → LOCKED_HAS_PAYMENT trước (mig 125); khoá HĐĐT đứng sau."""
		self._dong({"trang_thai": "issued", "misa_inv_no": "0000123"})
		frappe.db.set_value("NPP Cong No", {"hoa_don": self.hd}, "da_thu", 1000)
		self.assertEqual(self._huy()["error"]["message"], "LOCKED_HAS_PAYMENT: hóa đơn đã có tiền thu, huỷ phiếu thu trước")

	def test_kv48_thu_tu_truoc_phieu_tra_hoan_thanh(self):
		"""HĐ có phiếu trả hoàn thành + HĐĐT khoá → LOCKED_EINVOICE trước LOCKED_RETURN_DONE (đối chứng: không HĐĐT → LOCKED_RETURN_DONE)."""
		ket = self._goi("owner", "save_pos_return", {"p": {"customer_id": self.ma["C1"], "invoice_id": self.hd, "complete": True, "zone": "sale",
			"lines": [{"product_id": self.ma["P1"], "unit_name": "Lon", "quantity": 1, "unit_price": 9500, "vat_rate": 0.08}]}})
		self.assertNotIn("error", ket, ket)
		self.assertEqual(frappe.db.get_value("NPP Phieu Tra", ket["data"], ["hoa_don", "trang_thai"]), (self.hd, "completed"))
		self.assertEqual(self._huy()["error"]["message"], "LOCKED_RETURN_DONE: hóa đơn đã có phiếu trả hoàn thành")
		self._dong({"trang_thai": "issued"})
		self.assertEqual(self._huy()["error"]["message"], DA_PHAT_HANH)

	def test_sales_invoice_khong_co_truong_misa(self):
		"""I8 (vế 2) / BP §5.6: mọi trường MISA ở NPP HDDT — amend của Sửa HĐ không có gì để chép (Gotcha #2)."""
		la = [f.fieldname for f in frappe.get_meta("Sales Invoice").fields if "misa" in f.fieldname.lower() or "hddt" in f.fieldname.lower()]
		self.assertEqual(la, [])


class TestKhoaHddtDocCoKhoa(_NenHoaDon):
	"""§6.1: đọc CÓ KHOÁ (LOCK IN SHARE MODE) — giao dịch Huỷ HĐ đã chụp ảnh (REPEATABLE READ) TRƯỚC khi phát hành ở kết nối khác commit dòng
	HĐĐT; đọc thường không thấy dòng ấy (đã kiểm), đọc có khoá thấy → vẫn khoá. Lớp riêng: giao dịch của lớp mới mở sau commit của setUpClass —
	không còn khoá khoảng (gap lock) nào trên `tabNPP HDDT` từ bài trước chặn câu chèn của kết nối thứ hai."""

	@contextmanager
	def _ket_noi_hai(self):
		"""Kết nối thứ hai (phát hành ở request khác). Không dùng `secondary_connection()` của lõi: nó gọi frappe.connect() TRƯỚC khi nhớ kết nối
		đang dùng nên ra khỏi khối vẫn ở kết nối thứ hai (frappe/tests/classes/integration_test_case.py — đo: bài đọc thấy dòng vừa commit)."""
		chinh = frappe.local.db
		if getattr(self, "_kn2", None) is None:
			frappe.connect(set_admin_as_user=False)
			self._kn2 = frappe.local.db
			self.addCleanup(self._kn2.close)
		frappe.local.db = self._kn2
		try:
			yield
		finally:
			frappe.local.db = chinh

	def _thu(self, kv: dict, mong: str):
		ten = str(uuid.uuid4())
		frappe.db.sql("SELECT COUNT(*) FROM `tabNPP HDDT`")  # ảnh chụp đã lập từ setUp; câu đọc thường cho chắc
		try:
			with self._ket_noi_hai():
				frappe.db.sql("""INSERT INTO `tabNPP HDDT` (`name`, `creation`, `modified`, `owner`, `modified_by`, `docstatus`, `idx`,
					`hoa_don_ban`, `nguoi_mua`, `trang_thai`, `misa_ref_id`, `misa_status`, `misa_sent_at`)
					VALUES (%(ten)s, NOW(6), NOW(6), 'Administrator', 'Administrator', 0, 0, %(hd)s, 'Tạp hoá A', %(tt)s, %(ref)s, %(st)s, NOW(6))""",
					{"ten": ten, "hd": self.hd, "tt": kv["trang_thai"], "ref": str(uuid.uuid4()), "st": kv["misa_status"]})
				frappe.db.commit()
			self.assertEqual(frappe.db.sql("SELECT COUNT(*) FROM `tabNPP HDDT` WHERE `name` = %s", ten)[0][0], 0,
				"đọc thường đã thấy dòng của kết nối kia — bài không còn thử được đọc có khoá")
			ket = self._huy()
			self.assertEqual((ket.get("error") or {}).get("message"), mong, ket)
			self.assertEqual(frappe.db.get_value("Sales Invoice", self.hd, "docstatus"), 1)
		finally:
			frappe.db.rollback()  # nhả khoá S của câu đọc có khoá — lui về điểm lưu KHÔNG nhả khoá dòng
			with self._ket_noi_hai():
				frappe.db.sql("DELETE FROM `tabNPP HDDT` WHERE `name` = %s", ten)
				frappe.db.commit()
			frappe.db.savepoint("npp_test")  # tearDown lui về điểm này

	def test_dang_cho_misa_vua_commit(self):
		self._thu({"trang_thai": "draft", "misa_status": "pending"}, CHO_MISA)

	def test_da_phat_hanh_vua_commit(self):
		self._thu({"trang_thai": "issued", "misa_status": "sent"}, DA_PHAT_HANH)


class TestHddtDocType(IntegrationTestCase):
	"""Bốn DocType (đặc tả §1.2): cấu trúc + chỉ mục, tim_kd, validate (I1, H24, NOT NULL, khoá trống → NULL), on_trash, Single cấu hình
	(không lưu lúc cài, Password), chuẩn hoá snapshot."""

	def setUp(self):
		frappe.db.savepoint("npp_test")

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.flags.in_install = False

	# ------------------------------------------------------------------------------------------------ cấu trúc
	def test_cau_truc_va_chi_muc(self):
		m = frappe.get_meta("NPP HDDT")
		self.assertFalse(m.is_submittable)  # Link từ dòng docstatus 0 không chặn huỷ SI / SO (delete_doc.py:379–382)
		self.assertEqual(m.autoname, "UUID")
		self.assertEqual(m.get_field("nguoi_mua").fieldtype, "Small Text")
		self.assertEqual(frappe.get_meta("NPP MISA Snapshot").get_field("nguoi_mua").fieldtype, "Small Text")
		self.assertTrue(m.get_field("misa_ref_id").unique)
		self.assertEqual([m.get_field(f).fieldtype for f in ("hoa_don_ban_ls", "don_hang_ls") if m.get_field(f)], [])  # P8 — chưa dựng
		sn = frappe.get_meta("NPP MISA Snapshot")
		self.assertEqual((sn.get_field("co_tong_tien").fieldtype, sn.get_field("co_tong_tien").hidden), ("Check", 1))
		self.assertEqual({sn.get_field(f).fieldtype for f in ("publish_status", "einvoice_status")}, {"Data"})
		self.assertTrue(sn.get_field("ref_id").unique)
		self.assertTrue(frappe.get_meta("NPP MISA Cau Hinh").issingle)
		self.assertEqual({frappe.get_meta("NPP MISA Cau Hinh").get_field(f).fieldtype for f in ("tai_khoan", "mat_khau")}, {"Password"})
		for dt in ("NPP HDDT", "NPP MISA Cau Hinh", "NPP MISA Log", "NPP MISA Snapshot"):  # vai NPP không mở Desk
			self.assertEqual({p.role for p in frappe.get_meta(dt).permissions}, {"System Manager"}, dt)

		def chi_muc(bang: str) -> dict:
			ra = {}
			for r in frappe.db.sql(f"SHOW INDEX FROM `{bang}`", as_dict=True):
				ra.setdefault(r.Key_name, {"cot": [], "duy_nhat": not r.Non_unique})["cot"].append(r.Column_name)
			return {tuple(v["cot"]): v["duy_nhat"] for v in ra.values()}

		hd = chi_muc("tabNPP HDDT")
		self.assertIs(hd.get(("misa_inv_series", "misa_inv_no")), True)
		self.assertIs(hd.get(("misa_ref_id",)), True)
		for cot in ("misa_last_checked_at", "hoa_don_ban", "don_hang", "misa_org_ref_id", "phat_hanh_luc", "trang_thai"):
			self.assertIn((cot,), hd, cot)
		sn_cm = chi_muc("tabNPP MISA Snapshot")
		self.assertIs(sn_cm.get(("ref_id",)), True)
		for cot in (("ky_hieu_chuan", "so_hddt_chuan"), ("ket_qua_khop", "ngay_phat_hanh"), ("ma_tra_cuu",), ("hddt",)):
			self.assertIn(cot, sn_cm, cot)
		lg = chi_muc("tabNPP MISA Log")
		for cot in (("hddt",), ("goi_luc",)):
			self.assertIn(cot, lg, cot)
		# Link tới DocType UUID: cùng kiểu uuid với khoá đích (thiet_lap/cot_uuid.py) — câu gỡ hddt của on_trash so được
		for bang in ("tabNPP MISA Log", "tabNPP MISA Snapshot"):
			self.assertEqual(frappe.db.sql("""SELECT `DATA_TYPE` FROM information_schema.columns WHERE table_schema = DATABASE()
				AND table_name = %s AND column_name = 'hddt'""", bang)[0][0], "uuid", bang)

	# ------------------------------------------------------------------------------------------------ tim_kd
	def test_tim_kd_nhu_trigger_nppsale(self):
		"""before_save: khoa_tim_ds(so_hd_go_tay, nguoi_mua, misa_inv_no, misa_invoice_id) — đúng thứ tự trigger trg_zzzz_tim_kd (mig 249). Số mong
		đo trên Postgres tham chiếu (16/11/2026): SELECT public.khoa_tim_ds(VARIADIC ARRAY[…]::text[]) — NULL của trigger thành ''."""
		ca = [
			(("HD-0042-1", "Tạp hoá Cô Ba", "00007140", None), "hd 0042 1 hd00421 hd421 tap hoa co ba taphoacoba 00007140 7140"),
			(("INV-20261115-0042", "Công ty TNHH Đại Phát", None, "abc-123"),
				"inv 20261115 0042 inv202611150042 inv2026111542 cong ty tnhh dai phat congtytnhhdaiphat abc 123 abc123"),
			((None, "Khách lẻ", "00000456", None), "khach le khachle 00000456 456"),
			(("", "  Nguyễn  Văn   A ", "0", None), "nguyen van a nguyenvana 0"),
		]
		for (so, nguoi, inv_no, cu), mong in ca:
			ten = dong_hddt(so_hd_go_tay=so, nguoi_mua=nguoi, misa_inv_no=inv_no, misa_invoice_id=cu)
			self.assertEqual(frappe.db.get_value("NPP HDDT", ten, "tim_kd"), mong, (so, nguoi, inv_no))
		# đổi người mua (dòng nháp sửa được) → tính lại
		d = frappe.get_doc("NPP HDDT", ten)
		d.nguoi_mua = "Tạp hoá Cô Ba"
		d.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("NPP HDDT", ten, "tim_kd"), "tap hoa co ba taphoacoba 0")
		self.assertEqual(H.khoa_tim_hddt({"so_hd_go_tay": "00007140", "nguoi_mua": "HD-0042-1", "misa_inv_no": "Tạp hoá Cô Ba"}),
			"00007140 7140 hd 0042 1 hd00421 hd421 tap hoa co ba taphoacoba")  # đổi thứ tự cột là khoá khác (đo PG)

	# ------------------------------------------------------------------------------------------------ validate
	def _sua(self, ten: str, **kv):
		d = frappe.get_doc("NPP HDDT", ten)
		d.update(kv)
		d.save(ignore_permissions=True)
		return d

	def test_refid_bat_bien(self):
		"""I1: RefID đã có thì không đổi / không xoá; đang trống thì điền được (System Manager gán tay tờ mất RefID — §6.4 đặc tả)."""
		r = str(uuid.uuid4())
		ten = dong_hddt(misa_ref_id=r, misa_status="error")
		for gt in (str(uuid.uuid4()), "", None):
			with self.assertRaises(NppLoi) as e:
				self._sua(ten, misa_ref_id=gt)
			self.assertTrue(str(e.exception).startswith("HDDT_REFID_BAT_BIEN:"), str(e.exception))
		self.assertEqual(frappe.db.get_value("NPP HDDT", ten, "misa_ref_id"), r)
		mat = dong_hddt(trang_thai="issued", misa_status="signed", misa_inv_no="00000456", misa_note="MẤT RefID: …")
		self._sua(mat, misa_ref_id="goc-9")
		self.assertEqual(frappe.db.get_value("NPP HDDT", mat, "misa_ref_id"), "goc-9")

	def test_h24_sua_nguoi_mua_tien(self):
		"""KV-52 / KV-50 (d) phần DocType: sửa người mua / tiền / số gõ tay khi dòng ĐANG draft ∧ misa_status trống / error (H24)."""
		duoc = [{}, {"misa_status": "error", "misa_ref_id": "@ref"}]  # tờ tay bị MISA từ chối (error có RefID) — sửa được (≠ bản trước)
		khoa = [{"misa_status": "pending", "misa_ref_id": "@ref"}, {"misa_status": "sent", "misa_ref_id": "@ref"},
			{"trang_thai": "issued", "misa_status": "sent", "misa_ref_id": "@ref"}, {"trang_thai": "issued"}, {"trang_thai": "cancelled"},
			{"misa_status": "signed", "misa_ref_id": "@ref"}]
		doi = [{"nguoi_mua": "Cty C mới"}, {"dia_chi_nguoi_mua": "1 Lê Lợi"}, {"mst_nguoi_mua": "0300000001"}, {"tien_hang": 1},
			{"tien_thue": 1}, {"tong_tien": 1}, {"so_hd_go_tay": "INV-1"}]
		for kv in duoc + khoa:
			for d in doi:
				frappe.db.savepoint("h24")
				try:
					kv2 = {k: (str(uuid.uuid4()) if v == "@ref" else v) for k, v in kv.items()}
					ten = dong_hddt(mst_nguoi_mua="0300000009", tien_hang=100000, tien_thue=10000, tong_tien=110000, **kv2)
					if kv in duoc:
						self._sua(ten, **d)
						k, v = next(iter(d.items()))
						self.assertEqual(frappe.db.get_value("NPP HDDT", ten, k), v, (kv, d))
					else:
						with self.assertRaises(NppLoi, msg=(kv, d)) as e:
							self._sua(ten, **d)
						self.assertTrue(str(e.exception).startswith("HDDT_KHOA_SUA:"), str(e.exception))
				finally:
					frappe.db.rollback(save_point="h24")
		# luật xét trạng thái CŨ: issued → draft cùng lúc đổi người mua vẫn bị chặn
		ten = dong_hddt(trang_thai="issued")
		with self.assertRaises(NppLoi):
			self._sua(ten, trang_thai="draft", nguoi_mua="Khác")
		# các trường misa_* không chặn (System Manager xoá dấu MISA để phát hành lại tờ mất RefID — §6.4 (b))
		ten = dong_hddt(trang_thai="issued", misa_status="signed", misa_inv_no="00000456", misa_inv_series="1C26TAA")
		self._sua(ten, misa_inv_no=None, misa_inv_series=None, misa_status="")
		v = frappe.db.get_value("NPP HDDT", ten, ["misa_inv_no", "misa_status"])
		self.assertIsNone(v[0])
		self.assertFalse(v[1])
		# không đổi gì ở trường người mua / tiền → lưu được ở mọi trạng thái (vd đổi trạng thái nội bộ issued → cancelled)
		self._sua(ten, trang_thai="cancelled")

	def test_nguoi_mua_rong_23502(self):
		for gt in ("", "   ", None):
			with self.assertRaises(NppLoi) as e:
				dong_hddt(nguoi_mua=gt)
			self.assertEqual((e.exception.code, str(e.exception)),
				("23502", 'null value in column "customer_name" of relation "invoices" violates not-null constraint'))
		ten = dong_hddt()
		with self.assertRaises(NppLoi) as e:
			self._sua(ten, nguoi_mua="  ")
		self.assertEqual(e.exception.code, "23502")

	def test_khoa_trong_ve_null_va_cap_duy_nhat(self):
		"""Khoá trống → NULL (hai tờ '' không đụng chỉ mục duy nhất); có số mà ký hiệu NULL → '' (để cặp duy nhất bắt được); trùng (ký hiệu, số)
		nguyên văn → lỗi trùng của CSDL."""
		a = dong_hddt(misa_ref_id="", misa_inv_no="")
		b = dong_hddt(misa_ref_id="  ", misa_inv_no=" ")
		self.assertEqual(frappe.db.sql("SELECT COUNT(*) FROM `tabNPP HDDT` WHERE `name` IN (%s, %s) AND `misa_ref_id` IS NULL AND `misa_inv_no` IS NULL",
			(a, b))[0][0], 2)
		c = dong_hddt(misa_inv_no="00000123")
		self.assertEqual(frappe.db.get_value("NPP HDDT", c, "misa_inv_series"), "")
		with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
			dong_hddt(misa_inv_no="00000123")  # ('', '00000123') lần hai
		dong_hddt(misa_inv_no="00000123", misa_inv_series="1C26TAA")  # khác ký hiệu → được (so nguyên văn như Postgres)
		with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
			r = str(uuid.uuid4())
			dong_hddt(misa_ref_id=r)
			dong_hddt(misa_ref_id=r)

	# ------------------------------------------------------------------------------------------------ on_trash
	def test_xoa(self):
		"""KV-50 (e) / KV-52 phần DocType: xoá chỉ dòng nháp chưa RefID; Log / Snapshot trỏ tới → hddt NULL (thay ON DELETE SET NULL)."""
		ten = dong_hddt()
		log = frappe.get_doc({"doctype": "NPP MISA Log", "hddt": ten, "nguon": "publish", "ket_qua": "failed",
			"gui_di": json.dumps([{"RefID": "x"}])}).insert(ignore_permissions=True).name
		sn = frappe.get_doc({"doctype": "NPP MISA Snapshot", "ref_id": str(uuid.uuid4()), "hddt": ten, "so_hddt": "00000001"}).insert(
			ignore_permissions=True).name
		frappe.delete_doc("NPP HDDT", ten, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("NPP HDDT", ten))
		self.assertEqual((frappe.db.get_value("NPP MISA Log", log, "hddt"), frappe.db.get_value("NPP MISA Snapshot", sn, "hddt")), (None, None))
		for kv in ({"misa_status": "error", "misa_ref_id": str(uuid.uuid4())}, {"misa_status": "pending", "misa_ref_id": str(uuid.uuid4())},
				{"trang_thai": "issued"}, {"trang_thai": "cancelled"}):
			ten = dong_hddt(**kv)
			with self.assertRaises(NppLoi) as e:
				frappe.delete_doc("NPP HDDT", ten, ignore_permissions=True)
			self.assertEqual((str(e.exception), e.exception.code, e.exception.to_dict()["message"]),
				("Chỉ xoá được hoá đơn điện tử nháp chưa gửi MISA.", "P0001", "Chỉ xoá được hoá đơn điện tử nháp chưa gửi MISA."), kv)
			self.assertTrue(frappe.db.exists("NPP HDDT", ten), kv)

	# ------------------------------------------------------------------------------------------------ NPP MISA Cau Hinh
	def test_cau_hinh_khong_luu_luc_cai_dat(self):
		""""Đã lưu" = có dòng tabSingles của nha_cung_cap; init_singles() của lõi (post_install, mỗi lần cài một app) không được lưu Single này."""
		import frappe.installer as I

		frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)
		frappe.db.sql("DELETE FROM `__Auth` WHERE `doctype` = %s", CH.TEN)
		frappe.clear_document_cache(CH.TEN, CH.TEN)
		goc = frappe.get_all

		def chi_cau_hinh(*a, **k):  # init_singles chỉ thấy Single này (Single khác của site không bị lưu trong bài)
			if a and a[0] == "DocType" and (k.get("filters") or {}) == {"issingle": True}:
				return [CH.TEN]
			return goc(*a, **k)

		self.assertFalse(CH.da_luu())
		self.assertEqual(frappe.get_single(CH.TEN).dia_chi_api, "https://testapp.meinvoice.vn/api/v2")  # chưa lưu vẫn ra mặc định
		frappe.flags.in_install = "nppsale"
		with patch.object(frappe, "get_all", chi_cau_hinh):
			I.init_singles()  # new_doc → save() (→ insert())
		ch = frappe.get_single(CH.TEN)  # bước cài đặt nào đó lưu bản đang có — đường save() không qua insert()
		ch.misa_inv_series = "1C26TAA"
		ch.save(ignore_permissions=True)
		frappe.new_doc(CH.TEN).insert(ignore_permissions=True)  # đường insert() gọi thẳng
		frappe.flags.in_install = False
		self.assertFalse(CH.da_luu())
		self.assertEqual(frappe.db.sql("SELECT COUNT(*) FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)[0][0], 0)
		# đối chứng: ngoài lúc cài, cùng lời gọi lưu thật (bài trên không xanh nhờ init_singles bỏ qua Single này)
		with patch.object(frappe, "get_all", chi_cau_hinh):
			I.init_singles()
		self.assertTrue(CH.da_luu())

	def test_cau_hinh_mat_khau(self):
		"""Password ở __Auth (bảng Singles + Version chỉ có dấu *); has_username / has_password không giải mã; ô trống + save() XOÁ bản mã (bẫy
		§1.7 — nơi ghi phải bỏ qua ô trống). Giá trị bịa của bài: u-thu / p-thu."""
		frappe.db.sql("DELETE FROM `tabSingles` WHERE `doctype` = %s", CH.TEN)
		frappe.db.sql("DELETE FROM `__Auth` WHERE `doctype` = %s", CH.TEN)
		frappe.clear_document_cache(CH.TEN, CH.TEN)
		self.assertEqual((CH.co_bi_mat("tai_khoan"), CH.co_bi_mat("mat_khau")), (False, False))
		ch = frappe.get_single(CH.TEN)
		ch.tai_khoan, ch.mat_khau = "u-thu", "p-thu"
		ch.save(ignore_permissions=True, ignore_version=False)
		self.assertTrue(CH.da_luu())
		self.assertEqual((CH.co_bi_mat("tai_khoan"), CH.co_bi_mat("mat_khau")), (True, True))
		self.assertEqual(frappe.get_single(CH.TEN).get_password("mat_khau", raise_exception=False), "p-thu")
		tho = " ".join(str(v) for (v,) in frappe.db.sql("SELECT `value` FROM `tabSingles` WHERE `doctype` = %s", CH.TEN))
		phien = " ".join(frappe.get_all("Version", filters={"ref_doctype": CH.TEN}, pluck="data"))
		self.assertTrue(phien)
		for bi_mat in ("u-thu", "p-thu"):
			self.assertNotIn(bi_mat, tho)
			self.assertNotIn(bi_mat, phien)
			self.assertNotIn(bi_mat, frappe.db.sql("SELECT IFNULL(GROUP_CONCAT(`password`), '') FROM `__Auth` WHERE `doctype` = %s", CH.TEN)[0][0])
		with self.assertRaises(ValueError):
			CH.co_bi_mat("dia_chi_api")
		ch = frappe.get_single(CH.TEN)
		ch.mat_khau = ""
		ch.save(ignore_permissions=True)
		self.assertEqual((CH.co_bi_mat("tai_khoan"), CH.co_bi_mat("mat_khau")), (True, False))

	# ------------------------------------------------------------------------------------------------ NPP MISA Snapshot
	def test_snapshot_chuan_hoa(self):
		"""so_hddt_chuan / ky_hieu_chuan = chuan_so / ky_hieu_chat (H21) — ở validate và qua chuan_hoa_snapshot cho câu ghi gộp."""
		ten = frappe.get_doc({"doctype": "NPP MISA Snapshot", "ref_id": str(uuid.uuid4()), "so_hddt": "00000123", "ky_hieu": " 1c26 taa "}).insert(
			ignore_permissions=True).name
		self.assertEqual(frappe.db.get_value("NPP MISA Snapshot", ten, ["so_hddt", "ky_hieu", "so_hddt_chuan", "ky_hieu_chuan"]),
			("00000123", " 1c26 taa ", "123", "1C26TAA"))  # lưu nguyên văn, chuẩn hoá khi so
		d = frappe.get_doc("NPP MISA Snapshot", ten)
		d.so_hddt, d.ky_hieu = "000", None
		d.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("NPP MISA Snapshot", ten, ["so_hddt_chuan", "ky_hieu_chuan"]), ("0", ""))  # H21: '000' → '0'
		self.assertEqual(SN.chuan_hoa_snapshot("1C26 TAA", " 12 3 "), ("1C26TAA", "12 3"))
		for vao, ra in CHUAN_SO:
			self.assertEqual(SN.chuan_hoa_snapshot(None, vao)[1], ra, vao)
		for vao, ra in KY_HIEU_CHAT:
			self.assertEqual(SN.chuan_hoa_snapshot(vao, None)[0], ra, vao)


# Mẫu chuẩn hoá — đặc tả HĐĐT §2.1–§2.2 [đo bằng mã TS thật]: trim / \s kiểu JS (có U+FEFF, không có U+001C).
CHUAN_SO = [(None, ""), ("", ""), ("   ", ""), ("00000123", "123"), ("000", "0"), ("0", "0"), (" 12 3 ", "12 3"), ("﻿00000123", "123"),
	("\x1c0012", "\x1c0012"), ("A0012", "A0012"), (" 007　", "7")]
KY_HIEU_CHAT = [(None, ""), ("", ""), (" 1c26 taa ", "1C26TAA"), ("1C26﻿TAA", "1C26TAA"), ("1C26\x1cTAA", "1C26\x1cTAA"),
	("\x1c1C26TAA", "\x1c1C26TAA"), ("1C26\tT A A", "1C26TAA")]


class TestChuanHoaKhopTS(unittest.TestCase):
	"""Chuẩn hoá của NPP MISA Snapshot (`chuan_hoa_snapshot` → luat/hddt.py) so CHÍNH mã TS của nppsale (`portal/nguon/src/lib/misa/normalize.ts::
	normalizeInvNo`, `reconcile.ts::strictSeries` — cắt nguyên văn hàm khỏi tệp) trên cùng mẫu. Bỏ qua khi không có portal/nguon (bản bench) hoặc
	node — chạy thuần: cd /home/user/npp && <python của bench> -m unittest nppsale.tests.test_hddt_khoa.TestChuanHoaKhopTS"""

	TS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "portal", "nguon", "src", "lib", "misa"))

	@unittest.skipUnless(os.path.isdir(os.path.join(os.path.dirname(__file__), "..", "..", "portal", "nguon", "src", "lib", "misa"))
		and (shutil.which("node") or os.path.exists("/opt/node24/bin/node")), "không có nguon/ hoặc node")
	def test_khop_ban_ts(self):
		import re

		node = "/opt/node24/bin/node" if os.path.exists("/opt/node24/bin/node") else shutil.which("node")
		with open(os.path.join(self.TS, "reconcile.ts"), encoding="utf-8") as f:
			rec = f.read()
		ham = "\n".join(re.search(r"^function " + t + r"\(.*?^}\n", rec, re.S | re.M).group(0) for t in ("norm", "strictSeries"))
		with tempfile.TemporaryDirectory() as d:
			shutil.copy(os.path.join(self.TS, "normalize.ts"), os.path.join(d, "normalize.ts"))
			mau_so = [x for x, _ in CHUAN_SO]
			mau_kh = [x for x, _ in KY_HIEU_CHAT]
			with open(os.path.join(d, "chay.ts"), "w", encoding="utf-8") as f:
				f.write(f'import {{ normalizeInvNo }} from "./normalize.ts"\n{ham}\n'
					f"console.log(JSON.stringify([{json.dumps(mau_so)}.map(v => normalizeInvNo(v)), {json.dumps(mau_kh)}.map(v => strictSeries(v))]))\n")
			ra = subprocess.run([node, os.path.join(d, "chay.ts")], capture_output=True, text=True, timeout=60)
		self.assertEqual(ra.returncode, 0, ra.stderr)
		so_ts, kh_ts = json.loads(ra.stdout)
		self.assertEqual(so_ts, [r for _, r in CHUAN_SO])
		self.assertEqual(kh_ts, [r for _, r in KY_HIEU_CHAT])
		self.assertEqual([SN.chuan_hoa_snapshot(None, x)[1] for x in mau_so], so_ts)
		self.assertEqual([SN.chuan_hoa_snapshot(x, None)[0] for x in mau_kh], kh_ts)
