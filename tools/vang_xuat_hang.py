#!/usr/bin/env python3
"""Dữ liệu vàng cho XUẤT HÀNG / HUỶ HĐ / SỬA HĐ (`post_invoice`, `cancel_invoice`, `reissue_invoice` — mig 125 / 128 / 162 / 174 / 183 / 186 /
213 / 215 / 217 / 227 / 247) — chạy CHÍNH hàm + trigger của nppsale ở Postgres
tham chiếu (schema_full.sql). Phần chưa gồm: hàng trả / hàng đổi kèm đơn (phiếu trả tự sinh) — bộ riêng khi dựng phiếu trả.

Mỗi tình huống: tạo đơn (create_order_with_lines, đơn submitted) → xuất hàng (post_invoice) dưới đúng người, mỗi lệnh một giao dịch;
ghi lại lỗi hoặc: mã HĐ, tiền (subtotal / vat / total), hạn trả, dòng HĐ, lô đã lấy theo từng dòng (mã lô × SL cơ sở), tồn lô còn lại,
short_qty, near_expiry_skipped, trạng thái đơn, công nợ (số nợ, NV giữ, hạn). tests/test_xuat_hang.py chạy cùng chuỗi trên site Frappe.

	python3 tools/vang_xuat_hang.py   → nppsale/tests/du_lieu/xuat_hang_mau.json
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vang_tao_don import (
	GIA,
	HANG,
	KHACH,
	NGUOI,
	NHOM,
	NS,
	ORG,
	PSQL,
	_lit,
	dong,
	ref,
	sql_nen,
	tong,
	uid,
)

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICH = os.path.join(GOC, "nppsale", "tests", "du_lieu", "xuat_hang_mau.json")

# Lô: (mã lô, mặt hàng, SL cơ sở, nhận lúc = hôm nay + n ngày (8:00 giờ VN), hạn dùng = hôm nay + n ngày, giá vốn / đơn vị cơ sở, vùng).
# Ngày tương đối để bài kiểm chạy được mọi ngày (lô không tự hết hạn theo lịch).
LO = [
	("L1-CU", "P1", 30, -43, 108, 8000, "sale"),
	("L2-MOI-HAN-SOM", "P1", 50, -39, 63, 8200, "sale"),
	("L3-CAN-DATE", "P1", 20, -54, 37, 7900, "date"),
	("L4-DAU", "P2", 10, -42, 200, 4000, "sale"),
	("L5-DAU-DATE", "P2", 6, -73, 18, 3900, "date"),
]


def sql_lo() -> str:
	q = []
	for ma, sp, sl, nhan, han, gia, vung in LO:
		luc = f"((now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date + {nhan} + time '08:00') AT TIME ZONE 'Asia/Ho_Chi_Minh'"
		q.append("INSERT INTO batches (id, org_id, product_id, batch_code, expires_at, qty_initial, qty_on_hand, unit_cost, warehouse_zone, "
			f"received_at, created_at) VALUES ('{uid('lo:' + ma)}', '{ORG}', '{uid(sp)}', '{ma}', "
			f"(now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date + {han}, {sl}, {sl}, {gia}, '{vung}', {luc}, {luc});")
	return "\n".join(q)


def don(nguoi, lines, ma, *, khach="@C1", giam_don=0, **o):
	t = tong(lines, giam_don)
	oo = {"order_code": "TAM-1", "customer_id": khach, "payment_terms": "COD", "expected_delivery": None, "notes": None,
		"status": "submitted", "approval_reason": None, "sales_user_id": None, **t, **o}
	return {"buoc": "tao", "nguoi": nguoi, "p": {"client_request_id": str(uuid.uuid5(NS, "xuat:" + ma)), "order": oo, "lines": lines,
		"returns": None, "return_lines": []}}


def xuat(nguoi, dong_xuat, **p):
	"""dong_xuat: [(chỉ số dòng đơn hoặc None = dòng thêm, {đè trường})]; trường không đè lấy từ dòng đơn."""
	return {"buoc": "xuat", "nguoi": nguoi, "dong": [list(x) for x in dong_xuat], "p": p}


def huy(nguoi, ly_do="Khach tra lai hang"):
	return {"buoc": "huy", "nguoi": nguoi, "ly_do": ly_do}


def sua(nguoi, dong_sua, **p):
	"""Sửa HĐ (reissue_invoice) tờ đang hiệu lực. dong_sua: [(chỉ số dòng của TỜ ĐANG SỬA hoặc None = dòng thêm, {đè trường})] — như màn
	Sửa HĐ dựng tải trọng từ dòng hoá đơn. Dòng thêm mang "@dong_don": k = dựng từ dòng đơn thứ k (dòng chưa giao, nối lại đơn)."""
	return {"buoc": "sua", "nguoi": nguoi, "dong": [list(x) for x in dong_sua], "p": p}


def gan(nguoi, nv, loai="invoice"):
	"""assign_doc_seller: đổi người đứng tên HĐ đang hiệu lực."""
	return {"buoc": "gan", "nguoi": nguoi, "nv": nv, "loai": loai}


def nghi(nv):
	"""NV nghỉ việc (mốc left_at) — đặt thẳng, không qua cho_nhan_vien_nghi (bước ấy còn chuyển nợ; ở đây chỉ thử luật giữ nợ)."""
	return {"buoc": "nghi", "nguoi": "owner", "nv": nv}


def doi_he_so(sp, dv, hs):
	"""Danh mục đổi hệ số quy đổi của một đơn vị (người quản trị sửa sản phẩm) — không qua RPC."""
	return {"buoc": "doi_he_so", "nguoi": "owner", "sp": sp, "dv": dv, "hs": hs}


def tinh_huong() -> list[dict]:
	A = [dong(sl=2, gia=9500), dong(sp="@P2", dv="Chai", gia=5000, thue=0.1)]
	T = []

	def th(ma, *buoc, oversell=False):
		T.append({"ma": ma, "buoc": list(buoc), "cho_ban_vuot_ton": oversell})

	# --- lô FIFO theo ngày nhận
	th("xuat_du_mot_lo", don("sales_a", A, "xuat_du_mot_lo"), xuat("owner", [(0, {}), (1, {})]))
	th("xuat_qua_hai_lo", don("sales_a", [dong(sl=40, gia=9500)], "xuat_qua_hai_lo"), xuat("owner", [(0, {})]))
	th("xuat_thung_quy_doi", don("sales_a", [dong(dv="Thung", hs=24, sl=2, gia=230000)], "xuat_thung"), xuat("owner", [(0, {})]))
	th("xuat_giao_thieu", don("sales_a", A, "xuat_giao_thieu"), xuat("owner", [(0, {"quantity": 1}), (1, {})]))
	th("xuat_bo_dong", don("sales_a", A, "xuat_bo_dong"), xuat("owner", [(0, {})]))
	th("xuat_dong_them", don("sales_a", A[:1], "xuat_dong_them"), xuat("owner", [(0, {}), (None, {"product_id": "@P2", "unit_name": "Chai",
		"quantity": 2, "unit_price": 5000, "vat_rate": 0.1, "conversion_factor": 1})]))
	th("xuat_he_so_sai_duoc_chuan", don("sales_a", [dong(dv="Loc", hs=6, sl=1, gia=57000)], "xuat_he_so_sai"),
		xuat("owner", [(0, {"conversion_factor": 4})]))
	th("xuat_don_vi_co_so_he_so_sai", don("sales_a", [dong(sl=2, gia=9500)], "xuat_co_so_he_so_sai"),
		xuat("owner", [(0, {"conversion_factor": 5})]))
	# --- thiếu tồn / kho cận date / bán vượt tồn
	th("thieu_ton", don("sales_a", [dong(sl=90, gia=9500)], "thieu_ton"), xuat("owner", [(0, {})]))
	th("thieu_ton_con_o_kho_date", don("sales_a", [dong(sp="@P2", dv="Chai", sl=12, gia=5000, thue=0.1)], "thieu_ton_date"),
		xuat("owner", [(0, {})]))
	th("hang_khong_co_lo", don("owner", [dong(sp="@P3", dv="Goi", sl=1, gia=1000, thue=0)], "hang_khong_lo"), xuat("owner", [(0, {})]))
	th("ban_vuot_ton", don("sales_a", [dong(sl=90, gia=9500)], "ban_vuot_ton"), xuat("owner", [(0, {})]), oversell=True)
	# --- tiền
	th("giam_gia_don", don("sales_giam", A, "giam_gia_don", giam_don=2000), xuat("owner", [(0, {}), (1, {})], discount=2000))
	th("giam_gia_don_vuot_tien", don("sales_a", A[:1], "giam_vuot"), xuat("owner", [(0, {})], discount=99999999))
	th("giam_gia_don_chu", don("sales_a", A, "giam_chu"), xuat("owner", [(0, {}), (1, {})], discount="abc"))
	th("thue_khac_don", don("sales_a", A, "thue_khac"), xuat("owner", [(0, {"vat_rate": 0.05}), (1, {"vat_rate": 8})]))
	th("dieu_khoan_net30_va_ngay", don("sales_a", A, "net30"), xuat("owner", [(0, {}), (1, {})], payment_terms="NET30",
		invoice_date="@hom_nay-3", notes="Giao chieu"))
	# --- quyền / trạng thái / dữ liệu hỏng
	th("nv_ban_hang_xuat", don("sales_a", A, "nv_xuat"), xuat("sales_a", [(0, {}), (1, {})]))
	th("thu_kho_xuat", don("sales_a", A, "kho_xuat"), xuat("warehouse", [(0, {}), (1, {})]))
	th("ke_toan_xuat", don("sales_a", A, "kt_xuat"), xuat("accountant", [(0, {}), (1, {})]))
	th("quan_ly_xuat", don("sales_a", A, "ql_xuat"), xuat("manager", [(0, {}), (1, {})]))
	th("don_nhap_khong_xuat", don("sales_a", A, "nhap_xuat", status="draft"), xuat("owner", [(0, {}), (1, {})]))
	th("xuat_hai_lan", don("sales_a", A, "hai_lan"), xuat("owner", [(0, {}), (1, {})]), xuat("owner", [(0, {}), (1, {})]))
	th("khong_dong", don("sales_a", A, "khong_dong"), xuat("owner", [(0, {"quantity": 0})]))
	th("dong_sai_don", don("sales_a", A, "dong_sai"), xuat("owner", [(0, {"product_id": "@P2", "unit_name": "Chai"})]))
	# --- huỷ HĐ = huỷ đơn (mig 217)
	th("huy_hd_chu", don("sales_a", A, "huy_hd_chu"), xuat("owner", [(0, {}), (1, {})]), huy("owner"))
	th("huy_hd_quan_ly", don("sales_a", [dong(sl=40, gia=9500)], "huy_hd_ql"), xuat("owner", [(0, {})]), huy("manager", "Sai gia"))
	th("huy_hd_giao_thieu", don("sales_a", A, "huy_hd_thieu"), xuat("owner", [(0, {"quantity": 1})]), huy("owner"))
	th("huy_hd_nv_khong_quyen", don("sales_a", A, "huy_hd_nv"), xuat("owner", [(0, {}), (1, {})]), huy("sales_a"))
	th("huy_hd_khong_ly_do", don("sales_a", A, "huy_hd_ly_do"), xuat("owner", [(0, {}), (1, {})]), huy("owner", "   "))
	th("huy_hd_hai_lan", don("sales_a", A, "huy_hd_2"), xuat("owner", [(0, {}), (1, {})]), huy("owner"), huy("owner", "lan 2"))
	th("huy_roi_xuat_lai", don("sales_a", A, "huy_xuat_lai"), xuat("owner", [(0, {}), (1, {})]), huy("owner"),
		xuat("owner", [(0, {}), (1, {})]))
	# --- Sửa HĐ = huỷ + lập lại trong một giao dịch, giữ số gốc -n (mig 128 / 213 / 215 / 247)
	X2 = xuat("owner", [(0, {}), (1, {})])
	th("sua_hd_doi_sl", don("sales_a", A, "sua_sl"), X2, sua("owner", [(0, {"quantity": 3}), (1, {})]))
	th("sua_hd_bo_dong", don("sales_a", A, "sua_bo"), X2, sua("owner", [(0, {})]))
	th("sua_hd_them_dong", don("sales_a", A, "sua_them"), xuat("owner", [(0, {})]), sua("owner", [(0, {}), (None, {"product_id": "@P2",
		"unit_name": "Hop", "quantity": 1, "unit_price": 48000, "vat_rate": 0.1, "conversion_factor": 3})]))
	th("sua_hd_giao_thieu_roi_du", don("sales_a", A, "sua_thieu_du"), xuat("owner", [(0, {"quantity": 1}), (1, {})]),
		sua("owner", [(0, {"quantity": 2}), (1, {})]))
	th("sua_hd_doi_gia_giam", don("sales_a", A, "sua_gia"), X2, sua("owner", [(0, {"unit_price": 9000, "line_discount": 500}), (1, {})]))
	th("sua_hd_mac_dinh_to_cu", don("sales_giam", A, "sua_mac_dinh", giam_don=2000),
		xuat("owner", [(0, {}), (1, {})], discount=2000, payment_terms="NET30", invoice_date="@hom_nay-3", notes="Giao chieu"),
		sua("owner", [(0, {}), (1, {})]))
	th("sua_hd_doi_ngay_dk_giam", don("sales_giam", A, "sua_doi_dk", giam_don=2000),
		xuat("owner", [(0, {}), (1, {})], discount=2000, payment_terms="NET30", invoice_date="@hom_nay-3"),
		sua("owner", [(0, {}), (1, {})], discount=0, payment_terms="NET7", invoice_date="@hom_nay-1", notes="Sua lai"))
	th("sua_hd_giu_he_so_to_cu", don("sales_a", [dong(dv="Thung", hs=24, sl=1, gia=230000)], "sua_he_so"), xuat("owner", [(0, {})]),
		doi_he_so("P1", "Thung", 20), sua("owner", [(0, {"quantity": 2})]))
	th("sua_hd_dong_moi_he_so_danh_muc", don("sales_a", A, "sua_he_so_moi"), X2, doi_he_so("P1", "Loc", 4),
		sua("owner", [(0, {}), (1, {}), (None, {"product_id": "@P1", "unit_name": "Loc", "quantity": 1, "unit_price": 57000,
			"vat_rate": 0.08, "conversion_factor": 6})]))
	th("sua_hd_dong_don_doi_he_so", don("sales_a", [dong(sl=2, gia=9500), dong(dv="Loc", hs=6, sl=1, gia=57000)], "sua_dong_don_hs"),
		xuat("owner", [(0, {})]), doi_he_so("P1", "Loc", 4), sua("owner", [(0, {}), (None, {"@dong_don": 1})]))
	th("sua_hd_hai_lan", don("sales_a", A, "sua_2"), X2, sua("owner", [(0, {"quantity": 3}), (1, {})]),
		sua("owner", [(0, {"quantity": 1}), (1, {})]))
	th("sua_hd_quan_ly", don("sales_a", A, "sua_ql"), X2, sua("manager", [(0, {}), (1, {"quantity": 2})]))
	th("sua_hd_nv_khong_quyen", don("sales_a", A, "sua_nv"), X2, sua("sales_a", [(0, {}), (1, {})]))
	th("sua_hd_da_huy", don("sales_a", A, "sua_da_huy"), X2, huy("owner"), sua("owner", [(0, {}), (1, {})]))
	th("sua_hd_khong_dong", don("sales_a", A, "sua_rong"), X2, sua("owner", [(0, {"quantity": 0}), (1, {"quantity": 0})]))
	th("sua_hd_thieu_ton", don("sales_a", A, "sua_thieu"), X2, sua("owner", [(0, {"quantity": 95}), (1, {})]))
	th("sua_roi_huy", don("sales_a", A, "sua_huy"), X2, sua("owner", [(0, {"quantity": 3}), (1, {})]), huy("owner", "Khach doi y"))
	# --- đổi người đứng tên HĐ (assign_doc_seller — mig 160 / 194) + người giữ nợ (mig 182 / 223 / 227) + Sửa HĐ giữ người
	th("gan_nv_hd", don("sales_a", A, "gan_nv"), X2, gan("owner", "sales_b"))
	th("gan_nv_quan_ly", don("sales_a", A, "gan_ql"), X2, gan("manager", "sales_b"))
	th("gan_nv_cho_chinh_quan_ly", don("sales_a", A, "gan_cho_ql"), X2, gan("owner", "manager"))
	th("gan_nv_sales_cam", don("sales_a", A, "gan_sales"), X2, gan("sales_a", "sales_b"))
	th("gan_nv_ke_toan_cam", don("sales_a", A, "gan_kt"), X2, gan("accountant", "sales_b"))
	th("gan_nv_thu_kho_khong_nhan", don("sales_a", A, "gan_kho"), X2, gan("owner", "warehouse"))
	th("gan_nv_ngung_hoat_dong", don("sales_a", A, "gan_ngung"), X2, gan("owner", "sales_nghi"))
	th("gan_nv_sai_loai", don("sales_a", A, "gan_loai"), X2, gan("owner", "sales_b", loai="order"))
	th("gan_nv_phieu_tra_khong_co", don("sales_a", A, "gan_pt"), X2, gan("owner", "sales_b", loai="return"))
	th("gan_nv_hd_da_huy", don("sales_a", A, "gan_huy"), X2, huy("owner"), gan("owner", "sales_b"))
	th("gan_nv_da_nghi_giu_no_cu", don("sales_a", A, "gan_da_nghi"), X2, nghi("sales_b"), gan("owner", "sales_b"))
	th("gan_nv_roi_sua", don("sales_a", A, "gan_sua"), X2, gan("owner", "sales_b"), sua("owner", [(0, {}), (1, {})]))
	th("nv_nghi_roi_xuat", don("sales_a", A, "nghi_xuat"), nghi("sales_a"), X2)
	th("nv_nghi_roi_sua", don("sales_a", A, "nghi_sua"), X2, nghi("sales_a"), sua("owner", [(0, {"quantity": 3}), (1, {})]))
	th("nv_nghi_roi_gan_lai", don("sales_a", A, "nghi_gan"), nghi("sales_a"), X2, gan("owner", "sales_b"))
	return T


def _gia(v) -> str:
	if v is None:
		return "NULL"
	return _lit(str(v))


def sql_tinh_huong(t: dict) -> str:
	khoi = []
	for b in t["buoc"]:
		u = uid("u:" + b["nguoi"])
		if b["buoc"] == "tao":
			lenh = (f"SELECT r.order_id INTO v_don FROM public.create_order_with_lines({_lit(json.dumps(ref(b['p'])))}::jsonb) r; "
				"SELECT array_agg(s.id ORDER BY s.ctid) INTO v_dd FROM sales_order_lines s WHERE s.order_id = v_don;")
		elif b["buoc"] == "huy":
			lenh = (f"SELECT to_jsonb(r) INTO v_tra FROM public.cancel_invoice(v_hd, {_lit(b['ly_do'])}) r; "
				"v_ds_huy := v_ds_huy || jsonb_build_array(v_tra);")
		elif b["buoc"] == "gan":
			lenh = f"PERFORM public.assign_doc_seller({_lit(b['loai'])}, v_hd, '{uid('u:' + b['nv'])}');"
		elif b["buoc"] == "nghi":
			lenh = f"EXECUTE 'RESET ROLE'; UPDATE users SET left_at = now() WHERE id = '{uid('u:' + b['nv'])}';"
		elif b["buoc"] == "doi_he_so":
			lenh = (f"EXECUTE 'RESET ROLE'; UPDATE product_units SET conversion = {b['hs']} WHERE product_id = '{uid(b['sp'])}' "
				f"AND unit_name = {_lit(b['dv'])};")
		elif b["buoc"] == "sua":
			dong_x = json.dumps(ref(b["dong"]))
			p = json.dumps(ref(ngay_tuong_doi(b["p"])))
			lenh = f"""
      SELECT jsonb_agg(CASE WHEN x.e->>0 IS NULL AND (x.e->1) ? '@dong_don' THEN
            (SELECT jsonb_build_object('order_line_id', d.id, 'product_id', d.product_id, 'unit_name', d.unit_name,
              'conversion_factor', d.conversion_factor, 'quantity', d.quantity, 'unit_price', d.unit_price, 'line_discount', d.line_discount,
              'vat_rate', d.vat_rate, 'is_exchange', false, 'note', d.note)
             FROM sales_order_lines d WHERE d.id = v_dd[(x.e->1->>'@dong_don')::int + 1]) || ((x.e->1) - '@dong_don')
          WHEN x.e->>0 IS NULL THEN x.e->1
          ELSE jsonb_build_object('order_line_id', l.order_line_id, 'product_id', l.product_id, 'unit_name', l.unit_name,
            'conversion_factor', l.conversion_factor, 'quantity', l.quantity, 'unit_price', l.unit_price,
            'line_discount', l.line_discount, 'vat_rate', l.vat_rate, 'is_exchange', l.is_exchange, 'note', l.note) || (x.e->1) END
          ORDER BY x.i) INTO v_dong
        FROM jsonb_array_elements({_lit(dong_x)}::jsonb) WITH ORDINALITY x(e, i)
        LEFT JOIN LATERAL (SELECT * FROM sales_invoice_lines s WHERE s.invoice_id = v_hd ORDER BY s.sort_order OFFSET (x.e->>0)::int LIMIT 1) l
          ON x.e->>0 IS NOT NULL;
      SELECT r.invoice_id, to_jsonb(r) INTO v_hd, v_tra
        FROM public.reissue_invoice(v_hd, ({_lit(p)}::jsonb) || jsonb_build_object('lines', v_dong)) r;
      v_ds_hd := v_ds_hd || jsonb_build_array(v_tra);"""
		else:
			dong_x = json.dumps(ref(b["dong"]))
			p = json.dumps(ref(ngay_tuong_doi(b["p"])))
			lenh = f"""
      SELECT jsonb_agg(CASE WHEN x.e->>0 IS NULL THEN x.e->1
          ELSE jsonb_build_object('order_line_id', l.id, 'product_id', l.product_id, 'unit_name', l.unit_name,
            'conversion_factor', l.conversion_factor, 'quantity', l.quantity - COALESCE(l.invoiced_qty, 0), 'unit_price', l.unit_price,
            'line_discount', l.line_discount, 'vat_rate', l.vat_rate, 'is_exchange', false, 'note', l.note) || (x.e->1) END
          ORDER BY x.i) INTO v_dong
        FROM jsonb_array_elements({_lit(dong_x)}::jsonb) WITH ORDINALITY x(e, i)
        LEFT JOIN LATERAL (SELECT * FROM sales_order_lines s WHERE s.order_id = v_don ORDER BY s.ctid OFFSET (x.e->>0)::int LIMIT 1) l
          ON x.e->>0 IS NOT NULL;
      SELECT r.invoice_id, to_jsonb(r) INTO v_hd, v_tra
        FROM public.post_invoice(({_lit(p)}::jsonb) || jsonb_build_object('order_id', v_don, 'lines', v_dong)) r;
      v_ds_hd := v_ds_hd || jsonb_build_array(v_tra);"""
		khoi.append(f"""
  IF NOT v_dung THEN
    BEGIN
      EXECUTE 'SET CONSTRAINTS ALL DEFERRED';
      PERFORM set_config('request.jwt.claim.sub', {_lit(u)}, true);
      EXECUTE 'SET LOCAL ROLE authenticated';
      {lenh}
      EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';
      EXECUTE 'RESET ROLE';
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
  v_don uuid; v_dd uuid[]; v_hd uuid; v_dong jsonb; v_tra jsonb; v_ds_hd jsonb := '[]'::jsonb; v_ds_huy jsonb := '[]'::jsonb; v_kq jsonb := '[]'::jsonb;
  v_dung boolean := false;
  v_ct jsonb;
BEGIN
  BEGIN
    UPDATE organizations SET allow_oversell = {str(t['cho_ban_vuot_ton']).lower()} WHERE id = '{ORG}';
    {''.join(khoi)}
    SELECT jsonb_build_object(
      'tra_ve', v_ds_hd, 'tra_ve_huy', v_ds_huy,
      'don', (SELECT jsonb_build_object('status', so.status, 'co_completed_at', so.completed_at IS NOT NULL, 'cancel_reason', so.cancel_reason,
          'co_cancelled_at', so.cancelled_at IS NOT NULL,
          'lich_su', (SELECT jsonb_agg(jsonb_build_array(h.from_status, h.to_status) ORDER BY h.changed_at, h.ctid)
            FROM order_status_history h WHERE h.order_id = so.id)) FROM sales_orders so WHERE so.id = v_don),
      'thong_bao', (SELECT jsonb_object_agg(x.type, x.n) FROM (SELECT n.type, count(*) AS n FROM notifications n
          WHERE n.link_url = '/orders/' || v_don::text OR n.link_url IN (SELECT '/sales-invoices/' || s2.id::text FROM sales_invoices s2
            WHERE s2.order_id = v_don) GROUP BY n.type) x),
      'hd', (SELECT jsonb_agg(jsonb_build_object('ma', si.invoice_code, 'status', si.status, 'ngay', si.invoice_date, 'han', si.due_date,
          'dieu_khoan', si.payment_terms, 'subtotal', si.subtotal, 'vat', si.vat, 'total', si.total, 'ghi_chu', si.notes,
          'sales_user', (SELECT u.full_name FROM users u WHERE u.id = si.sales_user_id),
          'huy_ly_do', si.cancel_reason, 'co_huy_luc', si.cancelled_at IS NOT NULL,
          'huy_boi', (SELECT u.full_name FROM users u WHERE u.id = si.cancelled_by),
          'dong', (SELECT jsonb_agg(jsonb_build_object('sp', (SELECT p.sku FROM products p WHERE p.id = l.product_id), 'dv', l.unit_name,
              'hs', l.conversion_factor, 'sl', l.quantity, 'gia', l.unit_price, 'giam', l.line_discount, 'tien', l.line_total,
              'thue', l.vat_rate, 'doi', l.is_exchange, 'noi_don', l.order_line_id IS NOT NULL) ORDER BY l.sort_order)
            FROM sales_invoice_lines l WHERE l.invoice_id = si.id),
          'lo', (SELECT jsonb_agg(jsonb_build_array((SELECT p.sku FROM products p WHERE p.id = sel.product_id), b.batch_code, c.qty_in_base_uom)
              ORDER BY (SELECT p.sku FROM products p WHERE p.id = sel.product_id), b.received_at, b.batch_code, c.qty_in_base_uom)
            FROM stock_entry_lines sel JOIN stock_line_consumptions c ON c.line_id = sel.id JOIN batches b ON b.id = c.batch_id
            WHERE sel.entry_id = si.stock_entry_id),
          'cong_no', (SELECT jsonb_agg(jsonb_build_object('so_tien', r.amount, 'da_thu', r.paid, 'han', r.due_date, 'status', r.status,
              'nv', (SELECT u.full_name FROM users u WHERE u.id = r.sales_user_id))) FROM receivables r WHERE r.invoice_id = si.id)
        ) ORDER BY si.invoice_seq, si.reissue_no) FROM sales_invoices si WHERE si.order_id = v_don),
      'ton_lo', (SELECT jsonb_object_agg(b.batch_code, b.qty_on_hand) FROM batches b WHERE b.org_id = '{ORG}'))
      INTO v_ct;
    RAISE EXCEPTION USING ERRCODE = 'ZZ999';
  EXCEPTION WHEN SQLSTATE 'ZZ999' THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  INSERT INTO _vang_kq VALUES ({_lit(t['ma'])}, v_kq, v_ct);
END $c$;
"""


def ngay_tuong_doi(v, hom_nay: datetime.date | None = None):
	""""@hom_nay" / "@hom_nay±n" trong tải trọng → ngày thật (giờ VN) — bộ sinh và bài kiểm dùng cùng luật."""
	hn = hom_nay or _hom_nay()
	if isinstance(v, str) and v.startswith("@hom_nay"):
		n = int(v[len("@hom_nay"):] or 0)
		return (hn + datetime.timedelta(days=n)).isoformat()
	if isinstance(v, dict):
		return {a: ngay_tuong_doi(b, hn) for a, b in v.items()}
	if isinstance(v, list):
		return [ngay_tuong_doi(x, hn) for x in v]
	return v


def _hom_nay() -> datetime.date:
	return (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=7)).date()


def _chuan(k: dict) -> dict:
	"""Bỏ UUID ngẫu nhiên; ngày tương đối → "@hom_nay" / "@hom_nay+n" (bài kiểm chạy được mọi ngày)."""
	hn = _hom_nay()

	def ngay(v):
		if not isinstance(v, str) or len(v) != 10:
			return v
		try:
			d = datetime.date.fromisoformat(v)
		except ValueError:
			return v
		n = (d - hn).days
		return v if abs(n) > 400 else ("@hom_nay" if n == 0 else f"@hom_nay{n:+d}")

	ct = k.get("ct") or {}
	for x in ct.get("tra_ve_huy") or []:
		x["import_entry_id"] = bool(x.get("import_entry_id"))
	for x in ct.get("tra_ve") or []:
		for khoa in ("invoice_id", "entry_id", "receivable_id"):
			x[khoa] = bool(x.get(khoa))
	for h in ct.get("hd") or []:
		for khoa in ("ngay", "han"):
			h[khoa] = ngay(h.get(khoa))
		for c in h.get("cong_no") or []:
			c["han"] = ngay(c.get("han"))
	return k


def main():
	T = tinh_huong()
	sql = ["BEGIN;", sql_nen(), sql_lo(), "CREATE TEMP TABLE _vang_kq (ma text, buoc jsonb, ct jsonb);"]
	sql += [sql_tinh_huong(t) for t in T]
	sql.append("SELECT json_agg(json_build_object('ma', ma, 'buoc', buoc, 'ct', ct)) FROM _vang_kq;")
	sql.append("ROLLBACK;")
	ra = subprocess.run(PSQL, shell=True, input="\n".join(sql), capture_output=True, text=True, check=False)
	if ra.returncode != 0:
		raise SystemExit(ra.stderr[-4000:])
	kq = {k["ma"]: _chuan(k) for k in json.loads(ra.stdout.strip().splitlines()[-1])}
	tep = {"ghi_chu": "Sinh bởi tools/vang_xuat_hang.py — post_invoice / cancel_invoice / reissue_invoice + trigger thật của nppsale (chưa gồm hàng trả kèm đơn, tiền thu).",
		"nen": {"nguoi": NGUOI, "nhom": NHOM, "khach": KHACH, "hang": HANG, "gia": GIA, "lo": LO},
		"tinh_huong": [dict(t, mong={"buoc": kq[t["ma"]]["buoc"], "ct": kq[t["ma"]]["ct"]}) for t in T]}
	with open(DICH, "w", encoding="utf-8") as f:
		json.dump(tep, f, ensure_ascii=False, indent=1)
		f.write("\n")
	print(f"{len(T)} tình huống → {DICH}")
	for t in T:
		k = kq[t["ma"]]
		bs = " | ".join("ok" if x["ok"] else f"{x['ma_loi']} {x['loi'][:90]}" for x in k["buoc"])
		hd = (k["ct"] or {}).get("hd") or []
		tom = "; ".join(f"{h['ma']} {h['total']} lô {h['lo']}" for h in hd)
		print(f"  {t['ma']:<28} {bs}\n      → {tom[:200]}")


if __name__ == "__main__":
	main()
