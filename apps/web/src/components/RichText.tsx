// Inline-markdown renderer for member notes — the EXACT subset Ricky's Mission-KPIs editor
// persists (MarkdownAttributedConverter.swift): **bold**, *italic*, ***bold-italic***, and
// [label](url) links; block constructs are out of scope by design. Underscore variants
// (__bold__, _italic_) are accepted too since hand-typed notes use them. Rendering builds REACT
// NODES only (never innerHTML), so imported note text can't inject markup; link hrefs are
// restricted to http(s). Unbalanced markers fall through as literal text — a lone asterisk in a
// note must never eat the rest of the line.

import type { ReactNode } from 'react';

const TOKEN = new RegExp(
  [
    /\*\*\*(.+?)\*\*\*/.source, // 1: ***bold italic***
    /\*\*(.+?)\*\*/.source, // 2: **bold**
    // Italic content must not start/end with a space ("3 * 4 * 5" is math, not emphasis).
    /\*([^*\s](?:[^*\n]*?[^*\s])?)\*/.source, // 3: *italic*
    /___(.+?)___/.source, // 4: ___bold italic___
    /__(.+?)__/.source, // 5: __bold__
    /_([^_\s](?:[^_\n]*?[^_\s])?)_/.source, // 6: _italic_
    /\[([^\]\n]+?)\]\(([^)\s]+?)\)/.source, // 7+8: [label](url)
  ].join('|'),
  'g',
);

function safeHref(url: string): string | null {
  return /^https?:\/\//i.test(url) ? url : null;
}

/** Parse one note body into inline React nodes. Exported for tests. */
export function richTextNodes(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0;
    if (at > last) nodes.push(text.slice(last, at));
    const [, boldItal, bold, ital, uBoldItal, uBold, uItal, label, url] = m;
    if (boldItal != null || uBoldItal != null) {
      nodes.push(<strong key={key++}><em>{boldItal ?? uBoldItal}</em></strong>);
    } else if (bold != null || uBold != null) {
      nodes.push(<strong key={key++}>{bold ?? uBold}</strong>);
    } else if (ital != null || uItal != null) {
      nodes.push(<em key={key++}>{ital ?? uItal}</em>);
    } else if (label != null && url != null) {
      const href = safeHref(url);
      // A non-http(s) target renders as plain text — the label alone, never a live link.
      nodes.push(href
        ? <a key={key++} href={href} target="_blank" rel="noopener noreferrer">{label}</a>
        : label);
    }
    last = at + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

/** A note body with the inline formatting rendered. Wrap in a pre-wrap parent for line breaks. */
export function RichText({ text }: { text: string }) {
  return <>{richTextNodes(text)}</>;
}
