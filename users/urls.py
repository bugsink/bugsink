from django.urls import path

from .views import user_list, user_edit

urlpatterns = [
    path('', user_list, name="user_list"),
    path('<str:user_pk>/edit/', user_edit, name="user_edit"),
]
