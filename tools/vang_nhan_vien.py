#!/usr/bin/env python3
"""Dữ liệu vàng cho NHÂN VIÊN NGHỈ VIỆC (mig 223): `so_chung_tu_nhan_vien`, `cho_nhan_vien_nghi`, `giao_cong_no_npp` — chạy CHÍNH hàm của
nppsale ở Postgres tham chiếu, mỗi lệnh một giao dịch con dưới đúng người (lỗi không dừng chuỗi).

Nền: sales_a phụ trách C1 (chính) + C2 (chính), sales_b phụ trách C1 (phụ); lịch tuyến sales_a (C1 thứ 2, C2 thứ 3), sales_b (C1 thứ 4);
HD-0001 (C1) + HD-0002 (C2) của sales_a, HD-0002 đã thu đủ; HD-0003 (C1) của sales_b. So: kết quả từng lệnh (đếm chứng từ: chỉ khach / lich_tuyen / so_khoan_no /
tien_no và "có chứng từ" — danh sách bảng của Frappe khác bảng của nppsale) + trạng thái cuối (NV, phân công, lịch tuyến, công nợ).

	python3 tools/vang_nhan_vien.py   → nppsale/tests/du_lieu/nhan_vien_nghi_mau.json
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
DICH = os.path.join(GOC, "nppsale", "tests", "du_lieu", "nhan_vien_nghi_mau.json")
KHONG_CO = "00000000-0000-4000-8000-000000000999"

A = [dong(sl=2, gia=9500), dong(sp="@P2", dv="Chai", gia=5000, thue=0.1)]
NEN = {
	"phan_cong": [("C1", "sales_a", "primary"), ("C2", "sales_a", "primary"), ("C1", "sales_b", "secondary")],
	"lich_tuyen": [("sales_a", 2, "C1"), ("sales_a", 3, "C2"), ("sales_b", 4, "C1")],
	# C2: bảng giá chuẩn. HĐ thứ ba của C1 do sales_b (phụ) lập — nợ NV đang làm giữ: giao nợ NPP không được đụng tới
	"don": [don("sales_a", A, "nv_c1", khach="@C1"), don("sales_a", [dong(sl=1, gia=10000)], "nv_c2", khach="@C2"),
		don("sales_b", [dong(sl=1, gia=9500)], "nv_c1_b", khach="@C1")],
	"da_thu_du": [1],  # chỉ số HĐ (theo thứ tự đơn) đã thu đủ
}
BUOC = [
	("owner", "so_chung_tu_nhan_vien", {"p_user_id": "@u:sales_a"}),
	("manager", "so_chung_tu_nhan_vien", {"p_user_id": "@u:sales_a"}),
	("owner", "so_chung_tu_nhan_vien", {"p_user_id": KHONG_CO}),
	("manager", "cho_nhan_vien_nghi", {"p_user_id": "@u:sales_a"}),
	("owner", "cho_nhan_vien_nghi", {"p_user_id": "@u:owner"}),
	("owner", "cho_nhan_vien_nghi", {"p_user_id": KHONG_CO}),
	("owner", "cho_nhan_vien_nghi", {"p_user_id": "@u:sales_a"}),
	("owner", "so_chung_tu_nhan_vien", {"p_user_id": "@u:sales_a"}),
	("owner", "giao_cong_no_npp", {"p_customer_id": "@C1", "p_user_id": "@u:sales_a"}),
	("owner", "giao_cong_no_npp", {"p_customer_id": "@C1", "p_user_id": "@u:sales_nghi"}),
	("sales_b", "giao_cong_no_npp", {"p_customer_id": "@C1", "p_user_id": "@u:sales_b"}),
	("accountant", "giao_cong_no_npp", {"p_customer_id": "@C2", "p_user_id": "@u:sales_b"}),
	("accountant", "giao_cong_no_npp", {"p_customer_id": "@C1", "p_user_id": "@u:sales_giam"}),
	("owner", "so_chung_tu_nhan_vien", {"p_user_id": "@u:sales_giam"}),  # chứng từ DUY NHẤT trỏ tới sales_giam là dòng nợ vừa giao
	("owner", "so_chung_tu_nhan_vien", {"p_user_id": "@u:sales_b"}),
	("owner", "cho_nhan_vien_nghi", {"p_user_id": "@u:sales_a"}),
]


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


def sql_kich_ban() -> str:
	nen = []
	for k, nv, vai in NEN["phan_cong"]:
		nen.append(f"INSERT INTO customer_assignments (customer_id, user_id, role) VALUES ('{uid(k)}', '{uid('u:' + nv)}', '{vai}');")
	for nv, thu, k in NEN["lich_tuyen"]:
		nen.append(f"INSERT INTO pjp_routes (org_id, sales_user_id, day_of_week, customer_id, visit_order) VALUES ('{ORG}', "
			f"'{uid('u:' + nv)}', {thu}, '{uid(k)}', 1);")
	tao = []
	for i, d in enumerate(NEN["don"]):
		tao.append(_buoc_sql(d["nguoi"], f"SELECT r.order_id INTO v_don FROM public.create_order_with_lines({_lit(json.dumps(ref(d['p'])))}::jsonb) r;"))
		tao.append(_buoc_sql("owner", """SELECT r.invoice_id INTO v_hd FROM public.post_invoice(jsonb_build_object('order_id', v_don, 'lines',
        (SELECT jsonb_agg(jsonb_build_object('order_line_id', l.id, 'product_id', l.product_id, 'unit_name', l.unit_name,
          'conversion_factor', l.conversion_factor, 'quantity', l.quantity, 'unit_price', l.unit_price, 'line_discount', l.line_discount,
          'vat_rate', l.vat_rate)) FROM sales_order_lines l WHERE l.order_id = v_don))) r;"""))
		if i in NEN["da_thu_du"]:
			tao.append("  UPDATE receivables SET paid = amount WHERE invoice_id = v_hd;")
	buoc = []
	for nguoi, ham, ts in BUOC:
		dau = ", ".join(f"{k} => {_lit(ref(v)) if v != KHONG_CO else _lit(v)}::uuid" for k, v in ts.items())
		buoc.append(_buoc_sql(nguoi, f"SELECT to_jsonb(public.{ham}({dau})) INTO v_tra; v_kq := v_kq || jsonb_build_object('ok', true, 'tra', v_tra);"))
	ten_nv = ", ".join(f"('{k}', '{uid('u:' + k)}'::uuid)" for k in NGUOI)
	ten_kh = ", ".join(f"('{k}', '{uid(k)}'::uuid)" for k in ("C1", "C2"))
	return f"""
DO $c$
DECLARE v_don uuid; v_hd uuid; v_tra jsonb; v_kq jsonb := '[]'::jsonb; v_ct jsonb;
BEGIN
  {''.join(nen)}
  {''.join(tao)}
  IF v_kq <> '[]'::jsonb THEN
    RAISE EXCEPTION 'Dựng nền hỏng: %', v_kq;
  END IF;
  {''.join(buoc)}
  WITH nv(k, id) AS (VALUES {ten_nv}), kh(k, id) AS (VALUES {ten_kh})
  SELECT jsonb_build_object(
    'nhan_vien', (SELECT jsonb_object_agg(nv.k, jsonb_build_object('dang_lam', COALESCE(u.is_active, true), 'da_nghi', u.left_at IS NOT NULL,
        'nghi_boi', (SELECT x.k FROM nv x WHERE x.id = u.left_by))) FROM users u JOIN nv ON nv.id = u.id WHERE nv.k IN ('sales_a', 'sales_b')),
    'phan_cong', (SELECT jsonb_agg(jsonb_build_array(kh.k, nv.k, a.role) ORDER BY kh.k, nv.k) FROM customer_assignments a
        JOIN kh ON kh.id = a.customer_id JOIN nv ON nv.id = a.user_id),
    'lich_tuyen', (SELECT jsonb_agg(jsonb_build_array(nv.k, r.day_of_week, kh.k) ORDER BY nv.k, r.day_of_week) FROM pjp_routes r
        JOIN kh ON kh.id = r.customer_id JOIN nv ON nv.id = r.sales_user_id),
    'cong_no', (SELECT jsonb_agg(jsonb_build_object('hd', si.invoice_code, 'nv', (SELECT nv.k FROM nv WHERE nv.id = r.sales_user_id),
        'co_ve', r.ve_npp_luc IS NOT NULL, 'status', r.status, 'con', r.amount - COALESCE(r.paid, 0)) ORDER BY si.invoice_code)
        FROM receivables r JOIN sales_invoices si ON si.id = r.invoice_id))
    INTO v_ct;
  INSERT INTO _vang_kq VALUES (v_kq, v_ct);
END $c$;
"""


def _chuan_buoc(x: dict) -> dict:
	if x.get("ok") and isinstance(x.get("tra"), dict) and "tong" in x["tra"]:
		t = x["tra"]
		x["tra"] = {"co_chung_tu": t["tong"] > 0, "khach": t["khach"], "lich_tuyen": t["lich_tuyen"], "so_khoan_no": t["so_khoan_no"],
			"tien_no": t["tien_no"]}
	return x


def main():
	sql = ["BEGIN;", sql_nen(), sql_lo(), "CREATE TEMP TABLE _vang_kq (buoc jsonb, ct jsonb);", sql_kich_ban(),
		"SELECT json_build_object('buoc', buoc, 'ct', ct) FROM _vang_kq;", "ROLLBACK;"]
	ra = subprocess.run(PSQL, shell=True, input="\n".join(sql), capture_output=True, text=True, check=False)
	if ra.returncode != 0:
		raise SystemExit(ra.stderr[-4000:])
	kq = json.loads(ra.stdout.strip().splitlines()[-1])
	kq["buoc"] = [_chuan_buoc(x) for x in kq["buoc"]]
	tep = {"ghi_chu": "Sinh bởi tools/vang_nhan_vien.py — so_chung_tu_nhan_vien / cho_nhan_vien_nghi / giao_cong_no_npp thật của nppsale.",
		"nen": NEN, "buoc": [{"nguoi": n, "ham": h, "tham_so": t} for n, h, t in BUOC], "mong": kq}
	with open(DICH, "w", encoding="utf-8") as f:
		json.dump(tep, f, ensure_ascii=False, indent=1)
		f.write("\n")
	for (n, h, _t), x in zip(BUOC, kq["buoc"], strict=True):
		print(f"  {n:<11} {h:<24} {'ok ' + json.dumps(x.get('tra'), ensure_ascii=False) if x['ok'] else x['ma_loi'] + ' ' + x['loi']}")
	print(json.dumps(kq["ct"], ensure_ascii=False))


if __name__ == "__main__":
	main()
