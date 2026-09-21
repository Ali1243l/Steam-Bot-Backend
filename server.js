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
  stats,
  addLog,
  getEResultName,
} from './src/server/steamManager.js';

import SteamTotp from 'steam-totp';

dotenv.config();

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
   * POST /api/process-task
   * Fetches the next available account from Supabase (`stock_accounts` table),
   * transitions status to 'processing', logs in programmatically via CM socket,
   * handles 2FA / Steam Guard, and synchronizes status to 'completed' or 'failed'.
   */
  app.post('/api/process-task', async (req, res) => {
    const taskId = `task_${Date.now()}`;
    addLog('info', `Received task processing request [${taskId}]`);

    try {
      let targetAccount = null;

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

      // 3. Atomically transition status to 'processing' in Supabase
      if (accountId) {
        await updateAccountStatus(accountId, 'processing');
      }

      addLog('info', `Account [${username}] locked for processing. Establishing CM Socket connection...`);

      // 4. Authenticate at the protocol level via steam-user
      const authResult = await authenticateSteamAccount(targetAccount);

      // 5. Update status to 'completed' in Supabase
      const updateData = {
        target_verification_code: authResult.target_verification_code || null,
      };

      if (accountId) {
        await updateAccountStatus(accountId, 'completed', updateData);
      }

      addLog('info', `Account [${username}] authentication successfully finalized with status 'completed'`);

      return res.status(200).json({
        success: true,
        status: 'completed',
        account: {
          id: accountId,
          steam_username: username,
          original_email: targetAccount.original_email,
          steamID64: authResult.steamID64,
          target_verification_code: authResult.target_verification_code,
        },
        session: {
          sessionID: authResult.sessionID,
          cookiesCount: authResult.cookiesCount,
          authenticatedAt: authResult.authenticatedAt,
        },
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
  });

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
