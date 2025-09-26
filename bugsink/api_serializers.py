import datetime
from rest_framework import serializers


class UTCModelSerializer(serializers.ModelSerializer):

    def build_standard_field(self, field_name, model_field):
        field_class, field_kwargs = super().build_standard_field(field_name, model_field)

        if field_class is serializers.DateTimeField:
            field_kwargs.setdefault("default_timezone", datetime.timezone.utc)

        return field_class, field_kwargs
