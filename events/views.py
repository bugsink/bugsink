import json

from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.utils.http import content_disposition_header

from issues.utils import get_hash_for_data, get_issue_grouper_for_data

from .models import Event


def event_detail(request, pk):
    obj = get_object_or_404(Event, pk=pk)

    parsed_data = json.loads(obj.data)

    # sentry/glitchtip have some code here to deal with the case that "values" is not present, and exception itself is
    # the list of exceptions, but we don't aim for endless backwards compat (yet) so we don't.
    exceptions = parsed_data["exception"]["values"] if "exception" in parsed_data else None

    if parsed_data["logentry"]:
        logentry = parsed_data["logentry"]
        if "formatted" not in logentry:
            # TODO this is just a wild guess"
            if "message" in logentry:
                if "params" not in logentry:
                    logentry["formatted"] = logentry["message"]
                else:
                    logentry["formatted"] = logentry["message"].format(logentry["params"])

    return render(request, "events/event_detail.html", {
        "obj": obj,
        "parsed_data": parsed_data,
        "exceptions": exceptions,
        "issue_grouper": get_issue_grouper_for_data(parsed_data),
    })


def event_download(request, pk, as_attachment=False):
    obj = get_object_or_404(Event, pk=pk)
    result = HttpResponse(obj.data, content_type="application/json")
    result["Content-Disposition"] = content_disposition_header(
        as_attachment=as_attachment, filename=obj.id.hex + ".json")
    return result


def debug_get_hash(request, event_pk):
    # debug view; not for eternity

    obj = get_object_or_404(Event, pk=event_pk)

    parsed_data = json.loads(obj.data)

    print(get_hash_for_data(parsed_data))
