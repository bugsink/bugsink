import urllib.parse

from django import forms
from django.urls import reverse
from django.contrib.auth.forms import UserCreationForm as BaseUserCreationForm
from django.core.validators import EmailValidator
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.contrib.auth import password_validation
from django.forms import ModelForm
from django.utils.html import escape, mark_safe


UserModel = get_user_model()


class UserCreationForm(BaseUserCreationForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].validators = [EmailValidator()]
        self.fields['username'].label = "Email"

        self.fields['username'].help_text = None  # "Email" is descriptive enough

        # the other conditions will be "revealed" when you trip'em up. Arguably that's an UX anti-pattern, but so is
        # having too many instructions. I'm erring on assuming my users are smart enough to pick a good password
        # initially, and if they don't, at least they'll have only a single instruction to read. (bad password-pickers
        # are probably bad readers too)
        self.fields['password1'].help_text = "At least 8 characters"

        self.fields['password2'].help_text = None  # "Confirm password" is descriptive enough

    class Meta:
        model = UserModel
        fields = ("username",)

    def clean_username(self):
        if UserModel.objects.filter(username=self.cleaned_data['username'], is_active=False).exists():
            raise ValidationError(mark_safe(
                'This email is already registered but not yet confirmed. Please check your email for the confirmation '
                'link or <b><a href="' + reverse("resend_confirmation") + "?email=" +
                urllib.parse.quote(escape(self.cleaned_data['username'])) + '">request it again</a></b>.'))
        return self.cleaned_data['username']

    def _post_clean(self):
        # copy of django.contrib.auth.forms.UserCreationForm._post_clean; but with password1 instead of password2; I'd
        # say it's better UX to complain where the original error is made

        ModelForm._post_clean(self)  # commented out because we want to skip the direct superclass
        # Validate the password after self.instance is updated with form data
        # by super().
        password = self.cleaned_data.get("password1")
        if password:
            try:
                password_validation.validate_password(password, self.instance)
            except ValidationError as error:
                self.add_error("password1", error)

    def save(self, **kwargs):
        commit = kwargs.pop("commit", True)
        user = super().save(commit=False)
        user.email = user.username
        if commit:
            user.save()
        return user


class ResendConfirmationForm(forms.Form):
    email = forms.EmailField()
