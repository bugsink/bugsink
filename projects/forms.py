from django import forms
from django.contrib.auth import get_user_model
from django.template.defaultfilters import yesno
from django.urls import reverse

from teams.models import TeamMembership

from .models import Project, ProjectMembership, ProjectRole

User = get_user_model()


class ProjectMemberInviteForm(forms.Form):
    email = forms.EmailField(label='Email', required=True)
    role = forms.ChoiceField(
        label='Role', choices=ProjectRole.choices, required=True, initial=ProjectRole.MEMBER, widget=forms.RadioSelect)

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
        assert self.instance is not None, "This form is only implemented for editing"

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

        empty_label = 'Default (%s, as per %s settings)' % (yesno(sea_default).capitalize(), sea_defined_at)
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
        if self.instance is not None and self.instance.pk is not None:
            # for editing, we disallow changing the team. consideration: it's somewhat hard to see what the consequences
            # for authorization are (from the user's perspective).
            del self.fields["team"]

            # for editing, the DSN is availabe, but read-only
            self.fields["dsn"].initial = self.instance.dsn
            self.fields["dsn"].label = "DSN (read-only)"
            self.fields["dsn"].help_text = 'Use the DSN to <a href="' +\
                                           reverse('project_sdk_setup', kwargs={'project_pk': self.instance.pk}) +\
                                           '" class="text-cyan-800 font-bold">set up the SDK</a>.'

            # if we ever push slug to the form, editing it should probably be disallowed as well (but mainly because it
            # has consequences on the issue's short identifier)
            # del self.fields["slug"]
        else:
            # for creation, we allow changing the team; (as an additional improvement we _could_ consider hiding this
            # field if there is only one team, and especially if SINGLE_TEAM is True, but being explicit is fine too as
            # it suggests at least somewhere that teams are a thing)
            self.fields["team"].queryset = team_qs
            if team_qs.count() == 0:
                self.fields["team"].help_text = 'You don\'t have any teams yet; <a href="' +\
                                                reverse("team_new") +\
                                                '" class="text-cyan-800 font-bold">Create a team first.</a>'
            elif team_qs.count() == 1:
                self.fields["team"].initial = team_qs.first()

            # for creation, we don't show the DSN field
            del self.fields["dsn"]

    class Meta:
        model = Project

        fields = ["team", "name", "visibility"]
        # "slug",  <= for now, we just do this in the model; if we want to do it in the form, I would want to have some
        # JS in place like we have in the admin. django/contrib/admin/static/admin/js/prepopulate.js is an example of
        # how Django does this (but it requires JQuery)

        # "alert_on_new_issue", "alert_on_regression", "alert_on_unmute" later
