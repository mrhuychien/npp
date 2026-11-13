#!/usr/bin/env python3
"""Bảng chân trị NGƯỜI GIỮ NỢ — chạy CHÍNH trigger `_cong_no_giu_ve_npp` (mig 223 / 246) của nppsale ở Postgres tham chiếu: mọi tổ hợp
(người giữ cũ, mốc về NPP, dấu bàn giao) × người mới (đang làm / đã nghỉ / trống), cả lượt INSERT. tests/test_luat_giu_no.py so với
nppsale/luat/giu_no.py.

	python3 tools/vang_giu_no.py   → nppsale/tests/du_lieu/giu_no_mau.json
"""
from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vang_tao_don import ORG, PSQL, sql_nen, uid

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICH = os.path.join(GOC, "nppsale", "tests", "du_lieu", "giu_no_mau.json")
NV = {"A": "sales_a", "B": "sales_b", "N": "sales_giam"}  # N: đã nghỉ việc (left_at)


def _u(k):
	return "NULL" if k is None else f"'{uid('u:' + NV[k])}'"


def main():
	cu_ds = [(nv, ve, giao) for nv in ("A", "B", "N", None) for ve in (False, True) for giao in (None, "A", "B", "N")
		if not (ve and nv is not None)]  # chế độ giao nợ: có người giữ thì không có mốc về NPP
	moi_ds = ["A", "B", "N", None]
	sql = ["BEGIN;", sql_nen(), f"UPDATE users SET left_at = now() WHERE id = {_u('N')};",
		"CREATE TEMP TABLE _kq (loai text, cu jsonb, moi text, nv text, co_ve boolean, giao text);"]
	for i, ((nv, ve, giao), moi) in enumerate(itertools.product(cu_ds, moi_ds)):
		rid = uid(f"no:{i}")
		sql.append(f"""
SELECT set_config('npp.giao_cong_no', 'on', true);
INSERT INTO receivables (id, org_id, customer_id, sales_user_id, amount, opening_balance, ve_npp_luc, giao_tu_nv)
  VALUES ('{rid}', '{ORG}', '{uid('C1')}', {_u(nv)}, 1000, true, {'now()' if ve else 'NULL'}, {_u(giao)});
SELECT set_config('npp.giao_cong_no', '', true);
UPDATE receivables SET sales_user_id = {_u(moi)} WHERE id = '{rid}';
INSERT INTO _kq SELECT 'doi', '{json.dumps({"nv": nv, "ve": ve, "giao": giao})}'::jsonb, {'NULL' if moi is None else repr(moi)},
  (SELECT k FROM (VALUES {", ".join(f"('{k}', '{uid('u:' + v)}'::uuid)" for k, v in NV.items())}) x(k, id) WHERE x.id = r.sales_user_id),
  r.ve_npp_luc IS NOT NULL,
  (SELECT k FROM (VALUES {", ".join(f"('{k}', '{uid('u:' + v)}'::uuid)" for k, v in NV.items())}) x(k, id) WHERE x.id = r.giao_tu_nv)
  FROM receivables r WHERE r.id = '{rid}';
DELETE FROM receivables WHERE id = '{rid}';""")
	for j, moi in enumerate(moi_ds):
		rid = uid(f"lap:{j}")
		sql.append(f"""
INSERT INTO receivables (id, org_id, customer_id, sales_user_id, amount, opening_balance, giao_tu_nv)
  VALUES ('{rid}', '{ORG}', '{uid('C1')}', {_u(moi)}, 1000, true, {_u('B')});
INSERT INTO _kq SELECT 'lap', NULL, {'NULL' if moi is None else repr(moi)},
  (SELECT k FROM (VALUES {", ".join(f"('{k}', '{uid('u:' + v)}'::uuid)" for k, v in NV.items())}) x(k, id) WHERE x.id = r.sales_user_id),
  r.ve_npp_luc IS NOT NULL,
  (SELECT k FROM (VALUES {", ".join(f"('{k}', '{uid('u:' + v)}'::uuid)" for k, v in NV.items())}) x(k, id) WHERE x.id = r.giao_tu_nv)
  FROM receivables r WHERE r.id = '{rid}';
DELETE FROM receivables WHERE id = '{rid}';""")
	sql.append("SELECT json_agg(json_build_object('loai', loai, 'cu', cu, 'moi', moi, 'nv', nv, 'co_ve', co_ve, 'giao', giao)) FROM _kq;")
	sql.append("ROLLBACK;")
	ra = subprocess.run(PSQL, shell=True, input="\n".join(sql), capture_output=True, text=True, check=False)
	if ra.returncode != 0:
		raise SystemExit(ra.stderr[-4000:])
	kq = json.loads(ra.stdout.strip().splitlines()[-1])
	with open(DICH, "w", encoding="utf-8") as f:
		json.dump({"ghi_chu": "Sinh bởi tools/vang_giu_no.py — trigger _cong_no_giu_ve_npp thật của nppsale; N = NV đã nghỉ.",
			"dong": kq}, f, ensure_ascii=False, indent=1)
		f.write("\n")
	print(f"{len(kq)} dòng → {DICH}")


if __name__ == "__main__":
	main()
