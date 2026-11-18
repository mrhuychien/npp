"""Nền báo cáo P6 (mốc M0 — đặc tả báo cáo P6 §2.0, §3.3, L5, L11, ❓Q14) + `bao_cao_so_ban` (mốc M1 — §2.1) — cần bench:

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

`TestBaoCaoSoBan` (M1): `bao_cao_so_ban` trên Sổ BC của bài vàng P6 (test_bao_cao_vang — dựng lại qua RPC dưới đúng người, đồng hồ ghim): dạng JSON (đúng 6
khối nppsale + `tinh_lai_gia_von` ❓Q12, bộ khoá từng khối, kiểu — không `Decimal` / datetime lọt ra, `dong_hd` xếp theo id, GET qua /rest/v1/rpc), biên
tham số (NULL / ngược / '' / chữ / ngày không có thật / ngày kèm giờ), người ngoài NPP / NV bị khoá / Guest, vế RLS từng vai (văn phòng + thủ kho mọi
chứng từ; NVBH HĐ mình / của đơn mình, phiếu mình), che giá vốn (❓Q3 — `gv[].tien` / `gv_tra[].tien` null với người thiếu ô `inventory.cost`,
số lượng không che), đếm việc tính lại giá vốn (❓Q12). Số cụ thể từng khối so ở bài vàng (VB-A01…A15, E01, E06, E09, E15, E16).
"""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, nowdate

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.ghi import ghi
from nppsale.cong.sql import BoThamSo, LoiCong
from nppsale.cong.truy_van import doc
from nppsale.luat.bao_cao import CAU_QUA_HAN, MA_QUA_HAN
from nppsale.rpc import bao_cao as BC
from nppsale.tests import test_bao_cao_vang as V
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
			for ten, ts in (("bao_cao_ton_kho", {"p_tu": hn, "p_den": hn}), ("bao_cao_cong_no", {"p_tu_thu": hn, "p_tu_90": hn}),
					("bao_cao_so_ban", {"p_tu": hn, "p_den": hn})):
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


class TestBaoCaoSoBan(V.TestBaoCaoVang):
	"""`bao_cao_so_ban` (đặc tả báo cáo P6 §2.1) trên Sổ BC của bài vàng."""

	test_kich_ban_vang = None  # bài so vàng chạy ở test_bao_cao_vang
	KHOI = ("hd", "dong_hd", "tra", "dong_tra", "gv", "gv_tra")

	def setUp(self):
		super().setUp()
		sai = self._dung_s1()
		self.assertFalse(sai, "\n".join(sai))
		self.sd = self.bo["S1"]

	def _sb(self, nguoi: str | None, tu="2026-11-01", den="2026-11-30") -> dict:
		email = self.sd.ma["k:" + nguoi] if nguoi in ("CHU", "QL", "KT", "TK", "NV_AN", "NV_BINH") else nguoi
		return self._goi(email, "bao_cao_so_ban", {"p_tu": tu, "p_den": den}, "2026-11-17T08:00:00+07:00")

	def _rong(self, tinh_lai=0) -> dict:
		return {**{k: [] for k in self.KHOI}, "tinh_lai_gia_von": tinh_lai}

	def test_dang_json(self):
		"""L12: dict đúng 6 khối nppsale (mỗi khối một list) + `tinh_lai_gia_von` (số nguyên — ❓Q12); bộ khoá từng khối như `to_jsonb` / `jsonb_build_object`
		của mig 256; kiểu như PostgREST (ngày 'YYYY-MM-DD', giờ ISO +07:00, bool thật, số int khi chẵn, chuỗi rỗng → null); `dong_hd` ORDER BY id (đường lùi
		`.order('id')`); đi được bằng GET /rest/v1/rpc/bao_cao_so_ban?q=… (portal)."""
		import re

		kq = self._sb("CHU")["data"]
		self.assertEqual(sorted(kq), sorted([*self.KHOI, "tinh_lai_gia_von"]))
		self.assertTrue(all(isinstance(kq[k], list) for k in self.KHOI))
		self.assertIs(type(kq["tinh_lai_gia_von"]), int)
		json.dumps(kq)  # không Decimal / datetime lọt ra (portal/rest.py in Decimal thành CHUỖI)
		self.assertEqual([r["id"] for r in kq["dong_hd"]], sorted(r["id"] for r in kq["dong_hd"]))
		cua = self._loc_so_ban(kq, self.sd)
		khoa = {"hd": {"id", "invoice_code", "invoice_date", "order_id", "status", "total", "subtotal", "vat", "customer_id", "sales_user_id",
			"posted_by", "payment_terms"}, "dong_hd": {"id", "invoice_id", "product_id", "unit_name", "conversion_factor", "quantity", "unit_price",
			"line_total", "is_exchange", "line_discount", "order_line_id"}, "tra": {"id", "status", "customer_id", "invoice_id", "credit_note_amount",
			"created_at", "revenue_date", "sales_user_id", "reason", "credit_with_invoice", "ma"}, "dong_tra": {"return_id", "product_id", "unit_name",
			"quantity", "line_total", "unit_price"}, "gv": {"product_id", "sl", "tien"}, "gv_tra": {"return_id", "product_id", "tien"}}
		for k, bo in khoa.items():
			self.assertTrue(cua[k], k)
			self.assertEqual({tuple(sorted(r)) for r in cua[k]}, {tuple(sorted(bo))}, k)
		hd1 = next(r for r in cua["hd"] if r["id"] == self.sd.nhan["HD-0001"])
		self.assertEqual((hd1["invoice_date"], hd1["status"], hd1["total"], hd1["subtotal"], hd1["vat"], hd1["posted_by"], hd1["sales_user_id"],
			hd1["payment_terms"], hd1["invoice_code"], hd1["order_id"]), ("2026-11-03", "posted", 534000, 530000, 4000, self.sd.ma["k:CHU"],
			self.sd.ma["k:NV_AN"], "COD", self.sd.nhan["HD-0001"], self.sd.nhan["DH-0001"]))
		self.assertIs(type(hd1["total"]), int)
		doi = next(r for r in cua["dong_hd"] if r["is_exchange"])
		self.assertEqual((doi["is_exchange"], doi["order_line_id"], doi["unit_price"], doi["line_total"]), (True, None, 0, 0))
		self.assertTrue(all(type(r["is_exchange"]) is bool and type(r["conversion_factor"]) is int for r in cua["dong_hd"]))
		pt1 = next(r for r in cua["tra"] if r["id"] == self.sd.nhan["PT-0001"])
		self.assertRegex(pt1["created_at"], r"^2026-11-16T20:50:47(\.\d+)?\+07:00$")
		self.assertEqual((pt1["revenue_date"], pt1["credit_with_invoice"], pt1["reason"], pt1["ma"], pt1["status"]),
			("2026-11-03", True, "damaged", self.sd.nhan["PT-0001"], "completed"))
		pt3 = next(r for r in cua["tra"] if r["id"] == self.sd.nhan["PT-0003"])
		self.assertEqual((pt3["invoice_id"], pt3["credit_with_invoice"]), (None, False))
		self.assertTrue(all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["revenue_date"]) for r in cua["tra"]))
		# GET qua lối của portal (`goiMotLuot` — {get: true}): cùng kết quả
		ma, than = self._rest_get("rpc/bao_cao_so_ban", {"p_tu": "2026-11-01", "p_den": "2026-11-30"})
		self.assertEqual((ma, json.loads(json.dumps(than["data"], default=str))), (200, json.loads(json.dumps(kq))))

	def _rest_get(self, duong: str, ts: dict) -> tuple[int, dict]:
		from nppsale.portal.rest import xu_ly

		class Yc:
			method = "GET"

			def __init__(self):
				self.args = {"q": json.dumps(ts)}

			def get_data(self, as_text=False):
				return ""

		V.DongHo.dat("2026-11-17T08:00:00+07:00")
		self._nguoi(self.sd.ma["k:CHU"])
		try:
			return xu_ly(duong, Yc())
		finally:
			self._nguoi(None)

	def test_bien_tham_so_va_nguoi_ngoai(self):
		"""§2.1 bảng biên: một đầu kỳ NULL / kỳ ngược → 6 mảng rỗng, không lỗi; chuỗi không phải ngày (kể cả '' — `getdate('')` là HÔM NAY, không được
		lọt) → 22007, ngày không có thật → 22008 (ép kiểu `date` của PostgREST trước thân hàm); ngày kèm giờ đọc phần ngày; NV bị khoá / người ngoài NPP →
		rỗng đúng dạng (user_org_id() NULL); Guest → PGRST301 401."""
		for tu, den in (("2026-11-30", "2026-11-01"), (None, "2026-11-30"), ("2026-11-01", None), (None, None)):
			self.assertEqual(self._sb("CHU", tu, den)["data"], self._rong(), (tu, den))
		for v, ma, cau in (("abc", "22007", 'invalid input syntax for type date: "abc"'), ("", "22007", 'invalid input syntax for type date: ""'),
				("2026-02-30", "22008", 'date/time field value out of range: "2026-02-30"')):
			ket = self._sb("CHU", v, "2026-11-30")
			self.assertEqual((ket["error"]["code"], ket["error"]["message"]), (ma, cau), v)
			ket = self._sb("CHU", "2026-11-01", v)
			self.assertEqual(ket["error"]["code"], ma, v)
		kq = self._sb("CHU")["data"]
		self.assertEqual(self._sb("CHU", "2026-11-01T00:00:00+07:00", "2026-11-30T23:59:59+07:00")["data"], kq)
		# NV bị khoá (dang_hoat_dong = 0) và người không phải NV của NPP: rỗng đúng dạng, KHÔNG lỗi
		frappe.db.set_value("NPP Nhan Vien", self.sd.ma["k:NV_BINH"], "dang_hoat_dong", 0, update_modified=False)
		self.assertEqual(self._sb("NV_BINH")["data"], self._rong())
		email = "p6m1-ngoai@nppsale.local"
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": "Ngoai", "send_welcome_email": 0}).insert(ignore_permissions=True)
		self.assertEqual(self._sb(email)["data"], self._rong())
		self._nguoi("Guest")
		try:
			ket = api.rpc(ten="bao_cao_so_ban", tham_so={"p_tu": "2026-11-01", "p_den": "2026-11-30"})
		finally:
			self._nguoi(None)
		self.assertEqual((ket["error"]["code"], ket["status"]), ("PGRST301", 401))

	def test_rls_tung_vai_va_che_gia_von(self):
		"""L9: văn phòng + thủ kho thấy mọi HĐ / phiếu trả (cùng một kết quả); NVBH: HĐ mình đứng tên hoặc của đơn mình, phiếu mình lập / đứng tên / gắn HĐ
		/ đơn mình; giá vốn xuất không lọc theo người (phiếu kho: mọi NV — SL như nhau). ❓Q3: `gv[].tien` / `gv_tra[].tien` = null với người thiếu ô
		`inventory.cost` (NVBH mặc định; Kế toán / Quản lý bị thu bằng quyền riêng), số lượng không che; Chủ luôn thấy; Administrator (việc nền) thấy."""
		n = self.sd.nhan
		kq = {v: self._loc_so_ban(self._sb(v)["data"], self.sd) for v in ("CHU", "QL", "KT", "TK", "NV_AN", "NV_BINH")}
		for v in ("QL", "KT", "TK"):
			self.assertEqual({k: kq[v][k] for k in self.KHOI}, {k: kq["CHU"][k] for k in self.KHOI}, v)
		self.assertEqual({r["id"] for r in kq["CHU"]["hd"]}, {n["HD-0001"], n["HD-0002"], n["HD-0005"]})
		self.assertEqual({r["id"] for r in kq["NV_AN"]["hd"]}, {n["HD-0001"], n["HD-0005"]})
		self.assertEqual({r["id"] for r in kq["NV_BINH"]["hd"]}, {n["HD-0002"]})
		self.assertEqual({r["id"] for r in kq["NV_AN"]["tra"]}, {n["PT-0001"], n["PT-0003"], n["PT-0007"]})
		self.assertEqual({r["id"] for r in kq["NV_BINH"]["tra"]}, {n["PT-0002"]})
		self.assertEqual({r["invoice_id"] for r in kq["NV_AN"]["dong_hd"]}, {n["HD-0001"], n["HD-0005"]})
		self.assertEqual({r["return_id"] for r in kq["NV_BINH"]["dong_tra"]}, {n["PT-0002"]})
		sl = {v: sorted((r["product_id"], r["sl"]) for r in kq[v]["gv"]) for v in kq}
		self.assertEqual(len({json.dumps(x) for x in sl.values()}), 1, sl)  # giá vốn xuất: cùng SL với mọi vai
		self.assertEqual(sl["CHU"], [("SP1", 96), ("SP2", 30), ("SP3", 15)])  # Q1 (HĐ4 31/10 sang tháng 10), Q9 (HĐ3 huỷ rơi với mọi vai)
		for v in ("NV_AN", "NV_BINH"):
			self.assertTrue(kq[v]["gv"] and all(r["tien"] is None for r in kq[v]["gv"] + kq[v]["gv_tra"]), v)
		for v in ("CHU", "QL", "KT", "TK"):
			self.assertTrue(all(r["tien"] is not None for r in kq[v]["gv"] + kq[v]["gv_tra"]), v)
		self.assertEqual(sorted((r["product_id"], r["tien"]) for r in kq["CHU"]["gv"]), [("SP1", 672000), ("SP2", 90000), ("SP3", 5000)])
		# thu ô inventory.cost của Kế toán / Quản lý bằng quyền riêng → null, SL giữ; Chủ không thu được
		for v in ("KT", "QL", "CHU"):
			frappe.get_doc({"doctype": "NPP Quyen Rieng", "nhan_vien": self.sd.ma["k:" + v], "khoa_quyen": "inventory.cost.read",
				"duoc_phep": 0}).insert(ignore_permissions=True)
		for v in ("KT", "QL"):
			x = self._loc_so_ban(self._sb(v)["data"], self.sd)
			self.assertTrue(all(r["tien"] is None for r in x["gv"] + x["gv_tra"]), v)
			self.assertEqual(sorted((r["product_id"], r["sl"]) for r in x["gv"]), sl["CHU"], v)
			self.assertEqual(x["hd"], kq["CHU"]["hd"], v)  # doanh thu / trả đủ số
		self.assertEqual(self._loc_so_ban(self._sb("CHU")["data"], self.sd)["gv"], kq["CHU"]["gv"])
		self._nguoi("Administrator")
		try:
			V.DongHo.dat("2026-11-17T08:00:00+07:00")
			ad = self._loc_so_ban(api.rpc(ten="bao_cao_so_ban", tham_so={"p_tu": "2026-11-01", "p_den": "2026-11-30"})["data"], self.sd)
		finally:
			self._nguoi(None)
		self.assertEqual({k: ad[k] for k in self.KHOI}, {k: kq["CHU"][k] for k in self.KHOI})

	def test_to_dau_ky_va_chuoi_rong(self):
		"""L1: tờ nợ đầu kỳ `DK-` (Sales Invoice `is_opening = 'Yes'`, ngày trong kỳ) KHÔNG vào `hd` / `dong_hd` / giá vốn (nợ vẫn ở công nợ — VB-E10);
		chuỗi rỗng Frappe lưu cho Link trống → null như Postgres (`sales_user_id` của phiếu mất người đứng tên)."""
		truoc = self._sb("CHU")["data"]
		ket = self._cong(self.sd.ma["k:CHU"], {"bang": "receivables", "hanh_dong": "insert", "gia_tri": {"org_id": self.sd.ma["org"],
			"customer_id": self.sd.ma["kh:0911000002"], "amount": 1000000, "paid": 0, "opening_balance": True, "due_date": "2026-11-05",
			"status": "open", "note": "No dau ky"}, "select": "id"}, "2026-11-05T08:00:00+07:00")
		self.assertNotIn("error", ket, ket)
		dk = frappe.get_all("Sales Invoice", filters={"customer": self.sd.ma["kh:0911000002"], "is_opening": "Yes", "docstatus": 1},
			fields=["name", "posting_date", "grand_total"])
		self.assertEqual([(str(x.posting_date), float(x.grand_total)) for x in dk], [("2026-11-05", 1000000.0)])  # tờ có thật, ngày trong kỳ
		sau = self._sb("CHU")["data"]
		self.assertEqual({k: sau[k] for k in self.KHOI}, {k: truoc[k] for k in self.KHOI})
		pt3 = self.sd.nhan["PT-0003"]
		frappe.db.set_value("NPP Phieu Tra", pt3, "nhan_vien", "", update_modified=False)
		r = next(x for x in self._sb("CHU")["data"]["tra"] if x["id"] == pt3)
		self.assertIsNone(r["sales_user_id"])

	def test_tinh_lai_gia_von_q12(self):
		"""❓Q12: `tinh_lai_gia_von` = số Repost Item Valuation đã gửi còn `Queued` / `In Progress` có ngày ≤ cuối kỳ (việc ghi lùi về sau kỳ không đổi giá
		vốn trong kỳ); `bao_cao_ton_kho` đếm MỌI việc còn chờ (giá vốn lô hiện tại); việc xong / hỏng / nháp không đếm; người ngoài NPP 0."""
		truoc = self._sb("CHU")["data"]["tinh_lai_gia_von"]
		truoc_tk = self._goi(self.sd.ma["k:CHU"], "bao_cao_ton_kho", {"p_tu": "2026-11-01", "p_den": "2026-11-30"})["data"]["tinh_lai_gia_von"]
		cong_ty = frappe.db.get_single_value("NPP Cai Dat", "cong_ty")
		for i, (tt, ds, ngay) in enumerate((("Queued", 1, "2026-11-20"), ("In Progress", 1, "2026-11-30"), ("Queued", 1, "2026-12-01"),
				("Completed", 1, "2026-11-10"), ("Failed", 1, "2026-11-10"), ("Queued", 0, "2026-11-10"), ("Queued", 2, "2026-11-10"))):
			luc = dt.datetime(2026, 11, 17, 7, 0)
			frappe.db.sql("""INSERT INTO `tabRepost Item Valuation` (`name`, `creation`, `modified`, `modified_by`, `owner`, `docstatus`, `status`,
				`posting_date`, `posting_time`, `company`, `based_on`) VALUES (%s, %s, %s, 'Administrator', 'Administrator', %s, %s, %s, '00:00:00',
				%s, 'Item and Warehouse')""", (f"P6M1-RIV-{i}", luc, luc, ds, tt, ngay, cong_ty))
		self.assertEqual(self._sb("CHU")["data"]["tinh_lai_gia_von"], truoc + 2)  # Queued 20/11 + In Progress 30/11
		self.assertEqual(self._sb("NV_AN")["data"]["tinh_lai_gia_von"], truoc + 2)  # số việc, không phải giá vốn — không che
		self.assertEqual(self._sb("CHU", "2026-12-01", "2026-12-31")["data"]["tinh_lai_gia_von"], truoc + 3)
		self.assertEqual(self._goi(self.sd.ma["k:CHU"], "bao_cao_ton_kho", {"p_tu": "2026-11-01", "p_den": "2026-11-30"})["data"]["tinh_lai_gia_von"],
			truoc_tk + 3)
		# kỳ thiếu một / hai đầu, kỳ ngược: rỗng đúng dạng (tinh_lai_gia_von 0) dù có việc chờ ≤ "cuối kỳ" — mỗi vế của điều kiện thoát sớm có ca riêng
		for tu, den in ((None, None), (None, "2026-11-30"), ("2026-11-01", None), ("2026-12-31", "2026-12-01")):
			self.assertEqual(self._sb("CHU", tu, den)["data"], self._rong(), (tu, den))


NGUOI_S = ("CHU", "QL", "KT", "TK", "NV_AN", "NV_BINH")
GIO_DOC = "2026-11-17T08:00:00+07:00"  # giờ đọc của Sổ BC (vn_today = 17/11)
P11 = {"p_period_start": "2026-11-01"}  # đầu tháng 11 (`dauKy` của /dashboard)


class _TrenSoBC(V.TestBaoCaoVang):
	"""Sổ BC (S1) của bài vàng, đã tách khỏi dữ liệu khác của site dùng chung (`_chi_so_cua_bo` — hàm tổng hợp toàn sổ)."""

	test_kich_ban_vang = None  # bài so vàng chạy ở test_bao_cao_vang

	def setUp(self):
		super().setUp()
		sai = self._dung_s1()
		self.assertFalse(sai, "\n".join(sai))
		self.sd = self.bo["S1"]
		self._chi_so_cua_bo(self.sd)

	def _email_cua(self, nguoi: str) -> str:
		return self.sd.ma["k:" + nguoi] if nguoi in NGUOI_S else nguoi

	def _rpc(self, nguoi: str, ten: str, ts: dict | None = None, gio: str = GIO_DOC) -> dict:
		return self._goi(self._email_cua(nguoi), ten, ts or {}, gio)

	def _rest(self, nguoi: str, ten: str, ts: dict, phuong_thuc: str = "GET") -> tuple[int, dict]:
		"""Lối `/rest/v1/rpc/<hàm>` của portal: GET `?q=<JSON>` (hàm chỉ đọc — `{get: true}`) hoặc POST thân JSON."""
		from nppsale.portal.rest import xu_ly

		class Yc:
			method = phuong_thuc

			def __init__(self):
				self.args = {"q": json.dumps(ts)} if phuong_thuc == "GET" else {}

			def get_data(self, as_text=False):
				return json.dumps(ts) if phuong_thuc == "POST" else ""

		V.DongHo.dat(GIO_DOC)
		self._nguoi(self._email_cua(nguoi))
		try:
			return xu_ly(f"rpc/{ten}", Yc())
		finally:
			self._nguoi(None)

	def _loi(self, ket: dict) -> tuple:
		self.assertIn("error", ket, ket)
		return ket["error"]["code"], ket["error"]["message"]

	def _ngoai_npp(self) -> str:
		email = "p6m2-ngoai@nppsale.local"
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": "Ngoai", "send_welcome_email": 0}).insert(ignore_permissions=True)
		return email


class TestBaoCaoTongQuan(_TrenSoBC):
	"""`dashboard_summary` / `dashboard_channel_revenue` / `dashboard_top_customers` (§2.3-2.5), `my_sales_target` (§2.11), view cổng
	`v_hoa_don_con_lai` dưới RLS phiếu trả của người gọi (security_invoker — mig 257). Số theo vai / mốc ở bài vàng (VB-B01…B06, E03, E10)."""

	TQ = ("dashboard_summary", "dashboard_channel_revenue", "dashboard_top_customers")

	def test_dang_bien_va_nguoi_ngoai(self):
		"""L12: `dashboard_summary` đúng MỘT dòng 4 khoá (số int — không Decimal / chuỗi lọt ra); hai hàm kia list đã xếp. Biên: ngày kèm giờ đọc phần ngày;
		NULL / thiếu tham số → không HĐ / phiếu nào (hai số công nợ vẫn đủ; kênh / top rỗng); '' / chữ → 22007, ngày không có thật → 22008 (ép kiểu
		`date` TRƯỚC thân hàm). Người không phải NV đang hoạt động → rỗng đúng dạng; Guest → PGRST301. GET (`{get: true}`) và POST cùng kết quả."""
		ds = self._rpc("CHU", "dashboard_summary", P11)["data"]
		self.assertEqual(ds, [{"period_revenue": 790960, "period_orders": 3, "open_receivables": 830960, "overdue_count": 1}])
		self.assertTrue(all(type(v) is int for v in ds[0].values()), ds)
		self.assertEqual(self._rpc("CHU", "dashboard_summary", {"p_period_start": "2026-11-01T00:00:00+07:00"})["data"], ds)
		khong = [{"period_revenue": 0, "period_orders": 0, "open_receivables": 830960, "overdue_count": 1}]
		self.assertEqual(self._rpc("CHU", "dashboard_summary", {"p_period_start": None})["data"], khong)
		self.assertEqual(self._rpc("CHU", "dashboard_summary", {})["data"], khong)
		for ham in self.TQ[1:]:
			self.assertEqual(self._rpc("CHU", ham, {"p_period_start": None})["data"], [], ham)
			self.assertEqual(self._rpc("CHU", ham)["data"], [], ham)
		for v, ma, cau in (("", "22007", 'invalid input syntax for type date: ""'), ("abc", "22007", 'invalid input syntax for type date: "abc"'),
				("2026-02-30", "22008", 'date/time field value out of range: "2026-02-30"')):
			for ham in self.TQ:
				self.assertEqual(self._loi(self._rpc("CHU", ham, {"p_period_start": v})), (ma, cau), (ham, v))
		kenh = self._rpc("CHU", "dashboard_channel_revenue", P11)["data"]
		top = self._rpc("CHU", "dashboard_top_customers", P11)["data"]
		self.assertEqual(kenh, [{"channel": "GT", "total": 504000}, {"channel": "MT", "total": 306960}, {"channel": "Khác", "total": -20000}])
		self.assertEqual([(r["customer_id"], r["store_name"], r["total"], r["order_count"]) for r in top],
			[(self.sd.ma["kh:0911000001"], "Tap hoa Hai", 504000, 1), (self.sd.ma["kh:0911000002"], "Sieu thi Ba", 306960, 1),
				(self.sd.ma["kh:0911000003"], "Quan Tu", -20000, 1)])
		json.dumps([ds, kenh, top])
		for ham, mong in zip(self.TQ, (ds, kenh, top), strict=True):
			for pt in ("GET", "POST"):
				ma, than = self._rest("CHU", ham, P11, pt)
				self.assertEqual((ma, json.loads(json.dumps(than["data"]))), (200, mong), (ham, pt))
		# NV bị khoá / người ngoài NPP: rỗng đúng dạng, không lỗi; Guest: PGRST301 401
		rong = {"dashboard_summary": [{"period_revenue": 0, "period_orders": 0, "open_receivables": 0, "overdue_count": 0}],
			"dashboard_channel_revenue": [], "dashboard_top_customers": []}
		frappe.db.set_value("NPP Nhan Vien", self.sd.ma["k:NV_BINH"], "dang_hoat_dong", 0, update_modified=False)
		for ai in ("NV_BINH", self._ngoai_npp()):
			for ham in self.TQ:
				self.assertEqual(self._rpc(ai, ham, P11)["data"], rong[ham], (ai, ham))
		self._nguoi("Guest")
		try:
			for ham in self.TQ:
				ket = api.rpc(ten=ham, tham_so=P11)
				self.assertEqual((ket["error"]["code"], ket["status"]), ("PGRST301", 401), ham)
		finally:
			self._nguoi(None)
		# quá hạn 8 s của dashboard_* → 57014 (giao diện dịch QUA_HAN_VI, không hiện 0)
		with patch("nppsale.luat.bao_cao.HET_GIO_NHANH", 0.000001):
			for ham in self.TQ:
				ma, than = self._rest("CHU", ham, P11)
				self.assertEqual((ma, than["error"]["code"], than["error"]["message"]), (500, MA_QUA_HAN, CAU_QUA_HAN), ham)
		self.assertNotIn("error", self._rpc("CHU", "dashboard_summary", P11))

	def test_p_limit_nhu_postgres(self):
		"""`LIMIT GREATEST(1, LEAST(p_limit, 100))` tính ở Python: thiếu → 5 (DEFAULT), null → 100 (LEAST bỏ NULL), ≤ 0 → 1, > 100 → 100; ép kiểu
		`integer` như PostgREST (đo bản tham chiếu `json_to_record`): chuỗi số (bỏ khoảng trắng, có dấu) được; số thực (kể cả 5.0) / bool / chữ / '1e2' →
		22P02 nguyên văn; ngoài int4 → 22003."""
		g = BC.gioi_han_top
		self.assertEqual([g(), g(None), g(0), g(-5), g(1), g(7), g(100), g(101), g(10 ** 6), g("3"), g(" 7 "), g("+2"), g("-1")],
			[5, 100, 1, 1, 1, 7, 100, 100, 100, 3, 7, 2, 1])
		for v, ma, cau in ((2.5, "22P02", 'invalid input syntax for type integer: "2.5"'), (5.0, "22P02", 'invalid input syntax for type integer: "5.0"'),
				(True, "22P02", 'invalid input syntax for type integer: "true"'), ("abc", "22P02", 'invalid input syntax for type integer: "abc"'),
				("1e2", "22P02", 'invalid input syntax for type integer: "1e2"'), ("", "22P02", 'invalid input syntax for type integer: ""'),
				(99999999999, "22003", 'value "99999999999" is out of range for type integer'),
				("-2147483649", "22003", 'value "-2147483649" is out of range for type integer')):
			with self.assertRaises(LoiCong) as e:
				g(v)
			self.assertEqual((e.exception.ma, e.exception.thong_diep), (ma, cau), v)
		self.assertEqual(g(2147483647), 100)
		# qua RPC: số dòng theo giới hạn; lỗi ép kiểu trả về người gọi
		for lim, n in ((1, 1), ("2", 2), (0, 1), (-5, 1), (None, 3), (5, 3)):
			ket = self._rpc("CHU", "dashboard_top_customers", {**P11, "p_limit": lim})
			self.assertEqual(len(ket["data"]), n, (lim, ket))
		self.assertEqual(self._loi(self._rpc("CHU", "dashboard_top_customers", {**P11, "p_limit": "abc"})),
			("22P02", 'invalid input syntax for type integer: "abc"'))

	def test_kenh_top_va_so_don_nhu_postgres(self):
		"""Kênh nhóm theo chuỗi ĐÚNG như Postgres (gộp ở Python — `GROUP BY` của MariaDB `utf8mb4_unicode_ci` gộp 'GT' với 'gt'); kênh chỉ có khoảng trắng
		giữ nguyên (NULLIF(' ', '') của Postgres không ra NULL; MariaDB PAD SPACE coi ' ' = ''); bằng tiền → khoá phụ theo điểm mã. Số đơn không đếm HĐ
		không đơn ('' của Frappe = NULL); top: bằng tiền → khoá phụ mã khách; khách chỉ có hàng trả không vào top."""
		k1, k2, k3 = (self.sd.ma[f"kh:091100000{i}"] for i in (1, 2, 3))
		frappe.db.set_value("Customer", k2, "npp_tuyen", "gt", update_modified=False)
		frappe.db.set_value("Customer", k3, "npp_tuyen", " ", update_modified=False)
		self.assertEqual(self._rpc("CHU", "dashboard_channel_revenue", P11)["data"],
			[{"channel": "GT", "total": 504000}, {"channel": "gt", "total": 306960}, {"channel": " ", "total": -20000}])
		frappe.db.set_value("Customer", k3, "npp_tuyen", "", update_modified=False)
		# bằng tiền: đổi thẳng tiền HĐ1 cho K1 thuần 306.960 như K2 (336.960 - 30.000 của PT-0001)
		hd1 = self.sd.nhan["HD-0001"]
		frappe.db.set_value("Sales Invoice", hd1, "grand_total", 336960, update_modified=False)
		frappe.db.set_value("Customer", k1, "npp_tuyen", "MT", update_modified=False)
		frappe.db.set_value("Customer", k2, "npp_tuyen", "GT", update_modified=False)
		self.assertEqual(self._rpc("CHU", "dashboard_channel_revenue", P11)["data"],
			[{"channel": "GT", "total": 306960}, {"channel": "MT", "total": 306960}, {"channel": "Khác", "total": -20000}])
		top = self._rpc("CHU", "dashboard_top_customers", {**P11, "p_limit": 2})["data"]
		self.assertEqual([r["customer_id"] for r in top], sorted([k1, k2]))  # bằng tiền → mã khách tăng
		# HĐ không đơn ('' của Frappe) không đếm vào số đơn (COUNT(DISTINCT order_id) bỏ NULL)
		frappe.db.set_value("Sales Invoice", self.sd.nhan["HD-0002"], "npp_don_hang", "", update_modified=False)
		self.assertEqual(self._rpc("CHU", "dashboard_summary", P11)["data"][0]["period_orders"], 2)
		self.assertEqual({r["customer_id"]: r["order_count"] for r in self._rpc("CHU", "dashboard_top_customers", P11)["data"]},
			{k1: 1, k2: 0, k3: 1})
		# khách chỉ có hàng trả (từ 21/11: chỉ PT-0006 02/12 của K2) không vào top; kênh vẫn trừ
		self.assertEqual(self._rpc("CHU", "dashboard_top_customers", {"p_period_start": "2026-11-21"})["data"], [])
		self.assertEqual(self._rpc("CHU", "dashboard_channel_revenue", {"p_period_start": "2026-11-21"})["data"], [{"channel": "GT", "total": -10800}])

	def test_my_sales_target(self):
		"""§2.11: SỐ TRƠN; tới khi P7 có DocType `NPP Cau Hinh Luong` → 0 với mọi vai (giao diện ẩn cột Chỉ tiêu / mục tiêu); có DocType → Single
		`muc_doanh_so_a` (chưa lưu → 0; KHÔNG xét `dang_dung`), int khi chẵn; NV bị khoá / người ngoài → 0. Đăng ký MỘT chỗ (P7 không khai lại), nhận
		cả GET lẫn POST."""
		from nppsale import rpc as R

		R.nap()
		self.assertIs(R.DANG_KY["my_sales_target"].ham, BC.my_sales_target)
		self.assertFalse(R.DANG_KY["my_sales_target"].ghi)
		self.assertFalse(frappe.db.exists("DocType", BC.DT_CAU_HINH_LUONG))  # P7 chưa dựng — đổi bài khi P7 tới
		for v in NGUOI_S:
			self.assertEqual(self._rpc(v, "my_sales_target"), {"data": 0, "status": 200}, v)
		self.assertEqual(BC.muc_tieu_doanh_so(), Decimal(0))
		goc_exists, goc_single = frappe.db.exists, frappe.db.get_single_value
		gia_tri = {"v": 80000000.0}
		doc_luc = []

		def exists(dt, dn=None, *a, **k):
			if (dt, dn) == ("DocType", BC.DT_CAU_HINH_LUONG):
				return BC.DT_CAU_HINH_LUONG
			return goc_exists(dt, dn, *a, **k)

		def single(dt, f, cache=True):
			if dt == BC.DT_CAU_HINH_LUONG:
				doc_luc.append((f, cache))
				return gia_tri["v"]
			return goc_single(dt, f, cache=cache)

		with patch.object(frappe.db, "exists", exists), patch.object(frappe.db, "get_single_value", single):
			self.assertEqual(self._rpc("NV_AN", "my_sales_target")["data"], 80000000)
			self.assertIs(type(self._rpc("CHU", "my_sales_target")["data"]), int)
			self.assertEqual(doc_luc[0], ("muc_doanh_so_a", False))  # đọc thẳng sổ, không qua cache
			gia_tri["v"] = 1234.5
			self.assertEqual(self._rpc("KT", "my_sales_target")["data"], 1234.5)
			gia_tri["v"] = None  # Single chưa lưu
			self.assertEqual(self._rpc("NV_AN", "my_sales_target")["data"], 0)
			gia_tri["v"] = 5000000.0
			ma, than = self._rest("NV_AN", "my_sales_target", {}, "GET")
			self.assertEqual((ma, than["data"]), (200, 5000000))
			frappe.db.set_value("NPP Nhan Vien", self.sd.ma["k:NV_BINH"], "dang_hoat_dong", 0, update_modified=False)
			self.assertEqual(self._rpc("NV_BINH", "my_sales_target")["data"], 0)
			self.assertEqual(self._rpc(self._ngoai_npp(), "my_sales_target")["data"], 0)

	def test_con_lai_theo_rls_phieu_tra(self):
		"""`v_hoa_don_con_lai` (mig 257) là view `security_invoker`: câu con phiếu trả chạy dưới RLS `returns` của NGƯỜI GỌI. Bộ S3 (HĐ5 của đơn NV An gán
		sang NV Bình) + NV Bình lập phiếu tự lập 10.000 gắn HĐ5 (không đơn), Chủ Hoàn thành: NV An vẫn thấy HĐ5 (đơn của mình) nhưng KHÔNG thấy phiếu ⇒
		con_lai 220.000 (chỉ trừ PT-0007 tự sinh của đơn mình); NV Bình / Chủ / thủ kho 210.000 — số đo trên bản tham chiếu (vbc_s3, BEGIN … ROLLBACK).
		Lọc / gộp trên `con_lai` (`gopMayChu` — `con_lai.sum()`) dùng cùng biểu thức của người gọi."""
		sd = self.sd
		sai = self._phat_lai("S3", sd)
		self.assertFalse(sai, sai)
		hd5, k3, sp1 = sd.nhan["HD-0005"], sd.ma["kh:0911000003"], sd.ma["sp:SP1"]
		pt = self._rpc("NV_BINH", "create_return_with_lines", {"p_head": {"customer_id": k3, "invoice_id": hd5, "reason": "damaged", "status": "draft"},
			"p_lines": [{"product_id": sp1, "unit_name": V.uom_site("lon"), "quantity": 1, "unit_price": 10000, "vat_rate": 0, "line_total": 10000,
				"is_exchange": False}]}, "2026-11-16T21:05:00+07:00")
		self.assertNotIn("error", pt, pt)
		ten_pt = pt["data"] if isinstance(pt["data"], str) else pt["data"][0]["return_id"]
		ket = self._rpc("CHU", "complete_return", {"p_return_id": ten_pt, "p_zone": "sale"}, "2026-11-16T21:05:01+07:00")
		self.assertNotIn("error", ket, ket)
		self.assertEqual(frappe.db.get_value("NPP Phieu Tra", ten_pt, ["trang_thai", "hoa_don", "don_hang", "nhan_vien"]),
			("completed", hd5, None, sd.ma["k:NV_BINH"]))

		def con_lai(nguoi, them_loc=()):
			V.DongHo.dat(GIO_DOC)
			nc = NguCanh(user=self._email_cua(nguoi), vai=frappe.db.get_value("NPP Nhan Vien", self._email_cua(nguoi), "vai"))
			return {r["id"]: r["con_lai"] for r in doc({"bang": "v_hoa_don_con_lai", "select": "id, total, con_lai",
				"loc": [{"op": "eq", "cot": "id", "gt": hd5}, *them_loc]}, nc)["data"]}

		self.assertEqual(con_lai("NV_AN"), {hd5: 220000})
		for v in ("NV_BINH", "CHU", "TK", "KT"):
			self.assertEqual(con_lai(v), {hd5: 210000}, v)
		# lọc trên con_lai theo biểu thức của người gọi
		self.assertEqual(con_lai("NV_AN", ({"op": "gt", "cot": "con_lai", "gt": 215000},)), {hd5: 220000})
		self.assertEqual(con_lai("CHU", ({"op": "gt", "cot": "con_lai", "gt": 215000},)), {})
		# gộp trên máy chủ (`gopMayChu` — con_lai.sum()) của NV An gồm 220.000 của HĐ5
		V.DongHo.dat(GIO_DOC)
		nc = NguCanh(user=sd.ma["k:NV_AN"], vai="sales")
		tong = doc({"bang": "v_hoa_don_con_lai", "select": "con_lai.sum()", "loc": [{"op": "eq", "cot": "id", "gt": hd5}]}, nc)["data"]
		self.assertEqual(json.loads(json.dumps(tong, default=str)), [{"sum": 220000}])


class TestHangKhachDaLay(_TrenSoBC):
	"""`hang_khach_da_lay` (§2.9, mig 246) — SECURITY DEFINER, CHỈ số lượng theo đơn vị cơ sở. Số cụ thể theo vai ở bài vàng (VB-C01…C04); ở đây: lỗi /
	quyền, ép kiểu tham số, lọc tuyến ĐÚNG chuỗi như Postgres, hệ số dòng trả theo danh mục HIỆN TẠI (❓Q7), thứ tự theo điểm mã (❓Q8), `nv_chinh`."""

	def _hang(self, nguoi: str, ts: dict) -> dict:
		ket = self._rpc(nguoi, "hang_khach_da_lay", ts)
		self.assertNotIn("error", ket, ket)
		return self._chuan_hang_da_lay(ket["data"], self.sd)

	def test_loi_quyen_va_ep_kieu(self):
		"""P0001 nguyên văn: NV bị khoá / người ngoài NPP → KHONG_DU_QUYEN; thủ kho → "KHONG_DU_QUYEN: vai này không xem hàng khách đã lấy"; chủ / QL / KT
		gửi `p_nv` không phải NV của NPP → KHONG_TIM_THAY_NV (NV đã khoá vẫn là NV của NPP — chỉ kiểm thuộc NPP). Guest → PGRST301. Tham số mảng không
		phải mảng → 22P02 malformed array literal; ngày sai → 22007 / 22008. POST (giao diện gọi) và GET cùng kết quả; quá hạn 8 s → 57014."""
		k1 = self.sd.ma["kh:0911000001"]
		self.assertEqual(self._loi(self._rpc("TK", "hang_khach_da_lay", {"p_khach": [k1]})),
			("P0001", "KHONG_DU_QUYEN: vai này không xem hàng khách đã lấy"))
		self.assertEqual(self._loi(self._rpc("CHU", "hang_khach_da_lay", {"p_nv": "khong-co@nppsale.local"})), ("P0001", "KHONG_TIM_THAY_NV"))
		self.assertEqual(self._loi(self._rpc("CHU", "hang_khach_da_lay", {"p_nv": ""})), ("P0001", "KHONG_TIM_THAY_NV"))
		frappe.db.set_value("NPP Nhan Vien", self.sd.ma["k:NV_BINH"], "dang_hoat_dong", 0, update_modified=False)
		self.assertEqual(self._hang("QL", {"p_nv": self.sd.ma["k:NV_BINH"]})["nv"], self.sd.ma["k:NV_BINH"])  # NV đã khoá vẫn là NV của NPP
		for ai in ("NV_BINH", self._ngoai_npp()):
			self.assertEqual(self._loi(self._rpc(ai, "hang_khach_da_lay", {"p_khach": [k1]})), ("P0001", "KHONG_DU_QUYEN"), ai)
		self._nguoi("Guest")
		try:
			ket = api.rpc(ten="hang_khach_da_lay", tham_so={"p_khach": [k1]})
		finally:
			self._nguoi(None)
		self.assertEqual((ket["error"]["code"], ket["status"]), ("PGRST301", 401))
		for ts in ({"p_khach": k1}, {"p_khach": {"a": 1}}, {"p_tuyen": "GT"}):
			self.assertEqual(self._loi(self._rpc("CHU", "hang_khach_da_lay", ts))[0], "22P02", ts)
		self.assertEqual(self._loi(self._rpc("CHU", "hang_khach_da_lay", {"p_khach": [k1], "p_tu": ""})),
			("22007", 'invalid input syntax for type date: ""'))
		self.assertEqual(self._loi(self._rpc("CHU", "hang_khach_da_lay", {"p_khach": [k1], "p_tu": "2026-02-30"}))[0], "22008")
		mong = self._rpc("CHU", "hang_khach_da_lay", {"p_khach": [k1]})["data"]
		for pt in ("POST", "GET"):
			ma, than = self._rest("CHU", "hang_khach_da_lay", {"p_khach": [k1]}, pt)
			self.assertEqual((ma, json.loads(json.dumps(than["data"]))), (200, json.loads(json.dumps(mong))), pt)
		with patch("nppsale.luat.bao_cao.HET_GIO_NHANH", 0.000001):
			self.assertEqual(self._loi(self._rpc("CHU", "hang_khach_da_lay", {"p_khach": [k1]})), (MA_QUA_HAN, CAU_QUA_HAN))

	def test_loc_tuyen_va_mang_nhu_postgres(self):
		"""`p_khach`: phần tử không phải chuỗi bỏ (không khớp); `[]` → không khách nào (khác NULL). `p_tuyen` so ĐÚNG chuỗi như `= ANY(text[])` của Postgres
		(collation MariaDB không phân biệt hoa thường — 'gt' không khớp 'GT'); mã tuyến của khách trim khoảng trắng; rỗng / chỉ khoảng trắng / NULL →
		'__chua_co_tuyen'; mảng có phần tử nhưng bị bỏ hết (không phải chuỗi) VẪN lọc (cardinality > 0) → không khách nào; mảng rỗng → không lọc."""
		k1, k2, k3 = (self.sd.ma[f"kh:091100000{i}"] for i in (1, 2, 3))

		def khach(ts):
			return [x["id"] for x in self._hang("CHU", ts)["khach"]]

		tat_ca = {"p_khach": [k1, k2, k3]}
		self.assertEqual(khach({"p_khach": [123, None, k1, ["x"]]}), ["0911000001"])
		self.assertEqual(self._hang("CHU", {"p_khach": []}), {"nv": None, "khach": [], "hang": [], "sp": [], "ncc": []})
		self.assertEqual(khach({**tat_ca, "p_tuyen": ["gt"]}), [])
		self.assertEqual(khach({**tat_ca, "p_tuyen": ["GT", "MT"]}), ["0911000002", "0911000001"])  # Sieu thi Ba < Tap hoa Hai
		self.assertEqual(khach({**tat_ca, "p_tuyen": []}), ["0911000003", "0911000002", "0911000001"])
		self.assertEqual(khach({**tat_ca, "p_tuyen": [1]}), [])
		self.assertEqual(khach({**tat_ca, "p_tuyen": ["__chua_co_tuyen"]}), ["0911000003"])
		frappe.db.set_value("Customer", k1, "npp_tuyen", "  GT ", update_modified=False)
		frappe.db.set_value("Customer", k2, "npp_tuyen", "   ", update_modified=False)
		frappe.db.set_value("Customer", k3, "npp_tuyen", None, update_modified=False)
		self.assertEqual(khach({**tat_ca, "p_tuyen": ["GT"]}), ["0911000001"])
		self.assertEqual(khach({**tat_ca, "p_tuyen": ["__chua_co_tuyen"]}), ["0911000003", "0911000002"])
		kq = self._hang("CHU", {"p_khach": [k1, k2]})
		self.assertEqual([x["channel"] for x in kq["khach"]], ["   ", "  GT "])  # kênh trả THÔ (không trim)

	def test_he_so_danh_muc_va_thu_tu_diem_ma(self):
		"""❓Q7: dòng TRẢ quy đổi theo danh mục HIỆN TẠI (dòng trả không chụp hệ số ở nppsale), dòng HĐ theo hệ số CHỤP trên dòng — đổi hệ số thùng của SP1
		24 → 20 thì K3 trả 20 + 2 = 22 (PT-0003 1 thùng + PT-0007 2 lon), đi vẫn 24 (HĐ5 1 thùng chụp 24). ❓Q8: xếp theo ĐIỂM MÃ như C.UTF-8 (hoa trước
		thường, chữ có dấu sau chữ không dấu) — MariaDB `ORDER BY` (unicode_ci) sẽ xếp khác. `nv_chinh` nối ', ' các NV CHÍNH đang làm theo tên."""
		k1, k3 = self.sd.ma["kh:0911000001"], self.sd.ma["kh:0911000003"]
		sp1, thung = self.sd.ma["sp:SP1"], V.uom_site("thung")
		self.assertEqual([(h["k"], h["di"], h["tra"], h["sl"]) for h in self._hang("CHU", {"p_khach": [k3]})["hang"]], [("0911000003", 24, 26, -2)])
		frappe.db.sql("UPDATE `tabUOM Conversion Detail` SET `conversion_factor` = 20 WHERE `parent` = %s AND `parenttype` = 'Item' AND `uom` = %s",
			(sp1, thung))
		self.assertEqual([(h["k"], h["p"], h["di"], h["tra"], h["sl"], h["lan"], h["cuoi"]) for h in self._hang("CHU", {"p_khach": [k3]})["hang"]],
			[("0911000003", "SP1", 24, 22, 2, 1, "2026-11-20")])
		# điểm mã: 'Tap hoa Hai' < 'quan Tu' ('T' 0x54 < 'q' 0x71) — unicode_ci xếp 'quan Tu' trước; 'Ánh' sau mọi chữ ASCII
		frappe.db.set_value("Customer", k3, "customer_name", "quan Tu", update_modified=False)
		self.assertEqual([x["store_name"] for x in self._hang("NV_AN", {})["khach"]], ["Tap hoa Hai", "quan Tu"])
		frappe.db.set_value("Customer", k1, "customer_name", "Ánh Hai", update_modified=False)
		self.assertEqual([x["store_name"] for x in self._hang("NV_AN", {})["khach"]], ["quan Tu", "Ánh Hai"])
		# hai NV chính đang làm → nối theo tên (điểm mã); phân công đã thôi không tính
		frappe.get_doc({"doctype": "NPP Phan Cong Khach", "khach": k1, "nhan_vien": self.sd.ma["k:NV_BINH"], "vai_tro": "primary",
			"trang_thai": "active"}).insert(ignore_permissions=True)
		frappe.db.set_value("NPP Nhan Vien", self.sd.ma["k:NV_BINH"], "ho_ten", "Ánh NV", update_modified=False)
		kq = {x["id"]: x["nv_chinh"] for x in self._hang("CHU", {"p_khach": [k1, k3]})["khach"]}
		self.assertEqual(kq, {"0911000001": "NV An, Ánh NV", "0911000003": "NV An"})  # unicode_ci sẽ xếp 'Ánh NV' trước
		frappe.db.sql("UPDATE `tabNPP Phan Cong Khach` SET `trang_thai` = 'inactive' WHERE `khach` = %s", k3)
		self.assertIsNone(next(x for x in self._hang("CHU", {"p_khach": [k3]})["khach"])["nv_chinh"])
