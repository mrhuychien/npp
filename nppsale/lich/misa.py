"""Việc nền HĐĐT MISA — thay `/api/einvoice/sync` (vòng quét trạng thái HAI lượt), `/api/einvoice/pull-snapshots` (kéo danh sách MISA về
`NPP MISA Snapshot` + khớp bốn tầng) và phần HĐĐT của `/api/cron/daily` (nppsale `vercel.json` "0 18 * * *" UTC = 01:00 giờ VN). Đặc tả
`dac_ta_hddt.md` §5 (+ [Soát thiếu 2]); blueprint 02 §4.6.0 / §4.6.9; skill einvoice-misa-sync Gotcha #3 (hai lượt, nhật ký lượt), #7, #10.

Lịch (§5.1): MỘT mục `hooks.py` cron "0 1 * * *" → `dong_bo`, chỉ XẾP HÀNG `chay_dong_bo` vào hàng `long` (hàng `default` cắt ở 300 s —
`scheduled_job_type.py:190–191`; 2 × 200 lời GET + tới 300 trang có thể lâu hơn). `chay_dong_bo` chạy TUẦN TỰ trong khoá tệp của site: đồng bộ
trạng thái TRƯỚC, kéo snapshot SAU, mỗi việc bọc try riêng — đồng bộ hỏng vẫn kéo (như `runJob` của `src/app/api/cron/daily/route.ts:43–95`). Hai mục
lịch riêng là hai Scheduled Job Type: thứ tự xếp hàng bị xáo (`frappe/utils/scheduler.py:133–150`) và chạy song song được ⇒ vòng khớp đọc sổ chưa
cập nhật số (BP §4.6.9). Production phải có worker nghe hàng `long` (`bench worker` không `--queue` nghe mọi hàng) và scheduler bật cho site
(`bench enable-scheduler`), không thì im lặng — Scheduled Job Log báo "Complete" ngay sau khi xếp hàng; bằng chứng DUY NHẤT việc đã chạy là MỘT
dòng `NPP MISA Log` `sync_run` + MỘT dòng `pull_snapshots` mỗi lượt (Gotcha #3 — nppsale chỉ trả báo cáo trong HTTP response). Khám sổ
`nppsale.kham_so.hddt` nhóm 4 báo khi dòng `sync_run` mới nhất cũ hơn 26 giờ.

Chạy tay (System Manager): `bench --site <site> execute nppsale.lich.misa.chay_dong_bo [--kwargs "{'days': 90}"]`. Không whitelist hàm nào ở đây
(nppsale chặn ba route bằng CRON_SECRET; Frappe chạy lịch trong tiến trình, không có cửa HTTP — §4.9).

Lệch có chủ ý so với nppsale (bài `test_lich_misa` khai): H14 (cửa sổ = GREATEST(phát hành nội bộ, lần gửi MISA gần nhất)), H15 (token MỘT lần
đầu lượt; hết hạn giữa lượt thì MỘT lời /oauth — hỏng ⇒ dừng lượt, không hỏi /oauth cho từng tờ), H5 (tờ treo quá 10 phút mà MISA không có ⇒
`error`; MISA có tờ treo / lỗi ⇒ xác nhận đẩy), lượt 2 quét cả `misa_status` trống, ngày cửa sổ snapshot + ngày khớp của sổ theo giờ VN, khử trùng
RefID trong một lượt kéo (`trung_ref_trong_luot`), `publish_status` / `einvoice_status` là chữ (số lẻ không làm hỏng cả lô), ghi một snapshot
hỏng thì không đếm, có nhật ký lượt.
"""
from __future__ import annotations

import datetime as _dt
import json
from contextlib import ExitStack
from uuid import uuid7
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_system_timezone

from nppsale.api import misa as M
from nppsale.api import misa_mang as MM
from nppsale.luat.hddt import dong_snapshot, khop_mot, lap_chi_muc, quyet_ket_qua_khop, so

TEN_VIEC = "npp_misa_dong_bo"  # job_id (khử trùng hàng đợi) + tên khoá tệp (sites/<site>/locks/npp_misa_dong_bo.lock)
TRAN_LUOT = 200  # PASS_LIMIT (sync/route.ts:54) — mỗi lượt tối đa 200 tờ
CUA_SO_NGAY = 60  # WINDOW_DAYS (sync/route.ts:56)
CO_TRANG = 100  # PAGE_SIZE (pull-snapshots/route.ts:40)
TRAN_TRANG = 300  # MAX_PAGES (:46) — 300 × 100 = 30.000 tờ / lượt; chạm trần thì BÁO (`hit_page_cap`), không im lặng kéo thiếu
NGAY_MAC_DINH = 60  # DEFAULT_DAYS (:47); cron của nppsale luôn 60 (pull-snapshots nhận chính req của cron/daily)
NGAY_TOI_DA = 400
LO_GHI = 500  # số dòng một câu INSERT … ON DUPLICATE KEY UPDATE
LO_COMMIT = 200  # khớp: commit theo lô (skill "Chốt chặn khi ghi" — 50–200 dòng)
_VN = ZoneInfo("Asia/Ho_Chi_Minh")

CAU_BO_QUA_CAU_HINH = "chưa cấu hình / đang tắt"
CAU_BO_QUA_KHOA = "bỏ qua — lượt khác đang chạy"
# câu lỗi nguyên văn nppsale (Phụ lục A, dòng sync / pull-snapshots) — giữ trong `errors[]` của nhật ký lượt
CAU_DOC_CAU_HINH = "Lỗi đọc cấu hình: {msg}"  # sync/route.ts:73, pull-snapshots/route.ts:68
CAU_LUOT_LOI = "Lượt {so} lỗi: {msg}"  # sync/route.ts:117, 141
CAU_MOC_LOI = "Không ghi được mốc đã hỏi: {msg}"  # sync/route.ts:165
CAU_NHAT_KY_LOI = "Không ghi được nhật ký hoá đơn: {msg}"  # sync/route.ts:215
CAU_KEO_LOI = "Kéo danh sách lỗi: {msg}"  # pull-snapshots/route.ts:129
CAU_GHI_SNAP_LOI = "Ghi snapshot lỗi: {msg}"  # :152
CAU_DOI_SOAT_LOI = "Đối soát lỗi: {msg}"  # :173
CAU_DOC_SO = "Đọc sổ hoá đơn: {msg}"  # reconcile-org.ts:59 (docDuHoacNem)
CAU_DOC_SNAP = "Đọc snapshot MISA: {msg}"  # reconcile-org.ts:94
CAU_GHI_KHOP_LOI = "Ghi kết quả khớp lỗi ({ref}): {msg}"  # [≠ nhỏ] nppsale chỉ console.error rồi VẪN đếm (reconcile-org.ts:116–126)
CAU_DANH_DAU_LOI = "Không đánh dấu được tờ gốc bị thay thế: {msg}"  # §4.7: nppsale chỉ console.error — vòng quét đẩy vào errors

# [Sửa cuối — phát hiện 17] Hạn của một lượt đêm (việc RQ trần 3600 s — `dong_bo`): MISA chậm (~15 s / lời GET) là 400 tờ × 15 s = 6.000 s ⇒ RQ cắt
# việc giữa chừng, KHÔNG dòng nhật ký lượt, KHÔNG kéo snapshot (§0.2-8 "một dòng nhật ký mỗi lượt chạy"). Đồng bộ dừng nhận tờ mới sau
# HAN_DONG_BO_S (phần còn lại → `bo_qua_vi_het_gio`, failed); kéo snapshot dừng nhận trang mới sau HAN_KEO_S tính từ đầu lượt (một lời gọi dở dang
# thêm tối đa 5 + 60 s — vẫn dưới 3600 s + 60 s RQ chờ trước khi giết hẳn). Lỗi ĐƯỜNG TRUYỀN liên tiếp NGAT_LOI_MANG tờ (MISA sập / mạng đứt —
# không phải MISA trả lỗi) ⇒ dừng lượt như H15 (phần còn lại → `bo_qua_vi_mang`) thay vì chờ hết giờ từng tờ.
HAN_DONG_BO_S = 40 * 60
HAN_KEO_S = 55 * 60
NGAT_LOI_MANG = 5
CAU_HET_HAN_KEO = "Kéo danh sách dừng vì quá hạn lượt đêm ({phut} phút) sau {trang} trang — bỏ khớp đêm nay."
CAU_RQ_CAT = "RQ cắt việc (quá trần thời gian của việc nền) — lượt dở dang: {msg}"

# §5.2 bước 3 — cửa sổ (H14): mốc muộn hơn của (phát hành nội bộ, lần gửi MISA gần nhất). `GREATEST` của MariaDB với NULL ra NULL nên phải
# IFNULL; mốc 0 kiểu DATETIME (không chuỗi) để phép so là so ngày giờ. nppsale chỉ `issued_at ≥ now − 60` ⇒ tờ treo chưa có `issued_at` / tờ
# "Khoá HĐ" cũ mới đẩy không bao giờ được quét; COALESCE thì tờ khoá cũ đẩy muộn cũng lọt.
_MOC = "GREATEST(IFNULL(`phat_hanh_luc`, TIMESTAMP('1900-01-01')), IFNULL(`misa_sent_at`, TIMESTAMP('1900-01-01')))"
_COT_LUOT = "`name`, `misa_ref_id`, `misa_inv_no`, `misa_status`, `don_hang`"
# Lượt 1 — có RefID, CHƯA có số (gồm tờ `pending` hết giờ và `error` có RefID): hỏi xem MISA cấp chưa.
LUOT_1 = f"""SELECT {_COT_LUOT} FROM `tabNPP HDDT`
	WHERE IFNULL(`misa_ref_id`, '') <> '' AND IFNULL(`misa_inv_no`, '') = '' AND {_MOC} >= %(tu)s
	ORDER BY `misa_last_checked_at` ASC, `name` ASC LIMIT %(tran)s"""
# Lượt 2 — ĐÃ có số nhưng chưa ở trạng thái cuối. Thiếu lượt này thì tờ bị huỷ / BỊ THAY THẾ trên MISA sau khi đã cấp số không bao giờ bị phát hiện
# (lượt 1 loại chúng ra) — sổ vẫn ghi một HĐ hợp lệ, rủi ro thuế thật (Gotcha #3). `misa_no_locked`: tờ người GÁN TAY số thì RefID trỏ tờ đã chết —
# quét là ghi số chết đè số người vừa gán. nppsale `NOT IN` loại luôn `misa_status` NULL — ở đây trống vẫn được quét [≠ nhỏ].
LUOT_2 = f"""SELECT {_COT_LUOT} FROM `tabNPP HDDT`
	WHERE IFNULL(`misa_ref_id`, '') <> '' AND IFNULL(`misa_inv_no`, '') <> '' AND IFNULL(`misa_status`, '') NOT IN ('cancelled', 'replaced')
		AND IFNULL(`misa_no_locked`, 0) = 0 AND {_MOC} >= %(tu)s
	ORDER BY `misa_last_checked_at` ASC, `name` ASC LIMIT %(tran)s"""
# Cột dữ liệu của một dòng snapshot (`dong_snapshot` + bản ghi thô + lúc kéo) — câu ghi lượt kéo CHỈ đụng các cột này (+ modified): KHÔNG `hddt`,
# `cach_khop`, `do_tin`, `ket_qua_khop`, `ghi_chu_khop`, `khop_luc`, `creation`, `name`, `owner` (chốt tay của người sống qua mọi lượt kéo).
COT_SNAPSHOT = ("ref_id", "ky_hieu", "so_hddt", "ngay_phat_hanh", "ma_tra_cuu", "ma_cqt", "mst_nguoi_mua", "nguoi_mua", "tong_tien", "co_tong_tien",
	"tien_truoc_thue", "tien_thue", "publish_status", "einvoice_status", "quan_he", "da_huy", "ref_id_goc", "so_hddt_chuan", "ky_hieu_chuan",
	"ban_ghi_tho", "keo_luc")

try:  # RQ cắt việc quá `timeout` bằng JobTimeoutException (lớp con của Exception) — nuốt nó trong vòng "lỗi một tờ" là việc chạy quá hạn
	from rq.timeouts import JobTimeoutException as _HetGioViec
except ImportError:  # pragma: no cover — rq luôn có trong bench
	_HetGioViec = ()


def _bay_gio():
	"""Giờ site — qua `nppsale.api.misa.bay_gio` (bài thử ghim một chỗ cho cả route lẫn lịch)."""
	return M.bay_gio()


def _commit() -> None:
	"""Commit giữa việc (sau mỗi tờ / mỗi lô) — bài thử chạy trong một giao dịch lui cuối bài nên bỏ qua (`commit_giua_chung`)."""
	M.commit_giua_chung()


def _cau(e: Exception) -> str:
	return str(e) or type(e).__name__


def _lui(diem: str) -> None:
	try:
		frappe.db.rollback(save_point=diem)
	except Exception:  # kết nối hỏng: không còn gì để lui (lỗi gốc đã vào errors)
		pass


def _ngay_vn(gio) -> _dt.date:
	"""Giờ site (không múi) → NGÀY theo giờ VN (giờ site của app là giờ VN; đổi múi cho chắc nếu site đặt khác)."""
	return gio.replace(tzinfo=ZoneInfo(get_system_timezone())).astimezone(_VN).date()


def _gio_site(ngay: _dt.date, gio: _dt.time) -> _dt.datetime:
	"""Mốc giờ VN (ngày + giờ) → giờ site không múi (để so với cột Datetime)."""
	return _dt.datetime.combine(ngay, gio, tzinfo=_VN).astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


def _nhat_ky_luot(nguon: str, ket_qua: str, bao: dict) -> None:
	"""MỘT dòng nhật ký lượt (`sync_run` / `pull_snapshots`, `hddt` trống — §5.4) + commit. `loi` = lý do bỏ qua ∥ ≤ 10 câu lỗi đầu (đọc nhanh ở
	danh sách Desk; đủ bộ ở `nhan_ve.errors`). Không có bí mật: câu lỗi của lớp mạng đã che (I6). Ghi hỏng: lui điểm lưu + Error Log."""
	cau = [(f"{e['invoice_id']}: " if e.get("invoice_id") else "") + e["message"] for e in bao.get("errors", ())]
	loi = bao.get("bo_qua") or ("\n".join(cau[:10]) + (f"\n… (+{len(cau) - 10} lỗi)" if len(cau) > 10 else "") if cau else None)
	M._ghi_nhat_ky_an_toan(nguon, ket_qua, nhan_ve=bao, loi=loi)
	_commit()


def _cau_hinh(bao: dict):
	"""Cấu hình cho một lượt (sync / kéo): None ⇒ đã ghi vào `bao` lý do dừng (`bo_qua` hoặc `errors`) — người gọi ghi nhật ký rồi thôi. Như nppsale
	chỉ chạy cấu hình `is_active` (sync/route.ts:66–71). Token: `token_path ∥ "/oauth"` (lay_cau_hinh mặc định)."""
	try:
		ch = MM.lay_cau_hinh()
	except Exception as e:
		bao["errors"].append({"message": CAU_DOC_CAU_HINH.format(msg=_cau(e))})
		return None
	if ch is None or not ch.dang_dung:
		bao["bo_qua"] = CAU_BO_QUA_CAU_HINH
		return None
	bao["orgs"] = 1
	try:
		ch.giai_ma()
	except MM.LoiGiaiMa as e:  # khoá site đổi — một lỗi, không gọi MISA
		bao["errors"].append({"message": M.CAU_DS_GIAI_MA.format(msg=e.ly_do)})
		return None
	return ch


# =====================================================================================================================================
# §5.1 Lịch
# =====================================================================================================================================

def dong_bo() -> None:
	"""Mục lịch cron "0 1 * * *" (hooks.py — 01:00 giờ site = giờ VN): CHỈ xếp hàng `chay_dong_bo` ở hàng `long` (trần 1 giờ), `job_id` +
	`deduplicate` — lượt trước còn trong hàng / đang chạy thì không xếp thêm."""
	frappe.enqueue("nppsale.lich.misa.chay_dong_bo", queue="long", timeout=3600, job_id=TEN_VIEC, deduplicate=True)


def chay_dong_bo(days=NGAY_MAC_DINH) -> dict:
	"""Một lượt đêm: khoá tệp của site (`frappe.utils.synchronization.filelock`, chờ 1 s — lượt chạy tay không chồng lượt lịch; khoá do tiến trình
	giữ, tiến trình chết là nhả) → `dong_bo_trang_thai()` → `keo_snapshot(days)`. Mỗi việc bọc try riêng (đồng bộ ném ⇒ một dòng `sync_run` failed,
	VẪN kéo snapshot). Khoá đang bị giữ ⇒ một dòng `sync_run` "bỏ qua — lượt khác đang chạy" (lõi ghi thêm một Error Log "Filelock: Failed to
	aquire …"). → {dong_bo, keo_snapshot} (bench execute in ra)."""
	from frappe.utils.file_lock import LockTimeoutError
	from frappe.utils.synchronization import filelock

	kq = {}
	with ExitStack() as khoa:
		try:
			khoa.enter_context(filelock(TEN_VIEC, timeout=1))
		except LockTimeoutError:
			bao = {"orgs": 0, "bo_qua": CAU_BO_QUA_KHOA, "errors": [], "bat_dau": _bay_gio(), "ket_thuc": _bay_gio()}
			_nhat_ky_luot("sync_run", "success", bao)
			return {"bo_qua": CAU_BO_QUA_KHOA}
		dau_luot = MM._dong_ho()
		try:
			kq["dong_bo"] = dong_bo_trang_thai(han=dau_luot + HAN_DONG_BO_S)
		except _HetGioViec as e:  # [phát hiện 17] vẫn để lại MỘT dòng nhật ký lượt rồi mới ném (RQ chờ 60 s trước khi giết hẳn)
			_ghi_rq_cat("sync_run", e)
			raise
		except Exception as e:  # lỗi không lường của cả lượt (vd đọc sổ hỏng giữa chừng) — vẫn kéo snapshot
			_lui_het()
			M._ghi_loi("HĐĐT MISA: vòng quét lỗi")
			bao = {"orgs": 0, "errors": [{"message": _cau(e)}], "bat_dau": None, "ket_thuc": _bay_gio()}
			_nhat_ky_luot("sync_run", "failed", bao)
			kq["dong_bo"] = bao
		try:
			kq["keo_snapshot"] = keo_snapshot(days, han=dau_luot + HAN_KEO_S)
		except _HetGioViec as e:
			_ghi_rq_cat("pull_snapshots", e)
			raise
		except Exception as e:
			_lui_het()
			M._ghi_loi("HĐĐT MISA: kéo snapshot lỗi")
			bao = {"orgs": 0, "errors": [{"message": _cau(e)}]}
			_nhat_ky_luot("pull_snapshots", "failed", bao)
			kq["keo_snapshot"] = bao
	return kq


def _lui_het() -> None:
	"""Bỏ phần CHƯA commit của việc vừa hỏng (mỗi tờ / mỗi lô đã commit riêng) TRƯỚC khi ghi Error Log + nhật ký lượt (lui sau là xoá luôn hai dòng
	ấy). Bài thử (một giao dịch, không commit) giữ nguyên để còn soi."""
	if not frappe.flags.in_test:
		frappe.db.rollback()


def _ghi_rq_cat(nguon: str, e: BaseException) -> None:
	"""[Sửa cuối — phát hiện 17] RQ cắt việc (JobTimeoutException) — lượt đêm vẫn để lại MỘT dòng nhật ký `failed` (bằng chứng duy nhất việc đã chạy
	— §5.1) trước khi ngoại lệ đi tiếp cho RQ. Hỏng ở đây (CSDL) thì thôi — không che lỗi gốc."""
	try:
		_lui_het()
		_nhat_ky_luot(nguon, "failed", {"orgs": 0, "errors": [{"message": CAU_RQ_CAT.format(msg=_cau(e))}], "ket_thuc": _bay_gio()})
	except Exception:  # đang bị RQ cắt: không để lỗi phụ đè lỗi gốc
		pass


# =====================================================================================================================================
# §5.2 Vòng quét trạng thái — hai lượt (sync/route.ts:58–232)
# =====================================================================================================================================

def dong_bo_trang_thai(han: float | None = None) -> dict:
	"""Hỏi MISA (`GET ?refID=`, KHÔNG BAO GIỜ bằng mã tra cứu / số) từng tờ của hai lượt, ghi bằng ĐÚNG hàm ghi của Làm mới
	(`nppsale.api.misa.ghi_ket_qua_keo_ve` — hai đường không được kết luận khác nhau về một tờ). → báo cáo lượt (cũng là `nhan_ve` của MỘT dòng
	nhật ký `sync_run`: {orgs, checked, updated, originals_marked_replaced, treo_thanh_loi, errors, luot_1, luot_2, bo_qua…, bat_dau, ket_thuc}).

	1. Cấu hình chưa lưu / tắt → `bo_qua`; đọc hỏng / giải mã hỏng → một lỗi; không gọi MISA.
	2. Hai câu lượt (giờ tính ở Python — múi giờ phiên CSDL có thể khác giờ site; `misa_last_checked_at` trống trước, rồi tăng dần, rồi `name`);
	   câu một lượt hỏng → `Lượt n lỗi: …`, lượt kia vẫn chạy (lượt ấy coi như bỏ dở ⇒ `failed`).
	3. [ĐX H15] Token lấy RIÊNG trước mỗi tờ, hỏng ⇒ DỪNG lượt (phần còn lại vào `bo_qua_vi_token`, `failed`): tờ đầu là MỘT lời /oauth cho cả lượt
	   (mật khẩu sai ⇒ một lỗi, không GET nào), các tờ sau lấy từ RAM (không gọi mạng), token hết hạn giữa lượt ⇒ MỘT lời. nppsale lấy token trong
	   từng lời hỏi, lỗi không nhớ ⇒ mật khẩu sai là /oauth cho TỪNG tờ — tới 400 lời / đêm, nguy cơ MISA khoá tài khoản. Không tờ nào để hỏi thì
	   không gọi MISA [=].
	4. Mỗi tờ (lượt 1 rồi lượt 2), không giữ khoá dòng / giao dịch trong lúc chờ HTTP:
	   - MISA không có (None): [ĐX H5] `pending` đã gửi quá 10 phút → `error` + câu "lượt đẩy trước chưa tới MISA…"; còn lại CHỈ ghi
	     `misa_last_checked_at` (không giảm — I10) — KHÔNG hạ trạng thái đang đúng (có thể chỉ là lỗi tạm); ghi hỏng → `Không ghi được mốc đã hỏi`.
	   - MISA có: `ghi_ket_qua_keo_ve` (xác nhận đẩy khi tờ `pending` / `error` — H5); ghi hỏng → errors (trùng số: câu 409 của Làm mới) và sang tờ
	     sau; OK → `updated`; tờ gốc được đánh dấu bị thay thế → `originals_marked_replaced`; có ghi chú → nhật ký `sync` (KHÔNG best-effort: chỉ tờ
	     có chuyện đáng nói mới có dòng — mất dòng là mất đúng ghi chú kế toán cần đọc ⇒ hỏng thì vào errors).
	   - MISA / mạng ném → lui điểm lưu, errors {invoice_id, message}, chạy tiếp (ném ở đây là 199 tờ còn lại không bao giờ được hỏi).
	     [Sửa cuối — phát hiện 10] MISA TRẢ LỜI lỗi cho tờ (HTTP lỗi / `success: false` — vd RefID MISA không có, nếu MISA báo "không có" theo kiểu
	     ấy — §9.4-2 chưa đo) ⇒ VẪN ghi mốc hỏi (không giảm): RefID nay ghi TRƯỚC khi gửi và GIỮ khi MISA từ chối, nên tờ bị từ chối nằm lượt 1 suốt
	     60 ngày — không xoay hàng đợi thì ≥ 200 tờ như vậy chiếm trọn lượt 1 mỗi đêm, tờ `sent` mới ký không bao giờ được kéo số. Lỗi ĐƯỜNG TRUYỀN
	     không ghi mốc (đêm sau hỏi lại trước) [= nppsale].
	   - commit sau MỖI tờ — một tờ hỏng không cuộn lại cả lượt; khoá dòng của hàm ghi nhả trước lời GET kế.
	5. [Sửa cuối — phát hiện 17] `han` (mốc `misa_mang._dong_ho()`; mặc định lúc vào + HAN_DONG_BO_S): quá hạn ⇒ dừng nhận tờ mới, phần còn lại
	   `bo_qua_vi_het_gio`, failed; NGAT_LOI_MANG tờ liên tiếp lỗi đường truyền ⇒ dừng như H15, phần còn lại `bo_qua_vi_mang`, failed.
	Không ghi `misa_signed_at` / `misa_published_at` / `misa_invoice_url` khi tờ chuyển `signed` [=] (chỉ phát hành ghi ba cột ấy)."""
	bao = {"orgs": 0, "checked": 0, "updated": 0, "originals_marked_replaced": 0, "treo_thanh_loi": 0, "errors": [], "luot_1": 0, "luot_2": 0,
		"bat_dau": _bay_gio()}
	han = MM._dong_ho() + HAN_DONG_BO_S if han is None else han
	ket_qua = "success"
	ch = _cau_hinh(bao)
	if ch is None:
		return _xong_dong_bo(bao, "success" if bao.get("bo_qua") else "failed")
	tu = _bay_gio() - _dt.timedelta(days=CUA_SO_NGAY)
	hang = []
	for so_luot, cau_sql in ((1, LUOT_1), (2, LUOT_2)):
		try:
			ds = frappe.db.sql(cau_sql, {"tu": tu, "tran": TRAN_LUOT}, as_dict=True)
		except Exception as e:
			bao["errors"].append({"message": CAU_LUOT_LOI.format(so=so_luot, msg=_cau(e))})
			ket_qua, ds = "failed", []
		bao[f"luot_{so_luot}"] = len(ds)
		hang += ds
	loi_mang_lien_tiep = 0
	for i, r in enumerate(hang):
		if MM._dong_ho() > han:  # [phát hiện 17] để lại thời gian cho kéo snapshot + dòng nhật ký lượt
			bao["bo_qua_vi_het_gio"] = len(hang) - i
			ket_qua = "failed"
			break
		try:
			MM.lay_token(ch)  # [ĐX H15] tờ đầu: MỘT lời /oauth cho cả lượt; sau đó RAM (hết hạn giữa lượt ⇒ một lời)
		except MM.MisaLoi as e:
			bao["errors"].append({"message": str(e)})
			bao["bo_qua_vi_token"] = len(hang) - i
			ket_qua = "failed"
			break
		bao["checked"] += 1
		loi_mang_lien_tiep = loi_mang_lien_tiep + 1 if _hoi_mot_to(ch, r, bao) else 0
		_commit()
		if loi_mang_lien_tiep >= NGAT_LOI_MANG and i + 1 < len(hang):  # [phát hiện 17] MISA không trả lời liên tiếp — thôi chờ từng tờ
			bao["bo_qua_vi_mang"] = len(hang) - i - 1
			ket_qua = "failed"
			break
	return _xong_dong_bo(bao, ket_qua)


def _xong_dong_bo(bao: dict, ket_qua: str) -> dict:
	bao["ket_thuc"] = _bay_gio()
	_nhat_ky_luot("sync_run", ket_qua, bao)
	return bao


def _hoi_mot_to(ch, r, bao: dict) -> bool:
	"""Một tờ của vòng quét (§5.2 bước 4) — mọi lỗi vào `bao["errors"]`, không ném (trừ RQ cắt việc). → True khi lời hỏi hỏng vì ĐƯỜNG TRUYỀN (MISA
	không trả lời — người gọi đếm để ngắt lượt)."""
	ref = (r.misa_ref_id or "").strip()  # như Làm mới (nppsale.api.misa._lam_moi) — cùng tờ thì cùng lời hỏi
	diem = "npp_lich_misa_to"
	frappe.db.savepoint(diem)
	try:
		# tờ treo / lỗi + bản ghi rỗng `{}` = MISA không có (phát hiện 9 — cùng luật Làm mới / phát hành)
		raw = M.ban_ghi_cua_to(MM.lay_hd(ch, ref), r.misa_status, ref)
	except _HetGioViec:
		raise
	except Exception as e:  # MISA / token / mạng — câu đã che bí mật (lớp mạng)
		_lui(diem)
		bao["errors"].append({"invoice_id": r.name, "message": _cau(e)})
		if isinstance(e, MM.MisaLoi) and e.truyen_tai:
			return True
		if isinstance(e, MM.MisaLoi):  # [phát hiện 10] MISA TRẢ LỜI lỗi: vẫn ghi mốc hỏi để hàng đợi xoay vòng
			try:
				_ghi_moc_hoi(r.name, _bay_gio())
			except _HetGioViec:
				raise
			except Exception as e2:
				_lui(diem)
				bao["errors"].append({"invoice_id": r.name, "message": CAU_MOC_LOI.format(msg=_cau(e2))})
		return False
	luc = _bay_gio()
	if raw is None:
		try:
			if M.xu_ly_misa_khong_co(r.name, luc):  # [ĐX H5]
				bao["treo_thanh_loi"] += 1
			else:
				_ghi_moc_hoi(r.name, luc)
		except _HetGioViec:
			raise
		except Exception as e:  # mốc "đã hỏi lúc nào" là thứ xếp lượt sau — ghi hỏng mà im thì tờ này bị hỏi lại mãi, tờ khác không tới lượt
			_lui(diem)
			bao["errors"].append({"invoice_id": r.name, "message": CAU_MOC_LOI.format(msg=_cau(e))})
		return False
	try:
		kq = M.ghi_ket_qua_keo_ve(r.name, raw, xac_nhan_day=(r.misa_status or "") in ("pending", "error"), luc=luc, co_ma=ch.co_ma)
	except _HetGioViec:
		raise
	except Exception as e:  # trùng số (LoiTrungSoHddt — câu 409 của Làm mới) hoặc lỗi ghi: dòng không đổi, sang tờ sau (nppsale `continue`)
		_lui(diem)
		bao["errors"].append({"invoice_id": r.name, "message": _cau(e)})
		return False
	bao["updated"] += 1
	if kq["goc"]:
		bao["originals_marked_replaced"] += 1
	if kq["loi_danh_dau"]:
		bao["errors"].append({"invoice_id": r.name, "message": CAU_DANH_DAU_LOI.format(msg=kq["loi_danh_dau"])})
	if kq["ghi_chu"]:  # chỉ tờ có chuyện đáng nói — không log tờ bình thường (einvoice_logs thành bãi rác thì không ai đọc)
		frappe.db.savepoint("npp_lich_misa_nk")
		try:
			M.ghi_nhat_ky("sync", "success", hddt=r.name, don_hang=r.don_hang, gui_di={"source": "sync", "ref_id": ref},
				nhan_ve=MM.che_ban_ghi(raw, ch), loi="\n".join(kq["ghi_chu"]), misa_inv_no=kq["so_that"])  # che bí mật dội lại (phát hiện 8)
		except _HetGioViec:
			raise
		except Exception as e:
			_lui("npp_lich_misa_nk")
			bao["errors"].append({"invoice_id": r.name, "message": CAU_NHAT_KY_LOI.format(msg=_cau(e))})
	return False


def _ghi_moc_hoi(ten: str, luc) -> None:
	"""MISA không trả gì cho tờ (không treo quá 10 phút): CHỈ ghi `misa_last_checked_at` — không giảm (I10: lượt chạy chậm hơn không lùi mốc)."""
	frappe.db.sql("""UPDATE `tabNPP HDDT` SET `misa_last_checked_at` = GREATEST(IFNULL(`misa_last_checked_at`, %(luc)s), %(luc)s)
		WHERE `name` = %(ten)s""", {"luc": luc, "ten": ten})


# =====================================================================================================================================
# §5.3 Kéo danh sách MISA về snapshot (pull-snapshots/route.ts:49–215)
# =====================================================================================================================================

def so_ngay(days) -> int:
	"""`Math.min(Math.max(Number(days) || 60, 1), 400)` (pull-snapshots/route.ts:54) rồi lấy phần nguyên: '0' / 'abc' / thiếu → 60; 1000 → 400;
	-5 → 1; '2.5' → 2."""
	n = so(days)  # Number() kiểu JS (chuỗi số, '0x..', khoảng trắng hai đầu)
	if not n:
		n = NGAY_MAC_DINH
	return int(min(max(n, 1), NGAY_TOI_DA))


def keo_snapshot(days=NGAY_MAC_DINH, han: float | None = None) -> dict:
	"""Kéo danh sách MISA (`ds_hd`, cửa sổ ngày VN) về `NPP MISA Snapshot` theo `ref_id`, rồi khớp bốn tầng (`khop_snapshot`). MỘT dòng nhật ký
	`pull_snapshots` {from, to, orgs, pulled, matched (gồm amount_diff), misa_only, needs_review, skipped_unlink, read_truncated, hit_page_cap,
	short_pull, trung_ref_trong_luot, errors}. Đi ngược `dong_bo_trang_thai` (từ MISA về sổ) — cách duy nhất thấy HĐ phát hành THẲNG trên web MISA
	(HĐ ngoài sổ — Gotcha #10).

	1. `den` = HÔM NAY giờ VN, `tu` = `den − days` [≠ nppsale lấy ngày UTC: chạy 01:00 VN ra `to` = hôm qua].
	2. Cấu hình chưa lưu / tắt → `bo_qua`; giải mã hỏng → một lỗi. Token: bản nhớ RAM của lượt đồng bộ vừa chạy (cùng tiến trình).
	3. Trang 0..299 × 100: DỪNG theo trang RỖNG hoặc < 100 dòng — không theo `recordsTotal` (có lúc trả 0 dù có dữ liệu — đo của nppsale: lấy nó
	   làm điều kiện dừng là kéo thiếu toàn bộ, im lặng); `recordsTotal` = số ĐẦU TIÊN gặp qua các trang; trang 299 vẫn đầy ⇒ `hit_page_cap`;
	   `recordsTotal` > số đã kéo ⇒ `short_pull`. Ném → `Kéo danh sách lỗi: …`, bỏ cả phần đã kéo + bỏ khớp (như nppsale `continue`).
	4–5. `dong_snapshot` (luật thuần — thiếu RefID bỏ; ngày không có thật ⇒ NULL — H26) → khử trùng theo `ref_id` (trang trượt — bản gặp SAU thắng)
	   → `INSERT … ON DUPLICATE KEY UPDATE` theo lô ≤ 500, trong MỘT điểm lưu (hỏng lô nào cũng lui hết — như một câu upsert của nppsale) →
	   `Ghi snapshot lỗi: …`, bỏ khớp.
	6. `khop_snapshot(tu, den)` — hỏng → `Đối soát lỗi: …`. Khớp chạy cả khi lượt này không kéo được dòng nào (nppsale).
	[Sửa cuối — phát hiện 17] `han` (mốc `misa_mang._dong_ho()`; mặc định lúc vào + HAN_KEO_S): quá hạn trước trang kế ⇒ dừng như lỗi kéo (bỏ phần
	đã kéo + bỏ khớp, failed) — không để RQ cắt việc giữa chừng mà không có dòng nhật ký."""
	n = so_ngay(days)
	han = MM._dong_ho() + HAN_KEO_S if han is None else han
	den = _ngay_vn(_bay_gio())
	tu = den - _dt.timedelta(days=n)
	bao = {"from": tu.isoformat(), "to": den.isoformat(), "orgs": 0, "pulled": 0, "matched": 0, "misa_only": 0, "needs_review": 0,
		"skipped_unlink": 0, "read_truncated": [], "hit_page_cap": False, "short_pull": [], "trung_ref_trong_luot": 0, "errors": []}
	ch = _cau_hinh(bao)
	if ch is None:
		return _xong_keo(bao, "success" if bao.get("bo_qua") else "failed")
	dong, tong = [], None
	try:
		for trang in range(TRAN_TRANG):
			if MM._dong_ho() > han:
				raise _QuaHanLuot(CAU_HET_HAN_KEO.format(phut=round(HAN_KEO_S / 60), trang=trang))
			kq = MM.ds_hd(ch, tu.isoformat(), den.isoformat(), trang * CO_TRANG, CO_TRANG)
			if tong is None:
				tong = kq["records_total"]
			if not kq["dong"]:
				break
			dong += kq["dong"]
			if len(kq["dong"]) < CO_TRANG:
				break
			if trang == TRAN_TRANG - 1:
				bao["hit_page_cap"] = True
	except _HetGioViec:
		raise
	except _QuaHanLuot as e:
		bao["errors"].append({"message": str(e)})
		return _xong_keo(bao, "failed")
	except Exception as e:
		bao["errors"].append({"message": CAU_KEO_LOI.format(msg=_cau(e))})
		return _xong_keo(bao, "failed")
	if tong is not None and tong > len(dong):  # kéo được ít hơn hẳn là báo đỏ, không phải chuyện bỏ qua
		bao["short_pull"].append({"expected": tong, "got": len(dong)})
	luc = _bay_gio()
	ds, trung = _khu_trung(dong, luc, ch)
	bao["trung_ref_trong_luot"] = trung
	if ds:
		frappe.db.savepoint("npp_lich_misa_snap")
		try:
			ghi_snapshot(ds, luc)
		except _HetGioViec:
			raise
		except Exception as e:
			_lui("npp_lich_misa_snap")
			bao["errors"].append({"message": CAU_GHI_SNAP_LOI.format(msg=_cau(e))})
			return _xong_keo(bao, "failed")
		bao["pulled"] = len(ds)
		_commit()
	try:
		tk = khop_snapshot(tu, den)
	except _HetGioViec:
		raise
	except Exception as e:
		bao["errors"].append({"message": CAU_DOI_SOAT_LOI.format(msg=_cau(e))})
		return _xong_keo(bao, "failed")
	for k in ("matched", "misa_only", "needs_review", "skipped_unlink"):
		bao[k] = tk[k]
	bao["errors"] += tk["errors"]
	if tk["book_truncated"] or tk["snap_truncated"]:  # Frappe đọc HẾT sổ / snapshot (nppsale trần 20.000 / 30.000) — khoá giữ cho đủ bộ
		bao["read_truncated"].append({"book": tk["book_truncated"], "snapshots": tk["snap_truncated"]})
	return _xong_keo(bao, "success")


class _QuaHanLuot(Exception):
	"""Kéo danh sách quá hạn lượt đêm (phát hiện 17) — `str(e)` vào `errors` nguyên văn."""


def _xong_keo(bao: dict, ket_qua: str) -> dict:
	_nhat_ky_luot("pull_snapshots", ket_qua, bao)
	return bao


def _khu_trung(dong: list, luc, ch=None) -> tuple[list[dict], int]:
	"""Bản ghi MISA → dòng snapshot (bỏ dòng thiếu RefID), khử trùng theo `ref_id` [Soát thiếu 2]: danh sách MISA phân trang theo offset — MISA phát
	hành thêm tờ trong lúc kéo là trang trượt, một RefID về hai lần (nppsale upsert cả mảng trong MỘT câu ⇒ Postgres từ chối cả câu "ON CONFLICT DO
	UPDATE command cannot affect row a second time" ⇒ đêm đó không khớp). Bản gặp SAU thắng (như `ON DUPLICATE KEY UPDATE` gặp trùng trong một
	câu); khoá so như chỉ mục duy nhất của MariaDB (utf8mb4_unicode_ci — không phân biệt hoa thường) để `pulled` = số dòng thật trong sổ.
	→ (dòng, số RefID về hơn một lần)."""
	ra: dict = {}
	trung: set = set()
	for raw in dong:
		d = dong_snapshot(raw)
		if d is None:
			continue
		# bản thô ghi ra (QL đọc qua cổng `misa_invoice_snapshots.raw`): che bí mật dội lại (phát hiện 8); trường đã bóc từ bản NGUYÊN ở trên
		d["ban_ghi_tho"] = json.dumps(MM.che_ban_ghi(raw, ch) if ch is not None else raw, ensure_ascii=False)
		d["keo_luc"] = luc
		k = d["ref_id"].casefold()
		if k in ra:
			trung.add(k)
		ra[k] = d
	return list(ra.values()), len(trung)


def ghi_snapshot(ds: list[dict], luc) -> None:
	"""Ghi theo `ref_id` (unique): dòng mới tự sinh `name` (uuid7 — như `autoname: UUID` của lõi), `creation`, `owner` (Administrator ở việc nền);
	trùng thì CHỈ cập nhật cột dữ liệu (`COT_SNAPSHOT`) + `modified` — chốt tay của người (`hddt`, `cach_khop` …) sống qua mọi lượt kéo (I7).
	`so_hddt_chuan` / `ky_hieu_chuan` đã tính trong `dong_snapshot` (= `chuan_hoa_snapshot` của controller — câu gộp không qua validate)."""
	nguoi = frappe.session.user or "Administrator"
	cot = ("name", "creation", "modified", "modified_by", "owner", "docstatus", "idx", *COT_SNAPSHOT)
	cap_nhat = ", ".join(f"`{c}` = VALUES(`{c}`)" for c in (*COT_SNAPSHOT, "modified", "modified_by"))
	mot = "(" + ", ".join(["%s"] * len(cot)) + ")"
	for i in range(0, len(ds), LO_GHI):
		lo = ds[i:i + LO_GHI]
		gia_tri = []
		for d in lo:
			gia_tri += [str(uuid7()), luc, luc, nguoi, nguoi, 0, 0, *(d[c] for c in COT_SNAPSHOT)]
		frappe.db.sql(f"INSERT INTO `tabNPP MISA Snapshot` ({', '.join(f'`{c}`' for c in cot)}) VALUES {', '.join([mot] * len(lo))} "
			f"ON DUPLICATE KEY UPDATE {cap_nhat}", gia_tri)


# =====================================================================================================================================
# §5.4 Khớp bốn tầng (reconcile-org.ts:44–137) — CHỈ ghi snapshot, KHÔNG BAO GIỜ ghi NPP HDDT (Gotcha #10: cô lập phạm vi hỏng)
# =====================================================================================================================================

def _ngay_khop_so(r) -> str | None:
	"""Ngày khớp tầng 4 của một tờ sổ: `misa_inv_date` ∥ ngày VN của `phat_hanh_luc` [≠ nppsale: 10 ký tự đầu chuỗi UTC] ∥ ngày VN của `misa_sent_at`
	(tờ huỷ nội bộ rồi phát hành giữ `phat_hanh_luc` NULL — phát hiện 2) ∥ None (không vào tầng 4)."""
	if r.misa_inv_date:
		return r.misa_inv_date.isoformat()
	moc = r.phat_hanh_luc or r.misa_sent_at
	return _ngay_vn(moc).isoformat() if moc else None


def khop_snapshot(tu: _dt.date, den: _dt.date) -> dict:
	"""Khớp snapshot CHƯA chốt tay (`cach_khop` ≠ manual) có `ngay_phat_hanh` ∈ [tu, den] (snapshot ngày NULL không bao giờ được khớp [=]) với sổ
	`NPP HDDT` có GREATEST(`phat_hanh_luc`, `misa_sent_at`) ∈ [tu 00:00:00, den 23:59:59] giờ VN hoặc `misa_inv_date` ∈ [tu, den] (mọi trạng thái;
	[≠ H14 mở rộng — phát hiện 2] nppsale: `issued_at` trong cửa sổ, `issued_at` NULL không vào). Luật ở `nppsale/luat/hddt.py`
	(`lap_chi_muc` / `khop_mot` / `quyet_ket_qua_khop` — một chỗ khai, Gotcha #9).

	- Đọc HẾT sổ và snapshot (không trần 1.000 dòng của PostgREST — bản cũ của nppsale chỉ thấy 1.000 tờ và CẮT LIÊN KẾT đúng của mọi tờ khác) ⇒
	  `book_truncated` / `snap_truncated` luôn False. Ngày khớp của sổ = `misa_inv_date` ∥ NGÀY VN của `phat_hanh_luc` ∥ NGÀY VN của `misa_sent_at`
	  (`_ngay_khop_so`) [≠ nppsale: 10 ký tự đầu chuỗi `issued_at` PostgREST trả — thường UTC ⇒ tờ 00:00–07:00 VN lệch một ngày ở tầng 4].
	- KHÔNG HẠ CẤP KHI THIẾU CĂN CỨ: không khớp được mà snapshot đang trỏ tờ KHÔNG nằm trong phần sổ vừa đọc (tờ ghi sổ ngoài khung ngày) ⇒
	  `skipped_unlink`, không ghi gì. Còn lại ghi `hddt` = tờ khớp ∥ NULL (cắt liên kết cũ khi không khớp), cách / độ tin / kết quả / ghi chú,
	  `khop_luc`. Trước khi ghi đọc lại dòng CÓ KHOÁ: người nối tay giữa lúc đọc và lúc ghi thì máy không đè, không đếm.
	- Ghi một snapshot hỏng: lui điểm lưu của dòng, `Ghi kết quả khớp lỗi ({ref_id}): …`, KHÔNG đếm [≠ nhỏ — nppsale console.error rồi vẫn đếm].
	  Đọc hỏng: ném `Đọc sổ hoá đơn: …` / `Đọc snapshot MISA: …` (người gọi ghi `Đối soát lỗi: …`) [=].
	→ {matched (gồm amount_diff), misa_only, needs_review, skipped_unlink, book_truncated, snap_truncated, errors}."""
	tk = {"matched": 0, "misa_only": 0, "needs_review": 0, "skipped_unlink": 0, "book_truncated": False, "snap_truncated": False, "errors": []}
	try:
		# [Sửa cuối — phát hiện 2 — mở rộng H14] phần sổ: mốc muộn hơn của (phát hành nội bộ, lần gửi MISA gần nhất) trong cửa sổ — CÙNG mốc với vòng
		# quét (`_MOC`) — HOẶC ngày HĐĐT MISA đã cấp trong cửa sổ. nppsale chỉ `issued_at` trong cửa sổ ⇒ tờ "Khoá HĐ" cũ mới đẩy (phat_hanh_luc T−90,
		# gửi MISA T−1 — KV-37 tờ Y) và tờ huỷ nội bộ rồi phát hành (phat_hanh_luc giữ NULL — KV-26 b) không vào sổ: snapshot RefID của chính chúng
		# thành "Chỉ có trên MISA — phát hành ngoài app" mỗi đêm (báo động giả HĐ ngoài sổ; "Dựng hoá đơn" thì 409 RefID) — vòng quét và vòng khớp
		# kết luận khác nhau về một tờ. Thêm tờ vào sổ chỉ THÊM căn cứ (tầng RefID / mã / số là chắc chắn).
		so_doc = frappe.db.sql(f"""SELECT `name`, `misa_ref_id`, `misa_lookup_code`, `misa_inv_series`, `misa_inv_no`, `misa_inv_date`,
				`mst_nguoi_mua`, `phat_hanh_luc`, `misa_sent_at`, `tong_tien`
			FROM `tabNPP HDDT` WHERE ({_MOC} >= %(tu)s AND {_MOC} <= %(den)s) OR (`misa_inv_date` >= %(tu_ngay)s AND `misa_inv_date` <= %(den_ngay)s)
			ORDER BY `name`""", {"tu": _gio_site(tu, _dt.time(0, 0, 0)), "den": _gio_site(den, _dt.time(23, 59, 59)), "tu_ngay": tu,
			"den_ngay": den}, as_dict=True)
	except Exception as e:
		raise RuntimeError(CAU_DOC_SO.format(msg=_cau(e))) from e
	so_ = [{"id": r.name, "misa_ref_id": r.misa_ref_id, "misa_lookup_code": r.misa_lookup_code, "misa_inv_series": r.misa_inv_series,
		"misa_inv_no": r.misa_inv_no, "mst": r.mst_nguoi_mua, "tong_tien": r.tong_tien, "ngay": _ngay_khop_so(r)} for r in so_doc]
	cm = lap_chi_muc(so_)
	theo_id = {d["id"]: d for d in so_}
	try:
		snaps = frappe.db.sql("""SELECT `name`, `ref_id`, `ma_tra_cuu`, `ky_hieu`, `so_hddt`, `ngay_phat_hanh`, `mst_nguoi_mua`, `tong_tien`,
				`co_tong_tien`, `quan_he`, `da_huy`, `hddt`
			FROM `tabNPP MISA Snapshot` WHERE `ngay_phat_hanh` >= %s AND `ngay_phat_hanh` <= %s AND IFNULL(`cach_khop`, '') <> 'manual'
			ORDER BY `name`""", (tu, den), as_dict=True)
	except Exception as e:
		raise RuntimeError(CAU_DOC_SNAP.format(msg=_cau(e))) from e
	luc = _bay_gio()
	da_ghi = 0
	for s in snaps:
		hit = khop_mot(s, cm)
		if not hit and s.hddt and s.hddt not in theo_id:  # ⚠ không hạ cấp khi thiếu căn cứ
			tk["skipped_unlink"] += 1
			continue
		ket_qua, ghi_chu = quyet_ket_qua_khop(s, hit, theo_id)
		frappe.db.savepoint("npp_lich_misa_khop")
		try:
			# đọc lại CÓ KHOÁ: người "Nối tay" (request khác) giữa lúc vòng khớp đọc danh sách và lúc ghi thì máy KHÔNG đè chốt tay — và không đếm
			lai = frappe.db.sql("SELECT IFNULL(`cach_khop`, '') FROM `tabNPP MISA Snapshot` WHERE `name` = %s FOR UPDATE", s.name)
			if not lai or lai[0][0] == "manual":
				continue
			frappe.db.sql("""UPDATE `tabNPP MISA Snapshot` SET `hddt` = %s, `cach_khop` = %s, `do_tin` = %s, `khop_luc` = %s, `ket_qua_khop` = %s,
				`ghi_chu_khop` = %s WHERE `name` = %s""",
				(hit[0] if hit else None, hit[1] if hit else None, hit[2] if hit else None, luc, ket_qua, ghi_chu, s.name))
		except _HetGioViec:
			raise
		except Exception as e:
			_lui("npp_lich_misa_khop")
			tk["errors"].append({"message": CAU_GHI_KHOP_LOI.format(ref=s.ref_id, msg=_cau(e))})
			continue
		if ket_qua == "misa_only":
			tk["misa_only"] += 1
		elif ket_qua == "needs_review":
			tk["needs_review"] += 1
		elif ket_qua in ("matched", "amount_diff"):
			tk["matched"] += 1
		da_ghi += 1
		if da_ghi % LO_COMMIT == 0:
			_commit()
	_commit()
	return tk
