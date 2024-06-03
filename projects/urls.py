from django.urls import path

from .views import project_list, project_members

urlpatterns = [
    path('', project_list, name="project_list"),
    path('<int:project_pk>/members/', project_members, name="project_members"),
]
