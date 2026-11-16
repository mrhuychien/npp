"""Lớp gọi MISA meInvoice WebAPI v2 — chép `src/lib/misa/client.ts` của nppsale (commit ghim `58158b1`, `portal/nguon`): năm lời gọi (token
`/oauth`, đẩy `/v3sainvoice`, một HĐ `GET /v3sainvoice/?refID=`, danh sách `/v3sainvoice/paging`, mẫu `/v3common/template`), token nhớ RAM,
thử lại MỘT lần khi lỗi xác thực. Đặc tả `dac_ta_hddt.md` §3 (+ [Soát thiếu 2]: H25, H27, `get_password` None → '').

Chỉ GỬI / NHẬN byte; đọc phản hồi bằng `nppsale/luat/hddt.py` (`doc_phan_hoi_*`, `hieu_phan_hoi_day`, `la_loi_xac_thuc`, `js_json` … — một chỗ
khai luật, không chép lại ở đây). Không whitelist hàm nào: chỉ route `nppsale/api/misa.py` và việc nền `nppsale/lich/misa.py` gọi.

Quy ước (§3.1):
- `requests` thẳng — KHÔNG `frappe.integrations.utils.make_request` (`raise_for_status` làm mất thân lỗi mà `loi_misa` cần, `log_error` mọi
  ngoại lệ), KHÔNG `get_request_session` (Retry 5 lần khi 500), KHÔNG Integration Request (lưu cả thân gửi — lời lấy mẫu có mật khẩu).
  `_phien()` là điểm tiêm adapter giả khi thử (`nppsale/tests/test_misa_mang.py`, §8.0 tầng 2).
- Hẹn giờ rõ cho MỌI lời gọi (requests mặc định chờ mãi): token / một HĐ / mẫu (5, 15) giây, đẩy (5, 30), danh sách (5, 60). Route phát hành
  phải xong trong 120 s của gunicorn: đã quá `HAN_THU_LAI_S` kể từ lúc bắt đầu đẩy thì không thử lại; trong `day_hd` mọi lời gọi (kể cả lời
  hỏi trước khi thử lại của H27) bị cắt hẹn đọc cho vừa `HAN_DAY_S` [ĐX — đặc tả chỉ tính token + đẩy; thêm GET của H27 là quá 120 s].
- Lỗi truyền tải → `MisaLoi` câu tiếng Việt (nppsale: `fetch failed` tiếng Anh vào `misa_error`). Với lời ĐẨY phân hai loại: không nối được /
  sai địa chỉ / bắt tay TLS hỏng = CHƯA GỬI (`CAU_CHUA_GUI`); hết giờ đọc / đứt giữa chừng = CHƯA BIẾT MISA nhận chưa (`CAU_CHUA_BIET`,
  `chua_biet=True` — route giữ `pending`, Làm mới / vòng quét gỡ theo RefID).
- Bí mật (I6): tài khoản / mật khẩu / token / thân `/oauth` / thân lấy mẫu KHÔNG vào câu lỗi, nhật ký hay Error Log. Câu lỗi chỉ mang chữ MISA
  trả + tên lớp lỗi; phần "Raw" của câu `/oauth` đã che (H25 — `che_token`); MISA dội lại đúng giá trị bí mật đang dùng thì thay bằng `***`
  [ĐX]. Biến cục bộ giữ bí mật đặt tên có chữ `password` / `token` / `secret` / `key` — bộ che biến của `frappe.get_traceback(with_context=True)`
  (developer_mode; Error Log, Scheduled Job Log) chỉ nhận tên tiếng Anh (`frappe/utils/__init__.py:340–375`); `CauHinhMisa` có `__repr__`
  riêng (bộ in của traceback_with_variables in TỪNG thuộc tính của dataclass dùng repr tự sinh — bỏ qua `repr=False`).
"""
from __future__ import annotations

import contextvars
import dataclasses
import hashlib
import json
import re
import ssl
import time
from urllib.parse import quote, quote_plus, urlencode

import frappe
import requests
import urllib3

from nppsale.luat.hddt import (
	CAU_THIEU_DUONG_DAY,
	CAU_THIEU_DUONG_TOKEN,
	doc_phan_hoi_ds,
	doc_phan_hoi_lay_hd,
	doc_phan_hoi_mau,
	doc_phan_hoi_token,
	hieu_phan_hoi_day,
	js_json,
	js_trim,
	la_loi_xac_thuc,
	ma_url,
	so_js,
)

TEN_CAU_HINH = "NPP MISA Cau Hinh"

# Hẹn giờ (nối, đọc) giây — §3.1 [ĐX]. Đọc là chờ giữa hai lần nhận byte (requests), không phải tổng.
HET_GIO_TOKEN = (5, 15)
HET_GIO_MOT_HD = (5, 15)
HET_GIO_MAU = (5, 15)
HET_GIO_DAY = (5, 30)
HET_GIO_DS = (5, 60)
HAN_THU_LAI_S = 60  # đã quá 60 s kể từ lúc bắt đầu đẩy thì không thử lại token (§3.1)
HAN_DAY_S = 110  # trần cả chuỗi đẩy (thử lại + hỏi trước của H27) — gunicorn cắt ở 120 s
HET_GIO_DOC_TOI_THIEU = 1

TOKEN_SONG_S = 30 * 60  # TOKEN_TTL_MS (client.ts:21)
TOKEN_BOT_S = 60  # hết hạn sớm 60 s (client.ts:369)
DO_DAI_CHE = 4  # bí mật ngắn hơn thì không che chuỗi dội lại (che "ab" là băm nát câu lỗi)

CAU_CHUA_GUI = "Không kết nối được tới MISA ({ten}) — hoá đơn chưa được gửi."
CAU_CHUA_BIET = (
	"Không nhận được trả lời của MISA (hết giờ / rớt mạng) — chưa biết MISA đã nhận hoá đơn chưa. "
	"ĐỪNG đẩy lại: bấm 'Làm mới trạng thái từ MISA' sau ít phút."
)
# Lời không phải đẩy (token, một HĐ, danh sách, mẫu): "chưa gửi / chưa biết" vô nghĩa — câu trung tính [ĐX].
CAU_KHONG_KET_NOI = "Không kết nối được tới MISA ({ten})."
CAU_KHONG_TRA_LOI = "Không nhận được trả lời của MISA ({ten}) — thử lại sau ít phút."
CAU_GIAI_MA = (
	"Không giải mã được tài khoản MISA — khoá mã hoá của site (encryption_key trong site_config.json) đã đổi so với lúc lưu cấu hình?"
)
LY_DO_GIAI_MA = "khoá mã hoá của site không mở được tài khoản / mật khẩu MISA đã lưu"


class MisaLoi(Exception):
	"""Lỗi gọi MISA — `str(e)` là câu tiếng Việt nguyên văn (đặc tả Phụ lục A) để route trả `{error: câu}` / ghi `misa_error`.
	`chua_biet` chỉ có nghĩa với lời ĐẨY: True khi thân có thể đã tới MISA (hết giờ đọc / đứt giữa chừng). `truyen_tai`: lỗi đường truyền (không
	nối được / hết giờ / đứt — MISA KHÔNG trả lời gì), khác lỗi MISA TRẢ LỜI (HTTP lỗi, `success: false`) — vòng quét xoay hàng đợi theo lỗi MISA trả
	lời và ngắt lượt khi lỗi đường truyền liên tiếp (lich/misa.py)."""

	def __init__(self, cau: str, *, chua_biet: bool = False, truyen_tai: bool = False):
		super().__init__(cau)
		self.chua_biet = chua_biet
		self.truyen_tai = truyen_tai


class LoiCauHinh(MisaLoi):
	"""[Sửa cuối — phát hiện 6 (+3)] Địa chỉ / đường dẫn MISA trong cấu hình không hợp lệ (ngoài máy chủ MISA cho phép, không https, đường dẫn lạ)
	— KHÔNG gọi mạng. `str(e)` = câu 400 tiếng Việt (route lưu cấu hình trả ngay; route khác / vòng quét gặp cấu hình sửa tay trên Desk cũng dừng
	trước khi giải mã / gửi tài khoản đi đâu)."""


class LoiGiaiMa(MisaLoi):
	"""Không giải mã được tài khoản / mật khẩu đã lưu (khoá site đổi — `frappe/utils/password.py:201–220`; khoá sai định dạng). `str(e)` =
	câu của Làm mới / Thử kết nối (§4.3 bước 5, §4.5 bước 3); `ly_do` để ghép câu riêng của phát hành ("Không giải mã được credentials MISA
	(kiểm tra encryption_key …): {ly_do}" — §4.1.1 bước 6) và của vòng quét / Dựng ("Giải mã cấu hình lỗi: {ly_do}")."""

	ly_do = LY_DO_GIAI_MA

	def __init__(self):
		super().__init__(CAU_GIAI_MA)


@dataclasses.dataclass(repr=False)
class CauHinhMisa:
	"""Cấu hình của MỘT lượt gọi (= `MisaConfig` của client.ts) — `lay_cau_hinh()` dựng từ Single `NPP MISA Cau Hinh`.

	`dia_chi_api` nối chuỗi NGUYÊN VĂN như TS (không bỏ "/" cuối); `mst` đi ở header `taxcode` / `TaxCode`; `duong_token` / `duong_day` đã chọn
	theo route (phát hành không lùi token về "/oauth"; đơn vị có mã đẩy "/v3sainvoice/Code"); `co_ma` chọn đoạn `code` của bốn đường còn lại.
	`tai_khoan` / `mat_khau` None = chưa nạp (`giai_ma`, lời gọi đầu tự nạp); nạp rồi thì luôn là chuỗi ('' khi chưa nhập — §3.1 [Soát thiếu 2]).
	`cau_hinh_payload` = trường cho `dung_payload(cau_hinh=…)`."""

	dia_chi_api: str
	mst: str = ""
	duong_token: str = "/oauth"
	duong_day: str = "/v3sainvoice"
	co_ma: bool = False
	tai_khoan: str | None = None
	mat_khau: str | None = None
	dang_dung: bool = True
	moi_truong_thu: bool = True
	cau_hinh_payload: dict = dataclasses.field(default_factory=dict)

	def __repr__(self):  # không bao giờ in tài khoản / mật khẩu (traceback có biến, log, print)
		def an(v):
			return repr(v) if v is None else ("'***'" if v else "''")

		return (f"CauHinhMisa(dia_chi_api={self.dia_chi_api!r}, mst={self.mst!r}, duong_token={self.duong_token!r}, "
			f"duong_day={self.duong_day!r}, co_ma={self.co_ma!r}, tai_khoan={an(self.tai_khoan)}, mat_khau={an(self.mat_khau)}, "
			f"dang_dung={self.dang_dung!r}, moi_truong_thu={self.moi_truong_thu!r})")

	def giai_ma(self, secret_tk: str | None = None, secret_mk: str | None = None) -> CauHinhMisa:
		"""Nạp tài khoản / mật khẩu từ hai trường Password của Single (mã bằng `encryption_key` của site — §1.7). Chữ khác rỗng (sau trim kiểu JS)
		truyền vào thì dùng nó và KHÔNG giải mã trường ấy (Thử kết nối: ô vừa gõ chưa lưu — `test-connection/route.ts:80–81`, `||` ngắn mạch:
		gõ cả hai thì thử được cả khi bản mã cũ hỏng). Chưa nhập → '' (nppsale `decryptSecret(null)` = '' — `src/lib/crypto.ts:44–45`; `None`
		lọt vào `urlencode` là gửi chữ "None"). Giải mã hỏng → `LoiGiaiMa` (câu tiếng Việt; bỏ câu tiếng Anh lõi đã đẩy vào message_log)."""
		self.tai_khoan = _doc_bi_mat("tai_khoan", secret_tk)
		self.mat_khau = _doc_bi_mat("mat_khau", secret_mk)
		return self


def _doc_bi_mat(truong: str, password_vao) -> str:
	"""⚠ Frappe v16: `get_decrypted_password(…, raise_exception=False)` NUỐT lỗi giải mã (`frappe/utils/password.py:36–43` — trả None như
	"chưa nhập") nhưng thông điệp tiếng Anh "Encryption key is invalid…" của `frappe.throw` đã vào message_log ⇒ khoá site đổi thành "Chưa nhập
	username/password" + chữ Anh về trình duyệt (`_server_messages`). Nên: hỏi `__Auth` có bản mã chưa (`co_bi_mat`, không giải mã) — không có →
	''; có → giải mã với `raise_exception=True` để thấy lỗi (đặc tả §1.7 (3)–(4) viết "luôn raise_exception=False" — lệch có lý do)."""
	if isinstance(password_vao, str) and js_trim(password_vao):
		return js_trim(password_vao)
	from frappe.utils.password import get_decrypted_password

	from nppsale.npp_hddt.doctype.npp_misa_cau_hinh.npp_misa_cau_hinh import co_bi_mat

	if not co_bi_mat(truong):
		return ""
	nhat_ky = getattr(frappe.local, "message_log", None)
	n = len(nhat_ky) if nhat_ky is not None else 0
	try:
		password = get_decrypted_password(TEN_CAU_HINH, TEN_CAU_HINH, truong, raise_exception=True)
	except (frappe.ValidationError, ValueError) as e:
		# decrypt(): InvalidToken → frappe.throw (ValidationError + msgprint tiếng Anh); khoá sai định dạng → ValueError của Fernet. Dọn thông
		# điệp tiếng Anh khỏi message_log (không về trình duyệt qua _server_messages).
		if nhat_ky is not None:
			del nhat_ky[n:]
		raise LoiGiaiMa() from e
	return password or ""


# ----------------------------------------------------------------------------------------------- [Sửa cuối — phát hiện 6 (+3)] địa chỉ MISA
# Máy chủ MISA được gọi tới — blueprint 02 §4.6 `dia_chi_api` ("default testapp…; thật: app…"), màn cấu hình nppsale
# (`settings/einvoice/page.tsx:252–254`: Sandbox / Production). nppsale nhận MỌI chuỗi `api_base`: chủ / KT KHÔNG biết mật khẩu MISA chỉ cần đổi địa
# chỉ rồi bấm "Thử kết nối" (hoặc chờ vòng quét 01:00) là máy chủ giải mã tài khoản + mật khẩu đã lưu và POST tới máy tuỳ ý — kèm SSRF vào mạng
# trong (câu lỗi mang 500 ký tự trả lời về trình duyệt). Thêm máy (MISA đổi miền) qua `site_config.json`: "npp_misa_may_chu": ["…"] — chỉ người
# quản trị máy chủ sửa được. Lệch nppsale có chủ ý [≠ H28 — Q8].
MAY_CHU_MISA = frozenset({"testapp.meinvoice.vn", "app.meinvoice.vn"})
# Khớp TRỌN chuỗi (không qua urlparse: bộ phân tích của Python và của urllib3 hiểu khác nhau `https://a\@b/` — urlparse ra máy b, urllib3 nối
# tới a): https, máy chữ / số / . / -, cổng 443 nếu ghi, đường dẫn chỉ ký tự an toàn ⇒ `{api}{đường}` nối chuỗi ra đúng một máy với mọi bộ phân tích.
_DIA_CHI_API = re.compile(r"https://([A-Za-z0-9.-]+)(?::443)?(/[A-Za-z0-9._~/-]*)?")
_DUONG = re.compile(r"/[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*/?")
CAU_SAI_DIA_CHI = ("Địa chỉ API MISA không hợp lệ: chỉ nhận https:// tới máy chủ MISA ({may}), ví dụ https://testapp.meinvoice.vn/api/v2 "
	"(thử) hoặc https://app.meinvoice.vn/api/v2 (thật).")
CAU_SAI_DUONG = "Endpoint MISA không hợp lệ ({truong}): phải là đường dẫn bắt đầu bằng \"/\", ví dụ /oauth hoặc /v3sainvoice."


def may_chu_cho_phep() -> frozenset:
	"""MAY_CHU_MISA + `npp_misa_may_chu` của site_config (danh sách hoặc một chuỗi) — chữ thường."""
	them = frappe.conf.get("npp_misa_may_chu") if getattr(frappe.local, "conf", None) is not None else None
	if isinstance(them, str):
		them = [them]
	return frozenset(MAY_CHU_MISA) | frozenset(js_trim(x).lower() for x in (them or ()) if isinstance(x, str) and js_trim(x))


def may_cua(dia_chi_api) -> str | None:
	"""Máy (chữ thường) của một địa chỉ API HỢP LỆ theo `_DIA_CHI_API`; không hợp lệ → None."""
	m = _DIA_CHI_API.fullmatch(dia_chi_api or "")
	return m.group(1).lower() if m else None


def kiem_dia_chi_api(dia_chi_api) -> str | None:
	"""→ câu lỗi | None. https + máy trong danh sách cho phép + đường dẫn an toàn (không `\\`, `@`, `?`, `#`, khoảng trắng, cổng khác 443)."""
	may = may_cua(dia_chi_api)
	cho_phep = may_chu_cho_phep()
	if may is None or may not in cho_phep:
		return CAU_SAI_DIA_CHI.format(may=", ".join(sorted(cho_phep)))
	return None


def kiem_duong(duong, truong: str) -> str | None:
	"""Đường token / phát hành: trống thì để luật cũ báo ("Chưa cấu hình 'Endpoint…'"); có chữ thì phải là đường dẫn `/…` (không `//`, `@`, `?`,
	`#`, `\\`, `:` — đường nối thẳng sau địa chỉ API: `https://app.meinvoice.vn` + `@may-khac/oauth` là gửi sang máy khác)."""
	d = js_trim(duong or "")
	if d and not _DUONG.fullmatch(d):
		return CAU_SAI_DUONG.format(truong=truong)
	return None


def kiem_cau_hinh(dia_chi_api, duong_token, duong_day) -> str | None:
	"""Một luật cho route lưu cấu hình (trước khi lưu) và `lay_cau_hinh` (mọi lời gọi MISA — bắt cả bản sửa tay trên Desk / dữ liệu chuyển sang)."""
	return (kiem_dia_chi_api(dia_chi_api) or kiem_duong(duong_token, "token_path") or kiem_duong(duong_day, "publish_path"))


def lay_cau_hinh(*, lui_duong_token: bool = True) -> CauHinhMisa | None:
	"""Đọc Single `NPP MISA Cau Hinh` → `CauHinhMisa` (chưa giải mã bí mật — gọi `.giai_ma()` ở bước của route). None = CHƯA LƯU (không có dòng
	`tabSingles` của `nha_cung_cap` — §1.2: `get_single` của Single chưa lưu vẫn trả mặc định nên không dùng để biết "chưa cấu hình").
	KHÔNG xét `dang_dung` (phát hành / vòng quét tự xét `ch.dang_dung`; Làm mới / Dựng / Thử kết nối thì không — [=]). Lỗi CSDL để nổi lên
	(route dịch "Không đọc được cấu hình MISA: …" / "Lỗi truy vấn cấu hình MISA").

	[Sửa cuối — phát hiện 6] Địa chỉ / đường dẫn không hợp lệ (`kiem_cau_hinh` — sửa tay trên Desk, dữ liệu chuyển sang) → `LoiCauHinh` (không
	giải mã, không gọi mạng).

	`lui_duong_token`: Làm mới / quét / kéo snapshot / Dựng / Thử kết nối `token_path || "/oauth"`; phát hành truyền False — `cfg.token_path`
	thẳng (`publish/route.ts:329`, [=]: trống ⇒ "Chưa cấu hình 'Endpoint lấy token' …"). `mst` = `mst_nguoi_ban` ∥ `NPP Cai Dat.ma_so_thue` ∥ ''
	(dự phòng MST là [BP]; nppsale chỉ `tax_code || ""`). `duong_day` = "/v3sainvoice/Code" khi có mã, ngược lại `duong_phat_hanh` ∥
	"/v3sainvoice" (`publish/route.ts:331–333`)."""
	from nppsale.npp_hddt.doctype.npp_misa_cau_hinh.npp_misa_cau_hinh import da_luu

	if not da_luu():
		return None
	d = frappe.get_single(TEN_CAU_HINH)
	loi = kiem_cau_hinh(d.dia_chi_api, d.duong_lay_token, d.duong_phat_hanh)  # [Sửa cuối — phát hiện 6] trước MỌI lời gọi / giải mã
	if loi:
		raise LoiCauHinh(loi)
	co_ma = bool(d.misa_is_invoice_with_code)
	duong_token = d.duong_lay_token or ("/oauth" if lui_duong_token else "")
	return CauHinhMisa(
		dia_chi_api=d.dia_chi_api or "",
		mst=d.mst_nguoi_ban or frappe.db.get_single_value("NPP Cai Dat", "ma_so_thue") or "",
		duong_token=duong_token,
		duong_day="/v3sainvoice/Code" if co_ma else (d.duong_phat_hanh or "/v3sainvoice"),
		co_ma=co_ma,
		dang_dung=bool(d.dang_dung),
		moi_truong_thu=bool(d.moi_truong_thu),
		cau_hinh_payload={k: d.get(k) for k in ("misa_company_id", "misa_org_unit_id", "misa_user_id", "loai_hd", "misa_inv_series",
			"misa_inv_template_no", "misa_template_id", "ke_thua_mau_cu")},
	)


def _nap_bi_mat(ch: CauHinhMisa) -> None:
	if ch.tai_khoan is None or ch.mat_khau is None:
		ch.giai_ma()


# =====================================================================================================================================
# Truyền tải
# =====================================================================================================================================

def _khong_xac_thuc(r):
	return r


def _phien() -> requests.Session:
	"""Mỗi lời gọi một phiên (đóng ngay — không giữ ổ cắm giữa các request của gunicorn). Bài thử gắn AdapterGia vào phiên này.

	Giữ `trust_env` (proxy / CA của môi trường máy chủ) nhưng đặt xác thực rỗng: phiên không có `auth` thì requests đọc `~/.netrc` — một dòng
	netrc cho máy MISA là Basic auth ĐÈ `Authorization: Bearer …` (prepare_auth chạy sau header) và thêm header thứ ba cho `/oauth`."""
	s = requests.Session()
	s.auth = _khong_xac_thuc
	return s


def _dong_ho() -> float:
	"""Đồng hồ đơn điệu (giây) cho hạn token và hạn thử lại — bài thử thay bằng đồng hồ giả."""
	return time.monotonic()


_HAN = contextvars.ContextVar("npp_misa_han_day", default=None)  # mốc `_dong_ho()` phải xong chuỗi đẩy (đặt trong day_hd)


def _tran_het_gio(het_gio: tuple) -> tuple:
	han = _HAN.get()
	if han is None:
		return het_gio
	con_lai = han - _dong_ho() - het_gio[0]
	return (het_gio[0], max(HET_GIO_DOC_TOI_THIEU, min(het_gio[1], con_lai)))


# Lỗi xảy ra TRƯỚC khi byte nào của yêu cầu rời máy: hết giờ nối, proxy, địa chỉ / header hỏng. (`SSLError` xét riêng — `_ssl_luc_bat_tay`.)
_LOI_CHUA_GUI = (requests.exceptions.ConnectTimeout, requests.exceptions.ProxyError,
	requests.exceptions.MissingSchema, requests.exceptions.InvalidSchema, requests.exceptions.InvalidURL, requests.exceptions.InvalidHeader,
	requests.exceptions.URLRequired)
# Khung của lỗi TLS lúc BẮT TAY (urllib3 2.x: connection._ssl_wrap_socket_and_match_hostname → ssl_.ssl_wrap_socket → SSLContext.wrap_socket →
# SSLSocket._create → do_handshake) — chưa byte nào của yêu cầu HTTP đi. Lỗi bản ghi lúc đọc trả lời đi qua getresponse → recv_into → read.
_KHUNG_BAT_TAY = frozenset({"do_handshake", "_ssl_wrap_socket_and_match_hostname", "_match_hostname", "match_hostname"})


def _loi_ssl_trong_cung(e: BaseException):
	"""ssl.SSLError (gồm SSLCertVerificationError / CertificateError) nằm trong chuỗi requests → urllib3 (args, reason, __cause__, __context__)."""
	da_xem, cho = set(), [e]
	while cho:
		x = cho.pop()
		if x is None or id(x) in da_xem or not isinstance(x, BaseException):
			continue
		da_xem.add(id(x))
		if isinstance(x, (ssl.SSLError, ssl.CertificateError)):
			return x
		cho += [a for a in x.args if isinstance(a, BaseException)]
		cho += [getattr(x, "reason", None), x.__cause__, x.__context__]
	return None


def _ssl_luc_bat_tay(e: requests.exceptions.SSLError) -> bool:
	"""[Sửa cuối — phát hiện 11] `requests.exceptions.SSLError` gom CẢ lỗi bắt tay (chứng chỉ sai, sai phiên bản — chưa gửi gì) LẪN lỗi bản ghi TLS
	lúc ĐỌC trả lời (RECORD_LAYER_FAILURE, MAC sai — thân yêu cầu ĐÃ tới máy chủ) [đo: máy chủ TLS giả nhận trọn thân rồi ghi bản ghi hỏng ⇒
	cùng lớp `requests.exceptions.SSLError`, cùng bọc MaxRetryError]. Phân theo KHUNG nơi ssl.SSLError được ném (bắt tay ⇒ `do_handshake` /
	`_ssl_wrap_socket_and_match_hostname`), không theo mã lý do (OpenSSL 3 báo RECORD_LAYER_FAILURE cho cả hai). Không tìm ra ⇒ coi như sau khi
	gửi (chưa biết — giữ `pending` là phía an toàn: H2 còn khoá, H5 gỡ sau 10 phút nếu MISA không có)."""
	import traceback

	x = _loi_ssl_trong_cung(e)
	if x is None or x.__traceback__ is None:
		return False
	return any(k.name in _KHUNG_BAT_TAY for k in traceback.extract_tb(x.__traceback__))


def _phan_loai(e: Exception) -> tuple[bool, str]:
	"""→ (chưa gửi?, tên lỗi để in). `ConnectionError` từ chối nối / không phân giải được tên = MaxRetryError(reason=NewConnectionError)
	(urllib3 2.x: NameResolutionError là lớp con) → chưa gửi, in tên lý do. `SSLError` → chưa gửi CHỈ khi hỏng lúc bắt tay (`_ssl_luc_bat_tay`).
	Còn lại (ReadTimeout, ChunkedEncodingError, ConnectionError của ProtocolError / RemoteDisconnected, lỗi TLS lúc đọc trả lời, lỗi urllib3 lọt
	qua requests …) = chưa biết — đẩy lại an toàn nhờ hỏi MISA trước (H3)."""
	if isinstance(e, _LOI_CHUA_GUI):
		return True, type(e).__name__
	if isinstance(e, requests.exceptions.SSLError):
		return _ssl_luc_bat_tay(e), type(e).__name__
	if isinstance(e, requests.exceptions.ConnectionError):
		ly_do = getattr(e.args[0] if e.args else None, "reason", None)
		if isinstance(ly_do, urllib3.exceptions.NewConnectionError):
			return True, type(ly_do).__name__
	return False, type(e).__name__


TRAN_THAN = 2 * 1024 * 1024  # [Sửa cuối — phát hiện 6] trần thân trả lời: đọc dần, quá thì dừng (không nuốt cả bộ nhớ tiến trình)
CAU_THAN_QUA_LON = "MISA trả về quá {kb} KB — dừng đọc ({ten})."


class _QuaLon(Exception):
	pass


def _doc_than_gioi_han(r) -> bytes:
	"""Đọc thân theo khúc tới `TRAN_THAN` (requests mặc định đọc trọn vào RAM, không trần) — quá trần → `_QuaLon` (`_gui` đổi thành MisaLoi)."""
	buf = bytearray()
	for khuc in r.iter_content(64 * 1024):
		buf += khuc
		if len(buf) > TRAN_THAN:
			raise _QuaLon()
	return bytes(buf)


def _gui(phuong_thuc: str, url: str, headers: dict, than_secret: bytes | None, het_gio: tuple, *, la_day: bool = False) -> tuple[int, str]:
	"""Một lời HTTP → (mã HTTP, thân chữ). Thân giải mã UTF-8 như `res.text()` của fetch (bỏ BOM đầu, byte hỏng → U+FFFD) — không dùng
	`r.text` (requests đoán bảng mã khi thiếu charset). Lỗi truyền tải → `MisaLoi` (`truyen_tai=True`; không mang URL / thân / header — chỉ tên lớp
	lỗi). [Sửa cuối — phát hiện 6] KHÔNG theo chuyển hướng (requests mặc định theo 307 / 308 là GỬI LẠI thân — form /oauth và thân lấy mẫu có mật
	khẩu — sang máy trong `Location`): 3xx trả về như mã lỗi HTTP; thân đọc dần, trần `TRAN_THAN`."""
	try:
		with _phien() as s:
			r = s.request(phuong_thuc, url, headers=headers, data=than_secret, timeout=_tran_het_gio(het_gio), allow_redirects=False,
				stream=True)
			try:
				return r.status_code, _doc_than_gioi_han(r).decode("utf-8-sig", "replace")
			finally:
				r.close()
	except _QuaLon as e:
		raise MisaLoi(CAU_THAN_QUA_LON.format(kb=TRAN_THAN // 1024, ten=phuong_thuc), chua_biet=la_day, truyen_tai=True) from e
	except (requests.RequestException, urllib3.exceptions.HTTPError) as e:
		chua_gui, ten = _phan_loai(e)
		if la_day:
			raise MisaLoi(CAU_CHUA_GUI.format(ten=ten) if chua_gui else CAU_CHUA_BIET, chua_biet=not chua_gui, truyen_tai=True) from e
		raise MisaLoi((CAU_KHONG_KET_NOI if chua_gui else CAU_KHONG_TRA_LOI).format(ten=ten), truyen_tai=True) from e


def _bien_the(s: str) -> set:
	"""[Sửa cuối — phát hiện 8] Mọi dạng một bí mật có thể quay về trong thân / câu lỗi MISA: nguyên văn, mã form (`urlencode` của /oauth —
	quote_plus: '@' → %40, ' ' → '+'), mã URL đủ (`quote(s, safe='')`), thoát JSON (`\\"`, `\\\\`, `\\uXXXX` khi ensure_ascii)."""
	ra = {s, quote_plus(s), quote(s, safe=""), json.dumps(s, ensure_ascii=False)[1:-1], json.dumps(s)[1:-1]}
	return {x for x in ra if len(x) >= DO_DAI_CHE}


def _che_bi_mat(v, ch: CauHinhMisa, *token_dung):
	"""[ĐX — I6] MISA dội lại đúng tài khoản / mật khẩu / token đang dùng trong câu lỗi hoặc thân trả về (vd "Tài khoản u-… không tồn tại",
	"Token eyJ… hết hạn") → thay bằng `***` trước khi tới `misa_error` / nhật ký. Chuỗi trong dict / list che đệ quy (không đổi kiểu, thứ tự).
	[Sửa cuối — phát hiện 8] che cả dạng đã mã hoá (`_bien_the` — form /oauth dội lại, JSON thoát `\\"`); dài trước ngắn sau. CHỈ dùng cho thứ
	sắp GHI ra (câu lỗi, nhật ký, bản ghi thô của snapshot) — không che dữ liệu dùng để kết luận (mật khẩu yếu "1234" là che mất số HĐ "00001234")."""
	cac_secret = sorted({b for x in (ch.tai_khoan, ch.mat_khau, *token_dung) if isinstance(x, str) and len(x) >= DO_DAI_CHE
		for b in _bien_the(x)}, key=len, reverse=True)
	if not cac_secret:
		return v

	def che(x):
		if isinstance(x, str):
			for s in cac_secret:
				x = x.replace(s, "***")
			return x
		if isinstance(x, list):
			return [che(y) for y in x]
		if isinstance(x, dict):
			return {k: che(y) for k, y in x.items()}
		return x

	return che(v)


def _la_so(v) -> bool:
	return isinstance(v, (int, float)) and not isinstance(v, bool)


_TOKEN_NHO: dict = {}  # khoá băm (`_khoa_token`) → (token, hết hạn theo _dong_ho) — RAM tiến trình (§3.3)


def _khoa_token(ch: CauHinhMisa, duong: str) -> str:
	"""[Sửa cuối — phát hiện 5 — ≠ H29] Khoá bản nhớ token = SHA-256 của (site, địa chỉ API, MST, tài khoản, MẬT KHẨU, đường token). nppsale / đặc tả
	§3.3 khoá theo `"{api}|{mst}|{tai_khoan}"`: một tiến trình gunicorn phục vụ MỌI site của bench (mỗi NPP một site) ⇒ chủ / KT site B nhập MST
	(công khai) + tài khoản MISA của NPP A + mật khẩu bất kỳ là dùng được token của A trong ~29 phút (đẩy nháp vào tài khoản A, đọc HĐ của A theo
	RefID); cùng site, mật khẩu sai vẫn chạy bằng token cũ. Băm (không giữ chuỗi mật khẩu làm khoá dict)."""
	site = getattr(frappe.local, "site", None) or ""
	cac_phan = (site, ch.dia_chi_api or "", ch.mst or "", ch.tai_khoan or "", ch.mat_khau or "", duong)
	return hashlib.sha256("\0".join(cac_phan).encode("utf-8")).hexdigest()


def token_dang_nho(ch: CauHinhMisa) -> str | None:
	"""Token còn hạn trong RAM của cấu hình `ch` (đã nạp bí mật) ∥ None — để che token khi ghi bản ghi MISA ra nhật ký (`che_ban_ghi`)."""
	if ch.tai_khoan is None or ch.mat_khau is None:
		return None
	nho = _TOKEN_NHO.get(_khoa_token(ch, js_trim(ch.duong_token or "")))
	return nho[0] if nho and nho[1] > _dong_ho() else None


def che_ban_ghi(v, ch: CauHinhMisa):
	"""[Sửa cuối — phát hiện 8] Bản ghi MISA (`lay_hd` / `ds_hd` — trả NGUYÊN cho luật kết luận) trước khi GHI ra NPP MISA Log.nhan_ve /
	NPP MISA Snapshot.ban_ghi_tho (QL đọc qua cổng): che tài khoản / mật khẩu / token đang dùng ở mọi dạng (I6). Không đổi gì khi không có bí mật."""
	return _che_bi_mat(v, ch, *(t for t in (token_dang_nho(ch),) if t))


def xoa_token_nho() -> None:
	"""Quên mọi token đã nhớ (bài thử; đổi tài khoản)."""
	_TOKEN_NHO.clear()


# =====================================================================================================================================
# Năm lời gọi (§3.2)
# =====================================================================================================================================

def lay_token(ch: CauHinhMisa, ep: bool = False, tra_tho: bool = False):
	"""getToken (client.ts:306–371): `POST {api}{duong_token.trim()}`, header ĐÚNG hai khoá `Content-Type: text/plain` + `taxcode` (chữ thường —
	tài liệu LAYTOKEN; gửi nhiều kiểu chữ là MISA từ chối), thân là CHUỖI form `grant_type=password&username=…&password=…` (`urlencode` để nguyên
	`~`, mã `*` — URLSearchParams ngược lại; cùng nghĩa sau giải mã — §3.2).

	Nhớ RAM theo `_khoa_token` (site + api + MST + tài khoản + mật khẩu + đường — [≠ H29]; nppsale `"{dia_chi_api}|{mst}|{tai_khoan}"`), sống
	`min(expires_in, 30 phút) − 60 s` (`expires_in` là số > 0, ngược lại 30 phút); `ep=True` bỏ qua bản nhớ; lỗi KHÔNG nhớ (lần sau gọi lại).
	Không đưa vào Redis / CSDL. Thiếu đường token → `MisaLoi` (không gọi mạng) — xét TRƯỚC bản nhớ như TS. Lỗi (HTTP lỗi, thân có `error`,
	không thấy token — phần Raw đã che H25) → `MisaLoi` câu của `doc_phan_hoi_token`.

	`tra_tho=True` (Thử kết nối) → `(token, thân /oauth đã parse)` từ CÙNG một lời gọi (luôn gọi mạng; nppsale gọi `/oauth` hai lần —
	client.ts:259–283 [≠ nhỏ]). Thân có token: route chỉ đọc định danh (`tach_dinh_danh`), không ghi nhật ký."""
	duong = js_trim(ch.duong_token or "")
	if not duong:
		raise MisaLoi(CAU_THIEU_DUONG_TOKEN)
	_nap_bi_mat(ch)
	cache_key = _khoa_token(ch, duong)  # tên có `key`: bộ che biến của traceback che (giá trị đã là chuỗi băm)
	bay_gio = _dong_ho()
	if not ep and not tra_tho:
		token_nho = _TOKEN_NHO.get(cache_key)
		if token_nho and token_nho[1] > bay_gio:
			return token_nho[0]
	password_form = urlencode({"grant_type": "password", "username": ch.tai_khoan, "password": ch.mat_khau}).encode("utf-8")
	st, token_text = _gui("POST", f"{ch.dia_chi_api}{duong}", {"Content-Type": "text/plain", "taxcode": ch.mst}, password_form,
		HET_GIO_TOKEN)
	token_kq = doc_phan_hoi_token(st, token_text)
	if token_kq["loi"]:
		raise MisaLoi(_che_bi_mat(token_kq["loi"], ch))
	token = token_kq["token"]
	song = token_kq["expires_in"]
	song = min(song, TOKEN_SONG_S) if _la_so(song) and song > 0 else TOKEN_SONG_S
	_TOKEN_NHO[cache_key] = (token, bay_gio + song - TOKEN_BOT_S)
	return (token, token_kq["tho"]) if tra_tho else token


def _post_hd(ch: CauHinhMisa, url: str, token: str, than: bytes) -> tuple[int, str]:
	# Header MST là `TaxCode` (PascalCase — tài liệu HDGTGT mục 2), MỘT lần; `cfg.taxCode || ""` (client.ts:466–477).
	return _gui("POST", url, {"Content-Type": "application/json", "Authorization": f"Bearer {token}", "TaxCode": ch.mst or ""}, than,
		HET_GIO_DAY, la_day=True)


def _hong(cau: str, chua_biet: bool = False) -> dict:
	return {"ok": False, "raw": None, "error": cau, "lookup_code": None, "inv_no": None, "ref_id": None, "chua_biet": chua_biet, "da_co": None}


# [Sửa cuối — phát hiện 12 — ≠ H30] 502 Bad Gateway / 504 Gateway Timeout = cổng / bộ cân tải TRƯỚC MISA không nhận được trả lời của máy sau —
# máy sau có thể ĐÃ ghi nháp. nppsale (và §4.1.1 bước 14) coi mọi 5xx là lỗi rõ → `error` ⇒ mở khoá Huỷ / Sửa HĐ (vế H2 không khoá error) cho một
# HĐ mà MISA có thể đang giữ nháp. Ở đây: CHƯA BIẾT như hết giờ đọc — giữ `pending`, không thử lại POST; Làm mới / vòng quét gỡ theo RefID (H5:
# MISA không có sau 10 phút → error). 500 / 503 giữ là lỗi rõ [=] (KV-20).
MA_CONG_HET_GIO = (502, 504)
CAU_CONG_CHUA_BIET = " — chưa biết MISA đã nhận hoá đơn chưa. ĐỪNG đẩy lại: bấm 'Làm mới trạng thái từ MISA' sau ít phút."


def _ket_qua(ch: CauHinhMisa, st: int, text: str, *token_dung) -> dict:
	kq = hieu_phan_hoi_day(st, text)
	if kq["error"]:
		kq["error"] = _che_bi_mat(kq["error"], ch, *token_dung)
	kq["raw"] = _che_bi_mat(kq["raw"], ch, *token_dung)
	chua_biet = st in MA_CONG_HET_GIO
	if chua_biet:
		kq["error"] = (kq["error"] or f"MISA publish lỗi {st}") + CAU_CONG_CHUA_BIET
	return {**kq, "chua_biet": chua_biet, "da_co": None}


def day_hd(ch: CauHinhMisa, payload: list, truoc_khi_thu_lai=None, *, bat_dau: float | None = None) -> dict:
	"""publishInvoice (client.ts:451–565): `POST {api}{duong_day}`, header `Content-Type: application/json` + `Authorization: Bearer …` +
	`TaxCode`, thân = `JSON.stringify(payload)` (MẢNG `[header]`; `js_json`, gửi byte UTF-8 — chuỗi str của http.client là latin-1).

	Luôn TRẢ dict, không ném (trừ lỗi lập trình): {ok, raw, error, lookup_code, inv_no, ref_id} như `hieu_phan_hoi_day` (`error`, `raw` đã che bí
	mật dội lại) + `chua_biet` + `da_co`:
	- thiếu `duong_day` → lỗi `CAU_THIEU_DUONG_DAY`, không gọi mạng (TS trả, không ném);
	- token hỏng (ít gặp: route đã lấy token ở bước 8, đây lấy từ RAM) → lỗi = câu token, chưa gửi;
	- lỗi truyền tải: chưa gửi → `CAU_CHUA_GUI`; chưa biết → `CAU_CHUA_BIET` + `chua_biet=True` (route giữ `pending`);
	- MISA trả HTTP lỗi mà `la_loi_xac_thuc` (401 / 403, hoặc thân có token / expired / unauthorized — ĐÚNG CẢ 400 / 500) và chưa quá
	  `HAN_THU_LAI_S` kể từ `bat_dau` (mặc định: lúc vào hàm; route truyền mốc `_dong_ho()` đầu request) → thử lại MỘT lần: token mới (ép), rồi
	  [ĐX H27] `truoc_khi_thu_lai()` (route truyền `lambda: lay_hd(ch, ref)`) — có bản ghi (kể cả `{}`) ⇒ KHÔNG POST lần 2, trả kết quả lần 1 kèm
	  `da_co` = bản ghi (route xử lý như "đẩy lại thấy trên MISA" — §4.1.1 bước 10; kiểm `da_co` TRƯỚC `ok`); ném `MisaLoi` ⇒ coi như lần 1 lỗi
	  rõ (câu lần 1); None ⇒ POST lại nguyên thân, cùng RefID. `truoc_khi_thu_lai` None ⇒ gửi thẳng như nppsale [=]. Token ép hỏng → câu token
	  (nppsale: ném ra khỏi publishInvoice). Hết giờ ở POST lần 2 vẫn là "chưa biết"."""
	duong = js_trim(ch.duong_day or "")
	if not duong:
		return _hong(CAU_THIEU_DUONG_DAY)
	bat_dau = _dong_ho() if bat_dau is None else bat_dau
	moc = _HAN.set(bat_dau + HAN_DAY_S)
	try:
		return _day(ch, payload, truoc_khi_thu_lai, f"{ch.dia_chi_api}{duong}", bat_dau)
	finally:
		_HAN.reset(moc)


def _day(ch: CauHinhMisa, payload: list, truoc_khi_thu_lai, url: str, bat_dau: float) -> dict:
	than = js_json(payload).encode("utf-8")
	try:
		token_dau = lay_token(ch)
		st, text = _post_hd(ch, url, token_dau, than)
	except MisaLoi as e:
		return _hong(str(e), chua_biet=e.chua_biet)
	if 200 <= st <= 299 or st in MA_CONG_HET_GIO or not la_loi_xac_thuc(st, text) or _dong_ho() - bat_dau > HAN_THU_LAI_S:
		return _ket_qua(ch, st, text, token_dau)  # 502 / 504: chưa biết — KHÔNG thử lại (máy sau có thể đã ghi)
	try:
		token = lay_token(ch, ep=True)
	except MisaLoi as e:
		return _hong(str(e))
	if truoc_khi_thu_lai is not None:
		try:
			ban_ghi = truoc_khi_thu_lai()
		except MisaLoi:
			return _ket_qua(ch, st, text, token_dau, token)
		if ban_ghi is not None:
			return {**_ket_qua(ch, st, text, token_dau, token), "da_co": ban_ghi}
	try:
		st, text = _post_hd(ch, url, token, than)
	except MisaLoi as e:
		return _hong(str(e), chua_biet=e.chua_biet)
	return _ket_qua(ch, st, text, token_dau, token)


def lay_hd(ch: CauHinhMisa, ref_id: str):
	"""getInvoiceByRefId (client.ts:151–178): `GET {api}/v3sainvoice/{code/ nếu có mã}?refID={encodeURIComponent}`, header `Authorization`,
	`TaxCode`, `Content-Type: application/json`. → bản ghi (dict; `{}` khi MISA trả JSON không phải object mà JS coi là có) | None (không có
	dữ liệu). Lỗi HTTP / `success: false` / truyền tải → `MisaLoi`. KHÔNG thử lại kể cả 401 [=]."""
	token = lay_token(ch)
	url = f"{ch.dia_chi_api}/v3sainvoice/{'code/' if ch.co_ma else ''}?refID={ma_url(str(ref_id))}"
	st, text = _gui("GET", url, {"Authorization": f"Bearer {token}", "TaxCode": ch.mst, "Content-Type": "application/json"}, None,
		HET_GIO_MOT_HD)
	kq = doc_phan_hoi_lay_hd(st, text)
	if kq["loi"]:
		raise MisaLoi(_che_bi_mat(kq["loi"], ch, token))
	return kq["ban_ghi"]


def ds_hd(ch: CauHinhMisa, tu, den, start: int, length: int) -> dict:
	"""listInvoices (client.ts:202–253): `POST {api}/{code/ nếu có mã}v3sainvoice/paging`, header `Content-Type:
	application/x-www-form-urlencoded` + `Authorization` + `TaxCode`, form `start`, `length`, `fromDate={tu}T00:00:00.000Z`,
	`toDate={den}T23:59:59.000Z` — ngày TRẦN, không nháy kép (§P.2: có nháy là 0 dòng không báo lỗi). `tu` / `den` = 'YYYY-MM-DD' (hoặc date).
	→ {dong, records_total}; trang méo → dòng [] không ném. Lỗi HTTP / `success: false` / truyền tải → `MisaLoi`."""
	token = lay_token(ch)
	form = urlencode([("start", so_js(start)), ("length", so_js(length)), ("fromDate", f"{tu}T00:00:00.000Z"),
		("toDate", f"{den}T23:59:59.000Z")]).encode("utf-8")
	st, text = _gui("POST", f"{ch.dia_chi_api}/{'code/' if ch.co_ma else ''}v3sainvoice/paging",
		{"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Bearer {token}", "TaxCode": ch.mst}, form, HET_GIO_DS)
	kq = doc_phan_hoi_ds(st, text)
	if kq["loi"]:
		raise MisaLoi(_che_bi_mat(kq["loi"], ch, token))
	return {"dong": kq["dong"], "records_total": kq["records_total"]}


def lay_mau(ch: CauHinhMisa, token: str | None = None, loai: int = 0) -> list:
	"""getInvoiceTemplates (client.ts:108–145): `POST {api}/v3common/{code/ nếu có mã}template`, header `Content-Type: application/json` +
	`Authorization` + `TaxCode`, thân JSON đúng bốn khoá `{TypeInvoice, TaxCode, UserName, Password}` — CHỨA MẬT KHẨU: không ghi ở đâu. `token`
	None → `lay_token(ch)` (RAM). → mảng mẫu (méo → []). Lỗi → `MisaLoi`."""
	_nap_bi_mat(ch)
	if token is None:
		token = lay_token(ch)
	password_body = js_json({"TypeInvoice": loai, "TaxCode": ch.mst, "UserName": ch.tai_khoan, "Password": ch.mat_khau}).encode("utf-8")
	st, text = _gui("POST", f"{ch.dia_chi_api}/v3common/{'code/' if ch.co_ma else ''}template",
		{"Content-Type": "application/json", "Authorization": f"Bearer {token}", "TaxCode": ch.mst}, password_body, HET_GIO_MAU)
	kq = doc_phan_hoi_mau(st, text)
	if kq["loi"]:
		raise MisaLoi(_che_bi_mat(kq["loi"], ch, token))
	return kq["mau"]
