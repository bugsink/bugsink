from django import forms
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.db.models import Sum

from bugsink.utils import assert_
from bugsink.app_settings import get_settings
from issues.grouping_mechanisms import GROUPING_TRANSITION_PERIOD, get_grouping_mechanism
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

    slug = forms.CharField(label="Slug", disabled=True)
    dsn = forms.CharField(label="DSN", disabled=True)

    def __init__(self, *args, **kwargs):
        team_qs = kwargs.pop("team_qs", None)
        super().__init__(*args, **kwargs)
        self.old_grouping_mechanism = None

        self.fields["retention_max_event_count"].help_text = _("The maximum number of events to store before evicting.")

        maxes = []
        if get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT is not None:
            maxes.append(get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT)
        if get_settings().MAX_RETENTION_EVENT_COUNT is not None:
            # pick an initial value that will leave some room for other projects
            maxes.append(get_settings().MAX_RETENTION_EVENT_COUNT // 5)
        if maxes:
            self.fields["retention_max_event_count"].initial = min(maxes)

        if self.instance is not None and self.instance.pk is not None:
            self.old_grouping_mechanism = self.instance.grouping_mechanism

            # for editing, we disallow changing the team. consideration: it's somewhat hard to see what the consequences
            # for authorization are (from the user's perspective).
            del self.fields["team"]

            # for editing, the slug is available, but read-only (editing affects the issue's short identifier)
            self.fields["slug"].initial = self.instance.slug
            self.fields["slug"].label = _("Slug (read-only)")

            # for editing, the DSN is availabe, but read-only
            self.fields["dsn"].initial = self.instance.dsn
            self.fields["dsn"].label = _("DSN (read-only)")
            href = reverse('project_sdk_setup', kwargs={'project_pk': self.instance.pk})

            self.fields["dsn"].help_text = format_html(
                _("Use the DSN to {link}."),
                link=format_html('<a href="{}" class="text-cyan-800 font-bold">{}</a>', href, _("set up the SDK")),
            )

            transition_ends_at = (
                self.instance.grouping_mechanism_upgraded_at + GROUPING_TRANSITION_PERIOD
                if self.instance.grouping_mechanism_upgraded_at is not None else None
            )
            if transition_ends_at is not None and timezone.now() <= transition_ends_at:
                previous_grouping_mechanism = get_grouping_mechanism(self.instance.previous_grouping_mechanism)
                self.fields["grouping_mechanism"].choices = [
                    (
                        value,
                        _("%(name)s -- previous, transitioning until %(date)s") % {
                            "name": label,
                            "date": timezone.localtime(transition_ends_at).strftime("%Y-%m-%d"),
                        } if value == previous_grouping_mechanism.identifier else label,
                    )
                    for value, label in self.fields["grouping_mechanism"].choices
                ]
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

            # for creation, we don't show the slug or DSN fields
            del self.fields["slug"]
            del self.fields["dsn"]

    class Meta:
        model = Project

        fields = ["team", "name", "visibility", "retention_max_event_count", "grouping_mechanism"]
        # slug is shown read-only via an explicit (declared) field for edit; creation auto-generates it on the model.
        # If we ever make slug editable, we'd want JS like django/contrib/admin/static/admin/js/prepopulate.js.

        # "alert_on_new_issue", "alert_on_regression", "alert_on_unmute" later

    def clean(self):
        cleaned_data = super().clean()

        # Checked here rather than left to validate_unique(), for 2 reasons: Django reports unique_together violations
        # as non-field errors, which our templates don't render, and it skips the check entirely when editing, because
        # the team field is not part of the form then.
        name = cleaned_data.get("name")
        team = cleaned_data.get("team") if "team" in self.fields else self.instance.team

        if name and team:
            others = Project.objects.filter(team=team, name=name)
            if self.instance.pk:
                others = others.exclude(pk=self.instance.pk)
            if others.exists():
                self.add_error("name", _("A project with this name already exists in this team."))

        return cleaned_data

    def clean_retention_max_event_count(self):
        retention_max_event_count = self.cleaned_data['retention_max_event_count']

        if self.instance and self.instance.pk:
            # skip validation / have better error message when the value is unchanged or decreased; otherwise one would
            # get "stuck" (have no more allowed edits, even for other values) after a budget decrease.
            grace = self.instance.retention_max_event_count
        else:
            grace = 0

        if get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT is not None:
            if retention_max_event_count > max(get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT, grace):
                raise forms.ValidationError("The maximum allowed retention per project is %d events." %
                                            get_settings().MAX_RETENTION_PER_PROJECT_EVENT_COUNT)

        if get_settings().MAX_RETENTION_EVENT_COUNT is not None:
            sum_of_others = Project.objects.exclude(pk=self.instance.pk).aggregate(
                total=Sum('retention_max_event_count'))['total'] or 0
            budget_left = max(get_settings().MAX_RETENTION_EVENT_COUNT - sum_of_others, 0, grace)

            if retention_max_event_count > budget_left:
                # grace not mentioned explicitly here as a reason for "why so high" but that's ok.
                raise forms.ValidationError("The maximum allowed retention for this project is %d events (based on the "
                                            "installation-wide max of %d events)." % (
                                                budget_left,
                                                get_settings().MAX_RETENTION_EVENT_COUNT))

        return retention_max_event_count

    def save(self, commit=True):
        if self.old_grouping_mechanism is not None:
            new_grouping_mechanism = self.cleaned_data["grouping_mechanism"]
            if new_grouping_mechanism != self.old_grouping_mechanism:
                self.instance.previous_grouping_mechanism = self.old_grouping_mechanism
                self.instance.grouping_mechanism_upgraded_at = timezone.now()

        return super().save(commit=commit)
