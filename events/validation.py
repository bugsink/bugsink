import json
from dataclasses import dataclass
from functools import lru_cache

import fastjsonschema
import jsonschema

from django.conf import settings


@dataclass(frozen=True)
class EventValidationProblem:
    path: str
    message: str
    validator: str | None = None
    validator_value: object = None
    absolute_path: tuple = ()

    def as_validation_error_message(self):
        return f"{self.path}: {self.message}"


@lru_cache(maxsize=1)
def _get_event_schema():
    schema_filename = settings.BASE_DIR / "api/event.schema.altered.json"
    with open(schema_filename, "r") as f:
        return json.loads(f.read())


def get_event_validation_problem(data):
    data_to_validate = {k: v for k, v in data.items() if k != "_meta"}

    try:
        from bugsink.event_schema import validate as validate_schema
        validate_schema(data_to_validate)
        return None
    except fastjsonschema.exceptions.JsonSchemaValueException as fastjsonschema_e:
        try:
            jsonschema.validate(data_to_validate, _get_event_schema())
        except jsonschema.ValidationError as inner_e:
            best = jsonschema.exceptions.best_match([inner_e])
            return EventValidationProblem(
                path=best.json_path or "$",
                message=best.message,
                validator=best.validator,
                validator_value=best.validator_value,
                absolute_path=tuple(best.absolute_path),
            )

        return EventValidationProblem(path="$", message=fastjsonschema_e.message)
