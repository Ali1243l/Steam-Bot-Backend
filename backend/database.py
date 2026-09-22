import os
import json
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")

supabase: Client = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("[DATABASE] Supabase client initialized successfully.")
    except Exception as e:
        print(f"[DATABASE] Error initializing Supabase: {e}")
else:
    print("[DATABASE] Supabase credentials not found in env.")

def get_next_available_account():
    if not supabase:
        return None
    try:
        # 1. البحث عن حساب بحالة available
        res = supabase.table("stock_accounts").select("*").eq("status", "available").order("id").limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
            
        # 2. إذا لم يجد (حل نهائي): خذ أول حساب وأعده available فوراً
        print("[DATABASE] No available accounts, recycling first existing stock account...")
        res_all = supabase.table("stock_accounts").select("*").order("id").limit(1).execute()
        if res_all.data and len(res_all.data) > 0:
            acc = res_all.data[0]
            update_account_status(acc.get("id"), "available")
            return acc
            
        return None
    except Exception as e:
        print(f"[DATABASE] Error: {e}")
        return None

def update_account_status(account_id: int | str, status: str, extra_data: dict = None):
    if not supabase or not account_id:
        return False
    try:
        payload = {"status": status}
        if extra_data:
            payload.update(extra_data)
        supabase.table("stock_accounts").update(payload).eq("id", account_id).execute()
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating status: {e}")
        return False
