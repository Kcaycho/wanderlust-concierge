import os
from google.cloud import firestore

# Hardcoded GCP Project ID for Firestore client
PROJECT_ID = "qwiklabs-gcp-02-ff416e0c2cdc"


def seed_database():
    db = firestore.Client(project=PROJECT_ID)
    destinations = [
        {
            "id": "tokyo-japan",
            "city": "Tokyo",
            "country": "Japan",
            "description": "A bustling metropolis blending ultra-modern skyscrapers with historic temples, world-class cuisine, and vibrant neighborhoods.",
            "best_season": "Spring / Autumn",
            "avg_daily_cost_usd": 150.0,
            "tags": ["culture", "food", "city", "shopping"],
            "popular_attractions": ["Senso-ji Temple", "Shibuya Crossing", "Meiji Shrine", "Tokyo Skytree"],
        },
        {
            "id": "kyoto-japan",
            "city": "Kyoto",
            "country": "Japan",
            "description": "Japan's cultural capital known for classical Buddhist temples, gardens, imperial palaces, Shinto shrines, and traditional wooden houses.",
            "best_season": "Spring / Autumn",
            "avg_daily_cost_usd": 130.0,
            "tags": ["culture", "history", "nature", "temples"],
            "popular_attractions": ["Fushimi Inari Shrine", "Kinkaku-ji (Golden Pavilion)", "Arashiyama Bamboo Grove"],
        },
        {
            "id": "paris-france",
            "city": "Paris",
            "country": "France",
            "description": "A global center for art, fashion, gastronomy, and culture with iconic landmarks like the Eiffel Tower and Louvre Museum.",
            "best_season": "Spring / Summer",
            "avg_daily_cost_usd": 180.0,
            "tags": ["art", "romance", "food", "museums"],
            "popular_attractions": ["Eiffel Tower", "Louvre Museum", "Notre-Dame Cathedral", "Arc de Triomphe"],
        },
        {
            "id": "bali-indonesia",
            "city": "Bali",
            "country": "Indonesia",
            "description": "An Indonesian island known for its forested volcanic mountains, iconic rice paddies, beaches, and coral reefs.",
            "best_season": "Dry Season (April - October)",
            "avg_daily_cost_usd": 75.0,
            "tags": ["beach", "nature", "wellness", "budget"],
            "popular_attractions": ["Ubud Monkey Forest", "Uluwatu Temple", "Tegallalang Rice Terraces"],
        },
        {
            "id": "new-york-usa",
            "city": "New York",
            "country": "USA",
            "description": "The Big Apple offers Broadway shows, world-famous museums, diverse dining, Central Park, and iconic skyline views.",
            "best_season": "Autumn / Spring",
            "avg_daily_cost_usd": 220.0,
            "tags": ["city", "shopping", "entertainment", "culture"],
            "popular_attractions": ["Statue of Liberty", "Central Park", "Times Square", "Empire State Building"],
        },
    ]

    print(f"Seeding Firestore collection 'destinations' in project: {PROJECT_ID}...")
    for item in destinations:
        doc_ref = db.collection("destinations").document(item["id"])
        doc_ref.set(item)
        print(f"  ✓ Added/Updated destination: {item['city']}, {item['country']}")

    print("Firestore seeding complete!")


if __name__ == "__main__":
    seed_database()
