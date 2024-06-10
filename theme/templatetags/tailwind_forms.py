from django import template


register = template.Library()


@register.inclusion_tag('tailwind_forms/formfield.html')
def tailwind_formfield(formfield):
    return {'formfield': formfield}
