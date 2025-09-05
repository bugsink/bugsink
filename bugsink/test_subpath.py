from django.test import TestCase, override_settings
from django.template import Template, Context

from bugsink.app_settings import get_path_prefix, override_settings as override_bugsink_settings
from bugsink.context_processors import useful_settings_processor


class SubpathHostingTestCase(TestCase):
    """Test subpath hosting functionality."""

    def test_get_path_prefix_default(self):
        """Test that get_path_prefix returns empty string for default BASE_URL."""
        with override_bugsink_settings(BASE_URL="http://localhost:8000"):
            self.assertEqual(get_path_prefix(), "")

    def test_get_path_prefix_subpath(self):
        """Test that get_path_prefix extracts path from BASE_URL."""
        with override_bugsink_settings(BASE_URL="https://example.com/bugsink"):
            self.assertEqual(get_path_prefix(), "/bugsink")

    def test_get_path_prefix_subpath_with_trailing_slash(self):
        """Test that get_path_prefix handles trailing slash correctly."""
        with override_bugsink_settings(BASE_URL="https://example.com/bugsink/"):
            self.assertEqual(get_path_prefix(), "/bugsink")

    def test_get_path_prefix_deeper_path(self):
        """Test that get_path_prefix handles deeper paths."""
        with override_bugsink_settings(BASE_URL="https://example.com/tools/bugsink"):
            self.assertEqual(get_path_prefix(), "/tools/bugsink")

    def test_context_processor_includes_path_prefix(self):
        """Test that context processor includes path prefix."""
        from django.http import HttpRequest
        
        request = HttpRequest()
        request.user = None  # Mock an anonymous user
        
        with override_bugsink_settings(BASE_URL="https://example.com/bugsink"):
            context = useful_settings_processor(request)
            self.assertEqual(context['path_prefix'], "/bugsink")

    def test_template_filter_with_prefix(self):
        """Test the with_prefix template filter."""
        template = Template('{% load urls %}{{ url | with_prefix }}')
        
        with override_bugsink_settings(BASE_URL="https://example.com/bugsink"):
            context = Context({'url': '/admin/'})
            result = template.render(context)
            self.assertEqual(result, "/bugsink/admin/")

    def test_template_filter_without_prefix(self):
        """Test the with_prefix template filter with no prefix."""
        template = Template('{% load urls %}{{ url | with_prefix }}')
        
        with override_bugsink_settings(BASE_URL="http://localhost:8000"):
            context = Context({'url': '/admin/'})
            result = template.render(context)
            self.assertEqual(result, "/admin/")

    def test_template_filter_relative_url(self):
        """Test the with_prefix template filter with relative URLs."""
        template = Template('{% load urls %}{{ url | with_prefix }}')
        
        with override_bugsink_settings(BASE_URL="https://example.com/bugsink"):
            context = Context({'url': 'admin/'})
            result = template.render(context)
            self.assertEqual(result, "admin/")  # Should not add prefix to relative URLs