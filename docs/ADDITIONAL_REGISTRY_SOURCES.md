# Additional MCP Registry Sources

Research findings on alternative and complementary MCP registry sources to consider for integration.

**Research Date:** 2025-11-12

---

## Official/Primary Sources

### 1. **MCP Official Registry** ⭐ HIGH PRIORITY
- **URL:** https://registry.modelcontextprotocol.io
- **API:** https://github.com/modelcontextprotocol/registry
- **API Docs:** Live API documentation available
- **Status:** API freeze (v0.1) - stable, no breaking changes
- **Type:** Official community-driven registry service
- **Description:** The canonical source of truth for MCP servers. Launched as the official MCP Registry with open catalog and API for publicly available MCP servers.
- **Features:**
  - Metadata about packages (not actual code/binaries)
  - Links to NPM, PyPI, Docker Hub, GitHub Releases
  - Publish once, consume anywhere
  - API for integration
- **Blog:** http://blog.modelcontextprotocol.io/posts/2025-09-08-mcp-registry-preview/
- **Integration Priority:** **HIGH** - This is the official source and should be added as a primary registry source

### 2. **modelcontextprotocol/servers** ⭐ HIGH PRIORITY
- **URL:** https://github.com/modelcontextprotocol/servers
- **Type:** Official MCP server implementations
- **Description:** Official Model Context Protocol servers repository
- **Notable Servers:**
  - AWS Athena, Cognito, Cost Explorer, Open Data
  - Multiple official AWS integrations
  - Community-trusted implementations
- **Integration Priority:** **HIGH** - Official implementations, highly trusted

### 3. **Microsoft MCP Catalog** ⭐ HIGH PRIORITY
- **URL:** https://github.com/microsoft/mcp
- **Type:** Official Microsoft MCP server implementations
- **Description:** Catalog of official Microsoft MCP server implementations for AI-powered data access and tool integration
- **Integration Priority:** **HIGH** - Official Microsoft servers, enterprise-grade

---

## Community Registries & Aggregators

### 4. **Glama.ai MCP Registry** ⭐ MEDIUM-HIGH PRIORITY
- **URL:** https://glama.ai/mcp/servers
- **API:** https://glama.ai/api/mcp/v1/servers/
- **JSON Feed:** https://glama.ai/mcp/servers.json
- **Type:** Commercial directory with API
- **Description:** Comprehensive MCP server directory with 3,000+ servers
- **Features:**
  - Direct API access for programmatic queries
  - Discord integration for new server announcements
  - Search functionality
  - Metadata for each server
- **Integration Priority:** **MEDIUM-HIGH** - Large catalog with API, but commercial/third-party

### 5. **MCP-Get Registry** ⭐ MEDIUM PRIORITY
- **URL:** https://mcp-get.com
- **GitHub:** https://github.com/michaellatman/mcp-get
- **Type:** CLI package manager with registry
- **Description:** Command-line tool that manages MCP servers with package registry
- **Features:**
  - Package management
  - Comprehensive analytics
  - GitHub integration
  - Browse and search interface
- **Integration Priority:** **MEDIUM** - CLI-focused, may have API for registry data

### 6. **Mastra.ai MCP Registry Registry**
- **URL:** https://mastra.ai/mcp-registry-registry
- **Type:** Meta-registry (registry of registries)
- **Description:** "The Definitive hub for MCP Registries"
- **Integration Priority:** **LOW-MEDIUM** - Meta-registry, useful for discovery but may be redundant

---

## Awesome Lists (Curated Collections)

### 7. **punkpeye/awesome-mcp-servers** ⭐ MEDIUM PRIORITY
- **URL:** https://github.com/punkpeye/awesome-mcp-servers
- **Type:** Curated awesome list
- **Description:** A curated list of awesome Model Context Protocol (MCP) servers
- **Integration Priority:** **MEDIUM** - Well-maintained, but manual curation may lag

### 8. **wong2/awesome-mcp-servers**
- **URL:** https://github.com/wong2/awesome-mcp-servers
- **Type:** Curated awesome list
- **Notable:** Includes context-awesome server (queries 8,500+ curated awesome lists)
- **Integration Priority:** **LOW-MEDIUM** - Alternative awesome list

### 9. **appcypher/awesome-mcp-servers**
- **URL:** https://github.com/appcypher/awesome-mcp-servers
- **Type:** Curated awesome list
- **Description:** Mentioned in r/Anthropic discussions
- **Integration Priority:** **LOW-MEDIUM** - One of several awesome lists

### 10. **TensorBlock/awesome-mcp-servers**
- **URL:** https://github.com/TensorBlock/awesome-mcp-servers
- **Type:** Comprehensive collection
- **Description:** Claims to be a comprehensive collection
- **Integration Priority:** **LOW-MEDIUM** - Another awesome list variant

### 11. **habitoai/Awesome-MCP-Servers-directory**
- **URL:** https://github.com/habitoai/Awesome-MCP-Servers-directory
- **Type:** Categorized collection
- **Description:** Servers categorized by functionality
- **Integration Priority:** **LOW-MEDIUM** - Categorization may be useful

### 12. **rohitg00/awesome-devops-mcp-servers**
- **URL:** https://github.com/rohitg00/awesome-devops-mcp-servers
- **Type:** DevOps-focused list
- **Description:** Curated list focused on DevOps tools
- **Integration Priority:** **LOW** - Niche focus

### 13. **esc5221/awesome-awesome-mcp-servers**
- **URL:** https://github.com/esc5221/awesome-awesome-mcp-servers
- **Type:** Meta awesome list (list of lists)
- **Description:** Curated list of awesome-mcp-servers lists
- **Integration Priority:** **LOW** - Meta-list, useful for discovery only

---

## Specialized/Enterprise

### 14. **Azure API Center** (Microsoft)
- **URL:** https://learn.microsoft.com/en-us/azure/api-center/register-discover-mcp-server
- **Type:** Enterprise registry service
- **Description:** Use Azure API Center to maintain an inventory/registry of remote MCP servers
- **Features:**
  - Private enterprise registry
  - API Center portal for discovery
  - Integration with Azure API Management
- **Integration Priority:** **LOW** - Enterprise/private focus, not public registry

### 15. **IBM Context Forge**
- **URL:** https://github.com/IBM/mcp-context-forge
- **Type:** MCP Gateway & Registry
- **Description:** Central management point for tools, resources, and prompts
- **Features:**
  - Converts REST API endpoints to MCP
  - Composes virtual MCP servers
  - OAuth 2.0 support
  - MCP Server Catalog in YAML
  - Protocol conversion (stdio, SSE, Streamable HTTP)
- **Integration Priority:** **LOW-MEDIUM** - Interesting for gateway features, but complex

---

## Implementation Recommendations

### Phase 1: High-Priority Official Sources
1. **MCP Official Registry** - Add as primary source
   - API endpoint: https://registry.modelcontextprotocol.io (check docs for exact endpoint)
   - Stable API (v0.1 freeze)
   - Create new scraper: `mcp_official_registry.py`

2. **modelcontextprotocol/servers** - Git source (similar to Docker registry)
   - Clone/update: https://github.com/modelcontextprotocol/servers
   - Parse server definitions (likely JSON/YAML)

3. **Microsoft MCP** - Git source
   - Clone/update: https://github.com/microsoft/mcp
   - Parse catalog structure

### Phase 2: Enhanced Metadata
4. **GitHub Stars** - ✅ IMPLEMENTED
   - Fetch stars from GitHub API for repositories
   - Use logarithmic scale for ranking (10 stars = +1, 100 = +2, etc.)
   - Capped at +10 points for very popular projects
   - Added to `raw_metadata["github_stars"]`
   - Significantly improves popularity ranking

### Phase 3: Community Aggregators
5. **Glama.ai** - Add if API is accessible
   - JSON endpoint: https://glama.ai/mcp/servers.json
   - Large catalog (3,000+ servers)
   - Create scraper: `glama_registry.py`

### Phase 4: Curated Lists (Lower Priority)
6. Consider aggregating 1-2 well-maintained awesome lists
   - Focus on punkpeye/awesome-mcp-servers (most established)
   - Parse README.md for server entries

### Not Recommended
- **Azure API Center** - Enterprise/private focus
- **Multiple awesome lists** - Too much overlap, pick 1-2 max
- **Meta-lists** - Redundant with direct sources
- **IBM Context Forge** - Gateway focus, not a registry

---

## Technical Considerations

### API Access
- **MCP Official Registry:** Has API, needs investigation of endpoints/auth
- **Glama.ai:** JSON feed available, check rate limits/terms
- **GitHub sources:** Use existing git clone/update mechanism

### Data Normalization
All sources should map to existing `RegistryEntry` model:
- Extract: name, description, categories, tags, repo_url, container_image
- Map source-specific fields to standard schema
- Handle missing fields gracefully

### Rate Limiting
- GitHub API: Existing rate limits apply
- New APIs: Implement per-source rate limiting
- Cache aggressively (24h+ for static data)

### Ranking/Priority
Current search ranking weights:
- Official flag (+20 points)
- MCP Official Registry source (+15 points)
- Featured flag (+10 points)
- GitHub stars (logarithmic, max +10 points)
- Docker registry source (+5 points)
- Container image (+3 points)
- Categories (+2 points each, max 3)

Future additions:
- Microsoft/AWS official (+12 points)
- Community registries (+5 points)
- Awesome lists (+2 points)

---

## Next Steps

1. ✅ **MCP Official Registry** - COMPLETED
   - Implemented scraper with GitHub stars fetching
   - Integrated into background refresh scheduler
   - Search ranking with highest priority (+15 points)
   - GitHub stars add logarithmic popularity boost
   - Test script validates functionality

2. **Test Glama.ai JSON feed:**
   - Fetch: https://glama.ai/mcp/servers.json
   - Analyze schema
   - Check rate limits/ToS

3. **Implement remaining Phase 1 sources:**
   - modelcontextprotocol/servers git scraper
   - Microsoft MCP catalog scraper

4. **Enhanced popularity metrics:**
   - Consider download counts from NPM/PyPI
   - Track activation frequency in local registry
   - Monitor update recency

5. **Documentation:**
   - ✅ Update README with MCP Official source
   - ✅ Document source priorities
   - ✅ Add implementation summary
   - Add source selection criteria for users

---

## References

- MCP Registry Blog: http://blog.modelcontextprotocol.io/posts/2025-09-08-mcp-registry-preview/
- MCP Developer Summit: Registry session discussions
- Reddit r/ClaudeAI: Community feedback on registries (1h2cnf1, 1h36xzl)
- Reddit r/LocalLLaMA: 2000+ MCP servers discussion (1jromm0)