// Display-only masking for login emails on the admin console (shoulder-surfing protection — the
// data itself stays admin-only via RLS). The local part keeps its first character plus up to four
// `*`; the domain stays visible so rows remain distinguishable.
export function maskEmail(email: string): string {
  const at = email.indexOf('@');
  const local = at >= 0 ? email.slice(0, at) : email;
  const domain = at >= 0 ? email.slice(at) : '';
  if (!local) return email;
  const stars = Math.min(Math.max(local.length - 1, 1), 4);
  return local[0] + '*'.repeat(stars) + domain;
}
