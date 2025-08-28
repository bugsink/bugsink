from django.db import models

IGNORED_ATTRS = ['verbose_name', 'help_text']

original_deconstruct = models.Field.deconstruct


def new_deconstruct(self):
    # works around the non-fix of https://code.djangoproject.com/ticket/21498 (I don't agree with the reasoning that
    # "in principle any field could influence the database schema"; you must be _insane_ if verbose_name or help_text
    # actually do, and the cost of the migrations is real)
    # solution from https://stackoverflow.com/a/39801321/339144
    name, path, args, kwargs = original_deconstruct(self)
    for attr in IGNORED_ATTRS:
        kwargs.pop(attr, None)
    return name, path, args, kwargs


def monkey_patch_deconstruct():
    models.Field.deconstruct = new_deconstruct
