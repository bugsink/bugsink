from datetime import timedelta

from django.shortcuts import render
from django.db import models
from django.shortcuts import redirect
from django.http import Http404, HttpResponseRedirect
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.contrib.auth import logout
from django.urls import reverse
from django.utils import timezone

from users.models import EmailVerification
from teams.models import TeamMembership, Team, TeamRole

from bugsink.app_settings import get_settings, CB_ANYBODY, CB_MEMBERS, CB_ADMINS
from bugsink.decorators import login_exempt, atomic_for_request_method

from .models import Project, ProjectMembership, ProjectRole, ProjectVisibility
from .forms import ProjectMembershipForm, MyProjectMembershipForm, ProjectMemberInviteForm, ProjectForm
from .tasks import send_project_invite_email, send_project_invite_email_new_user


User = get_user_model()


@atomic_for_request_method
def project_list(request, ownership_filter=None):
    my_memberships = ProjectMembership.objects.filter(user=request.user)
    my_team_memberships = TeamMembership.objects.filter(user=request.user)

    my_projects = Project.objects.filter(projectmembership__in=my_memberships).order_by('name').distinct()
    my_teams_projects = \
        Project.objects \
        .filter(team__teammembership__in=my_team_memberships) \
        .exclude(projectmembership__in=my_memberships) \
        .order_by('name').distinct()

    if request.user.is_superuser:
        # superusers can see all project, even hidden ones
        other_projects = Project.objects \
            .exclude(projectmembership__in=my_memberships) \
            .exclude(team__teammembership__in=my_team_memberships) \
            .order_by('name').distinct()
    else:
        other_projects = Project.objects \
            .exclude(projectmembership__in=my_memberships) \
            .exclude(team__teammembership__in=my_team_memberships) \
            .exclude(visibility=ProjectVisibility.TEAM_MEMBERS) \
            .order_by('name').distinct()

    if ownership_filter is None:
        if my_projects.exists():
            return redirect('project_list_mine')
        if my_teams_projects.exists():
            return redirect('project_list_teams')
        if other_projects.exists():
            return redirect('project_list_other')
        return redirect('project_list_mine')  # if nothing to show, might as well show your own

    if request.method == 'POST':
        full_action_str = request.POST.get('action')
        action, project_pk = full_action_str.split(":", 1)
        if action == "leave":
            ProjectMembership.objects.filter(project=project_pk, user=request.user.id).delete()
        elif action == "join":
            project = Project.objects.get(id=project_pk)
            if not project.is_joinable(user=request.user) and not request.user.is_superuser:
                raise PermissionDenied("This project is not joinable")

            messages.success(request, 'You have joined the project "%s"' % project.name)
            ProjectMembership.objects.create(
                project_id=project_pk, user_id=request.user.id, role=ProjectRole.MEMBER, accepted=True)
            return redirect('project_member_settings', project_pk=project_pk, user_pk=request.user.id)

    if ownership_filter == "mine":
        base_qs = my_projects
    elif ownership_filter == "teams":
        base_qs = my_teams_projects
    elif ownership_filter == "other":
        base_qs = other_projects
    else:
        raise ValueError(f"Invalid ownership_filter: {ownership_filter}")

    project_list = base_qs.annotate(
        open_issue_count=models.Count('issue', filter=models.Q(issue__is_resolved=False, issue__is_muted=False)),
        member_count=models.Count(
            'projectmembership', distinct=True, filter=models.Q(projectmembership__accepted=True)),
    ).select_related('team')

    if ownership_filter == "mine":
        # Perhaps there's some Django-native way of doing this, but I can't figure it out soon enough, and this also
        # works:
        my_memberships_dict = {m.project_id: m for m in my_memberships}

        project_list_2 = []
        for project in project_list:
            project.member = my_memberships_dict.get(project.id)
            project_list_2.append(project)
        project_list = project_list_2

    return render(request, 'projects/project_list.html', {
        'can_create':
            request.user.is_superuser or TeamMembership.objects.filter(user=request.user, role=TeamRole.ADMIN).exists(),
        'ownership_filter': ownership_filter,
        'project_list': project_list,
    })


@atomic_for_request_method
def project_new(request):
    if not (request.user.is_superuser or TeamMembership.objects.filter(user=request.user,
            role=TeamRole.ADMIN).exists()):
        raise PermissionDenied("You need to be a team admin to create a project")

    if get_settings().SINGLE_TEAM and Team.objects.count() == 0:
        # we just create the Single Team if it doesn't exist yet (whatever user triggers this doesn't matter)
        Team.objects.create(name="Single Team")

    if request.user.is_superuser:
        team_qs = Team.objects.all()
    else:
        my_admin_memberships = TeamMembership.objects.filter(user=request.user, role=TeamRole.ADMIN, accepted=True)
        team_qs = Team.objects.filter(teammembership__in=my_admin_memberships).distinct()

    if request.method == 'POST':
        form = ProjectForm(request.POST, team_qs=team_qs)

        if form.is_valid():
            project = form.save()

            # the user who creates the project is automatically an (accepted) admin of the project
            ProjectMembership.objects.create(project=project, user=request.user, role=ProjectRole.ADMIN, accepted=True)
            return redirect('project_sdk_setup', project_pk=project.id)

    else:
        form = ProjectForm(team_qs=team_qs)

    return render(request, 'projects/project_new.html', {
        'form': form,
    })


def _check_project_admin(project, user):
    if not user.is_superuser and \
       not ProjectMembership.objects.filter(
            project=project, user=user, role=ProjectRole.ADMIN, accepted=True).exists() and \
       not TeamMembership.objects.filter(team=project.team, user=user, role=TeamRole.ADMIN, accepted=True).exists():
        raise PermissionDenied("You are not an admin of this project")


@atomic_for_request_method
def project_edit(request, project_pk):
    project = Project.objects.get(id=project_pk)

    _check_project_admin(project, request.user)

    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)

        if form.is_valid():
            form.save()
            return redirect('project_members', project_pk=project.id)

    else:
        form = ProjectForm(instance=project)

    return render(request, 'projects/project_edit.html', {
        'project': project,
        'form': form,
    })


@atomic_for_request_method
def project_members(request, project_pk):
    project = Project.objects.get(id=project_pk)
    _check_project_admin(project, request.user)

    if request.method == 'POST':
        full_action_str = request.POST.get('action')
        action, user_id = full_action_str.split(":", 1)
        if action == "remove":
            ProjectMembership.objects.filter(project=project_pk, user=user_id).delete()
        elif action == "reinvite":
            user = User.objects.get(id=user_id)
            _send_project_invite_email(user, project_pk)
            messages.success(request, f"Invitation resent to {user.email}")

    return render(request, 'projects/project_members.html', {
        'project': project,
        'members': project.projectmembership_set.all().select_related('user'),
    })


def _send_project_invite_email(user, project_pk):
    """Send an email to a user inviting them to a project; (for new users this includes the email-verification link)"""
    if user.is_active:
        send_project_invite_email.delay(user.email, project_pk)
    else:
        # this happens for new (in this view) users, but also for users who have been invited before but have
        # not yet accepted the invite. In the latter case, we just send a fresh email
        verification = EmailVerification.objects.create(user=user, email=user.username)
        send_project_invite_email_new_user.delay(user.email, project_pk, verification.token)


@atomic_for_request_method
def project_members_invite(request, project_pk):
    # NOTE: project-member invite is just that: a direct invite to a project. If you want to also/instead invite someone
    # to a team, you need to just do that instead.

    project = Project.objects.get(id=project_pk)

    _check_project_admin(project, request.user)

    if get_settings().USER_REGISTRATION in [CB_ANYBODY, CB_MEMBERS]:
        user_must_exist = False
    elif get_settings().USER_REGISTRATION == CB_ADMINS and request.user.is_superuser:
        user_must_exist = False
    else:
        user_must_exist = True

    if request.method == 'POST':
        form = ProjectMemberInviteForm(user_must_exist, request.POST)

        if form.is_valid():
            # because we do validation in the form (which takes user_must_exist as a param), we know we can create the
            # user if needed if this point is reached.
            email = form.cleaned_data['email']

            user, user_created = User.objects.get_or_create(
                email=email, defaults={'username': email, 'is_active': False})

            _send_project_invite_email(user, project_pk)

            _, membership_created = ProjectMembership.objects.get_or_create(project=project, user=user, defaults={
                'role': form.cleaned_data['role'],
                'accepted': False,
            })

            if membership_created:
                messages.success(request, f"Invitation sent to {email}")
            else:
                messages.success(
                    request, f"Invitation resent to {email} (it was previously sent and we just sent it again)")

            if request.POST.get('action') == "invite_and_add_another":
                return redirect('project_members_invite', project_pk=project_pk)

            # I think this is enough feedback, as the user will just show up there
            return redirect('project_members', project_pk=project_pk)

    else:
        form = ProjectMemberInviteForm(user_must_exist)

    return render(request, 'projects/project_members_invite.html', {
        'project': project,
        'form': form,
    })


@atomic_for_request_method
def project_member_settings(request, project_pk, user_pk):
    try:
        your_membership = ProjectMembership.objects.get(project=project_pk, user=request.user)
    except ProjectMembership.DoesNotExist:
        raise PermissionDenied("You are not a member of this project")

    if not your_membership.accepted:
        return redirect("project_members_accept", project_pk=project_pk)

    this_is_you = str(user_pk) == str(request.user.id)
    if not this_is_you:
        _check_project_admin(Project.objects.get(id=project_pk), request.user)

        membership = ProjectMembership.objects.get(project=project_pk, user=user_pk)
        create_form = lambda data: ProjectMembershipForm(data, instance=membership)  # noqa
    else:
        edit_role = your_membership.role == ProjectRole.ADMIN or request.user.is_superuser
        create_form = lambda data: MyProjectMembershipForm(data=data, instance=your_membership, edit_role=edit_role)  # noqa

    if request.method == 'POST':
        form = create_form(request.POST)

        if form.is_valid():
            form.save()
            if this_is_you:
                # assumption (not always true): when editing yourself, you came from the project list not the project
                # members
                return redirect('project_list')
            return redirect('project_members', project_pk=project_pk)

    else:
        form = create_form(None)

    return render(request, 'projects/project_member_settings.html', {
        'this_is_you': this_is_you,
        'user': User.objects.get(id=user_pk),
        'project': Project.objects.get(id=project_pk),
        'form': form,
    })


@atomic_for_request_method
@login_exempt  # no login is required, the token is what identifies the user
def project_members_accept_new_user(request, project_pk, token):
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

        return HttpResponseRedirect(reverse("reset_password", kwargs={"token": token}) + "?next=" + reverse(
            project_members_accept, kwargs={"project_pk": project_pk})
        )

    # the above "set_password" branch is the "main flow"/"whole point" of this view: auto-login using a token and
    # subsequent password-set because no (active) user exists yet. However, it is possible that a user ends up here
    # while already having completed registration, e.g. when multiple invites have been sent in a row. In that case, the
    # password-setting may be skipped and we can just skip straight to the actual project-accept.

    # to remove some of the confusion mentioned in "project_members_accept", we at least log you out if the verification
    # you've clicked on is for a different user than the one you're logged in as.
    if request.user.is_authenticated and request.user != user:
        logout(request)

    # In this case, we clean up the no-longer-required verification object (we make somewhat of an exception to the
    # "don't change stuff on GET" rule, because it's immaterial here).
    verification.delete()

    # And we just redirect to the regular "accept" page. No auto-login, because we're not in a POST request here. (at a
    # small cost in UX in the case you reach this page in a logged-out state).
    return redirect("project_members_accept", project_pk=project_pk)


@atomic_for_request_method
def project_members_accept(request, project_pk):
    # NOTE: in principle it is confusingly possible to reach this page while logged in as user A, while having been
    # invited as user B. Security-wise this is fine, but UX-wise it could be confusing. However, I'm in the assumption
    # here that normal people (i.e. not me) don't have multiple accounts, so I'm not going to bother with this.

    project = Project.objects.get(id=project_pk)
    membership = ProjectMembership.objects.get(project=project, user=request.user)

    if membership.accepted:
        # i.e. the user has already accepted the invite, we just silently redirect as if they had just done so
        return redirect("project_member_settings", project_pk=project_pk, user_pk=request.user.id)

    if request.method == 'POST':
        # no need for a form, it's just a pair of buttons
        if request.POST["action"] == "decline":
            membership.delete()
            return redirect("home")

        if request.POST["action"] == "accept":
            membership.accepted = True
            membership.save()
            return redirect("project_member_settings", project_pk=project_pk, user_pk=request.user.id)

        raise Http404("Invalid action")

    return render(request, "projects/project_members_accept.html", {"project": project, "membership": membership})


@atomic_for_request_method
def project_sdk_setup(request, project_pk, platform=""):
    project = Project.objects.get(id=project_pk)

    if not request.user.is_superuser and not ProjectMembership.objects.filter(project=project, user=request.user,
                                                                              accepted=True).exists():
        raise PermissionDenied("You are not a member of this project")

    # NOTE about lexers:: I have bugsink/pyments_extensions; but the platforms mentioned there don't necessarily map to
    # what I will make selectable here. "We'll see" whether yet another lookup dict will be needed.

    assert platform in ["", "python", "javascript", "php"]

    template_name = "projects/project_sdk_setup%s.html" % ("_" + platform if platform else "")

    return render(request, template_name, {
        "project": project,
        "dsn": project.dsn,
    })
