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

    # note to self: CursorPagination is the "obviously right" choice for navigating large datasets because it scales
    # well; I'm not entirely sure why I didn't use the non-API equvivalent of this for the web UI (in issues/views.py)
    # when I ran into performance problems in the past. I suspect it's because (at least partially) because the "cursor"
    # approach precludes jumping to arbitrary pages; another part might be that I assumed that "endless scrolling" (by
    # clicking 'next page' repeatedly) is an unlikely use case anyway, especially since I already generally have very
    # large page sizes; in short, I probably dind't think that the performance problem of "navigating to a large offset"
    # was likely to happen in practice (as opposed to: count breaking down at scale, which I did see in practice and
    # solved). For now: we'll keep this for the API only, and see how it goes.

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
