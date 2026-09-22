const baseURL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export interface ResearchRequest {
  topic: string;
}

export interface ResearchStreamEvent {
  type: string;
  [key: string]: unknown;
}

export interface StreamOptions {
  signal?: AbortSignal;
  /** 服务端分配的任务 ID，用于精确取消 */
  onTaskId?: (taskId: string) => void;
}

/**
 * 主动取消后端正在执行的研究任务。
 *
 * @param taskId 目标任务 ID；不传则取消后端当前所有活跃任务。
 */
export async function cancelResearch(taskId?: string): Promise<void> {
  try {
    await fetch(`${baseURL}/research/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId ?? null })
    });
  } catch (err) {
    console.warn("Failed to send cancel request:", err);
  }
}

export async function runResearchStream(
  payload: ResearchRequest,
  onEvent: (event: ResearchStreamEvent) => void,
  options: StreamOptions = {}
): Promise<void> {
  const response = await fetch(`${baseURL}/research/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream"
    },
    body: JSON.stringify(payload),
    signal: options.signal
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    throw new Error(
      errorText || `研究请求失败，状态码：${response.status}`
    );
  }

  const body = response.body;
  if (!body) {
    throw new Error("浏览器不支持流式响应，无法获取研究进度");
  }

  // 响应头中的任务 ID 先于首个事件到达，可直接用于取消
  const headerTaskId = response.headers.get("X-Task-Id");
  if (headerTaskId) {
    options.onTaskId?.(headerTaskId);
  }

  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);

      if (rawEvent.startsWith("data:")) {
        const dataPayload = rawEvent.slice(5).trim();
        if (dataPayload) {
          try {
            const event = JSON.parse(dataPayload) as ResearchStreamEvent;
            onEvent(event);

            if (event.type === "task_started") {
              const startedTaskId = String(event.task_id ?? "");
              if (startedTaskId) {
                options.onTaskId?.(startedTaskId);
              }
            }

            if (event.type === "error" || event.type === "done") {
              return;
            }
          } catch (error) {
            console.error("解析流式事件失败：", error, dataPayload);
          }
        }
      }

      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      // 处理可能的尾巴事件
      if (buffer.trim()) {
        const rawEvent = buffer.trim();
        if (rawEvent.startsWith("data:")) {
          const dataPayload = rawEvent.slice(5).trim();
          if (dataPayload) {
            try {
              const event = JSON.parse(dataPayload) as ResearchStreamEvent;
              onEvent(event);
            } catch (error) {
              console.error("解析流式事件失败：", error, dataPayload);
            }
          }
        }
      }
      break;
    }
  }
}

// --- 历史记录 ---

export interface HistoryRun {
  run_id: string;
  topic: string;
  created_at: string | null;
  /** 后端返回的相对路径，如 /output/audio/xxx.mp3；无音频时为 null */
  audio_url: string | null;
  has_report: boolean;
}

export interface HistoryDetail extends HistoryRun {
  report: string;
}

/** 把后端返回的相对路径补全为可直接访问的绝对地址。 */
export function toAbsoluteUrl(path: string | null | undefined): string {
  if (!path) return "";
  return path.startsWith("http") ? path : `${baseURL}${path}`;
}

/** 获取历史运行列表（已产出报告或播客音频者）。 */
export async function fetchHistory(): Promise<HistoryRun[]> {
  const response = await fetch(`${baseURL}/api/history`);
  if (!response.ok) {
    throw new Error(`获取历史记录失败，状态码：${response.status}`);
  }
  const data = await response.json();
  return (data?.runs ?? []) as HistoryRun[];
}

/** 获取单次历史运行的详情（含报告正文）。 */
export async function fetchHistoryDetail(runId: string): Promise<HistoryDetail> {
  const response = await fetch(
    `${baseURL}/api/history/${encodeURIComponent(runId)}`
  );
  if (!response.ok) {
    throw new Error(`获取历史详情失败，状态码：${response.status}`);
  }
  return (await response.json()) as HistoryDetail;
}
