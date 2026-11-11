/**
 * Bộ dựng truy vấn cùng giao diện postgrest-js — gửi về cổng trên Frappe (nppsale/portal/rest.py):
 *   `.from(bang)…`  → `/rest/v1/<bảng>` (yêu cầu JSON khớp nppsale/cong/sql.py)
 *   `.rpc(ten, …)…` → `/rest/v1/rpc/<hàm>`; lọc / sắp / phân trang / chọn cột / đếm đặt SAU lời gọi hàm (như PostgREST bọc kết quả
 *                     hàm trả tập) đi kèm tham số `sau` — máy chủ áp lên kết quả.
 * Kiểu dữ liệu theo postgrest-js khi không khai sơ đồ: `data` là `any[]`, `.single()` / `.maybeSingle()` là một dòng.
 * Phép mã nppsale không dùng thì ném lỗi ngay (lộ ra khi chạy thử, không lặng lẽ sai).
 */
import type { PostgrestError, PostgrestResponse, Transport, YeuCau } from "./kieu"

type DemKieu = "exact" | "planned" | "estimated"
type BangNgoai = { foreignTable?: string; referencedTable?: string }
type Dong<T> = T extends Array<infer U> ? U : T

/** Phần chung của truy vấn bảng và lời gọi hàm: lọc, sắp, phân trang, một dòng, huỷ, ném lỗi. */
export abstract class BoLoc<T = any[]> implements PromiseLike<PostgrestResponse<T>> {
  protected loc: Array<Record<string, unknown>> = []
  protected thuTu: Array<Record<string, unknown>> = []
  protected khoang?: [number, number]
  protected gioiHan?: number
  protected mot: "one" | "maybe" | null = null
  protected tinHieu?: AbortSignal
  protected nemLoi = false

  constructor(protected t: Transport) {}

  private them(op: string, cot: string, gt: unknown): this {
    this.loc.push({ op, cot, gt })
    return this
  }
  eq(cot: string, gt: unknown): this {
    return this.them("eq", cot, gt)
  }
  neq(cot: string, gt: unknown): this {
    return this.them("neq", cot, gt)
  }
  gt(cot: string, gt: unknown): this {
    return this.them("gt", cot, gt)
  }
  gte(cot: string, gt: unknown): this {
    return this.them("gte", cot, gt)
  }
  lt(cot: string, gt: unknown): this {
    return this.them("lt", cot, gt)
  }
  lte(cot: string, gt: unknown): this {
    return this.them("lte", cot, gt)
  }
  like(cot: string, gt: string): this {
    return this.them("like", cot, gt)
  }
  ilike(cot: string, gt: string): this {
    return this.them("ilike", cot, gt)
  }
  is(cot: string, gt: null | boolean): this {
    return this.them("is", cot, gt)
  }
  in(cot: string, ds: readonly unknown[]): this {
    return this.them("in", cot, Array.from(ds))
  }
  contains(cot: string, gt: unknown): this {
    return this.them("cs", cot, gt)
  }
  containedBy(cot: string, gt: unknown): this {
    return this.them("cd", cot, gt)
  }
  overlaps(cot: string, gt: unknown): this {
    return this.them("ov", cot, gt)
  }
  not(cot: string, toanTu: string, gt: unknown): this {
    this.loc.push({ op: "not", cot, op_con: toanTu, gt })
    return this
  }
  or(bieuThuc: string, opts?: BangNgoai): this {
    this.loc.push({ op: "or", bieu_thuc: bieuThuc, bang_ngoai: opts?.referencedTable ?? opts?.foreignTable ?? null })
    return this
  }
  filter(cot: string, toanTu: string, gt: unknown): this {
    this.loc.push({ op: "filter", cot, toan_tu: toanTu, gt })
    return this
  }
  match(doi: Record<string, unknown>): this {
    this.loc.push({ op: "match", gt: doi })
    return this
  }
  textSearch(_cot: string, _q: string, _o?: unknown): this {
    throw new Error("textSearch chưa hỗ trợ ở cổng nppsale")
  }
  order(cot: string, opts?: { ascending?: boolean; nullsFirst?: boolean } & BangNgoai): this {
    this.thuTu.push({
      cot,
      tang: opts?.ascending ?? true,
      null_dau: opts?.nullsFirst ?? null,
      bang_ngoai: opts?.referencedTable ?? opts?.foreignTable ?? null,
    })
    return this
  }
  range(tu: number, den: number, opts?: BangNgoai): this {
    if (opts?.foreignTable || opts?.referencedTable) throw new Error("range trên bảng lồng chưa hỗ trợ ở cổng nppsale")
    this.khoang = [tu, den]
    return this
  }
  limit(n: number, opts?: BangNgoai): this {
    if (opts?.foreignTable || opts?.referencedTable) throw new Error("limit trên bảng lồng chưa hỗ trợ ở cổng nppsale")
    this.gioiHan = n
    return this
  }
  single<R = Dong<T>>(): BoLoc<R> {
    this.mot = "one"
    return this as unknown as BoLoc<R>
  }
  maybeSingle<R = Dong<T>>(): BoLoc<R | null> {
    this.mot = "maybe"
    return this as unknown as BoLoc<R | null>
  }
  abortSignal(s: AbortSignal): this {
    this.tinHieu = s
    return this
  }
  throwOnError(): this {
    this.nemLoi = true
    return this
  }
  returns<U>(): BoLoc<U> {
    return this as unknown as BoLoc<U>
  }
  csv(): this {
    throw new Error("csv chưa hỗ trợ ở cổng nppsale")
  }

  protected abstract gui(): Promise<PostgrestResponse<any>>

  async thucHien(): Promise<PostgrestResponse<T>> {
    const kq = await this.gui()
    if (this.nemLoi && kq.error) throw Object.assign(new Error(kq.error.message), kq.error)
    return kq as PostgrestResponse<T>
  }

  then<A = PostgrestResponse<T>, B = never>(
    onOk?: ((v: PostgrestResponse<T>) => A | PromiseLike<A>) | null,
    onErr?: ((e: any) => B | PromiseLike<B>) | null
  ): Promise<A | B> {
    return this.thucHien().then(onOk, onErr)
  }
}

/** `.from(bang)` */
export class QueryBuilder<T = any[]> extends BoLoc<T> {
  private hanhDong: YeuCau["hanh_dong"] = "select"
  private chon?: string | null
  private dem?: DemKieu | null
  private chiDem = false
  private giaTri?: unknown
  private xungDot?: string
  private boQuaTrung = false

  constructor(t: Transport, private bang: string) {
    super(t)
  }

  select<R = any[]>(cot = "*", opts?: { count?: DemKieu; head?: boolean }): QueryBuilder<R> {
    this.chon = cot
    if (opts?.count) this.dem = opts.count
    if (opts?.head) this.chiDem = true
    return this as unknown as QueryBuilder<R>
  }
  insert(giaTri: unknown, opts?: { count?: DemKieu; defaultToNull?: boolean }): QueryBuilder<null> {
    this.hanhDong = "insert"
    this.giaTri = giaTri
    if (opts?.count) this.dem = opts.count
    return this as unknown as QueryBuilder<null>
  }
  upsert(giaTri: unknown, opts?: { onConflict?: string; ignoreDuplicates?: boolean; count?: DemKieu; defaultToNull?: boolean }): QueryBuilder<null> {
    this.hanhDong = "upsert"
    this.giaTri = giaTri
    if (opts?.onConflict) this.xungDot = opts.onConflict
    if (opts?.ignoreDuplicates) this.boQuaTrung = true
    if (opts?.count) this.dem = opts.count
    return this as unknown as QueryBuilder<null>
  }
  update(giaTri: unknown, opts?: { count?: DemKieu }): QueryBuilder<null> {
    this.hanhDong = "update"
    this.giaTri = giaTri
    if (opts?.count) this.dem = opts.count
    return this as unknown as QueryBuilder<null>
  }
  delete(opts?: { count?: DemKieu }): QueryBuilder<null> {
    this.hanhDong = "delete"
    if (opts?.count) this.dem = opts.count
    return this as unknown as QueryBuilder<null>
  }

  /** Yêu cầu gửi đi (để test so được). */
  yeuCau(): YeuCau {
    const doc = this.hanhDong === "select"
    const yc: YeuCau = { bang: this.bang, hanh_dong: this.hanhDong, loc: this.loc, thu_tu: this.thuTu }
    if (this.chon !== undefined && this.chon !== null) yc.select = this.chon
    else if (doc) yc.select = "*"
    if (this.khoang) yc.range = this.khoang
    if (this.gioiHan !== undefined) yc.limit = this.gioiHan
    if (this.dem) yc.count = this.dem
    if (this.chiDem) yc.head = true
    if (this.mot) yc.mot = this.mot
    if (!doc) yc.gia_tri = this.giaTri
    if (this.xungDot) yc.on_conflict = this.xungDot
    if (this.boQuaTrung) yc.bo_qua_trung = true
    return yc
  }

  protected gui() {
    const yc = this.yeuCau()
    return this.t.goi(`/rest/v1/${encodeURIComponent(this.bang)}`, yc, { doc: yc.hanh_dong === "select", signal: this.tinHieu })
  }
}

/** `.rpc(ten, thamSo, { get, count, head })` — hàm cùng tên ở nppsale.rpc. */
export class RpcBuilder<T = any> extends BoLoc<T> {
  private chon?: string

  constructor(
    t: Transport,
    private ten: string,
    private thamSo: object | undefined,
    private doc: boolean,
    private dem?: DemKieu,
    private chiDem = false
  ) {
    super(t)
  }

  select<R = any[]>(cot = "*"): RpcBuilder<R> {
    this.chon = cot
    return this as unknown as RpcBuilder<R>
  }

  /** Phần áp lên kết quả hàm (rỗng = không gửi). */
  sau(): Record<string, unknown> | null {
    const s: Record<string, unknown> = {}
    if (this.chon && this.chon !== "*") s.select = this.chon
    if (this.loc.length) s.loc = this.loc
    if (this.thuTu.length) s.thu_tu = this.thuTu
    if (this.khoang) s.range = this.khoang
    if (this.gioiHan !== undefined) s.limit = this.gioiHan
    if (this.dem) s.count = this.dem
    if (this.chiDem) s.head = true
    return Object.keys(s).length ? s : null
  }

  protected async gui() {
    const sau = this.sau()
    const duong = `/rest/v1/rpc/${encodeURIComponent(this.ten)}` + (sau ? `?sau=${encodeURIComponent(JSON.stringify(sau))}` : "")
    const kq = await this.t.goi(duong, this.thamSo ?? {}, { doc: this.doc, signal: this.tinHieu })
    return motDong(kq, this.mot)
  }
}

/** `.single()` / `.maybeSingle()` trên kết quả dạng mảng — cùng mã lỗi PGRST116 như PostgREST. */
export function motDong(kq: PostgrestResponse<any>, mot: "one" | "maybe" | null): PostgrestResponse<any> {
  if (kq.error || !mot || !Array.isArray(kq.data)) return kq
  const ds = kq.data as unknown[]
  if (ds.length === 1) return { ...kq, data: ds[0] }
  if (ds.length === 0 && mot === "maybe") return { ...kq, data: null }
  const error: PostgrestError = {
    message: "JSON object requested, multiple (or no) rows returned",
    code: "PGRST116",
    details: `The result contains ${ds.length} rows`,
    hint: "",
  }
  return { ...kq, data: null, error, status: 406 }
}
