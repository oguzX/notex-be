"""Note-specific schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.items import ItemResponse


# Query params for list notes endpoint
NoteListStatus = Literal["all", "active", "archived"]


class ConvertNoteToTaskRequest(BaseModel):
    """Request body for converting a note to a task."""

    due_date: datetime


class ConvertNoteToTaskResponse(BaseModel):
    """Response for note-to-task conversion.

    If conflict=False, `item` contains the converted task.
    If conflict=True, `conflicting_task` and `suggestions` are returned.
    """

    conflict: bool
    item: ItemResponse | None = None
    conflicting_task: ItemResponse | None = None
    suggestions: list[str] | None = None
