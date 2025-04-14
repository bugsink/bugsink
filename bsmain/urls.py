from django.urls import path

from .views import auth_token_list, auth_token_create


urlpatterns = [
    path('auth_tokens/', auth_token_list, name='auth_token_list'),
    path('auth_tokens/create/', auth_token_create, name='auth_token_create'),
]
