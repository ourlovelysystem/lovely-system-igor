import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


conversation_path = Path(__file__).parents[1] / "src" / "conversation" / "app.py"
spec = importlib.util.spec_from_file_location("igor_conversation", conversation_path)
assert spec and spec.loader
conversation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conversation)


def event(method, path, body=None, owner="operator-1"):
    return {
        "requestContext": {
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": {"sub": owner}}},
        },
        "rawPath": path,
        "body": json.dumps(body or {}),
    }


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.table = Mock()
        self.bedrock = Mock()
        self.lambda_client = Mock()

    def call(self, method, path, body=None, owner="operator-1"):
        return conversation.handle(
            event(method, path, body, owner),
            table=self.table,
            bedrock=self.bedrock,
            lambda_client=self.lambda_client,
            control_function_name="igor-control",
            model_id="global.openai.gpt-5.6-terra",
        )

    def test_create_conversation_records_owner(self):
        with patch.object(conversation, "now_iso", return_value="2026-09-05T12:00:00+00:00"):
            result = self.call("POST", "/conversations")
        self.assertEqual(201, result["statusCode"])
        item = self.table.put_item.call_args.kwargs["Item"]
        self.assertEqual("operator-1", item["owner_id"])
        self.assertEqual("META", item["record_key"])

    def test_missing_identity_is_rejected(self):
        result = conversation.handle(
            {"requestContext": {"http": {"method": "POST"}}, "rawPath": "/conversations"},
            table=self.table,
            bedrock=self.bedrock,
            lambda_client=self.lambda_client,
            control_function_name="igor-control",
            model_id="model",
        )
        self.assertEqual(401, result["statusCode"])

    def test_other_operators_conversation_is_hidden(self):
        self.table.get_item.return_value = {
            "Item": {"conversation_id": "abc", "record_key": "META", "owner_id": "someone-else"}
        }
        result = self.call("GET", "/conversations/abc")
        self.assertEqual(404, result["statusCode"])

    def test_general_conversation_returns_model_text_without_tool(self):
        self.table.query.return_value = {
            "Items": [
                {
                    "role": "user",
                    "content_json": '[{"text":"What are you?"}]',
                }
            ]
        }
        self.bedrock.converse.return_value = {
            "stopReason": "end_turn",
            "output": {"message": {"role": "assistant", "content": [{"text": "I am Igor."}]}},
        }
        result = conversation.converse(
            table=self.table,
            bedrock=self.bedrock,
            lambda_client=self.lambda_client,
            control_function_name="igor-control",
            model_id="model",
            conversation_id="abc",
        )
        self.assertEqual("I am Igor.", result["text"])
        self.assertEqual([], result["tool_events"])
        self.lambda_client.invoke.assert_not_called()

    def test_binary_reasoning_content_survives_storage_round_trip(self):
        content = [
            {"reasoningContent": {"redactedContent": b"\x00\xffprivate-reasoning"}},
            {"text": "The visible answer."},
        ]

        conversation._put_message(
            self.table,
            conversation_id="abc",
            role="assistant",
            content=content,
        )

        stored_item = self.table.put_item.call_args.kwargs["Item"]
        self.table.query.return_value = {"Items": [stored_item]}
        loaded = conversation._load_messages(self.table, "abc")

        self.assertEqual(content, loaded[0]["content"])
        self.assertIsInstance(
            loaded[0]["content"][0]["reasoningContent"]["redactedContent"],
            bytes,
        )

    def test_general_task_tool_queues_job_and_returns_truthful_followup(self):
        self.table.query.return_value = {
            "Items": [
                {
                    "role": "user",
                    "content_json": '[{"text":"Build a greeting service."}]',
                }
            ]
        }
        self.bedrock.converse.side_effect = [
            {
                "stopReason": "tool_use",
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "tool-1",
                                    "name": "execute_task",
                                    "input": {"objective": "Build a greeting service."},
                                }
                            }
                        ],
                    }
                },
            },
            {
                "stopReason": "end_turn",
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [{"text": "Job job-123 is queued; it is not complete."}],
                    }
                },
            },
        ]
        control_response = {
            "statusCode": 202,
            "body": json.dumps({"job_id": "job-123", "status": "QUEUED"}),
        }
        self.lambda_client.invoke.return_value = {
            "StatusCode": 200,
            "Payload": io.BytesIO(json.dumps(control_response).encode("utf-8")),
        }

        result = conversation.converse(
            table=self.table,
            bedrock=self.bedrock,
            lambda_client=self.lambda_client,
            control_function_name="igor-control",
            model_id="model",
            conversation_id="abc",
        )

        self.assertEqual("Job job-123 is queued; it is not complete.", result["text"])
        self.assertEqual("execute_task", result["tool_events"][0]["name"])
        self.assertEqual("QUEUED", result["tool_events"][0]["result"]["status"])
        invoked = json.loads(self.lambda_client.invoke.call_args.kwargs["Payload"])
        self.assertEqual("/jobs", invoked["rawPath"])
        self.assertEqual(
            "Build a greeting service.",
            json.loads(invoked["body"])["idea"],
        )


if __name__ == "__main__":
    unittest.main()
