<template>
  <div class="min-h-screen p-4 md:p-6">
    <div class="max-w-4xl mx-auto">
      <!-- Header -->
      <div class="nav-glass rounded-2xl shadow-lg mb-6 px-6 py-3.5">
        <div class="flex items-center justify-between gap-4">
          <div class="flex items-center gap-3">
            <div class="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
              <span class="text-lg">🗂️</span>
            </div>
            <div>
              <h1 class="text-xl font-bold text-white tracking-tight leading-tight">历史记录</h1>
              <p class="text-[11px] text-gray-500 mt-0.5">往期生成的播客与研究报告</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <button class="nav-action-btn text-blue-300" @click="$emit('refresh')" aria-label="刷新历史记录">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
              刷新
            </button>
            <button class="nav-action-btn text-gray-300" @click="$emit('back')" aria-label="返回首页">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 17l-5-5m0 0l5-5m-5 5h12"/></svg>
              返回
            </button>
          </div>
        </div>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="history-card rounded-2xl p-8 text-center">
        <p class="text-sm text-gray-400">正在加载历史记录...</p>
      </div>

      <!-- Error -->
      <div v-else-if="error" class="history-error rounded-2xl p-6">
        <p class="text-sm font-semibold text-red-300">加载失败</p>
        <p class="text-xs text-red-200/80 mt-1 break-words">{{ error }}</p>
        <button class="nav-action-btn text-blue-300 mt-3" @click="$emit('refresh')">重试</button>
      </div>

      <!-- Empty -->
      <div v-else-if="!runs.length" class="history-card rounded-2xl p-10 text-center">
        <span class="text-3xl">📭</span>
        <p class="text-sm text-gray-300 mt-3">还没有历史记录</p>
        <p class="text-xs text-gray-500 mt-1">完成一次播客制作后，往期内容会自动保留在这里。</p>
      </div>

      <!-- List -->
      <ul v-else class="flex flex-col gap-3">
        <li v-for="run in runs" :key="run.run_id" class="history-card rounded-2xl">
          <div class="p-4 flex items-center gap-4">
            <div class="history-avatar">
              <span class="text-lg">{{ run.audio_url ? '🎧' : '📄' }}</span>
            </div>

            <div class="min-w-0 flex-1">
              <p class="text-sm font-semibold text-gray-100 truncate" :title="run.topic">{{ run.topic }}</p>
              <p class="text-[11px] text-gray-500 mt-1">
                <span>{{ formatTime(run.created_at) }}</span>
                <span class="mx-1.5 text-gray-700">·</span>
                <span :class="run.audio_url ? 'text-emerald-400' : 'text-gray-600'">
                  {{ run.audio_url ? '音频可用' : '无音频' }}
                </span>
                <span class="mx-1.5 text-gray-700">·</span>
                <span :class="run.has_report ? 'text-blue-400' : 'text-gray-600'">
                  {{ run.has_report ? '含报告' : '无报告' }}
                </span>
              </p>
            </div>

            <button
              class="nav-action-btn text-blue-300 flex-shrink-0"
              :disabled="!run.audio_url && !run.has_report"
              @click="$emit('open', run)"
            >
              打开
            </button>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

<script lang="ts" setup>
import type { HistoryRun } from "../services/api";

defineProps<{
  runs: HistoryRun[];
  loading: boolean;
  error: string;
}>();

defineEmits<{
  back: [];
  refresh: [];
  open: [run: HistoryRun];
}>();

/** 把 ISO 时间格式化为本地可读文本；缺失时给出明确占位。 */
function formatTime(value: string | null): string {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
</script>

<style scoped>
.nav-glass {
  background: rgba(30, 32, 38, 0.9);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}
.nav-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
  transition: all 0.2s ease;
  cursor: pointer;
}
.nav-action-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.1);
}
.nav-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.history-card {
  background: rgba(22, 24, 30, 0.85);
  backdrop-filter: blur(30px);
  -webkit-backdrop-filter: blur(30px);
  border: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow:
    0 12px 30px rgba(0, 0, 0, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
  transition: border-color 0.2s ease, transform 0.2s ease;
}
li.history-card:hover {
  border-color: rgba(59, 130, 246, 0.3);
  transform: translateY(-1px);
}

.history-error {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.25);
  backdrop-filter: blur(12px);
}

.history-avatar {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
</style>
