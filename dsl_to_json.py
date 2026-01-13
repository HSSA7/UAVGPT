"""
dsl_to_json.py
Parses DSL commands into structured JSON.
Includes robustness against malformed lines and support for Payload commands.
"""

import json
import re
import sys
from typing import List, Dict, Any
from dotenv import load_dotenv

# Force load .env to ensure keys are available if this script is entry point
load_dotenv()

from nl_to_drone_dsl import nl_to_dsl

# ----------------------------------------------------------
# PARSER UTILITIES
# ----------------------------------------------------------

# UPDATE: Added PAYLOAD keywords (ROI, TRIGGER, GIMBAL, SERVO)
ACTION_KEYWORDS = {
    # Navigation
    "ARM", "DISARM", "TAKEOFF", "LAND", "GOTO", "HOLD",
    "CIRCLE", "RETURN", "SPEED", "YAW", "FOLLOW", "WAIT", "ROTATE", "MOVE",
    
    # Payload / Mission
    "ROI",      # MAV_CMD_DO_SET_ROI
    "TRIGGER",  # MAV_CMD_DO_DIGICAM_CONTROL
    "GIMBAL",   # MAV_CMD_DO_MOUNT_CONTROL
    "SERVO"     # MAV_CMD_DO_SET_SERVO
}

def parse_param_list(tokens: List[str], idx: int):
    """
    Extract parameters k=v until control (AFTER/UNTIL) or end.
    Supports numeric OR string values.
    """
    params = {}
    while idx < len(tokens):
        tok = tokens[idx]

        if tok in ("AFTER", "UNTIL"):
            break

        if "=" in tok:
            k, v = tok.split("=")

            # Detect numeric vs string
            # Check for float/int format
            if re.fullmatch(r"-?\d+(\.\d+)?", v):
                params[k] = float(v) if "." in v else int(v)
            else:
                params[k] = v  # keep as string

        idx += 1

    return params, idx


def parse_control(tokens: List[str], idx: int):
    """
    Parses AFTER or UNTIL control.
    """
    if idx >= len(tokens):
        return {"after_state": "NONE", "after_drone": None, "until": None}, idx

    tok = tokens[idx]

    if tok == "AFTER":
        target = tokens[idx + 1]
        if target.startswith("s"):
            return {
                "after_state": target,
                "after_drone": None,
                "until": None
            }, idx + 2
        else:
            return {
                "after_state": "NONE",
                "after_drone": target,
                "until": None
            }, idx + 2

    if tok == "UNTIL":
        cond = tokens[idx + 1]
        return {
            "after_state": "NONE",
            "after_drone": None,
            "until": cond
        }, idx + 2

    # No control
    return {"after_state": "NONE", "after_drone": None, "until": None}, idx


# ----------------------------------------------------------
# MAIN DSL → JSON FUNCTION
# ----------------------------------------------------------

def dsl_to_json(dsl: str) -> Dict[str, Any]:
    """
    Converts DSL script into mission JSON.
    Skips invalid lines instead of crashing.
    """

    # Remove newlines + double spaces
    cleaned = re.sub(r"\s+", " ", dsl).strip()

    # Split instructions on semicolon
    raw_cmds = [c.strip() for c in cleaned.split(";") if c.strip()]

    steps = []
    used_drones = set()
    state_counter = 1

    for cmd in raw_cmds:
        tokens = cmd.split()
        
        # 1. ROBUSTNESS CHECK: Ensure we have enough tokens
        if len(tokens) < 2: 
            # Need at least DRONE and ID. Action might be missing or implict?
            # Actually need 3 for standard commands: DRONE id ACTION
            if len(tokens) == 0: continue
            # If it's just "STOP", our previous robustness fix handles it elsewhere,
            # but strict DSL should be DRONE id ACTION.
            # We'll log warning and skip.
            print(f"Warning: Skipping malformed/short line: '{cmd}'", file=sys.stderr)
            continue

        # Expect form: DRONE d1 ACTION params control
        if tokens[0] != "DRONE":
            print(f"Warning: Skipping line not starting with DRONE: '{cmd}'", file=sys.stderr)
            continue

        drone_id = tokens[1]
        used_drones.add(drone_id)

        # Next token must be action
        idx = 2
        if idx >= len(tokens):
            print(f"Warning: Missing action in line: '{cmd}'", file=sys.stderr)
            continue

        action = tokens[idx]
        
        # 2. KEYWORD CHECK & AUTO-FIX
        if action not in ACTION_KEYWORDS:
            if action == "STOP":
                action = "HOLD" # Auto-fix common mistake
            else:
                print(f"Warning: Unknown action '{action}' in line: '{cmd}'", file=sys.stderr)
                continue
                
        idx += 1

        # Params
        params, idx = parse_param_list(tokens, idx)

        # Control fields
        control, idx = parse_control(tokens, idx)

        # Build state object
        state_id = f"s{state_counter}"
        next_state = f"s{state_counter+1}" if state_counter < len(raw_cmds) else None

        steps.append({
            "state_id": state_id,
            "drone": drone_id,
            "action": action,
            "params": params,
            "control": control,
            "next": next_state
        })

        state_counter += 1

    return {
        "mission_id": "mission_auto",
        "drones": sorted(list(used_drones)),
        "steps": steps
    }


# ----------------------------------------------------------
# CLI TEST (Clean Output for Piping)
# ----------------------------------------------------------

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="NL -> Drone DSL Translator")
    parser.add_argument("--text", "-t", type=str, required=True)
    parser.add_argument("--provider", "-p", type=str, default="openai",
                        help="LLM provider (openai, gemini, ollama)")
    args = parser.parse_args()

    # Print debug info to stderr (so it doesn't break the pipe)
    print(f"Using provider: {args.provider}", file=sys.stderr)
    
    try:
        dsl = nl_to_dsl(args.text, provider_name=args.provider)
        
        # Parse DSL to JSON
        result = dsl_to_json(dsl)
        
        # ONLY print the JSON to standard output
        print(json.dumps(result, indent=2))
        
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)