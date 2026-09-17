"""使用阿里云 DashScope Qwen TTS 从文本生成音频。"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from pathlib import Path
from threading import Event

import requests

from config import Configuration

logger = logging.getLogger(__name__)


class AudioGenerationService:
    """使用 DashScope Qwen TTS 生成播客语音。"""

    def __init__(self, config: Configuration) -> None:
        self._config = config
        self._output_dir = Path(config.audio_output_dir)
        self._ensure_output_dir()

    def _ensure_output_dir(self) -> None:
        """确保音频输出目录存在。"""
        if self._output_dir.exists():
            return

        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Created audio output directory: %s",
                self._output_dir,
            )
        except Exception as e:
            logger.error(
                "Failed to create audio output directory: %s",
                e,
            )

    def generate_audio(
        self,
        script: list[dict[str, str]],
        task_id: str = "default",
        progress_callback: Callable[
            [int, int, str, str],
            bool | None
        ] | None = None,
        cancel_event: Event | None = None,
    ) -> list[str]:
        """
        根据播客脚本生成多个 MP3 音频片段。

        script:
            [
                {
                    "role": "Host",
                    "content": "大家好，欢迎收听..."
                },
                {
                    "role": "Guest",
                    "content": "大家好..."
                }
            ]
        """

        if not self._config.tts_api_key:
            logger.error(
                "TTS_API_KEY 未配置，无法生成音频。"
            )
            return []

        if not self._config.tts_base_url:
            logger.error(
                "TTS_BASE_URL 未配置，无法生成音频。"
            )
            return []

        if not self._config.tts_model:
            logger.error(
                "TTS_MODEL 未配置，无法生成音频。"
            )
            return []

        total = len(script)

        if total == 0:
            logger.warning("没有可生成的播客脚本。")
            return []

        logger.info(
            "准备为 %d 段对话生成语音...",
            total,
        )

        generated_files: list[str] = []

        for index, turn in enumerate(script):
            role = str(turn.get("role", "")).strip()
            content = str(turn.get("content", "")).strip()

            if not role or not content:
                logger.warning(
                    "[TTS %d/%d] 跳过空内容",
                    index + 1,
                    total,
                )
                continue

            # 检查取消
            if cancel_event and cancel_event.is_set():
                logger.info(
                    "Audio generation cancelled before TTS %d/%d",
                    index + 1,
                    total,
                )
                break

            voice = self._get_voice_for_role(role)

            file_name = (
                f"{task_id}_{index:03d}_{role}.mp3"
            )

            file_path = self._output_dir / file_name

            logger.info(
                "[TTS %d/%d] 正在为 %s 生成语音: %s",
                index + 1,
                total,
                role,
                content[:50],
            )

            success = self._call_tts_api(
                text=content,
                voice=voice,
                output_path=file_path,
            )

            if success:
                generated_files.append(str(file_path))

                logger.info(
                    "[TTS %d/%d] ✓ %s 语音生成成功",
                    index + 1,
                    total,
                    role,
                )

                # TTS 完成后检查取消
                if cancel_event and cancel_event.is_set():
                    logger.info(
                        "Audio generation cancelled after TTS %d/%d",
                        index + 1,
                        total,
                    )
                    break

                # 回调上层
                if progress_callback:
                    preview = (
                        content[:30] + "..."
                        if len(content) > 30
                        else content
                    )

                    should_continue = progress_callback(
                        index + 1,
                        total,
                        role,
                        preview,
                    )

                    if should_continue is False:
                        logger.info(
                            "Audio generation cancelled "
                            "by progress callback."
                        )
                        break

            else:
                logger.error(
                    "[TTS %d/%d] ✗ %s 语音生成失败",
                    index + 1,
                    total,
                    role,
                )

        logger.info(
            "语音生成完成，成功 %d/%d 段",
            len(generated_files),
            total,
        )

        return generated_files

    def _get_voice_for_role(self, role: str) -> str:
        """
        将播客角色映射到 Qwen TTS 音色。

        当前使用：
        Host  -> Cherry
        Guest -> Serena

        如果你的项目需要其他音色，
        可以只修改这里。
        """

        role_lower = role.lower()

        if (
            "host" in role_lower
            or "xiayu" in role_lower
            or "夏雨" in role_lower
        ):
            return "Cherry"

        if (
            "guest" in role_lower
            or "liwa" in role_lower
            or "李娃" in role_lower
        ):
            return "Serena"

        # 默认 Host 音色
        return "Cherry"

    def _call_tts_api(
        self,
        text: str,
        voice: str,
        output_path: Path,
    ) -> bool:
        """
        调用 DashScope Qwen TTS API。

        使用 DashScope multimodal-generation 接口。
        """

        if output_path.exists():
            logger.info(
                "Audio file already exists: %s",
                output_path,
            )
            return True

        headers = {
            "Authorization": (
                f"Bearer {self._config.tts_api_key}"
            ),
            "Content-Type": "application/json",
        }

        # Qwen TTS 请求体
        payload = {
            "model": self._config.tts_model,
            "input": {
                "text": text,
                "voice": voice,
            },
        }

        try:
            logger.info(
                "Calling Qwen TTS: model=%s voice=%s",
                self._config.tts_model,
                voice,
            )

            response = requests.post(
                self._config.tts_base_url,
                json=payload,
                headers=headers,
                timeout=getattr(
                    self._config,
                    "tts_timeout",
                    300,
                ),
            )

            logger.info(
                "Qwen TTS response status: %s",
                response.status_code,
            )

            if response.status_code != 200:
                logger.error(
                    "Qwen TTS API failed: HTTP %s",
                    response.status_code,
                )

                logger.error(
                    "Qwen TTS response: %s",
                    response.text[:2000],
                )

                return False

            # 尝试解析 JSON
            try:
                data = response.json()
            except ValueError:
                data = None

            if data is None:
                logger.error(
                    "Qwen TTS returned non-JSON response."
                )
                return False

            # ==================================================
            # 情况 1：API 直接返回音频 URL
            # ==================================================

            audio_url = self._extract_audio_url(data)

            if audio_url:
                logger.info(
                    "Qwen TTS returned audio URL: %s",
                    audio_url,
                )

                return self._download_audio(
                    audio_url,
                    output_path,
                )

            # ==================================================
            # 情况 2：API 返回 base64 音频
            # ==================================================

            audio_base64 = self._extract_audio_base64(data)

            if audio_base64:
                try:
                    audio_bytes = base64.b64decode(
                        audio_base64
                    )

                    with open(
                        output_path,
                        "wb",
                    ) as f:
                        f.write(audio_bytes)

                    logger.info(
                        "Saved Qwen TTS base64 audio: %s",
                        output_path,
                    )

                    return True

                except Exception as e:
                    logger.exception(
                        "Failed to decode Qwen TTS audio: %s",
                        e,
                    )

                    return False

            # ==================================================
            # 情况 3：返回结构和预期不同
            # ==================================================

            logger.error(
                "Qwen TTS 请求成功，但没有找到音频数据。"
            )

            logger.error(
                "Qwen TTS response JSON: %s",
                data,
            )

            return False

        except requests.Timeout:
            logger.error(
                "Qwen TTS request timeout."
            )
            return False

        except requests.RequestException as e:
            logger.error(
                "Qwen TTS network error: %s",
                e,
            )
            return False

        except Exception as e:
            logger.exception(
                "Exception during Qwen TTS call: %s",
                e,
            )
            return False

    def _extract_audio_url(
        self,
        data: dict,
    ) -> str | None:
        """
        从 DashScope 返回结果中寻找音频 URL。

        兼容不同版本返回结构。
        """

        # 常见结构：
        # output.audio.url
        try:
            url = data["output"]["audio"]["url"]

            if isinstance(url, str) and url:
                return url

        except (KeyError, TypeError):
            pass

        # 某些返回结构：
        # output.url
        try:
            url = data["output"]["url"]

            if isinstance(url, str) and url:
                return url

        except (KeyError, TypeError):
            pass

        # 某些返回结构：
        # output.audio
        try:
            audio = data["output"]["audio"]

            if isinstance(audio, str):
                if audio.startswith("http"):
                    return audio

        except (KeyError, TypeError):
            pass

        return None

    def _extract_audio_base64(
        self,
        data: dict,
    ) -> str | None:
        """
        从 API 返回值中寻找 base64 音频数据。
        """

        possible_paths = [
            ("output", "audio", "data"),
            ("output", "audio", "base64"),
            ("output", "audio"),
            ("audio", "data"),
            ("audio", "base64"),
        ]

        for path in possible_paths:
            current = data

            try:
                for key in path:
                    current = current[key]
            except (KeyError, TypeError):
                continue

            if isinstance(current, str):
                # 防止把普通 URL 当成 base64
                if current.startswith("http"):
                    continue

                if len(current) > 100:
                    return current

        return None

    def _download_audio(
        self,
        audio_url: str,
        output_path: Path,
    ) -> bool:
        """
        下载 TTS API 返回的音频 URL。
        """

        try:
            logger.info(
                "Downloading generated audio..."
            )

            response = requests.get(
                audio_url,
                timeout=getattr(
                    self._config,
                    "tts_timeout",
                    300,
                ),
            )

            if response.status_code != 200:
                logger.error(
                    "Audio download failed: HTTP %s",
                    response.status_code,
                )

                logger.error(
                    "Download response: %s",
                    response.text[:1000],
                )

                return False

            if not response.content:
                logger.error(
                    "Downloaded audio is empty."
                )
                return False

            with open(
                output_path,
                "wb",
            ) as f:
                f.write(response.content)

            logger.info(
                "Audio saved successfully: %s",
                output_path,
            )

            return True

        except requests.RequestException as e:
            logger.error(
                "Audio download failed: %s",
                e,
            )
            return False

        except Exception as e:
            logger.exception(
                "Failed to save downloaded audio: %s",
                e,
            )
            return False