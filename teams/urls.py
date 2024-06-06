from django.urls import path

from .views import (
    team_list, team_members, team_members_invite, team_members_accept_new_user, team_members_accept,
    team_member_settings, team_new, team_edit)

urlpatterns = [
    path('', team_list, name="team_list"),
    path('mine/', team_list, kwargs={"ownership_filter": "mine"}, name="team_list_mine"),
    path('other/', team_list, kwargs={"ownership_filter": "other"}, name="team_list_other"),
    path('new/', team_new, name="team_new"),
    path('<str:team_pk>/edit/', team_edit, name="team_edit"),
    path('<str:team_pk>/members/', team_members, name="team_members"),
    path('<str:team_pk>/members/invite/', team_members_invite, name="team_members_invite"),
    path('<str:team_pk>/members/accept/', team_members_accept, name="team_members_accept"),
    path(
        '<str:team_pk>/members/accept/<str:token>/', team_members_accept_new_user, name="team_members_accept_new_user"),
    path('<str:team_pk>/members/settings/<str:user_pk>/', team_member_settings, name="team_member_settings"),
]
