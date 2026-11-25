<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import Swal from 'sweetalert2'
import { BRAND } from '@/constants/brand'
import AppButton from '@/components/ui/AppButton.vue'
import { uploadIssueImages } from '@/services/issue'
import { compressImages, isHeicLike } from '@/utils/imageCompress'
import type { IssueImage, IssueImageKind } from '@/types/issue'

/**
 * 📷 แนบรูปของเรื่อง — ใช้ได้ **2 โหมด**
 *
 * 1. **buffer mode** (`issueId` ไม่ส่ง/null) — เลือก/พรีวิวเท่านั้น ยังไม่ยิง network
 *    ⇒ หน้า `NewIssue` เก็บไฟล์ไว้ก่อน แล้วอัปโหลดหลังสร้างเรื่องสำเร็จ (ท่า 3.1)
 * 2. **immediate mode** (ส่ง `issueId`) — เลือกแล้วกด "แนบรูป" ยิงอัปโหลดทันที
 *    ⇒ หน้า `IssueDetail` ของผู้แจ้ง/ผู้รับปัจจุบัน
 *
 * 🔴 **ข้อความเตือนต้องอยู่ใต้ปุ่มเสมอ** — ผู้ใช้อาจไม่รู้ว่ารูปเป็นส่วนหนึ่งของเรื่อง
 *    และเพื่อนร่วมห้องเห็นได้ (visibility เท่ากับเรื่อง) การซ่อนข้อความนี้ = หลอกผู้ใช้
 */
const props = withDefaults(
  defineProps<{
    kind: IssueImageKind
    /** เพดานต่อชนิด — ค่าจาก `limits` ของ server ไม่ใช่ค่าคงที่ฝั่ง UI */
    maxCount: number
    /** จำนวนที่มีอยู่แล้วบน server (เฉพาะ immediate mode) */
    existingCount?: number
    sizeLimitMb?: number
    /** `null`/ไม่ส่ง = buffer mode */
    issueId?: number | null
    /** ไฟล์ที่เลือกไว้ — เฉพาะ buffer mode (ผูก `v-model:files`) */
    files?: File[]
    disabled?: boolean
  }>(),
  {
    existingCount: 0,
    sizeLimitMb: 10,
    issueId: null,
    files: () => [],
    disabled: false,
  },
)

const emit = defineEmits<{
  'update:files': [files: File[]]
  uploaded: [images: IssueImage[]]
}>()

const cameraInput = ref<HTMLInputElement | null>(null)
const albumInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

const isBuffer = computed(() => props.issueId == null)
const picked = ref<File[]>([])

/** object URL ต่อไฟล์ — ต้อง revoke เมื่อเอาไฟล์ออก/component ถูกทำลาย ไม่งั้นหน่วยความจำค้าง */
const previews = new Map<File, string>()

function previewFor(file: File): string {
  let url = previews.get(file)
  if (!url) {
    url = URL.createObjectURL(file)
    previews.set(file, url)
  }
  return url
}

function revoke(file: File): void {
  const url = previews.get(file)
  if (url) {
    URL.revokeObjectURL(url)
    previews.delete(file)
  }
}

watch(
  () => props.files,
  (next) => {
    if (!isBuffer.value) return
    // ล้าง preview ของไฟล์ที่พ่อถอดออก (เช่นหลังส่งฟอร์มสำเร็จ)
    for (const f of picked.value) if (!next.includes(f)) revoke(f)
    picked.value = [...next]
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  for (const f of picked.value) revoke(f)
})

const usedCount = computed(() => props.existingCount + picked.value.length)
const remaining = computed(() => Math.max(0, props.maxCount - usedCount.value))

function setPicked(next: File[]): void {
  // revoke เฉพาะไฟล์ที่ถูกถอด
  for (const f of picked.value) if (!next.includes(f)) revoke(f)
  picked.value = next
  if (isBuffer.value) emit('update:files', next)
}

function pickerError(text: string): void {
  void Swal.fire({
    icon: 'error',
    title: 'แนบรูปไม่ได้',
    text,
    confirmButtonColor: BRAND,
  })
}

const MAX_BYTES = computed(() => props.sizeLimitMb * 1024 * 1024)

function isAcceptableType(file: File): boolean {
  return file.type.startsWith('image/') || isHeicLike(file)
}

/**
 * รับไฟล์จาก `<input>` — ตรวจชนิด/ขนาด/จำนวนก่อน แล้วค่อยเพิ่ม
 *
 * ⚠️ ตรวจซ้ำที่ server เสมอ — การตรวจฝั่งนี้เป็น UX (บอกทันที) ไม่ใช่ด่านความปลอดภัย
 */
function onFiles(event: Event): void {
  const input = event.target as HTMLInputElement
  const incoming = Array.from(input.files ?? [])
  input.value = '' // ให้เลือกไฟล์เดิมซ้ำได้ (change event เกิดใหม่)
  if (!incoming.length) return

  const accepted: File[] = []
  let slots = remaining.value
  let skippedBig = 0
  let skippedType = 0
  let skippedCount = 0

  for (const f of incoming) {
    if (!isAcceptableType(f)) {
      skippedType++
      continue
    }
    if (f.size > MAX_BYTES.value) {
      skippedBig++
      continue
    }
    if (slots <= 0) {
      skippedCount++
      continue
    }
    accepted.push(f)
    slots--
  }

  if (skippedType || skippedBig || skippedCount) {
    const parts: string[] = []
    if (skippedType) parts.push(`${skippedType} ไฟล์ไม่ใช่รูป`)
    if (skippedBig) parts.push(`${skippedBig} ไฟล์ใหญ่เกิน ${props.sizeLimitMb} MB`)
    if (skippedCount) parts.push(`${skippedCount} ไฟล์เกินจำนวนที่แนบได้ (${props.maxCount} รูป)`)
    pickerError(parts.join(' · '))
  }

  if (accepted.length) setPicked([...picked.value, ...accepted])
}

function removeAt(index: number): void {
  const next = picked.value.filter((_, i) => i !== index)
  setPicked(next)
}

/** immediate mode — ย่อรูปในเครื่องก่อน แล้วส่งพร้อมกันในคำขอเดียว */
async function uploadNow(): Promise<void> {
  if (isBuffer.value || !picked.value.length || uploading.value || props.disabled) return
  const issueId = props.issueId
  if (issueId == null) return

  uploading.value = true
  try {
    const prepared = await compressImages(picked.value)
    const res = await uploadIssueImages(issueId, prepared, props.kind)
    const uploaded = res.items
    setPicked([])
    emit('uploaded', uploaded)
  } catch (e) {
    void Swal.fire({
      icon: 'error',
      title: 'แนบรูปไม่สำเร็จ',
      text: e instanceof Error ? e.message : 'เกิดข้อผิดพลาด กรุณาลองใหม่',
      confirmButtonColor: BRAND,
    })
  } finally {
    uploading.value = false
  }
}

defineExpose({ uploadNow })
</script>

<template>
  <div class="rounded-card border border-line bg-canvas p-3">
    <div class="flex flex-wrap items-center gap-2">
      <input
        ref="cameraInput"
        type="file"
        accept="image/*"
        capture="environment"
        class="hidden"
        data-testid="issue-image-camera"
        @change="onFiles"
      />
      <input
        ref="albumInput"
        type="file"
        accept="image/*,image/heic,image/heif"
        multiple
        class="hidden"
        data-testid="issue-image-album"
        @change="onFiles"
      />

      <AppButton
        variant="secondary"
        size="sm"
        :disabled="disabled || uploading || remaining <= 0"
        @click="cameraInput?.click()"
      >
        <template #icon><i class="bi bi-camera" /></template>
        ถ่ายรูป
      </AppButton>
      <AppButton
        variant="secondary"
        size="sm"
        :disabled="disabled || uploading || remaining <= 0"
        @click="albumInput?.click()"
      >
        <template #icon><i class="bi bi-image" /></template>
        เลือกจากอัลบั้ม
      </AppButton>

      <span class="ml-auto text-[13px] font-medium tabular-nums text-ink-3">
        {{ usedCount }}/{{ maxCount }} รูป
      </span>
    </div>

    <!-- ⚠️ ข้อความเตือน privacy — ต้องแสดงเสมอเมื่อมีช่องแนบรูป -->
    <p class="mt-2 flex items-start gap-1.5 text-[12px] leading-relaxed text-ink-3">
      <i class="bi bi-eye mt-0.5 shrink-0" aria-hidden="true" />
      <span>รูปนี้จะถูกมองเห็นโดยเพื่อนร่วมห้องและคณะห้องผู้รับเรื่อง</span>
    </p>

    <ul v-if="picked.length" class="mt-3 grid grid-cols-3 gap-2">
      <li v-for="(file, i) in picked" :key="`${file.name}-${i}`" class="relative">
        <img
          :src="previewFor(file)"
          :alt="`รูปที่เลือก ${i + 1}: ${file.name}`"
          class="h-24 w-full rounded-control border border-line object-cover"
          loading="lazy"
        />
        <button
          type="button"
          class="tap-44 absolute -right-1.5 -top-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-ink-1 text-white shadow-sm"
          :aria-label="`เอารูป ${file.name} ออก`"
          :disabled="uploading"
          @click="removeAt(i)"
        >
          <i class="bi bi-x-lg text-xs" aria-hidden="true" />
        </button>
      </li>
    </ul>

    <div v-if="!isBuffer && picked.length" class="mt-3">
      <AppButton size="sm" block :loading="uploading" @click="uploadNow">
        <template #icon><i class="bi bi-cloud-arrow-up" /></template>
        แนบ {{ picked.length }} รูป
      </AppButton>
    </div>
  </div>
</template>
