"""Luật thuần HOÁ ĐƠN ĐIỆN TỬ MISA meInvoice — chép `src/lib/misa/{normalize,status,apply,mapper,reconcile}.ts` + phần ĐỌC phản hồi của
`client.ts` của nppsale (commit ghim `58158b1`, `portal/nguon.json`), cùng ba mẩu thuần nằm trong route: công thức dòng hàng của
`app/api/einvoice/publish/route.ts:197–313`, link tra cứu (`:390–392`) và `toSnapshotRow` (`app/api/einvoice/pull-snapshots/route.ts:185–215`).

Không import frappe, không gọi mạng (như `nppsale/luat/*`). Một chỗ khai, mọi nơi dùng: phát hành, Làm mới, vòng quét, kéo snapshot, Dựng từ
snapshot, khớp bốn tầng, lớp gọi MISA (`nppsale/api/misa_mang.py` chỉ gửi / nhận byte rồi đọc bằng các hàm ở đây) — hai bản chuẩn hoá là hai
màn hình khớp khác nhau (skill einvoice-misa-sync, Gotcha #9). Đặc tả: `dac_ta_hddt.md` §2 (+ §3.2 H25, §4.1.2, §5.3 bước 4, H26).

Số vàng: `tools/vang_hddt.mjs` chạy CHÍNH mã TS (bản chép chỉ khác dòng import, `crypto.randomUUID` + `Date` ghim) →
`nppsale/tests/du_lieu/hddt_mau.json`; bài `nppsale/tests/test_luat_hddt.py`.

"Kiểu JS" (§2.1 — gốc của mọi lệch vặt): `Math.round` nửa lên về +∞ (`tron`, không phải `round()` làm tròn ngân hàng của Python),
`String(number)` (`so_js`), `Intl.NumberFormat("vi-VN")` (`tien_vn`), `trim()` / `\\s` / `\\d` của JS (`js_trim`, `JS_KT`, `[0-9]`),
`Number()` của chuỗi (`so`), thứ tự khoá `Object.keys` (`js_khoa`), `slice` theo đơn vị UTF-16 (`js_cat`), `JSON.parse` / `JSON.stringify`
(`js_doc_json`, `js_json`), độ "truthy" (`js_dung`).

Lệch có chủ ý so với nppsale (đặc tả §0.3, bài vàng khai từng ca): H8 + H17 trong `ap_dung`; H7 `gop_ghi_chu`; H25 `che_token` trong câu lỗi
`/oauth`; H26 `ngay_that` / `bo_ngay_khong_that` cho hàm ghi (`ngay_iso` giữ đúng TS). Lệch nhỏ: thân JSON `null` ở `/oauth`, `GET ?refID=`,
danh sách, mẫu — TS ném `TypeError` tiếng Anh (`obj["success"]` của `null`), ở đây coi như không có dữ liệu.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import re
import uuid
from decimal import Decimal
from urllib.parse import quote

# =====================================================================================================================================
# §2.1 Số và chuỗi "kiểu JS"
# =====================================================================================================================================

# WhiteSpace + LineTerminator của ECMAScript = tập ký tự `String.prototype.trim()`, `\s` (không cờ u) và `Number()` bỏ ở hai đầu. Khác
# `str.strip()` / `\s` của Python: JS có U+FEFF (BOM), Python thì không; Python có U+001C–U+001F, U+0085, JS thì không [đo, đặc tả §2.1].
JS_KT = (
	"\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
	"\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_KT = re.compile("[" + re.escape(JS_KT) + "]+")
_CHI_SO_MANG = re.compile(r"0|[1-9][0-9]*")
_THAP_PHAN = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_KHAC_CO_SO = re.compile(r"0([xXoObB])([0-9a-zA-Z]+)")
_CO_SO = {"x": (16, re.compile(r"[0-9a-fA-F]+")), "o": (8, re.compile(r"[0-7]+")), "b": (2, re.compile(r"[01]+"))}
_SO_NGUYEN_AN_TOAN = 2 ** 53


def js_trim(s: str) -> str:
	"""`String.prototype.trim()`: bỏ JS_KT ở hai đầu (giữ \\x1c, bỏ BOM — ngược `str.strip()`)."""
	return s.strip(JS_KT)


def _bo_kt(s: str) -> str:
	"""`s.replace(/\\s+/g, "")` của JS."""
	return _KT.sub("", s)


def js_dung(v) -> bool:
	"""Độ "truthy" của JS: None / False / 0 / -0 / NaN / "" là sai; mọi dict / list (kể cả rỗng) là đúng."""
	if v is None or v is False:
		return False
	if v is True:
		return True
	if isinstance(v, (float, Decimal)):
		return not (v.is_nan() if isinstance(v, Decimal) else math.isnan(v)) and v != 0
	if isinstance(v, int):
		return v != 0
	if isinstance(v, str):
		return v != ""
	return True


def _hoac(v, mac_dinh):
	"""`v || mac_dinh` của JS (khác `or` của Python ở NaN: NaN || 0 → 0)."""
	return v if js_dung(v) else mac_dinh


def _la_so_js(v) -> bool:
	"""`typeof v === "number"` (số Python, không bool; gồm cả NaN / vô cực)."""
	return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _thuc(v) -> float:
	"""Số Python → float của JS (int vượt 2^53 mất chính xác như Number; quá lớn → vô cực)."""
	try:
		return float(v)
	except OverflowError:
		return math.inf if v > 0 else -math.inf


def _js_so_chuoi(s: str) -> float:
	"""`Number(chuỗi)` của JS: bỏ JS_KT hai đầu; rỗng → 0; thập phân / mũ; 0x 0o 0b (không dấu); "Infinity" có dấu; còn lại NaN.
	Python `float()` khác: nhận "1_0", "inf", "nan", chữ số Unicode; ném lỗi với "0x3" [đo — đặc tả §2.1]."""
	t = js_trim(s)
	if t == "":
		return 0.0
	if _THAP_PHAN.fullmatch(t):
		return float(t)
	m = _KHAC_CO_SO.fullmatch(t)
	if m:
		co_so, mau = _CO_SO[m.group(1).lower()]
		if mau.fullmatch(m.group(2)):
			return _thuc(int(m.group(2), co_so))
		return math.nan
	if t in ("Infinity", "+Infinity"):
		return math.inf
	if t == "-Infinity":
		return -math.inf
	return math.nan


def _js_so(v) -> float:
	"""`Number(v)` của JS cho các kiểu gặp ở đây: None (= null) → 0, bool → 0/1, số, Decimal, chuỗi; kiểu khác → NaN."""
	if v is None:
		return 0.0
	if isinstance(v, bool):
		return 1.0 if v else 0.0
	if isinstance(v, (int, float, Decimal)):
		return _thuc(v)
	if isinstance(v, str):
		return _js_so_chuoi(v)
	return math.nan


def _lam_tron_js(x: float) -> float:
	"""`Math.round(x)`: số nguyên gần nhất, hai bên bằng nhau thì về phía +∞ (−2,5 → −2); giữ −0 (−0,5 ≤ x < 0 → −0).
	Không dùng `floor(x + 0.5)`: 0.49999999999999994 + 0.5 = 1.0 trong số thực (đặc tả §2.1)."""
	if math.isnan(x) or math.isinf(x):
		return x
	f = math.floor(x)
	r = f + 1 if x - f >= 0.5 else f
	if r == 0 and math.copysign(1.0, x) < 0:
		return -0.0
	return float(r)


def tron(x) -> int:
	"""`roundVnd` (mapper.ts:66–68) = `Math.round(Number(x) || 0)` → int của Python (để JSON phát `2` chứ không `2.0`).
	None / NaN / chuỗi không phải số → 0. 1234,5 → 1235 (`round()` của Python ra 1234 — KV-04)."""
	n = _js_so(x)
	if not js_dung(n):
		return 0
	r = _lam_tron_js(n)
	if math.isinf(r):
		return r
	return int(r)


def _chu_so(x: float) -> tuple[str, int]:
	"""(chữ số ngắn nhất, n) với x = 0.d1d2…dk × 10^n (x > 0, hữu hạn) — `repr` của Python và `Number::toString` cùng chọn dãy chữ số
	ngắn nhất khôi phục đúng số thực; chỉ khác cách trình bày."""
	r = repr(x)
	if "e" in r:
		m, e = r.split("e")
		mu = int(e)
	else:
		m, mu = r, 0
	nguyen, _, le = m.partition(".")
	tat_ca = nguyen + le
	cs = tat_ca.lstrip("0")
	n = len(nguyen) - (len(tat_ca) - len(cs)) + mu
	return (cs.rstrip("0") or "0"), n


def _so_js_duong(x: float) -> str:
	cs, n = _chu_so(x)
	k = len(cs)
	if k <= n <= 21:
		return cs + "0" * (n - k)
	if 0 < n <= 21:
		return cs[:n] + "." + cs[n:]
	if -6 < n <= 0:
		return "0." + "0" * (-n) + cs
	mu = n - 1
	dau = "+" if mu >= 0 else "-"
	if k == 1:
		return f"{cs}e{dau}{abs(mu)}"
	return f"{cs[0]}.{cs[1:]}e{dau}{abs(mu)}"


def so_js(v) -> str:
	"""`String(v)` / template literal của JS: 215000.0 → "215000"; None → "null" (`MISA trả PublishStatus=null …`); dạng mũ chỉ khi
	|x| ≥ 1e21 hoặc < 1e-6 ("1e+21", "1e-7" — `repr` của Python dùng mũ từ 1e16 và dưới 1e-4, đệm số 0: '1e+16', '1e-07')."""
	if v is None:
		return "null"
	if v is True:
		return "true"
	if v is False:
		return "false"
	if isinstance(v, str):
		return v
	if isinstance(v, int):
		if abs(v) <= _SO_NGUYEN_AN_TOAN:
			return str(v)
		v = _thuc(v)
	if isinstance(v, Decimal):
		v = _thuc(v)
	if isinstance(v, float):
		if math.isnan(v):
			return "NaN"
		if math.isinf(v):
			return "Infinity" if v > 0 else "-Infinity"
		if v == 0:
			return "0"
		if v < 0:
			return "-" + _so_js_duong(-v)
		return _so_js_duong(v)
	return str(v)


def _chu_so_nguyen(x: float) -> str:
	"""Chữ số thập phân của số nguyên x ≥ 0 theo cách Intl in (chữ số ngắn nhất rồi đệm 0: 1e23 → "1000…0", không phải 99999999999999991611392)."""
	if x == 0:
		return "0"
	cs, n = _chu_so(x)
	return cs + "0" * (n - len(cs))


def tien_vn(v) -> str:
	"""`formatCurrency` (src/lib/utils.ts:14–18): `Intl.NumberFormat("vi-VN").format(Math.round(v)) + "đ"` — chấm hàng nghìn, âm có "-":
	212600 → "212.600đ", −108002 → "-108.002đ", None → "0đ", −0,4 / −0,5 → "-0đ" (Math.round ra −0, Intl in dấu) [đo]."""
	x = 0.0 if v is None else _js_so(v)
	if math.isnan(x):
		return "NaNđ"
	r = _lam_tron_js(x)
	am = r < 0 or (r == 0 and math.copysign(1.0, r) < 0)
	if math.isinf(r):
		return ("-" if am else "") + "∞đ"
	chu = _chu_so_nguyen(abs(r))
	nhom = []
	while len(chu) > 3:
		nhom.insert(0, chu[-3:])
		chu = chu[:-3]
	nhom.insert(0, chu)
	return ("-" if am else "") + ".".join(nhom) + "đ"


def chuoi(v) -> str | None:
	"""`str()` của status.ts:109–111: chuỗi sau `trim()` khác rỗng → chuỗi đã trim; còn lại (kể cả số) None."""
	if isinstance(v, str):
		t = js_trim(v)
		return t or None
	return None


def so(v):
	"""`num()` của status.ts:100–107: số hữu hạn (không bool) giữ nguyên; chuỗi khác rỗng sau trim → `Number()` của JS ('0x3' → 3,
	'1_0' → None, ' 3 ' → 3, '1e5' → 100000); kết quả không hữu hạn hoặc kiểu khác → None."""
	if isinstance(v, bool) or v is None:
		return None
	if isinstance(v, (int, float, Decimal)):
		if isinstance(v, int) and abs(v) <= _SO_NGUYEN_AN_TOAN:
			return v
		n = _thuc(v)
		return n if math.isfinite(n) else None
	if isinstance(v, str) and js_trim(v) != "":
		n = _js_so_chuoi(v)
		return n if math.isfinite(n) else None
	return None


def js_khoa(d: dict) -> list:
	"""Thứ tự `Object.keys` / `Object.values` / `JSON.stringify`: khoá là chỉ số mảng ("0" … "4294967294") đứng trước, tăng dần, rồi các
	khoá khác theo thứ tự chèn — `{"b":1,"2":2,"a":3,"1":4}` → ["1","2","b","a"] [đo]; `dict` của Python giữ đúng thứ tự JSON."""
	def la_chi_so(k) -> bool:
		return isinstance(k, str) and bool(_CHI_SO_MANG.fullmatch(k)) and int(k) <= 4294967294

	return sorted((k for k in d if la_chi_so(k)), key=int) + [k for k in d if not la_chi_so(k)]


def js_cat(s: str, n: int) -> str:
	"""`s.slice(0, n)` của JS: đếm đơn vị UTF-16, cắt được nửa cặp surrogate ("ab😀cd".slice(0, 3) = "ab\\ud83d") [đo]."""
	b = s.encode("utf-16-le", "surrogatepass")
	return b[: 2 * n].decode("utf-16-le", "surrogatepass")


def _tu_choi_hang(s: str):
	raise ValueError(f"{s} không phải JSON")


def _so_nguyen_json(s: str):
	n = int(s)
	if abs(n) > _SO_NGUYEN_AN_TOAN:
		return float(s)
	if n == 0 and s.startswith("-"):
		return -0.0
	return n


def js_doc_json(text: str):
	"""`JSON.parse`: chặt như JS — NaN / Infinity là lỗi (Python `json.loads` nhận); số nguyên vượt 2^53 thành số thực như Number
	(12345678901234567890 → 1.2345678901234567e19, `so_js` ra "12345678901234567000"). Lỗi → ValueError."""
	return json.loads(text, parse_constant=_tu_choi_hang, parse_int=_so_nguyen_json)


_THOAT_JSON = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _chuoi_json(s: str) -> str:
	ra = ['"']
	i, n = 0, len(s)
	while i < n:
		c = s[i]
		o = ord(c)
		if c in _THOAT_JSON:
			ra.append(_THOAT_JSON[c])
		elif o < 0x20:
			ra.append("\\u%04x" % o)
		elif 0xD800 <= o <= 0xDBFF and i + 1 < n and 0xDC00 <= ord(s[i + 1]) <= 0xDFFF:
			ra.append(c + s[i + 1])
			i += 1
		elif 0xD800 <= o <= 0xDFFF:
			ra.append("\\u%04x" % o)  # surrogate lẻ (vd sau js_cat) — JSON.stringify bản "well-formed"
		else:
			ra.append(c)
		i += 1
	ra.append('"')
	return "".join(ra)


def js_json(v) -> str:
	"""`JSON.stringify(v)` (không thụt lề): thứ tự khoá như JS (`js_khoa`), số theo `so_js` (2.0 → "2", NaN / vô cực → "null"), chuỗi không
	thoát ký tự ngoài ASCII. Dùng cho mảng `ErrorCode` trong câu lỗi (client.ts:414) và thân JSON gửi MISA."""
	if v is None:
		return "null"
	if v is True:
		return "true"
	if v is False:
		return "false"
	if _la_so_js(v):
		x = _thuc(v) if not isinstance(v, int) or abs(v) > _SO_NGUYEN_AN_TOAN else v
		if isinstance(x, float) and not math.isfinite(x):
			return "null"
		return so_js(x)
	if isinstance(v, str):
		return _chuoi_json(v)
	if isinstance(v, (list, tuple)):
		return "[" + ",".join(js_json(x) for x in v) + "]"
	if isinstance(v, dict):
		goc = {str(k): k for k in v}
		return "{" + ",".join(_chuoi_json(k) + ":" + js_json(v[goc[k]]) for k in js_khoa(goc)) + "}"
	raise TypeError(f"js_json không nhận kiểu {type(v).__name__}")


def _chuoi_js(v) -> str:
	"""`String(v)` cho các hàm chuẩn hoá (đầu vào thường là chuỗi)."""
	return v if isinstance(v, str) else so_js(v)


def _norm(v) -> str:
	"""`norm()` của reconcile.ts:62–64: `(v ?? "").trim()`."""
	return "" if v is None else js_trim(_chuoi_js(v))


# =====================================================================================================================================
# §2.2 Chuẩn hoá — "chuẩn hoá khi SO, giữ nguyên khi LƯU" (normalize.ts:1–12)
# =====================================================================================================================================

def chuan_so(s) -> str:
	"""normalizeInvNo (normalize.ts:20–26): None → ''; trim; rỗng → ''; bỏ số 0 ĐẦU; còn rỗng → '0'. KHÔNG bỏ khoảng trắng giữa:
	'00000123' → '123', '000' → '0', ' 12 3 ' → '12 3'."""
	if s is None:
		return ""
	t = js_trim(_chuoi_js(s))
	if not t:
		return ""
	return t.lstrip("0") or "0"


def cung_so(a, b) -> bool:
	"""sameInvNo (normalize.ts:42–49): hai bản chuẩn hoá khác rỗng và bằng nhau (rỗng không bằng gì, kể cả rỗng)."""
	na, nb = chuan_so(a), chuan_so(b)
	return bool(na) and bool(nb) and na == nb


def ky_hieu_long(s) -> str:
	"""normalizeSeries (normalize.ts:36–39): trim, viết hoa, bỏ CHỮ SỐ ĐẦU (`^\\d+` của JS chỉ là [0-9] — '１C25MHG' giữ nguyên) —
	'1C25MHG' → 'C25MHG', ' 1c25 mhg' → 'C25 MHG'. Chỉ dùng cho tầng khớp lỏng (3b)."""
	if s is None:
		return ""
	return re.sub(r"^[0-9]+", "", js_trim(_chuoi_js(s)).upper())


def cung_ky_hieu(a, b) -> bool:
	"""sameSeries (normalize.ts:52–57)."""
	na, nb = ky_hieu_long(a), ky_hieu_long(b)
	return bool(na) and bool(nb) and na == nb


def ky_hieu_chat(s) -> str:
	"""strictSeries (reconcile.ts:79–81): trim, viết hoa, bỏ MỌI khoảng trắng kiểu JS, GIỮ mẫu số — khoá tầng 3 (chắc chắn); cũng là
	`ky_hieu_chuan` của snapshot (H21)."""
	return _bo_kt(_norm(s).upper())


def mst_du(s) -> str:
	"""MST đủ chuỗi (reconcile.ts:144, 199 — `norm(v).replace(/\\s+/g, "")`): khoá tầng 4 vòng trong."""
	return _bo_kt(_norm(s))


def mst_goc(s) -> str:
	"""baseTaxCode (reconcile.ts:90–92): MST đủ rồi cắt trước "-" đầu tiên ('0301175691-044' → '0301175691') — chỉ vòng ngoài tầng 4."""
	return mst_du(s).split("-")[0]


_NGAY_KHOP = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})")
_NGAY_ISO = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")


def ngay_khop(s) -> str | None:
	"""matchDate (reconcile.ts:155–158): 10 ký tự `^\\d{4}-\\d{2}-\\d{2}` sau trim, không parse ('٢٠٢٦-١١-١٥' → None). Nhận cả `date`
	(cột Date của Frappe)."""
	if isinstance(s, _dt.date):
		s = s.isoformat()
	m = _NGAY_KHOP.match(_norm(s))
	return m.group(1) if m else None


def ngay_iso(s) -> str | None:
	"""isoDateOnly (apply.ts:140–148): `^(\\d{4})-(\\d{2})-(\\d{2})` sau trim, tháng 1–12, ngày 1–31; sai → None (không ghi rác vào cột kỳ
	thuế). KHÔNG kiểm lịch thật: '2026-02-30' lọt qua [đo] — giữ đúng TS; hàm ghi kiểm bằng `ngay_that` (H26)."""
	if not isinstance(s, str):
		return None
	m = _NGAY_ISO.match(js_trim(s))
	if not m:
		return None
	y, mo, d = m.groups()
	if not (1 <= int(mo) <= 12 and 1 <= int(d) <= 31):
		return None
	return f"{y}-{mo}-{d}"


def ngay_that(d) -> str | None:
	"""[ĐX H26] Chuỗi `YYYY-MM-DD` là ngày có thật trên lịch → giữ; '2026-02-30' / '2026-04-31' / năm 0000 → None. MariaDB
	`STRICT_TRANS_TABLES` (như Postgres) từ chối CẢ câu ghi có ngày như thế — hàm ghi kéo về / kéo snapshot phải lọc trước (§4.8 bước 4b)."""
	if not isinstance(d, str) or not _NGAY_ISO.fullmatch(d):
		return None
	try:
		_dt.date.fromisoformat(d)
	except ValueError:
		return None
	return d


def la_so_cho(s) -> bool:
	"""isPlaceholderInvNo (status.ts:74–78): None / rỗng sau trim / bắt đầu '<' ('<Chưa cấp số>') → MISA chưa cấp số."""
	if not js_dung(s):
		return True
	t = js_trim(_chuoi_js(s))
	return t == "" or t.startswith("<")


def so_khac(so_so, so_misa) -> bool:
	"""invNoConflict (status.ts:333–336): cả hai có số mà khác nhau sau chuẩn hoá."""
	if not js_dung(so_so) or not js_dung(so_misa):
		return False
	return not cung_so(so_so, so_misa)


# =====================================================================================================================================
# §2.3 Đọc bản ghi MISA — readSnapshot / readCancelled (status.ts:113–166)
# =====================================================================================================================================

# Cờ huỷ: tên ĐẦU đã xác minh trên tài khoản thật (`afterpublishing/{RefID}`); ba tên sau là dự phòng (status.ts:130–135).
_CO_HUY = ("IsInvoiceDeleted", "IsInvoiceCanceled", "IsCanceled", "IsCancelled")


def doc_ban_ghi(raw) -> dict:
	"""Bóc bản ghi MISA thô (không phải dict → coi như {}). Cờ huỷ CHỈ nhận đúng `True` kiểu bool — chuỗi "true" / số 1 không tính (KV-06
	B14: nhận "truthy" là mở đường cho `CancelStatus: 0` thành "đã huỷ")."""
	r = raw if isinstance(raw, dict) else {}
	huy, nguon = False, None
	for k in _CO_HUY:
		if r.get(k) is True:
			huy, nguon = True, k
			break
	return {
		"inv_no": chuoi(r.get("InvNo")),
		"inv_series": chuoi(r.get("InvSeries")),
		"inv_date": chuoi(r.get("InvDate")),
		"invoice_code": chuoi(r.get("InvoiceCode")),
		"transaction_id": chuoi(r.get("TransactionID")),
		"org_ref_id": chuoi(r.get("OrgRefID")),
		"deleted_reason": chuoi(r.get("DeletedReason")),
		"publish_status": so(r.get("PublishStatus")),
		"einvoice_status": so(r.get("EInvoiceStatus")),
		"total_amount": so(r.get("TotalAmount")),
		"total_without_vat": so(r.get("TotalAmountWithoutVAT")),
		"total_vat": so(r.get("TotalVATAmount")),
		"huy": huy,
		"nguon_huy": nguon,
	}


def co_ban_ghi_that(raw, ref=None) -> bool:
	"""[Sửa cuối — phát hiện 9 của vòng soát] Bản ghi `GET ?refID=` có THẬT SỰ nói "MISA đang giữ tờ này" không: dict mang RefID trùng `ref` (so
	không phân biệt hoa thường, sau trim) HOẶC có ít nhất một trường nhận diện / trạng thái (InvNo — kể cả chỗ giữ chỗ '<Chưa cấp số>', InvSeries,
	TransactionID, InvoiceCode, PublishStatus, EInvoiceStatus, TotalAmount) HOẶC cờ huỷ. `doc_phan_hoi_lay_hd` (parity JS — giữ nguyên) trả `{}` cho
	`data: '{}'` / `'[]'` / `'1'`…: JS coi là "có dữ liệu" nhưng bản ghi ấy không nói gì — coi là "MISA có tờ" thì phát hành bỏ POST (H3 / H27) và
	xác nhận đẩy (H5) một tờ MISA chưa từng nhận, kẹt `sent` + `issued` vĩnh viễn (RefID bất biến — mọi lần hỏi lại vẫn `{}`). Dạng "không có" thật của
	MISA chưa đo (§9.4-2). Người gọi chỉ dùng cho tờ `pending` / `error` (nppsale không bao giờ hỏi RefID MISA chưa nhận — tờ khác giữ [=])."""
	if not isinstance(raw, dict) or not raw:
		return False
	r = raw.get("RefID")
	if isinstance(ref, str) and isinstance(r, str) and js_trim(r) and js_trim(r).casefold() == js_trim(ref).casefold():
		return True
	bg = doc_ban_ghi(raw)
	return bool(bg["huy"]) or any(bg[k] is not None for k in ("inv_no", "inv_series", "transaction_id", "invoice_code", "publish_status",
		"einvoice_status", "total_amount"))


# =====================================================================================================================================
# §2.4 Suy trạng thái — deriveState (status.ts:184–255). HAI TRỤC ở HAI trường: PublishStatus (phát hành) / EInvoiceStatus (quan hệ).
# =====================================================================================================================================

PUBLISH_STATUS_DA_CAP_MA = 3  # mốc DUY NHẤT chắc chắn "đã cấp mã" — `>= 1` KHÔNG phải "đã ký" (status.ts:22–38)
PUBLISH_STATUS_NHAP = 0
DUNG_SAI_TIEN = 1  # AMOUNT_TOLERANCE (status.ts:262): lệch đúng 1 đ bỏ qua, 2 đ báo

_QUAN_HE = {"1": "new", "3": "replacement", "4": "adjustment", "7": "replaced", "8": "adjusted"}


def quan_he(einvoice_status) -> str | None:
	"""readRelation (status.ts:40–52): None → None (không ghi, giữ cũ); 1/3/4/7/8 → new/replacement/adjustment/replaced/adjusted; số
	khác (kể cả 3,5) → 'unknown' — KHÔNG đoán. Tra như thuộc tính đối tượng JS (`RELATION_BY_CODE[x]` — khoá là `String(x)`): 7.0 → "7"
	→ replaced; chuỗi '7' (cột Data `einvoice_status` của snapshot) cũng vậy, '07' / '7.0' thì không."""
	if einvoice_status is None:
		return None
	return _QUAN_HE.get(_chuoi_js(einvoice_status), "unknown")


def suy_trang_thai(bg: dict, co_ma, dang) -> tuple:
	"""→ (status | None, relation | None, note | None). `bg` = `doc_ban_ghi(raw)`; `co_ma` = đơn vị dùng HĐ CÓ MÃ
	(`misa_is_invoice_with_code`); `dang` = `misa_status` đang lưu. status None = KHÔNG kết luận được, giữ nguyên trạng thái đang có.
	Ghi chú trong một kết luận nối bằng dấu cách."""
	rel = quan_he(bg.get("einvoice_status"))
	ghi = []
	if rel == "unknown":
		ghi.append(f"MISA trả EInvoiceStatus={so_js(bg.get('einvoice_status'))} (không rõ nghĩa) — chưa xác định quan hệ.")
	# Trạng thái CUỐI: huỷ và bị thay thế thắng mọi thứ khác.
	if bg.get("huy"):
		ly_do = bg.get("deleted_reason")
		ghi.append(f"MISA báo hoá đơn ĐÃ HUỶ ({so_js(bg.get('nguon_huy'))})" + (f" — lý do: {ly_do}." if ly_do else "."))
		return "cancelled", rel, " ".join(ghi) or None
	if rel == "replaced":
		ghi.append("Hoá đơn này đã BỊ THAY THẾ trên MISA — hết hiệu lực, không kê khai.")
		return "replaced", rel, " ".join(ghi)
	if rel == "adjusted":
		# BỊ điều chỉnh: VẪN còn hiệu lực — gộp vào 'replaced' là khai thiếu doanh thu bản gốc.
		ghi.append("Hoá đơn này BỊ ĐIỀU CHỈNH bởi một tờ khác — VẪN còn hiệu lực và vẫn phải kê khai.")
	if la_so_cho(bg.get("inv_no")):
		# Chưa cấp số: vẫn là nháp đã đẩy lên — không hạ trạng thái đang đúng xuống thấp hơn 'sent'.
		return (None if dang == "sent" else "sent"), rel, " ".join(ghi) or None
	ps = bg.get("publish_status")
	if _la_so_js(ps) and ps == PUBLISH_STATUS_DA_CAP_MA:
		return "signed", rel, " ".join(ghi) or None
	if _la_so_js(ps) and ps == PUBLISH_STATUS_NHAP:
		return "sent", rel, " ".join(ghi) or None
	# PublishStatus lạ (kể cả vắng): KHÔNG đoán, lùi về mốc chắc chắn.
	if js_dung(co_ma):
		if bg.get("invoice_code"):
			return "signed", rel, " ".join(ghi) or None
		ghi.append(f"MISA trả PublishStatus={so_js(ps)} (không rõ nghĩa) và chưa có mã CQT — đang chờ cấp mã.")
		return "waiting_code", rel, " ".join(ghi)
	ghi.append(
		f"MISA trả PublishStatus={so_js(ps)} (không rõ nghĩa). Đơn vị dùng hoá đơn "
		"KHÔNG MÃ nên không có mã CQT để đối chiếu — giữ nguyên trạng thái, cần kiểm tra tay."
	)
	return None, rel, " ".join(ghi)


# =====================================================================================================================================
# §2.5 So tiền — checkAmounts (status.ts:257–327)
# =====================================================================================================================================

def _so_so(v):
	"""Số của sổ (Currency Frappe có thể là Decimal) → int / float; None giữ None."""
	if v is None or isinstance(v, bool):
		return None
	if isinstance(v, Decimal):
		return float(v)
	return v if isinstance(v, (int, float)) else so(v)


def so_tien(bg: dict, relation, so_: dict) -> tuple:
	"""→ (lech, note, da_so). So CHỈ vế MISA thật sự trả số: luôn Tổng tiền; Tiền hàng / Thuế GTGT chỉ khi MISA trả khác 0 và khác None
	(0 nghĩa là "endpoint không tách thuế"); vế nào một bên None thì bỏ; lệch khi |MISA − sổ| > 1 đ. HĐ ĐIỀU CHỈNH mang số chênh — không so.
	`so_` = dòng sổ: `tien_hang`, `tien_thue`, `tong_tien` (KHÔNG trừ hàng trả, KHÔNG cộng giảm giá đơn — H10)."""
	if relation == "adjustment":
		return False, "Hoá đơn ĐIỀU CHỈNH mang số chênh, không phải tổng tiền — không so với sổ.", []
	lech, da_so = [], []

	def ss(nhan, misa, minh):
		if misa is None or minh is None:
			return
		da_so.append(nhan)
		if abs(misa - minh) > DUNG_SAI_TIEN:
			lech.append(f"{nhan}: sổ {so_js(minh)}, MISA {so_js(misa)}")

	ss("Tổng tiền", bg.get("total_amount"), _so_so(so_.get("tong_tien")))
	tw = bg.get("total_without_vat")
	if tw is not None and tw != 0:
		ss("Tiền hàng", tw, _so_so(so_.get("tien_hang")))
	tv = bg.get("total_vat")
	if tv is not None and tv != 0:
		ss("Thuế GTGT", tv, _so_so(so_.get("tien_thue")))
	if not lech:
		return False, None, da_so
	return True, f"Lệch tiền với MISA — {' · '.join(lech)}.", da_so


# =====================================================================================================================================
# §2.6 Áp kết quả — applyMisaSnapshot (apply.ts:45–134) + H8 / H17; H7 gộp ghi chú; H26 lọc ngày cho hàm ghi
# =====================================================================================================================================

def ap_dung(raw, so_: dict, co_ma, luc) -> dict:
	"""Dựng phần ghi cho MỘT dòng `NPP HDDT` từ bản ghi MISA trả về → `{cap_nhat, ghi_chu, danh_dau_goc, tom_tat}`. Làm mới, vòng quét và
	đẩy-lại-thấy-trên-MISA cùng đi qua đây nên không thể kết luận khác nhau về một tờ.

	`so_` = {misa_inv_no, misa_status, misa_no_locked, tien_hang, tien_thue, tong_tien, so_hd_go_tay}. `cap_nhat` CHỈ chứa khoá có giá trị
	(ghi None đè là xoá trắng mã tra cứu đang đúng — Gotcha #7); `misa_last_checked_at = luc` LUÔN có (lượt 2 sắp theo cột này).
	`misa_note` KHÔNG nằm trong `cap_nhat`: hàm ghi gộp `ghi_chu` bằng `gop_ghi_chu` (H7). `danh_dau_goc` = OrgRefID chỉ khi tờ này là bản
	THAY THẾ (điều chỉnh cũng mang OrgRefID mà bản gốc VẪN hiệu lực).

	Lệch có chủ ý: [ĐX H8] MISA trả bản ghi chưa có số cho tờ sổ đã có số → không hạ về 'sent' + ghi chú; [ĐX H17] số gõ tay khác số MISA →
	ghi chú (không đổi trạng thái). Thứ tự ghi chú: suy trạng thái, H8, khoá gán tay, so tiền, H17."""
	bg = doc_ban_ghi(raw)
	st, rel, note = suy_trang_thai(bg, co_ma, so_.get("misa_status"))
	ghi_chu = [note] if note else []
	so_that = not la_so_cho(bg["inv_no"])
	so_so = so_.get("misa_inv_no")

	if not so_that and not la_so_cho(so_so) and st == "sent":  # [ĐX H8]
		st = None
		ghi_chu.append(f"MISA trả bản ghi chưa có số trong khi sổ đã ghi số {so_js(so_so)} — giữ nguyên trạng thái, cần kiểm tra tay.")

	cap = {}
	if so_that:
		if js_dung(so_.get("misa_no_locked")):
			# Số người GÁN TAY: không đè, nhưng KHÔNG im lặng (Gotcha #8).
			if so_khac(so_so, bg["inv_no"]):
				ghi_chu.append(f"Sổ ghi số {so_js(so_so)}, MISA cấp số {bg['inv_no']} (khoá gán tay nên không ghi đè).")
				st = "amount_mismatch"
		else:
			cap["misa_inv_no"] = bg["inv_no"]
	if bg["inv_series"]:
		cap["misa_inv_series"] = bg["inv_series"]
	if bg["transaction_id"]:
		cap["misa_lookup_code"] = bg["transaction_id"]
	if bg["invoice_code"]:
		cap["misa_invoice_code"] = bg["invoice_code"]
	if bg["org_ref_id"]:
		cap["misa_org_ref_id"] = bg["org_ref_id"]
	if rel:
		cap["misa_relation"] = rel
	if bg["inv_date"]:
		d = ngay_iso(bg["inv_date"])
		if d:
			cap["misa_inv_date"] = d

	lech, note_tien, da_so = so_tien(bg, rel, so_)
	if note_tien:
		ghi_chu.append(note_tien)
	if lech and st not in ("cancelled", "replaced"):
		st = "amount_mismatch"  # lệch tiền KHÔNG đè trạng thái cuối

	go_tay = chuoi(so_.get("so_hd_go_tay"))
	if go_tay and so_that and not cung_so(go_tay, bg["inv_no"]):  # [BP H17]
		ghi_chu.append(f"Sổ ghi số {go_tay}, MISA cấp số {bg['inv_no']}.")

	if st:
		cap["misa_status"] = st
	cap["misa_last_checked_at"] = luc
	return {
		"cap_nhat": cap,
		"ghi_chu": ghi_chu,
		"danh_dau_goc": bg["org_ref_id"] if rel == "replacement" and bg["org_ref_id"] else None,
		"tom_tat": {
			"InvNo": bg["inv_no"] if so_that else None,
			"status": st,
			"relation": rel,
			"amountsCompared": da_so,
			"notes": list(ghi_chu),
		},
	}


def gop_ghi_chu(cu: str | None, moi) -> str | None:
	"""[BP H7] `misa_note` = các dòng cũ + dòng mới CHƯA có nguyên văn trong ô, nối "\\n" (nppsale THAY cả ô — `apply.ts:113`,
	`mark-replaced.ts` — là mất ghi chú "MẤT RefID" / ghi chú người). Không có dòng mới → trả nguyên ô cũ (người gọi so để biết có đổi không)."""
	dong = cu.split("\n") if cu else []
	them = []
	for m in moi or ():
		if m and m not in dong and m not in them:
			them.append(m)
	if not them:
		return cu
	return "\n".join(dong + them)


def ghi_chu_ngay_khong_that(inv_date_tho) -> str:
	"""[ĐX H26] Câu ghi chú khi MISA trả InvDate không phải ngày có thật (`inv_date_tho` = InvDate đã trim)."""
	return f"MISA trả InvDate={inv_date_tho} không phải ngày có thật — bỏ qua, cần kiểm tra tay."


def bo_ngay_khong_that(cap_nhat: dict, raw) -> list:
	"""[ĐX H26 — §4.8 bước 4b] `cap_nhat.misa_inv_date` (do `ngay_iso` giữ đúng TS) không phải ngày có thật → BỎ khoá ấy (sửa tại chỗ) và
	trả một ghi chú; các khoá khác vẫn ghi. nppsale: Postgres từ chối cả câu UPDATE, Làm mới vẫn 200 mà sổ không đổi gì."""
	d = cap_nhat.get("misa_inv_date")
	if d is None or ngay_that(d):
		return []
	cap_nhat.pop("misa_inv_date")
	return [ghi_chu_ngay_khong_that(doc_ban_ghi(raw)["inv_date"])]


def ghi_chu_bi_thay_the(ten_thay_the) -> str:
	"""Câu ghi chú tờ GỐC khi phát hiện bản thay thế qua OrgRefID (mark-replaced.ts:50–52; `danh_dau_goc` §4.7 THÊM dòng — H7)."""
	return (
		"Đã bị thay thế bởi một hoá đơn khác trên MISA (phát hiện qua OrgRefID của tờ "
		f"thay thế, id nội bộ {ten_thay_the}). Hết hiệu lực — KHÔNG kê khai tờ này."
	)


# =====================================================================================================================================
# §2.7 Dòng hàng (publish/route.ts:197–313) + dựng payload (mapper.ts:90–203)
# =====================================================================================================================================

def gia_gop(gia_ban, giam, sl) -> float:
	"""Đơn giá GỘP đưa mapper (route.ts:216, 280 — `qty > 0 ? netPrice + discount / qty : netPrice`): CỘNG NGƯỢC giảm dòng vào đơn giá ĐÃ
	giảm. Mapper coi đơn giá là giá bảng (AmountOC = SL × giá rồi mới trừ giảm dòng) — quên cộng ngược là trừ chiết khấu HAI lần, HĐĐT gửi cơ
	quan thuế thấp hơn thực tế đúng bằng khoản giảm."""
	q = _js_so(_hoac(sl, 0))
	gia = _js_so(_hoac(gia_ban, 0))
	g = _js_so(_hoac(giam, 0))
	return gia + g / q if q > 0 else gia


def thue_phan_tram(r, khi_trong=0):
	"""Thuế suất dòng → PHẦN TRĂM MISA đòi (route.ts:217, 228 / 289–290): `Math.round(r × (100 nếu r ≤ 1, ngược lại 1))` — 0,1 → 10,
	0,08 → 8, 10 → 10 (và 1 → 100: chép nguyên). `r` None: nhánh HĐ bán / LS `khi_trong=0` (`Number(l.vat_rate ?? 0)` — thuế chụp trên
	dòng, NULL là 0 %); nhánh đơn cũ `khi_trong=10` (`products.vat_rate` NULL → 10)."""
	if r is None:
		return khi_trong
	x = _js_so(r)
	v = _lam_tron_js(x * (100 if x <= 1 else 1))
	return int(v) if math.isfinite(v) else v


def dong_hang(ten, sku, dvt, dvt_co_so, sl, gia_ban, giam, he_so, vat) -> dict:
	"""Một dòng chứng từ (Sales Invoice Item / dòng LS / Sales Order Item — §4.1.2) → dòng của `dung_payload` (route.ts:207–230):
	`gia_ban` = đơn giá ĐÃ giảm (`rate`), `giam` = tổng giảm của DÒNG (trường ghi nhớ `npp_giam_dong` — KHÔNG đọc `discount_amount` /
	`price_list_rate` của lõi: dòng hàng đổi mang giá bảng ở đó), `vat` = `thue_phan_tram(...)`. ĐVT trống → ĐVT cơ sở → ''."""
	return {
		"ten": _hoac(ten, ""),
		"sku": _hoac(sku, None),
		"dvt": _hoac(dvt, None) or _hoac(dvt_co_so, ""),
		"dvt_co_so": _hoac(dvt_co_so, None),
		"sl": _js_so(_hoac(sl, 0)),
		"don_gia": gia_gop(gia_ban, giam, sl),
		"he_so": _js_so(_hoac(he_so, 1)),
		"vat": vat,
		"giam": _js_so(_hoac(giam, 0)),
	}


def dong_tong_hop(tien_hang, tien_thue, tong_tien) -> dict:
	"""Không đọc được dòng hàng (tờ tay / không gắn chứng từ — route.ts:298–313): MỘT dòng "Hàng hoá, dịch vụ" / "Lần", đơn giá = tiền hàng ∥
	tổng tiền, thuế = `Math.round(tien_thue / tien_hang × 100)` (tiền hàng > 0) ngược lại 10. Mức thuế trộn ⇒ tổng lệch sổ: 195.000 +
	17.600 → 9 % → 17.550, tổng 212.550 [đo M4]."""
	sub = _js_so(_hoac(tien_hang, 0))
	if sub > 0:
		v = _lam_tron_js((_js_so(_hoac(tien_thue, 0)) / sub) * 100)
		vat = int(v) if math.isfinite(v) else v
	else:
		vat = 10
	return {
		"ten": "Hàng hoá, dịch vụ",
		"sku": None,
		"dvt": "Lần",
		"dvt_co_so": None,
		"sl": 1,
		"don_gia": sub if js_dung(sub) else _js_so(_hoac(tong_tien, 0)),
		"he_so": 1,
		"vat": vat,
		"giam": 0,
	}


_GIO_VN = _dt.timezone(_dt.timedelta(hours=7))


def gio_vn(luc: _dt.datetime) -> str:
	"""vnInvoiceDate (mapper.ts:70–80): giờ VN `YYYY-MM-DDTHH:MM:SS+07:00` tính từ thời điểm tuyệt đối (UTC + 7 giờ) — không phụ thuộc múi
	giờ site. `luc` PHẢI có múi giờ (vd `datetime.now(UTC)`): datetime trần thì không biết là giờ nào ⇒ ValueError."""
	if not isinstance(luc, _dt.datetime) or luc.utcoffset() is None:
		raise ValueError("gio_vn: luc phải là datetime có múi giờ (vd datetime.now(UTC)).")
	return luc.astimezone(_GIO_VN).strftime("%Y-%m-%dT%H:%M:%S") + "+07:00"


def _so_json(v):
	"""Số đưa vào JSON gửi MISA: số nguyên phát `int` (`json.dumps(2.0)` là "2.0", JSON.stringify là "2"); số lẻ (SL quy đổi lẻ) giữ float."""
	if isinstance(v, bool) or v is None:
		return v
	if isinstance(v, Decimal):
		v = float(v)
	if isinstance(v, float) and v.is_integer() and abs(v) <= _SO_NGUYEN_AN_TOAN:
		return int(v)
	return v


def _ten_lien_he(nguoi_mua: dict, po_note) -> str | None:
	"""buildContactName (mapper.ts:82–88): có ghi chú PO (sau trim) → "{tên}, {PO}" (nhánh kênh MT ra cùng chuỗi); không → None."""
	po = js_trim(po_note) if isinstance(po_note, str) else ""
	if po:
		return f"{so_js(nguoi_mua.get('ten'))}, {po}"
	return None


def dung_payload(nguoi_mua: dict, dong: list, ref_id: str, cau_hinh: dict, che_do: str = "as_sold", po_note=None, luc=None,
		sinh_uuid=None) -> list:
	"""invoiceToMisaPayload (mapper.ts:90–203) → thân gửi `/v3sainvoice` = MẢNG `[header]`. Khác TS duy nhất: `ref_id` truyền TỪ NGOÀI
	(đã commit trước khi gọi MISA — H3, BP §7.3-10), `sinh_uuid` (RefDetailID từng dòng) tiêm được; `luc` = thời điểm dựng (có múi giờ).

	`nguoi_mua` = {ten, mst, dia_chi, email, kenh, hinh_thuc_tt}; `dong` = [{ten, sku, dvt, dvt_co_so, sl, don_gia (GIÁ GỘP — `dong_hang`),
	he_so, vat (%), giam}] theo thứ tự `idx` / `sort_order` (H19); `cau_hinh` = trường của `NPP MISA Cau Hinh` (misa_company_id,
	misa_org_unit_id, misa_user_id, loai_hd, misa_inv_series, misa_inv_template_no, misa_template_id, ke_thua_mau_cu); `che_do` 'box'
	quy về ĐVT cơ sở khi hệ số > 1, khác 'box' là as_sold.

	Mỗi dòng: AmountOC = tron(SL × giá) (giá CHƯA làm tròn), VAT tròn TỪNG dòng = tron((AmountOC − giảm) × thuế / 100) (Q3 câu 19 (c));
	`tron` là Math.round của JS. Người bán KHÔNG có trong payload (MST người bán đi ở header HTTP `TaxCode`)."""
	box = che_do == "box"
	sinh = sinh_uuid or (lambda: str(uuid.uuid4()))
	bay_gio = gio_vn(luc if luc is not None else _dt.datetime.now(_dt.UTC))
	ty_gia = 1

	chi_tiet = []
	for i, l in enumerate(dong):
		cf = _hoac(_js_so(_hoac(l.get("he_so"), 1)), 1)
		dvt = l.get("dvt")
		sl = _js_so(_hoac(l.get("sl"), 0))
		gia = _js_so(_hoac(l.get("don_gia"), 0))
		if box and cf > 1:
			dvt = _hoac(l.get("dvt_co_so"), dvt)
			sl = sl * cf
			gia = gia / cf
		thue = 10 if l.get("vat") is None else _js_so(l.get("vat"))
		giam = tron(_hoac(l.get("giam"), 0))
		tien = tron(sl * gia)
		tien_thue = tron(((tien - giam) * thue) / 100)
		chi_tiet.append({
			"RefDetailID": sinh(),
			"RefID": ref_id,
			"InventoryItemType": 1,
			"InventoryItemCode": _hoac(l.get("sku"), ""),
			"Description": l.get("ten"),
			"UnitName": dvt,
			"Quantity": _so_json(sl),
			"UnitPrice": tron(gia),
			"AmountOC": tien,
			"Amount": tien * ty_gia,
			"DiscountRate": 0,
			"DiscountAmountOC": giam,
			"DiscountAmount": giam * ty_gia,
			"VATRate": _so_json(thue),
			"VATAmountOC": tien_thue,
			"VATAmount": tien_thue * ty_gia,
			"SortOrder": i + 1,
			"SortOrderView": i + 1,
			"IsPromotion": False,
		})

	tong_ban = sum((d["AmountOC"] for d in chi_tiet), 0)
	tong_giam = sum((d["DiscountAmountOC"] for d in chi_tiet), 0)
	tong_thue = sum((d["VATAmountOC"] for d in chi_tiet), 0)
	truoc_thue = tong_ban - tong_giam
	tong = truoc_thue + tong_thue
	muc = {d["VATRate"] for d in chi_tiet}
	nhieu_muc = len(muc) > 1
	thue_dau = 0 if nhieu_muc else (chi_tiet[0]["VATRate"] if chi_tiet else 10)
	loai = cau_hinh.get("loai_hd")
	header = {
		"RefID": ref_id,
		"CompanyID": _hoac(cau_hinh.get("misa_company_id"), ""),
		"OrganizationUnitID": _hoac(cau_hinh.get("misa_org_unit_id"), ""),
		"UserID": _hoac(cau_hinh.get("misa_user_id"), ""),
		"InvoiceType": _so_json(1 if loai is None else loai),
		"InvSeries": _hoac(cau_hinh.get("misa_inv_series"), ""),
		"InvTemplateNo": _hoac(cau_hinh.get("misa_inv_template_no"), "1"),
		"InvoiceTemplateID": _hoac(cau_hinh.get("misa_template_id"), ""),
		"IsInheritFromOldTemplate": js_dung(cau_hinh.get("ke_thua_mau_cu")),
		"InvDate": bay_gio,
		"InvNo": "<Chưa cấp số>",
		"SourceType": 0,
		"SendInvoiceStatus": 0,
		"SendNumber": 0,
		"CurrencyCode": "VND",
		"CurrencyID": "VND",
		"ExchangeRate": ty_gia,
		"ExchangeRateOperation": 0,
		"TypeDiscount": 1 if tong_giam > 0 else 0,  # 1 = chiết khấu dòng
		"DiscountRate": 0,
		"IsMoreVATRate": nhieu_muc,
		"VATRate": thue_dau,
		"EInvoiceStatus": 0,
		"PaymentStatus": 0,
		"PaymentRule": 0,
		"ApproveStep": -3,
		"CreatedDate": bay_gio,
		"ModifiedDate": bay_gio,
		"EditVersion": 0,
		"OrgInvoiceType": 1,
		"TotalSaleAmountOC": tong_ban,
		"TotalSaleAmount": tong_ban * ty_gia,
		"TotalAmountWithoutVATOC": truoc_thue,
		"TotalAmountWithoutVAT": truoc_thue * ty_gia,
		"TotalVATAmountOC": tong_thue,
		"TotalVATAmount": tong_thue * ty_gia,
		"TotalDiscountAmountOC": tong_giam,
		"TotalDiscountAmount": tong_giam * ty_gia,
		"TotalAmountOC": tong,
		"TotalAmount": tong * ty_gia,
		"AccountObjectTaxCode": _hoac(nguoi_mua.get("mst"), ""),
		"AccountObjectName": nguoi_mua.get("ten"),
		"AccountObjectAddress": _hoac(nguoi_mua.get("dia_chi"), ""),
		"AccountObjectCode": "",
		"ContactName": _hoac(_ten_lien_he(nguoi_mua, po_note), nguoi_mua.get("ten")),
		"ReceiverEmail": _hoac(nguoi_mua.get("email"), ""),
		"ReceiverName": "",
		"ReceiverMobile": "",
		"PaymentMethod": _hoac(nguoi_mua.get("hinh_thuc_tt"), "TM/CK"),
		"IsTaxReduction43": 8 in muc,
		"InvoiceDetails": chi_tiet,
	}
	return [header]


def ma_url(s: str) -> str:
	"""`encodeURIComponent` của JS (giữ A–Z a–z 0–9 - _ . ! ~ * ' ( ))."""
	return quote(s, safe="-_.!~*'()")


def url_tra_cuu(ma) -> str | None:
	"""Link tra cứu công khai khi phát hành có mã (route.ts:390–392); không mã → None."""
	return f"https://www.meinvoice.vn/tra-cuu?code={ma_url(ma)}" if js_dung(ma) else None


# =====================================================================================================================================
# §2.8 Hiểu phản hồi MISA (client.ts) — chỉ phần ĐỌC; gửi / thử lại / token RAM là việc của nppsale/api/misa_mang.py
# =====================================================================================================================================

CAU_THIEU_DUONG_TOKEN = "Chưa cấu hình 'Endpoint lấy token' (token_path) cho MISA. Vào Cài đặt → Hoá đơn điện tử."
CAU_THIEU_DUONG_DAY = "Chưa cấu hình 'Endpoint phát hành' (publish_path) cho MISA. Vào Cài đặt → Hoá đơn điện tử."
CAU_KHONG_CO_DU_LIEU = (
	"MISA trả success nhưng không có dữ liệu hoá đơn. "
	"Thường do: api_base sai (sandbox vs production lệch tài khoản), hoặc path không trùng (/v3sainvoice vs /v3sainvoice/Code)."
)


def _la_2xx(http_status) -> bool:
	return isinstance(http_status, int) and 200 <= http_status <= 299


def _doc_than(text, khi_hong):
	"""`text ? JSON.parse(text) : {}`; parse hỏng → `khi_hong(text)`."""
	if not text:
		return {}
	try:
		return js_doc_json(text)
	except ValueError:
		return khi_hong(text)


def loi_misa(data, text) -> str:
	"""extractErrorMessage (client.ts:285–304): `error_description || error` (truthy kiểu JS) là chuỗi khác rỗng → nó + " ({error})" nếu
	`error` là chuỗi khác nó (kể cả chuỗi rỗng); không thì nối " — " các chuỗi khác rỗng của ErrorCode, DescriptionErrorCode,
	descriptionErrorCode, Errors, errorMessage, message; không có → 500 đơn vị UTF-16 đầu của thân."""
	d = data if isinstance(data, dict) else {}
	e = _hoac(d.get("error_description"), d.get("error"))
	if isinstance(e, str) and e:
		loi = d.get("error")
		return e + (f" ({loi})" if isinstance(loi, str) and loi != e else "")
	phan = [x for x in (d.get(k) for k in ("ErrorCode", "DescriptionErrorCode", "descriptionErrorCode", "Errors", "errorMessage", "message"))
		if isinstance(x, str) and x]
	if phan:
		return " — ".join(phan)
	return js_cat(text or "", 500)


def la_loi_xac_thuc(http_status, text) -> bool:
	"""looksLikeAuthError (client.ts:373–377): 401 / 403, hoặc thân (chữ thường) có "token" / "expired" / "unauthorized" — ĐÚNG CẢ với 400 /
	500 (H27). Chỉ xét khi HTTP lỗi."""
	if http_status in (401, 403):
		return True
	t = (text or "").lower()
	return "token" in t or "expired" in t or "unauthorized" in t


def _boc_ket_qua_day(obj: dict) -> tuple:
	"""extractPublishResult (client.ts:379–449) → (lookup, inv_no, ref_id, trong_ok, trong_loi). Bóc `data` / `newdata` / `content` / `Data`
	(chuỗi JSON lồng): ra MẢNG khác rỗng → lấy phần tử đầu làm ứng viên; ra đối tượng → coi là map RefID → kết quả, duyệt giá trị THEO THỨ TỰ
	KHOÁ CỦA JS (`js_khoa`), mỗi giá trị kiểu đối tượng thành ứng viên + đọc Success / ErrorMessage / ErrorCode + bóc tiếp `Data`. ⚠ `Data`
	bên trong là chuỗi của MỘT object HĐ (dạng tài liệu mô tả) thì object ấy bị coi là "map" và KHÔNG vào ứng viên ⇒ không đọc được mã
	[đo thu3] — chép nguyên văn (H20)."""
	ung_vien = [obj]
	trang = {"ok": None, "loi": None}

	def boc(v):
		if not isinstance(v, str) or not v:
			return
		try:
			p = js_doc_json(v)
		except ValueError:
			return
		if isinstance(p, list) and p:
			ung_vien.append(p[0])
		elif isinstance(p, dict):
			for k in js_khoa(p):
				e = p[k]
				if isinstance(e, (dict, list)):
					ung_vien.append(e)
					if isinstance(e, dict):
						s = e.get("Success")
						if isinstance(s, bool):
							trang["ok"] = s
						m = e.get("ErrorMessage")
						if isinstance(m, str) and m:
							trang["loi"] = m
						ec = e.get("ErrorCode")
						if isinstance(ec, list) and ec:
							trang["loi"] = (trang["loi"] + " · " if trang["loi"] else "") + js_json(ec)
						boc(e.get("Data"))

	for k in ("data", "newdata", "content", "Data"):
		boc(obj.get(k))

	def chon(*khoa):
		for src in ung_vien:
			if not isinstance(src, dict):
				continue
			for k in khoa:
				v = src.get(k)
				if isinstance(v, str) and v:
					return v
				if _la_so_js(v):
					return so_js(v)
		return None

	return (
		chon("TransactionID", "transactionID", "LookupCode", "lookupCode", "lookup_code"),
		# KHÔNG lùi về RefID (mig 099: inv_no nhận GUID là lẫn khoá).
		chon("InvNo", "invNo", "InvoiceNumber"),
		chon("RefID", "refID"),
		trang["ok"],
		trang["loi"],
	)


def hieu_phan_hoi_day(http_status: int, text: str) -> dict:
	"""Đọc trả lời của `POST /v3sainvoice` (publishInvoice, client.ts:491–564) → {ok, raw, error, lookup_code, inv_no, ref_id}.
	`raw` = thân đã parse (không phải JSON → {"raw": thân}). Thứ tự: HTTP lỗi → "MISA publish lỗi {HTTP}: …"; Success / success là False hoặc
	errorCode / ErrorCode là chuỗi khác rỗng → "MISA publish thất bại: …"; kết quả bên trong Success False → "MISA từ chối hoá đơn: …";
	không có gì nhận ra (data / newdata rỗng, content vắng, không mã nào) → CAU_KHONG_CO_DU_LIEU; còn lại ok. (TS bỏ khoá `ref_id` khi
	hỏng — ở đây luôn có, None.)"""
	text = text or ""
	data = _doc_than(text, lambda t: {"raw": t})
	obj = data if isinstance(data, dict) else {}

	def hong(cau):
		return {"ok": False, "raw": data, "error": cau, "lookup_code": None, "inv_no": None, "ref_id": None}

	if not _la_2xx(http_status):
		return hong(f"MISA publish lỗi {so_js(http_status)}: {loi_misa(data, text)}")
	if (obj.get("Success") is False or obj.get("success") is False
			or (isinstance(obj.get("errorCode"), str) and obj.get("errorCode") != "")
			or (isinstance(obj.get("ErrorCode"), str) and obj.get("ErrorCode") != "")):
		return hong(f"MISA publish thất bại: {loi_misa(data, text)}")
	lookup, inv_no, ref_id, trong_ok, trong_loi = _boc_ket_qua_day(obj)
	if trong_ok is False:
		return hong(f"MISA từ chối hoá đơn: {trong_loi or loi_misa(data, text)}")
	rong = (obj.get("data") in ("", None) and obj.get("newdata") in ("", None) and obj.get("content") is None
		and not lookup and not inv_no and not ref_id and trong_ok is not True)
	if rong:
		return hong(CAU_KHONG_CO_DU_LIEU)
	return {"ok": True, "raw": data, "error": None, "lookup_code": lookup, "inv_no": inv_no, "ref_id": ref_id}


# --- /oauth ---------------------------------------------------------------------------------------------------------------------------

# (a) giá trị của MỌI khoá có chữ "token" — kể cả phần tử đầu của mảng (`"tokens":["…"]`); giá trị dừng ở nháy / phẩy / & / khoảng trắng / } / ]
_KHOA_TOKEN = re.compile(r'(?i)(\\?"?[A-Za-z0-9_]*token[A-Za-z0-9_]*\\?"?\s*[:=]\s*(?:\[\s*)?\\?"?)([^"\\,&\s}\]]+)')
# (b) chuỗi dạng JWT ở BẤT KỲ đâu (eyJ<đầu>.<thân>.<chữ ký>)
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")
# (c) giá trị TRÔNG NHƯ token (≥ 20 ký tự base64url liền, không khoảng trắng) của khoá data / jwt / access / bearer / *key: API tích hợp của MISA trả
#     `{"Success":true,"Data":"<token>"}` — tên khoá không có chữ "token" nên (a) không bắt
_KHOA_GIONG_TOKEN = re.compile(
	r'(?i)(\\?"?(?:data|jwt|access|bearer|[A-Za-z0-9_]*key)\\?"?\s*[:=]\s*(?:\[\s*)?\\?"?)([A-Za-z0-9_\-.+/=]{20,})(?=\\?"|[,&\s}\]]|$)')


def che_token(text: str) -> str:
	"""[ĐX H25] Che token trên CHUỖI THÔ — một luật cho JSON, JSON lồng trong chuỗi (`\\"`) và dạng form; không parse rồi dựng lại (đổi khoảng
	trắng là câu lệch nppsale cả khi không có gì để che): (a) giá trị MỌI khoá có chữ "token" (không phân biệt hoa thường, kể cả trong mảng);
	[Sửa cuối — phát hiện 7] (b) mọi chuỗi dạng JWT; (c) giá trị dạng token (≥ 20 ký tự base64url) của khoá data / jwt / access / bearer / *key.
	`{"Data":{"AccessToken":"T"}}` → `{"Data":{"AccessToken":"***"}}`, `access_token=a&token_type=b` → `access_token=***&token_type=***`,
	`{"tokens":["T"]}` → `{"tokens":["***"]}`, `{"success":true,"data":"eyJ….….…"}` → `{"success":true,"data":"***"}`. Thân không có gì giống token
	giữ y nppsale (KV-14 `{"foo":1}`). Gọi lại trên chuỗi đã che không đổi gì (`***` che thành `***`)."""
	t = _JWT.sub("***", text or "")
	t = _KHOA_TOKEN.sub(lambda m: m.group(1) + "***", t)
	return _KHOA_GIONG_TOKEN.sub(lambda m: m.group(1) + "***", t)


def _lay_token(d: dict) -> str | None:
	"""extractToken (client.ts:33–47): access_token ∥ accessToken ∥ Data.access_token ∥ data.access_token — chuỗi khác rỗng."""
	cho = [d.get("access_token"), d.get("accessToken")]
	for k in ("Data", "data"):
		v = d.get(k)
		cho.append(v.get("access_token") if isinstance(v, dict) else None)
	for c in cho:
		if isinstance(c, str) and c:
			return c
	return None


def doc_phan_hoi_token(http_status: int, text: str) -> dict:
	"""Đọc trả lời `POST /oauth` (getToken, client.ts:341–370; thân thô của getTokenWithRawResponse :279–282) → {token, expires_in, loi, tho}.
	HTTP lỗi HOẶC thân có `error` là chuỗi khác rỗng (MISA hay trả 200 kèm {error, error_description, status: 401}) → "MISA token lỗi
	{status số trong thân ∥ HTTP}: …"; không thấy token → "MISA token: không thấy access_token trong response. Raw: {300 đơn vị đầu}" — phần
	Raw đã qua `che_token` [ĐX H25: nppsale in nguyên, token lọt vào misa_error / nhật ký]. `tho` = thân đã parse ({"_raw": thân} nếu không phải
	JSON) cho Thử kết nối (`tach_dinh_danh`)."""
	text = text or ""
	data = _doc_than(text, lambda t: {})
	tho = _doc_than(text, lambda t: {"_raw": t})
	d = data if isinstance(data, dict) else {}
	co_loi = isinstance(d.get("error"), str) and d.get("error") != ""
	if not _la_2xx(http_status) or co_loi:
		st = d.get("status")
		ma = so_js(st) if _la_so_js(st) else so_js(http_status)
		# [Sửa cuối — phát hiện 7] che cả nhánh HTTP lỗi: thân thô (500 ký tự của `loi_misa`) che TRƯỚC khi cắt (token nằm vắt qua mốc cắt không
		# lọt nửa), câu lấy từ trường lỗi che SAU — câu không có gì giống token giữ y nppsale ("Sai tài khoản hoặc mật khẩu (invalid_grant)")
		return {"token": None, "expires_in": None, "loi": f"MISA token lỗi {ma}: {che_token(loi_misa(data, che_token(text)))}", "tho": tho}
	tok = _lay_token(d)
	if not tok:
		return {"token": None, "expires_in": None,
			"loi": f"MISA token: không thấy access_token trong response. Raw: {js_cat(che_token(text), 300)}", "tho": tho}
	return {"token": tok, "expires_in": d.get("expires_in"), "loi": None, "tho": tho}


# --- GET ?refID= / danh sách / mẫu ----------------------------------------------------------------------------------------------------

def _chuoi_du_lieu(d: dict):
	"""`obj["data"] ?? obj["Data"]` — `Data` chỉ khi `data` vắng / null (chuỗi rỗng KHÔNG lùi)."""
	v = d.get("data")
	return d.get("Data") if v is None else v


def doc_phan_hoi_lay_hd(http_status: int, text: str) -> dict:
	"""Đọc trả lời `GET /v3sainvoice/[code/]?refID=` (getInvoiceByRefId, client.ts:166–177) → {loi, ban_ghi}. HTTP lỗi → "Lấy HD lỗi
	{HTTP}: …" (401 cũng không lấy token mới — chép nguyên); success / Success False → "Lấy HD thất bại: …"; `data` (∥ `Data`) là chuỗi JSON
	khác rỗng → bản ghi. Không phải chuỗi / rỗng / parse hỏng / parse ra null, false, 0, '' → None (không có dữ liệu); parse ra kiểu khác
	không phải dict → {} (JS coi là có dữ liệu)."""
	text = text or ""
	obj = _doc_than(text, lambda t: {})
	d = obj if isinstance(obj, dict) else {}
	if not _la_2xx(http_status):
		return {"loi": f"Lấy HD lỗi {so_js(http_status)}: {loi_misa(obj, text)}", "ban_ghi": None}
	if d.get("success") is False or d.get("Success") is False:
		return {"loi": f"Lấy HD thất bại: {loi_misa(obj, text)}", "ban_ghi": None}
	s = _chuoi_du_lieu(d)
	if not isinstance(s, str) or not s:
		return {"loi": None, "ban_ghi": None}
	try:
		v = js_doc_json(s)
	except ValueError:
		return {"loi": None, "ban_ghi": None}
	if isinstance(v, dict):
		return {"loi": None, "ban_ghi": v}
	return {"loi": None, "ban_ghi": {} if js_dung(v) else None}


def _mang_trong_chuoi(d: dict) -> list:
	s = _chuoi_du_lieu(d)
	if not isinstance(s, str) or not s:
		return []
	try:
		v = js_doc_json(s)
	except ValueError:
		return []
	return v if isinstance(v, list) else []


def doc_phan_hoi_ds(http_status: int, text: str) -> dict:
	"""Đọc trả lời `POST /[code/]v3sainvoice/paging` (listInvoices, client.ts:224–252) → {loi, dong, records_total}. `recordsTotal` ∥
	`RecordsTotal` chỉ khi là số; `data` ∥ `Data` là chuỗi JSON MẢNG (parse hai lần); méo → [] không ném (một trang méo không làm hỏng cả lượt)."""
	text = text or ""
	obj = _doc_than(text, lambda t: {})
	d = obj if isinstance(obj, dict) else {}
	if not _la_2xx(http_status):
		return {"loi": f"Lấy danh sách HD lỗi {so_js(http_status)}: {loi_misa(obj, text)}", "dong": [], "records_total": None}
	if d.get("success") is False or d.get("Success") is False:
		return {"loi": f"Lấy danh sách HD thất bại: {loi_misa(obj, text)}", "dong": [], "records_total": None}
	tong = d.get("recordsTotal")
	if tong is None:
		tong = d.get("RecordsTotal")
	return {"loi": None, "dong": _mang_trong_chuoi(d), "records_total": tong if _la_so_js(tong) else None}


def doc_phan_hoi_mau(http_status: int, text: str) -> dict:
	"""Đọc trả lời `POST /v3common/[code/]template` (getInvoiceTemplates, client.ts:128–144) → {loi, mau} (mảng mẫu; méo → [])."""
	text = text or ""
	obj = _doc_than(text, lambda t: {})
	d = obj if isinstance(obj, dict) else {}
	if not _la_2xx(http_status):
		return {"loi": f"Lấy mẫu HD lỗi {so_js(http_status)}: {loi_misa(obj, text)}", "mau": []}
	if d.get("success") is False or d.get("Success") is False:
		return {"loi": f"Lấy mẫu HD thất bại: {loi_misa(obj, text)}", "mau": []}
	return {"loi": None, "mau": _mang_trong_chuoi(d)}


def tach_dinh_danh(raw) -> dict:
	"""extractTenantIds (client.ts:53–102): ứng viên = thân `/oauth`, `Data`, `data` (đối tượng, hoặc chuỗi JSON ra đối tượng). companyId /
	orgUnitId / userId = chuỗi khác rỗng hoặc số (→ `so_js`: 156217 → "156217"); isInvoiceWithCode = bool, hoặc chuỗi "true" / "false"
	(không phân biệt hoa thường, sau trim) ∥ None."""
	obj = raw if isinstance(raw, (dict, list)) else {}
	ung_vien = [obj]
	if isinstance(obj, dict):
		for k in ("Data", "data"):
			v = obj.get(k)
			if isinstance(v, (dict, list)):
				ung_vien.append(v)
			elif isinstance(v, str) and v:
				try:
					p = js_doc_json(v)
				except ValueError:
					continue
				if isinstance(p, (dict, list)):
					ung_vien.append(p)

	def chon(*khoa):
		for src in ung_vien:
			if not isinstance(src, dict):
				continue
			for k in khoa:
				v = src.get(k)
				if isinstance(v, str) and v:
					return v
				if _la_so_js(v):
					return so_js(v)
		return None

	def chon_bool(*khoa):
		for src in ung_vien:
			if not isinstance(src, dict):
				continue
			for k in khoa:
				v = src.get(k)
				if isinstance(v, bool):
					return v
				if isinstance(v, str):
					t = js_trim(v.lower())
					if t == "true":
						return True
					if t == "false":
						return False
		return None

	return {
		"companyId": chon("CompanyID", "companyID", "companyId", "company_id"),
		"orgUnitId": chon("OrganizationUnitID", "organizationUnitID", "organizationUnitId", "OrgUnitID"),
		"userId": chon("UserID", "userID", "userId", "user_id"),
		"isInvoiceWithCode": chon_bool("IsInvoiceWithCode", "isInvoiceWithCode"),
	}


# =====================================================================================================================================
# §5.3 bước 4 — một bản ghi danh sách MISA → dòng NPP MISA Snapshot (toSnapshotRow, pull-snapshots/route.ts:185–215)
# =====================================================================================================================================

def dong_snapshot(raw) -> dict | None:
	"""→ các trường dữ liệu của `NPP MISA Snapshot` (chưa gồm `ban_ghi_tho` = raw, `keo_luc`, `name`); thiếu RefID (chuỗi, sau trim) → None.
	Số HĐ giữ NGUYÊN VĂN (chỗ giữ chỗ `<…` → None); `tong_tien` None → 0 + `co_tong_tien` 0 (Frappe ép NOT NULL — §1.2); `tien_truoc_thue` /
	`tien_thue` 0 khi MISA trả 0 / thiếu (nppsale ghi NULL — cổng trả NULLIF); `publish_status` / `einvoice_status` = `so_js` ∥ '' (Data —
	3,5 lưu '3.5', nppsale cột integer hỏng cả lô); `so_hddt_chuan` / `ky_hieu_chuan` = `chuan_so` / `ky_hieu_chat` (H21 — cùng hàm khớp, khác
	cột GENERATED của Postgres ở '000' và tab); [ĐX H26] ngày không có thật → `ngay_phat_hanh` None (thô còn trong `ban_ghi_tho`)."""
	r = raw if isinstance(raw, dict) else {}
	ref = js_trim(r["RefID"]) if isinstance(r.get("RefID"), str) else ""
	if not ref:
		return None
	bg = doc_ban_ghi(r)
	so_hd = bg["inv_no"] if bg["inv_no"] and not bg["inv_no"].startswith("<") else None
	ps, es, tong = bg["publish_status"], bg["einvoice_status"], bg["total_amount"]
	mst, ten = r.get("AccountObjectTaxCode"), r.get("AccountObjectName")
	return {
		"ref_id": ref,
		"ky_hieu": bg["inv_series"],
		"so_hddt": so_hd,
		"ngay_phat_hanh": ngay_that(ngay_iso(bg["inv_date"])) if bg["inv_date"] else None,
		"ma_tra_cuu": bg["transaction_id"],
		"ma_cqt": bg["invoice_code"],
		"mst_nguoi_mua": mst if isinstance(mst, str) else None,
		"nguoi_mua": ten if isinstance(ten, str) else None,
		"tong_tien": tong if tong is not None else 0,
		"co_tong_tien": 1 if tong is not None else 0,
		"tien_truoc_thue": _hoac(bg["total_without_vat"], 0),
		"tien_thue": _hoac(bg["total_vat"], 0),
		"publish_status": "" if ps is None else so_js(ps),
		"einvoice_status": "" if es is None else so_js(es),
		"quan_he": quan_he(es),
		"da_huy": 1 if bg["huy"] else 0,
		"ref_id_goc": bg["org_ref_id"],
		"so_hddt_chuan": None if so_hd is None else chuan_so(so_hd),
		"ky_hieu_chuan": ky_hieu_chat(bg["inv_series"]),
	}


# =====================================================================================================================================
# §2.9 Khớp bốn tầng (reconcile.ts:94–288) — chỉ quyết, KHÔNG ghi gì (module khớp chỉ ghi snapshot; không bao giờ ghi NPP HDDT)
# =====================================================================================================================================

def _chuoi_ngay(ngay) -> str:
	"""Ngày khớp tầng 4 dạng 'YYYY-MM-DD': chuỗi giữ nguyên; `date` của Frappe → isoformat; `datetime` → phần ngày (người gọi đổi
	`phat_hanh_luc` sang giờ VN trước — giờ site là giờ VN)."""
	if isinstance(ngay, _dt.datetime):
		ngay = ngay.date()
	return ngay.isoformat() if isinstance(ngay, _dt.date) else _chuoi_js(ngay)


def _khoa_tien(mst: str, ngay, tien) -> str:
	"""amtKey (reconcile.ts:112–113): `{MST}|{ngày}|{Math.round(|tiền|)}` — trị tuyệt đối vì HĐ điều chỉnh giảm mang tiền ÂM trên MISA."""
	return f"{mst}|{_chuoi_ngay(ngay)}|{so_js(_lam_tron_js(abs(_thuc(tien))))}"


def lap_chi_muc(so_: list) -> dict:
	"""buildIndex (reconcile.ts:115–152). Mỗi dòng sổ: {id, misa_ref_id, misa_lookup_code, misa_inv_series, misa_inv_no, mst, ngay
	(= misa_inv_date ∥ ngày VN của phat_hanh_luc ∥ ngày VN của misa_sent_at, 'YYYY-MM-DD' — `lich/misa.py::_ngay_khop_so`), tong_tien}. RefID / mã tra cứu / (ký hiệu chặt, số) — tờ ĐẦU TIÊN giữ khoá
	(hai tờ cùng khoá là dữ liệu hỏng, ghi đè im lặng là giấu nó); khoá lỏng / MST + ngày + tiền giữ DANH SÁCH. Tờ chỉ có số gõ tay không vào
	chỉ mục số."""
	cm = {"by_ref": {}, "by_txn": {}, "by_no": {}, "by_loose": {}, "by_base": {}, "by_full": {}}
	for r in so_:
		i = r.get("id")
		ref = r.get("misa_ref_id")
		if js_dung(ref):
			cm["by_ref"].setdefault(_norm(ref), i)
		txn = r.get("misa_lookup_code")
		if js_dung(txn):
			cm["by_txn"].setdefault(_norm(txn), i)
		kh, sh = r.get("misa_inv_series"), r.get("misa_inv_no")
		if js_dung(kh) and js_dung(sh):
			cm["by_no"].setdefault(f"{ky_hieu_chat(kh)}|{chuan_so(sh)}", i)
			cm["by_loose"].setdefault(f"{ky_hieu_long(kh)}|{chuan_so(sh)}", []).append(i)
		ngay, tien = r.get("ngay"), _so_so(r.get("tong_tien"))
		if js_dung(ngay) and tien is not None:
			du = mst_du(r.get("mst"))
			if du:
				cm["by_full"].setdefault(_khoa_tien(du, ngay, tien), []).append(i)
			goc = mst_goc(r.get("mst"))
			if goc:
				cm["by_base"].setdefault(_khoa_tien(goc, ngay, tien), []).append(i)
	return cm


def _tien_snapshot(snap: dict):
	"""`total_amount` của snapshot: `tong_tien` khi MISA có trả tổng (`co_tong_tien`), ngược lại None (§5.4 — Frappe ép Currency NOT NULL 0,
	nên 0 của dòng `co_tong_tien = 0` là "không có số", không phải 0 đ). Dict không có khoá `co_tong_tien` → đọc thẳng `tong_tien`."""
	if "co_tong_tien" in snap and not js_dung(snap.get("co_tong_tien")):
		return None
	return _so_so(snap.get("tong_tien"))


def khop_mot(snap: dict, cm: dict):
	"""matchOne (reconcile.ts:160–233) → (id, cach_khop, do_tin, ghi_chu) | None, dừng ở tầng đầu trúng. `snap` = trường NPP MISA Snapshot:
	ref_id, ma_tra_cuu, ky_hieu, so_hddt, ngay_phat_hanh, mst_nguoi_mua, tong_tien (+ co_tong_tien: 0 ⇒ coi như MISA không trả tổng).
	1 RefID → 2 mã tra cứu → 3 (ký hiệu chặt, số) — chắc chắn; 3b ký hiệu bỏ chữ số đầu, đúng MỘT ứng viên — cần review; 4 MST + ngày + tiền:
	MST đủ đúng một → review, NHIỀU → dừng (None); rồi MST gốc đúng một → review."""
	ref = snap.get("ref_id")
	if js_dung(ref):
		h = cm["by_ref"].get(_norm(ref))
		if js_dung(h):
			return h, "ref_id", "certain", None
	txn = snap.get("ma_tra_cuu")
	if js_dung(txn):
		h = cm["by_txn"].get(_norm(txn))
		if js_dung(h):
			return h, "transaction_id", "certain", None
	kh, sh = snap.get("ky_hieu"), snap.get("so_hddt")
	if js_dung(kh) and js_dung(sh):
		h = cm["by_no"].get(f"{ky_hieu_chat(kh)}|{chuan_so(sh)}")
		if js_dung(h):
			return h, "inv_no", "certain", None
		lo = cm["by_loose"].get(f"{ky_hieu_long(kh)}|{chuan_so(sh)}")
		if lo and len(lo) == 1:
			return (lo[0], "inv_no_loose", "review",
				f"Khớp sau khi bỏ chữ số đầu của ký hiệu (MISA: {_chuoi_js(kh)}). Xác nhận đúng mẫu số trước khi chốt.")
	ngay = ngay_khop(snap.get("ngay_phat_hanh"))
	tien = _tien_snapshot(snap)
	if ngay and tien is not None:
		du = mst_du(snap.get("mst_nguoi_mua"))
		if du:
			ung = cm["by_full"].get(_khoa_tien(du, ngay, tien))
			if ung and len(ung) == 1:
				return ung[0], "tax_date_amount", "review", f"Suy đoán từ MST {du} + ngày {ngay} + tiền. Duy nhất một hoá đơn trùng."
			if ung and len(ung) > 1:
				return None  # nhiều tờ trùng ở vòng trong thì DỪNG — nới sang MST gốc chỉ làm rổ to thêm
		goc = mst_goc(snap.get("mst_nguoi_mua"))
		if goc:
			ung = cm["by_base"].get(_khoa_tien(goc, ngay, tien))
			if ung and len(ung) == 1:
				return (ung[0], "tax_date_amount", "review",
					f"Suy đoán từ MST gốc {goc} (đã bỏ đuôi chi nhánh) + ngày {ngay} + tiền. "
					"Duy nhất một hoá đơn trùng — kiểm lại đúng chi nhánh trước khi chốt.")
	return None


def canh_bao_noi_tay(misa_inv_no, misa_inv_series, so_hddt, ky_hieu) -> tuple:
	"""Nối tay snapshot vào một tờ sổ (reconcile-action/route.ts:163–184, `link`) → (canh_bao, ket_qua_khop, ghi_chu_khop). Sổ đã ghi
	số / ký hiệu KHÁC MISA (so qua `cung_so` / `cung_ky_hieu`) → cảnh báo, không chặn (bản thay thế mang số mới là chuyện đúng) nhưng phải NÓI
	RA: có cảnh báo → needs_review + "Người nối tay. {cảnh báo nối dấu cách}", không → matched + "Người nối tay."."""
	canh_bao = []
	if js_dung(misa_inv_no) and js_dung(so_hddt) and not cung_so(misa_inv_no, so_hddt):
		canh_bao.append(f"Sổ đang ghi số {so_js(misa_inv_no)}, MISA là {so_js(so_hddt)}.")
	if js_dung(misa_inv_series) and js_dung(ky_hieu) and not cung_ky_hieu(misa_inv_series, ky_hieu):
		canh_bao.append(f"Sổ đang ghi ký hiệu {so_js(misa_inv_series)}, MISA là {so_js(ky_hieu)}.")
	if canh_bao:
		return canh_bao, "needs_review", "Người nối tay. " + " ".join(canh_bao)
	return canh_bao, "matched", "Người nối tay."


def trung_so(ky_hieu_a, so_a, ky_hieu_b, so_b) -> bool:
	"""[ĐX §1.6 — dùng ở hàm ghi kéo về, §4.8 bước 4] Hai tờ "trùng số sau chuẩn hoá": cùng `chuan_so` (khác rỗng) VÀ (cùng `ky_hieu_chat`
	HOẶC một bên trống ký hiệu). Chỉ mục duy nhất (ký hiệu, số) so NGUYÊN VĂN nên không bắt '00000123' vs '123', hay ('', '123') vs
	('1C26TAA', '123') — có trùng thì vẫn ghi số MISA (nguồn sự thật) và thêm `ghi_chu_trung_so`, không đổi trạng thái."""
	if not cung_so(so_a, so_b):
		return False
	a, b = ky_hieu_chat(ky_hieu_a), ky_hieu_chat(ky_hieu_b)
	return a == b or not a or not b


def ghi_chu_trung_so(so_hddt, ten_khac) -> str:
	"""Câu ghi chú trùng số (§1.6, Phụ lục B [F])."""
	return f"Số HĐĐT {so_js(so_hddt)} trùng (sau chuẩn hoá) với hoá đơn {so_js(ten_khac)} — cần kiểm tra."


def quyet_ket_qua_khop(snap: dict, hit, so_theo_id: dict) -> tuple:
	"""decideStatus (reconcile.ts:249–288) → (ket_qua_khop, ghi_chu_khop). Vòng đời đọc từ CỜ THẬT, kết luận TRƯỚC khi hỏi "khớp được
	không": `da_huy` → cancelled; `quan_he` replaced → replaced; không hit → misa_only; hit cần review → needs_review (+ ghi chú tầng);
	điều chỉnh → matched (không so tiền); | |MISA| − |sổ| | > 1 đ → amount_diff (`tien_vn`); còn lại matched. `snap` như `khop_mot` (+ da_huy,
	quan_he); `hit` = kết quả `khop_mot`; `so_theo_id` = {id: dòng sổ có `tong_tien`}."""
	if js_dung(snap.get("da_huy")):
		return "cancelled", "MISA báo hoá đơn đã huỷ."
	if snap.get("quan_he") == "replaced":
		return "replaced", "Đã bị thay thế trên MISA — hết hiệu lực."
	if not hit:
		return "misa_only", "Không tìm được hoá đơn tương ứng trong sổ — hoá đơn phát hành ngoài app."
	if hit[2] == "review":
		return "needs_review", hit[3]
	if snap.get("quan_he") == "adjustment":
		return "matched", "Hoá đơn điều chỉnh mang số chênh — không so tiền với sổ."
	dong = so_theo_id.get(hit[0])
	tien_so = _so_so(dong.get("tong_tien")) if dong else None
	tien_misa = _tien_snapshot(snap)
	if tien_so is not None and tien_misa is not None:
		if abs(abs(tien_misa) - abs(tien_so)) > DUNG_SAI_TIEN:
			return "amount_diff", f"Lệch tiền — sổ {tien_vn(tien_so)}, MISA {tien_vn(tien_misa)}."
	return "matched", None
