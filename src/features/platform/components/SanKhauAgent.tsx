/**
 * «Sân khấu» phía trên khung hội thoại của tab Voice (`/thu-agent`): một ẢNH
 * NỀN phủ kín + một NGƯỜI DẪN đứng góc dưới bên phải, mấp máy môi khi agent
 * phát tiếng và đứng yên khi im.
 *
 * - **Nền mặc định** là phông studio trung tính vẽ bằng CSS (`phong-san-khau`
 *   + quầng sáng `quang-nguoi-dan` bám theo người dẫn) — ảnh dự án cố định bỏ
 *   2026-10-07: sai với mọi workspace khác. Agent gửi ảnh (`send_media`) thì
 *   album mở đè lên, và `anhNen` = ảnh đang hiện của album (nền mờ phía sau).
 *   Ảnh mới TẢI XONG mới hiện, mờ dần đè lên ảnh cũ (`NenSanKhau`).
 * - **Người dẫn** đọc tín hiệu tiếng agent qua `tinHieuRef` (không qua state/
 *   prop số): mức loa + số giây audio còn trong hàng đợi + lượt đang mở; đổi
 *   ~12 lần/giây, đẩy nó qua state là vẽ lại cả `CheGiongNoi` — gồm
 *   toàn bộ danh sách tin nhắn — 12 lần/giây chỉ để một khung hình biết.
 *
 * Toàn bộ quyết định "nói/im, tua về đâu" nằm ở `nguoiDan.ts` (thuần, có test);
 * tệp này chỉ THI HÀNH lệnh và vẽ.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  buocVideo,
  daNhay,
  datGioTay,
  DOAN,
  giayVeNghi,
  FPS,
  khung as giayCuaKhung,
  khungCua,
  taoBoDoNoi,
  TOC_DO,
  TOC_NGHI,
  TIN_HIEU_IM,
  TRANG_DAU,
  type TinHieuLoa,
  type TrangVideo,
} from '../nguoiDan'
import { ANH_CHO_AVATAR, urlAvatar, type VeAvatar } from '../avatarLipSync'
import { cachHien, kcVong, kieuThe, THOI_GIAN_DOI_ANH_MS } from '../sanKhau'
import { giamChuyenDong } from '@/lib/giamChuyenDong'

interface LopNen {
  /** `null` = phông studio (CSS), không phải ảnh. */
  readonly u: string | null
  /** Kích thước thật của ảnh — 0 khi chưa tải xong. */
  readonly w: number
  readonly h: number
}

/** Clip «stacked alpha»: nửa trên là hình màu đã nhân alpha trên nền đen, nửa
 *  dưới là mặt nạ trắng/đen. MP4 không có kênh trong suốt, nên ghép alpha
 *  phải tự làm lúc vẽ — xem shader dưới.
 *  Sinh từ HAI clip Kling (`video1_only_speak.mp4` nói · `video_2_hand_raise.mp4`
 *  đưa tay — nền phòng thật) bằng BiRefNet-portrait từng khung + làm mượt
 *  mặt nạ theo thời gian chỉ ở chỗ đứng yên; rồi DỰNG thành 410 khung theo
 *  bố cục `DOAN` ở `nguoiDan.ts` (`-g 4` để tua nhanh). */
const VIDEO_NGUOI_DAN = '/nguoi-dan.mp4'
/** Khung chờ (vị trí 0 = clip nói khung 0 = ảnh gốc của Kling) đã ghép alpha
 *  sẵn — poster lúc video chưa tải xong, và là TOÀN BỘ người dẫn trên máy
 *  không có WebGL (đứng yên). Sinh lại từ CHÍNH vị trí 0 nếu dựng lại tệp:
 *  poster và khung chờ lệch nhau là một cú nhảy ngay lúc video tải xong. */
const ANH_NGUOI_DAN_NGHI = '/nguoi-dan-nghi.webp'
const RONG = 628
const CAO = 1000
/** Khung người dẫn (cỡ theo `cqw` — lý do ở `NguoiDan`) — dùng chung với quầng
 *  sáng phía sau để hai thứ không bao giờ lệch nhau. */
const KHUNG_NGUOI_DAN = 'absolute bottom-0 right-[3%] aspect-[628/1000] h-[min(92%,54.7cqw)]'

/** Ngưỡng tính theo `mucRms` (đã ×4): giọng TTS thường 0.2–0.8, tiếng ồn nền
 *  của buffer rỗng là 0 tròn. 0.04 bắt được cả âm cuối nhỏ mà không bắt nhiễu. */
const NGUONG_NOI = 0.04
/** Chỉ dùng khi gateway KHÔNG gửi sự kiện lượt (bản cũ): khi đó chỉ còn mức
 *  loa để đoán, phải chờ một khoảng lặng đủ dài mới dám coi là im. */
const GIU_NOI_MS = 800
/** Lượt còn mở thì bắc cầu khoảng lặng giữa hai câu tới chừng này (audio về
 *  theo từng câu, giữa câu hàng đợi có thể cạn vài trăm ms). */
const GIU_GIUA_CAU_MS = 1_500

const DINH = `
attribute vec2 p;
varying vec2 uv;
void main() {
  uv = vec2((p.x + 1.0) * 0.5, (1.0 - p.y) * 0.5);
  gl_Position = vec4(p, 0.0, 1.0);
}`
// Màu nửa trên vốn đã ghép lên nền ĐEN — tức là màu đã premultiply sẵn —
// nên xuất thẳng (rgb, a) cho canvas premultipliedAlpha, không chia lại cho a.
// `min(c, a)` chặn viền: chỗ mặt nạ mờ hơn màu (nén lệch) sẽ loé sáng.
// Kẹp y màu dưới 0.5 nửa texel để lọc tuyến tính không hút mép mặt nạ lên.
// `vien`: mờ dần 3% sát mép trái/phải + 2% mép trên — clip gốc cắt cụt đầu
// ngón tay lúc đưa tay giới thiệu và mặt nạ có vài chấm nhiễu ở hàng trên
// cùng; không mờ thì hiện thành một vết cắt thẳng giữa sân khấu.
// HAI luồng `texA`/`texB` hoà theo `k` (0 = chỉ A): trộn trên giá trị ĐÃ
// premultiply nên một pixel trong suốt ở luồng này không kéo màu đen vào
// luồng kia — trộn trước khi nhân alpha là thấy viền tối loé ở mép tóc.
const MANH = `
precision mediump float;
uniform sampler2D texA;
uniform sampler2D texB;
uniform float k;
varying vec2 uv;
vec4 lay(sampler2D t) {
  float yMau = min(uv.y * 0.5, 0.5 - 0.5 / ${CAO * 2}.0);
  vec3 c = texture2D(t, vec2(uv.x, yMau)).rgb;
  float a = texture2D(t, vec2(uv.x, 0.5 + uv.y * 0.5)).r;
  float vien = smoothstep(0.0, 0.03, uv.x) * smoothstep(0.0, 0.03, 1.0 - uv.x) * smoothstep(0.0, 0.02, uv.y);
  a *= vien;
  return vec4(min(c * vien, vec3(a)), a);
}
void main() {
  gl_FragColor = k > 0.0 ? mix(lay(texA), lay(texB), k) : lay(texA);
}`

function coWebGl(): boolean {
  return typeof window !== 'undefined' && typeof window.WebGLRenderingContext !== 'undefined'
}

type Ve = (a: HTMLVideoElement, b: HTMLVideoElement | null, k: number) => void

/** Dựng WebGL cho canvas. `null` ⇒ không dùng được (người gọi rơi về ảnh tĩnh). */
function dungVe(canvas: HTMLCanvasElement): Ve | null {
  const gl = canvas.getContext('webgl', { premultipliedAlpha: true, alpha: true, antialias: false })
  if (!gl) return null

  function bien(loai: number, nguon: string): WebGLShader | null {
    const s = gl!.createShader(loai)
    if (!s) return null
    gl!.shaderSource(s, nguon)
    gl!.compileShader(s)
    return gl!.getShaderParameter(s, gl!.COMPILE_STATUS) ? s : null
  }
  const vs = bien(gl.VERTEX_SHADER, DINH)
  const fs = bien(gl.FRAGMENT_SHADER, MANH)
  const ct = gl.createProgram()
  if (!vs || !fs || !ct) return null
  gl.attachShader(ct, vs)
  gl.attachShader(ct, fs)
  gl.linkProgram(ct)
  if (!gl.getProgramParameter(ct, gl.LINK_STATUS)) return null
  gl.useProgram(ct)

  const dem = gl.createBuffer()
  gl.bindBuffer(gl.ARRAY_BUFFER, dem)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
  const viTri = gl.getAttribLocation(ct, 'p')
  gl.enableVertexAttribArray(viTri)
  gl.vertexAttribPointer(viTri, 2, gl.FLOAT, false, 0, 0)

  // Texture không phải luỹ thừa 2 (720×1464) — WebGL1 chỉ nhận khi CLAMP +
  // không mipmap; thiếu một trong hai là texture đen trơn, không báo lỗi.
  function taoTex(don: number): WebGLTexture | null {
    gl!.activeTexture(gl!.TEXTURE0 + don)
    const t = gl!.createTexture()
    gl!.bindTexture(gl!.TEXTURE_2D, t)
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_WRAP_S, gl!.CLAMP_TO_EDGE)
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_WRAP_T, gl!.CLAMP_TO_EDGE)
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MIN_FILTER, gl!.LINEAR)
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MAG_FILTER, gl!.LINEAR)
    return t
  }
  const texA = taoTex(0)
  const texB = taoTex(1)
  gl.uniform1i(gl.getUniformLocation(ct, 'texA'), 0)
  gl.uniform1i(gl.getUniformLocation(ct, 'texB'), 1)
  const viTriK = gl.getUniformLocation(ct, 'k')
  gl.viewport(0, 0, RONG, CAO)
  gl.clearColor(0, 0, 0, 0)

  return (a, b, k) => {
    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, texA)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, a)
    // Ngoài lúc hoà trộn thì không upload luồng thứ hai — một texture 720×1464
    // mỗi khung là thứ tốn nhất của cả vòng vẽ.
    if (b) {
      gl.activeTexture(gl.TEXTURE1)
      gl.bindTexture(gl.TEXTURE_2D, texB)
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, b)
    }
    gl.uniform1f(viTriK, b ? k : 0)
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
  }
}

/** Nửa khung — sai số chấp nhận được khi so `currentTime` với một mốc. */
const NUA_KHUNG = 0.5 / FPS

function NguoiDan({
  video,
  tinHieuRef,
  lenhGioTay,
  tuDongGioTay,
}: {
  video: boolean
  tinHieuRef: React.MutableRefObject<TinHieuLoa>
  lenhGioTay: number
  tuDongGioTay: boolean
}) {
  // Prop đổi giữa các lần vẽ, còn vòng rAF thì sống suốt — đọc qua ref để
  // vòng không phải dựng lại (dựng lại là mất trạng thái clip đang chạy).
  const lenhRef = useRef(lenhGioTay)
  lenhRef.current = lenhGioTay
  const tuDongRef = useRef(tuDongGioTay)
  tuDongRef.current = tuDongGioTay
  const videoA = useRef<HTMLVideoElement>(null)
  const videoB = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  // Giảm chuyển động ⇒ đứng ảnh tĩnh như máy không có WebGL: vòng vẽ người dẫn chạy
  // mãi không có nút dừng (WCAG 2.2.2), và nhờ vậy cũng không tải video (tệp 4,65 MB,
  // hai `<video>` cùng tải ⇒ đo được 8–9 MB qua mạng). `video={false}` (sân khấu
  // chờ trước Áp dụng) cũng đứng ảnh tĩnh.
  const [mayVeDuoc] = useState(() => coWebGl() && !giamChuyenDong())
  const veDuoc = video && mayVeDuoc
  // Canvas chỉ hiện khi ĐÃ vẽ được khung đầu — trước đó là ảnh poster, không
  // phải một ô trong suốt trống rồi người dẫn đột ngột hiện ra.
  const [daVe, setDaVe] = useState(false)
  const [dangNoi, setDangNoi] = useState(false)

  useEffect(() => {
    const a = videoA.current
    const b = videoB.current
    const canvas = canvasRef.current
    if (!veDuoc || !a || !b || !canvas) return
    const ve = dungVe(canvas)
    if (!ve) return

    // HAI video cùng một tệp: một cái đang HIỆN (`chinh`), cái kia tua SẴN
    // tới đích của kế hoạch kế tiếp. Tới đúng khung thì đổi TỨC THÌ — đích luôn
    // là khung KỀ khung đang hiện (xem docstring `nguoiDan.ts`), nên không
    // cần và không được hoà trộn.
    const vs = [a, b] as const
    let chinh = 0
    const doNoi = taoBoDoNoi({
      nguong: NGUONG_NOI,
      giuMs: GIU_NOI_MS,
      giuGiuaCauMs: GIU_GIUA_CAU_MS,
    })
    let trang: TrangVideo = TRANG_DAU
    let lenhDaNhan = lenhRef.current
    let tocHien = TOC_NGHI
    let canVe = true
    // Khung video đã lên canvas lần cuối. Vòng rAF chạy theo nhịp MÀN HÌNH
    // (60–120 lần/giây) còn video chỉ ra ~11 khung/giây lúc chờ (24 fps × 0,45)
    // — upload lại cùng một texture 628×2000 mỗi nhịp là phần đắt nhất mà vô ích.
    // Không dùng `requestVideoFrameCallback`: video ở đây `display:none`, và
    // trình duyệt nào không báo khung cho video ẩn thì người dẫn đứng hình.
    let khungDaVe = -1
    let noiTruoc = false
    let khung = 0

    const phu = () => vs[1 - chinh] as HTMLVideoElement
    const hien = () => vs[chinh] as HTMLVideoElement
    const dungO = (v: HTMLVideoElement, n: number) =>
      !v.seeking && v.readyState >= 2 && Math.abs(v.currentTime - giayCuaKhung(n)) <= NUA_KHUNG

    const danhDauVe = () => (canVe = true)
    for (const v of vs) {
      v.addEventListener('seeked', danhDauVe)
      v.addEventListener('loadeddata', danhDauVe)
      // `defaultPlaybackRate` để lần nạp lại nguồn (trình duyệt tự làm khi
      // thiếu bộ nhớ) không trả tốc độ về 1.
      v.defaultPlaybackRate = tocHien
      v.playbackRate = tocHien
    }
    a.currentTime = giayCuaKhung(DOAN.fDau)
    b.currentTime = giayCuaKhung(DOAN.rDau)

    const nhip = () => {
      const bayGio = performance.now()
      const noi = doNoi(tinHieuRef.current, bayGio, giayVeNghi(khungCua(hien().currentTime)))
      if (noi !== noiTruoc) {
        noiTruoc = noi
        setDangNoi(noi)
      }
      if (lenhRef.current !== lenhDaNhan) {
        lenhDaNhan = lenhRef.current
        trang = datGioTay(trang)
      }
      if (trang.tuDongGioTay !== tuDongRef.current)
        trang = { ...trang, tuDongGioTay: tuDongRef.current }
      const v = hien()
      const r = buocVideo(trang, khungCua(v.currentTime), noi, bayGio)
      trang = r.trang
      // Chờ thì chậm (nhịp thở), nói thì gần nguyên tốc — đổi cho CẢ HAI video
      // để lần đổi video kế tiếp không nhảy tốc độ.
      const toc = trang.cheDo === 'nghi' ? TOC_NGHI : TOC_DO
      if (toc !== tocHien) {
        tocHien = toc
        for (const x of vs) {
          x.defaultPlaybackRate = toc
          x.playbackRate = toc
        }
      }
      const kh = trang.keHoach
      // Có kế hoạch mà video đang dừng nghĩa là nó đang GIỮ khung chờ video
      // phụ tua xong — đừng cho chạy tiếp qua khung `tai`.
      if (r.phat && v.paused && !kh) void v.play().catch(() => {})

      if (kh) {
        const p = phu()
        if (!p.seeking && Math.abs(p.currentTime - giayCuaKhung(kh.toi)) > NUA_KHUNG) {
          p.pause()
          p.currentTime = giayCuaKhung(kh.toi)
        }
        // Tới lúc khung `tai` vừa hiện xong (đầu khung kế tiếp) ⇒ đổi. Video
        // phụ chưa tua xong thì GIỮ khung `tai` chờ — một khung đứng thêm vài
        // chục ms khó thấy hơn một khung lạ chen vào.
        if (v.ended || v.currentTime >= (kh.tai + 1) / FPS - 0.004) {
          if (dungO(p, kh.toi)) {
            v.pause()
            chinh = 1 - chinh
            if (kh.phat) void p.play().catch(() => {})
            trang = daNhay(trang)
            canVe = true
          } else v.pause()
        }
      }

      const h = hien()
      const n = khungCua(h.currentTime)
      if (h.readyState >= 2 && (canVe || n !== khungDaVe)) {
        canVe = false
        khungDaVe = n
        ve(h, null, 0)
        setDaVe(true)
      }
      khung = requestAnimationFrame(nhip)
    }
    khung = requestAnimationFrame(nhip)

    // Tab ẩn: rAF tự dừng nhưng video vẫn giải mã. Dừng đúng những video đang
    // chạy rồi chạy lại chúng khi quay về — không `play()` cả hai, video đang
    // GIỮ khung chờ video phụ tua (xem `kh` ở trên) phải đứng yên.
    const dungKhiAn = new Set<HTMLVideoElement>()
    const doiHien = () => {
      if (document.hidden) {
        for (const v of vs)
          if (!v.paused) {
            v.pause()
            dungKhiAn.add(v)
          }
      } else {
        for (const v of dungKhiAn) void v.play().catch(() => {})
        dungKhiAn.clear()
      }
    }
    document.addEventListener('visibilitychange', doiHien)

    return () => {
      cancelAnimationFrame(khung)
      document.removeEventListener('visibilitychange', doiHien)
      for (const v of vs) {
        v.removeEventListener('seeked', danhDauVe)
        v.removeEventListener('loadeddata', danhDauVe)
        v.pause()
      }
    }
  }, [veDuoc, tinHieuRef])

  return (
    <div
      data-testid="nguoi-dan"
      data-dang-noi={dangNoi ? '1' : '0'}
      // Cỡ theo BỀ NGANG khung (`cqw`), không theo chiều cao: desktop kéo sân
      // khấu cao kín cột (2026-10-02) mà người dùng đã chốt «đừng cho nhân vật
      // to quá» (2026-10-01). 54,7cqw = đúng 82% chiều cao của khung 3:2 cũ ⇒
      // ở 3:2 không đổi một pixel; khung thấp hơn 3:2 thì kẹp 92% chiều cao.
      // `pointer-events-none`: vuốt chuyển ảnh album phải bắt được cả khi ngón
      // tay đặt lên người dẫn — trên điện thoại cô ấy chiếm gần nửa khung.
      className={`${KHUNG_NGUOI_DAN} pointer-events-none ${dangNoi ? '' : 'nguoi-dan-tho'}`}
    >
      {/* KHÔNG lật gương: clip này đưa tay sang TRÁI khung hình — đã hướng
          về màn chiếu bên trái sân khấu. (Clip cũ đưa tay sang phải nên từng
          phải `-scale-x-100`; đổi clip thì xem lại hướng tay.) */}
      <img
        src={ANH_NGUOI_DAN_NGHI}
        alt=""
        className={`absolute inset-0 size-full ${daVe ? 'invisible' : ''}`}
      />
      {veDuoc && (
        <>
          <canvas
            ref={canvasRef}
            width={RONG}
            height={CAO}
            className={`absolute inset-0 size-full ${daVe ? '' : 'invisible'}`}
          />
          {[videoA, videoB].map((ref, i) => (
            <video
              key={i}
              ref={ref}
              src={VIDEO_NGUOI_DAN}
              muted
              playsInline
              preload="auto"
              className="hidden"
            />
          ))}
        </>
      )}
    </div>
  )
}

// Một texture «stacked alpha» (nửa trên màu đã nhân alpha, nửa dưới mặt nạ) —
// cùng định dạng `MANH` ở trên nhưng frame đến từ avatar service dạng ảnh
// (ImageBitmap), không qua hai <video>. Kẹp y màu dưới 0.5 nửa texel như trên.
const MANH_LIP = `
precision mediump float;
uniform sampler2D tex;
uniform float caoTexel;
varying vec2 uv;
void main() {
  float yMau = min(uv.y * 0.5, 0.5 - 0.5 * caoTexel);
  vec3 c = texture2D(tex, vec2(uv.x, yMau)).rgb;
  float a = texture2D(tex, vec2(uv.x, 0.5 + uv.y * 0.5)).r;
  float vien = smoothstep(0.0, 0.03, uv.x) * smoothstep(0.0, 0.03, 1.0 - uv.x) * smoothstep(0.0, 0.02, uv.y);
  a *= vien;
  gl_FragColor = vec4(min(c * vien, vec3(a)), a);
}`

/** Dựng WebGL vẽ frame lip sync. `null` ⇒ không dùng được (giữ ảnh chờ). */
function dungVeLip(canvas: HTMLCanvasElement): VeAvatar | null {
  const gl = canvas.getContext('webgl', { premultipliedAlpha: true, alpha: true, antialias: false })
  if (!gl) return null
  const bien = (loai: number, nguon: string): WebGLShader | null => {
    const sh = gl.createShader(loai)
    if (!sh) return null
    gl.shaderSource(sh, nguon)
    gl.compileShader(sh)
    return gl.getShaderParameter(sh, gl.COMPILE_STATUS) ? sh : null
  }
  const vs = bien(gl.VERTEX_SHADER, DINH)
  const fs = bien(gl.FRAGMENT_SHADER, MANH_LIP)
  const ct = gl.createProgram()
  if (!vs || !fs || !ct) return null
  gl.attachShader(ct, vs)
  gl.attachShader(ct, fs)
  gl.linkProgram(ct)
  if (!gl.getProgramParameter(ct, gl.LINK_STATUS)) return null
  gl.useProgram(ct)
  const dem = gl.createBuffer()
  gl.bindBuffer(gl.ARRAY_BUFFER, dem)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
  const viTri = gl.getAttribLocation(ct, 'p')
  gl.enableVertexAttribArray(viTri)
  gl.vertexAttribPointer(viTri, 2, gl.FLOAT, false, 0, 0)
  const tex = gl.createTexture()
  gl.bindTexture(gl.TEXTURE_2D, tex)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
  gl.uniform1i(gl.getUniformLocation(ct, 'tex'), 0)
  const caoTexel = gl.getUniformLocation(ct, 'caoTexel')
  gl.clearColor(0, 0, 0, 0)
  return (anh) => {
    const w = anh.width
    const h = anh.height / 2
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w
      canvas.height = h
    }
    gl.viewport(0, 0, w, h)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, anh)
    gl.uniform1f(caoTexel, 1 / anh.height)
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
  }
}

/**
 * Người dẫn LIP SYNC thật (MuseTalk) — thay `NguoiDan` khi có
 * `VITE_AVATAR_WS_URL`. Component này KHÔNG tự nối gì: nó chỉ đăng ký hàm vẽ
 * vào `veRef`, còn `giongNoi.ts` + `avatarLipSync.ts` quyết frame nào vẽ lúc
 * nào theo đồng hồ âm thanh. Chưa có frame (chưa gọi / service tắt) ⇒ ảnh chờ.
 */
function NguoiDanLipSync({
  veRef,
  anhCho = ANH_CHO_AVATAR,
}: {
  veRef: React.MutableRefObject<VeAvatar | null> | undefined
  /** Ảnh chờ (poster) của nhân vật đang dùng — mặc định là người dẫn có sẵn. */
  anhCho?: string | undefined
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [daVe, setDaVe] = useState(false)
  // Tỉ lệ khung theo CHÍNH ảnh chờ (cùng cỡ frame avatar service gửi) — đổi
  // nhân vật là đổi ảnh, không phải sửa số ở đây. Mặc định = người dẫn hiện
  // tại 628×1000 (cũng là số `RONG_THE` của album đang canh theo).
  const [tiLe, setTiLe] = useState(RONG / CAO)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!veRef || !canvas || !coWebGl()) return
    const ve = dungVeLip(canvas)
    if (!ve) return
    let dau = true
    veRef.current = (anh) => {
      ve(anh)
      if (dau) {
        dau = false
        setDaVe(true)
      }
    }
    return () => {
      veRef.current = null
    }
  }, [veRef])
  return (
    <div
      data-testid="nguoi-dan"
      data-lip-sync="1"
      className="pointer-events-none absolute bottom-0 right-[3%] h-[min(92%,54.7cqw)]"
      style={{ aspectRatio: tiLe }}
    >
      <img
        src={anhCho}
        alt=""
        onLoad={(e) => {
          const { naturalWidth: w, naturalHeight: h } = e.currentTarget
          if (w > 0 && h > 0) setTiLe(w / h)
        }}
        className={`absolute inset-0 size-full ${daVe ? 'invisible' : ''}`}
      />
      <canvas ref={canvasRef} className={`absolute inset-0 size-full ${daVe ? '' : 'invisible'}`} />
    </div>
  )
}

/**
 * Nền sân khấu, đổi ảnh KHÔNG để lộ khoảng trống: ảnh mới tải ngầm, tải xong
 * mới chồng lên ảnh đang hiện và mờ dần vào (`nen-vao`); ảnh cũ nằm dưới cho
 * tới lần đổi sau. Ảnh lỗi (link chết, CORS…) ⇒ giữ nguyên nền đang có.
 * Bản đầu đổi `src` thẳng: ảnh từ xa chưa tải xong thì sân khấu trống trơn
 * một nhịp, rồi ảnh hiện giật từng dải.
 */
function NenSanKhau({ anh, mo }: { anh: string | null; mo: boolean }) {
  // Mới nhất cuối mảng; giữ tối đa HAI lớp (đang hiện + đang mờ vào). Mỗi lớp
  // nhớ kích thước thật của ảnh để chọn cách hiện (xem `cachHien`).
  const [lop, setLop] = useState<readonly LopNen[]>([{ u: anh, w: 0, h: 0 }])
  const khungRef = useRef<HTMLDivElement>(null)
  const [khung, setKhung] = useState({ w: 0, h: 0 })
  useEffect(() => {
    const el = khungRef.current
    if (!el) return
    const do_ = () => setKhung({ w: el.clientWidth, h: el.clientHeight })
    do_()
    const ro = new ResizeObserver(do_)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  useEffect(() => {
    const chong = (moi: LopNen) =>
      setLop((c) => (c[c.length - 1]?.u === anh ? [...c.slice(0, -1), moi] : [...c.slice(-1), moi]))
    // Phông không phải tải ⇒ mờ vào ngay (album đóng thì nó phủ dần lên ảnh cuối).
    if (anh === null) {
      chong({ u: null, w: 0, h: 0 })
      return
    }
    let huy = false
    const im = new Image()
    im.onload = () => {
      if (!huy) chong({ u: anh, w: im.naturalWidth, h: im.naturalHeight })
    }
    im.src = anh
    return () => {
      huy = true
    }
  }, [anh])
  // Mỗi lớp = ảnh NÉT + (khi «contain») chính ảnh đó phủ kín, làm mờ, phía sau
  // để lấp phần trống. Bản đầu chỉ `object-cover`: sân khấu desktop ~1240×360
  // (≈ 3,4:1) mà ảnh nền 600×400 (3:2) ⇒ ảnh bị phóng ×2 chiều ngang rồi cắt
  // mất phần lớn chiều dọc — mờ và mất nội dung; chỉ mobile (khung gần 3:2)
  // mới nét. Ảnh agent gửi cũng đủ loại tỉ lệ ⇒ chọn THEO TỪNG ẢNH × KHUNG.
  return (
    <div ref={khungRef} className="absolute inset-0">
      {lop.map(({ u, w, h }, i) => {
        if (u === null)
          return (
            <div
              key="phong"
              className={`phong-san-khau absolute inset-0 ${i > 0 ? 'nen-vao' : ''}`}
            />
          )
        const cach = cachHien(khung.w, khung.h, w, h)
        return (
          <div
            key={u}
            data-cach-hien={mo ? 'mo' : cach}
            className={`absolute inset-0 ${i > 0 ? 'nen-vao' : ''}`}
          >
            {/* Album đang mở: nền là CHÍNH ảnh đang hiện, phóng + làm mờ — màu
                dự án phủ kín khung, ảnh nét đã nằm trên thẻ. */}
            {mo ? (
              <img
                src={u}
                alt=""
                className="absolute inset-0 size-full scale-125 object-cover blur-2xl brightness-[.7] saturate-[1.15]"
              />
            ) : (
              <>
                {cach === 'contain' && (
                  <img
                    src={u}
                    alt=""
                    className="absolute inset-0 size-full scale-110 object-cover blur-2xl brightness-90"
                  />
                )}
                <img
                  src={u}
                  alt=""
                  className={`absolute inset-0 size-full ${cach === 'contain' ? 'object-contain' : 'object-cover'}`}
                />
              </>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Album đang hiện trên sân khấu — `CheGiongNoi` giữ state (`LuanPhienAnh`). */
export interface AlbumSanKhau {
  readonly ds: readonly string[]
  readonly i: number
  /** Mốc ảnh hiện tại được đưa lên — chạy lại vạch đếm giờ mỗi lần đổi. */
  readonly doiLuc: number
}

/** Kéo bao nhiêu phần bề rộng thẻ thì các thẻ dịch một bậc. >1 để cú vuốt
 *  ngắn trên điện thoại vẫn kéo được thẻ kế vào giữa. */
const KEO_MOT_BAC = 1.6
/** Thả quá chừng này phần bề rộng thẻ — hoặc vuốt nhanh hơn `VUOT_NHANH` px/ms
 *  — thì sang đúng MỘT ảnh; ít hơn thì thẻ bật về chỗ cũ. */
const NGUONG_THA = 0.15
const VUOT_NHANH = 0.5
/** Cú vuốt nhanh phải đi ít nhất chừng này px — không thì một cú CHẠM (dịch
 *  vài px trong 1ms) cũng đạt «vận tốc» và lướt mất ảnh. */
const VUOT_TOI_THIEU_PX = 24
/** Thời gian album mờ đi lúc đóng — khớp `album-ra` ở `theme.css`. */
const ALBUM_RA_MS = 450
/**
 * Bề rộng thẻ chính của album — nhỏ nhất trong ba giới hạn, theo đơn vị của
 * sân khấu (container `size`):
 * - 78cqw: không rộng quá phần lớn khung;
 * - 88cqh: cao (= rộng × 2/3) không quá ~59% để chừa nhãn trên + phụ đề dưới;
 * - mép phải thẻ (4cqw + rộng) chỉ KHẼ CHẠM tay người dẫn, không bị che lẹm
 *   (người dùng chốt 2026-10-02). Mép trái phần nhìn thấy của người dẫn =
 *   97cqw − 0,89 × bề ngang khung người dẫn (đo trên `nguoi-dan-nghi.webp`:
 *   ngang khuỷu tay, hình bắt đầu ở 10,8% bề ngang khung); bề ngang khung =
 *   0,628 × cao, cao = min(92cqh, 54.7cqw) — cùng số với lớp của `NguoiDan`.
 *   0,89 × 0,628 ≈ 0,559; +1cqw để mép thẻ chạm vào chứ không hở.
 * ⚠️ Đổi cỡ/vị trí người dẫn hoặc dựng lại clip là phải đo và sửa lại vế này.
 */
const RONG_THE = 'min(78cqw, 88cqh, calc(94cqw - 0.559 * min(92cqh, 54.7cqw)))'

/**
 * Album xếp chồng (stacked deck / cover flow): thẻ chính rõ ở giữa-trái (chừa
 * chỗ người dẫn bên phải), thẻ trước/sau ló mép phía sau, lặp vòng vô hạn.
 * Vuốt (điện thoại) / kéo chuột ở BẤT KỲ đâu trên sân khấu để lướt; desktop
 * có thêm mũi tên khi rê chuột.
 *
 * Vị trí thẻ ghi THẲNG vào `style` qua ref chứ không qua state: lúc kéo nó đổi
 * mỗi `pointermove` (~60 lần/giây), qua state là vẽ lại cả `CheGiongNoi`.
 */
function AlbumAnh({
  album,
  dangRa,
  onLuot,
  onGiu,
}: {
  album: AlbumSanKhau
  dangRa: boolean
  onLuot: (buoc: number) => void
  onGiu: (dang: boolean) => void
}) {
  const { ds, i, doiLuc } = album
  const n = ds.length
  const deckRef = useRef<HTMLDivElement>(null)
  const theRef = useRef<Array<HTMLDivElement | null>>([])
  const dCuRef = useRef<Array<number | null>>([])
  const keoRef = useRef<{ x0: number; t0: number; dx: number; id: number } | null>(null)

  function ve(f: number): void {
    const w = deckRef.current?.clientWidth || 300
    theRef.current.forEach((el, j) => {
      if (!el) return
      const dNguyen = n > 1 ? kcVong(j, i, n) : 0
      const k = kieuThe(dNguyen + f * KEO_MOT_BAC, w)
      // Thẻ «nhảy» từ đầu vòng này sang đầu kia (vd. ảnh 1 ↔ ảnh cuối khi
      // lướt): tắt chuyển động một nhịp, không cho nó bay ngang qua cả chồng.
      const cu = dCuRef.current[j]
      if (cu != null && Math.abs(dNguyen - cu) > 1.5) {
        el.dataset.nhay = '1'
        requestAnimationFrame(() => delete el.dataset.nhay)
      }
      dCuRef.current[j] = dNguyen
      el.style.transform = `translate3d(${k.tx}px, ${k.ty}px, ${k.tz}px) rotateY(${k.ry}deg) scale(${k.sc})`
      el.style.opacity = String(k.op)
      el.style.filter = k.bl > 0.05 ? `blur(${k.bl}px)` : 'none'
      el.style.zIndex = String(k.z)
      el.dataset.chinh = dNguyen === 0 ? '1' : '0'
    })
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- `ve` đọc đúng i/n của lần vẽ này
  useLayoutEffect(() => ve(0), [i, n])
  useEffect(() => {
    const el = deckRef.current
    if (!el) return
    const ro = new ResizeObserver(() =>
      ve(keoRef.current ? keoRef.current.dx / (el.clientWidth || 1) : 0),
    )
    ro.observe(el)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- như trên
  }, [i, n])

  const tha = (e: React.PointerEvent) => {
    const k = keoRef.current
    if (!k || k.id !== e.pointerId) return
    keoRef.current = null
    deckRef.current?.removeAttribute('data-keo')
    const w = deckRef.current?.clientWidth || 300
    const v = k.dx / Math.max(1, performance.now() - k.t0)
    const nhanh = Math.abs(k.dx) >= VUOT_TOI_THIEU_PX && Math.abs(v) > VUOT_NHANH
    const buoc =
      k.dx < -w * NGUONG_THA || (nhanh && v < 0)
        ? 1
        : k.dx > w * NGUONG_THA || (nhanh && v > 0)
          ? -1
          : 0
    onGiu(false)
    if (buoc) onLuot(buoc)
    else ve(0)
  }

  return (
    <div
      data-testid="album"
      data-album-anh={i}
      // `touch-pan-y`: vuốt DỌC vẫn cuộn trang như thường, chỉ vuốt NGANG thuộc
      // về album — điện thoại không phải chọn giữa cuộn và lướt ảnh.
      className={`group/album absolute inset-0 touch-pan-y select-none ${n > 1 ? 'cursor-grab active:cursor-grabbing' : ''} ${dangRa ? 'album-ra' : 'album-vao'}`}
      onPointerDown={(e) => {
        if (n < 2 || dangRa || (e.pointerType === 'mouse' && e.button !== 0)) return
        keoRef.current = { x0: e.clientX, t0: performance.now(), dx: 0, id: e.pointerId }
        e.currentTarget.setPointerCapture?.(e.pointerId)
        deckRef.current?.setAttribute('data-keo', '1')
        onGiu(true)
      }}
      onPointerMove={(e) => {
        const k = keoRef.current
        if (!k || k.id !== e.pointerId) return
        k.dx = e.clientX - k.x0
        ve(k.dx / (deckRef.current?.clientWidth || 300))
      }}
      onPointerUp={tha}
      onPointerCancel={tha}
    >
      <div
        ref={deckRef}
        // Cỡ theo CẢ HAI chiều sân khấu + vị trí người dẫn — xem `RONG_THE`.
        // Bản 58% cố định nằm lọt thỏm giữa khung cao kín cột (2026-10-02).
        className="album-deck absolute left-[4%] top-[47%] aspect-[3/2] -translate-y-1/2 @max-md:top-[43%]"
        style={{ width: RONG_THE }}
      >
        {ds.map((u, j) => (
          <div
            key={`${j}:${u}`}
            ref={(el) => {
              theRef.current[j] = el
            }}
            className="album-the absolute inset-0 overflow-hidden rounded-lg bg-white/15 shadow-xl ring-1 ring-white/20 backdrop-blur-sm"
          >
            {/* Ảnh agent gửi là link ngoài, tải có thể chậm: thẻ là tấm kính mờ
                trong lúc chờ, ảnh mờ dần vào khi xong (`data-tai`) — không phải
                một khối đen trơn giữa sân khấu. */}
            <img
              src={u}
              alt=""
              draggable={false}
              onLoad={(e) => (e.currentTarget.dataset.tai = '1')}
              className="pointer-events-none size-full object-cover"
            />
          </div>
        ))}
        {n > 1 && (
          <div className="absolute inset-x-0 -bottom-3 h-[2px] overflow-hidden rounded-full bg-white/25">
            <div
              key={`${i}:${doiLuc}`}
              className="album-tien-do h-full bg-white/85"
              style={{ animationDuration: `${THOI_GIAN_DOI_ANH_MS}ms` }}
            />
          </div>
        )}
      </div>
      {n > 1 &&
        ([-1, 1] as const).map((b) => (
          <button
            key={b}
            type="button"
            tabIndex={-1}
            aria-label={b < 0 ? 'Ảnh trước' : 'Ảnh sau'}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => onLuot(b)}
            // Chỉ máy có chuột (hover) mới hiện mũi tên; điện thoại thì vuốt.
            // Hai mũi tên đối xứng: cách mép trái / mép PHẢI thẻ chính 8px.
            style={b > 0 ? { left: `calc(4cqw + ${RONG_THE} - 40px)` } : undefined}
            className={`absolute top-[47%] z-20 hidden size-8 -translate-y-1/2 cursor-pointer place-items-center rounded-full bg-surface/80 text-fg opacity-0 shadow-md backdrop-blur-md transition-opacity group-hover/album:opacity-100 [@media(hover:hover)]:grid ${b < 0 ? 'left-[calc(4cqw+8px)]' : ''}`}
          >
            <svg
              viewBox="0 0 24 24"
              className="size-4"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                d={b < 0 ? 'M15 6l-6 6 6 6' : 'M9 6l6 6-6 6'}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        ))}
    </div>
  )
}

export function SanKhauAgent({
  video = true,
  tinHieuRef,
  anhNen: anhNenVao,
  lenhGioTay = 0,
  tuDongGioTay = true,
  album,
  onLuotAlbum,
  onGiuAlbum,
  veAvatarRef,
  anhChoAvatar,
  toiDay = false,
  children,
}: {
  /** `false` ⇒ người dẫn là ảnh tĩnh, KHÔNG tải video (8–9 MB). Sân khấu chờ
   *  trước Áp dụng dùng nó: mở tab Voice để xem chưa phải là sắp gọi. */
  video?: boolean
  /** Tín hiệu tiếng agent — `CheGiongNoi` ghi vào từ `onMucLoa` (mức loa +
   *  giây audio còn trong hàng đợi) và từ sự kiện `agent_speaking`/
   *  `agent_done`/`agent_interrupted`. Vắng ⇒ người dẫn luôn ở vòng chờ. */
  tinHieuRef?: React.MutableRefObject<TinHieuLoa>
  /** Ảnh nền ĐÈ lên nền mặc định — dùng khi album mở (ảnh đang hiện).
   *  Vắng ⇒ phông studio trung tính (`phong-san-khau`), không thuộc dự án nào. */
  anhNen?: string | null
  /** TĂNG số này lên một = yêu cầu đưa tay giới thiệu. Người dẫn rẽ vào cử
   *  chỉ ở lần quay về tư thế gốc kế tiếp (tối đa ~5s), nếu lúc đó vẫn đang
   *  nói. Chỗ để sau này nối logic «khi nào đưa tay» (vd. lúc bắn ảnh lên). */
  lenhGioTay?: number
  /** Tự đưa tay sau một lúc nói (`NOI_TRUOC_GIO_TAY_MS`, cách nhau `GIAN_CACH_GIO_TAY_MS` + ngẫu nhiên).
   *  Tắt đi khi đã có logic riêng qua `lenhGioTay`. */
  tuDongGioTay?: boolean
  /** Album ảnh (`send_media`) đang mở — `null`/`ds` rỗng ⇒ nền thường. Khi có,
   *  `anhNen` nên là ảnh đang hiện của album (nền mờ phía sau lấy từ nó). */
  album?: AlbumSanKhau | null
  /** Người dùng vuốt/bấm mũi tên: ±1 ảnh. */
  onLuotAlbum?: (buoc: number) => void
  /** Đang giữ/kéo album (`true`) ⇒ người gọi tạm dừng tự chuyển; thả ra (`false`). */
  onGiuAlbum?: (dang: boolean) => void
  /** Chỗ `CheGiongNoi` lấy hàm vẽ frame lip sync (xem `NguoiDanLipSync`).
   *  Chỉ có tác dụng khi bật `VITE_AVATAR_WS_URL`. */
  veAvatarRef?: React.MutableRefObject<VeAvatar | null>
  /** Ảnh chờ của người dẫn lip sync đang dùng (nhân vật workspace tự tạo — `nhanVat.ts`).
   *  Vắng ⇒ người dẫn mặc định. Đổi ảnh = dựng lại khung (tỉ lệ theo ảnh mới). */
  anhChoAvatar?: string | null | undefined
  /** Dải tối mờ ở đáy (khi có phụ đề) để chữ trắng đọc được trên mọi nền. Vẽ
   *  DƯỚI người dẫn: đặt trong lớp phủ (`children`) thì nó đè lên thân người dẫn
   *  và nhân vật tối hẳn đi lúc agent nói — phụ đề vốn ở góc trái, không cần nó
   *  phủ lên người. */
  toiDay?: boolean
  /** Lớp phủ do màn chứa vẽ lên TRÊN nền + người dẫn (nhãn trạng thái, phụ
   *  đề, bộ đếm ảnh…). Sân khấu không biết gì về cuộc gọi — nó chỉ chừa chỗ. */
  children?: React.ReactNode
}) {
  const imLang = useRef<TinHieuLoa>(TIN_HIEU_IM)
  const anhNen = anhNenVao || null
  // Album vừa đóng vẫn vẽ thêm `ALBUM_RA_MS` để mờ đi, không biến mất cái rụp.
  const coAlbum = !!album && album.ds.length > 0
  const [albumCuoi, setAlbumCuoi] = useState<AlbumSanKhau | null>(null)
  if (coAlbum && albumCuoi !== album) setAlbumCuoi(album)
  useEffect(() => {
    if (coAlbum || !albumCuoi) return
    const t = window.setTimeout(() => setAlbumCuoi(null), ALBUM_RA_MS)
    return () => window.clearTimeout(t)
  }, [coAlbum, albumCuoi])
  const albumVe = coAlbum ? album : albumCuoi
  return (
    <div
      aria-hidden
      data-testid="san-khau"
      data-anh-nen={anhNen ?? undefined}
      data-lenh-gio-tay={lenhGioTay}
      data-album={coAlbum ? album.ds.length : 0}
      // Khung theo TỈ LỆ 3:2 (người dùng chốt: «khung nền phải khớp với ảnh»).
      // Ảnh nền khác tỉ lệ thì `cachHien` lo: lệch ≤ 30% ⇒ phủ kín, hơn ⇒ hiện
      // trọn + dải mờ hai bên. Ba ảnh nền hiện tại (16:9, ~2:1, ~4:3) đều phủ kín.
      // Desktop: CAO KÍN cột (`lg:flex-1`, bỏ khoá 3:2) để cạnh dưới hai cột
      // sát đáy màn — có đánh giá sau cuộc gọi thì tự thấp lại nhường chỗ (tối
      // thiểu 180px). Mobile giữ 3:2. Lệch tỉ lệ ảnh thì `cachHien` lo phần nền.
      className="relative aspect-[3/2] [container-type:size] w-full overflow-hidden rounded-lg border border-border bg-fill-strong lg:aspect-auto lg:min-h-[180px] lg:flex-1"
    >
      <NenSanKhau anh={anhNen} mo={coAlbum} />
      {/* Quầng sáng sau lưng người dẫn: CÙNG khung với người dẫn nên bám theo cô
          ấy ở mọi cỡ sân khấu (vẽ cứng vào ảnh nền thì lệch khi khung đổi tỉ
          lệ — đo 55–120px). Album mở thì tắt: nền là ảnh dự án. Nằm DƯỚI thẻ album. */}
      <div
        className={`${KHUNG_NGUOI_DAN} quang-nguoi-dan pointer-events-none transition-opacity duration-700 ${albumVe ? 'opacity-0' : ''}`}
      />
      {albumVe && (
        <AlbumAnh
          album={albumVe}
          dangRa={!coAlbum}
          onLuot={(b) => onLuotAlbum?.(b)}
          onGiu={(d) => onGiuAlbum?.(d)}
        />
      )}
      {toiDay && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-panel/60 to-transparent" />
      )}
      {urlAvatar() ? (
        // Người dẫn lip sync không tải video nào (chỉ ảnh chờ tới khi có frame) ⇒
        // không cần `video`; prop đó chỉ áp cho clip Kling bên dưới.
        <NguoiDanLipSync
          key={anhChoAvatar ?? 'mac-dinh'}
          veRef={veAvatarRef}
          anhCho={anhChoAvatar ?? undefined}
        />
      ) : (
        <NguoiDan
          video={video}
          tinHieuRef={tinHieuRef ?? imLang}
          lenhGioTay={lenhGioTay}
          tuDongGioTay={tuDongGioTay}
        />
      )}
      {children}
    </div>
  )
}
