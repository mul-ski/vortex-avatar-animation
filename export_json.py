
import bpy
import json
import uuid
from mathutils import Matrix,Quaternion
import math


# =========================================================
# Coordinate conversion
# =========================================================

AXIS_CONVERSION = Matrix((
    (-1, 0, 0),
    (0, 0, 1),
    (0, 1, 0),
))


def convert_position(location):
    return AXIS_CONVERSION @ location


def convert_rotation(quaternion):
    """
    Convert a Blender rotation into the target coordinate system.

    R_target = C * R_blender * C^-1
    """

    blender_rotation = quaternion.to_matrix()

    target_rotation = (
        AXIS_CONVERSION
        @ blender_rotation
        @ AXIS_CONVERSION.inverted()
    )

    return target_rotation.to_quaternion()


def get_color(obj):
    """
    Get the color for an object using the following priority:

    1. Custom property "object_color"
    2. Diffuse color from the first material
    3. Object's Viewport Display > Color
    4. White
    """

    # 1. Check for custom property "object_color"
    if "object_color" in obj:
        color = obj["object_color"]

        return {
            "r": float(color[0]),
            "g": float(color[1]),
            "b": float(color[2]),
            "a": float(color[3]) if len(color) > 3 else 1.0,
        }

    # 2. Get color from the first material
    if obj.data.materials:
        material = obj.data.materials[0]
        color = material.diffuse_color

        return {
            "r": float(color[0]),
            "g": float(color[1]),
            "b": float(color[2]),
            "a": float(color[3]),
        }

    # 3. Fall back to Viewport Display > Color
    color = obj.color

    return {
        "r": float(color[0]),
        "g": float(color[1]),
        "b": float(color[2]),
        "a": float(color[3]),
    }


def export_object(obj):

    # -----------------------------------------------------
    # Position
    # -----------------------------------------------------

    position = convert_position(
        obj.matrix_world.translation
    )

    # -----------------------------------------------------
    # Rotation
    # -----------------------------------------------------

    rotation = convert_rotation(
        obj.matrix_world.to_quaternion()
    )

    # -----------------------------------------------------
    # Dimensions
    #
    # obj.dimensions is the object's WORLD-SPACE
    # bounding-box dimensions.
    #
    # Target axes:
    # X = Blender X
    # Y = Blender Z
    # Z = Blender Y
    #
    # The negative X direction doesn't affect dimensions.
    # -----------------------------------------------------

    dimensions = obj.dimensions

    target_dimensions = {
        "x": float(dimensions.x),
        "y": float(dimensions.z),
        "z": float(dimensions.y),
    }

    # -----------------------------------------------------
    # Material
    # -----------------------------------------------------

    color = get_color(obj)

    # Match a material name against the supported names.
    material_keywords = ("Plastic", "Paint", "Metal",
                         "Wood", "Grass", "Smooth")

    material = "Plastic"

    # Check all materials assigned to the object.
    for slot in obj.material_slots:
        if slot.material is None:
            continue

        material_name = slot.material.name
        material_name_lower = material_name.lower()

        for keyword in material_keywords:
            if (
                material_name_lower == keyword.lower()
                or material_name_lower.startswith(keyword.lower())
                or keyword.lower() in material_name_lower
            ):
                material = keyword
                break

        if material != "Plastic" or any(
            material_name_lower == keyword.lower()
            or material_name_lower.startswith(keyword.lower())
            or keyword.lower() in material_name_lower
            for keyword in material_keywords
        ):
            break

    # -----------------------------------------------------
    # Custom properties
    # -----------------------------------------------------

    cast_shadow = obj.visible_shadow  # bool(obj.get("cast_shadow", True))
    anchored = bool(obj.get("anchored", True))
    can_collide = bool(obj.get("can_collide", True))
    spawn_location = bool(obj.get("spawn_location", False))
    baseplate = bool(obj.get("baseplate", False))
    custom_appearance = bool(obj.get("custom_appearance", False))
    truss = bool(obj.get("truss", False))

    # -----------------------------------------------------
    # JSON object
    # -----------------------------------------------------

    return {
        "name": obj.name,

        "position": {
            "x": float(position.x),
            "y": float(position.y),
            "z": float(position.z),
        },

        "rotation": {
            "x": float(rotation.x),
            "y": float(rotation.y),
            "z": float(rotation.z),
            "w": float(rotation.w),
        },

        "scale": target_dimensions,

        "color": color,

        "material": material,
        "group": None,
        "cast_shadow": cast_shadow,
        "anchored": anchored,
        "can_collide": can_collide,
        "spawn_location": spawn_location,
        "baseplate": baseplate,
        "custom_appearance": custom_appearance,
        "truss": truss,
        "textures": [],
    }


def find_export_sun():
    """
    Find the Sun light to export.

    Priority:
    1. First SUN light with custom property "vortex_main_sun" == True
    2. Otherwise, the first SUN light in the scene
    3. None if there are no SUN lights
    """

    first_sun = None

    for obj in bpy.context.scene.objects:
        if obj.type != 'LIGHT' or obj.data.type != 'SUN':
            continue

        # Remember the first Sun as fallback.
        if first_sun is None:
            first_sun = obj

        # Prefer explicitly exportable suns.
        if bool(obj.get("vortex_main_sun", False)):
            return obj

    return first_sun


def color_to_rgba(color):
    """
    Convert a Blender RGB color to the target RGBA format.
    """

    return {
        "r": float(color[0]),
        "g": float(color[1]),
        "b": float(color[2]),
        "a": 1.0,
    }


SUN_ILLUMINANCE_MULTIPLIER = 1000.0


def get_sun_info():
    """
    Export the scene sun information.

    Defaults are used when no Blender Sun light exists.
    """

    # -----------------------------------------------------
    # Defaults
    # -----------------------------------------------------

    result = {
        "ambient_color": {
            "r": 1.0,
            "g": 1.0,
            "b": 1.0,
            "a": 1.0,
        },

        "brightness": 2000,

        "sun_color": {
            "r": 1.0,
            "g": 1.0,
            "b": 1.0,
            "a": 1.0,
        },

        "sun_illuminance": 8000,

        "sun_shadow_maps_enabled": True,

        "sun_rotation": {
            "x": -0.39447272,
            "y": 0.43916786,
            "z": 0.22334667,
            "w": 0.775654,
        },
    }

    # -----------------------------------------------------
    # Find Sun
    # -----------------------------------------------------

    sun = find_export_sun()

    if sun is None:
        return result

    sun_data = sun.data

    # -----------------------------------------------------
    # Sun color
    # -----------------------------------------------------

    result["sun_color"] = color_to_rgba(sun_data.color)

    # -----------------------------------------------------
    # Sun shadow maps
    # -----------------------------------------------------

    result["sun_shadow_maps_enabled"] = bool(sun_data.use_shadow)

    # -----------------------------------------------------
    # Sun rotation
    #
    # Use the Blender object's world-space quaternion.
    # -----------------------------------------------------

    rotation = convert_rotation(sun.matrix_world.to_quaternion()) @ Quaternion((1, 0, 0), math.radians(-90))

    result["sun_rotation"] = {
        "x": float(rotation.x),
        "y": float(rotation.y),
        "z": float(rotation.z),
        "w": float(rotation.w),
    }

    # fak ai

    result["sun_illuminance"] = float(sun_data.energy * 1000.0)
    result["brightness"] = float(
        sun_data.energy * 125.0
    )

    return result


# =========================================================
# Export operator
# =========================================================

class EXPORT_OT_vortex_json(bpy.types.Operator):

    bl_idname = "export_scene.vortex_json"
    bl_label = "Export Vortex Place JSON"
    bl_description = "Export objects to Vortex JSON format"

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to export file",
        subtype="FILE_PATH",
    )

    selected_only: bpy.props.BoolProperty(
        name="Selected Objects Only",
        description="Only export selected mesh objects",
        default=True,
    )

    def execute(self, context):

        if self.selected_only:
            objects = [
                obj
                for obj in context.selected_objects
                if obj.type == 'MESH'
            ]
        else:
            objects = [
                obj
                for obj in context.scene.objects
                if obj.type == 'MESH'
            ]

        export_data = {}

        try:
            export_data["project_version"] = 1
            export_data["project_id"] = uuid.uuid4().hex
            export_data["parts"] = [
                export_object(obj)
                for obj in objects
            ]
            export_data["lighting"] = get_sun_info()
            export_data["groups"] = []
        except Exception as e:

            self.report(
                {'ERROR'},
                f"Export failed: {e}"
            )

            return {'CANCELLED'}

        try:

            with open(
                self.filepath,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    export_data,
                    file,
                    indent=2,
                    ensure_ascii=False,
                )

        except Exception as e:

            self.report(
                {'ERROR'},
                f"File export failed: {e}"
            )

            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Exported {len(export_data)} object(s)"
        )

        return {'FINISHED'}

    def invoke(self, context, event):

        self.filepath = "export.json"

        context.window_manager.fileselect_add(self)

        return {'RUNNING_MODAL'}


# =========================================================
# Export menu
# =========================================================

def menu_export(self, context):

    self.layout.operator(
        EXPORT_OT_vortex_json.bl_idname,
        text="Vortex Place JSON (.json)"
    )


# =========================================================
# Registration
# =========================================================

classes = (
    EXPORT_OT_vortex_json,
)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            pass
    try:
        bpy.types.TOPBAR_MT_file_export.append(
            menu_export
        )
    finally:
        pass


def unregister():
    try:
        bpy.types.TOPBAR_MT_file_export.remove(
            menu_export
        )

        # for cls in reversed(classes):
        #    bpy.utils.unregister_class(cls)
    except Exception as e:
        pass


if __name__ == "__main__":
    register()
