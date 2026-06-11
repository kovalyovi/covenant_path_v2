// Recent-logins email masking (admin console): first char of the local part + up to four `*`,
// domain kept visible. The eye toggle reveals the full address; this pins the mask itself.

import { describe, it, expect } from 'vitest';
import { maskEmail } from '../logic/mask';

describe('maskEmail', () => {
  it('keeps the first character and caps at four stars, domain visible', () => {
    expect(maskEmail('ilia.kovaliov@gmail.com')).toBe('i****@gmail.com');
  });

  it('uses fewer stars for short local parts', () => {
    expect(maskEmail('bob@x.org')).toBe('b**@x.org');
  });

  it('still masks a one-char local part with one star', () => {
    expect(maskEmail('a@x.org')).toBe('a*@x.org');
  });

  it('masks an @-less string as a bare username', () => {
    expect(maskEmail('username')).toBe('u****');
  });

  it('passes empty / degenerate input through', () => {
    expect(maskEmail('')).toBe('');
    expect(maskEmail('@x.org')).toBe('@x.org');
  });
});
