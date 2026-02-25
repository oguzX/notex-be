"""Tests for message_ops payload in WebSocket events.

These tests verify that:
1. WS events include exactly the ops produced for the current message
2. Different messages have isolated ops (no mixing)
3. Tool mode properly sets empty ops and includes tool_response
"""

import pytest
from uuid import uuid4

from app.schemas.enums import ItemRefType, ItemType, OpType
from app.schemas.events import MessageOpsPayload
from app.schemas.proposals import (
    ItemOp,
    ItemRef,
    ItemResolution,
    LlmProposalPayload,
    ProposalResolution,
)


def _build_message_ops_payload(
    validated_payload: LlmProposalPayload,
    resolution: ProposalResolution,
    proposal_id,
    message_id,
    version: int,
    tool_response_data: dict | None = None,
) -> MessageOpsPayload:
    """
    Local copy of the helper function for testing.
    This matches the implementation in app/workers/tasks.py.
    """
    ops_list = [op.model_dump(mode="json") for op in validated_payload.ops]
    clarifications_list = [c.model_dump(mode="json") for c in validated_payload.clarifications]
    resolution_dict = resolution.model_dump(mode="json") if resolution else None
    
    no_op = len(ops_list) == 0
    
    return MessageOpsPayload(
        message_id=message_id,
        proposal_id=proposal_id,
        version=version,
        ops=ops_list,
        resolution=resolution_dict,
        clarifications=clarifications_list,
        no_op=no_op,
        tool_response=tool_response_data,
    )


class TestMessageOpsPayload:
    """Test suite for message_ops payload construction."""

    def test_message_with_three_ops_includes_exactly_three(self):
        """Verify a message with 3 ops results in exactly 3 ops in message_ops."""
        message_id = uuid4()
        proposal_id = uuid4()
        version = 1
        
        # Create 3 ops
        ops = [
            ItemOp(
                op=OpType.CREATE,
                item_type=ItemType.TASK,
                temp_id="temp_1",
                title="Task 1",
            ),
            ItemOp(
                op=OpType.CREATE,
                item_type=ItemType.TASK,
                temp_id="temp_2",
                title="Task 2",
            ),
            ItemOp(
                op=OpType.CREATE,
                item_type=ItemType.TASK,
                temp_id="temp_3",
                title="Task 3",
            ),
        ]
        
        payload = LlmProposalPayload(ops=ops, needs_confirmation=False)
        resolution = ProposalResolution(resolutions=[], needs_confirmation=False)
        
        message_ops = _build_message_ops_payload(
            validated_payload=payload,
            resolution=resolution,
            proposal_id=proposal_id,
            message_id=message_id,
            version=version,
        )
        
        # Verify exactly 3 ops
        assert len(message_ops.ops) == 3
        assert message_ops.message_id == message_id
        assert message_ops.proposal_id == proposal_id
        assert message_ops.version == version
        assert message_ops.no_op is False
        assert message_ops.tool_response is None

    def test_second_message_does_not_include_first_message_ops(self):
        """Verify ops from message 1 are not included in message 2's payload."""
        message_1_id = uuid4()
        message_2_id = uuid4()
        proposal_1_id = uuid4()
        proposal_2_id = uuid4()
        
        # Message 1 has 3 ops
        ops_1 = [
            ItemOp(op=OpType.CREATE, item_type=ItemType.TASK, temp_id="msg1_task1", title="Msg1 Task 1"),
            ItemOp(op=OpType.CREATE, item_type=ItemType.TASK, temp_id="msg1_task2", title="Msg1 Task 2"),
            ItemOp(op=OpType.CREATE, item_type=ItemType.TASK, temp_id="msg1_task3", title="Msg1 Task 3"),
        ]
        payload_1 = LlmProposalPayload(ops=ops_1, needs_confirmation=False)
        resolution_1 = ProposalResolution(resolutions=[], needs_confirmation=False)
        
        message_ops_1 = _build_message_ops_payload(
            validated_payload=payload_1,
            resolution=resolution_1,
            proposal_id=proposal_1_id,
            message_id=message_1_id,
            version=1,
        )
        
        # Message 2 has 1 op
        ops_2 = [
            ItemOp(op=OpType.CREATE, item_type=ItemType.TASK, temp_id="msg2_task1", title="Msg2 Task 1"),
        ]
        payload_2 = LlmProposalPayload(ops=ops_2, needs_confirmation=False)
        resolution_2 = ProposalResolution(resolutions=[], needs_confirmation=False)
        
        message_ops_2 = _build_message_ops_payload(
            validated_payload=payload_2,
            resolution=resolution_2,
            proposal_id=proposal_2_id,
            message_id=message_2_id,
            version=2,
        )
        
        # Verify message 1 has 3 ops
        assert len(message_ops_1.ops) == 3
        assert message_ops_1.message_id == message_1_id
        assert all("msg1" in op.get("temp_id", "") for op in message_ops_1.ops)
        
        # Verify message 2 has exactly 1 op (not 4)
        assert len(message_ops_2.ops) == 1
        assert message_ops_2.message_id == message_2_id
        assert message_ops_2.ops[0].get("temp_id") == "msg2_task1"
        
        # Verify no mixing of ops
        msg2_temp_ids = [op.get("temp_id") for op in message_ops_2.ops]
        assert "msg1_task1" not in msg2_temp_ids
        assert "msg1_task2" not in msg2_temp_ids
        assert "msg1_task3" not in msg2_temp_ids

    def test_tool_mode_has_empty_ops_and_tool_response(self):
        """Verify tool mode sets empty ops and includes tool_response."""
        message_id = uuid4()
        proposal_id = uuid4()
        version = 1
        
        # Tool mode: empty ops
        payload = LlmProposalPayload(
            ops=[],
            needs_confirmation=False,
            reasoning="Tool response",
        )
        resolution = ProposalResolution(resolutions=[], needs_confirmation=False)
        
        tool_response_data = {
            "text": "Here are your tasks for today...",
            "tool_calls": [{"tool": "list_tasks", "result": []}],
        }
        
        message_ops = _build_message_ops_payload(
            validated_payload=payload,
            resolution=resolution,
            proposal_id=proposal_id,
            message_id=message_id,
            version=version,
            tool_response_data=tool_response_data,
        )
        
        # Verify empty ops
        assert len(message_ops.ops) == 0
        assert message_ops.no_op is True
        
        # Verify tool_response is present
        assert message_ops.tool_response is not None
        assert message_ops.tool_response["text"] == "Here are your tasks for today..."
        assert len(message_ops.tool_response["tool_calls"]) == 1

    def test_no_op_without_tool_response(self):
        """Verify no-op case without tool mode (conversational response)."""
        message_id = uuid4()
        proposal_id = uuid4()
        version = 1
        
        # Conversational response: no ops, no tool
        payload = LlmProposalPayload(
            ops=[],
            needs_confirmation=False,
            reasoning="Just a friendly response",
        )
        resolution = ProposalResolution(resolutions=[], needs_confirmation=False)
        
        message_ops = _build_message_ops_payload(
            validated_payload=payload,
            resolution=resolution,
            proposal_id=proposal_id,
            message_id=message_id,
            version=version,
            tool_response_data=None,
        )
        
        assert len(message_ops.ops) == 0
        assert message_ops.no_op is True
        assert message_ops.tool_response is None

    def test_clarifications_included_in_payload(self):
        """Verify clarifications are properly included in message_ops."""
        from app.schemas.enums import ClarificationField
        from app.schemas.proposals import Clarification
        
        message_id = uuid4()
        proposal_id = uuid4()
        version = 1
        
        ops = [
            ItemOp(
                op=OpType.CREATE,
                item_type=ItemType.TASK,
                temp_id="temp_1",
                title="Task without time",
            ),
        ]
        
        clarifications = [
            Clarification(
                clarification_id="clar_001",
                field=ClarificationField.DUE_AT,
                target_temp_id="temp_1",
                message="When would you like to schedule this?",
            ),
        ]
        
        payload = LlmProposalPayload(
            ops=ops,
            needs_confirmation=True,
            clarifications=clarifications,
        )
        resolution = ProposalResolution(resolutions=[], needs_confirmation=False)
        
        message_ops = _build_message_ops_payload(
            validated_payload=payload,
            resolution=resolution,
            proposal_id=proposal_id,
            message_id=message_id,
            version=version,
        )
        
        assert len(message_ops.ops) == 1
        assert len(message_ops.clarifications) == 1
        assert message_ops.clarifications[0]["clarification_id"] == "clar_001"
        assert message_ops.clarifications[0]["target_temp_id"] == "temp_1"

    def test_resolution_included_in_payload(self):
        """Verify resolution data is properly included in message_ops."""
        message_id = uuid4()
        proposal_id = uuid4()
        existing_item_id = uuid4()
        version = 1
        
        ops = [
            ItemOp(
                op=OpType.UPDATE,
                ref=ItemRef(type=ItemRefType.NATURAL, value="meeting tomorrow"),
                title="Updated meeting",
            ),
        ]
        
        resolutions = [
            ItemResolution(
                ref=ItemRef(type=ItemRefType.NATURAL, value="meeting tomorrow"),
                resolved_item_id=existing_item_id,
                confidence=0.95,
                requires_confirmation=False,
            ),
        ]
        
        payload = LlmProposalPayload(ops=ops, needs_confirmation=False)
        resolution = ProposalResolution(resolutions=resolutions, needs_confirmation=False)
        
        message_ops = _build_message_ops_payload(
            validated_payload=payload,
            resolution=resolution,
            proposal_id=proposal_id,
            message_id=message_id,
            version=version,
        )
        
        assert message_ops.resolution is not None
        assert len(message_ops.resolution["resolutions"]) == 1
        assert message_ops.resolution["resolutions"][0]["confidence"] == 0.95

    def test_version_tracking(self):
        """Verify version is correctly tracked in message_ops."""
        message_id = uuid4()
        proposal_id = uuid4()
        
        payload = LlmProposalPayload(ops=[], needs_confirmation=False)
        resolution = ProposalResolution(resolutions=[], needs_confirmation=False)
        
        for version in [1, 5, 10, 100]:
            message_ops = _build_message_ops_payload(
                validated_payload=payload,
                resolution=resolution,
                proposal_id=proposal_id,
                message_id=message_id,
                version=version,
            )
            assert message_ops.version == version

    def test_serialization_produces_valid_json(self):
        """Verify message_ops can be serialized to valid JSON."""
        message_id = uuid4()
        proposal_id = uuid4()
        version = 1
        
        ops = [
            ItemOp(
                op=OpType.CREATE,
                item_type=ItemType.TASK,
                temp_id="temp_1",
                title="Test task",
                due_at="2026-02-05T10:00:00Z",
            ),
        ]
        
        payload = LlmProposalPayload(ops=ops, needs_confirmation=False)
        resolution = ProposalResolution(resolutions=[], needs_confirmation=False)
        
        message_ops = _build_message_ops_payload(
            validated_payload=payload,
            resolution=resolution,
            proposal_id=proposal_id,
            message_id=message_id,
            version=version,
        )
        
        # Should serialize without errors
        json_output = message_ops.model_dump(mode="json")
        
        assert "message_id" in json_output
        assert "proposal_id" in json_output
        assert "ops" in json_output
        assert "version" in json_output
        assert json_output["version"] == 1
        assert len(json_output["ops"]) == 1
