// RichText (2026-07-19): imported Mission-KPIs notes carry inline markdown (**bold**, *italic*,
// ***bold-italic***, [label](url) — his MarkdownAttributedConverter's exact wire subset). We render
// that subset as real formatting instead of raw markers — via React nodes only (no innerHTML), with
// hrefs restricted to http(s) and unbalanced markers left as literal text.

import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { RichText } from '../components/RichText';

const html = (text: string) => render(<span><RichText text={text} /></span>).container.innerHTML;

describe('RichText', () => {
  it('renders bold, italic, and bold-italic markers as formatting', () => {
    expect(html('a **b** c')).toContain('<strong>b</strong>');
    expect(html('a *i* c')).toContain('<em>i</em>');
    expect(html('x ***bi*** y')).toContain('<strong><em>bi</em></strong>');
    expect(html('u __b__ and _i_')).toContain('<strong>b</strong>');
    expect(html('u __b__ and _i_')).toContain('<em>i</em>');
  });

  it('renders [label](url) as a safe new-tab link, http(s) only', () => {
    const out = html('see [the plan](https://example.org/x)');
    expect(out).toContain('href="https://example.org/x"');
    expect(out).toContain('rel="noopener noreferrer"');
    expect(out).toContain('>the plan</a>');
    // A javascript: target must never become a live link — label as plain text.
    const bad = html('[click](javascript:alert(1))');
    expect(bad).not.toContain('<a');
    expect(bad).toContain('click');
  });

  it('never injects HTML from the note text itself', () => {
    expect(html('<img src=x onerror=alert(1)>')).toContain('&lt;img');
  });

  it('leaves plain text and unbalanced markers untouched', () => {
    expect(html('5 * 3 = 15 and a_b')).toContain('5 * 3 = 15 and a_b');
    // Space-adjacent delimiters are math/punctuation, not emphasis (CommonMark-style).
    expect(html('3 * 4 * 5')).toBe('<span>3 * 4 * 5</span>');
    expect(html('just text')).toBe('<span>just text</span>');
  });
});
