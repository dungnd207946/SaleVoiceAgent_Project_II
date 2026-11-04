import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

export const kichBanNav: NavLeaf = {
  kind: 'leaf',
  key: 'kich-ban',
  path: '/kich-ban',
  label: { vi: 'Kịch bản', en: 'Playbook' },
  icon: 'kichBan',
  requiredActions: [ACTIONS.AGENT_CONFIG_READ],
}
