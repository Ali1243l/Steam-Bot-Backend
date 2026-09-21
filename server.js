/**
 * Steam Protocol Automation Node Server
 *
 * Direct Socket/Web Protocol Worker:
 * - CM Socket Authentication via node-steam-user (Protocol-Level TCP/WebSocket)
 * - Steam Community WebSession extraction
 * - Supabase Queue consumer & state sync
 * - Automated Steam Email Change Workflow (Help Wizard AJAX + Outlook IMAP)
 */

import express from 'express';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import {
  authenticateSteamAccount,
  authenticateAndExtractSession,
  activeConnections,
  sessionCache,
  stats,
  addLog,
  getEResultName,
} from './src/server/steamManager.js';
import {
  isConfigured as isSupabaseConfigured,
  fetchAvailableAccounts,
  updateAccountStatus,
  loadInitialAccounts,
  getSupabaseClient,
} from './src/server/supabase.js';
import {
  executeSteamEmailChange,
  fetchOutlookVerificationCode,
  parseSteamVerificationCode,
  extractActiveSessionId,
  triggerSteamChangeEmailVerification,
} from './src/server/emailManager.js';

import SteamTotp from 'steam-totp';

dotenv.config();

// Global process error handlers to prevent socket resets from crashing the Node.js daemon
process.on('uncaughtException', (err) => {
  console.error('[SteamNode-CRITICAL] Uncaught exception handled:', err.message);
});

process.on('unhandledRejection', (reason) => {
  console.error('[SteamNode-CRITICAL] Unhandled promise rejection handled:', reason);
});

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 8000;

// Built-in Native CORS (No extra packages needed)
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept, Authorization');
  if (req.method === 'OPTIONS') {
    return res.sendStatus(200);
  }
  next();
});

app.use(express.json());

// In-memory live logs ring buffer
const liveLogs = [];
const MAX_LOGS = 100;

function appendLog(type, message, extra = null) {
  const timestamp = new Date().toISOString();
  const entry = {
    id: `${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
    timestamp,
    type,
    message,
    extra,
  };
  liveLogs.unshift(entry);
  if (liveLogs.length > MAX_LOGS) {
    liveLogs.pop();
  }
  const prefix = `[SteamNode-${type.toUpperCase()}]`;
  if (type === 'error') {
    console.error(prefix, message, extra || '');
  } else {
    console.log(prefix, message, extra || '');
  }
}

// Performance metrics tracker
const metrics = {
  totalProcessed: 0,
  completed: 0,
  failed: 0,
  startedAt: Date.now(),
};

// ==========================================
// 1. Healthcheck & Metrics Endpoint
// ==========================================
app.get('/health', async (req, res) => {
  const uptimeSeconds = Math.floor((Date.now() - metrics.startedAt) / 1000);
  const hours = Math.floor(uptimeSeconds / 3600);
  const minutes = Math.floor((uptimeSeconds % 3600) / 60);
  const seconds = uptimeSeconds % 60;
  const uptimeFormatted = `${hours}h ${minutes}m ${seconds}s`;

  let totalLoadedAccounts = 0;
  try {
    const accs = await fetchAvailableAccounts();
    totalLoadedAccounts = accs.length;
  } catch (e) {
    totalLoadedAccounts = 0;
  }

  res.json({
    status: 'healthy',
    nodeRole: 'Steam-Protocol-Automation-Node',
    version: '1.0.0',
    uptimeSeconds,
    uptimeFormatted,
    sockets: {
      active: activeConnections ? activeConnections.size : 0,
      totalProcessed: metrics.totalProcessed,
      completed: metrics.completed,
      failed: metrics.failed,
    },
    memory: {
      rssMb: Math.round(process.memoryUsage().rss / 1024 / 1024),
      heapUsedMb: Math.round(process.memoryUsage().heapUsed / 1024 / 1024),
      heapTotalMb: Math.round(process.memoryUsage().heapTotal / 1024 / 1024),
    },
    supabase: {
      configured: isSupabaseConfigured,
      provider: 'Supabase Cloud (PostgreSQL)',
      url: process.env.SUPABASE_URL ? 'https://***.supabase.co' : 'Not configured',
      totalLoadedAccounts,
    },
    timestamp: new Date().toISOString(),
  });
});

// ==========================================
// 2. Fetch Live Logs Endpoint
// ==========================================
app.get('/api/logs', (req, res) => {
  res.json({
    success: true,
    logs: liveLogs,
  });
});

// ==========================================
// 3. Supabase Stock Queue Endpoint
// ==========================================
app.get('/api/accounts', async (req, res) => {
  try {
    const accounts = await fetchAvailableAccounts();
    res.json({
      success: true,
      count: accounts.length,
      accounts: accounts.map((acc) => ({
        id: acc.id,
        steam_username: acc.steam_username,
        original_email: acc.original_email,
        status: acc.status,
        target_verification_code: acc.target_verification_code,
        assigned_game: acc.assigned_game,
        hasSharedSecret: Boolean(acc.shared_secret),
        updated_at: acc.updated_at,
      })),
    });
  } catch (err) {
    res.status(500).json({
      success: false,
      error: err.message,
    });
  }
});

// ==========================================
// 4. Task Processing Worker Endpoint
// ==========================================
app.post('/api/process-task', async (req, res) => {
  const taskId = `task-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`;
  metrics.totalProcessed++;
  appendLog('info', `Received task dispatch [${taskId}]`);

  let targetAccount = null;

  try {
    const available = await fetchAvailableAccounts();
    targetAccount = available.find((a) => a.status === 'available');

    if (!targetAccount) {
      appendLog('warn', `Task [${taskId}] aborted: No 'available' accounts in Supabase stock_accounts`);
      return res.status(404).json({
        success: false,
        message: 'No available accounts found in Supabase queue',
      });
    }

    appendLog('info', `Selected account [${targetAccount.steam_username}] (ID: ${targetAccount.id}) for socket execution`);

    // Authenticate CM Socket
    const authResult = await authenticateSteamAccount({
      steam_username: targetAccount.steam_username,
      steam_password: targetAccount.steam_password,
      shared_secret: targetAccount.shared_secret,
      original_email: targetAccount.original_email,
    });

    metrics.completed++;
    appendLog('info', `Socket task [${taskId}] successfully completed for ${targetAccount.steam_username}`);

    res.json({
      success: true,
      taskId,
      account: targetAccount.steam_username,
      steamID64: authResult.steamID64,
      cookieCount: authResult.cookies ? authResult.cookies.length : 0,
      sessionID: authResult.sessionID,
      message: 'Account successfully authenticated via CM Sockets and cookies stored',
    });
  } catch (err) {
    metrics.failed++;
    appendLog('error', `Task [${taskId}] failed: ${err.message}`);

    if (targetAccount?.id) {
      try {
        await updateAccountStatus(targetAccount.id, 'failed');
      } catch (dbErr) {
        appendLog('error', `Failed to mark account failed in Supabase: ${dbErr.message}`);
      }
    }

    res.status(500).json({
      success: false,
      taskId,
      error: err.message,
      code: err.eresult ? `EResult_${err.eresult}` : 'CM_SOCKET_EXECUTION_FAILED',
    });
  }
});

// ==========================================
// 5. Standalone Email Change Endpoint
// ==========================================
app.post('/api/change-email', async (req, res) => {
  const {
    account_id,
    steam_username,
    target_email,
    manual_code,
    email_password,
  } = req.body;

  if (!target_email) {
    return res.status(400).json({
      success: false,
      error: 'target_email is required',
    });
  }

  appendLog('info', `Starting standalone email change for ${steam_username || account_id} -> ${target_email}`);

  try {
    let account = null;
    if (account_id) {
      const allAccs = await fetchAvailableAccounts();
      account = allAccs.find((a) => a.id === account_id);
    }

    if (!account && steam_username) {
      const allAccs = await fetchAvailableAccounts();
      account = allAccs.find((a) => a.steam_username === steam_username);
    }

    if (!account) {
      return res.status(404).json({
        success: false,
        error: 'Account not found in stock_accounts',
      });
    }

    // Step 1: Connect CM Socket and acquire web session
    const authResult = await authenticateSteamAccount({
      steam_username: account.steam_username,
      steam_password: account.steam_password,
      shared_secret: account.shared_secret,
      original_email: account.original_email,
    });

    let finalCode = manual_code;

    // Step 2: Extract code if not provided manually
    if (!finalCode) {
      const effectiveEmailPass = email_password || account.email_password;
      if (!effectiveEmailPass) {
        return res.status(400).json({
          success: false,
          error: 'email_password is required for automated Outlook code extraction or provide manual_code',
        });
      }

      const emailResult = await executeSteamEmailChange(authResult.community, {
        originalEmail: account.original_email,
        emailPassword: effectiveEmailPass,
        targetEmail: target_email,
        sessionID: authResult.sessionID,
        logger: (msg) => appendLog('info', msg),
      });

      finalCode = emailResult.verificationCode;
    } else {
      // Direct submission with pre-provided code
      const activeSessionId = extractActiveSessionId(authResult.community, authResult.sessionID);
      appendLog('info', `Submitting manual verification code [${finalCode}] to Steam Help Wizard... Active sessionid: [${activeSessionId ? activeSessionId.substring(0, 6) + '***' : 'empty'}]`);

      await new Promise((resolve, reject) => {
        authResult.community.httpRequestPost(
          {
            uri: 'https://help.steampowered.com/en/wizard/AjaxChangeEmail',
            form: {
              sessionid: activeSessionId,
              wizard_ajax: 1,
              email: target_email,
              code: finalCode,
            },
            headers: {
              Referer: 'https://help.steampowered.com/en/wizard/HelpWithLoginInfo?issueid=406',
              Origin: 'https://help.steampowered.com',
              'X-Requested-With': 'XMLHttpRequest',
            },
            json: true,
          },
          (err, response, body) => {
            if (err) return reject(err);
            appendLog('info', `Steam Help Wizard AjaxChangeEmail exact response:`, JSON.stringify(body));
            if (body && (body.success === 1 || body.success === true || body.result === 1)) {
              resolve(body);
            } else {
              reject(new Error(body?.error || body?.msg || JSON.stringify(body)));
            }
          }
        );
      });
    }

    // Step 3: Update Supabase
    await updateAccountStatus(account.id, 'completed', {
      original_email: target_email,
      target_verification_code: finalCode,
    });

    appendLog('info', `Email for ${account.steam_username} successfully changed to ${target_email}`);

    res.json({
      success: true,
      account: account.steam_username,
      newEmail: target_email,
      verificationCode: finalCode,
      message: 'Steam email successfully updated and recorded in database',
    });
  } catch (err) {
    const isImapRestricted =
      err.code === 'EMAIL_CODE_EXTRACTION_FAILED' ||
      err.message?.includes('disabled') ||
      err.message?.includes('AUTHENTICATE') ||
      err.message?.includes('ECONNRESET');

    if (isImapRestricted) {
      appendLog('warn', 'Outlook IMAP Basic Auth restricted by Microsoft. Steam code dispatched to inbox.');
      return res.status(200).json({
        success: false,
        requiresManualCode: true,
        code: 'OUTLOOK_AUTH_RESTRICTED',
        account: steam_username || account_id,
        targetEmail: target_email,
        message: 'Steam verification code sent to your Outlook inbox. Enter the 5-character code to finish.',
      });
    }

    appendLog('error', `Email change failed: ${err.message}`);

    res.status(500).json({
      success: false,
      error: err.message,
      code: err.code || 'EMAIL_CHANGE_FAILED',
      requiresManualCode: false,
    });
  }
});

// Fallback HTML Status for root requests (safe if dist does not exist)
app.get('/', (req, res) => {
  const distIndex = path.join(process.cwd(), 'dist', 'index.html');
  if (fs.existsSync(distIndex)) {
    return res.sendFile(distIndex);
  }
  res.send(`
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>Steam Protocol Automation Node</title>
      <style>
        body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; padding: 40px; text-align: center; }
        .card { background: #1e293b; max-width: 500px; margin: 0 auto; padding: 30px; border-radius: 12px; border: 1px solid #334155; }
        .status { color: #10b981; font-weight: bold; font-size: 20px; margin-bottom: 15px; }
        a { color: #38bdf8; text-decoration: none; font-weight: 500; }
      </style>
    </head>
    <body>
      <div class="card">
        <div class="status">● Steam Automation Node is Active</div>
        <p>Port: ${PORT} | Role: Protocol Socket Worker</p>
        <p><a href="/health">View /health JSON Metrics</a></p>
        <p><a href="/api/accounts">View /api/accounts Queue</a></p>
      </div>
    </body>
    </html>
  `);
});

// Serve dist static files if present
const distPath = path.join(process.cwd(), 'dist');
if (fs.existsSync(distPath)) {
  app.use(express.static(distPath));
  app.get('*', (req, res) => {
    res.sendFile(path.join(distPath, 'index.html'));
  });
}

// Start Server
app.listen(PORT, '0.0.0.0', async () => {
  appendLog('info', `Steam Protocol Automation Node listening on port ${PORT}`);
  appendLog('info', `Healthcheck available at: http://localhost:${PORT}/health`);
  appendLog('info', `Task processing endpoint: POST http://localhost:${PORT}/api/process-task`);

  // Pre-seed Supabase accounts
  try {
    await loadInitialAccounts();
  } catch (e) {
    appendLog('error', `Failed initial account load: ${e.message}`);
  }
});
