import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '../vitest.setup'
import {
  checkConflicts,
  conflictSummary,
  dismissConflict,
  projectConflicts,
  scanAll,
  scanProject,
} from '../src/features/conflicts/api'

describe('API cảnh báo mâu thuẫn', () => {
  it('gọi đúng đường dẫn và phương thức', async () => {
    const goi: string[] = []
    server.use(
      http.get('/api/v1/conflicts/summary', () => (goi.push('GET summary'), HttpResponse.json([]))),
      http.get(
        '/api/v1/projects/:code/conflicts',
        ({ params }) => (goi.push(`GET ${params.code}`), HttpResponse.json([])),
      ),
      http.get('/api/v1/projects/:code/conflicts/check', ({ request }) => {
        goi.push(`GET check ${new URL(request.url).searchParams.get('since')}`)
        return HttpResponse.json({ checking: false, failed: false, conflicts: [] })
      }),
      http.post(
        '/api/v1/projects/:code/conflicts/scan',
        () => (goi.push('POST scan nplb'), HttpResponse.json({ jobId: 1 }, { status: 202 })),
      ),
      http.post(
        '/api/v1/conflicts/scan',
        () => (goi.push('POST scan all'), HttpResponse.json({ queued: 2 }, { status: 202 })),
      ),
      http.post(
        '/api/v1/conflicts/:id/dismiss',
        ({ params }) => (
          goi.push(`POST dismiss ${params.id}`),
          new HttpResponse(null, { status: 204 })
        ),
      ),
    )
    await conflictSummary()
    await projectConflicts('nplb')
    await checkConflicts('nplb', '2026-10-14T00:00:00Z')
    expect(await scanProject('nplb')).toEqual({ jobId: 1 })
    expect(await scanAll()).toEqual({ queued: 2 })
    await dismissConflict(41)
    expect(goi).toEqual([
      'GET summary',
      'GET nplb',
      'GET check 2026-10-14T00:00:00Z',
      'POST scan nplb',
      'POST scan all',
      'POST dismiss 41',
    ])
  })
})
