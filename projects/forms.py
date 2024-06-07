from django import forms
from django.contrib.auth import get_user_model
from django.template.defaultfilters import yesno

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

        # True as default ... same TODO as in teams/forms.py
        try:
            tm = TeamMembership.objects.get(team=self.instance.project.team, user=self.instance.user)
            team_send_email_alerts = tm.send_email_alerts if tm.send_email_alerts is not None else True
        except TeamMembership.DoesNotExist:
            team_send_email_alerts = True

        empty_label = "Team-default (currently: %s)" % yesno(team_send_email_alerts)
        self.fields['send_email_alerts'].empty_label = empty_label
        self.fields['send_email_alerts'].widget.choices[0] = ("unknown", empty_label)


class ProjectForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        team_qs = kwargs.pop("team_qs", None)
        super().__init__(*args, **kwargs)
        if self.instance is not None and self.instance.pk is not None:
            # for editing, we disallow changing the team. consideration: it's somewhat hard to see what the consequences
            # for authorization are (from the user's perspective).
            del self.fields["team"]

            # if we ever push slug to the form, editing it should probably be disallowed as well (but mainly because it
            # has consequences on the issue's short identifier)
            # del self.fields["slug"]
        else:
            self.fields["team"].queryset = team_qs

    class Meta:
        model = Project

        fields = ["team", "name", "visibility"]
        # "slug",  <= for now, we just do this in the model; if we want to do it in the form, I would want to have some
        # JS in place like we have in the admin. django/contrib/admin/static/admin/js/prepopulate.js is an example of
        # how Django does this (but it requires JQuery)

        # "alert_on_new_issue", "alert_on_regression", "alert_on_unmute" later
