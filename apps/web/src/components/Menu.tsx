// A small accessible dropdown menu (the React equivalent of PopupMenuButton). Opens under the
// trigger; closes on outside-click, Escape, or selection. Used for the app-bar "⋯" menu and the
// stake switcher.

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Icon, type IconName } from './Icon';

export interface MenuItem {
  value: string;
  label: string;
  icon?: IconName;
  checked?: boolean;
}

interface Props {
  trigger: (props: { open: boolean; toggle: () => void; id: string; controls: string }) => ReactNode;
  items: MenuItem[];
  onSelect: (value: string) => void;
  label: string;
  align?: 'left' | 'right';
}

export function Menu({ trigger, items, onSelect, label, align = 'right' }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const btnId = useId();

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-flex' }}>
      {trigger({ open, toggle: () => setOpen((o) => !o), id: btnId, controls: menuId })}
      {open && (
        <ul
          id={menuId}
          role="menu"
          aria-label={label}
          style={{
            position: 'absolute',
            top: '100%',
            [align]: 0,
            marginTop: 4,
            minWidth: 220,
            background: 'var(--surface-container-high)',
            border: '1px solid var(--outline-variant)',
            borderRadius: 'var(--radius-md)',
            boxShadow: '0 6px 24px rgba(0,0,0,0.25)',
            padding: '6px 0',
            zIndex: 40,
            listStyle: 'none',
            margin: 0,
          }}
        >
          {items.map((it) => (
            <li key={it.value} role="none">
              <button
                role="menuitem"
                type="button"
                className="list-tile"
                style={{ padding: '10px 16px' }}
                onClick={() => {
                  setOpen(false);
                  onSelect(it.value);
                }}
              >
                {it.checked !== undefined && (
                  <Icon name={it.checked ? 'check' : 'circle_outline'} size={18} color={it.checked ? 'var(--primary)' : 'transparent'} />
                )}
                {it.icon && <Icon name={it.icon} size={20} />}
                <span className="list-tile__main">{it.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
