import sys
import json
import re
import math
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.animation import FuncAnimation

# --- PHYSICS ENGINE ---
def interpolate(start, end, steps=20):
    path = []
    vector = np.array(end) - np.array(start)
    for i in range(1, steps + 1):
        point = np.array(start) + vector * (i / steps)
        path.append(tuple(point))
    return path

def generate_circle_path(center, radius, start_alt, steps=60):
    """Generates a circular path around the center point."""
    path = []
    # 1. Move from Center to Edge (East)
    edge_start = (center[0] + radius, center[1], start_alt)
    path.extend(interpolate(center, edge_start, steps=10))
    
    # 2. Perform Circle
    for i in range(steps + 1):
        angle = 2 * math.pi * (i / steps)
        x = center[0] + radius * math.cos(angle)
        y = center[1] + radius * math.sin(angle)
        path.append((x, y, start_alt))
        
    # 3. Return to Center
    path.extend(interpolate(edge_start, center, steps=10))
    return path

def process_mission(mission_json):
    current_pos = [0.0, 0.0, 0.0] 
    current_heading = 0.0 # 0 = North (Y+), 90 = East (X+)
    
    trajectory = [tuple(current_pos)]
    headings = [0.0]
    events = []
    roi_targets = [] 
    status_log = ["IDLE"] 

    steps = mission_json.get("steps", [])
    
    print(f"DEBUG: Processing {len(steps)} steps...")

    for i, step in enumerate(steps):
        action = step.get("action")
        params = step.get("params", {})
        
        start = list(current_pos)
        end = list(current_pos)
        path_segment = []
        current_status = f"{action}"
        
        # --- MOTION ---
        if action == "TAKEOFF":
            alt = float(params.get("altitude", params.get("alt", 10)))
            end[2] = alt
            path_segment = interpolate(start, end, steps=30)
            current_status = f"TAKEOFF {alt}m"

        elif action == "LAND":
            end[2] = 0.0
            path_segment = interpolate(start, end, steps=30)
            current_status = "LANDING"

        elif action == "GOTO":
            if "x" in params: end[0] = float(params["x"])
            if "y" in params: end[1] = float(params["y"])
            if "z" in params: end[2] = float(params["z"])
            path_segment = interpolate(start, end, steps=40)
            current_status = "NAVIGATING"

        elif action == "YAW":
            angle = float(params.get("angle", 0))
            current_heading = angle 
            path_segment = [tuple(current_pos)] * 15 
            current_status = f"YAW {angle}°"

        elif action == "CIRCLE":
            radius = float(params.get("radius", 5))
            path_segment = generate_circle_path(start, radius, start[2])
            current_status = f"CIRCLING r={radius}m"
            # Note: Heading calculation for circles is complex, we'll just keep current or tangent
            # For simplicity in this viz, we keep current heading or make it look at center
            # Let's just extend the last heading for simplicity
            
        elif action == "MOVE":
            dist = float(params.get("distance", 0))
            direction = str(params.get("direction", "")).upper()
            
            dx, dy, dz = 0, 0, 0
            
            if "NORTH" in direction: dy += dist
            elif "SOUTH" in direction: dy -= dist
            elif "EAST" in direction:  dx += dist
            elif "WEST" in direction:  dx -= dist
            elif "UP" in direction:    dz += dist
            elif "DOWN" in direction:  dz -= dist
            elif "FORWARD" in direction:
                rad = math.radians(90 - current_heading)
                dx += dist * math.cos(rad)
                dy += dist * math.sin(rad)
            elif "BACK" in direction:
                rad = math.radians(90 - current_heading)
                dx -= dist * math.cos(rad)
                dy -= dist * math.sin(rad)
            elif "NORTHEAST" in direction: 
                d = dist * 0.707; dx += d; dy += d;

            end[0] += dx; end[1] += dy; end[2] += dz
            path_segment = interpolate(start, end, steps=30)
            current_status = f"MOVING {direction}"

        elif action == "RETURN":
            end = [0.0, 0.0, current_pos[2]] 
            path_segment = interpolate(start, end, steps=50)
            current_status = "RTL"

        # --- PAYLOAD ---
        elif action == "ROI":
            tx, ty = None, None
            if "x" in params: tx, ty = float(params["x"]), float(params["y"])
            
            if tx is not None:
                start_idx = len(trajectory)
                duration = 20 
                path_segment = [tuple(current_pos)] * duration
                current_status = f"TRACKING {tx},{ty}"
                for k in range(duration):
                    roi_targets.append((start_idx + k, (tx, ty, 0)))
            else:
                 current_status = "ROI CLEAR"
                 path_segment = [tuple(current_pos)] * 5

        elif action == "TRIGGER":
            events.append({'pos': tuple(current_pos), 'type': 'PHOTO', 'label': 'PHOTO'})
            path_segment = [tuple(current_pos)] * 10
            current_status = "CAPTURING IMG"

        elif action == "SERVO":
            events.append({'pos': tuple(current_pos), 'type': 'DROP', 'label': 'DROP'})
            path_segment = [tuple(current_pos)] * 10
            current_status = "PAYLOAD RELEASE"

        elif action == "WAIT":
             path_segment = [tuple(current_pos)] * 20
             current_status = "WAITING..."

        if path_segment:
            trajectory.extend(path_segment)
            # Extend headings logic
            if action == "CIRCLE":
                # Calculate tangent headings for circle
                circle_len = len(path_segment)
                for k in range(circle_len):
                    # Rough estimate: look forward along path
                    if k < circle_len - 1:
                        p1 = path_segment[k]; p2 = path_segment[k+1]
                        dx = p2[0]-p1[0]; dy = p2[1]-p1[1]
                        # Math angle to Compass angle: Compass = 90 - Math
                        math_ang = math.degrees(math.atan2(dy, dx))
                        headings.append(90 - math_ang)
                    else:
                        headings.append(headings[-1])
            else:
                headings.extend([current_heading] * len(path_segment))
                
            status_log.extend([current_status] * len(path_segment))
            current_pos = end

    return trajectory, headings, events, roi_targets, status_log

# --- DRONE RENDERER ---
def get_drone_geometry(x, y, z, heading_deg, scale=2.0):
    """Returns the coordinates for a Quadcopter shape (X-frame)."""
    rad = math.radians(90 - heading_deg)
    
    # Arm offsets
    d = scale
    
    # 45 deg offset for X-config
    arm_angles = [45, 135, 225, 315] 
    arms = []
    
    for ang in arm_angles:
        local_rad = math.radians(ang + (90-heading_deg) - 90)
        ax = x + d * math.cos(local_rad)
        ay = y + d * math.sin(local_rad)
        arms.append((ax, ay, z))
        
    return arms 

def animate_mission(mission_json):
    trajectory, headings, events, roi_targets, status_log = process_mission(mission_json)
    
    if not trajectory:
        print("No moves found.")
        return

    # Setup 3D Plot
    fig = plt.figure(figsize=(12, 8), facecolor='#222222')
    ax = fig.add_subplot(111, projection='3d', facecolor='#222222')
    
    # Sim Style
    ax.tick_params(axis='x', colors='gray')
    ax.tick_params(axis='y', colors='gray')
    ax.tick_params(axis='z', colors='gray')
    
    # FIX: Updated for Matplotlib 3.8+ compatibility
    ax.xaxis.set_pane_color((0.1, 0.1, 0.1, 1.0))
    ax.yaxis.set_pane_color((0.1, 0.1, 0.1, 1.0))
    ax.zaxis.set_pane_color((0.05, 0.05, 0.05, 1.0))
    
    ax.grid(color='gray', linestyle=':', linewidth=0.3)

    # Calculate Limits
    xs, ys, zs = zip(*trajectory)
    all_x = list(xs) + [e['pos'][0] for e in events]
    all_y = list(ys) + [e['pos'][1] for e in events]
    all_z = list(zs) + [e['pos'][2] for e in events]
    
    # Add ROI targets to limits
    for _, t in roi_targets:
        all_x.append(t[0]); all_y.append(t[1])

    pad = 10
    ax.set_xlim(min(all_x)-pad, max(all_x)+pad)
    ax.set_ylim(min(all_y)-pad, max(all_y)+pad)
    ax.set_zlim(0, max(max(all_z)+pad, 20)) 

    # Draw Ground Plane (Grid)
    xx, yy = np.meshgrid(np.linspace(min(all_x)-10, max(all_x)+10, 10),
                         np.linspace(min(all_y)-10, max(all_y)+10, 10))
    ax.plot_wireframe(xx, yy, np.zeros_like(xx), color='#444444', alpha=0.3)

    # Static Elements
    ax.plot(xs, ys, zs, color='#00ff00', linestyle=':', linewidth=0.8, alpha=0.4, label='Flight Path')

    for e in events:
        c, m = 'white', 'o'
        if e['type'] == 'PHOTO': c, m = 'cyan', '*'
        elif e['type'] == 'DROP': c, m = 'magenta', 'v'
        elif e['type'] == 'LOOK': c, m = 'orange', 's'
        ax.scatter(e['pos'][0], e['pos'][1], e['pos'][2], color=c, marker=m, s=80, edgecolors='white', zorder=10)
        ax.text(e['pos'][0], e['pos'][1], e['pos'][2]+2, e['label'], color='white', fontsize=7)

    # --- DYNAMIC ELEMENTS ---
    arm1, = ax.plot([], [], [], color='red', linewidth=2)   
    arm2, = ax.plot([], [], [], color='white', linewidth=2) 
    shadow, = ax.plot([], [], [], color='black', marker='o', alpha=0.3)
    sight_line, = ax.plot([], [], [], color='orange', linestyle='--', linewidth=1.5)
    
    # HUD Text
    hud_mode = fig.text(0.02, 0.95, "MODE: STABILIZED", color='cyan', fontsize=12, fontfamily='monospace', weight='bold')
    hud_stat = fig.text(0.02, 0.91, "STAT: IDLE", color='white', fontsize=10, fontfamily='monospace')
    hud_alt  = fig.text(0.02, 0.87, "ALT : 0.0m", color='white', fontsize=10, fontfamily='monospace')
    hud_head = fig.text(0.02, 0.83, "HDG : 000°", color='white', fontsize=10, fontfamily='monospace')

    def update(frame):
        if frame >= len(trajectory): return
        
        x, y, z = trajectory[frame]
        h = headings[frame]
        stat = status_log[frame]
        
        # 1. Update Drone Geometry
        arms = get_drone_geometry(x, y, z, h, scale=3.0)
        
        # Front V (Red)
        arm1.set_data([arms[1][0], x, arms[0][0]], [arms[1][1], y, arms[0][1]])
        arm1.set_3d_properties([arms[1][2], z, arms[0][2]])
        
        # Back V (White)
        arm2.set_data([arms[2][0], x, arms[3][0]], [arms[2][1], y, arms[3][1]])
        arm2.set_3d_properties([arms[2][2], z, arms[3][2]])
        
        # 2. Update Shadow
        shadow.set_data([x], [y])
        shadow.set_3d_properties([0]) 
        
        # 3. Update ROI 
        active_target = None
        for f_idx, t_pos in roi_targets:
            if f_idx == frame:
                active_target = t_pos
                break
        
        if active_target:
            sight_line.set_data([x, active_target[0]], [y, active_target[1]])
            sight_line.set_3d_properties([z, active_target[2]])
        else:
            sight_line.set_data([], [])
            sight_line.set_3d_properties([])

        # 4. Update HUD
        hud_stat.set_text(f"STAT: {stat}")
        hud_alt.set_text(f"ALT : {z:.1f}m")
        hud_head.set_text(f"HDG : {int(h)%360:03d}°")
        
        return arm1, arm2, shadow, sight_line, hud_stat, hud_alt, hud_head

    ani = FuncAnimation(fig, update, frames=len(trajectory), blit=False, interval=30)
    plt.legend(loc='upper right', facecolor='#333333', edgecolor='white', labelcolor='white')
    plt.show()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r') as f:
            data = json.load(f)
            animate_mission(data)
    elif not sys.stdin.isatty():
        data = json.loads(sys.stdin.read())
        animate_mission(data)
    else:
        print("Usage: python3 visualize.py mission.json")