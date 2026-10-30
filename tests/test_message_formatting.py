from modules.message_formatting import message_spans


def test_styles_and_lists_render_without_markdown_delimiters():
    spans = list(message_spans("## Result\n**Ready** and *waiting* with `a_b`\n- first\n1. next\n"))
    assert "".join(text for text, _ in spans) == "Result\nReady and waiting with a_b\n• first\n1. next\n"
    assert ("Ready", ("md_bold",)) in spans
    assert ("waiting", ("md_italic",)) in spans
    assert ("a_b", ("md_code",)) in spans


def test_code_fences_preserve_literal_markdown_and_blank_lines():
    text = "```python\n**literal** <tag>\n\n```\nAfter"
    spans = list(message_spans(text))
    assert ''.join(part for part, _ in spans) == '**literal** <tag>\n\nAfter'
    assert spans[-1] == ('After', ())
    assert all('md_code_block' in tags for _, tags in spans[:-1])


def test_multiline_python_highlighting_preserves_source():
    source = 'def answer():\n    """line one\nline two"""\n    return 42 # comment\n'
    spans = list(message_spans('```python\n' + source + '```'))
    assert ''.join(text for text, _ in spans) == source
    for tag in ('keyword', 'string', 'number', 'comment', 'function'):
        assert any('syntax_' + tag in tags for _, tags in spans)


def test_unknown_language_and_unclosed_fences_remain_literal():
    source = '\t**literal** <script> & `ticks`\n'
    spans = list(message_spans('~~~unknown-language\n' + source))
    assert ''.join(text for text, _ in spans) == source
    assert all('md_code_block' in tags for _, tags in spans)


def test_highlighter_keeps_tabs_crlf_and_missing_final_newline():
    source = 'if True:\r\n\tprint("✓")'
    assert ''.join(text for text, _ in message_spans('```python\n' + source)) == source


def test_paths_unclosed_markup_and_html_remain_literal():
    text = "some_file_name C:\\my_folder\\file.txt **unfinished <b>HTML</b>"
    assert "".join(part for part, _ in message_spans(text)) == text


def test_links_display_destination_without_executing_anything():
    assert list(message_spans("[Docs](https://example.com/a)")) == [
        ("Docs (https://example.com/a)", ("md_link",))]
    text = "[run](javascript:alert)"
    assert "".join(part for part, _ in message_spans(text)) == text
