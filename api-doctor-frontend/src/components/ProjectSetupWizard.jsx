import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { ArrowLeft, ArrowRight, CheckCircle2, FolderGit2, Loader2, Rocket, Search, Server, Sparkles } from 'lucide-react';

const STEPS = [
  { id: 1, title: 'Project' },
  { id: 2, title: 'GitHub' },
  { id: 3, title: 'Deployment' },
  { id: 4, title: 'Runtime' },
  { id: 5, title: 'Connection Test' },
];

const panelStyle = {
  backgroundColor: 'var(--surface-1)',
  border: '1px solid var(--border-color)',
  borderRadius: '12px',
  boxShadow: '0 20px 60px rgba(0,0,0,0.45)',
};

const inputStyle = {
  width: '100%',
  padding: '10px 12px',
  backgroundColor: 'var(--surface-2)',
  border: '1px solid var(--border-color)',
  borderRadius: '8px',
  color: 'var(--text-primary)',
  fontSize: '12px',
  outline: 'none',
  fontFamily: 'var(--font-mono)'
};

function defaultState() {
  return {
    name: '',
    description: '',
    githubToken: '',
    githubOwner: '',
    githubRepo: '',
    githubBranch: 'main',
    deploymentProvider: 'render',
    renderApiKey: '',
    renderOwnerId: '',
    renderServiceId: '',
    renderServiceName: '',
    runtime: {
      build_command: '',
      test_command: '',
      run_command: '',
      entrypoint: '',
    },
  };
}

export default function ProjectSetupWizard({ isOpen, fullScreen = false, onClose, onCreated }) {
  const [step, setStep] = useState(1);
  const [form, setForm] = useState(defaultState());
  const [repositories, setRepositories] = useState([]);
  const [repoSearch, setRepoSearch] = useState('');
  const [branches, setBranches] = useState([]);
  const [renderServices, setRenderServices] = useState([]);
  const [preview, setPreview] = useState(null);
  const [isLoadingRepos, setIsLoadingRepos] = useState(false);
  const [isLoadingBranches, setIsLoadingBranches] = useState(false);
  const [isLoadingServices, setIsLoadingServices] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    setStep(1);
    setForm(defaultState());
    setRepositories([]);
    setRepoSearch('');
    setBranches([]);
    setRenderServices([]);
    setPreview(null);
    setError('');
  }, [isOpen]);

  const filteredRepositories = useMemo(() => {
    const query = repoSearch.trim().toLowerCase();
    if (!query) return repositories;
    return repositories.filter(repo => `${repo.full_name || ''} ${repo.description || ''}`.toLowerCase().includes(query));
  }, [repositories, repoSearch]);

  if (!isOpen) return null;

  const nextStep = () => setStep(prev => Math.min(prev + 1, STEPS.length));
  const prevStep = () => setStep(prev => Math.max(prev - 1, 1));

  const buildPayload = () => ({
    name: form.name,
    description: form.description,
    github: {
      token: form.githubToken,
      owner: form.githubOwner,
      repo: form.githubRepo,
      branch: form.githubBranch,
    },
    deployment: {
      provider: form.deploymentProvider,
      api_key: form.deploymentProvider === 'render' ? form.renderApiKey : '',
      service_id: form.deploymentProvider === 'render' ? form.renderServiceId : '',
      service_name: form.deploymentProvider === 'render' ? form.renderServiceName : '',
      owner_id: form.deploymentProvider === 'render' ? form.renderOwnerId : '',
    },
    runtime_overrides: {
      build_command: form.runtime.build_command,
      test_command: form.runtime.test_command,
      run_command: form.runtime.run_command,
      entrypoint: form.runtime.entrypoint,
    },
    activate: true,
  });

  const loadRepositories = async () => {
    if (!form.githubToken.trim()) {
      setError('Enter a GitHub token to load accessible repositories.');
      return;
    }
    setError('');
    setIsLoadingRepos(true);
    try {
      const res = await api.listGithubRepositories(form.githubToken.trim());
      setRepositories(res.repositories || []);
      if ((res.repositories || []).length === 0) {
        setError('No accessible repositories were returned for this token.');
      }
    } catch (err) {
      setError(err.message || 'GitHub authentication failed.');
    } finally {
      setIsLoadingRepos(false);
    }
  };

  const loadBranches = async () => {
    if (!form.githubOwner || !form.githubRepo) {
      setError('Select or enter a repository first.');
      return;
    }
    setError('');
    setIsLoadingBranches(true);
    try {
      const res = await api.listGithubBranches({
        token: form.githubToken.trim(),
        owner: form.githubOwner,
        repo: form.githubRepo,
      });
      setBranches(res.branches || []);
      setForm(prev => ({
        ...prev,
        githubBranch: prev.githubBranch || res.repository?.default_branch || 'main',
      }));
    } catch (err) {
      setError(err.message || 'Unable to load branches.');
    } finally {
      setIsLoadingBranches(false);
    }
  };

  const loadRenderServices = async () => {
    if (!form.renderApiKey.trim()) {
      setError('Enter a Render API key to load services.');
      return;
    }
    setError('');
    setIsLoadingServices(true);
    try {
      const res = await api.listRenderServices(form.renderApiKey.trim());
      setRenderServices(res.services || []);
      if ((res.services || []).length === 0) {
        setError('No Render services were returned for this API key.');
      }
    } catch (err) {
      setError(err.message || 'Render authentication failed.');
    } finally {
      setIsLoadingServices(false);
    }
  };

  const runPreview = async () => {
    setError('');
    setIsPreviewing(true);
    try {
      const res = await api.previewProject(buildPayload());
      setPreview(res);
      setForm(prev => ({
        ...prev,
        runtime: {
          build_command: prev.runtime.build_command || res.settings?.build_command || '',
          test_command: prev.runtime.test_command || res.settings?.test_command || '',
          run_command: prev.runtime.run_command || res.settings?.run_command || '',
          entrypoint: prev.runtime.entrypoint || res.settings?.source_configuration?.entrypoint || '',
        }
      }));
      return res;
    } catch (err) {
      setError(err.message || 'Project inspection failed.');
      return null;
    } finally {
      setIsPreviewing(false);
    }
  };

  const createProject = async () => {
    setError('');
    setIsCreating(true);
    try {
      const res = await api.createProject(buildPayload());
      if (onCreated) onCreated(res.project, res);
    } catch (err) {
      setError(err.message || 'Project creation failed.');
    } finally {
      setIsCreating(false);
    }
  };

  const stepReady = () => {
    if (step === 1) return Boolean(form.name.trim());
    if (step === 2) return Boolean(form.githubOwner.trim() && form.githubRepo.trim() && form.githubBranch.trim());
    if (step === 3) return form.deploymentProvider !== 'render' || Boolean(form.renderApiKey.trim() && form.renderServiceId.trim());
    if (step === 4) return true;
    return Boolean(preview);
  };

  const handleNext = async () => {
    if (step === 2 && branches.length === 0) {
      await loadBranches();
    }
    if (step === 4 && !preview) {
      const result = await runPreview();
      if (!result) return;
    }
    if (!stepReady()) {
      setError('Complete the current step before continuing.');
      return;
    }
    setError('');
    nextStep();
  };

  const wrapperStyle = fullScreen
    ? {
        minHeight: '100vh',
        width: '100vw',
        background: 'radial-gradient(circle at top, rgba(124,140,248,0.18), transparent 45%), #0b1020',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '32px'
      }
    : {
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.72)',
        backdropFilter: 'blur(4px)',
        zIndex: 1200,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px'
      };

  return (
    <div style={wrapperStyle}>
      <div style={{ ...panelStyle, width: 'min(980px, 96vw)', minHeight: 'min(720px, 92vh)', display: 'flex', overflow: 'hidden' }}>
        <div style={{ width: '260px', borderRight: '1px solid var(--border-color)', backgroundColor: 'rgba(124,140,248,0.06)', padding: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '18px' }}>
            <div style={{ width: '38px', height: '38px', borderRadius: '10px', background: 'linear-gradient(135deg, var(--color-accent), #8b5cf6)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff' }}>
              <Sparkles size={18} />
            </div>
            <div>
              <div style={{ fontSize: '11px', letterSpacing: '0.08em', color: 'var(--text-muted)', fontWeight: 700 }}>FIRST-TIME SETUP</div>
              <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>Connect your project</div>
            </div>
          </div>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: '24px' }}>
            Connect your GitHub repository and production environment to start diagnosing real failures.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {STEPS.map(item => (
              <div key={item.id} style={{
                padding: '10px 12px',
                borderRadius: '8px',
                border: `1px solid ${step === item.id ? 'rgba(124,140,248,0.4)' : 'transparent'}`,
                backgroundColor: step === item.id ? 'rgba(124,140,248,0.12)' : 'transparent',
                color: step === item.id ? 'var(--text-primary)' : 'var(--text-muted)',
                fontSize: '12px',
                fontWeight: step === item.id ? 600 : 500,
              }}>
                {item.id}. {item.title}
              </div>
            ))}
          </div>
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '24px 28px 18px', borderBottom: '1px solid var(--border-color)' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', letterSpacing: '0.08em', fontWeight: 700, marginBottom: '8px' }}>
              STEP {step} OF {STEPS.length}
            </div>
            <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)' }}>{STEPS[step - 1].title}</div>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: '24px 28px', display: 'flex', flexDirection: 'column', gap: '18px' }}>
            {step === 1 && (
              <>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Project name</label>
                  <input value={form.name} onChange={e => setForm(prev => ({ ...prev, name: e.target.value }))} placeholder="Hack Store" style={inputStyle} />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Project description</label>
                  <textarea value={form.description} onChange={e => setForm(prev => ({ ...prev, description: e.target.value }))} rows={5} placeholder="Production app monitored by API Doctor" style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }} />
                </div>
              </>
            )}

            {step === 2 && (
              <>
                <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
                  <div style={{ flex: 1 }}>
                    <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>GitHub token</label>
                    <input type="password" value={form.githubToken} onChange={e => setForm(prev => ({ ...prev, githubToken: e.target.value }))} placeholder="ghp_..." style={inputStyle} />
                  </div>
                  <button type="button" onClick={loadRepositories} className="btn-outline" style={{ height: '38px' }}>
                    {isLoadingRepos ? <Loader2 size={14} className="spin" /> : <FolderGit2 size={14} />}
                    <span>Load Repositories</span>
                  </button>
                </div>

                {repositories.length > 0 && (
                  <div style={{ ...panelStyle, backgroundColor: 'var(--surface-2)', padding: '14px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                      <Search size={14} style={{ color: 'var(--text-muted)' }} />
                      <input value={repoSearch} onChange={e => setRepoSearch(e.target.value)} placeholder="Search repositories..." style={{ ...inputStyle, padding: '8px 10px' }} />
                    </div>
                    <div style={{ maxHeight: '180px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {filteredRepositories.map(repo => (
                        <button
                          key={repo.id || repo.full_name}
                          type="button"
                          onClick={() => {
                            setForm(prev => ({
                              ...prev,
                              githubOwner: repo.owner || '',
                              githubRepo: repo.name || '',
                              githubBranch: repo.default_branch || 'main',
                              name: prev.name || repo.name || '',
                              description: prev.description || repo.description || '',
                            }));
                            setBranches([]);
                          }}
                          style={{
                            textAlign: 'left',
                            padding: '10px 12px',
                            borderRadius: '8px',
                            border: `1px solid ${form.githubOwner === repo.owner && form.githubRepo === repo.name ? 'rgba(61,214,140,0.4)' : 'var(--border-color)'}`,
                            backgroundColor: form.githubOwner === repo.owner && form.githubRepo === repo.name ? 'rgba(61,214,140,0.08)' : 'var(--surface-1)',
                            color: 'var(--text-primary)',
                            cursor: 'pointer'
                          }}
                        >
                          <div style={{ fontSize: '12px', fontWeight: 600 }}>{repo.full_name}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{repo.description || 'No description'}</div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Repository owner</label>
                    <input value={form.githubOwner} onChange={e => setForm(prev => ({ ...prev, githubOwner: e.target.value }))} placeholder="dushu2006" style={inputStyle} />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Repository name</label>
                    <input value={form.githubRepo} onChange={e => setForm(prev => ({ ...prev, githubRepo: e.target.value }))} placeholder="HACK-STORE" style={inputStyle} />
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
                  <div style={{ flex: 1 }}>
                    <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Branch</label>
                    {branches.length > 0 ? (
                      <select value={form.githubBranch} onChange={e => setForm(prev => ({ ...prev, githubBranch: e.target.value }))} style={inputStyle}>
                        {branches.map(branch => <option key={branch} value={branch}>{branch}</option>)}
                      </select>
                    ) : (
                      <input value={form.githubBranch} onChange={e => setForm(prev => ({ ...prev, githubBranch: e.target.value }))} placeholder="main" style={inputStyle} />
                    )}
                  </div>
                  <button type="button" onClick={loadBranches} className="btn-outline" style={{ height: '38px' }}>
                    {isLoadingBranches ? <Loader2 size={14} className="spin" /> : <ArrowRight size={14} />}
                    <span>Verify Repository</span>
                  </button>
                </div>
              </>
            )}

            {step === 3 && (
              <>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Where is this project deployed?</label>
                  <select value={form.deploymentProvider} onChange={e => setForm(prev => ({ ...prev, deploymentProvider: e.target.value }))} style={inputStyle}>
                    <option value="render">Render</option>
                    <option value="manual">Manual Logs</option>
                  </select>
                </div>

                {form.deploymentProvider === 'render' ? (
                  <>
                    <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
                      <div style={{ flex: 1 }}>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Render API key</label>
                        <input type="password" value={form.renderApiKey} onChange={e => setForm(prev => ({ ...prev, renderApiKey: e.target.value }))} placeholder="rnd_..." style={inputStyle} />
                      </div>
                      <button type="button" onClick={loadRenderServices} className="btn-outline" style={{ height: '38px' }}>
                        {isLoadingServices ? <Loader2 size={14} className="spin" /> : <Server size={14} />}
                        <span>Load Services</span>
                      </button>
                    </div>
                    {renderServices.length > 0 && (
                      <div>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Render service</label>
                        <select
                          value={form.renderServiceId}
                          onChange={e => {
                            const selected = renderServices.find(item => item.id === e.target.value);
                            setForm(prev => ({
                              ...prev,
                              renderServiceId: e.target.value,
                              renderServiceName: selected?.name || '',
                              renderOwnerId: selected?.owner_id || '',
                            }));
                          }}
                          style={inputStyle}
                        >
                          <option value="">Select a service</option>
                          {renderServices.map(service => (
                            <option key={service.id} value={service.id}>{service.name || service.id}</option>
                          ))}
                        </select>
                      </div>
                    )}
                  </>
                ) : (
                  <div style={{ ...panelStyle, backgroundColor: 'var(--surface-2)', padding: '16px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}>Manual log source</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.6 }}>
                      The project will be created without an external deployment integration. You can paste production logs manually whenever you diagnose an incident.
                    </div>
                  </div>
                )}
              </>
            )}

            {step === 4 && (
              <>
                {!preview ? (
                  <div style={{ ...panelStyle, backgroundColor: 'var(--surface-2)', padding: '18px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '8px' }}>Inspect repository runtime</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: '14px' }}>
                      API Doctor will verify the repository, synchronize the workspace, detect the framework, and suggest test and run commands.
                    </div>
                    <button type="button" onClick={runPreview} className="btn-primary">
                      {isPreviewing ? <Loader2 size={14} className="spin" /> : <Rocket size={14} />}
                      <span>Inspect Project</span>
                    </button>
                  </div>
                ) : (
                  <>
                    <div style={{ ...panelStyle, backgroundColor: 'var(--surface-2)', padding: '16px' }}>
                      <div style={{ fontSize: '11px', letterSpacing: '0.08em', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '10px' }}>DISCOVERED RUNTIME</div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                        <InfoRow label="Language" value={preview.profile?.language || 'Unknown'} />
                        <InfoRow label="Framework" value={preview.profile?.framework || 'Unknown'} />
                        <InfoRow label="Package manager" value={preview.profile?.package_manager || 'Unknown'} />
                        <InfoRow label="Entrypoint" value={preview.profile?.entrypoint || '—'} />
                      </div>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '12px' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Run command</label>
                        <input value={form.runtime.run_command} onChange={e => setForm(prev => ({ ...prev, runtime: { ...prev.runtime, run_command: e.target.value } }))} style={inputStyle} />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Test command</label>
                        <input value={form.runtime.test_command} onChange={e => setForm(prev => ({ ...prev, runtime: { ...prev.runtime, test_command: e.target.value } }))} style={inputStyle} />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Build command</label>
                        <input value={form.runtime.build_command} onChange={e => setForm(prev => ({ ...prev, runtime: { ...prev.runtime, build_command: e.target.value } }))} placeholder="Optional" style={inputStyle} />
                      </div>
                    </div>
                  </>
                )}
              </>
            )}

            {step === 5 && (
              <>
                {!preview && (
                  <button type="button" onClick={runPreview} className="btn-primary" style={{ alignSelf: 'flex-start' }}>
                    {isPreviewing ? <Loader2 size={14} className="spin" /> : <CheckCircle2 size={14} />}
                    <span>Run Connection Test</span>
                  </button>
                )}
                {preview && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {(preview.checks || []).map(item => (
                      <div key={item.key} style={{ ...panelStyle, backgroundColor: 'var(--surface-2)', padding: '12px 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <CheckCircle2 size={15} style={{ color: item.ok ? 'var(--color-success)' : 'var(--color-failure)' }} />
                          <div>
                            <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>{item.label}</div>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{item.detail || 'Verified'}</div>
                          </div>
                        </div>
                        <div style={{ color: item.ok ? 'var(--color-success)' : 'var(--color-failure)', fontSize: '11px', fontWeight: 700 }}>
                          {item.ok ? 'OK' : 'FAILED'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {error && (
              <div style={{ color: 'var(--color-failure)', fontSize: '12px', backgroundColor: 'rgba(240,96,90,0.08)', border: '1px solid rgba(240,96,90,0.2)', borderRadius: '8px', padding: '10px 12px' }}>
                {error}
              </div>
            )}
          </div>

          <div style={{ padding: '18px 28px', borderTop: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              {!fullScreen && (
                <button type="button" onClick={onClose} className="btn-outline">Cancel</button>
              )}
            </div>
            <div style={{ display: 'flex', gap: '10px' }}>
              {step > 1 && (
                <button type="button" onClick={prevStep} className="btn-outline">
                  <ArrowLeft size={14} />
                  <span>Back</span>
                </button>
              )}
              {step < STEPS.length ? (
                <button type="button" onClick={handleNext} className="btn-primary">
                  <span>Continue</span>
                  <ArrowRight size={14} />
                </button>
              ) : (
                <button type="button" onClick={createProject} disabled={!preview || isCreating} className="btn-primary">
                  {isCreating ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
                  <span>Create Project</span>
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function InfoRow({ label, value }) {
  return (
    <div style={{ backgroundColor: 'var(--surface-1)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '10px 12px' }}>
      <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.06em', fontWeight: 700, marginBottom: '6px' }}>{label}</div>
      <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontWeight: 600 }}>{value}</div>
    </div>
  );
}
