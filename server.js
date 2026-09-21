/**
 * Steam Protocol Automation Node (Production Server)
 *
 * Direct Socket/Web Protocol Worker:
 * - CM Socket Authentication via node-steam-user (Protocol-Level TCP/WebSocket)
 * - Steam Community WebSession extraction
 * - Supabase Queue consumer & state sync
 * - Automated Steam Email Change Workflow (Help Wizard AJAX + Outlook IMAP)
 */

import express from 'express';
import cors from 'cors';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import {
  authenticateAndExtractSession,
  activeConnections,
  sessionCache,
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

app.use(cors({ origin: true, credentials: true }));
app.use(express.json());

// In-memory live logs ring buffer
const liveLogs = [];
const MAX_LOGS = 100;

function addLog(type, message, extra = null) {
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
  activeSockets: 0,
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
      active: activeConnections.size,
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
  addLog('info', `Received task dispatch [${taskId}]`);

  let targetAccount = null;

  try {
    const available = await fetchAvailableAccounts();
    targetAccount = available.find((a) => a.status === 'available');

    if (!targetAccount) {
      addLog('warn', `Task [${taskId}] aborted: No 'available' accounts in Supabase stock_accounts`);
      return res.status(404).json({
        success: false,
        message: 'No available accounts found in Supabase queue',
      });
    }

    addLog('info', `Selected account [${targetAccount.steam_username}] (ID: ${targetAccount.id}) for socket execution`);

    // Authenticate CM Socket
    const authResult = await authenticateAndExtractSession(
      {
        username: targetAccount.steam_username,
        password: targetAccount.steam_password,
        sharedSecret: targetAccount.shared_secret,
        proxy: targetAccount.proxy || process.env.STEAM_PROXY,
      },
      (msg) => addLog('info', msg)
    );

    metrics.completed++;
    addLog('info', `Socket task [${taskId}] successfully completed for ${targetAccount.steam_username}`);

    res.json({
      success: true,
      taskId,
      account: targetAccount.steam_username,
      steamID64: authResult.steamID64,
      cookieCount: authResult.cookies.length,
      sessionID: authResult.sessionID,
      message: 'Account successfully authenticated via CM Sockets and cookies stored',
    });
  } catch (err) {
    metrics.failed++;
    addLog('error', `Task [${taskId}] failed: ${err.message}`);

    if (targetAccount?.id) {
      try {
        await updateAccountStatus(targetAccount.id, 'failed');
      } catch (dbErr) {
        addLog('error', `Failed to mark account failed in Supabase: ${dbErr.message}`);
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

  addLog('info', `Starting standalone email change for ${steam_username || account_id} -> ${target_email}`);

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
    const authResult = await authenticateAndExtractSession(
      {
        username: account.steam_username,
        password: account.steam_password,
        sharedSecret: account.shared_secret,
        proxy: account.proxy || process.env.STEAM_PROXY,
      },
      (msg) => addLog('info', msg)
    );

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
        logger: (msg) => addLog('info', msg),
      });

      finalCode = emailResult.verificationCode;
    } else {
      // Direct submission with pre-provided code
      const activeSessionId = extractActiveSessionId(authResult.community, authResult.sessionID);
      addLog('info', `Submitting manual verification code [${finalCode}] to Steam Help Wizard... Active sessionid: [${activeSessionId ? activeSessionId.substring(0, 6) + '***' : 'empty'}]`);
      
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
            addLog('info', `Steam Help Wizard AjaxChangeEmail exact response:`, JSON.stringify(body));
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

    addLog('info', `Email for ${account.steam_username} successfully changed to ${target_email}`);

    res.json({
      success: true,
      account: account.steam_username,
      newEmail: target_email,
      verificationCode: finalCode,
      message: 'Steam email successfully updated and recorded in database',
    });
  } catch (err) {
    addLog('error', `Email change failed: ${err.message}`);
    const isImapRestricted =
      err.code === 'EMAIL_CODE_EXTRACTION_FAILED' ||
      err.message?.includes('disabled') ||
      err.message?.includes('AUTHENTICATE') ||
      err.message?.includes('ECONNRESET');

    res.status(500).json({
      success: false,
      error: err.message,
      code: err.code || (isImapRestricted ? 'OUTLOOK_AUTH_RESTRICTED' : 'EMAIL_CHANGE_FAILED'),
      requiresManualCode: isImapRestricted,
      message: isImapRestricted
        ? 'Steam has triggered the verification email to your inbox! Microsoft restricts automated IMAP login on this Outlook account. Please check your Outlook inbox directly, enter the 5-character code in the box below, and click Change Email.'
        : err.message,
    });
  }
});

// Serve frontend assets in production
const distPath = path.join(process.cwd(), 'dist');
app.use(express.static(distPath));

app.get('*', (req, res) => {
  res.sendFile(path.join(distPath, 'index.html'));
});

// Start Server
app.listen(PORT, '0.0.0.0', async () => {
  addLog('info', `Steam Protocol Automation Node listening on port ${PORT}`);
  addLog('info', `Healthcheck available at: http://localhost:${PORT}/health`);
  addLog('info', `Task processing endpoint: POST http://localhost:${PORT}/api/process-task`);

  // Pre-seed Supabase accounts
  try {
    await loadInitialAccounts();
  } catch (e) {
    addLog('error', `Failed initial account load: ${e.message}`);
  }
});
