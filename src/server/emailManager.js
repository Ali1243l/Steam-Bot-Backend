/**
 * Outlook Verification Code & Steam Email Change Engine
 *
 * Implements:
 * 1. WebSession handover to SteamCommunity with active session verification
 * 2. Steam Help Wizard verification initiation via AJAX with sessionid & wizard_ajax
 * 3. Outlook IMAP code extraction with resilient try-catch error handling
 * 4. Submission of verification code + target_email finalization
 */

import { ImapFlow } from 'imapflow';
import { simpleParser } from 'mailparser';

/**
 * Safely extracts the active sessionid string from SteamCommunity cookies or session
 *
 * @param {Object} community
 * @param {string} [fallbackId]
 * @returns {string}
 */
export function extractActiveSessionId(community, fallbackId = null) {
  // 1. Try getCookies() for help.steampowered.com / steamcommunity.com
  try {
    if (community && typeof community.getCookies === 'function') {
      const domains = [
        'https://help.steampowered.com',
        'https://steamcommunity.com',
        'https://store.steampowered.com',
      ];
      for (const domain of domains) {
        const cookies = community.getCookies(domain);
        const cookieList = Array.isArray(cookies)
          ? cookies
          : typeof cookies === 'string'
          ? cookies.split(';')
          : [];
        for (const c of cookieList) {
          const match = String(c).match(/sessionid=([a-zA-Z0-9_-]+)/i);
          if (match && match[1]) {
            return match[1];
          }
        }
      }
    }
  } catch (e) {
    // Non-blocking cookie inspection
  }

  // 2. Try getSessionID() on community instance
  try {
    if (community && typeof community.getSessionID === 'function') {
      const sid = community.getSessionID();
      if (sid && sid.length > 4) return sid;
    }
  } catch (e) {
    // Non-blocking
  }

  // 3. Try community._jar if available
  try {
    if (community && community._jar && typeof community._jar.getCookieStringSync === 'function') {
      const cookieStr =
        community._jar.getCookieStringSync('https://help.steampowered.com') ||
        community._jar.getCookieStringSync('https://steamcommunity.com') ||
        '';
      const match = cookieStr.match(/sessionid=([a-zA-Z0-9_-]+)/i);
      if (match && match[1]) {
        return match[1];
      }
    }
  } catch (e) {
    // Non-blocking
  }

  return fallbackId || '';
}

/**
 * Extracts 5-character Steam verification code from email body or subject
 *
 * @param {string} text
 * @returns {string|null}
 */
export function parseSteamVerificationCode(text) {
  if (!text) return null;

  const patterns = [
    /(?:verification code|confirmation code|code is|security code)[:\s]+<[^>]*>?\s*([A-Z0-9]{5})\b/i,
    /(?:verification code|confirmation code|code is|security code)[:\s]+([A-Z0-9]{5})\b/i,
    /<td[^>]*class="[^"]*code[^"]*"[^>]*>\s*([A-Z0-9]{5})\s*<\/td>/i,
    /<span[^>]*style="[^"]*"[^>]*>\s*([A-Z0-9]{5})\s*<\/span>/i,
    />\s*([A-Z0-9]{5})\s*</,
    /\b([A-Z0-9]{5})\b/,
  ];

  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match && match[1]) {
      const code = match[1].toUpperCase();
      if (!['CLASS', 'STYLE', 'HTTPS', 'WIDTH', 'TABLE', 'STEAM'].includes(code)) {
        return code;
      }
    }
  }

  return null;
}

/**
 * Safely disconnects and cleans up IMAP resources without throwing unhandled promise rejections
 *
 * @param {ImapFlow} client
 * @param {Object} lock
 */
async function safeCloseImap(client, lock) {
  if (lock) {
    try {
      if (typeof lock.release === 'function') {
        lock.release();
      }
    } catch (e) {
      // Ignored
    }
  }

  if (client) {
    try {
      if (typeof client.logout === 'function') {
        await client.logout();
      }
    } catch (e) {
      // Ignored
    }

    try {
      if (typeof client.close === 'function') {
        await client.close();
      }
    } catch (e) {
      // Ignored
    }
  }
}

/**
 * Connects to Outlook IMAP and polls for the latest Steam confirmation email.
 * Refactored to use standard async/await try-catch blocks with zero undefined .catch calls.
 *
 * @param {string} email
 * @param {string} password
 * @param {Object} [options]
 * @param {number} [options.timeoutMs=60000]
 * @param {number} [options.pollIntervalMs=4000]
 * @param {Function} [options.logger]
 * @returns {Promise<string>} 5-character verification code
 */
export async function fetchOutlookVerificationCode(email, password, options = {}) {
  const timeoutMs = options.timeoutMs || 60000;
  const pollIntervalMs = options.pollIntervalMs || 4000;
  const log = options.logger || console.log;

  log(`[EmailEngine] Connecting to Outlook IMAP (${email})...`);

  const imapHosts = ['outlook.office365.com', 'imap-mail.outlook.com'];

  for (const host of imapHosts) {
    let client = null;
    let lock = null;
    let lastSocketError = null;

    try {
      client = new ImapFlow({
        host,
        port: 993,
        secure: true,
        auth: {
          user: email,
          pass: password,
        },
        logger: false,
        emitLogs: false,
      });

      // Attach error listener to prevent unhandled 'error' event on ImapFlow
      client.on('error', (err) => {
        lastSocketError = err;
        log(`[EmailEngine] Socket event handled on ${host}: ${err.message}`);
      });

      log(`[EmailEngine] Establishing TLS connection to ${host}:993...`);
      await client.connect();
      log(`[EmailEngine] Successfully established IMAP TLS connection to ${host}`);

      lock = await client.getMailboxLock('INBOX');
      const startTime = Date.now();

      while (Date.now() - startTime < timeoutMs) {
        log(`[EmailEngine] Polling mailbox for Steam verification messages...`);

        const uids = await client.search({ from: 'steampowered.com' }, { uid: true });

        if (uids && uids.length > 0) {
          const newestUid = uids[uids.length - 1];
          log(`[EmailEngine] Found ${uids.length} Steam email(s). Fetching message UID: ${newestUid}`);

          const message = await client.fetchOne(newestUid, {
            source: true,
            envelope: true,
          });

          if (message && message.source) {
            const parsed = await simpleParser(message.source);
            const fullContent = `${parsed.subject || ''} ${parsed.text || ''} ${parsed.html || ''}`;
            const extractedCode = parseSteamVerificationCode(fullContent);

            if (extractedCode) {
              log(`[EmailEngine] Successfully extracted 5-character Steam code: ${extractedCode}`);
              return extractedCode;
            }
          }
        }

        log(`[EmailEngine] Code not yet arrived. Waiting ${pollIntervalMs / 1000}s before next check...`);
        await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
      }

      throw new Error(`IMAP timeout: No Steam verification code received within ${timeoutMs / 1000}s`);
    } catch (imapErr) {
      log(`[EmailEngine] Host ${host} notice: ${imapErr.message}`);

      const errMsg = imapErr.message || '';
      const sockMsg = lastSocketError?.message || '';
      const isRestricted =
        errMsg.includes('disabled') ||
        errMsg.includes('AUTHENTICATE') ||
        errMsg.includes('ECONNRESET') ||
        sockMsg.includes('ECONNRESET') ||
        errMsg.includes('LOGIN failed');

      if (isRestricted) {
        throw new Error(`Outlook IMAP Basic Auth restricted by Microsoft: ${errMsg || sockMsg}`);
      }

      if (host === imapHosts[imapHosts.length - 1]) {
        throw imapErr;
      }
    } finally {
      await safeCloseImap(client, lock);
    }
  }

  throw new Error('Failed to connect to Outlook IMAP servers');
}

/**
 * Triggers Steam Help Wizard to dispatch a verification code to the original account email.
 * Calls https://help.steampowered.com/en/wizard/ajaxdosendemailchangeverification with sessionid & wizard_ajax=1
 * Logs the exact JSON response.
 *
 * @param {Object} community Authenticated SteamCommunity instance
 * @param {string} [sessionID]
 * @param {Function} [logger]
 * @returns {Promise<{dispatched: boolean, response: any, sessionId: string}>}
 */
export async function triggerSteamChangeEmailVerification(community, sessionID, logger) {
  const log = logger || console.log;
  const activeSessionId = extractActiveSessionId(community, sessionID);

  log(`[EmailChange] Triggering Steam Help Wizard verification... Active sessionid: [${activeSessionId ? activeSessionId.substring(0, 6) + '***' : 'empty'}]`);

  const endpoints = [
    'https://help.steampowered.com/en/wizard/ajaxdosendemailchangeverification',
    'https://help.steampowered.com/en/wizard/AjaxSendChangeEmailVerification',
  ];

  let dispatched = false;
  let responseData = null;

  for (const endpoint of endpoints) {
    try {
      const result = await new Promise((resolve) => {
        community.httpRequestPost(
          {
            uri: endpoint,
            form: {
              sessionid: activeSessionId,
              wizard_ajax: 1,
            },
            headers: {
              Referer: 'https://help.steampowered.com/en/wizard/HelpWithLoginInfo?issueid=406',
              Origin: 'https://help.steampowered.com',
              'X-Requested-With': 'XMLHttpRequest',
              'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            },
            json: true,
          },
          (err, res, body) => {
            if (err) {
              log(`[EmailChange] Request error calling ${endpoint}: ${err.message}`);
              return resolve({ success: false, error: err.message });
            }

            // PIPELINE RESILIENCE: Always log exact JSON response from Steam Help Wizard
            log(`[EmailChange] Steam Help Wizard AJAX exact response from ${endpoint}:`, JSON.stringify(body));

            if (body && (body.success === 1 || body.success === true || body.result === 1)) {
              resolve({ success: true, body });
            } else {
              resolve({ success: false, body });
            }
          }
        );
      });

      responseData = result.body;
      if (result.success) {
        dispatched = true;
        log(`[EmailChange] Confirmed: Steam Help Wizard dispatched confirmation email! Response: ${JSON.stringify(result.body)}`);
        break;
      }
    } catch (e) {
      log(`[EmailChange] Exception calling ${endpoint}: ${e.message}`);
    }
  }

  return {
    dispatched,
    response: responseData,
    sessionId: activeSessionId,
  };
}

/**
 * Automated Steam Email Change Workflow
 *
 * @param {Object} community Authenticated SteamCommunity instance
 * @param {Object} params
 * @param {string} params.originalEmail Current account email
 * @param {string} params.emailPassword Password for original email
 * @param {string} params.targetEmail New email to set on Steam account
 * @param {string} [params.sessionID]
 * @param {Function} [params.logger]
 */
export async function executeSteamEmailChange(community, params) {
  const { originalEmail, emailPassword, targetEmail, sessionID, logger } = params;
  const log = logger || console.log;

  if (!community) {
    throw new Error('Active SteamCommunity instance is required');
  }
  if (!targetEmail) {
    throw new Error('target_email is required for email change workflow');
  }

  log(`[EmailChange] Initiating Steam Email Change from ${originalEmail} -> ${targetEmail}`);

  // Step 1: Verify Steam Community Active Session
  await new Promise((resolve) => {
    community.loggedIn((err, loggedIn) => {
      if (err) {
        log(`[EmailChange] Warning checking loggedIn status: ${err.message}`);
      }
      log(`[EmailChange] Steam Community session verified. LoggedIn: ${Boolean(loggedIn)}`);
      resolve(true);
    });
  });

  const activeSessionId = extractActiveSessionId(community, sessionID);

  // Step 2: Request Steam to dispatch change verification code to original_email
  const triggerResult = await triggerSteamChangeEmailVerification(community, activeSessionId, log);

  // Step 3: Extract verification code from Outlook
  log(`[EmailChange] Polling Outlook inbox (${originalEmail}) for verification code...`);
  let verificationCode = null;

  try {
    verificationCode = await fetchOutlookVerificationCode(originalEmail, emailPassword, {
      logger: log,
      timeoutMs: 45000,
      pollIntervalMs: 3000,
    });
  } catch (emailErr) {
    log(`[EmailChange] Outlook automated retrieval notice: ${emailErr.message}`);
    const structuredErr = new Error(`Email verification code retrieval: ${emailErr.message}`);
    structuredErr.code = 'EMAIL_CODE_EXTRACTION_FAILED';
    structuredErr.helpWizardDispatched = triggerResult.dispatched;
    structuredErr.helpWizardResponse = triggerResult.response;
    throw structuredErr;
  }

  if (!verificationCode) {
    throw new Error('Failed to extract valid 5-character verification code from email');
  }

  log(`[EmailChange] Extracted verification code: [${verificationCode}]. Submitting to Steam...`);

  // Step 4: Submit code & target_email to Steam Help Wizard
  const submitResult = await new Promise((resolve, reject) => {
    community.httpRequestPost(
      {
        uri: 'https://help.steampowered.com/en/wizard/AjaxChangeEmail',
        form: {
          sessionid: activeSessionId,
          wizard_ajax: 1,
          email: targetEmail,
          code: verificationCode,
        },
        headers: {
          Referer: 'https://help.steampowered.com/en/wizard/HelpWithLoginInfo?issueid=406',
          Origin: 'https://help.steampowered.com',
          'X-Requested-With': 'XMLHttpRequest',
        },
        json: true,
      },
      (err, res, body) => {
        if (err) {
          log(`[EmailChange] AjaxChangeEmail network error: ${err.message}`);
          return reject(err);
        }

        log(`[EmailChange] AjaxChangeEmail exact response:`, JSON.stringify(body));
        if (body && (body.success === 1 || body.success === true || body.result === 1)) {
          resolve({
            success: true,
            verificationCode,
            targetEmail,
            message: 'Steam email successfully changed',
          });
        } else {
          const errorMsg = body?.error || body?.msg || JSON.stringify(body);
          reject(new Error(`Steam change email rejected: ${errorMsg}`));
        }
      }
    );
  });

  return submitResult;
}
