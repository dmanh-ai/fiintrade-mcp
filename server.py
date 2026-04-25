"""
FiinTrade MCP Server — v1
Cung cấp 15 tool truy cập dữ liệu chứng khoán Việt Nam từ FiinTrade.

Auth: header `u268359` (giá trị từ env FIINTRADE_TOKEN).
Token lấy từ DevTools > Network > 1 request bất kỳ tới *.fiintrade.vn
                                  > tab Headers > "u268359: <giá trị>".
Token có thể rotate; nếu lỗi 401 → vào FiinTrade web, copy token mới,
update env var trên Railway, redeploy.

Hai nhóm tool:
  - Group A (live snapshot): gọi REST API, trả JSON realtime.
  - Group B (Excel download): tải file .xlsx, parse, trả full history dạng JSON.
"""
import os
import io
import time
from typing import Optional

import httpx
import pandas as pd
from fastmcp import FastMCP

# ============================================================
# CONFIG
# ============================================================
TOKEN = os.environ.get("FIINTRADE_TOKEN", "")
if not TOKEN:
    raise RuntimeError(
        "Missing env var FIINTRADE_TOKEN. "
        "Lay gia tri tu DevTools > Network > header 'u268359' tren fiintrade.vn"
    )

BASE_HEADERS = {
    "u268359": TOKEN,
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Origin": "https://fiintrade.vn",
    "Referer": "https://fiintrade.vn/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

HOSTS = {
    "core": "https://core.fiintrade.vn",
    "market": "https://market.fiintrade.vn",
    "technical": "https://technical.fiintrade.vn",
    "tools": "https://tools.fiintrade.vn",
}

mcp = FastMCP("fiintrade")


# ============================================================
# HTTP HELPERS
# ============================================================
async def _get_json(host: str, path: str, params: Optional[dict] = None) -> dict:
    """GET 1 endpoint REST, tra ve JSON."""
    url = f"{HOSTS[host]}{path}"
    p = dict(params or {})
    p.setdefault("language", "vi")
    p.setdefault("time", int(time.time() * 1000))  # cache buster
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=BASE_HEADERS, params=p)
        r.raise_for_status()
        return r.json()


async def _download_excel(host: str, path: str, params: dict) -> bytes:
    """Tai 1 file Excel tu FiinTrade."""
    url = f"{HOSTS[host]}{path}"
    p = dict(params)
    p.setdefault("language", "vi")
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url, headers=BASE_HEADERS, params=p)
        r.raise_for_status()
        return r.content


def _parse_fiintrade_excel(content: bytes) -> pd.DataFrame:
    """
    Parse file Excel cua FiinTrade.
    Cau truc: 7 dong meta (logo + Data Title + Date Of Extract + dong trong),
              header thuc o row 8 (zero-indexed = 7).
    """
    df = pd.read_excel(io.BytesIO(content), sheet_name=0, header=7)
    df = df.dropna(how="all").reset_index(drop=True)
    # Chuyen datetime -> ISO string de JSON serialize duoc
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
    return df


def _df_to_response(df: pd.DataFrame, code: str) -> dict:
    """Convert DataFrame -> response JSON chuan."""
    return {
        "ticker": code.upper(),
        "rows": len(df),
        "columns": list(df.columns),
        "data": df.to_dict(orient="records"),
    }


# ============================================================
# GROUP A — LIVE API (REST snapshot)
# ============================================================

@mcp.tool()
async def get_latest_price(code: str) -> dict:
    """
    Lay gia realtime cua 1 ma chung khoan.

    Args:
        code: Ma CK (vd 'HPG', 'VHM', 'VNINDEX')
    """
    return await _get_json(
        "technical", "/PriceData/GetLatestPrice", {"Code": code.upper()}
    )


@mcp.tool()
async def get_price_history(
    code: str,
    frequency: str = "Daily",
    page_size: int = 60,
    page: int = 1,
) -> dict:
    """
    Lay lich su OHLCV cua 1 ma (live API, mac dinh 60 phien gan nhat).
    Cho du lieu lon hon nen dung `download_price_overview` (file Excel).

    Args:
        code: Ma CK
        frequency: 'Daily' | 'Weekly' | 'Monthly'
        page_size: So phien (mac dinh 60, max ~500)
        page: Phan trang (mac dinh 1)
    """
    return await _get_json(
        "technical",
        "/PriceData/GetPriceData",
        {
            "Code": code.upper(),
            "Frequently": frequency,
            "Page": page,
            "PageSize": page_size,
        },
    )


@mcp.tool()
async def get_indices() -> dict:
    """
    Snapshot tat ca chi so dang giao dich: VNINDEX, VN30, HNX, HNX30, UPCOM...
    Tra ve gia hien tai, % thay doi, volume, value.
    """
    return await _get_json(
        "market",
        "/MarketInDepth/GetLatestIndices",
        {"pageSize": 99999, "status": 1},
    )


@mcp.tool()
async def get_money_flow_contribution(
    com_group: str = "VNINDEX",
    flow_type: str = "Total",
) -> dict:
    """
    Top ma dong gop dong tien cho 1 chi so trong phien hien tai
    (tab "Ty trong" trong widget Xu huong dong tien).

    Args:
        com_group: 'VNINDEX' | 'VN30' | 'HNXINDEX' | 'UPCOMINDEX'
        flow_type: 'Total' | 'Foreign' | 'Proprietary' (doan — chua verify het)
    """
    return await _get_json(
        "market",
        "/MoneyFlow/GetContribution",
        {"ComGroupCode": com_group.upper(), "Type": flow_type},
    )


@mcp.tool()
async def get_money_flow_by_investor(
    com_group: str = "VNINDEX",
    investor_type: str = "LocalIndividualMatch",
) -> dict:
    """
    Dong tien theo nhom nha dau tu cho 1 chi so (live snapshot).
    Response chua data cua TAT CA nhom NDT trong 1 lan goi (UI chi filter local),
    nen `investor_type` chi anh huong tab nao duoc "highlight".

    De co FULL HISTORY theo tung phien cho 1 ma cu the, dung
    `download_investor_history(code)` thay vi tool nay.

    Args:
        com_group: 'VNINDEX' | 'VN30' | 'HNXINDEX' | 'UPCOMINDEX'
        investor_type: 'LocalIndividualMatch' (da verify) |
                       'ForeignMatch' | 'ProprietaryMatch' |
                       'LocalInstitutionMatch' (doan)
    """
    return await _get_json(
        "market",
        "/MoneyFlow/GetStatisticInvestor",
        {"ComGroupCode": com_group.upper(), "investorType": investor_type},
    )


@mcp.tool()
async def get_money_flow_chart(code: str = "VNINDEX", frequency: str = "Daily") -> dict:
    """
    Chart du lieu dong tien theo nhom NDT cho 1 ma/chi so.

    Args:
        code: Ma CK hoac chi so (vd 'VNINDEX', 'HPG')
        frequency: 'Daily' | 'Weekly' | 'Monthly'
    """
    return await _get_json(
        "market",
        "/MoneyFlow/GetStatisticInvestorChart",
        {"Code": code.upper(), "Frequently": frequency},
    )


@mcp.tool()
async def get_time_and_sales(code: str, page: int = 1, offset: int = 0) -> dict:
    """
    Khop lenh chi tiet theo tung tick trong phien hien tai.

    Args:
        code: Ma CK
        page: Trang (mac dinh 1, moi nhat)
        offset: Offset
    """
    return await _get_json(
        "technical",
        "/TimeAndSales/GetTimeAndSales",
        {"Code": code.upper(), "page": page, "offset": offset},
    )


@mcp.tool()
async def get_busd_chart(code: str) -> dict:
    """
    Bieu do ap luc mua chu dong (BU) - ban chu dong (SD) intraday.

    Args:
        code: Ma CK
    """
    return await _get_json(
        "technical",
        "/TimeAndSales/GetTimeAndSalesBuSdChart",
        {"Code": code.upper()},
    )


@mcp.tool()
async def get_watchlist() -> dict:
    """Lay danh sach watchlist da luu tren FiinTrade cua user."""
    return await _get_json("core", "/UserSetting/GetUserWatchList", {})


@mcp.tool()
async def list_tickers(include_industry: bool = True) -> dict:
    """
    Danh sach tat ca ma CK dang giao dich.

    Args:
        include_industry: True de kem phan nganh ICB
    """
    organizations = await _get_json("core", "/Master/GetListOrganization", {})
    result = {"organizations": organizations}
    if include_industry:
        result["industries"] = await _get_json(
            "core", "/Master/GetAllIcbIndustry", {}
        )
    return result


@mcp.tool()
async def get_hot_news(language: str = "vi") -> dict:
    """
    Tin tuc nong tu FiinTrade.

    Args:
        language: 'vi' | 'en'
    """
    return await _get_json(
        "core", "/UtilFeature/GetHotNews", {"language": language}
    )


# ============================================================
# GROUP B — EXCEL DOWNLOAD (FULL HISTORY)
# ============================================================
# Pattern: GET technical.fiintrade.vn/PriceData/DownloadPriceData
#          ?Code=X&Frequently=Daily&PageSize=2000&Screen=<TYPE>
# 1 request -> toan bo lich su (~2000 phien ~ 8 nam) tra ve Excel.
# ============================================================

@mcp.tool()
async def download_investor_history(code: str, page_size: int = 2000) -> dict:
    """
    *** TOOL QUAN TRONG NHAT *** - phan tich dong tien theo nhom NDT.

    Tra ve full lich su (mac dinh 2000 phien ~ 8 nam) gom:
    - Gia dong cua, % thay doi
    - KL khop rong (Ca nhan / To chuc / Tu doanh / Nuoc ngoai)
    - GT khop rong (Ca nhan / To chuc / Tu doanh / Nuoc ngoai)

    Dung de phat hien accumulation/distribution, divergence smart money,
    track theo dau ca map theo tung phien.

    Args:
        code: Ma CK
        page_size: So phien (mac dinh 2000)
    """
    content = await _download_excel(
        "technical",
        "/PriceData/DownloadPriceData",
        {
            "Code": code.upper(),
            "Frequently": "Daily",
            "From": "",
            "To": "",
            "Page": 1,
            "PageSize": page_size,
            "Screen": "StatisticByInvestor",
        },
    )
    df = _parse_fiintrade_excel(content)
    return _df_to_response(df, code)


@mcp.tool()
async def download_price_overview(code: str, page_size: int = 2000) -> dict:
    """
    Excel tong hop gia: OHLCV + foreign net + thong ke khop lenh, full history.

    Args:
        code: Ma CK
        page_size: So phien (mac dinh 2000)
    """
    content = await _download_excel(
        "technical",
        "/PriceData/DownloadPriceData",
        {
            "Code": code.upper(),
            "Frequently": "Daily",
            "From": "",
            "To": "",
            "Page": 1,
            "PageSize": page_size,
            "Screen": "Overview",
        },
    )
    df = _parse_fiintrade_excel(content)
    return _df_to_response(df, code)


@mcp.tool()
async def download_order_statistics(code: str, page_size: int = 2000) -> dict:
    """
    Excel thong ke dat lenh full history (so lenh dat mua/ban, KL/gia tri
    trung binh moi lenh, ap luc mua/ban...).

    Huu ich de phat hien big orders va su thay doi cuong do dat lenh.

    Args:
        code: Ma CK
        page_size: So phien (mac dinh 2000)
    """
    content = await _download_excel(
        "technical",
        "/PriceData/DownloadPriceData",
        {
            "Code": code.upper(),
            "Frequently": "Daily",
            "From": "",
            "To": "",
            "Page": 1,
            "PageSize": page_size,
            "Screen": "OrderStatistic",
        },
    )
    df = _parse_fiintrade_excel(content)
    return _df_to_response(df, code)


@mcp.tool()
async def download_time_sales(code: str) -> dict:
    """
    Excel Time & Sales chi tiet khop lenh tung tick.

    Args:
        code: Ma CK
    """
    content = await _download_excel(
        "technical",
        "/TimeAndSales/DownloadTimeAndSales",
        {"Code": code.upper()},
    )
    df = _parse_fiintrade_excel(content)
    return _df_to_response(df, code)


# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    # Streamable-HTTP transport cho deploy Railway
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
