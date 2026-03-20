import json
from dataclasses import dataclass
from functools import lru_cache

import fastjsonschema
import jsonschema
from jsonschema.validators import validator_for

from django.conf import settings


@dataclass(frozen=True)
class EventValidationProblem:
    absolute_path: tuple = ()
    absolute_schema_path: tuple = ()
    display_path: str = "$"
    message: str = ""
    instance: object = None
    schema: object = None
    validator: str | None = None
    validator_value: object = None

    def as_validation_error_message(self):
        return f"{self.display_path}: {self.message}"


@lru_cache(maxsize=1)
def _get_event_schema():
    schema_filename = settings.BASE_DIR / "api/event.schema.json"
    with open(schema_filename, "r") as f:
        return json.loads(f.read())


@lru_cache(maxsize=1)
def _get_fast_event_validator():
    # Use fastjsonschema for the hot path. When it rejects an event, we fall back to jsonschema to get the structured
    # error details that drive normalization.
    return fastjsonschema.compile(
        _get_event_schema(),
        use_formats=False,
        use_default=False,
        detailed_exceptions=False,
    )


@lru_cache(maxsize=1)
def _get_jsonschema_validator():
    schema = _get_event_schema()
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)
    return validator_class(schema)


def _format_absolute_path(absolute_path):
    if not absolute_path:
        return "$"

    result = "$"
    for part in absolute_path:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += f".{part}"
    return result


def get_event_validation_problem(data):
    data_to_validate = {k: v for k, v in data.items() if k != "_meta"}

    try:
        _get_fast_event_validator()(data_to_validate)
        return None
    except fastjsonschema.exceptions.JsonSchemaValueException:
        best = jsonschema.exceptions.best_match(_get_jsonschema_validator().iter_errors(data_to_validate))
        return EventValidationProblem(
            absolute_path=tuple(best.absolute_path),
            absolute_schema_path=tuple(best.absolute_schema_path),
            display_path=_format_absolute_path(tuple(best.absolute_path)),
            message=best.message,
            instance=best.instance,
            schema=best.schema,
            validator=best.validator,
            validator_value=best.validator_value,
        )
