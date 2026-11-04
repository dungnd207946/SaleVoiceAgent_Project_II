/**
 * Tab Vị trí — hai ô của `projects` và vùng ảnh `vi_tri`.
 *
 * Tự lưu từng ô (`useLuuTungO`): PATCH mang đúng ô vừa rời, backend
 * `exclude_unset` nên nó không đụng 15 ô còn lại của `projects`.
 */
import { useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { suaDuAn, type DuAn, type Media } from '../api'
import { danhSachMedia } from '../api'
import { KHU_VUC, nhanCua } from '../enums'
import { cauLoi, loiO } from '../thongDiep'
import { useLuuTungO } from '../useLuuTungO'
import { DongTrangThai, OChu } from '@/components/ui/Truong'
import { TAB_DAY } from '@/components/ui/Bang'
import { LoiTai } from '@/components/ui/TrangThai'
import { useTrangCuon } from './useTrangCuon'
import { VungMedia } from './VungMedia'
import { useKhungSua } from '../khungSua'
import { SectionCard } from './SectionCard'

interface ViTri {
  region: string
  address: string
}

export function ViTriTab({ duAn, projectCode }: { duAn: DuAn; projectCode: string }) {
  const qc = useQueryClient()
  const { dangSua } = useKhungSua()

  const luu = useCallback(
    async (patch: Partial<ViTri>) => {
      const d = await suaDuAn(projectCode, patch)
      void qc.invalidateQueries({ queryKey: ['re', projectCode] })
      return d
    },
    [projectCode, qc],
  )

  const o = useLuuTungO<ViTri>({ region: duAn.region, address: duAn.address }, luu)

  // `region` nhận CẢ giá trị máy (`mien_nam`) lẫn chữ tự do ("Quận 7, TP.HCM").
  // Ô nhập buộc hiện đúng thứ sẽ được lưu, nên giá trị máy phải được dịch ở một
  // dòng cạnh nó — nếu không người dùng chỉ thấy `mien_nam` và không biết agent
  // nói gì với khách.
  const nhanVung = nhanCua(KHU_VUC, o.v.region)
  const viNguoiDoc = nhanVung !== o.v.region ? `Khách nghe là «${nhanVung}»` : undefined

  const media = useTrangCuon<Media>(['re', projectCode, 'media'], (c) =>
    danhSachMedia(projectCode, { limit: 200, cursor: c }),
  )

  return (
    <div className={`${TAB_DAY} flex flex-col gap-4 pb-2`}>
      <SectionCard title="Vị trí dự án">
        <OChu
          ten="region"
          khoa={!dangSua}
          nhan="Khu vực"
          batBuoc
          giaTri={dangSua ? o.v.region : nhanVung}
          doi={(x) => o.doi('region', x)}
          xong={() => o.xong('region')}
          loi={loiO(o.loi, 'region')}
          goiY={viNguoiDoc}
          goiYTrongO="VD: Hà Nội · Gia Lâm"
        />
        <div className="lg:col-span-2">
          <OChu
            ten="address"
            khoa={!dangSua}
            nhan="Địa chỉ"
            giaTri={o.v.address}
            doi={(x) => o.doi('address', x)}
            xong={() => o.xong('address')}
            loi={loiO(o.loi, 'address')}
            goiYTrongO="Số nhà, đường, phường/xã, quận/huyện"
          />
        </div>
      </SectionCard>

      {o.loi != null && <DongTrangThai mau="alert">{cauLoi(o.loi, 'lưu vị trí')}</DongTrangThai>}

      {media.isPending ? (
        <p className="text-[14px] text-muted">Đang tải…</p>
      ) : media.error ? (
        <LoiTai viec="ảnh vị trí" thuLai={() => void media.refetch()} />
      ) : (
        <VungMedia
          projectCode={projectCode}
          category="vi_tri"
          nhan="Vị trí"
          title="Bản đồ vị trí"
          boCuc="gallery"
          anh={media.items.filter((m) => !m.zoneCode && !m.unitCode && m.category === 'vi_tri')}
          lamMoi={() => void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })}
        />
      )}
    </div>
  )
}
