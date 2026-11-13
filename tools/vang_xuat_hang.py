#!/usr/bin/env python3
"""Dữ liệu vàng cho XUẤT HÀNG (`post_invoice`, mig 125 / 174 / 183 / 186 / 217 / 227) — chạy CHÍNH hàm + trigger của nppsale ở Postgres
tham chiếu (schema_full.sql). Phần chưa gồm: hàng trả / hàng đổi kèm đơn (phiếu trả tự sinh) — bộ riêng khi dựng phiếu trả.

Mỗi tình huống: tạo đơn (create_order_with_lines, đơn submitted) → xuất hàng (post_invoice) dưới đúng người, mỗi lệnh một giao dịch;
ghi lại lỗi hoặc: mã HĐ, tiền (subtotal / vat / total), hạn trả, dòng HĐ, lô đã lấy theo từng dòng (mã lô × SL cơ sở), tồn lô còn lại,
short_qty, near_expiry_skipped, trạng thái đơn, công nợ (số nợ, NV giữ, hạn). tests/test_xuat_hang.py chạy cùng chuỗi trên site Frappe.

	python3 tools/vang_xuat_hang.py   → nppsale/tests/du_lieu/xuat_hang_mau.json
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vang_tao_don import (
	GIA,
	HANG,
	KHACH,
	NGUOI,
	NHOM,
	NS,
	ORG,
	PSQL,
	_lit,
	dong,
	ref,
	sql_nen,
	tong,
	uid,
)

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICH = os.path.join(GOC, "nppsale", "tests", "du_lieu", "xuat_hang_mau.json")

# Lô: (mã lô, mặt hàng, SL cơ sở, nhận lúc = hôm nay + n ngày (8:00 giờ VN), hạn dùng = hôm nay + n ngày, giá vốn / đơn vị cơ sở, vùng).
# Ngày tương đối để bài kiểm chạy được mọi ngày (lô không tự hết hạn theo lịch).
LO = [
	("L1-CU", "P1", 30, -43, 108, 8000, "sale"),
	("L2-MOI-HAN-SOM", "P1", 50, -39, 63, 8200, "sale"),
	("L3-CAN-DATE", "P1", 20, -54, 37, 7900, "date"),
	("L4-DAU", "P2", 10, -42, 200, 4000, "sale"),
	("L5-DAU-DATE", "P2", 6, -73, 18, 3900, "date"),
]


def sql_lo() -> str:
	q = []
	for ma, sp, sl, nhan, han, gia, vung in LO:
		luc = f"((now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date + {nhan} + time '08:00') AT TIME ZONE 'Asia/Ho_Chi_Minh'"
		q.append("INSERT INTO batches (id, org_id, product_id, batch_code, expires_at, qty_initial, qty_on_hand, unit_cost, warehouse_zone, "
			f"received_at, created_at) VALUES ('{uid('lo:' + ma)}', '{ORG}', '{uid(sp)}', '{ma}', "
			f"(now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date + {han}, {sl}, {sl}, {gia}, '{vung}', {luc}, {luc});")
	return "\n".join(q)


def don(nguoi, lines, ma, *, khach="@C1", giam_don=0, **o):
	t = tong(lines, giam_don)
	oo = {"order_code": "TAM-1", "customer_id": khach, "payment_terms": "COD", "expected_delivery": None, "notes": None,
		"status": "submitted", "approval_reason": None, "sales_user_id": None, **t, **o}
	return {"buoc": "tao", "nguoi": nguoi, "p": {"client_request_id": str(uuid.uuid5(NS, "xuat:" + ma)), "order": oo, "lines": lines,
		"returns": None, "return_lines": []}}


def xuat(nguoi, dong_xuat, **p):
	"""dong_xuat: [(chỉ số dòng đơn hoặc None = dòng thêm, {đè trường})]; trường không đè lấy từ dòng đơn."""
	return {"buoc": "xuat", "nguoi": nguoi, "dong": [list(x) for x in dong_xuat], "p": p}


def tinh_huong() -> list[dict]:
	A = [dong(sl=2, gia=9500), dong(sp="@P2", dv="Chai", gia=5000, thue=0.1)]
	T = []

	def th(ma, *buoc, oversell=False):
		T.append({"ma": ma, "buoc": list(buoc), "cho_ban_vuot_ton": oversell})

	# --- lô FIFO theo ngày nhận
	th("xuat_du_mot_lo", don("sales_a", A, "xuat_du_mot_lo"), xuat("owner", [(0, {}), (1, {})]))
	th("xuat_qua_hai_lo", don("sales_a", [dong(sl=40, gia=9500)], "xuat_qua_hai_lo"), xuat("owner", [(0, {})]))
	th("xuat_thung_quy_doi", don("sales_a", [dong(dv="Thung", hs=24, sl=2, gia=230000)], "xuat_thung"), xuat("owner", [(0, {})]))
	th("xuat_giao_thieu", don("sales_a", A, "xuat_giao_thieu"), xuat("owner", [(0, {"quantity": 1}), (1, {})]))
	th("xuat_bo_dong", don("sales_a", A, "xuat_bo_dong"), xuat("owner", [(0, {})]))
	th("xuat_dong_them", don("sales_a", A[:1], "xuat_dong_them"), xuat("owner", [(0, {}), (None, {"product_id": "@P2", "unit_name": "Chai",
		"quantity": 2, "unit_price": 5000, "vat_rate": 0.1, "conversion_factor": 1})]))
	th("xuat_he_so_sai_duoc_chuan", don("sales_a", [dong(dv="Loc", hs=6, sl=1, gia=57000)], "xuat_he_so_sai"),
		xuat("owner", [(0, {"conversion_factor": 4})]))
	th("xuat_don_vi_co_so_he_so_sai", don("sales_a", [dong(sl=2, gia=9500)], "xuat_co_so_he_so_sai"),
		xuat("owner", [(0, {"conversion_factor": 5})]))
	# --- thiếu tồn / kho cận date / bán vượt tồn
	th("thieu_ton", don("sales_a", [dong(sl=90, gia=9500)], "thieu_ton"), xuat("owner", [(0, {})]))
	th("thieu_ton_con_o_kho_date", don("sales_a", [dong(sp="@P2", dv="Chai", sl=12, gia=5000, thue=0.1)], "thieu_ton_date"),
		xuat("owner", [(0, {})]))
	th("hang_khong_co_lo", don("owner", [dong(sp="@P3", dv="Goi", sl=1, gia=1000, thue=0)], "hang_khong_lo"), xuat("owner", [(0, {})]))
	th("ban_vuot_ton", don("sales_a", [dong(sl=90, gia=9500)], "ban_vuot_ton"), xuat("owner", [(0, {})]), oversell=True)
	# --- tiền
	th("giam_gia_don", don("sales_giam", A, "giam_gia_don", giam_don=2000), xuat("owner", [(0, {}), (1, {})], discount=2000))
	th("giam_gia_don_vuot_tien", don("sales_a", A[:1], "giam_vuot"), xuat("owner", [(0, {})], discount=99999999))
	th("giam_gia_don_chu", don("sales_a", A, "giam_chu"), xuat("owner", [(0, {}), (1, {})], discount="abc"))
	th("thue_khac_don", don("sales_a", A, "thue_khac"), xuat("owner", [(0, {"vat_rate": 0.05}), (1, {"vat_rate": 8})]))
	th("dieu_khoan_net30_va_ngay", don("sales_a", A, "net30"), xuat("owner", [(0, {}), (1, {})], payment_terms="NET30",
		invoice_date="@hom_nay-3", notes="Giao chieu"))
	# --- quyền / trạng thái / dữ liệu hỏng
	th("nv_ban_hang_xuat", don("sales_a", A, "nv_xuat"), xuat("sales_a", [(0, {}), (1, {})]))
	th("thu_kho_xuat", don("sales_a", A, "kho_xuat"), xuat("warehouse", [(0, {}), (1, {})]))
	th("ke_toan_xuat", don("sales_a", A, "kt_xuat"), xuat("accountant", [(0, {}), (1, {})]))
	th("quan_ly_xuat", don("sales_a", A, "ql_xuat"), xuat("manager", [(0, {}), (1, {})]))
	th("don_nhap_khong_xuat", don("sales_a", A, "nhap_xuat", status="draft"), xuat("owner", [(0, {}), (1, {})]))
	th("xuat_hai_lan", don("sales_a", A, "hai_lan"), xuat("owner", [(0, {}), (1, {})]), xuat("owner", [(0, {}), (1, {})]))
	th("khong_dong", don("sales_a", A, "khong_dong"), xuat("owner", [(0, {"quantity": 0})]))
	th("dong_sai_don", don("sales_a", A, "dong_sai"), xuat("owner", [(0, {"product_id": "@P2", "unit_name": "Chai"})]))
	return T


def _gia(v) -> str:
	if v is None:
		return "NULL"
	return _lit(str(v))


def sql_tinh_huong(t: dict) -> str:
	khoi = []
	for b in t["buoc"]:
		u = uid("u:" + b["nguoi"])
		if b["buoc"] == "tao":
			lenh = (f"SELECT r.order_id INTO v_don FROM public.create_order_with_lines({_lit(json.dumps(ref(b['p'])))}::jsonb) r;")
		else:
			dong_x = json.dumps(ref(b["dong"]))
			p = json.dumps(ref(ngay_tuong_doi(b["p"])))
			lenh = f"""
      SELECT jsonb_agg(CASE WHEN x.e->>0 IS NULL THEN x.e->1
          ELSE jsonb_build_object('order_line_id', l.id, 'product_id', l.product_id, 'unit_name', l.unit_name,
            'conversion_factor', l.conversion_factor, 'quantity', l.quantity - COALESCE(l.invoiced_qty, 0), 'unit_price', l.unit_price,
            'line_discount', l.line_discount, 'vat_rate', l.vat_rate, 'is_exchange', false, 'note', l.note) || (x.e->1) END
          ORDER BY x.i) INTO v_dong
        FROM jsonb_array_elements({_lit(dong_x)}::jsonb) WITH ORDINALITY x(e, i)
        LEFT JOIN LATERAL (SELECT * FROM sales_order_lines s WHERE s.order_id = v_don ORDER BY s.ctid OFFSET (x.e->>0)::int LIMIT 1) l
          ON x.e->>0 IS NOT NULL;
      SELECT r.invoice_id, to_jsonb(r) INTO v_hd, v_tra
        FROM public.post_invoice(({_lit(p)}::jsonb) || jsonb_build_object('order_id', v_don, 'lines', v_dong)) r;
      v_ds_hd := v_ds_hd || jsonb_build_array(v_tra);"""
		khoi.append(f"""
  IF NOT v_dung THEN
    BEGIN
      EXECUTE 'SET CONSTRAINTS ALL DEFERRED';
      PERFORM set_config('request.jwt.claim.sub', {_lit(u)}, true);
      EXECUTE 'SET LOCAL ROLE authenticated';
      {lenh}
      EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';
      EXECUTE 'RESET ROLE';
      v_kq := v_kq || jsonb_build_object('ok', true);
    EXCEPTION WHEN OTHERS THEN
      v_kq := v_kq || jsonb_build_object('ok', false, 'ma_loi', SQLSTATE, 'loi', SQLERRM);
      v_dung := true;
    END;
    EXECUTE 'RESET ROLE';
  END IF;""")
	return f"""
DO $c$
DECLARE
  v_don uuid; v_hd uuid; v_dong jsonb; v_tra jsonb; v_ds_hd jsonb := '[]'::jsonb; v_kq jsonb := '[]'::jsonb; v_dung boolean := false;
  v_ct jsonb;
BEGIN
  BEGIN
    UPDATE organizations SET allow_oversell = {str(t['cho_ban_vuot_ton']).lower()} WHERE id = '{ORG}';
    {''.join(khoi)}
    SELECT jsonb_build_object(
      'tra_ve', v_ds_hd,
      'don', (SELECT jsonb_build_object('status', so.status, 'co_completed_at', so.completed_at IS NOT NULL) FROM sales_orders so WHERE so.id = v_don),
      'hd', (SELECT jsonb_agg(jsonb_build_object('ma', si.invoice_code, 'status', si.status, 'ngay', si.invoice_date, 'han', si.due_date,
          'dieu_khoan', si.payment_terms, 'subtotal', si.subtotal, 'vat', si.vat, 'total', si.total, 'ghi_chu', si.notes,
          'sales_user', (SELECT u.full_name FROM users u WHERE u.id = si.sales_user_id),
          'dong', (SELECT jsonb_agg(jsonb_build_object('sp', (SELECT p.sku FROM products p WHERE p.id = l.product_id), 'dv', l.unit_name,
              'hs', l.conversion_factor, 'sl', l.quantity, 'gia', l.unit_price, 'giam', l.line_discount, 'tien', l.line_total,
              'thue', l.vat_rate, 'doi', l.is_exchange, 'noi_don', l.order_line_id IS NOT NULL) ORDER BY l.sort_order)
            FROM sales_invoice_lines l WHERE l.invoice_id = si.id),
          'lo', (SELECT jsonb_agg(jsonb_build_array((SELECT p.sku FROM products p WHERE p.id = sel.product_id), b.batch_code, c.qty_in_base_uom)
              ORDER BY (SELECT p.sku FROM products p WHERE p.id = sel.product_id), b.received_at)
            FROM stock_entry_lines sel JOIN stock_line_consumptions c ON c.line_id = sel.id JOIN batches b ON b.id = c.batch_id
            WHERE sel.entry_id = si.stock_entry_id),
          'cong_no', (SELECT jsonb_agg(jsonb_build_object('so_tien', r.amount, 'da_thu', r.paid, 'han', r.due_date, 'status', r.status,
              'nv', (SELECT u.full_name FROM users u WHERE u.id = r.sales_user_id))) FROM receivables r WHERE r.invoice_id = si.id)
        ) ORDER BY si.invoice_seq) FROM sales_invoices si WHERE si.order_id = v_don),
      'ton_lo', (SELECT jsonb_object_agg(b.batch_code, b.qty_on_hand) FROM batches b WHERE b.org_id = '{ORG}'))
      INTO v_ct;
    RAISE EXCEPTION USING ERRCODE = 'ZZ999';
  EXCEPTION WHEN SQLSTATE 'ZZ999' THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  INSERT INTO _vang_kq VALUES ({_lit(t['ma'])}, v_kq, v_ct);
END $c$;
"""


def ngay_tuong_doi(v, hom_nay: datetime.date | None = None):
	""""@hom_nay" / "@hom_nay±n" trong tải trọng → ngày thật (giờ VN) — bộ sinh và bài kiểm dùng cùng luật."""
	hn = hom_nay or _hom_nay()
	if isinstance(v, str) and v.startswith("@hom_nay"):
		n = int(v[len("@hom_nay"):] or 0)
		return (hn + datetime.timedelta(days=n)).isoformat()
	if isinstance(v, dict):
		return {a: ngay_tuong_doi(b, hn) for a, b in v.items()}
	if isinstance(v, list):
		return [ngay_tuong_doi(x, hn) for x in v]
	return v


def _hom_nay() -> datetime.date:
	return (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=7)).date()


def _chuan(k: dict) -> dict:
	"""Bỏ UUID ngẫu nhiên; ngày tương đối → "@hom_nay" / "@hom_nay+n" (bài kiểm chạy được mọi ngày)."""
	hn = _hom_nay()

	def ngay(v):
		if not isinstance(v, str) or len(v) != 10:
			return v
		try:
			d = datetime.date.fromisoformat(v)
		except ValueError:
			return v
		n = (d - hn).days
		return v if abs(n) > 400 else ("@hom_nay" if n == 0 else f"@hom_nay{n:+d}")

	ct = k.get("ct") or {}
	for x in ct.get("tra_ve") or []:
		for khoa in ("invoice_id", "entry_id", "receivable_id"):
			x[khoa] = bool(x.get(khoa))
	for h in ct.get("hd") or []:
		for khoa in ("ngay", "han"):
			h[khoa] = ngay(h.get(khoa))
		for c in h.get("cong_no") or []:
			c["han"] = ngay(c.get("han"))
	return k


def main():
	T = tinh_huong()
	sql = ["BEGIN;", sql_nen(), sql_lo(), "CREATE TEMP TABLE _vang_kq (ma text, buoc jsonb, ct jsonb);"]
	sql += [sql_tinh_huong(t) for t in T]
	sql.append("SELECT json_agg(json_build_object('ma', ma, 'buoc', buoc, 'ct', ct)) FROM _vang_kq;")
	sql.append("ROLLBACK;")
	ra = subprocess.run(PSQL, shell=True, input="\n".join(sql), capture_output=True, text=True, check=False)
	if ra.returncode != 0:
		raise SystemExit(ra.stderr[-4000:])
	kq = {k["ma"]: _chuan(k) for k in json.loads(ra.stdout.strip().splitlines()[-1])}
	tep = {"ghi_chu": "Sinh bởi tools/vang_xuat_hang.py — post_invoice + trigger thật của nppsale (chưa gồm hàng trả kèm đơn).",
		"nen": {"nguoi": NGUOI, "nhom": NHOM, "khach": KHACH, "hang": HANG, "gia": GIA, "lo": LO},
		"tinh_huong": [dict(t, mong={"buoc": kq[t["ma"]]["buoc"], "ct": kq[t["ma"]]["ct"]}) for t in T]}
	with open(DICH, "w", encoding="utf-8") as f:
		json.dump(tep, f, ensure_ascii=False, indent=1)
		f.write("\n")
	print(f"{len(T)} tình huống → {DICH}")
	for t in T:
		k = kq[t["ma"]]
		bs = " | ".join("ok" if x["ok"] else f"{x['ma_loi']} {x['loi'][:90]}" for x in k["buoc"])
		hd = (k["ct"] or {}).get("hd") or []
		tom = "; ".join(f"{h['ma']} {h['total']} lô {h['lo']}" for h in hd)
		print(f"  {t['ma']:<28} {bs}\n      → {tom[:200]}")


if __name__ == "__main__":
	main()
