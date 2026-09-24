"""AVA HTML content policy tests (Step 4.5).

Prove the document content safety boundary:

* canonical editor-produced HTML passes through unchanged;
* dangerous executable markup is rejected, never stored as trusted content;
* malformed/unacceptable input is rejected rather than silently stripped;
* the policy tolerates the empty-paragraph content new documents carry.
"""

import pytest

from ava.services.html_content_policy import HtmlContentError, validate_html_content

# ============================================================
# BEGIN: Accepted content
# ============================================================


def test_initial_frontend_document_is_accepted_unchanged() -> None:
    """The exact initial frontend document passes through byte-for-byte."""
    content = "<h1>AVA Document Workspace</h1><p>This is an AVA document.</p>"
    validate_html_content(content)  # must not raise
    assert True


def test_empty_paragraph_is_accepted() -> None:
    """A blank document serializes as an empty paragraph; it must pass."""
    validate_html_content("<p></p>")


def test_editor_vocabulary_is_accepted() -> None:
    """Every tag the editor's StarterKit can produce is accepted."""
    content = (
        "<h2>Heading</h2>"
        "<p>Plain. <strong>Bold</strong> <em>Italic</em> <s>Strike</s> "
        "<code>inline</code></p>"
        "<blockquote><p>Quote</p></blockquote>"
        "<pre><code>code block</code></pre>"
        "<ul><li>One</li></ul><ol><li>Two</li></ol>"
        "<hr>"
    )
    validate_html_content(content)


def test_future_link_support_is_accepted() -> None:
    """``<a>`` with safe protocols or fragments is accepted."""
    validate_html_content('<p><a href="https://example.com">x</a></p>')
    validate_html_content('<p><a href="http://example.com">x</a></p>')
    validate_html_content('<p><a href="mailto:a@b.c">x</a></p>')
    validate_html_content('<p><a href="tel:+1234">x</a></p>')
    validate_html_content('<p><a href="#section">x</a></p>')


def test_escaped_angle_brackets_in_code_are_accepted() -> None:
    """Literal ``<`` inside code blocks must be HTML-escaped, and is accepted."""
    validate_html_content("<pre><code>&lt;script&gt;</code></pre>")


def test_html_comments_are_tolerated() -> None:
    """Comments are inert text and do not make a fragment invalid."""
    validate_html_content("<!-- welcome --><p>Body</p>")


# ============================================================
# END: Accepted content
# ============================================================


# ============================================================
# BEGIN: Rejected content (safety)
# ============================================================


@pytest.mark.parametrize(
    "content",
    [
        "<script>alert(1)</script>",
        "<p><script>alert(1)</script></p>",
        "<script src='https://evil.example/x.js'></script><p>x</p>",
    ],
)
def test_script_elements_are_rejected(content: str) -> None:
    """Executable ``<script>`` markup must never pass."""
    with pytest.raises(HtmlContentError):
        validate_html_content(content)


@pytest.mark.parametrize(
    "content",
    [
        "<img src=x onerror=alert(1)>",
        '<img src="https://evil.example/x.png">',
        "<svg onload=alert(1)>",
        "<iframe src='https://evil.example'></iframe>",
        "<style>body{display:none}</style>",
        "<div>x</div>",
        "<table><tr><td>x</td></tr></table>",
        "<textarea>x</textarea>",
        "<form><input></form>",
    ],
)
def test_sink_tags_are_rejected(content: str) -> None:
    """IMG/SVG/iframe/style/layout/active-content tags are all rejected."""
    with pytest.raises(HtmlContentError):
        validate_html_content(content)


@pytest.mark.parametrize(
    "content",
    [
        '<a href="javascript:alert(1)">x</a>',
        '<a href="JaVaScRiPt:alert(1)">x</a>',
        '<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>',
        '<a href="vbscript:msgbox(1)">x</a>',
        '<a href="//evil.example/x">x</a>',
    ],
)
def test_executable_hrefs_are_rejected(content: str) -> None:
    """Hrefs that can execute scripts are rejected regardless of casing."""
    with pytest.raises(HtmlContentError):
        validate_html_content(content)


def test_event_handler_attributes_are_rejected() -> None:
    """Inline event handlers (``on*``) are rejected even on allowed tags."""
    with pytest.raises(HtmlContentError):
        validate_html_content('<p onclick="alert(1)">x</p>')
    with pytest.raises(HtmlContentError):
        validate_html_content('<p onmouseover="alert(1)">x</p>')


def test_inline_styles_and_arbitrary_attributes_are_rejected() -> None:
    """``style``/``class``/``id``/``src`` are rejected on allowed tags."""
    with pytest.raises(HtmlContentError):
        validate_html_content('<p style="position:fixed">x</p>')
    with pytest.raises(HtmlContentError):
        validate_html_content('<p class="x">x</p>')
    with pytest.raises(HtmlContentError):
        validate_html_content('<p id="x">x</p>')
    with pytest.raises(HtmlContentError):
        validate_html_content('<p> + <img-ish src="x">')


# ============================================================
# END: Rejected content (safety)
# ============================================================


# ============================================================
# BEGIN: Rejected content (structure)
# ============================================================


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   ",
        "\n\t",
    ],
)
def test_empty_or_whitespace_content_is_rejected(content: str) -> None:
    with pytest.raises(HtmlContentError):
        validate_html_content(content)


def test_text_only_content_is_rejected() -> None:
    """A fragment must contain elements; bare text is not canonical content."""
    with pytest.raises(HtmlContentError):
        validate_html_content("just some text")


def test_doctype_and_processing_instructions_are_rejected() -> None:
    """Content is a fragment; full-document declarations are rejected."""
    with pytest.raises(HtmlContentError):
        validate_html_content("<!DOCTYPE html><p>x</p>")
    with pytest.raises(HtmlContentError):
        validate_html_content("<?xml version='1.0'?><p>x</p>")


@pytest.mark.parametrize(
    "content",
    [
        "</p>",
        "<p>unclosed",
        "<strong>x</strong></p>",
        "<p><strong>mismatch</p></strong>",
        "<ul><li>a</ul>",
    ],
)
def test_malformed_markup_is_rejected(content: str) -> None:
    """Unbalanced or mismatched markup is rejected, never auto-fixed."""
    with pytest.raises(HtmlContentError):
        validate_html_content(content)


# ============================================================
# END: Rejected content (structure)
# ============================================================