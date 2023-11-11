import json

from django.shortcuts import render, get_object_or_404

from issues.utils import get_hash_for_data, get_issue_grouper_for_data

from .models import Event


def event_detail(request, pk):
    obj = get_object_or_404(Event, pk=pk)

    parsed_data = json.loads(obj.data)

    # NOTE: instead of values, this may also just be a flat list; TODO implement this
    exceptions = parsed_data["exception"]["values"]

    return render(request, "events/event_detail.html", {
        "obj": obj,
        "parsed_data": parsed_data,
        "exceptions": exceptions,
        "issue_grouper": get_issue_grouper_for_data(parsed_data),
    })


def debug_get_hash(request, event_pk):
    # debug view; not for eternity

    obj = get_object_or_404(Event, pk=event_pk)

    parsed_data = json.loads(obj.data)

    print(get_hash_for_data(parsed_data))
