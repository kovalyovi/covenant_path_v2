// Regression for the ops "Missing: [object Object], …" bug (2026-06-18): the enrolled-stakes card
// joined `coverage.missing`, which is a list of {feature, granted_by, …} OBJECTS, so `.join(', ')`
// rendered "[object Object]". formatMissingFeatures maps each to its feature label instead.

import { describe, expect, it } from 'vitest';
import { formatMissingFeatures } from '../logic/coverage';

describe('formatMissingFeatures', () => {
  it('renders feature labels, not [object Object], for the object shape', () => {
    const missing = [
      { feature: 'Ward leadership', granted_by: ['Bishop'], also_unnamed_roles: 0 },
      { feature: 'Temple recommend status', granted_by: [], also_unnamed_roles: 2 },
    ];
    const out = formatMissingFeatures(missing);
    expect(out).toBe('Ward leadership, Temple recommend status');
    expect(out).not.toContain('[object Object]');
  });

  it('passes legacy plain strings through unchanged', () => {
    expect(formatMissingFeatures(['Sacrament attendance', 'Ministering'])).toBe(
      'Sacrament attendance, Ministering',
    );
  });

  it('drops blank/featureless entries and tolerates non-arrays', () => {
    expect(formatMissingFeatures([{ granted_by: ['x'] }, { feature: 'Callings' }])).toBe('Callings');
    expect(formatMissingFeatures(undefined)).toBe('');
    expect(formatMissingFeatures(null)).toBe('');
  });
});
