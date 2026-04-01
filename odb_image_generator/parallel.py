"""Parallel processing utilities for image generation."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Iterator, List, TypeVar, Optional, Any

T = TypeVar("T")
R = TypeVar("R")

# Try to import tqdm, fallback to simple implementations if not available
try:
    from tqdm import tqdm as _tqdm

    TQDM_AVAILABLE = True

    def safe_tqdm(iterable: Iterable[T] | None = None, **kwargs) -> Any:
        """Thread-safe tqdm wrapper."""
        return _tqdm(iterable, **kwargs)

    def safe_tqdm_write(msg: str) -> None:
        """Write message without corrupting progress bar."""
        _tqdm.write(msg)

except ImportError:
    TQDM_AVAILABLE = False

    def safe_tqdm(iterable: Iterable[T] | None = None, **kwargs) -> Any:
        """Fallback when tqdm is not available - returns iterable unchanged."""
        if iterable is not None:
            return iterable
        # For manual progress bar usage (total=N), return a dummy context manager
        return _DummyProgressBar(**kwargs)

    def safe_tqdm_write(msg: str) -> None:
        """Fallback print when tqdm is not available."""
        print(msg)


class _DummyProgressBar:
    """Dummy progress bar for when tqdm is not available."""

    def __init__(self, total: int = 0, desc: str = "", disable: bool = False, **kwargs):
        self.total = total
        self.desc = desc
        self.disable = disable
        self.n = 0
        self._batch_count = 0

    def __enter__(self):
        if not self.disable and self.desc:
            print(f"{self.desc}...")
        return self

    def __exit__(self, *args):
        pass

    def update(self, n: int = 1) -> None:
        """Update progress counter."""
        self.n += n
        self._batch_count += 1
        # Print progress every 5 batches
        if not self.disable and self._batch_count % 5 == 0:
            print(f"Processed {self.n}/{self.total} items...")

    def __iter__(self):
        return self

    def __next__(self):
        raise StopIteration


def get_optimal_workers() -> int:
    """Get optimal worker count based on CPU cores.
    
    Capped at 4 to prevent excessive memory usage from concurrent
    image operations (each worker holds large image data).
    """
    return min(os.cpu_count() or 4, 4)


def batch_items(items: List[T], batch_size: int) -> Iterator[List[T]]:
    """Yield batches of items for memory-efficient processing.
    
    Args:
        items: List of items to batch
        batch_size: Maximum items per batch (must be >= 1)
        
    Yields:
        Lists of at most batch_size items
    """
    if batch_size < 1:
        batch_size = 1
    
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def parallel_map(
    func: Callable[[T], R],
    items: List[T],
    max_workers: int | None = None,
) -> List[R | None]:
    """Execute function on items in parallel using thread pool.
    
    Uses ThreadPoolExecutor with context manager for automatic cleanup.
    Maintains order of results matching input items.
    
    Args:
        func: Function to apply to each item
        items: List of items to process
        max_workers: Number of parallel workers (None = auto-detect)
        
    Returns:
        List of results in same order as input items (None for failed items)
    """
    if not items:
        return []
    
    if max_workers is None:
        max_workers = get_optimal_workers()
    
    # Single-threaded fallback for max_workers=1 or single item
    if max_workers <= 1 or len(items) == 1:
        results: List[R | None] = []
        for item in items:
            try:
                results.append(func(item))
            except Exception as e:
                safe_tqdm_write(f"Error processing item: {e}")
                results.append(None)
        return results
    
    results = [None] * len(items)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks with index to maintain order
        future_to_idx = {
            executor.submit(func, item): idx
            for idx, item in enumerate(items)
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                # Log error but don't fail entire batch
                safe_tqdm_write(f"Error processing item {idx}: {e}")
                results[idx] = None
    
    return results
