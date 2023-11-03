from rest_framework.negotiation import BaseContentNegotiation


class IgnoreClientContentNegotiation(BaseContentNegotiation):
    # Sentry clients do not always send the correct Accept headers but expect json anyway.
    # Proceed as per https://www.django-rest-framework.org/api-guide/content-negotiation/#example

    def select_parser(self, request, parsers):
        """
        Select the first parser in the `.parser_classes` list.
        """
        return parsers[0]

    def select_renderer(self, request, renderers, format_suffix):
        """
        Select the first renderer in the `.renderer_classes` list.
        """
        return (renderers[0], renderers[0].media_type)
