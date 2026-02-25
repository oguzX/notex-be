"""JSON utilities."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for special types."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        return super().default(obj)


def dumps(obj: Any, **kwargs: Any) -> str:
    """Dump object to JSON string with custom encoder."""
    return json.dumps(obj, cls=CustomJSONEncoder, **kwargs)


def loads(s: str) -> Any:
    """Load JSON string to object."""
    return json.loads(s)
