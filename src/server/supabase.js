/**
 * Supabase Database Integration for Stock Accounts Management
 * Maps directly to table: `stock_accounts`
 *
 * Schema mapping:
 * - Username: `steam_username`
 * - Password: `steam_password`
 * - Email: `original_email`
 * - Status field: `status` ('available', 'processing', 'completed', 'failed')
 * - Target Verification Code output field: `target_verification_code`
 */

import { createClient } from '@supabase/supabase-js';
import dotenv from 'dotenv';

dotenv.config();

// Ensure WebSocket compatibility for Node.js environments without native WebSocket
if (typeof globalThis.WebSocket === 'undefined') {
  globalThis.WebSocket = class WebSocketStub {
    constructor() {}
    addEventListener() {}
    removeEventListener() {}
    send() {}
    close() {}
  };
}

const supabaseUrl = process.env.SUPABASE_URL || '';
const supabaseKey = process.env.SUPABASE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY || '';

let supabaseClient = null;
let isConfigured = false;

if (supabaseUrl && supabaseKey && !supabaseUrl.includes('your-project')) {
  try {
    supabaseClient = createClient(supabaseUrl, supabaseKey, {
      auth: { persistSession: false },
    });
    isConfigured = true;
    console.log('[Supabase] Successfully initialized Supabase client connection to:', supabaseUrl);
  } catch (err) {
    console.error('[Supabase] Initialization failed:', err.message);
  }
} else {
  console.warn('[Supabase] Warning: SUPABASE_URL or SUPABASE_KEY is missing or using placeholder in .env. Falling back to in-memory staging store.');
}

// In-memory store fallback for development / testing when Supabase credentials are not yet configured
let memoryAccounts = [
  {
    id: 1,
    steam_username: 'demo_trader_01',
    steam_password: 'DEMO_PASSWORD_CHANGE_ME',
    original_email: 'trader01@automation-node.internal',
    status: 'available',
    target_verification_code: null,
    shared_secret: '',
    created_at: new Date(Date.now() - 3600000).toISOString(),
    last_error: null,
  },
  {
    id: 2,
    steam_username: 'bot_gifter_02',
    steam_password: 'DEMO_PASSWORD_CHANGE_ME',
    original_email: 'gifter02@automation-node.internal',
    status: 'available',
    target_verification_code: null,
    shared_secret: '',
    created_at: new Date(Date.now() - 1800000).toISOString(),
    last_error: null,
  },
];

/**
 * Fetch the next available account for processing.
 * Reads pending records where status = 'available'.
 */
export async function fetchNextAvailableAccount() {
  if (isConfigured && supabaseClient) {
    try {
      const { data, error } = await supabaseClient
        .from('stock_accounts')
        .select('*')
        .eq('status', 'available')
        .order('created_at', { ascending: true })
        .limit(1)
        .maybeSingle();

      if (error) {
        console.error('[Supabase] Query error fetching next available account:', error.message);
        throw error;
      }

      return data;
    } catch (err) {
      console.error('[Supabase] Error executing fetchNextAvailableAccount:', err.message);
      throw err;
    }
  }

  // Fallback to in-memory account queue
  const account = memoryAccounts.find((acc) => acc.status === 'available');
  return account || null;
}

/**
 * Update the status and metadata of a stock account.
 * Status values: 'available', 'processing', 'completed', 'failed'
 */
export async function updateAccountStatus(accountId, status, extraFields = {}) {
  // Only update columns that exist in the Supabase stock_accounts table
  const validColumns = new Set([
    'status',
    'target_verification_code',
    'assigned_game',
    'steam_username',
    'steam_password',
    'original_email',
    'email_password',
    'updated_at'
  ]);

  const sanitizedPayload = {
    status,
    updated_at: new Date().toISOString(),
  };

  for (const [k, v] of Object.entries(extraFields)) {
    if (validColumns.has(k) && v !== undefined) {
      sanitizedPayload[k] = v;
    }
  }

  if (isConfigured && supabaseClient) {
    try {
      const { data, error } = await supabaseClient
        .from('stock_accounts')
        .update(sanitizedPayload)
        .eq('id', accountId)
        .select()
        .single();

      if (error) {
        console.error(`[Supabase] Failed to update account ${accountId} status to ${status}:`, error.message);
        if (error.message && error.message.includes('check constraint')) {
          // If the DB constraint restricts status values, update without modifying status
          const { status: _ignored, ...payloadWithoutStatus } = sanitizedPayload;
          if (Object.keys(payloadWithoutStatus).length > 0) {
            const retryRes = await supabaseClient
              .from('stock_accounts')
              .update(payloadWithoutStatus)
              .eq('id', accountId)
              .select()
              .maybeSingle();
            return retryRes.data;
          }
        }
        throw error;
      }

      console.log(`[Supabase] Successfully updated account ID ${accountId} status to '${status}'`);
      return data;
    } catch (err) {
      console.error(`[Supabase] updateAccountStatus exception for ID ${accountId}:`, err.message);
      throw err;
    }
  }

  // Fallback in-memory update
  const index = memoryAccounts.findIndex((acc) => acc.id === accountId);
  if (index !== -1) {
    memoryAccounts[index] = {
      ...memoryAccounts[index],
      ...sanitizedPayload,
    };
    return memoryAccounts[index];
  }

  return null;
}

/**
 * Fetch summary of all accounts for the monitoring UI
 */
export async function fetchAccountsList(limit = 50) {
  if (isConfigured && supabaseClient) {
    try {
      const { data, error } = await supabaseClient
        .from('stock_accounts')
        .select('*')
        .order('created_at', { ascending: false })
        .limit(limit);

      if (error) throw error;
      return data || [];
    } catch (err) {
      console.warn('[Supabase] Failed to fetch accounts list, using local fallback:', err.message);
    }
  }

  return [...memoryAccounts];
}

/**
 * Insert or register an account into stock_accounts
 */
export async function insertAccount(accountData) {
  const newAccount = {
    steam_username: accountData.steam_username,
    steam_password: accountData.steam_password,
    original_email: accountData.original_email || null,
    email_password: accountData.email_password || null,
    status: accountData.status || 'available',
    target_verification_code: accountData.target_verification_code || null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  if (isConfigured && supabaseClient) {
    const { data, error } = await supabaseClient
      .from('stock_accounts')
      .insert([newAccount])
      .select()
      .single();

    if (error) throw error;
    return data;
  }

  newAccount.id = Date.now();
  memoryAccounts.unshift(newAccount);
  return newAccount;
}

/**
 * Check connectivity and configuration status
 */
export function getSupabaseStatus() {
  return {
    configured: isConfigured,
    provider: isConfigured ? 'Supabase Cloud (PostgreSQL)' : 'In-Memory Store (Awaiting .env credentials)',
    url: isConfigured ? supabaseUrl.replace(/(https?:\/\/)([^.]+)(\..+)/, '$1***$3') : 'Not configured',
    totalLoadedAccounts: memoryAccounts.length,
  };
}
