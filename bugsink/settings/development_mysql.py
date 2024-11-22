from .development import *  # noqa
from .development import DATABASES


DATABASES['default'] = {
    'ENGINE': 'django.db.backends.mysql',
    'NAME': 'bugsink',
    'USER': 'bugsink',
    'PASSWORD': 'bugsink',
}
