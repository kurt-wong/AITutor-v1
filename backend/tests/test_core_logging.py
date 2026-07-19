"""
test_core_logging.py — core/logging.py + core/prompt_loader.py 测试

覆盖:
- core/logging.py (42行, 60% → 目标95%)
- core/prompt_loader.py (32行, 53% → 目标85%)

测试数量: 25 个
"""

import json
import logging
import pytest
from unittest.mock import patch


# ═══════════════════════════════════════════════════════════════
# logging.py 测试
# ═══════════════════════════════════════════════════════════════

class TestJSONFormatter:
    """JSONFormatter 测试"""

    def test_format_basic(self):
        """基本格式化"""
        from app.core.logging import JSONFormatter
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="test message", args=(), exc_info=None,
        )
        result = formatter.format(record)
        data = json.loads(result)
        assert data["level"] == "INFO"
        assert data["message"] == "test message"
        assert data["logger"] == "test"
        assert "timestamp" in data

    def test_format_with_extra_data(self):
        """带额外数据"""
        from app.core.logging import JSONFormatter
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="test.py",
            lineno=1, msg="warning", args=(), exc_info=None,
        )
        record.extra_data = {"user_id": 123, "action": "login"}
        result = formatter.format(record)
        data = json.loads(result)
        assert data["user_id"] == 123
        assert data["action"] == "login"

    def test_format_with_request_context(self):
        """带请求上下文"""
        from app.core.logging import JSONFormatter, set_request_context, clear_request_context
        formatter = JSONFormatter()
        set_request_context("req-123", "trace-456")
        try:
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="test.py",
                lineno=1, msg="with context", args=(), exc_info=None,
            )
            result = formatter.format(record)
            data = json.loads(result)
            assert data["request_id"] == "req-123"
            assert data["trace_id"] == "trace-456"
        finally:
            clear_request_context()


class TestSetupLogging:
    """setup_logging 测试"""

    def test_setup_logging(self):
        """配置日志"""
        from app.core.logging import setup_logging
        setup_logging(level=logging.DEBUG)
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert len(root.handlers) > 0

    def test_setup_logging_default_level(self):
        """默认级别"""
        from app.core.logging import setup_logging
        setup_logging()
        root = logging.getLogger()
        assert root.level == logging.INFO


class TestRequestIdFunctions:
    """请求 ID 相关函数测试"""

    def test_generate_request_id(self):
        """生成请求 ID"""
        from app.core.logging import generate_request_id
        rid = generate_request_id()
        assert isinstance(rid, str)
        assert len(rid) > 0
        assert "-" in rid

    def test_set_and_clear_request_context(self):
        """设置和清除请求上下文"""
        from app.core.logging import (
            set_request_context, clear_request_context,
            request_id_var, trace_id_var,
        )
        set_request_context("req-001", "trace-001")
        assert request_id_var.get() == "req-001"
        assert trace_id_var.get() == "trace-001"

        clear_request_context()
        assert request_id_var.get() == ""
        assert trace_id_var.get() == ""

    def test_set_request_context_no_trace(self):
        """设置请求上下文 - 无 trace_id"""
        from app.core.logging import set_request_context, clear_request_context, trace_id_var
        set_request_context("req-002")
        assert trace_id_var.get() == "req-002"
        clear_request_context()


class TestRequestTimer:
    """RequestTimer 测试"""

    def test_timer_context_manager(self):
        """计时器上下文管理器"""
        from app.core.logging import RequestTimer
        import time

        with RequestTimer() as timer:
            time.sleep(0.01)

        assert timer.latency_ms > 0
        assert timer.latency_ms < 1000

    def test_timer_init(self):
        """计时器初始化"""
        from app.core.logging import RequestTimer
        timer = RequestTimer()
        assert timer.start_time == 0
        assert timer.latency_ms == 0


class TestGetLogger:
    """get_logger 测试"""

    def test_get_logger(self):
        """获取 logger"""
        from app.core.logging import get_logger
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"


# ═══════════════════════════════════════════════════════════════
# prompt_loader.py 测试
# ═══════════════════════════════════════════════════════════════

class TestPromptLoader:
    """PromptLoader 测试"""

    def test_load_prompt_invalid_name(self):
        """无效名称"""
        from app.core.prompt_loader import load_prompt
        with pytest.raises(ValueError, match="Invalid prompt name"):
            load_prompt("../etc/passwd")

    def test_load_prompt_path_traversal(self):
        """路径遍历攻击"""
        from app.core.prompt_loader import load_prompt
        with pytest.raises(ValueError, match="Invalid prompt name"):
            load_prompt("test/../secret")

    def test_load_prompt_special_chars(self):
        """特殊字符"""
        from app.core.prompt_loader import load_prompt
        with pytest.raises(ValueError, match="Invalid prompt name"):
            load_prompt("test@#$")

    def test_load_prompt_not_found(self, tmp_path):
        """文件不存在"""
        from app.core.prompt_loader import load_prompt
        with patch("app.core.prompt_loader.PROMPTS_DIR", tmp_path):
            with pytest.raises(FileNotFoundError, match="not found"):
                load_prompt("nonexistent")

    def test_load_prompt_success(self, tmp_path):
        """成功加载"""
        from app.core.prompt_loader import load_prompt
        prompt_file = tmp_path / "test_prompt.yaml"
        prompt_file.write_text(
            "name: test_prompt\nversion: '1.0'\nsystem_prompt: Hello {name}\ndescription: Test",
            encoding="utf-8",
        )
        with patch("app.core.prompt_loader.PROMPTS_DIR", tmp_path):
            data = load_prompt("test_prompt")
        assert data["name"] == "test_prompt"
        assert data["system_prompt"] == "Hello {name}"

    def test_get_system_prompt(self, tmp_path):
        """获取系统提示"""
        from app.core.prompt_loader import get_system_prompt
        prompt_file = tmp_path / "test.yaml"
        prompt_file.write_text(
            "name: test\nsystem_prompt: You are a tutor\ndescription: Test",
            encoding="utf-8",
        )
        with patch("app.core.prompt_loader.PROMPTS_DIR", tmp_path):
            result = get_system_prompt("test")
        assert result == "You are a tutor"

    def test_format_prompt(self, tmp_path):
        """格式化提示"""
        from app.core.prompt_loader import format_prompt
        prompt_file = tmp_path / "greet.yaml"
        prompt_file.write_text(
            "name: greet\nsystem_prompt: 'Hello {user_name}, welcome to {place}'\ndescription: Test",
            encoding="utf-8",
        )
        with patch("app.core.prompt_loader.PROMPTS_DIR", tmp_path):
            result = format_prompt("greet", user_name="Alice", place="School")
        assert "Alice" in result
        assert "School" in result

    def test_list_prompts(self, tmp_path):
        """列出所有提示"""
        from app.core.prompt_loader import list_prompts
        for name in ["prompt1", "prompt2"]:
            (tmp_path / f"{name}.yaml").write_text(
                f"name: {name}\nversion: '1.0'\ndescription: Test {name}",
                encoding="utf-8",
            )
        (tmp_path / "prompt_registry.yaml").write_text("name: registry", encoding="utf-8")

        with patch("app.core.prompt_loader.PROMPTS_DIR", tmp_path):
            prompts = list_prompts()

        assert len(prompts) == 2
        names = [p["name"] for p in prompts]
        assert "prompt1" in names
        assert "prompt2" in names
