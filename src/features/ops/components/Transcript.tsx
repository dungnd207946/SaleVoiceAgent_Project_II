/**
 * Transcript một phiên (spec §5.2, §5.3).
 *
 * PHÒNG THỦ LÀ YÊU CẦU, KHÔNG PHẢI SỰ CẨN THẬN THỪA: `conversation_messages` do
 * một hệ khác ghi và `0915` cố ý KHÔNG có CHECK trên `role`. Một lượt méo chỉ
 * được làm hỏng chính nó — các lượt còn lại vẫn phải hiện.
 *
 * HÌNH DẠNG THẬT của một cuộc gọi tool (chốt 07/08, đọc dữ liệu thật của team
 * agent — KHÔNG phải suy đoán): nó KHÔNG nằm trên một hàng. Nó là HAI hàng:
 *
 *   1. Hàng `role: "assistant"`, `content: ""`, `meta.tool_calls: [{id, type:
 *      "function", function: {name, arguments}}]` — đây là YÊU CẦU gọi tool,
 *      KHÔNG phải một lời nói rỗng của agent. Không được render bong bóng
 *      trống cho hàng này.
 *   2. Hàng `role: "tool"`, `content` là CHUỖI JSON kết quả (có thể rất dài),
 *      `meta: {name, tool_call_id}` khớp với `id` ở hàng (1). Không được
 *      render nguyên văn chuỗi JSON đó như một lời hội thoại.
 *
 * Hai hàng đó ghép lại thành MỘT khối `MotTheCongCu` — đóng theo mặc định,
 * bấm để xem tham số/kết quả. Ghép bằng `tool_call_id`, KHÔNG bằng vị trí kề
 * nhau: dữ liệu lệch (lịch sử bị cắt, hai luồng chèn lẫn) vẫn phải ra đúng.
 */
import { useEffect, useRef, useState } from 'react'
import { gioPhut } from '@/lib/dinhDang'
import type { Luot } from '../api'
import { docNhanKichBan } from '../nhanKichBan'
import { TheNutKichBan } from './TheNutKichBan'

/** `user` bên phải, `assistant` bên trái. Mọi giá trị khác ⇒ dòng hệ thống. */
function ben(role: string): 'khach' | 'agent' | 'he_thong' {
  if (role === 'user') return 'khach'
  if (role === 'assistant') return 'agent'
  return 'he_thong'
}

function gioCua(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '' // KHÔNG in 'Invalid Date' lên màn
  return gioPhut(d)
}

interface CuocGoiTool {
  readonly id: string
  readonly ten: string
  /** Chuỗi JSON nguyên văn của `arguments`. `''` nếu không có. */
  readonly thamSo: string
}

/** Đọc MỘT phần tử của `meta.tool_calls`. `null` nếu thiếu `id` hoặc tên hàm —
 * một mục không tên thì không có gì để hiện, bỏ qua đúng mục đó, không vỡ cả
 * hàng (cùng lý lẽ giữ nguyên từ trước). */
function docCuocGoi(item: unknown): CuocGoiTool | null {
  if (!item || typeof item !== 'object') return null
  const o = item as Record<string, unknown>
  const fn = o.function
  if (typeof o.id !== 'string' || !o.id || !fn || typeof fn !== 'object') return null
  const ten = (fn as Record<string, unknown>).name
  if (typeof ten !== 'string' || !ten) return null
  const thamSoRaw = (fn as Record<string, unknown>).arguments
  return { id: o.id, ten, thamSo: typeof thamSoRaw === 'string' ? thamSoRaw : '' }
}

/** `meta` là jsonb do hệ khác ghi — có thể là bất cứ gì, kể cả không phải
 * object (xem test "lượt có meta méo"). Mọi bước đọc ở đây phải tự kiểm kiểu,
 * không tin vào kiểu TypeScript khai ở `api.ts`. */
function layDsCuocGoi(meta: unknown): CuocGoiTool[] {
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return []
  const tc = (meta as Record<string, unknown>).tool_calls
  if (!Array.isArray(tc)) return []
  const ra: CuocGoiTool[] = []
  for (const item of tc) {
    const cg = docCuocGoi(item)
    if (cg) ra.push(cg)
  }
  return ra
}

function layToolCallId(meta: unknown): string | null {
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return null
  const id = (meta as Record<string, unknown>).tool_call_id
  return typeof id === 'string' && id ? id : null
}

function layTenTool(meta: unknown): string | null {
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return null
  const ten = (meta as Record<string, unknown>).name
  return typeof ten === 'string' && ten ? ten : null
}

/** Parse-và-canh-dòng JSON; chuỗi không parse được thì hiện nguyên văn — kết
 * quả tool là dữ liệu của hệ khác, không phải hợp đồng đã ký. */
function demDep(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

/** `''`/`'{}'`/`'[]'` không đáng một khối riêng — coi như "không có tham số". */
function thamSoDeHien(raw: string): string {
  const s = raw.trim()
  if (s === '' || s === '{}' || s === '[]') return ''
  return demDep(raw)
}

/**
 * Tham số ở dạng MỘT DÒNG, để hiện SẴN lúc thẻ còn đóng.
 *
 * Khác `demDep`: không xuống dòng, không cách sau dấu hai chấm — `JSON.stringify`
 * trần. Đây là bản người ta liếc qua, không phải bản đọc kỹ; bản đọc kỹ nằm
 * trong khối «Tham số» sau khi bấm mở.
 *
 * VÌ SAO PHẢI HIỆN SẴN: thẻ đóng chỉ có tên hàm, nên muốn biết agent đã hỏi
 * `search_units` với điều kiện gì thì phải bấm từng thẻ một — mà đa số thẻ mở ra
 * chỉ để đọc đúng một dòng này. Chuỗi không parse được thì hiện nguyên văn: kết
 * quả tool là dữ liệu của hệ khác, không phải hợp đồng đã ký.
 */
function thamSoMotDong(raw: string): string {
  const s = raw.trim()
  if (s === '' || s === '{}' || s === '[]') return ''
  try {
    return JSON.stringify(JSON.parse(s))
  } catch {
    return s
  }
}

function KhoiDuLieuTool({ nhan, noiDung }: { nhan: string; noiDung: string }) {
  return (
    <div>
      <p className="mb-1 text-nhan font-semibold uppercase tracking-wider text-muted-3">{nhan}</p>
      <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded border border-border bg-surface p-2 font-mono text-[11.5px] text-muted">
        {noiDung}
      </pre>
    </div>
  )
}

/**
 * Một cuộc gọi tool đã ghép cặp (hoặc mồ côi — `ketQua` vẫn có thể là kết quả
 * của một hàng `tool` không hàng `assistant` nào khai).
 *
 * ĐÓNG theo mặc định, và đóng/mở bằng STATE của component, KHÔNG bằng CSS
 * (`<details>`/`:hover`). jsdom không chạy CSS ẩn/hiện theo UA stylesheet, nên
 * một cổng test dựa vào đó không chứng minh được gì — `{mo && (...)}` là DOM
 * thật, `queryByText` trả `null` thật khi đóng.
 */
function MotTheCongCu({
  ten,
  thamSo,
  ketQua,
}: {
  ten: string
  thamSo: string
  ketQua: string | null
}) {
  const [mo, setMo] = useState(false)
  const thamSoDep = thamSoDeHien(thamSo)
  const thamSoMotDongHien = thamSoMotDong(thamSo)

  return (
    <div
      data-testid="the-cong-cu"
      // KHÔNG bong bóng: không mỏ, không viền đứt (viền đứt đã mang nghĩa
      // "chưa có gì" ở nơi khác trong app — dùng lại đây sẽ đá nghĩa). Nền
      // `bg-acs` — CÙNG MÀU bong bóng agent, KHÔNG phải màu bong bóng khách
      // (`bg-bg`): tool là hành động của agent, đứng bên trái, nên phải cùng
      // sắc với "lời agent nói", chỉ khác ở HÌNH (hộp bo đều, không mỏ) để vẫn
      // phân biệt được với một lời nói thật.
      className="max-w-[76%] self-start overflow-hidden rounded-lg border border-border bg-acs"
    >
      <button
        type="button"
        onClick={() => setMo((v) => !v)}
        // `items-start`, KHÔNG `items-center`: dòng preview tham số bên dưới
        // làm cột trái cao hơn một dòng so với mũi tên — căn giữa sẽ kéo mũi
        // tên lệch xuống khi có preview, lệch lên khi không có.
        className="flex w-full items-start gap-1.5 px-3 py-2 text-left text-[13px] text-muted"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span>Agent đã dùng tool ·</span>
            <span className="font-mono font-semibold text-fg">{ten}</span>
          </div>
          {/* PREVIEW MỘT DÒNG, hiện cả khi thẻ đóng. `truncate` chứ không xuống
              dòng: nó là một dòng liếc qua — tham số dài thì cụt đuôi ở đây và
              đọc đủ trong khối «Tham số» sau khi mở. */}
          {thamSoMotDongHien && (
            <p className="mt-0.5 truncate font-mono text-[11.5px] text-muted-2">
              {thamSoMotDongHien}
            </p>
          )}
        </div>
        <span
          className={`mt-0.5 shrink-0 text-muted-3 transition-transform ${mo ? 'rotate-90' : ''}`}
        >
          ›
        </span>
      </button>
      {mo && (
        <div className="space-y-2 border-t border-border-soft px-3 py-2.5">
          {thamSoDep && <KhoiDuLieuTool nhan="Tham số" noiDung={thamSoDep} />}
          <KhoiDuLieuTool
            nhan="Kết quả"
            noiDung={ketQua === null ? 'Phiên bị ngắt trước khi có kết quả.' : demDep(ketQua)}
          />
        </div>
      )}
    </div>
  )
}

function BongBongLuot({
  role,
  content,
  taoLuc,
}: {
  role: 'khach' | 'agent'
  content: string
  taoLuc: string
}) {
  return (
    <div className="group/msg flex flex-col">
      <span
        data-testid="bong-bong"
        // `tabIndex={0}` là chỗ neo focus cho bàn phím: `:focus-within` của mốc
        // giờ dưới đây phải có MỘT phần tử con nhận được focus, nếu không quy
        // tắc "focus hiện y như hover" (ràng buộc §5.3 thứ 2) không bao giờ
        // kích hoạt được — bong bóng bản thân không có input/button nào khác.
        tabIndex={0}
        className={`max-w-[76%] rounded-2xl px-3 py-2 text-[14px] leading-[1.55] ${
          role === 'khach'
            ? 'ml-auto rounded-br-sm border border-border bg-bg'
            : 'rounded-bl-sm bg-acs'
        }`}
      >
        {/* Ai nói chỉ hiện bằng màu + căn trái/phải — trình đọc màn hình cần chữ
            (WCAG 1.3.1). Lịch sử tĩnh nên không cần vùng live. */}
        <span className="sr-only">{role === 'khach' ? 'Khách' : 'Agent'}: </span>
        {content}
      </span>
      <span
        data-testid="moc-gio"
        // `translate-y-[3px]` là cái "nhích" mà ràng buộc mốc giờ #4 nói tới:
        // giờ trượt nhẹ lên đúng vị trí lúc hiện, không chỉ mờ dần tại chỗ.
        // `prefers-reduced-motion` ở `theme.css` ghim `transform: none` để bỏ
        // đúng phần trượt này mà KHÔNG đụng vào transition của `opacity` —
        // mờ dần vẫn phải còn.
        className={`moc-gio h-4 translate-y-[3px] text-[11.5px] leading-4 text-muted-3 opacity-0 transition
                    group-hover/msg:translate-y-0 group-hover/msg:opacity-100
                    group-focus-within/msg:translate-y-0 group-focus-within/msg:opacity-100
                    ${role === 'khach' ? 'text-right' : ''}`}
      >
        {gioCua(taoLuc)}
      </span>
    </div>
  )
}

export function Transcript({
  luot,
  skillCallsDuPhong = [],
  toSang,
}: {
  luot: readonly Luot[]
  skillCallsDuPhong?: readonly unknown[]
  /** `seq` của lượt cần cuộn tới + tô sáng (deep-link `?seq=`). */
  toSang?: number
}) {
  const goc = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (toSang === undefined) return
    goc.current?.querySelector(`[data-seq="${toSang}"]`)?.scrollIntoView?.({ block: 'center' })
  }, [toSang, luot])

  // Pass 1 — quét TRƯỚC khi render: mọi `tool_call_id` mà một hàng `assistant`
  // BẤT KỲ đã khai, và kết quả (nếu có) của từng id. Tách khỏi vòng render để
  // KHÔNG phụ thuộc thứ tự hàng — một hàng `tool` tới trước hàng `assistant`
  // khai nó (dữ liệu lệch) vẫn được nhận diện đúng là "đã ghép cặp", không bị
  // render lặp hai lần (một lần ở khối ghép, một lần ở nhánh mồ côi).
  const idDaKhai = new Set<string>()
  const ketQuaTheoId = new Map<string, string>()
  for (const l of luot) {
    if (l.role === 'assistant') {
      for (const cg of layDsCuocGoi(l.meta)) idDaKhai.add(cg.id)
    } else if (l.role === 'tool') {
      const id = layToolCallId(l.meta)
      if (id) ketQuaTheoId.set(id, l.content)
    }
  }

  const coToolTrongLuot = idDaKhai.size > 0
  // Dự phòng chỉ tính khi KHÔNG lượt nào mang tool_calls — với `luot` rỗng thì
  // điều đó luôn đúng, nên một phiên 0 lượt vẫn có thể có khối này.
  const coDuPhong = !coToolTrongLuot && skillCallsDuPhong.length > 0

  // KHÔNG early-return riêng cho `luot.length === 0`: một phiên 0 lượt VẪN có
  // thể mang `skillCalls` mức phiên (ca `s-anh-2` trong fake) — early-return ở
  // đây sẽ chặn khối dự phòng dưới không bao giờ tới được.
  if (luot.length === 0 && !coDuPhong) {
    return (
      <p className="p-6 text-center text-than text-muted">Phiên này chưa có bản ghi hội thoại.</p>
    )
  }

  // `relative`: mỗi lượt mang một nhãn `sr-only` (`position:absolute`). Thiếu
  // containing block ở đây, nhãn bám ra tới `<main>` — vượt qua vùng cuộn
  // `overflow-y-auto` của màn cha nên KHÔNG bị cắt, và static position của
  // lượt cuối (tính như thể transcript không cuộn) kéo `<main>` dài thêm đúng
  // chiều cao transcript: phiên dài là trang cuộn trắng xuống tận đáy. Đo trên
  // `/convos/$phone` (1916×988, ~44 lượt): `<main>` dư 2289px → 0. Cùng bài
  // học `OMedia.tsx` (`max-md:relative`).
  return (
    <div ref={goc} className="relative flex flex-col gap-2.5">
      {luot.length === 0 && (
        <p className="text-center text-than text-muted">Phiên này chưa có bản ghi hội thoại.</p>
      )}
      {luot.map((l) => {
        // `tool` — hàng KẾT QUẢ. Đã ghép cặp thì hiện qua khối của hàng
        // `assistant` khai nó (nhánh dưới) — ở đây chỉ còn lo phần MỒ CÔI: một
        // kết quả không hàng `assistant` nào khai (lịch sử bị cắt đầu, hoặc dữ
        // liệu lệch). Một hàng mồ côi vẫn phải HIỆN, không được biến mất.
        if (l.role === 'tool') {
          const id = layToolCallId(l.meta)
          if (id && idDaKhai.has(id)) return null
          return (
            <MotTheCongCu
              key={l.seq}
              ten={layTenTool(l.meta) ?? 'không rõ'}
              thamSo=""
              ketQua={l.content}
            />
          )
        }

        if (l.role === 'assistant') {
          const dsCuocGoi = layDsCuocGoi(l.meta)
          // `content: ''` + không cuộc gọi nào ⇒ không có gì để hiện. KHÔNG
          // render một bong bóng trống — hàng `content: ''` kèm `tool_calls`
          // là YÊU CẦU gọi tool (xem docstring đầu tệp), không phải một lời
          // nói rỗng; hàng rỗng cả hai là dữ liệu suy biến, bỏ qua an toàn.
          if (!l.content && dsCuocGoi.length === 0) return null
          const nhanKb = docNhanKichBan(l.meta)
          return (
            <div
              key={l.seq}
              data-testid={`tin-${l.seq}`}
              data-seq={l.seq}
              data-to-sang={l.seq === toSang ? 'true' : undefined}
              className={`flex flex-col gap-2.5 ${l.seq === toSang ? 'rounded-lg ring-2 ring-ac/40' : ''}`}
            >
              {l.content && <BongBongLuot role="agent" content={l.content} taoLuc={l.taoLuc} />}
              {nhanKb && l.content && <TheNutKichBan nhan={nhanKb} />}
              {dsCuocGoi.map((cg) => (
                <MotTheCongCu
                  key={`${l.seq}-${cg.id}`}
                  ten={cg.ten}
                  thamSo={cg.thamSo}
                  ketQua={ketQuaTheoId.get(cg.id) ?? null}
                />
              ))}
            </div>
          )
        }

        const b = ben(l.role)
        if (b === 'he_thong') {
          return (
            <p key={l.seq} className="text-center text-[12px] italic text-muted-3">
              <span className="sr-only">Hệ thống: </span>
              {l.content}
            </p>
          )
        }
        return (
          <div
            key={l.seq}
            data-testid={`tin-${l.seq}`}
            data-seq={l.seq}
            data-to-sang={l.seq === toSang ? 'true' : undefined}
            className={l.seq === toSang ? 'rounded-lg ring-2 ring-ac/40' : ''}
          >
            <BongBongLuot role={b} content={l.content} taoLuc={l.taoLuc} />
          </div>
        )
      })}

      {/* Dự phòng: chỉ khi KHÔNG lượt nào mang tool_calls. `conversations.skill_calls`
          ở mức PHIÊN nên không biết nó thuộc lượt nào — dồn xuống cuối là chỗ duy
          nhất không nói sai vị trí. */}
      {coDuPhong && (
        <div className="mt-2 rounded-lg border border-border bg-bg p-2.5">
          <p className="mb-1 text-[11.5px] font-semibold uppercase tracking-wider text-muted-3">
            Công cụ agent đã gọi
          </p>
          {skillCallsDuPhong.map((s, i) => (
            <p key={i} className="font-mono text-[12px] text-muted-2">
              {typeof s === 'string' ? s : JSON.stringify(s)}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
