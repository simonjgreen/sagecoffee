"""CLI application for Sage Coffee library."""

import asyncio
import json
import logging
from typing import Annotated

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from sagecoffee.auth import SyncAuthClient
from sagecoffee.client import SageCoffeeClient
from sagecoffee.logging import redact, setup_logging
from sagecoffee.store import ConfigStore

app = typer.Typer(
    name="sagectl",
    help="Control Breville/Sage coffee machines from the command line.",
    no_args_is_help=True,
)


def setup_debug_logging(
    debug: bool = False,
    debug_http: bool = False,
    debug_ws: bool = False,
) -> None:
    """Set up logging based on debug flags."""
    if debug or debug_http or debug_ws:
        # Enable DEBUG level when any debug flag is set
        setup_logging(level=logging.DEBUG, debug_http=debug_http, debug_ws=debug_ws)


raw_app = typer.Typer(help="Send raw commands")
app.add_typer(raw_app, name="raw")

console = Console()

# Exit codes
EXIT_SUCCESS = 0
EXIT_AUTH_FAILURE = 1
EXIT_CONFIG_MISSING = 2
EXIT_NETWORK_FAILURE = 3
EXIT_TIMEOUT = 4


def get_store() -> ConfigStore:
    """Get the config store."""
    return ConfigStore()


def require_config(store: ConfigStore) -> None:
    """Require that the config is set up."""
    if not store.is_configured():
        rprint("[red]Error:[/red] Not configured. Run 'sagectl bootstrap' first.")
        raise typer.Exit(EXIT_CONFIG_MISSING)


def get_client_id(store: ConfigStore, client_id: str | None) -> str:
    """Get client ID from CLI arg, env, or config (has default)."""
    if client_id:
        return client_id
    return store.client_id


@app.command()
def bootstrap(
    username: Annotated[
        str,
        typer.Option(
            "--username",
            "-u",
            help="Your Breville account email",
            prompt=True,
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            "--password",
            "-p",
            help="Your Breville account password",
            prompt=True,
            hide_input=True,
        ),
    ],
    client_id: Annotated[
        str | None,
        typer.Option(
            "--client-id",
            help="OAuth client ID (has default, rarely needed)",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging"),
    ] = False,
) -> None:
    """
    Bootstrap authentication with username/password.

    This stores the refresh_token for future use. You only need to run this once.
    """
    if debug:
        setup_logging(level=10)

    store = get_store()
    cid = get_client_id(store, client_id)

    try:
        auth = SyncAuthClient(cid)
        tokens = auth.password_realm_login(username, password)

        # Save to config
        store.client_id = cid
        if tokens.refresh_token:
            store.refresh_token = tokens.refresh_token

        rprint("[green]Success![/green] Authentication complete.")
        rprint(f"  Token type: {tokens.token_type}")
        rprint(f"  Expires in: {tokens.expires_in} seconds")
        rprint(f"  Has id_token: {bool(tokens.id_token)}")
        rprint(f"  Has refresh_token: {bool(tokens.refresh_token)}")
        rprint(f"  Config saved to: {store.config_path}")

    except Exception as e:
        rprint(f"[red]Error:[/red] Authentication failed: {e}")
        raise typer.Exit(EXIT_AUTH_FAILURE)


@app.command()
def refresh(
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging"),
    ] = False,
) -> None:
    """
    Refresh tokens using the stored refresh_token.

    Prints token status after refresh.
    """
    if debug:
        setup_logging(level=10)

    store = get_store()
    require_config(store)

    try:
        auth = SyncAuthClient(store.client_id)  # type: ignore
        tokens = auth.refresh(store.refresh_token)  # type: ignore

        # Update stored refresh token if rotated
        if tokens.refresh_token and tokens.refresh_token != store.refresh_token:
            store.refresh_token = tokens.refresh_token
            rprint("[yellow]Note:[/yellow] Refresh token was rotated and saved.")

        rprint("[green]Success![/green] Tokens refreshed.")
        rprint(f"  Token type: {tokens.token_type}")
        rprint(f"  Expires in: {tokens.expires_in} seconds")
        rprint(f"  Has id_token: {bool(tokens.id_token)}")
        rprint(f"  id_token (redacted): {redact(tokens.id_token) if tokens.id_token else 'None'}")

    except Exception as e:
        rprint(f"[red]Error:[/red] Refresh failed: {e}")
        raise typer.Exit(EXIT_AUTH_FAILURE)


@app.command()
def appliances(
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging"),
    ] = False,
) -> None:
    """
    List all appliances for the current user.
    """
    if debug:
        setup_logging(level=10)

    store = get_store()
    require_config(store)

    async def _run() -> None:
        async with SageCoffeeClient.from_config(store) as client:
            appliance_list = await client.list_appliances()

            if not appliance_list:
                rprint("[yellow]No appliances found.[/yellow]")
                return

            table = Table(title="Appliances")
            table.add_column("Name", style="cyan")
            table.add_column("Model", style="green")
            table.add_column("Serial Number")
            table.add_column("Pairing Type")

            for a in appliance_list:
                table.add_row(
                    a.name or "(unnamed)",
                    a.model,
                    a.serial_number,
                    a.pairing_type or "-",
                )

            console.print(table)

    try:
        asyncio.run(_run())
    except Exception as e:
        rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(EXIT_NETWORK_FAILURE)


@app.command()
def tail(
    serial: Annotated[
        str | None,
        typer.Option("--serial", "-s", help="Appliance serial number"),
    ] = None,
    jsonl: Annotated[
        bool,
        typer.Option("--jsonl", help="Output as JSON lines"),
    ] = False,
    once: Annotated[
        bool,
        typer.Option("--once", help="Exit after first state report"),
    ] = False,
    fields: Annotated[
        str | None,
        typer.Option("--fields", "-f", help="Comma-separated fields to show"),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging"),
    ] = False,
    debug_http: Annotated[
        bool,
        typer.Option("--debug-http", help="Enable HTTP debug logging (redacted)"),
    ] = False,
    debug_ws: Annotated[
        bool,
        typer.Option("--debug-ws", help="Enable WebSocket debug logging (redacted)"),
    ] = False,
) -> None:
    """
    Stream state updates from appliances.

    Connects to the WebSocket and prints state updates as they arrive.
    """
    setup_debug_logging(debug, debug_http, debug_ws)

    store = get_store()
    require_config(store)

    field_list = fields.split(",") if fields else None

    async def _run() -> None:
        async with SageCoffeeClient.from_config(store) as client:
            rprint("[cyan]Connecting to state stream...[/cyan]")

            async for state in client.tail_state(serial=serial):
                if jsonl:
                    # Output as JSON line
                    output = {
                        "serial": state.serial_number,
                        "state": state.reported_state,
                        "data": state.raw_data,
                    }
                    if field_list:
                        # Filter to requested fields
                        filtered = {"serial": state.serial_number}
                        for field in field_list:
                            parts = field.split(".")
                            value = state.reported
                            for part in parts:
                                if isinstance(value, dict):
                                    value = value.get(part)
                                else:
                                    value = None
                                    break
                            filtered[field] = value
                        output = filtered
                    print(json.dumps(output), flush=True)
                else:
                    # Pretty print
                    rprint(f"\n[cyan]State update:[/cyan] {state.serial_number}")
                    rprint(f"  State: [green]{state.reported_state}[/green]")

                    if field_list:
                        for field in field_list:
                            parts = field.split(".")
                            value = state.reported
                            for part in parts:
                                if isinstance(value, dict):
                                    value = value.get(part)
                                else:
                                    value = None
                                    break
                            rprint(f"  {field}: {value}")
                    else:
                        # Show some common fields
                        boilers = state.boiler_temps
                        if boilers:
                            for b in boilers:
                                cur, tgt = b.current_temp, b.target_temp
                                rprint(f"  Boiler {b.id}: {cur}°C (target: {tgt}°C)")

                        grind = state.grind_size
                        if grind is not None:
                            rprint(f"  Grind size: {grind}")

                if once:
                    break

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        rprint("\n[yellow]Interrupted[/yellow]")
    except Exception as e:
        rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(EXIT_NETWORK_FAILURE)


@app.command()
def wake(
    serial: Annotated[
        str | None,
        typer.Option("--serial", "-s", help="Appliance serial number"),
    ] = None,
    wait: Annotated[
        bool,
        typer.Option("--wait", "-w", help="Wait for ready state"),
    ] = False,
    timeout: Annotated[
        int,
        typer.Option("--timeout", "-t", help="Timeout in seconds for --wait"),
    ] = 300,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging"),
    ] = False,
) -> None:
    """
    Wake up an appliance.

    Sends the wake command to transition from asleep to ready.
    """
    if debug:
        setup_logging(level=10)

    store = get_store()
    require_config(store)

    async def _run() -> None:
        async with SageCoffeeClient.from_config(store) as client:
            # Send wake command
            rprint("[cyan]Sending wake command...[/cyan]")
            await client.wake(serial)
            rprint("[green]Wake command sent.[/green]")

            if wait:
                rprint(f"[cyan]Waiting for ready state (timeout: {timeout}s)...[/cyan]")

                ws = await client.connect_state_stream(serial)
                start_time = asyncio.get_event_loop().time()

                async for state in ws.listen_states():
                    if state.reported_state == "ready":
                        rprint("[green]Appliance is ready![/green]")
                        return

                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed > timeout:
                        s = state.reported_state
                        rprint(f"[red]Timeout:[/red] Still in state '{s}' after {timeout}s")
                        raise typer.Exit(EXIT_TIMEOUT)

                    rprint(f"  Current state: {state.reported_state}")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        rprint("\n[yellow]Interrupted[/yellow]")
    except typer.Exit:
        raise
    except Exception as e:
        rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(EXIT_NETWORK_FAILURE)


@app.command("sleep")
def sleep_cmd(
    serial: Annotated[
        str | None,
        typer.Option("--serial", "-s", help="Appliance serial number"),
    ] = None,
    wait: Annotated[
        bool,
        typer.Option("--wait", "-w", help="Wait for asleep state"),
    ] = False,
    timeout: Annotated[
        int,
        typer.Option("--timeout", "-t", help="Timeout in seconds for --wait"),
    ] = 60,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging"),
    ] = False,
) -> None:
    """
    Put an appliance to sleep.

    Sends the sleep command to transition to asleep state.
    """
    if debug:
        setup_logging(level=10)

    store = get_store()
    require_config(store)

    async def _run() -> None:
        async with SageCoffeeClient.from_config(store) as client:
            # Send sleep command
            rprint("[cyan]Sending sleep command...[/cyan]")
            await client.sleep(serial)
            rprint("[green]Sleep command sent.[/green]")

            if wait:
                rprint(f"[cyan]Waiting for asleep state (timeout: {timeout}s)...[/cyan]")

                ws = await client.connect_state_stream(serial)
                start_time = asyncio.get_event_loop().time()

                async for state in ws.listen_states():
                    if state.reported_state == "asleep":
                        rprint("[green]Appliance is asleep.[/green]")
                        return

                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed > timeout:
                        s = state.reported_state
                        rprint(f"[red]Timeout:[/red] Still in state '{s}' after {timeout}s")
                        raise typer.Exit(EXIT_TIMEOUT)

                    rprint(f"  Current state: {state.reported_state}")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        rprint("\n[yellow]Interrupted[/yellow]")
    except typer.Exit:
        raise
    except Exception as e:
        rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(EXIT_NETWORK_FAILURE)


@app.command()
def config(
    show: Annotated[
        bool,
        typer.Option("--show", help="Show current configuration"),
    ] = True,
) -> None:
    """
    Show or manage configuration.
    """
    store = get_store()

    if show:
        config_data = store.get_all()

        table = Table(title="Configuration")
        table.add_column("Key", style="cyan")
        table.add_column("Value")

        for key, value in config_data.items():
            table.add_row(key, str(value))

        console.print(table)


@raw_app.command("ws")
def raw_ws(
    message: Annotated[
        str,
        typer.Argument(help="JSON message to send"),
    ],
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging"),
    ] = False,
) -> None:
    """
    Send a raw WebSocket message.

    Example: sagectl raw ws '{"action":"ping"}'
    """
    if debug:
        setup_logging(level=10)

    store = get_store()
    require_config(store)

    try:
        msg = json.loads(message)
    except json.JSONDecodeError as e:
        rprint(f"[red]Error:[/red] Invalid JSON: {e}")
        raise typer.Exit(1)

    async def _run() -> None:
        async with SageCoffeeClient.from_config(store) as client:
            ws = await client.connect_state_stream()

            rprint(f"[cyan]Sending:[/cyan] {message}")
            await ws.send_raw(msg)

            # Wait for one response
            async for response in ws.listen():
                rprint("[green]Response:[/green]")
                print(json.dumps(response, indent=2))
                break

    try:
        asyncio.run(_run())
    except Exception as e:
        rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(EXIT_NETWORK_FAILURE)


@raw_app.command("http")
def raw_http(
    method: Annotated[
        str,
        typer.Argument(help="HTTP method (GET, POST, etc.)"),
    ],
    path: Annotated[
        str,
        typer.Argument(help="API path"),
    ],
    body: Annotated[
        str | None,
        typer.Argument(help="JSON body (for POST/PUT)"),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging"),
    ] = False,
) -> None:
    """
    Send a raw HTTP request.

    Example: sagectl raw http POST /appliance/v1/appliances/ABC/set-coffeeParams '{}'
    """
    if debug:
        setup_logging(level=10)

    store = get_store()
    require_config(store)

    json_body = None
    if body:
        try:
            json_body = json.loads(body)
        except json.JSONDecodeError as e:
            rprint(f"[red]Error:[/red] Invalid JSON body: {e}")
            raise typer.Exit(1)

    async def _run() -> None:
        async with SageCoffeeClient.from_config(store) as client:
            api = client._get_api_client()

            rprint(f"[cyan]{method} {path}[/cyan]")
            if json_body:
                rprint(f"[cyan]Body:[/cyan] {body}")

            response = await api.request(method, path, json=json_body)

            rprint("[green]Response:[/green]")
            print(json.dumps(response, indent=2))

    try:
        asyncio.run(_run())
    except Exception as e:
        rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(EXIT_NETWORK_FAILURE)


if __name__ == "__main__":
    app()
