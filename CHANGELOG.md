# Changelog

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
- Removed the "Glows" latitude brightening (use the band colours instead).

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
