from django.shortcuts import get_object_or_404, render, redirect
from django.http import Http404
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bugsink.api_capabilities import CAPABILITIES
from bugsink.decorators import atomic_for_request_method

from .forms import AuthTokenForm
from .models import AuthToken


def _auth_tokens_visible_to(user):
    not_expired = Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    auth_tokens = AuthToken.objects.filter(not_expired)
    if user.is_superuser:
        return auth_tokens
    return auth_tokens.filter(is_user_bound=True, user=user)


@atomic_for_request_method
def auth_token_list(request):
    auth_tokens = _auth_tokens_visible_to(request.user)

    if request.method == 'POST':
        full_action_str = request.POST.get('action')
        action, pk = full_action_str.split(":", 1)
        if action == "revoke":
            auth_token = get_object_or_404(auth_tokens, pk=pk)
            auth_token.revoke()

            messages.success(request, _('Token revoked'))
            return redirect('auth_token_list')

        raise Http404("Invalid token action")

    auth_tokens = list(auth_tokens.select_related("user", "project").order_by("-created_at"))
    for auth_token in auth_tokens:
        auth_token.has_all_capabilities = auth_token.capabilities == set(CAPABILITIES)
        capability_groups = {}
        for capability in CAPABILITIES:
            if capability in auth_token.capabilities:
                prefix, name = capability.split(":", 1)
                capability_groups.setdefault(prefix, []).append(name)
        auth_token.capability_groups = capability_groups.items()

    return render(request, 'bsmain/auth_token_list.html', {
        'auth_tokens': auth_tokens,
    })


@atomic_for_request_method
def auth_token_create(request):
    if request.method == "POST":
        form = AuthTokenForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, _("Token created"))
            return redirect("auth_token_list")
    else:
        form = AuthTokenForm(user=request.user)

    return render(request, "bsmain/auth_token_create.html", {"form": form})
