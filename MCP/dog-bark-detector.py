#!/usr/bin/env python3
"""
Dog bark detection MCP server using YAMNet.

Exposes a tool that scans a directory of 1-minute audio files
and reports timestamps where barking is detected.

This wraps the user's YAMNet barking example into an MCP tool.
"""

from __future__ import annotations

from typing import Any, Dict, List
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("dog-bark-detector")


def _import_deps():
    """Import heavy dependencies lazily so the server can start even if missing."""
    try:
        import tensorflow as tf  # type: ignore
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:  # pragma: no cover - import failure path
        raise RuntimeError(
            "Failed to import required dependencies. "
            "Ensure `tensorflow`, `librosa`, and `numpy` are installed."
        ) from exc
    return tf, librosa, np


_yamnet_model = None


def _get_yamnet_model():
    """Load YAMNet model from TF Hub once and cache it."""
    global _yamnet_model
    if _yamnet_model is None:
        tf, _, _ = _import_deps()
        # Uses the same pattern as the user's example; this will download
        # the model the first time it is called.
        _yamnet_model = tf.saved_model.load("https://tfhub.dev/google/yamnet/1")
    return _yamnet_model


def _detect_barking_in_file(
    audio_path: str,
    threshold: float = 0.5,
    bark_class_index: int = 2,
) -> List[float]:
    """Detect barking timestamps in a single audio file using YAMNet."""
    tf, librosa, np = _import_deps()

    # Load audio at 16 kHz mono as expected by YAMNet
    waveform, sr = librosa.load(audio_path, sr=16000, mono=True)

    # YAMNet expects float32 tensor audio
    waveform_tf = tf.cast(waveform, tf.float32)

    model = _get_yamnet_model()

    # YAMNet returns (scores, embeddings, spectrogram)
    scores, embeddings, spectrogram = model(waveform_tf)
    scores_np = scores.numpy()

    # Barking class index (user specified this as 2)
    if bark_class_index < 0 or bark_class_index >= scores_np.shape[1]:
        raise ValueError(
            f"bark_class_index {bark_class_index} out of range "
            f"for scores with shape {scores_np.shape}"
        )

    bark_scores = scores_np[:, bark_class_index]

    # Frames where barking probability exceeds threshold
    bark_frames = np.where(bark_scores > threshold)[0]

    if bark_frames.size == 0:
        return []

    # Convert frame indices to timestamps in seconds.
    # This mirrors the user's example:
    #   timestamp = frame * (len(waveform) / len(bark_scores)) / sr
    num_samples = len(waveform)
    num_frames = len(bark_scores)
    timestamps: List[float] = []
    for frame in bark_frames:
        timestamp = frame * (num_samples / num_frames) / sr
        timestamps.append(float(timestamp))

    return timestamps


@mcp.tool()
async def detect_barking_in_directory(
    directory: str,
    threshold: float = 0.5,
    bark_class_index: int = 2,
    file_extension: str = ".wav",
) -> Dict[str, Any]:
    """Scan a directory of audio files for dog barking using YAMNet.

    Assumes files are ~1-minute clips, but works for any duration.

    Args:
        directory: Path to directory containing audio files.
        threshold: Barking probability threshold (0-1, default 0.5).
        bark_class_index: Index of the "Bark" class in YAMNet scores (default 2).
        file_extension: Audio file extension to scan (default ".wav").

    Returns:
        Dictionary with detection results per file, e.g.:
        {
            "success": True,
            "directory": "...",
            "file_count": 10,
            "scanned_files": 8,
            "detections": [
                {
                    "file": "clip001.wav",
                    "path": "/full/path/clip001.wav",
                    "has_bark": True,
                    "bark_timestamps": [1.23, 5.67]
                },
                ...
            ],
            "errors": [
                {"file": "bad.wav", "error": "reason"},
                ...
            ]
        }
    """
    try:
        if not os.path.isdir(directory):
            return {
                "success": False,
                "error": f"Directory not found or not a directory: {directory}",
            }

        # Normalize extension to start with dot
        if file_extension and not file_extension.startswith("."):
            file_extension = "." + file_extension

        all_entries = sorted(os.listdir(directory))
        files = [
            f for f in all_entries if f.lower().endswith(file_extension.lower())
        ]

        detections: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []

        for filename in files:
            full_path = os.path.join(directory, filename)
            try:
                timestamps = _detect_barking_in_file(
                    full_path,
                    threshold=threshold,
                    bark_class_index=bark_class_index,
                )
                detections.append(
                    {
                        "file": filename,
                        "path": os.path.abspath(full_path),
                        "has_bark": bool(timestamps),
                        "bark_timestamps": timestamps,
                    }
                )
            except Exception as exc:  # pragma: no cover - runtime error path
                errors.append(
                    {
                        "file": filename,
                        "error": str(exc),
                    }
                )

        return {
            "success": True,
            "directory": os.path.abspath(directory),
            "file_count": len(all_entries),
            "scanned_files": len(files),
            "detections": detections,
            "errors": errors,
        }
    except Exception as exc:  # pragma: no cover - top-level fallback
        return {
            "success": False,
            "error": str(exc),
        }


if __name__ == "__main__":
    mcp.run()

