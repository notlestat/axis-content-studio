# Graphic slots

Each reviewed visual opportunity has a slot under:
03_analysis/animations/slot-<visual-id>/

The slot's source, render.mp4, asset.json and commands.log stay with the project.
The source timing is remapped through the keep ranges to the output timeline.
A graphic may not straddle a cut. Captions are composited after it.

Use client.yaml graphics.engine to choose hyperframes, remotion, pil or auto.
Use frequency off, sparse or moderate. Sparse selects at most one opportunity per
short and roughly one per three minutes of longform. Engine and brand preferences
are part of the asset cache key. Custom creative style instructions guide Codex's
slot design; the stock card is only a starting template.

Set brand.logo to a client-relative file such as `brand/logos/logo.png`. The stock
HyperFrames and PIL cards display it in the upper left. Missing or invalid logos
fail visibly; logo bytes are included in the graphic cache key. Custom attached
compositions must incorporate the logo themselves. Install the named brand font
locally; the HyperFrames template declares it with `src: local(...)`.

## HyperFrames

Install once:

    cd tools/graphics
    npm ci

Use the project approvals, then:

    studio graphics build rui-fu ai-business-podcast g01

The adapter scaffolds locally, writes a branded deterministic composition, runs
HyperFrames check and renders the MP4. It fails visibly if the browser, font,
component, runtime, layout or render is unavailable. Read commands.log and inspect
the HTML and a render frame. Do not call a failed check a successful graphic.

To author a custom chart, UI animation or diagram, let Codex read the installed
HyperFrames skills and the slot's brief, work in a separate composition directory,
run HyperFrames check and render there, then attach that reviewed output:

    studio graphics attach rui-fu ai-business-podcast g01 --file /absolute/render.mp4

The stock card handles typography and lists. It does not invent charts or website
screenshots. Codex should build a custom composition for those opportunities.

## Remotion

When a client already has React-based graphics, use an isolated Remotion project
inside the slot. Render an MP4 with exactly the opportunity duration and target
resolution, then use graphics attach as above. Attachment validates dimensions and
duration and records a hash. No global Remotion dependency is needed by studio.
Read the installed remotion-best-practices and remotion-render skills when authoring.

## PIL

PIL provides a local static card with a short fade for simple explanatory inserts.
This is a supported video-use slot engine. Use HyperFrames for designed motion.
There is no silent switch to PIL if HyperFrames fails.
