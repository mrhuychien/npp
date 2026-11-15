"""RPC ban_giao_khach (mig 246) — chủ nhà 15/10/2026: "Gán cho toàn bộ khách hàng của nv A cho nv B (làm chung khách hàng) Hoặc là như
kiểu bàn giao lại khách hàng … dskh tuyến đó, đã lấy hàng gì, số lượng, hàng cty nào mà nv đó làm". Chốt: cả hai kiểu; toàn bộ / theo
tuyến / theo công ty; mốc 3 / 6 / 12 tháng / tất cả; chuyển hẳn → nợ theo NV nhận.

Một hàm, hai lượt: `p_thuc_hien = false` xem trước (danh sách khách + tổng), `true` làm thật (cùng bộ lọc).
- Nguồn: khách của một NV (`nv`) · chưa ai phụ trách (`chua_ai` — không còn phân công của người CÒN LÀM) · mọi khách (`tat_ca`); lọc
  danh sách khách, tuyến (`__chua_co_tuyen` = chưa có tuyến), công ty (NCC chính của mặt hàng đã mua, từ ngày).
- Làm chung: NV nhận thêm vào khách (phụ nếu khách đã có NV chính còn làm, không thì chính); NV đang phụ trách + nợ giữ nguyên.
- Chuyển hẳn (chỉ từ một NV): NV nhận thay đúng vai NV giao, NV giao gỡ khỏi khách (phân công + lịch tuyến); nợ chưa thu xong của NV giao
  sang NV nhận, mang dấu bàn giao (`giao_tu_nv` — tính lại theo chứng từ vẫn giữ NV nhận; chuyển ngược về đúng người gốc thì bỏ dấu).
- Lịch đi tuyến của NV giao chép cho khách MỚI của NV nhận (xếp sau các điểm NV nhận đã có trong ngày).
- NV nhận làm chính → nhận luôn nợ NPP đang giữ của khách (NV cũ nghỉ việc), như giao_cong_no_npp.
- Nhật ký `NPP Ban Giao Khach`; báo NV nhận (và NV giao khi chuyển hẳn).
"""
from __future__ import annotations

import frappe
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from nppsale.cong.loi import NppLoi
from nppsale.cong.ngu_canh import hien_tai
from nppsale.npp_he_thong.doctype.npp_thong_bao.npp_thong_bao import gui_thong_bao
from nppsale.su_kien.cong_no import dat_nguoi_giu

from . import rpc
from .don_hang import _chu

CHUA_CO_TUYEN = "__chua_co_tuyen"


def _ds(v) -> list[str]:
	if v is None:
		return []
	if isinstance(v, str):
		v = frappe.parse_json(v) if v.strip().startswith("[") else [v]
	return [str(x) for x in v if x is not None]


def _nv_dang_lam_sql(bd: str) -> str:
	return f"({bd}.`nghi_viec_luc` IS NULL AND IFNULL({bd}.`dang_hoat_dong`, 1) = 1)"


def _chon_khach(nguon: str, tu_nv, den_nv: str, tuyen: list, ncc: list, tu_ngay, khach: list | None) -> list[dict]:
	"""Khách khớp bộ lọc + vai hiện tại của NV giao / NV nhận + có NV chính còn làm (không tính NV nhận)."""
	dk, ts = [], {"tu": tu_nv or "", "den": den_nv}
	if khach is not None:
		if not khach:
			return []
		dk.append("c.`name` IN %(khach)s")
		ts["khach"] = tuple(khach)
	if tuyen:
		dk.append(f"COALESCE(NULLIF(TRIM(c.`npp_tuyen`), ''), '{CHUA_CO_TUYEN}') IN %(tuyen)s")
		ts["tuyen"] = tuple(tuyen)
	if nguon == "nv":
		dk.append("""EXISTS (SELECT 1 FROM `tabNPP Phan Cong Khach` a WHERE a.`khach` = c.`name` AND a.`nhan_vien` = %(tu)s
			AND a.`trang_thai` = 'active')""")
	elif nguon == "chua_ai":
		dk.append(f"""NOT EXISTS (SELECT 1 FROM `tabNPP Phan Cong Khach` a JOIN `tabNPP Nhan Vien` u ON u.`name` = a.`nhan_vien`
			WHERE a.`khach` = c.`name` AND a.`trang_thai` = 'active' AND {_nv_dang_lam_sql('u')})""")
	if ncc:
		dk.append("""EXISTS (SELECT 1 FROM `tabSales Invoice` i JOIN `tabSales Invoice Item` l ON l.`parent` = i.`name`
			JOIN `tabItem Default` d ON d.`parent` = l.`item_code` AND d.`parenttype` = 'Item'
			WHERE i.`customer` = c.`name` AND i.`docstatus` = 1 AND i.`is_return` = 0 AND IFNULL(i.`is_opening`, 'No') = 'No'
			AND IFNULL(l.`npp_hang_doi`, 0) = 0 AND (%(tu_ngay)s IS NULL OR i.`posting_date` >= %(tu_ngay)s)
			AND d.`default_supplier` IN %(ncc)s)""")
		ts["ncc"] = tuple(ncc)
		ts["tu_ngay"] = str(getdate(tu_ngay)) if tu_ngay else None
	return frappe.db.sql(f"""
		SELECT c.`name` AS id, c.`customer_name` AS store_name, c.`npp_chu_cua_hang` AS owner_name, c.`npp_sdt` AS phone,
			c.`npp_dia_chi` AS address, c.`npp_phuong` AS ward, c.`npp_tuyen` AS channel, c.`npp_trang_thai` AS status,
			(SELECT a.`vai_tro` FROM `tabNPP Phan Cong Khach` a WHERE a.`khach` = c.`name` AND a.`nhan_vien` = %(tu)s
				AND a.`trang_thai` = 'active' LIMIT 1) AS vai_giao,
			(SELECT a.`vai_tro` FROM `tabNPP Phan Cong Khach` a WHERE a.`khach` = c.`name` AND a.`nhan_vien` = %(den)s
				AND a.`trang_thai` = 'active' LIMIT 1) AS vai_nhan,
			EXISTS (SELECT 1 FROM `tabNPP Phan Cong Khach` a JOIN `tabNPP Nhan Vien` u ON u.`name` = a.`nhan_vien`
				WHERE a.`khach` = c.`name` AND a.`trang_thai` = 'active' AND a.`vai_tro` = 'primary' AND a.`nhan_vien` != %(den)s
				AND {_nv_dang_lam_sql('u')}) AS co_chinh
		FROM `tabCustomer` c
		WHERE {' AND '.join(dk) or '1 = 1'}
		ORDER BY c.`customer_name`, c.`name`""", ts, as_dict=True)


def _no(khach: str, dk: str, ts: dict) -> tuple[int, float]:
	r = frappe.db.sql(f"""SELECT COUNT(*), COALESCE(SUM(`so_tien` - IFNULL(`da_thu`, 0)), 0) FROM `tabNPP Cong No`
		WHERE `khach_hang` = %(k)s AND `trang_thai` != 'paid' AND {dk}""", {"k": khach, **ts})[0]
	return cint(r[0]), flt(r[1])


def _so(x: float):
	return int(x) if float(x).is_integer() else x


@rpc("ban_giao_khach", ghi=True)
def ban_giao_khach(p_den_nv=None, p_kieu="chung", p_nguon="nv", p_tu_nv=None, p_tuyen=None, p_ncc=None, p_tu_ngay=None, p_khach=None,
		p_giao_no_npp=True, p_thuc_hien=False):
	nc = hien_tai()
	if nc.vai not in ("owner", "manager"):
		raise NppLoi("KHONG_DU_QUYEN: chỉ Chủ NPP / Quản lý được bàn giao khách")
	kieu, nguon = p_kieu, p_nguon
	if kieu not in ("chung", "chuyen"):
		raise NppLoi("KIEU_KHONG_HOP_LE: chọn Làm chung hoặc Chuyển hẳn")
	if nguon not in ("nv", "chua_ai", "tat_ca"):
		raise NppLoi("NGUON_KHONG_HOP_LE: chọn khách của một NV, khách chưa ai phụ trách hoặc mọi khách")
	tu_nv, den_nv = _chu(p_tu_nv), _chu(p_den_nv)
	if nguon == "nv" and not tu_nv:
		raise NppLoi("CHON_NV_GIAO: chọn nhân viên giao khách")
	if kieu == "chuyen" and nguon != "nv":
		raise NppLoi("CHUYEN_CAN_NV_GIAO: chuyển hẳn chỉ làm được với khách của một nhân viên")
	if nguon == "nv" and tu_nv == den_nv:
		raise NppLoi("CUNG_MOT_NV: nhân viên giao và nhân viên nhận là một người")
	ten_giao = None
	if nguon == "nv":
		ten_giao = frappe.db.get_value("NPP Nhan Vien", tu_nv, "ho_ten")
		if not frappe.db.exists("NPP Nhan Vien", tu_nv):
			raise NppLoi("KHONG_TIM_THAY_NV_GIAO")
	nhan = frappe.db.get_value("NPP Nhan Vien", den_nv, ["ho_ten", "vai", "dang_hoat_dong", "nghi_viec_luc"], as_dict=True) if den_nv else None
	if not nhan or nhan.vai != "sales" or not cint(nhan.dang_hoat_dong if nhan.dang_hoat_dong is not None else 1) or nhan.nghi_viec_luc:
		raise NppLoi("NV_NHAN_KHONG_HOP_LE: người nhận phải là nhân viên bán hàng đang làm")
	tuyen, ncc = _ds(p_tuyen), _ds(p_ncc)
	khach_loc = None if p_khach is None else _ds(p_khach)
	giao_no_npp = True if p_giao_no_npp is None else bool(p_giao_no_npp)
	thuc_hien = bool(p_thuc_hien)
	if thuc_hien:  # hai lượt bàn giao cùng lúc của một NPP đi lần lượt (pg_advisory_xact_lock) — khoá dòng cài đặt tới hết giao dịch
		frappe.db.sql("SELECT `value` FROM `tabSingles` WHERE `doctype` = 'NPP Cai Dat' ORDER BY `field` LIMIT 1 FOR UPDATE")

	ds = _chon_khach(nguon, tu_nv, den_nv, tuyen, ncc, p_tu_ngay, khach_loc)
	rows = []
	for k in ds:
		if kieu == "chuyen":
			se_la = "primary" if "primary" in (k.vai_giao, k.vai_nhan) else "secondary"
		elif k.vai_nhan:
			se_la = k.vai_nhan
		elif cint(k.co_chinh):
			se_la = "secondary"
		else:
			se_la = "primary"
		chinh = frappe.db.sql("""SELECT u.`ho_ten` FROM `tabNPP Phan Cong Khach` a JOIN `tabNPP Nhan Vien` u ON u.`name` = a.`nhan_vien`
			WHERE a.`khach` = %s AND a.`trang_thai` = 'active' AND a.`vai_tro` = 'primary' ORDER BY u.`ho_ten`""", k.id)
		no_chuyen = no_npp = lich = None
		if kieu == "chuyen":
			so, tien = _no(k.id, "`nhan_vien` = %(tu)s", {"tu": tu_nv})
			no_chuyen = {"so": so, "tien": _so(tien)}
		if giao_no_npp and se_la == "primary":
			so, tien = _no(k.id, "`ve_npp_luc` IS NOT NULL", {})
			no_npp = {"so": so, "tien": _so(tien)}
		if nguon == "nv" and not k.vai_nhan:
			lich = [cint(r[0]) for r in frappe.db.sql("""SELECT DISTINCT `thu` FROM `tabNPP Lich Tuyen` WHERE `nhan_vien` = %s
				AND `khach` = %s ORDER BY `thu`""", (tu_nv, k.id))]
		rows.append({"id": k.id, "store_name": k.store_name, "owner_name": k.owner_name, "phone": k.phone, "address": k.address,
			"ward": k.ward, "channel": k.channel, "status": k.status, "vai_giao": k.vai_giao, "vai_nhan": k.vai_nhan, "se_la": se_la,
			"nv_chinh": ", ".join(r[0] for r in chinh) or None, "no_chuyen": no_chuyen, "no_npp": no_npp, "lich": lich})

	ids = [r["id"] for r in rows]
	moi = [r["id"] for r in rows if not r["vai_nhan"]]
	chinh_ids = [r["id"] for r in rows if r["se_la"] == "primary"]
	tong = {
		"so_khach": len(rows), "them_moi": len(moi), "da_co": len(rows) - len(moi),
		"len_chinh": sum(1 for r in rows if r["se_la"] == "primary" and (r["vai_nhan"] or "") != "primary"),
		"no_chuyen": {"so": sum((r["no_chuyen"] or {}).get("so", 0) for r in rows),
			"tien": _so(sum(flt((r["no_chuyen"] or {}).get("tien", 0)) for r in rows))},
		"no_npp": {"so": sum((r["no_npp"] or {}).get("so", 0) for r in rows),
			"tien": _so(sum(flt((r["no_npp"] or {}).get("tien", 0)) for r in rows))},
		"lich": frappe.db.count("NPP Lich Tuyen", {"nhan_vien": tu_nv, "khach": ("in", moi)}) if nguon == "nv" and moi else 0,
		"bo_qua": 0 if khach_loc is None else len(set(khach_loc)) - len(rows),
	}
	if not thuc_hien:
		return {"khach": rows, "tong": tong}
	if not ids:
		raise NppLoi("KHONG_CO_KHACH: không còn khách nào khớp để bàn giao")

	# ---- NV nhận: thêm mới / bật lại phân công đã tắt / nâng vai (chuyển hẳn thay vai chính của NV giao)
	hom_nay = nowdate()
	for r in rows:
		if r["vai_nhan"] and r["vai_nhan"] == r["se_la"]:
			continue
		ten = frappe.db.get_value("NPP Phan Cong Khach", {"khach": r["id"], "nhan_vien": den_nv}, "name")
		if ten:
			pc = frappe.get_doc("NPP Phan Cong Khach", ten)
			if pc.trang_thai != "active":
				pc.ngay_phan_cong = hom_nay
			pc.vai_tro, pc.trang_thai = r["se_la"], "active"
			pc.save(ignore_permissions=True)
		else:
			frappe.get_doc({"doctype": "NPP Phan Cong Khach", "khach": r["id"], "nhan_vien": den_nv, "vai_tro": r["se_la"],
				"trang_thai": "active", "ngay_phan_cong": hom_nay}).insert(ignore_permissions=True)

	# ---- lịch đi tuyến của NV giao → NV nhận, chỉ khách MỚI của NV nhận; xếp sau các điểm NV nhận đã có trong cùng ngày
	lich = 0
	if nguon == "nv" and moi:
		cuoi = {cint(t): cint(m) for t, m in frappe.db.sql("""SELECT `thu`, MAX(`thu_tu_ghe`) FROM `tabNPP Lich Tuyen` WHERE `nhan_vien` = %s
			GROUP BY `thu`""", den_nv)}
		for a in frappe.get_all("NPP Lich Tuyen", filters={"nhan_vien": tu_nv, "khach": ("in", moi)},
				fields=["thu", "khach", "thu_tu_ghe", "dang_dung"], order_by="creation asc"):
			if frappe.db.exists("NPP Lich Tuyen", {"nhan_vien": den_nv, "thu": a.thu, "khach": a.khach}):
				continue
			frappe.get_doc({"doctype": "NPP Lich Tuyen", "nhan_vien": den_nv, "thu": a.thu, "khach": a.khach,
				"thu_tu_ghe": cuoi.get(cint(a.thu), 0) + cint(a.thu_tu_ghe), "dang_dung": a.dang_dung}).insert(ignore_permissions=True)
			lich += 1

	bo, no_so, no_tien, npp_so, npp_tien = 0, 0, 0.0, 0, 0.0
	if kieu == "chuyen":
		for ten in frappe.get_all("NPP Lich Tuyen", filters={"nhan_vien": tu_nv, "khach": ("in", ids)}, pluck="name"):
			frappe.delete_doc("NPP Lich Tuyen", ten, ignore_permissions=True, force=True)
		for ten in frappe.get_all("NPP Phan Cong Khach", filters={"nhan_vien": tu_nv, "khach": ("in", ids)}, pluck="name"):
			frappe.delete_doc("NPP Phan Cong Khach", ten, ignore_permissions=True, force=True)
			bo += 1
		# nợ chưa thu xong của NV giao → NV nhận, dấu bàn giao (chuyển ngược về đúng người gốc thì bỏ dấu)
		for r in frappe.get_all("NPP Cong No", filters={"khach_hang": ("in", ids), "nhan_vien": tu_nv, "trang_thai": ("!=", "paid")},
				fields=["name", "so_tien", "da_thu", "giao_tu_nv"]):
			goc = r.giao_tu_nv or tu_nv
			dat_nguoi_giu(r.name, den_nv, None, None if goc == den_nv else goc)
			no_so += 1
			no_tien += flt(r.so_tien) - flt(r.da_thu)
	# nợ NPP đang giữ (NV cũ nghỉ việc) của khách mà NV nhận làm chính → NV nhận (như giao_cong_no_npp)
	if giao_no_npp and chinh_ids:
		for r in frappe.get_all("NPP Cong No", filters={"khach_hang": ("in", chinh_ids), "ve_npp_luc": ("is", "set"),
				"trang_thai": ("!=", "paid")}, fields=["name", "so_tien", "da_thu"]):
			dat_nguoi_giu(r.name, den_nv, None)
			npp_so += 1
			npp_tien += flt(r.so_tien) - flt(r.da_thu)

	kq = {"so_khach": len(ids), "them_moi": tong["them_moi"], "da_co": tong["da_co"], "len_chinh": tong["len_chinh"],
		"bo_khoi_nv_giao": bo, "lich": lich, "no_chuyen": {"so": no_so, "tien": _so(no_tien)},
		"no_npp": {"so": npp_so, "tien": _so(npp_tien)}, "bo_qua": tong["bo_qua"]}
	nguoi = nc.user if frappe.db.exists("NPP Nhan Vien", nc.user) else None
	log = frappe.get_doc({"doctype": "NPP Ban Giao Khach", "nguon": nguon, "tu_nv": tu_nv if nguon == "nv" else None, "den_nv": den_nv,
		"kieu": kieu, "bo_loc": frappe.as_json({"tuyen": tuyen, "ncc": ncc, "tu_ngay": str(getdate(p_tu_ngay)) if p_tu_ngay else None,
			"giao_no_npp": giao_no_npp}), "khach": frappe.as_json(ids), "ket_qua": frappe.as_json(kq), "tao_boi": nguoi,
		"tao_luc": now_datetime()}).insert(ignore_permissions=True)

	# ---- báo lên điện thoại: NV nhận (mở danh sách hàng khách đã lấy), NV giao khi chuyển hẳn
	nguon_cau = {"nv": "Từ " + (ten_giao or "nhân viên khác") + (" (chuyển hẳn)" if kieu == "chuyen" else " (làm chung)"),
		"chua_ai": "Khách chưa có nhân viên phụ trách"}.get(nguon, "Làm chung với nhân viên đang phụ trách")
	if no_so + npp_so > 0:
		nguon_cau += f" · nhận {no_so + npp_so} khoản nợ"
	gui_thong_bao(den_nv, "info", f"Bạn được giao {len(ids)} khách", nguon_cau, "/customers/hang-da-lay", {"ban_giao_id": log.name})
	if kieu == "chuyen":
		gui_thong_bao(tu_nv, "info", f"{len(ids)} khách của bạn đã chuyển cho {nhan.ho_ten or 'nhân viên khác'}",
			f"Kèm {no_so} khoản nợ chưa thu" if no_so > 0 else None, "/customers", {"ban_giao_id": log.name})
	return {**kq, "log_id": log.name}
