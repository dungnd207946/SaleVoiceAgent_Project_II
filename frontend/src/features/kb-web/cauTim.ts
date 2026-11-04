/** `{project}`/`{location}` của API hiện thành `{dự án}`/`{khu vực}` cho người đọc, và ngược lại khi gửi. */
export function hienCau(q: string): string {
  return q.replaceAll('{project}', '{dự án}').replaceAll('{location}', '{khu vực}')
}

export function guiCau(q: string): string {
  return q.replaceAll('{dự án}', '{project}').replaceAll('{khu vực}', '{location}')
}
