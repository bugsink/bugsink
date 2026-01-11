from unittest import TestCase as RegularTestCase
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils.safestring import SafeString
from django.utils.html import conditional_escape
from bugsink.pygments_extensions import choose_lexer_for_pattern, get_all_lexers
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase

from events.utils import IncompleteList, IncompleteDict

from .templatetags.issues import (
    _pygmentize_lines as actual_pygmentize_lines, format_var, pygmentize, timestamp_with_millis)

User = get_user_model()


class TestPygmentizeLineLineCountHandling(RegularTestCase):
    # The focus of these tests is `len(input) == len(output)`, which is hard in the presence of emptyness.
    #
    # For failure we depend on the asserts inside the function, simply calling the function and the assert not blowing
    # up is what we're proving here.

    def setUp(self):
        super().setUp()
        patcher = patch("theme.templatetags.issues.capture_stacktrace")
        self.capture_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def _pygmentize_lines(self, lines):
        # since we exclusively care about line-counts, we just pick something for filename and platform here.
        result = actual_pygmentize_lines(lines, filename="a.py", platform="python")
        self.capture_mock.assert_not_called()
        return result

    def test_pygmentize_lines_empty(self):
        self._pygmentize_lines([])

    def test_pygmentize_lines_single_empty_line(self):
        self._pygmentize_lines([""])

    def test_pygmentize_lines_single_space(self):
        self._pygmentize_lines([" "])

    def test_pygmentize_lines_single_line(self):
        self._pygmentize_lines(["print('hello world')"])

    def test_pygmentize_lines_leading_and_trailing_emptyness_0_1(self):
        self._pygmentize_lines(["print('hello world')", ""])

    def test_pygmentize_lines_leading_and_trailing_emptyness_0_2(self):
        self._pygmentize_lines(["print('hello world')", "", ""])

    def test_pygmentize_lines_leading_and_trailing_emptyness_2_0(self):
        self._pygmentize_lines(["", "", "print('hello world')"])

    def test_pygmentize_lines_leading_and_trailing_emptyness_1_1(self):
        self._pygmentize_lines(["", "print('hello world')", ""])

    def test_pygmentize_lines_leading_and_trailing_emptyness_2_1(self):
        self._pygmentize_lines(["", "", "print('hello world')", ""])

    def test_pygmentize_lines_leading_and_trailing_emptyness_1_2(self):
        self._pygmentize_lines(["", "print('hello world')", "", ""])

    def test_pygmentize_lines_leading_and_trailing_emptyness_2_2(self):
        self._pygmentize_lines(["", "", "print('hello world')", "", ""])

    def test_pygmentize_lines_newlines_in_the_middle(self):
        self._pygmentize_lines(["print('hello world')", "", "", "print('goodbye')"])

    def test_pygmentize_lines_non_python(self):
        # not actually python
        self._pygmentize_lines(["<?= 'hello world' ?>"])

    def test_pygmentize_lines_newline_in_code(self):
        self._pygmentize_lines(["print('hello world')\n"])

    def test_pygmentize_lines_newline_on_otherwise_empty_line(self):
        self._pygmentize_lines(["\n", "\n", "\n"])

    def test_pygmentize_lines_ruby_regression(self):
        # code taken from:
        # https://github.com/rails/rails/blob/0f969a989c87/activerecord/lib/active_record/connection_adapters/postgresql_adapter.rb
        code = """        #  - format_type includes the column size constraint, e.g. varchar(50)
        #  - ::regclass is a function that gives the id for a table name
        def column_definitions(table_name) #:nodoc:
          exec_query(<<-end_sql, 'SCHEMA').rows
              SELECT a.attname, format_type(a.atttypid, a.atttypmod),
                     pg_get_expr(d.adbin, d.adrelid), a.attnotnull, a.atttypid, a.atttypmod
                FROM pg_attribute a LEFT JOIN pg_attrdef d"""

        code_as_list = code.splitlines()
        actual_pygmentize_lines(code_as_list, filename="postgresql_adapter.rb", platform="ruby")
        self.capture_mock.assert_called()  # https://github.com/pygments/pygments/issues/2998


class TestChooseLexerForPattern(RegularTestCase):
    def test_choose_lexer_for_pattern(self):
        # simple 'does it not crash' test:

        for pattern, lexers in get_all_lexers()._list:
            choose_lexer_for_pattern(pattern, lexers, "", "", "python")


class TestFormatVar(RegularTestCase):

    def _format_var(self, var):
        # small helper for readable tests
        return format_var(var).replace("&#x27;", "'")

    def test_format_var_none(self):
        # This is how we've actually observed None values in the SDKs, so we should also handle it
        self.assertEqual(
            "None",
            self._format_var("None"),
        )

        # I _think_ SDKs generally don't send null (None) as a value, but if/when they do we should handle it
        # gracefully. See #119
        self.assertEqual(
            "None",
            self._format_var(None),
        )

    def test_format_var_nested(self):
        var = {
            "a": 1,
            "b": [2, 3],
            "c": {"d": 4},
            "d": [],
            "e": {},
            "f": "None",
            "g": "<python obj>",
        }

        self.assertEqual(
            "{'a': 1, 'b': [2, 3], 'c': {'d': 4}, 'd': [], 'e': {}, 'f': None, 'g': &lt;python obj&gt;}",
            self._format_var(var),
        )

    def test_format_var_nested_escaping(self):
        # like format_nested, but with the focus on "does escaping happen correctly?"
        var = {
            "hacker": ["<script>"],
        }

        self.assertEqual(
            '{&#x27;hacker&#x27;: [&lt;script&gt;]}',
            format_var(var),
        )
        self.assertTrue(isinstance(format_var(var), SafeString))

    def test_format_var_deep(self):
        def _deep(level):
            result = None
            for i in range(level):
                result = [result]
            return result

        var = _deep(10_000)

        self.assertEqual(
            '[' * 10_000 + 'None' + ']' * 10_000,
            self._format_var(var),
        )

    def test_format_var_incomplete_list(self):
        var = IncompleteList([1, 2, 3], 9)

        self.assertEqual(
            "[1, 2, 3, <i>&lt;9 items trimmed…&gt;</i>]",
            self._format_var(var),
        )

    def test_format_var_incomplete_dict(self):
        var = IncompleteDict({"a": 1, "b": 2, "c": 3}, 9)

        self.assertEqual(
            "{'a': 1, 'b': 2, 'c': 3, <i>&lt;9 items trimmed…&gt;</i>}",
            self._format_var(var),
        )


class TestPygmentizeEscapeMarkSafe(RegularTestCase):

    def test_escapes_html_in_all_contexts(self):
        out = pygmentize(
            {
                'filename':     'test.py',
                'pre_context':  ['<script>pre script</script>'],
                'context_line': '<script>my script</script>',
                'post_context': ['<script>post script</script>'],
            },
            platform='python',
        )

        for line in out['pre_context'] + [out['context_line']] + out['post_context']:
            self.assertIsInstance(line, SafeString)

            # we just check for the non-existance of <script> and </script> here because asserting against "whatever
            # pygmentize does" is not very useful, as it may change in the future.
            self.assertFalse("<script>" in line)
            self.assertFalse("</script>" in line)


class TimestampWithMillisTagTest(RegularTestCase):
    def test_float_input_produces_expected_safe_string(self):
        ts = 1620130245.1234

        self.assertEqual(
            '<span class="whitespace-nowrap">4 May 12:10:45.<span class="text-xs">123</span></span>',
            timestamp_with_millis(ts))

        self.assertTrue(isinstance(timestamp_with_millis(ts), SafeString))

    def test_timestamp_with_milis_is_not_a_target_for_html_injection(self):
        # even though the string input is returned as-is for this case, the tag will not mark it as safe in the process.
        ts = "<script>alert('hello');</script>"

        self.assertEqual(
            '&lt;script&gt;alert(&#x27;hello&#x27;);&lt;/script&gt;',
            conditional_escape(timestamp_with_millis(ts)))

        self.assertFalse(isinstance(timestamp_with_millis(ts), SafeString))


class NavigationLinksTestCase(TransactionTestCase):
    """Tests for navigation links in base.html template."""

    def test_superuser_sees_admin_and_normal_links(self):
        """Superusers should see all links in the navigation."""
        superuser = User.objects.create_superuser(username='admin', password='admin', email='admin@test.com')
        self.client.force_login(superuser)

        response = self.client.get('/', follow=True)
        self.assertEqual(200, response.status_code)

        self.assertContains(response, '/preferences/')
        self.assertContains(response, 'Preferences')
        self.assertContains(response, '/api/canonical/0/schema/swagger-ui/')
        self.assertContains(response, 'OpenAPI')

        # Admin only
        self.assertContains(response, '/admin/')
        self.assertContains(response, 'Admin')
        self.assertContains(response, '/users/')
        self.assertContains(response, 'Users')
        self.assertContains(response, '/bsmain/auth_tokens/')
        self.assertContains(response, 'Tokens')

    def test_user_sees_only_normal_links(self):
        """Users should see limited links in the navigation."""
        user = User.objects.create_user(username='user', password='user', email='user@test.com')
        self.client.force_login(user)

        response = self.client.get('/', follow=True)
        self.assertEqual(200, response.status_code)

        self.assertContains(response, '/preferences/')
        self.assertContains(response, 'Preferences')
        self.assertContains(response, '/api/canonical/0/schema/swagger-ui/')
        self.assertContains(response, 'OpenAPI')

        # Admin only. Not visible
        self.assertNotContains(response, '/admin/')
        self.assertNotContains(response, 'Admin')
        self.assertNotContains(response, '/users/')
        self.assertNotContains(response, 'Users')
        self.assertNotContains(response, '/bsmain/auth_tokens/')
        self.assertNotContains(response, 'Tokens')

    def test_anonymous_user_sees_no_links(self):
        """Anonymous users should see no links in the navigation."""

        response = self.client.get('/', follow=True)
        self.assertEqual(200, response.status_code)

        self.assertNotContains(response, '/preferences/')
        self.assertNotContains(response, 'Preferences')
        self.assertNotContains(response, '/api/canonical/0/schema/swagger-ui/')
        self.assertNotContains(response, 'OpenAPI')

        # Admin only. Not visible
        self.assertNotContains(response, '/admin/')
        self.assertNotContains(response, 'Admin')
        self.assertNotContains(response, '/users/')
        self.assertNotContains(response, 'Users')
        self.assertNotContains(response, '/bsmain/auth_tokens/')
        self.assertNotContains(response, 'Tokens')
