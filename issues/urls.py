from django.urls import path

from .views import (
    issue_list, issue_event_stacktrace, issue_event_details, issue_last_event, issue_event_list, issue_history,
    issue_grouping)

urlpatterns = [
    path('<int:project_id>/', issue_list, {"state_filter": "open"}, name="issue_list_open"),
    path('<int:project_id>/unresolved', issue_list, {"state_filter": "unresolved"}, name="issue_list_unresolved"),
    path('<int:project_id>/resolved/', issue_list, {"state_filter": "resolved"}, name="issue_list_resolved"),
    path('<int:project_id>/muted/', issue_list, {"state_filter": "muted"}, name="issue_list_muted"),
    path('<int:project_id>/all/', issue_list, {"state_filter": "all"}, name="issue_list_all"),

    path('issue/<uuid:issue_pk>/event/<uuid:event_pk>/', issue_event_stacktrace),
    path('issue/<uuid:issue_pk>/event/<uuid:event_pk>/details/', issue_event_details),
    path('issue/<uuid:issue_pk>/history/', issue_history),
    path('issue/<uuid:issue_pk>/grouping/', issue_grouping),
    path('issue/<uuid:issue_pk>/event/last/', issue_last_event),
    path('issue/<uuid:issue_pk>/events/', issue_event_list),
]
