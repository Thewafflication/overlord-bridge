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
    assert spans == [("**literal** <tag>\n", ("md_code",)), ("\n", ("md_code",)), ("After", ())]


def test_paths_unclosed_markup_and_html_remain_literal():
    text = "some_file_name C:\\my_folder\\file.txt **unfinished <b>HTML</b>"
    assert "".join(part for part, _ in message_spans(text)) == text


def test_links_display_destination_without_executing_anything():
    assert list(message_spans("[Docs](https://example.com/a)")) == [
        ("Docs (https://example.com/a)", ("md_link",))]
    text = "[run](javascript:alert)"
    assert "".join(part for part, _ in message_spans(text)) == text
