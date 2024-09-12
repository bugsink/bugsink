from django.forms import ModelForm

from .models import TurningPoint


class CommentForm(ModelForm):
    # note that we use about 5% of ModelForm functionality here... but "if it ain't broke don't fix it" :-)

    class Meta:
        model = TurningPoint
        fields = ['comment']


class IssueAdminForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for fieldname in self.fields:
            self.fields[fieldname].strip = False

    def clean_fixed_at(self):
        fixed_at = self.cleaned_data.get('fixed_at')
        fixed_at = fixed_at.replace("\r", "")
        return fixed_at

    def clean_events_at(self):
        events_at = self.cleaned_data.get('events_at')
        events_at = events_at.replace("\r", "")
        return events_at
