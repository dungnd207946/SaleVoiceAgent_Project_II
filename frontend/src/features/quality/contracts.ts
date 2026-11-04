/**
 * Mặt tiền công khai của `features/quality` — module KHÁC (`ops`) chỉ được
 * import từ đây, không import ruột `api.ts`/`components/*` (luật ranh giới
 * module, `tests/module-boundaries.test.ts`).
 */
export type { Feedback } from './api'
export { feedbackCuaPhien } from './api'
