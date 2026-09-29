import json

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from runtime.orchestrator import run_chimera

# Run the pipeline just like demo.py, but without the formatting/truncation
result = run_chimera(platform="YouTube", limit=3)

# Extract only the drafts
drafts = result.get("drafts", [])

# Save to a file so we can view the full contents easily
with open("generated_drafts.json", "w") as f:
    json.dump(drafts, f, indent=4)

print("Full drafts successfully saved to generated_drafts.json!")
