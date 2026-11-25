// 🖼️ รูปภาพกลาง (media_images) — ใช้ร่วมทุกส่วน: บอร์ด · ประกาศ · กิจกรรม · โปรไฟล์
//
// ⚠️ `url`/`thumb_url` เป็น **path relative + ลายเซ็นผูกกับผู้ดู** (หมดอายุ 15 นาที)
//    ⇒ ต้องผ่าน `absoluteMediaUrl()` ก่อนใส่ `<img>` และ **ห้ามเก็บข้ามหน้า/ข้ามผู้ใช้**
//    (URL ที่ได้จากคนหนึ่งเปิดในนามคนอื่น = 403)

/** ชนิดเจ้าของรูป — ต้องตรงกับ registry ฝั่ง backend (`services/media_policies.py`) */
export type MediaOwnerType = 'board' | 'board_comment' | 'announcement' | 'event' | 'user'

/** ชนิดรูป — 1 ชนิดต่อ owner_type: board/event = cover · board_comment/announcement = attachment · user = avatar */
export type MediaKind = 'cover' | 'attachment' | 'avatar'

export interface MediaImage {
  id: string
  owner_type: MediaOwnerType
  owner_id: number
  kind: MediaKind
  /** path relative (`/api/media/file/...?variant=full&...`) — ใช้ผ่าน `absoluteMediaUrl()` */
  url: string
  thumb_url: string
  width: number
  height: number
  bytes: number
  created_at: string
}

/** เพดานที่ server อนุญาต — UI ห้าม hardcode ซ้ำ */
export interface MediaLimits {
  max_per_owner: number
  max_per_request: number
  size_limit_mb: number
}

export interface MediaImagesResponse {
  items: MediaImage[]
  limits: MediaLimits
}

/**
 * ค่าเริ่มต้นก่อนได้ `limits` จริงจาก server (GET แรก) — ใช้กับหน้า *สร้างใหม่* ที่ยังไม่มี id
 * ⇒ ไม่มี endpoint ให้ถามเพดานได้ทันที
 *
 * ⚠️ ค่าตรงกับ `.env.example` (`MEDIA_MAX_UPLOAD_PER_REQUEST=3`, `MEDIA_IMAGE_SIZE_LIMIT_MB=10`)
 *    และ `MediaPolicy.max_per_owner` ฝั่ง backend — **ไม่ใช่คำสัญญา** ด่านจริงอยู่ที่ server
 */
export const DEFAULT_MEDIA_LIMITS: MediaLimits = {
  max_per_owner: 1,
  max_per_request: 3,
  size_limit_mb: 10,
}
