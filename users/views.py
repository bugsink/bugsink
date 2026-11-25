from datetime import timedelta
from urllib.parse import urlencode

from django.contrib.auth import login
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import render, redirect, reverse
from django.contrib.auth import get_user_model
from django.http import Http404
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils.translation import gettext as _
from django.utils import translation
from django.db.models import F
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache

from bugsink.app_settings import get_settings, CB_ANYBODY
from bugsink.decorators import atomic_for_request_method
from bugsink.middleware import get_chosen_language
from bugsink.utils import is_safe_next_url

from .forms import (
    UserCreationForm, ResendConfirmationForm, RequestPasswordResetForm, SetPasswordForm, PreferencesForm, UserEditForm)
from .models import EmailVerification
from .tasks import send_confirm_email, send_reset_email


User = get_user_model()


@atomic_for_request_method
@user_passes_test(lambda u: u.is_superuser)
def user_list(request):
    users = User.objects.all().order_by('username')

    if request.method == 'POST':
        full_action_str = request.POST.get('action')
        action, user_pk = full_action_str.split(":", 1)
        if action == "deactivate":
            user = User.objects.get(pk=user_pk)
            user.deactivate()

            messages.success(request, 'User %s deactivated' % user.username)
            return redirect('user_list')

        if action == "activate":
            user = User.objects.get(pk=user_pk)
            user.is_active = True
            user.is_deactivated = False
            user.save()

            messages.success(request, 'User %s activated' % user.username)
            return redirect('user_list')

        if action == "delete":
            user = User.objects.get(pk=user_pk)
            if user.is_active:
                messages.error(request, 'Cannot delete active user %s' % user.username)
            else:
                username = user.username
                user.delete()
                messages.success(request, 'User %s deleted' % username)
            return redirect('user_list')

    return render(request, 'users/user_list.html', {
        'users': users,
    })


@atomic_for_request_method
@user_passes_test(lambda u: u.is_superuser)
def user_edit(request, user_pk):
    user = User.objects.get(pk=user_pk)
    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user)

        if form.is_valid():
            form.save()
            return redirect("user_list")

    else:
        form = UserEditForm(instance=user)

    return render(request, "users/user_edit.html", {"form": form})


@sensitive_post_parameters("password1", "password2")
@atomic_for_request_method
def signup(request):
    if get_settings().USER_REGISTRATION != CB_ANYBODY:
        raise Http404("User self-registration is not allowed.")

    if request.method == 'POST':
        form = UserCreationForm(request.POST)

        if form.is_valid():
            if get_settings().USER_REGISTRATION_VERIFY_EMAIL:
                user = form.save(commit=False)
                user.is_active = False
                user.save()

                verification = EmailVerification.objects.create(user=user, email=user.username)
                send_confirm_email.delay(user.username, verification.token)

                return render(request, "users/confirm_email_sent.html", {"email": user.username})

            user = form.save()
            login(request, user)
            return redirect('home')
    else:
        form = UserCreationForm()

    return render(request, "signup.html", {"form": form})


@atomic_for_request_method
def confirm_email(request, token=None):
    # clean up expired tokens; doing this on every request is just fine, it saves us from having to run a cron job-like
    EmailVerification.objects.filter(
        created_at__lt=timezone.now() - timedelta(
            seconds=get_settings().USER_REGISTRATION_VERIFY_EMAIL_EXPIRY)).delete()

    try:
        verification = EmailVerification.objects.get(token=token, email=F("user__username"))
    except EmailVerification.DoesNotExist:
        # good enough (though a special page might be prettier)
        raise Http404("Invalid or expired token")

    if verification.user.is_active or verification.user.is_deactivated:
        raise Http404("This account is not awaiting email confirmation.")

    if request.method == 'POST':
        # We insist on POST requests to do the actual confirmation (at the cost of an extra click). See:
        # https://softwareengineering.stackexchange.com/a/422579/168778
        # there's no Django form (fields), there's just a button to generate the post request

        verification.user.is_active = True
        verification.user.save()
        verification.delete()

        # this mirrors the approach of what we do in password-resetting; and rightfully so because the in both cases
        # access to email is assumed to be sufficient proof of identity.
        login(request, verification.user)

        return redirect('home')

    return render(request, "users/confirm_email.html")


@atomic_for_request_method
def resend_confirmation(request):
    if request.method == 'POST':
        form = ResendConfirmationForm(request.POST)

        if form.is_valid():
            user = User.objects.get(username=form.cleaned_data['email'])
            if user.is_active or user.is_deactivated:
                raise Http404("This account is not awaiting email confirmation.")

            verification = EmailVerification.objects.create(user=user, email=user.username)
            send_confirm_email.delay(user.username, verification.token)
            return render(request, "users/confirm_email_sent.html", {"email": user.username})
    else:
        form = ResendConfirmationForm(data=request.GET)

    return render(request, "users/resend_confirmation.html", {"form": form})


@atomic_for_request_method
def request_reset_password(request):
    # something like this exists in Django too; copy-paste-modify from the other views was more simple than thoroughly
    # understanding the Django implementation and hooking into it.

    if request.method == 'POST':
        form = RequestPasswordResetForm(request.POST)

        if form.is_valid():
            user = User.objects.get(username=form.cleaned_data['email'])
            if not user.is_active or user.is_deactivated:
                raise Http404("Cannot reset the password of an inactive account.")

            # We reuse email-verification tokens for password resets and initial password setup after invitations.
            # Both use mailbox access to prove account ownership.
            verification = EmailVerification.objects.create(user=user, email=user.username)
            send_reset_email.delay(user.username, verification.token)
            return render(request, "users/reset_password_email_sent.html", {"email": user.username})

    else:
        form = RequestPasswordResetForm()

    return render(request, "users/request_reset_password.html", {"form": form})


@never_cache
@sensitive_post_parameters("new_password1", "new_password2")
@atomic_for_request_method
def reset_password(request, token=None):
    # alternative name: set_password (because this one also works for initial setting of a password)

    # clean up expired tokens; doing this on every request is just fine, it saves us from having to run a cron
    # job-like thing
    EmailVerification.objects.filter(
        created_at__lt=timezone.now() - timedelta(
            seconds=get_settings().USER_REGISTRATION_VERIFY_EMAIL_EXPIRY)).delete()

    # no_bandit_expl: "set-password" is a URL marker, not a secret token.
    verification_token = request.session.get("_password_reset_token") if token == "set-password" else token  # nosec B105

    try:
        verification = EmailVerification.objects.get(token=verification_token, email=F("user__username"))
    except EmailVerification.DoesNotExist:
        # good enough (though a special page might be prettier)
        raise Http404("Invalid or expired token")

    user = verification.user
    if user.is_deactivated:
        raise Http404("This account has been deactivated.")

    next_url = request.POST.get("next", request.GET.get("next", reverse("home")))

    if not is_safe_next_url(next_url, request):
        next_url = reverse("home")

    # no_bandit_expl: "set-password" is a URL marker, not a secret token.
    if token != "set-password":  # nosec B105
        # Keep the bearer token out of the form URL and subsequent Referer headers.
        request.session["_password_reset_token"] = verification.token
        # no_bandit_expl: "set-password" is a URL marker, not a secret token.
        reset_url = reverse("reset_password", kwargs={"token": "set-password"})  # nosec B105
        return redirect(reset_url + "?" + urlencode({"next": next_url}))

    if request.method == 'POST':
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            user.is_active = True  # also completes initial setup for invited users
            user.set_password(form.cleaned_data['new_password1'])
            user.save()

            request.session.pop("_password_reset_token", None)
            login(request, verification.user)

            return redirect(next_url)

    else:
        form = SetPasswordForm(user)

    return render(request, "users/reset_password.html", {"form": form, "next": next_url})


@atomic_for_request_method
# in the general case this is done by Middleware but we're under /accounts/, so we need it back.
# not security-critical because we simply get a failure on request.user if this wasn't there, but still the right thing.
@login_required
def preferences(request):
    user = request.user
    if request.method == 'POST':
        form = PreferencesForm(request.POST, instance=user)

        if form.is_valid():
            user = form.save()

            # activate the selected language immediately for the Success message; we've already passed the
            # middleware stage (which looked at the pre-change language), so we need to do this ourselves with the
            # fresh value.
            translation.activate(get_chosen_language(user, request))

            messages.success(request, _("Updated preferences"))
            return redirect('preferences')

    else:
        form = PreferencesForm(instance=user)

    return render(request, 'users/preferences.html', {
        'form': form,
    })


@sensitive_post_parameters("old_password", "new_password1", "new_password2")
@atomic_for_request_method
# in the general case this is done by Middleware but we're under /accounts/, so we need it back.
# not security-critical because we simply get a failure on request.user if this wasn't there, but still the right thing.
@login_required
def change_password(request):
    user = request.user
    if request.method == 'POST':
        form = PasswordChangeForm(user, request.POST)

        if form.is_valid():
            form.save()
            update_session_auth_hash(request, user)
            messages.success(request, _("Password updated"))
            return redirect('preferences')

    else:
        form = PasswordChangeForm(user)

    return render(request, 'users/change_password.html', {
        'form': form,
    })


DEBUG_CONTEXTS = {
    "confirm_email": {
        "site_title": get_settings().SITE_TITLE,
        "base_url": get_settings().BASE_URL + "/",
        "confirm_url": "http://example.com/confirm-email/1234567890abcdef",  # nonsense to avoid circular import
    },
    "reset_password_email": {
        "site_title": get_settings().SITE_TITLE,
        "base_url": get_settings().BASE_URL + "/",
        "reset_url": "http://example.com/reset-password/1234567890abcdef",  # nonsense to avoid circular import
    },
}


@atomic_for_request_method
def debug_email(request, template_name):
    return render(request, 'mails/' + template_name + ".html", DEBUG_CONTEXTS[template_name])
