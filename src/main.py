#!/usr/bin/env python3
"""Entry point for the Firecrawl account creator."""

import asyncio
import sys
from dataclasses import dataclass

from rich.console import Console

from src.config import DEFAULT_CONCURRENCY, DEFAULT_COUNT, DEFAULT_DELAY, PROXY_URL, validate_config
from src.email_provider import create_email
from src.log import Log
from src.session import default_manager as session

console = Console()


@dataclass
class CLIConfig:
    proxy: str | None = None
    count: int = DEFAULT_COUNT
    concurrency: int = DEFAULT_CONCURRENCY


def print_config(cfg: CLIConfig) -> None:
    console.print("[bold]Configuration:[/]")
    console.print(f"  Proxy: {'configured' if (cfg.proxy or PROXY_URL) else 'none (direct)'}")
    console.print(f"  Count: {cfg.count}")
    console.print(f"  Concurrency: {cfg.concurrency}")
    console.print(f"  Delay: {DEFAULT_DELAY}s")


async def register_one(
    index: int, total: int, sem: asyncio.Semaphore, delay: int, proxy: str | None
) -> str:
    from src.creator_rest import create_account_rest as create_account

    async with sem:
        log = Log(index, total)
        log.section("Registration")
        try:
            email, password = await create_email()
            log.info(f"Mail: {email}")
            result = await create_account(index, total, email, password, proxy=proxy, log=log)
            status = "success" if result else "failed"
        except Exception as exc:
            log.error(f"Error: {exc}")
            status = "failed"

    # Delay after releasing semaphore so next task can start
    if delay > 0:
        await asyncio.sleep(delay)
    return status


async def run(cfg: CLIConfig, delay: int) -> None:
    sem = asyncio.Semaphore(cfg.concurrency)
    tasks: list[asyncio.Task] = []

    for i in range(1, cfg.count + 1):
        task = asyncio.create_task(register_one(i, cfg.count, sem, delay, cfg.proxy))
        tasks.append(task)

    success = 0
    failed = 0
    try:
        for task in tasks:
            status = await task
            if status == "success":
                success += 1
            else:
                failed += 1
    except asyncio.CancelledError:
        # Graceful shutdown on Ctrl+C
        console.print("\n[yellow]Cancelling remaining tasks...[/]")
        for task in tasks:
            if not task.done():
                task.cancel()
        # Wait for all tasks to finish cancellation
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    console.print(f"\n[bold cyan]Done:[/] Success [green]{success}[/]  Failed [red]{failed}[/]")


async def main_async(args: list[str]) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Firecrawl Account Creator")
    parser.add_argument("count", nargs="?", type=int, default=None, help="Number of accounts")
    parser.add_argument("--concurrency", type=int, default=None, help="Max concurrent sessions")
    parser.add_argument(
        "--proxy", type=str, default=None, help="Proxy URL (socks5://user:pass@host:port)"
    )
    parsed = parser.parse_args(args)

    cfg = CLIConfig(
        proxy=parsed.proxy,
        count=parsed.count if parsed.count is not None else DEFAULT_COUNT,
        concurrency=min(
            parsed.concurrency if parsed.concurrency is not None else DEFAULT_CONCURRENCY,
            parsed.count if parsed.count is not None else DEFAULT_COUNT,
        ),
    )

    console.print("\n[bold cyan]Firecrawl Account Creator — REST mode[/]\n")
    print_config(cfg)

    if not validate_config():
        return

    # Configure shared session with the resolved proxy
    resolved_proxy = cfg.proxy if cfg.proxy is not None else (PROXY_URL or None)
    session.configure(resolved_proxy)

    console.print(f"\nCreating [bold]{cfg.count}[/] account(s), concurrency {cfg.concurrency}...")
    await run(cfg, DEFAULT_DELAY)


def main() -> None:
    try:
        asyncio.run(main_async(sys.argv[1:]))
    except KeyboardInterrupt:
        console.print("\n[bold red]Interrupted.[/]")
        sys.exit(1)


if __name__ == "__main__":
    main()
