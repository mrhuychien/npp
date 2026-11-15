#!/usr/bin/env python3
"""Dữ liệu vàng cho PHIẾU THU / TIỀN THU / NỢ ĐẦU KỲ (cash_receipts, cash_receipt_lines, payments, receivables của nppsale) — chạy CHÍNH hàm
+ trigger + RLS của nppsale ở Postgres tham chiếu (schema_full.sql): create_cash_receipt, void_cash_receipt; ghi thẳng `receivables` (nợ đầu
kỳ, dấu quá hạn — mig 214), `payments` (xác nhận), `cash_receipts` (ghi chú / xác nhận), `cash_receipt_lines`; cancel_invoice / reissue_invoice
có tiền thu (mig 125 / 184); phiếu trả làm nguồn dư có (save_pos_return / complete_return / cancel_return — mig 191 / 212);
giao_cong_no_npp / cho_nhan_vien_nghi; RPC đọc (receivables_by_customer / by_rep / summary, cash_received_total, bao_cao_cong_no).

Khuôn như tools/vang_phieu_tra.py (cùng nền dữ liệu, cùng cách chạy): mỗi tình huống một giao dịch con rồi lui; mỗi bước dưới đúng người
(request.jwt.claim.sub + ROLE authenticated); bước hỏng thì dừng và ghi mã + câu lỗi. Chỗ giữ trong tải trọng / điều kiện ghi thẳng:
	"@pth:<nhãn>"  id phiếu thu đã lập ở bước có nhãn ấy;      "@hd:<nhãn>"  id HĐ đã đặt nhãn (bước nhan_hd);
	"@no:hd" / "@no:hd:<nhãn>"  dòng công nợ của HĐ đang xét / HĐ có nhãn;  "@no:dk:<C1>"  dòng nợ đầu kỳ của khách;  "@no:pt"  dòng âm của
	phiếu trả đang xét; và mọi chỗ giữ của bộ phiếu trả ("@pt" "@hd" "@don" "@C1" "@u:x" "@hom_nay±n").
Ảnh chụp (ct) theo KHOÁ NGHIỆP VỤ của dòng công nợ (HD:<mã HĐ> | DK:<tên khách> | PT:<mã phiếu trả>): phiếu thu (theo thứ tự lập — trạng
thái, tiền, ngày, người, ghi chú, khoá gửi, dòng theo thứ tự chèn), khoản thu (`payments`), mọi dòng công nợ (số, đã thu, trạng thái, hạn,
người giữ, mốc về NPP, dấu bàn giao), HĐ (mã, trạng thái, tổng).

	python3 tools/vang_phieu_thu.py   → nppsale/tests/du_lieu/phieu_thu_mau.json
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vang_phieu_tra import _THAY, DAT_LAI_CO, _ref, _sql_ref, don, dt, ghi, goi, hoan, huy, huy_pt, pos, quyen, sua, xuat  # noqa: F401
from vang_phieu_tra import _lenh as _lenh_tra
from vang_tao_don import GIA, HANG, KHACH, NGUOI, NHOM, ORG, PSQL, _lit, ref, sql_nen, uid  # noqa: F401
from vang_xuat_hang import LO, _hom_nay, ngay_tuong_doi, sql_lo

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICH = os.path.join(GOC, "nppsale", "tests", "du_lieu", "phieu_thu_mau.json")

# Quyền vai của D1 (đặc tả §6.0): bộ gieo mặc định + quản lý lập / huỷ phiếu thu (= NPP có trước mig 215; bản Frappe gieo sẵn — Q7 / Q4)
QUYEN_VAI = [("manager", "orders", "approve"), ("manager", "orders", "update"), ("manager", "returns", "approve"),
	("manager", "inventory", "approve"), ("manager", "receivables", "create"), ("manager", "receivables", "update"),
	("sales", "orders", "update"), ("accountant", "receivables", "create"), ("accountant", "receivables", "update")]


# ------------------------------------------------------------------------------------------------ bước mới
def thu(nguoi, p, nhan=None):
	"""create_cash_receipt(p) — nhan: tên đặt cho phiếu vừa lập (dùng ở "@pth:<nhan>"). Trả về: nhãn của phiếu nhận được (phiếu cũ khi
	gửi lại cùng client_key)."""
	return {"buoc": "thu", "nguoi": nguoi, "p": p, "nhan": nhan}


def huy_thu(nguoi, nhan, ly_do="Thu nham"):
	"""void_cash_receipt(id phiếu có nhãn — "LA" = id lạ, None = NULL, p_reason)."""
	return {"buoc": "huy_thu", "nguoi": nguoi, "nhan": nhan, "ly_do": ly_do}


def dk(nguoi, khach, so_tien, han=None, nv=None, status="open", note=None, **them):
	"""Ghi thẳng `receivables.insert` nợ đầu kỳ (màn /finance/opening-balances): như giao diện gửi."""
	g = {"org_id": ORG, "customer_id": khach, "amount": so_tien, "paid": 0, "due_date": han, "status": status, "opening_balance": True,
		"note": note, **({"sales_user_id": nv} if nv else {}), **them}
	return {"buoc": "dk", "nguoi": nguoi, "g": g}


def ghi_no(nguoi, khoa_no, hanh_dong, gia_tri=None):
	"""Ghi thẳng `receivables` update / delete trên MỘT dòng theo khoá chỗ giữ ("@no:dk:C1", "@no:hd"…)."""
	return {"buoc": "ghi_no", "nguoi": nguoi, "no": khoa_no, "hd_": hanh_dong, "g": gia_tri}


def ghi_bang(nguoi, bang, hanh_dong, gia_tri, cot_loc, gt_loc):
	"""Ghi thẳng bảng tiền (cash_receipts / cash_receipt_lines / payments / cash_collections) — lọc `cot_loc = gt_loc` (gt_loc có chỗ giữ;
	"@dong_thu:<nhãn>" = mọi dòng của phiếu, "@khoan:<nhãn>" = mọi khoản thu (payment_id) của phiếu)."""
	return {"buoc": "ghi_bang", "nguoi": nguoi, "bang": bang, "hd_": hanh_dong, "g": gia_tri, "cot": cot_loc, "gt": gt_loc}


def doc(nguoi, ten, **ts):
	"""RPC đọc dưới đúng người (RLS người gọi) — kết quả vào tra_ve."""
	return {"buoc": "doc", "nguoi": nguoi, "ten": ten, "ts": ts}


def nhan_hd(ten):
	return {"buoc": "nhan_hd", "nguoi": "owner", "ten": ten}


def chon_hd(ten):
	return {"buoc": "chon_hd", "nguoi": "owner", "ten": ten}


def giao_no(nguoi, khach, nv):
	return {"buoc": "giao_no", "nguoi": nguoi, "khach": khach, "nv": nv}


def nghi(nguoi, nv):
	return {"buoc": "nghi", "nguoi": nguoi, "nv": nv}


def quyen_vai(vai, mo_dun, hanh_dong, duoc):
	return {"buoc": "quyen_vai", "nguoi": "owner", "vai": vai, "mo_dun": mo_dun, "hanh_dong": hanh_dong, "duoc": duoc}


# ------------------------------------------------------------------------------------------------ SQL
CHO_THU = ("@pth:", "@no:", "@hd:", "@dong_thu:", "@khoan:")


def _ref_thu(v):
	"""_ref của bộ phiếu trả + giữ chỗ của phiếu thu; "@no:dk:C1" → "@no:dk:<uuid khách>" (hàm thay của Postgres tra theo id); "@hom_nay±n"
	giữ nguyên (đổi ra ngày ở _v_lit / _p — _ref của bộ phiếu trả coi mọi "@x" là khoá nền)."""
	if isinstance(v, str) and v.startswith("@hom_nay"):
		return v
	if isinstance(v, str) and v.startswith(CHO_THU):
		if v.startswith("@no:dk:"):
			return "@no:dk:" + ref("@" + v[len("@no:dk:"):])
		return v
	if isinstance(v, dict):
		return {a: _ref_thu(b) for a, b in v.items()}
	if isinstance(v, list):
		return [_ref_thu(x) for x in v]
	return _ref(v)


def _p(v) -> str:
	t = _lit(json.dumps(_ref_thu(ngay_tuong_doi(v)), ensure_ascii=False))
	return f"public._vang_thay_thu({_THAY.format(x=t)}, v_hd, v_pt, v_nhan)::jsonb"


def _gt(v) -> str:
	"""Một giá trị (chỗ giữ) → biểu thức SQL text."""
	return f"(public._vang_thay_thu({_lit(json.dumps(_ref_thu(v)))}, v_hd, v_pt, v_nhan)::jsonb #>> '{{}}')"


def _lenh(b: dict) -> str:
	k = b["buoc"]
	if k == "thu":
		nhan = _lit(b["nhan"]) if b.get("nhan") else "NULL"
		return (f"SELECT public.create_cash_receipt({_p(b['p'])}) INTO v_id; "
			f"v_ten := COALESCE((SELECT e.key FROM jsonb_each_text(v_nhan) e WHERE e.value = v_id::text LIMIT 1), {nhan}, 'moi'); "
			f"IF {nhan} IS NOT NULL AND NOT v_nhan ? {nhan} THEN v_nhan := v_nhan || jsonb_build_object({nhan}, v_id::text); END IF; "
			"v_ds := v_ds || jsonb_build_array(jsonb_build_object('phieu', v_ten));")
	if k == "huy_thu":
		if b["nhan"] is None:
			ma = "NULL::uuid"
		elif b["nhan"] == "LA":
			ma = f"'{uid('phieu-thu-la')}'::uuid"
		else:
			ma = f"(v_nhan->>{_lit(b['nhan'])})::uuid"
		return f"PERFORM public.void_cash_receipt({ma}, {'NULL' if b['ly_do'] is None else _lit(b['ly_do'])});"
	if k == "dk":
		return _dk_sql(_ref_thu(b["g"]))
	if k == "pos":  # tải trọng có "@hd:<nhãn>" — thay bằng hàm của bộ phiếu thu (bộ phiếu trả chỉ biết "@pt" "@hd" "@don")
		return f"SELECT public.save_pos_return({_p(b['p'])}) INTO v_pt;"
	if k == "ghi_no":
		dieu = f"id = %%THAY:{b['no']}%%::uuid"  # giá trị chỗ giữ tính NGOÀI câu EXECUTE (biến plpgsql không thấy trong câu động)
		if b["hd_"] == "delete":
			cau = f"DELETE FROM receivables WHERE {dieu}"
		else:
			cau = f"UPDATE receivables SET {_set_sql('receivables', b['g'])} WHERE {dieu}"
		return _ghi_dong_sql(cau)
	if k == "ghi_bang":
		bang = b["bang"]
		gt = b["gt"]
		if isinstance(gt, str) and gt.startswith("@dong_thu:"):
			dieu = f"receipt_id = %%THAY:@pth:{gt[len('@dong_thu:'):]}%%::uuid"
		elif isinstance(gt, str) and gt.startswith("@khoan:"):
			dieu = f"id IN (SELECT payment_id FROM cash_receipt_lines WHERE receipt_id = %%THAY:@pth:{gt[len('@khoan:'):]}%%::uuid)"
		elif isinstance(gt, str) and gt.startswith(CHO_THU):
			dieu = f"{b['cot']} = %%THAY:{gt}%%" + ("::uuid" if b["cot"].endswith("id") else "")
		else:
			dieu = f"{b['cot']} = {_v_lit(_ref_thu(gt))}"
		if b["hd_"] == "insert":
			g = _ref_thu(b["g"])
			cau = f"INSERT INTO {bang} ({', '.join(g)}) VALUES ({', '.join('NULL' if v is None else _v_lit(v) for v in g.values())})"
		elif b["hd_"] == "delete":
			cau = f"DELETE FROM {bang} WHERE {dieu}"
		else:
			cau = f"UPDATE {bang} SET {_set_sql(bang, b['g'])} WHERE {dieu}"
		return _ghi_dong_sql(cau)
	if k == "doc":
		ten = b["ten"]
		ts = b["ts"]
		if ten in ("receivables_by_customer", "receivables_by_rep", "receivables_summary"):
			q = f"SELECT COALESCE(jsonb_agg(to_jsonb(r)), '[]'::jsonb) FROM public.{ten}() r"
		elif ten == "cash_received_total":
			q = (f"SELECT to_jsonb(public.cash_received_total({_ngay_sql(ts.get('p_from'))}, {_ngay_sql(ts.get('p_to'))}))")
		elif ten == "bao_cao_cong_no":
			q = f"SELECT public.bao_cao_cong_no({_ngay_sql(ts.get('p_tu_thu'))}, {_ngay_sql(ts.get('p_tu_90'))})"
		else:
			raise ValueError(f"RPC đọc lạ: {ten}")
		return f"{q} INTO v_tra; v_ds := v_ds || jsonb_build_array(jsonb_build_object('doc', {_lit(ten)}, 'kq', v_tra));"
	if k == "nhan_hd":
		return f"v_nhan := v_nhan || jsonb_build_object({_lit(b['ten'])}, v_hd::text);"
	if k == "chon_hd":
		return f"v_hd := (v_nhan->>{_lit(b['ten'])})::uuid;"
	if k == "giao_no":
		return (f"SELECT to_jsonb(public.giao_cong_no_npp('{ref(b['khach'])}', '{uid('u:' + b['nv'])}')) INTO v_tra; "
			"v_ds := v_ds || jsonb_build_array(jsonb_build_object('giao_no', v_tra));")
	if k == "nghi":
		return (f"SELECT to_jsonb(public.cho_nhan_vien_nghi('{uid('u:' + b['nv'])}')) INTO v_tra; "
			"v_ds := v_ds || jsonb_build_array(jsonb_build_object('nghi', v_tra));")
	if k == "quyen_vai":
		return (f"EXECUTE 'RESET ROLE'; INSERT INTO role_permissions (org_id, role, module, action, allowed) VALUES ('{ORG}', "
			f"{_lit(b['vai'])}, {_lit(b['mo_dun'])}, {_lit(b['hanh_dong'])}, {str(b['duoc']).lower()}) ON CONFLICT (org_id, role, module, action) "
			"DO UPDATE SET allowed = EXCLUDED.allowed;")
	return _lenh_tra(b)


def _set_sql(bang: str, g: dict) -> str:
	ra = []
	for c, v in _ref_thu(g).items():
		ra.append(f"{c} = " + ("NULL" if v is None else _v_lit(v)))
	return ", ".join(ra)


def _v_lit(v) -> str:
	if isinstance(v, str) and v.startswith("@hom_nay"):
		return _lit(ngay_tuong_doi(v))
	if isinstance(v, bool):
		return str(v).lower()
	if isinstance(v, (int, float)):
		return repr(v)
	if isinstance(v, str) and v.startswith(("@pth:", "@no:", "@hd:")):
		return "%%THAY:" + v + "%%"
	return "'" + str(v).replace("'", "''") + "'"


def _ghi_dong_sql(cau: str) -> str:
	"""Câu ghi thẳng (dưới RLS người gọi) — "%%THAY:@…%%" → giá trị chỗ giữ lúc chạy; ghi số dòng chạm vào tra_ve."""
	import re

	phan = re.split(r"%%THAY:(@[^%]+)%%", cau)
	bieu = []
	for i, x in enumerate(phan):
		if i % 2 == 0:
			bieu.append(_lit(x))
		else:
			bieu.append(f"quote_nullable({_gt(x)})")
	return (f"EXECUTE {' || '.join(bieu)}; GET DIAGNOSTICS v_n = ROW_COUNT; "
		"v_ds := v_ds || jsonb_build_array(jsonb_build_object('so_dong', v_n));")


def _dk_sql(g: dict) -> str:
	cot = ", ".join(g)
	gt = ", ".join("NULL" if v is None else _v_lit(ngay_tuong_doi(v) if isinstance(v, str) and v.startswith("@hom_nay") else v) for v in g.values())
	return _ghi_dong_sql(f"INSERT INTO receivables ({cot}) VALUES ({gt})")


def _ngay_sql(v) -> str:
	return "NULL" if v is None else f"{_lit(ngay_tuong_doi(v))}::date"


CO_PHIEN = DAT_LAI_CO


def sql_tinh_huong(t: dict) -> str:
	khoi = []
	for b in t["buoc"]:
		u = uid("u:" + b["nguoi"])
		khoi.append(f"""
  IF NOT v_dung THEN
    BEGIN
      EXECUTE 'SET CONSTRAINTS ALL DEFERRED';
      {CO_PHIEN}
      PERFORM set_config('request.jwt.claim.sub', {_lit(u)}, true);
      EXECUTE 'SET LOCAL ROLE authenticated';
      {_lenh(b)}
      EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';
      EXECUTE 'RESET ROLE';
      EXECUTE 'SET LOCAL session_replication_role = replica';
      UPDATE returns SET created_at = clock_timestamp() WHERE org_id = '{ORG}' AND created_at = now();
      UPDATE sales_orders SET created_at = clock_timestamp() WHERE org_id = '{ORG}' AND created_at = now();
      UPDATE cash_receipts SET created_at = clock_timestamp(), received_at = CASE WHEN received_at = now() THEN clock_timestamp()
        ELSE received_at END WHERE org_id = '{ORG}' AND created_at = now();
      UPDATE receivables SET created_at = clock_timestamp() WHERE org_id = '{ORG}' AND created_at = now();
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
  v_dung boolean := false; v_n int; v_id uuid; v_ten text; v_nhan jsonb := '{{}}'::jsonb;
  v_ct jsonb;
BEGIN
  BEGIN
    UPDATE organizations SET allow_oversell = {str(t.get('cho_ban_vuot_ton', False)).lower()} WHERE id = '{ORG}';
    {''.join(khoi)}
    SELECT public._vang_anh_chup_thu() INTO v_ct;
    v_ct := v_ct || jsonb_build_object('tra_ve', v_ds, 'nhan', v_nhan);
    RAISE EXCEPTION USING ERRCODE = 'ZZ999';
  EXCEPTION WHEN SQLSTATE 'ZZ999' THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  INSERT INTO _vang_kq VALUES ({_lit(t['ma'])}, v_kq, v_ct);
END $c$;
"""


def sql_ham_phu() -> str:
	"""Hàm phụ (tạo trong giao dịch của bộ sinh, lui cùng ROLLBACK cuối): thay chỗ giữ của phiếu thu + ảnh chụp theo khoá nghiệp vụ."""
	from vang_phieu_tra import sql_ham_phu as tra

	q = [tra()]
	q.append("SELECT public._gieo_quyen_mac_dinh('" + ORG + "');")
	for vai, mo, hd in QUYEN_VAI:
		q.append(f"INSERT INTO role_permissions (org_id, role, module, action, allowed) VALUES ('{ORG}', '{vai}', '{mo}', '{hd}', true) "
			"ON CONFLICT (org_id, role, module, action) DO UPDATE SET allowed = true;")
	# thứ tự chèn dòng phiếu thu (ctid đổi khi huỷ phiếu cập nhật payment_id)
	q.append("ALTER TABLE cash_receipt_lines ADD COLUMN _thu_tu bigserial;")
	q.append(f"""
CREATE OR REPLACE FUNCTION public._vang_khoa_no(p_id uuid) RETURNS text LANGUAGE sql SECURITY DEFINER AS $f$
  SELECT CASE WHEN r.invoice_id IS NOT NULL THEN 'HD:' || (SELECT si.invoice_code FROM sales_invoices si WHERE si.id = r.invoice_id)
    WHEN r.opening_balance THEN 'DK:' || (SELECT c.store_name FROM customers c WHERE c.id = r.customer_id)
    WHEN r.return_id IS NOT NULL THEN 'PT:' || (SELECT x.return_code FROM returns x WHERE x.id = r.return_id)
    ELSE 'KHAC' END FROM receivables r WHERE r.id = p_id
$f$;
GRANT EXECUTE ON FUNCTION public._vang_khoa_no(uuid) TO authenticated;

CREATE OR REPLACE FUNCTION public._vang_thay_thu(p text, p_hd uuid, p_pt uuid, p_nhan jsonb) RETURNS text LANGUAGE plpgsql SECURITY DEFINER AS $f$
DECLARE v text := p; m text[]; k text; gt text;
BEGIN
  FOR m IN SELECT regexp_matches(p, '"(@(?:pth|hd|no|dong_thu|khoan):[^"]*|@no:hd|@no:pt)"', 'g') LOOP
    k := m[1];
    gt := CASE
      WHEN k LIKE '@pth:%' THEN p_nhan->>substr(k, 6)
      WHEN k LIKE '@hd:%' THEN p_nhan->>substr(k, 5)
      WHEN k = '@no:hd' THEN (SELECT r.id::text FROM receivables r WHERE r.invoice_id = p_hd)
      WHEN k LIKE '@no:hd:%' THEN (SELECT r.id::text FROM receivables r WHERE r.invoice_id = (p_nhan->>substr(k, 8))::uuid)
      WHEN k LIKE '@no:dk:%' THEN (SELECT r.id::text FROM receivables r WHERE r.opening_balance AND r.customer_id = substr(k, 8)::uuid)
      WHEN k = '@no:pt' THEN (SELECT r.id::text FROM receivables r WHERE r.return_id = p_pt)
      ELSE NULL END;
    v := replace(v, '"' || k || '"', COALESCE(to_jsonb(gt)::text, 'null'));
  END LOOP;
  RETURN v;
END $f$;
GRANT EXECUTE ON FUNCTION public._vang_thay_thu(text, uuid, uuid, jsonb) TO authenticated;

CREATE OR REPLACE FUNCTION public._vang_anh_chup_thu() RETURNS jsonb LANGUAGE sql AS $f$
  SELECT jsonb_build_object(
    'phieu_thu', (SELECT jsonb_agg(jsonb_build_object(
        'ma_dang', CASE WHEN cr.receipt_code ~ '^PT-[0-9]{{6}}-[0-9]{{4}}$' THEN 'PT-NGAY-SO' ELSE cr.receipt_code END,
        'ngay_ma', substr(cr.receipt_code, 4, 6) = to_char(now() AT TIME ZONE 'Asia/Ho_Chi_Minh', 'YYMMDD'),
        'ngay', cr.receipt_date, 'nguon', cr.source_type, 'status', cr.status, 'tien', cr.submitted_amount, 'ky_vong', cr.expected_amount,
        'thu_boi', (SELECT u.full_name FROM users u WHERE u.id = cr.collected_by),
        'nhan_boi', (SELECT u.full_name FROM users u WHERE u.id = cr.received_by), 'co_nhan_luc', cr.received_at IS NOT NULL,
        'lap_boi', (SELECT u.full_name FROM users u WHERE u.id = cr.created_by),
        'huy_boi', (SELECT u.full_name FROM users u WHERE u.id = cr.voided_by), 'co_huy_luc', cr.voided_at IS NOT NULL,
        'ly_do_huy', cr.void_reason, 'ghi_chu', cr.notes, 'khoa_gui', cr.client_key,
        'dong', (SELECT jsonb_agg(jsonb_build_object('loai', l.kind, 'tien', l.amount, 'no', public._vang_khoa_no(l.receivable_id),
            'hd', (SELECT si.invoice_code FROM sales_invoices si WHERE si.id = l.invoice_id), 'co_don', l.order_id IS NOT NULL,
            'pt', (SELECT x.return_code FROM returns x WHERE x.id = l.return_id), 'co_khoan', l.payment_id IS NOT NULL,
            'co_no', l.receivable_id IS NOT NULL) ORDER BY l._thu_tu) FROM cash_receipt_lines l WHERE l.receipt_id = cr.id)
      ) ORDER BY cr.created_at, cr.id) FROM cash_receipts cr WHERE cr.org_id = '{ORG}'),
    'khoan', (SELECT jsonb_agg(jsonb_build_object('no', public._vang_khoa_no(p.receivable_id), 'tien', p.amount, 'cach', p.method,
        'thu_boi', (SELECT u.full_name FROM users u WHERE u.id = p.collected_by), 'xac_nhan', p.verified_by IS NOT NULL)
      ORDER BY public._vang_khoa_no(p.receivable_id), p.amount, p.method) FROM payments p
      JOIN receivables r ON r.id = p.receivable_id WHERE r.org_id = '{ORG}'),
    'cong_no', (SELECT jsonb_agg(jsonb_build_object('no', public._vang_khoa_no(c.id), 'so_tien', c.amount, 'da_thu', c.paid,
        'status', c.status, 'han', c.due_date, 'nv', (SELECT u.full_name FROM users u WHERE u.id = c.sales_user_id),
        've_npp', c.ve_npp_luc IS NOT NULL, 'giao_tu', (SELECT u.full_name FROM users u WHERE u.id = c.giao_tu_nv), 'ghi_chu', c.note)
      ORDER BY public._vang_khoa_no(c.id), c.amount) FROM receivables c WHERE c.org_id = '{ORG}'),
    'hd', (SELECT jsonb_agg(jsonb_build_object('ma', si.invoice_code, 'status', si.status, 'total', si.total, 'han', si.due_date)
      ORDER BY si.invoice_seq, si.reissue_no) FROM sales_invoices si WHERE si.org_id = '{ORG}'),
    'hom_nay', (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date)
$f$;
""")
	return "\n".join(q)


# ------------------------------------------------------------------------------------------------ tình huống (đặc tả phiếu thu §6)
P1 = {"product_id": "@P1", "unit_name": "Lon", "unit_price": 10000, "line_discount": 0, "conversion_factor": 1, "vat_rate": 0}


def _don_hd(ma, sl, *, nguoi="sales_a", khach="@C1", dk_tt="COD", ngay=None):
	"""Đơn P1 × sl (10.000 / lon, VAT 0) + Xuất hàng (owner) — HĐ = sl × 10.000, hạn = ngày + NETn."""
	lines = [{**P1, "quantity": sl, "line_total": sl * 10000}]
	b = [don(nguoi, lines, ma, khach=khach, payment_terms=dk_tt), xuat("owner", [(0, {})], **({"invoice_date": ngay} if ngay else {}))]
	return b


def tinh_huong() -> list[dict]:
	T: list[dict] = []

	def phang(b):
		return [y for x in b for y in phang(x)] if isinstance(b, list) else [b]

	def them(ma, *buoc, **o):
		T.append({"ma": ma, "buoc": phang(list(buoc)), **o})

	# ---- B. Nợ đầu kỳ (cổng receivables)
	them("b01_dk_nhap", dk("accountant", "@C1", 5000000, han="@hom_nay-45", nv="@u:sales_a", note="No cu"))
	them("b02_dk_trung", dk("accountant", "@C1", 5000000), dk("accountant", "@C1", 100))
	them("b03_dk_quyen", dk("manager", "@C2", 100000), )
	them("b03b_dk_nvbh", dk("sales_a", "@C2", 100000))
	them("b04a_dk_khoa_paid", dk("owner", "@C1", 100000, paid=50))
	them("b04b_dk_khoa_khong_dau_ky", dk("accountant", "@C1", 100000, opening_balance=False))
	them("b05_dk_so_0", dk("accountant", "@C1", 0))
	them("b05b_dk_so_le", dk("accountant", "@C1", 100000.5))
	them("b06_dk_sua_chua_thu", dk("accountant", "@C1", 6000000, han="@hom_nay-45"),
		ghi_no("accountant", "@no:dk:C1", "update", {"amount": 6500000, "due_date": "@hom_nay-30", "note": "Sua"}))
	them("b07_dk_sua_da_thu", dk("accountant", "@C1", 6000000),
		thu("accountant", {"customer_id": "@C1", "method": "cash", "lines": [{"receivable_id": "@no:dk:C1", "amount": 2000000}]}, "R1"),
		ghi_no("accountant", "@no:dk:C1", "update", {"amount": 6500000}))
	them("b08_dk_khoa_sua_paid", dk("accountant", "@C1", 6000000), ghi_no("accountant", "@no:dk:C1", "update", {"paid": 1}))
	them("b08b_dk_khoa_sua_khach", dk("accountant", "@C1", 6000000), ghi_no("accountant", "@no:dk:C1", "update", {"customer_id": "@C2"}))
	them("b08c_dk_sua_khong_quyen", dk("accountant", "@C1", 6000000), ghi_no("manager", "@no:dk:C1", "update", {"note": "x"}))
	them("b09_dk_xoa_chua_thu", dk("accountant", "@C2", 800000), ghi_no("accountant", "@no:dk:C2", "delete"))
	them("b10_dk_xoa_da_thu", dk("accountant", "@C2", 800000),
		thu("accountant", {"customer_id": "@C2", "lines": [{"receivable_id": "@no:dk:C2", "amount": 100000}]}, "R1"),
		ghi_no("accountant", "@no:dk:C2", "delete"))
	them("b11_dk_xoa_sau_huy_phieu", dk("accountant", "@C2", 800000),
		thu("accountant", {"customer_id": "@C2", "lines": [{"receivable_id": "@no:dk:C2", "amount": 800000}]}, "R1"),
		huy_thu("accountant", "R1"), ghi_no("accountant", "@no:dk:C2", "delete"))
	them("b12_qua_han_tay", dk("accountant", "@C1", 6000000, han="@hom_nay-45"),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:dk:C1", "amount": 2000000}]}, "R1"),
		ghi_no("accountant", "@no:dk:C1", "update", {"status": "overdue"}),
		ghi_no("owner", "@no:dk:C1", "update", {"status": "open"}))
	them("b12b_qua_han_dong_du", dk("accountant", "@C1", 100000),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:dk:C1", "amount": 100000}]}, "R1"),
		ghi_no("accountant", "@no:dk:C1", "update", {"status": "overdue"}))
	them("b13_dk_nv_nghi_giao_no", dk("owner", "@C2", 700000, nv="@u:sales_nghi"), giao_no("owner", "@C2", "sales_b"))

	# ---- C. Lập phiếu thu
	them("c01_thu_du", _don_hd("c01", 10), thu("accountant", {"customer_id": "@C1", "method": "cash",
		"lines": [{"receivable_id": "@no:hd", "amount": 100000}]}, "R1"))
	them("c02_thu_thieu_roi_not", _don_hd("c02", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 40000}]}, "R1"),
		thu("accountant", {"customer_id": "@C1", "method": "transfer", "lines": [{"receivable_id": "@no:hd", "amount": 60000}]}, "R2"))
	them("c03_nhieu_khoan_theo_han", _don_hd("c03a", 10, dk_tt="NET30"), nhan_hd("T1"), _don_hd("c03b", 5, dk_tt="NET7"), nhan_hd("T2"),
		dk("accountant", "@C1", 200000, han="@hom_nay-60"),
		thu("accountant", {"customer_id": "@C1", "use_credit": 0, "lines": [{"receivable_id": "@no:hd:T2", "amount": 20000},
			{"receivable_id": "@no:dk:C1", "amount": 200000}, {"receivable_id": "@no:hd:T1", "amount": 30000}]}, "R1"))
	them("c04a_thu_vuot", _don_hd("c04", 10), thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 100001}]}))
	them("c04b_hai_dong_cung_khoan_vuot", _don_hd("c04b", 10), thu("accountant", {"customer_id": "@C1", "lines": [
		{"receivable_id": "@no:hd", "amount": 60000}, {"receivable_id": "@no:hd", "amount": 50000}]}))
	them("c04c_hai_dong_cung_khoan", _don_hd("c04c", 10), thu("accountant", {"customer_id": "@C1", "lines": [
		{"receivable_id": "@no:hd", "amount": 60000}, {"receivable_id": "@no:hd", "amount": 40000}]}, "R1"))
	them("c05a_dong_0", _don_hd("c05a", 10), thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 0}]}))
	them("c05b_dong_am", _don_hd("c05b", 10), dk("accountant", "@C1", 50000), thu("accountant", {"customer_id": "@C1", "lines": [
		{"receivable_id": "@no:hd", "amount": 50000}, {"receivable_id": "@no:dk:C1", "amount": -10000}]}))
	them("c05c_dong_le", _don_hd("c05c", 10), thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10.5}]}))
	them("c05d_rong", thu("accountant", {"customer_id": "@C1", "lines": []}))
	them("c06a_sai_khach", _don_hd("c06a", 10, khach="@C2"), thu("accountant", {"customer_id": "@C1", "lines": [
		{"receivable_id": "@no:hd", "amount": 10000}]}))
	them("c06b_thieu_khach", _don_hd("c06b", 10), thu("accountant", {"lines": [{"receivable_id": "@no:hd", "amount": 10000}]}))
	them("c06c_method_la", _don_hd("c06c", 10), thu("accountant", {"customer_id": "@C1", "method": "card", "lines": [
		{"receivable_id": "@no:hd", "amount": 10000}]}))
	them("c06d_method_rong", _don_hd("c06d", 10), thu("accountant", {"customer_id": "@C1", "method": "", "lines": [
		{"receivable_id": "@no:hd", "amount": 10000}]}))
	them("c06e_ngay_sai", _don_hd("c06e", 10), thu("accountant", {"customer_id": "@C1", "receipt_date": "", "lines": [
		{"receivable_id": "@no:hd", "amount": 10000}]}))
	them("c06f_du_co_sai_kieu", _don_hd("c06f", 10), thu("accountant", {"customer_id": "@C1", "use_credit": "abc", "lines": [
		{"receivable_id": "@no:hd", "amount": 10000}]}))
	them("c06g_du_co_le", _don_hd("c06g", 10), thu("accountant", {"customer_id": "@C1", "use_credit": 1.5, "lines": [
		{"receivable_id": "@no:hd", "amount": 10000}]}))
	them("c07_client_key", _don_hd("c07", 10),
		thu("accountant", {"customer_id": "@C1", "client_key": "K-ABC", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"),
		thu("accountant", {"customer_id": "@C2", "client_key": "K-ABC", "lines": []}, "R2"),
		huy_thu("accountant", "R1"),
		thu("accountant", {"customer_id": "@C1", "client_key": "K-ABC", "lines": [{"receivable_id": "@no:hd", "amount": 20000}]}, "R3"),
		thu("accountant", {"customer_id": "@C1", "client_key": "", "lines": [{"receivable_id": "@no:hd", "amount": 5000}]}, "R4"))
	them("c08_ngay_tay_ghi_chu", _don_hd("c08", 10), thu("accountant", {"customer_id": "@C1", "receipt_date": "@hom_nay-13",
		"notes": "Thu ho chi Lan", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"))
	for nguoi in ("owner", "manager", "sales_a", "warehouse"):
		them(f"c09_quyen_{nguoi}", _don_hd(f"c09{nguoi}", 10), thu(nguoi, {"customer_id": "@C1", "lines": [
			{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"))
	them("c10_nvbh_quyen_rieng", _don_hd("c10", 10, nguoi="sales_b"), quyen("sales_a", "receivables.create", True),
		thu("sales_a", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"))

	# ---- D. Dư có
	tra_c1 = {"customer_id": "@C1", "reason": "damaged", "zone": "sale", "lines": [dt(sl=2, gia=9500, thue=0.08)], "complete": True}
	them("d01_du_co_phieu_tra", _don_hd("d01", 10), pos("manager", tra_c1),
		thu("accountant", {"customer_id": "@C1", "use_credit": 20520, "lines": [{"receivable_id": "@no:hd", "amount": 100000}]}, "R1"))
	them("d02_chi_dung_du_co", _don_hd("d02", 10), pos("manager", tra_c1),
		thu("accountant", {"customer_id": "@C1", "use_credit": 20520, "lines": [{"receivable_id": "@no:hd", "amount": 20520}]}, "R1"))
	them("d03_rut_qua_du_co", _don_hd("d03", 10), pos("manager", tra_c1),
		thu("accountant", {"customer_id": "@C1", "use_credit": 30000, "lines": [{"receivable_id": "@no:hd", "amount": 100000}]}))
	them("d04_du_co_vuot_phan_tra", _don_hd("d04", 10), pos("manager", tra_c1),
		thu("accountant", {"customer_id": "@C1", "use_credit": 20520, "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}))
	them("d05_du_co_tu_hd_tra_vuot", _don_hd("d05a", 1), nhan_hd("T1"), _don_hd("d05b", 10), nhan_hd("T2"),
		pos("manager", {**tra_c1, "invoice_id": "@hd:T1"}),
		thu("accountant", {"customer_id": "@C1", "use_credit": 10520, "lines": [{"receivable_id": "@no:hd:T2", "amount": 50000}]}, "R1"))
	them("d06_credits_cu", _don_hd("d06", 10), pos("manager", tra_c1),
		thu("accountant", {"customer_id": "@C1", "credits": [{"return_id": "@pt"}], "lines": [{"receivable_id": "@no:hd", "amount": 50000}]}))

	# ---- E. Huỷ phiếu thu
	them("e01_huy_phieu_dung_du_co", _don_hd("e01", 10), pos("manager", tra_c1),
		thu("accountant", {"customer_id": "@C1", "use_credit": 20520, "lines": [{"receivable_id": "@no:hd", "amount": 100000}]}, "R1"),
		huy_thu("accountant", "R1"))
	them("e02_huy_qua_han", _don_hd("e02", 10, dk_tt="NET7", ngay="@hom_nay-30"),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 40000}]}, "R1"), huy_thu("accountant", "R1"))
	them("e03_loi_theo_thu_tu", _don_hd("e03", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"),
		huy_thu("sales_a", "LA"))
	them("e03b_khong_quyen", _don_hd("e03b", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"), huy_thu("sales_a", "R1"))
	them("e03c_khong_ly_do", _don_hd("e03c", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"), huy_thu("accountant", "R1", "  "))
	them("e03d_ly_do_xuong_dong", _don_hd("e03d", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"), huy_thu("accountant", "R1", "\n"))
	them("e03e_huy_hai_lan", _don_hd("e03e", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"),
		huy_thu("accountant", "R1"), huy_thu("accountant", "R1"))
	them("e04_huy_phieu_tra_nguon_da_rut", _don_hd("e04", 10), pos("manager", tra_c1),
		thu("accountant", {"customer_id": "@C1", "use_credit": 20520, "lines": [{"receivable_id": "@no:hd", "amount": 100000}]}, "R1"),
		huy_pt("manager"))

	# ---- F. Ghi thẳng / xác nhận
	them("f01_xac_nhan_khoan", _don_hd("f01", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"),
		ghi_bang("accountant", "payments", "update", {"verified_by": "@u:accountant", "verified_at": "2026-11-15T10:00:00+07:00"}, "id",
			"@khoan:R1"),
		ghi_bang("manager", "payments", "update", {"verified_by": "@u:manager"}, "id", "@khoan:R1"),
		ghi_bang("accountant", "payments", "update", {"amount": 1}, "id", "@khoan:R1"))
	them("f02_ghi_thang_phieu", _don_hd("f02", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"),
		ghi_bang("accountant", "cash_receipts", "update", {"notes": "ghi chu moi"}, "id", "@pth:R1"),
		ghi_bang("sales_a", "cash_receipts", "update", {"notes": "x"}, "id", "@pth:R1"),
		ghi_bang("accountant", "cash_receipts", "delete", None, "id", "@pth:R1"),
		ghi_bang("owner", "cash_receipts", "update", {"submitted_amount": 1}, "id", "@pth:R1"))
	them("f03_dong_phieu_thu", _don_hd("f03", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"),
		ghi_bang("sales_a", "cash_receipt_lines", "update", {"notes": "x"}, "receipt_id", "@dong_thu:R1"),
		ghi_bang("accountant", "cash_receipt_lines", "update", {"notes": "x"}, "receipt_id", "@dong_thu:R1"))
	them("f04_phieu_moi_ghi_thang", ghi_bang("owner", "cash_receipts", "insert", {"org_id": ORG, "receipt_code": "PT-TAY", "notes": "x"},
		"id", None))

	# ---- G. Huỷ HĐ
	them("g01_huy_hd_co_phieu", _don_hd("g01", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"),
		huy("owner"))
	them("g02_huy_hd_sau_huy_phieu", _don_hd("g02", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"),
		huy_thu("accountant", "R1"), huy("owner"))
	them("g03_huy_hd_khoa_rut_du_co", _don_hd("g03a", 1), nhan_hd("T1"), dk("accountant", "@C1", 100000),
		pos("manager", {**tra_c1, "invoice_id": "@hd:T1"}),
		thu("accountant", {"customer_id": "@C1", "use_credit": 10520, "lines": [{"receivable_id": "@no:dk:C1", "amount": 10520}]}, "R1"),
		chon_hd("T1"), huy("owner"))

	# ---- H. Sửa HĐ có tiền thu (mig 184)
	them("h01_sua_tang", _don_hd("h01", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 40000}]}, "R1"),
		sua("owner", [(0, {"quantity": 12})]))
	them("h02_sua_giam_duoi_da_thu", _don_hd("h02", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 80000}]}, "R1"),
		sua("owner", [(0, {"quantity": 5})]))
	them("h03_sua_giam_roi_tang", _don_hd("h03", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 80000}]}, "R1"),
		sua("owner", [(0, {"quantity": 5})]), sua("owner", [(0, {"quantity": 12})]))
	them("h04_du_co_sau_sua_bi_rut_roi_huy_goc", _don_hd("h04a", 10), nhan_hd("T1"),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 80000}]}, "R1"),
		sua("owner", [(0, {"quantity": 5})]), nhan_hd("T1"), _don_hd("h04b", 5), nhan_hd("T2"),
		thu("accountant", {"customer_id": "@C1", "use_credit": 30000, "lines": [{"receivable_id": "@no:hd:T2", "amount": 50000}]}, "R2"),
		huy_thu("accountant", "R1"))
	them("h05_sua_hd_phieu_huy_va_song", _don_hd("h05", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 10000}]}, "R1"),
		huy_thu("accountant", "R1"),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 20000}]}, "R2"),
		sua("owner", [(0, {"quantity": 8})]))
	them("h06_sua_hd_duoc_dap_du_co", _don_hd("h06", 10), pos("manager", tra_c1),
		thu("accountant", {"customer_id": "@C1", "use_credit": 20520, "lines": [{"receivable_id": "@no:hd", "amount": 100000}]}, "R1"),
		sua("owner", [(0, {"quantity": 10})]))

	# ---- I. Nghỉ việc / giao nợ
	them("i01_nghi_viec_no_ve_npp", _don_hd("i01", 10),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd", "amount": 40000}]}, "R1"),
		nghi("owner", "sales_a"), giao_no("accountant", "@C1", "sales_b"))

	# ---- J. RPC đọc theo vai
	nen_j = [dk("accountant", "@C2", 700000, han="@hom_nay-40"), _don_hd("j01a", 10, dk_tt="NET7", ngay="@hom_nay-20"), nhan_hd("T1"),
		thu("accountant", {"customer_id": "@C1", "lines": [{"receivable_id": "@no:hd:T1", "amount": 30000}]}, "R1"),
		ghi_no("accountant", "@no:dk:C2", "update", {"status": "overdue"})]
	for nguoi in ("owner", "sales_a", "warehouse"):
		them(f"j01_doc_{nguoi}", nen_j, doc(nguoi, "receivables_by_customer"), doc(nguoi, "receivables_by_rep"),
			doc(nguoi, "receivables_summary"), doc(nguoi, "cash_received_total", p_from="@hom_nay", p_to="@hom_nay"),
			doc(nguoi, "bao_cao_cong_no", p_tu_thu="@hom_nay-180", p_tu_90="@hom_nay-91"))
	return T


def _chuan(k: dict) -> dict:
	"""Ngày thật → "@hom_nay±n"; id trong số trả về: người / khách nền → khoá nền ("@u:sales_a", "@C1"), id khác → có / không (bài so dùng
	cùng luật — nppsale.tests.test_phieu_thu_vang._chuan_gt)."""
	hn = _hom_nay()
	ten_cua = {uid("u:" + x): "@u:" + x for x in NGUOI} | {ref("@" + x): "@" + x for x in KHACH}

	def ngay(v):
		if not isinstance(v, str) or len(v) != 10:
			return v
		try:
			d = datetime.date.fromisoformat(v)
		except ValueError:
			return v
		n = (d - hn).days
		return v if abs(n) > 400 else ("@hom_nay" if n == 0 else f"@hom_nay{n:+d}")

	def gt(v, khoa=None):
		if isinstance(v, dict):
			return {a: gt(b, a) for a, b in v.items()}
		if isinstance(v, list):
			return [gt(x) for x in v]
		if khoa and (khoa == "id" or khoa.endswith("_id")) and isinstance(v, str):
			return ten_cua.get(v, True)
		if khoa and khoa.endswith("_at"):  # mốc giờ (created_at, collected_at…) → có / không
			return v is not None
		return ngay(v)

	ct = k.get("ct") or {}
	ct["tra_ve"] = [gt(x) for x in ct.get("tra_ve") or []]
	for x in ct["tra_ve"]:  # bao_cao_cong_no: jsonb_agg không ORDER BY — so như tập hợp
		if isinstance(x, dict) and x.get("doc") == "bao_cao_cong_no" and isinstance(x.get("kq"), dict):
			x["kq"] = {a: sorted(b, key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False)) if isinstance(b, list) else b
				for a, b in x["kq"].items()}
	ct["nhan"] = sorted(ct.get("nhan") or {})
	for p in ct.get("phieu_thu") or []:
		p["ngay"] = ngay(p.get("ngay"))
	for c in ct.get("cong_no") or []:
		c["han"] = ngay(c.get("han"))
	for h in ct.get("hd") or []:
		h["han"] = ngay(h.get("han"))
	ct.pop("hom_nay", None)
	return k


def main():
	import vang_tao_don as VT

	# phiếu thu dùng giá bảng chung (P1 10.000 / lon) cho cả hai khách — C1 bỏ nhóm G1 (giá nhóm 9.500 chặn đơn 10.000: PRICE_OVER_CEILING)
	VT.KHACH.update({k: [v[0], None] for k, v in VT.KHACH.items()})
	T = tinh_huong()
	sql = ["BEGIN;", sql_nen(), sql_lo(), sql_ham_phu(), "CREATE TEMP TABLE _vang_kq (ma text, buoc jsonb, ct jsonb);"]
	sql += [sql_tinh_huong(t) for t in T]
	sql.append("SELECT json_agg(json_build_object('ma', ma, 'buoc', buoc, 'ct', ct)) FROM _vang_kq;")
	sql.append("ROLLBACK;")
	ra = subprocess.run(PSQL, shell=True, input="\n".join(sql), capture_output=True, text=True, check=False)
	if ra.returncode != 0:
		raise SystemExit(ra.stderr[-4000:])
	kq = {k["ma"]: _chuan(k) for k in json.loads(ra.stdout.strip().splitlines()[-1])}
	tep = {"ghi_chu": "Sinh bởi tools/vang_phieu_thu.py — hàm + trigger + RLS thật của nppsale (phiếu thu, tiền thu, nợ đầu kỳ, dư có, huỷ / sửa HĐ).",
		"nen": {"nguoi": NGUOI, "nhom": NHOM, "khach": KHACH, "hang": HANG, "gia": GIA, "lo": LO, "quyen_vai": QUYEN_VAI, "org": ORG,
			"la": uid("phieu-thu-la")},
		"tinh_huong": [dict(t, mong={"buoc": kq[t["ma"]]["buoc"], "ct": kq[t["ma"]]["ct"]}) for t in T]}
	with open(DICH, "w", encoding="utf-8") as f:
		json.dump(tep, f, ensure_ascii=False, indent=1)
		f.write("\n")
	print(f"{len(T)} tình huống → {DICH}")
	for t in T:
		k = kq[t["ma"]]
		bs = " | ".join("ok" if x["ok"] else f"{x['ma_loi']} {x['loi'][:110]}" for x in k["buoc"])
		nos = "; ".join(f"{c['no']} {c['so_tien']}/{c['da_thu']} {c['status']}" for c in (k["ct"] or {}).get("cong_no") or [])
		print(f"  {t['ma']:<38} {bs}\n      → {nos[:240]}")


if __name__ == "__main__":
	main()
