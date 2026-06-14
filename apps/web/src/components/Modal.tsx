// Accessible modal dialog + bottom sheet + right side-sheet, with focus trapping, Escape-to-close,
// and a scrim. Mirrors the Flutter AlertDialog / showModalBottomSheet patterns. Rendered into a
// portal so they overlay.
//
// Animations: sheets (the `side` and bottom `sheet` variants) "show from behind and hide back" —
// they slide IN with a smooth easing curve and play a real EXIT animation on close before
// unmounting (we keep the dialog mounted, flip `closing`, then unmount on animationend / a fallback
// timeout). The centered dialog gets a gentle pop. Under prefers-reduced-motion the global rule in
// theme.css zeroes animation durations, so the animationend fires (near-)instantly — reduced-motion
// users get an instant show/hide with no stuck "closing" state.

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { IconButton, Spinner } from './ui';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  actions?: ReactNode;
  /** Render as a bottom sheet (drag-handle-less but full-width-ish) instead of a centered dialog. */
  sheet?: boolean;
  /** Render as a right side-sheet on desktop/tablet (slides in from the right, full height, the previous
   *  screen visible-but-dimmed at left); falls back to a bottom sheet on phones (#6b). */
  side?: boolean;
  /** Widen the side-sheet for dense content (e.g. the Admin ops console tables) — min(880px, 96vw). */
  wide?: boolean;
  /** Hide the close (×) button in the title row (e.g. when actions already include Cancel). */
  hideClose?: boolean;
  /** Render the panel chrome-less: no title row / body padding, so embedded content can supply its
   *  own header (e.g. the Admin sub-list pages with their own app-bar). `title` is still used as the
   *  dialog's accessible name. */
  bare?: boolean;
  /** Extra class for the body (e.g. `form-stack` to stack fields/buttons with the form gap). */
  bodyClassName?: string;
  /** Show a centered spinner over the body instead of the children — for in-sheet async loads, so a
   *  flow never has to block the whole screen with a full-screen scrim. */
  loading?: boolean;
}

// Exit animation duration (kept in sync with the CSS *-out keyframes). A fallback timeout unmounts
// even if animationend never fires (reduced-motion zeroes the duration → it fires ~instantly anyway).
const EXIT_MS = 260;

export function Modal({
  open, onClose, title, children, actions, sheet, side, wide, hideClose, bare, bodyClassName, loading,
}: ModalProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useRef(`modal-${Math.random().toString(36).slice(2)}`).current;
  // Callers pass inline `onClose` arrows, so its identity changes every render. The focus effect
  // must depend only on `open` — re-running it per render refocuses the dialog container on every
  // keystroke, which made the ReauthDialog password field impossible to type into (cursor lost
  // after each character). The listener reads the latest callback through this ref instead.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Keep the dialog mounted through its exit animation: `render` stays true while closing, `closing`
  // drives the *-out keyframes. When `open` goes true we (re)mount and clear `closing`.
  const [render, setRender] = useState(open);
  const [closing, setClosing] = useState(false);
  const exitTimer = useRef<number | null>(null);

  useEffect(() => {
    if (open) {
      if (exitTimer.current != null) {
        window.clearTimeout(exitTimer.current);
        exitTimer.current = null;
      }
      setRender(true);
      setClosing(false);
      return;
    }
    // open → false: if we were showing, play the exit then unmount.
    if (render) {
      setClosing(true);
      exitTimer.current = window.setTimeout(() => {
        setRender(false);
        setClosing(false);
        exitTimer.current = null;
      }, EXIT_MS);
    }
    return () => {
      if (exitTimer.current != null) {
        window.clearTimeout(exitTimer.current);
        exitTimer.current = null;
      }
    };
    // `render` intentionally omitted: we only react to `open` flips, reading the latest render via closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Focus trap + Escape + scroll-lock + focus-restore — active only while the dialog is actually open
  // (not during the exit animation, so the restored focus isn't yanked back).
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

  if (!render) return null;

  const variantClass = side ? ' side' : sheet ? ' sheet' : '';
  const closingClass = closing ? ' closing' : '';
  const sideClass = [
    'dialog',
    side ? 'dialog--side' : '',
    side && wide ? 'dialog--wide' : '',
  ].filter(Boolean).join(' ');

  return createPortal(
    <div className={`scrim${variantClass}${closingClass}`}>
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
        className={`${side ? sideClass : 'dialog'}${bare ? ' dialog--bare' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={bare ? title : undefined}
        aria-labelledby={bare ? undefined : titleId}
        aria-busy={loading || undefined}
        tabIndex={-1}
        ref={ref}
      >
        {!bare && (
          <div className="dialog__title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span id={titleId} style={{ flex: 1 }}>
              {title}
            </span>
            {!hideClose && <IconButton icon="close" label="Close" onClick={onClose} size={20} />}
          </div>
        )}
        <div
          className={
            bare
              ? `dialog__body dialog__body--bare${bodyClassName ? ` ${bodyClassName}` : ''}`
              : bodyClassName
                ? `dialog__body ${bodyClassName}`
                : 'dialog__body'
          }
          style={{ position: 'relative' }}
        >
          {loading ? (
            <div className="dialog__loading" role="status" aria-label="Loading">
              <Spinner large />
            </div>
          ) : (
            children
          )}
        </div>
        {actions && !loading && <div className="dialog__actions">{actions}</div>}
      </div>
    </div>,
    document.body,
  );
}
