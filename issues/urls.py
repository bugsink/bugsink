from django.urls import path

from .views import issue_list, issue_event_detail, issue_last_event, issue_event_list


urlpatterns = [
    # path('issue/<uuid:pk>/', issue_detail),
    path('<int:project_id>/', issue_list),
    path('issue/<uuid:issue_pk>/event/<uuid:event_pk>/', issue_event_detail),
    path('issue/<uuid:issue_pk>/event/last/', issue_last_event),
    path('issue/<uuid:issue_pk>/events/', issue_event_list),
]
