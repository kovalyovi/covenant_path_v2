// Regression test for the "password field is impossible to enter" report (2026-06-10): Modal's
// focus-trap effect depended on [open, onClose]; every caller passes an inline onClose arrow, so
// each keystroke re-ran the effect and refocused the dialog container, blurring the input mid-word.
// The harness below reproduces the real usage shape: state updates on change + inline onClose.

import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Modal } from '../components/Modal';

function PasswordDialog({ onClose }: { onClose: () => void }) {
  const [password, setPassword] = useState('');
  return (
    // Inline arrow: a NEW onClose identity on every render, exactly like ReauthDialog/AdminPage.
    <Modal open onClose={() => onClose()} title="Re-authorize">
      <input
        aria-label="Password"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
    </Modal>
  );
}

describe('Modal focus handling', () => {
  it('keeps focus in an input while typing despite inline onClose props', () => {
    render(<PasswordDialog onClose={() => {}} />);
    const input = screen.getByLabelText('Password') as HTMLInputElement;
    input.focus();
    for (const ch of 'secret') {
      fireEvent.change(input, { target: { value: input.value + ch } });
      expect(document.activeElement).toBe(input);
    }
    expect(input.value).toBe('secret');
  });

  it('focuses the dialog on open and still closes on Escape with the latest callback', () => {
    const onClose = vi.fn();
    render(<PasswordDialog onClose={onClose} />);
    expect(document.activeElement?.getAttribute('role')).toBe('dialog');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

// Regression for "side sheets don't slide in but slide out" (2026-06-17): the side-sheet entrance
// (`animation: side-in`) is turned off by `.dialog--entered`, and `entered` was flipped by ANY
// `animationend` bubbling up from a child (or every child under prefers-reduced-motion). That killed
// the slide-IN partway, while the slide-OUT on close still played (its rule out-specifies
// `.dialog--entered`). Only the dialog's OWN animation should mark it entered.
describe('Modal side-sheet entrance', () => {
  it('a child animationend does not mark the dialog entered (only its own does)', () => {
    render(
      <Modal open side title="Settings" onClose={() => {}}>
        <button data-testid="child">x</button>
      </Modal>,
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog.className).not.toContain('dialog--entered');
    // A CHILD's animationend bubbles up — it must NOT flip `entered` (which would disable side-in).
    fireEvent.animationEnd(screen.getByTestId('child'));
    expect(dialog.className).not.toContain('dialog--entered');
    // The dialog's OWN entrance animation finishing is what marks it entered.
    fireEvent.animationEnd(dialog);
    expect(dialog.className).toContain('dialog--entered');
  });
});
