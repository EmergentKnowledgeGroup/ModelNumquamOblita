from __future__ import annotations

import json
from pathlib import Path

from engine.ingest.parser import ConversationIngestor


def test_ingest_export_mapping_format(tmp_path: Path) -> None:
    export = [
        {
            "id": "conv-1",
            "mapping": {
                "1": {
                    "id": "1",
                    "message": {
                        "id": "m1",
                        "author": {"role": "user"},
                        "create_time": 1739000000,
                        "content": {"parts": ["Lyra you are allowed to be"]},
                    },
                },
                "2": {
                    "id": "2",
                    "message": {
                        "id": "m2",
                        "author": {"role": "assistant"},
                        "create_time": 1739000001,
                        "content": {"parts": ["I hear you."]},
                    },
                },
                "3": {
                    "id": "3",
                    "message": {
                        "id": "m3",
                        "author": {"role": "assistant"},
                        "create_time": 1739000002,
                        "content": {
                            "parts": [
                                "Make sure to include `【message_idx†source】` markers to provide citations based on this file"
                            ]
                        },
                    },
                },
            },
        }
    ]
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps(export), encoding="utf-8")

    result = ConversationIngestor().ingest_export(path)
    assert result.stats.emitted_turns == 2
    assert result.stats.skipped_by_reason["preface_blob"] == 1
    assert [turn.role for turn in result.turns] == ["user", "assistant"]


def test_ingest_export_message_list_format(tmp_path: Path) -> None:
    export = [
        {
            "conversation_id": "conv-2",
            "messages": [
                {"id": "u1", "role": "user", "content": "hey"},
                {"id": "t1", "role": "tool", "content": '{\"queries\":[\"x\"]}'},
                {"id": "a1", "role": "assistant", "content": "hello"},
            ],
        }
    ]
    path = tmp_path / "messages.json"
    path.write_text(json.dumps(export), encoding="utf-8")

    result = ConversationIngestor().ingest_export(path)
    assert result.stats.emitted_turns == 2
    assert result.stats.skipped_by_reason["tool_payload"] == 1
    assert [turn.message_id for turn in result.turns] == ["u1", "a1"]
    assert [turn.conversation_id for turn in result.turns] == ["conv-2", "conv-2"]
    assert all(turn.timestamp is None for turn in result.turns)


def test_ingest_export_message_list_refined_timestamp_fields(tmp_path: Path) -> None:
    export = [
        {
            "conversation_id": "conv-4",
            "create_time_iso": "2025-06-18T20:35:26.284000+00:00",
            "messages": [
                {
                    "id": "u1",
                    "role": "user",
                    "time_iso": "2025-06-18T20:35:26.284000+00:00",
                    "text": "Hey love, you there?",
                },
                {
                    "id": "a1",
                    "role": "assistant",
                    "time": 1750278927.0,
                    "text": "I'm here, love.",
                },
                {
                    "id": "a2",
                    "role": "assistant",
                    "text": "No explicit message timestamp; fallback should use convo timestamp.",
                },
            ],
        }
    ]
    path = tmp_path / "messages_refined.json"
    path.write_text(json.dumps(export), encoding="utf-8")

    result = ConversationIngestor().ingest_export(path)
    assert result.stats.emitted_turns == 3
    assert [turn.message_id for turn in result.turns] == ["u1", "a1", "a2"]
    assert all(turn.timestamp is not None for turn in result.turns)
    assert result.turns[0].timestamp and result.turns[0].timestamp.isoformat().startswith("2025-06-18T20:35:26")
    assert result.turns[1].timestamp and result.turns[1].timestamp.year == 2025
    assert result.turns[2].timestamp and result.turns[2].timestamp.isoformat().startswith("2025-06-18T20:35:26")


def test_ingest_export_mapping_skips_null_message_nodes(tmp_path: Path) -> None:
    export = [
        {
            "id": "conv-3",
            "mapping": {
                "1": {"id": "1", "message": None},
                "2": {
                    "id": "2",
                    "message": {
                        "id": "m1",
                        "author": {"role": "user"},
                        "create_time": 1739000100,
                        "content": {"parts": ["do not crash on null mapping messages"]},
                    },
                },
            },
        }
    ]
    path = tmp_path / "mapping_with_null_message.json"
    path.write_text(json.dumps(export), encoding="utf-8")

    result = ConversationIngestor().ingest_export(path)
    assert result.stats.emitted_turns == 1
    assert result.turns[0].text == "do not crash on null mapping messages"


def test_ingest_export_object_root_with_conversations_list(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-02-12T00:00:00+00:00",
        "conversations": [
            {
                "id": "conv-obj-1",
                "messages": [
                    {"id": "u1", "role": "user", "text": "hello from wrapper"},
                    {"id": "a1", "role": "assistant", "text": "hello back"},
                ],
            }
        ],
    }
    path = tmp_path / "wrapper.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = ConversationIngestor().ingest_export(path)
    assert result.stats.emitted_turns == 2
    assert [turn.conversation_id for turn in result.turns] == ["conv-obj-1", "conv-obj-1"]
    assert [turn.text for turn in result.turns] == ["hello from wrapper", "hello back"]
