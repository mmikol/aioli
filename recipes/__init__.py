"""The recipes package: the one way out to Spoonacular, and nothing kept.

Everything the service returns is fetched, used and dropped. What the
household owns - the pantry, the plan, the history - lives in the database;
a recipe never does (docs/db.md). The fixtures beside the client are
invented to the shape of the API for the same reason: a recorded response
is recipe data, and recipe data may not be kept.
"""
