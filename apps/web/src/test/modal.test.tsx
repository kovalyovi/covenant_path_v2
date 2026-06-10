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
