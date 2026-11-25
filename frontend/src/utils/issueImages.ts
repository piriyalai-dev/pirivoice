// 🖼️ ตรรกะเล็ก ๆ ของหน้าจอรูปเรื่อง — แยกไว้ให้เทสต์ได้โดยไม่ต้อง mount component
import type { IssueImageKind, IssueImageReceipt } from '@/types/issue'

export const ISSUE_STATUS_CLOSED: readonly string[] = ['resolved', 'cancelled', 'rejected']

/** เรื่องที่ปิดแล้วยังดูรูปได้ แต่ไม่เปิดช่องให้แนบเพิ่ม (backend ลบรูปก็บล็อกอยู่แล้ว) */
export function canUploadToIssueStatus(status: string): boolean {
  return !ISSUE_STATUS_CLOSED.includes(status)
}

export const KIND_LABELS: Record<IssueImageKind, string> = {
  report: 'หลักฐานตอนแจ้ง',
  progress: 'ความคืบหน้า',
}

/**
 * ข้อความป้าย "เปิดดูหรือยัง" สำหรับผู้แจ้ง
 *
 * @param hasAssignee — เรื่องยังไม่มีผู้รับ ⇒ แยกจาก "มีผู้รับแต่ยังไม่เปิด" ให้ผู้ใช้เข้าใจ
 * @returns `null` = ไม่ควรแสดงป้าย (ผู้รับ/admin เองเห็น receipt เป็น null อยู่แล้ว)
 */
export function receiptLabel(
  receipt: IssueImageReceipt | null,
  hasAssignee: boolean,
): string | null {
  if (!receipt) return null
  if (!hasAssignee) return 'ยังไม่มีผู้รับเรื่อง'
  if (receipt.current_assignee_viewed) return 'ผู้รับผิดชอบเปิดดูแล้ว'
  if (receipt.other_viewer_count > 0) {
    return `มี ${receipt.other_viewer_count} คนเปิดดูแล้ว · ผู้รับยังไม่เปิด`
  }
  return 'ผู้รับผิดชอบยังไม่เปิดดู'
}
