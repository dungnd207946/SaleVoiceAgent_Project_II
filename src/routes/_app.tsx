import { useEffect, useState } from 'react'
import { createFileRoute, Outlet } from '@tanstack/react-router'
import { CommandPalette } from '@/components/shell/CommandPalette'
import { LopPhu } from '@/components/shell/LopPhu'
import { NavPanel } from '@/components/shell/NavPanel'
import { Rail } from '@/components/shell/Rail'
import { Topbar } from '@/components/shell/Topbar'
import { useKhoManHinh } from '@/lib/khoManHinh'
import { SessionProvider, useSession } from '@/lib/session'

/**
 * App shell — layout của MỌI màn sau đăng nhập.
 *
 * `_app` là layout pathless: file `_app/dashboard.tsx` ra path `/dashboard`,
 * không phải `/_app/dashboard`.
 *
 * <SessionProvider> ở ĐÂY, không ở main.tsx: nó chặn cả cây trên GET /api/v1/me,
 * nên nếu nó bọc RouterProvider thì `/login` cũng không render được khi endpoint
 * đó trả 401. "Cần phiên" và "nằm trong _app" là cùng một điều kiện — nên chỗ
 * chặn chưa-đăng-nhập là MỘT chỗ, không phải 18 chỗ, đúng như file này đã hẹn.
 */
export const Route = createFileRoute('/_app')({
  component: AppLayout,
})

function AppLayout() {
  /**
   * Thu gọn panel màn (2026-08-24). CHỈ panel 240px — rail 68px ở lại, vì rail
   * là điều hướng chính giữa các mảng; ẩn luôn nó thì chỉ còn ⌘K. Panel
   * UNMOUNT hẳn chứ không `hidden` (cùng luật với form ở chế độ xem): một panel
   * `display:none` để lại mọi mục nav trong DOM, test vẫn thấy chúng trong khi
   * người dùng không thấy gì. Nút bật/tắt nằm ở ĐÁY RAIL — nó phải còn nhìn
   * thấy được ở cả trạng thái đã thu gọn, và bản đầu đặt ở Topbar thì lấn vào
   * tiêu đề màn (người dùng chê ngay khi xem thật). State là `useState`
   * phiên-sống: reload là panel mở lại, chưa ai yêu cầu ghi nhớ lâu hơn.
   */
  const [panelThuGon, setPanelThuGon] = useState(false)
  /**
   * Tablet/mobile (2026-09-28): nav mở trong LỚP PHỦ thay vì đẩy nội dung. State
   * riêng, không dùng lại `panelThuGon`: desktop nhớ lựa chọn thu/mở của nó, còn
   * lớp phủ luôn bắt đầu ĐÓNG — đổi tầng (xoay máy, kéo cửa sổ) là đóng, để
   * không bao giờ kẹt một nền mờ trên desktop.
   */
  const kho = useKhoManHinh()
  const [phuMo, setPhuMo] = useState(false)
  useEffect(() => setPhuMo(false), [kho])
  const dong = () => setPhuMo(false)

  return (
    <SessionProvider>
      <div className="flex min-h-screen">
        {/* Rail (mảng) → panel (màn) → nội dung. Ba cột, mỗi cột một cấp phạm
            vi, đọc từ trái sang phải là đi từ rộng tới hẹp. */}
        {kho === 'desktop' && (
          <>
            <Rail panelThuGon={panelThuGon} onDoiThuGon={() => setPanelThuGon((v) => !v)} />
            {!panelThuGon && <NavPanel />}
          </>
        )}
        {kho === 'tablet' && (
          <>
            <Rail panelThuGon={!phuMo} onDoiThuGon={() => setPhuMo((v) => !v)} />
            {phuMo && (
              <LopPhu dong={dong} nhan="Điều hướng" lech="sauRail">
                <NavPanel />
              </LopPhu>
            )}
          </>
        )}
        {kho === 'mobile' && phuMo && (
          <LopPhu dong={dong} nhan="Điều hướng">
            <Rail />
            <NavPanel />
          </LopPhu>
        )}
        {/*
          `relative` KHÔNG phải để định vị con nào — nó là thứ khoá `overflow-auto`
          ở dòng này lại. `.sr-only` của Tailwind dùng `position: absolute`, nên
          khi không có ancestor nào được position thì containing block của nó là
          initial containing block (viewport), CHỨ KHÔNG phải <main> — và
          `overflow` chỉ clip được hậu duệ có containing block nằm trong chính nó.
          Kết quả: input `sr-only` nào rơi xuống dưới mép viewport sẽ nong vùng
          scroll của DOCUMENT, sinh thanh cuộn thứ hai ở ngoài; `aside` là
          `sticky top-0` trong khung cao đúng 100vh nên không còn chỗ trượt và cả
          sidebar trôi theo. Đo được ở `/pform?tab=tong-quan` (id cũ lúc đo là
          `thong-tin`; form 1821px, hai ô tệp `sr-only` của OMedia ở y=1679):
          `html.scrollHeight` 1680 so với viewport 813. Thêm `relative` là ép mọi
          absolute-không-neo về lại trong <main> để nó clip được — sửa cho MỌI màn
          dài hơn một viewport, không riêng tab Tổng quan.
        */}
        <main
          className={`relative h-screen min-w-0 flex-1 overflow-auto max-lg:h-dvh ${phuMo ? 'max-lg:overflow-hidden' : ''}`}
        >
          <Topbar {...(kho === 'mobile' ? { moNav: () => setPhuMo(true) } : {})} />
          <ManTheoWorkspace />
        </main>
        {/* NGOÀI <main>: palette là lớp phủ toàn màn (`fixed inset-0`), đặt
            trong một ancestor có `overflow-auto` thì nó bị cắt theo vùng cuộn
            của nội dung thay vì phủ cả viewport. */}
        <CommandPalette />
      </div>
    </SessionProvider>
  )
}

/**
 * Đổi workspace ⇒ màn đang mở DỰNG LẠI TỪ ĐẦU, không chỉ nạp lại query.
 *
 * VÌ SAO KEY Ở ĐÂY CHỨ KHÔNG SỬA TỪNG MÀN. `switchWorkspace` đã bỏ cache mọi
 * query (lib/session.tsx), nhưng cái đó chỉ dọn được dữ liệu CÒN NẰM TRONG
 * react-query. Màn nào sao dữ liệu server vào `useState` để cho sửa — Agent
 * Studio sao cả 8 ô cấu hình — thì bản sao ấy sống ngoài cache, và route không
 * đổi nên component không dựng lại: query mới về vẫn bị bản sao cũ che.
 *
 * Triệu chứng nhẹ là nhìn thấy cấu hình workspace cũ. Hậu quả nặng là bấm Lưu
 * và áp dụng ngay lúc đó — ghi payload của workspace CŨ đè lên workspace MỚI,
 * đúng thứ hợp đồng cách ly tồn tại để chặn, chỉ là rò ở tầng state của client
 * chứ không ở tầng request.
 *
 * `key` ở layout khoá cả lớp lỗi này một lần: mọi state cục bộ của mọi màn đều
 * thuộc về đúng một workspace theo cấu trúc, và màn viết sau không phải nhớ.
 * Giá phải trả là mất scroll/UI state khi đổi workspace — đổi workspace là đổi
 * ngữ cảnh, giữ lại mới là cái sai.
 *
 * Canh bởi tests/doi-workspace.test.tsx.
 */
function ManTheoWorkspace() {
  const { currentWorkspace } = useSession()
  return <Outlet key={currentWorkspace.id} />
}
