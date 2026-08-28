"""工具调用探针判定逻辑单测：纯函数，不依赖真实网络。

用例覆盖两次生产事故的真实响应形态：
- 2026-08-27 openai 方言打平：tool_calls=null，content 含裸 JSON {"function_call":...}
- 2026-08-26 anthropic 方言打平：无 tool_use 块，stop_reason=end_turn
"""

from services.access_tool_probe import (
    judge_anthropic_nonstream,
    judge_anthropic_stream,
    judge_openai_nonstream,
    judge_openai_stream,
)

# 8/27 徐欣欣事故真实响应形态（ollama 原生 tool_call 泄漏为文本）
OPENAI_FLATTENED_CONTENT = (
    '{"function_call": {"name": "list_files", "arguments": {"path": "."}}}'
)
OPENAI_TOOL_CALLS = [
    {
        "index": 0,
        "type": "function",
        "function": {"name": "probe_echo", "arguments": '{"text": "ok"}'},
    }
]


def test_openai_nonstream_structured_tool_calls_passes() -> None:
    payload = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": OPENAI_TOOL_CALLS,
                },
            }
        ]
    }
    verdict = judge_openai_nonstream(payload)
    assert verdict["ok"] is True
    assert verdict["mode"] == "nonstream"


def test_openai_nonstream_flattened_fingerprint_fails() -> None:
    payload = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": OPENAI_FLATTENED_CONTENT,
                    "tool_calls": None,
                },
            }
        ]
    }
    verdict = judge_openai_nonstream(payload)
    assert verdict["ok"] is False
    assert "打平" in verdict["detail"]


def test_openai_nonstream_no_tool_calls_fails() -> None:
    payload = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "好的，已了解。",
                    "tool_calls": None,
                },
            }
        ]
    }
    verdict = judge_openai_nonstream(payload)
    assert verdict["ok"] is False
    assert "finish_reason=stop" in verdict["detail"]


def test_openai_stream_tool_calls_passes() -> None:
    chunks = [
        {"choices": [{"delta": {"content": ""}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [{"index": 0, "function": {"name": "probe_echo"}}]
                    }
                }
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]
    verdict = judge_openai_stream(chunks)
    assert verdict["ok"] is True
    assert verdict["mode"] == "stream"


def test_openai_stream_flattened_fingerprint_fails() -> None:
    chunks = [
        {"choices": [{"delta": {"content": OPENAI_FLATTENED_CONTENT[:30]}}]},
        {"choices": [{"delta": {"content": OPENAI_FLATTENED_CONTENT[30:]}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    verdict = judge_openai_stream(chunks)
    assert verdict["ok"] is False
    assert "打平" in verdict["detail"]


def test_anthropic_nonstream_tool_use_block_passes() -> None:
    payload = {
        "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": ""},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "probe_echo",
                "input": {"text": "ok"},
            },
        ],
    }
    verdict = judge_anthropic_nonstream(payload)
    assert verdict["ok"] is True


def test_anthropic_nonstream_flattened_fails() -> None:
    """8/26 贾越事故形态：stop_reason=end_turn，工具调用变文本块。"""
    payload = {
        "stop_reason": "end_turn",
        "content": [
            {"type": "text", "text": "我先加载相关技能 " + OPENAI_FLATTENED_CONTENT}
        ],
    }
    verdict = judge_anthropic_nonstream(payload)
    assert verdict["ok"] is False
    assert "打平" in verdict["detail"]


def test_anthropic_nonstream_plain_text_fails() -> None:
    payload = {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "收到，测试正常。"}],
    }
    verdict = judge_anthropic_nonstream(payload)
    assert verdict["ok"] is False
    assert "stop_reason=end_turn" in verdict["detail"]


def test_anthropic_stream_tool_use_event_passes() -> None:
    events = [
        {"type": "message_start"},
        {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "name": "probe_echo"},
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": ""},
        },
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ]
    verdict = judge_anthropic_stream(events)
    assert verdict["ok"] is True
    assert verdict["mode"] == "stream"


def test_anthropic_stream_text_only_fails() -> None:
    events = [
        {"type": "message_start"},
        {"type": "content_block_start", "content_block": {"type": "text"}},
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "无法调用工具"},
        },
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
    ]
    verdict = judge_anthropic_stream(events)
    assert verdict["ok"] is False
    assert "stop_reason=end_turn" in verdict["detail"]
