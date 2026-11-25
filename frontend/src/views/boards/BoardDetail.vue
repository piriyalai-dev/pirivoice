<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Swal from 'sweetalert2'
import { BRAND } from '@/constants/brand'
import { getBoard, submitVote, addComment, hideBoard } from '@/services/board'
import { uploadMedia, deleteMedia } from '@/services/media'
import { compressImages } from '@/utils/imageCompress'
import { DEFAULT_MEDIA_LIMITS } from '@/types/media'
import {
  boardTypeIcon,
  boardTypeHeading,
  boardAuthorFallback,
  type BoardDetail,
} from '@/types/board'
import type { ApiError } from '@/services/api'
import { goUnavailable } from '@/router/unavailable'
import { fmtDateShort } from '@/datetime'
import { absoluteMediaUrl } from '@/utils/media'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import CommentThread from '@/components/boards/CommentThread.vue'
import BookmarkButton from '@/components/BookmarkButton.vue'
import ImagePicker from '@/components/media/ImagePicker.vue'
import MediaThumb from '@/components/media/MediaThumb.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppEmptyState from '@/components/ui/AppEmptyState.vue'

const authStore = useAuthStore()
const notificationsStore = useNotificationsStore()

/**
 * 📄 PIRI Board — รองรับ 2 เลย์เอาต์:
 * - Vote: ตัวเลือกแบบ progress bar + เลือกโหวต (1 เสียง/คน — เปลี่ยนไม่ได้)
 * - Talk: คอมเมนต์แบบ threaded (CommentThread recursive)
 */
const route = useRoute()
const router = useRouter()

const board = ref<BoardDetail | null>(null)
const isLoading = ref(true)
const loadError = ref('')
/**
 * 🖼️ `cover_image_url` (ลิงก์ภายนอกเก่า) โหลดไม่ขึ้น — ซ่อนไปเลย
 * ⚠️ ต้องเป็น ref ไม่ใช่ inline handler: URL เก่าเป็นลิงก์นอกที่ตายได้ตลอด และการแก้
 *    `style.display` ใน template จะไม่ถูก re-render ⇒ รูปที่ตายแล้วจะยังกินที่ว่าง
 */
const legacyCoverBroken = ref(false)

// ===== Vote =====
const selectedChoice = ref<number | null>(null)
const voting = ref(false)
const myVoted = computed(() => (board.value?.my_vote_choice_id ?? null) !== null)

function choicePercent(c: { vote_count: number }): number {
  const total = board.value?.total_votes ?? 0
  if (total <= 0) return 0
  return Math.round((c.vote_count / total) * 100)
}

async function handleVote() {
  if (!board.value || selectedChoice.value === null || myVoted.value) return
  voting.value = true
  try {
    await submitVote(board.value.id, selectedChoice.value)
    Swal.fire({
      icon: 'success',
      title: 'ส่งเสียงโหวตแล้ว!',
      timer: 1200,
      showConfirmButton: false,
    })
    await load()
  } catch (e) {
    Swal.fire({
      icon: 'error',
      title: 'โหวตไม่สำเร็จ',
      text: e instanceof Error ? e.message : String(e),
    })
  } finally {
    voting.value = false
  }
}

// ===== 🖼️ รูปปก (เจ้าของโพสต์/สภา) =====
/**
 * ⚠️ การอัป/ลบปกของโพสต์ที่ **มีอยู่แล้ว** ทำทันที (ต่างจากตอนสร้าง ซึ่งต้องสร้างก่อน)
 *    ⇒ นี่คือทางกู้เมื่อ "สร้างข้อเสนอแล้วแต่อัปปกไม่สำเร็จ"
 */
const coverEditing = ref(false)
const coverFiles = ref<File[]>([])
const coverSaving = ref(false)

function startEditCover(): void {
  coverFiles.value = []
  coverEditing.value = true
}

function cancelEditCover(): void {
  coverFiles.value = []
  coverEditing.value = false
}

async function saveCover(): Promise<void> {
  const b = board.value
  if (!b || !coverFiles.value.length || coverSaving.value) return
  coverSaving.value = true
  try {
    const prepared = await compressImages(coverFiles.value)
    await uploadMedia('board', b.id, prepared)
    coverFiles.value = []
    coverEditing.value = false
    await load()
    Swal.fire({ icon: 'success', title: 'บันทึกรูปปกแล้ว', timer: 1200, showConfirmButton: false })
  } catch (e) {
    Swal.fire({
      icon: 'error',
      title: 'บันทึกรูปปกไม่สำเร็จ',
      text: e instanceof Error ? e.message : 'เกิดข้อผิดพลาด',
      confirmButtonColor: BRAND,
    })
  } finally {
    coverSaving.value = false
  }
}

async function removeCover(): Promise<void> {
  const b = board.value
  const img = b?.cover_image
  if (!b || !img) return
  const res = await Swal.fire({
    icon: 'warning',
    title: 'ลบรูปปกนี้?',
    text: 'รูปจะหายจากบอร์ดทันที (ไฟล์จริงจะถูกล้างภายหลังตามรอบ purge)',
    showCancelButton: true,
    confirmButtonText: 'ลบรูปปก',
    cancelButtonText: 'ยกเลิก',
    confirmButtonColor: BRAND,
  })
  if (!res.isConfirmed) return
  try {
    await deleteMedia('board', b.id, img.id)
    await load()
    Swal.fire({ icon: 'success', title: 'ลบรูปปกแล้ว', timer: 1200, showConfirmButton: false })
  } catch (e) {
    Swal.fire({
      icon: 'error',
      title: 'ลบไม่สำเร็จ',
      text: e instanceof Error ? e.message : 'เกิดข้อผิดพลาด',
      confirmButtonColor: BRAND,
    })
  }
}

// ===== Talk =====
const commentBody = ref('')
/** 🖼️ รูปที่เลือกไว้กับคอมเมนต์ root — อัปหลังคอมเมนต์เกิดแล้ว (ต้องมี id) */
const commentFiles = ref<File[]>([])
const postingComment = ref(false)

async function submitComment() {
  if (!board.value || !commentBody.value.trim()) return
  postingComment.value = true
  try {
    const created = await addComment(board.value.id, commentBody.value.trim())
    commentBody.value = ''

    // 🖼️ คอมเมนต์เกิดแล้ว ⇒ อัปรูปที่เลือกไว้ (ถ้ามี) · ล้มเหลว = คอมเมนต์ยังอยู่
    let attachError: string | null = null
    if (commentFiles.value.length) {
      try {
        const prepared = await compressImages(commentFiles.value)
        await uploadMedia('board_comment', created.id, prepared)
      } catch (e) {
        attachError = e instanceof Error ? e.message : 'เกิดข้อผิดพลาด'
      }
      commentFiles.value = []
    }

    if (attachError) {
      await Swal.fire({
        icon: 'warning',
        title: 'คอมเมนต์แล้ว แต่แนบรูปไม่สำเร็จ',
        text: attachError,
        confirmButtonColor: BRAND,
      })
    } else {
      Swal.fire({ icon: 'success', title: 'คอมเมนต์แล้ว', timer: 1000, showConfirmButton: false })
    }
    await load()
  } catch (e) {
    Swal.fire({
      icon: 'error',
      title: 'คอมเมนต์ไม่สำเร็จ',
      text: e instanceof Error ? e.message : String(e),
    })
  } finally {
    postingComment.value = false
  }
}

async function load() {
  isLoading.value = true
  loadError.value = ''
  try {
    board.value = await getBoard(Number(route.params.id))
    // รูปเก่าอาจเป็นบอร์ดคนละอันหลัง reload — ต้องให้มีโอกาสลองโหลดใหม่
    legacyCoverBroken.value = false
    // รีเซ็ตตัวเลือกที่เลือก (หลังโหวตแล้ว reload — ป้องกัน select ตัวเดิมหลงเหลือ)
    if (board.value?.my_vote_choice_id) selectedChoice.value = null
    // 🔔 เปิดบอร์ดแล้ว → mark notification ของบอร์ดนี้ว่าอ่านแล้ว (badge ลด)
    if (board.value) void notificationsStore.read({ board_id: board.value.id })
  } catch (e) {
    // 🚪 404 = บอร์ด "เปิดดูไม่ได้แล้ว" มีสองทางที่อยู่คนละคอลัมน์ — `deleted_at IS NOT NULL`
    //    (ถูกลบ) และ `status = 'hidden'` (สภาฯ กดซ่อน) · backend ตอบ 404 เหมือนกันทั้งคู่
    //    ⇒ ลิงก์ที่ผู้ใช้กดมา (จาก notification หรือ deep link ของ push) ใช้ต่อไม่ได้
    //    ⇒ พากลับไปที่ที่ไปต่อได้ + บอกสาเหตุ ดีกว่าค้างไว้กับ error ที่กดลองใหม่ก็ได้ 404
    //    (เหตุผลเต็มอยู่ใน `router/unavailable.ts` — **ห้ามแยกสองกรณีนี้ออกจากกัน**)
    if (e instanceof Error && (e as ApiError).status === 404) {
      await goUnavailable(router, 'board')
      return
    }
    loadError.value = e instanceof Error ? e.message : 'โหลดบอร์ดไม่สำเร็จ'
  } finally {
    isLoading.value = false
  }
}

// 🛡️ สภา/แอดมิน ซ่อน board ทั้งบอร์ด (หลุดจากฟีด + detail 404) — ต้องระบุเหตุผล
const hidingBoard = ref(false)
async function handleHideBoard() {
  if (!board.value || hidingBoard.value) return
  const { value } = await Swal.fire({
    title: 'ซ่อนบอร์ดนี้?',
    text: 'บอร์ดจะหายจากฟีดและรายละเอียดทันที (ผู้ใช้ทั่วไปมองไม่เห็น)',
    icon: 'warning',
    input: 'text',
    inputPlaceholder: 'เหตุผลที่ซ่อน (จำเป็น)',
    inputAttributes: { maxlength: '200' },
    showCancelButton: true,
    confirmButtonText: 'ซ่อนบอร์ด',
    confirmButtonColor: BRAND,
    cancelButtonText: 'ยกเลิก',
  })
  if (!value || !String(value).trim()) {
    if (value !== undefined)
      Swal.fire({ icon: 'warning', title: 'ต้องระบุเหตุผล', text: 'กรุณากรอกเหตุผลที่ซ่อน' })
    return
  }
  hidingBoard.value = true
  try {
    await hideBoard(board.value.id, String(value).trim())
    Swal.fire({
      icon: 'success',
      title: 'ซ่อนบอร์ดแล้ว',
      text: 'ย้ายกลับไปยังหน้ารวมบอร์ด',
      timer: 1500,
      showConfirmButton: false,
    }).then(() => {
      router.push({ name: 'boards' })
    })
  } catch (e) {
    Swal.fire({
      icon: 'error',
      title: 'ซ่อนไม่สำเร็จ',
      text: e instanceof Error ? e.message : String(e),
    })
  } finally {
    hidingBoard.value = false
  }
}

onMounted(load)

// 🕐 `fmtDateShort` มาจาก `@/datetime` (R5.5) — ของเดิมในไฟล์นี้เป็น **วันที่ล้วนก็อปที่สอง**
//    ต่างจากต้นฉบับแค่ `day: '2-digit'` ⇒ ตอนนี้เป็น `numeric` เหมือนกันทั้งระบบ (`1 ต.ค. 2569`)
//    ⚠️ คอมเมนต์ใต้กระทู้ (`CommentThread`) ยังใช้ `fmtDayTime` ที่ **มี** ศูนย์นำ — ตั้งใจ
//       ตามกฎใน `datetime.ts`: วันที่ล้วนอ่านเป็นประโยค · วันที่+เวลาอยู่ในคอลัมน์ที่ต้องตรงหลัก

// คอมเมนต์ root (parent_comment_id = null) — backend ส่ง tree ที่ roots อยู่ระดับบน
const rootComments = computed(() => board.value?.comments ?? [])
</script>

<template>
  <!-- โหลด: skeleton เนื้อหา -->
  <div v-if="isLoading" class="max-w-3xl mx-auto space-y-5">
    <div class="page-card p-5 space-y-3">
      <div class="flex items-center justify-between">
        <div class="h-5 w-24 bg-stone-100 animate-pulse rounded-md"></div>
        <div class="h-3 w-20 bg-stone-100 animate-pulse rounded"></div>
      </div>
      <div class="h-6 w-3/4 bg-stone-100 animate-pulse rounded"></div>
      <div class="h-4 w-1/2 bg-stone-100 animate-pulse rounded"></div>
      <div class="h-20 w-full bg-stone-100 animate-pulse rounded"></div>
    </div>
    <div class="page-card p-5 space-y-3">
      <div class="h-5 w-24 bg-stone-100 animate-pulse rounded"></div>
      <div class="h-14 w-full bg-stone-100 animate-pulse rounded-xl"></div>
      <div class="h-14 w-full bg-stone-100 animate-pulse rounded-xl"></div>
      <div class="h-14 w-full bg-stone-100 animate-pulse rounded-xl"></div>
      <div class="h-11 w-full bg-stone-100 animate-pulse rounded-xl"></div>
    </div>
  </div>

  <!-- ข้อผิดพลาด — 「ไม่มีการ์ดเส้นประ」 (AppEmptyState ไม่มี border-dashed โดยเจตนา) -->
  <AppCard v-else-if="loadError" :padded="false" class="max-w-3xl mx-auto py-4">
    <AppEmptyState icon="bi-file-earmark-x" title="เปิดกระทู้นี้ไม่สำเร็จ" :description="loadError">
      <div class="flex flex-wrap items-center justify-center gap-2">
        <AppButton variant="secondary" @click="load">
          <template #icon><i class="bi bi-arrow-clockwise" aria-hidden="true" /></template>
          ลองอีกครั้ง
        </AppButton>
        <AppButton :to="{ name: 'boards' }" variant="text">กลับไปหน้ารวมบอร์ด</AppButton>
      </div>
    </AppEmptyState>
  </AppCard>

  <div v-else-if="board" class="max-w-3xl mx-auto space-y-5">
    <!-- 🔴 ไม่มีปุ่มย้อนที่นี่ — `AppHeader` วาดปุ่ม ← (จาก `meta.headerBack` = `boards`) ให้แล้ว (R0.3) -->

    <!-- Header -->
    <div class="page-card p-5">
      <div class="flex items-center justify-between gap-3 mb-2">
        <span
          class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-stone-100 text-stone-600 text-[11px] font-semibold"
        >
          <i :class="boardTypeIcon(board.board_type)"></i> {{ boardTypeHeading(board.board_type) }}
        </span>
        <div class="flex items-center gap-2">
          <span class="text-xs text-ink-3">{{ fmtDateShort(board.created_at) }}</span>
          <!-- 🔖 บันทึกไว้อ่านทีหลัง (C2) -->
          <BookmarkButton entity-type="board" :entity-id="board.id" size="sm" />
          <button
            v-if="authStore.isCouncilAuthority"
            type="button"
            @click="handleHideBoard"
            :disabled="hidingBoard"
            data-testid="hide-board-btn"
            class="inline-flex items-center px-2.5 min-h-11 py-1 text-[11px] font-medium rounded-lg border border-brand/25 text-brand hover:bg-brand/5 disabled:opacity-40"
            title="ซ่อนบอร์ดนี้ (สภา/แอดมิน)"
          >
            <i class="bi bi-eye-slash mr-1"></i> ซ่อนบอร์ด
          </button>
        </div>
      </div>
      <!-- ⚠️ `<h2>` ไม่ใช่ `<h1>` — `<h1>` ของหน้าอยู่ที่ `AppHeader` แล้ว (R0.3.1) -->
      <!-- 🖼️ รูปปก — รูปใหม่ (media_images) ก่อน · ถ้าไม่มีค่อยใช้ลิงก์เก่าที่คัดลอกมาจากเรื่อง -->
      <MediaThumb
        v-if="board.cover_image"
        :image="board.cover_image"
        alt="รูปปกกระทู้"
        aspect="aspect-[16/9]"
        rounded="rounded-xl"
        class="mt-3"
      />
      <img
        v-else-if="board.cover_image_url && !legacyCoverBroken"
        :src="absoluteMediaUrl(board.cover_image_url)"
        alt="รูปปกกระทู้"
        class="mt-3 w-full rounded-xl border border-line object-cover"
        loading="lazy"
        @error="legacyCoverBroken = true"
      />
      <h2 class="mt-3 text-lg sm:text-xl font-bold text-stone-900 leading-snug break-words">
        {{ board.title }}
      </h2>
      <p class="text-stone-500 text-sm mt-1">
        โดย
        {{
          board.is_anonymous
            ? 'ไม่ระบุชื่อ'
            : board.author_name || boardAuthorFallback(board.board_type)
        }}
      </p>
      <p class="text-stone-700 mt-3 whitespace-pre-wrap break-words">{{ board.description }}</p>
      <div v-if="board.tags.length" class="flex flex-wrap gap-1.5 mt-3">
        <span
          v-for="tag in board.tags"
          :key="tag"
          class="px-2 py-0.5 bg-stone-100 text-stone-600 text-[11px] rounded-full"
          >#{{ tag }}</span
        >
      </div>

      <!-- 🖼️ จัดการรูปปก (เจ้าของโพสต์ หรือสภา/แอดมิน) — `cover_editable` มาจาก server -->
      <div v-if="board.cover_editable" class="mt-3">
        <div v-if="!coverEditing" class="flex flex-wrap items-center gap-2">
          <button
            type="button"
            class="inline-flex items-center rounded-control border border-line px-2.5 py-1 text-[12px] font-medium text-ink-2 hover:bg-canvas"
            data-testid="cover-edit-btn"
            @click="startEditCover"
          >
            <i class="bi bi-image mr-1" aria-hidden="true" />
            {{ board.cover_image ? 'เปลี่ยนรูปปก' : 'เพิ่มรูปปก' }}
          </button>
          <button
            v-if="board.cover_image"
            type="button"
            class="inline-flex items-center rounded-control border border-line px-2.5 py-1 text-[12px] font-medium text-danger hover:bg-canvas"
            data-testid="cover-remove-btn"
            @click="removeCover"
          >
            <i class="bi bi-trash mr-1" aria-hidden="true" />
            ลบรูปปก
          </button>
        </div>

        <div v-else class="space-y-2">
          <!-- ⚠️ ไม่ส่ง `existingCount` แม้จะมีปกอยู่ — backend เปลี่ยนปกด้วยการแทนที่
               (soft-delete ของเดิม + แถวใหม่) ⇒ ถ้านับรวมเพดาน 1 รูป ปุ่มจะถูกปิดทันที
               แล้วผู้ใช้จะ "เปลี่ยน" ปกไม่ได้เลย -->
          <ImagePicker
            v-model:files="coverFiles"
            :max-count="DEFAULT_MEDIA_LIMITS.max_per_owner"
            :size-limit-mb="DEFAULT_MEDIA_LIMITS.size_limit_mb"
            :disabled="coverSaving"
            :hint="
              board.cover_image
                ? 'รูปใหม่จะแทนที่รูปปกเดิม · ผู้ใช้ที่เข้าสู่ระบบทุกคนเห็นได้'
                : 'รูปจะถูกมองเห็นโดยผู้ใช้ที่เข้าสู่ระบบทุกคน'
            "
          />
          <div class="flex flex-wrap gap-2">
            <AppButton
              size="sm"
              :loading="coverSaving"
              :disabled="!coverFiles.length"
              data-testid="cover-save-btn"
              @click="saveCover"
            >
              บันทึกรูปปก
            </AppButton>
            <AppButton variant="text" size="sm" :disabled="coverSaving" @click="cancelEditCover">
              ยกเลิก
            </AppButton>
          </div>
        </div>
      </div>
    </div>

    <!-- ===================== Vote layout ===================== -->
    <div v-if="board.board_type === 'vote'" class="page-card p-5">
      <div class="flex items-center justify-between mb-1">
        <h2 class="text-lg font-bold text-stone-900">
          <i class="bi bi-bar-chart-fill mr-1 text-stone-500"></i> โหวต
        </h2>
        <span class="text-sm text-stone-500 font-display tabular-nums"
          >{{ board.total_votes.toLocaleString('en-US') }} เสียง</span
        >
      </div>

      <!-- แบนเนอร์: โหวตแล้ว → เปลี่ยนตัวเลือกไม่ได้ -->
      <div
        v-if="myVoted"
        data-testid="my-vote-banner"
        class="mb-4 px-3 py-2 bg-ok-faint border border-ok-line text-ok-strong text-sm rounded-xl"
      >
        <i class="bi bi-check-circle-fill mr-1"></i> คุณส่งเสียงโหวตแล้ว — แต่ละคนโหวตได้ 1 ครั้ง
      </div>

      <div class="space-y-3">
        <button
          v-for="c in board.choices"
          :key="c.id"
          type="button"
          :data-testid="'vote-choice-' + c.id"
          :disabled="myVoted"
          @click="selectedChoice = c.id"
          class="w-full text-left p-4 rounded-xl border-2 transition"
          :class="[
            !myVoted && selectedChoice === c.id
              ? 'border-brand bg-brand/5'
              : 'border-stone-200 hover:border-stone-300',
            board.my_vote_choice_id === c.id ? 'ring-2 ring-ok-focus border-ok-focus' : '',
            myVoted ? 'cursor-default' : 'cursor-pointer',
          ]"
        >
          <div class="flex items-center justify-between gap-3 mb-2">
            <span class="font-semibold text-stone-900 text-sm sm:text-base flex items-center gap-2">
              <span v-if="board.my_vote_choice_id === c.id" class="text-ok-solid"
                ><i class="bi bi-check-circle-fill"></i
              ></span>
              {{ c.choice_text }}
            </span>
            <span class="text-sm text-stone-500 font-display tabular-nums whitespace-nowrap">
              {{ c.vote_count.toLocaleString('en-US') }} เสียง · {{ choicePercent(c) }}%
            </span>
          </div>
          <!-- progress bar -->
          <div class="h-2.5 bg-stone-100 rounded-full overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-500"
              :class="board.my_vote_choice_id === c.id ? 'bg-ok-bright' : 'bg-brand'"
              :style="{ width: choicePercent(c) + '%' }"
            ></div>
          </div>
        </button>
      </div>

      <p v-if="!board.choices.length" class="text-sm text-ink-3 py-2">ยังไม่มีตัวเลือกโหวต</p>

      <button
        v-if="!myVoted"
        type="button"
        :disabled="selectedChoice === null || voting"
        data-testid="vote-submit"
        @click="handleVote"
        class="mt-4 w-full py-3 bg-brand text-white rounded-xl hover:bg-brand-strong disabled:opacity-50 font-medium"
      >
        {{
          voting
            ? 'กำลังส่งเสียง...'
            : selectedChoice === null
              ? 'เลือกตัวเลือกก่อนโหวต'
              : 'ส่งเสียงโหวต'
        }}
      </button>
    </div>

    <!-- ===================== Talk layout ===================== -->
    <div v-else class="page-card p-5">
      <h2 class="text-lg font-bold text-stone-900 mb-4">
        <i class="bi bi-chat-left-text mr-1 text-stone-500"></i> พูดคุย
        <span v-if="rootComments.length" class="text-sm font-normal text-ink-3"
          >({{ board.comment_count }})</span
        >
      </h2>

      <!-- ปิดคอมเมนต์ -->
      <div
        v-if="!board.allow_comments"
        class="mb-4 px-3 py-2 bg-stone-100 text-stone-600 text-sm rounded-xl"
      >
        <i class="bi bi-lock mr-1"></i> บอร์ดนี้ปิดคอมเมนต์ (อ่านอย่างเดียว)
      </div>

      <!-- ช่องคอมเมนต์ root -->
      <div v-if="board.allow_comments" class="mb-5 space-y-2">
        <div class="flex gap-2">
          <input
            v-model="commentBody"
            type="text"
            data-testid="comment-input"
            placeholder="ร่วมแสดงความเห็น..."
            maxlength="1000"
            class="flex-1 px-3 py-2.5 border border-stone-300 rounded-xl text-sm focus:ring-2 focus:ring-brand"
            @keyup.enter="submitComment"
          />
          <button
            type="button"
            :disabled="postingComment || !commentBody.trim()"
            data-testid="comment-submit"
            @click="submitComment"
            class="inline-flex items-center px-4 min-h-11 py-2.5 bg-brand text-white rounded-xl text-sm hover:bg-brand-strong disabled:opacity-50"
          >
            {{ postingComment ? '...' : 'ส่ง' }}
          </button>
        </div>
        <!-- 🖼️ แนบรูปกับคอมเมนต์ (ไม่บังคับ · สูงสุด 1) -->
        <ImagePicker
          v-model:files="commentFiles"
          :max-count="DEFAULT_MEDIA_LIMITS.max_per_owner"
          :size-limit-mb="DEFAULT_MEDIA_LIMITS.size_limit_mb"
          :disabled="postingComment"
          hint="รูปนี้จะถูกมองเห็นโดยผู้ใช้ที่เข้าสู่ระบบทุกคน"
        />
      </div>

      <!-- กระทู้คอมเมนต์ (threaded) -->
      <div v-if="rootComments.length" class="space-y-4">
        <CommentThread
          v-for="c in rootComments"
          :key="c.id"
          :board-id="board.id"
          :comment="c"
          @refresh="load"
        />
      </div>
      <p v-else-if="board.allow_comments" class="text-sm text-ink-3 py-2">
        ยังไม่มีความเห็น — เป็นคนแรกที่ร่วมพูดคุย
      </p>
    </div>
  </div>
</template>
