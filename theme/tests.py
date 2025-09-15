from unittest import TestCase as RegularTestCase

from django.utils.safestring import SafeString
from django.utils.html import conditional_escape
from bugsink.pygments_extensions import choose_lexer_for_pattern, get_all_lexers

from events.utils import IncompleteList, IncompleteDict

from .templatetags.issues import (
    _pygmentize_lines as actual_pygmentize_lines, format_var, pygmentize, timestamp_with_millis)


def _pygmentize_lines(lines):
    # since we exclusively care about line-counts, we just pick something for filename and platform here.
    return actual_pygmentize_lines(lines, filename="a.py", platform="python")


class TestPygmentizeLineLineCountHandling(RegularTestCase):
    # The focus of these tests is `len(input) == len(output)`, which is hard in the presence of emptyness.
    #
    # For failure we depend on the asserts inside the function, simply calling the function and the assert not blowing
    # up is what we're proving here.

    def test_pygmentize_lines_empty(self):
        _pygmentize_lines([])

    def test_pygmentize_lines_single_empty_line(self):
        _pygmentize_lines([""])

    def test_pygmentize_lines_single_space(self):
        _pygmentize_lines([" "])

    def test_pygmentize_lines_single_line(self):
        _pygmentize_lines(["print('hello world')"])

    def test_pygmentize_lines_leading_and_trailing_emptyness_0_1(self):
        _pygmentize_lines(["print('hello world')", ""])

    def test_pygmentize_lines_leading_and_trailing_emptyness_0_2(self):
        _pygmentize_lines(["print('hello world')", "", ""])

    def test_pygmentize_lines_leading_and_trailing_emptyness_2_0(self):
        _pygmentize_lines(["", "", "print('hello world')"])

    def test_pygmentize_lines_leading_and_trailing_emptyness_1_1(self):
        _pygmentize_lines(["", "print('hello world')", ""])

    def test_pygmentize_lines_leading_and_trailing_emptyness_2_1(self):
        _pygmentize_lines(["", "", "print('hello world')", ""])

    def test_pygmentize_lines_leading_and_trailing_emptyness_1_2(self):
        _pygmentize_lines(["", "print('hello world')", "", ""])

    def test_pygmentize_lines_leading_and_trailing_emptyness_2_2(self):
        _pygmentize_lines(["", "", "print('hello world')", "", ""])

    def test_pygmentize_lines_newlines_in_the_middle(self):
        _pygmentize_lines(["print('hello world')", "", "", "print('goodbye')"])

    def test_pygmentize_lines_non_python(self):
        # not actually python
        _pygmentize_lines(["<?= 'hello world' ?>"])

    def test_pygmentize_lines_newline_in_code(self):
        _pygmentize_lines(["print('hello world')\n"])

    def test_pygmentize_lines_newline_on_otherwise_empty_line(self):
        _pygmentize_lines(["\n", "\n", "\n"])


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
