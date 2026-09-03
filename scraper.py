import asyncio
import json
import os
from urllib.parse import quote_plus
from typing import List, Dict, Any

from playwright.async_api import async_playwright, Page
from google import genai

# Yeni Google GenAI API Yapılandırması
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    client = None

SEARCH_TERMS = [
    "FinTech internship",
    "LegalTech internship",
    "Data Analytics internship",
    "Data Analyst internship",
    "Business Analyst internship",
    "Compliance Intern",
    "Risk Management Intern",
    "Financial Crime Compliance (FCC) Intern",
    "Investment Research Working Student",
    "Strategy Intern",
    "Corporate Finance Working Student",
    "Business Development Intern",
]

def build_linkedin_jobs_url(term: str, location: str = "Switzerland") -> str:
    keyword = quote_plus(term)
    loc = quote_plus(location)
    return f"https://ch.linkedin.com/jobs/search?keywords={keyword}&location={loc}&f_TPR=r2592000"

async def scroll_jobs_page(page: Page, rounds: int = 5) -> None:
    for _ in range(rounds):
        await page.mouse.wheel(0, 1000)
        await page.wait_for_timeout(1000)

async def evaluate_job_with_gemini(title: str, company: str) -> str:
    if not client:
        return "Değerlendirme kapalı (API Key yok)"
        
    prompt = f"""
    Sen kıdemli bir İK asistanısın. Aday profili: İsviçre'de yaşayan, Hukuk geçmişine sahip, 
    LUMACSS (Computational Social Sciences) yüksek lisansı yapan, FinTech, LegalTech ve Veri Analizi 
    (Python, R, SQL) alanlarında yetkin bir araştırmacı ve stajyer adayı.
    
    İlan Başlığı: {title}
    Şirket: {company}
    
    Bu ilan adayın profiline uygun mu? Sadece 1 ile 10 arası bir puan ver ve tek cümlelik somut bir sebep yaz.
    Format: [Puan]/10 - [Sebep]
    """
    try:
        # YENİ KÜTÜPHANE ÇAĞRISI BURASI
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        return f"Hata: {e}"

async def extract_jobs(page: Page) -> List[Dict[str, Any]]:
    jobs = []
    cards = await page.query_selector_all(".base-card")
    
    for card in cards[:10]: 
        try:
            title_el = await card.query_selector(".base-search-card__title")
            title = await title_el.inner_text() if title_el else ""
            
            company_el = await card.query_selector(".base-search-card__subtitle")
            company = await company_el.inner_text() if company_el else ""
            
            location_el = await card.query_selector(".job-search-card__location")
            location = await location_el.inner_text() if location_el else ""
            
            link_el = await card.query_selector("a.base-card__full-link")
            link = await link_el.get_attribute("href") if link_el else ""
            
            if link and "?" in link:
                link = link.split("?")[0] 

            if title.strip():
                jobs.append({
                    "title": title.strip(),
                    "company": company.strip(),
                    "location": location.strip(),
                    "link": link
                })
        except Exception as e:
            continue
            
    return jobs

def dedupe_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for job in jobs:
        key = (job.get("title", ""), job.get("company", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(job)
    return result

async def main():
    all_jobs = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        
        print("Bot çalıştırılıyor. İlanlar taranıyor...\n")
        
        for term in SEARCH_TERMS:
            print(f"Aranıyor: {term}")
            await page.goto(build_linkedin_jobs_url(term), wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            await scroll_jobs_page(page)
            
            extracted = await extract_jobs(page)
            all_jobs.extend(extracted)
            
        await browser.close()
        
    unique_jobs = dedupe_jobs(all_jobs)
    print(f"\nToplam {len(unique_jobs)} benzersiz ilan bulundu. Gemini analiz ediyor...\n")
    print("-" * 50)
    
    final_results = []
    for job in unique_jobs:
        score = await evaluate_job_with_gemini(job['title'], job['company'])
        job['ai_score'] = score
        final_results.append(job)
        
        print(f"Pozisyon: {job['title']} | Şirket: {job['company']}")
        print(f"Değerlendirme: {score}")
        print("-" * 50)
        
    with open("jobs_output.json", "w", encoding="utf-8") as f:
        json.dump(final_results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
