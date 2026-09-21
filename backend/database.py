import os

# قراءة ملف .env ببايثون مباشرة لضمان عدم حدوث أي خطأ
def _load_env():
    paths = [
        "/home/ubuntu/Steam-Bot-Backend/.env",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        ".env"
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip().strip("'\""))
            except Exception as e:
                print(f"[ENV_NOTICE] {e}")
            break

_load_env()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

supabase = None
try:
    if SUPABASE_URL and SUPABASE_KEY:
        from supabase import create_client, Client
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("[DATABASE] Supabase client initialized successfully.")
    else:
        print("[DATABASE] Supabase credentials not set.")
except Exception as e:
    print(f"[DATABASE] Notice: {e}")

def get_next_available_account():
    if not supabase:
        return None
    try:
        res = (
            supabase.table("stock_accounts")
            .select("*")
            .eq("status", "available")
            .order("id")
            .limit(1)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return res.data[0]
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
