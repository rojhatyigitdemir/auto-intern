import asyncio
import json
import os
import requests
from urllib.parse import quote_plus
from typing import List, Dict, Any

from playwright.async_api import async_playwright, Page
from google import genai

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

SEEN_JOBS_FILE = "seen_jobs.json"

def load_seen_jobs() -> set:
    if os.path.exists(SEEN_JOBS_FILE):
        try:
            with open(SEEN_JOBS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen_jobs(seen_jobs: set):
    with open(SEEN_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_jobs), f, ensure_ascii=False, indent=2)

def build_linkedin_jobs_url(term: str, location: str = "Switzerland") -> str:
    keyword = quote_plus(term)
    loc = quote_plus(location)
    return f"https://ch.linkedin.com/jobs/search?keywords={keyword}&location={loc}&f_TPR=r2592000"

async def scroll_jobs_page(page: Page, rounds: int = 5) -> None:
    for _ in range(rounds):
        await page.mouse.wheel(0, 1000)
        await page.wait_for_timeout(1000)

def send_telegram_message(message: str):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram hatası: {e}")

async def evaluate_job_with_gemini(title: str, company: str) -> str:
    if not client:
        return "Değerlendirme kapalı (API Key yok)"
        
    prompt = f"""
    Sen kıdemli bir İK asistanısın. Aday profili: İsviçre'de yaşayan, Hukuk geçmişine sahip, 
    LUMACSS (Computational Social Sciences) yüksek lisansı yapan, FinTech, LegalTech ve Veri Analizi 
    (Python, R, SQL) alanlarında yetkin bir araştırmacı ve stajyer adayı.
    
    KATI ELEME KURALLARI (BU KURALLARA UYMAYAN İLANLARA KESİNLİKLE 1-4 ARASI PUAN VER):
    1. DİL KURALI: İlan başlığı veya yapısı Almanca olan işleri (örneğin 'Mitarbeiter/in', 'Rechtsanwältin', 'Fachmitarbeiter' vb.) KESİNLİKLE REDDET. Sadece İngilizce (veya uluslararası) profil arayanlara yüksek puan ver.
    2. ÇALIŞMA ORANI KURALI: Normal/Standart tam zamanlı (%100) işleri KESİNLİKLE REDDET. SADECE yarı zamanlı (örneğin %60-%80) pozisyonları VEYA başlığında açıkça "Intern", "Internship", "Trainee", "Working Student", "Praktikum" yazan %100 staj/öğrenci pozisyonlarını kabul et.
    
    İlan Başlığı: {title}
    Şirket: {company}
    
    Bu ilan adayın profiline uygun mu? Yukarıdaki kurallara göre sadece 1 ile 10 arası bir puan ver ve tek cümlelik somut bir sebep yaz.
    Format: [Puan]/10 - [Sebep]
    """
    try:
        # En güncel ve hatasız çalışan modeli kullanıyoruz
        response = client.models.generate_content(
            model='gemini-2.0-flash',
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
    
    seen_jobs = load_seen_jobs()
    new_jobs_found = False
    
    print(f"\nToplam {len(unique_jobs)} ilan bulundu. Hafıza kontrol ediliyor...\n")
    print("-" * 50)
    
    final_results = []
    for job in unique_jobs:
        job_id = f"{job['title']} | {job['company']}"
        
        if job_id in seen_jobs:
            continue
            
        score_text = await evaluate_job_with_gemini(job['title'], job['company'])
        job['ai_score'] = score_text
        final_results.append(job)
        
        print(f"YENİ İLAN! Pozisyon: {job['title']} | Şirket: {job['company']}")
        print(f"Değerlendirme: {score_text}")
        print("-" * 50)
        
        if any(f"{i}/10" in score_text for i in [7, 8, 9, 10]):
            msg = f"🚀 <b>Yeni Uygun Staj Bulundu!</b>\n\n"
            msg += f"📌 <b>Pozisyon:</b> {job['title']}\n"
            msg += f"🏢 <b>Şirket:</b> {job['company']}\n"
            msg += f"📍 <b>Konum:</b> {job['location']}\n\n"
            msg += f"🤖 <b>Yapay Zeka Yorumu:</b> {score_text}\n\n"
            msg += f"🔗 <a href='{job['link']}'>İlana Git</a>"
            
            send_telegram_message(msg)
            
        seen_jobs.add(job_id)
        new_jobs_found = True
        
    if new_jobs_found:
        save_seen_jobs(seen_jobs)
        print("\nHafıza güncellendi!")
    else:
        print("\nYeni bir ilan bulunamadı.")

if __name__ == "__main__":
    asyncio.run(main())
