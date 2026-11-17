"""Công nợ phải thu = bản chiếu thuần từ sổ (blueprint 02 §4.3.0, quyết định Q2).

`NPP Cong No` không có trường nào người dùng ghi: số tiền lấy từ Payment Ledger Entry của lõi, trạng thái nghiệp vụ (NV giữ nợ, dấu bàn
giao, mốc về NPP, hạn, dấu quá hạn, ghi chú) nằm ở trường `allow_on_submit` của chứng từ nguồn. Hàm chiếu tính lại được bất cứ lúc nào.

Dòng của HĐ / tờ nợ đầu kỳ: nhóm = {HĐ} ∪ {tờ ghi có độc lập gắn HĐ (`npp_hoa_don_goc`), đã ghi sổ}.
  so_tien = grand_total HĐ + Σ grand_total (âm) của tờ ghi có gắn — = total − credits của `_wf2b_recompute_receivable`
  con_no  = Σ Payment Ledger Entry.amount (delinked = 0) có against_voucher thuộc nhóm — âm = dư có
  da_thu  = so_tien − con_no;  trang_thai — một luật (`_cong_no_am_trang_thai`, mig 212)
Dòng phiếu trả tự lập độc lập: nhóm = các tờ ghi có của phiếu. Dòng tiền thừa của phiếu thu (phương án A, Q1 đặc tả phiếu thu): nhóm = Payment
Entry của phiếu (phần chưa phân bổ + bút toán cấn trừ trỏ vào nó).
Chứng từ nguồn không còn ghi sổ → xoá dòng; riêng dòng phiếu trả / tiền thừa còn dòng phiếu thu CHƯA huỷ trỏ tới thì giữ (số 0) — đặc tả §3.4-4.
"""
from __future__ import annotations

import frappe
from frappe.utils import flt, now_datetime

DT = "NPP Cong No"


def trang_thai(so_tien: float, da_thu: float, qua_han_tay: bool) -> str:
	"""_cong_no_am_trang_thai (mig 212): nợ âm (dư có) chỉ 'paid' khi dùng hết; trả dư là 'open' (dư có, trừ vào tổng nợ)."""
	if so_tien < 0:
		return "paid" if abs(da_thu - so_tien) < 0.01 else "open"
	if abs(da_thu - so_tien) < 0.01:
		return "paid"
	if da_thu > so_tien:
		return "open"
	if qua_han_tay:
		return "overdue"
	if da_thu > 0:
		return "partial"
	return "open"


def _con_no(nhom: list[str], loai: str = "Sales Invoice") -> float:
	if not nhom:
		return 0.0
	return flt(frappe.db.sql("""SELECT COALESCE(SUM(`amount`), 0) FROM `tabPayment Ledger Entry`
		WHERE `against_voucher_type` = %(l)s AND `against_voucher_no` IN %(n)s AND `delinked` = 0""", {"n": tuple(nhom), "l": loai})[0][0])


def ghi_co_gan(hd: str) -> list[str]:
	"""Tờ ghi có độc lập đang ghi sổ gắn HĐ (nhóm của dòng HĐ)."""
	if not frappe.db.has_column("Sales Invoice", "npp_hoa_don_goc"):
		return []
	return frappe.get_all("Sales Invoice", filters={"is_return": 1, "npp_hoa_don_goc": hd, "docstatus": 1}, pluck="name",
		order_by="posting_date asc, name asc")


def nhom_cua_dong(r) -> tuple[str, list[str]]:
	"""(loại chứng từ against_voucher, các chứng từ) của một dòng NPP Cong No — nhóm mà `con_no` cộng PLE."""
	if r.get("loai") == "tien_thua":
		pe = frappe.db.get_value("NPP Phieu Thu", r.get("phieu_thu"), "but_toan_tien") if r.get("phieu_thu") else None
		return "Payment Entry", [pe] if pe and frappe.db.get_value("Payment Entry", pe, "docstatus") == 1 else []
	if r.get("loai") == "phieu_tra":
		# mọi tờ ghi có của phiếu, kể cả đã huỷ: Payment Ledger của tờ huỷ đã delinked, nhưng bút toán cấn trừ lập lại có thể trỏ tờ huỷ (phiếu độc
		# lập bị huỷ khi dư có đã bị rút — Q3) và vẫn phải cộng vào dòng của phiếu (như chieu_phieu_tra)
		return "Sales Invoice", frappe.get_all("Sales Invoice", filters={"npp_phieu_tra": r.get("phieu_tra"), "is_return": 1,
			"docstatus": ("in", (1, 2))}, pluck="name", order_by="posting_date asc, name asc") if r.get("phieu_tra") else []
	hd = r.get("hoa_don")
	return "Sales Invoice", ([hd, *ghi_co_gan(hd)] if hd else [])


def con_no_dong(r) -> float:
	"""Số còn nợ của một dòng đọc thẳng từ sổ (không tin cột chiếu) — dùng sau khi đã khoá dòng."""
	loai, nhom = nhom_cua_dong(r)
	return _con_no(nhom, loai)


def chung_tu_am(r) -> list[tuple[str, str, float]]:
	"""Các chứng từ trong nhóm của dòng có số còn nợ (Σ PLE theo against_voucher) ÂM — nguồn để rút dư có: [(loại, tên, −còn nợ)],
	theo ngày ghi sổ rồi tên (đặc tả phiếu thu §2.1.5 bước 3)."""
	loai, nhom = nhom_cua_dong(r)
	if not nhom:
		return []
	am = {x[0]: -flt(x[1]) for x in frappe.db.sql("""SELECT `against_voucher_no`, SUM(`amount`) FROM `tabPayment Ledger Entry`
		WHERE `against_voucher_type` = %(l)s AND `against_voucher_no` IN %(n)s AND `delinked` = 0 GROUP BY `against_voucher_no`
		HAVING SUM(`amount`) < -0.005""", {"l": loai, "n": tuple(nhom)})}
	return [(loai, ten, am[ten]) for ten in nhom if ten in am]


def khoa_khach(kh: str) -> list:
	"""Khoá chung của mọi method đổi nợ một khách (đặc tả phiếu thu §2.0.4, Q15): dòng Customer rồi mọi dòng NPP Cong No của khách theo
	`name` — trước mọi câu đọc thường của thân method. Trả các dòng đã khoá."""
	frappe.db.sql("SELECT `name` FROM `tabCustomer` WHERE `name` = %s FOR UPDATE", kh)
	return frappe.db.sql(f"""SELECT `name`, `loai`, `hoa_don`, `phieu_tra`, `phieu_thu`, `don_hang`, `han_thanh_toan`, `so_tien`, `da_thu`,
		`con_no`, `trang_thai` FROM `tab{DT}` WHERE `khach_hang` = %s ORDER BY `name` FOR UPDATE""", kh, as_dict=True)


def _con_tham_chieu(dong: str | None) -> bool:
	"""Còn dòng phiếu thu CHƯA huỷ trỏ dòng công nợ (Q16 — `payments` của cổng đọc qua dòng công nợ)."""
	if not dong or not frappe.db.exists("DocType", "NPP Phieu Thu Dong"):
		return False
	return bool(frappe.db.sql("""SELECT 1 FROM `tabNPP Phieu Thu Dong` d JOIN `tabNPP Phieu Thu` p ON p.`name` = d.`parent`
		WHERE d.`parenttype` = 'NPP Phieu Thu' AND d.`cong_no` = %s AND p.`trang_thai` != 'voided' LIMIT 1""", dong))


def _ghi(khoa: str, gia_tri: dict) -> str:
	ten = frappe.db.get_value(DT, {"khoa_nguon": khoa}, "name")
	if ten:
		doc = frappe.get_doc(DT, ten)
		doc.update(gia_tri)
		doc.flags.ignore_permissions = True
		doc.save()
		return doc.name
	doc = frappe.get_doc({"doctype": DT, "khoa_nguon": khoa, **gia_tri})
	doc.insert(ignore_permissions=True)
	return doc.name


def _tao_luc_goc(ten: str, creation):
	"""Ngày lập của tờ GỐC trong chuỗi amend (nợ đầu kỳ sửa số = huỷ + `DK-…-n`; nppsale sửa tại chỗ — `created_at` không đổi)."""
	goc, da = frappe.db.get_value("Sales Invoice", ten, "amended_from"), {ten}
	while goc and goc not in da:
		da.add(goc)
		x = frappe.db.get_value("Sales Invoice", goc, ["creation", "amended_from"], as_dict=True)
		if not x:
			break
		creation, goc = x.creation, x.amended_from
	return creation


def chieu_hoa_don(ten: str) -> str | None:
	"""Chiếu dòng công nợ của một HĐ bán / tờ nợ đầu kỳ (không phải tờ ghi có). Trả tên dòng (receivable_id) hoặc None."""
	si = frappe.db.get_value("Sales Invoice", ten, ["name", "docstatus", "is_return", "customer", "customer_name", "grand_total", "creation", "due_date",
		"npp_don_hang", "npp_nv_giu_no", "npp_giao_tu_nv", "npp_ve_npp_luc", "npp_han_thanh_toan", "npp_qua_han_tay", "npp_ghi_chu"],
		as_dict=True)
	if not si or si.is_return:
		return None
	khoa = f"Sales Invoice:{ten}"
	if si.docstatus != 1:
		frappe.db.delete(DT, {"khoa_nguon": khoa})  # xoá thẳng — dòng phiếu thu đã huỷ có thể còn trỏ tới (blueprint §4.3)
		return None
	ghi_co = frappe.get_all("Sales Invoice", filters={"is_return": 1, "npp_hoa_don_goc": ten, "docstatus": 1},
		fields=["name", "grand_total"]) if frappe.db.has_column("Sales Invoice", "npp_hoa_don_goc") else []
	so_tien = flt(si.grand_total) + sum(flt(x.grand_total) for x in ghi_co)
	con_no = _con_no([ten, *(x.name for x in ghi_co)])
	da_thu = so_tien - con_no
	dau_ky = ten.startswith("DK-")
	return _ghi(khoa, {
		"loai": "dau_ky" if dau_ky else "hoa_don", "khach_hang": si.customer, "ten_khach": si.customer_name, "hoa_don": ten,
		"don_hang": si.npp_don_hang,
		"nhan_vien": si.npp_nv_giu_no, "giao_tu_nv": si.npp_giao_tu_nv, "ve_npp_luc": si.npp_ve_npp_luc,
		# nợ đầu kỳ: hạn người nhập (được trống — nppsale không đặt hạn); HĐ: hạn theo điều khoản
		"so_tien": so_tien, "da_thu": da_thu, "con_no": con_no,
		"han_thanh_toan": si.npp_han_thanh_toan if dau_ky else (si.npp_han_thanh_toan or si.due_date),
		"trang_thai": trang_thai(so_tien, da_thu, bool(si.npp_qua_han_tay)), "qua_han_tay": 1 if si.npp_qua_han_tay else 0,
		"ghi_chu": si.npp_ghi_chu if dau_ky else None, "tao_luc": _tao_luc_goc(ten, si.creation) if dau_ky else si.creation,
		"tinh_luc": now_datetime(), "khoa_cho": f"dau_ky:{si.customer}" if dau_ky else None,
	})


# Trường người giữ nợ trên chứng từ nguồn của từng loại dòng (blueprint 02 §5.6): (người giữ, mốc về NPP, dấu bàn giao). Dòng âm của phiếu
# trả tự lập (`NPP Phieu Tra:<PT>`) giữ ba trường ấy trên tờ ghi có ĐANG HIỆU LỰC của phiếu (`to_ghi_co`) — bàn giao / nghỉ việc / giao nợ
# ghi lên tờ rồi chiếu lại dòng.
TRUONG_GIU = {"Sales Invoice": ("npp_nv_giu_no", "npp_ve_npp_luc", "npp_giao_tu_nv"),
	"NPP Phieu Thu": ("nv_giu_tien_thua", "ve_npp_luc", "giao_tu_nv"),
	"NPP Phieu Tra": ("npp_nv_giu_no", "npp_ve_npp_luc", "npp_giao_tu_nv")}


_GIU_DAU = object()


def dat_nguoi_giu(dong: str, nv: str | None, ve_npp_luc, giao=_GIU_DAU) -> None:
	"""Chế độ GIAO NỢ (`npp.giao_cong_no` — RPC nghỉ việc / giao nợ / bàn giao): đặt thẳng người giữ của MỘT dòng công nợ trên chứng từ
	nguồn; có người giữ thì bỏ mốc về NPP (`_cong_no_giu_ve_npp`); dấu bàn giao giữ nguyên trừ khi truyền `giao`. Rồi chiếu lại dòng."""
	khoa = frappe.db.get_value(DT, dong, "khoa_nguon")
	dt, _, ten = (khoa or "").partition(":")
	truong = TRUONG_GIU.get(dt)
	if dt == "NPP Phieu Tra" and ten:
		dt, ten = "Sales Invoice", frappe.db.get_value("NPP Phieu Tra", ten, "to_ghi_co")
	if not truong or not ten:
		frappe.throw(f"Không rõ chứng từ nguồn của dòng công nợ {dong} ({khoa})")
	gt = {truong[0]: nv, truong[1]: None if nv else ve_npp_luc}
	if giao is not _GIU_DAU:
		gt[truong[2]] = giao
	frappe.db.set_value(dt, ten, gt, update_modified=False)
	if dt == "Sales Invoice":
		chieu_nguon_cua(frappe.db.get_value("Sales Invoice", ten, ["name", "is_return", "npp_hoa_don_goc", "npp_phieu_tra"], as_dict=True))
	elif dt == "NPP Phieu Thu":
		chieu_tien_thua(ten)


def chieu_phieu_tra(pt: str) -> str | None:
	"""Dòng công nợ ÂM (dư có) của phiếu trả TỰ LẬP độc lập — không HĐ, không đơn (`_cong_no_phieu_tra`, mig 191; blueprint §3.5.5):
	một phiếu một dòng, khoá `NPP Phieu Tra:<PT>` (giữ qua mỗi lần lập lại tờ ghi có). Có khi phiếu Hoàn thành và tờ ghi có đang ghi sổ;
	mất điều kiện → xoá dòng (bản chiếu thuần — nppsale để lại dòng amount 0, ⚠ Q6 của đặc tả). Hạn = ngày phiếu chụp lúc Hoàn thành
	(`npp_han_thanh_toan` của tờ) — đổi ngày phiếu sau đó không dời hạn (ĐT-PT G32 / Q10)."""
	khoa = f"NPP Phieu Tra:{pt}"
	r = frappe.db.get_value("NPP Phieu Tra", pt, ["name", "trang_thai", "tu_sinh", "to_ghi_co", "hoa_don", "don_hang"], as_dict=True) \
		if frappe.db.exists("DocType", "NPP Phieu Tra") else None
	to = None
	if r and not r.tu_sinh and r.trang_thai == "completed" and not r.hoa_don and not r.don_hang and r.to_ghi_co:
		to = frappe.db.get_value("Sales Invoice", r.to_ghi_co, ["name", "docstatus", "customer", "customer_name", "grand_total", "posting_date",
			"creation", "npp_nv_giu_no", "npp_giao_tu_nv", "npp_ve_npp_luc", "npp_han_thanh_toan"], as_dict=True)
	nhom = frappe.get_all("Sales Invoice", filters={"npp_phieu_tra": pt, "is_return": 1}, pluck="name")
	if not to or to.docstatus != 1:
		dong = frappe.db.get_value(DT, {"khoa_nguon": khoa}, "name")
		if not _con_tham_chieu(dong):
			frappe.db.delete(DT, {"khoa_nguon": khoa})
			return None
		# còn phiếu thu sống đã rút dư có của phiếu: giữ dòng với số 0 (= `_cong_no_phieu_tra` đặt amount 0) — nợ "tự tăng lại" ở đây
		con_no = _con_no(nhom)
		frappe.db.set_value(DT, dong, {"so_tien": 0, "da_thu": -con_no, "con_no": con_no, "trang_thai": trang_thai(0, -con_no, False),
			"tinh_luc": now_datetime()}, update_modified=False)
		return dong
	so_tien = flt(to.grand_total)
	con_no = _con_no(nhom)
	da_thu = so_tien - con_no
	return _ghi(khoa, {
		"loai": "phieu_tra", "khach_hang": to.customer, "ten_khach": to.customer_name, "hoa_don": None, "phieu_tra": pt, "don_hang": None,
		"nhan_vien": to.npp_nv_giu_no, "giao_tu_nv": to.npp_giao_tu_nv, "ve_npp_luc": to.npp_ve_npp_luc,
		# hạn = ngày phiếu lúc Hoàn thành (`_cong_no_phieu_tra` mig 191: COALESCE(return_date, ngày hoàn thành)) — chụp trên tờ lúc lập
		# (`luat.phieu_tra.han_no_am`); tờ lập trước bản sửa 🔧 P3-HAN-NO-AM không có số chụp → ngày ghi sổ tờ (= ngày bấm, như cũ)
		"so_tien": so_tien, "da_thu": da_thu, "con_no": con_no, "han_thanh_toan": to.npp_han_thanh_toan or to.posting_date,
		"trang_thai": trang_thai(so_tien, da_thu, False), "qua_han_tay": 0, "ghi_chu": "Dư có từ phiếu trả hàng", "tao_luc": to.creation,
		"tinh_luc": now_datetime(),
	})


def chieu_tien_thua(pt: str | None) -> str | None:
	"""Dòng TIỀN THỪA CHƯA PHÂN BỔ của một phiếu thu (CFD-04): phần chưa phân bổ của Payment Entry cùng tên cộng bút toán cấn trừ đã rút
	nó. Khoá `NPP Phieu Thu:<phiếu>`. Có dòng khi còn số ≠ 0 hoặc còn dòng phiếu thu chưa huỷ trỏ tới. Lưới an toàn: các RPC luôn phân bổ
	hết tiền phiếu (Sửa HĐ giảm tiền chuyển phần thu vượt vào chính HĐ mới — phương án B của Q1, `can_tru.chuyen_tien_thu`) nên dòng chỉ
	hiện khi sổ có Payment Entry treo tiền ngoài app — Σ nợ của khách vẫn khớp sổ cái, khám sổ nhóm 13 báo."""
	if not pt or not frappe.db.exists("DocType", "NPP Phieu Thu"):
		return None
	khoa = f"NPP Phieu Thu:{pt}"
	r = frappe.db.get_value("NPP Phieu Thu", pt, ["name", "khach_hang", "ten_khach", "but_toan_tien", "nv_giu_tien_thua",
		"giao_tu_nv", "ve_npp_luc", "creation"], as_dict=True)
	pe = r.but_toan_tien if r else None
	con_no = _con_no([pe], "Payment Entry") if pe and frappe.db.get_value("Payment Entry", pe, "docstatus") == 1 else 0.0
	dong = frappe.db.get_value(DT, {"khoa_nguon": khoa}, "name")
	if not r or (abs(con_no) < 0.005 and not _con_tham_chieu(dong)):
		if dong:
			frappe.db.delete(DT, {"khoa_nguon": khoa})
		return None
	return _ghi(khoa, {
		"loai": "tien_thua", "khach_hang": r.khach_hang, "ten_khach": r.ten_khach, "hoa_don": None, "phieu_tra": None,
		"phieu_thu": pt, "don_hang": None,
		"nhan_vien": r.nv_giu_tien_thua, "giao_tu_nv": r.giao_tu_nv, "ve_npp_luc": r.ve_npp_luc,
		"so_tien": 0, "da_thu": -con_no, "con_no": con_no, "han_thanh_toan": None,
		"trang_thai": trang_thai(0, -con_no, False), "qua_han_tay": 0, "ghi_chu": "Tiền thừa chưa phân bổ",
		"tao_luc": r.creation, "tinh_luc": now_datetime(),
	})


def chieu_dong(r) -> None:
	"""Chiếu lại một dòng NPP Cong No theo loại (dòng đọc từ khoa_khach / get_all)."""
	if r.get("loai") == "tien_thua":
		chieu_tien_thua(r.get("phieu_thu"))
	elif r.get("loai") == "phieu_tra":
		chieu_phieu_tra(r.get("phieu_tra"))
	elif r.get("hoa_don"):
		chieu_hoa_don(r.get("hoa_don"))


def chieu_nguon_cua(si) -> None:
	"""Mọi dòng công nợ chịu ảnh hưởng của một Sales Invoice (HĐ: chính nó; tờ ghi có gắn HĐ: HĐ gắn; tờ ghi có độc lập của phiếu trả tự
	lập: dòng âm của phiếu)."""
	if si.get("is_return"):
		goc = si.get("npp_hoa_don_goc")
		if goc:
			chieu_hoa_don(goc)
		elif si.get("npp_phieu_tra"):
			chieu_phieu_tra(si.get("npp_phieu_tra"))
		return
	chieu_hoa_don(si.name)


# ------------------------------------------------------------------------------------------------ doc_events
def sau_ghi_so_hoa_don(doc, method=None):
	chieu_nguon_cua(doc)
	if method == "on_update_after_submit" and doc.get("is_return"):
		# tờ ghi có đổi HĐ gắn (npp_hoa_don_goc, AOS): HĐ cũ mất khoản trừ; dòng âm độc lập của phiếu tính lại theo điều kiện mới
		cu = doc.get_doc_before_save()
		goc_cu = cu.get("npp_hoa_don_goc") if cu else None
		if goc_cu and goc_cu != doc.get("npp_hoa_don_goc"):
			chieu_hoa_don(goc_cu)
		if doc.get("npp_phieu_tra") and doc.get("npp_hoa_don_goc"):
			chieu_phieu_tra(doc.get("npp_phieu_tra"))


def chieu_cac_hd(ten_hd) -> None:
	"""Chiếu lại các nguồn công nợ chịu ảnh hưởng của một nhóm Sales Invoice (mỗi tên một lần)."""
	for ten in dict.fromkeys(t for t in ten_hd if t):
		si = frappe.db.get_value("Sales Invoice", ten, ["name", "is_return", "npp_hoa_don_goc", "npp_phieu_tra"], as_dict=True)
		if si:
			chieu_nguon_cua(si)


def sau_thanh_toan(doc, method=None):
	"""Payment Entry ghi sổ / huỷ: chiếu lại mọi HĐ được phân bổ + dòng tiền thừa của phiếu thu cùng tên (phần chưa phân bổ)."""
	chieu_cac_hd(r.reference_name for r in doc.get("references") or [] if r.reference_doctype == "Sales Invoice")
	if doc.get("npp_phieu_thu"):
		chieu_tien_thua(doc.get("npp_phieu_thu"))


def sau_but_toan(doc, method=None):
	"""Journal Entry ghi sổ / huỷ: chiếu lại mọi HĐ / tờ ghi có mà một vế khách hàng tham chiếu (cấn trừ dư có `CTR-` của phiếu thu,
	lập lại cấn trừ…). Đặc tả phiếu thu §0.4 chỉ đòi bút toán của app (`npp_loai` khác trống); ở đây chiếu cho MỌI bút toán có vế tham
	chiếu HĐ — bản chiếu luôn khớp sổ kể cả khi kế toán cấn trừ tay trên Desk (chỉ đọc vài dòng, không tốn gì thêm)."""
	tk = [r for r in doc.get("accounts") or [] if r.party_type == "Customer"]
	chieu_cac_hd(r.reference_name for r in tk if r.reference_type == "Sales Invoice")
	for pe in dict.fromkeys(r.reference_name for r in tk if r.reference_type == "Payment Entry" and r.reference_name):
		chieu_tien_thua(frappe.db.get_value("Payment Entry", pe, "npp_phieu_thu"))
