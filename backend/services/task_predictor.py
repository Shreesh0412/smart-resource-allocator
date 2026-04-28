"""
services/task_predictor.py
--------------------------
Uses Google Gemini AI to read task context (descriptions, urgency, volunteer counts)
to predict risk, and automatically extracts structured resource requirements from natural language.
"""

import os
import json
import google.generativeai as genai

def init_gemini(config):
    """Initializes the Gemini client if the API key is available."""
    api_key = config.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
        return True
    return False

def predict_task_risk(db, task, config):
    """
    Analyzes task details using Gemini and returns "on_track", "at_risk", or "critical".
    """
    if not init_gemini(config):
        print("WARNING: Gemini API Key missing. Falling back to basic math predictor.")
        vol_ratio = len(task.get("assigned_volunteers", [])) / max(1, task.get("volunteers_needed", 1))
        if vol_ratio == 0 and task.get("urgency") == "urgent": return "critical"
        elif vol_ratio < 1.0: return "at_risk"
        return "on_track"

    title = task.get('title', 'Unknown Task')
    desc = task.get('description', 'No description provided.')
    urgency = task.get('urgency', 'low')
    needed = task.get('volunteers_needed', 1)
    assigned = len(task.get('assigned_volunteers', []))
    deadline = task.get('deadline', 'Unknown')

    prompt = f"""
    You are an AI assistant managing an NGO disaster relief and resource allocation system.
    Analyze the following task and determine its completion risk.
    
    Task Title: {title}
    Description: {desc}
    Stated Urgency: {urgency}
    Volunteers Needed: {needed}
    Currently Assigned Volunteers: {assigned}
    Deadline: {deadline}
    
    Based on the severity in the description, the stated urgency, and the ratio of assigned vs needed volunteers, classify the risk of this task failing.
    
    Respond with ONLY ONE of the following exactly (no quotes, no other text):
    on_track
    at_risk
    critical
    """

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        result = response.text.strip().lower()
        
        if "critical" in result:
            return "critical"
        elif "at_risk" in result or "risk" in result:
            return "at_risk"
        else:
            return "on_track"
            
    except Exception as e:
        print(f"Gemini AI Error: {e}")
        return "at_risk" 

def extract_resources(description, config):
    """
    Uses Gemini to read a problem description and extract needed resources 
    into a structured JSON format.
    """
    if not init_gemini(config) or not description:
        return {}

    prompt = f"""
    Read the following emergency report description. Extract any physical resources or items 
    that the person is requesting or that are clearly needed. 
    
    Description: "{description}"
    
    Return the result strictly as a raw JSON object where the keys are the item names 
    (snake_case, lowercase) and the values are the quantities (integers). If no quantity is specified, use 1.
    If no resources are mentioned, return an empty JSON object {{}}.
    
    Example: {{"water_bottles": 50, "blankets": 10, "first_aid_kits": 2}}
    
    Do not include markdown formatting like ```json or anything else. Just the raw JSON.
    """

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        
        # Clean up the response in case the AI added markdown block ticks
        raw_text = response.text.strip().removeprefix('```json').removesuffix('```').strip()
        
        # Parse the string into a Python dictionary
        extracted_data = json.loads(raw_text)
        return extracted_data
    except Exception as e:
        print(f"Resource Extraction Error: {e}")
        return {}
