/**
 * Bộ icon của portal — HAI NGUỒN, một cửa gọi.
 *
 *   ① `PATHS` — path copy ĐÚNG từ prototype (`design/Tenant Portal.dc.html`).
 *      Lưới 20×20, stroke 1.6, linecap round.
 *   ② `LUCIDE` — component của `lucide-react`, dùng khi cần đúng một icon có
 *      sẵn ngoài đời thay vì một bản vẽ tay gần giống.
 *
 * Cả hai đi qua cùng `<Icon name="..." />`, nên chỗ gọi không cần biết icon
 * mình dùng đến từ đâu.
 *
 * ⚠ LUẬT CŨ ĐÃ ĐỔI (2026-08-08). Tệp này trước ghi "KHÔNG dùng lucide/heroicons
 * — nó đổi hình dáng nét so với thiết kế đã chốt, và thêm một dependency cho 15
 * đường path". Người dùng chốt ngược lại: cài Lucide. Lý do cũ vẫn đúng về
 * nguyên tắc, nhưng vẽ tay theo một ảnh chụp thì ra một icon GẦN GIỐNG chứ
 * không phải icon đó — và gần giống là thứ tệ nhất trong cả ba lựa chọn.
 *
 * ĐỘ DÀY NÉT PHẢI QUY VỀ CÙNG MỘT TỈ LỆ, không dùng mặc định của Lucide:
 *   · bộ nhà:  1.6 / lưới 20 = 0.080
 *   · Lucide:  2.0 / lưới 24 = 0.083  ⟶ đậm hơn ~4%, thấy được khi hai icon
 *              nằm cạnh nhau trong cùng một panel
 * Nên `Icon` ép `strokeWidth={1.92}` cho icon Lucide (= 0.080 × 24). Thêm icon
 * Lucide mới thì KHÔNG cần làm gì — hằng số nằm ở một chỗ, dưới cuối tệp.
 */
import type { SVGProps } from 'react'
import {
  Activity,
  Bot,
  BriefcaseBusiness,
  Building2,
  Check,
  ChevronDown,
  Copy,
  Crown,
  DoorOpen,
  Expand,
  Eye,
  EyeOff,
  Gem,
  Image,
  Globe,
  GraduationCap,
  HandCoins,
  Handshake,
  HardHat,
  Headset,
  House,
  Info,
  KeyRound,
  Landmark,
  Languages,
  ListTree,
  Megaphone,
  MessageSquareText,
  Mic,
  MicAudioLines,
  PanelLeftClose,
  PanelLeftOpen,
  Phone,
  PhoneForwarded,
  PhoneOff,
  Plus,
  RotateCw,
  Save,
  Scale,
  Scan,
  Search,
  Settings,
  Settings2,
  Shield,
  TriangleAlert,
  Shrink,
  Sprout,
  Star,
  Store,
  Tags,
  UserRound,
  UserRoundCog,
  Users,
  Upload,
  Video,
  Workflow,
  X,
} from 'lucide-react'

const PATHS: Record<string, React.ReactNode> = {
  dashboard: (
    <>
      <rect x="2.5" y="2.5" width="6.5" height="6.5" rx="1.4" />
      <rect x="11" y="2.5" width="6.5" height="4" rx="1.4" />
      <rect x="11" y="8.5" width="6.5" height="9" rx="1.4" />
      <rect x="2.5" y="11" width="6.5" height="6.5" rx="1.4" />
    </>
  ),
  convos: (
    <path d="M17 12.2a1.8 1.8 0 0 1-1.8 1.8H6.5L3 17.2V4.8A1.8 1.8 0 0 1 4.8 3h10.4A1.8 1.8 0 0 1 17 4.8z" />
  ),
  appts: (
    <>
      <rect x="2.8" y="4.2" width="14.4" height="13" rx="2" />
      <path d="M13.4 2.5v3.4M6.6 2.5v3.4M2.8 8.6h14.4" />
    </>
  ),
  quality: (
    <>
      <path d="M2.8 13.4 6.6 9l3.2 3 4.2-5.4" />
      <path d="M2.8 17.2h14.4" />
      <path d="M14 6.6h2.4V9" />
    </>
  ),
  projects: (
    <>
      <path d="M2.8 17.2h14.4" />
      <path d="M4.6 17.2V5.1l5.4-2.3 5.4 2.3v12.1" />
      <path d="M8.2 17.2v-3.6h3.6v3.6" />
    </>
  ),
  // `domains` (bánh răng của prototype) ĐÃ XOÁ 2026-08-08: «Quản lý lĩnh vực»
  // chuyển sang `Settings2` của Lucide, không còn chỗ nào dùng path này.
  kb: (
    <>
      <path d="M11.4 2.6H6a1.8 1.8 0 0 0-1.8 1.8v11.2A1.8 1.8 0 0 0 6 17.4h8a1.8 1.8 0 0 0 1.8-1.8V7z" />
      <path d="M11.4 2.6V7h4.4" />
      <path d="M7.6 11h4.8M7.6 14h3.2" />
    </>
  ),
  gaps: (
    <>
      <circle cx="10" cy="10" r="7.3" />
      <path d="M7.9 7.9a2.2 2.2 0 0 1 4.2.7c0 1.5-2.1 2.2-2.1 2.2" />
      <path d="M10 14.2h.02" />
    </>
  ),
  // `agent` KHÔNG còn ở đây — nó là `Bot` của Lucide, khai ở `LUCIDE` dưới cuối
  // tệp (2026-08-08). Tên khoá giữ nguyên nên không chỗ gọi nào phải sửa.
  // `api` KHÔNG còn ở đây — nó là `KeyRound` của Lucide, khai ở `LUCIDE` dưới
  // cuối tệp. Hai bản vẽ tay trước đó (mắt xích, rồi chìa khoá ngang) đều là
  // suy diễn từ một ảnh chụp nhỏ, không phải chính icon người dùng muốn.
  users: (
    <>
      <path d="M13.6 16.8v-1.4a3 3 0 0 0-3-3H5.4a3 3 0 0 0-3 3v1.4" />
      <circle cx="8" cy="6.4" r="2.9" />
      <path d="M17.6 16.8v-1.4a3 3 0 0 0-2.2-2.9M13 3.7a3 3 0 0 1 0 5.5" />
    </>
  ),
  audit: (
    <>
      <path d="M10 2.4 4 4.6v4.9c0 3.4 2.4 6.6 6 8.1 3.6-1.5 6-4.7 6-8.1V4.6z" />
      <path d="M7.8 9.9 9.4 11.5l3-3.2" />
    </>
  ),
  billing: (
    <>
      <rect x="2.4" y="4.6" width="15.2" height="10.8" rx="2" />
      <path d="M2.4 8.6h15.2M5.6 12.2h2.8" />
    </>
  ),
  caret: <path d="M7.5 4.5 13 10l-5.5 5.5" />,

  // ── Icon của MẢNG (rail), 2026-08-07 ──────────────────────────────────────
  // Mảng Vận hành và Quản trị dùng hai mark riêng, KHÔNG lấy lại icon của màn
  // nào trong mảng đó: rail và panel đứng cạnh nhau, hai icon giống hệt cách
  // nhau 68px là mời người dùng đọc chúng thành một thứ.
  //
  // Mảng AGENT là ngoại lệ CÓ LÝ DO: nó dùng `agent` (`Bot`) — xem chú thích ở
  // `lib/nav-registry.ts`. Không icon nào trong panel Agent trùng với nó.
  //
  // Cùng luật hình với bộ trên — lưới 20×20, stroke 1.6, bo tròn đầu nét.
  secOps: <path d="M2.4 10h3.1l2.3-5.6 3.5 11.2 2.3-5.6h4.0" />,
  secAdmin: (
    <>
      <path d="M3.2 6.4h13.6M3.2 13.6h13.6" />
      <circle cx="7.4" cy="6.4" r="2.1" />
      <circle cx="12.6" cy="13.6" r="2.1" />
    </>
  ),
  search: (
    <>
      <circle cx="8.8" cy="8.8" r="5.4" />
      <path d="M12.8 12.8 17.2 17.2" />
    </>
  ),
  // Năm icon dưới đây KHÔNG có trong prototype (nó không vẽ menu tài khoản, cũng
  // không vẽ nút hành động trong hàng bảng). Dựng theo đúng luật hình của bộ
  // trên: lưới 20×20, stroke 1.6, bo tròn đầu nét.
  //
  // `edit` · `trash` · `resend` là ba việc trong ô cuối của một hàng. Trước đây
  // chúng là chữ («Sửa» · «Xoá» · «Mời lại») dài ngắn khác nhau, nên cột hành
  // động của mỗi bảng rộng một kiểu và hàng nào có ba nút thì đội hình lệch hẳn
  // so với hàng chỉ có một. Icon vuông đều nhau khoá được chiều rộng cột.
  edit: (
    <>
      <path d="M12.9 3.4a1.85 1.85 0 0 1 2.6 2.6l-8.3 8.3-3.5.9.9-3.5z" />
      <path d="M11.8 4.5l2.6 2.6" />
    </>
  ),
  trash: (
    <>
      <path d="M3.6 5.4h12.8" />
      <path d="M7.8 5.4V4.2a1.2 1.2 0 0 1 1.2-1.2h2a1.2 1.2 0 0 1 1.2 1.2v1.2" />
      <path d="M5.4 5.4l.7 10.1a1.5 1.5 0 0 0 1.5 1.4h4.6a1.5 1.5 0 0 0 1.5-1.4l.7-10.1" />
      <path d="M8.4 8.6v5.2M11.6 8.6v5.2" />
    </>
  ),
  resend: (
    <>
      <path d="M16.4 10a6.4 6.4 0 1 1-1.9-4.5" />
      <path d="M16.6 3.2v3.6h-3.6" />
    </>
  ),
  /**
   * Nút nguồn — dùng cho CẢ hai chiều bật/tắt khoá, KHÔNG phải `trash`.
   * Khoá không bị xoá: backend chỉ đặt `revoked_at`, và tắt rồi bật lại được.
   * Một thùng rác ở đây sẽ hứa một việc không hoàn tác được, trong khi đây đúng
   * là việc hoàn tác được — và chính nhầm lẫn đó là thứ đã phải sửa.
   */
  power: (
    <>
      <path d="M10 2.6v6.4" />
      <path d="M14.9 5.7a6.6 6.6 0 1 1-9.8 0" />
    </>
  ),
  logout: (
    <>
      <path d="M12.4 2.8H5.4a2 2 0 0 0-2 2v10.4a2 2 0 0 0 2 2h7" />
      <path d="M13.6 6.8 16.8 10l-3.2 3.2M16.4 10H8.2" />
    </>
  ),
}

/**
 * Icon lấy nguyên từ `lucide-react`.
 *
 * Dùng khi cần ĐÚNG một icon có sẵn ngoài đời. Icon nào thuộc ngôn ngữ hình
 * riêng của prototype thì vẫn ở `PATHS` — không có lý do gì thay một bản vẽ
 * đang đúng bằng một bản khác chỉ vì thư viện đã cài.
 */
const LUCIDE = {
  api: KeyRound,
  /** «Dữ liệu ngoài» — trang web công khai hệ thống thu về cho agent. */
  duLieuNgoai: Globe,
  /** Tab «Sale» của khối cấu hình theo role (`/agent`) — cặp với `vaiTroKhach`: một
   *  cặp tab mà chỉ một bên có icon thì hai bên đọc thành hai hạng (luật `MucTab.icon`). */
  vaiTroSale: BriefcaseBusiness,
  /** Tab «Khách hàng» — một người, không phải `users` (nhóm người = «Người dùng» portal). */
  vaiTroKhach: UserRound,
  /** Nút «Thêm role» cuối hàng tab `/agent`. */
  them: Plus,
  /** Mũi tên mở menu «N role khác» khi hàng tab `/agent` không đủ chỗ. */
  moXuong: ChevronDown,
  /** Ô tìm trong menu «N role khác». */
  timKiem: Search,
  /**
   * Bộ icon cho role người dùng agent do workspace tự tạo (`features/agent/iconVaiTro.ts`
   * là bảng mã ↔ icon, backend chỉ lưu MÃ). Nhiều hình khác nhau là có chủ ý: mười tab
   * cùng một hình thì icon không còn giúp mắt tìm tab nào nữa — nó chỉ còn là trang trí.
   */
  vtVuongMien: Crown,
  vtDauTu: HandCoins,
  vtDoiTac: Handshake,
  vtDoanhNghiep: Building2,
  vtChuNha: House,
  vtHoTro: Headset,
  vtNhaThau: HardHat,
  vtDaiLy: Store,
  vtNganHang: Landmark,
  vtCaoCap: Gem,
  vtMarketing: Megaphone,
  vtKhachMoi: Sprout,
  vtNhom: Users,
  vtDaoTao: GraduationCap,
  vtPhapLy: Scale,
  /** Ghi một hàng vào bảng (nút «Thêm» của dialog Chuẩn hoá cách đọc). Trước là
   * `Plus`; đổi sang đĩa mềm theo yêu cầu 2026-08-25. Bộ nhà không có mark nào cho
   * việc này, và `check` thì đọc thành «xác nhận/hợp lệ» chứ không phải «ghi». */
  save: Save,
  /**
   * Con agent — dùng ở mục «Kỹ năng» và ở hình agent ngủ/thức của màn Thử agent.
   *
   * Thay bản vẽ tay theo prototype (một hộp chữ nhật có ăng-ten). `Bot` của
   * Lucide cùng ý nhưng nét gọn hơn và cao gần bằng các icon cạnh nó — xem luật
   * «cùng chiều cao THẤY ĐƯỢC» ở `danhTinh`.
   */
  agent: Bot,
  /** Tab «Voice» ở màn Thử agent — mic kèm sóng âm. */
  voice: MicAudioLines,
  /** Nút «Bắt đầu trò chuyện» / «Kết thúc» và ô mức micro của tab Voice —
   *  khuôn của một CUỘC GỌI (ống nghe xanh · ống nghe gạch đỏ), vì bố cục tab
   *  Voice dựng theo hình một cuộc gọi video. */
  goiDien: Phone,
  cupMay: PhoneOff,
  mic: Mic,
  /**
   * «Chuyển sale» — ống nghe kèm mũi tên rời đi.
   *
   * KHÔNG dùng lại `convos`: mark đó đang mang nghĩa «hội thoại» ở ngay mục
   * bên trên trong CÙNG mảng Vận hành, và hai mục cạnh nhau cùng mark thì
   * người dùng phải đọc chữ mới phân biệt được.
   */
  chuyenSale: PhoneForwarded,
  /** «Kịch bản» — sơ đồ các nút nối nhau (đồ thị playbook). */
  kichBan: Workflow,
  /** «Luồng xử lý» dưới câu trả lời ở Thử agent — cây các bước một lượt (L0 → NLU → … → phát ra). KHÔNG dùng lại
   *  `kichBan` (`Workflow`): đó là sơ đồ nút kịch bản, khác nghĩa, và hai mark cùng trong panel Agent. */
  luongXuLy: ListTree,
  /** Nút đóng panel / khung phụ (không phải hộp thoại — lightbox ảnh tự vẽ nét riêng). */
  dong: X,
  /**
   * «Cấu hình chung» — người + bánh răng: *chỉnh xem agent này là ai*.
   *
   * Màn đó khai agent LÀ AI: tên, thương hiệu, xưng hô, lời chào, giọng điệu,
   * phạm vi, rào chắn — tức cấu hình một NHÂN VẬT, không phải cài đặt hệ thống.
   *
   * KHÔNG dùng `IdCard` (thử rồi, bỏ): tấm thẻ nằm ngang, hộp bao 20×14 trên
   * lưới 24 nên cao 9.3px trong khi các icon cạnh nó 10.7–13.4px — đứng trong
   * một cột dọc thì nó đọc thành "nhỏ hơn". Icon cạnh nhau phải cùng CHIỀU CAO
   * thấy được, không chỉ cùng cỡ ô.
   *
   * KHÔNG dùng `Speech` (đầu người + sóng nói) dù nó hợp nghĩa: panel Agent
   * hiện ĐỒNG THỜI với tab voice `MicAudioLines` khi đang ở màn Thử agent, và
   * hai mark cùng có vạch sóng đứng cạnh nhau thì đọc nhầm nhau.
   * KHÔNG dùng `Bot`: con robot đã là icon của «Kỹ năng» trong CÙNG panel.
   */
  danhTinh: UserRoundCog,
  /**
   * Bánh răng — «Cài đặt workspace» (nav) và «Hồ sơ & tuỳ chọn» (`UserMenu`).
   *
   * ⚠️ TỪNG LÀ BẢN VẼ TAY TRONG `PATHS`, VÀ NÓ VẼ RA MỘT MẶT TRỜI: một vòng
   * tròn `r=2.6` cộng TÁM ĐOẠN THẲNG TÁCH RỜI toả ra bốn trục và bốn chéo. Bánh
   * răng thì có răng cưa DÍNH LIỀN vành; vòng tròn cộng tia rời là hình mặt
   * trời, không có cách đọc nào khác. Nó sống trong `UserMenu` như thế một thời
   * gian dài mà không ai nói — đúng thứ mà quyết định 2026-08-08 («vẽ tay theo
   * ảnh chụp thì ra icon *gần giống*, và gần giống là lựa chọn tệ nhất trong
   * ba») đã cảnh báo. Đây là ca mẫu của luật đó, nên nó dọn về Lucide.
   *
   * DÙNG Ở HAI CHỖ, CÓ CHỦ Ý — và điều đó phá lệ «một mark một nghĩa». Chấp
   * nhận vì hai chỗ ấy nói CÙNG một nghĩa («cài đặt»), chỉ khác PHẠM VI, mà
   * phạm vi thì nhãn ngay cạnh đã nói ra («workspace» vs «Hồ sơ»). Vẽ một mark
   * lạ cho một màn tên đúng là «Cài đặt workspace» để né một va chạm mà một chữ
   * đã giải quyết là đánh đổi sai chiều: nó làm mục hay bị quét mắt nhất thành
   * thứ phải đoán.
   */
  settings: Settings,
  /** «Quản lý lĩnh vực» — sổ các vertical và công tắc bật/tắt. Thanh trượt, KHÔNG
   *  phải bánh răng: nó là chỗ GẠT từng lĩnh vực, không phải chỗ cấu hình chung. */
  settings2: Settings2,
  /**
   * Khiên — đầu khu «Rào chắn đang bảo vệ workspace» ở màn Cấu hình chung.
   *
   * KHÔNG dùng lại `audit` (bản vẽ tay, cũng là một cái khiên có dấu tích): mark
   * đó đang mang nghĩa «Nhật ký» ở mảng Quản trị, và một mark hai nghĩa là thứ
   * người dùng phải học thuộc theo ngữ cảnh thay vì đọc được ngay.
   *
   * `Shield` trơn chứ KHÔNG `ShieldCheck`: sáu dòng bên dưới đã mỗi dòng một dấu
   * ✓ rồi — thêm một dấu tích nữa ở đầu khu là nói cùng một điều hai lần trong
   * cùng một khung nhìn.
   */
  shield: Shield,
  /** Biểu tượng sao — dùng cho hiển thị rating. */
  star: Star,
  /**
   * Bong bóng CÓ DÒNG CHỮ — nút «Đánh giá cuộc trò chuyện» dưới câu trả lời
   * cuối ở màn Thử agent.
   *
   * KHÔNG dùng lại `convos` (bong bóng trơn, bản vẽ tay): mark đó đang là icon
   * tab «Chat» của CHÍNH màn đó, hiện cách nút này chưa tới một màn hình — một
   * mark hai nghĩa là thứ người dùng phải học thuộc theo ngữ cảnh. Mấy dòng
   * chữ bên trong nói đúng thứ nút mở ra: một ô để VIẾT nhận xét.
   */
  nhanXet: MessageSquareText,
  /** Nút copy endpoint ở màn API Keys — hai tờ giấy chồng nhau, mark chuẩn ngoài đời. */
  copy: Copy,
  /** «Xoay khoá» — hàng bảng «Khoá đấu nối agent». Mũi tên vòng chuẩn cho "thay
   * bằng bản mới, huỷ bản cũ" — cùng nghĩa `RotateCw` dùng ở khắp nơi ngoài đời
   * cho "regenerate"/"rotate". */
  xoay: RotateCw,
  /** Cảnh báo mâu thuẫn dữ liệu — màn Kiến thức và màn dự án. Tam giác chấm than là mark
   * chuẩn ngoài đời cho «có chỗ cần xem», không phải lỗi hệ thống. */
  mauThuan: TriangleAlert,
  /**
   * Cặp con mắt — công tắc che/mở một bí mật hiện TẠI CHỖ (ô API Key ở tab
   * «Nguồn dữ liệu»). Hai mark, không phải một: một con mắt đơn đổi nghĩa theo
   * trạng thái thì người dùng phải nhớ "đang che hay đang mở" mới đoán được cú
   * bấm làm gì. `Eye` = đang che, bấm để mở; `EyeOff` = đang mở, bấm để che.
   */
  hienBiMat: Eye,
  cheBiMat: EyeOff,
  /** Biên nhận «đã copy» — cùng nút, đổi mark trong ~1.6s rồi về lại `copy`. */
  check: Check,
  /**
   * Cặp thu gọn/mở panel màn — nút ở `Topbar`. Hai mark, không phải một (cùng
   * lý lẽ `hienBiMat`/`cheBiMat`): mũi tên trong khung nói hướng CÚ BẤM sẽ đẩy
   * panel đi, nên `thuPanel` = panel đang mở, bấm để thu; `moPanel` = đang thu,
   * bấm để mở — người dùng không phải nhớ trạng thái mới đoán được nút làm gì.
   */
  thuPanel: PanelLeftClose,
  moPanel: PanelLeftOpen,
  /**
   * «Ngôn ngữ» trong menu Hồ sơ & tuỳ chọn.
   *
   * `Languages` (hai chữ A/文) chứ KHÔNG `Globe`: quả địa cầu trong phần mềm
   * quản trị đọc thành «vùng/khu vực» hoặc «tên miền» — mà portal này CÓ một màn
   * tên miền thật, nên mark đó đã có chỗ đứng khác. Hai ký tự của hai bảng chữ
   * cái nói đúng thứ nút này đổi: chữ trên màn hình.
   */
  ngonNgu: Languages,
  /**
   * «Căn / sản phẩm» ở hàng thước khắc vạch của ô Kiến thức (`/dashboard`).
   *
   * Một cánh cửa mở = một căn hộ — khái niệm MỚI thật sự (không có mark nào
   * trong `PATHS` nói đúng "một đơn vị BĐS để bán"), nên thêm một mục vào bộ
   * icon là đúng, không phải lách qua bằng cách mượn nghĩa một icon có sẵn
   * (`appts` — lịch hẹn — đã đứng nhầm chỗ này trước khi sửa, 2026-08-13).
   */
  can: DoorOpen,
  /**
   * «Lượt dùng» ở khối «Chi phí» — mạch hoạt động, đúng nghĩa số liệu xem
   * thường xuyên. `billingNav` đã có mark riêng (`billing`, ở `PATHS`); mục
   * này trước mượn tạm `quality`, nay có mark của chính nó.
   */
  usage: Activity,
  /** «Bảng giá» ở khối «Chi phí» — hai thẻ giá, đúng nghĩa bảng cấu hình giá. */
  pricing: Tags,
  /**
   * Nút «Xem nội dung đã nạp» ở hàng tài liệu «Tài liệu chung» (Task 15).
   *
   * `Eye` trơn — KHÔNG cùng khoá với `hienBiMat`: mark đó ghép cặp với
   * `cheBiMat` để nói trạng thái CHE/MỞ một bí mật; ở đây chỉ có một trạng
   * thái (xem), không có cặp đổi hình theo ngữ cảnh.
   */
  xemNoiDung: Eye,
  /**
   * Điều khiển sơ đồ cây `/kich-ban`. «Vừa khung» là `Scan` (khung bốn góc = đóng khung cả cây),
   * toàn màn hình là cặp MŨI TÊN `Expand`/`Shrink` — KHÔNG `Maximize`: nó cũng là bốn góc khung,
   * đứng cạnh `Scan` thì hai nút trông như một. Hai mark cho bật/tắt, cùng lý lẽ `thuPanel`/`moPanel`.
   */
  vuaKhung: Scan,
  toanManHinh: Expand,
  thoatToanManHinh: Shrink,
  /** Nút mở thông tin khách agent đã khai thác (`/convos/$phone`, dưới bề rộng ba cột). */
  thongTin: Info,
  /** Form tạo người dẫn (`NguoiDanDialog`): hai nguồn video/ảnh + ô chọn tệp. */
  video: Video,
  anh: Image,
  taiLen: Upload,
} as const

/** Bằng 1.6/20 của bộ nhà quy về lưới 24 của Lucide — xem đầu tệp. */
const NET_LUCIDE = 1.92

export type IconName = keyof typeof PATHS | keyof typeof LUCIDE

interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: IconName
}

export function Icon({ name, ...rest }: IconProps) {
  const Ngoai = (LUCIDE as Record<string, typeof KeyRound | undefined>)[name]
  if (Ngoai) {
    // `strokeWidth` đặt TRƯỚC `{...rest}`: chỗ gọi nào truyền độ dày riêng thì
    // vẫn thắng, giống hệt cách nhánh dưới hoạt động.
    return <Ngoai strokeWidth={NET_LUCIDE} aria-hidden="true" {...rest} />
  }

  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  )
}
