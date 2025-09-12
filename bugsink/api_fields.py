from rest_framework import serializers


def make_enum_field(enum_cls, *, name=None):

    class EnumChoiceField(serializers.ChoiceField):
        _enum_cls = enum_cls

        def __init__(self, **kwargs):
            self._to_value = {m.name.lower(): m.value for m in enum_cls}
            self._to_name = {m.value: m.name.lower() for m in enum_cls}
            super().__init__(choices=self._to_value, **kwargs)

        def to_representation(self, value):
            return self._to_name[value]

        def to_internal_value(self, data):
            key = super().to_internal_value(data)
            return self._to_value[key]

    EnumChoiceField.__name__ = name or f"{enum_cls.__name__}Field"
    return EnumChoiceField
