from django.urls import path

from .views import (
    project_list, project_members, project_members_accept, project_member_settings, project_members_invite,
    project_members_accept_new_user, project_new, project_edit, project_sdk_setup)

urlpatterns = [
    path('', project_list, name="project_list"),

    path('mine/', project_list, kwargs={"ownership_filter": "mine"}, name="project_list_mine"),
    path('teams/', project_list, kwargs={"ownership_filter": "teams"}, name="project_list_teams"),
    path('other/', project_list, kwargs={"ownership_filter": "other"}, name="project_list_other"),
    path('new/', project_new, name="project_new"),
    path('<int:project_pk>/edit/', project_edit, name="project_edit"),
    path('<int:project_pk>/members/', project_members, name="project_members"),
    path('<int:project_pk>/members/invite/', project_members_invite, name="project_members_invite"),
    path('<int:project_pk>/members/accept/', project_members_accept, name="project_members_accept"),
    path('<str:project_pk>/members/accept/<str:token>/', project_members_accept_new_user,
         name="project_members_accept_new_user"),
    path('<int:project_pk>/members/settings/<str:user_pk>/', project_member_settings, name="project_member_settings"),

    path('<int:project_pk>/sdk-setup/', project_sdk_setup, name="project_sdk_setup"),
    path('<int:project_pk>/sdk-setup/<str:platform>/', project_sdk_setup, name="project_sdk_setup_platform"),
]
