"""Image and index.json writer."""

import json
import os
import threading
from pathlib import Path
from threading import Lock
from typing import Dict, Any, List

from PIL import Image


class ImageWriter:
    """Handles writing component images and index file."""

    def __init__(self, out_dir: str | Path):
        self.out_dir = Path(out_dir)
        self.img_dir = self.out_dir / "images"
        self._index: List[Dict[str, Any]] = []
        self._lock = Lock()  # Thread-safe access to _index

        # Create directories
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.img_dir.mkdir(parents=True, exist_ok=True)

    def save_image(
        self,
        img: Image.Image,
        refdes: str,
        metadata: Dict[str, Any],
        compress_level: int = 6,
    ) -> str:
        """Save a component image and record metadata.

        Args:
            img: Image to save
            refdes: Component reference designator (used as filename)
            metadata: Additional metadata for index.json
            compress_level: PNG zlib level (pixels identical at any level;
                1 encodes ~3x faster for ~2% larger files)

        Returns:
            Relative path to saved image
        """
        filename = f"{refdes}.png"
        filepath = self.img_dir / filename

        # Atomic write (tmp + rename): save_image runs in parallel export
        # workers, and two tasks can map to the same filename (duplicate
        # refdes) — interleaved direct writes would tear the PNG. The rename
        # makes any concurrent same-name save an atomic last-wins, and a
        # reader can never observe a half-written file.
        tmp = filepath.with_name(f".{filename}.{threading.get_ident()}.tmp")
        img.save(tmp, "PNG", compress_level=compress_level)
        os.replace(tmp, filepath)

        # Build index entry (thread-safe)
        entry = {
            "refdes": refdes,
            **metadata,
            "image_file": f"images/{filename}",
        }
        with self._lock:
            self._index.append(entry)

        return f"images/{filename}"

    def write_index(self) -> Path:
        """Write index.json with all saved image metadata.
        
        Returns:
            Path to index.json file
        """
        index_path = self.out_dir / "index.json"

        with self._lock:
            data = list(self._index)  # Copy for thread safety

        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return index_path

    @property
    def count(self) -> int:
        """Number of images saved (thread-safe)."""
        with self._lock:
            return len(self._index)
