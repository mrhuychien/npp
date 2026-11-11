"""Sửa / huỷ / xoá đơn qua cổng trên Sales Order, so với CHÍNH trigger + RLS của nppsale (cần bench):

	bench --site poc.local run-tests --module nppsale.tests.test_sua_don

Dữ liệu vàng du_lieu/sua_don_mau.json (tools/vang_sua_don.py): mỗi tình huống là chuỗi lệnh như màn hình nppsale gửi — tạo đơn (RPC), rồi
sửa / thêm / xoá dòng, lưu đầu đơn, đổi trạng thái, cancel_order, xoá đơn — mỗi lệnh một giao dịch dưới đúng người. Bài này gửi cùng
chuỗi lệnh qua cổng (POST ghi bảng / RPC) dưới đúng người và so: từng lệnh cùng thành / bại (cùng mã + câu lỗi, cùng số dòng chạm tới —
RLS từ chối là 0 dòng, không lỗi), trạng thái cuối của đơn (trạng thái, khách, người đứng tên, điều khoản, ngày giao, ghi chú, tiền,
lần sửa, lý do / người huỷ, giảm đơn, lịch sử trạng thái, thông báo huỷ, dòng hàng) hoặc đơn đã bị xoá.

Lệch có chủ đích (blueprint 02 §3.2): ở nppsale subtotal / vat / total là số màn hình GHI vào đầu đơn — dòng đổi mà đầu đơn chưa lưu lại
thì tiền cũ "treo" (và giảm đơn suy ra lệch theo); bản Frappe tính tiền từ dòng. Màn hình luôn lưu đầu đơn ngay sau dòng (applyOrderEdit,
lưu dòng ở chi tiết đơn) nên hai bên trùng khi đầu đơn đã lưu — bài này chỉ so tiền / giảm đơn khi lệnh có tiền cuối cùng (tạo đơn hoặc
lưu đầu đơn có subtotal) đứng sau mọi lệnh đổi dòng thành công. Mốc giảm đơn gốc (bảng giam_don_goc của nppsale — trạng thái nội bộ)
không so: bản Frappe lưu phần giảm nên không cần mốc; hành vi kiểm quyền giảm đơn vẫn so qua từng lệnh.
"""
from __future__ import annotations

import json
import os

import frappe
from frappe.tests import IntegrationTestCase

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.truy_van import doc
from nppsale.tests.test_tao_don import doi_khoa, dung_nen

VANG = os.path.join(os.path.dirname(__file__), "du_lieu", "sua_don_mau.json")
ADMIN = NguCanh(user="Administrator", vai=None, bo_qua_rls=True)


def _so(x):
	return None if x is None else float(x)


class TestSuaDon(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)

	def setUp(self):
		frappe.db.savepoint("npp_test")
		frappe.local._npp_cai_dat_ban = None
		self.ma = dung_nen(self.vang["nen"])
		self.nguoi_cua = {v: k[2:] for k, v in self.ma.items() if k.startswith("u:")}
		self.khach_cua = {self.ma[k]: ten for k, (ten, _n) in self.vang["nen"]["khach"].items()}

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")

	def _lenh(self, b: dict, don: str | None) -> dict:
		ma = dict(self.ma, don=don)
		b = doi_khoa(b, ma)
		frappe.set_user(ma["u:" + b["nguoi"]])
		frappe.local._npp_ngu_canh = None
		try:
			if b["buoc"] == "rpc":
				return api.rpc(ten=b["ten"], tham_so=b["tham_so"])
			yc = {"bang": b["bang"], "hanh_dong": b["hanh_dong"], "select": "id", "count": "exact",
				"loc": [{"op": op, "cot": cot, "gt": gt} for cot, op, gt in b.get("loc") or []]}
			if b["hanh_dong"] != "delete":
				yc["gia_tri"] = b["gia_tri"]
			return api.truy_van(yeu_cau=yc)
		finally:
			frappe.set_user("Administrator")

	def _ct(self, don: str) -> dict:
		if not frappe.db.exists("Sales Order", don):
			return {"con": False}
		r = doc({"bang": "sales_orders", "select": "id, status, sales_user_id, customer_id, payment_terms, expected_delivery, notes, "
			"approval_reason, subtotal, vat, total, edit_no, cancel_reason, cancelled_by, cancelled_at, lines:sales_order_lines(product_id, "
			"unit_name, quantity, unit_price, line_discount, conversion_factor, vat_rate, note)",
			"loc": [{"op": "eq", "cot": "id", "gt": don}]}, ADMIN)["data"][0]
		chenh = float(frappe.db.get_value("Sales Order", don, "npp_giam_gia_don") or 0)
		return {
			"con": True, "status": r["status"], "sales_user": self.nguoi_cua.get(r["sales_user_id"]), "khach": self.khach_cua.get(r["customer_id"]),
			"payment_terms": r["payment_terms"], "expected_delivery": r["expected_delivery"], "notes": r["notes"],
			"approval_reason": r["approval_reason"], "subtotal": _so(r["subtotal"]), "vat": _so(r["vat"]), "total": _so(r["total"]),
			"edit_no": r["edit_no"], "cancel_reason": r["cancel_reason"], "cancelled_by": self.nguoi_cua.get(r["cancelled_by"]),
			"co_cancelled_at": r["cancelled_at"] is not None,
			"giam_don": chenh if chenh > max(1, len(r["lines"])) else 0.0,
			"lich_su": [[a, b] for a, b in frappe.get_all("NPP Nhat Ky Don", filters={"don": don, "loai": "trang_thai"},
				fields=["tu_trang_thai", "den_trang_thai"], order_by="luc asc, creation asc", as_list=True)] or None,
			"thong_bao": frappe.db.count("NPP Thong Bao", {"loai": "order_cancelled", "duong_dan": f"/orders/{don}"}),
			"dong": sorted(({"sp": x["product_id"], "dv": x["unit_name"], "sl": _so(x["quantity"]), "gia": _so(x["unit_price"]),
				"giam": _so(x["line_discount"]), "hs": _so(x["conversion_factor"]), "thue": _so(x["vat_rate"]), "ghi_chu": x["note"]}
				for x in r["lines"]), key=lambda d: (d["sp"], d["dv"])) or None,
		}

	@staticmethod
	def _tien_dong_bo(t: dict) -> bool:
		"""Đầu đơn khớp dòng ở cuối tình huống: sau lệnh đổi dòng thành công cuối cùng có một lệnh tạo / lưu đầu đơn có tiền thành công."""
		dong_bo = False
		for b, k in zip(t["buoc"], t["mong"]["buoc"], strict=False):
			if not k["ok"] or not k.get("so_dong"):
				continue
			if b["buoc"] == "rpc" and b["ten"] == "create_order_with_lines":
				dong_bo = True
			elif b["buoc"] == "ghi" and b["bang"] == "sales_order_lines":
				dong_bo = False
			elif b["buoc"] == "ghi" and b["bang"] == "sales_orders" and "subtotal" in (b.get("gia_tri") or {}):
				dong_bo = True
		return dong_bo

	def _mot(self, t: dict) -> list[str]:
		sai = []
		don = None
		for i, (b, mong) in enumerate(zip(t["buoc"], t["mong"]["buoc"], strict=False)):
			ket = self._lenh(b, don)
			if b["buoc"] == "rpc" and b["ten"] == "create_order_with_lines" and "error" not in ket:
				don = ket["data"][0]["order_id"]
			nhan = f"{t['ma']} bước {i + 1} ({b['buoc']} {b.get('bang') or b.get('ten')} {b.get('hanh_dong', '')} — {b['nguoi']})"
			if mong["ok"]:
				if "error" in ket:
					return [*sai, f"{nhan}: nppsale ghi được — bản Frappe báo {ket['error']['code']} {ket['error']['message'][:150]}"]
				n = 1 if b["buoc"] == "rpc" else (ket.get("count") or 0)
				if n != mong["so_dong"]:
					sai.append(f"{nhan}: chạm {n} dòng, nppsale {mong['so_dong']}")
			else:
				if "error" not in ket:
					return [*sai, f"{nhan}: nppsale báo {mong['ma_loi']} {mong['loi'][:120]} — bản Frappe lại ghi được"]
				if (ket["error"]["code"], ket["error"]["message"]) != (mong["ma_loi"], mong["loi"]):
					sai.append(f"{nhan}: lỗi {ket['error']['code']} {ket['error']['message'][:150]} ≠ nppsale {mong['ma_loi']} {mong['loi'][:150]}")
				break
		ct_mong = t["mong"]["ct"]
		if don is None or ct_mong is None:
			return sai
		ct = self._ct(don)
		if not ct_mong.get("con", True) or not ct["con"]:
			if ct["con"] != ct_mong.get("con", True):
				sai.append(f"{t['ma']}: đơn {'còn' if ct['con'] else 'đã xoá'} — nppsale {'còn' if ct_mong.get('con', True) else 'đã xoá'}")
			return sai
		mong_dong = sorted(({**d, **{k: _so(d[k]) for k in ("sl", "gia", "giam", "hs", "thue")}} for d in ct_mong["dong"] or []),
			key=lambda d: (d["sp"], d["dv"])) or None
		so_tien = ("subtotal", "vat", "total", "giam_don") if self._tien_dong_bo(t) else ()
		for k in ("status", "sales_user", "khach", "payment_terms", "expected_delivery", "notes", "approval_reason", *so_tien,
				"edit_no", "cancel_reason", "cancelled_by", "co_cancelled_at", "lich_su", "thong_bao"):
			v_mong = ct_mong.get(k)
			if k in ("subtotal", "vat", "total", "giam_don"):
				v_mong = _so(v_mong)
			if ct[k] != v_mong:
				sai.append(f"{t['ma']}: {k} = {ct[k]!r}, nppsale {v_mong!r}")
		if ct["dong"] != mong_dong:
			sai.append(f"{t['ma']}: dòng {ct['dong']} ≠ nppsale {mong_dong}")
		return sai

	def test_tung_chuoi_lenh_nhu_nppsale(self):
		sai = []
		for t in self.vang["tinh_huong"]:
			frappe.db.savepoint("npp_th")
			try:
				sai += self._mot(t)
			finally:
				frappe.db.rollback(save_point="npp_th")
				frappe.local._npp_ngu_canh = None
		if sai:
			self.fail(f"{len(sai)} chỗ lệch nppsale:\n" + "\n".join(sai))
