from django.http import HttpResponse
from django.utils.http import content_disposition_header
from django.shortcuts import render

from bugsink.decorators import event_membership_required, atomic_for_request_method
from issues.utils import get_values


@atomic_for_request_method
@event_membership_required
def event_download(request, event, as_attachment=False):
    result = HttpResponse(event.get_raw_data(), content_type="application/json")
    result["Content-Disposition"] = content_disposition_header(
        as_attachment=as_attachment, filename=event.id.hex + ".json")
    return result


@atomic_for_request_method
@event_membership_required
def event_plaintext(request, event):
    parsed_data = event.get_parsed_data()
    exceptions = get_values(parsed_data["exception"]) if "exception" in parsed_data else None

    return render(request, "events/event_stacktrace.txt", {
        "event": event,
        "exceptions": exceptions,
    }, content_type="text/plain")
