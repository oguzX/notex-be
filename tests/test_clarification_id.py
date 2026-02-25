"""Tests for clarification_id auto-generation."""

import pytest

from app.schemas.proposals import (
    Clarification,
    LlmProposalPayload,
    TaskOp,
    TaskRef,
    TimeSuggestion,
)
from app.schemas.enums import ClarificationField, OpType, TaskRefType


class TestClarificationIdGeneration:
    """Test that clarification_id is auto-generated when missing."""

    def test_clarification_auto_generates_id(self):
        """Clarification should auto-generate clarification_id if not provided."""
        clarification = Clarification(
            field=ClarificationField.DUE_AT,
            message="When would you like to schedule this?",
        )
        
        assert clarification.clarification_id is not None
        assert len(clarification.clarification_id) > 0
        assert clarification.clarification_id.startswith("clr_")

    def test_clarification_uses_provided_id(self):
        """Clarification should use provided clarification_id if given."""
        clarification = Clarification(
            clarification_id="my-custom-id",
            field=ClarificationField.DUE_AT,
            message="When would you like to schedule this?",
        )
        
        assert clarification.clarification_id == "my-custom-id"

    def test_clarification_generates_unique_ids(self):
        """Each clarification should have a unique auto-generated ID."""
        clarification1 = Clarification(
            field=ClarificationField.DUE_AT,
            message="Message 1",
        )
        clarification2 = Clarification(
            field=ClarificationField.DUE_AT,
            message="Message 2",
        )
        
        assert clarification1.clarification_id != clarification2.clarification_id


class TestLlmPayloadMissingClarificationId:
    """Test LLM payload normalization when clarification_id is missing."""

    def test_llm_payload_missing_clarification_id_is_repaired_via_schema(self):
        """LlmProposalPayload should auto-generate clarification_id via schema defaults."""
        # Simulate LLM response with missing clarification_id
        payload_data = {
            "ops": [
                {
                    "op": "create",
                    "temp_id": "task_1",
                    "title": "New task",
                }
            ],
            "clarifications": [
                {
                    "field": "due_at",
                    "op_ref": {"type": "temp_id", "value": "task_1"},
                    "message": "When would you like to schedule this task?",
                    "suggestions": [
                        {
                            "due_at": "2026-01-29T19:00:00Z",
                            "timezone": "UTC",
                            "label": "This evening at 7 PM",
                            "confidence": 0.7,
                        }
                    ],
                }
            ],
            "needs_confirmation": True,
        }
        
        # This should NOT raise ValidationError
        payload = LlmProposalPayload(**payload_data)
        
        assert payload.needs_confirmation is True
        assert len(payload.clarifications) == 1
        assert payload.clarifications[0].clarification_id is not None
        assert len(payload.clarifications[0].clarification_id) > 0
        assert payload.clarifications[0].clarification_id.startswith("clr_")

    def test_multiple_clarifications_get_unique_ids(self):
        """Multiple clarifications should each get unique auto-generated IDs."""
        payload_data = {
            "ops": [
                {"op": "create", "temp_id": "task_1", "title": "Task 1"},
                {"op": "create", "temp_id": "task_2", "title": "Task 2"},
            ],
            "clarifications": [
                {
                    "field": "due_at",
                    "op_ref": {"type": "temp_id", "value": "task_1"},
                    "message": "When for task 1?",
                    "suggestions": [],
                },
                {
                    "field": "due_at",
                    "op_ref": {"type": "temp_id", "value": "task_2"},
                    "message": "When for task 2?",
                    "suggestions": [],
                },
            ],
            "needs_confirmation": True,
        }
        
        payload = LlmProposalPayload(**payload_data)
        
        assert len(payload.clarifications) == 2
        assert payload.clarifications[0].clarification_id is not None
        assert payload.clarifications[1].clarification_id is not None
        assert payload.clarifications[0].clarification_id != payload.clarifications[1].clarification_id


class TestProviderNormalization:
    """Test the _normalize_clarifications function used in LLM providers."""

    def test_normalize_adds_missing_clarification_id(self):
        """Normalization should add clarification_id to clarifications missing it."""
        from app.llm.openai_provider import _normalize_clarifications
        
        payload_data = {
            "ops": [{"op": "create", "temp_id": "task_1", "title": "Task"}],
            "clarifications": [
                {"field": "due_at", "message": "When?", "suggestions": []},
                {"field": "due_at", "message": "What time?", "suggestions": []},
            ],
        }
        
        normalized = _normalize_clarifications(payload_data)
        
        assert "clarification_id" in normalized["clarifications"][0]
        assert "clarification_id" in normalized["clarifications"][1]
        assert normalized["clarifications"][0]["clarification_id"].startswith("clr_")
        assert normalized["clarifications"][1]["clarification_id"].startswith("clr_")
        # Each should be unique
        assert normalized["clarifications"][0]["clarification_id"] != normalized["clarifications"][1]["clarification_id"]

    def test_normalize_preserves_existing_clarification_id(self):
        """Normalization should not overwrite existing clarification_id."""
        from app.llm.openai_provider import _normalize_clarifications
        
        payload_data = {
            "ops": [],
            "clarifications": [
                {"clarification_id": "existing-id", "field": "due_at", "message": "When?"},
            ],
        }
        
        normalized = _normalize_clarifications(payload_data)
        
        assert normalized["clarifications"][0]["clarification_id"] == "existing-id"

    def test_normalize_handles_empty_clarifications(self):
        """Normalization should handle empty clarifications list."""
        from app.llm.openai_provider import _normalize_clarifications
        
        payload_data = {"ops": [], "clarifications": []}
        normalized = _normalize_clarifications(payload_data)
        assert normalized["clarifications"] == []

    def test_normalize_handles_missing_clarifications(self):
        """Normalization should handle missing clarifications key."""
        from app.llm.openai_provider import _normalize_clarifications
        
        payload_data = {"ops": []}
        normalized = _normalize_clarifications(payload_data)
        assert "clarifications" not in normalized or normalized.get("clarifications") == []

    def test_gemini_normalize_adds_missing_clarification_id(self):
        """Gemini provider normalization should also add clarification_id."""
        from app.llm.gemini_provider import _normalize_clarifications
        
        payload_data = {
            "ops": [],
            "clarifications": [
                {"field": "due_at", "message": "When?", "suggestions": []},
            ],
        }
        
        normalized = _normalize_clarifications(payload_data)
        
        assert "clarification_id" in normalized["clarifications"][0]
        assert normalized["clarifications"][0]["clarification_id"].startswith("clr_")


class TestEndToEndClarificationFlow:
    """Test the full flow from LLM payload to validated model."""

    def test_full_payload_validation_with_missing_clarification_id(self):
        """Full flow: LLM returns payload without clarification_id, should be repaired."""
        from app.llm.openai_provider import _normalize_clarifications
        
        # Simulated LLM response (missing clarification_id)
        llm_response = {
            "ops": [
                {
                    "op": "create",
                    "temp_id": "task_1",
                    "title": "Buy groceries",
                    "description": "Get milk, eggs, bread",
                }
            ],
            "needs_confirmation": True,
            "reasoning": "Created task but need time confirmation",
            "clarifications": [
                {
                    "field": "due_at",
                    "op_ref": {"type": "temp_id", "value": "task_1"},
                    "message": "When would you like to buy groceries?",
                    "suggestions": [
                        {
                            "due_at": "2026-01-29T18:00:00Z",
                            "timezone": "UTC",
                            "label": "This evening at 6 PM",
                            "confidence": 0.8,
                        }
                    ],
                }
            ],
        }
        
        # Step 1: Normalize (like LLM provider does)
        normalized = _normalize_clarifications(llm_response)
        
        # Step 2: Validate with Pydantic (should NOT raise)
        payload = LlmProposalPayload(**normalized)
        
        # Assertions
        assert payload.needs_confirmation is True
        assert len(payload.ops) == 1
        assert payload.ops[0].op == OpType.CREATE
        assert payload.ops[0].temp_id == "task_1"
        
        assert len(payload.clarifications) == 1
        clarification = payload.clarifications[0]
        assert clarification.clarification_id is not None
        assert clarification.clarification_id.startswith("clr_")
        assert clarification.field == ClarificationField.DUE_AT
        assert clarification.message == "When would you like to buy groceries?"
        assert len(clarification.suggestions) == 1
        assert clarification.suggestions[0].confidence == 0.8
