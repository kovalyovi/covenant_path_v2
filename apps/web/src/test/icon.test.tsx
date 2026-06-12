import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { Icon } from '../components/Icon';

// CLIENT-03: a `title` must never be interpolated into the SVG as raw HTML.
describe('Icon', () => {
  it('does not render a title string as raw HTML', () => {
    const { container } = render(<Icon name="help" title={'<img src=x onerror="alert(1)">'} />);
    // the payload is NOT parsed into DOM nodes — only the static <path> renders inside the SVG
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')?.querySelectorAll('*').length).toBe(1); // just <path>
    // the accessible name is still present, via the React-escaped aria-label attribute
    expect(container.querySelector('svg')?.getAttribute('aria-label')).toContain('<img');
  });
});
