import React, { useState } from 'react';
import { api } from '../api';
import { ArrowLeft, Eye, EyeOff, Loader2, LockKeyhole, ShieldCheck, Sparkles } from 'lucide-react';

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

function calculateAgeFromDOB(dobString) {
  if (!dobString) return null;
  const dob = new Date(dobString);
  if (isNaN(dob.getTime())) return null;
  const today = new Date();
  let age = today.getFullYear() - dob.getFullYear();
  const monthDiff = today.getMonth() - dob.getMonth();
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < dob.getDate())) {
    age--;
  }
  return age >= 0 ? age : null;
}

export default function LoginPage({ onAuthenticated }) {
  const [mode, setMode] = useState('login');
  const [showLoginPassword, setShowLoginPassword] = useState(false);
  const [showRegisterPassword, setShowRegisterPassword] = useState(false);

  const [loginForm, setLoginForm] = useState({ identifier: '', password: '' });
  const [registerForm, setRegisterForm] = useState({
    email: '',
    username: '',
    password: '',
    full_name: '',
    gender: '',
    date_of_birth: '',
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

  const handleDOBChange = (e) => {
    const dobValue = e.target.value;
    const computedAge = calculateAgeFromDOB(dobValue);
    setRegisterForm(prev => ({
      ...prev,
      date_of_birth: dobValue,
      age: computedAge !== null ? String(computedAge) : ''
    }));
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
        date_of_birth: registerForm.date_of_birth,
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
    <div style={{ minHeight: '100vh', width: '100vw', background: 'radial-gradient(circle at 30% 20%, rgba(240, 169, 58, 0.12), transparent 45%), #0A0E14', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px', overflowY: 'auto' }}>
      <div className="auth-shell" style={{ width: 'min(960px, 96vw)', minHeight: 'min(680px, 92vh)', backgroundColor: 'var(--surface-1)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-lg)', overflow: 'hidden', boxShadow: 'var(--shadow-elevation)' }}>
        <div className="auth-aside" style={{ background: 'linear-gradient(180deg, rgba(240, 169, 58, 0.08), rgba(27, 36, 50, 0.4))', borderRight: '1px solid var(--border-color)', padding: '36px 32px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: '24px' }}>
          <div>
            <div style={{ display: 'inline-flex', width: '44px', height: '44px', borderRadius: 'var(--radius-md)', alignItems: 'center', justifyContent: 'center', background: 'var(--color-accent)', color: '#0A0E14', marginBottom: '20px', boxShadow: '0 4px 14px rgba(240, 169, 58, 0.3)' }}>
              <Sparkles size={22} />
            </div>
            <div style={{ fontSize: '11px', letterSpacing: '0.08em', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '10px', fontFamily: 'var(--font-heading)' }}>API DOCTOR // AUTHENTICATION</div>
            <h1 style={{ fontSize: '28px', lineHeight: 1.2, fontWeight: 700, color: 'var(--text-primary)', marginBottom: '14px', fontFamily: 'var(--font-heading)' }}>
              Automated production failure diagnosis & code repair.
            </h1>
            <div style={{ fontSize: '13px', color: 'var(--text-muted)', lineHeight: 1.6 }}>
              Enter your credentials to open the API Doctor workspace. Authenticate to diagnose a current stack trace, inspect live steps, and generate pull requests.
            </div>
          </div>
          <div style={{ display: 'grid', gap: '12px' }}>
            {[
              'Context-aware repository analysis',
              'Deterministic stack trace diagnosis',
              'Automated sandbox verification & PR patch creation',
            ].map(item => (
              <div key={item} style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-primary)', fontSize: '12px' }}>
                <ShieldCheck size={15} style={{ color: 'var(--color-success)' }} />
                <span>{item}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="auth-main" style={{ padding: '36px 36px 30px', display: 'flex', flexDirection: 'column', position: 'relative' }}>
          {mode === 'register' && (
            <button
              type="button"
              onClick={() => { setMode('login'); setError(''); }}
              className="auth-back"
              title="Back to Login"
              aria-label="Back to Login"
            >
              <ArrowLeft size={15} />
            </button>
          )}

          <div style={{ display: 'flex', gap: '8px', marginBottom: '28px' }}>
            <button type="button" onClick={() => { setMode('login'); setError(''); }} className={mode === 'login' ? 'btn-primary' : 'btn-outline'}>
              <LockKeyhole size={14} />
              <span>Login</span>
            </button>
            <button type="button" onClick={() => { setMode('register'); setError(''); }} className={mode === 'register' ? 'btn-primary' : 'btn-outline'}>
              <Sparkles size={14} />
              <span>Register</span>
            </button>
          </div>

          {mode === 'login' ? (
            <form onSubmit={submitLogin} style={{ display: 'grid', gap: '16px', maxWidth: '420px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Email or username</label>
                <input value={loginForm.identifier} onChange={e => setLoginForm(prev => ({ ...prev, identifier: e.target.value }))} placeholder="you@example.com or doctor_user" style={inputStyle} required />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Password</label>
                <div style={{ position: 'relative', width: '100%' }}>
                  <input
                    type={showLoginPassword ? 'text' : 'password'}
                    value={loginForm.password}
                    onChange={e => setLoginForm(prev => ({ ...prev, password: e.target.value }))}
                    placeholder="Enter password"
                    style={{ ...inputStyle, paddingRight: '36px' }}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowLoginPassword(prev => !prev)}
                    style={{
                      position: 'absolute',
                      right: '10px',
                      top: '50%',
                      transform: 'translateY(-50%)',
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      padding: '2px'
                    }}
                    title={showLoginPassword ? 'Hide password' : 'Show password'}
                  >
                    {showLoginPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
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
                  <input value={registerForm.email} onChange={e => setRegisterForm(prev => ({ ...prev, email: e.target.value }))} placeholder="you@example.com" style={inputStyle} required />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Username</label>
                  <input value={registerForm.username} onChange={e => setRegisterForm(prev => ({ ...prev, username: e.target.value }))} placeholder="doctor_user" style={inputStyle} required />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Full name</label>
                  <input value={registerForm.full_name} onChange={e => setRegisterForm(prev => ({ ...prev, full_name: e.target.value }))} placeholder="API Doctor User" style={inputStyle} />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Password</label>
                  <div style={{ position: 'relative', width: '100%' }}>
                    <input
                      type={showRegisterPassword ? 'text' : 'password'}
                      value={registerForm.password}
                      onChange={e => setRegisterForm(prev => ({ ...prev, password: e.target.value }))}
                      placeholder="Create password"
                      style={{ ...inputStyle, paddingRight: '36px' }}
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setShowRegisterPassword(prev => !prev)}
                      style={{
                        position: 'absolute',
                        right: '10px',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        background: 'none',
                        border: 'none',
                        color: 'var(--text-muted)',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        padding: '2px'
                      }}
                      title={showRegisterPassword ? 'Hide password' : 'Show password'}
                    >
                      {showRegisterPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Gender</label>
                  <select
                    value={registerForm.gender}
                    onChange={e => setRegisterForm(prev => ({ ...prev, gender: e.target.value }))}
                    style={inputStyle}
                  >
                    <option value="">Select gender</option>
                    <option value="Male">Male</option>
                    <option value="Female">Female</option>
                    <option value="Others">Others</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Date of Birth</label>
                  <input
                    type="date"
                    value={registerForm.date_of_birth}
                    onChange={handleDOBChange}
                    style={inputStyle}
                  />
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
