"""Phiếu thu / tiền thu / nợ đầu kỳ (P3d) so với CHÍNH hàm + trigger + RLS của nppsale (cần bench):

	bench --site poc.local run-tests --module nppsale.tests.test_phieu_thu_vang

Dữ liệu vàng du_lieu/phieu_thu_mau.json (tools/vang_phieu_thu.py — đặc tả phiếu thu §6): mỗi tình huống là một chuỗi bước dưới đúng
người (tạo đơn, Xuất hàng, lập / huỷ phiếu thu, nợ đầu kỳ + dấu quá hạn ghi thẳng qua cổng, xác nhận khoản thu, phiếu trả làm nguồn dư
có, Huỷ / Sửa HĐ có tiền thu, nghỉ việc / giao nợ, RPC đọc công nợ). Bài này dựng cùng sổ trên site, phát lại cùng chuỗi qua cổng RPC /
cổng bảng (khung của test_phieu_tra_vang) và so: từng bước (thành / bại, mã + câu lỗi), số trả về, phiếu thu (trạng thái, tiền, ngày, người,
ghi chú, khoá gửi, dòng theo thứ tự), khoản thu (`payments`), mọi dòng công nợ theo KHOÁ NGHIỆP VỤ (HD:<mã HĐ> | DK:<tên khách> |
PT:<mã phiếu trả>), HĐ.

Chuẩn hoá trước khi so (không phải lệch):
- Mã phiếu thu: nppsale `PT-YYMMDD-NNNN` (4 số ngẫu nhiên) ↔ bản Frappe `PTH-YYMMDD-####` (chạy liên tục — Q7 "Mã phiếu thu") → so dạng.
- id trong số trả về: người / khách nền → khoá nền, id khác → có / không; mốc giờ → có / không; ngày → "@hom_nay±n" (cùng luật bộ sinh).
- `bao_cao_cong_no` gộp `jsonb_agg` không ORDER BY → so như tập hợp; khoản thu / dòng công nợ so theo khoá nghiệp vụ.
LECH_THU: tình huống bản Frappe chủ đích khác (00_quyet_dinh_trien_khai.md Q7 — chờ anh chốt) → mong lỗi riêng ở bước ghi trong bảng.
"""
from __future__ import annotations

import json
import os
import re
from decimal import Decimal

import frappe
from frappe.utils import flt

from nppsale.tests import test_phieu_tra_vang as TPV
from nppsale.tests import test_xuat_hang as XH

VANG = os.path.join(os.path.dirname(__file__), "du_lieu", "phieu_thu_mau.json")
CHO_THU = ("@pth:", "@hd:", "@no:", "@dong_thu:", "@khoan:")
KHONG_CO = "00000000-0000-4000-8000-000000000000"  # id không có dòng nào (nppsale: id = NULL / uuid lạ → 0 dòng)

_KHOA_SO_NO = ("BAD_AMOUNT: nợ đầu kỳ phải là số đồng chẵn lớn hơn 0", "Q7: nợ đầu kỳ 0 / âm / số lẻ — nppsale nhận")
# tình huống → (bước lệch (1-based), mã lỗi Frappe, đầu câu lỗi, lý do)
LECH_THU: dict[str, tuple[int, str, str, str]] = {
	"b05_dk_so_0": (1, "P0001", *_KHOA_SO_NO),
	"b05b_dk_so_le": (1, "P0001", *_KHOA_SO_NO),
	"b07_dk_sua_da_thu": (3, "P0001", "CONG_NO_KHOA", "Q2: sửa SỐ nợ đầu kỳ đã thu — nppsale cho (phần chênh thành dư có); huỷ + lập lại tờ DK- "
		"không mang được tiền đã thu (CFD-01)"),
}


def _so_hoa(v):
	"""Số → float (int 30000 của bản Frappe = 30000.0 của jsonb); giữ bool."""
	if isinstance(v, bool) or v is None:
		return v
	if isinstance(v, (int, float, Decimal)):
		return float(v)
	if isinstance(v, dict):
		return {a: _so_hoa(b) for a, b in v.items()}
	if isinstance(v, list):
		return [_so_hoa(x) for x in v]
	return v


def _ngay(v):
	if not isinstance(v, str) or len(v) != 10:
		return v
	try:
		d = frappe.utils.getdate(v)
	except Exception:  # noqa: BLE001 — chuỗi 10 ký tự không phải ngày
		return v
	n = (d - TPV.hom_nay()).days
	return v if abs(n) > 400 else ("@hom_nay" if n == 0 else f"@hom_nay{n:+d}")


def _chuan_gt(v, ten_cua: dict, khoa: str | None = None):
	"""= _chuan của bộ sinh: id người / khách nền → khoá nền, id khác → True; *_at → có / không; ngày → tương đối."""
	if isinstance(v, dict):
		return {a: _chuan_gt(b, ten_cua, a) for a, b in v.items()}
	if isinstance(v, list):
		return [_chuan_gt(x, ten_cua) for x in v]
	if khoa and (khoa == "id" or khoa.endswith("_id")) and isinstance(v, str):
		return ten_cua.get(v, True)
	if khoa and khoa.endswith("_at"):
		return v is not None
	if hasattr(v, "isoformat") and not isinstance(v, str):
		v = v.isoformat()
	return _ngay(v)


class TestPhieuThuVang(TPV.TestPhieuTraVang):
	@classmethod
	def setUpClass(cls):
		super(TPV.TestPhieuTraVang, cls).setUpClass()
		TPV.B.nap()
		with open(VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)

	def setUp(self):
		super().setUp()
		self.co_san["NPP Phieu Thu"] = set(frappe.get_all("NPP Phieu Thu", pluck="name"))
		# quyền vai của bộ sinh (_gieo_quyen_mac_dinh + QUYEN_VAI): site cài trước Q4 chưa có dòng quản lý lập / huỷ phiếu thu
		for vai, mo, hd in self.vang["nen"]["quyen_vai"]:
			ten = frappe.db.get_value("NPP Quyen Vai", {"vai": vai, "mo_dun": mo, "hanh_dong": hd}, "name")
			if ten:
				frappe.db.set_value("NPP Quyen Vai", ten, "duoc_phep", 1)
			else:
				frappe.get_doc({"doctype": "NPP Quyen Vai", "vai": vai, "mo_dun": mo, "hanh_dong": hd, "duoc_phep": 1}).insert(ignore_permissions=True)
		from nppsale.rpc.no_dau_ky import _org

		self.org = _org()
		self.ten_cua = {v: "@" + k for k, v in self.ma.items() if k.startswith("u:") or k in self.vang["nen"]["khach"]}

	# ------------------------------------------------------------------------------------------------ chỗ giữ
	def _dong_no(self, **dk) -> str | None:
		r = frappe.get_all("NPP Cong No", filters=dk, pluck="name", order_by="creation asc", limit=1)
		return r[0] if r else None

	def _thay(self, v, st: dict):
		if isinstance(v, str):
			if v == self.vang["nen"]["org"]:
				return self.org
			if v.startswith(("@pth:", "@hd:")):
				return st["nhan"].get(v.split(":", 1)[1])
			if v == "@no:hd":
				return self._dong_no(loai="hoa_don", hoa_don=st["hd"]) if st["hd"] else None
			if v.startswith("@no:hd:"):
				hd = st["nhan"].get(v[len("@no:hd:"):])
				return self._dong_no(loai="hoa_don", hoa_don=hd) if hd else None
			if v.startswith("@no:dk:"):
				return self._dong_no(loai="dau_ky", khach_hang=self.ma[v[len("@no:dk:"):]])
			if v == "@no:pt":
				return self._dong_no(loai="phieu_tra", phieu_tra=st["pt"]) if st["pt"] else None
		return super()._thay(v, st)

	def _tra_ve_hd(self, r: dict) -> dict:
		"""Số trả về của Xuất hàng / Sửa HĐ — cùng luật chuẩn hoá với bộ sinh (id → có / không, None giữ None)."""
		return _chuan_gt(r, self.ten_cua)

	# ------------------------------------------------------------------------------------------------ một bước
	def _ghi_dem(self, nguoi: str, yc: dict) -> tuple[dict, dict | None]:
		ket = self._ghi(nguoi, yc)
		return ket, None if "error" in ket else {"so_dong": len(ket.get("data") or [])}

	def _loc(self, cot: str, gt, st: dict) -> list[dict]:
		if isinstance(gt, str) and gt.startswith("@dong_thu:"):
			return [{"op": "eq", "cot": "receipt_id", "gt": st["nhan"].get(gt.split(":", 1)[1]) or KHONG_CO}]
		if isinstance(gt, str) and gt.startswith("@khoan:"):
			ph = st["nhan"].get(gt.split(":", 1)[1])
			ds = frappe.get_all("NPP Phieu Thu Dong", filters={"parent": ph, "parenttype": "NPP Phieu Thu"}, pluck="name") if ph else []
			return [{"op": "in", "cot": "id", "gt": ds or [KHONG_CO]}]
		v = self._thay(gt, st)
		return [{"op": "eq", "cot": cot, "gt": KHONG_CO if v is None and cot == "id" else v}]

	def _buoc(self, b: dict, st: dict) -> tuple[dict, dict | None]:
		k = b["buoc"]
		if k == "thu":
			ket = self._goi(b["nguoi"], "create_cash_receipt", {"p": self._thay(b["p"], st)})
			if "error" in ket:
				return ket, None
			ten = ket["data"]
			nhan = next((a for a, v in st["nhan"].items() if v == ten), None) or b.get("nhan") or "moi"
			if b.get("nhan") and b["nhan"] not in st["nhan"]:
				st["nhan"][b["nhan"]] = ten
			return ket, {"phieu": nhan}
		if k == "huy_thu":
			ma = None if b["nhan"] is None else self.vang["nen"]["la"] if b["nhan"] == "LA" else st["nhan"].get(b["nhan"])
			return self._goi(b["nguoi"], "void_cash_receipt", {"p_receipt_id": ma, "p_reason": b["ly_do"]}), None
		if k == "dk":
			return self._ghi_dem(b["nguoi"], {"bang": "receivables", "hanh_dong": "insert", "gia_tri": self._thay(b["g"], st)})
		if k == "ghi_no":
			dong = self._thay(b["no"], st) or KHONG_CO
			yc = {"bang": "receivables", "hanh_dong": b["hd_"], "loc": [{"op": "eq", "cot": "id", "gt": dong}]}
			if b["hd_"] != "delete":
				yc["gia_tri"] = self._thay(b["g"], st)
			return self._ghi_dem(b["nguoi"], yc)
		if k == "ghi_bang":
			yc = {"bang": b["bang"], "hanh_dong": b["hd_"]}
			if b["hd_"] != "delete":
				yc["gia_tri"] = self._thay(b["g"], st)
			if b["hd_"] != "insert":
				yc["loc"] = self._loc(b["cot"], b["gt"], st)
			return self._ghi_dem(b["nguoi"], yc)
		if k == "doc":
			ts = {a: XH.ngay_tuong_doi(v) for a, v in (b.get("ts") or {}).items()}
			ket = self._goi(b["nguoi"], b["ten"], ts)
			if "error" in ket:
				return ket, None
			kq = _chuan_gt(ket["data"], self.ten_cua)
			if b["ten"] == "bao_cao_cong_no" and isinstance(kq, dict):
				kq = {a: sorted(v, key=lambda r: json.dumps(_so_hoa(r), sort_keys=True, ensure_ascii=False)) if isinstance(v, list) else v
					for a, v in kq.items()}
			return ket, {"doc": b["ten"], "kq": kq}
		if k == "nhan_hd":
			st["nhan"][b["ten"]] = st["hd"]
			return {"data": None}, None
		if k == "chon_hd":
			st["hd"] = st["nhan"].get(b["ten"])
			return {"data": None}, None
		if k == "giao_no":
			ket = self._goi(b["nguoi"], "giao_cong_no_npp", {"p_customer_id": self.ma[b["khach"][1:]], "p_user_id": self.ma["u:" + b["nv"]]})
			return ket, None if "error" in ket else {"giao_no": ket["data"]}
		if k == "nghi":
			ket = self._goi(b["nguoi"], "cho_nhan_vien_nghi", {"p_user_id": self.ma["u:" + b["nv"]]})
			return ket, None if "error" in ket else {"nghi": ket["data"]}
		if k == "quyen_vai":
			ten = frappe.db.get_value("NPP Quyen Vai", {"vai": b["vai"], "mo_dun": b["mo_dun"], "hanh_dong": b["hanh_dong"]}, "name")
			if ten:
				frappe.db.set_value("NPP Quyen Vai", ten, "duoc_phep", 1 if b["duoc"] else 0)
			else:
				frappe.get_doc({"doctype": "NPP Quyen Vai", "vai": b["vai"], "mo_dun": b["mo_dun"], "hanh_dong": b["hanh_dong"],
					"duoc_phep": 1 if b["duoc"] else 0}).insert(ignore_permissions=True)
			return {"data": None}, None
		return super()._buoc(b, st)

	# ------------------------------------------------------------------------------------------------ ảnh chụp (cùng dạng _vang_anh_chup_thu)
	def _khoa_no(self, ten: str | None) -> str | None:
		r = frappe.db.get_value("NPP Cong No", ten, ["loai", "hoa_don", "khach_hang", "phieu_tra"], as_dict=True) if ten else None
		if not r:
			return None
		if r.loai == "hoa_don":
			return "HD:" + r.hoa_don
		if r.loai == "dau_ky":
			return "DK:" + (frappe.db.get_value("Customer", r.khach_hang, "customer_name") or "")
		if r.loai == "phieu_tra":
			return "PT:" + r.phieu_tra
		return "KHAC"

	def _ct_thu(self, tra_ve: list, st: dict) -> dict:
		ng = self.nguoi_cua.get
		hom = TPV.hom_nay().strftime("%y%m%d")
		phieu = []
		for r in frappe.get_all("NPP Phieu Thu", filters=self._moi("NPP Phieu Thu"), fields=["name", "ngay_thu", "nguon", "trang_thai",
				"tien_thu", "nguoi_thu", "nhan_boi", "nhan_luc", "owner", "huy_boi", "huy_luc", "ly_do_huy", "ghi_chu", "client_key"],
				order_by="creation asc, name asc"):
			dong = frappe.get_all("NPP Phieu Thu Dong", filters={"parent": r.name, "parenttype": "NPP Phieu Thu"}, fields=["loai", "so_tien",
				"cong_no", "hoa_don", "don_hang", "phieu_tra"], order_by="idx asc")
			phieu.append({"ma_dang": "PT-NGAY-SO" if re.fullmatch(r"PTH-\d{6}-\d{4}", r.name) else r.name, "ngay_ma": r.name[4:10] == hom,
				"ngay": TPV.ngay_tuong_doi(r.ngay_thu), "nguon": r.nguon, "status": r.trang_thai, "tien": flt(r.tien_thu), "ky_vong": flt(r.tien_thu),
				"thu_boi": ng(r.nguoi_thu), "nhan_boi": ng(r.nhan_boi), "co_nhan_luc": r.nhan_luc is not None, "lap_boi": ng(r.owner),
				"huy_boi": ng(r.huy_boi), "co_huy_luc": r.huy_luc is not None, "ly_do_huy": r.ly_do_huy, "ghi_chu": r.ghi_chu,
				"khoa_gui": r.client_key or None,
				"dong": [{"loai": d.loai, "tien": flt(d.so_tien), "no": self._khoa_no(d.cong_no), "hd": d.hoa_don or None,
					"co_don": bool(d.don_hang), "pt": d.phieu_tra or None, "co_khoan": r.trang_thai != "voided", "co_no": bool(d.cong_no)}
					for d in dong] or None})
		khoan = []
		for d in frappe.db.sql("""SELECT d.`parent`, d.`cong_no`, d.`so_tien`, d.`loai`, d.`xac_nhan_boi`, p.`hinh_thuc`, p.`nguoi_thu`
				FROM `tabNPP Phieu Thu Dong` d JOIN `tabNPP Phieu Thu` p ON p.`name` = d.`parent` WHERE d.`parenttype` = 'NPP Phieu Thu'
				AND p.`trang_thai` <> 'voided' AND d.`cong_no` IS NOT NULL""", as_dict=True):  # cột uuid: IFNULL(…, '') ra NULL
			if d.parent in self.co_san["NPP Phieu Thu"] or not frappe.db.exists("NPP Cong No", d.cong_no):
				continue  # payments JOIN receivables của nppsale: khoản trỏ dòng không còn thì không ra
			khoan.append({"no": self._khoa_no(d.cong_no), "tien": flt(d.so_tien), "cach": d.hinh_thuc if d.loai == "payment" else d.loai,
				"thu_boi": ng(d.nguoi_thu), "xac_nhan": bool(d.xac_nhan_boi)})
		no = []
		for c in frappe.get_all("NPP Cong No", filters=self._moi("NPP Cong No"), fields=["name", "so_tien", "da_thu", "trang_thai",
				"han_thanh_toan", "nhan_vien", "ve_npp_luc", "giao_tu_nv", "ghi_chu"]):
			no.append({"no": self._khoa_no(c.name), "so_tien": flt(c.so_tien), "da_thu": flt(c.da_thu), "status": c.trang_thai,
				"han": TPV.ngay_tuong_doi(c.han_thanh_toan), "nv": ng(c.nhan_vien), "ve_npp": c.ve_npp_luc is not None,
				"giao_tu": ng(c.giao_tu_nv), "ghi_chu": c.ghi_chu or None})
		hd = [{"ma": h.name, "status": {1: "posted", 2: "cancelled"}[h.docstatus], "total": flt(h.grand_total),
			"han": TPV.ngay_tuong_doi(h.npp_han_thanh_toan or h.due_date)}
			for h in sorted(frappe.get_all("Sales Invoice", filters={"is_return": 0, "docstatus": ("in", (1, 2)), "is_opening": ("!=", "Yes"),
				**self._moi("Sales Invoice")}, fields=["name", "docstatus", "grand_total", "npp_han_thanh_toan", "due_date"]),
				key=lambda x: (int(x.name.split("-")[1]), int(x.name.split("-")[2]) if x.name.count("-") > 1 else 0))]
		return {"tra_ve": _so_hoa(tra_ve), "phieu_thu": _so_hoa(phieu) or None, "khoan": self._xep(_so_hoa(khoan)) or None,
			"cong_no": self._xep(_so_hoa(no)) or None, "hd": _so_hoa(hd) or None, "nhan": sorted(st["nhan"])}

	@staticmethod
	def _xep(ds: list) -> list:
		return sorted(ds, key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False))

	def _mong_thu(self, ct: dict) -> dict:
		ct = json.loads(json.dumps(ct or {}))
		for p in ct.get("phieu_thu") or []:
			for k in ("ly_do_huy", "ghi_chu"):
				p[k] = p.get(k)
		return {"tra_ve": _so_hoa(ct.get("tra_ve") or []), "phieu_thu": _so_hoa(ct.get("phieu_thu")) or None,
			"khoan": self._xep(_so_hoa(ct.get("khoan") or [])) or None, "cong_no": self._xep(_so_hoa(ct.get("cong_no") or [])) or None,
			"hd": _so_hoa(ct.get("hd")) or None, "nhan": ct.get("nhan") or []}

	# ------------------------------------------------------------------------------------------------ một tình huống
	def _mot(self, t: dict) -> list[str]:
		mong = t["mong"]
		sai = []
		st = {"don": None, "hd": None, "pt": None, "nhan": {}}
		tra_ve = []
		lech = LECH_THU.get(t["ma"])
		for i, (b, m) in enumerate(zip(t["buoc"], mong["buoc"], strict=False)):
			nhan = f"{t['ma']} bước {i + 1} ({b['buoc']} — {b['nguoi']})"
			ket, tv = self._buoc(b, st)
			if lech and lech[0] == i + 1:
				if "error" not in ket or (ket["error"]["code"], ket["error"]["message"][:len(lech[2])]) != (lech[1], lech[2]):
					sai.append(f"{nhan}: lệch có chủ đích ({lech[3]}) mong {lech[1]} {lech[2]} — bản Frappe ra {ket.get('error') or 'thành công'}")
				return sai
			if m["ok"]:
				if "error" in ket:
					return [*sai, f"{nhan}: nppsale ghi được — bản Frappe báo {ket['error']['code']} {ket['error']['message'][:300]}"]
				if tv is not None:
					tra_ve.append(tv)
			else:
				if "error" not in ket:
					return [*sai, f"{nhan}: nppsale báo {m['ma_loi']} {m['loi'][:200]} — bản Frappe lại ghi được"]
				if (ket["error"]["code"], ket["error"]["message"]) != (m["ma_loi"], m["loi"]):
					sai.append(f"{nhan}: lỗi {ket['error']['code']} {ket['error']['message'][:300]} ≠ nppsale {m['ma_loi']} {m['loi'][:300]}")
				break
		ct = self._ct_thu(tra_ve, st)
		ct_mong = self._mong_thu(mong["ct"])
		for k in ("tra_ve", "phieu_thu", "khoan", "cong_no", "hd", "nhan"):
			if ct[k] != ct_mong.get(k):
				sai.append(f"{t['ma']}: {k} lệch ở {'; '.join(XH._cho_lech(ct[k], ct_mong.get(k)))[:2500]}")
		# bất biến sổ của bản ERPNext — khám công nợ phải sạch ở MỌI trạng thái cuối
		from nppsale.kham_so import quet_cong_no

		kh = [self.ma[k] for k in self.vang["nen"]["khach"]]
		for d in quet_cong_no(kh):
			sai.append(f"{t['ma']}: khám sổ nhóm {d.get('nhom')} {d.get('loai')} — {d.get('chung_tu')}: {d.get('chi_tiet')}")
		return sai
