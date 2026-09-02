import asyncio
import json
import os
from urllib.parse import quote_plus
from typing import List, Dict, Any

from playwright.async_api import async_playwright, Page

LINKEDIN_USERNAME = os.getenv("LINKEDIN_USERNAME")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD")

SEARCH_TERMS = [
    "FinTech internship",
    "LegalTech internship",
    "Data Analytics internship",
    "Data Analyst internship",
    "Business Analyst internship",
]

def build_linkedin_jobs_url(term: str, location: str = "Switzerland") -> str:
    # İsviçre lokasyonunu ve zaman filtresini ekliyoruz.
    keyword = quote_plus(term)
    loc = quote_plus(location)
    return (
        "https://www.linkedin.com/jobs/search/?keywords="
        f"{keyword}&location={loc}"
        "&geoId=102885843"
        "&f_WT=2"  # Ofis / remote / hybrid gibi filtreler; 2 = on-site? (kontrol edilmelidir)
        "&f_TPR=r2592000"
    )

async def login_if_needed(page: Page) -> None:
    if not LINKEDIN_USERNAME or not LINKEDIN_PASSWORD:
        print("LinkedIn kullanıcı adı/şifresi tanımlanmadı. Oturum açma atlanıyor.")
        return

    # Gerekirse oturum açma ekranı
    try:
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await page.fill("input[name='session_key']", LINKEDIN_USERNAME)
        await page.fill("input[name='session_password']", LINKEDIN_PASSWORD)
        await page.click("button[type='submit']")
        await page.wait_for_timeout(5000)
    except Exception:
        pass

async def accept_cookies_if_present(page: Page) -> None:
    try:
        # Çerez onayı butonları bazen değişir, bu alanlar genelde çalışan seçimlerdir
        selectors = [
            "button[action-type='ACCEPT']",
            "button:has-text('Accept')",
            "button:has-text('Kabul et')",
            "button:has-text('Accept cookies')",
        ]
        for selector in selectors:
            btn = page.locator(selector)
            if await btn.count() > 0:
                await btn.first.click()
                await page.wait_for_timeout(1000)
                return
    except Exception:
        pass

async def scroll_jobs_page(page: Page, rounds: int = 8) -> None:
    for _ in range(rounds):
        await page.mouse.wheel(0, 2000)
        await page.wait_for_timeout(900)

async def extract_jobs(page: Page) -> List[Dict[str, Any]]:
    jobs = []

    # LinkedIn kart listesi
    cards = page.locator("li.jobs-search-results__list-item")
    count = await cards.count()

    for i in range(count):
        card = cards.nth(i)
        if not await card.is_visible():
            continue

        try:
            title = await card.locator("h3").first.inner_text()
        except Exception:
            title = ""

        try:
            company = await card.locator("div.job-search-card__company-name").first.inner_text()
        except Exception:
            company = ""

        try:
            location = await card.locator("div.job-search-card__location").first.inner_text()
        except Exception:
            location = ""

        # "View job" linki
        href = ""
        try:
            href_el = card.locator("a[href*='/jobs/view/']").first
            href = await href_el.get_attribute("href") or ""
        except Exception:
            pass

        if href and not href.startswith("http"):
            href = "https://www.linkedin.com" + href

        if title.strip():
            jobs.append({
                "title": title.strip(),
                "company": company.strip(),
                "location": location.strip(),
                "link": href,
            })

    return jobs

def dedupe_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for job in jobs:
        key = (job.get("title", ""), job.get("company", ""), job.get("location", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(job)
    return result

async def scrape_term(term: str) -> List[Dict[str, Any]]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # headless=True de kullanılabilir
        page = await browser.new_page(viewport={"width": 1600, "height": 1200})
        await page.goto(build_linkedin_jobs_url(term), wait_until="domcontentloaded")

        await login_if_needed(page)
        await page.wait_for_timeout(3000)

        await accept_cookies_if_present(page)
        await page.wait_for_timeout(2000)

        # Yüklenmeyen sonuçlar için sayfayı biraz aşağı kaydır
        await scroll_jobs_page(page, rounds=8)

        jobs = await extract_jobs(page)
        await browser.close()
        return dedupe_jobs(jobs)

async def main():
    tasks = [scrape_term(term) for term in SEARCH_TERMS]
    results = await asyncio.gather(*tasks)

    all_jobs = []
    for item in results:
        all_jobs.extend(item)

    unique_jobs = dedupe_jobs(all_jobs)

    print(f"Toplam ilan sayısı: {len(unique_jobs)}")
    print(json.dumps(unique_jobs[:20], ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
    