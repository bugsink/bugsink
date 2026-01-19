from django import forms
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.db.models import Sum

from bugsink.utils import assert_
from bugsink.app_settings import get_settings
from teams.models import TeamMembership
from bsmain.utils import yesno

from .models import Project, ProjectMembership, ProjectRole

User = get_user_model()


class ProjectMemberInviteForm(forms.Form):
    email = forms.EmailField(label=_('Email'), required=True)
    role = forms.ChoiceField(
        label=_('Role'), choices=ProjectRole.choices, required=True, initial=ProjectRole.MEMBER,
        widget=forms.RadioSelect)

    def __init__(self, user_must_exist, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_must_exist = user_must_exist
        if user_must_exist:
            self.fields['email'].help_text = "The user must already exist in the system"

    def clean_email(self):
        email = self.cleaned_data['email']

        if self.user_must_exist and not User.objects.filter(email=email).exists():
            raise forms.ValidationError('No user with this email address in the system.')

        return email


class MyProjectMembershipForm(forms.ModelForm):
    """Edit _your_ ProjectMembership, i.e. email-settings, and role only for admins"""

    class Meta:
        model = ProjectMembership
        fields = ["send_email_alerts", "role"]

    def __init__(self, *args, **kwargs):
        edit_role = kwargs.pop("edit_role")
        super().__init__(*args, **kwargs)
        assert_(self.instance is not None, "This form is only implemented for editing")

        if not edit_role:
            del self.fields['role']

        try:
            tm = TeamMembership.objects.get(team=self.instance.project.team, user=self.instance.user)
            if tm.send_email_alerts is not None:
                sea_defined_at = "team membership"
                sea_default = tm.send_email_alerts
            else:
                sea_defined_at = "user"
                sea_default = self.instance.user.send_email_alerts

        except TeamMembership.DoesNotExist:
            sea_defined_at = "user"
            sea_default = self.instance.user.send_email_alerts

        empty_label = _('Default (%s, as per %s settings)') % (yesno(sea_default).capitalize(), sea_defined_at)
        self.fields['send_email_alerts'].empty_label = empty_label
        self.fields['send_email_alerts'].widget.choices[0] = ("unknown", empty_label)


class ProjectMembershipForm(forms.ModelForm):
    """Edit ProjectMembership for not-you, i.e. set a role but not email-settings"""

    class Meta:
        model = TeamMembership
        fields = ["role"]


class ProjectForm(forms.ModelForm):

    dsn = forms.CharField(label="DSN", disabled=True)

    def __init__(self, *args, **kwargs):
        team_qs = kwargs.pop("team_qs", None)
        super().__init__(*args, **kwargs)

        self.fields["retention_max_event_count"].help_text = _("The maximum number of events to store before evicting.")

        if get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT is not None:
            self.fields["retention_max_event_count"].initial = get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT

        if self.instance is not None and self.instance.pk is not None:
            # for editing, we disallow changing the team. consideration: it's somewhat hard to see what the consequences
            # for authorization are (from the user's perspective).
            del self.fields["team"]

            # for editing, the DSN is availabe, but read-only
            self.fields["dsn"].initial = self.instance.dsn
            self.fields["dsn"].label = _("DSN (read-only)")
            href = reverse('project_sdk_setup', kwargs={'project_pk': self.instance.pk})

            self.fields["dsn"].help_text = format_html(
                _("Use the DSN to {link}."),
                link=format_html('<a href="{}" class="text-cyan-800 font-bold">{}</a>', href, _("set up the SDK")),
            )

            # if we ever push slug to the form, editing it should probably be disallowed as well (but mainly because it
            # has consequences on the issue's short identifier)
            # del self.fields["slug"]
        else:
            # for creation, we allow changing the team; (as an additional improvement we _could_ consider hiding this
            # field if there is only one team, and especially if SINGLE_TEAM is True, but being explicit is fine too as
            # it suggests at least somewhere that teams are a thing)
            self.fields["team"].queryset = team_qs
            if team_qs.count() == 0:
                href = reverse("team_new")
                self.fields["team"].help_text = format_html(
                    "{}{}", _("You don't have any teams yet; "),
                    format_html('<a href="{}" class="text-cyan-800 font-bold">{}</a>', href, _("Create a team first.")))

            elif team_qs.count() == 1:
                self.fields["team"].initial = team_qs.first()

            # for creation, we don't show the DSN field
            del self.fields["dsn"]

    class Meta:
        model = Project

        fields = ["team", "name", "visibility", "retention_max_event_count"]
        # "slug",  <= for now, we just do this in the model; if we want to do it in the form, I would want to have some
        # JS in place like we have in the admin. django/contrib/admin/static/admin/js/prepopulate.js is an example of
        # how Django does this (but it requires JQuery)

        # "alert_on_new_issue", "alert_on_regression", "alert_on_unmute" later

    def clean_retention_max_event_count(self):
        retention_max_event_count = self.cleaned_data['retention_max_event_count']

        if get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT is not None:
            if retention_max_event_count > get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT:
                raise forms.ValidationError("The maximum allowed retention per project is %d events." %
                                            get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT)

        if get_settings().MAX_RETENTION_EVENT_COUNT is not None:
            sum_of_others = Project.objects.exclude(pk=self.instance.pk).aggregate(
                total=Sum('retention_max_event_count'))['total'] or 0
            budget_left = max(get_settings().MAX_RETENTION_EVENT_COUNT - sum_of_others, 0)

            if retention_max_event_count > budget_left:
                raise forms.ValidationError("The maximum allowed retention for this project is %d events (based on the "
                                            "installation-wide max of %d events)." % (
                                                budget_left,
                                                get_settings().MAX_RETENTION_EVENT_COUNT))

        return retention_max_event_count
