from django.urls import path, register_converter

from .views import (
    issue_list, issue_event_stacktrace, issue_event_details, issue_event_list, issue_history, issue_grouping,
    issue_event_breadcrumbs, event_by_internal_id, history_comment_new, history_comment_edit, history_comment_delete,
    issue_tags)


def regex_converter(passed_regex):

    class RegexConverter:
        regex = passed_regex

        def to_python(self, value):
            return value

        def to_url(self, value):
            return value

    return RegexConverter


register_converter(regex_converter("(first|last)"), "first-last")
register_converter(regex_converter("(prev|next)"), "prev-next")


urlpatterns = [
    path('<int:project_pk>/', issue_list, {"state_filter": "open"}, name="issue_list_open"),
    path('<int:project_pk>/unresolved', issue_list, {"state_filter": "unresolved"}, name="issue_list_unresolved"),
    path('<int:project_pk>/resolved/', issue_list, {"state_filter": "resolved"}, name="issue_list_resolved"),
    path('<int:project_pk>/muted/', issue_list, {"state_filter": "muted"}, name="issue_list_muted"),
    path('<int:project_pk>/all/', issue_list, {"state_filter": "all"}, name="issue_list_all"),

    path('issue/<uuid:issue_pk>/event/<uuid:event_pk>/', issue_event_stacktrace, name="event_stacktrace"),
    path('issue/<uuid:issue_pk>/event/<uuid:event_pk>/details/', issue_event_details, name="event_details"),
    path('issue/<uuid:issue_pk>/event/<uuid:event_pk>/breadcrumbs/', issue_event_breadcrumbs, name="event_breadcrumbs"),

    path('issue/<uuid:issue_pk>/event/<int:digest_order>/', issue_event_stacktrace, name="event_stacktrace"),
    path('issue/<uuid:issue_pk>/event/<int:digest_order>/details/', issue_event_details, name="event_details"),
    path('issue/<uuid:issue_pk>/event/<int:digest_order>/breadcrumbs/', issue_event_breadcrumbs,
         name="event_breadcrumbs"),

    path('issue/<uuid:issue_pk>/event/<int:digest_order>/', issue_event_stacktrace, name="event_stacktrace"),
    path('issue/<uuid:issue_pk>/event/<int:digest_order>/details/', issue_event_details, name="event_details"),
    path('issue/<uuid:issue_pk>/event/<int:digest_order>/breadcrumbs/', issue_event_breadcrumbs,
         name="event_breadcrumbs"),

    path('issue/<uuid:issue_pk>/event/<int:digest_order>/<prev-next:nav>/', issue_event_stacktrace,
         name="event_stacktrace"),
    path('issue/<uuid:issue_pk>/event/<int:digest_order>/<prev-next:nav>/details/', issue_event_details,
         name="event_details"),
    path('issue/<uuid:issue_pk>/event/<int:digest_order>/<prev-next:nav>/breadcrumbs/', issue_event_breadcrumbs,
         name="event_breadcrumbs"),

    path('issue/<uuid:issue_pk>/event/<first-last:nav>/', issue_event_stacktrace, name="event_stacktrace"),
    path('issue/<uuid:issue_pk>/event/<first-last:nav>/details/', issue_event_details, name="event_details"),
    path('issue/<uuid:issue_pk>/event/<first-last:nav>/breadcrumbs/', issue_event_details, name="event_breadcrumbs"),

    path('issue/<uuid:issue_pk>/tags/', issue_tags),
    path('issue/<uuid:issue_pk>/history/', issue_history),
    path('issue/<uuid:issue_pk>/grouping/', issue_grouping),
    path('issue/<uuid:issue_pk>/events/', issue_event_list),

    path('event/<uuid:event_pk>/', event_by_internal_id, name="event_by_internal_id"),
    path('issue/<uuid:issue_pk>/history/comment/', history_comment_new, name="history_comment_new"),
    path('issue/<uuid:issue_pk>/history/comment/<int:comment_pk>/', history_comment_edit, name="history_comment_edit"),
    path('issue/<uuid:issue_pk>/history/comment/<int:comment_pk>/delete/', history_comment_delete,
         name="history_comment_delete"),
]
