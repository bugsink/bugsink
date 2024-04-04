from django import template
register = template.Library()


@register.filter(name='items')
def items(value):
    """Just do value.items(); the reason to not just do value.items in the templatte that the latter will first do a
    dictionary lookup; if the dictionary contains an item with the key 'items', that will be returned which is
    definitely not what we want here. """
    try:
        return value.items()
    except AttributeError:
        # we still replicate the Django behavior of returning None if the value is not a dictionary
        return None


@register.filter(name='sorted_items')
def sorted_items(value):
    """As above, but return the items sorted by key."""
    try:
        return sorted(value.items())
    except AttributeError:
        return None


# the general version below doesn't work, because we don't auto-append function-execution for callables and possibly a
# whole bunch of other magic that Django does and we don't think about by default. I left it in as a starting point for
# a possible future, but for now I'm going with the thing we actually need (above)
# @register.filter(name='getattr')
# def _getattr(value, arg):
#     """Just do getattr(value, arg); the reason to not just do value.arg is that the latter will first do a dictionary
#     lookup; if the dictionary contains an item with the key 'arg', that will be returned, even if there is a
#     method/attribute of the same name.
#     """
#     return getattr(value, arg)
