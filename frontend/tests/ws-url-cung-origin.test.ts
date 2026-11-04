import { describe, expect, it } from 'vitest'
import { wsUrlCungOrigin } from '../src/features/platform/api'

describe('wsUrlCungOrigin', () => {
  it('https → wss, giữ nguyên host của portal', () => {
    expect(
      wsUrlCungOrigin('/v1/chat', { protocol: 'https:', host: 'agent-portal-dev.noble.vn' }),
    ).toBe('wss://agent-portal-dev.noble.vn/v1/chat')
  })
  it('http (local) → ws, giữ cả cổng', () => {
    expect(wsUrlCungOrigin('/v1/voice', { protocol: 'http:', host: 'localhost:5173' })).toBe(
      'ws://localhost:5173/v1/voice',
    )
  })
})
