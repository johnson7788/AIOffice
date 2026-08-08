import { describe, expect, it, vi } from 'vitest'
import '../src/renderer/web-adapter' // installs window.desktop

const enc = new TextEncoder()

function sseBody(parts: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(c) {
      for (const p of parts) c.enqueue(enc.encode(p))
      c.close()
    },
  })
}

// aiStream kicks off async stream reading; resolve once a terminal chunk lands
function collectUntilDone(): Promise<Array<Record<string, unknown>>> {
  return new Promise((resolve) => {
    const got: Array<Record<string, unknown>> = []
    const off = window.desktop.onAiStream((chunk) => {
      const c = chunk as Record<string, unknown>
      got.push(c)
      if (c.type === 'done' || c.type === 'error') {
        off()
        resolve(got)
      }
    })
  })
}

describe('web-adapter aiStream SSE parsing', () => {
  it('parses data frames, including one split across stream chunks', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        body: sseBody([
          'data: {"requestId":"r1","type":"delta","text":"He"}\n\n',
          'data: {"requestId":"r1","typ', // frame deliberately split mid-JSON
          'e":"delta","text":"llo"}\n\n',
          'data: {"requestId":"r1","type":"done","stopReason":"stop"}\n\n',
        ]),
      })),
    )
    const done = collectUntilDone()
    await window.desktop.aiStream({ requestId: 'r1' } as Parameters<typeof window.desktop.aiStream>[0])
    expect(await done).toEqual([
      { requestId: 'r1', type: 'delta', text: 'He' },
      { requestId: 'r1', type: 'delta', text: 'llo' },
      { requestId: 'r1', type: 'done', stopReason: 'stop' },
    ])
  })

  it('emits an error chunk on a non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, body: null })))
    const done = collectUntilDone()
    await window.desktop.aiStream({ requestId: 'r2' } as Parameters<typeof window.desktop.aiStream>[0])
    expect(await done).toEqual([{ requestId: 'r2', type: 'error', error: 'HTTP 500' }])
  })
})
