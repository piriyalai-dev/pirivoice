import api from './api'
import type { MediaImagesResponse, MediaKind, MediaOwnerType } from '@/types/media'

// 🖼️ รูปภาพกลาง (media_images) — ใช้ร่วมทุกส่วน
// ⚠️ ทุก GET ต้อง `noCache` : `url`/`thumb_url` มีลายเซ็นอายุ 15 นาที
//    ⇒ คำตอบที่แคชไว้จะพา URL ที่หมดอายุแล้วกลับมาให้ `<img>` → 403 เงียบ ๆ

export async function getMedia(
  ownerType: MediaOwnerType,
  ownerId: number,
): Promise<MediaImagesResponse> {
  return (await api.get(`/api/media/${ownerType}/${ownerId}`, {
    noCache: true,
  })) as MediaImagesResponse
}

/**
 * อัปโหลดรูปให้เจ้าของหนึ่งราย (multipart `files`)
 *
 * @param kind — ปกติไม่ต้องส่ง (backend ใช้ชนิดของเจ้าของเอง) · ส่งได้เพื่อความชัดเจน
 */
export async function uploadMedia(
  ownerType: MediaOwnerType,
  ownerId: number,
  files: File[],
  kind?: MediaKind,
): Promise<MediaImagesResponse> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  if (kind) form.append('kind', kind)

  return (await api.post(`/api/media/${ownerType}/${ownerId}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })) as MediaImagesResponse
}

/** ลบรูป (soft delete) — ผู้อัปหรือผู้จัดการเนื้อหานั้น */
export async function deleteMedia(
  ownerType: MediaOwnerType,
  ownerId: number,
  imageId: string,
): Promise<void> {
  await api.delete(`/api/media/${ownerType}/${ownerId}/${imageId}`)
}
