
import bpy
import traceback

from .vortex_avatar_downloader import spawn_user


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
            msg = f"Failed to load avatar: {traceback.print_exc()}"
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

        layout.prop(
            context.scene,
            "vortex_user_id",
            text="User Id",
        )

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
    finally:
        pass


def unregister():
    try:
        del bpy.types.Scene.vortex_user_id

        # for cls in reversed(classes):
        #    bpy.utils.unregister_class(cls)
    finally:
        pass
