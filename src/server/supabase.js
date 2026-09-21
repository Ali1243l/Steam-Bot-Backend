/**
 * Supabase Database Integration for Stock Accounts Management
 * Maps directly to table: `stock_accounts`
 */

import { createClient } from '@supabase/supabase-js';
import dotenv from 'dotenv';

dotenv.config();

const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;

export let isConfigured = Boolean(SUPABASE_URL && SUPABASE_KEY);
export let supabaseClient = null;

if (isConfigured) {
  try {
    supabaseClient = createClient(SUPABASE_URL, SUPABASE_KEY, {
      auth: {
        persistSession: false,
        autoRefreshToken: false,
      },
    });
    console.log('[Supabase] Successfully initialized Supabase client connection to:', SUPABASE_URL);
  } catch (err) {
    console.error('[Supabase] Failed to initialize client:', err.message);
    isConfigured = false;
  }
} else {
  console.warn('[Supabase] SUPABASE_URL or SUPABASE_KEY not provided. Operating in fallback mock storage.');
}

export function getSupabaseClient() {
  return supabaseClient;
}

// In-memory fallback stock accounts
let memoryAccounts = [
  {
    id: 'mem-1',
    steam_username: 'osuje21271',
    steam_password: 'Password123!',
    original_email: 'EsleyGabby583225@outlook.com',
    email_password: 'Password123!',
    shared_secret: '',
    status: 'available',
    target_verification_code: null,
    assigned_game: null,
    updated_at: new Date().toISOString(),
  }
];

export async function fetchAvailableAccounts() {
  if (isConfigured && supabaseClient) {
    try {
      const { data, error } = await supabaseClient
        .from('stock_accounts')
        .select('*')
        .order('created_at', { ascending: false });

      if (error) {
        console.error('[Supabase] Query error in fetchAvailableAccounts:', error.message);
        return memoryAccounts;
      }

      if (data && data.length > 0) {
        return data;
      }
      return memoryAccounts;
    } catch (err) {
      console.error('[Supabase] Exception fetching accounts:', err.message);
      return memoryAccounts;
    }
  }
  return memoryAccounts;
}

// Alias for compatibility
export const getAvailableAccounts = fetchAvailableAccounts;

export async function updateAccountStatus(accountId, status, extraFields = {}) {
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

  const allowedStatuses = new Set(['available', 'completed', 'failed', 'used']);

  const sanitizedPayload = {
    updated_at: new Date().toISOString(),
  };

  if (status && allowedStatuses.has(String(status).toLowerCase())) {
    sanitizedPayload.status = String(status).toLowerCase();
  }

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
        .maybeSingle();

      if (error) {
        console.error(`[Supabase] Failed to update account ${accountId}:`, error.message);
        if (error.message && error.message.includes('check constraint')) {
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
        return null;
      }

      console.log(`[Supabase] Successfully updated account ID ${accountId}`);
      return data;
    } catch (err) {
      console.error(`[Supabase] Exception updating account ${accountId}:`, err.message);
      return null;
    }
  }

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

export async function loadInitialAccounts() {
  return await fetchAvailableAccounts();
}
