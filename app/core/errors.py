"""Custom exceptions and error handlers."""

from typing import Any

import structlog
from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class ErrorResponse(BaseModel):
    """Standard error response schema."""

    error: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class NotexException(Exception):
    """Base exception for application errors."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: dict[str, Any] | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class ConversationNotFoundError(NotexException):
    """Conversation not found."""

    def __init__(self, conversation_id: str):
        super().__init__(
            message=f"Conversation {conversation_id} not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ProposalNotFoundError(NotexException):
    """Proposal not found."""

    def __init__(self, proposal_id: str):
        super().__init__(
            message=f"Proposal {proposal_id} not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class TaskNotFoundError(NotexException):
    """Task not found."""

    def __init__(self, task_id: str):
        super().__init__(
            message=f"Task {task_id} not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ItemNotFoundError(NotexException):
    """Item not found."""

    def __init__(self, item_id: str):
        super().__init__(
            message=f"Item {item_id} not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class StaleProposalError(NotexException):
    """Proposal is stale and cannot be applied."""

    def __init__(self, proposal_id: str, current_version: int, proposal_version: int):
        super().__init__(
            message=f"Proposal {proposal_id} is stale",
            status_code=status.HTTP_409_CONFLICT,
            details={
                "current_version": current_version,
                "proposal_version": proposal_version,
            },
        )


class ProposalNotReadyError(NotexException):
    """Proposal is not ready to be applied."""

    def __init__(self, proposal_id: str, current_status: str):
        super().__init__(
            message=f"Proposal {proposal_id} is not ready (status: {current_status})",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class ClarificationNotFoundError(NotexException):
    """Clarification not found in proposal."""

    def __init__(self, clarification_id: str, proposal_id: str):
        super().__init__(
            message=f"Clarification {clarification_id} not found in proposal {proposal_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class InvalidConfirmActionError(NotexException):
    """Invalid confirmation action for the given clarification type."""

    def __init__(self, action: str, clarification_field: str):
        super().__init__(
            message=f"Action '{action}' is not valid for clarification field '{clarification_field}'",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class ProposalAlreadyProcessedError(NotexException):
    """Proposal has already been applied or canceled."""

    def __init__(self, proposal_id: str, current_status: str):
        super().__init__(
            message=f"Proposal {proposal_id} has already been processed (status: {current_status})",
            status_code=status.HTTP_409_CONFLICT,
            details={"current_status": current_status},
        )


class NoApprovableProposalError(NotexException):
    """No actionable proposal found for approval."""

    def __init__(self, conversation_id: str):
        super().__init__(
            message=f"No approvable proposal found for conversation {conversation_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


async def notex_exception_handler(request: Request, exc: NotexException) -> JSONResponse:
    """Handle NotexException instances."""
    request_id = getattr(request.state, "request_id", None)
    
    logger.error(
        "notex_exception",
        error=exc.__class__.__name__,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details,
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.__class__.__name__,
            message=exc.message,
            details=exc.details,
            request_id=request_id,
        ).model_dump(exclude_none=True),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTPException instances."""
    request_id = getattr(request.state, "request_id", None)
    
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error="HTTPException",
            message=exc.detail,
            request_id=request_id,
        ).model_dump(exclude_none=True),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle validation errors."""
    request_id = getattr(request.state, "request_id", None)
    
    logger.warning(
        "validation_error",
        errors=exc.errors(),
    )
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            error="ValidationError",
            message="Request validation failed",
            details={"errors": exc.errors()},
            request_id=request_id,
        ).model_dump(exclude_none=True),
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    request_id = getattr(request.state, "request_id", None)
    
    logger.exception(
        "unhandled_exception",
        exception=exc.__class__.__name__,
        message=str(exc),
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="InternalServerError",
            message="An unexpected error occurred",
            request_id=request_id,
        ).model_dump(exclude_none=True),
    )
