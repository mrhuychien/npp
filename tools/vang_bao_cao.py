#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002, RUF003 — chữ tiếng Việt / số tiền dùng −, ×, – có chủ ý
"""Dữ liệu vàng cho BÁO CÁO (P6) — chạy CHÍNH hàm + trigger + RLS của nppsale (supabase/schema_full.sql) trên cụm Postgres NHÁP, và CHÍNH mã
TS của giao diện nppsale (tools/vang_bao_cao_ts.ts) cho phần số do trình duyệt tính.

Đặc tả: scratchpad bao_cao/dac_ta_bao_cao.md §5 (62 kịch bản VB-A01…VB-E16), §5.0 (ba bộ dữ liệu nền), §0.4 + §6.1 (Q1–Q14 — làm theo
"đề xuất"), mục "Chốt chéo với đặc tả P4" (ƯU TIÊN: giá dòng xuất lẻ XKL- / chuyển kho CKL- = 0 như nppsale — Q2 của Frappe = nppsale).

CÁCH CHẠY (mỗi lần dựng lại từ đầu — không đọc lại DB cũ; ~12 giây; hai lần liền nhau ra cùng tệp từng byte):
	python3 tools/vang_bao_cao.py                → nppsale/tests/du_lieu/bao_cao_mau.json (+ in bảng đối chiếu số với đặc tả)
	python3 tools/vang_bao_cao.py --chi VB-A0,VB-C → chỉ in các kịch bản ấy (không ghi tệp)
	VANG_BC_PSQL="<lệnh psql không -d>" …         → dùng cụm khác; VANG_BC_SCHEMA=<schema_full.sql> → bản schema khác
Cần: (1) một cụm Postgres 16 NHÁP được ghi / tạo DB (bộ sinh xoá + dựng lại mọi DB `vbc_*`, tạo vai Supabase nếu thiếu) — mặc định cụm Sổ BC của bước
đặc tả (Phụ lục C), bật bằng:
	unshare --user --map-user=1000 --map-group=1000 /usr/lib/postgresql/16/bin/pg_ctl -D <scratchpad>/bc_ban/pg/data \\
	  -o "-p 55640 -k <scratchpad>/bc_ban/pg/sock -c listen_addresses=''" -l <scratchpad>/bc_ban/pg/pg.log -w start
(KHÔNG dùng bản tham chiếu /tmp/pg-npp — bộ sinh ghi DB); (2) /home/user/nppsale/supabase/schema_full.sql (chỉ đọc); (3) portal/nguon/src
(scripts/lay-nguon.mjs — nppsale ghim ở portal/nguon.json) + portal/node_modules/.bin/esbuild + node.

1. KHUNG (DB `vbc_khung`, dựng lại mỗi lần ~3 giây): nền Supabase giả (vai anon / authenticated / service_role, schema auth + auth.uid() đọc
   `request.jwt.claim.sub`) + NGUYÊN schema_full.sql của nppsale + GRANT như Supabase + GHIM ĐỒNG HỒ: mọi `now()` / `CURRENT_DATE` /
   `gen_random_uuid()` / `random()` trong thân hàm (schema public, auth) và trong DEFAULT của cột được thay bằng `_vang_now()` / `_vang_today()` /
   `_vang_uuid()` / `_vang_random()` — giờ đọc từ biến phiên `vang.gio` (thiếu → lỗi VANG_CHUA_GHIM_GIO, không lặng lẽ lấy giờ thật), uuid / số
   ngẫu nhiên = md5 của số đếm (tất định — mã phiếu thu PT-YYMMDD-NNNN của create_cash_receipt dùng random()). Logic hàm KHÔNG đổi: bộ sinh
   kiểm lại từng thân hàm — hoàn nguyên các từ thay thế phải ra NGUYÊN VĂN thân gốc (`_kiem_ghim`), và không còn chỗ đọc giờ / uuid thật.
   Lý do: kịch bản phụ thuộc "lúc bấm" (phiếu nhập lại tự lập ghi sổ now(), credited_at = now() khi ngày phiếu = hôm nay, tuổi nợ theo
   vn_today()) — Postgres không có đồng hồ giả, libfaketime không cài. Chạy bất kỳ ngày nào cũng ra cùng tệp (hai lần liền nhau giống hệt).
2. BỘ NỀN (mỗi bộ một DB mới):
   - Sổ BC (S1 … S11): DB mới từ khung → hạt giống (ghi thẳng quyền máy chủ — danh mục như kb/00_seed.sql của bước đặc tả) → từng BƯỚC là
     MỘT lời gọi RPC nppsale dưới đúng người (`request.jwt.claim.sub` + ROLE authenticated, mỗi bước một giao dịch — như production) hoặc
     một ghi thẳng có kiểm soát (qua quyền trình duyệt = cổng Frappe; hoặc quyền máy chủ khi đặc tả nói không dựng được qua RPC — lý do ghi
     ở bước). Đồng hồ ghim theo từng bước ("gio"): Sổ BC dựng lúc 16/11/2026 20:50–21:10 VN như cụm của bước đặc tả (R15), giờ ghi sổ phiếu
     xuất của HĐ dời như kb/03_lui_gio.sql (bước ghi thẳng máy chủ). S2 … S11 = bản sao S1 (CREATE DATABASE … TEMPLATE) + bước riêng.
   - Nền N: DB mới từ khung + tools/vang_bao_cao_nen_n.sql (dựng TAY như bước đặc tả, trigger tắt); biến thể KB10 / KB14 / KB15 / KB21 chạy
     trong khối lui (như bien.sh).
   - E2E (bộ e2e một lượt, 29/09/2026): DB mới từ khung + chèn thẳng đúng dòng của e2e/bao-cao-cu-mot-luot.spec.ts (+ hai dòng nợ của VB-E04).
3. ĐỌC: mỗi lời gọi chạy dưới đúng người, đồng hồ ghim ("gio" của lời gọi — Sổ BC đọc lúc 17/11/2026 08:00 VN như [T] của đặc tả, Nền N
   lúc 16/11 12:00, E2E lúc 30/09 10:00), kết quả chuẩn hoá: uuid → khoá nghiệp vụ (mã chứng từ / mã phiếu / email NV / SKU / SĐT khách / tên
   NCC / mã lô), mốc giờ → "YYYY-MM-DDTHH:MM:SS+07:00", số → int khi chẵn; mảng không có thứ tự theo đặc tả được xếp theo khoá (so như tập).
4. TS: kết quả `bao_cao_so_ban` (dạng thô, id gốc) + danh mục mặt hàng → node chạy bản bó esbuild của vang_bao_cao_ts.ts → chuẩn hoá như trên.
5. Frappe: mỗi kịch bản mang "lech_frappe" (⚠K + "Frappe:" theo đề xuất Qn, Q2 = 0 theo chốt chéo P4) và — khi đổi số — "mong_frappe" (cùng
   dạng "mong", tính lại từ dữ liệu: giá vốn kỳ theo NGÀY HĐ (Q1), không quirk RLS (Q9), che giá vốn với vai thiếu `inventory.cost` (Q3),
   chuỗi không múi giờ = giờ VN (Q5)).
6. Đối chiếu với đặc tả: mỗi kịch bản có "doi_chieu" — số của đặc tả §5 ↔ số chạy thật; lệch thì TIN số chạy thật (đặc tả có thể sai).
"""
from __future__ import annotations

import argparse
import datetime
import decimal
import json
import os
import re
import subprocess
import sys
import tempfile

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICH = os.path.join(GOC, "nppsale", "tests", "du_lieu", "bao_cao_mau.json")
TS_GOC = os.path.join(GOC, "tools", "vang_bao_cao_ts.ts")
NEN_N_SQL = os.path.join(GOC, "tools", "vang_bao_cao_nen_n.sql")
NGUON_TS = os.path.join(GOC, "portal", "nguon", "src")
ESBUILD = os.path.join(GOC, "portal", "node_modules", ".bin", "esbuild")
SCHEMA = os.environ.get("VANG_BC_SCHEMA", "/home/user/nppsale/supabase/schema_full.sql")
_SP = "/tmp/claude-0/-home-user/be8a8bc5-5535-54ff-9841-5ce47a46cd08/scratchpad"
PSQL = os.environ.get(
	"VANG_BC_PSQL",
	f"unshare --user --map-user=1000 --map-group=1000 /usr/lib/postgresql/16/bin/psql -h {_SP}/bc_ban/pg/sock -p 55640 -U postgres",
)
TIEN_TO = "vbc_"  # mọi DB của bộ sinh: vbc_khung, vbc_s1 … — xoá / dựng lại mỗi lần
VN = datetime.timezone(datetime.timedelta(hours=7))


# ================================================================================================ psql
def psql(db: str, sql: str) -> str:
	ra = subprocess.run(f"{PSQL} -d {db} -X -q -t -A -v ON_ERROR_STOP=1", shell=True, input=sql, capture_output=True, text=True,
		check=False)
	if ra.returncode != 0:
		raise SystemExit(f"psql {db} hỏng:\n{ra.stderr[-6000:]}")
	return ra.stdout


def psql_json(db: str, sql: str):
	"""Câu trả MỘT giá trị json (dòng cuối của stdout) — số giữ Decimal (không mất chữ số)."""
	ra = psql(db, sql).strip().splitlines()
	return json.loads(ra[-1], parse_float=decimal.Decimal, parse_int=decimal.Decimal) if ra else None


def _lit(s) -> str:
	if s is None:
		return "NULL"
	return "'" + str(s).replace("'", "''") + "'"


def _j(v) -> str:
	return _lit(json.dumps(v, ensure_ascii=False, sort_keys=True))


# ================================================================================================ khung + đồng hồ ghim
NEN_SUPABASE = """
-- Nền giả của Supabase (như bc_ban/nen.sql của bước đặc tả) — vai tạo một lần cho cả cụm.
DO $r$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN CREATE ROLE service_role NOLOGIN BYPASSRLS; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticator') THEN CREATE ROLE authenticator NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_admin') THEN CREATE ROLE supabase_admin NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_user') THEN CREATE ROLE dashboard_user NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'postgres_fdw') THEN CREATE ROLE postgres_fdw NOLOGIN; END IF;
END $r$;
CREATE SCHEMA auth; CREATE SCHEMA storage; CREATE SCHEMA extensions; CREATE SCHEMA cron;
CREATE TABLE auth.users (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), email text, phone text, raw_user_meta_data jsonb, created_at timestamptz DEFAULT now());
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $f$ SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid $f$;
CREATE FUNCTION auth.role() RETURNS text LANGUAGE sql STABLE AS $f$ SELECT current_setting('request.jwt.claim.role', true) $f$;
CREATE FUNCTION auth.jwt() RETURNS jsonb LANGUAGE sql STABLE AS $f$ SELECT '{}'::jsonb $f$;
CREATE TABLE storage.buckets (id text PRIMARY KEY, name text, public boolean DEFAULT false, file_size_limit bigint, allowed_mime_types text[], created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now(), owner uuid);
CREATE TABLE storage.objects (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), bucket_id text, name text, owner uuid, metadata jsonb, created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now(), last_accessed_at timestamptz);
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
CREATE FUNCTION storage.foldername(name text) RETURNS text[] LANGUAGE sql IMMUTABLE AS $f$ SELECT string_to_array(name, '/') $f$;
CREATE TABLE cron.job (jobid bigserial PRIMARY KEY, jobname text, schedule text, command text);
CREATE FUNCTION cron.schedule(jobname text, schedule text, command text) RETURNS bigint LANGUAGE sql AS $f$ INSERT INTO cron.job(jobname, schedule, command) VALUES ($1, $2, $3) RETURNING jobid $f$;
CREATE FUNCTION cron.unschedule(jobname text) RETURNS boolean LANGUAGE sql AS $f$ DELETE FROM cron.job WHERE cron.job.jobname = $1 RETURNING true $f$;
GRANT USAGE ON SCHEMA auth, storage, extensions TO anon, authenticated, service_role;
"""

GRANT_SUPABASE = """
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
"""

HAM_GHIM = """
-- ĐỒNG HỒ GHIM của bộ sinh vàng (chỉ có ở DB nháp vbc_*): giờ = biến phiên vang.gio; thiếu là lỗi (không lặng lẽ dùng giờ thật).
CREATE OR REPLACE FUNCTION public._vang_now() RETURNS timestamptz LANGUAGE plpgsql STABLE AS $f$
DECLARE s text := current_setting('vang.gio', true);
BEGIN
  IF s IS NULL OR s = '' THEN RAISE EXCEPTION 'VANG_CHUA_GHIM_GIO'; END IF;
  RETURN s::timestamptz;
END $f$;
-- CURRENT_DATE = ngày theo múi giờ của PHIÊN (UTC như Supabase) — giữ đúng nghĩa.
CREATE OR REPLACE FUNCTION public._vang_today() RETURNS date LANGUAGE sql STABLE AS $f$
  SELECT (public._vang_now() AT TIME ZONE current_setting('TimeZone'))::date $f$;
-- random() (mã phiếu thu PT-YYMMDD-NNNN của create_cash_receipt) → dãy giả ngẫu nhiên tất định
CREATE SEQUENCE IF NOT EXISTS public._vang_rnd_seq;
CREATE OR REPLACE FUNCTION public._vang_random() RETURNS double precision LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public AS $f$
  SELECT ('x' || substr(md5('vang-rnd:' || nextval('public._vang_rnd_seq')::text), 1, 8))::bit(32)::bigint / 4294967296.0 $f$;
CREATE SEQUENCE IF NOT EXISTS public._vang_uuid_seq;
CREATE OR REPLACE FUNCTION public._vang_uuid() RETURNS uuid LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public AS $f$
  SELECT md5('vang-bao-cao:' || nextval('public._vang_uuid_seq')::text)::uuid $f$;
GRANT EXECUTE ON FUNCTION public._vang_now(), public._vang_today(), public._vang_uuid(), public._vang_random() TO PUBLIC;
"""

_TU_GIO = (r"\mnow\s*\(\s*\)|\mcurrent_date\M|gen_random_uuid\s*\(|clock_timestamp|statement_timestamp|transaction_timestamp|\mcurrent_timestamp\M"
	r"|\mlocaltimestamp\M|\mrandom\s*\(\s*\)")
_THAY = [
	(re.compile(r"(?<![\w.])now\s*\(\s*\)", re.I), "public._vang_now()"),
	(re.compile(r"(?<![\w.])(clock_timestamp|statement_timestamp|transaction_timestamp)\s*\(\s*\)", re.I), "public._vang_now()"),
	(re.compile(r"(?<![\w.])current_timestamp\b", re.I), "public._vang_now()"),
	(re.compile(r"(?<![\w.])localtimestamp\b", re.I), "(public._vang_now() AT TIME ZONE current_setting('TimeZone'))"),
	(re.compile(r"(?<![\w.])current_date\b", re.I), "public._vang_today()"),
	(re.compile(r"(?<![\w.])gen_random_uuid\s*\(\s*\)", re.I), "public._vang_uuid()"),
	(re.compile(r"(?<![\w.])random\s*\(\s*\)", re.I), "public._vang_random()"),
]


def _thay_gio(s: str) -> str:
	for re_, moi in _THAY:
		s = re_.sub(moi, s)
	return s


def _kiem_ghim(goc: str, moi: str) -> bool:
	"""Hoàn nguyên ba hàm ghim phải ra đúng thân gốc (chỉ đổi từ khoá đồng hồ / uuid — so không phân biệt hoa thường của từ khoá)."""
	def chuan(s):
		s = re.sub(r"\(public\._vang_now\(\) AT TIME ZONE current_setting\('TimeZone'\)\)", "localtimestamp", s)
		s = s.replace("public._vang_now()", "now()").replace("public._vang_today()", "current_date").replace("public._vang_uuid()", "gen_random_uuid()")
		s = s.replace("public._vang_random()", "random()")
		s = re.sub(r"(?<![\w.])random\s*\(\s*\)", "random()", s, flags=re.I)
		s = re.sub(r"(?<![\w.])(clock_timestamp|statement_timestamp|transaction_timestamp)\s*\(\s*\)", "now()", s, flags=re.I)
		s = re.sub(r"(?<![\w.])current_timestamp\b", "now()", s, flags=re.I)
		s = re.sub(r"(?<![\w.])now\s*\(\s*\)", "now()", s, flags=re.I)
		s = re.sub(r"(?<![\w.])current_date\b", "current_date", s, flags=re.I)
		s = re.sub(r"(?<![\w.])gen_random_uuid\s*\(\s*\)", "gen_random_uuid()", s, flags=re.I)
		return s
	return chuan(goc) == chuan(moi)


def dung_khung() -> dict:
	"""DB vbc_khung = nền Supabase + schema_full.sql + GRANT + đồng hồ ghim. Trả số hàm / cột đã ghim (ghi vào tệp vàng)."""
	ds = psql("postgres", f"SELECT datname FROM pg_database WHERE datname LIKE '{TIEN_TO}%' ORDER BY 1;").split()
	for d in ds:
		psql("postgres", f"DROP DATABASE IF EXISTS {d};")
	psql("postgres", f"CREATE DATABASE {TIEN_TO}khung TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C.UTF-8' LC_CTYPE 'C.UTF-8';")
	with open(SCHEMA, encoding="utf-8") as f:
		schema = f.read()
	psql(f"{TIEN_TO}khung", NEN_SUPABASE + "\n" + schema + "\n" + GRANT_SUPABASE + HAM_GHIM)
	db = f"{TIEN_TO}khung"
	ham = psql_json(db, f"""SELECT COALESCE(json_agg(json_build_object('ten', p.oid::regprocedure::text, 'def', pg_get_functiondef(p.oid))
		ORDER BY p.oid::regprocedure::text), '[]') FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
		WHERE n.nspname IN ('public', 'auth') AND p.prokind IN ('f', 'p') AND p.proname NOT LIKE '\\_vang\\_%'
		AND pg_get_functiondef(p.oid) ~* {_lit(_TU_GIO)};""")
	cot = psql_json(db, f"""SELECT COALESCE(json_agg(json_build_object('bang', format('%I.%I', n.nspname, c.relname), 'cot', a.attname,
		'expr', pg_get_expr(d.adbin, d.adrelid)) ORDER BY 1), '[]') FROM pg_attrdef d JOIN pg_class c ON c.oid = d.adrelid
		JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
		WHERE n.nspname IN ('public', 'auth', 'storage', 'cron') AND a.attgenerated = '' AND pg_get_expr(d.adbin, d.adrelid) ~* {_lit(_TU_GIO)};""")
	lenh = []
	for h in ham:
		moi = _thay_gio(h["def"])
		if not _kiem_ghim(h["def"], moi):
			raise SystemExit(f"ghim đồng hồ đổi thân hàm ngoài từ khoá: {h['ten']}")
		lenh.append(moi.rstrip() + ";")
	for c in cot:
		lenh.append(f"ALTER TABLE {c['bang']} ALTER COLUMN {json.dumps(c['cot'])} SET DEFAULT {_thay_gio(c['expr'])};")
	psql(db, "\n".join(lenh))
	con = psql_json(db, f"""SELECT json_build_object('ham', (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
		WHERE n.nspname IN ('public', 'auth') AND p.prokind IN ('f', 'p') AND p.proname NOT LIKE '\\_vang\\_%'
		AND pg_get_functiondef(p.oid) ~* {_lit(_TU_GIO)}), 'cot', (SELECT count(*) FROM pg_attrdef d JOIN pg_class c ON c.oid = d.adrelid
		JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname IN ('public', 'auth', 'storage', 'cron')
		AND pg_get_expr(d.adbin, d.adrelid) ~* {_lit(_TU_GIO)}));""")
	if int(con["ham"]) or int(con["cot"]):
		raise SystemExit(f"còn chỗ đọc đồng hồ / uuid thật sau khi ghim: {con}")
	psql(db, """
CREATE TABLE public._vang_buoc (bo text, so int, ok boolean, tra jsonb, ma_loi text, loi text);
CREATE TABLE public._vang_doc (ma text, so int, ok boolean, kq jsonb, ma_loi text, loi text);
""" + HAM_GIAI)
	return {"ham_da_ghim": len(ham), "cot_da_ghim": len(cot)}


# Giải chỗ giữ ĐỘNG trong tải trọng (chứng từ sinh ở bước trước) — chạy dưới quyền máy chủ nhưng auth.uid() là người của bước.
HAM_GIAI = r"""
CREATE OR REPLACE FUNCTION public._vang_id(s text) RETURNS uuid LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $f$
DECLARE v uuid;
BEGIN
  IF s LIKE '@don:%' THEN SELECT id INTO v FROM sales_orders WHERE order_code = substr(s, 6);
  ELSIF s LIKE '@hd:%' THEN SELECT id INTO v FROM sales_invoices WHERE invoice_code = substr(s, 5);
  ELSIF s LIKE '@pt:%' THEN SELECT id INTO v FROM returns WHERE return_code = substr(s, 5);
  ELSIF s LIKE '@no:hd:%' THEN SELECT rc.id INTO v FROM receivables rc JOIN sales_invoices si ON si.id = rc.invoice_id WHERE si.invoice_code = substr(s, 8);
  ELSIF s LIKE '@no:pt:%' THEN SELECT rc.id INTO v FROM receivables rc JOIN returns r ON r.id = rc.return_id WHERE r.return_code = substr(s, 8);
  ELSE RAISE EXCEPTION 'VANG_CHO_GIU_LA: %', s;
  END IF;
  IF v IS NULL THEN RAISE EXCEPTION 'VANG_KHONG_THAY: %', s; END IF;
  RETURN v;
END $f$;
CREATE OR REPLACE FUNCTION public._vang_giai(p jsonb, p_doi jsonb DEFAULT NULL) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public AS $f$
DECLARE s text; ra jsonb;
BEGIN
  IF p IS NULL THEN RETURN NULL; END IF;
  IF jsonb_typeof(p) = 'object' THEN
    SELECT COALESCE(jsonb_object_agg(e.key, public._vang_giai(e.value, p_doi)), '{}'::jsonb) INTO ra FROM jsonb_each(p) e;
    RETURN ra;
  ELSIF jsonb_typeof(p) = 'array' THEN
    SELECT COALESCE(jsonb_agg(public._vang_giai(e.v, p_doi) ORDER BY e.n), '[]'::jsonb) INTO ra FROM jsonb_array_elements(p) WITH ORDINALITY e(v, n);
    RETURN ra;
  ELSIF jsonb_typeof(p) <> 'string' THEN
    RETURN p;
  END IF;
  s := p #>> '{}';
  IF s LIKE '@dong_xuat:%' THEN
    -- = kb/xuat.sql của bước đặc tả: mọi dòng còn xuất của đơn (SL còn lại, giá đơn) — như màn Xuất hàng gửi nguyên
    SELECT jsonb_agg(jsonb_build_object('order_line_id', g.order_line_id, 'product_id', g.product_id, 'unit_name', g.unit_name,
             'conversion_factor', g.conversion_factor, 'quantity', g.remaining_qty, 'unit_price', g.unit_price, 'line_discount', g.line_discount,
             'vat_rate', g.vat_rate::text, 'is_exchange', g.is_exchange, 'note', g.note))
      INTO ra FROM get_invoiceable_lines(public._vang_id('@don:' || substr(s, 12))) g;
    RETURN ra;
  ELSIF s LIKE '@dong_sua:%' THEN
    -- = kb/08_sua_hd2.sql: dòng hiện có của HĐ, SL đổi theo p_doi {"<SKU>/<ĐV>": SL}
    SELECT jsonb_agg(jsonb_build_object('order_line_id', l.order_line_id, 'product_id', l.product_id, 'unit_name', l.unit_name,
             'conversion_factor', l.conversion_factor,
             'quantity', COALESCE((p_doi ->> (pr.sku || '/' || l.unit_name))::numeric, l.quantity),
             'unit_price', l.unit_price, 'line_discount', l.line_discount, 'vat_rate', l.vat_rate::text, 'is_exchange', l.is_exchange)
             ORDER BY l.sort_order)
      INTO ra FROM sales_invoice_lines l JOIN products pr ON pr.id = l.product_id
     WHERE l.invoice_id = public._vang_id('@hd:' || substr(s, 11));
    RETURN ra;
  ELSIF s ~ '^@(don|hd|pt|no):' THEN
    RETURN to_jsonb(public._vang_id(s));
  END IF;
  RETURN p;
END $f$;
GRANT EXECUTE ON FUNCTION public._vang_id(text), public._vang_giai(jsonb, jsonb) TO PUBLIC;
"""


# ================================================================================================ bộ nền
# ---- Sổ BC (S) — §5.0 mục 1; uuid hạt giống giữ như kb/00_seed.sql của bước đặc tả -------------------------------------------------
ORG_S = "00000000-0000-0000-0000-0000000000a1"
_u = lambda d: "00000000-0000-0000-0000-" + d.rjust(12, "0")  # noqa: E731
# người: khoá → (uuid, tên, vai, email — id NV bên Frappe = NPP Nhan Vien.name = email)
NGUOI_S = {
	"CHU": (_u("b001"), "Chu NPP", "owner", "chu@sobc.vn"),
	"NV_AN": (_u("b002"), "NV An", "sales", "nv.an@sobc.vn"),
	"TK": (_u("b003"), "Thu kho", "warehouse", "thukho@sobc.vn"),
	"KT": (_u("b004"), "Ke toan", "accountant", "ketoan@sobc.vn"),
	"NV_BINH": (_u("b005"), "NV Binh", "sales", "nv.binh@sobc.vn"),
	"QL": (_u("b006"), "Quan ly", "manager", "quanly@sobc.vn"),
}
NCC_S = {"CTY_NUOC": (_u("f0001"), "Cty Nuoc"), "CTY_BANH": (_u("f0002"), "Cty Banh")}
CONG_TY_NV_S = {"NV_AN": ["CTY_NUOC"], "NV_BINH": ["CTY_BANH"]}
# khách: khoá → (uuid, tên cửa hàng, chủ, SĐT, tuyến) — hạn mức 100.000.000, COD, địa chỉ HN, người tạo Chủ
KHACH_S = {
	"K1": (_u("c0001"), "Tap hoa Hai", "Chi Hai", "0911000001", "GT"),
	"K2": (_u("c0002"), "Sieu thi Ba", "Anh Ba", "0911000002", "MT"),
	"K3": (_u("c0003"), "Quan Tu", "Co Tu", "0911000003", ""),
}
PHAN_CONG_S = [("K1", "NV_AN", "primary"), ("K2", "NV_BINH", "primary"), ("K3", "NV_AN", "primary"), ("K3", "NV_BINH", "secondary")]
# hàng: SKU → (uuid, tên, ĐV cơ sở, VAT, giá bán cơ sở (sell_price), giá vốn mặc định, NCC chính, {ĐV: hệ số})
HANG_S = {
	"SP1": (_u("d0001"), "Nuoc ngot", "lon", 0, 10000, 7000, "CTY_NUOC", {"thung": 24}),
	"SP2": (_u("d0002"), "Banh quy", "goi", 0.08, 5000, 3000, "CTY_BANH", {}),
	"SP3": (_u("d0003"), "Keo", "goi", 0, 2000, 1000, None, {}),
}
# lô (kho bán): mã → (uuid, SKU, hạn, SL đầu = tồn đầu (ĐV cơ sở), giá vốn / ĐV cơ sở) — nhận 01/10/2026 08:00 VN
LO_S = {
	"L1": (_u("e0001"), "SP1", "2028-12-31", 2000, 7000),
	"L2": (_u("e0002"), "SP2", "2028-12-31", 2000, 3000),
	"L3": (_u("e0003"), "SP3", "2028-12-31", 2000, 1000),
}
PK_TAY_S = {"XK-HUY-01": _u("aa01"), "XK-MAU-02": _u("aa02")}  # phiếu xuất kho lẻ (kb/06) — id cố định như bước đặc tả
PTNCC_S = {"TRNCC-1": _u("ab01")}  # phiếu trả NCC của VB-E08 (bộ S9)
GIO_SEED_S = "2026-11-16T20:50:26+07:00"  # = created_at lô của cụm bước đặc tả (13:50:26 UTC)
GIO_DOC_S = "2026-11-17T08:00:00+07:00"   # đọc: vn_today() = 17/11/2026 (như [T] — VB-A16 receivables_summary)


def sql_seed_s() -> str:
	q = [f"INSERT INTO organizations (id, name, slug) VALUES ('{ORG_S}', 'NPP BC', 'npp-bc');"]
	for i, ten, vai, _email in NGUOI_S.values():
		q.append(f"INSERT INTO auth.users (id) VALUES ('{i}');")
		q.append(f"INSERT INTO users (id, org_id, full_name, role) VALUES ('{i}', '{ORG_S}', {_lit(ten)}, '{vai}');")
	for i, ten in NCC_S.values():
		q.append(f"INSERT INTO suppliers (id, org_id, name) VALUES ('{i}', '{ORG_S}', {_lit(ten)});")
	for nv, ds in CONG_TY_NV_S.items():
		for n in ds:
			q.append(f"INSERT INTO user_suppliers (user_id, supplier_id, org_id) VALUES ('{NGUOI_S[nv][0]}', '{NCC_S[n][0]}', '{ORG_S}');")
	for i, ten, chu, sdt, tuyen in KHACH_S.values():
		q.append("INSERT INTO customers (id, org_id, store_name, owner_name, phone, address, credit_limit, payment_terms, channel, created_by) "
			f"VALUES ('{i}', '{ORG_S}', {_lit(ten)}, {_lit(chu)}, '{sdt}', 'HN', 100000000, 'COD', {_lit(tuyen)}, '{NGUOI_S['CHU'][0]}');")
	for kh, nv, vai in PHAN_CONG_S:
		q.append(f"INSERT INTO customer_assignments (customer_id, user_id, role, status) VALUES ('{KHACH_S[kh][0]}', '{NGUOI_S[nv][0]}', '{vai}', 'active');")
	for sku, (i, ten, dv, vat, gia, von, ncc, dvs) in HANG_S.items():
		q.append("INSERT INTO products (id, org_id, sku, name, base_unit, vat_rate, sell_price, cost_price, primary_supplier_id) VALUES "
			f"('{i}', '{ORG_S}', '{sku}', {_lit(ten)}, {_lit(dv)}, {vat}, {gia}, {von}, {_lit(NCC_S[ncc][0]) if ncc else 'NULL'});")
		for dvx, hs in dvs.items():
			q.append(f"INSERT INTO product_units (product_id, unit_name, conversion) VALUES ('{i}', {_lit(dvx)}, {hs});")
	for ma, (i, sku, han, sl, gia) in LO_S.items():
		q.append("INSERT INTO batches (id, org_id, product_id, batch_code, expires_at, qty_initial, qty_on_hand, unit_cost, warehouse_zone, received_at) "
			f"VALUES ('{i}', '{ORG_S}', '{HANG_S[sku][0]}', '{ma}', '{han}', {sl}, {sl}, {gia}, 'sale', '2026-10-01T08:00:00+07:00');")
	return "\n".join(q)


# ---- Nền N — §5.4; tools/vang_bao_cao_nen_n.sql (dựng tay) --------------------------------------------------------------------
ORG_N = "a0000000-0000-0000-0000-00000000000a"
ORG_NB = "b0000000-0000-0000-0000-00000000000b"
_n = lambda p, d: f"{p}0000000-0000-0000-0000-0000000000{d:02d}"  # noqa: E731
NGUOI_N = {
	"CHU": (_n(1, 1), "Chủ A", "owner", "chu@nenn.vn"), "QL": (_n(1, 2), "Quản lý A", "manager", "quanly@nenn.vn"),
	"KT": (_n(1, 3), "Kế toán A", "accountant", "ketoan@nenn.vn"), "TK": (_n(1, 4), "Thủ kho A", "warehouse", "thukho@nenn.vn"),
	"NV_MOT": (_n(1, 5), "NV Một", "sales", "nv.mot@nenn.vn"), "NV_HAI": (_n(1, 6), "NV Hai", "sales", "nv.hai@nenn.vn"),
	"KHOA": (_n(1, 8), "Bị khoá", "owner", "khoa@nenn.vn"), "CHU_B": (_n(1, 9), "Chủ B", "owner", "chu.b@nppb.vn"),
}
KHACH_N = {"K1": (_n(2, 1), "Tạp hoá Một", "0900000001"), "K2": (_n(2, 2), "Tạp hoá Hai", "0900000002"),
	"K3": (_n(2, 3), "Tạp hoá Ba", "0900000003"), "KB": (_n(2, 9), "Khách B", "0900000009")}
HANG_N = {"SP1": (_n(3, 1), "Nước ngọt", "Lon"), "SP2": (_n(3, 2), "Dầu ăn", "Chai"), "SPB": (_n(3, 9), "Hàng B", "Cái")}
GIO_NAP_N = "2026-11-16T12:00:00+07:00"
GIO_DOC_N = "2026-11-16T12:00:00+07:00"  # T = 16/11/2026 (nền N ép vn_today() = 16/11)
# khoá nghiệp vụ của các dòng dựng tay (uuid cố định trong tệp nền) — dùng ở chuẩn hoá
KHOA_N = {}
for _i in range(1, 7):
	KHOA_N[_n(4, _i)] = f"DH{_i}"
	KHOA_N[_n(5, _i)] = f"HD-000{_i}"
	KHOA_N[_n(7, _i)] = f"RC{_i}"
	KHOA_N[_n(8, _i)] = f"PM{_i}"
	KHOA_N[f"d0000000-0000-0000-0000-0000000000{_i:02d}"] = f"PY{_i}"
	KHOA_N[f"f1000000-0000-0000-0000-0000000000{_i:02d}"] = f"X{_i}"
for _i in range(1, 6):
	KHOA_N[_n(6, _i)] = f"R{_i}"
	KHOA_N[f"e0000000-0000-0000-0000-0000000000{_i:02d}"] = f"PP{_i}"
KHOA_N[_n(7, 7)] = "RC7"
KHOA_N[_n(8, 7)] = "PM7"
for _i in range(1, 16):
	KHOA_N[f"90000000-0000-0000-0000-0000000000{_i:02d}"] = f"E{_i}"
KHOA_N.update({_n(4, 9): "B:DH1", _n(5, 9): "B:HD-0001", _n(7, 9): "B:RC1", _n(8, 9): "B:PM1",
	"90000000-0000-0000-0000-000000000099": "B:E1", "f1000000-0000-0000-0000-000000000009": "B:X1",
	"c0000000-0000-0000-0000-000000000001": "NCC Một", "c0000000-0000-0000-0000-000000000002": "NCC Hai",
	"c0000000-0000-0000-0000-000000000003": "NCC Ba", "c1000000-0000-0000-0000-000000000001": "TH-1", ORG_N: "NPP A", ORG_NB: "NPP B"})
for _k, (_i, _t, _v, _e) in NGUOI_N.items():
	KHOA_N[_i] = _e
for _k, (_i, _t, _s) in KHACH_N.items():
	KHOA_N[_i] = _s
for _k, (_i, _t, _d) in HANG_N.items():
	KHOA_N[_i] = _k
for _i, _c, _nh in (("f0000000-0000-0000-0000-000000000001", "RENT", "operating"), ("f0000000-0000-0000-0000-000000000002", "SALARY", "hr"),
		("f0000000-0000-0000-0000-000000000003", "COGS_ADJ", "cogs"), ("f0000000-0000-0000-0000-000000000004", "FIN", "financial"),
		("f0000000-0000-0000-0000-000000000005", "TAX", "tax")):
	KHOA_N[_i] = _c

# ---- E2E — e2e/bao-cao-cu-mot-luot.spec.ts (29/09/2026) + hai dòng nợ VB-E04 (§5.5) ----------------------------------------------
ORG_E = "00000000-0000-4000-8000-0000000000a1"
NGUOI_E = {"CHU": ("00000000-0000-4000-8000-0000000000b1", "Chu E2E", "owner", "chu@e2e.vn"),
	"NV_A": ("00000000-0000-4000-8000-0000000000b6", "NV Một Lượt A", "sales", "nv.a@e2e.vn"),
	"NV_B": ("00000000-0000-4000-8000-0000000000b7", "NV Một Lượt B", "sales", "nv.b@e2e.vn")}
# id GIỮ thứ tự của e2e: 'hd-ml-a' < 'hd-ml-b' (mã điểm) — nhanVienPhieuTra đoán NV phiếu trả cũ theo HĐ gặp trước
ID_E = {"KH": "00000000-0000-4000-8000-0000000000c7", "SP": "00000000-0000-4000-8000-0000000000d6",
	"HD-ML-A": "e2e00000-0000-4000-8000-00000000000a", "HD-ML-B": "e2e00000-0000-4000-8000-00000000000b",
	"HD-ML-HUY": "e2e00000-0000-4000-8000-00000000000c", "TR-ML-1": "e2e00000-0000-4000-8000-0000000000e1",
	"SE-ML-1": "e2e00000-0000-4000-8000-0000000000f1", "SE-ML-HUY": "e2e00000-0000-4000-8000-0000000000f2",
	"SE-ML-DAO": "e2e00000-0000-4000-8000-0000000000f3", "SE-ML-NHAP": "e2e00000-0000-4000-8000-0000000000f4",
	"KH-CO-BA": "00000000-0000-4000-8000-0000000000c1", "KH-DAI-LY-MINH": "00000000-0000-4000-8000-0000000000c2",
	"HD-E2E-1": "e2e00000-0000-4000-8000-0000000000a1", "TR-E2E-1": "e2e00000-0000-4000-8000-0000000000e2",
	"bc-rc-1": "e2e00000-0000-4000-8000-0000000000d1", "bc-rc-2": "e2e00000-0000-4000-8000-0000000000d2"}
SDT_E = {"KH": "0912000001", "KH-CO-BA": "0912000002", "KH-DAI-LY-MINH": "0912000003"}
GIO_NAP_E = "2026-09-30T10:00:00+07:00"
GIO_DOC_E = "2026-09-30T10:00:00+07:00"  # đồng hồ e2e 30/09/2026


def sql_e2e() -> str:
	"""Đúng dòng e2e/bao-cao-cu-mot-luot.spec.ts (beforeAll) chèn thẳng (trigger tắt — như sổ giả e2e); id chữ của e2e → uuid giữ thứ tự."""
	i = ID_E
	n = "'2026-09-29'"
	chu, nva, nvb = NGUOI_E["CHU"][0], NGUOI_E["NV_A"][0], NGUOI_E["NV_B"][0]
	q = ["SET session_replication_role = replica;",
		f"INSERT INTO organizations (id, name, slug) VALUES ('{ORG_E}', 'NPP E2E', 'npp-e2e');"]
	for u, ten, vai, _e in NGUOI_E.values():
		q.append(f"INSERT INTO auth.users (id) VALUES ('{u}');")
		q.append(f"INSERT INTO users (id, org_id, full_name, role, is_active, created_at) VALUES ('{u}', '{ORG_E}', {_lit(ten)}, '{vai}', true, "
			"'2026-09-01T00:00:00Z');")
	q.append(f"INSERT INTO products (id, org_id, sku, name, brand, base_unit, sell_price, status, primary_supplier_id) VALUES ('{i['SP']}', '{ORG_E}', "
		"'ML1', 'Sữa một lượt', 'Hiệu Một Lượt', 'hộp', 20000, 'active', NULL);")
	q.append(f"INSERT INTO product_units (product_id, unit_name, conversion) VALUES ('{i['SP']}', 'thùng', 24);")
	q.append(f"INSERT INTO price_lists (id, product_id, unit_name, group_id, price) VALUES (md5('pl-ml-t')::uuid, '{i['SP']}', 'thùng', NULL, 450000), "
		f"(md5('pl-ml-h')::uuid, '{i['SP']}', 'hộp', NULL, 20000);")
	for k, ten in (("KH", "Khách Một Lượt"), ("KH-CO-BA", "Tạp hoá Cô Ba"), ("KH-DAI-LY-MINH", "Đại lý Minh")):
		q.append(f"INSERT INTO customers (id, org_id, store_name, owner_name, phone, address, group_id, channel, payment_terms, credit_limit, status) "
			f"VALUES ('{i[k]}', '{ORG_E}', {_lit(ten)}, 'Chu', '{SDT_E[k]}', 'HN', NULL, NULL, 'COD', 0, 'active');")
	# B chèn TRƯỚC A (thứ tự tự nhiên của sổ khác thứ tự cách cũ xếp) — như e2e. Sổ thật bắt buộc order_id / invoice_seq (sổ giả e2e để null):
	# mỗi HĐ một đơn DH-ML-* cùng NV (một đơn một HĐ — mig 217); đơn không vào số nào của các kịch bản E.
	for so_, (k, nv, st, tong, se) in enumerate((("HD-ML-B", nvb, "posted", 210000, "SE-ML-1"), ("HD-ML-A", nva, "posted", 920000, "SE-ML-1"),
			("HD-ML-HUY", nva, "cancelled", 100000, "SE-ML-HUY")), 1):
		don = "DH" + k[2:]
		q.append(f"INSERT INTO sales_orders (id, org_id, order_code, customer_id, sales_user_id, order_date, status, total, order_seq) VALUES "
			f"(md5('{don}')::uuid, '{ORG_E}', '{don}', '{i['KH']}', '{nv}', {n}, '{'cancelled' if st == 'cancelled' else 'completed'}', {tong}, {so_});")
		q.append("INSERT INTO sales_invoices (id, org_id, invoice_code, order_id, customer_id, status, subtotal, vat, total, payment_terms, due_date, "
			f"invoice_date, created_at, sales_user_id, posted_by, stock_entry_id, invoice_seq) VALUES ('{i[k]}', '{ORG_E}', '{k}', md5('{don}')::uuid, "
			f"'{i['KH']}', '{st}', {tong}, 0, {tong}, 'COD', {n}, {n}, '2026-09-29T03:00:00Z', '{nv}', '{chu}', '{i[se]}', {so_});")
	for hd, sl, dv, hs, gia, tien, doi, stt in (("HD-ML-B", 10, "hộp", 1, 21000, 210000, False, 0), ("HD-ML-A", 2, "thùng", 24, 470000, 940000, False, 0),
			("HD-ML-A", 3, "hộp", 1, 0, 0, True, 1), ("HD-ML-HUY", 5, "hộp", 1, 20000, 100000, False, 0)):
		q.append("INSERT INTO sales_invoice_lines (id, invoice_id, product_id, quantity, unit_name, conversion_factor, unit_price, line_discount, vat_rate, "
			f"line_total, is_exchange, sort_order, order_line_id) VALUES (md5('{hd}/{dv}/{doi}')::uuid, '{i[hd]}', '{i['SP']}', {sl}, '{dv}', {hs}, {gia}, 0, 0, "
			f"{tien}, {str(doi).lower()}, {stt}, NULL);")
	q.append("INSERT INTO returns (id, org_id, customer_id, invoice_id, credit_note_amount, created_at, revenue_date, sales_user_id, requested_by, reason, "
		f"credit_with_invoice, status, return_code) VALUES ('{i['TR-ML-1']}', '{ORG_E}', '{i['KH']}', NULL, 42000, '2026-09-29T06:00:00Z', {n}, NULL, "
		f"'{chu}', 'damaged', false, 'completed', 'TR-ML-1');")
	q.append("INSERT INTO return_lines (id, return_id, product_id, unit_name, quantity, unit_price, line_total, is_exchange) VALUES "
		f"(md5('rl-ml-1')::uuid, '{i['TR-ML-1']}', '{i['SP']}', 'hộp', 2, 21000, 42000, false);")
	for k, loai, ghi in (("SE-ML-1", "export", ""), ("SE-ML-HUY", "export", ""), ("SE-ML-DAO", "export", "Đảo phiếu trả 00000000-0000-4000-8000-000000000999"),
			("SE-ML-NHAP", "import", f"Nhập lại từ phiếu trả {i['TR-ML-1']}")):
		q.append(f"INSERT INTO stock_entries (id, org_id, entry_code, type, status, posted_at, notes) VALUES ('{i[k]}', '{ORG_E}', '{k}', '{loai}', "
			f"'posted', '2026-09-29T04:00:00Z', {_lit(ghi)});")
	for k, sl, gia in (("SE-ML-1", 58, 15000), ("SE-ML-HUY", 5, 15000), ("SE-ML-DAO", 7, 0), ("SE-ML-NHAP", 2, 15000)):
		q.append("INSERT INTO stock_entry_lines (id, entry_id, product_id, unit_name, quantity, qty_in_base_uom, conversion_factor_snapshot, unit_cost) VALUES "
			f"(md5('sel/{k}')::uuid, '{i[k]}', '{i['SP']}', 'hộp', {sl}, {sl}, 1, {gia});")
	# VB-E04 (e2e/doi-cong-no-thu-tien / bao-cao-tong-hop): bc-rc-1 Cô Ba 900.000 / 200.000 hạn 01/09 partial, HĐ HD-E2E-1 (20/08);
	# bc-rc-2 Đại lý Minh −150.000 / 0 open, gắn phiếu trả (10/09) — e2e/bao-cao-tong-hop.spec.ts:162-166 (người giữ nợ = Chủ)
	q.append(f"INSERT INTO sales_orders (id, org_id, order_code, customer_id, sales_user_id, order_date, status, total, order_seq) VALUES "
		f"(md5('DH-E2E-1')::uuid, '{ORG_E}', 'DH-E2E-1', '{i['KH-CO-BA']}', '{chu}', '2026-08-20', 'completed', 900000, 4);")
	q.append("INSERT INTO sales_invoices (id, org_id, invoice_code, order_id, customer_id, status, subtotal, vat, total, payment_terms, due_date, invoice_date, "
		f"created_at, sales_user_id, posted_by, invoice_seq) VALUES ('{i['HD-E2E-1']}', '{ORG_E}', 'HD-E2E-1', md5('DH-E2E-1')::uuid, '{i['KH-CO-BA']}', 'posted', "
		f"900000, 0, 900000, 'NET12', '2026-09-01', '2026-08-20', '2026-08-20T03:00:00Z', '{chu}', '{chu}', 4);")
	q.append("INSERT INTO returns (id, org_id, customer_id, credit_note_amount, created_at, revenue_date, sales_user_id, requested_by, reason, "
		f"credit_with_invoice, status, return_code) VALUES ('{i['TR-E2E-1']}', '{ORG_E}', '{i['KH-DAI-LY-MINH']}', 150000, '2026-09-10T03:00:00Z', "
		f"'2026-09-10', '{chu}', '{chu}', 'damaged', false, 'completed', 'TR-E2E-1');")
	q.append("INSERT INTO receivables (id, org_id, customer_id, sales_user_id, invoice_id, return_id, amount, paid, due_date, status, opening_balance, created_at) "
		f"VALUES ('{i['bc-rc-1']}', '{ORG_E}', '{i['KH-CO-BA']}', '{chu}', '{i['HD-E2E-1']}', NULL, 900000, 200000, '2026-09-01', 'partial', false, "
		f"'2026-08-20T03:00:00Z'), ('{i['bc-rc-2']}', '{ORG_E}', '{i['KH-DAI-LY-MINH']}', '{chu}', NULL, '{i['TR-E2E-1']}', -150000, 0, NULL, 'open', "
		"false, '2026-09-10T03:00:00Z');")
	q.append("SET session_replication_role = origin;")
	return "\n".join(q)


# ================================================================================================ bước dựng (dữ liệu — bài Frappe phát lại)
def rpc(nguoi, ham, tham_so, gio, *, nhan=None, cho_loi=None, doi=None, ghi_chu=None, frappe=None):
	"""MỘT lời gọi RPC nppsale dưới đúng người; tham_so = tham số đặt tên như PostgREST gửi (chỗ giữ "@…" = khoá nghiệp vụ)."""
	b = {"loai": "rpc", "nguoi": nguoi, "rpc": ham, "tham_so": tham_so, "gio": gio}
	for k, v in (("nhan", nhan), ("cho_loi", cho_loi), ("doi_sl", doi), ("ghi_chu", ghi_chu), ("frappe", frappe)):
		if v is not None:
			b[k] = v
	return b


def cong(nguoi, bang, hanh_dong, gio, *, gia_tri=None, loc=None, ly_do, frappe=None):
	"""Ghi thẳng QUA QUYỀN TRÌNH DUYỆT (vai authenticated: RLS + trigger khoá ghi thẳng như production) = ghi qua cổng bảng bên Frappe."""
	b = {"loai": "ghi_cong", "nguoi": nguoi, "bang": bang, "hanh_dong": hanh_dong, "gio": gio, "ly_do": ly_do}
	if gia_tri is not None:
		b["gia_tri"] = gia_tri
	if loc is not None:
		b["loc"] = loc
	if frappe is not None:
		b["frappe"] = frappe
	return b


def may_chu(mo_ta, sql, gio, *, ly_do, frappe):
	"""Ghi thẳng QUYỀN MÁY CHỦ (không người, trigger vẫn chạy) — chỉ chỗ đặc tả nói không dựng được qua RPC / cổng; frappe = cách bản Frappe làm."""
	return {"loai": "ghi_may_chu", "nguoi": "MAY_CHU", "mo_ta": mo_ta, "sql": " ".join(sql.split()), "gio": gio, "ly_do": ly_do, "frappe": frappe}


def g(hh, mm, ss=0, ngay="2026-11-16"):
	return f"{ngay}T{hh:02d}:{mm:02d}:{ss:02d}+07:00"


def _don(crid, kh, tong, dong, *, tra=None, dong_tra=None, nv=None):
	o = {"customer_id": kh, "payment_terms": "COD", **tong, "status": "submitted", "approval_reason": ""}
	if nv:
		o["sales_user_id"] = nv
	return {"p": {"client_request_id": crid, "order": o, "lines": dong, "returns": tra, "return_lines": dong_tra or []}}


def _dd(sp, dv, sl, gia, hs, vat):
	return {"product_id": "@sp:" + sp, "unit_name": dv, "quantity": sl, "unit_price": gia, "line_total": sl * gia, "conversion_factor": hs,
		"vat_rate": vat}


def _dt(sp, dv, sl, gia, vat, doi=False, ly_do=None, tien=None):
	x = {"product_id": "@sp:" + sp, "unit_name": dv, "quantity": sl, "unit_price": gia, "vat_rate": vat,
		"line_total": tien if tien is not None else round(sl * gia * (1 + vat)), "is_exchange": doi}
	if ly_do:
		x["reason"] = ly_do
	return x


def _xuat(nguoi, don, ngay, giam, gio, nhan):
	return rpc(nguoi, "post_invoice", {"p": {"order_id": "@don:" + don, "invoice_date": ngay, "discount": giam, "lines": "@dong_xuat:" + don}}, gio,
		nhan=nhan, ghi_chu="lines = mọi dòng còn xuất của đơn (get_invoiceable_lines — SL còn lại, giá đơn, hàng đổi) như kb/xuat.sql",
		frappe="get_invoiceable_lines(đơn) rồi post_invoice với invoice_date + giảm giá đơn (Frappe: posting_date = ngày HĐ)")


def _lui_gio_xuat(hd, moc, gio):
	return may_chu(f"phiếu xuất của {hd}: posted_at = created_at = {moc}; sales_invoices.posted_at theo",
		f"UPDATE stock_entries e SET posted_at = '{moc}', created_at = '{moc}' FROM sales_invoices si WHERE si.invoice_code = '{hd}' AND e.id = si.stock_entry_id; "
		f"UPDATE sales_invoices si SET posted_at = '{moc}' WHERE si.invoice_code = '{hd}';", gio,
		ly_do="kb/03_lui_gio.sql: mô phỏng giờ ghi sổ THẬT của phiếu xuất (cụm dựng cả sổ trong 20 phút ngày 16/11; post_invoice ghi posted_at = now())",
		frappe="bỏ qua — Frappe ghi sổ kho theo posting_date = ngày HĐ (Q1); 'lúc bấm' chỉ là creation")


NV, CHU, AN, BINH = "@nv:", "CHU", "NV_AN", "NV_BINH"
K1, K2, K3 = "@kh:0911000001", "@kh:0911000002", "@kh:0911000003"
LY_DO_NGAY_PHIEU = "ngày chứng từ của phiếu tự lập Nháp — màn sửa phiếu ghi thẳng (mig 214 cho ghi Nháp; = kb/05_tra2.sql)"


def buoc_s1() -> list[dict]:
	"""Sổ BC — kb/00_seed … 07_thu + 09_dh5 (+ kb/xuat.sql, kb/03 dời giờ) của bước đặc tả, đúng thứ tự đã chạy (npp_s1)."""
	B = []
	B.append(rpc(AN, "create_order_with_lines", _don("22222222-2222-2222-2222-000000000001", K1, {"subtotal": 530000, "vat": 4000, "total": 534000},
		[_dd("SP1", "thung", 2, 240000, 24, "0"), _dd("SP2", "goi", 10, 5000, 1, "0.08")],
		tra={"reason": "damaged", "notes": "hang mop"},
		dong_tra=[_dt("SP1", "lon", 3, 10000, 0, ly_do="damaged"), _dt("SP3", "goi", 5, 2000, 0, doi=True)]), g(20, 50, 47), nhan="DH-0001"))
	B.append(_xuat(CHU, "DH-0001", "2026-11-03", "0", g(20, 51, 3), "HD-0001"))
	B.append(rpc(CHU, "create_order_with_lines", _don("22222222-2222-2222-2222-000000000002", K2, {"subtotal": 340000, "vat": 7200, "total": 347200},
		[_dd("SP1", "thung", 1, 250000, 24, "0"), _dd("SP2", "goi", 20, 4500, 1, "0.08")], nv=NV + "nv.binh@sobc.vn"), g(20, 52, 40), nhan="DH-0002",
		ghi_chu="Chủ lập hộ NV Bình (sales_user_id)"))
	B.append(rpc(CHU, "create_order_with_lines", _don("22222222-2222-2222-2222-000000000003", K2, {"subtotal": 720000, "vat": 0, "total": 720000},
		[_dd("SP1", "thung", 3, 240000, 24, "0")], nv=NV + "nv.binh@sobc.vn"), g(20, 52, 41), nhan="DH-0003"))
	B.append(rpc(AN, "create_order_with_lines", _don("22222222-2222-2222-2222-000000000004", K1, {"subtotal": 240000, "vat": 0, "total": 240000},
		[_dd("SP1", "thung", 1, 240000, 24, "0")]), g(20, 52, 42), nhan="DH-0004"))
	B.append(_xuat(CHU, "DH-0002", "2026-11-10", "10000", g(20, 52, 43), "HD-0002"))
	B.append(_xuat(CHU, "DH-0003", "2026-11-15", "0", g(20, 52, 44), "HD-0003"))
	B.append(_xuat(CHU, "DH-0004", "2026-10-31", "0", g(20, 52, 45), "HD-0004"))
	for hd, moc in (("HD-0001", "2026-11-03T09:00:00+07:00"), ("HD-0002", "2026-11-10T09:00:00+07:00"), ("HD-0003", "2026-11-15T09:00:00+07:00"),
			("HD-0004", "2026-11-01T06:30:00+07:00")):
		B.append(_lui_gio_xuat(hd, moc, g(20, 52, 50)))
	B.append(rpc(BINH, "create_return_with_lines", {"p_head": {"customer_id": K2, "invoice_id": "@hd:HD-0002", "reason": "damaged", "status": "draft"},
		"p_lines": [_dt("SP2", "goi", 4, 4500, 0.08)]}, g(20, 53, 15), nhan="PT-0002"))
	B.append(rpc(AN, "create_return_with_lines", {"p_head": {"customer_id": K3, "reason": "refused", "status": "draft"},
		"p_lines": [_dt("SP1", "thung", 1, 240000, 0)]}, g(20, 53, 16), nhan="PT-0003"))
	B.append(rpc(AN, "create_return_with_lines", {"p_head": {"customer_id": K1, "reason": "expired", "status": "draft"},
		"p_lines": [_dt("SP1", "lon", 2, 10000, 0)]}, g(20, 53, 17), nhan="PT-0004"))
	B.append(rpc(AN, "create_return_with_lines", {"p_head": {"customer_id": K1, "invoice_id": "@hd:HD-0001", "reason": "wrong_item", "status": "draft"},
		"p_lines": [_dt("SP1", "lon", 6, 10000, 0)]}, g(20, 53, 18), nhan="PT-0005"))
	B.append(rpc(BINH, "create_return_with_lines", {"p_head": {"customer_id": K2, "reason": "expired", "status": "draft"},
		"p_lines": [_dt("SP2", "goi", 2, 5000, 0.08)]}, g(20, 53, 19), nhan="PT-0006"))
	B.append(rpc(CHU, "complete_return", {"p_return_id": "@pt:PT-0001", "p_zone": "sale", "p_ngay": "2026-11-05"}, g(20, 53, 20),
		ghi_chu="phiếu tự sinh: Chủ nhập kho chọn ngày 05/11 (phiếu nhập ghi sổ 05/11 12:00 VN)"))
	B.append(rpc(CHU, "complete_return", {"p_return_id": "@pt:PT-0002", "p_zone": "sale", "p_ngay": "2026-11-12"}, g(20, 53, 21),
		cho_loi="NGAY_NHAP_CHI_TU_SINH", ghi_chu="kb/04_tra.sql dừng có chủ ý ở đây: phiếu tự lập không chọn được ngày nhập (§5.0) — bước LỖI, không đổi sổ"))
	B.append(cong(CHU, "returns", "update", g(20, 53, 25), gia_tri={"return_date": "2026-11-12"}, loc={"id": "@pt:PT-0002"}, ly_do=LY_DO_NGAY_PHIEU))
	B.append(cong(CHU, "returns", "update", g(20, 53, 26), gia_tri={"return_date": "2026-11-14"}, loc={"id": "@pt:PT-0003"}, ly_do=LY_DO_NGAY_PHIEU))
	B.append(cong(CHU, "returns", "update", g(20, 53, 27), gia_tri={"return_date": "2026-11-20"}, loc={"id": "@pt:PT-0005"}, ly_do=LY_DO_NGAY_PHIEU))
	B.append(cong(CHU, "returns", "update", g(20, 53, 28), gia_tri={"return_date": "2026-12-02"}, loc={"id": "@pt:PT-0006"}, ly_do=LY_DO_NGAY_PHIEU))
	B.append(rpc(CHU, "complete_return", {"p_return_id": "@pt:PT-0002", "p_zone": "sale"}, g(20, 53, 33)))
	B.append(rpc(CHU, "complete_return", {"p_return_id": "@pt:PT-0003", "p_zone": "sale"}, g(20, 53, 34)))
	B.append(rpc(CHU, "complete_return", {"p_return_id": "@pt:PT-0005", "p_zone": "sale"}, g(20, 53, 35)))
	B.append(rpc(CHU, "cancel_return", {"p_return_id": "@pt:PT-0005", "p_reason": "khach lay lai"}, g(20, 53, 36),
		ghi_chu="nppsale sinh phiếu xuất 'Đảo phiếu trả …' giá 0 (Frappe: huỷ chứng từ nhập lại — docstatus 2)"))
	B.append(rpc(CHU, "complete_return", {"p_return_id": "@pt:PT-0006", "p_zone": "sale"}, g(20, 53, 37),
		ghi_chu="ngày phiếu 02/12 ≠ hôm nay → credited_at 02/12 12:00; phiếu nhập lại ghi sổ LÚC BẤM (16/11)"))
	B.append(rpc(CHU, "cancel_invoice", {"p_invoice_id": "@hd:HD-0003", "p_reason": "khach doi y"}, g(20, 53, 38), nhan="HD-0003 (huỷ)"))
	for ma, ly, sp, sl, ghi in (("XK-HUY-01", "damaged", "SP3", 10, "Xuất huỷ hàng hỏng"), ("XK-MAU-02", "sample", "SP2", 5, "Xuất hàng mẫu")):
		B.append(cong(CHU, "stock_entries", "insert", g(20, 53, 50), gia_tri={"id": "@pk:" + ma, "org_id": "@org", "entry_code": ma, "type": "export",
			"status": "draft", "created_by": NV + "chu@sobc.vn", "notes": ghi, "issue_reason": ly, "warehouse_zone": "sale"},
			ly_do="phiếu xuất kho lẻ NHÁP lập qua bảng như màn /inventory/stock-issue (kb/06_xuat_kho.sql)", frappe="cổng stock_entries ghi nháp xuất lẻ (P4)"))
		B.append(cong(CHU, "stock_entry_lines", "insert", g(20, 53, 50), gia_tri={"entry_id": "@pk:" + ma, "product_id": "@sp:" + sp, "unit_name": "goi",
			"quantity": sl, "qty_in_base_uom": sl, "qty_in_transaction_uom": sl, "transaction_uom": "goi", "conversion_factor_snapshot": 1},
			ly_do="dòng phiếu xuất kho lẻ nháp (kb/06)", frappe="cổng stock_entry_lines ghi nháp (P4)"))
		B.append(rpc(CHU, "post_stock_issue", {"p_entry_id": "@pk:" + ma}, g(20, 53, 51), nhan=ma,
			ghi_chu="nppsale: dòng phiếu giữ unit_cost 0 (giá thật chỉ ở stock_line_consumptions) — Q2 chốt chéo P4: Frappe cổng / NGUON_DONG_XUAT cũng 0"))
	B.append(may_chu("XK-HUY-01 posted_at = 18/11 10:00 VN; XK-MAU-02 posted_at = 01/12 00:00 VN (= 30/11 17:00 UTC)",
		"UPDATE stock_entries SET posted_at = '2026-11-18T10:00:00+07:00' WHERE entry_code = 'XK-HUY-01'; "
		"UPDATE stock_entries SET posted_at = '2026-12-01T00:00:00+07:00' WHERE entry_code = 'XK-MAU-02';", g(20, 53, 55),
		ly_do="kb/06_xuat_kho.sql: post_stock_issue ghi sổ lúc bấm — dời về giờ ghi sổ của kịch bản (biên tháng + múi giờ)",
		frappe="ghim đồng hồ bước post_stock_issue: XK-HUY-01 lúc 18/11 10:00, XK-MAU-02 lúc 01/12 00:00 (posting_date 01/12)"))
	B.append(rpc(CHU, "create_cash_receipt", {"p": {"customer_id": K1, "method": "cash", "receipt_date": "2026-11-20",
		"lines": [{"receivable_id": "@no:hd:HD-0001", "amount": 200000}]}}, g(20, 54, 0), nhan="phiếu thu 200.000 HĐ1"))
	B.append(cong(CHU, "receivables", "update", g(20, 54, 10), gia_tri={"status": "overdue"}, loc={"id": "@no:hd:HD-0004"},
		ly_do="nút 'Đánh dấu quá hạn' — cổng receivables update status (bước đặc tả ghi bằng quyền máy chủ; trình duyệt cũng được: trigger khoá không chặn status)",
		frappe="cổng receivables update status = 'overdue' (P3d)"))
	B.append(rpc(AN, "create_order_with_lines", _don("22222222-2222-2222-2222-000000000005", K3, {"subtotal": 240000, "vat": 0, "total": 240000},
		[_dd("SP1", "thung", 1, 240000, 24, "0")], tra={"reason": "near_expiry"},
		dong_tra=[_dt("SP1", "lon", 2, 10000, 0)]), g(20, 59, 34), nhan="DH-0005"))
	B.append(_xuat(CHU, "DH-0005", "2026-11-20", "0", g(20, 59, 35), "HD-0005"))
	B.append(_lui_gio_xuat("HD-0005", "2026-11-20T09:00:00+07:00", g(20, 59, 40)))
	return B


def buoc_bien_the() -> dict:
	"""Bộ con = bản sao S1 + bước riêng (§5.0: npp_s2 … npp_s7) + bộ ◇ của nhóm E (S8 … S11)."""
	ky = {"p_invoice_id": "@hd:HD-0002", "p": {"invoice_date": "2026-11-10", "discount": "10000", "payment_terms": "COD", "lines": "@dong_sua:HD-0002"}}
	return {
		"S2": ("Sửa HĐ2 (reissue): giữ ngày 10/11, giảm đơn 10.000, COD, bánh 20 → 18 gói", [
			rpc(CHU, "reissue_invoice", ky, g(21, 0, 22), doi={"SP2/goi": 18}, nhan="HD-0002-1",
				ghi_chu="lines = dòng hiện có của HĐ2, SL bánh 18 (kb/08_sua_hd2.sql)")]),
		"S3": ("Gán người HĐ5 sang NV Bình", [
			rpc(CHU, "assign_doc_seller", {"p_kind": "invoice", "p_id": "@hd:HD-0005", "p_user": NV + "nv.binh@sobc.vn"}, g(21, 1, 0))]),
		"S4": ("Phiếu chỉ có hàng đổi: ĐH6 (NV An, K1) 5 gói kẹo + ĐỔI 4 gói kẹo → HĐ6 25/11 + PT-0008 tự sinh 0 đ nhập kho lúc bấm", [
			rpc(AN, "create_order_with_lines", _don("22222222-2222-2222-2222-000000000006", K1, {"subtotal": 10000, "vat": 0, "total": 10000},
				[_dd("SP3", "goi", 5, 2000, 1, "0")], tra={"reason": "damaged"},
				dong_tra=[_dt("SP3", "goi", 4, 2000, 0, doi=True, tien=8000)]), g(21, 2, 9), nhan="DH-0006"),
			_xuat(CHU, "DH-0006", "2026-11-25", "0", g(21, 2, 10), "HD-0006"),
			_lui_gio_xuat("HD-0006", "2026-11-25T09:00:00+07:00", g(21, 2, 12)),
			rpc(CHU, "complete_return", {"p_return_id": "@pt:PT-0008", "p_zone": "sale"}, g(21, 2, 17),
				ghi_chu="phiếu tự sinh 0 đ — nhập kho lúc bấm 16/11 (ngày khác ngày HĐ)")]),
		"S5": ("Huỷ HĐ5 (phiếu tự sinh PT-0007 đang Chờ xử lý)", [
			rpc(CHU, "cancel_invoice", {"p_invoice_id": "@hd:HD-0005", "p_reason": "khach tra ca don"}, g(21, 2, 30))]),
		"S6": ("Bán chéo K3: NV An lập đơn K3 3 gói kẹo (hàng chưa gán công ty) → HĐ 22/11", [
			rpc(AN, "create_order_with_lines", _don("22222222-2222-2222-2222-000000000007", K3, {"subtotal": 6000, "vat": 0, "total": 6000},
				[_dd("SP3", "goi", 3, 2000, 1, "0")]), g(21, 3, 28), nhan="DH-0006"),
			_xuat(CHU, "DH-0006", "2026-11-22", "0", g(21, 3, 29), "HD-0006")]),
		"S7": ("Huỷ nhập kho phiếu tự sinh đã nhập (PT-0001)", [
			rpc(CHU, "cancel_return", {"p_return_id": "@pt:PT-0001", "p_reason": "nhap nham kho"}, g(21, 10, 40),
				ghi_chu="phiếu tự sinh đã nhập kho → đảo kho, phiếu về Chờ xử lý, nợ giữ nguyên")]),
		"S8": ("◇ VB-E07: phiếu tự lập K1 không gắn HĐ (trả 2 lon + ĐỔI 1 gói kẹo), ngày phiếu 12/11, Hoàn thành lúc bấm 15/11", [
			rpc(AN, "create_return_with_lines", {"p_head": {"customer_id": K1, "reason": "damaged", "status": "draft"},
				"p_lines": [_dt("SP1", "lon", 2, 10000, 0), _dt("SP3", "goi", 1, 2000, 0, doi=True)]}, g(9, 50, 0, "2026-11-15"), nhan="PT-0008"),
			cong(AN, "returns", "update", g(9, 51, 0, "2026-11-15"), gia_tri={"return_date": "2026-11-12"}, loc={"id": "@pt:PT-0008"}, ly_do=LY_DO_NGAY_PHIEU),
			rpc(CHU, "complete_return", {"p_return_id": "@pt:PT-0008", "p_zone": "sale"}, g(10, 0, 0, "2026-11-15"),
				ghi_chu="đồng hồ ghim 15/11 10:00 — nppsale phiếu nhập lại ghi sổ lúc bấm; Frappe tờ ghi có HDT- posting_date 15/11")]),
		"S8b": ("◇ VB-E07 (sau): S8 + sửa ngày phiếu → 10/11 khi phiếu đang Hoàn thành", [
			cong(CHU, "returns", "update", g(10, 5, 0, "2026-11-15"), gia_tri={"return_date": "2026-11-10"}, loc={"id": "@pt:PT-0008"},
				ly_do="đổi ngày chứng từ phiếu Hoàn thành — trigger khoá cho sửa return_date (ghi chú / lý do / ngày / người); mốc credited_at đi theo (mig 188)",
				frappe="cổng returns update return_date của phiếu completed (P3c) — hook tính lại ngay_tru_doanh_so")]),
		"S9": ("◇ VB-E08: trả NCC Cty Bánh 5 gói SP2 (lô L2 giá 3.000) ghi sổ 19/11", [
			cong(CHU, "supplier_returns", "insert", g(10, 0, 0, "2026-11-19"), gia_tri={"id": "@ptncc:TRNCC-1", "org_id": "@org",
				"supplier_id": "@ncc:Cty Banh", "warehouse_zone": "sale", "status": "draft", "subtotal": 15000, "vat": 0, "total": 15000,
				"created_by": NV + "chu@sobc.vn"}, ly_do="phiếu trả NCC NHÁP qua bảng như màn /pos/tra-ncc", frappe="cổng supplier_returns ghi nháp (P4)"),
			cong(CHU, "supplier_return_lines", "insert", g(10, 0, 0, "2026-11-19"), gia_tri={"return_id": "@ptncc:TRNCC-1", "product_id": "@sp:SP2",
				"unit_name": "goi", "quantity": 5, "unit_price": 3000, "line_total": 15000, "conversion_factor": 1, "sort_order": 1},
				ly_do="dòng phiếu trả NCC nháp", frappe="cổng supplier_return_lines ghi nháp (P4)"),
			rpc(CHU, "complete_supplier_return", {"p_return_id": "@ptncc:TRNCC-1"}, g(10, 0, 5, "2026-11-19"),
				ghi_chu="dòng phiếu xuất trả NCC mang GIÁ LÔ 3.000 (Frappe: giá dòng trả NCC = |Σ SVD| / |Σ SL| của sổ kho — ĐT-KM S2)")]),
		"S10": ("◇ VB-E10: nợ đầu kỳ K2 1.000.000 + nợ HĐ cũ K1 500.000 (ngày 05/11)", [
			cong(CHU, "receivables", "insert", g(8, 0, 0, "2026-11-05"), gia_tri={"org_id": "@org", "customer_id": K2, "amount": 1000000, "paid": 0,
				"opening_balance": True, "due_date": "2026-11-05", "status": "open", "note": "No dau ky"},
				ly_do="nợ đầu kỳ chưa thu — màn công nợ ghi thẳng (mig 214 cho phép)", frappe="ghi_no_dau_ky K2 1.000.000 (tờ DK- ngày 05/11)"),
			cong(CHU, "receivables", "insert", g(8, 1, 0, "2026-11-05"), gia_tri={"org_id": "@org", "customer_id": K1, "amount": 500000, "paid": 0,
				"opening_balance": True, "due_date": "2026-11-05", "status": "open", "note": "HD cu H3"},
				ly_do="nppsale KHÔNG có tờ HĐ cũ is_opening (khái niệm P8) — công nợ của nó = một dòng nợ không HĐ; giữ số công nợ như tờ H3",
				frappe="tờ HĐ cũ H3: Sales Invoice is_opening = 'Yes' 500.000 cho K1, posting_date 05/11, giữ mã HĐ cũ (P8 — công cụ nhập NPP LS)")]),
		"S11": ("◇ VB-E11: phiếu thu 50.000 HĐ1 lập lúc 23:30 VN ngày 30/11", [
			rpc(CHU, "create_cash_receipt", {"p": {"customer_id": K1, "method": "cash", "receipt_date": "2026-11-30",
				"lines": [{"receivable_id": "@no:hd:HD-0001", "amount": 50000}]}}, g(23, 30, 0, "2026-11-30"),
				ghi_chu="đồng hồ ghim 30/11 23:30 VN → payments.collected_at = 2026-11-30T23:30+07:00")]),
	}


# bộ con: mã → bộ gốc (bản sao) — thứ tự dựng
GOC_BIEN_THE = {"S2": "S1", "S3": "S1", "S4": "S1", "S5": "S1", "S6": "S1", "S7": "S1", "S8": "S1", "S8b": "S8", "S9": "S1", "S10": "S1",
	"S11": "S1"}


# ================================================================================================ chạy bước
CO_PHIEN = ("npp.don_dong_215", "npp.duyet_anh_diem_ban", "npp.giao_cong_no", "npp.giu_phieu_tu_lap", "npp.he_so_tu_hd",
	"npp.reissue_chuyen_thu", "npp.reissue_nguoi_no", "npp.reissue_stash", "npp.tra_da_nhap_210", "npp.via_rpc")  # = tools/vang_phieu_tra.py
DAT_LAI_CO = " ".join(f"PERFORM set_config('{c}', '', true);" for c in CO_PHIEN)
_RE_DONG = re.compile(r"^@(don|hd|pt|no|dong_xuat|dong_sua):")


def ma_tinh_s() -> dict:
	"""Chỗ giữ TĨNH của Sổ BC (danh mục hạt giống) → uuid."""
	m = {"@org": ORG_S}
	for i, _t, _v, email in NGUOI_S.values():
		m["@nv:" + email] = i
	for i, _t, _c, sdt, _tu in KHACH_S.values():
		m["@kh:" + sdt] = i
	for sku, (i, *_r) in HANG_S.items():
		m["@sp:" + sku] = i
	for i, ten in NCC_S.values():
		m["@ncc:" + ten] = i
	for ma, (i, *_r) in LO_S.items():
		m["@lo:" + ma] = i
	for ma, i in PK_TAY_S.items():
		m["@pk:" + ma] = i
	for ma, i in PTNCC_S.items():
		m["@ptncc:" + ma] = i
	return m


def giai_tinh(v, m: dict):
	if isinstance(v, dict):
		return {a: giai_tinh(b, m) for a, b in v.items()}
	if isinstance(v, list):
		return [giai_tinh(x, m) for x in v]
	if isinstance(v, str) and v.startswith("@") and not _RE_DONG.match(v):
		if v not in m:
			raise SystemExit(f"chỗ giữ lạ: {v}")
		return m[v]
	return v


def _dong(v, ra: set):
	"""Gom chỗ giữ ĐỘNG (chứng từ sinh ở bước trước) trong giá trị ghi thẳng."""
	if isinstance(v, dict):
		for b in v.values():
			_dong(b, ra)
	elif isinstance(v, list):
		for x in v:
			_dong(x, ra)
	elif isinstance(v, str) and _RE_DONG.match(v):
		ra.add(v)


def _gt_sql(v) -> str:
	if v is None:
		return "NULL"
	if isinstance(v, bool):
		return "true" if v else "false"
	if isinstance(v, (int, float, decimal.Decimal)):
		return str(v)
	if isinstance(v, str) and _RE_DONG.match(v):
		return f"(v_ids ->> {_lit(v)})::uuid"
	return _lit(v)


GOI_RPC = {
	"create_order_with_lines": "SELECT to_jsonb(t) INTO v_tra FROM public.create_order_with_lines(v_p->'p') t;",
	"post_invoice": "SELECT to_jsonb(t) INTO v_tra FROM public.post_invoice(v_p->'p') t;",
	"reissue_invoice": "SELECT to_jsonb(t) INTO v_tra FROM public.reissue_invoice((v_p->>'p_invoice_id')::uuid, v_p->'p') t;",
	"create_return_with_lines": "v_tra := jsonb_build_object('return_id', public.create_return_with_lines(v_p->'p_head', v_p->'p_lines'));",
	"complete_return": "SELECT jsonb_agg(to_jsonb(t)) INTO v_tra FROM public.complete_return((v_p->>'p_return_id')::uuid, v_p->>'p_zone') t;",
	"complete_return/3": "SELECT jsonb_agg(to_jsonb(t)) INTO v_tra FROM public.complete_return((v_p->>'p_return_id')::uuid, v_p->>'p_zone', (v_p->>'p_ngay')::date) t;",
	"cancel_return": "PERFORM public.cancel_return((v_p->>'p_return_id')::uuid, v_p->>'p_reason');",
	"cancel_invoice": "SELECT jsonb_agg(to_jsonb(t)) INTO v_tra FROM public.cancel_invoice((v_p->>'p_invoice_id')::uuid, v_p->>'p_reason') t;",
	"assign_doc_seller": "PERFORM public.assign_doc_seller(v_p->>'p_kind', (v_p->>'p_id')::uuid, (v_p->>'p_user')::uuid);",
	"create_cash_receipt": "v_tra := jsonb_build_object('receipt_id', public.create_cash_receipt(v_p->'p'));",
	"post_stock_issue": "v_tra := jsonb_build_object('entry_id', public.post_stock_issue((v_p->>'p_entry_id')::uuid));",
	"complete_supplier_return": "v_tra := jsonb_build_object('return_id', public.complete_supplier_return((v_p->>'p_return_id')::uuid));",
}


def sql_buoc(bo: str, so: int, b: dict, nguoi: dict, m: dict) -> str:
	sub = "" if b["nguoi"] == "MAY_CHU" else nguoi[b["nguoi"]][0]
	vai = "" if b["nguoi"] == "MAY_CHU" else "EXECUTE 'SET LOCAL ROLE authenticated';"
	ids: set = set()
	if b["loai"] == "rpc":
		ten = b["rpc"] + ("/3" if b["rpc"] == "complete_return" and "p_ngay" in b["tham_so"] else "")
		goi = GOI_RPC[ten]
		p = _j(giai_tinh(b["tham_so"], m))
		doi = _j(b["doi_sl"]) if b.get("doi_sl") else "NULL"
		than = f"v_p := public._vang_giai({p}::jsonb, {doi}::jsonb);\n    {vai}\n    {goi}"
	elif b["loai"] == "ghi_cong":
		gt = giai_tinh(b.get("gia_tri") or {}, m)
		loc = giai_tinh(b.get("loc") or {}, m)
		_dong(gt, ids)
		_dong(loc, ids)
		if b["hanh_dong"] == "insert":
			cau = f"INSERT INTO public.{b['bang']} ({', '.join(gt)}) VALUES ({', '.join(_gt_sql(x) for x in gt.values())})"
		else:
			dat = ", ".join(f"{k} = {_gt_sql(x)}" for k, x in gt.items())
			cau = f"UPDATE public.{b['bang']} SET {dat} WHERE " + " AND ".join(f"{k} = {_gt_sql(x)}" for k, x in loc.items())
		than = (f"{vai}\n    EXECUTE {_lit(cau)} USING v_ids;\n    GET DIAGNOSTICS v_n = ROW_COUNT;\n"
			"    IF v_n <> 1 THEN RAISE EXCEPTION 'VANG_SO_DONG: % dòng', v_n; END IF;\n    v_tra := jsonb_build_object('so_dong', v_n);")
		than = than.replace("v_ids ->>", "$1 ->>")
	else:  # ghi_may_chu
		than = "\n    ".join(f"EXECUTE {_lit(c.strip())};" for c in b["sql"].split(";") if c.strip())
	dong = f"v_ids := public._vang_giai({_j({k: k for k in sorted(ids)})}::jsonb);" if ids else ""
	return f"""SELECT set_config('vang.gio', {_lit(b['gio'])}, false);
DO $vb$
DECLARE v_p jsonb; v_ids jsonb := '{{}}'::jsonb; v_tra jsonb; v_n bigint;
BEGIN
  BEGIN
    {DAT_LAI_CO}
    PERFORM set_config('request.jwt.claim.sub', {_lit(sub)}, true);
    {dong}
    {than}
    EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';
    EXECUTE 'RESET ROLE';
    INSERT INTO public._vang_buoc VALUES ({_lit(bo)}, {so}, true, v_tra, NULL, NULL);
  EXCEPTION WHEN OTHERS THEN
    INSERT INTO public._vang_buoc VALUES ({_lit(bo)}, {so}, false, NULL, SQLSTATE, SQLERRM);
  END;
END $vb$;"""


def chay_bo_s(bo: str, buoc: list[dict], db: str):
	m = ma_tinh_s()
	sql = [sql_buoc(bo, i + 1, b, NGUOI_S, m) for i, b in enumerate(buoc)]
	psql(db, "\n".join(sql))
	kq = psql_json(db, f"SELECT COALESCE(json_agg(json_build_object('so', so, 'ok', ok, 'tra', tra, 'ma_loi', ma_loi, 'loi', loi) ORDER BY so), '[]') "
		f"FROM public._vang_buoc WHERE bo = {_lit(bo)};")
	for b, k in zip(buoc, kq, strict=True):
		ok_mong = not b.get("cho_loi")
		if k["ok"] != ok_mong or (b.get("cho_loi") and b["cho_loi"] not in (k["loi"] or "")):
			raise SystemExit(f"bộ {bo} bước {k['so']} ({b.get('rpc') or b.get('bang') or b.get('mo_ta')}): {k}")
	return kq


def dung_bo_s() -> dict:
	"""S1 từ khung (hạt giống + bước), S2 … S11 = bản sao bộ gốc + bước riêng. Trả {bo: (mô tả, bước, kết quả bước)}."""
	ra = {}
	psql("postgres", f"CREATE DATABASE {TIEN_TO}s1 TEMPLATE {TIEN_TO}khung;")
	psql(f"{TIEN_TO}s1", f"SELECT set_config('vang.gio', {_lit(GIO_SEED_S)}, false);\n" + sql_seed_s())
	b1 = buoc_s1()
	ra["S1"] = ("Sổ BC — §5.0 mục 1 (npp_s1 của bước đặc tả)", b1, chay_bo_s("S1", b1, f"{TIEN_TO}s1"))
	for bo, (mo_ta, bs) in buoc_bien_the().items():
		db = f"{TIEN_TO}{bo.lower()}"
		psql("postgres", f"CREATE DATABASE {db} TEMPLATE {TIEN_TO}{GOC_BIEN_THE[bo].lower()};")
		ra[bo] = (mo_ta, bs, chay_bo_s(bo, bs, db))
	return ra


def dung_bo_khac():
	psql("postgres", f"CREATE DATABASE {TIEN_TO}n TEMPLATE {TIEN_TO}khung;")
	with open(NEN_N_SQL, encoding="utf-8") as f:
		psql(f"{TIEN_TO}n", f"SELECT set_config('vang.gio', {_lit(GIO_NAP_N)}, false);\n" + f.read())
	psql("postgres", f"CREATE DATABASE {TIEN_TO}e2e TEMPLATE {TIEN_TO}khung;")
	psql(f"{TIEN_TO}e2e", f"SELECT set_config('vang.gio', {_lit(GIO_NAP_E)}, false);\n" + sql_e2e())


# ================================================================================================ đọc (lời gọi của kịch bản)
# hàm → (tham số [(tên, kiểu Postgres)], dạng kết quả: "jsonb" | "bang" (RETURNS TABLE — giữ thứ tự hàm) | "so" (số trơn))
HAM = {
	"bao_cao_so_ban": ([("p_tu", "date"), ("p_den", "date")], "jsonb"),
	"bao_cao_ton_kho": ([("p_tu", "date"), ("p_den", "date")], "jsonb"),
	"bao_cao_cong_no": ([("p_tu_thu", "date"), ("p_tu_90", "date")], "jsonb"),
	"dashboard_summary": ([("p_period_start", "date")], "bang"),
	"dashboard_channel_revenue": ([("p_period_start", "date")], "bang"),
	"dashboard_top_customers": ([("p_period_start", "date"), ("p_limit", "integer")], "bang"),
	"finance_pnl": ([("p_from", "date"), ("p_to", "date")], "bang"),
	"finance_cash_flow": ([("p_from", "date"), ("p_to", "date")], "bang"),
	"finance_balance_sheet": ([("p_as_of", "date")], "bang"),
	"hang_khach_da_lay": ([("p_nv", "uuid"), ("p_khach", "uuid[]"), ("p_tu", "date"), ("p_tuyen", "text[]")], "jsonb"),
	"my_sales_target": ([], "so"),
	"payables_summary": ([("p_since", "timestamptz")], "bang"),
	"payables_by_supplier": ([], "bang"),
	"receivables_summary": ([], "bang"),
	"receivables_by_customer": ([], "bang"),
	"receivables_by_rep": ([], "bang"),
	"stock_value_summary": ([], "bang"),
	"cash_received_total": ([("p_from", "date"), ("p_to", "date")], "so"),
}
# Đọc BẢNG qua quyền trình duyệt (RLS) — như câu của giao diện qua cổng bảng (bên Frappe: nppsale.cong.truy_van.doc dưới đúng người)
DOC_BANG = {
	"v_hoa_don_con_lai": ("SELECT COALESCE(jsonb_agg(jsonb_build_object('id', v.id, 'status', v.status, 'total', v.total, 'con_lai', v.con_lai) "
		"ORDER BY v.invoice_code), '[]') FROM public.v_hoa_don_con_lai v", "cổng v_hoa_don_con_lai: select id, status, total, con_lai"),
	"receivables": ("SELECT COALESCE(jsonb_agg(jsonb_build_object('id', r.id, 'customer_id', r.customer_id, 'sales_user_id', r.sales_user_id, "
		"'invoice_id', r.invoice_id, 'return_id', r.return_id, 'amount', r.amount, 'paid', r.paid, 'status', r.status, 'due_date', r.due_date) "
		"ORDER BY r.created_at, r.id), '[]') FROM public.receivables r", "cổng receivables: select id, customer_id, sales_user_id, invoice_id, return_id, "
		"amount, paid, status, due_date"),
	"returns": ("SELECT COALESCE(jsonb_agg(jsonb_build_object('id', r.id, 'status', r.status, 'invoice_id', r.invoice_id, 'credit_note_amount', "
		"r.credit_note_amount, 'return_date', r.return_date, 'revenue_date', r.revenue_date, 'credited_at', r.credited_at, 'sales_user_id', r.sales_user_id) "
		"ORDER BY r.return_code), '[]') FROM public.returns r", "cổng returns: select id, status, invoice_id, credit_note_amount, return_date, revenue_date, "
		"credited_at, sales_user_id"),
	"sales_orders": ("SELECT COALESCE(jsonb_agg(jsonb_build_object('id', o.id, 'status', o.status, 'sales_user_id', o.sales_user_id) ORDER BY o.order_code), "
		"'[]') FROM public.sales_orders o", "cổng sales_orders: select id, status, sales_user_id"),
	"sales_invoices": ("SELECT COALESCE(jsonb_agg(jsonb_build_object('id', i.id, 'invoice_date', i.invoice_date, 'status', i.status, 'subtotal', i.subtotal, "
		"'vat', i.vat, 'total', i.total, 'sales_user_id', i.sales_user_id) ORDER BY i.invoice_code), '[]') FROM public.sales_invoices i",
		"cổng sales_invoices: select id, invoice_date, status, subtotal, vat, total, sales_user_id"),
	"payments": ("SELECT COALESCE(jsonb_agg(jsonb_build_object('id', p.id, 'amount', p.amount, 'method', p.method, 'collected_at', p.collected_at) "
		"ORDER BY p.collected_at, p.id), '[]') FROM public.payments p", "cổng payments: select id, amount, method, collected_at"),
}


def goi(ham, nguoi, **ts):
	"""Một lời gọi đọc: hàm RPC (tham số đặt tên) hoặc bảng cổng ("bang:<tên>", tham số "loc" = [(cột, toán tử, giá trị)])."""
	o = {"ham": ham, "nguoi": nguoi}
	if ts:
		o["tham_so"] = ts
	return o


def _gt_doc(v, kieu: str, m: dict) -> str:
	if v is None:
		return f"NULL::{kieu}"
	if isinstance(v, list):
		return "ARRAY[" + ", ".join(_lit(m.get(x, x)) if isinstance(x, str) else str(x) for x in v) + f"]::{kieu}"
	if isinstance(v, str):
		return f"{_lit(m.get(v, v))}::{kieu}"
	return f"{v}::{kieu}"


def bieu_thuc_doc(c: dict, m: dict) -> str:
	ts = c.get("tham_so") or {}
	if c["ham"].startswith("bang:"):
		sql, _ = DOC_BANG[c["ham"][5:]]
		loc = ts.get("loc") or []
		if loc:
			op = {"eq": "=", "gte": ">=", "lte": "<=", "gt": ">", "lt": "<"}
			dk = " AND ".join(f"{cot} {op[o]} {_lit(m.get(x, x))}" for cot, o, x in loc)
			sql = sql + f" WHERE {dk}"
		return f"({sql})"
	thams, dang = HAM[c["ham"]]
	da = [f"{ten} => {_gt_doc(ts[ten], kieu, m)}" for ten, kieu in thams if ten in ts]
	goi_ = f"public.{c['ham']}({', '.join(da)})"
	if dang == "jsonb":
		return f"(SELECT {goi_})"
	if dang == "so":
		return f"(SELECT to_jsonb({goi_}))"
	return f"(SELECT COALESCE(jsonb_agg(to_jsonb(t) - 'ordinality' ORDER BY t.ordinality), '[]'::jsonb) FROM {goi_} WITH ORDINALITY t)"


def sql_doc_kich_ban(ma: str, cs: list[dict], nguoi: dict, m: dict, gio: str, bien_the: str | None) -> str:
	khoi = []
	for so, c in enumerate(cs):
		if c["ham"].startswith("ts:"):
			continue
		sub = nguoi[c["nguoi"]][0] if c["nguoi"] in nguoi else c["nguoi"]
		khoi.append(f"""
    BEGIN
      PERFORM set_config('vang.gio', {_lit(c.get('gio') or gio)}, true);
      PERFORM set_config('request.jwt.claim.sub', {_lit(sub)}, true);
      EXECUTE 'SET LOCAL ROLE authenticated';
      v_tra := {bieu_thuc_doc(c, m)};
      EXECUTE 'RESET ROLE';
      v_kq := v_kq || jsonb_build_array(jsonb_build_object('so', {so}, 'ok', true, 'kq', v_tra));
    EXCEPTION WHEN OTHERS THEN
      v_kq := v_kq || jsonb_build_array(jsonb_build_object('so', {so}, 'ok', false, 'ma_loi', SQLSTATE, 'loi', SQLERRM));
    END;""")
	bt = ""
	if bien_the:
		bt = (f"PERFORM set_config('vang.gio', {_lit(gio)}, true);\n    EXECUTE 'SET LOCAL session_replication_role = replica';\n    "
			+ "\n    ".join(f"EXECUTE {_lit(x.strip())};" for x in bien_the.split(";") if x.strip())
			+ "\n    EXECUTE 'SET LOCAL session_replication_role = origin';")
	return f"""DO $vd$
DECLARE v_kq jsonb := '[]'::jsonb; v_tra jsonb;
BEGIN
  BEGIN
    {bt}{''.join(khoi)}
    RAISE EXCEPTION USING ERRCODE = 'ZZ999';
  EXCEPTION WHEN SQLSTATE 'ZZ999' THEN NULL;
  END;
  INSERT INTO public._vang_doc SELECT {_lit(ma)}, (x->>'so')::int, (x->>'ok')::boolean, x->'kq', x->>'ma_loi', x->>'loi'
    FROM jsonb_array_elements(v_kq) x;
END $vd$;"""


def ban_do_id(db: str) -> dict:
	"""uuid → khoá nghiệp vụ của chứng từ sinh trong DB (mã đơn / HĐ / phiếu trả, dòng HĐ / dòng đơn, dòng nợ, phiếu kho, phiếu thu)."""
	return psql_json(db, r"""SELECT COALESCE(jsonb_object_agg(x.id, x.k), '{}') FROM (
  SELECT id::text AS id, order_code AS k FROM sales_orders
  UNION ALL SELECT id::text, invoice_code FROM sales_invoices
  UNION ALL SELECT id::text, return_code FROM returns WHERE return_code IS NOT NULL
  UNION ALL SELECT l.id::text, si.invoice_code || '/' || p.sku || '/' || l.unit_name || CASE WHEN l.is_exchange THEN '/doi' ELSE '' END
    FROM sales_invoice_lines l JOIN sales_invoices si ON si.id = l.invoice_id JOIN products p ON p.id = l.product_id
  UNION ALL SELECT l.id::text, so.order_code || '/' || p.sku || '/' || l.unit_name
    FROM sales_order_lines l JOIN sales_orders so ON so.id = l.order_id JOIN products p ON p.id = l.product_id
  UNION ALL SELECT rc.id::text, 'no:' || COALESCE(si.invoice_code, r.return_code, 'dk:' || c.phone || ':' || trim(to_char(rc.amount, 'FM999999999990')))
    FROM receivables rc LEFT JOIN sales_invoices si ON si.id = rc.invoice_id LEFT JOIN returns r ON r.id = rc.return_id
    JOIN customers c ON c.id = rc.customer_id
  UNION ALL SELECT id::text, 'pk:' || entry_code FROM stock_entries
  UNION ALL SELECT id::text, 'phieu_thu:' || receipt_code FROM cash_receipts WHERE receipt_code IS NOT NULL
  UNION ALL SELECT p.id::text, 'thu:' || COALESCE(si.invoice_code, r.return_code, 'dk') || ':' || trim(to_char(p.amount, 'FM999999999990'))
    FROM payments p JOIN receivables rc ON rc.id = p.receivable_id LEFT JOIN sales_invoices si ON si.id = rc.invoice_id
    LEFT JOIN returns r ON r.id = rc.return_id
  UNION ALL SELECT id::text, 'ptncc:' || COALESCE(return_code, id::text) FROM supplier_returns
  UNION ALL SELECT b.id::text, b.batch_code || '::' || b.warehouse_zone FROM batches b
) x;""")


def ban_do_tinh(bo: str) -> dict:
	if bo.startswith("S"):
		m = {ORG_S: "NPP BC"}
		for i, _t, _v, email in NGUOI_S.values():
			m[i] = email
		for i, _t, _c, sdt, _tu in KHACH_S.values():
			m[i] = sdt
		for sku, (i, *_r) in HANG_S.items():
			m[i] = sku
		for i, ten in NCC_S.values():
			m[i] = ten
		return m
	if bo == "N":
		return dict(KHOA_N)
	m = {ORG_E: "NPP E2E", ID_E["SP"]: "ML1"}
	for i, _t, _v, email in NGUOI_E.values():
		m[i] = email
	for k, sdt in SDT_E.items():
		m[ID_E[k]] = sdt
	return m


# ================================================================================================ chuẩn hoá (bài so dùng CÙNG luật)
_RE_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_RE_LUC = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}(:?\d{2})?|Z)$")


def so(v):
	"""Tiền / SL: int khi chẵn, float (≤ 6 chữ số lẻ) khi lẻ — như chuan_gia_tri('tien'|'so') của cổng Frappe."""
	d = decimal.Decimal(str(v))
	if d == d.to_integral_value():
		return int(d)
	return float(round(d, 6))


def gio_vn(s: str) -> str:
	t = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
	if t.tzinfo is None:
		t = t.replace(tzinfo=VN)
	return t.astimezone(VN).replace(microsecond=0).isoformat()


def chuan(v, idm: dict, la: str | None = None):
	"""uuid → khoá nghiệp vụ (không biết → "?<uuid>"; cả KHOÁ dict là uuid — kết quả TS theo NV / mặt hàng); mốc giờ → giờ VN cố định; số → int / float;
	dict / list đệ quy."""
	if isinstance(v, dict):
		return {(idm.get(k, la or "?" + k) if _RE_UUID.fullmatch(k) else k): chuan(x, idm, la) for k, x in v.items()}
	if isinstance(v, list):
		return [chuan(x, idm, la) for x in v]
	if isinstance(v, bool) or v is None:
		return v
	if isinstance(v, (decimal.Decimal, int, float)):
		return so(v)
	if isinstance(v, str):
		if _RE_UUID.fullmatch(v):
			return idm.get(v, la or "?" + v)
		if _RE_LUC.match(v):
			return gio_vn(v)
		return _RE_UUID.sub(lambda m: idm.get(m.group(0), la or "?" + m.group(0)), v)
	return v


def _k(*cot):
	return lambda x: tuple("" if x.get(c) is None else str(x.get(c)) for c in cot)


# mảng KHÔNG thứ tự (đặc tả L12) → xếp theo khoá để so như tập; mảng có thứ tự (hàm TABLE, hang_khach_da_lay) giữ nguyên
XEP = {
	"bao_cao_so_ban": {"hd": _k("id"), "dong_hd": _k("invoice_id", "product_id", "unit_name", "is_exchange", "quantity"), "tra": _k("id"),
		"dong_tra": _k("return_id", "product_id", "unit_name", "quantity"), "gv": _k("product_id"), "gv_tra": _k("return_id", "product_id")},
	"bao_cao_ton_kho": {"lo": _k("id"), "dong": _k("ngay", "invoice_id", "product_id", "unit_name", "is_exchange")},
	"bao_cao_cong_no": {"mo": _k("id"), "gan90": _k("id"), "thu": _k("id")},
}


def xep(ham: str, kq):
	if isinstance(kq, dict) and ham in XEP:
		kq = dict(kq)
		for k, f in XEP[ham].items():
			if isinstance(kq.get(k), list):
				kq[k] = sorted(kq[k], key=f)
	return kq


# ================================================================================================ TS (mã giao diện nppsale thật)
_BO_TS: list = []


def _ts_bo() -> str:
	if _BO_TS:
		return _BO_TS[0]
	if not os.path.isdir(NGUON_TS):
		raise SystemExit(f"thiếu {NGUON_TS} — chạy portal/scripts/lay-nguon.mjs (nppsale ghim ở portal/nguon.json)")
	tam = tempfile.mkdtemp(prefix="vang-bc-ts-")
	with open(os.path.join(tam, "tsconfig.json"), "w") as f:
		json.dump({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": [NGUON_TS + "/*"]}}}, f)
	ra = os.path.join(tam, "vang_bao_cao_ts.mjs")
	r = subprocess.run([ESBUILD, TS_GOC, "--bundle", "--platform=node", "--format=esm", f"--tsconfig={tam}/tsconfig.json", f"--outfile={ra}",
		"--log-level=warning"], capture_output=True, text=True, check=False)
	if r.returncode != 0:
		raise SystemExit("esbuild hỏng:\n" + r.stderr[-4000:])
	_BO_TS.append(ra)
	return ra


def _ra_json(v):
	if isinstance(v, decimal.Decimal):
		return int(v) if v == v.to_integral_value() else float(v)
	raise TypeError(type(v))


def chay_ts(cas: list[dict]) -> list[dict]:
	r = subprocess.run(["node", _ts_bo()], input=json.dumps(cas, default=_ra_json), capture_output=True, text=True, check=False)
	if r.returncode != 0:
		raise SystemExit("node (mã TS nppsale) hỏng:\n" + r.stderr[-4000:])
	return json.loads(r.stdout)


def san_pham_db(db: str):
	return psql_json(db, """SELECT COALESCE(jsonb_agg(jsonb_build_object('id', p.id, 'sku', p.sku, 'name', p.name, 'brand', p.brand,
  'primary_supplier_id', p.primary_supplier_id, 'base_unit', p.base_unit, 'sell_price', p.sell_price,
  'units', COALESCE((SELECT jsonb_agg(jsonb_build_object('unit_name', u.unit_name, 'conversion', u.conversion) ORDER BY u.unit_name)
                     FROM product_units u WHERE u.product_id = p.id), '[]'::jsonb),
  'price_lists', COALESCE((SELECT jsonb_agg(jsonb_build_object('unit_name', g.unit_name, 'price', g.price, 'group_id', g.group_id) ORDER BY g.id)
                     FROM price_lists g WHERE g.product_id = p.id), '[]'::jsonb)) ORDER BY p.sku), '[]') FROM products p;""")


def ts_gon(r: dict, idm: dict) -> dict:
	"""Kết quả TS → phần đặc tả §5 dùng (tổng, theo NV, giá vốn, phân bổ dòng, SL mặt hàng, hàng bán theo NV) — chuẩn hoá id."""
	x = chuan(r, idm)
	dong = sorted(x["dong"], key=lambda d: (-d["loai"], d["ct"], d["sp"] or "", d["sl"]))
	hb = []
	for h in sorted(x["hang_ban_nv"], key=lambda h: h["id"]):
		hb.append({k: h[k] for k in ("id", "qty", "sl_hien", "don_vi", "listed", "revenue", "diff", "docDiscount", "thueLamTron", "returnQty",
			"sl_tra_hien", "returnValue", "returnListed", "diffReturn", "netRevenue", "diffNet", "tongChenh")}
			| {"products": [{"sku": p["sku"], "qty": p["qty"], "listed": p["listed"], "revenue": p["revenue"], "diff": p["diff"],
				"returnQty": p["returnQty"], "returnValue": p["returnValue"], "diffReturn": p["diffReturn"],
				"donVi": [{k: d[k] for k in ("unit", "heSo", "qty", "returnQty", "giaBang", "giaBan", "listed", "revenue", "diff", "returnValue",
					"diffReturn")} for d in p["donVi"]]} for p in h["products"]]})
	return {"tong": x["tong"], "theo_nv": dict(sorted(x["theo_nv"].items())), "gia_von_xuat": x["gia_von_xuat"],
		"gia_von_co_so": dict(sorted(x["gia_von_co_so"].items())), "gia_von_tra": dict(sorted(x["gia_von_tra"].items())),
		"thu_tu_hd": x["thu_tu_hd"], "nv_phieu_tra": dict(sorted(x["nv_phieu_tra"].items())), "dong": dong,
		"sl_mat_hang": dict(sorted(x["sl_mat_hang"].items())), "hang_ban_nv": hb}


# ================================================================================================ mô phỏng luật Frappe (đề xuất Qn) trên dữ liệu
def gv_frappe(db: str, org: str, tu: str, den: str):
	"""Giá vốn XUẤT kỳ theo luật Frappe (đặc tả L4-b, Phụ lục A NGUON_DONG_XUAT): chứng từ xuất đã ghi sổ theo NGÀY CHỨNG TỪ — HĐ theo ngày HĐ
	(Q1: posting_date), phiếu khác theo ngày ghi sổ VN; bỏ phiếu xuất của HĐ huỷ với MỌI vai (Q9 — docstatus 2); xuất lẻ XKL- giá 0 (Q2 chốt
	chéo P4 = nppsale; Nền N đặt tay 8.000 cho phiếu hư hỏng E6 → 0); trả NCC giá lô; không phiếu 'Đảo phiếu trả' (Frappe không có)."""
	return psql_json(db, f"""SELECT COALESCE(jsonb_agg(jsonb_build_object('product_id', x.product_id, 'sl', x.sl, 'tien', x.tien) ORDER BY x.product_id), '[]')
FROM (
  SELECT l.product_id,
         sum(CASE WHEN l.qty_in_base_uom IS NOT NULL THEN abs(l.qty_in_base_uom)
                  ELSE abs(COALESCE(l.quantity, 0)) * CASE WHEN l.conversion_factor_snapshot > 0 THEN l.conversion_factor_snapshot ELSE 1 END END) AS sl,
         sum((CASE WHEN l.qty_in_base_uom IS NOT NULL THEN abs(l.qty_in_base_uom)
                   ELSE abs(COALESCE(l.quantity, 0)) * CASE WHEN l.conversion_factor_snapshot > 0 THEN l.conversion_factor_snapshot ELSE 1 END END)
             * CASE WHEN e.hd IS NULL AND COALESCE(e.notes, '') NOT LIKE 'Xuất kho trả NCC%' THEN 0 ELSE COALESCE(l.unit_cost, 0) END) AS tien
    FROM (SELECT e.*, (SELECT min(h.invoice_date) FROM sales_invoices h WHERE h.stock_entry_id = e.id AND h.status = 'posted') AS hd
            FROM stock_entries e
           WHERE e.org_id = '{org}' AND e.status = 'posted' AND e.type = 'export' AND COALESCE(e.notes, '') NOT LIKE 'Đảo phiếu trả %'
             AND NOT EXISTS (SELECT 1 FROM sales_invoices si WHERE si.stock_entry_id = e.id AND si.status = 'cancelled')) e
    JOIN stock_entry_lines l ON l.entry_id = e.id
   WHERE COALESCE(e.hd, (e.posted_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date) BETWEEN '{tu}' AND '{den}'
   GROUP BY l.product_id) x;""")


# ================================================================================================ kịch bản (đặc tả §5)
def tong(ds, c):
	return sum(x.get(c) or 0 for x in ds)


def tim(ds, **kv):
	return next((x for x in ds if all(x.get(a) == b for a, b in kv.items())), None)


def bo_ma(ds, *cot):
	return [tuple(x.get(c) for c in cot) for x in ds]


def ts(tu, **k):
	"""Lời gọi TS: chạy mã giao diện nppsale trên kết quả bao_cao_so_ban của lời gọi số `tu` (k: doi_gia = bảng giá chung thay thế)."""
	return {"ham": "ts:ban_hang", "tu": tu, **k}


T11 = {"p_tu": "2026-11-01", "p_den": "2026-11-30"}
T10 = {"p_tu": "2026-10-01", "p_den": "2026-10-31"}
T12 = {"p_tu": "2026-12-01", "p_den": "2026-12-31"}
F11 = {"p_from": "2026-11-01", "p_to": "2026-11-30"}
F10 = {"p_from": "2026-10-01", "p_to": "2026-10-31"}
F12 = {"p_from": "2026-12-01", "p_to": "2026-12-31"}
SAU_KHOA = ["dong_hd", "dong_tra", "gv", "gv_tra", "hd", "tra"]
Q1 = ("Q1 (⚠K): giá vốn kỳ theo posting_date = NGÀY HĐ (nppsale theo lúc ghi sổ phiếu xuất) — HĐ4 đề 31/10 ghi sổ 01/11 06:30 VN: nppsale "
	"vào tháng 11, Frappe vào tháng 10")
Q2 = "Q2 = 0 (chốt chéo P4 — ƯU TIÊN): dòng xuất lẻ XKL- / chuyển kho CKL- giá 0 ở cổng + NGUON_DONG_XUAT như nppsale; sổ kho / GL vẫn giá thật"
Q3 = "Q3 (⚠K): người thiếu ô inventory.cost (NVBH mặc định) nhận MỌI số giá vốn = null; số lượng không che (nppsale chỉ ẩn ở giao diện)"
Q9 = "Q9 (⚠K): không tái hiện quirk RLS — phiếu xuất của HĐ huỷ (docstatus 2) rơi với MỌI vai (nppsale: NVBH không thấy HĐ huỷ của NV khác nên cộng thêm)"
Q12 = "Q12 (đề xuất): kết quả thêm khoá tinh_lai_gia_von (số việc Repost Item Valuation còn chờ; 0 khi chạy hết) — so 6 khoá nppsale + khoá thêm là số ≥ 0"
ID_FR = ("⚠K id = name chứng từ (HĐ / phiếu trả / đơn) thay uuid; NV = email; khách = Customer.name (bài so đổi về SĐT như tệp vàng); dòng con: "
	"dong_hd.id / order_line_id so theo khoá <mã chứng từ>/<SKU>/<ĐV>[/doi]")
THU_TU = ("dong_hd / dong_tra: nppsale ORDER BY uuid, Frappe ORDER BY name (chuỗi ngẫu nhiên) — so NHƯ TẬP; kiểm riêng danh sách Frappe tăng dần theo "
	"id. hd / tra / gv / gv_tra không thứ tự (tệp vàng xếp theo khoá)")


def kich_ban() -> list[dict]:
	K = []

	def kb(ma, bo, ten, goi_, *, nguon="chay_that", lech=None, kiem=None, fr=None, ky_vong=None, cho=None, chon=None, buoc=None):
		K.append({"ma": ma, "bo": bo, "ten": ten, "goi": goi_, "nguon": nguon, "lech_frappe": lech or [], "kiem": kiem or [], "fr": fr,
			"ky_vong_dac_ta": ky_vong, "cho": cho, "chon": chon, "buoc_them": buoc})

	# ---------------------------------------------------------------------------------------------------------------- A
	kb("VB-A01", "S1", "bao_cao_so_ban tháng 11 (Chủ) — bộ khoá, hd, dong_hd", [goi("bao_cao_so_ban", "CHU", **T11)],
		chon={0: ["hd", "dong_hd"]}, lech=[ID_FR, Q12, THU_TU, "posted_by = owner của Sales Invoice (email Chủ) — Administrator / Guest → null"],
		kiem=[("bộ khoá (6)", SAU_KHOA, lambda k: sorted(k[0])),
			("số HĐ", 3, lambda k: len(k[0]["hd"])),
			("HĐ1 total / subtotal / vat / NV", (534000, 530000, 4000, "nv.an@sobc.vn"), lambda k: bo_ma([tim(k[0]["hd"], id="HD-0001")], "total", "subtotal", "vat", "sales_user_id")[0]),
			("HĐ2 total / subtotal / vat / NV", (337200, 330000, 7200, "nv.binh@sobc.vn"), lambda k: bo_ma([tim(k[0]["hd"], id="HD-0002")], "total", "subtotal", "vat", "sales_user_id")[0]),
			("HĐ5 total / subtotal / vat / NV", (240000, 240000, 0, "nv.an@sobc.vn"), lambda k: bo_ma([tim(k[0]["hd"], id="HD-0005")], "total", "subtotal", "vat", "sales_user_id")[0]),
			("Σ total", 1111200, lambda k: tong(k[0]["hd"], "total")),
			("mọi HĐ: status posted / COD / posted_by Chủ / 12 khoá", True, lambda k: all(h["status"] == "posted" and h["payment_terms"] == "COD"
				and h["posted_by"] == "chu@sobc.vn" and len(h) == 12 for h in k[0]["hd"])),
			("dong_hd: 6 dòng × 11 khoá", (6, True), lambda k: (len(k[0]["dong_hd"]), all(len(d) == 11 for d in k[0]["dong_hd"]))),
			("dòng đổi HĐ1 (SP3 goi 5 × 0, order_line_id null)", (5, 0, 0, True, None), lambda k: bo_ma([tim(k[0]["dong_hd"], invoice_id="HD-0001",
				product_id="SP3")], "quantity", "unit_price", "line_total", "is_exchange", "order_line_id")[0]),
			("L1: HĐ2 round(Σ line_total) − subtotal = giảm đơn", 10000, lambda k: round(sum(d["line_total"] for d in k[0]["dong_hd"]
				if d["invoice_id"] == "HD-0002")) - tim(k[0]["hd"], id="HD-0002")["subtotal"])])
	kb("VB-A02", "S1", "bao_cao_so_ban tháng 11 (Chủ) — tra, dong_tra", [goi("bao_cao_so_ban", "CHU", **T11)], chon={0: ["tra", "dong_tra"]},
		lech=[ID_FR, THU_TU, "tra.created_at = creation phiếu trả (giờ ghim của bước lập phiếu, ISO +07:00); ma = name phiếu"],
		kiem=[("tra (mã, trạng thái, tiền, revenue_date, NV, lý do, tự sinh)", [
				("PT-0001", "completed", 30000, "2026-11-03", "nv.an@sobc.vn", "damaged", True),
				("PT-0002", "completed", 19440, "2026-11-12", "nv.binh@sobc.vn", "damaged", False),
				("PT-0003", "completed", 240000, "2026-11-14", "nv.an@sobc.vn", "refused", False),
				("PT-0007", "submitted", 20000, "2026-11-20", "nv.an@sobc.vn", "near_expiry", True)],
				lambda k: bo_ma(k[0]["tra"], "id", "status", "credit_note_amount", "revenue_date", "sales_user_id", "reason", "credit_with_invoice")),
			("HĐ gắn của phiếu", ["HD-0001", "HD-0002", None, "HD-0005"], lambda k: [t["invoice_id"] for t in k[0]["tra"]]),
			("Σ credit", 309440, lambda k: tong(k[0]["tra"], "credit_note_amount")),
			("11 khoá / phiếu", True, lambda k: all(len(t) == 11 for t in k[0]["tra"])),
			("dong_tra (phiếu, SKU, ĐV, SL, đơn giá, tiền)", [("PT-0001", "SP1", "lon", 3, 10000, 30000), ("PT-0002", "SP2", "goi", 4, 4500, 19440),
				("PT-0003", "SP1", "thung", 1, 240000, 240000), ("PT-0007", "SP1", "lon", 2, 10000, 20000)],
				lambda k: bo_ma(k[0]["dong_tra"], "return_id", "product_id", "unit_name", "quantity", "unit_price", "line_total")),
			("dong_tra 6 khoá", True, lambda k: all(len(d) == 6 for d in k[0]["dong_tra"]))])
	kb("VB-A03", "S1", "bao_cao_so_ban tháng 11 (Chủ) — gv", [goi("bao_cao_so_ban", "CHU", **T11)], chon={0: ["gv"]},
		lech=[Q1, Q2, Q9, "Frappe: SP1 96 / 672.000 (HĐ4 sang tháng 10), SP2 30 / 90.000, SP3 15 / 5.000 (xuất huỷ giá 0) — Σ 767.000 (đặc tả ghi "
			"777.000 vì giả định Q2 = giá thật; chốt chéo P4 đổi Q2 = 0)"],
		kiem=[("gv (SKU, sl, tiền)", [("SP1", 120, 840000), ("SP2", 30, 90000), ("SP3", 15, 5000)], lambda k: bo_ma(k[0]["gv"], "product_id", "sl", "tien"))],
		fr=lambda c, k: {0: c.so_ban_fr(k[0], T11, "CHU")})
	kb("VB-A04", "S1", "bao_cao_so_ban tháng 11 (Chủ) — gv_tra", [goi("bao_cao_so_ban", "CHU", **T11)], chon={0: ["gv_tra"]},
		lech=["gv_tra nối phiếu nhập lại theo Link npp_phieu_tra (nppsale nối chữ ghi chú) — cùng số; PT-0007 Chờ xử lý chưa nhập → không dòng"],
		kiem=[("gv_tra", [("PT-0001", "SP1", 21000), ("PT-0001", "SP3", 5000), ("PT-0002", "SP2", 12000), ("PT-0003", "SP1", 168000)],
				lambda k: bo_ma(k[0]["gv_tra"], "return_id", "product_id", "tien")),
			("Σ gv_tra", 206000, lambda k: tong(k[0]["gv_tra"], "tien"))])
	kb("VB-A05", "S1", "số giao diện từ mã TS (tuMotLuot → dungDongBan → congBan), Chủ, tháng 11", [goi("bao_cao_so_ban", "CHU", **T11), ts(0)],
		nguon="ts", chon={0: []}, lech=[Q1, Q2, "Frappe: giaVonXuat 767.000 (Q1; Q2 = 0); cost / gp / theo NV không đổi; màn tài chính giaVonXuat − Σ gv_tra = "
			"561.000 (nppsale 729.000); phân bổ tiền theo dòng ±1 đ (name dòng con ngẫu nhiên — R6): so theo HĐ / NV / mặt hàng"],
		kiem=[("tổng rev / ret / net / cost / gp / nInv / nCust", (1111200, 309440, 801760, 561000, 240760, 3, 3),
				lambda k: tuple(k[1]["tong"][x] for x in ("rev", "ret", "net", "cost", "gp", "nInv", "nCust"))),
			("giaVonXuat", 935000, lambda k: k[1]["gia_von_xuat"]),
			("giaVonCoSo SP1 / SP2 / SP3", (7000, 3000, 333.333333), lambda k: tuple(round(k[1]["gia_von_co_so"][x], 6) for x in ("SP1", "SP2", "SP3"))),
			("NV An rev / ret / net / cost / gp / nInv / nCust", (774000, 290000, 484000, 345000, 139000, 2, 2),
				lambda k: tuple(k[1]["theo_nv"]["nv.an@sobc.vn"][x] for x in ("rev", "ret", "net", "cost", "gp", "nInv", "nCust"))),
			("NV Bình rev / ret / net / cost / gp", (337200, 19440, 317760, 216000, 101760),
				lambda k: tuple(k[1]["theo_nv"]["nv.binh@sobc.vn"][x] for x in ("rev", "ret", "net", "cost", "gp"))),
			("phân bổ HĐ1 SP1 / SP2", (483623, 50377), lambda k: tuple(round(tim(k[1]["dong"], ct="HD-0001", sp=x)["tien"]) for x in ("SP1", "SP2"))),
			("phân bổ HĐ2 SP1 / SP2", (247941, 89259), lambda k: tuple(round(tim(k[1]["dong"], ct="HD-0002", sp=x)["tien"]) for x in ("SP1", "SP2"))),
			("giảm giá đơn HĐ2 SP1 / SP2", (7353, 2647), lambda k: tuple(round(tim(k[1]["dong"], ct="HD-0002", sp=x)["giam_don"]) for x in ("SP1", "SP2"))),
			("màn tài chính: giaVonXuat − Σ gv_tra", 729000, lambda k: k[1]["gia_von_xuat"] - sum(v["total"] for v in k[1]["gia_von_tra"].values()))],
		fr=lambda c, k: {1: c.ts_fr(0, T11, "CHU")})
	kb("VB-A06", "S1", "bao_cao_so_ban tháng 11 dưới NV An (RLS NVBH) + số TS", [goi("bao_cao_so_ban", "NV_AN", **T11), ts(0)],
		lech=[Q1, Q3, Q9, "Frappe: gv SL SP1 96 (Q1 + Q9 — không cộng 72 lon HĐ3 huỷ), SP2 30, SP3 15, mọi tien null; gv_tra.tien null; TS: giá vốn 0 (giao "
			"diện ẩn giá vốn với NVBH)"],
		kiem=[("hd", ["HD-0001", "HD-0005"], lambda k: [h["id"] for h in k[0]["hd"]]), ("Σ hd", 774000, lambda k: tong(k[0]["hd"], "total")),
			("dong_hd", 4, lambda k: len(k[0]["dong_hd"])), ("tra", ["PT-0001", "PT-0003", "PT-0007"], lambda k: [t["id"] for t in k[0]["tra"]]),
			("Σ tra", 290000, lambda k: tong(k[0]["tra"], "credit_note_amount")), ("dong_tra", 3, lambda k: len(k[0]["dong_tra"])),
			("gv_tra", [("PT-0001", "SP1", 21000), ("PT-0001", "SP3", 5000), ("PT-0003", "SP1", 168000)], lambda k: bo_ma(k[0]["gv_tra"], "return_id", "product_id", "tien")),
			("gv (quirk Q9: gồm 72 lon HĐ3 huỷ)", [("SP1", 192, 1344000), ("SP2", 30, 90000), ("SP3", 15, 5000)], lambda k: bo_ma(k[0]["gv"], "product_id", "sl", "tien")),
			("TS net / cost / giaVonXuat", (484000, 345000, 1439000), lambda k: (k[1]["tong"]["net"], k[1]["tong"]["cost"], k[1]["gia_von_xuat"]))],
		fr=lambda c, k: {0: c.so_ban_fr(k[0], T11, "NV_AN"), 1: c.ts_fr(0, T11, "NV_AN")})
	kb("VB-A07", "S1", "bao_cao_so_ban tháng 11 dưới NV Bình, Kế toán, Quản lý, Thủ kho", [goi("bao_cao_so_ban", "CHU", **T11),
		goi("bao_cao_so_ban", "NV_BINH", **T11), goi("bao_cao_so_ban", "KT", **T11), goi("bao_cao_so_ban", "QL", **T11), goi("bao_cao_so_ban", "TK", **T11)],
		lech=[Q1, Q3, "Frappe: NV Bình gv / gv_tra tien null; Kế toán / Quản lý / Thủ kho = Chủ (thủ kho có inventory.cost mặc định)"],
		kiem=[("NV Bình hd / tra", (["HD-0002"], ["PT-0002"]), lambda k: ([h["id"] for h in k[1]["hd"]], [t["id"] for t in k[1]["tra"]])),
			("NV Bình dong_hd / dong_tra", (2, [("PT-0002", "SP2", "goi", 4, 4500, 19440)]), lambda k: (len(k[1]["dong_hd"]),
				bo_ma(k[1]["dong_tra"], "return_id", "product_id", "unit_name", "quantity", "unit_price", "line_total"))),
			("NV Bình gv = Chủ (thấy HĐ3 của mình)", [("SP1", 120, 840000), ("SP2", 30, 90000), ("SP3", 15, 5000)], lambda k: bo_ma(k[1]["gv"], "product_id", "sl", "tien")),
			("NV Bình gv_tra", [("PT-0002", "SP2", 12000)], lambda k: bo_ma(k[1]["gv_tra"], "return_id", "product_id", "tien")),
			("Kế toán / Quản lý / Thủ kho = Chủ", (True, True, True), lambda k: (k[2] == k[0], k[3] == k[0], k[4] == k[0]))],
		fr=lambda c, k: {i: c.so_ban_fr(k[i], T11, n) for i, n in enumerate(("CHU", "NV_BINH", "KT", "QL", "TK"))})
	kb("VB-A08", "S1", "kỳ một ngày 03/11 và 20/11 (Chủ)", [goi("bao_cao_so_ban", "CHU", p_tu="2026-11-03", p_den="2026-11-03"),
		goi("bao_cao_so_ban", "CHU", p_tu="2026-11-20", p_den="2026-11-20")],
		lech=["Frappe = nppsale (HĐ1 / HĐ5 ghi sổ đúng ngày HĐ); gv_tra theo revenue_date của phiếu, không theo ngày nhập kho (05/11)"],
		kiem=[("03/11 hd / dong_hd / tra", (["HD-0001"], 3, [("PT-0001", 30000)]), lambda k: ([h["id"] for h in k[0]["hd"]], len(k[0]["dong_hd"]),
				bo_ma(k[0]["tra"], "id", "credit_note_amount"))),
			("03/11 dong_tra", [("SP1", "lon", 3)], lambda k: bo_ma(k[0]["dong_tra"], "product_id", "unit_name", "quantity")),
			("03/11 gv", [("SP1", 48, 336000), ("SP2", 10, 30000), ("SP3", 5, 5000)], lambda k: bo_ma(k[0]["gv"], "product_id", "sl", "tien")),
			("03/11 gv_tra", [("PT-0001", "SP1", 21000), ("PT-0001", "SP3", 5000)], lambda k: bo_ma(k[0]["gv_tra"], "return_id", "product_id", "tien")),
			("20/11 hd / dong_hd", ([("HD-0005", 240000)], 1), lambda k: (bo_ma(k[1]["hd"], "id", "total"), len(k[1]["dong_hd"]))),
			("20/11 tra / dong_tra", ([("PT-0007", "submitted", 20000)], [("SP1", "lon", 2, 10000)]), lambda k: (bo_ma(k[1]["tra"], "id", "status",
				"credit_note_amount"), bo_ma(k[1]["dong_tra"], "product_id", "unit_name", "quantity", "unit_price"))),
			("20/11 gv / gv_tra", ([("SP1", 24, 168000)], []), lambda k: (bo_ma(k[1]["gv"], "product_id", "sl", "tien"), k[1]["gv_tra"]))],
		fr=lambda c, k: {0: c.so_ban_fr(k[0], {"p_tu": "2026-11-03", "p_den": "2026-11-03"}, "CHU"),
			1: c.so_ban_fr(k[1], {"p_tu": "2026-11-20", "p_den": "2026-11-20"}, "CHU")})
	kb("VB-A09", "S1", "biên tháng và múi giờ: tháng 10, tháng 12 (Chủ)", [goi("bao_cao_so_ban", "CHU", **T10), goi("bao_cao_so_ban", "CHU", **T12)],
		lech=[Q1, Q2, "Frappe: tháng 10 gv {SP1 24 / 168.000} (HĐ4 posting_date 31/10); tháng 12 gv {SP2 5 / 0} (xuất lẻ 01/12 — Q2 = 0 như nppsale; đặc tả "
			"ghi 15.000 theo Q2 giá thật)"],
		kiem=[("T10 hd / dong_hd", ([("HD-0004", 240000, "2026-10-31")], [("SP1", "thung", 1, 240000)]), lambda k: (bo_ma(k[0]["hd"], "id", "total",
				"invoice_date"), bo_ma(k[0]["dong_hd"], "product_id", "unit_name", "quantity", "line_total"))),
			("T10 tra / dong_tra / gv / gv_tra rỗng", ([], [], [], []), lambda k: (k[0]["tra"], k[0]["dong_tra"], k[0]["gv"], k[0]["gv_tra"])),
			("T12 hd rỗng; tra", ([], [("PT-0006", "completed", 10800, "2026-12-02")]), lambda k: (k[1]["hd"], bo_ma(k[1]["tra"], "id", "status",
				"credit_note_amount", "revenue_date"))),
			("T12 dong_tra", [("SP2", "goi", 2, 5000, 10800)], lambda k: bo_ma(k[1]["dong_tra"], "product_id", "unit_name", "quantity", "unit_price", "line_total")),
			("T12 gv (xuất lẻ 01/12 00:00 VN, giá 0)", [("SP2", 5, 0)], lambda k: bo_ma(k[1]["gv"], "product_id", "sl", "tien")),
			("T12 gv_tra", [("PT-0006", "SP2", 6000)], lambda k: bo_ma(k[1]["gv_tra"], "return_id", "product_id", "tien"))],
		fr=lambda c, k: {0: c.so_ban_fr(k[0], T10, "CHU"), 1: c.so_ban_fr(k[1], T12, "CHU")})
	sai = [("2026-11-30", "2026-11-01"), (None, "2026-11-30"), ("2026-11-01", None), ("abc", "2026-11-30"), ("2026-02-30", "2026-11-30"), ("", "2026-11-30")]
	kb("VB-A10", "S1", "tham số lạ (đảo kỳ, NULL, chuỗi sai)", [goi("bao_cao_so_ban", "CHU", p_tu=a, p_den=b) for a, b in sai],
		lech=["Frappe _ngay(): None → NULL (6 mảng rỗng); chuỗi sai → LoiCong 22007 'invalid input syntax for type date: \"…\"'; ngày không có thật → 22008; "
			"'' → 22007 (KHÔNG hiểu là hôm nay — getdate('') của Frappe trả hôm nay); câu lỗi so nguyên văn",
			"Guest gọi → PGRST301 401 (nppsale 42501) — chấp nhận, không thuộc bộ vàng"],
		kiem=[("đảo kỳ / NULL đầu / NULL cuối: 6 mảng rỗng", [{k: [] for k in SAU_KHOA}] * 3, lambda k: [k[i] for i in range(3)]),
			("'abc' → 22007", "22007", lambda k: k[3]["ma_loi"]), ("'2026-02-30' → 22008", "22008", lambda k: k[4]["ma_loi"]),
			("'' → 22007", "22007", lambda k: k[5]["ma_loi"])])
	kb("VB-A11", "S2", "Sửa HĐ2 (reissue_invoice): số bán, dashboard, công nợ", [goi("bao_cao_so_ban", "CHU", **T11), goi("bao_cao_so_ban", "NV_AN", **T11),
		goi("dashboard_summary", "CHU", p_period_start="2026-11-01"), goi("dashboard_channel_revenue", "CHU", p_period_start="2026-11-01"), ts(0),
		goi("bang:sales_invoices", "CHU"), goi("bang:receivables", "CHU")],
		lech=[Q1, Q3, Q9, "Frappe: tờ mới HD-0002-1 posting_date 10/11 (giữ ngày) — gv Chủ SP1 96 / 672.000 (Q1), SP2 28 / 84.000, SP3 15 / 5.000; NV An gv SL "
			"SP1 96, SP2 28, SP3 15 (Q9 — không cộng tờ cũ HD-0002 / HĐ3), tien null (Q3); TS giaVonXuat 761.000"],
		kiem=[("hd", [("HD-0001", 534000), ("HD-0002-1", 327480), ("HD-0005", 240000)], lambda k: bo_ma(k[0]["hd"], "id", "total")),
			("HD-0002-1 ngày / subtotal / vat / NV", ("2026-11-10", 321000, 6480, "nv.binh@sobc.vn"), lambda k: bo_ma([tim(k[0]["hd"], id="HD-0002-1")],
				"invoice_date", "subtotal", "vat", "sales_user_id")[0]),
			("HD-0002 cancelled", "cancelled", lambda k: tim(k[5], id="HD-0002")["status"]),
			("dong_hd HD-0002-1", [("SP1", "thung", 1, 250000, 250000), ("SP2", "goi", 18, 4500, 81000)], lambda k: bo_ma([d for d in k[0]["dong_hd"]
				if d["invoice_id"] == "HD-0002-1"], "product_id", "unit_name", "quantity", "unit_price", "line_total")),
			("PT-0002 gắn HD-0002-1, revenue_date 12/11", ("HD-0002-1", "2026-11-12"), lambda k: bo_ma([tim(k[0]["tra"], id="PT-0002")], "invoice_id", "revenue_date")[0]),
			("gv Chủ", [("SP1", 120, 840000), ("SP2", 28, 84000), ("SP3", 15, 5000)], lambda k: bo_ma(k[0]["gv"], "product_id", "sl", "tien")),
			("gv_tra không đổi (Σ)", 206000, lambda k: tong(k[0]["gv_tra"], "tien")),
			("TS rev / net / cost / gp / giaVonXuat", (1101480, 792040, 555000, 237040, 929000), lambda k: (k[4]["tong"]["rev"], k[4]["tong"]["net"],
				k[4]["tong"]["cost"], k[4]["tong"]["gp"], k[4]["gia_von_xuat"])),
			("TS NV Bình rev / net / cost / gp", (327480, 308040, 210000, 98040), lambda k: tuple(k[4]["theo_nv"]["nv.binh@sobc.vn"][x] for x in ("rev", "net", "cost", "gp"))),
			("công nợ HD-0002-1", 308040, lambda k: (lambda r: r["amount"] - r["paid"])(tim(k[6], invoice_id="HD-0002-1"))),
			("NV An gv (quirk Q9)", [("SP1", 216, 1512000), ("SP2", 48, 144000)], lambda k: bo_ma([g_ for g_ in k[1]["gv"] if g_["product_id"] != "SP3"], "product_id", "sl", "tien")),
			("dashboard_summary Chủ", [(781240, 3, 821240, 1)], lambda k: bo_ma(k[2], "period_revenue", "period_orders", "open_receivables", "overdue_count")),
			("channel Chủ", [("GT", 504000), ("MT", 297240), ("Khác", -20000)], lambda k: bo_ma(k[3], "channel", "total"))],
		fr=lambda c, k: {0: c.so_ban_fr(k[0], T11, "CHU"), 1: c.so_ban_fr(k[1], T11, "NV_AN"), 4: c.ts_fr(0, T11, "CHU")})
	kb("VB-A12", "S7", "Huỷ nhập kho phiếu tự sinh đã nhập (PT-0001)", [goi("bao_cao_so_ban", "CHU", **T11), goi("bang:returns", "CHU"),
		goi("bang:receivables", "CHU")],
		lech=[Q1, Q2, "Frappe: NL- của PT-0001 docstatus 2 (không có phiếu 'Đảo phiếu trả') → gv_tra như nppsale; gv theo Q1 / Q2 như VB-A03"],
		kiem=[("PT-0001 trạng thái / revenue_date / tiền", ("submitted", "2026-11-03", 30000), lambda k: bo_ma([tim(k[1], id="PT-0001")], "status", "revenue_date",
				"credit_note_amount")[0]),
			("công nợ HĐ1 (amount)", 504000, lambda k: tim(k[2], invoice_id="HD-0001")["amount"]),
			("tra 4 phiếu (PT-0001 submitted)", [("PT-0001", "submitted"), ("PT-0002", "completed"), ("PT-0003", "completed"), ("PT-0007", "submitted")],
				lambda k: bo_ma(k[0]["tra"], "id", "status")),
			("gv_tra", [("PT-0002", "SP2", 12000), ("PT-0003", "SP1", 168000)], lambda k: bo_ma(k[0]["gv_tra"], "return_id", "product_id", "tien")),
			("gv SP1 không đổi", ("SP1", 120, 840000), lambda k: bo_ma([tim(k[0]["gv"], product_id="SP1")], "product_id", "sl", "tien")[0])],
		fr=lambda c, k: {0: c.so_ban_fr(k[0], T11, "CHU")})
	kb("VB-A13", "S4", "Phiếu chỉ có hàng đổi (HĐ6 25/11, PT-0008 0 đ)", [goi("bao_cao_so_ban", "CHU", p_tu="2026-11-25", p_den="2026-11-25"),
		goi("bang:receivables", "CHU"), goi("bang:v_hoa_don_con_lai", "CHU")],
		lech=["Frappe = nppsale; cổng stock_entries.notes của NL- = 'Nhập lại từ phiếu trả PT-0008' (dựng từ Link — XNT xếp 'Trả về')"],
		kiem=[("hd HĐ6", [("HD-0006", 10000, 10000, 0)], lambda k: bo_ma(k[0]["hd"], "id", "total", "subtotal", "vat")),
			("dong_hd", [("SP3", "goi", 5, 2000, 10000, False), ("SP3", "goi", 4, 0, 0, True)], lambda k: bo_ma(k[0]["dong_hd"], "product_id", "unit_name",
				"quantity", "unit_price", "line_total", "is_exchange")),
			("tra PT-0008", [("PT-0008", "completed", 0, "2026-11-25", True)], lambda k: bo_ma(k[0]["tra"], "id", "status", "credit_note_amount", "revenue_date",
				"credit_with_invoice")),
			("dong_tra rỗng", [], lambda k: k[0]["dong_tra"]),
			("gv", [("SP3", 9, 9000)], lambda k: bo_ma(k[0]["gv"], "product_id", "sl", "tien")),
			("gv_tra (nhập ngày khác ngày HĐ)", [("PT-0008", "SP3", 4000)], lambda k: bo_ma(k[0]["gv_tra"], "return_id", "product_id", "tien")),
			("công nợ HĐ6", 10000, lambda k: tim(k[1], invoice_id="HD-0006")["amount"]),
			("con_lai HĐ6", 10000, lambda k: tim(k[2], id="HD-0006")["con_lai"])],
		fr=lambda c, k: {0: c.so_ban_fr(k[0], {"p_tu": "2026-11-25", "p_den": "2026-11-25"}, "CHU")})
	kb("VB-A14", "S5", "Huỷ HĐ5 (phiếu tự sinh PT-0007 đang Chờ xử lý)", [goi("bao_cao_so_ban", "CHU", **T11),
		goi("dashboard_summary", "CHU", p_period_start="2026-11-01"), goi("dashboard_channel_revenue", "CHU", p_period_start="2026-11-01"),
		goi("dashboard_top_customers", "CHU", p_period_start="2026-11-01", p_limit=5), goi("bang:returns", "CHU"), goi("bang:sales_orders", "CHU"),
		goi("bang:receivables", "CHU")],
		lech=[Q1, Q2, "Frappe: gv SP1 72 / 504.000 (Q1: HĐ4 sang tháng 10), SP3 15 / 5.000 (Q2 = 0); còn lại như nppsale"],
		kiem=[("ĐH5 / PT-0007", ("cancelled", "cancelled", None, None), lambda k: (tim(k[5], id="DH-0005")["status"], tim(k[4], id="PT-0007")["status"],
				tim(k[4], id="PT-0007")["invoice_id"], tim(k[4], id="PT-0007")["revenue_date"])),
			("công nợ HĐ5 biến mất", None, lambda k: tim(k[6], invoice_id="HD-0005")),
			("hd / tra", (["HD-0001", "HD-0002"], ["PT-0001", "PT-0002", "PT-0003"]), lambda k: ([h["id"] for h in k[0]["hd"]], [t["id"] for t in k[0]["tra"]])),
			("gv", [("SP1", 96, 672000), ("SP2", 30, 90000), ("SP3", 15, 5000)], lambda k: bo_ma(k[0]["gv"], "product_id", "sl", "tien")),
			("dashboard_summary", [(570960, 2, 610960, 1)], lambda k: bo_ma(k[1], "period_revenue", "period_orders", "open_receivables", "overdue_count")),
			("channel", [("GT", 504000), ("MT", 306960), ("Khác", -240000)], lambda k: bo_ma(k[2], "channel", "total")),
			("top", [("0911000001", 504000, 1), ("0911000002", 306960, 1)], lambda k: bo_ma(k[3], "customer_id", "total", "order_count"))],
		fr=lambda c, k: {0: c.so_ban_fr(k[0], T11, "CHU")})
	kb("VB-A15", "S3", "Gán người HĐ5 sang NV Bình (assign_doc_seller)", [goi("bao_cao_so_ban", "NV_AN", **T11), goi("bao_cao_so_ban", "NV_BINH", **T11),
		goi("dashboard_summary", "NV_AN", p_period_start="2026-11-01"), goi("dashboard_summary", "NV_BINH", p_period_start="2026-11-01"),
		goi("dashboard_channel_revenue", "NV_BINH", p_period_start="2026-11-01"), goi("dashboard_top_customers", "NV_BINH", p_period_start="2026-11-01", p_limit=5),
		goi("bang:sales_invoices", "CHU"), goi("bang:receivables", "CHU"), goi("bang:returns", "CHU")],
		lech=[Q3, "Frappe: vế RLS sales_invoices cho NVBH = HĐ mình đứng tên HOẶC của đơn mình (ve_hoa_don) — NV An vẫn thấy HĐ5; gv tien null (Q3)"],
		kiem=[("HĐ5 NV Bình; PT-0007 + nợ HĐ5 theo NV Bình", ("nv.binh@sobc.vn", "nv.binh@sobc.vn", "nv.binh@sobc.vn", 220000),
				lambda k: (tim(k[6], id="HD-0005")["sales_user_id"], tim(k[8], id="PT-0007")["sales_user_id"], tim(k[7], invoice_id="HD-0005")["sales_user_id"],
				(lambda r: r["amount"] - r["paid"])(tim(k[7], invoice_id="HD-0005")))),
			("NV An hd / tra", (["HD-0001", "HD-0005"], ["PT-0001", "PT-0003", "PT-0007"]), lambda k: ([h["id"] for h in k[0]["hd"]], [t["id"] for t in k[0]["tra"]])),
			("NV Bình hd / tra", (["HD-0002", "HD-0005"], ["PT-0002", "PT-0007"]), lambda k: ([h["id"] for h in k[1]["hd"]], [t["id"] for t in k[1]["tra"]])),
			("dashboard NV An", [(484000, 2, 304000, 1)], lambda k: bo_ma(k[2], "period_revenue", "period_orders", "open_receivables", "overdue_count")),
			("dashboard NV Bình", [(526960, 2, 526960, 0)], lambda k: bo_ma(k[3], "period_revenue", "period_orders", "open_receivables", "overdue_count")),
			("channel NV Bình", [("MT", 306960), ("Khác", 220000)], lambda k: bo_ma(k[4], "channel", "total")),
			("top NV Bình", [("0911000002", 306960), ("0911000003", 220000)], lambda k: bo_ma(k[5], "customer_id", "total"))],
		fr=lambda c, k: {0: c.so_ban_fr(k[0], T11, "NV_AN"), 1: c.so_ban_fr(k[1], T11, "NV_BINH")})
	A16 = [goi("finance_pnl", n, **F11) for n in ("CHU", "TK", "NV_AN", "NV_BINH")] + [goi("finance_pnl", "CHU", **F10), goi("finance_pnl", "CHU", **F12)]
	A16 += [goi("finance_cash_flow", n, **F11) for n in ("CHU", "NV_AN", "TK", "NV_BINH")]
	A16 += [goi("finance_balance_sheet", n, p_as_of="2026-11-30") for n in ("CHU", "NV_AN", "TK", "NV_BINH")]
	A16 += [goi("stock_value_summary", n) for n in ("CHU", "QL", "KT", "TK", "NV_AN", "NV_BINH")]
	A16 += [goi("bao_cao_ton_kho", n, p_tu="2026-09-01", p_den="2026-11-30") for n in ("CHU", "NV_AN")]
	A16 += [goi("bao_cao_cong_no", n, p_tu_thu="2026-06-03", p_tu_90="2026-08-31") for n in ("CHU", "NV_AN")]
	A16 += [goi("receivables_summary", n) for n in ("CHU", "NV_AN")]
	P = ("revenue", "order_count", "cogs", "revenue_gross", "returns_value", "returns_cogs")
	kb("VB-A16", "S1", "tài chính / tồn / công nợ trên Sổ BC (dựng bằng RPC thật)", A16,
		lech=[Q1, Q2, Q3, Q9, "Frappe: finance_pnl tháng 11 Chủ / Thủ kho cogs 555.000 (xuất 767.000 − 212.000; đặc tả 565.000 theo Q2 giá thật), tháng 10 cogs "
			"168.000, tháng 12 cogs 0 (xuất lẻ 5 gói SP2 giá 0 — Q2 = 0); NV An / NV Bình cogs, returns_cogs null; finance_balance_sheet.inventory / "
			"stock_value_summary.inventory_value / bao_cao_ton_kho lo[].unit_cost của NVBH null; còn lại như nppsale",
			"receivables_summary ghim hôm nay = 17/11/2026 (đồng hồ đọc của Sổ BC)",
			"Q14: finance_* trên Frappe ném PGRST202 tới khi có cổng expenses / payable_payments / payables — bài so chạy sau P4 + P7 (hoặc giả lập nguồn)"],
		kiem=[("pnl T11 Chủ", (801760, 3, 723000, 1111200, 309440, 212000), lambda k: tuple(k[0][0][x] for x in P)),
			("pnl T11 Chủ exp_* = 0", 0, lambda k: sum(k[0][0][x] for x in ("exp_cogs", "exp_operating", "exp_hr", "exp_financial", "exp_tax", "exp_other", "total_expenses"))),
			("pnl T11 Thủ kho = Chủ", True, lambda k: k[1] == k[0]),
			("pnl T11 NV An", (484000, 2, 1245000, 774000, 290000, 194000), lambda k: tuple(k[2][0][x] for x in P)),
			("pnl T11 NV Bình", (317760, 1, 917000, 337200, 19440, 18000), lambda k: tuple(k[3][0][x] for x in P)),
			("pnl T10 Chủ", (240000, 1, 0, 240000, 0, 0), lambda k: tuple(k[4][0][x] for x in P)),
			("pnl T12 Chủ", (-10800, 0, 0, 0, 10800, 0), lambda k: tuple(k[5][0][x] for x in P)),
			("xuất = cogs + returns_cogs (Chủ T11) = giaVonXuat VB-A05", 935000, lambda k: k[0][0]["cogs"] + k[0][0]["returns_cogs"]),
			("cash_flow T11 Chủ / NV An / Thủ kho / NV Bình", [(200000, 0, 0), (200000, 0, 0), (0, 0, 0), (0, 0, 0)], lambda k: [tuple(k[i][0][x] for x in
				("cash_from_customers", "cash_to_suppliers", "cash_to_expenses")) for i in (6, 7, 8, 9)]),
			("balance 30/11 Chủ", (200000, 830960, 21252000, 0, 0, 0), lambda k: tuple(k[10][0][x] for x in ("cash", "accounts_receivable", "inventory",
				"accounts_payable", "unpaid_expenses", "supplier_prepayments"))),
			("balance 30/11 NV An / Thủ kho / NV Bình (cash, AR, inventory)", [(200000, 524000, 21252000), (0, 0, 21252000), (0, 306960, 21252000)],
				lambda k: [tuple(k[i][0][x] for x in ("cash", "accounts_receivable", "inventory")) for i in (11, 12, 13)]),
			("stock_value_summary mọi vai", [(21252000, 3)] * 6, lambda k: [(k[i][0]["inventory_value"], k[i][0]["batch_count"]) for i in range(14, 20)]),
			("ton_kho Chủ lo", [("L1::sale", "SP1", 1907, 7000, "2028-12-31"), ("L2::sale", "SP2", 1971, 3000, "2028-12-31"), ("L3::sale", "SP3", 1990, 1000, "2028-12-31")],
				lambda k: bo_ma(k[20]["lo"], "id", "product_id", "qty_on_hand", "unit_cost", "expires_at")),
			("ton_kho Chủ dong (7) / NV An (lo 3, dong 5)", (7, 3, 5), lambda k: (len(k[20]["dong"]), len(k[21]["lo"]), len(k[21]["dong"]))),
			("cong_no Chủ mo / gan90 / thu", (6, 6, 1), lambda k: (len(k[22]["mo"]), len(k[22]["gan90"]), len(k[22]["thu"]))),
			("cong_no Chủ mo (khoá, amount, paid, status)", [("no:HD-0001", 504000, 200000, "partial"), ("no:HD-0002", 317760, 0, "open"),
				("no:HD-0004", 240000, 0, "overdue"), ("no:HD-0005", 220000, 0, "open"), ("no:PT-0003", -240000, 0, "open"), ("no:PT-0006", -10800, 0, "open")],
				lambda k: bo_ma(k[22]["mo"], "id", "amount", "paid", "status")),
			("cong_no NV An mo / gan90 / thu", (4, 4, 1), lambda k: (len(k[23]["mo"]), len(k[23]["gan90"]), len(k[23]["thu"]))),
			("receivables_summary Chủ (total, current, warning, overdue, critical)", (830960, 209200, 2, 621760, 4, 0, 0, 0, 0),
				lambda k: tuple(k[24][0][x] for x in ("total_outstanding", "current_amount", "current_count", "warning_amount", "warning_count", "overdue_amount",
					"overdue_count", "critical_amount", "critical_count"))),
			("receivables_summary NV An (total, current, warning)", (524000, 220000, 1, 304000, 3), lambda k: tuple(k[25][0][x] for x in ("total_outstanding",
				"current_amount", "current_count", "warning_amount", "warning_count")))],
		fr=lambda c, k: c.a16_fr(k))

	# ---------------------------------------------------------------------------------------------------------------- B
	DS = ("period_revenue", "period_orders", "open_receivables", "overdue_count")
	kb("VB-B01", "S1", "dashboard_summary('2026-11-01') theo vai + NULL", [goi("dashboard_summary", n, p_period_start="2026-11-01") for n in ("CHU", "KT", "QL", "TK")]
		+ [goi("dashboard_summary", "CHU", p_period_start=None)],
		lech=["Q10: thủ kho có reports.dashboard nhưng RLS công nợ cho 0 / 0 — Frappe chép y (vế cổng receivables: thủ kho False)",
			"Q11: không cận trên ngày (PT-0006 ngày 02/12 vẫn trừ) — chép y"],
		kiem=[("Chủ / Kế toán / Quản lý", [(790960, 3, 830960, 1)] * 3, lambda k: [bo_ma(k[i], *DS)[0] for i in range(3)]),
			("Thủ kho", (790960, 3, 0, 0), lambda k: bo_ma(k[3], *DS)[0]),
			("đúng 1 dòng", [1, 1, 1, 1, 1], lambda k: [len(x) for x in k]),
			("(NULL)", (0, 0, 830960, 1), lambda k: bo_ma(k[4], *DS)[0])])
	kb("VB-B02", "S1", "dashboard_channel_revenue('2026-11-01')", [goi("dashboard_channel_revenue", "CHU", p_period_start="2026-11-01"),
		goi("dashboard_channel_revenue", "TK", p_period_start="2026-11-01"), goi("dashboard_channel_revenue", "CHU", p_period_start=None)],
		lech=["channel = Customer.npp_tuyen (mã tuyến thô, không trim, không dịch); khách không thấy dưới RLS → 'Khác' (vế khách đặt trong điều kiện LEFT JOIN); "
			"xếp total giảm rồi channel (khoá phụ chỉ để ổn định)", "MariaDB GROUP BY utf8mb4_unicode_ci gộp mã khác hoa / thường (R8) — dữ liệu ở đây không lệch"],
		kiem=[("Chủ", [("GT", 504000), ("MT", 306960), ("Khác", -20000)], lambda k: bo_ma(k[0], "channel", "total")),
			("Thủ kho (RLS khách → Khác)", [("Khác", 790960)], lambda k: bo_ma(k[1], "channel", "total")),
			("(NULL) → 0 dòng", [], lambda k: k[2])])
	top = [goi("dashboard_top_customers", "CHU", p_period_start="2026-11-01", p_limit=x) for x in (5, 1, 0, -5, None)]
	kb("VB-B03", "S1", "dashboard_top_customers: p_limit biên, thủ kho", [*top, goi("dashboard_top_customers", "CHU", p_period_start="2026-11-01"),
		goi("dashboard_top_customers", "TK", p_period_start="2026-11-01", p_limit=5)],
		lech=["lim tính ở Python: p_limit None → 100, thiếu → 5, còn lại max(1, min(int, 100)) — KHÔNG chép GREATEST/LEAST (MariaDB trả NULL khi có NULL); "
			"khách chỉ có hàng trả không hiện; store_name khách không thấy = 'N/A'"],
		kiem=[("(5)", [("0911000001", "Tap hoa Hai", 504000, 1), ("0911000002", "Sieu thi Ba", 306960, 1), ("0911000003", "Quan Tu", -20000, 1)],
				lambda k: bo_ma(k[0], "customer_id", "store_name", "total", "order_count")),
			("số dòng p_limit 1 / 0 / −5 / NULL / bỏ tham số", [1, 1, 1, 3, 3], lambda k: [len(k[i]) for i in range(1, 6)]),
			("p_limit 1 → K1 504.000", [("0911000001", 504000)], lambda k: bo_ma(k[1], "customer_id", "total")),
			("Thủ kho: 3 dòng cùng số, store_name N/A", [("N/A", 504000), ("N/A", 306960), ("N/A", -20000)], lambda k: bo_ma(k[6], "store_name", "total"))])
	kb("VB-B04", "S1", "mốc 15/11 và 21/11 — doanh thu âm, không cận trên (Chủ)", [goi(h, "CHU", p_period_start=d) for d in ("2026-11-15", "2026-11-21")
		for h in ("dashboard_summary", "dashboard_channel_revenue", "dashboard_top_customers")],
		lech=["Q11 chép y (phiếu trả đề ngày tương lai vẫn trừ)"],
		kiem=[("15/11 summary", (209200, 1, 830960, 1), lambda k: bo_ma(k[0], *DS)[0]),
			("15/11 channel", [("Khác", 220000), ("MT", -10800)], lambda k: bo_ma(k[1], "channel", "total")),
			("15/11 top", [("0911000003", 220000, 1)], lambda k: bo_ma(k[2], "customer_id", "total", "order_count")),
			("21/11 summary (âm)", (-10800, 0, 830960, 1), lambda k: bo_ma(k[3], *DS)[0]),
			("21/11 channel", [("MT", -10800)], lambda k: bo_ma(k[4], "channel", "total")),
			("21/11 top rỗng", [], lambda k: k[5])])
	kb("VB-B05", "S1", "dashboard dưới NVBH ('2026-11-01')", [goi(h, n, p_period_start="2026-11-01") for n in ("NV_AN", "NV_BINH")
		for h in ("dashboard_summary", "dashboard_channel_revenue", "dashboard_top_customers")],
		kiem=[("NV An summary", (484000, 2, 524000, 1), lambda k: bo_ma(k[0], *DS)[0]),
			("NV An channel", [("GT", 504000), ("Khác", -20000)], lambda k: bo_ma(k[1], "channel", "total")),
			("NV An top", [("0911000001", 504000, 1), ("0911000003", -20000, 1)], lambda k: bo_ma(k[2], "customer_id", "total", "order_count")),
			("NV Bình summary", (306960, 1, 306960, 0), lambda k: bo_ma(k[3], *DS)[0]),
			("NV Bình channel / top", ([("MT", 306960)], [("0911000002", 306960, 1)]), lambda k: (bo_ma(k[4], "channel", "total"),
				bo_ma(k[5], "customer_id", "total", "order_count")))])
	kb("VB-B06", "S1", "v_hoa_don_con_lai (bài hồi quy — cổng đã có)", [goi("bang:v_hoa_don_con_lai", "CHU"), goi("bang:v_hoa_don_con_lai", "NV_AN"),
		dict(goi("bang:v_hoa_don_con_lai", "CHU"), bo="S2"), dict(goi("bang:v_hoa_don_con_lai", "CHU"), bo="S4")],
		lech=["Frappe: đã có (cong/bang/hoa_don.py — luật mig 257) — bài hồi quy"],
		kiem=[("Sổ BC Chủ (HĐ, trạng thái, con_lai)", [("HD-0001", "posted", 504000), ("HD-0002", "posted", 317760), ("HD-0003", "cancelled", 720000),
				("HD-0004", "posted", 240000), ("HD-0005", "posted", 220000)], lambda k: bo_ma(k[0], "id", "status", "con_lai")),
			("NV An", [("HD-0001", 504000), ("HD-0004", 240000), ("HD-0005", 220000)], lambda k: bo_ma(k[1], "id", "con_lai")),
			("S2 HD-0002-1 / HD-0002", [("HD-0002", "cancelled", 337200), ("HD-0002-1", "posted", 308040)], lambda k: [x for x in bo_ma(k[2], "id", "status",
				"con_lai") if x[0].startswith("HD-0002")]),
			("S4 HĐ6", ("HD-0006", 10000), lambda k: bo_ma([tim(k[3], id="HD-0006")], "id", "con_lai")[0])])

	# ---------------------------------------------------------------------------------------------------------------- C
	HL = ("k", "p", "di", "tra", "sl", "lan", "cuoi")
	kb("VB-C01", "S1", "hang_khach_da_lay — NV An tự gọi", [goi("hang_khach_da_lay", "NV_AN"), goi("hang_khach_da_lay", "NV_AN", p_tu="2026-11-15")],
		lech=["Q8: khach / sp / ncc xếp ở Python theo (chuỗi theo điểm mã, id) như collation C.UTF-8 của bản tham chiếu ('Quan Tu' trước 'Tap hoa Hai')",
			"Q7: SL dòng trả quy đổi theo danh mục HIỆN TẠI", "Hàm DEFINER — đọc thẳng sổ, không vế RLS cổng; nhận POST"],
		kiem=[("nv", "nv.an@sobc.vn", lambda k: k[0]["nv"]),
			("khach (tên, tuyến, NV chính, trạng thái)", [("Quan Tu", "", "NV An", "active"), ("Tap hoa Hai", "GT", "NV An", "active")],
				lambda k: bo_ma(k[0]["khach"], "store_name", "channel", "nv_chinh", "status")),
			("hang", [("0911000001", "SP1", 72, 3, 69, 2, "2026-11-03"), ("0911000003", "SP1", 24, 26, -2, 1, "2026-11-20")], lambda k: bo_ma(k[0]["hang"], *HL)),
			("sp / ncc", ([("SP1", "Nuoc ngot", "lon", "Cty Nuoc")], ["Cty Nuoc"]), lambda k: (bo_ma(k[0]["sp"], "sku", "name", "base_unit", "ncc"),
				[x["name"] for x in k[0]["ncc"]])),
			("p_tu 15/11: hang", [("0911000003", "SP1", 24, 2, 22, 1, "2026-11-20")], lambda k: bo_ma(k[1]["hang"], *HL)),
			("p_tu 15/11: khach vẫn đủ 2", 2, lambda k: len(k[1]["khach"]))])
	kb("VB-C02", "S1", "hang_khach_da_lay — Chủ theo NV Bình; Chủ theo danh sách khách", [goi("hang_khach_da_lay", "CHU", p_nv="@nv:nv.binh@sobc.vn"),
		goi("hang_khach_da_lay", "CHU", p_khach=["@kh:0911000001"]), goi("hang_khach_da_lay", "CHU", p_khach=["@kh:0911000001"], p_tu="2026-11-01")],
		lech=["Q8 (thứ tự chữ) như VB-C01"],
		kiem=[("p_nv NV Bình: nv / khach", ("nv.binh@sobc.vn", [("Quan Tu", "NV An"), ("Sieu thi Ba", "NV Binh")]), lambda k: (k[0]["nv"],
				bo_ma(k[0]["khach"], "store_name", "nv_chinh"))),
			("p_nv NV Bình: hang / sp / ncc", ([("0911000002", "SP2", 20, 6, 14, 1, "2026-11-10")], ["SP2"], ["Cty Banh"]), lambda k: (bo_ma(k[0]["hang"], *HL),
				[x["sku"] for x in k[0]["sp"]], [x["name"] for x in k[0]["ncc"]])),
			("p_khach [K1]: nv / khach", (None, ["Tap hoa Hai"]), lambda k: (k[1]["nv"], [x["store_name"] for x in k[1]["khach"]])),
			("p_khach [K1]: hang", [("0911000001", "SP1", 72, 3, 69, 2, "2026-11-03"), ("0911000001", "SP2", 10, 0, 10, 1, "2026-11-03")],
				lambda k: bo_ma(k[1]["hang"], *HL)),
			("p_khach [K1]: sp / ncc (xếp tên)", (["Banh quy", "Nuoc ngot"], ["Cty Banh", "Cty Nuoc"]), lambda k: ([x["name"] for x in k[1]["sp"]],
				[x["name"] for x in k[1]["ncc"]])),
			("+ p_tu 01/11", [("0911000001", "SP1", 48, 3, 45, 1, "2026-11-03"), ("0911000001", "SP2", 10, 0, 10, 1, "2026-11-03")], lambda k: bo_ma(k[2]["hang"], *HL))])
	kb("VB-C03", "S1", "hang_khach_da_lay — lọc tuyến, NVBH bị ép về mình, rỗng, lỗi", [
		goi("hang_khach_da_lay", "CHU", p_nv="@nv:nv.an@sobc.vn", p_tuyen=["GT"]),
		goi("hang_khach_da_lay", "CHU", p_nv="@nv:nv.an@sobc.vn", p_tuyen=["__chua_co_tuyen"]),
		goi("hang_khach_da_lay", "NV_AN", p_nv="@nv:nv.binh@sobc.vn", p_khach=["@kh:0911000002"]),
		goi("hang_khach_da_lay", "NV_AN", p_khach=["@kh:0911000001", "@kh:0911000002"]),
		goi("hang_khach_da_lay", "CHU"), goi("hang_khach_da_lay", "CHU", p_khach=[]),
		goi("hang_khach_da_lay", "TK", p_khach=["@kh:0911000001"]), goi("hang_khach_da_lay", "CHU", p_nv="@la"),
		goi("hang_khach_da_lay", "QL", p_nv="@nv:nv.an@sobc.vn", p_tu="2026-11-01")],
		lech=["Frappe: p_khach = [] → không khách nào (khác None); lỗi P0001 giữ nguyên văn (NppLoi); '@la' = id không thuộc NPP → KHONG_TIM_THAY_NV"],
		kiem=[("tuyến GT", (["Tap hoa Hai"], [("0911000001", "SP1", 72, 3, 69, 2)]), lambda k: ([x["store_name"] for x in k[0]["khach"]],
				bo_ma(k[0]["hang"], *HL[:6]))),
			("tuyến __chua_co_tuyen", (["Quan Tu"], [("0911000003", "SP1", 24, 26, -2, 1)]), lambda k: ([x["store_name"] for x in k[1]["khach"]],
				bo_ma(k[1]["hang"], *HL[:6]))),
			("NV An gửi p_nv NV Bình + K2", ("nv.an@sobc.vn", [], [], [], ["Cty Nuoc"]), lambda k: (k[2]["nv"], k[2]["khach"], k[2]["hang"], k[2]["sp"],
				[x["name"] for x in k[2]["ncc"]])),
			("NV An gửi [K1, K2] → chỉ K1", ["Tap hoa Hai"], lambda k: [x["store_name"] for x in k[3]["khach"]]),
			("Chủ không tham số", {"nv": None, "khach": [], "hang": [], "sp": [], "ncc": []}, lambda k: k[4]),
			("p_khach '{}'", {"nv": None, "khach": [], "hang": [], "sp": [], "ncc": []}, lambda k: k[5]),
			("Thủ kho → P0001", ("P0001", "KHONG_DU_QUYEN: vai này không xem hàng khách đã lấy"), lambda k: (k[6]["ma_loi"], k[6]["loi"])),
			("id lạ → KHONG_TIM_THAY_NV", ("P0001", "KHONG_TIM_THAY_NV"), lambda k: (k[7]["ma_loi"], k[7]["loi"])),
			("Quản lý p_nv NV An p_tu 01/11", [("0911000001", "SP1", 48, 3, 45, 1), ("0911000003", "SP1", 24, 26, -2, 1)], lambda k: bo_ma(k[8]["hang"], *HL[:6]))])
	kb("VB-C04", "S6", "SECURITY DEFINER — NV Bình thấy hàng NV An bán cho khách mình phụ trách phụ", [goi("hang_khach_da_lay", "NV_BINH"),
		goi("bao_cao_so_ban", "NV_BINH", **T11)],
		lech=["Frappe: hàm DEFINER không lọc người đứng tên HĐ; bao_cao_so_ban (INVOKER) dưới NV Bình không có HĐ mới"],
		kiem=[("khach", ["Quan Tu", "Sieu thi Ba"], lambda k: [x["store_name"] for x in k[0]["khach"]]),
			("hang", [("0911000002", "SP2", 20, 6, 14, 1, "2026-11-10"), ("0911000003", "SP3", 3, 0, 3, 1, "2026-11-22")], lambda k: bo_ma(k[0]["hang"], *HL)),
			("sp (tên, NCC)", [("Banh quy", "Cty Banh"), ("Keo", None)], lambda k: bo_ma(k[0]["sp"], "name", "ncc")),
			("ncc", ["Cty Banh"], lambda k: [x["name"] for x in k[0]["ncc"]]),
			("bao_cao_so_ban NV Bình hd", ["HD-0002"], lambda k: [h["id"] for h in k[1]["hd"]])])

	# ---------------------------------------------------------------------------------------------------------------- D (Nền N)
	A, NM, NH, K3N = ORG_N, NGUOI_N["NV_MOT"][0], NGUOI_N["NV_HAI"][0], KHACH_N["K3"][0]
	kb10 = {"ma": "KB10", "mo_ta": "xoá mọi công nợ + khoản thu của NPP A; thêm 9 dòng nợ không HĐ của K3 do NV Hai giữ (tiền / đã thu / hạn / trạng thái): "
		"1.000 / 0 / 16/11 (T) / open; 2.000 / 0 / 15/11 / open; 4.000 / 0 / 17/10 / open; 8.000 / 0 / 16/10 / open; 16.000 / 0 / 17/09 / open; 32.000 / 0 / 16/09 / "
		"open; 64.000 / 0 / không hạn / open; 128.000 / 0 / 31/12 / overdue (dấu tay, chưa tới hạn); 256.000 / 256.000 / 01/01 / paid", "sql": (f"DELETE FROM payments WHERE receivable_id IN (SELECT id FROM receivables WHERE org_id = '{A}'); DELETE FROM receivables WHERE org_id = '{A}'; "
		"INSERT INTO receivables (org_id, customer_id, sales_user_id, amount, paid, due_date, status, opening_balance, created_at) VALUES "
		+ ", ".join(f"('{A}', '{K3N}', '{NH}', {a}, {pd}, {_lit(h)}, '{st}', false, '2026-11-01T08:00:00+07:00')" for a, pd, h, st in (
			(1000, 0, "2026-11-16", "open"), (2000, 0, "2026-11-15", "open"), (4000, 0, "2026-10-17", "open"), (8000, 0, "2026-10-16", "open"),
			(16000, 0, "2026-09-17", "open"), (32000, 0, "2026-09-16", "open"), (64000, 0, None, "open"), (128000, 0, "2026-12-31", "overdue"),
			(256000, 256000, "2026-01-01", "paid"))))}
	kb14 = {"ma": "KB14", "mo_ta": "RC2 (nợ HD2 của K2) chuyển hẳn sang NV Một giữ, giao_tu_nv = NV Hai (như ban_giao_khach chuyển hẳn; phân công khách chưa đổi)",
		"sql": f"UPDATE receivables SET sales_user_id = '{NM}', giao_tu_nv = '{NH}' WHERE id = '{_n(7, 2)}'"}
	kb15 = {"ma": "KB15", "mo_ta": "RC5 (nợ đầu kỳ K3) do NV Một giữ", "sql": f"UPDATE receivables SET sales_user_id = '{NM}' WHERE id = '{_n(7, 5)}'"}
	kb21 = {"ma": "KB21", "mo_ta": "PY4 (trả trước 0 / 300.000 của NCC Ba) chuyển sang NCC Một",
		"sql": "UPDATE payables SET supplier_id = 'c0000000-0000-0000-0000-000000000001' WHERE id = 'd0000000-0000-0000-0000-000000000004'"}
	PN = ("revenue_gross", "returns_value", "revenue", "order_count", "cogs", "returns_cogs", "exp_cogs", "exp_operating", "exp_hr", "exp_financial",
		"exp_tax", "exp_other", "total_expenses")
	CF = ("cash_from_customers", "cash_to_suppliers", "cash_to_expenses")
	BS = ("cash", "accounts_receivable", "inventory", "accounts_payable", "unpaid_expenses", "supplier_prepayments")
	RS = ("total_outstanding", "current_amount", "current_count", "warning_amount", "warning_count", "overdue_amount", "overdue_count", "critical_amount",
		"critical_count")
	RC = ("customer_id", "store_name", "phone", "rep_name", "total_debt", "total_paid", "remaining", "overdue_amount", "credit_limit")
	RR = ("user_id", "full_name", "customer_count", "customers_with_debt", "total_debt", "total_paid", "total_amount", "overdue_amount", "collection_rate", "dso")
	PS = ("supplier_name", "supplier_code", "invoice_count", "total_debt", "total_paid", "remaining", "overdue_count", "total_returned")
	NEN_FR = ("Nền N dựng TAY (trigger tắt) — bài Frappe phát lại bằng RPC P3 / P3c / P3d / P4 / P7 + ghi thẳng có kiểm soát (xem bo.N.frappe); E8 / E9 "
		"('Đảo phiếu trả', '(đã đảo)') không tồn tại trên Frappe (kết quả như nppsale vì nppsale loại chúng)")
	E6 = ("Q2 = 0 (chốt chéo P4): E6 xuất lẻ 'Hư hỏng' — nền N đặt tay giá 8.000 (dòng xuất lẻ thật của nppsale mang 0); Frappe XKL- giá 0 → giá vốn xuất "
		"3.192.000, cogs 2.880.000 (= cột 'nếu Q2 chép y' của đặc tả)")
	kb("VB-D01", "N", "finance_pnl tháng 11 (Chủ, Quản lý, Kế toán)", [goi("finance_pnl", n, **F11) for n in ("CHU", "QL", "KT")],
		lech=[NEN_FR, E6, "Q14: hàm ném PGRST202 tới khi có nguồn expenses / payable_payments / payables (P4 + P7)"],
		kiem=[("Chủ: gross / trả / revenue / số đơn / cogs / trả vốn / 6 nhóm chi / tổng chi", (6940500, 2102000, 4838500, 3, 3072000, 312000, 150000,
				3000000, 5000000, 0, 80000, 50000, 8280000), lambda k: tuple(k[0][0][x] for x in PN)),
			("Quản lý / Kế toán = Chủ", (True, True), lambda k: (k[1] == k[0], k[2] == k[0])),
			("giao diện: lãi gộp / lãi HĐ / lãi thuần", (1766500, -6233500, -6363500), lambda k: (lambda r: (r["revenue"] - r["cogs"],
				r["revenue"] - r["cogs"] - r["exp_operating"] - r["exp_hr"], r["revenue"] - r["cogs"] - r["exp_operating"] - r["exp_hr"] - r["exp_financial"]
				- r["exp_tax"] - r["exp_other"]))(k[0][0])),
			("Báo cáo tổng hợp '− Chi phí' (bỏ nhóm cogs)", 8130000, lambda k: k[0][0]["total_expenses"] - k[0][0]["exp_cogs"])],
		fr=lambda c, k: {i: c.pnl_fr(k[i], F11, n) for i, n in enumerate(("CHU", "QL", "KT"))})
	kb("VB-D02", "N", "tháng 10: finance_pnl và finance_cash_flow (Chủ)", [goi("finance_pnl", "CHU", **F10), goi("finance_cash_flow", "CHU", **F10)],
		lech=[NEN_FR],
		kiem=[("pnl T10", (1000000, 0, 1000000, 1, 384000, 0, 0, 0, 0, 100000, 0, 0, 100000), lambda k: tuple(k[0][0][x] for x in PN)),
			("cash_flow T10", (1000000, 1000000, 0), lambda k: tuple(k[1][0][x] for x in CF))],
		fr=lambda c, k: {0: c.pnl_fr(k[0], F10, "CHU")})
	kb("VB-D03", "N", "finance_pnl tháng 11 dưới RLS — NV Một và Thủ kho", [goi("finance_pnl", "NV_MOT", **F11), goi("finance_pnl", "TK", **F11)],
		lech=[NEN_FR, Q3, Q9, E6, "Frappe: NV Một cogs / returns_cogs null (nếu không che: 3.192.000 / 0 — Q9 không cộng E4 của HĐ huỷ, Q2 E6 = 0); Thủ kho cogs 2.880.000"],
		kiem=[("NV Một", (4940500, 1652000, 3288500, 2, 3684000, 0, 0, 0, 0, 0, 0, 0, 0), lambda k: tuple(k[0][0][x] for x in PN)),
			("Thủ kho", (6940500, 2102000, 4838500, 3, 3072000, 312000, 0, 0, 0, 0, 0, 0, 0), lambda k: tuple(k[1][0][x] for x in PN))],
		fr=lambda c, k: {0: c.pnl_fr(k[0], F11, "NV_MOT"), 1: c.pnl_fr(k[1], F11, "TK")})
	kb("VB-D04", "N", "finance_cash_flow tháng 11 + mốc giờ VN (Chủ)", [goi("finance_cash_flow", "CHU", **F11),
		goi("finance_cash_flow", "CHU", p_from="2026-11-01", p_to="2026-11-01"), goi("finance_cash_flow", "CHU", p_from="2026-10-31", p_to="2026-10-31"),
		dict(goi("finance_cash_flow", "CHU", **F11), ghi_chu="bài Frappe chạy thêm dưới Administrator (bo_qua_rls) — phải ra cùng số Chủ (JOIN dòng nợ, §2.7)")],
		lech=[NEN_FR, "Q4 (đề xuất giữ nppsale): cash_to_suppliers gồm offset PP4 200.000 → 5.200.000 (bỏ offset ở CẢ hai hàm thì 5.000.000)",
			"mốc [p_from 00:00 VN, p_to+1 00:00 VN): PM3 06:30 và PP5 05:00 sáng 01/11 thuộc 01/11"],
		kiem=[("T11", (1200000, 5200000, 3230000), lambda k: tuple(k[0][0][x] for x in CF)),
			("01/11", (200000, 700000, 0), lambda k: tuple(k[1][0][x] for x in CF)),
			("31/10", (0, 0, 0), lambda k: tuple(k[2][0][x] for x in CF)),
			("giao diện: lưu chuyển thuần", -7230000, lambda k: (lambda r: r["cash_from_customers"] - r["cash_to_suppliers"] - r["cash_to_expenses"])(k[0][0]))])
	kb("VB-D05", "N", "finance_balance_sheet('2026-11-30') (Chủ / Kế toán)", [goi("finance_balance_sheet", n, p_as_of="2026-11-30") for n in ("CHU", "KT")],
		lech=[NEN_FR, "Q4: cash trừ cả offset"],
		kiem=[("Chủ", (-6830000, 4288500, 3810000, 7300000, 5150000, 300000), lambda k: tuple(k[0][0][x] for x in BS)),
			("Kế toán = Chủ", True, lambda k: k[1] == k[0]),
			("giao diện: tổng tài sản / nợ phải trả / vốn chủ", (1568500, 12450000, -10881500), lambda k: (lambda r: (r["cash"] + r["accounts_receivable"]
				+ r["inventory"] + r["supplier_prepayments"], r["accounts_payable"] + r["unpaid_expenses"], r["cash"] + r["accounts_receivable"] + r["inventory"]
				+ r["supplier_prepayments"] - r["accounts_payable"] - r["unpaid_expenses"]))(k[0][0]))])
	kb("VB-D06", "N", "finance_balance_sheet('2026-10-31') + Dòng tiền không khép", [goi("finance_balance_sheet", "CHU", p_as_of="2026-10-31"),
		goi("finance_cash_flow", "CHU", **F11), goi("finance_balance_sheet", "CHU", p_as_of="2026-11-30")],
		lech=[NEN_FR, "chép y: cân đối trừ chi theo ngày chi + đã trả HIỆN TẠI, dòng tiền theo ngày trả — X4 lệch 100.000"],
		kiem=[("31/10", (300000, 4288500, 3810000, 7300000, 0, 300000), lambda k: tuple(k[0][0][x] for x in BS)),
			("Dòng tiền tháng 11: đầu kỳ + thu − NCC − chi", -6930000, lambda k: k[0][0]["cash"] + k[1][0]["cash_from_customers"] - k[1][0]["cash_to_suppliers"]
				- k[1][0]["cash_to_expenses"]),
			("cuối kỳ (cân đối 30/11) — lệch 100.000", -6830000, lambda k: k[2][0]["cash"])])
	kb("VB-D07", "N", "receivables_summary (Chủ) = dashboard_summary.open_receivables", [goi("receivables_summary", "CHU"),
		goi("dashboard_summary", "CHU", p_period_start="2026-11-01")],
		lech=[NEN_FR, "receivables_summary đã có trên Frappe (cong_no_doc.py) — bài hồi quy; hôm nay = 16/11/2026"],
		kiem=[("summary", (4288500, 1550000, 2, 2288500, 2, -200000, 1, 650000, 1), lambda k: tuple(k[0][0][x] for x in RS)),
			("dashboard open_receivables / overdue_count", (4288500, 1), lambda k: (k[1][0]["open_receivables"], k[1][0]["overdue_count"]))])
	kb("VB-D08", "N", "mốc tuổi nợ + dấu quá hạn (biến thể KB10)", [dict(goi(h, "CHU"), bien_the=kb10) for h in ("receivables_summary", "receivables_by_rep",
		"receivables_by_customer")],
		lech=[NEN_FR, "biến thể: xoá công nợ / khoản thu NPP A, thêm 9 dòng nợ đầu kỳ K3 do NV Hai giữ (ghi thẳng — bài Frappe: cổng receivables nợ đầu kỳ + dấu "
			"quá hạn; dòng paid: thu đủ bằng phiếu thu)", "R12: rep_name dự phòng = NV giữ nợ id nhỏ nhất (Frappe email — chỉ một NV ở đây)"],
		kiem=[("summary", (255000, 193000, 3, 6000, 2, 24000, 2, 32000, 1), lambda k: tuple(k[0][0][x] for x in RS)),
			("by_rep NV Hai", [("nv.hai@nenn.vn", "NV Hai", 1, 1, 255000, 256000, 511000, 128000, 50, 23)], lambda k: bo_ma(k[1], *RR)),
			("by_customer K3", [("0900000003", 255000, 0, 255000, 128000, 0, "NV Hai")], lambda k: bo_ma(k[2], "customer_id", "total_debt", "total_paid",
				"remaining", "overdue_amount", "credit_limit", "rep_name"))])
	kb("VB-D09", "N", "receivables_by_customer (Chủ)", [goi("receivables_by_customer", "CHU")], lech=[NEN_FR],
		kiem=[("3 dòng", [("0900000002", "Tạp hoá Hai", "0900000002", "NV Hai", 1850000, 0, 1850000, 300000, 0),
				("0900000001", "Tạp hoá Một", "0900000001", "NV Một", 3988500, 2200000, 1788500, 0, 5000000),
				("0900000003", "Tạp hoá Ba", "0900000003", "-", 700000, 50000, 650000, 0, 0)], lambda k: bo_ma(k[0], *RC)),
			("Σ remaining", 4288500, lambda k: tong(k[0], "remaining"))])
	kb("VB-D10", "N", "receivables_by_rep (Chủ)", [goi("receivables_by_rep", "CHU")], lech=[NEN_FR],
		kiem=[("3 dòng", [("nv.mot@nenn.vn", "NV Một", 2, 2, 2088500, 2200000, 4288500, 300000, 51, 12),
				("nv.hai@nenn.vn", "NV Hai", 2, 1, 1550000, 400000, 1950000, 0, 21, 0),
				(None, "(Chưa gán nhân viên)", 1, 1, 650000, 50000, 700000, 0, 7, 107)], lambda k: bo_ma(k[0], *RR))])
	kb("VB-D11", "N", "mọi hàm công nợ / tiền dưới NV Một", [goi("receivables_summary", "NV_MOT"), goi("receivables_by_customer", "NV_MOT"),
		goi("receivables_by_rep", "NV_MOT"), goi("bao_cao_cong_no", "NV_MOT", p_tu_thu="2026-05-20", p_tu_90="2026-08-17"),
		goi("finance_cash_flow", "NV_MOT", **F11), goi("finance_balance_sheet", "NV_MOT", p_as_of="2026-11-30"), goi("payables_by_supplier", "NV_MOT"),
		goi("payables_summary", "NV_MOT", p_since="2026-11-01T00:00:00")],
		lech=[NEN_FR, Q3, "Frappe: finance_balance_sheet.inventory = null với NV Một"],
		kiem=[("summary", (2088500, 0, 0, 2288500, 2, -200000, 1, 0, 0), lambda k: tuple(k[0][0][x] for x in RS)),
			("by_customer", [("0900000001", 3988500, 2200000, 1788500, 0, 5000000, "NV Một"), ("0900000002", 300000, 0, 300000, 300000, 0, "NV Hai")],
				lambda k: sorted(bo_ma(k[1], "customer_id", "total_debt", "total_paid", "remaining", "overdue_amount", "credit_limit", "rep_name"))),
			("by_rep chỉ NV Một", [("nv.mot@nenn.vn", "NV Một", 2, 2, 2088500, 2200000, 4288500, 300000, 51, 12)], lambda k: bo_ma(k[2], *RR)),
			("cong_no mo / gan90 / thu", ((3, 3, 3), ["RC1", "RC3", "RC4"]), lambda k: ((len(k[3]["mo"]), len(k[3]["gan90"]), len(k[3]["thu"])),
				[x["id"] for x in k[3]["mo"]])),
			("cash_flow", (1200000, 0, 0), lambda k: tuple(k[4][0][x] for x in CF)),
			("balance", (2200000, 2088500, 3810000, 0, 0, 0), lambda k: tuple(k[5][0][x] for x in BS)),
			("payables_by_supplier / payables_summary", ([], (0, 0)), lambda k: (k[6], (k[7][0]["open_payables"], k[7][0]["month_total"])))],
		fr=lambda c, k: {5: c.che(k[5], [0], ("inventory",))})
	kb("VB-D12", "N", "bàn giao chuyển hẳn RC2 từ NV Hai sang NV Một (biến thể KB14)", [dict(goi("receivables_by_rep", "CHU"), bien_the=kb14),
		dict(goi("receivables_summary", "NV_MOT"), bien_the=kb14), dict(goi("bao_cao_cong_no", "NV_MOT", p_tu_thu="2026-05-20", p_tu_90="2026-08-17"), bien_the=kb14),
		dict(goi("receivables_by_customer", "NV_MOT"), bien_the=kb14)],
		lech=[NEN_FR, "biến thể = ban_giao_khach chuyển hẳn (nợ chưa thu sang NV nhận, giao_tu_nv = NV giao) — bài Frappe: RPC ban_giao_khach (P2) hoặc ghi "
			"thẳng NPP Cong No.nhan_vien + giao_tu_nv", "R11: NV nhận không thấy HĐ gốc / khoản thu cũ (RLS) — hành vi nppsale giữ nguyên"],
		kiem=[("by_rep (NV, nợ, đã thu, tổng, KH có nợ, tỉ lệ, DSO)", [("nv.mot@nenn.vn", 3788500, 2300000, 6088500, 2, 38, 8), (None, 650000, 50000, 700000, 1, 7, 107),
				("nv.hai@nenn.vn", -150000, 300000, 150000, 0, 100, 0)], lambda k: bo_ma(k[0], "user_id", "total_debt", "total_paid", "total_amount",
				"customers_with_debt", "collection_rate", "dso")),
			("NV Một summary total / current", (3788500, 1700000, 1), lambda k: (k[1][0]["total_outstanding"], k[1][0]["current_amount"], k[1][0]["current_count"])),
			("NV Một cong_no mo 4, RC2 invoice null, thu 3", (4, None, 3), lambda k: (len(k[2]["mo"]), tim(k[2]["mo"], id="RC2").get("invoice"), len(k[2]["thu"]))),
			("NV Một by_customer K2 remaining / rep", (2000000, "NV Hai"), lambda k: (lambda r: (r["remaining"], r["rep_name"]))(tim(k[3], customer_id="0900000002")))])
	kb("VB-D13", "N", "NVBH giữ nợ của khách mình không thấy (biến thể KB15)", [dict(goi("receivables_by_customer", "NV_MOT"), bien_the=kb15)],
		lech=[NEN_FR, "R12: rep_name dự phòng = NV giữ nợ (MIN sales_user_id)"],
		kiem=[("dòng K3 thêm", ("-", "-", "NV Một", 700000, 50000, 650000, 0, 0), lambda k: bo_ma([tim(k[0], customer_id="0900000003")], "store_name", "phone",
			"rep_name", "total_debt", "total_paid", "remaining", "overdue_amount", "credit_limit")[0])])
	kb("VB-D14", "N", "bao_cao_cong_no (Chủ, X = 16/11/2026)", [goi("bao_cao_cong_no", "CHU", p_tu_thu="2026-05-20", p_tu_90="2026-08-17"),
		goi("bao_cao_cong_no", "CHU", p_tu_thu=None, p_tu_90=None)],
		lech=[NEN_FR, "bao_cao_cong_no đã có trên Frappe — bài hồi quy; tham số sai dạng nên dùng _ngay (22007) cho thống nhất (§2.12)"],
		kiem=[("mo / gan90 / thu", (["RC1", "RC2", "RC3", "RC4", "RC5", "RC6"], ["RC1", "RC2", "RC3", "RC4", "RC6", "RC7"],
				["PM1", "PM2", "PM3", "PM4", "PM5", "PM6", "PM7"]), lambda k: ([x["id"] for x in k[0]["mo"]], [x["id"] for x in k[0]["gan90"]],
				[x["id"] for x in k[0]["thu"]])),
			("RC1 invoice", {"invoice_code": "HD-0001", "invoice_date": "2026-11-02"}, lambda k: tim(k[0]["mo"], id="RC1")["invoice"]),
			("RC5 / RC6 invoice null; RC6 return_id", (None, None, "R5"), lambda k: (tim(k[0]["mo"], id="RC5")["invoice"], tim(k[0]["mo"], id="RC6")["invoice"],
				tim(k[0]["mo"], id="RC6")["return_id"])),
			("(NULL, NULL)", (6, [], []), lambda k: (len(k[1]["mo"]), k[1]["gan90"], k[1]["thu"]))])
	kb("VB-D15", "N", "bao_cao_ton_kho 90 ngày + stock_value_summary", [goi("bao_cao_ton_kho", n, p_tu="2026-08-19", p_den="2026-11-16") for n in ("CHU", "TK", "NV_MOT")]
		+ [goi("bao_cao_ton_kho", "CHU", p_tu="2026-11-30", p_den="2026-11-01")] + [goi("stock_value_summary", n) for n in ("CHU", "TK", "NV_MOT", "KHOA", "CHU_B")],
		lech=[NEN_FR, Q3, "Frappe: lo.id = '<lô>::<vùng>' (tệp vàng đã chuẩn hoá về dạng này); NV Một lo[].unit_cost null, stock_value_summary.inventory_value null "
			"(batch_count vẫn 3); tài khoản khoá (0, 0); Chủ B không dựng được (một site = một NPP — R16)"],
		kiem=[("lo (id, SL, giá, hạn)", [("L-A::sale", 240, 8000, "2027-06-30"), ("L-B::sale", 30, 60000, "2027-03-31"), ("L-D::date", 12, 7500, "2026-12-10")],
				lambda k: bo_ma(k[0]["lo"], "id", "qty_on_hand", "unit_cost", "expires_at")),
			("lo 7 khoá / dòng 7", (True, 7), lambda k: (all(len(x) == 7 for x in k[0]["lo"]), len(k[0]["dong"]))),
			("dong (HĐ, SKU, đổi)", [("HD-0001", "SP1", False), ("HD-0001", "SP2", False), ("HD-0001", "SP2", True), ("HD-0002", "SP2", False),
				("HD-0003", "SP1", False), ("HD-0005", "SP1", False), ("HD-0006", "SP2", False)], lambda k: sorted(bo_ma(k[0]["dong"], "invoice_id", "product_id",
				"is_exchange"))),
			("Thủ kho = Chủ; NV Một lo 3 / dong 5", (True, 3, 5), lambda k: (k[1] == k[0], len(k[2]["lo"]), len(k[2]["dong"]))),
			("đảo kỳ → dong rỗng", [], lambda k: k[3]["dong"]),
			("Màn Kho: SP1 tồn / giá trị / sl30", (252, 2010000, 192), lambda k: (sum(x["qty_on_hand"] for x in k[0]["lo"] if x["product_id"] == "SP1"),
				sum(x["qty_on_hand"] * x["unit_cost"] for x in k[0]["lo"] if x["product_id"] == "SP1"),
				sum(x["quantity"] * x["conversion_factor"] for x in k[0]["dong"] if x["product_id"] == "SP1" and not x["is_exchange"] and x["ngay"] >= "2026-10-18"))),
			("Màn Kho: SP2 tồn / giá trị / sl30", (30, 1800000, 30), lambda k: (sum(x["qty_on_hand"] for x in k[0]["lo"] if x["product_id"] == "SP2"),
				sum(x["qty_on_hand"] * x["unit_cost"] for x in k[0]["lo"] if x["product_id"] == "SP2"),
				sum(x["quantity"] * x["conversion_factor"] for x in k[0]["dong"] if x["product_id"] == "SP2" and not x["is_exchange"] and x["ngay"] >= "2026-10-18"))),
			("stock_value_summary Chủ / TK / NV Một / khoá / Chủ B", [(3810000, 3), (3810000, 3), (3810000, 3), (0, 0), (100000, 1)],
				lambda k: [(k[i][0]["inventory_value"], k[i][0]["batch_count"]) for i in range(4, 9)])],
		fr=lambda c, k: {2: c.che_lo(k[2]), 6: c.che(k[6], [0], ("inventory_value",))})
	kb("VB-D16", "N", "payables_by_supplier (Kế toán) + trả trước bù trong CÙNG một NCC (biến thể KB21)", [goi("payables_by_supplier", n) for n in ("KT", "TK", "NV_MOT")]
		+ [dict(goi("finance_balance_sheet", "CHU", p_as_of="2026-11-30"), bien_the=kb21), dict(goi("payables_by_supplier", "KT"), bien_the=kb21)],
		lech=[NEN_FR, "payables_by_supplier dựng ở P4 (rpc/cong_no_ncc.py) — bài so; supplier_code = Supplier.npp_ma ('-' khi trống)"],
		kiem=[("Kế toán", [("NCC Một", "N1", 2, 9500000, 4000000, 5500000, 0, 500000), ("NCC Hai", "N2", 1, 2000000, 200000, 1800000, 1, 0),
				("NCC Ba", "-", 1, 0, 300000, -300000, 0, 0)], lambda k: bo_ma(k[0], *PS)),
			("Thủ kho / NV Một", ([], []), lambda k: (k[1], k[2])),
			("biến thể: balance AP / prepay / cash", (7000000, 0, -6830000), lambda k: (k[3][0]["accounts_payable"], k[3][0]["supplier_prepayments"], k[3][0]["cash"])),
			("biến thể: by_supplier", [("NCC Một", "N1", 3, 9500000, 4300000, 5200000, 0, 500000), ("NCC Hai", "N2", 1, 2000000, 200000, 1800000, 1, 0)],
				lambda k: bo_ma(k[4], *PS))])
	kb("VB-D17", "N", "payables_summary và mốc p_since không múi giờ (Kế toán)", [goi("payables_summary", "KT", p_since="2026-11-01T00:00:00"),
		goi("payables_summary", "KT", p_since="2026-11-01T00:00:00+07:00"), goi("payables_summary", "KT", p_since=None),
		goi("payables_summary", "TK", p_since="2026-11-01T00:00:00"), goi("payables_summary", "NV_MOT", p_since="2026-11-01T00:00:00")],
		lech=[NEN_FR, "Q5 (⚠K nhỏ): chuỗi KHÔNG múi giờ hiểu theo giờ VN — Frappe ('2026-11-01T00:00:00') → month_total 10.200.000 (nppsale hiểu là UTC = 07:00 VN "
			"→ 9.500.000)"],
		kiem=[("'…T00:00:00' (UTC ở nppsale)", (7000000, 9500000), lambda k: (k[0][0]["open_payables"], k[0][0]["month_total"])),
			("'…T00:00:00+07:00'", (7000000, 10200000), lambda k: (k[1][0]["open_payables"], k[1][0]["month_total"])),
			("NULL", (7000000, 0), lambda k: (k[2][0]["open_payables"], k[2][0]["month_total"])),
			("Thủ kho / NV Một", [(0, 0), (0, 0)], lambda k: [(k[i][0]["open_payables"], k[i][0]["month_total"]) for i in (3, 4)])],
		fr=lambda c, k: {0: [dict(k[0][0], month_total=k[1][0]["month_total"])]})
	KH = [goi("finance_pnl", "KHOA", **F11), goi("finance_cash_flow", "KHOA", **F11), goi("finance_balance_sheet", "KHOA", p_as_of="2026-11-30"),
		goi("receivables_summary", "KHOA"), goi("receivables_by_customer", "KHOA"), goi("receivables_by_rep", "KHOA"), goi("stock_value_summary", "KHOA"),
		goi("payables_summary", "KHOA", p_since="2026-11-01T00:00:00"), goi("payables_by_supplier", "KHOA"), goi("bao_cao_so_ban", "KHOA", **T11),
		goi("bao_cao_ton_kho", "KHOA", p_tu="2026-08-19", p_den="2026-11-16"), goi("bao_cao_cong_no", "KHOA", p_tu_thu="2026-05-20", p_tu_90="2026-08-17"),
		goi("dashboard_summary", "KHOA", p_period_start="2026-11-01")]
	CB = [dict(goi(h, "CHU_B", **ts_), chi_nppsale=True) for h, ts_ in (("finance_pnl", F11), ("finance_cash_flow", F11),
		("finance_balance_sheet", {"p_as_of": "2026-11-30"}), ("receivables_by_rep", {}), ("receivables_by_customer", {}), ("receivables_summary", {}))]
	kb("VB-D18", "N", "cô lập NPP + tài khoản khoá", KH + CB,
		lech=[NEN_FR, "R16: một site = một NPP — sáu lời gọi Chủ B mang chi_nppsale (bài Frappe bỏ); tài khoản khoá = NPP Nhan Vien dang_hoat_dong = 0 → vai None → "
			"mọi hàm 'rỗng đúng dạng' (dict mảng rỗng / một dòng toàn 0 / list rỗng), không lỗi"],
		kiem=[("khoá: pnl / cash_flow / balance toàn 0", (0, 0, 0), lambda k: (sum(abs(v) for v in k[0][0].values()), sum(abs(v) for v in k[1][0].values()),
				sum(abs(v) for v in k[2][0].values()))),
			("khoá: summary 0, by_customer / by_rep []", (0, [], []), lambda k: (sum(abs(v) for v in k[3][0].values()), k[4], k[5])),
			("khoá: stock_value_summary", (0, 0), lambda k: (k[6][0]["inventory_value"], k[6][0]["batch_count"])),
			("khoá: payables (0, 0) / []", ((0, 0), []), lambda k: ((k[7][0]["open_payables"], k[7][0]["month_total"]), k[8])),
			("khoá: bao_cao_so_ban / ton_kho / cong_no rỗng", ({x: [] for x in SAU_KHOA}, {"lo": [], "dong": []}, {"mo": [], "gan90": [], "thu": []}),
				lambda k: (k[9], k[10], k[11])),
			("khoá: dashboard_summary", (0, 0, 0, 0), lambda k: bo_ma(k[12], *DS)[0]),
			("Chủ B pnl revenue / số đơn / cogs / exp_other / tổng chi", (9999000, 1, 10000, 1000, 1000), lambda k: tuple(k[13][0][x] for x in ("revenue",
				"order_count", "cogs", "exp_other", "total_expenses"))),
			("Chủ B cash_flow", (9999000, 0, 1000), lambda k: tuple(k[14][0][x] for x in CF)),
			("Chủ B balance", (9998000, 0, 100000, 0, 0, 0), lambda k: tuple(k[15][0][x] for x in BS)),
			("Chủ B by_rep", [("Chủ B", 1, 0, 0, 9999000, 9999000, 100, 0)], lambda k: bo_ma(k[16], "full_name", "customer_count", "customers_with_debt",
				"total_debt", "total_paid", "total_amount", "collection_rate", "dso")),
			("Chủ B by_customer [] / summary 0", ([], 0), lambda k: (k[17], sum(abs(v) for v in k[18][0].values())))])
	kb("VB-D19", "N", "Thủ kho — mọi hàm", [goi("finance_pnl", "TK", **F11), goi("finance_cash_flow", "TK", **F11), goi("finance_balance_sheet", "TK", p_as_of="2026-11-30"),
		goi("receivables_summary", "TK"), goi("receivables_by_customer", "TK"), goi("receivables_by_rep", "TK"), goi("payables_by_supplier", "TK"),
		goi("payables_summary", "TK", p_since="2026-11-01T00:00:00"), goi("stock_value_summary", "TK"),
		goi("bao_cao_ton_kho", "TK", p_tu="2026-08-19", p_den="2026-11-16"), goi("bao_cao_cong_no", "TK", p_tu_thu="2026-05-20", p_tu_90="2026-08-17")],
		lech=[NEN_FR, E6, "Frappe: thủ kho cogs 2.880.000 (Q2 = 0)"],
		kiem=[("pnl revenue / cogs / chi phí", (4838500, 3072000, 0), lambda k: (k[0][0]["revenue"], k[0][0]["cogs"], k[0][0]["total_expenses"])),
			("cash_flow", (0, 0, 0), lambda k: tuple(k[1][0][x] for x in CF)),
			("balance", (0, 0, 3810000, 0, 0, 0), lambda k: tuple(k[2][0][x] for x in BS)),
			("summary 0; by_customer / by_rep / by_supplier []", (0, [], [], []), lambda k: (sum(abs(v) for v in k[3][0].values()), k[4], k[5], k[6])),
			("payables_summary / stock_value", ((0, 0), (3810000, 3)), lambda k: ((k[7][0]["open_payables"], k[7][0]["month_total"]),
				(k[8][0]["inventory_value"], k[8][0]["batch_count"]))),
			("ton_kho lo 3 / dong 7; cong_no rỗng", (3, 7, {"mo": [], "gan90": [], "thu": []}), lambda k: (len(k[9]["lo"]), len(k[9]["dong"]), k[10]))],
		fr=lambda c, k: {0: c.pnl_fr(k[0], F11, "TK")})
	kb("VB-D20", "N", "tham số NULL (Chủ)", [goi("finance_balance_sheet", "CHU", p_as_of=None), goi("finance_pnl", "CHU", p_from=None, p_to="2026-11-30"),
		goi("finance_cash_flow", "CHU", p_from="2026-11-01", p_to=None), goi("payables_summary", "CHU", p_since=None),
		goi("bao_cao_ton_kho", "CHU", p_tu=None, p_den=None), goi("bao_cao_cong_no", "CHU", p_tu_thu=None, p_tu_90=None)],
		lech=[NEN_FR],
		kiem=[("balance(NULL)", (0, 4288500, 3810000, 7300000, 0, 300000), lambda k: tuple(k[0][0][x] for x in BS)),
			("pnl / cash_flow toàn 0", (0, 0), lambda k: (sum(abs(v) for v in k[1][0].values()), sum(abs(v) for v in k[2][0].values()))),
			("payables_summary(NULL)", (7000000, 0), lambda k: (k[3][0]["open_payables"], k[3][0]["month_total"])),
			("ton_kho(NULL, NULL)", (3, []), lambda k: (len(k[4]["lo"]), k[4]["dong"])),
			("cong_no(NULL, NULL)", (6, [], []), lambda k: (len(k[5]["mo"]), k[5]["gan90"], k[5]["thu"]))])

	# ---------------------------------------------------------------------------------------------------------------- E
	E29 = {"p_tu": "2026-09-29", "p_den": "2026-09-29"}
	HB = ("listed", "revenue", "diff", "docDiscount", "thueLamTron", "returnQty", "returnValue", "diffReturn", "netRevenue", "diffNet", "tongChenh")
	E2E_FR = ("bộ E2E: phiếu trả TR-ML-1 KHÔNG NV, KHÔNG HĐ chỉ có từ dữ liệu chuyển (phiếu tự lập Frappe luôn có người) → bài dựng bằng ghi thẳng; mã HĐ phải giữ "
		"thứ tự HD-ML-A < HD-ML-B theo mã điểm (nhanVienPhieuTra đoán NV theo HĐ GẶP TRƯỚC)")
	kb("VB-E01", "E2E", "Bán hàng một ngày (e2e bao-cao-cu-mot-luot, 29/09/2026) — máy chủ + mã TS", [goi("bao_cao_so_ban", "CHU", **E29), ts(0)],
		nguon=["chay_that", "ts", "dac_ta"], lech=[E2E_FR, "SE-ML-DAO ('Đảo phiếu trả') không tồn tại trên Frappe; SE-ML-HUY là phiếu của HĐ huỷ (docstatus 2) — cùng số"],
		ky_vong="Chủ mở /bao-cao/ban-hang?ky=custom&ca=2026-09-29&cb=2026-09-29 (chế độ Mặt hàng, Nhân viên): chỉ GET /rest/v1/rpc/bao_cao_so_ban (kỳ + kỳ so sánh), "
			"không câu nào tới sales_invoice_lines / return_lines / stock_entry_lines / batches. Thẻ: Doanh thu 1.130.000; Hàng trả 42.000; DT thuần 1.088.000; "
			"Số HĐ 2; Khách mua 1; Lãi gộp 248.000. Mặt hàng: '2 thùng 10 hộp'. Nhân viên — NV A: Doanh thu 920.000, Hàng trả 42.000, DT thuần 878.000, Theo bảng "
			"giá 900.000, Chênh lệch bán 40.000, Giảm giá đơn −20.000, Thuế + làm tròn 0, Chênh lệch trả −2.000, Chênh lệch thuần 38.000, Tổng chênh lệch 18.000, "
			"Lãi gộp 188.000; NV B: 210.000 / 0 / 210.000, chênh bán 10.000, tổng chênh 10.000, Lãi gộp 60.000.",
		kiem=[("máy chủ: hd / gv / gv_tra", (["HD-ML-A", "HD-ML-B"], [("ML1", 58, 870000)], [("TR-ML-1", "ML1", 30000)]), lambda k: ([h["id"] for h in k[0]["hd"]],
				bo_ma(k[0]["gv"], "product_id", "sl", "tien"), bo_ma(k[0]["gv_tra"], "return_id", "product_id", "tien"))),
			("TS tổng rev / ret / net / nInv / nCust / gp", (1130000, 42000, 1088000, 2, 1, 248000), lambda k: tuple(k[1]["tong"][x] for x in ("rev", "ret", "net",
				"nInv", "nCust", "gp"))),
			("TS giá vốn xuất / giá vốn trả", (870000, 30000), lambda k: (k[1]["gia_von_xuat"], sum(v["total"] for v in k[1]["gia_von_tra"].values()))),
			("TS Mặt hàng ML1", (58, "2 thùng 10 hộp"), lambda k: (k[1]["sl_mat_hang"]["ML1"]["sl"], k[1]["sl_mat_hang"]["ML1"]["chu"])),
			("TS phiếu trả cũ quy về NV A", "nv.a@e2e.vn", lambda k: k[1]["nv_phieu_tra"]["TR-ML-1"]),
			("TS NV A rev / ret / net / gp", (920000, 42000, 878000, 188000), lambda k: tuple(k[1]["theo_nv"]["nv.a@e2e.vn"][x] for x in ("rev", "ret", "net", "gp"))),
			("TS NV B rev / ret / net / gp", (210000, 0, 210000, 60000), lambda k: tuple(k[1]["theo_nv"]["nv.b@e2e.vn"][x] for x in ("rev", "ret", "net", "gp"))),
			("TS NV A Theo bảng giá / chênh bán / giảm đơn / thuế+làm tròn / chênh trả / chênh thuần / tổng chênh", (900000, 40000, 20000, 0, -2000, 38000, 18000),
				lambda k: (lambda h: (h["listed"], h["diff"], h["docDiscount"], h["thueLamTron"], h["diffReturn"], h["diffNet"], h["tongChenh"]))(
				tim(k[1]["hang_ban_nv"], id="nv.a@e2e.vn"))),
			("TS NV B chênh bán / tổng chênh", (10000, 10000), lambda k: (lambda h: (h["diff"], h["tongChenh"]))(tim(k[1]["hang_ban_nv"], id="nv.b@e2e.vn")))])
	kb("VB-E02", "E2E", "Hai đường đọc phải ra Y HỆT (một lượt ↔ từng bảng) + tắt hàm", [goi("bao_cao_so_ban", "CHU", **E29), ts(0)], nguon=["dac_ta", "ts"],
		lech=["Lần 2 (cổng trả PGRST202 cho bao_cao_so_ban) cần cổng stock_entries / stock_entry_lines với notes NGUYÊN VĂN 'Nhập lại từ phiếu trả <PT>' dựng từ "
			"Link cho NL- và HDT- có kho (§2.13, M13) — bài e2e portal khi P4 có cổng phiếu kho", "R5: thứ tự id hai đường (mã điểm JS vs collation) — chưa đo"],
		ky_vong="Cùng dữ liệu VB-E01 (và Sổ BC). Lần 1 có hàm: mở /reports/sales (Thời gian, Lợi nhuận, Giảm giá HĐ, Trả hàng, Nhân viên), /reports/customers "
			"(Bán hàng, Lợi nhuận, Hàng bán theo khách — mở dòng khách), /reports/products (Bán hàng, Lợi nhuận, Xuất nhập tồn), /reports/finance, "
			"/analytics/business/overview, cost-profit, /analytics/products/overview, categories; chụp chữ <main>. Lần 2: cổng trả PGRST202 cho bao_cao_so_ban "
			"(+ bao_cao_ton_kho, bao_cao_cong_no cho /bao-cao/ban-hang, /bao-cao/kho, /bao-cao/cong-no), mở lại y như trên. Kỳ vọng: chữ <main> từng tab hai "
			"lần bằng nhau; lần 1 mọi lời gọi bao_cao_so_ban là GET, không GET nào tới sales_invoice_lines / return_lines / sales_invoices (trừ câu sales_invoices "
			"lọc stock_entry_id của tab Lợi nhuận theo ngày). /reports/sales tab Nhân viên: NV A 878.000, NV B 210.000 (không phải 168.000). Lỗi khác "
			"PGRST202 / 42883 (vd 500) → hộp lỗi, không số 0.",
		kiem=[("tab Nhân viên (DT thuần — mã TS dungDongBan)", (878000, 210000), lambda k: (k[1]["theo_nv"]["nv.a@e2e.vn"]["net"], k[1]["theo_nv"]["nv.b@e2e.vn"]["net"]))])
	kb("VB-E03", "S1", "NVBH mở báo cáo + trang chủ NVBH (NV An)", [goi("bao_cao_so_ban", "NV_AN", **T11), goi("my_sales_target", "NV_AN"),
		goi("dashboard_summary", "NV_AN", p_period_start="2026-11-01")], nguon=["chay_that", "dac_ta"],
		lech=["my_sales_target Frappe = 0 tới P7 (NPP Cau Hinh Luong) — mục tiêu ẩn; nppsale = 0 vì sổ không có hr_salary_config", "phần giao diện: chỉ đặc tả"],
		ky_vong="NVBH mở /bao-cao/ban-hang (Tháng này): thanh lọc 'Nhân viên: <tên mình>' (khoá), không nút chế độ Nhân viên, không thẻ Lãi gộp, không nút Xuất Excel; số "
			"chỉ gồm HĐ mình đứng tên / của đơn mình. /bao-cao/cong-no: chỉ phiếu mình giữ, ghi chú 'Chỉ hiện khách bạn phụ trách'. /reports/sales: không tab Lợi "
			"nhuận / Nhân viên. /customers/hang-da-lay: RPC bỏ p_nv. Gõ thẳng /bao-cao/tai-chinh, /bao-cao, /dashboard, /reports/employees → về /home. Trang chủ "
			"NVBH: một đợt song song (HĐ posted của tôi từ min(thứ Hai, đầu quý) tới max(Chủ nhật, cuối quý), phiếu trả theo revenue_date, nợ của tôi chưa paid, "
			"đơn không huỷ, lượt ghé, đơn nháp, lịch tuyến hôm nay (day_of_week 0 = Thứ Hai), 5 đơn gần, my_sales_target (POST), tên khách theo khối 200 id, tên "
			"tuyến); doanh số kỳ = Σ total HĐ của tôi − Σ |credit| phiếu traCuaToi; mục tiêu tháng = my_sales_target, quý × 3.",
		kiem=[("doanh số tháng 11 NV An = Σ HĐ − Σ phiếu trả", (774000, 290000, 484000), lambda k: (tong(k[0]["hd"], "total"), tong(k[0]["tra"], "credit_note_amount"),
				tong(k[0]["hd"], "total") - tong(k[0]["tra"], "credit_note_amount"))),
			("= dashboard_summary NV An (VB-B05)", 484000, lambda k: k[2][0]["period_revenue"]),
			("my_sales_target", 0, lambda k: k[1])])
	kb("VB-E04", "E2E", "Công nợ dư có không ép về 0, tuổi nợ, sổ chi tiết", [goi("bao_cao_cong_no", "CHU", p_tu_thu="2026-04-03", p_tu_90="2026-07-01")],
		nguon=["chay_that", "dac_ta"], lech=["bao_cao_cong_no đã có trên Frappe — giao diện chạy nguyên"],
		ky_vong="Gieo bc-rc-1 (Tạp hoá Cô Ba 900.000 / 200.000, hạn 01/09, partial, HĐ HD-E2E-1 20/08) + bc-rc-2 (Đại lý Minh −150.000 / 0, open, gắn phiếu trả — "
			"10/09); mở /bao-cao/cong-no (X = 30/09/2026: p_tu_thu = min(X−180, 01/09) = 2026-04-03, p_tu_90 = X−91 = 2026-07-01); 'Tuổi nợ'; về 'Khách', bấm Cô Ba. "
			"Kỳ vọng: MỘT GET bao_cao_cong_no; thẻ Tổng phải thu 700.000, Dư có 150.000; dòng Đại lý Minh 'Dư có 150.000'; tuổi nợ đủ 5 nhóm (Trong hạn, 1–30, "
			"31–60, 61–90, Trên 90 ngày); bấm Cô Ba → 'Sổ chi tiết · Tạp hoá Cô Ba', số dư chạy kết thúc đúng nợ hiện tại 700.000.",
		kiem=[("mo (khoá, amount, paid, status)", [("no:HD-E2E-1", 900000, 200000, "partial"), ("no:TR-E2E-1", -150000, 0, "open")],
				lambda k: sorted(bo_ma(k[0]["mo"], "id", "amount", "paid", "status"))),
			("thẻ Tổng phải thu / Dư có (Σ dương / Σ âm của amount − paid)", (700000, 150000), lambda k: (sum(max(0, x["amount"] - x["paid"]) for x in k[0]["mo"]),
				-sum(min(0, x["amount"] - x["paid"]) for x in k[0]["mo"])))])
	kb("VB-E05", "E2E", "Hàng bán theo nhân viên (/bao-cao/nhan-vien) — mã TS congHangBanNhanVien + chotTienChungTu", [goi("bao_cao_so_ban", "CHU", **E29), ts(0)],
		nguon=["ts", "dac_ta"], lech=[E2E_FR, "C4 (🔧 P2): cổng price_lists chỉ bảng giá chung + bảng mặc định của nhóm khách — không thì 'Theo bảng giá' có thể lấy "
			"Standard Selling (VB-E15)"],
		ky_vong="Chủ mở /bao-cao/nhan-vien (kỳ chứa 29/09), bấm NV A, Xuất Excel: MỘT GET bao_cao_so_ban + users / customers / products(units, price_lists); không đọc "
			"phiếu xuất / giá vốn. Dòng NV A: SL bán '48', Đơn vị 'đơn vị', Theo bảng giá 900.000, Doanh thu 920.000, Chênh lệch bán 40.000, Thuế + làm tròn 0, "
			"Giảm giá đơn 20.000, SL trả 2, Giá trị trả −42.000, Chênh lệch trả −2.000, Doanh thu net 878.000, Chênh lệch net 38.000, Tổng chênh lệch 18.000. Chi "
			"tiết theo đơn vị dòng (thùng: giá bảng 450.000, giá bán 470.000; hộp: hàng trả 2). Excel có dòng '(Tổng hợp)' một số Σ cơ sở + 'đơn vị'.",
		kiem=[("NV A SL / Đơn vị", ("48", "đơn vị"), lambda k: (tim(k[1]["hang_ban_nv"], id="nv.a@e2e.vn")["sl_hien"], tim(k[1]["hang_ban_nv"], id="nv.a@e2e.vn")["don_vi"])),
			("NV A (bảng giá, DT, chênh bán, giảm đơn, thuế, SL trả, trả, chênh trả, net, chênh net, tổng chênh)", (900000, 920000, 40000, 20000, 0, 2, 42000, -2000,
				878000, 38000, 18000), lambda k: (lambda h: tuple(h[x] for x in HB))(tim(k[1]["hang_ban_nv"], id="nv.a@e2e.vn"))),
			("chi tiết thùng: giá bảng / giá bán", (450000, 470000), lambda k: (lambda d: (d["giaBang"], d["giaBan"]))(tim(tim(k[1]["hang_ban_nv"], id="nv.a@e2e.vn")
				["products"][0]["donVi"], unit="thùng"))),
			("chi tiết hộp: SL trả", 2, lambda k: tim(tim(k[1]["hang_ban_nv"], id="nv.a@e2e.vn")["products"][0]["donVi"], unit="hộp")["returnQty"])])
	kb("VB-E06", "S1", "HĐ ghi lùi ngày — giá vốn theo ngày HĐ (Q1)", [goi("bao_cao_so_ban", "CHU", **T10), goi("bao_cao_so_ban", "CHU", **T11),
		goi("finance_pnl", "CHU", **F10), goi("finance_pnl", "CHU", **F11)], chon={0: ["gv"], 1: ["gv"]},
		lech=[Q1, Q2, "Frappe: tháng 10 gv {SP1 24 / 168.000}, finance_pnl tháng 10 cogs 168.000; tháng 11 gv SP1 96 / 672.000, cogs 555.000 (Q2 = 0); cổng "
			"stock_entries.posted_at của HĐ4 = 31/10 → XNT tháng 10 có 'Xuất bán' 24 lon — lệch có chủ ý, chờ chủ nhà ghi nhận"],
		kiem=[("T10 gv rỗng / T11 gv SP1", ([], ("SP1", 120, 840000)), lambda k: (k[0]["gv"], bo_ma([tim(k[1]["gv"], product_id="SP1")], "product_id", "sl", "tien")[0])),
			("pnl T10 revenue / cogs", (240000, 0), lambda k: (k[2][0]["revenue"], k[2][0]["cogs"])),
			("pnl T11 cogs", 723000, lambda k: k[3][0]["cogs"])],
		fr=lambda c, k: {0: c.so_ban_fr(k[0], T10, "CHU"), 1: c.so_ban_fr(k[1], T11, "CHU"), 2: c.pnl_fr(k[2], F10, "CHU"), 3: c.pnl_fr(k[3], F11, "CHU")})
	d = lambda x: {"p_tu": x, "p_den": x}  # noqa: E731
	f = lambda x: {"p_from": x, "p_to": x}  # noqa: E731
	kb("VB-E07", "S8", "◇ phiếu tự lập có hàng đổi + đổi ngày phiếu đang Hoàn thành", [goi("bao_cao_so_ban", "CHU", **d("2026-11-12")),
		goi("finance_pnl", "CHU", **f("2026-11-15")), goi("finance_pnl", "CHU", **f("2026-11-12")), goi("bang:returns", "CHU"), goi("bang:receivables", "CHU"),
		dict(goi("bao_cao_so_ban", "CHU", **d("2026-11-10")), bo="S8b"), dict(goi("bao_cao_so_ban", "CHU", **d("2026-11-12")), bo="S8b"),
		dict(goi("finance_pnl", "CHU", **f("2026-11-15")), bo="S8b"), dict(goi("bang:returns", "CHU"), bo="S8b")],
		lech=["Frappe: phiếu tự lập Hoàn thành → tờ ghi có HDT- có kho, posting_date = lúc bấm 15/11 (giữ khi đổi ngày phiếu) → finance_pnl(15/11).returns_cogs "
			"15.000 cả trước lẫn sau; cổng stock_entries.notes của tờ ghi có = 'Nhập lại từ phiếu trả PT-0008' (dựng từ Link — M13)",
			"đặc tả (◇) bỏ sót PT-0002 (tự lập, revenue_date 12/11 trong Sổ BC): bao_cao_so_ban(12/11).tra và finance_pnl(12/11).returns_value gồm cả PT-0002"],
		kiem=[("trước: PT-0008 revenue_date / tiền / NV / HĐ", ("2026-11-12", 20000, "nv.an@sobc.vn", None), lambda k: bo_ma([tim(k[0]["tra"], id="PT-0008")],
				"revenue_date", "credit_note_amount", "sales_user_id", "invoice_id")[0]),
			("dong_tra (không dòng đổi)", [("PT-0008", "SP1", "lon", 2, 10000, 20000)], lambda k: [x for x in bo_ma(k[0]["dong_tra"], "return_id", "product_id",
				"unit_name", "quantity", "unit_price", "line_total") if x[0] == "PT-0008"]),
			("gv_tra PT-0008", [("PT-0008", "SP1", 14000), ("PT-0008", "SP3", 1000)], lambda k: [x for x in bo_ma(k[0]["gv_tra"], "return_id", "product_id", "tien")
				if x[0] == "PT-0008"]),
			("finance_pnl(15/11).returns_cogs trước", 15000, lambda k: k[1][0]["returns_cogs"]),
			("finance_pnl(12/11) returns_value / returns_cogs (đặc tả chỉ tính PT-0008)", (20000, 0), lambda k: (k[2][0]["returns_value"], k[2][0]["returns_cogs"])),
			("công nợ dòng âm K1 NV An", (-20000, "nv.an@sobc.vn", "0911000001"), lambda k: (lambda r: (r["amount"], r["sales_user_id"], r["customer_id"]))(
				tim(k[4], return_id="PT-0008"))),
			("sau: revenue_date / credited_at", ("2026-11-10", "2026-11-10T12:00:00+07:00"), lambda k: bo_ma([tim(k[8], id="PT-0008")], "revenue_date", "credited_at")[0]),
			("sau: (10/11).tra có PT-0008, (12/11) không", (True, False), lambda k: (tim(k[5]["tra"], id="PT-0008") is not None, tim(k[6]["tra"], id="PT-0008") is not None)),
			("finance_pnl(15/11).returns_cogs sau", 15000, lambda k: k[7][0]["returns_cogs"])])
	kb("VB-E08", "S9", "◇ xuất kho lẻ + trả NCC vào giá vốn", [goi("bao_cao_so_ban", "CHU", **T11), goi("bao_cao_so_ban", "CHU", **T12), goi("finance_pnl", "CHU", **F11),
		goi("finance_pnl", "CHU", **F12)], chon={0: ["gv"], 1: ["gv"]},
		lech=[Q1, Q2, "Frappe: giá dòng trả NCC = |Σ SVD| / |Σ SL| của sổ kho dòng (ĐT-KM S2 — không đọc PI Item.valuation_rate = giá trả); trả NCC với đơn giá khác "
			"giá lô thì thêm ca như ĐT-KM V81; tháng 11 Frappe gv SP1 96 / 672.000 (Q1), SP2 35 / 105.000, SP3 15 / 5.000 → cogs 570.000; tháng 12 SP2 5 / 0"],
		kiem=[("T11 gv SP2 / SP3", [("SP2", 35, 105000), ("SP3", 15, 5000)], lambda k: [x for x in bo_ma(k[0]["gv"], "product_id", "sl", "tien") if x[0] != "SP1"]),
			("pnl T11 cogs", 738000, lambda k: k[2][0]["cogs"]),
			("T12 gv", [("SP2", 5, 0)], lambda k: bo_ma(k[1]["gv"], "product_id", "sl", "tien"))],
		fr=lambda c, k: {0: c.so_ban_fr(k[0], T11, "CHU"), 1: c.so_ban_fr(k[1], T12, "CHU"), 2: c.pnl_fr(k[2], F11, "CHU"), 3: c.pnl_fr(k[3], F12, "CHU")})
	E09 = lambda n: [goi("bao_cao_so_ban", n, **T11), dict(goi("bao_cao_ton_kho", n, p_tu="2026-08-20", p_den="2026-11-17"),  # noqa: E731
		ghi_chu="= napTonKho của /bao-cao/kho: hôm nay − 89 … hôm nay (hôm nay 17/11/2026)"), goi("finance_pnl", n, **F11),
		goi("finance_balance_sheet", n, p_as_of="2026-11-30"), goi("stock_value_summary", n)]
	kb("VB-E09", "S1", "◇ che giá vốn (Q3): Kế toán bị thu inventory.cost", E09("KT") + E09("CHU"), chon={0: ["gv", "gv_tra"], 5: ["gv", "gv_tra"]},
		lech=[Q3, "Bước Frappe: NPP Quyen Rieng thu ô inventory.cost của Kế toán trước khi gọi (nppsale chỉ ẩn ở giao diện — số giống Chủ)",
			"Frappe Kế toán: gv[].sl đủ (96 / 30 / 15) nhưng tien null, gv_tra[].tien null, lo[].unit_cost null, cogs / returns_cogs null, inventory null, "
			"inventory_value null (batch_count 3); doanh thu / trả / công nợ đủ số. Chủ: đủ số. Báo cáo tổng hợp không hiện 'N mã chưa có giá vốn' cho người không "
			"xem giá vốn (man-ban-hang.tsx:189)"],
		kiem=[("nppsale: Kế toán = Chủ (mọi lời gọi)", True, lambda k: all(k[i] == k[i + 5] for i in range(5)))],
		fr=lambda c, k: c.e09_fr(k))
	kb("VB-E10", "S10", "◇ nợ đầu kỳ + tờ HĐ cũ (is_opening) không vào doanh thu", [goi("bao_cao_so_ban", "CHU", **T11),
		goi("dashboard_summary", "CHU", p_period_start="2026-11-01"), goi("dashboard_channel_revenue", "CHU", p_period_start="2026-11-01"),
		goi("dashboard_top_customers", "CHU", p_period_start="2026-11-01", p_limit=5), goi("finance_pnl", "CHU", **F11),
		goi("bao_cao_ton_kho", "CHU", p_tu="2026-09-01", p_den="2026-11-30"), goi("receivables_by_customer", "CHU")], chon={0: ["hd"]},
		lech=["Frappe: tờ DK- (ghi_no_dau_ky) và tờ HĐ cũ H3 (Sales Invoice is_opening = 'Yes', giữ mã HĐ cũ — P8) KHÔNG vào hd / dong_hd / doanh thu / số đơn / "
			"top / kênh / dong tồn kho; nợ của chúng ở NPP Cong No (open_receivables, receivables_*). nppsale không có tờ HĐ cũ — bộ S10 dựng nợ của nó bằng một dòng "
			"nợ không HĐ K1 500.000", Q1, Q2],
		kiem=[("hd vẫn 3 tờ, Σ", (3, 1111200), lambda k: (len(k[0]["hd"]), tong(k[0]["hd"], "total"))),
			("dashboard period_revenue / period_orders / open_receivables", (790960, 3, 2330960), lambda k: (k[1][0]["period_revenue"], k[1][0]["period_orders"],
				k[1][0]["open_receivables"])),
			("kênh / top không đổi", ([("GT", 504000), ("MT", 306960), ("Khác", -20000)], [("0911000001", 504000), ("0911000002", 306960), ("0911000003", -20000)]),
				lambda k: (bo_ma(k[2], "channel", "total"), bo_ma(k[3], "customer_id", "total"))),
			("revenue_gross", 1111200, lambda k: k[4][0]["revenue_gross"]),
			("tồn kho dong không đổi", 7, lambda k: len(k[5]["dong"])),
			("công nợ K1 / K2 tăng (K1 544.000 + 500.000; K2 306.960 + 1.000.000)", (1044000, 1306960), lambda k: (tim(k[6], customer_id="0911000001")["remaining"], tim(k[6], customer_id="0911000002")["remaining"]))],
		fr=lambda c, k: {4: c.pnl_fr(k[4], F11, "CHU")})
	kb("VB-E11", "S11", "◇ múi giờ ở bộ lọc cổng (C1) và ở RPC: phiếu thu 23:30 VN ngày 30/11", [goi("finance_cash_flow", "CHU", **F11),
		goi("finance_cash_flow", "CHU", **F12), goi("bang:payments", "CHU", loc=[("collected_at", "gte", "2026-12-01T00:00:00+07:00")]),
		goi("bang:payments", "CHU", loc=[("collected_at", "gte", "2026-11-30T17:00:00.000Z")]), goi("bang:payments", "CHU")],
		lech=["🔧 C1: cổng Frappe hôm nay hiểu chuỗi 'Z' như giờ VN (lệch 7 giờ) → lọc '2026-11-30T17:00:00.000Z' RA khoản thu — sau khi sửa _ep (gio_vao) phải "
			"ra [] như nppsale; '/reports' trang gộp và '/analytics/customers/overview' (đếm khách mới) ra cùng số nppsale sau khi sửa",
			"collected_at = creation phiếu thu (ghim 30/11 23:30 VN)"],
		kiem=[("cash_flow T11 / T12 tiền thu", (250000, 0), lambda k: (k[0][0]["cash_from_customers"], k[1][0]["cash_from_customers"])),
			("lọc '+07:00' và 'Z' (cùng thời điểm) → không ra", ([], []), lambda k: (k[2], k[3])),
			("khoản thu 30/11 23:30 VN", ("2026-11-30T23:30:00+07:00", 50000), lambda k: (lambda p: (p["collected_at"], p["amount"]))(tim(k[4], amount=50000)))])
	kb("VB-E12", None, "Tính lại giá vốn chạy nền (CFD-07, Q12) — chỉ Frappe", [], nguon="dac_ta",
		lech=[Q12, "R3: incoming_rate sau Repost = |SVD| / |SL| (SVD làm tròn đồng) — dung sai 0,5 đ / dòng"],
		ky_vong="Sổ BC (S2): Sửa HĐ2 khi đã có chứng từ kho sau ngày 10/11 cùng mặt hàng → lõi xếp Repost Item Valuation. Gọi bao_cao_so_ban tháng 11 trước và sau khi "
			"chạy hết việc (enqueue_parallel_reposting() + worker); đếm SELECT COUNT(*) FROM tabRepost Item Valuation WHERE docstatus = 1 AND status IN ('Queued', "
			"'In Progress'). Kỳ vọng: trong lúc còn việc đếm > 0 (và tinh_lai_gia_von > 0 nếu chốt Q12); chạy xong 0; gv = VB-A11 phần Frappe (mong_frappe) trong "
			"dung sai 0,5 đ / dòng (một lô giá cố định nên không đổi giá bình quân); incoming_rate dòng sau = |SVD| / |SL|.")
	kb("VB-E13", None, "Cân đối và tồn quỹ qua ngày cắt (P8)", [], nguon="dac_ta", cho="P8",
		lech=["Q13: finance_balance_sheet.cash LUỸ KẾ ⇒ mọi lần gọi cần NPP LS Khoan Thu / LS Khoan Chi NCC / LS Chi Phi (hoặc một số dư tiền tại ngày cắt)",
			"R17: nhánh lưu trữ (UNION NPP LS *, CAST … COLLATE) chưa có DocType"],
		ky_vong="Bước: Nền N chuyển sang NPP LS * với NPP Cai Dat.ngay_cat_chuyen = 01/12/2026 (khoản thu PM1…PM4 Σ 2.600.000, khoản chi NCC PP1…PP5 Σ 6.200.000, chi phí "
			"đã trả X1, X4, X5, X6 Σ 3.230.000); sau cắt thêm phiếu thu 500.000 ngày 05/12. Kỳ vọng: finance_balance_sheet('2026-11-30').cash = −6.830.000 (= VB-D05, đọc "
			"từ LS); ('2026-12-31').cash = −6.330.000 — không 'về 0' ở ngày cắt; bao_cao_so_ban('2026-11-01','2026-12-31').hd = HĐ tháng 11 từ LS ∪ HĐ tháng 12 từ "
			"sổ thật, tờ đầu kỳ (is_opening) không có; accounts_receivable = Σ NPP Cong No mở (gồm tờ đầu kỳ).")
	kb("VB-E14", "E2E", "◇ chênh lệch theo bảng giá HIỆN HÀNH, đúng đơn vị (mã TS)", [goi("bao_cao_so_ban", "CHU", **E29),
		ts(0, doi_gia={"ML1": [{"unit_name": "thùng", "price": 460000, "group_id": None}, {"unit_name": "hộp", "price": 20000, "group_id": None}]}),
		ts(0, doi_gia={"ML1": [{"unit_name": "hộp", "price": 20000, "group_id": None}]})], nguon=["ts", "dac_ta"],
		lech=["KHÔNG đọc price_list_rate chụp trên dòng SI; đổi giá bảng làm chênh của kỳ cũ đổi theo (như nppsale)", "C3 ❓ thứ tự dòng lồng price_lists (giá hiện hành)"],
		ky_vong="Dữ liệu VB-E01. Đổi Item Price thùng của bảng giá chung 450.000 → 460.000; mở lại 'Hàng bán theo nhân viên'. NV A: Theo bảng giá 920.000, Chênh lệch "
			"bán 20.000, Giảm giá đơn 20.000, Thuế + làm tròn 0, Chênh lệch trả −2.000, Chênh lệch net 18.000, Tổng chênh lệch −2.000. Xoá giá thùng khỏi bảng giá chung → "
			"giá thùng = 20.000 × 24 = 480.000 → chênh bán −20.000.",
		kiem=[("thùng 460.000: NV A bảng giá / chênh bán / giảm đơn / thuế / chênh trả / chênh net / tổng chênh", (920000, 20000, 20000, 0, -2000, 18000, -2000),
				lambda k: (lambda h: (h["listed"], h["diff"], h["docDiscount"], h["thueLamTron"], h["diffReturn"], h["diffNet"], h["tongChenh"]))(
				tim(k[1]["hang_ban_nv"], id="nv.a@e2e.vn"))),
			("xoá giá thùng: chênh bán NV A", -20000, lambda k: tim(k[2]["hang_ban_nv"], id="nv.a@e2e.vn")["diff"])])
	kb("VB-E15", "E2E", "◇ bảng giá ngoài NPP không được thành 'giá chung' (C4) — chỉ Frappe", [goi("bao_cao_so_ban", "CHU", **E29), ts(0)], nguon=["dac_ta", "ts"],
		lech=["🔧 C4 (P2): hôm nay (chưa sửa) bài phải ĐỎ; nppsale không có khái niệm bảng giá ngoài NPP (price_lists group_id NULL = bảng giá chung)"],
		ky_vong="Dữ liệu VB-E01. Thêm Item Price 'Standard Selling' cho 'Sữa một lượt' thùng 999.000 (name nhỏ hơn dòng 'Gia chuan' để ra TRƯỚC nếu cổng không lọc); thêm "
			"Price List bán 'Gia le' không gắn nhóm khách nào, thùng 1.000.000. Kỳ vọng: cổng products(price_lists(unit_name, price, group_id)) của mặt hàng KHÔNG có hai "
			"dòng ấy (chỉ 'Gia chuan' + bảng mặc định của nhóm khách); 'Hàng bán theo nhân viên' NV A vẫn Theo bảng giá 900.000, Chênh lệch bán 40.000 (= VB-E05); POS giá "
			"thùng cho khách nhóm không có bảng riêng vẫn 450.000.",
		kiem=[("NV A Theo bảng giá / Chênh lệch bán (= VB-E05)", (900000, 40000), lambda k: (lambda h: (h["listed"], h["diff"]))(tim(k[1]["hang_ban_nv"], id="nv.a@e2e.vn")))])
	kb("VB-E16", None, "Câu báo cáo quá hạn ra 57014 (L11) — chỉ Frappe", [], nguon="dac_ta",
		lech=["🔧 MariaDB 1969 (max_statement_time) phải đổi sang 57014 + câu Postgres ('canceling statement due to statement timeout') — _chay §2.0 hoặc cong/api.py::_loi"],
		ky_vong="Gọi /rest/v1/rpc/bao_cao_so_ban?q=… (Chủ, tháng 11) với hạn ép rất nhỏ (bài vá _chay / execution_timeout xuống 0,000001 s, hoặc chèn SELECT SLEEP(2) "
			"trong một nhánh thử), tương tự finance_pnl (hạn 8 s), dashboard_summary. Kỳ vọng: HTTP 500, thân {\"error\": {\"code\": \"57014\", \"message\": \"canceling "
			"statement due to statement timeout\", …}}; giao diện (errorMessage) ra câu QUA_HAN_VI; sau lỗi phiên trả lại max_statement_time cũ (câu tiếp theo cùng "
			"worker không bị cắt). Lỗi khác (vd bảng thiếu) KHÔNG bị đổi thành 57014.")
	return K


# ================================================================================================ chạy đọc + TS + Frappe
LA = "00000000-0000-0000-0000-00000000dead"  # "@la" — id không thuộc NPP nào


def bo_cua(bo: str) -> str:
	return "S" if bo.startswith("S") else bo


def nguoi_cua(bo: str) -> dict:
	return {"S": NGUOI_S, "N": NGUOI_N, "E2E": NGUOI_E}[bo_cua(bo)]


def ma_doc(bo: str) -> dict:
	"""Chỗ giữ tĩnh của lời gọi đọc (người, khách, id lạ)."""
	if bo_cua(bo) == "S":
		m = ma_tinh_s()
	else:
		m = {}
		for i, _t, _v, email in nguoi_cua(bo).values():
			m["@nv:" + email] = i
	m["@la"] = LA
	return m


def gio_doc(bo: str) -> str:
	return {"S": GIO_DOC_S, "N": GIO_DOC_N, "E2E": GIO_DOC_E}[bo_cua(bo)]


def org_cua(bo: str) -> str:
	return {"S": ORG_S, "N": ORG_N, "E2E": ORG_E}[bo_cua(bo)]


def db_cua(bo: str) -> str:
	return TIEN_TO + bo.lower()


class Ctx:
	"""Ngữ cảnh một kịch bản: kết quả thô (id gốc) của từng lời gọi + luật Frappe (đề xuất Qn) để dựng mong_frappe."""

	def __init__(self, t: dict, tho: dict, idm: dict):
		self.t, self.tho, self.idm = t, tho, idm
		self.thu_von = set(t.get("thu_von") or ())

	def _bo(self, i=None):
		c = self.t["goi"][i] if i is not None else {}
		return c.get("bo") or self.t["bo"]

	def khong_von(self, nguoi: str) -> bool:
		return nguoi_cua(self.t["bo"])[nguoi][2] == "sales" or nguoi in self.thu_von

	def gv_fr(self, ky: dict, tho=False):
		bo = self.t["bo"]
		r = gv_frappe(db_cua(bo), org_cua(bo), ky.get("p_tu") or ky.get("p_from"), ky.get("p_den") or ky.get("p_to"))
		return r if tho else chuan(r, self.idm[bo])

	def so_ban_fr(self, kq: dict, ky: dict, nguoi: str) -> dict:
		x = dict(kq)
		x["gv"] = sorted(self.gv_fr(ky), key=XEP["bao_cao_so_ban"]["gv"])
		if self.khong_von(nguoi):
			x["gv"] = [dict(g_, tien=None) for g_ in x["gv"]]
			x["gv_tra"] = [dict(g_, tien=None) for g_ in x["gv_tra"]]
		return x

	def ts_fr(self, i: int, ky: dict, nguoi: str) -> dict:
		so_ban = dict(self.tho[i])
		so_ban["gv"] = self.gv_fr(ky, tho=True)
		if self.khong_von(nguoi):
			so_ban["gv"] = [dict(g_, tien=None) for g_ in so_ban["gv"]]
			so_ban["gv_tra"] = [dict(g_, tien=None) for g_ in so_ban["gv_tra"]]
		bo = self.t["bo"]
		return ts_gon(chay_ts([{"ma": self.t["ma"], "so_ban": so_ban, "san_pham": san_pham_db(db_cua(bo))}])[0], self.idm[bo])

	def pnl_fr(self, kq: list, ky: dict, nguoi: str) -> list:
		r = dict(kq[0])
		xuat = sum(g_["tien"] for g_ in self.gv_fr(ky))
		r["cogs"] = so(decimal.Decimal(str(xuat)) - decimal.Decimal(str(r["returns_cogs"])))
		if self.khong_von(nguoi):
			r["cogs"] = r["returns_cogs"] = None
		return [r]

	@staticmethod
	def che(kq: list, dong, khoa) -> list:
		return [dict(x, **{k: None for k in khoa}) if i in dong else x for i, x in enumerate(kq)]

	@staticmethod
	def che_lo(kq: dict) -> dict:
		return dict(kq, lo=[dict(x, unit_cost=None) for x in kq["lo"]])

	def a16_fr(self, k: list) -> dict:
		ra = {0: self.pnl_fr(k[0], F11, "CHU"), 1: self.pnl_fr(k[1], F11, "TK"), 2: self.pnl_fr(k[2], F11, "NV_AN"), 3: self.pnl_fr(k[3], F11, "NV_BINH"),
			4: self.pnl_fr(k[4], F10, "CHU"), 5: self.pnl_fr(k[5], F12, "CHU")}
		for i in (11, 13):
			ra[i] = self.che(k[i], [0], ("inventory",))
		for i in (18, 19):
			ra[i] = self.che(k[i], [0], ("inventory_value",))
		ra[21] = self.che_lo(k[21])
		return ra

	def e09_fr(self, k: list) -> dict:
		self.thu_von = {"KT"}
		return {0: self.so_ban_fr(k[0], T11, "KT"), 1: self.che_lo(k[1]), 2: self.pnl_fr(k[2], F11, "KT"), 3: self.che(k[3], [0], ("inventory",)),
			4: self.che(k[4], [0], ("inventory_value",)), 5: self.so_ban_fr(k[5], T11, "CHU"), 7: self.pnl_fr(k[7], F11, "CHU")}


def doc_tat_ca(K: list[dict]) -> dict:
	"""Chạy mọi lời gọi đọc (gom theo DB) → {(mã, số): {"ok", "kq" thô | "ma_loi", "loi"}}."""
	theo_db: dict = {}
	for t in K:
		nhom: dict = {}
		for so_, c in enumerate(t["goi"]):
			if c["ham"].startswith("ts:"):
				continue
			bo = c.get("bo") or t["bo"]
			bt = c.get("bien_the")
			nhom.setdefault((bo, bt["ma"] if bt else None), []).append((so_, c))
		for (bo, _bt), cs in nhom.items():
			bt = cs[0][1].get("bien_the")
			goi_ = [None] * len(t["goi"])
			for so_, c in cs:
				goi_[so_] = c
			theo_db.setdefault(bo, []).append((t["ma"], goi_, bt["sql"] if bt else None))
	ra = {}
	for bo, ds in theo_db.items():
		db = db_cua(bo)
		ng, m, gio = nguoi_cua(bo), ma_doc(bo), gio_doc(bo)
		sql = ["TRUNCATE public._vang_doc;"]
		for ma, goi_, bt in ds:
			cs = [c if c is not None else {"ham": "ts:bo_qua"} for c in goi_]
			sql.append(sql_doc_kich_ban(ma, cs, ng, m, gio, bt))
		psql(db, "\n".join(sql))
		for x in psql_json(db, "SELECT COALESCE(json_agg(json_build_object('ma', ma, 'so', so, 'ok', ok, 'kq', kq, 'ma_loi', ma_loi, 'loi', loi)), '[]') "
				"FROM public._vang_doc;"):
			ra[(x["ma"], int(x["so"]))] = x
	return ra


def anh_chup(db: str, idm: dict) -> dict:
	"""Ảnh chụp sổ sau khi dựng (bài Frappe kiểm bộ dựng trước khi so báo cáo) — chuẩn hoá khoá nghiệp vụ."""
	x = psql_json(db, """SELECT jsonb_build_object(
 'hd', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', i.id, 'don', i.order_id, 'ngay', i.invoice_date, 'status', i.status, 'subtotal', i.subtotal, 'vat', i.vat,
   'total', i.total, 'nv', i.sales_user_id, 'khach', i.customer_id) ORDER BY i.invoice_code) FROM sales_invoices i), '[]'),
 'don', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', o.id, 'status', o.status, 'nv', o.sales_user_id, 'khach', o.customer_id, 'total', o.total)
   ORDER BY o.order_code) FROM sales_orders o), '[]'),
 'phieu_tra', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', r.id, 'status', r.status, 'tu_sinh', r.credit_with_invoice, 'tien', r.credit_note_amount,
   'ngay_phieu', r.return_date, 'revenue_date', r.revenue_date, 'credited_at', r.credited_at, 'hd', r.invoice_id, 'nv', r.sales_user_id, 'khach', r.customer_id)
   ORDER BY r.return_code) FROM returns r), '[]'),
 'cong_no', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', c.id, 'amount', c.amount, 'paid', c.paid, 'status', c.status, 'nv', c.sales_user_id,
   'han', c.due_date, 'khach', c.customer_id) ORDER BY c.created_at, c.id) FROM receivables c), '[]'),
 'thu', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', p.id, 'amount', p.amount, 'method', p.method, 'luc', p.collected_at) ORDER BY p.collected_at, p.id)
   FROM payments p), '[]'),
 'lo', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', b.id, 'ton', b.qty_on_hand, 'gia', b.unit_cost) ORDER BY b.batch_code, b.warehouse_zone)
   FROM batches b), '[]'),
 'phieu_kho', COALESCE((SELECT jsonb_agg(jsonb_build_object('loai', e.type, 'status', e.status, 'ghi_so', e.posted_at, 'ghi_chu', e.notes,
   'dong', (SELECT jsonb_agg(jsonb_build_object('sp', l.product_id, 'sl_co_so', l.qty_in_base_uom, 'gia', l.unit_cost) ORDER BY l.product_id, l.qty_in_base_uom)
            FROM stock_entry_lines l WHERE l.entry_id = e.id)) ORDER BY e.posted_at NULLS LAST, e.notes) FROM stock_entries e), '[]'));""")
	return chuan(x, idm)


def anh_chup_ncc(db: str, idm: dict) -> dict:
	x = psql_json(db, """SELECT jsonb_build_object(
 'ncc', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', s.id, 'ma', s.code) ORDER BY s.name) FROM suppliers s), '[]'),
 'cong_no_ncc', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', p.id, 'ncc', p.supplier_id, 'phieu_kho', p.stock_entry_id, 'so_hd', p.invoice_number,
   'amount', p.amount, 'paid', p.paid, 'han', p.due_date, 'status', p.status, 'dau_ky', p.opening_balance, 'tao_luc', p.created_at) ORDER BY p.created_at, p.id)
   FROM payables p), '[]'),
 'tra_ncc', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', p.id, 'cong_no', p.payable_id, 'amount', p.amount, 'method', p.method, 'luc', p.paid_at)
   ORDER BY p.paid_at, p.id) FROM payable_payments p), '[]'),
 'chi_phi', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', e.id, 'danh_muc', c.code, 'nhom', c.bucket, 'ngay_chi', e.expense_date, 'so_tien', e.amount,
   'da_tra', e.is_paid, 'tra_luc', e.paid_at, 'nguon', e.source_type) ORDER BY e.expense_date, e.id) FROM expenses e
   LEFT JOIN expense_categories c ON c.id = e.category_id), '[]'));""")
	return chuan(x, idm)


QUY_UOC = [
	"Mỗi bộ nền dựng trong DB MỚI (Postgres nháp — khung schema_full.sql của nppsale + đồng hồ ghim); mỗi bước là MỘT giao dịch như production, chạy dưới đúng "
	"người (request.jwt.claim.sub + ROLE authenticated) — 'MAY_CHU' = quyền máy chủ (chỉ chỗ có 'ly_do'); bước có 'cho_loi' là bước chờ lỗi (đúng mã / câu "
	"ghi ở bước — sổ không đổi).",
	"Đồng hồ: mỗi bước / lời gọi mang 'gio' (ISO +07:00) = 'lúc bấm' đã ghim — bài Frappe ghim cùng giờ (frappe.utils.now / nowdate) trước bước. Sổ BC dựng "
	"16/11/2026 20:50–21:10 VN (R15; bộ ◇ ghim theo bước: S8 15/11, S9 19/11, S10 05/11, S11 30/11 23:30), đọc 17/11/2026 08:00 VN (vn_today = 17/11 như "
	"[T]); Nền N đọc 16/11/2026 12:00 VN; E2E đọc 30/09/2026 10:00 VN.",
	"Chỗ giữ trong tham số: '@nv:<email>' (NV — NPP Nhan Vien.name), '@kh:<SĐT>' (khách), '@sp:<SKU>', '@ncc:<tên NCC>', '@org' (NPP), '@pk:<mã phiếu kho tay>', "
	"'@ptncc:<mã>', '@don:<mã đơn>', '@hd:<mã HĐ>', '@pt:<mã phiếu trả>', '@no:hd:<mã HĐ>' / '@no:pt:<mã phiếu trả>' (dòng công nợ), '@dong_xuat:<mã đơn>' "
	"(= mọi dòng get_invoiceable_lines của đơn, SL còn lại), '@dong_sua:<mã HĐ>' + 'doi_sl' {'<SKU>/<ĐV>': SL} (= dòng hiện có của HĐ, đổi SL), '@la' (id lạ).",
	"Kết quả đã chuẩn hoá: uuid → khoá nghiệp vụ (mã đơn / HĐ / phiếu trả; dòng HĐ '<HĐ>/<SKU>/<ĐV>[/doi]'; dòng đơn '<đơn>/<SKU>/<ĐV>'; công nợ "
	"'no:<HĐ | phiếu trả | dk:<SĐT>:<tiền>>'; lô '<mã lô>::<vùng>' (= id cổng batches của Frappe); phiếu kho 'pk:<mã>'; khoản thu 'thu:<chứng từ>:<tiền>'; NV = "
	"email; khách = SĐT; hàng = SKU; NCC = tên); Nền N giữ khoá đặc tả (HD1 = 'HD-0001', R1…R5, RC1…RC7, PM1…PM7, PY1…PY6, PP1…PP5, X1…X6, E1…E15; NPP B tiền tố "
	"'B:'); mốc giờ → 'YYYY-MM-DDTHH:MM:SS+07:00'; số → int khi chẵn, float khi lẻ (6 chữ số).",
	"Thứ tự: mảng không thứ tự theo đặc tả L12 (bao_cao_so_ban.hd / dong_hd / tra / dong_tra / gv / gv_tra; bao_cao_ton_kho.lo / dong; bao_cao_cong_no.mo / "
	"gan90 / thu) đã xếp theo khoá — so như TẬP; list của hàm TABLE và hang_khach_da_lay giữ thứ tự hàm — so có thứ tự.",
	"goi[i].mong = {ok, kq} hoặc {ok: false, ma_loi (SQLSTATE), loi (nguyên văn)}; 'chon' = chỉ giữ các khoá ấy của kết quả dict (khoá '_khoa' = bộ khoá đầy đủ); "
	"goi[i].mong_frappe (khi có) = kết quả Frappe kỳ vọng theo đề xuất Qn (cùng dạng, cùng chuẩn hoá) — bài Frappe so với mong_frappe thay mong; "
	"'chi_nppsale': true = lời gọi không dựng được trên Frappe (bỏ).",
	"Lời gọi 'ts:ban_hang' = mã TS thật của giao diện nppsale chạy trên kết quả bao_cao_so_ban của lời gọi 'tu' (danh mục mặt hàng của sổ; 'doi_gia' thay bảng giá "
	"chung); bài Frappe chạy cùng mã (portal) trên kết quả RPC Frappe — hoặc so phần máy chủ rồi dùng số TS này làm kỳ vọng giao diện.",
	"lech_frappe = điểm Frappe khác nppsale có chủ ý (⚠K) / chờ chốt (❓Qn — làm theo 'đề xuất'; Q2 theo 'Chốt chéo với đặc tả P4': xuất lẻ / chuyển kho giá 0); "
	"doi_chieu = số đặc tả §5 ↔ số chạy thật (khop false = đặc tả lệch — tin số chạy thật).",
	"Tiền so tuyệt đối; giá vốn dung sai ≤ 0,5 đ / dòng xuất (L4-c); phân bổ tiền theo dòng của mã TS ±1 đ / dòng (R6) — so theo HĐ / NV / mặt hàng.",
]

FRAPPE_N = [
	"NPP A = site; người: Chủ, Quản lý, Kế toán, Thủ kho, NV Một, NV Hai (sales), Bị khoá (owner, dang_hoat_dong = 0); NPP B (Chủ B) không dựng được (một site = "
	"một NPP — R16): mọi lời gọi của Chủ B mang chi_nppsale.",
	"Danh mục: K1 Tạp hoá Một (0900000001, hạn mức 5.000.000, NV Một chính), K2 Tạp hoá Hai (0900000002, hạn mức trống, NV Hai chính), K3 Tạp hoá Ba (0900000003, "
	"hạn mức 0, không phân công); SP1 Nước ngọt (cơ sở Lon, Thùng = 24), SP2 Dầu ăn (Chai); NCC Một (mã N1), NCC Hai (N2), NCC Ba (mã trống).",
	"HĐ (create_order_with_lines + post_invoice ghim ngày HĐ, NV đơn = NV HĐ): HD1 K1 / NV Một 02/11 4.640.500 (SP1 5 Thùng + SP2 10 Chai + SP2 1 Chai ĐỔI 0 đ); "
	"HD2 K2 / NV Hai 05/11 2.000.000 (SP2 20); HD3 K1 / NV Một 20/10 1.000.000 (SP1 2 Thùng); HD4 K3 / NV Hai 10/11 500.000 (SP2 5) rồi cancel_invoice; HD5 K2 / "
	"NV Một 01/11 300.000 (SP1 1 Thùng — ghim giờ ghi sổ 01/11 00:30 VN); HD6 K3 / NV Hai 15/09 400.000 (SP2 6).",
	"Giá vốn: lô L-A SP1 8.000 / lon (kho bán), L-B SP2 60.000 (kho bán), L-C SP2 50.000 (tồn 0), L-D SP1 7.500 (kho date) — tồn cuối phải = du_lieu.lo (nhập "
	"đầu kỳ đủ để sau mọi xuất / nhập còn đúng số; mỗi mặt hàng xuất từ lô có giá nêu ở phiếu kho để giá vốn kỳ khớp). E15 (HĐ6 tháng 9, 55.000) không ảnh "
	"hưởng kịch bản nào ngoài dòng tồn kho 90 ngày.",
	"Phiếu trả: R1 tự sinh theo HD1 (Chờ xử lý, 1.652.000); R2 tự lập gắn HD2 Hoàn thành ngày 08/11 (200.000; phiếu nhập lại 2 Chai × 60.000 ghi sổ 08/11); R3 Nháp "
	"(100.000); R4 tự lập Hoàn thành rồi Huỷ (60.000 — Frappe: chứng từ nhập lại docstatus 2, không phiếu 'Đảo'); R5 tự lập K2 / NV Hai không HĐ Hoàn thành 11/11 "
	"(250.000; nhập lại 1 Thùng SP1 × 8.000 ghi sổ 11/11) → dòng công nợ âm RC6.",
	"Công nợ / khoản thu (create_cash_receipt ghim giờ; ghi thẳng có kiểm soát chỗ không có RPC): RC3 trả dư = HĐ3 1.200.000 thu đủ rồi Sửa HĐ giảm về 1.000.000 (P3d "
	"phương án B); RC4 (HD5) dấu quá hạn bấm tay (cổng receivables status); RC5 nợ đầu kỳ K3 700.000 hạn 01/08 (ghi_no_dau_ky) + PM7 50.000 'return_credit' (luồng cũ — "
	"ghi thẳng); RC6 / PM5 / PM6 = phiếu thu cấn trừ dư có R5 sang RC2 (±100.000 credit_applied); PM1 RC1 1.000.000 tiền mặt 03/11 10:00; PM2 RC3 1.000.000 chuyển "
	"khoản 25/10; PM3 RC3 200.000 tiền mặt 01/11 06:30; PM4 RC7 400.000 tiền mặt 20/09.",
	"Kho khác: E6 xuất lẻ 'Hư hỏng' 24 lon SP1 ngày 12/11 (post_stock_issue — Frappe giá 0, Q2); E7 trả NCC TH-1 3 Chai SP2 NCC Một ngày 13/11 (complete_supplier_return "
	"— giá lô 60.000; nợ âm PY2 −500.000); E11 xuất lẻ NHÁP 4 Chai (Stock Entry docstatus 0); E12 / E13 phiếu nhập NCC (PY1 / PY5 / PY6).",
	"NCC (P4): PY1 N1 phiếu nhập 10.000.000 ngày 04/11 (PP1 Ghi trả 4.000.000 chuyển khoản 06/11 14:00); PY3 N2 nợ đầu kỳ 2.000.000 dấu quá hạn (PP4 bù trừ 200.000 "
	"'offset' 09/11 — JE bu_tru_ncc); PY4 N3 trả trước 300.000 (chi_tra_ncc 07/11 09:00, không phiếu nhập); PY5 N2 phiếu nhập 1.000.000 ngày 10/10 trả đủ 15/10; PY6 N2 "
	"phiếu nhập 700.000 lúc 01/11 05:00 VN trả đủ 01/11 05:00.",
	"Chi phí (P7 — NPP Phieu Chi; chưa có RPC phiếu chi tay → ghi thẳng): X1 Thuê kho (operating) 3.000.000 ngày 03/11 trả 03/11 09:00; X2 Lương (hr) 5.000.000 15/11 "
	"chưa trả; X3 COGS_ADJ (cogs, nguồn stocktake) 150.000 12/11 chưa trả; X4 Lãi vay (financial) 100.000 ngày 28/10 trả 02/11 08:00; X5 không danh mục 50.000 20/11 "
	"trả 20/11 09:00; X6 Thuế (tax) 80.000 05/11 trả 06/11 10:00.",
]


# điều kiện để bài Frappe chạy được lời gọi (đặc tả §4.1 — ma trận RPC → nguồn → phải xong trước)
CAN_FRAPPE = {
	"bao_cao_so_ban": "P6-2 (rpc/bao_cao.py) + hằng nguon_dong_xuat / nguon_dong_nhap_lai (đã có — cong/bang/kho.py)",
	"bao_cao_ton_kho": "đã có (P4 M9 — rpc/kho.py)",
	"dashboard_summary": "P6-3", "dashboard_channel_revenue": "P6-3", "dashboard_top_customers": "P6-3",
	"hang_khach_da_lay": "P6-4", "my_sales_target": "P6-4 (trả 0 tới P7 — NPP Cau Hinh Luong)",
	"finance_pnl": "P6-5 + cổng expenses / expense_categories (P7 — Q14: tới khi có thì hàm ném PGRST202)",
	"finance_cash_flow": "P6-5 + cổng payable_payments (P4 — đã có) + expenses (P7 — Q14)",
	"finance_balance_sheet": "P6-5 + payables / payable_payments (P4 — đã có) + expenses (P7 — Q14)",
	"payables_summary": "đã có (P4 M3)", "payables_by_supplier": "đã có (P4 M3)",
	"receivables_summary": "đã có (P3d)", "receivables_by_customer": "đã có (P3d)", "receivables_by_rep": "đã có (P3d)",
	"bao_cao_cong_no": "đã có (P3d)", "stock_value_summary": "đã có (rpc/kho.py)", "cash_received_total": "đã có (P3d)",
	"ts:ban_hang": "mã TS portal/nguon (giao diện chạy nguyên trên cổng)",
}

HUONG_DAN_FRAPPE = [
	"Dựng bộ nền một lần mỗi lớp bài (setUpClass) dưới đúng người: người / khách / hàng / lô / NCC theo 'nen', rồi từng bước của 'bo.<bộ>.buoc' (S2 … S11 = "
	"bản sao S1 + bước riêng: dựng S1 rồi chạy bước riêng trong điểm lưu, lui sau kịch bản — hoặc dựng riêng từng bộ). Mỗi bước: ghim đồng hồ = 'gio' (patch "
	"frappe.utils.now_datetime / nowdate / getdate(None) hoặc frappe.flags.current_date), đặt người (NguCanh như tests/test_kho_mua_vang.py), gọi "
	"nppsale.cong.api.rpc(ten=<rpc>, tham_so=<tham_so đã giải chỗ giữ>) — tên RPC Frappe trùng nppsale; bước 'ghi_cong' = cổng bảng (nppsale.cong — insert / "
	"update dưới đúng người); bước 'ghi_may_chu' theo trường 'frappe' của bước (kb/03 dời giờ phiếu xuất: BỎ — Frappe ghi sổ kho theo posting_date).",
	"Sau khi dựng, so sổ với 'bo.<bộ>.anh_chup' (HĐ, đơn, phiếu trả, công nợ, khoản thu, tồn lô) trước khi so báo cáo — lệch ở đây là lỗi bộ dựng, không phải "
	"lỗi báo cáo. Phiếu kho của HĐ / nhập lại trên Frappe là chính chứng từ (không so mã XK-/NL-).",
	"Giải chỗ giữ: '@don:' / '@hd:' / '@pt:' → name Frappe của chứng từ có nhãn ấy (ghi lại từ kết quả bước lập — mã Frappe có thể khác 'DH-0001' / "
	"'HD-0001' / 'PT-0001'); '@dong_xuat:<đơn>' → get_invoiceable_lines(đơn) (SL còn lại, giá, hàng đổi) như màn Xuất hàng; '@dong_sua:<HĐ>' + doi_sl → dòng "
	"hiện có của HĐ, đổi SL theo '<SKU>/<ĐV>'; '@no:hd:<HĐ>' → NPP Cong No của HĐ.",
	"Gọi báo cáo: mỗi tinh_huong.goi dưới 'nguoi', đồng hồ 'gio', tham số 'tham_so' (giữ chuỗi như GET gửi — '' / 'abc' / '2026-02-30' phải ra 22007 / 22008); "
	"'bang:<tên>' = câu đọc cổng bảng (nppsale.cong.truy_van.doc) dưới người ấy; 'bien_the' (Nền N) = sửa sổ trong điểm lưu trước lời gọi, lui sau; "
	"'chi_nppsale' = bỏ.",
	"Chuẩn hoá kết quả Frappe y như tệp vàng (quy_uoc) rồi so với 'mong_frappe' nếu có, không thì 'mong' — chỉ phần khoá 'chon' (+ '_khoa' = bộ khoá đủ; "
	"Frappe thêm 'tinh_lai_gia_von' nếu chốt Q12 — bỏ khoá ấy khi so bộ khoá). Mảng không thứ tự so như tập (đã xếp); list hàm TABLE so có thứ tự.",
	"Ánh xạ khoá: NV = email ('nen.*.nguoi'); khách = SĐT (Customer.npp_sdt); hàng = SKU (item_code); lô = '<mã lô>::<vùng>'; công nợ 'no:<chứng từ>'; Nền N "
	"dùng khoá đặc tả (RC1…, PM1…) — bài giữ bảng ánh xạ name Frappe → khoá khi dựng.",
	"Lời gọi 'ts:ban_hang': chạy mã TS của portal (tools/vang_bao_cao_ts.ts — cùng hàm tuMotLuot → dungDongBan → congBan / congHangBanNhanVien) trên kết quả "
	"bao_cao_so_ban của Frappe, hoặc chỉ so phần máy chủ và coi số TS là kỳ vọng giao diện (bài e2e portal).",
	"Kịch bản 'nguon' gồm 'dac_ta' (giao diện / chỉ Frappe): kiểm theo 'ky_vong_dac_ta' bằng bài e2e portal hoặc bài riêng; 'cho': 'P8' = để tới P8.",
	"Thứ tự dựng gợi ý theo §4.2: P6-2 (A01–A15, E01, E06, E09, E15, E16) → P6-3 (B01–B06, E10) → P6-4 (C01–C04) → P6-5 (A16, D01–D20, E07, E08, E12) sau P4 + "
	"P7 chi phí; 'can_frappe' của từng kịch bản ghi điều kiện.",
]


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--chi", help="chỉ in các kịch bản có mã bắt đầu bằng (phẩy ngăn) — không ghi tệp")
	a = ap.parse_args()
	K = kich_ban()
	khung = dung_khung()
	bo_s = dung_bo_s()
	dung_bo_khac()
	cac_bo = [*bo_s, "N", "E2E"]
	idm = {bo: {**(ban_do_id(db_cua(bo)) or {}), **ban_do_tinh(bo)} for bo in cac_bo}
	doc = doc_tat_ca(K)
	# ---- TS: gom mọi ca, chạy node MỘT lần
	sp_db = {}
	ca_ts = []
	for t in K:
		for i, c in enumerate(t["goi"]):
			if c["ham"] == "ts:ban_hang":
				bo = c.get("bo") or t["bo"]
				sp = sp_db.setdefault(bo, san_pham_db(db_cua(bo)))
				if c.get("doi_gia"):
					sp = [dict(p, price_lists=c["doi_gia"].get(p["sku"], p["price_lists"])) for p in sp]
				ca_ts.append({"ma": f"{t['ma']}#{i}", "so_ban": doc[(t["ma"], c["tu"])]["kq"], "san_pham": sp})
	kq_ts = {r["ma"]: r for r in chay_ts(ca_ts)} if ca_ts else {}
	# ---- dựng tình huống
	ra_t = []
	doi_chieu_tong = []
	for t in K:
		k, tho, goi_ra = [], {}, []
		for i, c in enumerate(t["goi"]):
			bo = c.get("bo") or t["bo"]
			if c["ham"] == "ts:ban_hang":
				x = ts_gon(kq_ts[f"{t['ma']}#{i}"], idm[bo])
				k.append(x)
				goi_ra.append({k_: v for k_, v in c.items()} | {"mong": {"ok": True, "kq": x}})
				continue
			d = doc[(t["ma"], i)]
			if d["ok"]:
				tho[i] = d["kq"]
				x = xep(c["ham"], chuan(d["kq"], idm[bo]))
				k.append(x)
				mong = {"ok": True, "kq": x}
			else:
				x = {"ma_loi": d["ma_loi"], "loi": d["loi"]}
				k.append(x)
				mong = {"ok": False, **x}
			bt = c.get("bien_the")
			goi_ra.append({k_: v for k_, v in c.items() if k_ != "bien_the"}
				| ({"bien_the": {"ma": bt["ma"], "mo_ta": bt["mo_ta"], "sql_nppsale": chuan(bt["sql"], idm[bo])}} if bt else {})
				| {"gio": c.get("gio") or gio_doc(bo), "mong": mong})
		# Frappe
		fr = {}
		if t.get("fr"):
			fr = t["fr"](Ctx(t, tho, idm), k)
		for i, v in fr.items():
			if v != k[i]:
				goi_ra[i]["mong_frappe"] = {"ok": True, "kq": v}
		# chọn khoá
		for i, ks in (t.get("chon") or {}).items():
			for nh in ("mong", "mong_frappe"):
				m_ = goi_ra[i].get(nh)
				if m_ and m_.get("ok") and isinstance(m_["kq"], dict):
					m_["kq"] = {"_khoa": sorted(m_["kq"]), **{x: m_["kq"][x] for x in ks}}
			goi_ra[i]["chon"] = ks
		# đối chiếu đặc tả
		dc = []
		for nhan, dac_ta, f in t.get("kiem") or []:
			try:
				chay_ = f(k)
			except Exception as e:  # lỗi trích số (đặc tả ↔ cấu trúc kết quả) ghi thành chênh
				chay_ = f"LOI_TRICH: {type(e).__name__}: {e}"
			dt = json.loads(json.dumps(dac_ta, default=str))
			cy = json.loads(json.dumps(chay_, default=str))
			dc.append({"muc": nhan, "dac_ta": dt, "chay": cy, "khop": dt == cy})
		doi_chieu_tong += [(t["ma"], x) for x in dc]
		can = sorted({CAN_FRAPPE[(c["ham"] if not c["ham"].startswith("bang:") else "")] for c in t["goi"] if not c["ham"].startswith("bang:")}
			| ({"cổng bảng đã có (P3)"} if any(c["ham"].startswith("bang:") for c in t["goi"]) else set()))
		x = {"ma": t["ma"], "ten": t["ten"], "bo": t["bo"], "nguon": t["nguon"], "can_frappe": can, "goi": goi_ra, "lech_frappe": t["lech_frappe"],
			"doi_chieu": dc}
		for kk in ("ky_vong_dac_ta", "cho"):
			if t.get(kk):
				x[kk] = t[kk]
		ra_t.append(x)
	if a.chi:
		for x in ra_t:
			if any(x["ma"].startswith(c) for c in a.chi.split(",")):
				print(json.dumps(x, ensure_ascii=False, indent=1))
		return
	# ---- bộ nền (dữ liệu dựng — bài Frappe phát lại)
	bo_ra = {}
	for bo, (mo_ta, bs, kq) in bo_s.items():
		buoc = []
		for b, r in zip(bs, kq, strict=True):
			y = dict(b)
			y["kq"] = ({"ok": True, "tra": chuan(r["tra"], idm[bo], "(không còn trong sổ)")} if r["ok"]
				else {"ok": False, "ma_loi": r["ma_loi"], "loi": r["loi"]})
			buoc.append(y)
		bo_ra[bo] = {"mo_ta": mo_ta, "goc": GOC_BIEN_THE.get(bo), "buoc": buoc, "anh_chup": anh_chup(db_cua(bo), idm[bo])}
	bo_ra["N"] = {"mo_ta": "Nền N (§5.4) — dựng TAY như bước đặc tả: tools/vang_bao_cao_nen_n.sql (trigger tắt); bài Frappe dựng lại bằng RPC + ghi thẳng có kiểm "
		"soát theo 'frappe' và so sổ với 'anh_chup'", "goc": None, "tep_sql": "tools/vang_bao_cao_nen_n.sql", "frappe": FRAPPE_N,
		"anh_chup": anh_chup(db_cua("N"), idm["N"]) | anh_chup_ncc(db_cua("N"), idm["N"])}
	bo_ra["E2E"] = {"mo_ta": "Bộ e2e một lượt (e2e/bao-cao-cu-mot-luot.spec.ts, 29/09/2026) + hai dòng nợ VB-E04 (e2e/bao-cao-tong-hop.spec.ts) — chèn thẳng như sổ "
		"giả e2e (id chữ của e2e → uuid GIỮ thứ tự HD-ML-A < HD-ML-B)", "goc": None,
		"frappe": ["HĐ / phiếu trả / phiếu kho chèn thẳng có kiểm soát (phiếu trả không NV, không HĐ chỉ có ở dữ liệu chuyển); bảng giá chung: thùng 450.000, hộp "
			"20.000; Item.npp_gia_ban 20.000; mã HĐ giữ thứ tự HD-ML-A < HD-ML-B theo mã điểm"],
		"anh_chup": anh_chup(db_cua("E2E"), idm["E2E"])}
	nen = {
		"S": {"org": "NPP BC", "nguoi": {k: {"ten": v[1], "vai": v[2], "email": v[3]} for k, v in NGUOI_S.items()},
			"ncc": [v[1] for v in NCC_S.values()], "cong_ty_nv": {NGUOI_S[k][3]: [NCC_S[n][1] for n in v] for k, v in CONG_TY_NV_S.items()},
			"khach": {v[3]: {"ten": v[1], "chu": v[2], "tuyen": v[4], "han_muc": 100000000, "dieu_khoan": "COD", "dia_chi": "HN", "nguoi_tao": "chu@sobc.vn"}
				for v in KHACH_S.values()},
			"phan_cong": [{"khach": KHACH_S[a][3], "nv": NGUOI_S[b][3], "vai_tro": c, "trang_thai": "active"} for a, b, c in PHAN_CONG_S],
			"hang": {k: {"ten": v[1], "dv_co_so": v[2], "vat": v[3], "gia_ban": v[4], "gia_von": v[5], "ncc": NCC_S[v[6]][1] if v[6] else None, "quy_doi": v[7]}
				for k, v in HANG_S.items()},
			"bang_gia_chung": [], "lo": {k: {"sku": v[1], "han": v[2], "sl": v[3], "gia_von": v[4], "kho": "sale", "nhan_luc": "2026-10-01T08:00:00+07:00"}
				for k, v in LO_S.items()},
			"gio_hat_giong": GIO_SEED_S, "gio_doc": GIO_DOC_S,
			"frappe": "mỗi mặt hàng MỘT lô (định giá lô của lõi = giá lô) để giá vốn khớp; bảng giá chung trống (giá niêm yết = Item.npp_gia_ban); thủ kho / kế "
				"toán / quản lý / chủ có inventory.cost mặc định, NVBH không"},
		"N": {"nguoi": {k: {"ten": v[1], "vai": v[2], "email": v[3], **({"khoa": True} if k == "KHOA" else {}), **({"npp": "B"} if k == "CHU_B" else {})}
				for k, v in NGUOI_N.items()},
			"khach": {v[2]: {"ten": v[1]} for v in KHACH_N.values()}, "hang": {k: {"ten": v[1], "dv_co_so": v[2]} for k, v in HANG_N.items()},
			"gio_doc": GIO_DOC_N},
		"E2E": {"nguoi": {k: {"ten": v[1], "vai": v[2], "email": v[3]} for k, v in NGUOI_E.items()}, "khach": {v: k for k, v in SDT_E.items()},
			"hang": {"ML1": {"ten": "Sữa một lượt", "thuong_hieu": "Hiệu Một Lượt", "dv_co_so": "hộp", "quy_doi": {"thùng": 24}, "gia_ban": 20000,
				"bang_gia_chung": {"thùng": 450000, "hộp": 20000}}}, "gio_doc": GIO_DOC_E},
	}
	tep = {"ghi_chu": "Sinh bởi tools/vang_bao_cao.py — hàm + trigger + RLS thật của nppsale (schema_full.sql, Postgres nháp, đồng hồ ghim) + mã TS thật của giao "
		"diện (portal/nguon) — đặc tả P6 §5 (62 kịch bản VB-A01…VB-E16).", "quy_uoc": QUY_UOC, "huong_dan_frappe": HUONG_DAN_FRAPPE, "ghim_dong_ho": khung, "nen": nen, "bo": bo_ra,
		"tinh_huong": ra_t}
	with open(DICH, "w", encoding="utf-8") as f_:
		json.dump(tep, f_, ensure_ascii=False, indent=1)
		f_.write("\n")
	lech = [(m_, x) for m_, x in doi_chieu_tong if not x["khop"]]
	print(f"{len(ra_t)} kịch bản → {DICH}; đối chiếu đặc tả: {len(doi_chieu_tong)} mục, {len(doi_chieu_tong) - len(lech)} khớp, {len(lech)} lệch")
	for m_, x in lech:
		print(f"  LỆCH {m_} · {x['muc']}: đặc tả {json.dumps(x['dac_ta'], ensure_ascii=False)} ↔ chạy {json.dumps(x['chay'], ensure_ascii=False)}")


if __name__ == "__main__":
	main()
