import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bang,
  CAO_MAN,
  DauBang,
  HANG_NUT,
  Hang,
  NUT_CHINH,
  NUT_HANG,
  NUT_HANG_XOA,
  NUT_PHU,
  O_LOC,
  TD,
  TheBang,
  VungCuon,
  type Cot,
} from '@/components/ui/Bang'
import { CongTac } from '@/components/ui/CongTac'
import { DauMuc } from '@/components/ui/DauMuc'
import { LoiTai } from '@/components/ui/TrangThai'
import { LoiApi } from '@/lib/http'
import { docChuDe, KHOA, soanChuDe, suaChuDe, themChuDe, xoaChuDe, type ChuDe } from '../api'
import { guiCau, hienCau } from '../cauTim'
import { HopThoai } from './HopThoai'

const COT: readonly Cot[] = [
  { nhan: 'Bật' },
  { nhan: 'Chủ đề' },
  { nhan: 'Mô tả', rong: 'w-full' },
  { nhan: '' },
]

const O_NHIEU_DONG = 'w-full rounded-md border border-border-strong px-3 py-2 text-than focus:border-fg'

function FormChuDe({ ban, dong }: { ban: ChuDe | null; dong: () => void }) {
  const [ten, setTen] = useState(ban?.ten ?? '')
  const [moTa, setMoTa] = useState(ban?.moTa ?? '')
  const [cauTim, setCauTim] = useState(ban ? ban.cauTim.map(hienCau).join('\n') : '')
  const [daSoan, setDaSoan] = useState(ban !== null)
  const [loi, setLoi] = useState('')
  const qc = useQueryClient()
  const soan = useMutation({
    mutationFn: () => soanChuDe(ten.trim(), moTa.trim()),
    onSuccess: (r) => {
      setCauTim(r.cauTim.map(hienCau).join('\n'))
      setDaSoan(true)
      setLoi('')
    },
    onError: (e: Error) => setLoi(e instanceof LoiApi ? e.message : 'Không soạn được câu tìm bài.'),
  })
  const luu = useMutation({
    mutationFn: () => {
      const cau = cauTim
        .split('\n')
        .map((c) => guiCau(c.trim()))
        .filter(Boolean)
      return ban
        ? suaChuDe(ban.id, { ten: ten.trim(), moTa: moTa.trim(), cauTim: cau })
        : themChuDe({ ten: ten.trim(), moTa: moTa.trim(), cauTim: cau, tuKhoa: [] })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: KHOA.chuDe })
      dong()
    },
    onError: (e: Error) => setLoi(e instanceof LoiApi ? e.message : 'Không lưu được chủ đề.'),
  })

  return (
    <HopThoai tieuDe={ban ? `Sửa chủ đề «${ban.ten}»` : 'Thêm chủ đề'} dong={dong}>
      <label className="mt-4 block">
        <span className="mb-1.5 block text-phu text-muted">Tên chủ đề</span>
        <input className={`${O_LOC} w-full`} value={ten} onChange={(e) => setTen(e.target.value)} maxLength={80} autoFocus />
      </label>
      <label className="mt-3 block">
        <span className="mb-1.5 block text-phu text-muted">Mô tả: chủ đề này nói về gì, khách hay hỏi gì</span>
        <textarea className={O_NHIEU_DONG} rows={3} value={moTa} onChange={(e) => setMoTa(e.target.value)} maxLength={1000} />
      </label>
      {daSoan && (
        <label className="mt-3 block">
          <span className="mb-1.5 block text-phu text-muted">
            Câu tìm bài, mỗi dòng một câu. {'{dự án}'} và {'{khu vực}'} được thay bằng tên và địa danh của từng dự án.
          </span>
          <textarea className={O_NHIEU_DONG} rows={5} value={cauTim} onChange={(e) => setCauTim(e.target.value)} />
        </label>
      )}
      {loi && (
        <p role="alert" className="mt-2 text-[13px] text-badge-alert-fg">
          {loi}
        </p>
      )}
      <div className={`${HANG_NUT} mt-4`}>
        <button type="button" className={NUT_PHU} onClick={dong}>
          Huỷ
        </button>
        {daSoan ? (
          <>
            <button type="button" className={NUT_PHU} disabled={!ten.trim() || soan.isPending} onClick={() => soan.mutate()}>
              {soan.isPending ? 'Đang soạn…' : 'Soạn lại câu tìm'}
            </button>
            <button type="button" className={NUT_CHINH} disabled={luu.isPending || !ten.trim() || !cauTim.trim()} onClick={() => luu.mutate()}>
              Lưu chủ đề
            </button>
          </>
        ) : (
          <button type="button" className={NUT_CHINH} disabled={!ten.trim() || soan.isPending} onClick={() => soan.mutate()}>
            {soan.isPending ? 'Đang soạn…' : 'Tạo câu tìm bài'}
          </button>
        )}
      </div>
    </HopThoai>
  )
}

export function TabChuDe({ suaDuoc }: { suaDuoc: boolean }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: KHOA.chuDe, queryFn: docChuDe })
  const [form, setForm] = useState<'dong' | 'them' | ChuDe>('dong')
  const [loi, setLoi] = useState('')
  const lamTuoi = () => void qc.invalidateQueries({ queryKey: ['kb-web'] })
  const bat = useMutation({ mutationFn: (v: { id: number; bat: boolean }) => suaChuDe(v.id, { bat: v.bat }), onSuccess: lamTuoi })
  const xoa = useMutation({ mutationFn: xoaChuDe, onSuccess: lamTuoi, onError: (e: Error) => setLoi(e.message) })

  if (q.isPending) return <p className="text-[14px] text-muted">Đang tải…</p>
  if (q.isError) return <LoiTai viec="danh sách chủ đề" thuLai={() => void q.refetch()} />
  const ds = q.data
  const soBat = ds.filter((c) => c.bat).length

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <DauMuc
        tieuDe="Chủ đề hồ sơ"
        dem={`${soBat} / ${ds.length} đang bật`}
        ghiChu="Các chủ đề dùng để tìm thông tin cho hồ sơ dự án. Tối đa 20 chủ đề."
        phai={
          suaDuoc ? (
            <button type="button" className={NUT_CHINH} onClick={() => setForm('them')} disabled={ds.length >= 20}>
              Thêm chủ đề
            </button>
          ) : undefined
        }
      />
      {loi && (
        <p role="alert" className="text-[13px] text-badge-alert-fg">
          {loi}
        </p>
      )}
      <TheBang cao={CAO_MAN}>
        <VungCuon>
          <Bang nhan="Chủ đề">
            <DauBang cot={COT} />
            <tbody>
              {ds.map((c) => (
                <Hang key={c.id}>
                  <td className={`${TD} w-12`}>
                    <CongTac bat={c.bat} nhan={c.ten} dangGui={bat.isPending || !suaDuoc} doi={(v) => bat.mutate({ id: c.id, bat: v })} />
                  </td>
                  <td className={`${TD} font-medium whitespace-nowrap text-fg`}>{c.ten}</td>
                  <td className={`${TD} text-[13px] text-muted`}>{c.moTa || '—'}</td>
                  <td className={`${TD} text-right whitespace-nowrap`}>
                    {suaDuoc && (
                      <span className="inline-flex gap-1.5">
                        <button type="button" className={NUT_HANG} onClick={() => setForm(c)}>
                          Sửa
                        </button>
                        <button
                          type="button"
                          className={NUT_HANG_XOA}
                          onClick={() => {
                            if (window.confirm(`Xoá chủ đề «${c.ten}»? Mục này sẽ không còn trong hồ sơ ở lần viết kế tiếp.`)) xoa.mutate(c.id)
                          }}
                        >
                          Xoá
                        </button>
                      </span>
                    )}
                  </td>
                </Hang>
              ))}
            </tbody>
          </Bang>
        </VungCuon>
      </TheBang>
      {form !== 'dong' && <FormChuDe key={form === 'them' ? 'them' : form.id} ban={form === 'them' ? null : form} dong={() => setForm('dong')} />}
    </div>
  )
}
