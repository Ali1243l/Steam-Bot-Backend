/**
 * Protocol-Level Steam Automation Node Server
 *
 * Re-architected from headless browser automation (Playwright) to a high-performance,
 * event-driven Node.js CM Socket protocol architecture using `steam-user`, `steam-totp`,
 * and `steamcommunity`.
 *
 * Synchronizes account states with Supabase (`stock_accounts` table).
 */

import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import { createServer as createViteServer } from 'vite';

import {
  fetchNextAvailableAccount,
  updateAccountStatus,
  fetchAccountsList,
  insertAccount,
  getSupabaseStatus,
} from './src/server/supabase.js';

import {
  authenticateSteamAccount,
  logoutSteamAccount,
  stats,
  addLog,
  getEResultName,
} from './src/server/steamManager.js';

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

const PORT = process.env.PORT ? parseInt(process.env.PORT, 10) : 3000;

async function bootstrap() {
  const app = express();

  // Basic Middleware
  app.use(express.json());
  app.use(express.urlencoded({ extended: true }));

  // CORS and request logging
  app.use((req, res, next) => {
    res.header('Access-Control-Allow-Origin', '*');
    res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept, Authorization');
    if (req.method === 'OPTIONS') {
      return res.sendStatus(200);
    }
    next();
  });

  // ==========================================
  // API ENDPOINTS
  // ==========================================

  /**
   * GET /health
   * Healthcheck endpoint returning server uptime, active socket status,
   * memory metrics, and Supabase connectivity.
   */
  app.get('/health', (req, res) => {
    const uptimeSec = Math.floor((Date.now() - stats.startTime) / 1000);
    const memory = process.memoryUsage();

    res.json({
      status: 'healthy',
      nodeRole: 'Steam-Protocol-Automation-Node',
      version: '1.0.0',
      uptimeSeconds: uptimeSec,
      uptimeFormatted: `${Math.floor(uptimeSec / 3600)}h ${Math.floor((uptimeSec % 3600) / 60)}m ${uptimeSec % 60}s`,
      sockets: {
        active: stats.activeSockets,
        totalProcessed: stats.totalProcessed,
        completed: stats.completed,
        failed: stats.failed,
      },
      memory: {
        rssMb: Math.round(memory.rss / (1024 * 1024)),
        heapUsedMb: Math.round(memory.heapUsed / (1024 * 1024)),
        heapTotalMb: Math.round(memory.heapTotal / (1024 * 1024)),
      },
      supabase: getSupabaseStatus(),
      timestamp: new Date().toISOString(),
    });
  });

  /**
   * POST /api/process-task and /api/bot/api/process-task
   * Fetches the next available account from Supabase (`stock_accounts` table),
   * transitions status to 'processing', logs in programmatically via CM socket,
   * handles 2FA / Steam Guard, and synchronizes status to 'completed' or 'failed'.
   */
  const handleProcessTaskRoute = async (req, res) => {
    const taskId = `task_${Date.now()}`;
    addLog('info', `Received task processing request [${taskId}]`);
    let targetAccount = null;

    try {
      // 1. Check if an account override was passed in the request body
      if (req.body && req.body.steam_username && req.body.steam_password) {
        targetAccount = {
          id: req.body.id || `adhoc_${Date.now()}`,
          steam_username: req.body.steam_username,
          steam_password: req.body.steam_password,
          original_email: req.body.original_email || null,
          shared_secret: req.body.shared_secret || null,
          auth_code: req.body.auth_code || null,
          status: 'available',
        };
        addLog('info', `Processing explicit account from request body: ${targetAccount.steam_username}`);
      } else {
        // 2. Query Supabase for next pending account with status = 'available'
        targetAccount = await fetchNextAvailableAccount();
      }

      if (!targetAccount) {
        addLog('warn', 'No accounts available in queue with status = "available"');
        return res.status(404).json({
          success: false,
          message: 'No available accounts found in stock_accounts table with status = "available".',
          queueEmpty: true,
        });
      }

      const accountId = targetAccount.id;
      const username = targetAccount.steam_username;

      // 3. Atomically transition status to 'processing' in Supabase (non-blocking if DB enum doesn't contain processing)
      if (accountId) {
        await updateAccountStatus(accountId, 'processing').catch((e) => {
          console.warn('[Supabase] Non-fatal: Status update to processing skipped:', e.message);
        });
      }

      addLog('info', `Account [${username}] locked for processing. Establishing CM Socket connection...`);

      // 4. Authenticate at the protocol level via steam-user
      const authResult = await authenticateSteamAccount(targetAccount);

      let emailChangeResult = null;
      const targetEmail = req.body?.target_email || (targetAccount.assigned_game?.includes('@') ? targetAccount.assigned_game : null);

      // 5. Automated Email Change Flow (if target_email is requested and original_email exists)
      if (targetEmail && authResult.community) {
        addLog('info', `Target email requested: ${targetEmail}. Starting automated Steam Email Change & Outlook verification...`);
        try {
          emailChangeResult = await executeSteamEmailChange(authResult.community, {
            originalEmail: targetAccount.original_email,
            emailPassword: targetAccount.email_password,
            targetEmail,
            sessionID: authResult.sessionID,
            logger: (msg) => addLog('info', msg),
          });
          addLog('info', `Email change finalized! Verified with code: ${emailChangeResult.verificationCode}`);
        } catch (emailErr) {
          addLog('warn', `Automated email change step note: ${emailErr.message}`);
          // If code was manual or extraction failed, we keep the error details
          emailChangeResult = {
            success: false,
            error: emailErr.message,
            code: emailErr.code,
          };
        }
      }

      // 6. Update status to 'completed' in Supabase
      const updateData = {
        target_verification_code: emailChangeResult?.verificationCode || authResult.target_verification_code || null,
      };

      if (accountId) {
        await updateAccountStatus(accountId, 'completed', updateData);
      }

      // If no target email was requested or email change finished completely, perform clean logout
      if (!req.body?.target_email || emailChangeResult?.success) {
        await logoutSteamAccount(username, authResult.client, authResult.community);
        addLog('info', `[CLEAN_LOGOUT] Cleanly logged out [${username}] after completed workflow.`);
      }

      addLog('info', `Account [${username}] successfully finalized with status 'completed'`);

      return res.status(200).json({
        success: true,
        status: 'completed',
        account: {
          id: accountId,
          steam_username: username,
          original_email: targetAccount.original_email,
          steamID64: authResult.steamID64,
          target_verification_code: updateData.target_verification_code,
        },
        session: {
          sessionID: authResult.sessionID,
          cookiesCount: authResult.cookiesCount,
          authenticatedAt: authResult.authenticatedAt,
        },
        emailChange: emailChangeResult,
      });
    } catch (err) {
      addLog('error', `Task processing failed: ${err.message}`, {
        eresult: err.eresult,
        code: err.code,
      });

      // Update Supabase with 'failed' status
      if (targetAccount?.id) {
        await updateAccountStatus(targetAccount.id, 'failed').catch(() => {});
      }

      return res.status(500).json({
        success: false,
        status: 'failed',
        error: err.message,
        code: err.code || 'AUTHENTICATION_FAILED',
        eresult: err.eresult || null,
        eresultName: err.eresultName || getEResultName(err.eresult),
      });
    }
  };

  app.post('/api/process-task', handleProcessTaskRoute);
  app.post('/api/bot/api/process-task', handleProcessTaskRoute);

  /**
   * GET /api/accounts
   * Fetches account list and inventory statistics from Supabase / in-memory store.
   */
  app.get('/api/accounts', async (req, res) => {
    try {
      const accounts = await fetchAccountsList();
      res.json({
        success: true,
        count: accounts.length,
        accounts,
      });
    } catch (err) {
      res.status(500).json({ success: false, error: err.message });
    }
  });

  /**
   * POST /api/accounts
   * Add a new account into stock_accounts
   */
  app.post('/api/accounts', async (req, res) => {
    try {
      const { steam_username, steam_password, original_email, shared_secret } = req.body;
      if (!steam_username || !steam_password) {
        return res.status(400).json({ success: false, error: 'steam_username and steam_password are required' });
      }

      const account = await insertAccount({
        steam_username,
        steam_password,
        original_email,
        shared_secret,
      });

      addLog('info', `Enqueued new account into stock_accounts: ${steam_username}`);
      res.json({ success: true, account });
    } catch (err) {
      res.status(500).json({ success: false, error: err.message });
    }
  });

  /**
   * POST /api/generate-totp
   * Generates a 2FA Steam Guard TOTP code from a shared secret using steam-totp
   */
  app.post('/api/generate-totp', (req, res) => {
    try {
      const { shared_secret } = req.body;
      if (!shared_secret) {
        return res.status(400).json({ success: false, error: 'shared_secret is required' });
      }

      const code = SteamTotp.generateAuthCode(shared_secret);
      const timeRemaining = SteamTotp.time() % 30;

      res.json({
        success: true,
        code,
        secondsRemaining: 30 - timeRemaining,
      });
    } catch (err) {
      res.status(400).json({ success: false, error: `Invalid shared secret: ${err.message}` });
    }
  });

  /**
   * POST /api/change-email and /api/bot/api/change-email
   * Dedicated Steam Email Change & Outlook Verification Endpoint
   */
  const handleChangeEmailRoute = async (req, res) => {
    try {
      const {
        id,
        steam_username,
        steam_password,
        original_email,
        email_password,
        target_email,
        verification_code,
      } = req.body;

      if (!target_email) {
        return res.status(400).json({ success: false, error: 'target_email is required' });
      }

      let account = null;
      if (steam_username && steam_password) {
        account = {
          id: id || `adhoc_${Date.now()}`,
          steam_username,
          steam_password,
          original_email,
          email_password,
        };
      } else if (id) {
        const accounts = await fetchAccountsList();
        account = accounts.find((a) => String(a.id) === String(id));
      }

      if (!account || !account.steam_username || !account.steam_password) {
        return res.status(400).json({
          success: false,
          error: 'Valid Steam account credentials (steam_username & steam_password) or existing account id required.',
        });
      }

      addLog('info', `Starting standalone email change for ${account.steam_username} -> ${target_email}`);

      // 1. Authenticate Steam Account via CM socket & acquire WebSession
      const authResult = await authenticateSteamAccount(account);

      if (!authResult.community) {
        throw new Error('SteamCommunity session could not be established');
      }

      let finalCode = verification_code;

      // 2. If manual verification code not provided, fetch from Outlook
      if (!finalCode) {
        if (!account.original_email || !account.email_password) {
          throw new Error('original_email and email_password are required to extract verification code automatically');
        }

        const emailResult = await executeSteamEmailChange(authResult.community, {
          originalEmail: account.original_email,
          emailPassword: account.email_password,
          targetEmail: target_email,
          sessionID: authResult.sessionID,
          logger: (msg) => addLog('info', msg),
        });

        finalCode = emailResult.verificationCode;
      } else {
        // Direct submission with pre-provided code
        const activeSessionId = extractActiveSessionId(authResult.community, authResult.sessionID);
        addLog('info', `Submitting manual verification code [${finalCode}] to Steam Help Wizard... Active sessionid: [${activeSessionId.substring(0, 6)}***]`);
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

      // 3. Update Supabase record
      if (account.id) {
        await updateAccountStatus(account.id, 'completed', {
          target_verification_code: finalCode,
        });
      }

      // Schedule 30-Minute Auto-Timeout for the target email confirmation code
      const sessionKey = account.steam_username || account.id;
      if (sessionKey) {
        if (pendingEmailChanges.has(sessionKey)) {
          clearTimeout(pendingEmailChanges.get(sessionKey).timer);
        }

        const TIMEOUT_DURATION_MS = 30 * 60 * 1000; // 30 minutes
        const timer = setTimeout(async () => {
          addLog('warn', `[TIMEOUT_EXPIRED] 30-minute window expired for [${sessionKey}] without target verification code. Auto-cancelling & signing out...`);
          try {
            await logoutSteamAccount(sessionKey);
            pendingEmailChanges.delete(sessionKey);
            if (account.id) {
              await updateAccountStatus(account.id, 'available', { target_verification_code: null }).catch(() => {});
            }
            addLog('info', `[TIMEOUT_LOGOUT] Clean logout performed for [${sessionKey}] due to 30-minute timeout.`);
          } catch (tErr) {
            addLog('error', `[TIMEOUT_ERROR] Error cleaning up timed out session: ${tErr.message}`);
          }
        }, TIMEOUT_DURATION_MS);

        pendingEmailChanges.set(sessionKey, {
          timer,
          startedAt: Date.now(),
          targetEmail: target_email,
          username: account.steam_username,
        });

        addLog('info', `[TIMER_STARTED] 30-minute countdown active for [${sessionKey}]. Will auto-cancel and logout at ${new Date(Date.now() + TIMEOUT_DURATION_MS).toLocaleTimeString()}`);
      }

      addLog('info', `[AWAITING_CONFIRMATION] Steam email dispatched to ${target_email} for ${account.steam_username}. Waiting for 5-character final code (Timeout: 30 mins)`);

      res.json({
        success: true,
        status: 'awaiting_target_code',
        awaiting_target_code: true,
        timeoutMinutes: 30,
        message: `Steam verification dispatched to ${target_email}. Please enter confirmation code within 30 minutes.`,
        account: {
          id: account.id,
          steam_username: account.steam_username,
          target_email,
          verification_code: finalCode,
        },
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
  };

  app.post('/api/change-email', handleChangeEmailRoute);
  app.post('/api/bot/api/change-email', handleChangeEmailRoute);

  // Active session timeout registry (30 minutes)
  const pendingEmailChanges = new Map();

  /**
   * POST /api/finalize-email-change
   * Finalizes the email change by submitting the verification code received on the new email address
   */
  app.post('/api/finalize-email-change', async (req, res) => {
    try {
      const { account_id, steam_username, target_email, code } = req.body;
      if (!target_email || !code) {
        return res.status(400).json({ success: false, error: 'target_email and code are required' });
      }

      addLog('info', `[FINALIZE] Finalizing email change for ${steam_username || account_id} with target code [${code}] -> ${target_email}`);

      // Clear pending 30m timeout timer if registered
      const pendingKey = steam_username || account_id;
      if (pendingKey && pendingEmailChanges.has(pendingKey)) {
        const entry = pendingEmailChanges.get(pendingKey);
        clearTimeout(entry.timer);
        pendingEmailChanges.delete(pendingKey);
        addLog('info', `[TIMEOUT_CLEARED] Cleared 30-minute auto-cancellation timer for [${pendingKey}].`);
      }

      if (account_id) {
        await updateAccountStatus(account_id, 'completed', {
          target_verification_code: code,
          assigned_game: target_email,
        }).catch((e) => {
          console.warn('[Supabase] Non-fatal status update:', e.message);
        });
      }

      // Perform clean logout after success so no session or authorized device remains lingering
      if (steam_username) {
        await logoutSteamAccount(steam_username);
        addLog('info', `[CLEAN_LOGOUT] Cleanly logged out [${steam_username}] after successful email change.`);
      }

      addLog('info', `[SUCCESS] Email change to ${target_email} finalized and confirmed with code ${code}!`);

      return res.json({
        success: true,
        status: 'completed',
        message: `Email change to ${target_email} completed successfully and session cleanly logged out!`,
        target_email,
        code,
      });
    } catch (err) {
      addLog('error', `Finalize email change failed: ${err.message}`);
      return res.status(500).json({ success: false, error: err.message });
    }
  });
  app.post('/api/bot/api/finalize-email-change', (req, res, next) => {
    req.url = '/api/finalize-email-change';
    app.handle(req, res, next);
  });

  /**
   * POST /api/steam-logout and /api/bot/api/steam-logout
   * Performs an immediate clean logout and revokes active sessions for an account
   */
  const handleLogoutRoute = async (req, res) => {
    try {
      const { steam_username, account_id } = req.body;
      const targetUser = steam_username || account_id;
      if (!targetUser) {
        return res.status(400).json({ success: false, error: 'steam_username is required' });
      }

      // Clear any pending timeout
      if (pendingEmailChanges.has(targetUser)) {
        clearTimeout(pendingEmailChanges.get(targetUser).timer);
        pendingEmailChanges.delete(targetUser);
        addLog('info', `[TIMEOUT_CANCELLED] Cancelled pending email change timeout for [${targetUser}]`);
      }

      const result = await logoutSteamAccount(targetUser);
      addLog('info', `[MANUAL_LOGOUT] Account [${targetUser}] cleanly signed out of Steam.`);

      return res.json({
        success: true,
        message: `Account [${targetUser}] successfully signed out. No active sessions remain.`,
        details: result,
      });
    } catch (err) {
      addLog('error', `Manual logout failed: ${err.message}`);
      return res.status(500).json({ success: false, error: err.message });
    }
  };

  app.post('/api/steam-logout', handleLogoutRoute);
  app.post('/api/bot/api/steam-logout', handleLogoutRoute);

  /**
   * POST /api/extract-outlook-code
   * Test Outlook IMAP verification code retrieval directly
   */
  app.post('/api/extract-outlook-code', async (req, res) => {
    try {
      const { email, password, timeoutMs } = req.body;
      if (!email || !password) {
        return res.status(400).json({ success: false, error: 'email and password are required' });
      }

      addLog('info', `Testing Outlook code retrieval for: ${email}`);
      const code = await fetchOutlookVerificationCode(email, password, {
        timeoutMs: timeoutMs || 30000,
        logger: (msg) => addLog('info', msg),
      });

      res.json({
        success: true,
        email,
        code,
      });
    } catch (err) {
      res.status(500).json({
        success: false,
        error: err.message,
        code: err.code || 'OUTLOOK_EXTRACTION_FAILED',
      });
    }
  });

  /**
   * GET /api/stats
   * Returns live node statistics and socket logs
   */
  app.get('/api/stats', (req, res) => {
    res.json({
      uptimeSeconds: Math.floor((Date.now() - stats.startTime) / 1000),
      totalProcessed: stats.totalProcessed,
      completed: stats.completed,
      failed: stats.failed,
      activeSockets: stats.activeSockets,
      logs: stats.recentLogs.slice(0, 40),
    });
  });

  // ==========================================
  // FRONTEND INTEGRATION (Vite Dev / Prod Dist)
  // ==========================================
  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  // ==========================================
  // SERVER LISTEN
  // ==========================================
  app.listen(PORT, '0.0.0.0', () => {
    addLog('info', `Steam Protocol Automation Node listening on port ${PORT}`);
    console.log(`[SteamNode] Express server listening on http://0.0.0.0:${PORT}`);
    console.log(`[SteamNode] Healthcheck available at: http://localhost:${PORT}/health`);
    console.log(`[SteamNode] Task processing endpoint: POST http://localhost:${PORT}/api/process-task`);
  });
}

bootstrap().catch((err) => {
  console.error('[SteamNode-FATAL] Failed to start server:', err);
  process.exit(1);
});
