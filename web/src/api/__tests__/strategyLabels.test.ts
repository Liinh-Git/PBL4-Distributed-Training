import test from 'node:test';
import assert from 'node:assert/strict';
import { formatStrategy } from '../../utils/date';

test('strategy labels distinguish async, strict BSP, missing and unknown codes', () => {
  assert.equal(formatStrategy('async_sgd'), 'Async-SGD');
  assert.equal(formatStrategy('strict_bsp'), 'Đồng bộ chặt');
  assert.equal(formatStrategy(undefined), 'Chưa xác định');
  assert.equal(formatStrategy('future_strategy'), 'future_strategy');
});
