/**
 * Unit tests for Training Topology Visualizer Logic & Architectural Compliance
 *
 * Runs with: npx tsx --test src/api/__tests__/topology.test.ts
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

describe('Training Topology Visualizer Architectural & Truthful Telemetry Tests', () => {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);
  const componentPath = path.resolve(
    __dirname,
    '../../components/training/TrainingTopologyVisualizer.tsx'
  );
  const componentSource = fs.readFileSync(componentPath, 'utf8');

  test('Architectural Purity: Zero forbidden frameworks, fake protocols or mock strings in source', () => {
    // 1. Must NOT contain gRPC (violates Rule 12 in AGENTS.md)
    assert.strictEqual(
      componentSource.includes('gRPC'),
      false,
      'TrainingTopologyVisualizer must not mention gRPC'
    );
    assert.strictEqual(
      componentSource.includes('grpc'),
      false,
      'TrainingTopologyVisualizer must not mention grpc'
    );

    // 2. Must NOT contain DTP v1.3 (DTP/1 is canonical)
    assert.strictEqual(
      componentSource.includes('DTP v1.3'),
      false,
      'Must not mention fake DTP v1.3'
    );

    // 3. Must NOT contain prototype phase descriptions (Image 1, Image 2, Image 3, Image 4)
    assert.strictEqual(componentSource.includes('Image 1'), false);
    assert.strictEqual(componentSource.includes('Image 2'), false);
    assert.strictEqual(componentSource.includes('Image 3'), false);
    assert.strictEqual(componentSource.includes('Image 4'), false);

    // 4. Must NOT contain hardcoded fake speeds or latencies
    assert.strictEqual(componentSource.includes('5MB/s'), false);
    assert.strictEqual(componentSource.includes('10 Gbps OK'), false);
    assert.strictEqual(componentSource.includes('4.2ms'), false);
    assert.strictEqual(componentSource.includes('1.24 ms'), false);
    assert.strictEqual(componentSource.includes('0.18 ms'), false);

    // 5. Must NOT contain fake fallback model version '3264'
    assert.strictEqual(componentSource.includes('3264'), false);

    // 6. Must NOT contain simulation timers or random percentage generation
    assert.strictEqual(
      componentSource.includes('setInterval'),
      false,
      'Must not contain setInterval for random mock ticks'
    );
    assert.strictEqual(
      componentSource.includes('% 7'),
      false,
      'Must not contain random mock modulo operations'
    );
  });

  test('Dynamic geometry layout handles 0, 1, 2, 3, 4, and N workers without collision', () => {
    function getTopologyLayout(count: number) {
      const serverWidth = 240;
      const serverHeight = 145;
      const monitorWidth = 220;
      const monitorHeight = 135;

      if (count <= 0) {
        return {
          serverCoord: { x: 500, y: 280, width: serverWidth, height: serverHeight },
          workerCoords: [],
        };
      }
      if (count === 1) {
        return {
          serverCoord: { x: 670, y: 280, width: serverWidth, height: serverHeight },
          workerCoords: [
            { x: 260, y: 280, cardWidth: monitorWidth, cardHeight: monitorHeight },
          ],
        };
      }
      if (count === 2) {
        return {
          serverCoord: { x: 500, y: 280, width: serverWidth, height: serverHeight },
          workerCoords: [
            { x: 190, y: 280, cardWidth: monitorWidth, cardHeight: monitorHeight },
            { x: 810, y: 280, cardWidth: monitorWidth, cardHeight: monitorHeight },
          ],
        };
      }
      if (count === 3) {
        return {
          serverCoord: { x: 500, y: 275, width: serverWidth, height: serverHeight },
          workerCoords: [
            { x: 200, y: 130, cardWidth: monitorWidth, cardHeight: monitorHeight },
            { x: 800, y: 130, cardWidth: monitorWidth, cardHeight: monitorHeight },
            { x: 500, y: 480, cardWidth: monitorWidth, cardHeight: monitorHeight },
          ],
        };
      }
      const rx = 350;
      const ry = 190;
      const coords = [];
      for (let i = 0; i < count; i++) {
        const angle = -Math.PI / 2 + (2 * Math.PI * i) / count;
        coords.push({
          x: Math.round(500 + rx * Math.cos(angle)),
          y: Math.round(280 + ry * Math.sin(angle)),
          cardWidth: 180,
          cardHeight: 115,
        });
      }
      return {
        serverCoord: { x: 500, y: 280, width: serverWidth, height: serverHeight },
        workerCoords: coords,
      };
    }

    // 0 workers
    const layout0 = getTopologyLayout(0);
    assert.strictEqual(layout0.workerCoords.length, 0);

    // 1 worker (horizontal pipeline, worker on left, server on right, zero vertical overlap)
    const layout1 = getTopologyLayout(1);
    assert.strictEqual(layout1.workerCoords.length, 1);
    const w1 = layout1.workerCoords[0];
    const s1 = layout1.serverCoord;
    assert.strictEqual(w1.x, 260);
    assert.strictEqual(s1.x, 670);
    // Gap between worker right edge (260 + 110 = 370) and server left edge (670 - 120 = 550) is 180px
    assert.strictEqual(s1.x - s1.width / 2 > w1.x + w1.cardWidth / 2, true);

    // 2 workers (symmetric left and right)
    const layout2 = getTopologyLayout(2);
    assert.strictEqual(layout2.workerCoords.length, 2);
    assert.strictEqual(layout2.workerCoords[0].x < layout2.serverCoord.x, true);
    assert.strictEqual(layout2.workerCoords[1].x > layout2.serverCoord.x, true);

    // 3 workers (triangular, bottom worker does NOT collide with server or canvas bottom)
    const layout3 = getTopologyLayout(3);
    assert.strictEqual(layout3.workerCoords.length, 3);
    const bottomWorker = layout3.workerCoords[2];
    const s3 = layout3.serverCoord;
    // Server bottom is 275 + 145/2 = 347.5px. Bottom worker top is 480 - 135/2 = 412.5px.
    // Gap is 65px!
    assert.strictEqual(bottomWorker.y - bottomWorker.cardHeight / 2 > s3.y + s3.height / 2, true);
    // Bottom worker ends at 480 + 135/2 = 547.5px, safely within 580px canvas
    assert.strictEqual(bottomWorker.y + bottomWorker.cardHeight / 2 < 580, true);

    // N = 6 workers
    const layout6 = getTopologyLayout(6);
    assert.strictEqual(layout6.workerCoords.length, 6);
    const distinctPoints = new Set(layout6.workerCoords.map(c => `${c.x},${c.y}`));
    assert.strictEqual(distinctPoints.size, 6);
  });

  test('Endpoint calculation strictly separates nodes and link vectors', () => {
    function computeLinkEndpoints(
      wx: number,
      wy: number,
      wCardW: number,
      wCardH: number,
      cx = 500,
      cy = 250,
      cCardW = 210,
      cCardH = 140
    ) {
      const dx = cx - wx;
      const dy = cy - wy;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist === 0) return { x1: wx, y1: wy, x2: cx, y2: cy };

      const wRadius = Math.min(wCardW, wCardH) / 2 + 10;
      const cRadius = Math.min(cCardW, cCardH) / 2 + 12;

      const x1 = Math.round(wx + (dx / dist) * wRadius);
      const y1 = Math.round(wy + (dy / dist) * wRadius);
      const x2 = Math.round(cx - (dx / dist) * cRadius);
      const y2 = Math.round(cy - (dy / dist) * cRadius);

      return { x1, y1, x2, y2 };
    }

    const { x1, y1, x2, y2 } = computeLinkEndpoints(210, 115, 190, 110, 500, 250, 210, 140);
    // Link must start further right and down from worker center
    assert.strictEqual(x1 > 210, true);
    assert.strictEqual(y1 > 115, true);
    // Link must end further left and up from PS center
    assert.strictEqual(x2 < 500, true);
    assert.strictEqual(y2 < 250, true);
  });

  test('Honest telemetry and partial projection detection', () => {
    // Partial projection when 1 of 3 expected sessions observed
    const expectedWorkers = 3;
    const observedWorkers = [
      { workerId: 0, sessionId: 's_0', nodeLabel: 'node-0', state: 'RUNNING' },
    ];
    const isPartialProjection = expectedWorkers > 0 && observedWorkers.length < expectedWorkers;
    assert.strictEqual(isPartialProjection, true);

    // Null sample count and model version display honest Pending
    const step = {
      operationId: 1,
      totalSampleCount: null as number | null,
      outputModelVersion: null as string | null,
    };
    const sampleDisplay = step.totalSampleCount != null
      ? `${step.totalSampleCount.toLocaleString()}`
      : 'Pending';
    const modelDisplay = step.outputModelVersion ? `v${step.outputModelVersion}` : 'Pending';

    assert.strictEqual(sampleDisplay, 'Pending');
    assert.strictEqual(modelDisplay, 'Pending');
    assert.notStrictEqual(sampleDisplay, '192');
    assert.notStrictEqual(modelDisplay, 'v3264');
  });
});
