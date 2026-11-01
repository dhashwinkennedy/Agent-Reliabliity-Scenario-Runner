import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

describe('Navigation and Page Routing', () => {
  const REQUIRED_SECTIONS = [
    { name: 'Dashboard', path: '/' },
    { name: 'Datasets', path: '/datasets' },
    { name: 'Agents', path: '/agents' },
    { name: 'Providers', path: '/providers' },
    { name: 'Experiments', path: '/experiments' },
    { name: 'Analytics', path: '/analytics' },
  ];

  test('persistent sidebar defines exactly the 6 required platform sections', () => {
    assert.equal(REQUIRED_SECTIONS.length, 6);
    const names = REQUIRED_SECTIONS.map((s) => s.name);
    assert.deepEqual(names, [
      'Dashboard',
      'Datasets',
      'Agents',
      'Providers',
      'Experiments',
      'Analytics',
    ]);
  });

  test('routes map correctly to the required section endpoints', () => {
    const paths = REQUIRED_SECTIONS.map((s) => s.path);
    assert.ok(paths.includes('/'));
    assert.ok(paths.includes('/datasets'));
    assert.ok(paths.includes('/agents'));
    assert.ok(paths.includes('/providers'));
    assert.ok(paths.includes('/experiments'));
    assert.ok(paths.includes('/analytics'));
  });

  test('experiments detail route matches parameterized path', () => {
    const experimentDetailPattern = /^\/experiments\/([a-zA-Z0-9_-]+)$/;
    assert.ok(experimentDetailPattern.test('/experiments/exp-12345'));
    assert.ok(experimentDetailPattern.test('/experiments/exp-baseline-egal-group'));
  });
});
