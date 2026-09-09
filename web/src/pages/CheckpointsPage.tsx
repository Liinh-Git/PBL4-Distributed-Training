import { useState, useEffect, useCallback } from 'react';
import { checkpointsApi, type CheckpointDetail } from '../api/checkpoints';
import { jobsApi } from '../api/jobs';
import { createIdempotencyKey } from '../api/client';
import type { CheckpointListItem } from '../domain/types';
import { useNavigate, useParams } from 'react-router-dom';

export default function CheckpointsPage() {
  const navigate = useNavigate();
  const { checkpointId } = useParams<{ checkpointId?: string }>();
  const [checkpoints, setCheckpoints] = useState<CheckpointListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [jobIdFilter, setJobIdFilter] = useState('');
  const [stateFilter, setStateFilter] = useState('');

  // Selected detail
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<CheckpointDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [resumingId, setResumingId] = useState<string | null>(null);

  const fetchCheckpoints = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await checkpointsApi.list({
        job_id: jobIdFilter || undefined,
        state: stateFilter || undefined,
        limit: 100,
      });
      setCheckpoints(res.data || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [jobIdFilter, stateFilter]);

  useEffect(() => {
    fetchCheckpoints();
  }, [fetchCheckpoints]);

  const handleInspect = async (checkpointId: string) => {
    setDetailLoading(true);
    try {
      const detail = await checkpointsApi.get(checkpointId);
      setSelectedCheckpoint(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    if (checkpointId) void handleInspect(checkpointId);
  }, [checkpointId]);

  const handleResume = async (jobId: string, targetCheckpointId: string) => {
    if (!window.confirm(`Resume job ${jobId} from checkpoint ${targetCheckpointId}?`)) return;
    setResumingId(targetCheckpointId);
    setError(null);
    try {
      const key = createIdempotencyKey('job_resume');
      const res = await jobsApi.resume(jobId, targetCheckpointId, key);
      navigate(res.attempt_id ? `/attempts/${res.attempt_id}` : '/current-job');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setResumingId(null);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>Checkpoints</h1>
          <p className="text-secondary" style={{ fontSize: 13, marginTop: 4 }}>
            Durably persisted model checkpoints and resume recovery cursors.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={fetchCheckpoints} disabled={loading}>
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="card" style={{ background: 'var(--error-dim)', borderColor: 'var(--error)', padding: 12 }}>
          <span style={{ color: 'var(--error)', fontWeight: 500 }}>{error}</span>
        </div>
      )}

      {/* Filter Bar */}
      <div className="card" style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Job ID:</span>
          <input
            className="form-input"
            style={{ width: 180 }}
            placeholder="Filter by Job ID"
            value={jobIdFilter}
            onChange={(e) => setJobIdFilter(e.target.value)}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>State:</span>
          <select
            className="form-select"
            style={{ width: 150 }}
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value)}
          >
            <option value="">All States</option>
            <option value="COMPLETE">COMPLETE</option>
            <option value="WRITING">WRITING</option>
            <option value="FAILED">FAILED</option>
          </select>
        </div>
        {(jobIdFilter || stateFilter) && (
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => {
              setJobIdFilter('');
              setStateFilter('');
            }}
          >
            Reset Filters
          </button>
        )}
      </div>

      {/* Checkpoints Table */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Checkpoints ({checkpoints.length})</span>
        </div>
        {checkpoints.length === 0 ? (
          <div className="text-muted" style={{ padding: 24, textAlign: 'center' }}>
            No checkpoints found matching the filter criteria.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="table" style={{ width: '100%', textAlign: 'left', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)', fontSize: 12 }}>
                  <th style={{ padding: '8px 12px' }}>Checkpoint ID</th>
                  <th style={{ padding: '8px 12px' }}>State</th>
                  <th style={{ padding: '8px 12px' }}>Job ID</th>
                  <th style={{ padding: '8px 12px' }}>Attempt ID</th>
                  <th style={{ padding: '8px 12px' }}>Model Version</th>
                  <th style={{ padding: '8px 12px' }}>Step</th>
                  <th style={{ padding: '8px 12px' }}>Created</th>
                  <th style={{ padding: '8px 12px' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {checkpoints.map((c) => (
                  <tr key={c.checkpoint_id} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      {c.checkpoint_id}
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <span className={`status-badge status-${c.state}`}>
                        <span className="status-dot" />
                        {c.state}
                      </span>
                    </td>
                    <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      {c.job_id || '—'}
                    </td>
                    <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      {c.created_by_attempt_id}
                    </td>
                    <td style={{ padding: '10px 12px' }}>v{c.model_version}</td>
                    <td style={{ padding: '10px 12px' }}>{c.source_step_id ?? '—'}</td>
                    <td style={{ padding: '10px 12px', fontSize: 12, color: 'var(--text-muted)' }}>
                      {new Date(c.created_at).toLocaleTimeString()}
                    </td>
                    <td style={{ padding: '10px 12px', display: 'flex', gap: 6 }}>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => navigate(`/checkpoints/${c.checkpoint_id}`)}
                        disabled={detailLoading}
                      >
                        Inspect
                      </button>
                      {c.state === 'COMPLETE' && c.job_id && (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => handleResume(c.job_id!, c.checkpoint_id)}
                          disabled={resumingId === c.checkpoint_id}
                        >
                          {resumingId === c.checkpoint_id ? 'Resuming...' : 'Resume'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Detail Modal */}
      {selectedCheckpoint && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 200,
          }}
        >
          <div className="card" style={{ width: 560, padding: 24, maxHeight: '85vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h2 style={{ fontSize: 16, fontWeight: 700 }}>Checkpoint Detail</h2>
              <button className="btn btn-ghost btn-sm" onClick={() => navigate('/checkpoints')}>
                ✕
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13 }}>
              <div>
                <span className="text-muted">Checkpoint ID: </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                  {selectedCheckpoint.checkpoint_id}
                </span>
              </div>
              <div>
                <span className="text-muted">State: </span>
                <span className={`status-badge status-${selectedCheckpoint.state}`}>
                  <span className="status-dot" />
                  {selectedCheckpoint.state}
                </span>
              </div>
              <div>
                <span className="text-muted">Created By Attempt: </span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{selectedCheckpoint.created_by_attempt_id}</span>
              </div>
              <div>
                <span className="text-muted">Model Version: </span>
                <span>v{selectedCheckpoint.model_version}</span>
              </div>
              <div>
                <span className="text-muted">Contract Hash: </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                  {selectedCheckpoint.contract_hash || '—'}
                </span>
              </div>
              <div>
                <span className="text-muted">Dataset Build ID: </span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{selectedCheckpoint.dataset_build_id || '—'}</span>
              </div>

              {selectedCheckpoint.recovery_cursor && (
                <div className="card" style={{ background: 'var(--bg-elevated)', padding: 12, marginTop: 6 }}>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>Recovery Cursor:</div>
                  <div>Epoch: {selectedCheckpoint.recovery_cursor.epoch}</div>
                  <div>Next Batch Ordinal: {selectedCheckpoint.recovery_cursor.next_batch_ordinal}</div>
                </div>
              )}

              {selectedCheckpoint.integrity && (
                <div className="card" style={{ background: 'var(--bg-elevated)', padding: 12, marginTop: 6 }}>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>Integrity & Artifact:</div>
                  <div style={{ wordBreak: 'break-all', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                    SHA-256: {selectedCheckpoint.integrity.model_sha256}
                  </div>
                  {selectedCheckpoint.integrity.artifact_size_bytes != null && (
                    <div style={{ marginTop: 4 }}>
                      Size: {(selectedCheckpoint.integrity.artifact_size_bytes / (1024 * 1024)).toFixed(2)} MB
                    </div>
                  )}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20 }}>
              <button className="btn btn-secondary" onClick={() => setSelectedCheckpoint(null)}>
                Close
              </button>
              {selectedCheckpoint.state === 'COMPLETE' && selectedCheckpoint.job_id && (
                <button
                  className="btn btn-primary"
                  onClick={() => handleResume(selectedCheckpoint.job_id!, selectedCheckpoint.checkpoint_id)}
                  disabled={resumingId === selectedCheckpoint.checkpoint_id}
                >
                  {resumingId === selectedCheckpoint.checkpoint_id ? 'Resuming...' : 'Resume from Checkpoint'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
