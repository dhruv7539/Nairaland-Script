# pip install playwright bs4 pandas emoji
# python -m playwright install chromium
import time, random, re, html
from pathlib import Path
import pandas as pd
from bs4 import BeautifulSoup
import emoji
from playwright.sync_api import sync_playwright

# ───────── CONFIG ─────────
THREAD_URL   = "https://www.nairaland.com/8156758/bbnaija-2024-live-updates-thread"
MAX_PAGES    = 4       
HEADLESS     = False      
BASE_DELAY_S = 2.2       
PROFILE_DIR  = "nl_profile"  

def page_url(n: int) -> str:
    # nairaland paging: page 1 = base; page 2 = /1; page 3 = /2; ...
    return THREAD_URL if n == 1 else f"{THREAD_URL}/{n-1}"

# ───────── PARSERS ─────────
def parse_document(html_text: str) -> pd.DataFrame:
    soup = BeautifulSoup(html_text, "html.parser")
    table = soup.find("table", attrs={"summary": "posts"}) or soup
    rows = []
    for td in table.select('td[id^="pb"]'):
        pid_raw = td.get("id", "")
        if not pid_raw.startswith("pb"):
            continue
        post_id = int(pid_raw[2:])

        # meta row = previous <tr>
        meta_tr = td.find_parent("tr").find_previous_sibling("tr")
        meta_td = meta_tr.find("td", class_="bold l pu") if meta_tr else None

        username = "N/A"; timestamp = "N/A"
        if meta_td:
            u_tag = meta_td.find("a", class_="user")
            s_tag = meta_td.find("span", class_="s")
            if u_tag: username = u_tag.get_text(strip=True)
            if s_tag: timestamp = s_tag.get_text(" ", strip=True)

        # main content
        content_div = td.find("div", class_="narrow") or td

        # drop quotes/quoted blocks if present
        for q in content_div.find_all(["blockquote", "div"], class_=lambda c: c and "quote" in c):
            q.decompose()

        # replace emoji images by alt/title
        inner = BeautifulSoup(str(content_div), "html.parser")
        for img in inner.find_all("img"):
            alt = (img.get("alt") or "").strip().lower()
            ch  = emoji.emojize(f":{alt}:", language="alias")
            if ch.startswith(":") and ch.endswith(":"):  # unknown alias
                ch = ""
            img.replace_with(ch)

        content_text = html.unescape(inner.get_text(" ", strip=True))

        # likes & shares
        likes = shares = 0
        like_b = td.select_one(f"b#lpt{post_id}")
        if like_b:
            m = re.search(r"(\d+)", like_b.get_text(strip=True))
            if m: likes = int(m.group(1))
        share_b = td.select_one(f"b#shb{post_id}")
        if share_b:
            m = re.search(r"(\d+)", share_b.get_text(strip=True))
            if m: shares = int(m.group(1))

        # reply target (if any)
        reply_to = None
        for a in content_div.select('a[href*="/post/"]'):
            m = re.search(r"/post/(\d+)", a["href"])
            if m:
                reply_to = int(m.group(1))
                break
        if reply_to is None:
            btag = content_div.find("b")
            if btag and btag.get_text(strip=True).lower().startswith("post="):
                m = re.search(r"(\d+)", btag.get_text())
                if m: reply_to = int(m.group(1))

        rows.append({
            "PostID": post_id,
            "ReplyToPostID": reply_to,
            "Username": username,
            "Timestamp": timestamp,
            "Content": content_text,
            "Likes": likes,
            "Shares": shares
        })
    return pd.DataFrame(rows)

def build_hierarchy(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["PostID"]        = pd.to_numeric(df["PostID"], errors="coerce").astype("Int64")
    df["ReplyToPostID"] = pd.to_numeric(df["ReplyToPostID"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["PostID"]).drop_duplicates(subset=["PostID"], keep="first")

    children = {}
    for pid, parent in zip(df["PostID"], df["ReplyToPostID"]):
        key = None if pd.isna(parent) else int(parent)
        children.setdefault(key, []).append(int(pid))

    lookup = df.set_index("PostID").to_dict("index")
    out = []
    def dfs(parent, tier):
        for pid in children.get(parent, []):
            row = lookup.get(pid)
            if not row: continue
            indent = "\u00A0" * 4 * tier
            out.append({
                "Tier": tier,
                "PostID": pid,
                "Username": row["Username"],
                "Timestamp": row["Timestamp"],
                "Comment": row["Content"],
                "Likes": row["Likes"],
                "Shares": row["Shares"],
                "IndentedComment": indent + row["Content"],
            })
            dfs(pid, tier + 1)
    dfs(None, 0)
    return pd.DataFrame(out)

def detect_total_pages(html_text: str) -> int:
    """Find the highest page number by scanning links that end with /<index> where page = index+1."""
    soup = BeautifulSoup(html_text, "html.parser")
    # accept absolute or relative hrefs
    thread_tail = re.escape("/" + THREAD_URL.split("/", 3)[3])  # "/8156758/bbnaija-2024-live-updates-thread"
    max_page = 1
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(rf"{thread_tail}(?:/(\d+))?$", href)
        if m:
            idx = m.group(1)
            page_num = 1 if idx is None else int(idx) + 1
            if page_num > max_page:
                max_page = page_num
    return max_page

# ───────── SCRAPER ─────────
def scrape_with_playwright():
    user_data = Path(PROFILE_DIR); user_data.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data),
            headless=HEADLESS,                     # first run: False
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = ctx.new_page()
        page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})

        # Load page 1 and optionally auto-detect total pages
        print("[1/?] opening page 1…")
        page.goto(page_url(1), wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_selector('table[summary="posts"]', timeout=120_000)

        for _ in range(3):
            page.mouse.wheel(0, random.randint(300, 900))
            time.sleep(0.4 + random.random()*0.4)

        html1 = page.content()
        total_pages = detect_total_pages(html1) if MAX_PAGES is None else min(MAX_PAGES, detect_total_pages(html1))
        print(f"• Detected ~{total_pages} pages")

        frames = [parse_document(html1)]
        # walk the rest
        for n in range(2, total_pages + 1 if (MAX_PAGES is None) else (MAX_PAGES + 1)):
            url = page_url(n)
            print(f"[{n}/{total_pages if MAX_PAGES is None else MAX_PAGES}] {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_selector('table[summary="posts"]', timeout=120_000)
            for _ in range(2):
                page.mouse.wheel(0, random.randint(300, 900))
                time.sleep(0.3 + random.random()*0.4)
            frames.append(parse_document(page.content()))
            time.sleep(BASE_DELAY_S + random.uniform(0.4, 1.1))

        ctx.close()
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

def main():
    flat = scrape_with_playwright()
    print(f"🔹 Scraped {len(flat)} posts")
    hier = build_hierarchy(flat)
    hier = hier[hier["Comment"].astype(str).str.strip().astype(bool)]
    print(f"🔹 Filtered to {len(hier)} non-empty comments")
    hier.to_csv("hierarchy_reading_view.csv", index=False)
    print("✅ Saved hierarchy_reading_view.csv")

if __name__ == "__main__":
    main()
