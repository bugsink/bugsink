from django import template


register = template.Library()


@register.inclusion_tag('tailwind_forms/formfield.html')
def tailwind_formfield(formfield, implicit=False):
    # we just monkey-patch the class attr. if (i.e. as long as) it works, it ain't stupid
    if not formfield:
        return {"formfield": None}

    if formfield.errors:
        formfield.field.widget.attrs['class'] = "bg-red-50"
    else:
        formfield.field.widget.attrs['class'] = "bg-slate-50"
    formfield.field.widget.attrs['class'] += " pl-4 py-2 md:py-4 focus:outline-none w-full"

    if implicit:
        formfield.field.widget.attrs['placeholder'] = formfield.label

    return {
        'formfield': formfield,
        'implicit': implicit,
    }


@register.inclusion_tag('tailwind_forms/formfield.html')
def tailwind_formfield_implicit(formfield):
    # implicit meaning: the label is rendered as a placeholder. This only works for text inputs and fire-once (i.e. the
    # first time the form is rendered)
    return tailwind_formfield(formfield, True)
