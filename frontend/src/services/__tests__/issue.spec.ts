import { describe, it, expect, beforeEach, vi } from 'vitest'

// mock axios instance — ทดสอบเฉพาะ service layer ไม่ต้องมี backend จริง
const { getMock, patchMock, postMock, deleteMock } = vi.hoisted(() => ({
  getMock: vi.fn<(url: string, config?: unknown) => Promise<unknown>>(),
  patchMock: vi.fn<(url: string, data?: unknown) => Promise<unknown>>(),
  postMock: vi.fn<(url: string, data?: unknown, config?: unknown) => Promise<unknown>>(),
  deleteMock: vi.fn<(url: string) => Promise<unknown>>(),
}))
vi.mock('@/services/api', () => ({
  default: { get: getMock, patch: patchMock, post: postMock, delete: deleteMock },
}))

import {
  listIssues,
  updateIssue,
  createComment,
  updateComment,
  deleteComment,
  changeDestination,
  getIssueImages,
  uploadIssueImages,
  deleteIssueImage,
} from '@/services/issue'

describe('issue services (รายการ/แก้ไขเรื่อง + คอมเมนต์)', () => {
  beforeEach(() => {
    getMock.mockReset()
    patchMock.mockReset()
    postMock.mockReset()
    deleteMock.mockReset()
  })

  it('listIssues → GET /api/issues พร้อม params และ unwrap เป็น IssueListResponse (envelope)', async () => {
    const fakeRes = {
      items: [{ id: 1, title: 'เรื่องแรก' }],
      total: 42,
      page: 2,
      page_size: 20,
      pages: 3,
    }
    getMock.mockResolvedValue(fakeRes)

    const result = await listIssues({
      received: true,
      q: 'พัดลม',
      sort: 'asc',
      limit: 20,
      offset: 20,
    })

    expect(getMock).toHaveBeenCalledTimes(1)
    expect(getMock).toHaveBeenCalledWith('/api/issues', {
      params: { received: true, q: 'พัดลม', sort: 'asc', limit: 20, offset: 20 },
    })
    expect(result).toEqual(fakeRes)
  })

  it('updateIssue → PATCH /api/issues/{id} (ต้องมี prefix /api)', async () => {
    const fakeIssue = { id: 7, title: 'แก้ไขแล้ว' }
    patchMock.mockResolvedValue(fakeIssue)

    const result = await updateIssue(7, { title: 'แก้ไขแล้ว', is_anonymous: false })

    expect(patchMock).toHaveBeenCalledTimes(1)
    expect(patchMock).toHaveBeenCalledWith('/api/issues/7', {
      title: 'แก้ไขแล้ว',
      is_anonymous: false,
    })
    expect(result).toEqual(fakeIssue)
  })

  it('createComment → POST /api/issues/{id}/comments', async () => {
    const fakeComment = { id: 1, body: 'รับทราบ' }
    postMock.mockResolvedValue(fakeComment)

    const result = await createComment(7, 'รับทราบ')

    expect(postMock).toHaveBeenCalledWith('/api/issues/7/comments', { body: 'รับทราบ' })
    expect(result).toEqual(fakeComment)
  })

  it('updateComment → PATCH /api/issues/{id}/comments/{cid}', async () => {
    const fakeComment = { id: 1, body: 'แก้แล้ว' }
    patchMock.mockResolvedValue(fakeComment)

    const result = await updateComment(7, 1, 'แก้แล้ว')

    expect(patchMock).toHaveBeenCalledWith('/api/issues/7/comments/1', { body: 'แก้แล้ว' })
    expect(result).toEqual(fakeComment)
  })

  it('deleteComment → DELETE /api/issues/{id}/comments/{cid}', async () => {
    deleteMock.mockResolvedValue({ status: 'ok' })

    await deleteComment(7, 1)

    expect(deleteMock).toHaveBeenCalledWith('/api/issues/7/comments/1')
  })

  it('changeDestination → PATCH /api/issues/{id}/destination ส่ง requested_destination', async () => {
    const fakeIssue = { id: 7, requested_destination: 'talk', current_level: 'council' }
    patchMock.mockResolvedValue(fakeIssue)

    const result = await changeDestination(7, 'talk')

    expect(patchMock).toHaveBeenCalledWith('/api/issues/7/destination', {
      requested_destination: 'talk',
    })
    expect(result).toEqual(fakeIssue)
  })
})

describe('issue image services', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    deleteMock.mockReset()
  })

  it('getIssueImages → GET รายการรูปแบบ noCache (signed URL ต้องสด)', async () => {
    const fake = { items: [], limits: { max_report: 3, max_progress: 3, max_per_request: 3, size_limit_mb: 10 } }
    getMock.mockResolvedValue(fake)

    const result = await getIssueImages(12)

    expect(getMock).toHaveBeenCalledWith('/api/issues/12/images', { noCache: true })
    expect(result).toEqual(fake)
  })

  it('uploadIssueImages → multipart files + kind', async () => {
    const fake = { items: [], limits: { max_report: 3, max_progress: 3, max_per_request: 3, size_limit_mb: 10 } }
    postMock.mockResolvedValue(fake)
    const a = new File([new Uint8Array([1])], 'a.jpg', { type: 'image/jpeg' })
    const b = new File([new Uint8Array([2])], 'b.webp', { type: 'image/webp' })

    const result = await uploadIssueImages(12, [a, b], 'report')

    expect(postMock).toHaveBeenCalledTimes(1)
    const [url, body, config] = postMock.mock.calls[0] as unknown as [
      string,
      FormData,
      { headers: Record<string, string> },
    ]
    expect(url).toBe('/api/issues/12/images')
    expect(body).toBeInstanceOf(FormData)
    expect(body.getAll('files')).toHaveLength(2)
    expect(body.get('kind')).toBe('report')
    expect(config.headers['Content-Type']).toBe('multipart/form-data')
    expect(result).toEqual(fake)
  })

  it('uploadIssueImages ไม่ส่ง kind เมื่อไม่ระบุ', async () => {
    postMock.mockResolvedValue({ items: [], limits: {} })
    await uploadIssueImages(3, [new File([new Uint8Array([1])], 'a.jpg', { type: 'image/jpeg' })])
    const body = postMock.mock.calls[0]?.[1] as FormData
    expect(body.get('kind')).toBeNull()
  })

  it('deleteIssueImage → DELETE ตาม id รูป', async () => {
    deleteMock.mockResolvedValue(undefined)
    await deleteIssueImage(12, 'img-uuid')
    expect(deleteMock).toHaveBeenCalledWith('/api/issues/12/images/img-uuid')
  })
})
