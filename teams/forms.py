from django import forms
from django.contrib.auth import get_user_model
from django.template.defaultfilters import yesno

from .models import TeamRole, TeamMembership, Team

User = get_user_model()


class TeamMemberInviteForm(forms.Form):
    email = forms.EmailField(label='Email', required=True)
    role = forms.ChoiceField(
        label='Role', choices=TeamRole.choices, required=True, initial=TeamRole.MEMBER, widget=forms.RadioSelect)

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


class MyTeamMembershipForm(forms.ModelForm):
    """Edit _your_ TeamMembership, i.e. email-settings, and role only for admins"""

    class Meta:
        model = TeamMembership
        fields = ["send_email_alerts", "role"]

    def __init__(self, *args, **kwargs):
        edit_role = kwargs.pop("edit_role")
        super().__init__(*args, **kwargs)
        assert self.instance is not None, "This form is only implemented for editing"

        if not edit_role:
            del self.fields['role']

        global_send_email_alerts = self.instance.user.send_email_alerts
        empty_label = "User-default (%s)" % yesno(global_send_email_alerts).capitalize()
        self.fields['send_email_alerts'].empty_label = empty_label
        self.fields['send_email_alerts'].widget.choices[0] = ("unknown", empty_label)


class TeamMembershipForm(forms.ModelForm):
    """Edit TeamMembership for not-you, i.e. set a role but not email-settings"""

    class Meta:
        model = TeamMembership
        fields = ["role"]


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "visibility"]
