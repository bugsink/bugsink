from unittest import TestCase as RegularTestCase

from bugsink.pygments_extensions import choose_lexer_for_pattern, get_all_lexers

from events.utils import IncompleteList, IncompleteDict

from .templatetags.issues import _pygmentize_lines as actual_pygmentize_lines, format_var


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


class TestChooseLexerForPatter(RegularTestCase):
    def test_choose_lexer_for_pattern(self):
        # simple 'does it not crash' test:

        for pattern, lexers in get_all_lexers()._list:
            choose_lexer_for_pattern(pattern, lexers, "", "", "python")


class TestFormatVar(RegularTestCase):

    def _format_var(self, var):
        # small helper for readable tests
        return format_var(var).replace("&#x27;", "'")

    def test_format_var_none(self):
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
            "f": None,
        }

        self.assertEqual(
            "{'a': 1, 'b': [2, 3], 'c': {'d': 4}, 'd': [], 'e': {}, 'f': None}",
            self._format_var(var),
        )

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
