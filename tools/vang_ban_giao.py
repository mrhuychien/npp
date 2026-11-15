#!/usr/bin/env python3
"""Dữ liệu vàng cho BÀN GIAO KHÁCH (`ban_giao_khach`, mig 246) — chạy CHÍNH hàm của nppsale ở Postgres tham chiếu.

Nền (dựng một lần): NCC S1 (P1), S2 (P2); khách C1 (Tuyen A), C2 (chưa có tuyến), C3 (Tuyen B, chưa ai phụ trách); phân công C1: sales_a
chính + sales_b phụ, C2: sales_a chính + sales_b (đã tắt); lịch tuyến sales_a (T1: C1#1, C2#2; T3: C2#1), sales_b (T1: C1#1);
HD-0001 (C1, sales_a, có P2), HD-0002 (C2, sales_a), HD-0003 (C1, sales_b). Mỗi tình huống chạy trong một giao dịch con rồi lùi: từng
lệnh (lỗi không dừng chuỗi) → kết quả; cuối tình huống chụp phân công, lịch tuyến, người giữ nợ + dấu bàn giao, nhật ký, thông báo.

	python3 tools/vang_ban_giao.py   → nppsale/tests/du_lieu/ban_giao_mau.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vang_tao_don import NGUOI, ORG, PSQL, _lit, dong, ref, sql_nen, uid
from vang_xuat_hang import don, sql_lo

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICH = os.path.join(GOC, "nppsale", "tests", "du_lieu", "ban_giao_mau.json")
KHONG_CO = "00000000-0000-4000-8000-000000000777"

NEN = {
	"ncc": {"S1": ("NCC VTD 1", "P1"), "S2": ("NCC VTD 2", "P2")},
	"khach_them": {"C3": "Tap hoa VTD 3"},
	"tuyen": {"C1": "Tuyen A", "C2": None, "C3": "Tuyen B"},
	"phan_cong": [("C1", "sales_a", "primary", "active"), ("C1", "sales_b", "secondary", "active"), ("C2", "sales_a", "primary", "active"),
		("C2", "sales_b", "secondary", "inactive")],
	# sales_a T5: C1 — khách NV nhận (sales_b) đã có nhưng khác ngày: không được chép (chỉ chép lịch của khách MỚI)
	"lich_tuyen": [("sales_a", 1, "C1", 1), ("sales_a", 1, "C2", 2), ("sales_a", 3, "C2", 1), ("sales_a", 5, "C1", 1), ("sales_b", 1, "C1", 1)],
	"don": [don("sales_a", [dong(sl=2, gia=9500), dong(sp="@P2", dv="Chai", gia=5000, thue=0.1)], "bg_1", khach="@C1"),
		don("sales_a", [dong(sl=1, gia=10000)], "bg_2", khach="@C2"),
		don("sales_b", [dong(sl=1, gia=9500)], "bg_3", khach="@C1")],
}


def bg(nguoi="owner", **p):
	return {"nguoi": nguoi, "ham": "ban_giao_khach", "tham_so": p}


def nghi(nv):
	return {"nguoi": "owner", "ham": "cho_nhan_vien_nghi", "tham_so": {"p_user_id": "@u:" + nv}}


def nghi_thang(nv):
	"""Mốc nghỉ đặt thẳng (dữ liệu cũ: NV đã nghỉ mà phân công còn đó — cho_nhan_vien_nghi mới gỡ phân công)."""
	return {"nguoi": "owner", "ham": "_nghi_thang", "tham_so": {"p_user_id": "@u:" + nv}}


A_B = {"p_den_nv": "@u:sales_b", "p_tu_nv": "@u:sales_a"}
TINH_HUONG = [
	("xem_lam_chung_nv", [bg(**A_B)]),
	("lam_chung_nv", [bg(**A_B, p_thuc_hien=True)]),
	("xem_chuyen_han", [bg(**A_B, p_kieu="chuyen")]),
	("chuyen_han", [bg(**A_B, p_kieu="chuyen", p_thuc_hien=True)]),
	("chuyen_han_roi_nguoc_lai", [bg(**A_B, p_kieu="chuyen", p_thuc_hien=True),
		bg(p_den_nv="@u:sales_a", p_tu_nv="@u:sales_b", p_kieu="chuyen", p_thuc_hien=True)]),
	("quan_ly_chuyen_han", [bg("manager", **A_B, p_kieu="chuyen", p_thuc_hien=True)]),
	("chuyen_tu_nv_phu_sang_nv_chinh", [bg(p_den_nv="@u:sales_a", p_tu_nv="@u:sales_b", p_kieu="chuyen"),
		bg(p_den_nv="@u:sales_a", p_tu_nv="@u:sales_b", p_kieu="chuyen", p_thuc_hien=True)]),
	("chua_ai_nv_nghi_con_phan_cong", [nghi_thang("sales_a"), bg(p_den_nv="@u:sales_b", p_nguon="chua_ai"),
		bg(p_den_nv="@u:sales_giam", p_nguon="tat_ca", p_khach=["@C2"])]),
	("chua_ai_sau_nghi_viec", [nghi("sales_a"), bg(p_den_nv="@u:sales_b", p_nguon="chua_ai"),
		bg(p_den_nv="@u:sales_b", p_nguon="chua_ai", p_thuc_hien=True)]),
	("chua_ai_khong_giao_no_npp", [nghi("sales_a"), bg(p_den_nv="@u:sales_giam", p_nguon="chua_ai", p_giao_no_npp=False, p_thuc_hien=True)]),
	("tat_ca_theo_danh_sach", [bg(p_den_nv="@u:sales_giam", p_nguon="tat_ca", p_khach=["@C1", "@C3", KHONG_CO]),
		bg(p_den_nv="@u:sales_giam", p_nguon="tat_ca", p_khach=["@C1", "@C3", KHONG_CO], p_thuc_hien=True)]),
	("loc_tuyen", [bg(**A_B, p_tuyen=["Tuyen A"]), bg(**A_B, p_tuyen=["__chua_co_tuyen"]),
		bg(p_den_nv="@u:sales_b", p_nguon="tat_ca", p_tuyen=["Tuyen B", "__chua_co_tuyen"])]),
	("loc_ncc", [bg(**A_B, p_ncc=["@S2"]), bg(**A_B, p_ncc=["@S1"], p_tu_ngay="@hom_nay"),
		bg(**A_B, p_ncc=["@S1", "@S2"], p_tu_ngay="@hom_nay+1"), bg(**A_B, p_ncc=["@S2"], p_tu_ngay="@hom_nay+1", p_thuc_hien=True)]),
	("loi_dau_vao", [bg("sales_a", **A_B), bg("accountant", **A_B), bg(**A_B, p_kieu="xyz"), bg(**A_B, p_nguon="abc"),
		bg(p_den_nv="@u:sales_b"), bg(p_den_nv="@u:sales_b", p_nguon="tat_ca", p_kieu="chuyen"),
		bg(p_den_nv="@u:sales_a", p_tu_nv="@u:sales_a"), bg(p_den_nv="@u:sales_b", p_tu_nv=KHONG_CO),
		bg(p_den_nv="@u:manager", p_tu_nv="@u:sales_a"), bg(p_den_nv="@u:sales_nghi", p_tu_nv="@u:sales_a"),
		bg(p_den_nv=None, p_tu_nv="@u:sales_a")]),
]

KIEU = {"p_den_nv": "uuid", "p_tu_nv": "uuid", "p_kieu": "text", "p_nguon": "text", "p_tuyen": "text[]", "p_ncc": "uuid[]",
	"p_tu_ngay": "date", "p_khach": "uuid[]", "p_giao_no_npp": "boolean", "p_thuc_hien": "boolean", "p_user_id": "uuid"}


def _gia_tri(k, v) -> str:
	from vang_xuat_hang import ngay_tuong_doi

	v = ngay_tuong_doi(v)
	if v is None:
		return f"NULL::{KIEU[k]}"
	v = v if v == KHONG_CO else (ref(v) if not isinstance(v, list) else [x if x == KHONG_CO else ref(x) for x in v])
	if isinstance(v, list):
		return "ARRAY[" + ", ".join(_lit(str(x)) for x in v) + f"]::{KIEU[k]}"
	if isinstance(v, bool):
		return "true" if v else "false"
	return f"{_lit(str(v))}::{KIEU[k]}"


def _buoc_sql(nguoi: str, lenh: str) -> str:
	return f"""
    BEGIN
      EXECUTE 'SET CONSTRAINTS ALL DEFERRED';
      PERFORM set_config('request.jwt.claim.sub', {_lit(uid('u:' + nguoi))}, true);
      EXECUTE 'SET LOCAL ROLE authenticated';
      {lenh}
      EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';
      EXECUTE 'RESET ROLE';
    EXCEPTION WHEN OTHERS THEN
      EXECUTE 'RESET ROLE';
      v_kq := v_kq || jsonb_build_object('ok', false, 'ma_loi', SQLSTATE, 'loi', SQLERRM);
    END;
    EXECUTE 'RESET ROLE';"""


def _khoa_ten() -> tuple[str, str, str]:
	nv = ", ".join(f"('{k}', '{uid('u:' + k)}'::uuid)" for k in NGUOI)
	kh = ", ".join(f"('{k}', '{uid(k)}'::uuid)" for k in ("C1", "C2", "C3"))
	ncc = ", ".join(f"('{k}', '{uid(k)}'::uuid)" for k in NEN["ncc"])
	return nv, kh, ncc


def sql_nen_ban_giao() -> str:
	q = []
	for k, (ten, sp) in NEN["ncc"].items():
		q.append(f"INSERT INTO suppliers (id, org_id, name) VALUES ('{uid(k)}', '{ORG}', {_lit(ten)});")
		q.append(f"UPDATE products SET primary_supplier_id = '{uid(k)}' WHERE id = '{uid(sp)}';")
	for k, ten in NEN["khach_them"].items():
		q.append(f"INSERT INTO customers (id, org_id, store_name, owner_name, phone, address) VALUES ('{uid(k)}', '{ORG}', {_lit(ten)}, "
			f"'Chu', '0900000099', 'Dia chi');")
	for k, t in NEN["tuyen"].items():
		q.append(f"UPDATE customers SET channel = {_lit(t) if t else 'NULL'} WHERE id = '{uid(k)}';")
	for k, nv, vai, tt in NEN["phan_cong"]:
		q.append(f"INSERT INTO customer_assignments (customer_id, user_id, role, status, assigned_at) VALUES ('{uid(k)}', "
			f"'{uid('u:' + nv)}', '{vai}', '{tt}', DATE '2026-01-05');")
	for nv, thu, k, thu_tu in NEN["lich_tuyen"]:
		q.append(f"INSERT INTO pjp_routes (org_id, sales_user_id, day_of_week, customer_id, visit_order) VALUES ('{ORG}', '{uid('u:' + nv)}', "
			f"{thu}, '{uid(k)}', {thu_tu});")
	tao = []
	for d in NEN["don"]:
		tao.append(_buoc_sql(d["nguoi"], f"SELECT r.order_id INTO v_don FROM public.create_order_with_lines({_lit(json.dumps(ref(d['p'])))}::jsonb) r;"))
		tao.append(_buoc_sql("owner", """SELECT r.invoice_id INTO v_hd FROM public.post_invoice(jsonb_build_object('order_id', v_don, 'lines',
          (SELECT jsonb_agg(jsonb_build_object('order_line_id', l.id, 'product_id', l.product_id, 'unit_name', l.unit_name,
            'conversion_factor', l.conversion_factor, 'quantity', l.quantity, 'unit_price', l.unit_price, 'line_discount', l.line_discount,
            'vat_rate', l.vat_rate)) FROM sales_order_lines l WHERE l.order_id = v_don))) r;"""))
	return "\n".join(q) + f"""
DO $n$
DECLARE v_don uuid; v_hd uuid; v_kq jsonb := '[]'::jsonb;
BEGIN
  {''.join(tao)}
  IF v_kq <> '[]'::jsonb THEN RAISE EXCEPTION 'Dựng nền hỏng: %', v_kq; END IF;
END $n$;"""


def sql_tinh_huong(ma: str, buoc: list) -> str:
	nv, kh, _ncc = _khoa_ten()
	lenh = []
	for b in buoc:
		if b["ham"] == "_nghi_thang":
			lenh.append(f"""
    UPDATE users SET left_at = now() WHERE id = {_gia_tri('p_user_id', b['tham_so']['p_user_id'])};
    v_kq := v_kq || jsonb_build_object('ok', true, 'tra', NULL);""")
			continue
		dau = ", ".join(f"{k} => {_gia_tri(k, v)}" for k, v in b["tham_so"].items())
		lenh.append(_buoc_sql(b["nguoi"], f"SELECT to_jsonb(public.{b['ham']}({dau})) INTO v_tra; "
			"v_kq := v_kq || jsonb_build_object('ok', true, 'tra', v_tra);"))
	return f"""
DO $c$
DECLARE v_tra jsonb; v_kq jsonb := '[]'::jsonb; v_ct jsonb;
BEGIN
  BEGIN
    {''.join(lenh)}
    WITH nv(k, id) AS (VALUES {nv}), kh(k, id) AS (VALUES {kh})
    SELECT jsonb_build_object(
      'phan_cong', (SELECT jsonb_agg(jsonb_build_array(kh.k, nv.k, a.role, a.status, a.assigned_at = public.vn_today())
          ORDER BY kh.k, nv.k) FROM customer_assignments a JOIN kh ON kh.id = a.customer_id JOIN nv ON nv.id = a.user_id),
      'lich_tuyen', (SELECT jsonb_agg(jsonb_build_array(nv.k, r.day_of_week, kh.k, r.visit_order, r.is_active)
          ORDER BY nv.k, r.day_of_week, kh.k) FROM pjp_routes r JOIN kh ON kh.id = r.customer_id JOIN nv ON nv.id = r.sales_user_id),
      'cong_no', (SELECT jsonb_agg(jsonb_build_object('hd', si.invoice_code, 'nv', (SELECT nv.k FROM nv WHERE nv.id = r.sales_user_id),
          'giao', (SELECT nv.k FROM nv WHERE nv.id = r.giao_tu_nv), 'co_ve', r.ve_npp_luc IS NOT NULL) ORDER BY si.invoice_code)
          FROM receivables r JOIN sales_invoices si ON si.id = r.invoice_id),
      'nhat_ky', (SELECT jsonb_agg(jsonb_build_object('nguon', l.nguon, 'tu', (SELECT nv.k FROM nv WHERE nv.id = l.tu_nv),
          'den', (SELECT nv.k FROM nv WHERE nv.id = l.den_nv), 'kieu', l.kieu, 'bo_loc', l.bo_loc,
          'khach', (SELECT jsonb_agg(COALESCE((SELECT kh.k FROM kh WHERE kh.id = x.v), x.v::text) ORDER BY x.i)
                    FROM unnest(l.khach) WITH ORDINALITY x(v, i)),
          'ket_qua', l.ket_qua, 'tao_boi', (SELECT nv.k FROM nv WHERE nv.id = l.tao_boi)) ORDER BY (SELECT nv.k FROM nv WHERE nv.id = l.tu_nv) NULLS FIRST, (SELECT nv.k FROM nv WHERE nv.id = l.den_nv))
          FROM ban_giao_khach_log l),
      'thong_bao', (SELECT jsonb_agg(jsonb_build_object('nguoi', nv.k, 'loai', n.type, 'tieu_de', n.title, 'noi_dung', n.body,
          'duong_dan', n.link_url) ORDER BY nv.k, n.title) FROM notifications n JOIN nv ON nv.id = n.user_id WHERE n.type = 'info'))
      INTO v_ct;
    RAISE EXCEPTION USING ERRCODE = 'ZZ999';
  EXCEPTION WHEN SQLSTATE 'ZZ999' THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  INSERT INTO _vang_kq VALUES ({_lit(ma)}, v_kq, v_ct);
END $c$;
"""


def _chuan(x):
	"""UUID khách / NCC / NV trong kết quả → khoá (C1, S1, sales_a…); số nguyên giữ nguyên."""
	ten = {uid(k): k for k in ("C1", "C2", "C3", *NEN["ncc"])} | {uid("u:" + k): k for k in NGUOI} | {KHONG_CO: "KHONG_CO"}
	if isinstance(x, dict):
		return {k: (bool(v) if k == "log_id" else _chuan(v)) for k, v in x.items()}
	if isinstance(x, list):
		return [_chuan(v) for v in x]
	if isinstance(x, str) and x in ten:
		return ten[x]
	return x


def main():
	sql = ["BEGIN;", sql_nen(), sql_lo(), sql_nen_ban_giao(), "CREATE TEMP TABLE _vang_kq (ma text, buoc jsonb, ct jsonb);"]
	sql += [sql_tinh_huong(ma, buoc) for ma, buoc in TINH_HUONG]
	sql.append("SELECT json_agg(json_build_object('ma', ma, 'buoc', buoc, 'ct', ct)) FROM _vang_kq;")
	sql.append("ROLLBACK;")
	ra = subprocess.run(PSQL, shell=True, input="\n".join(sql), capture_output=True, text=True, check=False)
	if ra.returncode != 0:
		raise SystemExit(ra.stderr[-4000:])
	kq = {k["ma"]: _chuan(k) for k in json.loads(ra.stdout.strip().splitlines()[-1])}
	tep = {"ghi_chu": "Sinh bởi tools/vang_ban_giao.py — ban_giao_khach (+ cho_nhan_vien_nghi) thật của nppsale.", "nen": NEN,
		"khong_co": KHONG_CO, "tinh_huong": [{"ma": ma, "buoc": buoc, "mong": {"buoc": kq[ma]["buoc"], "ct": kq[ma]["ct"]}}
			for ma, buoc in TINH_HUONG]}
	with open(DICH, "w", encoding="utf-8") as f:
		json.dump(tep, f, ensure_ascii=False, indent=1)
		f.write("\n")
	for ma, buoc in TINH_HUONG:
		print(f"  {ma}")
		for b, x in zip(buoc, kq[ma]["buoc"], strict=True):
			if x["ok"]:
				t = x["tra"] or {}
				tom = t.get("tong") or {k: v for k, v in t.items() if k != "log_id"}
				print(f"      {b['nguoi']:<11} ok {json.dumps(tom, ensure_ascii=False)[:230]}")
			else:
				print(f"      {b['nguoi']:<11} {x['ma_loi']} {x['loi'][:120]}")


if __name__ == "__main__":
	main()
