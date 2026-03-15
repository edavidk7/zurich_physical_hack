#!/usr/bin/env python3
"""
SO-101 URDF Joint Frame Viewer

Parses the SO-101 URDF kinematic chain, computes FK at a given joint config,
and renders each link frame with RGB = XYZ axis gizmos in a matplotlib 3D plot.

Usage:
    python urdf_frame_viewer.py
    python urdf_frame_viewer.py --joints 0 -30 45 0 0 0
    python urdf_frame_viewer.py --urdf path/to/so-101.urdf
"""

from __future__ import annotations
import matplotlib
matplotlib.use("QtAgg")  # Use non-interactive backend for better performance and headless environments
import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


# ──────────────────────────────────────────────────────────────────────
# Geometry helpers
# ──────────────────────────────────────────────────────────────────────


def rotx(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def roty(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rotz(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def rpy_to_rot(rpy: list[float]) -> np.ndarray:
    """RPY (XYZ intrinsic) → 3×3 rotation matrix."""
    return rotz(rpy[2]) @ roty(rpy[1]) @ rotx(rpy[0])


def make_T(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def axis_angle_rot(axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues rotation about an arbitrary unit axis."""
    k = axis / (np.linalg.norm(axis) + 1e-12)
    c, s = np.cos(angle), np.sin(angle)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return c * np.eye(3) + s * K + (1 - c) * np.outer(k, k)


# ──────────────────────────────────────────────────────────────────────
# URDF parser (minimal, joint chain only)
# ──────────────────────────────────────────────────────────────────────


@dataclass
class URDFJoint:
    name: str
    type: str
    parent: str
    child: str
    xyz: np.ndarray = field(default_factory=lambda: np.zeros(3))
    rpy: np.ndarray = field(default_factory=lambda: np.zeros(3))
    axis: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 1.0]))
    lower: float = -np.pi
    upper: float = np.pi


def parse_urdf(path_or_string: str) -> list[URDFJoint]:
    """Parse joint chain from a URDF file or XML string."""
    try:
        tree = ET.parse(path_or_string)
        root = tree.getroot()
    except (OSError, ET.ParseError):
        root = ET.fromstring(path_or_string)

    joints: list[URDFJoint] = []
    for jel in root.findall("joint"):
        name = jel.attrib["name"]
        jtype = jel.attrib["type"]
        parent = jel.find("parent").attrib["link"]
        child = jel.find("child").attrib["link"]

        xyz = np.zeros(3)
        rpy = np.zeros(3)
        origin = jel.find("origin")
        if origin is not None:
            if origin.attrib.get("xyz"):
                xyz = np.array(list(map(float, origin.attrib["xyz"].split())))
            if origin.attrib.get("rpy"):
                rpy = np.array(list(map(float, origin.attrib["rpy"].split())))

        axis = np.array([0.0, 0.0, 1.0])
        ax_el = jel.find("axis")
        if ax_el is not None and ax_el.attrib.get("xyz"):
            axis = np.array(list(map(float, ax_el.attrib["xyz"].split())))

        lower, upper = -np.pi, np.pi
        lim = jel.find("limit")
        if lim is not None:
            lower = float(lim.attrib.get("lower", -np.pi))
            upper = float(lim.attrib.get("upper", np.pi))

        joints.append(URDFJoint(name, jtype, parent, child, xyz, rpy, axis, lower, upper))
    return joints


# ──────────────────────────────────────────────────────────────────────
# Mesh loading
# ──────────────────────────────────────────────────────────────────────


@dataclass
class URDFLink:
    name: str
    mesh_file: str | None = None
    visual_xyz: np.ndarray = field(default_factory=lambda: np.zeros(3))
    visual_rpy: np.ndarray = field(default_factory=lambda: np.zeros(3))


def parse_urdf_links(path_or_string: str) -> dict[str, URDFLink]:
    """Parse visual mesh info from each <link> element."""
    try:
        tree = ET.parse(path_or_string)
        root = tree.getroot()
    except (OSError, ET.ParseError):
        root = ET.fromstring(path_or_string)

    links: dict[str, URDFLink] = {}
    for lel in root.findall("link"):
        name = lel.attrib["name"]
        link = URDFLink(name=name)
        visual = lel.find("visual")
        if visual is not None:
            origin = visual.find("origin")
            if origin is not None:
                if origin.attrib.get("xyz"):
                    link.visual_xyz = np.array(list(map(float, origin.attrib["xyz"].split())))
                if origin.attrib.get("rpy"):
                    link.visual_rpy = np.array(list(map(float, origin.attrib["rpy"].split())))
            geom = visual.find("geometry")
            if geom is not None:
                mesh_el = geom.find("mesh")
                if mesh_el is not None:
                    link.mesh_file = mesh_el.attrib.get("filename")
        links[name] = link
    return links


def find_mesh_dir(urdf_path: str) -> str | None:
    """Find the meshes/ directory sibling to the urdf/ folder."""
    candidate = Path(urdf_path).resolve().parent.parent / "meshes"
    return str(candidate) if candidate.is_dir() else None


def resolve_mesh_path(mesh_file: str, mesh_dir: str) -> str | None:
    """Convert package://so-101/meshes/Foo.STL → absolute path."""
    # Strip package URI prefix, keep just the filename
    filename = Path(mesh_file).name
    p = Path(mesh_dir) / filename
    return str(p) if p.exists() else None


def load_stl(path: str, max_triangles: int = 1010) -> np.ndarray | None:
    """Load a binary STL file.

    Returns an (N, 3, 3) float32 array of triangle vertices (N ≤ max_triangles),
    or None on failure. Uses uniform decimation to stay under max_triangles.
    """
    dtype = np.dtype([
        ("normal", np.float32, (3,)),
        ("v0", np.float32, (3,)),
        ("v1", np.float32, (3,)),
        ("v2", np.float32, (3,)),
        ("attr", np.uint16),
    ])
    try:
        with open(path, "rb") as f:
            f.read(80)  # header
            n = np.frombuffer(f.read(4), dtype=np.uint32)[0]
            raw = np.frombuffer(f.read(n * 50), dtype=dtype)
        tris = np.stack([raw["v0"], raw["v1"], raw["v2"]], axis=1)  # (N, 3, 3)
        if len(tris) > max_triangles:
            step = len(tris) // max_triangles
            tris = tris[::step]
        return tris
    except Exception as e:
        print(f"[mesh] failed to load {path}: {e}", file=sys.stderr)
        return None


# ──────────────────────────────────────────────────────────────────────
# FK computation
# ──────────────────────────────────────────────────────────────────────

PLACO_TO_MOTOR = {
    "Rotation": "shoulder_pan",
    "Pitch": "shoulder_lift",
    "Elbow": "elbow_flex",
    "Wrist_Pitch": "wrist_flex",
    "Wrist_Roll": "wrist_roll",
    "Jaw": "gripper",
}


def compute_fk(
    joints: list[URDFJoint],
    q_deg: dict[str, float],
) -> list[tuple[str, str, np.ndarray]]:
    """
    Walk the kinematic chain and return (joint_name, child_link, T_world_child)
    for every joint. q_deg is keyed by motor name (shoulder_pan, etc.).

    Returns list of (joint_name, child_link_name, 4×4 world transform).
    """
    # Build parent→children map
    link_T: dict[str, np.ndarray] = {"base_link": np.eye(4)}
    results: list[tuple[str, str, np.ndarray]] = [("(world)", "base_link", np.eye(4))]

    for joint in joints:
        T_parent = link_T.get(joint.parent, np.eye(4))

        # Static origin transform
        R_origin = rpy_to_rot(joint.rpy)
        T_origin = make_T(R_origin, joint.xyz)

        # Joint rotation (if revolute/continuous)
        T_joint = np.eye(4)
        if joint.type in ("revolute", "continuous"):
            motor_name = PLACO_TO_MOTOR.get(joint.name, joint.name)
            angle_deg = q_deg.get(motor_name, 0.0)
            angle_rad = np.deg2rad(angle_deg)
            R_joint = axis_angle_rot(joint.axis, angle_rad)
            T_joint[:3, :3] = R_joint

        T_world_child = T_parent @ T_origin @ T_joint
        link_T[joint.child] = T_world_child
        results.append((joint.name, joint.child, T_world_child))

    return results


# ──────────────────────────────────────────────────────────────────────
# Visualization
# ──────────────────────────────────────────────────────────────────────


def draw_frame(
    ax: Axes3D,
    T: np.ndarray,
    label: str,
    length: float = 0.025,
    lw: float = 2.0,
    fontsize: int = 7,
):
    """Draw RGB axis arrows + label at a 4×4 frame transform."""
    o = T[:3, 3]
    colors = ["#ff3333", "#33cc33", "#3388ff"]
    axis_labels = ["+X", "+Y", "+Z"]

    for i, (c, al) in enumerate(zip(colors, axis_labels)):
        d = T[:3, i] * length
        ax.quiver(
            o[0],
            o[1],
            o[2],
            d[0],
            d[1],
            d[2],
            color=c,
            linewidth=lw,
            arrow_length_ratio=0.18,
        )

    ax.text(
        o[0],
        o[1],
        o[2] + length * 0.3,
        label,
        fontsize=fontsize,
        color="#bbbbbb",
        ha="center",
        fontfamily="monospace",
    )


_LINK_COLORS = [
    "#6688bb", "#7799cc", "#88aadd", "#99bbee",
    "#5577aa", "#6688bb", "#778899",
]


def draw_meshes(
    ax: Axes3D,
    frames: list[tuple[str, str, np.ndarray]],
    link_visuals: dict[str, URDFLink],
    mesh_dir: str,
    max_triangles: int = 1010,
    alpha: float = 0.35,
):
    """Load and render each link's STL mesh transformed into world space."""
    # Build link_name → T_world from frames list
    link_T: dict[str, np.ndarray] = {"Base": np.eye(4)}
    for _, child_link, T in frames:
        link_T[child_link] = T

    for i, (link_name, link) in enumerate(link_visuals.items()):
        if link.mesh_file is None:
            continue
        mesh_path = resolve_mesh_path(link.mesh_file, mesh_dir)
        if mesh_path is None:
            continue
        tris = load_stl(mesh_path, max_triangles=max_triangles)
        if tris is None or len(tris) == 0:
            continue

        T_world = link_T.get(link_name, np.eye(4))
        # Apply visual origin offset
        T_visual = make_T(rpy_to_rot(link.visual_rpy), link.visual_xyz)
        T = T_world @ T_visual

        R, t = T[:3, :3], T[:3, 3]
        verts = (tris @ R.T) + t  # (N, 3, 3)

        color = _LINK_COLORS[i % len(_LINK_COLORS)]
        poly = Poly3DCollection(verts, alpha=alpha, facecolor=color, edgecolor="none", zsort="average")
        ax.add_collection3d(poly)


def plot_robot(
    frames: list[tuple[str, str, np.ndarray]],
    q_deg: dict[str, float],
    title: str = "SO-101 Joint Frames",
    axis_length: float = 0.025,
    link_visuals: dict[str, URDFLink] | None = None,
    mesh_dir: str | None = None,
    max_triangles: int = 1010,
):
    """3D plot of the kinematic chain with axis gizmos and optional STL meshes."""
    fig = plt.figure(figsize=(12, 9), facecolor="#111118")
    ax = fig.add_subplot(111, projection="3d", facecolor="#111118")

    # Draw STL meshes (behind frame axes)
    if link_visuals and mesh_dir:
        draw_meshes(ax, frames, link_visuals, mesh_dir, max_triangles=max_triangles)

    # Draw link connections (lines between consecutive origins)
    positions = [f[2][:3, 3] for f in frames]
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    ax.plot(xs, ys, zs, "-o", color="#445566", linewidth=2, markersize=4, zorder=1)

    # Draw each frame
    for joint_name, link_name, T in frames:
        motor = PLACO_TO_MOTOR.get(joint_name, "")
        if motor:
            label = f"{motor}\n({joint_name})"
        elif joint_name == "(world)":
            label = "base_link"
        else:
            label = link_name

        is_ee = link_name == "Fixed_Jaw"
        draw_frame(
            ax,
            T,
            label,
            length=axis_length * (1.8 if is_ee else 1.0),
            lw=3.0 if is_ee else 2.0,
            fontsize=8 if is_ee else 7,
        )

        # Highlight EE with a larger dot
        if is_ee:
            o = T[:3, 3]
            ax.scatter([o[0]], [o[1]], [o[2]], color="#ffaa33", s=60, zorder=5)

    # Joint config text
    config_lines = [f"Joint config (deg):"]
    for name in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]:
        config_lines.append(f"  {name:16s} = {q_deg.get(name, 0.0):+7.1f}°")
    config_text = "\n".join(config_lines)

    # EE frame info
    ee_frame = [f for f in frames if f[1] == "Fixed_Jaw"]
    if ee_frame:
        T_ee = ee_frame[0][2]
        p = T_ee[:3, 3] * 1010
        config_text += f"\n\nEE position (mm):\n  X={p[0]:+.1f}  Y={p[1]:+.1f}  Z={p[2]:+.1f}"
        config_text += f"\n\nEE frame axes (columns of R):"
        for i, name in enumerate(["+X", "+Y", "+Z"]):
            v = T_ee[:3, i]
            config_text += f"\n  {name}: [{v[0]:+.3f}, {v[1]:+.3f}, {v[2]:+.3f}]"

    fig.text(
        0.02,
        0.02,
        config_text,
        fontsize=8,
        fontfamily="monospace",
        color="#7799bb",
        verticalalignment="bottom",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#181822", edgecolor="#334", alpha=0.9),
    )

    # Axis labels and styling
    ax.set_xlabel("X (m)", color="#ff4444", fontsize=9, fontfamily="monospace")
    ax.set_ylabel("Y (m)", color="#44cc44", fontsize=9, fontfamily="monospace")
    ax.set_zlabel("Z (m)", color="#4488ff", fontsize=9, fontfamily="monospace")

    ax.tick_params(colors="#556677", labelsize=7)
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.xaxis.pane.set_edgecolor("#222233")
    ax.yaxis.pane.set_edgecolor("#222233")
    ax.zaxis.pane.set_edgecolor("#222233")

    # Equal aspect ratio
    all_pts = np.array(positions)
    center = all_pts.mean(axis=0)
    max_range = max(all_pts.max(axis=0) - all_pts.min(axis=0)) / 2 * 1.3
    max_range = max(max_range, 0.05)
    ax.set_xlim(center[0] - max_range, center[0] + max_range)
    ax.set_ylim(center[1] - max_range, center[1] + max_range)
    ax.set_zlim(center[2] - max_range, center[2] + max_range)

    ax.set_title(title, color="#7799bb", fontsize=12, fontfamily="monospace", pad=10)

    # Legend
    from matplotlib.lines import Line2D

    legend_elements = [
        Line2D([0], [0], color="#ff3333", lw=2, label="+X (red)"),
        Line2D([0], [0], color="#33cc33", lw=2, label="+Y (green)"),
        Line2D([0], [0], color="#3388ff", lw=2, label="+Z (blue)"),
        Line2D([0], [0], marker="o", color="#ffaa33", label="EE (Fixed_Jaw)", markersize=8, linestyle="None"),
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=7, facecolor="#181822", edgecolor="#334", labelcolor="#99aabb")

    plt.tight_layout()
    return fig


# ──────────────────────────────────────────────────────────────────────
# Find URDF
# ──────────────────────────────────────────────────────────────────────


def find_urdf() -> str:
    """Try to find the SO-101 URDF from lerobot installation."""
    import site, sys

    search_paths = sys.path + site.getsitepackages() + [site.getusersitepackages()]
    for sp in search_paths:
        candidate = Path(sp) / "resources" / "urdf" / "so-101" / "urdf" / "so-101.urdf"
        if candidate.exists():
            return str(candidate)

    # Also check relative to cwd
    for pattern in ["**/*so-101.urdf", "**/*so_101.urdf"]:
        matches = list(Path(".").glob(pattern))
        if matches:
            return str(matches[0])

    return None


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="SO-101 URDF joint frame viewer")
    ap.add_argument(
        "--urdf",
        default=None,
        help="Path to SO-101 URDF (auto-detected from lerobot if omitted)",
    )
    ap.add_argument(
        "--joints",
        nargs=6,
        type=float,
        default=[0, 0, 0, 0, 0, 0],
        metavar=("PAN", "LIFT", "ELBOW", "WFLEX", "WROLL", "GRIP"),
        help="Joint angles in degrees",
    )
    ap.add_argument(
        "--axis-length",
        type=float,
        default=0.025,
        help="Length of axis arrows in metres (default: 0.025)",
    )
    ap.add_argument(
        "--save",
        default=None,
        help="Save plot to file instead of showing interactively",
    )
    ap.add_argument(
        "--no-mesh",
        action="store_true",
        help="Disable STL mesh rendering (faster, frames only)",
    )
    ap.add_argument(
        "--max-triangles",
        type=int,
        default=1010,
        help="Max triangles per mesh for decimation (default: 1010)",
    )
    args = ap.parse_args()

    # Find URDF
    urdf_path = args.urdf
    if urdf_path is None:
        urdf_path = find_urdf()
    if urdf_path is None or not Path(urdf_path).exists():
        print("URDF not found — using embedded kinematic chain", file=sys.stderr)
        urdf_path = None

    if urdf_path:
        print(f"Using URDF: {urdf_path}")
        joints = parse_urdf(urdf_path)
        link_visuals = parse_urdf_links(urdf_path) if not args.no_mesh else None
        mesh_dir = find_mesh_dir(urdf_path) if not args.no_mesh else None
        if link_visuals and mesh_dir:
            print(f"Mesh dir: {mesh_dir}")
        elif not args.no_mesh:
            print("Mesh dir not found — rendering frames only", file=sys.stderr)
            link_visuals = None
    else:
        joints = parse_urdf(EMBEDDED_URDF)
        link_visuals = None
        mesh_dir = None

    motor_names = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
    q_deg = dict(zip(motor_names, args.joints, strict=False))

    print(f"Joint config: {q_deg}")

    frames = compute_fk(joints, q_deg)

    print(f"\nComputed {len(frames)} frames:")
    for _, lname, T in frames:
        p = T[:3, 3] * 1010
        print(f"  {lname:20s}  pos=({p[0]:+7.1f}, {p[1]:+7.1f}, {p[2]:+7.1f}) mm")

    # Print EE frame details
    ee = [f for f in frames if f[1] == "Fixed_Jaw"]
    if ee:
        T_ee = ee[0][2]
        print("\n  EE (Fixed_Jaw) frame axes at zero config:")
        for i, label in enumerate(["+X", "+Y", "+Z"]):
            v = T_ee[:3, i]
            print(f"    {label} = [{v[0]:+.4f}, {v[1]:+.4f}, {v[2]:+.4f}]")

    fig = plot_robot(
        frames, q_deg,
        axis_length=args.axis_length,
        link_visuals=link_visuals,
        mesh_dir=mesh_dir,
        max_triangles=args.max_triangles,
    )

    if args.save:
        fig.savefig(args.save, dpi=150, bbox_inches="tight")
        print(f"\nSaved to {args.save}")
    else:
        plt.show()


# ──────────────────────────────────────────────────────────────────────
# Embedded URDF fallback
# ──────────────────────────────────────────────────────────────────────

EMBEDDED_URDF = """\
<?xml version="1.0" ?>
<robot name="so-101">
  <link name="base_link"/>
  <link name="shoulder_link"/>
  <link name="upper_arm_link"/>
  <link name="forearm_link"/>
  <link name="wrist_link"/>
  <link name="hand_link"/>
  <link name="Fixed_Jaw"/>
  <link name="Moving_Jaw"/>

  <joint name="Rotation" type="revolute">
    <parent link="base_link"/>
    <child link="shoulder_link"/>
    <origin xyz="0 0 0.0456" rpy="0 0 0"/>
    <axis xyz="0 0 -1"/>
    <limit lower="-1.6" upper="1.6"/>
  </joint>

  <joint name="Pitch" type="revolute">
    <parent link="shoulder_link"/>
    <child link="upper_arm_link"/>
    <origin xyz="0 0 0.0405" rpy="0 0 0"/>
    <axis xyz="0 -1 0"/>
    <limit lower="-1.57" upper="1.57"/>
  </joint>

  <joint name="Elbow" type="revolute">
    <parent link="upper_arm_link"/>
    <child link="forearm_link"/>
    <origin xyz="0.10825 0 0" rpy="0 0 0"/>
    <axis xyz="0 -1 0"/>
    <limit lower="-1.6" upper="1.4"/>
  </joint>

  <joint name="Wrist_Pitch" type="revolute">
    <parent link="forearm_link"/>
    <child link="wrist_link"/>
    <origin xyz="0.096 0 0" rpy="0 0 0"/>
    <axis xyz="0 -1 0"/>
    <limit lower="-1.67" upper="1.67"/>
  </joint>

  <joint name="Wrist_Roll" type="revolute">
    <parent link="wrist_link"/>
    <child link="hand_link"/>
    <origin xyz="0 0 0" rpy="0 0 0"/>
    <axis xyz="-1 0 0"/>
    <limit lower="-3.14" upper="3.14"/>
  </joint>

  <joint name="Jaw" type="revolute">
    <parent link="hand_link"/>
    <child link="Fixed_Jaw"/>
    <origin xyz="0.0486 0 0" rpy="0 0 0"/>
    <axis xyz="0 -1 0"/>
    <limit lower="-0.21" upper="1.5"/>
  </joint>

  <joint name="Moving_Jaw_joint" type="fixed">
    <parent link="Fixed_Jaw"/>
    <child link="Moving_Jaw"/>
    <origin xyz="0 0 0" rpy="0 0 0"/>
  </joint>
</robot>
"""


if __name__ == "__main__":
    main()
