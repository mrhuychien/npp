/**
 * Bộ dựng truy vấn cùng giao diện postgrest-js (`.from(bang).select().eq()...`) — gửi về cổng `/rest/v1/<bảng>` trên Frappe.
 * Chỉ khai những phép mã nppsale dùng thật (đo 11/11/2026); phép chưa hỗ trợ ném lỗi ngay để lộ ra khi chạy thử.
 */
import type { PostgrestResponse, Transport, YeuCau } from "./kieu"

type DemKieu = "exact" | "planned" | "estimated"

export class QueryBuilder<T = any> implements PromiseLike<PostgrestResponse<T>> {
  protected yc: YeuCau
  protected tinHieu?: AbortSignal
  protected nemLoi = false

  constructor(protected t: Transport, bang: string) {
    this.yc = { bang, hanh_dong: "select", loc: [], thu_tu: [] }
  }

  select(cot = "*", opts?: { count?: DemKieu; head?: boolean }): this {
    this.yc.select = cot
    if (opts?.count) this.yc.count = opts.count
    if (opts?.head) this.yc.head = true
    return this
  }
  insert(giaTri: unknown, opts?: { count?: DemKieu; defaultToNull?: boolean }): this {
    this.yc.hanh_dong = "insert"
    this.yc.gia_tri = giaTri
    if (opts?.count) this.yc.count = opts.count
    return this
  }
  upsert(giaTri: unknown, opts?: { onConflict?: string; ignoreDuplicates?: boolean; count?: DemKieu }): this {
    this.yc.hanh_dong = "upsert"
    this.yc.gia_tri = giaTri
    if (opts?.onConflict) this.yc.on_conflict = opts.onConflict
    if (opts?.ignoreDuplicates) this.yc.bo_qua_trung = true
    if (opts?.count) this.yc.count = opts.count
    return this
  }
  update(giaTri: unknown, opts?: { count?: DemKieu }): this {
    this.yc.hanh_dong = "update"
    this.yc.gia_tri = giaTri
    if (opts?.count) this.yc.count = opts.count
    return this
  }
  delete(opts?: { count?: DemKieu }): this {
    this.yc.hanh_dong = "delete"
    if (opts?.count) this.yc.count = opts.count
    return this
  }

  private loc(op: string, cot: string, gt: unknown): this {
    this.yc.loc.push({ op, cot, gt })
    return this
  }
  eq(cot: string, gt: unknown) { return this.loc("eq", cot, gt) }
  neq(cot: string, gt: unknown) { return this.loc("neq", cot, gt) }
  gt(cot: string, gt: unknown) { return this.loc("gt", cot, gt) }
  gte(cot: string, gt: unknown) { return this.loc("gte", cot, gt) }
  lt(cot: string, gt: unknown) { return this.loc("lt", cot, gt) }
  lte(cot: string, gt: unknown) { return this.loc("lte", cot, gt) }
  like(cot: string, gt: string) { return this.loc("like", cot, gt) }
  ilike(cot: string, gt: string) { return this.loc("ilike", cot, gt) }
  is(cot: string, gt: null | boolean) { return this.loc("is", cot, gt) }
  in(cot: string, ds: readonly unknown[]) { return this.loc("in", cot, Array.from(ds)) }
  contains(cot: string, gt: unknown) { return this.loc("cs", cot, gt) }
  containedBy(cot: string, gt: unknown) { return this.loc("cd", cot, gt) }
  overlaps(cot: string, gt: unknown) { return this.loc("ov", cot, gt) }
  not(cot: string, toanTu: string, gt: unknown): this {
    this.yc.loc.push({ op: "not", cot, op_con: toanTu, gt })
    return this
  }
  or(bieuThuc: string, opts?: { foreignTable?: string; referencedTable?: string }): this {
    this.yc.loc.push({ op: "or", bieu_thuc: bieuThuc, bang_ngoai: opts?.referencedTable ?? opts?.foreignTable ?? null })
    return this
  }
  filter(cot: string, toanTu: string, gt: unknown): this {
    this.yc.loc.push({ op: "filter", cot, toan_tu: toanTu, gt })
    return this
  }
  match(doi: Record<string, unknown>): this {
    this.yc.loc.push({ op: "match", gt: doi })
    return this
  }
  textSearch(): this {
    throw new Error("textSearch chưa hỗ trợ ở cổng nppsale")
  }
  order(cot: string, opts?: { ascending?: boolean; nullsFirst?: boolean; foreignTable?: string; referencedTable?: string }): this {
    this.yc.thu_tu.push({
      cot,
      tang: opts?.ascending ?? true,
      null_dau: opts?.nullsFirst ?? null,
      bang_ngoai: opts?.referencedTable ?? opts?.foreignTable ?? null,
    })
    return this
  }
  range(tu: number, den: number, opts?: { foreignTable?: string; referencedTable?: string }): this {
    if (opts?.foreignTable || opts?.referencedTable) throw new Error("range trên bảng lồng chưa hỗ trợ ở cổng nppsale")
    this.yc.range = [tu, den]
    return this
  }
  limit(n: number, opts?: { foreignTable?: string; referencedTable?: string }): this {
    if (opts?.foreignTable || opts?.referencedTable) throw new Error("limit trên bảng lồng chưa hỗ trợ ở cổng nppsale")
    this.yc.limit = n
    return this
  }
  single(): this {
    this.yc.mot = "one"
    return this
  }
  maybeSingle(): this {
    this.yc.mot = "maybe"
    return this
  }
  abortSignal(s: AbortSignal): this {
    this.tinHieu = s
    return this
  }
  throwOnError(): this {
    this.nemLoi = true
    return this
  }
  returns<U>(): QueryBuilder<U> {
    return this as unknown as QueryBuilder<U>
  }
  csv(): this {
    throw new Error("csv chưa hỗ trợ ở cổng nppsale")
  }

  async thucHien(): Promise<PostgrestResponse<T>> {
    const yc: YeuCau = { ...this.yc }
    const doc = yc.hanh_dong === "select"
    if (doc && (yc.select === undefined || yc.select === null)) yc.select = "*"
    const kq = (await this.t.goi(`/rest/v1/${encodeURIComponent(yc.bang)}`, yc, { doc, signal: this.tinHieu })) as PostgrestResponse<T>
    if (this.nemLoi && kq.error) throw Object.assign(new Error(kq.error.message), kq.error)
    return kq
  }

  then<A = PostgrestResponse<T>, B = never>(
    onOk?: ((v: PostgrestResponse<T>) => A | PromiseLike<A>) | null,
    onErr?: ((e: any) => B | PromiseLike<B>) | null
  ): Promise<A | B> {
    return this.thucHien().then(onOk, onErr)
  }
}

/** `.rpc(ten, thamSo, { get })` — hàm cùng tên ở nppsale.rpc. */
export class RpcBuilder<T = any> implements PromiseLike<PostgrestResponse<T>> {
  private tinHieu?: AbortSignal
  private nemLoi = false
  private mot: "one" | "maybe" | null = null

  constructor(private t: Transport, private ten: string, private thamSo: Record<string, unknown> | undefined, private doc: boolean) {}

  abortSignal(s: AbortSignal): this {
    this.tinHieu = s
    return this
  }
  throwOnError(): this {
    this.nemLoi = true
    return this
  }
  single(): this {
    this.mot = "one"
    return this
  }
  maybeSingle(): this {
    this.mot = "maybe"
    return this
  }
  select(): this {
    return this
  }
  returns<U>(): RpcBuilder<U> {
    return this as unknown as RpcBuilder<U>
  }

  async thucHien(): Promise<PostgrestResponse<T>> {
    const kq = (await this.t.goi(`/rest/v1/rpc/${encodeURIComponent(this.ten)}`, this.thamSo ?? {}, { doc: this.doc, signal: this.tinHieu })) as PostgrestResponse<any>
    if (!kq.error && this.mot && Array.isArray(kq.data)) {
      const ds = kq.data as unknown[]
      if (ds.length === 1) kq.data = ds[0]
      else if (ds.length === 0 && this.mot === "maybe") kq.data = null
      else {
        kq.data = null
        kq.error = { message: "JSON object requested, multiple (or no) rows returned", code: "PGRST116", details: `The result contains ${ds.length} rows`, hint: null }
      }
    }
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
