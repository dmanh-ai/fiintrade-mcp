# FiinTrade MCP Server

MCP server cho phép Claude.ai truy cập trực tiếp dữ liệu chứng khoán Việt Nam từ FiinTrade.

Hai nhóm tool: **Live API** (snapshot realtime, JSON) và **Excel download** (full history 2000 phiên ≈ 8 năm, parse Excel → JSON).

## 15 Tools

### Group A — Live snapshot (REST)

| Tool | Mục đích |
|---|---|
| `get_latest_price` | Giá realtime 1 mã |
| `get_price_history` | OHLCV n phiên gần nhất (mặc định 60) |
| `get_indices` | Snapshot VNINDEX/VN30/HNX/HNX30/UPCOM |
| `get_money_flow_contribution` | Top mã đóng góp dòng tiền cho 1 chỉ số |
| `get_money_flow_by_investor` | Money flow theo nhóm NĐT (snapshot) |
| `get_money_flow_chart` | Chart investor flow |
| `get_time_and_sales` | Khớp lệnh chi tiết phiên hiện tại |
| `get_busd_chart` | Áp lực mua/bán chủ động (BU/SD) |
| `get_watchlist` | Watchlist của user |
| `list_tickers` | Danh sách toàn bộ mã + phân ngành ICB |
| `get_hot_news` | Tin nóng |

### Group B — Excel download (full history)

| Tool | Mục đích |
|---|---|
| `download_investor_history` ⭐ | KL+GT khớp ròng 4 nhóm NĐT, 2000 phiên |
| `download_price_overview` | Giá tổng hợp + foreign net + thống kê khớp lệnh |
| `download_order_statistics` | Thống kê đặt lệnh (số lệnh, KL/lệnh trung bình) |
| `download_time_sales` | Time & Sales chi tiết tick-by-tick |

## Deploy lên Railway

### 1. Tạo GitHub repo và push code

```bash
cd fiintrade-mcp
git init
git add .
git commit -m "Initial FiinTrade MCP server"
gh repo create fiintrade-mcp --private --source=. --push
```

### 2. Lấy token `u268359`

Trên fiintrade.vn (đã login):
- Mở DevTools (F12) → tab **Network**
- Refresh trang, click bất kỳ widget nào để bắn request
- Click vào 1 request đến `*.fiintrade.vn` (vd `GetLatestPrice`)
- Tab **Headers** → tìm header `u268359` → copy value (chuỗi base64 dạng `xxxxxxxxxxxx==`)

### 3. Tạo project Railway

- https://railway.app/new → "Deploy from GitHub repo" → chọn `fiintrade-mcp`
- Railway tự detect Dockerfile, build và deploy

### 4. Set env var

Trong Railway dashboard:
- Tab **Variables** → Add: `FIINTRADE_TOKEN` = `<token_vừa_copy>`
- Save → service tự restart

### 5. Generate public URL

- Tab **Settings** → **Networking** → **Generate Domain**
- Format: `https://fiintrade-mcp-production-xxxx.up.railway.app`

### 6. Add vào Claude.ai

- Settings → **Connectors** → **Add custom connector**
- **Name**: `FiinTrade`
- **URL**: `https://<your-railway-domain>/mcp`
- **OAuth**: bỏ trống
- Save → Test → 15 tool sẽ xuất hiện trong dropdown tools

## Test local

```bash
export FIINTRADE_TOKEN="<your_token>"
pip install -r requirements.txt
python server.py
# Server chạy trên http://localhost:8000/mcp
```

## Khi token hết hạn (lỗi 401)

Token `u268359` có thể rotate. Khi MCP trả lỗi 401:

1. Lên fiintrade.vn → DevTools → copy token `u268359` mới
2. Railway dashboard → Variables → update `FIINTRADE_TOKEN`
3. Service auto-restart, MCP hoạt động lại

## Lưu ý

- **Rate limit**: dùng vừa phải. Excel download (Group B) ~250 KB/request, dùng cho phân tích 1-2 mã/lần.
- **Param đoán** chưa verify hết: `flow_type` trong `get_money_flow_contribution` (`Total`/`Foreign`/`Proprietary`?) và `investor_type` trong `get_money_flow_by_investor` (`LocalIndividualMatch` đã verify, các nhóm khác đoán theo pattern). Test thử nếu lỗi → báo Claude điều chỉnh.
- **Backup chắc ăn cho money flow**: `download_investor_history` luôn trả ĐỦ 4 nhóm NĐT trong 1 file, không phụ thuộc enum đoán.
