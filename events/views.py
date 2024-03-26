from django.http import HttpResponse
from django.utils.http import content_disposition_header

from bugsink.decorators import event_membership_required


@event_membership_required
def event_download(request, event, as_attachment=False):
    result = HttpResponse(event.data, content_type="application/json")
    result["Content-Disposition"] = content_disposition_header(
        as_attachment=as_attachment, filename=event.id.hex + ".json")
    return result
