// Architecture viewer: spec -> fixed column layout -> React Flow, with editing.
import React, { useState, useEffect, useLayoutEffect, useMemo, useRef, useCallback } from "react";
import { createRoot } from "react-dom";
import {
  ReactFlow, Background, Controls, Handle, Position, BaseEdge, EdgeLabelRenderer,
  MarkerType, getBezierPath, getSmoothStepPath,
} from "@xyflow/react";
import htm from "htm";

const html = htm.bind(React.createElement);

// Layout template (px). Positions are always computed, never stored.
const CARD_W = 320;
const PAD = 18;        // group padding
const GAP = 44;        // between cards in a group (room for an edge label)
const INNER = 12;      // class card inner padding around method cards
const MGAP = 10;       // between method cards
const COL_GAP = 170;   // between script columns (room for edge labels)
const ROW_GAP = 48;    // between groups in the same column
const GROUP_W = CARD_W + 2 * PAD;
const METHOD_W = CARD_W - 2 * INNER;
const STATUSES = ["planned", "built", "changed"];
const KINDS = ["function", "class", "stage"]; // "method" is only created inside a class
const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;

// ------------------------------------------------------------------ model

function buildModel(spec) {
  const byRef = new Map();
  const scripts = [];
  for (const s of spec.scripts || []) {
    const nodes = (s.nodes || []).filter((n) => n && n.id);
    const classes = new Set(nodes.filter((n) => n.kind === "class").map((n) => n.id));
    const units = [];
    const unitOf = new Map();
    nodes.forEach((n, index) => {
      const ref = `${s.id}.${n.id}`;
      const cls = n.id.split(".")[0];
      const parent = n.kind === "method" && n.id.includes(".") && classes.has(cls) ? `${s.id}.${cls}` : null;
      byRef.set(ref, { ref, node: n, script: s, parent });
      if (!parent) {
        const u = { ref, index, methods: [] };
        units.push(u);
        unitOf.set(ref, u);
      }
    });
    for (const info of byRef.values()) {
      if (info.script === s && info.parent) {
        const u = unitOf.get(info.parent);
        u.methods.push(info.ref);
        unitOf.set(info.ref, u);
      }
    }
    scripts.push({ script: s, units, unitOf });
  }

  const edges = (spec.edges || [])
    .map((e, i) => ({ ...e, id: `e${i}`, index: i }))
    .filter((e) => byRef.has(e.from) && byRef.has(e.to));

  for (const sc of scripts) sc.units = topoOrder(sc, edges);

  return { scripts, edges, byRef, layer: scriptLayers(scripts, edges, byRef) };
}

// Order cards in a script by data flow, falling back to spec order.
function topoOrder(sc, edges) {
  const indeg = new Map(sc.units.map((u) => [u, 0]));
  const next = new Map(sc.units.map((u) => [u, []]));
  for (const e of edges) {
    const a = sc.unitOf.get(e.from), b = sc.unitOf.get(e.to);
    if (a && b && a !== b) { next.get(a).push(b); indeg.set(b, indeg.get(b) + 1); }
  }
  const out = [];
  const ready = sc.units.filter((u) => indeg.get(u) === 0);
  while (ready.length) {
    ready.sort((x, y) => x.index - y.index);
    const u = ready.shift();
    out.push(u);
    for (const v of next.get(u)) { indeg.set(v, indeg.get(v) - 1); if (indeg.get(v) === 0) ready.push(v); }
  }
  for (const u of sc.units) if (!out.includes(u)) out.push(u); // cycles: keep spec order
  out.forEach((u, i) => (u.order = i));
  return out;
}

// Column per script: longest path over script-to-script edges.
function scriptLayers(scripts, edges, byRef) {
  const layer = Object.fromEntries(scripts.map((s) => [s.script.id, 0]));
  const max = scripts.length - 1;
  for (let i = 0; i < scripts.length; i++) {
    let changed = false;
    for (const e of edges) {
      const a = byRef.get(e.from).script.id, b = byRef.get(e.to).script.id;
      if (a !== b && layer[b] < layer[a] + 1 && layer[a] < max) { layer[b] = layer[a] + 1; changed = true; }
    }
    if (!changed) break;
  }
  return layer;
}

// ------------------------------------------------------------------ edits
// Each takes a draft copy of the spec and changes it in place.

function findNode(spec, ref) {
  for (const script of spec.scripts || []) {
    const nodes = script.nodes || [];
    const index = nodes.findIndex((n) => `${script.id}.${n.id}` === ref);
    if (index >= 0) return { script, node: nodes[index], index };
  }
  return null;
}

function uniqueId(script, base) {
  const ids = new Set((script.nodes || []).map((n) => n.id));
  if (!ids.has(base)) return base;
  let i = 2;
  while (ids.has(`${base}_${i}`)) i++;
  return `${base}_${i}`;
}

function addNode(spec, scriptId, classId) {
  const script = spec.scripts.find((s) => s.id === scriptId);
  script.nodes = script.nodes || [];
  const id = classId
    ? uniqueId(script, `${classId}.new_method`)
    : uniqueId(script, "new_function");
  script.nodes.push({ id, kind: classId ? "method" : "function", status: "planned", purpose: "" });
  return `${scriptId}.${id}`;
}

function renameNode(spec, ref, newId) {
  const { script, node } = findNode(spec, ref);
  const moved = new Map([[ref, `${script.id}.${newId}`]]);
  if (node.kind === "class") {
    for (const m of script.nodes) {
      if (m.kind === "method" && m.id.startsWith(node.id + ".")) {
        const id = newId + m.id.slice(node.id.length);
        moved.set(`${script.id}.${m.id}`, `${script.id}.${id}`);
        m.id = id;
      }
    }
  }
  node.id = newId;
  for (const e of spec.edges || []) {
    if (moved.has(e.from)) e.from = moved.get(e.from);
    if (moved.has(e.to)) e.to = moved.get(e.to);
  }
  return moved.get(ref);
}

function deleteNode(spec, ref) {
  const { script, node } = findNode(spec, ref);
  const gone = new Set([ref]);
  script.nodes = script.nodes.filter((n) => {
    const r = `${script.id}.${n.id}`;
    const isOwnMethod = node.kind === "class" && n.kind === "method" && n.id.startsWith(node.id + ".");
    if (r === ref || isOwnMethod) { gone.add(r); return false; }
    return true;
  });
  spec.edges = (spec.edges || []).filter((e) => !gone.has(e.from) && !gone.has(e.to));
}

// Set a field; empty optional values are removed rather than saved as "".
function setField(obj, key, value, required = false) {
  const empty = value === "" || (Array.isArray(value) && value.length === 0);
  if (empty && !required) delete obj[key];
  else obj[key] = value;
}

const splitList = (text) => text.split(",").map((x) => x.trim()).filter(Boolean);

// ------------------------------------------------------------------ layout

function computeLayout(model, sizes, cardData) {
  const h = (k) => sizes[k] ?? 80;
  const nodes = [];
  const colY = new Map();

  for (const sc of model.scripts) {
    const sid = sc.script.id;
    const gid = `s:${sid}`;
    const children = [];
    let y = h(gid);
    for (const u of sc.units) {
      const top = h(u.ref);
      let uh = top;
      const kids = [];
      if (u.methods.length) {
        let my = top;
        for (const m of u.methods) { kids.push({ ref: m, y: my }); my += h(m) + MGAP; }
        uh = my - MGAP + INNER;
      }
      children.push({ ref: u.ref, y, h: uh, kids });
      y += uh + GAP;
    }
    const gh = children.length ? y - GAP + PAD : h(gid) + PAD;
    const col = model.layer[sid];
    const gy = colY.get(col) ?? 0;
    colY.set(col, gy + gh + ROW_GAP);

    nodes.push({
      id: gid, type: "script", position: { x: col * (GROUP_W + COL_GAP), y: gy },
      data: { script: sc.script, ...cardData(gid) }, style: { width: GROUP_W, height: gh },
      draggable: false, connectable: false,
    });
    for (const c of children) {
      nodes.push({
        id: c.ref, type: "card", parentId: gid, position: { x: PAD, y: c.y },
        data: { info: model.byRef.get(c.ref), container: c.kids.length > 0, ...cardData(c.ref) },
        style: { width: CARD_W, height: c.h }, draggable: false,
      });
      for (const k of c.kids) {
        nodes.push({
          id: k.ref, type: "card", parentId: c.ref, position: { x: INNER, y: k.y },
          data: { info: model.byRef.get(k.ref), ...cardData(k.ref) },
          style: { width: METHOD_W, height: h(k.ref) }, draggable: false,
        });
      }
    }
  }
  return nodes;
}

// Pick handles so arrows stay readable:
//   other script        -> right side into left side
//   next card below      -> bottom into top
//   same script, farther -> bracket on the right side
function edgeRoute(model, e) {
  const a = model.byRef.get(e.from), b = model.byRef.get(e.to);
  if (a.script.id !== b.script.id) return { sourceHandle: "r", targetHandle: "l", route: "curve" };
  const sc = model.scripts.find((s) => s.script === a.script);
  let adjacent = false;
  if (!a.parent && !b.parent) {
    adjacent = sc.unitOf.get(b.ref).order === sc.unitOf.get(a.ref).order + 1;
  } else if (a.parent && a.parent === b.parent) {
    const ms = sc.unitOf.get(a.ref).methods;
    adjacent = ms.indexOf(b.ref) === ms.indexOf(a.ref) + 1;
  }
  return adjacent
    ? { sourceHandle: "b", targetHandle: "t", route: "curve" }
    : { sourceHandle: "r", targetHandle: "rt", route: "loop" };
}

function buildEdges(model, selectedEdge) {
  return model.edges.map((e) => {
    const { route, ...handles } = edgeRoute(model, e);
    const selected = e.index === selectedEdge;
    return {
      id: e.id, source: e.from, target: e.to, type: "data", ...handles,
      zIndex: 1000, // above the script group boxes, which would otherwise hide them
      data: { label: e.data, shape: e.shape, route, selected, index: e.index },
      markerEnd: { type: MarkerType.ArrowClosed, color: selected ? "#3b82f6" : "#8a93a3", width: 16, height: 16 },
      style: { stroke: selected ? "var(--accent)" : "var(--edge)", strokeWidth: selected ? 2.5 : 1.5 },
    };
  });
}

// ------------------------------------------------------------------ live activity

const MAX_EVENTS = 300;
const ACTIVE_MS = 20000;  // a card glows this long after Claude touched it
const GLOW = { read: "read", edit: "edit", write: "edit", run: "run", "run-error": "error" };
const CHANGES = new Set(["edit", "write"]);
const VERB = {
  read: "reading", edit: "editing", write: "rewrote", run: "running", "run-error": "run failed",
  check: "checking", "check-result": "check", test: "testing", "test-result": "tests", todo: "step",
};

// Per card / script group: {state: glow while recent, touched: changed during the current task}.
function activityStates(events, task, now) {
  const out = {};
  const mark = (key, e) => {
    const s = (out[key] ||= {});
    if (GLOW[e.kind] && now - Date.parse(e.ts) < ACTIVE_MS) s.state = GLOW[e.kind];
    if (CHANGES.has(e.kind) && e.task === task) s.touched = true;
  };
  for (const e of events) {
    if (!e.ts) continue;
    if (e.refs?.length) e.refs.forEach((r) => mark(r, e));
    else if (e.script) mark(`s:${e.script}`, e);
  }
  return out;
}

// Keep the same object while its content is unchanged, so the layout isn't redone every tick.
function useStable(value) {
  const ref = useRef({ key: null, value });
  const key = JSON.stringify(value);
  if (ref.current.key !== key) ref.current = { key, value };
  return ref.current.value;
}

const clock = (ts) => (ts ? new Date(ts).toLocaleTimeString([], { hour12: false }) : "");

// ------------------------------------------------------------------ canvas components

function Issues({ list }) {
  if (!list?.length) return null;
  return html`<div class="card-issues">
    ${list.map((i, k) => html`<div key=${k} class=${"lvl-" + i.level}>${i.level === "error" ? "✕" : "!"} ${i.message}</div>`)}
  </div>`;
}

function Card({ info, issues, expanded, onToggle, selected, container, measure, activity }) {
  const n = info.node;
  const status = STATUSES.includes(n.status) ? n.status : "planned";
  const helpers = n.helpers || [];
  const methods = n.methods || [];
  const name = info.parent ? n.id.split(".").slice(1).join(".") : n.id;
  const hasError = issues?.some((i) => i.level === "error");
  const hasCode = Boolean(n.signature) || methods.length > 0 || helpers.length > 0;
  return html`<div
      class=${`card st-${status}${hasError ? " has-error" : ""}${selected ? " selected" : ""}${activity?.state ? " act-" + activity.state : ""}`}
      data-measure=${measure}
      style=${container ? { height: "100%" } : null}>
    ${activity?.touched && html`<span class="touched" title="Claude changed this during the current task">✎</span>`}
    <div class="card-head">
      <span class="card-name">${name}${n.kind === "method" ? "()" : ""}</span>
      <span class="card-kind">${n.kind}</span>
      <span class="pill">${status}</span>
    </div>
    ${n.purpose
      ? html`<div class="card-purpose">${n.purpose}</div>`
      : html`<div class="card-purpose empty">no purpose yet</div>`}
    ${n.explain
      ? html`<p class="card-explain">${n.explain}</p>`
      : html`<p class="card-explain empty">No explanation yet.</p>`}
    ${hasCode && html`<button class="code-toggle nodrag" onClick=${(ev) => { ev.stopPropagation(); onToggle?.(info.ref); }}>
      ${expanded ? "▾" : "▸"} code details
    </button>`}
    ${hasCode && expanded && html`<div class="code-details">
      ${n.signature && html`<code class="card-sig">${n.signature}</code>`}
      ${methods.length > 0 && html`<div class="code-row"><span>other methods</span>
        ${methods.map((m) => html`<span key=${m} class="chip">.${m}()</span>`)}</div>`}
      ${helpers.length > 0 && html`<div class="code-row"><span>helpers</span>
        ${helpers.map((x) => html`<span key=${x} class="chip">${x}</span>`)}</div>`}
    </div>`}
    <${Issues} list=${issues} />
  </div>`;
}

function ScriptHead({ script, issues, onAdd, measure }) {
  return html`<div class="group-head" data-measure=${measure}>
    <div class="group-title">
      <b>${script.id}</b><span class="group-file">${script.file}</span>
      <button class="add-btn nodrag" title="Add a node to this script"
        onClick=${(ev) => { ev.stopPropagation(); onAdd?.(script.id); }}>+ node</button>
    </div>
    ${script.purpose && html`<div class="group-purpose">${script.purpose}</div>`}
    <${Issues} list=${issues} />
  </div>`;
}

function CardNode({ data }) {
  return html`<${React.Fragment}>
    <${Handle} type="target" position=${Position.Top} id="t" />
    <${Handle} type="target" position=${Position.Left} id="l" />
    <${Handle} type="target" position=${Position.Right} id="rt" />
    <${Card} ...${data} />
    <${Handle} type="source" position=${Position.Bottom} id="b" />
    <${Handle} type="source" position=${Position.Right} id="r" />
  <//>`;
}

function ScriptNode({ data }) {
  const act = data.activity;
  return html`<div class=${`group${act?.state ? " act-" + act.state : ""}`}>
    ${act?.touched && html`<span class="touched" title="Claude rewrote this file during the current task">✎</span>`}
    <${ScriptHead} script=${data.script} issues=${data.issues} onAdd=${data.onAdd} />
  </div>`;
}

function DataEdge(p) {
  const args = {
    sourceX: p.sourceX, sourceY: p.sourceY, targetX: p.targetX, targetY: p.targetY,
    sourcePosition: p.sourcePosition, targetPosition: p.targetPosition,
  };
  const [path, lx, ly] = p.data.route === "loop"
    ? getSmoothStepPath({ ...args, borderRadius: 10, offset: 30 })
    : getBezierPath(args);
  return html`<${React.Fragment}>
    <${BaseEdge} path=${path} markerEnd=${p.markerEnd} style=${p.style} interactionWidth=${16} />
    <${EdgeLabelRenderer}>
      <div class=${`edge-label nodrag nopan${p.data.selected ? " selected" : ""}${p.data.label ? "" : " missing"}`}
        style=${{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}
        onClick=${() => p.data.onSelect?.(p.data.index)}>
        ${p.data.label || "data?"}
        ${p.data.shape && html`<span class="edge-shape">${p.data.shape}</span>`}
      </div>
    <//>
  <//>`;
}

const nodeTypes = { card: CardNode, script: ScriptNode };
const edgeTypes = { data: DataEdge };

// Renders every card off-screen at its real width so the layout can use real heights.
function Measure({ model, cardData, onSizes }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const sizes = {};
    ref.current.querySelectorAll("[data-measure]").forEach((el) => (sizes[el.dataset.measure] = el.offsetHeight));
    onSizes(sizes);
  });
  const items = [];
  for (const sc of model.scripts) {
    const gid = `s:${sc.script.id}`;
    items.push(html`<div key=${gid} style=${{ width: GROUP_W }}><${ScriptHead} script=${sc.script} issues=${cardData(gid).issues} measure=${gid} /></div>`);
    for (const u of sc.units) {
      for (const ref of [u.ref, ...u.methods]) {
        const info = model.byRef.get(ref);
        items.push(html`<div key=${ref} style=${{ width: info.parent ? METHOD_W : CARD_W }}>
          <${Card} info=${info} ...${cardData(ref)} measure=${ref} />
        </div>`);
      }
    }
  }
  return html`<div ref=${ref} style=${{ position: "absolute", left: -10000, top: 0, visibility: "hidden" }}>${items}</div>`;
}

// ------------------------------------------------------------------ inspector

// Text field that commits on blur/Enter (used for ids, where every keystroke would re-key the graph).
function CommitInput({ value, onCommit, validate, ...rest }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const error = text !== value ? validate?.(text) : null;
  const commit = () => { if (text !== value && !validate?.(text)) onCommit(text); else setText(value); };
  return html`<${React.Fragment}>
    <input ...${rest} value=${text} onChange=${(e) => setText(e.target.value)} onBlur=${commit}
      onKeyDown=${(e) => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") { setText(value); } }} />
    ${error && html`<div class="field-error">${error}</div>`}
  <//>`;
}

// List field: shows "a, b" and commits the parsed list on blur.
function ListInput({ value, onCommit, ...rest }) {
  const joined = (value || []).join(", ");
  return html`<${CommitInput} ...${rest} value=${joined} onCommit=${(t) => onCommit(splitList(t))} />`;
}

function NodeInspector({ spec, sel, edit, select, close }) {
  const found = findNode(spec, sel);
  if (!found) return null;
  const { script, node } = found;
  const isMethod = node.kind === "method";
  const prefix = isMethod ? node.id.split(".")[0] + "." : "";
  const shortId = node.id.slice(prefix.length);
  const known = new Set(["id", "kind", "status", "purpose", "explain", "signature", "helpers", "methods"]);
  const extra = Object.keys(node).filter((k) => !known.has(k));
  const validateId = (t) => {
    if (!IDENT.test(t)) return "use letters, digits and _ only";
    if (script.nodes.some((n) => n !== node && n.id === prefix + t)) return "already used in this script";
    return null;
  };
  const patch = (fn) => edit((s) => fn(findNode(s, sel).node));

  return html`<div class="inspector">
    <div class="insp-head"><span>${script.id} · ${node.kind}</span><button class="x" onClick=${close}>×</button></div>
    <label>Name</label>
    <div class="id-row">${prefix && html`<span class="id-prefix">${prefix}</span>`}
      <${CommitInput} class="mono" value=${shortId} validate=${validateId}
        onCommit=${(t) => edit((s) => select({ node: renameNode(s, sel, prefix + t) }))} />
    </div>
    <div class="two">
      <div><label>Kind</label>
        <select value=${node.kind} disabled=${isMethod} onChange=${(e) => patch((n) => { n.kind = e.target.value; })}>
          ${(isMethod ? ["method"] : KINDS).map((k) => html`<option key=${k}>${k}</option>`)}
        </select></div>
      <div><label>Status</label>
        <select value=${node.status} onChange=${(e) => patch((n) => { n.status = e.target.value; })}>
          ${STATUSES.map((k) => html`<option key=${k}>${k}</option>`)}
        </select></div>
    </div>
    <label>Purpose <span class="hint">one-line headline</span></label>
    <textarea rows="2" value=${node.purpose || ""} onChange=${(e) => patch((n) => setField(n, "purpose", e.target.value, true))} />
    <label>Explain <span class="hint">in, what happens, out, why</span></label>
    <textarea rows="7" placeholder="Plain words, no code terms: what comes in, what is done to it, what goes out, and why the next step needs it."
      value=${node.explain || ""} onChange=${(e) => patch((n) => setField(n, "explain", e.target.value))} />
    <div class="insp-section">Code details</div>
    <label>Signature</label>
    <input class="mono" placeholder=${`${shortId}(x: T) -> R`} value=${node.signature || ""}
      onChange=${(e) => patch((n) => setField(n, "signature", e.target.value))} />
    <label>Helpers <span class="hint">comma-separated</span></label>
    <${ListInput} class="mono" value=${node.helpers} onCommit=${(v) => patch((n) => setField(n, "helpers", v))} />
    ${node.kind === "class" && html`<${React.Fragment}>
      <label>Other methods <span class="hint">not on the data path</span></label>
      <${ListInput} class="mono" value=${node.methods} onCommit=${(v) => patch((n) => setField(n, "methods", v))} />
    <//>`}
    ${extra.length > 0 && html`<div class="hint extra">Also kept: ${extra.join(", ")}</div>`}
    <div class="insp-actions">
      ${node.kind === "class" && html`<button class="btn" onClick=${() => edit((s) => select({ node: addNode(s, script.id, node.id) }))}>+ method node</button>`}
      <button class="btn danger" onClick=${() => { edit((s) => deleteNode(s, sel)); close(); }}>Delete node</button>
    </div>
  </div>`;
}

function EdgeInspector({ spec, index, edit, close }) {
  const e = spec.edges?.[index];
  if (!e) return null;
  const patch = (fn) => edit((s) => fn(s.edges[index]));
  return html`<div class="inspector">
    <div class="insp-head"><span>data flow</span><button class="x" onClick=${close}>×</button></div>
    <div class="edge-ends mono">${e.from}<br />→ ${e.to}</div>
    <label>Data <span class="hint">what travels</span></label>
    <input autoFocus=${!e.data} placeholder="e.g. cleaned DataFrame" value=${e.data || ""}
      onChange=${(ev) => patch((x) => setField(x, "data", ev.target.value, true))} />
    <label>Shape <span class="hint">optional</span></label>
    <input class="mono" placeholder="e.g. X (N, 32) float32" value=${e.shape || ""}
      onChange=${(ev) => patch((x) => setField(x, "shape", ev.target.value))} />
    <div class="insp-actions">
      <button class="btn danger" onClick=${() => { edit((s) => s.edges.splice(index, 1)); close(); }}>Delete arrow</button>
    </div>
  </div>`;
}

function ActivityStrip({ events, live, model, onPick, onClose }) {
  const rows = events.slice(-120).reverse();
  const target = (e) => {
    if (e.refs?.length) {
      return e.refs.map((r) => html`<button key=${r} class="act-ref" disabled=${!model?.byRef.has(r)}
        onClick=${() => onPick(r)}>${r}</button>`);
    }
    return html`<span class="act-file">${e.file || (e.script ? `${e.script} (whole script)` : "")}</span>`;
  };
  return html`<div class="activity">
    <div class="act-head">
      <b>Claude's activity</b>
      <span class="hint">${live.session ? `session ${live.session.slice(0, 8)}` : "no Claude session found for this project yet"}</span>
      <button class="x" onClick=${onClose}>×</button>
    </div>
    <div class="act-rows">
      ${rows.length === 0 && html`<div class="act-empty">Nothing yet. Activity appears here as Claude reads and edits this project.</div>`}
      ${rows.map((e) => e.kind === "task"
        ? html`<div key=${e.seq} class="act-task">💬 ${e.detail}</div>`
        : html`<div key=${e.seq} class=${`act-row k-${e.kind}${e.ok === true ? " good" : e.ok === false ? " bad" : ""}`}>
            <span class="act-time">${clock(e.ts)}</span>
            <span class="act-verb">${e.ok === true ? "✓ " : e.ok === false ? "✕ " : ""}${VERB[e.kind] || e.kind}</span>
            <span class="act-target">${["read", "edit", "write", "run"].includes(e.kind) ? target(e) : null}
              ${!["read", "edit", "write", "run"].includes(e.kind) && e.detail && html`<span class="act-detail">${e.detail}</span>`}</span>
          </div>`)}
    </div>
  </div>`;
}

// ------------------------------------------------------------------ app

function App() {
  const [payload, setPayload] = useState(null);   // last version read from / written to disk
  const [draft, setDraft] = useState(null);       // unsaved edits, or null
  const [loadError, setLoadError] = useState(null);
  const [saveState, setSaveState] = useState("idle"); // idle | saving | saved | error
  const [conflict, setConflict] = useState(false);
  const [expanded, setExpanded] = useState(() => new Set());
  const [sizes, setSizes] = useState(null);
  const [showIssues, setShowIssues] = useState(false);
  const [sel, setSel] = useState(null);           // {node: ref} | {edge: index} | null
  const [live, setLive] = useState({ seq: 0, task: null, on: false, session: null });
  const [events, setEvents] = useState([]);       // live session events, oldest first
  const [now, setNow] = useState(() => Date.now());
  const [showActivity, setShowActivity] = useState(true);

  const spec = draft ?? payload?.spec;
  const dirty = draft !== null;

  const accept = useCallback((p) => {
    setPayload(p);
    document.title = `${p.spec?.project ?? "Architecture"} · archview`;
  }, []);

  const load = useCallback(() => {
    fetch("/api/spec")
      .then((r) => r.json())
      .then((p) => { accept(p); setDraft(null); setConflict(false); setLoadError(null); })
      .catch((e) => setLoadError(String(e)));
  }, [accept]);
  useEffect(load, [load]);

  const save = useCallback(async (force = false) => {
    if (!draft) return;
    setSaveState("saving");
    try {
      const r = await fetch("/api/spec", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec: draft, mtime: payload.mtime, force }),
      });
      const p = await r.json();
      if (r.status === 409) { setConflict(true); setSaveState("idle"); return; }
      if (!r.ok) throw new Error(p.error || r.statusText);
      accept(p);
      setDraft(null);
      setConflict(false);
      setSaveState("saved");
    } catch (e) {
      setSaveState("error");
      console.error(e);
    }
  }, [draft, payload, accept]);

  // One poll per second: live session activity, plus noticing when the file changes on disk.
  const stateRef = useRef({});
  stateRef.current = { payload, dirty, saving: saveState === "saving", live };
  useEffect(() => {
    const t = setInterval(async () => {
      const { payload, dirty, saving, live } = stateRef.current;
      try {
        const a = await (await fetch(`/api/activity?after=${live.seq}`)).json();
        setNow(Date.now());
        if (a.seq !== live.seq || a.task !== live.task || a.live !== live.on || a.session !== live.session) {
          setLive({ seq: a.seq, task: a.task, on: a.live, session: a.session });
          if (a.events.length) setEvents((old) => [...old, ...a.events].slice(-MAX_EVENTS));
        }
        if (!payload || saving || a.mtime === payload.mtime) return;
        if (dirty) setConflict(true);
        else load();
      } catch { /* server stopped; keep the page as is */ }
    }, 1000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    const warn = (e) => { if (stateRef.current.dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  const edit = useCallback((fn) => {
    setDraft((old) => {
      const next = structuredClone(old ?? stateRef.current.payload.spec);
      fn(next);
      return next;
    });
    setSaveState("idle");
  }, []);

  const model = useMemo(() => (spec ? buildModel(spec) : null), [spec]);

  const issuesBy = useMemo(() => {
    const m = new Map();
    for (const i of payload?.issues || []) {
      const key = model?.byRef.has(i.where) ? i.where : `s:${i.where}`;
      m.set(key, [...(m.get(key) || []), i]);
    }
    return m;
  }, [payload, model]);

  const toggle = useCallback((ref) => setExpanded((old) => {
    const s = new Set(old);
    s.has(ref) ? s.delete(ref) : s.add(ref);
    return s;
  }), []);

  const addTo = useCallback((sid) => edit((s) => setSel({ node: addNode(s, sid) })), [edit]);

  const activity = useStable(useMemo(() => activityStates(events, live.task, now), [events, live.task, now]));

  const cardData = useCallback((key) => ({
    issues: issuesBy.get(key), expanded: expanded.has(key), onToggle: toggle,
    selected: sel?.node === key, onAdd: addTo, activity: activity[key],
  }), [issuesBy, expanded, toggle, sel, addTo, activity]);

  const selectEdge = useCallback((index) => setSel({ edge: index }), []);
  const onSizes = useCallback((s) => setSizes((old) => (JSON.stringify(old) === JSON.stringify(s) ? old : s)), []);
  const nodes = useMemo(() => (model && sizes ? computeLayout(model, sizes, cardData) : []), [model, sizes, cardData]);
  const edges = useMemo(() => (model ? buildEdges(model, sel?.edge).map((e) => ({ ...e, data: { ...e.data, onSelect: selectEdge } })) : []),
    [model, sel, selectEdge]);

  const onConnect = useCallback(({ source, target }) => {
    if (!model?.byRef.has(source) || !model.byRef.has(target) || source === target) return;
    if ((spec.edges || []).some((e) => e.from === source && e.to === target)) return;
    edit((s) => { s.edges = s.edges || []; s.edges.push({ from: source, to: target, data: "" }); setSel({ edge: s.edges.length - 1 }); });
  }, [model, spec, edit]);

  // Keyboard: Ctrl+S saves, Delete removes the selection, Escape deselects.
  useEffect(() => {
    const onKey = (e) => {
      const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); return; }
      if (typing) return;
      if (e.key === "Escape") setSel(null);
      if ((e.key === "Delete" || e.key === "Backspace") && sel) {
        if (sel.node) edit((s) => deleteNode(s, sel.node));
        else edit((s) => s.edges.splice(sel.edge, 1));
        setSel(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save, sel, edit]);

  if (loadError) return html`<div class="message">Cannot reach the archview server.<pre>${loadError}</pre></div>`;
  if (!payload) return html`<div class="message">Loading…</div>`;
  if (payload.error && !draft) return html`<div class="message">The spec could not be read.<pre>${payload.error}</pre>
    <button class="btn" onClick=${load}>Try again</button></div>`;

  const all = payload.issues || [];
  const errors = all.filter((i) => i.level === "error").length;
  const warnings = all.length - errors;
  const status = dirty
    ? html`<span class="save-state dirty">● unsaved changes</span>`
    : saveState === "saved" ? html`<span class="save-state ok">✓ saved</span>`
    : saveState === "error" ? html`<span class="save-state bad">save failed</span>` : null;

  return html`<div class="app">
    <div class="bar">
      <h1>${spec.project}</h1>
      <span class="path" title=${payload.path}>${payload.path.split(/[\\/]/).slice(-2).join("/")}</span>
      <span class="spacer"></span>
      ${live.on && html`<button class=${`btn live${showActivity ? " on" : ""}`} onClick=${() => setShowActivity((v) => !v)}
        title=${live.task ? `Current task: ${live.task}` : "Claude's activity"}>
        <span class="live-dot"></span>${live.task ? live.task.slice(0, 48) + (live.task.length > 48 ? "…" : "") : "activity"}
      </button>`}
      <div class="legend">
        <span style=${{ "--c": "var(--planned)" }}>planned</span>
        <span style=${{ "--c": "var(--built)" }}>built</span>
        <span style=${{ "--c": "var(--changed)" }}>changed</span>
      </div>
      <button class=${`btn ${errors ? "err" : warnings ? "warn" : ""}`} onClick=${() => setShowIssues((v) => !v)}
        title=${dirty ? "Checked against the last saved version" : ""}>
        ${all.length ? `${errors} error${errors === 1 ? "" : "s"}, ${warnings} warning${warnings === 1 ? "" : "s"}` : "✓ in sync"}
      </button>
      ${status}
      <button class="btn primary" disabled=${!dirty || saveState === "saving"} onClick=${() => save()}>
        ${saveState === "saving" ? "Saving…" : "Save"}
      </button>
    </div>
    ${conflict && html`<div class="conflict">
      <b>architecture.yaml changed on disk</b> (probably Claude) while you had unsaved edits.
      <button class="btn" onClick=${load}>Load theirs (discard mine)</button>
      <button class="btn danger" onClick=${() => save(true)}>Overwrite with mine</button>
    </div>`}
    <div class="canvas">
      ${showIssues && all.length > 0 && html`<div class="issues">
        ${all.map((i, k) => html`<div key=${k} class="row">
          <span class=${"lvl-" + i.level}>${i.level}</span> <span class="where">${i.where}</span> — ${i.message}
        </div>`)}
      </div>`}
      ${sel?.node && html`<${NodeInspector} key=${sel.node} spec=${spec} sel=${sel.node} edit=${edit} select=${setSel} close=${() => setSel(null)} />`}
      ${sel?.edge !== undefined && sel?.edge !== null && html`<${EdgeInspector} key=${"e" + sel.edge} spec=${spec} index=${sel.edge} edit=${edit} close=${() => setSel(null)} />`}
      <${Measure} model=${model} cardData=${cardData} onSizes=${onSizes} />
      ${model.scripts.length === 0 && html`<div class="message">
        <b>No scripts planned yet.</b><br />
        Ask Claude to plan a feature. It will add the steps to architecture.yaml, and they appear here for review.
      </div>`}
      ${nodes.length > 0 && html`<${ReactFlow}
        nodes=${nodes} edges=${edges} nodeTypes=${nodeTypes} edgeTypes=${edgeTypes}
        nodesDraggable=${false} nodesConnectable=${true} elementsSelectable=${false}
        connectionMode="loose" onConnect=${onConnect}
        onNodeClick=${(_, n) => setSel(n.type === "card" ? { node: n.id } : null)}
        onEdgeClick=${(_, e) => setSel({ edge: e.data.index })}
        onPaneClick=${() => setSel(null)}
        deleteKeyCode=${null}
        fitView=${true} fitViewOptions=${{ padding: 0.15 }} minZoom=${0.2} colorMode="system">
        <${Background} gap=${24} size=${1} />
        <${Controls} showInteractive=${false} />
      <//>`}
    </div>
    ${live.on && showActivity && html`<${ActivityStrip} events=${events} live=${live} model=${model}
      onPick=${(ref) => setSel({ node: ref })} onClose=${() => setShowActivity(false)} />`}
  </div>`;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
