from rest_framework import serializers


class EnumLowercaseChoiceField(serializers.ChoiceField):

    def __init__(self, enum_cls, **kwargs):
        self._to_value = {member.name.lower(): member.value for member in enum_cls}
        super().__init__(choices=self._to_value, **kwargs)
        self._to_name = {member.value: member.name.lower() for member in enum_cls}

    def to_representation(self, value):
        # fails hard for invalid values (shouldn't happen, would imply data corruption)
        return self._to_name[value]

    def to_internal_value(self, data):
        key = super().to_internal_value(data)
        return self._to_value[key]
