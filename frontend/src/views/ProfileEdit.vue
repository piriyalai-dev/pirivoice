<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useRouter } from 'vue-router';
import Swal from 'sweetalert2';
import { getMyProfile, updateMyProfile } from '@/services/profile';
// 🖼️ รูปโปรไฟล์ — อัป/ลบทันที (มี userId แล้ว ไม่ต้องรอ "บันทึก" เหมือนฟอร์มข้อความ)
import { deleteMedia, uploadMedia } from '@/services/media';
import { compressImages } from '@/utils/imageCompress';
import { DEFAULT_MEDIA_LIMITS, type MediaImage } from '@/types/media';
import { useAuthStore } from '@/stores/auth';
import AppCard from '@/components/ui/AppCard.vue';
import AppButton from '@/components/ui/AppButton.vue';
import AppEmptyState from '@/components/ui/AppEmptyState.vue';
import ImagePicker from '@/components/media/ImagePicker.vue';
import MediaThumb from '@/components/media/MediaThumb.vue';
import { BRAND } from '@/constants/brand';

const router = useRouter();
const authStore = useAuthStore();

const isLoading = ref(true);
const isSaving = ref(false);
const loadError = ref(false);

const editPrefix = ref('');
const editFirstName = ref('');
const editLastName = ref('');
const editNickname = ref('');
const editPhone = ref('');
const editEmail = ref('');

// ── รูปโปรไฟล์ (media_images owner_type=user) ────────────────────────────────
//
// ⚠️ ต่างจากฟอร์มข้อความ: รูป **อัป/ลบทันที** ไม่รอปุ่ม "บันทึก" — เพราะรูปผูกกับ
//    "บัญชีที่ล็อกอินอยู่" (มี id แล้ว) และการอัปซ้ำ = แทนของเดิมฝั่ง server
//    ⇒ ถ้าอัปไม่สำเร็จก็แค่แจ้ง ไม่กระทบข้อมูลที่พิมพ์ในฟอร์ม
const currentAvatar = ref<MediaImage | null>(null);
const avatarFiles = ref<File[]>([]);
const avatarBusy = ref(false);

async function onAvatarPicked(files: File[]): Promise<void> {
  const uid = authStore.user?.id;
  if (!files.length || !uid || avatarBusy.value) return;
  avatarBusy.value = true;
  try {
    const prepared = await compressImages(files);
    const res = await uploadMedia('user', uid, prepared);
    currentAvatar.value = res.items[0] ?? null;
    avatarFiles.value = []; // ล้าง preview ชั่วคราว (อัปเสร็จแล้ว)
    await authStore.loadMe(); // ให้ sidebar/More เห็นรูปใหม่ทันที
    Swal.fire({ icon: 'success', title: 'เปลี่ยนรูปโปรไฟล์แล้ว', timer: 1200, showConfirmButton: false });
  } catch (e: unknown) {
    Swal.fire({ icon: 'error', title: 'อัปรูปไม่สำเร็จ', text: e instanceof Error ? e.message : 'เกิดข้อผิดพลาด' });
  } finally {
    avatarBusy.value = false;
  }
}

async function removeAvatar(): Promise<void> {
  const uid = authStore.user?.id;
  const av = currentAvatar.value;
  if (!uid || !av || avatarBusy.value) return;
  const res = await Swal.fire({
    icon: 'warning',
    title: 'ลบรูปโปรไฟล์?',
    text: 'รูปจะหายจากโปรไฟล์และแถบด้านข้างทันที (อัปใหม่ได้ภายหลัง)',
    showCancelButton: true,
    confirmButtonText: 'ลบรูป',
    cancelButtonText: 'ยกเลิก',
    confirmButtonColor: BRAND,
  });
  if (!res.isConfirmed) return;
  avatarBusy.value = true;
  try {
    await deleteMedia('user', uid, av.id);
    currentAvatar.value = null;
    await authStore.loadMe();
  } catch (e: unknown) {
    Swal.fire({ icon: 'error', title: 'ลบรูปไม่สำเร็จ', text: e instanceof Error ? e.message : 'เกิดข้อผิดพลาด' });
  } finally {
    avatarBusy.value = false;
  }
}

async function loadProfile() {
  isLoading.value = true;
  loadError.value = false;
  try {
    // ⚠️ ฟอร์มแก้ไขต้องได้ค่าล่าสุด — ห้ามใช้ cache
    const p = await getMyProfile({ fresh: true });
    editPrefix.value = p.prefix || '';
    editFirstName.value = p.first_name || '';
    editLastName.value = p.last_name || '';
    editNickname.value = p.nickname || '';
    editPhone.value = p.phone_number || '';
    editEmail.value = p.email || '';
    currentAvatar.value = p.avatar ?? null;
    avatarFiles.value = [];
  } catch (e: unknown) {
    loadError.value = true;
    Swal.fire({ icon: 'error', title: 'โหลดโปรไฟล์ไม่สำเร็จ', text: e instanceof Error ? e.message : 'เกิดข้อผิดพลาด' });
  } finally {
    isLoading.value = false;
  }
}
onMounted(loadProfile);

const canSave = computed(() => editFirstName.value.trim() && editLastName.value.trim());

async function saveProfile() {
  if (!editFirstName.value.trim() || !editLastName.value.trim()) {
    Swal.fire({ icon: 'warning', title: 'กรอกชื่อให้ครบ', text: 'ชื่อ และ นามสกุล จำเป็น' });
    return;
  }
  isSaving.value = true;
  try {
    await updateMyProfile({
      prefix: editPrefix.value.trim() || null,
      first_name: editFirstName.value.trim(),
      last_name: editLastName.value.trim(),
      nickname: editNickname.value.trim() || null,
      phone_number: editPhone.value.trim() || null,
      email: editEmail.value.trim() || null,
    });
    // อัปเดต display name ใน auth store (ชื่อที่ขึ้น sidebar/header)
    await authStore.loadMe();
    Swal.fire({ icon: 'success', title: 'บันทึกโปรไฟล์แล้ว', timer: 1200, showConfirmButton: false });
    router.push({ name: 'profile' });
  } catch (e: unknown) {
    Swal.fire({ icon: 'error', title: 'บันทึกไม่สำเร็จ', text: e instanceof Error ? e.message : 'เกิดข้อผิดพลาด' });
  } finally {
    isSaving.value = false;
  }
}

const goBack = () => router.push({ name: 'profile' });

const inputCls = 'w-full px-3.5 py-2.5 border border-stone-300 rounded-xl text-sm mt-1 bg-white transition focus:ring-2 focus:ring-brand/25 focus:border-brand';
</script>

<template>
  <div class="max-w-2xl mx-auto">
    <!-- Loading skeleton -->
    <div v-if="isLoading" class="space-y-4" aria-busy="true">
      <div class="h-6 w-64 animate-pulse rounded bg-stone-100"></div>
      <div class="space-y-5 rounded-2xl border border-stone-200 bg-white p-6 sm:p-8">
        <div v-for="i in 5" :key="i" class="space-y-2">
          <div class="h-3 w-24 animate-pulse rounded bg-stone-100"></div>
          <div class="h-10 animate-pulse rounded-lg bg-stone-100"></div>
        </div>
      </div>
    </div>

    <!-- Error + retry — 「ไม่มีการ์ดเส้นประ」 (AppEmptyState ไม่มี border-dashed โดยเจตนา) -->
    <AppCard v-else-if="loadError" :padded="false" class="py-4">
      <AppEmptyState
        icon="bi-pencil-square"
        title="ไม่สามารถโหลดข้อมูลโปรไฟล์ได้ในขณะนี้"
        description="ตรวจสอบการเชื่อมต่อแล้วลองอีกครั้ง"
      >
        <AppButton variant="secondary" @click="loadProfile">
          <template #icon><i class="bi bi-arrow-clockwise" aria-hidden="true" /></template>
          ลองใหม่
        </AppButton>
      </AppEmptyState>
    </AppCard>

    <form v-else @submit.prevent="saveProfile" class="space-y-4">
      <!-- 🔴 ไม่มี <h1>/eyebrow/ปุ่มย้อนที่นี่ — `AppHeader` วาดชื่อหน้า (routeTitles) เป็น <h1>
           และปุ่ม ← (จาก `meta.headerBack`) ให้แล้ว (R0.3) ⇒ ของเดิมคือของซ้ำทั้งสามอย่าง -->

      <!-- 🖼️ รูปโปรไฟล์ — อัป/ลบทันที (ไม่ต้องกด "บันทึก" ด้านล่าง) -->
      <div class="space-y-4 rounded-2xl border border-stone-200 bg-white p-6 sm:p-8">
        <div>
          <p class="text-xs font-semibold text-stone-700">รูปโปรไฟล์ <span class="font-normal text-ink-3">(ไม่บังคับ)</span></p>
          <p class="mt-1 text-[12px] leading-relaxed text-ink-3">
            รูปนี้แสดงในโปรไฟล์และแถบเมนูของคุณ — เห็นได้เฉพาะผู้ที่เข้าสู่ระบบ
          </p>
        </div>
        <div class="flex items-center gap-3">
          <div class="w-16 shrink-0">
            <MediaThumb
              v-if="currentAvatar"
              :image="currentAvatar"
              alt="รูปโปรไฟล์ปัจจุบัน"
              rounded="rounded-full"
              aspect="aspect-square"
            />
            <div
              v-else
              class="flex aspect-square w-full items-center justify-center rounded-full bg-brand text-xl font-bold text-white"
              aria-hidden="true"
            >
              <i class="bi bi-person"></i>
            </div>
          </div>
          <div class="min-w-0 flex-1">
            <p class="text-[12px] leading-snug text-ink-3">
              {{ currentAvatar ? 'เลือกรูปใหม่เพื่อแทนที่รูปเดิม' : 'ยังไม่มีรูป — เลือกจากอัลบั้มหรือถ่ายใหม่' }}
            </p>
            <button
              v-if="currentAvatar"
              type="button"
              class="mt-2 rounded-lg px-2 py-1 text-[12px] font-semibold text-brand transition hover:bg-brand/5"
              :disabled="avatarBusy"
              data-testid="avatar-remove-btn"
              @click="removeAvatar"
            >
              <i class="bi bi-trash3"></i> ลบรูป
            </button>
          </div>
        </div>
        <!-- ⚠️ ไม่ส่ง `existingCount` โดยเจตนา — มีรูปเดิมอยู่แล้วก็ยังต้องเลือกใหม่ได้
             (server แทนของเดิมให้) · ถ้าส่ง 1 จะปิดปุ่มทั้งคู่เพราะ "เต็ม" -->
        <ImagePicker
          v-model:files="avatarFiles"
          :max-count="DEFAULT_MEDIA_LIMITS.max_per_owner"
          :size-limit-mb="DEFAULT_MEDIA_LIMITS.size_limit_mb"
          :disabled="avatarBusy"
          hint="แสดงผลเป็นวงกลม — รูปจะถูกครอปให้พอดีกรอบ"
          @change="onAvatarPicked"
        />
      </div>

      <div class="space-y-5 rounded-2xl border border-stone-200 bg-white p-6 sm:p-8">
        <!-- ชื่อ: คำนำหน้า / ชื่อ / นามสกุล (mobile = 1 คอลัมน์) -->
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <label class="block text-xs font-semibold text-stone-700">คำนำหน้า</label>
            <input v-model="editPrefix" :class="inputCls" placeholder="นาย / นางสาว" />
          </div>
          <div>
            <label class="block text-xs font-semibold text-stone-700">ชื่อ <span class="text-brand">*</span></label>
            <input v-model="editFirstName" :class="inputCls" required />
          </div>
          <div>
            <label class="block text-xs font-semibold text-stone-700">นามสกุล <span class="text-brand">*</span></label>
            <input v-model="editLastName" :class="inputCls" required />
          </div>
        </div>

        <div>
          <label class="block text-xs font-semibold text-stone-700">ชื่อเล่น</label>
          <input v-model="editNickname" :class="inputCls" placeholder="ชื่อที่เพื่อนเรียก" />
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label class="block text-xs font-semibold text-stone-700">เบอร์โทร</label>
            <input v-model="editPhone" :class="inputCls" type="tel" placeholder="08x-xxx-xxxx" />
          </div>
          <div>
            <label class="block text-xs font-semibold text-stone-700">อีเมล</label>
            <input v-model="editEmail" :class="inputCls" type="email" placeholder="example@mail.com" />
          </div>
        </div>
      </div>

      <!-- ปุ่ม -->
      <div class="flex gap-2 pt-1">
        <button
          type="submit"
          :disabled="isSaving || !canSave"
          class="flex-1 py-3 bg-brand text-white rounded-xl hover:bg-brand-strong disabled:opacity-50 font-semibold transition-colors"
        >
          <i class="bi bi-check-lg mr-1"></i> {{ isSaving ? 'กำลังบันทึก...' : 'บันทึก' }}
        </button>
        <button
          type="button"
          @click="goBack"
          class="px-5 py-3 bg-white border border-stone-200 text-stone-600 rounded-xl hover:bg-stone-50 text-sm font-medium transition"
        >
          ยกเลิก
        </button>
      </div>
    </form>
  </div>
</template>
