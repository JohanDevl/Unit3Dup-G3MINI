# -*- coding: utf-8 -*-
"""Convert BBCode (including Unit3Dup custom tags) to HTML for web preview."""

from __future__ import annotations

import html
import re


# Order matters: process inner tags before outer tags
_RULES: list[tuple[str, str]] = [
    # Custom Unit3Dup tags
    (r'\[badge=(\w+)\](.*?)\[/badge\]', r'<span class="badge badge-\1">\2</span>'),
    (r'\[card-title\](.*?)\[/card-title\]', r'<div class="card-title">\1</div>'),
    (r'\[card-body\](.*?)\[/card-body\]', r'<div class="card-body">\1</div>'),
    (r'\[card\](.*?)\[/card\]', r'<div class="card">\1</div>'),
    (r'\[grid\](.*?)\[/grid\]', r'<div class="grid">\1</div>'),
    (r'\[col\](.*?)\[/col\]', r'<div class="col">\1</div>'),

    # Standard BBCode
    (r'\[b\](.*?)\[/b\]', r'<strong>\1</strong>'),
    (r'\[i\](.*?)\[/i\]', r'<em>\1</em>'),
    (r'\[u\](.*?)\[/u\]', r'<u>\1</u>'),
    (r'\[s\](.*?)\[/s\]', r'<s>\1</s>'),
    (r'\[size=(\d+)\](.*?)\[/size\]', r'<span style="font-size:\1px">\2</span>'),
    (r'\[color=(#?[\w]+)\](.*?)\[/color\]', r'<span style="color:\1">\2</span>'),
    (r'\[center\](.*?)\[/center\]', r'<div style="text-align:center">\1</div>'),
    (r'\[url=(.*?)\](.*?)\[/url\]', r'<a href="\1" target="_blank">\2</a>'),
    (r'\[url\](.*?)\[/url\]', r'<a href="\1" target="_blank">\1</a>'),
    (r'\[img=(\d+)\](.*?)\[/img\]', r'<img src="\2" style="max-width:\1px" loading="lazy">'),
    (r'\[img\](.*?)\[/img\]', r'<img src="\1" style="max-width:100%" loading="lazy">'),
    (r'\[code\](.*?)\[/code\]', r'<pre><code>\1</code></pre>'),
    (r'\[quote\](.*?)\[/quote\]', r'<blockquote>\1</blockquote>'),
]

# Compile patterns with DOTALL so . matches newlines
_COMPILED_RULES = [(re.compile(p, re.DOTALL | re.IGNORECASE), r) for p, r in _RULES]

_SAFE_URL_RE = re.compile(r'^https?://', re.IGNORECASE)

def _sanitize_urls(html_text: str) -> str:
    """Remove dangerous href/src attributes that don't start with http(s)."""
    def _check_attr(match):
        attr = match.group(1)  # href or src
        url = match.group(2)
        if _SAFE_URL_RE.match(url):
            return match.group(0)  # keep safe URLs
        return f'{attr}="#"'  # replace dangerous URLs

    return re.sub(r'((?:href|src))="([^"]*)"', _check_attr, html_text)


def bbcode_to_html(text: str | None) -> str:
    """Convert BBCode text to HTML."""
    if not text:
        return ""

    result = html.escape(text)

    # Apply rules (multiple passes for nested tags)
    for _ in range(3):
        prev = result
        for pattern, replacement in _COMPILED_RULES:
            result = pattern.sub(replacement, result)
        if result == prev:
            break

    # Sanitize URLs to prevent javascript: and data: XSS
    result = _sanitize_urls(result)

    # Convert newlines to <br>
    result = result.replace("\n", "<br>\n")

    return result
