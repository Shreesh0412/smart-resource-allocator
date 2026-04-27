"""
services/task_predictor.py
--------------------------
Uses Google Gemini AI to read task context (descriptions, urgency, volunteer counts)
and accurately predict the risk of a task failing or missing its deadline.
"""

import os
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
    # 1. Check if Gemini is configured
    if not init_gemini(config):
        print("WARNING: Gemini API Key missing. Falling back to basic math predictor.")
        # Fallback logic if API key isn't set up
        vol_ratio = len(task.get("assigned_volunteers", [])) / max(1, task.get("volunteers_needed", 1))
        if vol_ratio == 0 and task.get("urgency") == "urgent": return "critical"
        elif vol_ratio < 1.0: return "at_risk"
        return "on_track"

    # 2. Extract context for the AI
    title = task.get('title', 'Unknown Task')
    desc = task.get('description', 'No description provided.')
    urgency = task.get('urgency', 'low')
    needed = task.get('volunteers_needed', 1)
    assigned = len(task.get('assigned_volunteers', []))
    deadline = task.get('deadline', 'Unknown')

    # 3. Create the prompt for Gemini
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

    # 4. Call Gemini 1.5 Flash (Fast & cheap, perfect for quick data tagging)
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        
        # Clean up the AI's response to match our database enums
        result = response.text.strip().lower()
        
        # Ensure it only returns the exact strings our frontend expects
        if "critical" in result:
            return "critical"
        elif "at_risk" in result or "risk" in result:
            return "at_risk"
        else:
            return "on_track"
            
    except Exception as e:
        print(f"Gemini AI Error: {e}")
        return "at_risk" # Safe default if the API call fails
