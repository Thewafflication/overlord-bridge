"""Small, inert Markdown renderer for native chat text widgets."""
import re


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
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            else:
                yield line, ("md_code",)
            continue
        if marker:
            fence = marker[1]
            continue
        heading = re.match(r"^ {0,3}#{1,6}\s+(.+?)(?:\s+#+)?$", line.rstrip("\r\n"))
        if heading:
            yield from _inline(heading[1], ("md_heading",))
            yield "\n", ()
            continue
        line = re.sub(r"^(\s*)[-+*] +", r"\1• ", line)
        yield from _inline(line)
