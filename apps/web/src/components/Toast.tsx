// Lightweight toast/snackbar system (the React equivalent of ScaffoldMessenger.showSnackBar).
// `useToast()` exposes show({ message, action }); toasts auto-dismiss. A polite live region keeps
// it accessible to screen readers.

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

interface ToastAction {
  label: string;
  onClick: () => void;
}

interface ToastItem {
  id: number;
  message: string;
  action?: ToastAction;
  leaving?: boolean; // drives the exit animation before the node unmounts
}

interface ToastApi {
  show: (opts: { message: string; action?: ToastAction; durationMs?: number }) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const remove = useCallback((id: number) => {
    setItems((cur) => cur.filter((t) => t.id !== id));
  }, []);

  // Play the exit animation, then unmount (reduced-motion zeroes the keyframe so this is ~instant).
  const dismiss = useCallback((id: number) => {
    setItems((cur) => cur.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
    window.setTimeout(() => remove(id), 200);
  }, [remove]);

  const show = useCallback<ToastApi['show']>(
    ({ message, action, durationMs = 5000 }) => {
      const id = nextId.current++;
      setItems((cur) => [...cur, { id, message, action }]);
      window.setTimeout(() => dismiss(id), durationMs);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(
        <div className="toast-host" role="region" aria-live="polite" aria-label="Notifications">
          {items.map((t) => (
            <div className={t.leaving ? 'toast toast--leaving' : 'toast'} key={t.id}>
              <span>{t.message}</span>
              {t.action && (
                <button
                  type="button"
                  onClick={() => {
                    t.action!.onClick();
                    dismiss(t.id);
                  }}
                >
                  {t.action.label}
                </button>
              )}
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
