cd /home/ubuntu/Steam-Bot-Backend

# 1. إيقاف الحاوية الحالية
sudo docker stop steam-bot-container 2>/dev/null || true
sudo docker rm steam-bot-container 2>/dev/null || true

# 2. إنشاء مجلد dist به صفحة HTML نظيفة للواجهة
mkdir -p dist
cat << 'EOF' > dist/index.html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Steam Protocol Automation Node</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; padding: 40px; text-align: center; }
    .card { background: #1e293b; max-width: 600px; margin: 0 auto; padding: 30px; border-radius: 12px; border: 1px solid #334155; }
    .status { color: #10b981; font-weight: bold; font-size: 20px; margin-bottom: 20px; }
    .badge { display: inline-block; background: #0284c7; color: white; padding: 4px 12px; border-radius: 20px; font-size: 14px; }
    a { color: #38bdf8; text-decoration: none; }
  </style>
</head>
<body>
  <div class="card">
    <div class="status">● Steam Node Server is LIVE & Healthy</div>
    <p>Direct Socket Protocol Worker (Node-Steam-User & Supabase Queue)</p>
    <div style="margin: 20px 0;">
      <span class="badge">Port 8000</span>
      <span class="badge">Cloud Node</span>
    </div>
    <p><a href="/health" target="_blank">View /health JSON Metrics</a></p>
    <p><a href="/api/accounts" target="_blank">View /api/accounts</a></p>
  </div>
</body>
</html>
EOF

# 3. بناء الحاوية متضمنة مجلد dist
sudo docker build -t steam-bot .

# 4. تشغيل الحاوية
sudo docker run -d \
  --name steam-bot-container \
  --restart always \
  -m 1800m \
  -p 8000:8000 \
  -e PORT=8000 \
  -e SUPABASE_URL="https://mgddwvkgswdahragsazv.supabase.co" \
  -e SUPABASE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1nZGR3dmtnc3dkYWhyYWdzYXp2Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4OTg0ODE3OSwiZXhwIjoyMTA1NDI0MTc5fQ.L0ldAP1YU6ZSHI-wev_0XbW8aOLlH18de4GNog7FqMw" \
  steam-bot

# 5. عرض السجلات
sudo docker logs -f steam-bot-container
