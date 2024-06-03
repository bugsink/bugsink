from django import forms
from django.contrib.auth import get_user_model

from .models import TeamRole

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
