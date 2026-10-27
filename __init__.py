
bl_info = {
    "name": "Vortex Loader",
    "blender": (5, 2, 0),
    "version": (0, 0, 14),
    "category": "Object",
}

from . import auto_load

try:
    auto_load.init()

    def register():
        auto_load.register()

    def unregister():
        auto_load.unregister()

    if __name__ == "__main__":
        print("__init__.py was executed directly")

except Exception as e:
    print(f"Error auto_load {__name__}: {e}")
