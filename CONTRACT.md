# Internal contract between engine (D), server (A) and site (C)

UNSAID.md wins over this file. The orchestrator owns this file. Agents propose changes in their report and don't edit it.

## Engine entry point (D owns `engine/unsaid/api.py`)

```python
run_unsaid(city: str, loves: list, *, walls_path=None, mode="fake"|"live",
           on_event=None, qloo=None, gemini=None) -> dict
resolve_love(text: str, hint: str|None, *, mode) -> {"status": "ok"|"needs_input"|"miss", "chip": {...}, "alternatives": [...]}
resolve_city(text: str, *, mode) -> {"status": "ok"|"needs_input", "city": {...}, "alternatives": [...]}
```

- `loves` items are either a resolved chip `{"id", "label", "kind", "type"}` or plain text. Plain text triggers `needs_input` when it's ambiguous.
- `on_event(evt: dict)` streams progress; the server forwards each event as one NDJSON line.
- Python 3.9 standard library only (the Mac runs 3.9.6).

## Result (`GET /api/unsaid?city=&loves=` → final NDJSON line `{"type":"done","result":…}`)

```json
{
  "status": "ok|empty_few|empty_none|needs_input|partial|waking|ranking|dated_only|degraded|queued|limited",
  "flags": ["flat", "thin_taste", "dead_love:<label>", "fake"],
  "loves": [{"id","label","kind","type","dead":false}],
  "city": {"id","name","slug","center":[lon,lat],"radius_mi"},
  "picks":    [CARD × ≤7],   // for-you order
  "reserves": [CARD × ≤3],
  "wall": [{"name","norm","provider","model","phrasing_id","phrasing","asked_at","lane":"dated|live",
            "outcome":"struck|dimmed","reason":"in pool|not in pool|closed (Qloo)|not found in Qloo","qloo_id":null}],
  "counts": {"wall":0,"asks":0,"P":0,"U":0,"S":0,"R_mi":0,"floor":{"closed":0,"below_43":0,"outside_R":0,"not_venue":0}},
  "burn": {"asked":[{"neighbourhood","lane","asked_at","named":[]}], "burned":[{"card_id","by","at"}]},
  "diag": {"qloo_calls":0,"rho_tp":null,"rho_res":null,"cap_keep":null,"cap_shared":null,"engine_v":"","as_of":"", "trace_url":null}
}
```

CARD:
```json
{"id":"<qloo entity id>","name","what":"soul food · live R&B","because":"<love label>",
 "fit_rank":4,"any_rank":151,"U":198,"rating":4.6,"open":true,"neighbourhood":"","address":"",
 "lat":0,"lon":0,"url":"","holds":3,"n_loves":3,"tied":false,
 "never_said":{"asks":0,"city_asks":0,"street_asks":0,"as_of":"2026-10-30T09:00-04:00"}}
```

## Stream events (one JSON object per line)

`{"type":"status","state":…,"text":…}` · `{"type":"wall_name",…wall item…}` · `{"type":"pool","U":n}` ·
`{"type":"strike","norm":…,"outcome":…}` · `{"type":"card",…CARD…}` · `{"type":"burn",…}` ·
`{"type":"calls","done":18,"total":27}` · `{"type":"done","result":{…}}`

## Fake mode

Every response built from fake data carries `"fake"` in `flags`, and the UI shows a visible MOCK tag while it is there. Mock data is never shown unmarked.
