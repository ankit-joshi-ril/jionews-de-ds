"""
Shared constants for all feed validators.
"""

# Language name → numeric ID mapping (used across JioNews pipelines)
LANGUAGE_ID_MAP = {
    "English": 1, "Hindi": 2, "Gujarati": 3, "Marathi": 4,
    "Telugu": 5, "Tamil": 6, "Bangla": 7, "Urdu": 8,
    "Kannada": 9, "Malayalam": 10, "Odia": 11, "Punjabi": 12,
    "Assamese": 13,
}

# Valid content categories
VALID_CATEGORIES = [
    "Agro", "Astrology", "Auto", "Automobile", "Business",
    "Career", "Education", "Entertainment", "Health",
    "India", "National", "International", "World",
    "Latest News", "Top News", "Lifestyle", "Fashion",
    "Sci and Tech", "Sports", "Cricket",
]

# YouTube domain patterns (used for video feed validation)
YOUTUBE_DOMAINS = {"youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com"}

# Streaming platform domains (non-MP4 sources)
STREAMING_DOMAINS = {"vimeo.com", "dailymotion.com"}

# Valid MP4 file type brands (ftyp box)
MP4_FTYP_BRANDS = {b"isom", b"iso2", b"avc1", b"mp41", b"mp42", b"M4V ", b"M4A ", b"f4v ", b"kddi", b"MSNV"}
