/**
 * Bộ vàng BÁO CÁO (P6) — phần GIAO DIỆN: chạy CHÍNH mã TS của nppsale (portal/nguon/src — nppsale ghim ở portal/nguon.json) trên kết quả
 * `bao_cao_so_ban` mà tools/vang_bao_cao.py lấy từ Postgres (hàm thật, dữ liệu dựng qua RPC thật). Đặc tả P6 §2.14 / §5 (VB-A05, A06, A11,
 * E01, E02, E03, E05, E14, E15).
 *
 * Không chạy riêng: tools/vang_bao_cao.py bó tệp này bằng esbuild (portal/node_modules) với bí danh "@/*" → portal/nguon/src/*, chạy bằng
 * node, đưa vào stdin MỘT mảng ca {ma, so_ban, san_pham}, đọc ra stdout MỘT mảng kết quả (cùng thứ tự). Mã nppsale gọi nguyên hàm:
 *  - Báo cáo tổng hợp (/bao-cao/ban-hang): `tuMotLuot` → `dungDongBan` (dm dựng như `napDanhMuc` — nap-danh-muc.ts:98-117, chép vòng
 *    dựng dm.sp vì hàm gốc đọc Supabase) → `congBan` (tổng, theo NV); `nhanVienPhieuTra` (NV của phiếu trả).
 *  - "Hàng bán theo nhân viên" (/bao-cao/nhan-vien = reports/employees, mối quan tâm "summary", không lọc): CHÉP đúng các useMemo của
 *    page.tsx (linesByInvoice bỏ dòng đổi :290-300; returnLinesTheoNv / returnsTheoNv :399-422; employeeSummaryRows :838-880) rồi gọi
 *    nguyên `congHangBanNhanVien` + `chotTienChungTu` + `giamGiaHoaDon`.
 *  - SL mặt hàng dạng "2 thùng 10 hộp": `tachDonVi` + `chuDonVi` (lib/orders/pick-list.ts); phần tổng hợp NV: `hienTongSL` + `DON_VI_TONG`.
 *  - /reports/sales tab Nhân viên (soát VB-E02 — màn được kiểm, KHÔNG phải /bao-cao/ban-hang): CHÉP đúng useMemo `employeeRows` của
 *    app/(dashboard)/reports/sales/page.tsx:504-552 (không lọc; đầu vào = `docSoBanKy` — mot.hd / mot.dongHd đã bỏ dòng đổi / mot.tra /
 *    mot.giaVonTra / mot.giaVonCoSo; productMap từ products(id, base_unit, primary_supplier_id, units)) rồi gọi nguyên `congLoiNhuanNhanVien`
 *    + `soLuongCoSoDongHd`; `nvPhieuTra` = `nhanVienPhieuTra(returns, invoices)` như :489.
 *  - Báo cáo tổng hợp › Kho, XNT (soát VB-E08 — lớp lỗi S13: `ref_order_ids` chuỗi '[]' làm xuất lẻ / trả NCC thành "Xuất bán"): CHÉP vòng
 *    phân loại của `napBienDong` (lib/bao-cao/nap-kho.ts:216-236 — hàm gốc đọc Supabase) trên phiếu kho + dòng do bộ sinh đọc, rồi gọi nguyên
 *    `tinhXnt` với tồn hiện tại theo lô (như man-kho.tsx:169-177).
 */
import { readFileSync } from "node:fs"
import { tuMotLuot, dungDongBan } from "@/lib/bao-cao/nap-ban-hang"
import { congBan, danhMucRong } from "@/lib/bao-cao/cong"
import { nhanVienPhieuTra, congHangBanNhanVien, chotTienChungTu, congLoiNhuanNhanVien } from "@/lib/analytics/hang-ban-nhan-vien"
import { giamGiaHoaDon, soLuongCoSoDongHd } from "@/lib/analytics/sales"
import { tachDonVi, chuDonVi } from "@/lib/orders/pick-list"
import { hienTongSL, DON_VI_TONG } from "@/lib/analytics/sl-theo-don-vi"
import { soLuongCoSoDongKho, vnDateOf } from "@/lib/analytics/sales"
import { tinhXnt, type BienDong, type LoaiBienDong } from "@/lib/bao-cao/nap-kho"

type SpTho = {
	id: string
	sku: string | null
	name: string
	brand?: string | null
	primary_supplier_id?: string | null
	base_unit: string | null
	sell_price?: number | string | null
	units?: { unit_name: string; conversion: number | string }[] | null
	price_lists?: { unit_name: string; price: number | string; group_id: string | null }[] | null
}
type Ca = { ma: string; so_ban: never; san_pham: SpTho[] }
type PhieuKho = { id: string; type: string; notes: string | null; entry_code: string | null; posted_at: string | null; ref_order_ids: unknown }
type DongKho = { entry_id: string; product_id: string; quantity: number; qty_in_base_uom: number | null; conversion_factor_snapshot: number | null;
	unit_cost: number | null }
type CaXnt = { ma: string; xnt: { a: string; b: string; pk: PhieuKho[]; dong: DongKho[]; ton: Record<string, number> } }

/** XNT [a, b] — vòng phân loại CHÉP từ napBienDong (nap-kho.ts:216-236) + tinhXnt gốc. */
function motXnt(ca: CaXnt) {
	const { a, b, pk, dong, ton } = ca.xnt
	const theoId = new Map(pk.map((e) => [e.id, e]))
	const ds: BienDong[] = []
	for (const l of dong) {
		const e = theoId.get(l.entry_id)
		if (!e || !e.posted_at) continue
		const q = soLuongCoSoDongKho(l as never)
		const coDon = Array.isArray(e.ref_order_ids) ? e.ref_order_ids.length > 0 : !!e.ref_order_ids
		let loai: LoaiBienDong
		let sl: number
		if (e.type === "import") {
			loai = (e.notes || "").startsWith("Nhập lại từ phiếu trả") ? "tra" : "nhap"
			sl = q
		} else if (e.type === "export") {
			loai = coDon ? "ban" : "khac"
			sl = -q
		} else {
			loai = "khac"
			sl = Number(l.qty_in_base_uom ?? l.quantity ?? 0)
		}
		ds.push({ ngay: vnDateOf(e.posted_at), sp: l.product_id, sl, loai, ma: e.entry_code || e.id.slice(0, 8), phieu: e.id, gia: Number(l.unit_cost || 0) })
	}
	ds.sort((x, y) => x.ngay.localeCompare(y.ngay))
	const xnt = tinhXnt(new Map(Object.entries(ton)), ds, a, b)
	return { ma: ca.ma, xnt: Object.fromEntries([...xnt].map(([sp, x]) => [sp, x])), loai: Object.fromEntries(ds.map((d) => [`${d.ma}/${d.sp}`, d.loai])) }
}

/** dm.sp như `napDanhMuc` (nap-danh-muc.ts:98-117) — chỉ phần mặt hàng (khách / NV / kênh không vào số). */
function danhMucSp(sp: SpTho[]) {
	const dm = danhMucRong()
	for (const p of sp) {
		const donVi = (p.units || [])
			.map((u) => ({ ten: u.unit_name, heSo: Number(u.conversion) }))
			.filter((u) => u.heSo > 0 && u.ten !== p.base_unit)
		const lon = donVi.filter((u) => u.heSo > 1).sort((a, b) => b.heSo - a.heSo)[0]
		dm.sp.set(p.id, {
			ten: p.name,
			sku: p.sku || "",
			thuongHieu: (p.brand || "").trim(),
			ncc: p.primary_supplier_id || "",
			donViCoSo: p.base_unit || "",
			donViLon: lon || null,
			donVi,
			giaBan: Number(p.sell_price) || 0,
			bangGia: (p.price_lists || []).filter((g) => !g.group_id).map((g) => ({ ten: g.unit_name, gia: Number(g.price) || 0 })),
		} as never)
	}
	return dm
}

function mot(ca: Ca) {
	const tho = tuMotLuot(ca.so_ban)
	const dm = danhMucSp(ca.san_pham)
	const nvTra = nhanVienPhieuTra(tho.tra, tho.hd)
	const out = dungDongBan({
		hoaDon: tho.hd,
		dongHd: tho.dongHd,
		tra: tho.tra.map((r) => ({ ...r, ...(tho.traThem.get(r.id) ?? {}) })) as never,
		dongTra: tho.dongTra,
		giaVonCoSo: tho.giaVonCoSo,
		giaVonTra: tho.giaVonTra,
		nvTra,
		dm,
	})
	const theoNv: Record<string, ReturnType<typeof congBan>> = {}
	const nhom = new Map<string, typeof out.dong>()
	for (const l of out.dong) nhom.set(l.nv, [...(nhom.get(l.nv) ?? []), l])
	for (const [nv, ls] of nhom) theoNv[nv] = congBan(ls)
	// SL bán theo mặt hàng (đơn vị cơ sở, hàng đổi không tính) → "2 thùng 10 hộp"
	const slSp = new Map<string, number>()
	for (const l of out.dong) if (l.loai > 0 && l.sp) slSp.set(l.sp, (slSp.get(l.sp) ?? 0) + l.sl)
	const spById = new Map(ca.san_pham.map((p) => [p.id, p]))
	const slMatHang: Record<string, { sl: number; chu: string }> = {}
	for (const [pid, sl] of slSp) {
		const p = spById.get(pid)
		slMatHang[pid] = { sl, chu: chuDonVi(tachDonVi(sl, p ? { base_unit: p.base_unit || "", units: p.units } : null, p?.base_unit || "")) }
	}

	// ---- "Hàng bán theo nhân viên" (reports/employees page.tsx, không lọc) ----
	const linesByInvoice = new Map<string, (typeof tho.dongHd)[number][]>()
	for (const l of tho.dongHd) {
		if (l.is_exchange) continue
		linesByInvoice.set(l.invoice_id, [...(linesByInvoice.get(l.invoice_id) ?? []), l])
	}
	const returnById = new Map(tho.tra.map((r) => [r.id, r]))
	const returnLinesTheoNv: { uid: string; line: (typeof tho.dongTra)[number] }[] = []
	for (const rl of tho.dongTra) {
		const r = returnById.get(rl.return_id)
		const uid = nvTra.get(rl.return_id)
		if (!r || !uid) continue
		returnLinesTheoNv.push({ uid, line: rl })
	}
	const returnsTheoNv: { uid: string; r: (typeof tho.tra)[number] }[] = []
	for (const r of tho.tra) {
		const uid = nvTra.get(r.id)
		if (!uid) continue
		returnsTheoNv.push({ uid, r })
	}
	const ban: { uid: string; line: never }[] = []
	const giamDon: { uid: string; tien: number }[] = []
	const tienHd = new Map<string, number>()
	for (const o of tho.hd) {
		const dongHd = linesByInvoice.get(o.id) || []
		tienHd.set(o.sales_user_id, (tienHd.get(o.sales_user_id) ?? 0) + Number(o.total || 0))
		giamDon.push({ uid: o.sales_user_id, tien: giamGiaHoaDon(o, dongHd) })
		for (const l of dongHd) ban.push({ uid: o.sales_user_id, line: l as never })
	}
	const tienTra = new Map<string, number>()
	for (const { uid, r } of returnsTheoNv) tienTra.set(uid, (tienTra.get(uid) ?? 0) + Number(r.credit_note_amount || 0))
	const sanPham = new Map(ca.san_pham.map((p) => [p.id, p as never]))
	const hangBanNv = chotTienChungTu(
		congHangBanNhanVien({ ban, tra: returnLinesTheoNv as never, sanPham, giamDon }),
		tienHd,
		tienTra
	).map((r) => ({ ...r, sl_hien: hienTongSL(r.qtyTheoDv), sl_tra_hien: hienTongSL(r.returnQtyTheoDv), don_vi: DON_VI_TONG }))

	// ---- /reports/sales tab Nhân viên — useMemo employeeRows (page.tsx:504-552), không lọc NCC / bảng giá / kênh, không tìm kiếm ----
	const dongKy = tho.dongHd.filter((l) => !l.is_exchange) // docSoBanKy (nap-ban-hang.ts:315-318)
	const lineByInvoice = new Map<string, typeof dongKy>()
	for (const l of dongKy) {
		const a = lineByInvoice.get(l.invoice_id) || []
		a.push(l)
		lineByInvoice.set(l.invoice_id, a)
	}
	const productMap = new Map(ca.san_pham.map((p) => [p.id, { id: p.id, base_unit: p.base_unit, primary_supplier_id: p.primary_supplier_id ?? null,
		units: p.units ?? [] }]))
	const avgCost = tho.giaVonCoSo
	const giaVonHoaDon = (invoiceId: string) => {
		let cogs = 0
		for (const l of lineByInvoice.get(invoiceId) || []) {
			cogs += soLuongCoSoDongHd(l as never, productMap.get(l.product_id) as never) * (avgCost.get(l.product_id) || 0)
		}
		return cogs
	}
	const nvReportsSales = congLoiNhuanNhanVien({
		hoaDon: tho.hd as never,
		giaVonHoaDon,
		phieuTra: tho.tra as never,
		nvPhieuTra: nvTra,
		giaVonTra: tho.giaVonTra,
		matHangQua: undefined,
	}).map((r) => ({ id: r.id, orders: r.orders, revenue: r.revenue, cogs: r.cogs, profit: r.profit }))

	return {
		ma: ca.ma,
		tong: congBan(out.dong),
		theo_nv: theoNv,
		gia_von_xuat: tho.giaVonXuat,
		gia_von_co_so: Object.fromEntries(tho.giaVonCoSo),
		gia_von_tra: Object.fromEntries([...tho.giaVonTra].map(([k, v]) => [k, { total: v.total, byProduct: Object.fromEntries(v.byProduct) }])),
		thu_tu_hd: tho.hd.map((h) => h.id),
		nv_phieu_tra: Object.fromEntries(nvTra),
		dong: out.dong.map((l) => ({
			loai: l.loai, ct: l.ct, sp: l.sp, nv: l.nv, kh: l.kh, ngay: l.ngay, sl: l.sl, tien: l.tien, gia_von: l.giaVon,
			giam_don: l.giamDon ?? 0, niem_yet: l.niemYet ?? null, tien_tt: l.tienTT ?? null, thieu_gv: !!l.thieuGV,
		})),
		sl_mat_hang: slMatHang,
		hang_ban_nv: hangBanNv,
		nv_reports_sales: nvReportsSales,
	}
}

const vao = JSON.parse(readFileSync(0, "utf8")) as (Ca | CaXnt)[]
process.stdout.write(JSON.stringify(vao.map((ca) => ("xnt" in ca ? motXnt(ca) : mot(ca as Ca)))))
