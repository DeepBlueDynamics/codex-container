# Product Search MCP Server

**Version:** 0.1.0  
**Source Article:** https://softwaredoug.com/blog/2025/09/22/agents-turn-simple-keyword-search-into-compelling-search-experiences

## Overview

This MCP server implements the "dumb search with agent reasoning" pattern from the article. Instead of building a complex search system with synonyms, query understanding, and reranking, it provides a simple, transparent keyword search that agents can learn to use effectively through iteration and memory.

## Core Concept

**Traditional RAG/Search:**
- Complex "thick" search API with query understanding, synonyms, reranking
- Agent calls once, gets results, done
- Opaque - hard for agent to understand what works

**This Approach:**
- Simple "dumb" keyword search (BM25-style)
- Agent tries queries, evaluates results, learns what works
- Transparent - agent builds mental model of how search works
- Semantic caching of query evaluations builds knowledge over time

## File Locations

```
codex-container/MCP/
├── product-search.py                           # Main MCP server
└── product_search_data/
    ├── products.json                           # Product catalog
    ├── query_history.json                      # Query evaluations & learning
    └── sample_furniture.json                   # 30 sample products to load
```

## Tools Available (10 total)

### 🔍 Search Tools

#### 1. `search_products`
Simple keyword or fuzzy similarity search.

**Parameters:**
- `query` (str): Search query
- `top_k` (int, default=5): Number of results
- `use_fuzzy` (bool, default=False): Enable fuzzy matching
- `fuzzy_threshold` (float, default=0.6): Min similarity (0.0-1.0)

**Modes:**
- **Keyword mode** (default): BM25-style token matching - intentionally simple
- **Fuzzy mode**: Text similarity matching using difflib

**Example:**
```python
# Keyword search
search_products("velvet sofa", top_k=5)

# Fuzzy search
search_products("vampyre couch", top_k=5, use_fuzzy=True, fuzzy_threshold=0.6)
```

#### 2. `fuzzy_search_products`
Dedicated fuzzy similarity search (convenience wrapper).

**Parameters:**
- `query` (str): Search query
- `top_k` (int, default=5): Number of results
- `similarity_threshold` (float, default=0.6): Min similarity

**Use when:**
- Query has typos or variations
- Looking for semantic matches
- Not sure of exact product names

**Example:**
```python
fuzzy_search_products("vampyre couch", top_k=5, similarity_threshold=0.6)
# Finds: "couch fit for a vampire" even with spelling variation
```

### 🧠 Learning/Memory Tools

#### 3. `get_past_queries`
Find similar past queries with their evaluations.

**Parameters:**
- `current_query` (str): Query to find matches for
- `similarity_threshold` (float, default=0.7): Min similarity
- `max_results` (int, default=5): Max similar queries

**Returns:** Past queries with:
- What the user wanted
- What query was used
- Quality rating (good/meh/bad)
- Reasoning why
- Similarity score

**Use before searching** to learn from past experience.

**Example:**
```python
get_past_queries("ugly chair", similarity_threshold=0.7, max_results=5)
# Returns: "ugliest chair in the catalog" with similarity 0.82
#          Shows which search terms worked: "cow print chair" (good), 
#                                           "weird chair" (bad)
```

#### 4. `save_query_evaluation`
Save how well a search worked for future learning.

**Parameters:**
- `user_query` (str): Original user intent
- `search_tool_query` (str): Actual search terms used
- `quality` (str): 'good', 'meh', or 'bad'
- `reasoning` (str): Why this rating

**Call after every search** to build knowledge graph.

**Example:**
```python
save_query_evaluation(
    user_query="ugliest chair in the catalog",
    search_tool_query="cow print chair",
    quality="good",
    reasoning="Returned an adult cow print task chair that clearly fits a loud/novelty aesthetic"
)
```

### 📦 Product Management Tools

#### 5. `add_product`
Add new product to catalog.

**Parameters:**
- `name` (str): Product name
- `description` (str): Product description
- `product_id` (str, optional): ID (auto-generated if omitted)
- `price` (float, optional): Price
- `category` (str, optional): Category
- `brand` (str, optional): Brand name
- `metadata` (dict, optional): Additional fields

**Example:**
```python
add_product(
    name="Gothic Throne Chair",
    description="Medieval-inspired high-back chair with carved gargoyles",
    price=2499.99,
    category="chair",
    brand="Castle Furniture"
)
```

#### 6. `update_product`
Update existing product fields.

**Parameters:**
- `product_id` (str): ID of product to update
- `name`, `description`, `price`, `category`, `brand`, `metadata` (all optional)

#### 7. `delete_product`
Remove product from catalog.

**Parameters:**
- `product_id` (str): ID to delete

#### 8. `list_products`
Browse products with pagination.

**Parameters:**
- `limit` (int, default=100): Max products to return
- `offset` (int, default=0): Skip this many products
- `category` (str, optional): Filter by category

**Example:**
```python
list_products(limit=20, offset=0, category="chair")
```

### 📊 Utility Tools

#### 9. `get_product_stats`
Get catalog and query history statistics.

**Returns:**
- Total products
- Category breakdown
- Total queries evaluated
- Quality rating distribution (good/meh/bad counts)
- Data directory location

#### 10. `load_sample_furniture`
Load 30 sample furniture products from the article.

**Parameters:**
- `replace_existing` (bool, default=False): Replace all products or add to existing

**Sample products include:**
- Velvet chesterfield sofas (for "vampire couch" queries)
- Chaise lounges with "fainting-couch energy"
- Bold statement pieces: zebra chair, cow print chair
- The infamous "Gaudy" armchair
- Gothic Revival chair, Victorian pieces
- Various styles: modern, industrial, bohemian, art deco

**Example:**
```python
load_sample_furniture(replace_existing=False)
# Adds 30 products to catalog
```

## Usage Pattern (From Article)

### System Prompt for Agent

```
You take user search queries and use search tools to find furniture products.

Look at the search tools you have, their limitations, how they work, etc when forming your plan.

Before searching you MUST use "get_past_queries" to get similar past queries the user has made.

Remember every tool usage you make. After searching with a tool, evaluate the results,
then save the interaction (immediately after tool usage) with "save_query_evaluation".
```

### Example Flow

1. **User asks:** "A couch fit for a vampire"

2. **Agent checks past queries:**
   ```python
   get_past_queries("couch fit for a vampire")
   # Returns: No similar queries yet
   ```

3. **Agent searches:**
   ```python
   search_products("velvet chesterfield dramatic", top_k=10)
   # Returns: Porter Chesterfield, Quitaque Chesterfield, etc.
   ```

4. **Agent evaluates and saves:**
   ```python
   save_query_evaluation(
       user_query="couch fit for a vampire",
       search_tool_query="velvet chesterfield dramatic",
       quality="good",
       reasoning="Returned multiple dramatically tufted velvet chesterfield options with a vampiric vibe"
   )
   ```

5. **Next time similar query comes:**
   ```python
   get_past_queries("vampire sofa")  # similarity: 0.75
   # Returns the successful "velvet chesterfield dramatic" query
   # Agent knows this pattern works!
   ```

## Key Features from Article

### ✅ Implemented

1. **Simple, transparent search** - BM25-style keyword matching
2. **Agent memory** - Query history with similarity lookup
3. **Learning system** - Quality evaluations (good/meh/bad)
4. **Semantic caching** - Past queries inform future searches
5. **Fuzzy matching** - For query similarity (borrowed from gnosis-files.py)

### ➕ Enhanced Beyond Article

1. **Fuzzy product search** - Not in article, but useful
2. **Product CRUD** - Add/update/delete/list products
3. **Sample data loader** - 30 furniture items ready to test
4. **Statistics** - Track learning progress

## Sample Queries to Try

After loading sample furniture with `load_sample_furniture()`:

```python
# From the article examples:
search_products("couch fit for a vampire")
# → Finds velvet chesterfields

search_products("ugliest chair in the catalog") 
# → Finds zebra chair, cow print chair, Gaudy armchair

search_products("gothic furniture")
# → Finds Abbey Gothic Revival chair, Avondale chaise

# Try fuzzy search:
fuzzy_search_products("vampyre couch", similarity_threshold=0.6)
# → Still finds vampire-appropriate furniture despite typo

fuzzy_search_products("fainting couch")
# → Finds chaise lounges
```

## Technical Details

### Search Implementation

**Keyword Search (BM25-style):**
```python
def bm25_score(query_tokens, doc_tokens):
    matches = sum(1 for qt in query_tokens if qt in doc_tokens)
    return matches / len(query_tokens)
```

**Fuzzy Search:**
```python
def calculate_similarity(text1, text2):
    return difflib.SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
```

### Data Storage

**products.json:**
```json
[
  {
    "id": "4306",
    "name": "Porter 80\" Velvet Rolled Arm Chesterfield Sofa",
    "description": "Luxurious velvet chesterfield...",
    "price": 1899.99,
    "category": "sofa",
    "brand": "Porter"
  }
]
```

**query_history.json:**
```json
[
  {
    "user_query": "ugliest chair in the catalog",
    "search_tool_query": "cow print chair",
    "quality": "good",
    "reasoning": "Returned an adult cow print task chair...",
    "timestamp": "2025-10-20T08:30:00"
  }
]
```

## Installation

1. **File is already created at:**
   ```
   C:\Users\kord\Code\gnosis\codex-container\MCP\product-search.py
   ```

2. **Install using evolve_tool:**
   ```python
   evolve_tool(
       tool_name="product-search",
       use_existing="product-search.py"
   )
   ```

3. **Load sample data:**
   ```python
   load_sample_furniture(replace_existing=False)
   ```

4. **Start searching and learning!**

## Philosophy

This implementation follows the article's key insight:

> "The traditional, thick search APIs are counterproductive to being used by agents. They may be too complex for agents to reason about effectively."

Instead of trying to make search smarter, we make it **simpler and transparent**, then let the agent apply its intelligence through:
- Iterative query refinement
- Learning from past queries
- Building a mental model of what works

The agent becomes the "smart" layer, while the search remains predictably "dumb."

## References

- **Article:** https://softwaredoug.com/blog/2025/09/22/agents-turn-simple-keyword-search-into-compelling-search-experiences
- **Author:** Doug Turnbull (softwaredoug.com)
- **Course:** "Cheat at Search with LLMs" - mentioned in article
