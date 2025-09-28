import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List

import aiofiles
import httpx
from mcp.server.fastmcp import FastMCP


port = int(os.getenv("PORT", 8000))


# For remote deployment
mcp = FastMCP(
    name="recipe_research",
    host="0.0.0.0",
    port=port,
)

# testing for local deployment
# mcp = FastMCP(
#     name="recipe_research"
# )

# Create recipes directory
SCRIPT_DIR = Path(__file__).parent.resolve()
RECIPES_DIR = SCRIPT_DIR / "recipes"

# Initialize recipes directory on startup
try:
    RECIPES_DIR.mkdir(mode=0o755, exist_ok=True)

    # Test write permissions
    test_file = RECIPES_DIR / "write_test.txt"
    try:
        test_file.write_text("test", encoding="utf-8")
        test_file.unlink()  # Delete test file
    except Exception:
        pass

except Exception:
    pass

# Recipe index for faster lookups
RECIPE_INDEX_FILE = RECIPES_DIR / "recipe_index.json"



@mcp.tool()
async def search_recipes(dish_name: str, max_results: int = 5) -> List[str]:
    """
    Search for recipes by dish name. Extract ONLY the dish/food name from the user's query.

    Examples:
    - User says "Search for Arrabiata recipes" -> dish_name should be "Arrabiata"
    - User says "Find me some pasta recipes" -> dish_name should be "pasta"
    - User says "I want chicken curry recipes" -> dish_name should be "chicken curry"
    - User says "Show me pizza recipes with 5 results" -> dish_name should be "pizza"

    Args:
        dish_name: ONLY the dish/food name (e.g., "Arrabiata", "pasta", "chicken", "pizza", "curry")
        max_results: Number of results to return (extract from user query if specified, default: 5)

    Returns:
        List of recipe IDs found in the search
    """
    try:
        # Use the free search endpoint with the extracted dish name
        base_url = "https://www.themealdb.com/api/json/v1/1"
        search_url = f"{base_url}/search.php?s={dish_name}"

        async with httpx.AsyncClient() as client:
            response = await client.get(search_url, timeout=10)
            response.raise_for_status()

        data = response.json()

        if not data.get("meals"):
            return [f"No recipes found for dish: {dish_name}"]

        meals = data["meals"][:max_results]

        # Create directory for this search term - sanitize for all platforms
        # Remove characters that are invalid in filenames on Windows/Mac/Linux
        invalid_chars = '<>:"/\\|?*'
        dish_safe = dish_name.lower()
        for char in invalid_chars:
            dish_safe = dish_safe.replace(char, "_")
        dish_safe = dish_safe.replace(" ", "_")

        # Remove any leading/trailing dots or spaces (Windows compatibility)
        dish_safe = dish_safe.strip(". ")

        # Ensure the directory name isn't too long (Windows: 255, others: 255)
        if len(dish_safe) > 200:
            dish_safe = dish_safe[:200]

        # Ensure it's not empty or just underscores
        if not dish_safe or dish_safe.replace("_", "").strip() == "":
            dish_safe = "unknown_dish"

        dish_path = RECIPES_DIR / dish_safe

        try:
            dish_path.mkdir(mode=0o755, exist_ok=True)
        except Exception as e:
            return [f"Cannot create dish directory {dish_path}: {str(e)}"]

        file_path = dish_path / "recipes_info.json"

        # Try to load existing recipes info
        recipes_info = {}
        if file_path.exists():
            try:
                async with aiofiles.open(file_path, "r", encoding="utf-8") as json_file:
                    content = await json_file.read()
                    recipes_info = json.loads(content)
            except (FileNotFoundError, json.JSONDecodeError):
                pass

        # Process each recipe and get detailed information
        recipe_ids = []
        for meal in meals:
            recipe_id = meal["idMeal"]
            recipe_ids.append(recipe_id)

            # Since we already have detailed info from search, use it directly
            # Extract ingredients (TheMealDB has ingredients as strIngredient1, strIngredient2, etc.)
            ingredients = []
            for i in range(1, 21):  # TheMealDB has up to 20 ingredients
                ingredient = meal.get(f"strIngredient{i}")
                measure = meal.get(f"strMeasure{i}")
                if ingredient and ingredient.strip():
                    ingredients.append(
                        {
                            "ingredient": ingredient.strip(),
                            "measure": measure.strip() if measure else "",
                        }
                    )

            recipe_info = {
                "name": meal.get("strMeal", "Unknown"),
                "cuisine": meal.get("strArea", "Unknown"),
                "category": meal.get("strCategory", "Unknown"),
                "instructions": meal.get(
                    "strInstructions", "No instructions available"
                ),
                "image_url": meal.get("strMealThumb", ""),
                "youtube_url": meal.get("strYoutube", ""),
                "source_url": meal.get("strSource", ""),
                "ingredients": ingredients,
                "tags": (
                    meal.get("strTags", "").split(",") if meal.get("strTags") else []
                ),
            }

            recipes_info[recipe_id] = recipe_info

        # Save updated recipes_info
        try:
            async with aiofiles.open(file_path, "w", encoding="utf-8") as json_file:
                await json_file.write(json.dumps(recipes_info, indent=2, ensure_ascii=False))

            # Update recipe index
            try:
                recipe_index = await _load_recipe_index()
                for recipe_id in recipe_ids:
                    recipe_index[recipe_id] = str(file_path)

                async with aiofiles.open(RECIPE_INDEX_FILE, "w", encoding="utf-8") as index_file:
                    await index_file.write(json.dumps(recipe_index, indent=2))
            except Exception:
                pass

            return recipe_ids
        except Exception:
            # Return recipe IDs even if save fails
            return recipe_ids

    except httpx.RequestError as e:
        return [f"Error fetching recipes: {str(e)}"]
    except Exception as e:
        return [f"Error in search_recipes: {str(e)}"]

async def _build_recipe_index() -> dict[str, str]:
    """Build an index mapping recipe IDs to their file paths."""
    index = {}

    if not RECIPES_DIR.exists():
        return index

    # Collect all recipe info files
    recipe_files = []
    for item_path in RECIPES_DIR.iterdir():
        if item_path.is_dir():
            file_path = item_path / "recipes_info.json"
            if file_path.is_file():
                recipe_files.append(file_path)

    # Process files concurrently
    async def process_file(file_path: Path) -> dict[str, str]:
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as json_file:
                content = await json_file.read()
                recipes_info = json.loads(content)
                return {recipe_id: str(file_path) for recipe_id in recipes_info.keys()}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    # Process all files concurrently
    tasks = [process_file(file_path) for file_path in recipe_files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge results
    for result in results:
        if isinstance(result, dict):
            index.update(result)

    return index


async def _load_recipe_index() -> dict[str, str]:
    """Load recipe index from cache or build it."""
    try:
        if RECIPE_INDEX_FILE.exists():
            async with aiofiles.open(RECIPE_INDEX_FILE, "r", encoding="utf-8") as f:
                content = await f.read()
                return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Build and cache index
    index = await _build_recipe_index()
    try:
        async with aiofiles.open(RECIPE_INDEX_FILE, "w", encoding="utf-8") as f:
            await f.write(json.dumps(index, indent=2))
    except Exception:
        pass

    return index


@mcp.tool()
async def get_recipe_details(recipe_id: str) -> str:
    """
    Get detailed information about a specific recipe using its ID.

    Examples:
    - User says "Get details for recipe 52771" -> recipe_id should be "52771"
    - User says "Show me information about recipe ID 52772" -> recipe_id should be "52772"
    - User says "Tell me about recipe 52773" -> recipe_id should be "52773"

    Args:
        recipe_id: ONLY the numeric recipe ID (extract the ID number from user's request)

    Returns:
        JSON string with detailed recipe information if found, error message if not found
    """
    try:
        if not RECIPES_DIR.exists():
            return f"Recipes directory {RECIPES_DIR} does not exist."

        # Load recipe index for fast lookup
        recipe_index = await _load_recipe_index()

        if recipe_id not in recipe_index:
            return f"No saved information found for recipe {recipe_id}."

        # Get file path from index
        file_path = Path(recipe_index[recipe_id])

        if not file_path.exists():
            # Index is stale, rebuild it
            recipe_index = await _build_recipe_index()
            if recipe_id not in recipe_index:
                return f"No saved information found for recipe {recipe_id}."
            file_path = Path(recipe_index[recipe_id])

        # Load recipe details
        async with aiofiles.open(file_path, "r", encoding="utf-8") as json_file:
            content = await json_file.read()
            recipes_info = json.loads(content)

            if recipe_id in recipes_info:
                return json.dumps(recipes_info[recipe_id], indent=2)
            else:
                return f"Recipe {recipe_id} not found in {file_path}."

    except Exception as e:
        return f"Error in get_recipe_details: {str(e)}"

@mcp.tool()
async def create_meal_plan(recipe_ids: List[str], plan_name: str = "My Meal Plan") -> str:
    """
    Create a meal plan from selected recipe IDs. Extract recipe IDs and plan name from user query.

    Examples:
    - User says "Create meal plan with recipes 52771,52772,52773 called 'Italian Week'"
      -> recipe_ids should be ["52771", "52772", "52773"], plan_name should be "Italian Week"
    - User says "Make a meal plan named 'Dinner Ideas' using recipes 52774 and 52775"
      -> recipe_ids should be ["52774", "52775"], plan_name should be "Dinner Ideas"

    Args:
        recipe_ids: List of recipe ID numbers as strings (extract all IDs from user request)
        plan_name: Name for the meal plan (extract name from user request, default: "My Meal Plan")

    Returns:
        Success message with meal plan details or error message
    """
    try:
        # Create meal plans directory
        meal_plans_dir = RECIPES_DIR / "meal_plans"
        meal_plans_dir.mkdir(mode=0o755, exist_ok=True)

        # Sanitize plan name for cross-platform filename compatibility
        invalid_chars = '<>:"/\\|?*'
        plan_safe = plan_name.lower()
        for char in invalid_chars:
            plan_safe = plan_safe.replace(char, "_")
        plan_safe = plan_safe.replace(" ", "_")

        # Remove leading/trailing dots or spaces (Windows compatibility)
        plan_safe = plan_safe.strip(". ")

        if len(plan_safe) > 200:
            plan_safe = plan_safe[:200]

        # Ensure it's not empty
        if not plan_safe or plan_safe.replace("_", "").strip() == "":
            plan_safe = "meal_plan"

        plan_file = meal_plans_dir / f"{plan_safe}.json"

        # Collect recipe details for the meal plan using async calls
        async def get_recipe_data(recipe_id: str) -> dict | None:
            recipe_details = await get_recipe_details(recipe_id)
            if not recipe_details.startswith("No saved information") and not recipe_details.startswith("Error"):
                try:
                    recipe_data = json.loads(recipe_details)
                    return {
                        "id": recipe_id,
                        "name": recipe_data.get("name", "Unknown Recipe"),
                        "cuisine": recipe_data.get("cuisine", "Unknown"),
                        "category": recipe_data.get("category", "Unknown"),
                    }
                except json.JSONDecodeError:
                    pass
            return None

        # Process all recipe IDs concurrently
        tasks = [get_recipe_data(recipe_id) for recipe_id in recipe_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        meal_plan_recipes = []
        for result in results:
            if isinstance(result, dict) and result is not None:
                meal_plan_recipes.append(result)

        # Create timestamp
        timestamp = datetime.now().isoformat()

        meal_plan = {
            "plan_name": plan_name,
            "created_date": timestamp,
            "total_recipes": len(meal_plan_recipes),
            "recipes": meal_plan_recipes,
        }

        # Save meal plan using async file operations
        async with aiofiles.open(plan_file, "w", encoding="utf-8") as json_file:
            await json_file.write(json.dumps(meal_plan, indent=2, ensure_ascii=False))

        return f"Meal plan '{plan_name}' created successfully with {len(meal_plan_recipes)} recipes. Saved to: {plan_file}"

    except Exception as e:
        return f"Error creating meal plan: {str(e)}"


@mcp.tool()
async def search_by_first_letter(letter: str, max_results: int = 5) -> List[str]:
    """
    Search for recipes that start with a specific letter. Extract ONLY the single letter from user query.

    Examples:
    - User says "Show me recipes starting with A" -> letter should be "A"
    - User says "Find dishes that begin with the letter B" -> letter should be "B"
    - User says "Get recipes starting with letter C" -> letter should be "C"

    Args:
        letter: ONLY a single letter A-Z (extract the letter from user's request)
        max_results: Number of results to return (default: 5)

    Returns:
        List of recipe IDs found in the search
    """
    try:
        if len(letter) != 1 or not letter.isalpha():
            return [f"Please provide a single letter (a-z)"]

        base_url = "https://www.themealdb.com/api/json/v1/1"
        search_url = f"{base_url}/search.php?f={letter.lower()}"

        async with httpx.AsyncClient() as client:
            response = await client.get(search_url, timeout=10)
            response.raise_for_status()

        data = response.json()

        if not data.get("meals"):
            return [f"No recipes found starting with letter: {letter}"]

        meals = data["meals"][:max_results]
        recipe_ids = [meal["idMeal"] for meal in meals]

        # Save to letters directory
        letters_dir = RECIPES_DIR / "by_letter"
        letters_dir.mkdir(mode=0o755, exist_ok=True)

        # Create simple summary file
        summary = {
            "letter": letter.upper(),
            "found_recipes": len(recipe_ids),
            "recipe_ids": recipe_ids,
            "recipe_names": [meal["strMeal"] for meal in meals],
        }

        summary_file = letters_dir / f"letter_{letter.lower()}_search.json"

        async with aiofiles.open(summary_file, "w", encoding="utf-8") as json_file:
            await json_file.write(json.dumps(summary, indent=2, ensure_ascii=False))

        return recipe_ids

    except httpx.RequestError as e:
        return [f"Error searching by letter: {str(e)}"]
    except Exception as e:
        return [f"Error in search_by_first_letter: {str(e)}"]


@mcp.tool()
async def get_random_recipe() -> str:
    """
    Get a random recipe from TheMealDB.

    Returns:
        JSON string with random recipe information
    """
    try:
        base_url = "https://www.themealdb.com/api/json/v1/1"
        search_url = f"{base_url}/random.php"

        async with httpx.AsyncClient() as client:
            response = await client.get(search_url, timeout=10)
            response.raise_for_status()

        data = response.json()

        if not data.get("meals"):
            return "No random recipe found"

        meal = data["meals"][0]

        # Extract ingredients
        ingredients = []
        for i in range(1, 21):
            ingredient = meal.get(f"strIngredient{i}")
            measure = meal.get(f"strMeasure{i}")
            if ingredient and ingredient.strip():
                ingredients.append(
                    {
                        "ingredient": ingredient.strip(),
                        "measure": measure.strip() if measure else "",
                    }
                )

        recipe_info = {
            "id": meal.get("idMeal"),
            "name": meal.get("strMeal", "Unknown"),
            "cuisine": meal.get("strArea", "Unknown"),
            "category": meal.get("strCategory", "Unknown"),
            "instructions": meal.get("strInstructions", "No instructions available"),
            "image_url": meal.get("strMealThumb", ""),
            "youtube_url": meal.get("strYoutube", ""),
            "source_url": meal.get("strSource", ""),
            "ingredients": ingredients,
            "tags": meal.get("strTags", "").split(",") if meal.get("strTags") else [],
        }

        return json.dumps(recipe_info, indent=2)

    except httpx.RequestError as e:
        return f"Error getting random recipe: {str(e)}"
    except Exception as e:
        return f"Error in get_random_recipe: {str(e)}"


@mcp.tool()
async def test_filesystem() -> str:
    """Test basic filesystem operations"""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "test.json"
            test_data = {"test": "data", "status": "working", "platform": sys.platform}

            async with aiofiles.open(test_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(test_data, indent=2))

            async with aiofiles.open(test_file, "r", encoding="utf-8") as f:
                content = await f.read()
                loaded_data = json.loads(content)

            return f"Filesystem test PASSED on {sys.platform}: {loaded_data}"

    except Exception as e:
        return f"Filesystem test FAILED: {str(e)}"


@mcp.tool()
async def get_system_info() -> str:
    """Get system and directory information for debugging"""
    try:
        info = {
            "platform": sys.platform,
            "python_version": sys.version,
            "script_directory": str(SCRIPT_DIR),
            "recipes_directory": str(RECIPES_DIR),
            "recipes_dir_exists": RECIPES_DIR.exists(),
            "recipes_dir_is_writable": (
                os.access(RECIPES_DIR, os.W_OK) if RECIPES_DIR.exists() else False
            ),
            "current_working_directory": str(Path.cwd()),
        }
        return json.dumps(info, indent=2)
    except Exception as e:
        return f"Error getting system info: {str(e)}"


# ==================== RESOURCES ====================
# Resources provide read-only access to data


@mcp.resource("recipes://cuisines")
async def get_available_cuisines() -> str:
    """
    List all available cuisine folders in the recipes directory.

    This resource provides a simple list of all available cuisine/dish folders
    that contain saved recipe information.
    """
    cuisines = []

    # Get all cuisine/dish directories
    if RECIPES_DIR.exists():
        # Process directories concurrently
        async def check_cuisine_dir(cuisine_dir: Path) -> dict | None:
            if cuisine_dir.is_dir() and cuisine_dir.name not in ["meal_plans", "by_letter"]:
                recipes_file = cuisine_dir / "recipes_info.json"
                if recipes_file.exists():
                    display_name = cuisine_dir.name.replace("_", " ").title()
                    return {"folder": cuisine_dir.name, "display": display_name}
            return None

        # Collect all directory paths
        cuisine_dirs = [item for item in RECIPES_DIR.iterdir()]

        # Process all directories concurrently
        tasks = [check_cuisine_dir(cuisine_dir) for cuisine_dir in cuisine_dirs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter valid results
        cuisines = [result for result in results if isinstance(result, dict) and result is not None]

    # Create a simple markdown list
    content = "# Available Recipe Collections\n\n"
    if cuisines:
        content += f"Found **{len(cuisines)}** recipe collections:\n\n"
        for cuisine in cuisines:
            content += f"- **{cuisine['display']}** (folder: `{cuisine['folder']}`)\n"
        content += f"\n📖 Use `recipes://<folder_name>` to access recipes in that collection.\n"
        content += f"\n💡 Example: `recipes://italian` or `recipes://pasta`\n"
    else:
        content += "No recipe collections found. Search for some recipes first!\n"

    return content


@mcp.resource("recipes://{cuisine}")
async def get_cuisine_recipes(cuisine: str) -> str:
    """
    Get detailed information about recipes in a specific cuisine/dish collection.

    Args:
        cuisine: The cuisine/dish folder name to retrieve recipes for
    """
    cuisine_path = RECIPES_DIR / cuisine
    recipes_file = cuisine_path / "recipes_info.json"

    if not recipes_file.exists():
        return f"# No recipes found for: {cuisine}\n\nTry searching for recipes on this topic first."

    try:
        async with aiofiles.open(recipes_file, "r", encoding="utf-8") as f:
            content = await f.read()
            recipes_data = json.loads(content)

        # Create markdown content with recipe details
        display_name = cuisine.replace("_", " ").title()
        content = f"# {display_name} Recipe Collection\n\n"
        content += f"📚 Total recipes: **{len(recipes_data)}**\n\n"

        for recipe_id, recipe_info in recipes_data.items():
            content += f"## 🍽️ {recipe_info['name']}\n"
            content += f"- **Recipe ID**: `{recipe_id}`\n"
            content += f"- **Cuisine**: {recipe_info.get('cuisine', 'Unknown')}\n"
            content += f"- **Category**: {recipe_info.get('category', 'Unknown')}\n"

            # Add ingredients summary
            ingredients = recipe_info.get("ingredients", [])
            if ingredients:
                content += f"- **Main Ingredients**: {', '.join([ing['ingredient'] for ing in ingredients[:5]])}"
                if len(ingredients) > 5:
                    content += f" (+{len(ingredients)-5} more)"
                content += "\n"

            # Add links if available
            if recipe_info.get("image_url"):
                content += (
                    f"- **Image**: [View Recipe Photo]({recipe_info['image_url']})\n"
                )
            if recipe_info.get("youtube_url"):
                content += (
                    f"- **Video**: [Watch on YouTube]({recipe_info['youtube_url']})\n"
                )

            # Add truncated instructions
            instructions = recipe_info.get("instructions", "No instructions available")
            if len(instructions) > 300:
                content += f"\n### 📋 Instructions Preview\n{instructions[:300]}...\n\n"
            else:
                content += f"\n### 📋 Instructions\n{instructions}\n\n"

            content += "---\n\n"

        content += f"\n💡 **Tip**: Use `get_recipe_details('{list(recipes_data.keys())[0]}')` to get full details for any recipe.\n"

        return content

    except json.JSONDecodeError:
        return f"# Error reading recipes data for {cuisine}\n\nThe recipes data file is corrupted."
    except Exception as e:
        return f"# Error accessing {cuisine} recipes\n\nError: {str(e)}"


@mcp.resource("recipes://meal-plans")
async def get_available_meal_plans() -> str:
    """
    List all available meal plans that have been created.

    This resource provides access to saved meal plans.
    """
    meal_plans_dir = RECIPES_DIR / "meal_plans"

    if not meal_plans_dir.exists():
        return "# No Meal Plans Found\n\nCreate your first meal plan using the `create_meal_plan` tool!"

    # Process meal plan files concurrently
    async def process_meal_plan(plan_file: Path) -> dict | None:
        try:
            async with aiofiles.open(plan_file, "r", encoding="utf-8") as f:
                content = await f.read()
                plan_data = json.loads(content)
                return {
                    "file": plan_file.name,
                    "name": plan_data.get("plan_name", "Unknown Plan"),
                    "recipes": plan_data.get("total_recipes", 0),
                    "created": plan_data.get("created_date", "Unknown"),
                }
        except (json.JSONDecodeError, Exception):
            return None

    # Get all meal plan files and process them concurrently
    plan_files = list(meal_plans_dir.glob("*.json"))
    tasks = [process_meal_plan(plan_file) for plan_file in plan_files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter valid results
    meal_plans = [result for result in results if isinstance(result, dict) and result is not None]

    content = "# 📅 Available Meal Plans\n\n"
    if meal_plans:
        content += f"Found **{len(meal_plans)}** meal plans:\n\n"
        for plan in meal_plans:
            content += f"## 🍽️ {plan['name']}\n"
            content += f"- **Recipes**: {plan['recipes']} dishes\n"
            content += f"- **Created**: {plan['created'][:10] if 'T' in plan['created'] else plan['created']}\n"
            content += f"- **File**: `{plan['file']}`\n\n"
    else:
        content += "No meal plans found. Create your first meal plan!\n"

    return content


@mcp.resource("recipes://stats")
async def get_recipe_statistics() -> str:
    """
    Get overall statistics about the recipe collection.

    This resource provides insights into the recipe database.
    """
    stats = {
        "total_recipes": 0,
        "total_cuisines": 0,
        "cuisines": {},
        "categories": {},
        "meal_plans": 0,
    }

    # Count recipes by cuisine and category using async operations
    if RECIPES_DIR.exists():
        async def process_cuisine_dir(cuisine_dir: Path) -> dict:
            if cuisine_dir.is_dir() and cuisine_dir.name not in ["meal_plans", "by_letter"]:
                recipes_file = cuisine_dir / "recipes_info.json"
                if recipes_file.exists():
                    try:
                        async with aiofiles.open(recipes_file, "r", encoding="utf-8") as f:
                            content = await f.read()
                            recipes_data = json.loads(content)

                        local_stats = {
                            "total_recipes": len(recipes_data),
                            "total_cuisines": 1,
                            "cuisines": {},
                            "categories": {},
                        }

                        # Count by cuisine and category
                        for recipe in recipes_data.values():
                            cuisine = recipe.get("cuisine", "Unknown")
                            category = recipe.get("category", "Unknown")

                            local_stats["cuisines"][cuisine] = local_stats["cuisines"].get(cuisine, 0) + 1
                            local_stats["categories"][category] = local_stats["categories"].get(category, 0) + 1

                        return local_stats

                    except (json.JSONDecodeError, Exception):
                        pass

            return {"total_recipes": 0, "total_cuisines": 0, "cuisines": {}, "categories": {}}

        # Process all cuisine directories concurrently
        cuisine_dirs = [item for item in RECIPES_DIR.iterdir()]
        tasks = [process_cuisine_dir(cuisine_dir) for cuisine_dir in cuisine_dirs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge all results
        for result in results:
            if isinstance(result, dict):
                stats["total_recipes"] += result["total_recipes"]
                stats["total_cuisines"] += result["total_cuisines"]

                # Merge cuisine counts
                for cuisine, count in result["cuisines"].items():
                    stats["cuisines"][cuisine] = stats["cuisines"].get(cuisine, 0) + count

                # Merge category counts
                for category, count in result["categories"].items():
                    stats["categories"][category] = stats["categories"].get(category, 0) + count

    # Count meal plans
    meal_plans_dir = RECIPES_DIR / "meal_plans"
    if meal_plans_dir.exists():
        stats["meal_plans"] = len(list(meal_plans_dir.glob("*.json")))

    # Create markdown content
    content = "# 📊 Recipe Collection Statistics\n\n"
    content += f"## 📈 Overview\n"
    content += f"- **Total Recipes**: {stats['total_recipes']}\n"
    content += f"- **Recipe Collections**: {stats['total_cuisines']}\n"
    content += f"- **Meal Plans**: {stats['meal_plans']}\n\n"

    if stats["cuisines"]:
        content += "## 🌍 Top Cuisines\n"
        sorted_cuisines = sorted(
            stats["cuisines"].items(), key=lambda x: x[1], reverse=True
        )
        for cuisine, count in sorted_cuisines[:10]:
            content += f"- **{cuisine}**: {count} recipes\n"
        content += "\n"

    if stats["categories"]:
        content += "## 🍽️ Recipe Categories\n"
        sorted_categories = sorted(
            stats["categories"].items(), key=lambda x: x[1], reverse=True
        )
        for category, count in sorted_categories[:10]:
            content += f"- **{category}**: {count} recipes\n"
        content += "\n"

    content += (
        "💡 **Tip**: Explore specific collections using `recipes://<cuisine_name>`\n"
    )

    return content


# ==================== PROMPTS ====================
# Prompts provide pre-defined templates for common recipe-related tasks


@mcp.prompt()
async def generate_recipe_search_prompt(cuisine_type: str, num_recipes: int = 5) -> str:
    """Generate a prompt for Claude to find and discuss recipes from a specific cuisine."""
    return f"""Search for {num_recipes} recipes from '{cuisine_type}' cuisine using the async search_recipes tool. Follow these instructions:

1. First, search for recipes using await search_recipes(dish_name='{cuisine_type}', max_results={num_recipes})

2. For each recipe found, extract and organize the following information:
   - Recipe name and ID
   - Cuisine origin and category
   - Key ingredients and their quantities
   - Cooking time and difficulty level
   - Cooking methods and techniques used
   - Nutritional highlights or dietary considerations
   - Cultural significance or traditional context

3. Provide a comprehensive culinary analysis that includes:
   - Overview of {cuisine_type} cuisine characteristics
   - Common ingredients and flavor profiles across the recipes
   - Traditional cooking techniques and methods
   - Regional variations or modern adaptations
   - Most authentic or representative dishes

4. Organize your findings in a clear, structured format with headings and bullet points for easy readability.

Please present both detailed information about each recipe and a high-level understanding of {cuisine_type} culinary traditions."""


@mcp.prompt()
async def generate_meal_planning_prompt(
    meal_type: str, people_count: int = 4, dietary_restrictions: str = "none"
) -> str:
    """Generate a prompt for Claude to create a comprehensive meal plan."""
    return f"""Create a detailed {meal_type} meal plan for {people_count} people with dietary considerations: '{dietary_restrictions}'. Follow these instructions:

1. Search for appropriate recipes using the available search tools, considering:
   - Meal type: {meal_type}
   - Serving size: {people_count} people
   - Dietary restrictions: {dietary_restrictions}

2. For each selected recipe, analyze:
   - Preparation and cooking time
   - Ingredient availability and cost
   - Nutritional balance and dietary compliance
   - Cooking skill level required
   - Equipment and tools needed

3. Create a comprehensive meal planning guide that includes:
   - Complete shopping list with quantities
   - Preparation timeline and cooking schedule
   - Kitchen organization and mise en place tips
   - Nutritional breakdown and balance
   - Cost estimation and budget considerations
   - Alternative ingredients for dietary substitutions

4. Provide practical meal planning advice:
   - Make-ahead preparation tips
   - Storage and leftover suggestions
   - Scaling recipes up or down
   - Time-saving techniques

5. Use await create_meal_plan() to save your final meal plan with an appropriate name.

Present your meal plan in a clear, actionable format that a home cook can easily follow."""


@mcp.prompt()
async def generate_cooking_lesson_prompt(
    skill_level: str, technique_focus: str, cuisine_style: str = "any"
) -> str:
    """Generate a prompt for Claude to create a structured cooking lesson."""
    return f"""Design a comprehensive cooking lesson for a {skill_level} level cook focusing on '{technique_focus}' technique within {cuisine_style} cuisine. Follow these instructions:

1. Search for appropriate recipes that demonstrate the {technique_focus} technique using await search_recipes

2. Structure your lesson to include:
   - Technique explanation and theory
   - Equipment and tools required
   - Step-by-step technique demonstration
   - Common mistakes and how to avoid them
   - Quality indicators and success markers
   - Troubleshooting guide

3. Select recipes that progressively build skills:
   - Start with basic {technique_focus} applications
   - Progress to intermediate variations
   - Include advanced applications for skill building
   - Provide practice exercises and variations

4. Create educational content covering:
   - Historical and cultural context of the technique
   - Science behind the cooking method
   - Ingredient selection and preparation
   - Temperature control and timing
   - Visual and sensory cues for doneness

5. Provide learning objectives and assessment:
   - Clear learning goals for the lesson
   - Practice recommendations
   - Self-assessment criteria
   - Next steps for skill progression

Present your lesson in a structured, educational format suitable for {skill_level} level cooks learning {technique_focus}."""


@mcp.prompt()
async def generate_ingredient_exploration_prompt(
    main_ingredient: str, cooking_styles: str = "diverse", num_recipes: int = 6
) -> str:
    """Generate a prompt for Claude to explore and analyze recipes featuring a specific ingredient."""
    return f"""Conduct a comprehensive exploration of '{main_ingredient}' through {num_recipes} diverse recipes with {cooking_styles} cooking styles. Follow these instructions:

1. Search for recipes featuring {main_ingredient} using available async search tools (await search_recipes, await search_by_first_letter) to find {num_recipes} different preparations

2. For each recipe, analyze the ingredient usage:
   - How {main_ingredient} is prepared and processed
   - Cooking methods applied to {main_ingredient}
   - Flavor pairings and complementary ingredients
   - Cultural or regional preparation differences
   - Nutritional contributions and benefits
   - Texture and appearance transformations

3. Create a comprehensive ingredient profile including:
   - Botanical/biological background of {main_ingredient}
   - Nutritional composition and health benefits
   - Seasonal availability and sourcing tips
   - Storage methods and shelf life
   - Quality selection criteria
   - Common varieties and substitutions

4. Provide culinary technique analysis:
   - Best cooking methods for {main_ingredient}
   - Temperature and timing considerations
   - Preparation techniques and knife skills
   - Flavor enhancement strategies
   - Common cooking mistakes to avoid

5. Synthesize your findings into:
   - Versatility assessment of {main_ingredient}
   - Recipe recommendations for different skill levels
   - Menu planning suggestions
   - Cost-effective usage tips
   - Creative preparation ideas

Present your exploration as an educational ingredient guide that helps cooks understand and maximize the potential of {main_ingredient}."""


@mcp.prompt()
async def generate_cultural_cuisine_prompt(
    cuisine_name: str, cultural_context: str = "traditional", num_recipes: int = 5
) -> str:
    """Generate a prompt for Claude to explore the cultural and historical aspects of a cuisine."""
    return f"""Explore the cultural heritage and culinary traditions of {cuisine_name} cuisine from a {cultural_context} perspective through {num_recipes} representative recipes. Follow these instructions:

1. Search for authentic {cuisine_name} recipes using await search_recipes and await get_recipe_details

2. For each recipe, research and document:
   - Historical origins and cultural significance
   - Traditional preparation methods and rituals
   - Regional variations and family traditions
   - Social and ceremonial context
   - Seasonal and festival associations
   - Evolution and modern adaptations

3. Provide comprehensive cultural analysis including:
   - Geographic influences on {cuisine_name} cuisine
   - Historical trade routes and ingredient introductions
   - Religious and cultural dietary influences
   - Social hierarchy and food accessibility
   - Gender roles and cooking traditions
   - Celebration and hospitality customs

4. Examine culinary techniques and philosophy:
   - Traditional cooking methods and equipment
   - Flavor balance and seasoning principles
   - Ingredient sourcing and preservation methods
   - Meal structure and eating customs
   - Food presentation and aesthetic principles

5. Create educational content covering:
   - Key ingredients native to the region
   - Essential cooking techniques and skills
   - Cultural etiquette and dining customs
   - Modern influence and fusion adaptations
   - Preservation of culinary heritage

Present your exploration as a cultural culinary journey that respects and celebrates the heritage of {cuisine_name} cuisine while providing practical cooking knowledge."""



if __name__ == "__main__":
    # mcp.run()  # Run the MCP server on STDIO
    mcp.run(transport="streamable-http") 
