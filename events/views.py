import json

from django.shortcuts import render, get_object_or_404

from ingest.models import DecompressedEvent
from issues.utils import get_hash_for_data, get_issue_grouper_for_data


def decompressed_event_detail(request, pk):
    # this view is misplaced "by nature" (it mixes ingested stuff and rendering); until we create a pipeline for that.
    obj = get_object_or_404(DecompressedEvent, pk=pk)

    parsed_data = json.loads(obj.data)

    # NOTE: instead of values, this may also just be a flat list; TODO implement this
    exceptions = parsed_data["exception"]["values"]

    return render(request, "events/event_detail.html", {
        "obj": obj,
        "parsed_data": parsed_data,
        "exceptions": exceptions,
        "issue_grouper": get_issue_grouper_for_data(parsed_data),
    })


def debug_get_hash(request, decompressed_event_pk):
    # debug view; not for eternity

    obj = get_object_or_404(DecompressedEvent, pk=decompressed_event_pk)

    parsed_data = json.loads(obj.data)

    print(get_hash_for_data(parsed_data))
