"""Hai cửa công khai của cổng:

	POST|GET /api/method/nppsale.cong.api.truy_van   {"yeu_cau": {...}}   — .from(...) của createClient() ở portal
	POST|GET /api/method/nppsale.cong.api.rpc        {"ten": "...", "tham_so": {...}}  — .rpc(ten, tham_so, {get})

Trả 200 với {"data", "count"} hoặc {"error": {message, code, details, hint}, "status"} — lớp createClient() dựng lại đúng
{data, error, count, status} như supabase-js. Đọc chạy được bằng GET (Frappe không commit GET — thử lại an toàn); ghi chỉ POST.
"""
from __future__ import annotations

import json

import frappe

from . import bang as _bang
from .ghi import chuan_bi_kho as _chuan_bi_kho
from .ghi import ghi as _ghi
from .ghi import la_ghi_kho as _la_ghi_kho
from .loi import NppLoi
from .ngu_canh import hien_tai
from .sql import LoiCong
from .truy_van import ap_mot, doc


def _doc_json(x):
	if isinstance(x, str):
		return json.loads(x) if x else {}
	return x or {}


def _phuong_thuc() -> str:
	try:
		return (frappe.request.method or "POST").upper()
	except Exception:
		return "POST"


def _loi(e: Exception) -> dict:
	if isinstance(e, (LoiCong, NppLoi)):
		return {"error": e.to_dict(), "status": e.http}
	if isinstance(e, frappe.PermissionError):
		return {"error": {"message": "permission denied", "code": "42501", "details": str(e), "hint": None}, "status": 403}
	if isinstance(e, frappe.ValidationError):
		return {"error": {"message": str(e), "code": "P0001", "details": None, "hint": None}, "status": 400}
	raise e


@frappe.whitelist(methods=["GET", "POST"])
def truy_van(yeu_cau=None):
	if frappe.session.user == "Guest":
		return {"error": {"message": "JWT expired", "code": "PGRST301", "details": None, "hint": None}, "status": 401}
	_bang.nap()
	yc = _doc_json(yeu_cau)
	hd = yc.get("hanh_dong") or "select"
	if _la_ghi_kho(yc):
		return _ghi_kho(yc, hd)
	if hd != "select":
		return _ghi_thuong(yc, hd)
	try:
		ket = ap_mot(doc(yc, hien_tai()), yc.get("mot"))
		ket["status"] = 200
		return ket
	except Exception as e:  # noqa: BLE001 — dịch sang lỗi kiểu PostgREST, lỗi lạ thì ném tiếp
		return _loi(e)


def _ghi_thuong(yc: dict, hd: str) -> dict:
	"""Lời ghi thường của cổng: một lời ghi là một đơn vị — hỏng thì quay lui ĐÚNG phần của nó (savepoint), không cả giao dịch của request. Khoá chết /
	quá hạn chờ khoá / tờ đổi giữa lúc đọc và lúc lưu (`THU_LAI_LOI`) → lui HẲN rồi thử lại có giãn cách như `_goi_co_khoa`. Soát P4: khoá chết thì
	InnoDB lui CẢ giao dịch — điểm lưu không còn, `rollback(save_point=…)` hỏng 1305 ngay trong nhánh bắt lỗi → 500 "Lỗi máy chủ…" thay vì thử lại."""
	import time

	diem = "npp_cong_ghi"
	for lan in range(len(THU_LAI_KHOA) + 1):
		frappe.db.savepoint(diem)
		try:
			nc = hien_tai()
			if _phuong_thuc() != "POST":
				raise LoiCong("PGRST105", "ghi phải gửi bằng POST", http=405)
			ket = ap_mot(_ghi(yc, nc), yc.get("mot"))
			ket["status"] = 201 if hd in ("insert", "upsert") else 200
			return ket
		except THU_LAI_LOI as e:
			frappe.db.rollback()
			frappe.local._npp_ngu_canh = None
			if lan >= len(THU_LAI_KHOA):
				return _loi(LoiCong("40P01", f"Máy chủ đang bận ghi — thử lại sau ít giây ({type(e).__name__}).", http=503))
			time.sleep(THU_LAI_KHOA[lan])
		except Exception as e:  # noqa: BLE001 — dịch sang lỗi kiểu PostgREST, lỗi lạ thì ném tiếp
			frappe.db.rollback(save_point=diem)
			return _loi(e)


def _ghi_kho(yc: dict, hd: str) -> dict:
	"""Lời ghi cổng sinh chứng từ kho (bảng `batches`: sửa hạn / vùng → phiếu `CKL-`, xoá kiểm tồn — đặc tả kho_mua §2.1, BP §4.4.0): đọc dòng khớp
	bộ lọc + mặt hàng (`chuan_bi_kho`) → COMMIT → savepoint → bộ ghi khoá Bin làm câu ĐẦU (PoC 1d) → ghi; deadlock / quá hạn khoá → lui hẳn và thử
	lại có giãn cách (như `_goi_co_khoa` của RPC ghi kho). Lỗi ở bước đọc trả thẳng (chưa ghi gì, chưa có savepoint)."""
	import time

	diem = "npp_cong_ghi"
	for lan in range(len(THU_LAI_KHOA) + 1):
		try:
			nc = hien_tai()
			if _phuong_thuc() != "POST":
				raise LoiCong("PGRST105", "ghi phải gửi bằng POST", http=405)
			truoc = _chuan_bi_kho(yc, nc)
		except Exception as e:  # noqa: BLE001 — bước đọc: chưa có gì để lui
			return _loi(e)
		try:
			if not frappe.flags.in_test:  # bài kiểm chạy trong một giao dịch lui cuối bài — commit là ghi hẳn dữ liệu thử
				frappe.db.commit()
			frappe.db.savepoint(diem)
			ket = ap_mot(_ghi(yc, nc, truoc), yc.get("mot"))
			ket["status"] = 201 if hd in ("insert", "upsert") else 200
			return ket
		except THU_LAI_LOI as e:
			frappe.db.rollback()
			frappe.local._npp_ngu_canh = None
			if lan >= len(THU_LAI_KHOA):
				return _loi(LoiCong("40P01", f"Máy chủ đang bận ghi kho — thử lại sau ít giây ({type(e).__name__}).", http=503))
			time.sleep(THU_LAI_KHOA[lan])
		except Exception as e:  # noqa: BLE001 — như lời ghi thường: lui đúng phần của nó
			frappe.db.rollback(save_point=diem)
			return _loi(e)


def _gioi_han_khach(ten: str, toi_da: int) -> bool:
	"""Đếm lượt gọi của khách (chưa đăng nhập) theo IP trong một phút — True nếu còn được gọi."""
	ip = getattr(frappe.local, "request_ip", None) or "?"
	k = frappe.cache.make_key(f"npp_rl:{ten}:{ip}")
	n = frappe.cache.incr(k)
	if n == 1:
		frappe.cache.expire(k, 60)
	return n <= toi_da


@frappe.whitelist(methods=["GET", "POST"], allow_guest=True)
def rpc(ten=None, tham_so=None, sau=None):
	from nppsale import rpc as R

	R.nap()
	muc = R.DANG_KY.get(ten or "")
	khach = frappe.session.user == "Guest"
	if muc is None:
		if khach:
			return {"error": {"message": "JWT expired", "code": "PGRST301", "details": None, "hint": None}, "status": 401}
		return {"error": {"message": f"Could not find the function public.{ten} in the schema cache", "code": "PGRST202",
			"details": None, "hint": None}, "status": 404}
	if khach and not muc.cho_khach:
		return {"error": {"message": "JWT expired", "code": "PGRST301", "details": None, "hint": None}, "status": 401}
	if khach and not _gioi_han_khach(ten, muc.gioi_han_phut):
		return {"error": {"message": "Thử quá nhiều lần — đợi một phút rồi thử lại.", "code": "429", "details": None, "hint": None},
			"status": 429}
	if muc.ghi and _phuong_thuc() != "POST":
		return {"error": {"message": f"{ten} ghi sổ — phải gọi bằng POST", "code": "PGRST105", "details": None, "hint": None},
			"status": 405}
	diem = "npp_cong_rpc"
	ts = _doc_json(tham_so)
	if muc.chuan_bi is not None:
		return _goi_co_khoa(ten, muc, ts, sau, diem)
	import time

	for lan in range(len(THU_LAI_KHOA) + 1):
		frappe.db.savepoint(diem)
		try:
			frappe.local._npp_je_cho = None
			kq = muc.ham(**ts)
			_sau_rpc()
			sau_ = _doc_json(sau)
			if sau_:
				if not isinstance(kq, list):
					raise LoiCong("PGRST100", f"{ten} không trả tập dòng — không lọc / sắp / phân trang được kết quả")
				from .sau_ham import ap

				kq, dem = ap(kq, sau_)
				return {"data": kq, "count": dem, "status": 200}
			return {"data": kq, "status": 200}
		except (frappe.QueryDeadlockError, frappe.QueryTimeoutError) as e:
			# khoá chết: InnoDB lui CẢ giao dịch — điểm lưu không còn (lui về nó hỏng 1305 → 500); lui hẳn rồi thử lại như `_goi_co_khoa` (soát P4)
			frappe.db.rollback()
			frappe.local._npp_ngu_canh = None
			if lan >= len(THU_LAI_KHOA):
				return _loi(LoiCong("40P01", f"Máy chủ đang bận — thử lại sau ít giây ({type(e).__name__}).", http=503))
			time.sleep(THU_LAI_KHOA[lan])
		except Exception as e:  # noqa: BLE001 — RPC là một đơn vị: hỏng thì quay lui đúng phần của nó (như hàm Postgres)
			frappe.db.rollback(save_point=diem)
			return _loi(e)


THU_LAI_KHOA = (0.2, 0.5, 1.0)  # giây chờ trước lượt thử lại thứ 2, 3, 4
# lỗi lui HẲN + thử lại của lời ghi kho / RPC ghi kho / lời ghi thường của cổng: khoá chết, quá hạn chờ khoá, tờ đổi giữa lúc đọc (ảnh chụp) và lúc lưu
# (`check_if_latest` — đọc có khoá thấy bản mới hơn: thử lại là đọc lại từ đầu; soát P4)
THU_LAI_LOI = (frappe.QueryDeadlockError, frappe.QueryTimeoutError, frappe.TimestampMismatchError)


def _sau_rpc():
	"""Cuối mỗi lời gọi RPC (trong cùng điểm lui): lập lại các bút toán cấn trừ dư có đã huỷ vì tờ ghi có chúng trỏ bị huỷ / lập lại
	(nppsale.rpc.can_tru — đặc tả phiếu thu §2.5.2)."""
	if getattr(frappe.local, "_npp_je_cho", None):
		from nppsale.rpc.can_tru import sau_thao_tac_phieu_tra

		sau_thao_tac_phieu_tra()


def _goi_co_khoa(ten, muc, ts, sau, diem):
	"""RPC ghi kho: chuẩn bị → COMMIT → savepoint → hàm (câu đầu là khoá). Deadlock / quá hạn khoá → lui hẳn và thử lại."""
	import time

	for lan in range(len(THU_LAI_KHOA) + 1):
		try:
			muc.chuan_bi(**ts)
			if not frappe.flags.in_test:  # bài kiểm chạy trong một giao dịch lui cuối bài — commit là ghi hẳn dữ liệu thử
				frappe.db.commit()
			frappe.db.savepoint(diem)
			frappe.local._npp_je_cho = None
			kq = muc.ham(**ts)
			_sau_rpc()
			if _doc_json(sau):
				raise LoiCong("PGRST100", f"{ten} không trả tập dòng — không lọc / sắp / phân trang được kết quả")
			return {"data": kq, "status": 200}
		except THU_LAI_LOI as e:
			frappe.db.rollback()
			frappe.local._npp_ngu_canh = None
			if lan >= len(THU_LAI_KHOA):
				return _loi(LoiCong("40P01", f"Máy chủ đang bận ghi kho — thử lại sau ít giây ({type(e).__name__}).", http=503))
			time.sleep(THU_LAI_KHOA[lan])
		except Exception as e:  # noqa: BLE001 — như RPC thường: lui đúng phần của nó
			frappe.db.rollback(save_point=diem)
			return _loi(e)

