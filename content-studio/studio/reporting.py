from __future__ import annotations

import json

from studio.storage import Project


def costs(project: Project):
    path = project.file("logs/events.jsonl")
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    usage = [e for e in events if e["stage"] == "usage"]
    # An attempt and its result are one billable request. Keep unresolved attempts unknown.
    resolved = {e["request_id"] for e in usage if e.get("status") == "result"}
    billable = [e for e in usage if not (e.get("status") == "attempt" and e.get("request_id") in resolved)]
    known = sum(e["estimated_cost_usd"] for e in billable if e.get("estimated_cost_usd") is not None)
    unknown = [e for e in billable if e.get("estimated_cost_usd") is None]
    return {"processing_seconds": round(sum(e.get("seconds", 0) for e in events), 3), "api_calls": sum(e.get("api_calls", 0) for e in usage), "known_api_cost_usd": round(known, 6), "estimated_total_usd": None if unknown else round(known, 6), "unpriced_entries": len(unknown), "usage": billable}


def report(project: Project):
    sources = project.read("sources.json", [])
    plan = project.read("03_analysis/analysis.json", {})
    manifest = project.read("logs/render-manifest.json", {})
    data = costs(project)
    original = sum(s["duration"] for s in sources)
    lines = [f"# {project.read('project.json')['title']}", "", f"Source duration: {original:.2f}s", f"Human QC: {'approved for the current render' if project.approved('qc') else 'pending'}", ""]
    if project.read("project.json").get("private_test"):
        lines += ["Private development test. Do not publish or redistribute the source or clips.", ""]
    if "longform" in manifest:
        item = manifest["longform"]
        duration = item["qc"]["duration"]
        scope = plan.get("longform_scope", "full")
        lines += ["## Longform", "", f"Scope: {scope}", f"Original duration: {original:.2f}s", f"Final duration: {duration:.2f}s", f"{'Omitted outside representative section / removed' if scope != 'full' else 'Removed duration'}: {original-duration:.2f}s", f"Graphics generated: {', '.join(item['graphics']) or 'none'}", f"Output: {item['path']}", "", "Edits made:"]
        lines += [f"- {c['source']} {c['start']:.2f}-{c['end']:.2f}: {c['reason']}" for c in plan.get("longform", [])]
        if scope == "representative-section":
            cuts = plan.get("longform", [])
            envelope = sum(max(c["end"] for c in cuts if c["source"] == key) - min(c["start"] for c in cuts if c["source"] == key) for key in {c["source"] for c in cuts})
            kept = sum(c["end"] - c["start"] for c in cuts)
            lines += ["", f"Source span represented: {envelope:.2f}s; internal trims: {envelope-kept:.2f}s; material outside this sample: {original-envelope:.2f}s.", "The sample's omitted material is not a recommendation to remove the rest of the episode."]
    lines += ["", "## Shorts", "", f"Candidates: {len(plan.get('candidates', []))}", f"Rendered: {len([k for k in manifest if k != 'longform'])}", ""]
    for candidate in plan.get("candidates", []):
        if candidate["id"] in manifest:
            item = manifest[candidate["id"]]
            lines += [f"### {candidate['id']}", f"Hook: {candidate['hook']}", f"Source: {candidate['start_time']:.2f}-{candidate['end_time']:.2f}s", f"Duration: {item['qc']['duration']:.2f}s", f"Score: {candidate['scores']['overall']}/10, editorial judgment", f"Reason: {candidate['reason_selected']}", f"Graphics: {', '.join(item['graphics']) or 'none'}", f"Output: {item['path']}", ""]
    lines += ["## Processing and costs", "", f"Recorded processing time: {data['processing_seconds']:.1f}s. Excludes idle review time and Codex reasoning.", f"External API calls: {data['api_calls']}", f"Known API cost: ${data['known_api_cost_usd']:.4f}", f"Estimated total: {'UNKNOWN' if data['estimated_total_usd'] is None else '$'+str(data['estimated_total_usd'])}", f"Unpriced entries: {data['unpriced_entries']}", "Codex subscription cost and local electricity are not estimated. Token usage is null when unavailable.", ""]
    for entry in data["usage"]:
        cost = entry.get("estimated_cost_usd")
        lines.append(f"- {entry['category']} / {entry['provider']} / {entry['model']}: {'UNKNOWN' if cost is None else '$'+str(round(cost, 5))}")
    lines += ["", "## QC and remaining work", "", "Technical QC checks decoding, dimensions, duration, stream alignment, caption layout rules and loudness. Semantic lip sync, word-edge audibility, caption wording and graphics need a person watching and listening.", ""]
    for target, item in manifest.items():
        lines.append(f"- {target}: technical {'pass' if item['qc']['technical_pass'] else 'FAIL'}, warnings: {'; '.join(item['qc']['warnings']) or 'none'}")
    lines += ["", *[f"- {w}" for w in plan.get("warnings", [])]]
    project.text("report.md", "\n".join(lines) + "\n")
    project.write("logs/cost-summary.json", data)
    return project.file("report.md")
