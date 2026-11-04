/**
 * Nối một `NhomTab` (có `idPanel`) với vùng nội dung của nó — `aria-controls` ở
 * tab, `role="tabpanel"` + `aria-labelledby` ở vùng. Trải lên phần tử ĐANG CÓ của
 * màn (`<div {...panelTab(ID, dangMo)}>`), không bọc thêm thẻ: vùng tab của các màn
 * nằm trong khung flex, một lớp bọc mới là đổi bố cục. Audit 05/10: 9 tab, 0 tabpanel.
 */
export const idTab = (idPanel: string, id: string) => `${idPanel}-${id}`

export function panelTab(idPanel: string, dangMo: string) {
  return { role: 'tabpanel', id: idPanel, 'aria-labelledby': idTab(idPanel, dangMo) } as const
}
