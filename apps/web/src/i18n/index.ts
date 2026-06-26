// Localization (i18n) foundation. react-i18next with English / Spanish / Russian bundles. Strings are
// keyed (e.g. t('maintenance.title')); anything not yet translated falls back to English, so adding a
// language never blanks the UI and migrating a string is incremental + safe. The active language is
// remembered in localStorage and mirrored onto <html lang> (correct screen-reader pronunciation +
// hyphenation — an accessibility win too). Expand coverage by adding keys to the locale JSON + swapping
// a hardcoded string for t('…'); see apps/web/src/i18n/locales/*.json.

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import en from './locales/en.json';
import es from './locales/es.json';
import ru from './locales/ru.json';

export const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Español' },
  { code: 'ru', label: 'Русский' },
] as const;
export type LangCode = (typeof SUPPORTED_LANGUAGES)[number]['code'];

const STORAGE_KEY = 'cp:lang';

function initialLang(): LangCode {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && SUPPORTED_LANGUAGES.some((l) => l.code === saved)) return saved as LangCode;
  } catch { /* private mode */ }
  const nav = (navigator.language || 'en').slice(0, 2).toLowerCase();
  return SUPPORTED_LANGUAGES.some((l) => l.code === nav) ? (nav as LangCode) : 'en';
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, es: { translation: es }, ru: { translation: ru } },
  lng: initialLang(),
  fallbackLng: 'en',
  interpolation: { escapeValue: false }, // React already escapes
  returnNull: false,
});

function syncHtmlLang(lng: string) {
  try { document.documentElement.lang = lng; } catch { /* noop */ }
}
syncHtmlLang(i18n.language);
i18n.on('languageChanged', (lng) => {
  syncHtmlLang(lng);
  try { localStorage.setItem(STORAGE_KEY, lng); } catch { /* private mode */ }
});

/** Change the active language (persisted + reflected on <html lang>). */
export function setLanguage(code: LangCode): void {
  void i18n.changeLanguage(code);
}

export default i18n;
