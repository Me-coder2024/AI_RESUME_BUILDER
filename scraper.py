import os
import requests
import json
import time
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# Load environment variables
if os.path.exists(".env"):
    load_dotenv(".env")
elif os.path.exists(".env.example"):
    print("Warning: .env not found, using .env.example for credentials")
    load_dotenv(".env.example")
else:
    load_dotenv()

class ResumeScraper:
    def __init__(self):
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.linkedin_email = os.getenv("LINKEDIN_EMAIL")
        self.linkedin_password = os.getenv("LINKEDIN_PASSWORD")

    def scrape_github(self, username):
        print(f"Scraping GitHub for {username}...")
        headers = {}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
        
        # User profile
        profile_url = f"https://api.github.com/users/{username}"
        profile_resp = requests.get(profile_url, headers=headers)
        if profile_resp.status_code != 200:
            return {"error": f"GitHub user not found or API limit reached ({profile_resp.status_code})"}
        
        profile_data = profile_resp.json()
        
        # Repositories
        repos_url = f"https://api.github.com/users/{username}/repos?sort=updated&per_page=10"
        repos_resp = requests.get(repos_url, headers=headers)
        repos_data = repos_resp.json() if repos_resp.status_code == 200 else []

        projects = []
        languages = set()
        for repo in repos_data:
            if not repo["fork"]:
                projects.append({
                    "name": repo["name"],
                    "description": repo["description"],
                    "url": repo["html_url"],
                    "stars": repo["stargazers_count"],
                    "language": repo["language"],
                    "created_at": repo.get("created_at", "").split("T")[0] if repo.get("created_at") else "",
                    "pushed_at": repo.get("pushed_at", "").split("T")[0] if repo.get("pushed_at") else ""
                })
                if repo["language"]:
                    languages.add(repo["language"])

        return {
            "name": profile_data.get("name"),
            "bio": profile_data.get("bio"),
            "location": profile_data.get("location"),
            "public_repos": profile_data.get("public_repos"),
            "projects": projects,
            "skills": list(languages)
        }

    def scrape_linkedin(self, profile_url):
        if not self.linkedin_email or not self.linkedin_password:
            return {"error": "LinkedIn credentials (LINKEDIN_EMAIL, LINKEDIN_PASSWORD) missing in .env"}

        print(f"Scraping LinkedIn for {profile_url}...")
        
        chrome_options = Options()
        chrome_options.add_argument("--headless") # Comment out for debugging
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-notifications")
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        try:
            # Login
            driver.get("https://www.linkedin.com/login")
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "username"))).send_keys(self.linkedin_email)
            driver.find_element(By.ID, "password").send_keys(self.linkedin_password)
            driver.find_element(By.XPATH, "//button[@type='submit']").click()
            
            # Wait for login to complete
            time.sleep(5) 
            
            # Navigate to profile
            driver.get(profile_url)
            time.sleep(5) # Give it time to load dynamic content
            
            # Scroll down to trigger lazy loading of education/experience
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
            time.sleep(2)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

            soup = BeautifulSoup(driver.page_source, "html.parser")
            
            # Basic info
            name_elem = soup.find("h1", class_="text-heading-xlarge") or soup.find("h1", class_="vcard-detail-primary__headline")
            name = name_elem.get_text(strip=True) if name_elem else "Unknown"
            
            headline_elem = soup.find("div", class_="text-body-medium") or soup.find("div", class_="vcard-detail-primary__sub-text")
            headline = headline_elem.get_text(strip=True) if headline_elem else ""

            # Experience section
            experience = []
            exp_section = soup.find("div", id="experience")
            if exp_section:
                list_items = exp_section.find_parent("section").find_all("li", class_="artdeco-list__item")
                for item in list_items:
                    text = item.get_text(separator=" | ", strip=True)
                    experience.append(text)

            # Education section
            education = []
            edu_section = soup.find("div", id="education")
            if edu_section:
                list_items = edu_section.find_parent("section").find_all("li", class_="artdeco-list__item")
                for item in list_items:
                    text = item.get_text(separator=" | ", strip=True)
                    education.append(text)

            # Skills section
            skills = []
            print("Extracting skills...")
            
            # Navigate to deeper skills page for comprehensive extraction
            skills_url = profile_url.rstrip("/") + "/details/skills/"
            try:
                driver.get(skills_url)
                time.sleep(5)
                
                # Scroll multiple times to trigger lazy loading
                for _ in range(2):
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1)
                
                skills_soup = BeautifulSoup(driver.page_source, "html.parser")
                
                # The most reliable selector for the skill names themselves inside the list items
                skill_tags = skills_soup.find_all("div", class_="display-flex align-items-center mr1 hoverable-link-text")
                for tag in skill_tags:
                    s_name_elem = tag.find("span", {"aria-hidden": "true"}) or tag
                    s_name = s_name_elem.get_text(strip=True)
                    
                    if s_name and len(s_name) < 50:
                        s_lower = s_name.lower()
                        is_noise = any(x in s_lower for x in ["(he/him)", "(she/her)", "profile", "linkedin", "skill", "unknown"])
                        is_name = name.lower() in s_lower or s_lower in name.lower()
                        
                        if not is_noise and not is_name:
                            skills.append(s_name)
                
                if not skills:
                    skill_tags = skills_soup.find_all("div", class_="artdeco-entity-lockup__title")
                    for tag in skill_tags:
                        s_name = tag.get_text(strip=True)
                        if s_name and len(s_name) < 40 and name.lower() not in s_name.lower():
                            skills.append(s_name)

            except Exception as e:
                print(f"Details skills page failed: {e}")

            return {
                "name": name,
                "headline": headline,
                "experience": experience,
                "education": education,
                "skills": sorted(list(set(skills))) 
            }

        except Exception as e:
            return {"error": f"LinkedIn scraping failed: {str(e)}"}
        finally:
            driver.quit()

if __name__ == "__main__":
    # Example usage
    import sys
    if len(sys.argv) < 3:
        print("Usage: python scraper.py [github_username] [linkedin_url]")
    else:
        scraper = ResumeScraper()
        gh_data = scraper.scrape_github(sys.argv[1])
        li_data = scraper.scrape_linkedin(sys.argv[2])
        
        # Merge skills
        gh_skills = gh_data.get("skills", [])
        li_skills = li_data.get("skills", [])
        
        # Combined and deduplicated list (case-insensitive deduplication)
        combined_skills_map = {}
        for s in gh_skills + li_skills:
            if s:
                combined_skills_map[s.lower()] = s
        
        final_skills = sorted(list(combined_skills_map.values()))

        combined_data = {
            "github": gh_data,
            "linkedin": li_data,
            "final_skills": final_skills,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        with open("scraped_data.json", "w") as f:
            json.dump(combined_data, f, indent=4)
        
        print(f"Data saved to scraped_data.json. Total skills: {len(final_skills)}")
