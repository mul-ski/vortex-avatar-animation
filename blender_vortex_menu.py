
import bpy
import traceback

from . import vortex_ik
from .vortex_avatar_downloader import spawn_user


# ---------------------------------------------------------------------------
# IK toggle callbacks
# ---------------------------------------------------------------------------

def _rig_for_object(obj):
    """Return the Vortex rig that owns ``obj``, if there is one.

    Bodies have an Armature modifier and accessories are bone-parented, so
    clicking either of them in the viewport should still find the rig that
    the IK checkbox belongs to.
    """

    seen = set()

    while obj is not None and obj.name not in seen:
        if vortex_ik.is_vortex_rig(obj):
            return obj

        seen.add(obj.name)

        for modifier in getattr(obj, "modifiers", ()):
            if modifier.type == "ARMATURE":
                if vortex_ik.is_vortex_rig(modifier.object):
                    return modifier.object

        obj = obj.parent

    return None


def _context_rig(context):
    """The rig the IK checkbox should control, if the selection has one.

    The active object wins.  Otherwise a single selected rig, or the rig
    behind a selected body/accessory, is used.  With nothing selected (or
    with several different rigs in the selection) the checkbox falls back to
    the scene default for the next avatar.
    """

    view_layer = context.view_layer
    active = view_layer.objects.active if view_layer is not None else None

    rig = _rig_for_object(active)

    if rig is not None:
        return rig

    rigs = []

    for obj in context.selected_objects:
        candidate = _rig_for_object(obj)

        if candidate is not None and candidate not in rigs:
            rigs.append(candidate)

    if len(rigs) == 1:
        return rigs[0]

    return None


def _update_rig_ik(self, context):
    """Apply the checkbox to the rig it belongs to and remember the choice."""

    try:
        vortex_ik.apply_ik(self, self.vortex_use_ik)
    except Exception:
        traceback.print_exc()

    if not vortex_ik.supports_ik(self):
        return

    if vortex_ik.ik_enabled(self) != bool(self.vortex_use_ik):
        # The rig could not be changed right now (Edit Mode), so keep the
        # stored default as it was.
        return

    scene = context.scene

    if scene is not None:
        scene.vortex_use_ik = bool(self.vortex_use_ik)


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class VORTEXLOADER_OT_load_user_avatar(bpy.types.Operator):
    bl_idname = "vortex_loader.load_user_avatar"
    bl_label = "Load User Avatar"
    bl_description = "Load an avatar using its Vortex User ID"

    def execute(self, context):
        user_id = context.scene.vortex_user_id

        try:
            spawn_user(user_id)
        except Exception as error:
            traceback.print_exc()
            msg = f"Failed to load avatar: {error}"
            print(msg)
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}

        self.report({"INFO"}, f"Loaded avatar for User ID {user_id}")

        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Avatar Downloader Panel
# ---------------------------------------------------------------------------

class VORTEXLOADER_PT_avatar_downloader(bpy.types.Panel):
    bl_idname = "VORTEXLOADER_PT_avatar_downloader"
    bl_label = "Avatar Downloader"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Vortex Loader"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(
            scene,
            "vortex_user_id",
            text="User Id",
        )

        rig = _context_rig(context)
        old_layout = rig is not None and not vortex_ik.supports_ik(rig)

        if old_layout:
            layout.label(
                text="Reload this avatar to use IK.",
                icon="ERROR",
            )
        else:
            column = layout.column()
            column.enabled = not (rig is not None and rig.mode == "EDIT")

            if rig is not None:
                column.prop(
                    rig,
                    "vortex_use_ik",
                    text="Inverse Kinematics (Legs)",
                )
            else:
                column.prop(
                    scene,
                    "vortex_use_ik",
                    text="Inverse Kinematics (Legs)",
                )

            if rig is not None and rig.mode == "EDIT":
                layout.label(text="Exit Edit Mode to change IK.", icon="ERROR")

        layout.operator(
            VORTEXLOADER_OT_load_user_avatar.bl_idname,
            text="Load User Avatar",
            icon="USER",
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    VORTEXLOADER_OT_load_user_avatar,
    VORTEXLOADER_PT_avatar_downloader,
)


def register():
    try:
        # for cls in classes: # i think auto_load does that automatically for me right?
        #    bpy.utils.register_class(cls)

        bpy.types.Scene.vortex_user_id = bpy.props.IntProperty(
            name="User Id",
            description="Vortex User ID",
            default=95964,
            min=1,
        )

        bpy.types.Scene.vortex_use_ik = bpy.props.BoolProperty(
            name="Inverse Kinematics (Legs)",
            description=(
                "Move the legs with the foot gems instead of rotating the leg "
                "bones. Also used as the default for newly loaded avatars"
            ),
            default=False,
        )

        bpy.types.Object.vortex_use_ik = bpy.props.BoolProperty(
            name="Inverse Kinematics (Legs)",
            description=(
                "Move the legs with the foot gems instead of rotating the leg "
                "bones"
            ),
            default=False,
            update=_update_rig_ik,
        )
    finally:
        pass


def unregister():
    try:
        del bpy.types.Scene.vortex_user_id
        del bpy.types.Scene.vortex_use_ik
        del bpy.types.Object.vortex_use_ik

        # for cls in reversed(classes):
        #    bpy.utils.unregister_class(cls)
    finally:
        pass
