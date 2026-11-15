"""KHÁM SỔ — chỉ đọc, không sửa gì. Mỗi dòng ra là một chứng từ cần xem; không ra dòng nào là sổ sạch.

phieu_tra(): bản ERPNext của `scripts/sql/kiem-phieu-tra.sql` (nppsale — chủ nhà 25/09/2026: "quét lại hết phiếu trả hàng xem có phiếu nào
ở trạng thái chờ xử lý mà chưa trừ công nợ ko ?") + bất biến riêng của bản ERPNext (tờ ghi có ↔ phiếu, phiếu nhập kho ↔ phiếu):
  1. Phiếu TỰ SINH Chờ xử lý / Hoàn thành có tiền mà không đúng MỘT tờ ghi có không kho đang ghi sổ = −tiền trả (cùng HĐ).
  2. Phiếu TỰ LẬP đang Chờ xử lý (luật mig 191: không được có).
  3. Hàng trả theo đơn KẸT NHÁP dù đơn đã xuất HĐ (lỗi trước mig 189).
  4. Phiếu tự lập độc lập Hoàn thành có tiền mà không có dòng công nợ âm / tờ ghi có lệch tiền.
  5. Phiếu tự lập Hoàn thành gắn HĐ có tiền mà tờ ghi có có kho không gắn đúng HĐ / lệch tiền.
  6. Công nợ HĐ lệch công thức: tiền HĐ − Σ tiền phiếu đã trừ (phiếu tự sinh Chờ xử lý / Hoàn thành, phiếu tự lập Hoàn thành).
  7. Phiếu Hoàn thành theo ĐƠN mà chưa gắn HĐ (mig 200).
  8. Phiếu tự sinh Hoàn thành có dòng mà không có phiếu nhập kho đang ghi sổ (hoặc phiếu chưa hoàn thành vẫn giữ phiếu nhập).
Nhóm 5 / 8 của nppsale (cấn phiếu trả ở phiếu thu kiểu cũ — applied_receipt_id) không port: bản ERPNext không có lối ấy.

	bench --site <site> execute nppsale.kham_so.phieu_tra
"""
from __future__ import annotations

import frappe
from frappe.utils import flt

DT = "NPP Phieu Tra"


def _dong(nhom: int, loai: str, chung_tu: str, khach: str | None, tien, chi_tiet: str, nen_lam: str) -> dict:
	return {"nhom": nhom, "loai": loai, "chung_tu": chung_tu, "khach": khach, "tien_tra": flt(tien), "chi_tiet": chi_tiet, "nen_lam": nen_lam}


def _tru_cua_hd() -> dict:
	"""Khoản trừ của từng HĐ — luật creditCounted (= `_wf2b_recompute_receivable` mig 133 / 186)."""
	return {r[0]: flt(r[1]) for r in frappe.db.sql(f"""SELECT `hoa_don`, SUM(IFNULL(`tien_tra`, 0)) FROM `tab{DT}`
		WHERE IFNULL(`hoa_don`, '') != '' AND ((`tu_sinh` = 1 AND `trang_thai` IN ('submitted', 'completed'))
			OR (`tu_sinh` = 0 AND `trang_thai` = 'completed')) GROUP BY `hoa_don`""")}


@frappe.whitelist()
def phieu_tra() -> list[dict]:
	frappe.only_for(("System Manager", "Administrator"))
	return quet_phieu_tra()


def quet_phieu_tra() -> list[dict]:
	ra: list[dict] = []
	if not frappe.db.exists("DocType", DT):
		return ra
	ten_khach = dict(frappe.db.sql("SELECT `name`, `customer_name` FROM `tabCustomer`"))
	pts = frappe.get_all(DT, fields=["name", "trang_thai", "tu_sinh", "tien_tra", "khach_hang", "hoa_don", "don_hang", "to_ghi_co",
		"phieu_nhap_kho", "creation"], order_by="name asc")
	# tờ ghi có đang ghi sổ theo phiếu
	to = {}
	for t in frappe.get_all("Sales Invoice", filters={"is_return": 1, "docstatus": 1, "npp_phieu_tra": ("is", "set")},
			fields=["name", "npp_phieu_tra", "npp_hoa_don_goc", "update_stock", "grand_total"]):
		to.setdefault(t.npp_phieu_tra, []).append(t)
	nhap = {r[0]: r[1] for r in frappe.db.sql("""SELECT `npp_phieu_tra`, COUNT(*) FROM `tabStock Entry`
		WHERE `docstatus` = 1 AND IFNULL(`npp_phieu_tra`, '') != '' GROUP BY `npp_phieu_tra`""")}
	co_dong = {r[0] for r in frappe.db.sql("""SELECT DISTINCT `parent` FROM `tabNPP Phieu Tra Dong` WHERE `parenttype` = %s AND `so_luong` > 0""",
		(DT,))}
	for p in pts:
		kh = ten_khach.get(p.khach_hang) or p.khach_hang
		tien = flt(p.tien_tra)
		dang = to.get(p.name, [])
		khong_kho = [t for t in dang if not t.update_stock]
		co_kho = [t for t in dang if t.update_stock]
		if p.tu_sinh and p.trang_thai in ("submitted", "completed") and p.hoa_don:
			can = 1 if tien != 0 else 0
			dung = len(khong_kho) == can and (not can or (khong_kho[0].npp_hoa_don_goc == p.hoa_don
				and abs(flt(khong_kho[0].grand_total) + tien) < 0.5 and p.to_ghi_co == khong_kho[0].name))
			if not dung:
				ra.append(_dong(1, "Phiếu tự sinh — tờ ghi có không khớp phiếu", p.name, kh, tien,
					f"{len(khong_kho)} tờ đang ghi sổ ({', '.join(f'{t.name} {flt(t.grand_total):g}' for t in khong_kho) or 'không có'}) — "
					f"phải là {can} tờ = {-tien:g} gắn {p.hoa_don}",
					"Chạy lại dong_bo_to_ghi_co(HĐ); vẫn còn thì báo lại"))
		elif khong_kho:
			ra.append(_dong(1, "Tờ ghi có không kho còn ghi sổ của phiếu không còn trừ vào HĐ", p.name, kh, tien,
				", ".join(t.name for t in khong_kho), "Huỷ tờ ghi có thừa"))
		if not p.tu_sinh and p.trang_thai == "submitted":
			ra.append(_dong(2, "Phiếu tự lập đang Chờ xử lý (chưa trừ nợ, chưa nhập kho)", p.name, kh, tien,
				f"Lập {frappe.utils.formatdate(p.creation, 'dd/MM/yyyy')}", "Về Nháp; bấm Hoàn thành thì mới nhập kho + trừ nợ"))
		if p.trang_thai == "draft" and not p.hoa_don and p.don_hang and tien > 0:
			hd = frappe.db.sql("""SELECT COUNT(*) FROM `tabSales Invoice` WHERE `npp_don_hang` = %s AND `docstatus` = 1 AND `is_return` = 0
				AND `creation` >= %s""", (p.don_hang, p.creation))[0][0]
			if hd:
				ra.append(_dong(3, "Hàng trả theo đơn kẹt Nháp — đơn đã xuất HĐ, công nợ không trừ", p.don_hang, kh, tien,
					f"Đơn có {hd} hóa đơn đã ghi sổ", "Gắn phiếu vào HĐ của đơn (câu gắn của post_invoice) rồi tính lại công nợ"))
		if not p.tu_sinh and p.trang_thai == "completed" and not p.hoa_don and not p.don_hang and tien != 0:
			no = frappe.db.get_value("NPP Cong No", {"khoa_nguon": f"{DT}:{p.name}"}, "so_tien")
			if no is None or abs(flt(no) + tien) >= 0.5 or len(co_kho) != 1 or abs(flt(co_kho[0].grand_total) + tien) >= 0.5:
				ra.append(_dong(4, "Phiếu tự lập độc lập đã hoàn thành — công nợ âm / tờ ghi có lệch", p.name, kh, tien,
					f"Công nợ {no if no is not None else 'KHÔNG CÓ DÒNG'}; tờ có kho: "
					f"{', '.join(f'{t.name} {flt(t.grand_total):g}' for t in co_kho) or 'không có'}",
					"Chiếu lại công nợ (chieu_phieu_tra); tờ lệch thì ghi nhận lại phiếu"))
		if not p.tu_sinh and p.trang_thai == "completed" and p.hoa_don and tien != 0:
			if len(co_kho) != 1 or co_kho[0].npp_hoa_don_goc != p.hoa_don or abs(flt(co_kho[0].grand_total) + tien) >= 0.5:
				ra.append(_dong(5, "Phiếu tự lập gắn HĐ đã hoàn thành — tờ ghi có không gắn đúng HĐ / lệch tiền", p.name, kh, tien,
					", ".join(f"{t.name} {flt(t.grand_total):g} → {t.npp_hoa_don_goc or '—'}" for t in co_kho) or "không có tờ có kho",
					"Đặt npp_hoa_don_goc của tờ = HĐ của phiếu rồi chiếu lại công nợ HĐ"))
		if p.trang_thai == "completed" and not p.hoa_don and p.don_hang:
			ra.append(_dong(7, "Phiếu hoàn thành theo ĐƠN, chưa gắn HĐ", p.name, kh, tien, f"Đơn {p.don_hang}",
				"Đơn 1 HĐ: gắn HĐ ấy; 0 hoặc nhiều HĐ: gắn tay vào đúng HĐ (hoặc huỷ phiếu)"))
		if p.tu_sinh:
			n = nhap.get(p.name, 0)
			if p.trang_thai == "completed" and p.name in co_dong and (n != 1 or not p.phieu_nhap_kho):
				ra.append(_dong(8, "Phiếu tự sinh đã nhập kho — phiếu nhập kho không khớp", p.name, kh, tien,
					f"{n} phiếu nhập đang ghi sổ, phieu_nhap_kho = {p.phieu_nhap_kho or 'trống'}", "Báo lại — không tự sửa kho"))
			elif p.trang_thai != "completed" and n:
				ra.append(_dong(8, "Phiếu tự sinh chưa hoàn thành mà còn phiếu nhập kho đang ghi sổ", p.name, kh, tien,
					f"{n} phiếu nhập đang ghi sổ", "Huỷ phiếu nhập thừa (huỷ nhập kho của phiếu)"))
	# 6. công nợ HĐ lệch công thức
	tru = _tru_cua_hd()
	for h in frappe.get_all("Sales Invoice", filters={"is_return": 0, "docstatus": 1, "name": ("in", list(tru) or [""])},
			fields=["name", "customer", "grand_total"]):
		no = frappe.db.get_value("NPP Cong No", {"khoa_nguon": f"Sales Invoice:{h.name}"}, "so_tien")
		dung = flt(h.grand_total) - tru[h.name]
		if no is None or abs(flt(no) - dung) >= 0.5:
			ra.append(_dong(6, "Công nợ HĐ lệch với tiền hàng trả", h.name, ten_khach.get(h.customer) or h.customer, tru[h.name],
				f"Công nợ {no if no is not None else 'KHÔNG CÓ DÒNG'} — đúng phải là {dung:g}", "Chiếu lại công nợ HĐ (chieu_hoa_don)"))
	ra.sort(key=lambda x: (x["nhom"], x["chung_tu"]))
	return ra
