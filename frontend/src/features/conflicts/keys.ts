/** Khoá React Query của cảnh báo mâu thuẫn — mọi khoá bắt đầu bằng `conflicts` để làm mới một lượt. */
export const SUMMARY_KEY = ['conflicts', 'summary'] as const
export const projectKey = (code: string) => ['conflicts', 'project', code] as const
