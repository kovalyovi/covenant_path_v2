// A small inline-SVG icon set covering the glyphs the app uses (mirrors the Material icon names
// referenced across the Flutter views). Inline SVG keeps the bundle free of an icon dependency and
// lets icons inherit `currentColor`. Decorative by default (aria-hidden); pass `title` for a label.

import type { CSSProperties } from 'react';

export type IconName =
  | 'event_available'
  | 'timelapse'
  | 'checklist'
  | 'insights'
  | 'grid_on'
  | 'refresh'
  | 'menu'
  | 'sync'
  | 'summarize'
  | 'person_add'
  | 'admin'
  | 'settings'
  | 'chevron_right'
  | 'chevron_left'
  | 'arrow_up'
  | 'arrow_down'
  | 'unfold_more'
  | 'filter'
  | 'filter_off'
  | 'filter_outline'
  | 'groups'
  | 'event'
  | 'water_drop'
  | 'warning'
  | 'check'
  | 'check_circle'
  | 'circle_outline'
  | 'arrow_forward'
  | 'fingerprint'
  | 'shield'
  | 'info'
  | 'rule'
  | 'logout'
  | 'account'
  | 'feedback'
  | 'support'
  | 'brightness'
  | 'key'
  | 'open_in_new'
  | 'send'
  | 'close'
  | 'handshake'
  | 'badge'
  | 'volunteer'
  | 'medal'
  | 'premium'
  | 'diversity'
  | 'help'
  | 'group_outline'
  | 'menu_book'
  | 'verified'
  | 'compare'
  | 'leaderboard'
  | 'schedule'
  | 'drive'
  | 'table'
  | 'link_off'
  | 'play'
  | 'pause'
  | 'date_range'
  | 'sort'
  | 'commit'
  | 'cloud_sync'
  | 'storage'
  | 'photo'
  | 'copy'
  | 'replay'
  | 'error'
  | 'history'
  | 'history_off'
  | 'favorite'
  | 'library'
  | 'mail'
  | 'note'
  | 'account_balance'
  | 'visibility'
  | 'visibility_off';

interface Props {
  name: IconName;
  size?: number;
  color?: string;
  title?: string;
  style?: CSSProperties;
  className?: string;
}

// Each entry is the inner markup of a 24x24 viewBox SVG (stroke or fill uses currentColor).
const PATHS: Record<IconName, string> = {
  event_available:
    '<path fill="currentColor" d="M9 19l-4-4 1.4-1.4L9 16.2l8.6-8.6L19 9l-10 10z" opacity="0"/><path fill="currentColor" d="M19 3h-1V1h-2v2H8V1H6v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm0 16H5V9h14v10zM5 7V5h14v2H5zm6.4 10L8 13.6l1.4-1.4 2 2 3.6-3.6L16.4 12 11.4 17z"/>',
  timelapse:
    '<path fill="currentColor" d="M16.24 7.76A6 6 0 0 0 12 6v6l-4.24 4.24a6 6 0 1 0 8.48-8.48zM12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16z"/>',
  checklist:
    '<path fill="currentColor" d="M22 7h-9v2h9V7zm0 8h-9v2h9v-2zM5.5 8.5 3.5 6.5 2 8l3.5 3.5L11 6 9.5 4.5 5.5 8.5zm0 8L3.5 14.5 2 16l3.5 3.5L11 14l-1.5-1.5-4 4z"/>',
  insights:
    '<path fill="currentColor" d="M21 8a3 3 0 0 1-3 3l-2.6 4.5a3 3 0 1 1-2.4-1.2L10.6 11A3 3 0 0 1 8 12.5L5.4 17a3 3 0 1 1-1.7-1L6.3 11.5A3 3 0 1 1 11 9l1.4 3.3A3 3 0 0 1 15 14l2.6-4.5A3 3 0 1 1 21 8z"/>',
  grid_on:
    '<path fill="currentColor" d="M20 2H4a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2zM8 20H4v-4h4v4zm0-6H4v-4h4v4zm0-6H4V4h4v4zm6 12h-4v-4h4v4zm0-6h-4v-4h4v4zm0-6h-4V4h4v4zm6 12h-4v-4h4v4zm0-6h-4v-4h4v4zm0-6h-4V4h4v4z"/>',
  refresh:
    '<path fill="currentColor" d="M17.65 6.35A8 8 0 1 0 19.73 14H17.6A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>',
  menu: '<path fill="currentColor" d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"/>',
  sync: '<path fill="currentColor" d="M12 4V1L8 5l4 4V6a6 6 0 0 1 6 6 6 6 0 0 1-.6 2.6l1.5 1.5A8 8 0 0 0 12 4zm0 14a6 6 0 0 1-6-6c0-.94.22-1.82.6-2.6L5.1 7.9A8 8 0 0 0 12 20v3l4-4-4-4v3z"/>',
  summarize:
    '<path fill="currentColor" d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z"/>',
  person_add:
    '<path fill="currentColor" d="M15 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-9-2V7H4v3H1v2h3v3h2v-3h3v-2H6zm9 4c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>',
  admin:
    '<path fill="currentColor" d="M12 1 3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/>',
  settings:
    '<path fill="currentColor" d="M19.14 12.94a7.49 7.49 0 0 0 0-1.88l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.3 7.3 0 0 0-1.62-.94l-.36-2.54a.5.5 0 0 0-.5-.42h-3.84a.5.5 0 0 0-.5.42l-.36 2.54c-.59.24-1.13.56-1.62.94l-2.39-.96a.5.5 0 0 0-.6.22L2.7 8.84a.5.5 0 0 0 .12.64l2.03 1.58a7.49 7.49 0 0 0 0 1.88L2.82 14.5a.5.5 0 0 0-.12.64l1.92 3.32c.14.24.42.34.66.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.04.24.25.42.5.42h3.84c.25 0 .46-.18.5-.42l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.24.12.52.02.66-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.04-1.56zM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7z"/>',
  chevron_right: '<path fill="currentColor" d="M10 6 8.6 7.4 13.2 12l-4.6 4.6L10 18l6-6z"/>',
  chevron_left: '<path fill="currentColor" d="M14 6l1.4 1.4L10.8 12l4.6 4.6L14 18l-6-6z"/>',
  arrow_up: '<path fill="currentColor" d="M4 12l1.4 1.4L11 7.8V20h2V7.8l5.6 5.6L20 12l-8-8z"/>',
  arrow_down: '<path fill="currentColor" d="M20 12l-1.4-1.4L13 16.2V4h-2v12.2l-5.6-5.6L4 12l8 8z"/>',
  unfold_more: '<path fill="currentColor" d="M12 5.83 15.17 9l1.41-1.41L12 3 7.41 7.59 8.83 9 12 5.83zm0 12.34L8.83 15l-1.41 1.41L12 21l4.59-4.59L15.17 15 12 18.17z"/>',
  filter: '<path fill="currentColor" d="M10 18h4v-2h-4v2zM3 6v2h18V6H3zm3 7h12v-2H6v2z"/>',
  filter_off:
    '<path fill="currentColor" d="M14.73 9.9 19 5.66V4H6.83l7.9 7.9zM2.41 2.13 1 3.54 8 10.55V17l4 4v-6.46l4.46 4.46 1.41-1.41L2.41 2.13z"/>',
  filter_outline:
    '<path fill="currentColor" d="M7 6h10l-5 6.28L7 6zm-2.75-.39C6.27 8.2 10 13 10 13v6c0 .55.45 1 1 1h2c.55 0 1-.45 1-1v-6s3.72-4.8 5.74-7.39A1 1 0 0 0 18.95 4H5.04a1 1 0 0 0-.79 1.61z"/>',
  groups:
    '<path fill="currentColor" d="M12 12.75c1.63 0 3.07.39 4.24.9 1.08.48 1.76 1.56 1.76 2.73V18H6v-1.61c0-1.18.68-2.26 1.76-2.73 1.17-.52 2.61-.91 4.24-.91zM4 13c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm1.13 1.1c-.37-.06-.74-.1-1.13-.1-.99 0-1.93.21-2.78.58A2.01 2.01 0 0 0 0 16.43V18h4.5v-1.61c0-.83.23-1.61.63-2.29zM20 13c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm4 3.43c0-.81-.48-1.53-1.22-1.85A6.95 6.95 0 0 0 20 14c-.39 0-.76.04-1.13.1.4.68.63 1.46.63 2.29V18H24v-1.57zM12 6c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3z"/>',
  event:
    '<path fill="currentColor" d="M19 4h-1V2h-2v2H8V2H6v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 16H5V10h14v10zM5 8V6h14v2H5z"/>',
  water_drop:
    '<path fill="currentColor" d="M12 2.69 17 8a6.5 6.5 0 1 1-10 0l5-5.31zM12 20a4.5 4.5 0 0 0 4.5-4.5c0-1.4-.95-3.3-2.5-5.18C12.7 12.13 12 13.6 12 14.5a1 1 0 0 1-2 0c0-1.2.6-2.6 1.3-3.9C9.4 12.6 8.5 14.3 8.5 15.5A3.5 3.5 0 0 0 12 19v1z"/>',
  warning:
    '<path fill="currentColor" d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>',
  check: '<path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/>',
  check_circle:
    '<path fill="currentColor" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm-2 15-5-5 1.4-1.4 3.6 3.6 7.6-7.6L19 8l-9 9z"/>',
  circle_outline:
    '<path fill="currentColor" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16z"/>',
  arrow_forward: '<path fill="currentColor" d="M12 4l-1.4 1.4L16.2 11H4v2h12.2l-5.6 5.6L12 20l8-8z"/>',
  fingerprint:
    '<path fill="currentColor" d="M17.81 4.47c-.08 0-.16-.02-.23-.06C15.66 3.42 14 3 12.01 3c-1.98 0-3.86.47-5.57 1.41a.5.5 0 1 1-.48-.88C7.82 2.52 9.86 2 12.01 2c2.13 0 3.99.47 6.03 1.52a.5.5 0 0 1-.23.95zM3.5 9.72a.5.5 0 0 1-.41-.79c.99-1.4 2.25-2.5 3.75-3.27C9.98 4.04 14 4.03 17.15 5.65c1.5.77 2.76 1.86 3.75 3.25a.5.5 0 1 1-.81.59 9.45 9.45 0 0 0-3.4-2.95c-2.87-1.47-6.54-1.47-9.4.01a9.3 9.3 0 0 0-3.4 2.96c-.1.13-.25.21-.39.21zM9.75 21.79a.5.5 0 0 1-.35-.15c-1.2-1.2-1.85-1.97-2.78-3.65-.95-1.71-1.45-3.8-1.45-6.05 0-4.15 3.54-7.53 7.89-7.53s7.89 3.38 7.89 7.53a.5.5 0 0 1-1 0c0-3.6-3.09-6.53-6.89-6.53S6.17 8.34 6.17 11.94c0 2.02.44 3.87 1.31 5.49.79 1.45 1.34 2.06 2.42 3.15.19.2.19.51 0 .71-.1.1-.23.15-.36.15z"/>',
  shield:
    '<path fill="currentColor" d="M12 1 3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/>',
  info: '<path fill="currentColor" d="M11 7h2v2h-2V7zm0 4h2v6h-2v-6zm1-9a10 10 0 1 0 0 20 10 10 0 0 0 0-20z"/>',
  rule: '<path fill="currentColor" d="M21 8H3V4h18v4zm0 4H3v-2h18v2zM10.5 19.5 8 17l-1.5 1.5L10.5 22 17 15.5 15.5 14l-5 5.5z"/>',
  logout:
    '<path fill="currentColor" d="M17 7l-1.4 1.4L18.2 11H8v2h10.2l-2.6 2.6L17 17l5-5-5-5zM4 5h8V3H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8v-2H4V5z"/>',
  account:
    '<path fill="currentColor" d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>',
  feedback:
    '<path fill="currentColor" d="M20 2H4a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2zm-7 12h-2v-2h2v2zm0-4h-2V6h2v4z"/>',
  support:
    '<path fill="currentColor" d="M21 12.22A9 9 0 0 0 3 12.22V18a2 2 0 0 0 2 2h2v-7H5v-.78a7 7 0 0 1 14 0V13h-2v7h2a2 2 0 0 0 2-2v-5.78z"/>',
  brightness:
    '<path fill="currentColor" d="M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zm0-7-2.5 4h5L12 2zm0 20 2.5-4h-5L12 22zM2 12l4 2.5v-5L2 12zm20 0-4-2.5v5L22 12zM5.6 5.6l.7 4.3 3-3-3.7-1.3zm12.8 12.8-.7-4.3-3 3 3.7 1.3zM5.6 18.4l3.7-1.3-3-3-.7 4.3zm12.8-12.8-3.7 1.3 3 3 .7-4.3z"/>',
  key: '<path fill="currentColor" d="M12.65 10A6 6 0 0 0 7 6a6 6 0 0 0 0 12 6 6 0 0 0 5.65-4H17v4h4v-4h2v-4H12.65zM7 14a2 2 0 1 1 0-4 2 2 0 0 1 0 4z"/>',
  open_in_new:
    '<path fill="currentColor" d="M19 19H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7h-2v7zM14 3v2h3.6l-9.8 9.8 1.4 1.4L19 6.4V10h2V3h-7z"/>',
  send: '<path fill="currentColor" d="M2 21l21-9L2 3v7l15 2-15 2v7z"/>',
  close: '<path fill="currentColor" d="M19 6.4 17.6 5 12 10.6 6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12z"/>',
  handshake:
    '<path fill="currentColor" d="M11 6 8.5 8.5a1.5 1.5 0 0 0 0 2.1 1.5 1.5 0 0 0 2.1 0L13 8.2l5 5V18a2 2 0 0 1-2 2h-1l-3-3-1 1-3-3-1 1-2-2a2 2 0 0 1 0-2.8L9 6h2zm2-2 3 3h4v7l-7-7-2 2-1-1 3-4z"/>',
  badge:
    '<path fill="currentColor" d="M20 7h-4V5l-2-2h-4L8 5v2H4a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2zm-10-2h4v2h-4V5zm2 6a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm4 8H8v-1c0-1.33 2.67-2 4-2s4 .67 4 2v1z"/>',
  volunteer:
    '<path fill="currentColor" d="M12 5.5 11 6.6a3 3 0 0 0 0 4.2 3 3 0 0 0 2 .8 3 3 0 0 0 2-.8l1-1.1a3 3 0 0 0-4-4.2zM2 13h4v8H2v-8zm6.5 7L7 18.5V13l3-3 4 4h5a2 2 0 0 1 2 2c0 .5-.4 1-1 1l-5 1-3.5 1z"/>',
  medal:
    '<path fill="currentColor" d="M12 2 8 6h8l-4-4zm0 6a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0 2.5 1 2 2.2.2-1.7 1.5.5 2.1-2-1.1-2 1.1.5-2.1L8.8 12.7 11 12.5l1-2z"/>',
  premium:
    '<path fill="currentColor" d="M12 2 9 8l-7 .6 5.3 4.6L5.8 20 12 16.3 18.2 20l-1.5-6.8L22 8.6 15 8l-3-6z"/>',
  diversity:
    '<path fill="currentColor" d="M12 4a2 2 0 1 1 0 4 2 2 0 0 1 0-4zM5 11a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm14 0a2 2 0 1 1 0 4 2 2 0 0 1 0-4zM12 9c2 0 3.5 1.3 3.5 3S14 15 12 15s-3.5-1.3-3.5-3S10 9 12 9zM5 16c1.4 0 2.8.9 2.8 2.2V20H2v-1.8C2 16.9 3.6 16 5 16zm14 0c1.4 0 3 .9 3 2.2V20h-5.8v-1.8c0-1.3 1.4-2.2 2.8-2.2zM12 16c2 0 4 1 4 2.5V20H8v-1.5C8 17 10 16 12 16z"/>',
  help: '<path fill="currentColor" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 17h-2v-2h2v2zm2.07-7.75-.9.92C13.45 12.9 13 13.5 13 15h-2v-.5c0-1.1.45-2.1 1.17-2.83l1.24-1.26A1.98 1.98 0 0 0 10 8a2 2 0 0 0-2 2H6a4 4 0 1 1 8 0c0 .88-.36 1.68-.93 2.25z"/>',
  group_outline:
    '<path fill="currentColor" d="M16 11c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 3-1.34 3-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>',
  menu_book:
    '<path fill="currentColor" d="M21 5c-1.1-.35-2.3-.5-3.5-.5-1.7 0-3.55.3-4.5 1V20c.95-.7 2.8-1 4.5-1 1.2 0 2.4.15 3.5.5V5zM12 5.5C11.05 4.8 9.2 4.5 7.5 4.5c-1.7 0-3.55.3-4.5 1V20c.95-.7 2.8-1 4.5-1s3.55.3 4.5 1V5.5z"/>',
  verified:
    '<path fill="currentColor" d="M23 12l-2.4-2.8.3-3.7-3.6-.8L15.4 1.5 12 3 8.6 1.5 6.7 4.7l-3.6.8.3 3.7L1 12l2.4 2.8-.3 3.7 3.6.8 1.9 3.2L12 21l3.4 1.5 1.9-3.2 3.6-.8-.3-3.7L23 12zm-12.9 4.5L6.5 13l1.4-1.4 2.2 2.2 5.2-5.2 1.4 1.4-6.6 6.5z"/>',
  compare: '<path fill="currentColor" d="M9.01 14H2v2h7.01v3L13 15l-3.99-4v3zm5.98-1v-3H22V8h-7.01V5L11 9l3.99 4z"/>',
  leaderboard:
    '<path fill="currentColor" d="M7.5 21H2V9h5.5v12zm7.25-18h-5.5v18h5.5V3zM22 11h-5.5v10H22V11z"/>',
  schedule:
    '<path fill="currentColor" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67V7z"/>',
  drive:
    '<path fill="currentColor" d="M7.71 3.5 1.15 15l3.43 6 6.56-11.5L7.71 3.5zM9.4 15l-3.27 5.73h13.13L22.5 15H9.4zm13.45-1.27L16.29 2.27h-6.5l6.56 11.46h6.5z"/>',
  table:
    '<path fill="currentColor" d="M3 3h18a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm1 4v3h7V7H4zm9 0v3h7V7h-7zm-9 5v3h7v-3H4zm9 0v3h7v-3h-7zm-9 5v2h7v-2H4zm9 0v2h7v-2h-7z"/>',
  link_off:
    '<path fill="currentColor" d="M17 7h-4v1.9h4a3.1 3.1 0 0 1 0 6.2h-1.5l1.9 1.9H17a5 5 0 0 0 .9-9.96L17 7zM3.5 2.6 2.1 4l4.3 4.3A5 5 0 0 0 7 18h4v-1.9H7a3.1 3.1 0 0 1-.5-6.16L8.4 12H7v1.9h3.3l9.3 9.3 1.4-1.4L3.5 2.6zM13 12h.8l-1.9-1.9H11V12h2z"/>',
  play: '<path fill="currentColor" d="M8 5v14l11-7z"/>',
  pause: '<path fill="currentColor" d="M6 5h4v14H6V5zm8 0h4v14h-4V5z"/>',
  date_range:
    '<path fill="currentColor" d="M9 11H7v2h2v-2zm4 0h-2v2h2v-2zm4 0h-2v2h2v-2zm2-7h-1V2h-2v2H8V2H6v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 16H5V9h14v11z"/>',
  sort: '<path fill="currentColor" d="M3 18h6v-2H3v2zM3 6v2h18V6H3zm0 7h12v-2H3v2z"/>',
  commit:
    '<path fill="currentColor" d="M17.8 11A6 6 0 0 0 6.2 11H2v2h4.2a6 6 0 0 0 11.6 0H22v-2h-4.2zM12 15a3 3 0 1 1 0-6 3 3 0 0 1 0 6z"/>',
  cloud_sync:
    '<path fill="currentColor" d="M19.4 9A7 7 0 0 0 6 7a5 5 0 0 0-.7 9.95l.3-1.97A3 3 0 0 1 6 9h1l.2-.94A5 5 0 0 1 17 9.5l.13.97A3.5 3.5 0 0 1 19 16h-2.1l1.95 1.95A5.5 5.5 0 0 0 19.4 9zM12 12l-3 3h2v4h2v-4h2l-3-3z"/>',
  storage:
    '<path fill="currentColor" d="M2 20h20v-4H2v4zm2-3h2v2H4v-2zM2 4v4h20V4H2zm4 3H4V5h2v2zm-4 7h20v-4H2v4zm2-3h2v2H4v-2z"/>',
  photo:
    '<path fill="currentColor" d="M12 12.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM9 4 7.2 6H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-3.2L15 4H9zm3 13.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z"/>',
  copy: '<path fill="currentColor" d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11v14z"/>',
  replay:
    '<path fill="currentColor" d="M12 5V1L7 6l5 5V7a6 6 0 1 1-6 6H4a8 8 0 1 0 8-8z"/>',
  error: '<path fill="currentColor" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>',
  history:
    '<path fill="currentColor" d="M13 3a9 9 0 0 0-9 9H1l3.9 3.9.07.14L9 12H6a7 7 0 1 1 7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.98 8.98 0 1 0 13 3zm-1 5v5l4.25 2.52.75-1.23-3.5-2.08V8H12z"/>',
  history_off:
    '<path fill="currentColor" d="M2.4 2.1 1 3.5l3.5 3.5A9 9 0 1 0 13 3v2a7 7 0 1 1-6.6 4.6l1.6 1.6V8L4.9 9.7 2.4 2.1zM12 8v3.6l1.9 1.9.6-1L13.5 11V8H12z"/>',
  favorite:
    '<path fill="currentColor" d="M12 21.35 10.55 20C5.4 15.36 2 12.27 2 8.5 2 5.41 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.08C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.41 22 8.5c0 3.77-3.4 6.86-8.55 11.53L12 21.35z"/>',
  library:
    '<path fill="currentColor" d="M4 6H2v14a2 2 0 0 0 2 2h14v-2H4V6zm16-4H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2zm-7 12V6l5 4-5 4z"/>',
  mail: '<path fill="currentColor" d="M20 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 4-8 5-8-5V6l8 5 8-5v2z"/>',
  note: '<path fill="currentColor" d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h9l7-7V5a2 2 0 0 0-2-2zm-6 14v-4a1 1 0 0 1 1-1h4l-5 5z"/>',
  account_balance:
    '<path fill="currentColor" d="M4 10h3v7H4v-7zm6.5 0h3v7h-3v-7zM2 19h20v3H2v-3zm15-9h3v7h-3v-7zm-5-9L2 6v2h20V6L12 1z"/>',
  visibility:
    '<path fill="currentColor" d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-8a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/>',
  visibility_off:
    '<path fill="currentColor" d="M12 7a5 5 0 0 1 5 5c0 .65-.13 1.26-.36 1.83l2.92 2.92A11.82 11.82 0 0 0 23 12c-1.73-4.39-6-7.5-11-7.5-1.4 0-2.74.25-3.98.7l2.16 2.16C10.74 7.13 11.35 7 12 7zM2 4.27l2.28 2.28.46.46A11.8 11.8 0 0 0 1 12c1.73 4.39 6 7.5 11 7.5 1.55 0 3.03-.3 4.38-.84l.42.42L19.73 22 21 20.73 3.27 3 2 4.27zM7.53 9.8l1.55 1.55a3 3 0 0 0 3.57 3.57l1.55 1.55A4.98 4.98 0 0 1 7 12c0-.79.18-1.53.53-2.2zm4.31-.78 3.15 3.14L15 12a3 3 0 0 0-3-3l-.16.02z"/>',
};

export function Icon({ name, size = 20, color, title, style, className }: Props) {
  const inner = PATHS[name] ?? PATHS.help;
  return (
    <svg
      className={className ? `icon ${className}` : 'icon'}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      style={{ color, display: 'inline-block', verticalAlign: 'middle', flexShrink: 0, ...style }}
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
      dangerouslySetInnerHTML={{ __html: title ? `<title>${title}</title>${inner}` : inner }}
    />
  );
}
