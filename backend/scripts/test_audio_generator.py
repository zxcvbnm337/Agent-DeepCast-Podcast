import os
import sys
import unittest
from unittest.mock import MagicMock, mock_open, patch

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from services.audio_generator import AudioGenerationService

# 200 个 'A' 是合法 base64，长度 > 100 时会被 _extract_audio_base64 识别为音频数据
FAKE_AUDIO_B64 = "A" * 200


def _ok_response():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"output": {"audio": {"data": FAKE_AUDIO_B64}}}
    return response


def _failed_response():
    response = MagicMock()
    response.status_code = 500
    response.text = "Internal Server Error"
    return response


class TestAudioGenerationService(unittest.TestCase):
    def setUp(self):
        self.mock_config = MagicMock()
        self.mock_config.tts_api_key = "test_key"
        self.mock_config.audio_output_dir = "./test_output"
        self.mock_config.tts_base_url = "http://test.api/tts"
        self.mock_config.tts_model = "test-tts"
        self.mock_config.tts_timeout = 300
        self.mock_config.ffmpeg_path = "ffmpeg"
        # 默认串行，保证断言顺序稳定
        self.mock_config.tts_max_workers = 1
        self.mock_config.tts_max_retries = 2

        # Patch Path.mkdir to avoid actual filesystem creation during init
        with patch('pathlib.Path.mkdir'):
            self.service = AudioGenerationService(self.mock_config)

        # 去掉退避等待，避免测试真的 sleep
        self.service._retry_backoff_seconds = 0.0

    @patch('requests.post')
    @patch('builtins.open', new_callable=mock_open)
    @patch('pathlib.Path.exists')
    def test_generate_audio_success(self, mock_exists, mock_file, mock_post):
        mock_exists.return_value = False  # File doesn't exist
        mock_post.return_value = _ok_response()

        script = [
            {"role": "Host", "content": "Hello world"},
            {"role": "Guest", "content": "Hi host"}
        ]

        files = self.service.generate_audio(script, "task_123")

        self.assertEqual(len(files), 2)
        self.assertTrue(files[0].endswith("task_123_000_Host.mp3"))
        self.assertTrue(files[1].endswith("task_123_001_Guest.mp3"))
        self.assertEqual(mock_post.call_count, 2)

        # 请求体结构：{model, input: {text, voice}}
        _, kwargs = mock_post.call_args_list[0]
        self.assertEqual(kwargs["json"]["model"], "test-tts")
        self.assertEqual(kwargs["json"]["input"]["text"], "Hello world")
        self.assertEqual(kwargs["json"]["input"]["voice"], "Cherry")

        _, kwargs = mock_post.call_args_list[1]
        self.assertEqual(kwargs["json"]["input"]["text"], "Hi host")
        self.assertEqual(kwargs["json"]["input"]["voice"], "Serena")

    def test_generate_audio_no_api_key(self):
        self.mock_config.tts_api_key = None
        script = [{"role": "Host", "content": "Hello"}]

        files = self.service.generate_audio(script)
        self.assertEqual(files, [])

    def test_generate_audio_skips_empty_turns(self):
        with patch('requests.post') as mock_post, \
                patch('builtins.open', new_callable=mock_open), \
                patch('pathlib.Path.exists', return_value=False):
            mock_post.return_value = _ok_response()

            script = [
                {"role": "Host", "content": "  "},
                {"role": "Host", "content": "有效内容"},
            ]

            files = self.service.generate_audio(script, "task_skip")

            # 空片段被跳过，且保留下标 001 以维持与脚本的对应关系
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].endswith("task_skip_001_Host.mp3"))
            self.assertEqual(mock_post.call_count, 1)

    @patch('requests.post')
    @patch('pathlib.Path.exists', return_value=False)
    def test_generate_audio_api_failure_retries_then_skips(self, mock_exists, mock_post):
        mock_post.return_value = _failed_response()

        script = [{"role": "Host", "content": "Hello"}]
        failures = []

        files = self.service.generate_audio(
            script,
            "task_fail",
            failure_callback=lambda pos, role, reason: failures.append((pos, role, reason)),
        )

        self.assertEqual(files, [])
        # 1 次初始尝试 + 2 次重试
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][0], 1)
        self.assertEqual(failures[0][1], "Host")

    def test_generate_audio_retry_succeeds_on_second_attempt(self):
        with patch('requests.post') as mock_post, \
                patch('builtins.open', new_callable=mock_open), \
                patch('pathlib.Path.exists', return_value=False):
            mock_post.side_effect = [_failed_response(), _ok_response()]

            script = [{"role": "Guest", "content": "重试后成功"}]
            files = self.service.generate_audio(script, "task_retry")

            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].endswith("task_retry_000_Guest.mp3"))
            self.assertEqual(mock_post.call_count, 2)

    def test_partial_failure_keeps_successful_segments_in_order(self):
        with patch('requests.post') as mock_post, \
                patch('builtins.open', new_callable=mock_open), \
                patch('pathlib.Path.exists', return_value=False):
            # 第 1 段成功、第 2 段始终失败、第 3 段成功
            mock_post.side_effect = [
                _ok_response(),
                _failed_response(), _failed_response(), _failed_response(),
                _ok_response(),
            ]

            script = [
                {"role": "Host", "content": "第一段"},
                {"role": "Guest", "content": "第二段"},
                {"role": "Host", "content": "第三段"},
            ]

            files = self.service.generate_audio(script, "task_partial")

            self.assertEqual(len(files), 2)
            self.assertTrue(files[0].endswith("task_partial_000_Host.mp3"))
            self.assertTrue(files[1].endswith("task_partial_002_Host.mp3"))

    def test_concurrent_generation_preserves_order(self):
        self.mock_config.tts_max_workers = 3

        with patch('pathlib.Path.mkdir'):
            service = AudioGenerationService(self.mock_config)
        service._retry_backoff_seconds = 0.0

        with patch('requests.post') as mock_post, \
                patch('builtins.open', new_callable=mock_open), \
                patch('pathlib.Path.exists', return_value=False):
            mock_post.return_value = _ok_response()

            script = [
                {"role": "Host", "content": f"第 {i} 段"} for i in range(6)
            ]

            files = service.generate_audio(script, "task_parallel")

            self.assertEqual(len(files), 6)
            for index, path in enumerate(files):
                self.assertTrue(path.endswith(f"task_parallel_{index:03d}_Host.mp3"))

    def test_get_voice_for_role(self):
        self.assertEqual(self.service._get_voice_for_role("Host"), "Cherry")
        self.assertEqual(self.service._get_voice_for_role("Xiayu"), "Cherry")
        self.assertEqual(self.service._get_voice_for_role("Guest"), "Serena")
        self.assertEqual(self.service._get_voice_for_role("Liwa"), "Serena")
        self.assertEqual(self.service._get_voice_for_role("Unknown"), "Cherry")  # Default


if __name__ == '__main__':
    unittest.main()
