
import sys
import os
import json
import logging
import random
from typing import Dict, Any, List, Optional, Union
import datetime

__version__ = "0.1.2"
__updated__ = "2025-06-03"

# Define log path in the logs directory parallel to tools
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
logs_dir = os.path.join(parent_dir, "logs")
os.makedirs(logs_dir, exist_ok=True)

# Configure logging to file in the logs directory
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, "character_saver.log"))
    ]
)
logger = logging.getLogger("character_saver")

# Import MCP server
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("character-saver-server")

# Define the default character save location (Codex-friendly override)
# Priority:
# 1) CODEX_CHAR_DIR env var (explicit override)
# 2) /opt/codex-home/.codex/characters inside container
# 3) Fallback to host-specific Claude config

def get_claude_config_dir():
    """Get the character storage directory, preferring Codex paths when available."""
    # Explicit override
    override = os.environ.get("CODEX_CHAR_DIR")
    if override:
        os.makedirs(override, exist_ok=True)
        return override

    # Codex container default
    codex_default = "/opt/codex-home/.codex/characters"
    try:
        os.makedirs(codex_default, exist_ok=True)
        return codex_default
    except Exception:
        pass

    # Host fallbacks
    if sys.platform == "win32":
        config_dir = os.path.join(os.environ.get("APPDATA", ""), "Claude")
    elif sys.platform == "darwin":  # macOS
        config_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Claude")
    else:  # Linux and others
        config_dir = os.path.join(os.path.expanduser("~"), ".config", "claude")
    os.makedirs(config_dir, exist_ok=True)
    return config_dir

def get_character_save_file():
    """Get the path to the character save file."""
    config_dir = get_claude_config_dir()
    return os.path.join(config_dir, "saved_characters.json")

def load_saved_characters():
    """Load saved characters from the config file."""
    save_file = get_character_save_file()
    if not os.path.exists(save_file):
        logger.info(f"No save file found at {save_file}, creating empty character database")
        return {"characters": [], "collections": {}}
    
    try:
        with open(save_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            logger.info(f"Loaded {len(data.get('characters', []))} characters from {save_file}")
            return data
    except Exception as e:
        logger.error(f"Error loading character save file: {str(e)}")
        return {"characters": [], "collections": {}}

def save_characters_to_file(data):
    """Save character data to the config file."""
    save_file = get_character_save_file()
    
    try:
        with open(save_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            logger.info(f"Saved {len(data.get('characters', []))} characters to {save_file}")
        return True
    except Exception as e:
        logger.error(f"Error saving character data: {str(e)}")
        return False

@mcp.tool()
async def save_character(
    character: Dict[str, Any],
    collection_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Saves a character to the configuration file.
    
    Args:
        character: Character data dictionary to save
        collection_name: Optional name of a collection to add the character to
        
    Returns:
        Dictionary with save operation results
    """
    logger.info(f"Saving character: {character.get('name', 'Unknown')} to collection: {collection_name}")
    
    # Define valid emotional states for validation
    valid_emotions = ["Joy", "Trust", "Fear", "Surprise", "Sadness", "Boredom", "Anger", "Interest"]
    
    # Validate character data with detailed error messages
    validation_errors = []
    
    # Check required field: name
    if "name" not in character:
        validation_errors.append("Missing required field 'name'")
    elif not isinstance(character["name"], str) or not character["name"].strip():
        validation_errors.append("Field 'name' must be a non-empty string")
    
    # Check required field: emotional_state
    if "emotional_state" not in character:
        validation_errors.append("Missing required field 'emotional_state'")
    else:
        emotional_state = character["emotional_state"]
        if not isinstance(emotional_state, dict):
            validation_errors.append("Field 'emotional_state' must be a dictionary with 'primary' and 'secondary' keys")
        else:
            if "primary" not in emotional_state:
                validation_errors.append("Missing 'primary' emotion in emotional_state")
            elif emotional_state["primary"] not in valid_emotions:
                validation_errors.append(f"Invalid primary emotion '{emotional_state['primary']}'. Valid emotions: {', '.join(valid_emotions)}")
            
            if "secondary" not in emotional_state:
                validation_errors.append("Missing 'secondary' emotion in emotional_state")
            elif emotional_state["secondary"] not in valid_emotions:
                validation_errors.append(f"Invalid secondary emotion '{emotional_state['secondary']}'. Valid emotions: {', '.join(valid_emotions)}")
    
    # Return detailed validation errors if any
    if validation_errors:
        logger.error(f"Character validation failed: {validation_errors}")
        return {
            "success": False,
            "error": "Character validation failed",
            "message": "Invalid character data - see validation_errors for details",
            "validation_errors": validation_errors,
            "required_structure": {
                "name": "string (required)",
                "emotional_state": {
                    "primary": f"one of: {', '.join(valid_emotions)}",
                    "secondary": f"one of: {', '.join(valid_emotions)}"
                },
                "trait": "string (optional)",
                "any_other_fields": "flexible key-value pairs welcome!"
            },
            "example": {
                "name": "Trek",
                "emotional_state": {"primary": "Interest", "secondary": "Surprise"},
                "trait": "Reality-Seeker",
                "role": "CTO",
                "custom_field": "any_value_you_want"
            }
        }


    
    # Load existing data
    data = load_saved_characters()
    
    # Add timestamp to character data
    character["saved_timestamp"] = datetime.datetime.now().isoformat()
    
    # Check if this character already exists (by ID if present, or by name)
    existing_index = None
    for i, existing_char in enumerate(data["characters"]):
        if "id" in character and "id" in existing_char and character["id"] == existing_char["id"]:
            existing_index = i
            break
        elif character["name"] == existing_char["name"]:
            existing_index = i
            break
    
    # Update or append character
    if existing_index is not None:
        data["characters"][existing_index] = character
        logger.info(f"Updated existing character: {character.get('name')}")
    else:
        # Generate an ID if not present
        if "id" not in character:
            character["id"] = f"CHAR_{len(data['characters'])+1:03d}"
        data["characters"].append(character)
        logger.info(f"Added new character: {character.get('name')}")
    
    # Handle collection association
    if collection_name:
        if "collections" not in data:
            data["collections"] = {}
        
        if collection_name not in data["collections"]:
            data["collections"][collection_name] = []
        
        # Add to collection if not already there
        if character["id"] not in data["collections"][collection_name]:
            data["collections"][collection_name].append(character["id"])
            logger.info(f"Added character {character.get('name')} to collection {collection_name}")
    
    # Save the updated data
    if save_characters_to_file(data):
        return {
            "success": True,
            "message": f"Character {character.get('name')} saved successfully",
            "character": character,
            "collection": collection_name,
            "save_location": get_character_save_file()
        }
    else:
        return {
            "success": False,
            "error": "Failed to save character data",
            "message": "An error occurred while writing to the save file"
        }

@mcp.tool()
async def load_character(
    character_id: Optional[str] = None,
    character_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Loads a specific character from the save file.
    
    Args:
        character_id: ID of the character to load
        character_name: Name of the character to load (used if ID not provided)
        
    Returns:
        Dictionary with the loaded character data
    """
    logger.info(f"Loading character with ID: {character_id} or name: {character_name}")
    
    if not character_id and not character_name:
        logger.error("No character ID or name provided")
        return {
            "success": False,
            "error": "Missing identifier",
            "message": "Either character_id or character_name must be provided"
        }
    
    # Load saved data
    data = load_saved_characters()
    
    # Search for the character
    character = None
    for char in data["characters"]:
        if character_id and char.get("id") == character_id:
            character = char
            break
        elif character_name and char.get("name") == character_name:
            character = char
            break
    
    if character:
        logger.info(f"Found character: {character.get('name')}")
        return {
            "success": True,
            "character": character,
            "message": f"Character {character.get('name')} loaded successfully"
        }
    else:
        logger.warning(f"Character not found with ID: {character_id} or name: {character_name}")
        return {
            "success": False,
            "error": "Character not found",
            "message": f"No character found with ID: {character_id} or name: {character_name}"
        }

@mcp.tool()
async def list_characters(
    collection_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Lists all saved characters or those in a specific collection.
    
    Args:
        collection_name: Optional collection name to filter characters
        
    Returns:
        Dictionary with a list of character summaries
    """
    logger.info(f"Listing characters in collection: {collection_name if collection_name else 'all'}")
    
    # Load saved data
    data = load_saved_characters()
    
    # Filter by collection if specified
    if collection_name:
        if "collections" not in data or collection_name not in data["collections"]:
            logger.warning(f"Collection not found: {collection_name}")
            return {
                "success": False,
                "error": "Collection not found",
                "message": f"No collection named '{collection_name}' exists"
            }
        
        # Get characters in this collection
        collection_ids = data["collections"][collection_name]
        characters = [char for char in data["characters"] if char.get("id") in collection_ids]
    else:
        characters = data["characters"]
    
    # Create summary list with essential info
    character_summaries = [
        {
            "id": char.get("id", ""),
            "name": char.get("name", "Unknown"),
            "saved_timestamp": char.get("saved_timestamp", ""),
            "primary_emotion": char.get("emotional_state", {}).get("primary", "Unknown"),
            "trait": char.get("trait", char.get("quirk", ""))
        }
        for char in characters
    ]

    
    logger.info(f"Found {len(character_summaries)} characters")
    return {
        "success": True,
        "characters": character_summaries,
        "count": len(character_summaries),
        "collection": collection_name,
        "collections": list(data.get("collections", {}).keys()),
        "save_location": get_character_save_file()
    }

@mcp.tool()
async def create_collection(
    collection_name: str,
    character_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Creates a new character collection.
    
    Args:
        collection_name: Name for the new collection
        character_ids: Optional list of character IDs to add to the collection
        
    Returns:
        Dictionary with collection creation results
    """
    logger.info(f"Creating collection: {collection_name} with characters: {character_ids}")
    
    if not collection_name:
        logger.error("No collection name provided")
        return {
            "success": False,
            "error": "Missing collection name",
            "message": "A name must be provided for the new collection"
        }
    
    # Load saved data
    data = load_saved_characters()
    
    # Initialize collections if needed
    if "collections" not in data:
        data["collections"] = {}
    
    # Check if collection already exists
    if collection_name in data["collections"]:
        logger.warning(f"Collection already exists: {collection_name}")
        return {
            "success": False,
            "error": "Collection exists",
            "message": f"A collection named '{collection_name}' already exists"
        }
    
    # Create new collection
    data["collections"][collection_name] = []
    
    # Add characters if provided
    if character_ids:
        # Verify character IDs exist
        valid_ids = [char.get("id") for char in data["characters"]]
        for char_id in character_ids:
            if char_id in valid_ids:
                data["collections"][collection_name].append(char_id)
            else:
                logger.warning(f"Invalid character ID: {char_id}")
    
    # Save the updated data
    if save_characters_to_file(data):
        return {
            "success": True,
            "message": f"Collection '{collection_name}' created successfully",
            "collection": collection_name,
            "character_count": len(data["collections"][collection_name]),
            "save_location": get_character_save_file()
        }
    else:
        return {
            "success": False,
            "error": "Failed to save collection data",
            "message": "An error occurred while writing to the save file"
        }

if __name__ == "__main__":
    logger.info("Starting Character Saver MCP server")
    mcp.run(transport='stdio')
