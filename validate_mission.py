import sys
import json
import math
import datetime

# --- SCIENTIFIC CONSTRAINTS (The Ground Truth) ---
MAX_ALTITUDE = 120.0       # Legal ceiling (meters)
MIN_ALTITUDE = 0.0         # Physics constraint (Ground)
MAX_SPEED = 30.0           # Max motor speed (m/s)
MAX_DISTANCE = 500.0       # Geofence radius (m)

def validate_step(step, index, current_state, log_buffer):
    """
    Validates a single mission step against physics and safety rules.
    Logs detailed evidence to the buffer.
    """
    action = step.get("action")
    params = step.get("params", {})
    issues = []

    # Log the action for the report
    log_buffer.append(f"\n[Step {index}] ACTION: {action} | Params: {params}")

    # 1. PARAMETER VERIFICATION (Syntax Check)
    if action == "TAKEOFF":
        if "altitude" in params or "alt" in params:
            log_buffer.append("   ✅ [Syntax] Required param 'altitude' found.")
        else:
            msg = f"Step {index} (TAKEOFF): Missing 'altitude' parameter."
            issues.append(msg)
            log_buffer.append(f"   ❌ [Syntax] {msg}")

    # 2. PHYSICS PREDICTION (Semantic Check)
    # Predict where the drone will be after this step
    next_state = list(current_state)
    
    if action == "TAKEOFF":
        alt = float(params.get("altitude", params.get("alt", 10)))
        next_state[2] = alt
    elif action == "GOTO":
        if "x" in params: next_state[0] = float(params["x"])
        if "y" in params: next_state[1] = float(params["y"])
        if "z" in params: next_state[2] = float(params["z"])
    elif action == "MOVE":
        dist = float(params.get("distance", 0))
        direction = str(params.get("direction", "")).upper()
        if "NORTH" in direction: next_state[1] += dist
        elif "SOUTH" in direction: next_state[1] -= dist
        elif "EAST" in direction: next_state[0] += dist
        elif "WEST" in direction: next_state[0] -= dist
        elif "UP" in direction: next_state[2] += dist
        elif "DOWN" in direction: next_state[2] -= dist
    elif action == "LAND":
        next_state[2] = 0.0

    # Log the physics prediction
    log_buffer.append(f"   ℹ️  [State] Predicted Pos: (x={next_state[0]:.1f}, y={next_state[1]:.1f}, z={next_state[2]:.1f})")

    # 3. SAFETY CHECKS (Ground Truth Logic)
    
    # Check A: Minimum Altitude (Crash Prevention)
    if next_state[2] < MIN_ALTITUDE:
        msg = f"Step {index} CRITICAL: Drone commanded to crash/fly underground (z={next_state[2]}m)."
        issues.append(msg)
        log_buffer.append(f"   ❌ [Safety] {msg}")
    else:
        log_buffer.append(f"   ✅ [Safety] Altitude ({next_state[2]}m) >= Ground ({MIN_ALTITUDE}m).")

    # Check B: Maximum Altitude (Legal Compliance)
    if next_state[2] > MAX_ALTITUDE:
        msg = f"Step {index} WARNING: Altitude {next_state[2]}m exceeds legal limit."
        issues.append(msg)
        log_buffer.append(f"   ⚠️ [Safety] {msg}")
    else:
        log_buffer.append(f"   ✅ [Safety] Altitude ({next_state[2]}m) <= Ceiling ({MAX_ALTITUDE}m).")
    
    # Check C: Geofence (Operational Area)
    dist_from_home = math.sqrt(next_state[0]**2 + next_state[1]**2)
    if dist_from_home > MAX_DISTANCE:
        msg = f"Step {index} SAFETY: Drone leaving operational area ({dist_from_home:.1f}m > {MAX_DISTANCE}m)."
        issues.append(msg)
        log_buffer.append(f"   ❌ [Geofence] {msg}")
    else:
        log_buffer.append(f"   ✅ [Geofence] Distance ({dist_from_home:.1f}m) inside Radius ({MAX_DISTANCE}m).")

    return issues, next_state

def run_validation(mission_json):
    """
    Orchestrates the validation process and compiles the full report.
    """
    log_buffer = []
    
    # Header for the log file
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_buffer.append(f"\n{'='*50}")
    log_buffer.append(f"MISSION VALIDATION REPORT | {timestamp}")
    log_buffer.append(f"Mission ID: {mission_json.get('mission_id', 'Unknown')}")
    log_buffer.append(f"{'-'*50}")

    if "steps" not in mission_json:
        return ["Invalid JSON: No 'steps' key found."], log_buffer

    all_issues = []
    current_state = [0.0, 0.0, 0.0] # Start at Home (x=0, y=0, z=0)

    for i, step in enumerate(mission_json["steps"]):
        # Pass the log buffer down to record details
        step_issues, current_state = validate_step(step, i+1, current_state, log_buffer)
        all_issues.extend(step_issues)

    # Final Conclusion in the log
    log_buffer.append(f"{'-'*50}")
    if all_issues:
        log_buffer.append("CONCLUSION: ❌ FAILED")
        log_buffer.append(f"Total Errors: {len(all_issues)}")
    else:
        log_buffer.append("CONCLUSION: ✅ PASSED")
        log_buffer.append("All safety constraints satisfied.")
    log_buffer.append(f"{'='*50}\n")

    return all_issues, log_buffer

if __name__ == "__main__":
    # Read JSON from pipe (Standard Input)
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            print("Error: No input data.", file=sys.stderr)
            sys.exit(1)
            
        data = json.loads(raw_input)
        
        # --- EXECUTE VERIFICATION ---
        errors, logs = run_validation(data)
        
        # --- PERSISTENT LOGGING (APPEND MODE) ---
        # This writes to 'mission_validation_report.txt' without deleting old logs.
        try:
            with open("mission_validation_report.txt", "a", encoding="utf-8") as f:
                f.write("\n".join(logs))
        except Exception as e:
            print(f"Warning: Could not write to log file: {e}", file=sys.stderr)
        
        # --- TERMINAL OUTPUT ---
        if errors:
            print("\n❌ VERIFICATION FAILED (See mission_validation_report.txt)", file=sys.stderr)
            # Print specific errors to stderr so user sees them immediately
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            sys.exit(1) # Stop the pipeline
        else:
            print("\n✅ VERIFICATION SUCCESSFUL. Appended to 'mission_validation_report.txt'", file=sys.stderr)
            # Pass valid JSON to Standard Output (for visualize.py)
            print(json.dumps(data))
            
    except json.JSONDecodeError:
        print("Error: Failed to decode JSON.", file=sys.stderr)
        sys.exit(1)