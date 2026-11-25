<script setup lang="ts">
import { ref } from 'vue'
import { useIsDesktop } from '@/composables/useMediaQuery'
import AppSheet from '@/components/ui/AppSheet.vue'
import { absoluteMediaUrl } from '@/utils/media'
import type { MediaImage } from '@/types/media'

/**
 * 🖼️ รูปเดียว (thumbnail) + lightboxเมื่อแตะ
 *
 * - มือถือ → `AppSheet` (bottom sheet) · เดสก์ท็อป → ขยายใต้รูป (`AppSheet` เป็น mobile-only)
 * - `url`/`thumb_url` มีอายุ 15 นาที ⇒ ถ้าโหลดไม่ขึ้น **ห้ามทำให้ทั้งหน้าพัง**
 *   แสดงช่อง "โหลดไม่ได้" แทน และให้ผู้เรียก refetch เอง (ได้ URL ชุดใหม่)
 */
// ⚠️ ไม่เก็บผลลัพธ์ในตัวแปร — template ใช้ prop ตรง ๆ (`image`, `alt`, …)
withDefaults(
  defineProps<{
    image: MediaImage
    alt?: string
    /** มุมโค้งของ thumbnail */
    rounded?: string
    /** อัตราส่วนกล่อง thumbnail (Tailwind class) */
    aspect?: string
  }>(),
  {
    alt: 'รูปภาพ',
    rounded: 'rounded-control',
    aspect: 'aspect-square',
  },
)

const isDesktop = useIsDesktop()
const sheetOpen = ref(false)
const expanded = ref(false)
const broken = ref(false)

function open(): void {
  if (broken.value) return
  if (isDesktop.value) expanded.value = !expanded.value
  else sheetOpen.value = true
}
</script>

<template>
  <div>
    <button
      v-if="!broken"
      type="button"
      class="block w-full overflow-hidden border border-line bg-canvas transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
      :class="rounded"
      :aria-label="`เปิดดู ${alt}`"
      @click="open"
    >
      <img
        :src="absoluteMediaUrl(image.thumb_url)"
        :alt="alt"
        class="w-full object-cover"
        :class="aspect"
        loading="lazy"
        @error="broken = true"
      />
    </button>

    <div
      v-else
      class="flex flex-col items-center justify-center gap-1 border border-dashed border-line bg-canvas px-1 text-ink-3"
      :class="[rounded, aspect]"
      role="img"
      :aria-label="`${alt} — โหลดไม่ได้`"
    >
      <i class="bi bi-image-alt text-lg" aria-hidden="true" />
      <span class="text-[11px] leading-tight">โหลดไม่ได้</span>
    </div>

    <div v-if="expanded && !broken" class="mt-2">
      <img
        :src="absoluteMediaUrl(image.url)"
        :alt="alt"
        class="max-h-[70vh] w-full rounded-control border border-line object-contain"
        @error="broken = true"
      />
    </div>

    <AppSheet v-model="sheetOpen" :title="alt">
      <div class="px-2 pb-4">
        <img
          :src="absoluteMediaUrl(image.url)"
          :alt="alt"
          class="max-h-[60dvh] w-full rounded-control bg-canvas object-contain"
          @error="broken = true"
        />
      </div>
    </AppSheet>
  </div>
</template>
