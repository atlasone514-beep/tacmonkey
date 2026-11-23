"""Wording that can be changed from the Dev page without a release.

Every piece of on-screen text that may be edited has a key ("box.help") and its built-in wording.
t(key, default) gives the live wording if the developer changed it (live_data "texts"), else the
built-in one, and remembers the key so the Dev page can list it. A changed text with {fields} that
don't fit falls back to the built-in wording, so an edit can't break the window.
"""
import string

DEFAULTS = {}   # key -> built-in wording (filled as the window is built)
_live = {}


def set_live(texts):
    global _live
    _live = dict(texts or {})


def live():
    return dict(_live)


def _fields(text):
    try:
        return {f for _, f, _, _ in string.Formatter().parse(text) if f}
    except ValueError:
        return None


def t(key, default, **fields):
    DEFAULTS.setdefault(key, default)
    text = _live.get(key, default)
    if fields or _fields(default):
        if _fields(text) is None or not _fields(text) <= set(fields):
            text = default
        try:
            return text.format(**fields)
        except (KeyError, IndexError, ValueError):
            return default.format(**fields)
    return text


def usable(key, text):
    """None if text can stand in for key's wording, else why not (unknown {fields})."""
    want = _fields(DEFAULTS.get(key, ""))
    have = _fields(text)
    if have is None:
        return "a { or } doesn't pair up (write {{ or }} for a plain brace)"
    extra = have - (want or set())
    if extra:
        return f"uses {', '.join('{' + f + '}' for f in sorted(extra))}, which this text doesn't have"
    return None
