# ODB++ Component Image Generator

Generates per-component PCB images from ODB++ archives with layer stacking:
**Board → Copper → Soldermask (with openings) → Silkscreen → Annotations**

## Installation

```bash
# Create virtual environment
python -m venv .venv

# Activate (Windows)
.\.venv\Scripts\activate

# Install dependencies
pip install Pillow
```

## Usage

```bash
python cli.py --odb-tgz <archive.tgz> --out-dir <output_folder>
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--odb-tgz` | *(required)* | Path to ODB++ `.tgz` archive |
| `--out-dir` | *(required)* | Output directory for images |
| `--img-size` | 1024 | Output image size in pixels |
| `--render-size` | 8192 | Internal render size (higher = better quality) |
| `--window-mm` | 40.0 | Crop window size around each component (mm) |
| `--limit` | 0 | Limit number of components (0 = all) |
| `--component` | *(none)* | Filter to single component by refdes (e.g., `C45`) |
| `--pad` | *(none)* | Center crosshair on specific pad name (e.g., `1`) |
| `--target` | *(none)* | Repeatable per-item export: `REFDES` or `REFDES:PAD` (e.g., `--target C45:1 --target R45`). Cannot be combined with `--component/--pad`. |
| `--cross-arm-mm` | 1.5 | Crosshair arm half-length in mm |
| `--cross-thickness-px` | 3 | Crosshair line thickness in pixels |

### Examples

```bash
# Generate all components
python cli.py --odb-tgz CE_FLAME-DETECTOR.tgz --out-dir out_all

# Generate single component centered on component origin
python cli.py --odb-tgz CE_FLAME-DETECTOR.tgz --out-dir out --component C45

# Generate single component with crosshair on pad 1
python cli.py --odb-tgz CE_FLAME-DETECTOR.tgz --out-dir out --component C45 --pad 1

# Generate all components with crosshair on pad 1 (falls back to center if pad not found)
python cli.py --odb-tgz CE_FLAME-DETECTOR.tgz --out-dir out --pad 1

# Generate a specific list of components (optionally centered on a pad)
python cli.py --odb-tgz CE_FLAME-DETECTOR.tgz --out-dir out --target C45:1 --target R45 --target U7:3

# Change crosshair size
python cli.py --odb-tgz CE_FLAME-DETECTOR.tgz --out-dir out --component C45 --pad 1 --cross-arm-mm 2.5 --cross-thickness-px 5
```

## Output

- `<out-dir>/images/` — PNG images named `<refdes>.png` or `<refdes>_pad<N>.png`
- `<out-dir>/index.json` — Metadata index with component info

## Project Structure

```
odb_image_generator/
├── cli.py                      # CLI entry point
├── odb_image_generator/        # Main package
│   ├── models.py               # Data classes
│   ├── parsing/                # ODB++ parsing
│   │   ├── archive.py          # Archive extraction
│   │   ├── profile.py          # Board outline parsing
│   │   ├── components.py       # Component placement parsing
│   │   ├── symbols.py          # Symbol definitions (pads)
│   │   └── features.py         # Feature primitives (P/L/A/POLY/TEXT)
│   ├── rendering/              # Image rendering
│   │   ├── context.py          # Render context & transforms
│   │   ├── primitives.py       # Drawing primitives
│   │   └── layers/             # Layer renderers
│   │       ├── board.py        # Board outline
│   │       ├── copper.py       # Copper pads
│   │       ├── soldermask.py   # Soldermask with openings
│   │       └── silkscreen.py   # Silkscreen/legend
│   └── export/                 # Export utilities
│       ├── cropper.py          # Component cropping
│       ├── annotations.py      # Crosshairs & labels
│       └── writer.py           # Image & index output
└── legacy/                     # Backup of monolithic script
```

## Legacy Version

The original monolithic script is preserved in `legacy/`:

```bash
python legacy/odb_component_renders_board_copper_mask_silk.py --odb-tgz <archive.tgz> --out-dir <output>
```
