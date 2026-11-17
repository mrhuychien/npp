"""Luật thuần của BÁO CÁO (P6) — dùng chung cho mọi RPC báo cáo (đặc tả bao_cao §1 L5, L11, §2.0).

- Mốc kỳ (L5): cột DATE (`posting_date` ↔ `invoice_date`, `ngay_tru_doanh_so` ↔ `revenue_date`, `ngay_thu`, `ngay_chi`, `transaction_date`) so thẳng
  chuỗi 'YYYY-MM-DD' lịch VN, cả hai đầu tính (BETWEEN). Cột datetime (Frappe lưu KHÔNG múi giờ, theo giờ VN của site) lọc theo [p_tu 00:00 VN,
  (p_den + 1) 00:00 VN) — như `'<p_tu>T00:00:00+07:00'` … `'<p_den>T23:59:59.999+07:00'` của `bao_cao_so_ban` (mig 228 §5 / §7). Mốc tính ở Python —
  KHÔNG `NOW()` / `CURDATE()` / `CONVERT_TZ` trong câu báo cáo (MariaDB `@@system_time_zone = UTC`, đặc tả §0.3).
- Hẹn giờ (L11): `bao_cao_*` 40 giây (giao diện chờ 45 s MỘT lượt — `fetchCoHetGio`, `HET_GIO_BAO_CAO_MS`), `dashboard_*` / `finance_*` 8 giây (thay
  `statement_timeout` 8 s của vai `authenticated` Supabase). Quá hạn → mã Postgres `57014` + câu Postgres (giao diện dịch `QUA_HAN_VI` — bắt mã hoặc câu
  `canceling statement due to statement timeout`, src/lib/errors.ts:39-68).
"""
from __future__ import annotations

import datetime as _dt

HET_GIO_BAO_CAO = 40  # giây — bao_cao_* (giao diện chờ 45 s một lượt, không gửi lại)
HET_GIO_NHANH = 8  # giây — dashboard_* / finance_* (statement_timeout của vai authenticated Supabase)
MA_QUA_HAN = "57014"
CAU_QUA_HAN = "canceling statement due to statement timeout"


def moc_ky(tu: _dt.date, den: _dt.date) -> tuple[_dt.datetime, _dt.datetime]:
	"""Kỳ [tu, den] (lịch VN) → (từ, tới) cho cột datetime giờ site: `cot >= từ AND cot < tới` = [tu 00:00, (den + 1) 00:00) — chứng từ ghi sổ
	00:00–06:59 VN thuộc đúng ngày VN của nó (không lệch 7 giờ như so với mốc UTC)."""
	return _dt.datetime.combine(tu, _dt.time.min), _dt.datetime.combine(den + _dt.timedelta(days=1), _dt.time.min)
