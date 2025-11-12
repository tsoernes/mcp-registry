#!/usr/bin/env python3
"""
Test script for GitHub stars fetching across all registry sources.

Usage:
    python scripts/test_github_stars_all_sources.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_registry_server.scrapers import (
    scrape_docker_registry,
    scrape_mcp_official_registry,
    scrape_mcpservers_org,
)


async def test_mcp_official():
    """Test MCP Official Registry with GitHub stars."""
    print("\n" + "=" * 80)
    print("Testing MCP Official Registry")
    print("=" * 80)

    try:
        entries = await scrape_mcp_official_registry(limit=5, fetch_github_stars_flag=True)
        print(f"✓ Scraped {len(entries)} entries from MCP Official Registry")

        with_stars = [e for e in entries if e.raw_metadata.get("github_stars")]
        print(f"✓ {len(with_stars)}/{len(entries)} entries have GitHub stars")

        if with_stars:
            total_stars = sum(e.raw_metadata.get("github_stars", 0) for e in with_stars)
            print(f"✓ Total stars: {total_stars:,}")
            print(f"✓ Average stars: {total_stars // len(with_stars):,}")
            print("\nSample entries:")
            for entry in with_stars[:3]:
                stars = entry.raw_metadata.get("github_stars", 0)
                print(f"  - {entry.name}: {stars:,} stars")

        return True
    except Exception as e:
        print(f"✗ Error testing MCP Official: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_docker_registry():
    """Test Docker registry with GitHub stars."""
    print("\n" + "=" * 80)
    print("Testing Docker Registry")
    print("=" * 80)

    try:
        # Create temporary sources directory
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmpdir:
            sources_dir = Path(tmpdir)
            entries = await scrape_docker_registry(sources_dir, fetch_github_stars_flag=True)
            print(f"✓ Scraped {len(entries)} entries from Docker Registry")

            with_stars = [e for e in entries if e.raw_metadata.get("github_stars")]
            print(f"✓ {len(with_stars)}/{len(entries)} entries have GitHub stars")

            if with_stars:
                total_stars = sum(e.raw_metadata.get("github_stars", 0) for e in with_stars)
                print(f"✓ Total stars: {total_stars:,}")
                print(f"✓ Average stars: {total_stars // len(with_stars):,}")
                print("\nSample entries:")
                for entry in with_stars[:3]:
                    stars = entry.raw_metadata.get("github_stars", 0)
                    print(f"  - {entry.name}: {stars:,} stars")

        return True
    except Exception as e:
        print(f"✗ Error testing Docker Registry: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_mcpservers_org():
    """Test mcpservers.org with GitHub stars."""
    print("\n" + "=" * 80)
    print("Testing mcpservers.org")
    print("=" * 80)

    try:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmpdir:
            entries = await scrape_mcpservers_org(
                concurrency=5,
                limit=10,
                use_cache=False,
                cache_dir=tmpdir,
                fetch_github_stars_flag=True,
            )
            print(f"✓ Scraped {len(entries)} entries from mcpservers.org")

            with_stars = [e for e in entries if e.raw_metadata.get("github_stars")]
            print(f"✓ {len(with_stars)}/{len(entries)} entries have GitHub stars")

            if with_stars:
                total_stars = sum(e.raw_metadata.get("github_stars", 0) for e in with_stars)
                print(f"✓ Total stars: {total_stars:,}")
                print(f"✓ Average stars: {total_stars // len(with_stars):,}")
                print("\nSample entries:")
                for entry in with_stars[:3]:
                    stars = entry.raw_metadata.get("github_stars", 0)
                    print(f"  - {entry.name}: {stars:,} stars")

        return True
    except Exception as e:
        print(f"✗ Error testing mcpservers.org: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("=" * 80)
    print("Testing GitHub Stars Fetching Across All Sources")
    print("=" * 80)

    results = {}

    # Test each source
    results["MCP Official"] = await test_mcp_official()
    results["Docker Registry"] = await test_docker_registry()
    results["mcpservers.org"] = await test_mcpservers_org()

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    for source, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status:10} {source}")

    all_passed = all(results.values())
    print("\n" + "=" * 80)
    if all_passed:
        print("✓ All tests passed!")
        sys.exit(0)
    else:
        print("✗ Some tests failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
