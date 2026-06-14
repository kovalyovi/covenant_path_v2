// Shared UI primitives — the React equivalents of the Flutter shared widgets (SectionCard, buttons,
// chips, avatar, segmented control, spinner, count badge). New views compose these.

import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { Icon, type IconName } from './Icon';
import { hexA } from '../theme/tokens';
import { initialsOf } from '../logic/milestones';

type ButtonVariant = 'filled' | 'outlined' | 'text';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  icon?: IconName;
  block?: boolean;
  loading?: boolean;
}

export function Button({
  variant = 'text',
  icon,
  block,
  loading,
  children,
  className,
  disabled,
  ...rest
}: ButtonProps) {
  const cls = [
    'btn',
    `btn--${variant}`,
    block ? 'btn--block' : '',
    className ?? '',
  ].filter(Boolean).join(' ');
  return (
    <button className={cls} disabled={disabled || loading} {...rest}>
      {loading ? <span className="spinner" aria-hidden="true" /> : icon ? <Icon name={icon} size={18} /> : null}
      {children}
    </button>
  );
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
  label: string; // accessible name (also the tooltip)
  size?: number;
}

export function IconButton({ icon, label, size = 22, ...rest }: IconButtonProps) {
  return (
    <button className="iconbtn" aria-label={label} title={label} {...rest}>
      <Icon name={icon} size={size} />
    </button>
  );
}

export function Spinner({ large }: { large?: boolean }) {
  return <span className={large ? 'spinner spinner--lg' : 'spinner'} role="status" aria-label="Loading" />;
}

export function Card({ children, className, style }: { children: ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <div className={className ? `card ${className}` : 'card'} style={style}>
      {children}
    </div>
  );
}

interface SectionCardProps {
  title: string;
  children: ReactNode;
  icon?: IconName;
  iconColor?: string;
  /** Custom leading element (e.g. a completion ring); replaces the default `icon` glyph when set. */
  iconNode?: ReactNode;
  trailing?: ReactNode;
  onClick?: () => void;
  /** #10c: a left-edge completeness border + matching icon (✓ complete / ◐ partial / ⚠ incomplete) —
   *  green / amber / red. Not color-only: pair with an icon/label at the call site too. */
  tone?: 'good' | 'warn' | 'bad';
}

const TONE: Record<'good' | 'warn' | 'bad', string> = { good: '#2E7D32', warn: '#EF6C00', bad: '#E53935' };

/** A titled section as a rounded card — the building block for detail + KPI pages. Mirrors SectionCard. */
export function SectionCard({ title, children, icon, iconColor, iconNode, trailing, onClick, tone }: SectionCardProps) {
  const accent = iconColor ?? 'var(--primary)';
  const toneStyle = tone ? { borderLeft: `3px solid ${TONE[tone]}` } : undefined;
  const head = (
    <div className="section-card__head">
      {iconNode ? (
        iconNode
      ) : (
        icon && (
          <span className="section-card__icon" style={{ background: hexA(toHex(accent), 0.14), color: accent }}>
            <Icon name={icon} size={18} />
          </span>
        )
      )}
      <span className="section-card__title">{title}</span>
      {trailing}
    </div>
  );
  const body = (
    <div className="card__body">
      {head}
      {children}
    </div>
  );
  if (onClick) {
    return (
      <button type="button" className="card card--tappable" onClick={onClick} style={toneStyle}>
        {body}
      </button>
    );
  }
  return <div className="card" style={toneStyle}>{body}</div>;
}

// Accent may be a CSS var (var(--primary)) or a hex. hexA needs a hex; fall back to a neutral indigo
// for CSS-var accents (only used for the soft icon tint, so exactness isn't critical).
function toHex(c: string): string {
  return c.startsWith('#') ? c : '#4554b8';
}

export function CountBadge({ n }: { n: number }) {
  return <span className="count-badge">{n}</span>;
}

interface AvatarProps {
  name: string;
  photoUrl?: string | null;
  size?: number;
}

/** Member avatar: shows the stored LCR photo when present, else initials (also on load error). */
export function Avatar({ name, photoUrl, size = 36 }: AvatarProps) {
  const fontSize = size * 0.36;
  return (
    <span className="avatar" style={{ width: size, height: size, fontSize }} aria-hidden="true">
      {photoUrl ? (
        <img
          src={photoUrl}
          alt=""
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = 'none';
          }}
        />
      ) : (
        initialsOf(name)
      )}
    </span>
  );
}

interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  icon?: IconName;
}

interface SegmentedProps<T extends string> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
  disabled?: boolean;
}

/** A segmented (single-select) control. Mirrors Flutter's SegmentedButton. */
export function Segmented<T extends string>({ options, value, onChange, ariaLabel, disabled }: SegmentedProps<T>) {
  return (
    <div className="segmented" role="group" aria-label={ariaLabel}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className="segmented__btn"
          aria-pressed={value === o.value}
          disabled={disabled}
          onClick={() => onChange(o.value)}
        >
          {o.icon && <Icon name={o.icon} size={16} />}
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A linear progress bar (0..1). */
export function Progress({ value, color }: { value: number; color?: string }) {
  return (
    <div className="progress" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: color }} />
    </div>
  );
}

/** A pill showing the date range a period covers. Mirrors `_RangePill`. */
export function RangePill({ text }: { text: string }) {
  return (
    <span className="range-pill">
      <Icon name="date_range" size={14} />
      {text}
    </span>
  );
}
