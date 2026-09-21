import React, { useState, useEffect, useCallback } from 'react';
import {
  Activity,
  Cpu,
  Database,
  RefreshCw,
  Play,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  KeyRound,
  ShieldCheck,
  Terminal,
  Clock,
  Plus,
  Server,
  Layers,
  Sparkles,
  Mail,
  ArrowRight,
} from 'lucide-react';

interface NodeHealth {
  status: string;
  nodeRole: string;
  version: string;
  uptimeSeconds: number;
  uptimeFormatted: string;
  sockets: {
    active: number;
    totalProcessed: number;
    completed: number;
    failed: number;
  };
  memory: {
    rssMb: number;
    heapUsedMb: number;
    heapTotalMb: number;
  };
  supabase: {
    configured: boolean;
    provider: string;
    url: string;
    totalLoadedAccounts: number;
  };
  timestamp: string;
}

interface StockAccount {
  id: number | string;
  steam_username: string;
  steam_password?: string;
  original_email?: string;
  status: 'available' | 'processing' | 'completed' | 'failed';
  target_verification_code?: string | null;
  shared_secret?: string;
  created_at?: string;
  updated_at?: string;
  last_error?: string | null;
}

interface LogEntry {
  id: string;
  timestamp: string;
  level: 'info' | 'warn' | 'error';
  message: string;
  meta?: Record<string, unknown>;
}

export default function App() {
  const [health, setHealth] = useState<NodeHealth | null>(null);
  const [accounts, setAccounts] = useState<StockAccount[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [taskResult, setTaskResult] = useState<any | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);

  // New Account Modal / Form State
  const [showAddModal, setShowAddModal] = useState(false);
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newSecret, setNewSecret] = useState('');

  // 2FA TOTP Generator test state
  const [totpSecret, setTotpSecret] = useState('');
  const [generatedTotp, setGeneratedTotp] = useState<{ code: string; secondsRemaining: number } | null>(null);

  // Email Change Modal State
  const [emailChangeAccount, setEmailChangeAccount] = useState<StockAccount | null>(null);
  const [targetEmailInput, setTargetEmailInput] = useState('');
  const [emailPasswordInput, setEmailPasswordInput] = useState('');
  const [manualCodeInput, setManualCodeInput] = useState('');
  const [isChangingEmail, setIsChangingEmail] = useState(false);

  const fetchHealth = useCallback(async () => {
    try {
      const res = await fetch('/health');
      if (res.ok) {
        const data = await res.json();
        setHealth(data);
      }
    } catch (err) {
      console.warn('Healthcheck error:', err);
    }
  }, []);

  const fetchAccounts = useCallback(async () => {
    try {
      const res = await fetch('/api/accounts');
      if (res.ok) {
        const data = await res.json();
        setAccounts(data.accounts || []);
      }
    } catch (err) {
      console.warn('Accounts fetch error:', err);
    }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch('/api/stats');
      if (res.ok) {
        const data = await res.json();
        if (data.logs) {
          setLogs(data.logs);
        }
      }
    } catch (err) {
      console.warn('Stats fetch error:', err);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([fetchHealth(), fetchAccounts(), fetchStats()]);
    setLoading(false);
  }, [fetchHealth, fetchAccounts, fetchStats]);

  useEffect(() => {
    refreshAll();
    const interval = setInterval(() => {
      fetchHealth();
      fetchStats();
      fetchAccounts();
    }, 4000);
    return () => clearInterval(interval);
  }, [refreshAll, fetchHealth, fetchStats, fetchAccounts]);

  const handleProcessTask = async (accountOverride?: StockAccount) => {
    setIsProcessing(true);
    setTaskResult(null);

    const payload = accountOverride
      ? {
          id: accountOverride.id,
          steam_username: accountOverride.steam_username,
          steam_password: accountOverride.steam_password,
          original_email: accountOverride.original_email,
          shared_secret: accountOverride.shared_secret,
        }
      : {};

    try {
      const res = await fetch('/api/process-task', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      setTaskResult({
        ok: res.ok,
        status: res.status,
        data,
      });

      await refreshAll();
    } catch (err: any) {
      setTaskResult({
        ok: false,
        status: 500,
        data: { error: err.message },
      });
    } finally {
      setIsProcessing(false);
    }
  };

  const handleAddAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUsername || !newPassword) return;

    try {
      const res = await fetch('/api/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          steam_username: newUsername,
          steam_password: newPassword,
          original_email: newEmail,
          shared_secret: newSecret,
        }),
      });

      if (res.ok) {
        setNewUsername('');
        setNewPassword('');
        setNewEmail('');
        setNewSecret('');
        setShowAddModal(false);
        await refreshAll();
      }
    } catch (err) {
      console.error('Failed to add account:', err);
    }
  };

  const handleGenerateTotp = async () => {
    if (!totpSecret) return;
    try {
      const res = await fetch('/api/generate-totp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shared_secret: totpSecret }),
      });
      const data = await res.json();
      if (res.ok) {
        setGeneratedTotp(data);
      } else {
        alert(data.error || 'Failed to generate TOTP');
      }
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleExecuteEmailChange = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!emailChangeAccount || !targetEmailInput) return;

    setIsChangingEmail(true);
    try {
      const res = await fetch('/api/change-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: emailChangeAccount.id,
          steam_username: emailChangeAccount.steam_username,
          steam_password: emailChangeAccount.steam_password,
          original_email: emailChangeAccount.original_email,
          email_password: emailPasswordInput || undefined,
          target_email: targetEmailInput,
          verification_code: manualCodeInput || undefined,
        }),
      });

      const data = await res.json();
      setTaskResult({
        ok: res.ok,
        status: res.status,
        data,
      });

      if (res.ok) {
        setEmailChangeAccount(null);
        setTargetEmailInput('');
        setEmailPasswordInput('');
        setManualCodeInput('');
        await refreshAll();
      }
    } catch (err: any) {
      setTaskResult({
        ok: false,
        status: 500,
        data: { error: err.message },
      });
    } finally {
      setIsChangingEmail(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans antialiased selection:bg-cyan-500/30">
      {/* Top Protocol Header */}
      <header id="header-node-status" className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3.5 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20 ring-1 ring-cyan-400/30">
              <Cpu className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-bold tracking-tight text-white">Steam Automation Node</h1>
                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                  CM Sockets v5
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Protocol-level multi-account worker &bull; Supabase sync enabled
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/60 text-xs">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-slate-300 font-medium">Node Healthy</span>
              <span className="text-slate-500">|</span>
              <span className="text-slate-400 font-mono">{health?.uptimeFormatted || '0h 0m 0s'}</span>
            </div>

            <button
              id="btn-refresh-metrics"
              onClick={refreshAll}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 active:scale-95 text-slate-300 hover:text-white text-xs font-medium transition border border-slate-700 cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              Sync
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Metric Cards Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div id="metric-active-sockets" className="p-4 rounded-xl bg-slate-900/70 border border-slate-800 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between text-slate-400 text-xs font-medium mb-1">
              <span>Active CM Sockets</span>
              <Activity className="w-4 h-4 text-cyan-400" />
            </div>
            <div className="text-2xl font-bold text-white tracking-tight font-mono">
              {health?.sockets?.active ?? 0}
            </div>
            <p className="text-[11px] text-slate-400 mt-1">Direct TCP/WebSocket connections</p>
          </div>

          <div id="metric-total-tasks" className="p-4 rounded-xl bg-slate-900/70 border border-slate-800 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between text-slate-400 text-xs font-medium mb-1">
              <span>Processed Tasks</span>
              <Server className="w-4 h-4 text-blue-400" />
            </div>
            <div className="text-2xl font-bold text-white tracking-tight font-mono">
              {health?.sockets?.totalProcessed ?? 0}
            </div>
            <p className="text-[11px] text-slate-400 mt-1">Lifecycle executions via Express</p>
          </div>

          <div id="metric-success-rate" className="p-4 rounded-xl bg-slate-900/70 border border-slate-800 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between text-slate-400 text-xs font-medium mb-1">
              <span>Authenticated</span>
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="text-2xl font-bold text-emerald-400 tracking-tight font-mono">
              {health?.sockets?.completed ?? 0}
              <span className="text-xs text-slate-400 font-normal ml-2">
                / {health?.sockets?.failed ?? 0} failed
              </span>
            </div>
            <p className="text-[11px] text-slate-400 mt-1">Status: completed in Supabase</p>
          </div>

          <div id="metric-database-status" className="p-4 rounded-xl bg-slate-900/70 border border-slate-800 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between text-slate-400 text-xs font-medium mb-1">
              <span>Database Backend</span>
              <Database className="w-4 h-4 text-purple-400" />
            </div>
            <div className="text-sm font-semibold text-white tracking-tight truncate">
              {health?.supabase?.configured ? 'Supabase Connected' : 'Staging Memory Store'}
            </div>
            <p className="text-[11px] text-slate-400 mt-1 truncate">
              Table: <span className="font-mono text-purple-300">stock_accounts</span>
            </p>
          </div>
        </div>

        {/* Primary Action Console */}
        <section id="section-action-console" className="p-5 rounded-2xl bg-gradient-to-b from-slate-900 to-slate-900/90 border border-slate-800/80 shadow-xl space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                <Play className="w-4 h-4 text-cyan-400" />
                Task Orchestration Engine
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Executes <code className="text-cyan-300 font-mono">POST /api/process-task</code> to poll next available account, authenticate via socket, and save cookies.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button
                id="btn-process-next-task"
                onClick={() => handleProcessTask()}
                disabled={isProcessing}
                className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 active:scale-95 text-white text-xs font-semibold shadow-lg shadow-cyan-500/25 transition disabled:opacity-50 cursor-pointer"
              >
                {isProcessing ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Processing Socket Logon...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-white" />
                    Trigger Next Account Task
                  </>
                )}
              </button>

              <button
                id="btn-open-add-modal"
                onClick={() => setShowAddModal(true)}
                className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 active:scale-95 text-slate-200 text-xs font-medium border border-slate-700 transition cursor-pointer"
              >
                <Plus className="w-4 h-4" />
                Add Account
              </button>
            </div>
          </div>

          {/* Last Execution Result Box */}
          {taskResult && (
            <div
              id="box-task-result"
              className={`p-4 rounded-xl text-xs font-mono border transition-all ${
                taskResult.ok
                  ? 'bg-emerald-950/30 border-emerald-500/30 text-emerald-200'
                  : 'bg-rose-950/30 border-rose-500/30 text-rose-200'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2 font-semibold">
                  {taskResult.ok ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <XCircle className="w-4 h-4 text-rose-400" />
                  )}
                  <span>HTTP {taskResult.status} Response from /api/process-task</span>
                </div>
                <button
                  onClick={() => setTaskResult(null)}
                  className="text-slate-400 hover:text-white text-[11px] underline cursor-pointer"
                >
                  Clear
                </button>
              </div>
              <pre className="overflow-x-auto max-h-48 p-2 rounded bg-black/40 text-[11px] leading-relaxed">
                {JSON.stringify(taskResult.data, null, 2)}
              </pre>
            </div>
          )}
        </section>

        {/* Two-Column Layout: Stock Accounts Table & Socket Logs / Tools */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left 7 Cols: Supabase stock_accounts Queue */}
          <div className="lg:col-span-7 space-y-4">
            <div className="p-5 rounded-2xl bg-slate-900/80 border border-slate-800 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Layers className="w-4 h-4 text-purple-400" />
                  <h2 className="text-sm font-semibold text-white">
                    Supabase Queue &bull; <span className="font-mono text-purple-300">stock_accounts</span>
                  </h2>
                </div>
                <span className="text-xs text-slate-400">
                  {accounts.length} Total Record{accounts.length === 1 ? '' : 's'}
                </span>
              </div>

              {accounts.length === 0 ? (
                <div className="text-center py-10 border border-dashed border-slate-800 rounded-xl text-slate-500 text-xs">
                  No accounts in database. Click &ldquo;Add Account&rdquo; to insert a test record.
                </div>
              ) : (
                <div className="overflow-x-auto border border-slate-800 rounded-xl">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-800/60 text-slate-400 uppercase text-[10px] tracking-wider border-b border-slate-800">
                      <tr>
                        <th className="p-3">Username</th>
                        <th className="p-3">Status</th>
                        <th className="p-3">Target Code</th>
                        <th className="p-3 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono">
                      {accounts.map((acc) => {
                        let statusColor = 'bg-slate-700/40 text-slate-300 border-slate-600';
                        if (acc.status === 'available') statusColor = 'bg-cyan-500/10 text-cyan-300 border-cyan-500/30';
                        if (acc.status === 'processing') statusColor = 'bg-amber-500/10 text-amber-300 border-amber-500/30';
                        if (acc.status === 'completed') statusColor = 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30';
                        if (acc.status === 'failed') statusColor = 'bg-rose-500/10 text-rose-300 border-rose-500/30';

                        return (
                          <tr key={acc.id} className="hover:bg-slate-800/30 transition">
                            <td className="p-3">
                              <div className="font-semibold text-white">{acc.steam_username}</div>
                              <div className="text-[10px] text-slate-400 font-sans">{acc.original_email || 'No email attached'}</div>
                              {acc.last_error && (
                                <div className="text-[10px] text-rose-400 mt-0.5 truncate max-w-[200px]" title={acc.last_error}>
                                  Err: {acc.last_error}
                                </div>
                              )}
                            </td>
                            <td className="p-3">
                              <span className={`inline-block px-2 py-0.5 text-[10px] rounded-full border ${statusColor}`}>
                                {acc.status}
                              </span>
                            </td>
                            <td className="p-3">
                              {acc.target_verification_code ? (
                                <span className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-cyan-300 font-bold tracking-widest">
                                  {acc.target_verification_code}
                                </span>
                              ) : (
                                <span className="text-slate-600">&mdash;</span>
                              )}
                            </td>
                            <td className="p-3 text-right">
                              <div className="flex items-center justify-end gap-1.5">
                                <button
                                  onClick={() => handleProcessTask(acc)}
                                  disabled={isProcessing || isChangingEmail}
                                  className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-cyan-400 hover:text-cyan-300 border border-slate-700 text-[11px] transition cursor-pointer disabled:opacity-40"
                                >
                                  Run Socket
                                </button>
                                <button
                                  onClick={() => {
                                    setEmailChangeAccount(acc);
                                    setTargetEmailInput('');
                                    setManualCodeInput('');
                                    setEmailPasswordInput('');
                                  }}
                                  disabled={isProcessing || isChangingEmail}
                                  className="inline-flex items-center gap-1 px-2 py-1 rounded bg-indigo-950/60 hover:bg-indigo-900/80 text-indigo-300 hover:text-white border border-indigo-700/50 text-[11px] transition cursor-pointer disabled:opacity-40"
                                >
                                  <Mail className="w-3 h-3" />
                                  Change Email
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Quick 2FA TOTP Generator Tool */}
            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
              <div className="flex items-center gap-2 mb-2">
                <KeyRound className="w-4 h-4 text-amber-400" />
                <h3 className="text-xs font-semibold text-white">Local steam-totp Generator (2FA Verification)</h3>
              </div>
              <p className="text-[11px] text-slate-400 mb-3">
                Generates local Steam Guard codes from Base64 shared secrets without calling external APIs or browser DOM.
              </p>

              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="Paste shared_secret (e.g. Base64 2FA secret)..."
                  value={totpSecret}
                  onChange={(e) => setTotpSecret(e.target.value)}
                  className="flex-1 px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white font-mono focus:outline-none focus:border-amber-400/50"
                />
                <button
                  onClick={handleGenerateTotp}
                  className="px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 text-xs font-semibold border border-amber-500/30 transition cursor-pointer"
                >
                  Generate
                </button>
              </div>

              {generatedTotp && (
                <div className="mt-3 p-2.5 rounded-lg bg-amber-950/20 border border-amber-500/20 flex items-center justify-between font-mono text-xs">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4 text-amber-400" />
                    <span className="text-slate-300">Steam Guard Code:</span>
                    <span className="text-base font-bold text-amber-300 tracking-widest">{generatedTotp.code}</span>
                  </div>
                  <span className="text-[10px] text-slate-400">Expires in {generatedTotp.secondsRemaining}s</span>
                </div>
              )}
            </div>
          </div>

          {/* Right 5 Cols: Live Socket Event Logs */}
          <div className="lg:col-span-5 space-y-4">
            <div className="p-5 rounded-2xl bg-slate-900/80 border border-slate-800 shadow-sm flex flex-col h-[520px]">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Terminal className="w-4 h-4 text-cyan-400" />
                  <h2 className="text-sm font-semibold text-white">Live CM Socket Stream</h2>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-slate-800 text-[10px] text-slate-400 font-mono">
                  {logs.length} events
                </span>
              </div>

              <div className="flex-1 overflow-y-auto space-y-2 p-2 rounded-xl bg-slate-950 border border-slate-800/80 font-mono text-[11px]">
                {logs.length === 0 ? (
                  <div className="text-center py-12 text-slate-600">Waiting for socket activity...</div>
                ) : (
                  logs.map((log) => {
                    let badgeColor = 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20';
                    if (log.level === 'warn') badgeColor = 'text-amber-400 bg-amber-500/10 border-amber-500/20';
                    if (log.level === 'error') badgeColor = 'text-rose-400 bg-rose-500/10 border-rose-500/20';

                    return (
                      <div key={log.id} className="p-2 rounded bg-slate-900/60 border border-slate-800/50 space-y-1">
                        <div className="flex items-center justify-between text-[10px] text-slate-500">
                          <span className={`px-1.5 py-0.2 rounded uppercase font-bold border ${badgeColor}`}>
                            {log.level}
                          </span>
                          <span>{new Date(log.timestamp).toLocaleTimeString()}</span>
                        </div>
                        <p className="text-slate-200 break-words leading-tight">{log.message}</p>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Add Account Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Plus className="w-4 h-4 text-cyan-400" />
                Enqueue Account to stock_accounts
              </h3>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-slate-400 hover:text-white text-xs cursor-pointer"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleAddAccount} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-400 mb-1">Steam Username *</label>
                <input
                  type="text"
                  required
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  placeholder="e.g. steam_bot_01"
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white font-mono focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1">Steam Password *</label>
                <input
                  type="password"
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Password"
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white font-mono focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1">Original Email (optional)</label>
                <input
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  placeholder="bot@example.com"
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white font-mono focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1">2FA Shared Secret (optional)</label>
                <input
                  type="text"
                  value={newSecret}
                  onChange={(e) => setNewSecret(e.target.value)}
                  placeholder="Base64 Steam Guard shared secret"
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white font-mono focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-semibold shadow-md transition cursor-pointer"
                >
                  Enqueue
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Steam Email Change & Outlook Verification Modal */}
      {emailChangeAccount && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-xs">
          <div className="w-full max-w-lg p-6 rounded-2xl bg-slate-900 border border-indigo-900/60 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-indigo-500/20 text-indigo-400">
                  <Mail className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">Steam Email Change Engine</h3>
                  <p className="text-[11px] text-slate-400 font-mono">
                    Target Account: <span className="text-indigo-300">{emailChangeAccount.steam_username}</span>
                  </p>
                </div>
              </div>
              <button
                onClick={() => setEmailChangeAccount(null)}
                disabled={isChangingEmail}
                className="text-slate-400 hover:text-white text-base cursor-pointer disabled:opacity-30"
              >
                &times;
              </button>
            </div>

            <div className="p-3 rounded-xl bg-slate-950/70 border border-slate-800 text-[11px] space-y-1.5 text-slate-300">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Current Associated Email:</span>
                <span className="font-mono text-cyan-300">{emailChangeAccount.original_email || 'Not configured in DB'}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Automated Pipeline:</span>
                <span className="text-slate-400">CM Socket &rarr; WebSession &rarr; Outlook IMAP &rarr; Steam Help</span>
              </div>
            </div>

            <form onSubmit={handleExecuteEmailChange} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 font-medium mb-1">
                  New Target Email Address <span className="text-rose-400">*</span>
                </label>
                <input
                  type="email"
                  required
                  value={targetEmailInput}
                  onChange={(e) => setTargetEmailInput(e.target.value)}
                  placeholder="e.g. customer_new_email@example.com"
                  disabled={isChangingEmail}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white font-mono focus:outline-none focus:border-indigo-500 disabled:opacity-50"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1">
                  Outlook Email Password <span className="text-[10px] text-slate-500">(leave blank if already stored in DB)</span>
                </label>
                <input
                  type="password"
                  value={emailPasswordInput}
                  onChange={(e) => setEmailPasswordInput(e.target.value)}
                  placeholder="Optional: password to read verification code from Outlook"
                  disabled={isChangingEmail}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white font-mono focus:outline-none focus:border-indigo-500 disabled:opacity-50"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1">
                  Manual 5-Character Code Override <span className="text-[10px] text-slate-500">(optional fallback)</span>
                </label>
                <input
                  type="text"
                  maxLength={5}
                  value={manualCodeInput}
                  onChange={(e) => setManualCodeInput(e.target.value.toUpperCase())}
                  placeholder="e.g. 5G3K9 (if already retrieved)"
                  disabled={isChangingEmail}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white font-mono tracking-widest uppercase focus:outline-none focus:border-indigo-500 disabled:opacity-50"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setEmailChangeAccount(null)}
                  disabled={isChangingEmail}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition cursor-pointer disabled:opacity-40"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isChangingEmail || !targetEmailInput}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white font-semibold shadow-lg shadow-indigo-600/25 transition cursor-pointer disabled:opacity-50"
                >
                  {isChangingEmail ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      Executing Email Change Pipeline...
                    </>
                  ) : (
                    <>
                      <ArrowRight className="w-3.5 h-3.5" />
                      Change Email to Target
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
