import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

# Load env variables for API key
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Use a standard text model for generation
model = genai.GenerativeModel('gemini-2.5-flash')

def process_experience_with_gemini(experience_list):
    if not experience_list:
        return []

    processed = []
    for exp in experience_list:
        prompt = f"""
        You are an expert resume writer. 
        Analyze the following experience description and convert it into 2-3 highly professional, action-oriented bullet points.
        Do not include any introductory or concluding text, just the bullet points themselves separated by newlines.
        Each bullet point MUST start with an action verb.
        
        Experience:
        {exp}
        """
        try:
            response = model.generate_content(prompt)
            bullets = [b.strip().strip('-* ') for b in response.text.split('\n') if b.strip()]
            
            # Reconstruct the experience string with HTML bullets
            # The original parsing is: parts = exp.split(' | ')
            # So we keep the title and company, and replace the desc
            parts = exp.split(' | ')
            if len(parts) > 5:
                # Replace the original description with the new bullets
                bullets_html = "".join([f"<li>{b}</li>" for b in bullets if b])
                new_exp = " | ".join(parts[:5]) + " | " + f"<ul>{bullets_html}</ul>"
                processed.append(new_exp)
            else:
                processed.append(exp) # Fallback
        except Exception as e:
            print(f"Error processing experience with Gemini: {e}")
            processed.append(exp)
            
    return processed

def process_projects_with_gemini(projects_list):
    if not projects_list:
        return []

    processed_projects = []
    for proj in projects_list:
        desc = proj.get('description', '')
        if not desc:
            processed_projects.append(proj)
            continue
            
        prompt = f"""
        You are an expert resume writer.
        Analyze the following software project description and convert it into 2-3 highly professional, action-oriented bullet points.
        IMPORTANT: Your bullet points MUST highlight the impact of the project (e.g., "impact on X and Y", "improved Z", "enabled A to do B").
        Do not include any introductory or concluding text, just the bullet points themselves separated by newlines.
        Each bullet point MUST start with an action verb.
        
        Project Name: {proj.get('name', 'Unknown')}
        Description: {desc}
        """
        try:
            response = model.generate_content(prompt)
            bullets = [b.strip().strip('-* ') for b in response.text.split('\n') if b.strip()]
            bullets_html = "".join([f"<li>{b}</li>" for b in bullets if b])
            
            # Update the description with the new HTML bullets
            new_proj = proj.copy()
            new_proj['description'] = f"<ul>{bullets_html}</ul>"
            processed_projects.append(new_proj)
        except Exception as e:
            print(f"Error processing project with Gemini: {e}")
            processed_projects.append(proj)

    return processed_projects

def process_skills_with_gemini(skills_list):
    if not skills_list:
        return {}

    skills_str = ", ".join(skills_list)
    prompt = f"""
    You are an expert technical recruiter analyzing a candidate's skills.
    Categorize the following skills into ONLY these specific categories:
    - Language
    - Framework
    - Developer Tools
    - Libraries
    
    Filter out any skills that are irrelevant to a software engineering resume.
    Return the result strictly as a valid JSON object where the keys are the categories above, and the values are lists of strings representing the skills.
    Do not wrap the JSON in markdown code blocks or add any other text.
    
    Skills to categorize:
    {skills_str}
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith('```json'):
            text = text[7:]
        if text.endswith('```'):
            text = text[:-3]
            
        categorized_skills = json.loads(text.strip())
        return categorized_skills
    except Exception as e:
        print(f"Error processing skills with Gemini: {e}")
        # Fallback to a flat list
        return {"Skills": skills_list}
