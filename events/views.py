import json

from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils.http import content_disposition_header

from issues.utils import get_hash_for_data

from .models import Event
from bugsink.decorators import event_membership_required


@event_membership_required
def event_download(request, event, as_attachment=False):
    result = HttpResponse(event.data, content_type="application/json")
    result["Content-Disposition"] = content_disposition_header(
        as_attachment=as_attachment, filename=event.id.hex + ".json")
    return result


def debug_get_hash(request, event_pk):
    # debug view; not for eternity

    obj = get_object_or_404(Event, pk=event_pk)

    parsed_data = json.loads(obj.data)

    print(get_hash_for_data(parsed_data))
