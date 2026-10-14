# Gas Giant Studio

![Gas Giant Studio](docs/studio.png)

Gas Giant Studio makes swirly, banded gas giant textures for Kerbal Space Program
planet mods (Kopernicus). It also makes the matching normal map, an EVE flow map, so the
cloud layer can drift along the bands, and if you like an emissive map for glowing bands.

The swirls are not painted on. Every pixel of the map is carried along a simulated
wind field, so the band edges roll up into soft Kelvin-Helmholtz curls with long, fine
filaments, the way they do on real gas giants.

## Download and start

**Windows:** download `GasGiantStudio-<version>-windows-x64.zip`, unzip it anywhere and
start `GasGiantStudio.exe`. You don't need to install Python.

**From source (any system):** install Python 3.9 or newer, then

```
pip install numpy pillow
python gasgiant_ui.py
```

On Windows you can also double-click `Run Gas Giant Studio.bat`. It installs numpy
and Pillow the first time.

Some antivirus programs are suspicious of new, unsigned apps made with PyInstaller. If
yours complains, you can run Gas Giant Studio from source instead; it's the same program.

## What it can do

- **Bands:** pick a colour for every band. Each colour starts at its latitude and runs
  north to the next one. **Colours from picture...** reads the band colours from a
  reference image: click the north end, then the south end of a line across the bands.
- **Band thickness:** make a band thicker or thinner along its length with a small curve
  editor. Pull it down to 0% and the band stops there, so the bands next to it meet, like the
  dark belt that ends at Jupiter's Great Red Spot. The curls along its edges follow.
- **Glowing bands:** pick a band that glows. Everything that band is made of, including
  the bits that get rolled into curls and storms, goes into an emissive map in a glow
  colour of your choice (the band colour unless you pick another one), black everywhere
  else.
- **Night-side glow:** a heat glow over the whole planet for hot Jupiters. The darker,
  deeper clouds glow more, and the glow follows every swirl. It goes into the emissive map
  as well.
- **Curls:** rows of swirls along the band edges. You set their size, how far they roll
  up, their spacing and their spin. **Auto-place** puts them where the band colour changes.
- **Motion and Detail:** jet streaks, turbulence, thin light threads, soft patches and
  calm poles.
- **Storms:** small storm spots scattered over the planet, and big storms that you place
  yourself. A big storm works like a small one, only bigger: a spiral that winds the bands
  up, with a bright (or dark) centre. Stretch it into an oval, make the edge ragged, and
  give it spiral cloud arms if you like.
- **Poles:** a hexagon jet stream around a pole like Saturn's, or a ring of cyclones like
  Jupiter's, separately for the north and south pole. You set the size, number of sides
  or storms, spin, texture, dark eyes and colours.
- **Randomize:** every tab has its own Randomize button. **Surprise me** randomizes
  everything at once, and **Undo** (or Ctrl+Z) goes back.
- **Instant preview:** the bands show on a sphere right away while you edit. **Build**
  makes the real map.
- **Sizes:** 512, 1024, 2048, 4096, 8192 and 16384 pixels wide. The window shows about how
  long a build takes.
- **Export:** you choose the folder, the file names, the format and the size.

  | File | Formats |
  |---|---|
  | Colour map | DDS (BC1/DXT1 KSP-ready, BC3/DXT5, BC7), PNG, JPG, TGA, BMP |
  | Normal map | DDS (DXT5nm KSP-ready, BC5), PNG |
  | Flow map | `.truecolor` (EVE), PNG |
  | Emissive map | DDS (BC1/DXT1 KSP-ready, BC3/DXT5, BC7), PNG |
  | Preview sheet | PNG, JPG |

- **Flow Map Maker:** makes EVE flow maps for **any** gas giant texture, including ones
  you didn't make here. It finds the bands, lets neighbouring bands flow in opposite
  directions and adds storm swirls where you click. It shows the result as arrows or as
  a looping animation.

![Polar features](docs/poles.png)

![Night-side glow](docs/night_glow.png)

![Flow Map Maker](docs/flow_maps.png)

## Using the files in KSP

Which DDS format to pick:

| Map | Format | When |
|---|---|---|
| Colour, emissive | BC1 / DXT1 | the default; what KSP uses out of the box |
| Colour, emissive | BC7 | best quality, twice the file size |
| Colour, emissive | BC3 / DXT5 | when you need an alpha channel |
| Normal | DXT5nm | the default; for KSP's own planet shaders |
| Normal | BC5 | for shaders that ask for a BC5 normal map |

BC5 and BC7 need a texture loader that can read them, such as KSPTextureLoader.

DDS files are flipped upside down on export, because KSP expects that. Turn it off in
the export window if you need the files for something else.

A Kopernicus scaled-space body uses the colour and normal map like this:

```
ScaledVersion
{
	type = Atmospheric
	OnDemand
	{
		texture = MyPlanets/Textures/MyGiant_color.dds
		normals = MyPlanets/Textures/MyGiant_normal.dds
	}
}
```

To make the clouds move, give the planet an EVE cloud layer that uses the colour map as
its texture and the flow map as its `_FlowMap`:

```
EVE_CLOUDS
{
	OBJECT
	{
		name = MyGiant-clouds
		body = MyGiant
		altitude = 20000
		settings
		{
			_MainTex
			{
				value = MyPlanets/Textures/MyGiant_color
			}
			_FlowMap
			{
				speed = 0.06
				displacement = 0.2
				texture
				{
					value = MyPlanets/Textures/GiantFlow/MyGiant_flow
				}
			}
		}
	}
}
```

`speed` and `displacement` decide how fast and how far the clouds move in game. The
animation in the Flow Map Maker is only an approximation of that.

The emissive map is added on top of the planet's colours, so a mod that draws an
additive emissive layer on the scaled planet is needed, for example
`VertexColorMapEmissive` from DuckweedUtils:

```
ScaledVersion
{
	VertexColorMapEmissive
	{
		blendMode = Additive
		map = MyPlanets/Textures/MyGiant_emissive.dds
		brightness = 0.5
	}
}
```

The preview sheet shows the glow added to the planet, strongest on the night side. With
night-side glow on, the preview lights the planet from the side so the night side shows.

## Presets

Every planet is one small JSON file in `presets/`. Eight examples come with it:

| Preset | Look |
|---|---|
| Lavender | pastel lavender and peach bands with lots of curls and a glowing peach band |
| NeptuneBlue | pale blue with one deep blue band of wispy streaks |
| NeptuneStorm | the same with a big dark spiral storm |
| TealBands | teal and cream bands with a big pale storm with two arms |
| Jovian | Jupiter-like belts with a red storm and a dark belt that stops at the storm |
| JovianPoles | the same with Jupiter's rings of cyclones at both poles |
| Saturnine | pale gold Saturn-like bands with a hexagon in the north and one big vortex in the south |
| Ember | a dark hot Jupiter whose deep belts glow red-orange on the night side |

Builds go to `out/<name>/` (4096) and `out/<name>_<size>/` (other sizes). Every build
also saves the settings it was made with.

## Command line

Everything the window does also works from the command line, which is handy for scripts.

```
python gasgiant.py make Lavender --res 1024
python gasgiant.py export Lavender --res 1024 --to export --color bc7 --normal dds --emissive png
python gasgiant.py new MyGiant --template NeptuneBlue
python gasgiant.py flow MyGiant
python gasgiant.py sample picture.jpg X1 Y1 X2 Y2 --lat 70 -70
```

`--budget 150` stops a build after about 150 seconds and saves its progress. Running the
same command again continues where it stopped. With the Windows release, use
`GasGiantStudio.exe make ...` in the same way.

## Building the Windows release yourself

Install Python 3 for Windows, then double-click `build_release.bat` in this folder. It
makes a separate build environment with numpy, Pillow and PyInstaller, builds
`GasGiantStudio.exe`, test-runs it once and packs it into
`release/GasGiantStudio-<version>-windows-x64.zip` inside this folder.

## Requirements

- Windows release: 64-bit Windows 10 or 11.
- From source: Python 3.9+ with numpy, Pillow and Tkinter. Tkinter comes with the normal
  Python installers.
- RAM: about 1.5 GB for 4096, about 3 GB for 8192, about 6 GB for 16384.
