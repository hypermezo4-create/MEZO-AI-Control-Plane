# ruff: noqa: E501
from __future__ import annotations

import html
import secrets

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard() -> HTMLResponse:
    nonce = secrets.token_urlsafe(18)
    document = _document(nonce)
    response = HTMLResponse(document)
    response.headers["cache-control"] = "no-store"
    response.headers["content-security-policy"] = (
        "default-src 'none'; connect-src 'self'; img-src 'self' data:; "
        f"style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["referrer-policy"] = "no-referrer"
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    return response


def _document(nonce: str) -> str:
    safe_nonce = html.escape(nonce, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>MEZO Control Plane</title>
  <style nonce="{safe_nonce}">
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    body {{ margin: 0; background: #090d16; color: #eef3ff; }}
    header {{ padding: 18px 24px; border-bottom: 1px solid #263044; display:flex; gap:16px; align-items:center; }}
    h1 {{ font-size: 18px; margin: 0; }}
    main {{ display:grid; grid-template-columns:minmax(420px,1fr) minmax(360px,.8fr); min-height:calc(100vh - 66px); }}
    section {{ padding:20px; border-right:1px solid #263044; overflow:auto; }}
    input,button,textarea {{ background:#121a29; color:#eef3ff; border:1px solid #34405a; border-radius:7px; padding:9px 11px; }}
    input {{ min-width:300px; }} button {{ cursor:pointer; }} button:hover {{ border-color:#7ca7ff; }}
    table {{ width:100%; border-collapse:collapse; margin-top:16px; }}
    th,td {{ text-align:left; padding:10px; border-bottom:1px solid #263044; font-size:13px; }}
    tr[data-task] {{ cursor:pointer; }} tr[data-task]:hover {{ background:#111928; }}
    pre {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#0d1421; padding:14px; border-radius:8px; border:1px solid #263044; }}
    .muted {{ color:#9facbf; }} .actions {{ display:flex; gap:8px; flex-wrap:wrap; margin:12px 0; }}
    .status {{ margin-left:auto; color:#9facbf; font-size:13px; }}
    @media(max-width:900px) {{ main {{ grid-template-columns:1fr; }} section {{ border-right:0; border-bottom:1px solid #263044; }} }}
  </style>
</head>
<body>
<header>
  <h1>MEZO AI Control Plane</h1>
  <input id="apiKey" type="password" autocomplete="off" placeholder="Control-plane API key">
  <button id="connect">Connect</button>
  <span id="status" class="status">Disconnected</span>
</header>
<main>
  <section>
    <div class="actions"><button id="refresh">Refresh tasks</button><button id="alerts">View alerts</button></div>
    <table><thead><tr><th>State</th><th>Repository</th><th>Risk</th><th>Updated</th></tr></thead><tbody id="tasks"></tbody></table>
  </section>
  <section>
    <h2>Task detail</h2>
    <div class="actions">
      <button data-action="cancel">Cancel</button>
      <button data-action="approve">Approve</button>
      <button data-action="reject">Reject</button>
    </div>
    <pre id="detail" class="muted">Select a task.</pre>
  </section>
</main>
<script nonce="{safe_nonce}">
(() => {{
  const keyInput = document.getElementById('apiKey');
  const status = document.getElementById('status');
  const tasksBody = document.getElementById('tasks');
  const detail = document.getElementById('detail');
  let selectedTask = null;

  async function api(path, options = {{}}) {{
    const key = keyInput.value.trim();
    const headers = new Headers(options.headers || {{}});
    headers.set('x-api-key', key);
    if (options.body) headers.set('content-type', 'application/json');
    const response = await fetch(path, {{...options, headers}});
    const body = response.headers.get('content-type')?.includes('json') ? await response.json() : await response.text();
    if (!response.ok) throw new Error(typeof body === 'string' ? body : (body.error?.message || JSON.stringify(body)));
    return body;
  }}

  async function loadTasks() {{
    status.textContent = 'Loading…';
    const page = await api('/v1/tasks?offset=0&limit=100');
    tasksBody.replaceChildren(...page.items.map(task => {{
      const row = document.createElement('tr'); row.dataset.task = task.id;
      [task.state, task.request.repository, task.risk, new Date(task.updated_at).toLocaleString()].forEach(value => {{
        const cell = document.createElement('td'); cell.textContent = value; row.appendChild(cell);
      }});
      row.addEventListener('click', () => loadTask(task.id));
      return row;
    }}));
    status.textContent = `${{page.total}} task(s)`;
  }}

  async function loadTask(id) {{
    selectedTask = id;
    const [task, report] = await Promise.all([api(`/v1/tasks/${{id}}`), api(`/v1/tasks/${{id}}/report`)]);
    detail.textContent = JSON.stringify({{task, report}}, null, 2);
  }}

  async function act(action) {{
    if (!selectedTask) return;
    const reason = prompt(`Reason for ${{action}}:`);
    if (!reason) return;
    const suffix = action === 'approve' ? 'approvals' : action === 'reject' ? 'rejections' : 'cancel';
    const result = await api(`/v1/tasks/${{selectedTask}}/${{suffix}}`, {{method:'POST', body:JSON.stringify({{reason}})}});
    detail.textContent = JSON.stringify(result, null, 2); await loadTasks();
  }}

  document.getElementById('connect').addEventListener('click', async () => {{
    try {{ await loadTasks(); }} catch (error) {{ status.textContent = error.message; }}
  }});
  document.getElementById('refresh').addEventListener('click', () => loadTasks().catch(error => status.textContent = error.message));
  document.getElementById('alerts').addEventListener('click', async () => {{
    try {{ detail.textContent = JSON.stringify(await api('/v1/observability/alerts'), null, 2); }} catch(error) {{ status.textContent = error.message; }}
  }});
  document.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => act(button.dataset.action).catch(error => status.textContent = error.message)));
  if (keyInput.value) loadTasks().catch(error => status.textContent = error.message);
}})();
</script>
</body>
</html>"""
