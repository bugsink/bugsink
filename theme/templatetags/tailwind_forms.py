from django import template


register = template.Library()


@register.inclusion_tag('tailwind_forms/formfield.html')
def tailwind_formfield(formfield, implicit=False):
    # we just monkey-patch the class attr. if (i.e. as long as) it works, it ain't stupid
    if not formfield:
        return {"formfield": None}

    if formfield.errors:
        formfield.field.widget.attrs['class'] = "input input-bordered input-error w-full"
    else:
        formfield.field.widget.attrs['class'] = "input input-bordered w-full"

    widget_name = formfield.field.widget.__class__.__name__.lower()
    if "select" in widget_name:
        formfield.field.widget.attrs['class'] = formfield.field.widget.attrs['class'].replace("input input-bordered", "select select-bordered")
        if formfield.errors:
            formfield.field.widget.attrs['class'] = formfield.field.widget.attrs['class'].replace("input-error", "select-error")
    elif "checkbox" in widget_name:
        formfield.field.widget.attrs['class'] = "checkbox checkbox-primary"
    elif "textarea" in widget_name:
        formfield.field.widget.attrs['class'] = formfield.field.widget.attrs['class'].replace("input input-bordered", "textarea textarea-bordered")
        if formfield.errors:
            formfield.field.widget.attrs['class'] = formfield.field.widget.attrs['class'].replace("input-error", "textarea-error")

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
