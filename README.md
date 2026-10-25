# [Vortex](https://playvortex.io) Blender Addon

A bad, partially vibecoded Vortex user avatar rig downloader. And project Import-Export blender addon.

Targets Blender 5.2+  (Tested only on Windows)


!["Vortex + Blender" artwork](github/map_showcase.jpg)


## Supported Features:

- Load any Vortex user avatar from just a User Id.
 - - (It directly downloads textures and meshes from [playvortex.io](https://playvortex.io))
![Avatar Downloader showcase](github/avatar_showcase.gif)

- Import Vortex Json place file.
- Export Vortex Json place file. (It assumes all objects are scaled cubes.)
- Reference-style animation rig, matching the official Vortex rig.
- Optional leg IK, switched with a checkbox in the sidebar (FK by default).

## Installation:

1. [Download](https://github.com/barbq205/blender-vortex/releases) the addon zip file
2. Import the downloaded .zip file by selecting it from (User) Preferences/Addons/Install from File
3. Use the addon.

## How to use:

Export is kinda unintuitive, FIRST SELECT EVERYTHING BEFORE CLICKING EXPORT

Everything else can be figured out easily.

### Leg IK

The **Inverse Kinematics (Legs)** checkbox under the User Id field switches the selected avatar between FK and IK; with nothing selected it sets the default for the next avatar. It is off by default, because imported Vortex animations key the leg bones.

- IK off: the `LeftIK` / `RightIK` foot gems follow the legs.
- IK on: dragging the gems moves the legs, and rotating the leg bones directly is ignored.

The legs are single bones (no knees), so the gems **aim** the legs: the foot lands on its gem only while the gem stays within one leg length of the hip. Switching modes bakes the current pose, so the legs never snap. Avatars loaded with an older version of the addon have to be loaded again to use IK.

## TODO

- Groups are not suppported.
- Add `.vrtx` project file support.
- Materials ORM textures are set up wrong. I don't know real names of the textures.
- Imported parts UV scale is wrong.
- Import/Exports are incomplete and inacurate.
- Import/Exports are extremely slow.
- The code is rushed shit.
- Clean up the code.
- I don't know how to make blender extensions. Idk how this one works.

![Dancing Vortex character](github/california_gurls.gif)


## pls contribute smth

