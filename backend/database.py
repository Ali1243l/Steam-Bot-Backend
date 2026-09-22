import os

# قراءة ملف .env وتعيين المتغيرات في البيئة مباشرة
env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if not os.path.exists(env_file):
    env_file = "/home/ubuntu/Steam-Bot-Backend/.env"

if os.path.exists(env_file):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip("'\"")

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL")
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY")
    or os.getenv("VITE_SUPABASE_ANON_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
)

supabase = None

try:
    if SUPABASE_URL and SUPABASE_KEY:
        from supabase import create_client, Client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print(f"[DATABASE] ✅ Supabase connected successfully to: {SUPABASE_URL[:20]}...")
    else:
        print(f"[DATABASE] ❌ Supabase credentials missing! URL: {bool(SUPABASE_URL)}, KEY: {bool(SUPABASE_KEY)}")
except Exception as e:
    print(f"[DATABASE] ❌ Supabase connection error: {e}")

def get_next_available_account():
    if not supabase:
        print("[DATABASE] get_next_available_account: supabase client is None!")
        return None
    try:
        # 1. البحث عن حساب بحالة available
        res = supabase.table("stock_accounts").select("*").eq("status", "available").order("id").limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]

        # 2. إذا لم يجد (تدوير أول حساب فوراً)
        print("[DATABASE] No available account found, auto-recycling first account in stock...")
        res_all = supabase.table("stock_accounts").select("*").order("id").limit(1).execute()
        if res_all.data and len(res_all.data) > 0:
            acc = res_all.data[0]
            update_account_status(acc.get("id"), "available")
            return acc

        return None
    except Exception as e:
        print(f"[DATABASE] Error querying stock_accounts: {e}")
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
