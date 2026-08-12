import React, { useState } from 'react';
import { 
  Terminal, 
  FileText, 
  ListFilter, 
  FileDiff, 
  CheckCircle2, 
  ChevronDown, 
  ChevronUp, 
  Copy, 
  Pin, 
  Search,
  Check
} from 'lucide-react';

export default function BottomPanel({ 
  activeBottomTab, 
  setActiveBottomTab, 
  bottomHeight, 
  setBottomHeight,
  isBottomCollapsed,
  setIsBottomCollapsed
}) {
  const [copied, setCopied] = useState(false);
  const [logFilter, setLogFilter] = useState('');

  const tabs = [
    { id: 'terminal', label: 'Terminal', icon: Terminal },
    { id: 'output', label: 'Output', icon: FileText },
    { id: 'logs', label: 'Logs', icon: ListFilter, badge: 'ERROR' },
    { id: 'diff', label: 'Diff', icon: FileDiff },
    { id: 'tests', label: 'Tests', icon: CheckCircle2, badge: '14/14' },
  ];

  const handleCopyDiff = () => {
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isBottomCollapsed) {
    return (
      <div style={{
        height: '32px',
        backgroundColor: 'var(--surface-1)',
        borderTop: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justify: 'space-between',
        padding: '0 12px',
        userSelect: 'none'
      }}>
        <div style={{ display: 'flex', gap: '16px' }}>
          {tabs.map(t => (
            <div 
              key={t.id} 
              onClick={() => { setActiveBottomTab(t.id); setIsBottomCollapsed(false); }}
              style={{ fontSize: '11px', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <span>{t.label}</span>
            </div>
          ))}
        </div>
        <button onClick={() => setIsBottomCollapsed(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
          <ChevronUp size={14} />
        </button>
      </div>
    );
  }

  return (
    <div style={{
      height: `${bottomHeight}px`,
      backgroundColor: 'var(--surface-1)',
      borderTop: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column',
      userSelect: 'none',
      zIndex: 20
    }}>
      {/* Header & Tabs */}
      <div style={{
        height: '32px',
        backgroundColor: 'var(--surface-2)',
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justify: 'space-between',
        padding: '0 12px'
      }}>
        <div style={{ display: 'flex', height: '100%' }}>
          {tabs.map(t => {
            const Icon = t.icon;
            const isActive = activeBottomTab === t.id;
            return (
              <div 
                key={t.id}
                onClick={() => setActiveBottomTab(t.id)}
                style={{
                  height: '100%',
                  padding: '0 12px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  backgroundColor: isActive ? 'var(--surface-1)' : 'transparent',
                  borderTop: isActive ? '2px solid var(--color-accent)' : '2px solid transparent',
                  cursor: 'pointer',
                  color: isActive ? 'var(--text-primary)' : 'var(--text-muted)',
                  fontSize: '11px',
                  fontWeight: 500
                }}
              >
                <Icon size={13} />
                <span>{t.label}</span>
                {t.badge && (
                  <span style={{ 
                    fontSize: '9px', 
                    padding: '1px 4px', 
                    borderRadius: '3px', 
                    backgroundColor: t.id === 'logs' ? 'rgba(240,96,90,0.2)' : 'rgba(61,214,140,0.2)',
                    color: t.id === 'logs' ? 'var(--color-failure)' : 'var(--color-success)'
                  }}>
                    {t.badge}
                  </span>
                )}
              </div>
            );
          })}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button onClick={() => setIsBottomCollapsed(true)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <ChevronDown size={14} />
          </button>
        </div>
      </div>

      {/* Tab Content Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 14px', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
        
        {/* Terminal Tab */}
        {activeBottomTab === 'terminal' && (
          <div style={{ color: 'var(--text-primary)', lineHeight: 1.6 }}>
            <div style={{ color: 'var(--text-muted)' }}>$ pytest app/tests/test_checkout.py --verbose</div>
            <div>============================= test session starts =============================</div>
            <div>platform win32 -- Python 3.11.4, pytest-7.4.0, pluggy-1.2.0</div>
            <div>rootdir: D:\Projects\API-DOCTOR</div>
            <div>collected 14 items</div>
            <br />
            <div>app/tests/test_checkout.py::test_valid_checkout <span style={{ color: 'var(--color-success)' }}>PASSED</span> [  7%]</div>
            <div>app/tests/test_checkout.py::test_missing_payment_method <span style={{ color: 'var(--color-success)' }}>PASSED</span> [ 14%]</div>
            <div>app/tests/test_checkout.py::test_invalid_token <span style={{ color: 'var(--color-success)' }}>PASSED</span> [ 21%]</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '6px' }}>
              <span style={{ color: 'var(--color-success)' }}>$</span>
              <span style={{ width: '8px', height: '14px', backgroundColor: 'var(--text-primary)', display: 'inline-block' }} />
            </div>
          </div>
        )}

        {/* Output Tab */}
        {activeBottomTab === 'output' && (
          <div style={{ color: 'var(--text-primary)', lineHeight: 1.6 }}>
            <div>[14:32:04] [INFO] API Doctor Agent Initialized</div>
            <div>[14:32:05] [INFO] Intercepted HTTP 500 error on endpoint /api/v1/checkout</div>
            <div>[14:32:06] [DEBUG] AST Tree built for app/demo_api/bugs.py</div>
            <div>[14:32:08] [INFO] Root cause pinpointed: NoneType property access on line 122</div>
            <div>[14:32:12] [INFO] Verification sandbox created. Executing regression suite...</div>
            <div style={{ color: 'var(--color-success)' }}>[14:32:15] [SUCCESS] All 14 regression tests passed cleanly.</div>
          </div>
        )}

        {/* Logs Tab */}
        {activeBottomTab === 'logs' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', backgroundColor: 'var(--surface-2)', padding: '2px 8px', borderRadius: '4px', border: '1px solid var(--border-color)' }}>
                <Search size={12} style={{ color: 'var(--text-muted)' }} />
                <input 
                  type="text" 
                  placeholder="Filter logs..."
                  value={logFilter}
                  onChange={e => setLogFilter(e.target.value)}
                  style={{ background: 'none', border: 'none', color: 'var(--text-primary)', fontSize: '11px', outline: 'none' }}
                />
              </div>
              <button style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }} title="Pin log auto-scroll">
                <Pin size={13} />
              </button>
            </div>

            <div style={{ color: 'var(--text-muted)' }}>14:32:05.102 [<span style={{ color: 'var(--text-muted)' }}>INFO</span>] Request received POST /api/v1/checkout</div>
            <div style={{ color: 'var(--color-warning)' }}>14:32:05.110 [<span style={{ color: 'var(--color-warning)' }}>WARN</span>] Missing payment_method key in JSON payload</div>
            <div style={{ color: 'var(--color-failure)' }}>14:32:05.115 [<span style={{ color: 'var(--color-failure)' }}>ERROR</span>] AttributeError: 'NoneType' object has no attribute 'token' at bugs.py:122</div>
          </div>
        )}

        {/* Diff Tab */}
        {activeBottomTab === 'diff' && (
          <div style={{ position: 'relative' }}>
            <button 
              onClick={handleCopyDiff}
              style={{
                position: 'absolute',
                top: 0,
                right: 0,
                background: 'var(--surface-2)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-primary)',
                padding: '4px 8px',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '10px',
                display: 'flex',
                alignItems: 'center',
                gap: '4px'
              }}
            >
              {copied ? <Check size={12} style={{ color: 'var(--color-success)' }} /> : <Copy size={12} />}
              <span>{copied ? 'Copied!' : 'Copy Patch'}</span>
            </button>

            <div style={{ lineHeight: 1.6 }}>
              <div>--- a/app/demo_api/bugs.py</div>
              <div>+++ b/app/demo_api/bugs.py</div>
              <div>@@ -121,3 +121,5 @@</div>
              <div style={{ backgroundColor: 'var(--diff-remove-bg)', color: 'var(--diff-remove-text)' }}>- payment_token = payment_method.token</div>
              <div style={{ backgroundColor: 'var(--diff-add-bg)', color: 'var(--diff-add-text)' }}>+ if not payment_method:</div>
              <div style={{ backgroundColor: 'var(--diff-add-bg)', color: 'var(--diff-add-text)' }}>+     raise ValueError("Missing payment method payload")</div>
              <div style={{ backgroundColor: 'var(--diff-add-bg)', color: 'var(--diff-add-text)' }}>+ payment_token = payment_method.token</div>
            </div>
          </div>
        )}

        {/* Tests Tab */}
        {activeBottomTab === 'tests' && (
          <div>
            <div style={{ marginBottom: '10px', color: 'var(--color-success)', fontWeight: 600 }}>
              Summary: 14/14 tests passed (Total time: 420ms)
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {[
                { name: 'test_checkout_valid_payload', time: '32ms' },
                { name: 'test_checkout_null_payment_method', time: '14ms' },
                { name: 'test_checkout_token_verification', time: '45ms' },
                { name: 'test_checkout_rate_limiting', time: '18ms' }
              ].map(test => (
                <div key={test.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 8px', backgroundColor: 'var(--surface-2)', borderRadius: '4px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <CheckCircle2 size={13} style={{ color: 'var(--color-success)' }} />
                    <span>{test.name}</span>
                  </div>
                  <span style={{ color: 'var(--text-muted)' }}>{test.time}</span>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
