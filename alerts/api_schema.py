from django import forms
from drf_spectacular.openapi import AutoSchema

from .models import MessagingServiceConfig, get_alert_service_backend_class, get_alert_service_kind_choices


class MessagingServiceSchema(AutoSchema):
    def get_operation(self, *args, **kwargs):
        operation = super().get_operation(*args, **kwargs)
        if operation is not None and self.view.action == "create":
            # drf-spectacular cannot infer body requiredness from a raw request schema.
            operation["requestBody"]["required"] = True
        return operation


def config_schema(kind):
    form = get_alert_service_backend_class(kind).get_form_class()()
    properties = {}
    required = []
    for name, field in form.fields.items():
        if isinstance(field, forms.IntegerField):
            schema = {"type": "integer"}
            if field.min_value is not None:
                schema["minimum"] = field.min_value
            if field.max_value is not None:
                schema["maximum"] = field.max_value
        elif isinstance(field, forms.CharField):
            schema = {"type": "string"}
            if field.required:
                schema["minLength"] = 1
            if field.max_length is not None:
                schema["maxLength"] = field.max_length
            if isinstance(field, forms.URLField):
                schema["format"] = "uri"
        else:
            raise NotImplementedError("No API schema for config field: %s." % name)

        if field.help_text:
            schema["description"] = str(field.help_text)
        if field.required:
            required.append(name)
        else:
            schema["nullable"] = True
        properties[name] = schema

    return {"type": "object", "title": kind, "properties": properties, "required": required}


def messaging_service_create_schema():
    return {
        "oneOf": [
            {
                "type": "object",
                "title": label,
                "properties": {
                    "project": {"type": "integer"},
                    "display_name": {
                        "type": "string", "minLength": 1,
                        "maxLength": MessagingServiceConfig._meta.get_field("display_name").max_length,
                    },
                    "kind": {"type": "string", "enum": [kind]},
                    "config": {**config_schema(kind), "writeOnly": True},
                },
                "required": ["project", "display_name", "kind", "config"],
            }
            for kind, label in get_alert_service_kind_choices()
        ],
    }
