"""Duyệt ảnh + vị trí điểm bán (mig 244): duyet_anh_diem_ban, xin_doi_anh_diem_ban, duyet_yeu_cau_anh_diem_ban,
huy_yeu_cau_anh_diem_ban — tên, tham số, mã lỗi (tiền tố message) và dạng trả về giữ nguyên để màn chi tiết khách / Điểm bán cần
cập nhật chạy không sửa. Cờ phiên `frappe.flags.npp_duyet_anh_diem_ban` thay `npp.duyet_anh_diem_ban` cho khoá ảnh / vị trí cho qua.
"""
from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe.utils import now_datetime

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import co_quyen, hien_tai
from nppsale.luat.quyen import co_quyen as _co_quyen_thuan

from . import rpc

DUONG_ANH = "/storage/v1/object/public/customer-photos/"


def mo_ta_yeu_cau(loai: str, o: int | None) -> str:
	return {
		"photo_add": f"Thêm ảnh {o or ''}", "photo_replace": f"Thay ảnh {o or ''}", "photo_delete": f"Xoá ảnh {o or ''}",
		"pin_set": "Dời vị trí", "pin_clear": "Xoá vị trí",
	}.get(loai, loai)


def nguoi_duyet() -> list[str]:
	"""NV đang hoạt động có quyền customers.approve (chủ NPP luôn có, trừ khi bị cấm riêng)."""
	ra = []
	for nv in frappe.get_all("NPP Nhan Vien", filters={"dang_hoat_dong": 1}, fields=["name", "vai", "nghi_viec_luc"]):
		if nv.nghi_viec_luc:
			continue
		rieng = {r.khoa_quyen: bool(r.duoc_phep) for r in frappe.get_all("NPP Quyen Rieng", filters={"nhan_vien": nv.name},
			fields=["khoa_quyen", "duoc_phep"])}
		vai = {(nv.vai, r.mo_dun, r.hanh_dong): bool(r.duoc_phep) for r in frappe.get_all("NPP Quyen Vai", filters={"vai": nv.vai},
			fields=["mo_dun", "hanh_dong", "duoc_phep"])}
		if _co_quyen_thuan(nv.vai, "customers.approve", rieng, vai):
			ra.append(nv.name)
	return ra


def bao_tin(nguoi: list[str], tieu_de: str, noi_dung: str, duong_dan: str, du_lieu: dict):
	for u in dict.fromkeys(x for x in nguoi if x):
		frappe.get_doc({"doctype": "NPP Thong Bao", "nguoi_nhan": u, "loai": "customer_photo_review", "tieu_de": tieu_de[:500],
			"noi_dung": noi_dung, "duong_dan": duong_dan, "du_lieu": frappe.as_json(du_lieu)}).insert(ignore_permissions=True)


@contextmanager
def _co_duyet():
	cu = getattr(frappe.flags, "npp_duyet_anh_diem_ban", False)
	frappe.flags.npp_duyet_anh_diem_ban = True
	try:
		yield
	finally:
		frappe.flags.npp_duyet_anh_diem_ban = cu


def _khoa_khach(khach: str) -> dict:
	r = frappe.db.sql("SELECT name, customer_name, owner, npp_duyet_anh_luc, npp_vi_do, npp_kinh_do FROM `tabCustomer` "
		"WHERE name = %s FOR UPDATE", (khach,), as_dict=True)
	if not r:
		raise NppLoi("KHACH_KHONG_HOP_LE: Điểm bán không thuộc đơn vị của bạn.")
	return r[0]


def _ten_nv(u: str) -> str:
	return frappe.db.get_value("NPP Nhan Vien", u, "ho_ten") or "Nhân viên"


def bao_anh_dau_cho_duyet(anh):
	"""Ảnh đầu tiên của khách CHƯA duyệt → báo mọi người duyệt trừ người chụp (trg_bao_anh_dau_cho_duyet). Gọi từ after_insert."""
	kh = frappe.db.get_value("Customer", anh.khach, ["customer_name", "npp_duyet_anh_luc"], as_dict=True)
	if not kh or kh.npp_duyet_anh_luc:
		return
	if frappe.db.count("NPP Anh Diem Ban", {"khach": anh.khach}) != 1:
		return
	bao_tin([u for u in nguoi_duyet() if u != frappe.session.user], f"Ảnh điểm bán chờ duyệt: {kh.customer_name}",
		f"{_ten_nv(anh.nguoi_tai)} vừa chụp ảnh điểm bán — mở để duyệt ảnh + vị trí.", f"/customers/{anh.khach}",
		{"customer_id": anh.khach, "kind": "new_photo"})


@rpc("duyet_anh_diem_ban", ghi=True)
def duyet_anh_diem_ban(p_customer_id: str, p_duyet: bool = True):
	nc = hien_tai()
	if not nc.vai or not co_quyen(nc, "customers.approve"):
		raise NppLoi("FORBIDDEN: chỉ chủ NPP (hoặc người được cấp quyền Duyệt khách hàng) được duyệt ảnh điểm bán.", code="42501",
			http=403)
	kh = _khoa_khach(p_customer_id)
	with _co_duyet():
		if p_duyet is None or p_duyet:
			if not kh.npp_vi_do and not frappe.db.exists("NPP Anh Diem Ban", {"khach": p_customer_id}):
				raise NppLoi("CHUA_CO_GI_DE_DUYET: Điểm bán chưa có ảnh hay vị trí để duyệt.")
			frappe.db.set_value("Customer", p_customer_id, {"npp_duyet_anh_luc": now_datetime(), "npp_duyet_anh_boi": nc.user})
			return {"duyet": True, "file_bo": []}
		bo = []
		for r in frappe.get_all("NPP Yeu Cau Anh Diem Ban", filters={"khach": p_customer_id, "trang_thai": "pending"},
				fields=["name", "anh_url"]):
			_dong_yeu_cau(r.name, "cancelled", nc.user, "Bỏ duyệt — nhân viên sửa thẳng được")
			if r.anh_url:
				bo.append(r.anh_url)
		frappe.db.set_value("Customer", p_customer_id, {"npp_duyet_anh_luc": None, "npp_duyet_anh_boi": None})
		return {"duyet": False, "file_bo": bo}


def _dong_yeu_cau(ten: str, trang_thai: str, nguoi: str, ghi_chu: str | None):
	d = frappe.get_doc("NPP Yeu Cau Anh Diem Ban", ten)
	d.trang_thai = trang_thai
	d.nguoi_duyet = nguoi
	d.duyet_luc = now_datetime()
	d.ghi_chu_duyet = ghi_chu
	d.save(ignore_permissions=True)


def _phu_trach(nc, khach: str, kh: dict) -> bool:
	if co_quyen(nc, "customer.view_all") or kh["owner"] == nc.user:
		return True
	if frappe.db.exists("NPP Phan Cong Khach", {"khach": khach, "nhan_vien": nc.user, "trang_thai": "active"}):
		return True
	from nppsale.cong.bang._chung import co_cot

	return bool(co_cot("Sales Order", "npp_nhan_vien") and frappe.db.exists("Sales Order", {"customer": khach, "npp_nhan_vien": nc.user}))


@rpc("xin_doi_anh_diem_ban", ghi=True)
def xin_doi_anh_diem_ban(p_customer_id: str, p_photo_action: str = "none", p_photo_id: str | None = None, p_slot: int | None = None,
		p_photo_url: str | None = None, p_taken_at: str | None = None, p_gps_lat=None, p_gps_lng=None, p_gps_accuracy=None,
		p_pin_action: str = "keep", p_pin_lat=None, p_pin_lng=None):
	from nppsale.cong.bang._chung import gio_vao

	nc = hien_tai()
	if nc.vai not in ("owner", "manager", "sales"):
		raise NppLoi("FORBIDDEN: vai trò của bạn không được sửa ảnh điểm bán.", code="42501", http=403)
	kh = _khoa_khach(p_customer_id)
	if nc.vai == "sales" and not _phu_trach(nc, p_customer_id, kh):
		raise NppLoi("KHONG_PHU_TRACH: Bạn không phụ trách điểm bán này.", code="42501", http=403)
	if not kh["npp_duyet_anh_luc"]:
		raise NppLoi("CHUA_DUYET: Ảnh điểm bán chưa được duyệt — sửa thẳng được, không cần gửi yêu cầu.")
	anh_hd = p_photo_action or "none"
	vt_hd = p_pin_action or "keep"
	if anh_hd not in ("none", "add", "replace", "delete") or vt_hd not in ("keep", "set", "clear"):
		raise NppLoi(f"YEU_CAU_SAI: Thao tác không hợp lệ (ảnh {anh_hd}, vị trí {vt_hd}).")
	if anh_hd == "none" and vt_hd == "keep":
		raise NppLoi("YEU_CAU_RONG: Không có gì để đổi.")
	anh_id, o = None, None
	if anh_hd in ("replace", "delete"):
		r = frappe.db.get_value("NPP Anh Diem Ban", {"name": p_photo_id, "khach": p_customer_id}, ["name", "o_anh"], as_dict=True) if p_photo_id else None
		if not r:
			raise NppLoi("ANH_KHONG_TON_TAI: Ảnh này không còn — tải lại trang.")
		anh_id, o = r.name, r.o_anh
	elif anh_hd == "add":
		o = p_slot
		if o is None or not (1 <= int(o) <= 3):
			raise NppLoi("O_ANH_SAI: Ô ảnh phải từ 1 đến 3.")
		if frappe.db.exists("NPP Anh Diem Ban", {"khach": p_customer_id, "o_anh": o}):
			raise NppLoi(f"O_DA_CO_ANH: Ô ảnh {o} đã có ảnh — dùng Chụp lại.")
	org = frappe.db.get_single_value("NPP Cai Dat", "org_id")
	if anh_hd in ("add", "replace") and (not p_photo_url or not p_taken_at or f"{DUONG_ANH}{org}/{p_customer_id}/" not in p_photo_url):
		raise NppLoi("FILE_SAI: Ảnh mới không nằm trong kho ảnh của điểm bán này.")
	if vt_hd == "set" and (p_pin_lat is None or p_pin_lng is None or not (-90 <= float(p_pin_lat) <= 90) or not (-180 <= float(p_pin_lng) <= 180)):
		raise NppLoi("TOA_DO_SAI: Toạ độ vị trí mới không hợp lệ.")
	bo = []
	for r in frappe.get_all("NPP Yeu Cau Anh Diem Ban", filters={"khach": p_customer_id, "trang_thai": "pending"},
			fields=["name", "loai", "o_anh", "anh_url"]):
		trung_anh = anh_hd != "none" and r.loai.startswith("photo_") and r.o_anh == o
		trung_vt = vt_hd != "keep" and r.loai.startswith("pin_")
		if trung_anh or trung_vt:
			_dong_yeu_cau(r.name, "cancelled", nc.user, "Thay bằng yêu cầu mới")
			if r.anh_url:
				bo.append(r.anh_url)
	ids, mo_ta = [], []
	bay_gio = now_datetime()
	if anh_hd != "none":
		xoa = anh_hd == "delete"
		d = frappe.get_doc({
			"doctype": "NPP Yeu Cau Anh Diem Ban", "khach": p_customer_id, "loai": f"photo_{anh_hd}", "anh": anh_id, "o_anh": o,
			"anh_url": None if xoa else p_photo_url, "chup_luc": None if xoa else gio_vao(p_taken_at),
			"vi_do": 0 if xoa or p_gps_lat is None else p_gps_lat, "kinh_do": 0 if xoa or p_gps_lng is None else p_gps_lng,
			"sai_so": 0 if xoa or p_gps_accuracy is None else p_gps_accuracy, "trang_thai": "pending", "nguoi_xin": nc.user, "xin_luc": bay_gio,
		}).insert(ignore_permissions=True)
		ids.append(d.name)
		mo_ta.append(mo_ta_yeu_cau(f"photo_{anh_hd}", o))
	if vt_hd != "keep":
		d = frappe.get_doc({
			"doctype": "NPP Yeu Cau Anh Diem Ban", "khach": p_customer_id, "loai": f"pin_{vt_hd}",
			"vi_do_ghim": p_pin_lat if vt_hd == "set" else 0, "kinh_do_ghim": p_pin_lng if vt_hd == "set" else 0,
			"trang_thai": "pending", "nguoi_xin": nc.user, "xin_luc": bay_gio,
		}).insert(ignore_permissions=True)
		ids.append(d.name)
		mo_ta.append(mo_ta_yeu_cau(f"pin_{vt_hd}", None))
	bao_tin([u for u in nguoi_duyet() if u != nc.user], f"Yêu cầu duyệt ảnh điểm bán: {kh['customer_name']}",
		f"{_ten_nv(nc.user)} xin: {' · '.join(mo_ta)}", f"/customers/{p_customer_id}",
		{"customer_id": p_customer_id, "request_ids": ids, "kind": "request"})
	return {"ids": ids, "file_bo": bo}


@rpc("duyet_yeu_cau_anh_diem_ban", ghi=True)
def duyet_yeu_cau_anh_diem_ban(p_request_ids: list | None = None, p_dong_y: bool | None = None, p_ghi_chu: str | None = None):
	nc = hien_tai()
	if not nc.vai or not co_quyen(nc, "customers.approve"):
		raise NppLoi("FORBIDDEN: chỉ chủ NPP (hoặc người được cấp quyền Duyệt khách hàng) được duyệt ảnh điểm bán.", code="42501",
			http=403)
	ids = list(dict.fromkeys(p_request_ids or []))
	if p_dong_y is None or not ids:
		raise NppLoi("YEU_CAU_RONG: Chưa chọn yêu cầu nào.")
	ghi = (p_ghi_chu or "").strip() or None
	ds = frappe.db.sql("SELECT * FROM `tabNPP Yeu Cau Anh Diem Ban` WHERE name IN %(i)s ORDER BY xin_luc, name FOR UPDATE",
		{"i": tuple(ids)}, as_dict=True)
	if len(ds) != len(ids):
		raise NppLoi("YEU_CAU_KHONG_TON_TAI: Có yêu cầu không còn — tải lại trang.")
	xong = bo_qua = 0
	bo, khach_duyet = [], []
	with _co_duyet():
		for r in ds:
			if r.trang_thai != "pending":
				raise NppLoi(f'DA_XU_LY: Yêu cầu "{mo_ta_yeu_cau(r.loai, r.o_anh)}" đã được xử lý rồi — tải lại trang.')
			if not p_dong_y:
				_dong_yeu_cau(r.name, "rejected", nc.user, ghi)
				if r.anh_url:
					bo.append(r.anh_url)
				xong += 1
				continue
			loi_thoi = False
			if r.loai == "photo_add":
				if frappe.db.exists("NPP Anh Diem Ban", {"khach": r.khach, "o_anh": r.o_anh}):
					loi_thoi = True
				else:
					frappe.get_doc({"doctype": "NPP Anh Diem Ban", "khach": r.khach, "o_anh": r.o_anh, "anh_url": r.anh_url,
						"chup_luc": r.chup_luc, "vi_do": r.vi_do, "kinh_do": r.kinh_do, "sai_so": r.sai_so,
						"nguoi_tai": r.nguoi_xin}).insert(ignore_permissions=True)
			elif r.loai in ("photo_replace", "photo_delete"):
				goc = frappe.db.get_value("NPP Anh Diem Ban", {"name": r.anh, "khach": r.khach}, ["name", "anh_url"], as_dict=True) if r.anh else None
				if not goc:
					loi_thoi = True
				elif r.loai == "photo_replace":
					a = frappe.get_doc("NPP Anh Diem Ban", goc.name)
					a.update({"anh_url": r.anh_url, "chup_luc": r.chup_luc, "vi_do": r.vi_do, "kinh_do": r.kinh_do, "sai_so": r.sai_so,
						"nguoi_tai": r.nguoi_xin})
					a.save(ignore_permissions=True)
					bo.append(goc.anh_url)
				else:
					frappe.delete_doc("NPP Anh Diem Ban", goc.name, ignore_permissions=True)
					bo.append(goc.anh_url)
			elif r.loai == "pin_set":
				kh = frappe.get_doc("Customer", r.khach)
				kh.npp_vi_do, kh.npp_kinh_do = r.vi_do_ghim, r.kinh_do_ghim
				kh.save(ignore_permissions=True)
			elif r.loai == "pin_clear":
				kh = frappe.get_doc("Customer", r.khach)
				kh.npp_vi_do, kh.npp_kinh_do = 0, 0
				kh.save(ignore_permissions=True)
			if loi_thoi:
				_dong_yeu_cau(r.name, "cancelled", nc.user, "Ảnh gốc đã đổi — yêu cầu không còn áp được")
				if r.anh_url:
					bo.append(r.anh_url)
				bo_qua += 1
			else:
				_dong_yeu_cau(r.name, "approved", nc.user, ghi)
				xong += 1
				if r.khach not in khach_duyet:
					khach_duyet.append(r.khach)
		bay_gio = now_datetime()
		for k in khach_duyet:
			frappe.db.set_value("Customer", k, {"npp_duyet_anh_luc": bay_gio, "npp_duyet_anh_boi": nc.user})
	# Báo người gửi — gộp theo (khách, người gửi), trừ chính người duyệt
	nhom: dict = {}
	for r in frappe.get_all("NPP Yeu Cau Anh Diem Ban", filters={"name": ["in", ids]}, fields=["khach", "nguoi_xin", "loai", "o_anh", "trang_thai"]):
		if not r.nguoi_xin or r.nguoi_xin == nc.user:
			continue
		nhom.setdefault((r.khach, r.nguoi_xin), []).append(r)
	for (k, u), ds_r in nhom.items():
		ds_r.sort(key=lambda x: (x.o_anh is None, x.o_anh or 0, x.loai))
		than = " · ".join(mo_ta_yeu_cau(x.loai, x.o_anh) + (" (không còn áp được)" if x.trang_thai == "cancelled" else "") for x in ds_r)
		if ghi:
			than += f" — {ghi}"
		ten_kh = frappe.db.get_value("Customer", k, "customer_name")
		frappe.get_doc({"doctype": "NPP Thong Bao", "nguoi_nhan": u, "loai": "customer_photo_review",
			"tieu_de": ("Đã duyệt ảnh điểm bán: " if p_dong_y else "Từ chối ảnh điểm bán: ") + (ten_kh or k), "noi_dung": than,
			"duong_dan": f"/customers/{k}", "du_lieu": frappe.as_json({"customer_id": k, "kind": "approved" if p_dong_y else "rejected"}),
		}).insert(ignore_permissions=True)
	return {"xong": xong, "bo_qua": bo_qua, "file_bo": bo}


@rpc("huy_yeu_cau_anh_diem_ban", ghi=True)
def huy_yeu_cau_anh_diem_ban(p_request_id: str):
	nc = hien_tai()
	r = frappe.db.sql("SELECT name, nguoi_xin, trang_thai, anh_url FROM `tabNPP Yeu Cau Anh Diem Ban` WHERE name = %s FOR UPDATE",
		(p_request_id,), as_dict=True)
	if not r:
		raise NppLoi("YEU_CAU_KHONG_TON_TAI: Không tìm thấy yêu cầu này.")
	r = r[0]
	if not nc.vai or (r.nguoi_xin != nc.user and not co_quyen(nc, "customers.approve")):
		raise NppLoi("FORBIDDEN: chỉ người gửi hoặc người duyệt được rút yêu cầu.", code="42501", http=403)
	if r.trang_thai != "pending":
		raise NppLoi("DA_XU_LY: Yêu cầu đã được xử lý rồi — tải lại trang.")
	_dong_yeu_cau(r.name, "cancelled", nc.user, "Người gửi rút yêu cầu" if r.nguoi_xin == nc.user else "Người duyệt bỏ yêu cầu")
	return {"file_bo": [r.anh_url] if r.anh_url else []}
