from django.forms import ModelForm

from .models import MessagingServiceConfig


class MessagingServiceConfigForm(ModelForm):

    def __init__(self, project, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project

    class Meta:
        model = MessagingServiceConfig
        fields = ["display_name", "kind"]

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.project = self.project
        if commit:
            instance.save()
        return instance
