from django.shortcuts import render, redirect
from django.http import Http404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test

from bugsink.decorators import atomic_for_request_method

from .models import AuthToken


@atomic_for_request_method
@user_passes_test(lambda u: u.is_superuser)
def auth_token_list(request):
    auth_tokens = AuthToken.objects.all()

    if request.method == 'POST':
        # DIT KOMT ZO WEL
        full_action_str = request.POST.get('action')
        action, pk = full_action_str.split(":", 1)
        if action == "delete":
            AuthToken.objects.get(pk=pk).delete()

            messages.success(request, 'Token deleted')
            return redirect('auth_token_list')

    return render(request, 'bsmain/auth_token_list.html', {
        'auth_tokens': auth_tokens,
    })


@atomic_for_request_method
@user_passes_test(lambda u: u.is_superuser)
def auth_token_create(request):
    if request.method != 'POST':
        raise Http404("Invalid request method")

    AuthToken.objects.create()

    return redirect("auth_token_list")
