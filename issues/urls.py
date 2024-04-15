from django.urls import path

from .views import (
    issue_list, issue_event_stacktrace, issue_event_details, issue_last_event, issue_event_list, issue_history,
    issue_grouping, issue_event_breadcrumbs, event_by_internal_id, history_comment_new, history_comment_edit)

urlpatterns = [
    path('<int:project_pk>/', issue_list, {"state_filter": "open"}, name="issue_list_open"),
    path('<int:project_pk>/unresolved', issue_list, {"state_filter": "unresolved"}, name="issue_list_unresolved"),
    path('<int:project_pk>/resolved/', issue_list, {"state_filter": "resolved"}, name="issue_list_resolved"),
    path('<int:project_pk>/muted/', issue_list, {"state_filter": "muted"}, name="issue_list_muted"),
    path('<int:project_pk>/all/', issue_list, {"state_filter": "all"}, name="issue_list_all"),

    path('issue/<uuid:issue_pk>/event/<uuid:event_pk>/', issue_event_stacktrace, name="event_stacktrace"),

    path('issue/<uuid:issue_pk>/event/<uuid:event_pk>/details/', issue_event_details, name="event_details"),
    path('issue/<uuid:issue_pk>/event/<uuid:event_pk>/breadcrumbs/', issue_event_breadcrumbs, name="event_breadcrumbs"),

    path('issue/<uuid:issue_pk>/event/<int:ingest_order>/', issue_event_stacktrace, name="event_stacktrace"),
    path('issue/<uuid:issue_pk>/event/<int:ingest_order>/details/', issue_event_details, name="event_details"),
    path('issue/<uuid:issue_pk>/event/<int:ingest_order>/breadcrumbs/', issue_event_breadcrumbs,
         name="event_breadcrumbs"),

    path('issue/<uuid:issue_pk>/history/', issue_history),
    path('issue/<uuid:issue_pk>/grouping/', issue_grouping),
    path('issue/<uuid:issue_pk>/event/last/', issue_last_event),
    path('issue/<uuid:issue_pk>/events/', issue_event_list),

    path('event/<uuid:event_pk>/', event_by_internal_id, name="event_by_internal_id"),
    path('issue/<uuid:issue_pk>/history/comment/', history_comment_new, name="history_comment_new"),
    path('event/<uuid:event_pk>/history/comment/<int:comment_id>/', history_comment_edit, name="history_comment_edit"),
]
