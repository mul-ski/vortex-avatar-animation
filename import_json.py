
import bpy
import json
import os
import traceback

from mathutils import Vector, Quaternion, Matrix


# ------------------------------------------------------------------------
# Template material configuration
# ------------------------------------------------------------------------

from . import constants


def get_material(name):
    """
    Get a material by name.

    1. Return it if it already exists in the current .blend.
    2. Otherwise append it from the template .blend.
    3. If the template doesn't contain it, create a fallback material.
    """

    name = "Vortex" + name

    # ------------------------------------------------------------
    # Already exists in the current file
    # ------------------------------------------------------------

    material = bpy.data.materials.get(name)

    if material is not None:
        return material

    # ------------------------------------------------------------
    # Try to append from template blend
    # ------------------------------------------------------------

    template_path = constants.TEMPLATE_BLEND

    if os.path.isfile(template_path):
        with bpy.data.libraries.load(template_path, link=False) as (data_from, data_to):
            if name in data_from.materials:
                data_to.materials = [name]

        material = bpy.data.materials.get(name)

        if material is not None:
            return material

    # ------------------------------------------------------------
    # Fallback material
    # ------------------------------------------------------------

    material = bpy.data.materials.new(name=name)

    # Use a Principled BSDF so the fallback works normally in
    # Blender's material/renderer pipeline.
    material.use_nodes = True

    nodes = material.node_tree.nodes
    principled = nodes.get("Principled BSDF")

    if principled is not None:
        # Neutral fallback appearance.
        principled.inputs["Base Color"].default_value = (
            0.8,
            0.8,
            0.8,
            1.0,
        )

        principled.inputs["Roughness"].default_value = 0.5

    return material


# ------------------------------------------------------------------------
# Coordinate conversion
# ------------------------------------------------------------------------


# Source coordinate system:
#
#       Y = UP
#       X = RIGHT
#       Z = FORWARD
#
# Blender:
#
#       Z = UP
#       X = RIGHT
#       -Y = FORWARD
#
# Therefore:
#
#       Blender X = Source X
#       Blender Y = -Source Z
#       Blender Z = Source Y
#
# This is a +90 degree rotation around X.
SOURCE_TO_BLENDER = Matrix((
    (1.0,  0.0, 0.0),
    (0.0,  0.0, -1.0),
    (0.0,  1.0, 0.0),
))


def convert_position(value):
    source = Vector((
        value["x"],
        value["y"],
        value["z"],
    ))

    return SOURCE_TO_BLENDER @ source


def convert_scale(value):
    """
    Dimensions need the same axis conversion, but dimensions
    are unsigned, so there is no sign on the axes.
    """

    return Vector((
        value["x"],
        value["z"],
        value["y"],
    ))


def convert_rotation(value):
    """
    Convert the source Y-up quaternion into Blender's Z-up
    coordinate system.

    Source JSON quaternion is:
        x, y, z, w

    Blender Quaternion constructor is:
        w, x, y, z
    """

    source_quat = Quaternion((
        value["w"],
        value["x"],
        value["y"],
        value["z"],
    ))

    basis_rotation = SOURCE_TO_BLENDER.to_4x4().to_quaternion()

    return (
        basis_rotation
        @ source_quat
        @ basis_rotation.inverted()
    )


# ------------------------------------------------------------------------
# Custom properties
# ------------------------------------------------------------------------

def set_custom_property(obj, name, value):
    """
    Store JSON data as a Blender custom property.

    Blender ID properties support primitive values, arrays and nested
    dictionaries in most modern Blender versions. For values that
    cannot be represented directly, fall back to JSON text.
    """

    if value is None:
        # Blender versions differ in their handling of None in ID props.
        # Store it as an explicit null marker.
        obj[name] = None
        return

    try:
        obj[name] = value
    except (TypeError, ValueError):
        # Lists/dictionaries/etc. that cannot be represented directly.
        obj[name] = json.dumps(value)


# ------------------------------------------------------------------------
# Project metadata
# ------------------------------------------------------------------------

def store_project_metadata(data):
    """
    Keep the values that describe the whole project, so the exporter can
    write the same place back out instead of inventing new ones.
    """

    scene = bpy.context.scene

    scene["vortex_project_version"] = int(
        data.get("project_version", 1)
    )

    project_id = data.get("project_id")

    if project_id:
        scene["vortex_project_id"] = str(project_id)
    elif "vortex_project_id" in scene:
        del scene["vortex_project_id"]

    groups = data.get("groups")

    if groups:
        scene["vortex_groups_json"] = json.dumps(groups)
    elif "vortex_groups_json" in scene:
        del scene["vortex_groups_json"]


# ------------------------------------------------------------------------
# Part creation
# ------------------------------------------------------------------------

def create_cube_template():
    """
    Build one unit cube and keep its mesh as a template.

    Copying a mesh is much faster than calling the cube operator and the
    UV operator for every part, and every part starts as the same cube.
    """

    bpy.ops.mesh.primitive_cube_add(
        size=1.0,
        location=(0.0, 0.0, 0.0),
    )

    template = bpy.context.object.data
    bpy.data.objects.remove(bpy.context.object, do_unlink=True)

    return template


def cube_face_axes(template):
    """
    Remember the dominant axis of every face.

    The projection axis depends on the face normal, and scaling the cube
    by positive dimensions cannot change which axis is dominant.
    """

    axes = []

    for polygon in template.polygons:
        axes.append(
            max(
                range(3),
                key=lambda index: abs(polygon.normal[index]),
            )
        )

    return axes


def build_part_mesh(template, face_axes, dimensions):
    """
    Create the scaled cube mesh for one part, including its UVs.

    This reproduces what the old code did with the cube operator and
    bpy.ops.uv.cube_project(cube_size=1.0): each face is projected along
    its dominant axis, and the position is offset by half a unit.
    """

    mesh = template.copy()

    mesh.transform(
        Matrix.Diagonal(
            (
                float(dimensions.x),
                float(dimensions.y),
                float(dimensions.z),
            )
        ).to_4x4()
    )

    uv_layer = mesh.uv_layers.active

    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name="UVMap")

    uv_data = uv_layer.data

    for polygon, axis in zip(mesh.polygons, face_axes):
        for loop_index in polygon.loop_indices:
            coordinate = mesh.vertices[
                mesh.loops[loop_index].vertex_index
            ].co

            if axis == 0:
                uv = (coordinate.y + 0.5, coordinate.z + 0.5)
            elif axis == 1:
                uv = (coordinate.x + 0.5, coordinate.z + 0.5)
            else:
                uv = (coordinate.x + 0.5, coordinate.y + 0.5)

            uv_data[loop_index].uv = uv

    return mesh


def create_part(part, collection=None, template=None, face_axes=None):
    """
    Create one cube from a JSON part definition.
    """

    name = part.get("name", "Part")

    # ------------------------------------------------------------
    # Create cube
    # ------------------------------------------------------------

    dimensions = convert_scale(part["scale"])

    own_template = template is None

    if own_template:
        template = create_cube_template()
        face_axes = cube_face_axes(template)

    mesh = build_part_mesh(template, face_axes, dimensions)

    if own_template:
        bpy.data.meshes.remove(template)

    obj = bpy.data.objects.new(name, mesh)

    if collection is None:
        bpy.context.scene.collection.objects.link(obj)
    else:
        collection.objects.link(obj)

    # ------------------------------------------------------------
    # Transform
    # ------------------------------------------------------------

    obj.location = convert_position(part["position"])
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = convert_rotation(part["rotation"])

    # ------------------------------------------------------------
    # Color
    # ------------------------------------------------------------

    color = part.get("color")
    rgba = (1.0, 1.0, 1.0, 1.0)

    if color:
        rgba = (
            float(color["r"]),
            float(color["g"]),
            float(color["b"]),
            float(color["a"]),
        )

    # Blender object viewport/display color.
    obj.color = rgba

    # Also preserve the original JSON color.
    obj["object_color"] = rgba

    ui = obj.id_properties_ui("object_color")
    ui.update(
        subtype="COLOR",
        min=0.0,
        max=1.0,
    )

    # ------------------------------------------------------------
    # Material
    # ------------------------------------------------------------

    material_name = part.get("material")

    if material_name:
        material = get_material(material_name)

        # Replace existing materials with the prepared material.
        obj.data.materials.clear()
        obj.data.materials.append(material)

    # ------------------------------------------------------------
    # Shadow visibility
    # ------------------------------------------------------------

    if "cast_shadow" in part:
        obj.visible_shadow = bool(part["cast_shadow"])

    # ------------------------------------------------------------
    # Additional JSON data as custom properties
    # ------------------------------------------------------------

    # Older builds read the JSON key with a typo, so a .blend saved
    # from one of those may still carry "custom_appearence".
    if (
        "custom_appearance" not in part
        and "custom_appearence" in part
    ):
        part = dict(part)
        part["custom_appearance"] = part["custom_appearence"]

    custom_properties = (
        "group",
        "anchored",
        "can_collide",
        "spawn_location",
        "baseplate",
        "custom_appearance",
        "truss",
        "textures",
        "point_light",
        "spot_light",
    )

    for property_name in custom_properties:
        if property_name in part:
            set_custom_property(
                obj,
                property_name,
                part[property_name],
            )

    return obj


# ------------------------------------------------------------------------
# Lighting
# ------------------------------------------------------------------------

def create_sun(lighting, collection=None):
    """
    Create the imported directional/sun light.
    """

    bpy.ops.object.light_add(
        type="SUN",
        location=(0.0, 0.0, 0.0),
    )

    sun = bpy.context.object
    sun.name = "Imported Sun"

    if collection is not None:
        for old_collection in list(sun.users_collection):
            old_collection.objects.unlink(sun)

        collection.objects.link(sun)

    light = sun.data

    # ------------------------------------------------------------
    # Color
    # ------------------------------------------------------------

    sun_color = lighting.get("sun_color")

    if sun_color:
        light.color = (
            sun_color["r"],
            sun_color["g"],
            sun_color["b"],
        )

    # ------------------------------------------------------------
    # Energy
    # ------------------------------------------------------------

    #
    # JSON:
    #
    #     sun_illuminance = 8000
    #
    # Blender:
    #
    #     energy = 8
    #
    light.energy = lighting.get("sun_illuminance", 0.0) / 1000.0

    # ------------------------------------------------------------
    # Shadow maps
    # ------------------------------------------------------------

    light.use_shadow = bool(
        lighting.get("sun_shadow_maps_enabled", True)
    )

    # ------------------------------------------------------------
    # Ambient light and brightness
    #
    # Blender has no direct equivalent, so keep the JSON values on the
    # sun object for the exporter to write back.
    # ------------------------------------------------------------

    ambient = lighting.get("ambient_color")

    if ambient:
        sun["vortex_ambient_color"] = (
            float(ambient["r"]),
            float(ambient["g"]),
            float(ambient["b"]),
            float(ambient.get("a", 1.0)),
        )

    brightness = lighting.get("brightness")

    if brightness is not None:
        sun["vortex_brightness"] = float(brightness)

    # ------------------------------------------------------------
    # Rotation
    # ------------------------------------------------------------

    sun_rotation = lighting.get("sun_rotation")

    if sun_rotation:
        sun.rotation_mode = "QUATERNION"
        sun.rotation_quaternion = convert_rotation(sun_rotation)

    # ------------------------------------------------------------
    # Marker
    # ------------------------------------------------------------

    sun["vortex_main_sun"] = True

    return sun


# ------------------------------------------------------------------------
# Import JSON
# ------------------------------------------------------------------------

def import_json(filepath):
    """
    Import the complete JSON scene.
    """

    with open(filepath, "r", encoding="utf-8") as file:
        data = json.load(file)

    # ------------------------------------------------------------
    # Project metadata
    # ------------------------------------------------------------

    store_project_metadata(data)

    # ------------------------------------------------------------
    # Create import collection
    # ------------------------------------------------------------

    collection_name = "Imported Vortex Project"

    collection = bpy.data.collections.get(collection_name)

    if collection is None:
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)

    # ------------------------------------------------------------
    # Parts
    # ------------------------------------------------------------

    parts = data.get("parts", [])

    template = create_cube_template()
    face_axes = cube_face_axes(template)

    # The old cube operator deselected everything it did not create,
    # so keep that behaviour instead of adding to the selection.
    for existing in bpy.context.selected_objects:
        existing.select_set(False)

    last_part = None

    try:
        for part in parts:
            last_part = create_part(
                part,
                collection=collection,
                template=template,
                face_axes=face_axes,
            )
    finally:
        bpy.data.meshes.remove(template)

    if last_part is not None:
        last_part.select_set(True)
        bpy.context.view_layer.objects.active = last_part

    # ------------------------------------------------------------
    # Lighting
    # ------------------------------------------------------------

    lighting = data.get("lighting")

    if lighting:
        create_sun(
            lighting,
            collection=collection,
        )

    return len(parts)


# ------------------------------------------------------------------------
# Blender operator
# ------------------------------------------------------------------------

class IMPORT_OT_vortex_json(bpy.types.Operator):
    bl_idname = "import_scene.vortex_json"
    bl_label = "Import Vortex JSON"
    bl_description = "Import Vortex place project JSON file"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(
        name="JSON File",
        subtype="FILE_PATH",
    )

    filter_glob: bpy.props.StringProperty(
        default="*.json",
        options={"HIDDEN"},
    )

    def execute(self, context):
        try:
            count = import_json(self.filepath)
        except Exception as error:
            print(f"Import failed: {traceback.print_exc()}")
            self.report({"ERROR"}, f"Import failed: {error}")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Imported {count} parts",
        )

        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


# ------------------------------------------------------------------------
# Menu
# ------------------------------------------------------------------------

def menu_func_import(self, context):
    self.layout.operator(
        IMPORT_OT_vortex_json.bl_idname,
        text="Vortex Place JSON (.json)",
    )


# ------------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------------

classes = (
    IMPORT_OT_vortex_json,
)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            pass

    try:
        bpy.types.TOPBAR_MT_file_import.append(
            menu_func_import
        )
    finally:
        pass


def unregister():
    try:
        bpy.types.TOPBAR_MT_file_import.remove(
            menu_func_import
        )
    finally:
        pass

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            pass


if __name__ == "__main__":
    register()
