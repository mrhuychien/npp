"""Kho + mua hàng + công nợ NCC (P4) so với CHÍNH hàm + trigger + RLS của nppsale (cần bench):

	bench --site poc.local run-tests --module nppsale.tests.test_kho_mua_vang
	NPP_VANG_CHI=V01,V13 bench … run-tests …        (chạy một phần — đầu mã kịch bản)

Dữ liệu vàng du_lieu/kho_mua_mau.json (tools/vang_kho_mua.py — đặc tả kho_mua §6: kịch bản V01–V87 trên bộ dữ liệu F §6.0). Bài dựng cùng người / NCC /
mặt hàng / khách / bảng giá bán trên site, phát lại cùng chuỗi bước qua cổng RPC / cổng bảng DƯỚI ĐÚNG NGƯỜI và so: từng bước (thành / bại, mã + câu lỗi
TỪNG KÝ TỰ — §2.5), số trả về, ảnh chụp cuối theo KHOÁ NGHIỆP VỤ (phiếu nhập + dòng, lô, công nợ NCC, bảng giá nhập, phiếu kho của phiếu nhập, HĐ bán nền,
nhãn) — cùng luật đọc với bộ sinh (`quy_uoc` của tệp vàng). Sau mỗi kịch bản: khám sổ công nợ NCC của các NCC nền + khám sổ P4 (kho / mua — M9) phải sạch.
Từ M9 mọi mốc M1–M9 đã dựng: không còn kịch bản "chưa dựng" (112 tình huống chạy, 11 chỉ nppsale).

Phạm vi theo mốc (đặc tả §8): kịch bản của mốc CHƯA DỰNG (`DA_DUNG`) bỏ qua và in số; `chi_nppsale` (kịch bản / bước — NPP thứ hai, dữ liệu cũ đặt bằng
quyền máy chủ) bỏ; `nguon: dac_ta` (chỉ có ở Frappe — mong là chữ của đặc tả) kiểm bằng hàm riêng ở `KIEM_DAC_TA`.

Chuẩn hoá trước khi so (khác có chủ đích — không phải lệch; quyết định tạm Q9):
- câu 18: Frappe cấp số `PN-` lúc LẬP NHÁP → mã phiếu so theo NHÃN của bước (P, Q…): mã nppsale / tên Frappe → "<nhãn>", lô "<nhãn>-NNN"; phiếu tạm nppsale
  chưa mã cũng mang "<nhãn>" (bên Frappe nó đã có số).
- CFD-01: khôi phục = amend `PN-0001-1` → cả chuỗi amend là MỘT nhãn, ảnh chụp lấy tờ CUỐI của chuỗi (nppsale giữ id).
- §7.2 #14: phiếu kho của phiếu nhập = chính PI → ghi chú phiếu kho = ghi chú phiếu (nppsale "Nhập kho từ phiếu nhập hàng <mã>"); dòng kho không so
  `quantity` (⚠K §4.5: Frappe SL giao dịch, nppsale ROUND(SL cơ sở)); phiếu kho của HĐ bán / hoàn kho / nhập lại hàng khách trả (`XK-` / `NK-` / `NL-`)
  và `phieu_kho` / `entry_id` của HĐ không so ở ảnh chụp (phiếu kho của HĐ / tờ ghi có = chính chứng từ — đọc cổng ở nppsale.tests.test_kho_tay).
- M4 — phiếu kho tay (nhãn `pk:`): mã phiếu → "<nhãn>" (Frappe cấp `XKL-` / `CKL-` / `IN-…` — mã trình duyệt gửi bị thay, §4.5), trong câu lỗi
  cũng vậy (tên Frappe / mã nppsale của phiếu kho, phiếu nhập, phiếu trả NCC, HĐ, chứng từ của phiếu trả khách → "<nhãn>" — từ M4); vết lấy lô
  (`stock_line_consumptions` ↔ gói lô Outward) so GỘP theo lô ở mức phiếu (V42: nppsale thứ tự dòng theo uuid); dòng xuất / chuyển không so `lo`
  (⚠K cổng: `batch_id` khi dòng lấy đúng một lô, nppsale luôn NULL); lô dựng sẵn ở kho bán mà hạn trong ngưỡng vào thẳng kho date (trigger
  `batches_auto_zone` lúc chèn — bản Frappe: kho tạo theo `goi_lo.kho_nhan_lo` của app, M5).
- M5 — lô + kho cận date: chỗ giữ "@lo:<mã>[@vùng]" → id cổng `<lô>::<vùng>`; rà soát / sửa hạn chuyển lô bằng phiếu `CKL-` (⚠K §7.2 #7) → lô có thêm
  dòng kho bán tồn 0 và thẻ kho không đổi vùng hồi tố (hàm LECH từng kịch bản); số lô rà soát trừ lô CÓ SẴN trên site mà phiếu rà soát chở.
- M6 — kiểm kê: phiếu kiểm kê là `NPP Kiem Ke` (tên `KK-YYMMDD-NNNN` — mã trình duyệt gửi bị thay) → so theo nhãn như phiếu kho tay; giờ trong câu
  `ALREADY_POSTED` (HH:MI DD/MM/YYYY) → "<HH:MI @hom_nay±n>" cả hai phía; chi phí hao hụt (`expenses` ↔ `NPP Phieu Chi` nguồn `stocktake`) so theo
  (danh mục, ngày, tiền, diễn giải / tham chiếu / phiếu nguồn theo nhãn, chưa trả, người lập); `expense_id` → "cp:<nhãn phiếu kiểm kê>".
- §7.2 #26: lô mà mọi gói lô đã huỷ (huỷ phiếu nhập) → cổng `batches` ra dòng "lô chưa phát sinh" `qty_initial 0` (nppsale giữ số nhập cũ, `status
  cancelled`); trạng thái tắt = `cancelled` như nppsale (Batch `disabled` — §7.3 điểm 35).
- M8 — nhà cung cấp: ảnh chụp thêm `ncc` (NCC của bộ dữ liệu + NCC lập trong kịch bản — chỗ giữ "@S5" gắn với tên `NCC-####` Frappe cấp, id gửi lên bị
  bỏ), `hang` (trạng thái + NCC chính của mặt hàng nền — trừ X chỉ Frappe), `phan_cong` (NV ↔ NCC); tệp vàng chỉ ghi ba mục ấy khi khác nền (`nen.ct_nen`)
  — vắng mặt = như nền; NCC chính của nền = `Item Default.default_supplier` (B / N → S3, M → S1, R → S4); ngày trong ghi chú gộp ("<@hom_nay>") → ngày VN
  thật; số phiên danh mục so MỨC TĂNG (V84 — nppsale tăng theo từng lệnh trên products, kể cả 0 dòng).
- M9 — báo cáo / đầu-cuối: `bao_cao_ton_kho` so theo tập (id `<lô>::<vùng>` → "lo:<mã>@<vùng>"; lô có sẵn trên site / lô ảo hàng không lô và dòng
  của HĐ có sẵn bỏ), "hoa_don_mua_con_no" mô phỏng câu của /purchasing/invoices QUA CỔNG (mã phiếu theo nhãn), V80 kiểm đặc tả (`_v80`); sau MỌI kịch
  bản còn chạy khám sổ P4 (`nppsale.kham_so.quet_kho_mua` trên hàng / NCC của bộ dữ liệu — tồn lô = Σ gói lô = Bin = Σ sổ kho, lô không âm, một giá
  nhập mỗi đơn vị…) bên cạnh khám sổ công nợ NCC.
- tiền: Frappe làm tròn đồng (BP §7.2 điểm 3); giá vốn lô so 2 chữ số lẻ (§7.1 #5).
LECH: kịch bản bản Frappe khác hẳn (⚠K / ❓) → hàm sửa phần MONG (bước + ảnh chụp) thành kết quả Frappe, kèm lý do — 00_quyet_dinh_trien_khai.md Q9.
"""
from __future__ import annotations

import copy
import json
import os
import re
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, nowdate

from nppsale.cong import api
from nppsale.cong import bang as B
from nppsale.cong.dang_ky import NguCanh
from nppsale.cong.truy_van import doc as doc_cong
from nppsale.luat.sdt import email_ky_thuat
from nppsale.tests import test_xuat_hang as XH
from nppsale.thiet_lap.kho_mua import cai_dat_kho

VANG = os.path.join(os.path.dirname(__file__), "du_lieu", "kho_mua_mau.json")
ADMIN = NguCanh(user="Administrator", vai=None, bo_qua_rls=True)
NS = uuid.UUID("6f1c2a77-1d0e-4b8f-9a3c-2b4d5e6f7081")

# mốc dựng → số kịch bản (đặc tả §8; V81–V87 gắn mốc theo §9.3)
MOC = {"M1": range(1, 17), "M2": (*range(17, 29), 87), "M3": (*range(29, 41), 86), "M4": (*range(41, 56), 81, 85), "M5": (*range(56, 60), 82),
	"M6": range(60, 65), "M7": (*range(65, 72), 83), "M8": (72, 73, 84), "M9": range(74, 81)}
DA_DUNG = ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9")
# mục ảnh chụp đã so theo mốc (mục của mốc sau — tra_no, phieu_chi, chi_phi… — thêm khi dựng)
MUC_SO = ("pn", "ptn", "lo", "no", "tra_no", "phieu_chi", "gia_nhap", "phieu_kho", "hd", "tra_khach", "chi_phi", "ncc", "hang", "phan_cong", "nhan")
NEN_TINH = ("ncc", "hang", "phan_cong")  # mục ảnh chụp tệp vàng chỉ ghi khi khác bộ dữ liệu nền (`nen.ct_nen`) — vắng mặt = như nền (M8)
BUOC_PK = ("nhap_kho", "pk", "xuat_le", "chuyen", "huy_pk")  # bước phiếu kho tay (M4)
LOAI_CT = ("pn", "ptn")  # nhãn chứng từ PI (phiếu nhập / phiếu trả NCC): cả chuỗi amend là MỘT nhãn (CFD-01)
LA = str(uuid.uuid5(NS, "p4:la"))  # "@la" — id không có dòng nào (uuid hợp lệ như bộ sinh)
_RE_HOM_NAY = re.compile(r"^@hom_nay([+-]\d+)?(T.*)?$")
_RE_THIEU = re.compile(r"(INSUFFICIENT_STOCK \| .*\()([^()]*)(\): cần )")
_RE_DA_XUAT = re.compile(r"(: đã xuất \S+ )(\S+)(, số lượng mới chỉ )")  # DA_XUAT_NHIEU_HON (M7): đơn vị cơ sở của mặt hàng
_RE_XK_PTN = re.compile(r"Xuất kho trả NCC — phiếu (\S+) \(kho: \w+\)")
_RE_GIO_NGAY = re.compile(r"\b(\d{2}):(\d{2}) (\d{2})/(\d{2})/(\d{4})\b")  # `to_char(posted_at, 'HH24:MI DD/MM/YYYY')` — ALREADY_POSTED (M6)


def moc_cua(ma: str) -> str | None:
	n = int(re.match(r"V(\d+)", ma).group(1))
	return next((m for m, ds in MOC.items() if n in ds), None)


# ------------------------------------------------------------------------------------------------ lệch có chủ đích (⚠K / ❓ — Q9)
def _v05d(t, mong):
	mong["ct"]["no"][0]["status"] = "paid"


def _v08b(t, mong):
	b = mong["buoc"]
	b[0] = {"ok": False, "ma_loi": "P0001", "loi": "SO_LUONG_KHONG_HOP_LE: Dòng 2 có số lượng không lớn hơn 0."}
	b[1] = {"ok": False, "ma_loi": "P0001", "loi": "PHIEU_KHONG_CO_HANG: Phiếu chưa có dòng hàng nào."}
	t["buoc"][0]["tiep"] = True
	p = next(x for x in mong["ct"]["pn"] if x["nhan"] == "P")
	p.pop("dong", None)
	p.update({"subtotal": 0, "total": 0})


def _v12(t, mong):
	"""Hàng THEO LÔ không bao giờ âm (CFD-05 B): huỷ bị chặn dù cờ bán vượt tồn đã bật — câu riêng §7.3 điểm 12; dừng ở bước huỷ → sổ như V11."""
	mong["buoc"][4] = {"ok": False, "ma_loi": "P0001", "loi": "HANG_DA_XUAT: Không huỷ được vì hàng của phiếu đã xuất bớt — Hàng A (nhập 48.000000, còn "
		"18.000000). Lập phiếu trả hàng NCC hoặc phiếu điều chỉnh kho."}
	ct = mong["ct"]
	p = ct["pn"][0]
	for k in ("huy_boi", "luc_huy", "ly_do_huy"):
		p.pop(k, None)
	p.update({"status": "completed", "no": "PN:PN-0001"})
	ct["lo"][0].update({"ton": 18.0, "status": "available"})
	ct["no"] = [{"luc": "@luc_goi", "ncc": "@S1", "khoa": "PN:PN-0001", "so_hd": "HD-NCC-1", "da_tra": 0, "dau_ky": False, "status": "open",
		"ghi_chu": "Phiếu nhập hàng PN-0001", "so_tien": 480000, "phieu_kho": "PN-0001", "luc_bang_hoan_thanh": True}]
	ct["hd"][0]["status"] = "posted"
	ct["phieu_kho"][0]["status"] = "posted"


# ------------------------------------------------------------------------------------------------ M2 — trả NCC
USE_RPC_TRA = "USE_RPC: dùng nút Gửi phiếu / Huỷ phiếu / Khôi phục"


def _ptn(ct: dict, nhan: str) -> dict:
	return next(p for p in ct["ptn"] if p["nhan"] == nhan)


def _v18(t, mong):
	_ptn(mong["ct"], "R").update({"subtotal": 15000, "total": 15000})


def _v19(t, mong):
	"""Hàng THEO LÔ không xuất âm (CFD-05 B): gửi báo như V18 lần 1 dù NPP cho bán vượt tồn → phiếu ở Nháp; huỷ = dấu huỷ của nháp."""
	mong["buoc"][6] = {"ok": False, "ma_loi": "P0001", "loi": "INSUFFICIENT_STOCK | Sữa hộp (hộp): cần 20, kho hàng date còn 0.000000, kho "
		"hàng bán còn 100.000000"}
	t["buoc"][6]["tiep"] = True
	p = _ptn(mong["ct"], "R")
	for k in ("phieu_kho", "hoan_thanh_boi", "luc_hoan_thanh"):
		p.pop(k, None)
	mong["ct"]["phieu_kho"] = None


def _v22(t, mong):
	"""CFD-01: tờ amend NHÁP không trỏ phiếu kho (nppsale: nháp còn trỏ `XK-` cũ)."""
	_ptn(mong["ct"], "R").pop("phieu_kho", None)


def _v25(t, mong):
	"""Sửa phiếu đã xuất = RPC `sua_phieu_tra_ncc` MỘT giao dịch (§3.8 / §7.3 điểm 2): cổng chặn lối ghi thẳng `status 'draft'` của nppsale."""
	ghi = t["buoc"][7]["gia_tri"]
	dau = {k: v for k, v in ghi.items() if k not in ("status", "cancel_reason", "subtotal", "vat", "total")}
	t["buoc"][6:10] = [
		{"buoc": "ghi", "nguoi": "TK", "bang": "supplier_returns", "hanh_dong": "update", "gia_tri": ghi, "loc": {"id": "@ptn:R"}, "tiep": True},
		{"buoc": "ptn_sua", "nguoi": "TK", "nhan": "R", "dau": dau, "dong": t["buoc"][8]["dong"], "ly_do": "Sửa phiếu từ POS — lập lại"},
	]
	mong["buoc"][6:10] = [{"ok": False, "ma_loi": "P0001", "loi": USE_RPC_TRA}, {"ok": True, "tra": {"id": "ptn:R", "trang_thai": "completed"}}]


def _v26(t, mong):
	"""Tiền làm tròn đồng (BP §7.2 điểm 3); nợ 0 đ = đã trả đủ (BP §4.3.0); R4 có dòng SL ≤ 0 / tiền âm → cổng chặn lúc lưu dòng (§7.3 điểm 23)."""
	ct = mong["ct"]
	_ptn(ct, "R1").update({"vat": 988, "total": 13333})
	for x in ct["no"]:
		if x["khoa"] == "PTNCC:PTNCC-0001":
			x["so_tien"] = -13333
		if x["khoa"] == "PTNCC:PTNCC-0003":
			x["status"] = "paid"
	ct["no"] = [x for x in ct["no"] if x["khoa"] != "PTNCC:PTNCC-0004"]
	mong["buoc"][10] = {"ok": False, "ma_loi": "P0001", "loi": "SO_LUONG_KHONG_HOP_LE: Dòng 2 có số lượng không lớn hơn 0."}
	mong["buoc"][11] = {"ok": False, "ma_loi": "P0001", "loi": "PHIEU_KHONG_CO_HANG: Phiếu chưa có dòng hàng nào."}
	t["buoc"][10]["tiep"] = t["buoc"][11]["tiep"] = True
	r4 = _ptn(ct, "R4")
	for k in ("dong", "phieu_kho", "no", "hoan_thanh_boi", "luc_hoan_thanh"):
		r4.pop(k, None)
	r4.update({"status": "draft", "subtotal": 0, "total": 0})
	ct["phieu_kho"] = [x for x in ct["phieu_kho"] if "PTNCC-0004" not in (x.get("ghi_chu") or "")]
	next(x for x in ct["lo"] if x["ma"] == "L-B3")["ton"] = 99.0


def _v27(t, mong):
	mong["buoc"][6] = {"ok": True, "tra": {"so_dong": 1}}


def _v28(t, mong):
	"""Cổng chặn ba lối ghi thẳng lên phiếu ĐÃ XUẤT (BP §6.1): sửa dòng, về nháp, xoá → phiếu, kho, nợ giữ nguyên."""
	for i in (6, 7, 10):
		mong["buoc"][i] = {"ok": False, "ma_loi": "P0001", "loi": USE_RPC_TRA}
		t["buoc"][i]["tiep"] = True
	ct = mong["ct"]
	r1 = _ptn(ct, "R1")
	r1["status"] = "completed"
	r1["dong"][0]["sl"] = 2
	ct["ptn"].append({**copy.deepcopy(r1), "ma": "PTNCC-0002", "no": "PTNCC:PTNCC-0002", "nhan": "R2", "vung": "sale", "subtotal": 4000,
		"total": 4000, "dong": [{**r1["dong"][0], "sl": 4, "tien": 4000}]})
	for x in ct["no"]:
		if x["khoa"].startswith("PK:"):
			x["khoa"] = "PTNCC:PTNCC-0002"


# ------------------------------------------------------------------------------------------------ M3 — công nợ + tiền NCC
def _bo_buoc(t, mong, *chi_so):
	"""Bỏ bước (và kết quả mong của nó) — thứ tự giảm dần để chỉ số không trôi."""
	for i in sorted(chi_so, reverse=True):
		del t["buoc"][i]
		del mong["buoc"][i]


BU_TRU_HET = {"ok": False, "ma_loi": "P0001", "loi": "BU_TRU_KHONG_CON: NCC không còn khoản giảm để bù trừ."}


def _no(ct: dict, khoa: str) -> dict:
	return next(x for x in ct["no"] if x["khoa"] == khoa)


def _v36(t, mong):
	"""§7.3 điểm 10 / BP §7.1 điểm 15 (quyết định tạm Q9): Bù trừ (`offset`) = bút toán `CTN-` trừ vào khoản giảm CÒN MỞ của phiếu trả NCC của
	chính NCC (R −30.000) — nppsale ghi `offset` như khoản trả không tiền, không gắn khoản nào (dòng âm vẫn open). Bù 50.000 vượt khoản giảm →
	BU_TRU_KHONG_CON; bù 30.000 (hết khoản giảm) được; bù thêm 1 → BU_TRU_KHONG_CON; "trả nốt" 170.000 thay 150.000 (khoản PN về đủ như nppsale),
	hình thức '' → tiền mặt (cổng `cash`); Ghi trả vào dòng R (đã bù hết) → OVERPAY còn 0 (nppsale −30000); dòng R `paid` (đã dùng hết khoản giảm)."""
	b, m = t["buoc"], mong["buoc"]
	b[9] = {**b[9], "tiep": True}
	m[9] = BU_TRU_HET
	b[10] = {**b[10], "tien": 170000}
	m[10] = {"ok": True, "tra": {"new_paid": 200000, "new_status": "paid", "payment_id": "tra:PN:PN-0001"}}
	m[12] = {"ok": False, "ma_loi": "P0001", "loi": "OVERPAY: số tiền vượt quá công nợ còn lại (còn 0)."}
	b[10:10] = [{"buoc": "ghi_tra", "nguoi": "KT", "no": "@no:pn:PA", "tien": 30000, "cach": "offset", "ghi_chu": ""},
		{"buoc": "ghi_tra", "nguoi": "KT", "no": "@no:pn:PA", "tien": 1, "cach": "offset", "tiep": True}]
	m[10:10] = [{"ok": True, "tra": {"new_paid": 30000, "new_status": "partial", "payment_id": "tra:PN:PN-0001"}}, BU_TRU_HET]
	ct = mong["ct"]
	_no(ct, "PTNCC:PTNCC-0001").update({"da_tra": -30000, "status": "paid"})
	ct["tra_no"] = [
		{"no": "PN:PN-0001", "boi": "@u:KT", "luc": "@luc_goi", "cach": "offset", "tien": 30000, "xac_nhan": False},
		{"no": "PTNCC:PTNCC-0001", "boi": "@u:KT", "luc": "@luc_goi", "cach": "offset", "tien": -30000, "xac_nhan": False},
		{"no": "PN:PN-0001", "boi": "@u:KT", "luc": "@luc_goi", "cach": "cash", "tien": 170000, "ghi_chu": "trả nốt", "xac_nhan": False}]


def _v38(t, mong):
	"""(1) ⚠K số HĐ của khoản nợ phiếu nhập = `bill_no` của chính tờ (đặc tả §4.4): sửa ở màn công nợ là đổi luôn số HĐ NCC của phiếu nhập (nppsale
	hai cột riêng). (2) `DA_CAN_TRU` dựng bằng bút toán bù trừ `CTN-` trỏ phiếu trả NCC (KF của kịch bản) thay bước máy chủ đặt `paid −30000`: KT bù
	30.000 vào P → huỷ R báo DA_CAN_TRU (−30000) như nppsale; dòng R đã bù hết → `paid` (nppsale dữ liệu cũ vẫn open)."""
	b, m = t["buoc"], mong["buoc"]
	b[22] = {"buoc": "ghi_tra", "nguoi": "KT", "no": "@no:pn:P", "tien": 30000, "cach": "offset"}
	m[22] = {"ok": True, "tra": {"new_paid": 80000, "new_status": "partial", "payment_id": "tra:PN:PN-0001"}}
	b[23] = {k: v for k, v in b[23].items() if k != "chi_nppsale"}
	ct = mong["ct"]
	ct["pn"][0]["so_hd"] = "HD-MOI"
	_no(ct, "PN:PN-0001")["da_tra"] = 80000
	_no(ct, "PTNCC:PTNCC-0001").update({"da_tra": -30000, "status": "paid"})
	ct["tra_no"] += [{"no": "PN:PN-0001", "boi": "@u:KT", "luc": "@luc_goi", "cach": "offset", "tien": 30000, "xac_nhan": False},
		{"no": "PTNCC:PTNCC-0001", "boi": "@u:KT", "luc": "@luc_goi", "cach": "offset", "tien": -30000, "xac_nhan": False}]


def _v39(t, mong):
	"""⚠K đổi số nợ đầu kỳ ĐÃ trả → NO_NCC_KHOA (nppsale cho — `trangThaiSauSuaSoTien`): tờ amend `DKN-…-n` không mang được tiền đã trả."""
	mong["buoc"][10] = {"ok": False, "ma_loi": "P0001", "loi": "NO_NCC_KHOA: số nợ / số đã trả NCC chỉ đổi qua phiếu nhập, phiếu trả NCC, Ghi trả NCC (RPC)"}
	t["buoc"][10]["tiep"] = True
	dk = next(x for x in mong["ct"]["no"] if x["khoa"] == "DK:@S1")
	dk["so_tien"] = 350000


def _v86(t, mong):
	"""⚠K CFD-13: `post_stock_import` có NCC + tiền nợ là PHIẾU NHẬP `PN-` → khoản nợ của nó là khoản của phiếu nhập: xoá cũng 23503 như bước 3 (cùng
	nhánh mã — đặc tả §7.3 điểm 38), huỷ phiếu kho → ENTRY_HAS_SOURCE "thuộc một hoá đơn nhập mua" (nppsale: nợ của `IN-` xoá được rồi huỷ được) —
	lô, nợ, phiếu kho giữ nguyên."""
	b, m = t["buoc"], mong["buoc"]
	m[3]["tra"]["payable_id"] = "no:PN:<IN1>"
	m[4] = {"ok": False, "ma_loi": "23503", "loi": 'update or delete on table "payables" violates foreign key constraint '
		'"purchase_invoices_payable_id_fkey" on table "purchase_invoices"'}
	b[4]["tiep"] = True
	m[5] = {"ok": False, "ma_loi": "P0001", "loi": "ENTRY_HAS_SOURCE: phiếu IN-20261116-3001 thuộc một hoá đơn nhập mua. Huỷ hoá đơn nhập đó thay vì "
		"huỷ riêng phiếu kho."}
	ct = mong["ct"]
	next(x for x in ct["lo"] if x["ma"] == "LOT-IN-20261116-3001-1")["ton"] = 5.0
	ct["no"].append({"luc": "@luc_goi", "ncc": "@S1", "khoa": "PN:<IN1>", "so_hd": "HD-IN", "da_tra": 0, "dau_ky": False, "status": "open",
		"ghi_chu": "Nhập kho IN-20261116-3001", "so_tien": 50000, "phieu_kho": "<IN1>", "luc_bang_hoan_thanh": True})
	pk = next(x for x in ct["phieu_kho"] if x.get("nhan") == "IN1")
	pk["status"] = "posted"
	pk.pop("ghi_chu", None)


# ------------------------------------------------------------------------------------------------ M4 — phiếu kho tay
def _loi(cau: str) -> dict:
	return {"ok": False, "ma_loi": "P0001", "loi": cau}


HUY_NHAP = {"ok": True, "tra": {"cancelled": True, "reversed": False, "lines_reversed": 0}}  # huỷ nháp = xoá nháp (§7.3 điểm 1) / phiếu đã huỷ


def _pk(ct: dict, nhan: str) -> dict:
	return next(x for x in ct["phieu_kho"] if x.get("nhan") == nhan)


def _bo_pk(ct: dict, *nhan: str) -> None:
	"""Phiếu nháp đã XOÁ ở bản Frappe (huỷ nháp = xoá — §7.3 điểm 1): không còn trong ảnh chụp (nhãn giữ)."""
	ct["phieu_kho"] = [x for x in ct.get("phieu_kho") or [] if x.get("nhan") not in nhan] or None


def _chuyen_vung(mong, ma_lo: str, boi: str = "@u:TK") -> None:
	"""⚠K §3.16 Frappe bước 4: MỘT Batch cho hai kho — `npp_chuyen_vung_luc` / `npp_chuyen_vung_boi` (người ghi sổ chuyển kho) hiện ở CẢ HAI dòng cổng
	`batches` của lô (nppsale: `zone_moved_at` chỉ trên dòng lô ĐÍCH, `zone_moved_by` không ghi)."""
	for x in mong["ct"]["lo"]:
		if x["ma"] == ma_lo:
			x.update({"luc_chuyen_vung": "@luc_goi", "chuyen_boi": boi})


LO_TRUNG_V41 = "LO_TRUNG_MA: Mã lô LOT-IN-20261001-1234-1 đã có trong sổ — đổi mã lô ấy rồi ghi lại phiếu nhập kho."


def _v41(t, mong):
	"""⚠K CFD-13: nhập kho có NCC + tiền nợ = PHIẾU NHẬP `PN-` → khoản nợ là khoản của phiếu nhập (khoá `PN:`); §7.3 điểm 6 / BP §7.1 điểm 14 (Q9):
	gọi lại cùng mã phiếu (lô `LOT-<mã>-1` đã có) → LO_TRUNG_MA (nppsale lập phiếu thứ hai + lô thứ hai CÙNG mã)."""
	b, m = t["buoc"], mong["buoc"]
	m[0]["tra"]["payable_id"] = "no:PN:<IN1>"
	for i in (4, 5):
		m[i] = _loi(LO_TRUNG_V41)
		b[i]["tiep"] = True
	ct = mong["ct"]
	lo_in = [x for x in ct["lo"] if x["ma"] == "LOT-IN-20261001-1234-1"]
	ct["lo"] = [x for x in ct["lo"] if x["ma"] != "LOT-IN-20261001-1234-1"] + lo_in[:1]
	ct["no"] = [{**ct["no"][0], "khoa": "PN:<IN1>", "phieu_kho": "<IN1>", "luc_bang_hoan_thanh": True}]
	ct["phieu_kho"] = [x for x in ct["phieu_kho"] if x.get("nhan") not in ("IN5", "IN6")]
	ct["nhan"] = [x for x in ct["nhan"] if x not in ("pk:IN5", "pk:IN6")]


KHONG_DU_V43 = "KHONG_DU_TON: Nuoc ngot — cần 24.000000 Thung, kho hàng bán chỉ còn 10.000000. Giảm số lượng, đổi kho, hoặc nhập bù rồi ghi sổ lại."


def _v43b(t, mong):
	"""CFD-05 B: hàng THEO LÔ không bao giờ âm — cờ bán vượt tồn không áp (nppsale ghi sổ, 14 thiếu im lặng): báo như V43a, nháp giữ, tồn không đổi."""
	mong["buoc"][4] = _loi(KHONG_DU_V43)
	ct = mong["ct"]
	next(x for x in ct["lo"] if x["ma"] == "L-A")["ton"] = 10.0
	pk = _pk(ct, "X")
	pk["status"] = "draft"
	pk.pop("luc_ghi_so", None)
	for d in pk["dong"]:
		d.pop("vet", None)


def _v44a(t, mong):
	"""CFD-05 B: Q theo lô mà không lô nào → KHONG_DU_TON dù cho bán vượt tồn (nppsale ghi sổ âm không vết rồi huỷ báo NO_CONSUMPTION_TRACE); phiếu
	ở nháp → huỷ = xoá nháp `[true, false, 0]`."""
	t["buoc"][2]["tiep"] = True
	mong["buoc"][2] = _loi("KHONG_DU_TON: Dau an — cần 3.000000 Chai, kho hàng bán chỉ còn 0. Giảm số lượng, đổi kho, hoặc nhập bù rồi ghi sổ lại.")
	mong["buoc"][3] = HUY_NHAP
	_bo_pk(mong["ct"], "XKL-AM")


def _v44b(t, mong):
	"""§7.3 điểm 23: cổng chặn dòng SL ≤ 0 lúc lưu (nppsale nhận: XKL-M báo "vừa bị lấy mất", XKL-0 ghi sổ +2 rồi NO_CONSUMPTION_TRACE) → hai phiếu
	không dòng: ghi sổ báo PHIEU_KHONG_CO_HANG; huỷ nháp XKL-0 = xoá."""
	b, m = t["buoc"], mong["buoc"]
	m[1] = _loi("SO_LUONG_KHONG_HOP_LE: Dòng 2 có số lượng không lớn hơn 0.")
	m[2] = _loi("PHIEU_KHONG_CO_HANG: Phiếu chưa có dòng hàng nào.")
	m[3] = _loi("SO_LUONG_KHONG_HOP_LE: Dòng 1 có số lượng không lớn hơn 0.")
	m[4] = _loi("PHIEU_KHONG_CO_HANG: Phiếu chưa có dòng hàng nào.")
	for i in (1, 2, 3, 4):
		b[i]["tiep"] = True
	m[5] = HUY_NHAP
	ct = mong["ct"]
	_pk(ct, "XKL-M").pop("dong", None)
	_bo_pk(ct, "XKL-0")


def _v45(t, mong):
	"""§7.3 điểm 1: huỷ nháp = XOÁ nháp → lệnh đổi `draft → cancelled` không còn dòng để trả (0 dòng); ghi sổ phiếu ấy → PHIEU_KHONG_TON_TAI (đặc tả
	V45 ⚠K)."""
	m = mong["buoc"]
	m[10] = {"ok": True, "tra": {"so_dong": 0}}
	m[11] = _loi("PHIEU_KHONG_TON_TAI: Không tìm thấy phiếu xuất kho này.")
	_bo_pk(mong["ct"], "X4")


def _v46(t, mong):
	"""(1) §7.3 điểm 1: huỷ nháp E1 = xoá → 0 dòng trả về; ghi lên E1 sau đó: thêm dòng → RLS (phiếu cha không còn), về nháp / xoá → 0 dòng. (2) ⚠K
	§4.5: phiếu đã ghi sổ chỉ sửa `notes` — đổi `entry_code` / `issue_reason` / `supplier_id` / `ref_order_ids` cùng lệnh → SO_KHO_KHOA, không đổi gì
	(tên chứng từ Frappe không đổi được). (3) Phiếu kiểm kê (M6 — `NPP Kiem Ke`): quản lý đổi thẳng trạng thái → 0 dòng như nppsale (RLS), nháp giữ."""
	b, m = t["buoc"], mong["buoc"]
	m[5] = {"ok": True, "tra": {"so_dong": 0}}
	m[8] = _loi("SO_KHO_KHOA: phiếu đã ghi sổ chỉ sửa được ghi chú.")
	b[8]["tiep"] = True
	m[10] = {"ok": False, "ma_loi": "42501", "loi": 'new row violates row-level security policy for table "stock_entry_lines"'}
	m[11] = {"ok": True, "tra": {"so_dong": 0}}
	m[12] = {"ok": True, "tra": {"so_dong": 0}}
	ct = mong["ct"]
	_bo_pk(ct, "E1")
	e2 = _pk(ct, "E2")
	for k in ("ncc", "ly_do_xuat", "ghi_chu"):
		e2.pop(k, None)
	e2["so_don"] = 0


def _v47(t, mong):
	_chuyen_vung(mong, "L-A")


def _v50(t, mong):
	"""§7.3 điểm 1: huỷ nháp XKL-N = xoá → lần hai ENTRY_NOT_FOUND; không còn dòng "Đã huỷ" + ghi chú của nháp (đặc tả V50 ⚠K)."""
	mong["buoc"][10] = _loi("ENTRY_NOT_FOUND: không tìm thấy phiếu kho này.")
	_bo_pk(mong["ct"], "XKL-N")


def _v51(t, mong):
	"""⚠K CFD-13: nhập kho có NCC + tiền nợ = PHIẾU NHẬP → huỷ phiếu kho báo "thuộc một hoá đơn nhập mua" (nppsale: "đang có công nợ NCC"), nợ là khoản
	`PN:`; §7.2 #26: lô mà mọi gói lô đã huỷ (nhập rồi huỷ) ra dòng "chưa phát sinh" nhập 0 (nppsale giữ số nhập cũ)."""
	m = mong["buoc"]
	m[0]["tra"]["payable_id"] = "no:PN:<IN1>"
	m[1] = _loi("ENTRY_HAS_SOURCE: phiếu IN-20261116-0001 thuộc một hoá đơn nhập mua. Huỷ hoá đơn nhập đó thay vì huỷ riêng phiếu kho.")
	ct = mong["ct"]
	next(x for x in ct["lo"] if x["ma"] == "LOT-IN-20261116-0002-1")["nhap"] = 0.0
	ct["no"][0].update({"khoa": "PN:<IN1>", "phieu_kho": "<IN1>", "luc_bang_hoan_thanh": True})


def _v52(t, mong):
	_chuyen_vung(mong, "G-1")


def _v53(t, mong):
	"""⚠K §7.2 #14: phiếu kho của HĐ / phiếu trả NCC / phiếu trả khách = CHÍNH chứng từ (HĐ, PI trả NCC, tờ ghi có có kho) → câu nêu tên chứng từ;
	cổng `batches` "nhập" = Σ phần VÀO kho của lô (gồm hàng khách trả nhập lại — nppsale `qty_initial` giữ số nhập đầu)."""
	m = mong["buoc"]
	for i in (7, 12):
		m[i]["loi"] = m[i]["loi"].replace("phiếu XK-<giờ> thuộc hóa đơn", "phiếu HD-0001 thuộc hóa đơn")
	m[9]["loi"] = m[9]["loi"].replace("phiếu XK-<giờ>", "phiếu PTNCC-0001")
	m[10]["loi"] = m[10]["loi"].replace("phiếu NL-<giờ>", "phiếu <T1>")
	next(x for x in mong["ct"]["lo"] if x["ma"] == "L-A")["nhap"] = 11.0


def _v54(t, mong):
	"""⚠K §3.19 Frappe bước 4 (đóng lỗ V18): nguồn nhận diện bằng TRƯỜNG THẬT, không theo ghi chú; phiếu đã ghi sổ chỉ sửa được ghi chú (đổi mã →
	SO_KHO_KHOA) → ghi chú "hoàn kho do huỷ HĐ" vẫn huỷ được ngay lần đầu `[true, true, 1]`; các lần sau phiếu đã huỷ `[true, false, 0]`, ghi chú sửa
	sau cùng giữ nguyên."""
	b, m = t["buoc"], mong["buoc"]
	b[3]["tiep"] = True
	m[3] = _loi("SO_KHO_KHOA: phiếu đã ghi sổ chỉ sửa được ghi chú.")
	b.insert(4, {"buoc": "ghi", "nguoi": "TK", "bang": "stock_entries", "hanh_dong": "update", "gia_tri": {"notes": "Hoàn kho do huỷ hóa đơn HD-9999"},
		"loc": {"id": "@pk:X1"}})
	m.insert(4, {"ok": True, "tra": {"so_dong": 1}})
	m[5] = {"ok": True, "tra": {"cancelled": True, "reversed": True, "lines_reversed": 1}}
	for i in (7, 9, 11):
		m[i] = HUY_NHAP
	_pk(mong["ct"], "X1")["ghi_chu"] = "binh thuong"


def _v55(t, mong):
	_chuyen_vung(mong, "L-A")


def _v81(t, mong):
	"""`finance_pnl` / `bao_cao_so_ban` thuộc P6 (chưa có trên bản Frappe — đặc tả §5.7) → giá vốn kỳ đọc QUA CỔNG như `fetchCogsForRange` (đường lùi
	của giao diện khi thiếu hàm): Σ |SL cơ sở| × `unit_cost` dòng phiếu `export` đã ghi sổ trong kỳ = số `finance_pnl.cogs` của nppsale (HĐ 100.000 +
	trả NCC 3 × giá LÔ 10.000, xuất lẻ 0 — §7.3 điểm 36, §10 điểm 3)."""
	gv = mong["buoc"][7]["tra"][0]["cogs"]
	t["buoc"][7:9] = [{"buoc": "gia_von_ky", "nguoi": "CHU", "tu": "@hom_nay", "den": "@hom_nay"}]
	mong["buoc"][7:9] = [{"ok": True, "tra": {"cogs": gv}}]


def _v85(t, mong):
	_chuyen_vung(mong, "PN-0001-001")


# ------------------------------------------------------------------------------------------------ M5 — lô + kho cận date
def _con_dong_ban(mong, ma_lo: str) -> None:
	"""⚠K §3.20 / §4.6 (§7.2 #7): rà soát / sửa hạn chuyển lô bằng phiếu `CKL-` `chuyen_date_tu_dong` → cổng `batches` còn dòng KHO BÁN của lô (tồn 0,
	nhập = số đã vào kho bán) bên cạnh dòng kho date — nppsale lật cờ vùng của MỘT dòng lô tại chỗ (thẻ kho đổi vùng hồi tố)."""
	x = next(y for y in mong["ct"]["lo"] if y["ma"] == ma_lo and y["vung"] == "date")
	mong["ct"]["lo"].append({**x, "vung": "sale", "ton": 0.0})


def _v56b(t, mong):
	_con_dong_ban(mong, "L5")


def _v57(t, mong):
	_con_dong_ban(mong, "L46")


def _lo_pk(ct: dict, nhan: str, cu: str, moi: str) -> None:
	"""Lô của dòng / vết lấy lô trong ảnh chụp phiếu kho `nhan`: nppsale in VÙNG HIỆN TẠI của dòng lô (đổi vùng hồi tố khi lô bị rà soát / sửa hạn), Frappe
	in kho của chính chứng từ (sổ kho không hồi tố — ⚠K §7.2 #13)."""
	pk = _pk(ct, nhan)
	for d in pk.get("dong") or []:
		if d.get("lo") == cu:
			d["lo"] = moi
		for v in d.get("vet") or []:
			if v.get("lo") == cu:
				v["lo"] = moi


def _v58(t, mong):
	"""⚠K §3.20: rà soát = `CKL-` 3 cái kho bán → date (nppsale lật cả dòng lô G-1 sang date); huỷ XKL-C trả 3 về KHO BÁN — nơi đã lấy (nppsale: về
	dòng lô gốc nay ở date) → G-1 bán 3 (nhập 10) / date 7 (4 + 3); thẻ kho không đổi vùng hồi tố (IN-B, vết CKL-B / XKL-C ở kho bán). Dấu chuyển vùng
	của Batch: lúc = lúc rà soát, người = TK của CKL-B (rà soát không ghi người — giữ người cũ như nppsale giữ `zone_moved_by`)."""
	ct = mong["ct"]
	goc = next(x for x in ct["lo"] if x["ma"] == "G-1")
	ct["lo"] = [{**goc, "vung": "sale", "ton": 3.0, "nhap": 10.0, "chuyen_boi": "@u:TK"},
		{**goc, "vung": "date", "ton": 7.0, "nhap": 7.0, "chuyen_boi": "@u:TK"}]
	for nhan in ("IN-B", "CKL-B", "XKL-C"):
		_lo_pk(ct, nhan, "G-1@date", "G-1@sale")


def _v59(t, mong):
	"""Bước 13 xoá lô của phiếu nhập P theo mã nppsale `PN-0001-001` → mã Frappe của P (dãy `PN-` của site — câu 18, so theo nhãn); ⚠K §4.6: sửa hạn L7
	vào ngưỡng = `CKL-` 7 sang date (dòng kho bán còn lại tồn 0)."""
	t["buoc"][12]["loc"] = {"id": "@lo:<pn:P>-001"}
	_con_dong_ban(mong, "L7")


def _v82a(t, mong):
	"""⚠K §4.6 S7 / V82a: hạn gửi lại không đổi vẫn chạy luật kho date → `CKL-` `chuyen_date_tu_dong` 10 cái (nppsale lật cả dòng lô, thẻ kho IN40 hồi tố
	sang date); vị trí 'Ke 2' ở cả hai dòng (một Batch)."""
	_con_dong_ban(mong, "L-40")
	_lo_pk(mong["ct"], "IN40", "L-40@date", "L-40@sale")


def _v82b(t, mong):
	"""⚠K §7.2 #27 / V82b: hạn là của Batch (một lô cho hai kho) — sửa trên dòng `::date` đổi hạn cả hai dòng (+20) và kéo tồn kho bán còn 6 sang date
	(`CKL-` tự động): date 10 (nhập 4 + 6), bán 0 (nhập 10); nppsale chỉ đổi hạn dòng date, dòng bán giữ +90 / tồn 6. Dấu chuyển vùng của CKL tay ở cả
	hai dòng (như M4)."""
	ct = mong["ct"]
	for x in ct["lo"]:
		if x["ma"] == "L-90":
			x.update({"han": "@hom_nay+20"} | ({"ton": 10.0, "nhap": 10.0} if x["vung"] == "date" else {"ton": 0.0}))
	_chuyen_vung(mong, "L-90")


def _v82d(t, mong):
	"""❓ §7.3 điểm 37 (đề xuất): "lô đang có tồn" xét Σ tồn MỌI kho của Batch (dòng kho bán tồn 0 nhưng dòng date còn 4) → sửa giá báo SO_KHO_KHOA, giá
	giữ 10.000 (nppsale nhận — chỉ đổi giá dòng tồn 0)."""
	mong["buoc"][6] = _loi("SO_KHO_KHOA: không sửa giá vốn của lô đang có tồn — giá vốn đã đi vào các phiếu xuất trước đó.")
	for x in mong["ct"]["lo"]:
		if x["ma"] == "L-90":
			x["gia"] = 10000
	_chuyen_vung(mong, "L-90")


# ------------------------------------------------------------------------------------------------ M6 — kiểm kê
def _nhap_lo(mong, ma_lo: str, nhap: float) -> None:
	"""⚠K (một luật với M4 "cột nhập của cổng batches" — V53): phần THỪA kiểm kê vào lô = Material Receipt `DCK-` → cổng `batches.qty_initial` (Σ phần
	VÀO kho của lô) tăng theo; nppsale giữ `qty_initial` (thừa chỉ cộng `qty_on_hand`)."""
	for x in mong["ct"]["lo"]:
		if x["ma"] == ma_lo:
			x["nhap"] = nhap


def _v60(t, mong):
	_nhap_lo(mong, "L-RONG", 2.0)


def _v63(t, mong):
	"""⚠K §3.17 Frappe bước 2 (đóng lỗ V13): `post_stock_adjustment` chỉ nhận phiếu kiểm kê `NPP Kiem Ke` → phiếu xuất nháp XKL-5 → ENTRY_NOT_FOUND (không
	dấu chấm); phiếu xuất giữ nháp, L-A giữ 10 (nppsale: ghi sổ phiếu XUẤT thành +5 vào L-A)."""
	mong["buoc"][3] = _loi("ENTRY_NOT_FOUND: không tìm thấy phiếu kiểm kê")
	ct = mong["ct"]
	next(x for x in ct["lo"] if x["ma"] == "L-A")["ton"] = 10.0
	pk = _pk(ct, "XKL-5")
	pk["status"] = "draft"
	pk.pop("luc_ghi_so", None)


def _v64(t, mong):
	_nhap_lo(mong, "Q-1", 5.0)


# ------------------------------------------------------------------------------------------------ M7 — sửa phiếu nhập đã hoàn thành
CHI_SUA_GIA = _loi("PHIEU_DA_XUAT_CHI_SUA_GIA: Lô của phiếu đã xuất ở HD-0001 — chỉ sửa được giá; muốn đổi số lượng / mặt hàng / NCC / kho thì huỷ "
	"các HĐ đã lấy lô hoặc lập phiếu trả hàng NCC / điều chỉnh kho.")


def _ct_sau_sua_gia(ct: dict) -> None:
	"""Ảnh chụp sau bước sửa giá chung của V65–V69 (P: thùng 2 × 264.000, `HD-NCC-9`, ghi chú "sửa giá"; lô 11.000 / tồn 18; nợ 528.000 đã trả 100.000)
	— bước sửa SAU của V67 / V69 bị từ chối nên sổ dừng ở đây (số y như ảnh chụp nppsale của V66)."""
	ct["lo"] = [{"ma": "PN-0001-001", "sp": "@A", "gia": 11000.0, "han": "2099-12-31", "nsx": "@hom_nay", "ton": 18.0, "nhap": 48.0, "vung": "sale",
		"status": "available", "luc_nhan": "@luc_goi"}]
	ct["no"] = [{"luc": "@luc_goi", "ncc": "@S1", "khoa": "PN:PN-0001", "so_hd": "HD-NCC-9", "da_tra": 100000, "dau_ky": False, "status": "partial",
		"ghi_chu": "Phiếu nhập hàng PN-0001", "so_tien": 528000, "phieu_kho": "PN-0001", "luc_bang_hoan_thanh": True}]
	p = ct["pn"][0]
	p.update({"so_hd": "HD-NCC-9", "ghi_chu": "sửa giá", "subtotal": 528000, "total": 528000, "dong": [{"dv": "thùng", "hs": 24, "sl": 2, "sp": "@A",
		"gia": 264000, "stt": 1, "giam": 0, "thue": 0, "tien": 528000}]})
	ct["gia_nhap"] = [{"dv": "thùng", "sp": "@A", "gia": 264000, "ngay": "@hom_nay-46", "nguon": "PN-0001", "sua_boi": "@u:KT"}]
	pk = next(x for x in ct["phieu_kho"] if x["ma"] == "PN-0001")
	pk["dong"] = [{"dv": "thùng", "hs": 24.0, "lo": "PN-0001-001@sale", "sl": 48, "sp": "@A", "gia": 11000.0, "dv_gd": "thùng", "sl_cs": 48.0,
		"sl_gd": 2.0}]


def _v67(t, mong):
	"""⚠K CFD-06 / §7.2 #3 (§3.3 nhánh B): lô của P đã bán → chỉ sửa giá; đổi ĐV thùng → hộp, SL, thêm dòng B → PHIEU_DA_XUAT_CHI_SUA_GIA (mã + câu đề
	xuất §7.3 điểm 7, chờ chốt) — sổ giữ như sau lần sửa giá (nppsale: lô A 30 / tồn 0, lô mới B, nợ 380.000)."""
	mong["buoc"][5] = CHI_SUA_GIA
	_ct_sau_sua_gia(mong["ct"])


def _trang_thai_tra_du(mong, khoa: str = "PN:PN-0001") -> None:
	"""BP §4.3.0 / §7.3 điểm 13 (⚠K): khoản đã trả DƯ (đã trả > số nợ — NCC nợ lại mình) là `open` (một luật với phải thu); nppsale `partial`."""
	next(x for x in mong["ct"]["no"] if x["khoa"] == khoa)["status"] = "open"


def _v69b(t, mong):
	_trang_thai_tra_du(mong)


def _v70(t, mong):
	"""⚠K §3.3 nhánh A (V70): sửa phiếu CHƯA xuất = huỷ + amend — dòng nhập lại theo luật kho nhận lúc nhập (`batches_auto_zone`): đổi kho đầu phiếu về
	kho bán thì A vào kho bán nhưng C (hạn +20, trong ngưỡng 30) VẪN vào kho cận date (nppsale đổi vùng tại chỗ cả lô C về bán — trigger chỉ chạy khi
	chèn / đổi hạn)."""
	ct = mong["ct"]
	next(x for x in ct["lo"] if x["ma"] == "PN-0001-002")["vung"] = "date"
	for d in next(x for x in ct["phieu_kho"] if x["ma"] == "PN-0001")["dong"]:
		if d["lo"] == "PN-0001-002@sale":
			d["lo"] = "PN-0001-002@date"


def _v71(t, mong):
	_trang_thai_tra_du(mong)


# ------------------------------------------------------------------------------------------------ M8 — nhà cung cấp
def _v84(t, mong):
	"""Số phiên danh mục (`danh_muc_ban_phien.phien` ↔ `NPP Phien Danh Muc`) so MỨC TĂNG, không số tuyệt đối (tệp vàng `khac_frappe`): nppsale +2 / +4
	(trigger mức câu lệnh `trg_phien_danh_muc_ban` chạy cho MỖI lệnh UPDATE / DELETE products kể cả 0 dòng — vòng khoá ngoại, hành động ON DELETE SET
	NULL), bản Frappe tăng ở mỗi lần đổi Item (`thay_doi_hang`) + MỘT lần cuối RPC (`gop_nha_cung_cap` / `xoa_nha_cung_cap` — S11 / S12)."""
	dau = True
	for b, m in zip(t["buoc"], mong["buoc"], strict=False):
		if b["buoc"] == "doc_phien":
			m["tra"] = {"phien": "dau" if dau else "tang"}
			dau = False


# ------------------------------------------------------------------------------------------------ M9 — báo cáo, đầu-cuối
def _v74(t, mong):
	"""⚠K (một luật với M4 V53 / M6 V60): cột "nhập" của cổng `batches` = Σ phần VÀO kho của lô → L2 (`PN-0002-001`) 50 + 2 thừa kiểm kê (`DCK-`) + 1 hàng
	khách trả nhập lại (`NL-`) = 53; nppsale giữ `qty_initial` 50. Giá lô L2 vẫn 9.000 ở cả hai (thừa kiểm kê nhập theo giá vốn HIỆN TẠI của lô — M6;
	phiếu nhập lại hàng trả theo giá lô — P3) nên ⚠K "bình quân lại" của đặc tả §6.9 V74 / §7.1 #1 KHÔNG xảy ra — kiểm thêm ở
	nppsale.tests.test_bao_cao_kho (giá vốn HĐ 250.000, kho giảm 45.000 khi trả NCC, chênh 5.000 vào TK chi phí mặc định)."""
	_nhap_lo(mong, "PN-0002-001", 53.0)


def _v75(t, mong):
	"""❓ §7.3 điểm 21 (Q9 — theo đề xuất): `bao_cao_ton_kho.lo.unit_cost` che theo `inventory.cost` như cổng `batches` → NVBH (không có ô ấy) nhận NULL;
	nppsale hàm không che (giao diện che)."""
	for x in mong["buoc"][6]["tra"]["lo"]:
		x["unit_cost"] = None


def _v76(t, mong):
	"""⚠K §7.2 #14: phiếu kho của HĐ = CHÍNH HĐ → dòng `v_stock_movements` của HĐ mang mã HĐ (nppsale phiếu `XK-<giờ>` riêng); ⚠K §3.16: dấu chuyển
	vùng ở cả hai dòng cổng `batches` của lô (như V85)."""
	ma_hd = mong["ct"]["hd"][0]["ma"]
	for x in mong["buoc"][7]["tra"]:
		if x["entry_code"] == "XK-<giờ>":
			x["entry_code"] = ma_hd
	_chuyen_vung(mong, "PN-0001-001")


def _v77(t, mong):
	"""⚠K CFD-13 (một luật với V41 / V51 / V86): nhập kho có NCC + tiền nợ = PHIẾU NHẬP `PN-` → khoản nợ là khoản của phiếu nhập (khoá `PN:`), phiếu
	của nó hiện trong tab "Còn nợ" vì cổng `stock_entries` gồm PI phiếu nhập; mã phiếu trong kết quả tìm so theo nhãn (Frappe cấp `PN-` cho cả hai)."""
	m = mong["buoc"]
	m[7]["tra"]["payable_id"] = "no:PN:<IN1>"
	m[8]["tra"] = sorted({"IN-20261116-2001": "<IN1>", "PN-0001": "<P1>"}[x] for x in m[8]["tra"])
	no = _no(mong["ct"], "PK:IN-20261116-2001:HD01-C")
	no.update({"khoa": "PN:<IN1>", "phieu_kho": "<IN1>", "luc_bang_hoan_thanh": True})


# kịch bản [Frappe] (`nguon: dac_ta` — mong là chữ của đặc tả) → hàm kiểm riêng của lớp bài
KIEM_DAC_TA = {"V02c": "_v02c", "V12b": "_v12b", "V19b": "_v19b", "V43c": "_v43c", "V44c": "_v44c", "V57b": "_v57b", "V80": "_v80"}

LECH: dict[str, tuple] = {
	"V05d": (_v05d, "BP §4.3.0: khoản nợ 0 đ (giảm đầu phiếu nuốt hết tiền) là ĐÃ TRẢ ĐỦ — một luật với phải thu; nppsale chèn dòng `open` amount 0"),
	"V08b": (_v08b, "§7.3 điểm 23: lõi không nhận PI nháp dòng SL 0 (đo M0) → cổng chặn ngay lúc lưu dòng bằng câu của sua_phieu_nhap (nppsale báo lúc "
		"hoàn thành); phiếu P ở lại không dòng → Hoàn thành báo PHIEU_KHONG_CO_HANG"),
	"V12": (_v12, "CFD-05 B / §7.3 điểm 12: hàng theo lô đã xuất không huỷ được phiếu nhập kể cả khi cho bán vượt tồn"),
	"V18": (_v18, "tiền phiếu NHÁP = số lõi tính lại mỗi lần lưu dòng (dựng lại bảng thuế); nppsale giữ số trình duyệt gửi lúc lập đầu phiếu"),
	"V19": (_v19, "CFD-05 B: hàng theo lô không xuất âm — phiếu trả NCC báo INSUFFICIENT_STOCK dù NPP cho bán vượt tồn (nppsale ghi dòng không lô)"),
	"V22": (_v22, "CFD-01: tờ amend nháp không trỏ phiếu kho cũ"),
	"V25": (_v25, "§3.8 / §7.3 điểm 2: sửa phiếu trả đã xuất = RPC sua_phieu_tra_ncc một giao dịch; cổng cấm ghi thẳng status (USE_RPC)"),
	"V26": (_v26, "BP §7.2 điểm 3 tiền làm tròn đồng; BP §4.3.0 nợ 0 đ đã trả đủ; §7.3 điểm 23 dòng SL ≤ 0 / tiền âm bị cổng chặn lúc lưu"),
	"V27": (_v27, "⚠K: cổng bỏ qua return_code / return_seq (tờ Frappe không đổi tên) — không có lỗi trùng seq; số của nháp cuối bị xoá vẫn cấp "
		"lại như nppsale (lõi lùi dãy số)"),
	"V28": (_v28, "BP §6.1: cổng chặn sửa dòng / về nháp / xoá phiếu trả đã xuất (USE_RPC) — nppsale RLS cho ghi thẳng (K25)"),
	"V36": (_v36, "§7.3 điểm 10: Bù trừ = bút toán CTN- trong phạm vi khoản giảm còn mở của phiếu trả NCC (vượt → BU_TRU_KHONG_CON); hình thức "
		"'' / NULL → tiền mặt"),
	"V38": (_v38, "§4.4: số HĐ khoản nợ PN = bill_no của tờ; DA_CAN_TRU dựng bằng bút toán CTN- thay bước máy chủ đặt paid trên dòng âm"),
	"V39": (_v39, "⚠K sửa số nợ đầu kỳ đã trả bị chặn (tờ amend không mang được tiền đã trả)"),
	"V86": (_v86, "⚠K CFD-13: IN- có NCC + tiền là phiếu nhập — xoá nợ của nó 23503, huỷ phiếu kho → ENTRY_HAS_SOURCE (hoá đơn nhập mua)"),
	# M4 — phiếu kho tay
	"V41": (_v41, "⚠K CFD-13: nhập kho có NCC + tiền = phiếu nhập PN- (nợ PN:); §7.3 điểm 6: gọi lại cùng mã → LO_TRUNG_MA (nppsale lô trùng mã)"),
	"V43b": (_v43b, "CFD-05 B: hàng theo lô không âm — cờ bán vượt tồn không áp cho xuất lẻ (nppsale thiếu im lặng)"),
	"V44a": (_v44a, "CFD-05 B: hàng theo lô không lô nào → KHONG_DU_TON (nppsale ghi sổ âm, huỷ NO_CONSUMPTION_TRACE); huỷ nháp = xoá"),
	"V44b": (_v44b, "§7.3 điểm 23: cổng chặn dòng SL ≤ 0 lúc lưu → phiếu không dòng (nppsale nhận dòng âm)"),
	"V45": (_v45, "§7.3 điểm 1: huỷ nháp = xoá nháp → 0 dòng trả về, ghi sổ sau đó PHIEU_KHONG_TON_TAI"),
	"V46": (_v46, "§7.3 điểm 1 huỷ nháp = xoá; ⚠K §4.5 phiếu đã ghi sổ chỉ sửa notes; phiếu kiểm kê thuộc M6"),
	"V47": (_v47, "⚠K §3.16: một Batch cho hai kho — dấu chuyển vùng (lúc + người) ở cả hai dòng cổng batches"),
	"V48": (_v47, "⚠K §3.16: dấu chuyển vùng ở cả hai dòng cổng batches"),
	"V49": (_v47, "⚠K §3.16: dấu chuyển vùng ở cả hai dòng cổng batches"),
	"V50": (_v50, "§7.3 điểm 1: huỷ nháp = xoá → lần hai ENTRY_NOT_FOUND"),
	"V51": (_v51, "⚠K CFD-13: IN- có NCC + tiền là phiếu nhập (ENTRY_HAS_SOURCE hoá đơn nhập mua); §7.2 #26 lô nhập rồi huỷ ra nhập 0"),
	"V52": (_v52, "⚠K §3.16: dấu chuyển vùng ở cả hai dòng cổng batches"),
	"V53": (_v53, "⚠K §7.2 #14: phiếu kho của HĐ / trả NCC / trả khách = chính chứng từ (câu nêu tên chứng từ); nhập lô gồm hàng khách trả"),
	"V54": (_v54, "⚠K §3.19: nguồn theo trường thật, phiếu đã ghi sổ chỉ sửa ghi chú → huỷ được ngay lần đầu"),
	"V55": (_v55, "⚠K §3.16: dấu chuyển vùng ở cả hai dòng cổng batches"),
	"V81": (_v81, "finance_pnl / bao_cao_so_ban thuộc P6 → giá vốn kỳ đọc qua cổng (fetchCogsForRange) — cùng số 130.000"),
	"V85": (_v85, "⚠K §3.16: dấu chuyển vùng ở cả hai dòng cổng batches"),
	# M5 — lô + kho cận date
	"V56b": (_v56b, "⚠K §4.6: sửa hạn vào ngưỡng = phiếu CKL- chuyen_date_tu_dong — dòng kho bán còn lại tồn 0"),
	"V57": (_v57, "⚠K §3.20: rà soát = phiếu CKL- chuyen_date_tu_dong — dòng kho bán còn lại tồn 0"),
	"V58": (_v58, "⚠K §3.20: rà soát = CKL- bán → date; huỷ xuất lẻ trả về kho bán (nơi đã lấy); thẻ kho không đổi vùng hồi tố"),
	"V59": (_v59, "câu 18: mã lô của PN theo nhãn; ⚠K §4.6: sửa hạn vào ngưỡng = CKL- (dòng kho bán tồn 0)"),
	"V82a": (_v82a, "⚠K §4.6 S7: hạn gửi lại không đổi vẫn đổi kho = CKL-; thẻ kho không hồi tố"),
	"V82b": (_v82b, "⚠K §7.2 #27: một Batch cho hai kho — sửa hạn dòng date đổi hạn cả lô, kéo tồn kho bán sang date"),
	"V82d": (_v82d, "❓ §7.3 điểm 37: lô đang có tồn xét theo cả Batch → sửa giá dòng tồn 0 vẫn chặn"),
	# M6 — kiểm kê
	"V60": (_v60, "⚠K: thừa kiểm kê = Material Receipt DCK- → cột nhập của cổng batches gồm phần thừa (L-RONG 2; nppsale qty_initial giữ 0)"),
	"V63": (_v63, "⚠K §3.17 (đóng lỗ V13): duyệt kiểm kê chỉ nhận NPP Kiem Ke → phiếu xuất nháp báo ENTRY_NOT_FOUND, kho không đổi"),
	"V64": (_v64, "⚠K: thừa kiểm kê vào lô rỗng Q-1 = Material Receipt DCK- → cột nhập 5 (nppsale qty_initial giữ 0)"),
	# M7 — sửa phiếu nhập đã hoàn thành
	"V67": (_v67, "⚠K CFD-06 / §7.2 #3: lô đã bán → chỉ sửa giá; đổi ĐV / SL / thêm dòng → PHIEU_DA_XUAT_CHI_SUA_GIA (§7.3 điểm 7)"),
	"V69": (_v67, "⚠K CFD-06 / §7.2 #3: lô đã bán → chỉ sửa giá; đổi thùng → hộp → PHIEU_DA_XUAT_CHI_SUA_GIA (nppsale sửa được — xem V69b)"),
	"V69b": (_v69b, "BP §4.3.0 / §7.3 điểm 13: khoản trả dư (đã trả 100.000 > nợ 80.000) là open — nppsale partial"),
	"V70": (_v70, "⚠K §3.3 nhánh A: amend nhập lại theo luật kho nhận — C hạn trong ngưỡng vẫn vào kho cận date khi đầu phiếu về kho bán"),
	"V71": (_v71, "BP §4.3.0 / §7.3 điểm 13: khoản trả dư sau sửa (đã trả 1.200.000 > nợ 800.000) là open — nppsale partial"),
	# M8 — nhà cung cấp
	"V84a": (_v84, "số phiên danh mục so mức tăng (nppsale +2: trigger mức câu lệnh cho từng lệnh trên products, kể cả 0 dòng)"),
	"V84b": (_v84, "số phiên danh mục so mức tăng (nppsale +4)"),
	# M9 — báo cáo, đầu-cuối
	"V74": (_v74, "⚠K cột nhập của cổng batches gồm thừa kiểm kê + hàng khách trả nhập lại (L2 53; nppsale 50) — giá lô giữ 9.000 ở cả hai"),
	"V75": (_v75, "❓ §7.3 điểm 21: bao_cao_ton_kho che giá vốn lô theo inventory.cost như cổng batches (NVBH NULL)"),
	"V76": (_v76, "⚠K §7.2 #14: dòng lịch sử tồn của HĐ mang mã HĐ; ⚠K §3.16: dấu chuyển vùng ở cả hai dòng cổng batches"),
	"V77": (_v77, "⚠K CFD-13: nhập kho có NCC + tiền là phiếu nhập (khoản PN:) — mã phiếu theo nhãn"),
}


# ------------------------------------------------------------------------------------------------ chuẩn hoá giá trị
def _so(v):
	if isinstance(v, bool) or v is None:
		return v
	if isinstance(v, (int, float)):
		return float(v)
	if isinstance(v, dict):
		return {a: _so(b) for a, b in v.items()}
	if isinstance(v, list):
		return [_so(x) for x in v]
	return v


def _bo_null(d: dict) -> dict:
	"""jsonb_strip_nulls của bộ sinh: khoá mang null bị bỏ."""
	return {k: v for k, v in d.items() if v is not None}


def _gio(v):
	"""Mốc giờ (cổng trả ISO kèm múi giờ site) → datetime không múi giờ theo giờ site."""
	from zoneinfo import ZoneInfo

	from frappe.utils import get_system_timezone

	d = get_datetime(v)
	return d.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None) if d.tzinfo else d


def _dv(v):
	"""Đơn vị tính so KHÔNG phân biệt dấu / hoa thường: UOM của Frappe là bản ghi (khoá `name`, collation utf8mb4_unicode_ci) — "thùng" và "Thung"
	là MỘT đơn vị, tên lưu theo bản ghi có trước (nppsale lưu chữ tự do của từng dòng)."""
	import unicodedata

	if not isinstance(v, str):
		return v
	return "".join(c for c in unicodedata.normalize("NFD", v.replace("đ", "d").replace("Đ", "D")) if unicodedata.category(c) != "Mn").lower()


def _dv_loi(s):
	"""Đơn vị trong câu thiếu tồn của phiếu trả NCC (`INSUFFICIENT_STOCK | <tên> (<đơn vị cơ sở>): cần …`) và câu `DA_XUAT_NHIEU_HON` của sửa phiếu nhập
	(`<tên>: đã xuất <x> <đơn vị cơ sở>, số lượng mới chỉ <y>` — M7) so như `_dv`: Frappe in `stock_uom` (bản ghi UOM có trước — "Hop"), nppsale in
	`products.base_unit` ("hộp"). Phần còn lại của câu vẫn so từng ký tự."""
	if not isinstance(s, str):
		return s
	s = _RE_DA_XUAT.sub(lambda m: m.group(1) + _dv(m.group(2)) + m.group(3), s)
	return _RE_THIEU.sub(lambda m: m.group(1) + _dv(m.group(2)) + m.group(3), s)


def _gap_dv(v):
	"""Gập mọi khoá đơn vị (`dv`, `dv_gd`, `unit_name`, `transaction_uom`) của một giá trị lồng — áp cho cả hai phía trước khi so."""
	if isinstance(v, dict):
		return {k: (_dv(x) if k in ("dv", "dv_gd", "unit_name", "transaction_uom") else _dv_loi(x) if k == "ly_do" else _gap_dv(x)) for k, x in v.items()}
	if isinstance(v, list):
		return _xep([_gap_dv(x) for x in v]) if v and isinstance(v[0], dict) and "stt" not in v[0] else [_gap_dv(x) for x in v]
	return v


def _xep(ds: list) -> list:
	return sorted(ds, key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False))


def _gop_tra_truoc(ds: list) -> list:
	"""⚠K (đặc tả §4.4): phần chưa phân bổ của một phiếu chi là MỘT dòng `<PE>::tra_truoc` — nppsale có thể giữ nhiều dòng `payable_payments` trên dòng
	trả trước (phần dồn đi rồi trả về khi huỷ phiếu nhập — `_tra_phan_bo_ve_truoc` chuyển nguyên dòng): gộp các dòng `TT:` cùng phiếu chi, cộng tiền.
	M7 (sửa phiếu nhập nhánh amend): tiền MỘT phiếu tiền trên một khoản có thể là hai dòng cổng — tham chiếu phiếu tiền (phần vừa tờ mới) + vế bút toán
	chuyển tiền trả dư `chuyen_tra_du_ncc` (cùng hình thức / người / lúc chi / ghi chú / phiếu chi), nppsale MỘT dòng giữ nguyên → gộp mọi dòng cùng
	danh tính (mọi trường trừ tiền), áp CẢ HAI phía."""
	gop: dict = {}
	ra = []
	for x in ds:
		k = json.dumps({a: b for a, b in x.items() if a != "tien"}, sort_keys=True, ensure_ascii=False)
		if k in gop:
			gop[k]["tien"] = flt(gop[k]["tien"]) + flt(x["tien"])
		else:
			gop[k] = dict(x)
			ra.append(gop[k])
	return ra


_RE_NGAY_LOI = re.compile(r"<@hom_nay([+-]\d+)?>")


def _ngay_trong_loi(chu: str) -> str:
	"""Chỗ giữ ngày trong câu lỗi của tệp vàng ("hạn <@hom_nay+10>" — `HANG_GAN_HAN`) → ngày thật DD/MM/YYYY (giờ VN của site)."""
	return _RE_NGAY_LOI.sub(lambda m: add_days(XH.hom_nay(), int(m.group(1) or 0)).strftime("%d/%m/%Y"), chu or "")


def _gio_trong_loi(chu: str) -> str:
	"""Giờ ghi sổ trong câu lỗi của bản Frappe (`ALREADY_POSTED: … lúc HH:MI DD/MM/YYYY` — giờ VN của site) → "<HH:MI @hom_nay±n>" như `chuan_loi` của
	bộ sinh (giờ phụ thuộc lúc chạy)."""
	def doi(m):
		n = (getdate(f"{m.group(5)}-{m.group(4)}-{m.group(3)}") - XH.hom_nay()).days
		return "<HH:MI @hom_nay" + (f"{n:+d}" if n else "") + ">"

	return _RE_GIO_NGAY.sub(doi, chu or "")


def _thay_ma(chu: str, bang: dict) -> str:
	"""Thay mã / tên chứng từ (cả từ — không ăn vào mã dài hơn) bằng nhãn, MỘT lượt (nhãn đã thay không bị quét lại)."""
	if not bang or not chu:
		return chu
	mau = re.compile(r"(?<![\w-])(" + "|".join(re.escape(m) for m in sorted(bang, key=len, reverse=True)) + r")(?![\w-])")
	return mau.sub(lambda m: bang[m.group(1)], chu)


# ------------------------------------------------------------------------------------------------ bộ dữ liệu F (§6.0)
def dung_nen_kho(nen: dict) -> dict:
	"""Người (NPP A), NCC, mặt hàng (theo lô trừ X — câu 14 B), khách, giá bán; cờ bán vượt tồn / ngưỡng kho date như nền."""
	from nppsale.rpc.don_hang import _dam_bao_uom
	from nppsale.su_kien.san_pham import bang_gia_chung

	ma = {}
	for i, (k, (vai, npp)) in enumerate(nen["nguoi"].items()):
		if npp != "A":
			continue
		sdt = f"0918{700000 + i:06d}"
		email = email_ky_thuat(sdt)
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": k, "send_welcome_email": 0}).insert(ignore_permissions=True)
		if not frappe.db.exists("NPP Nhan Vien", email):
			frappe.get_doc({"doctype": "NPP Nhan Vien", "user": email, "ho_ten": k, "vai": vai, "sdt": sdt, "dang_hoat_dong": 1}).insert(
				ignore_permissions=True)
		ma["u:" + k] = email
	nhom_ncc = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
	for k, (ten, ma_ncc, npp, them) in nen["ncc"].items():
		if npp != "A":
			continue
		ma[k] = frappe.get_doc({"doctype": "Supplier", "supplier_name": ten, "supplier_group": nhom_ncc, "npp_ma": ma_ncc,
			"npp_dien_thoai": them.get("phone"), "tax_id": them.get("tax_code"), "supplier_details": them.get("notes")}).insert(
			ignore_permissions=True).name
		if them.get("email"):  # "hai@ncc" của nền: trường Email của Frappe kiểm dạng — nppsale lưu chữ tự do
			frappe.db.set_value("Supplier", ma[k], "npp_email", them["email"], update_modified=False)
	nhom_hang = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	hang = {k: (*v, {}) for k, v in nen["hang"].items()} | nen.get("hang_frappe", {})
	cong_ty = frappe.db.get_single_value("NPP Cai Dat", "cong_ty")
	for k, (sku, ten, dv, han, dvs, ncc_chinh, them) in hang.items():
		for u in [dv, *dvs]:
			_dam_bao_uom(u)
		co_lo = them.get("has_batch_no", 1)
		if not frappe.db.exists("Item", sku):
			frappe.get_doc({"doctype": "Item", "item_code": sku, "item_name": ten, "item_group": nhom_hang, "stock_uom": dv, "is_stock_item": 1,
				"has_batch_no": co_lo, "create_new_batch": 0, "has_expiry_date": 1 if (co_lo and han) else 0, "shelf_life_in_days": han or 0,
				"allow_negative_stock": them.get("allow_negative_stock", 0), "npp_thue_suat": 0,
				"uoms": [{"uom": u, "conversion_factor": h} for u, h in dvs.items()]}).insert(ignore_permissions=True)
		ma[k] = sku
		if ncc_chinh and ncc_chinh in ma:  # NCC chính (`products.primary_supplier_id` — §6.0) = `Item Default.default_supplier` của công ty (M8)
			it = frappe.get_doc("Item", sku)
			dong = next((d for d in it.get("item_defaults") or [] if d.company == cong_ty), None) or it.append("item_defaults", {"company": cong_ty})
			dong.default_supplier = ma[ncc_chinh]
			it.save(ignore_permissions=True)
	nhom_khach = "VTD Khong Nhom"
	if not frappe.db.exists("Customer Group", nhom_khach):
		frappe.get_doc({"doctype": "Customer Group", "customer_group_name": nhom_khach, "parent_customer_group": "All Customer Groups",
			"is_group": 0}).insert(ignore_permissions=True)
	for i, (k, ten) in enumerate(nen["khach"].items()):
		ma[k] = frappe.db.get_value("Customer", {"customer_name": ten}, "name") or frappe.get_doc({"doctype": "Customer", "customer_name": ten,
			"customer_type": "Company", "customer_group": nhom_khach, "npp_sdt": f"09187900{i + 1:02d}"}).insert(ignore_permissions=True).name
	for sp, dv, gia in nen["gia_ban"]:
		if not frappe.db.exists("Item Price", {"item_code": ma[sp], "price_list": bang_gia_chung(), "uom": dv}):
			frappe.get_doc({"doctype": "Item Price", "item_code": ma[sp], "price_list": bang_gia_chung(), "uom": dv, "price_list_rate": gia}).insert(
				ignore_permissions=True)
	if frappe.db.exists("DocType", "NPP Danh Muc Chi Phi"):  # danh mục chi phí của NPP A (hao hụt kiểm kê ghi vào COGS_ADJ — M6)
		for ma_dm, ten, nhom in nen.get("danh_muc_chi_phi") or []:
			if not frappe.db.exists("NPP Danh Muc Chi Phi", {"ma": ma_dm}):
				frappe.get_doc({"doctype": "NPP Danh Muc Chi Phi", "ma": ma_dm, "ten": ten, "nhom": nhom, "dang_dung": 1}).insert(ignore_permissions=True)
	frappe.db.set_single_value("NPP Cai Dat", {"cho_ban_vuot_ton": 1 if nen["cho_ban_vuot_ton"] else 0,
		"nguong_kho_date_ngay": nen["nguong_kho_date_ngay"]})
	frappe.local._npp_cai_dat_ban = None
	ma["org"] = frappe.db.get_single_value("NPP Cai Dat", "org_id")
	return ma


def dung_lo(ma: dict, cd, b: dict) -> str:
	"""Lô dựng sẵn (bước `lo` của tệp vàng — nppsale INSERT batches bằng quyền máy chủ; dùng chung với nppsale.tests.test_tra_ncc): Batch (hạn,
	ngày SX, ngày nhận 08:00 VN, kho tạo, vị trí) + phiếu nhập kho Material Receipt có gói lô ghi LÙI về ngày nhận, giá = giá lô; `nhap` > `ton` →
	phiếu xuất phần chênh (lô đã dùng bớt)."""
	from nppsale.rpc.goi_lo import gan_goi_lo, kho_cua_vung, lap_goi_lo

	sp = ma[b["sp"][1:]]
	kho = kho_cua_vung(b["vung"], cd)
	hn = XH.hom_nay()
	ngay = add_days(hn, b["nhan_ngay"])
	nhap = b["ton"] if b.get("nhap") is None else b["nhap"]
	lo = frappe.get_doc({"doctype": "Batch", "batch_id": b["ma"], "item": sp, "expiry_date": add_days(hn, b["han"]) if b.get("han") is not None
		else None, "manufacturing_date": add_days(hn, b["nsx"]) if b.get("nsx") is not None else None, "npp_ngay_nhap": f"{ngay} 08:00:00",
		"npp_kho_tao": kho, "npp_vi_tri": b.get("vi_tri")}).insert(ignore_permissions=True)
	# nppsale: ngày SX NULL khi không gửi (lõi tự điền hôm nay — before_save); lúc tạo = ngày tạo 08:00 (thứ tự hoà hạn của FEFO)
	frappe.db.set_value("Batch", lo.name, {"manufacturing_date": add_days(hn, b["nsx"]) if b.get("nsx") is not None else None,
		"creation": f"{add_days(hn, b.get('tao_ngay', b['nhan_ngay']))} 08:00:00"}, update_modified=False)
	dv = frappe.db.get_value("Item", sp, "stock_uom")
	for loai, sl, gio in (("Inward", nhap, "08:00:00"), ("Outward", nhap - b["ton"], "08:00:01")):
		if sl <= 0:
			continue
		kho_se = {"t_warehouse": kho} if loai == "Inward" else {"s_warehouse": kho}
		se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt" if loai == "Inward" else "Material Issue",
			"company": cd.cong_ty, "posting_date": ngay, "posting_time": gio, "set_posting_time": 1,
			"items": [{"item_code": sp, "qty": sl, "uom": dv, "conversion_factor": 1, "basic_rate": b["gia"], **kho_se}]})
		gan_goi_lo(se.items[0], lap_goi_lo(loai, "Stock Entry", sp, kho, {lo.name: sl}, ngay, gio, cd.cong_ty))
		se.insert(ignore_permissions=True)
		se.submit()
	return lo.name


class TestKhoMuaVang(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		B.nap()
		with open(VANG, encoding="utf-8") as f:
			cls.vang = json.load(f)

	def setUp(self):
		frappe.db.savepoint("npp_test")
		# commit thật làm mất điểm lui (dữ liệu bài nằm lại sổ — sự cố M0); Error Log là MyISAM; việc repost nền không đẩy vào Redis
		self.nhat_ky, self.repost = [], []
		for p in (patch.object(frappe.db, "commit", lambda *a, **k: None),
				patch.object(frappe, "log_error", lambda title=None, message=None, **k: self.nhat_ky.append(title)),
				patch("nppsale.rpc.phieu_nhap._xep_repost", lambda: self.repost.append(1))):
			p.start()
			self.addCleanup(p.stop)
		frappe.local._npp_cai_dat_ban = None
		self.cd = cai_dat_kho()
		self.co_san = {dt: set(frappe.get_all(dt, pluck="name")) for dt in ("Purchase Invoice", "Batch", "NPP Cong No NCC", "Sales Invoice", "Supplier",
			"Item Price", "Payment Entry", "Stock Entry", "Stock Ledger Entry", "NPP Phieu Chi", "NPP Kiem Ke")}
		self.ma = dung_nen_kho(self.vang["nen"])
		self.khoa_cua = {v: "@" + k for k, v in self.ma.items()}  # tên Frappe → khoá nền (@A, @S1, @u:TK)
		self.vung = {self.cd.kho_ban: "sale", self.cd.kho_can_date: "date"}

	def tearDown(self):
		frappe.db.rollback(save_point="npp_test")
		frappe.set_user("Administrator")
		frappe.local._npp_cai_dat_ban = None
		frappe.local._npp_ngu_canh = None

	# ------------------------------------------------------------------------------------------------ gọi dưới đúng người
	def _nguoi(self, nguoi: str):
		frappe.set_user(self.ma["u:" + nguoi])
		frappe.local._npp_ngu_canh = None

	def _ve_admin(self):
		frappe.set_user("Administrator")
		frappe.local._npp_ngu_canh = None
		frappe.local._npp_cai_dat_ban = None

	def _goi(self, nguoi: str, ten: str, ts: dict) -> dict:
		self._nguoi(nguoi)
		try:
			return api.rpc(ten=ten, tham_so=ts)
		finally:
			self._ve_admin()

	def _cong(self, nguoi: str, yc: dict) -> dict:
		self._nguoi(nguoi)
		try:
			return api.truy_van(yeu_cau=yc)
		finally:
			self._ve_admin()

	# ------------------------------------------------------------------------------------------------ chỗ giữ + nhãn
	def _thay(self, v, st: dict):
		"""Chỗ giữ của tải trọng → giá trị trên site: "@org", "@A", "@S1", "@u:TK", "@pn:<nhãn>", "@ptn:<nhãn>", "@hom_nay±n"."""
		if isinstance(v, str):
			if v == "@org":
				return self.ma["org"]
			if v == "@la":
				return LA
			m = _RE_HOM_NAY.match(v)
			if m:  # "@hom_nay±n" → ngày VN; "@hom_nay±nTHH:MM:SS+07:00" → mốc giờ (cùng luật `thuc` của bộ sinh)
				return str(add_days(XH.hom_nay(), int(m.group(1) or 0))) + (m.group(2) or "")
			if v.startswith(("@pn:", "@ptn:", "@pk:", "@pc:")):
				return self._ten(st, v[1:])
			if v.startswith("@no:"):
				return self._dong_no(st, v[4:])
			if v.startswith("@lo:"):
				return self._id_lo(st, v[4:])
			if v.startswith("@"):
				return self.ma.get(v[1:], v)
			return v
		if isinstance(v, dict):
			return {a: self._thay(b, st) for a, b in v.items()}
		if isinstance(v, list):
			return [self._thay(x, st) for x in v]
		return v

	@staticmethod
	def _cuoi(ten: str | None) -> str | None:
		"""Tờ cuối của chuỗi amend (CFD-01)."""
		for _ in range(50):
			x = frappe.db.get_value("Purchase Invoice", {"amended_from": ten}, "name", order_by="creation desc") if ten else None
			if not x:
				return ten
			ten = x
		return ten

	@staticmethod
	def _goc(ten: str | None) -> str | None:
		for _ in range(50):
			x = frappe.db.get_value("Purchase Invoice", ten, "amended_from") if ten else None
			if not x:
				return ten
			ten = x
		return ten

	def _ten(self, st: dict, nhan: str) -> str | None:
		"""Nhãn → tên Frappe của tờ CÒN HIỆU LỰC (tờ cuối chuỗi amend)."""
		goc = st["nhan"].get(nhan)
		return self._cuoi(goc) if nhan.split(":", 1)[0] in LOAI_CT else goc

	def _dong_no(self, st: dict, k: str) -> str | None:
		"""Chỗ giữ dòng công nợ NCC (bộ sinh `_vp4_id`): "pn|ptn:<nhãn>" dòng của phiếu, "dk:<NCC>" nợ đầu kỳ, "ma:<số HĐ>" theo số HĐ NCC, "pk:<nhãn>"
		dòng gắn phiếu kho, "tt:<nhãn phiếu chi>" dòng trả trước."""
		loai, _, nhan = k.partition(":")
		if loai in ("pn", "ptn"):
			return frappe.db.get_value("NPP Cong No NCC", {"chung_tu": self._ten(st, f"{loai}:{nhan}")}, "name")
		if loai == "dk":
			return frappe.db.get_value("NPP Cong No NCC", {"nha_cung_cap": self.ma[nhan], "loai": "dau_ky"}, "name")
		if loai == "ma":
			return frappe.db.get_value("NPP Cong No NCC", {"so_hd_ncc": nhan}, "name", order_by="tao_luc asc, name asc")
		if loai == "pk":  # nợ lập tay gắn phiếu kho; phiếu nhập kho có NCC + nợ là PHIẾU NHẬP (CFD-13) → dòng nợ của chính tờ
			ten = st["nhan"].get("pk:" + nhan)
			return (frappe.db.get_value("NPP Cong No NCC", {"phieu_kho": ten}, "name")
				or frappe.db.get_value("NPP Cong No NCC", {"chung_tu": ten}, "name")) if ten else None
		if loai == "tt":
			ten = st["nhan"].get("pc:" + nhan)
			return frappe.db.get_value("NPP Cong No NCC", {"phieu_chi": ten, "loai": "tra_truoc"}, "name") if ten else None
		raise ValueError(f"chỗ giữ dòng nợ lạ: @no:{k}")

	def _id_lo(self, st: dict, k: str) -> str | None:
		"""Chỗ giữ lô "@lo:<mã>[@vùng]" (bộ sinh `_vp4_id`: dòng `batches` cùng mã — đúng vùng nếu có — tạo sớm nhất) → id cổng `<lô>::<vùng>`; "<pn:P>"
		trong mã = tên Frappe của phiếu nhập nhãn P (gốc chuỗi amend — lô `<PN gốc>-NNN`). Không vùng: nppsale một dòng lô (vùng HIỆN TẠI — trigger /
		rà soát lật cờ tại chỗ) ↔ dòng cổng còn tồn nhiều nhất của Batch, hoà thì dòng kho bán (dòng tạo trước)."""
		ma, _, vung = k.partition("@")
		m = re.match(r"<pn:([^>]+)>", ma)
		if m:
			ma = "-".join(str(self._goc(st["nhan"].get("pn:" + m.group(1)))).split("-")[:2]) + ma[m.end():]
		ds = doc_cong({"bang": "batches", "select": "id, warehouse_zone, qty_on_hand", "loc": [{"op": "eq", "cot": "batch_code", "gt": ma}]},
			ADMIN)["data"]
		if vung:
			ds = [r for r in ds if r["warehouse_zone"] == vung]
		ds.sort(key=lambda r: (-flt(r["qty_on_hand"]), r["warehouse_zone"] != "sale"))
		return ds[0]["id"] if ds else None

	def _khoa_no(self, st: dict, ten_dong: str | None) -> str | None:
		"""Khoá nghiệp vụ của một dòng công nợ NCC — cùng dạng `_vp4_khoa_no` của bộ sinh: PN:<nhãn> | PTNCC:<nhãn> | DK:<NCC> | TT:<nhãn phiếu
		chi> | PK:<phiếu kho>[:<số HĐ>] | TAY:<số HĐ>."""
		r = frappe.db.get_value("NPP Cong No NCC", ten_dong, ["loai", "chung_tu", "phieu_chi", "nha_cung_cap", "so_hd_ncc", "phieu_kho"],
			as_dict=True) if ten_dong else None
		if not r:
			return None
		if r.loai == "phieu_nhap":
			return f"PN:{self._ma_pn(st, r.chung_tu)}"
		if r.loai == "tra_ncc":
			return f"PTNCC:{self._ma_pn(st, r.chung_tu)}"
		if r.loai == "dau_ky":
			return "DK:" + str(self.khoa_cua.get(r.nha_cung_cap, r.nha_cung_cap))
		if r.loai == "tra_truoc":
			return f"TT:{self._ma_pn(st, r.phieu_chi)}"
		if r.phieu_kho:
			return f"PK:{self._ma_pn(st, r.phieu_kho)}" + (f":{r.so_hd_ncc}" if r.so_hd_ncc else "")
		return f"TAY:{r.so_hd_ncc or ''}"

	def _nhan_ct(self, st: dict, ten: str | None, loai: str) -> str | None:
		"""Nhãn của tờ (theo tờ gốc chuỗi amend). Hai nhãn cùng tên tờ = phiếu nháp số lớn nhất bị xoá rồi số được cấp lại cho phiếu lập sau
		(lõi lùi dãy số khi xoá tờ số cuối — `frappe/model/delete_doc.py:253`, như `_danh_so_tra_ncc` mig 240) → nhãn SAU thắng."""
		goc = self._goc(ten)
		return next((k[len(loai) + 1:] for k, v in reversed(st["nhan"].items()) if k.startswith(loai + ":") and v == goc), None)

	def _nhan_pn(self, st: dict, ten: str | None) -> str | None:
		return self._nhan_ct(st, ten, "pn")

	def _nhan_ptn(self, st: dict, ten: str | None) -> str | None:
		return self._nhan_ct(st, ten, "ptn")

	def _ma_pn(self, st: dict, ten: str | None):
		"""Tên một tờ của chuỗi (phiếu nhập / phiếu trả NCC) / một phiếu chi NCC / phiếu kho dựng nền → "<nhãn>" (tờ ngoài kịch bản giữ tên)."""
		n = self._nhan_pn(st, ten) or self._nhan_ptn(st, ten) or self._nhan_ct(st, ten, "pc") or self._nhan_ct(st, ten, "pk")
		return f"<{n}>" if n else ten

	def _ma_lo(self, st: dict, ma: str | None):
		m = re.fullmatch(r"(.+)-(\d{3})", ma or "")
		if m and self._nhan_pn(st, m.group(1)):
			return f"<{self._nhan_pn(st, m.group(1))}>-{m.group(2)}"
		return ma

	def _chu_ma(self, st: dict, chu: str | None):
		"""Mã phiếu trong câu chữ (ghi chú công nợ…) → "<nhãn>" — tên dài (tờ amend) thay trước."""
		if not chu:
			return chu
		ten = sorted({x for v in st["nhan"].values() if v for x in frappe.get_all("Purchase Invoice",
			filters={"name": ("like", f"{v}%")}, pluck="name")} | {v for k, v in st["nhan"].items() if v and k.startswith("pc:")},
			key=len, reverse=True)
		for x in ten:
			n = self._ma_pn(st, x)
			if n != x:
				chu = re.sub(rf"(?<![\w-]){re.escape(x)}(?![\w-])", n, chu)
		return chu

	def _luc(self, v):
		if not v:
			return None
		d = _gio(v)
		if abs((now_datetime() - d).total_seconds()) < 3 * 3600:
			return "@luc_goi"
		n = (d.date() - XH.hom_nay()).days
		return f"@hom_nay{n:+d}T{d:%H:%M}" if n else f"@hom_nayT{d:%H:%M}"

	@staticmethod
	def _ngay(v):
		if not v:
			return None
		d = getdate(v)
		n = (d - XH.hom_nay()).days
		if abs(n) > 400:
			return str(d)
		return "@hom_nay" if n == 0 else f"@hom_nay{n:+d}"

	# ------------------------------------------------------------------------------------------------ một bước
	def _buoc(self, b: dict, st: dict) -> tuple[dict, object]:
		"""→ (kết quả cổng {data} | {error}, số trả về đã chuẩn hoá để so `tra` — None khi bước không trả gì)."""
		k = b["buoc"]
		if k == "pn":
			ket = self._cong(b["nguoi"], {"bang": "purchase_invoices", "hanh_dong": "insert", "gia_tri": self._thay(b["dau"], st), "select": "id"})
			if "error" in ket:
				return ket, None
			st["nhan"]["pn:" + b["nhan"]] = ket["data"][0]["id"]
			return self._ghi_dong(b, st), None
		if k == "pn_dong":
			ten = self._ten(st, "pn:" + b["nhan"])
			ket = self._cong(b["nguoi"], {"bang": "purchase_invoice_lines", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "invoice_id",
				"gt": ten}]})
			return (ket if "error" in ket else self._ghi_dong(b, st)), None
		if k in ("pn_hoan", "pn_huy", "pn_khoi_phuc"):
			ten = {"pn_hoan": "complete_purchase_invoice", "pn_huy": "cancel_purchase_invoice", "pn_khoi_phuc": "khoi_phuc_phieu_nhap"}[k]
			ts = {"p_invoice_id": self._ten(st, "pn:" + b["nhan"])}
			if k == "pn_huy":
				ts["p_reason"] = b.get("ly_do")
			ket = self._goi(b["nguoi"], ten, ts)
			if "error" in ket:
				return ket, None
			r = ket["data"]
			if isinstance(r, dict):
				return ket, {**r, "id": "pn:" + (self._nhan_pn(st, r.get("id")) or "?")}
			return ket, "pn:" + (self._nhan_pn(st, r) or "?")
		if k == "pn_sua":  # M7 — sửa phiếu nhập đã hoàn thành (tờ cuối chuỗi amend; `id` trả về = tờ còn hiệu lực → nhãn)
			ts = {"p_invoice_id": self._ten(st, "pn:" + b["nhan"]), "p_head": self._thay(b.get("dau") or {}, st),
				"p_lines": self._thay(b.get("dong") or [], st)}
			ket = self._goi(b["nguoi"], "sua_phieu_nhap", ts)
			if "error" in ket:
				return ket, None
			return ket, {**ket["data"], "id": "pn:" + (self._nhan_pn(st, ket["data"].get("id")) or "?")}
		if k == "gia":
			ket = self._goi(b["nguoi"], "luu_gia_nhap", {"p_dong": self._thay(b.get("p_dong"), st)})
			return ket, None if "error" in ket else ket["data"]
		if k == "doc_bang":
			cot = b.get("cot")
			yc = {"bang": b["bang"], "select": ", ".join([*cot, "__id:id"]) if cot else "*",
				"loc": [{"op": "eq", "cot": c, "gt": self._thay(v, st)} for c, v in (b.get("loc") or {}).items()]}
			ket = self._cong(b["nguoi"], yc)
			if "error" in ket:
				return ket, None
			cu = set().union(*self.co_san.values())  # dòng có sẵn trên site (dữ liệu dựng thử cũ) không thuộc kịch bản
			if b["bang"] == "batches":  # id cổng `<lô>::<vùng>` — lô có sẵn theo mã; lô ảo `~SKU::vùng` (hàng không lô của site) nppsale không có
				ds = [r for r in ket["data"] if not str(r.get("__id") or r.get("id")).startswith("~")
					and str(r.get("__id") or r.get("id")).rpartition("::")[0] not in self.co_san["Batch"]]
			else:
				ds = [r for r in ket["data"] if (r.get("__id") or r.get("id")) not in cu]
			return ket, _xep([self._chuan_dong({c: v for c, v in r.items() if c != "__id"}, st) for r in ds])
		if k == "dem":
			# đếm dòng người gọi đọc được — trừ dòng có sẵn trên site (dữ liệu dựng thử cũ) như `doc_bang`
			ket = self._cong(b["nguoi"], {"bang": b["bang"], "select": "id",
				"loc": [{"op": "eq", "cot": c, "gt": self._thay(v, st)} for c, v in (b.get("loc") or {}).items()]})
			cu = set().union(*self.co_san.values())
			return ket, None if "error" in ket else {"so": len([r for r in ket["data"] if r["id"] not in cu])}
		if k == "ghi":
			yc = {"bang": b["bang"], "hanh_dong": b["hanh_dong"], "select": "id",
				"loc": [{"op": "eq", "cot": c, "gt": self._thay(v, st)} for c, v in (b.get("loc") or {}).items()]}
			if b["hanh_dong"] != "delete":
				yc["gia_tri"] = self._thay(b.get("gia_tri"), st)
			ket = self._cong(b["nguoi"], yc)
			if "error" not in ket and b["bang"] == "suppliers" and b["hanh_dong"] == "insert":
				# NCC lập trong kịch bản mang chỗ giữ của bộ sinh ("id": "@S5") — Frappe đặt tên `NCC-####` (id gửi lên bị bỏ): ghi nhận khoá cho các bước sau
				gt = b.get("gia_tri")
				for g, r in zip(gt if isinstance(gt, list) else [gt], ket.get("data") or [], strict=False):
					if str(g.get("id") or "").startswith("@"):
						self.ma[g["id"][1:]] = r["id"]
						self.khoa_cua[r["id"]] = g["id"]
			return ket, None if "error" in ket else {"so_dong": len(ket.get("data") or [])}
		if k == "co_am":
			frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 1 if b.get("bat", True) else 0)
			frappe.local._npp_cai_dat_ban = None
			return {"data": None}, None
		if k == "nguong":
			frappe.db.set_single_value("NPP Cai Dat", "nguong_kho_date_ngay", b["ngay"])
			frappe.local._npp_cai_dat_ban = None
			return {"data": None}, None
		if k == "ban":
			return self._ban(b, st)
		if k == "huy_hd":
			ket = self._goi(b["nguoi"], "cancel_invoice", {"p_invoice_id": st["nhan"].get("hd:" + b["nhan"]), "p_reason": b.get("ly_do")})
			if "error" in ket:
				return ket, None
			r = ket["data"][0]
			return ket, {"order_status": r.get("order_status"), "import_entry_id": bool(r.get("import_entry_id"))}
		# ------------------------------------------------------------------ M2 — trả NCC
		if k == "lo":
			self._lo(b)
			return {"data": None}, None
		if k == "dong_lo":  # nppsale batches.status 'cancelled' ↔ Batch.disabled
			frappe.db.set_value("Batch", b["lo"], "disabled", 1, update_modified=False)
			return {"data": None}, None
		if k == "ptn":
			ket = self._cong(b["nguoi"], {"bang": "supplier_returns", "hanh_dong": "insert", "gia_tri": self._thay(b["dau"], st), "select": "id"})
			if "error" in ket:
				return ket, None
			st["nhan"]["ptn:" + b["nhan"]] = ket["data"][0]["id"]
			return self._ghi_dong_ptn(b, st), None
		if k == "ptn_dong":
			ten = self._ten(st, "ptn:" + b["nhan"])
			ket = self._cong(b["nguoi"], {"bang": "supplier_return_lines", "hanh_dong": "delete", "loc": [{"op": "eq", "cot": "return_id",
				"gt": ten}]})
			return (ket if "error" in ket else self._ghi_dong_ptn(b, st)), None
		if k in ("ptn_gui", "ptn_huy", "ptn_khoi_phuc", "ptn_sua"):
			ten = {"ptn_gui": "complete_supplier_return", "ptn_huy": "cancel_supplier_return", "ptn_khoi_phuc": "khoi_phuc_phieu_tra_ncc",
				"ptn_sua": "sua_phieu_tra_ncc"}[k]
			nhan = b["nhan"]
			ts = {"p_return_id": self._thay(nhan, st) if nhan.startswith("@") else self._ten(st, "ptn:" + nhan)}
			if k == "ptn_huy":
				ts["p_reason"] = b.get("ly_do")
			if k == "ptn_sua":
				ts.update({"p_head": self._thay(b.get("dau") or {}, st), "p_lines": self._thay(b.get("dong") or [], st), "p_reason": b.get("ly_do"),
					"p_chi_luu_nhap": b.get("chi_luu_nhap")})
			ket = self._goi(b["nguoi"], ten, ts)
			if "error" in ket:
				return ket, None
			r = ket["data"]
			if isinstance(r, dict):
				return ket, {**r, "id": "ptn:" + (self._nhan_ptn(st, r.get("id")) or "?")}
			return ket, "ptn:" + (self._nhan_ptn(st, r) or "?")
		if k == "doc" and b.get("ten") == "lo_theo_phieu_goc":
			return self._lo_theo_phieu_goc(b, st)
		# ------------------------------------------------------------------ M3 — công nợ + tiền NCC
		if k == "chi":
			ts = {"p_supplier_id": self._thay(b["ncc"], st), "p_amount": b["tien"], "p_method": b.get("cach"), "p_notes": b.get("ghi_chu"),
				"p_reference": b.get("tham_chieu")}
			if b.get("ngay") is not None:
				ts["p_paid_date"] = self._thay(b["ngay"], st)
			ket = self._goi(b["nguoi"], "chi_tra_ncc", ts)
			if "error" in ket:
				return ket, None
			st["nhan"]["pc:" + b["nhan"]] = ket["data"]["id"]
			return ket, self._tra_pc(st, ket["data"])
		if k == "huy_chi":
			ket = self._goi(b["nguoi"], "huy_phieu_chi_ncc", {"p_id": self._ten(st, "pc:" + b["nhan"]), "p_reason": b.get("ly_do")})
			return ket, None if "error" in ket else self._tra_pc(st, ket["data"])
		if k == "ghi_tra":
			ket = self._goi(b["nguoi"], "record_payable_payment", {"p_payable_id": self._thay(b["no"], st), "p_amount": b["tien"],
				"p_method": b.get("cach"), "p_notes": b.get("ghi_chu")})
			if "error" in ket:
				return ket, None
			r = ket["data"][0]
			dong = doc_cong({"bang": "payable_payments", "select": "payable_id", "loc": [{"op": "eq", "cot": "id", "gt": r["payment_id"]}]},
				ADMIN)["data"]
			return ket, {**r, "payment_id": "tra:" + str(self._khoa_no(st, dong[0]["payable_id"] if dong else None))}
		if k == "doc" and b.get("ten") in ("payables_summary", "payables_by_supplier"):
			ts = self._thay(b.get("ts") or {}, st)
			ket = self._goi(b["nguoi"], b["ten"], ts)
			if "error" in ket:
				return ket, None
			if b["ten"] == "payables_by_supplier":  # site có sẵn NCC ngoài bộ dữ liệu (dữ liệu demo) — chỉ so dòng của NCC nền
				ncc = {v for kk, v in self.ma.items() if re.fullmatch(r"S\d", kk)}
				return ket, [{c: (self.khoa_cua.get(v, v) if c == "supplier_id" else v) for c, v in r.items()} for r in ket["data"]
					if r["supplier_id"] in ncc]
			mo, thang = self._tong_no_co_san(b["nguoi"], ts.get("p_since"))
			return ket, [{"open_payables": flt(r["open_payables"]) - mo, "month_total": flt(r["month_total"]) - thang} for r in ket["data"]]
		if k == "kham_ncc":
			return {"data": None}, self._kham_ncc()
		# ------------------------------------------------------------------ M4 — phiếu kho tay
		if k == "nhap_kho":
			ket = self._goi(b["nguoi"], "post_stock_import", {"p": self._thay(b["p"], st)})
			if "error" in ket:
				return ket, None
			r = ket["data"][0]
			st["nhan"]["pk:" + b["nhan"]] = r["entry_id"]
			# `entry_id` bỏ như kết quả HĐ (`_chuan_tra`); mã phiếu → nhãn (Frappe cấp `IN-…` / `PN-` — mã trình duyệt gửi chỉ còn ở tên lô)
			return ket, {"entry_code": f"<{b['nhan']}>" if r.get("entry_code") == r.get("entry_id") else r.get("entry_code"),
				"payable_id": ("no:" + str(self._khoa_no(st, r["payable_id"]))) if r.get("payable_id") else None,
				"lines_written": r.get("lines_written")}
		if k == "pk":
			ket = self._cong(b["nguoi"], {"bang": "stock_entries", "hanh_dong": "insert", "gia_tri": self._thay(b["dau"], st), "select": "id"})
			if "error" in ket:
				return ket, None
			ten = ket["data"][0]["id"]
			st["nhan"]["pk:" + b["nhan"]] = ten
			dong = [{**self._thay(d, st), "entry_id": ten} for d in b.get("dong") or []]
			if not dong:
				return ket, None
			return self._cong(b["nguoi"], {"bang": "stock_entry_lines", "hanh_dong": "insert", "gia_tri": dong, "select": "id"}), None
		if k in ("xuat_le", "chuyen"):
			ket = self._goi(b["nguoi"], "post_stock_issue" if k == "xuat_le" else "post_stock_transfer",
				{"p_entry_id": self._ten(st, "pk:" + b["nhan"])})
			if "error" in ket:
				return ket, None
			return ket, "pk:" + (self._nhan_ct(st, ket["data"], "pk") or "?")
		if k == "huy_pk":
			nhan = b["nhan"]
			ten = self._pk_nguon(st, nhan[1:]) if nhan.startswith("@") else self._ten(st, "pk:" + nhan)
			ket = self._goi(b["nguoi"], "cancel_stock_entry", {"p_entry_id": ten, "p_reason": b.get("ly_do")})
			return ket, None if "error" in ket else ket["data"][0]
		if k == "tra_khach":  # phiếu trả khách TỰ LẬP không gắn HĐ (P3): lập nháp + hoàn thành kho bán — như bộ sinh
			head = {"customer_id": self._thay(b.get("khach", "@K1"), st), "reason": "damaged", "status": "draft"}
			ket = self._goi(b["nguoi"], "create_return_with_lines", {"p_head": head, "p_lines": self._thay(b["dong"], st)})
			if "error" in ket:
				return ket, None
			st["nhan"]["tk:" + b["nhan"]] = ket["data"]
			ket = self._goi(b["nguoi"], "complete_return", {"p_return_id": ket["data"], "p_zone": "sale"})
			return ket, None if "error" in ket else {}  # `entry_id` bỏ như kết quả HĐ (`_chuan_tra`)
		if k == "gia_von_ky":
			return self._gia_von_ky(b, st)
		# ------------------------------------------------------------------ M5 — lô + kho cận date
		if k == "ra_soat":
			return self._ra_soat(b, st)
		# ------------------------------------------------------------------ M6 — kiểm kê
		if k in ("kk_duyet", "kk_tu_choi"):
			nhan = b["nhan"]
			ten = self._thay(nhan, st) if nhan.startswith("@") else self._ten(st, "pk:" + nhan)
			if k == "kk_tu_choi":
				ket = self._goi(b["nguoi"], "reject_stock_adjustment", {"p_entry_id": ten, "p_reason": b.get("ly_do")})
				return ket, None if "error" in ket else ket["data"]
			ket = self._goi(b["nguoi"], "post_stock_adjustment", {"p_entry_id": ten})
			if "error" in ket:
				return ket, None
			r = dict(ket["data"][0])
			if r.get("expense_id"):  # phiếu chi hao hụt → "cp:<nhãn phiếu kiểm kê>" (bộ sinh: "cp:" + tham chiếu)
				r["expense_id"] = "cp:" + str(self._ma_pn(st, frappe.db.get_value("NPP Phieu Chi", r["expense_id"], "so_tham_chieu")))
			return ket, r
		# ------------------------------------------------------------------ M8 — nhà cung cấp
		if k == "gop":
			ket = self._goi(b["nguoi"], "gop_nha_cung_cap", {"p_tu": self._thay(b["tu"], st), "p_vao": self._thay(b["vao"], st)})
			if "error" in ket:
				return ket, None
			return ket, {**ket["data"], "vao": self.khoa_cua.get(ket["data"]["vao"], ket["data"]["vao"])}
		if k == "xoa_ncc":  # không có khoá `xoa_hang` = không truyền tham số (mặc định false)
			ts = {"p_id": self._thay(b["ncc"], st)}
			if "xoa_hang" in b:
				ts["p_xoa_hang"] = b["xoa_hang"]
			ket = self._goi(b["nguoi"], "xoa_nha_cung_cap", ts)
			return ket, None if "error" in ket else ket["data"]
		if k == "doc" and b.get("ten") == "so_chung_tu_ncc":
			ket = self._goi(b["nguoi"], "so_chung_tu_ncc", self._thay(b.get("ts") or {}, st))
			return ket, None if "error" in ket else ket["data"]
		# ------------------------------------------------------------------ M9 — báo cáo, đầu-cuối
		if k == "doc" and b.get("ten") == "bao_cao_ton_kho":
			return self._bao_cao_ton_kho(b, st)
		if k == "doc" and b.get("ten") == "hoa_don_mua_con_no":
			return self._hoa_don_mua_con_no(b, st)
		if k == "goi_rpc":
			ket = self._goi(b["nguoi"], b["ten"], self._thay(b.get("ts") or {}, st))
			return ket, None if "error" in ket else ket["data"]
		if k == "doc_phien":
			# ⚠K (tệp vàng `khac_frappe` V84): so MỨC TĂNG của số phiên danh mục (`NPP Phien Danh Muc`), không số tuyệt đối
			from nppsale.npp_he_thong.doctype.npp_phien_danh_muc.npp_phien_danh_muc import doc_phien

			p, truoc = cint(doc_phien()["phien"]), st.get("phien")
			st["phien"] = p
			return {"data": None}, {"phien": "dau" if truoc is None else ("tang" if p > truoc else "khong_tang")}
		raise ValueError(f"bước chưa dựng ở bài so: {k}")

	def _ckl_tu_dong(self) -> set:
		return set(frappe.get_all("Stock Entry", filters={"npp_loai": "chuyen_date_tu_dong", "docstatus": 1}, pluck="name"))

	def _lo_cu_trong(self, phieu: set) -> int:
		"""Số lô CÓ SẴN trên site (dữ liệu dựng thử cũ — `co_san`) mà các phiếu rà soát mới chở — trừ ra để so số của kịch bản (tồn kho bán của lô cũ
		vào ngưỡng hay không tuỳ ngày chạy)."""
		if not phieu:
			return 0
		return len({r[0] for r in frappe.db.sql("""SELECT DISTINCT e.`batch_no` FROM `tabSerial and Batch Bundle` b
			JOIN `tabSerial and Batch Entry` e ON e.`parent` = b.`name` WHERE b.`voucher_type` = 'Stock Entry' AND b.`voucher_no` IN %s
			AND b.`type_of_transaction` = 'Outward'""", (tuple(phieu),)) if r[0] in self.co_san["Batch"]})

	def _ra_soat(self, b: dict, st: dict) -> tuple[dict, object]:
		"""`refresh_warehouse_zones(NPP)` dưới đúng người; "HE_THONG" = không người đăng nhập (nppsale: vai service_role, cron) ↔ Administrator."""
		truoc = self._ckl_tu_dong()
		ts = {"p_org_id": self._thay(b.get("org", "@org"), st)}
		if b["nguoi"] == "HE_THONG":
			self._ve_admin()
			ket = api.rpc(ten="refresh_warehouse_zones", tham_so=ts)
		else:
			ket = self._goi(b["nguoi"], "refresh_warehouse_zones", ts)
		if "error" in ket:
			return ket, None
		return ket, ket["data"] - self._lo_cu_trong(self._ckl_tu_dong() - truoc)

	def _tong_no_co_san(self, nguoi: str, tu) -> tuple[float, float]:
		"""Phần của các dòng công nợ NCC CÓ SẴN trên site trước kịch bản (NCC ngoài bộ dữ liệu) trong `payables_summary` — trừ ra để so số của
		kịch bản. Vai không đọc được `payables` (RLS) → 0 như kết quả hàm."""
		if self.vang["nen"]["nguoi"][nguoi][0] not in ("owner", "manager", "accountant") or not self.co_san["NPP Cong No NCC"]:
			return 0.0, 0.0
		tu = get_datetime(str(tu).replace("T", " ")[:19]) if tu else None
		mo = thang = 0.0
		for r in frappe.get_all("NPP Cong No NCC", filters={"name": ("in", list(self.co_san["NPP Cong No NCC"]))},
				fields=["so_tien", "da_tra", "trang_thai", "phieu_kho", "tao_luc"]):
			if r.trang_thai != "paid":
				mo += flt(r.so_tien) - flt(r.da_tra)
			if r.phieu_kho and tu is not None and r.tao_luc and get_datetime(r.tao_luc) >= tu:
				thang += flt(r.so_tien)
		return mo, thang

	def _tra_pc(self, st: dict, r: dict) -> dict:
		"""Kết quả chi_tra_ncc / huy_phieu_chi_ncc → mã phiếu chi theo nhãn (dãy `PCNCC-` của site — so theo nhãn như phiếu nhập)."""
		return {**r, "id": "pc:" + str(self._ma_pn(st, r.get("id"))), "code": self._ma_pn(st, r.get("code"))}

	def _kham_ncc(self) -> dict:
		"""Bất biến khám sổ dòng 66 (bộ sinh `_vp4_kham_ncc`) đếm trên NCC của bộ dữ liệu — nppsale.kham_so.quet_dong_chi_ncc nhóm 23–26."""
		from nppsale.kham_so import quet_dong_chi_ncc

		lech = quet_dong_chi_ncc([v for kk, v in self.ma.items() if re.fullmatch(r"S\d", kk)])
		dem = lambda n: len([x for x in lech if x["nhom"] == n])  # noqa: E731
		return {"paid_lech": dem(23), "phieu_chi_lech": dem(24), "luc_chi_lech": dem(25), "chi_vao_dong_am": dem(26)}

	def _ghi_dong_ptn(self, b: dict, st: dict) -> dict:
		ten = self._ten(st, "ptn:" + b["nhan"])
		dong = [{**self._thay(d, st), "return_id": ten} for d in b.get("dong") or []]
		if not dong:
			return {"data": []}
		return self._cong(b["nguoi"], {"bang": "supplier_return_lines", "hanh_dong": "insert", "gia_tri": dong, "select": "id"})

	def _lo(self, b: dict) -> str:
		"""Lô dựng sẵn: nppsale chèn `batches` bằng quyền máy chủ → trigger `batches_auto_zone` (mig 028) đẩy lô kho bán có hạn trong ngưỡng sang kho date
		NGAY lúc chèn (L-C hạn +10 — đặc tả §6.4). Bản Frappe (M5): kho tạo theo CHÍNH hàm của app (`goi_lo.kho_nhan_lo` — cổng `batches` tạo lô rỗng,
		phiếu nhập, nhập kho tay dùng chung; ngưỡng hiện tại của `NPP Cai Dat`) rồi phiếu nhập kho có gói lô vào kho ấy."""
		from nppsale.rpc.goi_lo import kho_nhan_lo, vung_cua_kho

		han = add_days(XH.hom_nay(), b["han"]) if b.get("han") is not None else None
		frappe.local._npp_cai_dat_ban = None
		cd = cai_dat_kho()
		return dung_lo(self.ma, self.cd, {**b, "vung": vung_cua_kho(kho_nhan_lo(b["vung"], han, cd, XH.hom_nay()), cd)})

	def _pk_nguon(self, st: dict, k: str) -> str | None:
		"""Chỗ giữ phiếu kho của chứng từ gốc (bộ sinh `_pk_khoa`): "pk:hd:<nhãn>" HĐ bán (phiếu kho của HĐ = chính HĐ — ⚠K §7.2 #14), "pk:pn:<nhãn>" /
		"pk:ptn:<nhãn>" tờ CUỐI của phiếu nhập / trả NCC, "pk:nl:<nhãn phiếu trả khách>" chứng từ nhập lại của phiếu trả (Stock Entry `NL-` hoặc tờ ghi
		có có kho `HDT-`)."""
		_, loai, nhan = k.split(":", 2)
		if loai == "hd":
			return st["nhan"].get("hd:" + nhan)
		if loai in LOAI_CT:
			return self._ten(st, f"{loai}:{nhan}")
		if loai == "nl":
			r = frappe.db.get_value("NPP Phieu Tra", st["nhan"].get("tk:" + nhan), ["to_ghi_co", "phieu_nhap_kho"], as_dict=True)
			return (r.phieu_nhap_kho or r.to_ghi_co) if r else None
		raise ValueError(f"chỗ giữ phiếu kho lạ: @{k}")

	def _gia_von_ky(self, b: dict, st: dict) -> tuple[dict, object]:
		"""Giá vốn kỳ đọc QUA CỔNG dưới đúng người — chép `fetchCogsForRange` + `fetchPostedStockEntries('export')` + `chiPhieuXuatBan` (TS
		src/lib/analytics/sales.ts:400–420, 836–881): phiếu `export` `posted` có `posted_at` trong ngày VN của kỳ, bỏ ghi chú "Đảo phiếu trả " (phiếu
		của HĐ huỷ đã `cancelled` ở cổng Frappe); Σ |SL cơ sở| (thiếu → |quantity| × hệ số) × `unit_cost` dòng. Phiếu có sẵn trên site bỏ."""
		tu, den = self._thay(b["tu"], st), self._thay(b["den"], st)
		ket = self._cong(b["nguoi"], {"bang": "stock_entries", "select": "id, notes", "loc": [{"op": "eq", "cot": "status", "gt": "posted"},
			{"op": "eq", "cot": "type", "gt": "export"}, {"op": "gte", "cot": "posted_at", "gt": f"{tu}T00:00:00+07:00"},
			{"op": "lte", "cot": "posted_at", "gt": f"{den}T23:59:59.999+07:00"}]})
		if "error" in ket:
			return ket, None
		cu = set().union(*self.co_san.values())
		ids = [r["id"] for r in ket["data"] if r["id"] not in cu and not (r.get("notes") or "").startswith("Đảo phiếu trả ")]
		ket = self._cong(b["nguoi"], {"bang": "stock_entry_lines", "select": "entry_id, quantity, qty_in_base_uom, conversion_factor_snapshot, "
			"unit_cost", "loc": [{"op": "in", "cot": "entry_id", "gt": ids or [""]}]})
		if "error" in ket:
			return ket, None
		gv = 0.0
		for d in ket["data"]:
			hs = flt(d["conversion_factor_snapshot"])
			sl = abs(flt(d["qty_in_base_uom"])) if d["qty_in_base_uom"] is not None else abs(flt(d["quantity"])) * (hs if hs > 0 else 1)
			gv += sl * flt(d["unit_cost"])
		return ket, {"cogs": round(gv, 2)}

	def _bao_cao_ton_kho(self, b: dict, st: dict) -> tuple[dict, object]:
		"""RPC `bao_cao_ton_kho` (M9 — §5.4) dưới đúng người → cùng dạng `chuan_gt` của bộ sinh: id lô `<lô>::<vùng>` → "lo:<mã>@<vùng>", mặt hàng →
		khoá nền, ngày / mốc giờ → "@hom_nay±n[THH:MI]", HĐ → "hd:<nhãn>". Lô có sẵn trên site / lô ảo (hàng không lô của site) và dòng của HĐ có sẵn
		(dữ liệu dựng thử cũ) bỏ; hai mảng so theo tập (nppsale `lo` sắp theo uuid, `dong` không sắp — thứ tự `id` của bản Frappe kiểm ở
		nppsale.tests.test_bao_cao_kho)."""
		ket = self._goi(b["nguoi"], "bao_cao_ton_kho", self._thay(b.get("ts") or {}, st))
		if "error" in ket:
			return ket, None
		k = self.khoa_cua.get
		hd = {v: kk[3:] for kk, v in st["nhan"].items() if kk.startswith("hd:") and v}
		lo = []
		for r in ket["data"]["lo"]:
			ma, _, vung = r["id"].rpartition("::")
			if r["id"].startswith("~") or ma in self.co_san["Batch"]:
				continue
			lo.append({"id": f"lo:{self._ma_lo(st, ma)}@{vung}", "product_id": k(r["product_id"]) or r["product_id"],
				"batch_code": self._ma_lo(st, r["batch_code"]), "qty_on_hand": r["qty_on_hand"], "unit_cost": r["unit_cost"],
				"expires_at": self._ngay(r["expires_at"]), "created_at": self._luc(r["created_at"])})
		dong = [{"ngay": self._ngay(r["ngay"]), "invoice_id": "hd:" + hd[r["invoice_id"]], "product_id": k(r["product_id"]) or r["product_id"],
			"unit_name": r["unit_name"], "conversion_factor": r["conversion_factor"], "quantity": r["quantity"], "is_exchange": r["is_exchange"]}
			for r in ket["data"]["dong"] if r["invoice_id"] not in self.co_san["Sales Invoice"]]
		return ket, {"lo": _xep(_so(lo)), "dong": _xep(_so(dong))}

	def _hoa_don_mua_con_no(self, b: dict, st: dict) -> tuple[dict, object]:
		"""Mô phỏng câu của /purchasing/invoices tab "Còn nợ" + ô tìm (TS src/app/(dashboard)/purchasing/invoices/page.tsx:117–154 + `useListSearch`
		→ `menhDeTimDanhSach`, V77) QUA CỔNG dưới đúng người: tra trước `suppliers` (tên / mã) và `payables` (số HĐ NCC → `stock_entry_id`) chứa chữ gõ,
		rồi `stock_entries` `type = import` có `debt:payables!inner(status)` `neq paid` và `or(entry_code / tim_kd ilike, supplier_id.in, id.in)` →
		mã phiếu (theo nhãn: phiếu nhập "<P1>", nhập kho có NCC + nợ — PN theo CFD-13 — "<IN1>")."""
		tu = b["ts"]["tim"]
		ncc = self._cong(b["nguoi"], {"bang": "suppliers", "select": "id", "loc": [{"op": "or", "bieu_thuc": f"name.ilike.*{tu}*,code.ilike.*{tu}*"}]})
		no = self._cong(b["nguoi"], {"bang": "payables", "select": "stock_entry_id", "loc": [{"op": "ilike", "cot": "invoice_number", "gt": f"*{tu}*"}]})
		for x in (ncc, no):
			if "error" in x:
				return x, None
		menh = [f"entry_code.ilike.*{tu}*", f"tim_kd.ilike.*{tu.lower()}*"]
		if ncc["data"]:
			menh.append(f"supplier_id.in.({','.join(r['id'] for r in ncc['data'])})")
		ids = sorted({r["stock_entry_id"] for r in no["data"] if r.get("stock_entry_id")})
		if ids:
			menh.append(f"id.in.({','.join(ids)})")
		ket = self._cong(b["nguoi"], {"bang": "stock_entries", "select": "id, entry_code, debt:payables!inner(status)",
			"loc": [{"op": "eq", "cot": "type", "gt": "import"}, {"op": "or", "bieu_thuc": ",".join(menh)},
				{"op": "neq", "cot": "debt.status", "gt": "paid"}]})
		if "error" in ket:
			return ket, None
		cu = set().union(*self.co_san.values())
		return ket, sorted(self._ma_pn(st, r["entry_code"]) for r in ket["data"] if r["id"] not in cu)

	def _lo_theo_phieu_goc(self, b: dict, st: dict) -> tuple[dict, object]:
		"""Mô phỏng `loadReceiptLinesForReturn` (TS src/lib/pos/load.ts:312–350) qua cổng dưới đúng người — bản lớp phủ của portal
		(portal/src/thay/lib/pos/load.ts) cắt đuôi amend của mã phiếu trước khi tìm lô `<mã>-%` (§7.3 điểm 41, V87)."""
		pn = self._thay(b["ts"]["pn"], st)
		ket = self._cong(b["nguoi"], {"bang": "purchase_invoices", "select": "id, receipt_code", "loc": [{"op": "eq", "cot": "id", "gt": pn}]})
		if "error" in ket:
			return ket, None
		ma = ket["data"][0]["receipt_code"] if ket["data"] else None
		goc = "-".join(ma.split("-")[:2]) if ma else None
		ket = self._cong(b["nguoi"], {"bang": "batches", "select": "product_id, batch_code, expires_at, warehouse_zone",
			"loc": [{"op": "like", "cot": "batch_code", "gt": f"{goc}-%"}]})
		if "error" in ket:
			return ket, None
		ds = sorted(ket["data"], key=lambda r: (r["batch_code"], r["warehouse_zone"]))
		return ket, [{"product_id": self.khoa_cua.get(r["product_id"], r["product_id"]), "batch_code": self._ma_lo(st, r["batch_code"]),
			"expires_at": r["expires_at"]} for r in ds]

	def _ghi_dong(self, b: dict, st: dict) -> dict:
		ten = self._ten(st, "pn:" + b["nhan"])
		dong = [{**self._thay(d, st), "invoice_id": ten} for d in b.get("dong") or []]
		if not dong:
			return {"data": []}
		return self._cong(b["nguoi"], {"bang": "purchase_invoice_lines", "hanh_dong": "insert", "gia_tri": dong, "select": "id"})

	def _ban(self, b: dict, st: dict) -> tuple[dict, object]:
		"""Bán làm nền (P3): create_order_with_lines (đơn submitted, giá bảng giá bán nền) + post_invoice đủ dòng — như `_ban_sql` của bộ sinh."""
		gia = {(sp, dv): g for sp, dv, g in self.vang["nen"]["gia_ban"]}
		gia_cua = lambda x: gia.get((x["product_id"][1:], x["unit_name"]), 10000)  # noqa: E731 — X (chỉ Frappe) không có giá bán nền
		dong = [{"product_id": self.ma[x["product_id"][1:]], "unit_name": x["unit_name"], "quantity": x["quantity"], "unit_price": gia_cua(x),
			"line_discount": 0, "conversion_factor": 1, "vat_rate": 0, "line_total": x["quantity"] * gia_cua(x)} for x in b["dong"]]
		tong = sum(x["line_total"] for x in dong)
		p = {"client_request_id": str(uuid.uuid5(NS, f"{st['ma']}:don:{b['nhan']}")), "order": {"order_code": "TAM-1",
			"customer_id": self.ma[b.get("khach", "@K1")[1:]], "payment_terms": "COD", "expected_delivery": None, "subtotal": tong, "vat": 0,
			"total": tong, "notes": None, "status": "submitted", "approval_reason": None, "sales_user_id": None}, "lines": dong, "returns": None,
			"return_lines": []}
		ket = self._goi(b["nguoi"], "create_order_with_lines", {"p": p})
		if "error" in ket:
			return ket, None
		don = ket["data"][0]["order_id"]
		dd = frappe.get_all("Sales Order Item", filters={"parent": don}, fields=["name", "item_code", "uom", "conversion_factor", "qty", "rate",
			"npp_giam_dong", "npp_thue_suat", "additional_notes"], order_by="idx asc")
		lines = [{"order_line_id": r.name, "product_id": r.item_code, "unit_name": r.uom, "conversion_factor": r.conversion_factor, "quantity": r.qty,
			"unit_price": r.rate, "line_discount": r.npp_giam_dong, "vat_rate": r.npp_thue_suat, "is_exchange": False, "note": r.additional_notes}
			for r in dd]
		ket = self._goi(b["nguoi"], "post_invoice", {"p": {"order_id": don, "lines": lines}})
		if "error" in ket:
			return ket, None
		r = ket["data"][0]
		st["nhan"]["hd:" + b["nhan"]] = r["invoice_id"]
		st["nhan"]["don:" + b["nhan"]] = don
		return ket, {"short_qty": flt(r.get("short_qty")), "invoice_id": "hd:" + b["nhan"], "invoice_code": r.get("invoice_code"),
			"order_status": r.get("order_status"), "receivable_id": "@id" if r.get("receivable_id") else None,
			"near_expiry_skipped": flt(r.get("near_expiry_skipped"))}

	def _chuan_dong(self, r: dict, st: dict) -> dict:
		"""Dòng đọc qua cổng → khoá nghiệp vụ (cùng luật `chuan_gt` của bộ sinh): mặt hàng / NCC / người → khoá nền; phiếu nhập → "pn:<nhãn>";
		ngày → "@hom_nay±n"; số → float."""
		ra = {}
		for k, v in r.items():
			if k == "source_invoice_id" or (k.endswith("invoice_id") and v):
				v = ("pn:" + (self._nhan_pn(st, v) or "?")) if v else None
			elif k == "return_id" and v:
				v = "ptn:" + (self._nhan_ptn(st, v) or "?")
			elif k in ("entry_code", "entry_id") and v:  # mã phiếu kho (v_stock_movements…) → "<nhãn>" (phiếu kho tay / phiếu nhập / trả NCC)
				v = self._ma_pn(st, v)
			elif k == "batch_code" and v:  # lô của phiếu nhập `<PN>-NNN` → "<nhãn>-NNN" (câu 18 — M7 V70)
				v = self._ma_lo(st, v)
			elif isinstance(v, str) and v in self.khoa_cua:
				v = self.khoa_cua[v]
			elif k.endswith(("_date", "_at")) and v:
				# `batches.expires_at` / `manufactured_at` là DATE ở nppsale (tên đuôi `_at`) — so như ngày
				v = self._ngay(v) if k.endswith("_date") or k in ("expires_at", "manufactured_at") else self._luc(v)
			ra[k] = _so(v)
		return ra

	# ------------------------------------------------------------------------------------------------ ảnh chụp cuối (cùng dạng _vp4_anh)
	def _ct(self, st: dict) -> dict:
		k = self.khoa_cua.get
		chuoi = {nhan[3:]: self._cuoi(goc) for nhan, goc in st["nhan"].items() if nhan.startswith("pn:") and goc}
		pn, phieu_kho = [], []
		for nhan, ten in chuoi.items():
			r = doc_cong({"bang": "purchase_invoices", "select": "*, lines:purchase_invoice_lines(*)", "loc": [{"op": "eq", "cot": "id", "gt": ten}]},
				ADMIN)["data"][0]
			dong = [_bo_null({"sp": k(d["product_id"]), "dv": d["unit_name"], "sl": d["quantity"], "gia": d["unit_price"], "giam": d["line_discount"],
				"thue": d["vat_rate"], "hs": d["conversion_factor"], "tien": d["line_total"], "ghi_chu": d["notes"], "stt": d["sort_order"]})
				for d in sorted(r["lines"], key=lambda x: x["sort_order"])]
			pn.append(_bo_null({"nhan": nhan, "ma": f"<{nhan}>", "status": r["status"], "ncc": k(r["supplier_id"]), "so_hd": r["invoice_number"],
				"ngay": self._ngay(r["invoice_date"]), "vung": r["warehouse_zone"], "subtotal": r["subtotal"], "vat": r["vat"], "total": r["total"],
				"giam": r["discount"], "thue_tay": r["vat_override"], "ghi_chu": r["notes"], "lap_boi": k(r["created_by"]),
				"luc_hoan_thanh": self._luc(r["completed_at"]), "luc_huy": self._luc(r["cancelled_at"]), "huy_boi": k(r["cancelled_by"]),
				"ly_do_huy": r["cancel_reason"], "phieu_kho": f"<{nhan}>" if r["stock_entry_id"] else None, "co_phieu_kho": bool(r["stock_entry_id"]),
				"no": f"PN:<{nhan}>" if r["payable_id"] else None, "dong": dong or None}))
			if r["stock_entry_id"]:
				phieu_kho.append(self._phieu_kho_pn(nhan, ten, r, st))
		ptn = []
		for nhan, goc in st["nhan"].items():
			if not nhan.startswith("ptn:") or not goc or self._nhan_ptn(st, goc) != nhan[4:]:
				continue  # nhãn của phiếu nháp đã xoá mà số đã cấp lại cho phiếu sau
			ds = doc_cong({"bang": "supplier_returns", "select": "*, lines:supplier_return_lines(*)", "loc": [{"op": "eq", "cot": "id",
				"gt": self._cuoi(goc)}]}, ADMIN)["data"]
			if not ds:
				continue  # phiếu nháp đã xoá
			r, nhan = ds[0], nhan[4:]
			dong = [_bo_null({"sp": k(d["product_id"]), "dv": d["unit_name"], "sl": d["quantity"], "gia": d["unit_price"], "giam": d["line_discount"],
				"thue": d["vat_rate"], "hs": d["conversion_factor"], "tien": d["line_total"], "ghi_chu": d["notes"], "stt": d["sort_order"]})
				for d in sorted(r["lines"], key=lambda x: x["sort_order"])]
			ptn.append(_bo_null({"nhan": nhan, "ma": f"<{nhan}>", "npp": "A", "status": r["status"], "ncc": k(r["supplier_id"]),
				"ngay": self._ngay(r["return_date"]), "ly_do": r["reason"], "ghi_chu": r["notes"], "vung": r["warehouse_zone"],
				"subtotal": r["subtotal"], "vat": r["vat"], "total": r["total"], "giam": r["discount"], "thue_tay": r["vat_override"],
				"phieu_kho": f"<{nhan}>" if r["stock_entry_id"] else None, "no": f"PTNCC:<{nhan}>" if r["payable_credit_id"] else None,
				"luc_hoan_thanh": self._luc(r["completed_at"]), "hoan_thanh_boi": k(r["completed_by"]), "lap_boi": k(r["created_by"]),
				"ly_do_huy": r["cancel_reason"], "ma_cu": r["return_code_cu"], "dong": dong or None}))
			# phiếu kho của phiếu trả = chính các tờ ĐÃ / THÔI ghi sổ của chuỗi (nppsale: mỗi lần gửi một phiếu `XK-` mới, huỷ giữ phiếu cũ)
			to = goc
			for _ in range(50):
				if cint(frappe.db.get_value("Purchase Invoice", to, "docstatus")) in (1, 2):
					phieu_kho.append(self._phieu_kho_ptn(nhan, to, st))
				to = frappe.db.get_value("Purchase Invoice", {"amended_from": to}, "name", order_by="creation desc")
				if not to:
					break
		lo = []
		for r in doc_cong({"bang": "batches", "select": "*"}, ADMIN)["data"]:
			ma_lo = r["batch_code"]
			if ma_lo in self.co_san["Batch"] or r["id"].startswith("~"):
				continue
			lo.append(_bo_null({"sp": k(r["product_id"]), "ma": self._ma_lo(st, ma_lo), "vung": r["warehouse_zone"], "nhap": r["qty_initial"],
				"ton": r["qty_on_hand"], "gia": round(flt(r["unit_cost"]), 2), "status": r["status"], "han": self._ngay(r["expires_at"]),
				"nsx": self._ngay(r["manufactured_at"]), "vi_tri": r["location"], "luc_nhan": self._luc(r["received_at"]),
				"luc_chuyen_vung": self._luc(r["zone_moved_at"]), "chuyen_boi": k(r["zone_moved_by"])}))
		no = []
		ncc = [v for kk, v in self.ma.items() if re.fullmatch(r"S\d", kk)]
		dong_no = []
		for r in doc_cong({"bang": "payables", "select": "*", "loc": [{"op": "in", "cot": "supplier_id", "gt": ncc}]}, ADMIN)["data"]:
			if r["id"] in self.co_san["NPP Cong No NCC"]:
				continue
			dong_no.append(r["id"])
			nguon = frappe.db.get_value("NPP Cong No NCC", r["id"], ["loai", "chung_tu"], as_dict=True)
			khoa = self._khoa_no(st, r["id"])
			# nppsale tính `luc_bang_hoan_thanh` qua `purchase_invoices.payable_id` — chỉ dòng nợ của PHIẾU NHẬP có
			pi_luc = (frappe.db.get_value("Purchase Invoice", nguon.chung_tu, "npp_hoan_thanh_luc") if nguon.chung_tu and nguon.loai == "phieu_nhap"
				else None)
			tao = frappe.db.get_value("NPP Cong No NCC", r["id"], "tao_luc")
			no.append(_bo_null({"khoa": khoa, "ncc": k(r["supplier_id"]), "so_hd": self._ma_pn(st, r["invoice_number"]), "so_tien": r["amount"], "da_tra": r["paid"],
				"status": r["status"], "han": self._ngay(r["due_date"]), "ghi_chu": self._chu_ma(st, r["notes"]), "dau_ky": bool(r["opening_balance"]),
				"luc": self._luc(r["created_at"]), "phieu_kho": self._ma_pn(st, r["stock_entry_id"]),
				"luc_bang_hoan_thanh": (get_datetime(pi_luc) == get_datetime(tao)) if pi_luc and tao else None}))
		tra_no = []
		for r in doc_cong({"bang": "payable_payments", "select": "*", "loc": [{"op": "in", "cot": "payable_id", "gt": dong_no or [""]}]},
				ADMIN)["data"]:
			tra_no.append(_bo_null({"no": self._khoa_no(st, r["payable_id"]), "tien": r["amount"], "cach": r["method"], "boi": k(r["paid_by"]),
				"luc": self._luc(r["paid_at"]), "ghi_chu": self._chu_ma(st, r["notes"]), "phieu_chi": self._ma_pn(st, r["supplier_payment_id"]),
				"xac_nhan": r["verified_by"] is not None}))
		phieu_chi = []
		for r in doc_cong({"bang": "supplier_payments", "select": "*, dong:payable_payments(amount, paid_at)",
				"loc": [{"op": "in", "cot": "supplier_id", "gt": ncc}]}, ADMIN)["data"]:
			if r["id"] in self.co_san["Payment Entry"]:
				continue
			dong = r.get("dong") or []
			phieu_chi.append(_bo_null({"nhan": self._nhan_ct(st, r["id"], "pc"), "ma": self._ma_pn(st, r["code"]), "ncc": k(r["supplier_id"]),
				"ngay": self._ngay(r["paid_date"]), "tien": r["amount"], "cach": r["method"], "tham_chieu": r["reference_code"], "ghi_chu": r["notes"],
				"status": r["status"], "tra_truoc": self._khoa_no(st, r["prepay_payable_id"]), "lap_boi": k(r["created_by"]),
				"luc_huy": self._luc(r["cancelled_at"]), "huy_boi": k(r["cancelled_by"]), "ly_do_huy": r["cancel_reason"],
				"luc_chi": sorted({self._luc(x["paid_at"]) for x in dong}) or None,
				"tong_dong": sum(flt(x["amount"]) for x in dong) if dong else None}))
		gia_nhap = []
		hang = [v for kk, v in self.ma.items() if re.fullmatch(r"[A-Z]", kk)]
		for r in doc_cong({"bang": "purchase_price_lists", "select": "*", "loc": [{"op": "in", "cot": "product_id", "gt": hang}]}, ADMIN)["data"]:
			gia_nhap.append(_bo_null({"sp": k(r["product_id"]), "dv": r["unit_name"], "gia": r["price"], "ngay": self._ngay(r["effective_date"]),
				"nguon": self._ma_pn(st, r["source_invoice_id"]), "sua_boi": k(r["updated_by"])}))
		hd = []
		for nhan, ten in st["nhan"].items():
			if nhan.startswith("hd:") and ten:
				r = frappe.db.get_value("Sales Invoice", ten, ["name", "docstatus", "grand_total"], as_dict=True)
				hd.append({"nhan": nhan[3:], "ma": r.name, "status": {1: "posted", 2: "cancelled"}.get(r.docstatus, "draft"), "total": r.grand_total})
		for nhan, ten in st["nhan"].items():  # phiếu kho tay (M4) — đọc qua cổng; nháp số cuối bị xoá thì số cấp lại cho phiếu sau: nhãn SAU thắng
			if nhan.startswith("pk:") and ten and self._nhan_ct(st, ten, "pk") == nhan[3:]:
				x = self._phieu_kho_pk(nhan[3:], ten, st)
				if x:
					phieu_kho.append(x)
		chi_phi = []
		ten_pk = self._ten_trong_loi(st)
		for r in frappe.get_all("NPP Phieu Chi", fields=["name", "danh_muc", "ngay_chi", "so_tien", "dien_giai", "so_tham_chieu", "nguon_loai",
				"kiem_ke", "da_tra", "owner"]):
			if r.name in self.co_san["NPP Phieu Chi"]:
				continue
			chi_phi.append(_bo_null({"loai": frappe.db.get_value("NPP Danh Muc Chi Phi", r.danh_muc, "ma") if r.danh_muc else None,
				"ngay": self._ngay(r.ngay_chi), "tien": r.so_tien, "mo_ta": _thay_ma(r.dien_giai, ten_pk), "tham_chieu": _thay_ma(r.so_tham_chieu, ten_pk),
				"nguon": r.nguon_loai, "nguon_pk": self._ma_pn(st, r.kiem_ke), "da_tra": bool(r.da_tra), "lap_boi": k(r.owner)}))
		tra_khach = []
		for nhan, ten in st["nhan"].items():
			if nhan.startswith("tk:") and ten:
				for r in doc_cong({"bang": "returns", "select": "status, credit_note_amount", "loc": [{"op": "eq", "cot": "id", "gt": ten}]},
						ADMIN)["data"]:
					tra_khach.append({"nhan": nhan[3:], "ma": f"<{nhan[3:]}>", "status": r["status"], "tien": r["credit_note_amount"]})
		# M8 — NCC (cột `_vp4_anh` của bộ sinh: khoá, tên, mã, SĐT, email, MST, ghi chú, đang hợp tác, người lập), phân công NV ↔ NCC, mặt hàng (trạng
		# thái + NCC chính) của bộ dữ liệu — NCC / NV có sẵn trên site (dữ liệu dựng thử cũ) bỏ; hàng `hang_frappe` (X — chỉ Frappe) bỏ
		ncc_ds = []
		for r in doc_cong({"bang": "suppliers", "select": "id, name, code, phone, email, tax_code, notes, is_active, created_by"}, ADMIN)["data"]:
			if r["id"] in self.co_san["Supplier"]:
				continue
			ncc_ds.append(_bo_null({"khoa": k(r["id"]) or r["id"], "ten": r["name"], "ma": r["code"], "phone": r["phone"], "email": r["email"],
				"tax_code": r["tax_code"], "ghi_chu": r["notes"], "dang_lam": r["is_active"], "lap_boi": k(r["created_by"])}))
		nv = {v for kk, v in self.ma.items() if kk.startswith("u:")}
		phan_cong = [[k(u) or u, k(n) or n] for u, n in frappe.db.sql("SELECT `parent`, `nha_cung_cap` FROM `tabNPP Nhan Vien Cong Ty`")
			if u in nv and n not in self.co_san["Supplier"]]
		hang_ds = []
		for kk in self.vang["nen"]["hang"]:
			for r in doc_cong({"bang": "products", "select": "id, status, primary_supplier_id", "loc": [{"op": "eq", "cot": "id", "gt": self.ma[kk]}]},
					ADMIN)["data"]:
				hang_ds.append(_bo_null({"khoa": "@" + kk, "status": r["status"], "ncc": k(r["primary_supplier_id"]) or r["primary_supplier_id"]}))
		return {"pn": _xep(_so(pn)) or None, "ptn": _xep(_so(ptn)) or None, "lo": _xep(_so(lo)) or None, "no": _xep(_so(no)) or None,
			"tra_no": _xep(_so(_gop_tra_truoc(tra_no))) or None, "phieu_chi": _xep(_so(phieu_chi)) or None, "gia_nhap": _xep(_so(gia_nhap)) or None,
			"phieu_kho": _xep(_so(phieu_kho)) or None, "hd": _xep(_so(hd)) or None, "tra_khach": _xep(_so(tra_khach)) or None,
			"chi_phi": _xep(_so(chi_phi)) or None, "ncc": _xep(ncc_ds) or None, "hang": _xep(hang_ds) or None, "phan_cong": _xep(phan_cong) or None,
			"nhan": sorted(st["nhan"])}

	def _phieu_kho_pk(self, nhan: str, ten: str, st: dict) -> dict | None:
		"""Phiếu kho có nhãn `pk:` (nhập kho tay / xuất lẻ / chuyển kho — kể cả PI `PN-` của nhập kho có NCC + nợ, CFD-13) đọc QUA CỔNG `stock_entries`
		+ `stock_entry_lines` (cùng luật đọc với giao diện). Dòng nhập so `lo`; dòng xuất / chuyển không (⚠K: cổng có `batch_id` khi dòng lấy đúng một
		lô — nppsale NULL) mà so VẾT lấy lô ở mức phiếu: gói lô Outward của các dòng (cả gói đã huỷ — nppsale giữ `stock_line_consumptions` khi huỷ)
		gộp theo (lô, giá) — đặc tả V42: thứ tự dòng nppsale theo uuid, so tổng theo lô. Nháp đã xoá (huỷ nháp — §7.3 điểm 1) → None."""
		ds = doc_cong({"bang": "stock_entries", "select": "*, lines:stock_entry_lines(*)", "loc": [{"op": "eq", "cot": "id", "gt": ten}]},
			ADMIN)["data"]
		if not ds:
			return None
		r, k = ds[0], self.khoa_cua.get
		xuat = r["type"] in ("export", "transfer")
		dong = []
		for d in r["lines"] or []:
			lo = None
			if d["batch_id"] and not xuat and not d["batch_id"].startswith("~"):
				ma, _, vung = d["batch_id"].rpartition("::")
				lo = f"{self._ma_lo(st, ma)}@{vung}"
			dong.append(_bo_null({"sp": k(d["product_id"]), "lo": lo, "dv": d["unit_name"], "sl_cs": d["qty_in_base_uom"],
				"sl_gd": d["qty_in_transaction_uom"], "dv_gd": d["transaction_uom"], "hs": d["conversion_factor_snapshot"],
				"gia": round(flt(d["unit_cost"]), 2), "ghi_chu": d["notes"]}))
		vet = []
		if xuat:
			for ma, kho, sl, gia in frappe.db.sql("""SELECT e.`batch_no`, e.`warehouse`, SUM(ABS(e.`qty`)),
					ABS(SUM(e.`stock_value_difference`)) / NULLIF(ABS(SUM(e.`qty`)), 0)
				FROM `tabSerial and Batch Bundle` b JOIN `tabSerial and Batch Entry` e ON e.`parent` = b.`name`
				WHERE b.`voucher_type` = 'Stock Entry' AND b.`voucher_no` = %s AND b.`type_of_transaction` = 'Outward' AND IFNULL(e.`batch_no`, '') != ''
				GROUP BY e.`batch_no`, e.`warehouse`""", ten):
				vet.append({"lo": f"{self._ma_lo(st, ma)}@{self.vung.get(kho)}", "sl": flt(sl), "gia": round(flt(gia), 2)})
		return _bo_null({"ma": f"<{nhan}>", "nhan": nhan, "loai": r["type"], "status": r["status"], "vung": r["warehouse_zone"],
			"vung_dich": r["dest_warehouse_zone"], "ncc": k(r["supplier_id"]), "ly_do_xuat": r["issue_reason"], "ghi_chu": r["notes"],
			"luc_ghi_so": self._luc(r["posted_at"]), "lap_boi": k(r["created_by"]), "so_don": len(r["ref_order_ids"] or []),
			"dong": _xep(dong) or None, "vet": _xep(vet) or None})

	def _phieu_kho_pn(self, nhan: str, ten: str, r: dict, st: dict) -> dict:
		"""Phiếu kho của phiếu nhập = chính PI (⚠K §7.2 #14): dòng = dòng PI, lô theo gói lô (cả gói đã huỷ), giá = giá vốn mỗi đơn vị cơ sở."""
		from nppsale.rpc.phieu_nhap import _lo_cua_dong

		lo_dong = _lo_cua_dong(ten)
		dong = []
		for d in frappe.get_all("Purchase Invoice Item", filters={"parent": ten, "parenttype": "Purchase Invoice"}, fields=["name", "item_code", "uom",
				"qty", "stock_qty", "conversion_factor", "warehouse", "valuation_rate"], order_by="idx asc"):
			lo = lo_dong.get(d.name)
			gia = frappe.db.sql("""SELECT e.`incoming_rate` FROM `tabSerial and Batch Entry` e JOIN `tabSerial and Batch Bundle` b ON b.`name` = e.`parent`
				WHERE b.`voucher_type` = 'Purchase Invoice' AND b.`voucher_no` = %s AND b.`voucher_detail_no` = %s LIMIT 1""", (ten, d.name))
			dong.append({"sp": self.khoa_cua.get(d.item_code), "lo": f"{self._ma_lo(st, lo)}@{self.vung.get(d.warehouse)}" if lo else None,
				"dv": d.uom, "sl_cs": d.stock_qty, "sl_gd": d.qty, "dv_gd": d.uom, "hs": d.conversion_factor,
				"gia": round(flt(gia[0][0] if gia else d.valuation_rate), 2)})
		return _bo_null({"ma": f"<{nhan}>", "loai": "import", "status": "posted" if r["status"] == "completed" else "cancelled",
			"vung": r["warehouse_zone"], "ncc": self.khoa_cua.get(r["supplier_id"]), "ghi_chu": r["notes"], "luc_ghi_so": "@luc_goi",
			"lap_boi": self.khoa_cua.get(r["created_by"]), "so_don": 0, "dong": _xep([_bo_null(x) for x in dong])})

	def _phieu_kho_ptn(self, nhan: str, ten: str, st: dict) -> dict:
		"""Phiếu kho của phiếu trả NCC = một tờ đã / thôi ghi sổ của chuỗi (⚠K §7.2 #14): mỗi (dòng, lô) của gói lô Outward — cả gói đã huỷ — so theo
		(mặt hàng, lô, SL cơ sở, giá lô) (§6.0 / §4.5 ⚠K: nppsale một dòng phiếu kho mỗi lô lấy, ĐV của dòng mà SL là cơ sở)."""
		pi = frappe.db.get_value("Purchase Invoice", ten, ["docstatus", "supplier", "npp_hoan_thanh_boi", "npp_kho_nhap", "set_warehouse",
			"npp_ghi_chu"], as_dict=True)
		dong = [{"sp": self.khoa_cua.get(sp), "lo": f"{self._ma_lo(st, lo)}@{self.vung.get(kho)}", "sl_cs": abs(flt(sl)), "gia": round(flt(gia), 2)}
			for sp, lo, kho, sl, gia in frappe.db.sql("""SELECT d.`item_code`, e.`batch_no`, e.`warehouse`, e.`qty`, e.`incoming_rate`
				FROM `tabPurchase Invoice Item` d JOIN `tabSerial and Batch Bundle` b ON b.`voucher_type` = 'Purchase Invoice'
					AND b.`voucher_no` = d.`parent` AND b.`voucher_detail_no` = d.`name`
				JOIN `tabSerial and Batch Entry` e ON e.`parent` = b.`name`
				WHERE d.`parent` = %s AND d.`parenttype` = 'Purchase Invoice'""", ten)]
		return _bo_null({"ma": f"<{nhan}>", "loai": "export", "status": "posted" if pi.docstatus == 1 else "cancelled",
			"vung": self.vung.get(pi.npp_kho_nhap or pi.set_warehouse), "ncc": self.khoa_cua.get(pi.supplier), "luc_ghi_so": "@luc_goi",
			"lap_boi": self.khoa_cua.get(pi.npp_hoan_thanh_boi), "so_don": 0, "ghi_chu": pi.npp_ghi_chu, "dong": _xep([_bo_null(x) for x in dong])})

	def _chuan_mong(self, ct: dict) -> dict:
		"""Ảnh chụp nppsale → cùng dạng bên Frappe theo các luật chuẩn hoá ở đầu tệp."""
		ct = copy.deepcopy(ct or {})
		# NPP thứ hai (`chi_nppsale`) không có ở bản Frappe (một site một NPP — câu 2)
		ct["ptn"] = [p for p in ct.get("ptn") or [] if p.get("npp", "A") == "A"] or None
		ma_nhan = {p["ma"]: p["nhan"] for p in [*(ct.get("pn") or []), *(ct.get("ptn") or []), *(ct.get("phieu_chi") or [])]
			if p.get("ma") and p.get("nhan")}

		def nhan(ma):
			return f"<{ma_nhan[ma]}>" if ma in ma_nhan else ma

		def lo(ma):
			m = re.fullmatch(r"(.+)-(\d{3})(@\w+)?", ma or "")
			return f"{nhan(m.group(1))}-{m.group(2)}{m.group(3) or ''}" if m and m.group(1) in ma_nhan else ma

		def chu(s):
			for ma in sorted(ma_nhan, key=len, reverse=True):
				s = re.sub(rf"(?<![\w-]){re.escape(ma)}(?![\w-])", nhan(ma), s) if s else s
			return s

		ghi_chu_pn = {}
		for p in ct.get("pn") or []:
			p["ma"] = f"<{p['nhan']}>"  # câu 18: phiếu tạm cũng có số
			if p.get("phieu_kho"):
				p["phieu_kho"] = nhan(p["phieu_kho"])
			if p.get("no"):
				p["no"] = "PN:" + nhan(p["no"].split(":", 1)[1])
			ghi_chu_pn[p["ma"]] = p.get("ghi_chu")
		for p in ct.get("ptn") or []:
			p["ma"] = f"<{p['nhan']}>"
			p.pop("seq", None)  # dãy `PTNCC-.####` của site (không lấy lại số đã xoá — ⚠K V27): so theo nhãn
			if p.get("phieu_kho"):
				p["phieu_kho"] = p["ma"]  # phiếu kho = chính tờ (⚠K §7.2 #14 — nppsale `XK-<giờ>`)
			if p.get("no"):
				p["no"] = "PTNCC:" + p["ma"]
			ghi_chu_pn[p["ma"]] = p.get("ghi_chu")
		for x in ct.get("lo") or []:
			x["ma"] = lo(x["ma"])
			x["gia"] = round(flt(x.get("gia")), 2)
			if x.get("status") == "cancelled":
				x["nhap"] = 0.0  # §7.2 #26: lô chưa phát sinh của cổng batches
		for x in ct.get("no") or []:
			loai, ma = x["khoa"].split(":", 1)
			x["khoa"] = f"{loai}:{nhan(ma)}"
			if x.get("phieu_kho"):
				x["phieu_kho"] = nhan(ma) if loai == "PTNCC" else nhan(x["phieu_kho"])  # phiếu kho của phiếu trả = chính tờ
			if x.get("so_hd"):
				x["so_hd"] = nhan(x["so_hd"])  # phiếu trả: số HĐ = mã phiếu (mig 228 / 240)
			if x.get("ghi_chu"):
				x["ghi_chu"] = _ngay_trong_loi(chu(x["ghi_chu"]))  # ngày trong ghi chú ("gộp ngày <@hom_nay>" — V72) → ngày VN thật
		for x in ct.get("gia_nhap") or []:
			if x.get("nguon"):
				x["nguon"] = nhan(x["nguon"])
		for x in ct.get("tra_no") or []:
			loai, ma = x["no"].split(":", 1)
			x["no"] = f"{loai}:{nhan(ma)}"
			if x.get("phieu_chi"):
				x["phieu_chi"] = nhan(x["phieu_chi"])
			if x.get("ghi_chu"):
				x["ghi_chu"] = chu(x["ghi_chu"])
		ct["tra_no"] = _gop_tra_truoc(ct.get("tra_no") or []) or None
		for x in ct.get("phieu_chi") or []:
			x["ma"] = nhan(x["ma"])
			x.pop("seq", None)  # dãy `PCNCC-.####` của site: so theo nhãn (như phiếu nhập — câu 18)
			if x.get("tra_truoc"):
				loai, ma = x["tra_truoc"].split(":", 1)
				x["tra_truoc"] = f"{loai}:{nhan(ma)}"
		ma_pk = {x["ma"]: x["nhan"] for x in ct.get("phieu_kho") or [] if x.get("nhan") and x.get("ma")}  # mã phiếu kho / kiểm kê → nhãn

		def chu_pk(s):
			for ma in sorted(ma_pk, key=len, reverse=True):
				s = re.sub(rf"(?<![\w-]){re.escape(ma)}(?![\w-])", f"<{ma_pk[ma]}>", s) if s else s
			return s

		for x in ct.get("chi_phi") or []:  # chi phí hao hụt kiểm kê (M6): mã phiếu kiểm kê → nhãn
			for c in ("mo_ta", "tham_chieu", "nguon_pk"):
				if x.get(c):
					x[c] = chu_pk(x[c])
		pk = []
		for x in ct.get("phieu_kho") or []:
			if x.get("nhan"):  # phiếu kho tay (M4): mã → nhãn (Frappe cấp `XKL-` / `CKL-` / `IN-…` / `PN-`); vết lấy lô gộp theo (lô, giá) ở mức phiếu
				x["ma"] = f"<{x['nhan']}>"
				gop: dict = {}
				for d in x.get("dong") or []:
					d.pop("sl", None)
					for v in d.pop("vet", None) or []:
						kv = (lo(v["lo"]), round(flt(v["gia"]), 2))
						gop[kv] = gop.get(kv, 0.0) + flt(v["sl"])
					if x.get("loai") in ("export", "transfer"):
						d.pop("lo", None)
					elif d.get("lo"):
						d["lo"] = lo(d["lo"])
					d["gia"] = round(flt(d.get("gia")), 2)
				x["dong"] = _xep(_so(x.get("dong") or [])) or None
				x["vet"] = _xep([{"lo": a, "sl": sl, "gia": g} for (a, g), sl in gop.items()]) or None
				pk.append(_bo_null(x))
				continue
			tra = _RE_XK_PTN.fullmatch(x.get("ghi_chu") or "")  # phiếu `XK-<giờ>` của phiếu trả NCC — nhận theo ghi chú của hàm
			if tra and tra.group(1) in ma_nhan:
				x["ma"] = nhan(tra.group(1))
			elif x.get("ma") in ma_nhan:
				x["ma"] = nhan(x["ma"])
			else:
				continue  # phiếu kho của HĐ / hoàn kho / phiếu kho tay — cổng stock_entries (M4)
			x.pop("ghi_chu", None)
			if ghi_chu_pn.get(x["ma"]):
				x["ghi_chu"] = ghi_chu_pn[x["ma"]]
			for d in x.get("dong") or []:
				d.pop("sl", None)
				d.pop("vet", None)
				if tra:  # nppsale ghi SL CƠ SỞ dưới ĐV của dòng, hệ số 1 ("CHÉP Y NGUYÊN 071") — Frappe so (mặt hàng, lô, SL cơ sở, giá lô)
					for c in ("dv", "hs", "sl_gd", "dv_gd"):
						d.pop(c, None)
				d["lo"] = lo(d.get("lo"))
				d["gia"] = round(flt(d.get("gia")), 2)
			x["dong"] = _xep(_so(x.get("dong") or []))
			pk.append(x)
		ct["phieu_kho"] = pk or None
		for x in ct.get("hd") or []:
			x.pop("phieu_kho", None)
		for x in ct.get("tra_khach") or []:
			x["ma"] = f"<{x['nhan']}>"  # dãy `PT-.####` của site: so theo nhãn
		for m in NEN_TINH:  # M8: mục chỉ ghi khi khác nền — vắng mặt = như nền
			if m not in ct:
				ct[m] = copy.deepcopy(self.vang["nen"]["ct_nen"].get(m))
		for x in ct.get("ncc") or []:
			if x.get("ghi_chu"):
				x["ghi_chu"] = _ngay_trong_loi(x["ghi_chu"])  # "Gộp từ NCC … ngày <@hom_nay>." (V72) → ngày VN thật
		return {m: (_xep(_so(ct.get(m))) if isinstance(ct.get(m), list) and m != "nhan" else ct.get(m)) or None for m in MUC_SO} | {
			"nhan": sorted(ct.get("nhan") or [])}

	def _chuan_tra(self, tra, ct: dict | None = None):
		"""`tra` của bước bên nppsale → cùng dạng: bỏ `entry_id` (HĐ bán: phiếu kho = chính HĐ; nhập kho tay / phiếu trả khách: nhãn đặt từ chính kết
		quả), id phiếu kho hoàn → có / không; mã lô của phiếu nhập trong dòng đọc (`batch_code` — V87) → "<nhãn>-NNN" (câu 18); mã phiếu kho trong
		dòng đọc (`entry_code` — V85) → "<nhãn>"; số → float."""
		ma_nhan = {p["ma"]: p["nhan"] for p in (ct or {}).get("pn") or [] if p.get("ma")}
		ma_khac = {p["ma"]: p["nhan"] for p in [*((ct or {}).get("ptn") or []), *((ct or {}).get("phieu_chi") or []),
			*((ct or {}).get("phieu_kho") or [])] if p.get("ma") and p.get("nhan")}

		def nhan(ma):
			n = ma_nhan.get(ma) or ma_khac.get(ma)
			return f"<{n}>" if n else ma

		def mot(x):
			x = dict(x)
			x.pop("entry_id", None)
			if "import_entry_id" in x:
				x["import_entry_id"] = bool(x["import_entry_id"])
			if str(x.get("id") or "").startswith("pc:"):  # phiếu chi NCC: mã theo nhãn (dãy PCNCC- của site)
				x["id"] = "pc:" + nhan(x["id"][3:])
				x["code"] = nhan(x.get("code"))
			if str(x.get("expense_id") or "").startswith("cp:"):  # phiếu chi hao hụt kiểm kê (M6): "cp:<nhãn phiếu kiểm kê>"
				x["expense_id"] = "cp:" + nhan(x["expense_id"][3:])
			if str(x.get("payment_id") or "").startswith("tra:"):  # khoản trả: "tra:<khoá nợ>"
				loai, _, ma = x["payment_id"][4:].partition(":")
				x["payment_id"] = f"tra:{loai}:{nhan(ma)}"
			m = re.fullmatch(r"(.+)-(\d{3})", x.get("batch_code") or "")
			if m and m.group(1) in ma_nhan:
				x["batch_code"] = f"<{ma_nhan[m.group(1)]}>-{m.group(2)}"
			if x.get("entry_code"):  # dòng v_stock_movements (V85): mã phiếu kho → "<nhãn>"
				x["entry_code"] = nhan(x["entry_code"])
			return x

		if isinstance(tra, dict):
			tra = mot(tra)
		if isinstance(tra, list):
			return _xep(_so([mot(x) if isinstance(x, dict) else x for x in tra]))
		return _so(tra)

	# ------------------------------------------------------------------------------------------------ một kịch bản
	def _mot(self, t: dict) -> list[str]:
		t = copy.deepcopy(t)
		mong = t["mong"]
		lech = LECH.get(t["ma"])
		if lech:
			lech[0](t, mong)
		sai = []
		st = {"ma": t["ma"], "nhan": {}}
		# kịch bản có bước phiếu kho tay (M4 — kể cả V86 của M3): mã chứng từ trong câu lỗi so theo nhãn (Frappe cấp `XKL-` / `CKL-` / `IN-…` / `PN-`;
		# phiếu kho của HĐ / PI = chính chứng từ)
		chuan_ma = any(b["buoc"] in BUOC_PK for b in t["buoc"])
		ma_mong = self._ma_mong(t, mong) if chuan_ma else {}
		# nhãn chỉ bước `chi_nppsale` lập (NPP thứ hai) — không có ở bản Frappe
		bo_nhan = {f"{b['buoc']}:{b['nhan']}" for b in t["buoc"] if b.get("chi_nppsale") and b["buoc"] in LOAI_CT} - {
			f"{b['buoc']}:{b['nhan']}" for b in t["buoc"] if not b.get("chi_nppsale") and b["buoc"] in LOAI_CT}
		if mong.get("ct") and mong["ct"].get("nhan"):
			mong["ct"]["nhan"] = [x for x in mong["ct"]["nhan"] if x not in bo_nhan]
		for i, (b, m) in enumerate(zip(t["buoc"], mong["buoc"], strict=False)):
			if b.get("chi_nppsale"):
				continue
			nhan = f"{t['ma']} bước {i + 1} ({b['buoc']} — {b['nguoi']})"
			if b["buoc"] == "nhap_kho" and m.get("ok") and isinstance(m.get("tra"), dict):
				m["tra"]["entry_code"] = f"<{b['nhan']}>"  # mã trình duyệt gửi ↔ tên chứng từ Frappe — so theo nhãn
			ket, tv = self._buoc(b, st)
			if m["ok"]:
				if "error" in ket:
					return [*sai, f"{nhan}: nppsale ghi được — bản Frappe báo {ket['error']['code']} {ket['error']['message'][:400]} "
						f"{(ket['error'].get('details') or '')[:300]}"]
				if m.get("tra") is not None and _gap_dv(self._chuan_tra(m["tra"], mong.get("ct"))) != _gap_dv(_so(tv)):
					sai.append(f"{nhan}: trả về {json.dumps(tv, ensure_ascii=False)[:600]} ≠ nppsale "
						f"{json.dumps(self._chuan_tra(m['tra'], mong.get('ct')), ensure_ascii=False)[:600]}")
				continue
			if "error" not in ket:
				return [*sai, f"{nhan}: nppsale báo {m['ma_loi']} {m['loi'][:300]} — bản Frappe lại ghi được"]
			loi_f, loi_m = _gio_trong_loi(ket["error"]["message"]), _ngay_trong_loi(m["loi"])
			if chuan_ma:
				loi_f, loi_m = _thay_ma(loi_f, self._ten_trong_loi(st)), _thay_ma(loi_m, ma_mong)
			if (ket["error"]["code"], _dv_loi(loi_f)) != (m["ma_loi"], _dv_loi(loi_m)):
				sai.append(f"{nhan}: lỗi {ket['error']['code']} {loi_f[:400]} ≠ nppsale {m['ma_loi']} {loi_m[:400]}")
			if not b.get("tiep"):
				break
		ct = _gap_dv(self._ct(st))
		ct_mong = _gap_dv(self._chuan_mong(mong.get("ct")))
		for k in MUC_SO:
			if ct.get(k) != ct_mong.get(k):
				sai.append(f"{t['ma']}: {k} lệch ở {'; '.join(XH._cho_lech(ct.get(k), ct_mong.get(k)))[:3000]}")
		from nppsale.kham_so import quet_cong_no_ncc, quet_kho_mua

		ncc = [v for kk, v in self.ma.items() if re.fullmatch(r"S\d", kk)]
		for d in quet_cong_no_ncc(ncc):
			sai.append(f"{t['ma']}: khám sổ NCC nhóm {d.get('nhom')} {d.get('loai')} — {d.get('chung_tu')}: {d.get('chi_tiet')}")
		# M9 — khám sổ P4 (đặc tả §8.1): tồn lô = Σ gói lô = Bin = Σ sổ kho, lô không âm, giá nhập một giá mỗi đơn vị… trên hàng / NCC của bộ dữ liệu
		for d in quet_kho_mua([v for kk, v in self.ma.items() if re.fullmatch(r"[A-Z]", kk)], ncc)["can_xem"]:
			sai.append(f"{t['ma']}: khám sổ kho / mua nhóm {d.get('nhom')} {d.get('loai')} — {d.get('chung_tu')}: {d.get('chi_tiet')}")
		return sai

	@staticmethod
	def _ma_mong(t: dict, mong: dict) -> dict:
		"""Mã nppsale trong câu lỗi → "<nhãn>" (từ M4): mã phiếu kho tay của bước `pk` / `nhap_kho`, mã phiếu nhập / trả NCC / HĐ trong ảnh chụp."""
		ra: dict = {}
		for b in t["buoc"]:
			ma = ((b.get("dau") or {}).get("entry_code") if b["buoc"] == "pk" else (b.get("p") or {}).get("entry_code") if b["buoc"] == "nhap_kho"
				else None)
			if ma:
				ra.setdefault(ma, f"<{b['nhan']}>")
		for muc in ("pn", "ptn", "hd"):
			for x in (mong.get("ct") or {}).get(muc) or []:
				if x.get("ma") and x.get("nhan"):
					ra.setdefault(x["ma"], f"<{x['nhan']}>")
		return ra

	def _ten_trong_loi(self, st: dict) -> dict:
		"""Tên Frappe trong câu lỗi → "<nhãn>" (từ M4): phiếu kho tay (`pk:`), phiếu nhập / trả NCC (cả chuỗi amend), HĐ bán, chứng từ nhập lại của
		phiếu trả khách (`tk:` — tờ ghi có có kho / Stock Entry `NL-`)."""
		ra: dict = {}
		for k, v in st["nhan"].items():
			loai, _, nhan = k.partition(":")
			if not v or loai not in ("pk", "pn", "ptn", "hd", "tk"):
				continue
			if loai in LOAI_CT:
				ten, x = [], self._goc(v)
				for _ in range(50):
					if not x:
						break
					ten.append(x)
					x = frappe.db.get_value("Purchase Invoice", {"amended_from": x}, "name")
			elif loai == "tk":
				r = frappe.db.get_value("NPP Phieu Tra", v, ["to_ghi_co", "phieu_nhap_kho"], as_dict=True) or frappe._dict()
				ten = [x for x in (r.get("to_ghi_co"), r.get("phieu_nhap_kho")) if x]
			else:
				ten = [v]
			for x in ten:
				ra.setdefault(x, f"<{nhan}>")
		return ra

	# ------------------------------------------------------------------------------------------------ kịch bản [Frappe] (`nguon: dac_ta`)
	def _v02c(self, t: dict) -> list[str]:
		"""Hai tiến trình cùng Hoàn thành một phiếu nháp: không chạy hai tiến trình thật được trong một giao dịch bài (nháp chưa commit, tiến trình kia
		không thấy) — kiểm điều kiện đủ của luật: (a) câu ĐẦU của thân hàm (sau bước chuẩn bị) là khoá Bin, câu kế là khoá PI `FOR UPDATE`, mọi câu
		đọc PI / dòng sau đó — lượt thứ hai xếp hàng ở khoá PI rồi thấy docstatus 1; (b) gọi lần hai trả đúng tên, không nhập kho / lô / nợ lần hai."""
		sai = []
		st = {"ma": t["ma"], "nhan": {}}
		ket, _ = self._buoc(t["buoc"][0], st)
		if "error" in ket:
			return [f"V02c: lập phiếu nháp hỏng {ket['error']}"]
		ten = self._ten(st, "pn:P")
		cau, moc = [], []
		goc_sql, goc_sp = frappe.db.sql, frappe.db.savepoint

		def ghi_sql(q, *a, **kw):
			cau.append(str(q))
			return goc_sql(q, *a, **kw)

		def ghi_sp(ten_sp, *a, **kw):
			kq = goc_sp(ten_sp, *a, **kw)
			if ten_sp == "npp_cong_rpc":
				moc.append(len(cau))  # sau câu SAVEPOINT: câu kế là câu đầu của thân hàm
			return kq

		with patch.object(frappe.db, "sql", ghi_sql), patch.object(frappe.db, "savepoint", ghi_sp):
			k1 = self._goi("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		k2 = self._goi("TK", "complete_purchase_invoice", {"p_invoice_id": ten})
		if "error" in k1 or "error" in k2 or k1["data"] != ten or k2["data"] != ten:
			sai.append(f"V02c: hai lượt trả {k1} / {k2}, mong {ten} cả hai")
		than = [" ".join(q.split()) for q in cau[moc[0]:]] if moc else []
		if len(than) < 2 or not ("`tabBin`" in than[0] and "FOR UPDATE" in than[0]):
			sai.append(f"V02c: câu đầu thân hàm phải là khoá Bin — {than[:1]}")
		elif not ("`tabPurchase Invoice`" in than[1] and "FOR UPDATE" in than[1]):
			sai.append(f"V02c: câu thứ hai phải là khoá PI FOR UPDATE — {than[1][:200]}")
		so = (frappe.db.count("Batch", {"reference_name": ten}), frappe.db.count("NPP Cong No NCC", {"chung_tu": ten}),
			frappe.db.count("Stock Ledger Entry", {"voucher_no": ten, "is_cancelled": 0}))
		if so != (1, 1, 1):
			sai.append(f"V02c: lô / dòng nợ / dòng sổ kho = {so}, mong (1, 1, 1) — nhập kho đúng một lần")
		return sai

	def _v12b(self, t: dict) -> list[str]:
		"""Hàng KHÔNG lô X (allow_negative_stock) + NPP cho bán vượt tồn: PN 48 → bán 30 → huỷ PN được, Bin kho bán −30, dòng nợ PN bỏ; huỷ HĐ →
		Bin 0 (câu 15, mig 238)."""
		sai = []
		st = {"ma": t["ma"], "nhan": {}}
		bin_x = lambda: flt(frappe.db.get_value("Bin", {"item_code": self.ma["X"], "warehouse": self.cd.kho_ban}, "actual_qty"))  # noqa: E731
		for i, b in enumerate(t["buoc"]):
			ket, _ = self._buoc(b, st)
			if "error" in ket:
				return [f"V12b bước {i + 1} ({b['buoc']}): {ket['error']['code']} {ket['error']['message'][:300]}"]
			if b["buoc"] == "pn_huy":
				ten = self._ten(st, "pn:P")
				if (bin_x(), frappe.db.get_value("Purchase Invoice", ten, "docstatus"), frappe.db.count("NPP Cong No NCC", {"chung_tu": ten})) != (
						-30, 2, 0):
					sai.append(f"V12b: sau huỷ PN mong Bin −30, PI huỷ, không dòng nợ — có Bin {bin_x()}")
		if bin_x() != 0:
			sai.append(f"V12b: sau huỷ HĐ mong Bin 0 — có {bin_x()}")
		return sai

	def _v19b(self, t: dict) -> list[str]:
		"""Hàng KHÔNG lô X (allow_negative_stock) + NPP cho bán vượt tồn: kho date có 15 (bước `nhap_kho` — post_stock_import, M4) → phiếu trả NCC
		20 → gửi được, Bin kho date −5 (giá phần âm do lõi định — §2.6); huỷ → Bin về 15. Cờ tắt → INSUFFICIENT_STOCK."""
		sai = []
		st = {"ma": t["ma"], "nhan": {}}
		x, kho = self.ma["X"], self.cd.kho_can_date
		bin_x = lambda: flt(frappe.db.get_value("Bin", {"item_code": x, "warehouse": kho}, "actual_qty"))  # noqa: E731
		for i, b in enumerate(t["buoc"]):
			if b["buoc"] == "ptn_gui":  # cờ NPP tắt: hàng không lô cũng chặn như nppsale
				frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 0)
				frappe.local._npp_cai_dat_ban = None
				ket, _ = self._buoc(b, st)
				if (ket.get("error") or {}).get("message", "")[:20] != "INSUFFICIENT_STOCK |":
					sai.append(f"V19b: cờ tắt mong INSUFFICIENT_STOCK — có {ket}")
				frappe.db.set_single_value("NPP Cai Dat", "cho_ban_vuot_ton", 1)
				frappe.local._npp_cai_dat_ban = None
			ket, _ = self._buoc(b, st)
			if "error" in ket:
				return [*sai, f"V19b bước {i + 1} ({b['buoc']}): {ket['error']['code']} {ket['error']['message'][:300]}"]
			ten = self._ten(st, "ptn:R") if st["nhan"].get("ptn:R") else None
			if b["buoc"] == "ptn_gui" and (bin_x(), frappe.db.get_value("Purchase Invoice", ten, "docstatus"),
					flt(frappe.db.get_value("NPP Cong No NCC", {"chung_tu": ten}, "so_tien"))) != (-5, 1, -20000):
				sai.append(f"V19b: sau gửi mong Bin −5, tờ ghi sổ, nợ −20000 — có Bin {bin_x()}")
		if (bin_x(), frappe.db.count("NPP Cong No NCC", {"chung_tu": self._ten(st, "ptn:R")})) != (15, 0):
			sai.append(f"V19b: sau huỷ mong Bin 15, không dòng nợ — có Bin {bin_x()}")
		return sai

	def _bin_x(self, kho: str | None = None) -> float:
		return flt(frappe.db.get_value("Bin", {"item_code": self.ma["X"], "warehouse": kho or self.cd.kho_ban}, "actual_qty"))

	def _chay_het(self, t: dict, st: dict) -> list[str]:
		for i, b in enumerate(t["buoc"]):
			ket, _ = self._buoc(b, st)
			if "error" in ket:
				return [f"{t['ma']} bước {i + 1} ({b['buoc']}): {ket['error']['code']} {ket['error']['message'][:300]}"]
		return []

	def _v43c(self, t: dict) -> list[str]:
		"""Hàng KHÔNG lô X (allow_negative_stock) + NPP cho bán vượt tồn, kho bán có 10 (post_stock_import): xuất lẻ 24 cái → ghi sổ được, Bin kho bán
		−14 (CFD-05 B — chỉ hàng không lô được âm, cần cả cờ mặt hàng lẫn cờ NPP)."""
		dau = self._bin_x()
		sai = self._chay_het(t, {"ma": t["ma"], "nhan": {}})
		if not sai and self._bin_x() - dau != -14:
			sai.append(f"V43c: mong Bin kho bán đổi −14 (10 nhập − 24 xuất) — đổi {self._bin_x() - dau}")
		return sai

	def _v44c(self, t: dict) -> list[str]:
		"""Hàng KHÔNG lô X + cho bán vượt tồn, Bin 0: xuất lẻ 3 cái → ghi sổ (Bin −3); huỷ được (lõi đảo sổ kho) → Bin về như cũ — nppsale
		NO_CONSUMPTION_TRACE (⚠K có lợi: §3.19 Frappe bước 5)."""
		dau = self._bin_x()
		st = {"ma": t["ma"], "nhan": {}}
		sai = self._chay_het({**t, "buoc": t["buoc"][:3]}, st)
		if sai:
			return sai
		if self._bin_x() - dau != -3:
			sai.append(f"V44c: sau ghi sổ mong Bin −3 — đổi {self._bin_x() - dau}")
		ket, tv = self._buoc(t["buoc"][3], st)
		if "error" in ket or tv != {"cancelled": True, "reversed": True, "lines_reversed": 1}:
			sai.append(f"V44c: huỷ mong [true, true, 1] — có {ket.get('error') or tv}")
		if self._bin_x() != dau:
			sai.append(f"V44c: sau huỷ mong Bin về {dau} — có {self._bin_x()}")
		return sai

	def _v57b(self, t: dict) -> list[str]:
		"""Việc đêm 01:00 VN (`nppsale.rpc.lo_kho.ra_soat_kho_date` — hooks.py) rà soát kho date cho NPP, không người: ngưỡng 100, lô L46 (+46) tồn 10 ở
		kho bán → MỘT phiếu `CKL-` `chuyen_date_tu_dong` chở 10 cái L46 sang kho date, `npp_chuyen_vung_luc` ghi, người không ghi; chạy lại → không
		phiếu mới (đặc tả §3.20, V57b)."""
		from nppsale.rpc.lo_kho import ra_soat_kho_date

		st = {"ma": t["ma"], "nhan": {}}
		sai = self._chay_het({**t, "buoc": [b for b in t["buoc"] if b["buoc"] != "viec_dem"]}, st)
		if sai:
			return sai
		dau = self._ckl_tu_dong()
		self._ve_admin()
		ra_soat_kho_date()
		moi = self._ckl_tu_dong() - dau
		dong = frappe.db.sql("""SELECT b.`voucher_no`, e.`batch_no`, e.`warehouse`, e.`qty` FROM `tabSerial and Batch Bundle` b
			JOIN `tabSerial and Batch Entry` e ON e.`parent` = b.`name` WHERE b.`voucher_type` = 'Stock Entry' AND b.`voucher_no` IN %s
			AND e.`batch_no` = 'L46'""", (tuple(moi) or ("",),))
		if len(moi) != 1 or sorted((k, flt(q)) for _se, _lo, k, q in dong) != sorted([(self.cd.kho_ban, -10.0), (self.cd.kho_can_date, 10.0)]):
			sai.append(f"V57b: lượt đêm 1 mong MỘT phiếu CKL- chở L46 10 cái bán → date — có phiếu {moi}, dòng {dong}")
		lo = frappe.db.get_value("Batch", "L46", ["npp_chuyen_vung_luc", "npp_chuyen_vung_boi"], as_dict=True)
		if not lo.npp_chuyen_vung_luc or abs((get_datetime(lo.npp_chuyen_vung_luc) - now_datetime()).total_seconds()) > 300 or lo.npp_chuyen_vung_boi:
			sai.append(f"V57b: dấu chuyển vùng mong lúc ≈ bây giờ, không người — có {lo}")
		ra_soat_kho_date()
		if self._ckl_tu_dong() - dau != moi:
			sai.append("V57b: lượt đêm 2 không được lập phiếu mới")
		if self.nhat_ky:
			sai.append(f"V57b: việc đêm ghi Error Log {self.nhat_ky}")
		return sai

	def _v80(self, t: dict) -> list[str]:
		"""Luồng cũ + bảng không port (đặc tả §3.21, §4.8, V80): `post_stock_export` (giữ tên) và mọi lời ghi vào `swap_stock_movements` /
		`purchase_orders` / `purchase_order_lines` → đúng câu `LEGACY_FLOW_REMOVED: chức năng đã gỡ` (P0001); đọc ba bảng trả `[]` (không 404 /
		PGRST205)."""
		sai = []
		st = {"ma": t["ma"], "nhan": {}}
		for i, b in enumerate(t["buoc"]):
			ket, tv = self._buoc(b, st)
			ten = f"V80 bước {i + 1} ({b['buoc']} {b.get('ten') or b.get('bang')})"
			if b["buoc"] == "doc_bang":
				if "error" in ket or tv != []:
					sai.append(f"{ten}: mong [] — có {ket.get('error') or tv}")
			elif (ket.get("error") or {}).get("code") != "P0001" or ket["error"].get("message") != "LEGACY_FLOW_REMOVED: chức năng đã gỡ":
				sai.append(f"{ten}: mong P0001 LEGACY_FLOW_REMOVED: chức năng đã gỡ — có {ket.get('error') or tv}")
		return sai

	# ------------------------------------------------------------------------------------------------ chạy
	def test_kich_ban_vang(self):
		chi = os.environ.get("NPP_VANG_CHI")
		sai, bo = [], {"chưa dựng": [], "chỉ nppsale": [], "đặc tả chưa kiểm": []}
		da_chay = 0
		for t in self.vang["tinh_huong"]:
			if chi and not any(t["ma"].startswith(x) for x in chi.split(",")):
				continue
			if moc_cua(t["ma"]) not in DA_DUNG:
				bo["chưa dựng"].append(t["ma"])
				continue
			if t.get("chi_nppsale"):
				bo["chỉ nppsale"].append(t["ma"])
				continue
			if t.get("nguon") == "dac_ta" and t["ma"] not in KIEM_DAC_TA:
				bo["đặc tả chưa kiểm"].append(t["ma"])
				continue
			frappe.db.savepoint("npp_th")
			frappe.local._npp_cai_dat_ban = None
			ma, khoa_cua = dict(self.ma), dict(self.khoa_cua)  # NCC lập trong kịch bản (@S5 — M8) chỉ sống trong kịch bản ấy
			try:
				sai += getattr(self, KIEM_DAC_TA[t["ma"]])(t) if t.get("nguon") == "dac_ta" else self._mot(t)
				da_chay += 1
			finally:
				frappe.db.rollback(save_point="npp_th")
				self._ve_admin()
				self.ma, self.khoa_cua = ma, khoa_cua
		print(f"\nkho_mua_vang: chạy {da_chay} kịch bản; " + "; ".join(f"{k} {len(v)}" for k, v in bo.items()))
		self.assertFalse(sai, "\n".join(sai))
		self.assertFalse(self.nhat_ky, f"Error Log ghi trong bài: {self.nhat_ky}")
