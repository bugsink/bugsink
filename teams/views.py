from datetime import timedelta

from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model, login
from django.http import Http404, HttpResponseRedirect
from django.utils import timezone
from django.urls import reverse
from django.contrib import messages

from users.models import EmailVerification
from bugsink.app_settings import get_settings
from bugsink.decorators import login_exempt

from .models import Team, TeamMembership, TeamRole
from .forms import TeamMemberInviteForm
from .tasks import send_team_invite_email, send_team_invite_email_new_user

User = get_user_model()


def team_list(request):
    team_list = Team.objects.all()
    return render(request, 'teams/team_list.html', {
        'state_filter': 'mine',
        'team_list': team_list,
    })


def team_members(request, team_pk):
    # TODO: check if user is a member of the team and has permission to view this page
    team = Team.objects.get(id=team_pk)
    return render(request, 'teams/team_members.html', {
        'team': team,
        'members': team.teammembership_set.all().select_related('user'),
    })


def team_members_invite(request, team_pk):
    # TODO: check if user is a member of the team and has permission to view this page

    team = Team.objects.get(id=team_pk)

    user_must_exist = True  # TODO implement based on USER_REGISTRATION setting and how it compares to the current user
    user_must_exist = False

    if request.method == 'POST':
        form = TeamMemberInviteForm(user_must_exist, request.POST)

        if form.is_valid():
            # because we do validation in the form (which takes user_must_exist as a param), we know we can create the
            # user if needed if this point is reached.
            email = form.cleaned_data['email']

            user, user_created = User.objects.get_or_create(
                email=email, defaults={'username': email, 'is_active': False})

            if user.is_active:
                send_team_invite_email.delay(email, team_pk)
            else:
                # this happens for new (in this view) users, but also for users who have been invited before but have
                # not yet accepted the invite. In the latter case, we just send a fresh email
                verification = EmailVerification.objects.create(user=user, email=user.username)
                send_team_invite_email_new_user.delay(email, team_pk, verification.token)

            _, membership_created = TeamMembership.objects.get_or_create(team=team, user=user, defaults={
                'role': form.cleaned_data['role'],
                'accepted': False,
            })

            if membership_created:
                messages.success(request, f"Invitation sent to {email}")
            else:
                messages.success(
                    request, f"Invitation resent to {email} (it was previously sent and we just sent it again)")

            if request.POST.get('action') == "invite_and_add_another":
                return redirect('team_members_invite', team_pk=team_pk)

            # I think this is enough feedback, as the user will just show up there
            return redirect('team_members', team_pk=team_pk)

    else:
        form = TeamMemberInviteForm(user_must_exist)

    return render(request, 'teams/team_members_invite.html', {
        'team': team,
        'form': form,
    })


@login_exempt  # no login is required, the token is what identifies the user
def team_members_accept_new_user(request, team_pk, token):
    # There is a lot of overlap with the email-verification flow here; security-wise we make the same assumptions as we
    # do over there, namely: access to email implies control over the account. This is also the reason we reuse that
    # app's `EmailVerification` model.

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
    if not user.has_usable_password() or not user.is_active:
        # NOTE: we make the had assumption here that users without a password can self-upgrade to become users with a
        # password. In the future (e.g. LDAP) this may not be what we want, and we'll have to implement a separate field
        # to store whether we're dealing with "created by email invite, password must still be set" or "created by
        # external system, password is managed externally". For now, we're good.
        # In the above we take the (perhaps redundant) approach of checking for either of 2 login-blocking conditions.

        return HttpResponseRedirect(reverse("set_password", kwargs={"token": token}) + "?next=" + reverse(
            team_members_accept, kwargs={"team_pk": team_pk})
        )
        # TODO: thoughts about showing the user what's going on.

    # the above "set_password" branch is the "main flow"/"whole point" of this view: auto-login using a token and
    # subsequent password-set because no user exists yet. However, it is possible that a user ends up here while already
    # having registered, e.g. when multiple invites have been sent in a row. In that case, the password-setting may be
    # skipped and we can just skip straight to the actual team-accept

    # TODO: check how this interacts with login_[not]_required.... my thinking is: we should just do a login() here
    # and should be OK; but this needs to be tested.
    login(request, user)
    return team_members_accept(request, team_pk)


def team_members_accept(request, team_pk):
    team = Team.objects.get(id=team_pk)
    membership = TeamMembership.objects.get(team=team, user=request.user)

    if membership.accepted:
        return redirect()  # TODO same question as below

    if request.method == 'POST':
        # no need for a form, it's just a pair of buttons
        if request.POST["action"] == "decline":
            membership.delete()
            return redirect("home")

        if request.POST["action"] == "accept":
            membership.accepted = True
            membership.save()
            return redirect()  # TODO what's a good thing to show for any given team? we don't have that yet I think.

        raise Http404("Invalid action")

    return render(request, "teams/team_members_accept.html", {"team": team, "membership": membership})
