from rest_framework.exceptions import ValidationError

from bugsink.decorators import atomic_for_request_method


class AtomicRequestMixin:
    def dispatch(self, request, *args, **kwargs):
        wrapped = atomic_for_request_method(super().dispatch, using=None)
        return wrapped(request, *args, **kwargs)


class ExpandableSerializerMixin:
    expandable_fields = {}

    def __init__(self, *args, **kwargs):
        self._expand = set(kwargs.pop("expand", []))
        super().__init__(*args, **kwargs)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for field, serializer_cls in self.expandable_fields.items():
            if field in self._expand:
                data[field] = serializer_cls(getattr(instance, field)).data
        return data


class ExpandViewSetMixin:
    """
    Mixin for ViewSets that support ?expand=...
    Requires the serializer class to define expandable_fields.
    """

    def get_serializer(self, *args, **kwargs):
        expand = self.request.query_params.getlist("expand")
        if expand:
            if len(expand) == 1 and "," in expand[0]:
                expand = expand[0].split(",")

            serializer_cls = self.get_serializer_class()
            expandable = getattr(serializer_cls, "expandable_fields", None)
            if expandable is None:
                raise ValidationError({"expand": ["Expansions are not supported on this endpoint."]})

            invalid = [f for f in expand if f not in expandable]
            if invalid:
                raise ValidationError({"expand": [f"Unknown field: {name}" for name in invalid]})

            kwargs["expand"] = expand

        return super().get_serializer(*args, **kwargs)
