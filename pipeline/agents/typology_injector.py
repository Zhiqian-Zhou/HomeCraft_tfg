"""Stage 1f-bis — translate `gi.selected_typologies` into concrete shape ops.

After `connector_planner_v4` produces the connector_plan (doors + windows +
staircases), this stage layers `kind="typology"` ops on top of the
architecture plan for whichever kinds the chooser selected.

The composer's "later wins" semantic means typology cells override the
deterministic envelope cells they overlap with, while non-overlapping cells
(walls, doors, frames) from the deterministic layer are preserved.

Kinds handled
-------------
* **roof** — bbox = union of envelope_role="roof" ops in architecture_plan.
  The typology re-renders the roof at the same bounds.
* **tower** — only when `gi.silhouette_id` looks tower-like (contains
  "tower" or "keep" or "spire"). Op spans `gi.building_aabb`; the typology
  redraws the entire envelope. Silhouettes that aren't tower-shaped (e.g.
  a longhouse) skip tower injection even if the chooser picked one.
* **window** — picks the first `connector_plan.windows` slot and emits a
  small typology op at that slot's AABB. Subsequent slots keep the
  deterministic windows so the building isn't over-decorated.
* **garden** — bbox = `gi.site_aabb` minus the vertical span (gardens are
  ground-level only). Emits a single garden typology op at y=0 spanning
  the whole site.

Failure handling
----------------
* Missing selected_typologies → no-op.
* Selected typology references an unknown name → silent skip (voxelizer
  would have raised, but we want graceful degradation).
* Missing inputs (no architecture_plan roof / no building_aabb / no
  connector_plan window slot) → that kind is dropped, others continue.
"""
from __future__ import annotations

from typing import Callable, Optional


_TOWER_HINTS = ("tower", "keep", "spire", "minaret", "campanile", "pagoda")


def _is_tower_silhouette(silhouette_id: str | None) -> bool:
    """Cheap heuristic: silhouette ids containing 'tower'/'keep'/etc. are
    tower-shaped enough to swap the entire envelope for a tower typology."""
    if not silhouette_id:
        return False
    s = silhouette_id.lower()
    return any(h in s for h in _TOWER_HINTS)


def _roof_bbox_from_ops(ops: list[dict]) -> tuple[int, int, int, int, int, int] | None:
    """Bounding box union of all ops whose `envelope_role == "roof"`."""
    xs0, ys0, zs0, xs1, ys1, zs1 = [], [], [], [], [], []
    for op in ops:
        if op.get("envelope_role") != "roof":
            continue
        bb = op.get("aabb")
        if bb is not None and len(bb) == 6:
            xs0.append(bb[0]); ys0.append(bb[1]); zs0.append(bb[2])
            xs1.append(bb[3]); ys1.append(bb[4]); zs1.append(bb[5])
            continue
        at = op.get("at")
        if at is not None and len(at) == 3:
            xs0.append(at[0]); ys0.append(at[1]); zs0.append(at[2])
            xs1.append(at[0] + 1); ys1.append(at[1] + 1); zs1.append(at[2] + 1)
    if not xs0:
        return None
    return (min(xs0), min(ys0), min(zs0),
            max(xs1), max(ys1), max(zs1))


def _pick_window_slot_aabb(connector_plan: dict) -> list[int] | None:
    """Pick the first validated window slot's AABB from connector_plan.

    The window typology lives at that slot's coordinates. Subsequent
    windows in connector_plan remain deterministic so we don't over-decorate.
    """
    windows = (connector_plan or {}).get("windows") or []
    for w in windows:
        validated = w.get("validated") or {}
        aabb = validated.get("aabb")
        if aabb and len(aabb) == 6:
            return list(aabb)
    return None


def _garden_aabb_from_site(site_aabb: list[int]) -> list[int] | None:
    """Garden lives at ground level over the full site footprint.

    Y is clamped to [site_y0, site_y0+2] — gardens are a thin slab
    (grass + 1 row for flowers/fence). Returns None if site is malformed.
    """
    if not site_aabb or len(site_aabb) != 6:
        return None
    x0, y0, z0, x1, _y1, z1 = site_aabb
    return [int(x0), int(y0), int(z0),
            int(x1), int(y0) + 2, int(z1)]


def inject(*, global_intent: dict,
           architecture_plan: dict,
           connector_plan: Optional[dict] = None,
           log: Optional[Callable[..., None]] = None) -> dict:
    """Return a copy of `architecture_plan` with typology ops appended.

    The original `architecture_plan` is shallow-copied; only `ops` is
    extended. Other top-level fields are preserved.
    """
    if log is None:
        log = lambda *_a, **_kw: None  # noqa: E731

    selected = (global_intent.get("selected_typologies") or {})
    if not selected:
        log("[typology_injector] no selected_typologies on gi — nothing to inject")
        return architecture_plan

    style = global_intent.get("style", "medieval")
    silhouette = global_intent.get("silhouette_id")
    ops_in = architecture_plan.get("ops", [])
    new_ops = list(ops_in)
    appended: dict[str, str] = {}

    # ── ROOF ───────────────────────────────────────────────────────────────
    roof_name = selected.get("roof")
    if roof_name:
        bb = _roof_bbox_from_ops(ops_in)
        if bb is None:
            log(f"[typology_injector] no roof envelope found, skipping roof "
                f"typology '{roof_name}'")
        else:
            new_ops.append({
                "kind": "typology",
                "name": roof_name,
                "aabb": list(bb),
                "style": style,
                "envelope_role": "roof",
                "room_id": None,
            })
            appended["roof"] = roof_name

    # ── TOWER ──────────────────────────────────────────────────────────────
    # Only meaningful when the silhouette is tower-shaped; otherwise the
    # tower op would draw walls on top of a longhouse (visual mess).
    tower_name = selected.get("tower")
    if tower_name:
        if not _is_tower_silhouette(silhouette):
            log(f"[typology_injector] silhouette {silhouette!r} is not "
                f"tower-shaped — skipping tower '{tower_name}'")
        else:
            building_aabb = global_intent.get("building_aabb")
            if not building_aabb or len(building_aabb) != 6:
                log(f"[typology_injector] no building_aabb on gi — skipping "
                    f"tower '{tower_name}'")
            else:
                new_ops.append({
                    "kind": "typology",
                    "name": tower_name,
                    "aabb": list(building_aabb),
                    "style": style,
                    "envelope_role": "tower",
                    "room_id": None,
                })
                appended["tower"] = tower_name

    # ── WINDOW ─────────────────────────────────────────────────────────────
    window_name = selected.get("window")
    if window_name:
        slot_aabb = _pick_window_slot_aabb(connector_plan or {})
        if slot_aabb is None:
            log(f"[typology_injector] no window slot in connector_plan — "
                f"skipping window '{window_name}'")
        else:
            new_ops.append({
                "kind": "typology",
                "name": window_name,
                "aabb": slot_aabb,
                "style": style,
                "envelope_role": "window",
                "room_id": None,
            })
            appended["window"] = window_name

    # ── GARDEN ─────────────────────────────────────────────────────────────
    garden_name = selected.get("garden")
    if garden_name:
        site_aabb = global_intent.get("site_aabb")
        garden_aabb = _garden_aabb_from_site(site_aabb) if site_aabb else None
        if garden_aabb is None:
            log(f"[typology_injector] no site_aabb on gi — skipping garden "
                f"'{garden_name}'")
        else:
            new_ops.append({
                "kind": "typology",
                "name": garden_name,
                "aabb": garden_aabb,
                "style": style,
                "envelope_role": "garden",
                "room_id": None,
            })
            appended["garden"] = garden_name

    log(f"[typology_injector] appended {len(new_ops) - len(ops_in)} typology "
        f"ops: {appended}")
    out = dict(architecture_plan)
    out["ops"] = new_ops
    return out


__all__ = ["inject"]
