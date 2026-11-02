/** Tab Tổng quan: các phần thông tin của `projects` bên trái; ảnh cover, kiến thức cho agent, giờ cập nhật bên phải. */
import { useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { danhSachMedia, suaDuAn, type DuAn, type DuAnGhi, type Media } from '../api'
import { mediaKem } from '../mediaKem'
import { LOAI_HINH, SALE_PHASE } from '../enums'
import { cauLoi, loiO } from '../thongDiep'
import { useLuuTungO } from '../useLuuTungO'
import {
  CaHang,
  DongTrangThai,
  OChon,
  OChonNhieu,
  OChu,
  OSo,
  ReadField,
} from '@/components/ui/Truong'
import { TAB_DAY } from '@/components/ui/Bang'
import { ngayThangNam, gioPhut } from '@/lib/dinhDang'
import { OMedia } from './OMedia'
import { OHangMucBanGiao } from './OHangMucBanGiao'
import { hangMucDeGui } from '../banGiao'
import { useKhungSua } from '../khungSua'
import { useTrangCuon } from './useTrangCuon'
import { SectionCard } from './SectionCard'
import { SalePhaseChip } from './SaleChip'
import { ImageCard } from './ImageCard'
import { KbCard } from './KbCard'
import { areaWithHectare, percent, plainNumber, vndLarge } from '../formatValue'

function tuDuAn(d: DuAn): DuAnGhi {
  return {
    name: d.name,
    category: [...d.category],
    investor: d.investor,
    developer: d.developer,
    totalLandAreaM2: d.totalLandAreaM2,
    floorAreaM2: d.floorAreaM2,
    buildDensityPct: d.buildDensityPct,
    productScale: d.productScale,
    amenities: d.amenities,
    ownershipForm: d.ownershipForm,
    handoverStandard: [...d.handoverStandard],
    totalInvestmentVnd: d.totalInvestmentVnd,
    salePhase: d.salePhase,
    overview: d.overview,
    totalUnits: d.totalUnits ?? null,
    numBuildings: d.numBuildings ?? null,
    managementFeeVndM2: d.managementFeeVndM2 ?? null,
    parkingCarFeeVnd: d.parkingCarFeeVnd ?? null,
    parkingMotoFeeVnd: d.parkingMotoFeeVnd ?? null,
  }
}

function ngayGio(iso: string): string {
  const d = new Date(iso)
  return `${ngayThangNam(d)} ${gioPhut(d)}`
}

export function TongQuanTab({ duAn }: { duAn: DuAn }) {
  const qc = useQueryClient()
  const { dangSua } = useKhungSua()
  const khoa = !dangSua

  // `status` KHÔNG bao giờ đi trong thân PATCH — chip trạng thái sở hữu trường đó.
  const luu = useCallback(
    async (patch: Partial<DuAnGhi>) => {
      const than = patch.handoverStandard
        ? { ...patch, handoverStandard: hangMucDeGui(patch.handoverStandard) }
        : patch
      const d = await suaDuAn(duAn.projectCode, than)
      void qc.invalidateQueries({ queryKey: ['re', 'projects'] })
      void qc.invalidateQueries({ queryKey: ['re', duAn.projectCode] })
      return d
    },
    [duAn.projectCode, qc],
  )

  const o = useLuuTungO(tuDuAn(duAn), luu)
  const { v, doi, xong, doiVaLuu } = o

  const media = useTrangCuon<Media>(['re', duAn.projectCode, 'media'], (c) =>
    danhSachMedia(duAn.projectCode, { limit: 200, cursor: c }),
  )
  // `coverMedia` vắng = chưa đổi ở màn này ⇒ hiện ảnh đang lưu; `null` = vừa bỏ ảnh.
  const cover =
    v.coverMedia === undefined
      ? mediaKem(media.items.find((m) => m.id === duAn.coverMediaId))
      : v.coverMedia

  return (
    <div className={`${TAB_DAY} pb-2`}>
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_312px]">
        <div className="flex min-w-0 flex-col gap-4">
          <SectionCard title="Thông tin chung">
            <OChu
              ten="name"
              khoa={khoa}
              nhan="Tên thương mại"
              batBuoc
              giaTri={v.name ?? ''}
              doi={(x) => doi('name', x)}
              xong={() => xong('name')}
              loi={loiO(o.loi, 'name')}
              goiYTrongO="Tên khách nghe trên thị trường, VD: Vinhomes Ocean Park 2"
            />
            <OChon
              ten="salePhase"
              khoa={khoa}
              nhan="Trạng thái kinh doanh"
              giaTri={v.salePhase ?? 'sap_mo_ban'}
              doi={(x) => doiVaLuu('salePhase', x)}
              muc={SALE_PHASE}
              loi={loiO(o.loi, 'salePhase')}
              renderValue={(x) => <SalePhaseChip value={x} />}
            />
            <OChonNhieu
              ten="category"
              khoa={khoa}
              nhan="Loại hình"
              giaTri={v.category ?? []}
              doi={(x) => doiVaLuu('category', x)}
              muc={LOAI_HINH}
              loi={loiO(o.loi, 'category')}
            />
            <OChu
              ten="investor"
              khoa={khoa}
              nhan="Chủ đầu tư"
              batBuoc
              giaTri={v.investor ?? ''}
              doi={(x) => doi('investor', x)}
              xong={() => xong('investor')}
              loi={loiO(o.loi, 'investor')}
              goiYTrongO="Tên pháp nhân đứng tên dự án"
            />
            <OChu
              ten="developer"
              khoa={khoa}
              nhan="Đơn vị phát triển"
              giaTri={v.developer ?? ''}
              doi={(x) => doi('developer', x)}
              xong={() => xong('developer')}
              loi={loiO(o.loi, 'developer')}
              goiYTrongO="Để trống nếu trùng chủ đầu tư"
            />
            <ReadField label="Mã dự án">
              <span className="font-mono text-than">{duAn.projectCode}</span>
              {dangSua && (
                <span className="block text-phu text-muted-2">Mã không đổi được sau khi tạo.</span>
              )}
            </ReadField>
          </SectionCard>

          <SectionCard title="Giới thiệu dự án" cols={1}>
            <OChu
              ten="overview"
              khoa={khoa}
              nhan="Giới thiệu dự án"
              hideLabelInView
              batBuoc
              hangChu={8}
              giaTri={v.overview ?? ''}
              doi={(x) => doi('overview', x)}
              xong={() => xong('overview')}
              loi={loiO(o.loi, 'overview')}
              goiYTrongO="Vị trí và kết nối · quy mô và các dòng sản phẩm · tiện ích nổi bật · tiến độ và thời điểm bàn giao · vì sao khách nên quan tâm. Viết thành đoạn, đúng giọng bạn muốn agent nói với khách."
            />
          </SectionCard>

          <SectionCard title="Tiện ích" cols={1}>
            <OChu
              ten="amenities"
              khoa={khoa}
              nhan="Tiện ích"
              hideLabelInView
              hangChu={4}
              giaTri={v.amenities ?? ''}
              doi={(x) => doi('amenities', x)}
              xong={() => xong('amenities')}
              loi={loiO(o.loi, 'amenities')}
              goiYTrongO="Công viên trung tâm 12 ha, bể bơi ngoài trời 1.200 m², trường liên cấp, TTTM, phòng gym…"
            />
          </SectionCard>

          <SectionCard title="Quy mô và mật độ">
            <OSo
              ten="totalLandAreaM2"
              khoa={khoa}
              nhan="Tổng diện tích đất"
              unit="m²"
              format={areaWithHectare}
              giaTri={v.totalLandAreaM2 ?? null}
              doi={(x) => doi('totalLandAreaM2', x)}
              xong={() => xong('totalLandAreaM2')}
              min={0}
              loi={loiO(o.loi, 'totalLandAreaM2')}
              goiYTrongO="458000"
            />
            <OSo
              ten="floorAreaM2"
              khoa={khoa}
              nhan="Tổng diện tích sàn"
              unit="m²"
              giaTri={v.floorAreaM2 ?? null}
              doi={(x) => doi('floorAreaM2', x)}
              xong={() => xong('floorAreaM2')}
              min={0}
              loi={loiO(o.loi, 'floorAreaM2')}
              goiYTrongO="1250000"
            />
            <OSo
              ten="buildDensityPct"
              khoa={khoa}
              nhan="Mật độ xây dựng"
              unit="%"
              format={percent}
              giaTri={v.buildDensityPct ?? null}
              doi={(x) => doi('buildDensityPct', x)}
              xong={() => xong('buildDensityPct')}
              min={0}
              max={100}
              loi={loiO(o.loi, 'buildDensityPct')}
              goiYTrongO="0 – 100"
            />
            <OSo
              ten="numBuildings"
              khoa={khoa}
              nhan="Số toà"
              unit="toà"
              format={plainNumber}
              giaTri={v.numBuildings ?? null}
              doi={(x) => doi('numBuildings', x)}
              xong={() => xong('numBuildings')}
              min={0}
              buoc={1}
              loi={loiO(o.loi, 'numBuildings')}
              goiYTrongO="3"
            />
            <OSo
              ten="totalUnits"
              khoa={khoa}
              nhan="Tổng số căn"
              unit="căn"
              format={plainNumber}
              giaTri={v.totalUnits ?? null}
              doi={(x) => doi('totalUnits', x)}
              xong={() => xong('totalUnits')}
              min={0}
              buoc={1}
              loi={loiO(o.loi, 'totalUnits')}
              goiYTrongO="1240"
            />
            <OSo
              ten="totalInvestmentVnd"
              khoa={khoa}
              nhan="Tổng mức đầu tư"
              unit="đồng"
              format={vndLarge}
              giaTri={v.totalInvestmentVnd ?? null}
              doi={(x) => doi('totalInvestmentVnd', x)}
              xong={() => xong('totalInvestmentVnd')}
              min={0}
              buoc={1}
              loi={loiO(o.loi, 'totalInvestmentVnd')}
              goiYTrongO="23000000000000"
            />
            <CaHang>
              <OChu
                ten="productScale"
                khoa={khoa}
                nhan="Quy mô sản phẩm"
                giaTri={v.productScale ?? ''}
                doi={(x) => doi('productScale', x)}
                xong={() => xong('productScale')}
                loi={loiO(o.loi, 'productScale')}
                goiYTrongO="3 toà · 1.240 căn hộ · 68 shophouse"
              />
            </CaHang>
          </SectionCard>

          <SectionCard title="Phí dịch vụ">
            <OSo
              ten="managementFeeVndM2"
              khoa={khoa}
              nhan="Phí quản lý"
              unit="đ/m²/tháng"
              giaTri={v.managementFeeVndM2 ?? null}
              doi={(x) => doi('managementFeeVndM2', x)}
              xong={() => xong('managementFeeVndM2')}
              min={0}
              loi={loiO(o.loi, 'managementFeeVndM2')}
              goiYTrongO="15000"
            />
            <OSo
              ten="parkingCarFeeVnd"
              khoa={khoa}
              nhan="Gửi ô tô"
              unit="đ/xe/tháng"
              giaTri={v.parkingCarFeeVnd ?? null}
              doi={(x) => doi('parkingCarFeeVnd', x)}
              xong={() => xong('parkingCarFeeVnd')}
              min={0}
              loi={loiO(o.loi, 'parkingCarFeeVnd')}
              goiYTrongO="1500000"
            />
            <OSo
              ten="parkingMotoFeeVnd"
              khoa={khoa}
              nhan="Gửi xe máy"
              unit="đ/xe/tháng"
              giaTri={v.parkingMotoFeeVnd ?? null}
              doi={(x) => doi('parkingMotoFeeVnd', x)}
              xong={() => xong('parkingMotoFeeVnd')}
              min={0}
              loi={loiO(o.loi, 'parkingMotoFeeVnd')}
              goiYTrongO="120000"
            />
          </SectionCard>

          <SectionCard title="Sở hữu và bàn giao" cols={1}>
            <OChu
              ten="ownershipForm"
              khoa={khoa}
              nhan="Hình thức sở hữu"
              giaTri={v.ownershipForm ?? ''}
              doi={(x) => doi('ownershipForm', x)}
              xong={() => xong('ownershipForm')}
              loi={loiO(o.loi, 'ownershipForm')}
              goiYTrongO="Sổ hồng lâu dài · 50 năm"
            />
            <OHangMucBanGiao
              khoa={khoa}
              giaTri={v.handoverStandard ?? []}
              doi={(x) => doi('handoverStandard', x)}
              xong={() => xong('handoverStandard')}
              doiVaLuu={(x) => doiVaLuu('handoverStandard', x)}
              loi={loiO(o.loi, 'handoverStandard')}
            />
          </SectionCard>

          {o.loi != null && <DongTrangThai mau="alert">{cauLoi(o.loi, 'lưu dự án')}</DongTrangThai>}
        </div>

        <aside className="flex flex-col gap-4">
          <ImageCard
            title="Ảnh cover"
            media={cover}
            editing={dangSua}
            editor={
              <OMedia bare nhan="Ảnh cover" giaTri={cover} doi={(x) => doiVaLuu('coverMedia', x)} />
            }
          />
          <KbCard code={duAn.projectCode} published={duAn.status === 'published'} />
          <SectionCard title="Cập nhật" cols={1}>
            <ReadField label="Tạo">
              <span className="font-mono text-than">{ngayThangNam(new Date(duAn.createdAt))}</span>
            </ReadField>
            <ReadField label="Sửa lần cuối">
              <span className="font-mono text-than">{ngayGio(duAn.updatedAt)}</span>
            </ReadField>
          </SectionCard>
        </aside>
      </div>
    </div>
  )
}
