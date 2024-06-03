from django.urls import path

from .views import team_list, team_members, team_members_invite, team_members_accept_new_user, team_members_accept

urlpatterns = [
    path('', team_list, name="team_list"),
    path('<str:team_pk>/members/', team_members, name="team_members"),
    path('<str:team_pk>/members/invite/', team_members_invite, name="team_members_invite"),
    path('<str:team_pk>/members/accept/', team_members_accept, name="team_members_accept"),
    path(
        '<str:team_pk>/members/accept/<str:token>/', team_members_accept_new_user, name="team_members_accept_new_user"),
]
