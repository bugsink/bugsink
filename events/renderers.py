from rest_framework.renderers import BaseRenderer


class MarkdownRenderer(BaseRenderer):
    media_type = "text/markdown"
    format = "md"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data.encode("utf-8")
