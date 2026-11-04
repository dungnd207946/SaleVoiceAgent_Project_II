import { createFileRoute } from '@tanstack/react-router'
import { HoSoScreen } from '@/features/auth/components/HoSoScreen'

export const Route = createFileRoute('/_app/settings')({
  component: HoSoScreen,
})
