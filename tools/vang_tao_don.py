#!/usr/bin/env python3
"""Sinh dữ liệu vàng cho RPC `create_order_with_lines` bằng CHÍNH hàm + trigger của nppsale trên Postgres tham chiếu (dựng từ
supabase/schema_full.sql). Mỗi tình huống chạy thật dưới vai `authenticated` (RLS + trigger như production), kết quả được ghi
lại rồi lui về — sổ tham chiếu không giữ gì.

	python3 tools/vang_tao_don.py [--psql "<lệnh psql>"]   → nppsale/tests/du_lieu/tao_don_mau.json

Tệp JSON mang cả định nghĩa tình huống (khoá tượng trưng: "@C1" = khách C1, "@P1" = mặt hàng P1, "@u:sales_a" = nhân viên) lẫn
kết quả mong đợi; tests/test_tao_don.py dựng cùng bộ dữ liệu trên site Frappe và so từng tình huống.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import uuid

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICH = os.path.join(GOC, "nppsale", "tests", "du_lieu", "tao_don_mau.json")
PSQL = "runuser -u postgres -- psql -h /tmp/pg-npp/sock -p 55500 -U postgres -d npp -X -q -t -A -v ON_ERROR_STOP=1"

NS = uuid.UUID("6f1c2a52-6b3e-4d8b-9a55-0e6c1d2f3a40")


def uid(k: str) -> str:
	return str(uuid.uuid5(NS, k))


ORG = uid("org")

# ---------------------------------------------------------------- dữ liệu nền (cùng bộ dựng lại trên Frappe ở test_tao_don.py)
NGUOI = {
	# khoá: (vai, cho_sua_gia, tran_tang_gia, cho_giam_gia, kieu_tran, tran_giam (None = không trần), đang làm)
	"owner": ("owner", False, 0, False, "pct", None, True),
	"accountant": ("accountant", False, 0, False, "pct", None, True),
	"manager": ("manager", False, 0, False, "pct", None, True),
	"manager_nang10": ("manager", False, 10, True, "pct", None, True),
	"sales_a": ("sales", False, 0, False, "pct", None, True),
	"sales_b": ("sales", False, 0, False, "pct", None, True),
	"sales_giam": ("sales", False, 0, True, "pct", None, True),
	"sales_giam5": ("sales", False, 0, True, "pct", 5, True),
	"sales_giam20k": ("sales", False, 0, True, "vnd", 20000, True),
	"sales_nang10": ("sales", True, 10, False, "pct", None, True),
	"sales_nang_khong_co": ("sales", False, 15, False, "pct", None, True),
	"warehouse": ("warehouse", False, 0, False, "pct", None, True),
	"sales_nghi": ("sales", False, 0, False, "pct", None, False),
}
NHOM = {"G1": "VTD Nhom 1"}
KHACH = {"C1": ("Tap hoa VTD 1", "G1"), "C2": ("Tap hoa VTD 2", None)}
# mặt hàng: (sku, tên, đơn vị cơ sở, giá bán cơ sở, thuế mặc định, {đơn vị: hệ số})
HANG = {
	"P1": ("VTD-P1", "Nuoc ngot VTD", "Lon", 10000, 0.08, {"Thung": 24, "Loc": 6}),
	"P2": ("VTD-P2", "Dau an VTD", "Chai", 5000, 0.1, {"Hop": 10}),
	"P3": ("VTD-P3", "Hang chua gia VTD", "Goi", 0, 0, {}),
}
# bảng giá: (mặt hàng, nhóm hoặc None = Gia chuan, đơn vị, giá)
GIA = [("P1", None, "Lon", 10000), ("P1", None, "Thung", 230000), ("P1", "G1", "Lon", 9500)]


def ref(v):
	if isinstance(v, str) and v.startswith("@"):
		k = v[1:]
		if k.startswith("u:"):
			return uid("u:" + k[2:])
		return uid(k)
	if isinstance(v, dict):
		return {a: ref(b) for a, b in v.items()}
	if isinstance(v, list):
		return [ref(x) for x in v]
	return v


def sql_nen() -> str:
	q = ["GRANT USAGE ON SCHEMA public, auth TO authenticated;",
		"GRANT ALL ON ALL TABLES IN SCHEMA public TO authenticated;",
		"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated;",
		f"INSERT INTO organizations (id, name, slug) VALUES ('{ORG}', 'NPP VTD', 'npp-vtd');"]
	for k, (vai, sua, nang, giam, kieu, tran, lam) in NGUOI.items():
		i = uid("u:" + k)
		q.append(f"INSERT INTO auth.users (id) VALUES ('{i}');")
		q.append("INSERT INTO users (id, org_id, full_name, role, is_active, allow_price_edit, price_edit_max_increase_pct, allow_discount, "
			f"discount_max_type, discount_max_value) VALUES ('{i}', '{ORG}', '{k}', '{vai}', {str(lam).lower()}, {str(sua).lower()}, {nang}, "
			f"{str(giam).lower()}, '{kieu}', {'NULL' if tran is None else tran});")
	for k, ten in NHOM.items():
		q.append(f"INSERT INTO customer_groups (id, org_id, name) VALUES ('{uid(k)}', '{ORG}', '{ten}');")
	for i, (k, (ten, nhom)) in enumerate(KHACH.items()):
		nhom_sql = "'" + uid(nhom) + "'" if nhom else "NULL"
		q.append("INSERT INTO customers (id, org_id, store_name, owner_name, phone, address, group_id) VALUES "
			f"('{uid(k)}', '{ORG}', '{ten}', 'Chu', '09000000{i + 1:02d}', 'Dia chi', {nhom_sql});")
	for k, (sku, ten, dv, gia, thue, dvs) in HANG.items():
		q.append("INSERT INTO products (id, org_id, sku, name, base_unit, sell_price, vat_rate) VALUES "
			f"('{uid(k)}', '{ORG}', '{sku}', '{ten}', '{dv}', {gia}, {thue});")
		for d, hs in dvs.items():
			q.append(f"INSERT INTO product_units (product_id, unit_name, conversion) VALUES ('{uid(k)}', '{d}', {hs});")
	for sp, nhom, dv, gia in GIA:
		nhom_sql = "'" + uid(nhom) + "'" if nhom else "NULL"
		q.append(f"INSERT INTO price_lists (product_id, group_id, unit_name, price) VALUES ('{uid(sp)}', {nhom_sql}, '{dv}', {gia});")
	return "\n".join(q)


# ---------------------------------------------------------------- tình huống
def don(khach="@C1", **k):
	o = {"order_code": "TAM-1", "customer_id": khach, "payment_terms": "COD", "expected_delivery": None, "subtotal": 0, "vat": 0,
		"total": 0, "notes": None, "status": "draft", "approval_reason": None, "sales_user_id": None}
	o.update(k)
	return o


def dong(sp="@P1", dv="Lon", sl=1, gia=10000, giam=0, hs=1, thue=0.08, **k):
	d = {"product_id": sp, "unit_name": dv, "quantity": sl, "unit_price": gia, "line_discount": giam, "line_total": round(sl * gia),
		"conversion_factor": hs, "vat_rate": thue}
	d.update(k)
	return d


def _thue(v):
	"""Thuế dòng màn hình dùng để cộng VAT — cùng luật hợp lệ với _thue_hop_le (chuỗi / số 0..1), còn lại 0."""
	try:
		x = float(v)
	except (TypeError, ValueError):
		return 0
	return x if not isinstance(v, bool) and 0 <= x <= 1 else 0


def tong(lines, giam_don=0, tru=0):
	tien = round(sum(d["quantity"] * d["unit_price"] for d in lines))
	vat = round(sum(d["quantity"] * d["unit_price"] * _thue(d.get("vat_rate")) for d in lines))
	sub = tien - giam_don
	return {"subtotal": sub, "vat": vat, "total": max(0, sub + vat - tru)}


def th(ma, nguoi, lines, *, khach="@C1", crid=None, goi_lai=False, giam_don=0, tru=0, o=None, bo=None):
	"""Một tình huống: nguoi gọi create_order_with_lines với các dòng; giam_don / tru → subtotal / total như màn POS gửi."""
	t = tong(lines, giam_don, tru)
	oo = don(khach, **t)
	oo.update(o or {})
	p = {"client_request_id": str(uuid.uuid5(NS, "crid:" + ma)) if crid is None else crid, "order": oo, "lines": lines, "returns": None, "return_lines": []}
	for k in bo or []:
		p.pop(k, None)
	return {"ma": ma, "nguoi": nguoi, "p": p, "goi_lai": goi_lai}


def tinh_huong() -> list[dict]:
	T = []
	# --- đúng giá bảng, các vai
	for n in ("owner", "accountant", "manager", "sales_a", "sales_giam"):
		T.append(th(f"dung_gia_{n}", n, [dong(gia=9500), dong(sp="@P2", dv="Chai", gia=5000, thue=0.1)]))
	T.append(th("kho_khong_lap_don", "warehouse", [dong(gia=9500)]))
	T.append(th("nv_nghi_khong_lap_don", "sales_nghi", [dong(gia=9500)]))
	# --- giá bảng theo nhóm / chuẩn / đơn vị quy đổi (khách C2 không nhóm)
	T.append(th("c2_gia_chuan", "sales_a", [dong(gia=10000)], khach="@C2"))
	T.append(th("c2_duoi_gia_chuan", "sales_a", [dong(gia=9500)], khach="@C2"))
	T.append(th("thung_gia_rieng", "sales_a", [dong(dv="Thung", hs=24, gia=230000)], khach="@C2"))
	T.append(th("thung_duoi_gia_rieng", "sales_a", [dong(dv="Thung", hs=24, gia=228000)], khach="@C2"))
	T.append(th("loc_quy_doi_nhom", "sales_a", [dong(dv="Loc", hs=6, gia=57000)]))
	T.append(th("loc_quy_doi_duoi", "sales_a", [dong(dv="Loc", hs=6, gia=56000)]))
	T.append(th("loc_quy_doi_chuan", "sales_a", [dong(dv="Loc", hs=6, gia=60000)], khach="@C2"))
	T.append(th("hop_quy_doi_gia_sp", "sales_a", [dong(sp="@P2", dv="Hop", hs=10, gia=50000, thue=0.1)]))
	T.append(th("hop_duoi_gia_sp", "sales_a", [dong(sp="@P2", dv="Hop", hs=10, gia=49000, thue=0.1)]))
	T.append(th("chua_co_gia_ban_bat_ky", "sales_a", [dong(sp="@P3", dv="Goi", gia=1234, thue=0)]))
	T.append(th("chua_co_gia_ban_0", "sales_a", [dong(sp="@P3", dv="Goi", gia=0, thue=0)]))
	# --- sai số làm tròn: SL × 0,5 + 1
	T.append(th("duoi_gia_trong_sai_so", "sales_a", [dong(sl=4, gia=9497)]))  # giảm 12 ≤ 4×0,5+1 = 3? (không) → lỗi
	T.append(th("duoi_gia_1d_sl1", "sales_a", [dong(sl=1, gia=9499)]))  # giảm 1 ≤ 1,5
	T.append(th("duoi_gia_2d_sl1", "sales_a", [dong(sl=1, gia=9498)]))  # giảm 2 > 1,5
	T.append(th("duoi_gia_sl10_6d", "sales_a", [dong(sl=10, gia=9499.4)]))  # giảm 6 ≤ 6
	# --- giảm dòng có quyền / trần
	T.append(th("giam_co_quyen", "sales_giam", [dong(sl=2, gia=9000, giam=1000)]))
	T.append(th("giam_tran5_trong", "sales_giam5", [dong(sl=10, gia=9025)]))  # giảm 4.750 ≤ 5% × 95.000 = 4.750
	T.append(th("giam_tran5_vuot", "sales_giam5", [dong(sl=10, gia=9000)]))  # giảm 5.000 > 4.750 + 6
	T.append(th("giam_tran_vnd_trong", "sales_giam20k", [dong(sl=10, gia=7500)]))  # 20.000
	T.append(th("giam_tran_vnd_vuot", "sales_giam20k", [dong(sl=10, gia=7400)]))  # 21.000
	T.append(th("giam_dong_khai_ro", "sales_giam5", [dong(sl=1, gia=9500, giam=600)]))  # khai giảm 600 > 5% của 10.100 = 505 + 1,5
	T.append(th("giam_dong_khai_khong_quyen", "sales_a", [dong(sl=1, gia=9500, giam=500)]))
	T.append(th("manager_giam_khong_tran", "manager_nang10", [dong(sl=3, gia=5000)]))
	T.append(th("manager_khong_quyen_giam", "manager", [dong(sl=3, gia=9000)]))
	T.append(th("owner_giam_tuy_y", "owner", [dong(sl=3, gia=1)]))
	T.append(th("ke_toan_giam_tuy_y", "accountant", [dong(sl=3, gia=1)]))
	# --- nâng giá: trần = round(giá bảng × (1 + pct)) + 1
	T.append(th("nang_khong_quyen_1d", "sales_a", [dong(gia=9501)]))
	T.append(th("nang_khong_quyen_2d", "sales_a", [dong(gia=9502)]))
	T.append(th("nang10_trong", "sales_nang10", [dong(gia=10450)]))
	T.append(th("nang10_vuot", "sales_nang10", [dong(gia=10452)]))
	T.append(th("nang_sales_khong_co_quyen_15", "sales_nang_khong_co", [dong(gia=10000)]))
	T.append(th("manager_nang10_trong", "manager_nang10", [dong(gia=10450)]))
	T.append(th("manager_nang0_vuot", "manager", [dong(gia=9600)]))
	T.append(th("nang_kem_giam_dong", "sales_nang10", [dong(sl=2, gia=10400, giam=200)]))  # trước giảm 10.500 > 10.451
	T.append(th("nang_chua_co_gia", "sales_a", [dong(sp="@P3", dv="Goi", gia=99999, thue=0)]))
	# --- dữ liệu dòng hỏng
	T.append(th("sl_0", "sales_a", [dong(sl=0)]))
	T.append(th("sl_am", "owner", [dong(sl=-2)]))
	T.append(th("gia_am", "owner", [dong(gia=-1)]))
	T.append(th("giam_am", "owner", [dong(giam=-5)]))
	T.append(th("dv_rong_he_so_1", "sales_a", [dong(dv="", gia=9500)]))
	T.append(th("dv_rong_he_so_6", "sales_a", [dong(dv="", hs=6, gia=9500)]))
	T.append(th("dv_null", "owner", [dong(dv=None, gia=9500)]))
	T.append(th("thue_8_khong_hop_le", "sales_a", [dong(gia=9500, thue=8)]))
	T.append(th("thue_chuoi", "sales_a", [dong(gia=9500, thue="0.1")]))
	T.append(th("thue_thieu", "sales_a", [{k: v for k, v in dong(gia=9500).items() if k != "vat_rate"}]))
	T.append(th("ghi_chu_dong", "sales_a", [dong(gia=9500, note="giao sang"), dong(gia=9500, note="")]))
	T.append(th("hang_khong_co", "owner", [dong(sp="@P9", gia=1000)]))
	# --- giảm giá cả đơn (kiểm cuối giao dịch)
	T.append(th("giam_don_khong_quyen", "sales_a", [dong(sl=2, gia=9500)], giam_don=1000))
	T.append(th("giam_don_trong_sai_so", "sales_a", [dong(sl=2, gia=9500), dong(sp="@P2", dv="Chai", gia=5000, thue=0.1)], giam_don=2))
	T.append(th("giam_don_vuot_sai_so", "sales_a", [dong(sl=2, gia=9500), dong(sp="@P2", dv="Chai", gia=5000, thue=0.1)], giam_don=3))
	T.append(th("giam_don_co_quyen", "sales_giam", [dong(sl=2, gia=9500)], giam_don=5000))
	T.append(th("giam_don_tran5_trong", "sales_giam5", [dong(sl=10, gia=9500)], giam_don=4750))
	T.append(th("giam_don_tran5_vuot", "sales_giam5", [dong(sl=10, gia=9500)], giam_don=4753))
	T.append(th("giam_don_tran_vnd", "sales_giam20k", [dong(sl=10, gia=9500)], giam_don=20002))
	T.append(th("giam_don_tran_vnd_vuot", "sales_giam20k", [dong(sl=10, gia=9500)], giam_don=20003))
	T.append(th("giam_don_chu", "owner", [dong(sl=10, gia=9500)], giam_don=50000))
	T.append(th("giam_don_cong_giam_dong", "sales_giam5", [dong(sl=10, gia=9500, giam=1000)], giam_don=4800))  # trước giảm 9.600 > trần
	T.append(th("giam_don_nen_gom_giam_dong", "sales_giam5", [dong(sl=10, gia=9400, giam=1000)], giam_don=4752))  # nền 95.000 → 4.750+2
	T.append(th("giam_don_nen_gom_giam_dong_vuot", "sales_giam5", [dong(sl=10, gia=9400, giam=1000)], giam_don=4753))
	T.append(th("tru_hang_tra", "sales_a", [dong(sl=2, gia=9500)], tru=5000))
	# --- trạng thái
	T.append(th("gui_luon", "sales_a", [dong(gia=9500)], o={"status": "submitted", "approval_reason": "Vuot han muc"}))
	T.append(th("trang_thai_rong", "sales_a", [dong(gia=9500)], o={"status": ""}))
	T.append(th("trang_thai_huy", "sales_a", [dong(gia=9500)], o={"status": "cancelled"}))
	T.append(th("trang_thai_hoan_thanh", "owner", [dong(gia=9500)], o={"status": "completed"}))
	T.append(th("trang_thai_la", "owner", [dong(gia=9500)], o={"status": "approved"}))
	# --- người đứng tên
	T.append(th("chu_lap_ho_sales", "owner", [dong(gia=9500)], o={"sales_user_id": "@u:sales_a"}))
	T.append(th("quan_ly_lap_ho_sales", "manager", [dong(gia=9500)], o={"sales_user_id": "@u:sales_a"}))
	T.append(th("sales_lap_ho_sales", "sales_a", [dong(gia=9500)], o={"sales_user_id": "@u:sales_b"}))
	T.append(th("chu_lap_ho_kho", "owner", [dong(gia=9500)], o={"sales_user_id": "@u:warehouse"}))
	T.append(th("chu_lap_ho_nguoi_la", "owner", [dong(gia=9500)], o={"sales_user_id": "@u:khong_co"}))
	T.append(th("sales_ten_minh", "sales_a", [dong(gia=9500)], o={"sales_user_id": "@u:sales_a"}))
	T.append(th("chu_lap_ho_nv_nghi", "owner", [dong(gia=9500)], o={"sales_user_id": "@u:sales_nghi"}))
	T.append(th("lap_ho_giam_theo_nguoi_goi", "owner", [dong(sl=3, gia=1)], o={"sales_user_id": "@u:sales_a"}))
	T.append(th("ql_lap_ho_nhap_kin", "manager", [dong(gia=9500)], o={"sales_user_id": "@u:sales_a"}, goi_lai=True))
	T.append(th("chu_lap_ho_sales_gui", "owner", [dong(gia=9500)], o={"sales_user_id": "@u:sales_a", "status": "submitted"}))
	T.append(th("ql_lap_ho_sales_gui", "manager", [dong(gia=9500)], o={"sales_user_id": "@u:sales_a", "status": "submitted"},
		goi_lai=True))
	T.append(th("chu_lap_ho_nv_nghi_gui", "owner", [dong(gia=9500)], o={"sales_user_id": "@u:sales_nghi", "status": "submitted"}))
	T.append(th("lap_ho_gui_giam_theo_nguoi_goi", "owner", [dong(sl=3, gia=1)], o={"sales_user_id": "@u:sales_a",
		"status": "submitted"}))
	T.append(th("ql_lap_ho_gui_khong_quyen_giam", "manager", [dong(sl=3, gia=9000)], o={"sales_user_id": "@u:sales_giam",
		"status": "submitted"}))
	T.append(th("sales_gui_ten_minh_goi_lai", "sales_a", [dong(gia=9500)], o={"status": "submitted"}, goi_lai=True))
	# --- tải trọng hỏng / gọi lại
	T.append(th("thieu_crid", "sales_a", [dong(gia=9500)], crid=""))
	T.append(th("crid_hong", "sales_a", [dong(gia=9500)], crid="khong-phai-uuid"))
	T.append(th("crid_hoa", "sales_a", [dong(gia=9500)], crid="6F1C2A52-6B3E-4D8B-9A55-0E6C1D2F3A99"))
	T.append(th("khong_dong", "sales_a", []))
	T.append(th("dong_khong_phai_mang", "sales_a", [dong(gia=9500)], bo=["lines"]))
	T.append(th("khach_khong_co", "sales_a", [dong(gia=9500)], khach="@C9"))
	T.append(th("goi_lai_cung_crid", "sales_a", [dong(gia=9500)], goi_lai=True))
	T.append(th("dieu_khoan_net30", "sales_a", [dong(gia=9500)], o={"payment_terms": "NET30", "expected_delivery": "2026-12-01",
		"notes": "Giao buoi sang"}))
	T.append(th("dieu_khoan_rong", "sales_a", [dong(gia=9500)], o={"payment_terms": ""}))
	return T


# ---------------------------------------------------------------- chạy trên Postgres tham chiếu
def _lit(s: str) -> str:
	return "'" + s.replace("'", "''") + "'"


def sql_tinh_huong(t: dict) -> str:
	p = json.dumps(ref(t["p"]), ensure_ascii=False)
	u = uid("u:" + t["nguoi"])
	lan = 2 if t["goi_lai"] else 1
	return f"""
DO $c$
DECLARE
  v_ok boolean := false; v_loi text; v_ma text; v_ct jsonb; v_lan jsonb := '[]'::jsonb; r record; i int; v_don uuid;
BEGIN
  BEGIN
    EXECUTE 'SET CONSTRAINTS ALL DEFERRED';  -- mỗi tình huống = giao dịch mới: ràng buộc hoãn về mặc định
    PERFORM set_config('request.jwt.claim.sub', {_lit(u)}, true);
    EXECUTE 'SET LOCAL ROLE authenticated';
    FOR i IN 1..{lan} LOOP
      SELECT * INTO r FROM public.create_order_with_lines({_lit(p)}::jsonb);
      EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';
      v_lan := v_lan || jsonb_build_object('already_existed', r.already_existed, 'giong_don', r.order_id = COALESCE(v_don, r.order_id));
      v_don := r.order_id;
    END LOOP;
    EXECUTE 'RESET ROLE';
    SELECT jsonb_build_object(
      'status', so.status, 'sales_user', (SELECT u.full_name FROM users u WHERE u.id = so.sales_user_id),
      'created_by', (SELECT u.full_name FROM users u WHERE u.id = so.created_by),
      'payment_terms', so.payment_terms, 'expected_delivery', so.expected_delivery, 'notes', so.notes,
      'subtotal', so.subtotal, 'vat', so.vat, 'total', so.total, 'approval_reason', so.approval_reason,
      'co_submitted_at', so.submitted_at IS NOT NULL, 'giam_don', public._giam_don_hien_tai(so.id),
      'lich_su', (SELECT jsonb_agg(jsonb_build_array(h.from_status, h.to_status) ORDER BY h.changed_at) FROM order_status_history h
        WHERE h.order_id = so.id),
      'dong', (SELECT jsonb_agg(jsonb_build_object('sp', (SELECT p.sku FROM products p WHERE p.id = l.product_id), 'dv', l.unit_name,
        'sl', l.quantity, 'gia', l.unit_price, 'giam', l.line_discount, 'hs', l.conversion_factor, 'thue', l.vat_rate,
        'ghi_chu', l.note) ORDER BY l.ctid) FROM sales_order_lines l WHERE l.order_id = so.id),
      'lan', v_lan)
      INTO v_ct FROM sales_orders so WHERE so.id = v_don;
    v_ok := true;
    RAISE EXCEPTION USING ERRCODE = 'ZZ999';
  EXCEPTION
    WHEN SQLSTATE 'ZZ999' THEN NULL;
    WHEN OTHERS THEN v_ok := false; v_loi := SQLERRM; v_ma := SQLSTATE;
  END;
  INSERT INTO _vang_kq VALUES ({_lit(t['ma'])}, v_ok, v_ma, v_loi, v_ct);
END $c$;
"""


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--psql", default=PSQL)
	a = ap.parse_args()
	T = tinh_huong()
	sql = ["BEGIN;", sql_nen(), "CREATE TEMP TABLE _vang_kq (ma text, ok boolean, ma_loi text, loi text, ct jsonb);"]
	sql += [sql_tinh_huong(t) for t in T]
	sql.append("SELECT json_agg(json_build_object('ma', ma, 'ok', ok, 'ma_loi', ma_loi, 'loi', loi, 'ct', ct)) FROM _vang_kq;")
	sql.append("ROLLBACK;")
	ra = subprocess.run(a.psql, shell=True, input="\n".join(sql), capture_output=True, text=True, check=False)
	if ra.returncode != 0:
		raise SystemExit(ra.stderr[-4000:])
	kq = {k["ma"]: k for k in json.loads(ra.stdout.strip().splitlines()[-1])}
	ra_tep = {"ghi_chu": "Sinh bởi tools/vang_tao_don.py từ create_order_with_lines + trigger thật của nppsale (schema_full.sql).",
		"nen": {"nguoi": NGUOI, "nhom": NHOM, "khach": KHACH, "hang": HANG, "gia": GIA},
		"tinh_huong": [dict(t, mong=kq[t["ma"]]) for t in T]}
	with open(DICH, "w", encoding="utf-8") as f:
		json.dump(ra_tep, f, ensure_ascii=False, indent=1)
		f.write("\n")
	ok = sum(1 for t in T if kq[t["ma"]]["ok"])
	print(f"{len(T)} tình huống ({ok} ghi được, {len(T) - ok} báo lỗi) → {DICH}")
	for t in T:
		k = kq[t["ma"]]
		print(f"  {t['ma']:<32} {'OK ' if k['ok'] else (k['ma_loi'] or '')} {'' if k['ok'] else (k['loi'] or '')[:110]}")


if __name__ == "__main__":
	main()
