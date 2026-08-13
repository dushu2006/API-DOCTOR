import React, { useMemo, useState } from 'react';
import { Copy, FolderGit2, Pencil, PlusCircle, Server, Trash2 } from 'lucide-react';

export default function ProjectSelectorModal({
  isOpen,
  projects = [],
  currentProjectId,
  onSelectProject,
  onRenameProject,
  onDuplicateProject,
  onDeleteProject,
  onNewProject,
}) {
  const [editingId, setEditingId] = useState(null);
  const [draftName, setDraftName] = useState('');
  const [busyId, setBusyId] = useState(null);

  const sortedProjects = useMemo(() => projects, [projects]);

  if (!isOpen) return null;

  const startRename = (project) => {
    setEditingId(project.id);
    setDraftName(project.name || '');
  };

  const saveRename = async (project) => {
    if (!draftName.trim()) return;
    setBusyId(project.id);
    try {
      await onRenameProject?.(project, draftName.trim());
      setEditingId(null);
      setDraftName('');
    } finally {
      setBusyId(null);
    }
  };

  const duplicateProject = async (project) => {
    setBusyId(project.id);
    try {
      await onDuplicateProject?.(project, `${project.name} Copy`);
    } finally {
      setBusyId(null);
    }
  };

  const deleteProject = async (project) => {
    const confirmed = window.confirm(`Delete project "${project.name}"? This removes its runs, settings, and integrations.`);
    if (!confirmed) return;
    setBusyId(project.id);
    try {
      await onDeleteProject?.(project);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      zIndex: 1200,
      backgroundColor: 'rgba(0,0,0,0.72)',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '24px'
    }}>
      <div style={{
        width: 'min(860px, 94vw)',
        backgroundColor: 'var(--surface-1)',
        border: '1px solid var(--border-color)',
        borderRadius: '14px',
        boxShadow: '0 20px 60px rgba(0,0,0,0.45)',
        overflow: 'hidden'
      }}>
        <div style={{ padding: '24px 26px', borderBottom: '1px solid var(--border-color)' }}>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.08em', marginBottom: '8px' }}>PROJECTS</div>
          <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '8px' }}>Manage Projects</div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.6 }}>
            Open, rename, duplicate, or delete your projects. Each project keeps only its repository, integrations, and settings.
          </div>
        </div>

        <div style={{ padding: '20px 26px', display: 'grid', gap: '12px', maxHeight: '70vh', overflowY: 'auto' }}>
          {sortedProjects.map(project => {
            const provider = (project.integrations || []).find(item => item.enabled && ['render', 'manual'].includes(item.provider))?.provider || 'manual';
            const isEditing = editingId === project.id;
            const isBusy = busyId === project.id;
            return (
              <div
                key={project.id}
                style={{
                  padding: '16px 18px',
                  borderRadius: '10px',
                  border: currentProjectId === project.id ? '1px solid rgba(124,140,248,0.4)' : '1px solid var(--border-color)',
                  backgroundColor: currentProjectId === project.id ? 'rgba(124,140,248,0.08)' : 'var(--surface-2)',
                  color: 'var(--text-primary)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '14px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', flex: 1 }}>
                  <div style={{ width: '40px', height: '40px', borderRadius: '10px', backgroundColor: 'rgba(124,140,248,0.14)', color: 'var(--color-accent)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <FolderGit2 size={18} />
                  </div>
                  <div style={{ flex: 1 }}>
                    {isEditing ? (
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '6px' }}>
                        <input value={draftName} onChange={e => setDraftName(e.target.value)} style={{ width: '100%', padding: '8px 10px', backgroundColor: 'var(--surface-1)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--text-primary)', outline: 'none' }} />
                        <button type="button" onClick={() => saveRename(project)} className="btn-primary" disabled={isBusy}>Save</button>
                        <button type="button" onClick={() => setEditingId(null)} className="btn-outline">Cancel</button>
                      </div>
                    ) : (
                      <div style={{ fontSize: '15px', fontWeight: 700, marginBottom: '4px' }}>{project.name}</div>
                    )}
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>
                      {project.github_owner}/{project.github_repo}
                    </div>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '11px', color: 'var(--text-muted)', flexWrap: 'wrap' }}>
                      <span style={{ padding: '2px 6px', borderRadius: '999px', backgroundColor: 'rgba(124,140,248,0.12)', color: 'var(--color-accent)' }}>
                        {project.default_branch || project.github_branch || 'main'}
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Server size={12} />
                        {String(provider).toUpperCase()}
                      </span>
                      {currentProjectId === project.id && (
                        <span style={{ padding: '2px 6px', borderRadius: '999px', backgroundColor: 'rgba(61,214,140,0.12)', color: 'var(--color-success)' }}>ACTIVE</span>
                      )}
                    </div>
                  </div>
                </div>
                <div style={{ textAlign: 'right', minWidth: '290px' }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>Last updated: {project.updated_at ? new Date(project.updated_at).toLocaleString() : '—'}</div>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', flexWrap: 'wrap' }}>
                    <button type="button" onClick={() => onSelectProject?.(project)} className="btn-primary" disabled={isBusy}>Open</button>
                    {!isEditing && (
                      <button type="button" onClick={() => startRename(project)} className="btn-outline" disabled={isBusy}>
                        <Pencil size={13} />
                        <span>Rename</span>
                      </button>
                    )}
                    <button type="button" onClick={() => duplicateProject(project)} className="btn-outline" disabled={isBusy}>
                      <Copy size={13} />
                      <span>Duplicate</span>
                    </button>
                    <button type="button" onClick={() => deleteProject(project)} className="btn-danger-outline" disabled={isBusy}>
                      <Trash2 size={13} />
                      <span>Delete</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div style={{ padding: '18px 26px', borderTop: '1px solid var(--border-color)', display: 'flex', justifyContent: 'flex-end' }}>
          <button type="button" onClick={onNewProject} className="btn-primary">
            <PlusCircle size={14} />
            <span>New Project</span>
          </button>
        </div>
      </div>
    </div>
  );
}
