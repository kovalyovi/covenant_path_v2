// A custom single-select dropdown that shows an icon + accent color per option (the milestone
// icon/color for categories, the unit pill color for units) and animates open/close — replacing the
// plain native <select> in the filter rows. Accessible listbox: button (aria-haspopup) + a role=listbox
// popup, arrow-key navigation, Enter/Space to select, Escape + outside-click to close, typeahead.

import { useEffect, useId, useRef, useState } from 'react';
import { Icon, type IconName } from './Icon';
import { hexA } from '../theme/tokens';

export interface DropdownOption {
  value: string;
  label: string;
  icon?: IconName;
  color?: string; // accent for the leading icon/dot
  trailing?: string; // small trailing text (e.g. an outstanding count)
}

export function Dropdown({
  value, options, onChange, ariaLabel, minWidth,
}: {
  value: string;
  options: DropdownOption[];
  onChange: (value: string) => void;
  ariaLabel: string;
  /** Optional floor; by default the trigger sizes to the selected option's content. */
  minWidth?: number;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0); // highlighted index while open
  const wrapRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const listId = useId();
  const selectedIdx = Math.max(0, options.findIndex((o) => o.value === value));
  const selected = options[selectedIdx];

  // Outside-click closes.
  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  // When opening, highlight the selected option and scroll it into view.
  useEffect(() => {
    if (open) {
      setActive(selectedIdx);
      requestAnimationFrame(() => {
        listRef.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({ block: 'nearest' });
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function choose(i: number) {
    const o = options[i];
    if (o) onChange(o.value);
    setOpen(false);
  }

  function onKey(e: React.KeyboardEvent) {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        setOpen(true);
      }
      return;
    }
    if (e.key === 'Escape') { e.preventDefault(); setOpen(false); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(options.length - 1, a + 1)); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); return; }
    if (e.key === 'Home') { e.preventDefault(); setActive(0); return; }
    if (e.key === 'End') { e.preventDefault(); setActive(options.length - 1); return; }
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(active); return; }
    // typeahead: jump to the next option starting with the typed letter
    if (e.key.length === 1 && /\S/.test(e.key)) {
      const k = e.key.toLowerCase();
      const start = (active + 1) % options.length;
      for (let n = 0; n < options.length; n++) {
        const i = (start + n) % options.length;
        if (options[i].label.toLowerCase().startsWith(k)) { setActive(i); break; }
      }
    }
  }

  return (
    <div className="dd" ref={wrapRef} style={minWidth ? { minWidth } : undefined}>
      <button
        type="button"
        className="dd__trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={onKey}
      >
        {selected?.icon && <Icon name={selected.icon} size={16} color={selected.color ?? 'var(--on-surface-variant)'} />}
        {selected && !selected.icon && selected.color && (
          <span className="dd__dot" style={{ background: selected.color }} />
        )}
        <span className="dd__label">{selected?.label ?? ''}</span>
        {selected?.trailing && <span className="dd__trailing">{selected.trailing}</span>}
        <Icon name="arrow_down" size={16} color="var(--on-surface-variant)" />
      </button>
      {open && (
        <ul className="dd__menu" role="listbox" id={listId} aria-label={ariaLabel} ref={listRef} tabIndex={-1}>
          {options.map((o, i) => {
            const isSel = o.value === value;
            const isActive = i === active;
            return (
              <li
                key={o.value}
                role="option"
                aria-selected={isSel}
                data-active={isActive}
                className={`dd__option${isActive ? ' dd__option--active' : ''}${isSel ? ' dd__option--selected' : ''}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(i)}
              >
                {o.icon && <Icon name={o.icon} size={16} color={o.color ?? 'var(--on-surface-variant)'} />}
                {!o.icon && o.color && <span className="dd__dot" style={{ background: o.color }} />}
                <span className="dd__label" style={o.color && (o.icon || o.color) ? { color: isSel ? o.color : undefined } : undefined}>{o.label}</span>
                {o.trailing && (
                  <span className="dd__trailing" style={o.color ? { background: hexA(o.color, 0.16), color: o.color } : undefined}>{o.trailing}</span>
                )}
                {isSel && <Icon name="check" size={15} color={o.color ?? 'var(--primary)'} />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
