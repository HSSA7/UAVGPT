"""
nl_to_drone_dsl.py
Includes Refiner, Explainer, Self-Repair, and CONVERSATIONAL MEMORY.
"""
from typing import Optional
import re
from llm_provider import get_llm_provider, LLMProvider

# --- CONFIGURATION ---
SYSTEM_INSTRUCTIONS = """
You are a strict translator that converts natural language drone commands into DSL.
Rules:
- Output MULTIPLE DSL instructions if needed.
- Ends with semicolon `;`.
- Use only uppercase DSL commands.
- ALWAYS separate multiple instructions by a newline.
- EVERY instruction MUST start with "DRONE <id>".

KEYWORDS:
- MOTION: ARM, DISARM, TAKEOFF, LAND, GOTO, HOLD, CIRCLE, RETURN, SPEED, YAW, MOVE, WAIT
- PAYLOAD: ROI, TRIGGER, GIMBAL, SERVO

CRITICAL RULES:
1. DO NOT invent new commands. Use ONLY the keywords listed above.
2. If the user says "Stop", translate it as "DRONE d1 HOLD;".
3. For "North/South/East/West", use the MOVE command with 'direction' and 'distance'.
4. ROI FORMAT: Always use 'x=... y=...'. DO NOT use 'coordinates=(...)' or tuples.
   CORRECT: "DRONE d1 ROI x=50 y=50;"
   WRONG: "DRONE d1 ROI coordinates=(50,50);"
5. UNSAFE/UNKNOWN COMMANDS: If the user asks for something unsafe or unknown, translate it as a safe wait: "DRONE d1 WAIT duration=1;".
"""

FEW_SHOT_EXAMPLES = [
    ("Takeoff to 10m", "DRONE d1 TAKEOFF altitude=10;"),
    ("Stop", "DRONE d1 HOLD;"),
    ("Look at 50,50", "DRONE d1 ROI x=50 y=50;"),
    ("Take a photo", "DRONE d1 TRIGGER action=PHOTO;")
]
FEW_SHOT_TEXT = "\n".join([f"NL: {nl}\nDSL:\n{dsl}" for nl, dsl in FEW_SHOT_EXAMPLES])

def get_provider(name="openai"):
    return get_llm_provider(name)

def clean_dsl(raw_text: str) -> str:
    # Extract code between ``` if present
    match = re.search(r"```(?:\w+)?\n(.*?)```", raw_text, re.DOTALL)
    if match:
        raw_text = match.group(1)
    # Extract only lines ending in ;
    lines = re.findall(r".+?;", raw_text, flags=re.DOTALL)
    return "\n".join(line.strip() for line in lines).strip()

# ---------------------------------------------------------
# 1. CORE GENERATOR
# ---------------------------------------------------------
def nl_to_dsl(nl_text: str, provider_name: str = "openai") -> str:
    provider = get_provider(provider_name)
    prompt = f"{SYSTEM_INSTRUCTIONS}\n\nExamples:\n{FEW_SHOT_TEXT}\n\nNL: {nl_text}\nDSL:"
    return clean_dsl(provider.generate(prompt))

# ---------------------------------------------------------
# 2. THE EXPLAINER (For Human Check)
# ---------------------------------------------------------
def explain_dsl(dsl_text: str, provider_name: str = "openai") -> str:
    """
    Asks the LLM to translate the DSL back into a summary for the user.
    """
    provider = get_provider(provider_name)
    prompt = f"""
    You are a Safety Officer. Read this Drone DSL code and explain clearly what the drone will do.
    
    DSL CODE:
    {dsl_text}
    
    Explanation for Pilot:
    """
    return provider.generate(prompt).strip()

# ---------------------------------------------------------
# 3. THE REPAIRMAN (For Syntax Errors)
# ---------------------------------------------------------
def repair_dsl_with_error(bad_dsl: str, error_msg: str, provider_name: str = "openai") -> str:
    """
    Feeds the error message back to the LLM to fix the code.
    """
    provider = get_provider(provider_name)
    prompt = f"""
    {SYSTEM_INSTRUCTIONS}
    
    I tried to run your DSL code but it failed with this error:
    ERROR: {error_msg}
    
    BAD CODE:
    {bad_dsl}
    
    Please FIX the code to satisfy the rules. Output only the valid DSL.
    FIXED DSL:
    """
    return clean_dsl(provider.generate(prompt))

# ---------------------------------------------------------
# 4. THE CONVERSATIONALIST (New Refinement Logic)
# ---------------------------------------------------------
def refine_dsl(current_dsl: str, user_feedback: str, provider_name: str = "openai") -> str:
    """
    Takes the existing plan and modifies it based on user chat.
    """
    provider = get_provider(provider_name)
    prompt = f"""
    {SYSTEM_INSTRUCTIONS}
    
    CURRENT PLAN (DSL):
    {current_dsl}
    
    USER FEEDBACK (CORRECTION):
    "{user_feedback}"
    
    TASK: Update the CURRENT PLAN based on the user feedback. 
    - Keep the parts that were correct. 
    - Only change what the user asked for.
    - Ensure valid syntax (DRONE id ACTION...).
    
    UPDATED DSL:
    """
    return clean_dsl(provider.generate(prompt))