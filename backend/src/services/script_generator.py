"""将研究报告转换为播客脚本的服务。"""

from __future__ import annotations

import json
import logging
import re

from openai import OpenAI

from config import Configuration
from models import SummaryState
from prompts import script_writer_instructions

logger = logging.getLogger(__name__)

# 播客脚本的 JSON Schema
SCRIPT_JSON_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "role": {
                "type": "string",
                "enum": ["Host", "Guest"],
                "description": "对话角色，Host 为主持人，Guest 为嘉宾"
            },
            "content": {
                "type": "string",
                "description": "对话内容"
            }
        },
        "required": ["role", "content"]
    },
    "minItems": 6,
    "maxItems": 15
}


class ScriptGenerationService:
    """从研究报告生成对话脚本（使用结构化输出）。"""

    def __init__(
        self,
        config: Configuration,
        script_agent: OpenAI | None = None,
    ) -> None:
        """
        初始化服务。

        Args:
            config: 全局配置对象。
            script_agent: 可选的自定义脚本生成客户端/代理。
                如果提供，将直接使用该客户端；否则将基于配置创建默认的 OpenAI 客户端。
        """
        self._config = config
        # 优先使用注入的自定义客户端，以保持向后兼容和可测试性；
        # 如果未提供，则基于配置创建默认的 OpenAI 客户端以支持结构化输出。
        self._client = script_agent or OpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
        )
        # 使用 fast_llm_model（ecnu-max）进行脚本生成，它支持结构化输出
        self._model = config.fast_llm_model or "ecnu-max"

    

    def _parse_script_json(self, content: str) -> list | None:
        """
        尝试多种方式解析脚本 JSON。
        
        Args:
            content: LLM 返回的原始内容
            
        Returns:
            解析后的列表，失败返回 None
        """
        # 1. 直接尝试解析
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.debug("Direct JSON parse failed at char %d: %s", e.pos, e.msg)
        
        # 2. 尝试从 markdown 代码块中提取
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if json_match:
            try:
                result = json.loads(json_match.group(1).strip())
                logger.info("Extracted JSON from markdown code block")
                return result
            except json.JSONDecodeError:
                pass
        
        # 3. 提取 JSON 数组部分
        start_idx = content.find('[')
        end_idx = content.rfind(']')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = content[start_idx:end_idx + 1]
            
            # 3a. 直接尝试
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.debug("Array extraction failed at char %d: %s", e.pos, e.msg)
                # 记录出错位置附近的内容
                error_start = max(0, e.pos - 50)
                error_end = min(len(json_str), e.pos + 50)
                logger.debug("Content around error: ...%s...", json_str[error_start:error_end])
            
            # 3b. 尝试修复常见问题
            fixed_json = self._fix_json_issues(json_str)
            try:
                result = json.loads(fixed_json)
                logger.info("Parsed JSON after fixing common issues")
                return result
            except json.JSONDecodeError:
                pass
        
        # 4. 最后尝试：逐个对象解析
        result = self._parse_objects_individually(content)
        if result:
            logger.info("Parsed %d objects individually", len(result))
            return result
        
        logger.error("Could not parse JSON from response. First 500 chars: %s", content[:500])
        return None
    
    def _fix_json_issues(self, json_str: str) -> str:
        """尝试修复常见的 JSON 格式问题。"""
        fixed = json_str
        
        # 替换中文引号为英文引号
        fixed = fixed.replace('"', '"').replace('"', '"')
        fixed = fixed.replace(''', "'").replace(''', "'")
        
        # 移除可能的 BOM 或其他不可见字符
        fixed = fixed.strip('\ufeff\u200b\u200c\u200d')
        # 修复未转义的换行符（在字符串值内）
        # 这是一个简化的修复，可能不完美
        def escape_newlines_in_strings(match):
            return match.group(0).replace('\n', '\\n').replace('\r', '\\r')
        
        # 匹配 JSON 字符串值
        fixed = re.sub(r'"[^"]*"', escape_newlines_in_strings, fixed)
        
        return fixed
    
    def _parse_objects_individually(self, content: str) -> list | None:
        """
        尝试逐个解析 JSON 对象。
        
        当整体解析失败时，尝试提取每个 {role, content} 对象。
        """
        results = []
        
        # 匹配 {"role": "...", "content": "..."} 模式
        # 使用非贪婪匹配
        pattern = r'\{\s*"role"\s*:\s*"(Host|Guest)"\s*,\s*"content"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
        
        for match in re.finditer(pattern, content, re.DOTALL):
            role = match.group(1)
            # 处理转义字符
            content_text = match.group(2)
            try:
                # 使用 json.loads 来正确处理转义
                content_text = json.loads(f'"{content_text}"')
            except Exception:
                pass
            results.append({"role": role, "content": content_text})
        
        if results:
            return results
        
        return None

    def generate_script(self, state: SummaryState) -> list:
        """
        根据研究报告生成播客脚本
        """

        report = state.structured_report

        if not report:
            raise ValueError("结构化报告为空，无法生成脚本")

        messages = [
            {
                "role": "system",
                "content": script_writer_instructions,
            },
            {
                "role": "user",
                "content": f"""
    请根据下面的研究报告生成双人播客脚本。
    
    要求：
    1. Host负责引导话题
    2. Guest负责专业解释
    3. 输出JSON数组
    4. 每个对象包含role和content
    
    
    研究报告：
    
    {report}
    """
            }
        ]

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.7,
        )

        content = response.choices[0].message.content

        script = self._parse_script_json(content)

        if not script:
            raise ValueError("播客脚本解析失败")

        # 保存到状态
        state.podcast_script = script

        return script