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

    def as_validation_error_message(self):
        return f"{self.path}: {self.message}"


@lru_cache(maxsize=1)
def _get_schema():
    schema_filename = settings.BASE_DIR / 'api/event.schema.altered.json'
    with open(schema_filename, 'r') as f:
        return json.loads(f.read())


@lru_cache(maxsize=1)
def _get_fast_validator():
    from bugsink.event_schema import validate as validate_schema
    return validate_schema


def get_event_validation_problem(data):
    data_to_validate = {k: v for k, v in data.items() if k != "_meta"}

    try:
        _get_fast_validator()(data_to_validate)
        return None
    except fastjsonschema.exceptions.JsonSchemaValueException as fastjsonschema_e:
        # fastjsonschema is our fast path, but its anyOf errors are not specific enough to drive targeted repairs.
        # For failures we pay the extra cost of jsonschema to get the actual failing path back.
        try:
            jsonschema.validate(data_to_validate, _get_schema())
        except jsonschema.ValidationError as inner_e:
            best = jsonschema.exceptions.best_match([inner_e])
            return EventValidationProblem(best.json_path or "$", best.message)

        return EventValidationProblem("$", fastjsonschema_e.message)
