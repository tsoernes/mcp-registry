# MCP Registry Testing Report

**Date:** 2025-11-10  
**Test Run:** Comprehensive functionality and code testing  
**Coverage:** 41% (48/64 tests passing)

## Executive Summary

The mcp-registry server is functional with working core registry operations, but several critical issues were discovered during testing:

1. ✅ **Core Registry Works**: Tools respond, background refresh runs, search/list operations functional
2. ❌ **Docker Registry Parser Broken**: Expects JSON but registry uses YAML format
3. ❌ **MCPServers Scraper Timeouts**: 60-second timeout insufficient for full scrape (~5,575 pages)
4. ❌ **Test Failures**: 16/64 tests failing due to fixture signature issues
5. ❌ **Coverage Below Threshold**: 41% vs 70% required

## Detailed Test Results

### Unit Tests (pytest)

```
Platform: linux
Python: 3.13.9
Pytest: 8.4.2
Result: 48 passed, 16 failed (75% pass rate)
Coverage: 40.68% (target: 70%)
```

#### Passing Tests (48)
- ✅ All model validation tests (RegistryEntry, ServerCommand, LaunchMethod, etc.)
- ✅ Registry core operations (add, search, list, rank by popularity)
- ✅ Fuzzy search with RapidFuzz integration
- ✅ Popularity-based ranking (official, featured, categories, etc.)
- ✅ Cache and state persistence

#### Failing Tests (16)
All failures in `tests/test_editor_config.py` due to fixture lambda signature:

```python
TypeError: editor_manager.<locals>.<lambda>() takes 0 positional arguments but 1 was given
```

**Affected Tests:**
- `test_add_zed_server_new_config`
- `test_add_zed_server_existing_config`
- `test_add_claude_server_new_config`
- `test_add_server_without_args_or_env`
- `test_remove_zed_server`
- `test_remove_nonexistent_server`
- `test_remove_server_no_config_file`
- `test_remove_claude_server`
- `test_list_configured_servers_zed`
- `test_list_configured_servers_claude`
- `test_list_configured_servers_empty`
- `test_list_configured_servers_no_file`
- `test_backup_created`
- `test_invalid_json_handling`
- `test_config_formatting`
- `test_overwrite_existing_server`

**Root Cause:** The test fixture creates mock callable but doesn't match method signature expecting `self`.

### Integration Tests (Manual Tool Calls)

#### ✅ registry-status
- **Status:** Working
- **Output:** Shows source status, entry counts, cache directories
- **Issue:** Docker source shows 0 entries (parser bug)

#### ✅ registry-list
- **Status:** Partially working
- **Docker source:** Returns 0 servers (YAML parsing not implemented)
- **MCPServers source:** Still refreshing after 5+ minutes

#### ✅ registry-active
- **Status:** Working
- **Output:** Correctly shows no active servers

#### ❌ registry-refresh
- **Status:** Timeout
- **Error:** `Context server request timeout` after 60 seconds
- **Cause:** MCPServers scraper processing 5,575+ HTML pages

#### ⏸️ registry-find
- **Status:** Not tested (no entries available)
- **Reason:** Both sources empty/still refreshing

#### ⏸️ registry-add
- **Status:** Not tested
- **Reason:** No entries to activate

## Critical Bugs Discovered

### 1. Docker Registry YAML Parser Not Implemented

**File:** `mcp_registry_server/scrapers/docker_registry.py`  
**Lines:** 133-165

**Current Code:**
```python
# Pattern 1: Single registry.json file
registry_json = repo_dir / "registry.json"

# Pattern 2: Multiple JSON files in a servers/ directory
servers_dir = repo_dir / "servers"
if servers_dir.exists() and servers_dir.is_dir():
    for json_file in servers_dir.glob("*.json"):
        # ...
```

**Actual Structure:**
```
~/.local/share/mcp-registry/sources/docker-mcp-registry/servers/
├── github/
│   └── server.yaml          # ← YAML format!
├── filesystem/
│   └── server.yaml
├── ...
```

**Sample YAML:**
```yaml
name: filesystem
image: mcp/filesystem
type: server
meta:
  category: devops
  tags:
    - filesystem
    - devops
about:
  title: Filesystem (Reference)
  description: Local filesystem access with configurable allowed paths
  icon: https://avatars.githubusercontent.com/u/182288589?s=200&v=4
source:
  project: https://github.com/modelcontextprotocol/servers
  branch: 2025.4.24
  commit: b4ee623039a6c60053ce67269701ad9e95073306
  dockerfile: src/filesystem/Dockerfile
config:
  secrets:
    - name: github.personal_access_token
      env: GITHUB_PERSONAL_ACCESS_TOKEN
      example: <YOUR_TOKEN>
```

**Fix Required:**
- Add `pyyaml` dependency
- Change glob pattern from `*.json` to `*/server.yaml`
- Parse YAML and map to RegistryEntry format
- Handle nested directory structure

### 2. MCPServers Scraper Concurrency Bottleneck

**File:** `scripts/scrape_mcpservers.py`  
**Lines:** 687-691

**Current Implementation:**
```python
async with httpx.AsyncClient(timeout=20) as client:
    # ← Missing connection limits!
```

**Issues:**
- AsyncClient doesn't use `max_connections` or `max_keepalive` parameters
- Default httpx connection limit is 100
- Function signature accepts parameters but doesn't apply them
- Current concurrency: 20 (semaphore)
- Actual HTTP concurrency: ~100 (httpx default)

**Fix Required:**
```python
import httpx

limits = httpx.Limits(
    max_connections=max_connections,
    max_keepalive_connections=max_keepalive
)
async with httpx.AsyncClient(timeout=20, limits=limits, http2=http2) as client:
    # ...
```

**Wrapper Call in mcpservers_scraper.py:**
```python
servers = await loop.run_in_executor(
    None,
    lambda: scrape_all_servers(
        # ...
        max_connections=128,      # ← Not being used!
        max_keepalive=32,         # ← Not being used!
    ),
)
```

### 3. Scraper Timeout During Initial Refresh

**Observation:**
- First run scrapes ~5,575 HTML pages from mcpservers.org
- Takes 5+ minutes even with caching
- MCP client timeout is 60 seconds
- Background refresh triggers but tool calls during refresh timeout

**Evidence:**
```bash
$ ls ~/.cache/mcp-registry/mcpservers_html/ | wc -l
5575
```

**Current Mitigation:**
- Scraper runs in executor (non-blocking)
- Background task continues after timeout

**Remaining Issue:**
- User can't force refresh without timeout
- No progress indication
- Cache population blocks initial use

### 4. Test Fixture Lambda Signature Mismatch

**File:** `tests/test_editor_config.py`  
**Pattern:** Multiple tests

**Issue:**
```python
@pytest.fixture
def editor_manager(tmp_path):
    return EditorConfigManager(
        get_zed_config_path=lambda: tmp_path / "zed_settings.json",
        #                    ^^^^^^ Missing self parameter!
        # ...
    )
```

**Expected Signature:**
```python
class EditorConfigManager:
    def __init__(self, get_zed_config_path: Callable[[Self], Path], ...):
        #                                           ^^^^^ Expects self
```

**Fix Required:**
Change lambda to accept unused `self`:
```python
get_zed_config_path=lambda self: tmp_path / "zed_settings.json",
```

## Code Coverage Analysis

### Low Coverage Areas (<30%)

| Module | Coverage | Missing Areas |
|--------|----------|---------------|
| editor_config.py | 29% | Config path resolution, backup logic, JSON5 parsing |
| podman_runner.py | 19% | Container lifecycle, exec dispatch, error handling |
| docker_registry.py | 13% | All parsing logic (YAML not implemented) |
| tasks.py | 15% | Background refresh scheduler, error recovery |
| server.py | 17% | FastMCP tool handlers, tool dispatch |

### High Coverage Areas (>90%)

| Module | Coverage | Status |
|--------|----------|--------|
| models.py | 100% | ✅ Excellent |
| registry.py | 91% | ✅ Good |
| __init__.py | 100% | ✅ Excellent |

## Performance Observations

### Scraping Performance

**MCPServers.org (Categories Mode):**
- Pages scraped: 5,575
- Time: ~5-10 minutes (first run)
- Cache hit: <1 minute (subsequent runs)
- Concurrency: 20 (semaphore) + ~100 (httpx default)

**Docker Registry (Git Clone):**
- Clone time: ~2 seconds
- Server definitions: 500+ directories
- No parsing (YAML support missing)

### Memory Usage
- Scraper HTML cache: ~323 MB (5,575 files)
- Git clone: ~1.5 MB
- Runtime: Not measured (TODO)

## Recommendations

### Priority 1 (Critical - Blocking Functionality)

1. **Fix Docker YAML Parser**
   - Add `pyyaml` dependency
   - Implement `*/server.yaml` parsing
   - Map YAML schema to RegistryEntry
   - **Impact:** Docker source completely broken (0 entries)

2. **Fix httpx Connection Limits**
   - Apply `max_connections` and `max_keepalive` to AsyncClient
   - Test with higher concurrency (50-100)
   - **Impact:** Scraper not using tunable parameters

3. **Fix Test Fixture Signatures**
   - Add `self` parameter to all lambda mocks
   - Re-run tests to verify editor config logic
   - **Impact:** 25% test failure rate

### Priority 2 (Important - Quality)

4. **Increase Test Coverage to 70%**
   - Add integration tests for Podman operations
   - Test editor config backup/restore
   - Test background refresh scheduler
   - Mock external dependencies (git, httpx)

5. **Add Scraper Progress Indication**
   - Emit progress events during long scrapes
   - Return quick stats before timeout
   - Provide incremental results

### Priority 3 (Enhancement)

6. **Optimize Initial Cache Population**
   - Add `--limit` parameter to initial refresh
   - Implement incremental scraping (top N pages per category)
   - Pre-seed cache with essential servers only

7. **Add CI/CD Pipeline**
   - GitHub Actions for tests on PR
   - Automated coverage reporting
   - Linting and type checking

8. **Implement registry-exec Dispatch**
   - MCP client communication for running containers
   - Support both stdio and HTTP transports
   - Tool forwarding to mounted servers

## Test Reproduction

### Run Full Test Suite
```bash
cd /home/torstein.sornes/code/mcp-registry
uv run pytest -v tests/
```

### Run Specific Test File
```bash
uv run pytest -v tests/test_registry.py
uv run pytest -v tests/test_editor_config.py
```

### Check Coverage Report
```bash
uv run pytest --cov-report=html
firefox htmlcov/index.html
```

### Manual Tool Testing
```python
# Use Zed AI assistant or Claude Desktop with mcp-registry server
registry_status()
registry_list(limit=10, source="docker")
registry_find(query="filesystem", limit=5)
```

## Files Examined

### Source Code
- ✅ `mcp_registry_server/registry.py` - Core registry logic
- ✅ `mcp_registry_server/models.py` - Data models
- ✅ `mcp_registry_server/editor_config.py` - Editor integration
- ✅ `mcp_registry_server/scrapers/mcpservers_scraper.py` - MCPServers wrapper
- ✅ `mcp_registry_server/scrapers/docker_registry.py` - Docker parser (broken)
- ✅ `scripts/scrape_mcpservers.py` - Scraper implementation
- ⏸️ `mcp_registry_server/podman_runner.py` - Not tested (no containers)
- ⏸️ `mcp_registry_server/server.py` - Partially tested (tools respond)

### Tests
- ✅ `tests/test_models.py` - 100% passing
- ✅ `tests/test_registry.py` - 100% passing
- ❌ `tests/test_editor_config.py` - 0% passing (16/16 failed)

### Configuration
- ✅ `pyproject.toml` - Dependencies correct (missing pyyaml)
- ✅ `pytest.ini` - Fixed (removed unsupported option)
- ✅ `README.md`, `QUICKSTART.md` - Documentation complete

## Conclusion

The mcp-registry server is **architecturally sound** with a well-designed modular structure, good separation of concerns, and comprehensive documentation. The core registry operations work correctly.

However, **critical bugs prevent both data sources from working:**
1. Docker registry parser doesn't support YAML
2. MCPServers scraper doesn't apply connection limits
3. Test suite has 25% failure rate

**Recommended Next Steps:**
1. Fix Docker YAML parser (1-2 hours)
2. Fix httpx connection limits (30 minutes)
3. Fix test fixtures (30 minutes)
4. Increase concurrency limit and test performance
5. Add progress indicators for long operations

**Estimated Time to Production-Ready:** 4-6 hours of focused work.