#!/usr/bin/env python3
"""Dữ liệu vàng cho PHIẾU TRẢ (returns / return_lines của nppsale) — chạy CHÍNH hàm + trigger của nppsale ở Postgres tham chiếu
(schema_full.sql): create_order_with_lines (hàng trả kèm đơn), post_invoice (return_adds / return_edits, gắn phiếu nháp của đơn →
tự sinh), create_return_with_lines, save_pos_return, complete_return (2 / 3 tham số), cancel_return, cancel_invoice, reissue_invoice
(tra_da_nhap lam_lai / giu), assign_doc_seller('return'), ghi thẳng bảng (RLS + trigger khoá — mig 191 / 214 / 227).

Mỗi tình huống chạy trong một giao dịch con rồi lui (ZZ999) — mọi số đếm (PT-…, HD-…) bắt đầu lại từ nền. Mỗi bước chạy dưới đúng người
(request.jwt.claim.sub + ROLE authenticated), bước hỏng thì dừng tình huống và ghi mã + câu lỗi. Chỗ giữ chỗ trong tải trọng:
"@pt" = id phiếu trả đang xét, "@hd" = id HĐ đang xét, "@don" = id đơn; "@dong:SKU:DV" / "@doi:SKU:DV" = id dòng trả / dòng đổi đầu tiên
của mặt hàng + đơn vị ấy trên phiếu đang xét (không theo thứ tự vật lý — Postgres dời dòng khi sửa).

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


def ghi(nguoi, cau, cong):
	"""Ghi thẳng bảng dưới RLS + trigger như cổng PostgREST. cau: câu SQL cho Postgres (chỗ giữ :pt :hd :don lúc chạy, @C1 / @P1 /
	@u:sales_a = id nền); cong: lời ghi của cổng cho bản Frappe ({bang, hanh_dong, gia_tri, loc}; chỗ giữ "@pt" "@hd" "@don"
	"@dong:SKU:DV" như tải trọng RPC). Kết quả so: số dòng bị ghi (UPDATE / DELETE bị RLS lọc → 0, không lỗi)."""
	return {"buoc": "ghi", "nguoi": nguoi, "cau": cau, "cong": cong}


def quyen(nv, khoa, duoc):
	"""Quyền riêng của một người (user_permission_overrides → NPP Quyen Rieng) — đặt bằng quyền quản trị."""
	return {"buoc": "quyen", "nguoi": "owner", "nv": nv, "khoa": khoa, "duoc": duoc}


def huy_don(nguoi, ly_do="Khach khong lay"):
	"""cancel_order(@don, lý do)."""
	return {"buoc": "huy_don", "nguoi": nguoi, "ly_do": ly_do}


def gan_hd(nguoi, nv):
	"""assign_doc_seller('invoice', @hd, nv)."""
	return {"buoc": "gan_hd", "nguoi": nguoi, "nv": nv}


def dong_hd(nguoi="owner"):
	"""get_invoiceable_lines(@don) — kết quả (bỏ id) vào tra_ve."""
	return {"buoc": "dong_hd", "nguoi": nguoi}


def doi_khach_don(khach):
	"""Đổi khách của đơn đang xét bằng quyền quản trị (PG: UPDATE sales_orders; Frappe: sửa thẳng Sales Order) — không đụng phiếu trả."""
	return {"buoc": "doi_khach_don", "nguoi": "owner", "khach": khach}


def goi(nguoi, ten, sql_args, ts):
	"""Gọi RPC bất kỳ: sql_args = đối số SQL cho Postgres (@C1 / @u:x = id nền; :pt :hd :don lúc chạy); ts = tham số RPC của bản Frappe."""
	return {"buoc": "goi", "nguoi": nguoi, "ten": ten, "sql": sql_args, "ts": ts}


def doi_nv_don(nv):
	"""Đổi người đứng tên đơn đang xét bằng quyền quản trị (UPDATE sales_orders.sales_user_id / Sales Order.npp_nhan_vien)."""
	return {"buoc": "doi_nv_don", "nguoi": "owner", "nv": nv}


# ------------------------------------------------------------------------------------------------ SQL
_THAY = ("replace(replace(replace({x}, '\"@pt\"', COALESCE(to_jsonb(v_pt::text)::text, 'null')), "
	"'\"@hd\"', COALESCE(to_jsonb(v_hd::text)::text, 'null')), '\"@don\"', COALESCE(to_jsonb(v_don::text)::text, 'null'))")


CHO_GIU_CHAY = ("@pt", "@hd", "@don")


def _ref(v):
	"""ref() của bộ tạo đơn nhưng giữ nguyên chỗ giữ lúc chạy ("@pt" "@hd" "@don" "@dong:…" "@doi:…")."""
	if isinstance(v, str) and (v in CHO_GIU_CHAY or v.startswith(("@dong:", "@doi:"))):
		return v
	if isinstance(v, dict):
		return {a: _ref(b) for a, b in v.items()}
	if isinstance(v, list):
		return [_ref(x) for x in v]
	return ref(v)


def _p(v) -> str:
	"""Tải trọng JSON → biểu thức jsonb có thay chỗ giữ lúc chạy (+ "@dong:…" / "@doi:…")."""
	t = _lit(json.dumps(_ref(ngay_tuong_doi(v)), ensure_ascii=False))
	return f"public._vang_thay_dong({_THAY.format(x=t)}, v_pt)::jsonb"


def _lenh(b: dict) -> str:
	k = b["buoc"]
	if k == "tao":
		return (f"SELECT r.order_id INTO v_don FROM public.create_order_with_lines({_p(b['p'])}) r; "
			"SELECT id INTO v_pt FROM returns WHERE order_id = v_don ORDER BY created_at, ctid LIMIT 1;")
	if k == "xuat":
		dong_x = _lit(json.dumps(_ref(b["dong"])))
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
		# complete_return RETURNS TABLE(entry_id uuid) — một cột: bí danh là chính giá trị (PostgREST trả [{entry_id}])
		if b.get("ngay"):
			return (f"SELECT jsonb_build_object('entry_id', x) INTO v_tra FROM public.complete_return(v_pt, {_lit(b['zone'])}, "
				f"{_lit(ngay_tuong_doi(b['ngay']))}::date) AS x; v_ds := v_ds || jsonb_build_array(v_tra);")
		return (f"SELECT jsonb_build_object('entry_id', x) INTO v_tra FROM public.complete_return(v_pt, {_lit(b['zone'])}) AS x; "
			"v_ds := v_ds || jsonb_build_array(v_tra);")
	if k == "huy_pt":
		return f"PERFORM public.cancel_return(v_pt, {'NULL' if b['ly_do'] is None else _lit(b['ly_do'])});"
	if k == "huy":
		return (f"SELECT to_jsonb(r) INTO v_tra FROM public.cancel_invoice(v_hd, {_lit(b['ly_do'])}) r; "
			"v_ds := v_ds || jsonb_build_array(v_tra);")
	if k == "sua":
		dong_x = _lit(json.dumps(_ref(b["dong"])))
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
		cau = _sql_ref(b["cau"]).replace(":pt", "%1$L::uuid").replace(":hd", "%2$L::uuid").replace(":don", "%3$L::uuid")
		return (f"EXECUTE format($q${cau}$q$, v_pt::text, v_hd::text, v_don::text); GET DIAGNOSTICS v_n = ROW_COUNT; "
			"v_ds := v_ds || jsonb_build_array(jsonb_build_object('so_dong', v_n));")
	if k == "quyen":
		return (f"EXECUTE 'RESET ROLE'; INSERT INTO user_permission_overrides (user_id, permission_key, granted, org_id) VALUES "
			f"('{uid('u:' + b['nv'])}', {_lit(b['khoa'])}, {str(b['duoc']).lower()}, '{ORG}') ON CONFLICT (user_id, permission_key) "
			f"DO UPDATE SET granted = EXCLUDED.granted;")
	if k == "huy_don":
		return f"PERFORM public.cancel_order(v_don, {_lit(b['ly_do'])});"
	if k == "gan_hd":
		return f"PERFORM public.assign_doc_seller('invoice', v_hd, '{uid('u:' + b['nv'])}');"
	if k == "dong_hd":
		return ("SELECT COALESCE(jsonb_agg(to_jsonb(r)), '[]'::jsonb) INTO v_tra FROM public.get_invoiceable_lines(v_don) r; "
			"v_ds := v_ds || jsonb_build_array(jsonb_build_object('dong_hd', v_tra));")
	if k == "doi_khach_don":
		return f"EXECUTE 'RESET ROLE'; UPDATE sales_orders SET customer_id = '{uid(b['khach'][1:])}' WHERE id = v_don;"
	if k == "goi":
		args = _sql_ref(b["sql"]).replace(":pt", "%1$L::uuid").replace(":hd", "%2$L::uuid").replace(":don", "%3$L::uuid")
		return f"EXECUTE format($q$SELECT public.{b['ten']}({args})$q$, v_pt::text, v_hd::text, v_don::text);"
	if k == "doi_nv_don":
		return f"EXECUTE 'RESET ROLE'; UPDATE sales_orders SET sales_user_id = '{uid('u:' + b['nv'])}' WHERE id = v_don;"
	raise ValueError(f"bước lạ: {k}")


def _sql_ref(cau: str) -> str:
	"""@C1 / @P1 / @u:sales_a trong câu SQL → id nền đặt trong nháy."""
	import re

	return re.sub(r"@(u:[A-Za-z0-9_]+|[A-Z][A-Za-z0-9_]*)", lambda m: f"'{ref('@' + m.group(1))}'", cau)


# Cờ phiên `npp.*` các hàm đặt bằng set_config(…, true) sống tới HẾT GIAO DỊCH; mỗi tình huống chạy cả chuỗi bước trong MỘT giao dịch
# (production: mỗi lời gọi một giao dịch) → xoá hết trước mỗi bước, không thì `npp.via_rpc = 'on'` của post_invoice rò sang lời ghi thẳng
# sau đó (guard người đứng tên, khoá trình duyệt bị miễn sai).
CO_PHIEN = ("npp.don_dong_215", "npp.duyet_anh_diem_ban", "npp.giao_cong_no", "npp.giu_phieu_tu_lap", "npp.he_so_tu_hd",
	"npp.reissue_chuyen_thu", "npp.reissue_nguoi_no", "npp.reissue_stash", "npp.tra_da_nhap_210", "npp.via_rpc")
DAT_LAI_CO = " ".join(f"PERFORM set_config('{c}', '', true);" for c in CO_PHIEN)


def sql_tinh_huong(t: dict) -> str:
	khoi = []
	for b in t["buoc"]:
		u = uid("u:" + b["nguoi"])
		khoi.append(f"""
  IF NOT v_dung THEN
    BEGIN
      EXECUTE 'SET CONSTRAINTS ALL DEFERRED';
      {DAT_LAI_CO}
      PERFORM set_config('request.jwt.claim.sub', {_lit(u)}, true);
      EXECUTE 'SET LOCAL ROLE authenticated';
      {_lenh(b)}
      EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';
      EXECUTE 'RESET ROLE';
      EXECUTE 'SET LOCAL session_replication_role = replica';
      UPDATE returns SET created_at = clock_timestamp() WHERE org_id = '{ORG}' AND created_at = now();
      UPDATE sales_orders SET created_at = clock_timestamp() WHERE org_id = '{ORG}' AND created_at = now();
      EXECUTE 'SET LOCAL session_replication_role = origin';
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
  v_dung boolean := false; v_n int;
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
	"""Hàm phụ (tạo trong giao dịch của bộ sinh, lui cùng ROLLBACK cuối): thay "@dong:…" / "@doi:…" + ảnh chụp trạng thái cả NPP."""
	return f"""
CREATE OR REPLACE FUNCTION public._vang_thay_dong(p text, p_pt uuid) RETURNS text LANGUAGE plpgsql SECURITY DEFINER AS $f$
DECLARE r record; v text := p;
BEGIN
  IF p_pt IS NULL OR (position('@dong:' IN p) = 0 AND position('@doi:' IN p) = 0) THEN RETURN p; END IF;
  FOR r IN SELECT DISTINCT ON (l.is_exchange, pr.sku, l.unit_name) l.id, l.is_exchange, pr.sku, l.unit_name
      FROM return_lines l JOIN products pr ON pr.id = l.product_id WHERE l.return_id = p_pt
      ORDER BY l.is_exchange, pr.sku, l.unit_name, l.ctid LOOP
    v := replace(v, '"@' || CASE WHEN r.is_exchange THEN 'doi' ELSE 'dong' END || ':' || r.sku || ':' || r.unit_name || '"',
      to_jsonb(r.id::text)::text);
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
            'ghi_chu', l.note) ORDER BY l.is_exchange, (SELECT p.sku FROM products p WHERE p.id = l.product_id), l.unit_name, l.unit_price,
            l.quantity) FROM return_lines l WHERE l.return_id = r.id)
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
    'nhap', (SELECT jsonb_agg(jsonb_build_array(r.return_code, (SELECT p.sku FROM products p WHERE p.id = l.product_id), l.qty_in_base_uom,
        l.unit_cost) ORDER BY r.return_code, (SELECT p.sku FROM products p WHERE p.id = l.product_id), l.qty_in_base_uom)
      FROM stock_entries e JOIN returns r ON e.notes = 'Nhập lại từ phiếu trả ' || r.id::text
      JOIN stock_entry_lines l ON l.entry_id = e.id WHERE e.org_id = '{ORG}' AND e.status = 'posted'),
    'hom_nay', (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date)
$f$;
"""


# ------------------------------------------------------------------------------------------------ tình huống (đặc tả §6, Sổ C)
def dt(sp="@P1", dv="Lon", sl=1, gia=9500, thue=0.08, doi=False, **k):
	"""Dòng trả / đổi (tải trọng RPC: return_lines, return_adds, lines của save_pos_return / create_return_with_lines)."""
	d = {"product_id": sp, "unit_name": dv, "quantity": sl, "unit_price": gia, "vat_rate": thue, "is_exchange": doi}
	d.update(k)
	return d


def doi_x(sp="@P2", dv="Chai", sl=1, hs=1, thue=0.1):
	"""Dòng hàng ĐỔI xuất đi trong lines của post_invoice (POS dựng bằng dongHangDoi: giá 0, '[Exchange]')."""
	return (None, {"product_id": sp, "unit_name": dv, "conversion_factor": hs, "quantity": sl, "unit_price": 0, "line_discount": 0,
		"vat_rate": thue, "is_exchange": True, "note": "[Exchange]"})


TRA = {"reason": "damaged"}
DT_DOI = [dt(sl=1, gia=9500, reason="damaged"), dt("@P2", "Chai", 1, 5000, 0.1, doi=True)]  # G14: trả P1 Lon 1 + đổi P2 Chai 1
L2 = [dong(sl=2, gia=9500)]
PT_ID = {"op": "eq", "cot": "id", "gt": "@pt"}


def _don_tra(ma, nguoi="sales_a", lines=None, dong_tra=None, **o):
	return don(nguoi, lines or L2, ma, tra=TRA, dong_tra=DT_DOI if dong_tra is None else dong_tra, **o)


def _hd_c1(ma, nguoi="sales_a", lines=None, **o):
	"""Đơn C1 không hàng trả + xuất ngay (owner) → HĐ của C1 đứng tên `nguoi`."""
	ls = lines or L2
	return [don(nguoi, ls, ma, **o), xuat("owner", [(i, {}) for i in range(len(ls))])]


def tinh_huong() -> list[dict]:
	T: list[dict] = []

	def th(ma, *buoc, **k):
		T.append({"ma": ma, "buoc": list(buoc), **k})

	# ---------------------------------------------------------------- nhóm 1: lập / sửa nháp, luật chung
	th("g01_pos_nhap", pos("sales_a", {"customer_id": "@C1", "reason": "damaged", "notes": "t1", "lines": [
		dt(sl=2, gia=9500, thue=0.1, reason="expired"), dt("@P2", "Chai", 1, 5000, 0.1, doi=True, reason="damaged"),
		dt("@P2", "Chai", 0, 5000, 0.1)]}))
	th("g02a_nv_khac_hd_gan_nhat", *_hd_c1("g02a"), pos("sales_b", {"customer_id": "@C1", "lines": [dt()]}))
	th("g02b_nv_khac_gan_hd", *_hd_c1("g02b"), pos("sales_b", {"customer_id": "@C1", "invoice_id": "@hd", "lines": [dt()]}))
	th("g02c_thu_kho", pos("warehouse", {"customer_id": "@C1", "lines": [dt()]}))
	th("g02d_ke_toan", pos("accountant", {"customer_id": "@C1", "lines": [dt()]}))
	th("g02e_chu_khach_chua_mua", pos("owner", {"customer_id": "@C2", "lines": [dt(gia=10000)]}))
	th("g02f_lech_khach", *_hd_c1("g02f"), pos("owner", {"customer_id": "@C2", "invoice_id": "@hd", "lines": [dt(gia=10000)]}))
	th("g02g_nv_khach_chua_mua", pos("sales_a", {"customer_id": "@C2", "lines": [dt(gia=10000)]}))
	hd_giam = _hd_c1("g03", "owner", [dong(sl=10, gia=9500), dong(dv="Thung", sl=1, gia=220000, giam=10000, hs=24)],
		sales_user_id="@u:sales_a")
	th("g03a_tran_gan_hd", *hd_giam, pos("sales_a", {"customer_id": "@C1", "invoice_id": "@hd", "lines": [dt(gia=9500)]}),
		pos("sales_a", {"customer_id": "@C1", "invoice_id": "@hd", "lines": [dt(gia=9501)]}),
		pos("sales_a", {"customer_id": "@C1", "invoice_id": "@hd", "lines": [dt(dv="Thung", gia=230000)]}),
		pos("sales_a", {"customer_id": "@C1", "invoice_id": "@hd", "lines": [dt(gia=9502)]}))
	th("g03b_tran_thung", *hd_giam, pos("sales_a", {"customer_id": "@C1", "invoice_id": "@hd", "lines": [dt(dv="Thung", gia=230002)]}))
	th("g03c_tran_hang_khong_co_tren_hd", *hd_giam,
		pos("sales_a", {"customer_id": "@C1", "invoice_id": "@hd", "lines": [dt("@P2", "Chai", gia=5002, thue=0.1)]}))
	th("g04a_tran_bang_gia_nhom", pos("sales_a", {"customer_id": "@C1", "lines": [dt(gia=9501)]}),
		pos("sales_a", {"customer_id": "@C1", "lines": [dt(gia=9502)]}))
	th("g04b_tran_bang_gia_chung", pos("sales_b", {"customer_id": "@C2", "lines": [dt(gia=10001)]}),
		pos("sales_b", {"customer_id": "@C2", "lines": [dt(gia=10002)]}))
	th("g04c_tran_nang_10", pos("sales_nang10", {"customer_id": "@C2", "lines": [dt(gia=11001)]}),
		pos("sales_nang10", {"customer_id": "@C2", "lines": [dt(gia=11002)]}))
	th("g04d_tran_quan_ly_nang_10", pos("manager_nang10", {"customer_id": "@C1", "lines": [dt(gia=10451)]}),
		pos("manager_nang10", {"customer_id": "@C1", "lines": [dt(gia=10452)]}))
	th("g04e_tran_quan_ly", pos("manager", {"customer_id": "@C1", "lines": [dt(gia=9502)]}))
	th("g04f_tran_ngoai_le", pos("owner", {"customer_id": "@C1", "lines": [dt(gia=99999)]}),
		pos("sales_a", {"customer_id": "@C1", "lines": [dt(gia=99999, doi=True)]}),
		pos("sales_a", {"customer_id": "@C1", "lines": [dt("@P2", "Hop", gia=50001, thue=0.1)]}),
		pos("sales_a", {"customer_id": "@C1", "lines": [dt("@P3", "Goi", gia=77777, thue=0)]}),
		pos("sales_a", {"customer_id": "@C1", "lines": [dt(dv="hop", gia=999999)]}),
		pos("sales_a", {"customer_id": "@C1", "lines": [dt("@P2", "Hop", gia=50002, thue=0.1)]}))
	for ma, ls in (("g05a_gia_am", [dt(gia=-1)]), ("g05b_thue_qua_1", [dt(thue=1.5)]), ("g05c_thue_am", [dt(thue=-0.1)]),
			("g05d_khong_dong", []), ("g05e_moi_dong_sl_0", [dt(sl=0)]), ("g05f_sl_am", [dt(sl=-2)]),
			("g05g_thieu_mat_hang", [{"unit_name": "Lon", "quantity": 1, "unit_price": 9500}]), ("g05h_dong_khong_phai_mang", "x")):
		th(ma, pos("sales_a", {"customer_id": "@C1", "lines": ls}))
	th("g05i_thieu_khach", pos("owner", {"lines": [dt()]}))
	th("g05j_hd_khong_co", pos("owner", {"customer_id": "@C1", "invoice_id": "@P1", "lines": [dt()]}))
	th("g05k_don_vi_rong_va_lam_tron", pos("owner", {"customer_id": "@C1", "lines": [dt(dv="", sl=3, gia=9000, thue=0)]}),
		pos("owner", {"customer_id": "@C1", "lines": [{"product_id": "@P1", "quantity": 1.5, "unit_price": 8999.5, "vat_rate": 0.08}]}))
	th("g05l_ngay_sai_dang", pos("owner", {"customer_id": "@C1", "return_date": "31/12/2026", "lines": [dt()]}))
	th("g05m_complete_chu", pos("owner", {"customer_id": "@C1", "complete": "co", "lines": [dt()]}))
	th("g05n_so_luong_chu", pos("owner", {"customer_id": "@C1", "lines": [dt(sl="hai")]}))
	th("g05o_mat_hang_khong_co", pos("owner", {"customer_id": "@C1", "lines": [dt(sp="@C1")]}))
	th("g06a_nvbh_sua_phieu_nguoi_khac", pos("sales_a", {"customer_id": "@C1", "reason": "damaged", "notes": "goc", "lines": [dt()]}),
		pos("sales_b", {"return_id": "@pt", "customer_id": "@C1", "lines": [dt()]}))
	th("g06b_nvbh_sua_phieu_chu_lap", *_hd_c1("g06b"), pos("owner", {"customer_id": "@C1", "lines": [dt()]}),
		pos("sales_a", {"return_id": "@pt", "customer_id": "@C1", "reason": "expired", "return_date": "@hom_nay-3", "lines": [dt(sl=2)]}))
	th("g06c_doi_khach_hd_nguoi_theo_hd", don("sales_b", [dong(gia=10000)], "g06c", khach="@C2"), xuat("owner", [(0, {})]),
		pos("sales_a", {"customer_id": "@C1", "reason": "damaged", "notes": "n", "lines": [dt()]}),
		pos("sales_a", {"return_id": "@pt", "customer_id": "@C2", "invoice_id": "@hd", "lines": [dt("@P2", "Chai", 1, 5000, 0.1)]}),
		pos("sales_a", {"return_id": "@pt", "customer_id": "@C2", "invoice_id": "@hd", "lines": [dt("@P2", "Chai", 1, 5000, 0.1)]}))
	th("g07a_sua_phieu_da_huy", pos("sales_a", {"customer_id": "@C1", "lines": [dt()]}), huy_pt("owner", "Khach doi y"),
		pos("manager", {"return_id": "@pt", "customer_id": "@C1", "lines": [dt()]}))
	th("g07b_sua_phieu_tu_sinh", _don_tra("g07b"), xuat("owner", [(0, {}), doi_x()]),
		pos("manager", {"return_id": "@pt", "customer_id": "@C1", "lines": [dt()]}))
	th("g07c_sua_phieu_da_nhap_khong_ghi_nhan", pos("owner", {"customer_id": "@C2", "complete": True, "zone": "sale",
		"lines": [dt(gia=10000)]}), pos("manager", {"return_id": "@pt", "customer_id": "@C2", "lines": [dt(gia=10000)]}))
	th("g07d_nvbh_sua_phieu_da_nhap", pos("owner", {"customer_id": "@C1", "complete": True, "zone": "sale", "lines": [dt()]}),
		pos("sales_a", {"return_id": "@pt", "customer_id": "@C1", "complete": True, "lines": [dt()]}))
	th("g07e_tu_sinh_khong_dong", _don_tra("g07e"), xuat("owner", [(0, {}), doi_x()]),
		pos("manager", {"return_id": "@pt", "customer_id": "@C1", "lines": []}))
	th("g07f_nvbh_sua_phieu_theo_don", _don_tra("g07f"), pos("sales_a", {"return_id": "@pt", "customer_id": "@C1", "lines": [dt(sl=2)]}))
	th("g07g_phieu_khong_co", pos("owner", {"return_id": "@P1", "customer_id": "@C1", "lines": [dt()]}))
	th("g08a_lap_web", *_hd_c1("g08a"), lap("sales_a", {"customer_id": "@C1", "invoice_id": "@hd", "order_id": "@don", "reason": "damaged",
		"status": "draft", "credit_note_amount": 123}, [dt(sl=2, gia=9500, thue=0.1, line_total=1)]))
	th("g08b_lap_web_khong_trang_thai", lap("sales_a", {"customer_id": "@C1", "reason": "damaged"}, [dt()]))
	th("g08c_lap_web_hoan_thanh", lap("sales_a", {"customer_id": "@C1", "status": "completed"}, [dt()]))
	th("g09a_chu_dat_nguoi", lap("owner", {"customer_id": "@C2", "sales_user_id": "@u:sales_b", "status": "draft"}, [dt(gia=10000)]))
	th("g09b_nvbh_dat_nguoi_khac", lap("sales_a", {"customer_id": "@C2", "sales_user_id": "@u:sales_b", "status": "draft"},
		[dt(gia=10000)]))
	th("g09c_dat_thu_kho", lap("owner", {"customer_id": "@C2", "sales_user_id": "@u:warehouse", "status": "draft"}, [dt(gia=10000)]))
	th("g09d_dat_nguoi_la", lap("owner", {"customer_id": "@C2", "sales_user_id": "@C1", "status": "draft"}, [dt(gia=10000)]))
	th("g09e_nguoi_theo_hd", *_hd_c1("g09e"), lap("owner", {"customer_id": "@C1", "invoice_id": "@hd", "sales_user_id": "@u:sales_b",
		"status": "draft"}, [dt()]))
	th("g09f_thu_kho_lap", *_hd_c1("g09f"), lap("warehouse", {"customer_id": "@C1", "status": "draft"}, [dt()]))
	th("g09g_ke_toan_lap", *_hd_c1("g09g"), lap("accountant", {"customer_id": "@C1", "status": "draft"}, [dt()]))
	th("g09h_ke_toan_khach_moi", lap("accountant", {"customer_id": "@C2", "status": "draft"}, [dt(gia=10000)]))
	for ma, head, ls in (("g10a_khong_dong", {}, []), ("g10b_gia_am", {}, [dt(gia=-5)]), ("g10c_thue_qua", {}, [dt(thue=1.5)]),
			("g10d_ly_do_phieu_la", {"reason": "khac"}, [dt()]), ("g10e_ly_do_dong_la", {}, [dt(reason="khac")]),
			("g10f_sl_0", {}, [dt(sl=0)]), ("g10g_sl_am", {}, [dt(sl=-2), dt(dv="Thung", gia=1000)]),
			("g10h_thieu_don_vi", {}, [{"product_id": "@P1", "quantity": 2, "unit_price": 9000, "vat_rate": 0}]),
			("g10i_thieu_so_luong", {}, [{"product_id": "@P1", "unit_name": "Lon", "unit_price": 9000}]),
			("g10j_thieu_mat_hang", {}, [{"unit_name": "Lon", "quantity": 1, "unit_price": 9000}]),
			("g10k_vuot_tran", {}, [dt(gia=9502)]), ("g10l_doi_giu_ly_do", {}, [dt("@P2", "Chai", 1, 5000, 0.1, doi=True, reason="expired")]),
			("g10m_thieu_khach", {"customer_id": None}, [dt()]), ("g10n_khach_khong_co", {"customer_id": "@P1"}, [dt()])):
		th(ma, lap("sales_a", {"customer_id": "@C1", "status": "draft", **head}, ls))
	th("g10o_phieu_theo_don", _don_tra("g10o", dong_tra=[]), lap("sales_a", {"customer_id": "@C1", "order_id": "@don", "status": "draft"},
		[dt()]))
	# ghi thẳng (cổng PostgREST) — phiếu nháp của sales_a
	ins = ghi("sales_a", f"INSERT INTO returns (org_id, customer_id, requested_by, status, reason) VALUES ('{ORG}', @C1, @u:sales_a, "
		"'draft', 'damaged')", {"bang": "returns", "hanh_dong": "insert", "gia_tri": {"customer_id": "@C1", "status": "draft",
			"reason": "damaged"}})
	dong_l = ghi("sales_a", "INSERT INTO return_lines (return_id, product_id, unit_name, quantity, unit_price, line_total) VALUES "
		"(:pt, @P1, 'Lon', 3, 9500, 1)", {"bang": "return_lines", "hanh_dong": "insert", "gia_tri": {"return_id": "@pt", "product_id": "@P1",
			"unit_name": "Lon", "quantity": 3, "unit_price": 9500, "line_total": 1}})

	def sua_pt(nguoi, gt: dict, sql_set: str):
		return ghi(nguoi, f"UPDATE returns SET {sql_set} WHERE id = :pt", {"bang": "returns", "hanh_dong": "update", "gia_tri": gt,
			"loc": [PT_ID]})

	nen11 = [ins, chon("moi_nhat"), dong_l]
	th("g11a_ghi_thang_nhap", *nen11, sua_pt("sales_a", {"notes": "ghi", "reason": "expired", "return_date": "@hom_nay-2"},
		"notes = 'ghi', reason = 'expired', return_date = (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date - 2"), sua_pt("sales_a", {"credit_note_amount": 1}, "credit_note_amount = 1"),
		ghi("sales_a", "UPDATE return_lines SET quantity = 4 WHERE return_id = :pt", {"bang": "return_lines", "hanh_dong": "update",
			"gia_tri": {"quantity": 4}, "loc": [{"op": "eq", "cot": "return_id", "gt": "@pt"}]}),
		sua_pt("sales_a", {"status": "submitted"}, "status = 'submitted'"))
	th("g11b_chen_cho_xu_ly", ghi("sales_a", f"INSERT INTO returns (org_id, customer_id, requested_by, status) VALUES ('{ORG}', @C1, "
		"@u:sales_a, 'submitted')", {"bang": "returns", "hanh_dong": "insert", "gia_tri": {"customer_id": "@C1", "status": "submitted"}}))
	th("g11c_chen_khong_trang_thai", ghi("sales_a", f"INSERT INTO returns (org_id, customer_id, requested_by) VALUES ('{ORG}', @C1, "
		"@u:sales_a)", {"bang": "returns", "hanh_dong": "insert", "gia_tri": {"customer_id": "@C1"}}))
	th("g11d_cot_chi_rpc", *nen11, sua_pt("sales_a", {"completed_at": "2026-11-01T00:00:00+07:00"}, "completed_at = now()"))
	th("g11e_nvbh_doi_nguoi", *nen11, sua_pt("sales_a", {"sales_user_id": "@u:sales_b"}, "sales_user_id = @u:sales_b"))
	th("g11f_nvbh_gan_hd_nguoi_khac", don("sales_b", [dong(gia=10000)], "g11f", khach="@C2"), xuat("owner", [(0, {})]), *nen11,
		sua_pt("sales_a", {"customer_id": "@C2", "invoice_id": "@hd"}, "customer_id = @C2, invoice_id = :hd"))
	th("g12a_nvbh_khac", *nen11, sua_pt("sales_b", {"notes": "x"}, "notes = 'x'"),
		ghi("sales_b", "DELETE FROM returns WHERE id = :pt", {"bang": "returns", "hanh_dong": "delete", "loc": [PT_ID]}),
		ghi("sales_b", "INSERT INTO return_lines (return_id, product_id, unit_name, quantity, unit_price, line_total) VALUES "
			"(:pt, @P1, 'Lon', 1, 9500, 0)", {"bang": "return_lines", "hanh_dong": "insert", "gia_tri": {"return_id": "@pt",
				"product_id": "@P1", "unit_name": "Lon", "quantity": 1, "unit_price": 9500}}))
	th("g12b_thu_kho", *nen11, sua_pt("warehouse", {"notes": "x"}, "notes = 'x'"),
		ghi("warehouse", "DELETE FROM returns WHERE id = :pt", {"bang": "returns", "hanh_dong": "delete", "loc": [PT_ID]}),
		ghi("warehouse", "INSERT INTO return_lines (return_id, product_id, unit_name, quantity, unit_price, line_total) VALUES "
			"(:pt, @P1, 'Lon', 1, 9500, 0)", {"bang": "return_lines", "hanh_dong": "insert", "gia_tri": {"return_id": "@pt",
				"product_id": "@P1", "unit_name": "Lon", "quantity": 1, "unit_price": 9500}}))
	th("g12c_quan_ly", *nen11, sua_pt("accountant", {"notes": "kt"}, "notes = 'kt'"),
		sua_pt("manager", {"notes": "QL", "sales_user_id": "@u:sales_b"}, "notes = 'QL', sales_user_id = @u:sales_b"),
		ghi("sales_a", "DELETE FROM returns WHERE id = :pt", {"bang": "returns", "hanh_dong": "delete", "loc": [PT_ID]}),
		ghi("manager", "DELETE FROM returns WHERE id = :pt", {"bang": "returns", "hanh_dong": "delete", "loc": [PT_ID]}))
	th("g12d_quan_ly_dat_thu_kho", *nen11, sua_pt("manager", {"sales_user_id": "@u:warehouse"}, "sales_user_id = @u:warehouse"))
	th("g12e_chen_dong_phieu_khong_co", ghi("sales_a", "INSERT INTO return_lines (return_id, product_id, unit_name, quantity, unit_price, "
		"line_total) VALUES (@P2, @P1, 'Lon', 1, 9500, 0)", {"bang": "return_lines", "hanh_dong": "insert", "gia_tri": {"return_id": "@P2",
			"product_id": "@P1", "unit_name": "Lon", "quantity": 1, "unit_price": 9500}}))
	th("g13_thue_100_ngay_tuong_lai", *_hd_c1("g13"), pos("sales_a", {"customer_id": "@C1", "return_date": "@hom_nay+30", "lines": [dt()]}),
		pos("sales_a", {"customer_id": "@C1", "invoice_id": "@hd", "lines": [dt(thue=1)]}))

	# ---------------------------------------------------------------- nhóm 2: phiếu kèm đơn, sửa / huỷ / xoá đơn
	th("g14_don_kem_tra_goi_lai", _don_tra("g14"), _don_tra("g14", dong_tra=[dt(sl=5)]))
	th("g15a_don_nhap_kem_tra", don("sales_a", [dong(sl=10, gia=9500)], "g15a", status="draft", tra={"reason": "damaged",
		"notes": "tra kem"}, dong_tra=[dt(sl=2, line_total=1, reason="expired"), dt("@P2", "Chai", 1, 5000, 0.1, doi=True)]))
	th("g15b_don_kem_tra_vuot_tran", _don_tra("g15b", dong_tra=[dt(gia=9600)]))
	th("g15c_don_kem_tra_sl_am", don("sales_a", L2, "g15c", tra={}, dong_tra=[dt(sl=-1)]))
	th("g15d_chu_lap_don_cho_nv", don("owner", [dong(gia=10000)], "g15d", khach="@C2", sales_user_id="@u:sales_a",
		tra={"reason": "refused"}, dong_tra=[dt(gia=10000)]))
	th("g15e_khong_dong_tra", don("sales_a", L2, "g15e", tra=TRA, dong_tra=[]))
	for ma, dtra, tra in (("g16a_ly_do_dong_la", [dt(reason="abc")], TRA), ("g16b_gia_am", [dt(gia=-1)], TRA),
			("g16c_thue_8", [dt(thue=8)], TRA), ("g16d_ly_do_phieu_la", [dt()], {"reason": "xyz"}), ("g16e_ly_do_phieu_null", [dt()], {})):
		th(ma, don("sales_a", L2, ma, tra=tra, dong_tra=dtra))
	th("g16f_sl_am_no_tang", don("sales_a", L2, "g16f", tra=TRA, dong_tra=[dt(sl=-1)]), xuat("owner", [(0, {})]))
	sync = [_don_tra("g17", dong_tra=[dt()]),
		sua_pt("sales_a", {"reason": "expired", "customer_id": "@C2"}, "reason = 'expired', customer_id = @C2"),
		ghi("sales_a", "DELETE FROM return_lines WHERE return_id = :pt", {"bang": "return_lines", "hanh_dong": "delete",
			"loc": [{"op": "eq", "cot": "return_id", "gt": "@pt"}]}),
		ghi("sales_a", "INSERT INTO return_lines (return_id, product_id, unit_name, quantity, unit_price, vat_rate, line_total) VALUES "
			"(:pt, @P1, 'Thung', 1, 230000, 0.08, 5)", {"bang": "return_lines", "hanh_dong": "insert", "gia_tri": {"return_id": "@pt",
				"product_id": "@P1", "unit_name": "Thung", "quantity": 1, "unit_price": 230000, "vat_rate": 0.08, "line_total": 5}}),
		ghi("sales_a", "INSERT INTO return_lines (return_id, product_id, unit_name, quantity, unit_price, vat_rate, line_total) VALUES "
			"(:pt, @P1, '', 2, 9000, 0.08, 0)", {"bang": "return_lines", "hanh_dong": "insert", "gia_tri": {"return_id": "@pt",
				"product_id": "@P1", "unit_name": "", "quantity": 2, "unit_price": 9000, "vat_rate": 0.08, "line_total": 0}})]
	th("g17a_sua_phieu_kem_don", *sync, sua_pt("sales_a", {"status": "submitted"}, "status = 'submitted'"))
	sync_xuat = [*sync, doi_khach_don("@C2"), xuat("owner", [(0, {})]), sua_pt("sales_a", {"notes": "nv"}, "notes = 'nv'"),
		sua_pt("owner", {"reason": "refused", "notes": "chu"}, "reason = 'refused', notes = 'chu'")]
	th("g17b_sua_dong_tu_sinh", *sync_xuat, ghi("owner", "UPDATE return_lines SET quantity = 3 WHERE return_id = :pt",
		{"bang": "return_lines", "hanh_dong": "update", "gia_tri": {"quantity": 3}, "loc": [{"op": "eq", "cot": "return_id", "gt": "@pt"}]}))
	th("g17c_huy_thang_tu_sinh", *sync_xuat, sua_pt("owner", {"status": "cancelled"}, "status = 'cancelled'"))
	th("g18a_huy_don_kem_tra", _don_tra("g18a"), huy_don("sales_a", "Khach khong lay"))
	th("g18b_xoa_don_nhap_kem_tra", _don_tra("g18b", status="draft"), ghi("sales_a", "DELETE FROM sales_orders WHERE id = :don",
		{"bang": "sales_orders", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "id", "gt": "@don"}]}))
	th("g18c_xoa_phieu_nguoi_khac", pos("sales_a", {"customer_id": "@C1", "lines": [dt()]}),
		ghi("sales_b", "DELETE FROM returns WHERE id = :pt", {"bang": "returns", "hanh_dong": "delete", "loc": [PT_ID]}),
		ghi("sales_a", "DELETE FROM returns WHERE id = :pt", {"bang": "returns", "hanh_dong": "delete", "loc": [PT_ID]}))
	th("g18d_huy_don_chi_phieu_nhap", _don_tra("g18d"), lap("sales_a", {"customer_id": "@C1", "order_id": "@don", "status": "draft"},
		[dt()]), huy_don("owner", "Doi y"))

	# ---------------------------------------------------------------- nhóm 3: hoàn thành / huỷ phiếu TỰ LẬP
	th("g19a_theo_don_khong_hoan_thanh", _don_tra("g19a"), hoan("owner"))
	th("g19b_theo_don_khong_huy", _don_tra("g19b"), huy_pt("owner", "x"))
	th("g19c_lap_web_theo_don", _don_tra("g19c", dong_tra=[]), lap("sales_a", {"customer_id": "@C1", "order_id": "@don", "status": "draft"},
		[dt()]), hoan("owner"))
	doc_lap = pos("owner", {"customer_id": "@C2", "lines": [dt(dv="Thung", sl=2, gia=200000, thue=0.1), dt("@P2", "Chai", 3, 3333.5, 0),
		dt(sl=6, gia=0, doi=True)]})
	th("g20_doc_lap_hoan_thanh", doc_lap, hoan("owner", "sale"))
	th("g21_doc_lap_huy", doc_lap, hoan("owner", "sale"), huy_pt("owner", "khach doi y"))
	th("g24_tra_vuot_hd_kho_date", *_hd_c1("g24"), pos("owner", {"customer_id": "@C1", "invoice_id": "@hd", "complete": True,
		"zone": "date", "lines": [dt(sl=3)]}))
	th("g25_hang_khong_tren_hd", *_hd_c1("g25"), pos("owner", {"customer_id": "@C1", "invoice_id": "@hd", "complete": True, "zone": "sale",
		"lines": [dt("@P2", "Chai", 4, 2500, 0.08)]}))
	th("g25b_hang_chua_co_lo", *_hd_c1("g25b"), pos("owner", {"customer_id": "@C1", "invoice_id": "@hd", "complete": True, "zone": "sale",
		"lines": [dt("@P3", "", 2, 7000, 0.05)]}))
	nhap_c2 = pos("owner", {"customer_id": "@C2", "lines": [dt(gia=10000)]})
	th("g26a_kho_sai", nhap_c2, hoan("owner", "kho"))
	th("g26b_kho_hoa", nhap_c2, hoan("owner", "SALE"))
	th("g27a_hd_da_huy", *_hd_c1("g27a"), huy("owner", "Sai"), pos("owner", {"customer_id": "@C1", "invoice_id": "@hd", "lines": [dt()]}),
		hoan("owner"))
	th("g27b_nvbh_hoan_thanh", nhap_c2, hoan("sales_a"))
	th("g27c_ke_toan_huy", nhap_c2, hoan("owner"), huy_pt("accountant", "x"))
	th("g27d_khong_co_phieu", hoan("owner"))
	th("g27e_hoan_thanh_lai", nhap_c2, hoan("owner"), hoan("owner"))
	th("g27f_huy_lai", nhap_c2, huy_pt("owner", "x"), huy_pt("owner", "y"))
	th("g27g_huy_nhap_rong_khong_ly_do", ghi("owner", f"INSERT INTO returns (org_id, customer_id, requested_by, status) VALUES ('{ORG}', "
		"@C2, @u:owner, 'draft')", {"bang": "returns", "hanh_dong": "insert", "gia_tri": {"customer_id": "@C2", "status": "draft"}}),
		chon("moi_nhat"), huy_pt("owner", None))
	th("g28_huy_khi_hang_da_ban", pos("owner", {"customer_id": "@C2", "complete": True, "zone": "sale", "lines": [dt(sl=10, gia=10000)]}),
		don("owner", [dong(sl=90, gia=10000)], "g28", khach="@C2"), xuat("owner", [(0, {})]), chon("moi_nhat"), huy_pt("owner", "x"))
	th("g29a_sua_phieu_da_nhap_luu_nhap", doc_lap, hoan("owner", "sale"),
		pos("owner", {"return_id": "@pt", "customer_id": "@C2", "lines": [dt(gia=10000)]}))
	th("g29b_ghi_nhan_lai", doc_lap, hoan("owner", "sale"), pos("owner", {"return_id": "@pt", "customer_id": "@C2", "complete": True,
		"zone": "date", "return_date": "@hom_nay-1", "lines": [dt(dv="Thung", sl=1, gia=200000, thue=0.1)]}))
	th("g31_nhap_theo_don_da_xuat_tu_gan_hd", *_hd_c1("g31"), ghi("owner", f"INSERT INTO returns (org_id, customer_id, order_id, requested_by, "
		f"status) VALUES ('{ORG}', @C1, :don, @u:owner, 'draft')", {"bang": "returns", "hanh_dong": "insert", "gia_tri": {"customer_id": "@C1",
			"order_id": "@don", "status": "draft"}}), chon("moi_nhat"),
		pos("owner", {"return_id": "@pt", "customer_id": "@C1", "complete": True, "zone": "sale", "lines": [dt()]}))
	rc = [pos("owner", {"customer_id": "@C2", "complete": True, "zone": "sale", "lines": [dt(gia=10000)]})]
	th("g32a_hoan_thanh_ghi_thang", *rc, sua_pt("owner", {"notes": "ghi", "reason": "expired"}, "notes = 'ghi', reason = 'expired'"),
		sua_pt("owner", {"return_date": "@hom_nay-2"}, "return_date = (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date - 2"),
		ghi("owner", "DELETE FROM returns WHERE id = :pt", {"bang": "returns", "hanh_dong": "delete", "loc": [PT_ID]}),
		sua_pt("owner", {"customer_id": "@C1"}, "customer_id = @C1"))
	th("g32b_hoan_thanh_sua_tien", *rc, sua_pt("owner", {"credit_note_amount": 1}, "credit_note_amount = 1"))
	th("g32c_hoan_thanh_sua_dong", *rc, ghi("owner", "UPDATE return_lines SET quantity = 9 WHERE return_id = :pt", {"bang": "return_lines",
		"hanh_dong": "update", "gia_tri": {"quantity": 9}, "loc": [{"op": "eq", "cot": "return_id", "gt": "@pt"}]}))
	th("g32d_hoan_thanh_huy_thang", *rc, sua_pt("owner", {"status": "cancelled"}, "status = 'cancelled'"))
	rs = [_don_tra("g32e"), xuat("owner", [(0, {}), doi_x()])]
	th("g32e_tu_sinh_ghi_thang", *rs, sua_pt("owner", {"notes": "ts", "return_date": "@hom_nay-1"},
		"notes = 'ts', return_date = (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date - 1"),
		sua_pt("owner", {"sales_user_id": "@u:sales_b"}, "sales_user_id = @u:sales_b"), sua_pt("owner", {"customer_id": "@C2"}, "customer_id = @C2"))
	th("g32f_tu_sinh_chen_dong", *rs, ghi("owner", "INSERT INTO return_lines (return_id, product_id, unit_name, quantity, unit_price, "
		"line_total) VALUES (:pt, @P1, 'Lon', 1, 9500, 0)", {"bang": "return_lines", "hanh_dong": "insert", "gia_tri": {"return_id": "@pt",
			"product_id": "@P1", "unit_name": "Lon", "quantity": 1, "unit_price": 9500}}))
	th("g32g_tu_sinh_chen_dong_vuot_tran", *rs, ghi("sales_a", "INSERT INTO return_lines (return_id, product_id, unit_name, quantity, "
		"unit_price, line_total) VALUES (:pt, @P1, 'Lon', 1, 99999, 0)", {"bang": "return_lines", "hanh_dong": "insert", "gia_tri": {
			"return_id": "@pt", "product_id": "@P1", "unit_name": "Lon", "quantity": 1, "unit_price": 99999}}))
	th("g33a_doi_nguoi_ghi_thang", *rc, sua_pt("owner", {"sales_user_id": "@u:sales_b"}, "sales_user_id = @u:sales_b"),
		sua_pt("owner", {"sales_user_id": "@u:warehouse"}, "sales_user_id = @u:warehouse"))
	th("g33b_gan_nguoi_phieu", *rc, gan("owner", "sales_a"), gan("manager", "sales_b"), gan("sales_a", "sales_a"))
	th("g33c_gan_nguoi_phieu_theo_hd", *rs, gan("owner", "sales_b"))
	th("g34a_nvbh_ghi_nhan", pos("sales_a", {"customer_id": "@C1", "complete": True, "lines": [dt()]}))
	th("g34b_kho_loi", pos("owner", {"customer_id": "@C1", "complete": True, "zone": "loi", "lines": [dt()]}))

	# ---------------------------------------------------------------- nhóm 4: phiếu TỰ SINH qua Xuất hàng
	th("g35_dong_xuat_hang", _don_tra("g35"), dong_hd(), xuat("owner", [(0, {}), doi_x()]), dong_hd())
	th("g35b_dong_doi_theo_hop", _don_tra("g35b", dong_tra=[dt(), dt("@P2", "Hop", 1, 50000, 0.1, doi=True)]), dong_hd())
	tu_sinh = [_don_tra("g36"), xuat("owner", [(0, {}), doi_x()])]
	th("g36_xuat_tu_sinh", *tu_sinh)
	th("g37a_nhap_kho_tu_sinh", *tu_sinh, hoan("owner", "sale"))
	th("g37b_ngay_truoc_hd", *tu_sinh, hoan("owner", "sale", "@hom_nay-1"))
	th("g37c_ngay_tuong_lai", *tu_sinh, hoan("owner", "sale", "@hom_nay+1"))
	th("g37d_kho_la", *tu_sinh, hoan("owner", "kho_la"))
	th("g37e_hd_lui_ngay", _don_tra("g37e"), xuat("owner", [(0, {}), doi_x()], invoice_date="@hom_nay-2"),
		hoan("owner", "sale", "@hom_nay-3"))
	th("g37f_hd_lui_ngay_ok", _don_tra("g37f"), xuat("owner", [(0, {}), doi_x()], invoice_date="@hom_nay-2"),
		hoan("owner", "date", "@hom_nay-1"))
	th("g37g_nvbh_ngay_tuong_lai", *tu_sinh, hoan("sales_a", "sale", "@hom_nay+1"))
	th("g37h_nvbh_ngay_dung", *tu_sinh, hoan("sales_a", "sale", "@hom_nay"))
	th("g37i_thu_kho_co_quyen", *tu_sinh, quyen("warehouse", "returns.approve", True), hoan("warehouse", "sale", "@hom_nay"),
		hoan("warehouse", "sale"))
	th("g37j_tu_lap_chon_ngay", nhap_c2, hoan("owner", "sale", "@hom_nay"))
	th("g38_nhap_date_huy_nhap_lai", _don_tra("g38", dong_tra=[dt(), dt(sl=5, gia=0, doi=True)]),
		xuat("owner", [(0, {}), doi_x("@P1", "Lon", 5, thue=0.08)]), quyen("warehouse", "returns.approve", True),
		hoan("warehouse", "date", "@hom_nay"), huy_pt("warehouse", "nhap nham kho"), hoan("owner", "sale"), huy_pt("owner", "lan hai"))
	th("g39a_huy_tu_sinh", *tu_sinh, huy_pt("owner", "x"))
	th("g39b_pos_tu_sinh", *tu_sinh, pos("owner", {"return_id": "@pt", "customer_id": "@C1", "lines": [dt()]}))
	th("g39c_ghi_dong_tu_sinh", *tu_sinh, ghi("owner", "DELETE FROM return_lines WHERE return_id = :pt", {"bang": "return_lines",
		"hanh_dong": "delete", "loc": [{"op": "eq", "cot": "return_id", "gt": "@pt"}]}))
	th("g40a_xuat_them_tra", don("sales_a", L2, "g40a"), xuat("owner", [(0, {}), doi_x()], return_adds=[dt(reason="expired"),
		dt("@P2", "Chai", 1, 5000, 0.1, doi=True)]))
	th("g40b_xuat_them_tra_sl_0", don("sales_a", L2, "g40b"), xuat("owner", [(0, {})], return_adds=[dt(sl=0)]))
	th("g40c_xuat_them_tra_rong", don("sales_a", L2, "g40c"), xuat("owner", [(0, {})], return_adds=[]))
	th("g41a_xuat_doi_quy_cach", _don_tra("g41a"), xuat("owner", [(0, {}), doi_x()], return_edits=[{"line_id": "@dong:VTD-P1:Lon",
		"quantity": 3, "unit_name": "Loc", "note": "ghi chu moi", "reason": "expired"}]))
	th("g41b_xuat_don_vi_la", _don_tra("g41b"), xuat("owner", [(0, {}), doi_x()], return_edits=[{"line_id": "@dong:VTD-P1:Lon",
		"quantity": 1, "unit_name": "Bao"}]))
	th("g42a_don_kem_tra_9501", _don_tra("g42a", dong_tra=[dt(gia=9501)]))
	th("g42b_chu_don_kem_tra_cao", _don_tra("g42b", "owner", dong_tra=[dt(gia=9600)]))
	th("g42c_doi_gia_cao", _don_tra("g42c", dong_tra=[dt(gia=99999, doi=True)]))
	th("g42d_quan_ly_them_tra_khi_xuat", don("owner", [dong(sl=2, gia=9800)], "g42d"), xuat("manager", [(0, {})], return_adds=[dt(gia=9700)]))
	th("g42e_sua_hd_them_tra_theo_gia_to_cu", _don_tra("g42e", "owner", [dong(sl=2, gia=9800)], dong_tra=[dt()]), xuat("owner", [(0, {})]),
		sua("manager", [(0, {})], return_adds=[dt(gia=9700)]), sua("manager", [(0, {})], return_adds=[dt(gia=9900)]))
	th("g42f_xuat_doi_lon_sang_thung", _don_tra("g42f", "owner", dong_tra=[dt()]), xuat("manager", [(0, {})],
		return_edits=[{"line_id": "@dong:VTD-P1:Lon", "quantity": 1, "unit_name": "Thung"}]))
	nen44 = [don("owner", [dong(sl=2, gia=9500), dong(dv="Thung", sl=1, gia=230000, hs=24)], "g44", tra=TRA, dong_tra=[
		dt(sl=2, gia=9500, thue=0.1, note="g1", reason="expired"), dt("@P2", "Chai", 3, 5000, 0.1), dt("@P2", "Chai", 1, 5000, 0.1, doi=True)])]
	th("g44a_sua_dong_luc_xuat", *nen44, xuat("owner", [(0, {}), (1, {}), doi_x()], return_edits=[
		{"line_id": "@dong:VTD-P1:Lon", "quantity": 1, "unit_name": "Thung"}, {"line_id": "@dong:VTD-P2:Chai", "quantity": 0},
		{"line_id": "@doi:VTD-P2:Chai", "quantity": 2, "note": ""}, {"line_id": "@P1", "quantity": 9}]),
		sua("owner", [(0, {}), (1, {}), (2, {})], return_edits=[{"line_id": "@dong:VTD-P1:Thung", "quantity": 5, "unit_name": "Lon",
			"reason": ""}]))
	th("g44b_don_vi_la", *nen44, xuat("owner", [(0, {}), (1, {}), doi_x()], return_edits=[{"line_id": "@dong:VTD-P1:Lon", "quantity": 1,
		"unit_name": "hop"}]))
	th("g44c_ly_do_la", *nen44, xuat("owner", [(0, {}), (1, {}), doi_x()], return_edits=[{"line_id": "@dong:VTD-P1:Lon", "quantity": 1,
		"reason": "khac"}]))
	for ma, adds in (("g45a_them_gia_am", [dt(gia=-5)]), ("g45b_them_thue_8", [dt(thue=8)]),
			("g45c_them_sl0_va_don_vi_rong", [dt(sl=0, gia=-5), dt(dv="", gia=9000)]), ("g45d_them_ly_do_la", [dt(reason="xx")])):
		th(ma, don("sales_a", L2, ma), xuat("owner", [(0, {})], return_adds=adds))
	th("g46a_hai_phieu_theo_don", _don_tra("g46a"), lap("sales_a", {"customer_id": "@C1", "order_id": "@don", "reason": "refused",
		"status": "draft"}, [dt("@P2", "Chai", 2, 5000, 0.1)]), xuat("owner", [(0, {}), doi_x()], return_adds=[dt(sl=4)]))
	th("g46b_khach_lech", _don_tra("g46b"), doi_khach_don("@C2"), xuat("owner", [(0, {}), doi_x()]))

	# ---------------------------------------------------------------- nhóm 5: Huỷ HĐ / Sửa HĐ
	da_nhap = [*tu_sinh, hoan("owner", "sale")]
	cu2 = [(0, {}), (1, {})]
	th("g47a_sua_hd_chua_chon", *da_nhap, sua("owner", cu2))
	th("g47b_sua_hd_chon_sai", *da_nhap, sua("owner", cu2, tra_da_nhap="xyz"))
	th("g47c_nvbh_chua_chon", *da_nhap, sua("sales_a", cu2))
	th("g47d_nvbh_lam_lai", *da_nhap, sua("sales_a", cu2, tra_da_nhap="lam_lai"))
	th("g47e_nvbh_giu", *da_nhap, sua("sales_a", cu2, tra_da_nhap="giu"))
	th("g47f_ql_mat_quyen_lam_lai", *da_nhap, quyen("manager", "returns.approve", False), sua("manager", cu2, tra_da_nhap="lam_lai"))
	th("g47g_ql_mat_quyen_giu", *da_nhap, quyen("manager", "returns.approve", False), sua("manager", cu2, tra_da_nhap="giu"))
	lam_lai = [*da_nhap, sua("owner", cu2, tra_da_nhap="lam_lai", return_edits=[{"line_id": "@dong:VTD-P1:Lon", "quantity": 2}])]
	th("g48_lam_lai_sua_sl", *lam_lai)
	giu = [*lam_lai, hoan("owner", "date"), sua("owner", [(0, {"quantity": 3}), (1, {})], tra_da_nhap="giu",
		return_edits=[{"line_id": "@dong:VTD-P1:Lon", "quantity": 5}])]
	th("g49_giu_tang_sl_hd", *giu)
	th("g50a_huy_hd_da_nhap", *giu, huy("owner", "Khach doi y"))
	th("g50b_huy_nhap_hai_lan", *giu, huy_pt("owner", "Huy nhap tay"), huy_pt("owner", "Huy lan 2"))
	th("g50c_huy_hd_huy_ca_don", *giu, huy_pt("owner", "Huy nhap tay"), huy("owner", "Khach doi y"))
	th("g51_huy_hd_tu_sinh_va_tu_lap", _don_tra("g51", dong_tra=[dt()]), xuat("owner", [(0, {})]),
		lap("sales_a", {"customer_id": "@C1", "invoice_id": "@hd", "reason": "refused", "status": "draft"}, [dt()]), huy("owner", "Sai khach"))
	th("g52a_tu_lap_cho_xu_ly", *_hd_c1("g52a"), lap("owner", {"customer_id": "@C1", "invoice_id": "@hd", "order_id": "@don",
		"reason": "refused", "status": "submitted"}, [dt()]))
	th("g52b_tu_lap_nhap_qua_sua_huy", *_hd_c1("g52b"), lap("owner", {"customer_id": "@C1", "invoice_id": "@hd", "order_id": "@don",
		"reason": "refused", "status": "draft"}, [dt()]), sua("owner", [(0, {})]), huy("owner", "Sai khach"))
	g40 = [don("sales_a", L2, "g53"), xuat("owner", [(0, {}), doi_x()], return_adds=[dt(reason="expired"),
		dt("@P2", "Chai", 1, 5000, 0.1, doi=True)])]
	th("g53_sua_hd_them_tra_no_am", *g40, sua("owner", cu2, return_adds=[dt(dv="Thung", gia=228000)]),
		sua("owner", cu2, return_edits=[{"line_id": "@dong:VTD-P1:Lon", "quantity": 0}, {"line_id": "@doi:VTD-P2:Chai", "quantity": 0}]))
	th("g54a_xuat_lam_rong", _don_tra("g54a"), xuat("owner", [(0, {})], return_edits=[{"line_id": "@dong:VTD-P1:Lon", "quantity": 0},
		{"line_id": "@doi:VTD-P2:Chai", "quantity": 0}]), hoan("owner", "sale"))
	rong = [_don_tra("g54b", dong_tra=[dt()]), xuat("owner", [(0, {})]), sua("owner", [(0, {})],
		return_edits=[{"line_id": "@dong:VTD-P1:Lon", "quantity": 0}])]
	th("g54b_sua_hd_lam_rong", *rong, ghi("sales_a", "DELETE FROM returns WHERE id = :pt", {"bang": "returns", "hanh_dong": "delete",
		"loc": [PT_ID]}))
	th("g54c_huy_phieu_rong", *rong, huy_pt("owner", "Don phieu rong"))
	th("g54d_dung_lai_phieu_rong", *rong, sua("owner", [(0, {})], return_adds=[dt(sl=2)]))
	tu_lap_hd = [*_hd_c1("g55"), pos("owner", {"customer_id": "@C1", "invoice_id": "@hd", "complete": True, "zone": "sale", "lines": [dt()]}),
		sua("owner", [(0, {"quantity": 3})]), sua("owner", [(0, {})], tra_da_nhap="lam_lai")]
	th("g55a_tu_lap_qua_sua_hd", *tu_lap_hd, huy("owner", "x"))
	th("g55b_tu_lap_huy_roi_huy_hd", *tu_lap_hd, huy_pt("owner", "Huy tu lap"), huy("owner", "x"))
	ca_hai = [_don_tra("g55c", lines=[dong(sl=4, gia=9500)], dong_tra=[dt(sl=2)]), xuat("owner", [(0, {})], invoice_date="@hom_nay-1"),
		hoan("owner", "sale", "@hom_nay"), pos("owner", {"customer_id": "@C1", "invoice_id": "@hd", "complete": True, "zone": "date",
			"lines": [dt()]})]
	th("g55c_hai_phieu_da_nhap_chua_chon", *ca_hai, sua("owner", [(0, {})]))
	th("g55d_hai_phieu_lam_lai_roi_giu", *ca_hai, sua("owner", [(0, {})], tra_da_nhap="lam_lai"), sua("owner", [(0, {})], tra_da_nhap="giu"))
	th("g56a_nguoi_theo_hd_khi_xuat", _don_tra("g56a", dong_tra=[dt(), dt("@P2", "Hop", 1, 50000, 0.1, doi=True)]), doi_nv_don("sales_b"),
		xuat("owner", [(0, {}), doi_x("@P2", "Hop", 1, hs=10)]))
	gan_b = [_don_tra("g56b", dong_tra=[dt()]), xuat("owner", [(0, {})]), gan_hd("owner", "sales_b")]
	th("g56b_doi_nguoi_hd_lan_phieu", *gan_b, chon("hd"), gan("owner", "sales_a"))
	th("g56c_sua_hd_doi_ngay", *gan_b, sua("owner", [(0, {})], invoice_date="@hom_nay-5", tra_da_nhap="xyz"), hoan("owner", "sale"),
		sua("owner", [(0, {})], tra_da_nhap="giu", invoice_date="@hom_nay-3"))

	# ---------------------------------------------------------------- nhóm 7: bổ sung khi soát thiếu (G59–G65)
	r1 = pos("sales_a", {"customer_id": "@C2", "lines": [dt(sl=2, gia=9000)]})
	th("g59a_nvbh_huy_nhap", r1, huy_pt("sales_a", "lap nham"))
	th("g59b_chu_huy_nhap_con_dong", r1, huy_pt("owner", "lap nham"), huy_pt("owner", "lai"))
	th("g59c_huy_nhap_gan_hd", *_hd_c1("g59c"), pos("owner", {"customer_id": "@C1", "invoice_id": "@hd", "lines": [dt()]}),
		huy_pt("owner", "khach doi y"), hoan("owner"))
	th("g59d_sua_phieu_da_huy", r1, huy_pt("owner", "lap nham"), sua_pt("owner", {"notes": "da huy"}, "notes = 'da huy'"),
		pos("owner", {"return_id": "@pt", "customer_id": "@C2", "lines": [dt(gia=9000)]}))
	doc_lap60 = [pos("owner", {"customer_id": "@C2", "complete": True, "zone": "sale", "lines": [dt(dv="Thung", sl=2, gia=200000, thue=0.1)]})]
	ghi_lai = {"return_id": "@pt", "customer_id": "@C2", "complete": True, "zone": "sale", "lines": [dt(dv="Thung", gia=200000, thue=0.1)]}
	th("g60a_ql_mat_quyen_ghi_nhan_lai", *doc_lap60, quyen("manager", "returns.approve", False), pos("manager", ghi_lai))
	th("g60b_ql_mat_quyen_luu_nhap", *doc_lap60, quyen("manager", "returns.approve", False), pos("manager", {**ghi_lai, "complete": False}))
	th("g60c_chu_mat_quyen", quyen("owner", "returns.approve", False), pos("owner", {"customer_id": "@C2", "lines": [dt(gia=10000)]}),
		hoan("owner"))
	th("g60d_chu_mat_quyen_huy", quyen("owner", "returns.approve", False), pos("owner", {"customer_id": "@C2", "lines": [dt(gia=10000)]}),
		huy_pt("owner", "x"))
	r61 = [pos("sales_a", {"customer_id": "@C2", "lines": [dt(sl=2, gia=9000)]}),
		sua_pt("manager", {"sales_user_id": "@u:sales_b"}, "sales_user_id = @u:sales_b"),
		sua_pt("sales_a", {"notes": "x"}, "notes = 'x'"),
		ghi("sales_a", "DELETE FROM returns WHERE id = :pt", {"bang": "returns", "hanh_dong": "delete", "loc": [PT_ID]}),
		ghi("sales_a", "INSERT INTO return_lines (return_id, product_id, unit_name, quantity, unit_price, line_total) VALUES "
			"(:pt, @P1, 'Lon', 1, 9000, 0)", {"bang": "return_lines", "hanh_dong": "insert", "gia_tri": {"return_id": "@pt",
				"product_id": "@P1", "unit_name": "Lon", "quantity": 1, "unit_price": 9000}}),
		ghi("sales_a", "UPDATE return_lines SET quantity = 3 WHERE return_id = :pt AND quantity = 2", {"bang": "return_lines",
			"hanh_dong": "update", "gia_tri": {"quantity": 3}, "loc": [{"op": "eq", "cot": "return_id", "gt": "@pt"},
				{"op": "eq", "cot": "quantity", "gt": 2}]})]
	th("g61a_nguoi_lap_ghi_dong_phieu_nguoi_khac", *r61)
	th("g61b_nguoi_lap_xoa_het_dong", *r61, ghi("sales_a", "DELETE FROM return_lines WHERE return_id = :pt", {"bang": "return_lines",
		"hanh_dong": "delete", "loc": [{"op": "eq", "cot": "return_id", "gt": "@pt"}]}))
	r62 = [*_hd_c1("g62"), ghi("owner", f"INSERT INTO returns (org_id, customer_id, order_id, requested_by, status, reason) VALUES "
		f"('{ORG}', @C2, :don, @u:owner, 'draft', 'damaged')", {"bang": "returns", "hanh_dong": "insert", "gia_tri": {"customer_id": "@C2",
			"order_id": "@don", "status": "draft", "reason": "damaged"}}), chon("moi_nhat")]
	th("g62a_theo_don_khach_khac_hoan_thanh", *r62, hoan("owner"))
	th("g62b_theo_don_khach_khac_ghi_nhan", *r62, pos("owner", {"return_id": "@pt", "customer_id": "@C2", "complete": True, "zone": "sale",
		"lines": [dt("@P2", "Chai", 1, 5000, 0.1)]}))
	r63 = [pos("owner", {"customer_id": "@C2", "lines": [dt(gia=10000)]}), gan("owner", "sales_a"), hoan("owner", "sale")]
	th("g63a_nghi_viec_ghi_nhan_lai_giao_no", *r63, goi("owner", "cho_nhan_vien_nghi", "@u:sales_a", {"p_user_id": "@u:sales_a"}),
		pos("owner", {"return_id": "@pt", "customer_id": "@C2", "complete": True, "zone": "sale", "lines": [dt(sl=2, gia=10000)]}),
		goi("owner", "giao_cong_no_npp", "@C2, @u:sales_b", {"p_customer_id": "@C2", "p_user_id": "@u:sales_b"}))
	th("g63b_phieu_moi_dung_ten_nv_da_nghi", *_hd_c1("g63b"), goi("owner", "cho_nhan_vien_nghi", "@u:sales_a", {"p_user_id": "@u:sales_a"}),
		pos("owner", {"customer_id": "@C1", "complete": True, "zone": "sale", "lines": [dt()]}))
	th("g65a_chen_cot_chi_rpc", ghi("owner", f"INSERT INTO returns (org_id, customer_id, requested_by, status, reason, destination_zone, "
		"completed_by, completed_at, cancelled_at, cancel_reason, credited_at) VALUES ('" + ORG + "', @C2, @u:owner, 'draft', 'damaged', 'date', "
		"@u:owner, now(), now(), 'x', now())", {"bang": "returns", "hanh_dong": "insert", "gia_tri": {"customer_id": "@C2", "status": "draft",
			"reason": "damaged", "destination_zone": "date", "completed_by": "@u:owner", "completed_at": "2026-11-15T10:00:00+07:00",
			"cancelled_at": "2026-11-15T10:00:00+07:00", "cancel_reason": "x", "credited_at": "2026-11-15T10:00:00+07:00"}}),
		chon("moi_nhat"), sua_pt("owner", {"destination_zone": "sale", "cancel_reason": "y"}, "destination_zone = 'sale', cancel_reason = 'y'"),
		sua_pt("owner", {"completed_at": "2026-11-15T11:00:00+07:00"}, "completed_at = now() + interval '1 hour'"))
	th("g65b_vung_kho_sai", ghi("owner", f"INSERT INTO returns (org_id, customer_id, requested_by, status, destination_zone) VALUES "
		f"('{ORG}', @C2, @u:owner, 'draft', 'kho')", {"bang": "returns", "hanh_dong": "insert", "gia_tri": {"customer_id": "@C2",
			"status": "draft", "destination_zone": "kho"}}))
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
