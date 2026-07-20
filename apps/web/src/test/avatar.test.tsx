// Avatar dead-photo fallback (2026-07-19, missionary-photos incident): every stored signed URL had
// expired (the CI photo pass silently skipped for a month), and a broken <img> was just display:none'd
// — leaving EMPTY circles instead of initials wherever a photo_url was present. On load error the
// avatar must degrade to initials, and a FRESH URL arriving later (the re-signed one) must render again.
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Avatar } from '../components/ui';

describe('Avatar', () => {
  it('renders initials when there is no photo', () => {
    const { container } = render(<Avatar name="Jordan Sample" />);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('JS')).toBeInTheDocument();
  });

  it('falls back to INITIALS (not an empty circle) when the photo URL is dead', () => {
    const { container } = render(<Avatar name="Jordan Sample" photoUrl="https://x.test/expired.jpg" />);
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    fireEvent.error(img!);
    // Pre-fix this failed: the img was only hidden, initials never rendered.
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('JS')).toBeInTheDocument();
  });

  it('recovers when a fresh URL replaces the failed one', () => {
    const { container, rerender } = render(
      <Avatar name="Jordan Sample" photoUrl="https://x.test/expired.jpg" />,
    );
    fireEvent.error(container.querySelector('img')!);
    expect(container.querySelector('img')).toBeNull();

    rerender(<Avatar name="Jordan Sample" photoUrl="https://x.test/fresh.jpg" />);
    const fresh = container.querySelector('img');
    expect(fresh).not.toBeNull();
    expect(fresh!.getAttribute('src')).toBe('https://x.test/fresh.jpg');
  });
});
