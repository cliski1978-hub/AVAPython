"""AVA-owned HTML content policy (Step 4.5).

The canonical document content is serialized HTML produced by the frontend
editor (Tiptap). A durable document store would become a stored-XSS sink
unless content is vetted on every write, so this module defines the smallest
safe boundary supported by existing dependencies: a **reject-on-violation**
allowlist policy implemented with the standard library ``html.parser``.

Tiptap is deliberately never imported or consulted here. The policy treats
content as an opaque serialized-HTML string and enforces a documented set of
rules; anything the policy does not explicitly allow is **rejected**, never
silently stripped or mutated.

Rules (documented policy):

1. Content must be non-empty and must contain at least one element
   (text-only payloads are rejected; ``<p></p>`` — the empty paragraph the
   editor emits for a blank document — is accepted).
2. Only the following tags are allowed (the editor's produced vocabulary,
   plus ``<a>`` for future link support):

   ``p``, ``h1``..``h6``, ``strong``, ``em``, ``s``, ``code``, ``pre``,
   ``blockquote``, ``ul``, ``ol``, ``li``, ``br``, ``hr``, ``a``

3. The only attribute allowed anywhere is ``href``, and only on ``<a>``.
   Event-handler attributes (``on*``), inline ``style``, ``class``, ``id``,
   ``src``/``srcset``, and all other attributes are rejected.
4. ``<a href=...>`` values are restricted to ``http``, ``https``, ``mailto``,
   ``tel``, or in-document fragments (``#...``). Executable protocols
   (``javascript:``, ``vbscript:``, ``data:``) and protocol-relative URLs
   (``//host``) are rejected. Relative URLs are rejected; the editor emits
   absolute or fragment links.
5. The document may not contain a DOCTYPE declaration or processing
   instructions (content is assumed to be a fragment, never a full document).
6. Markup must be well-formed: start/end tags must balance (void tags
   ``br``/``hr`` excluded) and nesting must be explicit. Unclosed tags and
   mismatched closing tags are rejected. The editor serializes literal
   content inside ``<code>``/``<pre>`` HTML-escaped, so literal ``<`` inside
   those blocks cannot legitimately appear.
7. HTML comments are tolerated (they are inert text) but never counted as
   document content.

Deferred hardening (documented): this is the minimal policy, not a general
purpose sanitizer. When durable persistence and external/orchestrated
content inputs arrive (later Phase 4 steps), re-evaluate a battle-tested
sanitizer (e.g. ``bleach``/``nh3`` or a server-side DOMPurify port) or a
policy-file driven whitelist. Until then, the reject-first policy keeps
disallowed markup out of trusted backend content without mutating valid
editor output.
"""

from html.parser import HTMLParser

#: Tags the AVA canonical serialized-HTML content may contain. This is the
#: vocabulary the frontend editor (Tiptap StarterKit) produces today, plus
#: ``<a>`` for future link support. Anything outside this set is rejected.
ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "strong",
        "em",
        "s",
        "code",
        "pre",
        "blockquote",
        "ul",
        "ol",
        "li",
        "br",
        "hr",
        "a",
    }
)

#: Void elements never push onto the tag stack.
VOID_TAGS: frozenset[str] = frozenset({"br", "hr"})

#: The only attribute allowed anywhere, and only on ``<a>``.
ALLOWED_ATTRIBUTES: frozenset[str] = frozenset({"href"})

#: Attribute-name prefixes that are always dangerous (event handlers).
BANNED_ATTRIBUTE_PREFIXES: tuple[str, ...] = ("on",)

#: Protocols accepted in ``href`` values.
SAFE_HREF_PROTOCOLS: frozenset[str] = frozenset({"http", "https", "mailto", "tel"})

#: Protocols/URL shapes that must never appear in ``href``.
BANNED_HREF_PREFIXES: tuple[str, ...] = ("javascript:", "vbscript:", "data:")


class HtmlContentError(ValueError):
    """Raised when document content violates the AVA HTML content policy."""


def validate_html_content(content: str) -> None:
    """Validate serialized-HTML content against the AVA content policy.

    Args:
        content: The serialized-HTML string to validate.

    Raises:
        HtmlContentError: If the content violates any policy rule.
    """
    if not content.strip():
        raise HtmlContentError("content is empty or whitespace-only")
    parser = _PolicyParser()
    try:
        parser.feed(content)
        parser.close()
    except HtmlContentError:
        raise
    except Exception as exc:
        raise HtmlContentError(f"malformed HTML content: {exc}") from exc
    if parser._open_tags:
        raise HtmlContentError(f"unclosed tag <{parser._open_tags[-1]}>")
    if parser._element_count == 0:
        raise HtmlContentError("content must contain at least one element")


def _validate_href(value: str | None) -> None:
    """Reject ``href`` values that could execute when rendered."""
    if value is None:
        return
    stripped = value.strip()
    if not stripped or stripped.startswith("#"):
        return
    lowered = stripped.lower()
    for banned in BANNED_HREF_PREFIXES:
        if lowered.startswith(banned):
            raise HtmlContentError(f"unsafe href protocol '{banned.rstrip(':')}'")
    if lowered.startswith("//"):
        raise HtmlContentError("protocol-relative href not allowed")
    if ":" in stripped:
        scheme = stripped.split(":", 1)[0].lower()
        if scheme not in SAFE_HREF_PROTOCOLS:
            raise HtmlContentError(f"unsafe href scheme '{scheme}'")
        return
    raise HtmlContentError("relative href not allowed; use an absolute or fragment href")


class _PolicyParser(HTMLParser):
    """Parser that raises ``HtmlContentError`` on the first policy violation."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._open_tags: list[str] = []
        self._element_count: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record(tag, attrs)
        if tag not in VOID_TAGS:
            self._open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if not self._open_tags:
            raise HtmlContentError(f"unexpected closing tag </{tag}>")
        open_tag = self._open_tags.pop()
        if open_tag != tag:
            raise HtmlContentError(f"mismatched closing tag </{tag}> (expected </{open_tag}>)")

    def handle_decl(self, decl: str) -> None:
        raise HtmlContentError("DOCTYPE/document declarations are not allowed")

    def handle_pi(self, data: str) -> None:
        raise HtmlContentError("processing instructions are not allowed")

    def _record(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS:
            raise HtmlContentError(f"disallowed tag <{tag}>")
        self._element_count += 1
        for name, value in attrs:
            if name.startswith(BANNED_ATTRIBUTE_PREFIXES):
                raise HtmlContentError(f"event-handler attribute '{name}' not allowed on <{tag}>")
            if name not in ALLOWED_ATTRIBUTES:
                raise HtmlContentError(f"attribute '{name}' not allowed on <{tag}>")
            if tag != "a" and name == "href":
                raise HtmlContentError(f"attribute 'href' only allowed on <a>, not <{tag}>")
            if name == "href":
                _validate_href(value)