"""Post-link observation wrapper for the single-video motion/short stage pair."""

import math
import sys
from numbers import Integral, Real

ERROR = "postlink observation invalid"


def _snapshot(nodes_by_id, edges):
    if not isinstance(nodes_by_id, dict) or not isinstance(edges, list):
        raise ValueError(ERROR)
    ids = []
    for node_id in nodes_by_id:
        if isinstance(node_id, bool) or not isinstance(node_id, Integral):
            raise ValueError(ERROR)
        ids.append(int(node_id))
    id_set = set(ids)
    if len(id_set) != len(ids):
        raise ValueError(ERROR)
    snap_nodes = []
    for node_id in nodes_by_id:
        node = nodes_by_id[node_id]
        if not isinstance(node, dict):
            raise ValueError(ERROR)
        for key in ("t", "z", "y", "x"):
            if key not in node:
                raise ValueError(ERROR)
        for key in ("t",):
            value = node[key]
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ValueError(ERROR)
        synthetic = node.get("gap_synthetic", 0)
        if isinstance(synthetic, bool) or not isinstance(synthetic, Integral):
            raise ValueError(ERROR)
        synthetic = int(synthetic)
        if synthetic not in (0, 1):
            raise ValueError(ERROR)
        coords = []
        for key in ("z", "y", "x"):
            value = node[key]
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(ERROR)
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(ERROR)
            coords.append(value)
        t = int(node["t"])
        if not math.isfinite(float(t)):
            raise ValueError(ERROR)
        snap_nodes.append([int(node_id), t, coords[0], coords[1], coords[2], synthetic])
    snap_edges = []
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError(ERROR)
        if "source_id" not in edge or "target_id" not in edge:
            raise ValueError(ERROR)
        src = edge["source_id"]
        dst = edge["target_id"]
        for endpoint in (src, dst):
            if isinstance(endpoint, bool) or not isinstance(endpoint, Integral):
                raise ValueError(ERROR)
            if int(endpoint) not in id_set:
                raise ValueError(ERROR)
        snap_edges.append([int(src), int(dst)])
    snap_nodes.sort(key=lambda row: tuple(row[:5]))
    snap_edges.sort()
    return {"nodes": snap_nodes, "edges": snap_edges}


def observe_postlink(run, motion_function, short_function):
    if not callable(run):
        raise TypeError(ERROR)
    for function in (motion_function, short_function):
        if not callable(function) or not hasattr(function, "__code__"):
            raise TypeError(ERROR)
    motion_code = motion_function.__code__
    short_code = short_function.__code__
    if motion_code is short_code:
        raise ValueError(ERROR)
    if sys.getprofile() is not None:
        raise RuntimeError(ERROR)
    state = [0]
    error = [False]
    snapshots = {}

    def callback(frame, event, arg):
        if error[0]:
            return
        try:
            code = frame.f_code
            if code is motion_code:
                if event != "return":
                    return
                if state[0] != 0:
                    error[0] = True
                    return
                if not isinstance(arg, list) or not arg:
                    error[0] = True
                    return
                snapshots["motion_after"] = _snapshot(frame.f_locals["nodes_by_id"], arg)
                state[0] = 1
            elif code is short_code:
                if event == "call":
                    if state[0] != 1:
                        error[0] = True
                        return
                    snapshots["short_before"] = _snapshot(
                        frame.f_locals["nodes_by_id"], frame.f_locals["edges"]
                    )
                    state[0] = 2
                elif event == "return":
                    if state[0] != 2:
                        error[0] = True
                        return
                    if (
                        not isinstance(arg, tuple)
                        or len(arg) != 2
                        or not isinstance(arg[0], dict)
                        or not isinstance(arg[1], list)
                    ):
                        error[0] = True
                        return
                    snapshots["short_after"] = _snapshot(arg[0], arg[1])
                    state[0] = 3
                else:
                    return
            else:
                return
        except Exception:
            error[0] = True

    previous = sys.getprofile()
    sys.setprofile(callback)
    try:
        result = run()
    finally:
        sys.setprofile(previous)
    if error[0] or state[0] != 3 or len(snapshots) != 3:
        raise RuntimeError(ERROR)
    return result, snapshots
