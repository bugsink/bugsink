from django.urls import path

from .views import issue_list, issue_event_list


urlpatterns = [
    # path('issue/<uuid:pk>/', issue_detail),
    path('<int:project_id>/', issue_list),
    path('issue/<uuid:issue_pk>/events/', issue_event_list),
]
