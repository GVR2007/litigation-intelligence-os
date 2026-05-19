"""Inspect HTML structure of all scraping sources."""
import requests
import re
import json

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'}

# ── 1. ITATONLINE ─────────────────────────────────────────────────────────────
print("=" * 70)
print("1. ITATONLINE.ORG")
print("=" * 70)
r = requests.get('https://itatonline.org/archives/page/2/', headers=headers, timeout=15)
html = r.text
print(f"Status: {r.status_code} | Length: {len(html):,}")

# Entry titles + URLs
titles = re.findall(r'class=["\']entry-title["\'][^>]*>.*?<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL)
print(f"\nArticle count: {len(titles)}")

# Get full first article block
start = html.find('<article')
end = html.find('</article>') + 10
article_block = html[start:end]

# Extract key fields from URL slugs
for url, title in titles[:3]:
    title_clean = re.sub(r'<[^>]+>', '', title).strip()
    slug = url.split('/archives/')[-1].rstrip('/')

    # Extract sections from slug (pattern: -s-269ss- or -section-269-ss-)
    sec_matches = re.findall(r'\b(?:s|section)[_-](\w+)', slug, re.IGNORECASE)

    # Extract court from title
    court_m = re.search(r'\((.*?)\)\s*$', title_clean)
    court = court_m.group(1) if court_m else ''

    # Key ratio = everything after "court" in slug
    ratio_part = slug.replace('-', ' ').strip()
    print(f"\n  Title: {title_clean[:70]}")
    print(f"  Court: {court}")
    print(f"  URL:   {url[:80]}")
    print(f"  Ratio: {ratio_part[len(title_clean)//3:][:120]}")

# Find date patterns
dates = re.findall(r'datetime=["\']([^"\']+)["\']', html)
print(f"\n  Sample dates: {dates[:3]}")

# Find any structured metadata
meta = re.findall(r'<strong>(.*?)</strong>\s*:?\s*(.*?)(?:<|$)', html)
print(f"\n  Meta fields (strong tags): {meta[:5]}")

# ── 2. TAXGURU ────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("2. TAXGURU.IN — ITAT JUDGMENTS")
print("=" * 70)
r2 = requests.get('https://taxguru.in/income-tax/page/1/?cat=itat-judgments', headers=headers, timeout=15)
html2 = r2.text
print(f"Status: {r2.status_code} | Length: {len(html2):,}")

titles2 = re.findall(r'class=["\']entry-title["\'][^>]*>.*?<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html2, re.DOTALL)
if not titles2:
    titles2 = re.findall(r'<h[23][^>]*>.*?<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>.*?</h[23]>', html2, re.DOTALL)
print(f"Article count: {len(titles2)}")
for url, title in titles2[:5]:
    title_clean = re.sub(r'<[^>]+>', '', title).strip()
    print(f"  - {title_clean[:80]}")
    print(f"    {url[:80]}")

dates2 = re.findall(r'datetime=["\']([^"\']+)["\']', html2)
print(f"  Dates: {dates2[:3]}")

# ── 3. TAXSCAN ────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("3. TAXSCAN.IN")
print("=" * 70)
r3 = requests.get('https://www.taxscan.in/income-tax/page/2/', headers=headers, timeout=15)
html3 = r3.text
print(f"Status: {r3.status_code} | Length: {len(html3):,}")

titles3 = re.findall(r'<a\s+href=["\']([^"\']*taxscan\.in/top-stories/[^"\']+)["\'][^>]*>(.*?)</a>', html3, re.DOTALL)
if not titles3:
    titles3 = re.findall(r'<h[23][^>]*>.*?<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>.*?</h[23]>', html3, re.DOTALL)
print(f"Article count: {len(titles3)}")
for url, title in titles3[:5]:
    title_clean = re.sub(r'<[^>]+>', '', title).strip()
    if title_clean:
        print(f"  - {title_clean[:80]}")
        print(f"    {url[:80]}")

# ── 4. TAXSCAN RSS ────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("4. TAXSCAN RSS FEED")
print("=" * 70)
r4 = requests.get('https://www.taxscan.in/feed/', headers=headers, timeout=15)
print(f"Status: {r4.status_code} | Length: {len(r4.text):,}")
if r4.status_code == 200:
    items = re.findall(r'<item>(.*?)</item>', r4.text, re.DOTALL)
    print(f"RSS items: {len(items)}")
    for item in items[:3]:
        title = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', item)
        link = re.search(r'<link>(.*?)</link>', item)
        date = re.search(r'<pubDate>(.*?)</pubDate>', item)
        if title:
            print(f"  - {title.group(1)[:80]}")
            if link: print(f"    {link.group(1)[:80]}")
            if date: print(f"    {date.group(1)[:40]}")

# ── 5. ITATONLINE RSS ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("5. ITATONLINE RSS FEED")
print("=" * 70)
r5 = requests.get('https://itatonline.org/archives/feed/', headers=headers, timeout=15)
print(f"Status: {r5.status_code} | Length: {len(r5.text):,}")
if r5.status_code == 200:
    items = re.findall(r'<item>(.*?)</item>', r5.text, re.DOTALL)
    print(f"RSS items: {len(items)}")
    for item in items[:3]:
        title = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>', item)
        link = re.search(r'<link>(.*?)</link>', item)
        date = re.search(r'<pubDate>(.*?)</pubDate>', item)
        desc = re.search(r'<description><!\[CDATA\[(.*?)\]\]>', item, re.DOTALL)
        t = title.group(1) or title.group(2) if title else ''
        print(f"  - {t[:80]}")
        if link: print(f"    {link.group(1)[:80]}")
        if desc:
            d = re.sub(r'<[^>]+>', '', desc.group(1)).strip()[:200]
            print(f"    Desc: {d}")

# ── 6. TAXGURU RSS ────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("6. TAXGURU RSS FEED")
print("=" * 70)
r6 = requests.get('https://taxguru.in/feed/', headers=headers, timeout=15)
print(f"Status: {r6.status_code} | Length: {len(r6.text):,}")
if r6.status_code == 200:
    items = re.findall(r'<item>(.*?)</item>', r6.text, re.DOTALL)
    print(f"RSS items: {len(items)}")
    for item in items[:5]:
        title = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>', item)
        link = re.search(r'<link>(.*?)</link>', item)
        cats = re.findall(r'<category><!\[CDATA\[(.*?)\]\]></category>', item)
        t = (title.group(1) or title.group(2)) if title else ''
        print(f"  - {t[:80]}")
        print(f"    cats: {cats[:3]}")
        if link: print(f"    {link.group(1)[:80]}")

print("\nDONE.")
