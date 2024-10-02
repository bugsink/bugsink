from datetime import timedelta

from django.contrib.auth import login
from django.shortcuts import render, redirect, reverse
from django.contrib.auth import get_user_model
from django.http import Http404
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test

from bugsink.app_settings import get_settings, CB_ANYBODY
from bugsink.decorators import atomic_for_request_method

from .forms import (
    UserCreationForm, ResendConfirmationForm, RequestPasswordResetForm, SetPasswordForm, PreferencesForm, UserEditForm)
from .models import EmailVerification
from .tasks import send_confirm_email, send_reset_email


UserModel = get_user_model()


@atomic_for_request_method
@user_passes_test(lambda u: u.is_superuser)
def user_list(request):
    users = UserModel.objects.all().order_by('username')

    if request.method == 'POST':
        full_action_str = request.POST.get('action')
        action, user_pk = full_action_str.split(":", 1)
        if action == "deactivate":
            user = UserModel.objects.get(pk=user_pk)
            user.is_active = False
            user.save()

            messages.success(request, 'User %s deactivated' % user.username)
            return redirect('user_list')

        if action == "activate":
            user = UserModel.objects.get(pk=user_pk)
            user.is_active = True
            user.save()

            messages.success(request, 'User %s activated' % user.username)
            return redirect('user_list')

    return render(request, 'users/user_list.html', {
        'users': users,
    })


@atomic_for_request_method
@user_passes_test(lambda u: u.is_superuser)
def user_edit(request, user_pk):
    user = UserModel.objects.get(pk=user_pk)
    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user)

        if form.is_valid():
            form.save()
            return redirect("user_list")

    else:
        form = UserEditForm(instance=user)

    return render(request, "users/user_edit.html", {"form": form})


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
        created_at__lt=timezone.now() - timedelta(get_settings().USER_REGISTRATION_VERIFY_EMAIL_EXPIRY)).delete()

    try:
        verification = EmailVerification.objects.get(token=token)
    except EmailVerification.DoesNotExist:
        # good enough (though a special page might be prettier)
        raise Http404("Invalid or expired token")

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
            user = UserModel.objects.get(username=form.cleaned_data['email'])
            if user.is_active:
                raise Http404("This email is already confirmed.")

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
            user = UserModel.objects.get(username=form.cleaned_data['email'])
            # if not user.is_active  no separate branch for this: password-reset implies email-confirmation

            # we reuse the EmailVerification model for password resets; security wise it doesn't matter, because the
            # visiting any link with the token implies control over the email account; and we have defined that such
            # control implies both verification and password-resetting.
            verification = EmailVerification.objects.create(user=user, email=user.username)
            send_reset_email.delay(user.username, verification.token)
            return render(request, "users/reset_password_email_sent.html", {"email": user.username})

    else:
        form = RequestPasswordResetForm()

    return render(request, "users/request_reset_password.html", {"form": form})


@atomic_for_request_method
def reset_password(request, token=None):
    # alternative name: set_password (because this one also works for initial setting of a password)

    # clean up expired tokens; doing this on every request is just fine, it saves us from having to run a cron
    # job-like thing
    EmailVerification.objects.filter(
        created_at__lt=timezone.now() - timedelta(get_settings().USER_REGISTRATION_VERIFY_EMAIL_EXPIRY)).delete()

    try:
        verification = EmailVerification.objects.get(token=token)
    except EmailVerification.DoesNotExist:
        # good enough (though a special page might be prettier)
        raise Http404("Invalid or expired token")

    user = verification.user
    next = request.POST.get("next", request.GET.get("next", reverse("home")))

    if request.method == 'POST':
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            user.is_active = True  # password-reset implies email-confirmation
            user.set_password(form.cleaned_data['new_password1'])
            user.save()

            verification.delete()

            login(request, verification.user)

            return redirect(next)

    else:
        form = SetPasswordForm(user)

    return render(request, "users/reset_password.html", {"form": form, "next": next})


@atomic_for_request_method
# in the general case this is done by Middleware but we're under /accounts/, so we need it back.
# not security-critical because we simply get a failure on request.user if this wasn't there, but still the right thing.
@login_required
def preferences(request):
    user = request.user
    if request.method == 'POST':
        form = PreferencesForm(request.POST, instance=user)

        if form.is_valid():
            form.save()
            messages.success(request, "Updated preferences")
            return redirect('preferences')

    else:
        form = PreferencesForm(instance=user)

    return render(request, 'users/preferences.html', {
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
