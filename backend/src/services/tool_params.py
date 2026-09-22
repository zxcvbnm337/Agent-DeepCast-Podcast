"""工具调用参数归一化。

模型有时不遵守「参数平铺」的约定，而是把参数多嵌一层 ``input``：

    [TOOL_CALL:note:{"input": "{\\"action\\":\\"create\\", ...}"}]

此时框架解析出的参数字典退化为 ``{"input": "<一串 JSON 字符串>"}``，
``action`` / ``task_id`` / ``note_id`` 等键**全部取不到**，后果有两层：

1. 工具侧：``NoteTool.validate_parameters`` 因为缺少必填的 ``action`` 直接返回
   「参数验证失败」，**笔记根本不会被创建**；
2. 事件侧：``task_id`` 只能推断为 None，即便笔记创建成功也无法挂到对应任务上。

本模块提供**窄条件**解包（仅当参数只有一个键且键名为 ``input``、其值能解析为
dict 时才解包），避免误伤正常参数。
"""

from __future__ import annotations

import json
from typing import Any


def unwrap_single_input(parameters: dict[str, Any]) -> dict[str, Any]:
    """解掉「多嵌一层 input」的参数包装。

    只在「参数字典恰好只有一个键、且键名为 ``input``」时尝试解包；其余情况原样返回，
    以保证这个归一化不会改变任何正常调用的语义。

    Args:
        parameters: 框架解析出的工具参数。

    Returns:
        解包后的参数字典；无法解包时返回入参本身。
    """
    if not isinstance(parameters, dict):
        return parameters
    if list(parameters.keys()) != ["input"]:
        return parameters

    inner = parameters["input"]

    # 值已经是 dict：直接采用
    if isinstance(inner, dict):
        return inner or parameters

    # 值是字符串：仅在形如 JSON 对象时尝试解析
    if isinstance(inner, str):
        text = inner.strip()
        if not text.startswith("{"):
            return parameters
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return parameters
        if isinstance(decoded, dict) and decoded:
            return decoded

    return parameters
