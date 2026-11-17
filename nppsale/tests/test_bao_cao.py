"""Nền báo cáo P6 (mốc M0 — đặc tả báo cáo P6 §2.0, §3.3, L5, L11, ❓Q14) — cần bench:

	bench --site poc.local run-tests --module nppsale.tests.test_bao_cao

- khung `nppsale.rpc.bao_cao`: `_ngay` (ép kiểu `date` như PostgREST: 22007 / 22008), `_la_nv`, `_ve` (vế RLS bảng cổng), `_so`, `_chay` (quá hạn → 57014,
  trả lại hẹn giờ phiên, lỗi khác giữ nguyên), `_can_nguon` (PGRST202 khi bảng cổng chưa đăng ký — Q14);
- 🔧 L11 / VB-E16: lỗi quá hạn MariaDB 1969 qua cổng RPC (`cong/api.py::_loi`) và qua `/rest/v1/rpc/...` (portal/rest.py) → HTTP 500 + mã 57014 + câu
  Postgres; `bao_cao_*` chạy dưới hẹn 40 s (`bao_cao_ton_kho`, `bao_cao_cong_no`); `bao_cao_cong_no('')` → 22007 như nppsale;
- 🔧 C1 / VB-E11: lọc cột `gio` với chuỗi có múi giờ ('Z' / '+07:00') so đúng thời điểm (trước đây 'Z' lệch 7 giờ);
- 🔧 C2: `workflow_sessions` đủ 12 cột của nppsale (`PendingWorkWidget` không còn 42703);
- 🔧 C4 / VB-E15: nguồn cổng `price_lists` chỉ bảng giá của NPP (bảng giá chung + bảng mặc định của nhóm khách, đang bật);
- chỉ mục `NPP Phieu Thu Dong.cong_no` (§2.13).
Dựng trên bộ nền của bài Xuất hàng (test_tao_don.dung_nen + test_xuat_hang.dung_kho).
"""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.ghi import ghi
from nppsale.cong.sql import BoThamSo, LoiCong
from nppsale.cong.truy_van import doc
from nppsale.luat.bao_cao import CAU_QUA_HAN, MA_QUA_HAN
from nppsale.rpc import bao_cao as BC
from nppsale.tests import test_xuat_hang as XH
from nppsale.tests.test_tao_don import dung_nen

COT_WS = "id, org_id, user_id, entity_type, entity_id, stage, last_url, form_draft, entity_label, last_action_at, created_at, closed_at"


class TestBaoCaoNen(IntegrationTestCase):
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
		self.han_cu = frappe.db.get_execution_timeout()

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_ngu_canh = None
		frappe.db.set_execution_timeout(self.han_cu)

	def _nc(self, nguoi: str) -> NguCanh:
		u = self.ma["u:" + nguoi]
		return NguCanh(user=u, vai=frappe.db.get_value("NPP Nhan Vien", u, "vai"))

	def _goi(self, nguoi: str, ten: str, ts: dict | None = None) -> dict:
		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None
		try:
			return api.rpc(ten=ten, tham_so=ts or {})
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	def _rest(self, nguoi: str, duong: str, ts: dict | None = None) -> tuple[int, dict]:
		"""Gọi đúng lối `/rest/v1/rpc/<hàm>?q=…` của portal (GET) — nppsale.portal.rest.xu_ly."""
		from nppsale.portal.rest import xu_ly

		class Yc:
			method = "GET"

			def __init__(self):
				self.args = {"q": json.dumps(ts or {})}

			def get_data(self, as_text=False):
				return ""

		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None
		try:
			return xu_ly(duong, Yc())
		finally:
			frappe.set_user("Administrator")
			frappe.local._npp_ngu_canh = None

	# ------------------------------------------------------------------------------------------------ khung §2.0
	def test_ngay_nhu_postgres(self):
		"""`_ngay`: None → None (SQL NULL); '' / chữ → 22007; ngày không có thật → 22008; ISO (kể cả kèm giờ) → date — `getdate('')` (= hôm nay) không lọt."""
		self.assertIsNone(BC._ngay(None))
		self.assertEqual(BC._ngay("2026-11-17"), dt.date(2026, 11, 17))
		self.assertEqual(BC._ngay("2026-11-17T23:59:00+07:00"), dt.date(2026, 11, 17))
		for v, ma in (("", "22007"), ("abc", "22007"), ("2026-02-30", "22008"), ("2026-13-01", "22008")):
			with self.assertRaises(LoiCong) as e:
				BC._ngay(v)
			self.assertEqual(e.exception.ma, ma, v)
		self.assertEqual(BC._ky(dt.date(2026, 11, 1), dt.date(2026, 11, 30)), (dt.datetime(2026, 11, 1), dt.datetime(2026, 12, 1)))
		self.assertIsNone(BC._ky(None, dt.date(2026, 11, 30)))
		self.assertEqual(BC._hom_nay(), getdate(nowdate()))

	def test_la_nv_va_ve_rls(self):
		"""`_la_nv` = user_org_id() IS NOT NULL; `_ve` = vế RLS của BẢNG CỔNG (một luật với câu đọc thẳng): NVBH chỉ dòng nợ mình giữ, thủ kho không dòng
		nào, chủ mọi dòng; bảng chưa đăng ký → 42P01."""
		self.assertFalse(BC._la_nv(NguCanh(user="x@y", vai=None)))
		self.assertTrue(BC._la_nv(self._nc("sales_a")))
		self.assertTrue(BC._la_nv(NguCanh(user="Administrator", bo_qua_rls=True)))
		ts = BoThamSo()
		ve = BC._ve("receivables", self._nc("sales_a"), "rc", ts)
		self.assertEqual(ve, "(rc.`nhan_vien` = %(p0)s)")
		self.assertEqual(ts.gia_tri, {"p0": self.ma["u:sales_a"]})
		self.assertEqual(BC._ve("receivables", self._nc("warehouse"), "rc", BoThamSo()), "1=0")
		self.assertEqual(BC._ve("receivables", self._nc("owner"), "rc", BoThamSo()), "(1 = 1)")
		with self.assertRaises(LoiCong) as e:
			BC._ve("bang_khong_co", self._nc("owner"), "x", BoThamSo())
		self.assertEqual(e.exception.ma, "42P01")

	def test_so(self):
		self.assertEqual(BC._so(Decimal("12.50")), 12.5)
		self.assertIs(type(BC._so(1200.0)), int)
		self.assertEqual(BC._so("337200.000000"), 337200)
		self.assertIsNone(BC._so(None))
		self.assertEqual(BC._so(Decimal("-0.5"), "so"), -0.5)

	def test_can_nguon_q14(self):
		"""❓Q14: nguồn thiếu → PGRST202 đúng câu "hàm chưa có" của cổng (404); đủ thì không làm gì. Kiểm theo BẢNG CỔNG — `expenses` chưa đăng ký (P7)."""
		with self.assertRaises(LoiCong) as e:
			BC._can_nguon("finance_pnl", "receivables", "expenses")
		self.assertEqual((e.exception.ma, e.exception.thong_diep, e.exception.http),
			("PGRST202", "Could not find the function public.finance_pnl in the schema cache", 404))
		self.assertEqual(api._loi(e.exception), {"error": {"message": "Could not find the function public.finance_pnl in the schema cache",
			"code": "PGRST202", "details": None, "hint": None}, "status": 404})
		self.assertIsNone(BC._can_nguon("finance_cash_flow", "receivables", "payables", "payable_payments"))

	# ------------------------------------------------------------------------------------------------ L11 — quá hạn → 57014
	def test_chay_qua_han_57014_tra_lai_han(self):
		"""`_chay`: câu quá `max_statement_time` (MariaDB 1969) → LoiCong 57014 + câu Postgres, HTTP 500; hẹn giờ phiên trả về mức cũ (câu sau không bị
		cắt); lỗi khác (bảng thiếu) KHÔNG đổi thành 57014; giá trị trả về đi qua nguyên vẹn."""
		truoc = frappe.db.get_execution_timeout()
		with self.assertRaises(LoiCong) as e:
			BC._chay(lambda: frappe.db.sql("SELECT SLEEP(2)"), 0.2)
		self.assertEqual((e.exception.ma, e.exception.thong_diep, e.exception.http), (MA_QUA_HAN, CAU_QUA_HAN, 500))
		self.assertEqual(frappe.db.get_execution_timeout(), truoc)
		self.assertEqual(frappe.db.sql("SELECT SLEEP(0.3)")[0][0], 0)  # không còn bị cắt
		with self.assertRaises(Exception) as e:
			BC._chay(lambda: frappe.db.sql("SELECT * FROM `tabKhong Co Bang Nay`"), 5)
		self.assertNotIsInstance(e.exception, LoiCong)
		self.assertEqual(BC._chay(lambda: {"lo": [], "dong": []}, 5), {"lo": [], "dong": []})
		# hẹn lồng nhau: khối trong trả về hẹn của khối ngoài
		def ngoai():
			BC._chay(lambda: None, 3)
			return frappe.db.get_execution_timeout()
		self.assertEqual(float(BC._chay(ngoai, 7)), 7.0)

	def test_cong_rpc_qua_han_57014(self):
		"""VB-E16: lỗi quá hạn ở BẤT KỲ RPC / câu đọc nào của cổng (`cong/api.py::_loi`) → {error: {code: 57014, message: "canceling statement due to
		statement timeout"}, status 500} — qua `/rest/v1/rpc/…` là HTTP 500 cùng thân (trước đây 500 XX000 "Lỗi máy chủ…", giao diện không dịch
		`QUA_HAN_VI`); `bao_cao_*` dưới hẹn của `_chay`; lỗi khác ném tiếp (portal trả 500 XX000 như trước)."""
		from nppsale import rpc as R

		R.nap()

		def cham():
			with frappe.db.execution_timeout(0.2):
				frappe.db.sql("SELECT SLEEP(2)")

		def bang_thieu():
			frappe.db.sql("SELECT * FROM `tabKhong Co Bang Nay`")

		R.DANG_KY["__thu_qua_han"] = R.MucRpc(cham, ghi=False)
		R.DANG_KY["__thu_loi_khac"] = R.MucRpc(bang_thieu, ghi=False)
		try:
			mong = {"error": {"message": CAU_QUA_HAN, "code": MA_QUA_HAN, "details": None, "hint": None}, "status": 500}
			self.assertEqual(self._goi("owner", "__thu_qua_han"), mong)
			ma, than = self._rest("owner", "rpc/__thu_qua_han")
			self.assertEqual((ma, than), (500, {"error": mong["error"]}))
			# lỗi khác (bảng thiếu) KHÔNG thành 57014: `_loi` ném tiếp → portal/rest.py (CongRest.render) trả 500 XX000 như trước
			with self.assertRaises(Exception) as e:
				self._goi("owner", "__thu_loi_khac")
			self.assertNotIsInstance(e.exception, LoiCong)
			self.assertTrue(frappe.db.is_missing_table(e.exception) or "Khong Co Bang Nay" in str(e.exception), e.exception)
		finally:
			R.DANG_KY.pop("__thu_qua_han", None)
			R.DANG_KY.pop("__thu_loi_khac", None)
		# bao_cao_ton_kho / bao_cao_cong_no chạy dưới hẹn `HET_GIO_BAO_CAO` — ép hẹn rất nhỏ thì câu quá hạn ra 57014
		hn = str(getdate(nowdate()))
		with patch("nppsale.luat.bao_cao.HET_GIO_BAO_CAO", 0.000001):
			for ten, ts in (("bao_cao_ton_kho", {"p_tu": hn, "p_den": hn}), ("bao_cao_cong_no", {"p_tu_thu": hn, "p_tu_90": hn})):
				ma, than = self._rest("owner", f"rpc/{ten}", ts)
				self.assertEqual((ma, than), (500, {"error": mong["error"]}), ten)
		self.assertNotIn("error", self._goi("owner", "bao_cao_ton_kho", {"p_tu": hn, "p_den": hn}))

	def test_bao_cao_cong_no_tham_so_ngay(self):
		"""§2.12 (soát thiếu): `bao_cao_cong_no('')` → 22007 như nppsale (trước đây '' bị coi như NULL); NULL → bỏ khối; ngày sai → 22008."""
		ket = self._goi("owner", "bao_cao_cong_no", {"p_tu_thu": "", "p_tu_90": None})
		self.assertEqual(ket["error"]["code"], "22007", ket)
		self.assertEqual(self._goi("owner", "bao_cao_cong_no", {"p_tu_thu": "2026-02-30"})["error"]["code"], "22008")
		ket = self._goi("owner", "bao_cao_cong_no", {})
		self.assertNotIn("error", ket, ket)
		self.assertEqual((ket["data"]["gan90"], ket["data"]["thu"]), ([], []))

	# ------------------------------------------------------------------------------------------------ C1 — lọc giờ có múi giờ
	def test_c1_loc_gio_co_mui_gio(self):
		"""VB-E11 / §3.3-C1: bản ghi lập 23:30 VN ngày D — lọc `created_at >= (D+1) 00:00 VN` viết 'Z' (= D 17:00Z, `toISOString()` của giao diện) hay
		'+07:00' đều KHÔNG ra (trước đây 'Z' bị hiểu là 17:00 GIỜ VN → ra); mốc 23:00 VN ('D 16:00Z') thì ra; chuỗi không múi giờ đọc như giờ site."""
		k = self.ma["C1"]
		d = getdate(nowdate())
		frappe.db.sql("UPDATE `tabCustomer` SET `creation` = %s WHERE `name` = %s", (dt.datetime.combine(d, dt.time(23, 30)), k))
		mai = d + dt.timedelta(days=1)

		def ra(loc):
			return [r["id"] for r in doc({"bang": "customers", "select": "id, created_at", "loc": [{"op": "eq", "cot": "id", "gt": k}, loc]},
				self._nc("owner"))["data"]]

		z = (dt.datetime.combine(mai, dt.time(0, 0)) - dt.timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
		self.assertEqual(ra({"op": "gte", "cot": "created_at", "gt": z}), [])
		self.assertEqual(ra({"op": "gte", "cot": "created_at", "gt": f"{mai.isoformat()}T00:00:00+07:00"}), [])
		self.assertEqual(ra({"op": "gte", "cot": "created_at", "gt": f"{d.isoformat()}T16:00:00.000Z"}), [k])
		self.assertEqual(ra({"op": "lt", "cot": "created_at", "gt": z}), [k])
		self.assertEqual(ra({"op": "gte", "cot": "created_at", "gt": f"{d.isoformat()}T23:00:00"}), [k])  # không múi giờ = giờ site (❓Q5)
		self.assertEqual(ra({"op": "gte", "cot": "created_at", "gt": f"{d.isoformat()}T23:45:00"}), [])
		# khách đầu ngày D+1 (00:30 VN = D 17:30Z) — mốc 'Z' của 00:00 VN ra đúng khách ấy
		frappe.db.sql("UPDATE `tabCustomer` SET `creation` = %s WHERE `name` = %s", (dt.datetime.combine(mai, dt.time(0, 30)), k))
		self.assertEqual(ra({"op": "gte", "cot": "created_at", "gt": z}), [k])
		self.assertEqual(ra({"op": "lt", "cot": "created_at", "gt": z}), [])

	# ------------------------------------------------------------------------------------------------ C2 — workflow_sessions
	def test_c2_workflow_sessions_du_cot(self):
		"""`listOpenSessions` (src/lib/workflow/sessions.ts:141-156): 12 cột + `is('closed_at', null)` + sắp `last_action_at desc` → `[]` sạch (trước
		đây 42703); cột nppsale không có (`state`) → 42703 như nppsale; ghi (insert / update closed_at / form_draft) trả thành công, không lưu gì."""
		u = self.ma["u:sales_a"]
		ket = doc({"bang": "workflow_sessions", "select": COT_WS, "loc": [{"op": "eq", "cot": "user_id", "gt": u},
			{"op": "is", "cot": "closed_at", "gt": None}], "thu_tu": [{"cot": "last_action_at", "tang": False}]}, self._nc("sales_a"))
		self.assertEqual(ket["data"], [])
		with self.assertRaises(LoiCong) as e:
			doc({"bang": "workflow_sessions", "select": "id, state"}, self._nc("sales_a"))
		self.assertEqual(e.exception.ma, "42703")
		frappe.set_user(u)
		try:
			nc = self._nc("sales_a")
			self.assertEqual(ghi({"bang": "workflow_sessions", "hanh_dong": "insert", "gia_tri": {"org_id": None, "user_id": u, "entity_type":
				"sales_order", "entity_id": "x", "stage": "editing_lines", "last_url": "/x", "entity_label": None, "form_draft": {}},
				"select": "id"}, nc)["data"], [])
			self.assertEqual(ghi({"bang": "workflow_sessions", "hanh_dong": "update", "gia_tri": {"closed_at": "2026-11-17T01:00:00.000Z"},
				"loc": [{"op": "eq", "cot": "user_id", "gt": u}, {"op": "is", "cot": "closed_at", "gt": None}]}, nc).get("data") or [], [])
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------------------------------------------------------ C4 — price_lists chỉ bảng giá NPP
	def test_c4_price_lists_chi_bang_gia_npp(self):
		"""VB-E15 / §3.3-C4: Item Price của bảng giá bán NGOÀI NPP (vd `Standard Selling` của lõi) không vào cổng `price_lists` — cả đọc thẳng lẫn lồng
		`products(price_lists(…))` mà giao diện dùng cho "Theo bảng giá" / giá POS; bảng giá chung (group null) và bảng mặc định của nhóm khách (group =
		nhóm) vẫn có; bảng giá bị tắt thì không."""
		p1, g1 = self.ma["P1"], self.ma["G1"]
		if not frappe.db.exists("Price List", "Standard Selling"):
			frappe.get_doc({"doctype": "Price List", "price_list_name": "Standard Selling", "selling": 1, "currency": "VND",
				"enabled": 1}).insert(ignore_permissions=True)
		frappe.db.set_value("Price List", "Standard Selling", {"selling": 1, "enabled": 1})
		frappe.get_doc({"doctype": "Item Price", "item_code": p1, "price_list": "Standard Selling", "uom": "Lon",
			"price_list_rate": 13151}).insert(ignore_permissions=True)

		def gia(nguoi="owner"):
			ds = doc({"bang": "price_lists", "select": "unit_name, price, group_id", "loc": [{"op": "eq", "cot": "product_id", "gt": p1}]},
				self._nc(nguoi))["data"]
			long_ = doc({"bang": "products", "select": "id, price_lists(unit_name, price, group_id)", "loc": [{"op": "eq", "cot": "id", "gt": p1}]},
				self._nc(nguoi))["data"][0]["price_lists"]
			return sorted((x["unit_name"], x["price"], x["group_id"]) for x in ds), sorted((x["unit_name"], x["price"], x["group_id"]) for x in long_)

		mong = sorted([("Lon", 10000, None), ("Thung", 230000, None), ("Lon", 9500, g1)])
		self.assertEqual(gia(), (mong, mong))
		self.assertEqual(gia("sales_a"), (mong, mong))
		# bảng mặc định của nhóm khách bị tắt → không còn là nguồn giá
		bg = frappe.db.get_value("Customer Group", g1, "default_price_list")
		frappe.db.set_value("Price List", bg, "enabled", 0)
		mong2 = sorted([("Lon", 10000, None), ("Thung", 230000, None)])
		self.assertEqual(gia(), (mong2, mong2))

	# ------------------------------------------------------------------------------------------------ chỉ mục §2.13
	def test_chi_muc_phieu_thu_dong_cong_no(self):
		"""§2.13: `NPP Phieu Thu Dong.cong_no` có chỉ mục (khoản thu theo dòng nợ — `payments` lồng `receivable`, `finance_*` JOIN NPP Cong No)."""
		cot = frappe.db.sql("""SELECT DISTINCT `column_name` FROM information_schema.statistics WHERE `table_schema` = DATABASE()
			AND `table_name` = 'tabNPP Phieu Thu Dong' AND `seq_in_index` = 1""", pluck=True)
		self.assertIn("cong_no", cot)
		self.assertTrue(frappe.get_meta("NPP Phieu Thu Dong").get_field("cong_no").search_index)


_ = add_days
