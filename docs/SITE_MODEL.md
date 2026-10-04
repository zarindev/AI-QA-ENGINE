# Site Model

After exploring, QA Pilot combines the crawl (`crawl/pages.json`) with the site profile (`site_profile.json`)
into one knowledge graph: a NetworkX `MultiDiGraph` stored in `site_model.json` (node-link format). Later stages
read it to design tests; the UI draws it with React Flow.

## Nodes

| Kind | Id | Attributes |
|---|---|---|
| `role` | `role:admin` | `observed` (true when QA Pilot logged in as this role) |
| `page` | `page:/patients/{id}` | `template`, `label` (title), `sample_url`, `roles`, `page_ids`, `is_login`, `status`, `forms`, `tables` |
| `entity` | `entity:Patient` | `operations` (create/read/update/delete/list/search), `fields` |
| `field` | `field:Patient.Date of birth` | `entity`, `type`, `required`, `validation` |
| `module` | `module:Billing` | — |
| `feature` | `feature:FT-03` | `module`, `description` |

Pages are **URL templates**, not URLs: `/patients/12` and `/patients/13` are one screen, `/patients/{id}`.
Workflow and state nodes are added by the Requirements stage (Phase 3).

## Edges

| Kind | From → To | Meaning |
|---|---|---|
| `can_access` | role → page | The role opened this screen during exploration |
| `links_to` | page → page | A link on one screen leads to the other |
| `shows` / `creates` / `updates` | page → entity | The screen lists the entity, or has a form that creates/edits it |
| `has_field` | entity → field | |
| `relates_to` | entity → entity | e.g. Appointment → Patient (a field named after another entity) |
| `in_module` | feature → module | |
| `on_page` | feature → page | |
| `uses` | role → feature | |

## File format

```json
{
  "schema_version": 1,
  "graph": { "directed": true, "multigraph": true, "graph": {"domain": "healthcare", ...},
             "nodes": [{"id": "role:doctor", "kind": "role", ...}, ...],
             "links": [{"source": "role:doctor", "target": "page:/patients", "kind": "can_access", "key": 0}, ...] },
  "stats": { "role": 4, "page": 16, "entity": 5, "field": 36, "module": 7, "feature": 7, "edges": 240 }
}
```

Load it with `networkx.node_link_graph(data["graph"], edges="links")`, or call
`app.understand.model_builder.from_json(data)`.

## API

- `GET /api/projects/{slug}/runs/{run}/model?view=graph` returns the raw file.
- `GET /api/projects/{slug}/runs/{run}/model?kinds=role,page,entity` returns React Flow `nodes`/`edges`, laid out in
  columns by kind (long kinds wrap into several sub-columns).
