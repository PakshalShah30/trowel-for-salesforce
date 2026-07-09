"""Week 2: explain one Flow in structured JSON — your first LLM contact.

Usage:
    python -m archaeologist.summarize --flow path/to/MyFlow.flow-meta.xml

Design notes:
- Forced tool-use output, NOT "please reply in JSON" (FRAMEWORK / Week 2 why):
  schema-constrained output is deterministic and testable; prose parsing is neither.
- temperature=0: analysis wants reproducibility, not creativity.
"""

import argparse
import json
import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

FLOW_SUMMARY_TOOL = {
    "name": "record_flow_summary",
    "description": "Record the structured analysis of a Salesforce Flow.",
    "input_schema": {
        "type": "object",
        "properties": {
            "purpose": {"type": "string", "description": "One-sentence plain-English purpose"},
            "trigger": {"type": "string", "description": "What starts this Flow (record event, schedule, screen...)"},
            "objects_touched": {"type": "array", "items": {"type": "string"}},
            "fields_written": {"type": "array", "items": {"type": "string"},
                               "description": "Object.Field it writes, e.g. Lead.Status"},
            "risk_notes": {"type": "array", "items": {"type": "string"},
                           "description": "Anything smelly: hardcoded IDs, missing fault paths, recursion risk"},
        },
        "required": ["purpose", "trigger", "objects_touched", "fields_written", "risk_notes"],
    },
}


def summarize_flow(xml_path: Path) -> dict:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    xml = xml_path.read_text()
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2000,
        temperature=0,
        tools=[FLOW_SUMMARY_TOOL],
        tool_choice={"type": "tool", "name": "record_flow_summary"},
        messages=[{
            "role": "user",
            "content": (
                "Analyze this Salesforce Flow metadata XML. Be precise: only list "
                "objects/fields that literally appear in the XML.\n\n" + xml
            ),
        }],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--flow", required=True, help="Path to .flow-meta.xml")
    args = parser.parse_args()
    summary = summarize_flow(Path(args.flow))
    print(json.dumps(summary, indent=2))
