#!/usr/bin/env node
/**
 * Bộ vàng HOÁ ĐƠN ĐIỆN TỬ MISA — luật thuần (nppsale/luat/hddt.py) so với CHÍNH mã TS của nppsale (đặc tả dac_ta_hddt.md §8.0 tầng 1).
 *
 * Cách làm (như bộ thử scratchpad/hddt/vang/ của lượt gộp đặc tả):
 *  1. Chép `src/lib/misa/{apply,status,mapper,normalize,reconcile,client,types}.ts` từ portal/nguon/ (nppsale ghim ở portal/nguon.json) ra thư
 *     mục tạm, CHỈ đổi dòng import ("./x" → "./x.ts", "@/types" → "./types-app.ts", "@/lib/utils" → "./utils.ts" — có kiểm: dòng khác là lỗi).
 *  2. `utils.ts` = đúng hai mẩu `const VND = …` + `formatCurrency` cắt từ src/lib/utils.ts (tệp gốc nhập clsx / tailwind-merge).
 *  3. `trich.ts` = các hàm KHÔNG export cắt NGUYÊN VĂN từ tệp gốc (num, str, norm, looseSeries, strictSeries, roundVnd, extractToken,
 *     extractErrorMessage, looksLikeAuthError, extractPublishResult; toSnapshotRow của pull-snapshots/route.ts) + các mẩu thuần
 *     nằm trong route, cắt nguyên văn rồi bọc thành hàm: publish/route.ts (`.map((l) => …)` dựng dòng nhánh HĐ bán / nhánh đơn, khối dòng
 *     tổng hợp, link tra cứu), mark-replaced.ts (câu ghi chú tờ gốc), reconcile-action/route.ts (khối cảnh báo nối tay + match_status /
 *     match_note).
 *  4. Ghim `crypto.randomUUID` (dãy 00000000-0000-4000-8000-000000000001, …, đếm lại từ 1 mỗi ca) và `Date` (15/11/2026 10:00:00 +07:00,
 *     đổi được theo ca), thay `fetch` bằng kịch bản giả (không gọi MISA thật — https://misa.gia/api/v2).
 *  5. Mỗi ca ghi đầu vào (tên trường phía Python) + `mong` = kết quả Python phải ra. Ca bản Python CHỦ Ý khác TS ([ĐX] H#, hoặc lệch nhỏ) có
 *     thêm `lech` = {ma, ly_do, ts: kết quả TS}; `mong` khi ấy = kết quả TS + luật H# (dựng lại ở đây bằng JS — bản thứ hai của luật lệch,
 *     không chép từ Python).
 *
 * Số không biểu diễn được bằng JSON ở đầu vào: {"$so": "-0.4"} (số thực — Python float(), JS Number()), {"$nguyen": "9007199254740993"}
 * (số nguyên Python — JS Number()).
 *
 *   node --experimental-strip-types tools/vang_hddt.mjs        → ghi nppsale/tests/du_lieu/hddt_mau.json
 *   node --experimental-strip-types tools/vang_hddt.mjs --in   → in ra stdout (bài test_luat_hddt so với tệp đã ghi)
 *   VANG_HDDT_GIU_TAM=1 …                                       → giữ thư mục tạm (xem bản chép / trich.ts)
 */
import crypto from "node:crypto"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const GOC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const SRC = path.join(GOC, "portal", "nguon", "src")
const DICH = path.join(GOC, "nppsale", "tests", "du_lieu", "hddt_mau.json")
const IN_RA = process.argv.includes("--in")
if (!fs.existsSync(SRC)) throw new Error(`Không thấy ${SRC} — chạy scripts/lay-nguon.mjs trước (nppsale ghim ở portal/nguon.json).`)
const GHIM = JSON.parse(fs.readFileSync(path.join(GOC, "portal", "nguon.json"), "utf8"))

const doc = (p) => fs.readFileSync(path.join(SRC, p), "utf8")
const sha = (s) => crypto.createHash("sha256").update(s).digest("hex").slice(0, 16)

// ----------------------------------------------------------------------------------------------------------------------------------
// 1–3. Chép mã TS ra thư mục tạm
// ----------------------------------------------------------------------------------------------------------------------------------
const TAM = fs.mkdtempSync(path.join(os.tmpdir(), "vang-hddt-"))
const NGUON_DA_DOC = {}

function doiImport(text, ten) {
	const dong = text.split("\n")
	const ra = dong.map((d) => {
		const m = d.match(/^(\s*(?:import\b.*|\}) from ")([^"]+)(".*)$/)
		if (!m) return d
		const spec = m[2]
		if (spec.startsWith("node:")) return d
		let moi
		if (spec === "@/types") moi = "./types-app.ts"
		else if (spec === "@/lib/utils") moi = "./utils.ts"
		else if (/^\.\/[\w-]+$/.test(spec)) moi = spec + ".ts"
		else throw new Error(`${ten}.ts: import lạ ${spec}`)
		return m[1] + moi + m[3]
	})
	ra.forEach((d, i) => {
		if (d !== dong[i] && !/ from "/.test(dong[i])) throw new Error(`${ten}.ts: dòng ${i + 1} khác mà không phải import`)
	})
	return ra.join("\n")
}

function trichHam(text, ten, tep, dau = "function") {
	const i = text.indexOf(`\n${dau} ${ten}(`)
	if (i < 0) throw new Error(`${tep}: không thấy "${dau} ${ten}("`)
	const j = text.indexOf("\n}\n", i + 1)
	if (j < 0) throw new Error(`${tep}: không thấy dấu đóng của ${ten}`)
	return text.slice(i + 1, j + 2)
}

function khopNgoac(text, iMo) {
	let sau = 0
	for (let i = iMo; i < text.length; i++) {
		const c = text[i]
		if (c === "/" && text[i + 1] === "/") {
			i = text.indexOf("\n", i)
			continue
		}
		if (c === '"' || c === "'" || c === "`") {
			let j = i + 1
			while (text[j] !== c) j += text[j] === "\\" ? 2 : 1
			i = j
			continue
		}
		if (c === "{") sau++
		else if (c === "}" && --sau === 0) return i
	}
	throw new Error("không khớp ngoặc")
}

function trichMap(route, sauDong) {
	const i = route.indexOf(sauDong)
	const j = route.indexOf(".map((l) => {", i)
	if (i < 0 || j < 0) throw new Error(`publish/route.ts: không thấy .map((l) => { sau "${sauDong}"`)
	const mo = route.indexOf("{", j + ".map((l) => ".length)
	return route.slice(j + ".map(".length, khopNgoac(route, mo) + 1)
}

function trichKhoi(route, dau) {
	const i = route.indexOf(dau)
	if (i < 0) throw new Error(`publish/route.ts: không thấy "${dau}"`)
	return route.slice(i, khopNgoac(route, i + dau.length - 1) + 1)
}

for (const t of ["apply", "status", "mapper", "normalize", "reconcile", "client", "types"]) {
	const p = `lib/misa/${t}.ts`
	const goc = doc(p)
	NGUON_DA_DOC[p] = sha(goc)
	fs.writeFileSync(path.join(TAM, `${t}.ts`), doiImport(goc, t))
}
fs.writeFileSync(path.join(TAM, "package.json"), '{"type":"module"}\n')
fs.writeFileSync(path.join(TAM, "types-app.ts"), "export type MisaStatus = string\nexport type MisaRelation = string\n")

const utils = doc("lib/utils.ts")
NGUON_DA_DOC["lib/utils.ts"] = sha(utils)
const vnd = utils.match(/^const VND = new Intl\.NumberFormat\("vi-VN"\)$/m)
if (!vnd) throw new Error("lib/utils.ts: không thấy const VND")
fs.writeFileSync(path.join(TAM, "utils.ts"), vnd[0] + "\n\n" + trichHam(utils, "formatCurrency", "lib/utils.ts", "export function"))

const tepDoc = {}
for (const p of ["lib/misa/status.ts", "lib/misa/reconcile.ts", "lib/misa/mapper.ts", "lib/misa/client.ts", "lib/misa/mark-replaced.ts",
	"app/api/einvoice/publish/route.ts", "app/api/einvoice/pull-snapshots/route.ts"]) {
	tepDoc[p] = doc(p)
	NGUON_DA_DOC[p] = sha(tepDoc[p])
}
const route = tepDoc["app/api/einvoice/publish/route.ts"]
const iLookup = route.indexOf("const lookupUrl = result.lookup_code")
const lookupExpr = route.slice(iLookup, route.indexOf(": null", iLookup) + ": null".length)
const ghiChuGoc = tepDoc["lib/misa/mark-replaced.ts"].match(/misa_note:\s*([\s\S]*?`),\n/)
if (iLookup < 0 || !ghiChuGoc) throw new Error("không cắt được link tra cứu / câu đánh dấu tờ gốc")
// reconcile-action/route.ts:163–184 (`link`): khối cảnh báo + hai biểu thức match_status / match_note của câu UPDATE.
const doiSoat = doc("app/api/einvoice/reconcile-action/route.ts")
NGUON_DA_DOC["app/api/einvoice/reconcile-action/route.ts"] = sha(doiSoat)
const canhBao = (() => {
	const i0 = doiSoat.indexOf("const warnings: string[] = []")
	const i2 = doiSoat.indexOf("if (inv.misa_inv_series && snapSeries", i0)
	const st = doiSoat.match(/match_status: (warnings\.length \? "needs_review" : "matched"),/)
	const note = doiSoat.match(/match_note: (warnings\.length\s*\? `[^`]*`\s*: "[^"]*"),/)
	if (i0 < 0 || i2 < 0 || !st || !note) throw new Error("reconcile-action/route.ts: không cắt được khối cảnh báo nối tay")
	return { khoi: doiSoat.slice(i0, khopNgoac(doiSoat, doiSoat.indexOf("{", i2)) + 1), st: st[1], note: note[1] }
})()

fs.writeFileSync(path.join(TAM, "trich.ts"), [
	'import { normalizeSeries, sameInvNo, sameSeries } from "./normalize.ts"',
	'import { readSnapshot, readRelation } from "./status.ts"',
	'import { isoDateOnly } from "./apply.ts"',
	trichHam(tepDoc["lib/misa/status.ts"], "num", "status.ts"),
	trichHam(tepDoc["lib/misa/status.ts"], "str", "status.ts"),
	trichHam(tepDoc["lib/misa/reconcile.ts"], "norm", "reconcile.ts"),
	trichHam(tepDoc["lib/misa/reconcile.ts"], "looseSeries", "reconcile.ts"),
	trichHam(tepDoc["lib/misa/reconcile.ts"], "strictSeries", "reconcile.ts"),
	trichHam(tepDoc["lib/misa/mapper.ts"], "roundVnd", "mapper.ts"),
	trichHam(tepDoc["lib/misa/client.ts"], "extractToken", "client.ts"),
	trichHam(tepDoc["lib/misa/client.ts"], "extractErrorMessage", "client.ts"),
	trichHam(tepDoc["lib/misa/client.ts"], "looksLikeAuthError", "client.ts"),
	trichHam(tepDoc["lib/misa/client.ts"], "extractPublishResult", "client.ts"),
	trichHam(tepDoc["app/api/einvoice/pull-snapshots/route.ts"], "toSnapshotRow", "pull-snapshots/route.ts"),
	`export const dongHd = ${trichMap(route, "if (si) {")}`,
	`export const dongDon = ${trichMap(route, "if (order) {")}`,
	`export function dongTongHop(invoice: any) {\nlet lines: any[] = []\n${trichKhoi(route, "if (lines.length === 0) {")}\nreturn lines[0]\n}`,
	`export function urlTraCuu(result: any) {\n${lookupExpr}\nreturn lookupUrl\n}`,
	`export const ghiChuGoc = (replacementInvoiceId: string) => ${ghiChuGoc[1]}`,
	`export function canhBaoNoiTay(inv: any, snap: any) {\n${canhBao.khoi}\nreturn { warnings, match_status: ${canhBao.st}, ` +
		`match_note: ${canhBao.note} }\n}`,
	"export { num, str, norm, looseSeries, strictSeries, roundVnd, extractToken, extractErrorMessage, looksLikeAuthError, " +
		"extractPublishResult, toSnapshotRow }",
	"",
].join("\n\n"))

// ----------------------------------------------------------------------------------------------------------------------------------
// 4. Ghim thời gian, UUID; fetch giả
// ----------------------------------------------------------------------------------------------------------------------------------
const LUC = "2026-11-15T10:00:00+07:00"
const DateGoc = globalThis.Date
let gioGhim = DateGoc.parse(LUC)
globalThis.Date = class DateGhim extends DateGoc {
	constructor(...a) {
		if (a.length) super(...a)
		else super(gioGhim)
	}
	static now() {
		return gioGhim
	}
}
let demUuid = 0
const uuidThu = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`
crypto.randomUUID = () => uuidThu(++demUuid)

const API = "https://misa.gia/api/v2"
let kichBan = []
let goi = []
globalThis.fetch = async (url, init = {}) => {
	const u = String(url)
	goi.push(`${init.method || "GET"} ${u.startsWith(API) ? u.slice(API.length) : u}`)
	const b = kichBan.shift()
	if (!b) throw new Error(`fetch giả: hết kịch bản cho ${u}`)
	return new Response(b.body, { status: b.status ?? 200 })
}
const TOKEN_OK = { status: 200, body: '{"access_token":"T1","expires_in":3600}' }
let demCfg = 0
const cauHinhTs = (them = {}) => ({
	apiBase: API, taxCode: "0100000000", username: `u-thu-${++demCfg}`, password: "p-thu",
	tokenPath: "/oauth", publishPath: "/v3sainvoice", isInvoiceWithCode: false, ...them,
})

const nap = (t) => import(pathToFileURL(path.join(TAM, `${t}.ts`)).href)
const [N, S, A, Mp, R, C, T, U] = await Promise.all(
	["normalize", "status", "apply", "mapper", "reconcile", "client", "trich", "utils"].map(nap))

// ----------------------------------------------------------------------------------------------------------------------------------
// 5. Ca
// ----------------------------------------------------------------------------------------------------------------------------------
const giai = (v) => {
	if (Array.isArray(v)) return v.map(giai)
	if (v && typeof v === "object") {
		const k = Object.keys(v)
		if (k.length === 1 && (k[0] === "$so" || k[0] === "$nguyen")) return Number(v[k[0]])
		return Object.fromEntries(Object.entries(v).map(([a, b]) => [a, giai(b)]))
	}
	return v
}
const so = (lit) => ({ $so: lit })
const loiTs = (f) => {
	try {
		return { ra: f() }
	} catch (e) {
		return { loi: e.message }
	}
}
const loiTsAsync = async (f) => {
	try {
		return { ra: await f() }
	} catch (e) {
		return { loi: e.message }
	}
}
const KHONG_CO = (x) => x === undefined ? null : x
const out = {}

// Ngày có thật (H26) — kiểm bằng lịch UTC (Date.parse của V8 lăn 2026-02-30 thành 02/03 [đo]).
function ngayThat(d) {
	if (typeof d !== "string" || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(d)) return false
	const [y, m, n] = d.split("-").map(Number)
	const t = new DateGoc(0)
	t.setUTCFullYear(y, m - 1, n)
	return y >= 1 && t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === n
}
// Che token (H25) — bản JS của luật đặc tả §3.2 (regex trên chuỗi thô).
const cheToken = (s) => s.replace(/(\\?"?[A-Za-z0-9_]*token[A-Za-z0-9_]*\\?"?\s*[:=]\s*\\?"?)([^"\\,&\s}]+)/gi, (_, a) => a + "***")
const LY_DO_NULL = "Thân JSON là `null`: TS ném TypeError tiếng Anh (đọc thuộc tính của null) — bản Python coi như không có dữ liệu."

// --- §2.1 ---
out.tron = ["0", "0.5", "1.5", "2.5", "-0.5", "-1.5", "-2.5", "1234.5", "0.49999999999999994", "-0.49999999999999994",
	"4503599627370495.5", "-4503599627370495.5", "100999.00000000001", "7999.92", "NaN", "-0", "1e21"]
	.map((lit) => ({ vao: so(lit), mong: T.roundVnd(Number(lit)) }))
	.concat([null, "12", "abc", " 0x10 ", true].map((v) => ({ vao: v, mong: T.roundVnd(v) })))

out.so_js = ["0", "-0", "1", "-1", "215000", "215000.0", "0.1", "0.5", "1e20", "1e21", "1.5e21", "123456789012345680000", "1e16",
	"12345678901234567", "1e-6", "1e-7", "1.5e-7", "0.000123", "1e-4", "123.456", "-1e-7", "5e-324", "1.7976931348623157e308",
	"0.30000000000000004", "NaN", "Infinity", "-Infinity"].map((lit) => ({ vao: so(lit), mong: String(Number(lit)) }))
	.concat([{ vao: { $nguyen: "9007199254740993" }, mong: String(9007199254740993) }, { vao: { $nguyen: "215000" }, mong: "215000" },
		{ vao: null, mong: String(null) }, { vao: true, mong: String(true) }, { vao: "abc", mong: "abc" }])

out.tien_vn = ["212600", "-108002", "0", "-0", "-0.4", "-0.5", "0.5", "1.5", "-1.5", "2.5", "1234", "123", "1234567.89", "999.5",
	"-212600.5", "1e21", "1e23", "123456789012345680000", "9007199254740994", "NaN", "Infinity", "-Infinity"]
	.map((lit) => ({ vao: so(lit), mong: U.formatCurrency(Number(lit)) }))
	.concat([{ vao: null, mong: U.formatCurrency(null) }])

out.js_khoa = ['{"b":1,"2":2,"a":3,"1":4}', '{"4294967295":1,"4294967294":2,"-1":3,"01":4,"1.5":5,"0":6,"x":7}', '{"z":1,"y":2}', "{}"]
	.map((t) => ({ vao: t, mong: Object.keys(JSON.parse(t)) }))

out.js_cat = [["ab😀cd", 3], ["ab😀cd", 4], ["ab😀cd", 2], ["", 5], ["abc", 0], ["x".repeat(299) + "😀z", 300], ["é😀", 10]]
	.map(([s, n]) => ({ vao: [s, n], mong: s.slice(0, n) }))

out.js_json = ['["InvalidBuyerTaxCode"]', '[{"b":1,"1":2,"0":[3]}]', '{"a":"é\\u0001\\"\\\\\\n","b":[1.5,2,1e21,-0,1e-7,0.1]}',
	'["\\ud83d","\\ud83d\\ude00"]', "[12345678901234567890]", '{"s":"a\\u2028b\\u007f\\u001f"}', "[true,false,null,{}]"]
	.map((t) => ({ vao: t, mong: JSON.stringify(JSON.parse(t)) }))

out.chuoi = ["  a ", "", "   ", "\ufeff00000123", "\x1c1C26TAA", "\u00a0x\u00a0", "\u3000\u2028y\u2029", 123, null, true, { a: 1 }, ["x"]]
	.map((v) => ({ vao: v, mong: T.str(v) }))

out.so = ["0x3", "0X1f", "0b11", "0o17", "1_0", " 3 ", "1e5", "Infinity", "+Infinity", "-Infinity", "infinity", "inf", "nan", "NaN",
	"\ufeff3", "\x1c3", "\u00a03\u00a0", "-0x3", "+5", "-5", ".5", "5.", "1e", "", "  ", "１２", "٣", "00012", "-0", "1e400", "0x",
	"0b2", "12abc", "3.5", 3, 3.5, -2, 0, true, false, null, { a: 1 }, [3]]
	.map((v) => ({ vao: v, mong: T.num(v) }))
	.concat([{ vao: so("NaN"), mong: T.num(NaN) }, { vao: so("Infinity"), mong: T.num(Infinity) }])

out.quan_he = [1, 3, 4, 7, 8, 5, 0, 3.5, so("7.0"), "7", "07", "7.0", null, true, so("NaN"), so("-0"), 1e21]
	.map((v) => ({ vao: v, mong: S.readRelation(giai(v)) }))

// --- §2.2 ---
const CH = []
const themCH = (ham, f, ds) => ds.forEach((vao) => CH.push({ ham, vao, mong: f(...vao) }))
themCH("chuan_so", N.normalizeInvNo, [["00000123"], ["000"], [" 12 3 "], [null], [""], ["  "], ["0"], ["\ufeff0012"], ["\x1c0012"],
	["\u00a00012\u00a0"], ["0012a"], ["abc"], ["00 12"]])
themCH("cung_so", N.sameInvNo, [["00000123", "123"], ["", ""], [null, null], ["0", "000"], ["12 3", "123"], ["123", null],
	[" 123 ", "0123"]])
themCH("ky_hieu_long", N.normalizeSeries, [["1C25MHG"], [" 1c25 mhg"], ["C25MHG"], ["１C25MHG"], ["١C25MHG"], ["12C"], ["123"],
	[null], [""], ["ß1"], ["\ufeff1c25"]])
themCH("cung_ky_hieu", N.sameSeries, [["1C25MHG", "C25MHG"], ["", ""], ["1C25MHG", "2C25MHG"], ["1c25mhg", "C25MHG "],
	["123", "456"]])
themCH("ky_hieu_chat", T.strictSeries, [["1C26TAA"], [" 1c26 taa "], ["1C26\ufeffTAA"], ["1C26\x1cTAA"], ["1C26\tT\u3000AA"], [null],
	[""], ["ß"]])
themCH("mst_du", (v) => T.norm(v).replace(/\s+/g, ""), [["0301175691-044"], [" 0301 175691-044 "], ["\u00a00301175691"], [null],
	[""]])
themCH("mst_goc", R.baseTaxCode, [["0301175691-044"], ["0301175691"], [" 0301175691 - 044"], ["-044"], [null], [""]])
themCH("ngay_khop", R.matchDate, [["2026-11-10T00:00:00"], [" 2026-11-10"], ["2026-1-10"], ["٢٠٢٦-١١-١٥"], [null], [""], ["20261110"],
	["2026-11-10x"]])
themCH("ngay_iso", A.isoDateOnly, [["2026-09-04T00:00:00"], ["2026-09-04"], [" 2026-09-04 "], ["2026-13-01"], ["2026-00-10"],
	["2026-02-30"], ["2026-04-31"], ["2026-02-29"], ["2026-12-32"], ["abc"], ["٢٠٢٦-١١-١٥"], ["2026-9-4"], ["\ufeff2026-09-04"]])
themCH("la_so_cho", S.isPlaceholderInvNo, [["<Chưa cấp số>"], [" <x"], [""], ["  "], [null], ["00000123"], ["\ufeff<"], ["0"]])
themCH("so_khac", S.invNoConflict, [["123", "00000999"], ["123", "0000123"], [null, "1"], ["1", ""], ["0", "000"]])
out.chuan_hoa = CH

// --- §2.3 doc_ban_ghi ---
const bgPy = (s) => ({
	inv_no: s.invNo, inv_series: s.invSeries, inv_date: s.invDate, invoice_code: s.invoiceCode, transaction_id: s.transactionId,
	org_ref_id: s.orgRefId, deleted_reason: s.deletedReason, publish_status: s.publishStatus, einvoice_status: s.eInvoiceStatus,
	total_amount: s.totalAmount, total_without_vat: s.totalWithoutVat, total_vat: s.totalVat, huy: s.cancelled, nguon_huy: s.cancelledSource,
})
const B3 = { InvNo: "00000123", InvSeries: "1C25MHG", InvDate: "2026-09-04T00:00:00", PublishStatus: 3, EInvoiceStatus: 1,
	TransactionID: "TX1", InvoiceCode: "M1-25-XYZ", TotalAmount: 110000, TotalAmountWithoutVAT: 0, TotalVATAmount: 0 }
out.doc_ban_ghi = [B3, {}, [], "abc", { IsInvoiceDeleted: "true" }, { IsInvoiceDeleted: 1 }, { IsCancelled: true, IsCanceled: true },
	{ IsInvoiceCanceled: true, DeletedReason: " Sai giá " }, { InvNo: " 00000123 ", InvSeries: "\x1c1C26TAA", InvDate: "\ufeff2026-11-15",
		TransactionID: "", OrgRefID: "  " },
	{ PublishStatus: "0x3", EInvoiceStatus: "1_0", TotalAmount: "1e5", TotalAmountWithoutVAT: " 3 ", TotalVATAmount: "abc" },
	{ PublishStatus: 3.5, EInvoiceStatus: true, TotalAmount: -5000, InvNo: 123, InvoiceCode: null }]
	.map((raw) => ({ vao: raw, mong: bgPy(S.readSnapshot(raw)) }))

// --- §2.4 suy_trang_thai / §2.5 so_tien ---
const PH = "<Chưa cấp số>"
out.suy_trang_thai = [
	["KV-06 B2 sổ sent", { InvNo: PH, PublishStatus: 0, TotalAmount: 110000 }, false, "sent"],
	["chưa số, sổ signed", { InvNo: PH, PublishStatus: 0 }, false, "signed"],
	["chưa số, sổ trống", {}, false, null],
	["KV-06 B3", B3, false, "sent"],
	["KV-06 B10 có mã chưa mã CQT", { InvNo: "00000123", PublishStatus: 2 }, true, "sent"],
	["KV-06 B11 không mã", { InvNo: "00000123", PublishStatus: 2 }, false, "sent"],
	["KV-06 B12 EInvoiceStatus 5", { InvNo: "00000123", PublishStatus: 3, EInvoiceStatus: 5 }, false, "sent"],
	["KV-06 B14 cờ huỷ là chuỗi", { InvNo: "00000123", PublishStatus: 3, IsInvoiceDeleted: "true" }, false, "sent"],
	["không PublishStatus, không mã", { InvNo: "00000123" }, false, "sent"],
	["không PublishStatus, có mã, có mã CQT", { InvNo: "00000123", InvoiceCode: "M1" }, true, "sent"],
	["huỷ có lý do", { IsInvoiceDeleted: true, DeletedReason: "Sai giá", InvNo: "00000123", PublishStatus: 3 }, false, "signed"],
	["huỷ không lý do + quan hệ lạ", { IsCanceled: true, EInvoiceStatus: 6 }, false, "signed"],
	["bị thay thế, chưa số", { EInvoiceStatus: 7, InvNo: PH }, false, "sent"],
	["bị điều chỉnh, có số", { EInvoiceStatus: 8, InvNo: "00000123", PublishStatus: 3 }, false, "signed"],
	["bị điều chỉnh, chưa số, sổ sent", { EInvoiceStatus: 8, InvNo: PH }, false, "sent"],
	["PublishStatus '0x3'", { InvNo: "00000123", PublishStatus: "0x3" }, false, "sent"],
	["PublishStatus 0 có số", { InvNo: "00000123", PublishStatus: 0 }, false, "signed"],
	["EInvoiceStatus 3.5", { InvNo: "00000123", PublishStatus: 3, EInvoiceStatus: 3.5 }, false, null],
	["EInvoiceStatus 1e21", { InvNo: "00000123", PublishStatus: 3, EInvoiceStatus: 1e21 }, false, null],
	["PublishStatus 1, có mã, không mã CQT", { InvNo: "1", PublishStatus: 1 }, 1, null],
].map(([ten, raw, coMa, dang]) => {
	const d = S.deriveState({ snap: S.readSnapshot(raw), orgUsesInvoiceCode: !!coMa, currentStatus: dang })
	return { ten, vao: { raw, co_ma: coMa, dang }, mong: [d.status, d.relation, d.note] }
})

const SO_KV06 = { misa_status: "sent", tien_hang: 100000, tien_thue: 10000, tong_tien: 110000 }
const SO_HD3 = { tien_hang: 195000, tien_thue: 20000, tong_tien: 215000 }
out.so_tien = [
	["KV-09 lệch 1 đ", { TotalAmount: 110001 }, null, SO_KV06],
	["KV-09 lệch 2 đ", { TotalAmount: 110002 }, null, SO_KV06],
	["KV-09 thuế tách 0", { TotalAmount: 110000, TotalAmountWithoutVAT: 0.0, TotalVATAmount: 0.0 }, "new", SO_KV06],
	["KV-09 HD-0003 giảm đơn (H10)", { TotalAmount: 220000, TotalAmountWithoutVAT: 200000, TotalVATAmount: 20000 }, "new", SO_HD3],
	["KV-09 10 dòng × 10.005 @ 8 %", { TotalAmount: 108050 }, null, { tien_hang: 100050, tien_thue: 8004, tong_tien: 108054 }],
	["điều chỉnh không so", { TotalAmount: -5000 }, "adjustment", SO_KV06],
	["MISA không trả tổng", { TotalAmountWithoutVAT: 1 }, null, SO_KV06],
	["sổ không có tổng", { TotalAmount: 1 }, null, { tien_hang: 1, tien_thue: null, tong_tien: null }],
	["sổ số lẻ", { TotalAmount: 110002 }, null, { tong_tien: 110000.5 }],
	["MISA chuỗi số", { TotalAmount: "110002", TotalVATAmount: "10000" }, null, SO_KV06],
	["âm vs dương", { TotalAmount: -5000 }, "replaced", { tong_tien: 5000 }],
	["thuế lệch, tiền hàng khớp", { TotalAmount: 110000, TotalAmountWithoutVAT: 100000, TotalVATAmount: 10500 }, null, SO_KV06],
].map(([ten, raw, relation, so_]) => {
	const r = S.checkAmounts({ snap: S.readSnapshot(raw), relation,
		book: { subtotal: KHONG_CO(so_.tien_hang), vat: KHONG_CO(so_.tien_thue), total: KHONG_CO(so_.tong_tien) } })
	return { ten, vao: { raw, relation, so: so_ }, mong: [r.mismatch, r.note, r.compared] }
})

// --- §2.6 ap_dung (+ H8, H17) ---
const LUC_HOI = "2026-11-15T03:00:00.000Z"
function apDung(ten, raw, so_, coMa = false) {
	const book = { id: "E", misa_ref_id: "R", misa_inv_no: KHONG_CO(so_.misa_inv_no), misa_status: KHONG_CO(so_.misa_status),
		misa_no_locked: KHONG_CO(so_.misa_no_locked), subtotal: KHONG_CO(so_.tien_hang), vat: KHONG_CO(so_.tien_thue),
		total: KHONG_CO(so_.tong_tien) }
	const ts = A.applyMisaSnapshot(raw, book, { orgUsesInvoiceCode: !!coMa, now: LUC_HOI })
	const notes = ts.summary.notes
	if ((ts.updates.misa_note ?? null) !== (notes.length ? notes.join("\n") : null)) throw new Error(`${ten}: misa_note ≠ notes`)
	const cap = { ...ts.updates }
	delete cap.misa_note
	const mong = { cap_nhat: cap, ghi_chu: [...notes], danh_dau_goc: ts.markOriginalReplaced,
		tom_tat: { InvNo: ts.summary.invNo, status: ts.summary.status, relation: ts.summary.relation,
			amountsCompared: ts.summary.amountsCompared, notes: null } }
	const lech = []
	const snap = S.readSnapshot(raw)
	const d = S.deriveState({ snap, orgUsesInvoiceCode: !!coMa, currentStatus: book.misa_status })
	if (S.isPlaceholderInvNo(snap.invNo) && !S.isPlaceholderInvNo(book.misa_inv_no) && d.status === "sent") {
		mong.ghi_chu.splice(d.note ? 1 : 0, 0,
			`MISA trả bản ghi chưa có số trong khi sổ đã ghi số ${book.misa_inv_no} — giữ nguyên trạng thái, cần kiểm tra tay.`)
		if (ts.summary.status === "sent") {
			delete mong.cap_nhat.misa_status
			mong.tom_tat.status = null
		}
		lech.push("H8")
	}
	const goTay = T.str(so_.so_hd_go_tay)
	if (goTay && !S.isPlaceholderInvNo(snap.invNo) && !N.sameInvNo(goTay, snap.invNo)) {
		mong.ghi_chu.push(`Sổ ghi số ${goTay}, MISA cấp số ${snap.invNo}.`)
		lech.push("H17")
	}
	mong.tom_tat.notes = [...mong.ghi_chu]
	const ca = { ten, vao: { raw, so: so_, co_ma: coMa, luc: LUC_HOI }, mong }
	if (lech.length) {
		ca.lech = {
			ma: lech.join(" + "),
			ly_do: lech.map((m) => m === "H8"
				? "H8: MISA trả bản ghi chưa có số cho tờ sổ đã có số — nppsale hạ về 'sent', bản Python giữ trạng thái + ghi chú."
				: "H17: số gõ tay (so_hd_go_tay) khác số MISA — thêm ghi chú, không đổi trạng thái (nppsale im lặng).").join(" "),
			ts: { updates: ts.updates, markOriginalReplaced: ts.markOriginalReplaced, summary: ts.summary },
		}
	}
	return ca
}
const SO_SIGNED = { misa_status: "signed", misa_inv_no: "00000123", tien_hang: 100000, tien_thue: 10000, tong_tien: 110000 }
out.ap_dung = [
	apDung("KV-06 B2", { InvNo: PH, PublishStatus: 0, TotalAmount: 110000 }, SO_KV06),
	apDung("KV-06 B3", B3, SO_KV06),
	apDung("KV-06 B10", { InvNo: "00000123", PublishStatus: 2, TotalAmount: 110000 }, SO_KV06, true),
	apDung("KV-06 B11", { InvNo: "00000123", PublishStatus: 2, TotalAmount: 110000 }, SO_KV06, false),
	apDung("KV-06 B12", { InvNo: "00000123", PublishStatus: 3, EInvoiceStatus: 5, TotalAmount: 110000 }, SO_KV06),
	apDung("KV-06 B14", { InvNo: "00000123", PublishStatus: 3, IsInvoiceDeleted: "true", TotalAmount: 110000 }, SO_KV06),
	apDung("KV-06 (+) PublishStatus vắng", { InvNo: "00000123", TotalAmount: 110000 }, SO_KV06),
	apDung("KV-07 B4 huỷ + lệch", { IsInvoiceDeleted: true, DeletedReason: "Sai giá", InvNo: "00000123", PublishStatus: 3, TotalAmount: 99000 },
		SO_SIGNED),
	apDung("KV-07 B5 thay thế", { EInvoiceStatus: 3, OrgRefID: "goc-1", InvNo: "00000124", PublishStatus: 3, TotalAmount: 110000 }, SO_SIGNED),
	apDung("KV-07 B6 điều chỉnh", { EInvoiceStatus: 4, OrgRefID: "goc-1", InvNo: "00000125", PublishStatus: 3, TotalAmount: -5000 },
		SO_SIGNED),
	apDung("KV-07 B7 bị điều chỉnh", { EInvoiceStatus: 8, InvNo: "00000123", PublishStatus: 3, TotalAmount: 110000 }, SO_SIGNED),
	apDung("KV-07 B8 bị thay thế", { EInvoiceStatus: 7, InvNo: "00000123", PublishStatus: 3, TotalAmount: 110000 }, SO_SIGNED),
	apDung("KV-08 B9 khoá gán tay, số khác", { InvNo: "00000999", PublishStatus: 3, EInvoiceStatus: 1, TotalAmount: 110000 },
		{ misa_no_locked: true, misa_inv_no: "123", misa_status: "signed", tong_tien: 110000 }),
	apDung("KV-08 B9 khoá gán tay, cùng số", { InvNo: "0000123", PublishStatus: 3, EInvoiceStatus: 1, TotalAmount: 110000 },
		{ misa_no_locked: true, misa_inv_no: "123", misa_status: "signed", tong_tien: 110000 }),
	apDung("KV-08 B1 [H8] MISA trả {}", {}, SO_SIGNED),
	apDung("H8 + lệch tiền", { InvNo: PH, TotalAmount: 120000 }, SO_SIGNED),
	apDung("H8 + bị điều chỉnh (ghi chú suy trạng thái đứng trước)", { InvNo: PH, EInvoiceStatus: 8, TotalAmount: 110000 }, SO_SIGNED),
	apDung("không H8: sổ đang sent có số", { InvNo: PH }, { ...SO_SIGNED, misa_status: "sent" }),
	apDung("không H8: sổ chưa có số", { InvNo: PH }, { misa_status: "error", tong_tien: 1 }),
	apDung("KV-08 [H17] số gõ tay khác", { InvNo: "00000123", PublishStatus: 3, TotalAmount: 110000 },
		{ ...SO_KV06, so_hd_go_tay: "INV-20261115-1234" }),
	apDung("H17 cùng số sau chuẩn hoá", { InvNo: "00000123", PublishStatus: 3, TotalAmount: 110000 }, { ...SO_KV06, so_hd_go_tay: " 123 " }),
	apDung("H17 MISA chưa cấp số", { InvNo: PH, PublishStatus: 0 }, { ...SO_KV06, so_hd_go_tay: "INV-1" }),
	apDung("H17 + khoá gán tay + lệch", { InvNo: "00000999", PublishStatus: 3, TotalAmount: 120000 },
		{ misa_no_locked: 1, misa_inv_no: "123", misa_status: "signed", tong_tien: 110000, so_hd_go_tay: "123" }),
	apDung("KV-09 lệch 1 đ", { InvNo: "00000123", PublishStatus: 3, TotalAmount: 110001 }, SO_KV06),
	apDung("KV-09 lệch 2 đ", { InvNo: "00000123", PublishStatus: 3, TotalAmount: 110002 }, SO_KV06),
	apDung("KV-09 HD-0003", { InvNo: "00000126", PublishStatus: 3, TotalAmount: 220000, TotalAmountWithoutVAT: 200000, TotalVATAmount: 20000 },
		{ misa_status: "sent", ...SO_HD3 }),
	apDung("bị thay thế + lệch: giữ replaced", { EInvoiceStatus: 7, InvNo: "00000123", TotalAmount: 1 }, SO_SIGNED),
	apDung("huỷ + thay thế: huỷ thắng", { IsInvoiceDeleted: true, EInvoiceStatus: 7, InvNo: "00000123" }, SO_SIGNED),
	apDung("ngày không có thật vẫn ghi (H26 ở hàm ghi)", { InvNo: "00000123", InvDate: "2026-02-30T00:00:00", PublishStatus: 3,
		TotalAmount: 110000 }, SO_KV06),
	apDung("ngày rác bỏ qua", { InvNo: "00000123", InvDate: "abc", PublishStatus: 3 }, SO_KV06),
	apDung("BOM ở số + chuỗi tiền", { InvNo: "\ufeff00000123", PublishStatus: "3", TotalAmount: "110000", InvSeries: " 1C26TAA " }, SO_KV06),
	apDung("bản ghi là mảng", [], SO_KV06),
	apDung("sổ tiền số thực, sổ không tiền", { InvNo: "1", PublishStatus: 3, TotalAmount: 5, TotalVATAmount: 2 },
		{ misa_status: "sent", tien_thue: 0.5, tong_tien: null }),
]

// --- §2.7 dòng hàng + payload ---
const lTs = (c) => ({ unit_name: c.dvt, quantity: c.sl, unit_price: c.gia_ban, line_discount: c.giam, conversion_factor: c.he_so,
	vat_rate: c.thue, product: { name: c.ten, sku: c.sku, base_unit: c.dvt_co_so, vat_rate: c.thue } })
const dongPy = (m) => ({ ten: m.product_name, sku: KHONG_CO(m.sku), dvt: KHONG_CO(m.unit_name), dvt_co_so: KHONG_CO(m.base_unit),
	sl: m.quantity, don_gia: m.unit_price, he_so: m.conversion_factor, vat: KHONG_CO(m.vat_rate), giam: m.line_discount })
const dongTs = (d) => ({ product_name: d.ten, sku: d.sku, unit_name: d.dvt, base_unit: d.dvt_co_so, quantity: d.sl, unit_price: d.don_gia,
	conversion_factor: d.he_so, vat_rate: d.vat, line_discount: d.giam })
const ct = (nhanh, ten, sku, dvt, dvt_co_so, sl, gia_ban, giam, he_so, thue) =>
	({ nhanh, ten, sku, dvt, dvt_co_so, sl, gia_ban, giam, he_so, thue })
const dongCt = (c) => (c.nhanh === "don" ? T.dongDon : T.dongHd)(giai(lTs(c)))

const HD1 = [ct("hd", "Kẹo", "SP04", "Gói", "Gói", 10, 10000, 0, 1, 0.1), ct("hd", "Nước", "SP05", "Chai", "Chai", 5, 19000, 5000, 1, 0.08)]
const HD2 = [ct("hd", "Bia lon", "SP01", "Thùng", "Lon", 2, 240000, 0, 24, 0.1), ct("hd", "Sữa hộp", "SP02", "Hộp", "Hộp", 1, 0, 0, 1, 0.1),
	ct("hd", "Bánh", "SP03", "Hộp", "Hộp", 3, 33333, 1000, 1, 0.08)]
out.dong_hang = [...HD1, ...HD2,
	ct("hd", "Kẹo", "SP04", null, "Gói", 2, 100, 50, null, 10),
	ct("hd", null, "", null, null, 0, 500, 100, 0, null),
	ct("hd", "Trả", "SP09", "Hộp", "Hộp", -1, 1000, 100, 1, 1),
	ct("hd", "Lẻ", "SP10", "Kg", "Kg", 1.5, 21000, 1000, 1, 0.05),
	ct("hd", "Thuế 1,5", "SP11", "Cái", null, 1, 1000, 0, 1, 1.5),
	ct("hd", "Thuế 0,0525", "SP12", "Cái", null, 1, 1000, 0, 1, 0.0525),
	ct("hd", "Chuỗi rỗng", "SP13", "Cái", null, 1, 1000, 0, 1, ""),
	ct("don", "Nhánh đơn", "SP14", "Thùng", "Lon", 1, 240000, 0, 24, null),
	ct("don", "Nhánh đơn 8 %", "SP15", "Hộp", "Hộp", 3, 33333, 1000, 1, 0.08),
].map((c) => ({ vao: c, mong: dongPy(dongCt(c)) }))
out.dong_tong_hop = [[195000, 17600, 212600], [0, 0, 50000], [null, null, null], [100000, 5000, 105000], [100, 33, 133],
	[195000, null, 195000], [-100, 10, -90]]
	.map(([th, tt, tg]) => ({ vao: { tien_hang: th, tien_thue: tt, tong_tien: tg },
		mong: dongPy(T.dongTongHop({ subtotal: th, vat: tt, total: tg })) }))

const CFG = { misa_company_id: "156217", misa_org_unit_id: null, misa_user_id: null, misa_template_id: null, misa_inv_series: "1C26TAA",
	misa_inv_template_no: "1", loai_hd: 1, ke_thua_mau_cu: 0 }
const MUA = { ten: "Tạp hoá A", mst: "0301175691-044", dia_chi: "12 Lê Lợi", email: null, kenh: null, hinh_thuc_tt: "Chuyển khoản" }
function payload(ten, { nguoi_mua = MUA, dong, dong_ct, tong_hop, cau_hinh = CFG, che_do = "as_sold", po_note = null, luc = LUC }) {
	gioGhim = DateGoc.parse(luc)
	demUuid = 0
	let lines
	if (dong_ct) lines = dong_ct.map(dongCt)
	else if (tong_hop) lines = [T.dongTongHop({ subtotal: tong_hop.tien_hang, vat: tong_hop.tien_thue, total: tong_hop.tong_tien })]
	else lines = giai(dong).map(dongTs)
	const p = Mp.invoiceToMisaPayload({
		buyer: { name: nguoi_mua.ten, tax_code: nguoi_mua.mst, address: nguoi_mua.dia_chi, email: nguoi_mua.email, channel: nguoi_mua.kenh,
			payment_method_label: nguoi_mua.hinh_thuc_tt },
		seller: { name: "NPP thử", taxCode: "0100000000", address: "" },
		lines, mode: che_do, poNote: po_note || null,
		invSeries: cau_hinh.misa_inv_series, invTemplateNo: cau_hinh.misa_inv_template_no, companyId: cau_hinh.misa_company_id,
		orgUnitId: cau_hinh.misa_org_unit_id, templateId: cau_hinh.misa_template_id, userId: cau_hinh.misa_user_id,
		invoiceType: cau_hinh.loai_hd ?? 1, isInheritFromOldTemplate: !!cau_hinh.ke_thua_mau_cu,
	})
	gioGhim = DateGoc.parse(LUC)
	const vao = { nguoi_mua, cau_hinh, che_do, po_note, luc, uuid: Array.from({ length: demUuid }, (_, i) => uuidThu(i + 1)) }
	if (dong_ct) vao.dong_ct = dong_ct
	else if (tong_hop) vao.tong_hop = tong_hop
	else vao.dong = dong
	return { ten, vao, mong: p }
}
const d = (ten, sl, don_gia, giam, vat, them = {}) => ({ ten, sku: null, dvt: "Hộp", dvt_co_so: null, sl, don_gia, he_so: 1, vat, giam, ...them })
out.dung_payload = [
	payload("KV-01 hai mức thuế, giảm dòng, PO", { dong_ct: HD1, po_note: "PO-7" }),
	payload("KV-02 chiết khấu không chia hết", { dong_ct: [ct("hd", "Bánh", "SP03", "Hộp", "Hộp", 3, 33333, 1000, 1, 0.1)] }),
	payload("KV-03 quy đổi hộp + đầu vào lạ", { che_do: "box", nguoi_mua: { ...MUA, hinh_thuc_tt: null }, dong: [
		d("Bia", 2, 100000, 0, 10, { dvt: "Thùng", dvt_co_so: "Lon", he_so: 24 }), d("X", 2, 1000, 0, null, { he_so: 0 }),
		d("Y", 2, 1000, 0, 0, { dvt_co_so: "cái" })] }),
	payload("KV-04 làm tròn nửa đồng", { dong: [d("X", 1, 12345, 0, 10)] }),
	payload("KV-05 không dòng", { dong: [] }),
	payload("KV-05 dòng tổng hợp", { tong_hop: { tien_hang: 195000, tien_thue: 17600, tong_tien: 212600 } }),
	payload("KV-28 HD-0002 as_sold", { dong_ct: HD2 }),
	payload("KV-28 HD-0002 box", { dong_ct: HD2, che_do: "box" }),
	payload("KV-09 10 dòng × 10.005 @ 8 %", { dong: Array.from({ length: 10 }, (_, i) => d(`Hàng ${i + 1}`, 1, 10005, 0, 8)) }),
	payload("SL lẻ + box lẻ", { che_do: "box", dong: [d("Gạo", 1.5, 10000, 0, 5, { dvt: "Kg" }),
		d("Bia", 0.5, 240000, 0, 10, { dvt: "Thùng", dvt_co_so: "Lon", he_so: 24 }),
		d("Nước", 1, 100, 0, 10, { dvt: "Thùng", dvt_co_so: "Chai", he_so: 24 })] }),
	payload("kênh MT + PO có khoảng trắng", { nguoi_mua: { ...MUA, kenh: "MT" }, po_note: "  PO-9 ", dong: [d("X", 1, 1000, 0, 10)] }),
	payload("PO chỉ khoảng trắng, kênh mt", { nguoi_mua: { ...MUA, kenh: "mt", email: "a@b.vn" }, po_note: " \u3000 ",
		dong: [d("X", 1, 1000, 0, 10)] }),
	payload("cấu hình trống / 0 / kế thừa", { cau_hinh: { misa_company_id: "", misa_org_unit_id: "ou", misa_user_id: "us",
		misa_template_id: "tpl", misa_inv_series: null, misa_inv_template_no: "", loai_hd: 0, ke_thua_mau_cu: 1 },
	nguoi_mua: { ten: "Cty \"B\"\u0001 😀", mst: null, dia_chi: null, email: null, kenh: null, hinh_thuc_tt: null }, dong: [d("X", 1, 1, 0, 10)] }),
	payload("loại HĐ trống → 1", { cau_hinh: { ...CFG, loai_hd: null }, dong: [d("X", 1, 1000, 0, 10)] }),
	payload("bốn mức thuế", { dong: [d("A", 1, 1000, 0, 0), d("B", 1, 1000, 0, 5), d("C", 1, 1000, 0, 8), d("D", 1, 1000, 0, 10)] }),
	payload("một mức 8 %", { dong: [d("A", 2, 1000, 0, 8), d("B", 1, 999, 0, 8)] }),
	payload("thuế số thực 10.0 + SL số thực", { dong: [d("A", so("2.0"), so("1000.0"), so("0.0"), so("10.0"))] }),
	payload("qua nửa đêm UTC → ngày VN hôm sau", { luc: "2026-11-15T17:30:05Z", dong: [d("X", 1, 1000, 0, 10)] }),
	payload("chế độ lạ = as_sold", { che_do: "thung", dong: [d("Bia", 2, 240000, 0, 10, { dvt: "Thùng", dvt_co_so: "Lon", he_so: 24 })] }),
	payload("nhánh đơn: thuế hiện hành trống → 10", { dong_ct: [ct("don", "Đơn cũ", "SP14", "Thùng", "Lon", 1, 240000, 0, 24, null),
		ct("don", "Đơn cũ 2", "SP15", "Hộp", "Hộp", 3, 33333, 1000, 1, 0.08)], che_do: "box" }),
]
out.url_tra_cuu = ["TXABC", "TX ABC/1?&=+#~!*'()é", null, ""].map((ma) => ({ vao: ma, mong: T.urlTraCuu({ lookup_code: ma }) }))
out.canh_bao_noi_tay = [
	["0000300", null, "00000201", "1C26TAA"], ["00000201", "1C26TAA", "201", "1C26TAA"], ["123", "1C26TAA", "123", "C26TAA"],
	["123", "1C26TAA", "123", "1C26TAB"], ["300", "2C26TAA", "201", "1C26TAB"], [null, null, "1", "X"], ["1", "X", null, ""],
	["", "", "1", "Y"],
].map(([no, se, sno, sse]) => {
	const r = T.canhBaoNoiTay({ misa_inv_no: no, misa_inv_series: se }, { inv_no: sno, inv_series: sse })
	return { vao: [no, se, sno, sse], mong: [r.warnings, r.match_status, r.match_note] }
})
out.ghi_chu_bi_thay_the = ["E10", "0b6c9f9e-1111-4222-8333-444455556666"].map((v) => ({ vao: v, mong: T.ghiChuGoc(v) }))

// --- §2.8 đọc phản hồi ---
out.loi_misa = [
	[{ error_description: "Sai", error: "invalid_grant" }, "x"], [{ error: "x" }, "y"], [{ error: "x", error_description: "x" }, "y"],
	[{ error: "", error_description: "Mô tả" }, "y"], [{ error_description: 5, error: "x", message: "m" }, "y"],
	[{ ErrorCode: "E1", DescriptionErrorCode: "D", descriptionErrorCode: "d", Errors: "Es", errorMessage: "em", message: "m" }, "y"],
	[{ ErrorCode: ["E1"] }, '{"ErrorCode":["E1"]}'], [null, "abc"], [[], "x".repeat(600)], [{}, "x".repeat(499) + "😀tail"],
	[{ error_description: true, error: "x" }, "t"], [{ error_description: "", error: 0, message: "" }, "t"], [{ error: { a: 1 } }, "t"],
	["chuỗi", "t"],
].map(([data, text]) => ({ vao: [data, text], mong: T.extractErrorMessage(data, text) }))
out.la_loi_xac_thuc = [[401, ""], [403, "x"], [400, "Token mismatch"], [500, "EXPIRED"], [500, "Unauthorized access"], [500, "oops"],
	[400, "TO\u212aEN"], [200, "token"], [404, ""]].map(([st, t]) => ({ vao: [st, t], mong: T.looksLikeAuthError(st, t) }))

const J = JSON.stringify
const R1 = "rid-1"
const mapR = (o) => J({ [R1]: o })
async function phanHoiDay(ten, status, text) {
	kichBan = [TOKEN_OK, { status, body: text }, TOKEN_OK, { status, body: text }]
	goi = []
	const r = await C.publishInvoice(cauHinhTs(), [{ RefID: R1 }])
	kichBan = []
	const mong = { ok: r.ok, raw: r.raw, error: r.ok ? null : r.error, lookup_code: KHONG_CO(r.lookup_code), inv_no: KHONG_CO(r.inv_no),
		ref_id: KHONG_CO(r.ref_id) }
	return { ten, vao: { status, text }, mong, thu_lai: goi.filter((g) => g.startsWith("POST /v3sainvoice")).length === 2 }
}
out.hieu_phan_hoi_day = [
	await phanHoiDay("KV-10 map RefID → Data chuỗi OBJECT (H20: không đọc được mã)", 200, J({ success: true, data: mapR({
		Data: J({ RefID: R1, InvNo: PH }), ErrorMessage: null, ErrorCode: [], Success: true, EntityState: 0 }) })),
	await phanHoiDay("KV-10 map RefID → Data chuỗi MẢNG", 200, J({ success: true, data: mapR({
		Data: J([{ RefID: R1, InvNo: "00000123", TransactionID: "TXABC" }]), Success: true }) })),
	await phanHoiDay("KV-10 map RefID → Data OBJECT", 200, J({ success: true, data: mapR({
		Data: { RefID: R1, InvNo: "00000123", TransactionID: "TXABC" }, Success: true }) })),
	await phanHoiDay("KV-10 data = chuỗi mảng HĐ", 200, J({ success: true, data: J([{ RefID: R1, InvNo: "00000123", TransactionID: "TXABC" }]) })),
	await phanHoiDay("KV-10 data = chuỗi object phẳng", 200, J({ success: true, data: J({ RefID: R1, InvNo: "00000123", TransactionID: "TXABC" }) })),
	await phanHoiDay("KV-10 trường ngay ngoài cùng", 200, J({ success: true, TransactionID: "TXABC", InvNo: "00000123" })),
	await phanHoiDay("KV-10 / KV-19 MISA từ chối", 200, J({ success: true, data: mapR({ Data: null,
		ErrorMessage: "Mã số thuế người mua không hợp lệ", ErrorCode: ["InvalidBuyerTaxCode"], Success: false }) })),
	await phanHoiDay("KV-10 success + data rỗng", 200, J({ success: true, data: "" })),
	await phanHoiDay("KV-10 Success false + ErrorCode chuỗi", 200, J({ Success: false, ErrorCode: "InvalidTemplate",
		DescriptionErrorCode: "Mẫu không tồn tại" })),
	await phanHoiDay("KV-10 / KV-20 HTTP 500 HTML", 500, "<html>Bad gateway</html>"),
	await phanHoiDay("thứ tự khoá JS: khoá số đứng trước", 200, J({ success: true, data: '{"b":{"Success":true,"ErrorMessage":"B"},' +
		'"2":{"Success":false,"ErrorMessage":"2"}}' })),
	await phanHoiDay("thứ tự khoá JS: khoá số sau cùng thắng", 200, J({ success: true, data: '{"2":{"Success":true},"b":{"Success":false,' +
		'"ErrorMessage":"b hỏng"}}' })),
	await phanHoiDay("ErrorCode là mảng object khoá số", 200, J({ success: true, data: mapR({ Success: false,
		ErrorCode: [{ b: 1, 1: 2 }, "X"] }) })),
	await phanHoiDay("ErrorMessage sau thay, ErrorCode nối", 200, J({ success: true, data: J({ a: { ErrorMessage: "A", ErrorCode: ["X"] },
		c: { ErrorMessage: "B", Success: false } }) })),
	await phanHoiDay("Success true sau cùng thắng", 200, J({ success: true, data: J({ a: { Success: false, ErrorMessage: "A",
		ErrorCode: ["X"] }, c: { Success: true, Data: J([{ InvNo: "7" }]) } }) })),
	await phanHoiDay("Data lồng bóc đệ quy", 200, J({ success: true, data: mapR({ Success: true,
		Data: J({ K: { Success: false, ErrorMessage: "inner" } }) }) })),
	await phanHoiDay("HTTP 401 error_description (thử lại)", 401, J({ error: "invalid_token", error_description: "Token hết hạn" })),
	await phanHoiDay("H27 400 có chữ token (thử lại)", 400, J({ message: "InvalidInvoiceTemplate token mismatch" })),
	await phanHoiDay("HTTP 400 thân dài + emoji ở mép 500", 400, "x".repeat(499) + "😀" + "đuôi"),
	await phanHoiDay("thân null", 200, "null"),
	await phanHoiDay("thân mảng", 200, "[1,2]"),
	await phanHoiDay("thân chuỗi JSON", 200, '"chuỗi"'),
	await phanHoiDay("thân rỗng", 200, ""),
	await phanHoiDay("data = '[]'", 200, J({ success: true, data: "[]" })),
	await phanHoiDay("data = '[null]'", 200, J({ success: true, data: "[null]" })),
	await phanHoiDay("map → giá trị mảng", 200, J({ success: true, data: '{"R":[{"x":1}]}' })),
	await phanHoiDay("số lớn ở mã tra cứu, số ở InvNo", 200, '{"success":true,"TransactionID":12345678901234567890,"InvNo":123,"RefID":0}'),
	await phanHoiDay("content null", 200, J({ success: true, content: null })),
	await phanHoiDay("content 0", 200, J({ success: true, content: 0 })),
	await phanHoiDay("Success là chuỗi 'false'", 200, J({ Success: "false" })),
	await phanHoiDay("errorCode chuỗi + message", 200, J({ errorCode: "E1", message: "Lỗi x" })),
	await phanHoiDay("error rỗng + error_description rỗng", 200, J({ success: false, error: "", error_description: "" })),
	await phanHoiDay("newdata chuỗi mảng", 201, J({ newdata: J([{ TransactionID: "TXN", RefID: "R9" }]) })),
	await phanHoiDay("không phải JSON, 200", 200, "OK"),
	await phanHoiDay("NaN không phải JSON", 200, '{"success":true,"InvNo":NaN}'),
]

async function token(ten, status, text, { ma, ly_do } = {}) {
	kichBan = [{ status, body: text }]
	const cfg = cauHinhTs()
	const r = await loiTsAsync(() => C.getToken(cfg, true))
	kichBan = []
	const ca = { ten, vao: { status, text } }
	const mong = { token: KHONG_CO(r.ra), loi: KHONG_CO(r.loi) }
	if (r.ra) {
		kichBan = [{ status, body: text }, { status, body: text }]
		mong.tho = (await C.getTokenWithRawResponse(cauHinhTs())).raw
		kichBan = []
	}
	const lech = []
	if (r.loi && r.loi.startsWith("MISA token: không thấy access_token")) {
		const moi = `MISA token: không thấy access_token trong response. Raw: ${cheToken(text).slice(0, 300)}`
		if (moi !== r.loi) {
			mong.loi = moi
			lech.push(["H25", "H25: phần Raw của câu lỗi che giá trị khoá có chữ 'token' — nppsale in nguyên (token lọt vào misa_error / nhật ký)."])
		}
	}
	if (ma) {
		mong.token = null
		mong.loi = `MISA token: không thấy access_token trong response. Raw: ${cheToken(text).slice(0, 300)}`
		lech.push([ma, ly_do])
	}
	ca.mong = mong
	if (lech.length) ca.lech = { ma: lech.map((x) => x[0]).join(" + "), ly_do: lech.map((x) => x[1]).join(" "), ts: r }
	return ca
}
out.doc_phan_hoi_token = [
	await token("access_token", 200, J({ access_token: "T1", expires_in: 3600 })),
	await token("accessToken", 200, J({ accessToken: "T2" })),
	await token("Data.access_token", 200, J({ Data: { access_token: "T3" } })),
	await token("data.access_token", 200, J({ data: { access_token: "T4" }, CompanyID: 1 })),
	await token("Data là chuỗi (không đọc)", 200, J({ Data: J({ access_token: "T5" }) })),
	await token("KV-14 200 kèm error + status 401", 200, J({ error: "invalid_grant", error_description: "Sai tài khoản hoặc mật khẩu", status: 401 })),
	await token("status là chuỗi → HTTP", 200, J({ error: "x", status: "401" })),
	await token("HTTP 500 HTML", 500, "<html>x</html>"),
	await token("HTTP 400 {}", 400, "{}"),
	await token("KV-14 {foo:1}", 200, J({ foo: 1 })),
	await token("KV-55 token dưới khoá lạ", 200, '{"Data":{"AccessToken":"TOKEN-GIA-123"},"expires_in":3600}'),
	await token("thân dạng form", 200, "access_token=abc123&token_type=bearer"),
	await token("thân rỗng", 200, ""),
	await token("thân null", 200, "null", { ma: "≠ nhỏ", ly_do: LY_DO_NULL }),
	await token("access_token rỗng", 200, J({ access_token: "" })),
	await token("access_token là số", 200, J({ access_token: 123 })),
	await token("HTTP 401 error", 401, J({ error: "invalid_client" })),
	await token("thân mảng", 200, "[1,2]"),
	await token("thân dài > 300, token ở cuối", 200, J({ pad: "x".repeat(320), refresh_token: "R-BI-MAT" })),
]

async function layHd(ten, status, text, { ma, ly_do, mong } = {}) {
	kichBan = [TOKEN_OK, { status, body: text }]
	const r = await loiTsAsync(() => C.getInvoiceByRefId(cauHinhTs(), R1))
	kichBan = []
	const v = r.ra
	const ca = { ten, vao: { status, text }, mong: { loi: KHONG_CO(r.loi),
		ban_ghi: v && typeof v === "object" && !Array.isArray(v) ? v : (v ? {} : null) } }
	if (ma) {
		ca.lech = { ma, ly_do, ts: r }
		ca.mong = mong
	}
	return ca
}
out.doc_phan_hoi_lay_hd = [
	await layHd("data chuỗi object", 200, J({ success: true, data: J({ RefID: R1, InvNo: "00000123", PublishStatus: 3 }) })),
	await layHd("Data khi data vắng", 200, J({ Data: J({ InvNo: "1" }) })),
	await layHd("Data khi data null", 200, J({ data: null, Data: J({ InvNo: "2" }) })),
	await layHd("data rỗng không lùi về Data", 200, J({ data: "", Data: J({ InvNo: "3" }) })),
	await layHd("data là số", 200, J({ data: 5 })),
	await layHd("KV-13 data:null", 200, J({ success: true, data: null })),
	await layHd("data không phải JSON", 200, J({ data: "khong-json" })),
	await layHd("data 'null'", 200, J({ data: "null" })),
	await layHd("data '[1]' → {}", 200, J({ data: "[1]" })),
	await layHd("data '0'", 200, J({ data: "0" })),
	await layHd("data chuỗi chuỗi", 200, J({ data: '"abc"' })),
	await layHd("data 'false'", 200, J({ data: "false" })),
	await layHd("data 'true'", 200, J({ data: "true" })),
	await layHd("KV-13 GET 401", 401, "Unauthorized"),
	await layHd("KV-13 Success false", 200, J({ Success: false, ErrorCode: "NotFound" })),
	await layHd("success false không câu", 200, J({ success: false })),
	await layHd("thân null", 200, "null", { ma: "≠ nhỏ", ly_do: LY_DO_NULL, mong: { loi: null, ban_ghi: null } }),
	await layHd("thân rỗng", 200, ""),
	await layHd("HTTP 500 thân rỗng", 500, ""),
	await layHd("thân là mảng", 200, '[{"data":"x"}]'),
]

async function ds(ten, status, text, { ma, ly_do, mong } = {}) {
	kichBan = [TOKEN_OK, { status, body: text }]
	const r = await loiTsAsync(() => C.listInvoices(cauHinhTs(), { fromDate: "2026-09-17", toDate: "2026-11-15", start: 0, length: 100 }))
	kichBan = []
	const ca = { ten, vao: { status, text }, mong: r.loi ? { loi: r.loi, dong: [], records_total: null }
		: { loi: null, dong: r.ra.rows, records_total: r.ra.recordsTotal } }
	if (ma) {
		ca.lech = { ma, ly_do, ts: r }
		ca.mong = mong
	}
	return ca
}
out.doc_phan_hoi_ds = [
	await ds("KV-13 recordsTotal 0 + 2 dòng", 200, J({ success: true, recordsTotal: 0, data: J([{ RefID: "a" }, { RefID: "b" }]) })),
	await ds("KV-13 Data không JSON + RecordsTotal 5", 200, J({ Data: "khong-phai-json", RecordsTotal: 5 })),
	await ds("recordsTotal chuỗi", 200, J({ recordsTotal: "5", data: "[]" })),
	await ds("recordsTotal null → RecordsTotal", 200, J({ recordsTotal: null, RecordsTotal: 7, data: '{"a":1}' })),
	await ds("HTTP 401", 401, "Unauthorized"),
	await ds("Success false", 200, J({ Success: false, message: "Lỗi" })),
	await ds("recordsTotal vắng", 200, J({ success: true, data: "[]" })),
	await ds("thân null", 200, "null", { ma: "≠ nhỏ", ly_do: LY_DO_NULL, mong: { loi: null, dong: [], records_total: null } }),
	await ds("dòng không phải object", 200, J({ data: '[1,"x",null]' })),
	await ds("recordsTotal số lẻ, data rỗng", 200, J({ recordsTotal: 3.5, data: "" })),
]

async function mau(ten, status, text, { ma, ly_do, mong } = {}) {
	kichBan = [TOKEN_OK, { status, body: text }]
	const r = await loiTsAsync(() => C.getInvoiceTemplates(cauHinhTs()))
	kichBan = []
	const ca = { ten, vao: { status, text }, mong: { loi: KHONG_CO(r.loi), mau: r.ra ?? [] } }
	if (ma) {
		ca.lech = { ma, ly_do, ts: r }
		ca.mong = mong
	}
	return ca
}
out.doc_phan_hoi_mau = [
	await mau("một mẫu", 200, J({ success: true, data: J([{ IPTemplateID: "t1", InvSeries: "1C26TAA", IsPublished: true }]) })),
	await mau("Data object", 200, J({ Data: '{"a":1}' })),
	await mau("data không JSON", 200, J({ data: "x" })),
	await mau("HTTP 500", 500, "boom"),
	await mau("Success false", 200, J({ Success: false, errorMessage: "Sai" })),
	await mau("thân null", 200, "null", { ma: "≠ nhỏ", ly_do: LY_DO_NULL, mong: { loi: null, mau: [] } }),
]

out.tach_dinh_danh = [
	{ Data: '{"CompanyID":156217,"OrganizationUnitID":"ou","UserID":"us","IsInvoiceWithCode":"True"}' },
	{ access_token: "T", CompanyID: "c1", Data: { CompanyID: "c2", IsInvoiceWithCode: false } },
	{ data: '[{"CompanyID":"x"}]' },
	{ Data: "khong-json", data: { UserID: 0 } },
	{ IsInvoiceWithCode: " FALSE " }, { isInvoiceWithCode: "yes", IsInvoiceWithCode: 1 },
	null, [], "abc", { CompanyID: "", companyID: "c3" }, { Data: { OrgUnitID: "o" }, organizationUnitId: "o2" },
	{ Data: '"chuỗi"', data: "null", UserID: "u" },
].map((raw) => ({ vao: raw, mong: C.extractTenantIds(raw) }))

// --- hằng câu (client.ts) ---
kichBan = []
const thieuToken = await loiTsAsync(() => C.getToken(cauHinhTs({ tokenPath: "  " })))
const thieuDay = await C.publishInvoice(cauHinhTs({ publishPath: "" }), [])
out.hang_so = [
	{ ten: "CAU_THIEU_DUONG_TOKEN", mong: thieuToken.loi },
	{ ten: "CAU_THIEU_DUONG_DAY", mong: thieuDay.error },
	{ ten: "CAU_KHONG_CO_DU_LIEU", mong: out.hieu_phan_hoi_day.find((c) => c.ten === "KV-10 success + data rỗng").mong.error },
]

// --- §5.3 bước 4 dong_snapshot ---
function snap(raw) {
	const ts = T.toSnapshotRow("org", raw)
	const ca = { vao: raw }
	if (!ts) {
		ca.mong = null
		return ca
	}
	const mong = {
		ref_id: ts.ref_id, ky_hieu: ts.inv_series, so_hddt: ts.inv_no, ngay_phat_hanh: ts.inv_date, ma_tra_cuu: ts.transaction_id,
		ma_cqt: ts.invoice_code, mst_nguoi_mua: ts.buyer_tax_code, nguoi_mua: ts.buyer_name, tong_tien: ts.total_amount ?? 0,
		co_tong_tien: ts.total_amount != null ? 1 : 0, tien_truoc_thue: ts.amount_before_vat ?? 0, tien_thue: ts.vat_amount ?? 0,
		publish_status: ts.publish_status == null ? "" : String(ts.publish_status),
		einvoice_status: ts.einvoice_status == null ? "" : String(ts.einvoice_status),
		quan_he: ts.relation, da_huy: ts.is_deleted ? 1 : 0, ref_id_goc: ts.org_ref_id,
		so_hddt_chuan: ts.inv_no == null ? null : N.normalizeInvNo(ts.inv_no), ky_hieu_chuan: T.strictSeries(ts.inv_series),
	}
	if (ts.inv_date && !ngayThat(ts.inv_date)) {
		mong.ngay_phat_hanh = null
		const { raw: _bo, pulled_at: _bo2, ...con } = ts
		ca.lech = { ma: "H26", ly_do: "H26: ngày không có thật — nppsale cả lô upsert hỏng; bản Python ghi ngay_phat_hanh NULL.", ts: con }
	}
	ca.mong = mong
	return ca
}
out.dong_snapshot = [
	{ RefID: " rid-1 ", InvSeries: "1C26TAA", InvNo: "00000123", InvDate: "2026-11-02T00:00:00", TransactionID: "TXA", InvoiceCode: "M1",
		AccountObjectTaxCode: " 0301175691-044 ", AccountObjectName: "Tạp hoá A", TotalAmount: 212600, TotalAmountWithoutVAT: 0,
		TotalVATAmount: 0, PublishStatus: 3, EInvoiceStatus: 1, OrgRefID: null, IsInvoiceDeleted: false },
	{ InvNo: "1" }, { RefID: 123 }, { RefID: "  " },
	{ RefID: "r2", InvNo: PH, PublishStatus: 0 },
	{ RefID: "r3", InvNo: "00000124", PublishStatus: 3.5, EInvoiceStatus: 7, InvDate: "2026-02-30", TotalAmount: 1000 },
	{ RefID: "r4", TotalAmountWithoutVAT: 195000, TotalVATAmount: 17600 },
	{ RefID: "r5", IsInvoiceDeleted: true, OrgRefID: "goc", InvSeries: " 1c26 taa ", InvNo: "000" },
	{ RefID: "r6", AccountObjectName: 123, TotalAmount: "212600", EInvoiceStatus: "abc", InvDate: "2026-04-31T00:00:00" },
	[],
].map(snap)

// --- §2.9 khớp bốn tầng ---
const SO = [
	{ id: "b1", misa_ref_id: "rid-1", misa_lookup_code: "TXA", misa_inv_series: "1C26TAA", misa_inv_no: "00000123", mst: "0301175691-044",
		ngay: "2026-11-02", tong_tien: 212600 },
	{ id: "b2", misa_ref_id: null, misa_lookup_code: null, misa_inv_series: "2C26TAA", misa_inv_no: "00000500", mst: null, ngay: "2026-11-02",
		tong_tien: 1000 },
	{ id: "b3", mst: "0301175691-044", ngay: "2026-11-10", tong_tien: 55000 },
	{ id: "b4", mst: "0302222222-001", ngay: "2026-11-11", tong_tien: 66000 },
	{ id: "b5", mst: "0303333333", ngay: "2026-11-12", tong_tien: 70000 },
	{ id: "b6", mst: "0303333333", ngay: "2026-11-12", tong_tien: 70000 },
	{ id: "b7", misa_ref_id: "rid-7", misa_inv_series: "1C26TAA", misa_inv_no: "00000130", ngay: "2026-11-13", tong_tien: 108000 },
	{ id: "b8", misa_ref_id: "rid-1", misa_lookup_code: "  TXA  ", ngay: null, tong_tien: 1 },
	{ id: "b9", misa_ref_id: "  ", ngay: "2026-11-20", tong_tien: null, mst: "0309999999" },
	{ id: "b10", mst: " 0304 444444 ", ngay: "2026-11-14", tong_tien: -2500.5 },
	{ id: "b11", misa_inv_series: "1C26\ufeffTAB", misa_inv_no: "77" },
	{ id: "b12", misa_inv_series: "2C26TAA", misa_inv_no: "123" },
	{ id: "b13", misa_inv_series: "", misa_inv_no: "999", mst: "0305555555", ngay: "2026-11-15", tong_tien: 0 },
]
const bookTs = (r) => ({ id: r.id, misa_ref_id: KHONG_CO(r.misa_ref_id), misa_lookup_code: KHONG_CO(r.misa_lookup_code),
	misa_inv_series: KHONG_CO(r.misa_inv_series), misa_inv_no: KHONG_CO(r.misa_inv_no), customer_tax_code: KHONG_CO(r.mst),
	match_date: KHONG_CO(r.ngay), total: KHONG_CO(r.tong_tien) })
const idx = R.buildIndex(SO.map(bookTs))
const theoId = new Map(SO.map((r) => [r.id, bookTs(r)]))
out.khop_so = SO
out.khop_chi_muc = { by_ref: [...idx.byRef], by_txn: [...idx.byTxn], by_no: [...idx.byNo], by_loose: [...idx.byLooseNo],
	by_base: [...idx.byTaxDateAmount], by_full: [...idx.byFullTaxDateAmount] }
const sn = (ten, o) => ({ ten, s: { ref_id: "x", ma_tra_cuu: null, ky_hieu: null, so_hddt: null, ngay_phat_hanh: null, mst_nguoi_mua: null,
	tong_tien: null, quan_he: "new", da_huy: 0, ...o } })
out.khop = [
	sn("KV-11 RefID", { ref_id: "rid-1", tong_tien: 212600 }),
	sn("KV-11 mã tra cứu", { ref_id: "m1", ma_tra_cuu: "TXA", tong_tien: 212600 }),
	sn("KV-11 ký hiệu + số, lệch tiền", { ref_id: "m0", ky_hieu: " 1c26taa", so_hddt: "123", tong_tien: 212000 }),
	sn("KV-11 bỏ chữ số đầu, 1 ứng viên", { ref_id: "m2", ky_hieu: "C26TAA", so_hddt: "500", tong_tien: 1000 }),
	sn("bỏ chữ số đầu, 2 ứng viên → không", { ref_id: "m3", ky_hieu: "C26TAA", so_hddt: "123" }),
	sn("KV-11 MST đủ + ngày + tiền", { ref_id: "m4", ngay_phat_hanh: "2026-11-10T00:00:00", mst_nguoi_mua: "0301175691-044", tong_tien: 55000 }),
	sn("KV-11 MST gốc, tiền âm", { ref_id: "m5", ngay_phat_hanh: "2026-11-11", mst_nguoi_mua: "0302222222", tong_tien: -66000 }),
	sn("KV-11 MST đủ 2 ứng viên → dừng", { ref_id: "m6", ngay_phat_hanh: "2026-11-12", mst_nguoi_mua: "0303333333", tong_tien: 70000 }),
	sn("KV-11 ngoài sổ", { ref_id: "m7", ky_hieu: "1C26TAA", so_hddt: "99999", tong_tien: 5 }),
	sn("KV-11 đã huỷ", { ref_id: "rid-1", da_huy: 1, tong_tien: 1 }),
	sn("KV-11 điều chỉnh", { ref_id: "rid-7", quan_he: "adjustment", tong_tien: -20000 }),
	sn("KV-11 bị thay thế", { ref_id: "rid-7", quan_he: "replaced", tong_tien: 108000 }),
	sn("KV-11 lệch tiền âm", { ref_id: "rid-7", tong_tien: -108002 }),
	sn("KV-11 lệch 1 đ", { ref_id: "rid-7", tong_tien: 108001 }),
	sn("MISA không tổng tiền", { ref_id: "rid-7", tong_tien: null }),
	sn("BOM giữa ký hiệu → khớp chặt", { ref_id: "m8", ky_hieu: "1C26\ufeffTAA", so_hddt: "123" }),
	sn("\\x1c giữa ký hiệu → không", { ref_id: "m9", ky_hieu: "1C26\x1cTAA", so_hddt: "123" }),
	sn("RefID chỉ khoảng trắng → khoá rỗng", { ref_id: "   " }),
	sn("mã tra cứu có khoảng trắng", { ref_id: "m10", ma_tra_cuu: "  TXA  " }),
	sn("tiền làm tròn trị tuyệt đối", { ref_id: "m11", ngay_phat_hanh: "2026-11-14", mst_nguoi_mua: "0304444444", tong_tien: 2500.6 }),
	sn("tầng 4 thiếu ngày", { ref_id: "m12", mst_nguoi_mua: "0301175691-044", tong_tien: 55000 }),
	sn("số rỗng bỏ tầng 3", { ref_id: "m13", ky_hieu: "1C26TAA", so_hddt: "" }),
	sn("ký hiệu sổ có BOM", { ref_id: "m14", ky_hieu: "1C26TAB", so_hddt: "0077" }),
	sn("sổ ký hiệu rỗng không vào chỉ mục số, tầng 4 tiền 0", { ref_id: "m15", ky_hieu: "C", so_hddt: "999", ngay_phat_hanh: "2026-11-15",
		mst_nguoi_mua: "0305555555", tong_tien: 0 }),
	sn("ref_id rỗng", { ref_id: "", ma_tra_cuu: "TXA" }),
].map(({ ten, s }) => {
	const snTs = { ref_id: s.ref_id, transaction_id: s.ma_tra_cuu, inv_series: s.ky_hieu, inv_no: s.so_hddt, inv_date: s.ngay_phat_hanh,
		buyer_tax_code: s.mst_nguoi_mua, total_amount: s.tong_tien }
	const hit = R.matchOne(snTs, idx)
	const kq = R.decideStatus({ relation: s.quan_he, is_deleted: !!s.da_huy, total_amount: s.tong_tien }, hit, theoId)
	return { ten, vao: s, mong: { hit: hit && [hit.invoiceId, hit.method, hit.confidence, hit.note], ket_qua: [kq.match_status, kq.match_note] } }
})

// ----------------------------------------------------------------------------------------------------------------------------------
// 6. Ghi
// ----------------------------------------------------------------------------------------------------------------------------------
out.nguon = {
	nppsale: GHIM.ref, luc: LUC, uuid: uuidThu(1) + " …", tep: NGUON_DA_DOC,
	ghi_chu: "Sinh bằng tools/vang_hddt.mjs từ chính mã TS (bản chép chỉ khác dòng import + hàm không export cắt nguyên văn). " +
		"Ca có `lech` là chỗ bản Python chủ ý khác TS (đặc tả §0.3 H#); `lech.ts` = kết quả TS. " +
		"dong_snapshot: so_hddt_chuan / ky_hieu_chuan theo H21 (= chuan_so / ky_hieu_chat của tầng khớp, không phải cột GENERATED của Postgres).",
}
const THU_TU = ["nguon", "tron", "so_js", "tien_vn", "js_khoa", "js_cat", "js_json", "chuoi", "so", "quan_he", "chuan_hoa", "doc_ban_ghi",
	"suy_trang_thai", "so_tien", "ap_dung", "dong_hang", "dong_tong_hop", "dung_payload", "url_tra_cuu", "ghi_chu_bi_thay_the", "canh_bao_noi_tay", "loi_misa",
	"la_loi_xac_thuc", "hieu_phan_hoi_day", "doc_phan_hoi_token", "doc_phan_hoi_lay_hd", "doc_phan_hoi_ds", "doc_phan_hoi_mau",
	"tach_dinh_danh", "hang_so", "dong_snapshot", "khop_so", "khop_chi_muc", "khop"]
if (THU_TU.length !== Object.keys(out).length) throw new Error("THU_TU thiếu mục: " + Object.keys(out).filter((k) => !THU_TU.includes(k)))
const dong = ["{"]
THU_TU.forEach((k, i) => {
	const v = out[k]
	const phay = i === THU_TU.length - 1 ? "" : ","
	if (Array.isArray(v)) {
		dong.push(`${J(k)}: [`)
		v.forEach((x, j) => dong.push(" " + J(x) + (j === v.length - 1 ? "" : ",")))
		dong.push("]" + phay)
	} else dong.push(`${J(k)}: ${J(v)}${phay}`)
})
dong.push("}")
const ra = dong.join("\n") + "\n"
if (process.env.VANG_HDDT_GIU_TAM) console.error(`Giữ thư mục tạm (VANG_HDDT_GIU_TAM): ${TAM}`)
else fs.rmSync(TAM, { recursive: true, force: true })
if (IN_RA) process.stdout.write(ra)
else {
	fs.writeFileSync(DICH, ra)
	const dem = THU_TU.filter((k) => Array.isArray(out[k])).reduce((s, k) => s + out[k].length, 0)
	console.log(`Đã ghi ${path.relative(GOC, DICH)}: ${dem} ca, ${out.ap_dung.filter((c) => c.lech).length + out.doc_phan_hoi_token
		.filter((c) => c.lech).length + out.dong_snapshot.filter((c) => c.lech).length} ca khai lệch.`)
}
