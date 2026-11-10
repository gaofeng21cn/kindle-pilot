"""Additive native collection changes, preserving both sides of membership.

The native service owns writes. A caller must bind the device and firmware,
back up the databases, journal the payload before submitting once, and compare
later read-only exports. This module never opens a device database writable.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import CompanionError


CATALOG_SQL = """SELECT json_object(
 'schema','kindle-pilot-native-catalog/v1',
 'collections',json((SELECT json_group_array(json_object(
  'uuid',p_uuid,'name',p_titles_0_nominal,'visible',p_isVisibleInHome,
  'archived',p_isArchived,'members',json(j_members),
  'member_count',p_memberCount,'home_member_count',p_homeMemberCount,
  'sync_counter',p_collectionSyncCounter)) FROM Entries WHERE p_type='Collection')),
 'books',json((SELECT json_group_array(json_object(
  'uuid',p_uuid,'title',p_titles_0_nominal,'location',p_location,
  'cde_key',p_cdeKey,'cde_type',p_cdeType,'collection_count',p_collectionCount,
  'collections',json(j_collections),'archived',p_isArchived,
  'visible',p_isVisibleInHome,'content_state',p_contentState))
  FROM Entries WHERE p_type='Entry:Item')),
 'relations',json((SELECT json_group_array(json_object(
  'collection_uuid',i_collection_uuid,'book_uuid',i_member_uuid,
  'member_type',i_member_cde_type,'member_key',i_member_cde_key,
  'present',i_member_is_present,'sideloaded',i_is_sideloaded,'order',i_order))
  FROM Collections)));
"""


def _index(catalog: dict[str, Any]) -> tuple[dict, dict, dict, dict]:
    books = {b["uuid"]: b for b in catalog["books"]}
    shelves = {c["uuid"]: c for c in catalog["collections"]}
    if len(books) != len(catalog["books"]) or len(shelves) != len(catalog["collections"]):
        raise CompanionError("COLLECTION_IDENTITY", "duplicate native object identity")
    members: dict[str, set[str]] = defaultdict(set)
    memberships: dict[str, set[str]] = defaultdict(set)
    for row in catalog["relations"]:
        cid, uid = row["collection_uuid"], row["book_uuid"]
        if cid not in shelves or uid not in books or uid in members[cid]:
            raise CompanionError("COLLECTION_RELATION", "unknown or duplicate native membership")
        members[cid].add(uid)
        memberships[uid].add(cid)
    return books, shelves, members, memberships


def prepare_addition(catalog: dict[str, Any], target: dict[str, Any], timestamp: int) -> dict[str, Any]:
    """Prepare one collection; retain every existing membership and source path."""
    books, shelves, members, memberships = _index(catalog)
    cid, name = target["uuid"], target["name"]
    selected = set(target["book_uuids"])
    if (not selected or len(selected) != len(target["book_uuids"])
            or not isinstance(name, str) or not name.strip()
            or any(ord(c) < 32 for c in name)):
        raise CompanionError("COLLECTION_TARGET", "invalid collection target")
    shelf = shelves.get(cid)
    if ((shelf and shelf["name"] != name) or cid in books
            or any(c["uuid"] != cid and c["name"].casefold() == name.casefold() for c in shelves.values())):
        raise CompanionError("COLLECTION_NAME", "collection identity or name changed")
    for uid in selected:
        book = books.get(uid)
        if not book or book["archived"] != 0 or not book["location"]:
            raise CompanionError("COLLECTION_LOCAL_BOOK", "target must be an indexed downloaded book")
    added = selected - members[cid]
    all_members = members[cid] | selected
    if len(all_members) > 350:
        raise CompanionError("COLLECTION_LIMIT", "collection exceeds 350-member batch limit")
    commands = []
    if not shelf:
        commands.append({"insert": {
            "type": "Collection", "uuid": cid, "lastAccess": timestamp,
            "titles": [{"display": name, "direction": "LTR", "language": "zh_CN"}],
            "isVisibleInHome": 1, "isArchived": 1,
            "mimeType": "application/x-kindle-collection",
            "collectionCount": None, "collectionDataSetName": cid,
        }})
    # Set both item.collections and collection.members in a single transaction.
    # The final members command lets the service calculate visible counts.
    for uid in sorted(added):
        stored = books[uid]["collections"] or []
        if not isinstance(stored, list) or any(c not in shelves for c in stored):
            raise CompanionError("COLLECTION_ITEM_STATE", "item has unknown collection metadata")
        prior = memberships[uid] | set(stored)
        if prior != memberships[uid]:
            raise CompanionError("COLLECTION_ITEM_STATE", "item metadata and relation identities differ")
        commands.append({"update": {"type": "Entry:Item", "uuid": uid,
                                    "collections": sorted(prior | {cid})}})
    if added:
        commands.append({"update": {"type": "Collection", "uuid": cid,
                                    "members": sorted(all_members)}})
    return {
        "target": {"uuid": cid, "name": name, "book_uuids": sorted(selected)},
        "added_book_uuids": sorted(added), "created": shelf is None,
        "payload": {"commands": commands, "type": "ChangeRequest", "id": 1, "caller": "KindlePilot"},
    }


def verify_addition(before: dict[str, Any], after: dict[str, Any], prepared: dict[str, Any]) -> dict[str, Any]:
    old_books, old_shelves, old_members, old_memberships = _index(before)
    books, shelves, members, memberships = _index(after)
    target = prepared["target"]
    cid = target["uuid"]
    expected_members = old_members[cid] | set(target["book_uuids"])
    added = set(prepared["added_book_uuids"])
    checks = {
        "target_name": cid in shelves and shelves[cid]["name"] == target["name"],
        "target_members": members[cid] == expected_members,
        "original_collection_names": all(c in shelves and shelves[c]["name"] == v["name"] for c, v in old_shelves.items()),
        "other_memberships_unchanged": all(members[c] == m for c, m in old_members.items() if c != cid),
        "target_preserved_old_members": old_members[cid].issubset(members[cid]),
        "book_paths_unchanged": all(u in books and books[u]["location"] == old_books[u]["location"] for u in expected_members),
        "item_memberships": all(memberships[u] == old_memberships[u] | {cid} for u in added),
        "item_metadata": all(set(books[u]["collections"] or []) == memberships[u] for u in added if u in books),
    }
    # Native count means visible collections on this firmware, not all links.
    checks["visible_counts"] = all(
        books[u]["collection_count"] == sum(shelves[c]["visible"] == 1 for c in memberships[u])
        for u in expected_members if u in books
    )
    checks["collection_counts"] = (cid in shelves and shelves[cid]["member_count"] == len(expected_members)
                                   and shelves[cid]["home_member_count"] == sum(
                                       r["present"] == 1 for r in after["relations"] if r["collection_uuid"] == cid))
    return {"collection_uuid": cid, "name": target["name"], "members": len(expected_members),
            "checks": checks, "verified": all(checks.values())}


def prepare_rename(catalog: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """Prepare an exact compare-and-swap collection rename.

    The caller must provide the UUID and the name observed in the same catalog
    export. Renaming changes only the collection title; members, visibility,
    books and source paths remain outside the write set.
    """
    _, shelves, _, _ = _index(catalog)
    cid = target.get("uuid")
    current_name = target.get("current_name")
    name = target.get("name")
    if (not isinstance(cid, str) or not cid or not isinstance(current_name, str)
            or not isinstance(name, str) or not current_name.strip() or not name.strip()
            or current_name == name or any(ord(c) < 32 for c in name)):
        raise CompanionError("COLLECTION_RENAME_TARGET", "rename requires an observed current name and a different valid name")
    shelf = shelves.get(cid)
    if not shelf or shelf["name"] != current_name:
        raise CompanionError("COLLECTION_RENAME_IDENTITY", "collection UUID or current name changed")
    if any(c["uuid"] != cid and c["name"].casefold() == name.casefold() for c in shelves.values()):
        raise CompanionError("COLLECTION_NAME", "another collection already uses the requested name")
    payload = {
        "commands": [{"update": {
            "type": "Collection",
            "uuid": cid,
            "titles": [{"display": name, "direction": "LTR", "language": target.get("language", "zh_CN")}],
        }}],
        "type": "ChangeRequest",
        "id": 1,
        "caller": "KindlePilot",
    }
    return {"target": {"uuid": cid, "current_name": current_name, "name": name}, "payload": payload}


def verify_rename(before: dict[str, Any], after: dict[str, Any], prepared: dict[str, Any]) -> dict[str, Any]:
    old_books, old_shelves, old_members, old_memberships = _index(before)
    books, shelves, members, memberships = _index(after)
    target = prepared["target"]
    cid = target["uuid"]
    old_pairs = {(r["collection_uuid"], r["book_uuid"]) for r in before["relations"]}
    new_pairs = {(r["collection_uuid"], r["book_uuid"]) for r in after["relations"]}
    checks = {
        "target_name": cid in shelves and shelves[cid]["name"] == target["name"],
        "other_collection_names": all(c in shelves and (c == cid or shelves[c]["name"] == value["name"])
                                       for c, value in old_shelves.items()),
        "visibility_unchanged": all(c in shelves and shelves[c]["visible"] == value["visible"]
                                     for c, value in old_shelves.items()),
        "memberships_unchanged": new_pairs == old_pairs,
        "collection_members_unchanged": all(c in members and members[c] == old_members[c] for c in old_members),
        "book_metadata_unchanged": all(u in books and set(books[u]["collections"] or []) == old_memberships[u]
                                        for u in old_books),
        "book_paths_unchanged": all(u in books and books[u]["location"] == value["location"]
                                     for u, value in old_books.items()),
    }
    return {"collection_uuid": cid, "name": target["name"], "checks": checks, "verified": all(checks.values())}


def verify_organization(before: dict[str, Any], after: dict[str, Any], targets: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare the whole authorized graph after several independent additions."""
    old_books, old_shelves, old_members, _ = _index(before)
    books, shelves, members, _ = _index(after)
    old_pairs = {(r["collection_uuid"], r["book_uuid"]) for r in before["relations"]}
    actual = {(r["collection_uuid"], r["book_uuid"]) for r in after["relations"]}
    additions = {(t["uuid"], u) for t in targets for u in t["book_uuids"]}
    selected = {u for _, u in additions}
    checks = {
        "original_memberships_preserved": old_pairs.issubset(actual),
        "exact_authorized_graph": actual == old_pairs | additions,
        "original_collection_names": all(c in shelves and shelves[c]["name"] == v["name"] for c, v in old_shelves.items()),
        "original_collection_visibility": all(c in shelves and shelves[c]["visible"] == v["visible"] for c, v in old_shelves.items()),
        "target_names": all(t["uuid"] in shelves and shelves[t["uuid"]]["name"] == t["name"] for t in targets),
        "target_members": all(members[t["uuid"]] == old_members[t["uuid"]] | set(t["book_uuids"]) for t in targets),
        "source_paths_preserved": all(u in books and books[u]["location"] == old_books[u]["location"] for u in selected),
        "idempotent": all(not prepare_addition(after, t, 0)["payload"]["commands"] for t in targets),
    }
    return {"collections": len(shelves), "relations": len(actual), "covered_books": len(selected),
            "checks": checks, "verified": all(checks.values())}


def prepare_retirement(catalog: dict[str, Any], target: dict[str, Any],
                       original_collection_ids: set[str], destinations: dict[str, set[str]]) -> dict[str, Any]:
    """Retire one explicitly owned collection after every member is placed.

    The target must come from the saved creation receipt, including the exact
    UUID, name and member UUIDs. Original collections are never eligible.
    """
    books, shelves, members, memberships = _index(catalog)
    cid = target["uuid"]
    shelf = shelves.get(cid)
    if cid in original_collection_ids or not shelf or shelf["name"] != target["name"]:
        raise CompanionError("COLLECTION_RETIRE_IDENTITY", "only an exact task-created collection can be retired")
    selected = members[cid]
    if selected != set(target["member_uuids"]):
        raise CompanionError("COLLECTION_RETIRE_CHANGED", "collection members changed since consolidation preview")
    commands = [{"update": {"type": "Collection", "uuid": cid, "members": []}}]
    for uid in sorted(selected):
        keep = memberships[uid] - {cid}
        wanted = destinations.get(uid, set()) - {cid}
        if not wanted or not wanted.issubset(keep):
            raise CompanionError("COLLECTION_RETIRE_DESTINATION", "member has not reached its approved destination")
        if books[uid]["archived"] != 0 or not books[uid]["location"]:
            raise CompanionError("COLLECTION_RETIRE_BOOK", "retirement is limited to the task's downloaded books")
        commands.append({"update": {"type": "Entry:Item", "uuid": uid, "collections": sorted(keep)}})
    # collections updates count all supplied links; the native library displays
    # only visible collections. Use a separate final update with that exact count.
    for uid in sorted(selected):
        count = sum(shelves[c]["visible"] == 1 for c in memberships[uid] - {cid})
        commands.append({"update": {"type": "Entry:Item", "uuid": uid, "collectionCount": count}})
    commands.append({"delete": {"uuid": cid}})
    return {"target": target, "payload": {"commands": commands, "type": "ChangeRequest", "id": 1, "caller": "KindlePilot"}}


def verify_retirement(before: dict[str, Any], after: dict[str, Any], prepared: dict[str, Any]) -> dict[str, Any]:
    old_books, old_shelves, _, _ = _index(before)
    books, shelves, _, memberships = _index(after)
    cid = prepared["target"]["uuid"]
    touched = set(prepared["target"]["member_uuids"])
    expected = {(r["collection_uuid"], r["book_uuid"]) for r in before["relations"] if r["collection_uuid"] != cid}
    actual = {(r["collection_uuid"], r["book_uuid"]) for r in after["relations"]}
    checks = {
        "collection_absent": cid not in shelves,
        "other_collections_preserved": all(c in shelves and shelves[c]["name"] == v["name"] for c, v in old_shelves.items() if c != cid),
        "other_memberships_preserved": actual == expected,
        "books_and_paths_preserved": all(u in books and books[u]["location"] == old_books[u]["location"] for u in touched),
        "item_metadata": all(set(books[u]["collections"] or []) == memberships[u] for u in touched if u in books),
        "visible_counts": all(books[u]["collection_count"] == sum(shelves[c]["visible"] == 1 for c in memberships[u]) for u in touched if u in books),
    }
    return {"collection_uuid": cid, "checks": checks, "verified": all(checks.values())}
