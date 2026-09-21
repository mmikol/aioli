"""Fixtures invented to the shape of the API, because the real thing may not be kept.

The usual move is to record a live response and replay it. The terms forbid
exactly that - recipe data may not be held past the hour - and a fixture is a
place data gets held for years (docs/db.md). So every recipe below is made up:
the titles, the ingredients and the method are written here and belong to
nobody. They are wrong in every particular except the one that matters, which
is the shape.

What keeps them honest is `shape_errors`, the comparator the unit tests use
against these and the contract test uses against the live service. It reads
keys and types and never values, so it can say the service renamed a field
without anything true about a recipe being written down.
"""
import io
import json
from urllib.error import HTTPError

# Words that mark a fixture as ours. A response pasted in from the service
# would carry none of them, which is what the test asserting them is for.
SYNTHETIC_MARKERS = ("fictional", "notional", "invented", "imaginary", "pretend",
                     "make-believe")

# The guard is closed by default: every string in a fixture is assumed to be a
# recipe's own words unless its key is on the list below. An allow-list of
# keys-that-must-be-invented was the first shape and it was the wrong one - it
# passed over `summary` and `localizedName`, which the fixtures already carry
# and which are the service's own prose, so a pasted live response would have
# sailed through the one test standing between it and a public repo. A field
# the service adds tomorrow now fails closed rather than slipping past unread.
#
# What is exempt is vocabulary rather than authorship: an aisle, a unit, a
# media type, a diet. "Skillet" is the word for a skillet, and a canned-goods
# aisle is a supermarket's word, not a recipe's.
TAXONOMY_KEYS = frozenset((
    "aisle", "unit", "unitLong", "unitShort", "consistency", "imageType",
    "image", "sourceUrl", "sourceName", "creditsText", "license", "name",
    "dishTypes", "diets", "cuisines", "occasions", "equipment",
))


def _ingredient(ingredient_id, name, amount, unit, original, aisle):
    """One line of a recipe's ingredients, as search returns it."""
    return {
        "id": ingredient_id,
        "aisle": aisle,
        "image": f"https://example.invalid/{name.replace(' ', '-')}.jpg",
        "name": name,
        "amount": amount,
        "unit": unit,
        "unitLong": unit,
        "unitShort": unit,
        "original": original,
        "originalName": name,
        "meta": [],
    }


NOTIONAL_CHICKPEAS = _ingredient(
    10001, "notional chickpeas", 1.0, "can", "1 can of notional chickpeas", "Canned and Jarred")
INVENTED_LEMON = _ingredient(
    10002, "invented lemon", 1.0, "", "1 invented lemon, zest and juice", "Produce")
PRETEND_OLIVE_OIL = _ingredient(
    10003, "pretend olive oil", 2.0, "tbsp", "2 tbsp pretend olive oil",
    "Oil, Vinegar, Salad Dressing")
IMAGINARY_PARSLEY = _ingredient(
    10004, "imaginary parsley", 0.25, "cup", "1/4 cup chopped imaginary parsley", "Produce")
MAKE_BELIEVE_RICE = _ingredient(
    10005, "make-believe rice", 1.5, "cups", "1 1/2 cups make-believe rice", "Pasta and Rice")

# A complexSearch answer with fillIngredients on, which is the call the planner
# makes: used, missed and unused are what it scores the pantry with.
COMPLEX_SEARCH = {
    "results": [
        {
            "id": 9001,
            "title": "Fictional Chickpea and Notional Lemon Skillet",
            "image": "https://example.invalid/fictional-skillet.jpg",
            "imageType": "jpg",
            "usedIngredientCount": 2,
            "missedIngredientCount": 1,
            "usedIngredients": [NOTIONAL_CHICKPEAS, PRETEND_OLIVE_OIL],
            "missedIngredients": [INVENTED_LEMON],
            "unusedIngredients": [MAKE_BELIEVE_RICE],
            "likes": 0,
        },
        {
            "id": 9002,
            "title": "Invented Lentil Stew with Imaginary Herbs",
            "image": "https://example.invalid/invented-stew.jpg",
            "imageType": "jpg",
            "usedIngredientCount": 1,
            "missedIngredientCount": 2,
            "usedIngredients": [PRETEND_OLIVE_OIL],
            "missedIngredients": [IMAGINARY_PARSLEY, MAKE_BELIEVE_RICE],
            "unusedIngredients": [],
            "likes": 0,
        },
    ],
    "offset": 0,
    "number": 2,
    "totalResults": 2,
}

# The same call with addRecipeNutrition on. Nutrition is shown and not scored,
# so it rides along only when something is going to display it.
COMPLEX_SEARCH_WITH_NUTRITION = {
    "results": [
        dict(COMPLEX_SEARCH["results"][0], nutrition={
            "nutrients": [
                {"name": "Calories", "amount": 612.0, "unit": "kcal", "percentOfDailyNeeds": 30.6},
                {"name": "Protein", "amount": 21.0, "unit": "g", "percentOfDailyNeeds": 42.0},
                {"name": "Fat", "amount": 18.5, "unit": "g", "percentOfDailyNeeds": 28.4},
                {"name": "Carbohydrates", "amount": 88.0, "unit": "g", "percentOfDailyNeeds": 29.3},
            ],
        }),
    ],
    "offset": 0,
    "number": 1,
    "totalResults": 1,
}

# findByIngredients, the second pass. A bare list rather than an envelope,
# which is the difference the client's point arithmetic has to know about.
FIND_BY_INGREDIENTS = [
    {
        "id": 9003,
        "title": "Pretend Pantry Noodles with Make-Believe Greens",
        "image": "https://example.invalid/pretend-noodles.jpg",
        "imageType": "jpg",
        "usedIngredientCount": 3,
        "missedIngredientCount": 1,
        "usedIngredients": [NOTIONAL_CHICKPEAS, PRETEND_OLIVE_OIL, MAKE_BELIEVE_RICE],
        "missedIngredients": [IMAGINARY_PARSLEY],
        "unusedIngredients": [],
        "likes": 12,
    },
]

# What the stove asks for: the method, and the ready time the cadence sums.
INFORMATION = {
    "id": 9001,
    "title": "Fictional Chickpea and Notional Lemon Skillet",
    "image": "https://example.invalid/fictional-skillet.jpg",
    "imageType": "jpg",
    "readyInMinutes": 35,
    "servings": 4,
    "sourceUrl": "https://example.invalid/recipes/fictional-skillet",
    "vegetarian": True,
    "vegan": False,
    "glutenFree": True,
    "dairyFree": True,
    "aggregateLikes": 0,
    "healthScore": 61.0,
    "pricePerServing": 187.5,
    "cuisines": [],
    "dishTypes": ["lunch", "main course", "dinner"],
    "diets": ["gluten free", "dairy free", "vegetarian"],
    "occasions": [],
    "summary": "A pretend skillet supper invented for a test suite.",
    "instructions": "Warm the pretend olive oil. Add the notional chickpeas and cook until "
                    "they colour. Finish with the invented lemon and the imaginary parsley.",
    "analyzedInstructions": [
        {
            "name": "",
            "steps": [
                {
                    "number": 1,
                    "step": "Warm the pretend olive oil in a skillet over a medium heat.",
                    "ingredients": [
                        {"id": 10003, "name": "pretend olive oil",
                         "localizedName": "pretend olive oil",
                         "image": "https://example.invalid/pretend-olive-oil.jpg"},
                    ],
                    "equipment": [
                        {"id": 20001, "name": "frying pan", "localizedName": "notional frying pan",
                         "image": "https://example.invalid/frying-pan.jpg"},
                    ],
                },
                {
                    "number": 2,
                    "step": "Add the notional chickpeas and the invented lemon zest; cook"
                            " for ten minutes.",
                    "ingredients": [
                        {"id": 10001, "name": "notional chickpeas",
                         "localizedName": "notional chickpeas",
                         "image": "https://example.invalid/notional-chickpeas.jpg"},
                    ],
                    "equipment": [],
                },
            ],
        },
    ],
    "extendedIngredients": [
        dict(NOTIONAL_CHICKPEAS, consistency="SOLID", measures={
            "us": {"amount": 1.0, "unitShort": "can", "unitLong": "can"},
            "metric": {"amount": 1.0, "unitShort": "can", "unitLong": "can"},
        }),
        dict(PRETEND_OLIVE_OIL, consistency="LIQUID", measures={
            "us": {"amount": 2.0, "unitShort": "Tbsps", "unitLong": "Tbsps"},
            "metric": {"amount": 2.0, "unitShort": "Tbsps", "unitLong": "Tbsps"},
        }),
    ],
}

# What a spent day looks like coming back. The client turns this into its own
# error type; the body is here so a test does not have to invent one inline.
QUOTA_EXHAUSTED = {
    "status": "failure",
    "code": 402,
    "message": "The daily points limit has been reached.",
}


def quota_exhausted_error(url="https://api.spoonacular.com/recipes/complexSearch"):
    """The 402 as urllib raises it, ready for a stub opener to throw."""
    body = io.BytesIO(json.dumps(QUOTA_EXHAUSTED).encode("utf-8"))
    return HTTPError(url, 402, "Payment Required", {"Content-Type": "application/json"}, body)


def shape_errors(expected, actual, path="$"):
    """Where `actual` fails to carry the shape `expected` describes.

    Keys and types only, never values, so the same comparator can be pointed at
    the live service without a word of anybody's recipe being written down. It
    is deliberately one-sided: the service may add fields and stay compatible,
    so extra keys pass and only a missing or retyped one is reported.

    Two allowances follow from what the service actually does. A null is not a
    shape failure - a recipe with no instructions is a thin recipe, not a
    renamed field - and an empty list is not either, since a search that
    matched nothing says nothing about the shape of what it would have
    returned. A test that needs results asserts that for itself.
    """
    if expected is None or actual is None:
        return []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected an object, got {_name(actual)}"]
        found = []
        for key, value in expected.items():
            if key not in actual:
                found.append(f"{path}.{key}: missing")
                continue
            found.extend(shape_errors(value, actual[key], f"{path}.{key}"))
        return found
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: expected a list, got {_name(actual)}"]
        if not expected or not actual:
            return []
        # One of each is enough to catch a rename, and cheap enough to run over
        # a live answer while someone waits for it.
        return shape_errors(expected[0], actual[0], f"{path}[0]")
    if isinstance(expected, bool):
        return [] if isinstance(actual, bool) else [f"{path}: expected a boolean,"
                                                    f" got {_name(actual)}"]
    if isinstance(expected, int | float):
        # int against float is not a difference worth failing a week's plan
        # over; the service returns whichever the number happens to be.
        ok = isinstance(actual, int | float) and not isinstance(actual, bool)
        return [] if ok else [f"{path}: expected a number, got {_name(actual)}"]
    if isinstance(expected, str):
        return [] if isinstance(actual, str) else [f"{path}: expected a string,"
                                                   f" got {_name(actual)}"]
    return []


def invented_text(value, exempt=TAXONOMY_KEYS, key=None):
    """Every string in a fixture that has to be made up, for the test that
    insists all of it is.

    Collected by default and exempted by name, so a field nobody thought about
    is caught rather than missed. A string reached through a list carries the
    key the list hung from, since an `instructions` expressed as a list of
    steps is as much the service's prose as one expressed as a paragraph.
    """
    found = []
    if isinstance(value, dict):
        for inner_key, inner in value.items():
            found.extend(invented_text(inner, exempt, inner_key))
    elif isinstance(value, list):
        for item in value:
            found.extend(invented_text(item, exempt, key))
    elif isinstance(value, str) and value.strip() and key not in exempt:
        found.append(value)
    return found


def _name(value):
    """What a thing is, for a complaint a person has to read."""
    return "null" if value is None else type(value).__name__
