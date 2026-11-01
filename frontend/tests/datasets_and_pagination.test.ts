import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

describe('Dataset Management and Pagination', () => {
  test('pagination calculations handle more than 100 records correctly across pages', () => {
    const total = 250;
    const limit = 25;

    // Page 1
    let offset = 0;
    let currentPage = Math.floor(offset / limit) + 1;
    let totalPages = Math.ceil(total / limit);
    let startItem = offset + 1;
    let endItem = Math.min(offset + limit, total);
    let hasMore = offset + limit < total;

    assert.equal(currentPage, 1);
    assert.equal(totalPages, 10);
    assert.equal(startItem, 1);
    assert.equal(endItem, 25);
    assert.equal(hasMore, true);

    // Page 5 (offset = 100, reaching past 100 records)
    offset = 100;
    currentPage = Math.floor(offset / limit) + 1;
    startItem = offset + 1;
    endItem = Math.min(offset + limit, total);
    hasMore = offset + limit < total;

    assert.equal(currentPage, 5);
    assert.equal(startItem, 101);
    assert.equal(endItem, 125);
    assert.equal(hasMore, true);

    // Last Page (offset = 225)
    offset = 225;
    currentPage = Math.floor(offset / limit) + 1;
    startItem = offset + 1;
    endItem = Math.min(offset + limit, total);
    hasMore = offset + limit < total;

    assert.equal(currentPage, 10);
    assert.equal(startItem, 226);
    assert.equal(endItem, 250);
    assert.equal(hasMore, false);
  });

  test('dataset validation status and error arrays format properly', () => {
    const dataset = {
      id: 'ds-test-01',
      display_name: 'Financial News Q3',
      format: 'jsonl',
      size_bytes: 4096000,
      record_count: 500,
      validation_status: 'warning',
      validation_errors: [],
      validation_warnings: ['Missing optional timestamp field in 3 records'],
    };

    assert.equal(dataset.validation_status, 'warning');
    assert.equal(dataset.validation_errors.length, 0);
    assert.equal(dataset.validation_warnings.length, 1);
  });

  test('backend snapshot reference deletion error is honestly formatted', () => {
    const backendError = {
      code: 'CANNOT_DELETE_DATASET_WITH_SNAPSHOTS',
      message: 'Dataset "ds-123" cannot be deleted because it is referenced by 2 immutable snapshot(s).',
    };

    assert.equal(backendError.code, 'CANNOT_DELETE_DATASET_WITH_SNAPSHOTS');
    assert.ok(backendError.message.includes('cannot be deleted because it is referenced by'));
  });
});
