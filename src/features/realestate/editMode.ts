/** Cờ đang sửa của một dự án — dùng chung cho `/pform` và `/uform`, nên sang màn một căn vẫn đang sửa. */
import { useSyncExternalStore } from 'react'

let editingCode: string | null = null
const listeners = new Set<() => void>()

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useEditing(code: string | undefined): boolean {
  return useSyncExternalStore(subscribe, () => code !== undefined && editingCode === code)
}

export function setEditing(code: string | null): void {
  if (editingCode === code) return
  editingCode = code
  listeners.forEach((listener) => listener())
}
