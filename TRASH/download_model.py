#!/usr/bin/env python3
"""Download GLiNER2 model weights."""
from huggingface_hub import snapshot_download

print("Downloading GLiNER2 model...")
snapshot_download(
    repo_id="fastino/gliner2-base-v1",
    local_files_only=False,
    resume_download=True,
)
print("Done!")
