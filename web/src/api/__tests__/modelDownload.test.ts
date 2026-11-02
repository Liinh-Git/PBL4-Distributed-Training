import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ApiClient } from '../client';
import { CheckpointsService } from '../checkpoints';
import { ModelDownloadLink } from '../../components/common/ModelDownloadLink';

test('model download targets Management Backend and encodes opaque IDs as one segment', () => {
  const service = new CheckpointsService(new ApiClient('https://management.example/'));
  assert.equal(service.modelDownloadUrl('id/with?characters#'),
    'https://management.example/api/v1/checkpoints/id%2Fwith%3Fcharacters%23/model');
});

test('native download link preserves the app and does not use the JSON response cache', () => {
  const html = renderToStaticMarkup(React.createElement(ModelDownloadLink, { checkpointId: 'saved-model' }));
  assert.match(html, /href="[^"]*\/api\/v1\/checkpoints\/saved-model\/model"/);
  assert.match(html, /download=""/);
  assert.match(html, /target="_blank"/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.match(html, /Tải model/);
  assert.doesNotMatch(html, /9002|Bearer|RUNTIME_ARTIFACT_TOKEN/);
});
