# Nairaland Thread Scraper (Playwright)

Scrapes Nairaland threads into a CSV (`hierarchy_reading_view.csv`) with columns:
`PostID, ReplyToPostID, Username, Timestamp, Content, Likes, Shares`.

Uses **Playwright (Chromium)** to behave like a real browser and bypass bot checks.

## Prerequisites
- Python 3.9+
- Works best **locally** (VPN off). Datacenter IPs are more likely to be blocked.

## Setup
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium

