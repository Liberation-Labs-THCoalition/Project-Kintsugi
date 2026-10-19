"""`kintsugi keys`: mint, list and revoke per-org API keys (step 3).

The first admin key can only come from here; no HTTP route mints a key without an admin principal, and none mints one
at all today. A new key is printed once and never stored: only its SHA-256 is kept in API_KEYS_FILE.
"""

from __future__ import annotations

import typer

from kintsugi.api.auth import Principal, audit
from kintsugi.cli import console, err_console, keys_app
from kintsugi.security.api_keys import ROLES, get_key_store


def _cli_principal(org_id: str) -> Principal:
    return Principal(org_id=org_id, key_id="cli", role="admin")


@keys_app.command("create")
def create(
    org: str = typer.Option(..., "--org", help="The organization the key belongs to"),
    role: str = typer.Option("member", "--role", help="member or admin"),
    label: str = typer.Option("", "--label", help="A note to tell keys apart"),
    person: str = typer.Option("", "--person", help="Who holds it; consent counts one person's keys once"),
) -> None:
    """Mint a key. It is shown once: store it now."""
    if role not in ROLES:
        err_console.print(f"role must be one of {', '.join(ROLES)}")
        raise typer.Exit(2)
    rec, plaintext = get_key_store().create(org, role, label, person=person)
    audit(_cli_principal(org), "keys.create", new_key_id=rec.id, new_role=role, label=label, person=person)
    console.print(f"key id {rec.id}  org {rec.org_id}  role {rec.role}")
    console.print("This key is shown once and cannot be recovered:")
    typer.echo(plaintext)


@keys_app.command("list")
def list_keys() -> None:
    """List keys (id, org, role, label, first characters). Never the key itself."""
    for rec in get_key_store().list():
        state = f"revoked {rec.revoked_at}" if rec.revoked_at else "live"
        typer.echo(f"{rec.id}  org={rec.org_id}  role={rec.role}  kin_{rec.prefix}...  {state}  {rec.label}"
                   + (f"  person={rec.person}" if rec.person else ""))


@keys_app.command("set-person")
def set_person(key_id: str = typer.Argument(..., help="The key id from `kintsugi keys list`"),
               person: str = typer.Argument(..., help="Who holds it")) -> None:
    """Record who holds a key, so consent counts all of one person's keys as one person."""
    store = get_key_store()
    rec = store.get(key_id)
    if rec is None or not store.set_person(key_id, person):
        err_console.print(f"no key with id {key_id}")
        raise typer.Exit(1)
    audit(_cli_principal(rec.org_id), "keys.set_person", key_id=key_id, person=person)
    console.print(f"{key_id} is held by {person}")


@keys_app.command("revoke")
def revoke(key_id: str = typer.Argument(..., help="The key id from `kintsugi keys list`")) -> None:
    """Revoke a key. It stops working at once."""
    store = get_key_store()
    rec = next((r for r in store.list() if r.id == key_id), None)
    if rec is None or not store.revoke(key_id):
        err_console.print(f"no live key with id {key_id}")
        raise typer.Exit(1)
    audit(_cli_principal(rec.org_id), "keys.revoke", revoked_key_id=key_id)
    console.print(f"revoked {key_id}")
