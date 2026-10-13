import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { setTimeout } from 'node:timers/promises';
import { ApiClient } from '../client';
import { SystemService } from '../system';
import { DatasetBuildsService } from '../datasetBuilds';
import { JobsService } from '../jobs';
import { AttemptsService } from '../attempts';
import { StepsService } from '../steps';
import { CheckpointsService } from '../checkpoints';

const baseUrl = process.env.PBL4_API_SMOKE_URL;
test('Frontend API clients complete a real DBS Job through the real Backend', {
  skip: !baseUrl,
  timeout: 120_000,
}, async () => {
  const client = new ApiClient(baseUrl!);
  const system = new SystemService(client);
  const jobs = new JobsService(client);
  const attempts = new AttemptsService(client);
  const buildId = process.env.PBL4_API_SMOKE_BUILD_ID!;
  const build = (await new DatasetBuildsService(client).getBuild(buildId)).data;
  assert.equal(build.state, 'READY');
  const nodes = (await system.getNodes()).data.filter(n => n.state === 'ONLINE');
  assert.equal(nodes.length, build.shard_count);
  assert.ok((await system.getCapabilities()).data.supported_models.some(m => m.model_id === 'small_cnn'));
  await system.getHealth();
  const job = (await jobs.createJob({
    display_name: 'Phase 2 real frontend API DBS workflow',
    requested_contract: {
      dataset_build_id: buildId, model_id: 'small_cnn', epochs: 3,
      learning_rate: 0.01, training_seed: 20260910, training_strategy: 'strict_bsp',
      workload_policy: 'dbs', work_units_per_step: 6,
    },
  })).data;
  assert.deepEqual((await jobs.validateJob(job.job_id)).data.errors, []);
  const started = (await jobs.startJob(job.job_id, { node_ids: nodes.map(n => n.node_id) })).data;
  const frozen = (await jobs.getJob(job.job_id)).data;
  assert.equal(frozen.resolved_contract?.workload?.policy, 'dbs');
  assert.equal(frozen.resolved_contract?.workload?.work_units_per_step, 6);
  assert.equal(frozen.resolved_contract?.dataset.dataset_build_id, buildId);
  const deadline = Date.now() + 90_000;
  let attempt = (await attempts.getAttempt(started.attempt_id)).data;
  while (!['COMPLETED', 'FAILED', 'ABORTED'].includes(attempt.state) && Date.now() < deadline) {
    await setTimeout(250);
    attempt = (await attempts.getAttempt(started.attempt_id)).data;
  }
  assert.equal(attempt.state, 'COMPLETED');
  assert.equal(attempt.model_version, 6);
  const steps = (await new StepsService(client).listSteps(started.attempt_id, { limit: 200 })).data;
  assert.equal(steps.length, 6);
  assert.ok(steps.every(s => s.state === 'COMMITTED'));
  const checkpoints = (await new CheckpointsService(client).listCheckpoints({ attempt_id: started.attempt_id, limit: 200 })).data;
  assert.equal(checkpoints.length, 6);
  assert.ok(checkpoints.every(c => c.state === 'COMPLETE'));
  if (process.env.PBL4_API_SMOKE_EVIDENCE) {
    fs.writeFileSync(process.env.PBL4_API_SMOKE_EVIDENCE, JSON.stringify({
      verdict: 'PASS', base_url: baseUrl, job_id: job.job_id, attempt_id: started.attempt_id,
      dataset_build_id: buildId, model_id: 'small_cnn', policy: 'dbs', K: 6,
      node_ids: nodes.map(n => n.node_id), steps: steps.length,
      model_version: attempt.model_version, checkpoints: checkpoints.length,
    }, null, 2));
  }
});
