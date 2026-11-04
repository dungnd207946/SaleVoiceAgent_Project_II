# `contracts/` — BẢN SAO, không phải nguồn

**Đừng sửa file nào trong thư mục này bằng tay.**

Nguồn nằm ở repo backend: `odyssey-portal-backend/src/portal/core/auth/actions.py`. Thư mục này là
bản sao byte-for-byte của `odyssey-portal-backend/contracts/`, để `tests/actions-parity.test.ts`
canh được `src/lib/actions.ts` mà không cần với sang repo khác.

Lý lẽ đầy đủ (vì sao chọn cách này, hai cách kia hỏng ở đâu): `contracts/README.md` của repo backend.

## Đổi một action thì làm gì

Bốn bước, đúng thứ tự — sửa `src/lib/actions.ts` trước là làm cổng parity đỏ mà chưa sửa được gì:

```bash
# 1. repo backend: sửa src/portal/core/auth/actions.py
# 2. repo backend:
make contracts
# 3. từ thư mục cha chứa cả hai repo:
cp odyssey-portal-backend/contracts/actions.json odyssey-portal-frontend/contracts/actions.json
# 4. repo này: sửa src/lib/actions.ts cho khớp, rồi
npx vitest run tests/actions-parity.test.ts
```

Mở **một cặp MR, hai repo, cùng lúc**, ghi chéo link cho nhau. Đây là quy ước bù cho khoảng hở đã
biết: bước 3 là thao tác tay, nên BE đổi mà không ai copy sang thì **cả hai repo vẫn xanh** — lệch
chỉ lộ ra lúc chạy app. Chi tiết ở README bên repo backend.

## Artefact thứ hai — `audit-actions.json`

Nguồn BE: `src/portal/core/nhat_ky_ma.py` (`MA_TAT_CA` = mã đang ghi + mã đã nghỉ hưu). Sinh bằng
`make contracts` bên BE, copy tay sang đây; FE dùng ở `src/features/platform/so-hanh-dong.ts`.
Cổng `tests/audit-actions-parity.test.ts` canh: mọi mã phải có nhãn, sổ FE không có nhãn lạ, tiền
tố của mọi mã thuộc đúng một nhóm lọc.

Quy trình «BE thêm/bớt một điểm ghi nhật ký»: (1) BE thêm mã vào `nhat_ky_ma.py` rồi `make
contracts`; (2) copy `audit-actions.json` sang đây; (3) thêm/bỏ nhãn ở `so-hanh-dong.ts` (mã nghỉ
hưu GIỮ nhãn, hậu tố «(cũ)»); (4) `npx vitest run tests/audit-actions-parity.test.ts`.

Nhắc đúng khoảng hở đã nêu ở trên: cổng đọc BẢN SAO, nên quên bước copy thì cả hai repo vẫn xanh —
và artefact này trôi thường xuyên hơn `actions.json` (mỗi feature mới thường có một điểm ghi mới).
