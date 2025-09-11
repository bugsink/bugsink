from rest_framework.pagination import CursorPagination
from rest_framework.exceptions import ValidationError


class AscDescCursorPagination(CursorPagination):
    """
    Cursor-based paginator that supports `?order=asc|desc`.
    Each view sets:
        base_ordering = ("field",) or ("field1", "field2")
        default_direction = "asc" | "desc"
        page_size = <int>
    """

    base_ordering = None
    default_direction = "desc"

    def get_ordering(self, request, queryset, view):
        order_param = request.query_params.get("order")
        if order_param and order_param not in ("asc", "desc"):
            raise ValidationError({"order": ["Must be 'asc' or 'desc'."]})

        direction = order_param or self.default_direction

        if self.base_ordering is None:
            raise RuntimeError("AscDescCursorPagination requires base_ordering to be set.")

        ordering = []
        for field in self.base_ordering:
            ordering.append(f"-{field}" if direction == "desc" else field)
        return ordering
