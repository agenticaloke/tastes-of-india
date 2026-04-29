RUN_INTERVAL_HOURS = 6

# Cities and their search keywords
CITIES = [
    {"slug": "jaipur",     "name": "Jaipur",     "keywords": ["Jaipur", "Rajasthan", "Rajasthani"]},
    {"slug": "kolkata",    "name": "Kolkata",     "keywords": ["Kolkata", "Bengali", "West Bengal"]},
    {"slug": "hyderabad",  "name": "Hyderabad",   "keywords": ["Hyderabad", "Hyderabadi", "Telangana"]},
    {"slug": "indore",     "name": "Indore",      "keywords": ["Indore", "Indori", "Madhya Pradesh"]},
    {"slug": "delhi",      "name": "Delhi",       "keywords": ["Delhi", "Old Delhi", "New Delhi"]},
    {"slug": "bikaner",    "name": "Bikaner",     "keywords": ["Bikaner", "Bikaneri", "Marwari", "Marwar"]},
    {"slug": "bangalore",  "name": "Bangalore",   "keywords": ["Bangalore", "Bengaluru", "Karnataka", "Udupi", "Mangalorean"]},
]

CATEGORIES = ["appetizer", "snack", "starter", "entree", "dessert", "drink"]

# Every search query will include this modifier so we only pick up veg recipes.
VEG_QUERY_MODIFIER = "vegetarian"

# Trusted vegetarian-friendly Indian recipe sites to search.
# Each agent run consults at least MIN_SITES_PER_RUN of these.
TARGET_SITES = [
    "vegrecipesofindia.com",
    "archanaskitchen.com",
    "indianhealthyrecipes.com",
    "cookwithmanali.com",
    "whiskaffair.com",
    "hebbarskitchen.com",
    "spiceupthecurry.com",
    "myfoodstory.com",
    "tarladalal.com",
    "sailusfood.com",
    "cookingandme.com",
    "rakskitchen.net",
    "sharmispassions.com",
    "manjulaskitchen.com",
    "vegetarianindiancooking.com",
]

# How many distinct sites to query in a single run (random sample).
MIN_SITES_PER_RUN = 10

# How many categories to search per (city, site) pair (random sample).
CATEGORIES_PER_SITE = 2

# DuckDuckGo HTML search endpoint (scraper-friendly, no API key needed)
DDG_URL = "https://html.duckduckgo.com/html/"

# Polite delay between HTTP requests (seconds)
REQUEST_DELAY = 2.5

# Max new recipes to add per agent run (safety cap)
MAX_NEW_PER_RUN = 20

# Any recipe whose ingredients/instructions/name contains any of these tokens
# is rejected as non-vegetarian.
NON_VEG_TOKENS = [
    "chicken", "murgh", "murg", "mutton", "lamb", "goat", "beef", "pork", "ham",
    "bacon", "sausage", "salami", "pepperoni", "prosciutto",
    "fish", "macher", "mach ", "ilish", "hilsa", "pomfret", "rohu", "tuna",
    "salmon", "anchovy", "anchovies", "sardine", "mackerel",
    "prawn", "shrimp", "crab", "lobster", "oyster", "clam", "mussel", "squid",
    "octopus", "scallop", "calamari",
    "egg", "eggs", "anda", "omelette", "omelet",
    "gelatin", "gelatine", "lard", "tallow", "suet", "keema", "kheema", "qeema",
    "seekh", "haleem", "nihari", "kebab", "kabab",
]
