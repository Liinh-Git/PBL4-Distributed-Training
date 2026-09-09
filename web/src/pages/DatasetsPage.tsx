import { useState, useEffect, useCallback } from 'react';
import { datasetsApi } from '../api/datasets';
import { createIdempotencyKey } from '../api/client';
import { useNavigate, useParams } from 'react-router-dom';
import type { DatasetItem, DatasetBuildListItem } from '../domain/types';

export default function DatasetsPage() {
  const navigate = useNavigate();
  const { datasetBuildId } = useParams<{ datasetBuildId?: string }>();
  const [datasets, setDatasets] = useState<DatasetItem[]>([]);
  const [builds, setBuilds] = useState<DatasetBuildListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>('');

  // Modals
  const [showCreateDataset, setShowCreateDataset] = useState(false);
  const [newDatasetName, setNewDatasetName] = useState('');

  const [showCreateBuild, setShowCreateBuild] = useState(false);
  const [buildProfile] = useState('CNN_IMAGE_CLASSIFICATION_V1');
  const [buildBatchSize, setBuildBatchSize] = useState(64);
  const [buildSeed, setBuildSeed] = useState(42);

  const [actionLoading, setActionLoading] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [dsRes, bldRes] = await Promise.all([
        datasetsApi.list({ limit: 100 }),
        datasetBuildId
          ? datasetsApi.getBuild(datasetBuildId).then((build) => ({ data: [build] }))
          : datasetsApi.builds(selectedDatasetId ? { dataset_id: selectedDatasetId, limit: 100 } : { limit: 100 }),
      ]);
      setDatasets(dsRes.data || []);
      setBuilds(bldRes.data || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [datasetBuildId, selectedDatasetId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleCreateDataset = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    setActionMessage(null);
    try {
      const key = createIdempotencyKey('ds_create');
      await datasetsApi.create(
        {
          name: newDatasetName,
          task_type: 'image_classification',
          source_type: 'builtin',
          source_reference: 'cifar10',
        },
        key,
      );
      setShowCreateDataset(false);
      setNewDatasetName('');
      await fetchData();
      setActionMessage('Dataset created successfully.');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(false);
    }
  };

  const handleCreateBuild = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedDatasetId && datasets.length === 0) return;
    const targetDatasetId = selectedDatasetId || datasets[0]?.dataset_id;
    setActionLoading(true);
    setActionMessage(null);
    try {
      const key = createIdempotencyKey('bld_create');
      await datasetsApi.createBuild(
        {
          dataset_id: targetDatasetId,
          profile: buildProfile,
          batch_size: buildBatchSize,
          partition_seed: buildSeed,
        },
        key,
      );
      setShowCreateBuild(false);
      await fetchData();
      setActionMessage('Dataset build requested (ACCEPTED).');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeprecate = async (buildId: string) => {
    if (!window.confirm(`Deprecate build ${buildId}?`)) return;
    setActionLoading(true);
    try {
      const key = createIdempotencyKey('bld_deprecate');
      await datasetsApi.deprecateBuild(buildId, key, 'User deprecated via UI');
      await fetchData();
      setActionMessage(`Build ${buildId} deprecated.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async (buildId: string) => {
    if (!window.confirm(`Purge/delete build ${buildId}?`)) return;
    setActionLoading(true);
    try {
      const key = createIdempotencyKey('bld_delete');
      await datasetsApi.deleteBuild(buildId, key, 'User purged via UI');
      await fetchData();
      setActionMessage(`Build ${buildId} deleted.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Page Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>Datasets & Artifact Builds</h1>
          <p className="text-secondary" style={{ fontSize: 13, marginTop: 4 }}>
            Manage source dataset catalogs and canonical materialized partition builds.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn btn-secondary" onClick={() => setShowCreateDataset(true)}>
            + New Dataset
          </button>
          <button
            className="btn btn-primary"
            onClick={() => setShowCreateBuild(true)}
            disabled={datasets.length === 0}
          >
            + Create Build
          </button>
        </div>
      </div>

      {actionMessage && (
        <div className="card" style={{ background: 'var(--success-dim)', borderColor: 'var(--success)', padding: 12 }}>
          <span style={{ color: 'var(--success)', fontWeight: 500 }}>{actionMessage}</span>
        </div>
      )}

      {error && (
        <div className="card" style={{ background: 'var(--error-dim)', borderColor: 'var(--error)', padding: 12 }}>
          <span style={{ color: 'var(--error)', fontWeight: 500 }}>{error}</span>
        </div>
      )}

      {/* Dataset Sources Section */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Dataset Catalogs ({datasets.length})</span>
          <button className="btn btn-ghost btn-sm" onClick={fetchData} disabled={loading}>
            Refresh
          </button>
        </div>
        {datasets.length === 0 ? (
          <div className="text-muted" style={{ padding: 20, textAlign: 'center' }}>
            No datasets registered yet. Click "+ New Dataset" to create one.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="table" style={{ width: '100%', textAlign: 'left', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)', fontSize: 12 }}>
                  <th style={{ padding: '8px 12px' }}>Name</th>
                  <th style={{ padding: '8px 12px' }}>Dataset ID</th>
                  <th style={{ padding: '8px 12px' }}>Task Type</th>
                  <th style={{ padding: '8px 12px' }}>Source Type</th>
                  <th style={{ padding: '8px 12px' }}>Reference</th>
                  <th style={{ padding: '8px 12px' }}>Created</th>
                  <th style={{ padding: '8px 12px' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((ds) => {
                  const isSelected = selectedDatasetId === ds.dataset_id;
                  return (
                    <tr
                      key={ds.dataset_id}
                      style={{
                        borderBottom: '1px solid var(--border)',
                        background: isSelected ? 'var(--accent-glow)' : undefined,
                      }}
                    >
                      <td style={{ padding: '10px 12px', fontWeight: 600 }}>{ds.name}</td>
                      <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                        {ds.dataset_id}
                      </td>
                      <td style={{ padding: '10px 12px' }}>
                        <span className="badge">{ds.task_type}</span>
                      </td>
                      <td style={{ padding: '10px 12px' }}>{ds.source_type}</td>
                      <td style={{ padding: '10px 12px', color: 'var(--text-secondary)' }}>{ds.source_reference}</td>
                      <td style={{ padding: '10px 12px', fontSize: 12, color: 'var(--text-muted)' }}>
                        {new Date(ds.created_at).toLocaleDateString()}
                      </td>
                      <td style={{ padding: '10px 12px' }}>
                        <button
                          className={`btn btn-sm ${isSelected ? 'btn-primary' : 'btn-secondary'}`}
                          onClick={() => setSelectedDatasetId(isSelected ? '' : ds.dataset_id)}
                        >
                          {isSelected ? 'Viewing Builds' : 'Filter Builds'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Dataset Builds Section */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">
            Materialized Builds {selectedDatasetId ? `for ${selectedDatasetId}` : `(${builds.length})`}
          </span>
          {selectedDatasetId && (
            <button className="btn btn-ghost btn-sm" onClick={() => setSelectedDatasetId('')}>
              Clear Filter
            </button>
          )}
        </div>
        {builds.length === 0 ? (
          <div className="text-muted" style={{ padding: 20, textAlign: 'center' }}>
            No builds found. Click "+ Create Build" to initiate build materialization.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="table" style={{ width: '100%', textAlign: 'left', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)', fontSize: 12 }}>
                  <th style={{ padding: '8px 12px' }}>Build ID</th>
                  <th style={{ padding: '8px 12px' }}>State</th>
                  <th style={{ padding: '8px 12px' }}>Profile</th>
                  <th style={{ padding: '8px 12px' }}>Batch Size</th>
                  <th style={{ padding: '8px 12px' }}>Shards</th>
                  <th style={{ padding: '8px 12px' }}>Samples</th>
                  <th style={{ padding: '8px 12px' }}>Created</th>
                  <th style={{ padding: '8px 12px' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {builds.map((b) => (
                  <tr key={b.dataset_build_id} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => navigate(`/dataset-builds/${b.dataset_build_id}`)}
                      >
                        {b.dataset_build_id}
                      </button>
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <span className={`status-badge status-${b.state}`}>
                        <span className="status-dot" />
                        {b.state}
                      </span>
                    </td>
                    <td style={{ padding: '10px 12px' }}>{b.profile}</td>
                    <td style={{ padding: '10px 12px' }}>{b.batch_size}</td>
                    <td style={{ padding: '10px 12px' }}>{b.shard_count}</td>
                    <td style={{ padding: '10px 12px' }}>{b.sample_count ?? '—'}</td>
                    <td style={{ padding: '10px 12px', fontSize: 12, color: 'var(--text-muted)' }}>
                      {new Date(b.created_at).toLocaleTimeString()}
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <div style={{ display: 'flex', gap: 6 }}>
                        {b.state === 'READY' && (
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleDeprecate(b.dataset_build_id)}
                            disabled={actionLoading}
                          >
                            Deprecate
                          </button>
                        )}
                        {(b.state === 'DEPRECATED' || b.state === 'FAILED') && (
                          <button
                            className="btn btn-danger btn-sm"
                            onClick={() => handleDelete(b.dataset_build_id)}
                            disabled={actionLoading}
                          >
                            Purge
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal: Create Dataset */}
      {showCreateDataset && (
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
          <div className="card" style={{ width: 440, padding: 24 }}>
            <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>Register New Dataset</h2>
            <form onSubmit={handleCreateDataset} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div className="form-group">
                <label className="form-label">Dataset Name</label>
                <input
                  className="form-input"
                  required
                  value={newDatasetName}
                  onChange={(e) => setNewDatasetName(e.target.value)}
                  placeholder="e.g. CIFAR-10 Benchmark"
                />
              </div>
              <div className="form-group">
                <label className="form-label">Task Type</label>
                <input className="form-input" value="image_classification" readOnly />
              </div>
              <div className="form-group">
                <label className="form-label">Source Type</label>
                <input className="form-input" value="builtin" readOnly />
              </div>
              <div className="form-group">
                <label className="form-label">Source Reference</label>
                <input className="form-input" value="cifar10" readOnly />
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 10 }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowCreateDataset(false)}
                  disabled={actionLoading}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={actionLoading || !newDatasetName}>
                  {actionLoading ? 'Creating...' : 'Register Dataset'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Create Build */}
      {showCreateBuild && (
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
          <div className="card" style={{ width: 440, padding: 24 }}>
            <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>Request Dataset Build</h2>
            <form onSubmit={handleCreateBuild} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div className="form-group">
                <label className="form-label">Target Dataset</label>
                <select
                  className="form-select"
                  value={selectedDatasetId || datasets[0]?.dataset_id || ''}
                  onChange={(e) => setSelectedDatasetId(e.target.value)}
                >
                  {datasets.map((d) => (
                    <option key={d.dataset_id} value={d.dataset_id}>
                      {d.name} ({d.dataset_id})
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Profile</label>
                <input
                  className="form-input"
                  value={buildProfile}
                  readOnly
                  style={{ opacity: 0.8, cursor: 'not-allowed' }}
                />
                <span className="text-muted" style={{ fontSize: 11 }}>
                  Canonical profile for V1 image classification.
                </span>
              </div>
              <div className="form-group">
                <label className="form-label">Batch Size</label>
                <input
                  type="number"
                  className="form-input"
                  min={1}
                  max={1024}
                  value={buildBatchSize}
                  onChange={(e) => setBuildBatchSize(Number(e.target.value))}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Partition Seed</label>
                <input
                  type="number"
                  className="form-input"
                  value={buildSeed}
                  onChange={(e) => setBuildSeed(Number(e.target.value))}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 10 }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowCreateBuild(false)}
                  disabled={actionLoading}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={actionLoading}>
                  {actionLoading ? 'Dispatching...' : 'Dispatch Build Command'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
