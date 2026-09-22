"""将任务结果整合为最终报告的服务。"""

from __future__ import annotations

import logging
from pathlib import Path

from hello_agents import ToolAwareSimpleAgent

from config import Configuration
from models import SummaryState
from services.text_processing import strip_tool_calls
from utils import strip_thinking_tokens

logger = logging.getLogger(__name__)


class ReportingService:
    """生成最终的结构化报告。"""

    def __init__(  # noqa: D107
        self, report_agent: ToolAwareSimpleAgent, config: Configuration
    ) -> None:
        self._agent = report_agent
        self._config = config

    def _load_note_content(self, note_id: str) -> str | None:
        """
        直接从笔记工作区读取任务笔记全文。

        早期实现要求模型自行回放 ``[TOOL_CALL:note:{"action":"read",...}]``
        才能读到笔记，把报告质量押在模型能否精确复现标记格式上；一旦标记格式
        有偏差，报告会静默降级为只用任务总结。笔记文件本来就在本地工作区，
        由后端直接读取更可靠，同时省掉一轮工具调用往返。
        """
        workspace = self._config.notes_workspace
        if not workspace or not note_id:
            return None

        path = Path(workspace) / f"{note_id}.md"
        try:
            if not path.is_file():
                logger.warning("Task note file not found: %s", path)
                return None
            content = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Failed to read task note %s: %s", path, exc)
            return None

        return content or None

    def generate_report(self, state: SummaryState) -> str:
        """
        基于完成的任务生成结构化报告。

        Args:
            state: 包含任务结果和笔记的研究状态。

        Returns:
            Markdown 格式的报告文本。
        """
        tasks_block = []
        missing_notes: list[str] = []

        for task in state.todo_items:
            summary_block = task.summary or "暂无可用信息"
            sources_block = task.sources_summary or "暂无来源"

            note_block = ""
            if task.note_id:
                note_content = self._load_note_content(task.note_id)
                if note_content:
                    note_block = (
                        f"- 任务笔记（{task.note_id}，已由系统读取）：\n{note_content}\n"
                    )
                else:
                    missing_notes.append(task.note_id)
                    note_block = (
                        f"- 任务笔记（{task.note_id}）读取失败，请以上方任务总结为准\n"
                    )

            tasks_block.append(
                f"### 任务 {task.id}: {task.title}\n"
                f"- 任务目标：{task.intent}\n"
                f"- 检索查询：{task.query}\n"
                f"- 执行状态：{task.status}\n"
                f"- 任务总结：\n{summary_block}\n"
                f"- 来源概览：\n{sources_block}\n"
                f"{note_block}"
            )

        if missing_notes:
            logger.warning(
                "Report built with %d unavailable task note(s): %s",
                len(missing_notes),
                ", ".join(missing_notes),
            )

        prompt = (
            f"研究主题：{state.research_topic}\n"
            f"任务概览：\n{''.join(tasks_block)}\n"
            "请整合以上全部信息，撰写一份完整的深度研究报告。\n"
            "说明：任务笔记内容已由系统直接读取并附在上方，无需调用 note 工具读取；"
            "最终报告由系统统一落库，你只需输出报告正文。"
        )

        response = self._agent.run(prompt)
        self._agent.clear_history()

        report_text = response.strip()
        if self._config.strip_thinking_tokens:
            report_text = strip_thinking_tokens(report_text)

        report_text = strip_tool_calls(report_text).strip()

        return report_text or "报告生成失败，请检查输入。"
