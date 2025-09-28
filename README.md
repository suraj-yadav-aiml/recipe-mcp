# Recipe Research MCP Server

A comprehensive Model Context Protocol (MCP) server that provides recipe search, storage, and meal planning functionality using TheMealDB API. Built with FastMCP and designed for both local development and remote deployment.

## 🚀 Features

### 🔍 Recipe Search & Discovery
- Search recipes by dish name or cuisine
- Find recipes starting with specific letters
- Get random recipe suggestions
- Detailed recipe information with ingredients, instructions, and metadata

### 📊 Recipe Management
- Automatic recipe storage and indexing
- Fast recipe lookup system
- Recipe collection organization by cuisine/dish type
- Cross-platform file handling with proper sanitization

### 🍽️ Meal Planning
- Create custom meal plans from selected recipes
- Save and manage multiple meal plans
- Recipe collection statistics and insights

### 🎯 MCP Integration
- **Tools**: Interactive recipe search and meal planning functions
- **Resources**: Read-only access to recipe collections and statistics
- **Prompts**: Pre-defined templates for cooking education and analysis

## 📋 Requirements

- **Python**: 3.12 or higher
- **Package Manager**: UV (recommended)
- **Dependencies**:
  - `mcp[cli]>=1.15.0`
  - `httpx>=0.28.1`
  - `aiofiles>=24.1.0`

## 🛠️ Installation

### Using UV (Recommended)

```bash
# Clone the repository
git clone https://github.com/suraj-yadav-aiml/recipe-mcp.git
cd recipe-mcp

# Create and activate virtual environment
uv venv
# On Windows
.venv\Scripts\activate
# On macOS/Linux
source .venv/bin/activate

# Install dependencies
uv sync

# Test the MCP Server
mcp dev recipe_server.py
```

### Using pip

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows
.venv\Scripts\activate
# On macOS/Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Test the MCP Server
mcp dev recipe_server.py
```

## 🚀 Usage

### Local Development (STDIO Transport)

```bash
if __name__ == "__main__":
    mcp.run(transport="stdio") 
```

### Remote Deployment (HTTP Transport)

```bash

if __name__ == "__main__":
    mcp.run(transport="streamable-http") 
```

### MCP Client Configuration

Add to your MCP client configuration:

```json
{
  "recipe_research": {
    "command": "uv",
    "args": [
      "run",
      "--with",
      "mcp[cli]",
      "httpx",
      "aiofiles",
      "mcp",
      "run",
      "path/to/recipe_server.py"
    ],
    "cwd": "path/to/project",
    "env": {
      "PYTHONPATH": "path/to/project"
    }
  }
}
```
Or

```josn
{
  "recipe_research": {
      "command": "C:\\Users\\Admin\\.local\\bin\\uv.EXE",
      "args": [
        "--directory",
        ""path/to/project"",
        "run",
        ""path/to/project"/recipe_server.py"
    ]
  }
}

```

## 🔧 API Reference

### Tools

#### `search_recipes(dish_name: str, max_results: int = 5)`
Search for recipes by dish name using TheMealDB API.

**Example:**
```python
# Search for pasta recipes
results = await search_recipes("pasta", max_results=10)
```

#### `get_recipe_details(recipe_id: str)`
Get detailed information about a specific recipe by ID.

**Example:**
```python
# Get details for recipe ID 52771
details = await get_recipe_details("52771")
```

#### `create_meal_plan(recipe_ids: List[str], plan_name: str = "My Meal Plan")`
Create a meal plan from selected recipe IDs.

**Example:**
```python
# Create a meal plan
plan = await create_meal_plan(
    ["52771", "52772", "52773"],
    "Italian Week"
)
```

#### `search_by_first_letter(letter: str, max_results: int = 5)`
Search for recipes that start with a specific letter.

**Example:**
```python
# Find recipes starting with 'A'
results = await search_by_first_letter("A")
```

#### `get_random_recipe()`
Get a random recipe from TheMealDB.

### Resources

#### `recipes://cuisines`
List all available recipe collections in the database.

#### `recipes://{cuisine}`
Get detailed information about recipes in a specific cuisine collection.

**Example:** `recipes://italian`, `recipes://pasta`

#### `recipes://meal-plans`
View all saved meal plans with their details.

#### `recipes://stats`
Get comprehensive statistics about the recipe collection.

### Prompts

#### `generate_recipe_search_prompt(cuisine_type: str, num_recipes: int = 5)`
Generate a comprehensive prompt for recipe search and culinary analysis.

#### `generate_meal_planning_prompt(meal_type: str, people_count: int = 4, dietary_restrictions: str = "none")`
Create a detailed meal planning prompt with shopping lists and preparation guides.

#### `generate_cooking_lesson_prompt(skill_level: str, technique_focus: str, cuisine_style: str = "any")`
Design structured cooking lessons focused on specific techniques.

#### `generate_ingredient_exploration_prompt(main_ingredient: str, cooking_styles: str = "diverse", num_recipes: int = 6)`
Explore recipes and techniques featuring a specific ingredient.

#### `generate_cultural_cuisine_prompt(cuisine_name: str, cultural_context: str = "traditional", num_recipes: int = 5)`
Explore the cultural heritage and traditions of specific cuisines.

## 📁 Data Structure

```
recipes/
├── <dish_name>/
│   └── recipes_info.json          # Recipe details by dish/cuisine
├── meal_plans/
│   └── <plan_name>.json          # Saved meal plans
├── by_letter/
│   └── letter_<x>_search.json    # Letter-based searches
└── recipe_index.json             # Master recipe index
```

### Recipe Data Format

```json
{
  "recipe_id": {
    "name": "Recipe Name",
    "cuisine": "Italian",
    "category": "Pasta",
    "instructions": "Step by step instructions...",
    "image_url": "https://...",
    "youtube_url": "https://...",
    "source_url": "https://...",
    "ingredients": [
      {
        "ingredient": "Tomatoes",
        "measure": "400g"
      }
    ],
    "tags": ["Vegetarian", "Quick"]
  }
}
```

## 🌐 API Integration

This server integrates with [TheMealDB](https://www.themealdb.com/) free API:

- **Base URL**: `https://www.themealdb.com/api/json/v1/1`
- **Search by name**: `/search.php?s={dish_name}`
- **Search by letter**: `/search.php?f={letter}`
- **Random recipe**: `/random.php`

No API key required for the free tier.

## 🔧 Development

### Code Standards

- **Async/Await**: All I/O operations use asyncio and aiofiles
- **HTTP Requests**: Use httpx for all web requests
- **Path Handling**: Use Pathlib for cross-platform compatibility
- **Error Handling**: Comprehensive but not verbose
- **Concurrency**: Use asyncio.gather() for parallel operations
- **No Logging**: Code should not include logging statements

### File Operations

- All JSON files use UTF-8 encoding with `ensure_ascii=False`
- Directory creation uses `mode=0o755` for cross-platform compatibility
- Filename sanitization removes invalid characters for Windows/Mac/Linux compatibility
- Recipe index automatically rebuilds when stale entries are detected



##  Deployment


### Local Development
- Uses STDIO transport by default
- Suitable for MCP client integration

### Remote Deployment
- Set `PORT` environment variable
- Server binds to `0.0.0.0` for external access
- Uses streamable HTTP transport

## 📊 Performance Features

- **Concurrent Operations**: Recipe processing uses asyncio.gather()
- **Caching**: Recipe index provides fast lookups
- **Lazy Loading**: Resources load data on-demand
- **Cross-platform**: Handles Windows, Mac, and Linux file systems


## 📄 License

This project is part of an educational MCP server implementation.

## 🔗 Related Links

- [Model Context Protocol Documentation](https://modelcontextprotocol.io/)
- [FastMCP Framework](https://github.com/jlowin/fastmcp)
- [TheMealDB API](https://www.themealdb.com/api.php)
- [UV Package Manager](https://github.com/astral-sh/uv)