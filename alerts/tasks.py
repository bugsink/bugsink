from celery import shared_task


@shared_task
def send_unmute_notification(issue_id):
    raise NotImplementedError("TODO")
