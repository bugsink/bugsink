from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter

from django import template


register = template.Library()


@register.tag(name="code")
def do_code(parser, token):
    nodelist = parser.parse(("endcode",))
    parser.delete_first_token()
    return CodeNode(nodelist)


class CodeNode(template.Node):

    def __init__(self, nodelist):
        self.nodelist = nodelist

    def render(self, context):
        content = self.nodelist.render(context)

        # remove trailing whitespace from each line (it's never wanted, and in the case of code blocks it can actually
        # hurt, e.g. for space-after-backslash in bash)
        content = "\n".join([line.rstrip() for line in content.split("\n")])

        lang_identifier, code = content.split("\n", 1)
        assert lang_identifier.startswith(":::") or lang_identifier.startswith("#!"), \
            "Expected code block identifier ':::' or '#!' not " + lang_identifier

        lang = lang_identifier[3:].strip() if lang_identifier.startswith(":::") else lang_identifier[2:].strip()
        is_shebang = lang_identifier.startswith("#!")
        formatter = HtmlFormatter(linenos="table" if is_shebang else False)

        lexer = get_lexer_by_name(lang, stripall=True)

        return highlight(code, lexer, formatter).replace("highlight", "p-4 mt-4 bg-slate-50 syntax-coloring")
