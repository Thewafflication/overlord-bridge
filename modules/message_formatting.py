"""Small, inert Markdown renderer for native chat text widgets."""
import re

from pygments.lexers import get_lexer_by_name
from pygments.token import Token
from pygments.util import ClassNotFound


SYNTAX_COLORS = {"keyword": "#c4b5fd", "string": "#86efac", "comment": "#94a3b8",
                 "number": "#fdba74", "function": "#93c5fd", "operator": "#f9a8d4"}


def _code_spans(source, language):
    base = ("md_code", "md_code_block")
    try:
        lexer = get_lexer_by_name(language, stripnl=False, ensurenl=False)
    except ClassNotFound:
        yield source, base
        return
    # Unknown languages and large blocks remain readable, literal code.
    if len(source) > 100000:
        yield source, base
        return
    for _, token, value in lexer.get_tokens_unprocessed(source):
        style = next((name for kind, name in (
            (Token.Keyword, "keyword"), (Token.Literal.String, "string"),
            (Token.Comment, "comment"), (Token.Literal.Number, "number"),
            (Token.Name.Function, "function"), (Token.Operator, "operator")) if token in kind), None)
        if value:
            yield value, base + (("syntax_" + style,) if style else ())


_INLINE = re.compile(
    r"(`+)(.+?)\1|\*\*(.+?)\*\*|__(.+?)__|"
    r"(?<!\w)\*([^*\n]+)\*|(?<!\w)_([^_\n]+)_(?!\w)|"
    r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)"
)


def _inline(text, tags=()):
    offset = 0
    for match in _INLINE.finditer(text):
        if match.start() > offset:
            yield text[offset:match.start()], tags
        ticks, code, bold, strong, italic, emphasis, label, url = match.groups()
        if ticks:
            yield code, tags + ("md_code",)
        elif bold is not None or strong is not None:
            yield from _inline(bold if bold is not None else strong, tags + ("md_bold",))
        elif italic is not None or emphasis is not None:
            yield from _inline(italic if italic is not None else emphasis, tags + ("md_italic",))
        else:
            yield label + " (" + url + ")", tags + ("md_link",)
        offset = match.end()
    if offset < len(text):
        yield text[offset:], tags


def message_spans(text):
    """Yield display text and Tk tags; never interpret HTML or execute links."""
    fence = None
    code_lines = []
    language = "text"
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
                yield from _code_spans("".join(code_lines), language)
                code_lines = []
            else:
                code_lines.append(line)
            continue
        if marker:
            fence = marker[1]
            language = marker[2].strip().split()[0] if marker[2].strip() else "text"
            continue
        heading = re.match(r"^ {0,3}#{1,6}\s+(.+?)(?:\s+#+)?$", line.rstrip("\r\n"))
        if heading:
            yield from _inline(heading[1], ("md_heading",))
            yield "\n", ()
            continue
        line = re.sub(r"^(\s*)[-+*] +", r"\1• ", line)
        yield from _inline(line)
    if fence:
        yield from _code_spans("".join(code_lines), language)
