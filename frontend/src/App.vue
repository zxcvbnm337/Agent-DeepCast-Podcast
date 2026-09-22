<template>
  <div class="app-root min-h-screen">
    <!-- View 1: Setup -->
    <SetupView
      v-if="currentView === 'setup'"
      v-model:topic="form.topic"
      @start="startProduction"
      @open-history="openHistory"
    />

    <!-- View 2: Production -->
    <ProductionView
      v-else-if="currentView === 'producing'"
      ref="productionRef"
      :logs="logs"
      :is-waiting="isWaiting"
      :waiting-dots="waitingDots"
      :production-stage="productionStage"
      :failed-at="failedAt"
      :status-message="currentStatusMessage"
      :progress-percent="progressPercent"
      :report-ready="reportReady"
      :podcast-ready="podcastReady"
      :audio-url="audioUrl"
      @cancel="cancelProduction"
      @back="backToSetup"
      @download-report="downloadReport"
      @go-player="currentView = 'player'"
    />

    <!-- View 3: Player -->
    <PlayerView
      v-else-if="currentView === 'player'"
      :topic="form.topic"
      :audio-url="audioUrl"
      :report-markdown="reportMarkdown"
      @reset="resetApp"
      @download-report="downloadReport"
    />

    <!-- View 4: History -->
    <HistoryView
      v-else-if="currentView === 'history'"
      :runs="historyRuns"
      :loading="historyLoading"
      :error="historyError"
      @back="currentView = 'setup'"
      @refresh="loadHistory"
      @open="openHistoryRun"
    />
  </div>
</template>

<script lang="ts" setup>
import { reactive, ref, nextTick } from "vue";
import {
  runResearchStream,
  cancelResearch,
  fetchHistory,
  fetchHistoryDetail,
  toAbsoluteUrl,
  type ResearchStreamEvent,
  type HistoryRun,
} from "./services/api";

import SetupView from "./components/SetupView.vue";
import ProductionView from "./components/ProductionView.vue";
import PlayerView from "./components/PlayerView.vue";
import HistoryView from "./components/HistoryView.vue";
import type { LogEntry } from "./components/TerminalLog.vue";
import type { ProductionStage } from "./components/ProductionView.vue";

// --- Types ---
type ViewState = "setup" | "producing" | "player" | "history";

// --- State ---
const currentView = ref<ViewState>("setup");
const productionStage = ref<ProductionStage>("research");
// 记录失败发生在哪一步，让 Pipeline 仍能高亮出错的阶段
const failedAt = ref<ProductionStage>("research");
const form = reactive({ topic: "" });

const logs = ref<LogEntry[]>([]);
const reportReady = ref(false);
const podcastReady = ref(false);

const audioProgress = reactive({ current: 0, total: 0, role: "" });
const taskProgress = reactive({ completed: 0, total: 0 });
const progressPercent = ref(0);
const currentStatusMessage = ref("");
const isWaiting = ref(false);
const waitingDots = ref(".");
let waitingInterval: ReturnType<typeof setInterval> | null = null;

const reportMarkdown = ref("");
const audioUrl = ref("");

// 历史记录（从后端 output/ 目录只读重建，不依赖本次会话状态）
const historyRuns = ref<HistoryRun[]>([]);
const historyLoading = ref(false);
const historyError = ref("");
// 标记当前播放器展示的是历史记录，决定返回时回到历史列表还是设置页
const playerFromHistory = ref(false);

let abortController: AbortController | null = null;
let currentTaskId: string | null = null;

const productionRef = ref<InstanceType<typeof ProductionView> | null>(null);

// --- Helpers ---

function startWaitingAnimation() {
  stopWaitingAnimation();
  isWaiting.value = true;
  waitingDots.value = ".";
  waitingInterval = setInterval(() => {
    waitingDots.value = waitingDots.value.length >= 3 ? "." : waitingDots.value + ".";
  }, 500);
}

function stopWaitingAnimation() {
  isWaiting.value = false;
  if (waitingInterval) {
    clearInterval(waitingInterval);
    waitingInterval = null;
  }
}

const TERMINAL_STAGES: ProductionStage[] = ["done", "cancelled", "failed"];

/**
 * 判断是否已进入终态。
 *
 * 参数显式标注类型是必要的：TypeScript 的控制流分析会把 `productionStage.value`
 * 收窄成 startProduction 开头赋的字面量 "research"，导致与 "done" / "cancelled"
 * 比较时误报 TS2367（两侧无重叠）。
 */
function isTerminalStage(stage: ProductionStage) {
  return TERMINAL_STAGES.includes(stage);
}

function addLog(message: string) {
  const time = new Date().toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  logs.value.push({ time, message });
  nextTick(() => {
    productionRef.value?.scrollTerminal();
  });
}

// --- Actions ---

async function startProduction() {
  if (!form.topic.trim()) return;

  currentView.value = "producing";
  productionStage.value = "research";
  logs.value = [];
  reportMarkdown.value = "";
  audioUrl.value = "";
  audioProgress.current = 0;
  audioProgress.total = 0;
  taskProgress.completed = 0;
  taskProgress.total = 0;
  progressPercent.value = 2;
  currentStatusMessage.value = "正在初始化...";
  reportReady.value = false;
  podcastReady.value = false;

  abortController = new AbortController();
  currentTaskId = null;
  failedAt.value = "research";
  playerFromHistory.value = false;
  startWaitingAnimation();

  addLog("🚀 启动 DeepCast 制作流程...");
  addLog(`📌 主题: ${form.topic}`);

  try {
    await runResearchStream(
      { topic: form.topic },
      handleStreamEvent,
      {
        signal: abortController.signal,
        onTaskId: (id) => {
          currentTaskId = id;
        }
      }
    );
  } catch (err: any) {
    if (err.name === "AbortError" || err.message?.includes("aborted")) {
      addLog("🛑 制作已取消。");
    } else {
      addLog(`❌ 错误: ${err.message || err}`);
      console.error(err);
    }
  } finally {
    stopWaitingAnimation();
    // 兜底：若事件流既没有给出 done / cancelled / error 就结束了（服务端进程崩溃、
    // 网络中断、代理超时等），必须显式收尾，否则界面会永远停在「正在处理...」，
    // 用户无法判断是仍在运行还是已经失败。
    // 显式标注让 TS 不要用控制流收窄后的字面量类型
    const stageAfterRun: ProductionStage = productionStage.value;
    if (!isTerminalStage(stageAfterRun)) {
      failedAt.value = stageAfterRun;
      productionStage.value = "failed";
      currentStatusMessage.value = "制作中断：事件流意外结束";
      addLog("❌ [ERROR] 事件流意外结束（未收到完成或失败事件）");
    }
  }
}

function handleStreamEvent(event: ResearchStreamEvent) {
  console.log("Event:", event.type, event);

  if (event.type === "task_started") {
    const startedId = String((event as any).task_id || "");
    if (startedId) {
      addLog(`🆔 [TASK] 任务 ID: ${startedId}`);
    }
  }

  if (event.type === "log") {
    const msg = String((event as any).message || "");
    const cleanMsg = msg.replace(/\u001b\[\d+m/g, "");
    addLog(`INFO: ${cleanMsg}`);

    const ttsMatch = cleanMsg.match(/\[TTS (\d+)\/(\d+)\]/);
    if (ttsMatch) {
      audioProgress.current = parseInt(ttsMatch[1], 10);
      audioProgress.total = parseInt(ttsMatch[2], 10);
      currentStatusMessage.value = `音频生成: ${audioProgress.current}/${audioProgress.total}`;
    }
    return;
  }

  if (event.type === "stage_change") {
    const payload = event as any;
    const stage = payload.stage;
    const message = payload.message || "";
    currentStatusMessage.value = message;

    addLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    addLog(`📌 [STAGE] ${stage.toUpperCase()} - ${message}`);
    addLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");

    if (stage === "report") {
      productionStage.value = "research";
      progressPercent.value = 40;
    } else if (stage === "script") {
      productionStage.value = "script";
      progressPercent.value = 55;
    } else if (stage === "audio") {
      productionStage.value = "audio";
      progressPercent.value = 70;
    } else if (stage === "synthesis") {
      productionStage.value = "audio";
      progressPercent.value = 95;
    }
  }

  if (event.type === "tool_call") {
    const p = event as any;
    addLog(`🔧 [TOOL] ${p.tool} - ${p.agent || "Agent"}`);
  }

  if (event.type === "todo_list") {
    const p = event as any;
    const tasks = p.tasks || [];
    taskProgress.total = tasks.length;
    taskProgress.completed = 0;
  }

  if (event.type === "task_status") {
    const p = event as any;
    if (p.status === "completed") {
      taskProgress.completed++;
      if (taskProgress.total > 0) {
        progressPercent.value = Math.round((taskProgress.completed / taskProgress.total) * 40);
      }
      addLog(`✅ [TASK ${p.task_id}] ${p.title}`);
    } else if (p.status === "in_progress") {
      addLog(`🚀 [TASK ${p.task_id}] ${p.title} (In Progress)`);
    } else if (p.status === "failed") {
      addLog(`❌ [TASK ${p.task_id}] Failed: ${p.title}`);
    }
  }

  if (event.type === "final_report") {
    reportMarkdown.value = String((event as any).report);
    reportReady.value = true;
    addLog("📄 [REPORT] 报告已生成");
  }

  if (event.type === "podcast_script") {
    productionStage.value = "audio";
    addLog("🎙️ [SCRIPT] 剧本已生成");
  }

  if (event.type === "audio_start") {
    const p = event as any;
    audioProgress.total = p.total || 0;
    addLog(`🎵 [AUDIO] 开始生成音频, 共 ${audioProgress.total} 段`);
  }

  if (event.type === "audio_progress") {
    const p = event as any;
    audioProgress.current = p.current;
    audioProgress.total = p.total;
    currentStatusMessage.value = `生成音频: ${p.role} (${p.current}/${p.total})`;
    if (p.total > 0) {
      progressPercent.value = 70 + Math.round((p.current / p.total) * 25);
    }
  }

  if (event.type === "podcast_ready") {
    const p = event as any;
    const filename = String(p.file).split(/[\\/]/).pop();
    if (filename) {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
      audioUrl.value = `${baseUrl}/output/audio/${filename}`;
      podcastReady.value = true;
      productionStage.value = "done";
      progressPercent.value = 100;
      currentStatusMessage.value = "🎉 播客制作完成！";
      stopWaitingAnimation();
      addLog(`🎉 [PODCAST] 制作完成: ${filename}`);
    }
  }

  if (event.type === "error") {
    const detail = String((event as any).detail || (event as any).message || "未知错误");
    addLog(`❌ [ERROR] 制作中断：${detail}`);
    stopWaitingAnimation();
    if (productionStage.value !== "failed") {
      failedAt.value = productionStage.value;
    }
    productionStage.value = "failed";
    currentStatusMessage.value = `制作失败：${detail}`;
    return;
  }

  if (event.type === "cancelled") {
    const msg = (event as any).message || "研究任务已取消";
    addLog(`🛑 [CANCELLED] ${msg}`);
    stopWaitingAnimation();
    productionStage.value = "cancelled";
    currentStatusMessage.value = "任务已取消";
    return;
  }

  if (event.type === "done") {
    addLog("✅ [DONE] 所有任务结束");
    stopWaitingAnimation();
    productionStage.value = "done";
    progressPercent.value = 100;

    if (!podcastReady.value && audioProgress.total > 0) {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
      fetch(`${baseUrl}/api/audio/latest`)
        .then(res => res.json())
        .then(data => {
          if (data.file) {
            audioUrl.value = `${baseUrl}${data.url}`;
            podcastReady.value = true;
            currentStatusMessage.value = "🎉 播客制作完成！";
            addLog(`🎉 [PODCAST] 找到音频文件: ${data.file}`);
          } else {
            currentStatusMessage.value = "任务完成（音频未生成）";
            addLog(`⚠️ 未找到音频文件: ${data.error || "未知错误"}`);
          }
        })
        .catch(err => {
          currentStatusMessage.value = "任务完成（无法获取音频）";
          addLog(`⚠️ 获取音频文件失败: ${err.message}`);
        });
    } else if (podcastReady.value) {
      currentStatusMessage.value = "🎉 播客制作完成！";
    } else {
      currentStatusMessage.value = "任务完成（音频可能未生成）";
    }
  }
}

function cancelProduction() {
  if (confirm("确定要取消制作吗？")) {
    addLog("🛑 用户请求取消制作...");

    // 1. 立即中断 SSE 连接 — 后端 monitor_disconnect 会自动检测并设置 cancel_event
    if (abortController) {
      abortController.abort();
      abortController = null;
    }

    // 2. 显式调用 cancel API 作为后备（防止 disconnect 检测延迟）
    cancelResearch(currentTaskId ?? undefined).catch(() => {});

    stopWaitingAnimation();
    productionStage.value = "cancelled";
    addLog("🛑 已取消制作");

    setTimeout(() => {
      currentView.value = "setup";
      currentStatusMessage.value = "";
    }, 1000);
  }
}

function resetApp() {
  stopWaitingAnimation();
  currentStatusMessage.value = "";
  reportReady.value = false;
  podcastReady.value = false;
  audioUrl.value = "";

  // 从历史记录打开的播放器，返回历史列表而非清空重来
  if (playerFromHistory.value) {
    playerFromHistory.value = false;
    currentView.value = "history";
    loadHistory();
    return;
  }

  currentView.value = "setup";
  form.topic = "";
}

/**
 * 失败后返回设置页，但保留已填主题，方便用户直接重试。
 * （resetApp 会清空主题，用于播放器页的「重新开始」。）
 */
function backToSetup() {
  currentView.value = "setup";
  currentStatusMessage.value = "";
  stopWaitingAnimation();
}

// --- History ---

async function loadHistory() {
  historyLoading.value = true;
  historyError.value = "";
  try {
    historyRuns.value = await fetchHistory();
  } catch (err: any) {
    historyError.value = err.message || String(err);
    historyRuns.value = [];
  } finally {
    historyLoading.value = false;
  }
}

function openHistory() {
  currentView.value = "history";
  loadHistory();
}

/**
 * 打开一条历史记录：拉取详情后复用播放器页展示。
 * 主题、音频地址、报告正文都直接覆盖到当前状态，播放器无需区分「新生成」与「历史」。
 */
async function openHistoryRun(run: HistoryRun) {
  historyLoading.value = true;
  historyError.value = "";
  try {
    const detail = await fetchHistoryDetail(run.run_id);
    form.topic = detail.topic || run.topic;
    audioUrl.value = detail.audio_url ? toAbsoluteUrl(detail.audio_url) : "";
    reportMarkdown.value = detail.report || "";
    reportReady.value = !!detail.report;
    podcastReady.value = !!detail.audio_url;
    progressPercent.value = 100;
    currentStatusMessage.value = "";
    productionStage.value = "done";
    failedAt.value = "done";
    logs.value = [];
    playerFromHistory.value = true;
    currentView.value = "player";
  } catch (err: any) {
    historyError.value = err.message || String(err);
  } finally {
    historyLoading.value = false;
  }
}

function downloadReport() {
  if (!reportMarkdown.value) return;
  const blob = new Blob([reportMarkdown.value], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "DeepCast深度研究报告.md";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
</script>

<style scoped>
.app-root {
  background: linear-gradient(145deg, #0c0e14 0%, #111420 30%, #0e1018 60%, #0a0c12 100%);
  background-attachment: fixed;
}
</style>