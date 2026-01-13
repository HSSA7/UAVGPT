import sys
import time
import json
from nl_to_drone_dsl import nl_to_dsl
from dsl_to_json import dsl_to_json
from validate_mission import run_validation

# CONFIGURATION
PROVIDER = "openai" 
DELAY = 1.0 # Seconds between calls to respect API limits

# THE EXHAUSTIVE DATASET (14 Categories)
TEST_DATASET = {
    # --- FLIGHT SAFETY ---
    "ARM": [
        "Arm the drone", "Engage motors", "Unlock safety", "Power up rotors", "Enable system",
        "Start engines", "Prepare for flight", "Arm d1", "Set arm state true", "Activate drone"
    ],
    "DISARM": [
        "Disarm drone", "Kill motors", "Cut power", "Lock safety", "Stop engines",
        "Disable rotors", "Shut down", "Disarm system", "Turn off motors", "Emergency stop"
    ],
    "TAKEOFF": [
        "Takeoff to 10m", "Ascend to 20m", "Climb to 50ft", "Lift off to 5m", "Launch to 15m",
        "Start flight altitude 10", "Rise to 30m", "Takeoff height 12", "Go up to 10m", "Depart vertical 20m"
    ],
    "LAND": [
        "Land now", "Touch down", "Descend to ground", "Return to surface", "Land immediately",
        "Stop flying and land", "Set mode LAND", "Come down", "Land at current spot", "Terminate flight"
    ],
    
    # --- NAVIGATION ---
    "MOVE": [
        "Move North 10m", "Fly forward 20m", "Go South 50m", "Slide West 30m", "Shift East 15m",
        "Climb Up 5m", "Drop Down 2m", "Move forward 100 ft", "Move right 5m", "Back up 10m"
    ],
    "GOTO": [
        "Fly to x=10 y=20", "Go to 30, 40", "Head to x=5 y=5", "Transit to 100, 100",
        "Move to grid 50, -50", "Fly to dest x=0 y=10", "Nav to x=20 y=20 z=10", "Go to point 5, 5",
        "Fly straight to x=15 y=15", "Relocate to 10, 0"
    ],
    "CIRCLE": [
        "Circle radius 10m", "Orbit here radius 5", "Loiter around point radius 20", "Fly circle 15m",
        "Do a 360 orbit", "Circle target 5m", "Start circling 30m", "Orbit left 10m",
        "Turn in circle 25m", "Loiter turns radius 8"
    ],
    "RETURN": [
        "Return to launch", "Come home", "RTL", "Fly back to start", "Abort and return",
        "Go home", "Return to base", "Back to launch", "Return immediately", "Retreat to start"
    ],

    # --- PHYSICS ---
    "SPEED": [
        "Set speed 10 m/s", "Fly fast 20 m/s", "Slow down 2 m/s", "Velocity 15",
        "Cruise speed 5", "Max speed 25", "Speed up to 12", "Reduce speed 1", "Speed 50 km/h", "Maintain 8 m/s"
    ],
    "YAW": [
        "Yaw 90 deg", "Rotate right 45", "Turn left 180", "Face North",
        "Spin 360", "Heading 270", "Look South", "Yaw clockwise 90", "Yaw CCW 45", "Orientation 120"
    ],

    # --- PAYLOAD / MISSION (The New Stuff) ---
    "ROI": [
        "Look at x=10 y=10", "Point nose at 50, 50", "Focus on target x=0 y=0", "Set ROI North 20m",
        "Keep camera on home", "Track object 30, 30", "Observe point 5, 5", "Stare at 10, 10",
        "Lock view 100, 100", "Region of interest 15, 15"
    ],
    "TRIGGER": [
        "Take a picture", "Capture photo", "Trigger camera", "Snap shot", "Start recording",
        "Stop video", "Video on", "Video off", "Click photo", "Shoot image"
    ],
    "GIMBAL": [
        "Pitch gimbal down 90", "Look down with camera", "Rotate camera up 45", "Gimbal yaw 0",
        "Point camera forward", "Tilt camera -30", "Level gimbal", "Pan camera right",
        "Gimbal pitch -90", "Reset mount"
    ],
    "SERVO": [
        "Open gripper (Servo 1)", "Drop payload", "Release package", "Set servo 1 to 1100",
        "Close claw", "Servo 2 pwm 1900", "Activate servo 5", "Deploy mechanism",
        "Unlock hook", "Engage servo 1"
    ]
}

def run_suite():
    print(f"--- STARTING EXHAUSTIVE DRONE STRESS TEST ---")
    print(f"Dataset Size: {sum(len(v) for v in TEST_DATASET.values())} commands")
    print("="*60)

    total_pass = 0
    total_fail = 0
    
    for category, commands in TEST_DATASET.items():
        print(f"\n>>> TESTING: {category}")
        print("-" * 60)
        
        for i, cmd in enumerate(commands):
            print(f"[{i+1:02d}] '{cmd}'", end=" ")
            sys.stdout.flush()
            
            try:
                # 1. NL -> DSL (The Brain)
                dsl = nl_to_dsl(cmd, provider_name=PROVIDER)
                
                # 2. DSL -> JSON (The Parser)
                mission = dsl_to_json(dsl)
                
                # 3. SAFETY VALIDATION (The Safety Officer)
                # This ensures we catch safety violations (e.g. negative altitude)
                # It returns a list of errors. Empty list = Safe.
                errors, _ = run_validation(mission)
                
                if errors:
                    print(f"-> ❌ FAIL (Safety Violation)")
                    total_fail += 1
                    continue
                
                if not mission['steps']:
                    print(f"-> ❌ FAIL (No Steps Generated)")
                    total_fail += 1
                    continue
                
                gen_action = mission['steps'][0]['action']
                
                # 4. CATEGORY MATCHING (The Accuracy Check)
                expected_list = [category]
                if category == "MOVE": expected_list = ["MOVE", "GOTO"]
                if category == "GOTO": expected_list = ["GOTO", "MOVE"]
                if category == "TRIGGER": expected_list = ["TRIGGER"]
                
                if gen_action in expected_list or gen_action == category:
                    print(f"-> ✅ PASS ({gen_action})")
                    total_pass += 1
                else:
                    print(f"-> ⚠️  MISMATCH (Exp: {category}, Got: {gen_action})")
                    total_fail += 1
                    
            except Exception as e:
                print(f"-> ❌ CRASH: {e}")
                total_fail += 1
                
            time.sleep(DELAY) # Rate limiting

    print("="*60)
    print(f"FINAL SCORE: {total_pass} PASSED / {total_fail} FAILED")
    print("="*60)

if __name__ == "__main__":
    run_suite()