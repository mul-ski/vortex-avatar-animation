
import requests
import tempfile
import bpy
import base64
import os
from . import constants
from . import vortex_ik

# CONSTANTS

VORTEX_SHAPES_COLLECTION_NAME = "VORTEX_SHAPES"

# print(requests.get("https://playvortex.io/api/users/outfits?ids=95964").json())


# HELPERS

def decode_base64_data(data: str) -> bytes:
    """Decode base64 data, optionally stripping a data URI prefix."""
    if data.startswith("data:"):
        _, data = data.split(",", 1)

    return base64.b64decode(data)


def hex_to_rgba(hex_color, alpha=None):
    hex_color = hex_color.lstrip("#")

    if len(hex_color) not in (6, 8):
        raise ValueError("Color must be 6 or 8 hex characters")

    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0

    if len(hex_color) == 8:
        a = int(hex_color[6:8], 16) / 255.0
    else:
        a = 1.0

    if alpha is not None:
        a = alpha

    return (r, g, b, a)


def image_from_png_bytes(
    png_data: bytes,
    preferred_name: str | None = None,
) -> bpy.types.Image:
    """Create a packed Blender Image from PNG byte data."""

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png_data)
        temp_path = f.name

    try:
        image = bpy.data.images.load(temp_path, check_existing=False)
        image.pack()

        if preferred_name:
            image.name = preferred_name

        return image
    finally:
        os.remove(temp_path)


def load_glb_from_bytes(glb_data: bytes) -> bpy.types.Object:
    """Load a GLB from bytes and return its single imported object."""

    collection = bpy.context.collection

    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
        f.write(glb_data)
        temp_path = f.name

    try:
        # Remember existing objects so we can identify what was imported.
        existing_objects = set(bpy.data.objects)

        bpy.ops.import_scene.gltf(filepath=temp_path)

        imported_objects = [
            obj for obj in bpy.data.objects
            if obj not in existing_objects
        ]

        if len(imported_objects) != 1:
            raise RuntimeError(
                f"Expected exactly one imported object, "
                f"got {len(imported_objects)}"
            )

        obj = imported_objects[0]

        # Remove it from whatever collection the importer placed it in.
        for old_collection in list(obj.users_collection):
            old_collection.objects.unlink(obj)

        # Link it to the currently active collection.
        collection.objects.link(obj)

        return obj

    finally:
        os.remove(temp_path)


def set_material_texture(
    object,
    texture_node_name,
    new_image,
):
    count = 0

    for slot in object.material_slots:
        material = slot.material

        if material is None or not material.use_nodes:
            continue

        for node in material.node_tree.nodes:
            if node.label == texture_node_name and node.type == 'TEX_IMAGE':
                node.image = new_image
                count += 1

    return count


# HTTP STUFF


def get_user_outfit(user_id=95964):
    return requests.get(f"{constants.API_DOMAIN}/users/outfits?ids={user_id}").json()[str(user_id)]


def load_clothing_images(clothing_ids):
    images = {}
    missing_ids = []

    # Check Blender's existing image datablocks.
    for clothing_id in clothing_ids:
        image_name = f"{constants.VORTEX_IMAGE_PREFIX}{clothing_id}"
        image = bpy.data.images.get(image_name)

        if image is not None:
            images[clothing_id] = image
        else:
            missing_ids.append(clothing_id)

    # Download only images that aren't already loaded.
    if missing_ids:
        ids_as_str = ",".join(map(str, missing_ids))

        response = requests.get(
            f"{constants.API_DOMAIN}/clothing/images?ids={ids_as_str}"
        )
        response.raise_for_status()

        clothing_data = response.json()

        for key, value in clothing_data.items():
            clothing_id = int(key)

            data = decode_base64_data(value)
            image = image_from_png_bytes(
                data,
                preferred_name=f"{constants.VORTEX_IMAGE_PREFIX}{key}",
            )

            images[clothing_id] = image

    # Preserve the exact order of clothing_ids.
    return images


def load_accessory_meshes(accessory_ids):
    ids_as_str = ",".join(map(str, accessory_ids))
    accessories = {}
    accessories_data = requests.get(
        f"{constants.API_DOMAIN}/meshes?ids={ids_as_str}"
    ).json()
    for key, value in accessories_data.items():
        mesh_id = int(key)

        data = decode_base64_data(value["data"])
        accessory_obj = load_glb_from_bytes(data)
        accessory_obj["accessory_id"] = mesh_id
        accessory_obj["accessory_type"] = value["type"]

        accessories[mesh_id] = accessory_obj

    return accessories


# DOING THE MAIN STUFF


def _load_template_collection():
    """
    Temporarily append the template collection from the bundled
    .blend file.

    Returns the loaded collection.
    """

    if not os.path.isfile(constants.TEMPLATE_BLEND):
        raise RuntimeError(
            f"Template blend file not found: {constants.TEMPLATE_BLEND}"
        )

    # If the collection somehow already exists, use it.
    existing_collection = bpy.data.collections.get(
        constants.VORTEX_RIGS_TEMPLATE_COLLECTION_NAME)

    if existing_collection is not None:
        return existing_collection

    with bpy.data.libraries.load(
        constants.TEMPLATE_BLEND,
        link=False,
    ) as (data_from, data_to):

        if constants.VORTEX_RIGS_TEMPLATE_COLLECTION_NAME not in data_from.collections:
            raise RuntimeError(
                f'Collection "{constants.VORTEX_RIGS_TEMPLATE_COLLECTION_NAME}" '
                f'not found in "{constants.TEMPLATE_BLEND}".'
            )

        data_to.collections = [constants.VORTEX_RIGS_TEMPLATE_COLLECTION_NAME]

    collection = bpy.data.collections.get(
        constants.VORTEX_RIGS_TEMPLATE_COLLECTION_NAME)

    if collection is None:
        raise RuntimeError(
            f'Failed to load "{constants.VORTEX_RIGS_TEMPLATE_COLLECTION_NAME}".'
        )

    return collection


def _remove_template_collection(collection):
    """
    Remove a temporary template collection and all objects/data exclusively
    associated with the collection.

    Only data-blocks referenced by objects in this collection are considered
    for orphan cleanup. Unrelated orphaned data elsewhere in the Blender file
    is left untouched.
    """

    # Collect all objects, including objects in nested collections.
    objects = list(collection.all_objects)

    # Snapshot data-blocks referenced by those objects before removing
    # anything. Removing objects later will change their user counts.
    meshes = set()
    armatures = set()
    materials = set()

    for obj in objects:
        data = obj.data

        if data is None:
            continue

        if obj.type == 'MESH':
            meshes.add(data)

        elif obj.type == 'ARMATURE':
            armatures.add(data)

        # Not every object data-block has a .materials collection.
        for material in getattr(data, "materials", ()):
            if material is not None:
                materials.add(material)

    # Remove the collection and unlink it from the scene.
    bpy.data.collections.remove(
        collection,
        do_unlink=True,
    )

    # Remove the template objects.
    for obj in objects:
        if obj.name in bpy.data.objects:
            bpy.data.objects.remove(
                obj,
                do_unlink=True,
            )

    # Only remove data-blocks that belonged to/referenced the deleted
    # template objects AND are now completely unused.
    for mesh in meshes:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    for armature in armatures:
        if armature.users == 0:
            bpy.data.armatures.remove(armature)

    for material in materials:
        if material.users == 0:
            bpy.data.materials.remove(material)


def _ensure_custom_shapes_in_view_layer(armature):
    """
    Link custom bone shape objects into a hidden collection in the scene.

    Pose bone custom shapes are only evaluated (and therefore only drawn)
    when their object is part of the view layer. The template keeps the
    shapes outside the temporary RIGS collection so they are not deleted
    with it, which means they arrive here unlinked. Adding them to a
    hidden-but-evaluated collection makes the rig display its gem shapes
    without adding visible helper objects to the scene.
    """

    shapes = {
        pose_bone.custom_shape
        for pose_bone in armature.pose.bones
        if pose_bone.custom_shape is not None
    }

    if not shapes:
        return

    scene = bpy.context.scene
    shape_collection = bpy.data.collections.get(
        VORTEX_SHAPES_COLLECTION_NAME
    )

    if shape_collection is None:
        shape_collection = bpy.data.collections.new(
            VORTEX_SHAPES_COLLECTION_NAME
        )
        scene.collection.children.link(shape_collection)

    # Hide the collection in the viewport, but keep it included so the
    # shape objects are still evaluated by the depsgraph.
    layer_collection = bpy.context.view_layer.layer_collection.children.get(
        shape_collection.name
    )

    if layer_collection is not None:
        layer_collection.hide_viewport = True

    for shape in shapes:

        if shape_collection not in shape.users_collection:
            shape_collection.objects.link(shape)

        # Custom shapes are helpers: never render or select them, but do
        # not disable the object itself (that removes it from evaluation).
        shape.hide_render = True
        shape.hide_select = True
        shape.hide_viewport = False

        try:
            shape.hide_set(True)
        except RuntimeError:
            pass


def _remove_unused_custom_shapes():
    """Drop custom shape objects left behind by deleted avatars."""

    shape_collection = bpy.data.collections.get(
        VORTEX_SHAPES_COLLECTION_NAME
    )

    if shape_collection is None:
        return

    for obj in list(shape_collection.objects):

        # Collection membership itself counts as a user, so unlink first
        # and only delete the object when nothing else references it.
        shape_collection.objects.unlink(obj)

        if obj.users != 0:
            shape_collection.objects.link(obj)
            continue

        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)

        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def spawn_character(armature_name="VORTEXIAN_RIG_MALE"):
    """
    Spawn a character from the bundled template .blend file.

    The template is loaded temporarily and removed after the
    character has been cloned.
    """

    template_collection = None

    try:
        # ---------------------------------------------------------
        # Load template.
        # ---------------------------------------------------------

        template_collection = _load_template_collection()

        # ---------------------------------------------------------
        # Find requested armature.
        # ---------------------------------------------------------

        armature = template_collection.objects.get(armature_name)

        if armature is None:
            raise RuntimeError(
                f'Armature "{armature_name}" not found '
                f'in "{constants.VORTEX_RIGS_TEMPLATE_COLLECTION_NAME}".'
            )

        if armature.type != "ARMATURE":
            raise RuntimeError(
                f'"{armature_name}" is not an armature.'
            )

        # ---------------------------------------------------------
        # Target collection.
        # ---------------------------------------------------------

        target_collection = bpy.context.collection

        if target_collection is None:
            raise RuntimeError("No active collection.")

        # ---------------------------------------------------------
        # Clone armature.
        # ---------------------------------------------------------

        new_armature = armature.copy()
        new_armature.data = armature.data.copy()

        target_collection.objects.link(new_armature)

        # ---------------------------------------------------------
        # Find all objects belonging to this character.
        # ---------------------------------------------------------

        objects_to_clone = []

        for obj in template_collection.all_objects:

            if obj == armature:
                continue

            parent = obj.parent

            while parent is not None:

                if parent == armature:
                    objects_to_clone.append(obj)
                    break

                parent = parent.parent

        # ---------------------------------------------------------
        # Clone objects.
        # ---------------------------------------------------------

        object_map = {}

        for obj in objects_to_clone:

            new_obj = obj.copy()

            # Copy object data.
            if obj.data is not None:
                new_obj.data = obj.data.copy()

            # Copy materials for mesh objects.
            if obj.type == "MESH":

                for i, material in enumerate(obj.data.materials):

                    if material is not None:
                        new_obj.data.materials[i] = material.copy()

            target_collection.objects.link(new_obj)

            object_map[obj] = new_obj

        # ---------------------------------------------------------
        # Rebuild parenting.
        # ---------------------------------------------------------

        for old_obj, new_obj in object_map.items():

            if old_obj.parent == armature:
                new_obj.parent = new_armature

            elif old_obj.parent in object_map:
                new_obj.parent = object_map[old_obj.parent]

            new_obj.matrix_parent_inverse = (
                old_obj.matrix_parent_inverse.copy()
            )

        # ---------------------------------------------------------
        # Fix armature modifiers.
        # ---------------------------------------------------------

        for old_obj, new_obj in object_map.items():

            for modifier in new_obj.modifiers:

                if modifier.type == "ARMATURE":
                    if modifier.object == armature:
                        modifier.object = new_armature

        # ---------------------------------------------------------
        # Point copied constraints at the new armature.
        # ---------------------------------------------------------

        for pose_bone in new_armature.pose.bones:

            for constraint in pose_bone.constraints:

                if getattr(constraint, "target", None) == armature:
                    constraint.target = new_armature

        # ---------------------------------------------------------
        # Leg IK mode.
        # ---------------------------------------------------------

        use_ik = bool(getattr(bpy.context.scene, "vortex_use_ik", False))

        vortex_ik.apply_ik(new_armature, use_ik, bake=False)

        try:
            new_armature.vortex_use_ik = vortex_ik.ik_enabled(new_armature)
        except AttributeError:
            pass

        # ---------------------------------------------------------
        # Spawn at 3D cursor.
        # ---------------------------------------------------------

        cursor_location = bpy.context.scene.cursor.location.copy()

        new_armature.matrix_world = armature.matrix_world.copy()

        offset = cursor_location - new_armature.location
        new_armature.location += offset

        # ---------------------------------------------------------
        # Make the custom bone shapes drawable.
        # ---------------------------------------------------------

        _ensure_custom_shapes_in_view_layer(new_armature)

        # ---------------------------------------------------------
        # Select spawned character.
        # ---------------------------------------------------------

        bpy.ops.object.select_all(action="DESELECT")

        new_armature.select_set(True)

        for obj in object_map.values():
            obj.select_set(True)

        bpy.context.view_layer.objects.active = new_armature

        return new_armature

    finally:
        # ---------------------------------------------------------
        # IMPORTANT:
        #
        # Always remove the temporary template, even if spawning
        # fails halfway through.
        # ---------------------------------------------------------

        if template_collection is not None:
            # Only remove it if it still exists.
            if template_collection.name in bpy.data.collections:
                _remove_template_collection(
                    template_collection
                )

        _remove_unused_custom_shapes()


def spawn_user(user_id=95964):
    outfit = get_user_outfit(user_id)

    # Spawn the appropriate character rig.
    rig_name = (
        "VORTEXIAN_RIG_FEMALE"
        if outfit["body_type"] == "female"
        else "VORTEXIAN_RIG_MALE"
    )
    armature = spawn_character(rig_name)
    body = armature.children[0]

    # Apply outfit properties to the body.
    for key, value in outfit.items():
        body[key] = value

    # Apply body colors.
    body_parts = ("head", "torso", "larm", "rarm", "lleg", "rleg")
    for part, color in zip(body_parts, outfit["body_colors"]):
        body[f"color_{part}"] = hex_to_rgba(color)

    # Store the user ID on both objects.
    body["user_id"] = user_id
    armature["user_id"] = user_id

    # Force Blender to update materials using the new colors.
    body.update_tag()

    # Load and apply clothing textures.
    texture_ids = {
        "shirt_id": "SHIRT_TEXTURE",
        "pant_id": "PANTS_TEXTURE",
        "face_id": "FACE_TEXTURE",
    }

    clothes_to_download = [
        outfit[key]
        for key in texture_ids
        if outfit[key] is not None
    ]

    if clothes_to_download:
        clothing = load_clothing_images(clothes_to_download)

        for outfit_key, material_name in texture_ids.items():
            clothing_id = outfit[outfit_key]

            if clothing_id is not None and clothing.get(clothing_id) is not None:
                set_material_texture(
                    body,
                    material_name,
                    clothing[clothing_id],
                )

    # Load and attach accessories.
    accessory_ids = outfit["accessory_ids"]

    if accessory_ids:
        accessories = load_accessory_meshes(accessory_ids)

        head_accessory_types = {"hat", "hair", "face_accessory"}

        for accessory_id, accessory in accessories.items():
            world_matrix = accessory.matrix_world.copy()

            # Offset the accessory by the 3D cursor's world-space position.
            world_matrix.translation += bpy.context.scene.cursor.location

            accessory.parent = armature
            accessory.parent_type = "BONE"

            accessory.parent_bone = (
                "Head"
                if accessory["accessory_type"] in head_accessory_types
                else "Torso"
            )

            # Preserve the accessory's world-space position.
            accessory.matrix_world = world_matrix

    armature.name = f"VORTEX_USER_{user_id}"

    return armature, body


if __name__ == "__main__":
    print("========= VORTEX DOWNLOADER TEST ====================================")
    print(get_user_outfit(95964))
    print(spawn_user(95964))
    print("========= VORTEX DOWNLOADER END =====================================")
