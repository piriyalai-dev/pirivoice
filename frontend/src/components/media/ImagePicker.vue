<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import Swal from 'sweetalert2'
import { BRAND } from '@/constants/brand'
import AppButton from '@/components/ui/AppButton.vue'
import { isHeicLike } from '@/utils/imageCompress'

/**
 * 📷 เลือกรูป (กล้อง/อัลบั้ม) — **presentational เท่านั้น** ไม่เรียก service เอง
 *
 * ใช้ได้ 2 ทาง:
 * - `v-model:files` — พ่อคุมไฟล์ที่เลือก แล้วค่อยอัปโหลดเอง (ท่า "สร้างก่อน แล้วอัป")
 * - ไม่ผูก v-model — พ่อฟัง `@change` รับไฟล์ไปทำอะไรก็ได้
 *
 * ⚠️ **ตรวจฝั่งนี้เป็น UX ไม่ใช่ด่านความปลอดภัย** — server ตรวจชนิด/ขนาด/จำนวนซ้ำเสมอ
 * ⚠️ object URL ของ preview ต้องถูก revoke เสมอ (ถอดรูปออก/component ถูกทำลาย/พ่อล้างไฟล์)
 *    ไม่งั้นหน่วยความจำค้างในแท็บที่เปิดนาน (มือถือจะเริ่มช้าเงียบ ๆ)
 */
const props = withDefaults(
  defineProps<{
    /** ไฟล์ที่เลือกอยู่ (v-model:files) */
    files?: File[]
    /** เพดานจำนวนรูปของ "ที่นี้" — ค่าจาก limits ของ server ไม่ใช่ค่าคงที่ */
    maxCount?: number
    /** จำนวนรูปที่มีอยู่แล้วบน server (นับรวมกับที่เลือกใหม่) */
    existingCount?: number
    sizeLimitMb?: number
    disabled?: boolean
    /** ข้อความใต้ปุ่ม — บอกว่ารูปนี้ใครเห็นได้ (ต้องไม่หลอกผู้ใช้) */
    hint?: string
  }>(),
  {
    files: () => [],
    maxCount: 1,
    existingCount: 0,
    sizeLimitMb: 10,
    disabled: false,
    hint: '',
  },
)

const emit = defineEmits<{
  'update:files': [files: File[]]
  change: [files: File[]]
}>()

const cameraInput = ref<HTMLInputElement | null>(null)
const albumInput = ref<HTMLInputElement | null>(null)
const picked = ref<File[]>([])

/** object URL ต่อไฟล์ — revoke เมื่อเอาไฟล์ออก/component ถูกทำลาย */
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
    // ล้าง preview ของไฟล์ที่พ่อถอดออก (เช่นหลังอัปโหลดสำเร็จ)
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
const MAX_BYTES = computed(() => props.sizeLimitMb * 1024 * 1024)

function setPicked(next: File[]): void {
  for (const f of picked.value) if (!next.includes(f)) revoke(f)
  picked.value = next
  emit('update:files', next)
  emit('change', next)
}

function pickerError(text: string): void {
  void Swal.fire({
    icon: 'error',
    title: 'แนบรูปไม่ได้',
    text,
    confirmButtonColor: BRAND,
  })
}

function isAcceptableType(file: File): boolean {
  return file.type.startsWith('image/') || isHeicLike(file)
}

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
  setPicked(picked.value.filter((_, i) => i !== index))
}

/** ให้พ่อล้างไฟล์หลังอัปสำเร็จ */
function clear(): void {
  setPicked([])
}

defineExpose({ clear })
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
        data-testid="image-picker-camera"
        @change="onFiles"
      />
      <input
        ref="albumInput"
        type="file"
        accept="image/*,image/heic,image/heif"
        :multiple="maxCount - existingCount > 1"
        class="hidden"
        data-testid="image-picker-album"
        @change="onFiles"
      />

      <AppButton
        variant="secondary"
        size="sm"
        :disabled="disabled || remaining <= 0"
        @click="cameraInput?.click()"
      >
        <template #icon><i class="bi bi-camera" /></template>
        ถ่ายรูป
      </AppButton>
      <AppButton
        variant="secondary"
        size="sm"
        :disabled="disabled || remaining <= 0"
        @click="albumInput?.click()"
      >
        <template #icon><i class="bi bi-image" /></template>
        เลือกจากอัลบั้ม
      </AppButton>

      <span class="ml-auto text-[13px] font-medium tabular-nums text-ink-3">
        {{ usedCount }}/{{ maxCount }} รูป
      </span>
    </div>

    <!-- ⚠️ ข้อความบอกผู้เห็น — ต้องแสดงเสมอเมื่อมีช่องแนบรูป -->
    <p v-if="hint" class="mt-2 flex items-start gap-1.5 text-[12px] leading-relaxed text-ink-3">
      <i class="bi bi-eye mt-0.5 shrink-0" aria-hidden="true" />
      <span>{{ hint }}</span>
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
          :disabled="disabled"
          @click="removeAt(i)"
        >
          <i class="bi bi-x-lg text-xs" aria-hidden="true" />
        </button>
      </li>
    </ul>
  </div>
</template>
