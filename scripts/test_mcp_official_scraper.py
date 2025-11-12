#!/usr/bin/env python3
"""
Test script for MCP Official Registry scraper.

Usage:
    python scripts/test_mcp_official_scraper.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_registry_server.scrapers.mcp_official_registry import scrape_mcp_official_registry


async def main():
    """Test the MCP Official Registry scraper."""
    print("Testing MCP Official Registry scraper...")
    print("=" * 80)

    try:
        # Scrape a small subset for testing
        print("\n1. Fetching first 10 servers from MCP Official Registry...")
        entries = await scrape_mcp_official_registry(limit=10, timeout=30.0)

        print(f"\n✓ Successfully scraped {len(entries)} entries\n")

        # Display details
        for i, entry in enumerate(entries, 1):
            print(f"\n--- Entry {i} ---")
            print(f"ID:           {entry.id}")
            print(f"Name:         {entry.name}")
            print(f"Description:  {entry.description[:100]}...")
            print(f"Source:       {entry.source}")
            print(f"Repo URL:     {entry.repo_url or 'N/A'}")
            print(f"Categories:   {', '.join(entry.categories) or 'None'}")
            print(f"Tags:         {', '.join(entry.tags[:5]) or 'None'}")
            print(f"Official:     {entry.official}")
            print(f"Featured:     {entry.featured}")
            print(f"API Key Req:  {entry.requires_api_key}")
            print(f"Launch:       {entry.launch_method}")
            print(f"Container:    {entry.container_image or 'N/A'}")
            if entry.raw_metadata:
                print(f"Version:      {entry.raw_metadata.get('version', 'N/A')}")
                print(f"Updated:      {entry.raw_metadata.get('updated_at', 'N/A')}")

        print("\n" + "=" * 80)
        print(f"✓ Test completed successfully!")
        print(f"  Total entries scraped: {len(entries)}")
        print(f"  Launch methods: {set(e.launch_method.value for e in entries)}")
        print(f"  With containers: {sum(1 for e in entries if e.container_image)}")
        print(f"  Require API keys: {sum(1 for e in entries if e.requires_api_key)}")

    except Exception as e:
        print(f"\n✗ Error during scraping: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
