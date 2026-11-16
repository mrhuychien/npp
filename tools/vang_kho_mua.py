#!/usr/bin/env python3
"""Dữ liệu vàng cho KHO + MUA HÀNG + CÔNG NỢ NCC (P4) — chạy CHÍNH hàm + trigger + RLS của nppsale ở Postgres tham chiếu
(schema_full.sql, /tmp/pg-npp): complete / cancel / sua / khoi_phuc phiếu nhập, luu_gia_nhap (+ trigger ghi giá nhập), post_stock_import,
complete / cancel / khoi_phuc phiếu trả NCC, record_payable_payment, chi_tra_ncc / huy_phieu_chi_ncc (+ dồn trả trước), gop / xoa NCC,
post_stock_issue / post_stock_transfer / post_stock_adjustment / reject_stock_adjustment / cancel_stock_entry / refresh_warehouse_zones,
RPC đọc (payables_summary, payables_by_supplier, so_chung_tu_ncc, bao_cao_ton_kho, finance_pnl, bao_cao_so_ban); ghi thẳng bảng dưới RLS +
trigger khoá (mig 170 / 227 / 232 / 233); bán (create_order_with_lines + post_invoice), huỷ HĐ, phiếu trả khách (P3) làm nền.

Đặc tả: scratchpad kho_mua/dac_ta_kho_mua.md §6 (87 kịch bản V01-V87, bộ dữ liệu F §6.0, quy ước so) + §6.10 (V81-V87) + §9 (bản sửa).

Khuôn như tools/vang_phieu_thu.py / vang_phieu_tra.py: mỗi kịch bản một giao dịch con rồi lui (ZZ999 — sổ tham chiếu không giữ gì, mọi
số đếm PN- / PTNCC- / PCNCC- bắt đầu lại); mỗi bước dưới đúng người (request.jwt.claim.sub + ROLE authenticated; "MAY_CHU" = quyền máy
chủ để dựng nền, "HE_THONG" = vai service_role không người — lịch chạy); bước hỏng thì ghi mã + câu lỗi và DỪNG kịch bản — trừ bước mang
"tiep": true (bước chờ lỗi mà đặc tả còn làm tiếp sau đó: lỗi được ghi, bước ấy lui về điểm lưu riêng, kịch bản chạy tiếp).

Chỗ giữ trong tải trọng (giải ở lúc chạy — hàm _vp4_id): "@org" "@org_b" "@u:<người>" "@S1".. (NCC) "@A".. (mặt hàng) "@K1" (khách)
"@la" (id lạ); "@pn:<nhãn>" "@ptn:<nhãn>" "@pk:<nhãn>" "@pc:<nhãn>" "@hd:<nhãn>" "@tk:<nhãn>" = chứng từ đã đặt nhãn ở bước trước;
"@pk:pn|ptn|hd:<nhãn>" = phiếu kho của phiếu nhập / phiếu trả NCC / HĐ; "@pk:nl:<nhãn>" = phiếu nhập lại của phiếu trả khách;
"@no:pn|ptn:<nhãn>" = dòng công nợ của phiếu; "@no:dk:<NCC>" = nợ đầu kỳ; "@no:ma:<số HĐ>" = dòng nợ theo số HĐ NCC; "@no:pk:<nhãn>" =
dòng nợ của phiếu kho; "@no:tt:<nhãn phiếu chi>" = dòng trả trước; "@lo:<mã lô>[@vùng]" = lô. Ngày "@hom_nay±n" (giờ VN), giờ
"@hom_nay±nTHH:MM:SS+07:00".

Ảnh chụp sau kịch bản (ct) theo KHOÁ NGHIỆP VỤ (không id): phiếu nhập + dòng, phiếu trả NCC + dòng, công nợ NCC (khoá PN:<mã> | PTNCC:<mã>
| DK:<NCC> | TT:<mã phiếu chi> | PK:<mã phiếu kho>[:<số HĐ>] | TAY:<số HĐ>) + khoản trả + phiếu chi, phiếu kho + dòng + vết lấy lô, lô
(tồn theo vùng, giá, hạn, trạng thái), bảng giá nhập, chi phí hao hụt, NCC + phân công, mặt hàng, HĐ bán / phiếu trả khách nền; số trả về
của từng bước (id → khoá nghiệp vụ). Ngày → "@hom_nay±n"; mốc giờ của lượt chạy → "@luc_goi", mốc giờ dựng sẵn → "@hom_nay±nTHH:MI" (VN).

Giờ: phiên đặt TimeZone = Asia/Ho_Chi_Minh — `CURRENT_DATE` / `::date` của nppsale (ngày UTC trên Supabase) trùng ngày VN, tức là chạy như
trong 07:00-23:59 giờ VN (§6.0 / §2.5); vì thế giờ in trong câu ALREADY_POSTED là giờ VN (đề xuất Frappe) — bộ sinh thay bằng chỗ giữ. Cả bộ
sinh là MỘT giao dịch nên now() đứng yên: sau mỗi bước, mốc giờ = now() của dòng vừa ghi lùi về "now() - 5 phút + số bước ms" — dòng của bước
sau luôn mới hơn (thứ tự ghi nợ / lúc chi / ngày nhận lô như production). id dòng do bộ sinh chèn là uuid5 tất định → hàm nppsale nào duyệt
`ORDER BY id` cho cùng kết quả mỗi lần sinh (hai lần sinh liền nhau ra cùng tệp).

	python3 tools/vang_kho_mua.py                 → nppsale/tests/du_lieu/kho_mua_mau.json
	python3 tools/vang_kho_mua.py --chi V17,V2    → chạy thử vài kịch bản (in kết quả, không ghi tệp)
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vang_phieu_tra import (
	DAT_LAI_CO,  # xoá cờ phiên npp.* trước mỗi bước (mỗi lời gọi production là một giao dịch)
)
from vang_tao_don import PSQL, _lit

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICH = os.path.join(GOC, "nppsale", "tests", "du_lieu", "kho_mua_mau.json")
NS = uuid.UUID("2b7f6c1e-4d0a-4f35-9e8b-5a1c3d7e9f04")


def uid(k: str) -> str:
	return str(uuid.uuid5(NS, k))


ORG = uid("p4:org")
ORG_B = uid("p4:org_b")
LA = uid("p4:la")  # id không có dòng nào

# ------------------------------------------------------------------------------------------------ bộ dữ liệu F (§6.0)
# người: khoá → (vai, NPP)
NGUOI = {"CHU": ("owner", "A"), "QL": ("manager", "A"), "KT": ("accountant", "A"), "TK": ("warehouse", "A"), "NV": ("sales", "A"),
	"CHU_B": ("owner", "B")}
# NCC: khoá → (tên, mã, NPP, hồ sơ thêm)
NCC = {
	"S1": ("NCC Một", "NCC01", "A", {"phone": "0901", "notes": "ghi chú S1"}),
	"S2": ("NCC Hai", "NCC02", "A", {"email": "hai@ncc", "tax_code": "0101", "notes": "NCC hai cũ"}),
	"S3": ("NCC Ba", None, "A", {}),
	"S0": ("NCC trống", None, "A", {}),
	"S4": ("NCC Bốn", None, "A", {}),
	"SB": ("NCC của B", "B01", "B", {}),
}
# mặt hàng: khoá → (sku, tên, ĐV cơ sở, hạn dùng (ngày) hoặc None, {ĐV: hệ số}, NCC chính)
HANG = {
	"A": ("SPA", "Hàng A", "hộp", None, {"thùng": 24}, None),
	"B": ("SPB", "Hàng B", "gói", None, {}, "S3"),
	"C": ("SPC", "Hàng C", "chai", 20, {}, None),
	"D": ("SPD", "Hàng D", "lon", 180, {"lốc": 6, "thùng": 24}, None),
	"K": ("SPK", "Hàng K", "kg", None, {}, None),
	"M": ("SPM", "Sữa hộp", "hộp", None, {"thùng": 24}, "S1"),
	"N": ("SPN", "Kẹo", "túi", None, {"thùng": 10}, "S3"),
	"P": ("SPP", "Nuoc ngot", "Lon", None, {"Thung": 24}, None),
	"Q": ("SPQ", "Dau an", "Chai", None, {}, None),
	"G": ("SPG", "Gao", "Kg", None, {}, None),
	"R": ("SPR", "Hàng R", "cái", None, {}, "S4"),
}
# [Frappe] hàng KHÔNG LÔ (chỉ bản Frappe dựng — has_batch_no 0, allow_negative_stock 1; §6.0) cho V12b / V19b / V43c / V44c
HANG_FRAPPE = {"X": ("SPX", "Hàng không lô", "cai", None, {}, None, {"has_batch_no": 0, "allow_negative_stock": 1})}
KHACH = {"K1": "Khach Mot"}
# giá bán (bảng giá chung) cho các lượt bán làm nền: (mặt hàng, ĐV, giá)
GIA_BAN = [("A", "hộp", 12000), ("P", "Lon", 10000), ("G", "Kg", 25000), ("M", "hộp", 1500), ("R", "cái", 8000)]
# Danh mục chi phí của NPP A (hao hụt kiểm kê ghi vào COGS_ADJ — post_stock_adjustment)
DANH_MUC_CP = [("COGS_ADJ", "Dieu chinh kiem ke", "cogs"), ("AAA", "Khac", "other")]

KHOA_TINH = {"@org": ORG, "@org_b": ORG_B, "@la": LA, "@S5": uid("p4:S5")}
for _k in NGUOI:
	KHOA_TINH["@u:" + _k] = uid("p4:u:" + _k)
for _k in NCC:
	KHOA_TINH["@" + _k] = uid("p4:ncc:" + _k)
for _k in HANG:
	KHOA_TINH["@" + _k] = uid("p4:sp:" + _k)
for _k in KHACH:
	KHOA_TINH["@" + _k] = uid("p4:kh:" + _k)


def _hom_nay() -> datetime.date:
	return (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=7)).date()


_RE_NGAY = re.compile(r"^@hom_nay([+-]\d+)?(T.*)?$")


def thuc(v, hn: datetime.date | None = None):
	""""@hom_nay±n" → ngày thật (VN); "@hom_nay±nT12:00:00+07:00" → mốc giờ thật — bộ sinh và bài so dùng cùng luật."""
	hn = hn or _hom_nay()
	if isinstance(v, str):
		m = _RE_NGAY.match(v)
		if m:
			d = (hn + datetime.timedelta(days=int(m.group(1) or 0))).isoformat()
			return d + (m.group(2) or "")
		return v
	if isinstance(v, dict):
		return {a: thuc(b, hn) for a, b in v.items()}
	if isinstance(v, list):
		return [thuc(x, hn) for x in v]
	return v


# ------------------------------------------------------------------------------------------------ bước
def _b(buoc, nguoi, **k):
	o = {"buoc": buoc, "nguoi": nguoi}
	for a, v in k.items():
		if v is not None or a in ("ly_do", "gia_tri", "p_dong"):
			o[a] = v
	return o


def d(sp, dv, sl, gia, *, giam=0, thue=0, hs=1, stt=None, ghi_chu=None, tien=None):
	"""Một dòng phiếu nhập / phiếu trả NCC đúng như màn ghi (cột nppsale): giảm dòng là TIỀN, thuế là TỈ LỆ, line_total = lineTotalOf."""
	net = max(0, sl * gia - giam)
	return {"product_id": sp, "unit_name": dv, "quantity": sl, "unit_price": gia, "line_discount": giam, "vat_rate": thue,
		"conversion_factor": hs, "line_total": tien if tien is not None else round(net * (1 + thue), 6), "notes": ghi_chu,
		"sort_order": stt}


def _danh_stt(dong):
	return [dict(x, sort_order=x["sort_order"] if x.get("sort_order") is not None else i + 1) for i, x in enumerate(dong)]


def _xem(dong, giam=0, thue_tay=None):
	"""Tiền xem trước màn máy tính gửi kèm phiếu tạm (receipt-form purchaseTotals): Σ tiền dòng, VAT dòng hoặc số gõ tay, giảm sau thuế."""
	sub = sum(max(0, x["quantity"] * x["unit_price"] - x["line_discount"]) for x in dong)
	vat = sum(max(0, x["quantity"] * x["unit_price"] - x["line_discount"]) * x["vat_rate"] for x in dong)
	if thue_tay is not None:
		vat = max(0, thue_tay)
	return {"subtotal": sub, "vat": round(vat, 6), "total": max(0, round(sub + vat - giam, 6))}


def pn(nguoi, nhan, ncc, dong, *, so_hd=None, ngay=None, vung="sale", giam=0, thue_tay=None, ghi_chu=None, xem=None, them=None):
	"""Phiếu nhập TẠM ghi thẳng qua cổng (purchase_invoices.insert + purchase_invoice_lines.insert — như save-receipt.ts)."""
	dong = _danh_stt(dong)
	dau = {"org_id": "@org", "supplier_id": ncc, "invoice_number": so_hd, "invoice_date": ngay, "warehouse_zone": vung, "discount": giam,
		"vat_override": thue_tay, "notes": ghi_chu, "status": "draft", "created_by": "@u:" + nguoi, **(xem or _xem(dong, giam, thue_tay)),
		**(them or {})}
	if ngay is None:
		dau.pop("invoice_date")
	return _b("pn", nguoi, nhan=nhan, dau=dau, dong=dong)


def pn_dong(nguoi, nhan, dong):
	"""Ghi lại dòng của phiếu tạm (xoá hết rồi chèn — saveReceiptLines)."""
	return _b("pn_dong", nguoi, nhan=nhan, dong=_danh_stt(dong))


def pn_hoan(nguoi, nhan, tiep=None):
	return _b("pn_hoan", nguoi, nhan=nhan, tiep=tiep)


def pn_huy(nguoi, nhan, ly_do="Người dùng huỷ từ màn chi tiết", tiep=None):
	return _b("pn_huy", nguoi, nhan=nhan, ly_do=ly_do, tiep=tiep)


def pn_sua(nguoi, nhan, dau, dong, tiep=None):
	"""sua_phieu_nhap(p_head, p_lines) — dòng theo thứ tự (stt = vị trí)."""
	return _b("pn_sua", nguoi, nhan=nhan, dau=dau, dong=_danh_stt(dong), tiep=tiep)


def pn_khoi_phuc(nguoi, nhan, tiep=None):
	return _b("pn_khoi_phuc", nguoi, nhan=nhan, tiep=tiep)


def gia(nguoi, dong, tiep=None):
	"""luu_gia_nhap(p_dong) — dong: [(mặt hàng, ĐV, giá | None)] hoặc tải trọng thô."""
	if isinstance(dong, list) and dong and isinstance(dong[0], tuple):
		dong = [{"product_id": sp, "unit_name": dv, "price": g} for sp, dv, g in dong]
	return _b("gia", nguoi, p_dong=dong, tiep=tiep)


def nhap_kho(nguoi, nhan, p, tiep=None):
	"""post_stock_import(p) → phiếu kho đặt nhãn "pk:<nhan>"."""
	return _b("nhap_kho", nguoi, nhan=nhan, p=p, tiep=tiep)


def ptn(nguoi, nhan, ncc, dong, *, vung="date", giam=0, thue_tay=None, ly_do=None, ghi_chu=None, ma=None, xem=None, them=None):
	"""Phiếu trả NCC NHÁP ghi thẳng qua cổng (supplier_returns.insert + supplier_return_lines.insert)."""
	dong = _danh_stt(dong)
	dau = {"org_id": "@org", "supplier_id": ncc, "warehouse_zone": vung, "discount": giam, "vat_override": thue_tay, "reason": ly_do,
		"notes": ghi_chu, "status": "draft", "created_by": "@u:" + nguoi, **(xem or _xem(dong, giam, thue_tay)), **(them or {})}
	if ma is not None:
		dau["return_code"] = ma
	if vung is None:
		dau.pop("warehouse_zone")
	return _b("ptn", nguoi, nhan=nhan, dau=dau, dong=dong)


def ptn_dong(nguoi, nhan, dong):
	return _b("ptn_dong", nguoi, nhan=nhan, dong=_danh_stt(dong))


def ptn_gui(nguoi, nhan, tiep=None):
	return _b("ptn_gui", nguoi, nhan=nhan, tiep=tiep)


def ptn_huy(nguoi, nhan, ly_do="Người dùng huỷ từ màn chi tiết", tiep=None):
	return _b("ptn_huy", nguoi, nhan=nhan, ly_do=ly_do, tiep=tiep)


def ptn_khoi_phuc(nguoi, nhan, tiep=None):
	return _b("ptn_khoi_phuc", nguoi, nhan=nhan, tiep=tiep)


def ghi_tra(nguoi, no, tien, cach="transfer", ghi_chu=None, tiep=None):
	"""record_payable_payment(dòng nợ, tiền, hình thức, ghi chú)."""
	return _b("ghi_tra", nguoi, no=no, tien=tien, cach=cach, ghi_chu=ghi_chu, tiep=tiep)


def chi(nguoi, nhan, ncc, tien, ngay=None, cach="cash", ghi_chu=None, tham_chieu=None, tiep=None):
	"""chi_tra_ncc(NCC, tiền, ngày, hình thức, ghi chú, tham chiếu) → phiếu chi đặt nhãn "pc:<nhan>"."""
	o = _b("chi", nguoi, nhan=nhan, ncc=ncc, tien=tien, ngay=ngay, cach=cach, ghi_chu=ghi_chu, tham_chieu=tham_chieu, tiep=tiep)
	o["cach"] = cach  # None tường minh = gửi NULL (V37)
	return o


def huy_chi(nguoi, nhan, ly_do=None, tiep=None):
	return _b("huy_chi", nguoi, nhan=nhan, ly_do=ly_do, tiep=tiep)


def gop(nguoi, tu, vao, tiep=None):
	return _b("gop", nguoi, tu=tu, vao=vao, tiep=tiep)


def xoa_ncc(nguoi, ncc, xoa_hang="__mac_dinh__", tiep=None):
	o = _b("xoa_ncc", nguoi, ncc=ncc, tiep=tiep)
	if xoa_hang != "__mac_dinh__":
		o["xoa_hang"] = xoa_hang
	return o


def dk(sp, sl, *, dv=None, cs=None, gia=0, lo=None, hs=1, ghi_chu=None):
	"""Một dòng phiếu kho do màn lập (stock_entry_lines): sl = SL giao dịch, cs = SL cơ sở (mặc định sl * hệ số)."""
	dvx = dv or HANG[sp[1:]][2]
	cs = sl * hs if cs is None else cs
	return {"product_id": sp, "batch_id": lo, "unit_name": dvx, "quantity": sl, "qty_in_base_uom": cs, "qty_in_transaction_uom": sl,
		"transaction_uom": dvx, "conversion_factor_snapshot": hs, "unit_cost": gia, "notes": ghi_chu}


def pk(nguoi, nhan, loai, vung, dong, *, ma=None, dich=None, ly_do_xuat=None, ghi_chu=None, status="draft", them=None):
	"""Phiếu kho NHÁP ghi thẳng qua cổng (stock_entries.insert + stock_entry_lines.insert — màn xuất lẻ / chuyển kho / kiểm kê)."""
	dau = {"org_id": "@org", "entry_code": ma or nhan, "type": loai, "warehouse_zone": vung, "dest_warehouse_zone": dich,
		"issue_reason": ly_do_xuat, "notes": ghi_chu, "status": status, "created_by": "@u:" + nguoi, **(them or {})}
	if status is None:
		dau.pop("status")
	if vung is None:
		dau.pop("warehouse_zone")
	return _b("pk", nguoi, nhan=nhan, dau=dau, dong=dong)


def xuat_le(nguoi, nhan, tiep=None):
	return _b("xuat_le", nguoi, nhan=nhan, tiep=tiep)


def chuyen(nguoi, nhan, tiep=None):
	return _b("chuyen", nguoi, nhan=nhan, tiep=tiep)


def kk_duyet(nguoi, nhan, tiep=None):
	return _b("kk_duyet", nguoi, nhan=nhan, tiep=tiep)


def kk_tu_choi(nguoi, nhan, ly_do=None, tiep=None):
	return _b("kk_tu_choi", nguoi, nhan=nhan, ly_do=ly_do, tiep=tiep)


def huy_pk(nguoi, nhan, ly_do=None, tiep=None):
	"""cancel_stock_entry(phiếu, lý do) — nhan là nhãn ("X") hoặc chỗ giữ ("@pk:pn:P")."""
	return _b("huy_pk", nguoi, nhan=nhan, ly_do=ly_do, tiep=tiep)


def ra_soat(nguoi, org="@org", tiep=None):
	return _b("ra_soat", nguoi, org=org, tiep=tiep)


def ghi(nguoi, bang, hanh_dong, gia_tri=None, loc=None, tiep=None):
	"""Ghi thẳng bảng dưới RLS + trigger như cổng PostgREST (insert / update / delete); kết quả so: số dòng chạm (RLS lọc → 0, không lỗi)."""
	return _b("ghi", nguoi, bang=bang, hanh_dong=hanh_dong, gia_tri=gia_tri, loc=loc, tiep=tiep)


def doc(nguoi, ten, tiep=None, **ts):
	"""RPC đọc dưới đúng người — kết quả vào số trả về của bước."""
	return _b("doc", nguoi, ten=ten, ts=ts, tiep=tiep)


def dem(nguoi, bang, loc=None):
	"""Đếm dòng đọc được qua cổng (RLS của người gọi)."""
	return _b("dem", nguoi, bang=bang, loc=loc)


def ban(nguoi, nhan, dong, khach="@K1"):
	"""Bán làm nền (P3): create_order_with_lines (đơn submitted) + post_invoice đủ dòng → HĐ đặt nhãn "hd:<nhan>". dong: [(mặt hàng, ĐV, SL)]."""
	return _b("ban", nguoi, nhan=nhan, khach=khach, dong=[{"product_id": sp, "unit_name": dv, "quantity": sl} for sp, dv, sl in dong])


def huy_hd(nguoi, nhan, ly_do="Khach tra lai hang"):
	return _b("huy_hd", nguoi, nhan=nhan, ly_do=ly_do)


def tra_khach(nguoi, nhan, dong, khach="@K1"):
	"""Phiếu trả khách TỰ LẬP không gắn HĐ (create_return_with_lines + complete_return kho bán) → phiếu nhập lại NL-."""
	return _b("tra_khach", nguoi, nhan=nhan, khach=khach,
		dong=[{"product_id": sp, "unit_name": dv, "quantity": sl, "unit_price": g, "vat_rate": 0, "is_exchange": False} for sp, dv, sl, g in dong])


def lo(ma, sp, vung, ton, gia, *, han=None, nhan=-30, tao=None, vi_tri=None, nsx=None, nhap=None):
	"""Lô dựng sẵn bằng quyền máy chủ (nppsale INSERT batches — trigger tự đẩy vùng date chạy; Frappe: Material Receipt có gói lô, ghi lùi
	ngày nhận). han: số ngày từ hôm nay (None = không hạn → 2099-12-31); nhan / tao: ngày nhận / ngày tạo (08:00 VN)."""
	return _b("lo", "MAY_CHU", ma=ma, sp=sp, vung=vung, ton=ton, gia=gia, han=han, nhan_ngay=nhan, tao_ngay=tao if tao is not None else nhan,
		vi_tri=vi_tri, nsx=nsx, nhap=nhap)


def co_am(bat=True):
	"""Cờ bán vượt tồn của NPP (organizations.allow_oversell ↔ NPP Cai Dat.cho_ban_vuot_ton)."""
	return _b("co_am", "MAY_CHU", bat=bat)


def nguong(n):
	"""Ngưỡng kho date (pricing_rules.date_warehouse_threshold_days ↔ NPP Cai Dat.nguong_kho_date_ngay)."""
	return _b("nguong", "MAY_CHU", ngay=n)


def dong_lo(ma):
	"""Đóng lô (nppsale batches.status 'cancelled' ↔ Frappe Batch.disabled = 1)."""
	return _b("dong_lo", "MAY_CHU", lo=ma)


def may_chu(sql, mo_ta):
	"""Đặt dữ liệu bằng quyền máy chủ — CHỈ phía nppsale (dữ liệu cũ / sửa tay); {@khoá} trong câu = id lúc chạy."""
	return _b("may_chu", "MAY_CHU", sql=sql, mo_ta=mo_ta)


def doc_phien():
	"""Số phiên danh mục bán (danh_muc_ban_phien.phien ↔ NPP Phien Danh Muc)."""
	return _b("doc_phien", "MAY_CHU")


def kham_ncc():
	"""Bất biến khám sổ công nợ NCC (kham-so-that.sql dòng 66 — BP §7.2 điểm 8), đọc bằng quyền máy chủ."""
	return _b("kham_ncc", "MAY_CHU")


def doc_bang(nguoi, bang, loc=None, cot=None):
	"""Đọc thẳng một bảng / view qua cổng (RLS người gọi) — dòng chuẩn hoá theo khoá nghiệp vụ."""
	return _b("doc_bang", nguoi, bang=bang, loc=loc, cot=cot)


# Từ vựng bước (ghi vào tệp vàng cho bài so bản Frappe): loại bước → mô tả (docstring của hàm dựng bước)
BUOC_MO_TA = {
	"pn": pn.__doc__, "pn_dong": pn_dong.__doc__, "pn_hoan": "complete_purchase_invoice(phiếu nhập có nhãn)",
	"pn_huy": "cancel_purchase_invoice(phiếu, lý do)", "pn_sua": pn_sua.__doc__, "pn_khoi_phuc": "khoi_phuc_phieu_nhap(phiếu)",
	"gia": gia.__doc__, "nhap_kho": nhap_kho.__doc__, "ptn": ptn.__doc__, "ptn_dong": "Ghi lại dòng phiếu trả NCC nháp (xoá hết rồi chèn)",
	"ptn_gui": "complete_supplier_return(phiếu)", "ptn_huy": "cancel_supplier_return(phiếu, lý do)", "ptn_khoi_phuc": "khoi_phuc_phieu_tra_ncc(phiếu)",
	"ghi_tra": ghi_tra.__doc__, "chi": chi.__doc__, "huy_chi": "huy_phieu_chi_ncc(phiếu chi, lý do)", "gop": "gop_nha_cung_cap(tu, vao)",
	"xoa_ncc": "xoa_nha_cung_cap(NCC[, xoa_hang]) — không có khoá xoa_hang = không truyền tham số", "pk": pk.__doc__,
	"xuat_le": "post_stock_issue(phiếu)", "chuyen": "post_stock_transfer(phiếu)", "kk_duyet": "post_stock_adjustment(phiếu)",
	"kk_tu_choi": "reject_stock_adjustment(phiếu, lý do)", "huy_pk": huy_pk.__doc__, "ra_soat": "refresh_warehouse_zones(NPP)",
	"ghi": ghi.__doc__, "doc": doc.__doc__ + " Tên: payables_summary, payables_by_supplier, so_chung_tu_ncc, bao_cao_ton_kho, finance_pnl, "
	"bao_cao_so_ban; mô phỏng câu màn: hoa_don_mua_con_no (V77), lo_theo_phieu_goc (V87).", "dem": dem.__doc__, "ban": ban.__doc__,
	"huy_hd": "cancel_invoice(HĐ có nhãn, lý do)", "tra_khach": tra_khach.__doc__, "lo": lo.__doc__, "co_am": co_am.__doc__,
	"nguong": nguong.__doc__, "dong_lo": dong_lo.__doc__, "may_chu": may_chu.__doc__, "doc_phien": doc_phien.__doc__,
	"kham_ncc": kham_ncc.__doc__, "doc_bang": doc_bang.__doc__,
	"song_song": "[Frappe] chạy đồng thời các bước trong `lenh` (hai tiến trình)", "viec_dem": "[Frappe] việc nền theo lịch (không người)",
	"goi_rpc": "[Frappe] gọi RPC `ten` với tham số `ts`",
}


# ------------------------------------------------------------------------------------------------ SQL — sinh từng bước
def _j(v) -> str:
	"""Tải trọng (có chỗ giữ) → biểu thức jsonb: "@hom_nay…" đổi ở Python, "@…" khác đổi lúc chạy (_vp4_thay)."""
	return f"public._vp4_thay({_lit(json.dumps(thuc(v), ensure_ascii=False))}, v_nhan)::jsonb"


def _id(k) -> str:
	if k is None:
		return "NULL::uuid"
	return f"public._vp4_id({_lit(k)}, v_nhan)"


def _pk_khoa(nhan: str) -> str:
	return _kh("pk", nhan)


def _kh(loai: str, nhan: str) -> str:
	"""Nhãn → chỗ giữ ("P" → "@pn:P"); nhãn đã là chỗ giữ ("@la", "@pk:pn:P") giữ nguyên."""
	return nhan if nhan.startswith("@") else f"@{loai}:{nhan}"


def _t(v) -> str:
	return "NULL" if v is None else _lit(str(v))


def _so(v) -> str:
	return "NULL" if v is None else (f"{_lit(v)}::numeric" if isinstance(v, str) else repr(v))


def _ghi_nhan(khoa: str, bieu: str) -> str:
	return f"v_nhan := v_nhan || jsonb_build_object({_lit(khoa)}, ({bieu})::text);"


def _cot(bang: str, cols) -> tuple[str, str]:
	return ", ".join(cols), ", ".join("r." + c for c in cols)


def _chen(bang: str, gia_tri: dict, id_bieu: str | None = None) -> str:
	cols = list(gia_tri)
	ds, rs = _cot(bang, cols)
	if id_bieu:
		return (f"INSERT INTO {bang} (id, {ds}) SELECT {id_bieu}, {rs} FROM jsonb_populate_record(NULL::{bang}, {_j(gia_tri)}) r;")
	return f"INSERT INTO {bang} ({ds}) SELECT {rs} FROM jsonb_populate_record(NULL::{bang}, {_j(gia_tri)}) r;"


def _chen_dong(bang: str, khoa_cha: str, id_bieu: str, dong: list, hat: str) -> str:
	"""Chèn dòng con; id dòng tất định (uuid5 theo kịch bản / bước / thứ tự) — hàm nppsale nào duyệt dòng `ORDER BY id` (xuất lẻ, kiểm
	kê, huỷ phiếu nhập kho) cho cùng thứ tự mỗi lần sinh."""
	if not dong:
		return ""
	cols = sorted({c for x in dong for c in x})
	ds, rs = _cot(bang, cols)
	rows = [{"id": uid(f"{hat}:{i}"), **{c: x.get(c) for c in cols}} for i, x in enumerate(dong)]
	return (f"INSERT INTO {bang} (id, {khoa_cha}, {ds}) SELECT r.id, {id_bieu}, {rs} FROM jsonb_populate_recordset(NULL::{bang}, "
		f"{_j(rows)}) WITH ORDINALITY AS r ORDER BY ordinality;")


_CO_ID = {"payables", "batches", "stock_entries", "stock_entry_lines", "payable_payments", "supplier_payments", "suppliers",
	"purchase_invoices", "purchase_invoice_lines", "supplier_returns", "supplier_return_lines"}


def _ghi_thang(b: dict, hat: str = "") -> str:
	"""Ghi thẳng dưới RLS: insert (cột theo tải trọng) / update (SET theo tải trọng) / delete — lọc bằng bản ghi `loc`. Dòng chèn không
	mang id thì được id tất định (cùng thứ tự `ORDER BY id` mỗi lần sinh)."""
	bang, hd, g, loc = b["bang"], b["hanh_dong"], b.get("gia_tri") or {}, b.get("loc") or {}
	if hd == "insert":
		rows = g if isinstance(g, list) else [g]
		if bang in _CO_ID:
			rows = [x if "id" in x else {"id": uid(f"{hat}:{i}"), **x} for i, x in enumerate(rows)]
		cols = sorted({c for x in rows for c in x})
		ds, rs = _cot(bang, cols)
		cau = f"INSERT INTO {bang} ({ds}) SELECT {rs} FROM jsonb_populate_recordset(NULL::{bang}, $1) r"
		tham = _j([{c: x.get(c) for c in cols} for x in rows])
	elif hd == "update":
		sets = ", ".join(f"{c} = r.{c}" for c in g)
		dieu = " AND ".join(f"t.{c} = f.{c}" for c in loc) or "true"
		cau = (f"UPDATE {bang} t SET {sets} FROM jsonb_populate_record(NULL::{bang}, $1) r, jsonb_populate_record(NULL::{bang}, $2) f "
			f"WHERE {dieu}")
		tham = _j(g)
	else:
		dieu = " AND ".join(f"t.{c} = f.{c}" for c in loc) or "true"
		cau = f"DELETE FROM {bang} t USING jsonb_populate_record(NULL::{bang}, $2) f WHERE {dieu}"
		tham = "NULL::jsonb"
	return (f"EXECUTE {_lit(cau)} USING {tham}, {_j(loc)}; GET DIAGNOSTICS v_n = ROW_COUNT; "
		"v_tra := jsonb_build_object('so_dong', v_n);")


def _lenh(b: dict, ma: str, so: int = 0) -> str:  # một nhánh mỗi loại bước
	k = b["buoc"]
	hat = f"p4:{ma}:{so}"
	if k == "pn":
		i = uid(f"p4:{ma}:pn:{b['nhan']}")
		return (_chen("purchase_invoices", b["dau"], f"'{i}'::uuid")
			+ _chen_dong("purchase_invoice_lines", "invoice_id", f"'{i}'::uuid", b["dong"], hat) + _ghi_nhan("pn:" + b["nhan"], f"'{i}'"))
	if k == "pn_dong":
		x = _id("@pn:" + b["nhan"])
		return f"DELETE FROM purchase_invoice_lines WHERE invoice_id = {x}; " + _chen_dong("purchase_invoice_lines", "invoice_id", x, b["dong"], hat)
	if k == "ptn":
		i = uid(f"p4:{ma}:ptn:{b['nhan']}")
		return (_chen("supplier_returns", b["dau"], f"'{i}'::uuid")
			+ _chen_dong("supplier_return_lines", "return_id", f"'{i}'::uuid", b["dong"], hat) + _ghi_nhan("ptn:" + b["nhan"], f"'{i}'"))
	if k == "ptn_dong":
		x = _id("@ptn:" + b["nhan"])
		return f"DELETE FROM supplier_return_lines WHERE return_id = {x}; " + _chen_dong("supplier_return_lines", "return_id", x, b["dong"], hat)
	if k == "pk":
		i = uid(f"p4:{ma}:pk:{b['nhan']}")
		return (_chen("stock_entries", b["dau"], f"'{i}'::uuid")
			+ _chen_dong("stock_entry_lines", "entry_id", f"'{i}'::uuid", b["dong"], hat) + _ghi_nhan("pk:" + b["nhan"], f"'{i}'"))
	if k == "pn_hoan":
		return f"SELECT to_jsonb(public.complete_purchase_invoice({_id(_kh('pn', b['nhan']))})) INTO v_tra;"
	if k == "pn_huy":
		return f"SELECT to_jsonb(public.cancel_purchase_invoice({_id(_kh('pn', b['nhan']))}, {_t(b['ly_do'])})) INTO v_tra;"
	if k == "pn_sua":
		return f"SELECT public.sua_phieu_nhap({_id(_kh('pn', b['nhan']))}, {_j(b['dau'])}, {_j(b['dong'])}) INTO v_tra;"
	if k == "pn_khoi_phuc":
		return f"SELECT public.khoi_phuc_phieu_nhap({_id(_kh('pn', b['nhan']))}) INTO v_tra;"
	if k == "gia":
		return f"SELECT public.luu_gia_nhap({_j(b['p_dong'])}) INTO v_tra;"
	if k == "nhap_kho":
		return (f"SELECT to_jsonb(r) INTO v_tra FROM public.post_stock_import({_j(b['p'])}) r; "
			+ _ghi_nhan("pk:" + b["nhan"], "v_tra->>'entry_id'"))
	if k == "ptn_gui":
		return f"SELECT to_jsonb(public.complete_supplier_return({_id(_kh('ptn', b['nhan']))})) INTO v_tra;"
	if k == "ptn_huy":
		return f"SELECT to_jsonb(public.cancel_supplier_return({_id(_kh('ptn', b['nhan']))}, {_t(b['ly_do'])})) INTO v_tra;"
	if k == "ptn_khoi_phuc":
		return f"SELECT public.khoi_phuc_phieu_tra_ncc({_id(_kh('ptn', b['nhan']))}) INTO v_tra;"
	if k == "ghi_tra":
		return (f"SELECT to_jsonb(r) INTO v_tra FROM public.record_payable_payment({_id(b['no'])}, {_so(b['tien'])}, {_t(b.get('cach'))}, "
			f"{_t(b.get('ghi_chu'))}) r;")
	if k == "chi":
		ngay = "NULL::date" if b.get("ngay") is None else f"{_lit(thuc(b['ngay']))}::date"
		return (f"SELECT public.chi_tra_ncc({_id(b['ncc'])}, {_so(b['tien'])}, {ngay}, {_t(b.get('cach'))}, {_t(b.get('ghi_chu'))}, "
			f"{_t(b.get('tham_chieu'))}) INTO v_tra; " + _ghi_nhan("pc:" + b["nhan"], "v_tra->>'id'"))
	if k == "huy_chi":
		return f"SELECT public.huy_phieu_chi_ncc({_id(_kh('pc', b['nhan']))}, {_t(b.get('ly_do'))}) INTO v_tra;"
	if k == "gop":
		return f"SELECT public.gop_nha_cung_cap({_id(b['tu'])}, {_id(b['vao'])}) INTO v_tra;"
	if k == "xoa_ncc":
		if "xoa_hang" in b:
			return (f"SELECT public.xoa_nha_cung_cap({_id(b['ncc'])}, "
				f"{'NULL' if b['xoa_hang'] is None else str(b['xoa_hang']).lower()}) INTO v_tra;")
		return f"SELECT public.xoa_nha_cung_cap({_id(b['ncc'])}) INTO v_tra;"
	if k == "xuat_le":
		return f"SELECT to_jsonb(public.post_stock_issue({_id(_pk_khoa(b['nhan']))})) INTO v_tra;"
	if k == "chuyen":
		return f"SELECT to_jsonb(public.post_stock_transfer({_id(_pk_khoa(b['nhan']))})) INTO v_tra;"
	if k == "kk_duyet":
		return f"SELECT to_jsonb(r) INTO v_tra FROM public.post_stock_adjustment({_id(_pk_khoa(b['nhan']))}) r;"
	if k == "kk_tu_choi":
		return f"SELECT to_jsonb(public.reject_stock_adjustment({_id(_pk_khoa(b['nhan']))}, {_t(b.get('ly_do'))})) INTO v_tra;"
	if k == "huy_pk":
		return f"SELECT to_jsonb(r) INTO v_tra FROM public.cancel_stock_entry({_id(_pk_khoa(b['nhan']))}, {_t(b.get('ly_do'))}) r;"
	if k == "ra_soat":
		return f"SELECT to_jsonb(public.refresh_warehouse_zones({_id(b['org'])})) INTO v_tra;"
	if k == "ghi":
		return _ghi_thang(b, hat)
	if k == "dem":
		dieu = " AND ".join(f"t.{c} = f.{c}" for c in (b.get("loc") or {})) or "true"
		cau = f"SELECT count(*) FROM {b['bang']} t, jsonb_populate_record(NULL::{b['bang']}, $1) f WHERE {dieu}"
		return f"EXECUTE {_lit(cau)} INTO v_n USING {_j(b.get('loc') or {})}; v_tra := jsonb_build_object('so', v_n);"
	if k == "doc":
		return _doc_sql(b)
	if k == "doc_bang":
		return _doc_bang_sql(b)
	if k == "ban":
		return _ban_sql(b, ma)
	if k == "huy_hd":
		return f"SELECT to_jsonb(r) INTO v_tra FROM public.cancel_invoice({_id(_kh('hd', b['nhan']))}, {_t(b['ly_do'])}) r;"
	if k == "tra_khach":
		head = {"customer_id": b["khach"], "reason": "damaged", "status": "draft"}
		return (f"SELECT public.create_return_with_lines({_j(head)}, {_j(b['dong'])}) INTO v_id; "
			"SELECT jsonb_build_object('entry_id', x) INTO v_tra FROM public.complete_return(v_id, 'sale') AS x; "
			+ _ghi_nhan("tk:" + b["nhan"], "v_id"))
	if k == "lo":
		hn = "(now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date"
		han = "DATE '2099-12-31'" if b.get("han") is None else f"{hn} + {b['han']}"
		luc_nhan = f"(({hn} + {b['nhan_ngay']}) + time '08:00') AT TIME ZONE 'Asia/Ho_Chi_Minh'"
		luc_tao = f"(({hn} + {b['tao_ngay']}) + time '08:00') AT TIME ZONE 'Asia/Ho_Chi_Minh'"
		nsx = "NULL" if b.get("nsx") is None else f"{hn} + {b['nsx']}"
		nhap = b["ton"] if b.get("nhap") is None else b["nhap"]
		i = uid(f"p4:{ma}:lo:{b['ma']}:{b['vung']}")
		return ("INSERT INTO batches (id, org_id, product_id, batch_code, expires_at, manufactured_at, location, qty_initial, qty_on_hand, "
			f"unit_cost, warehouse_zone, received_at, created_at) VALUES ('{i}', '{ORG}', {_id(b['sp'])}, {_lit(b['ma'])}, {han}, {nsx}, "
			f"{_t(b.get('vi_tri'))}, {nhap}, {b['ton']}, {b['gia']}, {_lit(b['vung'])}, {luc_nhan}, {luc_tao});")
	if k == "co_am":
		return f"UPDATE organizations SET allow_oversell = {str(b['bat']).lower()} WHERE id = '{ORG}';"
	if k == "nguong":
		return (f"INSERT INTO pricing_rules (org_id, date_warehouse_threshold_days) VALUES ('{ORG}', {b['ngay']}) ON CONFLICT (org_id) "
			"DO UPDATE SET date_warehouse_threshold_days = EXCLUDED.date_warehouse_threshold_days;")
	if k == "dong_lo":
		return f"UPDATE batches SET status = 'cancelled' WHERE id = {_id('@lo:' + b['lo'])};"
	if k == "may_chu":
		return f"EXECUTE public._vp4_sql({_lit(b['sql'])}, v_nhan);"
	if k == "doc_phien":
		return "SELECT jsonb_build_object('phien', phien) INTO v_tra FROM danh_muc_ban_phien WHERE id = 1;"
	if k == "kham_ncc":
		return "SELECT public._vp4_kham_ncc() INTO v_tra;"
	raise ValueError(f"bước lạ: {k}")


def _doc_sql(b: dict) -> str:
	ten, ts = b["ten"], b.get("ts") or {}

	def ngay(x):
		return "NULL::date" if ts.get(x) is None else f"{_lit(thuc(ts[x]))}::date"

	if ten == "payables_summary":
		q = (f"SELECT COALESCE(jsonb_agg(to_jsonb(r)), '[]'::jsonb) FROM public.payables_summary({_lit(thuc(ts['p_since']))}::timestamptz) r")
	elif ten == "payables_by_supplier":
		q = "SELECT COALESCE(jsonb_agg(to_jsonb(r)), '[]'::jsonb) FROM public.payables_by_supplier() r"
	elif ten == "so_chung_tu_ncc":
		q = f"SELECT public.so_chung_tu_ncc({_id(ts['p_supplier_id'])})"
	elif ten == "bao_cao_ton_kho":
		q = f"SELECT public.bao_cao_ton_kho({ngay('p_tu')}, {ngay('p_den')})"
	elif ten == "finance_pnl":
		q = f"SELECT COALESCE(jsonb_agg(to_jsonb(r)), '[]'::jsonb) FROM public.finance_pnl({ngay('p_from')}, {ngay('p_to')}) r"
	elif ten == "bao_cao_so_ban":
		q = f"SELECT public.bao_cao_so_ban({ngay('p_tu')}, {ngay('p_den')})"
	elif ten == "lo_theo_phieu_goc":
		# mô phỏng loadReceiptLinesForReturn (TS src/lib/pos/load.ts:312-350): lô của phiếu nhập gốc = batch_code LIKE '<receipt_code>-%'
		q = ("SELECT COALESCE(jsonb_agg(jsonb_build_object('product_id', b.product_id, 'batch_code', b.batch_code, 'expires_at', b.expires_at) "
			"ORDER BY b.batch_code, b.warehouse_zone), '[]'::jsonb) FROM batches b "
			f"WHERE b.batch_code LIKE (SELECT pi.receipt_code FROM purchase_invoices pi WHERE pi.id = {_id(ts['pn'])}) || '-%'")
	elif ten == "hoa_don_mua_con_no":
		# mô phỏng câu cổng của /purchasing/invoices tab "Còn nợ" + ô tìm (vùng ④, V77): stock_entries type import có dòng công nợ
		# chưa trả (debt:payables!inner(status) neq paid) và (mã phiếu / khoá tìm / số HĐ NCC của dòng nợ chứa chữ gõ)
		tu = _lit(ts["tim"])
		q = ("SELECT COALESCE(jsonb_agg(public._vp4_ma(e.entry_code) ORDER BY e.entry_code), '[]'::jsonb) FROM stock_entries e "
			"WHERE e.type = 'import' AND EXISTS (SELECT 1 FROM payables p WHERE p.stock_entry_id = e.id AND p.status <> 'paid') "
			f"AND (e.entry_code ILIKE '%' || {tu} || '%' OR e.tim_kd ILIKE '%' || lower({tu}) || '%' "
			f"OR e.id IN (SELECT p.stock_entry_id FROM payables p WHERE p.invoice_number ILIKE '%' || {tu} || '%'))")
	else:
		raise ValueError(f"RPC đọc lạ: {ten}")
	return f"{q} INTO v_tra;"


def _doc_bang_sql(b: dict) -> str:
	"""Đọc bảng / view qua RLS người gọi; trả mảng dòng (cột chọn), id → khoá ở bước chuẩn hoá."""
	bang = b["bang"]
	loc = b.get("loc") or {}
	cot = b.get("cot")
	dieu = " AND ".join(f"t.{c} = f.{c}" for c in loc) or "true"
	chon = "to_jsonb(t)" if not cot else "jsonb_build_object(" + ", ".join(f"'{c}', t.{c}" for c in cot) + ")"
	cau = (f"SELECT COALESCE(jsonb_agg({chon} ORDER BY {', '.join('t.' + c for c in (cot or ['ctid']))}), '[]'::jsonb) FROM {bang} t, "
		f"jsonb_populate_record(NULL::{bang}, $1) f WHERE {dieu}")
	return f"EXECUTE {_lit(cau)} INTO v_tra USING {_j(loc)};"


def _ban_sql(b: dict, ma: str) -> str:
	gia = {(sp, dv): g for sp, dv, g in GIA_BAN}
	dong = []
	for x in b["dong"]:
		g = gia[(x["product_id"][1:], x["unit_name"])]
		dong.append({"product_id": x["product_id"], "unit_name": x["unit_name"], "quantity": x["quantity"], "unit_price": g,
			"line_discount": 0, "line_total": x["quantity"] * g, "conversion_factor": 1, "vat_rate": 0})
	tong = sum(x["line_total"] for x in dong)
	p = {"client_request_id": uid(f"p4:{ma}:don:{b['nhan']}"), "order": {"order_code": "TAM-1", "customer_id": b["khach"],
		"payment_terms": "COD", "expected_delivery": None, "subtotal": tong, "vat": 0, "total": tong, "notes": None, "status": "submitted",
		"approval_reason": None, "sales_user_id": None}, "lines": dong, "returns": None, "return_lines": []}
	return (f"SELECT r.order_id INTO v_id FROM public.create_order_with_lines({_j(p)}) r; "
		"SELECT jsonb_agg(jsonb_build_object('order_line_id', l.id, 'product_id', l.product_id, 'unit_name', l.unit_name, "
		"'conversion_factor', l.conversion_factor, 'quantity', l.quantity, 'unit_price', l.unit_price, 'line_discount', l.line_discount, "
		"'vat_rate', l.vat_rate, 'is_exchange', false, 'note', l.note) ORDER BY l.ctid) INTO v_dong FROM sales_order_lines l "
		"WHERE l.order_id = v_id; "
		"SELECT to_jsonb(r) INTO v_tra FROM public.post_invoice(jsonb_build_object('order_id', v_id, 'lines', v_dong)) r; "
		+ _ghi_nhan("hd:" + b["nhan"], "v_tra->>'invoice_id'") + " " + _ghi_nhan("don:" + b["nhan"], "v_id"))


# Mốc giờ do hàm đặt bằng now() (= đầu giao dịch của CẢ bộ sinh, giống nhau ở mọi bước) → lùi về "now() - 5 phút + số bước ms" ngay sau
# bước: dòng của bước sau (mang now()) luôn MỚI hơn mọi dòng của bước trước, như production (mỗi lời gọi một giao dịch) — dồn trả trước
# theo ngày ghi nợ / lúc chi, FIFO theo ngày nhận, FEFO hoà hạn theo lúc tạo. (Dời TỚI giờ thật thì dòng của bước đang chạy lại "cũ" hơn
# dòng các bước trước — _don_tra_truoc_ncc trong trigger chọn nhầm khoản mới nhất.) Chạy trong 5 phút đầu ngày VN thì mốc lùi sang hôm trước.
_DOI_GIO = [("purchase_invoices", ["created_at", "completed_at", "cancelled_at"]), ("supplier_returns", ["created_at", "completed_at"]),
	("payables", ["created_at"]), ("supplier_payments", ["created_at", "cancelled_at"]), ("stock_entries", ["created_at", "posted_at"]),
	("batches", ["created_at", "received_at", "zone_moved_at"]), ("purchase_price_lists", ["updated_at"]),
	("expenses", ["created_at"]), ("sales_orders", ["created_at"]), ("sales_invoices", ["created_at"]), ("returns", ["created_at"]),
	("receivables", ["created_at"])]


def _sql_doi_gio() -> str:
	q = []
	for bang, cots in _DOI_GIO:
		sets = ", ".join(f"{c} = CASE WHEN {c} = now() THEN v_luc ELSE {c} END" for c in cots)
		dk_ = " OR ".join(f"{c} = now()" for c in cots)
		q.append(f"UPDATE {bang} SET {sets} WHERE org_id IN ('{ORG}', '{ORG_B}') AND ({dk_});")
	q.append("UPDATE payable_payments SET paid_at = v_luc WHERE paid_at = now();")
	q.append("UPDATE stock_line_consumptions SET created_at = v_luc WHERE created_at = now();")
	return "\n      ".join(q)


def _vai(nguoi: str) -> tuple[str, str]:
	"""(sub, câu đặt vai) của một người."""
	if nguoi == "MAY_CHU":
		return "", ""
	if nguoi == "HE_THONG":
		return "", "EXECUTE 'SET LOCAL ROLE service_role';"
	return uid("p4:u:" + nguoi), "EXECUTE 'SET LOCAL ROLE authenticated';"


def sql_tinh_huong(t: dict) -> str:
	khoi = []
	for so, b in enumerate(t["buoc"]):
		sub, vai = _vai(b["nguoi"])
		khoi.append(f"""
  IF NOT v_dung THEN
    BEGIN
      v_tra := NULL;
      EXECUTE 'SET CONSTRAINTS ALL DEFERRED';
      {DAT_LAI_CO}
      PERFORM set_config('request.jwt.claim.sub', {_lit(sub)}, true);
      {vai}
      {_lenh(b, t['ma'], so)}
      EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';
      EXECUTE 'RESET ROLE';
      EXECUTE 'SET LOCAL session_replication_role = replica';
      v_luc := now() - interval '5 minutes' + interval '{so + 1} milliseconds';
      {_sql_doi_gio()}
      EXECUTE 'SET LOCAL session_replication_role = origin';
      v_kq := v_kq || jsonb_build_array(jsonb_build_object('ok', true, 'tra', v_tra));
    EXCEPTION WHEN OTHERS THEN
      v_kq := v_kq || jsonb_build_array(jsonb_build_object('ok', false, 'ma_loi', SQLSTATE, 'loi', SQLERRM));
      v_dung := {'false' if b.get('tiep') else 'true'};
    END;
    EXECUTE 'RESET ROLE';
  END IF;""")
	return f"""
DO $c$
DECLARE
  v_tra jsonb; v_kq jsonb := '[]'::jsonb; v_dung boolean := false; v_n bigint; v_id uuid; v_dong jsonb; v_luc timestamptz;
  v_nhan jsonb := '{{}}'::jsonb; v_ct jsonb;
BEGIN
  BEGIN
    {''.join(khoi)}
    SELECT public._vp4_anh(v_nhan) INTO v_ct;
    v_ct := v_ct || jsonb_build_object('nhan', v_nhan);
    RAISE EXCEPTION USING ERRCODE = 'ZZ999';
  EXCEPTION WHEN SQLSTATE 'ZZ999' THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  INSERT INTO _vang_kq VALUES ({_lit(t['ma'])}, v_kq, v_ct);
END $c$;
"""


# ------------------------------------------------------------------------------------------------ SQL — nền + hàm phụ
def sql_nen() -> str:
	q = ["SET client_encoding = 'UTF8';", "SET TIME ZONE 'Asia/Ho_Chi_Minh';",
		"GRANT USAGE ON SCHEMA public, auth TO authenticated, service_role;",
		"GRANT ALL ON ALL TABLES IN SCHEMA public TO authenticated, service_role;",
		"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated, service_role;",
		f"INSERT INTO organizations (id, name, slug, allow_oversell) VALUES ('{ORG}', 'NPP A', 'p4-npp-a', false), "
		f"('{ORG_B}', 'NPP B', 'p4-npp-b', false);"]
	org = {"A": ORG, "B": ORG_B}
	for k, (vai, o) in NGUOI.items():
		i = uid("p4:u:" + k)
		q.append(f"INSERT INTO auth.users (id) VALUES ('{i}');")
		q.append(f"INSERT INTO users (id, org_id, full_name, role, is_active) VALUES ('{i}', '{org[o]}', '{k}', '{vai}', true);")
	for k, (ten, ma, o, them) in NCC.items():
		cols = ["id", "org_id", "name", "code", *them]
		vals = [f"'{uid('p4:ncc:' + k)}'", f"'{org[o]}'", _lit(ten), _t(ma), *[_lit(v) for v in them.values()]]
		q.append(f"INSERT INTO suppliers ({', '.join(cols)}) VALUES ({', '.join(vals)});")
	for k, (sku, ten, dv, han, dvs, ncc) in HANG.items():
		q.append("INSERT INTO products (id, org_id, sku, name, base_unit, shelf_life_days, primary_supplier_id) VALUES "
			f"('{uid('p4:sp:' + k)}', '{ORG}', '{sku}', {_lit(ten)}, {_lit(dv)}, {'NULL' if han is None else han}, "
			f"{'NULL' if ncc is None else _lit(uid('p4:ncc:' + ncc))});")
		for dvx, hs in dvs.items():
			q.append(f"INSERT INTO product_units (product_id, unit_name, conversion) VALUES ('{uid('p4:sp:' + k)}', {_lit(dvx)}, {hs});")
	for i, (k, ten) in enumerate(KHACH.items()):
		q.append("INSERT INTO customers (id, org_id, store_name, owner_name, phone, address) VALUES "
			f"('{uid('p4:kh:' + k)}', '{ORG}', {_lit(ten)}, 'Chu', '09440000{i + 1:02d}', 'Dia chi');")
	for sp, dv, g in GIA_BAN:
		q.append(f"INSERT INTO price_lists (product_id, group_id, unit_name, price) VALUES ('{uid('p4:sp:' + sp)}', NULL, {_lit(dv)}, {g});")
	for ma, ten, nhom in DANH_MUC_CP:
		q.append(f"INSERT INTO expense_categories (org_id, code, name, bucket) VALUES ('{ORG}', '{ma}', '{ten}', '{nhom}');")
	q.append("CREATE TEMP TABLE _vp4_ten (id uuid PRIMARY KEY, khoa text NOT NULL);")
	q.append("INSERT INTO _vp4_ten VALUES " + ", ".join(f"('{v}', {_lit(k)})" for k, v in KHOA_TINH.items()) + ";")
	q.append("GRANT SELECT ON _vp4_ten TO authenticated, service_role;")
	return "\n".join(q)


def sql_ham_phu() -> str:
	"""Hàm phụ (tạo trong giao dịch của bộ sinh, lui cùng ROLLBACK cuối): giải chỗ giữ + ảnh chụp theo khoá nghiệp vụ."""
	return f"""
CREATE OR REPLACE FUNCTION public._vp4_id(k text, p_nhan jsonb) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER AS $f$
DECLARE s text;
BEGIN
  IF k IS NULL THEN RETURN NULL; END IF;
  IF k ~ '^@(pn|ptn|pk|pc|hd|tk|don):[^:]+$' THEN RETURN (p_nhan->>substr(k, 2))::uuid; END IF;
  IF k LIKE '@pk:pn:%' THEN RETURN (SELECT stock_entry_id FROM purchase_invoices WHERE id = (p_nhan->>('pn:' || substr(k, 8)))::uuid); END IF;
  IF k LIKE '@pk:ptn:%' THEN RETURN (SELECT stock_entry_id FROM supplier_returns WHERE id = (p_nhan->>('ptn:' || substr(k, 9)))::uuid); END IF;
  IF k LIKE '@pk:hd:%' THEN RETURN (SELECT stock_entry_id FROM sales_invoices WHERE id = (p_nhan->>('hd:' || substr(k, 8)))::uuid); END IF;
  IF k LIKE '@pk:nl:%' THEN
    RETURN (SELECT id FROM stock_entries WHERE notes = 'Nhập lại từ phiếu trả ' || (p_nhan->>('tk:' || substr(k, 8)))
      ORDER BY created_at DESC LIMIT 1);
  END IF;
  IF k LIKE '@no:pn:%' THEN RETURN (SELECT payable_id FROM purchase_invoices WHERE id = (p_nhan->>('pn:' || substr(k, 8)))::uuid); END IF;
  IF k LIKE '@no:ptn:%' THEN RETURN (SELECT payable_credit_id FROM supplier_returns WHERE id = (p_nhan->>('ptn:' || substr(k, 9)))::uuid); END IF;
  IF k LIKE '@no:dk:%' THEN
    RETURN (SELECT p.id FROM payables p WHERE p.opening_balance AND p.supplier_id = (SELECT id FROM _vp4_ten WHERE khoa = '@' || substr(k, 8)));
  END IF;
  IF k LIKE '@no:ma:%' THEN
    RETURN (SELECT p.id FROM payables p WHERE p.org_id IN ('{ORG}', '{ORG_B}') AND p.invoice_number = substr(k, 8) ORDER BY p.created_at, p.id LIMIT 1);
  END IF;
  IF k LIKE '@no:pk:%' THEN RETURN (SELECT p.id FROM payables p WHERE p.stock_entry_id = (p_nhan->>('pk:' || substr(k, 8)))::uuid LIMIT 1); END IF;
  IF k LIKE '@no:tt:%' THEN RETURN (SELECT prepay_payable_id FROM supplier_payments WHERE id = (p_nhan->>('pc:' || substr(k, 8)))::uuid); END IF;
  IF k LIKE '@lo:%' THEN
    s := substr(k, 5);
    RETURN (SELECT b.id FROM batches b WHERE b.org_id IN ('{ORG}', '{ORG_B}') AND b.batch_code = split_part(s, '@', 1)
      AND (split_part(s, '@', 2) = '' OR b.warehouse_zone = split_part(s, '@', 2)) ORDER BY b.created_at, b.id LIMIT 1);
  END IF;
  RETURN (SELECT id FROM _vp4_ten WHERE khoa = k);
END $f$;
GRANT EXECUTE ON FUNCTION public._vp4_id(text, jsonb) TO authenticated, service_role;

CREATE OR REPLACE FUNCTION public._vp4_thay(p text, p_nhan jsonb) RETURNS text LANGUAGE plpgsql SECURITY DEFINER AS $f$
DECLARE v text := p; m text[];
BEGIN
  FOR m IN SELECT DISTINCT regexp_matches(p, '"(@[^"]+)"', 'g') LOOP
    v := replace(v, '"' || m[1] || '"', COALESCE(to_jsonb(public._vp4_id(m[1], p_nhan)::text)::text, 'null'));
  END LOOP;
  RETURN v;
END $f$;
GRANT EXECUTE ON FUNCTION public._vp4_thay(text, jsonb) TO authenticated, service_role;

CREATE OR REPLACE FUNCTION public._vp4_sql(p text, p_nhan jsonb) RETURNS text LANGUAGE plpgsql SECURITY DEFINER AS $f$
DECLARE v text := p; m text[];
BEGIN
  FOR m IN SELECT DISTINCT regexp_matches(p, '\\{{(@[^}}]+)\\}}', 'g') LOOP
    v := replace(v, '{{' || m[1] || '}}', quote_nullable(public._vp4_id(m[1], p_nhan)::text));
  END LOOP;
  RETURN v;
END $f$;

CREATE OR REPLACE FUNCTION public._vp4_k(p uuid) RETURNS text LANGUAGE sql STABLE AS $f$ SELECT khoa FROM _vp4_ten WHERE id = p $f$;

CREATE OR REPLACE FUNCTION public._vp4_ngay(d date) RETURNS text LANGUAGE sql STABLE AS $f$
  SELECT CASE WHEN d IS NULL THEN NULL WHEN d >= DATE '2099-01-01' OR abs(d - CURRENT_DATE) > 400 THEN d::text
    WHEN d = CURRENT_DATE THEN '@hom_nay' WHEN d > CURRENT_DATE THEN '@hom_nay+' || (d - CURRENT_DATE)
    ELSE '@hom_nay' || (d - CURRENT_DATE) END
$f$;

CREATE OR REPLACE FUNCTION public._vp4_luc(t timestamptz) RETURNS text LANGUAGE sql STABLE AS $f$
  SELECT CASE WHEN t IS NULL THEN NULL WHEN t >= now() - interval '10 minutes' THEN '@luc_goi'
    ELSE public._vp4_ngay((t AT TIME ZONE 'Asia/Ho_Chi_Minh')::date) || 'T' || to_char(t AT TIME ZONE 'Asia/Ho_Chi_Minh', 'HH24:MI') END
$f$;

CREATE OR REPLACE FUNCTION public._vp4_ma(c text) RETURNS text LANGUAGE sql IMMUTABLE AS $f$
  SELECT regexp_replace(c, '^(XK|NK|NL|TH)-[0-9]{{6}}-[0-9]{{6}}$', '\\1-<giờ>')
$f$;

CREATE OR REPLACE FUNCTION public._vp4_nhan(p_nhan jsonb, p_loai text, p uuid) RETURNS text LANGUAGE sql STABLE AS $f$
  SELECT substr(e.key, length(p_loai) + 2) FROM jsonb_each_text(p_nhan) e WHERE e.key LIKE p_loai || ':%' AND e.value = p::text LIMIT 1
$f$;

CREATE OR REPLACE FUNCTION public._vp4_ma_pk(p uuid) RETURNS text LANGUAGE sql STABLE AS $f$
  SELECT public._vp4_ma(e.entry_code) FROM stock_entries e WHERE e.id = p
$f$;

CREATE OR REPLACE FUNCTION public._vp4_lo(p uuid) RETURNS text LANGUAGE sql STABLE AS $f$
  SELECT b.batch_code || '@' || b.warehouse_zone FROM batches b WHERE b.id = p
$f$;

CREATE OR REPLACE FUNCTION public._vp4_khoa_no(p_id uuid) RETURNS text LANGUAGE sql STABLE AS $f$
  SELECT CASE
    WHEN EXISTS (SELECT 1 FROM purchase_invoices pi WHERE pi.payable_id = p.id)
      THEN 'PN:' || (SELECT COALESCE(pi.receipt_code, '?') FROM purchase_invoices pi WHERE pi.payable_id = p.id LIMIT 1)
    WHEN EXISTS (SELECT 1 FROM supplier_returns r WHERE r.payable_credit_id = p.id)
      THEN 'PTNCC:' || (SELECT COALESCE(r.return_code, '?') FROM supplier_returns r WHERE r.payable_credit_id = p.id LIMIT 1)
    WHEN p.opening_balance THEN 'DK:' || COALESCE(public._vp4_k(p.supplier_id), '?')
    WHEN EXISTS (SELECT 1 FROM supplier_payments s WHERE s.prepay_payable_id = p.id)
      THEN 'TT:' || (SELECT s.code FROM supplier_payments s WHERE s.prepay_payable_id = p.id LIMIT 1)
    WHEN p.stock_entry_id IS NOT NULL THEN 'PK:' || COALESCE(public._vp4_ma_pk(p.stock_entry_id), '?') || COALESCE(':' || p.invoice_number, '')
    ELSE 'TAY:' || COALESCE(p.invoice_number, '') END
  FROM payables p WHERE p.id = p_id
$f$;

CREATE OR REPLACE FUNCTION public._vp4_ghi_chu(t text) RETURNS text LANGUAGE sql STABLE AS $f$
  SELECT regexp_replace(t, '[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}', '<id>', 'g')
$f$;

CREATE OR REPLACE FUNCTION public._vp4_kham_ncc() RETURNS jsonb LANGUAGE sql STABLE AS $f$
  SELECT jsonb_build_object(
    'paid_lech', (SELECT count(*) FROM payables p WHERE p.org_id = '{ORG}'
      AND abs(COALESCE(p.paid, 0) - COALESCE((SELECT sum(x.amount) FROM payable_payments x WHERE x.payable_id = p.id), 0)) > 0.01),
    'phieu_chi_lech', (SELECT count(*) FROM supplier_payments s WHERE s.org_id = '{ORG}' AND s.status = 'posted'
      AND abs(s.amount - COALESCE((SELECT sum(x.amount) FROM payable_payments x WHERE x.supplier_payment_id = s.id), 0)) > 0.01),
    'luc_chi_lech', (SELECT count(*) FROM supplier_payments s WHERE s.org_id = '{ORG}' AND s.status = 'posted'
      AND (SELECT count(DISTINCT x.paid_at) FROM payable_payments x WHERE x.supplier_payment_id = s.id) > 1),
    'chi_vao_dong_am', (SELECT count(*) FROM payable_payments x JOIN payables p ON p.id = x.payable_id
      WHERE p.org_id = '{ORG}' AND p.amount < 0 AND x.supplier_payment_id IS NOT NULL))
$f$;

CREATE OR REPLACE FUNCTION public._vp4_anh(p_nhan jsonb) RETURNS jsonb LANGUAGE sql AS $f$
  SELECT jsonb_strip_nulls(jsonb_build_object(
    'pn', (SELECT jsonb_agg(jsonb_build_object(
        'nhan', public._vp4_nhan(p_nhan, 'pn', pi.id), 'ma', pi.receipt_code, 'status', pi.status, 'ncc', public._vp4_k(pi.supplier_id),
        'so_hd', pi.invoice_number, 'ngay', public._vp4_ngay(pi.invoice_date), 'vung', pi.warehouse_zone, 'subtotal', pi.subtotal,
        'vat', pi.vat, 'total', pi.total, 'giam', pi.discount, 'thue_tay', pi.vat_override, 'ghi_chu', pi.notes,
        'lap_boi', public._vp4_k(pi.created_by), 'luc_hoan_thanh', public._vp4_luc(pi.completed_at), 'luc_huy', public._vp4_luc(pi.cancelled_at),
        'huy_boi', public._vp4_k(pi.cancelled_by), 'ly_do_huy', pi.cancel_reason, 'phieu_kho', public._vp4_ma_pk(pi.stock_entry_id),
        'co_phieu_kho', pi.stock_entry_id IS NOT NULL, 'no', public._vp4_khoa_no(pi.payable_id),
        'dong', (SELECT jsonb_agg(jsonb_build_object('sp', public._vp4_k(l.product_id), 'dv', l.unit_name, 'sl', l.quantity, 'gia', l.unit_price,
            'giam', l.line_discount, 'thue', l.vat_rate, 'hs', l.conversion_factor, 'tien', l.line_total, 'ghi_chu', l.notes, 'stt', l.sort_order)
          ORDER BY l.sort_order, public._vp4_k(l.product_id), l.unit_name, l.quantity) FROM purchase_invoice_lines l WHERE l.invoice_id = pi.id)
      ) ORDER BY pi.created_at, pi.id) FROM purchase_invoices pi WHERE pi.org_id IN ('{ORG}', '{ORG_B}')),
    'ptn', (SELECT jsonb_agg(jsonb_build_object(
        'nhan', public._vp4_nhan(p_nhan, 'ptn', r.id), 'ma', r.return_code, 'seq', r.return_seq, 'ma_cu', r.return_code_cu,
        'npp', CASE WHEN r.org_id = '{ORG}' THEN 'A' ELSE 'B' END, 'ngay', public._vp4_ngay(r.return_date), 'ly_do', r.reason,
        'ghi_chu', r.notes, 'ncc', public._vp4_k(r.supplier_id), 'vung', r.warehouse_zone, 'subtotal', r.subtotal, 'vat', r.vat,
        'total', r.total, 'giam', r.discount, 'thue_tay', r.vat_override, 'status', r.status, 'phieu_kho', public._vp4_ma_pk(r.stock_entry_id),
        'no', public._vp4_khoa_no(r.payable_credit_id), 'luc_hoan_thanh', public._vp4_luc(r.completed_at),
        'hoan_thanh_boi', public._vp4_k(r.completed_by), 'lap_boi', public._vp4_k(r.created_by), 'ly_do_huy', r.cancel_reason,
        'dong', (SELECT jsonb_agg(jsonb_build_object('sp', public._vp4_k(l.product_id), 'dv', l.unit_name, 'sl', l.quantity, 'gia', l.unit_price,
            'giam', l.line_discount, 'thue', l.vat_rate, 'hs', l.conversion_factor, 'tien', l.line_total, 'ghi_chu', l.notes, 'stt', l.sort_order)
          ORDER BY l.sort_order, public._vp4_k(l.product_id), l.unit_name, l.quantity) FROM supplier_return_lines l WHERE l.return_id = r.id)
      ) ORDER BY r.org_id = '{ORG_B}', r.return_seq NULLS LAST, r.created_at, r.id) FROM supplier_returns r WHERE r.org_id IN ('{ORG}', '{ORG_B}')),
    'no', (SELECT jsonb_agg(jsonb_build_object(
        'khoa', public._vp4_khoa_no(p.id), 'ncc', public._vp4_k(p.supplier_id), 'so_hd', p.invoice_number, 'so_tien', p.amount,
        'da_tra', p.paid, 'status', p.status, 'han', public._vp4_ngay(p.due_date), 'ghi_chu', p.notes, 'dau_ky', p.opening_balance,
        'luc', public._vp4_luc(p.created_at), 'phieu_kho', public._vp4_ma_pk(p.stock_entry_id),
        'luc_bang_hoan_thanh', (SELECT pi.completed_at = p.created_at FROM purchase_invoices pi WHERE pi.payable_id = p.id LIMIT 1))
      ORDER BY public._vp4_khoa_no(p.id), p.amount, p.created_at) FROM payables p WHERE p.org_id = '{ORG}'),
    'tra_no', (SELECT jsonb_agg(jsonb_build_object(
        'no', public._vp4_khoa_no(x.payable_id), 'tien', x.amount, 'cach', x.method, 'boi', public._vp4_k(x.paid_by),
        'luc', public._vp4_luc(x.paid_at), 'ghi_chu', x.notes, 'phieu_chi', (SELECT s.code FROM supplier_payments s WHERE s.id = x.supplier_payment_id),
        'xac_nhan', x.verified_by IS NOT NULL)
      ORDER BY public._vp4_khoa_no(x.payable_id), x.paid_at, x.amount, x.notes) FROM payable_payments x JOIN payables p ON p.id = x.payable_id
      WHERE p.org_id = '{ORG}'),
    'phieu_chi', (SELECT jsonb_agg(jsonb_build_object(
        'nhan', public._vp4_nhan(p_nhan, 'pc', s.id), 'ma', s.code, 'seq', s.seq, 'ncc', public._vp4_k(s.supplier_id),
        'ngay', public._vp4_ngay(s.paid_date), 'tien', s.amount, 'cach', s.method, 'tham_chieu', s.reference_code, 'ghi_chu', s.notes,
        'status', s.status, 'tra_truoc', public._vp4_khoa_no(s.prepay_payable_id), 'lap_boi', public._vp4_k(s.created_by),
        'luc_huy', public._vp4_luc(s.cancelled_at), 'huy_boi', public._vp4_k(s.cancelled_by), 'ly_do_huy', s.cancel_reason,
        'luc_chi', (SELECT jsonb_agg(DISTINCT public._vp4_luc(x.paid_at)) FROM payable_payments x WHERE x.supplier_payment_id = s.id),
        'tong_dong', (SELECT sum(x.amount) FROM payable_payments x WHERE x.supplier_payment_id = s.id))
      ORDER BY s.seq) FROM supplier_payments s WHERE s.org_id = '{ORG}'),
    'phieu_kho', (SELECT jsonb_agg(jsonb_build_object(
        'nhan', public._vp4_nhan(p_nhan, 'pk', e.id), 'ma', public._vp4_ma(e.entry_code), 'loai', e.type, 'status', e.status,
        'vung', e.warehouse_zone, 'vung_dich', e.dest_warehouse_zone, 'ncc', public._vp4_k(e.supplier_id), 'ly_do_xuat', e.issue_reason,
        'ghi_chu', public._vp4_ghi_chu(e.notes), 'luc_ghi_so', public._vp4_luc(e.posted_at), 'lap_boi', public._vp4_k(e.created_by),
        'so_don', jsonb_array_length(e.ref_order_ids),
        'dong', (SELECT jsonb_agg(jsonb_build_object('sp', public._vp4_k(l.product_id), 'lo', public._vp4_lo(l.batch_id), 'dv', l.unit_name,
            'sl', l.quantity, 'sl_cs', l.qty_in_base_uom, 'sl_gd', l.qty_in_transaction_uom, 'dv_gd', l.transaction_uom,
            'hs', l.conversion_factor_snapshot, 'gia', l.unit_cost, 'ghi_chu', l.notes,
            'vet', (SELECT jsonb_agg(jsonb_build_object('lo', public._vp4_lo(c.batch_id), 'sl', c.qty_in_base_uom, 'gia', c.unit_cost)
                ORDER BY public._vp4_lo(c.batch_id), c.qty_in_base_uom) FROM stock_line_consumptions c WHERE c.line_id = l.id))
          ORDER BY public._vp4_k(l.product_id), public._vp4_lo(l.batch_id), l.qty_in_base_uom, l.unit_name) FROM stock_entry_lines l
          WHERE l.entry_id = e.id)
      ) ORDER BY e.created_at, e.entry_code, e.id) FROM stock_entries e WHERE e.org_id = '{ORG}'),
    'lo', (SELECT jsonb_agg(jsonb_build_object(
        'sp', public._vp4_k(b.product_id), 'ma', b.batch_code, 'vung', b.warehouse_zone, 'nhap', b.qty_initial, 'ton', b.qty_on_hand,
        'gia', b.unit_cost, 'status', b.status, 'han', public._vp4_ngay(b.expires_at), 'nsx', public._vp4_ngay(b.manufactured_at),
        'vi_tri', b.location, 'luc_nhan', public._vp4_luc(b.received_at), 'luc_chuyen_vung', public._vp4_luc(b.zone_moved_at),
        'chuyen_boi', public._vp4_k(b.zone_moved_by))
      ORDER BY public._vp4_k(b.product_id), b.batch_code, b.warehouse_zone, b.created_at) FROM batches b WHERE b.org_id = '{ORG}'),
    'gia_nhap', (SELECT jsonb_agg(jsonb_build_object(
        'sp', public._vp4_k(g.product_id), 'dv', g.unit_name, 'gia', g.price, 'ngay', public._vp4_ngay(g.effective_date),
        'nguon', (SELECT COALESCE(pi.receipt_code, public._vp4_nhan(p_nhan, 'pn', pi.id)) FROM purchase_invoices pi WHERE pi.id = g.source_invoice_id),
        'sua_boi', public._vp4_k(g.updated_by))
      ORDER BY public._vp4_k(g.product_id), g.unit_name) FROM purchase_price_lists g WHERE g.org_id = '{ORG}'),
    'chi_phi', (SELECT jsonb_agg(jsonb_build_object(
        'loai', (SELECT c.code FROM expense_categories c WHERE c.id = x.category_id), 'ngay', public._vp4_ngay(x.expense_date),
        'tien', x.amount, 'mo_ta', x.description, 'tham_chieu', x.reference_code, 'nguon', x.source_type,
        'nguon_pk', public._vp4_ma_pk(x.source_id), 'da_tra', x.is_paid, 'lap_boi', public._vp4_k(x.created_by))
      ORDER BY x.created_at, x.reference_code) FROM expenses x WHERE x.org_id = '{ORG}'),
    'ncc', (SELECT jsonb_agg(jsonb_build_object(
        'khoa', public._vp4_k(s.id), 'ten', s.name, 'ma', s.code, 'phone', s.phone, 'email', s.email, 'tax_code', s.tax_code,
        'ghi_chu', s.notes, 'dang_lam', s.is_active, 'lap_boi', public._vp4_k(s.created_by))
      ORDER BY s.name) FROM suppliers s WHERE s.org_id = '{ORG}'),
    'phan_cong', (SELECT jsonb_agg(jsonb_build_array(public._vp4_k(u.user_id), public._vp4_k(u.supplier_id))
      ORDER BY public._vp4_k(u.user_id), public._vp4_k(u.supplier_id)) FROM user_suppliers u WHERE u.org_id = '{ORG}'),
    'hang', (SELECT jsonb_agg(jsonb_build_object('khoa', public._vp4_k(p.id), 'status', p.status, 'ncc', public._vp4_k(p.primary_supplier_id))
      ORDER BY p.sku) FROM products p WHERE p.org_id = '{ORG}'),
    'hd', (SELECT jsonb_agg(jsonb_build_object('nhan', public._vp4_nhan(p_nhan, 'hd', si.id), 'ma', si.invoice_code, 'status', si.status,
        'total', si.total, 'phieu_kho', public._vp4_ma_pk(si.stock_entry_id)) ORDER BY si.invoice_seq, si.reissue_no)
      FROM sales_invoices si WHERE si.org_id = '{ORG}'),
    'tra_khach', (SELECT jsonb_agg(jsonb_build_object('nhan', public._vp4_nhan(p_nhan, 'tk', x.id), 'ma', x.return_code, 'status', x.status,
        'tien', x.credit_note_amount) ORDER BY x.return_seq) FROM returns x WHERE x.org_id = '{ORG}'),
    'id_khoa', (SELECT jsonb_object_agg(i, k) FROM (
        SELECT pi.id::text AS i, 'pn:' || COALESCE(public._vp4_nhan(p_nhan, 'pn', pi.id), pi.receipt_code, '?') AS k FROM purchase_invoices pi
          WHERE pi.org_id IN ('{ORG}', '{ORG_B}')
        UNION ALL SELECT r.id::text, 'ptn:' || COALESCE(public._vp4_nhan(p_nhan, 'ptn', r.id), r.return_code, '?') FROM supplier_returns r
          WHERE r.org_id IN ('{ORG}', '{ORG_B}')
        UNION ALL SELECT p.id::text, 'no:' || public._vp4_khoa_no(p.id) FROM payables p WHERE p.org_id IN ('{ORG}', '{ORG_B}')
        UNION ALL SELECT x.id::text, 'tra:' || public._vp4_khoa_no(x.payable_id) FROM payable_payments x JOIN payables p ON p.id = x.payable_id
          WHERE p.org_id IN ('{ORG}', '{ORG_B}')
        UNION ALL SELECT e.id::text, 'pk:' || COALESCE(public._vp4_nhan(p_nhan, 'pk', e.id), public._vp4_ma(e.entry_code)) FROM stock_entries e
          WHERE e.org_id IN ('{ORG}', '{ORG_B}')
        UNION ALL SELECT b.id::text, 'lo:' || b.batch_code || '@' || b.warehouse_zone FROM batches b WHERE b.org_id IN ('{ORG}', '{ORG_B}')
        UNION ALL SELECT s.id::text, 'pc:' || s.code FROM supplier_payments s WHERE s.org_id IN ('{ORG}', '{ORG_B}')
        UNION ALL SELECT x.id::text, 'cp:' || COALESCE(x.reference_code, '?') FROM expenses x WHERE x.org_id IN ('{ORG}', '{ORG_B}')
        UNION ALL SELECT si.id::text, 'hd:' || COALESCE(public._vp4_nhan(p_nhan, 'hd', si.id), si.invoice_code) FROM sales_invoices si
          WHERE si.org_id IN ('{ORG}', '{ORG_B}')
        UNION ALL SELECT x.id::text, 'tk:' || COALESCE(public._vp4_nhan(p_nhan, 'tk', x.id), x.return_code) FROM returns x
          WHERE x.org_id IN ('{ORG}', '{ORG_B}')
        UNION ALL SELECT t.id::text, t.khoa FROM _vp4_ten t) z)
  ))
$f$;
"""


# ------------------------------------------------------------------------------------------------ kịch bản (đặc tả §6)
def np(b: dict) -> dict:
	"""Bước CHỈ chạy phía nppsale (NPP thứ hai / dữ liệu cũ) — bản Frappe bỏ qua bước này và kết quả của nó."""
	return dict(b, chi_nppsale=True)


def _phang(x):
	return [y for z in x for y in _phang(z)] if isinstance(x, (list, tuple)) else [x]


LO_M = [lo("L-B1", "@M", "date", 10, 1000, han=15, nhan=-46), lo("L-B2", "@M", "date", 5, 1200, han=4, nhan=-42),
	lo("L-B3", "@M", "sale", 100, 900, han=197, nhan=-76), lo("L-B4", "@B", "date", 3, 500, han=197, nhan=-76)]


def LO_P(a=10, b=5, c=20):
	"""Lô dựng sẵn vùng ③ (hàng P): L-A kho bán hạn +200 nhận -40 giá 8.000; L-B kho bán hạn +100 nhận -10 giá 9.000; L-C hạn +10 giá 7.000
	(chèn kho bán → trigger đẩy sang date). None = không dựng lô ấy."""
	r = []
	if a is not None:
		r.append(lo("L-A", "@P", "sale", a, 8000, han=200, nhan=-40))
	if b is not None:
		r.append(lo("L-B", "@P", "sale", b, 9000, han=100, nhan=-10))
	if c is not None:
		r.append(lo("L-C", "@P", "sale", c, 7000, han=10, nhan=-50))
	return r


P1_DONG = [d("@A", "thùng", 2, 240000, hs=24)]
V01 = [pn("TK", "P", "@S1", P1_DONG, so_hd="HD-NCC-1", ngay="@hom_nay-46"), pn_hoan("TK", "P")]
V29 = [pn("TK", "PA", "@S1", [d("@A", "hộp", 20, 10000)]), pn_hoan("TK", "PA"),
	pn("TK", "PB", "@S1", [d("@A", "hộp", 30, 10000)]), pn_hoan("TK", "PB"),
	ghi("KT", "payables", "insert", {"org_id": "@org", "supplier_id": "@S1", "amount": 100000, "paid": 0, "status": "open",
		"opening_balance": True, "notes": "Nợ đầu kỳ"}),
	ghi("KT", "payables", "insert", {"org_id": "@org", "supplier_id": "@S1", "amount": 5, "paid": 0, "status": "open",
		"opening_balance": True}, tiep=True),
	ptn("TK", "R", "@S1", [d("@A", "hộp", 5, 10000)], vung="sale"), ptn_gui("TK", "R"),
	chi("KT", "C1", "@S1", 250000, None, "cash", "  trả đợt 1 ", " REF1 ")]
V30 = [*V29, chi("KT", "C2", "@S1", 600000, "@hom_nay-6", "transfer"), doc("KT", "payables_summary", p_since="@hom_nay-300"),
	doc("KT", "payables_by_supplier")]
V31 = [*V30, ghi("KT", "payables", "insert", {"org_id": "@org", "supplier_id": "@S1", "invoice_number": "LAP-TAY", "amount": 100000,
	"paid": 0, "status": "open"})]
V32 = [*V31, huy_chi("KT", "C2", "  nhầm  "), huy_chi("KT", "C2", "  nhầm  "), doc("KT", "so_chung_tu_ncc", p_supplier_id="@S1")]
V33 = [chi("KT", "C21", "@S2", 30000, "@hom_nay-4", "cash"), chi("KT", "C22", "@S2", 20000, "@hom_nay-5", "transfer"),
	ghi("KT", "payables", "insert", {"org_id": "@org", "supplier_id": "@S2", "invoice_number": "N1", "amount": 25000, "paid": 0, "status": "open"}),
	huy_chi("KT", "C22")]
BAN30 = ban("CHU", "H1", [("@A", "hộp", 30)])
V65_NEN = [*V01, BAN30, ghi_tra("KT", "@no:pn:P", 100000, "transfer")]
DAU65 = {"supplier_id": "@S1", "invoice_number": "HD-NCC-9", "invoice_date": "@hom_nay-46", "warehouse_zone": "sale", "discount": 0,
	"vat_override": None, "notes": "sửa giá"}
V65 = [*V65_NEN, pn_sua("KT", "P", DAU65, [d("@A", "thùng", 2, 264000, hs=24)])]
V47 = [lo("L-A", "@P", "sale", 10, 8000, han=200, nhan=-40, vi_tri="Ke 1"), lo("L-C", "@P", "sale", 20, 7000, han=10, nhan=-50), co_am(),
	pk("TK", "CKL-1", "transfer", "sale", [dk("@P", 4)], dich="date"), chuyen("TK", "CKL-1"),
	pk("TK", "CKL-2", "transfer", "sale", [dk("@P", 3)], dich="date"), chuyen("TK", "CKL-2")]
V52 = [nhap_kho("TK", "IN-B", {"entry_code": "IN-B", "warehouse_zone": "sale", "lines": [{"product_id": "@G", "unit_name": "Kg", "qty_tx": 10,
	"conv": 1, "base_qty": 10, "base_cost": 20000, "batch_code": "G-1", "expires_at": "@hom_nay+120"}]}),
	pk("TK", "CKL-B", "transfer", "sale", [dk("@G", 4)], dich="date"), chuyen("TK", "CKL-B")]
V61 = [*LO_P(10, 5, None),
	pk("TK", "KK-1", "stocktake", None, [dk("@P", -12, lo="@lo:L-A", gia=8000)]), pk("TK", "KK-2", "stocktake", None, [dk("@P", -16)]),
	pk("TK", "KK-3", "stocktake", None, [dk("@Q", 4)]), pk("TK", "KK-4", "stocktake", None, [dk("@Q", -4)]),
	kk_duyet("CHU", "KK-1", tiep=True), kk_duyet("CHU", "KK-2", tiep=True), kk_duyet("CHU", "KK-3", tiep=True), kk_duyet("CHU", "KK-4", tiep=True)]


def _no(ncc, so, **k):
	return {"org_id": "@org", "supplier_id": ncc, "invoice_number": so, "paid": 0, "status": "open", **k}


def tinh_huong() -> list[dict]:
	T: list[dict] = []

	def th(ma, ten, *buoc, **o):
		T.append({"ma": ma, "ten": ten, "buoc": _phang(buoc), **o})

	def fr(ma, ten, mo_ta, mong, *buoc):
		"""Kịch bản [Frappe] — không chạy phía nppsale: bước (cùng bộ từ vựng; "@X" = hàng không lô chỉ có ở bản Frappe — nen.hang_frappe)
		+ "mong" chép từ đặc tả."""
		T.append({"ma": ma, "ten": ten, "nguon": "dac_ta", "buoc": _phang(buoc), "mo_ta": mo_ta, "mong": {"dac_ta": mong}})

	# ============================================================ §6.1 M1 — phiếu nhập
	th("V01", "Nháp → hoàn thành, một dòng thùng x24", *V01,
		khac_frappe=["⚠K mã PN- cấp lúc lập nháp (câu 18)", "⚠K phiếu kho = chính PI (không stock_entries riêng)",
			"hạn lô trống → cổng trả 2099-12-31 (CFD-10)", "❓ §7.3 ghi chú công nợ lấy npp_ghi_chu"])
	th("V02", "Bấm Hoàn thành lần hai · đánh số PN", *V01, pn_hoan("TK", "P"),
		pn("TK", "Q", "@S1", [d("@B", "gói", 10, 5000)]),
		pn("TK", "R", "@S1", [d("@B", "gói", 5, 5000)]), pn_hoan("TK", "R"), pn_huy("TK", "R", "x"),
		pn("TK", "T", "@S1", [d("@B", "gói", 3, 5000)]), pn_hoan("TK", "T"),
		khac_frappe=["⚠K câu 18: Q mang PN-0002 ngay lúc lập, R PN-0003, T PN-0004 (nppsale: Q chưa mã, R PN-0002, T PN-0003)"])
	th("V02b", "Mã PN sau PN-9999 là PN-10000 (không cắt khi > 9999)", pn("TK", "Z", "@S1", [d("@B", "gói", 1, 5000)]),
		may_chu("UPDATE purchase_invoices SET receipt_code = 'PN-9999' WHERE id = {@pn:Z}", "phiếu tạm Z mang sẵn mã PN-9999 (dữ liệu cũ)"),
		pn("TK", "P", "@S1", [d("@B", "gói", 2, 5000)]), pn_hoan("TK", "P"), chi_nppsale=True)
	fr("V02c", "Hai tiến trình cùng Hoàn thành một phiếu nháp", "Hai lượt complete_purchase_invoice song song trên cùng một PI nháp.",
		"Đúng một lần nhập kho / một bộ lô / một dòng NPP Cong No NCC; lượt sau (chờ khoá PI FOR UPDATE) thấy docstatus 1 → trả tên PI. "
		"⚠K có lợi: nppsale đọc không khoá nên có thể nhập hai lần (suy từ mã, chưa chạy).",
		pn("TK", "P", "@S1", P1_DONG), _b("song_song", "TK", lenh=[pn_hoan("TK", "P"), pn_hoan("TK", "P")]))
	th("V03", "Nhiều đơn vị quy đổi + SL lẻ", pn("TK", "P", "@S1", [d("@D", "thùng", 2, 216000, giam=12000, hs=24), d("@D", "lốc", 3, 54000, hs=6),
		d("@D", "lon", 5, 9500), d("@K", "kg", 2.5, 30000)], ngay="@hom_nay-45"), pn_hoan("TK", "P"),
		khac_frappe=["⚠K cổng stock_entry_lines.quantity = SL giao dịch (2/3/5/2.5) — nppsale ROUND(SL cơ sở) 48/18/5/3; so qty_in_base_uom"])
	L4 = [d("@A", "hộp", 10, 11000, giam=10000, thue=0.08), d("@B", "gói", 5, 7000, thue=0.1)]
	th("V04", "Giảm dòng + VAT dòng + giảm đầu phiếu (màn máy tính)", pn("TK", "P", "@S1", L4, giam=5000), pn_hoan("TK", "P"),
		khac_frappe=["Frappe: hai dòng VAT + một dòng Actual Deduct 5.000 (Total), grand_total 141500"])
	th("V05a", "Thuế gõ tay 11.000", pn("TK", "P", "@S1", L4, giam=5000, thue_tay=11000), pn_hoan("TK", "P"))
	th("V05b", "Thuế gõ tay 0 = không thuế (khác NULL)", pn("TK", "P", "@S1", L4, giam=5000, thue_tay=0), pn_hoan("TK", "P"))
	th("V05c", "Thuế gõ tay âm (ghi khi còn nháp) → kẹp 0", pn("TK", "P", "@S1", L4, giam=5000, thue_tay=-500), pn_hoan("TK", "P"))
	th("V05d", "Giảm đầu phiếu lớn hơn tiền → tổng kẹp 0", pn("TK", "P", "@S1", [d("@A", "hộp", 10, 10000, thue=0.1)], giam=200000,
		thue_tay=7000), pn_hoan("TK", "P"),
		khac_frappe=["Frappe: dòng Deduct kẹp còn 107.000 (lõi từ chối grand_total < 0), nợ 0 (❓ nppsale vẫn ghi dòng nợ amount 0)"])
	th("V06a", "POS: thuế 10 % cấp phiếu + giảm đầu phiếu", pn("CHU", "P", "@S1", P1_DONG, giam=30000, thue_tay=45000,
		xem={"subtotal": 450000, "vat": 45000, "total": 495000}), pn_hoan("CHU", "P"))
	th("V06b", "Màn máy tính cùng số liệu, VAT dòng 0,1", pn("CHU", "P", "@S1", [d("@A", "thùng", 2, 240000, hs=24, thue=0.1)], giam=30000),
		pn_hoan("CHU", "P"))
	th("V07", "Hạn ngắn vào kho bán → kho date; phiếu chọn kho date",
		pn("TK", "P1", "@S1", [d("@C", "chai", 10, 15000), d("@D", "lon", 6, 9000)]), pn_hoan("TK", "P1"),
		pn("TK", "P2", "@S1", [d("@D", "thùng", 1, 216000, hs=24)], vung="date"), pn_hoan("TK", "P2"),
		khac_frappe=["Frappe: dòng PI hàng C vào kho_can_date, set_warehouse vẫn kho bán; zone_moved_at trống"])
	th("V07c", "Biên ngưỡng: hạn = đúng ngưỡng → date", nguong(20), pn("TK", "P", "@S1", [d("@C", "chai", 1, 15000)]), pn_hoan("TK", "P"))
	th("V07d", "Biên ngưỡng: hạn = ngưỡng + 1 → kho bán", nguong(19), pn("TK", "P", "@S1", [d("@C", "chai", 1, 15000)]), pn_hoan("TK", "P"))
	th("V08a", "Hoàn thành phiếu không dòng", pn("TK", "P", "@S1", []), pn_hoan("TK", "P"))
	th("V08b", "Dòng thứ 2 SL 0 → lỗi, không tiêu số PN", pn("TK", "P", "@S1", [d("@A", "hộp", 10, 10000), d("@B", "gói", 0, 5000)]),
		pn_hoan("TK", "P", tiep=True), pn("TK", "Q", "@S1", [d("@B", "gói", 1, 5000)]), pn_hoan("TK", "Q"),
		khac_frappe=["❓ Frappe: lõi có nhận dòng qty 0 khi lưu nháp không — §4.2; Frappe số PN đã cấp lúc lập nháp"])
	th("V08c", "Hoàn thành phiếu đã huỷ", pn("TK", "P", "@S1", [d("@B", "gói", 1, 5000)]), pn_huy("TK", "P"), pn_hoan("TK", "P"))
	th("V08d", "NVBH hoàn thành phiếu nhập", pn("TK", "P", "@S1", [d("@B", "gói", 1, 5000)]), pn_hoan("NV", "P"))
	th("V08e", "Chủ NPP khác hoàn thành", pn("TK", "P", "@S1", [d("@B", "gói", 1, 5000)]), pn_hoan("CHU_B", "P"), chi_nppsale=True)
	V09 = [pn("TK", "Q", "@S1", [d("@B", "gói", 10, 5000)]), pn_huy("TK", "Q"), pn_huy("TK", "Q")]
	th("V09", "Huỷ phiếu tạm (hai lần)", *V09, khac_frappe=["⚠K Frappe nháp có mã PN — §7.3 điểm 1 giữ nháp mang dấu huỷ"])
	th("V10", "Huỷ phiếu hoàn thành, hàng chưa động", *V01, pn_huy("TK", "P", "x"),
		khac_frappe=["Frappe: PI docstatus 2, gói lô đảo, dòng NPP Cong No NCC xoá; Batch không có trạng thái cancelled (⚠K)",
			"(S9) cổng batches sau huỷ: dòng 'lô chưa phát sinh' PN-0001-001::<vùng npp_kho_tao> qty_initial 0 / unit_cost npp_gia_von_lo_rong "
			"— nppsale qty_initial 48 / status cancelled / unit_cost 10000 (⚠K nếu không theo đề xuất §3.1 bước 4)"])
	th("V11", "Huỷ khi đã xuất, không cho tồn âm", *V01, BAN30, pn_huy("TK", "P"))
	th("V12", "Huỷ khi đã xuất, NPP cho tồn âm; rồi huỷ HĐ", *V01, co_am(), BAN30, pn_huy("TK", "P"), huy_hd("CHU", "H1"),
		khac_frappe=["⚠K Frappe hàng THEO LÔ vẫn HANG_DA_XUAT (CFD-05 B) — xem V12b cho hàng không lô X"])
	fr("V12b", "Huỷ PN hàng không lô X khi đã bán, cho tồn âm",
		"Như V12 với mặt hàng X (has_batch_no 0, allow_negative_stock 1), NPP Cai Dat.cho_ban_vuot_ton = 1: PN 48 cái → bán 30 → huỷ PN → huỷ HĐ.",
		"Huỷ PN được, Bin kho bán -30; huỷ HĐ → Bin 0 (câu 15, mig 238).",
		co_am(), pn("TK", "P", "@S1", [d("@X", "cai", 48, 10000)]), pn_hoan("TK", "P"), ban("CHU", "H1", [("@X", "cai", 30)]),
		pn_huy("TK", "P"), huy_hd("CHU", "H1"))
	th("V13", "Khôi phục phiếu đã hoàn thành rồi huỷ (hai lần, huỷ lại, khôi phục lại)", *V01, pn_huy("TK", "P", "x"),
		pn_khoi_phuc("TK", "P"), pn_khoi_phuc("TK", "P"), pn_huy("TK", "P", "x"), pn_khoi_phuc("TK", "P"),
		khac_frappe=["⚠K Frappe id = PN-0001-1 (tờ amend), nhập vào đúng Batch cũ, tao_luc = npp_hoan_thanh_luc gốc"])
	th("V13b", "Khôi phục sau huỷ khi lô âm (cho tồn âm)", *V01, co_am(), BAN30, pn_huy("TK", "P", "x"), pn_khoi_phuc("TK", "P"),
		chi_nppsale=True)
	th("V14a", "Khôi phục phiếu huỷ lúc tạm", *V09, pn_khoi_phuc("TK", "Q"))
	th("V14b", "Khôi phục khi phiếu kho không ở trạng thái huỷ", pn("TK", "T", "@S1", [d("@B", "gói", 2, 5000)]), pn_hoan("TK", "T"),
		pn_huy("TK", "T", "x"), may_chu("UPDATE stock_entries SET status = 'posted' WHERE id = {@pk:pn:T}", "phiếu kho của T đặt lại posted"),
		pn_khoi_phuc("TK", "T"), chi_nppsale=True)
	th("V14c", "Khôi phục phiếu luồng sửa cũ (dòng lệch lô) → về nháp", pn("TK", "R", "@S1", [d("@B", "gói", 5, 5000)]), pn_hoan("TK", "R"),
		pn_huy("TK", "R", "x"), ghi("TK", "purchase_invoices", "update", {"status": "draft"}, {"id": "@pn:R"}),
		ghi("TK", "purchase_invoice_lines", "update", {"quantity": 7}, {"invoice_id": "@pn:R"}), pn_huy("TK", "R", "y"),
		pn_khoi_phuc("TK", "R"), chi_nppsale=True)
	th("V14d", "NVBH khôi phục phiếu nhập", *V01, pn_huy("TK", "P", "x"), pn_khoi_phuc("NV", "P"))
	th("V14e", "Chủ NPP khác khôi phục", *V01, pn_huy("TK", "P", "x"), pn_khoi_phuc("CHU_B", "P"), chi_nppsale=True)
	xem_gia = doc_bang("KT", "purchase_price_lists", cot=["product_id", "unit_name", "price", "effective_date", "source_invoice_id"])
	V15 = [pn("TK", "P1", "@S1", [d("@A", "hộp", 10, 10000), d("@A", "thùng", 1, 230000, hs=24), d("@A", "hộp", 2, 0)], ngay="@hom_nay-46"),
		pn_hoan("TK", "P1"), xem_gia,
		pn("TK", "P2", "@S1", [d("@A", "hộp", 5, 11000)], ngay="@hom_nay-42"), pn_hoan("TK", "P2"), xem_gia,
		pn("TK", "P0", "@S1", [d("@A", "hộp", 5, 9000)], ngay="@hom_nay-57"), pn_hoan("TK", "P0"), xem_gia,
		pn("TK", "P3", "@S1", [d("@B", "gói", 10, 5000), d("@B", "gói", 5, 4800)], ngay="@hom_nay-42"), pn_hoan("TK", "P3")]
	th("V15", "Bảng giá nhập ghi từ phiếu", *V15,
		khac_frappe=["Frappe: MỘT Item Price mỗi (mặt hàng, ĐV) trên 'Gia nhap', valid_from = ngày phiếu, reference = PN"])
	th("V16", "Sửa tay bảng giá nhập", *V15, gia("KT", [("@A", "thùng", 240000)]), gia("KT", [("@A", "hộp", 12000)]),
		pn_huy("KT", "P2"), pn_khoi_phuc("KT", "P2"), xem_gia,
		gia("KT", [("@A", "lốc", 1)], tiep=True), gia("KT", [("@A", "hộp", -5)], tiep=True), gia("KT", [("@A", "hộp", "abc")], tiep=True),
		gia("KT", [("@A", "thùng", None)]), gia("KT", [("@A", "hộp", 12345.6)]), gia("NV", [("@A", "hộp", 1)], tiep=True),
		dem("NV", "purchase_price_lists"), gia("KT", None, tiep=True), gia("KT", []),
		khac_frappe=["Frappe khôi phục P2 = amend PN-0002-1 — giá ngày cũ không đè"])

	# ============================================================ §6.2 M2 — trả hàng NCC
	R17 = ptn("TK", "R", "@S1", [d("@M", "thùng", 0.5, 240000, giam=10000, thue=0.1, hs=24), d("@B", "gói", 2, 5000, thue=0.08)], vung="date",
		giam=1000, ma="GO-TAY-BI-DE", xem={"subtotal": 999999, "vat": 999999, "total": 999999})
	th("V17", "Gửi phiếu trả — FEFO kho date, tiền tính lại, nợ âm (gọi hai lần)", *LO_M, R17, ptn_gui("TK", "R"), ptn_gui("TK", "R"),
		khac_frappe=["⚠K cổng Frappe 2 dòng PI (so theo mặt hàng, lô sau quy đổi); nppsale một dòng phiếu kho mỗi lô lấy, unit_name thùng mà SL là hộp"])
	th("V17b", "Lô hết hạn (hôm qua) ở kho date lấy trước", *LO_M, lo("L-HH", "@M", "date", 2, 800, han=-1, nhan=-100), R17, ptn_gui("TK", "R"))
	V18 = [*LO_M, ptn("KT", "R", "@S1", [d("@M", "hộp", 20, 1000)]), ptn_gui("KT", "R", tiep=True),
		ptn_dong("KT", "R", [d("@N", "thùng", 1.5, 10000, hs=10)]), ptn_gui("KT", "R")]
	th("V18", "Thiếu tồn — câu INSUFFICIENT_STOCK nguyên văn", *V18)
	th("V19", "Bật bán vượt tồn: gửi được (dòng không lô) rồi huỷ", co_am(), *LO_M, ptn("KT", "R", "@S1", [d("@M", "hộp", 20, 1000)]),
		ptn_gui("KT", "R"), ptn_huy("KT", "R", "thử"),
		khac_frappe=["⚠K Frappe hàng theo lô → như V18 (INSUFFICIENT_STOCK) — xem V19b cho hàng không lô"])
	fr("V19b", "Trả NCC hàng không lô X khi cho tồn âm",
		"cho_ban_vuot_ton = 1, X có allow_negative_stock: kho date X còn 15; PTNCC X 20 cái → gửi → huỷ.",
		"Gửi được, Bin kho date -5 (giá phần âm do lõi định — §2.6); huỷ hoàn đủ Bin về 15.",
		co_am(), nhap_kho("TK", "INX", {"entry_code": "IN-X-1", "warehouse_zone": "date", "lines": [{"product_id": "@X", "unit_name": "cai",
			"qty_tx": 15, "conv": 1, "base_qty": 15, "base_cost": 1000}]}),
		ptn("KT", "R", "@S1", [d("@X", "cai", 20, 1000)]), ptn_gui("KT", "R"), ptn_huy("KT", "R", "thử"))
	V20 = [*LO_M, ptn("QL", "R", "@S1", [d("@M", "hộp", 10, 1000), d("@M", "hộp", 5, 1000)], vung="sale"), ptn_gui("QL", "R"),
		dong_lo("L-B3"), ptn_huy("QL", "R", "gửi nhầm"), ptn_huy("QL", "R", "lần 2")]
	th("V20", "Huỷ phiếu đã gửi: hai dòng cùng lô, lô đóng mở lại; huỷ lần hai", *V20,
		khac_frappe=["❓ Frappe: lõi có chặn hoàn vào lô disabled — §3.8 bước 4 (bật lại lô trước khi huỷ)"])
	V21 = [*V20, ptn_khoi_phuc("QL", "R"), ptn_khoi_phuc("QL", "R")]
	th("V21", "Khôi phục phiếu từng gửi (hai lần)", *V21, khac_frappe=["⚠K Frappe id = PTNCC-0001-1"])
	V22 = [*V21, ptn_huy("QL", "R", "huỷ để thử"), pk("TK", "X1", "export", "sale", [dk("@M", 93)], ly_do_xuat="damaged"), xuat_le("TK", "X1"),
		ptn_khoi_phuc("QL", "R")]
	th("V22", "Khôi phục khi kho không đủ → dừng ở Nháp kèm lý do", *V22, khac_frappe=["Frappe: tờ amend -n ở nháp giữ lại, id = tờ ấy"])
	V23a = [*V22, ptn_huy("QL", "R", "huỷ nháp"), ptn_khoi_phuc("QL", "R")]
	th("V23a", "Dữ liệu cũ: nháp trỏ phiếu kho cũ — huỷ nháp rồi khôi phục thử gửi lại", *V23a, chi_nppsale=True)
	th("V23b", "Dòng đã đổi sau khi huỷ → khôi phục về nháp (không gửi)", *V23a, huy_pk("TK", "X1", "tra lai"), ptn_huy("QL", "R", "z"),
		ghi("QL", "supplier_return_lines", "update", {"quantity": 6}, {"return_id": "@ptn:R", "sort_order": 2}), ptn_khoi_phuc("QL", "R"),
		chi_nppsale=True)
	th("V23c", "Phiếu đã gửi bị đặt thẳng cancelled → PHIEU_KHO_LECH", *LO_M, ptn("TK", "R", "@S1", [d("@M", "hộp", 2, 1000)]),
		ptn_gui("TK", "R"), ghi("TK", "supplier_returns", "update", {"status": "cancelled"}, {"id": "@ptn:R"}), ptn_khoi_phuc("TK", "R"),
		chi_nppsale=True)
	th("V24", "Quyền / trạng thái ở ba RPC phiếu trả", *LO_M, ptn("KT", "R", "@S1", [d("@M", "hộp", 1, 1000)]),
		ptn_khoi_phuc("NV", "R", tiep=True), ptn_huy("NV", "R", tiep=True), ptn_gui("NV", "R", tiep=True), ptn_gui("KT", "@la", tiep=True),
		np(ptn_gui("CHU_B", "R", tiep=True)), ghi("NV", "supplier_returns", "update", {"notes": "nv sua"}, {"id": "@ptn:R"}),
		dem("NV", "supplier_returns"), ptn("KT", "E", "@S1", []), ptn_gui("KT", "E", tiep=True),
		ptn_huy("KT", "R"), ptn_gui("KT", "R", tiep=True))
	th("V25", "Sửa phiếu đã xuất từ POS (huỷ → về nháp ghi thẳng → dòng → gửi)", *LO_M, ptn("TK", "R", "@S1", [d("@M", "hộp", 6, 1000)]),
		ptn_gui("TK", "R"), ptn_huy("TK", "R", "Sửa phiếu từ POS — lập lại"),
		ghi("TK", "supplier_returns", "update", {"supplier_id": "@S1", "return_date": "@hom_nay", "warehouse_zone": "date", "reason": None,
			"notes": None, "discount": 0, "subtotal": 8000, "vat": 0, "total": 8000, "vat_override": None, "status": "draft",
			"cancel_reason": None}, {"id": "@ptn:R"}),
		ptn_dong("TK", "R", [d("@M", "hộp", 8, 1000)]), ptn_gui("TK", "R"),
		khac_frappe=["⚠K Frappe (phương án §3.8 khi chốt): RPC sua_phieu_tra_ncc một giao dịch — PTNCC-0001 huỷ, PTNCC-0001-1 hoàn thành cùng "
			"số kho / nợ; cổng cấm update status (USE_RPC)"])
	th("V26", "Tiền phiếu trả: không làm tròn, thuế gõ tay kẹp, tổng kẹp, dòng SL ≤ 0", *LO_M,
		ptn("CHU", "R1", "@S1", [d("@M", "hộp", 1, 12345, thue=0.08)]), ptn_gui("CHU", "R1"),
		ptn("CHU", "R2", "@S1", [d("@M", "hộp", 1, 10000, thue=0.1)], thue_tay=-500), ptn_gui("CHU", "R2"),
		ptn("CHU", "R3", "@S1", [d("@M", "hộp", 1, 10000)], vung="sale", thue_tay=1000, giam=999999), ptn_gui("CHU", "R3"),
		ptn("CHU", "R4", "@S1", [d("@M", "hộp", 2, 10000), d("@M", "hộp", -1, 10000), d("@M", "hộp", 0, 10000),
			d("@M", "hộp", 1, 10000, giam=25000)], vung="sale"), ptn_gui("CHU", "R4"),
		khac_frappe=["⚠K Frappe làm tròn đồng (988 / 13333)", "❓ Frappe: dòng SL ≤ 0 / giá 0 không biểu diễn được trên PI trả (§3.7 bước 4, 7) → R4 chờ chốt"])
	th("V27", "Đánh số PTNCC (mã gõ tay bị đè, xoá nháp lấy lại số, return_seq NULL / trùng)",
		ptn("TK", "A", "@S1", [], vung=None, ma="TU-GO"), ptn("TK", "B", "@S1", [], vung=None),
		ghi("TK", "supplier_returns", "delete", loc={"id": "@ptn:B"}), ptn("TK", "C", "@S1", [], vung=None),
		ghi("TK", "supplier_returns", "update", {"return_code": "DOI-MA"}, {"id": "@ptn:A"}),
		ghi("TK", "supplier_returns", "update", {"return_seq": None}, {"id": "@ptn:A"}),
		ghi("TK", "supplier_returns", "update", {"return_seq": 3}, {"id": "@ptn:C"}, tiep=True),
		np(ptn("CHU_B", "BB", "@SB", [], vung=None, them={"org_id": "@org_b"})),
		khac_frappe=["⚠K Frappe dãy PTNCC-.#### không lấy lại số đã xoá, không đổi tên qua return_code / return_seq (cổng bỏ qua hai cột)"])
	th("V28", "Lối ghi thẳng nppsale không chặn (sửa dòng / về nháp / xoá phiếu đã xuất)", *LO_M,
		ptn("TK", "R1", "@S1", [d("@M", "hộp", 2, 1000)]), ptn_gui("TK", "R1"),
		ghi("TK", "supplier_return_lines", "update", {"quantity": 99}, {"return_id": "@ptn:R1"}),
		ghi("TK", "supplier_returns", "update", {"status": "draft"}, {"id": "@ptn:R1"}),
		ptn("TK", "R2", "@S1", [d("@M", "hộp", 4, 1000)], vung="sale"), ptn_gui("TK", "R2"),
		ghi("TK", "supplier_returns", "delete", loc={"id": "@ptn:R2"}),
		khac_frappe=["⚠K Frappe: USE_RPC / SO_KHO_KHOA-kiểu cho cả ba lời ghi (đóng lỗ — BP §6.1)"])

	# ============================================================ §6.3 M3 — công nợ NCC, Ghi trả, phiếu chi
	th("V29", "Phiếu chi: nợ đầu kỳ trước, không đụng dòng âm", *V29,
		khac_frappe=["nppsale K14 dựng PN-A / PN-B bằng dòng nợ ghi thẳng 01/10, 05/10; bộ này dùng phiếu nhập thật (thứ tự ghi nợ theo bước)"])
	th("V30", "Phiếu chi trả dư + ghi lùi ngày; số tổng hợp", *V30)
	th("V31", "Khoản nợ mới tự ăn tiền trả trước", *V31, khac_frappe=["Frappe: nợ lập tay = tờ NTN-"])
	th("V32", "Huỷ phiếu chi (hai lần) + so_chung_tu_ncc", *V32,
		khac_frappe=["⚠K Frappe đếm payables theo bản chiếu, stock_entries theo §5.3"])
	th("V33", "Hai phiếu chi cùng dư — chi sớm dồn trước; huỷ một thì phiếu kia dồn vào", *V33)
	th("V34", "Huỷ phiếu nhập đã được phiếu chi trừ tiền", pn("TK", "P1", "@S2", [d("@N", "túi", 10, 10000)]), pn_hoan("TK", "P1"),
		pn("TK", "P2", "@S2", [d("@N", "túi", 5, 10000)]), pn_hoan("TK", "P2"), chi("CHU", "C1", "@S2", 120000),
		pn_huy("CHU", "P1", "nhập nhầm"))
	th("V34b", "Chỉ có trả trước 500.000, huỷ PN 480.000 → trả trước về 500.000", chi("CHU", "C1", "@S1", 500000), *V01,
		pn_huy("TK", "P", "x"))
	th("V35", "Huỷ phiếu nhập khi đã Ghi trả", *V01, ghi_tra("KT", "@no:pn:P", 100000, "cash"), pn_huy("TK", "P"))
	th("V35b", "Huỷ phiếu nhập đã Ghi trả + đã bán, cho tồn âm → DA_TRA_TIEN trước HANG_DA_XUAT", *V01, co_am(), BAN30,
		ghi_tra("KT", "@no:pn:P", 100000, "cash"), pn_huy("TK", "P"))
	th("V36", "Ghi trả từng dòng — quyền, số, vượt, bù trừ, hình thức",
		pn("TK", "PA", "@S1", [d("@A", "hộp", 20, 10000)]), pn_hoan("TK", "PA"), pn("TK", "PB", "@S1", [d("@A", "hộp", 5, 10000)]),
		pn_hoan("TK", "PB"), ptn("TK", "R", "@S1", [d("@A", "hộp", 3, 10000)], vung="sale"), ptn_gui("TK", "R"),
		ghi_tra("QL", "@no:pn:PA", 1000, tiep=True), ghi_tra("KT", "@no:pn:PA", 0, tiep=True), ghi_tra("KT", "@no:pn:PA", 250000, tiep=True),
		ghi_tra("KT", "@no:pn:PA", 50000, "offset", ""), ghi_tra("KT", "@no:pn:PA", 150000, "", "trả nốt"),
		ghi_tra("KT", "@no:pn:PA", 1, tiep=True), ghi_tra("KT", "@no:ptn:R", 1, tiep=True), ghi_tra("KT", "@la", 1, tiep=True),
		np(ghi_tra("CHU_B", "@no:pn:PB", 1, tiep=True)), ghi_tra("KT", "@no:pn:PB", 1, "chuyen", tiep=True),
		khac_frappe=["❓ offset: Frappe JE CTN- khi có khoản giảm (BP §7.1 điểm 15)", "❓ method '' / NULL: Frappe dùng ht_tien_mat, cổng trả cash"])
	th("V37", "Lỗi lập phiếu chi; chi khi NCC chỉ còn dòng âm", chi("QL", "C0", "@S1", 1000, tiep=True), chi("CHU", "C0", "@S1", 0, tiep=True),
		chi("CHU", "C0", "@S1", 1000, cach="offset", tiep=True), chi("CHU", "C0", "@S1", 1000, cach=None, tiep=True),
		np(chi("CHU", "C0", "@SB", 1000, tiep=True)), chi("CHU", "C0", "@S1", 1000, "@hom_nay+1", tiep=True),
		lo("L-M", "@M", "date", 10, 1000, han=100, nhan=-10), ptn("TK", "R", "@S2", [d("@M", "hộp", 3, 10000)]), ptn_gui("TK", "R"),
		chi("CHU", "C1", "@S2", 70000))
	th("V38", "Khoá ghi thẳng công nợ / dòng chi / phiếu chi",
		pn("TK", "P", "@S1", [d("@A", "hộp", 10, 10000)]), pn_hoan("TK", "P"), ghi_tra("KT", "@no:pn:P", 50000, "cash"),
		ptn("TK", "R", "@S1", [d("@A", "hộp", 3, 10000)], vung="sale"), ptn_gui("TK", "R"), chi("KT", "C1", "@S2", 10000),
		ghi("KT", "payables", "insert", _no("@S1", None, amount=1000, paid=500), tiep=True),
		ghi("KT", "payables", "insert", _no("@S1", None, amount=1000, status="paid"), tiep=True),
		ghi("KT", "payables", "insert", _no("@S1", None, amount=1000, status="overdue", opening_balance=True)),
		ghi("KT", "payables", "update", {"paid": 1}, {"id": "@no:dk:S1"}, tiep=True),
		ghi("KT", "payables", "update", {"amount": 3000, "status": "open"}, {"id": "@no:dk:S1"}),
		ghi("KT", "payables", "update", {"status": "paid"}, {"id": "@no:dk:S1"}, tiep=True),
		ghi("KT", "payables", "update", {"amount": 999}, {"id": "@no:pn:P"}, tiep=True),
		ghi("KT", "payables", "update", {"invoice_number": "HD-MOI", "due_date": "@hom_nay+30", "notes": "ghi chu moi"}, {"id": "@no:pn:P"}),
		ghi("KT", "payables", "delete", loc={"id": "@no:pn:P"}, tiep=True),
		ghi("KT", "payables", "delete", loc={"id": "@no:ptn:R"}, tiep=True),
		ghi("KT", "payable_payments", "insert", {"payable_id": "@no:pn:P", "amount": 1, "method": "cash"}, tiep=True),
		ghi("KT", "payable_payments", "update", {"verified_by": "@u:KT", "verified_at": "@hom_nayT10:00:00+07:00"}, {"payable_id": "@no:pn:P"}),
		ghi("KT", "payable_payments", "update", {"verified_by": "@u:KT", "notes": "x"}, {"payable_id": "@no:pn:P"}, tiep=True),
		ghi("KT", "supplier_payments", "update", {"notes": "x"}, {"id": "@pc:C1"}),
		ghi("KT", "supplier_payments", "insert", {"org_id": "@org", "seq": 99, "code": "PCNCC-0099", "supplier_id": "@S1",
			"paid_date": "@hom_nay", "amount": 1, "method": "cash"}, tiep=True),
		ghi("QL", "payables", "insert", _no("@S1", None, amount=1000), tiep=True),
		np(may_chu("UPDATE payables SET paid = -30000 WHERE id = {@no:ptn:R}", "dữ liệu cũ: dòng âm của phiếu trả mang paid -30.000")),
		np(ptn_huy("KT", "R", tiep=True)),
		khac_frappe=["sửa amount đầu kỳ chưa trả: Frappe amend DKN-…-1", "xoá nợ phiếu trả: nppsale 23503 khoá ngoại — ⚠K Frappe câu NO_NCC_KHOA "
			"(BP §7.1 điểm 17)", "DA_CAN_TRU: Frappe dựng bằng JE CTN- tham chiếu PTNCC"])
	th("V39", "Nợ lập tay + nợ đầu kỳ qua màn (thêm, quá hạn ↔ mở, sửa, xoá; Excel hai lần; sửa số tiền đầu kỳ)",
		nhap_kho("CHU", "IN1", {"entry_code": "IN-20261116-1001", "supplier_id": "@S1", "warehouse_zone": "sale", "notes": "NCC: NCC Một • Kho: Kho bán",
			"payable": None, "lines": [{"product_id": "@A", "unit_name": "hộp", "qty_tx": 5, "conv": 1, "base_qty": 5, "base_cost": 10000}]}),
		ghi("CHU", "payables", "insert", _no("@S1", "HD-TAY-1", amount=2000000, stock_entry_id="@pk:IN1", due_date="@hom_nay+30")),
		ghi("CHU", "payables", "update", {"status": "overdue"}, {"stock_entry_id": "@pk:IN1"}),
		ghi("CHU", "payables", "update", {"status": "open"}, {"stock_entry_id": "@pk:IN1"}),
		ghi("CHU", "payables", "update", {"invoice_number": "HD-TAY-2"}, {"stock_entry_id": "@pk:IN1"}),
		ghi("CHU", "payables", "delete", loc={"stock_entry_id": "@pk:IN1"}),
		ghi("KT", "payables", "insert", [_no("@S1", None, amount=300000, opening_balance=True, notes="Nợ đầu kỳ (Excel)")]),
		ghi("KT", "payables", "insert", [_no("@S1", None, amount=300000, opening_balance=True, notes="Nợ đầu kỳ (Excel)")], tiep=True),
		ghi("KT", "payables", "update", {"amount": 350000}, {"id": "@no:dk:S1"}),
		chi("KT", "C1", "@S1", 100000),
		ghi("KT", "payables", "update", {"amount": 400000, "status": "partial"}, {"id": "@no:dk:S1"}),
		khac_frappe=["số 0 → trình duyệt chặn 'Số tiền không hợp lệ' (không gọi máy chủ)", "hạn tự điền hôm nay + 30 (NET30)",
			"Frappe: nợ lập tay = NTN- + npp_phieu_kho; xoá = huỷ NTN-; sửa số đầu kỳ chưa trả → DKN-xxxx-1; đã trả → ⚠K NO_NCC_KHOA"])
	th("V40", "Bất biến khám sổ công nợ NCC sau V29-V33", *V32, *V33, kham_ncc(),
		khac_frappe=["[Frappe] bất biến khám sổ dòng 66: payables.paid = Σ payable_payments (±0,01); Σ dòng mỗi phiếu chi posted (kể cả "
			"::tra_truoc) = paid_amount; paid_at mọi dòng của một phiếu chi = lúc chi; không phiếu chi nào phân bổ vào dòng âm"])

	# ============================================================ §6.4 M4 — phiếu kho tay
	P41 = {"entry_code": "IN-20261001-1234", "posted_at": "@hom_nay-46T12:00:00+07:00", "supplier_id": "@S1", "warehouse_zone": "date",
		"notes": "NCC: S • Kho: Kho date", "payable": {"amount": 480000, "invoice_number": "HD-9"},
		"lines": [{"product_id": "@A", "unit_name": "thùng", "qty_tx": 2, "conv": 24, "base_qty": 48, "base_cost": 10000, "batch_code": "",
			"expires_at": "@hom_nay+226"}]}
	th("V41", "Nhập kho tay post_stock_import (NCC + nợ, vai, kho lạ, SL 0, không NCC, gọi lại, tồn đầu kỳ Excel)",
		nhap_kho("CHU", "IN1", P41), nhap_kho("KT", "IN2", P41, tiep=True), nhap_kho("CHU", "IN3", {**P41, "warehouse_zone": "kho-lung"}, tiep=True),
		nhap_kho("CHU", "IN4", {**P41, "lines": [{**P41["lines"][0], "base_qty": 0}]}, tiep=True),
		nhap_kho("CHU", "IN5", {**P41, "supplier_id": None}), nhap_kho("CHU", "IN6", P41),
		nhap_kho("CHU", "DK1", {"entry_code": "DK-20261116-1001", "supplier_id": None, "warehouse_zone": "sale",
			"notes": "Tồn kho đầu kỳ — nhập từ file Excel sản phẩm (1 mặt hàng)", "payable": None,
			"lines": [{"product_id": "@B", "batch_code": "LOT-DK-20261116-1001-1", "expires_at": "2099-12-31", "unit_name": "gói", "qty_tx": 10,
				"conv": 1, "base_qty": 10, "base_cost": 4000}]}),
		khac_frappe=["⚠K Frappe: có NCC + tiền → PI PN- (CFD-13; ❓ giá vốn lô vs nợ — §7.3), entry_id = entry_code = tên PI",
			"không NCC → SE IN-YYYYMMDD-#### (lùi ngày, repost); gọi lại → chứng từ thứ hai, tên lô LOT-… trùng → ❓ BP §7.1 điểm 14",
			"tồn đầu kỳ → ton_dau_ky is_opening (❓ nhận diện DK-)"])
	th("V42", "Xuất lẻ FEFO, hai dòng cùng mặt hàng + khoá phiếu đã ghi sổ", *LO_P(),
		pk("TK", "XKL-TEST1", "export", "sale", [dk("@P", 7), dk("@P", 5)], ly_do_xuat="damaged"), xuat_le("TK", "XKL-TEST1"),
		xuat_le("TK", "XKL-TEST1"), ghi("TK", "stock_entries", "update", {"notes": "ghi chu moi"}, {"id": "@pk:XKL-TEST1"}),
		ghi("TK", "stock_entry_lines", "update", {"quantity": 1}, {"entry_id": "@pk:XKL-TEST1"}, tiep=True),
		ghi("TK", "stock_entries", "update", {"warehouse_zone": "date"}, {"id": "@pk:XKL-TEST1"}, tiep=True),
		ghi("TK", "stock_entries", "delete", loc={"id": "@pk:XKL-TEST1"}, tiep=True),
		khac_frappe=["⚠K cổng Frappe unit_cost dòng = giá vốn ≠ 0, batch_id khi một lô; tên phiếu XKL-0001 trong câu xoá"])
	th("V43a", "Xuất lẻ thiếu tồn — nhãn đơn vị MIN(unit_name)", *LO_P(10, None, 20),
		pk("TK", "X", "export", "sale", [dk("@P", 1, dv="Thung", hs=24)]), xuat_le("TK", "X"))
	th("V43b", "Xuất lẻ thiếu tồn, cho bán vượt tồn → thiếu im lặng", co_am(), *LO_P(10, None, 20),
		pk("TK", "X", "export", "sale", [dk("@P", 1, dv="Thung", hs=24)]), xuat_le("TK", "X"),
		khac_frappe=["⚠K Frappe P theo lô → như V43a (KHONG_DU_TON) — xem V43c"])
	fr("V43c", "Xuất lẻ hàng không lô X vượt tồn khi cho âm", "cho_ban_vuot_ton = 1, X kho bán 10: XKL 24 cái → ghi sổ.",
		"Ghi sổ được, Bin kho bán -14 (Item.allow_negative_stock + cho_ban_vuot_ton).",
		co_am(), nhap_kho("TK", "INX", {"entry_code": "IN-X-1", "warehouse_zone": "sale", "lines": [{"product_id": "@X", "unit_name": "cai",
			"qty_tx": 10, "conv": 1, "base_qty": 10, "base_cost": 1000}]}),
		pk("TK", "X", "export", "sale", [{**dk("@P", 24), "product_id": "@X", "unit_name": "cai", "transaction_uom": "cai"}]), xuat_le("TK", "X"))
	th("V44a", "Xuất lẻ âm hoàn toàn (không lô nào) rồi huỷ", co_am(), pk("TK", "XKL-AM", "export", "sale", [dk("@Q", 3)]),
		xuat_le("TK", "XKL-AM"), huy_pk("TK", "XKL-AM", "nham"),
		khac_frappe=["⚠K Frappe: Q theo lô → KHONG_DU_TON … chỉ còn 0; X không lô → ghi sổ, HUỶ ĐƯỢC"])
	th("V44b", "Xuất lẻ có dòng âm", *LO_P(3, None, None), pk("TK", "XKL-M", "export", "sale", [dk("@P", 5), dk("@P", -3)]),
		xuat_le("TK", "XKL-M", tiep=True), pk("TK", "XKL-0", "export", "sale", [dk("@P", -2)]), xuat_le("TK", "XKL-0"),
		huy_pk("TK", "XKL-0", "x"), khac_frappe=["❓ Frappe: dòng SL ≤ 0 → cổng chặn (§3.15 bước 4)"])
	fr("V44c", "Huỷ phiếu xuất lẻ hàng không lô X đã ghi sổ âm", "cho_ban_vuot_ton = 1: XKL X 3 cái (Bin 0) → ghi sổ → cancel_stock_entry.",
		"Ghi sổ được (Bin -3); huỷ được (lõi đảo SLE) → Bin 0 — nppsale NO_CONSUMPTION_TRACE (⚠K).",
		co_am(), pk("TK", "XKL-AM", "export", "sale", [{**dk("@P", 3), "product_id": "@X", "unit_name": "cai", "transaction_uom": "cai"}]),
		xuat_le("TK", "XKL-AM"), huy_pk("TK", "XKL-AM", "nham"))
	th("V45", "Xuất lẻ — cổng vai, loại, trạng thái", *LO_P(10, None, 20),
		pk("TK", "X1", "export", "sale", [dk("@P", 1)]), xuat_le("NV", "X1", tiep=True), np(xuat_le("CHU_B", "X1", tiep=True)),
		pk("TK", "X2", "export", "sale", []), xuat_le("TK", "X2", tiep=True),
		pk("TK", "X3", "transfer", "sale", [dk("@P", 1)], dich="date"), xuat_le("TK", "X3", tiep=True),
		pk("TK", "X4", "export", "sale", [dk("@P", 1)]), ghi("TK", "stock_entries", "update", {"status": "cancelled"}, {"id": "@pk:X4"}),
		xuat_le("TK", "X4", tiep=True), pk("TK", "X5", "export", "date", [dk("@P", 25)]), xuat_le("TK", "X5", tiep=True),
		khac_frappe=["⚠K Frappe nháp huỷ = xoá → PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu xuất kho này."])
	th("V46", "Khoá ghi thẳng phiếu kho (mig 170)", *LO_P(10, None, None),
		ghi("TK", "stock_entries", "insert", {"org_id": "@org", "entry_code": "X-POSTED", "type": "export"}, tiep=True),
		pk("TK", "E1", "export", "sale", [dk("@P", 1)]),
		ghi("TK", "stock_entries", "update", {"status": "posted"}, {"id": "@pk:E1"}, tiep=True),
		ghi("TK", "stock_entries", "update", {"type": "import"}, {"id": "@pk:E1"}, tiep=True),
		ghi("TK", "stock_entries", "update", {"status": "cancelled"}, {"id": "@pk:E1"}),
		pk("TK", "E2", "export", "sale", [dk("@P", 1)]), xuat_le("TK", "E2"),
		ghi("TK", "stock_entries", "update", {"entry_code": "XKL-DOI-MA", "issue_reason": "other", "supplier_id": "@S1", "ref_order_ids": ["x"],
			"notes": "sua ghi chu"}, {"id": "@pk:E2"}),
		ghi("TK", "stock_entries", "update", {"posted_at": "@hom_nay-1T09:00:00+07:00"}, {"id": "@pk:E2"}, tiep=True),
		ghi("TK", "stock_entry_lines", "insert", {"entry_id": "@pk:E1", "product_id": "@P", "unit_name": "Lon", "quantity": 1,
			"qty_in_base_uom": 1}, tiep=True),
		ghi("TK", "stock_entries", "update", {"status": "draft"}, {"id": "@pk:E1"}, tiep=True),
		ghi("TK", "stock_entries", "delete", loc={"id": "@pk:E1"}, tiep=True),
		pk("TK", "E3", "export", "sale", [dk("@P", 1)]), ghi("TK", "stock_entries", "delete", loc={"id": "@pk:E3"}),
		ghi("NV", "stock_entries", "insert", {"org_id": "@org", "entry_code": "NV-1", "type": "export", "status": "draft"}, tiep=True),
		pk("TK", "KK1", "stocktake", None, [dk("@P", -1)]), ghi("QL", "stock_entries", "update", {"status": "cancelled"}, {"id": "@pk:KK1"}),
		khac_frappe=["nháp → huỷ: Frappe xoá nháp", "⚠K Frappe phiếu đã ghi sổ chỉ sửa notes — đổi entry_code / issue_reason / supplier_id / "
			"ref_order_ids → 'SO_KHO_KHOA: phiếu đã ghi sổ chỉ sửa được ghi chú.'"])
	th("V47", "Chuyển kho bán → date một phần lô, rồi gộp lô", *V47,
		khac_frappe=["Frappe: MỘT Batch L-A, tồn kho bán 3, kho date 7, giá vốn 8.000 ở cả hai, npp_ngay_nhap giữ, npp_chuyen_vung_luc có"])
	th("V48", "Chuyển date → bán bị chặn vì lô cận hạn đứng đầu FEFO", *V47,
		pk("TK", "CKL-3", "transfer", "date", [dk("@P", 2)], dich="sale"), chuyen("TK", "CKL-3"))
	th("V49", "Chuyển kho — các lỗi khác (thiếu tồn, trùng kho, thiếu đích, huỷ CKL, vai)", *V47,
		pk("TK", "CKL-3", "transfer", "date", [dk("@P", 2)], dich="sale"), chuyen("TK", "CKL-3", tiep=True),
		ghi("TK", "stock_entry_lines", "update", {"quantity": 30, "qty_in_base_uom": 30, "qty_in_transaction_uom": 30}, {"entry_id": "@pk:CKL-3"}),
		chuyen("TK", "CKL-3", tiep=True),
		ghi("TK", "stock_entries", "update", {"dest_warehouse_zone": "date"}, {"id": "@pk:CKL-3"}), chuyen("TK", "CKL-3", tiep=True),
		ghi("TK", "stock_entries", "update", {"dest_warehouse_zone": None}, {"id": "@pk:CKL-3"}), chuyen("TK", "CKL-3", tiep=True),
		huy_pk("TK", "CKL-1", "x", tiep=True), chuyen("QL", "CKL-3", tiep=True))
	th("V50", "Huỷ phiếu xuất lẻ đã ghi sổ (vai) + huỷ phiếu nháp (lý do rỗng, lần hai)", *LO_P(10, 5, None),
		pk("TK", "XKL-12", "export", "sale", [dk("@P", 12)]), xuat_le("TK", "XKL-12"),
		huy_pk("QL", "XKL-12", "x", tiep=True), huy_pk("NV", "XKL-12", "x", tiep=True), np(huy_pk("CHU_B", "XKL-12", "x", tiep=True)),
		huy_pk("TK", "XKL-12", "nham"), pk("TK", "XKL-N", "export", "sale", [dk("@P", 1)]), huy_pk("TK", "XKL-N", ""),
		huy_pk("TK", "XKL-N", "lan 2"), khac_frappe=["⚠K Frappe nháp → xoá (không còn ghi chú; lần 2 → ENTRY_NOT_FOUND)"])
	th("V51", "Huỷ phiếu nhập kho tay IN- (có nợ NCC; đã xuất bớt; huỷ xuất rồi huỷ nhập)",
		nhap_kho("TK", "IN1", {"entry_code": "IN-20261116-0001", "supplier_id": "@S1", "warehouse_zone": "sale", "notes": None,
			"payable": {"amount": 50000, "invoice_number": None}, "lines": [{"product_id": "@Q", "unit_name": "Chai", "qty_tx": 10, "conv": 1,
				"base_qty": 10, "base_cost": 5000, "expires_at": "@hom_nay+15"}]}),
		huy_pk("TK", "IN1", "x", tiep=True),
		nhap_kho("TK", "IN2", {"entry_code": "IN-20261116-0002", "supplier_id": None, "warehouse_zone": "sale", "payable": None,
			"lines": [{"product_id": "@G", "unit_name": "Kg", "qty_tx": 10, "conv": 1, "base_qty": 10, "base_cost": 20000}]}),
		pk("TK", "XKL-G", "export", "sale", [dk("@G", 2.5)]), xuat_le("TK", "XKL-G"), huy_pk("TK", "IN2", "x", tiep=True),
		huy_pk("TK", "XKL-G", "x"), huy_pk("TK", "IN2", "x"),
		khac_frappe=["⚠K Frappe: IN- có NCC + tiền là PN → 'ENTRY_HAS_SOURCE: phiếu PN-… thuộc một hoá đơn nhập mua. …'"])
	th("V52", "Chuyển một phần lô làm phiếu nhập không huỷ được", *V52, huy_pk("TK", "IN-B", "x"),
		khac_frappe=["Frappe Batch G-1 kho bán 6, kho date 4"])
	th("V53", "Huỷ phiếu kho thuộc chứng từ gốc (HĐ, PN, PTNCC, phiếu trả khách; HĐ đã huỷ)", *LO_P(10, None, None),
		ban("CHU", "H1", [("@P", "Lon", 2)]), pn("TK", "P", "@S1", [d("@A", "hộp", 10, 10000)]), pn_hoan("TK", "P"),
		ptn("TK", "R", "@S1", [d("@A", "hộp", 2, 10000)], vung="sale"), ptn_gui("TK", "R"), tra_khach("CHU", "T1", [("@P", "Lon", 1, 10000)]),
		huy_pk("CHU", "@pk:hd:H1", "x", tiep=True), huy_pk("CHU", "@pk:pn:P", "x", tiep=True), huy_pk("CHU", "@pk:ptn:R", "x", tiep=True),
		huy_pk("CHU", "@pk:nl:T1", "x", tiep=True), huy_hd("CHU", "H1"), huy_pk("CHU", "@pk:hd:H1", "x", tiep=True),
		khac_frappe=["Frappe: mã phiếu = tên chứng từ (HĐ / PI / NL-), cùng câu (§3.19 bước 2, 4)"])
	th("V54", "Nhận diện nguồn qua ghi chú (đổi mã + ghi chú phiếu tay)", *LO_P(10, None, None),
		pk("TK", "X1", "export", "sale", [dk("@P", 1)]), xuat_le("TK", "X1"),
		ghi("TK", "stock_entries", "update", {"entry_code": "XKL-DOI-MA", "notes": "Hoàn kho do huỷ hóa đơn HD-9999"}, {"id": "@pk:X1"}),
		huy_pk("TK", "X1", "x", tiep=True),
		ghi("TK", "stock_entries", "update", {"notes": "Đảo phiếu trả abc"}, {"id": "@pk:X1"}), huy_pk("TK", "X1", "x", tiep=True),
		ghi("TK", "stock_entries", "update", {"notes": "Nhập lại từ phiếu trả abc"}, {"id": "@pk:X1"}), huy_pk("TK", "X1", "x", tiep=True),
		ghi("TK", "stock_entries", "update", {"notes": "binh thuong"}, {"id": "@pk:X1"}), huy_pk("TK", "X1", "x"),
		khac_frappe=["⚠K Frappe: đổi mã → SO_KHO_KHOA; nhận diện bằng trường thật → cả bốn ghi chú huỷ được ngay lần đầu (true, true, 1)"])
	th("V55", "Danh sách phiếu kho: duyệt / huỷ hàng loạt (lời gọi máy chủ của màn)", *LO_P(10, None, 20),
		pk("TK", "XKL-1", "export", "sale", [dk("@P", 2)]), pk("TK", "CKL-1", "transfer", "sale", [dk("@P", 1)], dich="date"),
		pk("TK", "IN-OLD", "import", "sale", [dk("@P", 5)]), xuat_le("TK", "XKL-1"), chuyen("TK", "CKL-1"),
		pn("TK", "P", "@S1", [d("@A", "hộp", 5, 10000)]), pn_hoan("TK", "P"),
		huy_pk("TK", "XKL-1", "Huỷ từ danh sách phiếu kho", tiep=True), huy_pk("TK", "@pk:pn:P", "Huỷ từ danh sách phiếu kho", tiep=True),
		khac_frappe=["IN- nháp: màn KHÔNG gọi máy chủ — 'Phiếu nhập nháp không ghi sổ từ đây được — không có đường nào cộng kho cho nó. Mở "
			"phiếu để kiểm tra, hoặc lập lại phiếu ở màn Nhập kho.'; toast 'Đã duyệt 2/3 phiếu'; huỷ: '1 phiếu KHÔNG huỷ được'"])

	# ============================================================ §6.5 M5 — lô và kho cận date
	V56 = [nguong(45), ghi("TK", "batches", "insert", [{"org_id": "@org", "product_id": "@P", "batch_code": f"R{n}", "expires_at": f"@hom_nay+{n}",
		"qty_initial": 0, "qty_on_hand": 0, "unit_cost": 0, "warehouse_zone": "sale"} for n in (44, 45, 46, 90, 91)]),
		ghi("TK", "batches", "update", {"expires_at": "@hom_nay+30"}, {"id": "@lo:R90"}),
		ghi("TK", "batches", "update", {"expires_at": "@hom_nay+300"}, {"id": "@lo:R44"})]
	th("V56", "Tự chuyển vùng khi tạo lô / đổi hạn (lô rỗng)", *V56,
		khac_frappe=["Frappe lô rỗng: chỉ đổi npp_kho_tao (+44, +45 → kho_can_date)"])
	th("V56b", "Lô có tồn ở kho bán đổi hạn vào ngưỡng", nguong(45), lo("L5", "@P", "sale", 5, 8000, han=100, nhan=-5),
		ghi("TK", "batches", "update", {"expires_at": "@hom_nay+20"}, {"id": "@lo:L5"}),
		khac_frappe=["[Frappe] SE CKL- chuyen_date_tu_dong 5 cái trong cùng lượt (nppsale lật vùng cả dòng lô)"])
	th("V57", "Rà soát kho date (NV, NPP khác, không người đăng nhập)", nguong(45), lo("L46", "@P", "sale", 10, 8000, han=46, nhan=-5),
		ghi("TK", "batches", "insert", {"org_id": "@org", "product_id": "@P", "batch_code": "L91", "expires_at": "@hom_nay+91", "qty_initial": 0,
			"qty_on_hand": 0, "unit_cost": 0, "warehouse_zone": "sale"}),
		nguong(100), ra_soat("NV"), np(ra_soat("NV", "@org_b", tiep=True)), ra_soat("HE_THONG"),
		khac_frappe=["Frappe: một CKL- chuyen_date_tu_dong 10 cái, npp_chuyen_vung_luc; gọi lại → 0, không phiếu mới"])
	fr("V57b", "Việc đêm 01:00 VN rà soát kho date", "Lịch chạy refresh_warehouse_zones cho NPP (không người), ngưỡng 100, lô +46 tồn 10.",
		"Một phiếu CKL- chuyen_date_tu_dong 10 cái; chạy lại không sinh phiếu mới (bàn bạc dòng 209 — nppsale không có lịch).",
		nguong(45), lo("L46", "@P", "sale", 10, 8000, han=46, nhan=-5), nguong(100), _b("viec_dem", "HE_THONG", ten="ra_soat_kho_date"),
		_b("viec_dem", "HE_THONG", ten="ra_soat_kho_date"))
	th("V58", "Huỷ xuất lẻ sau khi lô bị rà sang date", *V52, pk("TK", "XKL-C", "export", "sale", [dk("@G", 3)]), xuat_le("TK", "XKL-C"),
		nguong(200), ra_soat("TK"), huy_pk("TK", "XKL-C", "x"),
		khac_frappe=["⚠K Frappe: rà soát = CKL- 3 cái bán → date; huỷ XKL-C trả 3 về kho bán (nơi đã lấy) → G-1 bán 3, date 7; thẻ kho không đổi "
			"vùng hồi tố"])
	th("V59", "Lô qua cổng: tạo rỗng / có tồn, đổi mã, đổi hạn, sửa giá, sửa tồn, xoá", nguong(30),
		ghi("TK", "batches", "insert", {"org_id": "@org", "product_id": "@P", "batch_code": "R0", "expires_at": "@hom_nay+300", "qty_initial": 0,
			"qty_on_hand": 0, "unit_cost": 0, "warehouse_zone": "sale"}),
		ghi("TK", "batches", "insert", {"org_id": "@org", "product_id": "@P", "batch_code": "R5", "expires_at": "@hom_nay+300", "qty_initial": 5,
			"qty_on_hand": 5, "unit_cost": 0, "warehouse_zone": "sale"}, tiep=True),
		ghi("TK", "batches", "update", {"batch_code": "R0-MOI"}, {"id": "@lo:R0"}),
		lo("L7", "@P", "sale", 7, 8000, han=100, nhan=-5),
		ghi("TK", "batches", "update", {"expires_at": "@hom_nay+20"}, {"id": "@lo:L7"}),
		ghi("TK", "batches", "update", {"unit_cost": 9000}, {"id": "@lo:L7"}, tiep=True),
		ghi("TK", "batches", "update", {"qty_on_hand": 8}, {"id": "@lo:L7"}, tiep=True),
		ghi("TK", "batches", "delete", loc={"id": "@lo:L7"}, tiep=True),
		pn("TK", "P", "@S1", [d("@A", "hộp", 2, 10000)]), pn_hoan("TK", "P"), pn_huy("TK", "P", "x"),
		ghi("TK", "batches", "delete", loc={"id": "@lo:PN-0001-001"}, tiep=True),
		ghi("NV", "batches", "insert", {"org_id": "@org", "product_id": "@P", "batch_code": "NV-1", "expires_at": "@hom_nay+300", "qty_initial": 0,
			"qty_on_hand": 0, "unit_cost": 0, "warehouse_zone": "sale"}, tiep=True),
		khac_frappe=["đổi mã → Frappe rename_doc (mọi chứng từ trỏ mã mới)", "đổi hạn khi còn 7 ở kho bán → Frappe CKL- 7 sang date (nppsale lật vùng)",
			"xoá lô đã có phiếu: nppsale 23503 khoá ngoại (❓ câu Frappe)"])

	# ============================================================ §6.6 M6 — kiểm kê
	th("V60", "Duyệt kiểm kê: có lô, hụt không lô, thừa không lô, dòng 0 (vai, gọi lại, từ chối sau duyệt)", *LO_P(),
		lo("L-RONG", "@P", "sale", 0, 0, han=300, nhan=-1),
		pk("TK", "KK60", "stocktake", None, [dk("@P", -3, lo="@lo:L-A", gia=8000), dk("@P", -6.5), dk("@P", 2), dk("@P", 0)]),
		kk_duyet("TK", "KK60", tiep=True), kk_duyet("KT", "KK60", tiep=True), kk_duyet("QL", "KK60"), kk_duyet("QL", "KK60", tiep=True),
		kk_tu_choi("QL", "KK60", "x", tiep=True),
		khac_frappe=["Frappe: DCK- Issue (L-A 3 kho bán, L-C 6,5 kho date) + Receipt (L-RONG 2, giá 0, allow_zero_valuation_rate); NPP Phieu Chi "
			"69.500 ngay_chi VN", "❓ ALREADY_POSTED in giờ VN (đề xuất) — nppsale giờ phiên (UTC trên Supabase)"])
	th("V61", "Kiểm kê — các lỗi chặn duyệt", *V61)
	th("V62", "Từ chối kiểm kê (lý do rỗng, lần hai, duyệt phiếu đã từ chối, phiếu xuất, NPP khác, id lạ, huỷ thẳng)", *V61,
		kk_tu_choi("QL", "KK-1", ""), kk_tu_choi("QL", "KK-1", "lan 2"), kk_tu_choi("QL", "KK-2", "Dem lai"), kk_duyet("QL", "KK-2", tiep=True),
		pk("TK", "XKL-9", "export", "sale", [dk("@P", 1)]), kk_tu_choi("QL", "XKL-9", "x", tiep=True),
		np(kk_tu_choi("CHU_B", "KK-3", "x", tiep=True)), np(kk_duyet("CHU_B", "KK-3", tiep=True)), kk_duyet("QL", "@la", tiep=True),
		ghi("CHU", "stock_entries", "update", {"status": "cancelled"}, {"id": "@pk:KK-3"}))
	th("V63", "Lỗ: duyệt 'kiểm kê' trên phiếu xuất nháp", *LO_P(10, 5, None), pk("TK", "XKL-5", "export", "sale", [dk("@P", 5)]),
		kk_duyet("CHU", "XKL-5"), khac_frappe=["⚠K Frappe: chỉ nhận NPP Kiem Ke → ENTRY_NOT_FOUND: không tìm thấy phiếu kiểm kê (lỗ đóng)"])
	th("V64", "Kiểm kê → duyệt qua màn (tạo lô rỗng cho hàng chưa có lô rồi duyệt; từ chối phiếu khác)",
		lo("L-30", "@P", "sale", 30, 8000, han=200, nhan=-30), lo("L-10", "@P", "sale", 10, 9000, han=100, nhan=-10),
		pk("TK", "KK64", "stocktake", None, [dk("@P", -3, lo="@lo:L-30", gia=8000), dk("@Q", 5)], ma="KK2611161234"),
		ghi("TK", "batches", "insert", {"org_id": "@org", "product_id": "@Q", "batch_code": "Q-1", "expires_at": "@hom_nay+365", "qty_initial": 0,
			"qty_on_hand": 0, "unit_cost": 0, "warehouse_zone": "sale"}),
		kk_duyet("CHU", "KK64"), pk("TK", "KK64B", "stocktake", None, [dk("@P", -1, lo="@lo:L-10", gia=9000)], ma="KK2611165678"),
		kk_tu_choi("CHU", "KK64B", None),
		khac_frappe=["màn duyệt khoá nút khi còn hàng chưa có lô ('Còn 1 sản phẩm chưa có lô — tạo lô trước rồi mới duyệt được') — không gọi máy chủ",
			"❓ toast 'Đã lưu phiếu kiểm kê <mã>' in mã trình duyệt vs tên Frappe KK-.YY.MM.DD.-.####"])

	# ============================================================ §6.7 M7 — sửa phiếu nhập đã hoàn thành
	th("V65", "Sửa giá phiếu đã bán, đã trả một phần", *V65, pn_huy("KT", "P", tiep=True),
		khac_frappe=["Frappe nhánh B: LCV SGN- +48.000; JE DCN- Nợ tk_trung_gian_sua_gia_nhap / Có Phải trả S1; npp_sua_gia; bill_no HD-NCC-9; "
			"id giữ PN-0001"])
	th("V66", "Sửa SL thấp hơn số đã xuất", *V65, pn_sua("KT", "P", {"warehouse_zone": "sale"}, [d("@A", "thùng", 1, 264000, hs=24)]))
	V67 = [*V65, pn_sua("KT", "P", {"warehouse_zone": "sale"}, [d("@A", "hộp", 30, 11000), d("@B", "gói", 10, 5000)])]
	th("V67", "Sửa thùng → hộp đúng số đã bán + thêm dòng", *V67,
		khac_frappe=["⚠K Frappe: lô đã xuất → đổi ĐV / SL / thêm dòng bị từ chối (đề xuất PHIEU_DA_XUAT_CHI_SUA_GIA — §3.3; CFD-06)"])
	th("V68", "Bỏ dòng chưa xuất / bỏ dòng đã xuất / thêm lại hàng đã bỏ", *V67,
		pn_sua("KT", "P", {"warehouse_zone": "sale"}, [d("@A", "hộp", 30, 11000)]),
		pn_sua("KT", "P", {"warehouse_zone": "sale"}, [d("@B", "gói", 1, 5000)], tiep=True),
		pn_sua("KT", "P", {"warehouse_zone": "sale"}, [d("@A", "hộp", 30, 11000), d("@B", "gói", 4, 5000)]), chi_nppsale=True)
	th("V69", "Sửa xuống dưới số tiền đã trả (nppsale đổi sang hộp)", *V65, pn_sua("KT", "P", DAU65, [d("@A", "hộp", 30, 2000)]),
		khac_frappe=["⚠K bản Frappe chỉ sửa giá — xem V69b"])
	th("V69b", "Sửa xuống dưới số đã trả, giữ thùng 2 (đúng tải trọng bản Frappe)", *V65, pn_sua("KT", "P", DAU65, [d("@A", "thùng", 2, 40000, hs=24)]),
		khac_frappe=["Frappe: LCV SGN- -400.000; JE DCN- Debit Note giảm nợ 400.000; bản chiếu so_tien 80000, da_tra 100000 → trang_thai open "
			"(⚠K BP §4.3.0 — nppsale partial)"])

	def dau70(vung):
		return {"supplier_id": "@S1", "invoice_number": None, "invoice_date": "@hom_nay", "warehouse_zone": vung, "discount": 0,
			"vat_override": None, "notes": None}

	Q70 = [d("@A", "thùng", 1, 240000, hs=24), d("@C", "chai", 10, 15000)]
	XEM_LO = doc_bang("TK", "batches", cot=["batch_code", "warehouse_zone", "qty_on_hand", "expires_at"])
	th("V70", "Đổi kho trên phiếu (date, về bán, phiếu khác sửa giá không đổi kho)", pn("TK", "Q", "@S1", Q70, ngay="@hom_nay"),
		pn_hoan("TK", "Q"), pn_sua("TK", "Q", dau70("date"), Q70), XEM_LO, pn_sua("TK", "Q", dau70("sale"), Q70),
		pn("TK", "Q2", "@S1", [d("@C", "chai", 5, 15000)], ngay="@hom_nay"), pn_hoan("TK", "Q2"),
		pn_sua("TK", "Q2", dau70("sale"), [d("@C", "chai", 5, 16000)]),
		khac_frappe=["Frappe (chưa xuất → nhánh A amend): (2) A vào kho bán, C VẪN vào kho date (luật kho nhận theo hạn lúc nhập — ⚠K)"])
	th("V71", "Sửa phiếu nhập chưa xuất — tiền đã trả đi theo (tham khảo nppsale)",
		pn("TK", "P2", "@S1", [d("@A", "thùng", 5, 240000, hs=24)]), pn_hoan("TK", "P2"), ghi_tra("KT", "@no:pn:P2", 1000000, "transfer"),
		chi("KT", "C1", "@S1", 200000), pn("TK", "P1", "@S1", P1_DONG), pn_hoan("TK", "P1"),
		pn_sua("KT", "P1", dau70("sale"), [d("@A", "hộp", 60, 10000), d("@B", "gói", 10, 5000)]),
		pn_sua("KT", "P2", dau70("sale"), [d("@A", "thùng", 5, 160000, hs=24)]),
		nguon="nppsale+dac_ta",
		khac_frappe=["[Frappe] PN-xxxx-1 thay tờ cũ (tờ cũ cancelled), dòng cũ nhập vào đúng Batch cũ, dòng mới lô mới; PE GTN- / PCNCC- phân bổ "
			"lại sang tờ mới (reconcile_against_document, giữ tên PE) tới mức còn nợ; phần dư — ❓ nppsale giữ cả paid trên dòng nợ (partial), "
			"Frappe phần không phân bổ được nằm lại PE (§7.3); id trả = tờ mới; giá nhập ghi lại; so_dong, doi_gia_lo 0"])

	# ============================================================ §6.8 M8 — gộp / xoá NCC
	NEN72 = [ghi("KT", "payables", "insert", _no("@S1", None, amount=100000, opening_balance=True, notes="Đầu kỳ S1")),
		ghi("KT", "payables", "insert", _no("@S2", None, amount=40000, opening_balance=True, notes="  ")),
		ghi("CHU", "user_suppliers", "insert", [{"user_id": "@u:NV", "supplier_id": "@S1", "org_id": "@org"},
			{"user_id": "@u:NV", "supplier_id": "@S2", "org_id": "@org"}, {"user_id": "@u:TK", "supplier_id": "@S2", "org_id": "@org"}])]
	th("V72", "Gộp NCC — hai bên cùng có nợ đầu kỳ (vai, trùng, NPP khác)", *NEN72, gop("TK", "@S2", "@S1", tiep=True),
		gop("KT", "@S2", "@S2", tiep=True), np(gop("KT", "@SB", "@S1", tiep=True)), np(gop("KT", "@S2", "@SB", tiep=True)), gop("KT", "@S2", "@S1"),
		khac_frappe=["Frappe: tờ DKN- của S2 → lap_tay + ghi chú; rename_doc merge"])
	th("V72b", "Gộp NCC — trả trước của bên gộp không tự dồn; nợ mới dồn vào khoản cũ nhất", chi("KT", "C1", "@S2", 10000),
		ghi("KT", "payables", "insert", _no("@S1", "NO-S1", amount=50000)), gop("KT", "@S2", "@S1"),
		ghi("KT", "payables", "insert", _no("@S1", "NO-MOI", amount=1)))
	th("V73", "Xoá NCC (vai, có chứng từ, chỉ còn mặt hàng, gọi lại, xoá thẳng, created_by)",
		ghi("KT", "payables", "insert", [_no("@S1", "N1", amount=1000), _no("@S1", "N2", amount=2000)]),
		lo("L-B4", "@B", "date", 3, 500, han=197, nhan=-76),
		xoa_ncc("KT", "@S3", True, tiep=True), xoa_ncc("CHU", "@S1", True, tiep=True), xoa_ncc("CHU", "@S3", True),
		xoa_ncc("CHU", "@S3", True, tiep=True), ghi("CHU", "suppliers", "delete", loc={"id": "@S0"}, tiep=True),
		ghi("CHU", "suppliers", "delete", loc={"id": "@S1"}, tiep=True),
		ghi("CHU", "suppliers", "insert", {"id": "@S5", "org_id": "@org", "name": "NCC Năm", "created_by": "@u:NV"}),
		ghi("CHU", "suppliers", "update", {"created_by": "@u:NV"}, {"id": "@S5"}), xoa_ncc("CHU", "@S0"),
		khac_frappe=["🔧 cổng suppliers: câu NCC_XOA_QUA_RPC phải đúng nguyên văn; nhánh NCC_CO_CHUNG_TU trước (§3.14)"])

	# ============================================================ §6.9 M9 — báo cáo, giá vốn, đầu-cuối
	th("V74", "Giá vốn: lô đích danh nppsale ↔ batch-wise ERPNext", pn("TK", "P1", "@S1", [d("@A", "hộp", 20, 8000)]), pn_hoan("TK", "P1"),
		pn("TK", "P2", "@S1", [d("@A", "hộp", 50, 9000)]), pn_hoan("TK", "P2"), BAN30,
		ptn("TK", "R", "@S1", [d("@A", "hộp", 5, 10000)], vung="sale"), ptn_gui("TK", "R"),
		pk("TK", "KK", "stocktake", None, [dk("@A", 2, lo="@lo:PN-0002-001", gia=8500)]), kk_duyet("CHU", "KK"),
		tra_khach("CHU", "T1", [("@A", "hộp", 1, 12000)]),
		khac_frappe=["⚠K Frappe bình quân lại giá L2 khi thừa / nhập lại giá khác (§7.1); phần chênh tiền trả NCC vào 632 (nppsale không ghi)"])
	NEN75 = [*LO_P(), lo("L-RONG", "@P", "sale", 0, 0, han=300, nhan=-1), ban("CHU", "H1", [("@P", "Lon", 2)])]
	th("V75", "bao_cao_ton_kho (chủ, NVBH)", *NEN75, doc("CHU", "bao_cao_ton_kho", p_tu="@hom_nay-89", p_den="@hom_nay"),
		doc("NV", "bao_cao_ton_kho", p_tu="@hom_nay-89", p_den="@hom_nay"),
		khac_frappe=["[Frappe] lo: id <lô>::<vùng>, hạn trống → 2099-12-31, sắp id; NV: unit_cost che (❓ §7.3) — nppsale chỉ che ở giao diện"])
	COT_VSM = ["entry_code", "warehouse_zone", "signed_qty_in_base_uom", "entry_type", "entry_status", "transaction_uom", "qty_in_transaction_uom",
		"qty_in_base_uom", "conversion_factor", "unit_cost"]
	th("V76", "Thẻ kho / lịch sử tồn (v_stock_movements)", *V01, pk("TK", "CKL", "transfer", "sale", [dk("@A", 4)], dich="date"),
		chuyen("TK", "CKL"), pk("TK", "XKL", "export", "sale", [dk("@A", 2)]), xuat_le("TK", "XKL"), ban("CHU", "H1", [("@A", "hộp", 1)]),
		doc_bang("CHU", "v_stock_movements", {"product_id": "@A"}, COT_VSM),
		khac_frappe=["Màn thẻ kho: tồn đầu kỳ = Σ biến động trước hôm nay theo ngày VN; lịch sử eq entry_status posted, eq warehouse_zone, "
			"or(posted_at ≤ hôm qua 23:59:59.999+07:00 | …); 'Tồn sau' cộng dồn từng kho; chuyển kho hai dòng"])
	th("V77", "Hoá đơn mua tra cứu lọc còn nợ (mô phỏng câu cổng)", pn("TK", "P1", "@S1", [d("@A", "hộp", 1, 10000)], so_hd="HD01-A"),
		pn_hoan("TK", "P1"), pn("TK", "P2", "@S1", [d("@A", "hộp", 1, 10000)], so_hd="HD01-B"), pn_hoan("TK", "P2"),
		ghi_tra("KT", "@no:pn:P2", 10000, "cash"), pn("TK", "P3", "@S1", [d("@A", "hộp", 1, 10000)], so_hd="XX-1"), pn_hoan("TK", "P3"),
		nhap_kho("CHU", "IN1", {"entry_code": "IN-20261116-2001", "supplier_id": "@S1", "warehouse_zone": "sale",
			"payable": {"amount": 20000, "invoice_number": "HD01-C"}, "lines": [{"product_id": "@A", "unit_name": "hộp", "qty_tx": 2, "conv": 1,
				"base_qty": 2, "base_cost": 10000}]}),
		doc("CHU", "hoa_don_mua_con_no", tim="HD01"),
		khac_frappe=["Frappe: phiếu IN- có NCC + tiền nay là PN (hiện ở đây vì cổng stock_entries gồm PI docstatus 1 / 2)"])
	th("V78", "POS: phiếu nhập mới → Lưu tạm → Hoàn thành (thuế 8 % cấp phiếu, giảm dòng + giảm phiếu)", gia("CHU", [("@A", "thùng", 480000)]),
		pn("CHU", "P", "@S1", [d("@B", "gói", 5, 20000), d("@A", "thùng", 2, 480000, giam=10000, hs=24)], giam=5000, thue_tay=83600,
			xem={"subtotal": 1045000, "vat": 83600, "total": 1128600}), pn_hoan("CHU", "P"),
		khac_frappe=["màn: B lên đầu (sort_order 1), toast 'Đã lưu phiếu tạm', nhãn NHÁP → 'ĐÃ NHẬP KHO', nút trái 'Huỷ', nút chính 'Lưu sửa'"])
	th("V79", "Bảng giá nhập sửa tay (một giá + bỏ một giá)", gia("KT", [("@A", "hộp", 20000)]),
		gia("KT", [("@A", "thùng", 470000), ("@A", "hộp", None)]),
		khac_frappe=["toast 'Đã lưu bảng giá nhập — 1 giá, bỏ 1'; POS thêm A (hộp) giá gợi ý round(470000 / 24) = 19583; đổi thùng → 470000; "
			"TK không vào được /purchasing/price-list (ô purchasing.invoices)"])
	fr("V80", "Luồng cũ và bảng không port", "Gọi post_stock_export(<id>); đọc swap_stock_movements, purchase_orders, purchase_order_lines; "
		"ghi một dòng vào mỗi bảng.", "LEGACY_FLOW_REMOVED: chức năng đã gỡ (RPC và mọi lời ghi); đọc trả [] (không 404 / PGRST205).",
		_b("goi_rpc", "CHU", ten="post_stock_export", ts={"p_entry_id": "@la"}),
		*[doc_bang("CHU", b_) for b_ in ("swap_stock_movements", "purchase_orders", "purchase_order_lines")],
		*[ghi("CHU", b_, "insert", {"org_id": "@org"}, tiep=True) for b_ in ("swap_stock_movements", "purchase_orders", "purchase_order_lines")])
	th("V81", "Giá vốn kỳ: trả NCC tính vào (giá lô), xuất lẻ không", pn("CHU", "P", "@S1", [d("@A", "hộp", 50, 10000)]), pn_hoan("CHU", "P"),
		ban("CHU", "H1", [("@A", "hộp", 10)]), pk("TK", "XKL", "export", "sale", [dk("@A", 2)], ly_do_xuat="damaged"), xuat_le("TK", "XKL"),
		ptn("TK", "R", "@S1", [d("@A", "hộp", 3, 12000)], vung="sale"), ptn_gui("TK", "R"),
		doc("CHU", "finance_pnl", p_from="@hom_nay", p_to="@hom_nay"), doc("CHU", "bao_cao_so_ban", p_tu="@hom_nay", p_den="@hom_nay"),
		khac_frappe=["Frappe: dòng cổng stock_entry_lines của PTNCC unit_cost 10000 (từ SLE); tổng 130.000 nếu chốt §7.3 điểm 36 'dòng XKL unit_cost 0', "
			"150.000 nếu giữ valuation (⚠K)"])
	NEN82 = [nhap_kho("TK", "IN40", {"entry_code": "IN-20261116-4001", "warehouse_zone": "sale", "lines": [{"product_id": "@A", "unit_name": "hộp",
		"qty_tx": 10, "conv": 1, "base_qty": 10, "base_cost": 10000, "batch_code": "L-40", "expires_at": "@hom_nay+40"}]}), nguong(45)]
	NEN82B = [nhap_kho("TK", "IN90", {"entry_code": "IN-20261116-9001", "warehouse_zone": "sale", "lines": [{"product_id": "@A", "unit_name": "hộp",
		"qty_tx": 10, "conv": 1, "base_qty": 10, "base_cost": 10000, "batch_code": "L-90", "expires_at": "@hom_nay+90"}]}),
		pk("TK", "CKL", "transfer", "sale", [dk("@A", 4)], dich="date"), chuyen("TK", "CKL"), nguong(45)]
	th("V82a", "Sửa lô qua màn: hạn gửi lại không đổi vẫn đổi kho", *NEN82,
		ghi("TK", "batches", "update", {"batch_code": "L-40", "manufactured_at": None, "expires_at": "@hom_nay+40", "location": "Ke 2"},
			{"id": "@lo:L-40"}), khac_frappe=["Frappe CKL- chuyen_date_tu_dong 10 cái + npp_vi_tri 'Ke 2'"])
	th("V82b", "Sửa hạn trên dòng date của lô hai kho", *NEN82B, ghi("TK", "batches", "update", {"expires_at": "@hom_nay+20"}, {"id": "@lo:L-90@date"}),
		khac_frappe=["⚠K Frappe hạn Batch +20 cho cả hai kho, tồn kho bán (nếu còn) bị chuyển sang date"])
	th("V82c", "Sửa ngày sản xuất một lô", *NEN82, ghi("TK", "batches", "update", {"manufactured_at": "@hom_nay-10"}, {"id": "@lo:L-40"}))
	th("V82d", "Sửa giá dòng lô tồn 0 khi dòng kho kia còn tồn", *NEN82B, pk("TK", "XKL", "export", "sale", [dk("@A", 6)]), xuat_le("TK", "XKL"),
		ghi("TK", "batches", "update", {"unit_cost": 12000}, {"id": "@lo:L-90@sale"}),
		khac_frappe=["⚠K Frappe theo đề xuất → SO_KHO_KHOA: không sửa giá vốn của lô đang có tồn — … (❓ §7.3 điểm 37)"])
	th("V83", "Sửa phiếu nhập cũ thiếu payable_id khi NCC đang có trả trước", pn("TK", "P", "@S1", [d("@A", "hộp", 5, 10000)]), pn_hoan("TK", "P"),
		may_chu("UPDATE purchase_invoices SET payable_id = NULL WHERE id = {@pn:P}; DELETE FROM payables WHERE stock_entry_id = {@pk:pn:P}",
			"phiếu nhập trước mig 142: không có dòng công nợ"),
		chi("KT", "C1", "@S1", 70000), pn_sua("KT", "P", dau70("sale"), [d("@A", "hộp", 5, 10000)]), chi_nppsale=True)
	th("V84a", "Gộp NCC tăng phiên danh mục", doc_phien(), gop("KT", "@S2", "@S1"), doc_phien(),
		khac_frappe=["so MỨC TĂNG phien (sau - trước), không số tuyệt đối; nppsale +2 (UPDATE products trong vòng khoá ngoại + hành động "
			"ON DELETE SET NULL của products khi xoá NCC — cả hai kích trigger mức câu lệnh dù 0 dòng); Frappe tăng ≥ 1 (đặc tả §6.10)"])
	th("V84b", "Xoá NCC có mặt hàng chỉ có lô rỗng", ghi("TK", "batches", "insert", {"org_id": "@org", "product_id": "@R", "batch_code": "R-1",
		"expires_at": "@hom_nay+365", "qty_initial": 0, "qty_on_hand": 0, "unit_cost": 0, "warehouse_zone": "sale"}),
		gia("KT", [("@R", "cái", 5000)]), doc_phien(), xoa_ncc("CHU", "@S4", True), doc_phien(),
		khac_frappe=["Frappe: xoá Batch không SBE trước rồi delete_doc('Item'); giá nhập / giá bán của R mất theo; phien tăng (so mức tăng, "
			"không số tuyệt đối)"])
	th("V85", "Lịch sử tồn hiện ĐV giao dịch (v_stock_movements)", *V01, pk("TK", "CKL", "transfer", "sale", [dk("@A", 4)], dich="date"),
		chuyen("TK", "CKL"), doc_bang("CHU", "v_stock_movements", {"product_id": "@A"}, COT_VSM),
		khac_frappe=["Frappe theo đề xuất nối voucher_detail_no → giống; không nối → '+48 hộp (= +48)' (⚠K)"])
	th("V86", "Xoá khoản nợ của phiếu nhập / của IN- ở màn công nợ", *V01, ghi("CHU", "payables", "delete", loc={"id": "@no:pn:P"}, tiep=True),
		nhap_kho("CHU", "IN1", {"entry_code": "IN-20261116-3001", "supplier_id": "@S1", "warehouse_zone": "sale",
			"payable": {"amount": 50000, "invoice_number": "HD-IN"}, "lines": [{"product_id": "@A", "unit_name": "hộp", "qty_tx": 5, "conv": 1,
				"base_qty": 5, "base_cost": 10000}]}),
		ghi("CHU", "payables", "delete", loc={"id": "@no:pk:IN1"}), huy_pk("CHU", "IN1", "x"),
		khac_frappe=["Frappe: khoản của PN → câu theo §7.3 điểm 38 (đề xuất đúng câu 23503); IN- có NCC + tiền là PN (CFD-13) → cũng bị chặn, huỷ "
			"phải đi cancel_purchase_invoice (⚠K)"])
	th("V87", "POS trả NCC theo phiếu gốc đã khôi phục (lô của phiếu)", *V01, pn_huy("TK", "P", "x"), pn_khoi_phuc("TK", "P"),
		doc("TK", "lo_theo_phieu_goc", pn="@pn:P"),
		nguon="nppsale+dac_ta",
		khac_frappe=["[Frappe] TK /pos/tra-ncc chọn S1, phiếu gốc PN-0001-1 (tờ amend): dòng A hiện lô PN-0001-001 (hạn) — không rỗng; nppsale giữ id + "
			"receipt_code 'PN-0001' hiện lô ấy"])
	return T


# ------------------------------------------------------------------------------------------------ chuẩn hoá (bài so dùng CÙNG luật)
_RE_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_RE_XK = re.compile(r"\b(XK|NK|NL|TH)-\d{6}-\d{6}\b")
_RE_GIO_NGAY = re.compile(r"\b(\d{2}):(\d{2}) (\d{2})/(\d{2})/(\d{4})\b")
_RE_NGAY_VN = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_RE_ISO_LUC = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


def ngay_tuong(d: datetime.date, hn: datetime.date | None = None) -> str:
	"""Ngày → "@hom_nay±n" (giữ nguyên ngày xa hơn 400 ngày, vd 2099-12-31)."""
	hn = hn or _hom_nay()
	n = (d - hn).days
	if abs(n) > 400:
		return d.isoformat()
	return "@hom_nay" if n == 0 else f"@hom_nay{n:+d}"


def chuan_loi(s: str | None, id_khoa: dict | None = None, hn: datetime.date | None = None) -> str | None:
	"""Câu lỗi → dạng so được: mã XK-/NK-/NL- theo giờ → "XK-<giờ>"; "HH:MI DD/MM/YYYY" → "<HH:MI @hom_nay±n>" (giờ phụ thuộc lúc chạy);
	"DD/MM/YYYY" → "<@hom_nay±n>"; uuid → khoá nghiệp vụ "<pn:P>" / "<id>"."""
	if s is None:
		return s
	hn = hn or _hom_nay()
	s = _RE_XK.sub(lambda m: m.group(1) + "-<giờ>", s)
	s = _RE_GIO_NGAY.sub(lambda m: "<HH:MI " + ngay_tuong(datetime.date(int(m.group(5)), int(m.group(4)), int(m.group(3))), hn) + ">", s)
	s = _RE_NGAY_VN.sub(lambda m: "<" + ngay_tuong(datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1))), hn) + ">", s)
	return _RE_UUID.sub(lambda m: "<" + (id_khoa or {}).get(m.group(0), "id") + ">", s)


def chuan_gt(v, id_khoa: dict, hn: datetime.date | None = None, khoa: str | None = None):
	"""Số trả về của bước / dòng đọc bảng → khoá nghiệp vụ: uuid → id_khoa (không biết → "@id"); ngày ISO → "@hom_nay±n"; mốc giờ ISO →
	"@luc_goi" (trong lượt chạy, ±10 phút) hoặc "@hom_nay±nTHH:MI" (giờ VN); mã XK-… → "XK-<giờ>"."""
	hn = hn or _hom_nay()
	if isinstance(v, dict):
		return {a: chuan_gt(b, id_khoa, hn, a) for a, b in v.items()}
	if isinstance(v, list):
		return [chuan_gt(x, id_khoa, hn) for x in v]
	if not isinstance(v, str):
		return v
	if _RE_UUID.fullmatch(v):
		return id_khoa.get(v, "@id")
	if _RE_ISO_LUC.match(v):
		try:
			t = datetime.datetime.fromisoformat(v)
		except ValueError:
			return v
		if t.tzinfo is None:
			t = t.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=7)))
		vn = t.astimezone(datetime.timezone(datetime.timedelta(hours=7)))
		if abs((datetime.datetime.now(datetime.UTC) - t).total_seconds()) < 3600:
			return "@luc_goi"
		return ngay_tuong(vn.date(), hn) + "T" + vn.strftime("%H:%M")
	if len(v) == 10 and v[4] == "-" and v[7] == "-":
		try:
			return ngay_tuong(datetime.date.fromisoformat(v), hn)
		except ValueError:
			return v
	return _RE_XK.sub(lambda m: m.group(1) + "-<giờ>", v)


def _chuan(k: dict) -> dict:
	hn = _hom_nay()
	ct = k.get("ct") or {}
	id_khoa = ct.pop("id_khoa", None) or {}
	nhan = ct.pop("nhan", None) or {}
	for a, v in nhan.items():  # nhãn của chứng từ đã bị xoá vẫn đổi được
		id_khoa.setdefault(v, a)
	buoc = []
	for x in k.get("buoc") or []:
		if x.get("ok"):
			y = {"ok": True}
			if x.get("tra") is not None:
				y["tra"] = chuan_gt(x["tra"], id_khoa, hn)
		else:
			y = {"ok": False, "ma_loi": x.get("ma_loi"), "loi": chuan_loi(x.get("loi"), id_khoa, hn)}
		buoc.append(y)
	ct["nhan"] = sorted(nhan)

	def chuoi(v):  # chữ trong ảnh chụp (ghi chú gộp NCC "ngày dd/mm/yyyy"…) — cùng luật câu lỗi
		if isinstance(v, dict):
			return {a: chuoi(b) for a, b in v.items()}
		if isinstance(v, list):
			return [chuoi(x) for x in v]
		return chuan_loi(v, id_khoa, hn) if isinstance(v, str) else v

	return {"buoc": buoc, "ct": chuoi(ct)}


# ------------------------------------------------------------------------------------------------ chạy
NEN_TINH = ("ncc", "hang", "phan_cong")  # mục ảnh chụp chỉ ghi khi khác bộ dữ liệu nền

QUY_UOC = [
	"Mỗi kịch bản chạy trong một giao dịch con rồi lui; mỗi bước dưới đúng người; bước hỏng thì DỪNG — trừ bước \"tiep\": true (bước chờ lỗi: "
	"lỗi được ghi, bước lui về điểm lưu riêng, chạy tiếp).",
	"Bước \"chi_nppsale\": true (và kịch bản \"chi_nppsale\": true) là tình huống chỉ có ở nppsale (NPP thứ hai, dữ liệu cũ đặt bằng quyền máy chủ) "
	"— bản Frappe bỏ qua bước / kịch bản ấy.",
	"Kịch bản \"nguon\": \"dac_ta\" là [Frappe] — không chạy nppsale, \"mong.dac_ta\" chép từ đặc tả; \"nguon\": \"nppsale+dac_ta\" có cả kết quả "
	"nppsale (tham khảo) lẫn kỳ vọng Frappe ở \"khac_frappe\". \"khac_frappe\" = chỗ Frappe khác nppsale có chủ ý (⚠K) / chờ chốt (❓) — so theo đó.",
	"Tải trọng: chỗ giữ \"@…\" (xem docstring tools/vang_kho_mua.py); ngày \"@hom_nay±n\" = ngày VN hôm nay ± n; mốc giờ \"@hom_nay±nTHH:MM:SS+07:00\".",
	"Kết quả bước: {ok, tra} hoặc {ok: false, ma_loi (SQLSTATE), loi}; câu lỗi so TỪNG KÝ TỰ sau chuan_loi: XK-/NK-/NL-YYMMDD-HHMMSS → "
	"\"XK-<giờ>\"; \"HH:MI DD/MM/YYYY\" → \"<HH:MI @hom_nay±n>\"; \"DD/MM/YYYY\" → \"<@hom_nay±n>\"; uuid → \"<khoá>\" (\"<pn:P>\", \"<id>\").",
	"Số trả về / dòng đọc bảng sau chuan_gt: uuid → khoá nghiệp vụ (pn:<nhãn|mã>, ptn:…, pk:<nhãn|mã>, no:<khoá nợ>, tra:<khoá nợ>, lo:<mã>@<vùng>, "
	"pc:<mã>, cp:<tham chiếu>, hd:…, tk:…, @u:<người>, @S1, @A…; không biết → \"@id\"); ngày → \"@hom_nay±n\"; mốc giờ trong lượt → \"@luc_goi\".",
	"Ảnh chụp ct: chữ qua cùng chuan_loi (ngày dd/mm/yyyy trong ghi chú → \"<@hom_nay±n>\"); trường null bị bỏ (jsonb_strip_nulls); khoá nợ: PN:<mã PN> | PTNCC:<mã> | DK:<NCC> | TT:<mã phiếu chi> | PK:<mã phiếu kho>"
	"[:<số HĐ NCC>] | TAY:<số HĐ NCC>; lô theo (mặt hàng, mã, vùng); mốc giờ \"@luc_goi\" (lúc gọi) hoặc \"@hom_nay±nTHH:MI\" (dựng sẵn / ghi lùi).",
	"Mục ảnh chụp ncc / hang / phan_cong chỉ có khi khác bộ dữ liệu nền (\"nen.ct_nen\"); vắng mặt = như nền.",
	"Tiền: nppsale numeric không làm tròn (13332.60) — Frappe làm tròn đồng, chênh < 1 đ / phiếu được (BP §7.2 điểm 3). Phiếu kho so theo "
	"(mặt hàng, lô, qty_in_base_uom), không so quantity (§4.5 ⚠K).",
	"Bộ sinh đặt TimeZone phiên = Asia/Ho_Chi_Minh: CURRENT_DATE của nppsale = ngày VN (như chạy 07:00-23:59 VN, §6.0); giờ trong ALREADY_POSTED "
	"vì thế là giờ VN.",
]


def chay(T: list[dict], them_sql: str = "", psql: str = PSQL) -> dict:
	"""Chạy các kịch bản (bỏ [Frappe]) trong MỘT giao dịch rồi lui; trả {mã: {buoc, ct}} đã chuẩn hoá (+ "_NEN"). them_sql chèn ngay sau
	hàm phụ (thử phá: CREATE OR REPLACE một hàm nppsale đã sửa — vẫn trong giao dịch, lui cùng)."""
	chay_ = [t for t in T if t.get("nguon") != "dac_ta"]
	sql = ["BEGIN;", sql_nen(), sql_ham_phu(), them_sql, "CREATE TEMP TABLE _vang_kq (ma text, buoc jsonb, ct jsonb);"]
	sql += [sql_tinh_huong(t) for t in [{"ma": "_NEN", "buoc": []}, *chay_]]
	sql.append("SELECT json_agg(json_build_object('ma', ma, 'buoc', buoc, 'ct', ct)) FROM _vang_kq;")
	sql.append("ROLLBACK;")
	ra = subprocess.run(psql, shell=True, input="\n".join(sql), capture_output=True, text=True, check=False)
	if ra.returncode != 0:
		raise SystemExit(ra.stderr[-6000:])
	kq = {k["ma"]: _chuan(k) for k in json.loads(ra.stdout.strip().splitlines()[-1])}
	nen_ct = kq["_NEN"]["ct"]
	for ma, k in kq.items():  # danh mục không đổi so với nền → bỏ (ảnh chụp chỉ mang phần khác nền)
		if ma == "_NEN":
			continue
		for muc in NEN_TINH:
			if k["ct"].get(muc) == nen_ct.get(muc):
				k["ct"].pop(muc, None)
	return kq


def main():
	import argparse

	ap = argparse.ArgumentParser()
	ap.add_argument("--chi", help="chỉ chạy các kịch bản có mã bắt đầu bằng (phẩy ngăn) — không ghi tệp vàng, in kết quả")
	ap.add_argument("--psql", default=PSQL)
	a = ap.parse_args()
	T = tinh_huong()
	if a.chi:
		T = [t for t in T if any(t["ma"].startswith(x) for x in a.chi.split(","))]
	kq = chay(T, psql=a.psql)
	nen_ct = kq.pop("_NEN")["ct"]
	if a.chi:
		for t in T:
			if t["ma"] in kq:
				print(json.dumps({"ma": t["ma"], **kq[t["ma"]]}, ensure_ascii=False, indent=1))
		return
	ra_t = []
	for t in T:
		x = dict(t)
		x.setdefault("nguon", "nppsale")
		if t.get("nguon") != "dac_ta":
			x["mong"] = kq[t["ma"]]
		ra_t.append(x)
	tep = {"ghi_chu": "Sinh bởi tools/vang_kho_mua.py — hàm + trigger + RLS thật của nppsale (Postgres tham chiếu): phiếu nhập, giá nhập, nhập kho tay, "
		"trả NCC, công nợ NCC / Ghi trả / phiếu chi, gộp / xoá NCC, phiếu kho (xuất lẻ, chuyển kho, kiểm kê, huỷ), lô / kho cận date. Đặc tả P4 §6.",
		"quy_uoc": QUY_UOC, "buoc_mo_ta": {k: " ".join(v.split()) for k, v in BUOC_MO_TA.items()},
		"nen": {"org": ORG, "org_b": ORG_B, "la": LA, "nguoi": NGUOI, "ncc": NCC, "hang": HANG, "hang_frappe": HANG_FRAPPE, "khach": KHACH,
			"gia_ban": GIA_BAN, "danh_muc_chi_phi": DANH_MUC_CP, "cho_ban_vuot_ton": False, "nguong_kho_date_ngay": 30, "id": KHOA_TINH,
			"ct_nen": {m: nen_ct.get(m) for m in NEN_TINH}},
		"tinh_huong": ra_t}
	with open(DICH, "w", encoding="utf-8") as f:
		json.dump(tep, f, ensure_ascii=False, indent=1)
		f.write("\n")
	so_v = sorted({re.match(r"V\d+", t["ma"]).group(0) for t in T})
	chay_ = [t for t in T if t.get("nguon") != "dac_ta"]
	print(f"{len(T)} kịch bản ({len(chay_)} chạy nppsale, {len(T) - len(chay_)} [Frappe]) phủ {len(so_v)} mã V → {DICH}")
	for t in chay_:
		k = kq[t["ma"]]
		bs = " | ".join("ok" if x["ok"] else f"{x['ma_loi']} {x['loi'][:90]}" for x in k["buoc"])
		print(f"  {t['ma']:<6} {bs[:400]}")


if __name__ == "__main__":
	main()
