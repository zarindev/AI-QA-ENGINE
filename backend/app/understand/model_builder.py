"""Stage ③ Site Model: combine crawl + profile into one knowledge graph (NetworkX MultiDiGraph).

Node kinds: role, module, feature, page, entity, field.            (workflows/states are added in stage ④)
Edge kinds: can_access (role→page), links_to (page→page), shows / creates / updates (page→entity),
            has_field (entity→field), relates_to (entity→entity), in_module (feature→module),
            on_page (feature→page), uses (role→feature).

Saved as node-link JSON in site_model.json; `to_react_flow()` turns it into the nodes/edges the UI draws.
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from app.storage.schemas import CrawlResult, SiteProfile
from app.understand import summary as summ

SCHEMA_VERSION = 1
KIND_ORDER = ["role", "module", "feature", "page", "entity", "field"]


def _page_id(template: str) -> str:
    return f"page:{template}"


def build_model(crawl: CrawlResult, profile: SiteProfile) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph(domain=profile.domain, sub_type=profile.sub_type, start_url=crawl.start_url)
    screens = summ.summarize(crawl, max_screens=500)
    templates = {s.template for s in screens}

    for role in sorted({p.role for p in crawl.pages} | set(profile.roles)):
        observed = any(p.role == role for p in crawl.pages)
        g.add_node(f"role:{role}", kind="role", label=role, observed=observed)

    by_template: dict[str, list] = {}
    for page in crawl.pages:
        by_template.setdefault(page.url_template, []).append(page)
    for s in screens:
        pages = by_template[s.template]
        statuses = sorted({p.status_code for p in pages if p.status_code})
        g.add_node(
            _page_id(s.template),
            kind="page",
            label=s.title or s.template,
            template=s.template,
            sample_url=s.sample_url,
            roles=s.roles,
            page_ids=s.page_ids,
            is_login=s.is_login,
            status=statuses[-1] if statuses else None,
            forms=len(pages[0].forms),
            tables=len(pages[0].tables),
        )
        for role in s.roles:
            g.add_edge(f"role:{role}", _page_id(s.template), kind="can_access")

    template_of_url = {p.url: p.url_template for p in crawl.pages}
    for page in crawl.pages:
        for link in page.links:
            target = template_of_url.get(link)
            if target and target != page.url_template and target in templates:
                if not g.has_edge(_page_id(page.url_template), _page_id(target), key="links_to"):
                    g.add_edge(_page_id(page.url_template), _page_id(target), key="links_to", kind="links_to")

    for module in profile.modules:
        g.add_node(f"module:{module}", kind="module", label=module)

    for entity in profile.entities:
        eid = f"entity:{entity.name}"
        g.add_node(
            eid,
            kind="entity",
            label=entity.name,
            operations=list(entity.operations),
            fields=[f.model_dump() for f in entity.fields],
        )
        for fld in entity.fields:
            fid = f"field:{entity.name}.{fld.name}"
            g.add_node(
                fid,
                kind="field",
                label=fld.name,
                entity=entity.name,
                type=fld.type,
                required=fld.required,
                validation=fld.validation,
            )
            g.add_edge(eid, fid, kind="has_field")
        for template in entity.pages:
            if _page_id(template) not in g:
                continue
            page_ops = _ops_on_page(crawl, template)
            kinds = page_ops or ["shows"]
            for kind in kinds:
                g.add_edge(_page_id(template), eid, key=kind, kind=kind)
    for entity in profile.entities:
        for other in entity.relations:
            if f"entity:{other}" in g:
                g.add_edge(f"entity:{entity.name}", f"entity:{other}", kind="relates_to")

    for feature in profile.features:
        fid = f"feature:{feature.id}"
        g.add_node(
            fid, kind="feature", label=feature.name, module=feature.module, description=feature.description
        )
        if feature.module and f"module:{feature.module}" in g:
            g.add_edge(fid, f"module:{feature.module}", kind="in_module")
        for template in feature.pages:
            if _page_id(template) in g:
                g.add_edge(fid, _page_id(template), kind="on_page")
        for role in feature.roles:
            if f"role:{role}" in g:
                g.add_edge(f"role:{role}", fid, kind="uses")
    return g


def _ops_on_page(crawl: CrawlResult, template: str) -> list[str]:
    """create/update when the page has a data-entry form, shows otherwise."""
    page = next((p for p in crawl.pages if p.url_template == template), None)
    if page is None:
        return []
    ops = []
    for form in page.forms:
        if len(form.field_indices) >= 2 and form.purpose in ("create", "edit", "other"):
            ops.append("updates" if form.purpose == "edit" or "edit" in template else "creates")
    if page.tables:
        ops.append("shows")
    return sorted(set(ops))


def to_json(g: nx.MultiDiGraph) -> dict[str, Any]:
    data = nx.node_link_data(g, edges="links")
    return {"schema_version": SCHEMA_VERSION, "graph": data, "stats": stats(g)}


def from_json(data: dict[str, Any]) -> nx.MultiDiGraph:
    return nx.node_link_graph(data["graph"], directed=True, multigraph=True, edges="links")


def stats(g: nx.MultiDiGraph) -> dict[str, int]:
    out: dict[str, int] = {kind: 0 for kind in KIND_ORDER}
    for _, attrs in g.nodes(data=True):
        out[attrs.get("kind", "other")] = out.get(attrs.get("kind", "other"), 0) + 1
    out["edges"] = g.number_of_edges()
    return out


def to_react_flow(g: nx.MultiDiGraph, kinds: list[str] | None = None) -> dict[str, Any]:
    """Columns by kind (roles → modules → features → pages → entities → fields), rows by order of appearance.
    The UI can re-layout; this gives a readable first picture without a JS layout library."""
    kinds = kinds or ["role", "page", "entity"]
    max_rows, col_w, row_h, kind_gap = 9, 250, 84, 110
    members: dict[str, list[tuple[str, dict[str, Any]]]] = {k: [] for k in KIND_ORDER}
    for node_id, attrs in g.nodes(data=True):
        if attrs.get("kind") in kinds:
            members[attrs["kind"]].append((node_id, attrs))
    nodes = []
    x = 0
    for kind in KIND_ORDER:
        group = members[kind]
        if not group:
            continue
        # Long kinds (40 pages) wrap into several sub-columns instead of one very tall column.
        n_cols = max(1, -(-len(group) // max_rows))
        rows_used = -(-len(group) // n_cols)
        for i, (node_id, attrs) in enumerate(group):
            col, row = divmod(i, rows_used)
            data = {k: v for k, v in attrs.items() if k not in ("fields",)}
            if kind == "entity":
                data["field_count"] = len(attrs.get("fields", []))
                data["fields"] = [f["name"] for f in attrs.get("fields", [])][:12]
            nodes.append(
                {
                    "id": node_id,
                    "type": kind,
                    "position": {"x": x + col * col_w, "y": row * row_h},
                    "data": data,
                }
            )
        x += n_cols * col_w + kind_gap
    visible = {n["id"] for n in nodes}
    edges = []
    for i, (src, dst, attrs) in enumerate(g.edges(data=True)):
        if src in visible and dst in visible:
            edges.append(
                {
                    "id": f"e{i}",
                    "source": src,
                    "target": dst,
                    "label": attrs.get("kind", ""),
                    "data": {"kind": attrs.get("kind", "")},
                }
            )
    return {"nodes": nodes, "edges": edges, "stats": stats(g)}
