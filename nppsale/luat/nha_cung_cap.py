"""Luật thuần của NHÀ CUNG CẤP: đếm chứng từ, gộp, xoá (P4 — mốc M8; đặc tả kho_mua §3.13, §3.14, §5.3, §7.2 #22 / #23, §7.3 điểm 18 / 25, §9 S11 /
S12) — không import frappe; bài: nppsale.tests.test_luat_nha_cung_cap.

1. Câu lỗi NGUYÊN VĂN của hàm / trigger nppsale (thân ở scratchpad kho_mua/src/<tên>.sql): `so_chung_tu_ncc` (mig 232 — chỉ MÃ, không câu),
   `gop_nha_cung_cap` (mig 232), `xoa_nha_cung_cap` (mig 233), trigger `_ncc_chan_xoa` / `_ncc_xoa_qua_rpc` (mig 232 / 233 — cổng `suppliers` xoá
   thẳng). Cửa vai ba RPC ở `nppsale.luat.kho_mua.CUA_VAI` (một bảng cho mọi RPC P4).
2. Đếm chứng từ (`_ncc_dem_chung_tu`): mọi khoá ngoại KHÔNG CASCADE trỏ `suppliers` trong `public` theo `ORDER BY` tên bảng, tên cột — `payables`,
   `products(primary_supplier_id)`, `purchase_invoices`, `purchase_orders`, `stock_entries`, `supplier_payments`, `supplier_returns`; chỉ bảng có
   dòng (> 0) vào `chi_tiet`; nhãn tiếng Việt theo bảng, bảng khác giữ TÊN THÔ (`supplier_payments` — §7.3 điểm 25 giữ y nppsale). Liệt kê trong câu
   `NCC_CO_CHUNG_TU`: `'<số> <nhãn>'` nối `', '` theo đúng thứ tự ấy; xoá qua RPC bỏ `products` (mặt hàng xử lý riêng), xoá thẳng (trigger) liệt kê CẢ
   mặt hàng.
3. Gộp (`gop_nha_cung_cap` bước 0 + 3): ghi chú dòng nợ đầu kỳ của NCC bị gộp khi NCC giữ lại đã có nợ đầu kỳ (`concat_ws(' · ', NULLIF(btrim(notes),
   ''), 'Nợ đầu kỳ của NCC <tên> (gộp ngày dd/mm/yyyy)')`); hồ sơ NCC giữ lại: ô chữ trống (sau `btrim`) lấy của NCC bị gộp, ô còn chữ giữ bản
   ĐÃ `btrim`; ngày cấp ĐKKD / hạn mức `COALESCE`; ghi chú `concat_ws(E'\\n', ghi chú cũ đã trim, 'Gộp từ NCC <tên>[ (<mã>)] ngày dd/mm/yyyy.',
   'Ghi chú NCC cũ: <ghi chú NCC bị gộp đã trim>')`. `btrim` một tham số của Postgres chỉ bỏ DẤU CÁCH (đo PG16) — `nppsale.luat.cong_no_ncc.btrim`.
   Ngày = hôm nay giờ VN (`now() AT TIME ZONE 'Asia/Ho_Chi_Minh'`).
4. Xoá (`xoa_nha_cung_cap` bước 4): mỗi mặt hàng lấy NCC làm NCC chính — không xoá hàng (`p_xoa_hang` false) → gỡ NCC (`mat_hang_go`); có chứng từ →
   ngừng bán + gỡ (`mat_hang_ngung_ban`); không → xoá (`mat_hang_da_xoa`). `IF NOT p_xoa_hang …` của plpgsql: tham số NULL GỬI TƯỜNG MINH đi nhánh
   xoá hàng như `true` (NOT NULL → NULL → không vào nhánh gỡ); KHÔNG gửi → mặc định `false`.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from nppsale.cong.loi import NppLoi
from nppsale.luat.cong_no_ncc import btrim

# ------------------------------------------------------------------------------------------------ 1. câu lỗi
# so_chung_tu_ncc (mig 232): chỉ MÃ, không câu (P0001)
KHONG_DU_QUYEN_DEM = "KHONG_DU_QUYEN"
KHONG_TIM_THAY_DEM = "KHONG_TIM_THAY_NCC"
# gop_nha_cung_cap (mig 232)
GOP_NCC_TRUNG = "GOP_NCC_TRUNG: chọn hai nhà cung cấp khác nhau"
KHONG_TIM_THAY_TU = "KHONG_TIM_THAY_NCC: nhà cung cấp cần gộp không còn / không thuộc NPP"
KHONG_TIM_THAY_VAO = "KHONG_TIM_THAY_NCC: nhà cung cấp giữ lại không còn / không thuộc NPP"
# xoa_nha_cung_cap (mig 233)
KHONG_TIM_THAY_XOA = "KHONG_TIM_THAY_NCC: nhà cung cấp không còn / không thuộc NPP"
# trigger `_ncc_xoa_qua_rpc` (mig 233) — cổng xoá thẳng NCC không còn chứng từ nào (đặc tả §3.14 🔧, §7.2 #22)
NCC_XOA_QUA_RPC = "NCC_XOA_QUA_RPC: xoá nhà cung cấp ở màn chi tiết NCC (chỉ Chủ NPP)."

# ------------------------------------------------------------------------------------------------ 2. đếm chứng từ
# (bảng, cột) của mọi khoá ngoại không CASCADE trỏ `suppliers` — đúng thứ tự `ORDER BY 1, 2` của `_ncc_dem_chung_tu` (pg_constraint bản tham chiếu;
# `user_suppliers` CASCADE không phải chứng từ)
BANG_CHUNG_TU = (("payables", "supplier_id"), ("products", "primary_supplier_id"), ("purchase_invoices", "supplier_id"),
	("purchase_orders", "supplier_id"), ("stock_entries", "supplier_id"), ("supplier_payments", "supplier_id"),
	("supplier_returns", "supplier_id"))
NHAN_BANG = {"purchase_invoices": "phiếu nhập", "supplier_returns": "phiếu trả NCC", "payables": "dòng công nợ NCC",
	"purchase_orders": "đơn đặt hàng NCC", "stock_entries": "phiếu kho", "products": "mặt hàng"}


def dem_chung_tu(so: Mapping[str, int]) -> dict:
	"""`_ncc_dem_chung_tu` từ số dòng mỗi bảng (`so[bang]`, thiếu = 0): `{tong, chi_tiet: [{bang, cot, so, nhan}]}` — chỉ bảng có dòng, đúng thứ tự
	khoá ngoại; nhãn bảng lạ = tên bảng thô."""
	tong, ct = 0, []
	for bang, cot in BANG_CHUNG_TU:
		n = int(so.get(bang) or 0)
		if n > 0:
			tong += n
			ct.append({"bang": bang, "cot": cot, "so": n, "nhan": NHAN_BANG.get(bang, bang)})
	return {"tong": tong, "chi_tiet": ct}


def mo_ta_chung_tu(chi_tiet: list[dict], bo_mat_hang: bool) -> str | None:
	"""`string_agg(so || ' ' || nhan, ', ')` của `chi_tiet` (theo thứ tự) — xoá qua RPC bỏ dòng `products`; rỗng → None (không có gì)."""
	ds = [f"{x['so']} {x['nhan']}" for x in chi_tiet if not (bo_mat_hang and x["bang"] == "products")]
	return ", ".join(ds) or None


def loi_co_chung_tu(ten: str, mo_ta: str) -> NppLoi:
	"""`NCC_CO_CHUNG_TU` của `xoa_nha_cung_cap` bước 1 và trigger `_ncc_chan_xoa` (cùng câu; `%` = tên NCC, danh sách chứng từ)."""
	return NppLoi(f'NCC_CO_CHUNG_TU: không xoá được nhà cung cấp "{ten}" — đã có {mo_ta}. Dùng "Ngừng hợp tác" hoặc "Gộp vào NCC khác".')


# ------------------------------------------------------------------------------------------------ 3. gộp
# cột hồ sơ chữ (ô trống của NCC giữ lại lấy của NCC bị gộp) và cột lấy `COALESCE` — đúng danh sách `UPDATE suppliers` bước 3 của mig 232
COT_CHU = ("category", "contact_name", "phone", "email", "address", "tax_code", "bank_account", "bank_name", "legal_name", "business_type",
	"representative", "business_license_no", "registered_address")
COT_COALESCE = ("business_license_date", "credit_limit")


def ngay_vn(d: date) -> str:
	"""`to_char(…, 'DD/MM/YYYY')`."""
	return d.strftime("%d/%m/%Y")


def ghi_chu_dau_ky_gop(ghi_chu: str | None, ten_tu: str, hom_nay: date) -> str:
	"""Bước 0: dòng nợ đầu kỳ của NCC bị gộp thành nợ thường khi NCC giữ lại đã có nợ đầu kỳ (`uq_payables_opening`)."""
	moi = f"Nợ đầu kỳ của NCC {ten_tu} (gộp ngày {ngay_vn(hom_nay)})"
	cu = btrim(ghi_chu)
	return f"{cu} · {moi}" if cu else moi


def ghi_chu_ho_so_gop(ghi_chu_vao: str | None, ten_tu: str, ma_tu: str | None, ghi_chu_tu: str | None, hom_nay: date) -> str:
	"""Bước 3: ghi chú NCC giữ lại — `concat_ws(E'\\n', NULLIF(btrim(cũ), ''), 'Gộp từ NCC <tên>[ (<mã>)] ngày dd/mm/yyyy.', 'Ghi chú NCC cũ: …')`."""
	phan = [btrim(ghi_chu_vao), f"Gộp từ NCC {ten_tu}{'' if ma_tu is None else f' ({ma_tu})'} ngày {ngay_vn(hom_nay)}."]
	cu = btrim(ghi_chu_tu)
	if cu:
		phan.append(f"Ghi chú NCC cũ: {cu}")
	return "\n".join(x for x in phan if x)


def ho_so_gop(vao: Mapping, tu: Mapping, hom_nay: date) -> dict:
	"""Hồ sơ NCC giữ lại sau gộp (cột nppsale `suppliers`): ô chữ = `COALESCE(NULLIF(btrim(vao), ''), tu)` (giữ bản đã trim của NCC giữ lại; lấy
	nguyên chữ của NCC bị gộp), ngày cấp ĐKKD / hạn mức = `COALESCE(vao, tu)`, ghi chú theo `ghi_chu_ho_so_gop`. Trả MỌI cột (kể cả không đổi)."""
	ra = {c: (btrim(vao.get(c)) or tu.get(c)) for c in COT_CHU}
	for c in COT_COALESCE:
		ra[c] = vao.get(c) if vao.get(c) is not None else tu.get(c)
	ra["notes"] = ghi_chu_ho_so_gop(vao.get("notes"), tu.get("name"), tu.get("code"), tu.get("notes"), hom_nay)
	return ra


# ------------------------------------------------------------------------------------------------ 4. xoá
def xoa_hang_cua(p_xoa_hang, co_truyen: bool) -> bool:
	"""`p_xoa_hang` của `xoa_nha_cung_cap` (boolean DEFAULT false): không truyền → false; NULL tường minh → như true (`IF NOT NULL OR …` không vào
	nhánh gỡ); còn lại theo giá trị (đã ép kiểu boolean ở nơi gọi)."""
	if not co_truyen:
		return False
	return True if p_xoa_hang is None else bool(p_xoa_hang)


def nhanh_mat_hang(xoa_hang: bool, co_chung_tu: bool) -> str:
	"""Một mặt hàng lấy NCC làm NCC chính → `go` (gỡ NCC) | `ngung_ban` (ngừng bán + gỡ) | `xoa` (thử xoá; vướng liên kết → `ngung_ban`)."""
	if not xoa_hang:
		return "go"
	return "ngung_ban" if co_chung_tu else "xoa"
