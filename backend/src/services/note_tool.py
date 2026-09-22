"""带参数容错的 NoteTool。

上游 ``hello_agents.tools.builtin.note_tool.NoteTool`` 在模型把参数多嵌一层
``input`` 时，会因为取不到必填的 ``action`` 而直接返回「❌ 参数验证失败」，
任务笔记因此被**静默丢弃**（既不报错，也没有任何产物）。

这里只在进入参数校验之前把参数解回平铺形态，其余行为完全沿用父类：
不改框架、不改既有写入逻辑，因此对旧数据与正常调用都没有副作用。
"""

from __future__ import annotations

from typing import Any

from hello_agents.tools.builtin.note_tool import NoteTool

from services.tool_params import unwrap_single_input


class RobustNoteTool(NoteTool):
    """在 ``NoteTool`` 之上补齐「参数被多嵌一层 input」的容错。"""

    def run(self, parameters: dict[str, Any]) -> str:
        """执行笔记操作，执行前先做参数归一化。

        Args:
            parameters: 框架解析出的工具参数，可能是被 ``input`` 包了一层的形态。

        Returns:
            工具执行结果文本（与父类一致）。
        """
        return super().run(unwrap_single_input(parameters))
