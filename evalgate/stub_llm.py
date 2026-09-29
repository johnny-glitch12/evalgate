"""Deterministic stub for ``lib.llm_client.call_llm`` — offline eval builds.

Every stage response is a pure function of ``(case_id, stage)``: same case,
same stage → byte-identical text, so eval runs are reproducible and a score
change can only come from a harness/pipeline change, never from stub noise.

The payloads match the EXACT formats the pipeline parses (read from
``prompts/code_gen_prompts.py`` + ``lib/code_gen_pipeline.py``):
    architect / planner / plan_verify / builder / reviewer / polisher /
    ui_builder / spec_verify / design_critic — all strict-JSON objects.
Texts are wrapped in a ```json fence on purpose: the pipeline's
``_extract_json`` strips fences, so stub mode exercises that real path.

The generated FILES are honest minimal implementations (real parsing, real
guards, real error shapes) — not decorative shells — so the pipeline's own
static validators (``validate_all_files``) pass on them. They are still test
fixtures: each main.py says so in its docstring.
"""
from __future__ import annotations

import json

from evalgate.cases import CASES  # noqa: F401  (imported for callers' convenience)

# ── stage detection (keyed on system-prompt content, like the real prompts) ──
_STAGE_MARKERS = [
    ("plan_verify", "PLAN VERIFIER stage"),
    ("spec_verify", "SPEC VERIFIER stage"),
    ("design_critic", "DESIGN CRITIC stage"),
    ("ui_builder", "UI BUILDER stage"),
    ("architect", "ARCHITECT stage"),
    ("planner", "PLANNER stage"),
    ("builder", "BUILDER stage"),
    ("reviewer", "REVIEWER stage"),
    ("polisher", "POLISHER stage"),
    ("editor", "EDITOR stage"),
]


def stage_from_system_prompt(system_prompt: str) -> str:
    """Map a pipeline system prompt to its stage name. Raises on unknown input
    rather than guessing — a silent wrong-stage answer would corrupt an eval."""
    sp = system_prompt or ""
    for stage, marker in _STAGE_MARKERS:
        if marker in sp:
            return stage
    raise ValueError("stub_llm: could not identify pipeline stage from system prompt")


# ── per-case compute bodies (real minimal logic; each must define `result`) ──
# Lines carry their own relative indentation; the generator adds the base
# indent for the `try:` body inside run().
_COMPUTE = {
    "slack_standup_bot": {"lines": [
        'text = "Standup summary: " + str(summary_text or "").strip()',
        'result = {"channel": str(channel or "").strip(), "text": text}',
    ]},
    "web_scraper_prices": {"imports": ["re"], "uses_httpx": True, "lines": [
        'resp = httpx.get(str(url or ""), timeout=20, follow_redirects=True)',
        'resp.raise_for_status()',
        'prices = re.findall(r"[$\\u20ac\\u00a3]\\s?\\d+(?:[.,]\\d{2})?", resp.text)',
        'result = {"url": url, "prices_found": len(prices), "prices": prices[:20]}',
    ]},
    "stripe_checkout_link": {"lines": [
        'result = {"product_name": str(product_name or "").strip(),',
        '          "amount_cents": int(amount or 0),',
        '          "currency": str(currency or "usd").lower(), "mode": "payment"}',
    ]},
    "metrics_dashboard": {"lines": [
        'data = json.loads(str(stats_json or "[]")) if isinstance(stats_json, str) else (stats_json or [])',
        'vals = [float(d.get("value") or 0) for d in data if isinstance(d, dict)]',
        'result = {"count": len(vals), "total": round(sum(vals), 2),',
        '          "average": round(sum(vals) / len(vals), 2) if vals else None}',
    ]},
    "email_digest_cron": {"lines": [
        'entries = [str(x) for x in (items or [])][:50]',
        'body = "\\n".join("- " + e for e in entries)',
        'result = {"subject": "Daily digest: " + str(len(entries)) + " item(s)", "body": body}',
    ]},
    "telegram_alert_bot": {"lines": [
        'result = {"chat_id": str(chat_id or "").strip(),',
        '          "text": "ALERT: " + str(alert_text or "").strip()}',
    ]},
    "csv_sales_report": {"imports": ["csv", "io"], "lines": [
        'rows = list(csv.DictReader(io.StringIO(str(csv_text or ""))))',
        'total = 0.0',
        'for row in rows:',
        '    try:',
        '        total += float(row.get("amount") or 0)',
        '    except (TypeError, ValueError):',
        '        continue',
        'result = {"rows": len(rows), "total": round(total, 2)}',
    ]},
    "webhook_relay": {"lines": [
        'body = json.loads(str(payload_json or "{}")) if isinstance(payload_json, str) else (payload_json or {})',
        'result = {"forwarded_keys": sorted(body) if isinstance(body, dict) else [], "payload": body}',
    ]},
    "docs_qa_agent": {"imports": ["re"], "lines": [
        'docs = [str(d) for d in (documents or [])]',
        'q_terms = {w for w in re.findall(r"[a-z0-9]+", str(question or "").lower()) if len(w) > 2}',
        'scored = []',
        'for i, d in enumerate(docs):',
        '    overlap = len(q_terms & set(re.findall(r"[a-z0-9]+", d.lower())))',
        '    if overlap:',
        '        scored.append((overlap, -i, d))',
        'scored.sort(reverse=True)',
        'sources = [d for _, _, d in scored[:3]]',
        'answer = sources[0][:280] if sources else "No relevant passage found in the provided documents."',
        'result = {"question": question, "answer": answer, "sources": sources}',
    ]},
    "cron_task_scheduler": {"from_imports": ["from datetime import datetime, timezone"], "lines": [
        'now = str(now_iso or "").strip() or datetime.now(timezone.utc).isoformat()',
        'due, upcoming = [], []',
        'for t in (tasks or []):',
        '    if isinstance(t, dict):',
        '        (due if str(t.get("due_at") or "") <= now else upcoming).append(t.get("name"))',
        'result = {"checked_at": now, "due": due, "upcoming": upcoming}',
    ]},
    "feedback_form_app": {"lines": [
        'text = str(feedback_text or "").lower()',
        'if any(w in text for w in ("bug", "broken", "crash", "error")):',
        '    category = "bug report"',
        'elif any(w in text for w in ("slow", "confusing", "hard")):',
        '    category = "usability"',
        'elif any(w in text for w in ("love", "great", "thanks")):',
        '    category = "praise"',
        'else:',
        '    category = "general"',
        'result = {"category": category, "length": len(text)}',
    ]},
    "crm_api_integrator": {"lines": [
        'parts = str(full_name or "").strip().split(" ")',
        'result = {"properties": {"firstname": parts[0] if parts else "",',
        '                         "lastname": " ".join(parts[1:]),',
        '                         "email": str(email or "").strip().lower(),',
        '                         "company": str(company or "").strip()}}',
    ]},
    "data_cleaner": {"lines": [
        'rows = json.loads(str(records_json or "[]")) if isinstance(records_json, str) else (records_json or [])',
        'seen, cleaned = set(), []',
        'for r in rows:',
        '    if not isinstance(r, dict):',
        '        continue',
        '    rec = {k: (v.strip() if isinstance(v, str) else v) for k, v in r.items()}',
        '    mail = str(rec.get("email") or "").strip().lower()',
        '    if mail and mail in seen:',
        '        continue',
        '    if mail:',
        '        seen.add(mail)',
        '    cleaned.append(rec)',
        'result = {"input_rows": len(rows), "clean_rows": len(cleaned), "records": cleaned[:50]}',
    ]},
    "deploy_notifier": {"lines": [
        'result = {"text": "Deploy " + str(status or "finished") + ": " + str(service or "unknown")}',
    ]},
}


def _uses_httpx(case: dict) -> bool:
    spec = _COMPUTE.get(case["id"], {})
    return bool(case["stub"].get("action")) or bool(spec.get("uses_httpx"))


# ── generated file contents ──────────────────────────────────────────────────
def _main_py(case: dict) -> str:
    st = case["stub"]
    spec = _COMPUTE.get(case["id"], {})
    names = [i["name"] for i in st["inputs"]]

    lines = [
        '"""%s - %s' % (st["name"], st["purpose"]),
        "",
        "Deterministic eval fixture (stub builder output) - never shipped to users.",
        '"""',
        "import json",
        "import os",
    ]
    for mod in spec.get("imports", []):
        lines.append(f"import {mod}")
    for imp in spec.get("from_imports", []):
        lines.append(imp)
    if _uses_httpx(case):
        lines += ["", "import httpx"]
    lines += ["", "from handlers import build_payload, summarize", "", ""]

    lines += [
        "def run(input, env=None, keys=None):",
        f'    """{st["purpose"]} Returns a dict; failures return an error dict."""',
        "    input = input or {}",
        "    env = env or {}",
        "    keys = keys or {}",
    ]
    # One explicit read per declared input — this is the input contract the
    # pipeline's check_input_contract validates (literal input.get("name")).
    for n in names:
        lines.append(f'    {n} = input.get("{n}")')
    payload_kv = ", ".join(f'"{n}": {n}' for n in names)
    lines.append(f"    payload = build_payload({{{payload_kv}}})")
    lines.append("    try:")
    for ln in spec.get("lines", ['result = {"summary": summarize(payload)}']):
        lines.append(("        " + ln) if ln else "")
    lines += [
        "    except Exception as exc:",
        '        return {"error": "processing failed: " + str(exc)}',
    ]

    if st.get("action"):
        ev = st["env_var"]
        integ = st.get("integration") or "target"
        lines += [
            f'    secret = str((keys or {{}}).get("{ev}") or os.environ.get("{ev}") or "").strip()',
            "    if not secret:",
            f'        return {{"needs_config": ["{ev}"],',
            f'                "error": "{ev} is not configured. Connect it in the agent settings.",',
            '                "preview": result}',
            "    # Safety gate: default to a dry run so this agent never fires a live",
            "    # action without an explicit confirm (dry_run=False).",
            '    if bool(input.get("dry_run", True)):',
            '        return {"ok": True, "dry_run": True, "preview": result}',
            "    try:",
        ]
        if st.get("endpoint_expr"):
            lines += [
                f'        url = {st["endpoint_expr"]}',
                "        resp = httpx.post(url, json=result, timeout=20)",
            ]
        else:
            lines += [
                f'        resp = httpx.post("{st["endpoint"]}", json=result,',
                '                          headers={"Authorization": "Bearer " + secret}, timeout=20)',
            ]
        lines += [
            "        resp.raise_for_status()",
            "    except Exception as exc:",
            f'        return {{"error": "{integ} request failed: " + str(exc)}}',
            '    return {"ok": True, "delivered": True, "result": result}',
        ]
    else:
        lines.append('    return {"ok": True, "result": result, "summary": summarize(payload)}')
    return "\n".join(lines) + "\n"


def _handlers_py(case: dict) -> str:
    return (
        f'"""Helpers for {case["stub"]["name"]}."""\n\n\n'
        "def build_payload(raw):\n"
        '    """Drop None values so the payload only carries fields the user provided."""\n'
        "    return {k: v for k, v in (raw or {}).items() if v is not None}\n\n\n"
        "def summarize(payload):\n"
        '    """One-line human summary of the fields this run processed."""\n'
        '    keys = ", ".join(sorted(payload)) or "no fields"\n'
        '    return "processed " + str(len(payload)) + " field(s): " + keys\n'
    )


def _requirements_txt(case: dict) -> str:
    if _uses_httpx(case):
        return "httpx==0.27.0\n"
    return "# stdlib only - no third-party dependencies\n"


def _env_example(case: dict) -> str:
    st = case["stub"]
    if st.get("env_var"):
        return (f'# {st["name"]} configuration\n'
                f'# {st["env_var"]} - {st.get("integration") or "service"} credential (required)\n'
                f'{st["env_var"]}=\n')
    return "# no credentials required - stdlib-only agent\n"


def _readme_md(case: dict) -> str:
    st = case["stub"]
    first = st["inputs"][0]["name"]
    if st.get("env_var"):
        config = (f'| Variable | Purpose |\n|---|---|\n'
                  f'| `{st["env_var"]}` | {st.get("integration") or "service"} credential |\n')
    else:
        config = "No environment variables required.\n"
    return f"""# {st["name"]}

{st["purpose"]}

## Quick Start

```
pip install -r requirements.txt
python -c "from main import run; print(run({{'{first}': '...'}}))"
```

## How It Works

- `main.py` exposes `run(input, env=None, keys=None) -> dict`, the Task Force entry point.
- `handlers.py` holds the payload/normalisation helpers.
- The node graph is trigger -> process -> {"deliver" if st.get("action") else "return"}.

## Configuration

{config}
## API

```
from main import run
result = run({{"{first}": "..."}}, env=None, keys=None)
```

`input` is always a dict - never keyword arguments.

## Limitations

- Deterministic eval fixture: minimal happy-path implementation for the offline eval harness.
- Failures return `{{"error": "..."}}` dicts; a missing credential returns `needs_config`, not a crash.
"""


def _app_jsx(case: dict) -> str:
    st = case["stub"]
    first = st["inputs"][0]["name"]
    label = first.replace("_", " ").capitalize()
    return f"""const {{ useState }} = React;
const App = () => {{
  const [value, setValue] = useState("");
  const [phase, setPhase] = useState("empty");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const runAgent = async () => {{
    setPhase("loading");
    setError("");
    try {{
      const out = await window.tfApi.run({{ {first}: value }});
      setResult(out);
      setPhase("result");
    }} catch (e) {{
      setError(String((e && e.message) || e));
      setPhase("error");
    }}
  }};
  return (
    <div className="min-h-screen bg-slate-950 p-4 sm:p-8 text-white flex items-center justify-center">
      <div className="w-full max-w-xl rounded-2xl border border-slate-800 bg-slate-900/70 p-6 shadow-2xl shadow-black/40">
        <div className="h-1 bg-gradient-to-r from-cyan-400 via-cyan-300 to-teal-400 rounded mb-4" />
        <h1 className="text-xl font-semibold tracking-tight">{st["name"]}</h1>
        <p className="text-[13px] text-slate-400">{st["purpose"]}</p>
        <label className="block mt-4 text-[12px] font-medium text-slate-300">{label}
          <input className="mt-1 w-full rounded-xl bg-slate-950/60 border border-slate-800 px-3 py-2 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/25"
                 value={{value}} onChange={{(e) => setValue(e.target.value)}} />
        </label>
        <button className="mt-4 rounded-xl bg-gradient-to-r from-cyan-400 to-teal-400 px-4 py-2 font-semibold text-slate-950 transition duration-200 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={{phase === "loading" || !value}} onClick={{runAgent}}>
          {{phase === "loading" ? "Running..." : "Run"}}
        </button>
        {{phase === "empty" && <p className="mt-4 text-center text-slate-600">Enter a value and run.</p>}}
        {{phase === "error" && <p role="alert" className="mt-4 rounded border border-rose-800/60 bg-rose-950/40 p-3 text-rose-300">{{error}}</p>}}
        {{phase === "result" && (
          <dl role="status" className="mt-4 space-y-1">
            {{Object.entries(result || {{}}).map(([k, v]) => (
              <div key={{k}} className="flex gap-2 text-[13px]">
                <dt className="text-slate-500">{{k}}</dt>
                <dd className="text-slate-300 tabular-nums">{{String(v)}}</dd>
              </div>
            ))}}
          </dl>
        )}}
      </div>
    </div>
  );
}};
window.__TF_APP = App;"""


# ── per-stage payloads (dicts; shapes mirror prompts/code_gen_prompts.py) ────
def _architect(case: dict) -> dict:
    st = case["stub"]
    has_ui = case["has_ui"]
    first = st["inputs"][0]["name"]
    criteria = [f"User provides {first} and sees a structured result"]
    if st.get("env_var"):
        criteria.append(f"With {st['env_var']} unset the run reports needs_config instead of crashing")
    criteria.append("Failures return a readable error dict, never a stack trace")
    # A stub block may pin a non-default stack (the live lane's service-shaped
    # case declares fastapi_service so a --dry-run artifact ROUTES honestly);
    # everything else keeps the historical python_agent declaration.
    stack = st.get("stack") or "python_agent"
    return {
        "name": st["name"],
        "description": st["purpose"],
        "purpose": st["purpose"],
        "stack": stack,
        "inputs": st["inputs"],
        "outputs": [{"name": "result", "type": "object",
                     "description": "The structured result of the run"}],
        "integrations": [st["integration"]] if st.get("integration") else [],
        "complexity": case["complexity"],
        "has_ui": has_ui,
        "headless_reason": st.get("headless_reason"),
        "ui_kind": st.get("ui_kind") or ("form" if has_ui else "none"),
        "ui_kind_label": (st.get("ui_kind") or "form").replace("_", " ").capitalize() if has_ui else "None",
        "ui_kind_reason": ("Best-fit front-end for this agent's input/output shape"
                           if has_ui else "Unattended background job"),
        "estimated_nodes": {"simple": 4, "medium": 7, "complex": 13}[case["complexity"]],
        "acceptance_criteria": criteria,
        "key_decisions": [f"stack locked to {stack} - a platform-executable python stack (eval stub surface)"],
    }


def _planner(case: dict) -> dict:
    st = case["stub"]
    first = st["inputs"][0]["name"]
    action_label = f"Deliver via {st['integration']}" if st.get("action") else "Return result"
    files = [
        {"path": "main.py", "purpose": f"Entry point - run(input) reads {first} and returns the result dict"},
        {"path": "handlers.py", "purpose": "Payload normalisation + summary helpers"},
        {"path": "requirements.txt", "purpose": "Pinned dependencies"},
        {"path": ".env.example", "purpose": "Required environment variables"},
        {"path": "README.md", "purpose": "Setup & usage docs"},
    ]
    env_vars = ([{"name": st["env_var"],
                  "description": f"{st.get('integration') or 'service'} credential", "required": True}]
                if st.get("env_var") else [])
    return {
        "files": files,
        "nodes": [
            {"id": "n1", "type": "trigger", "label": "Receive input", "position": {"x": 100, "y": 100}},
            {"id": "n2", "type": "transform", "label": f"Process {first}", "position": {"x": 400, "y": 100}},
            {"id": "n3", "type": "action", "label": action_label, "position": {"x": 700, "y": 100}},
        ],
        "edges": [
            {"id": "e1-2", "source": "n1", "target": "n2"},
            {"id": "e2-3", "source": "n2", "target": "n3"},
        ],
        "dependencies": ["httpx==0.27.0"] if _uses_httpx(case) else [],
        "env_vars": env_vars,
    }


def _builder(case: dict) -> dict:
    return {"files": [
        {"path": "main.py", "content": _main_py(case), "language": "python"},
        {"path": "handlers.py", "content": _handlers_py(case), "language": "python"},
        {"path": "requirements.txt", "content": _requirements_txt(case), "language": "text"},
        {"path": ".env.example", "content": _env_example(case), "language": "text"},
    ]}


def _ui_builder(case: dict) -> dict:
    st = case["stub"]
    return {
        "app_jsx": _app_jsx(case),
        "manifest": {"title": st["name"], "primary_color": "#22d3ee",
                     "layout": st.get("ui_kind") or "form", "embed_safe": True},
    }


def stub_stage_output(case: dict, stage: str) -> dict:
    """The parsed (dict) stub payload for one pipeline stage of one case."""
    st = case["stub"]
    if stage == "architect":
        return _architect(case)
    if stage == "planner":
        return _planner(case)
    if stage in ("builder", "builder_with_tools"):
        return _builder(case)
    if stage == "reviewer" or stage.startswith("reviewer_round") or stage.startswith("smoke_repair"):
        return {"fixes_applied": [], "diffs": []}
    if stage == "polisher":
        return {"files": [{"path": "README.md", "content": _readme_md(case), "language": "markdown"}]}
    if stage == "ui_builder":
        return _ui_builder(case)
    if stage == "plan_verify":
        return {"verified": True, "confidence": "high",
                "summary": f"The plan covers every core capability of: {st['purpose']}", "gaps": []}
    if stage == "spec_verify":
        return {"verified": True, "confidence": "high",
                "summary": "The build delivers what was asked.", "gaps": []}
    if stage == "design_critic":
        return {"design_aligned": True, "ui_kind_mismatch": False, "issues": [], "recommendations": []}
    raise ValueError(f"stub_llm: no stub payload for stage {stage!r}")


def stub_text(case: dict, stage: str) -> str:
    """The raw LLM-shaped text for a stage — fenced JSON, exactly the kind of
    response the pipeline's _extract_json has to strip and parse."""
    return "```json\n" + json.dumps(stub_stage_output(case, stage), indent=2) + "\n```"


def make_call_llm(case: dict):
    """A call_llm-compatible async stub bound to one case. Signature mirrors
    lib.llm_client.call_llm so a future piped mode can monkeypatch it in.
    Token counts are length-derived (deterministic), key_source says 'stub' so
    a stub run can never masquerade as a real provider call in any ledger."""
    async def _call(model: str, system_prompt: str, messages: list, **kwargs) -> dict:
        stage = stage_from_system_prompt(system_prompt)
        text = stub_text(case, stage)
        prompt_chars = len(system_prompt or "") + sum(len(str(m.get("content", ""))) for m in (messages or []))
        return {
            "text": text,
            "input_tokens": max(1, prompt_chars // 4),
            "output_tokens": max(1, len(text) // 4),
            "model": model,
            "key_source": "stub",
            "token_source": "stub",
        }
    return _call


__all__ = ["stage_from_system_prompt", "stub_stage_output", "stub_text", "make_call_llm"]
