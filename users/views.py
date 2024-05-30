from datetime import timedelta

from django.contrib.auth import login
from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from django.http import Http404
from django.utils import timezone

from bugsink.app_settings import get_settings, CB_ANYBODY

from .forms import UserCreationForm
from .models import EmailVerification
from .tasks import send_confirm_email


UserModel = get_user_model()


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


def confirm_email(request, token):
    # clean up expired tokens; doing this on every request is just fine, it saves us from having to run a cron job-like
    EmailVerification.objects.filter(
        created_at__lt=timezone.now() - timedelta(get_settings().USER_REGISTRATION_VERIFY_EMAIL_EXPIRY)).delete()

    try:
        verification = EmailVerification.objects.get(token=token)
    except EmailVerification.DoesNotExist:
        # good enough (though a special page might be prettier)
        raise Http404("Invalid or expired token")

    verification.user.is_active = True
    verification.user.save()
    verification.delete()

    # I don't want to log the user in based on the verification email alone; although in principle doing so would not
    # be something fundamentally more insecure than what we do in the password-reset loop (in both cases access to the
    # email is enough to get access to Bugsink), better to err on the side of security.
    # If we ever want to introduce a more user-friendly approach, we could make automatic login dependent on some
    # (signed) cookie that's being set when registring. i.e.: if you've just recently entered your password in the same
    # browser, it works.
    # login(request, verification.user)

    return render(request, "users/email_confirmed.html")


DEBUG_CONTEXTS = {
    "confirm_email": {
        "site_title": get_settings().SITE_TITLE,
        "base_url": get_settings().BASE_URL + "/",
        "confirm_url": "http://example.com/confirm-email/1234567890abcdef",  # nonsense to avoid circular import
    },
}


def debug_email(request, template_name):
    return render(request, 'users/' + template_name + ".html", DEBUG_CONTEXTS[template_name])
