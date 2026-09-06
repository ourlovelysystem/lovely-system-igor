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
        self.s3 = Mock()

    def call(self, method, path, body=None, owner="operator-1"):
        return conversation.handle(
            event(method, path, body, owner),
            table=self.table,
            bedrock=self.bedrock,
            lambda_client=self.lambda_client,
            control_function_name="igor-control",
            model_id="global.openai.gpt-5.6-terra",
            s3=self.s3,
            attachments_bucket="igor-evidence",
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

    def test_old_s3_location_media_block_is_removed_from_model_history(self):
        self.table.query.return_value = {
            "Items": [
                {
                    "role": "user",
                    "content_json": json.dumps(
                        [
                            {"text": "Inspect it"},
                            {
                                "image": {
                                    "format": "png",
                                    "source": {"s3Location": {"uri": "s3://igor/old.png"}},
                                }
                            },
                        ]
                    ),
                }
            ]
        }

        loaded = conversation._load_messages(self.table, "abc")

        self.assertEqual([{"text": "Inspect it"}], loaded[0]["content"])

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
        self.assertEqual("abc", json.loads(invoked["body"])["conversation_id"])

    def test_initiates_multipart_upload_without_sending_file_through_lambda(self):
        self.table.get_item.return_value = {
            "Item": {"conversation_id": "abc", "record_key": "META", "owner_id": "operator-1"}
        }
        self.s3.create_multipart_upload.return_value = {"UploadId": "upload-123"}

        result = self.call(
            "POST",
            "/conversations/abc/attachments",
            {"filename": "large log.txt", "content_type": "text/plain", "size": 6 * 1024**3},
        )

        self.assertEqual(201, result["statusCode"])
        body = json.loads(result["body"])
        self.assertGreater(body["part_count"], 1)
        stored = self.table.put_item.call_args.kwargs["Item"]
        self.assertEqual("UPLOADING", stored["status"])
        self.assertEqual(6 * 1024**3, stored["size"])
        self.assertTrue(stored["s3_key"].startswith("attachments/operator-1/abc/"))

    def test_small_image_is_loaded_from_private_s3_for_bedrock(self):
        attachment = {
            "attachment_id": "image-1",
            "filename": "screen.png",
            "content_type": "image/png",
            "size": 1000,
            "s3_uri": "s3://igor/attachments/operator/abc/image-1/screen.png",
            "s3_key": "attachments/operator/abc/image-1/screen.png",
        }
        self.s3.get_object.return_value = {"Body": io.BytesIO(b"\x89PNG\r\n\x1a\nimage-data")}
        attachment["size"] = len(b"\x89PNG\r\n\x1a\nimage-data")
        content = conversation._attachment_content("What is wrong here?", [attachment])
        self.assertFalse(any("image" in block for block in content))
        blocks, routing = conversation._model_attachment_blocks(self.s3, "igor", [attachment])
        self.assertEqual("conversation-model", routing[0]["component"])
        image = blocks[0]["image"]
        self.assertEqual("png", image["format"])
        self.assertEqual(b"\x89PNG\r\n\x1a\nimage-data", image["source"]["bytes"])
        self.s3.get_object.assert_called_once_with(
            Bucket="igor", Key=attachment["s3_key"]
        )

    def test_pdf_is_loaded_from_private_s3_for_bedrock(self):
        attachment = {
            "attachment_id": "pdf-1",
            "filename": "inspection report.pdf",
            "content_type": "application/pdf",
            "size": 5000,
            "s3_uri": "s3://igor/attachments/operator/abc/pdf-1/report.pdf",
            "s3_key": "attachments/operator/abc/pdf-1/report.pdf",
        }
        blocks, routing = conversation._model_attachment_blocks(self.s3, "igor", [attachment])
        self.assertEqual([], blocks)
        self.assertEqual("execution-worker", routing[0]["component"])
        self.assertIn("not a direct image", routing[0]["reason"])
        self.s3.get_object.assert_not_called()

    def test_gif89a_is_accepted_as_a_valid_common_image_format(self):
        attachment = {"filename": "animation.gif", "content_type": "image/gif", "size": 6, "s3_key": "attachments/x"}
        self.s3.get_object.return_value = {"Body": io.BytesIO(b"GIF89a")}
        blocks, routing = conversation._model_attachment_blocks(self.s3, "igor", [attachment])
        self.assertEqual("conversation-model", routing[0]["component"])
        self.assertEqual("gif", blocks[0]["image"]["format"])

    def test_mismatched_image_signature_is_routed_to_worker_without_model_bytes(self):
        attachment = {"filename": "renamed.png", "content_type": "image/png", "size": 3, "s3_key": "attachments/x"}
        self.s3.get_object.return_value = {"Body": io.BytesIO(b"bad")}
        blocks, routing = conversation._model_attachment_blocks(self.s3, "igor", [attachment])
        self.assertEqual([], blocks)
        self.assertEqual("execution-worker", routing[0]["component"])
        self.assertIn("corrupt", routing[0]["reason"])

    def test_completes_uploaded_parts_and_verifies_total_size(self):
        metadata = {"conversation_id": "abc", "record_key": "META", "owner_id": "operator-1"}
        attachment = {
            "conversation_id": "abc",
            "record_key": "ATTACH#file-1",
            "attachment_id": "file-1",
            "owner_id": "operator-1",
            "filename": "large.zip",
            "content_type": "application/zip",
            "size": 1024,
            "s3_key": "attachments/operator-1/abc/file-1/large.zip",
            "upload_id": "upload-1",
            "part_count": 1,
            "status": "UPLOADING",
        }
        self.table.get_item.side_effect = [{"Item": metadata}, {"Item": attachment}]
        self.s3.head_object.return_value = {"ContentLength": 1024}

        result = self.call(
            "POST",
            "/conversations/abc/attachments/file-1/complete",
            {"parts": [{"part_number": 1, "etag": '"etag-1"'}]},
        )

        self.assertEqual(200, result["statusCode"])
        self.s3.complete_multipart_upload.assert_called_once()
        update = self.table.update_item.call_args.kwargs
        self.assertEqual("READY", update["ExpressionAttributeValues"][":ready"])

    def test_large_file_stays_in_s3_for_worker_inspection(self):
        attachment = {
            "attachment_id": "large-1",
            "filename": "archive.bin",
            "content_type": "application/octet-stream",
            "size": 2 * 1024**3,
            "s3_uri": "s3://igor/attachments/operator/abc/large-1/archive.bin",
            "s3_key": "attachments/operator/abc/large-1/archive.bin",
        }
        content = conversation._attachment_content("Inspect this", [attachment])
        self.assertFalse(any("image" in block or "document" in block for block in content))
        self.assertIn(attachment["s3_uri"], content[1]["text"])
        blocks, routing = conversation._model_attachment_blocks(self.s3, "igor", [attachment])
        self.assertEqual([], blocks)
        self.assertEqual("execution-worker", routing[0]["component"])
        self.s3.get_object.assert_not_called()


if __name__ == "__main__":
    unittest.main()

class UploadEnhancementTests(ConversationTests):
    def test_small_file_uses_one_direct_put_and_verifies_before_ready(self):
        self.table.get_item.return_value = {"Item": {"conversation_id": "abc", "record_key": "META", "owner_id": "operator-1"}}
        self.s3.generate_presigned_url.return_value = "https://s3.example/direct"
        result = self.call("POST", "/conversations/abc/attachments", {"filename": "note.txt", "content_type": "text/plain", "size": 32 * 1024**2})
        body = json.loads(result["body"])
        self.assertEqual(201, result["statusCode"])
        self.assertEqual("direct", body["upload_mode"])
        self.assertEqual("put_object", self.s3.generate_presigned_url.call_args.args[0])
        self.s3.create_multipart_upload.assert_not_called()
        stored = self.table.put_item.call_args.kwargs["Item"]
        self.assertIn("preparing_started_at", stored["phase_timings"])

    def test_direct_completion_heads_object_without_multipart_completion(self):
        metadata = {"conversation_id": "abc", "record_key": "META", "owner_id": "operator-1"}
        attachment = {"conversation_id": "abc", "record_key": "ATTACH#file-1", "attachment_id": "file-1", "owner_id": "operator-1", "filename": "note.txt", "content_type": "text/plain", "size": 7, "s3_key": "attachments/x", "upload_mode": "direct", "status": "UPLOADING"}
        self.table.get_item.side_effect = [{"Item": metadata}, {"Item": attachment}]
        self.s3.head_object.return_value = {"ContentLength": 7}
        result = self.call("POST", "/conversations/abc/attachments/file-1/complete", {"parts": []})
        self.assertEqual(200, result["statusCode"])
        self.s3.complete_multipart_upload.assert_not_called()
        self.s3.head_object.assert_called_once()
        updates = self.table.update_item.call_args_list
        self.assertIn("verifying_started_at", updates[0].kwargs["UpdateExpression"])
        self.assertIn("verifying_completed_at", updates[1].kwargs["UpdateExpression"])

    def test_adaptive_parts_and_initial_url_batch_are_bounded(self):
        self.table.get_item.return_value = {"Item": {"conversation_id": "abc", "record_key": "META", "owner_id": "operator-1"}}
        self.s3.create_multipart_upload.return_value = {"UploadId": "upload-123"}
        self.s3.generate_presigned_url.return_value = "https://s3.example/part"
        result = self.call("POST", "/conversations/abc/attachments", {"filename": "medium.bin", "content_type": "application/octet-stream", "size": 512 * 1024**2})
        body = json.loads(result["body"])
        self.assertEqual("multipart", body["upload_mode"])
        self.assertGreaterEqual(body["part_count"], 4)
        self.assertLessEqual(len(body["part_urls"]), conversation.SIGNED_URL_BATCH_SIZE)
        self.assertLessEqual(body["part_count"], 10_000)

    def test_cancel_aborts_multipart_and_records_terminal_state(self):
        metadata = {"conversation_id": "abc", "record_key": "META", "owner_id": "operator-1"}
        attachment = {"conversation_id": "abc", "record_key": "ATTACH#file-1", "owner_id": "operator-1", "status": "UPLOADING", "upload_mode": "multipart", "upload_id": "upload-1", "s3_key": "attachments/x"}
        self.table.get_item.side_effect = [{"Item": metadata}, {"Item": attachment}]
        result = self.call("DELETE", "/conversations/abc/attachments/file-1", {})
        self.assertEqual(200, result["statusCode"])
        self.s3.abort_multipart_upload.assert_called_once()
        self.assertEqual("CANCELLED", self.table.update_item.call_args.kwargs["ExpressionAttributeValues"][":cancelled"])
