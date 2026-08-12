import React, { useState } from 'react';
import { api } from '../api';
import { Loader2, LockKeyhole, ShieldCheck, Sparkles } from 'lucide-react';

const inputStyle = {
  width: '100%',
  padding: '11px 12px',
  backgroundColor: 'var(--surface-2)',
  border: '1px solid var(--border-color)',
  borderRadius: '8px',
  color: 'var(--text-primary)',
  fontSize: '12px',
  outline: 'none',
};

export default function LoginPage({ onAuthenticated }) {
  const [mode, setMode] = useState('login');
  const [loginForm, setLoginForm] = useState({ identifier: '', password: '' });
  const [registerForm, setRegisterForm] = useState({
    email: '',
    username: '',
    password: '',
    full_name: '',
    gender: '',
    age: '',
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  const submitLogin = async (e) => {
    e.preventDefault();
    setError('');
    setIsSubmitting(true);
    try {
      const res = await api.login(loginForm.identifier, loginForm.password);
      onAuthenticated?.(res.user);
    } catch (err) {
      setError(err.message || 'Login failed.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const submitRegister = async (e) => {
    e.preventDefault();
    setError('');
    setIsSubmitting(true);
    try {
      const res = await api.register({
        email: registerForm.email,
        username: registerForm.username,
        password: registerForm.password,
        full_name: registerForm.full_name,
        gender: registerForm.gender,
        age: registerForm.age ? Number(registerForm.age) : null,
      });
      onAuthenticated?.(res.user);
    } catch (err) {
      setError(err.message || 'Registration failed.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', width: '100vw', background: 'radial-gradient(circle at top, rgba(124,140,248,0.18), transparent 42%), #0b1020', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '28px' }}>
      <div style={{ width: 'min(980px, 96vw)', minHeight: 'min(720px, 92vh)', backgroundColor: 'var(--surface-1)', border: '1px solid var(--border-color)', borderRadius: '16px', overflow: 'hidden', boxShadow: '0 24px 70px rgba(0,0,0,0.45)', display: 'flex' }}>
        <div style={{ width: '44%', background: 'linear-gradient(180deg, rgba(124,140,248,0.18), rgba(124,140,248,0.05))', borderRight: '1px solid var(--border-color)', padding: '34px 30px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          <div>
            <div style={{ display: 'inline-flex', width: '48px', height: '48px', borderRadius: '14px', alignItems: 'center', justifyContent: 'center', background: 'linear-gradient(135deg, var(--color-accent), #8b5cf6)', color: '#fff', marginBottom: '18px' }}>
              <Sparkles size={20} />
            </div>
            <div style={{ fontSize: '11px', letterSpacing: '0.08em', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '10px' }}>API DOCTOR ACCESS</div>
            <div style={{ fontSize: '34px', lineHeight: 1.15, fontWeight: 700, color: 'var(--text-primary)', marginBottom: '14px' }}>
              Sign in to your AI incident command center.
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-muted)', lineHeight: 1.7 }}>
              Use email or username plus password to unlock API Doctor. New users can register a local account with profile details and continue directly into the workspace.
            </div>
          </div>
          <div style={{ display: 'grid', gap: '12px' }}>
            {[
              'Project-aware workspace and onboarding',
              'Saved profile credentials for return visits',
              'Local session logic for simple hackathon auth',
            ].map(item => (
              <div key={item} style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-primary)', fontSize: '12px' }}>
                <ShieldCheck size={14} style={{ color: 'var(--color-success)' }} />
                <span>{item}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ flex: 1, padding: '34px 34px 30px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', gap: '8px', marginBottom: '26px' }}>
            <button type="button" onClick={() => setMode('login')} className={mode === 'login' ? 'btn-primary' : 'btn-outline'}>
              <LockKeyhole size={14} />
              <span>Login</span>
            </button>
            <button type="button" onClick={() => setMode('register')} className={mode === 'register' ? 'btn-primary' : 'btn-outline'}>
              <Sparkles size={14} />
              <span>Register</span>
            </button>
          </div>

          {mode === 'login' ? (
            <form onSubmit={submitLogin} style={{ display: 'grid', gap: '16px', maxWidth: '420px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Email or username</label>
                <input value={loginForm.identifier} onChange={e => setLoginForm(prev => ({ ...prev, identifier: e.target.value }))} placeholder="you@example.com or doctor_user" style={inputStyle} />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Password</label>
                <input type="password" value={loginForm.password} onChange={e => setLoginForm(prev => ({ ...prev, password: e.target.value }))} placeholder="Enter password" style={inputStyle} />
              </div>
              {error && <div style={{ color: 'var(--color-failure)', fontSize: '12px' }}>{error}</div>}
              <button type="submit" disabled={isSubmitting} className="btn-primary" style={{ justifyContent: 'center', padding: '10px 16px' }}>
                {isSubmitting ? <Loader2 size={15} className="spin" /> : <LockKeyhole size={15} />}
                <span>Login</span>
              </button>
            </form>
          ) : (
            <form onSubmit={submitRegister} style={{ display: 'grid', gap: '14px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Email</label>
                  <input value={registerForm.email} onChange={e => setRegisterForm(prev => ({ ...prev, email: e.target.value }))} placeholder="you@example.com" style={inputStyle} />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Username</label>
                  <input value={registerForm.username} onChange={e => setRegisterForm(prev => ({ ...prev, username: e.target.value }))} placeholder="doctor_user" style={inputStyle} />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Full name</label>
                  <input value={registerForm.full_name} onChange={e => setRegisterForm(prev => ({ ...prev, full_name: e.target.value }))} placeholder="API Doctor User" style={inputStyle} />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Password</label>
                  <input type="password" value={registerForm.password} onChange={e => setRegisterForm(prev => ({ ...prev, password: e.target.value }))} placeholder="Create password" style={inputStyle} />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Gender</label>
                  <input value={registerForm.gender} onChange={e => setRegisterForm(prev => ({ ...prev, gender: e.target.value }))} placeholder="Optional" style={inputStyle} />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Age</label>
                  <input type="number" min="1" max="150" value={registerForm.age} onChange={e => setRegisterForm(prev => ({ ...prev, age: e.target.value }))} placeholder="Optional" style={inputStyle} />
                </div>
              </div>
              {error && <div style={{ color: 'var(--color-failure)', fontSize: '12px' }}>{error}</div>}
              <button type="submit" disabled={isSubmitting} className="btn-primary" style={{ justifyContent: 'center', padding: '10px 16px' }}>
                {isSubmitting ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />}
                <span>Create Account</span>
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
