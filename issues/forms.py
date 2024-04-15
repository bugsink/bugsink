from django.forms import ModelForm

from .models import TurningPoint


class CommentForm(ModelForm):
    # note that we use about 5% of ModelForm functionality here... but "if it ain't broke don't fix it" :-)

    class Meta:
        model = TurningPoint
        fields = ['comment']
