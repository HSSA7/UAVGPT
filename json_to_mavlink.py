"""
json_to_mavlink.py

Convert mission JSON -> list of MAVLink commands (and optionally send them).

Requires:
    pip install pymavlink

Key function:
    compose_and_send_mavlink(mission_json, drone_sys_map, connections=None, send=False)

Parameters:
    mission_json: dict (your JSON mission)
    drone_sys_map: dict mapping your drone IDs to (system_id:int, component_id:int)
                   e.g. {"d1": (1, 1), "d2": (2, 1)}
    connections: optional dict mapping drone ids to pymavlink mavutil connections
                 e.g. {"d1": mavutil_connection_obj, ...}
    send: if True, will attempt to send messages via connections

Returns:
    list of generated action dicts (with `type`, `drone`, `sysid`, `compid`, and `payload` fields)
"""

from typing import Dict, List, Tuple, Optional, Any
import time
import math

# Import pymavlink types (raise clear error if missing)
try:
    from pymavlink import mavutil
except Exception as e:
    raise ImportError("pymavlink is required: pip install pymavlink") from e


# Helper to build a COMMAND_LONG send dict
def _command_long_dict(sysid: int, compid: int, command: int, params: List[float], confirmation: int = 0):
    # params must be length 7
    p = (params + [0.0] * 7)[:7]
    return {
        "type": "COMMAND_LONG",
        "sysid": sysid,
        "compid": compid,
        "command": command,
        "confirmation": confirmation,
        "params": p
    }


# Helper to build a MISSION_ITEM_INT dict (mission item with lat/lon encoded as int in 1e7)
def _mission_item_int_dict(sysid:int, compid:int, seq:int, command:int,
                           param1:float=0, param2:float=0, param3:float=0, param4:float=0,
                           x:int=0, y:int=0, z:float=0, frame:int=0, current:int=0, autocontinue:int=1):
    return {
        "type": "MISSION_ITEM_INT",
        "sysid": sysid,
        "compid": compid,
        "seq": seq,
        "command": command,
        "params": [param1, param2, param3, param4, x, y, z],
        "frame": frame,
        "current": current,
        "autocontinue": autocontinue
    }


# Main function
def compose_and_send_mavlink(mission_json: Dict[str, Any],
                             drone_sys_map: Dict[str, Tuple[int,int]],
                             connections: Optional[Dict[str, Any]] = None,
                             send: bool = False,
                             verbose: bool = True) -> List[Dict[str, Any]]:
    """
    Compose MAVLink messages for the provided mission JSON.

    - drone_sys_map: maps DSL drone ids to (system_id, component_id)
    - connections: optional mapping drone_id -> pymavlink connection (mavutil)
    - send: if True, send messages immediately using the provided connections
    - returns a list of composed message dicts (not raw bytes)
    """
    steps = mission_json.get("steps", [])
    mission_id = mission_json.get("mission_id", "mission_001")
    generated = []
    seq_counter_per_drone = {d: 0 for d in mission_json.get("drones", [])}

    # helper to send a command_long using a pymavlink connection
    def _send_command_long(conn, sysid, compid, cmd, params):
        # pymavlink call: command_long_send(target_system, target_component, command, confirmation, p1..p7)
        conn.mav.command_long_send(sysid, compid, cmd, 0,
                                   float(params[0] if len(params) > 0 else 0.0),
                                   float(params[1] if len(params) > 1 else 0.0),
                                   float(params[2] if len(params) > 2 else 0.0),
                                   float(params[3] if len(params) > 3 else 0.0),
                                   float(params[4] if len(params) > 4 else 0.0),
                                   float(params[5] if len(params) > 5 else 0.0),
                                   float(params[6] if len(params) > 6 else 0.0)
                                   )

    def _send_mission_item_int(conn, sysid, compid, seq, command, params, frame=0, current=0, autocontinue=1):
        # params: [p1,p2,p3,p4,x,y,z] where x/y for lat/lon int (1e7)
        p = params + [0.0] * (7 - len(params))
        conn.mav.mission_item_int_send(
            sysid, compid,
            seq,
            frame,
            int(current),
            int(autocontinue),
            int(command),
            float(p[0]), float(p[1]), float(p[2]), float(p[3]),
            int(p[4]), int(p[5]), float(p[6])
        )

    # iterate steps and compose messages
    for step in steps:
        drone = step.get("drone")
        if drone not in drone_sys_map:
            raise ValueError(f"Drone {drone} not found in drone_sys_map")
        sysid, compid = drone_sys_map[drone]
        action = step.get("action")
        params = step.get("params", {}) or {}
        control = step.get("control", {}) or {}
        state_id = step.get("state_id", None)
        seq = seq_counter_per_drone.get(drone, 0)

        # Map DSL actions to MAVLink commands
        if action == "ARM":
            # Use MAV_CMD_COMPONENT_ARM_DISARM (COMMAND_LONG): param1=1 to arm, 0 to disarm
            cmd = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
            p = [1.0]  # arm
            md = _command_long_dict(sysid, compid, cmd, p)
            md.update({"drone": drone, "action": "ARM", "state_id": state_id})
            generated.append(md)
            if send and connections and drone in connections:
                if verbose: print(f"[{drone}] Sending ARM (sys:{sysid})")
                _send_command_long(connections[drone], sysid, compid, cmd, p)

        elif action == "DISARM":
            cmd = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
            p = [0.0]  # disarm
            md = _command_long_dict(sysid, compid, cmd, p)
            md.update({"drone": drone, "action": "DISARM", "state_id": state_id})
            generated.append(md)
            if send and connections and drone in connections:
                if verbose: print(f"[{drone}] Sending DISARM (sys:{sysid})")
                _send_command_long(connections[drone], sysid, compid, cmd, p)

        elif action == "TAKEOFF":
            # Use MAV_CMD_NAV_TAKEOFF. This is normally a MISSION_ITEM or can be sent via COMMAND_LONG in some stacks.
            # We'll compose as a mission-item-int (MISSION protocol). For guided immediate takeoff, some systems accept COMMAND_LONG.
            cmd = mavutil.mavlink.MAV_CMD_NAV_TAKEOFF
            # Params may include altitude, yaw, etc.
            altitude = float(params.get("altitude", params.get("alt", params.get("z", 10))))
            # For mission item int we need lat/lon int; if not provided, send zeros and expect vehicle to takeoff in place.
            lat = int(params.get("lat", 0) * 1e7) if params.get("lat") else 0
            lon = int(params.get("lon", 0) * 1e7) if params.get("lon") else 0
            p = [0, 0, 0, 0, lat, lon, altitude]
            md = _mission_item_int_dict(sysid, compid, seq, cmd, *p[:4], x=p[4], y=p[5], z=altitude, frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, current=0, autocontinue=1)
            md.update({"drone": drone, "action": "TAKEOFF", "state_id": state_id, "human_params": params})
            generated.append(md)
            # increment seq
            seq_counter_per_drone[drone] = seq + 1
            if send and connections and drone in connections:
                if verbose: print(f"[{drone}] Uploading TAKEOFF mission item (seq {seq})")
                _send_mission_item_int(connections[drone], sysid, compid, seq, cmd, p, frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT)

        elif action == "LAND":
            # Use MAV_CMD_NAV_LAND as mission item
            cmd = mavutil.mavlink.MAV_CMD_NAV_LAND
            altitude = float(params.get("altitude", params.get("alt", 0)))
            lat = int(params.get("lat", 0) * 1e7) if params.get("lat") else 0
            lon = int(params.get("lon", 0) * 1e7) if params.get("lon") else 0
            p = [0, 0, 0, 0, lat, lon, altitude]
            md = _mission_item_int_dict(sysid, compid, seq, cmd, *p[:4], x=p[4], y=p[5], z=altitude, frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT)
            md.update({"drone": drone, "action": "LAND", "state_id": state_id, "human_params": params})
            generated.append(md)
            seq_counter_per_drone[drone] = seq + 1
            if send and connections and drone in connections:
                if verbose: print(f"[{drone}] Uploading LAND mission item (seq {seq})")
                _send_mission_item_int(connections[drone], sysid, compid, seq, cmd, p, frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT)

        elif action == "GOTO":
            # Use MAV_CMD_NAV_WAYPOINT as mission item
            cmd = mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
            # Accept lat/lon/z or local x/y/z params. Prefer lat/lon.
            if "lat" in params and "lon" in params:
                lat = int(float(params["lat"]) * 1e7)
                lon = int(float(params["lon"]) * 1e7)
                alt = float(params.get("altitude", params.get("alt", params.get("z", 0))))
                p = [0, 0, 0, 0, lat, lon, alt]
                md = _mission_item_int_dict(sysid, compid, seq, cmd, *p[:4], x=p[4], y=p[5], z=p[6], frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT)
            else:
                # If no lat/lon provided, we may use command_long guided reposition for some stacks (not standard)
                # We'll fall back to DO_REPOSITION (if available) via COMMAND_LONG (not standard across stacks).
                # Here we raise a warning and continue.
                md = {"type": "UNSUPPORTED", "drone": drone, "action": "GOTO", "reason": "Missing lat/lon", "params": params}
            md.update({"drone": drone, "action": "GOTO", "state_id": state_id, "human_params": params})
            generated.append(md)
            seq_counter_per_drone[drone] = seq + 1
            if send and connections and drone in connections and md.get("type") == "MISSION_ITEM_INT":
                if verbose: print(f"[{drone}] Uploading GOTO (seq {seq})")
                _send_mission_item_int(connections[drone], sysid, compid, seq, cmd, p, frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT)

        elif action == "SPEED":
            # Use MAV_CMD_DO_CHANGE_SPEED via COMMAND_LONG
            cmd = mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED
            # params: speed_type(0=airspeed,1=ground speed), speed, throttle
            speed_type = float(params.get("type", 1))  # default ground
            speed = float(params.get("speed", params.get("v", 0)))
            throttle = float(params.get("throttle", 0))
            p = [speed_type, speed, throttle]
            md = _command_long_dict(sysid, compid, cmd, p)
            md.update({"drone": drone, "action": "SPEED", "state_id": state_id, "human_params": params})
            generated.append(md)
            if send and connections and drone in connections:
                if verbose: print(f"[{drone}] Sending SPEED change (speed={speed})")
                _send_command_long(connections[drone], sysid, compid, cmd, p)

        elif action == "YAW":
            # Use MAV_CMD_CONDITION_YAW via COMMAND_LONG
            cmd = mavutil.mavlink.MAV_CMD_CONDITION_YAW
            # params: yaw (deg), speed, direction, relative
            yaw = float(params.get("yaw", params.get("heading", 0)))
            speed = float(params.get("speed", 0))
            direction = float(params.get("direction", 0))  # 1 cw, -1 ccw
            relative = float(1 if params.get("relative", True) else 0)
            p = [yaw, speed, direction, relative]
            md = _command_long_dict(sysid, compid, cmd, p)
            md.update({"drone": drone, "action": "YAW", "state_id": state_id, "human_params": params})
            generated.append(md)
            if send and connections and drone in connections:
                if verbose: print(f"[{drone}] Sending YAW (yaw={yaw})")
                _send_command_long(connections[drone], sysid, compid, cmd, p)

        elif action in {"HOLD", "RETURN", "CIRCLE", "FOLLOW", "WAIT"}:
            # Basic mapping suggestions:
            if action == "HOLD":
                # LOITER / hold - many autopilots interpret LOITER or use MAV_CMD_NAV_LOITER_UNTIL
                cmd = mavutil.mavlink.MAV_CMD_NAV_LOITER_UNTIL
                # MAV_CMD_NAV_LOITER_UNTIL params generally use time, etc. We'll set timeout param to params.get('time', 0)
                timeout = float(params.get("time", 0))
                p = [timeout, 0, 0, 0, 0, 0, 0]
                md = _mission_item_int_dict(sysid, compid, seq, cmd, *p[:4], x=0, y=0, z=0, frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT)
                generated.append(md)
                seq_counter_per_drone[drone] = seq + 1
                if send and connections and drone in connections:
                    if verbose: print(f"[{drone}] Uploading HOLD (loiter) mission item")
                    _send_mission_item_int(connections[drone], sysid, compid, seq, cmd, p)

            elif action == "RETURN":
                # Return to launch (RTL) - many autopilots support MAV_CMD_NAV_RETURN_TO_LAUNCH as mission item or mode.
                cmd = mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH
                md = _command_long_dict(sysid, compid, cmd, [])
                generated.append(md)
                if send and connections and drone in connections:
                    if verbose: print(f"[{drone}] Sending RETURN_TO_LAUNCH")
                    _send_command_long(connections[drone], sysid, compid, cmd, [])

            elif action == "CIRCLE":
                # Some autopilots have MAV_CMD_NAV_LOITER_TO_ALT or other circle/loiter commands.
                cmd = mavutil.mavlink.MAV_CMD_NAV_LOITER_TURNS  # if available
                turns = float(params.get("turns", 1))
                p = [turns, 0, 0, 0, 0, 0, 0]
                md = _mission_item_int_dict(sysid, compid, seq, cmd, *p[:4], x=0, y=0, z=params.get("alt", 0))
                generated.append(md)
                seq_counter_per_drone[drone] = seq + 1
                if send and connections and drone in connections:
                    if verbose: print(f"[{drone}] Uploading CIRCLE (loiter turns)")
                    _send_mission_item_int(connections[drone], sysid, compid, seq, cmd, p)

            elif action == "FOLLOW":
                # 'FOLLOW' is not a single standard MAV_CMD. Many autopilots implement a 'follow-me' behavior or DO_FOLLOW.
                # Here we attempt to use MAV_CMD_DO_FOLLOW (if present) or mark 'UNSUPPORTED' for runtime implementation.
                # We'll create a placeholder COMMAND_LONG for follow if user provided a 'target' param.
                if "target" in params:
                    # This is autopilot-specific; we'll package as COMMAND_LONG with command id if available.
                    md = {"type": "COMMAND_LONG", "sysid": sysid, "compid": compid, "command": "MAV_CMD_DO_FOLLOW (non-standard)", "params": params}
                else:
                    md = {"type": "UNSUPPORTED", "drone": drone, "action": "FOLLOW", "reason": "no target provided"}
                generated.append(md)

            elif action == "WAIT":
                # WAIT: encode as a simple delay/time in a "meta" step. Not a MAVLink command by itself; runtime orchestrator should sleep.
                wait_seconds = float(params.get("time", params.get("t", 1)))
                md = {"type": "WAIT", "drone": drone, "action": "WAIT", "seconds": wait_seconds, "state_id": state_id}
                generated.append(md)
                if send and verbose:
                    print(f"[{drone}] WAIT for {wait_seconds} seconds (no MAVLink message)")

        else:
            # Unsupported action
            md = {"type": "UNSUPPORTED", "drone": drone, "action": action, "params": params}
            generated.append(md)

        # note: control clauses (AFTER s1, AFTER d1, UNTIL cond) are not directly convertible to MAVLink messages.
        # They are scheduling constraints for your mission controller. We preserve them in the generated dicts.
        if generated:
            generated[-1]["control"] = control

    # return the generated plan/messages
    return generated


# Example usage:
if __name__ == "__main__":
    sample_json = {
        "mission_id": "m001",
        "drones": ["d1"],
        "steps": [
            {"state_id": "s1", "drone": "d1", "action": "ARM", "params": {}, "control": {"after_state": "NONE"}, "next": "s2"},
            {"state_id": "s2", "drone": "d1", "action": "TAKEOFF", "params": {"alt": 15}, "control": {"after_state": "s1"}, "next": "s3"},
            {"state_id": "s3", "drone": "d1", "action": "GOTO", "params": {"lat": 28.6139, "lon": 77.2090, "alt": 15}, "control": {"after_state": "s2"}, "next": None}
        ]
    }

    # example drone id mapping:
    drone_sys_map = {"d1": (1, 1)}

    # Compose messages (no real sending)
    plan = compose_and_send_mavlink(sample_json, drone_sys_map, connections=None, send=False, verbose=True)
    import pprint
    pprint.pprint(plan)
