<script setup lang="ts">
import { ref, watch } from 'vue'
import Swal from 'sweetalert2'
import { BRAND } from '@/constants/brand'
import { fmtDateTime } from '@/datetime'
import { useIsDesktop } from '@/composables/useMediaQuery'
import AppButton from '@/components/ui/AppButton.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import { absoluteMediaUrl, formatBytes } from '@/utils/media'
import { KIND_LABELS, receiptLabel } from '@/utils/issueImages'
import type { IssueImage } from '@/types/issue'

/**
 * 🖼️ แกลเลอรีรูปของเรื่อง
 *
 * - **มือถือ:** แตะรูป → `AppSheet` (bottom sheet) แบบ lightbox
 * - **เดสก์ท็อป:** `AppSheet` ถูกซ่อนด้วย `lg:hidden` ⇒ แตะแล้วขยายใต้กริดแทน
 *
 * ⚠️ `url`/`thumb_url` เป็น signed URL อายุสั้น ⇒ ถ้าโหลดไม่ขึ้น (403/404) เราต้อง
 *    **ไม่ทำให้ทั้งหน้าพัง** — แสดงช่อง "โหลดไม่ได้" + ปุ่มให้ผู้เรียก refetch รายการ
 *    (ผู้เรียกได้ URL ชุดใหม่)
 */
const props = defineProps<{
  images: IssueImage[]
  /** เรื่องมีผู้รับแล้วหรือยัง — ใช้แยกข้อความ "ยังไม่มีผู้รับ" ออกจาก "ยังไม่เปิดดู" */
  hasAssignee: boolean
  /** ผู้เรียกตัดสินรายรูป (ผู้อัปโหลดเอง + เรื่องยังไม่ปิด, หรือแอดมิน) */
  canDelete?: (image: IssueImage) => boolean
}>()

const emit = defineEmits<{
  delete: [image: IssueImage]
  refresh: []
}>()

const isDesktop = useIsDesktop()
const sheetOpen = ref(false)
const selected = ref<IssueImage | null>(null)
/** id ของรูปที่โหลดไม่ขึ้น — เก็บเป็น array เพื่อให้ template react ได้ */
const brokenIds = ref<string[]>([])

function isBroken(image: IssueImage): boolean {
  return brokenIds.value.includes(image.id)
}

function markBroken(image: IssueImage): void {
  if (!brokenIds.value.includes(image.id)) brokenIds.value = [...brokenIds.value, image.id]
}

function open(image: IssueImage): void {
  if (isBroken(image)) return
  selected.value = image
  if (!isDesktop.value) sheetOpen.value = true
}

function close(): void {
  sheetOpen.value = false
}

/** รายการเปลี่ยน (ลบ/refetch) → รูปที่เปิดค้างไว้อาจหายไปแล้ว */
watch(
  () => props.images,
  (next) => {
    if (selected.value && !next.some((i) => i.id === selected.value?.id)) {
      selected.value = null
      close()
    }
  },
)

function isDeletable(image: IssueImage): boolean {
  return props.canDelete ? props.canDelete(image) : false
}

async function confirmDelete(image: IssueImage): Promise<void> {
  const res = await Swal.fire({
    icon: 'warning',
    title: 'ลบรูปนี้?',
    text: 'รูปจะถูกซ่อนจากเรื่องนี้ทันที',
    showCancelButton: true,
    confirmButtonText: 'ลบรูป',
    cancelButtonText: 'ยกเลิก',
    confirmButtonColor: BRAND,
  })
  if (!res.isConfirmed) return
  close()
  emit('delete', image)
}

const badge = (image: IssueImage): string | null => receiptLabel(image.receipt, props.hasAssignee)
</script>

<template>
  <div>
    <ul class="grid grid-cols-3 gap-2 sm:gap-3">
      <li v-for="(image, i) in images" :key="image.id">
        <button
          v-if="!isBroken(image)"
          type="button"
          class="block w-full overflow-hidden rounded-control border border-line bg-canvas transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
          :aria-label="`เปิดดูรูปที่ ${i + 1} (${KIND_LABELS[image.kind]})`"
          @click="open(image)"
        >
          <img
            :src="absoluteMediaUrl(image.thumb_url)"
            :alt="`${KIND_LABELS[image.kind]} รูปที่ ${i + 1}`"
            class="aspect-square w-full object-cover"
            loading="lazy"
            @error="markBroken(image)"
          />
        </button>

        <button
          v-else
          type="button"
          class="flex aspect-square w-full flex-col items-center justify-center gap-1 rounded-control border border-dashed border-line bg-canvas px-1 text-ink-3"
          aria-label="รูปนี้โหลดไม่ได้ — ลองโหลดรายการใหม่"
          @click="emit('refresh')"
        >
          <i class="bi bi-image-alt text-lg" aria-hidden="true" />
          <span class="text-[11px] leading-tight">โหลดไม่ได้ · ลองใหม่</span>
        </button>

        <!-- 🔔 เฉพาะผู้แจ้งเท่านั้นที่มี receipt (ผู้รับเห็น null) — ข้อความบอกว่าผู้รับเปิดดูแล้วหรือยัง -->
        <p
          v-if="badge(image)"
          class="mt-1 flex items-start gap-1 text-[11px] leading-snug"
          :class="image.receipt?.current_assignee_viewed ? 'text-ok' : 'text-ink-3'"
        >
          <i
            class="mt-px shrink-0 text-[11px]"
            :class="image.receipt?.current_assignee_viewed ? 'bi bi-check2-circle' : 'bi bi-hourglass'"
            aria-hidden="true"
          />
          <span>{{ badge(image) }}</span>
        </p>
      </li>
    </ul>

    <!-- 🖥️ เดสก์ท็อป — AppSheet เป็น mobile-only จึงขยายรูปใต้กริดแทน -->
    <div
      v-if="isDesktop && selected"
      class="mt-3 rounded-card border border-line bg-canvas p-3"
      data-testid="issue-image-expanded"
    >
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="text-sm font-semibold text-ink-1">{{ KIND_LABELS[selected.kind] }}</p>
          <p class="mt-0.5 text-[13px] text-ink-2">
            {{ formatBytes(selected.bytes) }} · {{ fmtDateTime(selected.created_at) }}
          </p>
        </div>
        <button
          type="button"
          class="flex h-11 w-11 shrink-0 items-center justify-center rounded-control text-ink-2 hover:bg-surface hover:text-ink-1"
          aria-label="ปิดรูปขยาย"
          @click="selected = null"
        >
          <i class="bi bi-x-lg" aria-hidden="true" />
        </button>
      </div>
      <img
        :src="absoluteMediaUrl(selected.url)"
        :alt="KIND_LABELS[selected.kind]"
        class="mt-2 max-h-[70vh] w-full rounded-control border border-line object-contain"
        @error="markBroken(selected)"
      />
      <p v-if="badge(selected)" class="mt-2 text-[13px] text-ink-2">{{ badge(selected) }}</p>
      <AppButton
        v-if="isDeletable(selected)"
        variant="danger"
        size="sm"
        class="mt-2"
        @click="confirmDelete(selected)"
      >
        <template #icon><i class="bi bi-trash" /></template>
        ลบรูปนี้
      </AppButton>
    </div>

    <!-- 📱 มือถือ — bottom sheet lightbox -->
    <AppSheet
      v-model="sheetOpen"
      :title="selected ? KIND_LABELS[selected.kind] : 'รูปภาพ'"
      :description="selected ? `${formatBytes(selected.bytes)} · ${fmtDateTime(selected.created_at)}` : undefined"
    >
      <div v-if="selected" class="px-2 pb-4">
        <img
          :src="absoluteMediaUrl(selected.url)"
          :alt="KIND_LABELS[selected.kind]"
          class="max-h-[60dvh] w-full rounded-control bg-canvas object-contain"
          @error="markBroken(selected)"
        />
        <p v-if="badge(selected)" class="mt-2 text-[13px] text-ink-2">{{ badge(selected) }}</p>
        <AppButton
          v-if="isDeletable(selected)"
          variant="danger"
          block
          class="mt-3"
          @click="confirmDelete(selected)"
        >
          <template #icon><i class="bi bi-trash" /></template>
          ลบรูปนี้
        </AppButton>
      </div>
    </AppSheet>
  </div>
</template>
