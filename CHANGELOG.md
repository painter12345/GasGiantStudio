# Changelog

## 1.1.11

- In game view: now also shows the aurora (strongest on the night side) next to the glowing bands
  and heat glow. Both can be switched off on the Atmosphere tab ("In game view also shows").
- In game view: works without a Scatterer atmosphere too, as soon as the planet has an aurora or
  something that glows.

## 1.1.10

- Aurora: a new Aurora tab makes polar lights around each magnetic pole: glowing curtains
  with rays, a lower fringe, bright cores and a red and purple top part. Magnetic tilt per
  pole, oval size and wobble, a dark centre, the number, spacing and width of the curtains,
  gaps, rays, diffuse glow, brightness and six colours can be set, and a seed gives a new
  pattern.
- Aurora view: a new view next to In game shows both poles from above with all layers.
- Export: "Aurora (EVE)" writes <name>_aurora and <name>_aurora_top (DDS DXT5 or PNG, at
  the size set on the tab) and <name>_aurora.cfg, an EVE config that stacks them as thin
  layers from the lowest layer up, fading towards the top. From the command line:
  `--aurora dds|png|none`.
- Changing the aurora does not mark the build as out of date.
- The Live swirls switch and its size moved to the Build row, so the view buttons fit.

## 1.1.9

- Storm arms: the arms now lie on top of the bands like the storms do, instead of the bands
  showing through them. Arm strength now sets how solid an arm is (1 = fully covering), and
  the cloud texture inside an arm only changes its brightness, not how much band shows through.
  The arm texture and the ragged arm edges no longer follow the band swirls.
- Builds made with an older version are rebuilt instead of reused.

## 1.1.8

- Atmosphere: fixed the black layer Scatterer drew around the planet. atmo.cfg was written with
  specR, specG, specB and shininess at 0; it now uses specR/G/B 1 and shininess 10, like stock Jool. Presets and
  atmo.cfg files that still have shininess 0 (or all three spec values at 0) are repaired when
  they are loaded, and any of the other Scatterer values that are missing are filled in.
- Planet list entry: now also writes cloudIntegrationUsesScattererSunColors = False and
  autoMainSun = True, so a planet around another star is lit by that star.

## 1.1.7

- Atmosphere: a new Atmosphere tab makes a Scatterer atmosphere for the planet, with
  Scatterer's own values: atmosphereStartRadiusScale, HR and m_betaR (Rayleigh, the colour
  of the sky), HM, BETA_MSca and m_mieG (Mie, the haze), the ozone layer (useOzone,
  ozoneAbsorption, ozoneHeight, ozoneFalloff), averageGroundReflectance,
  multipleScattering, godrayStrength and the config points (altitude, skyExposure,
  scatteringExposure, skyAlpha, skyExtinctionTint, extinctionThickness, extinctionTint,
  postProcessAlpha, postProcessDepth). Other Scatterer values (rim, shine, cloud and
  scaled-texture settings) are kept and written back as they are.
- In game view: a new view next to the live preview shows the planet with its atmosphere
  the way KSP's map view shows it, using the last config point: the whole planet, a
  close-up of the day-side edge or of the sunset edge. It renders Rayleigh and Mie
  scattering with multiple scattering and the ozone layer in the same units as Scatterer,
  and puts the light on the planet and the sky the way Scatterer's scaled-space shaders
  do. Drag left or right (or use the Sun angle slider) to move the sun. It uses the
  current build when it is up to date, otherwise the live swirls.
- Sky colour... and Haze colour... set the scattering values from a colour, Match the
  planet takes the sky colour from the bands, and Start from fills in stock Jool, stock
  Kerbin or Earth-like values.
- Load from Scatterer config... reads an existing atmo.cfg (and the planet's sun, sun
  colour and eclipse casters from the planet list next to it). Read from Kopernicus config
  finds the planet's radius in your mod. When you switch the atmosphere on and your mod
  already has a Scatterer config for the planet, it offers to start from it.
- The tab shows the atmo.cfg and the planet list entry to copy. Save atmo.cfg... backs up
  the old file first and offers to write the planet list entry when the planet is not in
  Scatterer's list yet. Export has a new "Scatterer config" row; command line:
  `export --atmo cfg|none`.
- The preview sheet shows the planet with its atmosphere when it has one.
- NeptuneStorm now has an atmosphere.
- The swirl info moved to the tool row so the Export button always fits.
- Planets without an atmosphere come out exactly as before.

## 1.1.6

- Rings: a new Rings tab makes a ring texture for Kopernicus. Inner and outer edge, tilt,
  wide zones, fine ringlets, ringlet detail, opacity, soft edges, colour variation, a list
  of gaps (with "Random gaps"), inner/middle/outer colours (auto from the bands), texture
  width, "New pattern" and "Randomize rings". The tab shows the planet with its rings,
  including the planet's shadow on the rings and the rings' shadow on the planet, and the
  Kopernicus config to copy. Build writes the ring texture; Export saves it as DDS
  (BC3/DXT5 or BC7) or PNG; there is a file name for it on the Planet tab. Command line:
  `export --ring dds|bc7|png|none`.
- Storm chains: rows of storms along a latitude, like Jupiter's "string of pearls". Each
  chain has latitude (and end latitude), longitude, length (360 = all the way round),
  count, size, stretch, turns, spin, ragged, centre and jitter.
- Edit on the map: a tool row above the preview with Turn globe, Place storms, Storm
  chain and Move bands. Draw a chain by dragging along a latitude, or click for a ring all
  the way round; drag a chain to move it, right-click to remove it. Move bands: drag a
  band edge up or down, and the curl row on that edge comes along; double-click splits a
  band, right-click an edge removes it. Undo works for all of it.
- Saturnine now has rings.
- Fixed: lists that became empty (for example the big storms after loading a planet
  without any) left a big blank space in the tab.
- Planets without rings or storm chains come out exactly as before.

## 1.1.5

- New colour picker for every colour box (bands, glow, storms, poles, threads): a colour
  square and hue bar, hex and R/G/B fields, a before/now comparison, the planet's band
  colours and your recent colours as one-click swatches.
- Eyedropper: "Pick from screen" lets you click a colour anywhere on your screen, for
  example in a Jupiter photo open in your browser, with a magnifier and the hex value
  under the cursor. "Pick from picture..." does the same with an image file. It takes the
  average of 3 x 3 pixels so noisy photos give a clean colour.
- The planet and the live preview update while you pick; Cancel puts the old colour back,
  and Undo goes back after OK.
- Place big storms by clicking: turn on "Place storms" above the preview (or "Place on the
  map" under the big storms) and click the flat map or the globe to add a big storm there.
  Drag a storm to move it, right-click it to remove it; dashed outlines show where the
  storms are. Undo works for all of it.

## 1.1.4

- Live preview: the preview now shows the real swirls by itself a moment after each
  change, with storms, poles and glow. A quick rough version comes first, then a sharper
  one at 512 or 1024 pixels wide (pick next to the "Swirls" tickbox). Colour changes
  reuse the flow and show in about half a second. Untick "Swirls" for the old bands-only
  view. It waits while a build runs.
- Drag the globe in the live preview to turn it; double-click resets. This only turns the
  view, the preview camera in the Planet tab stays as it is.
- The flow field is computed about twice as fast, so every build starts sooner. The maps
  come out exactly the same as before.

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
