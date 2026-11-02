/**
 * Bảng token đẩy dữ liệu — khối thứ hai của tab «Nguồn dữ liệu».
 *
 * ── HAI ĐƯỜNG, MỘT QUYỀN ────────────────────────────────────────────────────
 * «Nhập liệu» có hai chủ thể và chúng cần hai cơ chế khác nhau, nhưng đổ về cùng
 * một quyền `catalog.write`:
 *   · NGƯỜI nhập liệu → một vai trò trong `control.roles` chỉ mang `catalog.*`.
 *     Cơ chế đó đã chạy sẵn, màn này không đụng tới.
 *   · HỆ THỐNG của khách → token dưới đây. Quyền CỨNG, không cấu hình được: đúng
 *     một `catalog.write`, đúng một cặp (workspace, lĩnh vực).
 *
 * ── VÌ SAO KHÔNG DÙNG LẠI `control.agent_keys` ─────────────────────────────
 * Luật viết trong `modules/enrollment/service.py` là *«api_key nói tôi là ai;
 * credential nói tôi được làm gì. Không gộp hai vai. api_key mở được ĐÚNG MỘT
 * thứ»* — và cái một-thứ đó là bộ credential của tenant (tức mật khẩu Postgres).
 * Thêm vai nạp dữ liệu vào chính khoá ấy là phá đúng luật đó, và tệ hơn: token
 * đẩy nằm trong hệ thống của BÊN THỨ BA, còn khoá agent thì không.
 *
 * ── HÌNH DẠNG: HAI CỘT, MỞ TẠI CHỖ ─────────────────────────────────────────
 * `Tên` · `Token` (che bằng dấu chấm, con mắt mở tại chỗ, nút copy) · thùng rác.
 * Không có gì khác.
 *
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Bang,
  DauBang,
  Hang,
  NUT_CHINH,
  NutIcon,
  TD,
  ThanhCong,
  TheBang,
  VungCuon,
  type Cot,
} from '@/components/ui/Bang'
import { KhoRong } from '@/components/ui/TrangThai'
import { LoiApi } from '@/lib/http'
import { Q_TONG_QUAN, taoToken, xoaToken, type Token } from '../nguon'
import { TaoTokenDialog, XoaTokenDialog } from './NguonTokenDialog'
import { OToken } from './OToken'

const COT: readonly Cot[] = [{ nhan: 'Tên' }, { nhan: 'Token', rong: 'w-full' }, { nhan: '' }]

function cau(e: unknown, macDinh: string): string {
  if (e instanceof LoiApi) return e.message
  return e instanceof Error ? e.message : macDinh
}

export function NguonToken({ tokens }: { readonly tokens: readonly Token[] }) {
  const qc = useQueryClient()
  const [moTao, setMoTao] = useState(false)
  const [dinhXoa, setDinhXoa] = useState<Token | null>(null)

  const mTao = useMutation({
    mutationFn: taoToken,
    onSuccess: () => {
      setMoTao(false)
      void qc.invalidateQueries({ queryKey: Q_TONG_QUAN })
    },
  })

  const mXoa = useMutation({
    mutationFn: xoaToken,
    onSuccess: () => {
      setDinhXoa(null)
      void qc.invalidateQueries({ queryKey: Q_TONG_QUAN })
    },
  })

  return (
    <>
      <TheBang>
        <ThanhCong>
          <h3 className="mr-auto text-the font-semibold text-fg">Token đẩy dữ liệu</h3>
          <button
            type="button"
            onClick={() => {
              mTao.reset()
              setMoTao(true)
            }}
            className={`${NUT_CHINH} flex-none`}
          >
            Tạo token
          </button>
        </ThanhCong>

        {tokens.length === 0 ? (
          <div className="p-4">
            <KhoRong
              tieuDe="Chưa có token nào."
              huongDan="Tạo một token rồi gửi cho đội kỹ thuật bên khách."
            />
          </div>
        ) : (
          <VungCuon>
            <Bang nhan="Token đẩy dữ liệu">
              <DauBang cot={COT} />
              <tbody>
                {tokens.map((k) => (
                  <Hang key={k.id}>
                    <td className={`${TD} whitespace-nowrap font-semibold text-fg`}>{k.label}</td>
                    <td className={TD}>
                      <OToken token={k.token} nhan={k.label} />
                    </td>
                    <td className={`${TD} whitespace-nowrap text-right`}>
                      <NutIcon
                        icon="trash"
                        nhan={`Xoá token ${k.label}`}
                        phaHuy
                        onClick={() => {
                          mXoa.reset()
                          setDinhXoa(k)
                        }}
                      />
                    </td>
                  </Hang>
                ))}
              </tbody>
            </Bang>
          </VungCuon>
        )}
      </TheBang>

      {moTao && (
        <TaoTokenDialog
          dangGui={mTao.isPending}
          loi={mTao.error ? cau(mTao.error, 'Không tạo được token') : null}
          onDong={() => setMoTao(false)}
          onTao={(label) => mTao.mutate(label)}
        />
      )}

      {dinhXoa && (
        <XoaTokenDialog
          token={dinhXoa}
          dangGui={mXoa.isPending}
          loi={mXoa.error ? cau(mXoa.error, 'Không xoá được token') : null}
          onDong={() => setDinhXoa(null)}
          onXoa={() => mXoa.mutate(dinhXoa.id)}
        />
      )}
    </>
  )
}
