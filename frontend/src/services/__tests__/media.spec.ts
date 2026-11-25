import { describe, it, expect, beforeEach, vi } from 'vitest'

// mock axios instance — ทดสอบเฉพาะ service layer ไม่ต้องมี backend จริง
const { getMock, postMock, deleteMock } = vi.hoisted(() => ({
  getMock: vi.fn<(url: string, config?: unknown) => Promise<unknown>>(),
  postMock: vi.fn<(url: string, data?: unknown, config?: unknown) => Promise<unknown>>(),
  deleteMock: vi.fn<(url: string) => Promise<unknown>>(),
}))
vi.mock('@/services/api', () => ({
  default: { get: getMock, post: postMock, delete: deleteMock },
}))

import { getMedia, uploadMedia, deleteMedia } from '@/services/media'
import { DEFAULT_MEDIA_LIMITS } from '@/types/media'

function fakeFile(name: string, type = 'image/jpeg'): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type })
}

describe('media services (รูปภาพกลาง)', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    deleteMock.mockReset()
  })

  it('getMedia → GET /api/media/{owner_type}/{owner_id} พร้อม noCache', async () => {
    const fake = { items: [], limits: DEFAULT_MEDIA_LIMITS }
    getMock.mockResolvedValue(fake)

    const result = await getMedia('board', 42)

    expect(getMock).toHaveBeenCalledWith('/api/media/board/42', { noCache: true })
    expect(result).toEqual(fake)
  })

  it('getMedia ต้องส่ง noCache เสมอ — URL มีลายเซ็นอายุ 15 นาที (แคชแล้วได้ URL ตาย)', async () => {
    getMock.mockResolvedValue({ items: [], limits: DEFAULT_MEDIA_LIMITS })

    await getMedia('board_comment', 9)

    const config = (getMock.mock.calls[0]?.[1] ?? {}) as { noCache?: boolean }
    expect(config.noCache).toBe(true)
  })

  it('uploadMedia → POST multipart ที่ /api/media/{owner_type}/{owner_id} และแนบทุกไฟล์ในฟิลด์ `files`', async () => {
    const fake = { items: [{ id: 'abc' }], limits: DEFAULT_MEDIA_LIMITS }
    postMock.mockResolvedValue(fake)

    const a = fakeFile('a.jpg')
    const b = fakeFile('b.jpg')
    const result = await uploadMedia('board', 42, [a, b])

    expect(postMock).toHaveBeenCalledTimes(1)
    const [url, body, config] = (postMock.mock.calls[0] ?? []) as [string, FormData, unknown]
    expect(url).toBe('/api/media/board/42')
    expect(body).toBeInstanceOf(FormData)

    const form = body as FormData
    expect(form.getAll('files')).toEqual([a, b])
    // ⚠️ ไม่ส่ง `kind` เมื่อไม่ได้ระบุ — backend ใช้ชนิดของเจ้าของเอง
    expect(form.has('kind')).toBe(false)

    expect(config).toEqual({ headers: { 'Content-Type': 'multipart/form-data' } })
    expect(result).toEqual(fake)
  })

  it('uploadMedia ส่ง kind เมื่อระบุ — และไม่ใส่ header Content-Type เองนอก multipart', async () => {
    postMock.mockResolvedValue({ items: [], limits: DEFAULT_MEDIA_LIMITS })

    await uploadMedia('user', 7, [fakeFile('avatar.png', 'image/png')], 'avatar')

    const form = postMock.mock.calls[0]?.[1] as FormData
    expect(form.get('kind')).toBe('avatar')
  })

  it('deleteMedia → DELETE /api/media/{owner_type}/{owner_id}/{image_id}', async () => {
    deleteMock.mockResolvedValue(undefined)

    await deleteMedia('event', 5, '11111111-2222-3333-4444-555555555555')

    expect(deleteMock).toHaveBeenCalledWith(
      '/api/media/event/5/11111111-2222-3333-4444-555555555555',
    )
  })

  it('DEFAULT_MEDIA_LIMITS ตรงกับ .env.example (เพดานปก/แนบ = 1 รูป, 10 MB)', () => {
    expect(DEFAULT_MEDIA_LIMITS.max_per_owner).toBe(1)
    expect(DEFAULT_MEDIA_LIMITS.max_per_request).toBe(3)
    expect(DEFAULT_MEDIA_LIMITS.size_limit_mb).toBe(10)
  })
})
