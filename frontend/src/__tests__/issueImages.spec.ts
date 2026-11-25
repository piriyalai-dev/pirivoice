import { describe, expect, it } from 'vitest'
import { canUploadToIssueStatus, receiptLabel } from '@/utils/issueImages'
import { absoluteMediaUrl, formatBytes } from '@/utils/media'
import type { IssueImageReceipt } from '@/types/issue'

function receipt(over: Partial<IssueImageReceipt> = {}): IssueImageReceipt {
  return {
    current_assignee_viewed: false,
    current_assignee_viewed_at: null,
    other_viewer_count: 0,
    last_viewed_at: null,
    ...over,
  }
}

describe('canUploadToIssueStatus', () => {
  it('เรื่องที่ยังเปิดอยู่แนบได้', () => {
    for (const s of ['pending', 'in_progress', 'escalated']) {
      expect(canUploadToIssueStatus(s)).toBe(true)
    }
  })

  it('เรื่องที่ปิดแล้วแนบเพิ่มไม่ได้', () => {
    for (const s of ['resolved', 'cancelled', 'rejected']) {
      expect(canUploadToIssueStatus(s)).toBe(false)
    }
  })
})

describe('receiptLabel', () => {
  it('ผู้รับ/admin เห็น receipt เป็น null ⇒ ไม่มีป้าย', () => {
    expect(receiptLabel(null, true)).toBeNull()
  })

  it('ยังไม่มีผู้รับ — บอกตรง ๆ ว่าไม่มีผู้รับ ไม่ใช่ "ยังไม่เปิด"', () => {
    expect(receiptLabel(receipt(), false)).toBe('ยังไม่มีผู้รับเรื่อง')
  })

  it('ผู้รับเปิดแล้ว', () => {
    expect(receiptLabel(receipt({ current_assignee_viewed: true }), true)).toBe(
      'ผู้รับผิดชอบเปิดดูแล้ว',
    )
  })

  it('มีแต่เพื่อนร่วมห้องเปิด — ไม่ปนกับสถานะของผู้รับ', () => {
    expect(receiptLabel(receipt({ other_viewer_count: 2 }), true)).toBe(
      'มี 2 คนเปิดดูแล้ว · ผู้รับยังไม่เปิด',
    )
  })

  it('ผู้รับยังไม่เปิด และไม่มีใครเปิด', () => {
    expect(receiptLabel(receipt(), true)).toBe('ผู้รับผิดชอบยังไม่เปิดดู')
  })
})

describe('absoluteMediaUrl', () => {
  it('เติม origin ให้ path relative', () => {
    expect(absoluteMediaUrl('/api/images/x?exp=1')).toMatch(/^http:\/\/localhost:8000\/api\/images\/x/)
  })

  it('ไม่แตะ absolute URL', () => {
    expect(absoluteMediaUrl('https://cdn.example.com/a.webp')).toBe('https://cdn.example.com/a.webp')
  })
})

describe('formatBytes', () => {
  it('แสดง KB/MB แบบอ่านง่าย', () => {
    expect(formatBytes(0)).toBe('0 KB')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB')
  })
})
