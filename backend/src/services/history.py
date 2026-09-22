"""历史记录服务：把 output/ 下已生成的产物重建为可浏览的历史列表。

产物其实一直都在磁盘上——报告落在 ``notes/``，音频落在 ``audio/``，
只是缺一个入口去读，所以「之前生成的播客听不了」。本模块不改动任何既有的
写入逻辑，只做只读重建，保证对老数据也立即生效：

- 运行标识 ``run_id`` 复用报告笔记的 note_id（形如 ``note_20260922_235523_21``）。
- 报告正文来自 ``notes/<run_id>.md``；主题取自笔记标题并去掉「研究报告：」前缀。
- 音频来自 ``audio/podcast_task_<run_id>.mp3``（合成阶段以 report_note_id 命名）。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 合法 run_id，用于阻断路径穿越
_RUN_ID_RE = re.compile(r"^note_\d{8}_\d{6}_\d+$")
# 合成产物命名：podcast_task_note_20260922_235523_21.mp3
_PODCAST_AUDIO_RE = re.compile(r"^podcast_task_(note_\d{8}_\d{6}_\d+)\.mp3$")
_REPORT_TITLE_PREFIX = "研究报告："
_UNKNOWN_TOPIC = "未命名主题"


class HistoryService:
    """只读地重建历史运行列表。"""

    def __init__(self, output_dir: str | Path) -> None:
        """基于 output 目录构造。"""
        self._output_dir = Path(output_dir)
        self._notes_dir = self._output_dir / "notes"
        self._audio_dir = self._output_dir / "audio"

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _load_conclusion_notes(self) -> list[dict[str, Any]]:
        """从 notes_index.json 读出所有结论笔记（即最终报告）的元信息。"""
        index_path = self._notes_dir / "notes_index.json"
        if not index_path.is_file():
            logger.warning("notes_index.json 不存在，历史列表将退化为仅依赖音频文件：%s", index_path)
            return []

        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("读取 notes_index.json 失败：%s", exc)
            return []

        notes = payload.get("notes") if isinstance(payload, dict) else None
        if not isinstance(notes, list):
            return []

        return [
            note
            for note in notes
            if isinstance(note, dict) and note.get("type") == "conclusion"
        ]

    def _scan_final_audio(self) -> dict[str, str]:
        """扫描最终合成的播客音频，返回 {run_id: 文件名}。"""
        result: dict[str, str] = {}
        if not self._audio_dir.is_dir():
            return result

        for path in self._audio_dir.glob("podcast_*.mp3"):
            match = _PODCAST_AUDIO_RE.match(path.name)
            if match:
                result[match.group(1)] = path.name
        return result

    @staticmethod
    def _topic_from_title(title: str) -> str:
        topic = (title or "").strip()
        if topic.startswith(_REPORT_TITLE_PREFIX):
            topic = topic[len(_REPORT_TITLE_PREFIX) :].strip()
        return topic or _UNKNOWN_TOPIC

    def _report_path(self, run_id: str) -> Path | None:
        """返回报告笔记路径；run_id 非法时返回 None（阻断路径穿越）。"""
        if not _RUN_ID_RE.match(run_id):
            return None
        return self._notes_dir / f"{run_id}.md"

    @staticmethod
    def _read_report_body(path: Path) -> str:
        """读取报告正文，并剥掉 YAML front matter。"""
        text = path.read_text(encoding="utf-8").strip()
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                text = parts[2].strip()
        return text

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def list_runs(self) -> list[dict[str, Any]]:
        """列出历史运行，按时间倒序。

        Returns:
            每项包含 run_id / topic / created_at / audio_url / has_report。
        """
        audio_by_run = self._scan_final_audio()

        entries: dict[str, dict[str, Any]] = {}
        for note in self._load_conclusion_notes():
            run_id = str(note.get("id") or "")
            if not run_id:
                continue
            entries[run_id] = {
                "run_id": run_id,
                "topic": self._topic_from_title(str(note.get("title") or "")),
                "created_at": note.get("created_at"),
            }

        # 有音频但没有对应报告笔记的运行也要列出（例如笔记索引被清理过）
        for run_id in audio_by_run:
            entries.setdefault(
                run_id,
                {"run_id": run_id, "topic": _UNKNOWN_TOPIC, "created_at": None},
            )

        runs: list[dict[str, Any]] = []
        for run_id, entry in entries.items():
            audio_name = audio_by_run.get(run_id)
            report_path = self._report_path(run_id)
            has_report = bool(report_path and report_path.is_file())

            # 既无音频也无报告的条目没有展示价值
            if not audio_name and not has_report:
                continue

            runs.append(
                {
                    **entry,
                    "audio_url": f"/output/audio/{audio_name}" if audio_name else None,
                    "has_report": has_report,
                }
            )

        # run_id 内嵌 YYYYMMDD_HHMMSS，字符串倒序即时间倒序
        runs.sort(key=lambda item: item["run_id"], reverse=True)
        return runs

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """获取单次运行的详情（含报告正文）。

        Returns:
            详情字典；run_id 非法或该运行无任何产物时返回 None。
        """
        report_path = self._report_path(run_id)
        if report_path is None:
            return None

        audio_name = self._scan_final_audio().get(run_id)
        has_report = report_path.is_file()
        if not audio_name and not has_report:
            return None

        topic = _UNKNOWN_TOPIC
        created_at: str | None = None
        for note in self._load_conclusion_notes():
            if str(note.get("id") or "") == run_id:
                topic = self._topic_from_title(str(note.get("title") or ""))
                created_at = note.get("created_at")
                break

        report = ""
        if has_report:
            try:
                report = self._read_report_body(report_path)
            except OSError as exc:
                logger.warning("读取报告正文失败 %s：%s", report_path, exc)

        return {
            "run_id": run_id,
            "topic": topic,
            "created_at": created_at,
            "audio_url": f"/output/audio/{audio_name}" if audio_name else None,
            "has_report": has_report,
            "report": report,
        }
