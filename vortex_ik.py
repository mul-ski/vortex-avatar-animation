"""Optional leg IK for spawned Vortex rigs.

The bundled template ships as a plain FK rig.  Each foot gem is a small bone
at the ankle, pointing down, that follows its leg through copy location and
copy rotation constraints.  Posing the leg therefore keeps the gem on the
foot, exactly like the released rig.

Turning IK on removes those follow constraints and adds an IK constraint to
each leg aimed at its gem, so the gems drive the legs instead.  Turning IK
off does the reverse and bakes the solved pose into the leg rotations, so
nothing jumps when the mode changes.

No IK constraint is ever stored while the follow constraints exist: a target
bone that also feeds its own IK target forms a dependency cycle, and Blender
then stops evaluating the copy constraints after a file reload.  Constraints
are therefore added and removed at runtime rather than muted.
"""

import bpy

IK_NAME = "Vortex IK"
FOLLOW_NAME = "Vortex Foot Follow"
ROTATION_NAME = "Vortex Foot Rotation"
ROOT_NAME = "HumanoidRootPart"

LEG_MARKER_PAIRS = (
    ("Left Leg", "LeftIK"),
    ("Right Leg", "RightIK"),
)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def is_vortex_rig(obj):
    """True for an armature built from the addon's rig template."""

    if obj is None or obj.type != "ARMATURE":
        return False

    pose_bones = obj.pose.bones

    for leg_name, marker_name in LEG_MARKER_PAIRS:
        if leg_name not in pose_bones or marker_name not in pose_bones:
            return False

    return True


def supports_ik(obj):
    """True when the foot gems use the current ankle-handle layout.

    Avatars spawned before 0.0.11 keep their gem at the sole and hang it off
    the leg, so enabling IK on them would move the gem and aim the leg at the
    wrong point.  They have to be loaded again.
    """

    if not is_vortex_rig(obj):
        return False

    root = obj.data.bones.get(ROOT_NAME)

    if root is None:
        return False

    for _leg_name, marker_name in LEG_MARKER_PAIRS:
        marker = obj.data.bones.get(marker_name)

        if marker is None or marker.parent != root:
            return False

    return True


def ik_enabled(obj):
    """True when the leg IK constraints are present."""

    if not is_vortex_rig(obj):
        return False

    for leg_name, _marker_name in LEG_MARKER_PAIRS:
        leg = obj.pose.bones[leg_name]

        for con in leg.constraints:
            if con.name == IK_NAME:
                return True

    return False


def _ik_constraint(leg):
    for con in leg.constraints:
        if con.name == IK_NAME:
            return con

    return None


def _pairs(obj):
    return [
        (obj.pose.bones[leg_name], obj.pose.bones[marker_name])
        for leg_name, marker_name in LEG_MARKER_PAIRS
    ]


# ---------------------------------------------------------------------------
# Constraint building
# ---------------------------------------------------------------------------

def _add_follow_constraints(armature_object, marker, leg):
    follow = marker.constraints.get(FOLLOW_NAME)

    if follow is None:
        follow = marker.constraints.new("COPY_LOCATION")
        follow.name = FOLLOW_NAME

    follow.target = armature_object
    follow.subtarget = leg.name
    follow.head_tail = 1.0
    follow.influence = 1.0
    follow.mute = False

    rotate = marker.constraints.get(ROTATION_NAME)

    if rotate is None:
        rotate = marker.constraints.new("COPY_ROTATION")
        rotate.name = ROTATION_NAME

    rotate.target = armature_object
    rotate.subtarget = leg.name
    rotate.influence = 1.0
    rotate.mute = False

    # A freshly created copy constraint is not always evaluated until one of
    # its properties changes, so nudge the value it already has.
    for value in (0.0, 1.0):
        follow.head_tail = value
        bpy.context.view_layer.update()


def _add_ik_constraint(armature_object, leg, marker):
    ik = _ik_constraint(leg)

    if ik is None:
        ik = leg.constraints.new("IK")
        ik.name = IK_NAME

    ik.target = armature_object
    ik.subtarget = marker.name
    ik.chain_count = 1
    ik.use_tail = True
    ik.use_stretch = False
    ik.influence = 1.0
    ik.mute = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_ik(obj, enabled, bake=True):
    """Switch leg IK on or off for ``obj``.

    ``bake`` keeps the current pose: the gems are placed where the feet are
    before IK is enabled, and the solved leg rotations are written to the
    bones before IK is removed.

    Returns True when the rig was changed, False when it is not a usable
    Vortex rig.
    """

    if not is_vortex_rig(obj):
        return False

    if not supports_ik(obj):
        return False

    if obj.mode not in {"OBJECT", "POSE"}:
        return False

    pairs = _pairs(obj)
    enabled = bool(enabled)

    if enabled == ik_enabled(obj):
        return False

    bpy.context.view_layer.update()

    if enabled:
        for leg, marker in pairs:
            saved = marker.matrix.copy()

            for name in (FOLLOW_NAME, ROTATION_NAME):
                con = marker.constraints.get(name)

                if con is not None:
                    marker.constraints.remove(con)

            if bake:
                marker.matrix = saved

        bpy.context.view_layer.update()

        for leg, marker in pairs:
            _add_ik_constraint(obj, leg, marker)

    else:
        saved = {}

        for leg, _marker in pairs:
            ik = _ik_constraint(leg)

            if ik is None:
                continue

            saved[leg.name] = leg.matrix.copy()
            leg.constraints.remove(ik)

        bpy.context.view_layer.update()

        if bake:
            for leg, _marker in pairs:
                matrix = saved.get(leg.name)

                if matrix is not None:
                    leg.matrix = matrix

            bpy.context.view_layer.update()

        for leg, marker in pairs:
            _add_follow_constraints(obj, marker, leg)

    bpy.context.view_layer.update()

    return True


def set_scene_ik(scene, enabled):
    """Store the mode and apply it to the active rig when there is one."""

    scene.vortex_use_ik = bool(enabled)

    obj = bpy.context.view_layer.objects.active

    if is_vortex_rig(obj):
        apply_ik(obj, bool(enabled))

    return scene.vortex_use_ik
