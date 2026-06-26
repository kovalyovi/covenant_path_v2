// Language picker (EN / ES / RU). Persists the choice + updates <html lang>; untranslated strings
// fall back to English. Drop into Settings — the foundation for a full localization pass.

import { useTranslation } from 'react-i18next';
import { SUPPORTED_LANGUAGES, setLanguage, type LangCode } from '../i18n';

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  return (
    <div style={{ display: 'grid', gap: 6 }}>
      <label htmlFor="cp-lang" style={{ fontWeight: 600 }}>{t('settings.language')}</label>
      <div className="muted" style={{ fontSize: 13 }}>{t('settings.languageHelp')}</div>
      <select
        id="cp-lang"
        value={(i18n.language || 'en').slice(0, 2)}
        onChange={(e) => setLanguage(e.target.value as LangCode)}
        style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border, #444)',
                 background: 'var(--surface, transparent)', color: 'inherit', maxWidth: 240 }}
      >
        {SUPPORTED_LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
      </select>
    </div>
  );
}
