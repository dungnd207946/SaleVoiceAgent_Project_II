/**
 * Bản ghi một cuộc gọi, TỰ DIỄN rồi lặp. Chữ ký của trang `/`.
 *
 * Vì sao nó là thứ đáng làm nhất ở đây: sản phẩm bán là một cuộc gọi. Để cuộc
 * gọi diễn ra trước mắt người đọc rẻ hơn mọi đoạn văn tả nó, và các chip «việc
 * đã làm» chen giữa lượt thoại là bằng chứng agent TRA CỨU chứ không đọc thuộc
 * — thứ khó nói bằng chữ.
 */
import { useEffect, useRef, useState } from 'react'
import { CUOC_GOI, KET_QUA, TEN_AGENT } from './duLieuMau'

/** `matchMedia` không có trong jsdom cũ; mặc định là KHÔNG giảm chuyển động. */
function giamChuyenDong(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
}

const TONG_LUOT = CUOC_GOI.length

export function TheCuocGoi() {
  /** Số lượt đã hiện. `TONG_LUOT` = xong cả cuộc. */
  const [hien, datHien] = useState(0)
  /** Đang chờ agent trả lời — hiện ba chấm. */
  const [dangNghi, datDangNghi] = useState(false)
  const [ketQua, datKetQua] = useState(0)
  const [giay, datGiay] = useState(0)
  const [vong, datVong] = useState(0)

  // `useRef` chứ không state: cờ này chỉ để vòng lặp biết mình đã bị huỷ, đọc
  // nó không cần render lại — và nếu là state thì effect tự huỷ chính nó.
  const song = useRef(true)

  useEffect(() => {
    if (giamChuyenDong()) {
      // Ghim trạng thái CUỐI, không phải trạng thái đầu. Tắt chuyển động mà để
      // thẻ trống thì mất đúng thứ nó kể — cùng lời dặn đã viết cho `agent-zzz`
      // trong theme.css.
      datHien(TONG_LUOT)
      datKetQua(KET_QUA.length)
      datGiay(134)
      return
    }

    song.current = true
    const doi = (ms: number) =>
      new Promise<void>((tiep) => {
        setTimeout(tiep, ms)
      })

    async function dien() {
      for (;;) {
        if (!song.current) return
        datHien(0)
        datKetQua(0)
        datGiay(0)
        await doi(700)

        for (let i = 0; i < TONG_LUOT; i++) {
          if (!song.current) return
          if (CUOC_GOI[i]?.ai === 'agent') {
            datDangNghi(true)
            await doi(900)
            if (!song.current) return
            datDangNghi(false)
          }
          datHien(i + 1)
          await doi(CUOC_GOI[i]?.ai === 'agent' ? 2100 : 1500)
        }

        for (let i = 0; i < KET_QUA.length; i++) {
          if (!song.current) return
          datKetQua(i + 1)
          await doi(260)
        }

        await doi(4200)
        if (!song.current) return
        // Vòng mới = một workspace khác, nên một cái tên khác.
        datVong((v) => v + 1)
      }
    }
    void dien()

    const nhip = setInterval(() => datGiay((g) => g + 1), 1000)
    return () => {
      song.current = false
      clearInterval(nhip)
    }
  }, [])

  const ten = TEN_AGENT[vong % TEN_AGENT.length] ?? TEN_AGENT[0]
  const dongHo = `${String(Math.floor(giay / 60)).padStart(2, '0')}:${String(giay % 60).padStart(2, '0')}`

  return (
    <figure className="overflow-hidden rounded-lg border border-panel-line bg-panel-raised">
      <figcaption className="flex items-center gap-3 border-b border-panel-line bg-white/[0.02] px-4 py-3">
        <span className="tho-nhe size-[7px] shrink-0 rounded-full bg-live" />
        <span className="mr-auto min-w-0">
          <b className="block text-[13px] font-semibold">Cuộc gọi đến · 0903 217 •••</b>
          <span className="flex items-center gap-1.5 font-mono text-nhan text-panel-muted-2">
            23:41 ·{' '}
            {/* Gạch chân nét đứt: dấu hiệu đây là một Ô CẤU HÌNH, không phải
                tên cố định của sản phẩm. */}
            <span className="border-b border-dashed border-panel-muted-2 pb-px text-panel-chu-2">
              {ten}
            </span>
            {/* Ẩn ở khổ hẹp: bốn mẩu trên một dòng làm meta vỡ hai hàng và đẩy
                sóng tiếng xuống. Tên agent và nhãn lĩnh vực có việc phải làm ở
                đây, tên thương hiệu thì không. */}
            <span className="hidden uppercase tracking-[0.06em] sm:inline">An Phú Land</span>
            <span className="rounded-full bg-ac/20 px-[7px] py-px text-nhan text-panel-mint-2">
              Bất động sản
            </span>
          </span>
        </span>
        <span aria-hidden className="flex h-5 items-center gap-[2.5px]">
          {[0, 1, 2, 3, 4, 5, 6].map((i) => (
            <i
              key={i}
              className="song-tieng block h-full w-[2.5px] origin-center rounded-sm bg-live opacity-85"
              style={{ animationDelay: `${i * 95}ms` }}
            />
          ))}
        </span>
        <span className="font-mono text-[12px] tabular-nums text-panel-muted-2">{dongHo}</span>
      </figcaption>

      {/*
        Neo ĐÁY + chiều cao CỐ ĐỊNH. Cuộc gọi tự diễn nên nội dung cao dần; không
        ghim thì cả trang nhảy theo từng lượt. Neo đáy để lượt mới đẩy lượt cũ
        lên — đúng dáng một bản ghi đang chạy — và mask làm mép trên mờ đi thay
        vì cắt ngang chữ.
      */}
      <div
        className="flex h-[380px] flex-col justify-end gap-[13px] overflow-hidden px-4 py-[18px] lg:h-[430px]"
        style={{ maskImage: 'linear-gradient(to bottom, transparent 0, #000 52px)' }}
      >
        {CUOC_GOI.map((luot, i) =>
          // `display:none` chứ KHÔNG `opacity:0`: ẩn bằng opacity thì lượt chưa
          // tới vẫn giữ chỗ, thẻ há một khoảng trống bằng đúng phần còn lại và
          // hiệu ứng "lượt cũ trôi lên" không bao giờ xảy ra.
          i < hien ? (
            <div key={i} className="luot-vao grid grid-cols-[44px_1fr] items-start gap-[11px]">
              {luot.viec && (
                <div className="col-start-2 mb-[7px] flex flex-wrap gap-[5px]">
                  {luot.viec.map((v, j) => (
                    <span
                      key={v.nhan}
                      className={`chip-vao inline-flex items-center gap-1.5 rounded-full border px-[11px] py-[3px] text-[11.5px] ${
                        v.banGiao
                          ? 'border-panel-hophach-vien bg-panel-hophach/[0.06] text-panel-hophach'
                          : 'border-panel-raised-2 bg-white/[0.03] text-panel-mint'
                      }`}
                      style={{ animationDelay: `${j * 90 + 120}ms` }}
                    >
                      {v.nhan}
                      {v.chiTiet && <s className="no-underline text-panel-muted-2">{v.chiTiet}</s>}
                    </span>
                  ))}
                </div>
              )}
              <span
                className={`pt-0.5 text-right font-mono text-nhan leading-normal ${
                  luot.ai === 'agent' ? 'font-medium text-live' : 'text-panel-muted-2'
                }`}
              >
                {luot.ai === 'agent' ? ten : 'Khách'}
              </span>
              <p
                className={`text-[14px] leading-[1.55] ${
                  luot.ai === 'agent' ? 'text-n1' : 'text-panel-chu'
                }`}
              >
                {luot.loi}
              </p>
            </div>
          ) : null,
        )}

        {dangNghi && (
          <div aria-hidden className="col-start-2 flex h-5 items-center gap-1 pl-[55px]">
            {[0, 1, 2].map((i) => (
              <i
                key={i}
                className="dang-nghi size-[5px] rounded-full bg-panel-muted-2"
                style={{ animationDelay: `${i * 160}ms` }}
              />
            ))}
          </div>
        )}
      </div>

      <figcaption className="flex flex-wrap items-center gap-x-3.5 gap-y-2 border-t border-panel-line bg-white/[0.02] px-4 py-3 text-[12px] text-panel-muted">
        {KET_QUA.map((k, i) => (
          <i
            key={k.nhan}
            className={`not-italic transition-[opacity,transform] duration-[400ms] ease-[cubic-bezier(0.16,1,0.3,1)] ${
              i < ketQua ? 'translate-y-0 opacity-100' : 'translate-y-1 opacity-0'
            } ${k.tot ? 'text-live' : ''}`}
          >
            {k.nhan}
          </i>
        ))}
      </figcaption>
    </figure>
  )
}
