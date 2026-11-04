/**
 * ĐỈNH panel — chọn workspace. Sở hữu: M2a (spec tổng §2).
 *
 * Prototype vẽ anphu · Growth, nhưng `plan` LUÔN null ở MVP (tenants cố ý
 * không có cột plan — xem migration 0002 và spec M2a §4.3①). Nên chỉ hiện slug.
 * Khi nào có bảng `accounts` thì nhánh kia tự bật, không phải sửa lại.
 *
 * Đổi workspace là REQUEST THẬT từ M2a-BE, và nó bỏ cache của workspace cũ —
 * xem `switchWorkspace` trong lib/session.tsx, và tests/doi-workspace.test.tsx.
 *
 * Tạo workspace mới mở DIALOG tại chỗ, không điều hướng sang một màn riêng.
 * Form có đúng một ô — một màn full-page cho một ô nhập là bắt người dùng rời
 * chỗ họ đang làm rồi tìm đường về.
 *
 * Mục đó hiện cho MỌI người đăng nhập được — khớp cửa thật ở backend
 * (`service.tao` kiểm `users.org_role`). Hiện cho member là mời họ bấm vào 403.
 *
 * ── KHỐI DANH TÍNH ĐÃ RỜI SANG `UserMenu` (2026-08-07) ──────────────────────
 * Comment cũ ở đây cấm tách hai menu, với lý do: "hai menu cách nhau 8px, cùng
 * bật lên từ một góc màn, là hai chỗ để người dùng phải đoán xem thứ mình cần
 * nằm bên nào". Lý do ấy ĐÚNG ở khoảng cách 8px — nó nói về sự nhập nhằng do
 * kề nhau, không phải về việc tách. Hai menu giờ ở hai ĐẦU của một cột cao
 * ngang màn hình, mỗi cái ở đúng chỗ phạm vi của nó: workspace mở đầu, danh
 * tính khép lại. Không còn hai thứ tranh nhau một góc.
 *
 * ── DISCLOSURE, KHÔNG PHẢI `role="menu"` (2026-10-05) ───────────────────────
 * Bản trước khai `menu`/`menuitem` mà không có phím mũi tên nào — trình đọc màn hình
 * hứa một mô hình phím không tồn tại, và Esc/chọn xong thì focus rơi về `<body>`.
 * Nay: nút mở mang `aria-expanded` + `aria-controls`, danh sách là nút thường đi bằng
 * Tab; Esc hoặc chọn xong thì focus TRẢ VỀ nút mở. Workspace đang mở nói bằng
 * `aria-current`, không chỉ bằng dấu ✓.
 */
import { useId, useRef, useState } from 'react'
import { useDongKhiRaNgoai } from '@/lib/dongKhiRaNgoai'
import { Icon } from '@/components/icons'
import { TaoWorkspaceDialog } from '@/features/workspace/components/TaoWorkspaceDialog'
import { useLang } from '@/i18n'
import { useSession } from '@/lib/session'

export function WorkspaceSwitcher() {
  const { t } = useLang()
  const { session, currentWorkspace, switchWorkspace } = useSession()
  const [open, setOpen] = useState(false)
  const [moTao, setMoTao] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)
  const nutRef = useRef<HTMLButtonElement>(null)
  const idDs = useId()

  /** Đóng và trả focus về nút mở — gọi TRƯỚC khi danh sách unmount. */
  function dong() {
    setOpen(false)
    nutRef.current?.focus()
  }

  // Bấm ra ngoài / bấm Esc thì đóng. Không có nó, menu dính lại là lỗi người
  // dùng gặp trong 10 giây đầu. Bấm ra ngoài thì KHÔNG kéo focus về: người dùng
  // vừa chỉ tay vào chỗ khác.
  useDongKhiRaNgoai(boxRef, open, (e) => (e.type === 'keydown' ? dong() : setOpen(false)))

  return (
    /* CAO ĐÚNG 72px = chiều cao `Topbar` — hai khối này nằm cạnh nhau ở đỉnh màn
       và đường `border-b` của chúng đọc thành MỘT đường ngang chạy hết bề rộng.
       Lệch 3.8px (bản cũ: `p-2.5` + nút 47.2px = 68.2) là một bậc thang ngay chỗ
       panel gặp topbar. Cùng lý do dùng `border-border` chứ không `border-soft`:
       hai nửa của một đường mà khác sắc thì vẫn đọc thành hai đường. */
    <div className="flex h-[72px] flex-none items-center border-b border-border px-2.5">
      {/* `w-full` vì khung ngoài giờ là flex — không có nó thì hộp co về bề rộng
          chữ và nút workspace ngắn lại theo tên workspace. */}
      <div ref={boxRef} className="relative w-full">
        <button
          ref={nutRef}
          type="button"
          aria-expanded={open}
          aria-controls={idDs}
          onClick={() => setOpen(!open)}
          className="flex w-full min-w-0 items-center gap-2 rounded-md border border-border-field bg-surface px-2.5 py-[7px] text-left hover:border-border-strong"
        >
          <span className="min-w-0 flex-1">
            <span className="block truncate text-than font-semibold leading-[1.3]">
              {currentWorkspace.name}
            </span>
            <span className="block truncate font-mono text-nhan leading-[1.3] text-muted-3">
              {currentWorkspace.plan
                ? `${currentWorkspace.slug} · ${currentWorkspace.plan}`
                : currentWorkspace.slug}
            </span>
          </span>
          <Icon
            name="caret"
            strokeWidth={2}
            className={`size-[13px] flex-none text-muted-2 transition-transform duration-150 ${open ? '-rotate-90' : 'rotate-90'}`}
          />
        </button>

        {open && (
          /* Bật XUỐNG, và đổ bóng xuống — switcher giờ ở đỉnh panel. Bản cũ bật
             lên với `shadow` âm vì nó nằm dưới đáy. */
          <div
            id={idDs}
            className="absolute left-0 top-[calc(100%+6px)] z-60 w-[236px] rounded-xl border border-border-field bg-surface p-1.5 shadow-menu"
          >
            <div
              id={`${idDs}-nhan`}
              className="px-[11px] pb-1.5 pt-[7px] text-nhan font-semibold uppercase tracking-[0.08em] text-muted-3"
            >
              {t({ vi: 'Workspace của bạn', en: 'My workspaces' })}
            </div>
            <div role="group" aria-labelledby={`${idDs}-nhan`}>
              {session.workspaces.map((ws) => (
                <button
                  key={ws.id}
                  type="button"
                  aria-current={ws.id === currentWorkspace.id ? 'true' : undefined}
                  onClick={() => {
                    // `void`: đóng menu ngay, không chờ request. Chờ thì menu dính
                    // lại suốt vòng đi-về và người dùng bấm thêm lần nữa.
                    void switchWorkspace(ws.id)
                    dong()
                  }}
                  className="flex w-full items-center gap-2.5 rounded-lg px-[11px] py-2 text-left text-than hover:bg-bg"
                >
                  <span className="min-w-0 flex-1 truncate">{ws.name}</span>
                  {ws.id === currentWorkspace.id && (
                    <Icon
                      name="check"
                      strokeWidth={2.4}
                      className="size-[15px] flex-none text-ac"
                    />
                  )}
                </button>
              ))}
            </div>
            {/* HIỆN CHO MỌI NGƯỜI từ 2026-08-15. Backend bỏ cổng
                `users.org_role = 'owner'` ở `service.tao` — ai đăng nhập được
                cũng tạo được workspace, và người tạo thành "Quản trị" của nó.
                Không còn điều kiện nào bọc khối này. */}
            <div className="mx-1 my-1.5 h-px bg-border-soft" />
            <button
              type="button"
              onClick={() => {
                // Focus về nút mở TRƯỚC khi dialog mở — `HopThoai` nhớ chỗ đó để trả
                // focus khi đóng.
                dong()
                setMoTao(true)
              }}
              className="flex w-full items-center gap-[7px] rounded-lg px-[11px] py-2 text-left text-than font-semibold text-ac hover:bg-bg"
            >
              <span className="w-[15px] flex-none text-center text-the leading-none">+</span>
              {t({ vi: 'Tạo workspace mới', en: 'Create new workspace' })}
            </button>
          </div>
        )}
      </div>

      {/* NGOÀI `boxRef` là cố ý: handler bấm ra ngoài để đóng menu dùng
          `boxRef.contains()`, và dialog nằm trong đó thì mọi cú bấm bên trong
          dialog cũng bị tính là bấm trong menu — menu mở lại phía sau dialog. */}
      {moTao && (
        <TaoWorkspaceDialog
          onDong={() => setMoTao(false)}
          onXong={async (ws) => {
            // Chuyển sang workspace vừa tạo. `switchWorkspace` là REQUEST THẬT và
            // nó xoá cache của workspace cũ — nhờ vậy màn hình sau khi tạo là
            // workspace mới thật sự rỗng, không phải dữ liệu workspace trước.
            await switchWorkspace(ws.id)

            // ĐÓNG BẰNG TAY, và đóng SAU. `key` ở routes/_app.tsx chỉ bọc
            // <Outlet> — panel (và switcher này, và dialog) nằm NGOÀI nó, nên
            // đổi workspace remount nội dung màn chứ KHÔNG remount dialog. Thiếu
            // dòng này thì dialog đứng lại vĩnh viễn ở nút Đang tạo… dù
            // workspace đã tạo xong — `dangGui` không có nhánh nào gỡ khi thành
            // công.
            //
            // SAU chứ không TRƯỚC `switchWorkspace`: đóng trước là trả người dùng
            // về màn workspace CŨ trong suốt vòng đi-về của POST /me/workspace.
            // Giữ dialog ở trạng thái Đang tạo… tới lúc xong là nói đúng thứ
            // đang diễn ra.
            setMoTao(false)
          }}
        />
      )}
    </div>
  )
}
