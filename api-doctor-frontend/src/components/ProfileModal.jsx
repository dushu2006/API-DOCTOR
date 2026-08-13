import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { ImagePlus, KeyRound, Loader2, LogOut, Save, ShieldAlert, Trash2 } from 'lucide-react';

const inputStyle = {
  width: '100%',
  padding: '10px 12px',
  backgroundColor: 'var(--surface-2)',
  border: '1px solid var(--border-color)',
  borderRadius: '8px',
  color: 'var(--text-primary)',
  fontSize: '12px',
  outline: 'none'
};

export default function ProfileModal({
  isOpen,
  user,
  projects = [],
  currentProject,
  onClose,
  onUpdated,
  onLogout,
  onDeleteAccount,
}) {
  const [form, setForm] = useState({ email: '', username: '', full_name: '', gender: '', age: '', avatar_data: '' });
  const [passwordForm, setPasswordForm] = useState({ current_password: '', new_password: '' });
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isChangingPassword, setIsChangingPassword] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!user) return;
    setForm({
      email: user.email || '',
      username: user.username || '',
      full_name: user.full_name || '',
      gender: user.gender || '',
      date_of_birth: user.date_of_birth || '',
      age: user.age || '',
      avatar_data: user.avatar_data || '',
    });
    setPasswordForm({ current_password: '', new_password: '' });
    setDeleteConfirm('');
    setError('');
    setMessage('');
  }, [user, isOpen]);

  const initials = useMemo(() => {
    const source = form.full_name || form.username || 'U';
    return source.split(' ').map(part => part[0]).join('').slice(0, 2).toUpperCase();
  }, [form.full_name, form.username]);

  if (!isOpen || !user) return null;

  const saveProfile = async () => {
    setError('');
    setMessage('');
    setIsSaving(true);
    try {
      const updated = await api.updateCurrentUser({
        email: form.email,
        username: form.username,
        full_name: form.full_name,
        gender: form.gender,
        date_of_birth: form.date_of_birth,
        age: form.age ? Number(form.age) : null,
        avatar_data: form.avatar_data,
      });
      onUpdated?.(updated);
      setMessage('Profile updated.');
    } catch (err) {
      setError(err.message || 'Unable to update profile.');
    } finally {
      setIsSaving(false);
    }
  };

  const changePassword = async () => {
    setError('');
    setMessage('');
    setIsChangingPassword(true);
    try {
      await api.changePassword(passwordForm.current_password, passwordForm.new_password);
      setPasswordForm({ current_password: '', new_password: '' });
      setMessage('Password updated successfully.');
    } catch (err) {
      setError(err.message || 'Unable to update password.');
    } finally {
      setIsChangingPassword(false);
    }
  };

  const readAvatar = async (file) => {
    if (!file) return;
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    setForm(prev => ({ ...prev, avatar_data: String(dataUrl || '') }));
  };

  const deleteAccount = async () => {
    if (deleteConfirm.trim() !== user.username) {
      setError(`Type ${user.username} to confirm account deletion.`);
      return;
    }
    setError('');
    setIsDeleting(true);
    try {
      await onDeleteAccount?.();
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1200, backgroundColor: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
      <div style={{ width: 'min(960px, 96vw)', maxHeight: '92vh', overflow: 'hidden', backgroundColor: 'var(--surface-1)', border: '1px solid var(--border-color)', borderRadius: '14px', boxShadow: '0 20px 60px rgba(0,0,0,0.45)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '22px 24px', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', gap: '18px' }}>
          {form.avatar_data ? (
            <img src={form.avatar_data} alt="Avatar" style={{ width: '64px', height: '64px', borderRadius: '18px', objectFit: 'cover', border: '1px solid var(--border-color)' }} />
          ) : (
            <div style={{ width: '64px', height: '64px', borderRadius: '18px', backgroundColor: 'rgba(124,140,248,0.16)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-accent)', fontWeight: 700, fontSize: '20px' }}>{initials}</div>
          )}
          <div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', letterSpacing: '0.08em', fontWeight: 700, marginBottom: '6px' }}>PROFILE</div>
            <div style={{ fontSize: '22px', fontWeight: 700, color: 'var(--text-primary)' }}>{form.full_name || form.username}</div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{form.email}</div>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '22px 24px', display: 'grid', gap: '18px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '12px' }}>
            <StatCard label="Projects" value={String(projects.length)} />
            <StatCard label="Current Project" value={currentProject?.name || 'None'} />
            <StatCard label="Diagnosis Storage" value="None" />
          </div>

          <Section title="Profile Details">
            <div style={{ display: 'grid', gap: '14px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <Field label="Email"><input value={form.email} onChange={e => setForm(prev => ({ ...prev, email: e.target.value }))} style={inputStyle} /></Field>
                <Field label="Username"><input value={form.username} onChange={e => setForm(prev => ({ ...prev, username: e.target.value }))} style={inputStyle} /></Field>
              </div>
              <Field label="Full name"><input value={form.full_name} onChange={e => setForm(prev => ({ ...prev, full_name: e.target.value }))} style={inputStyle} /></Field>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <Field label="Gender">
                  <select value={form.gender} onChange={e => setForm(prev => ({ ...prev, gender: e.target.value }))} style={inputStyle}>
                    <option value="">Select gender</option>
                    <option value="Male">Male</option>
                    <option value="Female">Female</option>
                    <option value="Others">Others</option>
                  </select>
                </Field>
                <Field label="Date of Birth">
                  <input type="date" value={form.date_of_birth} onChange={e => setForm(prev => ({ ...prev, date_of_birth: e.target.value }))} style={inputStyle} />
                </Field>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Avatar</label>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                  <label className="btn-outline" style={{ cursor: 'pointer' }}>
                    <ImagePlus size={14} />
                    <span>Upload Avatar</span>
                    <input type="file" accept="image/*" style={{ display: 'none' }} onChange={e => readAvatar(e.target.files?.[0])} />
                  </label>
                  {form.avatar_data && (
                    <button type="button" className="btn-outline" onClick={() => setForm(prev => ({ ...prev, avatar_data: '' }))}>Remove</button>
                  )}
                </div>
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button type="button" onClick={saveProfile} disabled={isSaving} className="btn-primary">
                  {isSaving ? <Loader2 size={14} className="spin" /> : <Save size={14} />}
                  <span>Save Profile</span>
                </button>
              </div>
            </div>
          </Section>

          <Section title="Change Password">
            <div style={{ display: 'grid', gap: '12px' }}>
              <Field label="Current password"><input type="password" value={passwordForm.current_password} onChange={e => setPasswordForm(prev => ({ ...prev, current_password: e.target.value }))} style={inputStyle} /></Field>
              <Field label="New password"><input type="password" value={passwordForm.new_password} onChange={e => setPasswordForm(prev => ({ ...prev, new_password: e.target.value }))} style={inputStyle} /></Field>
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button type="button" onClick={changePassword} disabled={isChangingPassword} className="btn-outline">
                  {isChangingPassword ? <Loader2 size={14} className="spin" /> : <KeyRound size={14} />}
                  <span>Update Password</span>
                </button>
              </div>
            </div>
          </Section>

          <Section title="Danger Zone">
            <div style={{ display: 'grid', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--color-warning)', fontSize: '12px' }}>
                <ShieldAlert size={15} />
                <span>Deleting your account removes your local profile, sessions, and owned projects.</span>
              </div>
              <Field label={`Type ${user.username} to confirm deletion`}><input value={deleteConfirm} onChange={e => setDeleteConfirm(e.target.value)} style={inputStyle} /></Field>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px' }}>
                <button type="button" onClick={onLogout} className="btn-outline">
                  <LogOut size={14} />
                  <span>Logout</span>
                </button>
                <button type="button" onClick={deleteAccount} disabled={isDeleting} className="btn-danger-outline">
                  {isDeleting ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />}
                  <span>Delete Account</span>
                </button>
              </div>
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

function StatCard({ label, value }) {
  return (
    <div style={{ backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px' }}>
      <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.08em', fontWeight: 700, marginBottom: '8px' }}>{label.toUpperCase()}</div>
      <div style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>{value}</div>
    </div>
  );
}
