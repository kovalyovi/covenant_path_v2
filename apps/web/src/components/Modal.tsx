// Accessible modal dialog + bottom sheet, with focus trapping, Escape-to-close, and a scrim. Mirrors
// the Flutter AlertDialog / showModalBottomSheet patterns. Rendered into a portal so they overlay.

import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { IconButton } from './ui';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  actions?: ReactNode;
  /** Render as a bottom sheet (drag-handle-less but full-width-ish) instead of a centered dialog. */
  sheet?: boolean;
  /** Hide the close (×) button in the title row (e.g. when actions already include Cancel). */
  hideClose?: boolean;
  /** Extra class for the body (e.g. `form-stack` to stack fields/buttons with the form gap). */
  bodyClassName?: string;
}

export function Modal({ open, onClose, title, children, actions, sheet, hideClose, bodyClassName }: ModalProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useRef(`modal-${Math.random().toString(36).slice(2)}`).current;
  // Callers pass inline `onClose` arrows, so its identity changes every render. The focus effect
  // must depend only on `open` — re-running it per render refocuses the dialog container on every
  // keystroke, which made the ReauthDialog password field impossible to type into (cursor lost
  // after each character). The listener reads the latest callback through this ref instead.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    // Focus the dialog so screen readers announce it and keyboard focus is captured.
    ref.current?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key === 'Tab' && ref.current) {
        const focusables = ref.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener('keydown', onKey, true);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.body.style.overflow = prevOverflow;
      prev?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div className={sheet ? 'scrim sheet' : 'scrim'}>
      {/* Backdrop as a real button so click-to-dismiss is keyboard/SR-accessible. The dialog also
          closes on Escape + the × button. The button is visually the scrim (filled via CSS). */}
      <button
        type="button"
        className="scrim__backdrop"
        aria-label="Close dialog"
        tabIndex={-1}
        onClick={onClose}
      />
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={ref}
      >
        <div className="dialog__title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span id={titleId} style={{ flex: 1 }}>
            {title}
          </span>
          {!hideClose && <IconButton icon="close" label="Close" onClick={onClose} size={20} />}
        </div>
        <div className={bodyClassName ? `dialog__body ${bodyClassName}` : 'dialog__body'}>{children}</div>
        {actions && <div className="dialog__actions">{actions}</div>}
      </div>
    </div>,
    document.body,
  );
}
