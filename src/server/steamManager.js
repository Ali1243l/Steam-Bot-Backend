/**
 * Protocol-Level Steam Automation Manager
 *
 * Utilizes:
 * - `steam-user`: Programmatic Steam CM socket connection, authentication, and session handling
 * - `steam-totp`: Local 2FA code generation from shared secrets
 * - `steamcommunity`: Web session and cookie management
 */

import SteamUser from 'steam-user';
import SteamTotp from 'steam-totp';
import SteamCommunity from 'steamcommunity';

// Operational metrics for node health monitoring
export const stats = {
  startTime: Date.now(),
  totalProcessed: 0,
  completed: 0,
  failed: 0,
  activeSockets: 0,
  recentLogs: [],
};

export function addLog(level, message, meta = {}) {
  const logEntry = {
    id: `${Date.now()}-${Math.random().toString(36).substr(2, 6)}`,
    timestamp: new Date().toISOString(),
    level,
    message,
    meta,
  };
  stats.recentLogs.unshift(logEntry);
  if (stats.recentLogs.length > 100) {
    stats.recentLogs.pop();
  }

  const tag = `[SteamNode-${level.toUpperCase()}]`;
  if (level === 'error') {
    console.error(`${tag} ${message}`, Object.keys(meta).length ? meta : '');
  } else if (level === 'warn') {
    console.warn(`${tag} ${message}`, Object.keys(meta).length ? meta : '');
  } else {
    console.log(`${tag} ${message}`, Object.keys(meta).length ? meta : '');
  }

  return logEntry;
}

/**
 * Maps Steam EResult numeric codes to human-readable error names
 */
export function getEResultName(eresult) {
  if (!eresult) return 'Unknown';
  if (SteamUser.EResult && SteamUser.EResult[eresult]) {
    return SteamUser.EResult[eresult];
  }
  return `EResult_${eresult}`;
}

/**
 * Authenticates a Steam account at the socket protocol level.
 *
 * @param {Object} account
 * @param {string} account.steam_username
 * @param {string} account.steam_password
 * @param {string} [account.original_email]
 * @param {string} [account.shared_secret]
 * @param {string} [account.auth_code]
 * @param {number} [timeoutMs=35000]
 * @returns {Promise<Object>}
 */
export async function authenticateSteamAccount(account, timeoutMs = 35000) {
  const { steam_username, steam_password, original_email, shared_secret, auth_code } = account;

  if (!steam_username || !steam_password) {
    throw new Error('Missing required credentials: steam_username and steam_password');
  }

  stats.totalProcessed += 1;
  stats.activeSockets += 1;

  addLog('info', `Initializing CM socket connection for account: ${steam_username}`, {
    username: steam_username,
    hasSharedSecret: Boolean(shared_secret),
  });

  return new Promise((resolve, reject) => {
    let isResolved = false;
    let timeoutTimer = null;
    let generatedVerificationCode = null;

    // Initialize stateless SteamUser client
    const client = new SteamUser({
      promptSteamGuardCode: false,
      autoRelogin: false,
      dataDirectory: null, // In-memory session, stateless container
      enablePicsCache: false,
    });

    const cleanup = () => {
      if (timeoutTimer) clearTimeout(timeoutTimer);
      stats.activeSockets = Math.max(0, stats.activeSockets - 1);
      try {
        client.removeAllListeners();
        client.logOff();
      } catch (err) {
        // Socket already closed
      }
    };

    const handleSuccess = (resultData) => {
      if (isResolved) return;
      isResolved = true;
      stats.completed += 1;
      cleanup();
      resolve(resultData);
    };

    const handleFailure = (err) => {
      if (isResolved) return;
      isResolved = true;
      stats.failed += 1;
      cleanup();
      reject(err);
    };

    // Safety timeout to avoid socket hanging indefinitely
    timeoutTimer = setTimeout(() => {
      addLog('error', `Connection timeout for ${steam_username} after ${timeoutMs}ms`);
      const timeoutErr = new Error(`Steam CM Socket timed out after ${timeoutMs / 1000}s`);
      timeoutErr.eresult = SteamUser.EResult?.Timeout || 16;
      timeoutErr.code = 'SocketTimeout';
      handleFailure(timeoutErr);
    }, timeoutMs);

    // 1. Steam Guard Event Handler (Email Code or 2FA Mobile TOTP)
    client.on('steamGuard', (domain, callback, lastCodeWrong) => {
      addLog('warn', `Steam Guard challenge issued for ${steam_username}`, {
        domain: domain || 'Mobile App (2FA)',
        lastCodeWrong: Boolean(lastCodeWrong),
      });

      if (lastCodeWrong) {
        const wrongErr = new Error('Previous Steam Guard verification code was invalid');
        wrongErr.code = 'InvalidSteamGuardCode';
        handleFailure(wrongErr);
        return;
      }

      // Case A: 2FA TOTP Shared Secret is available
      if (shared_secret) {
        try {
          const totpCode = SteamTotp.generateAuthCode(shared_secret);
          generatedVerificationCode = totpCode;
          addLog('info', `Generated local 2FA TOTP code for ${steam_username}: ${totpCode}`);
          callback(totpCode);
          return;
        } catch (totpErr) {
          addLog('error', `Failed generating TOTP auth code with steam-totp: ${totpErr.message}`);
        }
      }

      // Case B: Pre-supplied auth code
      if (auth_code) {
        generatedVerificationCode = auth_code;
        addLog('info', `Applying pre-supplied verification code for ${steam_username}: ${auth_code}`);
        callback(auth_code);
        return;
      }

      // Case C: Email-based Steam Guard code sent to email
      if (domain) {
        addLog('warn', `Steam Guard email code sent to ${domain} for account ${steam_username}`);
        const emailErr = new Error(`Steam Guard email verification code sent to ${original_email || domain}. Verification code needed.`);
        emailErr.code = 'SteamGuardEmailNeeded';
        emailErr.domain = domain;
        emailErr.original_email = original_email;
        handleFailure(emailErr);
        return;
      }

      // Case D: Mobile 2FA without shared secret
      const noTotpErr = new Error(`Account ${steam_username} requires Steam Guard Mobile Authenticator 2FA, but no shared_secret was configured.`);
      noTotpErr.code = 'TwoFactorMissingSharedSecret';
      handleFailure(noTotpErr);
    });

    // 2. Authentication Error Handler
    client.on('error', (err) => {
      const eresultName = getEResultName(err.eresult);
      addLog('error', `Authentication error for ${steam_username}: ${err.message} (${eresultName})`, {
        eresult: err.eresult,
        eresultName,
        message: err.message,
      });

      err.eresultName = eresultName;
      handleFailure(err);
    });

    // 3. LoggedOn Event Handler (CM Socket successfully authenticated)
    client.on('loggedOn', (details) => {
      const steamID64 = client.steamID ? client.steamID.getSteamID64() : null;
      addLog('info', `CM Socket successfully authenticated for ${steam_username}! SteamID64: ${steamID64}`, {
        steamID64,
        eresult: details.eresult,
      });

      // Request Web API Session & Cookies via steamcommunity
      client.on('webSession', (sessionID, cookies) => {
        addLog('info', `Obtained Steam Web Session for ${steam_username}. Cookie count: ${cookies ? cookies.length : 0}`);

        let community = null;
        try {
          community = new SteamCommunity();
          community.setCookies(cookies);
        } catch (commErr) {
          addLog('warn', `SteamCommunity setCookies notice: ${commErr.message}`);
        }

        handleSuccess({
          success: true,
          steam_username,
          steamID64,
          sessionID,
          cookies,
          community,
          cookiesCount: cookies ? cookies.length : 0,
          target_verification_code: generatedVerificationCode,
          authenticatedAt: new Date().toISOString(),
          details: {
            cellId: details.cell_id,
            publicIP: details.public_ip,
          },
        });
      });
    });

    // 4. Disconnected Handler
    client.on('disconnected', (eresult, msg) => {
      addLog('warn', `Steam CM Socket disconnected for ${steam_username}: ${msg} (${getEResultName(eresult)})`);
    });

    // Prepare logOn parameters
    const logOnDetails = {
      accountName: steam_username,
      password: steam_password,
    };

    // If shared_secret is provided, pre-calculate twoFactorCode
    if (shared_secret) {
      try {
        const preTotp = SteamTotp.generateAuthCode(shared_secret);
        logOnDetails.twoFactorCode = preTotp;
        generatedVerificationCode = preTotp;
        addLog('info', `Pre-computed 2FA twoFactorCode for initial logon: ${preTotp}`);
      } catch (totpGenErr) {
        addLog('warn', `Could not pre-compute 2FA code: ${totpGenErr.message}`);
      }
    } else if (auth_code) {
      logOnDetails.authCode = auth_code;
      generatedVerificationCode = auth_code;
    }

    // Initiate the CM Socket Login
    try {
      client.logOn(logOnDetails);
    } catch (logOnErr) {
      addLog('error', `client.logOn exception for ${steam_username}: ${logOnErr.message}`);
      handleFailure(logOnErr);
    }
  });
}
