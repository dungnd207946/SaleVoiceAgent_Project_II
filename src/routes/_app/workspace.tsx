import { createFileRoute } from '@tanstack/react-router'
import { CaiDatWorkspace } from '@/features/workspace/components/CaiDatWorkspace'

export const Route = createFileRoute('/_app/workspace')({
  component: CaiDatWorkspace,
})
