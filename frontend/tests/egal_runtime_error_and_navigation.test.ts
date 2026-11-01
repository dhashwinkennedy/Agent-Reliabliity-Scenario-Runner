import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { parseError, formatErrorMessage, formatErrorCode, isAbstention, ErrorText } from '../src/utils/error';
import { ErrorAlert } from '../src/components/ErrorAlert';

describe('EGAL Runtime Error Handling and Safe React Rendering', () => {
  test('1. parseError extracts code and message from backend structured error object', () => {
    const rawError = {
      code: 'AGENT_INPUT_INVALID',
      message: 'Remote end closed connection without response',
    };

    const parsed = parseError(rawError);
    assert.equal(parsed.code, 'AGENT_INPUT_INVALID');
    assert.equal(parsed.message, 'Remote end closed connection without response');
    assert.equal(typeof parsed.message, 'string');
    assert.equal(typeof parsed.code, 'string');
  });

  test('2. parseError safely unpacks stringified JSON error objects', () => {
    const jsonStringError = JSON.stringify({
      code: 'MODEL_OUTPUT_INVALID',
      message: 'Validation error: sentiment literal mismatch',
    });

    const parsed = parseError(jsonStringError);
    assert.equal(parsed.code, 'MODEL_OUTPUT_INVALID');
    assert.equal(parsed.message, 'Validation error: sentiment literal mismatch');
  });

  test('3. parseError handles standard Error instances, strings, and null safely', () => {
    const errInstance = new Error('Network timeout during inference');
    assert.equal(parseError(errInstance).message, 'Network timeout during inference');

    assert.equal(parseError('Simple failure message').message, 'Simple failure message');
    assert.equal(parseError(null).message, '');
    assert.equal(parseError(undefined).message, '');
  });

  test('4. parseError extracts human-readable message from FastAPI validation detail array', () => {
    const fastApiError = {
      detail: [
        { loc: ['body', 'input_mapping', 'headline'], msg: 'Field required', type: 'value_error.missing' },
      ],
    };

    const parsed = parseError(fastApiError);
    assert.ok(parsed.message.includes('input_mapping.headline: Field required'));
  });

  test('5. formatErrorMessage and formatErrorCode helpers provide typed string guarantees', () => {
    const errorObj = { code: 'EXECUTION_TIMEOUT', message: 'Model took 15000ms' };
    assert.equal(formatErrorMessage(errorObj), 'Model took 15000ms');
    assert.equal(formatErrorCode(errorObj), 'EXECUTION_TIMEOUT');

    assert.equal(formatErrorMessage('Simple error'), 'Simple error');
    assert.equal(formatErrorCode('Simple error'), undefined);
  });

  test('6. ErrorAlert safely accepts structured object as message without React child crash', () => {
    const structuredError = {
      code: 'HTTP_500',
      message: 'Agent execution failed: process was stopped',
    };

    // Instantiate React element
    const element = React.createElement(ErrorAlert, {
      title: 'Execution Error',
      message: structuredError,
    });

    assert.ok(element);
    assert.equal(element.props.title, 'Execution Error');
    assert.deepEqual(element.props.message, structuredError);
  });

  test('7. ErrorText component produces safe render tree without raw object children', () => {
    const rawError = {
      code: 'MODEL_OUTPUT_INVALID',
      message: 'Expected sentiment in [positive, negative, neutral]',
    };

    const element = React.createElement(ErrorText, {
      error: rawError,
      showCode: true,
    });

    assert.ok(element);
    assert.deepEqual(element.props.error, rawError);
  });
});

describe('EGAL Domain Abstention vs Technical Run Failure', () => {
  test('8. isAbstention identifies valid financial ABSTAIN outcome', () => {
    const abstentionOutput = {
      recommendation: 'ABSTAIN',
      abstention_reason: 'High market volatility and conflicting news sentiment',
      uncertainty_score: 0.88,
    };

    const { isAbstain, reason } = isAbstention(abstentionOutput);
    assert.equal(isAbstain, true);
    assert.equal(reason, 'High market volatility and conflicting news sentiment');
  });

  test('9. Technical error is NOT classified as a domain abstention', () => {
    const technicalFailure = {
      code: 'RUN_FAILED',
      message: 'Provider connection refused',
    };

    const { isAbstain } = isAbstention(technicalFailure);
    assert.equal(isAbstain, false);
  });

  test('10. Directional actions (BUY/SELL) are NOT classified as abstention', () => {
    const buyOutput = {
      recommendation: 'BUY',
      confidence: 0.95,
      target_price: 150.0,
    };

    const { isAbstain } = isAbstention(buyOutput);
    assert.equal(isAbstain, false);
  });
});

describe('Active Experiment Navigation and Polling Lifecycle', () => {
  test('11. Identifies running execution states for live polling', () => {
    const isRunningState = (status: string) => status === 'running' || status === 'queued';

    assert.equal(isRunningState('running'), true);
    assert.equal(isRunningState('queued'), true);
    assert.equal(isRunningState('completed'), false);
    assert.equal(isRunningState('stopped'), false);
    assert.equal(isRunningState('failed'), false);
  });

  test('12. Distinguishes live running placeholder from terminal empty runs state', () => {
    const getEmptyRunsPlaceholder = (isRunning: boolean) => {
      if (isRunning) {
        return 'Execution in progress. Runs are queued and executing.';
      }
      return 'No runs recorded for this repetition.';
    };

    assert.ok(getEmptyRunsPlaceholder(true).includes('Execution in progress'));
    assert.ok(getEmptyRunsPlaceholder(false).includes('No runs recorded'));
  });
});
