/**
 * ═══════════════════════════════════════════════════════════════════════════
 *  NAV REGISTRY — chỗ DUY NHẤT gom nav của mọi module (spec tổng §4⑤)
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * THÊM MỘT MÀN VÀO NAV = 3 việc, không có việc thứ 4:
 *   1. `src/features/<module>/nav.ts`  — khai NavLeaf (có `requiredActions`)
 *   2. file này                        — thêm MỘT dòng vào đúng mảng
 *   3. `src/routes/_app/<key>.tsx`     — thêm route
 *
 * KHÔNG ai phải sửa `components/shell/*`. Nếu bạn thấy mình đang sửa Rail hay
 * NavPanel để thêm một màn thì nghĩa là NavLeaf thiếu một trường — thêm trường
 * vào `nav-types.ts`, đừng đặc-biệt-hoá trong shell.
 *
 * ── BA MẢNG, KHÔNG PHẢI BA NHÓM DỌC (2026-08-07) ───────────────────────────
 * Trước: ba nhóm dọc (Vận hành · Kiến thức · Cấu hình) trong một sidebar 250px,
 * 13 mục cùng hiện một lúc. Sau: ba mảng trên rail, mỗi lần chỉ hiện mục của
 * mảng đang mở.
 *
 * Nhóm lại theo CÂU HỎI người dùng thật sự hỏi, không theo module sở hữu:
 *   · «agent trả lời sai, sửa ở đâu?» → Agent.
 *   · «ai được vào, ai đã làm gì, tốn bao nhiêu?» → Quản trị.
 *   · phần còn lại là việc hằng ngày → Vận hành.
 *
 * ── VÌ SAO DỮ LIỆU NẰM TRONG AGENT ─────────────────────────────────────────
 * Một vòng trước tách «Dữ liệu» (bất động sản · lĩnh vực · tài chính) thành
 * mảng thứ tư, cạnh Agent. Sai: dữ liệu nghiệp vụ KHÔNG phải một thứ song song
 * với agent, nó là MỘT PHẦN của agent — đó chính là thứ agent đọc để trả lời.
 * Tách ra là bắt người dùng trả lời «agent nói sai giá căn hộ, sửa ở đâu?»
 * bằng cách đoán xem giá căn hộ được tính là "dữ liệu" hay là "agent".
 *
 * ── VÌ SAO MẢNG AGENT CHIA KHỐI ────────────────────────────────────────────
 * Vòng sau đó xếp 7 mục của Agent thành một danh sách phẳng. Cũng sai, và sai
 * ở chỗ tinh hơn: nó xoá mất phân biệt QUAN TRỌNG NHẤT của màn Agent — cái gì
 * áp cho MỌI lĩnh vực, cái gì chỉ áp cho MỘT.
 *
 * Nên panel chia khối:
 *   · khối mở đầu (không nhãn) = phần CHUNG của agent. Danh tính, system
 *     prompt, rào chắn, kỹ năng chung; cộng tài liệu workspace, lỗ hổng, khoá
 *     API, và sổ lĩnh vực. Đổi ở đây là đổi cho mọi lĩnh vực.
 *   · mỗi lĩnh vực MỘT khối có nhãn = Kiến thức + Kỹ năng của riêng nó.
 *
 * `/kb` («Tài liệu») ở khối CHUNG chứ không nằm trong khối Bất động sản: nó là
 * tài liệu của cả workspace, agent tra nó ở mọi lĩnh vực. Xếp vào một khối
 * lĩnh vực là nav hứa một phạm vi mà backend không có. Ngày nào KB chia theo
 * lĩnh vực thật thì chuyển nó vào, không phải trước.
 *
 * Cấp cha mở/gập «Lĩnh vực» KHÔNG quay lại — khối là đường phân đoạn có tên,
 * mọi mục vẫn luôn nhìn thấy. Xem `NavSegment` ở `nav-types.ts`.
 *
 * Thứ tự mảng theo TẦN SUẤT mở, không theo vòng đời sản phẩm: người vận hành
 * mở portal ra là để xem hội thoại, không phải để chỉnh agent.
 *
 * `tests/nav-registry.test.ts` canh thứ tự này.
 *
 * Đây là file duy nhất được import nav của nhiều module — eslint tắt luật
 * ranh giới riêng cho nó.
 */
import { domainsNav, projectsNav } from '@/features/realestate/nav'
import { usersNav } from '@/features/auth/nav'
import { caiDatWorkspaceNav } from '@/features/workspace/nav'
import { agentNav, kyNangBdsNav } from '@/features/agent/nav'
import { kbNav } from '@/features/kb/nav'
import { duLieuNgoaiNav } from '@/features/kb-web/nav'
import { kichBanNav } from '@/features/kich-ban/nav'
import { chuyenSaleNav, convosNav, dashboardNav } from '@/features/ops/nav'
import { apiNav, auditNav, thuAgentNav } from '@/features/platform/nav'
import { billingNav, usageNav } from '@/features/billing/nav'
import { qualityNav } from '@/features/quality/nav'
import { flattenLeaves, khoi, matchesPath } from './nav-types'
import type { Label, NavGroup, NavLeaf } from './nav-types'

export const NAV: readonly NavGroup[] = [
  {
    key: 'ops',
    label: { vi: 'Vận hành', en: 'Operate' },
    icon: 'secOps',
    segments: [khoi(dashboardNav, convosNav, chuyenSaleNav, qualityNav)],
  },
  {
    key: 'agent',
    label: { vi: 'Agent', en: 'Agent' },
    // Con `Bot` — cùng hình với chính agent ở màn Thử agent, nên mảng và thứ nó
    // chứa đọc thành một.
    //
    // Điều này TỪNG bị cấm ("icon rail không dùng lại icon của màn nào") vì rail
    // và panel đứng cạnh nhau, hai icon giống hệt cách 68px sẽ đọc thành một
    // thứ. Lời cấm đó hết đúng: `Bot` KHÔNG còn xuất hiện trong panel Agent —
    // «Kỹ năng» là mục con trong khối lĩnh vực nên bỏ icon, còn «Cấu hình
    // chung» đã sang `UserRoundCog`. Không còn gì để trùng.
    icon: 'agent',
    segments: [
      // ① CHUNG cho mọi lĩnh vực — agent LÀ AI, nó ĐỌC gì, và THỬ xem ra sao.
      // «Thử agent» khép khối này lại vì nó là bước nghiệm thu của hai mục trên;
      // nó KHÔNG thuộc khối lĩnh vực nào — thử là thử cả agent, không thử riêng
      // một vertical.
      khoi(agentNav, kbNav, thuAgentNav),
      // ② Mỗi lĩnh vực một khối: Kiến thức (nguồn agent tra) + Kỹ năng (việc
      // agent làm được trong lĩnh vực đó) + Kịch bản (cách agent xử lý từng tình
      // huống bán hàng — nút kịch bản nói về căn, dự án, cọc nên thuộc BĐS, người
      // dùng chốt 2026-10-01). `linhVuc` buộc khối vào công tắc ở màn «Quản lý
      // lĩnh vực» — tắt là khối biến mất, kể cả Kịch bản.
      {
        label: { vi: 'Bất động sản', en: 'Real estate' },
        // Toà nhà — cùng mark `projects` đang dùng cho màn dự án, và ở đây nó
        // KHÔNG trùng lặp vì mục con trong khối gập bỏ icon (chúng thụt vào,
        // dưới đúng cái đầu khối này). Không vẽ mark mới cho thứ đã có mark đúng.
        icon: 'projects',
        linhVuc: 'bds',
        // «Dữ liệu ngoài» ngay dưới Kiến thức: hồ sơ web viết cho từng DỰ ÁN bất động sản,
        // nên tắt lĩnh vực là mục này ẩn theo (lịch thu thập phía backend cũng dừng).
        entries: [projectsNav, duLieuNgoaiNav, kyNangBdsNav, kichBanNav],
      },
      // ③ HỆ THỐNG — đường đấu nối và sổ lĩnh vực. Xuống cuối vì đây là thứ
      // dựng một lần rồi thôi, còn hai khối trên là thứ sửa hằng ngày.
      // «Quản lý lĩnh vực» đứng ngay dưới các khối lĩnh vực mà nó điều khiển.
      khoi(apiNav, domainsNav),
    ],
  },
  {
    key: 'admin',
    label: { vi: 'Quản trị', en: 'Admin' },
    icon: 'secAdmin',
    // `usersNav` TRỞ LẠI 2026-08-17 sau hai ngày bị ẩn. Lý do ẩn ("khối `/users*`
    // ở backend đóng bằng cờ `USERS_ADMIN_ENABLED`") sai đối tượng: màn «Thành
    // viên» chạy trên seam `/members` (gate `WORKSPACE_ADMIN`), không trên
    // `/users*`. Ẩn nó là chặn đường vào DUY NHẤT tới việc mời người vào workspace.
    // MỘT khối cho cả năm mục (người dùng chốt 2026-08-21). Ba mục chi phí
    // (`/usage` · `/billing` · `/pricing`) từng đứng ở khối RIÊNG, không nhãn —
    // ý đồ là «đứng liền nhau thì đọc thành một nhóm». Nhưng hai khối không
    // nhãn cạnh nhau chỉ khác nhau đúng một khoảng trắng dọc (xem `NavPanel`),
    // nên thứ người dùng thấy không phải một nhóm mà là một vết nứt giữa
    // «Nhật ký» và «Lượt dùng» — chia mảng Quản trị làm đôi mà không nói vì
    // sao. Khối riêng chỉ đáng khi nó CÓ NHÃN; và khối có nhãn thì mục con bỏ
    // hẳn icon (CLAUDE.md, mục Shell), tức ba icon `usage`/`billing`/`pricing`
    // thành code chết. Nên: một khối, các mục đồng cấp, có icon.
    //
    // ⚠️ ĐỪNG viết một con số đếm mục vào đoạn chú thích này. Bản trước ghi «năm
    // mục» rồi «còn BỐN mục», và merge `develop` 2026-08-21 (thêm
    // `caiDatWorkspaceNav`) làm cả hai con số sai cùng lúc — hai nhánh sửa cùng
    // khối này thì con số là thứ hỏng trước tiên và không cổng nào bắt được.
    // Danh sách thật nằm ở dòng `segments:` dưới đây, đọc nó.
    //
    // `pricingNav` RỜI KHỎI ĐÂY 2026-08-21 (người dùng chốt). Portal
    // này là hệ thống cho user ngoài dùng, họ không được đặt giá; giá nay do
    // migration `0949` của backend seed. Route `/pricing` GIỮ NGUYÊN và chuyển
    // xuống `OFF_NAV` — admin nền tảng có `X-Platform-Admin-Token` vẫn gõ URL vào
    // sửa được.
    //
    // «Cài đặt workspace» ĐỨNG CUỐI, có hai lý do và cả hai đều là ràng buộc thật:
    //
    // ① Bấm rail = ĐIỀU HƯỚNG tới mục ĐẦU của mảng. Đặt nó lên đầu là đổi màn
    //    mặc định của cả mảng Quản trị từ «Thành viên» sang một màn có nút xoá
    //    workspace — tức mỗi lần mở mảng này là hạ cánh xuống cạnh nó. Và mục đầu
    //    của mảng này vừa được trả lại cho `usersNav` ở đúng dòng comment trên;
    //    lấy chỗ đó là đảo ngược quyết định 2026-08-17 mà không ai yêu cầu.
    // ② Đây là thứ dựng một lần rồi thôi, còn BỐN mục trên là thứ đọc hằng ngày.
    //    Cùng lý lẽ đã xếp «API Keys» + «Quản lý lĩnh vực» xuống cuối mảng Agent.
    segments: [khoi(usersNav, auditNav, billingNav, usageNav, caiDatWorkspaceNav)],
  },
]

/**
 * Năm màn KHÔNG có mục nav — nhưng rail vẫn phải biết tô sáng mảng nào, và
 * topbar vẫn phải có tiêu đề.
 *
 * MỘT bảng cho cả hai câu hỏi. Trước đây `Topbar.tsx` giữ riêng một bảng
 * `EXTRA_TITLES` với đúng những path này; rail cần cùng danh sách ấy để trả lời
 * câu khác. Hai bảng cùng danh sách là hai chỗ để quên cập nhật một chỗ.
 *
 * `group` phải khớp một `key` trong `NAV` — `tests/nav-registry.test.ts` canh.
 */
export const OFF_NAV: readonly {
  readonly path: string
  readonly group: string
  readonly label: Label
}[] = [
  // `/users` KHÔNG còn ở đây — nó trở lại nav 2026-08-17 (xem khối `admin` ở
  // trên). Một path vừa ở NAV vừa ở OFF_NAV là lỗi, có cổng canh riêng.
  // Bỏ khỏi nav 2026-08-21: user của portal này không được đặt giá (xem khối
  // `admin` ở trên). Route còn — đường vào là gõ URL. Nhãn để nguyên «Bảng giá» chứ không thêm chữ
  // «(quản trị)»: topbar dùng chính chuỗi này, và một tiêu đề không khớp cái
  // người dùng vừa bấm là đúng lớp lỗi mà `/pform`/`/uform` dưới đây ghi lại.
  { path: '/pricing', group: 'admin', label: { vi: 'Bảng giá', en: 'Pricing' } },
  // «Kiến thức», KHÔNG «Bất động sản» (sửa 2026-08-08). Hai nhãn này tụt lại từ
  // trước lần đổi tên 2026-08-07: mục nav của `/projects` đã thành «Kiến thức»
  // (nó nằm DƯỚI nhãn khối «Bất động sản», xem `features/realestate/nav.ts`),
  // nhưng hai form con vẫn khai tên cũ. Hệ quả đo được: bấm «Kiến thức» → mở một
  // dự án → topbar đổi thành «Bất động sản», tức tiêu đề màn không còn khớp mục
  // nav vừa bấm, và đường về ở thân màn cũng nói một cái tên thứ ba.
  { path: '/pform', group: 'agent', label: { vi: 'Kiến thức', en: 'Knowledge' } },
  { path: '/uform', group: 'agent', label: { vi: 'Kiến thức', en: 'Knowledge' } },
  // Phải khớp `usersNav.label` — `/roles` redirect sang `/users`, và hai nhãn
  // lệch nhau nghĩa là tiêu đề nhảy chữ ngay giữa lần chuyển hướng.
  { path: '/roles', group: 'admin', label: { vi: 'Thành viên', en: 'Members' } },
  {
    path: '/settings',
    group: 'admin',
    label: { vi: 'Hồ sơ & tuỳ chọn', en: 'Profile & preferences' },
  },
]

/** Mục nav ứng với route đang mở, nếu có. */
export function leafFor(groups: readonly NavGroup[], pathname: string): NavLeaf | undefined {
  return flattenLeaves(groups).find((l) => matchesPath(l.path, pathname))
}

/**
 * Mảng mà route đang mở thuộc về.
 *
 * `groups` là danh sách ĐÃ LỌC QUYỀN, nên hàm này nhận vào chứ không đọc `NAV`
 * thẳng: mảng người dùng không có quyền thấy thì cũng không được tô sáng.
 *
 * Không tìm ra thì trả mảng đầu tiên — không trả `undefined`. Rail và panel
 * luôn phải hiện MỘT thứ gì đó; một panel rỗng ở route lạ trông như hỏng.
 */
export function groupFor(groups: readonly NavGroup[], pathname: string): NavGroup | undefined {
  const byLeaf = groups.find((g) => flattenLeaves([g]).some((l) => matchesPath(l.path, pathname)))
  if (byLeaf) return byLeaf
  const off = OFF_NAV.find((o) => matchesPath(o.path, pathname))
  if (off) {
    const byOff = groups.find((g) => g.key === off.group)
    if (byOff) return byOff
  }
  return groups[0]
}

/**
 * Tiêu đề màn cho topbar — nhãn của mục nav, hoặc của bảng `OFF_NAV`.
 *
 * Đọc `NAV` ĐẦY ĐỦ, không phải bản đã lọc quyền: gõ thẳng URL vào một màn
 * không có quyền thì API mới là thứ từ chối, còn `<h1>` trống là màn không có
 * mốc để trình đọc màn hình nhảy tới. Tiêu đề không phải một phép kiểm quyền.
 */
export function titleFor(pathname: string): Label | null {
  const leaf = leafFor(NAV, pathname)
  if (leaf) return leaf.label
  return OFF_NAV.find((o) => matchesPath(o.path, pathname))?.label ?? null
}
