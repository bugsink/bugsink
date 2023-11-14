import json

from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.utils.http import content_disposition_header

from issues.utils import get_hash_for_data, get_issue_grouper_for_data

from .models import Event


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
