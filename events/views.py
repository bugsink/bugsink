import json
from django.http import HttpResponse
from django.utils.http import content_disposition_header
from django.shortcuts import render

from bugsink.decorators import event_membership_required, atomic_for_request_method


@atomic_for_request_method
@event_membership_required
def event_download(request, event, as_attachment=False):
    result = HttpResponse(event.data, content_type="application/json")
    result["Content-Disposition"] = content_disposition_header(
        as_attachment=as_attachment, filename=event.id.hex + ".json")
    return result


@atomic_for_request_method
@event_membership_required
def event_plaintext(request, event):
    parsed_data = json.loads(event.data)
    exceptions = parsed_data["exception"]["values"] if "exception" in parsed_data else None

    return render(request, "events/event_stacktrace.txt", {
        "event": event,
        "exceptions": exceptions,
    }, content_type="text/plain")
