import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { CheckCircle2, Loader2, RefreshCw, Save, Settings, ShieldCheck } from 'lucide-react';

const inputStyle = {
  width: '100%',
  padding: '10px 12px',
  backgroundColor: 'var(--surface-2)',
  border: '1px solid var(--border-color)',
  borderRadius: '8px',
  color: 'var(--text-primary)',
  fontSize: '12px',
  outline: 'none',
};

export default function ProjectSettingsModal({ isOpen, currentProject, onClose, onSaved }) {
  const [form, setForm] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isVerifying, setIsVerifying] = useState({ github: false, deployment: false });
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const deploymentProvider = useMemo(
    () => (currentProject?.integrations || []).find(item => item.enabled && ['render', 'manual'].includes(item.provider))?.provider || 'manual',
    [currentProject]
  );

  useEffect(() => {
    if (!isOpen || !currentProject) return;
    setForm({
      project: {
        name: currentProject.name || '',
        description: currentProject.description || '',
        default_branch: currentProject.default_branch || currentProject.github_branch || 'main',
      },
      settings: {
        project_id: currentProject.id,
        sandbox_mode: currentProject.settings?.sandbox_mode || 'local',
        build_command: currentProject.settings?.build_command || '',
        test_command: currentProject.settings?.test_command || '',
        run_command: currentProject.settings?.run_command || '',
        source_configuration: currentProject.settings?.source_configuration || {},
        diagnosis_settings: {
          max_context_files: currentProject.settings?.diagnosis_settings?.max_context_files || 4,
          retrieval_top_k: currentProject.settings?.diagnosis_settings?.retrieval_top_k || 5,
        },
        repair_settings: {
          max_repair_attempts: currentProject.settings?.repair_settings?.max_repair_attempts || 2,
          auto_create_pr: Boolean(currentProject.settings?.repair_settings?.auto_create_pr),
          auto_merge: Boolean(currentProject.settings?.repair_settings?.auto_merge),
        },
        runtime_summary: currentProject.settings?.runtime_summary || currentProject.profile || {},
      }
    });
    setMessage('');
    setError('');
  }, [isOpen, currentProject]);

  if (!isOpen || !currentProject || !form) return null;

  const saveSettings = async () => {
    setError('');
    setMessage('');
    setIsSaving(true);
    try {
      await api.updateProject(currentProject.id, form.project);
      await api.updateProjectSettings(currentProject.id, form.settings);
      setMessage('Project settings saved.');
      await onSaved?.();
      onClose?.();
    } catch (err) {
      setError(err.message || 'Unable to save project settings.');
    } finally {
      setIsSaving(false);
    }
  };

  const verifyGithub = async () => {
    setError('');
    setMessage('');
    setIsVerifying(prev => ({ ...prev, github: true }));
    try {
      const res = await api.verifyGithubIntegration(currentProject.id);
      setMessage(res.message || 'GitHub repository verified successfully.');
    } catch (err) {
      setError(err.message || 'GitHub verification failed.');
    } finally {
      setIsVerifying(prev => ({ ...prev, github: false }));
    }
  };

  const verifyDeployment = async () => {
    if (deploymentProvider !== 'render') {
      setMessage('Manual log provider does not require external verification.');
      return;
    }
    setError('');
    setMessage('');
    setIsVerifying(prev => ({ ...prev, deployment: true }));
    try {
      const res = await api.verifyRenderIntegration(currentProject.id);
      setMessage(res.message || 'Render integration verified successfully.');
    } catch (err) {
      setError(err.message || 'Render verification failed.');
    } finally {
      setIsVerifying(prev => ({ ...prev, deployment: false }));
    }
  };

  const integrationBadge = (provider) => {
    const integration = (currentProject.integrations || []).find(item => item.provider === provider);
    return integration?.status || 'disconnected';
  };

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1200, backgroundColor: 'rgba(0,0,0,0.72)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
      <div style={{ width: 'min(860px, 96vw)', maxHeight: '92vh', overflow: 'hidden', backgroundColor: 'var(--surface-1)', border: '1px solid var(--border-color)', borderRadius: '14px', boxShadow: '0 20px 60px rgba(0,0,0,0.45)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '22px 24px', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ width: '40px', height: '40px', borderRadius: '12px', backgroundColor: 'rgba(124,140,248,0.14)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-accent)' }}>
            <Settings size={18} />
          </div>
          <div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', letterSpacing: '0.08em', fontWeight: 700 }}>PROJECT SETTINGS</div>
            <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)' }}>{currentProject.name}</div>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '22px 24px', display: 'grid', gap: '18px' }}>
          <Section title="General">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '12px' }}>
              <Field label="Project name"><input value={form.project.name} onChange={e => setForm(prev => ({ ...prev, project: { ...prev.project, name: e.target.value } }))} style={inputStyle} /></Field>
              <Field label="Description"><textarea rows={3} value={form.project.description} onChange={e => setForm(prev => ({ ...prev, project: { ...prev.project, description: e.target.value } }))} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
            </div>
          </Section>

          <Section title="Source">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <Field label="Repository"><input value={`${currentProject.github_owner}/${currentProject.github_repo}`} style={inputStyle} readOnly /></Field>
              <Field label="Branch"><input value={form.project.default_branch} onChange={e => setForm(prev => ({ ...prev, project: { ...prev.project, default_branch: e.target.value } }))} style={inputStyle} /></Field>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
              <StatusPill label="GitHub" value={integrationBadge('github')} />
              <button type="button" onClick={verifyGithub} className="btn-outline">
                {isVerifying.github ? <Loader2 size={14} className="spin" /> : <ShieldCheck size={14} />}
                <span>Verify Connection</span>
              </button>
            </div>
          </Section>

          <Section title="Deployment">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <Field label="Provider"><input value={deploymentProvider.toUpperCase()} style={inputStyle} readOnly /></Field>
              <Field label="Service"><input value={currentProject.render_service_id || 'Manual logs'} style={inputStyle} readOnly /></Field>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
              <StatusPill label="Deployment" value={integrationBadge(deploymentProvider)} />
              <button type="button" onClick={verifyDeployment} className="btn-outline">
                {isVerifying.deployment ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
                <span>Verify Deployment</span>
              </button>
            </div>
          </Section>

          <Section title="Runtime">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '12px' }}>
              <Field label="Run command"><input value={form.settings.run_command} onChange={e => setForm(prev => ({ ...prev, settings: { ...prev.settings, run_command: e.target.value } }))} style={inputStyle} /></Field>
              <Field label="Test command"><input value={form.settings.test_command} onChange={e => setForm(prev => ({ ...prev, settings: { ...prev.settings, test_command: e.target.value } }))} style={inputStyle} /></Field>
              <Field label="Build command"><input value={form.settings.build_command} onChange={e => setForm(prev => ({ ...prev, settings: { ...prev.settings, build_command: e.target.value } }))} style={inputStyle} /></Field>
            </div>
          </Section>

          <Section title="Diagnosis">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <Field label="Max context files"><input type="number" value={form.settings.diagnosis_settings.max_context_files} onChange={e => setForm(prev => ({ ...prev, settings: { ...prev.settings, diagnosis_settings: { ...prev.settings.diagnosis_settings, max_context_files: Number(e.target.value) || 0 } } }))} style={inputStyle} /></Field>
              <Field label="Retrieval top K"><input type="number" value={form.settings.diagnosis_settings.retrieval_top_k} onChange={e => setForm(prev => ({ ...prev, settings: { ...prev.settings, diagnosis_settings: { ...prev.settings.diagnosis_settings, retrieval_top_k: Number(e.target.value) || 0 } } }))} style={inputStyle} /></Field>
            </div>
          </Section>

          <Section title="Repair">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <Field label="Sandbox mode"><input value={form.settings.sandbox_mode} onChange={e => setForm(prev => ({ ...prev, settings: { ...prev.settings, sandbox_mode: e.target.value } }))} style={inputStyle} /></Field>
              <Field label="Max repair attempts"><input type="number" value={form.settings.repair_settings.max_repair_attempts} onChange={e => setForm(prev => ({ ...prev, settings: { ...prev.settings, repair_settings: { ...prev.settings.repair_settings, max_repair_attempts: Number(e.target.value) || 0 } } }))} style={inputStyle} /></Field>
            </div>
            <div style={{ display: 'flex', gap: '20px', fontSize: '12px', color: 'var(--text-primary)' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><input type="checkbox" checked={Boolean(form.settings.repair_settings.auto_create_pr)} onChange={e => setForm(prev => ({ ...prev, settings: { ...prev.settings, repair_settings: { ...prev.settings.repair_settings, auto_create_pr: e.target.checked } } }))} /> Auto create PR</label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><input type="checkbox" checked={Boolean(form.settings.repair_settings.auto_merge)} onChange={e => setForm(prev => ({ ...prev, settings: { ...prev.settings, repair_settings: { ...prev.settings.repair_settings, auto_merge: e.target.checked } } }))} /> Auto merge</label>
            </div>
          </Section>

          {(message || error) && (
            <div style={{ color: error ? 'var(--color-failure)' : 'var(--color-success)', fontSize: '12px', padding: '10px 12px', borderRadius: '8px', backgroundColor: error ? 'rgba(240,96,90,0.08)' : 'rgba(61,214,140,0.08)', border: `1px solid ${error ? 'rgba(240,96,90,0.18)' : 'rgba(61,214,140,0.18)'}` }}>
              {error || message}
            </div>
          )}
        </div>

        <div style={{ padding: '18px 24px', borderTop: '1px solid var(--border-color)', display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <button type="button" onClick={onClose} className="btn-outline">Close</button>
          <button type="button" onClick={saveSettings} disabled={isSaving} className="btn-primary">
            {isSaving ? <Loader2 size={14} className="spin" /> : <Save size={14} />}
            <span>Save Settings</span>
          </button>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px' }}>
      <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.08em', fontWeight: 700, marginBottom: '12px' }}>{title.toUpperCase()}</div>
      {children}
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>{label}</label>
      {children}
    </div>
  );
}

function StatusPill({ label, value }) {
  const ok = String(value).toLowerCase().includes('connect');
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--text-primary)' }}>
      <CheckCircle2 size={14} style={{ color: ok ? 'var(--color-success)' : 'var(--color-warning)' }} />
      <span>{label}: {value}</span>
    </div>
  );
}
