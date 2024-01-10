from celery import shared_task


@shared_task
def send_new_issue_alert(issue_id):
    raise NotImplementedError("TODO")


@shared_task
def send_regression_alert(issue_id):
    raise NotImplementedError("TODO")


@shared_task
def send_unmute_alert(issue_id):
    raise NotImplementedError("TODO")
