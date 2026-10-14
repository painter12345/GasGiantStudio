# Changelog

## 1.1.3

- Night-side glow (Bands tab): a heat glow over the whole planet for hot Jupiters. Darker
  clouds are deeper and hotter, so they glow more, and the glow follows every swirl and
  storm. Strength, how much more the dark clouds glow, cooler poles, hot and cool patches,
  and a dim and a bright glow colour can be set. It goes into the emissive map, together
  with any glowing bands.
- With night-side glow on, the instant preview and the preview sheet light the planet from
  the side, so the glowing night side shows.
- New example preset: Ember, a dark hot Jupiter with a red-orange night-side glow.
- Planets without night-side glow come out exactly as before.

## 1.1.2

- Polar features, on a new Poles tab. Each pole can get:
  - a **Hexagon**: a jet stream with straight sides around the pole, like Saturn's, with
    a spinning storm inside. Latitude, number of sides, roundness, rotation, jet speed,
    band width and brightness, wobble, inner turns and spin can be set.
  - **Cyclones**: a ring of round storms around the pole with one in the middle, like
    Jupiter's. Ring latitude, count, size, centre storm on/off, rotation, turns, spin and
    the edge of the polar cap can be set.
  - Both have cloud texture, dark eyes and their own cap, band, texture and eye colours.
    Colours left on auto follow the band at that pole.
- The instant preview shows the poles from above when a polar feature is on.
- "Randomize poles", and "Surprise me" also changes the polar features that are on.
- Two new example presets: Saturnine (hexagon in the north, one big vortex in the south)
  and JovianPoles (the Jovian planet with Jupiter's cyclone rings at both poles).
- Builds with polar features take about 1.5–2× longer, because the flow is followed in
  smaller steps near the poles. Planets without polar features come out exactly as
  before.

## 1.1.1

- More DDS formats in Export: BC7 and BC3 / DXT5 for the colour and emissive maps, BC5
  for the normal map. BC1 / DXT1 and DXT5nm stay the defaults. On the command line:
  `--color bc7`, `--normal bc5`, `--emissive bc3` and so on.

## 1.1.0

- Big storms are now big versions of the small storms: a spiral with a bright centre.
  Each big storm has its own turns, spin, centre brightness, centre size and centre
  colour, plus stretch and ragged edge. Presets from 1.0 keep their storm settings.
- Big storms stay round and centred: the band winds and curls flow around them instead
  of through them, and planets with big storms use a more accurate flow step, so the
  storms no longer get speckled or jagged edges.
- Big or stretched storms no longer turn into noise: "Ragged" now gives the storm a
  smooth, lobed outline instead of many small bumps inside it.
- Storm arms: give a big storm 1 to 6 spiral cloud arms. Arm length, width, curl,
  strength and colour can be set; the arms curl the way the storm turns.
- Glowing bands: pick one or more bands that glow. The build writes an extra emissive
  map (`_emissive.png` and `_emissive.dds`) in the band colour or a colour you pick,
  following all the swirls. Export it as DDS or PNG.
- The band list shows band numbers.
- Band thickness around the planet: a curve editor per band. 0% makes the band stop and
  the bands next to it meet; the curls along its edges and the emissive map follow.
  "Add gap", "Random" and "Reset" buttons. New example preset "Jovian".
- Removed the "Glows" latitude brightening (use the band colours instead).
- Removed the RAM estimate and the check of the PC's RAM from the window.

## 1.0.0

First public release.

- Gas giant generator: colour bands, Kelvin-Helmholtz curls along band edges, jets,
  turbulence, threads, small storms and big oval storms.
- Gas Giant Studio window with an instant band preview, builds from 512 to 16384 pixels
  wide, a preview sheet (sphere, flat map, both poles, close-up) and a RAM check for big
  builds.
- Colours from a reference picture.
- Randomize buttons on every tab, "Surprise me" and Undo.
- Export to DDS (KSP-ready), PNG, JPG, TGA and BMP. You choose the folder, names and size.
- Flow Map Maker for EVE flow maps on any gas giant texture: finds the bands, adds storm
  swirls and shows arrows or an animation.
- Command line for everything: make, export, new, flow, sample.
- Four example presets: Lavender, NeptuneBlue, NeptuneStorm, TealBands.
