from rest_framework.renderers import BaseRenderer, TemplateHTMLRenderer


class MarkdownRenderer(BaseRenderer):
    media_type = "text/markdown"
    format = "md"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = renderer_context["response"]
        if response.exception:
            # This breaks the "text/markdown response" contract, but this renderer is only used opportunistically for
            # event stacktraces anyway. We need some handling of the `response.exception` case because DRF still routes
            # exception responses through the chosen renderer, but we delegate to HTML exception rendering instead of
            # teaching this markdown renderer every DRF error-data shape. It's not like a user would expect e.g. a 404
            # to be rendered as markdown anyway (hence "opportunistically" above).
            return TemplateHTMLRenderer().render(data, accepted_media_type, renderer_context)

        return data.encode("utf-8")
