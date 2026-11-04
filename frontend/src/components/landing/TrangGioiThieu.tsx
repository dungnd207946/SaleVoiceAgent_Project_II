/**
 * Trang `/` — mặt tiền CÔNG KHAI, đứng ngoài `_app`.
 *
 * Ngoài `_app` nghĩa là ngoài `SessionProvider`: trang này phải render được khi
 * `GET /api/v1/me` trả 401, nên nó không đọc phiên, không gọi API, và mọi thứ
 * hiện ra là hằng số ở `duLieuMau.ts`.
 *
 * ── BA ĐIỀU TRANG NÀY KHÔNG ĐƯỢC NÓI ──────────────────────────────────────
 * ① Không gọi tên agent nào. `tenAgent` là cấu hình của từng workspace; tên
 *    trong bản ghi tự đổi mỗi vòng để nói điều đó bằng chuyển động.
 * ② Không khoá vào bất động sản. `nav-registry.ts` khai cả `bds` lẫn
 *    `taichinh`, và có màn «Quản lý lĩnh vực» bật/tắt từng khối — BĐS là lĩnh
 *    vực đang chạy, không phải phạm vi của sản phẩm. Cuộc gọi ở hero mang nhãn
 *    lĩnh vực để đọc ra là MỘT ví dụ.
 * ③ Không in tên hàm. AG_01 §II.3 — xem `lib/tools.ts`.
 *
 * Lĩnh vực Tài chính CỐ Ý không được quảng cáo: chưa có màn nào. Đưa lên trang
 * công khai là hứa thứ chưa có.
 */
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import { KhopTenDuAn } from './KhopTenDuAn'
import { TheCuocGoi } from './TheCuocGoi'
import { KY_NANG_BDS, KY_NANG_CHUNG, SO_KY_NANG } from './duLieuMau'

/** Hiện dần khi cuộn tới. IntersectionObserver, KHÔNG nghe sự kiện scroll.
 *  Người bật giảm chuyển động thấy nội dung NGAY (`motion-reduce:` ở `Hien`) — trước
 *  2026-10-05 sáu khối của trang đứng ẩn tới khi cuộn tới, kể cả với họ. */
function useHienDan<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [thay, datThay] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(
      ([en]) => {
        if (en?.isIntersecting) {
          datThay(true)
          io.disconnect()
        }
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.08 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return [ref, thay] as const
}

function Hien({ children, className = '' }: { children: ReactNode; className?: string }) {
  const [ref, thay] = useHienDan<HTMLDivElement>()
  return (
    <div
      ref={ref}
      className={`transition-[opacity,translate] duration-[650ms] ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:translate-y-0 motion-reduce:opacity-100 motion-reduce:transition-none ${
        thay ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0'
      } ${className}`}
    >
      {children}
    </div>
  )
}

const NUT =
  'inline-flex h-[42px] items-center justify-center rounded-full px-[22px] text-noi font-semibold transition active:translate-y-px'
const NUT_LON = 'h-12 px-6 text-the'
/** Hai nút của header ở điện thoại: cỡ desktop thì 390px không đủ chỗ cho logo + hai
 *  nút, và «Đăng ký»/«Đăng nhập» bẻ thành hai dòng ngay trong nút. */
const NUT_DAU_NHO = 'max-md:h-9 max-md:px-3.5 max-md:text-than'
/** Không nhãn nhỏ (kicker) phía trên — tiêu đề tự đứng được; ba nhãn mono VIẾT HOA
 *  «Ranh giới · Portal · Tiếng Việt» bỏ 2026-10-05 (quieter). */
const TIEU_DE =
  'max-w-[22ch] text-[clamp(27px,3.4vw,40px)] font-bold leading-[1.12] tracking-[-0.03em] text-balance'

export function TrangGioiThieu() {
  const hero = useRef<HTMLElement>(null)
  const [roiHero, datRoiHero] = useState(false)

  useEffect(() => {
    const el = hero.current
    if (!el) return
    // Quan sát CẢ khối hero, không phải một mốc mỏng cuối nó: mốc chỉ sinh
    // callback lúc vào và lúc ra viewport, nên cuộn tới giữa hero là không còn
    // sự kiện nào và thanh đứng nguyên màu cũ. Hero lại bắt đầu ngay đỉnh trang
    // nên không có tình huống "nằm dưới viewport".
    const io = new IntersectionObserver(([en]) => datRoiHero(!en?.isIntersecting), {
      rootMargin: '-68px 0px 0px 0px',
    })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  return (
    // KHÔNG `overflow-x-hidden` ở đây. `overflow-x: hidden` tính ra
    // `overflow-y: auto`, biến thẻ này thành scroll container — và `position:
    // sticky` của <header> sẽ dính vào NÓ chứ không vào viewport. Thẻ lại cao
    // bằng cả trang nên chẳng có gì để dính, thanh trôi mất khi cuộn (đo được
    // `top: -1254px`). Hero tự `overflow-hidden` rồi, nên dòng này chỉ còn là
    // cái bẫy.
    <div>
      {/* Còn ở hero ⇒ nền `panel` ĐẶC, không `panel/70`: header nằm trong luồng PHÍA TRÊN
          hero, nên ở đầu trang thứ nằm sau nó là nền sáng của body — 70% panel trên
          đó ra một dải xám #5e5f61 và chữ «Agent» chỉ còn 2,4:1 (audit 05/10). */}
      <header
        className={`sticky top-0 z-40 border-b backdrop-blur-[14px] transition-[background-color,border-color] duration-300 ${
          roiHero ? 'border-border bg-bg/85' : 'border-transparent bg-panel'
        }`}
      >
        <div className="mx-auto flex h-[68px] w-full max-w-[1240px] items-center gap-8 px-[clamp(20px,5vw,64px)] max-md:gap-3">
          <span className="mr-auto flex items-center gap-2.5 whitespace-nowrap">
            <img src="/favicon.svg" alt="" className="size-[30px]" />
            <span
              className={`text-the font-semibold tracking-[-0.015em] ${roiHero ? 'text-fg' : 'text-n1'}`}
            >
              NobleX{' '}
              <i
                className={`not-italic font-normal ${roiHero ? 'text-muted' : 'text-panel-muted'}`}
              >
                Agent
              </i>
            </span>
          </span>
          {/* Không có menu mục lục. Trang chỉ có bốn khối và người ta cuộn hết
              trong vài giây — một thanh mục lục ở đây chỉ chia sự chú ý với
              thứ DUY NHẤT header này tồn tại để nói. Các `id` của section vẫn
              giữ: hero còn trỏ tới `#ranh-gioi`, và link sâu vẫn dùng được. */}
          {/* «Đăng ký» là nút VIỀN, «Đăng nhập» giữ accent và đứng CUỐI — cùng
              luật hàng nút của portal (nút chính cuối hàng). Hai nút accent cạnh
              nhau thì không nút nào là nút chính nữa. Sắc viền phải đổi theo
              trạng thái thanh: nền hero tối dùng thang `panel-*`, sau khi rời
              hero nền sáng lại nên phải về `border`/`fg`, y như cụm chữ ở logo. */}
          <span className="flex items-center gap-2 whitespace-nowrap">
            <Link
              to="/dang-ky"
              className={`${NUT} ${NUT_DAU_NHO} border ${
                roiHero
                  ? 'border-border text-fg hover:border-muted'
                  : 'border-panel-line text-n1 hover:border-panel-muted'
              }`}
            >
              Đăng ký
            </Link>
            <Link to="/login" className={`${NUT} ${NUT_DAU_NHO} bg-ac text-white hover:bg-acd`}>
              Đăng nhập
            </Link>
          </span>
        </div>
      </header>

      {/* ── HERO ─────────────────────────────────────────────────────────
          Mặt TỐI duy nhất của cả portal, cố ý: thứ đang bán là cuộc gọi lúc
          11 giờ đêm. Tối một chỗ thì là chủ ý; tối cả trang thì là bộ theme
          thứ hai phải nuôi. */}
      <section ref={hero} className="relative overflow-hidden bg-panel text-n1">
        {/* Quầng sáng accent 800px sau thẻ cuộc gọi BỎ 2026-10-05 (quieter): trang trí
            thuần, và là đúng mẫu «spotlight glow» của UI máy sinh. Mặt tối tự đứng được. */}
        <div className="relative mx-auto grid w-full max-w-[1240px] gap-12 px-[clamp(20px,5vw,64px)] pb-[clamp(56px,8vw,96px)] pt-[clamp(48px,7vw,84px)] lg:grid-cols-[1fr_1.18fr] lg:items-center lg:gap-[60px]">
          <div>
            <span className="inline-flex items-center gap-2.5 rounded-full border border-panel-line py-[5px] pl-[11px] pr-[13px] text-phu text-panel-muted">
              <i className="tho-nhe size-[7px] shrink-0 rounded-full bg-live" /> Đang nghe máy
            </span>

            <h1 className="mt-5 text-[clamp(32px,4vw,46px)] font-semibold leading-[1.12] tracking-[-0.028em] text-balance">
              Khách gọi lúc 11 giờ đêm.
              <br />
              <em className="not-italic text-live">Có người nghe máy.</em>
            </h1>

            <p className="mt-[18px] max-w-[34ch] text-muc leading-[1.6] text-panel-chu-3">
              Agent tổng đài tiếng Việt — dạy theo lĩnh vực của bạn.
            </p>

            <div className="mt-7 flex flex-wrap gap-2.5">
              <Link to="/login" className={`${NUT} ${NUT_LON} bg-ac text-white hover:bg-acd`}>
                Đăng nhập portal
              </Link>
              <Link
                to="/dang-ky"
                className={`${NUT} ${NUT_LON} border border-panel-line text-n1 hover:border-panel-muted`}
              >
                Đăng ký
              </Link>
              {/*
                KHÔNG có nút «Nghe thử». Chưa có đường dẫn nào cho nó — một CTA
                trỏ vào `href="#"` trên trang bán hàng là cái bẫy đúng nghĩa.
                Ngày nào có số hotline demo hoặc form liên hệ thì thêm.
              */}
              <a
                href="#ranh-gioi"
                className={`${NUT} ${NUT_LON} border border-panel-line text-n1 hover:border-panel-muted`}
              >
                Xem agent làm gì
              </a>
            </div>

            <div className="mt-[30px] flex flex-wrap gap-2 border-t border-panel-line pt-6">
              {[
                [
                  'Điện thoại',
                  'M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2 4.2 2 2 0 0 1 4 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.1a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2Z',
                ],
                [
                  'Gọi trên web',
                  'M2 6a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6ZM2 9h20',
                ],
                [
                  'Chat',
                  'M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-4.2-1L3 20l1.2-4.4A8.4 8.4 0 0 1 3 11.5a8.4 8.4 0 0 1 9-8.4 8.4 8.4 0 0 1 9 8.4Z',
                ],
              ].map(([nhan, d]) => (
                <span
                  key={nhan}
                  className="inline-flex items-center gap-[7px] rounded-full bg-white/[0.045] py-1.5 pl-2.5 pr-3 text-phu text-panel-chu-3"
                >
                  <svg
                    aria-hidden
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="shrink-0 opacity-75"
                  >
                    <path d={d} />
                  </svg>
                  {nhan}
                </span>
              ))}
            </div>
          </div>

          <TheCuocGoi />
        </div>
      </section>

      {/* ── DẢI SỐ ───────────────────────────────────────────────────────
          Không có ô «<50ms». Đó là số đo của người viết mã; người mua không
          đo theo mili-giây và cũng không có cách nào kiểm nó. */}
      <div className="border-y border-border bg-surface">
        <div className="mx-auto grid w-full max-w-[1240px] gap-px bg-border sm:grid-cols-3">
          {[
            ['24/7', 'không có ca đêm, không có ngày lễ'],
            [String(SO_KY_NANG), 'việc agent làm được, bật tắt từng cái'],
            ['1', 'lối chuyển cho người thật'],
          ].map(([so, y]) => (
            <div key={so} className="bg-surface px-[clamp(16px,2.4vw,28px)] py-6">
              <b className="block font-mono text-[clamp(23px,2.8vw,30px)] font-medium tracking-[-0.02em]">
                {so}
              </b>
              <span className="mt-1.5 block text-phu text-muted">{y}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── RANH GIỚI ────────────────────────────────────────────────── */}
      <section id="ranh-gioi" className="scroll-mt-[84px] py-[clamp(60px,8vw,100px)]">
        <div className="mx-auto w-full max-w-[1240px] px-[clamp(20px,5vw,64px)]">
          <Hien>
            <h2 className={TIEU_DE}>Biết lúc nào phải chuyển máy</h2>
            {/* Phạm vi là trường CẤU HÌNH (`lamGi`/`khongLamGi` — đúng hai ô
                «Agent làm gì»/«Agent không làm gì» trong ảnh bên dưới). Không
                nói rõ thì hai danh sách này đọc thành luật cứng của sản phẩm. */}
            <p className="mt-3.5 max-w-[46ch] text-the leading-[1.6] text-muted">
              Phạm vi do bạn khai trong portal. Dưới đây là của An&nbsp;Phú&nbsp;Land.
            </p>
          </Hien>

          <Hien className="mt-11 grid gap-8 md:grid-cols-2 md:gap-0">
            <div className="md:border-r md:border-border md:pr-11">
              <h3 className="flex items-center gap-2.5 text-noi font-semibold">
                <svg
                  aria-hidden
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="shrink-0 text-ac"
                >
                  <path d="M20 6 9 17l-5-5" />
                </svg>
                Agent nhận
              </h3>
              <ul className="mt-[18px] flex flex-wrap gap-2">
                {[
                  'Nhận diện dự án',
                  'Tra giỏ hàng đang mở bán',
                  'Gợi ý căn hợp mệnh',
                  'Gửi mặt bằng, ảnh, tài liệu',
                  'Đặt lịch tham quan',
                  'Ghi nhận thông tin khách',
                ].map((x) => (
                  <li
                    key={x}
                    className="rounded-full border border-border bg-surface px-3.5 py-2 text-than text-fg"
                  >
                    {x}
                  </li>
                ))}
              </ul>
            </div>

            <div className="md:pl-11">
              <h3 className="flex items-center gap-2.5 text-noi font-semibold">
                <svg
                  aria-hidden
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="shrink-0 text-badge-warn-fg"
                >
                  <path d="M7 17 17 7M17 7h-6M17 7v6" />
                </svg>
                Chuyển người thật
              </h3>
              <ul className="mt-[18px] flex flex-wrap gap-2">
                {['Giá nội bộ · chiết khấu', 'Khách đã mua', 'Khách đòi gặp người'].map((x) => (
                  <li
                    key={x}
                    className="rounded-full border border-badge-warn-nhat-vien bg-badge-warn-nhat-bg px-3.5 py-2 text-than text-badge-warn-fg"
                  >
                    {x}
                  </li>
                ))}
              </ul>
              <p className="mt-[22px] text-than leading-[1.55] text-muted">
                Chỉ có một lối chuyển, và nó chuyển thẳng. Khách không bị đá qua ba câu hỏi sàng lọc
                rồi phải kể lại câu chuyện từ đầu.
              </p>
            </div>
          </Hien>
        </div>
      </section>

      {/* ── CẤU HÌNH — ảnh chụp THẬT từ portal ───────────────────────── */}
      <section
        id="cau-hinh"
        className="scroll-mt-[84px] border-y border-border bg-surface py-[clamp(60px,8vw,100px)]"
      >
        <div className="mx-auto w-full max-w-[1240px] px-[clamp(20px,5vw,64px)]">
          <Hien>
            <h2 className={TIEU_DE}>Tên, phạm vi, lĩnh vực — bạn đặt</h2>
          </Hien>

          <div className="mt-11 grid items-start gap-11 lg:grid-cols-[1.25fr_1fr] lg:gap-14">
            <Hien>
              {/*
                Cắt cụt ở ĐÁY, cố ý — màn hình đọc thành "còn tiếp" chứ không
                phải một tấm ảnh dán vào trang. `aspect-ratio` chứ không
                `max-height` cứng: vòng nhấn định vị bằng %, mà % tính theo
                KHUNG — khung cao cố định thì tỉ lệ đổi theo bề rộng màn hình và
                vòng nhấn trôi khỏi ô nó phải chỉ.
              */}
              <div className="relative aspect-[1132/780] overflow-hidden rounded-t-lg border border-b-0 border-border bg-surface">
                <img
                  src="/anh-cau-hinh-agent.png"
                  alt="Màn Cấu hình chung của portal: tên agent, tên thương hiệu, phạm vi, giọng điệu và rào chắn"
                  className="block w-full"
                />
                <span
                  aria-hidden
                  className="nhan-manh absolute left-[3.4%] top-[19.2%] h-[7.1%] w-[13%] rounded-sm border-2 border-ac bg-ac/[0.07]"
                >
                  <span className="absolute left-[calc(100%+10px)] top-1/2 -translate-y-1/2 whitespace-nowrap rounded-full bg-ac px-2.5 py-1 font-mono text-nhan text-white">
                    tên do bạn đặt
                  </span>
                </span>
                {/* Mờ dần ở mép cắt — cắt phẳng trông như ảnh tải lỗi. */}
                <span
                  aria-hidden
                  className="pointer-events-none absolute inset-x-0 bottom-0 h-[88px]"
                  style={{ background: 'linear-gradient(to bottom, transparent, var(--color-n1))' }}
                />
              </div>
            </Hien>

            <Hien>
              <h3 className="text-noi font-semibold">Kỹ năng — bật cái nào là quyền của bạn</h3>

              <p className="mt-[22px] text-phu font-medium text-muted">Chung cho mọi lĩnh vực</p>
              <BangKyNang muc={KY_NANG_CHUNG} />

              <p className="mt-[22px] text-phu font-medium text-muted">
                Lĩnh vực <b className="font-semibold text-ac">Bất động sản</b>
              </p>
              <BangKyNang muc={KY_NANG_BDS.map((nhan) => ({ nhan, bat: true }))} />

              <p className="mt-4 text-[13px] leading-[1.55] text-muted">
                Thêm một lĩnh vực là thêm một khối như thế — không phải dựng lại agent từ đầu.
              </p>
            </Hien>
          </div>
        </div>
      </section>

      {/* ── TIẾNG VIỆT ───────────────────────────────────────────────── */}
      <section id="tieng-viet" className="scroll-mt-[84px] py-[clamp(60px,8vw,100px)]">
        <div className="mx-auto grid w-full max-w-[1240px] items-center gap-10 px-[clamp(20px,5vw,64px)] lg:grid-cols-[1fr_1.05fr] lg:gap-16">
          <Hien>
            <h2 className={TIEU_DE}>Khách nói kiểu gì cũng ra đúng dự án</h2>
            <p className="mt-4 max-w-[40ch] text-[15.5px] leading-[1.6] text-muted">
              Nói tắt, nói sai tên, giọng vùng nào cũng ra đúng thứ khách đang hỏi. Không chắc thì
              hỏi lại, không đoán bừa.
            </p>
          </Hien>
          <Hien>
            <KhopTenDuAn />
          </Hien>
        </div>
      </section>

      <section className="bg-panel text-n1">
        <div className="mx-auto grid w-full max-w-[1240px] items-end gap-[30px] px-[clamp(20px,5vw,64px)] py-[clamp(60px,8vw,96px)] md:grid-cols-[1fr_auto] md:gap-14">
          <h2 className={`${TIEU_DE} text-n1`}>Đêm nay vẫn có người gọi</h2>
          <div className="flex flex-wrap gap-2.5">
            <Link to="/login" className={`${NUT} ${NUT_LON} bg-ac text-white hover:bg-acd`}>
              Đăng nhập portal
            </Link>
            <Link
              to="/dang-ky"
              className={`${NUT} ${NUT_LON} border border-panel-line text-n1 hover:border-panel-muted`}
            >
              Đăng ký
            </Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-panel-line bg-panel text-panel-muted">
        <div className="mx-auto flex w-full max-w-[1240px] flex-wrap items-center gap-x-7 gap-y-3.5 px-[clamp(20px,5vw,64px)] py-[26px] text-phu">
          <span>NobleX Agent · Odyssey</span>
          <span className="ml-auto font-mono">agents.noblex.vn</span>
        </div>
      </footer>
    </div>
  )
}

function BangKyNang({ muc }: { muc: readonly { nhan: string; bat: boolean }[] }) {
  const [ref, thay] = useHienDan<HTMLUListElement>()
  return (
    <ul ref={ref} className="mt-2 border-t border-border">
      {muc.map((m, i) => (
        <li
          key={m.nhan}
          className="flex items-center gap-3 border-b border-border py-[9px] text-than text-fg"
        >
          <span
            className={`relative h-[18px] w-[30px] shrink-0 rounded-full transition-colors duration-[340ms] ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none ${
              thay && m.bat ? 'bg-ac' : 'bg-border-strong'
            }`}
            style={{ transitionDelay: `${i * 85}ms` }}
          >
            {/* Tailwind v4 phát ra thuộc tính `translate`, không phải `transform`. */}
            <span
              className={`absolute left-0.5 top-0.5 size-[14px] rounded-full bg-white shadow-num transition-[translate] duration-[340ms] ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none ${
                thay && m.bat ? 'translate-x-3' : ''
              }`}
              style={{ transitionDelay: `${i * 85}ms` }}
            />
          </span>
          {m.nhan}
        </li>
      ))}
    </ul>
  )
}
