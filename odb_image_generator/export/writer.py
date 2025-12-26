"""Image and index.json writer."""

import json
import os
from pathlib import Path
from typing import Dict, Any, List

from PIL import Image


class ImageWriter:
    """Handles writing component images and index file."""

    def __init__(self, out_dir: str | Path):
        self.out_dir = Path(out_dir)
        self.img_dir = self.out_dir / "images"
        self._index: List[Dict[str, Any]] = []

        # Create directories
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.img_dir.mkdir(parents=True, exist_ok=True)

    def save_image(
        self,
        img: Image.Image,
        refdes: str,
        metadata: Dict[str, Any],
    ) -> str:
        """Save a component image and record metadata.
        
        Args:
            img: Image to save
            refdes: Component reference designator (used as filename)
            metadata: Additional metadata for index.json
            
        Returns:
            Relative path to saved image
        """
        filename = f"{refdes}.png"
        filepath = self.img_dir / filename

        img.save(filepath, "PNG")

        # Build index entry
        entry = {
            "refdes": refdes,
            **metadata,
            "image_file": f"images/{filename}",
        }
        self._index.append(entry)

        return f"images/{filename}"

    def write_index(self) -> Path:
        """Write index.json with all saved image metadata.
        
        Returns:
            Path to index.json file
        """
        index_path = self.out_dir / "index.json"

        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2)

        return index_path

    @property
    def count(self) -> int:
        """Number of images saved."""
        return len(self._index)
