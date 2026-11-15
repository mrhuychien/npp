#!/usr/bin/env python3
"""Dữ liệu vàng cho PHIẾU TRẢ (returns / return_lines của nppsale) — chạy CHÍNH hàm + trigger của nppsale ở Postgres tham chiếu
(schema_full.sql): create_order_with_lines (hàng trả kèm đơn), post_invoice (return_adds / return_edits, gắn phiếu nháp của đơn →
tự sinh), create_return_with_lines, save_pos_return, complete_return (2 / 3 tham số), cancel_return, cancel_invoice, reissue_invoice
(tra_da_nhap lam_lai / giu), assign_doc_seller('return'), ghi thẳng bảng (RLS + trigger khoá — mig 191 / 214 / 227).

Mỗi tình huống chạy trong một giao dịch con rồi lui (ZZ999) — mọi số đếm (PT-…, HD-…) bắt đầu lại từ nền. Mỗi bước chạy dưới đúng người
(request.jwt.claim.sub + ROLE authenticated), bước hỏng thì dừng tình huống và ghi mã + câu lỗi. Chỗ giữ chỗ trong tải trọng:
"@pt" = id phiếu trả đang xét, "@hd" = id HĐ đang xét, "@don" = id đơn; "@dong_tra:N" = id dòng thứ N (0-based) của phiếu trả đang xét.

Ảnh chụp sau tình huống (ct): phiếu trả (mã, trạng thái, tự sinh, tiền, ngày trừ doanh số, mốc, kho nhận, HĐ gắn, người, dòng), công
nợ (mọi dòng receivables của NPP), HĐ (như bộ Xuất hàng), tồn lô (gồm lô RESTOCK mới), phiếu kho nhập lại / đảo của phiếu trả.

	python3 tools/vang_phieu_tra.py   → nppsale/tests/du_lieu/phieu_tra_mau.json
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vang_tao_don import GIA, HANG, KHACH, NGUOI, NHOM, NS, ORG, PSQL, _lit, dong, ref, sql_nen, uid  # noqa: F401
from vang_xuat_hang import LO, _hom_nay, ngay_tuong_doi, sql_lo

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICH = os.path.join(GOC, "nppsale", "tests", "du_lieu", "phieu_tra_mau.json")


# ------------------------------------------------------------------------------------------------ bước
def don(nguoi, lines, ma, *, khach="@C1", tra=None, dong_tra=None, **o):
	"""create_order_with_lines — tra: đầu phiếu trả kèm đơn ({reason, notes…}), dong_tra: dòng trả [{product_id, unit_name, quantity,
	unit_price, vat_rate, is_exchange, note, reason}]."""
	import uuid

	from vang_tao_don import tong

	# màn POS gửi total = subtotal + VAT − tiền hàng trả kèm (dòng không đổi) — lệch là máy chủ suy ra "giảm giá đơn"
	tru = sum(round(x.get("quantity", 0) * x.get("unit_price", 0) * (1 + (x.get("vat_rate") or 0)))
		for x in (dong_tra or []) if not x.get("is_exchange"))
	oo = {"order_code": "TAM-1", "customer_id": khach, "payment_terms": "COD", "expected_delivery": None, "notes": None,
		"status": "submitted", "approval_reason": None, "sales_user_id": None, **tong(lines, o.pop("giam_don", 0), tru), **o}
	return {"buoc": "tao", "nguoi": nguoi, "p": {"client_request_id": str(uuid.uuid5(NS, "tra:" + ma)), "order": oo, "lines": lines,
		"returns": tra, "return_lines": dong_tra or []}}


def xuat(nguoi, dong_xuat, **p):
	"""post_invoice — dong_xuat: [(chỉ số dòng đơn | None, phần đè)]; p: return_adds / return_edits / discount / invoice_date…"""
	return {"buoc": "xuat", "nguoi": nguoi, "dong": [list(x) for x in dong_xuat], "p": p}


def lap(nguoi, head, lines):
	"""create_return_with_lines(p_head, p_lines) → phiếu đang xét."""
	return {"buoc": "lap", "nguoi": nguoi, "head": head, "lines": lines}


def pos(nguoi, p):
	"""save_pos_return(p) → phiếu đang xét (lập mới hoặc sửa "@pt")."""
	return {"buoc": "pos", "nguoi": nguoi, "p": p}


def hoan(nguoi, zone="sale", ngay=None):
	"""complete_return(@pt, zone) hoặc (@pt, zone, ngày) — ngay "@hom_nay±n"."""
	return {"buoc": "hoan", "nguoi": nguoi, "zone": zone, "ngay": ngay}


def huy_pt(nguoi, ly_do="Khach doi y"):
	return {"buoc": "huy_pt", "nguoi": nguoi, "ly_do": ly_do}


def huy(nguoi, ly_do="Khach tra lai hang"):
	"""cancel_invoice(@hd, lý do)."""
	return {"buoc": "huy", "nguoi": nguoi, "ly_do": ly_do}


def sua(nguoi, dong_sua, **p):
	"""reissue_invoice(@hd, p) — dong_sua như bộ Xuất hàng; p: tra_da_nhap / return_adds / return_edits…"""
	return {"buoc": "sua", "nguoi": nguoi, "dong": [list(x) for x in dong_sua], "p": p}


def chon(cach="don"):
	"""Đặt phiếu đang xét: "don" = phiếu đầu của đơn đang xét; "hd" = phiếu đầu gắn HĐ đang xét; "moi_nhat" = phiếu lập sau cùng."""
	return {"buoc": "chon", "nguoi": "owner", "cach": cach}


def gan(nguoi, nv):
	"""assign_doc_seller('return', @pt, nv)."""
	return {"buoc": "gan", "nguoi": nguoi, "nv": nv}


def ghi(nguoi, cau):
	"""Ghi thẳng bảng dưới RLS + trigger như cổng PostgREST — câu SQL có chỗ giữ :pt :hd :don :dong_tra0…"""
	return {"buoc": "ghi", "nguoi": nguoi, "cau": cau}


# ------------------------------------------------------------------------------------------------ SQL
_THAY = ("replace(replace(replace({x}, '\"@pt\"', COALESCE(to_jsonb(v_pt::text)::text, 'null')), "
	"'\"@hd\"', COALESCE(to_jsonb(v_hd::text)::text, 'null')), '\"@don\"', COALESCE(to_jsonb(v_don::text)::text, 'null'))")


def _p(v) -> str:
	"""Tải trọng JSON → biểu thức jsonb có thay chỗ giữ lúc chạy (+ "@dong_tra:N")."""
	t = _lit(json.dumps(ref(ngay_tuong_doi(v)), ensure_ascii=False))
	return f"public._vang_thay_dong({_THAY.format(x=t)}, v_pt)::jsonb"


def _lenh(b: dict) -> str:
	k = b["buoc"]
	if k == "tao":
		return (f"SELECT r.order_id INTO v_don FROM public.create_order_with_lines({_p(b['p'])}) r; "
			"SELECT id INTO v_pt FROM returns WHERE order_id = v_don ORDER BY created_at, ctid LIMIT 1;")
	if k == "xuat":
		dong_x = _lit(json.dumps(ref(b["dong"])))
		return f"""
      SELECT jsonb_agg(CASE WHEN x.e->>0 IS NULL THEN x.e->1
          ELSE jsonb_build_object('order_line_id', l.id, 'product_id', l.product_id, 'unit_name', l.unit_name,
            'conversion_factor', l.conversion_factor, 'quantity', l.quantity - COALESCE(l.invoiced_qty, 0), 'unit_price', l.unit_price,
            'line_discount', l.line_discount, 'vat_rate', l.vat_rate, 'is_exchange', false, 'note', l.note) || (x.e->1) END
          ORDER BY x.i) INTO v_dong
        FROM jsonb_array_elements({dong_x}::jsonb) WITH ORDINALITY x(e, i)
        LEFT JOIN LATERAL (SELECT * FROM sales_order_lines s WHERE s.order_id = v_don ORDER BY s.ctid OFFSET (x.e->>0)::int LIMIT 1) l
          ON x.e->>0 IS NOT NULL;
      SELECT r.invoice_id, to_jsonb(r) INTO v_hd, v_tra
        FROM public.post_invoice({_p(b['p'])} || jsonb_build_object('order_id', v_don, 'lines', COALESCE(v_dong, '[]'::jsonb))) r;
      v_ds := v_ds || jsonb_build_array(v_tra);
      SELECT COALESCE((SELECT id FROM returns WHERE invoice_id = v_hd ORDER BY created_at, ctid LIMIT 1), v_pt) INTO v_pt;"""
	if k == "lap":
		return f"SELECT public.create_return_with_lines({_p(b['head'])}, {_p(b['lines'])}) INTO v_pt;"
	if k == "pos":
		return f"SELECT public.save_pos_return({_p(b['p'])}) INTO v_pt;"
	if k == "hoan":
		if b.get("ngay"):
			return (f"SELECT to_jsonb(r) INTO v_tra FROM public.complete_return(v_pt, {_lit(b['zone'])}, "
				f"{_lit(ngay_tuong_doi(b['ngay']))}::date) r; v_ds := v_ds || jsonb_build_array(v_tra);")
		return (f"SELECT to_jsonb(r) INTO v_tra FROM public.complete_return(v_pt, {_lit(b['zone'])}) r; "
			"v_ds := v_ds || jsonb_build_array(v_tra);")
	if k == "huy_pt":
		return f"PERFORM public.cancel_return(v_pt, {_lit(b['ly_do'])});"
	if k == "huy":
		return (f"SELECT to_jsonb(r) INTO v_tra FROM public.cancel_invoice(v_hd, {_lit(b['ly_do'])}) r; "
			"v_ds := v_ds || jsonb_build_array(v_tra);")
	if k == "sua":
		dong_x = _lit(json.dumps(ref(b["dong"])))
		return f"""
      SELECT jsonb_agg(CASE WHEN x.e->>0 IS NULL THEN x.e->1
          ELSE jsonb_build_object('order_line_id', l.order_line_id, 'product_id', l.product_id, 'unit_name', l.unit_name,
            'conversion_factor', l.conversion_factor, 'quantity', l.quantity, 'unit_price', l.unit_price,
            'line_discount', l.line_discount, 'vat_rate', l.vat_rate, 'is_exchange', l.is_exchange, 'note', l.note) || (x.e->1) END
          ORDER BY x.i) INTO v_dong
        FROM jsonb_array_elements({dong_x}::jsonb) WITH ORDINALITY x(e, i)
        LEFT JOIN LATERAL (SELECT * FROM sales_invoice_lines s WHERE s.invoice_id = v_hd ORDER BY s.sort_order OFFSET (x.e->>0)::int LIMIT 1) l
          ON x.e->>0 IS NOT NULL;
      SELECT r.invoice_id, to_jsonb(r) INTO v_hd, v_tra
        FROM public.reissue_invoice(v_hd, {_p(b['p'])} || jsonb_build_object('lines', COALESCE(v_dong, '[]'::jsonb))) r;
      v_ds := v_ds || jsonb_build_array(v_tra);"""
	if k == "chon":
		dk = {"don": "order_id = v_don", "hd": "invoice_id = v_hd", "moi_nhat": f"org_id = '{ORG}'"}[b["cach"]]
		thu_tu = "created_at DESC, return_seq DESC" if b["cach"] == "moi_nhat" else "created_at, return_seq"
		return f"EXECUTE 'RESET ROLE'; SELECT id INTO v_pt FROM returns WHERE {dk} ORDER BY {thu_tu} LIMIT 1;"
	if k == "gan":
		return f"PERFORM public.assign_doc_seller('return', v_pt, '{uid('u:' + b['nv'])}');"
	if k == "ghi":
		cau = b["cau"].replace(":pt", "%1$L::uuid").replace(":hd", "%2$L::uuid").replace(":don", "%3$L::uuid")
		return f"EXECUTE format($q${cau}$q$, v_pt::text, v_hd::text, v_don::text);"
	raise ValueError(f"bước lạ: {k}")


def sql_tinh_huong(t: dict) -> str:
	khoi = []
	for b in t["buoc"]:
		u = uid("u:" + b["nguoi"])
		khoi.append(f"""
  IF NOT v_dung THEN
    BEGIN
      EXECUTE 'SET CONSTRAINTS ALL DEFERRED';
      PERFORM set_config('request.jwt.claim.sub', {_lit(u)}, true);
      EXECUTE 'SET LOCAL ROLE authenticated';
      {_lenh(b)}
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
  v_don uuid; v_hd uuid; v_pt uuid; v_dong jsonb; v_tra jsonb; v_ds jsonb := '[]'::jsonb; v_kq jsonb := '[]'::jsonb;
  v_dung boolean := false;
  v_ct jsonb;
BEGIN
  BEGIN
    UPDATE organizations SET allow_oversell = {str(t.get('cho_ban_vuot_ton', False)).lower()} WHERE id = '{ORG}';
    {''.join(khoi)}
    SELECT public._vang_anh_chup() INTO v_ct;
    v_ct := v_ct || jsonb_build_object('tra_ve', v_ds);
    RAISE EXCEPTION USING ERRCODE = 'ZZ999';
  EXCEPTION WHEN SQLSTATE 'ZZ999' THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  INSERT INTO _vang_kq VALUES ({_lit(t['ma'])}, v_kq, v_ct);
END $c$;
"""


def sql_ham_phu() -> str:
	"""Hàm phụ (tạo trong giao dịch của bộ sinh, lui cùng ROLLBACK cuối): thay "@dong_tra:N" + ảnh chụp trạng thái cả NPP."""
	return f"""
CREATE OR REPLACE FUNCTION public._vang_thay_dong(p text, p_pt uuid) RETURNS text LANGUAGE plpgsql AS $f$
DECLARE r record; v text := p;
BEGIN
  IF p_pt IS NULL OR position('@dong_tra:' IN p) = 0 THEN RETURN p; END IF;
  FOR r IN SELECT row_number() OVER (ORDER BY ctid) - 1 AS i, id FROM return_lines WHERE return_id = p_pt LOOP
    v := replace(v, '"@dong_tra:' || r.i || '"', to_jsonb(r.id::text)::text);
  END LOOP;
  RETURN v;
END $f$;
GRANT EXECUTE ON FUNCTION public._vang_thay_dong(text, uuid) TO authenticated;

CREATE OR REPLACE FUNCTION public._vang_anh_chup() RETURNS jsonb LANGUAGE sql AS $f$
  SELECT jsonb_build_object(
    'pt', (SELECT jsonb_agg(jsonb_build_object(
        'ma', r.return_code, 'status', r.status, 'tu_sinh', r.credit_with_invoice, 'tien', r.credit_note_amount,
        'ngay_tra', r.return_date, 'ngay_tru', r.revenue_date, 'co_ghi_co', r.credited_at IS NOT NULL,
        'ghi_co_12h', r.credited_at IS NOT NULL AND (r.credited_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::time = time '12:00',
        'co_hoan_thanh', r.completed_at IS NOT NULL, 'zone', r.destination_zone, 'ly_do', r.reason, 'ghi_chu', r.notes,
        'ly_do_huy', r.cancel_reason, 'co_huy_luc', r.cancelled_at IS NOT NULL,
        'hd', (SELECT si.invoice_code FROM sales_invoices si WHERE si.id = r.invoice_id), 'co_don', r.order_id IS NOT NULL,
        'nv', (SELECT u.full_name FROM users u WHERE u.id = r.sales_user_id),
        'nguoi_lap', (SELECT u.full_name FROM users u WHERE u.id = r.requested_by),
        'hoan_thanh_boi', (SELECT u.full_name FROM users u WHERE u.id = r.completed_by),
        'dong', (SELECT jsonb_agg(jsonb_build_object('sp', (SELECT p.sku FROM products p WHERE p.id = l.product_id), 'dv', l.unit_name,
            'sl', l.quantity, 'gia', l.unit_price, 'thue', l.vat_rate, 'tien', l.line_total, 'doi', l.is_exchange, 'ly_do', l.reason,
            'ghi_chu', l.note) ORDER BY l.ctid) FROM return_lines l WHERE l.return_id = r.id)
      ) ORDER BY r.return_seq) FROM returns r WHERE r.org_id = '{ORG}'),
    'cong_no', (SELECT jsonb_agg(jsonb_build_object(
        'hd', (SELECT si.invoice_code FROM sales_invoices si WHERE si.id = c.invoice_id),
        'pt', (SELECT r.return_code FROM returns r WHERE r.id = c.return_id), 'dau_ky', c.opening_balance,
        'so_tien', c.amount, 'da_thu', c.paid, 'status', c.status,
        'nv', (SELECT u.full_name FROM users u WHERE u.id = c.sales_user_id))
      ORDER BY (SELECT si.invoice_code FROM sales_invoices si WHERE si.id = c.invoice_id) NULLS LAST,
        (SELECT r.return_code FROM returns r WHERE r.id = c.return_id) NULLS LAST, c.amount) FROM receivables c WHERE c.org_id = '{ORG}'),
    'hd', (SELECT jsonb_agg(jsonb_build_object('ma', si.invoice_code, 'status', si.status, 'ngay', si.invoice_date, 'han', si.due_date,
        'subtotal', si.subtotal, 'vat', si.vat, 'total', si.total, 'huy_ly_do', si.cancel_reason,
        'sales_user', (SELECT u.full_name FROM users u WHERE u.id = si.sales_user_id),
        'dong', (SELECT jsonb_agg(jsonb_build_object('sp', (SELECT p.sku FROM products p WHERE p.id = l.product_id), 'dv', l.unit_name,
            'hs', l.conversion_factor, 'sl', l.quantity, 'gia', l.unit_price, 'giam', l.line_discount, 'tien', l.line_total,
            'thue', l.vat_rate, 'doi', l.is_exchange, 'noi_don', l.order_line_id IS NOT NULL) ORDER BY l.sort_order)
          FROM sales_invoice_lines l WHERE l.invoice_id = si.id)
      ) ORDER BY si.invoice_seq, si.reissue_no) FROM sales_invoices si WHERE si.org_id = '{ORG}'),
    'don', (SELECT jsonb_agg(jsonb_build_object('status', so.status,
        'dong_don', (SELECT jsonb_agg(jsonb_build_array((SELECT p.sku FROM products p WHERE p.id = l.product_id), l.unit_name, l.quantity,
            l.invoiced_qty) ORDER BY (SELECT p.sku FROM products p WHERE p.id = l.product_id), l.unit_name, l.quantity)
          FROM sales_order_lines l WHERE l.order_id = so.id)) ORDER BY so.created_at, so.ctid) FROM sales_orders so WHERE so.org_id = '{ORG}'),
    'ton_lo', (SELECT jsonb_object_agg(b.batch_code || '@' || b.warehouse_zone, jsonb_build_array(b.qty_on_hand, b.unit_cost))
      FROM batches b WHERE b.org_id = '{ORG}'),
    'lo_moi', (SELECT jsonb_agg(jsonb_build_object('sp', (SELECT p.sku FROM products p WHERE p.id = b.product_id),
        'ma_dau', split_part(b.batch_code, '-', 1), 'zone', b.warehouse_zone, 'ton', b.qty_on_hand, 'gia_von', b.unit_cost,
        'han', b.expires_at) ORDER BY b.created_at, b.batch_code)
      FROM batches b WHERE b.org_id = '{ORG}' AND b.batch_code NOT IN ({', '.join(_lit(x[0]) for x in LO)})),
    'phieu_kho', (SELECT jsonb_agg(jsonb_build_object('loai', e.type, 'status', e.status,
        'ghi_chu', regexp_replace(COALESCE(e.notes, ''), '[0-9a-f]{{8}}-[0-9a-f-]{{27}}', '<id>', 'g'),
        'dong', (SELECT jsonb_agg(jsonb_build_array((SELECT p.sku FROM products p WHERE p.id = l.product_id), l.unit_name, l.quantity,
            l.qty_in_base_uom, l.unit_cost) ORDER BY l.ctid) FROM stock_entry_lines l WHERE l.entry_id = e.id))
      ORDER BY e.created_at, e.ctid) FROM stock_entries e WHERE e.org_id = '{ORG}' AND COALESCE(e.notes, '') ~* '(phiếu trả|phieu tra|trả hàng)'),
    'hom_nay', (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date)
$f$;
"""


# ------------------------------------------------------------------------------------------------ tình huống (điền theo đặc tả)
def tinh_huong() -> list[dict]:
	T: list[dict] = []
	return T


def _chuan(k: dict) -> dict:
	"""Ngày thật → "@hom_nay±n"; bỏ UUID ngẫu nhiên trong câu trả về."""
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
	for p in ct.get("pt") or []:
		for khoa in ("ngay_tra", "ngay_tru"):
			p[khoa] = ngay(p.get(khoa))
	for h in ct.get("hd") or []:
		for khoa in ("ngay", "han"):
			h[khoa] = ngay(h.get(khoa))
	for x in ct.get("lo_moi") or []:
		x["han"] = ngay(x.get("han"))
	for x in ct.get("tra_ve") or []:
		if isinstance(x, dict):
			for khoa in list(x):
				if khoa.endswith("_id") or khoa in ("entry_id",):
					x[khoa] = bool(x.get(khoa))
	ct.pop("hom_nay", None)
	return k


def main():
	T = tinh_huong()
	if not T:
		raise SystemExit("chưa có tình huống — điền tinh_huong() theo đặc tả phiếu trả")
	sql = ["BEGIN;", sql_nen(), sql_lo(), sql_ham_phu(), "CREATE TEMP TABLE _vang_kq (ma text, buoc jsonb, ct jsonb);"]
	sql += [sql_tinh_huong(t) for t in T]
	sql.append("SELECT json_agg(json_build_object('ma', ma, 'buoc', buoc, 'ct', ct)) FROM _vang_kq;")
	sql.append("ROLLBACK;")
	ra = subprocess.run(PSQL, shell=True, input="\n".join(sql), capture_output=True, text=True, check=False)
	if ra.returncode != 0:
		raise SystemExit(ra.stderr[-4000:])
	kq = {k["ma"]: _chuan(k) for k in json.loads(ra.stdout.strip().splitlines()[-1])}
	tep = {"ghi_chu": "Sinh bởi tools/vang_phieu_tra.py — hàm + trigger thật của nppsale (phiếu trả tự sinh / tự lập, hàng đổi, nhập kho, huỷ).",
		"nen": {"nguoi": NGUOI, "nhom": NHOM, "khach": KHACH, "hang": HANG, "gia": GIA, "lo": LO},
		"tinh_huong": [dict(t, mong={"buoc": kq[t["ma"]]["buoc"], "ct": kq[t["ma"]]["ct"]}) for t in T]}
	with open(DICH, "w", encoding="utf-8") as f:
		json.dump(tep, f, ensure_ascii=False, indent=1)
		f.write("\n")
	print(f"{len(T)} tình huống → {DICH}")
	for t in T:
		k = kq[t["ma"]]
		bs = " | ".join("ok" if x["ok"] else f"{x['ma_loi']} {x['loi'][:110]}" for x in k["buoc"])
		pts = "; ".join(f"{p['ma']} {p['status']} {p['tien']}" for p in (k["ct"] or {}).get("pt") or [])
		print(f"  {t['ma']:<34} {bs}\n      → {pts[:220]}")


if __name__ == "__main__":
	main()
