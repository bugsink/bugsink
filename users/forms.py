import urllib.parse

from django import forms
from django.urls import reverse
from django.contrib.auth.forms import UserCreationForm as BaseUserCreationForm, SetPasswordForm as BaseSetPasswordForm
from django.core.validators import EmailValidator
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.contrib.auth import password_validation
from django.forms import ModelForm
from django.utils.html import escape, mark_safe


TRUE_FALSE_CHOICES = (
    (True, 'Yes'),
    (False, 'No')
)


def _(x):
    # dummy gettext
    return x


UserModel = get_user_model()


class UserCreationForm(BaseUserCreationForm):
    # Our UserCreationForm is the place where the "use email for usernames" logic is implemented.
    # We could instead push such logic in the model, and do it more thoroughly (i.e. remove either field, and point the
    # USERNAME_FIELD to the other). But I'm not sure that this is the most future-proof way forward. In particular,
    # external systems (AD, OAuth, etc.) may have 2 fields rather than 1.

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


class UserEditForm(ModelForm):
    # See notes in UserCreationForm about the "use email for usernames" logic; it's the same here.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].validators = [EmailValidator()]
        self.fields['username'].label = "Email"

        self.fields['username'].help_text = None  # "Email" is descriptive enough

    class Meta:
        model = UserModel
        fields = ("username",)

    def clean_username(self):
        if UserModel.objects.exclude(pk=self.instance.pk).filter(username=self.cleaned_data['username']).exists():
            raise ValidationError(mark_safe("This email is already registered by another user."))
        return self.cleaned_data['username']

    def save(self, **kwargs):
        commit = kwargs.pop("commit", True)
        user = super().save(commit=False)
        user.email = user.username
        if commit:
            user.save()
        return user


class ResendConfirmationForm(forms.Form):
    email = forms.EmailField()


class RequestPasswordResetForm(forms.Form):
    email = forms.EmailField()

    def clean_email(self):
        email = self.cleaned_data['email']
        if not UserModel.objects.filter(username=email).exists():
            # Many sites say "if the email is registered, we've sent you an email with a password reset link" instead.
            # The idea is not to leak information about which emails are registered. But in our setup we're already
            # leaking that information in the signup form. At least for now, I'm erring on the side of
            # user-friendliness. see https://news.ycombinator.com/item?id=33718202
            raise ValidationError("This email is not registered.")

        return email


class SetPasswordForm(BaseSetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].help_text = "At least 8 characters"

        self.fields['new_password2'].help_text = None  # "Confirm password" is descriptive enough


class PreferencesForm(ModelForm):
    # I haven't gotten a decent display for checkboxes in forms yet; the quickest hack around this is a ChoiceField
    send_email_alerts = forms.ChoiceField(
        label=_("Send email alerts"), choices=TRUE_FALSE_CHOICES, required=False, widget=forms.Select())

    class Meta:
        model = UserModel
        fields = ("send_email_alerts",)
