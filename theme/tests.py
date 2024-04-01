from unittest import TestCase

from .templatetags.issues import _pygmentize_lines


class TestIssuesTemplateTags(TestCase):
    # These tests depend on the assert inside the function, simply calling the function and the assert not blowing up is
    # what we're proving here.

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
