"""Escaped notebook schema markup with dependency-free selector copying."""
from html import escape

# Values are read from escaped DOM attributes, never interpolated into JS.
_COPY = """event.preventDefault(); event.stopPropagation();
(function(button) {
  const status = button.parentElement.querySelector('[role=status]');
  const input = button.parentElement.querySelector('input');
  const selector = button.dataset.selector;
  function copied() { status.textContent = 'Copied!'; input.hidden = true; button.focus(); }
  function fallback() {
    input.hidden = false; input.focus(); input.select();
    try { if (document.execCommand('copy')) { copied(); return; } } catch (_) {}
    status.textContent = 'Select and copy the selector below.';
  }
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(selector).then(copied, fallback);
    } else { fallback(); }
  } catch (_) { fallback(); }
})(this);"""


def selector(path):
    """Bracket syntax avoids dotted keys, Python keywords and method collisions."""
    return 'f' + ''.join('[...]' if key is Ellipsis else '[' + repr(key) + ']' for key in path)


def label(name, path):
    code = escape(selector(path), quote=True)
    return (
        '<span class="sunbear-schema-path">'
        f'<button type="button" data-selector="{code}" '
        f'title="Copy {code}" aria-label="Copy selector {code}" '
        f'onclick="{escape(_COPY, quote=True)}" '
        'style="font:inherit;font-weight:bold;color:inherit;background:none;'
        'border:0;padding:2px;cursor:copy;text-decoration:underline;'
        'text-decoration-style:dotted">'
        f'{escape(str(name))}</button>'
        '<span role="status" aria-live="polite" style="margin-left:6px"></span>'
        f'<input hidden readonly aria-label="Selector to copy" value="{code}" '
        'style="max-width:100%;font-family:monospace" />'
        '</span>'
    )


def render(root, collapsed=False, name='Root'):
    from .schema import Branch, Leaf, ListType
    selectors = []
    open_attr = '' if collapsed else ' open'

    def child_html(key, node, path):
        current = path + (key,)
        selectors.append(selector(current))
        heading = label(key, current)
        nested = node
        nested_path = current
        suffix = ''
        while isinstance(nested, Leaf) and isinstance(nested.type, ListType):
            nested = nested.type.item_type
            nested_path += (Ellipsis,)
            suffix += ' []'
            if isinstance(nested, ListType):
                nested = Leaf(nested)
        if isinstance(nested, Branch):
            children = ''.join(child_html(k, v, nested_path) for k, v in nested.fields.items())
            return f'<li><details{open_attr}><summary>{heading}{suffix}</summary><ul>{children}</ul></details></li>'
        return f'<li>{heading} : {escape(repr(node.type))}</li>'

    children = ''.join(child_html(k, v, ()) for k, v in root.fields.items())
    fallback = escape('\n'.join(selectors))
    return (
        '<div class="sunbear-schema">'
        '<p>Click a field to copy its selector (requires <code>from sunbear import f</code>).</p>'
        f'<details{open_attr}><summary><b>{escape(str(name))}</b></summary>'
        f'<ul style="list-style-type:none;padding-left:20px">{children}</ul>'
        + ('<span>(empty)</span>' if not root.fields else '')
        + '</details><details><summary>Copyable selectors</summary>'
        f'<pre>{fallback}</pre></details></div>'
    )
