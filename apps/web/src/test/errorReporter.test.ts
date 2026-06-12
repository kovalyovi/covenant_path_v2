import { describe, it, expect } from 'vitest';
import { scrub } from '../lib/errorReporter';

// CLIENT-04: client error telemetry must not forward member PII to the broker /log sink.
describe('errorReporter.scrub', () => {
  it('strips emails, URLs, and long digit runs', () => {
    const out = scrub('failed for a@b.com at https://x.test/p?token=secret123 id=1234567');
    expect(out).not.toContain('a@b.com');
    expect(out).not.toContain('https://x.test');
    expect(out).not.toContain('1234567');
    expect(out).toContain('<email>');
    expect(out).toContain('<url>');
    expect(out).toContain('<num>');
  });

  it('caps length at 300', () => {
    expect(scrub('x'.repeat(500)).length).toBeLessThanOrEqual(300);
  });
});
