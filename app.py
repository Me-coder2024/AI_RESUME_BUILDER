import os
import json
import subprocess
import time
import base64
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv
import google.generativeai as genai
from analyzer import process_experience_with_gemini, process_projects_with_gemini, process_skills_with_gemini

load_dotenv()

app = Flask(__name__)
CORS(app)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')

# In-memory storage for user data
user_sessions = {}

system_instruction = """
You are a helpful assistant guiding a user through building their resume.
Your goal is to collect their: Name, Phone Number, Email, LinkedIn Profile URL, and GitHub Profile URL.
You may also ask if they have any custom projects to add (Name, Description, Link).
Only ask for one thing at a time to keep it conversational. 
Be polite and professional.
When you are absolutely sure you have collected: Name, Phone, Email, LinkedIn, and GitHub, 
you must output exactly this JSON object structure and NOTHING ELSE:
```json
{
  "name": "their name",
  "phone": "their phone",
  "email": "their email",
  "linkedin": "their linkedin",
  "github": "their github",
  "custom_projects": [
     {"name": "proj", "description": "desc", "link": "url"}
  ]
}
```
If they don't want to add custom projects, output the JSON with an empty list.
Do not output the JSON until you have all 5 required fields.
"""


# Define the conversation flow
conversation_states = [
    "name",
    "phone",
    "email",
    "linkedin",
    "github",
    "ask_add_project"
]

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        session_id = data.get('session_id', 'default')
        user_message = data.get('message', '').strip()

        if session_id not in user_sessions:
            chat_session = model.start_chat(history=[
                {"role": "user", "parts": [system_instruction]},
                {"role": "model", "parts": ["Understood. I will help the user build their resume and output JSON when done."]}
            ])
            user_sessions[session_id] = {
                "chat": chat_session,
                "is_done": False,
                "data": None
            }

        session = user_sessions[session_id]
        
        if session["is_done"]:
            return jsonify({
                "response": "Starting automation...",
                "trigger_automation": True,
                "session_data": session["data"]
            })

        # Send user message to Gemini
        response = session["chat"].send_message(user_message)
        text = response.text.strip()
        
        # Check if the model decided to output the final JSON
        if "```json" in text or (text.startswith('{') and text.endswith('}')):
            try:
                json_str = text
                if "```json" in json_str:
                    json_str = json_str.split("```json")[-1].split("```")[0].strip()
                elif "```" in json_str:
                    json_str = json_str.split("```")[-1].split("```")[0].strip()
                
                parsed_data = json.loads(json_str)
                session["is_done"] = True
                session["data"] = parsed_data
                
                return jsonify({
                    "response": "Thank you! I have everything I need. Starting automation...",
                    "trigger_automation": True,
                    "session_data": parsed_data
                })
            except Exception as e:
                print(f"Failed to parse model JSON output: {e}")
                # Fallback to just returning the text if JSON parsing fails, though it shouldn't
                pass

        return jsonify({
            "response": text,
            "trigger_automation": False,
            "session_data": None
        })

    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/automate', methods=['POST'])
def automate():
    session_data = request.json
    github_user = session_data.get('github')
    linkedin_url = session_data.get('linkedin')

    if not github_user or not linkedin_url:
        return jsonify({"error": "Missing GitHub or LinkedIn info"}), 400

    # Clean github username if link was provided
    if "github.com/" in github_user:
        github_user = github_user.split("github.com/")[-1].strip("/")

    print(f"Running scraper for {github_user} and {linkedin_url}")
    
    try:
        # Run the existing scraper script
        result = subprocess.run(
            ['python', 'scraper.py', github_user, linkedin_url],
            capture_output=True, text=True, check=True
        )
        
        # Load the scraped data
        with open('scraped_data.json', 'r') as f:
            scraped_data = json.load(f)
            
        # Analyze with Gemini mapping
        print("Processing experiences with Gemini...")
        if 'linkedin' in scraped_data and 'experience' in scraped_data['linkedin']:
            scraped_data['linkedin']['experience'] = process_experience_with_gemini(scraped_data['linkedin']['experience'])
        
        print("Processing projects with Gemini...")
        if 'github' in scraped_data and 'projects' in scraped_data['github']:
             scraped_data['github']['projects'] = process_projects_with_gemini(scraped_data['github']['projects'])
             
        if 'custom_projects' in session_data:
             session_data['custom_projects'] = process_projects_with_gemini(session_data['custom_projects'])
             
        print("Processing skills with Gemini...")
        if 'final_skills' in scraped_data:
             scraped_data['categorized_skills'] = process_skills_with_gemini(scraped_data['final_skills'])
            
        # Fill the template
        generate_resume(scraped_data, session_data)
        
        print("Converting HTML to PDF...")
        generate_pdf_from_html('final_resume.html', 'final_resume.pdf')
        
        return jsonify({"status": "success", "message": "Resume generated successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def generate_resume(scraped_data, session_data):
    # Load template
    with open('resume_template.html', 'r', encoding='utf-8') as f:
        template = f.read()

    gh_profile = scraped_data.get('github', {})
    li_profile = scraped_data.get('linkedin', {})

    name = session_data.get('name') or gh_profile.get('name') or li_profile.get('name') or "Your Name"
    phone = session_data.get('phone') or "Your Phone"
    email = session_data.get('email') or "Your Email"
    linkedin_url = session_data.get('linkedin') or li_profile.get('headline', 'LinkedIn Profile')
    github_url = session_data.get('github') or f"github.com/{gh_profile.get('name', 'profile')}"

    # Simple placeholder replacement logic
    replacements = {
        "{name}": name,
        "{phone_number}": phone,
        "{email}": email,
        "{linkedin_url}": linkedin_url,
        "{github_url}": github_url,
    }

    # Replace Experience
    experience_html = ""
    for exp in li_profile.get('experience', []):
        parts = exp.split(' | ')
        title = parts[0] if len(parts) > 0 else "Experience"
        company = parts[1] if len(parts) > 1 else ""
        date = parts[4] if len(parts) > 4 else ""
        desc = " ".join(parts[5:]) if len(parts) > 5 else ""
        
        # Gemini has already returned nicely formatted HTML inside the bullet points for `desc`
        experience_html += f"""
        <div class="item">
            <div class="item-header">
                <span class="item-name">{title}</span>
                <span class="item-date">{date}</span>
            </div>
            <div class="item-sub-header">
                <span>{company}</span>
            </div>
            {desc}
        </div>
        """
    
    if experience_html:
        import re
        template = re.sub(r'(<section id="experience">.*?)<h2>Experience</h2>.*?<section id="projects">', 
                          r'\1<h2>Experience</h2>' + experience_html + '<section id="projects">', 
                          template, flags=re.DOTALL)

    # Replace Education
    education_html = ""
    for edu in li_profile.get('education', []):
        parts = edu.split(' | ')
        school = parts[0] if len(parts) > 0 else "University"
        degree = parts[2] if len(parts) > 2 else ""
        date = parts[4] if len(parts) > 4 else ""
        
        education_html += f"""
        <div class="item">
            <div class="item-header">
                <span class="item-name">{school}</span>
                <span class="item-date">{date}</span>
            </div>
            <div class="item-sub-header">
                <span>{degree}</span>
            </div>
        </div>
        """
    if education_html:
        import re
        template = re.sub(r'(<section id="education">.*?)<h2>Education</h2>.*?<section id="experience">', 
                          r'\1<h2>Education</h2>' + education_html + '<section id="experience">', 
                          template, flags=re.DOTALL)

    # Replace Projects
    projects_html = ""
    
    # 1. Top 3 from GitHub
    gh_projects = gh_profile.get('projects', [])
    try:
        gh_projects.sort(key=lambda x: int(x.get('stars', '0').replace(',', '') if str(x.get('stars', '')).replace(',', '').isdigit() else 0), reverse=True)
    except Exception:
        pass

    for p in gh_projects[:3]:
        # Formulate date display
        start = p.get('created_at', '')
        end = p.get('pushed_at', '')
        date_display = f"{start} - {end}" if start and end else "Dates Unavailable"
        
        # Determine language info
        lang = p.get('language', '')
        lang_display = f" | <i>{lang}</i>" if lang else ""
        
        experience_desc = p.get('description') or '<ul><li>No description provided.</li></ul>'
        if not str(experience_desc).startswith("<ul>"):
             experience_desc = f"<ul><li>{experience_desc}</li></ul>"
             

        projects_html += f"""
        <div class="item">
            <div class="item-header">
                <span class="item-name"><a href="{p.get('url', '#')}">{p.get('name', 'Project')}</a>{lang_display}</span>
                <span class="item-date">{date_display}</span>
            </div>
            {experience_desc}
        </div>
        """

    # 2. Add 1 extra custom project from user input
    custom_projects = session_data.get('custom_projects', [])
    if custom_projects and len(custom_projects) > 0:
        cp = custom_projects[0]
        
        desc = cp.get('description', 'No description provided.')
        if not str(desc).startswith("<ul>"):
            desc = f"<ul><li>{desc}</li></ul>"
            
        projects_html += f"""
        <div class="item">
            <div class="item-header">
                <span class="item-name">{cp.get('name', 'Custom Project')}</span>
                <span class="item-date"><a href="{cp.get('link', '#')}">Link</a></span>
            </div>
            {desc}
        </div>
        """

    if projects_html:
        import re
        template = re.sub(r'(<section id="projects">.*?)<h2>Projects</h2>.*?<section id="skills">', 
                          r'\1<h2>Projects</h2>' + projects_html + '<section id="skills">', 
                          template, flags=re.DOTALL)

    # Replace Skills
    categorized_skills = scraped_data.get('categorized_skills', {})
    skills_html = ""
    for category, skills in categorized_skills.items():
        if skills:
            skills_html += f"<p><b>{category}:</b> {', '.join(skills)}</p>"
    
    if not skills_html:
         # Fallback
         skills_list = scraped_data.get('final_skills', [])
         skills_html = f"<p><b>Skills:</b> {', '.join(skills_list)}</p>"
         
    import re
    template = re.sub(r'(<section id="skills">.*?)<h2>Technical Skills</h2>.*?</div>', 
                      r'\1<h2>Technical Skills</h2><div class="skills-container">' + skills_html + '</div>', 
                      template, flags=re.DOTALL)

    for key, val in replacements.items():
        template = template.replace(key, str(val))

    with open('final_resume.html', 'w', encoding='utf-8') as f:
        f.write(template)

def generate_pdf_from_html(html_path, output_pdf_path):
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    abs_path = os.path.abspath(html_path)
    # Using file:/// for local URLs on windows
    driver.get(f"file:///{abs_path.replace(chr(92), '/')}")
    
    # Allow some time for fonts to load or dynamic rendering 
    time.sleep(2)
    
    print_options = {
        'printBackground': True,
        'marginTop': 0,
        'marginBottom': 0,
        'marginLeft': 0,
        'marginRight': 0
    }
    
    pdf = driver.execute_cdp_cmd("Page.printToPDF", print_options)
    
    with open(output_pdf_path, 'wb') as f:
        f.write(base64.b64decode(pdf['data']))
        
    driver.quit()

@app.route('/download', methods=['GET'])
def download():
    return send_file('final_resume.pdf', as_attachment=True, download_name='AI_Resume.pdf')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
