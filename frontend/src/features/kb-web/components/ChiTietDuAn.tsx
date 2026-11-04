import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bang,
  CAO_MAN,
  DUONG_VE,
  DauBang,
  HANG_NUT,
  Hang,
  NUT_CHINH,
  NUT_HANG,
  NUT_PHU,
  NhomTab,
  PILL,
  TD,
  TD_PHU,
  TheBang,
  VungCuon,
  type Cot,
} from '@/components/ui/Bang'
import { DauMuc } from '@/components/ui/DauMuc'
import { Icon } from '@/components/icons'
import { ThanhTrang } from '@/components/ui/ThanhTrang'
import { KhoRong, LoiTai } from '@/components/ui/TrangThai'
import { anMuc, docChiTietDuAn, KHOA, lamMoiDuAn, loaiBai, type BaiDaThu } from '../api'
import { thanMuc } from '../hoSo'
import { usePhanTrang } from '../phanTrang'
import { luc } from '../thoiGian'

const KHONG_CO: readonly BaiDaThu[] = []

const COT_BAI: readonly Cot[] = [
  { nhan: 'Bài', rong: 'w-full' },
  { nhan: 'Nguồn' },
  { nhan: 'Ngày đăng' },
  { nhan: 'Trạng thái' },
  { nhan: '' },
]


export function ChiTietDuAn({
  code,
  ten,
  suaDuoc,
  quayLai,
}: {
  code: string
  ten: string
  suaDuoc: boolean
  quayLai: () => void
}) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: KHOA.chiTiet(code),
    queryFn: () => docChiTietDuAn(code),
    refetchInterval: (x) => (x.state.data?.dangChay ? 5_000 : false),
  })
  const [tab, setTab] = useState<'hs' | 'bt'>('hs')
  const [mo, setMo] = useState<ReadonlySet<string>>(new Set())
  const doiMo = (nhan: string) =>
    setMo((cu) => {
      const moi = new Set(cu)
      if (moi.has(nhan)) moi.delete(nhan)
      else moi.add(nhan)
      return moi
    })
  const lamTuoi = () => void qc.invalidateQueries({ queryKey: ['kb-web'] })
  const lamMoi = useMutation({ mutationFn: (mode: 'init' | 'rebuild') => lamMoiDuAn(code, mode), onSuccess: lamTuoi })
  const an = useMutation({ mutationFn: (v: { nhan: string; an: boolean }) => anMuc(code, v.nhan, v.an), onSuccess: lamTuoi })
  const loai = useMutation({ mutationFn: (v: { url: string; loai: boolean }) => loaiBai(code, v.url, v.loai), onSuccess: lamTuoi })
  const { hien: baiHien, thanh } = usePhanTrang(q.data?.bai ?? KHONG_CO)

  if (q.isPending) return <p className="text-[14px] text-muted">Đang tải…</p>
  if (q.isError) return <LoiTai viec="hồ sơ dự án" thuLai={() => void q.refetch()} />
  const ct = q.data
  const muc = ct.muc.map((m) => ({ ...m, ten: m.ten ?? m.nhan, an: m.an ?? ct.mucAn.includes(m.nhan) }))
  const capNhat = muc.map((m) => m.capNhatLuc).filter((x): x is string => !!x).sort().at(-1) ?? null
  const daCo = muc.filter((m) => m.noiDung && !m.an).length
  const trong = muc.every((m) => !m.noiDung && !m.an)

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div>
        <button type="button" className={DUONG_VE} onClick={quayLai}>
          ‹ Danh sách dự án
        </button>
        <DauMuc
          tieuDe={ten}
          ghiChu={`${daCo} / ${muc.length} chủ đề có dữ liệu · ${ct.bai.length} bài báo đã thu · ${capNhat ? `cập nhật ${luc(capNhat)}` : 'chưa có hồ sơ'}`}
          phai={
            suaDuoc ? (
              <div className={HANG_NUT}>
                {ct.dangChay && <span className="text-[13px] text-muted">đang viết…</span>}
                <button type="button" className={NUT_PHU} disabled={ct.dangChay || lamMoi.isPending} onClick={() => lamMoi.mutate('rebuild')}>
                  Viết lại hồ sơ từ đầu
                </button>
                <button type="button" className={NUT_CHINH} disabled={ct.dangChay || lamMoi.isPending} onClick={() => lamMoi.mutate('init')}>
                  {trong ? 'Tạo hồ sơ' : 'Cập nhật'}
                </button>
              </div>
            ) : undefined
          }
        />
      </div>
      <NhomTab
        muc={[
          { id: 'hs', nhan: `Hồ sơ · ${daCo}` },
          { id: 'bt', nhan: `Bài báo đã thu · ${ct.bai.length}` },
        ]}
        dangMo={tab}
        doi={setTab}
        nhan="Hồ sơ hay bài báo"
      />
      {tab === 'hs' &&
        (trong ? (
          <KhoRong tieuDe="Chưa có mục hồ sơ nào." huongDan="Bấm «Tạo hồ sơ» để dựng hồ sơ từ bài đã thu; cần vài phút." />
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-border bg-surface px-5">
            {muc.map((m) => {
              if (!m.noiDung)
                return (
                  <div key={m.nhan} className="flex items-center gap-3 border-t border-rule py-3 first:border-t-0">
                    <b className="text-[13px] text-muted">{m.ten}</b>
                    <span className="flex-1 text-[12px] text-muted-2">{m.an ? 'đang ẩn' : 'Chưa có dữ liệu'}</span>
                    {suaDuoc && m.an && (
                      <button type="button" className={NUT_HANG} disabled={an.isPending} onClick={() => an.mutate({ nhan: m.nhan, an: false })}>
                        Bỏ ẩn
                      </button>
                    )}
                  </div>
                )
              const dangAn = m.an
              const dangMo = mo.has(m.nhan)
              return (
                <div key={m.nhan} className="border-t border-rule py-3 first:border-t-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      aria-expanded={dangMo}
                      onClick={() => doiMo(m.nhan)}
                    >
                      <Icon
                        name="moXuong"
                        width={15}
                        height={15}
                        aria-hidden
                        className={`flex-none text-muted transition-transform ${dangMo ? '' : '-rotate-90'}`}
                      />
                      <b className={`text-[13px] ${dangAn ? 'text-muted' : ''}`}>{m.ten}</b>
                      <span className="min-w-0 flex-1 truncate text-[11.5px] text-muted-2">
                        {m.nguon.map((s) => `${s.ten}${s.ngay ? ` ${luc(s.ngay).replace(/ \d\d:\d\d$/, '')}` : ''}`).join(' · ')}
                      </span>
                    </button>
                    {suaDuoc && dangAn && (
                      <button type="button" className={NUT_HANG} disabled={an.isPending} onClick={() => an.mutate({ nhan: m.nhan, an: false })}>
                        Bỏ ẩn
                      </button>
                    )}
                  </div>
                  {dangMo && (
                    <p className={`mt-1.5 pl-[23px] text-[13px] whitespace-pre-line ${dangAn ? 'text-muted' : 'text-n10'}`}>
                      {thanMuc(m)}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        ))}
      {tab === 'bt' &&
        (ct.bai.length === 0 ? (
          <KhoRong tieuDe="Chưa có bài báo nào gắn với dự án này." huongDan="Bài sẽ xuất hiện sau lượt cập nhật mỗi đêm hoặc mỗi tuần." />
        ) : (
          <>
            <TheBang cao={CAO_MAN}>
              <VungCuon>
                <Bang nhan="Bài báo đã thu">
                  <DauBang cot={COT_BAI} />
                  <tbody>
                    {baiHien.map((b) => (
                      <Hang key={b.url}>
                        <td className={TD}>
                          <a className="font-medium text-ac hover:text-acd" href={b.url} target="_blank" rel="noreferrer">
                            {b.tieuDe || b.url}
                          </a>
                        </td>
                        <td className={TD_PHU}>{b.domain}</td>
                        <td className={TD_PHU}>{b.ngayDang ? luc(b.ngayDang).replace(/ \d\d:\d\d$/, '') : '—'}</td>
                        <td className={TD}>
                          {b.loai ? (
                            <span className={`${PILL} bg-badge-neutral-bg text-badge-neutral-fg`}>đã loại</span>
                          ) : (
                            <span className={`${PILL} bg-acs text-acd`}>đã dùng</span>
                          )}
                        </td>
                        <td className={`${TD} text-right`}>
                          {suaDuoc && (
                            <button type="button" className={NUT_HANG} disabled={loai.isPending} onClick={() => loai.mutate({ url: b.url, loai: !b.loai })}>
                              {b.loai ? 'Dùng lại' : 'Loại'}
                            </button>
                          )}
                        </td>
                      </Hang>
                    ))}
                  </tbody>
                </Bang>
              </VungCuon>
              <ThanhTrang {...thanh} />
            </TheBang>
          </>
        ))}
    </div>
  )
}
