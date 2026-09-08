from django.shortcuts import render, redirect
from django.http import Http404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bugsink.decorators import atomic_for_request_method

from .models import AuthToken


@atomic_for_request_method
@user_passes_test(lambda u: u.is_superuser)
def auth_token_list(request):
    not_expired = Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    auth_tokens = AuthToken.objects.filter(not_expired)

    if request.method == 'POST':
        full_action_str = request.POST.get('action')
        action, pk = full_action_str.split(":", 1)
        if action == "revoke":
            auth_token = AuthToken.objects.filter(pk=pk).first()
            if auth_token is not None:
                auth_token.revoke()

            messages.success(request, _('Token revoked'))
            return redirect('auth_token_list')

        elif action == "update_description":
            description = request.POST.get(f'description-{pk}', '')[:255]
            AuthToken.objects.filter(pk=pk).update(description=description)

            messages.success(request, _('Description updated'))
            return redirect('auth_token_list')

    return render(request, 'bsmain/auth_token_list.html', {
        'auth_tokens': auth_tokens,
    })


@atomic_for_request_method
@user_passes_test(lambda u: u.is_superuser)
def auth_token_create(request):
    if request.method != 'POST':
        raise Http404("Invalid request method")

    AuthToken.create_full_access()

    return redirect("auth_token_list")
