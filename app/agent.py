# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import math
import os
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from dotenv import load_dotenv
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from app.a2ui_utils import a2ui_callback

load_dotenv()

# Hardcoded project ID and GCS bucket name as required
PROJECT_ID = "qwiklabs-gcp-02-ff416e0c2cdc"
BUCKET_NAME = "wanderlust-assets-qwiklabs-gcp-02-ff416e0c2cdc"

# Load Agent Engine resource name from deployment_metadata.json if available
deployment_metadata_path = os.path.join(
    os.path.dirname(__file__), "..", "deployment_metadata.json"
)
agent_engine_resource_name = None
if os.path.exists(deployment_metadata_path):
    try:
        with open(deployment_metadata_path, "r") as f:
            metadata = json.load(f)
            agent_engine_resource_name = metadata.get("remote_agent_runtime_id")
    except Exception:
        pass

# Initialize Agent Engine Sandbox Code Executor for safe Python execution
code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=agent_engine_resource_name
)


async def generate_memories_callback(callback_context: CallbackContext):
    """Sends session event history to Vertex AI Memory Bank for long-term facts and allergy extraction."""
    await callback_context.add_session_to_memory()
    return None


async def generate_destination_image(
    prompt: str,
    tool_context: ToolContext,
) -> str:
    """Generates a travel image for a destination using gemini-3.1-flash-lite-image in global region, saves it as an artifact, and uploads it to public Cloud Storage.

    Args:
        prompt: Description of the travel destination or attraction image to generate (e.g. "Sunset over Senso-ji Temple in Tokyo").
        tool_context: ADK tool execution context provided automatically by the framework.

    Returns:
        Public HTTPS URL of the uploaded image in Cloud Storage.
    """
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=f"Generate a vivid travel photo of: {prompt}",
        )

        image_bytes = None
        mime_type = "image/jpeg"
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    image_bytes = part.inline_data.data
                    mime_type = part.inline_data.mime_type or "image/jpeg"
                    break

        if not image_bytes:
            return "Error: Model did not return any image data."

        filename = f"destination_{uuid.uuid4().hex[:8]}.jpg"

        # 1. Save artifact to Playground's Artifacts panel (awaited)
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        await tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload same image bytes directly to public Cloud Storage bucket
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"images/{filename}")
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/images/{filename}"
        return public_url
    except Exception as e:
        return f"Error generating travel image: {e}"


def geocode_address(address: str) -> dict:
    """Geocodes an address or landmark name into geographic coordinates using Google Geocoding API.

    Args:
        address: Address, location, or landmark name (e.g. "Shibuya Crossing, Tokyo" or "Eiffel Tower").

    Returns:
        Dictionary containing name/query, formatted address, and location (latitude and longitude).
    """
    try:
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            return {"error": "GOOGLE_MAPS_API_KEY is not set in environment."}

        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "WanderlustConcierge/1.0"})

        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status != 200:
                return {"error": f"Geocoding API returned HTTP {response.status}"}
            data = json.loads(response.read().decode())

            if data.get("status") != "OK" or not data.get("results"):
                return {"error": f"Geocoding failed with status: {data.get('status')}"}

            result = data["results"][0]
            loc = result.get("geometry", {}).get("location", {})
            return {
                "query": address,
                "formatted_address": result.get("formatted_address"),
                "location": {
                    "latitude": loc.get("lat"),
                    "longitude": loc.get("lng"),
                },
            }
    except Exception as e:
        return {"error": f"Failed to geocode address: {e}"}


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "tourist_attraction",
    radius_meters: float = 2000.0,
    max_results: int = 5,
) -> list[dict]:
    """Finds nearby places of a specified type near coordinates using Google Places API (New).

    Args:
        latitude: Center latitude coordinate.
        longitude: Center longitude coordinate.
        place_type: Type of place to find, e.g. "tourist_attraction", "restaurant", "museum", "cafe".
        radius_meters: Search radius in meters (default 2000m).
        max_results: Maximum number of places to return (default 5).

    Returns:
        List of nearby places with name, formatted address, location, and rating.
    """
    try:
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            return [{"error": "GOOGLE_MAPS_API_KEY is not set in environment."}]

        url = "https://places.googleapis.com/v1/places:searchNearby"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.rating",
        }
        body = json.dumps({
            "includedTypes": [place_type],
            "maxResultCount": max(1, min(20, int(max_results))),
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": float(latitude),
                        "longitude": float(longitude),
                    },
                    "radius": float(radius_meters),
                }
            },
        }).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status != 200:
                return [{"error": f"Places API returned HTTP {response.status}"}]
            data = json.loads(response.read().decode())

            places_list = []
            for item in data.get("places", []):
                loc = item.get("location", {})
                places_list.append({
                    "name": item.get("displayName", {}).get("text", "Unknown"),
                    "address": item.get("formattedAddress", "N/A"),
                    "location": {
                        "latitude": loc.get("latitude"),
                        "longitude": loc.get("longitude"),
                    },
                    "rating": item.get("rating"),
                })
            return places_list
    except Exception as e:
        return [{"error": f"Failed to search nearby places: {e}"}]


def search_destinations(country: str = None, tag: str = None, max_daily_budget_usd: float = None) -> list[dict]:
    """Searches travel destinations stored in Firestore database.

    Args:
        country: Optional country name filter (e.g. "Japan", "France").
        tag: Optional category tag filter (e.g. "culture", "beach", "food", "art").
        max_daily_budget_usd: Optional maximum average daily cost filter in USD.

    Returns:
        List of matching destination documents.
    """
    try:
        db = firestore.Client(project=PROJECT_ID)
        docs = db.collection("destinations").stream()
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id

            if country and country.lower() not in data.get("country", "").lower():
                continue
            if tag and tag.lower() not in [t.lower() for t in data.get("tags", [])]:
                continue
            if max_daily_budget_usd is not None and data.get("avg_daily_cost_usd", 0) > max_daily_budget_usd:
                continue

            results.append(data)
        return results
    except Exception as e:
        return [{"error": f"Failed to search destinations in Firestore: {e}"}]


def add_destination(
    city: str,
    country: str,
    description: str,
    best_season: str,
    avg_daily_cost_usd: float,
    tags: list[str],
    popular_attractions: list[str],
) -> str:
    """Adds or updates a travel destination in the Firestore database.

    Args:
        city: City or destination name (e.g. "Rome").
        country: Country name (e.g. "Italy").
        description: Brief overview of the destination.
        best_season: Best time of year to visit.
        avg_daily_cost_usd: Estimated average daily travel budget in USD.
        tags: List of descriptive tags, e.g. ["history", "food", "art"].
        popular_attractions: Key sights and attractions.

    Returns:
        Status message confirming document addition.
    """
    try:
        db = firestore.Client(project=PROJECT_ID)
        doc_id = f"{city.lower().replace(' ', '-')}-{country.lower().replace(' ', '-')}"
        data = {
            "id": doc_id,
            "city": city,
            "country": country,
            "description": description,
            "best_season": best_season,
            "avg_daily_cost_usd": float(avg_daily_cost_usd),
            "tags": tags,
            "popular_attractions": popular_attractions,
        }
        db.collection("destinations").document(doc_id).set(data)
        return f"Successfully saved destination '{city}, {country}' to Firestore (ID: {doc_id})."
    except Exception as e:
        return f"Error saving destination to Firestore: {e}"


def get_exchange_rates(from_currency: str = "USD", to_currencies: str = "JPY,EUR,GBP,CAD,AUD") -> dict:
    """Fetches real live foreign exchange rates for travel currency conversion from Frankfurter Public API.

    Args:
        from_currency: Base currency 3-letter ISO code (e.g. "USD", "EUR").
        to_currencies: Comma-separated list of target currency ISO codes (e.g. "JPY,EUR,GBP").

    Returns:
        Dictionary containing real live exchange rates and publication date.
    """
    try:
        base = from_currency.strip().upper()
        targets = ",".join([c.strip().upper() for c in to_currencies.split(",") if c.strip()])
        url = f"https://api.frankfurter.app/latest?from={base}&to={targets}"

        req = urllib.request.Request(url, headers={"User-Agent": "WanderlustConcierge/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status != 200:
                return {"error": f"Currency API returned status {response.status}"}
            data = json.loads(response.read().decode())
            return {
                "base_currency": data.get("base", base),
                "date": data.get("date"),
                "rates": data.get("rates", {}),
            }
    except Exception as e:
        return {"error": f"Failed to fetch exchange rates: {e}"}


def calculate_trip_budget_breakdown(
    num_days: int,
    avg_daily_cost_usd: float,
    num_travelers: int = 1,
    flight_cost_usd: float = 0.0,
    contingency_percent: float = 10.0,
) -> dict:
    """Calculates an itemized budget breakdown for a trip.

    Args:
        num_days: Total number of days for the trip.
        avg_daily_cost_usd: Estimated average daily cost per person in USD (lodging, dining, activities).
        num_travelers: Total number of people traveling together.
        flight_cost_usd: Estimated round-trip flight or transit cost per person in USD.
        contingency_percent: Percentage buffer to add for unexpected expenses (default 10%).

    Returns:
        Dictionary containing itemized daily and total trip cost estimates.
    """
    try:
        num_days = max(1, int(num_days))
        num_travelers = max(1, int(num_travelers))

        lodging_usd = round(avg_daily_cost_usd * 0.45, 2)
        dining_usd = round(avg_daily_cost_usd * 0.30, 2)
        activities_usd = round(avg_daily_cost_usd * 0.15, 2)
        local_transit_usd = round(avg_daily_cost_usd * 0.10, 2)

        daily_subtotal_all_travelers = round(avg_daily_cost_usd * num_days * num_travelers, 2)
        total_flights_all_travelers = round(float(flight_cost_usd) * num_travelers, 2)
        subtotal = daily_subtotal_all_travelers + total_flights_all_travelers

        contingency_usd = round(subtotal * (float(contingency_percent) / 100.0), 2)
        grand_total_usd = round(subtotal + contingency_usd, 2)
        cost_per_person = round(grand_total_usd / num_travelers, 2)

        return {
            "num_days": num_days,
            "num_travelers": num_travelers,
            "daily_per_person_breakdown_usd": {
                "lodging_accommodation": lodging_usd,
                "dining_food": dining_usd,
                "sightseeing_activities": activities_usd,
                "local_transportation": local_transit_usd,
                "total_daily": avg_daily_cost_usd,
            },
            "total_trip_summary_usd": {
                "total_daily_living_costs": daily_subtotal_all_travelers,
                "total_flights_transit": total_flights_all_travelers,
                "contingency_buffer": contingency_usd,
                "grand_total_trip_cost": grand_total_usd,
                "cost_per_person": cost_per_person,
            },
        }
    except Exception as e:
        return {"error": f"Error calculating budget breakdown: {e}"}


def calculate(expression: str) -> str:
    """Evaluates a mathematical expression safely.

    Args:
        expression: A mathematical expression string, e.g. "12 * 15 + 42" or "math.sqrt(144)".

    Returns:
        The evaluated result as a string.
    """
    try:
        allowed_names = {"math": math, "abs": abs, "round": round, "pow": pow}
        result = eval(expression, {"__builtins__": None}, allowed_names)
        return f"Result: {result}"
    except Exception as e:
        return f"Error evaluating expression: {e}"


def get_weather(location: str) -> str:
    """Gets current weather for a location.

    Args:
        location: City or location name.

    Returns:
        Weather report string.
    """
    loc = location.lower()
    if "san francisco" in loc or "sf" in loc:
        return "San Francisco: 62°F, Partly Cloudy with coastal fog."
    elif "tokyo" in loc:
        return "Tokyo: 22°C, Clear and pleasant."
    elif "london" in loc:
        return "London: 16°C, Mild rain showers."
    elif "new york" in loc or "nyc" in loc:
        return "New York: 75°F, Sunny."
    return f"{location}: 70°F, Clear skies."


# Generate A2UI system prompt using A2uiSchemaManager (version 0.8) and BasicCatalog
schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are Wanderlust Travel Concierge, a helpful AI assistant for travel planning. "
        "CRITICAL SAFETY REQUIREMENT: You must carefully remember, track, and respect ALL user food allergies, "
        "dietary restrictions (e.g. peanuts, tree nuts, shellfish, gluten, dairy, vegan), and health preferences "
        "across all sessions using Vertex AI Memory Bank. When making travel, dining, or itinerary recommendations, "
        "always cross-check against saved user allergies and explicitly highlight safe options or allergen warnings."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=code_executor,
    instruction=a2ui_instruction,
    tools=[
        PreloadMemoryTool(),
        generate_destination_image,
        geocode_address,
        find_nearby_places,
        search_destinations,
        add_destination,
        get_exchange_rates,
        calculate_trip_budget_breakdown,
        calculate,
        get_weather,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
