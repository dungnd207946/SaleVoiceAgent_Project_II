/**
 * Khối «Luồng xử lý» dưới một câu trả lời của engine v2 ở trang Thử agent — PORT từ `static/chat.html` của
 * odyssey-agent (`renderTrace`): hàng tóm tắt (NLU · act · chữ đầu · tổng · guard) → bấm mở ra thanh thời gian,
 * 9 bước L0 → NLU → chọn dự án → planner → fact sheet → Composer → guard → phát ra → việc đã làm, và JSON đầy đủ.
 *
 * Trace là `last_trace` của engine (khoá theo `agent_v2/engine.py::_turn`) — đọc phòng thủ: thiếu khoá nào thì bước
 * đó nói «không có», không vỡ. Mở/đóng bằng state chứ không `<details>` (jsdom không ẩn nội dung `<details>`).
 */
import { useState } from 'react'
import { useSaoChep } from '@/lib/saoChep'
import { Icon } from '@/components/icons'
import { useLang } from '@/i18n'

type Obj = Record<string, unknown>

const obj = (v: unknown): Obj =>
  typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Obj) : {}
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
const so = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
const chu = (v: unknown): string =>
  v === null || v === undefined ? '' : typeof v === 'string' ? v : JSON.stringify(v)

function ms(v: unknown): string {
  const n = so(v)
  if (n <= 0) return '—'
  return n < 1000 ? `${Math.round(n)} ms` : `${(n / 1000).toFixed(2).replace('.', ',')} s`
}

type Sac = '' | 'ok' | 'warn' | 'vang'
const SAC: Record<Sac, string> = {
  '': 'border border-border bg-surface text-nav',
  ok: 'border border-transparent bg-acs text-ac',
  warn: 'border border-transparent bg-badge-warn-bg text-badge-warn-fg',
  vang: 'border border-transparent bg-badge-warn-nhat-bg text-badge-warn-fg',
}

function Pill({ children, sac = '' }: { children: React.ReactNode; sac?: Sac }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-px font-mono text-nhan ${SAC[sac]}`}
    >
      {children}
    </span>
  )
}

function Bang({ dong }: { dong: Obj }) {
  const muc = Object.entries(dong).filter(([, v]) => v !== undefined && v !== null && v !== '')
  if (muc.length === 0) return <p className="text-phu text-muted-2">—</p>
  return (
    <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-3 gap-y-1 text-phu">
      {muc.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="break-words font-mono text-fg">{chu(v)}</dd>
        </div>
      ))}
    </dl>
  )
}

function DanhSach({ muc }: { muc: unknown[] }) {
  if (muc.length === 0) return <p className="text-phu text-muted-2">—</p>
  return (
    <ul className="list-disc space-y-0.5 pl-4 text-phu text-fg">
      {muc.map((x, i) => (
        <li key={i} className="break-words">
          {chu(x)}
        </li>
      ))}
    </ul>
  )
}

function Pre({ chuoi }: { chuoi: string }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-md border border-border bg-surface p-2.5 font-mono text-nhan leading-[1.5] whitespace-pre-wrap text-fg">
      {chuoi}
    </pre>
  )
}

/** Đoạn của thanh thời gian — nối tiếp nhau trên đường nóng tới chữ đầu, rồi phần phát còn lại. Màu là thang
 *  đơn sắc có sẵn (`--color-comp-*`), nhãn + số ở chú giải mới là thứ phân biệt. */
const DOAN = [
  ['l0', 'L0 tiền xử lý', 'var(--color-comp-5)'],
  ['nlu', 'NLU', 'var(--color-comp-1)'],
  ['skill', 'Planner + skill', 'var(--color-comp-2)'],
  ['cttft', 'Composer token đầu', 'var(--color-comp-3)'],
  ['first', 'Chờ câu đầu + guard', 'var(--color-comp-4)'],
  ['rest', 'Phát phần còn lại', 'var(--color-comp-0)'],
] as const

function ThanhThoiGian({ tm, composer }: { tm: Obj; composer: unknown }) {
  const l0 = so(tm['l0_ms'])
  const nlu = so(tm['nlu_ms'])
  const skill = so(tm['skills_ms'])
  const cttft = composer === 'called' ? so(tm['composer_ttft_ms']) : 0
  const ttft = so(tm['ttft_ms']) || so(tm['total_ms'])
  const v: Record<string, number> = {
    l0,
    nlu,
    skill,
    cttft,
    first: Math.max(0, ttft - l0 - nlu - skill - cttft),
    rest: Math.max(0, so(tm['total_ms']) - ttft),
  }
  const tong = Object.values(v).reduce((a, b) => a + b, 0) || 1
  const co = DOAN.filter(([k]) => v[k])
  return (
    <div>
      <div className="flex h-2 overflow-hidden rounded-full bg-fill" aria-hidden>
        {co.map(([k, nhan, mau]) => (
          <i
            key={k}
            title={`${nhan}: ${ms(v[k])}`}
            style={{ width: `${(100 * (v[k] ?? 0)) / tong}%`, background: mau }}
          />
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-nhan text-muted">
        {co.map(([k, nhan, mau]) => (
          <span key={k} className="inline-flex items-center gap-1">
            <b className="inline-block size-2 rounded-sm" style={{ background: mau }} />
            {nhan} <span className="font-mono tabular-nums">{ms(v[k])}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

interface Buoc {
  readonly ma: string
  readonly tieuDe: string
  readonly thoiGian: string
  readonly pills: React.ReactNode
  readonly noiDung: React.ReactNode
}

function buocCua(t: Obj): readonly Buoc[] {
  const tm = obj(t['timing'])
  const nlu = obj(t['nlu'])
  const acts = arr(nlu['acts'])
  const parts = arr(t['parts']).map(obj)
  const hits = arr(t['guard']).map(obj)
  const g6 = arr(t['g6_added'])
  const codeOut = arr(t['code_out'])
  const actions = arr(t['actions'])
  const pj = t['project'] ? obj(t['project']) : null
  const laLuat = nlu['source'] === 'rule'
  const fixes = arr(nlu['fixes'])
  const goi = t['composer'] === 'called'
  return [
    {
      ma: 'l0',
      tieuDe: '① L0 · Tiền xử lý',
      thoiGian: ms(tm['l0_ms']),
      pills: (
        <Pill sac={laLuat ? 'ok' : ''}>{laLuat ? 'làn luật — không gọi LLM' : 'chuyển NLU'}</Pill>
      ),
      noiDung: <Bang dong={{ 'lời khách': t['user'], 'nguồn act': nlu['source'] }} />,
    },
    {
      ma: 'nlu',
      tieuDe: '② L2 · NLU',
      thoiGian: laLuat ? '0 ms' : ms(tm['nlu_ms']),
      pills: (
        <>
          {nlu['buc'] === true && <Pill sac="warn">khách bực</Pill>}
          {Boolean(nlu['error']) && <Pill sac="warn">lỗi</Pill>}
          {fixes.length > 0 && <Pill sac="vang">luật sửa {fixes.length}</Pill>}
        </>
      ),
      noiDung: (
        <div className="space-y-2">
          <p className="text-phu text-muted">Act sau khi kiểm + sửa lệnh:</p>
          <DanhSach muc={acts} />
          <p className="text-phu text-muted">need (hồ sơ khách tự nói):</p>
          <Bang dong={obj(nlu['need'])} />
          {fixes.length > 0 && (
            <>
              <p className="text-phu text-muted">Sửa / luật đã áp:</p>
              <DanhSach muc={fixes} />
            </>
          )}
          {arr(nlu['dropped']).length > 0 && (
            <>
              <p className="text-phu text-muted">Lệnh bị bỏ:</p>
              <DanhSach muc={arr(nlu['dropped'])} />
            </>
          )}
          {Boolean(nlu['error']) && (
            <p className="text-phu text-badge-alert-fg">{chu(nlu['error'])}</p>
          )}
          {nlu['raw'] !== undefined && <Pre chuoi={JSON.stringify(nlu['raw'], null, 2)} />}
        </div>
      ),
    },
    {
      ma: 'du_an',
      tieuDe: '③ Chọn dự án',
      thoiGian: ms(tm['pick_ms']),
      pills: pj ? (
        <Pill sac={pj['status'] === 'resolved' ? 'ok' : 'vang'}>
          {chu(pj['status']) || '?'}
          {pj['code'] ? ` · ${chu(pj['code'])}` : ''}
        </Pill>
      ) : (
        <Pill>không nhắc dự án</Pill>
      ),
      noiDung: pj ? (
        <Bang
          dong={{
            'trạng thái': pj['status'],
            mã: pj['code'],
            bậc: pj['tier'],
            'tự suy': pj['inferred'],
            'LLM chọn': pj['llm_pick'],
            'dấu hiệu': pj['signal'],
            'ứng viên': pj['candidates'],
            'thời gian': ms(pj['ms']),
          }}
        />
      ) : (
        <p className="text-phu text-muted-2">Lượt này không cần giải mã dự án.</p>
      ),
    },
    {
      ma: 'planner',
      tieuDe: '④ L3–L4 · Planner + action',
      thoiGian: ms(tm['skills_ms']),
      pills: (
        <>
          <Pill>{parts.length} ý</Pill>
          {so(t['media']) > 0 && <Pill sac="ok">media {so(t['media'])}</Pill>}
        </>
      ),
      noiDung:
        parts.length === 0 ? (
          <p className="text-phu text-muted-2">(không có ý nào)</p>
        ) : (
          <div className="space-y-2">
            {parts.map((p, i) => (
              <div key={i} className="rounded-md border border-border bg-surface p-2.5">
                <p className="mb-1 text-phu font-semibold text-fg">
                  {chu(p['topic']) || '?'}{' '}
                  <span className="font-normal text-muted">· {chu(p['noi'])}</span>
                </p>
                <DanhSach muc={arr(p['facts'])} />
                {arr(p['actions']).length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {arr(p['actions']).map((a, j) => (
                      <Pill key={j} sac={chu(a).includes(':ok') ? 'ok' : 'warn'}>
                        {chu(a)}
                      </Pill>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        ),
    },
    {
      ma: 'factsheet',
      tieuDe: '⑤ L5 · Fact sheet',
      thoiGian: '',
      pills: <Pill>{chu(t['factsheet']).split('\n').length} dòng</Pill>,
      noiDung: <Pre chuoi={chu(t['factsheet']) || '(trống)'} />,
    },
    {
      ma: 'composer',
      tieuDe: '⑥ L6 · Composer',
      thoiGian: goi ? ms(tm['composer_ms']) : '',
      pills: (
        <>
          <Pill sac={goi ? '' : 'ok'}>{goi ? 'gọi LLM' : 'bỏ qua — chỉ câu code'}</Pill>
          {goi && <Pill>token đầu {ms(tm['composer_ttft_ms'])}</Pill>}
          {Boolean(t['composer_error']) && <Pill sac="warn">lỗi</Pill>}
        </>
      ),
      noiDung: (
        <Bang
          dong={{
            'trạng thái': t['composer'],
            'token đầu': ms(tm['composer_ttft_ms']),
            'cả stream': ms(tm['composer_ms']),
            lỗi: t['composer_error'],
          }}
        />
      ),
    },
    {
      ma: 'guard',
      tieuDe: '⑦ L7 · Guard',
      thoiGian: '',
      pills: (
        <>
          <Pill sac={hits.length ? 'warn' : 'ok'}>{hits.length} can thiệp</Pill>
          {g6.length > 0 && <Pill sac="vang">G6 nối {g6.length}</Pill>}
          {arr(t['lap_bo']).length > 0 && <Pill sac="vang">bỏ lặp {arr(t['lap_bo']).length}</Pill>}
        </>
      ),
      noiDung:
        hits.length === 0 && g6.length === 0 ? (
          <p className="text-phu text-muted-2">Không câu nào bị sửa / bỏ.</p>
        ) : (
          <div className="space-y-1.5 text-phu">
            {hits.map((h, i) => (
              <p key={i} className="break-words">
                <Pill sac="warn">{chu(h['rule']) || '?'}</Pill>{' '}
                <span className="text-muted line-through">{chu(h['before'])}</span> →{' '}
                <span className="text-fg">{chu(h['after']) || '(bỏ câu)'}</span>
              </p>
            ))}
            {g6.length > 0 && (
              <>
                <p className="text-muted">G6 nối thêm (ý Composer bỏ sót):</p>
                <DanhSach muc={g6} />
              </>
            )}
          </div>
        ),
    },
    {
      ma: 'phat',
      tieuDe: '⑧ Phát ra',
      thoiGian: `${ms(tm['ttft_ms'])} / ${ms(tm['total_ms'])}`,
      pills: <Pill>{codeOut.length} câu code</Pill>,
      noiDung: (
        <div className="space-y-2">
          <p className="text-phu text-muted">Câu do code phát nguyên văn (sau phần Composer):</p>
          <DanhSach muc={codeOut} />
          <Pre chuoi={chu(t['reply'])} />
        </div>
      ),
    },
    {
      ma: 'viec',
      tieuDe: '⑨ Sổ hành động lượt này',
      thoiGian: '',
      pills: <Pill sac={actions.length ? 'ok' : ''}>{actions.length} việc</Pill>,
      noiDung:
        actions.length === 0 ? (
          <p className="text-phu text-muted-2">Lượt này không ghi việc nào.</p>
        ) : (
          <div className="space-y-2">
            {actions.map((a, i) => (
              <Bang key={i} dong={obj(a)} />
            ))}
          </div>
        ),
    },
  ]
}

/** Một lượt có trace — thứ mọi component dưới đây nhận. */
export interface MucLuong {
  readonly trace: Record<string, unknown>
  readonly engine: string
  readonly turnId: string
  readonly luot: number
}

/** Hàng chip số đo của một lượt (NLU · act · chữ đầu · tổng · guard · việc) — đầu panel. */
function ChipLuong({ muc }: { muc: MucLuong }) {
  const tm = obj(muc.trace['timing'])
  const nlu = obj(muc.trace['nlu'])
  const acts = arr(nlu['acts'])
    .map((a) => chu(obj(a)['i']))
    .filter(Boolean)
  const hits = arr(muc.trace['guard']).length
  const viec = arr(muc.trace['actions']).length
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Pill>{acts.length ? acts.join(' + ') : '—'}</Pill>
      <Pill sac="vang">NLU {nlu['source'] === 'rule' ? 'làn luật' : ms(tm['nlu_ms'])}</Pill>
      <Pill>chữ đầu {ms(tm['ttft_ms'])}</Pill>
      <Pill>tổng {ms(tm['total_ms'])}</Pill>
      <Pill sac={hits ? 'warn' : 'ok'}>guard {hits}</Pill>
      {viec > 0 && <Pill sac="ok">việc {viec}</Pill>}
    </div>
  )
}

const NUT_PHU_NHO =
  'rounded-sm border border-border bg-surface px-2 py-0.5 text-nhan text-nav hover:bg-fill-strong'

/** Thân chi tiết: công cụ (mở / thu / copy) · thanh thời gian · 9 bước · JSON. Dùng chung khối tại chỗ và panel. */
function ChiTietLuong({ muc }: { muc: MucLuong }) {
  const { t } = useLang()
  const { daCopy, loiCopy, copy } = useSaoChep()
  const [buocMo, setBuocMo] = useState<ReadonlySet<string>>(new Set())
  const [moJson, setMoJson] = useState(false)
  const { trace } = muc
  const buoc = buocCua(trace)

  function doiBuoc(ma: string): void {
    setBuocMo((c) => {
      const moi = new Set(c)
      if (moi.has(ma)) moi.delete(ma)
      else moi.add(ma)
      return moi
    })
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          className={NUT_PHU_NHO}
          onClick={() => setBuocMo(new Set(buoc.map((b) => b.ma)))}
        >
          {t({ vi: 'Mở hết bước', en: 'Expand all' })}
        </button>
        <button type="button" className={NUT_PHU_NHO} onClick={() => setBuocMo(new Set())}>
          {t({ vi: 'Thu hết', en: 'Collapse all' })}
        </button>
        <button
          type="button"
          className={NUT_PHU_NHO}
          onClick={() => void copy(JSON.stringify(trace, null, 2))}
        >
          {daCopy
            ? t({ vi: 'Đã copy', en: 'Copied' })
            : loiCopy
              ? t({ vi: 'Không copy được', en: 'Copy failed' })
              : 'Copy JSON'}
        </button>
        <span className="ml-auto font-mono text-nhan text-muted">
          engine {muc.engine || '?'} · turn {muc.turnId}
        </span>
      </div>

      <ThanhThoiGian tm={obj(trace['timing'])} composer={trace['composer']} />

      <ul className="space-y-1.5">
        {buoc.map((b) => {
          const dangMo = buocMo.has(b.ma)
          return (
            <li key={b.ma} className="rounded-md border border-border bg-surface">
              <button
                type="button"
                aria-expanded={dangMo}
                onClick={() => doiBuoc(b.ma)}
                className="flex w-full flex-wrap items-center gap-1.5 px-2.5 py-1.5 text-left"
              >
                <span className="text-phu font-medium text-fg">{b.tieuDe}</span>
                {b.pills}
                <span className="ml-auto font-mono text-nhan tabular-nums text-muted">
                  {b.thoiGian}
                </span>
              </button>
              {dangMo && <div className="border-t border-border px-2.5 py-2">{b.noiDung}</div>}
            </li>
          )
        })}
      </ul>

      <div>
        <button
          type="button"
          aria-expanded={moJson}
          onClick={() => setMoJson((c) => !c)}
          className="text-phu text-muted hover:underline"
        >
          {t({ vi: 'JSON đầy đủ của lượt', en: 'Full turn JSON' })}
        </button>
        {moJson && (
          <div className="mt-1.5">
            <Pre chuoi={JSON.stringify(trace, null, 2)} />
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * Dòng trầm dưới câu trả lời — cùng họ với hàng icon copy / đánh giá (chữ nhỏ, sắc nhạt, nền chỉ khi rê / đang mở),
 * không phải một thẻ: thứ người dùng đọc là câu trả lời, luồng xử lý là thứ tra khi cần. Bấm để mở / đóng chi tiết.
 */
export function TomTatLuong({
  muc,
  mo,
  onBam,
  dieuKhien,
}: {
  muc: MucLuong
  mo: boolean
  onBam: () => void
  /** id vùng chi tiết mà nút mở ra (panel phải hoặc khối tại chỗ). */
  dieuKhien?: string
}) {
  const { t } = useLang()
  const tm = obj(muc.trace['timing'])
  const acts = arr(obj(muc.trace['nlu'])['acts'])
    .map((a) => chu(obj(a)['i']))
    .filter(Boolean)
  const hits = arr(muc.trace['guard']).length
  return (
    <button
      type="button"
      aria-expanded={mo}
      aria-controls={mo ? dieuKhien : undefined}
      data-luot={muc.luot}
      onClick={onBam}
      className={`inline-flex max-w-full items-center gap-1.5 rounded-sm px-1.5 py-1 text-phu transition-colors ${
        mo ? 'bg-acs text-ac' : 'text-muted hover:bg-fill-strong hover:text-fg'
      }`}
    >
      <Icon name="luongXuLy" className="size-3.5 flex-none" />
      <span className="font-medium whitespace-nowrap">
        {t({ vi: 'Luồng xử lý', en: 'Trace' })} · {t({ vi: 'lượt', en: 'turn' })} {muc.luot}
      </span>
      <span aria-hidden="true">·</span>
      <span className="min-w-0 truncate font-mono text-nhan">
        {acts.length ? acts.join(' + ') : '—'}
      </span>
      <span aria-hidden="true">·</span>
      <span className="font-mono text-nhan whitespace-nowrap tabular-nums">
        {ms(tm['total_ms'])}
      </span>
      {hits > 0 && (
        <>
          <span aria-hidden="true">·</span>
          <span className="font-mono text-nhan whitespace-nowrap text-badge-warn-fg">
            guard {hits}
          </span>
        </>
      )}
    </button>
  )
}

/** Màn hẹp: dòng tóm tắt, bấm thì chi tiết mở TẠI CHỖ ngay dưới. */
export function LuongXuLy({ muc }: { muc: MucLuong }) {
  const [mo, setMo] = useState(false)
  const id = `luong-${muc.luot}`
  return (
    <div className="flex w-full max-w-[80%] flex-col items-start gap-1.5">
      <TomTatLuong muc={muc} mo={mo} onBam={() => setMo((c) => !c)} dieuKhien={id} />
      {mo && (
        <div id={id} className="w-full space-y-3 rounded-lg border border-border bg-surface p-3">
          <ChipLuong muc={muc} />
          <ChiTietLuong muc={muc} />
        </div>
      )}
    </div>
  )
}

export const ID_PANEL_LUONG = 'panel-luong-xu-ly'

/**
 * Cột phải của tab Chat trên màn rộng — CHỈ mở khi người dùng bấm dòng tóm tắt của một lượt; đóng bằng nút × hoặc
 * Esc. Cao trọn khung, thân tự cuộn, hội thoại bên trái vẫn đọc trọn. `key` theo lượt để đổi lượt là các bước đang
 * mở / JSON thu lại.
 */
export function PanelLuong({ muc, onDong }: { muc: MucLuong; onDong: () => void }) {
  const { t } = useLang()
  return (
    <section
      id={ID_PANEL_LUONG}
      aria-label={t({ vi: 'Luồng xử lý', en: 'Trace' })}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onDong()
      }}
      className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border bg-surface"
    >
      <header className="flex flex-none items-center gap-2 border-b border-border py-2 pr-2 pl-4">
        <Icon name="luongXuLy" className="size-4 flex-none text-muted" />
        <h2 className="text-than font-semibold text-fg">
          {t({ vi: 'Luồng xử lý', en: 'Trace' })}
          <span className="font-normal text-muted">
            {' '}
            · {t({ vi: 'lượt', en: 'turn' })} {muc.luot}
          </span>
        </h2>
        <button
          type="button"
          onClick={onDong}
          aria-label={t({ vi: 'Đóng luồng xử lý', en: 'Close trace' })}
          className="ml-auto rounded-sm p-1.5 text-muted transition-colors hover:bg-fill-strong hover:text-fg"
        >
          <Icon name="dong" className="size-4" />
        </button>
      </header>
      <div className="min-h-0 flex-1 space-y-3 overflow-auto px-4 py-3">
        <ChipLuong muc={muc} />
        <ChiTietLuong key={`${muc.turnId}:${muc.luot}`} muc={muc} />
      </div>
    </section>
  )
}
