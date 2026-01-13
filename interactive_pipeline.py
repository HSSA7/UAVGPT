import sys
import json
import os
# This import is correct HERE because this file USES the functions
from nl_to_drone_dsl import nl_to_dsl, explain_dsl, repair_dsl_with_error, refine_dsl
from dsl_to_json import dsl_to_json
from validate_mission import run_validation

def interactive_session():
    print("\n" + "="*60)
    user_text = input("👨‍✈️ COMMANDER: Enter your mission request (or Press Enter to Quit):\n> ")
    if not user_text.strip(): return

    provider = "openai" 
    max_retries = 3
    print("\n🤖 AI: Generating mission plan...")
    current_dsl = nl_to_dsl(user_text, provider)

    while True:
        # 1. PARSE & REPAIR
        mission_json = None
        success = False
        for attempt in range(max_retries):
            try:
                mission_json = dsl_to_json(current_dsl)
                if not mission_json.get("steps"): raise ValueError("No steps.")
                success = True
                break
            except Exception as e:
                print(f"⚠️ Syntax Error: {e}")
                if attempt < max_retries - 1:
                    print("🔧 AI Auto-Repairing...")
                    current_dsl = repair_dsl_with_error(current_dsl, str(e), provider)
                else:
                    print("❌ Failed to fix code.")
                    return

        # 2. DISPLAY (Only once per valid plan)
        print("-" * 60)
        print(f"📋 CURRENT MISSION PLAN:\n{current_dsl}")
        print("-" * 60)
        print(f"🗣️ AI EXPLANATION:\n{explain_dsl(current_dsl, provider)}")
        print("-" * 60)

        # 3. DECISION LOOP
        while True:
            print("Options: [Y] Yes | [N] No | [C] Change")
            choice = input("👉 Your Choice: ").lower().strip()

            if choice == 'y':
                print("\n🛡️ SAFETY OFFICER: Validating...")
                errors, logs = run_validation(mission_json)
                with open("mission_validation_report.txt", "a") as f:
                    f.write("\n" + "="*60 + "\n" + "\n".join(logs))
                
                if errors:
                    print("❌ SAFETY FAILURE:")
                    for e in errors: print(f"  - {e}")
                    return 
                else:
                    print("✅ Mission Safe. Launching Visualizer...")
                    with open("temp_mission.json", "w") as f:
                        json.dump(mission_json, f)
                    os.system("python3 visualize.py temp_mission.json")
                    return 

            elif choice == 'n':
                print("🚫 Mission Aborted.")
                return

            elif choice == 'c':
                feedback = input("\n💬 What should I change?\n> ")
                if feedback.strip():
                    print("\n🤖 AI: Updating plan...")
                    current_dsl = refine_dsl(current_dsl, feedback, provider)
                    break 
                else:
                    print("No feedback. Keeping plan.")
            else:
                print("Invalid choice. Try again.")

if __name__ == "__main__":
    while True:
        interactive_session()
        if input("\nStart another session? (y/n): ").lower() != 'y':
            break