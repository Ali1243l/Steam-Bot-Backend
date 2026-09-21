/**
 * Outlook Verification Code & Steam Email Change Engine
 *
 * Implements:
 * 1. WebSession handover to SteamCommunity with active session verification
 * 2. Steam email change verification initiation
 * 3. Outlook IMAP / Web mail code extraction (noreply@steampowered.com 5-character code)
 * 4. Submission of verification code + target_email finalization
 */

import { ImapFlow } from 'imapflow';
import { simpleParser } from 'mailparser';

/**
 * Extracts 5-character Steam verification code from email body or subject
 * Steam format: e.g. "C8H2B", "9DF3A", or "Your account verification code is: XXXXX"
 *
 * @param {string} text
 * @returns {string|null}
 */
export function parseSteamVerificationCode(text) {
  if (!text) return null;

  // 1. Explicit pattern matching Steam email verification messages
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
      // Avoid false positive matches like HTML tags or common words
      const code = match[1].toUpperCase();
      if (!['CLASS', 'STYLE', 'HTTPS', 'WIDTH', 'TABLE', 'STEAM'].includes(code)) {
        return code;
      }
    }
  }

  return null;
}

/**
 * Connects to Outlook IMAP and polls for the latest Steam confirmation email
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

  // Try standard Outlook IMAP servers
  const imapHosts = ['outlook.office365.com', 'imap-mail.outlook.com'];

  for (const host of imapHosts) {
    const client = new ImapFlow({
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

    // CRITICAL: Attach error listener to ImapFlow instance to prevent unhandled 'error' event from crashing Node
    let lastSocketError = null;
    client.on('error', (err) => {
      lastSocketError = err;
      log(`[EmailEngine] Socket event handled on ${host}: ${err.message}`);
    });

    try {
      await client.connect();
      log(`[EmailEngine] Successfully established IMAP TLS connection to ${host}`);

      const lock = await client.getMailboxLock('INBOX');
      const startTime = Date.now();

      try {
        while (Date.now() - startTime < timeoutMs) {
          log(`[EmailEngine] Polling mailbox for Steam verification messages...`);

          // Search messages from steampowered.com
          const uids = await client.search({
            from: 'steampowered.com',
          }, { uid: true });

          if (uids && uids.length > 0) {
            // Sort ascending to get newest UID
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
      } finally {
        lock.release();
        await client.logout().catch(() => {});
        await client.close().catch(() => {});
      }
    } catch (imapErr) {
      log(`[EmailEngine] Host ${host} notice: ${imapErr.message}`);
      await client.logout().catch(() => {});
      await client.close().catch(() => {});

      // If basic authentication was disabled by Microsoft on consumer accounts:
      if (
        imapErr.message?.includes('disabled') ||
        imapErr.message?.includes('AUTHENTICATE') ||
        imapErr.message?.includes('ECONNRESET') ||
        lastSocketError?.message?.includes('ECONNRESET')
      ) {
        throw new Error(`Outlook IMAP Basic Auth restricted by Microsoft: ${imapErr.message}`);
      }
      if (host === imapHosts[imapHosts.length - 1]) {
        throw imapErr;
      }
    }
  }

  throw new Error('Failed to connect to Outlook IMAP servers');
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
  await new Promise((resolve, reject) => {
    community.loggedIn((err, loggedIn) => {
      if (err) {
        log(`[EmailChange] Warning checking loggedIn status: ${err.message}`);
      }
      log(`[EmailChange] Steam Community session verified. LoggedIn: ${Boolean(loggedIn)}`);
      resolve(true);
    });
  });

  const activeSessionId = sessionID || community.getSessionID();

  // Step 2: Request Steam to send change verification code to original_email
  log(`[EmailChange] Calling Steam Help Wizard to trigger confirmation code...`);

  let codeTriggered = false;
  try {
    const triggerUrl = 'https://help.steampowered.com/en/wizard/AjaxSendChangeEmailVerification';
    await new Promise((resolve, reject) => {
      community.httpRequestPost(
        {
          uri: triggerUrl,
          form: {
            sessionid: activeSessionId,
            wizard_ajax: 1,
          },
          json: true,
        },
        (err, res, body) => {
          if (err) {
            log(`[EmailChange] AjaxSendChangeEmailVerification notice: ${err.message}`);
            // Fallback: Proceed to check inbox in case code was sent
            resolve(false);
          } else {
            log(`[EmailChange] Trigger endpoint response:`, body || 'OK');
            codeTriggered = true;
            resolve(true);
          }
        }
      );
    });
  } catch (triggerErr) {
    log(`[EmailChange] Trigger call exception: ${triggerErr.message}`);
  }

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
    log(`[EmailChange] Outlook automated retrieval encountered: ${emailErr.message}`);
    // If Outlook basic auth is disabled on this specific consumer account,
    // re-throw a structured error with instructions so the admin can supply target_verification_code
    const structuredErr = new Error(`Email verification code retrieval: ${emailErr.message}`);
    structuredErr.code = 'EMAIL_CODE_EXTRACTION_FAILED';
    throw structuredErr;
  }

  if (!verificationCode) {
    throw new Error('Failed to extract valid 5-character verification code from email');
  }

  log(`[EmailChange] Extracted verification code: [${verificationCode}]. Submitting to Steam...`);

  // Step 4: Submit code & target_email to Steam
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
        json: true,
      },
      (err, res, body) => {
        if (err) {
          log(`[EmailChange] AjaxChangeEmail error: ${err.message}`);
          return reject(err);
        }

        log(`[EmailChange] Steam response:`, body);
        if (body && (body.success === 1 || body.success === true || body.result === 1)) {
          resolve({
            success: true,
            verificationCode,
            targetEmail,
            message: 'Steam email successfully changed',
          });
        } else {
          // If body contains specific error details
          const errorMsg = body?.error || body?.msg || 'Steam rejected confirmation code or target email';
          reject(new Error(`Steam change email rejected: ${errorMsg}`));
        }
      }
    );
  });

  return submitResult;
}
