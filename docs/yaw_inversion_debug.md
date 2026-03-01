# Yaw Inversion Debug Log

## Problem

When the VLM picks a target to the **left** of the probe tip in the camera image, the arm rotates to the **right** (and vice versa). The yaw direction is fully reversed. The magnitude appears roughly correct.

## Current State of the Code

A `pos_cam_m[0] = -pos_cam_m[0]` hack is applied in `server.py:1576-1579` before `cam_to_robot()` to work around the issue. The root cause is not yet identified.

### Files involved in the pipeline

1. **`src/localize_from_aruco.py`** -- ArUco detection, PnP pose, `pixel_to_3d()` ray-plane intersection. Outputs `pos_cam_m` (3D point in camera frame).
2. **`src/robot_cam_calibration.py`** -- `make_R_cam_ee()` builds R_cam_ee, `compute_T_robot_cam()` composes FK with camera-EE transform, `cam_to_robot()` applies it.
3. **`src/constants.py`** -- Physical constants: tilt, tool offset, P_TIP_CAM_M.
4. **`src/motor_control.py`** -- Motor-to-URDF angle conversion (shoulder_pan sign=-1, offset=-3.0).
5. **`src/ik_solver.py`** -- Placo-based FK/IK with tool offset.
6. **`server.py`** -- Orchestrates the full pipeline in the `/api/execute/run-step` endpoint (lines ~1400-1660).

## What We Proved Mathematically

### R_base and tilt are correct

The camera-to-robot transform was verified numerically at zero config:

```
cam +X (right in image) -> robot [0, -3, -100] mm  = pure robot -Z  (correct: right)
cam +Y (down in image)  -> robot [-57, -82, 2.5] mm (forward+down, correct for 35 deg tilt)
cam +Z (optical axis)   -> robot [-82, +57, -1.5] mm (forward+up component from tilt)
```

Wait -- the `cam +Z` maps to robot `[-82, +57, -1.5]`. The +57 in Y means the optical axis has an **upward** component in robot frame. But the camera tilts **downward** toward the workspace. After further analysis:

With `alpha = +35` (current):
```
cam +Z (optical) in robot: [-81.9, -57.4, 0]  (forward + DOWN) -- CORRECT
cam +Y (down)    in robot: [+57.4, -81.9, 0]  (has forward component from tilt)
cam +X (right)   in robot: [0, 0, -100]        (pure right) -- CORRECT
```

This was verified with a clean analytical computation (no T_cam_ee translation involved, just rotations). The R_base mapping is:
```
R_base = [[0, 0, 1],    # cam_X = +EE_Z  (right)
           [0, -1, 0],   # cam_Y = -EE_Y  (down)
           [1, 0, 0]]    # cam_Z = +EE_X  (forward)
```

### Round-trip transform is exact

```python
# Target at tip position of pan=+20 URDF
p_target_cam = inv(T_robot_cam) @ [tip20; 1]  # robot -> cam
p_recovered  = T_robot_cam @ [p_target_cam; 1] # cam -> robot
# Error: [0, 0, 0] mm -- exact round-trip
```

### Motor sign conversion is symmetric

```
motor_to_urdf: urdf = sign * motor + offset     (shoulder_pan: sign=-1, offset=-3.0)
urdf_to_motor: motor = sign * (urdf - offset)   (inverse)
```

No leakage -- URDF space is used for FK/IK/trajectory, motor-native only at read/write boundaries.

### EE frame at zero config

```
EE +X = [-1, 0, 0]    in robot base  (probe points BACKWARD in robot base!)
EE +Y = [0, +1, 0]    in robot base  (up)
EE +Z = [0, -0.03, -1] in robot base (roughly -Z = right)
```

Note: EE +X = robot -X at zero config. This is correct per the URDF -- the arm extends forward along robot -X when all joints are zero.

## What We Tested

| Test | R_base | Tilt alpha | Result |
|------|--------|------------|--------|
| Original (A) | `[[0,0,1],[0,-1,0],[1,0,0]]` | `+35` | Yaw inverted |
| Test 1 (B) | `[[0,0,-1],[0,1,0],[1,0,0]]` | `+35` | Worse than original |
| Test 2 (A) | `[[0,0,1],[0,-1,0],[1,0,0]]` | `-35` | More off than original |
| Column mirror in ArUco | Original A, `+35` | Mirrored col index | Still inverted |
| cam_X negate hack | Original A, `+35` | `pos_cam[0] *= -1` | **UNTESTED** |

## Key Diagnostic Data (from a real run)

```
Target in camera frame: (4.8, -5.4, 259.7) mm
  -> Almost dead center in image (4.8mm right, 5.4mm up)
  -> But user says target was to the LEFT of the probe tip

Target in robot frame:  (-78.8, -110.0, 123.9) mm
Current tip:            (-36.6, -146.5, 226.6) mm
Delta:                  (-42.2, +36.6, -102.7) mm
```

The cam_X value is **+4.8mm** (right) but the target is visually to the **left** of the tip. This means the ArUco 3D localization itself produces a flipped X, before the camera-to-robot transform is even involved.

## Theories for Root Cause

### Theory 1: ArUco board frame X-axis is flipped (MOST LIKELY)

The user confirmed:
- Marker ID 0 is at the **top-right** of the camera image
- IDs increase going to the **left**

The code assumes IDs increase to the right (`x0 = col * stride`), making board +X point left in the camera image. When PnP solves for the board pose, the resulting R includes this left-pointing X-axis. Then `pixel_to_3d` expresses the intersection point in camera frame, and the X component is inverted relative to the image.

**However**, we tried mirroring the column index and it didn't fix it. Possible reasons:
- The mirror changes where PnP thinks each marker is in 3D space, which changes the solved R and t. The new R might compensate and produce the same camera-frame result.
- The mirror was applied but the markers used (IDs 53, 28, 61) might have a layout where mirroring doesn't change the relative geometry much.
- We need to also flip the TL/TR/BL/BR corner order when mirroring, not just the position.

### Theory 2: OpenCV ArUco corner ordering vs. physical marker orientation

OpenCV's ArUco detector returns corners in the order TL, TR, BR, BL **of the marker as printed**. If the physical marker is viewed from behind (camera on the same side as the marker face), the corners are in the expected order. But if the sheet is placed face-down, or the markers are generated with a different origin convention, the corner order could be rotated or flipped, causing PnP to solve the wrong pose.

### Theory 3: `pixel_to_3d` ray-plane intersection has a sign ambiguity

The function computes:
```python
pos_cam = t_ray * ray_cam          # intersection in camera frame
pos_board = R.T @ (pos_cam - t)    # transform to board frame
```

The `pos_cam` result should be correct regardless of board frame convention -- it's purely in camera frame. But if the board normal (Z-axis) points away from the camera instead of toward it, the intersection could be computed on the wrong side of the plane. The code does check `t_ray > 0`, but there might be a subtle sign issue with `plane_offset_m`.

### Theory 4: Camera intrinsics / undistortion flipping X

If the camera matrix `K` has an unusual convention or the distortion coefficients cause a horizontal flip, `cv2.undistortPoints` could return mirrored normalized coordinates. This is unlikely with a standard camera but worth checking.

### Theory 5: PIL-to-OpenCV color conversion flips the image

In `server.py:1499`:
```python
camera_bgr = np.array(camera_pil)[:, :, ::-1].copy()
```

This only reverses the color channels (RGB->BGR), not spatial dimensions. Should be fine.

### Theory 6: VLM keypoint coordinates are in a different convention

The VLM returns normalized `(y, x)` coordinates in 0-1000 range, converted to pixel `(u, v)` at lines 1475-1477:
```python
norm_y, norm_x = target_kp["point"]
pixel_u = norm_x / 1000.0 * cam_w
pixel_v = norm_y / 1000.0 * cam_h
```

If the VLM actually returns `(x, y)` instead of `(y, x)`, the u/v would be swapped, placing the pixel at the wrong location. This could cause the ArUco localization to compute a flipped position. **Worth verifying.**

## Recommended Next Steps

1. **Test the cam_X negate hack** -- if it fixes yaw, the problem is definitively in the ArUco board X direction.

2. **Print/log the pixel coordinates AND visually verify** -- draw a bright circle on the image at `(pixel_u, pixel_v)` and confirm it matches the VLM's intended target. If the circle is on the wrong side, the VLM coordinate convention is the issue.

3. **Verify ArUco board frame visually** -- draw the board X/Y axes on the image using the solved R, t from PnP. If the drawn X-axis points LEFT in the image, the board frame is flipped and needs correction.

4. **Check the generate_aruco_sheet.py** script to see how markers are laid out (row-major left-to-right vs right-to-left). Compare with the physical printed sheet.

5. **Test with a single known marker** -- place one ArUco marker with known ID at a known position, localize a point at a known offset, and check if the camera-frame X sign is correct.

## Physical Setup Reference

- Robot: SO-101 (SO-ARM100)
- Camera: wrist-mounted, 1280x720, fx=fy=553.9, cx=640, cy=360
- Camera tilt: 35 degrees downward toward tool tip
- Tool offset: 59mm along EE +X
- ArUco sheet: DICT_4X4_250, 8 cols x 12 rows, 18mm markers, 4.5mm gap
- ArUco sheet orientation from camera: ID 0 at top-right, IDs increase leftward
- Motor: shoulder_pan has sign=-1 (motor and URDF rotate opposite directions)
