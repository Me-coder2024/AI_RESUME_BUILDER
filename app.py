import os
import json
import subprocess
import time
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

app = Flask(__name__)
CORS(app)

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

def get_model():
    # Try common model names
    for name in ['models/gemini-1.5-flash', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']:
        try:
            m = genai.GenerativeModel(name)
            # Test it briefly
            m.generate_content("test")
            return m
        except Exception as e:
            print(f"Failed to load model {name}: {e}")
            continue
    # Fallback to listing
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if models:
            return genai.GenerativeModel(models[0])
    except:
        pass
    raise Exception("No suitable Gemini model found. Check API Key or permissions.")

model = get_model()
print(f"Using model: {model.model_name}")

# In-memory storage for user data (for simplicity)
user_sessions = {}

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        session_id = data.get('session_id', 'default')
        user_message = data.get('message', '')

        if session_id not in user_sessions:
            user_sessions[session_id] = {
                "history": [],
                "data": {
                    "name": None,
                    "github": None,
                    "linkedin": None,
                    "projects": None,
                    "skills": None
                },
                "status": "collecting"
            }

        session = user_sessions[session_id]
        
        # Prompt for Gemini to act as a resume assistant
        system_prompt = """
        You are an AI Resume Builder assistant. Your goal is to collect information from the user to build their resume.
        
        Required Info:
        1. Full Name
        2. GitHub Username or Profile Link
        3. LinkedIn Profile URL
        4. Notable Projects (Optional but recommended)
        5. Key Technical Skills (Optional but recommended)

        Current collected data: {session_data}

        Instructions:
        - Be friendly and professional.
        - If info is missing, ask for it politely.
        - If the user provides a link, acknowledge it.
        - Important: If the user says something like "make my resume" or "I've provided all info", and you have at least Name, GitHub, and LinkedIn, say "Starting automation...". This exact phrase triggers the scraper.
        - For everything else, chat naturally about resumes.
        """.format(session_data=json.dumps(session["data"]))

        chat_session = model.start_chat(history=session["history"])
        response = chat_session.send_message(f"{system_prompt}\n\nUser: {user_message}")
        
        # Update local history
        session["history"].append({"role": "user", "parts": [user_message]})
        session["history"].append({"role": "model", "parts": [response.text]})

        # Try to extract data using an internal Gemini call (structured output)
        extraction_prompt = f"""
        Extract resume data from this conversation history: {json.dumps(session["history"])}.
        Return ONLY a JSON object with keys: name, github, linkedin, projects, skills. 
        If not found, use null.
        """
        try:
            extraction_resp = model.generate_content(extraction_prompt)
            # Simple extraction from the response text
            txt = extraction_resp.text.strip().strip('```json').strip('```')
            new_data = json.loads(txt)
            for key in session["data"]:
                if new_data.get(key):
                    session["data"][key] = new_data[key]
        except:
            pass

        trigger_automation = "Starting automation..." in response.text

        return jsonify({
            "response": response.text,
            "trigger_automation": trigger_automation,
            "session_data": session["data"]
        })
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/automate', methods=['POST'])
def automate():
    data = request.json
    github_user = data.get('github')
    linkedin_url = data.get('linkedin')

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
            
        # Fill the template
        generate_resume(scraped_data)
        
        return jsonify({"status": "success", "message": "Resume generated successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def generate_resume(data):
    # Load template
    with open('resume_template.html', 'r', encoding='utf-8') as f:
        template = f.read()

    gh_profile = data.get('github', {})
    li_profile = data.get('linkedin', {})

    # Simple placeholder replacement logic
    replacements = {
        "Jake Ryan": gh_profile.get('name') or li_profile.get('name') or "Your Name",
        "123-456-7890": "Your Phone",
        "jake@su.edu": "Your Email",
        "linkedin.com/in/jake": li_profile.get('headline', 'LinkedIn Profile'),
        "github.com/jake": f"github.com/{gh_profile.get('name', 'profile')}",
    }

    # Replace Experience
    experience_html = ""
    for exp in li_profile.get('experience', []):
        parts = exp.split(' | ')
        title = parts[0] if len(parts) > 0 else "Experience"
        company = parts[1] if len(parts) > 1 else ""
        date = parts[4] if len(parts) > 4 else ""
        desc = " ".join(parts[5:]) if len(parts) > 5 else ""
        
        experience_html += f"""
        <div class="item">
            <div class="item-header">
                <span class="item-name">{title}</span>
                <span class="item-date">{date}</span>
            </div>
            <div class="item-sub-header">
                <span>{company}</span>
            </div>
            <ul><li>{desc}</li></ul>
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
    for p in gh_profile.get('projects', []):
        projects_html += f"""
        <div class="item">
            <div class="item-header">
                <span class="item-name">{p['name']} | <i>{p['language']}</i></span>
                <span class="item-date">Stars: {p['stars']}</span>
            </div>
            <ul><li>{p['description'] or 'No description provided.'}</li></ul>
        </div>
        """
    if projects_html:
        import re
        template = re.sub(r'(<section id="projects">.*?)<h2>Projects</h2>.*?<section id="skills">', 
                          r'\1<h2>Projects</h2>' + projects_html + '<section id="skills">', 
                          template, flags=re.DOTALL)

    # Replace Skills
    skills_list = data.get('final_skills', [])
    skills_html = f"<p><b>Skills:</b> {', '.join(skills_list)}</p>"
    import re
    template = re.sub(r'(<section id="skills">.*?)<h2>Technical Skills</h2>.*?</div>', 
                      r'\1<h2>Technical Skills</h2><div class="skills-container">' + skills_html + '</div>', 
                      template, flags=re.DOTALL)

    for key, val in replacements.items():
        template = template.replace(key, str(val))

    with open('final_resume.html', 'w', encoding='utf-8') as f:
        f.write(template)

@app.route('/download', methods=['GET'])
def download():
    return send_file('final_resume.html', as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
