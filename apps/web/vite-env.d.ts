/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string;
  readonly VITE_SUPABASE_ANON_KEY: string;
  readonly VITE_BROKER_URL: string;
  readonly VITE_SENTRY_DSN: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// WebAuthn passkey bridge exposed by public/passkey.js (window.cpPasskey).
interface Window {
  cpPasskey?: {
    supported: () => boolean;
    create: (optionsJson: string) => Promise<string>;
    get: (optionsJson: string) => Promise<string>;
  };
}
